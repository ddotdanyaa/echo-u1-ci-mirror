"""Small, auditable task queue for optional Kilo workers; no model/network I/O.

This package intentionally does NOT deploy, merge, read Google keys, or pretend
that a worktree isolates files from the operating system. State transitions are
fenced with lease tokens and always require independent acceptance.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path, PurePosixPath
import json
import os
import re
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET

STATES = frozenset(("READY", "RUNNING", "REVIEW", "DONE", "FAILED", "BLOCKED"))
DENY_PARTS = frozenset((".env", ".git", ".kilo", ".ssh", "secrets", "private",
                        "transcripts", "credentials", "tokens", "recordings",
                        "__pycache__", "node_modules", "materials"))
SECRET = re.compile(
    r"(?:AIza[A-Za-z0-9_-]{20,}|sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|"
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----|"
    r"(?i:password|api[_-]?key|client_secret)\s*[:=]\s*(?:['\x22][^\x22']{8,}['\x22]|[A-Za-z0-9_.-]{8,})(?:\s|$))"
)
TASK_ID = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{0,63}$")
MODEL_ID = re.compile(r"^[a-zA-Z0-9._-]+/[a-zA-Z0-9._:-]+$")


class InvalidPlan(ValueError):
    pass


def safe_path(value: str) -> str:
    """Fail closed on traversal, hidden/system secrets, odd Windows filenames."""
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        raise InvalidPlan("unsafe path")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or value != path.as_posix():
        raise InvalidPlan("noncanonical path")
    if any(part in ("", ".", "..") or part.startswith(".") or part.lower() in DENY_PARTS
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

    @property
    def scope(self) -> frozenset[str]:
        return frozenset(self.touch_files)


def read_plan(plan: object) -> dict[str, Task]:
    """Tasks require explicit scope, dependencies and privacy classification.

    Missing privacy_safe is private, never sent to free third-party models.
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
            if len(val) != len(set(val)):
                raise InvalidPlan("duplicated " + k)
            fields[k] = tuple(val)
        files = {k: tuple(safe_path(p) for p in fields[k])
                 for k in ("touch_files", "read_files", "tests")}
        if not files["touch_files"]:
            raise InvalidPlan("task has no writing scope")
        if any(not p.startswith("tests/") or not p.endswith(".py") for p in files["tests"]):
            raise InvalidPlan("pytest scope must be named tests/*.py")
        if "privacy_safe" in row and type(row["privacy_safe"]) is not bool:
            raise InvalidPlan("privacy_safe is boolean")
        size = row.get("estimated_tokens", 0)
        if type(size) is not int or not 0 <= size <= 10_000_000:
            raise InvalidPlan("token estimate invalid")
        result[tid] = Task(tid, title.strip(), fields["depends_on"],
                           files["touch_files"], files["read_files"], files["tests"],
                           row.get("privacy_safe", False), size)
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


def initial_state(tasks: dict[str, Task]) -> dict:
    return {
        "schema": 1,
        "deploy_blocked": True,  # never equivalent to stopping development
        "max_model_calls": 10,
        "model_calls": 0,
        "tasks": {tid: {"status": "READY", "attempts": 0, "lease": None,
                        "deadline": None, "evidence": None} for tid in tasks},
    }


def validate_state(tasks: dict[str, Task], state: dict) -> None:
    if not isinstance(state, dict) or state.get("schema") != 1:
        raise InvalidPlan("unknown checkpoint schema")
    if set(state.get("tasks", {})) != set(tasks):
        raise InvalidPlan("task/checkpoint mismatch")
    for row in state["tasks"].values():
        if row.get("status") not in STATES or type(row.get("attempts")) is not int:
            raise InvalidPlan("invalid state")
    if type(state.get("max_model_calls")) is not int or type(state.get("model_calls")) is not int:
        raise InvalidPlan("invalid budget")
    if state["max_model_calls"] < 0 or state["model_calls"] < 0:
        raise InvalidPlan("negative budget")


def ready(tasks: dict[str, Task], state: dict, *, google: bool = True,
          occupied: tuple[str, ...] = ()) -> list[str]:
    """Sorted tasks ready to execute, excluding all concurrent writers."""
    validate_state(tasks, state)
    read_in_use = set()
    write_in_use = set(occupied)
    for tid, row in state["tasks"].items():
        if row["status"] == "RUNNING":
            write_in_use.update(tasks[tid].touch_files)
            read_in_use.update(tasks[tid].read_files)
            read_in_use.update(tasks[tid].tests)
    found = []
    for tid in sorted(tasks):
        task = tasks[tid]
        if state["tasks"][tid]["status"] != "READY":
            continue
        if google and not task.privacy_safe:
            continue
        reads = set(task.read_files) | set(task.tests)
        writes = set(task.touch_files)
        if (writes & (write_in_use | read_in_use)) or (reads & write_in_use):
            continue
        if all(state["tasks"][dep]["status"] == "DONE" for dep in task.depends_on):
            found.append(tid)
            write_in_use.update(writes)
            read_in_use.update(reads)
    return found


def acquire(tasks: dict[str, Task], state: dict, tid: str, *,
            now: float | None = None, lifetime: float = 1800.0) -> str:
    """Single-writer checkpoint must be locked by caller before mutation."""
    now = time.time() if now is None else float(now)
    if tid not in ready(tasks, state):
        raise InvalidPlan("not runnable")
    if state["model_calls"] >= state["max_model_calls"]:
        raise InvalidPlan("budget exhausted")
    token = uuid.uuid4().hex
    row = state["tasks"][tid]
    row.update(status="RUNNING", attempts=row["attempts"] + 1,
               lease=token, deadline=now + lifetime)
    state["model_calls"] += 1
    return token


def settle(state: dict, tid: str, token: str, *,
           tests_ok: bool, evidence: str, max_attempts: int = 2) -> str:
    """Fenced completion. Green requires manual review, never auto-DONE."""
    row = state["tasks"][tid]
    if row["status"] != "RUNNING" or row["lease"] != token:
        raise InvalidPlan("stale/foreign lease")
    if not isinstance(evidence, str) or not re.fullmatch(r"[0-9a-f]{64}", evidence):
        raise InvalidPlan("expected SHA256 digest of local test receipt")
    next_status = ("REVIEW" if tests_ok else
                   ("READY" if row["attempts"] < max_attempts else "FAILED"))
    row.update(status=next_status, lease=None, deadline=None, evidence=evidence)
    return next_status


def accept(state: dict, tid: str, *, reviewer: str) -> None:
    """Human or separately configured trusted reviewer must acknowledge."""
    row = state["tasks"][tid]
    if row["status"] != "REVIEW" or not reviewer.strip():
        raise InvalidPlan("not reviewed")
    row["status"] = "DONE"
    row["reviewer"] = reviewer[:80]


def pause_expired(state: dict, now: float) -> list[str]:
    """No dangerous auto-retry of possibly-live subprocesses after a crash."""
    suspect = []
    for tid, row in state["tasks"].items():
        if row["status"] == "RUNNING" and row.get("deadline") is not None and row["deadline"] <= now:
            row["status"] = "BLOCKED"
            suspect.append(tid)
    return suspect


def route(task: Task, *, small_model: str, large_model: str,
          threshold: int = 8000, fallback: bool = False) -> str:
    """Model IDs are supplied by actual Kilo local model list, not fabricated."""
    if not task.privacy_safe:
        raise InvalidPlan("cannot send a private task to a Google model")
    if not all(MODEL_ID.fullmatch(m) for m in (small_model, large_model)):
        raise InvalidPlan("model IDs must match provider/model")
    return large_model if fallback or task.estimated_tokens > threshold else small_model


def backoff(attempt: int, *, base: float = 2.0, cap: float = 20.0) -> float:
    if type(attempt) is not int or attempt < 0:
        raise ValueError("retry index")
    return min(cap, base * 2 ** min(attempt, 16))


def safe_source(path: Path, *, max_size: int = 200_000) -> bytes:
    """Reject symlinks, non-UTF8, suspicious secrets and oversized inputs."""
    if path.is_symlink() or not path.is_file() or path.stat().st_size > max_size:
        raise InvalidPlan("input requires trusted local review")
    data = path.read_bytes()
    if b"\x00" in data:
        raise InvalidPlan("binary input")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as e:
        raise InvalidPlan("not UTF-8") from e
    if SECRET.search(text):
        raise InvalidPlan("potential secret; private review required")
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
    """Write then replace, so interruption never yields a half checkpoint."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8",
                                     dir=path.parent, prefix=".agent-state-",
                                     delete=False) as f:
        tmp = Path(f.name)
        json.dump(state, f, ensure_ascii=False, sort_keys=True, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def load_state(path: Path, tasks: dict[str, Task]) -> dict:
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else initial_state(tasks)
    validate_state(tasks, data)
    return data
