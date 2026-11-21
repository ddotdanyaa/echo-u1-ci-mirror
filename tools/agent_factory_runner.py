"""Opt-in Kilo queue executor; defaults to planning, never deploying.

IMPORTANT: a copied work directory and git worktree are NOT OS sandboxes.
The --execute flag requires an explicit risk acknowledgement and a separately
configured account/OS sandbox when privacy matters. No file from the source
project is written back automatically.

One pass = one task: red-before on the base, ONE coder call, deterministic gates
(factory_gate), neighbour tests, an independent reviewer. A rejected candidate returns
its feedback and diff to the next pass; channel and provider faults are never strikes.
"""
from __future__ import annotations

import argparse
import ast
import contextlib
import difflib
from hashlib import sha256
import http.client
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import logging
import urllib.error
import urllib.request
import dataclasses
from dataclasses import replace

from .agent_factory import (BudgetExhausted, DEFER_REASONS, LEASE_LIFETIME_S, MAX_ATTEMPTS, MODEL_ID, InputTooLarge,
                            InvalidPlan, Lease, LockBusy, StaleLease, Task, add_feedback, begin, charge_call, claim,
                            defer, defer_streak, failed_models_of, is_unsafe_reject, seconds_to_local_midnight,
                            read_plan, ready, redact, REPEAT_MARK, route, quarantine, safe_path, safe_source, settle,
                            snapshot, txn, unclaim)
from .factory_context import (LARGE_FILE_CHARS, asked_names, failing_names, identifier_tokens, keywords_from, packet,
                              render, scrub_paths)
from .factory_process import kilo_argv, run_owned
from . import affected_tests
from . import factory_channels as channels
from . import factory_gate as gate
from . import factory_quota as quota_ledger
from . import factory_paid_critic as paid_critic

_log = logging.getLogger(__name__)
ENV_ALLOW = ("PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "LANG")
POLICY_FILE = "kilo.jsonc"
PROVIDER_STEPS = 8   # coder: outline -> read by lines -> grep -> edit needs room (3 was too few)
REVIEW_STEPS = 4     # the reviewer only reads and answers
TRANSIENT_HOPS = 4   # an overloaded (503) model: up to this many other models at once in the same call, no wait


ENV_HOLD_AFTER = 10          # consecutive environment shortages before the long hold (the candidate is kept)
ENV_HOLD_S = 1800
ENV_OTHER_CEILING = 3         # a persistent non-slot environment failure (a missing package...) is parked after this many
RED_BEFORE_WAIT_S = 120      # the base run before the coder call waits for a slot at most this long (its own ceiling)
SLOT_BUDGET_S = 300         # ONE wait for a pytest slot / free RAM per runner pass, shared by every gate run
IDLE_SUSPECTS_ALLOWED = 4   # 21.11 (was 2) idle timeouts treated as a rate limit; the next one is a worker fault (infra)


def factory_env(state: dict) -> dict:
    """The runner's own counters (idle timeouts, environment shortages): a state key of their own, because a
    name inside channel_quotas would be read as a quota group."""
    table = state.get('factory_env')
    if not isinstance(table, dict):
        table = state['factory_env'] = {}
    for name in ('idle', 'shortages', 'other'):
        if not isinstance(table.get(name), dict):
            table[name] = {}
    return table


def _now() -> float:
    """The runner's clock for the slot budget (tests replace THIS, never the global time module)."""
    return time.monotonic()


def kilo_config(provider: str, auth_env: str, steps: int) -> dict:
    """The process-owned Kilo config: the key reference and ONE agent. No prompt/system until the canary proves it."""
    return {"provider": {provider: {"options": {"apiKey": '{env:' + auth_env + '}'}}},
            'enabled_providers': [provider],
            'agent': {'factory': {'description': 'Bounded task executor', 'mode': 'primary',
                                  'steps': steps or PROVIDER_STEPS}}}


def _kilo_fits(order: list, steps: int, events: list) -> list:
    """The channels a Kilo run of ``steps`` steps can use: Kilo sends its steps back to back, so a channel whose
    rpm is below them answers 429 inside the run and Kilo sleeps there until the idle ceiling (live 20.11 12:25-12:44:
    three 3.6 Flash calls at rpm 5, 180 s each, no step, a strong-model request of the day spent). Such channels go
    out of the order; when none is left the order stays whole (a slow channel is better than no channel)."""
    fit = [c for c in order if not (type(c.get('rpm')) is int and c['rpm'] < steps)]
    if fit and len(fit) < len(order) and 'low_rpm_skipped' not in events:
        events.append('low_rpm_skipped')
    return fit or order


def requests_for(steps: int) -> int:
    """Provider requests of one multi-step call: every step plus the final answer after the tool limit."""
    return steps + 1

GATE_TIMEOUT_S = 30                   # owner rule: pytest never longer than 30 s
MAX_NEIGHBORS = 6
INFRA_DEFER_S = 300
DIFF_LIMIT = 3000
REVIEW_DIFF_LIMIT = 6000
# infra=True (counts toward the loop brake) ONLY for a dead channel or no result from the process;
# a slow test, a prose answer, a 429 or a blocked task is the task's or the model's business
INFRA_DEFERS = frozenset(("key_invalid", "balance", "model_missing"))  # real infrastructure faults


ESCALATE = frozenset(("gate_unknown", "provider_error", "no_independent_reviewer", "reviewer_failed",
                      "review_chain_short"))
ESCALATE_AFTER = 3          # the same postponement this many times in a row becomes BLOCKED
INFRA_CHANNEL_REASONS = frozenset(("dead", "no_key", "no_channels", "reservation_exceeds_tpm"))
FRESH_WAITS, FRESH_WAIT_S = 2, 60   # a task waits for a model that has not failed it at most this many times this long


class _FreshBusy(Exception):
    """Only models that already failed this task can take the coder call now (handled inside once())."""
REVIEW_HINT = ("The file is large: read the places you need with the read tool by line numbers from the "
               "outline. Do not edit anything: you only judge the diff.")
LIGHT_REVIEW_HINT = "The file is large: only its outline and the parts below are shown. You only judge the diff."
# The test author's most frequent defects, from the reviewers' rejections of the live series 19.11 17:53-18:38
# (a MagicMock as the code under test, assert False, a name-exists tautology, counts of the repository)
UNIT_TEST_RULES = ("The test must import the real functions or classes from the code files shown and call them, "
                   "then assert on what they return or do. Never test a MagicMock in place of that code, never "
                   "write assert False, a test that only checks that a name exists, or a hard-coded count of "
                   "files or markers in the repository. The project has no pytest-asyncio plugin: never write "
                   "async def test functions or @pytest.mark.asyncio; drive async code with asyncio.run(...) inside "
                   "a plain def test function." "\n" + gate.UNIT_TEST_RULES)   # one source: the gate's own rules
MARKER_PROBE = gate.GateResult(1, 1, 0, 1, 0, 0, True, '')   # a red result: only the marker can fail it
REVIEW_NOTE_LIMIT = 400     # <id>: what the task's earlier candidates were rejected for, shown to its critics
REVIEW_OVERHEAD = 1500 + REVIEW_NOTE_LIMIT      # reviewer instructions + verdict format on top of the files
VIEW_ROOM = 3000            # the least room planned for one file shown as outline + parts (render's floor is lower)
# what the files of one prompt may take: the reviewer's room besides its diff and instructions, less the coder's text
FIT_ROOM = channels.PROMPT_LIMIT_CHARS - REVIEW_DIFF_LIMIT - REVIEW_OVERHEAD - 3000
COPY_IGNORE = shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", ".env*", "SECRETS_LOCAL",
                                     "*.pem", "*.key")


class ChannelFault(Exception):
    """The channel or provider failed; the candidate is not to blame (no strike)."""

    def __init__(self, info: dict, wait_s: float = 0.0):
        super().__init__(info.get('kind', 'unknown'))
        self.info, self.wait_s = info, wait_s


class NoIndependentReviewer(Exception):
    """Only the coder's own model is available: the review waits (never a self-review)."""


class PromptTooLarge(Exception):
    """Prompt over the limit: not sent, no strike, the triage splits the task."""


class ReviewFault(Exception):
    """Reviewer call failed or answered with something that is not a verdict."""


def profile_names() -> tuple:
    """Names that identify the user: the home directory name and the login."""
    names = {Path.home().name, os.environ.get('USERNAME', ''), os.environ.get('USER', '')}
    return tuple(sorted(n for n in names if n))


def staging_reveals_profile(path) -> bool:
    """True when a WHOLE segment of the resolved path is the user's name (substrings of other words, such as
    'an' in 'agent-factory', are not a leak). 8.3 names are expanded by resolve()."""
    segments = {part.lower() for part in Path(path).resolve().parts}
    return any(name.lower() in segments for name in profile_names())


PROFILE_LEAK_MESSAGE = ("staging под профилем пользователя раскрывает имя модели: Kilo кладёт рабочий каталог "
                        "в системный промпт; задайте --state-dir вне профиля, например C:" + chr(92) + "agent-factory"
                        + chr(92) + "echo")


@contextlib.contextmanager
def scratch_redirect(staging):
    """Every temporary directory of a pass (base copies, gate trees, pytest basetemp) goes to <staging>/tmp:
    %TEMP% is under the profile and its paths would reach the model through test output."""
    tmp = Path(staging) / 'tmp'
    tmp.mkdir(parents=True, exist_ok=True)
    saved = (tempfile.tempdir, os.environ.get('TEMP'), os.environ.get('TMP'))
    tempfile.tempdir = str(tmp.resolve())
    os.environ['TEMP'] = os.environ['TMP'] = tempfile.tempdir
    try:
        if staging_reveals_profile(tempfile.gettempdir()):
            raise InvalidPlan(PROFILE_LEAK_MESSAGE)
        yield tmp
    finally:
        tempfile.tempdir = saved[0]
        for key, value in zip(('TEMP', 'TMP'), saved[1:]):
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def sweep_scratch(staging, max_age: float = 86400.0) -> list:
    """Orphans of killed passes (Kilo homes, review copies, tmp/*) older than a day, strictly inside staging.
    Returns the names it could not remove (a held file): the caller records them. Junctions are never followed."""
    staging = Path(staging)
    failed: list = []
    isjunction = getattr(os.path, 'isjunction', lambda _p: False)
    found = list(staging.glob('factory-kilo-home-*')) + list(staging.glob('factory-review-*'))
    found += list((staging / 'tmp').glob('*')) if (staging / 'tmp').is_dir() else []
    for item in found:
        try:
            if (item.is_symlink() or isjunction(item) or not inside_staging(item.resolve(), staging)
                    or time.time() - item.stat().st_mtime <= max_age):
                continue
            if item.is_dir():
                shutil.rmtree(item, onexc=lambda _f, _p, _e, name=item.name: failed.append(name))
            else:
                item.unlink()
        except OSError:
            failed.append(item.name)
    return failed


def worker_policy(task: Task, readable=()) -> dict:
    """Kilo 1.0 project permission syntax; policy is frozen in the staging snapshot.

    This is application-level enforcement, NOT an OS sandbox.

    NOTE: grep sees EVERYTHING in the work copy: the read deny rules do not apply to it (a grep for a
    secret would find it). Safety rests on safe_path / DENY_PARTS keeping .env, .git and secrets out of
    the copy in the first place; external_directory deny keeps every tool inside the copy.
    """
    edit = {"*": "deny"}
    # Kilo matches rules against the ABSOLUTE path; bare names never match.
    edit.update({"**/" + name: "allow" for name in sorted(task.touch_files)})
    read = {'*': 'deny', '*.env': 'deny', '**/*.env': 'deny',
            '*.env.*': 'deny', '**/*.env.*': 'deny'}
    read.update({'**/' + name: 'allow' for name in sorted(set(task.touch_files + task.tests))})
    # big read-only files are not in the prompt whole: the agent reads them by line numbers
    read.update({'**/' + name: 'allow' for name in sorted(readable)})
    return {
        "$schema": "https://app.kilo.ai/config.json",
        "enabled_providers": ["google"],
        "mcp": {},
        "formatter": False,
        "lsp": False,
        "permission": {
            "*": "deny",
            "read": read,
            "edit": edit,
            # search is allowed ONLY inside the work copy: it holds the task files and nothing else, and
            # external_directory stays deny. For a 100 KB file grep is the way to find a function.
            "glob": "allow",
            "grep": "allow",
            "list": "allow",
            "external_directory": "deny",
            "bash": "deny",
            "task": "deny",
            "agent_manager": "deny",
            "websearch": "deny",
            "webfetch": "deny",
            "doom_loop": "deny",
            "skill": "deny",
        },
    }


def source_path(root: Path, name: str) -> Path:
    safe_path(name)
    parent = root.resolve()
    parts = name.split("/")
    # A harmless-looking alias to a hidden directory is still a privacy leak.
    for depth in range(1, len(parts) + 1):
        if root.joinpath(*parts[:depth]).is_symlink():
            raise InvalidPlan("symlink component in source path")
    path = root.joinpath(*parts)
    if not path.resolve().is_relative_to(parent):
        raise InvalidPlan("path escapes source root")
    return path


def visible_targets(task: Task) -> dict:
    """context_targets of the files a prompt may show sliced: never writable files or tests."""
    return {n: s for n, s in task.context_targets if n not in task.touch_files + task.tests}


def pinned_targets(task: Task) -> dict:
    """file -> definition names the coordinator named in context_targets (a name selector, 'Class.method' gives the
    method), writable files included: the coder prompt shows each of them whole before anything else."""
    out: dict = {}
    for name, sel in task.context_targets:
        leaf = str(sel).rpartition('.')[2]
        if leaf.isidentifier():
            out.setdefault(name, set()).add(leaf)
    return {n: frozenset(v) for n, v in out.items()}


def inside_staging(path, staging) -> bool:
    """True only for a path STRICTLY inside staging (staging itself and anything outside are not)."""
    try:
        return Path(staging).resolve() in Path(path).resolve().parents
    except (OSError, ValueError, RuntimeError):
        return False


ATTEMPT_TAG = re.compile(r'^\[attempt (\d+)\] ')


def fresh_feedback(state: dict, tid: str) -> str | None:
    """Feedback for the coder: the LAST attempt's gate/review findings and Opus notes written after it.
    Infrastructure notes ([infra] ...) and older attempts never reach the coder. The runner tags its own
    entries: reject() writes "[attempt N] ...", block() writes "[infra] ..."; Opus notes are untagged."""
    items = [i for i in (state['tasks'][tid].get('feedback') or []) if isinstance(i, dict)]
    last_opus = max((i for i, item in enumerate(items) if item.get('source') == 'opus'), default=-1)
    tail = [(i, item) for i, item in enumerate(items)
            if i > last_opus and item.get('source') in ('gate', 'review')]
    last_n = None
    for _, item in tail:
        m = ATTEMPT_TAG.match(str(item.get('text', '')))
        if m:
            last_n = int(m.group(1))
    if last_n is not None:
        keep = {i for i, item in tail
                if (m := ATTEMPT_TAG.match(str(item.get('text', '')))) and int(m.group(1)) == last_n}
    else:   # an old state without attempt tags: the last plain gate/review entry (requeue notes included)
        plain = [i for i, item in tail if not (item.get('source') == 'gate'
                                               and str(item.get('text', '')).startswith(('[infra] ', REPEAT_MARK)))]
        keep = set(plain[-1:])
    # <id>: the loop's lines about the last failure (its repeat line, its class with the remedy and past cases) are
    # untagged and written after it; they reach the coder until a newer attempt is recorded
    anchor = max(keep, default=last_opus)
    keep |= {i for i, item in tail if i > anchor and item.get('source') == 'gate'
             and str(item.get('text', '')).startswith(REPEAT_MARK)}
    out = []
    for i, item in enumerate(items):
        text, source = str(item.get('text', '')), item.get('source')
        if source == 'opus':                      # every Opus note is an instruction, whatever its age
            out.append('[opus] ' + text)
        elif i in keep:
            m = ATTEMPT_TAG.match(text)
            out.append('[%s] %s' % (source, text[m.end():] if m else text))
    return '\n'.join(out) or None


def rejected_for(state: dict, tid: str) -> str:
    """What the task's earlier candidates were rejected for, as its coder was told (fresh_feedback) without the
    requeue notes and the loop's repeat markers; the newest REVIEW_NOTE_LIMIT characters. <id> (skeptic 20.11): a redo
    of a rejected test kept the very lines the rejection named and two critics approved it, they never saw it."""
    lines = [ln for ln in (fresh_feedback(state, tid) or '').split('\n')
             if ln.strip() and not ln.startswith(('[opus] Retry on factory version', '[gate] ' + REPEAT_MARK))]
    return redact('\n'.join(lines))[-REVIEW_NOTE_LIMIT:]


def large_names(task: Task, files: dict[str, bytes]) -> set[str]:
    """The files of the task shown as outline + parts, not whole: each over LARGE_FILE_CHARS, tests too, then the
    largest of the rest until the whole ones and VIEW_ROOM per view fit FIT_ROOM. The ONE rule of the coder prompt,
    the reviewer prompt, prepare(), the pass's size check and the read budget (live 20.11 04:29: four tasks were
    refused before any model call, every time, because their tests were always shown whole: one test file was
    50 KB, another task had five test files of 68 KB together)."""
    scope = set(task.touch_files) | set(task.read_files) | set(task.tests)
    sized = sorted(((len(v), n) for n, v in files.items() if n in scope), reverse=True)
    big = {n for size, n in sized if size > LARGE_FILE_CHARS}
    rest = [(size, n) for size, n in sized if n not in big]
    whole = sum(size for size, _ in rest)
    while rest and whole + VIEW_ROOM * len(big) > FIT_ROOM:
        size, name = rest.pop(0)
        big.add(name)
        whole -= size
    return big


BASE_CACHE_S = 6 * 3600     # a measured red base is reused this long for the same commit, tests and files


def _base_key(base_sha, task: Task, baseline: dict) -> str | None:
    """The identity of a base measurement: the base commit, the kind, the task's tests and the bytes of every staged
    file (the worker policy aside); None without a base commit (an unpinned tree is never reused)."""
    if not base_sha:
        return None
    h = sha256(('%s\n%s\n%s' % (base_sha, task.kind, '\n'.join(sorted(task.tests)))).encode('utf-8'))
    for name, data in sorted(baseline.items()):
        if name != POLICY_FILE:
            h.update(name.encode('utf-8') + b'\0' + sha256(data).digest())
    return h.hexdigest()


def _held_base(row: dict, key: str | None, kind: str | None = None):
    """The red base kept on the row for this key while it is fresh; None when absent, stale, foreign or unreadable
    (a damaged record only costs a new measurement). A code task's record must carry the path of its failing tests
    (GateResult.path; a record written before the trace existed is measured once more)."""
    held = row.get('base_red')
    if not key or not isinstance(held, dict) or held.get('key') != key:
        return None
    try:
        if not 0 <= _now() - float(held['at']) < BASE_CACHE_S:
            return None
        if kind == 'code' and 'path' not in held['result']:
            return None
        fields = {k: tuple(v) if isinstance(v, list) else v for k, v in held['result'].items()}
        if 'path' in fields:
            fields['path'] = tuple(tuple(p) for p in fields['path'])
        return gate.GateResult(**fields)
    except (TypeError, ValueError, KeyError, AttributeError):
        return None


def prepare(root: Path, task: Task, workdir: Path) -> dict[str, bytes]:
    """Copy only explicitly approved files, never .git, .env or any symlink.

    Existing tests are immutable for a code task. A unit_test task touches exactly its
    tests and the file may not exist yet (the model creates it). Safe staged sources
    still require external OS sandboxing before calling autonomous Kilo against private code.
    """
    root = root.resolve()
    workdir.mkdir(parents=True, exist_ok=False)
    names = set(task.read_files) | set(task.touch_files) | set(task.tests)
    if task.kind != "unit_test" and set(task.touch_files) & set(task.tests):
        raise InvalidPlan("existing acceptance tests are immutable")
    if not task.privacy_safe:
        raise InvalidPlan("private plan must not be staged for free-tier Google")
    if any(safe_path(name) != name for name in names):
        raise InvalidPlan("unsafe filename")
    if len(names) > 100:
        raise InvalidPlan("overbroad task scope")
    if len(task.title) > 240:
        raise InvalidPlan("unsafe prompt: title too long")
    staged: dict[str, bytes] = {}
    for name in sorted(names):
        src = source_path(root, name)
        # Nonexistent touch-files are permitted only as explicit new outputs.
        if not src.exists() and name in task.touch_files and name not in task.read_files:
            continue
        if not src.exists():
            raise InvalidPlan("required input missing")
        data = safe_source(src)
        dest = workdir.joinpath(*name.split("/"))
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        staged[name] = data
    # Count all visible bytes, including writable files and tests, not just prompt.
    big = large_names(task, staged)
    targets = visible_targets(task)   # only dependency context is sliced; writable files and tests stay whole
    # Big files reach the model as outline + fragments (and are read by line numbers): not counted here.
    # The task's budget (default 8 000) never caps below the prompt itself: render() checks the exact room
    # (live 19.11 21:24: <id>_test, 11 662 bytes against a 28 000-character prompt, was refused here).
    packet({n: v for n, v in staged.items() if n not in big}, targets,
           max_tokens=max(task.context_budget, channels.PROMPT_LIMIT_CHARS))
    # The model may not create/replace its own permissions. The file is also
    # compared byte-for-byte after coding and after pytest.
    conf = (json.dumps(worker_policy(task, readable=sorted(big & set(task.read_files))), sort_keys=True, ensure_ascii=False,
                       indent=2) + "\n").encode("utf-8")
    (workdir / POLICY_FILE).write_bytes(conf)
    staged[POLICY_FILE] = conf
    return staged


def inspect_changes(task: Task, workdir: Path, staged: dict[str, bytes]) -> tuple[str, ...]:
    """Reject changed tests, other files, deletion and generated test weakening."""
    allowed = set(task.touch_files)
    unchanged = ((set(task.read_files) | set(task.tests)) - allowed) | {POLICY_FILE}
    found: dict[str, bytes] = {}
    for p in workdir.rglob("*"):
        if p.is_symlink():
            raise InvalidPlan("symlink created in working copy")
        if not p.is_file():
            continue
        rel = p.relative_to(workdir).as_posix()
        if rel != POLICY_FILE:
            safe_path(rel)
        if rel not in allowed | unchanged:
            raise InvalidPlan("unapproved file created: " + rel)
        found[rel] = safe_source(p)
    if set(found) - set(staged) - allowed:
        raise InvalidPlan("unapproved output")
    for name in unchanged:
        if name not in found or staged.get(name) != found[name]:
            raise InvalidPlan("acceptance input/test changed: " + name)
    for name in set(staged) & allowed:
        if name not in found:
            raise InvalidPlan("worker deleted source: " + name)
    return tuple(sorted(n for n in allowed if found.get(n) != staged.get(n)))


def neighbor_tests(root: Path, task: Task) -> list[str]:
    """Tests one import hop from the touched files (risk register #35): at most MAX_NEIGHBORS,
    only files that exist in ``root``, never the task's own tests. The graph is built over ``root``
    (the mirror of HEAD), not over the tool's tree. Any failure RAISES: the caller records
    ``neighbors_unavailable`` instead of silently treating it as "no neighbours"."""
    graph = affected_tests.Graph(Path(root))
    found, _, _ = affected_tests.affected(list(task.touch_files), radius=1, g=graph)
    out: list[str] = []
    for name in found:
        if name in task.tests or name in task.touch_files or name in out:
            continue
        if (Path(root) / name).is_file():
            out.append(name)
    return out[:MAX_NEIGHBORS]


DURATIONS_FILE = "tests/data/factory_durations.json"    # measured seconds per test file of the previous cloud run


def _known_seconds(root: Path) -> dict:
    """The recorded duration table of ``root`` (flat ``{test path: seconds}``); missing or malformed is just empty."""
    try:
        raw = json.loads((Path(root) / DURATIONS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {k: float(v) for k, v in raw.items()
            if isinstance(k, str) and isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0}


def gate_order(root: Path, names, first=()) -> list[str]:
    """Order of test runs: ``first`` (what failed last time) before everything else, then the fast before the heavy:
    by the recorded duration of the file, and for a file with none by its size scaled to the recorded ones (bytes
    when nothing is recorded at all). Stable, never drops or adds a name."""
    names = list(dict.fromkeys(names))
    head = set(first)
    secs = _known_seconds(root)

    def size(name: str) -> int:
        try:
            return (Path(root) / name.split("::", 1)[0]).stat().st_size
        except OSError:
            return 0
    ratios = sorted(secs[n.split("::", 1)[0]] / size(n) for n in names
                    if n.split("::", 1)[0] in secs and size(n) > 0)
    scale = ratios[len(ratios) // 2] if ratios else None

    def estimate(name: str) -> float:
        file = name.split("::", 1)[0]
        if file in secs:
            return secs[file]
        return size(name) * scale if scale else float(size(name))
    return ([n for n in names if n in head]
            + sorted((n for n in names if n not in head), key=lambda n: (estimate(n), n)))


def red_entries(ids, tests) -> list[str]:
    """The entries of ``tests`` (files or ``file::test``) that hold a test id of ``ids`` ('classname::name' as the
    gate records them: ``tests.test_x.Class::name``): what the last candidate was red on."""
    files = set()
    for one in ids:
        parts = str(one).split("::", 1)[0].split(".")
        for i, part in enumerate(parts):
            if part.startswith("test_"):
                files.add("/".join(parts[:i + 1]) + ".py")
                break
    return [t for t in tests if t.split("::", 1)[0] in files]


def staged_run(run, root: Path, tests, red=()):
    """One result for ``tests``: the entries that failed last time run ALONE first; still red (and not by the
    environment): that result is the answer, the rest never runs. Green or unclear: the rest runs and both are merged
    (a single run when there is nothing to split)."""
    tests = gate_order(root, tests, red)
    first = [t for t in tests if t in set(red)]
    if not first or len(first) == len(tests):
        return run(tests)
    one = run(first)
    if one.env_reason or (one.failed + one.errors > 0 and not one.env_failed):
        return one
    rest = [t for t in tests if t not in set(first)]
    return gate._merge([(tuple(first), one), (tuple(rest), run(rest))])


def candidate_tree(root: Path, workdir: Path, changed, into: Path) -> Path:
    """Full copy of the source tree with the candidate files laid over it: real tests import
    the whole package (conftest, sibling modules) that the model's narrow copy lacks."""
    tree = into / "tree"
    shutil.copytree(root, tree, ignore=COPY_IGNORE)
    for name in changed:
        dest = tree.joinpath(*name.split("/"))
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(workdir.joinpath(*name.split("/")), dest)
    return tree


def _note_read(result: dict, part: dict, workdir: Path | None) -> None:
    """Names of files the model read with its read tool (inside the work copy only, at most 10).
    Raw tool arguments are never kept. Event shape (best effort, see tests): part.tool == "read" and the
    path under part.state.input / part.input as filePath | file_path | path."""
    if workdir is None or str(part.get('tool') or part.get('name') or '').lower() != 'read':
        return
    state = part.get('state') if isinstance(part.get('state'), dict) else {}
    args = state.get('input') if isinstance(state.get('input'), dict) else part.get('input')
    if not isinstance(args, dict):
        return
    raw = next((args[k] for k in ('filePath', 'file_path', 'path') if isinstance(args.get(k), str)), None)
    if not raw:
        return
    if raw[:2] in ('//', chr(92) * 2) or (raw[1:2] == ':' and raw[2:3] not in ('/', chr(92))):
        return   # UNC (resolve() could wait on the network) and drive-relative "C:x" are never work-copy files
    try:
        base = Path(workdir).resolve()
        # an absolute raw replaces ``base``; ".." anywhere is resolved before the containment test
        name = (base / raw).resolve().relative_to(base).as_posix()
    except (OSError, ValueError, RuntimeError):
        return
    if name == '.' or name in result['files_read'] or len(result['files_read']) >= 10:
        return
    result['files_read'].append(name)


def event_summary(stdout: bytes, workdir: Path | None = None) -> dict:
    """Only allowlisted metadata; never persist raw prompts/tool arguments."""
    result = {'input_tokens': None, 'output_tokens': None, 'reasoning_tokens': None,
              'cache_read_tokens': None, 'cache_write_tokens': None, 'finish_reason': None,
              'tool_events': 0, 'provider_error': False, 'error_class': None,
              'http_status': None, 'text': '', 'steps': 0, 'files_read': [], 'last_step_tools': 0}
    since_step = 0
    for line in stdout.decode('utf-8', errors='replace').splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        part = event.get('part', {})
        if not isinstance(part, dict):
            continue
        if event.get('type') == 'error':
            result['provider_error'] = True
            error = event.get('error', {})
            if isinstance(error, dict):
                result['error_class'] = str(error.get('name', 'unknown'))[:80]
                data = error.get('data', {})
                if isinstance(data, dict) and type(data.get('statusCode')) is int:
                    result['http_status'] = data['statusCode']
        if event.get('type') == 'tool_use':
            result['tool_events'] += 1
            since_step += 1
            _note_read(result, part, workdir)
        if event.get('type') == 'text':
            result['text'] += str(part.get('text', ''))
        if event.get('type') == 'step_finish':
            result['steps'] += 1
            result['last_step_tools'], since_step = since_step, 0
            tokens = part.get('tokens', {})
            if isinstance(tokens, dict):
                # Kilo/OpenCode: part.tokens of step_finish is the usage of THAT step (one LLM call), not a running
                # total (opencode noninteractive.ts maps session.step.ended tokens 1:1), so the steps are summed.
                cache = tokens.get('cache') if isinstance(tokens.get('cache'), dict) else {}
                for field, value in (('input_tokens', tokens.get('input')), ('output_tokens', tokens.get('output')),
                                     ('reasoning_tokens', tokens.get('reasoning')),
                                     ('cache_read_tokens', cache.get('read')),
                                     ('cache_write_tokens', cache.get('write'))):
                    if type(value) is int and value >= 0:
                        result[field] = (result[field] or 0) + value
            result['finish_reason'] = part.get('reason')
    return result


def unified_diff(baseline: dict[str, bytes], workdir: Path, names, limit: int) -> str:
    """Redacted, truncated unified diff of the candidate against the baseline."""
    chunks = []
    for name in sorted(names):
        path = workdir.joinpath(*name.split("/"))
        if not path.is_file():
            continue
        old = baseline.get(name, b'').decode('utf-8', 'replace').splitlines(keepends=True)
        new = path.read_bytes().decode('utf-8', 'replace').splitlines(keepends=True)
        chunks.extend(difflib.unified_diff(old, new, 'a/' + name, 'b/' + name, n=2))
    text = redact(''.join(chunks))
    return text if len(text) <= limit else text[:limit] + DIFF_CUT % limit


# the cut of a diff named as a cut, not as the end of the change: live 20.11 07:48 a critic rejected a self-fix whose
# code had passed the gate as "truncated ... incomplete and syntactically invalid"
DIFF_CUT = '\n[the diff is cut here at %d characters; the rest of the change is not shown]\n'
GATE_PASSED = (' The candidate already compiles and passes the task tests (the gate ran them before you): never reject '
               'it for syntax, imports or the cut of the diff; judge what the change does.')


REVIEW_CHECKS = (
    'Check ALL of: (1) the behaviour is really fixed, no lost behaviour, no stubs, no incomplete '
    'error handling; (2) NO hard-coding: the candidate must not fit data or expectations to the '
    'test (special-casing test inputs, copying expected values) instead of fixing the behaviour; '
    '(3) NO scope creep: nothing outside the task and the listed files. A legitimate pass '
    'statement is not itself a defect. The task tests are the specification, fixed before the coder '
    'started: never reject a candidate by disputing what a test expects; judge only whether the code '
    'meets it honestly.')
# A code task's critics rejected a correct candidate three times by arguing with the guard test's expectation
# instead of the change (live 21.11): the tests are not theirs to judge.
# A unit_test task writes ONLY the test; its code task comes after it. Live 19.11 19:14-19:16: with the checks of a
# fix the reviewer rejected good tests "the patch only adds a test case but does not implement the fix".
REVIEW_CHECKS_TEST = (
    'This task writes ONLY a test: the fix is a separate later task, so the code under test stays unchanged and '
    'the new test is expected to FAIL on it now. Never reject it because the code is not fixed. Check ALL of: '
    '(1) the test imports the real code and calls it, and asserts the behaviour the task describes; (2) it fails '
    'on the current code because of the described defect and would pass once the defect is fixed; (3) NO stub: no '
    'MagicMock in place of the code under test, no assert False, no test that only checks that a name exists, no '
    'hard-coded counts of files or markers in the repository; (4) nothing outside the test file; (5) it does not '
    'replace (monkeypatch, fake) the function inside which the described behaviour happens, read its body and the '
    'comments at the call; (6) every function is called with the kind of arguments its signature and docstring take; '
    '(7) the defect it asserts is the one the task text names, on input of the kind the project really has: reject '
    'a test whose defect is the model\'s own guess ("might", "or has spaces/formatting") or whose input the task '
    'text and the code shown never produce.')
# (5) and (6), 20.11 02:55: two promoted tests could never be made green by a correct fix. <id> called
# diagnostics.reason_of(call marks) although it takes an exception or a token (unknown for anything else); <id> replaced
# controlled_host.say, inside which speech_text turns numbers into words, so the fake always saw digits.
# Owner: «турнир нескольких кандидатов с последовательной цепочкой критиков». A pass of the light engine
# asks up to TOURNAMENT_SIZE coders, each a different model, and every next one is told why the previous one failed;
# the first candidate that passes the mechanical checks (it changes the files, compiles, weakens no check) goes to the
# gate. Then up to REVIEW_PANEL critics of different models review it one after another, each with its own lens;
# the majority decides (the owner's cap is 4 rounds). A missing further model shortens the tournament, never
# fails the pass; a chain cut short never approves: the candidate stays pending for the next pass (review_chain_short,
# ESCALATE_AFTER in a row is BLOCKED).
TOURNAMENT_SIZE = 3
TOURNAMENT_NOTE = ('\nAnother model already tried this task in this pass and its answer could not be used: %s. Do not '
                   'repeat that mistake: copy every SEARCH line exactly from the code shown above, or give REPLACE FUNCTION '
                   'for a function shown whole.\n')
# <id>: a candidate that fails the test gate for real (not the environment, not an unknown neighbour) does not end the
# pass while the tournament has room: the next model sees the failing output and the diff of the previous one.
TOURNAMENT_GATE_NOTE = ('\nAnother model already tried this task in this pass; its change was applied and the tests '
                        'failed. Do not repeat that mistake.\nFailing test output:\n%s\n')
TOURNAMENT_DIFF_NOTE = '\nIts diff (do not repeat it):\n%s\n'
# live 20.11 03:18, one task: three candidates in a row answered CANNOT: _last_clause_question to the same view
TOURNAMENT_ASKED_NOTE = 'The code it asked for (%s) is shown above now: edit it.\n'
TOURNAMENT_OUTPUT_LIMIT = 1500
# live 21.11 (replay of 36 CANNOT runs): 27 asked for a function defined in the task's own files, 17 repeated the same
# CANNOT on the next attempt. What a model asked for is kept on the task row, so every later attempt shows it first.
ASKED_KEEP = 12


def remember_asked(row: dict, names) -> None:
    """Add ``names`` (the definitions a coder asked to see) to the task row's ``asked`` list: no duplicates, the
    newest ASKED_KEEP kept."""
    kept = [n for n in (row.get('asked') or []) if isinstance(n, str)]
    for name in (sorted(names) if isinstance(names, (set, frozenset)) else names):
        if name and name not in kept:
            kept.append(name)
    row['asked'] = kept[-ASKED_KEEP:]


def defined_names(task: Task, workdir: Path) -> frozenset:
    """Names of the functions and classes (nested too) defined in the python files the task may change."""
    found = set()
    for name in task.touch_files:
        if not name.endswith('.py'):
            continue
        try:
            tree = ast.parse(Path(workdir).joinpath(*name.split('/')).read_bytes().decode('utf-8', 'replace'))
        except (OSError, SyntaxError, ValueError):
            continue
        found |= {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
    return frozenset(found)


class _GateRetry:
    """A real test failure of one candidate: the arguments of the ONE rejection that settles the pass if no other
    model can try, the failing output for the next prompt and the names of the files the candidate changed.
    ``no_effect``: the test failed exactly as on the base (same_failure): the change missed the checked path."""
    def __init__(self, reject_args: tuple, diag: str, changed, no_effect: bool = False):
        self.reject_args, self.diag, self.changed = reject_args, diag, list(changed)
        self.no_effect = no_effect


# <id> class "a change without effect" (live 20.11 10:35-10:43: 17 of 18 passes reached the gate with a real edit and
# every attempt of a task failed with the very output of the unchanged base: the models edited code off the path the
# guard test checks, e.g. cue timers for a test about the words of an objection)
NO_EFFECT_NOTE = ('\nThe previous change had NO effect on the failing test: it fails exactly as it did before the '
                  'change, so the code it edited is not on the path this test checks. Find where the asserted '
                  'behaviour is decided and change that place.')
# Path-checked scope (live 20.11 12:19 on: 11 of 20 passes no_effect, 0 promotions): the red-before run of a code task
# records the functions its failing tests ran (GateResult.path). Those in the task's files are shown first and whole
# (at most PATH_FOCUS_MAX names); those outside are named, and a CANNOT or an edit block naming one of them widens the
# task by its module (the loop amends touch_files); the NO_EFFECT_BLOCK_AFTER-th no-effect on one base blocks the task
# with that list for Opus instead of more passes.
OFF_PATH_NOTE = ('\nThe failing test also runs, outside the files you may change: %s. If the asserted behaviour is '
                 'decided there, answer CANNOT: <that name>.')
PATH_FOCUS_MAX = 12
OFF_PATH_SHORT = 8
OFF_PATH_WAIT_S = 30
NO_EFFECT_BLOCK_AFTER = 4   # 21.11 (was 2)
_ADDRESS = re.compile(r'0x[0-9A-Fa-f]{4,}')
_WORKDIR = re.compile(r'task-[\w.-]+')
_SECONDS = re.compile(r'\b\d+(?:\.\d+)?s\b')


def same_failure(base_diag: str, cand_diag: str) -> bool:
    """The candidate's failing output is the base's (object addresses, work folders and durations aside)."""
    def norm(text):
        return _SECONDS.sub('?s', _WORKDIR.sub('task', _ADDRESS.sub('0x?', text or ''))).strip()
    return bool(norm(cand_diag)) and norm(base_diag) == norm(cand_diag)


# Execution-ranked selection: the critics get the mechanical execution report and answer a fixed rubric; up to
# REVIEW_PANEL critics of different models vote and the majority decides (2 of 3). A split with no further model goes
# to the mechanical ranking. The owner's cap is 4 rounds.
REVIEW_PANEL = 3
REVIEW_LENSES = (
    '',
    'You are the SECOND critic: judge on your own, then look at what the earlier critic said. Look for what it may '
    'have missed: an expected result of the task\'s own examples that the change or the test does not pin exactly (a '
    'check that only says a value changed accepts any wrong change), a case the task names that is not handled, a '
    'change the task did not ask for.',
    'You are the THIRD critic: the earlier critics disagree or only partly checked. Check that nothing the task asks '
    'for is missing and that the change cannot break the code around it (callers, error paths, other inputs of the '
    'same function). Reject only a concrete defect you can name with its line.')
RUBRIC_ASK = (
    'Answer with exactly this JSON and nothing else: {"defect_assert_line": "<the exact line of the test, copied '
    'character for character, that observes the defect the task names>", "fix_changes_value": "<what a correct fix '
    'changes at that line: the value before and after>", "independent_asserts": ["<every assert line of the test '
    'that does not depend on the code under test, e.g. a literal compared with a literal; empty list when there is '
    'none>"], "approved": true|false, "reasons": ["each concrete defect"]}. The candidate is approved only when the '
    'line is really in the test and no independent assert is listed.\n')
EXEC_REPORT_LIMIT = 1500
EXEC_PATH_NAMES = 12


def execution_report(base, hollow=(), extra_names=()) -> str:
    """The mechanical facts a critic gets beside the diff (measured by the gate, not an opinion): the output of the
    red-before run, the functions the failing tests ran, hollow findings, names the candidate adds beyond the task."""
    parts = []
    diag = redact(str(getattr(base, 'diag', '') or '')).strip()
    if diag:
        parts.append('Red-before output (the tests on the unchanged base):\n' + diag[-600:])
    path = tuple(getattr(base, 'path', ()) or ())
    if path:
        parts.append('Failing path (functions the failing tests ran): ' + ', '.join(
            '%s::%s' % (p[0], p[1]) if isinstance(p, (list, tuple)) and len(p) > 1 else str(p)
            for p in path[:EXEC_PATH_NAMES]))
    if hollow:
        parts.append('Hollow findings: ' + '; '.join(redact(str(h))[:120] for h in hollow))
    if extra_names:
        parts.append('Names the candidate adds beyond the task: ' + ', '.join(redact(str(n))[:60] for n in extra_names))
    return ('Mechanical execution report:\n' + '\n'.join(parts) + '\n')[:EXEC_REPORT_LIMIT] if parts else ''


def mechanically_ok(base, hollow=(), extra_names=()) -> bool:
    """The mechanical ranking of a candidate: the failing tests ran code (a failing path was measured) and nothing
    hollow or extra was found. It only breaks a tie between critics, never overrules a majority."""
    return bool(getattr(base, 'path', ())) and not hollow and not extra_names


def _squash(text: str) -> str:
    return ' '.join(str(text).split())


def rubric_problems(answer: dict, haystack: str) -> list[str]:
    """Why an answer of the critic is not an approval: the cited test line must literally be in the code shown, the fix
    must name the value it changes, and no assert independent of the code under test may be listed. A missing or
    malformed rubric is a problem, never an approval."""
    problems = []
    line = answer.get('defect_assert_line')
    if not isinstance(line, str) or len(_squash(line)) < 3:
        problems.append('critic rubric: defect_assert_line is missing')
    elif _squash(line) not in _squash(haystack):
        problems.append('critic rubric: the cited line is not in the test: ' + redact(_squash(line))[:120])
    fix = answer.get('fix_changes_value')
    if not isinstance(fix, str) or not fix.strip():
        problems.append('critic rubric: fix_changes_value is missing')
    asserts = answer.get('independent_asserts')
    if not isinstance(asserts, list):
        problems.append('critic rubric: independent_asserts is missing')
    elif [a for a in asserts if str(a).strip()]:
        problems.append('independent asserts that do not depend on the code under test: ' +
                        '; '.join(redact(_squash(a))[:100] for a in asserts if str(a).strip()))
    return problems


def panel_verdict(votes: list, final: bool, mechanical_ok: bool):
    """True / False when the majority of the panel (2 of REVIEW_PANEL) is reached; None while undecided. ``final``:
    no further critic can be asked; an even split then goes to the mechanical ranking, a single vote stays undecided
    (one critic never decides alone)."""
    need = REVIEW_PANEL // 2 + 1
    yes = sum(1 for v in votes if v)
    if yes >= need:
        return True
    if len(votes) - yes >= need:
        return False
    if final and len(votes) >= 2 and yes * 2 == len(votes):
        return bool(mechanical_ok)
    return None


def review_candidate(task: Task, workdir: Path, model: str, invoke, *,
                     baseline: dict[str, bytes] | None = None,
                     scratch: Path | None = None, lens: str = '', prior: tuple = (),
                     rejected: str = '', rubric: bool = False, execution: str = '') -> tuple[bool, list[str]]:
    """A separate call sees an immutable copy and returns ``(approved, reasons)``.

    ``rubric``: the critic answers the fixed rubric (RUBRIC_ASK) and an approval stands only when the cited test line is
    really in the code shown and no independent assert is listed; ``execution``: the mechanical report shown to it.

    Its opinion never grants DONE. A failed call or an unreadable answer raises ReviewFault
    (the reviewer's fault is not the candidate's strike)."""
    reviewer = replace(task, touch_files=(),
                       read_files=tuple(sorted(set(task.touch_files + task.read_files))))
    with tempfile.TemporaryDirectory(prefix='factory-review-', dir=scratch, ignore_cleanup_errors=True) as directory:
        review_root = Path(directory) / 'input'
        snapshot = prepare(workdir, reviewer, review_root)
        files_for_hint = [n for n in snapshot if n != POLICY_FILE]
        light = engine_for('review', reviewer) == 'light'   # no tools: no read/grep words (critic 19.11 18:5x)
        checks = (REVIEW_CHECKS_TEST if task.kind == 'unit_test' else REVIEW_CHECKS) + (' ' + lens if lens else '')
        # <id> (owner): the next critic sees the remarks of all earlier critics of this candidate
        earlier = ('Earlier critics of this same candidate said:\n' +
                   ''.join('- ' + redact(str(p))[:600] + '\n' for p in prior) +
                   'Find what they missed or got wrong; do not repeat their remarks.\n') if prior else ''
        told = ('Earlier candidates of this task were rejected for:\n' + rejected[-REVIEW_NOTE_LIMIT:] +
                '\nReject this candidate if it still has a defect named there.\n') if rejected else ''
        # acceptance 20.11 (<id> and six before): the critics saw only the title ("Тест для <id>") and judged "the
        # described defect" by the test's own comment. They get the task text the coder got (same redaction, same cap).
        lessons = paid_critic.lessons_for(task, rejected or '')   # owner: catches of the paid critic that free critics missed
        goal = getattr(task, 'goal', '') or ''
        said_goal = ('Task text (what the coder was asked):\n' + redact(scrub_paths(goal))[:1500] + '\n') if goal else ''
        head = ('Review this patch task: ' + redact(task.title) + '.\n' + said_goal + checks + GATE_PASSED + '\n' + told +
                (lessons + '\n' if lessons else '') +
                (' The task files are below: small files whole, a large file as its outline and the parts that '
                 'matter. Judge the candidate by its diff and the code shown; never reject it only because some '
                 'code is not shown.\n' if light else
                 ' Read only the explicitly supplied files (relative paths in your working directory: '
                 + ', '.join(sorted(files_for_hint)) + '); grep inside it is allowed, nothing outside it.\n') +
                earlier + (execution if rubric else '') +
                (RUBRIC_ASK if rubric else 'Return exactly JSON {"approved":true|false,"reasons":["each concrete defect"]}.\n'))
        files = {n: v for n, v in snapshot.items() if n != POLICY_FILE}
        full_diff = unified_diff(baseline, workdir, task.touch_files, REVIEW_DIFF_LIMIT) if baseline is not None else ''
        priority = frozenset(keywords_from(task.title, strict=False)
                             | identifier_tokens(getattr(task, 'goal', '') or ''))
        words = priority | keywords_from(full_diff)
        big = large_names(task, files)
        targets = visible_targets(task)
        review_budget = (channels.PROMPT_LIMIT_CHARS - len(head) - 250 -
                         (REVIEW_DIFF_LIMIT if baseline is not None else 0))
        body = render(files, targets, large=big, keywords=words, budget_chars=review_budget,
                      small_tokens=max(task.context_budget, review_budget),
                      priority=priority, hint=LIGHT_REVIEW_HINT if light else REVIEW_HINT, tools=not light)
        room = channels.PROMPT_LIMIT_CHARS - len(head) - len(body) - 250  # the diff takes only what is left
        diff = ''
        if baseline is not None and room > 300:
            diff = unified_diff(baseline, workdir, task.touch_files, min(REVIEW_DIFF_LIMIT, room))
        prompt = head + ('Candidate diff:\n' + diff + '\n' if diff else '') + body
        rc, stdout, _ = invoke(reviewer, review_root, model, prompt_override=prompt)
        if rc != 0 or inspect_changes(reviewer, review_root, snapshot):
            raise ReviewFault('reviewer call failed rc=%s' % rc)
        summary = event_summary(stdout)
        if summary['provider_error'] or summary['finish_reason'] in ('length', 'max_tokens'):
            raise ReviewFault('reviewer provider error or truncated answer')
        text = summary['text'].strip()
        try:   # the first JSON object of the answer: free models wrap it in prose or a ```json fence
            answer, _ = json.JSONDecoder().raw_decode(text[text.index('{'):])
        except ValueError as error:
            raise ReviewFault('reviewer answer is not JSON') from error
        if not isinstance(answer, dict) or type(answer.get('approved')) is not bool:
            raise ReviewFault('reviewer answer has no verdict')
        reasons = answer.get('reasons', answer.get('reason', []))
        if isinstance(reasons, str):
            reasons = [reasons]
        reasons = [str(r)[:400] for r in reasons if str(r).strip()] if isinstance(reasons, list) else []
        if rubric and answer['approved']:
            def _is_test(name):
                low = str(name).replace('\\', '/').lower()
                return '/tests/' in '/' + low or low.rsplit('/', 1)[-1].startswith('test_') or '_test.' in low
            tests_shown = {n: v for n, v in files.items() if _is_test(n)}
            # the cited line must be in a test file; with no test file shown the code and the diff are all there is
            shown = tests_shown or files
            seen = '\n'.join([v.decode('utf-8', 'replace') if isinstance(v, bytes) else str(v)
                              for v in shown.values()] + ([] if tests_shown else [diff]))
            problems = rubric_problems(answer, seen)
            if problems:
                return False, problems + reasons
        if answer['approved']:
            return True, reasons          # an approving critic keeps its remarks: the next critic sees them
        return False, reasons or ['rejected without a stated reason']


REFERENCE_MAX = 5000   # the old-branch diff of a port task in the coder prompt; the view of the files gets the rest


def port_reference(root: Path, task: Task) -> str:
    """The diff of the old-branch commit a port task names (factory_port.reference: code files only, never a test or
    a key), '' for any other task or on any fault: a missing reference costs the model its example, never the pass."""
    sha = getattr(task, 'port_from', '')
    if not sha or task.kind == 'unit_test':
        return ''
    try:
        from . import factory_port
        return factory_port.reference(root, sha, max_chars=REFERENCE_MAX)
    except Exception:  # noqa: BLE001
        return ''


PORT_FOCUS_MAX = 8     # how many of the functions the old commit changed the coder's view asks for first


def port_focus(repo: Path, task: Task) -> frozenset:
    """The functions the old-branch commit of a port task changed, as names the coder's view shows first (whole when the
    room allows): the model edits their present versions, not whatever a stale suspect list names (live 20.11 09:34: the
    view showed ``_continuation`` of another module while ``_fast_release``, the function the commit changed, was only in
    the outline). Identifier-like names only: ``tick`` or ``release`` would pull every method of that name, a dunder
    every constructor. Empty for any other task and on any fault."""
    sha = getattr(task, 'port_from', '')
    if not sha or task.kind == 'unit_test':
        return frozenset()
    try:
        from . import factory_port
        names = factory_port.changed_names(repo, sha)
    except Exception:  # noqa: BLE001
        return frozenset()
    own = [n for n in names if identifier_tokens(n) == {n} and not n.startswith('__')]
    return frozenset(own[:PORT_FOCUS_MAX])


def build_coder_prompt(task: Task, visible: dict[str, bytes], feedback: str | None = None,
                       prev_diff: str = '', *, goal: str | None = None, failing: str = '',
                       light: bool = False, asked: frozenset = frozenset(), reference: str = '',
                       focus: frozenset = frozenset(), off_path=()) -> str:
    """The ONE builder of the coder prompt (used by the pass and by model_attempt's default). ``light``: the
    prompt of the light engine, which has no tools: no read/grep instructions (live 19.11 17:48-17:50:
    with them the model answered "CANNOT: requires access outside the provided files"). ``asked``: definitions
    a model of this pass asked to see; with the ones the feedback names (asked_names) they are shown first.
    ``off_path``: functions the failing test runs outside the task's files (OFF_PATH_NOTE)."""
    asked = frozenset(asked) | asked_names(feedback or '')
    targets = visible_targets(task)
    if task.kind == 'unit_test':
        # its own test file is the one file it writes: never "read-only" or "do not modify tests" (critic 19.11)
        core = ("Write ONLY the test of task " + task.id + ": " + redact(task.title) +
                ". Create or change only the test file: " + ", ".join(task.touch_files) +
                ". The code it tests is read-only. Do not execute deployment, read parent folders, "
                "or use network tools other than the configured model.\n" + UNIT_TEST_RULES)
    else:
        core = ("Implement ONLY task " + task.id + ": " + redact(task.title) +
                ". Change only: " + ", ".join(task.touch_files) +
                ". Read-only tests: " + ", ".join(task.tests) +
                ". Do not modify tests, execute deployment, read parent folders, "
                "or use network tools other than the configured model.")
    if light:
        core += ("\nThe task files are below: small files whole, a large file as its outline and the parts "
                 "that matter for the task.")
    else:
        core += ("\nAll task files are in your working directory under these relative paths: " +
                 ", ".join(sorted(set(task.touch_files) | set(task.read_files) | set(task.tests))) +
                 ". Read a file with the read tool by its exact relative path (use offset/limit for a line "
                 "range); find a function by name with grep inside this directory; never look for files "
                 "outside the working directory.")
    goal = getattr(task, 'goal', '') if goal is None else goal
    if goal:
        core += "\nTask text:\n" + redact(scrub_paths(goal))[:1500]
    if failing and task.kind != 'unit_test':
        core += "\nFailing on the base now (must pass after your change):\n" + redact(failing)[:1500]
    if off_path and task.kind != 'unit_test':
        core += OFF_PATH_NOTE % ', '.join(off_path)
    if reference and task.kind != 'unit_test':
        # a port task: the behaviour was built before on an old branch, in the code's old layout (live 20.11: 35 open
        # rows say so, their guard tests are red on the head of the unified code)
        core += ("\nThis behaviour was built before on an old branch, in the old layout of the code (commit " +
                 str(getattr(task, 'port_from', '')) + "). Its diff below is a reference, not a patch: files, names "
                 "and lines differ here, so copy every SEARCH line from the current files shown further below, never "
                 "from this diff. Bring the same behaviour into the files you may change:\n" +
                 redact(scrub_paths(reference))[:REFERENCE_MAX])
    if task.kind == 'unit_test':
        core += (" Write the test so that it FAILS on the current code because of the described "
                 "defect and would pass once the defect is fixed.")
        if task.backlog_id:
            core += " The FIRST line of the test file must be exactly: # factory-backlog-id: " + task.backlog_id
    if feedback:
        core += "\nThe previous candidate was rejected. Feedback:\n" + redact(feedback)
    tests_text = ' '.join(visible[n].decode('utf-8', 'replace') for n in task.tests if n in visible)
    tests_shown = {n: visible[n] for n in task.tests if n in visible}
    priority = frozenset(keywords_from(task.title, strict=False) | identifier_tokens(feedback or '')
                         | identifier_tokens(goal or '') | asked | failing_names(failing, tests_shown)
                         | frozenset(focus))
    words = priority | keywords_from(tests_text, prev_diff, feedback)
    budget = channels.PROMPT_LIMIT_CHARS - REVIEW_OVERHEAD - len(core) - (2500 if prev_diff else 0) - 60
    core += '\n' + render(visible, targets, large=large_names(task, visible), keywords=words,
                          budget_chars=budget, small_tokens=max(task.context_budget, budget), priority=priority,
                          asked=asked, pinned=pinned_targets(task),
                          **({'hint': LIGHT_HINT, 'tools': False} if light else {}))
    room = channels.PROMPT_LIMIT_CHARS - len(core) - 200
    if prev_diff and room > 300:
        core += "\nDiff of the rejected candidate (do not repeat its mistake):\n" + prev_diff[:room]
    return core


def _default_prompt(task: Task, workdir: Path, light: bool = False) -> str:
    """The coder prompt of a direct call without a prepared prompt (both engines build it the same way)."""
    visible = {name: safe_source(workdir / name) for name in
               sorted(set(task.touch_files + task.read_files + task.tests))
               if (workdir / name).exists()}
    return build_coder_prompt(task, visible, light=light)


def model_attempt(task: Task, workdir: Path, model: str, timeout: int,
                  *, prompt_override: str | None = None, steps: int | None = None,
                  key_env: str = 'GOOGLE_GENERATIVE_AI_API_KEY') -> tuple[int, bytes, bytes]:
    """Invoke Kilo with a frozen project policy and a temporary clean profile.

    The explicitly selected Google auth key is the only provider credential
    forwarded. No secret is placed in argv, model prompt or kilo.jsonc.
    The prompt travels in argv (Kilo takes the message as an argument; its stdin mode is not
    documented, so it is not assumed): the 28 000-character limit keeps it far below the OS limit.
    """
    if task.only_opus:
        return 125, b'', b'opus-only-task'
    prompt = prompt_override if prompt_override is not None else _default_prompt(task, workdir)
    if len(prompt) > channels.PROMPT_LIMIT_CHARS:
        return 125, b'', b'context-too-large'
    try:
        command = kilo_argv()
    except FileNotFoundError:
        # Preserve direct callers' executable lookup. CLI preflights availability.
        command = ['kilo']
    except (ValueError, OSError):
        return 125, b'', b'invalid-kilo-entrypoint'
    # Kilo puts its working directory into the system prompt of EVERY call: nothing under %TEMP%/the profile
    with tempfile.TemporaryDirectory(prefix="factory-kilo-home-", dir=workdir.parent, ignore_cleanup_errors=True) as home:
        base = Path(home)
        dirs = {name: base / name for name in
                ("config", "cache", "data", "appdata", "localappdata", "npm-cache")}
        for dest in dirs.values():
            dest.mkdir(parents=True, exist_ok=True)
        env = {k: v for k, v in os.environ.items() if k.upper() in ENV_ALLOW}
        env.update(HOME=home, USERPROFILE=home,
                   XDG_CONFIG_HOME=str(dirs["config"]),
                   XDG_CACHE_HOME=str(dirs["cache"]),
                   XDG_DATA_HOME=str(dirs["data"]),
                   APPDATA=str(dirs["appdata"]),
                   LOCALAPPDATA=str(dirs["localappdata"]),
                   NPM_CONFIG_CACHE=str(dirs["npm-cache"]),
                   TEMP=home, TMP=home, PYTHONUTF8="1",
                   PYTHONIOENCODING="utf-8")
        provider = model.split('/')[0]
        auth_env = 'OPENROUTER_API_KEY' if provider == 'openrouter' else 'GOOGLE_GENERATIVE_AI_API_KEY'
        credential = os.environ.get(key_env, '')
        if credential:
            env[auth_env] = credential
        # Kilo deliberately ignores {env:VAR} in untrusted project configs.
        # Supply the reference in a trusted PROCESS-OWNED config, while the
        # project kilo.jsonc remains the immutable deny-first permissions file.
        env["KILO_CONFIG_CONTENT"] = json.dumps(kilo_config(provider, auth_env, steps))
        args = [*command, "run", "--pure", "--auto", '--agent', 'factory',
                "--format", "json", "--model", model, prompt]
        try:
            if os.environ.get('FACTORY_KILO_ENTRY') or shutil.which('kilo'):
                p = run_owned(args, cwd=workdir, env=env, timeout=timeout)
            else:
                p = subprocess.run(args, cwd=workdir, env=env,
                                   capture_output=True, timeout=timeout, shell=False)
            return p.returncode, p.stdout, p.stderr
        except subprocess.TimeoutExpired:
            return 124, b"", b"worker-timeout"


# ---- The light engine (owner: small edits and reviews through fast calls, Kilo only for multi-file
# edits). ONE REST request instead of a Kilo agent loop. The coder prompt already carries the files (render():
# small files whole, keyword slices of large ones), so the model answers at once with SEARCH/REPLACE blocks and the
# runner applies them to the approved files only: the triage localises, one edit, the deterministic gate decides
# (the Agentless scheme). The answer comes back as a Kilo-shaped event stream, so event_summary(), classify(),
# reconcile() and the telemetry stay ONE path for both engines. Live evidence 19.11 17:04-17:13: three Kilo runs
# of a one-file task spent all 8 steps reading files that were already in the prompt and made no edit.
# a coder task that changes more files is a multi-file edit: Kilo. 3 since 20.11 (telemetry of the whole run: Kilo 0 of
# 14 passes ever reached a review, every one of the 17 promoted candidates came from the light engine; 08:44-08:46 a
# 3-file row burned its three passes on 'steps exhausted'); the triage's MAX_TOUCH is 3, so no triaged task goes to Kilo
LIGHT_MAX_FILES = 5   # 21.11 (was 3): the same as the triage's MAX_TOUCH
LIGHT_OVERHEAD_TOKENS = 600      # the rules below and the chat wrapper (Kilo: 5 300-7 300)
LIGHT_TIMEOUT_S = 180
LIGHT_MAX_OUTPUT = 8192
LIGHT_REASONING_TOKENS = 2048
LIGHT_ENDPOINTS = {'google': 'https://generativelanguage.googleapis.com/v1beta/openai/chat/completions',
                   'openrouter': 'https://openrouter.ai/api/v1/chat/completions'}
# The bound of an explicit day budget of model calls: above the capacity of every free key (~60 000 a day, 20.11);
# the loop passes the registry's capacity (factory_loop.Loop._call_budget), each channel's rpd stays its limit.
MAX_MODEL_CALLS = 100_000
# ERROR_PATTERNS 'inline-thought' (live 20.11): Gemma 4 writes its reasoning into the answer (<thought>...), cannot be
# told so by the API ('Thinking budget is not supported for this model', 400) and ran to the 8192 cap in ~175 s on
# coder calls; with this line its answers came without the section (probe 2 of 2, 3 of 3 with it before). Every light
# call starts with it; a leading block that still comes is stripped (_LIGHT_THOUGHT).
NO_THOUGHT = "Answer at once: do not think aloud, write no <thought> or <think> section. "
LIGHT_EDIT_RULES = (
    NO_THOUGHT + "You are a precise code editor. This call has NO tools: everything you may use is in the message. Change "
    "only the allowed files. Answer ONLY with edit blocks, no analysis before them. A block is: the file path on "
    "its own line; a line <<<<<<< SEARCH; lines copied EXACTLY from the shown file (enough to be unique, never "
    "line numbers or omission markers); a line =======; the new lines; a line >>>>>>> REPLACE. An empty SEARCH "
    "part creates a new file (or fills an empty one) with the new lines. Several blocks are allowed. If the "
    "code you must change is not shown, answer one line: CANNOT: and the name of the function you need. To "
    "replace a whole function or method instead, write the line REPLACE FUNCTION <path> <name> (name: func or "
    "Class.method), then a ```python fence with the complete new definition, then a closing ``` line. Use it "
    "only for a function shown WHOLE in the message, never for one shown in part; write every line of it, "
    "never ... or a comment instead of code.")
LIGHT_HINT = ("The file is large: only its outline and the parts below are shown. Copy SEARCH lines from the "
              "shown parts; if the code to change is not shown, answer CANNOT: and the function name. REPLACE FUNCTION "
              "only for a function shown whole.")
LIGHT_REVIEW_RULES = (NO_THOUGHT + "You review a code patch. This call has NO tools: everything you may use is in "
                      "the message. Answer with the JSON verdict only.")
_LIGHT_NAME = re.compile(r'[\w./\\-]+\.[A-Za-z0-9]+')
# Gemma 4 on the OpenAI-compatible endpoint puts its reasoning before the answer (<thought>...</thought>, live 19.11);
# other free models use <think>. A draft edit inside it must never be applied, and the verdict JSON follows it.
# Only a LEADING block: the same tags inside a REPLACE (code that strips them) are the edit itself (critic 19.11).
_LIGHT_THOUGHT = re.compile(r'^\s*<(thought|think)>.*?(?:</\1>|\Z)\s*', re.S | re.I)


def _example_function(task: Task, workdir) -> str:
    """A function of the first touch file that the title or the goal names (``Class.method`` or a plain name), else
    the first one of the file; '' when the file is no readable Python."""
    import ast
    first = task.touch_files[0]
    try:
        tree = ast.parse((Path(workdir).joinpath(*first.split('/'))).read_bytes().decode('utf-8'))
    except (OSError, UnicodeDecodeError, SyntaxError, ValueError, RecursionError, MemoryError, TypeError):
        return ''
    names = [n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    for c in (n for n in tree.body if isinstance(n, ast.ClassDef)):
        names.extend('%s.%s' % (c.name, m.name) for m in c.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)))
    said = re.findall(r'[^\W\d]\w*(?:\.[^\W\d]\w*)?', '%s %s' % (task.title, task.goal))
    for word in said:
        hit = [n for n in names if n == word] or [n for n in names if n.rpartition('.')[2] == word and '.' in n]
        if hit:
            return hit[0]
    return names[0] if names else ''


def light_rules(task: Task, workdir=None) -> str:
    """The coder's system text with the task's real file paths (live 19.11: a placeholder path in the format
    example was copied literally and became 'a block for a file outside the task'). The function in the example
    is a real one of the first file when ``workdir`` is given."""
    first = task.touch_files[0]
    name = (_example_function(task, workdir) if workdir is not None else '') or 'Class.method'
    leaf = name.rpartition('.')[2]
    return (LIGHT_EDIT_RULES + "\nAllowed files: " + ", ".join(task.touch_files) + ".\nThe shape of a block:\n"
            + first + "\n<<<<<<< SEARCH\n(old lines)\n=======\n(new lines)\n>>>>>>> REPLACE"
            + "\nor, for a whole function shown whole:\nREPLACE FUNCTION " + first + " " + name + "\n```python\n"
            "def " + leaf + "(...):\n    (the whole new definition, every line)\n```")


def path_trace(task: Task) -> tuple:
    """The source prefixes whose functions the red-before run records for a code task: the top folder of each touch
    file (a top-level file: itself); () for any other kind."""
    if task.kind != 'code':
        return ()
    return tuple(sorted({f.split('/', 1)[0] + '/' if '/' in f else f for f in task.touch_files}))


def cannot_names(payload: str) -> list:
    """The names a CANNOT answer gives: a lone word as it is (``CANNOT: provider``); in a sentence only the code-like
    words (with ``_``, ``.``, ``/`` or an inner capital), so prose (``requires access outside the files``) never
    matches a same-named function of the path by accident."""
    words = re.findall(r'[\w./-]+', payload or '')
    if len(words) <= 1:
        return words
    return [w for w in words if any(c in w for c in '_./') or any(c.isupper() for c in w[1:])]


_SCAN_SKIP = frozenset(('.git', 'node_modules', '__pycache__', 'venv', '.venv', 'site-packages', 'build', 'dist'))
_SCAN_MAX_FILES = 20000


def _repo_py_files(root) -> list:
    """Repo-relative paths (posix) of the ``.py`` files under ``root``: the one code map of a CANNOT answer."""
    out = []
    for cur, dirs, files in os.walk(str(root)):
        dirs[:] = [d for d in dirs if d not in _SCAN_SKIP and not d.startswith('.')]
        for f in files:
            if f.endswith('.py'):
                out.append(os.path.relpath(os.path.join(cur, f), str(root)).replace(os.sep, '/'))
        if len(out) > _SCAN_MAX_FILES:
            break
    return out


def repo_scope_target(root, name: str, touch=(), kind='code'):
    """The repo file a CANNOT name means when it lies outside ``touch``: an existing file (path, or a name found in
    exactly one place) or a function/class defined in exactly one file; None when absent, ambiguous, already in the
    task or forbidden (gate.is_forbidden: privacy, tests of other rows, the factory's own code). Never raises."""
    try:
        name = (name or '').strip().strip('`\'"*()[]:;,').replace(chr(92), '/')
        while name.startswith('./'):
            name = name[2:]
        if not name:
            return None
        have = {str(t).replace(chr(92), '/') for t in touch}

        def usable(rel):
            return rel not in have and not gate.is_forbidden(rel, kind, touch)
        direct = Path(root) / name
        if '/' in name or name.endswith('.py') or name.startswith('.'):
            if not name.endswith('.py'):
                return None           # code files only: .env, keys, data and configs are never a scope
            if direct.is_file() and '..' not in name.split('/'):
                return name if usable(name) else None
            hits = [f for f in _repo_py_files(root) if f.endswith('/' + name) and usable(f)]
            return hits[0] if len(hits) == 1 else None
        if not re.fullmatch(r'[A-Za-z_]\w*(\.[A-Za-z_]\w*)*', name):
            return None
        leaf = name.rpartition('.')[2]
        rx = re.compile(r'^[ \t]*(?:async[ \t]+)?(?:def|class)[ \t]+' + re.escape(leaf) + r'\b', re.M)
        hits = []
        for rel in _repo_py_files(root):
            if rel not in have and gate.is_forbidden(rel, kind, touch):
                continue
            try:
                p = Path(root) / rel
                if p.stat().st_size < 1_000_000 and rx.search(p.read_text(encoding='utf-8', errors='replace')):
                    if rel in have:
                        return None   # defined in the task's own files: the model must look there, not widen
                    hits.append(rel)
            except OSError:
                continue
        return hits[0] if len(hits) == 1 else None
    except Exception:  # noqa: BLE001 - a widening is an extra: without it the CANNOT is judged as before
        return None


def _cannot_key(text: str, clean=lambda s: s) -> str:
    """A CANNOT text as one comparable key: words only, folded, cut where the feedback line cuts it."""
    return re.sub(r'\W+', ' ', clean(redact(text or ''))[:150]).strip().casefold()


def cannot_repeats(feedback, payload: str, clean=lambda s: s) -> bool:
    """True when the newest gate remark of the task is a CANNOT with the same text as ``payload`` (twice in a row)."""
    key = _cannot_key(payload, clean)
    if not key:
        return False
    for item in reversed(list(feedback or [])):
        text = str(item.get('text', '')) if isinstance(item, dict) else ''
        if not isinstance(item, dict) or item.get('source') != 'gate' or text.startswith(('[infra] ', REPEAT_MARK)):
            continue
        said = re.search(r'CANNOT:\s*(.*)', text, re.S)
        return bool(said) and _cannot_key(said.group(1), clean) == key
    return False


def outside_names(text: str, allowed: tuple) -> list:
    """The file names an answer's edit blocks aimed at outside ``allowed`` (file-name lines, REPLACE FUNCTION paths)."""
    names = []
    for line in (text or '').replace('\r\n', '\n').split('\n'):
        s = line.strip()
        head = _FUNC_HEAD.fullmatch(_func_clean(s)) if _FUNC_START.match(_func_clean(s)) else None
        name = head.group(1) if head else s
        if name and not name.startswith('```') and _light_target(name, allowed) == '':
            names.append(name.strip('`*#:').strip().replace(chr(92), '/'))
    return names


def engine_for(role: str, task: Task) -> str:
    """'light' for every review and for a coder task of at most LIGHT_MAX_FILES files, else 'kilo'."""
    return 'light' if role == 'review' or len(task.touch_files) <= LIGHT_MAX_FILES else 'kilo'


def _light_target(line: str, allowed: tuple) -> str | None:
    """The allowed file a file-name line names; '' for a file outside the task; None when it is no file name."""
    name = line.strip().strip('`*#:').strip().replace(chr(92), '/')
    while name.startswith('./'):
        name = name[2:]
    if not _LIGHT_NAME.fullmatch(name):
        return None
    if name in allowed:
        return name
    hits = [a for a in allowed if a.endswith('/' + name) or name.endswith('/' + a)]
    return hits[0] if len(hits) == 1 else ''


class _FuncTarget(str):
    """The 'search' part of a function block: the name (func or Class.method) of the definition to replace."""


class _Blocks(list):
    """The parsed blocks; ``problems`` = {why: count} of function blocks that could not be read (never applied)."""
    problems: dict


_NAME = r'[^\W\d]\w*'
_FUNC_START = re.compile(r'REPLACE\s+FUNCTION\b', re.I)
_FUNC_HEAD = re.compile(r'REPLACE\s+FUNCTION\s+(\S+)\s+(%s(?:\.%s)?)(?:\s*\(\s*\))?' % (_NAME, _NAME), re.I)
_FENCE = re.compile(r'\s*(`{3,})')
FUNC_SHAPE = 'REPLACE FUNCTION <path> <name>, then a ```python fence, the whole definition, a closing ``` line'


def _func_clean(line: str) -> str:
    return re.sub(r'[`*]', '', line).strip('#: \t')


def _function_block(lines: list, i: int, allowed: tuple):
    """Read the function block whose header is ``lines[i]``: ``(next line, file or None, block or None, problem or
    None, outside)``. A blank line between the header and the fence is fine; the fence closes on a whole line of at
    least as many backticks as it opened with."""
    head = _FUNC_HEAD.fullmatch(_func_clean(lines[i]))
    if head is None:
        return i + 1, None, None, 'a REPLACE FUNCTION line gave no block; shape: ' + FUNC_SHAPE, 0
    name = _light_target(head.group(1), allowed)
    j = i + 1
    while j < len(lines) and not lines[j].strip():
        j += 1
    fence = _FENCE.match(lines[j]) if j < len(lines) else None
    if fence is None:
        return i + 1, name or None, None, 'REPLACE FUNCTION block without a ``` fence; shape: ' + FUNC_SHAPE, 0
    closing = re.compile(r'\s*`{%d,}\s*' % len(fence.group(1)))
    k = j + 1
    while k < len(lines) and not closing.fullmatch(lines[k]):
        k += 1
    if k >= len(lines):
        return len(lines), name or None, None, 'REPLACE FUNCTION block without a closing ``` line', 0
    if not name:
        return k + 1, None, None, None, 1
    body = lines[j + 1:k]
    if any(x.strip().startswith('<<<<<<<') and 'SEARCH' in x for x in body):
        return k + 1, name, ('inner', parse_edit_blocks('\n'.join(body), (name,))), None, 0
    return k + 1, name, (name, _FuncTarget(head.group(2)), '\n'.join(body)), None, 0


def parse_edit_blocks(text: str, allowed: tuple) -> tuple[list, int]:
    """``([(file, search, replace)], blocks for a file outside the task)``. The file of a block is the last
    file-name line before it; a block without one belongs to the only allowed file. An unterminated block is
    never applied; a function block that cannot be read is named in ``blocks.problems``."""
    lines = text.replace('\r\n', '\n').split('\n')
    blocks, outside, current, i = _Blocks(), 0, None, 0
    blocks.problems = {}
    while i < len(lines):
        s = lines[i].strip()
        if _FUNC_START.match(_func_clean(s)):
            i, name, got, why, out = _function_block(lines, i, allowed)
            outside += out
            if name:
                current = name
            if why:
                blocks.problems[why] = blocks.problems.get(why, 0) + 1
            if got is not None and got[0] == 'inner':
                blocks.extend(got[1][0])
                outside += got[1][1]
                for w, n in got[1][0].problems.items():
                    blocks.problems[w] = blocks.problems.get(w, 0) + n
            elif got is not None:
                blocks.append(got)
            continue
        if s.startswith('<<<<<<<') and 'SEARCH' in s:
            # the separator and the end are whole lines: a longer ===== underline inside SEARCH is text
            j = i + 1
            while j < len(lines) and lines[j].strip() != '=======':
                j += 1
            k = j + 1
            while k < len(lines) and lines[k].strip() != '>>>>>>> REPLACE':
                k += 1
            if k >= len(lines):
                break
            name = current if current is not None else (allowed[0] if len(allowed) == 1 else '')
            if name:
                blocks.append((name, '\n'.join(lines[i + 1:j]), '\n'.join(lines[j + 1:k])))
            else:
                outside += 1
            i = k + 1
            continue
        if s and not s.startswith('```'):
            hit = _light_target(s, allowed)
            if hit is not None:
                current = hit
        i += 1
    return blocks, outside


def _line_hits(text: str, search: str) -> list[int]:
    """Starts of the exact occurrences of ``search`` that begin and end on line boundaries (a SEARCH that is the
    head of a longer line, '    return x' in '    return x_list', is no occurrence: critic 19.11)."""
    hits, start = [], 0
    while True:
        i = text.find(search, start)
        if i < 0:
            return hits
        end = i + len(search)
        if (i == 0 or text[i - 1] == '\n') and (end == len(text) or text[end] == '\n' or search.endswith('\n')):
            hits.append(i)
        start = i + 1


def _replace_once(text: str, search: str, replace: str) -> str | None:
    """``text`` with the ONE occurrence of ``search`` replaced; None when it is absent or ambiguous."""
    return _replace_once_how(text, search, replace)[0]


def _replace_once_how(text: str, search: str, replace: str) -> tuple[str | None, str]:
    """``(new text or None, matcher)``. Matchers in order: 'exact' (whole lines), 'rstrip' (trailing spaces of
    lines ignored), 'shifted' (one common indent prefix), 'squeezed' (whitespace inside a line ignored, one place
    only), 'repair' (factory_patterns: a view line, a reflowed line). Ambiguous at a matcher: None, no later
    matcher is tried (a second place is a second place)."""
    hits = _line_hits(text, search)
    if len(hits) == 1:
        return text[:hits[0]] + replace + text[hits[0] + len(search):], 'exact'
    if len(hits) > 1:
        return None, ''
    lines = text.split('\n')
    want = [line.rstrip() for line in search.split('\n')]
    while want and not want[-1]:
        want.pop()
    while want and not want[0]:
        want.pop(0)
    if not want:
        return None, ''
    n = len(want)
    hits = [i for i in range(len(lines) - n + 1) if [line.rstrip() for line in lines[i:i + n]] == want]
    if len(hits) == 1:
        return '\n'.join(lines[:hits[0]] + replace.split('\n') + lines[hits[0] + n:]), 'rstrip'
    if hits:
        return None, ''
    shifted = _replace_shifted(lines, want, replace)
    if shifted is not None:
        return shifted, 'shifted'
    squeezed = _replace_squeezed(lines, want, replace)
    if squeezed is not None:
        return squeezed, 'squeezed'
    from .factory_patterns import repair     # ERROR_PATTERNS: a view line or a reflowed line, one place only
    fixed = repair(text, search, replace)
    return fixed, ('repair' if fixed is not None else '')


_COMMENT = chr(0)      # marks where a comment starts inside _squeeze
_DEF_HEAD = re.compile(r'(?:async\s+def|def|class)\s')


def _squeeze(line: str) -> str:
    """The line with the whitespace OUTSIDE string literals removed, but for one space kept between two word
    characters ('not x', 'return x' stay two words); a comment is cut and a trailing ':' dropped on a def/class
    line only. The literals stay exact, so two different code lines never collapse into one key."""
    out, quote, i, n = [], '', 0, len(line)
    while i < n:
        c = line[i]
        if quote:
            out.append(c)
            if c == '\\' and i + 1 < n:
                out.append(line[i + 1])
                i += 1
            elif c == quote:
                quote = ''
        elif c in '"\'':
            quote = c
            out.append(c)
        elif c == '#':
            out.append(_COMMENT)            # a comment start: kept as a marker, cut below on a def line only
            out.append(line[i:])
            break
        elif c in ' \t':
            j = i
            while j < n and line[j] in ' \t':
                j += 1
            if out and j < n and (out[-1][-1:].isalnum() or out[-1][-1:] == '_') and \
                    (line[j].isalnum() or line[j] == '_'):
                out.append(' ')
            i = j - 1
        else:
            out.append(c)
        i += 1
    key = ''.join(out)
    head = _DEF_HEAD.match(line.lstrip()) is not None
    code, mark, comment = key.partition(_COMMENT)
    if head:
        key = code.rstrip()
        return key[:-1].rstrip() if key.endswith(':') else key
    return code + ('#' + comment[1:] if mark else '')


_LITERAL = re.compile(r'''"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*\'''')


def _bracket_depth(line: str) -> int:
    """Brackets a code line opens minus the ones it closes (string literals and the comment left out)."""
    code = _LITERAL.sub('', line).partition('#')[0]
    return sum(code.count(c) for c in '([{') - sum(code.count(c) for c in ')]}')


def _replace_squeezed(lines: list, want: list, replace: str) -> str | None:
    """The SEARCH lines equal ONE place of the file once the whitespace inside each line is ignored (the file may be
    written compactly, 'f(a,b)', the model in PEP8, 'f(a, b)'); line breaks must agree. The REPLACE lines stay as the
    model wrote them, moved by the one indent difference of the place. None when there is no such place or more than
    one."""
    keys = [_squeeze(x) for x in want]
    if not any(keys):
        return None
    n = len(want)

    def lead(x):
        return x[:len(x) - len(x.lstrip(' \t'))]

    def shift_at(i):
        """The one indent difference of every code line of the place, or None when the lines disagree."""
        found, depth = None, 0
        for got, wanted in zip(lines[i:i + n], want):
            if not wanted.strip():
                continue
            delta = len(lead(got)) - len(lead(wanted))
            # <id> (replay 21.11): a continuation line of an open bracket is aligned by the model by eye, a column
            # off ('def f(a,' / '      b):'); its words are equal (the keys), only a statement line is pinned
            if found is not None and delta != found and depth <= 0:
                return None
            found = delta if found is None else found
            depth += _bracket_depth(got)
        return found

    places = [i for i in range(len(lines) - n + 1)
              if [_squeeze(x) for x in lines[i:i + n]] == keys and shift_at(i) is not None]
    if len(places) != 1:
        return None
    i = places[0]
    delta = shift_at(i)
    unit = lead(lines[i + next(j for j, x in enumerate(want) if x.strip())])[:1] or ' '
    out = []
    for x in replace.split('\n'):
        x = x.rstrip()
        if not x.strip():
            out.append('')
            continue
        out.append(unit * max(0, len(lead(x)) + delta) + x.lstrip(' \t'))
    return '\n'.join(lines[:i] + out + lines[i + n:])


def _replace_shifted(lines: list, want: list, replace: str) -> str | None:
    """aider's leading-whitespace rule (fac-light-indent, live 19.11: 11 of 32 coder answers missed their SEARCH):
    the SEARCH lines equal ONE place of the file but for one and the same prefix of spaces and tabs, and the REPLACE
    lines get that prefix. A prefix with anything but spaces/tabs is no shift ('return x' is never the tail of
    'foo_return x': coordinator's acceptance). None when there is no such place or more than one."""
    rep = [line.rstrip() for line in replace.split('\n')]
    lead = [len(x) - len(x.lstrip(' \t')) for x in want + rep if x.strip()]
    cut = min(lead) if lead else 0
    want = [x[cut:] if x.strip() else '' for x in want]
    rep = [x[cut:] if x.strip() else '' for x in rep]

    def prefix_at(i):
        found = None
        for k, wanted in enumerate(want):
            have = lines[i + k].rstrip()
            if not wanted:
                if have.strip():
                    return None
                continue
            if not have.endswith(wanted):
                return None
            prefix = have[:len(have) - len(wanted)]
            if prefix.strip(' \t') or (found is not None and prefix != found):
                return None
            found = prefix
        return found

    places = [(i, p) for i in range(len(lines) - len(want) + 1) for p in [prefix_at(i)] if p is not None]
    if len(places) != 1:
        return None
    i, prefix = places[0]
    return '\n'.join(lines[:i] + [prefix + x if x else '' for x in rep] + lines[i + len(want):])


_PARSE_ERRORS = (SyntaxError, ValueError, RecursionError, MemoryError)
_ELIDED = re.compile(r'\.\.\.|…|existing code|rest of|unchanged|omitted|same as (?:before|above)', re.I)


def _scan_text(new: str):
    """``(lines inside a multi-line string, comments)`` of a piece of Python, or None when it does not tokenize."""
    import io
    import tokenize
    inside, comments, stack = set(), [], []
    fstart, fend = getattr(tokenize, 'FSTRING_START', -1), getattr(tokenize, 'FSTRING_END', -1)
    try:
        for tok in tokenize.generate_tokens(io.StringIO(new).readline):
            if tok.type == tokenize.STRING and tok.end[0] > tok.start[0]:
                inside.update(range(tok.start[0] + 1, tok.end[0] + 1))
            elif tok.type == fstart:
                stack.append(tok.start[0])
            elif tok.type == fend and stack:
                inside.update(range(stack.pop() + 1, tok.end[0] + 1))
            elif tok.type == tokenize.COMMENT:
                comments.append(tok.string)
    except (tokenize.TokenError, *_PARSE_ERRORS):
        return None
    return inside, comments


def _shifted(new: str, inside: set, pad: str) -> str:
    """``new`` with the margin of its first code line replaced by ``pad``. A line inside a multi-line string is
    never touched (its text is the value of the string); a blank line elsewhere becomes empty."""
    lines = new.split('\n')
    margin = next((x[:len(x) - len(x.lstrip())] for x in lines if x.strip()), '')
    out = []
    for n, x in enumerate(lines, 1):
        if n in inside:
            out.append(x)
        elif not x.strip():
            out.append('')
        else:
            k = 0
            while k < len(margin) and k < len(x) and x[k] in ' \t':
                k += 1
            out.append(pad + x[k:])
    return '\n'.join(out)


def _is_stub(node) -> bool:
    import ast
    body = node.body[1:] if (node.body and isinstance(node.body[0], ast.Expr)
                             and isinstance(node.body[0].value, ast.Constant)
                             and isinstance(node.body[0].value.value, str)) else node.body
    return all(isinstance(n, ast.Pass) or (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)
                                           and n.value.value is Ellipsis) for n in body)


def _ellipses(node) -> int:
    import ast
    return sum(1 for n in ast.walk(node) if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)
               and n.value.value is Ellipsis)


def _function_nodes(tree, target: str) -> list:
    import ast
    cls, _, leaf = target.rpartition('.')
    scopes = [n.body for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls] if cls else [tree.body]
    return [n for body in scopes for n in body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == leaf]


def _replace_function(text: str, target: str, new: str, shown: str | None = None) -> tuple[str | None, str]:
    """``(text with the one top-level function or Class.method replaced, '')`` or ``(None, reason)``. The new
    definition is re-indented to the old one and must parse as exactly one function of the same name. ``shown``:
    the text the model saw; the old definition must stand in it whole (a function shown in part or only in the
    outline is not replaced: the model would delete code it never read). Decorators the new text omits stay."""
    import ast
    if '\r' in text or '\r' in new:
        return None, "function '%s': a lone carriage return in the text" % target
    try:
        tree = ast.parse(text)
    except _PARSE_ERRORS:
        return None, "function '%s': the file does not parse" % target
    leaf = target.rpartition('.')[2]
    found = _function_nodes(tree, target)
    if not found:
        return None, "function '%s' not found (only a top-level function or a method of a top-level class)" % target
    if len(found) > 1:
        return None, "function '%s' is defined more than once" % target
    node = found[0]
    lines = text.split('\n')
    deco_first = min([node.lineno] + [d.lineno for d in node.decorator_list])
    old_whole = '\n'.join(lines[deco_first - 1:node.end_lineno])
    if shown is not None and old_whole not in shown:
        return None, ("function '%s' was not shown whole: use SEARCH/REPLACE on the shown lines or answer CANNOT: %s"
                      % (target, target))
    new = new.strip('\n')
    scanned = _scan_text(new)
    if scanned is None:
        return None, "new text of function '%s' does not parse" % target
    inside, comments = scanned
    try:
        parsed = ast.parse(_shifted(new, inside, ''))
    except _PARSE_ERRORS:
        return None, "new text of function '%s' does not parse" % target
    if len(parsed.body) != 1 or not isinstance(parsed.body[0], (ast.FunctionDef, ast.AsyncFunctionDef)):
        return None, "new text of function '%s' must define exactly one function" % target
    fresh_node = parsed.body[0]
    if fresh_node.name != leaf:
        return None, "new text of function '%s' defines another name (%s), not the same name" % (
            target, fresh_node.name)
    if (_is_stub(fresh_node) and not _is_stub(node)) or _ellipses(fresh_node) > _ellipses(node):
        return None, "new text of function '%s' elides code (... or pass): write every line" % target
    bad = next((c for c in comments if _ELIDED.search(c) and c not in old_whole), None)
    if bad is not None:
        return None, "new text of function '%s' elides code (comment %r): write every line" % (target, bad[:30])
    first = node.lineno if (node.decorator_list and not fresh_node.decorator_list) else deco_first
    head_line = lines[node.lineno - 1]
    pad = head_line[:len(head_line) - len(head_line.lstrip())]
    fresh = _shifted(new, inside, pad).split('\n')
    done = '\n'.join(lines[:first - 1] + fresh + lines[node.end_lineno:])
    try:
        again = ast.parse(done)
    except _PARSE_ERRORS:
        return None, "function '%s': the file does not parse after the replacement" % target
    placed = _function_nodes(again, target)
    same = lambda n: (ast.dump(n.args), [ast.dump(x) for x in n.body], ast.dump(n.returns) if n.returns else '')
    if len(placed) != 1 or same(placed[0]) != same(fresh_node):
        return None, "function '%s': the file does not parse after the replacement" % target
    return done, ''


def apply_edit_blocks(workdir: Path, blocks, shown: str | None = None) -> tuple[list[str], dict]:
    """Apply the blocks inside ``workdir`` (the file names come from the task, never from the model):
    ``(changed files, {failure: count})``. All or nothing: when one block fails no file is written (half a
    candidate could pass weak tests; the failure note goes to the next attempt). A CRLF file stays CRLF. ``shown``:
    the prompt the model saw (LF); a function block is applied only to a definition that stands in it whole."""
    failed, texts, crlf, how = {}, {}, {}, []

    def fail(why):
        failed[why] = failed.get(why, 0) + 1

    for name, search, replace_text in blocks:
        if name not in texts:
            path = Path(workdir).joinpath(*name.split('/'))
            try:
                raw = path.read_bytes().decode('utf-8') if path.is_file() else ''
            except (OSError, UnicodeDecodeError):
                fail('unreadable file')
                continue
            crlf[name] = '\r\n' in raw
            texts[name] = raw.replace('\r\n', '\n')
        text = texts[name]
        if isinstance(search, _FuncTarget):
            new, why = _replace_function(text, str(search), replace_text, shown)
            if new is None:
                fail(why)
                continue
        elif not search.strip():
            if text.strip():
                fail('empty SEARCH on a file that is not empty')
                continue
            new = replace_text if replace_text.endswith('\n') else replace_text + '\n'
        else:
            new, matcher = _replace_once_how(text, search, replace_text)
            if new is None:
                fail('SEARCH not found exactly once')
                continue
            how.append(matcher)
        texts[name] = new
    payload = {}
    for name, text in texts.items():
        try:      # a lone surrogate from a JSON escape cannot be written: the model's answer, not a crash
            payload[name] = (text.replace('\n', '\r\n') if crlf[name] else text).encode('utf-8')
        except UnicodeError:
            fail('text that cannot be written as UTF-8')
    if failed:
        return [], failed
    applied = []
    for name, data in payload.items():
        path = Path(workdir).joinpath(*name.split('/'))
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        except OSError:
            fail('unwritable file')
            continue
        applied.append(name)
    applied = _Applied(applied)
    applied.matchers = how           # telemetry: which matcher placed each SEARCH/REPLACE block
    return applied, failed


class _Applied(list):
    """The changed files; ``matchers``: the matcher that placed each block (see _replace_once_how)."""
    matchers: list = []


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A 3xx is an error, never followed: urllib would resend the Authorization header to the new host (critic
    19.11), so the key could reach a third party."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_LIGHT_OPENER = urllib.request.build_opener(_NoRedirect)


def _with_retry_after(raw: bytes, header) -> bytes:
    """<id>: the Retry-After header (seconds) of an error answer travels in the body as ``_retry_after``, where
    classify() reads it; a date or garbage is ignored, a body that is not JSON is wrapped."""
    try:
        seconds = float(str(header).strip())
    except (TypeError, ValueError):
        return raw
    if not 0 < seconds <= 3600:
        return raw
    try:
        body = json.loads(raw.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        body = None
    if isinstance(body, dict):
        body['_retry_after'] = seconds
    elif isinstance(body, list) and len(body) == 1 and isinstance(body[0], dict):
        body = dict(body[0], _retry_after=seconds)
    else:
        body = {'error': {'message': (raw or b'')[:300].decode('utf-8', 'replace')}, '_retry_after': seconds}
    return json.dumps(body).encode('utf-8')


def _light_post(url: str, key: str, body: dict, timeout: float) -> tuple[int | None, bytes]:
    """(HTTP status or None, body). The key travels only in the Authorization header, never in a log."""
    request = urllib.request.Request(url, data=json.dumps(body).encode('utf-8'), method='POST',
                                     headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + key})
    try:
        with _LIGHT_OPENER.open(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        try:
            return error.code, _with_retry_after(error.read(), error.headers.get('Retry-After') if error.headers else None)
        except (OSError, http.client.HTTPException):
            return error.code, b''
    except (OSError, ValueError, http.client.HTTPException) as error:   # URLError, timeouts, resets
        return None, type(error).__name__.encode()


def _light_error(status: int | None, raw: bytes, name: str = 'APIError') -> bytes:
    """A Kilo-shaped error event: classify() reads the status and the provider body (quota ids, retryDelay).
    Gemini's OpenAI-compatible endpoint wraps the error object into a one-element list. ``name``:
    'NetworkError' (no HTTP answer at all) and 'UnreadableAnswer' (HTTP 200 that is no chat completion) have
    classes of their own (critic 19.11: both were 'transient' for ever, never the brake)."""
    text = (raw or b'')[:4000].decode('utf-8', 'replace')
    try:
        body = json.loads(text)
        if isinstance(body, list) and len(body) == 1 and isinstance(body[0], dict):
            text = json.dumps(body[0])
    except ValueError:
        pass
    data = {'message': text[:300]}
    if status is not None:
        data.update(statusCode=status, responseBody=text)
    return (json.dumps({'type': 'error', 'error': {'name': name, 'data': data}}) + '\n').encode('utf-8')


def _missing_blocks_note(workdir: Path, blocks, shown: str | None = None) -> str:
    """Per failed block: where its SEARCH missed and the closest real line. First, right after the counts (the note
    is cut at 300 characters): every definition a failed block aimed at that ``shown`` (the prompt) did not show
    whole, in the form asked_names reads, so the next candidate and the next pass are shown it first and whole."""
    from .factory_patterns import aimed_definition
    parts, asks = [], []
    seen = {x.strip() for x in (shown or '').replace('\r\n', '\n').split('\n')} if shown is not None else None
    for i, (name, search, replace_text) in enumerate(blocks, 1):
        if not search.strip() or isinstance(search, _FuncTarget):
            continue
        try:
            path = Path(workdir).joinpath(*name.split('/'))
            raw = path.read_bytes().decode('utf-8') if path.is_file() else ''
            text = raw.replace('\r\n', '\n')
        except (OSError, UnicodeDecodeError):
            continue
        if _replace_once(text, search, replace_text) is not None:
            continue
        aim = aimed_definition(text, search) if seen is not None else None
        if aim and not all(x.strip() in seen for x in aim[1] if x.strip()) and aim[0] not in asks:
            asks.append(aim[0])
        if len(parts) >= 2:
            continue                       # two blocks are named; the aims of the others are still asked for
        where = 'in the file more than once' if len(_line_hits(text, search)) > 1 else 'not in the file'
        have = {x.strip() for x in text.split('\n')}
        wanted = [x.strip() for x in search.split('\n') if x.strip()]
        first = next((x for x in wanted if x not in have), wanted[0] if wanted else '')[:80]
        part = "block %d (%s) SEARCH is %s: '%s'" % (i, name, where, first)
        # a guessed line (14 of the 56 no-change passes of the night 19-20.11): the real line it most looks like, so
        # the next attempt copies that one instead of guessing again; only a close look-alike is named
        close = difflib.get_close_matches(first, [x for x in have if x], n=1, cutoff=0.75) if first and \
            where == 'not in the file' else []
        if close:
            part += ", the closest line there: '%s'" % close[0][:100]
        parts.append(part)
    return ''.join('; ' + p for p in ["function '%s' was not shown whole" % a for a in asks[:3]] + parts)


def _light_note(total: int, applied: list, failed: dict, outside: int, text: str) -> str:
    """One line for the next attempt's feedback: what happened to the edit blocks (no file text)."""
    if not total:
        answer = text.strip()
        if answer[:7].upper() == 'CANNOT:':
            return 'the model answered CANNOT: ' + redact(answer[7:].strip())[:150]   # reject() scrubs paths
        return 'the answer had no SEARCH/REPLACE edit block (nor a REPLACE FUNCTION block)'
    parts = ['edit blocks %d, changed files %d' % (total, len(applied))]
    if outside:
        parts.append('%d block(s) for a file outside the task' % outside)
    parts.extend('%d: %s' % (n, why) for why, n in sorted(failed.items()))
    return '; '.join(parts)


LIGHT_ANSWERS_KEPT = 200

def _keep_answer(workdir: Path, text: str) -> None:
    try:
        folder = Path(workdir).parent / 'answers'
        folder.mkdir(exist_ok=True)
        (folder / (Path(workdir).name + '.txt')).write_text(text[:20000], encoding='utf-8')
        files = sorted((p for p in folder.iterdir() if p.is_file()), key=lambda p: p.stat().st_mtime)
        for old in files[:max(0, len(files) - LIGHT_ANSWERS_KEPT)]:
            old.unlink()
    except OSError:
        pass


CANDIDATE_TEMPERATURES = (0.2, 0.5, 0.8)   # <id>: every tournament candidate samples differently, not the same answer again


def candidate_temperature(k: int) -> float:
    return CANDIDATE_TEMPERATURES[min(max(0, int(k)), len(CANDIDATE_TEMPERATURES) - 1)]


def light_attempt(task: Task, workdir: Path, model: str, timeout: int = LIGHT_TIMEOUT_S,
                  *, prompt_override: str | None = None, steps: int | None = None,
                  key_env: str | None = None, post=None, temperature: float = 0.2) -> tuple[int, bytes, bytes]:
    """The light engine with model_attempt's contract: ``(rc, Kilo-shaped events, note)``. A task without
    touch_files (the reviewer's copy) only answers; a coder task gets its edit blocks applied in ``workdir``.
    ``post`` replaces the HTTP call (tests never reach the network)."""
    if task.only_opus:
        return 125, b'', b'opus-only-task'
    provider, _, model_id = model.partition('/')
    url = LIGHT_ENDPOINTS.get(provider)
    if url is None or not model_id:
        return 125, b'', b'light: unsupported provider'
    if not MODEL_ID.fullmatch(model):      # 0 rubles: an OpenRouter model without ':free' never leaves the machine
        return 125, b'', b'light: model id refused (a paid or malformed model)'
    prompt = prompt_override if prompt_override is not None else _default_prompt(task, workdir, light=True)
    if len(prompt) > channels.PROMPT_LIMIT_CHARS:
        return 125, b'', b'context-too-large'
    key = os.environ.get(key_env or ('OPENROUTER_API_KEY' if provider == 'openrouter' else 'GOOGLE_GENERATIVE_AI_API_KEY'), '')
    if not key:
        return 1, _light_error(401, b'{"error": {"message": "no API key in the environment"}}'), b''
    review = not task.touch_files
    body = {'model': model_id, 'max_tokens': channels.max_output_for(model, LIGHT_MAX_OUTPUT),
            'temperature': 0 if review else temperature,
            'messages': [{'role': 'system', 'content': LIGHT_REVIEW_RULES if review else light_rules(task, workdir)},
                         {'role': 'user', 'content': prompt}]}
    if provider == 'openrouter':
        body['reasoning'] = {'max_tokens': LIGHT_REASONING_TOKENS}
    status, raw = (post or _light_post)(url, key, body, max(10, min(int(timeout), LIGHT_TIMEOUT_S)))
    if status is None and raw == b'TimeoutError':
        # the request reached the provider, the answer did not come in time: Kilo's timeout contract (the idle
        # series, then the ceiling: reviewer_failed / worker_timeout), never an endless 'transient' (critic 19.11)
        return 124, b'', b'worker-timeout'
    if status is None:          # no connection at all (DNS, the proxy is down): the request never reached a provider
        return 1, _light_error(None, raw, 'NetworkError'), b''
    if status != 200:
        return 1, _light_error(status, raw), b''
    try:
        data = json.loads(raw.decode('utf-8'))
        error = data.get('error') if isinstance(data, dict) and 'choices' not in data else None
        if isinstance(error, dict) and type(error.get('code')) is int:
            # OpenRouter: an error during generation comes with HTTP 200 and an error object (its own code)
            return 1, _light_error(error['code'], raw), b''
        choice = data['choices'][0]
        content = choice['message'].get('content') or ''
        if isinstance(content, list):   # some OpenAI-compatible providers answer with text parts
            content = ''.join(str(p.get('text', '')) for p in content if isinstance(p, dict))
        text = _LIGHT_THOUGHT.sub('', str(content)).strip()
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        return 1, _light_error(None, b'unreadable answer', 'UnreadableAnswer'), b''
    if choice.get('finish_reason') in ('length', 'max_tokens') and text and not text.lstrip().upper().startswith('CANNOT'):
        # <id>: an answer cut by the output limit is a half edit: never applied, never judged; the next candidate is told
        return 1, _light_error(None, b'the answer was cut by the output limit', 'TruncatedAnswer'), b''
    if not text and choice.get('finish_reason') in ('length', 'max_tokens'):
        # the whole output limit went into reasoning (Gemma 4, live 20.11: 13 of 16 coder calls since midnight, ~100 s
        # each; the API refuses a thinking budget or level for it): no answer from this model now, another one is asked
        return 1, _light_error(None, b'the model used its whole output limit and gave no answer', 'EmptyAnswer'), b''
    usage = data.get('usage') if isinstance(data.get('usage'), dict) else {}
    given = usage.get('prompt_tokens_details') if isinstance(usage.get('prompt_tokens_details'), dict) else {}
    made = usage.get('completion_tokens_details') if isinstance(usage.get('completion_tokens_details'), dict) else {}
    cached = given.get('cached_tokens') if type(given.get('cached_tokens')) is int else None
    tokens = {}
    if type(usage.get('prompt_tokens')) is int:
        tokens['input'] = max(0, usage['prompt_tokens'] - (cached or 0))   # prompt_tokens include the cached part
    # completion_tokens already include the reasoning (OpenAI usage schema); the Kilo shape keeps them apart, so the
    # reasoning is counted once (live 19.11 19:44: Nemotron booked 5 515 + 8 192 + 8 192 for 13 707 real tokens)
    reasoning = made.get('reasoning_tokens') if type(made.get('reasoning_tokens')) is int else None
    if type(usage.get('completion_tokens')) is int:
        tokens['output'] = max(0, usage['completion_tokens'] - (reasoning or 0))
    if reasoning is not None:
        tokens['reasoning'] = reasoning
    if cached is not None:
        tokens['cache'] = {'read': cached, 'write': 0}
    events, note = [], ''
    if not review:
        blocks, outside = parse_edit_blocks(text, tuple(task.touch_files))
        problems = dict(getattr(blocks, 'problems', {}))
        if problems:      # a function block that could not be read is half a candidate: nothing is applied
            applied, failed = [], problems
        else:
            applied, failed = apply_edit_blocks(Path(workdir), blocks, prompt.replace('\r\n', '\n'))
        events.extend({'type': 'tool_use', 'part': {'tool': 'edit', 'state': {'input': {'filePath': n}}}}
                      for n in applied)
        note = _light_note(len(blocks) + outside + sum(problems.values()), applied, failed, outside, text)
        if 'squeezed' in getattr(applied, 'matchers', ()):
            note += '; matcher: whitespace-tolerant x%d' % applied.matchers.count('squeezed')
        if failed.get('SEARCH not found exactly once'):
            note += _missing_blocks_note(Path(workdir), blocks, prompt)
            from .factory_patterns import hints as pattern_hints
            note += ''.join('; ' + h for h in pattern_hints(blocks))
        if not applied:
            _keep_answer(Path(workdir), text)
    events.append({'type': 'text', 'part': {'text': text}})
    events.append({'type': 'step_finish', 'part': {'reason': choice.get('finish_reason') or 'stop', 'tokens': tokens}})
    return 0, ''.join(json.dumps(e, ensure_ascii=False) + '\n' for e in events).encode('utf-8'), note.encode('utf-8')


def _digest(*parts) -> str:
    return sha256('|'.join(str(p) for p in parts).encode('utf-8', 'replace')).hexdigest()


def _counts(result) -> dict | None:
    if result is None:
        return None
    return dict(collected=result.collected, passed=result.passed,
                failed=result.failed + result.errors, skipped=result.skipped)


def once(**kwargs) -> dict:
    """One pass on ONE task (arguments: see ``_once``). A lease that was claimed (handed in, or taken here) and that
    the pass never began to use -- an early return or a raise before ``_pass`` -- goes back to READY (unclaim, the
    attempt back) instead of being held until it expires and counted as an expiry."""
    box: dict = {}
    if kwargs.get('lease') is not None and kwargs.get('task_id'):
        box['claim'] = (kwargs['task_id'], kwargs['lease'])
    try:
        result = _once(_box=box, **kwargs)
    except BaseException:
        _drop_claim(kwargs, box)
        raise
    _drop_claim(kwargs, box)
    return result


def _drop_claim(kwargs: dict, box: dict) -> None:
    if box.get('passed') or not box.get('claim'):
        return
    tid, token = box['claim']
    try:
        Lease(kwargs['checkpoint'], kwargs['plan'], tid, token).commit(lambda s, r: unclaim(s, tid, token))
    except Exception as error:   # noqa: BLE001 - best effort: a stale/began/busy lease is released by its expiry
        _log.warning('lease of %s not returned: %s', tid, error)


def _once(*, root: Path, plan: Path, checkpoint: Path, staging: Path,
         small_model: str, large_model: str, execute: bool = False,
         acknowledge: bool = False, review_model: str | None = None,
         channel_config: Path | None = None, max_attempts: int = MAX_ATTEMPTS,
         max_model_calls: int | None = None, base_sha: str | None = None,
         small_follow_up: bool = True, port_repo: Path | None = None,
         task_id: str | None = None, lease: str | None = None, _box: dict | None = None) -> dict:
    """One pass on ONE task. ``task_id`` + ``lease``: the loop (or the pool) claimed the task and hands over its lease
    token; without a lease the pass claims the task itself (``task_id``, else the first ready one). There is no lock
    over the pass: the state changes only in short fenced commits (agent_factory.Lease)."""
    tasks = read_plan(json.loads(plan.read_text(encoding="utf-8")))
    if staging.resolve().is_relative_to(root.resolve()):
        raise InvalidPlan("staging inside source project is forbidden")
    if checkpoint.resolve().is_relative_to(root.resolve()):
        raise InvalidPlan("checkpoint inside source project is forbidden")
    if lease is not None and not task_id:
        raise InvalidPlan("a lease belongs to a task: task_id is required")
    tasks, state = snapshot(checkpoint, plan)             # read-only: the pass changes the state only by commits
    if lease is not None:
        candidates = [task_id] if task_id in tasks else []
    else:
        candidates = [t for t in ready(tasks, state) if task_id is None or t == task_id]
    if not candidates:
        return {"status": "IDLE", "next": None, "deploy_blocked": state["deploy_blocked"]}
    tid = candidates[0]
    task = tasks[tid]
    model = route(task, small_model=small_model, large_model=large_model)
    if not execute:
        return {"status": "DRY_RUN", "next": tid, "model": model,
                "deploy_blocked": state["deploy_blocked"]}
    if not acknowledge:
        raise InvalidPlan("autonomous Kilo is not OS isolated: explicit opt-in required")
    if not shutil.which("kilo") and not os.environ.get('FACTORY_KILO_ENTRY'):
        raise InvalidPlan("kilo command unavailable")
    configured = []
    if channel_config is not None:
        configured = json.loads(channel_config.read_text(encoding='utf-8'))['channels']
        channels.validate(configured)
        if not configured or any(c.get('verified') is not True for c in configured):
            raise InvalidPlan('channels require actual verified model/tool availability')
    if not configured and not os.environ.get("GOOGLE_GENERATIVE_AI_API_KEY"):
        raise InvalidPlan("Google API auth key must be set in the caller environment")
    if not review_model:
        raise InvalidPlan("review_model is required: no candidate may skip the independent review")
    if staging_reveals_profile(staging):
        raise InvalidPlan(PROFILE_LEAK_MESSAGE)
    try:
        staging.mkdir(parents=True, exist_ok=True)
        swept_failed = sweep_scratch(staging)
    except OSError as error:   # antivirus, a locked folder: the machine, not the task (a lease handed in is returned by once())
        return {'status': 'READY', 'reason': 'os_error', 'task_id': tid, 'task': tid,
                'backlog_id': task.backlog_id, 'base_sha': base_sha, 'calls': [], 'stages': {},
                'events': [], 'tests': None, 'infra': True, 'wait_s': 60.0,
                'error_type': type(error).__name__,
                'reason_detail': scrub_paths(redact(str(error))[:200], [root, staging]),
                'deploy_blocked': state['deploy_blocked']}
    if max_model_calls is not None:
        # Explicit operator budget for this checkpoint, never an implicit raise.
        with txn(checkpoint, plan) as (_tasks, fresh):
            fresh["max_model_calls"] = max_model_calls
    token = lease
    if token is None:
        try:
            claimed = claim(checkpoint, plan, tid)     # one transaction; calls are charged when they are made
        except BudgetExhausted:
            return {'status': 'WAITING_CHANNEL', 'reason': 'budget_exhausted', 'task_id': tid, 'task': tid,
                    'backlog_id': task.backlog_id, 'base_sha': base_sha, 'calls': [], 'stages': {}, 'events': [],
                    'tests': None, 'infra': False, 'wait_s': round(seconds_to_local_midnight(), 1),
                    'deploy_blocked': state['deploy_blocked']}
        if claimed is None:
            return {"status": "IDLE", "next": None, "deploy_blocked": state["deploy_blocked"]}
        tid, token = claimed
        _box['claim'] = (tid, token)
    _box['passed'] = True      # from here the pass itself returns or ends the lease
    return _pass(task, Lease(checkpoint, plan, tid, token), checkpoint=checkpoint, root=root, staging=staging,
                 small_model=small_model, large_model=large_model, review_model=review_model,
                 configured=configured, max_attempts=max_attempts, swept_failed=swept_failed,
                 base_sha=base_sha or os.environ.get('FACTORY_BASE_SHA'), small_follow_up=small_follow_up,
                 port_repo=port_repo,
                 ledger=(channel_config.resolve().parent / 'quota') if channel_config is not None else None)


def _pass(task: Task, ck: Lease, **kwargs) -> dict:
    try:
        with scratch_redirect(kwargs['staging']):
            return _pass_inner(task, ck, **kwargs)
    except LockBusy:          # the checkpoint lock stayed busy: no verdict, nothing written, the lease expires on its own
        return {'status': 'READY', 'reason': 'lock_busy', 'task_id': task.id, 'task': task.id,
                'backlog_id': task.backlog_id, 'base_sha': kwargs.get('base_sha'), 'calls': [], 'stages': {},
                'events': [], 'tests': None, 'infra': False, 'wait_s': 30.0}
    except StaleLease:        # the lease is not this pass's any more (it expired, or another writer ended the pass)
        return {'status': 'STALE_LEASE', 'reason': 'stale_lease', 'task_id': task.id, 'task': task.id,
                'backlog_id': task.backlog_id, 'base_sha': kwargs.get('base_sha'), 'calls': [], 'stages': {},
                'events': [], 'tests': None, 'infra': False, 'wait_s': 0.0}


def _pass_inner(task: Task, ck: Lease, *, checkpoint: Path, root: Path, staging: Path,
          small_model: str, large_model: str, review_model: str, configured: list,
          max_attempts: int, base_sha: str | None, swept_failed=(), ledger: Path | None = None,
          small_follow_up: bool = True, port_repo: Path | None = None) -> dict:
    """The pass of the lease ``ck`` (the task is already RUNNING under it). It keeps read-only facts (``state`` and
    ``row`` are a copy taken at the start); every change of the state is ONE ``ck.commit`` on the FRESH state."""
    tid, token = task.id, ck.token
    try:
        staging.mkdir(parents=True, exist_ok=True)
        ck.commit(lambda s, r: begin(s, tid, token, os.getpid()))   # fenced: a foreign or dead lease stops the pass here
    except StaleLease:
        raise
    except BaseException:      # never began: give the lease back (unclaim refuses once the pass began)
        _drop_claim({'checkpoint': checkpoint, 'plan': ck.plan}, {'claim': (tid, token)})
        raise
    state = ck.read()
    prefix = "task-" + tid + "-" + token[:8]
    row = state['tasks'][tid]
    attempt = row['attempts']
    calls: list[dict] = []
    stages: dict[str, float] = {}
    events: list[str] = ['sweep_failed'] if swept_failed else []
    ctx = {'workdir': staging / prefix, 'baseline': {}, 'coder_model': None, 'counts': None, 'role': 'code',
           'read_chars': 0, 'last_tokens': 0, 'last_text': '', 'roots': [root, staging]}
    scrub = lambda text: scrub_paths(text, ctx['roots'] + [ctx['workdir']])  # noqa: <id>
    report = {'task_id': tid, 'task': tid, 'backlog_id': task.backlog_id, 'base_sha': base_sha,
              'attempt': attempt, 'kind': task.kind, 'calls': calls, 'stages': stages,
              'events': events, 'reason': None, 'tests': None, 'wait_s': 0.0, 'infra': False,
              'deploy_blocked': state['deploy_blocked']}
    started_pass = time.monotonic()
    prev_diff_file = staging / 'prev-diff' / (tid + '.diff')

    def end(apply, **extra) -> dict:
        """The end of the pass: ``apply(state, row)`` makes the transition(s) on the fresh state and returns
        (status, more report fields) -- all of it ONE commit."""
        def commit(state, row):
            status, more = apply(state, row)
            if status not in ('READY', 'WAITING_CHANNEL'):      # settled, blocked or quarantined: every series is over
                table = factory_env(state)
                for key in ('task:%s:code' % tid, 'task:%s:review' % tid):
                    table['idle'].pop(key, None)
                table['shortages'].pop(tid, None)
                table['other'].pop(tid, None)
            return status, more, state['deploy_blocked']
        status, more, blocked = ck.commit(commit)
        report.update(extra)
        report.update(more or {})
        report['deploy_blocked'] = blocked
        report['status'] = status
        report['tests'] = _counts(ctx['counts'])
        report['dur_s'] = round(time.monotonic() - started_pass, 3)
        return report

    def has_pending() -> bool:
        return bool(ck.read()['tasks'][tid].get('pending_review'))

    def set_pending(state, row) -> None:
        old = row.get('pending_review') if isinstance(row.get('pending_review'), dict) else {}
        row['pending_review'] = dict(workdir=str(ctx['workdir']), baseline_digest=baseline_digest,
                                     coder_model=ctx['coder_model'])
        short = old.get('chain_short')
        if old.get('workdir') == str(ctx['workdir']) and type(short) is int and short > 0:
            row['pending_review']['chain_short'] = short     # the same candidate: its short chains keep counting

    def chain_short(state, row) -> int:
        """One more chain of this candidate cut short; counted on the candidate itself, so a channel_wait between two
        short chains does not reset the term the way it resets defer_streak."""
        pend = row.get('pending_review')
        if not isinstance(pend, dict):
            return ESCALATE_AFTER
        prior = pend.get('chain_short')
        pend['chain_short'] = (prior if type(prior) is int and prior > 0 else 0) + 1
        return pend['chain_short']

    def timed(name: str, fn):
        t0 = time.monotonic()
        try:
            return fn()
        finally:
            stages[name] = round(stages.get(name, 0.0) + time.monotonic() - t0, 3)

    def release(reason: str, seconds: float, infra: bool | None = None) -> dict:
        """No strike, attempt not spent: back to READY, postponed. ``infra`` only for real faults."""
        return end(lambda s, r: (defer(s, tid, token, reason, seconds), None), reason=reason,
                   wait_s=round(float(seconds), 1), infra=(reason in INFRA_DEFERS) if infra is None else infra)

    def block(reason: str, detail: str = '', *, infra: bool = False, keep: bool = False) -> dict:
        """BLOCKED without a strike (also drops a stale pending review: agent_factory.quarantine)."""
        detail = scrub(redact(detail))[:400]
        voided = []

        def apply(state, row):
            voided.append(row.get('pending_review'))
            quarantine(state, tid, token, reason=reason)
            if detail:
                add_feedback(state, tid, 'gate', '[infra] ' + reason + ': ' + detail)
            return 'BLOCKED', {'blocked_reason': row.get('blocked_reason')}
        result = end(apply, reason=reason, reason_detail=detail, infra=infra)
        old = voided[0]
        if not keep and isinstance(old, dict) and isinstance(old.get('workdir'), str) and inside_staging(old['workdir'], staging):
            shutil.rmtree(old['workdir'], ignore_errors=True)   # the candidate is void with the block
        return result

    def release_or_block(reason: str, seconds: float) -> dict:
        """The same postponement three times in a row is not a wait any more: BLOCKED for Opus."""
        if reason in ESCALATE and defer_streak(ck.read(), tid, reason) + 1 >= ESCALATE_AFTER:
            return block(reason, 'postponed %d times in a row' % ESCALATE_AFTER, infra=reason in INFRA_DEFERS)
        return release(reason, seconds)

    def reject(source: str, reason: str, text: str, names=(), mark=None) -> dict:
        """A candidate failed a gate or the reviewer: feedback + previous diff + a strike. ``mark(row)``: one more
        change of the row in the same commit."""
        reason = scrub(redact(reason))[:300]
        text = scrub(text)
        # NOTE: the previous diff below is deliberately NOT scrubbed: it is the user's own code under
        # relative a/ b/ names, and rewriting it would corrupt the diff the model must not repeat.
        if source == 'review' or reason in ('gate:no_changes', 'gate:steps_exhausted'):
            # the model's own final text: the REVIEWER's text on a review rejection, the CODER's on no_changes
            report['model_note'] = redact(ctx['last_text'])[:300]   # never raw tool arguments or the prompt
        if names:
            prev_diff_file.parent.mkdir(parents=True, exist_ok=True)
            prev_diff_file.write_text(unified_diff(ctx['baseline'], ctx['workdir'], names, DIFF_LIMIT),
                                      encoding='utf-8')
        else:
            prev_diff_file.unlink(missing_ok=True)  # never hand the next attempt another cycle's diff

        asked_now = (asked_names(text) | frozenset(ctx.get('asked') or ())) & defined_names(task, ctx['workdir'])

        def apply(state, row):
            add_feedback(state, tid, source, '[attempt %d] %s' % (attempt, text))
            if asked_now:                          # the next attempts show these whole first, whatever fails in between
                remember_asked(row, asked_now)
            if mark is not None:
                mark(row)
            failed = (list(ctx.get('tried', ())) + [m for m, _ in ctx.get('gate_red', ()) if m]
                      + ([ctx['coder_model']] if ctx.get('coder_model') else []))   # every model this pass tried
            status = settle(state, tid, token, tests_ok=False, evidence=_digest(reason, text),
                            max_attempts=max_attempts, unsafe=is_unsafe_reject(reason), failed_models=failed)
            row.pop('pending_review', None)
            return status, None
        return end(apply, reason=reason, reason_detail=redact(text)[:400])

    def call(role: str, call_task: Task, directory_for, preferred: str, prompt: str,
             *, exclude_model: str | None = None, skip_tiers: tuple = (), later: bool = False) -> tuple[int, bytes, bytes]:
        """One real model call with reservation, charging, classification, one transient retry. ``skip_tiers``:
        channel tiers this call may not use (factory_channels.route_order)."""
        ctx['role'] = role
        if len(prompt) > channels.PROMPT_LIMIT_CHARS:
            raise PromptTooLarge(str(len(prompt)))
        light = ctx['light'] = engine_for(role, call_task) == 'light'    # one request, the files travel in the prompt
        base_tokens = channels.estimate_tokens(len(prompt), 0 if light else ctx['read_chars'],
                                               overhead=LIGHT_OVERHEAD_TOKENS if light else None,
                                               cyrillic=channels.cyrillic_share(prompt))
        steps = 1 if light else (REVIEW_STEPS if role == 'review' else PROVIDER_STEPS)
        booked = 1 if light else requests_for(steps)   # the whole run: what choose() checks and reserve() books; reconcile() writes the fact
        def booked_one(row) -> None:
            began = row.get('began')
            if isinstance(began, dict):
                began['booked'] = int(began.get('booked') or 0) + 1      # the pool's admission counts workers that did not book yet

        family = os.path.splitext(task.touch_files[0].replace('\\', '/'))[0] if task.touch_files else ''
        suffix = ':review' if role == 'review' else ''      # a reviewer must not move the coder's remembered channel
        affinity = ['task:' + tid + suffix] + (['family:' + family + suffix] if family else [])

        hopped, last_info = [], None     # models that answered "overloaded" in THIS call: the next hop skips them
        for retry in range(1 + TRANSIENT_HOPS):
            selected, at, chosen, kwargs = None, None, preferred, {}
            if configured:
                route = 'review' if role == 'review' else 'code'
                live_state = ck.read().get('channel_quotas') or {}    # a fresh private copy: ratings, parked 404s, cooling
                excl = sorted(channels.excluded_models(exclude_model) | set(hopped)) or None
                order = channels.route_order(configured, route, attempt, base_tokens, preferred=preferred,
                                             exclude_model=excl, skip_tiers=skip_tiers, state=live_state,
                                             later=later)
                if not order and route == 'code':     # no escalation/main channel at all: any channel is better than none
                    order = channels.route_order(configured, route, 1, 0, preferred=preferred,
                                                 exclude_model=excl,   # never a model the tournament tried
                                                 skip_tiers=skip_tiers, state=live_state, later=later)
                if not order and hopped:              # every other model is overloaded too: the old transient path
                    raise ChannelFault(last_info or {'kind': 'transient'})
                if not order:
                    raise NoIndependentReviewer()
                if not light:
                    order = _kilo_fits(order, steps, events)

                def book(state, row):
                    """View + usable + choose + charge + reserve + publish: ONE commit on the fresh state, so two workers
                    never choose the same free request."""
                    quota = state.setdefault('channel_quotas', {})
                    seen = (quota_ledger.view(quota, quota_ledger.others(ledger, str(checkpoint)))
                            if ledger is not None else quota)    # <id>: the other states' bookings of the same keys
                    live = channels.usable(order, seen, os.environ) or order   # a dead or keyless channel sets no ceiling
                    tokens = min(base_tokens, max(c['tpm'] for c in live))  # a huge file may not make every channel "too small"
                    pick = channels.choose(order, seen, tokens, os.environ,
                                           requests=booked, affinity=affinity)   # a multi-step call needs room
                    charge_call(state, tid)   # BEFORE booking: an exhausted budget must leave no reservation behind
                    when = channels.reserve(quota, pick, tokens, requests=booked,
                                           affinity=affinity)   # exactly what choose() checked
                    if ledger is not None:
                        quota_ledger.publish(ledger, str(checkpoint), quota)
                    booked_one(row)
                    return pick, when, tokens
                selected, at, tokens = ck.commit(book)
                if tokens < base_tokens and 'reservation_capped' not in events:
                    events.append('reservation_capped')
                chosen, kwargs['key_env'] = selected['model'], selected['key_env']
            elif chosen in channels.excluded_models(exclude_model):
                raise NoIndependentReviewer()
            else:
                tokens = base_tokens

                def charge(state, row):
                    charge_call(state, tid)
                    booked_one(row)
                ck.commit(charge)
            ctx['last_tokens'] = tokens
            began = time.monotonic()
            try:
                directory = directory_for(retry)
                engine = light_attempt if light else model_attempt
                if light:
                    kwargs['temperature'] = candidate_temperature(ctx.get('candidate') or 0)
                code, stdout, stderr = engine(call_task, directory, chosen, timeout=240,
                                              prompt_override=prompt, steps=steps, **kwargs)
            except BaseException:
                if selected is not None:    # booked, never accounted: the reservation goes back (the call did not finish)
                    def unbook(state, row):
                        channels.reconcile(state['channel_quotas'], selected, at, tokens, 0,
                                           requests=booked, actual_requests=0)
                        if ledger is not None:
                            quota_ledger.publish(ledger, str(checkpoint), state['channel_quotas'])
                    try:
                        ck.commit(unbook)
                    except Exception as error:   # noqa: BLE001 - the original failure is what the pass reports
                        _log.warning('reservation not returned: %s', error)
                raise
            ctx['light_note'] = stderr.decode('utf-8', 'replace')[:300] if light and code == 0 else ''
            elapsed = round(time.monotonic() - began, 3)
            summary = event_summary(stdout, directory)
            idle = code == 124 and summary['steps'] == 0 and summary['tool_events'] == 0
            kinds = ('input_tokens', 'cache_read_tokens', 'cache_write_tokens')
            actual_input = (sum(summary[k] or 0 for k in kinds) if any(summary[k] is not None for k in kinds)
                            else None)       # None = Kilo reported no usage: unknown, never 0
            actual = (None if actual_input is None and summary['output_tokens'] is None
                      else (actual_input or 0) + (summary['output_tokens'] or 0) + (summary['reasoning_tokens'] or 0))

            def account(state, row):
                """What the call showed, on the FRESH state: the idle series, a cooling, the true-up of the booking and
                the ledger -- one commit."""
                counters = factory_env(state)['idle']
                task_key = 'task:%s:%s' % (tid, 'review' if role == 'review' else 'code')
                keys = (task_key, 'channel:' + str(selected['id'] if selected else chosen))
                prior = counters.get(task_key) if type(counters.get(task_key)) is int else 0    # only the TASK's own series blocks it
                ceiling = idle and prior >= IDLE_SUSPECTS_ALLOWED      # a broken launch must trip the brake, not cool forever
                info = channels.classify(stdout, stderr, code, idle=idle and not ceiling)
                if ceiling:
                    info['ceiling'] = True
                    if selected is not None:       # the NEXT task on this channel must not meet the same wall at once
                        channels.cool(state.setdefault('channel_quotas', {}), selected,
                                      seconds=channels.RATE_SUSPECT_COOL_S)
                    counters.pop(keys[1], None)
                if idle and not ceiling:
                    for k in keys:
                        counters[k] = (counters.get(k) if type(counters.get(k)) is int else 0) + 1
                elif summary['steps'] > 0 or summary['tool_events'] > 0 or info['kind'] == 'ok':
                    for k in keys:
                        counters.pop(k, None)               # real work was seen: the series is over
                if selected is not None:
                    # no usage reported: the fact is unknown, so the token booking stays whole
                    charged = actual_input if actual_input is not None else tokens
                    # Kilo retries inside a failed call and the retries spend quota the stream never shows: after a
                    # failure, or when nothing was reported, the booking stays whole; only a clean call is trued up
                    unknown = summary['steps'] == 0 and actual_input is None
                    failed = code != 0 or info['kind'] != 'ok' or summary['provider_error']
                    fact = max(booked, summary['steps']) if (failed or unknown) else max(1, summary['steps'])
                    if info['kind'] == 'network':
                        fact = 0         # no HTTP answer: the request never reached the provider's quota
                    channels.reconcile(state['channel_quotas'], selected, at, tokens, charged,
                                       requests=booked, actual_requests=fact)
                    # the series of failed calls of this channel: 'ok' with the whole output limit spent and no word
                    # of answer is a failure too (live 20.11: ~174 s each); no connection at all is the laptop's net,
                    # a task too big for the channel is the task's problem
                    empty = (info['kind'] == 'ok' and summary['finish_reason'] in ('length', 'max_tokens')
                             and not (summary['text'] or '').strip())
                    if info['kind'] not in ('network', 'too_big'):
                        streak = channels.note_outcome(
                            state['channel_quotas'], selected,
                            not empty and (info['kind'] == 'ok' or (info['kind'] == 'unknown' and code == 0)),
                            channels=configured)
                        if streak.get('reason'):
                            info['streak_cool'] = streak
                    if ledger is not None:
                        quota_ledger.publish(ledger, str(checkpoint), state['channel_quotas'])
                return info
            info = ck.commit(account)
            if info.get('suspect') and 'rate_limited_suspect' not in events:
                events.append('rate_limited_suspect')
            calls.append({'role': role, 'attempt': attempt, 'channel': selected['id'] if selected else None,
                          'model': chosen, 'reserved_tokens': tokens, 'actual_tokens': actual,
                          'actual_input_tokens': actual_input,
                          'input_tokens': summary['input_tokens'], 'output_tokens': summary['output_tokens'],
                          'reasoning_tokens': summary['reasoning_tokens'],
                          'cache_read_tokens': summary['cache_read_tokens'],
                          'cache_write_tokens': summary['cache_write_tokens'],
                          'candidate': ctx.get('candidate', 0) if role != 'review' else None,
                          'dur_s': elapsed, 'error_class': None if info['kind'] == 'ok' else info['kind'],
                          'http_status': info.get('status'), 'returncode': code,
                          'tool_events': summary['tool_events'], 'steps': summary['steps'],
                          'last_step_tools': summary['last_step_tools'],
                          'finish_reason': summary['finish_reason'], 'files_read': summary['files_read'],
                          'provider_error': info['kind'] not in ('ok', 'unknown') or summary['provider_error'],
                          'cool_reason': info.get('streak_cool', {}).get('reason'),
                          'cool_s': info.get('streak_cool', {}).get('cool_s')})
            ctx['last_text'] = summary['text']
            kind = info['kind']
            if kind == 'ok' or (kind == 'unknown' and code == 0):
                return code, stdout, stderr
            if kind in ('timeout', 'launcher'):
                raise ChannelFault(info)
            if selected is not None:
                def failure(state, row):
                    outcome = channels.apply_failure(state['channel_quotas'], selected, info, env=os.environ)
                    if ledger is not None:
                        quota_ledger.publish(ledger, str(checkpoint), state['channel_quotas'])
                    return outcome
                done = ck.commit(failure)
            else:
                done = {'cool_s': info.get('retry_after_s') or 0}
            if kind == 'transient' and selected is not None and retry < TRANSIENT_HOPS:
                # owner: on a 503 the step does not wait or throw the candidate away, it moves to a free model at
                # once (live 21.11 20:41-21:01: <id>_test lost three gate-passed candidates, 4-7 min each, because both
                # review channels were one overloaded Gemma). Only this call skips the model; its cooling is the channel's.
                hopped.append(chosen)
                last_info = info
                continue
            if kind in ('transient', 'network') and retry == 0:
                if done.get('action') != 'cool_model' and not info.get('streak_cool'):   # cooled: the retry takes another one at once
                    time.sleep(channels.TRANSIENT_RETRY_S)   # (live 20.11: a 503 of Gemma cost ~67 s, 20 s of it here)
                continue
            raise ChannelFault(info, done.get('cool_s') or 0)
        raise ChannelFault({'kind': 'transient'})  # unreachable guard

    def soonest(default: float) -> float:
        """Wait of the channel that can actually serve the NEXT step (coder, or a reviewer of another model)."""
        if not configured:
            return default
        pool = [c for c in configured if not (ctx['role'] == 'review' and c['model'] == ctx['coder_model'])]
        quota = ck.read().get('channel_quotas', {})
        seen = quota_ledger.view(quota, quota_ledger.others(ledger, str(checkpoint))) if ledger is not None else quota
        wait = channels.next_wait(pool, seen, ctx['last_tokens'], os.environ,
                                  requests=1 if ctx.get('light') else
                                  requests_for(REVIEW_STEPS if ctx['role'] == 'review' else PROVIDER_STEPS))
        return default if wait is None else max(5.0, wait)

    def fault(error: ChannelFault) -> dict:
        kind = error.info['kind']
        report['reason_detail'] = scrub(redact(error.info.get('message', '')))[:300]
        if ctx['role'] == 'review' and kind == 'timeout' and error.info.get('ceiling'):
            return block('reviewer_failed', 'idle reviewer timeout %d times in a row.%s'
                         % (IDLE_SUSPECTS_ALLOWED + 1, park_candidate()), keep=True)
        if ctx['role'] == 'review' and kind in ('timeout', 'launcher'):
            return release_or_block('reviewer_failed', INFRA_DEFER_S)  # the candidate stays pending
        if kind in ('rate_minute', 'rate_day'):
            return release(kind, soonest(error.wait_s or error.info.get('retry_after_s') or channels.DEFAULT_COOL_S))
        if kind == 'region':
            return release(kind, soonest(60))
        if kind in ('key_invalid', 'model_missing'):
            return release(kind, soonest(60))
        if kind == 'too_big':      # the task does not fit the provider budget: the task's problem, not the channel's
            return block('context_too_large', error.info.get('message', ''))
        if kind == 'balance':
            return release('balance', soonest(error.wait_s or channels.BALANCE_COOL_S))
        if kind == 'transient':
            return release('transient', 60)
        if kind == 'network':
            # the machine has no network: every channel fails the same way, so the loop brake decides (a series
            # of these stops the factory instead of spending the daily call budget on passes that cannot work)
            return release('network', 60, infra=True)
        if kind == 'timeout':
            return block('worker_timeout', infra=True)
        if kind == 'launcher':
            return block('unsafe_windows_launcher', error.info.get('message', ''), infra=True)
        return release_or_block('provider_error', INFRA_DEFER_S)

    base_holder = None
    gate_tmp = staging / 'tmp'     # pytest's own temp (--basetemp) stays inside staging, never under the profile
    slot = {'armed': False, 'left': float(SLOT_BUDGET_S), 'waited': 0.0}   # armed at the FIRST gate run

    def gate_run(tree, tests, touched=None):
        """gate.run_tests with the pass-wide slot budget: what is left of it, never a fresh one per call, and it is
        spent by WAITING for a slot only (GateResult.slot_wait_s), never by the run time of the tests. What was cut
        at the limit on the base (files, single tests) is handed over: the candidate run starts file by file and runs
        those tests alone (a joint run would only be cut again)."""
        slot['armed'] = True
        known = getattr(ctx.get('counts'), 'timed_out', ())
        result = gate.run_tests(tree, tests, GATE_TIMEOUT_S, workdir=gate_tmp,
                                wait_s=max(0.0, slot['left']), **({'hung': known} if known else {}),
                                **({'touched': tuple(touched)} if touched is not None else {}))
        waited = float(getattr(result, 'slot_wait_s', 0.0) or 0.0)
        slot['left'] -= waited
        slot['waited'] += waited
        stages['slot_wait_s'] = round(slot['waited'], 3)
        return result

    def park_candidate() -> str:
        """Save the diff of a paid candidate outside every sweep (staging/parked) and name it for Opus."""
        parked = staging / 'parked' / (tid + '.diff')
        parked.parent.mkdir(parents=True, exist_ok=True)
        parked.write_text(unified_diff(ctx['baseline'], ctx['workdir'], list(task.touch_files), 10 * DIFF_LIMIT),
                          encoding='utf-8')
        return ' The candidate diff is kept in parked/%s.diff.' % tid

    def env_release(why_text: str, candidate: bool = True) -> dict:
        """The environment failed, not the candidate: no strike, no feedback to the model, and a block ONLY for a
        persistent reason. The gate may hand the reason over as an ``env:`` verdict: the prefix is not part of it.
        'pytest slot:' (no slot / no RAM) is a passing shortage: release_transient with a long hold after many in a
        row, never a block. Any other reason (a missing package) has its own small ceiling, then parks the task
        for Opus with the candidate saved. (A dedicated defer reason waits for <id>; 'transient' is whitelisted.)"""
        reason = why_text[4:].lstrip() if why_text.startswith('env:') else why_text
        report['reason_detail'] = scrub(redact(reason))[:300]
        events.append('env_shortage')

        def count_it(state, row):
            """The environment counters and the kept candidate, on the fresh state: ONE commit."""
            table = factory_env(state)
            if not reason.startswith('pytest slot:'):
                seen = (table['other'].get(tid) if type(table['other'].get(tid)) is int else 0) + 1
                table['other'][tid] = seen
                if seen >= ENV_OTHER_CEILING:
                    table['other'].pop(tid, None)
                    return 'park', seen, False
            if candidate:      # (the red_before check runs before any candidate exists; a pending one stays as it is)
                set_pending(state, row)
            count = (table['shortages'].get(tid) if type(table['shortages'].get(tid)) is int else 0) + 1
            if reason.startswith('pytest slot:'):
                table['shortages'][tid] = count
            return 'release', count, bool(row.get('pending_review'))
        what, count, pending_now = ck.commit(count_it)
        if what == 'park':
            saved = park_candidate() if candidate else ''
            return block('gate_unknown', "ENV: %s (%d passes in a row; not the candidate fault).%s"
                         % (reason, count, saved), keep=True)
        report['pending_review'] = pending_now
        return release('transient', ENV_HOLD_S if count >= ENV_HOLD_AFTER else INFRA_DEFER_S)

    def base_root() -> Path:
        """Scratch copy of the source tree: the base runs execute untrusted tests, never in the live tree."""
        tree = Path(base_holder) / 'tree'
        if not tree.exists():
            shutil.copytree(root, tree, ignore=COPY_IGNORE)
            ctx['roots'].append(tree)
        return tree

    baseline_dir = None
    owned, live, parsed = set(), set(), True
    for other_tid, other in ck.read()['tasks'].items():     # fresh: other workers' candidates and leases are theirs
        for held in (other.get('pending_review'), other.get('candidate')):   # an approved candidate waits for its promote
            if held is not None:
                if isinstance(held, dict) and isinstance(held.get('workdir'), str):
                    try:
                        if '\0' in held['workdir']:      # Python 3.13+ resolve() no longer refuses an embedded NUL
                            raise ValueError('embedded null character')
                        owned.add(Path(held['workdir']).resolve())
                    except (OSError, ValueError, RuntimeError):
                        parsed = False
                else:
                    parsed = False     # a record we cannot read may own a copy: collect nothing this pass
        if other.get('status') == 'RUNNING' and isinstance(other.get('lease'), str):
            live.add('task-%s-%s' % (other_tid, other['lease'][:8]))
    if not parsed:
        events.append('cleanup_skipped_unparsed_pending')
    for stale in (staging.glob('task-*') if parsed else ()):   # copies of passes that no task owns any more
        try:
            if (stale.is_symlink() or not stale.is_dir() or not inside_staging(stale.resolve(), staging)
                    or stale.resolve() in owned
                    or any(stale.name == p or stale.name.startswith(p + '-') for p in live)):
                continue
            # younger than two leases: an expired-lease writer may still be writing into it
            if time.time() - stale.stat().st_mtime > 2 * LEASE_LIFETIME_S:
                shutil.rmtree(stale)
        except FileNotFoundError:
            pass
        except OSError:
            events.append('stale_baseline_kept' if stale.name.endswith('-baseline') else 'pending_copy_kept')
    try:
        base_holder = tempfile.mkdtemp(prefix='factory-base-')   # inside the try: an OSError here is a released pass
        pending = row.get('pending_review')
        if pending is not None and not (isinstance(pending, dict) and isinstance(pending.get('workdir'), str)
                                        and isinstance(pending.get('baseline_digest'), str)):
            ck.commit(lambda s, r: r.pop('pending_review', None))  # corrupt record: treat as absent
            events.append('pending_dropped')
            pending = None
        baseline_dir = ctx['workdir'] if not pending else staging / (prefix + '-baseline')
        ctx['baseline'] = prepare(root, task, baseline_dir)
        ctx['read_chars'] = sum(len(ctx['baseline'][n]) for n in large_names(task, ctx['baseline']))
        baseline_digest = sha256(b''.join(n.encode() + sha256(v).digest()
                                          for n, v in sorted(ctx['baseline'].items()))).hexdigest()
        if pending:
            old = Path(pending['workdir'])
            inside = inside_staging(old, staging)
            if pending.get('baseline_digest') != baseline_digest or not old.is_dir() or not inside:
                # HEAD moved (or the work copy is gone): the old candidate is void. Start fresh, no strike.
                ck.commit(lambda s, r: r.pop('pending_review', None))
                events.append('pending_dropped')
                if inside and old.is_dir():
                    shutil.rmtree(old, ignore_errors=True)
                ctx['workdir'] = baseline_dir
                pending = None
            else:
                ctx['workdir'] = old.resolve()
                ctx['coder_model'] = pending.get('coder_model')

        # 1. Base verdict before any model call: green = already done, unknown = infrastructure. A red base measured on
        # the same commit with the same tests and files is reused (base_red): it cannot change, and with a hanging
        # test file it cost 70 s every pass (live 20.11 05:25-05:37).
        key = _base_key(base_sha, task, ctx['baseline'])
        held = _held_base(row, key, task.kind)
        if held is not None:
            verdict, base = 'red', held
            events.append('base_reused')
        else:
            verdict, base = timed('red_before_s', lambda: gate.red_before(
                base_root() if task.kind != 'unit_test' else root, task.tests, GATE_TIMEOUT_S, task.kind,
                wait_s=(min(RED_BEFORE_WAIT_S, max(0.0, slot['left'])) if slot['armed'] else RED_BEFORE_WAIT_S),
                workdir=gate_tmp, touched=(), **({'trace': path_trace(task)} if path_trace(task) else {})))
            keep_red = (key and verdict == 'red' and not base.env_reason and task.kind != 'unit_test')

            def note_base(state, row):
                row.pop('base_red', None)
                if keep_red:
                    row['base_red'] = {'key': key, 'at': _now(), 'result': dataclasses.asdict(base)}
            ck.commit(note_base)
        ctx['counts'] = base
        if verdict == 'green':
            return block('already_green', 'the task tests already pass on the base')
        if verdict == 'unknown' and base.env_reason:
            return env_release(base.env_reason, candidate=False)    # the machine, not the task: never a block
        if verdict == 'unknown':
            report['reason_detail'] = scrub(redact(base.diag))[:300]
            return release_or_block('gate_unknown', INFRA_DEFER_S)

        # the path of the failing tests: on it in the task's files (shown first) / outside them (named, checked)
        on_mods, off_mods = gate.path_split(getattr(base, 'path', ()), task.touch_files) if task.kind == 'code' \
            else ({}, {})
        try:
            off_short = gate.off_path_short(off_mods, root, task.tests, OFF_PATH_SHORT, base.failed_ids) \
                if off_mods else []
            ranked_on = gate.rank_path(on_mods, root, task.tests, base.failed_ids) if on_mods else []
        except Exception:  # noqa: BLE001 - an order of names only: without it the lists stay unsorted
            off_short = ['%s.%s' % (m.rsplit('/', 1)[-1].rsplit('.', 1)[0], q)
                         for m, qs in off_mods.items() for q in qs][:OFF_PATH_SHORT]
            ranked_on = [(m, q) for m, qs in on_mods.items() for q in qs]
        leaves = [q.rpartition('.')[2] for _, q in ranked_on]
        path_focus = frozenset([n for n in dict.fromkeys(leaves)
                                if identifier_tokens(n) == {n} and not n.startswith('__')][:PATH_FOCUS_MAX])
        held_ne = row.get('no_effect')
        prior_ne = (held_ne['n'] if key and isinstance(held_ne, dict) and held_ne.get('key') == key
                    and type(held_ne.get('n')) is int else 0)

        def no_effects() -> int:
            return prior_ne + events.count('no_effect')

        def no_effect_block() -> dict | None:
            """The NO_EFFECT_BLOCK_AFTER-th change without effect on one base, with a path to show: BLOCKED for Opus
            with the functions the failing test runs outside the task (more passes would only repeat it)."""
            if not off_short or no_effects() < NO_EFFECT_BLOCK_AFTER:
                return None
            return block('off_path', 'the change had no effect %d times on the same base; the failing test runs '
                         'outside the task files: %s' % (no_effects(), ', '.join(off_short)))

        def scope_signal():
            """(module, name) when the last coder answer named a function of the failing test's path outside the task:
            a CANNOT name, or the file of an edit block outside the task; None otherwise."""
            note, text = ctx.get('light_note') or '', ctx.get('last_text') or ''
            said = re.search(r'CANNOT:\s*(.*)', note) or re.search(r'(?im)^\W*CANNOT:\s*(.*)$', text)
            names = cannot_names(said.group(1)) if said else []
            if 'outside the task' in note and off_mods:   # the light engine's count of blocks for other files
                names += outside_names(text, tuple(task.touch_files))
            for name in names:
                module = gate.path_lookup(off_mods, name) if off_mods else None
                if module:
                    return module, name
            if task.kind == 'code':     # 21.11: a CANNOT naming any repo file or function outside the task: same path
                for name in cannot_names(said.group(1)) if said else []:
                    module = repo_scope_target(root, name, task.touch_files, task.kind)
                    if module:
                        return module, name
            return None

        def cannot_loop():
            """The same CANNOT text twice in a row and no widening possible: more attempts would only repeat it;
            BLOCKED with the text as the reason (the existing quarantine), None otherwise."""
            note, text = ctx.get('light_note') or '', ctx.get('last_text') or ''
            said = re.search(r'CANNOT:\s*(.*)', note) or re.search(r'(?im)^\W*CANNOT:\s*(.*)$', text)
            if said and cannot_repeats(row.get('feedback'), said.group(1), scrub):
                return block('cannot_repeat', 'the model answered the same CANNOT twice in a row and no repo file or '
                             'function it names can be added to the task: ' + said.group(1).strip()[:150])
            return None

        def widen(module: str, name: str) -> dict:
            """The task's scope misses a module the failing test runs and the model named: the loop adds it to
            touch_files (report scope_add, no strike); over LIGHT_MAX_FILES or a forbidden path: BLOCKED for Opus."""
            why = gate.is_forbidden(module, task.kind) or (
                'more than %d files' % LIGHT_MAX_FILES if len(task.touch_files) + 1 > LIGHT_MAX_FILES else '')
            if why:
                return block('off_path', '%s (%s) runs in the failing test outside the task; it cannot be added: %s'
                             % (module, name, why))
            events.append('scope_add:' + module)
            report['scope_add'] = [module]
            report['reason_detail'] = scrub(redact('%s (%s) runs in the failing test outside the task' % (module, name)))
            return release('off_path', OFF_PATH_WAIT_S)

        def red_on(model) -> None:
            """<id>: the test ids the candidate of ``model`` was red on, for the loop's audit of a factory test."""
            ids = sorted(getattr(ctx.get('counts'), 'failed_ids', ()) or ())
            ctx.setdefault('gate_red', []).append([str(model or ''), ids])

        # 3. Deterministic gates (factory_gate only). A decision, not a settlement: a dict ends the pass; a
        # _GateRetry is a real test failure the tournament may answer with another model; (changed, receipt) goes on.
        def run_gates():
            changed = inspect_changes(task, ctx['workdir'], ctx['baseline'])
            if not changed:
                last = calls[-1] if calls else {}
                if last.get('steps', 0) >= PROVIDER_STEPS and not last.get('last_step_tools'):
                    events.append('steps_exhausted')    # the model ran out of steps and answered in text only
                    return reject('gate', 'gate:steps_exhausted',
                                  'the step limit ended the call without an edit (last step had no tool use)', ())
                note = ctx.get('light_note') or ''
                return reject('gate', 'gate:no_changes', 'the model produced no change to the approved files'
                              + (' (' + note + ')' if note else ''), ())
            cand_files = {n: ctx['workdir'].joinpath(*n.split('/')).read_text(encoding='utf-8', errors='replace')
                          for n in changed}
            for name, source in cand_files.items():
                if name.endswith('.py'):
                    try:
                        compile(source, name, 'exec')
                    except (SyntaxError, ValueError) as error:
                        return reject('gate', 'gate: compile error in ' + name,
                                      'does not compile: %s' % error, changed)
            problems = gate.weakening_violations(root, cand_files, task.kind, task.touch_files)
            if problems:
                text = '; '.join(problems)
                return reject('gate', 'weakening: ' + text[:300], 'weakening of the checks: ' + text, changed)
            if task.kind == 'unit_test':
                if task.backlog_id:
                    first = next((n for n in changed if n in task.tests), task.tests[0])   # the first CHANGED test file
                    marker_ok, marker_why = gate.accept_unit_test(MARKER_PROBE, cand_files.get(first, ''), task.backlog_id)
                    if not marker_ok:   # cheaper than running pytest first
                        return reject('gate', 'gate: ' + marker_why[:300], marker_why, changed)
                else:
                    events.append('unit_test_marker_skipped')   # nothing to check against: never an unfixable rejection
            try:      # mechanical facts for the critics (never a verdict): hollow findings, names added beyond the task
                ctx['hollow'], ctx['extra_names'] = gate.candidate_findings(root, cand_files, task.kind)
            except Exception:       # noqa: BLE001  a report fault must not stop the gate
                ctx['hollow'], ctx['extra_names'] = (), ()
            with tempfile.TemporaryDirectory(prefix='factory-gate-tree-', ignore_cleanup_errors=True) as d:
                tree = candidate_tree(root, ctx['workdir'], changed, Path(d))
                ctx['roots'].append(tree)
                # the gate decides whether a missing module is the environment or the candidate's own import (live
                # 19.11 18:06-18:08: written tests imported modules that do not exist and went round as 'environment')
                red_ids = [i for _, ids in ctx.get('gate_red', ()) for i in ids]
                cand = gate.candidate_import(timed('gate_s', lambda: staged_run(
                    lambda part: gate_run(tree, part, touched=changed), root, task.tests,
                    red_entries(red_ids, task.tests))), root, tree, changed)
                ctx['counts'] = cand
                if cand.env_reason:
                    return env_release(cand.env_reason)
                def measured(state, row):       # measured: both environment series are over
                    factory_env(state)['shortages'].pop(tid, None)
                    factory_env(state)['other'].pop(tid, None)
                ck.commit(measured)
                # pytest executes untrusted code: it may not rewrite the frozen tests or inputs.
                for name in sorted((set(task.tests) | set(task.read_files)) - set(changed)):
                    original, after = root.joinpath(*name.split('/')), tree.joinpath(*name.split('/'))
                    if original.is_file() and (not after.is_file() or after.read_bytes() != original.read_bytes()):
                        return reject('gate', 'gate: immutable file changed during pytest',
                                      'pytest changed a frozen file: ' + name, changed)
                if task.kind == 'unit_test':
                    added = []
                    for name in changed:     # the test functions this candidate ADDS (all of a new file)
                        if name in task.tests and name.endswith('.py'):
                            before = root.joinpath(*name.split('/'))
                            old_text = before.read_text(encoding='utf-8', errors='replace') if before.is_file() else ''
                            added += gate.added_tests(old_text, cand_files.get(name, ''))
                    ok, why = gate.accept_unit_test(cand, added=added)
                else:
                    ok, why = gate.accept(base, cand, verdict == 'red')
                if not ok and why.startswith('env:'):
                    return env_release(why)
                if not ok and task.kind != 'unit_test' and gate.undecided(base, cand):
                    # the budget left tests unrun and nothing that ran is red: not this candidate's failure, and the next
                    # model would spend the same budget again; the third such pass in a row blocks it (ESCALATE)
                    events.append('gate_undecided:%d' % len(cand.unrun))
                    report['reason_detail'] = ('%d test(s) of the task were not run here (the gate budget was spent); '
                                               'nothing that ran is red' % len(cand.unrun))
                    return release_or_block('gate_unknown', INFRA_DEFER_S)
                if not ok:
                    no_effect = task.kind != 'unit_test' and same_failure(base.diag, cand.diag)
                    if no_effect:
                        events.append('no_effect')
                    return _GateRetry(('gate', 'gate: ' + why[:300],
                                       ('[no effect] ' if no_effect else '') + why + '\n' + cand.diag, changed),
                                      cand.diag or why, changed, no_effect)
                left = gate.unmeasured(base, cand) if task.kind != 'unit_test' else ()
                if left:      # accepted on every test that ran; these hang or lack a package here on both sides
                    events.append('unmeasured:%d' % len(left))
                if task.kind != 'unit_test':
                    try:
                        near = gate_order(root, neighbor_tests(root, task)[:MAX_NEIGHBORS], ctx.get('neighbour_red', ()))
                    except Exception as error:  # noqa: BLE001 - "graph unavailable" is not "no neighbours"
                        events.append('neighbors_unavailable:' + redact(type(error).__name__))
                        near = []
                    if near:
                        def neighbours():
                            skipped_count = 0
                            last_result = None
                            settled = gate.cloud_each(tree, near)     # one cloud run for all of them; {} = not answered: local
                            for name in near:
                                mine = settled[name] if name in settled else gate_run(tree, [name])
                                last_result = mine
                                if mine.env_reason:
                                    return 'env', mine
                                if not mine.junit_ok and not (mine.failed or mine.errors):
                                    skipped_count += 1
                                    continue
                                if mine.failed + mine.errors > 0:
                                    theirs = gate_run(base_root(), [name], touched=())
                                    last_result = theirs
                                    if theirs.env_reason:
                                        return 'env', theirs
                                    if not theirs.junit_ok and not (theirs.failed or theirs.errors):
                                        return 'unknown', mine
                                    if mine.failed_ids or theirs.failed_ids:
                                        fresh = set(mine.failed_ids) - set(theirs.failed_ids)
                                    else:
                                        fresh = {'count'} if mine.failed + mine.errors > theirs.failed + theirs.errors else set()
                                    if fresh:
                                        ctx.setdefault('neighbour_red', []).append(name)
                                        return 'regression', mine
                            if skipped_count == len(near):
                                return 'skipped', last_result
                            if skipped_count > 0:
                                events.append('neighbors_skipped')
                            return 'ok', last_result
                        outcome, mine = timed('neighbors_s', neighbours)
                        if outcome == 'env':
                            return env_release(mine.env_reason)
                        if outcome == 'skipped':
                            events.append('neighbors_skipped')
                        elif outcome == 'unknown':
                            report['reason_detail'] = 'neighbour tests of the base are not measured'
                            # keep the candidate: the next pass resumes at the gates and measures, no new coder call
                            ck.commit(lambda s, r: set_pending(s, r))
                            report['pending_review'] = True
                            return release_or_block('gate_unknown', INFRA_DEFER_S)
                        elif outcome == 'regression':
                            return _GateRetry(('gate', 'gate:neighbors_regression',
                                               'new red among neighbour tests: ' + ', '.join(near) + '\n' + mine.diag,
                                               changed), mine.diag, changed)
            receipt = _digest(json.dumps(_counts(cand)), ','.join(changed))
            return changed, receipt

        # 2. The coder call(s) (a rejected candidate comes back next pass with feedback and its diff).
        decision = None
        if not pending:
            feedback = fresh_feedback(state, tid)       # the state of the start of the pass: its own feedback is final
            feedback = scrub(feedback) if feedback else feedback
            prev_diff = prev_diff_file.read_text(encoding='utf-8') if prev_diff_file.is_file() else ''
            role = 'repair' if (feedback or attempt > 1) else 'code'
            visible = {name: safe_source(ctx['workdir'] / name) for name in
                       sorted(set(task.touch_files + task.read_files + task.tests))
                       if (ctx['workdir'] / name).exists()}
            # the reviewer sees the small files whole plus its instructions and a diff: refuse BEFORE the coder is paid for
            small_total = sum(len(v) for n, v in visible.items() if n not in large_names(task, visible))
            if small_total + REVIEW_DIFF_LIMIT + REVIEW_OVERHEAD > channels.PROMPT_LIMIT_CHARS:
                raise PromptTooLarge('coder+review prompts cannot both fit')
            failing = (', '.join(base.failed_ids) + '\n' + base.diag).strip() if task.kind == 'code' else ''
            # ``root`` is the loop's plain copy of the sources (no .git): an old commit is read from the repository itself
            reference = port_reference(port_repo or root, task)
            if reference:
                events.append('port_reference:%d' % len(reference))
            elif task.port_from and task.kind != 'unit_test':
                events.append('port_reference_missing')      # a lost example shows in the telemetry, never silently
            focus = (port_focus(port_repo or root, task) if reference else frozenset()) | path_focus
            remembered = frozenset(state['tasks'][tid].get('asked') or ()) & defined_names(task, ctx['workdir'])

            def make_prompt(asked=frozenset()):
                return build_coder_prompt(task, visible, feedback, prev_diff, failing=scrub(failing),
                                          light=engine_for(role, task) == 'light',   # the same rule call() applies
                                          asked=frozenset(asked) | remembered, reference=reference, focus=focus, off_path=tuple(off_short))
            prompt = make_prompt()
            chosen = route(task, small_model=small_model, large_model=large_model, fallback=attempt > 1)

            def dir_for(retry: int) -> Path:
                if retry:  # a failed worker may have written files; never reuse its directory
                    ctx['workdir'] = staging / (prefix + "-retry-" + str(retry))
                    ctx['baseline'] = prepare(root, task, ctx['workdir'])
                return ctx['workdir']

            def unusable() -> str:
                """Step 3's mechanical checks, without a strike: why this candidate cannot go to the gate ('' when it
                can). A candidate that fails them makes room for the tournament's next model."""
                now = inspect_changes(task, ctx['workdir'], ctx['baseline'])
                if not now:
                    return ctx.get('light_note') or 'its answer changed no file'
                texts = {n: ctx['workdir'].joinpath(*n.split('/')).read_text(encoding='utf-8', errors='replace')
                         for n in now}
                for name, source in texts.items():
                    if name.endswith('.py'):
                        try:
                            compile(source, name, 'exec')
                        except (SyntaxError, ValueError) as error:
                            return 'its edit of %s does not compile (%s)' % (name, error)
                if gate.weakening_violations(root, texts, task.kind, task.touch_files):
                    return 'its edit weakened a check'
                if task.kind == 'unit_test' and task.backlog_id:
                    first = next((n for n in now if n in task.tests), task.tests[0])
                    ok, why = gate.accept_unit_test(MARKER_PROBE, texts.get(first, ''), task.backlog_id)
                    return '' if ok else why
                return ''

            def gate_note(failure) -> str:
                """The note for the next coder after a real test failure: the failing output (scrubbed, redacted) and the
                diff of the candidate. Over PROMPT_LIMIT_CHARS the diff goes first, then the output is shortened."""
                output = scrub(redact(failure.diag))[:TOURNAMENT_OUTPUT_LIMIT]
                diff = unified_diff(ctx['baseline'], ctx['workdir'], failure.changed, DIFF_LIMIT)
                room = channels.PROMPT_LIMIT_CHARS - len(prompt)
                lead = (NO_EFFECT_NOTE + (OFF_PATH_NOTE % ', '.join(off_short) if off_short else '')
                        if getattr(failure, 'no_effect', False) else '')
                for part in (TOURNAMENT_DIFF_NOTE % diff if diff else '', ''):
                    note = lead + TOURNAMENT_GATE_NOTE % output + part
                    if len(note) <= room:
                        return note
                fixed = len(TOURNAMENT_GATE_NOTE % '')
                return TOURNAMENT_GATE_NOTE % output[:max(0, room - fixed)] if room > fixed else ''

            def coder_exclusions(tried_now):
                """``exclude_model`` of a coder call. ``tried_now`` (this pass's earlier candidates) are always out; the
                models that failed this task in earlier attempts are out too while the router has another model for
                the call (a preference, never a reason to stop: with none left the call takes any)."""
                now_out = list(tried_now)
                older = [m for m in failed_models_of(row) if m not in now_out]
                if older and configured:
                    live_now = ck.read().get('channel_quotas') or {}
                    if channels.usable(channels.route_order(
                            configured, 'code', attempt, channels.estimate_tokens(len(prompt), 0),
                            exclude_model=now_out + older, state=live_now,
                            skip_tiers=() if small_follow_up or not now_out else ('small',)),
                            live_now, os.environ):   # a dead channel (checked with the call's own env) is no other model
                        tag = 'other_model_than_%d' % len(older)
                        if tag not in events:
                            events.append(tag)
                        return now_out + older
                return now_out or None

            size = TOURNAMENT_SIZE if configured and engine_for(role, task) == 'light' else 1
            tried, k_prompt, held, gate_failed, next_note = [], prompt, None, [], ''
            ctx['tried'] = tried     # the models of this pass's earlier candidates: reject() remembers them as failed
            asked = frozenset()      # code an earlier candidate of this pass asked for: every later one is shown it
            for k in range(size):
                if k:
                    held = (ctx['workdir'], ctx['baseline'])
                    tried.append(ctx['coder_model'])
                    view = make_prompt(asked) if asked else prompt
                    k_prompt = view + next_note
                    if len(k_prompt) > channels.PROMPT_LIMIT_CHARS:
                        k_prompt = view
                    ctx['workdir'] = staging / ('%s-cand-%d' % (prefix, k))
                    shutil.rmtree(ctx['workdir'], ignore_errors=True)
                    ctx['baseline'] = prepare(root, task, ctx['workdir'])
                    events.append('tournament_candidate_%d' % (k + 1))
                ctx['candidate'] = k
                def coder_call(tried=tried, k=k, k_prompt=k_prompt):
                    skip = () if small_follow_up or not k else ('small',)        # <id> small_follow_up
                    excluded = coder_exclusions(tried)
                    try:
                        return call(role, task, dir_for, chosen, k_prompt, exclude_model=excluded, skip_tiers=skip, later=bool(k))
                    except channels.ChannelUnavailable:
                        if len(excluded or ()) <= len(tried):
                            raise
                        # live 21.11 13:23: <id> spent all 6 attempts on one flash-lite in 3 min while the fresh models
                        # were busy for a minute. The first pass waits for a fresh model (this task only, a minute,
                        # no attempt spent) up to FRESH_WAITS times; after that it takes any model (13:11: never a stop).
                        if not k and defer_streak(ck.read(), tid, 'fresh_model_busy') < FRESH_WAITS:
                            raise _FreshBusy()
                        events.append('other_model_none_free')
                        return call(role, task, dir_for, chosen, k_prompt, exclude_model=list(tried) or None,
                                    skip_tiers=skip, later=bool(k))

                try:
                    rc, out, err = timed('code_s', coder_call)
                except _FreshBusy:
                    return release('fresh_model_busy', FRESH_WAIT_S)
                except (ChannelFault, channels.ChannelUnavailable, NoIndependentReviewer):
                    if not k:
                        raise
                    ctx['workdir'], ctx['baseline'] = held      # no further model now: the last candidate stands
                    events.append('tournament_short')
                    break
                decision = None          # the earlier candidate's failure is history now; this one is judged afresh
                ctx['coder_model'] = calls[-1]['model']
                if event_summary(out)['finish_reason'] in ('length', 'max_tokens'):
                    events.append('output_truncated')
                signal = scope_signal()
                if signal:                           # it named code of the failing path outside the task
                    return widen(*signal)
                stuck = cannot_loop()
                if stuck:
                    return stuck
                if k + 1 >= size:
                    break                            # the tournament is full: this candidate stands
                why = unusable()
                if why:                              # mechanically unusable: the next model hears why
                    next_note = TOURNAMENT_NOTE % scrub(redact(why))[:300]
                    wanted = asked_names(why) - asked
                    if wanted:                       # it asked for code: the next view shows that code first
                        asked |= wanted
                        ctx['asked'] = asked
                        next_note += TOURNAMENT_ASKED_NOTE % ', '.join(sorted(wanted))
                    continue
                decision = run_gates()               # usable: the deterministic gates decide
                if not isinstance(decision, _GateRetry):
                    break                            # passed, or a final result (environment, unknown neighbour, ...)
                gate_failed.append(ctx['coder_model'])
                red_on(ctx['coder_model'])
                blocked = no_effect_block() if decision.no_effect else None
                if blocked is not None:
                    return blocked                   # the second change without effect on this base
                events.append('tournament_gate_retry_%d' % (k + 1))
                next_note = gate_note(decision)
            if size > 1:
                report['tournament'] = dict(size=size, candidates=ctx['candidate'] + 1,
                                            models=tried + [ctx['coder_model']])
                if gate_failed:
                    report['tournament']['gate_failed'] = list(gate_failed)
        if decision is None:
            decision = run_gates()                   # the standing candidate (or the kept one of a pending review)
            if isinstance(decision, _GateRetry):
                red_on(ctx.get('coder_model'))
                if 'tournament' in report:
                    report['tournament']['gate_failed'] = (report['tournament'].get('gate_failed', [])
                                                           + [ctx['coder_model']])
        if isinstance(decision, _GateRetry):
            if ctx.get('gate_red'):                  # <id>: which test ids each red model failed on (the loop's audit)
                report['gate_red'] = ctx['gate_red']
            blocked = no_effect_block() if decision.no_effect else None
            if blocked is not None:
                return blocked
            seen_ne = no_effects()
            mark = (lambda r: r.__setitem__('no_effect', {'key': key, 'n': seen_ne})) if key and seen_ne else None
            return reject(*decision.reject_args, mark=mark)   # the pass ends on its last gate failure: ONE rejection
        if isinstance(decision, dict):
            return decision
        changed, receipt = decision


        # 4. Independent reviewer: another model, reasons go back as feedback.
        ck.commit(lambda s, r: set_pending(s, r))

        critics = []      # the models that reviewed this candidate: the next critic is none of them, nor the coder
        told = rejected_for(ck.read(), tid)

        def invoke(call_task, directory, preferred, **kwargs):
            return call('review', call_task, lambda _retry: directory, preferred,
                        kwargs['prompt_override'], exclude_model=[ctx['coder_model']] + critics)
        try:
            hollow, extra = tuple(ctx.get('hollow') or ()), tuple(ctx.get('extra_names') or ())
            exec_text = execution_report(base, hollow, extra)
            mech_ok = mechanically_ok(base, hollow, extra)
            votes, said, rejections = [], [], []
            approved = None
            for n in range(REVIEW_PANEL):
                try:     # up to REVIEW_PANEL critics of different models, each with its own lens; the majority decides
                    ok, why = timed('review_s', lambda: review_candidate(
                        task, ctx['workdir'], review_model, invoke, baseline=ctx['baseline'], scratch=staging,
                        lens=REVIEW_LENSES[n], prior=tuple(said), rejected=told, rubric=True, execution=exec_text))
                except (NoIndependentReviewer, channels.ChannelUnavailable, ReviewFault, ChannelFault):
                    if not votes:
                        raise                      # the first critic failed: the handlers below decide
                    approved = panel_verdict(votes, True, mech_ok)   # no further model: a split goes to the ranking
                    if approved is not None:
                        break
                    if all(votes):     # rule 4 of 21.11: the paid critic is the insurance second voice when no free
                        paid_second = paid_critic.control(   # model is left (live 17:20-17:50: 19 chains cut short)
                            task, unified_diff(ctx['baseline'], ctx['workdir'], task.touch_files, paid_critic.DIFF_LIMIT)
                            if ctx['baseline'] is not None else '', (exec_text + '\n' + told)[-paid_critic.FAIL_LIMIT:])
                        if paid_second is not None:          # no key, no budget, a fault: the free wait below, as before
                            ctx['paid_done'] = paid_second
                            events.append('paid_second_critic')
                            approved = paid_second['verdict'] != 'reject'
                            if not approved:
                                paid_critic.record_class(task, paid_second)
                                rejections.append(scrub(redact('paid critic [%s]: %s' % (
                                    paid_second['class'], paid_second['reason'] or paid_second['symptom']))))
                            break
                    # no further model now: one critic never approves alone (live 20.11 16:46, <id> approved by one
                    # critic, its commit rejected 4 min later). The candidate stays pending, the chain starts again
                    # on a later pass; the same postponement ESCALATE_AFTER times in a row is BLOCKED (the term).
                    events.append('review_chain_short')
                    report['critics'] = list(critics)
                    report['critiques'] = [scrub(redact(s))[:300] for s in said]
                    report['pending_review'] = True
                    if ck.commit(chain_short) >= ESCALATE_AFTER:   # the term of the candidate, whatever came between
                        return block('review_chain_short', 'review chain cut short %d times' % ESCALATE_AFTER)
                    return release_or_block('review_chain_short', INFRA_DEFER_S)
                critics.append(calls[-1]['model'])
                if n:
                    events.append('review_chain_%d' % (n + 1))
                votes.append(ok)
                said.append('critic %d %s: %s' % (n + 1, 'approved' if ok else 'rejected', '; '.join(why) or 'no remarks'))
                if not ok:
                    rejections.extend(why or ['rejected without a stated reason'])
                approved = panel_verdict(votes, n + 1 == REVIEW_PANEL, mech_ok)
                if approved is not None:
                    break
            reasons = [] if approved else (rejections or ['the critics are split and the mechanical ranking is against'])
            report['critics'] = list(critics)
            # redacted like reason_detail: a critic may quote a key it saw (test_reason_and_feedback_are_redacted_...,
            # red since the chain landed; that test never reaches the public cloud run, its fake key blocks it)
            report['critiques'] = [scrub(redact(s))[:300] for s in said]
        except NoIndependentReviewer:
            report['pending_review'] = True
            return _wait(release_or_block, report, 'no_independent_reviewer', status='WAITING_CHANNEL')
        except channels.ChannelUnavailable as error:
            report['pending_review'] = True
            return _wait(release, report, 'channel_wait', error.wait_s, status='WAITING_CHANNEL',
                         channel_reason=error.reason)
        except ReviewFault as error:
            report['pending_review'] = True
            report['reason_detail'] = scrub(redact(str(error)))[:300]
            return release_or_block('reviewer_failed', INFRA_DEFER_S)
        if not approved:
            return reject('review', 'review: ' + '; '.join(reasons), '; '.join(reasons), changed)
        # owner rule 4: the paid control critic sees only would-be promotions (free chain approved, gates passed).
        # A reject goes back like a free critic's; the catch enters the error-class registry the free review reads.
        paid = ctx.get('paid_done') or paid_critic.control(task, unified_diff(ctx['baseline'], ctx['workdir'], task.touch_files,
                                                      paid_critic.DIFF_LIMIT) if ctx['baseline'] is not None else '',
                                   (exec_text + '\n' + told)[-paid_critic.FAIL_LIMIT:])
        if paid is not None:
            report['paid_critic'] = paid
            if paid['verdict'] == 'reject':
                paid_critic.record_class(task, paid)
                why = scrub(redact('paid critic [%s]: %s' % (paid['class'], paid['reason'] or paid['symptom'])))
                return reject('review', 'review: ' + why, why, changed)
        reviewed = staging / "for-review" / tid
        if reviewed.exists():
            shutil.rmtree(reviewed)  # left over from an earlier candidate of this task
        reviewed.mkdir(parents=True)
        for name in changed:
            dst = reviewed.joinpath(*name.split("/"))
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ctx['workdir'].joinpath(*name.split("/")), dst)

        def approve(state, row):
            status = settle(state, tid, token, tests_ok=True, evidence=receipt, max_attempts=max_attempts)
            row.pop('pending_review', None)
            return status, None
        result = end(approve, changed=len(changed), receipt_sha256=receipt, cross_review=True)
        prev_diff_file.unlink(missing_ok=True)
        return result
    except (StaleLease, LockBusy):
        raise                       # the lease is gone / the lock is busy: write nothing (the caller reports it)
    except ChannelFault as error:
        return fault(error)
    except BudgetExhausted:
        report['pending_review'] = has_pending()
        return release('budget_exhausted', seconds_to_local_midnight())
    except channels.ChannelUnavailable as error:
        report['pending_review'] = has_pending()
        return _wait(release, report, 'channel_wait', error.wait_s, status='WAITING_CHANNEL',
                     channel_reason=error.reason)
    except NoIndependentReviewer:
        report['pending_review'] = has_pending()
        return _wait(release_or_block, report, 'no_independent_reviewer', status='WAITING_CHANNEL')
    except PromptTooLarge as error:
        return block('context_too_large', 'prompt of %s characters exceeds %d' %
                     (error, channels.PROMPT_LIMIT_CHARS))
    except Exception as error_obj:  # noqa: BLE001 - fail closed, never retry an uncertain worker
        text = scrub(redact(str(error_obj)))[:300]
        # prepare()/packet(): context over budget; a source over SOURCE_MAX_BYTES is the same resource limit (live 20.11:
        # it read 'scope_violation', the question asked "which files?" and the factory never retried the 6 rows)
        if isinstance(error_obj, InputTooLarge) or (isinstance(error_obj, InvalidPlan) and 'budget' in text):
            return block('context_too_large', text)
        if isinstance(error_obj, OSError):   # antivirus, a locked file, a full disk: the machine, not the task
            report['error_type'] = type(error_obj).__name__
            note = scrub(redact(str(error_obj)))[:200]
            report['reason_detail'] = note
            kind = 'os_error'   # whitelisted in agent_factory.DEFER_REASONS (seam test guards it)
            if defer_streak(ck.read(), tid, kind) + 1 >= ESCALATE_AFTER:
                # the same OS error on every pass is this task's problem (path clash, long path): block it,
                # and do not count it toward the brake of the whole factory
                return block('worker_exception', note, infra=False)
            return release(kind, 60, infra=True)
        reason = "scope_violation" if isinstance(error_obj, InvalidPlan) else "worker_exception"
        report['error_type'] = type(error_obj).__name__
        return block(reason, text)
    finally:
        if base_holder:
            shutil.rmtree(base_holder, ignore_errors=True)
        if baseline_dir is not None and baseline_dir.name.endswith('-baseline') and ctx['workdir'] != baseline_dir:
            shutil.rmtree(baseline_dir, ignore_errors=True)


def _wait(release, report: dict, reason: str, seconds: float = 60, *, status: str | None = None,
          channel_reason: str | None = None) -> dict:
    """Candidate kept (pending_review), no strike: the pass ends waiting for a channel/reviewer."""
    result = release(reason, max(1.0, seconds or 60))
    if status and result.get('status') != 'BLOCKED':
        result['status'] = status
    if channel_reason:
        result['channel_reason'] = channel_reason
        if channel_reason in INFRA_CHANNEL_REASONS:
            result['infra'] = True  # a dead key / no key / no channels must trip the loop brake
    return result


def main(argv=None):
    p = argparse.ArgumentParser(description="Fail-closed experimental Kilo task runner")
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--plan", type=Path, required=True)
    p.add_argument("--checkpoint", type=Path, required=True)
    p.add_argument("--staging", type=Path, required=True)
    p.add_argument("--small-model", required=True)
    p.add_argument("--large-model", required=True)
    p.add_argument("--execute", action="store_true")
    p.add_argument('--channels', type=Path, help='verified provider IDs, key environment names and actual quotas')
    p.add_argument('--review-model', help='independent reviewer (another model than the coder); defaults to large-model')
    p.add_argument('--base-sha', help='SHA of the integration branch the base was taken from (telemetry only)')
    p.add_argument("--ack-host-access-risk", action="store_true")
    p.add_argument("--max-tasks", type=int, default=1,
                   help="execute at most N sequential tasks; no implicit daemon")
    p.add_argument("--max-attempts", type=int, default=MAX_ATTEMPTS,
                   help="a task becomes FAILED after N failed attempts (each next one on another model where possible)")
    p.add_argument("--max-model-calls", type=int,
                   help="explicit model-call budget written into this checkpoint")
    p.add_argument("--small-follow-up", choices=("on", "off"), default="on",
                   help="may a small-tier model be a later tournament candidate (an A/B arm)")
    p.add_argument("--task", help="run this task (the one the loop claimed); default: the first ready one")
    p.add_argument("--lease", help="the lease token of --task, claimed by the caller (without it the pass claims its own)")
    p.add_argument("--port-repo", type=Path,
                   help="git repository that holds the old-branch commits of port tasks (--root is a copy without .git)")
    args = p.parse_args(argv)
    if not 1 <= args.max_tasks <= 10:
        p.error("--max-tasks must be in 1..10")
    if not 1 <= args.max_attempts <= MAX_ATTEMPTS:
        p.error("--max-attempts must be in 1..%d" % MAX_ATTEMPTS)
    if args.max_model_calls is not None and not 1 <= args.max_model_calls <= MAX_MODEL_CALLS:
        p.error("--max-model-calls must be in 1..%d" % MAX_MODEL_CALLS)
    if args.execute and args.staging.resolve().is_relative_to(args.root.resolve()):
        p.error("staging must not be within original repository")
    if args.lease and not args.task:
        p.error("--lease needs --task")
    outcomes = []
    for _ in range(args.max_tasks if args.execute else 1):
        options = {}
        if args.execute:
            options.update(review_model=args.review_model or args.large_model,
                           channel_config=args.channels, base_sha=args.base_sha,
                           small_follow_up=args.small_follow_up == "on", port_repo=args.port_repo)
        result = once(root=args.root, plan=args.plan, checkpoint=args.checkpoint,
                      staging=args.staging, small_model=args.small_model,
                      large_model=args.large_model, execute=args.execute,
                      acknowledge=args.ack_host_access_risk,
                      max_attempts=args.max_attempts,
                      max_model_calls=args.max_model_calls, task_id=args.task, lease=args.lease, **options)
        outcomes.append(result)
        if result["status"] not in ("REVIEW", "READY"):
            break
    for result in outcomes:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if all(x["status"] in ("DRY_RUN", "REVIEW", "IDLE")
                    for x in outcomes) else 2


if __name__ == "__main__":
    from . import factory_cloud_gate
    factory_cloud_gate.enable_product()     # only the worker process the loop starts may send a candidate tree to the cloud gate
    sys.exit(main())
