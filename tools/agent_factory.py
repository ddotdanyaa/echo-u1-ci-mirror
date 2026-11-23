"""Small, auditable task queue for optional Kilo workers; no model/network I/O.

This package intentionally does NOT deploy, merge, read Google keys, or pretend
that a worktree isolates files from the operating system. State transitions are
fenced with lease tokens and always require independent acceptance.
"""
from __future__ import annotations

import contextlib
import logging
from dataclasses import dataclass
from hashlib import sha1, sha256
from pathlib import Path, PurePosixPath
import json
import os
import re
import tempfile
import time
import uuid
import unicodedata
import xml.etree.ElementTree as ET

STATES = frozenset(("READY", "RUNNING", "REVIEW", "DONE", "PROMOTED", "FAILED", "BLOCKED"))
SATISFIED = frozenset(("DONE", "PROMOTED"))  # dependency is met
REFEED_SUFFIX = "_g"   # id suffix of the guard-backed re-feed of a failed row (tools.factory_autofeed.refeed_rows)
MAX_RESLICES = 2
RESLICE_AFTER = 2
RESLICE_ID = re.compile(r"_r\d+(?:_test)?$")
CONTRACT_MAX = 32000     # room for test.new.code (up to 8000 characters)
REASON_CLOUD_DOWN = "cloud_down"
REASON_CLOUD_BUSY = "cloud_busy"
SLICER_FILES: tuple[str, ...] = ("factory_architect.py", "factory_cards.py", "agent_factory_import.py")
_slicer_version: str | None = None


def slicer_version() -> str:
    """Fingerprint the slicer's source once per process."""
    global _slicer_version
    if _slicer_version is None:
        digest = sha1()
        for name in SLICER_FILES:
            path = Path(name)
            if not path.is_absolute():
                path = Path(__file__).parent / path
            try:
                digest.update(path.read_bytes())
            except FileNotFoundError:
                continue
        _slicer_version = "s" + digest.hexdigest()[:10]
    return _slicer_version


def is_terminal(reason: str | None) -> bool:
    return bool(reason and (reason == "quarantine" or
                           reason.startswith(("superseded", "closed", "not_code", "sliced"))))


def row_of(backlog_id: str) -> str:
    return backlog_id.split("#")[0]


def call_cap(parts: int = 1) -> int:
    return 2 * (max(1, parts) * 3 + 4)


FEEDBACK_SOURCES = frozenset(("gate", "review", "opus"))
MAX_STRIKES = 6   # 21.11 (was 3): the line a quarantine needs. A plain red (gate/review/no effect) is a retry and saturates one below it
UNSAFE_STRIKE = 2  # strikes one unsafe rejection counts (MAX_STRIKES // 3: three unsafe candidates quarantine)
GOAL_MAX = 6000  # 21.11: the task text a coder gets, same as the triage MAX_TEXT (was 1500)
MAX_ATTEMPTS = 6  # 21.11 (was 3 in the loop, 2 here): attempts of one task; each next one on another model where the router allows
# <id> (owner: «пока есть задачи, петля не стоит в HOLD дольше 5 минут ... у каждого запрета или блокировки есть причина
# и срок»): every BLOCKED row has a reason and a term; the loop lifts an expired block itself, AUTO_UNBLOCK_MAX times per
# task (shared with the new-version requeue ledger), then escalates. The term is fixed, not growing: a growing term
# would keep the loop in HOLD longer than 5 minutes when one blocked task is all that is left.
BLOCK_TERM_S = 300.0
AUTO_UNBLOCK_MAX = 6   # 21.11 (was 3)
OWNER_RULES = frozenset(("private", "only_opus"))   # the owner's rules: the only blocks without a term
LEASE_LIFETIME_S = 1800.0   # one lease length: acquire() and the stale work-copy cleanup share it
FEEDBACK_KEEP = 3
FEEDBACK_MAX_CHARS = 2000
REPEAT_MARK = "не повторяй:"   # the loop's line for a rejection seen again (factory_loop._learn_from_run)
DENY_PARTS = frozenset((".env", ".git", ".kilo", ".ssh", "secrets", "private",
                        "transcripts", "credentials", "tokens", "recordings",
                        "__pycache__", "node_modules", "materials", "kilo.jsonc", "kilo.json", "opencode.jsonc", "opencode.json",
                        "agents.md"))   # the agent-config file rule lives here only (compared lower-case)
SECRET = re.compile(
    r"(?:AIza[A-Za-z0-9_-]{20,}|sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|"
    r"gsk_[A-Za-z0-9]{20,}|xai-[A-Za-z0-9_-]{20,}|hf_[A-Za-z0-9]{20,}|"
    r"AQ\.[A-Za-z0-9_-]{20,}|(?i:bearer)\s+[A-Za-z0-9._~+/=-]{16,}|"
    r"(?<![0-9])[0-9]{8,10}:[A-Za-z0-9_-]{35}(?![A-Za-z0-9_-])|"
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----|"
    r"(?i:password|api[_-]?key|client_secret)\s*[:=]\s*(?:['\x22][^\x22']{8,}['\x22]|[A-Za-z0-9_.-]{8,})(?:\s|$))"
)
# Redaction for free text (feedback, logs). Broader than SECRET: SECRET also guards
# source files, where e-mail addresses and user paths are legitimate content.
REDACT_EXTRA = re.compile(
    # NAME_KEY=value, *_TOKEN=value, *_SECRET=value (value >= 8 chars), free text only
    r"(?i:[A-Za-z][A-Za-z0-9_]{0,63}_(?:key|token|secret))\s*=\s*['\"]?[^\s'\"]{8,}['\"]?|"
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}|"
    r"[A-Za-z]:[\\/]+Users[\\/]+[^\\/\s\"'<>|:]+"
)
# 21.11 (owner): the ONLY private class is passwords, API keys, tokens, .env, SECRETS_LOCAL, call recordings and call
# logs. A task whose title/goal names one is never sent to a free model (privacy_safe False); everything else is
# sendable. Words about call LOGIC, the owner, proxy, backlog ids or times are code work, not private. The importer
# classifies the rows first (agent_factory_import.PRIVATE); this regex is the same class as a second, narrow net.
PRIVATE_CLASS = re.compile(
    r"(?i)(?:\.env\b|secrets?[_ -]?local|\bpasswords?\b|парол\w*|"
    r"\bapi[ _-]?keys?\b|\b(?:private|secret|access)\s+keys?\b|(?:секретн|приватн)\w*\s+ключ\w*|ключ\w*\s+api\b|\bapi[ _-]?ключ\w*|"
    r"\b(?:auth|access|bearer|api|bot|oauth|secret|refresh)[ _-]?tokens?\b|токен\w*\s+(?:доступа|бота|авторизац\w*)|"
    r"\b(?:call|звон)\w*\s+(?:recordings?|logs?|audio|transcripts?|запис(?:и|ь|ей)|журнал\w*|логи?|логов|аудио|"
    r"транскрипт\w*)\b|"
    r"\b(?:recordings?|logs?|transcripts?)\s+of\s+(?:the\s+)?calls?\b|"
    r"\b(?:запис(?:и|ь|ей)|журнал\w*|логи?|логов|аудио\w*|транскрипт\w*)\s+звон\w*)"
)


def is_private_text(text: str) -> bool:
    """The text names the owner's private class (PRIVATE_CLASS): such a task never goes to a free model."""
    return bool(PRIVATE_CLASS.search(str(text or "")[:20_000]))


WINDOWS_DEVICE = re.compile(r"^(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?$", re.I)
TASK_ID = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{0,63}$")
PORT_SHA = re.compile(r"^[0-9a-f]{7,40}$")   # Task.port_from: an abbreviated or full commit id, nothing else
# provider/model or provider/vendor/model (OpenRouter); no segment may be only dots ('..').
# 0 RUB guard: an openrouter model must end with ":free" (a paid id is not a model of this project).
MODEL_ID = re.compile(r"^(?:(?!(?i:openrouter)/)|(?=.*:free$))(?!\.+/)[a-zA-Z0-9._-]+/(?:(?!\.+/)[a-zA-Z0-9._-]+/)?(?!\.+$)[a-zA-Z0-9._:-]+$")


LOCK_EVENTS: list[dict] = []  # journal of lock housekeeping (stale lock removed, ...)
LOCK_STALE_S = 120.0
LOCK_OWNER = "owner"   # <lock>.lockdir/owner = the holder's pid: a dead holder's lock is stale at once
_log = logging.getLogger(__name__)


class InvalidPlan(ValueError):
    pass


class BudgetExhausted(InvalidPlan):
    """The daily model-call budget is spent (resets at local midnight)."""


class LockBusy(InvalidPlan, OSError):
    """The state lock stayed with a live holder past the wait."""


class StaleLease(InvalidPlan):
    """The row's lease is not the caller's any more: it expired and was released, or the pass was settled elsewhere."""


class InputTooLarge(InvalidPlan):
    """A source over SOURCE_MAX_BYTES: a resource limit (the task blocks as context_too_large), never a scope violation."""


def safe_path(value: str) -> str:
    """Fail closed on traversal, hidden/system secrets, odd Windows filenames."""
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        raise InvalidPlan("unsafe path")
    if any(ord(ch) < 32 or ord(ch) == 127 or unicodedata.category(ch) == "Cf"
           for ch in value):
        raise InvalidPlan("control or bidi formatting in filename")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or value != path.as_posix():
        raise InvalidPlan("noncanonical path")
    if any(part in ("", ".", "..") or part.startswith(".") or part.lower() in DENY_PARTS
           or part.rstrip(" .") != part or WINDOWS_DEVICE.fullmatch(part)
           or any(c in part for c in '<>|?*"\x00') for part in path.parts):
        raise InvalidPlan("excluded path")
    return value


@dataclass(frozen=True)
class Task:
    id: str
    title: str
    depends_on: tuple[str, ...]
    touch_files: tuple[str, ...]
    read_files: tuple[str, ...]
    tests: tuple[str, ...]
    privacy_safe: bool
    estimated_tokens: int
    only_opus: bool = False
    context_targets: tuple[tuple[str, str], ...] = ()
    task_type: str = 'patch'
    context_budget: int = 8000
    backlog_id: str = ""
    priority: int = 5
    kind: str = "code"  # "code" | "unit_test" (creates its own test file)
    goal: str = ""      # the backlog row text the coder works from (<= GOAL_MAX chars)
    port_from: str = ""  # a port task: the old-branch commit whose behaviour it brings over (its diff is a reference)

    contract: str = ""

    @property
    def scope(self) -> frozenset[str]:
        return frozenset(p.casefold() for p in self.touch_files)


def _parse_priority(value: object) -> int:
    """<id>..P4 (or an int 0..9); smaller runs first."""
    if type(value) is int and 0 <= value <= 9:
        return value
    if isinstance(value, str) and re.fullmatch(r"P[0-9]", value):
        return int(value[1])
    raise InvalidPlan("invalid priority")


def read_plan(plan: object) -> dict[str, Task]:
    """Tasks require explicit scope, dependencies and privacy classification.

    21.11: a task is private only when the row says so or its title/goal names the owner's private class
    (passwords, keys, tokens, .env, SECRETS_LOCAL, call recordings and logs: PRIVATE_CLASS); a private task is
    never sent to a free third-party model. A row without privacy_safe is sendable otherwise.
    """
    data = plan.get("tasks") if isinstance(plan, dict) else plan
    if not isinstance(data, list):
        raise InvalidPlan("plan must contain a tasks list")
    result: dict[str, Task] = {}
    for row in data:
        if not isinstance(row, dict) or not TASK_ID.fullmatch(str(row.get("id", ""))):
            raise InvalidPlan("invalid id")
        tid = row["id"]
        if tid in result:
            raise InvalidPlan("duplicate id")
        title = row.get("title")
        if not isinstance(title, str) or not title.strip() or len(title) > 240:
            raise InvalidPlan("invalid title")
        fields = {}
        for k in ("depends_on", "touch_files", "read_files", "tests"):
            val = row.get(k, [])
            if not isinstance(val, list) or not all(isinstance(v, str) for v in val):
                raise InvalidPlan("invalid " + k)
            if len(val) != len({p.casefold() for p in val}):
                raise InvalidPlan("duplicated or case-aliased " + k)
            fields[k] = tuple(val)
        files = {k: tuple(safe_path(p) for p in fields[k])
                 for k in ("touch_files", "read_files", "tests")}
        if not files["touch_files"]:
            raise InvalidPlan("task has no writing scope")
        if not files["tests"]:
            raise InvalidPlan("task has no tests")
        if any(not p.startswith("tests/") or not p.endswith(".py") or
               not PurePosixPath(p).name.startswith("test_") for p in files["tests"]):
            raise InvalidPlan("pytest scope must be named tests/test_*.py")
        work_kind = row.get("kind", "code")
        if work_kind == "unit_test":
            # The task creates its own test file (it may not exist yet).
            if set(files["touch_files"]) != set(files["tests"]):
                raise InvalidPlan("unit_test task must touch exactly its tests")
        elif work_kind == "code":
            if ({p.casefold() for p in files["touch_files"]} &
                    {p.casefold() for p in files["tests"]}):
                raise InvalidPlan("code task must not edit its own tests")
        else:
            raise InvalidPlan("invalid kind")
        if "privacy_safe" in row and type(row["privacy_safe"]) is not bool:
            raise InvalidPlan("privacy_safe is boolean")
        size = row.get("estimated_tokens", 0)
        if type(size) is not int or not 0 <= size <= 10_000_000:
            raise InvalidPlan("token estimate invalid")
        opus = row.get('only_opus', False)
        targets = row.get('context_targets', {})
        budget = row.get('context_budget', 8000)
        kind = row.get('task_type', 'patch')
        if type(opus) is not bool or not isinstance(targets, dict):
            raise InvalidPlan('invalid Opus/context contract')
        if type(budget) is not int or not 100 <= budget <= 150000:
            raise InvalidPlan('invalid context budget')
        if kind not in ('patch', 'traceback', 'unit_test', 'multifile', 'review', 'logs'):
            raise InvalidPlan('invalid task type')
        backlog_id = row.get("backlog_id", "")
        if (not isinstance(backlog_id, str) or len(backlog_id) > 64 or
                any(ord(c) < 32 for c in backlog_id)):
            raise InvalidPlan("invalid backlog_id")
        priority = _parse_priority(row.get("priority", 5))
        goal = row.get("goal", "")
        if not isinstance(goal, str):
            raise InvalidPlan("goal must be a string")
        goal = goal.strip()[:GOAL_MAX]
        port_from = row.get("port_from", "")
        if not isinstance(port_from, str) or (port_from and not PORT_SHA.fullmatch(port_from)):
            raise InvalidPlan("port_from must be a commit sha")
        contract = row.get("contract", "")
        if not isinstance(contract, str) or len(contract) > CONTRACT_MAX:
            raise InvalidPlan("invalid contract")
        if contract:
            try:
                parsed_contract = json.loads(contract)
            except ValueError as exc:
                raise InvalidPlan("contract must be a JSON object") from exc
            if not isinstance(parsed_contract, dict):
                raise InvalidPlan("contract must be a JSON object")
        scope = set(files['touch_files'] + files['read_files'] + files['tests'])
        if any(k not in scope or not isinstance(v, str) for k, v in targets.items()):
            raise InvalidPlan('context target outside approved files')
        result[tid] = Task(tid, title.strip(), fields["depends_on"],
                           files["touch_files"], files["read_files"], files["tests"],
                           row.get("privacy_safe", True) and not is_private_text(title + "\n" + goal), size, opus,
                           tuple(sorted(targets.items())), kind, budget,
                           backlog_id, priority, work_kind, goal, port_from, contract)
    for task in result.values():
        if any(d not in result or d == task.id for d in task.depends_on):
            raise InvalidPlan("missing/self dependency")
    # Kahn's cycle test: fail before allocating work.
    visited: set[str] = set()
    def visit(tid: str, stack: frozenset[str]):
        if tid in stack:
            raise InvalidPlan("dependency cycle")
        if tid not in visited:
            for dep in result[tid].depends_on:
                visit(dep, stack | {tid})
            visited.add(tid)
    for tid in result:
        visit(tid, frozenset())
    return result


def _row_for(task: Task) -> dict:
    return {"status": "READY", "attempts": 0, "lease": None, "deadline": None,
            "evidence": None, "backlog_id": task.backlog_id,
            "kind": task.kind}


def initial_state(tasks: dict[str, Task]) -> dict:
    return {
        "schema": 1,
        "deploy_blocked": True,  # never equivalent to stopping development
        "max_model_calls": 10,
        "model_calls": 0,
        "strikes": {},
        "infra_streak": 0,
        "tasks": {tid: _row_for(task) for tid, task in tasks.items()},
    }


def sync_state(tasks: dict[str, Task], state: dict) -> dict:
    """Plan may grow: new tasks join as READY. Tasks may never disappear."""
    if not isinstance(state, dict) or state.get("schema") != 1 or \
            not isinstance(state.get("tasks"), dict):
        raise InvalidPlan("unknown checkpoint schema")
    if set(state["tasks"]) - set(tasks):
        raise InvalidPlan("task/checkpoint mismatch")
    state.setdefault("strikes", {})
    state.setdefault("infra_streak", 0)
    for tid, task in tasks.items():
        row = state["tasks"].get(tid)
        if row is None:
            row = state["tasks"][tid] = _row_for(task)
            if is_quarantined(state, task.backlog_id):
                row.update(status="FAILED", reason="quarantine", q_ver=slicer_version())
        elif isinstance(row, dict):
            for k, v in _row_for(task).items():
                if k not in ("status", "attempts", "lease", "deadline", "evidence"):
                    row.setdefault(k, v)
        if isinstance(row, dict) and row.get("status") == "BLOCKED" and "block_until" not in row:
            # a block written before <id> had no term: a passed defer term is its term (<id>, gate_unknown, stayed
            # BLOCKED 824 min after its «отложить до»), else one term from now
            nb = row.get("not_before")
            _block(row, row.get("blocked_reason") or "unknown", time.time(),
                   until=float(nb) if type(nb) in (int, float) else None)
    return state


def validate_state(tasks: dict[str, Task], state: dict) -> None:
    if not isinstance(state, dict) or state.get("schema") != 1:
        raise InvalidPlan("unknown checkpoint schema")
    if not isinstance(state.get("tasks"), dict) or set(state["tasks"]) != set(tasks):
        raise InvalidPlan("task/checkpoint mismatch")
    for row in state["tasks"].values():
        fb = row.get("feedback", [])
        if not isinstance(fb, list) or len(fb) > FEEDBACK_KEEP or any(
                not isinstance(x, dict) or not isinstance(x.get("source"), str) or
                x["source"] not in FEEDBACK_SOURCES or
                not isinstance(x.get("text"), str) or
                len(x["text"]) > FEEDBACK_MAX_CHARS for x in fb):
            raise InvalidPlan("invalid feedback")
        if row.get("status") not in STATES or type(row.get("attempts")) is not int:
            raise InvalidPlan("invalid state")
        if row["attempts"] < 0:
            raise InvalidPlan("negative attempts")
        if row["status"] == "RUNNING":
            if (not isinstance(row.get("lease"), str) or
                not re.fullmatch(r"[a-f0-9]{32}", row["lease"]) or
                type(row.get("deadline")) not in (int, float) or
                row["deadline"] <= 0 or row["attempts"] == 0):
                raise InvalidPlan("RUNNING task has no verifiable lease/deadline")
        elif row.get("lease") is not None or row.get("deadline") is not None:
            raise InvalidPlan("inactive task still holds lease")
        began = row.get("began")
        if began is not None and (row["status"] != "RUNNING" or not isinstance(began, dict)
                                  or type(began.get("pid")) is not int or type(began.get("booked")) is not int
                                  or began["booked"] < 0):
            raise InvalidPlan("began belongs to a running task only")
        if row["status"] == "BLOCKED":
            if not isinstance(row.get("blocked_reason"), str) or not row["blocked_reason"].strip():
                raise InvalidPlan("BLOCKED task has no reason")
            if row["blocked_reason"] not in OWNER_RULES and type(row.get("block_until")) not in (int, float):
                raise InvalidPlan("BLOCKED task has no term (block_until)")
    if type(state.get("max_model_calls")) is not int or type(state.get("model_calls")) is not int:
        raise InvalidPlan("invalid budget")
    if state["max_model_calls"] < 0 or state["model_calls"] < 0:
        raise InvalidPlan("negative budget")
    strikes = state.get("strikes", {})
    if not isinstance(strikes, dict) or any(type(v) is not int or v < 0 for v in strikes.values()):
        raise InvalidPlan("invalid strikes")
    if type(state.get("infra_streak", 0)) is not int or state.get("infra_streak", 0) < 0:
        raise InvalidPlan("invalid infra streak")


def stuck_rows(state, tasks) -> dict[str, list[str]]:
    """Current-generation failures, grouped by the whole backlog row."""
    grouped = {}
    for tid, task in tasks.items():
        bid = row_of(task.backlog_id or tid)
        grouped.setdefault(bid, []).append(tid)
    result = {}
    rows = state["tasks"]
    for bid, ids in grouped.items():
        if any(rows[t]["status"] in ("RUNNING", "REVIEW") for t in ids):
            continue
        def generation(t):
            match = re.search(r"_r(\d+)(?:_test)?$", t)
            return int(match[1]) if match else 0
        newest = max(map(generation, ids))
        current = [t for t in ids if generation(t) == newest]
        code = [t for t in current if tasks[t].kind == "code"]
        if code and all(rows[t]["status"] in SATISFIED for t in code):
            continue
        stuck = [t for t in current if (
            rows[t]["status"] == "FAILED" and not is_terminal(rows[t].get("reason"))) or (
            rows[t]["status"] == "READY" and any(
                rows.get(d, {}).get("status") == "FAILED" for d in tasks[t].depends_on))]
        if stuck:
            result[bid] = sorted(stuck)
    return result


def ready(tasks: dict[str, Task], state: dict, *, google: bool = True,
          occupied: tuple[str, ...] = (), now: float | None = None) -> list[str]:
    """Sorted tasks ready to execute, mutually compatible. Busy = RUNNING and REVIEW rows (a candidate holds its files
    until it is promoted). Exclusive = touch_files + tests, reads = read_files: two tasks never share an exclusive
    file, and one never writes what the other reads."""
    validate_state(tasks, state)
    now = time.time() if now is None else float(now)
    read_in_use = set()
    write_in_use = {(p.casefold(), None) for p in occupied}
    for tid, row in state["tasks"].items():
        if row["status"] in ("RUNNING", "REVIEW"):
            write_in_use.update(write_claims(tasks[tid]))
            read_in_use.update(p.casefold() for p in tasks[tid].read_files)
    found = []
    for tid in sorted(tasks, key=lambda t: (tasks[t].priority, t)):
        task = tasks[tid]
        if state["tasks"][tid]["status"] != "READY":
            continue
        if state['tasks'][tid].get('not_before', 0) > now:
            continue
        if google and (not task.privacy_safe or task.only_opus):
            continue
        reads = {p.casefold() for p in task.read_files}
        writes = write_claims(task)
        if _claims_clash(writes, write_in_use) or {f for f, _ in writes} & read_in_use \
                or reads & {f for f, _ in write_in_use}:
            continue
        if all(state["tasks"][dep]["status"] in SATISFIED for dep in task.depends_on):
            found.append(tid)
            write_in_use.update(writes)
            read_in_use.update(reads)
    return found


def write_claims(task: Task) -> set[tuple[str, str | None]]:
    """What a task books for writing: (file, None) is the whole file; (file, function) only that function. A task with
    a contract books the pairs "file + function" of its parts; a part with an anchor or without symbols, a test file
    and a file the contract does not name book the whole file."""
    whole = {p.casefold() for p in task.touch_files + task.tests}
    by_file: dict[str, set[str] | None] = {}
    if task.contract:
        try:
            parts = json.loads(task.contract).get("parts") or []
        except (ValueError, AttributeError):
            parts = []
        for part in parts:
            if not isinstance(part, dict) or not isinstance(part.get("file"), str):
                continue
            name = part["file"].casefold()
            symbols = part.get("symbols") or []
            if part.get("anchor") or not symbols:
                by_file[name] = None
            elif by_file.get(name, set()) is not None:
                by_file.setdefault(name, set()).update(str(s) for s in symbols)
    claims = set()
    for name in whole:
        symbols = by_file.get(name)
        if symbols:
            claims.update((name, s) for s in symbols)
        else:
            claims.add((name, None))
    return claims


def _claims_clash(claims, in_use) -> bool:
    for name, symbol in claims:
        for other, other_symbol in in_use:
            if name == other and (symbol is None or other_symbol is None or _symbols_overlap(symbol, other_symbol)):
                return True
    return False


def _symbols_overlap(a: str, b: str) -> bool:
    """The same name, or one inside the other: a class ``Foo`` holds its method ``Foo.bar``."""
    return a == b or a.startswith(b + ".") or b.startswith(a + ".")


def acquire(tasks: dict[str, Task], state: dict, tid: str, *,
            now: float | None = None, lifetime: float = LEASE_LIFETIME_S,
            charge: bool = True) -> str:
    """Single-writer checkpoint must be locked by caller before mutation.

    charge=True keeps the legacy behaviour (one model call is spent on lease);
    charge=False leaves spending to charge_call() at the moment of the call.
    """
    now = time.time() if now is None else float(now)
    _roll_budget(state, now)
    if tid not in ready(tasks, state, now=now):
        raise InvalidPlan("not runnable")
    if state["model_calls"] >= state["max_model_calls"]:
        raise BudgetExhausted("budget exhausted")
    token = uuid.uuid4().hex
    row = state["tasks"][tid]
    row.update(status="RUNNING", attempts=row["attempts"] + 1,
               lease=token, deadline=now + lifetime)
    if charge:
        state["model_calls"] += 1
    return token


def fence(state: dict, tid: str, token: str) -> None:
    """The lease of ``tid`` is still ``token``'s: the row is RUNNING under it. StaleLease otherwise (the lease expired and
    was released, or another writer settled the pass): a stale pass writes nothing."""
    row = state["tasks"].get(tid)
    if not isinstance(row, dict) or row.get("status") != "RUNNING" or row.get("lease") != token:
        raise StaleLease("stale/foreign lease")


def begin(state: dict, tid: str, token: str, pid: int) -> None:
    """The pass of ``token`` started its work in process ``pid``: from here its lease stays until the pass ends."""
    fence(state, tid, token)
    state["tasks"][tid]["began"] = {"pid": int(pid), "booked": 0}


def unclaim(state: dict, tid: str, token: str) -> None:
    """The exact inverse of acquire(charge=False) for a pass that died before it began: READY, the attempt back."""
    fence(state, tid, token)
    row = state["tasks"][tid]
    if "began" in row:
        raise InvalidPlan("the pass began: its lease stays until it ends")
    row.update(status="READY", attempts=max(0, row["attempts"] - 1), lease=None, deadline=None)


def settle(state: dict, tid: str, token: str, *,
           tests_ok: bool, evidence: str, max_attempts: int = MAX_ATTEMPTS,
           strike: bool = True, unsafe: bool = False, failed_models=(), reslice_after: int = 0) -> str:
    """Fenced completion. Green requires manual review, never auto-DONE.

    A red result is a strike by backlog_id unless strike=False (channel/provider
    faults are not the candidate's fault). ``unsafe`` (a weakened check, a frozen file rewritten): the strike
    counts UNSAFE_STRIKE; a plain red never reaches the quarantine line (add_strike). ``failed_models``: the models whose
    candidates were rejected; the next attempt starts on another one (failed_models_of). If the task's backlog_id is
    already quarantined when it settles, it ends FAILED(quarantine) even when green."""
    fence(state, tid, token)
    row = state["tasks"][tid]
    if not isinstance(evidence, str) or not re.fullmatch(r"[0-9a-f]{64}", evidence):
        raise InvalidPlan("expected SHA256 digest of local test receipt")
    next_status = ("REVIEW" if tests_ok else
                   ("READY" if row["attempts"] < max_attempts else "FAILED"))
    row.update(status=next_status, lease=None, deadline=None, evidence=evidence)
    row.pop("began", None)
    row.pop("defer_streak", None)
    row.pop("orphan_releases", None)    # the pass ended: a series of restarts during its passes is over
    if tests_ok and isinstance(row.get("pending_review"), dict):
        row["candidate"] = dict(row["pending_review"])   # kept while the row is in REVIEW: a requeue may resume it
    if not tests_ok and strike:
        # A strike is only a candidate failing the gate/reviewer (never a channel fault).
        add_strike(state, tid, unsafe=unsafe)
        note_failed_models(row, failed_models)
        row["reds"] = row.get("reds", 0) + 1
        if reslice_after and row["reds"] >= reslice_after:
            next_status = "FAILED"
            row.update(status="FAILED", reason="reslice")
    if state.get("strikes", {}).get(_strike_key(row, tid), 0) >= MAX_STRIKES:
        next_status = "FAILED"
        row.update(status="FAILED", reason="quarantine", q_ver=slicer_version())
    elif next_status == "REVIEW":
        row["reviewed_at"] = time.time()
        row["lease_expiries"] = 0
    if row["status"] != "REVIEW":
        row.pop("candidate", None)
    return next_status


def fail_row(state: dict, tid: str, token: str, reason: str) -> str:
    """Return an unusable contract to the slicer without charging a strike."""
    if reason not in {"reslice", "reslice:stale"}:
        raise InvalidPlan("invalid fail_row reason")
    fence(state, tid, token)
    row = state["tasks"][tid]
    row.update(status="FAILED", reason=reason, lease=None, deadline=None)
    for key in ("began", "candidate", "pending_review", "defer_streak", "orphan_releases"):
        row.pop(key, None)
    return "FAILED"


def _strike_key(row: dict, tid: str) -> str:
    return "bl:" + row["backlog_id"] if row.get("backlog_id") else "task:" + tid


FAILED_MODELS_KEEP = 8   # distinct models remembered per task (the pool of free models is not much bigger)


def note_failed_models(row: dict, models) -> None:
    """Remember the models whose candidates were rejected (newest last, distinct, FAILED_MODELS_KEEP at most): the
    next attempt of the task starts on another model where the router has one (failed_models_of)."""
    seen = [m for m in (row.get("coder_failed") or []) if isinstance(m, str)]
    for model in models or ():
        if isinstance(model, str) and model and len(model) <= 120:
            seen = [m for m in seen if m != model] + [model]
    if seen:
        row["coder_failed"] = seen[-FAILED_MODELS_KEEP:]


def failed_models_of(row: dict) -> list[str]:
    """The models that already failed this task (never raises on a hand-edited row)."""
    models = row.get("coder_failed") if isinstance(row, dict) else None
    return [m for m in models if isinstance(m, str)] if isinstance(models, list) else []


UNSAFE_REJECTS = ("weakening", "gate: immutable file")   # the reasons the runner's reject() gives for an unsafe candidate


def is_unsafe_reject(reason: str) -> bool:
    """A rejection reason of the unsafe class: a weakened check or a frozen file rewritten by the candidate. The one
    class that quarantines a task (add_strike); every other red is a retry. A secret in a candidate and a forbidden
    path never reach a rejection: inspect_changes raises and the pass BLOCKS (scope_violation)."""
    return str(reason or "").startswith(UNSAFE_REJECTS)


def strikes_for(state: dict, backlog_id: str) -> int:
    return int(state.get("strikes", {}).get("bl:" + backlog_id, 0))


def is_quarantined(state: dict, backlog_id: str) -> bool:
    return bool(backlog_id) and strikes_for(state, backlog_id) >= MAX_STRIKES


def add_strike(state: dict, tid: str, *, unsafe: bool = False) -> int:
    """Global strike keyed "bl:<backlog_id>" (or "task:<id>" when empty). MAX_STRIKES =>
    quarantine: READY/BLOCKED tasks of that key become FAILED(quarantine); REVIEW
    is left alone (it already passed the gates and is being merged); a RUNNING
    one is failed when it settles. Returns the new count.
    21.11: only UNSAFE rejections (a weakened check, a frozen file rewritten) reach the quarantine line, each one
    counts UNSAFE_STRIKE (three in a row quarantine; the next attempt runs on another model meanwhile); a plain red
    (gate, review, no effect) counts up to MAX_STRIKES - 1 and stops there: it is a retry (the attempts cap ends the
    task as an ordinary FAILED that the loop requeues), not a quarantine."""
    row = state["tasks"][tid]
    key = _strike_key(row, tid)
    strikes = state.setdefault("strikes", {})
    now = strikes.get(key, 0)
    if unsafe or now >= MAX_STRIKES:
        strikes[key] = now + UNSAFE_STRIKE
    else:
        strikes[key] = min(now + 1, MAX_STRIKES - 1)
    if strikes[key] >= MAX_STRIKES:
        for other, orow in state["tasks"].items():
            if (_strike_key(orow, other) == key and
                    orow["status"] in ("READY", "BLOCKED")):
                orow.update(status="FAILED", reason="quarantine", q_ver=slicer_version(), blocked_reason=None)
                _clear_block(orow)
    return strikes[key]


def _block(row: dict, reason: str, now: float, *, until: float | None = None) -> None:
    """The one way a row becomes BLOCKED: a reason and a term (blocked_at, block_until = now + BLOCK_TERM_S, or
    ``until``). An owner's rule (OWNER_RULES) has no term. The term replaces a defer term (not_before)."""
    reason = str(reason or "unknown")
    now = float(now)
    row.update(status="BLOCKED", blocked_reason=reason, lease=None, deadline=None, blocked_at=now,
               block_until=None if reason in OWNER_RULES else (float(until) if until is not None
                                                                else now + BLOCK_TERM_S))
    row.pop("not_before", None)


def _clear_block(row: dict) -> None:
    for key in ("blocked_at", "block_until"):
        row.pop(key, None)


def escalate(state: dict, tid: str) -> str:
    """The block of ``tid`` expired after AUTO_UNBLOCK_MAX automatic lifts: FAILED escalated:<reason>, for Opus and
    the backlog; the loop never lifts it again. Returns the new reason."""
    row = state["tasks"][tid]
    if row["status"] != "BLOCKED":
        raise InvalidPlan("task is not blocked")
    reason = ("escalated:" + str(row.get("blocked_reason") or "unknown"))[:80]
    row.update(status="FAILED", reason=reason, blocked_reason=None)
    _clear_block(row)
    return reason


PARK_REASONS = frozenset(("runner_no_result", "no_package", "promote_failed", "spec_not_testable"))


def park(state: dict, tid: str, reason: str, note: str, *, now: float | None = None) -> None:
    """The loop parks a task that can make no progress (the runner gives no result, a REVIEW has no
    package): BLOCKED with a whitelisted reason and a gate remark for Opus. Settled tasks only."""
    if reason not in PARK_REASONS:
        raise InvalidPlan("unknown park reason")
    row = state["tasks"][tid]
    if row["status"] not in ("READY", "RUNNING", "REVIEW"):
        raise InvalidPlan("only an unsettled task can be parked")
    _block(row, reason, time.time() if now is None else now)
    for key in ("pending_review", "candidate", "not_before", "orphan_releases", "began"):
        row.pop(key, None)
    add_feedback(state, tid, "gate", note)


def quarantine(state: dict, tid: str, token: str, *, reason: str, now: float | None = None) -> None:
    """Fail closed after unknown descendant, invalid auth, repeated 429, or unsafe worker.

    Never retry an uncertain process or a locked provider in the next batch.
    """
    allowed = {"worker_timeout", "provider_auth", "all_channels_throttled",
               "provider_unavailable", "unsafe_windows_launcher",
               "worker_exception", "scope_violation", "already_green",
               "context_too_large", "no_independent_reviewer", "gate_unknown",
               "provider_error", "no_diff", "reviewer_failed", "off_path", "review_chain_short",
               "cannot_repeat"}
    if reason not in allowed:
        raise InvalidPlan("unknown quarantine reason")
    fence(state, tid, token)
    row = state["tasks"][tid]
    row.pop("pending_review", None)  # a blocked task must not resume a stale candidate
    row.pop("orphan_releases", None)
    row.pop("began", None)
    _block(row, reason, time.time() if now is None else now)
    row["evidence"] = sha256(reason.encode("utf-8")).hexdigest()


DEFER_REASONS = frozenset((REASON_CLOUD_DOWN, REASON_CLOUD_BUSY, "rate_minute", "rate_day", "transient", "network", "region", "key_invalid",
                           "balance", "model_missing",
                           "provider_error", "gate_unknown", "no_independent_reviewer",
                           "channel_wait", "reviewer_failed", "budget_exhausted", "os_error",
                           "review_chain_short",   # one critic approved, no other model now: the candidate waits
                           "env_shortage",    # no slot / RAM: never a strike, never a block
                           "off_path"))      # the failing test runs a module outside the task: the loop widens it


def defer(state: dict, tid: str, token: str, reason: str, seconds: float, *,
          now: float | None = None) -> str:
    """RUNNING -> READY without a strike and without spending the attempt; the task is
    postponed to now + seconds. For channel/provider/infrastructure faults and waits, never
    for a candidate that failed a gate. ``reason`` must be whitelisted (no free text)."""
    if reason not in DEFER_REASONS:
        raise InvalidPlan("unknown defer reason")
    fence(state, tid, token)
    row = state["tasks"][tid]
    row.pop("began", None)
    now = time.time() if now is None else float(now)
    streak = row.get("defer_streak")
    if not isinstance(streak, dict):
        streak = {}
    row.update(status="READY", lease=None, deadline=None,
               attempts=max(0, row["attempts"] - 1),
               not_before=now + max(0.0, float(seconds)), defer_reason=reason,
               defer_streak={"reason": reason,
                             "n": (streak["n"] if type(streak.get("n")) is int else 0) + 1
                             if streak.get("reason") == reason else 1},
               evidence=sha256(reason.encode("utf-8")).hexdigest())
    row.pop("orphan_releases", None)
    if state.get("strikes", {}).get(_strike_key(row, tid), 0) >= MAX_STRIKES:
        row.update(status="FAILED", reason="quarantine", q_ver=slicer_version())
    return row["status"]


def defer_streak(state: dict, tid: str, reason: str) -> int:
    """How many deferrals for ``reason`` in a row this task already had (settle/unblock reset it)."""
    streak = state["tasks"][tid].get("defer_streak")
    if not isinstance(streak, dict) or streak.get("reason") != reason or type(streak.get("n")) is not int:
        return 0
    return streak["n"]


def seconds_to_local_midnight(now: float | None = None) -> float:
    now = time.time() if now is None else float(now)
    here = time.localtime(now)
    return max(60.0, 86400.0 - (here.tm_hour * 3600 + here.tm_min * 60 + here.tm_sec))


def _roll_budget(state: dict, now: float) -> None:
    """max_model_calls is a DAILY budget: the counter resets at local midnight."""
    today = time.strftime("%Y-%m-%d", time.localtime(now))
    if state.get("budget_day") is None:
        state["budget_day"] = today
    elif state["budget_day"] != today:
        state.update(budget_day=today, model_calls=0)


def accept(state: dict, tid: str, *, reviewer: str) -> None:
    """Manual acceptance by Opus/a human: REVIEW -> DONE. (The factory's own merge
    into the branch is mark_promoted(): REVIEW -> PROMOTED.) Both statuses
    satisfy depends_on (SATISFIED)."""
    row = state["tasks"][tid]
    if row["status"] != "REVIEW" or not reviewer.strip():
        raise InvalidPlan("not reviewed")
    row["status"] = "DONE"
    row["reviewer"] = redact(reviewer)[:80]


ORPHAN_FREE_RELEASES = 2   # restarts in a row during one task's passes that are not counted against it


def release_expired(state: dict, now: float, *, orphan: bool = False, keep=()) -> list[str]:
    """RUNNING with an expired lease goes back to READY: no strike, the attempt is
    NOT refunded. The third expiry of one task blocks it (blocked_reason
    "lease_expired"), so a task that kills its worker cannot loop forever.
    ``orphan``: the lease of a pass the loop lost at a restart (no runner of the state can be alive): the first
    ORPHAN_FREE_RELEASES in a row are not the task's doing (no expiry counted, the attempt acquire() took comes
    back); from the next one in a row it is an ordinary expiry, so a task whose pass kills the loop every time
    still ends BLOCKED (critic 19.11 18:39). A pass that ends (settle, defer, quarantine, park) or Opus's unblock
    resets the series."""
    freed = []
    for tid, row in state["tasks"].items():
        if tid in keep:      # a worker of the pool still runs it: the loop ends that pass itself (kill + accounting)
            continue
        if row["status"] == "RUNNING" and row.get("deadline") is not None and row["deadline"] <= now:
            row.pop("began", None)
            if orphan:
                series = row.get("orphan_releases")
                row["orphan_releases"] = (series if type(series) is int and series > 0 else 0) + 1
                if row["orphan_releases"] <= ORPHAN_FREE_RELEASES:
                    row.update(status="READY", lease=None, deadline=None, attempts=max(0, row["attempts"] - 1))
                    freed.append(tid)
                    continue
            row["lease_expiries"] = row.get("lease_expiries", 0) + 1
            row.update(status="READY", lease=None, deadline=None)
            if row["lease_expiries"] >= 3:
                _block(row, "lease_expired", now if now < float("inf") else time.time())   # inf: the orphan sweep
            freed.append(tid)
    return freed


def mark_promoted(state: dict, tid: str, commit_sha: str) -> None:
    """Merge by the factory: REVIEW -> PROMOTED (manual Opus acceptance is accept()
    -> DONE). Only REVIEW may be promoted; PROMOTED satisfies depends_on like DONE."""
    row = state["tasks"][tid]
    if row["status"] != "REVIEW":
        raise InvalidPlan("only a reviewed candidate can be promoted")
    if not isinstance(commit_sha, str) or not re.fullmatch(r"[0-9a-f]{7,40}", commit_sha):
        raise InvalidPlan("commit sha expected")
    row.update(status="PROMOTED", commit=commit_sha)
    row.pop("candidate", None)
    if row.get("kind") == "unit_test" and row.get("backlog_id"):
        # the sub-task shares the strike key of its main task: its attempts must not eat theirs
        state.get("strikes", {}).pop("bl:" + row["backlog_id"], None)
        for other, orow in state["tasks"].items():   # quarantined by these strikes before it ever ran
            if (other != tid and orow.get("backlog_id") == row["backlog_id"] and orow.get("status") == "FAILED"
                    and orow.get("reason") == "quarantine" and not orow.get("attempts")):
                orow.update(status="READY", reason=None)


def unblock(state: dict, tid: str, note: str | None) -> None:
    """Opus lifts BLOCKED/FAILED. Attempts restart; the strikes of this task's
    backlog_id are reset too (Opus gives a new attempt with new instructions). ``note=None``: the loop's own lift
    after a block's term (<id>): no Opus note, since an Opus note hides the last failure from the coder
    (agent_factory_runner.fresh_feedback) and evicts gate remarks; the loop journals the lift itself."""
    row = state["tasks"][tid]
    if row["status"] not in ("BLOCKED", "FAILED"):
        raise InvalidPlan("task is not blocked")
    state.get("strikes", {}).pop(_strike_key(row, tid), None)
    row.update(status="READY", attempts=0, lease=None, deadline=None,
               blocked_reason=None, reason=None, lease_expiries=0, reds=0)
    _clear_block(row)
    row.pop("not_before", None)
    row.pop("pending_review", None)
    row.pop("candidate", None)
    row.pop("defer_streak", None)
    row.pop("orphan_releases", None)
    row.pop("coder_failed", None)      # new instructions: every model starts fresh
    if note is not None:
        add_feedback(state, tid, "opus", note)


def requeue(state: dict, tid: str, note: str, keep_candidate: bool = False) -> None:
    """REVIEW -> READY when the integration branch moved after the gate. No strike,
    the attempt is not spent; the note is kept as gate feedback (redacted).
    ``keep_candidate``: the approved candidate comes back as the task's pending review: the next pass resumes at the
    gates on the new base and makes no coder call."""
    row = state["tasks"][tid]
    if row["status"] != "REVIEW":
        raise InvalidPlan("only a reviewed candidate can be requeued")
    row.update(status="READY", attempts=max(0, row["attempts"] - 1))
    row.pop("reviewed_at", None)
    kept = row.pop("candidate", None)
    if keep_candidate and isinstance(kept, dict):
        row["pending_review"] = kept
    add_feedback(state, tid, "gate", note)


REDACT_INPUT_MAX = 4 * FEEDBACK_MAX_CHARS   # cut BEFORE the regexes: bounded work on hostile input


def redact(text: str) -> str:
    text = SECRET.sub("[REDACTED]", str(text)[:REDACT_INPUT_MAX])
    return REDACT_EXTRA.sub("[REDACTED]", text)


def add_feedback(state: dict, tid: str, source: str, text: str) -> None:
    if source not in FEEDBACK_SOURCES:
        raise InvalidPlan("unknown feedback source")
    row = state["tasks"][tid]
    clean = redact(text)[:FEEDBACK_MAX_CHARS]
    items = list(row.get("feedback", [])) + [{"source": source, "text": clean}]
    # The window evicts older gate/review remarks first, then older repeat markers, then the oldest Opus note, but
    # NEVER the newest gate/review remark: it is the last failure, the class factory_requeue reads and the next coder
    # needs. Live 20.11 02:37: after three requeue notes the window held only Opus notes, every new failure was evicted
    # at once, 14 quarantined tasks had no class left. Live 20.11 06:2x: the loop's repeat marker ("не повторяй: ...")
    # counted as the newest failure and evicted the failure it repeats; three FAILED tasks were never returned.
    while len(items) > FEEDBACK_KEEP:
        own = [i for i, x in enumerate(items) if x["source"] != "opus"]
        marks = [i for i in own if str(items[i]["text"]).startswith(REPEAT_MARK)]
        failures = [i for i in own if i not in marks]
        notes = [i for i, x in enumerate(items) if x["source"] == "opus"]
        del items[(failures[:-1] or marks[:-1] or notes[:1] or marks or [0])[0]]
    row["feedback"] = items


def last_feedback(state: dict, tid: str) -> str | None:
    items = state["tasks"][tid].get("feedback") or []
    if not items:
        return None
    return "\n".join("[%s] %s" % (x["source"], x["text"]) for x in items)


def charge_call(state: dict, tid: str) -> int:
    """Spend one model call at the moment of the call. Returns calls used."""
    if tid not in state["tasks"]:
        raise InvalidPlan("unknown task")
    _roll_budget(state, time.time())
    if state["model_calls"] >= state["max_model_calls"]:
        raise BudgetExhausted("budget exhausted")
    state["model_calls"] += 1
    return state["model_calls"]


def note_infra(state: dict, ok: bool) -> int:
    """Serie of infrastructure failures; any success resets it."""
    state["infra_streak"] = 0 if ok else int(state.get("infra_streak", 0)) + 1
    return state["infra_streak"]


def hold_census(state, tasks, *, google=True) -> dict[str, int]:
    counts = {}
    for tid, row in state["tasks"].items():
        status, reason = row["status"], row.get("reason")
        task = tasks.get(tid)
        if reason == "quarantine":
            key = "quarantine"
        elif is_terminal(reason):
            continue
        elif status == "BLOCKED":
            key = "owner_rule" if row.get("blocked_reason") in OWNER_RULES else "blocked_term"
        elif status == "READY" and google and task and task.only_opus:
            key = "only_opus"
        elif status == "READY" and google and task and not task.privacy_safe:
            key = "private"
        elif status == "READY" and task and any(state["tasks"].get(d, {}).get("status") == "FAILED" for d in task.depends_on):
            key = "ready_dead_dep"
        elif status == "FAILED":
            key = "failed_other"
        else:
            continue
        counts[key] = counts.get(key, 0) + 1
    return counts


def next_action(state: dict, now: float, channel_wait_s: float,
                backlog_has_more: bool, tasks: dict[str, Task], *,
                google: bool = True, free: int = 0, skip=(),
                resliceable: frozenset[str] = frozenset(), slice_wait_s: float | None = None) -> dict:
    """PROMOTE | RUN | WAIT | TRIAGE | HOLD | DONE.

    Candidates come only from ready() (same google flag as the runner), so scope
    conflicts, dependencies and not_before have one owner.
    PROMOTE: a REVIEW candidate (oldest first) must be merged before anything else.
    RUN: ready task and a free channel; WAIT: ready but channel cooling, a future
    not_before, or a live lease (wait_s >= 5); TRIAGE: nothing runnable and the
    backlog has more; HOLD: only Opus/blocked/failed work is left; DONE otherwise."""
    rows = state["tasks"]
    skip = set(skip)         # tasks whose worker is still in the pool: the loop has not accounted their pass yet
    review = [(row.get("reviewed_at", 0), tid) for tid, row in rows.items()
              if row["status"] == "REVIEW" and tid not in skip]
    if review:
        return {"action": "PROMOTE", "task_id": min(review)[1], "reason": "review_pending"}
    runnable = [t for t in ready(tasks, state, google=google, now=now) if t not in skip]
    expired = sorted((float(row["block_until"]), tid) for tid, row in rows.items()
                     if row["status"] == "BLOCKED" and tid not in skip
                     and type(row.get("block_until")) in (int, float) and row["block_until"] <= now)
    if runnable:
        if channel_wait_s > 0:
            if expired:      # W-sha: a channel cooldown does not hold a lift whose term is over (it costs no model call)
                tid = expired[0][1]
                return {"action": "UNBLOCK", "task_id": tid, "reason": rows[tid].get("blocked_reason") or "unknown",
                        "block_until": expired[0][0]}
            return {"action": "WAIT", "wait_s": channel_wait_s, "reason": "channel_cooldown"}
        return {"action": "RUN", "task_id": runnable[0], "task_ids": runnable, "reason": "ready"}
    if expired:      # <id>: nothing runnable and a block's term is over: the loop lifts it itself (earliest first)
        tid = expired[0][1]
        return {"action": "UNBLOCK", "task_id": tid, "reason": rows[tid].get("blocked_reason") or "unknown",
                "block_until": expired[0][0]}
    delayed = [rows[t].get("not_before", 0) for t in ready(tasks, state, google=google,
                                                            now=float("inf"))]
    if free > 0 and backlog_has_more and not delayed:
        return {"action": "TRIAGE", "reason": "no_runnable_tasks"}   # a worker is live and there is room for more work
    deadlines = [r["deadline"] for r in rows.values()
                 if r["status"] == "RUNNING" and r.get("deadline") is not None]
    due = [d for d in delayed + deadlines if d > now]
    if due:
        return {"action": "WAIT", "wait_s": max(5, min(due) - now),
                "reason": "not_before_or_lease"}
    if any(r["status"] == "RUNNING" for r in rows.values()):
        return {"action": "WAIT", "wait_s": 5, "reason": "running_lease"}
    if backlog_has_more:
        return {"action": "TRIAGE", "reason": "no_runnable_tasks"}
    if resliceable:
        return {"action": "RESLICE", "reason": "rows_to_slice", "backlog_ids": sorted(resliceable)}
    if slice_wait_s is not None:
        return {"action": "WAIT", "wait_s": max(5, slice_wait_s), "reason": "architect_wait"}
    held, owner, terms = False, set(), []
    for tid, row in rows.items():
        st = row["status"]
        if is_terminal(row.get("reason")) and row.get("reason") != "quarantine":
            continue
        task = tasks.get(tid)
        if st == "BLOCKED" and row.get("blocked_reason") in OWNER_RULES:
            owner.add(row["blocked_reason"])
        elif st == "BLOCKED":
            held = True
            if type(row.get("block_until")) in (int, float):
                terms.append(float(row["block_until"]))
        elif st == "FAILED" and row.get("reason") != "quarantine":
            held = True
        elif st == "READY" and google and task is not None and (task.only_opus or not task.privacy_safe):
            owner.add("only_opus" if task.only_opus else "private")
        elif st == "READY":
            held = True  # not runnable now: dead dependency, conflict
    if terms:        # the HOLD ends at the earliest term: then that block is lifted (UNBLOCK)
        return {"action": "HOLD", "reason": "blocked_until", "wait_s": max(5.0, min(terms) - now),
                "blockers": hold_census(state, tasks, google=google)}
    if held:
        return {"action": "HOLD", "reason": "only_opus_or_blocked", "blockers": hold_census(state, tasks, google=google)}
    if owner:
        return {"action": "HOLD", "reason": "owner_rule:" + ",".join(sorted(owner)),
                "blockers": hold_census(state, tasks, google=google)}
    return {"action": "DONE", "reason": "nothing_left"}


def pid_alive(pid: int) -> bool:
    """Liveness without touching the process. os.kill(pid, 0) is NOT used on Windows."""
    if pid == os.getpid():
        return True
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes as W
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.OpenProcess.restype = W.HANDLE
        k.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
        k.GetExitCodeProcess.argtypes = [W.HANDLE, ctypes.POINTER(W.DWORD)]
        k.CloseHandle.argtypes = [W.HANDLE]
        handle = k.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return ctypes.get_last_error() == 5  # access denied: it exists
        code = W.DWORD()
        ok = k.GetExitCodeProcess(handle, ctypes.byref(code))
        k.CloseHandle(handle)
        return bool(ok) and code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _lock_owner(lock: Path) -> int | None:
    """The pid the holder wrote into its lockdir, or None (no file yet, or not a pid)."""
    try:
        return int((lock / LOCK_OWNER).read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return None


LOCK_DROP_RETRY_S = 2.0


def _drop_lock(lock: Path) -> None:
    """Remove the lockdir. On Windows a waiter that reads the owner file at that moment holds it open (no
    FILE_SHARE_DELETE), so unlink/rmdir fail with a sharing violation: retry briefly instead of leaking the lock."""
    deadline = time.monotonic() + LOCK_DROP_RETRY_S
    while True:
        try:
            (lock / LOCK_OWNER).unlink(missing_ok=True)
            lock.rmdir()
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.01)


@contextlib.contextmanager
def _dir_lock(path: Path, timeout_s: float):
    """Same lockdir convention as the checkpoint: <file>.lockdir, exclusive mkdir. The holder writes its pid into it:
    a lock whose holder is dead is cleared at once, any other after LOCK_STALE_S (a commit lasts milliseconds)."""
    lock = path.with_suffix(path.suffix + ".lockdir")
    lock.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            lock.mkdir()
            break
        except (FileExistsError, PermissionError):   # PermissionError: Windows answers a mkdir while the old lockdir
            # is being removed (delete pending) with WinError 5, not "exists" (live 21.11 14:13 crashed the loop)
            try:
                age = time.time() - lock.stat().st_mtime
            except OSError:
                age = 0.0
            owner = _lock_owner(lock)
            dead = owner is not None and not pid_alive(owner)
            if dead or age > LOCK_STALE_S:
                try:
                    _drop_lock(lock)
                    ev = {"event": "stale_lock_removed", "lock": str(lock), "age_s": round(age),
                          "why": "dead_holder" if dead else "old",
                          "holder": "dead" if dead else ("anonymous" if owner is None else "old")}
                    LOCK_EVENTS.append(ev)
                    _log.warning("%s", ev)
                    continue
                except OSError as e:
                    _log.warning("stale lock %s not removed: %s", lock, e)
            if time.monotonic() >= deadline:
                raise LockBusy("plan is locked by another writer")
            time.sleep(0.05)
    with contextlib.suppress(OSError):
        (lock / LOCK_OWNER).write_text(str(os.getpid()), encoding="ascii")
    try:
        yield
    finally:
        try:
            _drop_lock(lock)
        except OSError as e:
            LOCK_EVENTS.append({"event": "lock_release_failed", "lock": str(lock),
                                "reason": str(e)[:200]})
            _log.warning("lock %s not released: %s", lock, e)


@contextlib.contextmanager
def txn(checkpoint: Path, plan: Path, timeout_s: float = LOCK_STALE_S + 10):
    """One short transaction on the checkpoint: lock it, read the plan and the state FRESH (the plan grows while a pass
    works), hand them to the block, validate and save on a normal exit. A block that raises writes nothing. Passes
    change the state only through this: the lease protects the task, the lock only the commit."""
    checkpoint, plan = Path(checkpoint), Path(plan)
    with _dir_lock(checkpoint, timeout_s):
        tasks = read_plan(json.loads(plan.read_text(encoding="utf-8")))
        state = load_state(checkpoint, tasks)
        yield tasks, state
        validate_state(tasks, state)
        save_atomic(checkpoint, state)


def claim(checkpoint: Path, plan: Path, tid: str | None = None):
    """One transaction: the task ``tid`` (else the first ready one) goes RUNNING under a fresh lease; no model call is
    charged (the call is charged when it is made). (task id, token), or None when nothing is ready."""
    with txn(checkpoint, plan) as (tasks, state):
        choices = [t for t in ready(tasks, state) if tid is None or t == tid]
        if not choices:
            return None
        return choices[0], acquire(tasks, state, choices[0], charge=False)


def snapshot(checkpoint: Path, plan: Path, timeout_s: float = LOCK_STALE_S + 10):
    """(tasks, state) read FRESH under the lock and handed out as private copies, nothing saved. Readers go through
    the lock too: on Windows a lock-free read makes the writer's os.replace fail."""
    checkpoint, plan = Path(checkpoint), Path(plan)
    with _dir_lock(checkpoint, timeout_s):
        tasks = read_plan(json.loads(plan.read_text(encoding="utf-8")))
        return tasks, load_state(checkpoint, tasks)


class Lease:
    """A pass's handle on the checkpoint: the lease protects the task, the lock only each commit. ``commit(fn)`` = one
    transaction on the FRESH state: the lease is checked first (StaleLease writes nothing), then ``fn(state, row)``
    changes the state and the row of the pass's task, then the state is validated and saved. ``read()`` = a fresh
    private copy of the state (no save)."""

    def __init__(self, checkpoint: Path, plan: Path, tid: str, token: str):
        self.checkpoint, self.plan, self.tid, self.token = Path(checkpoint), Path(plan), tid, token

    def commit(self, fn):
        with txn(self.checkpoint, self.plan) as (_tasks, state):
            fence(state, self.tid, self.token)
            return fn(state, state["tasks"][self.tid])

    def read(self) -> dict:
        return snapshot(self.checkpoint, self.plan)[1]


def append_tasks(plan_path: Path, tasks: list[dict], *,
                 lock_timeout_s: float = 10.0) -> list[str]:
    """Add validated tasks to a plan file (atomic, under the plan's lockdir).
    Returns the added ids; the result's `.skipped` lists duplicates
    [{id, backlog_id, reason}]. Any invalid task (or broken plan JSON) raises
    InvalidPlan and nothing is written."""
    plan_path = Path(plan_path)
    with _dir_lock(plan_path, lock_timeout_s):
        rows: list[dict] = []
        extra: dict = {}
        if plan_path.exists():
            try:
                data = json.loads(plan_path.read_text(encoding="utf-8"))
            except (ValueError, OSError) as e:
                raise InvalidPlan("plan file is not valid JSON") from e
            if isinstance(data, dict):
                rows = list(data.get("tasks", []))
                extra = {k: v for k, v in data.items() if k != "tasks"}
            elif isinstance(data, list):
                rows = list(data)
            else:
                raise InvalidPlan("plan must contain a tasks list")
            read_plan(rows)
        known_ids = {r.get("id") for r in rows}
        known_backlog = {(r.get("backlog_id"), r.get("kind", "code")) for r in rows if r.get("backlog_id")}
        result = AppendResult()
        for row in tasks:
            if (not isinstance(row, dict) or not isinstance(row.get("id"), str)
                    or not isinstance(row.get("backlog_id", ""), str)):
                raise InvalidPlan("id and backlog_id must be strings")
            if not isinstance(row.get("kind", "code"), str):
                raise InvalidPlan("kind must be a string")
            rid, bid = row["id"], row.get("backlog_id") or ""
            if rid in known_ids:
                result.skipped.append({"id": rid, "backlog_id": bid, "reason": "duplicate id"})
                continue
            if (bid and (bid, row.get("kind", "code")) in known_backlog   # a unit_test sub-task shares its backlog_id
                    and not rid.endswith(REFEED_SUFFIX) and not RESLICE_ID.search(rid)):                 # a guard re-feed of a failed row (its own id: no duplicate)
                result.skipped.append({"id": rid, "backlog_id": bid,
                                       "reason": "duplicate backlog_id"})
                continue
            read_plan(rows + [row])  # same rules as the plan reader; raises InvalidPlan
            rows.append(row)
            known_ids.add(rid)
            if bid:
                known_backlog.add((bid, row.get("kind", "code")))
            result.append(rid)
        if result:
            save_atomic(plan_path, dict(extra, tasks=rows))
        return result


def amend_task(plan_path: Path, tid: str, *, touch_files=None, tests=None, read_files=None,
               context_targets=None, depends_on=None, goal=None, port_from=None, contract=None, state_path=None,
               lock_timeout_s: float = 10.0) -> dict:
    """Opus corrects one task of a live plan: only the given fields change, the whole plan is
    re-validated by read_plan, the write is atomic and happens under the plan's lockdir.
    A task that is RUNNING or REVIEW (checkpoint next to the plan, or `state_path`) is refused.
    Returns the new row."""
    plan_path = Path(plan_path)
    with _dir_lock(plan_path, lock_timeout_s):
        try:
            data = json.loads(plan_path.read_text(encoding="utf-8"))
        except ValueError as e:  # OSError is temporary: it propagates as is
            raise InvalidPlan("plan file is not valid JSON") from e
        extra: dict = {}
        if isinstance(data, dict):
            rows = list(data.get("tasks", []))
            extra = {k: v for k, v in data.items() if k != "tasks"}
        elif isinstance(data, list):
            rows = list(data)
        else:
            raise InvalidPlan("plan must contain a tasks list")
        idx = next((i for i, r in enumerate(rows) if isinstance(r, dict) and r.get("id") == tid), None)
        if idx is None:
            raise InvalidPlan("unknown task")
        sp = Path(state_path) if state_path else plan_path.with_name("state.json")
        if sp.exists():
            try:
                status = json.loads(sp.read_text(encoding="utf-8"))["tasks"].get(tid, {}).get("status")
            except (ValueError, KeyError, AttributeError) as e:
                raise InvalidPlan("checkpoint unreadable, task state unknown") from e
            if status in ("RUNNING", "REVIEW"):
                raise InvalidPlan("task is %s: wait for it to settle" % status)
        new = dict(rows[idx])
        for key, value in (("touch_files", touch_files), ("tests", tests),
                           ("read_files", read_files), ("depends_on", depends_on)):
            if value is not None:
                new[key] = list(value)
        if context_targets is not None:
            if not isinstance(context_targets, dict):
                raise InvalidPlan("context_targets must be a mapping")
            new["context_targets"] = dict(context_targets)
        if goal is not None:
            new["goal"] = redact(str(goal))[:1000]
        if contract is not None:
            new["contract"] = contract
        if port_from is not None:
            new["port_from"] = str(port_from)
        rows = rows[:idx] + [new] + rows[idx + 1:]
        read_plan(rows)  # the whole plan, not just this row
        save_atomic(plan_path, dict(extra, tasks=rows))
        return new


class AppendResult(list):
    """list[str] of added ids plus `.skipped` report of ignored duplicates."""

    def __init__(self):
        super().__init__()
        self.skipped: list[dict] = []


def route(task: Task, *, small_model: str, large_model: str,
          threshold: int = 8000, fallback: bool = False) -> str:
    """Model IDs are supplied by actual Kilo local model list, not fabricated."""
    if not task.privacy_safe or task.only_opus:
        raise InvalidPlan("cannot send a private task to a Google model")
    if not all(MODEL_ID.fullmatch(m) for m in (small_model, large_model)):
        raise InvalidPlan("model IDs must match provider/model")
    large = fallback or task.estimated_tokens >= threshold or task.task_type in ('multifile', 'review', 'logs')
    return large_model if large else small_model


def backoff(attempt: int, *, base: float = 2.0, cap: float = 20.0) -> float:
    if type(attempt) is not int or attempt < 0:
        raise ValueError("retry index")
    return min(cap, base * 2 ** min(attempt, 16))


# Live 20.11: under a 200 000-byte cap the product's largest file (echo_sync/cm_kind.py, 330 715 bytes) refused every
# task that named it - 6 rows blocked for good as 'scope_violation' ("input requires trusted local review"). A big file
# reaches a model as an outline plus fragments, so render() bounds what a model sees, not the size of the file.
SOURCE_MAX_BYTES = 1_000_000
_ASSIGNMENT = re.compile(r"(?i)(?:password|api[_-]?key|client_secret)\s*[:=]")
_KEYWORD_VALUE = re.compile(r"(?i)(?:password|api[_-]?key|client_secret)\s*[:=]\s*(?:continue|nonlocal)\s*$")


def secret_in_source(text: str) -> bool:
    """SECRET in a source file, minus two shapes of code that only look like a key (live 20.11, 2 product files):
    a key prefix inside a word (the name of a speech model whose word 'vosk' ends in the two letters of a key prefix,
    followed by a dash) and a Python keyword after the name password and a colon (an if on parts.password whose body
    is continue). An assignment of a value always counts, also inside a longer name. redact() masks both shapes in
    free text all the same."""
    for match in SECRET.finditer(text):
        found = match.group(0)
        if _ASSIGNMENT.match(found):
            if _KEYWORD_VALUE.match(found):
                continue
            return True
        before = text[match.start() - 1] if match.start() else ''
        if before.isalnum() or before == '_':
            continue
        return True
    return False


def safe_source(path: Path, *, max_size: int | None = None) -> bytes:
    """Reject symlinks, non-UTF8, suspicious secrets and oversized inputs; every refusal names the file."""
    limit = SOURCE_MAX_BYTES if max_size is None else max_size
    if path.is_symlink() or not path.is_file():
        raise InvalidPlan("input is not a regular file: %s" % path.name)
    if path.stat().st_size > limit:
        raise InputTooLarge("input over %d bytes: %s" % (limit, path.name))
    data = path.read_bytes()
    if b"\x00" in data:
        raise InvalidPlan("binary input: %s" % path.name)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as e:
        raise InvalidPlan("not UTF-8: %s" % path.name) from e
    if secret_in_source(text):
        raise InvalidPlan("potential secret in %s; private review required" % path.name)
    return data


def receipt_digest(stdout: bytes, stderr: bytes, code: int) -> str:
    """Store digest only, never spill private stdout/transcript into checkpoint."""
    return sha256(stdout[:100_000] + b"\0" + stderr[:100_000] +
                  f"\0{code}".encode()).hexdigest()


def grouped_failures(xml_text: str) -> list[dict]:
    """JUnit grouping by normalized exception *signature*, not proven root cause.

    Cards are BLOCKED and private by default; never dispatch directly to Google.
    """
    root = ET.fromstring(xml_text)
    groups: dict[str, dict] = {}
    for case in root.iter("testcase"):
        failure = next((x for x in case if x.tag in ("failure", "error")), None)
        if failure is None:
            continue
        # Do not persist full exception messages, stack frames or personal paths.
        kind = failure.tag
        message = failure.get("type", "unknown")
        message = re.sub(r"[^a-zA-Z0-9_.]", "_", message)[:60] or "unknown"
        node = f"{kind}:{message}"
        key = sha256(node.encode()).hexdigest()[:12]
        group = groups.setdefault(key, {"id": "CI_" + key,
                                        "signature": node, "count": 0,
                                        "status": "BLOCKED", "privacy_safe": False})
        group["count"] += 1
    return sorted(groups.values(), key=lambda x: x["id"])


def save_atomic(path: Path, state: dict) -> None:
    """Fsync then atomic replace; bounded retry for transient Windows WinError 5.

    Never truncate an old checkpoint; remove abandoned temp files on failure.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8",
                                         dir=path.parent, prefix=".agent-state-",
                                         delete=False) as f:
            tmp = Path(f.name)
            json.dump(state, f, ensure_ascii=False, sort_keys=True, indent=2)
            f.flush()
            os.fsync(f.fileno())
        for attempt in range(4):
            try:
                os.replace(tmp, path)
                tmp = None
                break
            except PermissionError:
                if attempt == 3:
                    raise
                time.sleep(0.04 * (2 ** attempt))
    finally:
        if tmp is not None:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass


TRACE_DIR = "traces"


def put_trace(state_dir: Path, tid: str, path) -> str:
    """<id>: the cloud trace of a red base lives beside the state (traces/<tid>.json), not inside it; returns the file name."""
    name = re.sub(r"[^A-Za-z0-9_.-]", "_", str(tid))[:80] or "task"
    if name != str(tid):                 # ids that clean to the same name (T/1, T_1) must not share a file
        name += "-" + sha256(str(tid).encode("utf-8")).hexdigest()[:8]
    folder = Path(state_dir) / TRACE_DIR
    folder.mkdir(parents=True, exist_ok=True)
    save_atomic(folder / (name + ".json"), {"path": [[str(c[0]), str(c[1]), int(c[2])] for c in path]})
    return name + ".json"


def get_trace(state_dir: Path, row: dict) -> tuple:
    """The trace of the row's red base as ((file, qualname, line), ...); () when there is none or the file is unreadable."""
    return load_trace(state_dir, row) or ()


def load_trace(state_dir: Path, row: dict):
    """Like get_trace, but None when the trace is unreadable (file missing, torn, garbage) - an empty trace is a real answer.
    A record that still carries the trace inline (written before <id>) is read as it is."""
    try:
        result = (row.get("base_red") or {}).get("result") or {}
        if result.get("path_file"):
            name = Path(str(result["path_file"])).name
            data = json.loads((Path(state_dir) / TRACE_DIR / name).read_text(encoding="utf-8"))
            raw = data["path"]
        else:
            raw = result.get("path") or ()
        return tuple((str(c[0]), str(c[1]), int(c[2])) for c in raw)
    except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError):
        return None


def _move_traces(state_dir: Path, data: dict) -> None:
    """One-off move of inline base_red traces of an old state into their files (the state shrinks on its next save)."""
    for tid, row in (data.get("tasks") or {}).items():
        result = ((row.get("base_red") or {}).get("result")) if isinstance(row, dict) else None
        if isinstance(result, dict) and "path" in result:
            try:
                result["path_file"] = put_trace(state_dir, tid, result["path"])
                del result["path"]
            except (OSError, ValueError, TypeError, IndexError):
                continue                      # unreadable trace: it stays inline, a damaged record only costs a new measurement


def load_state(path: Path, tasks: dict[str, Task]) -> dict:
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else initial_state(tasks)
    _move_traces(path.parent, data)
    sync_state(tasks, data)
    validate_state(tasks, data)
    return data
