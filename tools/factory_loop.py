"""The single continuous factory loop (pack D, DAY19_FACTORY_BUILD_PLAN K-D).

One iteration: refresh base -> release_expired -> next_action -> PROMOTE | RUN | WAIT | TRIAGE |
HOLD | DONE. Exits only on STOP (code 0), the deadline (0), the emergency brake (3: five
infrastructure failures in a row, file BRAKE, separate from the manual STOP) or when another
instance is alive (4). Every iteration writes one `span=loop` event: no silent sleeping.

Run:  python -m tools.factory_loop [--state-dir DIR] [--until "YYYY-MM-DD HH:MM"] [--once]
State dir (default C:\\agent-factory\\echo on Windows, outside the user profile: Kilo
puts its working directory into the model prompt, so the path must not carry the user name): plan.json, state.json (runner
checkpoint), telemetry.jsonl, stats.json, opus_questions.md, loop_state.json, STOP, BRAKE, loop.pid.
Provider keys must be in the environment (or --env-file; only key_env names of the channels are
read, values are never printed).
"""
from __future__ import annotations

import argparse
import ast
import datetime as dt
import collections
import contextlib
import ctypes
import copy
import errno
import hashlib
import inspect
import json
import os
import posixpath
import random
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import uuid
from types import SimpleNamespace
from dataclasses import dataclass
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools import agent_factory as F  # noqa: <id>
from tools import factory_review_wait as RW  # noqa: <id>
from tools import factory_channels as CH  # noqa: <id>
try:                                   # the public mirror (factory_mirror.MODULES) does not carry the cloud gate: there is no cloud route
    from tools import factory_cloud_gate  # noqa: <id>
except ImportError:
    factory_cloud_gate = None
from tools import factory_closures, factory_metrics  # noqa: <id>  (<id> hourly report, <id> closures writer)
from tools import factory_process  # noqa: <id>
from tools import factory_survive as SV  # noqa: <id>
from tools import factory_quota as quota_ledger  # noqa: <id>

RUNNER_TIMEOUT_S = int(F.LEASE_LIFETIME_S)  # one runner pass = one lease; not a switch
LOOP_HEAD_WAIT_S = 30       # W-bucket: an ask in the loop's own thread waits in the head at most this (then its call time)
from tools.factory_gate import MIN_FREE_RAM  # noqa: <id>  (one floor for the loop and the gates)
EST_DEFAULT_BYTES = 300 * 2 ** 20     # a worker's memory before the pool has measured five (job peaks: 36 + 87 MB)
EST_KEEP, EST_MIN_SAMPLES = 20, 5
WS_MIN_SAMPLES = 3                    # fac-58: working-set samples a worker needs before its ws peak (not the job peak) enters the estimate
EST_MEDIAN_DEFAULT = 100 * 2 ** 20    # a live worker's usual size when none is measured (live ones measured 51-88 MB)
BURST_SHARE = 0.15                    # the pool's one shared burst reserve = max(est_peak, this x live x est_peak)
YOUNG_S = 30                          # a worker younger than this still grows to its median: the gap is not free
# A worker of the light engine is one HTTP call with the files in the prompt (peak 40-120 MB); only a Kilo worker
# needs the gate's 2 GB floor. The floor admits light workers on a 3 GB machine; the estimate still limits how many.
LIGHT_FLOOR = 768 * 2 ** 20
# While the cloud answers the candidate checks run there (no local slot, no RAM budget): the pool counts no RAM per worker
# and takes up to factory_cloud_gate.MAX_LIVE tasks; only this emergency floor of the whole machine stays.
CLOUD_FLOOR = 1536 * 2 ** 20          # free memory below this stops admission whatever the cloud says; above it the measured estimate rules
CLOUD_TRIAL_S = 60                    # a cloud that does not answer is asked again by ONE trial card per this long (_capacity)
FAST_LOCAL_SHARE = 0.20               # more of the gate time than this spent on local runs: new workers send every test to the cloud
FAST_LOCAL_HOLD_S = 3600
WAIT_PULSE_S = 60.0                   # a wait for live workers writes a short event at least this often (the watcher's quiet limit is 300 s)
WAIT_BG_S = 0.03                     # the same look while a background triage / hold pick runs: a ready task is admitted within ~0.03 s of its card (the runner's own boot is on top of it)
WAIT_CHUNK_S = 3.0                  # real seconds between two looks at the pool while workers run
STALE_INDEX_LOCK_S = 120
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
# Channel-wide reasons stop every task; everything else is the task's own not_before.
from tools.agent_factory_runner import ESCALATE_AFTER, INFRA_CHANNEL_REASONS, INFRA_DEFERS, LIGHT_MAX_FILES  # noqa: <id>
from tools.agent_factory_runner import engine_for as _engine_for  # noqa: <id>
from tools.agent_factory_runner import _light_post  # noqa: <id>  (the <id> spec pass; tests replace this name)
from tools import factory_router as RT  # noqa: <id>


def _http_get(url: str, headers: dict, timeout: float = 30):
    """(status, JSON or None) of one GET (<id> model listings); the key travels in the headers only."""
    import urllib.error
    import urllib.request
    req = urllib.request.Request(url, headers={**headers, "User-Agent": "factory"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as e:
        return e.code, None
    except (urllib.error.URLError, OSError, ValueError):
        return None, None


def _probe(row: dict, key: str):
    """HTTP status of one tiny call of the row's model with the key (<id>: only a row that answers is written)."""
    from tools.agent_factory_runner import LIGHT_ENDPOINTS
    provider, _, model_id = row["model"].partition("/")
    body = {"model": model_id, "temperature": 0, "max_tokens": 5,
            "messages": [{"role": "user", "content": "Say OK"}]}
    from tools import factory_channels as C
    status, _, _sent = C.post_with_extra(_light_post, LIGHT_ENDPOINTS[provider], key, body, 60, row["model"])
    return status


def _env_values(text: str, names) -> dict:
    """Values of the given names in an env file text (the same parsing as load_keys); never logged."""
    found = {}
    for line in (text or "").splitlines():
        line = line.strip()
        if line.startswith("export "):
            line = line[7:].strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() in names:
            found[key.strip()] = value.strip().strip('"').strip("'")
    return found

DEAD_CHANNEL = INFRA_DEFERS | INFRA_CHANNEL_REASONS   # real infrastructure faults: the runner's sets
CHANNEL_REASONS = DEAD_CHANNEL | frozenset(("rate_minute", "rate_day", "region", "budget_exhausted",
                                            "channel_wait"))
# Temporary faults: they postpone only their own channel (channel_until) or their own task (not_before) with
# an exponential, jittered pause. They never grow the brake series. A permanent break (a dead channel, a dead
# runner, "infra" without such a reason) still does.
TEMPORARY_CHANNEL = frozenset(("rate_limited_suspect", "rate_limited", "429", "channel_timeout"))
TEMPORARY_TASK = frozenset(("transient", "env_shortage"))
BACKOFF_FIRST_S, BACKOFF_MAX_S = 60, 1800
JUDGED_OUTCOMES = frozenset(("off_path", "no_changes", "no_effect", "cannot_repeat", "scope_violation",
                             "review_chain_short", "context_too_large"))   # a weak candidate or task, not a dead pipeline
GLOBAL_WAIT_MAX_S = 300   # owner: a dead route gets 5 min, then the fallback. A wait no channel owns holds the
                          # whole loop, so it never exceeds this (live 21.11 12:22: an unnamed 'dead' held 12 tasks 1 h)
BRAKE_SPAN_S, BRAKE_MAX_S = 60, 60             # one minute, then one trial; a failed trial waits one minute again
GIT_WAIT_FIRST_S, GIT_WAIT_MAX_S = 30, 300
TIER_ORDER = ("small", "main", "escalation")
ERROR_MEMORY_MAX = 200
BEFORE_MODEL = frozenset(("already_green", "context_too_large", "scope_violation", "no_diff"))
SCOPE_MAX_FILES = LIGHT_MAX_FILES   # a task widened beyond it would leave the light engine
CLEANUP_EVENTS = ("stale_baseline_kept", "pending_copy_kept")
TELEMETRY_MAX_BYTES = 20 * 1024 * 1024
REJECT_PREFIXES = ("gate:", "weakening:", "review:")  # a real rejection, not a deferral
EXIT_OK, EXIT_BRAKE, EXIT_RUNNING, EXIT_LOCK_ERROR = 0, 3, 4, 5
LOCALAPPDATA = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
# Windows: a neutral directory on the system drive, never under C:\Users\<name>; elsewhere as before.
DEFAULT_STATE_DIR = (Path(os.environ.get("SystemDrive", "C:") + "\\") / "agent-factory" / "echo"
                     if os.name == "nt" else LOCALAPPDATA / "agent-factory" / "echo")
WORK = Path(r"<project-root>")


# ---- OS helpers -------------------------------------------------------------------------

pid_alive = F.pid_alive    # moved to agent_factory: the checkpoint lock reads its holder with it


def boot_time() -> float:
    """Best-effort boot epoch; process identity remains the primary lock check."""
    try:
        if os.name == "nt":
            ticks = ctypes.windll.kernel32.GetTickCount64
            ticks.restype = ctypes.c_ulonglong
            return time.time() - ticks() / 1000
        for line in Path("/proc/stat").read_text(encoding="ascii").splitlines():
            if line.startswith("btime "):
                return float(line.split()[1])
    except Exception:
        pass
    return 0.0


def proc_info(pid: int) -> tuple[str, float] | None:
    """Command line and creation epoch, or None when the process cannot be verified."""
    try:
        import psutil
    except ImportError:
        psutil = None
    if psutil is not None:
        try:
            proc = psutil.Process(pid)
            return " ".join(proc.cmdline()), proc.create_time()
        except psutil.Error:
            return None
    if os.name == "nt":
        try:
            script = ("Get-CimInstance Win32_Process -Filter 'ProcessId=%d' | "
                      "ForEach-Object { [pscustomobject]@{cmd=$_.CommandLine;"
                      "created=[DateTimeOffset]::new($_.CreationDate).ToUnixTimeMilliseconds()/1000} } | "
                      "ConvertTo-Json -Compress") % int(pid)
            out = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True,
                                 text=True, encoding="utf-8", errors="replace", timeout=10, check=True)
            info = json.loads(out.stdout or "null")
            if info:
                return str(info.get("cmd") or ""), float(info["created"])
        except (OSError, subprocess.SubprocessError, ValueError, TypeError, KeyError):
            pass
    return None


def set_execution_state(flags: int) -> None:
    """Keep the system awake while the loop works (process API; no system settings change)."""
    if os.name != "nt":
        return
    import ctypes
    ctypes.windll.kernel32.SetThreadExecutionState(ctypes.c_uint(flags))


def free_ram_bytes() -> int:
    if os.name != "nt":
        return 2 ** 62
    import ctypes

    class Mem(ctypes.Structure):
        _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong),
                    ("total_phys", ctypes.c_ulonglong), ("avail_phys", ctypes.c_ulonglong),
                    ("total_page", ctypes.c_ulonglong), ("avail_page", ctypes.c_ulonglong),
                    ("total_virt", ctypes.c_ulonglong), ("avail_virt", ctypes.c_ulonglong),
                    ("avail_ext", ctypes.c_ulonglong)]

    mem = Mem()
    mem.length = ctypes.sizeof(Mem)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(mem)):
        return 2 ** 62  # unknown: do not block the loop
    return int(mem.avail_phys)


def git_running() -> bool:
    """Is any git process alive? (tasklist cannot show cwd, so any live git is 'busy')."""
    try:
        if os.name == "nt":
            out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq git.exe", "/NH"],
                                 capture_output=True, text=True, errors="replace",
                                 timeout=20).stdout
            return "git.exe" in out.lower()
        return subprocess.run(["pgrep", "-x", "git"], capture_output=True).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return True  # unknown: assume busy, do not delete the lock


# ---- git --------------------------------------------------------------------------------

LOCK_NOTES: list[str] = []  # drained into telemetry by the loop


def _units(text: str):
    """W-flow 3: the top-level statements of a Python text as [(key, first_line, end_line, source)] (0-based, end
    exclusive; decorators and the lines up to the statement belong to it). None when it does not parse or a key repeats."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return None
    lines = text.splitlines()
    out, seen = [], set()
    for i, node in enumerate(tree.body):
        start = min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])]) - 1
        end = node.end_lineno
        src = "\n".join(lines[start:end])
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            key = "def:" + node.name
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            key = "import:" + src.strip()
        elif isinstance(node, ast.Assign) and all(isinstance(t, ast.Name) for t in node.targets):
            key = "assign:" + ",".join(t.id for t in node.targets)
        elif i == 0 and isinstance(node, ast.Expr) and isinstance(getattr(node, "value", None), ast.Constant):
            key = "doc"
        else:
            key = "other:" + src
        if key in seen:
            return None
        seen.add(key)
        out.append((key, start, end, src))
    return out


def merge_units(base: str, ours: str, theirs: str) -> str | None:
    """W-flow 3: when git's line merge conflicts, merge Python files by top-level statement: what the candidate added,
    changed or removed (a function, a class, an import, a constant) lands on ``ours`` when ``ours`` did not touch the same
    statement. None when the changes meet (the same statement changed on both sides, an odd statement) or a text does
    not parse. The newline of ``ours`` is kept."""
    nl = "\r\n" if "\r\n" in ours else "\n"
    b, o, t = (_units(x.replace("\r\n", "\n")) for x in (base, ours, theirs))
    if b is None or o is None or t is None:
        return None
    bs, os_, ts = ({u[0]: u[3] for u in x} for x in (b, o, t))
    changed_t = {k for k in set(bs) | set(ts) if bs.get(k) != ts.get(k)}
    changed_o = {k for k in set(bs) | set(os_) if bs.get(k) != os_.get(k)}
    for k in changed_t & changed_o:
        if os_.get(k) != ts.get(k):
            return None                      # both changed the same statement, differently
    if any(k.startswith("other:") for k in changed_t):
        return None                          # a loose statement moved: not a unit we can place
    lines = ours.replace("\r\n", "\n").split("\n")
    edits = []                               # (start, end, replacement lines) applied from the bottom
    pos = {u[0]: u for u in o}
    adds, imports = [], []
    for k in sorted(changed_t - (changed_t & changed_o) | {k for k in changed_t & changed_o if k not in os_}):
        if k in pos and k in ts:
            edits.append((pos[k][1], pos[k][2], ts[k].split("\n")))
        elif k in pos:
            edits.append((pos[k][1], pos[k][2], None))      # removed by the candidate
        elif k in ts:
            (imports if k.startswith("import:") else adds).append(ts[k])
    top = max([u[2] for u in o if u[0].startswith("import:")] + [u[2] for u in o if u[0] == "doc"] + [0])
    if imports:
        edits.append((top, top, imports))
    for start, end, new in sorted(edits, key=lambda e: (e[0], e[1]), reverse=True):
        lines[start:end] = [] if new is None else new
    text = "\n".join(lines).rstrip("\n")
    for block in adds:
        text += "\n\n\n" + block
    text += "\n"
    try:
        ast.parse(text)
    except (SyntaxError, ValueError):
        return None
    return text.replace("\n", nl)


def three_way_merge(base: str, ours: str, theirs: str, name: str = "") -> tuple[str, bool]:
    """git merge-file on three texts: (merged text, conflict). ``ours`` is the branch now, ``theirs`` the candidate.
    ``name``: the file's path; for a Python file a conflict of lines is retried statement by statement (merge_units)."""
    if ours == base or ours == theirs:
        return theirs, False
    if theirs == base:
        return ours, False
    merged, bad = _git_merge(base, ours, theirs)
    if bad and name.endswith(".py"):
        by_unit = merge_units(base, ours, theirs)
        if by_unit is not None:
            return by_unit, False
    return merged, bad


def _git_merge(base: str, ours: str, theirs: str) -> tuple[str, bool]:
    with tempfile.TemporaryDirectory() as d:
        paths = []
        for name, text in (("ours", ours), ("base", base), ("theirs", theirs)):
            q = Path(d) / name
            q.write_bytes(text.encode("utf-8"))
            paths.append(str(q))
        proc = subprocess.run(["git", "merge-file", "-p", *paths], capture_output=True)
    if proc.returncode < 0 or proc.returncode > 127:
        raise RuntimeError("git merge-file failed")
    return proc.stdout.decode("utf-8", errors="replace"), proc.returncode > 0


def code_sha(root: Path) -> str:
    """The SHA of the factory's own code under ``root`` (the folder that holds tools/). Never empty: the folder name when
    it looks like 12-40 hex (the machine runs from a code export ``.../code/<sha12>/`` without .git), else git HEAD,
    else the sha1 of tools/*.py (live 23.11: the export had no .git, the SHA was '' and no card was returned)."""
    root = Path(root).resolve()
    if re.fullmatch(r"[0-9a-fA-F]{12,40}", root.name):
        return root.name.lower()
    try:
        got = git_run(root, "rev-parse", "HEAD").strip()
        if re.fullmatch(r"[0-9a-f]{40}", got):
            return got
    except Exception:  # noqa: BLE001 - no git or no repository: the content decides
        pass
    h = hashlib.sha1()
    for p in sorted((root / "tools").glob("*.py")):
        try:
            h.update(p.name.encode("utf-8") + b"\0" + p.read_bytes() + b"\0")
        except OSError:
            continue
    return h.hexdigest()


def git_run(cwd: Path, *args: str, retry_lock: bool = True) -> str:
    cmd = ["git", "-c", "core.quotepath=off", "-C", str(cwd), *args]
    for attempt in (0, 1):
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                              errors="replace")
        if proc.returncode == 0:
            return proc.stdout
        if attempt == 0 and retry_lock and "index.lock" in proc.stderr and _drop_stale_lock(cwd):
            continue
        raise subprocess.CalledProcessError(proc.returncode, cmd, proc.stdout,
                                            F.redact(proc.stderr[-400:]))
    raise AssertionError("unreachable")


def _drop_stale_lock(cwd: Path) -> bool:
    """Remove a stuck index.lock older than 120 s when no git process is alive."""
    try:
        rel = subprocess.run(["git", "-C", str(cwd), "rev-parse", "--git-path", "index.lock"],
                             capture_output=True, text=True, check=True).stdout.strip()
        lock = Path(rel) if Path(rel).is_absolute() else Path(cwd) / rel
        if not lock.exists() or time.time() - lock.stat().st_mtime < STALE_INDEX_LOCK_S:
            return False
        if git_running():
            return False
        lock.unlink()
        return True
    except (OSError, subprocess.SubprocessError) as e:
        LOCK_NOTES.append("lock_check_failed: " + F.redact(str(e))[:200])
        return False


def _is_fixture_deco(d) -> bool:
    """pytest.fixture or pytest.fixture(scope=<str literal>): no positional args; only `scope`, its value a literal
    (name=, params=, autouse=, ids= and any computed value are refused: they run at import or rename a fixture)."""
    if isinstance(d, ast.Call):
        if d.args or any(k.arg != "scope" or not (isinstance(k.value, ast.Constant) and isinstance(k.value.value, str))
                         for k in d.keywords):
            return False
        d = d.func
    return isinstance(d, ast.Attribute) and d.attr == "fixture" and isinstance(d.value, ast.Name) and d.value.id == "pytest"


_BUILTIN_FIXTURES = frozenset((
    "tmp_path", "tmp_path_factory", "tmpdir", "tmpdir_factory", "monkeypatch", "capsys", "capfd", "capsysbinary", "capfdbinary",
    "caplog", "request", "pytestconfig", "recwarn", "cache", "doctest_namespace", "record_property", "record_xml_attribute",
    "record_testsuite_property", "testdir", "pytester", "env", "event_loop", "anyio_backend", "mocker"))


def _safe_annotation(a) -> bool:
    return a is None or all(isinstance(n, (ast.Name, ast.Attribute, ast.Constant, ast.Load, ast.Subscript, ast.Tuple, ast.BinOp, ast.BitOr))
                            for n in ast.walk(a))


def _fixture_def_faults(node, reserved) -> bool:
    """True when the def is unsafe at import: non-literal defaults/annotations, or a reserved (builtin/project) fixture name."""
    if node.name in _BUILTIN_FIXTURES or node.name in reserved:
        return True
    args = node.args
    defaults = list(args.defaults) + [x for x in args.kw_defaults if x is not None]
    for dflt in defaults:
        try:
            ast.literal_eval(dflt)
        except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
            return True
    every = args.posonlyargs + args.args + args.kwonlyargs + [x for x in (args.vararg, args.kwarg) if x is not None]
    return not all(_safe_annotation(a.annotation) for a in every) or not _safe_annotation(node.returns)


def _conftest_faults(name: str, text: str, reserved=frozenset(), old: str = "") -> list[str]:
    """W-pack: tests/conftest.py by AST allow-list: imports, constants (literals), docstring, and `def` fixtures decorated with
    pytest.fixture without autouse. No hooks, no pytest_* names, no module-level code, no session/items access."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError):
        return [name + ": conftest does not parse"]
    try:  # a top-level node that stood there before is not the package's: only what it adds or changes is judged
        stood = ast.parse(old).body
        before = {ast.dump(n) for n in stood}
    except (SyntaxError, ValueError, RecursionError):
        stood, before = [], set()
    bad = name + ": conftest allows only imports, constants and pytest.fixture functions (no hooks, plugins, autouse)"
    fresh = [n for n in tree.body if ast.dump(n) not in before]
    reserved = frozenset(reserved) | {n.name for n in stood if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
    if before - {ast.dump(n) for n in tree.body}:
        return [name + ": conftest drops or changes what stood there"]
    for node in fresh:
        if isinstance(node, ast.Import):
            if any(a.name.split(".")[-1].startswith("pytest_") or (a.asname or "").startswith("pytest_") for a in node.names):
                return [bad]
        elif isinstance(node, ast.ImportFrom):
            if any(a.name == "*" or a.name.startswith("pytest_") or (a.asname or "").startswith("pytest_") for a in node.names) \
                    or (node.module or "").split(".")[-1].startswith("pytest_"):
                return [bad]
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            pass
        elif isinstance(node, ast.Assign) and all(isinstance(t, ast.Name) and not t.id.startswith("pytest_") for t in node.targets):
            try:
                ast.literal_eval(node.value)
            except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
                return [bad]
        elif isinstance(node, ast.FunctionDef):
            if node.name.startswith("pytest_") or not node.decorator_list or not all(_is_fixture_deco(d) for d in node.decorator_list) \
                    or _fixture_def_faults(node, reserved):
                return [bad]
        else:
            return [bad]
    for node in (x for top in fresh for x in ast.walk(top)):
        if (isinstance(node, ast.Attribute) and node.attr in ("items", "session", "hookimpl", "hookspec")) \
                or (isinstance(node, ast.Name) and node.id in ("items", "session", "pytest_plugins")):
            return [name + ": conftest touches session/items/hooks"]
    return []


def _project_fixture_names(wt: Path) -> frozenset:
    """Names of fixtures defined in other conftest files of the project (tests/conftest.py itself may be updated)."""
    names = set()
    for p in Path(wt).rglob("conftest.py"):
        try:
            if p.relative_to(wt).as_posix().casefold() == "tests/conftest.py" or ".git" in p.parts:
                continue
            for n in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    names.add(n.name)
        except (OSError, ValueError, SyntaxError, RecursionError):
            continue
    return frozenset(names)


def package_digest(files: dict) -> str:
    """W-pack: sha1 over the sorted (path, bytes) of a root package."""
    h = hashlib.sha1()
    for name in sorted(files):
        h.update(name.encode("utf-8") + b"\0" + files[name] + b"\0")
    return h.hexdigest()


def refresh_mirror(repo: Path, ref: str, mirror: Path) -> str:
    """Read-only mirror of the branch HEAD via git archive. The swap is atomic-ish: unpack into
    <mirror>.new, then old -> .old, new -> mirror; a kill mid-unpack never breaks the mirror."""
    head = git_run(repo, "rev-parse", ref).strip()
    marker = mirror / ".factory_mirror"
    if marker.exists() and marker.read_text(encoding="utf-8").strip() == head:
        return head
    if mirror.exists() and not marker.exists():
        raise RuntimeError("mirror dir is not ours: " + str(mirror))
    new, old = (mirror.with_name(mirror.name + s) for s in (".new", ".old"))
    shutil.rmtree(new, ignore_errors=True)
    shutil.rmtree(old, ignore_errors=True)
    new.mkdir(parents=True)
    archive = mirror.with_name(mirror.name + ".tar")
    try:
        with archive.open("wb") as fh:
            subprocess.run(["git", "-C", str(repo), "archive", ref], stdout=fh,
                           stderr=subprocess.PIPE, check=True)
        with tarfile.open(archive) as tar:
            tar.extractall(new, filter="data")
    finally:
        archive.unlink(missing_ok=True)
    (new / ".factory_mirror").write_text(head, encoding="utf-8")
    if mirror.exists():
        os.replace(mirror, old)
    os.replace(new, mirror)
    shutil.rmtree(old, ignore_errors=True)
    return head


# ---- config / telemetry -----------------------------------------------------------------

def retry_fs(fn, *args, tries: int = 5, delay: float = 0.1, sleep=None):
    """Run ``fn(*args)``; a Windows sharing violation (antivirus, indexer: winerror 5 or 32, EBUSY) is retried
    ``tries`` times in all with a pause growing from ``delay`` to 2 s.  Any other error is raised at once."""
    pause = delay
    for n in range(tries):
        try:
            return fn(*args)
        except OSError as e:
            busy = getattr(e, "winerror", None) in (5, 32) or e.errno == errno.EBUSY
            if not busy or n == tries - 1:
                raise
            (sleep or time.sleep)(pause)
            pause = min(2.0, pause * 4)


@dataclass
class Config:
    state_dir: Path
    architect_rungs: tuple = ()
    hard_first_rung: int = 1
    repo: Path = WORK / "CLOUD_REPO"
    branch: str = "factory/night-20261119"
    worktree: Path = WORK / "W7" / "stage" / "factory_night_wt"
    backlog: Path = WORK / "BACKLOG_ECHO.md"
    channels: Path = WORK / "W7" / "factory" / "channels.json"
    until: dt.datetime | None = None
    once: bool = False
    clear_brake: bool = False
    small_model: str = "google/gemini-3.5-flash-lite"   # verified pair, loop.log 19.11
    large_model: str = "google/gemini-3.5-flash-lite"
    review_model: str = "google/gemini-3.1-flash-lite"
    env_file: Path | None = None
    max_attempts: int = F.MAX_ATTEMPTS   # 21.11: one owner (6); the runner refuses more than F.MAX_ATTEMPTS
    max_model_calls: int = 0        # 0: the day's capacity of the channel registry (Loop._call_budget)
    max_infra: int = 5
    triage_limit: int = 12
    hold_sleep: int = 60            # 21.11 (was 300)
    done_sleep: int = 300           # 21.11 (was 900)
    chunk: int = 60
    triage_retry_s: int = 600       # 21.11 (was 1800)
    triage_idle_sleep: int = 120
    metrics_since: str = ""         # <id>: cohort start (ISO time) of the hourly metrics span; empty = everything
    metrics_every_s: int = 3600     # <id>: one metrics span per hour
    sweep_every_s: int = 6 * 3600   # the red-guard supply: a cloud sweep at least this often (and when the base SHA moved)
    seen_retry_s: int = 3600        # 21.11 (was 21600) <id>: a skipped/stale backlog row is triaged again after this term, edit or not
    requeue_term_s: int = 900       # 21.11 (was 3600) <id>: a FAILED task of a retryable class is given back this long after its last try
    ready_target: int = 15          # <id> (owner): the slicer keeps this many tasks READY (0: off)
    ready_triage_s: int = 60        # <id>: READY below the target: the next top-up triage after this term (doubles while a portion is empty, up to triage_retry_s)
    not_code_term_s: int = 7 * 86400   # <id>: a row the head model called not code is looked at again after this term
    self_repo: bool = False         # 8.1: the second instance: the repository is the factory's own code (fac-* rows only)
    exit_when_idle: bool = False    # 1.6: the canary's loop ends when nothing is left to do
    sync_ref: str = "factory/ready-4534085"   # the second instance merges this branch into its own (cfg.branch) three-way: at the start, then hourly with no RUNNING
    sync_every_s: int = 3600


class _Later(Exception):
    """A temporary obstacle: the answer file stays in answers/ for the next iteration."""


@dataclass
class Outcome:
    code: int | None = None
    sleep: float = 0
    action: str = ""
    reason: str = ""
    status: str = "ok"
    blockers: dict | None = None
    proof: bool = False   # evidence that the pipeline works: the only thing that resets the series


def load_keys(env_file: Path, channels: Path, missing: list | None = None) -> dict:
    """Only the channels' key_env names; returned for the runner subprocess, never set in
    os.environ. A channel without a key is skipped (names go to `missing`); no key at all: refuse."""
    names = {c["key_env"] for c in json.loads(channels.read_text(encoding="utf-8"))["channels"]}
    found = {}
    for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line.startswith("export "):
            line = line[7:].strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() in names:
            found[key.strip()] = value.strip().strip('"').strip("'")
    result = {k: found[k] for k in names if found.get(k) and not os.environ.get(k)}
    absent = sorted(k for k in names if not os.environ.get(k) and k not in result)
    if len(absent) == len(names):
        raise SystemExit("no channel key available (names only): " + ", ".join(absent))
    if missing is not None:
        missing.extend(absent)
    return result


@dataclass
class Worker:
    """One runner process the loop started for one claimed task."""
    slot: int
    tid: str
    token: str | None
    base_sha: str
    root: Path | None = None
    owned: object = None
    out: Path | None = None
    err: Path | None = None
    fhs: tuple = ()
    t_claim: float = 0.0          # time.monotonic() at the claim
    t_start: float = 0.0          # time.monotonic() at the start of the process
    k: int = 1                    # live workers when it started (itself included)
    free_ram: int = 0
    hint: str = ""
    peak: int | None = None
    ws_peak: int = 0              # fac-58: the largest working set seen while it lived (the job peak is commit, not RAM)
    ws_n: int = 0                 # fac-58: how many working-set samples stand behind ws_peak
    res: dict | None = None       # the reaped result waiting for its accounting (the state lock was busy)


class Pool:
    """The live workers by slot. ``wait_any`` blocks until one exits or ``timeout`` real seconds pass; tests inject
    ``wait_fn(workers, timeout)``."""

    def __init__(self, wait_fn=None):
        self.workers: dict[int, Worker] = {}
        self.wait_fn = wait_fn

    def free_slot(self) -> int:
        n = 0
        while n in self.workers:
            n += 1
        return n

    def start(self, w: Worker) -> Worker:
        self.workers[w.slot] = w
        return w

    def remove(self, w: Worker) -> None:
        self.workers.pop(w.slot, None)

    def tids(self) -> set:
        return {w.tid for w in self.workers.values()}

    def roots(self) -> set:
        return {w.root for w in self.workers.values() if w.root is not None}

    def finished(self) -> list:
        return [w for w in self.workers.values() if w.owned is None or w.owned.poll() is not None]

    def wait_any(self, timeout: float) -> list:
        live = [w for w in self.workers.values() if w.owned is not None]
        if not live:
            return self.finished()
        done = self.finished()
        if done:
            return done
        if self.wait_fn is not None:
            self.wait_fn(live, timeout)
        elif os.name == "nt":
            try:
                import _winapi
                handles = [int(w.owned.proc._handle) for w in live[:60]]
                _winapi.WaitForMultipleObjects(handles, False, int(max(0.0, timeout) * 1000))
            except Exception:
                time.sleep(min(timeout, 0.1))
        else:
            end = time.monotonic() + timeout
            while time.monotonic() < end and not self.finished():
                time.sleep(0.05)
        return self.finished()


class Prefetch:
    """One background job of the loop: a triage portion or the head's hold picks. The thread does only network and
    file reads on private copies; the loop's own thread applies the result (the plan, the state and the loop state
    are written there only), so a slow free-model call never holds back the admission of a ready task."""

    def __init__(self, kind: str, work, ctx):
        self.kind, self.ctx, self._work = kind, ctx, work
        self.result = self.error = None
        self.done = threading.Event()
        self.t0 = time.monotonic()
        self.dur_s = 0.0
        self.cancel = threading.Event()     # fac-choke: set when the loop drops the job; the work reads it as threading.current_thread().cancel
        self.thread = threading.Thread(target=self._run, name="factory-" + kind, daemon=True)
        self.thread.cancel = self.cancel

    def _run(self) -> None:
        try:
            self.result = self._work()
        except BaseException as e:          # handed to the loop thread, which raises or books it as before
            self.error = e
        finally:
            self.dur_s = time.monotonic() - self.t0
            self.done.set()


MEM_RESERVE_DIR = DEFAULT_STATE_DIR.parent / "mem_reserve"     # next to the state dir; bookings of memory by the builders' runs and the runs waiting for it (0.5)


def _reserved_bytes() -> int:
    """Memory that is spoken for outside the pool: the architect's live agents (``EST_AGENT_BYTES`` x ``agent_live()``, 2.6:
    zero until that module is merged) and the bookings of the build (one file per booking holding the number of bytes)."""
    total = 0
    try:
        from tools import factory_architect as A
        total += int(A.EST_AGENT_BYTES) * int(A.agent_live())
    except (ImportError, AttributeError, TypeError, ValueError):
        pass
    try:
        for item in MEM_RESERVE_DIR.iterdir() if MEM_RESERVE_DIR.is_dir() else ():
            try:
                text = item.read_text(encoding="utf-8").strip()
                if text.startswith("{"):
                    text = str(json.loads(text).get("bytes", 0))
                total += max(0, int(text))
            except (OSError, ValueError, TypeError, AttributeError):
                continue
    except OSError:
        pass
    return total


FAULT_CLASSES = ("prompt oversize", "need rounds exhausted", "file not found", "symbol", "forbidden need", "not available", "oversize")


def fault_class(text: str) -> str:
    """The class of an architect fault: a known phrase, an http code, or the first word."""
    low = str(text).strip().lower()
    for known in FAULT_CLASSES:
        if low.startswith(known) or known in low:
            return known
    m = re.search(r"\b(?:http\s*)?([45]\d\d)\b", low)
    if m:
        return "http " + m.group(1)
    return (low.split() or ["unknown"])[0].rstrip(":;,")[:40]


def _cloud_up(fn) -> bool:
    """True when the cloud-gate probe ``fn`` says the cloud answers; no probe or any fault of it: the local rules."""
    try:
        return bool(fn and fn())
    except Exception:           # noqa: BLE001  a probe that breaks is "no cloud", never a stopped pool
        return False


LINKS_EVERY_S = 600     # 4.2 (<id>): the owner's journal is linked to backlog rows at most this often, and only when it grew
SLICE_PARALLEL = 12
AWAIT_STEP_S = 20                     # W-await: workers are waited for this long, then a full step (slicing, merges, answers) runs beside them
GUARD_REQUEUE_MAX = 3      # W-guard fix1: cards of one guard row sent back to the slicer as already_green, at most so often
RESLICE_STEP_S = 5.0
RESLICE_PER_STEP = SLICE_PARALLEL      # W-feed 4: up to SLICE_PARALLEL rows go to the slicer in one step
# fac-53 (plan 22.11: «впрок не режется, когда в READY уже вдвое больше потолка пула»; «карточки всегда первые»): no new slicing or
# solving starts while the cards ready() can start now are at least SLICE_AHEAD_X x max(live pool, SLICE_AHEAD_MIN). An order, not a
# ceiling: with fewer ready cards the slicer goes at full width; only a fresh regression (rank 0) always goes; a guarded row waits by its rank.
SLICE_AHEAD_X, SLICE_AHEAD_MIN = 2, 4
CARDS_FIRST_MEMO_S = 5.0
CARDS_FIRST_STALE_S = 60.0       # an older count says nothing: the loop's calls keep their own priority in the head
LOOP_YIELD_PRIORITY = 3          # the head's last level: the loop's calls go after every card ticket of equal age
RESLICE_SLEEP_S = 5
SLICE_WAIT_S = 60
SLICE_PAUSES = (60, 120, 300, 600)        # W-pay 2: the pause of a row's repeated wait grows
SLICE_STARVED_S = 600                    # W-prio2 2: no slice started or ended this long while a fresh row waits -> infra slicer_starved
SLICE_STALE_S = 3600                      # W-prio2 3: a slicer older than this is dropped (its result is ignored)
SLICE_WAIT_CALL_S = 120.0                # W-path A: the longest wait of one slicing call for a channel
SLICE_WAIT_JOB_S = 400.0                 # W-path A: the sum of the waits of one slicing job (under SLICE_STALE_S)
SLICE_HOPS = 4                           # W-path A: channels of one step tried at once after 429/500/503, then a wait
SLICE_HOPELESS_S = 600                   # W-gemma2 4: a row without a step (no money, no main channel) waits at least this
QUARANTINE_TTL_S = 21600
DRY_SLICE_MAX = 8           # W-dry 1: rows of cards without code that go to the slicer for code at the same time
STATE_LOCKED_SLEEP_S = 3    # W-gemma5 3: a busy state lock lives milliseconds: WAIT state_locked sleeps this long
DRY_CACHE_S = 5            # the edit_dry reading is kept this long
DAY_LEFT_FOR_CARDS = 0.35   # fac-63 (was W-dry 3 KW_DAY_LEFT_MIN 0.2): the loop's own calls (links / keywords, architect, slice) take a main-tier channel only while this share of its day is left; the rest is the cards' (edit + code + repair + review need ~600 of ~1700 requests a day)
CARD_BUDGET_ROLES = ("architect", "slice")    # fac-63: the loop's roles held to DAY_LEFT_FOR_CARDS on the main tier (thrifty does the same for every non-small tier)
HARD_FAILED_GENS = 6        # W-hard 1: generations that reached a red fix: from here the row sits until CONTRACT_REV changes
HARD_REOPEN_S = 86400       # ... and opens by a new CONTRACT_REV no more than once a day
RED_EDITS_BAR = 2           # W-hard 1: a rung whose contract gave this many red fixes is not called for the row again
A_NO_FIX = ("cannot_reproduce", "already_fixed", "hold")    # with duplicate_of:<ID>: the architect's no-fix holds (kept by text, 7 days)


class SliceWait(Exception):
    """No slicer channel is currently available; retry without spending a rung."""


POOL_DRY_S = 900          # headroom 0 with READY work this long: the watchdog probes the cooled channels (23.11)
PROBE_TIMEOUT_S = 30


def _probe_channel(channel, key):
    """One tiny real call to ``channel`` (the watchdog's probe), classified like any call: the classify() info, or
    None when the provider has no light endpoint. The key travels only in the header (agent_factory_runner._light_post)."""
    from tools import agent_factory_runner as R
    provider, _, name = str(channel["model"]).partition("/")
    url = R.LIGHT_ENDPOINTS.get(provider)
    if not url or not name:
        return None
    status, raw, _sent = CH.post_with_extra(R._light_post, url, key, {"model": name, "max_tokens": 8,
                                            "messages": [{"role": "user", "content": "ping"}]}, PROBE_TIMEOUT_S,
                                            channel["model"])
    if status == 200:
        return {"kind": "ok", "status": 200}
    name_ = "NetworkError" if status is None else "APIError"
    return CH.classify(R._light_error(status, raw, name_), b"", 1)


class Loop:
    TXN_WAIT_S = 10.0       # a transaction on the state waits at most this long for the lock (a commit lasts ms)
    CLAIM_WAIT_S = 2.0      # the claim waits less: a held lock is WAIT state_locked, not a stalled loop
    CLAIM_RETRIES = 5       # W-feed2 4g: a LockBusy of the claim is retried this many times (CLAIM_PAUSE_S apart), then the next card
    CLAIM_PAUSE_S = 0.3
    TICK_MIN_S = 300.0       # W-feed2 4c: the ticks whose data change rarely run at most once in this time

    def __init__(self, cfg: Config, *, triage_fn=None, runner_cmd=None, clock=time.time,
                 sleep=time.sleep, power_fn=set_execution_state, free_ram_fn=free_ram_bytes,
                 extra_env=None, startup_notes=None, rng=None, wait_fn=None, cloud_fn=None, reap_fn=None, sweep_fn=None, release_fn=None,
                 slice_fn=None, architect_fn=None, probe_fn=None, bisect_fn=None):
        if cfg.review_model in (cfg.small_model, cfg.large_model):
            raise ValueError("review model must differ from the code model: " + cfg.review_model)
        self.cfg = cfg
        self.rng = rng or random.Random()
        self.extra_env = dict(extra_env or {})
        self.startup_notes = list(startup_notes or [])
        self.triage_fn = triage_fn
        from tools import factory_architect as A
        self.architect_fn = architect_fn or A.contract_for
        self.slice_fn = slice_fn if slice_fn is not None else (self._slice if cfg.architect_rungs else None)
        self._slicers: dict[str, Prefetch] = {}
        self._hypers: dict[str, Prefetch] = {}      # W-feed2 2: rows whose hypotheses search is under way (the loop thread owns this)
        self._hypo_dropped: list[Prefetch] = []     # fac-choke: stale solves told to stop whose thread still runs (their snapshot stays)
        self._hypo_skip: dict[str, tuple] = {}      # row -> (base sha, time): nothing to search for it now
        self._ask_lock = threading.Lock()
        self._arch_quotas = None       # restored once, then owned in memory under _ask_lock
        self._head = self._head_close = None     # fac-40: the one host of the small-tier calls (started in run)
        self.sweep_fn = sweep_fn        # None: no cloud sweep (tests); main passes tools.echo_cloud.sweep
        self._sw = None                 # the cloud sweep job in flight (Prefetch) or None
        self._sw_refresh_at = 0.0
        self._lk = None                 # the owner-links job in flight (Prefetch) or None (4.2)
        self._lk_at, self._lk_size, self._lk_unlinked = 0.0, -1, None
        self._kw_quotas = {}            # the keywords' own quota ledger (a fresh {} per call overwrote the section: one request counted)
        self._lk_quotas = {}          # the links job's own quota ledger, one for the life of the loop (only that job's thread uses it)
        self.release_fn = release_fn    # None: no final build (tests); main passes the cloud one (tools.factory_release)
        self._rel = None                # the final build in flight (Prefetch, its own slot) or None
        self._rel_snap = None           # the snapshot the final build reads: _prune_snapshots keeps it
        self._rel_lock = threading.Lock()
        self._rel_note = None           # the info of the cloud run the build just made (its thread sets it, the loop's thread stores it)
        self.bisect_fn = bisect_fn      # None: no history search (tests); main passes the cloud one (tools.factory_bisect.step)
        self._bis = None                # the history search job in flight (Prefetch, its own slot, one at a time) or None
        self.runner_cmd = list(runner_cmd or [sys.executable, "-B", "-m",
                                              "tools.agent_factory_runner"])
        self.clock, self.sleep_fn = clock, sleep
        self.power_fn, self.free_ram_fn = power_fn, free_ram_fn
        self.cloud_fn = cloud_fn      # () -> bool: does the cloud gate answer now (main gives factory_cloud_gate.available)
        self.probe_fn = probe_fn if probe_fn is not None else _probe_channel   # (channel, key) -> classify() info | None
        self._dry_since, self._probed_at = None, 0.0   # the pool watchdog: headroom 0 with READY work since / last probe
        d = Path(cfg.state_dir)
        self.dir = d
        self.plan_path, self.ckpt = d / "plan.json", d / "state.json"
        self.tel_path, self.stats_path = d / "telemetry.jsonl", d / "stats.json"
        self.questions, self.ls_path = d / "opus_questions.md", d / "loop_state.json"
        self.stop, self.brake, self.pidfile = d / "STOP", d / "BRAKE", d / "loop.pid"
        self.stage, self.mirror = d / "stage", d / "src_mirror"
        self.snap_dir, self.workers_dir = d / "src_snapshots", d / "workers"
        self.pool = Pool(wait_fn)
        self._peaks: list = []          # job peaks (bytes) of the last EST_KEEP workers: the admission estimate
        self._brake_due = None          # a brake the drain of the live workers may still cancel
        self._infra_mono = 0.0          # when the last infrastructure result was accounted (one incident counts once)
        self._txn_open = False
        self._max_k, self._k_sum, self._k_n = 0, 0, 0
        self.run_id = uuid.uuid4().hex[:12]
        self.base_sha = ""
        self._mem_infra = 0
        self._rotating = self._rotate_failed = False
        self._rotate_note = None
        self._known_names: set = set()
        self._wt_lock = None
        self._lock_error = False
        self._key_names = None
        self._key_names_logged = False
        self._since_mem: dict = {}
        self._tries_mem: dict = {}
        self.iterations = 0
        self._bg = None            # the one background job in flight (Prefetch) or None
        self._bg_cancel = threading.Event()
        self._tel_lock = threading.RLock()
        self.reap_fn = reap_fn          # None: no reaping (tests); main passes the real one
        self._idle = SV.IdleWatch()
        self._reap_at = -1e18

    DISCOVER_EVERY_S = 86400

    def _discover_keys(self) -> None:
        """<id> (owner: a new key is one line in the secrets, the registry is not edited by hand): once a day at START
        the free models of every key of the env file are listed by its provider, probed once, and only the verified
        rows are written to the channel registry (tools/factory_discover.py); a new key reaches the runner at once.
        A fault never stops the loop."""
        from tools import factory_channels as C
        from tools import factory_discover as D
        try:
            ls = self.ls()
            if self.clock() - float(ls.get("discovered_at") or 0) < self.DISCOVER_EVERY_S:
                return
            text = (Path(self.cfg.env_file).read_text(encoding="utf-8", errors="replace")
                    if self.cfg.env_file else "")
            names = D.key_names(text)
            values = _env_values(text, set(names))
            keys = {n: os.environ.get(n) or self.extra_env.get(n) or values.get(n) for n in names}
            keys = {n: v for n, v in keys.items() if v}
            path = Path(self.cfg.channels)
            registry = json.loads(path.read_text(encoding="utf-8"))
            report = D.discover(registry, keys, get=_http_get, probe=_probe)
            if report["added"]:
                C.validate(registry["channels"])
                tmp = path.with_name(path.name + ".discover.tmp")
                tmp.write_text(json.dumps(registry, ensure_ascii=False, indent=1), encoding="utf-8")
                retry_fs(os.replace, tmp, path)
                for row in registry["channels"]:
                    if row["id"] in report["added"] and not os.environ.get(row["key_env"]):
                        self.extra_env.setdefault(row["key_env"], keys[row["key_env"]])
                self._key_names = None          # the scrubber reads the key names of the registry again
            ls["discovered_at"] = self.clock()
            self.save_ls(ls)
            self.event("discover", status="ok", reason="added %d, probe failed %d, listing errors %d" % (
                len(report["added"]), len(report["failed"]), len(report["errors"])),
                added=report["added"][:20] or None, errors=report["errors"] or None)
        except Exception as e:
            self.err("discover", e)

    def _build_router_table(self) -> None:
        """fac-43 step 0: the router's score table (router_table.json beside the telemetry) is built again from the
        telemetry: at START and after every release that accepted cards. A fault never stops the loop."""
        try:
            RT.build(self.dir)
        except Exception as e:  # noqa: BLE001 - the router keeps the table it has
            self.err("router table", e)

    def err(self, where: str, e: BaseException) -> None:
        """A swallowed error is still an event (never a silent pass)."""
        try:
            self.event("infra", status="error", reason="%s: %s: %s" % (
                where, type(e).__name__, F.redact(str(e))[:200]))
        except OSError:
            pass

    def rs(self, value, limit: int = 200):
        return F.redact(value)[:limit] if isinstance(value, str) else value

    # -- telemetry
    def ts(self) -> str:
        return dt.datetime.fromtimestamp(self.clock()).astimezone().isoformat(timespec="seconds")

    def _secret_values(self) -> list:
        """Env-file values plus the values already in os.environ under the channels' key_env."""
        values = list(self.extra_env.values())
        names = self._key_names
        if names is None:
            try:
                data = json.loads(Path(self.cfg.channels).read_text(encoding="utf-8"))
                names = self._key_names = [c["key_env"] for c in data.get("channels", [])
                                           if c.get("key_env")]
            except (OSError, ValueError, KeyError, TypeError) as e:
                names = []   # NOT cached: read again next time; say so once
                if not self._key_names_logged:
                    self._key_names_logged = True
                    self.err("channels.json unreadable, env keys unknown", e)
        values += [os.environ.get(n, "") for n in names]
        return [v for v in values if isinstance(v, str) and len(v) >= 6]

    def _scrub(self, text: str) -> str:
        """Every secret value out of any text we write to disk (raw and JSON-escaped forms)."""
        for secret in self._secret_values():
            for form in {secret, json.dumps(secret)[1:-1]}:
                text = text.replace(form, "[REDACTED]")
        return text

    def _rotate_telemetry(self) -> None:
        """telemetry.jsonl -> .1 -> .2 when over the limit; a failure is reported once."""
        if self._rotating:
            return
        self._rotating = True
        try:
            if self.tel_path.exists() and self.tel_path.stat().st_size > TELEMETRY_MAX_BYTES:
                one = self.tel_path.with_name(self.tel_path.name + ".1")
                two = self.tel_path.with_name(self.tel_path.name + ".2")
                if one.exists():
                    retry_fs(os.replace, one, two)
                retry_fs(os.replace, self.tel_path, one)
        except OSError as e:
            if not self._rotate_failed:
                self._rotate_failed = True
                self._rotate_note = "%s: %s" % (type(e).__name__, F.redact(str(e))[:150])
        finally:
            self._rotating = False

    def event(self, span: str, **fields) -> None:
        row = {"ts": self.ts(), "run_id": self.run_id, "span": span}
        row.update({k: v for k, v in fields.items() if v is not None})
        line = self._scrub(json.dumps(row, ensure_ascii=False))
        with self._tel_lock:                # the background job may report an error while the loop writes
            self._rotate_telemetry()
            with self.tel_path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
            if self._rotate_note:
                note, self._rotate_note = self._rotate_note, None
                self.event("infra", status="rotate_failed", reason=note)

    # -- loop_state.json
    def ls(self) -> dict:
        data = {}
        try:
            data = json.loads(self.ls_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as e:
            self.err("loop_state.json unreadable, starting empty", e)
        if not isinstance(data, dict):
            self.event("infra", status="error", reason="loop_state.json is not an object, starting empty")
            data = {}
        for k, v in (("bases", {}), ("holds", {}), ("totals", {}), ("seen", {}), ("closed", {}), ("hold_hash", {})):
            data.setdefault(k, v)
        return data

    def save_ls(self, ls: dict) -> None:
        F.save_atomic(self.ls_path, ls)

    # -- instance lock
    def acquire(self, boot=None) -> bool:
        boot = boot_time() if boot is None else boot
        self._boot_time = boot
        self.dir.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                fd = os.open(self.pidfile, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except OSError as e:
                if not isinstance(e, FileExistsError):
                    self._pid_trouble(e)
                    return False
                try:
                    written = self.pidfile.stat().st_mtime
                    other = int(self.pidfile.read_text(encoding="utf-8").strip())
                except ValueError:
                    other = 0                                 # an empty or torn file: stale
                except OSError as e2:
                    self._pid_trouble(e2)                    # unreadable (antivirus): not "already running"
                    return False
                if other and written >= boot - 5 and pid_alive(other):
                    info = proc_info(other)
                    if info and "tools.factory_loop" in info[0] and 0 < info[1] <= written + 5:
                        self.event("infra", status="refused", reason="already_running", pid=other)
                        return False
                self.event("infra", status="cleared", reason="stale_pid", pid=other)
                if other:
                    self.event("loop", action="RECOVER", status="ok", reason="crash_recovery", pid=other)
                try:
                    self.pidfile.unlink()
                except OSError as e2:
                    self._pid_trouble(e2)
                    return False
                continue
            try:
                with os.fdopen(fd, "w") as fh:
                    fh.write(str(os.getpid()))
            except OSError as e:
                self._pid_trouble(e)
                try:
                    self.pidfile.unlink(missing_ok=True)
                except OSError as e3:
                    self.err("loop.pid cleanup", e3)
                return False
            if not self._lock_worktree():
                try:
                    self.pidfile.unlink(missing_ok=True)
                except OSError as e3:
                    self.err("loop.pid cleanup", e3)
                return False
            self._warn_old_state_dir()
            return True
        return False

    def _pid_trouble(self, e: OSError) -> None:
        """loop.pid cannot be opened or removed (antivirus, read-only disk): not 'already running'."""
        self._lock_error = True
        self.event("infra", status="lock_error", reason="cannot use loop.pid: %s: %s"
                   % (type(e).__name__, F.redact(str(e))[:150]))

    def _worktree_lock_dir(self) -> Path | None:
        last = None
        for _ in range(3):                          # one try and two retries
            try:
                out = subprocess.run(["git", "-C", str(self.cfg.worktree), "rev-parse",
                                      "--absolute-git-dir"], capture_output=True, text=True,
                                     encoding="utf-8", errors="replace", check=True,
                                     timeout=30).stdout.strip()
                return Path(out) / "factory_loop.lockdir"
            except (OSError, subprocess.SubprocessError) as e:
                last = e
        self.event("infra", status="warning", reason="lock_disabled: git rev-parse failed 3 times: %s"
                   % F.redact(str(last))[:150])
        return None

    def _make_lock(self, lock: Path) -> bool:
        """Atomic: the owner file is written in a private directory which is then renamed."""
        tmp = lock.with_name("%s.%d.tmp" % (lock.name, os.getpid()))
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir()
        (tmp / "owner").write_text("%d|%s" % (os.getpid(), self.dir), encoding="utf-8")
        try:
            os.rename(tmp, lock)
        except OSError:
            shutil.rmtree(tmp, ignore_errors=True)
            return False
        self._wt_lock = lock
        return True

    @staticmethod
    def _owner_alive(pid: int, where: str) -> bool:
        """A pid is the owner only if it is alive AND its state dir's loop.pid says so (a reused
        pid of an unrelated process must not hold the worktree for ever)."""
        if pid < 0:
            return True                              # a lock being created right now
        if not pid_alive(pid):
            return False
        try:
            return int((Path(where) / "loop.pid").read_text(encoding="utf-8").strip()) == pid
        except (OSError, ValueError):
            return pid == os.getpid()               # cannot verify: only ourselves are certainly alive

    def _lock_worktree(self) -> bool:
        """Two loops (different --state-dir) must never commit into the same worktree.
        True only when the lock is really ours."""
        lock = self._worktree_lock_dir()
        if lock is None:
            return True  # cannot tell (a warning event was written): do not block the loop
        for attempt in range(3):
            try:
                if self._make_lock(lock):
                    return True
            except OSError as e:
                self._lock_error = True
                self.event("infra", status="lock_error", reason="cannot create the worktree lock: %s: %s"
                           % (type(e).__name__, F.redact(str(e))[:150]))
                return False
            try:
                pid_s, _, where = (lock / "owner").read_text(encoding="utf-8").partition("|")
                pid = int(pid_s)
            except (OSError, ValueError):
                pid, where = 0, ""
                try:  # no readable owner: a lock still being created is alive, an old one is dead
                    if time.time() - lock.stat().st_mtime < 10:
                        pid, where = -1, "?"
                except OSError:
                    pass
            if pid and where != str(self.dir) and self._owner_alive(pid, where):
                self.event("infra", status="refused", reason="worktree %s is held by pid %d "
                           "(state dir %s)" % (self.cfg.worktree, pid, self._scrub(where)))
                return False
            # stale: move it aside under a unique name first, re-read the owner, only then delete
            aside = lock.with_name("%s.stale.%d.%d" % (lock.name, os.getpid(), attempt))
            try:
                os.rename(lock, aside)
            except OSError:
                continue                             # somebody else just replaced/removed it: look again
            try:
                _, _, where2 = (aside / "owner").read_text(encoding="utf-8").partition("|")
                pid2 = int(_)
            except (OSError, ValueError):
                pid2, where2 = 0, ""
            if pid2 and pid2 != pid and where2 != str(self.dir) and self._owner_alive(pid2, where2):
                try:
                    os.rename(aside, lock)           # a live owner took it meanwhile: give it back
                except OSError:
                    pass
                self.event("infra", status="refused", reason="worktree lock was re-taken by pid %d" % pid2)
                return False
            shutil.rmtree(aside, ignore_errors=True)
        self.event("infra", status="refused", reason="could not take the worktree lock")
        return False

    def _warn_old_state_dir(self) -> None:
        old = LOCALAPPDATA / "agent-factory" / "echo"
        try:
            if old != self.dir:
                left = [n for n in ("loop.pid", "plan.json", "state.json") if (old / n).exists()]
                if left:
                    self.event("infra", status="warning", reason="the old state dir %s still has "
                               "%s: stop that loop / move the plan" % (old.name, ", ".join(left)))
        except OSError:
            pass

    def release(self) -> None:
        lock = getattr(self, "_wt_lock", None)
        if lock is not None:
            try:
                if (lock / "owner").read_text(encoding="utf-8").startswith("%d|" % os.getpid()):
                    shutil.rmtree(lock, ignore_errors=True)
            except OSError:
                pass
            self._wt_lock = None
        try:
            if self.pidfile.read_text(encoding="utf-8").strip() == str(os.getpid()):
                self.pidfile.unlink()
        except FileNotFoundError:
            pass
        except OSError as e:
            self.err("release pid", e)

    def _reap_real(self, **kw) -> list:
        return SV.reap(procs_fn=SV.list_processes, kill_fn=SV.kill_tree, **kw)

    def _survive_tick(self) -> None:
        """<id>: once per REAP_EVERY_S the orphan reaper (factory-owned children only), the telemetry tail is kept
        by _rotate_telemetry, and the idle watchdog: READY>0 and RUNNING=0 for 10 min -> one event and the stale
        global / task waits are healed. An aid: it never raises into the loop."""
        try:
            now = self.clock()
            if self.reap_fn is not None and now - self._reap_at >= SV.REAP_EVERY_S:
                self._reap_at = now
                markers = [str(self.stage), str(self.dir / "workers"), str(self.cfg.worktree)]
                live = [w.owned.pid for w in self.pool.workers.values() if getattr(w, "owned", None) is not None]
                killed = self.reap_fn(now=now, markers=markers, live_pids=live, self_pid=os.getpid())
                if killed:
                    self.event("infra", status="reaped", reason="orphan_children", pids=list(killed)[:20])
            if self.pool.workers:
                self._idle.observe(ready=0, running=1, now=now)
                return
            _tasks, state = self.load()
            rows = state["tasks"].values()
            ready = sum(1 for r in rows if r.get("status") == "READY")
            running = sum(1 for r in rows if r.get("status") == "RUNNING")
            if not self._idle.observe(ready=ready, running=running, now=now):
                return
            ls = self.ls()

            def fix(st):
                return SV.heal(st, ls, now=now)
            got = self._tx(fix)
            self.save_ls(ls)
            self.event("infra", status="healed", reason="idle_selfheal", ready=ready,
                       global_wait=got["global_wait"], tasks=len(got["tasks"]), task_ids=got["tasks"][:10])
        except Exception as e:
            self.err("survive tick", e)

    def release_orphan_leases(self) -> None:
        """At START no runner of this state can be alive (one loop instance by loop.pid; its runners die with
        their job object), so every RUNNING lease is an orphan of a killed pass: back to READY now, not after
        LEASE_LIFETIME_S (restart check 19.11 17:54: two kills left three tasks RUNNING for 30 minutes). A restart
        is not the task's doing: no expiry is counted and the attempt comes back (orphan=True), so restarts of
        the coordinator never block or fail a healthy task; a pass that hangs still expires by time."""
        for _ in range(30):         # a holder killed by a forced restart: its lock is stale in a moment (live 25.11 14:11: 15 cards stayed RUNNING)
            if not self.ckpt.with_suffix(self.ckpt.suffix + ".lockdir").exists():
                break
            self._sleep(2.0)
        if self.ckpt.with_suffix(self.ckpt.suffix + ".lockdir").exists():
            # the lock survived clear_stale_lockdir: a live holder is working, its lease is no orphan
            self.event("infra", status="skipped", reason="orphan_leases: state locked")
            return
        try:
            with self.txn() as (_, state):
                expired = F.release_expired(state, time.time())      # past their deadline already: ordinary expiries
                freed = F.release_expired(state, float("inf"), orphan=True)
            if expired or freed:
                self.event("infra", status="released", reason="orphan_leases", tasks=len(freed),
                           expired=len(expired))
        except Exception as e:                       # an aid: the loop starts anyway, leases expire by time
            self.err("orphan leases", e)

    def clear_stale_lockdir(self) -> None:
        """The runner's state lock is stale when its holder (the pid in <lock>/owner) is dead, or, for an
        anonymous lock, when it is older than LOCK_STALE_S. Called at start AND before every runner pass: the loop
        is the only parent of runners (one instance by loop.pid) and runs them one at a time, so a lock found
        there is never its own live runner. Restart check 19.11 17:42: a loop killed mid-pass left a seconds-old
        anonymous lock, the age rule ran only at start, and the new loop's runner refused every pass."""
        lock = self.ckpt.with_suffix(self.ckpt.suffix + ".lockdir")
        try:
            if not lock.exists():
                return
            owner = lock / F.LOCK_OWNER
            try:
                text = owner.read_text(encoding="ascii").strip()
            except OSError:
                text = ""                   # absent or unreadable this instant: the age rule decides
            try:
                pid = int(text) if text else None   # anonymous: an older runner, or between mkdir and the write
            except ValueError:
                pid = 0                     # garbage is no live holder
            written = lock.stat().st_mtime
            age = time.time() - written
            preboot = written < getattr(self, "_boot_time", 0.0) - 5
            alive = pid is not None and pid != os.getpid() and pid_alive(pid)
            if pid is None:
                stale = age > F.LOCK_STALE_S
            else:
                # a pid is reused (a reboot, hours later); no pass outlives RUNNER_TIMEOUT_S (the loop kills it);
                # the loop itself is never the holder (critic 19.11 18:39)
                stale = not alive or age > RUNNER_TIMEOUT_S + F.LOCK_STALE_S
            if stale or preboot:
                owner.unlink(missing_ok=True)
                lock.rmdir()
                self.event("infra", status="cleared", reason="stale_lockdir",
                           holder="anonymous" if pid is None else ("old" if alive else "dead"))
        except OSError as e:
            self.event("infra", status="error", reason="lockdir: " + F.redact(str(e))[:200])

    # -- state
    # The state changes ONLY here: a transaction (the lock, the plan and the state read FRESH, validated and saved on a
    # normal exit; an exception writes nothing). Readers take a locked snapshot. The runners write through the same lock.
    def _ensure_plan(self) -> None:
        if not self.plan_path.exists():
            F.save_atomic(self.plan_path, {"tasks": []})

    def load(self):
        """A private copy of (tasks, state), read fresh under the lock; to change the state use ``txn``."""
        if self._txn_open:
            raise RuntimeError("load() inside a transaction: use the one the block already holds")
        self._ensure_plan()
        try:
            return F.snapshot(self.ckpt, self.plan_path, self.TXN_WAIT_S)
        finally:
            self._lock_journal()

    @contextlib.contextmanager
    def txn(self, wait_s: float | None = None):
        """One short transaction on the checkpoint. Not re-entrant: a nested one would wait for its own lock."""
        if self._txn_open:
            raise RuntimeError("nested state transaction")
        self._ensure_plan()
        self._txn_open = True
        try:
            with F.txn(self.ckpt, self.plan_path, wait_s if wait_s is not None else self.TXN_WAIT_S) as pair:
                yield pair
        finally:
            self._txn_open = False
            self._lock_journal()

    def _lock_journal(self) -> None:
        """A stale state lock the transaction itself cleared is still an event (the same as clear_stale_lockdir's)."""
        mine = str(self.ckpt.with_suffix(self.ckpt.suffix + ".lockdir"))
        keep = []
        for ev in F.LOCK_EVENTS:
            if ev.get("event") == "stale_lock_removed" and ev.get("lock") == mine:
                self.event("infra", status="cleared", reason="stale_lockdir", holder=ev.get("holder", "old"))
            elif ev.get("event") == "lock_held" and ev.get("lock") in (mine, str(self.plan_path.with_suffix(self.plan_path.suffix + ".lockdir"))):   # W-ask 4: held over 500 ms: how long, and where
                self.event("infra", status="lock_held", reason="state lock held %s ms at %s" % (ev.get("held_ms"), ev.get("where")))
            else:
                keep.append(ev)
        F.LOCK_EVENTS[:] = keep

    def _tx(self, fn):
        """``fn(state)`` in one transaction; its value comes back."""
        with self.txn() as (_tasks, state):
            return fn(state)

    def note_infra(self, state: dict | None = None) -> int:
        try:
            return max(self._tx(lambda st: F.note_infra(st, False)), 0)
        except Exception as e:  # broken plan/checkpoint or a busy lock: fall back to memory
            self.err("note_infra", e)
            self._mem_infra += 1
            return self._mem_infra

    def _series_ok(self) -> None:
        """A successful RUN, PROMOTE or TRIAGE ends the infrastructure series."""
        self._mem_infra = 0
        try:
            self._tx(lambda st: F.note_infra(st, True) if st.get("infra_streak") else None)
        except Exception as e:
            self.err("series reset", e)
        try:
            ls = self.ls()
            if ls.get("series_ch"):
                ls["series_ch"] = {}                    # the series ended: its failed channels are forgiven
                self.save_ls(ls)
        except Exception as e:
            self.err("series channels reset", e)

    def clear_brake(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self.brake.unlink(missing_ok=True)
        self._mem_infra = 0
        try:
            self._tx(lambda st: F.note_infra(st, True))
        except Exception as e:
            self.err("clear-brake reset", e)
        try:
            ls = self.ls()
            ls["no_proof"] = {}
            ls["series_ch"] = {}
            ls["brake"] = None
            self.save_ls(ls)
        except OSError as e:
            self.err("clear-brake spread", e)
        self.event("infra", status="brake_cleared", reason="--clear-brake")

    # -- one iteration
    def step(self) -> Outcome:
        self.iterations += 1
        t0 = self.clock()
        self._ticks_ms = {}
        try:
            out = self._step()
        except F.LockBusy:      # the state is locked by a live writer: the same wait as always, no failure
            out = Outcome(sleep=STATE_LOCKED_SLEEP_S, action="WAIT", reason="state_locked")
        except Exception as e:  # a. one error never kills the loop
            reason = "%s: %s" % (type(e).__name__, F.redact(str(e))[:300])
            streak = self.note_infra(None)
            self._series_charge([], self.clock())            # a loop error belongs to no channel: the series is global
            self.event("infra", status="error", reason=reason, infra_streak=streak,
                       base_sha=self.base_sha or None)
            out = Outcome(sleep=60, action="CRASH", reason=reason, status="infra")
            if streak >= self.cfg.max_infra:
                out = self._brake_or_wait(streak, out)      # live workers finish first: a proof may cancel the brake
        # ONE rule for the brake series. It grows on: NO_RESULT, infra=True, DEAD_CHANNEL reasons.
        # It is reset ONLY by proof that the pipeline works (a model answered without a provider
        # error, the gates/reviewer ran, a real merge). Everything else is neutral: any TRIAGE,
        # WAIT, HOLD, DONE, IDLE, a channel wait, a requeue, a parked task.
        if out.proof and out.status not in ("infra", "brake"):
            self._series_ok()
            self._brake_close()
        while LOCK_NOTES:
            self.event("infra", status="lock_check_failed", reason=LOCK_NOTES.pop(0))
        self.event("loop", action=out.action, reason=out.reason, status=out.status,
                   sleep_s=out.sleep, dur_s=round(self.clock() - t0, 3),
                   base_sha=self.base_sha or None, iteration=self.iterations, blockers=out.blockers,
                   ticks_ms={k: int(v) for k, v in self._ticks_ms.items() if v > 500} or None)
        self._stats()
        self._hourly_metrics()
        return out

    def _hourly_metrics(self) -> None:
        """<id>: once an hour a light, LLM-free report of accepted/hour, time and calls per accepted, ECHO vs fac-*."""
        now = self.clock()
        last = getattr(self, "_metrics_at", None)
        if last is not None and now - last < self.cfg.metrics_every_s:
            return
        self._metrics_at = now
        try:
            rep = factory_metrics.build_report(self.dir, since=self.cfg.metrics_since or None, now=self.ts(),
                                               paid_spend=factory_metrics_spend_file())
            self.event("metrics", status="ok", **factory_metrics.span_fields(rep))
        except Exception as e:
            self.err("metrics", e)

    def _brake(self, streak: int, out: Outcome) -> Outcome:
        """Pause for one minute, then ONE trial pass. A failed trial repeats the same pause."""
        now = self.clock()
        ls = self.ls()
        span = BRAKE_SPAN_S
        ls["brake"] = {"until": now + span, "span": span, "half_open": False, "since": now}
        self.save_ls(ls)
        text = self._scrub("brake: %d infrastructure failures in a row at %s (%s); retry after %d s\n" % (
            streak, self.ts(), out.reason, span))
        self.brake.write_text(text, encoding="utf-8")
        self.event("infra", status="brake", reason=text.strip()[:300], infra_streak=streak,
                   span_s=span, retry_at=self._iso(now + span))
        out.code, out.status = EXIT_BRAKE, "brake"
        return out

    def _iso(self, t: float) -> str:
        return dt.datetime.fromtimestamp(t).astimezone().isoformat(timespec="seconds")

    def _wait_out_brake(self) -> bool:
        """Owner rule 3 (tactical brakes lift by themselves): a continuous loop (--until) sits the brake's term
        out in this process and then runs the half-open trial pass, instead of exiting with EXIT_BRAKE for a restart
        nobody makes (no scheduler is allowed; live 21.11 14:36 the factory stood dead 40 min). True = go on;
        False = not continuous (--once / no --until), or STOP / the deadline came while waiting."""
        cfg = self.cfg
        if not cfg.until or cfg.once:
            return False
        self.event("loop", action="BRAKE_WAIT", status="brake", reason="sitting the brake term out")
        while True:
            if self.stop.exists() or dt.datetime.fromtimestamp(self.clock()) >= cfg.until:
                return False
            b = self.ls().get("brake")
            b = b if isinstance(b, dict) else {}
            left = float(b.get("until", 0) or 0) - self.clock()
            if left <= 0 or b.get("half_open"):
                return not self._brake_gate()       # flips to half-open: one trial pass
            self._sleep(min(WAIT_CHUNK_S, left))

    def _brake_gate(self) -> bool:
        """True = stay stopped. A BRAKE file with no recorded term (manual or old) gets BRAKE_SPAN_S from now."""
        if not self.brake.exists():
            return False
        now = self.clock()
        ls = self.ls()
        b = ls.get("brake") if isinstance(ls.get("brake"), dict) else None
        if b is None:
            b = {"until": now + BRAKE_SPAN_S, "span": BRAKE_SPAN_S, "half_open": False, "since": now}
            ls["brake"] = b
            self.save_ls(ls)
        if now < float(b.get("until", 0)) and not b.get("half_open"):
            self.event("loop", action="EXIT", status="brake", reason="brake_active",
                       retry_at=self._iso(float(b["until"])))
            return True
        if not b.get("half_open"):
            b["half_open"] = True
            self.save_ls(ls)
            self.event("infra", status="brake_half_open", reason="the term is over: one trial pass",
                       span_s=b.get("span"))
        return False

    def _brake_close(self) -> None:
        """A proof of work during the trial pass: the brake file goes, the series starts from zero."""
        try:
            ls = self.ls()
            if not (isinstance(ls.get("brake"), dict) and ls["brake"].get("half_open")):
                return
            ls["brake"] = None
            self.save_ls(ls)
            self.brake.unlink(missing_ok=True)
            self.event("infra", status="brake_closed", reason="the trial pass proved the pipeline works")
        except OSError as e:
            self.err("brake close", e)

    # -- 21.11: an infrastructure failure series is charged to the channel that failed (that channel cools down);
    # the global brake needs every usable channel in the series. "*" = a failure no channel owns (a crashed runner,
    # a loop error): the whole path is the suspect, as before.
    SERIES_ANY = "*"

    def _series_charge(self, names: list, now: float) -> None:
        """Book the failed channels of this series; each one cools 60, 120 ... s (BACKOFF_*), never shorter than it was."""
        try:
            ls = self.ls()
            book = ls.get("series_ch") if isinstance(ls.get("series_ch"), dict) else {}
            ls["series_ch"] = book
            for name in names or [self.SERIES_ANY]:
                book[name] = int(book.get(name, 0) or 0) + 1
            self.save_ls(ls)
        except Exception as e:
            self.err("series charge", e)
            return
        for name in names:
            if name == self.SERIES_ANY:
                continue
            secs = min(BACKOFF_MAX_S, BACKOFF_FIRST_S * 2 ** min(book.get(name, 1) - 1, 10))
            try:
                self._tx(lambda st, n=name, s=secs: CH.cool_channel(st.setdefault("channel_quotas", {}), {"id": n},
                                                                    now=now, seconds=s))
            except Exception as e:
                self.err("channel cool", e)
        if names:
            self.event("infra", status="channel_charged", reason=",".join(self.rs(n, 60) for n in names),
                       scope="channel", backoff_n=max(book.get(n, 1) for n in names))

    def _series_all_failed(self) -> bool:
        """True = the brake may fire: a failure nobody owns is in the series, or every usable channel failed in it.
        Unknown (unreadable registry or state) = True, the old behaviour."""
        try:
            book = self.ls().get("series_ch")
            if not isinstance(book, dict) or not book or self.SERIES_ANY in book:
                return True
            configured = json.loads(Path(self.cfg.channels).read_text(encoding="utf-8"))["channels"]
            quota = self.load()[1].get("channel_quotas")
            quota = quota if isinstance(quota, dict) else {}
            seen = quota_ledger.view(quota, quota_ledger.others(Path(self.cfg.channels).resolve().parent / "quota",
                                                                str(self.ckpt)))     # W-gemma5 1: the one merged view
            live = CH.usable(configured, seen, {**os.environ, **self.extra_env})
            return not [c["id"] for c in live if c["id"] not in book]
        except Exception as e:
            self.err("series check", e)
            return True

    # -- temporary faults: a pause for their own channel or task only
    def _temporary(self, rkey: str, ckey: str, res: dict, no_result: bool) -> str:
        if no_result or rkey in DEAD_CHANNEL or ckey in DEAD_CHANNEL:
            return ""
        for k in (rkey, ckey):
            if k in TEMPORARY_CHANNEL or k in TEMPORARY_TASK:
                return k
        return "429" if res.get("http_status") == 429 else ""

    def _defer_temporary(self, reason: str, res: dict, calls: list, tid: str, ls: dict, out: Outcome,
                         wait_s) -> Outcome:
        """60, 120, 240 ... 1800 s (+-10 % jitter) for the key (a channel or a task); never the brake series."""
        now = self.clock()
        channel = reason in TEMPORARY_CHANNEL or reason == "429"
        if tid and reason == "rate_minute":
            self._small_wait_note(tid, now)       # W-gslice 3: an editor waits for a free channel: the slicing ensembles give way
        name = next((str(c.get("channel")) for c in calls if c.get("channel")), "") or str(
            res.get("channel") or "") or "*"
        key = ("ch:" + name[:40]) if channel else ("task:" + (tid or "?")[:60])
        book = ls.get("backoff")
        if not isinstance(book, dict):
            book = ls["backoff"] = {}
        rec = book.get(key) if isinstance(book.get(key), dict) else {}
        fresh = now - float(rec.get("at", 0) or 0) <= 2 * BACKOFF_MAX_S
        n = int(rec.get("n", 0) or 0) + 1 if fresh else 1
        base = min(BACKOFF_MAX_S, BACKOFF_FIRST_S * 2 ** min(n - 1, 10))
        if isinstance(wait_s, (int, float)) and not isinstance(wait_s, bool):
            base = max(base, float(wait_s))
        delay = min(float(BACKOFF_MAX_S), max(1.0, base * (1 + self.rng.uniform(-0.1, 0.1))))
        until = now + delay
        book[key] = {"n": n, "at": now, "until": until}
        for old in sorted(book, key=lambda k: float((book[k] or {}).get("at", 0)))[:-64]:
            book.pop(old, None)
        if channel and name != "*":     # a named channel cools alone; the other channels keep working (live 21.11: one
            self._tx(lambda st, n=name, s=delay: CH.cool_channel(    # channel's 429 held the whole loop 30 min)
                st.setdefault("channel_quotas", {}), {"id": n}, now=now, seconds=s))
        elif channel:
            ls["channel_until"] = max(float(ls.get("channel_until", 0)), now + min(delay, GLOBAL_WAIT_MAX_S))
        self.save_ls(ls)
        if not channel and tid:
            def postpone(state):
                row = state["tasks"].get(tid)
                if row is not None and row.get("status") in ("READY", "BLOCKED"):
                    row["not_before"] = max(float(row.get("not_before") or 0), until)
            self._tx(postpone)
        self.event("infra", task_id=tid or None, status="deferred", reason=self.rs(reason, 60),
                   scope="channel" if channel else "task", key=self.rs(key, 80), delay_s=round(delay, 1),
                   backoff_n=n, retry_at=self._iso(until))
        out.status, out.reason, out.sleep = "deferred", reason, (5 if channel else 1)
        return out

    def _git_wait(self, e) -> Outcome:
        """A git launch/OS failure waits independently of the infrastructure brake."""
        now, ls = self.clock(), self.ls()
        n = int((ls.get("git_wait") or {}).get("n", 0)) + 1
        delay = min(GIT_WAIT_MAX_S, GIT_WAIT_FIRST_S * 2 ** min(n - 1, 10))
        ls["git_wait"] = {"n": n, "at": now, "until": now + delay}
        self.save_ls(ls)
        self.event("infra", status="git_wait", reason="%s: %s" % (type(e).__name__, self.rs(str(e), 300)),
                   delay_s=delay, backoff_n=n, retry_at=self._iso(now + delay))
        if self.pool.workers:
            return self._await_workers()
        return Outcome(action="WAIT", status="git_wait", reason="git_wait", sleep=delay)

    def _act(self, state, tasks, ls, now, eligible=None) -> dict:
        wait_s = max(0.0, float(ls.get("channel_until", 0)) - now)
        free = 1 if (self.pool.workers and not self._capacity(None)) else 0
        if eligible is None:        # W-feed2 4d: _fill hands the set it already has
            eligible = self._resliceable(tasks, state, ls, now) if self.slice_fn else {}
        self._last_eligible = eligible
        waits = [until - now for until in ls.get("slice_wait", {}).values() if until > now]
        skip = self.pool.tids() | self._dry_blocked(tasks, state)
        ready_code = {t for t, task in tasks.items() if state["tasks"].get(t, {}).get("status") == "READY" and self._has_code(task)}
        if self._hypers:        # W-feed2 2: a row under the hypotheses search does not start with a card
            skip = skip | {t for t, task in tasks.items() if F.row_of(task.backlog_id or t) in self._hypers}
        if first := self._solver_first(tasks, state, ls, now):      # a red row is solved first; its own card (engine solver) is not held
            skip = skip | {t for t, task in tasks.items() if F.row_of(task.backlog_id or t) in first
                           and state["tasks"].get(t, {}).get("engine") != "solver"}
        # fac-54: a running solve holds only the cards of its own row (above), never every ready rel- card
        # a card with finished code spends no minute of the models: no search and no order of the rows holds it back
        skip = (skip - ready_code) | self.pool.tids()
        later = self._bisect_later(tasks, state) - ready_code        # W-bisect 4: never_green debt cards wait while there is other work

        def ask(hold):
            return F.next_action(state, now, wait_s, self._has_more(ls, now), tasks, free=free, skip=skip | hold,
                                 resliceable=frozenset(eligible), slice_wait_s=min(waits) if waits else None)
        act = ask(later)
        if later and act["action"] in ("DONE", "HOLD"):  # the queue is otherwise empty: the way out of the deferral
            act = ask(set())
        if act.get("task_ids"):
            act["task_ids"] = sorted(act["task_ids"], key=lambda t: t not in ready_code)
        return act

    def _lap(self, name, t0) -> None:
        """W-feed2 4a: the time of one stage of the step (ms, summed by name); the loop event shows those over 500 ms."""
        laps = self.__dict__.setdefault("_ticks_ms", {})
        laps[name] = laps.get(name, 0.0) + (self.clock() - t0) * 1000.0

    def _tick(self, name, fn, *args, every=0.0, skipped=None):
        """One tick of the step, measured. ``every``: not again sooner than that many seconds (the call before its term costs
        nothing, ``skipped`` is returned); the first call of a loop always runs."""
        now = self.clock()
        if every:
            last = self.__dict__.setdefault("_tick_at", {}).get(name)
            if last is not None and 0 <= now - last < every:
                return skipped
            self._tick_at[name] = now
        try:
            return fn(*args)
        finally:
            self._lap(name, now)

    def _early_fill(self, now):
        """W-feed2 4b: start the cards the plan can take now, before the heavy ticks. An Outcome ends the step, None goes on."""
        t0 = self.clock()
        tasks, state = self.load()
        ls = self.ls()
        act = self._act(state, tasks, ls, now)
        self._lap("early.act", t0)
        if act["action"] != "RUN":
            return None
        before = set(self.pool.tids())
        out = self._fill(act, tasks, state, ls, now)[0]
        if out is None:
            self._settle_started(set(self.pool.tids()) - before)
        return out

    EARLY_SETTLE_S = 1.0      # the most the heavy ticks wait for the runners of the early fill to take their cards

    def _settle_started(self, tids) -> None:
        """The runners started by the early fill take their cards (``began`` in the state) before the heavy ticks run, so those
        ticks do not compete with the booting runners for the state lock and the CPU. Bounded; a runner that ended is not waited for."""
        if not tids:
            return
        t0, c0 = time.monotonic(), self.clock()
        while time.monotonic() - t0 < self.EARLY_SETTLE_S:
            try:
                rows = self.load()[1]["tasks"]
            except (OSError, ValueError, KeyError, TypeError):
                return
            alive = {w.tid for w in self.pool.workers.values() if w.owned is not None and w.owned.poll() is None}
            waiting = [t for t in tids if t in alive and not (rows.get(t) or {}).get("began")]
            if not waiting:
                break
            time.sleep(0.02)
        self._lap("early.settle", c0)

    def _step(self) -> Outcome:
        cfg, now = self.cfg, self.clock()
        if cfg.self_repo:
            self._sync_ready_tick(now)      # before the mirror is read: the merged branch is what the cards see
        try:
            self.base_sha = refresh_mirror(cfg.repo, cfg.branch, self.mirror)
        except (subprocess.CalledProcessError, OSError) as e:
            return self._git_wait(e)
        ls = self.ls()
        if ls.pop("git_wait", None) is not None:
            self.save_ls(ls)
        verdict = ls.get("release") or {}
        F.FRESH_REL.clear()
        if verdict.get("status") == "new_red":
            F.FRESH_REL.add(str(verdict.get("sha") or "")[:8])
        self._tick("apply_answers", self.apply_answers)  # Opus answers first: before anything else touches the state
        out = self._early_fill(now)          # W-feed2 4b: the cards start BEFORE the heavy ticks
        if out is not None:
            return out
        self._tick("bg_poll", self._bg_poll)  # a finished background triage / hold pick is applied here, in this thread
        self._tick("sweep", self._sweep_tick, now)  # the red-guard supply follows the loop's own results and a periodic cloud sweep
        self._tick("links", self._links_tick, now, every=self.TICK_MIN_S)  # the owner's words are linked to backlog rows in their own slot (4.2)
        self._tick("release", self._release_tick, now)  # the final build: a full cloud sweep in its own slot, then the acceptance of merged rows
        self._tick("bisect", self._bisect_tick, now, every=self.TICK_MIN_S)  # W-bisect: the history search of the baseline debt (one cloud run at a time, behind the cards and the build)
        self._tick("neighbors", self._neighbors_tick, self.base_sha, None)  # the neighbour map of the base: built once per SHA in the background
        tasks, state = self.load()
        self._tick("reslice", self._reslice_tick, tasks, state, self.ls(), now)
        self._tick("hypo_feed", self._hypo_feed, now)     # W-feed2 2: the search of the red rows, independent of the slicer
        with self.txn() as (_tasks, state):       # a lease a live worker still holds is ended by the loop, not freed
            freed = F.release_expired(state, now, keep=self.pool.tids())
        if freed:
            self.event("infra", status="released", reason="lease_expired:" + ",".join(freed))
        self._tick("unburn", self._unburn_no_answer, every=self.TICK_MIN_S)
        self._tick("short_chain", self._unblock_short_chain, every=self.TICK_MIN_S)
        self._tick("guard_ids", self._guard_ids_reset, every=self.TICK_MIN_S)
        self._tick("guard_green", self._guard_green_requeue, every=self.TICK_MIN_S)
        self._tick("fixture_private", self._book_fixture_private, every=self.TICK_MIN_S)
        tasks, state = self.load()
        ls = self.ls()
        ls = self._tick("reconcile", self._reconcile_tick, tasks, state, ls, now, every=self.TICK_MIN_S, skipped=ls)
        ls = self._tick("lost", self._lost_tick, tasks, state, ls, now, every=self.TICK_MIN_S, skipped=ls)       # W-lost 1/3/4: the feed invariant, once a minute
        ls = self._close_parents(tasks, state, ls)
        if now - float(ls.get("tmp_clean_at", 0)) > 86400 and not any(
                r["status"] == "RUNNING" for r in state["tasks"].values()):
            ls["tmp_clean_at"] = now          # once a day, only while nothing runs
            self.save_ls(ls)
            self._clean_state_tmp()
        done = self.pool.finished()
        if done:                              # a worker ended: its result is accounted before anything new starts
            return self._account_done(done[0])
        act = self._act(state, tasks, ls, now)
        if act["action"] == "PROMOTE":
            return self._promote(act["task_id"], tasks, state, ls)
        out, act, tasks, state, ls = self._fill(act, tasks, state, ls, now)
        if out is not None:
            return out
        name, why = act["action"], act.get("reason", "")
        if name != "TRIAGE":
            self._ready_topup(state, tasks, ls, now)       # <id>: READY below the target: the slicer works ahead of the queue
        if name == "PROMOTE" and not self.pool.workers:
            return self._promote(act["task_id"], tasks, state, ls)
        if (name == "WAIT" and why == "channel_cooldown" and float(act.get("wait_s") or 0) >= 300
                and now - float(ls.get("wait_triage_at", 0)) >= cfg.triage_retry_s
                and self._bg is None
                and self._has_more(ls, now)
                and not any(r["status"] == "RUNNING" for r in state["tasks"].values())):
            ls["wait_triage_at"] = now  # a long channel wait: triage the next portion meanwhile
            self.save_ls(ls)
            return self._triage(state, tasks, ls, now)
        if name == "UNBLOCK":                  # <id>: a block's term is over, the loop lifts it itself (no wait for Opus)
            return self._auto_unblock(act)
        if name == "TRIAGE":
            if self.pool.workers:               # feed while they work: the portion is asked in the background
                self._triage_prefetch(state, tasks, ls, now)
                return self._await_workers()
            if self._bg is not None:            # one job in flight: nothing else to do but to look at it again
                self._bg.done.wait(WAIT_CHUNK_S)
                return Outcome(sleep=0, action="WAIT", reason="prefetch_running")
            out = self._triage(state, tasks, ls, now)
            return out
        if self.pool.workers:                  # nothing more to start now: wait for the next worker to end
            return self._await_workers()
        if name == "RUN":                      # work is ready but no worker may start: the reason is the wait
            return Outcome(sleep=60, action="WAIT", reason=self._refused or "not_runnable")
        if name == "WAIT":
            return Outcome(sleep=min(max(float(act.get("wait_s") or 0), 5), 60),
                           action="WAIT", reason=why)
        if name == "RESLICE":
            return Outcome(sleep=RESLICE_SLEEP_S, action="RESLICE", reason=why)
        if name == "HOLD":
            self._write_questions(tasks, state, ls)
            self._write_reconcile(tasks, state, self.ls(), now)
            sleep = cfg.hold_sleep
            if isinstance(act.get("wait_s"), (int, float)):     # the earliest block term ends the HOLD
                sleep = min(sleep, max(5.0, float(act["wait_s"])))
            return Outcome(sleep=sleep, action="HOLD", reason=why, blockers=act.get("blockers"))
        if cfg.exit_when_idle and not self._slicers and not ls.get("to_slice"):
            return Outcome(code=EXIT_OK, action="DONE", reason=why)        # 1.6: the canary's loop ends when nothing is left
        return Outcome(sleep=cfg.done_sleep, action="DONE", reason=why)

    def _auto_unblock(self, act) -> Outcome:
        """<id>: the block of act['task_id'] is past its term. Lifted (F.unblock) at most F.AUTO_UNBLOCK_MAX times per
        task, counted in requeue_ledger.json (key 'hold:<time>') together with the new-version requeues; past that the
        task is escalated (FAILED escalated:<reason>, a line in opus_questions.md), never lifted again."""
        tid, why = act["task_id"], str(act.get("reason") or "unknown")
        now = self.clock()
        term = self._iso(float(act.get("block_until") or now))
        path = self.cfg.state_dir / "requeue_ledger.json"
        try:
            ledger = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        except (OSError, ValueError):
            ledger = {}
        used = len(ledger.get(tid) or [])
        # already_green is a fact of the base, not of a model: a lift reruns the same green test on the same base (live
        # 21.11 21:41-22:20: 7 tasks took 12 lifts, a slot each, all green again). It goes to the head question at once.
        # a green candidate that only lacks a second reviewer waits for the day of the other models, it is never buried (live 25.11: <id>_s2_r2)
        if (used >= F.AUTO_UNBLOCK_MAX and why != "review_chain_short") or why == "already_green":
            got = []

            def esc(state):
                if state["tasks"].get(tid, {}).get("status") == "BLOCKED":
                    got.append(F.escalate(state, tid))
            self._tx(esc)
            text = "%s: %s, срок %s, возвратов %d/%d исчерпано" % (tid, why, term, used, F.AUTO_UNBLOCK_MAX)
            if got:
                self.event("infra", task_id=tid, status="escalated", reason=self.rs(got[0], 80), block_until=term,
                           returns=used)
                try:
                    self._write_questions(*self.load(), self.ls())
                except Exception as e:
                    self.err("questions after escalation", e)
            return Outcome(sleep=1, action="ESCALATE", reason=self.rs(text, 200))
        n = used + 1
        lifted = []

        def lift(state):   # no feedback note: the coder keeps its last failure; the event below is the record
            if state["tasks"].get(tid, {}).get("status") == "BLOCKED":
                F.unblock(state, tid, None)
                lifted.append(tid)
        self._tx(lift)
        if lifted:
            ledger.setdefault(tid, []).append("hold:" + self._iso(now))
            F.save_atomic(path, ledger)
        text = "%s: %s, срок %s, %d/%d" % (tid, why, term, n, F.AUTO_UNBLOCK_MAX)
        return Outcome(sleep=1, action="UNBLOCK", reason=self.rs(text, 200), status="ok" if lifted else "gone")

    _refused = ""

    def _fill(self, act, tasks, state, ls, now):
        """Start workers while there is compatible work and room for one more (capacity is checked BEFORE the <id> spec
        pass: a task that cannot start now costs no model call). (outcome | None, act, tasks, state, ls)."""
        self._refused = ""
        admitted, refused, live0 = 0, "", len(self.pool.workers)
        declined = set()                                    # W-gemma6: ids _admit answered 0 in this pass are not chosen again
        locked = None                                       # W-feed2 4g: the claim of a card met a busy lock five times: the next card
        # W-feed2 4d: the list of task ids is counted once per pass; the claim (F.acquire under the lock) checks every card
        # again, so after a start only the state is read anew, never the plan, the act or the resliceable set
        ids = list(act.get("task_ids") or [act.get("task_id")]) if act["action"] == "RUN" else []
        ids.sort(key=lambda t: not self._has_candidate(state, t))      # W-hypo3 3: the card with a green candidate resumes first (its review takes the minute before edits)
        for tid in ids[:64]:                              # bounded
            if not tid or tid in self.pool.tids() or tid in declined:
                continue
            t0 = self.clock()
            refused = self._capacity(tasks.get(tid), state)       # W-tick 4: the state of the pass, no load() per card
            self._lap("fill.capacity", t0)
            if refused:
                break
            t0 = self.clock()
            self._claimed_state = None                        # W-tick 6: set by this _admit's claim only, never a leftover (tasks stay the pass's plan: the claim does not change the plan)
            got = self._admit(tid, tasks, ls)
            self._lap("fill.admit", t0)
            if isinstance(got, Outcome):
                if got.reason == "state_locked":
                    locked = got
                    declined.add(tid)
                    continue
                self._pool_event(admitted, refused, live0, tasks, state, now)
                return got, act, tasks, state, ls
            admitted += got
            if not got:
                declined.add(tid)
                continue
            # W-tick 4: the state the claim itself wrote (no read per start). Known trade-off: began/booked written by _admit
            # after the claim are seen only by the one read at the end of the pass; the claim re-checks every card under the lock
            claimed = getattr(self, "_claimed_state", None)
            self._claimed_state = None
            if isinstance(claimed, dict):
                state = claimed
            else:
                t0 = self.clock()
                tasks, state = self.load()
                self._lap("fill.load", t0)
        if admitted:
            t0 = self.clock()
            tasks, state = self.load()          # the claims changed the state: ONE fresh read for the next act
            self._lap("fill.load", t0)
            ls = self.ls()
            act = self._act(state, tasks, ls, now, eligible=getattr(self, "_last_eligible", None))
            self._lap("fill.act", t0)
        elif locked is not None:
            self._pool_event(admitted, refused, live0, tasks, state, now)
            return locked, act, tasks, state, ls
        self._refused = refused
        self._pool_event(admitted, refused, live0, tasks, state, now)
        return None, act, tasks, state, ls

    def _pool_event(self, admitted: int, refused: str, live0: int, tasks=None, state=None, now=None) -> None:
        live = len(self.pool.workers)
        if live >= 2 or (refused and live >= 1):
            med, burst, _ = self._mem_plan()
            extra = {}
            if tasks is not None and state is not None:       # W-optim 5: what could start (no claims) and what the claims hold
                try:
                    skip = self._dry_blocked(tasks, state)
                    extra = dict(startable=len(F.claim_free(tasks, state, now, exclude=skip)),
                                 locked=F._blocked_by_claims(tasks, state, now, exclude=skip))
                except Exception as e:                        # an aid: the event stays as before
                    self.err("pool counts", e)
            self.event("pool", status="admitted" if admitted else "held", live=live, admitted=admitted or None,
                       refused_by=refused or None, free_ram_mb=int(self.free_ram_fn() / 2 ** 20),
                       est_mb=int(med / 2 ** 20), burst_mb=int(burst / 2 ** 20), headroom=self._headroom_seen, **extra)

    _headroom_seen = None

    def _ending(self) -> bool:
        cfg = self.cfg
        return self.stop.exists() or bool(cfg.until and dt.datetime.fromtimestamp(self.clock()) >= cfg.until)

    def _await_workers(self) -> Outcome:
        """Workers are live: wait for the next one to end (a short look every WAIT_CHUNK_S: a cooled channel or freed
        RAM may admit one more). STOP, the deadline or a due brake: no admission, drain every live worker."""
        self._pulse_at = getattr(self, "_pulse_at", None) or self.clock()
        began = self.clock()
        while True:
            if self._ending() or self._brake_due is not None:
                return self._drain()
            if self.clock() - began >= AWAIT_STEP_S:        # live 25.11: 40 % of the hours no row was sliced and nothing merged while one worker lived
                return Outcome(sleep=0, action="WAIT", reason="workers")
            done = self.pool.wait_any(WAIT_BG_S if self._bg is not None else WAIT_CHUNK_S)
            if done:
                return self._account_done(done[0])
            self._wait_pulse()
            late = [w for w in self.pool.workers.values()
                    if w.owned is not None and w.res is None and time.monotonic() - w.t_claim > RUNNER_TIMEOUT_S]
            if late:
                return self._account_done(late[0], timed_out=True)
            self._bg_poll()                     # a finished portion becomes tasks now, not after the next worker ends
            self._head_holds()                  # the gate decides; a pick runs in the background
            self._tick("hypo_feed", self._hypo_feed, self.clock())     # W-feed2 2: the searches go on while the workers work
            tasks, state = self.load()
            ls = self.ls()
            now = self.clock()
            act = self._act(state, tasks, ls, now)
            if act["action"] == "TRIAGE":
                self._triage_prefetch(state, tasks, ls, now)
            elif act["action"] == "RUN":
                out, act, tasks, state, ls = self._fill(act, tasks, state, ls, now)
                if out is not None:
                    return out

    def _wait_pulse(self) -> None:
        """The wait for live workers writes one short event at least every WAIT_PULSE_S: a worker may wait for the cloud for
        minutes and the loop writes nothing else, and the watcher of the telemetry (factory_survive) takes a silent file for a
        hung loop. A step that really hangs never gets here, so it writes none and is still caught."""
        now = self.clock()
        if now - getattr(self, "_pulse_at", now) < WAIT_PULSE_S:
            return
        self._pulse_at = now
        self.event("loop", action="WAIT", status="pulse", workers=len(self.pool.workers))

    def _drain(self) -> Outcome:
        """No admission: wait for every live worker and account it. A brake that is due waits for the last one, and a
        proof of work during the drain cancels it."""
        out = Outcome(action="RUN", reason="drain", status="ok")
        proof = False
        while self.pool.workers:
            done = self.pool.wait_any(WAIT_CHUNK_S)
            if not done:
                self._wait_pulse()
            late = [w for w in self.pool.workers.values()
                    if w.owned is not None and w.res is None and time.monotonic() - w.t_claim > RUNNER_TIMEOUT_S]
            for w in (done or late):
                try:
                    got = self._account(w, timed_out=w not in done)
                except F.LockBusy:
                    self.sleep_fn(1.0)          # the result is parked on the worker: look again, the others live on
                    continue
                proof = proof or got.proof
                if got.proof and got.status not in ("infra", "brake"):
                    self._series_ok()
                    self._brake_due = None
                out = got
        return self._finish_brake(out, proof)

    def _account_done(self, w: Worker, timed_out: bool = False) -> Outcome:
        out = self._account(w, timed_out=timed_out)
        if self._brake_due is not None:
            return self._drain() if self.pool.workers else self._finish_brake(out, out.proof)
        if self.pool.workers:
            out.sleep = 0                       # the others are still working: look at them at once
        return out

    def _finish_brake(self, out: Outcome, proof: bool) -> Outcome:
        due, self._brake_due = self._brake_due, None
        if due is None:
            return out
        try:
            streak = int(self.load()[1].get("infra_streak", 0))
        except Exception as e:
            self.err("brake check", e)
            streak = due
        if streak >= self.cfg.max_infra and not proof and self._series_all_failed():
            return self._brake(streak, out)
        out.proof = out.proof or proof
        if out.proof:
            out.status = "ok"
        return out

    def _seed_section(self, folder, section, quotas) -> None:
        """W-dry 3: the requests this section already published today (an earlier run of the loop, a call whose state
        was never saved) are in ``quotas`` before the next booking: a publish never writes a smaller count over a larger
        one. Joined by value, never sorted."""
        from tools import factory_quota as Q
        try:
            data = json.loads(Q.section_file(folder, section).read_text(encoding="utf-8"))
            saved = data["quotas"] if isinstance(data, dict) and isinstance(data.get("quotas"), dict) else {}
        except (OSError, ValueError):
            return
        for key, group in saved.items():
            if not (isinstance(group, dict) and isinstance(group.get("request_times"), list)):
                continue
            mine = quotas.setdefault(key, {})
            if not isinstance(mine, dict):
                continue
            for name in ("request_times", "rpm_times"):
                have = list(mine.get(name) or [])
                known = set(have)
                extra = [t for t in (group.get(name) or []) if isinstance(t, (int, float)) and t not in known]
                if extra:
                    mine[name] = have + extra
            mine["requests"] = max(int(mine.get("requests") or 0), int(group.get("requests") or 0))

    def _light_ask(self, text: str, *, attempt: int, section: str, quotas: dict, max_tokens: int, role: str = "code",
                   thrifty: bool = False, temperature: float = 0, only_tier: str = "", only_model: str = "", why: dict = None,
                   only_channel: str = "", no_head: bool = False, unserved: bool = False):
        """One free model call outside the runner (the <id> self-fix head): a registry channel in
        route_order (attempt 1: main first; 2: escalation first), booked in the shared quota ledger under `section`
        and cooled there on 429/5xx. Returns (status, model, answer, tokens): status 'ok', 'no_channel' or
        'http_<code>'; tokens = the usage of the answer, else the estimate."""
        from tools import agent_factory_runner as R
        from tools import factory_channels as C
        from tools import factory_quota as Q
        share = sum("\u0400" <= c <= "\u04ff" for c in text) / max(1, len(text))
        tokens = C.estimate_tokens(len(text), 0, 500, cyrillic=share)
        channels = json.loads(Path(self.cfg.channels).read_text(encoding="utf-8"))["channels"]
        env = {**os.environ, **self.extra_env}
        folder = Path(self.cfg.channels).resolve().parent / "quota"
        section = "%s@%s" % (section, self.ckpt)     # W-dry 3: one writer per section: a second instance never overwrites this file

        def publish():
            try:
                Q.publish(folder, section, quotas)
            except OSError as e:
                self.err(section + " ledger", e)
        via = []                   # fac-40: the small channels the head serves (nothing is booked here for them)
        with self._ask_lock:
            self._seed_section(folder, section, quotas)
            seen = Q.view(quotas, Q.others(folder, section))
            try:
                now_ask = self.clock()
                order = C.route_order(channels, role, attempt, tokens)
                if unserved:        # W-bucket: the head expired the ask: only the providers it does not serve, never around it
                    from tools import factory_head as HD
                    order = [c for c in order if not HD.serves(c)]
                # W-bucket: the channels a live head serves skip the ledger's day marks (the head's own PerDay rule closes them)
                headed = {c["id"] for c in ([] if no_head else self._head_channels(order))}
                kept, closed = self._day_split([c for c in order if c["id"] not in headed], seen, env, folder, now_ask)
                kept_ids = {c["id"] for c in kept} | headed
                order = [c for c in order if c["id"] in kept_ids]
                if not headed and not unserved and section.startswith("loop-architect@") and C.main_dry(channels, seen, env, now=now_ask):
                    # (a live head decides the day of the channels it serves by its own PerDay rule: no ledger day mark here)
                    # W-gemma2 3: every main channel is closed by the day's mark: the free steps (architect / code) go to Gemma
                    # only and send no request to a channel the day's mark closed (but the one probe of the gate below)
                    shut = {c["id"] for c in closed}
                    order = [c for c in C.route_order(channels, "edit", 1, min(tokens, C.DRY_SMALL_TOKENS), state=seen,
                                                      env=env, now=now_ask)
                             if C.tier_of(c) == "small" and c["id"] not in shut]

                def thrifty_ok(c):     # links / keywords / architect / slice: with under DAY_LEFT_FOR_CARDS of the day left a main-tier channel is kept for the cards
                    if C.tier_of(c) == "small" or not (thrifty or (role in CARD_BUDGET_ROLES and C.tier_of(c) == "main")):
                        return True
                    return C.day_left_share(seen, c, now=self.clock()) >= DAY_LEFT_FOR_CARDS
                before_thrifty = bool(order)
                order, closed = [c for c in order if thrifty_ok(c)], [c for c in closed if thrifty_ok(c)]
                if (before_thrifty and not order and not headed and not unserved and role == "architect"
                        and section.startswith("loop-architect@")):
                    # fac-63: the architect's route has no small tier: with the main day kept for the cards it asks Gemma
                    # (same fallback as main_dry), never stands idle until the day's reset
                    shut = {c["id"] for c in closed}
                    order = [c for c in C.route_order(channels, "edit", 1, min(tokens, C.DRY_SMALL_TOKENS), state=seen,
                                                      env=env, now=now_ask)
                             if C.tier_of(c) == "small" and c["id"] not in shut]
                if only_tier or only_model:     # W-gslice 1: the small-tier ensemble asks Gemma only, on its own model when named
                    def wanted(c):
                        return ((not only_tier or C.tier_of(c) == only_tier) and (not only_model or c["model"] == only_model)
                                and not C.is_reserve(c))
                    order, closed = [c for c in order if wanted(c)], [c for c in closed if wanted(c)]
                if only_channel:        # W-feed2 6: the pump's worker is bound to ONE real channel (model + key)
                    order = [c for c in order if c["id"] == only_channel]
                    closed = [c for c in closed if c["id"] == only_channel]
                channel = None
                for probe in closed:     # one probe per channel per 20 minutes, the claim shared by both instances; due whether
                    try:                 # or not the open channels answer (a healthy channel must not stay shut all day)
                        C.choose([probe], seen, tokens, env, now=now_ask)
                    except C.ChannelUnavailable:
                        continue
                    if Q.gate_claim(folder, probe["id"], now=now_ask):
                        channel = probe
                        break
                if channel is None:
                    via = [] if no_head else self._head_channels(order)
                    if not via:
                        channel = C.choose(order, seen, tokens, env, now=now_ask)
            except C.ChannelUnavailable as unavailable:
                if why is not None:         # W-prio3: the reason of the booking (tpm_window / rpm / rpd / cool ...) and the wait
                    why.update(reason=str(getattr(unavailable, "reason", "")), wait_s=float(getattr(unavailable, "wait_s", 0) or 0))
                return "no_channel", None, "", tokens
            if not via:
                model = channel["model"]
                C.reserve(quotas, channel, tokens, now=self.clock())
                publish()
        if via:
            done = self._light_via_head(via, text, tokens, max_tokens, temperature, role, why)
            if done is not None and done[0] == "head_expired":
                # W-bucket: the head could not send it in time: the other providers of the route answer it (never a
                # Google channel around the head); none of them: no channel now, with the head's reason and ETA
                from tools import factory_head as HD
                if not unserved and any(not HD.serves(c) for c in order):
                    return self._light_ask(text, attempt=attempt, section=section, quotas=quotas, max_tokens=max_tokens,
                                           role=role, thrifty=thrifty, temperature=temperature, only_tier=only_tier,
                                           only_model=only_model, why=why, only_channel=only_channel, no_head=True,
                                           unserved=True)
                return ("no_channel",) + tuple(done[1:])
            if done is not None:
                return done
            return self._light_ask(text, attempt=attempt, section=section, quotas=quotas, max_tokens=max_tokens, role=role,
                                   thrifty=thrifty, temperature=temperature, only_tier=only_tier, only_model=only_model, why=why,
                                   only_channel=only_channel, no_head=True)       # the head did not answer: the old path
        provider, _, model_id = model.partition("/")
        body = {"model": model_id, "temperature": temperature, "max_tokens": max_tokens,       # ERROR_PATTERNS inline-thought
                "messages": [{"role": "user", "content": R.NO_THOUGHT + "\n\n" + text}]}
        code_http, raw, _sent = C.post_with_extra(_light_post, R.LIGHT_ENDPOINTS[provider], env[channel["key_env"]],
                                                  body, 120, model)
        if code_http != 200:
            if code_http in (429, 500, 503):      # the next call takes another channel for a while
                with self._ask_lock:
                    info = None
                    if code_http in (429, 503):     # W-dry 3: a daily 429 names its limit (quotaValue): calls_day is aligned to it
                        try:
                            info = C.classify(R._light_error(code_http, raw), b"", 1)
                        except Exception as e:      # an aid: the plain cooling below stands
                            self.err("light failure class", e)
                    if info is not None and info.get("kind") in ("rate_day", "rate_minute"):
                        C.apply_failure(quotas, channel, info, env=env, now=self.clock())
                        if info.get("kind") == "rate_day":
                            try:
                                Q.gate_note(folder, channel["id"], now=self.clock())   # W-gemma2 3: closed until a probe answers
                            except OSError as e:
                                self.err(section + " day gate", e)
                    elif not only_channel:      # W-feed2 6: the pump's net 503 does not rest the channel: tpm and rpm set its pace
                        C.cool_channel(quotas, channel, now=self.clock(),      # W-gemma 3: a refused send of Gemma rests it 10 s
                                       **({"seconds": C.BIG_TIMEOUT_CLOSE_S} if C.no_streak(channel) else {}))
                    publish()
            return "http_%s" % code_http, model, "", tokens
        try:
            Q.gate_clear(folder, channel["id"])      # W-gemma2 3: an answer 200 ends the day's closing of the channel
        except OSError as e:
            self.err(section + " day gate", e)
        with self._ask_lock:       # ... and of the channel report's own probe series (day_probe) kept in the same ledger
            try:
                C.note_outcome(quotas, channel, True, now=self.clock())
                publish()
            except Exception as e:      # an aid: the answer stands
                self.err(section + " day probe", e)
        try:
            data = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
            answer = data["choices"][0]["message"].get("content") or ""
            used = (data.get("usage") or {}).get("total_tokens")
        except (ValueError, KeyError, IndexError, TypeError, AttributeError):
            answer, used = "", None
        return "ok", model, answer, used or tokens

    def _head_channels(self, order) -> list:
        """W-bucket: every channel of ``order`` the head serves (all Google tiers, in order) when the head is alive (a live
        pid and a fresh pulse, not merely its state file), else []."""
        from tools import factory_head as HD
        if not HD.alive(Path(self.cfg.channels).resolve().parent / HD.STATE_NAME):
            return []
        return [c for c in order if HD.serves(c)]

    def _light_via_head(self, via, text, tokens, max_tokens, temperature, role, why):
        """fac-40: one ask of the head. Returns the _light_ask tuple, or None when the head is down (event written)."""
        from tools import agent_factory_runner as R
        from tools import factory_head as HD
        body = {"temperature": temperature, "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": R.NO_THOUGHT + "\n\n" + text}]}
        # the loop's own thread (admission, ticks) never blocks for the head's full wait: LOOP_HEAD_WAIT_S there
        wait = LOOP_HEAD_WAIT_S if threading.current_thread() is threading.main_thread() else None
        try:
            got = HD.ask(Path(self.cfg.channels).resolve().parent / HD.STATE_NAME, role, tokens, body, [c["id"] for c in via],
                         deadline_s=HD.ticket_deadline(120, wait), call_timeout_s=120,
                         priority=Loop._loop_head_priority(self, role),     # fac-53: every _light_ask is the loop's own work
                         floor=Loop._loop_head_floor(self))                 # fac-57: and never ages past the cards while READY is full
        except HD.HeadDown as error:
            self.event("infra", status="head_down", reason=str(error)[:100])
            if error.alive:          # W-bucket: a live head that did not answer in time: wait, never around it
                if why is not None:
                    why.update(reason="head_busy", wait_s=30.0)
                return "no_channel", None, "", tokens
            return None
        model = got.get("model") or via[0]["model"]
        if got.get("status") == 200:
            try:
                data = json.loads(got["body"])
                return "ok", model, data["choices"][0]["message"].get("content") or "", (data.get("usage") or {}).get("total_tokens") or tokens
            except (ValueError, KeyError, IndexError, TypeError, AttributeError):
                return "ok", model, "", tokens
        if got.get("expired") and got.get("status") not in (200, 400, 401, 403, 404):    # never sent in time: what held it
            held = got.get("held") or {}
            if why is not None:
                why.update(reason=str(held.get("reason") or "head"), wait_s=float(got.get("eta_s") or held.get("wait_s") or 0))
            return "head_expired", None, "", tokens
        return "http_%s" % got["status"], model, "", tokens

    def _start_head(self) -> None:
        """fac-40: start the one host of the small-tier calls (local only, a random port, a token in head.json beside
        channels.json). Any fault leaves the old path: nothing else depends on it."""
        try:
            from tools import factory_head as HD
            if not self.cfg.channels or not Path(self.cfg.channels).is_file():
                return
            path = Path(self.cfg.channels).resolve()
            rows = json.loads(path.read_text(encoding="utf-8"))["channels"]
            self._head, self._head_close = HD.serve(rows, {**os.environ, **self.extra_env}, path.parent / HD.STATE_NAME,
                                                    folder=path.parent / "quota",
                                                    log=lambda row: self.event("head_call", **row))   # one row per call
            self.event("infra", status="head_up", reason="head started")
        except Exception as e:  # noqa: BLE001 - the old path stands
            self.err("head start", e)

    def _keep_head(self) -> None:
        """W-bucket: the head's pump thread died (its pulse stops, callers take the old path): close it and start a new one,
        so the head never stays down until the loop restarts. A fault leaves the old path."""
        head = getattr(self, "_head", None)
        thread = getattr(head, "pump_thread", None)
        if head is None or thread is None or thread.is_alive():
            return
        try:
            self.event("infra", status="head_restart", reason="the head's pump stopped")
            if self._head_close is not None:
                self._head_close()
        except Exception as e:  # noqa: BLE001 - the restart below still runs
            self.err("head close", e)
        self._head = self._head_close = None
        self._start_head()

    def _slice_hopeless(self) -> bool:
        """W-gemma2 4: no paid step (no key, no agent) and every main channel closed by the day's mark: only Gemma is left."""
        try:
            asks = self._asks()
            if "paid" in asks or "agent" in asks:
                return False
            from tools import factory_channels as C
            from tools import factory_quota as Q
            channels = json.loads(Path(self.cfg.channels).read_text(encoding="utf-8"))["channels"]
            env = {**os.environ, **self.extra_env}
            folder = Path(self.cfg.channels).resolve().parent / "quota"
            seen = Q.view(self._arch_quotas or {}, Q.others(folder, "%s@%s" % ("loop-architect", self.ckpt)))
            return bool(C.main_dry(channels, seen, env, now=self.clock()))
        except Exception as e:      # an aid: on any doubt the usual pause stands
            self.err("slice hopeless", e)
            return False

    def _day_split(self, order, seen, env, folder, now) -> tuple:
        """W-gemma2 3: (open channels of ``order``, the channels the day's mark closes). The closed ones are the rows of the
        channel report closed by the daily mark and the ones a slicer ask saw refused for the day (day_gate.json of the
        shared folder: kept until a probe of theirs answers, so an expired mark does not open them for every ask)."""
        from tools import factory_channels as C
        from tools import factory_quota as Q
        if not order:
            return [], []
        rows = {r["id"]: r for r in C.channel_report(order, seen, env, now=now)}
        today = {c["id"]: C.quota_day(c["model"], now)[0] for c in order}
        held = Q.gate_closed(folder, since=today)
        closed, free = [], []
        for c in order:
            if rows[c["id"]]["closed_by"] in C.DAILY_CLOSED or c["id"] in held:
                closed.append(c)
                if c["id"] not in held:
                    try:
                        Q.gate_note(folder, c["id"], now=now)   # seen closed the first time: its first probe is 20 minutes away
                    except OSError as e:
                        self.err("day gate", e)
            else:
                free.append(c)
        return free, closed

    def _telemetry_rows(self):
        """The rows of telemetry.jsonl and .1 (a broken line is skipped), one at a time: fac-58, the loop's weight does not
        grow with the journals (a whole read of ~40 MB left the process at hundreds of MB for good)."""
        for name in (self.tel_path.name, self.tel_path.name + ".1"):
            try:
                with (self.dir / name).open(encoding="utf-8", errors="replace") as fh:
                    for line in fh:
                        try:
                            row = json.loads(line)
                        except ValueError:
                            continue
                        if isinstance(row, dict):
                            yield row
            except OSError:
                continue

    # -- the free head answers the mechanical holds (which file to change): at once when idle, when READY is
    # low after HOLDS_LOW_EVERY_S, else every 20 min. With live workers the asks run in the background thread.
    HOLDS_EVERY_S = 600             # 21.11 (was 1200)
    HOLDS_LOW_EVERY_S = 30        # READY below the pool: the next picks are not held back for the 20 minutes
    READY_FLOOR = 2               # the pool size taken for the READY-low rule when fewer workers are live
    _last_out = None

    def _ready_low(self) -> bool:
        try:
            state = self.load()[1]
        except Exception as e:
            self.err("ready count", e)
            return False
        ready = sum(1 for r in state["tasks"].values() if r.get("status") == "READY")
        return ready < max(self.READY_FLOOR, len(self.pool.workers))

    def _head_holds(self) -> None:
        """An empty READY queue with an unparsed backlog is the trigger of the next triage portion, not idleness. After
        an idle step (HOLD, DONE, an empty TRIAGE) at once; with READY below the pool size after HOLDS_LOW_EVERY_S;
        else at most once per HOLDS_EVERY_S (requeued tasks kept the loop busy and the head never ran). Up to three holds
        of the kinds 'ambiguous localisation' and 'which module' go to a free head model; a valid pick becomes an
        answer file (backlog_id, touch_files, tests, note) that apply_answers turns into a task. A private or unclean
        row is never sent. A fault never stops the loop."""
        from tools import factory_context as X
        from tools import factory_holds as H
        from tools import factory_requeue
        if self._bg is not None:                 # one background job at a time; the gate is not used up
            return
        out = self._last_out
        idle = out is not None and (out.action in ("HOLD", "DONE") or (out.action == "TRIAGE" and out.status == "empty"))
        try:
            ls = self.ls()
            since = self.clock() - float(ls.get("holds_at") or 0)
            if not idle and since < self.HOLDS_EVERY_S and not (since >= self.HOLDS_LOW_EVERY_S and self._ready_low()):
                return
            ls["holds_at"] = self.clock()
            done = ls.setdefault("head_holds", {})
            picked = H.select(ls.get("holds") or {}, done, self.clock())
            self.save_ls(ls)
            if picked and (self.pool.workers or (out is not None and not idle)):    # a runner works or work is about to start: no ask in this thread
                self._holds_prefetch(picked, ls, H, X, factory_requeue)
                return
            for bid, question in picked:
                try:
                    self._head_one(bid, question, H, X, factory_requeue)
                except Exception as e:
                    self.err("head_holds", e)
        except Exception as e:
            self.err("head_holds", e)

    def _head_record(self, bid, status, model=None, tokens=None) -> None:
        ls = self.ls()
        ls.setdefault("head_holds", {})[bid] = {"at": self.ts(), "status": status}
        self.save_ls(ls)
        self.event("head", backlog_id=bid, status=status, model=self.rs(model), tokens=tokens)

    def _head_one(self, bid, question, H, X, factory_requeue) -> None:
        prep = self._head_prep(bid, question, H, X)
        if "status" in prep:
            return self._head_record(bid, prep["status"])
        ls = self.ls()
        # attempt 1: the main tier first. Picking files among candidates is light work; the escalation tier (3.6 Flash,
        # 20 a day per key) stays for the coder's hard attempts and the hourly self-fix design
        got = self._light_ask(prep["prompt"], attempt=1, section="loop-holds",
                              quotas=ls.setdefault("holds_quotas", {}), max_tokens=800)
        self.save_ls(ls)
        return self._head_finish(bid, prep, got, H, factory_requeue)

    def _head_prep(self, bid, question, H, X) -> dict:
        """Reads only (the backlog text, the mirror): {'status': ...} when nothing is asked, else the prompt and the
        row's facts. Safe in the background thread."""
        goal, private, unclean = self._backlog_text(bid)
        if private or unclean:
            return {"status": "private"}
        kind = H.kind_of(question)
        files, tests = H.candidates(question)
        if kind == "ambiguous" and not tests:
            own = H.row_test(bid, self.mirror)
            tests = [own] if own else []
        if not files or (not tests and kind != "candidates"):    # <id>: the triage makes a candidates row's test
            return {"status": "no_test"}
        outlines = {}
        for rel in files:
            try:
                outlines[rel] = X.outline((self.mirror / rel).read_text(encoding="utf-8", errors="replace"), 1500,
                                          tools=False)
            except OSError:
                pass
        return {"kind": kind, "files": files, "tests": tests,
                "prompt": H.prompt(bid, goal, question, files, tests, outlines)}

    def _head_finish(self, bid, prep, got, H, factory_requeue) -> None:
        """The state side of a hold pick; the loop's own thread only."""
        def record(status, model=None, tokens=None):
            self._head_record(bid, status, model, tokens)
        kind, files, tests = prep["kind"], prep["files"], prep["tests"]
        status, model, answer, tokens = got
        if status != "ok":
            return record("later", model, tokens)
        picked = H.parse(answer, files, kind=kind)
        if picked is None:
            return record("invalid", model, tokens)
        if "skip" in picked:
            return record("skip", model, tokens)
        if "not_code" in picked:
            return self._book_not_code(bid, picked["not_code"], record, model, tokens)
        try:
            if picked["note"]:
                self._check_note(picked["note"])
        except F.InvalidPlan:
            return record("invalid", model, tokens)
        if kind == "candidates":
            # <id>: no answer file (it needs tests): the next triage takes the pick as the row's scope and makes the
            # normal unit_test + code pair through every check of the triage
            ls = self.ls()
            ls.setdefault("head_scope", {})[bid] = {"touch_files": picked["touch_files"], "note": picked["note"],
                                                    "at": self.ts()}
            ls["holds"].pop(bid, None)
            ls.get("hold_hash", {}).pop(bid, None)
            ls["seen"].pop(bid, None)
            ls["triage_empty"] = None
            self.save_ls(ls)
            return record("scoped", model, tokens)
        payload = {"backlog_id": bid, "touch_files": picked["touch_files"], "tests": tests}
        if picked["note"]:
            payload["note"] = picked["note"]
        factory_requeue._write_answer(self.dir / "answers", payload, "head-" + bid)
        record("answered", model, tokens)

    def _holds_prefetch(self, picked, ls, H, X, factory_requeue) -> bool:
        quotas = copy.deepcopy(ls.get("holds_quotas") or {})      # private: the loop's ledger is written in its thread

        def work():
            out = []
            for bid, question in picked:
                if self._bg_cancel.is_set():
                    break
                try:
                    prep = self._head_prep(bid, question, H, X)
                    got = None if "status" in prep else self._light_ask(
                        prep["prompt"], attempt=1, section="loop-holds", quotas=quotas, max_tokens=800)
                    out.append((bid, prep, got))
                except Exception as e:
                    out.append((bid, None, e))
            return out, quotas
        return self._bg_start("holds", work, (H, factory_requeue))

    def _holds_apply(self, job) -> None:
        if job.error is not None:
            return self.err("head_holds", job.error)
        results, quotas = job.result
        H, factory_requeue = job.ctx
        try:
            ls = self.ls()
            ls["holds_quotas"] = quotas
            self.save_ls(ls)
        except Exception as e:
            self.err("head_holds", e)
        for bid, prep, got in results:
            try:
                if prep is None:
                    raise got
                if "status" in prep:
                    self._head_record(bid, prep["status"])
                else:
                    self._head_finish(bid, prep, got, H, factory_requeue)
            except Exception as e:
                self.err("head_holds", e)

    # -- the background slot: ONE job in flight (a triage portion or the head's picks)
    def _bg_start(self, kind: str, work, ctx) -> bool:
        if self._bg is not None:
            return False
        job = self._bg = Prefetch(kind, work, ctx)
        job.thread.start()
        return True

    def _bg_poll(self) -> None:
        """Loop thread: a finished job is applied here (a triage error is raised here, as the synchronous one was)."""
        job = self._bg
        if job is None or not job.done.is_set():
            return
        self._bg = None
        if job.kind == "triage":
            self._triage_apply(job)
        else:
            self._holds_apply(job)

    def _book_not_code(self, bid, why, record, model, tokens) -> None:
        """<id>: the head model says the row is not a change of the code (owner process, proxy, server, laptop, phone):
        the not_code book keeps it with a reason and a term (cfg.not_code_term_s). Unlike ``seen`` it survives backlog
        edits: only a change of the row's own text (its hash) or the end of the term gives it a fresh look."""
        try:
            digest = self._row_hashes("text").get(bid)
        except Exception as e:
            self.err("not_code: backlog unreadable", e)
            digest = None
        if not digest:      # the model already answered: not "later" (asked again at once), the normal 24 h repeat
            return record("unbooked", model, tokens)
        ls = self.ls()
        self._not_code_set(ls, bid, why, digest)
        self.save_ls(ls)
        record("not_code", model, tokens)

    ARCH_ENGINES = ("paid", "agent")      # the architect's own steps: their no-fix decision outlives a slicer version

    def _not_code_set(self, ls, bid, why, digest, engine="") -> None:
        """The ONE writer of the not_code book (the head's answer and the triage's structural cut, <id>).  ``engine``
        is the step that decided; a paid/agent decision expires by the row's text or the term, not by the slicer."""
        ls.setdefault("not_code", {})[bid] = {
            "hash": digest, "reason": ("не код: " + self._scrub(F.redact(str(why))))[:200],
            "until": self.clock() + self.cfg.not_code_term_s, "slicer": F.slicer_version(), "engine": str(engine or "")}
        ls["holds"].pop(bid, None)
        ls.get("hold_hash", {}).pop(bid, None)

    def _decision_set(self, ls, bid, kind, why, engine, now) -> None:
        """The architect's no-fix answer (already_fixed / cannot_reproduce / duplicate_of:<ID> / hold / not_code) of a row, written WITH the
        slicer version: the row's tasks are superseded at the same moment, so the answer is what speaks for the row (reconcile shows it
        instead of the superseded tasks' FAILED).  It leaves with the hold / not_code record it belongs to (_expire_slicer_decisions)."""
        ls.setdefault("arch_decision", {})[bid] = {
            "decision": str(kind), "why": self._scrub(F.redact(str(why)))[:200], "slicer": F.slicer_version(),
            "engine": str(engine or ""), "at": now}

    def _not_code_known(self, ls, now) -> set:
        """Rows of the not_code book whose term is live and whose text is unchanged; the rest leave the book."""
        self._expire_slicer_decisions(ls)
        book = ls.get("not_code")
        if not isinstance(book, dict) or not book:
            return set()
        try:
            texts = self._row_hashes("text")
        except Exception as e:
            self.err("not_code: backlog unreadable", e)
            return set(book)                      # cannot compare: keep them known one more triage
        live = set()
        for bid, rec in list(book.items()):
            try:
                ok = isinstance(rec, dict) and float(rec.get("until") or 0) > now and texts.get(bid) == rec.get("hash")
            except (TypeError, ValueError):
                ok = False
            if ok:
                live.add(bid)
            else:
                book.pop(bid, None)
        return live

    # -- Opus answer box
    ANSWER_MAX_BYTES = 64 * 1024
    ANSWER_KEEP = 200
    ANSWER_MAX_AGE_S = 2 * F.LEASE_LIFETIME_S   # an answer to an orphaned RUNNING task outlives its lease
    NO_RESULT_PARK = ESCALATE_AFTER   # the runner's own 'N times in a row' (no second constant)
    REQUEUE_PARK = ESCALATE_AFTER
    MERGE_RETRY_MAX = 5      # W-optim fix2: a contract card goes back to READY on a merge conflict at most so often in a row

    def apply_answers(self) -> int:
        box = self.dir / "answers"
        if not box.is_dir():
            self._known_names = set()
            return 0
        done = 0
        names0 = {f.name for f in box.glob("*.json")}   # the list BEFORE we touch anything
        ls = self.ls()
        applied = list(ls.get("answers_applied") or [])
        since = dict(ls.get("answer_since") or {})
        for k, v in self._since_mem.items():
            since[k] = min(v, since.get(k, v))
        since = {k: v for k, v in since.items() if (box / k).exists()}
        merged = dict(ls.get("answer_tries") or {})
        for k, v in self._tries_mem.items():  # memory keeps the limit when the save fails
            merged[k] = max(v, merged.get(k, 0))
        tries = {k: v for k, v in merged.items() if (box / k).exists()}
        for f in sorted(box.glob("*.json")):
            if f.name in applied:  # applied before, only the move failed
                self._answer_move(f, "done")
                continue
            try:
                if f.stat().st_size > self.ANSWER_MAX_BYTES:
                    raise F.InvalidPlan("answer file is larger than 64 KB")
                ans = json.loads(f.read_text(encoding="utf-8"))
                if not isinstance(ans, dict):
                    raise ValueError("answer is not an object")
                info = self._apply_one(ans)
            except (_Later, OSError) as e:
                tries[f.name] = tries.get(f.name, 0) + 1
                since.setdefault(f.name, self.clock())
                if self.clock() - since[f.name] > self.ANSWER_MAX_AGE_S:  # only age rejects
                    tries.pop(f.name, None)
                    since.pop(f.name, None)
                    self._answer_move(f, "rejected", "deferred too long: " + F.redact(str(e))[:200])
                    self.event("answer", status="rejected", reason="deferred too long: "
                               + F.redact(str(e))[:200], file=f.name)
                else:
                    self.event("answer", status="deferred", reason=F.redact(str(e))[:200],
                               file=f.name, attempt=tries[f.name])
            except Exception as e:
                why = "%s: %s" % (type(e).__name__, F.redact(str(e))[:300])
                tries.pop(f.name, None)
                self._answer_move(f, "rejected", why)
                self.event("answer", status="rejected", reason=why, file=f.name)
            else:
                tries.pop(f.name, None)
                applied = (applied + [f.name])[-50:]
                try:
                    ls = self.ls()
                    ls["answers_applied"], ls["answer_tries"] = applied, tries
                    self.save_ls(ls)
                except OSError as e:
                    self.err("answers_applied save", e)
                self._answer_move(f, "done")
                self.event("answer", status="applied", file=f.name, **info)
                done += 1
        self._tries_mem = dict(tries)
        self._since_mem = dict(since)
        try:
            ls = self.ls()
            ls["answers_applied"], ls["answer_tries"], ls["answer_since"] = applied, tries, since
            self.save_ls(ls)
        except OSError as e:
            self.err("answer counters save", e)
        for sub in ("done", "rejected"):
            self._rotate(box / sub)
        self._known_names = names0  # files that appeared meanwhile are not known: they wake us
        if done:
            try:
                tasks, state = self.load()
                self._write_questions(tasks, state, self.ls())
            except Exception as e:
                self.err("questions after answers", e)
        return done

    def _rotate(self, d: Path) -> None:
        try:
            files = sorted(p for p in d.glob("*.json")) if d.is_dir() else []
            for old in files[:-self.ANSWER_KEEP] if len(files) > self.ANSWER_KEEP else []:
                old.unlink(missing_ok=True)
                old.with_name(old.name + ".reason.txt").unlink(missing_ok=True)
        except OSError as e:
            self.err("answer rotate", e)

    def _answer_move(self, f: Path, sub: str, reason: str | None = None) -> None:
        try:
            dest = f.parent / sub
            dest.mkdir(exist_ok=True)
            target = dest / f.name
            retry_fs(os.replace, f, target)
            if reason:
                target.with_name(f.name + ".reason.txt").write_text(self._scrub(reason) + "\n", encoding="utf-8")
        except OSError as e:
            self.err("answer move", e)

    def _apply_one(self, ans: dict) -> dict:
        from tools import factory_gate
        try:
            tasks, state = self.load()
        except Exception as e:
            raise _Later("state unreadable: %s" % type(e).__name__) from e
        tid, bid = ans.get("task_id") or "", ans.get("backlog_id") or ""
        raw_note = str(ans.get("note") or "")             # the privacy check sees the RAW note
        note = F.redact(raw_note).strip()
        new_subtask = ans.get("kind") == "unit_test" and not tid
        if not tid and bid and not new_subtask:  # a new unit_test sub-task never rewrites the main one
            cands = [t for t, r in state["tasks"].items() if r.get("backlog_id") == bid]
            if ans.get("close") and len(cands) > 1:
                raise F.InvalidPlan("several tasks share %s (%s): give --task-id" % (
                    bid, ", ".join(cands[:5])))
            want_unit = any(str(x).startswith("tests/") for x in (ans.get("touch_files") or []))
            cands.sort(key=lambda t: (getattr(tasks.get(t), "kind", "code") == "unit_test") != want_unit)
            tid = cands[0] if cands else ""
        fields = {k: ans.get(k) for k in ("touch_files", "tests", "read_files",
                                           "context_targets", "depends_on", "port_from", "contract")
                  if ans.get(k) is not None}
        kind = tasks[tid].kind if tid in tasks else (ans.get("kind") or "code")
        if ans.get("package"):
            return self._package_answer(Path(ans["package"]), bid, note)
        if ans.get("accept"):
            return self._accept_answer(tid, bid, state, note)
        if ans.get("reject"):
            if tid in tasks and note and tasks[tid].privacy_safe and not tasks[tid].only_opus:
                self._check_note(raw_note)
            return self._reject_answer(tid, bid, state, note, revert=bool(ans.get("revert")))
        if ans.get("close"):
            return self._close_answer(ans, tid, bid, tasks, state, note)
        for path in fields.get("touch_files") or []:  # the one rule, here and in the CLI
            why = factory_gate.is_forbidden(path, kind)
            if why:
                raise F.InvalidPlan("%s: %s" % (path, why))
        if tid and tid in tasks and note and tasks[tid].privacy_safe and not tasks[tid].only_opus:
            self._check_note(raw_note)  # a public task's note goes into the external prompt
        if tid:
            if tid not in tasks:
                raise F.InvalidPlan("unknown task " + tid)
            status = state["tasks"][tid]["status"]
            if status in ("RUNNING", "REVIEW"):
                raise _Later("task is %s" % status)
            if status in ("DONE", "PROMOTED"):
                raise F.InvalidPlan("task is already %s: nothing to answer" % status)
            if ans.get("goal"):
                fields["goal"] = self._public_goal(ans["goal"])
            if not fields and not note:
                raise F.InvalidPlan("empty answer: nothing to change")
            if fields:
                try:
                    F.amend_task(self.plan_path, tid, **fields)
                except F.InvalidPlan as e:
                    if "locked" in str(e) or "RUNNING" in str(e) or "REVIEW" in str(e):
                        raise _Later(str(e)) from e
                    raise
            with self.txn() as (tasks, state):
                row = state["tasks"][tid]
                if row["status"] in ("BLOCKED", "FAILED"):
                    F.unblock(state, tid, note or "Opus: повторить попытку")
                    action = "unblocked"
                else:  # unblock writes the note itself; any other status keeps it as feedback
                    self._drop_pending(row)  # a fresh instruction invalidates the parked review
                    if note:
                        F.add_feedback(state, tid, "opus", note)
                    action = "amended" if fields else "feedback"
            ls = self.ls()
            if bid and ls["holds"].pop(bid, None) is not None:
                self.save_ls(ls)
            return {"task_id": tid, "backlog_id": bid or row.get("backlog_id"), "reason": action}
        if not bid or not ans.get("touch_files") or not ans.get("tests"):
            raise F.InvalidPlan("no such task: backlog_id with touch_files and tests is needed")
        from tools import agent_factory_import as imp
        base = imp._task_id(bid)[:56]
        new_id, n = base, 1
        while new_id in tasks:
            n += 1
            new_id = "%s_o%d" % (base, n)
        row = {"id": new_id, "title": ("Opus: " + bid)[:200],
               "touch_files": list(ans["touch_files"]), "tests": list(ans["tests"]),
               "read_files": list(ans.get("read_files") or []),
               "context_targets": dict(ans.get("context_targets") or {}),
               "depends_on": list(ans.get("depends_on") or []), "backlog_id": bid,
               "estimated_tokens": 4000, "priority": 1}
        if ans.get("contract") is not None:
            row["contract"] = ans["contract"]
        if ans.get("port_from"):
            row["port_from"] = str(ans["port_from"])
        if ans.get("kind") == "unit_test":
            row["kind"] = "unit_test"
        goal, private, unclean, known = self._backlog_row(bid)
        released_row = False
        internal = private or unclean
        if ans.get("goal"):
            # 21.11: the manual release is for a row private BY CONTENT (the narrowed class: keys, passwords, tokens,
            # .env, SECRETS_LOCAL, call recordings and logs); an unknown id carries none: Opus' goal is checked below
            if private and known and not ans.get("release_private"):
                raise F.InvalidPlan("row %s is private: a public --goal needs "
                                    "--release-private" % bid)
            # Opus' own technical wording (checked: no owner words/quotes/times/secrets) replaces a
            # row that left residue (or, released explicitly, a private one): THIS text only goes out
            goal, internal = self._public_goal(ans["goal"]), False
            if private:
                released_row = True
        # same rule as the triage otherwise: a private row, or a row with residue and no clean
        # goal, stays internal (only_opus, never sent to an external model)
        row["privacy_safe"], row["only_opus"] = not internal, internal
        if goal and not internal:
            row["goal"] = goal
        if note and not internal:
            self._check_note(raw_note)          # BEFORE the task exists: a refused answer creates nothing
        added = F.append_tasks(self.plan_path, [row])
        if not added:
            raise F.InvalidPlan("not added: " + str((getattr(added, "skipped", None) or [{}])[0].get("reason")))
        if note:
            self._tx(lambda st: F.add_feedback(st, new_id, "opus", note))
        ls = self.ls()
        ls["holds"].pop(bid, None)
        self.save_ls(ls)
        info = {"task_id": new_id, "backlog_id": bid, "reason": "created"}
        if ans.get("goal") and ans.get("release_private"):
            info["release_private"] = True
        return info

    def _park(self, tid: str, reason: str, note: str) -> None:
        """BLOCKED with a whitelisted reason (agent_factory.park): Opus sees it in opus_questions.md."""
        try:
            with self.txn() as (tasks, state):
                parked = state["tasks"][tid]["status"] in ("READY", "RUNNING", "REVIEW")
                if parked:
                    self._drop_pending(state["tasks"][tid])   # its work copy stays in staging otherwise
                    F.park(state, tid, reason, note, now=self.clock())
            if parked:
                self.event("infra", task_id=tid, status="parked", reason=reason)
        except Exception as e:
            self.err("park " + tid, e)

    @staticmethod
    def _clear_requeues(ls: dict, tid: str) -> None:
        ls.get("requeues", {}).pop(tid, None)

    def _drop_pending(self, row: dict) -> None:
        """Forget a parked review; delete its work copy only when it is STRICTLY inside staging
        (the runner's own check: staging itself, '', '.', outside paths and non-dicts are ignored)."""
        row.pop("candidate", None)
        pend = row.pop("pending_review", None)
        if not isinstance(pend, dict):
            return
        work = pend.get("workdir")
        if not isinstance(work, str) or not work.strip():
            return
        try:
            from tools.agent_factory_runner import inside_staging
            if inside_staging(work, self.stage):
                shutil.rmtree(Path(work), ignore_errors=True)
        except Exception as e:
            self.err("pending copy cleanup", e)

    def _accept_answer(self, tid, bid, state, note) -> dict:
        """ACCEPTED = taken by the coordinator (an explicit answer). PROMOTED only says the candidate is merged."""
        if not tid or tid not in state["tasks"]:
            raise F.InvalidPlan("accept needs a known task (--task-id)")
        status = state["tasks"][tid]["status"]
        if status != "PROMOTED":
            raise F.InvalidPlan("only a PROMOTED task can be accepted (it is %s)" % status)
        ls = self.ls()
        if not isinstance(ls.get("accepted"), dict):
            ls["accepted"] = {}
        if tid in ls["accepted"]:
            raise F.InvalidPlan("task %s is already accepted" % tid)
        ls["accepted"][tid] = {"at": self.ts(), "note": self._scrub(F.redact(note))[:200]}
        self.save_ls(ls)
        bid = bid or state["tasks"][tid].get("backlog_id")
        self.event("accept", task_id=tid, backlog_id=bid, status="accepted", reason="accepted_by_coordinator")
        self._write_closure(tid, bid, state["tasks"][tid])
        return {"task_id": tid, "backlog_id": bid, "reason": "accepted"}

    def _write_closure(self, tid, bid, row, how="accepted") -> None:
        """<id>: an ACCEPTED (coordinator) or PROMOTED (merged by the loop) ECHO task goes into the backlog's closures table
        (one atomic idempotent writer); fac-* only by the second (self-repo) instance, ECHO rows only by the first, and a row
        without a commit sha never (closed by the head, a duplicate)."""
        sha = row.get("commit")
        if not bid or not sha or str(bid).lower().startswith("fac-") != self.cfg.self_repo:
            return
        try:
            note = "free loop, merged by the loop (not yet taken)" if how == "promoted" else "free loop, accepted by the coordinator"
            res = factory_closures.record_closure(self.cfg.backlog, bid, str(sha), note)
            self.event("closure", task_id=tid, backlog_id=bid, status=res, reason=how)
        except Exception as e:
            self.err("closure", e)

    def _sweep_dir(self) -> Path:
        from tools import factory_autofeed as AF
        return AF.factory_dir(self.cfg.worktree) or Path(self.cfg.state_dir)

    def _sync_ready_tick(self, now) -> str:
        """The second instance's branch falls behind factory/ready-*: merge it in (a plain three-way ``git merge`` in the worktree)
        at the start of the work and then once an hour while nothing RUNS. A conflict is aborted and ends as one line in the
        report (event ``sync``, status ``conflict``); the work goes on on the branch as it is. Never raises; returns the status."""
        cfg = self.cfg
        if not cfg.sync_ref or self.pool.workers:
            return ""
        try:
            ls = self.ls()
            last = ls.get("ready_sync") or {}
            if last and now - float(last.get("at", 0)) < cfg.sync_every_s:
                return ""
            _tasks, state = self.load()
            if any(r.get("status") == "RUNNING" for r in state["tasks"].values()):
                return ""
            ls["ready_sync"] = {"at": now}       # a fault or a conflict also waits for the next hour
            self.save_ls(ls)
            wt = Path(cfg.worktree)
            status, line = "up_to_date", ""
            try:
                git_run(wt, "rev-parse", "--verify", "--quiet", cfg.sync_ref + "^{commit}")
                on = git_run(wt, "rev-parse", "--abbrev-ref", "HEAD").strip()
                if on != cfg.branch:
                    status, line = "skipped", "the worktree is on %s, not %s" % (on, cfg.branch)
                elif git_run(wt, "status", "--porcelain", "--untracked-files=no").strip():
                    status, line = "skipped", "the worktree has uncommitted changes"
                else:
                    try:
                        git_run(wt, "merge-base", "--is-ancestor", cfg.sync_ref, "HEAD")
                    except subprocess.CalledProcessError:
                        before = git_run(wt, "rev-parse", "HEAD").strip()
                        try:
                            git_run(wt, "-c", "user.name=factory-loop", "-c", "user.email=factory-loop",
                                    "merge", "--no-edit", "-m", "merge %s into %s" % (cfg.sync_ref, cfg.branch), cfg.sync_ref)
                            status = "merged"
                            line = "%s -> %s" % (before[:8], git_run(wt, "rev-parse", "HEAD").strip()[:8])
                        except subprocess.CalledProcessError as error:
                            files = git_run(wt, "diff", "--name-only", "--diff-filter=U").split()
                            try:
                                git_run(wt, "merge", "--abort")
                            except subprocess.CalledProcessError:
                                git_run(wt, "reset", "--merge")
                            status = "conflict"
                            line = "merge of %s into %s conflicts: %s" % (
                                cfg.sync_ref, cfg.branch, ", ".join(files[:8]) or F.redact(str(getattr(error, "stderr", "") or error))[:200])
            except subprocess.CalledProcessError as error:
                status, line = "skipped", F.redact(str(getattr(error, "stderr", "") or ""))[:200] or "git %s failed: ref %s missing?" % (
                    error.cmd[-1] if getattr(error, "cmd", None) else "", cfg.sync_ref)
            self.event("sync", status=status, reason=self.rs(line, 300), ref=cfg.sync_ref)
            return status
        except Exception as error:      # noqa: BLE001  the sync never stops the loop
            try:
                self.event("sync", status="error", reason=self.rs("%s: %s" % (type(error).__name__, error), 300))
            except Exception:           # noqa: BLE001
                pass
            return "error"

    def _sweep_tick(self, now) -> None:
        """Red-guard supply (the triage reads guard_sweep_<date>.json): (1) a finished cloud sweep is booked; (2) at most once a
        minute the newest sweep is refreshed from the tasks' own results (promoted guards go green, a fresh red base joins);
        (3) when the base SHA moved or the sweep is old, ONE cloud sweep starts in the background (own slot, no wait here)."""
        try:
            from tools import factory_autofeed as AF
        except ImportError:          # the public mirror withholds the feed module (backlog ids): no red-guard supply there
            return
        try:
            ls = None
            job = self._sw
            if job is not None and job.done.is_set():
                self._sw = None
                ls = self.ls()
                rec = dict(ls.get("sweep") or {})
                if job.error is None:
                    rec["failed_at"] = 0
                    self.event("sweep", status="done", dur_s=round(job.dur_s, 3), reason="cloud sweep written", base_sha=rec.get("sha"))
                else:
                    rec = dict(rec.get("prev") or {}, failed_at=now)
                    self.event("sweep", status="failed", dur_s=round(job.dur_s, 3), reason=F.redact(str(job.error))[:200])
                rec.pop("prev", None)
                ls["sweep"] = rec
                self.save_ls(ls)
            sw_dir = self._sweep_dir()
            if now - self._sw_refresh_at >= 60 and sw_dir.is_dir() and AF.latest_sweep(sw_dir) is not None:
                self._sw_refresh_at = now
                swat = float((self.ls().get("sweep") or {}).get("at") or 0)
                mt = self.ls().get("merged_at") or {}
                newer = [t for t, v in mt.items() if isinstance(v, (int, float)) and swat and v > swat] if isinstance(mt, dict) else []
                if newer:       # W-tick 3: with nothing merged since the sweep there is nothing to refresh: no state read, no sweep file read
                    try:
                        tasks, state = self.load()
                    except Exception as e:      # a busy plan lock: the refresh waits for the next minute, it is no fault
                        if type(e).__name__ != "LockBusy":
                            raise
                        return
                    rows = {tid: {"status": r.get("status"), "tests": list(tasks[tid].tests) if tid in tasks else [],
                                  "base_red": r.get("base_red")} for tid, r in state["tasks"].items()}
                    got = AF.refresh_from_tasks(self._sweep_dir(), rows, merged_after=newer)     # W-refresh 1: red only from the cloud sweep
                    if got and (got["green"] or got["red"]):
                        self.event("sweep", status="refreshed", reason="green=%d red=%d" % (len(got["green"]), len(got["red"])))
            if not self._ending():
                try:
                    self._guard_red_tick(now, AF)
                except Exception as e:      # W-echo 1: the invariant never stops the sweep
                    self.err("guard red", e)
                try:
                    self._outdated_tick(now)
                except Exception as e:      # W-prio 3: an aid, it never stops the sweep
                    self.err("outdated tests", e)
            if self.sweep_fn is None or self._sw is not None or self._ending():
                return
            ls = self.ls()
            out = self._sweep_dir()
            latest = AF.latest_sweep(out) if out.is_dir() else None
            stale_ids = (latest is not None and AF.sweep_lacks_ids(latest) and ls.get("ids_sweep_sha") != self.base_sha     # W-refresh 2: once per base
                         and now - float((ls.get("sweep") or {}).get("failed_at") or 0) >= AF.SWEEP_BACKOFF_S)
            if not stale_ids and not AF.sweep_due(ls.get("sweep"), self.base_sha, now, self.cfg.sweep_every_s):
                return          # W-guardid 2: a sweep without red_ids is stale (once; after a failure not before an hour)
            prev = sorted(AF.read_sweep(latest)) if latest is not None else []
            ls["sweep"] = {"sha": self.base_sha, "at": now, "prev": dict(ls.get("sweep") or {})}
            ls["ids_sweep_sha"] = self.base_sha
            self.save_ls(ls)
            fn, wt = self.sweep_fn, self.cfg.worktree
            self._sw = Prefetch("sweep", lambda: AF.run_cloud_sweep(fn, wt, out, previous=prev), {})
            self._sw.thread.start()
            self.event("sweep", status="started", reason="cloud sweep of %d guard files" % len(prev), base_sha=self.base_sha)
        except Exception as e:
            self.err("sweep", e)

    def _links_tick(self, now) -> None:
        """4.2 (<id>, <id>, <id>): every LINKS_EVERY_S, when OWNER_WORDS.md grew, ONE background job links the new entries to
        backlog rows (factory_intake.run_links; the small free tier first, role review; private chunks never leave).  The loop's
        own thread only starts it and books the count of unlinked requirements into reconcile.json."""
        if self.cfg.self_repo:
            return          # W-hypo3 4: the owner's words and the closures audit belong to the product instance only
        try:
            from tools import backlog_register as B
            from tools import factory_intake as I
        except ImportError:
            return          # the mirror (cloud matrix) does not carry the product's modules: nothing to link there, not an error
        try:
            job = self._lk
            if job is not None and job.done.is_set():
                self._lk = None
                if job.error is not None:
                    self.event("links", status="failed", dur_s=round(job.dur_s, 3), reason=F.redact(str(job.error))[:200])
                else:
                    data = job.result or {}
                    self._links_note(len(data.get("unlinked") or []))
                    self._audit_reopened(data.get("reopened") or {})
                    self.event("links", status="partial" if data.get("partial") else "done", dur_s=round(job.dur_s, 3), reason="linked rows=%d unlinked=%d" % (
                        len(data.get("links") or {}), len(data.get("unlinked") or [])))
            if self._lk is not None or self._ending() or now - self._lk_at < LINKS_EVERY_S:
                return
            words = next((c for c in B.OWNER_WORDS_CANDIDATES if c.exists()), None)
            if words is None or words.stat().st_size == self._lk_size:
                return
            self._lk_at, size = now, words.stat().st_size
            md = Path(self.cfg.backlog).read_bytes().decode("utf-8-sig")
            from tools import agent_factory_import as imp
            try:
                rows = {r["backlog_id"]: str(r.get("text") or "")[:200] for r in imp.parse_section4(md)}
            except ValueError:
                return      # a backlog without a bounded section 4 has no rows to link to: nothing to do, not an error
            if not rows:
                return
            out = words.parent / "owner_links.json"

            def ask(prompt):
                status, _, answer, _ = self._light_ask(prompt, attempt=1, section="loop-links", quotas=self._lk_quotas, max_tokens=300, role="aux", thrifty=True)
                if status != "ok":
                    raise RuntimeError("links: no answer (%s)" % status)    # run_links stops here and resumes from this entry
                return answer

            def work():
                data = I.run_links(words, rows, out, ask=ask, scrub=I.scrub)
                done = all(e["line"] <= int(data.get("upto_line") or 0) for e in I._entries(words)[0]); self._lk_size = size if done else self._lk_size; data = {**data, "partial": not done}
                audited = I.audit_closed_rows(self.cfg.backlog, out, lambda p, n: self._light_ask(p, attempt=n, section="loop-links", quotas=self._lk_quotas, max_tokens=300, role="aux", thrifty=True)[:3], I.scrub, self._commit_has_code)
                return {**data, "reopened": {b: str(r.get("why") or "") for b, r in (audited or {}).items() if r.get("reopened")}}
            self._lk = Prefetch("links", work, {})
            self._lk.thread.start()
        except Exception as e:
            self.err("links", e)

    def _audit_reopened(self, reopened: dict) -> None:
        """W-echo 4: a row two different models called not_done is open again in the backlog (FC.reopen): it also goes to to_slice with
        the audit's why as its text, and leaves the loop's closed book / holds, so the closure is not believed any more."""
        if not reopened or self.cfg.self_repo:      # W-hypo3 4: only the product instance reopens rows by the audit
            return
        ls, now = self.ls(), self.clock()
        for bid, why in sorted(reopened.items()):
            for key in ("closed", "holds", "hold_ver", "hold_hash", "hold_arch", "arch_decision", "not_code", "slice_wait", "reslices"):
                if isinstance(ls.get(key), dict):
                    ls[key].pop(bid, None)
            ls.setdefault("to_slice", {}).setdefault(bid, {"at": now, "hints": [], "guard": "", "text": self.rs(why, 300) or "not_done"})
            self.event("supply", status="audit_reopened", backlog_id=bid, reason=self.rs(why, 200) or "not_done")
        self.save_ls(ls)

    def _commit_has_code(self, sha) -> bool:
        """W-hypo3 4: the commit changed a .py file (the audit judges a triage-proof closure only then)."""
        out = git_run(self.cfg.repo, "show", "--name-only", "--format=", str(sha))
        return any(line.strip().endswith(".py") for line in out.splitlines())

    def _links_note(self, unlinked: int) -> None:
        self._lk_unlinked = unlinked          # written into reconcile.json by _write_reconcile_now

    def _release_tick(self, now) -> None:
        """The final build (5.1): (1) a finished build is judged here, in the loop's thread: the merged rows are accepted, a new red
        test becomes an urgent row; (2) with none in flight and one due (REL.due) a full cloud sweep starts in its OWN slot, so the pool
        goes on.  A build that did not end or failed leaves the record as it was and is repeated after REL.RETRY_S."""
        try:
            from tools import factory_release as REL
        except ImportError:
            return
        try:
            job = self._rel
            self._release_note_run()
            if job is not None and job.done.is_set():
                self._release_note_run()    # a note set after the first look (the job may have failed right after it)
                self._rel, self._rel_snap = None, None
                self._release_done(job, now, REL)
            if self.release_fn is None or self._rel is not None or self._ending() or not self.base_sha:
                return
            ls = self.ls()
            if REL.due(ls, now):
                self._release_start(ls, now, REL)
        except Exception as e:
            self.err("release", e)

    def _bisect_tick(self, now) -> None:
        """W-bisect: the history search of the baseline debt (tools.factory_bisect).  (1) a finished step is booked here; (2) READY
        cards of a row whose regression is now proven, cut without the proof, go back to the slicer; (3) with no step in flight, no
        final build and places over the cards' need, the next cloud run starts in its OWN slot (never two at once)."""
        try:
            from tools import factory_bisect as BIS
        except ImportError:
            return
        try:
            job = self._bis
            if job is not None and job.done.is_set():
                self._bis = None
                self._bisect_done(job, now, BIS)
            self._bisect_requeue(BIS)
            if self.bisect_fn is None or self._bis is not None or self._rel is not None or self._ending() or not self.base_sha:
                return
            self._bisect_start(now, BIS)
        except Exception as e:
            self.err("bisect", e)

    def _bisect_start(self, now, BIS) -> None:
        from tools import factory_release as REL
        ls = self.ls()
        if now < float(ls.get("bisect_retry_at") or 0):
            return
        state_dir = self.cfg.state_dir
        by_file = {f: [str(t) for t in r["tests"]] for f, r in REL.debt(state_dir).items() if not r.get("closed") and r.get("tests")}
        if not by_file or not BIS.pending(state_dir, by_file):
            return
        shards = REL.shards_for(self._release_places())
        if not shards and not BIS.has_run(state_dir):       # the cards come first: a run in flight holds its own places
            return
        commits = None
        if not BIS.load(state_dir)["commits"]:
            commits = BIS.history(lambda *a: git_run(self.cfg.repo, *a), self.base_sha)
        shutil.rmtree(self.dir / "bisect_snap", ignore_errors=True)     # leftovers of a dead process: nothing reads them now
        fn = self.bisect_fn
        self._bis = Prefetch("bisect", lambda: fn(
            state_dir=state_dir, tests_by_file=by_file, commits=commits, snapshot_fn=self._bisect_snapshot,
            free_fn=lambda p: shutil.rmtree(p, ignore_errors=True), diff_fn=self._bisect_diff, shards=max(shards, 1)), {})
        self._bis.thread.start()
        self.event("bisect", status="started", base_sha=self.base_sha, reason="history search: %d debt file(s)" % len(by_file))

    def _bisect_done(self, job, now, BIS) -> None:
        ls = self.ls()
        res = job.result if isinstance(job.result, dict) else {}
        if job.error is not None:
            ls["bisect_retry_at"] = now + BIS.RETRY_S
            self.save_ls(ls)
            self.event("bisect", status="failed", dur_s=round(job.dur_s, 3), reason=F.redact(str(job.error))[:200])
            return
        if ls.pop("bisect_retry_at", None) is not None:
            self.save_ls(ls)
        self.event("bisect", status=res.get("status") or "point", dur_s=round(job.dur_s, 3), sha=str(res.get("sha") or "")[:12] or None,
                   phase=res.get("phase") or None, more=bool(res.get("more")), reason=str(res.get("reason") or "")[:200] or None,
                   **{"bisect_" + k: v for k, v in BIS.counts(self.cfg.state_dir).items()})

    def _bisect_snapshot(self, sha) -> Path:
        """The tree of a commit of the working branch (git archive; the sweep's scanner reads it like any snapshot)."""
        root = self.dir / "bisect_snap"
        target = root / str(sha)[:12]
        shutil.rmtree(target, ignore_errors=True)
        target.mkdir(parents=True)
        archive = root / (str(sha)[:12] + ".tar")
        try:
            with archive.open("wb") as fh:
                subprocess.run(["git", "-C", str(self.cfg.repo), "archive", str(sha)], stdout=fh, stderr=subprocess.PIPE, check=True)
            with tarfile.open(archive) as tar:
                tar.extractall(target, filter="data")
        finally:
            archive.unlink(missing_ok=True)
        return target

    def _bisect_diff(self, green, red):
        """(changed files, the diff) between two commits of the working branch."""
        files = git_run(self.cfg.repo, "diff", "--name-only", str(green), str(red)).split("\n")
        return [f.strip() for f in files if f.strip()], git_run(self.cfg.repo, "diff", "--no-color", str(green), str(red))

    def _bisect_requeue(self, BIS) -> None:
        """W-bisect 4: the READY cards of a debt row whose regression is proven and whose cards were cut without that proof go back
        to the slicer (FAILED reslice:stale: no strike, the slicer's free retry); cards of a row with a worker on it stay."""
        state_dir = self.cfg.state_dir
        rows = {r for r, k in BIS.row_kinds(state_dir).items() if k == "regression"}
        if not rows:
            return
        sliced = self.ls().get("bisect_sliced") or {}
        want = {r for r in rows if (key := BIS.row_key(state_dir, r)) and sliced.get(r) != key}
        if not want:
            return
        tasks, state = self.load()
        rec = state["tasks"]
        busy = {F.row_of(t.backlog_id or tid) for tid, t in tasks.items() if rec[tid]["status"] in ("RUNNING", "REVIEW")}
        cards = [tid for tid, t in tasks.items() if F.row_of(t.backlog_id or tid) in want - busy and rec[tid]["status"] == "READY"
                 and not F.is_terminal(rec[tid].get("reason"))]
        if not cards:
            return
        with self.txn() as (_tasks, st):
            for tid in cards:
                if st["tasks"][tid]["status"] == "READY":
                    st["tasks"][tid].update(status="FAILED", reason="reslice:stale")
        self.event("bisect", status="requeued", reason="cards cut without the proof go back to the slicer: " + ",".join(sorted(
            {F.row_of(tasks[t].backlog_id or t) for t in cards}))[:200], count=len(cards))

    NO_ANSWER_TAIL = "no answer"

    def _unburn_no_answer(self) -> int:
        """W-vgs3 2: once at the start (event supply status=unburned, id of the card): cards that went red only because the ensemble
        got no answer at all (503) -- FAILED reslice / gate:part_failed, or READY with the last feedback ending «no answer» -- go
        back to READY (a card a new generation superseded is not touched); the reds and strikes of that text are taken off, those
        feedback lines dropped, and the row's to_slice / slice_wait record they caused is removed. A second start changes nothing."""
        if self.ls().get("unburned_no_answer"):
            return 0
        done: list = []
        with self.txn() as (tasks, st):
            for tid, row in st["tasks"].items():
                items = list(row.get("feedback") or [])
                if not items or F.is_terminal(row.get("reason")):
                    continue
                if not str(items[-1].get("text", "")).rstrip().endswith(self.NO_ANSWER_TAIL):
                    continue
                if not (row.get("status") == "READY" or
                        (row.get("status") == "FAILED" and row.get("reason") in ("reslice", "gate:part_failed"))):
                    continue
                bad = [x for x in items if str(x.get("text", "")).rstrip().endswith(self.NO_ANSWER_TAIL)]
                row["feedback"] = [x for x in items if x not in bad]
                row["reds"] = max(0, int(row.get("reds", 0)) - len(bad))
                bid = row.get("backlog_id") or (tasks[tid].backlog_id if tid in tasks else "")
                key = "bl:" + bid if bid else "task:" + tid
                strikes = st.setdefault("strikes", {})
                if key in strikes:
                    strikes[key] = max(0, int(strikes[key]) - len(bad))
                    if not strikes[key]:
                        strikes.pop(key)
                if row.get("status") == "FAILED":
                    row.update(status="READY", lease=None, deadline=None, attempts=max(0, int(row.get("attempts", 0)) - len(bad)))
                    row.pop("reason", None)
                done.append((tid, F.row_of(bid or tid)))
        ls = self.ls()
        for _tid, bid in done:
            for key in ("to_slice", "slice_wait"):
                (ls.get(key) or {}).pop(bid, None)
        ls["unburned_no_answer"] = True
        self.save_ls(ls)
        for tid, bid in done:
            self.event("supply", status="unburned", task_id=tid, backlog_id=bid, reason="no answer of the ensemble: back to READY")
        return len(done)

    def _unblock_short_chain(self) -> int:
        """W-rev 2: once at the start (event supply status=unblocked, id of the card): cards a short review chain BLOCKED
        (blocked_reason review_chain_short, 24.11) go back to READY -- a short chain is a wait now. A second start changes nothing."""
        if self.ls().get("unblocked_short_chain"):
            return 0
        with self.txn() as (_tasks, st):
            done = RW.unblock_short_chain(st, F.unblock)
        ls = self.ls()
        ls["unblocked_short_chain"] = True
        self.save_ls(ls)
        for tid in done:
            self.event("supply", status="unblocked", task_id=tid, reason="review_chain_short: a short chain is a wait now")
        return len(done)

    def _guard_of_row(self, row, ls):
        """W-guard 2: the guard test of a row: its to_slice entry's, else the red test of the newest sweep whose file is the row's
        guard file (test_v_<ID>.py); '' when the row has none (a rel-<sha> row's own guard is the regression book's)."""
        entry = (ls.get("to_slice") or {}).get(row) or {}
        if entry.get("guard"):
            return str(entry["guard"])
        if str(row).startswith("rel-"):
            return "rel"
        try:
            from tools import factory_autofeed as AF
            latest = AF.latest_sweep(self._sweep_dir())
            sweep = AF.read_sweep(latest) if latest is not None else {}
            for name in sorted(k for k, red in sweep.items() if red is True):
                path = str(name).partition("::")[0]
                if self.GUARD_FILE.search(path) and (self._guard_id_guess(path) == row):
                    return name
        except Exception as exc:                    # noqa: BLE001 - no guard found: the card is left as it was
            self.err("guard of row", exc)
        return ""

    def _guard_ids_reset(self) -> int:
        """W-guardid 3: ONCE, as soon as the newest sweep is of the new format (red_ids): the guard_requeues counters booked
        while the ids were unknown (the packet could not name the red test) are dropped, so the BLOCKED already_green cards of
        those rows go back to the slicer (_guard_green_requeue, reslice:stale, no budget).  The mark is in loop_state."""
        ls = self.ls()
        if ls.get("guard_ids_reset"):
            return 0
        try:
            from tools import factory_autofeed as AF
            latest = AF.latest_sweep(self._sweep_dir())
            if latest is None or not AF.sweep_has_ids(latest):
                return 0
        except ImportError:                         # no sweep module in this setting: nothing to reset, and no event (the loop's event stream stays as it was)
            return 0
        except Exception as exc:                    # noqa: BLE001 - no sweep, no reset yet: the next tick looks again
            self.err("guard ids reset", exc)
            return 0
        dropped = sorted((ls.get("guard_requeues") or {}))
        ls.pop("guard_requeues", None)
        ls["guard_ids_reset"] = self.clock()
        self.save_ls(ls)
        if dropped:
            self.event("supply", status="guard_ids_reset", reason="guard_requeues dropped for %s (sweep with red ids)" % ",".join(dropped)[:200])
        return len(dropped)

    def _guard_green_requeue(self) -> int:
        """W-guard 2: a card BLOCKED already_green whose row has a guard test is a wrong-test card (the contract named another,
        green test): FAILED reslice:stale (no strike, no spent reslice); the slicer then runs the guard's red test (red on the
        base) or closes the row by the guard (green).  Runs every tick, so the cards of earlier runs are passed at the start."""
        tasks, state = self.load()
        ls, picked = self.ls(), []
        for tid, rec in state["tasks"].items():
            task = tasks.get(tid)
            row = F.row_of(rec.get("backlog_id") or (task.backlog_id if task else "") or tid)
            # W-optim 4 (fix3): a READY or RUNNING debt card (rel-...) is passed too, but only when its guard is PROVEN green on this base
            waiting = rec.get("status") in ("READY", "RUNNING") and str(row).startswith("rel-")
            if not waiting and (rec.get("status") != "BLOCKED" or "already_green" not in str(rec.get("blocked_reason") or rec.get("reason") or "")):
                continue
            guard = self._guard_of_row(row, ls)
            if not guard:
                continue
            if int((ls.get("guard_requeues") or {}).get(row) or 0) >= GUARD_REQUEUE_MAX:
                continue                     # a row came back too often: the card stays BLOCKED (no endless circle)
            entry = (ls.get("to_slice") or {}).get(row) or {}
            try:                             # only when the slicer will know the guard's red ids (a list, may be empty = green)
                known = Loop._guard_red_ids(self, row, entry if entry.get("guard") or guard == "rel" else {"guard": guard})
            except Exception as exc:         # noqa: BLE001 - nothing known: the card is left as it was
                self.err("guard requeue ids", exc)
                known = None
            if known is not None and (known == [] or not waiting):
                picked.append((tid, row, guard))
        if not picked:
            return 0
        done = []
        with self.txn() as (_tasks, st):
            for tid, row, guard in picked:
                cur = st["tasks"].get(tid, {})
                if cur.get("status") in ("BLOCKED", "RUNNING") or (cur.get("status") == "READY" and not cur.get("lease")):
                    # a RUNNING debt card loses its lease: the worker's next write under the old token is refused and its pass ends
                    st["tasks"][tid].update(status="FAILED", reason="reslice:stale")
                    st["tasks"][tid].pop("blocked_reason", None)
                    st["tasks"][tid].update(lease=None, deadline=None)
                    done.append((tid, row))
        if done:                             # the count and the guard are booked only for cards that really went back
            ls = self.ls()
            counts = ls.setdefault("guard_requeues", {})
            guards = {t: g for t, _r, g in picked}
            for tid, row in done:            # the row keeps the guard: the packet of the new slice carries the red test
                counts[row] = int(counts.get(row) or 0) + 1
                if guards[tid] != "rel":
                    entry = ls.setdefault("to_slice", {}).setdefault(row, {"at": self.clock(), "hints": [], "priority": 0})
                    if not entry.get("guard"):
                        entry["guard"] = guards[tid]
            self.save_ls(ls)
        for tid, row in done:
            self.event("supply", status="guard_requeue", task_id=tid, backlog_id=row,
                       reason="already_green on a row with a guard: back to the slicer (reslice:stale)")
        return len(done)

    def _book_fixture_private(self) -> int:
        """W-vgs3 4: a debt card the runner ended not_code:fixture_private is booked in the not_code book (else the supply invariant
        would send the row back to the slicer): it does not go into the stream again."""
        tasks, state = self.load()
        ls = self.ls()
        book = ls.get("not_code") or {}
        rows = {F.row_of(r.get("backlog_id") or (tasks[t].backlog_id if t in tasks else "") or t)
                for t, r in state["tasks"].items() if r.get("reason") == "not_code:fixture_private"}
        rows = {b for b in rows if b and b not in book}
        if not rows:
            return 0
        try:
            hashes = self._row_hashes("text")
        except Exception:
            hashes = {}
        for bid in sorted(rows):
            self._not_code_set(ls, bid, "fixture_private", hashes.get(bid, ""))
            self.event("supply", status="not_code", backlog_id=bid, reason="fixture_private")
        self.save_ls(ls)
        return len(rows)

    def _bisect_later(self, tasks, state) -> set:
        """W-bisect 4: the READY cards of a never_green debt row (no green point in the whole history: nothing to restore) wait while
        there is other work; not terminal: ``_act`` gives them out when the queue is otherwise empty."""
        try:
            from tools import factory_bisect as BIS
            rows = {r for r, k in BIS.row_kinds(self.cfg.state_dir).items() if k == "never_green"}
        except Exception:
            return set()
        if not rows:
            return set()
        return {tid for tid, t in tasks.items() if F.row_of(t.backlog_id or tid) in rows and state["tasks"][tid]["status"] == "READY"}

    def _bisect_rank(self, bid) -> int:
        """Order among the baseline debt rows: 0 a proven regression, 1 not classified, 2 never_green / moved (the tail)."""
        try:
            from tools import factory_bisect as BIS
            return BIS.rank(self.cfg.state_dir, bid) if F.is_base_debt(bid) else 0
        except Exception:
            return 1

    def _release_note_run(self) -> None:
        """The cloud run the build made is written into loop_state (release_run.run) at once, so a restarted loop takes it up."""
        with self._rel_lock:                # the build's thread sets the note: read and clear it in one step
            info, self._rel_note = self._rel_note, None
        if not info or self._rel is None:   # a late note of a build that is over would write a run with no task
            return
        ls = self.ls()
        rr = ls.setdefault("release_run", {})
        if (rr.get("run") or {}).get("run_id") == info.get("run_id"):
            return
        rr["run"] = info
        self.save_ls(ls)
        sizes = [len(p) for p in info.get("parts") or ()]
        pred = [x for x in info.get("predicted") or () if isinstance(x, (int, float))]
        self.event("release", status="run", release_run=info.get("run_id"), shards=sizes, longest_s=max(pred) if pred else None,
                   reason="cloud run %s: %d shard(s) %s, wait %s s" % (info.get("run_id"), len(sizes), sizes, info.get("wait_s")))

    @staticmethod
    def _test_only(task) -> bool:
        """A task that adds tests and no code: a merged test task of a row is not yet the row."""
        files = [str(f).replace("\\", "/") for f in getattr(task, "touch_files", None) or ()]
        if getattr(task, "kind", "") == "unit_test":
            return True
        try:
            rig = json.loads(getattr(task, "contract", "") or "{}").get("rig") is True
        except (ValueError, TypeError, AttributeError):
            rig = False
        return not rig and bool(files and all(f.startswith("tests/") for f in files))      # a rig card IS the fix of its row (26.11: 0 accepted of 20 merged stand fixes)

    @staticmethod
    def _task_finished(row) -> bool:
        """The one meaning of 'this task is finished': merged (PROMOTED/DONE) or dropped for good (F.is_terminal reason:
        superseded:reslice<n>, quarantine, closed, sliced, not_code).  A finished task holds neither a row nor a test open."""
        row = row or {}
        return row.get("status") in ("PROMOTED", "DONE") or F.is_terminal(row.get("reason"))

    def _only_tests_changed(self, ls, sha) -> bool:
        """True when the tree changed since the last verdict in test files only (a sure 'no' on any doubt)."""
        last = ls.get("release")
        old = str(last.get("sha") or "") if isinstance(last, dict) else ""
        if not old or not sha or old == sha:
            return False
        try:
            out = git_run(self.cfg.repo, "diff", "--name-only", old, str(sha))
        except Exception:
            return False
        files = [f.strip().replace("\\", "/") for f in out.splitlines() if f.strip()]
        return bool(files) and all(f.startswith("tests/") for f in files)

    def _tree_of(self, sha) -> str:
        try:
            return git_run(self.cfg.repo, "rev-parse", str(sha) + "^{tree}").strip()
        except Exception:
            return ""

    def _release_start(self, ls, now, REL) -> None:
        tasks, state = self.load()
        unfinished = {tid for tid, r in state["tasks"].items() if not self._task_finished(r)}
        open_bids = {self._bid(state, tasks, tid) for tid in unfinished}
        open_tests = {f for tid in unfinished if tid in tasks for f in tasks[tid].tests}
        to_slice = ls.get("to_slice") or {}
        for name, rec in REL.regressions(self.cfg.state_dir).items():       # a confirmed regression is open work until its row is closed
            if rec.get("row") in to_slice or rec.get("row") in open_bids:
                open_tests.add(name.split("::", 1)[0])
        accepted = ls.get("accepted") or {}
        tids = sorted(tid for tid, r in state["tasks"].items()
                      if r.get("status") == "PROMOTED" and tid not in accepted and tid in tasks
                      and (self._bid(state, tasks, tid) or "") and not self._bid(state, tasks, tid).lower().startswith("fac-")
                      and not self._test_only(tasks[tid])      # a merged test task with no code is no row to accept
                      and self._bid(state, tasks, tid) not in open_bids)     # only whole stories: no unfinished task of the row
        try:
            open_ids = set(self._row_hashes("text"))
        except ValueError:                  # a backlog with no open-rows section: no row is open (a guard of it is a plain red)
            open_ids = set()
        except Exception as e:              # the file cannot be read now: the build waits for the next tick
            self.err("release: backlog unreadable", e)
            return
        resume = REL.resumable(ls)
        if resume:                          # the loop was restarted while a run was out: take that run up, never start another
            rr = ls["release_run"]
            sha = str(rr.get("sha") or self.base_sha)
            snap = self.snap_dir / sha[:12]
            snap = snap if snap.is_dir() else None          # gone: the files of a shard that did not end cannot be run again
            shards, tids, open_tests = REL.SWEEP_SHARDS[1], list(rr.get("tids") or ()), set(rr.get("open_tests") or ())
        else:
            sha = self.base_sha
            tree = self._tree_of(sha)
            if (not REL.worth_a_run(ls, sha, tree, len(tids))       # nothing to accept, this tree was judged already
                    or (not tids and self._only_tests_changed(ls, sha))):     # or only tests changed since the verdict
                if ls.get("release_skip") != sha:
                    ls["release_skip"] = sha
                    ls["release_skip_total"] = int(ls.get("promoted_total") or 0)     # REL.due counts it; the verdict record stays true
                    self.save_ls(ls)
                    self.event("release", status="skipped", base_sha=sha, reason="no row to accept, the tree of this SHA was judged")
                return
            shards = REL.shards_for(self._release_places())
            if not shards:                  # fewer than the minimum places left over by the task cards: wait for the next tick
                return
            snap = self._snapshot(sha)
            ls["release_run"] = {"sha": sha, "tree": tree, "tids": tids, "open_tests": sorted(open_tests),
                                 "promoted_total": int(ls.get("promoted_total") or 0)}
            ls.pop("release_skip", None)
            self.save_ls(ls)
        fn, state_dir = self.release_fn, self.cfg.state_dir
        guard_rows = {str(k): str(v["guard"]) for k, v in (ls.get("to_slice") or {}).items() if isinstance(v, dict) and v.get("guard")}   # fac-64
        self._rel_snap = snap
        with self._rel_lock:
            self._rel_note = None

        def note(info):
            with self._rel_lock:
                self._rel_note = info       # the loop's thread writes it into loop_state
        self._rel = Prefetch("release", lambda: fn(sha=sha, snapshot=snap, state_dir=state_dir, open_ids=open_ids,
                                                    open_tests=set(open_tests), shards=shards, on_run=note, resume=resume, guard_rows=guard_rows), {})
        self._rel.thread.start()
        self.event("release", status="started", base_sha=sha, release_run=(resume or {}).get("run_id"),
                   reason=("final build: picks up run %s" % resume["run_id"]) if resume else "final build: %d rows to accept" % len(tids))

    def _release_places(self) -> int:
        """Cloud job places the task cards leave free: the free plan's jobs minus the places the account really holds now
        (the same count the cards take places by) minus the places the cards waiting in the queue will take (cards first).
        The poll failed: the old upper bound, every live worker holding a candidate run of PRODUCT_SHARDS jobs."""
        if factory_cloud_gate is None:          # no cloud gate module: the cards hold no cloud places
            return 10 ** 6
        G = factory_cloud_gate
        busy = G.occupied_places()
        if busy is None:
            busy = len(self.pool.workers) * G.PRODUCT_SHARDS
            waiting = 0
        else:
            waiting = G.waiting_cards() * G.PRODUCT_SHARDS
        return max(0, G.FREE_PLAN_JOBS - busy - waiting)

    def _release_near(self, task, red_files) -> bool:
        """True when the task's files are neighbours of a red test (the neighbour map of 3.1, <state>/neighbors/latest.json:
        {source file: [test files]}); no map: every task is a neighbour (nothing is accepted next to a regression blindly)."""
        try:
            data = json.loads((Path(self.cfg.state_dir) / "neighbors" / "latest.json").read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return True
        except (OSError, ValueError):
            return True
        if red_files & {str(t).replace("\\", "/") for t in task.tests}:
            return True
        return any(red_files & {str(t).replace("\\", "/") for t in (data.get(f) or ())} for f in task.touch_files)

    def _release_done(self, job, now, REL) -> None:
        ls = self.ls()
        run = ls.get("release_run") or {}
        res = job.result if isinstance(job.result, dict) else {}
        status = res.get("status") or ""
        if job.error is not None or status not in ("baseline", "green", "new_red"):
            ls["release_retry_at"] = now + REL.RETRY_S              # no verdict: the record stays, the sweep repeats
            rr = ls.get("release_run")
            if isinstance(rr, dict) and job.error is None:
                rr.pop("run", None)     # run() gave the run up, or read it and it was short: it is spent, a new one next time
            self.save_ls(ls)            # (a failed wait keeps the run: REL.run counts the failures, in run.json, and says gave_up)
            why = F.redact(str(job.error))[:200] if job.error is not None else (res.get("reason") or status or "no result")
            self.event("release", status="failed" if job.error is not None else (status or "failed"), dur_s=round(job.dur_s, 3),
                       reason=str(why)[:200], base_sha=run.get("sha"), release_run=(res.get("sweep") or {}).get("run_id"),
                       shards=res.get("shards") or None, longest_s=res.get("longest_s"))
            return
        sha = str(res.get("sha") or run.get("sha") or "")
        new_red = [str(n) for n in ((res.get("sweep") or {}).get("new_red") or ())]
        tasks, state = self.load()
        taken = []
        if status in ("green", "new_red"):
            red_files = {n.split("::", 1)[0] for n in new_red}
            for tid in run.get("tids") or ():
                row, task = state["tasks"].get(tid) or {}, tasks.get(tid)
                if row.get("status") != "PROMOTED" or task is None or tid in (ls.get("accepted") or {}):
                    continue                                        # rejected or taken meanwhile
                if new_red and self._release_near(task, red_files):
                    continue                                        # a neighbour of the regression waits for the next build
                taken.append(tid)
        if not isinstance(ls.get("accepted"), dict):
            ls["accepted"] = {}
        for tid in taken:
            ls["accepted"][tid] = {"at": self.ts(), "note": "release %s" % sha[:8]}
        if status == "new_red":
            commits = ", ".join(str((state["tasks"].get(t) or {}).get("commit") or "")[:8] for t in (run.get("tids") or ())[:8]) or "-"
            rows = {}
            for n, name in enumerate(new_red, 1):
                key = "rel-%s-%d" % (sha[:8], n)
                rows[name] = key
                ls.setdefault("to_slice", {})[key] = {"at": now, "text": "после слияний %s упал тест %s" % (commits, name),
                                                      "guard": name, "hints": [], "priority": 0}
            try:
                REL.record_regressions(self.cfg.state_dir, new_red, rows, now)
            except OSError as e:
                self.err("release: regressions", e)
        for debt in res.get("debt_rows") or ():          # the red baseline, one row per test file (a line of its own, after the owner's)
            if str(debt.get("key")) in (ls.get("outdated_tests") or {}):
                continue                                 # W-prio 3: an outdated test gets no row
            try:
                names = [str(t).split("::", 1)[-1] for t in debt["tests"][:5]]
                ls.setdefault("to_slice", {}).setdefault(str(debt["key"]), {
                    "at": now, "hints": [], "priority": 2, "guard": str(debt["guard"]),
                    "text": "тест %s красный на базе %s: %s" % (debt["file"], sha[:8], ", ".join(names))})
            except (KeyError, TypeError, IndexError):
                self.err("release: debt row", ValueError(str(debt)[:100]))
        closed_rows = [str(r) for r in (res.get("closed_rows") or ()) if r]
        owner_rows = [b for b in closed_rows if not b.startswith("rel-")]      # fac-64: the owner's rows leave the slicer only, no "done" claim
        for bid in closed_rows:                          # W-part 1: green in the two last full builds: out of the queues
            for key in (("to_slice", "slice_wait") if bid in owner_rows else ("to_slice", "slice_wait", "reslices", "quarantine")):
                if isinstance(ls.get(key), dict):
                    ls[key].pop(bid, None)
            if bid in owner_rows and isinstance(ls.get("seen"), dict):     # the row stays open in the backlog: remember it, so the lost-rows pass does not hand it back
                ls["seen"][bid] = {"kind": "already_green", "reason": "guard green in two full builds", "until": now + self.LOST_AGAIN_S}
        ls["release"] = {"sha": sha, "at": now, "promoted_total": int(run.get("promoted_total") or 0),
                         "status": status, "new_red": new_red, "tree": run.get("tree") or ""}
        if isinstance(ls.get("release_run"), dict):
            ls["release_run"]["closed"] = True              # judged: the run is not taken up again
            ls["release_run"].pop("run", None)
        if status == "green":                   # coordinator 22.11 23:20: a green build deploys only when the deploy exists
            deploy = getattr(REL, "deploy", None)
            if deploy is None:
                ls["release"]["deploy_wait"] = "no_deploy_yet"
            else:
                try:
                    deploy(sha=sha, state_dir=self.cfg.state_dir)
                except Exception as e:
                    ls["release"]["deploy_wait"] = "deploy_failed"
                    self.err("release: deploy", e)
        ls.pop("release_retry_at", None)
        self.save_ls(ls)
        self.event("release", status=status, dur_s=round(job.dur_s, 3), base_sha=sha, reason=str(res.get("reason") or "")[:200],
                   new_red=len(new_red), accepted=len(taken), release_run=(res.get("sweep") or {}).get("run_id"),
                   shards=res.get("shards") or None, longest_s=res.get("longest_s"))
        for bid in owner_rows:
            self.event("release", status="slice_dropped", backlog_id=bid, reason="already_green (guard green in two full builds; "
                       "the guard may cover less than the row: the row stays open in the backlog)")
        closed_rows = [b for b in closed_rows if b not in owner_rows]
        if closed_rows:
            def supersede_green(st):
                for tid, row in st["tasks"].items():
                    if F.row_of(row.get("backlog_id") or tid) in closed_rows and row.get("status") == "READY":
                        row.update(status="FAILED", reason="superseded:already_green")
            try:
                self._tx(supersede_green)
            except Exception as e:      # noqa: BLE001 - a busy plan: the READY card meets the guard check later
                self.err("release: supersede already_green", e)
            for bid in closed_rows:
                self.event("release", status="debt_closed", backlog_id=bid, reason="superseded:already_green (green in two full builds)")
        try:        # fac-43 step 0: the models of each accepted card by role, from its call rows
            by_role = RT.models_by_role(RT.telemetry_rows(self.dir), taken) if taken else {}   # .jsonl, .1 and .2
        except Exception as e:  # noqa: BLE001 - the span goes without models; build() still finds the calls
            by_role = {}
            self.err("release: accepted models", e)
        for tid in taken:
            row, bid = state["tasks"].get(tid) or {}, self._bid(state, tasks, tid)
            self.event("accept", task_id=tid, backlog_id=bid, status="accepted", reason="accepted_by_release")
            self.event("accepted", task_id=tid, backlog_id=bid, sha=str(row.get("commit") or "") or None, base_sha=sha,
                       models=by_role.get(tid) or None)
            try:
                task_a = tasks.get(tid)
                # a card with a non-empty `more` fixed only part of the row (the barrier of _closes_row): the debt closes by two full builds
                if (task_a is None or not (Loop._contract(task_a).get("more") or row.get("reds_left"))) and REL.close_debt(self.cfg.state_dir, bid):     # a merged and accepted rel-base-<n>: its file leaves the debt
                    self.event("release", status="debt_closed", backlog_id=bid, reason="baseline debt row accepted")
                from tools import factory_gate as _fg
                if task_a is not None and _fg.is_rig_task(task_a) and not (Loop._contract(task_a).get("more") or row.get("reds_left")):
                    # W-rig (deliberate second way to close debt): the task says the ids leave the baseline debt at once, without the two
                    # green builds of W-part; a rig card replaces the test stand itself, its ids were verified in the cloud run of the candidate
                    spec = Loop._contract(task_a).get("test") or {}
                    gone = REL.close_debt_ids(self.cfg.state_dir, [spec.get("use")] + list(spec.get("also") or []))
                    if gone:
                        self.event("release", status="debt_closed", backlog_id=bid, reason="rig accepted: %d ids left the debt" % gone)
            except Exception as e:
                self.err("release: debt close", e)
            try:
                res_note = factory_closures.update_note(self.cfg.backlog, bid, str(row.get("commit") or ""), "accepted in release %s" % sha[:8])
                self.event("closure", task_id=tid, backlog_id=bid, status=res_note, reason="accepted_by_release")
            except Exception as e:
                self.err("release: closure note", e)
            task = tasks.get(tid)
            if task is not None and getattr(task, "contract", ""):
                try:                                    # an accepted fix, not a merged one, becomes the architect's example
                    from tools import factory_classes as CL
                    CL.record_contract(bid, task.touch_files, task.contract)
                except Exception as e:
                    self.err("release: contract example", e)
        if taken:
            self._build_router_table()

    def _neighbors_tick(self, head, root=None) -> None:
        """The neighbour map (``{file: [tests one import hop away]}``) of the base ``head``, built ONCE per SHA by one child
        process in a background slot (like the sweep): the workers read the copy of the last finished map from their snapshot
        and never build the import graph. Neither the step nor a card waits for it; a base without a map (the first run, a map
        that failed) is served by the graph as before. ``latest.json`` is moved to the new map after it is complete."""
        try:
            from tools import affected_tests as AT
            nb = Path(self.cfg.state_dir) / "neighbors"
            job = getattr(self, "_nb", None)
            if job is not None:
                if not job.done.is_set():
                    return
                self._nb = None
                if job.error is None and job.result:
                    shutil.copyfile(nb / (job.ctx["sha"] + ".json"), nb / "latest.json.new")
                    os.replace(nb / "latest.json.new", nb / "latest.json")
                    self.event("neighbors", status="done", dur_s=round(job.dur_s, 3), base_sha=job.ctx["sha"])
                else:
                    self.event("neighbors", status="failed", dur_s=round(job.dur_s, 3),
                               reason=F.redact(str(job.error or "no map"))[:200])
            if not head or getattr(self, "_nb_sha", None) == head or self._ending():
                return
            self._nb_sha = head
            target = nb / (head[:12] + ".json")
            nb.mkdir(parents=True, exist_ok=True)
            if target.is_file():                       # built by an earlier run of the loop
                shutil.copyfile(target, nb / "latest.json.new")
                os.replace(nb / "latest.json.new", nb / "latest.json")
                return
            tree = Path(root) if root is not None else self._snapshot(head)
            self._nb = Prefetch("neighbors", lambda: AT.build_neighbors(tree, target), {"sha": head[:12]})
            self._nb.thread.start()
        except Exception as e:      # noqa: BLE001  without a map the workers use the graph
            self.err("neighbors", e)

    @staticmethod
    def _closes_row(task, parents=None) -> bool:
        """A promoted task closes its backlog row only when it is the whole row's code task: a test sub-task or one part of
        a cut row shares the backlog ID but proves nothing about the row (the parents path closes a cut row)."""
        return (task is not None and getattr(task, "kind", "code") == "code"
                and not Loop._contract(task).get("more")
                and getattr(task, "backlog_id", "") not in (parents or {}))

    def _sync_stale_rows(self, ids, sha_of=None) -> int:
        """Rows the triage proved closed by a commit (stale) go into the closures table with that commit's sha; a row with no
        sha is left alone.  ``sha_of`` defaults to the sidecar of closed IDs.  Returns how many rows were added."""
        ids = [i for i in ids if i]
        if not ids:
            return 0
        try:
            if sha_of is None:
                from tools import factory_autofeed as AF
                path = AF.sidecar_path(self.cfg.worktree)
                sha_of = AF.read_closed(path) if path is not None else {}
                missing = [i for i in ids if i not in sha_of]
                if missing:                 # no sidecar entry: the closing commit itself names the sha
                    sha_of = dict(AF.closing_shas(self.cfg.worktree, missing), **sha_of)
            got = factory_closures.sync_stale(self.cfg.backlog, ids, sha_of, "commit closed the row (triage proof)")
        except ImportError:          # the public mirror withholds the feed module
            return 0
        except Exception as e:
            self.err("stale closures", e)
            return 0
        if got["added"] or got["no_sha"]:
            self.event("closure", status="stale_synced", reason="added=%d no_sha=%d" % (len(got["added"]), len(got["no_sha"])),
                       backlog_id=",".join(got["added"][:10]))
        return len(got["added"])

    def _package_answer(self, folder: Path, bid, note) -> dict:
        """W-pack: a root package (one root cause, many files) is merged by the cycle after a FULL cloud build of base and base+package:
        ``folder/files/**`` + ``folder/verdict.json`` {base, digest, runs [2], green, new_red [], review {"verdict": "approve"}}. All is
        checked again here: the digest, the paths (rig_touch_faults), the AST lock (rig_weakens), the calls (factory_calls), the touched
        files unchanged since the verdict's base. One commit, the worktree lock of the cycle, like _revert_answer.
        Trust: verdict.json is NOT signed; the answers folder is a trusted source (whoever can put a folder there is the owner).
        The two full cloud runs and the review are claimed by the verdict, the cycle cannot confirm them. A conftest is limited to
        fixtures (AST allow-list _conftest_faults; the path is compared canonically, only the exact name is written). A failed write/add/commit restores the package paths."""
        from tools import factory_calls, factory_gate
        wt = Path(self.cfg.worktree)
        try:
            verdict = json.loads((folder / "verdict.json").read_text(encoding="utf-8"))
            files = {x.relative_to(folder / "files").as_posix(): x.read_bytes() for x in sorted((folder / "files").rglob("*"))
                     if x.is_file() and not x.is_symlink() and "__pycache__" not in x.parts}
            texts = {n: raw.decode("utf-8") for n, raw in files.items()}
        except (OSError, ValueError) as e:
            raise F.InvalidPlan("package unreadable: %s" % type(e).__name__) from e
        base = str(verdict.get("base") or "")
        if not files or verdict.get("digest") != package_digest(files):
            raise F.InvalidPlan("package: the digest is not the one that was built")
        if not isinstance(verdict, dict):
            raise F.InvalidPlan("package: verdict.json must be an object")
        runs, review, green = verdict.get("runs"), verdict.get("review"), verdict.get("green")
        try:
            green = int(green) if isinstance(green, (int, str)) and not isinstance(green, bool) else 0
        except ValueError:
            green = 0
        if verdict.get("new_red") != [] or green <= 0 or not isinstance(runs, list) or len(runs) < 2 \
                or not all(isinstance(r, (dict, int)) and not isinstance(r, bool) for r in runs) or not isinstance(review, dict) or review.get("verdict") != "approve":
            raise F.InvalidPlan("package: needs green > 0, new_red [], two full runs and an approving review")
        faults = factory_gate.rig_touch_faults(list(files))
        if not re.fullmatch(r"[0-9a-f]{40}", base) or subprocess.run(
                ["git", "-C", str(wt), "merge-base", "--is-ancestor", base, self.cfg.branch], capture_output=True).returncode != 0:
            faults.append("base is not on " + self.cfg.branch)
        if git_run(wt, "rev-parse", "--abbrev-ref", "HEAD").strip() != self.cfg.branch:
            faults.append("merge worktree is not on " + self.cfg.branch)
        if not faults and self._dirty_paths(wt):
            faults.append("merge worktree is dirty: the package waits")
        if not faults and subprocess.run(["git", "-C", str(wt), "diff", "--quiet", base, "HEAD", "--", *files]).returncode != 0:
            faults.append("a file of the package changed since its base: build it again")
        if not faults:
            faults += factory_gate.rig_weakens(wt, texts)
            for name, text in texts.items():
                old = (wt / name).read_text(encoding="utf-8") if (wt / name).is_file() else ""
                if name.endswith(".py"):
                    faults += factory_calls.new_bad_calls(name, old, text, wt)
                canon = posixpath.normpath(name.replace("\\", "/")).casefold()
                is_conftest = canon == "tests/conftest.py"
                if is_conftest and name != canon:
                    faults.append(name + ": conftest must be written as exactly tests/conftest.py")
                if not is_conftest and factory_gate.is_forbidden(name, "code", named=list(files), rig=True):
                    faults.append(name + ": forbidden")
                if is_conftest:
                    faults += _conftest_faults(name, text, _project_fixture_names(wt), old)
                if F.is_private_text(text) and not F.is_private_text(old):
                    faults.append(name + ": private text")
        if faults:
            raise F.InvalidPlan("package refused: " + "; ".join(faults[:6]))
        key = bid or "rel-pack-" + verdict["digest"][:8]
        try:
            for name, raw in files.items():
                (wt / name).parent.mkdir(parents=True, exist_ok=True)
                (wt / name).write_bytes(raw)
            git_run(wt, "add", "--", *files)
            git_run(wt, "-c", "user.name=agent-factory", "-c", "user.email=agent-factory@localhost", "commit", "-q", "-m",
                    "factory-package(%s): %s" % (key, self._scrub(F.redact(note))[:300]))
            sha = git_run(wt, "rev-parse", "HEAD").strip()
        except Exception as e:  # a failed write/add/commit must not leave the package in the tree or the index
            try:
                self._restore(wt, list(files))
            except Exception as e2:
                self.err("package restore", e2)
            raise F.InvalidPlan("package: write or commit failed (%s), the tree is restored" % type(e).__name__) from e
        ls = self.ls()
        ls["promoted_total"] = int(ls.get("promoted_total") or 0) + 1     # a merged package makes a final build due, like a product row
        self.save_ls(ls)
        self.event("promote", task_id=key, backlog_id=key, status="promoted", reason="package", commit=sha, green=green)
        return {"task_id": None, "backlog_id": key, "reason": "package " + sha[:8]}

    def _revert_answer(self, tid, bid, state, note, ls) -> dict:
        """W-true2 3: --reject --revert: a revert commit of the merged edit in the cycle's own worktree (the worktree lock it
        holds for its whole life, like _promote), the task FAILED superseded:revert, the row back to to_slice with the note.
        A conflict is aborted (git revert --abort, no reset/clean) and refused with the reason."""
        row, wt = state["tasks"][tid], Path(self.cfg.worktree)
        sha = str(row.get("commit") or "")
        if not sha:
            raise F.InvalidPlan("task %s has no merge commit to revert" % tid)
        if git_run(wt, "rev-parse", "--abbrev-ref", "HEAD").strip() != self.cfg.branch:
            raise F.InvalidPlan("merge worktree is not on " + self.cfg.branch)
        if self._dirty_paths(wt):
            raise F.InvalidPlan("merge worktree is dirty: the revert waits")
        if subprocess.run(["git", "-C", str(wt), "merge-base", "--is-ancestor", sha, self.cfg.branch]).returncode != 0:
            raise F.InvalidPlan("commit %s is not on %s: nothing to revert" % (sha[:8], self.cfg.branch))
        text = self._scrub(F.redact(note))[:300]
        # a retry after a failed state write: the revert commit of this cycle is already in the branch, go on to the records
        done = git_run(wt, "log", "-1", "--format=%H", "--fixed-strings", "--grep", "factory-revert(%s):" % tid,
                       "%s..%s" % (sha, self.cfg.branch)).strip()
        if done:
            new_sha = done
        else:
            why = ""
            proc = subprocess.run(["git", "-C", str(wt), "revert", "--no-commit", sha], capture_output=True, text=True)
            if proc.returncode != 0:
                why = "revert of %s conflicts: %s" % (sha[:8], F.redact((proc.stdout + proc.stderr).strip())[:200])
            elif subprocess.run(["git", "-C", str(wt), "diff", "--cached", "--quiet"]).returncode == 0:
                why = "revert of %s changes nothing (already undone)" % sha[:8]
            if why:
                subprocess.run(["git", "-C", str(wt), "revert", "--abort"], capture_output=True)
                if self._dirty_paths(wt):
                    why += "; the worktree is not clean after the abort, needs a look"
                raise F.InvalidPlan(why)
            git_run(wt, "-c", "user.name=agent-factory", "-c", "user.email=agent-factory@localhost", "commit", "-q", "-m",
                    "factory-revert(%s): %s" % (tid, text))
            new_sha = git_run(wt, "rev-parse", "HEAD").strip()
        ls["promoted_total"] = int(ls.get("promoted_total") or 0) + 1     # the branch changed: a final build is due
        (ls.get("accepted") or {}).pop(tid, None)
        seen = ls.setdefault("rejected", {}).setdefault(tid, [])     # the recovered path of _promote never takes it again
        if sha not in seen:
            seen.append(sha)
        bid = bid or row.get("backlog_id")
        task = self.load()[0].get(tid)
        entry = ls.setdefault("to_slice", {}).setdefault(F.row_of(bid or tid), {"at": self.clock(), "hints": [], "guard": ""})
        entry["hints"] = [text] + [h for h in entry.get("hints", []) if h != text]
        entry["text"] = text
        if task is not None:
            entry["hints"] += [f for f in task.touch_files if f not in entry["hints"]]
        self.save_ls(ls)

        def fail(st):
            r = st["tasks"][tid]
            r.update(status="FAILED", reason="superseded:revert", commit=None, lease=None, deadline=None)
            F.add_feedback(st, tid, "opus", note or "reverted")
        self._tx(fail)
        try:
            res = factory_closures.update_note(self.cfg.backlog, bid, sha, "reverted " + sha[:8])
            self.event("closure", task_id=tid, backlog_id=bid, status=res, reason="reverted")
        except Exception as e:
            self.err("revert: closure note", e)
        self.event("reject", task_id=tid, backlog_id=bid, status="reverted", reason="rejected_by_coordinator", commit=new_sha)
        return {"task_id": tid, "backlog_id": bid, "reason": "reverted"}

    def _reject_answer(self, tid, bid, state, note, revert=False) -> dict:
        if not tid or tid not in state["tasks"]:
            raise F.InvalidPlan("reject needs a known task (--task-id)")
        status = state["tasks"][tid]["status"]
        if status != "PROMOTED":
            raise F.InvalidPlan("only a PROMOTED task can be rejected (it is %s)" % status)
        ls = self.ls()
        if revert:                                        # W-pack: a build may have accepted the culprit; the revert undoes that too
            return self._revert_answer(tid, bid, state, note, ls)
        if tid in (ls.get("accepted") or {}):
            raise F.InvalidPlan("task %s is already accepted" % tid)
        row = state["tasks"][tid]
        ls.setdefault("rejected", {}).setdefault(tid, []).append(row.get("commit"))
        self.save_ls(ls)

        def reset(st):
            r = st["tasks"][tid]
            if r["status"] != "PROMOTED":
                raise F.InvalidPlan("only a PROMOTED task can be rejected (it is %s)" % r["status"])
            r.update(status="READY", attempts=0, reds=0, commit=None, lease=None, deadline=None)
            F.add_feedback(st, tid, "opus", note or "rejected by Opus")
        self._tx(reset)
        bid = bid or row.get("backlog_id")
        self.event("reject", task_id=tid, backlog_id=bid, status="rejected", reason="rejected_by_coordinator")
        return {"task_id": tid, "backlog_id": bid, "reason": "rejected"}

    def _close_answer(self, ans, tid, bid, tasks, state, note) -> dict:
        """Opus closes the row: the task becomes DONE, or the hold is dropped and remembered.
        The row is fingerprinted FIRST: if that fails nothing has been changed yet."""
        ls = self.ls()
        if bid:  # durable across backlog edits; forgotten when the row's text changes
            try:
                fingerprint = self._row_hashes("text").get(bid)
                if not fingerprint:
                    if not tid:
                        raise F.InvalidPlan("row %s is not in the backlog: nothing to close" % bid)
                    fingerprint = ""        # a task of a row we cannot see: close the task only
                if fingerprint:
                    ls["closed"][bid] = fingerprint
            except F.InvalidPlan:
                raise
            except Exception as e:  # no sentinel without a hash: the answer waits and is retried
                raise _Later("backlog unreadable, cannot fingerprint the row: %s" % type(e).__name__) from e
        if tid:
            if tid not in tasks:
                raise F.InvalidPlan("unknown task " + tid)
            with self.txn() as (_t, st):            # the status is checked on the FRESH row, inside the transaction
                row = st["tasks"][tid]
                if row["status"] in ("RUNNING", "REVIEW"):
                    raise _Later("task is %s" % row["status"])
                if row["status"] == "DONE":
                    raise F.InvalidPlan("task is already DONE")
                if row["status"] == "PROMOTED":
                    # a close drops the candidate in ONE answer, its commit kept as rejected the way --reject keeps it
                    # (live 20.11 03:54: the close was refused, the reject after it made the task READY and the loop
                    # wrote the same test again before a second close could come)
                    ls.setdefault("rejected", {}).setdefault(tid, []).append(row.get("commit"))
                    row["commit"] = None
                row.update(status="DONE", lease=None, deadline=None, blocked_reason=None,
                           reason="closed_by_opus")
                self._drop_pending(row)
                row.pop("not_before", None)
                F.add_feedback(st, tid, "opus", note or "closed by Opus")
        elif not bid:
            raise F.InvalidPlan("close needs a task or a backlog id")
        ls["holds"].pop(bid or "", None)
        if tid:
            self._clear_requeues(ls, tid)
        self.save_ls(ls)
        info = {"task_id": tid or None, "backlog_id": bid or None, "reason": "closed"}
        if tid:
            deps = [t for t, tk in tasks.items() if tid in tk.depends_on]
            if deps:
                info["dependents"] = ",".join(deps[:10])  # they are released by this DONE
        return info

    def _backlog_text(self, bid: str) -> tuple[str, bool, bool]:
        """(public goal, private, unclean) through the existing parser. The row text goes through
        public_goal + residue: the owner's quotes/times/speech never reach an external model.
        private: a private row. unclean: the text did not pass the public check (goal is empty)."""
        return self._backlog_row(bid)[:3]

    def _backlog_row(self, bid: str) -> tuple[str, bool, bool, bool]:
        """_backlog_text plus ``known``: False = the id is not in the parse (private for free models, fail closed,
        but not private BY CONTENT: Opus' own public goal for it needs no --release-private, 21.11)."""
        try:
            from tools import agent_factory_import as imp
            for r in imp.parse_open_rows(self.cfg.backlog, self.cfg.worktree, include_closed=True):
                if r.get("backlog_id") != bid:
                    continue
                text = str(r.get("text") or "")
                if r.get("private") or not text:
                    return "", bool(r.get("private")), False, True
                goal, _classes = imp.screen(text, imp.MIN_PUBLIC_CHARS)
                if goal is None:
                    return "", False, True, True
                return F.redact(goal)[:F.GOAL_MAX], False, False, True
        except Exception as e:
            raise _Later("backlog parser failed: %s: %s" % (type(e).__name__, F.redact(str(e))[:200])) from e
        return "", True, False, False  # not in the parse (or unparsable as open): fail closed, private

    PHONE = re.compile(r"(?<![\w.])(?:\+\d[\d\s().-]{8,}\d|\(\d{3,4}\)[\s.-]?\d[\d\s.-]{5,}\d|"
                       r"\d{3}[\s.-]\d{3}[\s.-]\d{2}[\s.-]\d{2}|[78][3489]\d{9})(?![\w.])")

    @staticmethod
    def _flat(text: str) -> str:
        """Only the layout is ignored (spaces, ** and the backticks/asterisks at the ends), never the words."""
        return " ".join(text.replace("**", "").strip("`* ").split())

    @classmethod
    def _check_note(cls, note: str) -> None:
        """The note is written to the coder's prompt AS IS: it must survive the public cut unchanged
        (a quote, a time or a line reference means the owner's words, whatever the rest says)."""
        from tools import agent_factory_import as imp
        clean, bad = imp.screen(note, 0)
        hit = cls._privacy_hit(note)
        changed = clean is not None and cls._flat(clean) != cls._flat(note)
        if clean is None or bad or hit or changed:
            raise F.InvalidPlan("the note of a public task goes to an external model but it holds "
                                "%s" % (hit or "owner words, quotes or times (%s)"
                                        % (",".join(bad) or "cut by the public check")))

    @classmethod
    def _privacy_hit(cls, text: str) -> str:
        """Keys, secrets, phones, e-mail, profile paths, call recordings, personal data: the import's
        PRIVATE detector plus what redact() knows. '' when nothing matched."""
        from tools import agent_factory_import as imp
        # the phone first: PRIVATE carries PHONE.pattern too (19.11 17:47), and it would name a phone "private
        # material" (both refuse; the name tells Opus what to remove)
        m = cls.PHONE.search(text)
        if m and sum(c.isdigit() for c in m.group(0)) >= 10:
            return "a phone number"
        if imp.PRIVATE.search(text):
            return "private material (owner's private markers, recordings, keys, personal data)"
        step = F.REDACT_INPUT_MAX - 200               # redact() looks at a prefix only: look window by window
        for i in range(0, max(len(text), 1), step):
            window = text[i:i + F.REDACT_INPUT_MAX]
            if F.redact(window) != window:
                return "a secret, an e-mail or a profile path"
        return ""

    @classmethod
    def _public_goal(cls, text: str, *, released: bool = False) -> str:
        """Opus' technical wording: it must pass the same check, or the answer is refused."""
        from tools import agent_factory_import as imp
        goal, bad = imp.screen(str(text), imp.MIN_PUBLIC_CHARS)
        if goal is None:
            raise F.InvalidPlan("goal fails the public check (%s): write a technical wording "
                                "without the owner's words, quotes or times" % ",".join(bad))
        hit = cls._privacy_hit(str(text))
        if hit:
            raise F.InvalidPlan("goal contains %s: it can never go to an external model" % hit)
        return F.redact(goal)[:F.GOAL_MAX]

    # -- backlog polling
    def _has_more(self, ls: dict, now: float) -> bool:
        try:
            mtime = self.cfg.backlog.stat().st_mtime
        except OSError:
            return False
        if any(self._seen_expired(rec, now) for rec in (ls.get("seen") or {}).values()):
            return True                      # <id>: a skipped/stale row's term is over: it gets a fresh look
        mark = ls.get("triage_empty")
        return not (mark and mark.get("mtime") == mtime and now < mark.get("until", 0))

    @staticmethod
    def _seen_expired(rec, now: float) -> bool:
        """A seen row without a term (the bare word of older loops) counts as expired."""
        try:
            return not isinstance(rec, dict) or float(rec.get("until") or 0) <= now
        except (TypeError, ValueError):
            return True

    SEEN_KNOWN = "уже известна"            # the triage's word for a row the loop already holds: not booked as seen
    STALE_REASON = "закрыта коммитом <ID>: на HEAD; строку бэклога обновить"

    def _book_seen(self, ls, res, now) -> None:
        """<id> («у каждого запрета или блокировки в журнале есть причина и срок»): every stale/skipped row is booked
        with its reason and a term (cfg.seen_retry_s); rows the loop already holds are not booked (their state is the
        queue, the holds or the closed book). A row past its term that the triage did not report again is dropped."""
        cfg = self.cfg
        until = now + cfg.seen_retry_s
        reported = set()
        for key in ("stale", "skipped"):
            for item in res.get(key) or []:
                bid = item if isinstance(item, str) else (
                    item.get("backlog_id") if isinstance(item, dict) else None)
                if not bid:
                    continue
                reported.add(bid)
                why = (item.get("reason") if isinstance(item, dict) else "") or ""
                if key == "skipped" and str(why).startswith(self.SEEN_KNOWN):
                    # a live seen row is passed as known, so the triage calls it known: its term stays (popping it
                    # here re-triaged every seen row on every second triage, whatever its term)
                    if self._seen_expired(ls["seen"].get(bid), now):
                        ls["seen"].pop(bid, None)
                    continue
                why = self._scrub(F.redact(str(why)))[:200] if why else (
                    self.STALE_REASON if key == "stale" else "пропущена триажем")
                ls["seen"][bid] = {"kind": key, "reason": why, "until": until}
        for bid, rec in list(ls["seen"].items()):
            if bid not in reported and self._seen_expired(rec, now):
                ls["seen"].pop(bid, None)
        ls["skipped_unknown"] = {
            str(x["backlog_id"]): self._scrub(F.redact(str(x.get("state") or "")))[:60]
            for x in res.get("skipped_unknown") or [] if isinstance(x, dict) and x.get("backlog_id")}
        ls["deferred"] = {
            str(x.get("backlog_id") if isinstance(x, dict) else x):
                self._scrub(F.redact(str(x.get("reason") if isinstance(x, dict) else "") or "отложена"))[:200]
            for x in res.get("deferred") or [] if (x.get("backlog_id") if isinstance(x, dict) else x)}

    def _defer_seen(self, ls, now) -> None:
        """The triage failed: expired seen rows wait one more triage_retry_s (no busy re-triage of a broken backlog)."""
        for rec in (ls.get("seen") or {}).values():
            if isinstance(rec, dict) and self._seen_expired(rec, now):
                rec["until"] = now + self.cfg.triage_retry_s
        for bid, rec in list((ls.get("seen") or {}).items()):
            if not isinstance(rec, dict):
                ls["seen"][bid] = {"kind": str(rec), "reason": "пропущена триажем", "until": now + self.cfg.triage_retry_s}

    LOCATE_CALLS = 24       # free-model calls the localization may spend in one triage pass

    def _locate_ask(self, ls, quotas=None):
        """ask(prompt) -> text for the triage's localization: the same free channel choice, quota booking and
        redaction as the head pick (_light_ask), at most LOCATE_CALLS calls a pass. A refusal is an empty answer."""
        if quotas is None:
            quotas = ls.setdefault("locate_quotas", {})
        spent = [0]

        def ask(prompt):
            if spent[0] >= self.LOCATE_CALLS or self._bg_cancel.is_set():
                return ""
            spent[0] += 1
            status, _model, answer, _used = self._light_ask(F.redact(str(prompt)), attempt=1, section="loop-locate",
                                                            quotas=quotas, max_tokens=800)
            return answer if status == "ok" else ""
        return ask

    def _triage(self, state, tasks, ls, now) -> Outcome:
        ctx = self._triage_prepare(state, tasks, ls, now)
        try:
            res = ctx["fn"](**ctx["kwargs"])
        except (ValueError, NotImplementedError) as e:
            return self._triage_failed(e, ctx, ls)
        return self._triage_finish(res, ctx, ls)

    ESC_FAILS = 2                   # <id> rule 3: failures of one signature AFTER the tier was raised that end a task's attempts

    def _edit_dry(self, state=None) -> bool:
        """W-dry 1, the one reading of the state: every channel of the edit role is closed by the day's mark
        (factory_channels.edit_dry). Kept DRY_CACHE_S; an unreadable registry or state is 'not dry' (the normal mode)."""
        now = self.clock()
        cached = getattr(self, "_dry_cache", None)
        if cached and 0 <= now - cached[0] < DRY_CACHE_S:
            return cached[1]
        dry = False
        try:
            path = Path(self.cfg.channels)
            if path.is_file():
                configured = CH.validate(json.loads(path.read_text(encoding="utf-8"))["channels"], warn=False)
                env = {**os.environ, **self.extra_env}
                if state is None:
                    state = self.load()[1]
                quota = state.get("channel_quotas") if isinstance(state.get("channel_quotas"), dict) else {}
                seen = quota_ledger.view(quota, quota_ledger.others(path.resolve().parent / "quota", str(self.ckpt)),
                                         now=now)
                dry = bool(CH.edit_dry(configured, seen, env, now=now))
        except Exception as e:      # an aid: the normal mode stands
            self.err("edit dry", e)
        self._dry_cache = (now, dry)
        return dry

    @staticmethod
    def _has_code(task) -> bool:
        """W-dry 1: the card carries finished code and needs no edit channel: a code card whose every part has
        parts[].code, a test card with test.new.code."""
        contract = Loop._contract(task)
        if getattr(task, "kind", "") == "unit_test":
            new = (contract.get("test") or {}).get("new") if isinstance(contract.get("test"), dict) else None
            return bool(isinstance(new, dict) and isinstance(new.get("code"), str) and new["code"].strip())
        parts = contract.get("parts")
        return bool(isinstance(parts, list) and parts and all(
            isinstance(p, dict) and any(isinstance(p.get(k), str) and p[k].strip() for k in ("code", "file_text")) for p in parts))

    def _dry_blocked(self, tasks, state, state_for_dry=None) -> set:
        """W-dry 1: the READY cards without code while the edit channels are dry: the pool does not start them and they hold
        no place (an empty set in the normal mode)."""
        if not self._edit_dry(state_for_dry if state_for_dry is not None else state):
            return set()
        return {tid for tid, task in tasks.items()
                if state["tasks"].get(tid, {}).get("status") == "READY" and not self._has_code(task)}

    def _startable(self, tasks, state, now) -> list:
        """F.ready() without the cards the pool will not start now (W-dry 1)."""
        blocked = self._dry_blocked(tasks, state)
        return [t for t in F.ready(tasks, state, now=now) if t not in blocked]

    def _pool_cards(self, tasks, state, ls, now) -> list:
        """fac-53: the startable cards _act really hands to the pool now: the same skips (cards in the pool, the rows under the
        solver, the unsolved rows held for it, the rel- cards waiting behind a running solve); a card with finished code is never
        held. The held unsolved rows are those held even while READY is full (``_slice_exempt``), so the count does not depend
        on itself. Kept CARDS_FIRST_MEMO_S."""
        memo = self.__dict__.get("_cards_first_memo")
        if memo is not None and 0 <= now - memo[0] < CARDS_FIRST_MEMO_S:
            return memo[1]
        to_slice = ls.get("to_slice", {})
        first = {r for r in self._solver_first_rows(tasks, state, ls, now) if self._slice_exempt(r, to_slice.get(r))}
        busy, out = self.pool.tids(), []
        for t in self._startable(tasks, state, now):
            task = tasks[t]
            bid = str(task.backlog_id or t)
            row, engine = F.row_of(bid), state["tasks"].get(t, {}).get("engine")
            if t in busy:
                continue
            if not self._has_code(task) and (row in self._hypers or (row in first and engine != "solver")):
                continue
            out.append(t)
        self._cards_first_memo = (now, out, len(out) >= self._cards_first_bar())
        return out

    def _cards_first_bar(self) -> int:
        return SLICE_AHEAD_X * max(len(self.pool.workers), SLICE_AHEAD_MIN)

    def _cards_first(self, tasks, state, ls, now, rank=None) -> bool:
        """fac-53: True while the cards the pool takes now (``_pool_cards``) are at least SLICE_AHEAD_X x max(live pool,
        SLICE_AHEAD_MIN): the free models go to those cards, no new slicing / solving starts (but ``_slice_exempt`` rows).
        ``rank``: only the cards of that row_rank or higher count (W-prio2: an ECHO row never waits for the old reds)."""
        cards = self._pool_cards(tasks, state, ls, now)
        if rank is not None:
            cards = [t for t in cards if F.row_rank(F.row_of(tasks[t].backlog_id or t)) <= rank]
        return len(cards) >= self._cards_first_bar()

    def _loop_head_priority(self, role):
        """fac-53: the head priority of the loop's own calls (slicing, solving, holds, locate, keywords, links): behind every
        ticket of a card while READY is full (the last ``_pool_cards`` count, younger than CARDS_FIRST_STALE_S); otherwise a
        review-routed call (slice / aux) keeps the review's place it had before fac-53 and the rest the head's default."""
        from tools import factory_head as HD
        if Loop._loop_ready_full(self):
            return LOOP_YIELD_PRIORITY
        return HD.PRIORITY["review"] if role in ("slice", "aux") else None

    def _loop_ready_full(self) -> bool:
        """fac-57: READY is full by the last ``_pool_cards`` count (younger than CARDS_FIRST_STALE_S)."""
        memo = getattr(self, "_cards_first_memo", None)
        clock = getattr(self, "clock", None)
        return bool(memo is not None and clock is not None and 0 <= clock() - memo[0] < CARDS_FIRST_STALE_S and memo[2])

    def _loop_head_floor(self):
        """fac-57: the level the loop's head ticket never ages below: LOOP_YIELD_PRIORITY while READY is full (the head's
        AGE_S would lift a slicing ticket past the cards' edit / code in 2 minutes, past their review in 3), else None
        (the plain ageing: the slicing never starves while READY is thin)."""
        return LOOP_YIELD_PRIORITY if Loop._loop_ready_full(self) else None

    @staticmethod
    def _slice_exempt(row, entry=None) -> bool:
        """fac-53: the only rows sliced / solved whatever waits in READY: a fresh regression rel-<sha8>-<n> (row_rank 0). A row
        with a ready red test (guard) waits by its rank like any other (live 27.11: 77 of 108 queued rows had a guard, the
        exemption gave slicing 82 of 143 free calls while 39 cards waited); ``entry`` is kept for the callers."""
        return F.row_rank(row) == 0

    def _ready_topup(self, state, tasks, ls, now) -> bool:
        """<id>: READY below cfg.ready_target and the backlog may give more: the next portion is prefetched at once, without
        the empty-portion term (triage_retry_s) and without READY having to be empty. A portion that gave nothing doubles
        the wait (up to triage_retry_s), so an exhausted backlog is not read every minute. Rows of the not_code book stay
        known (never offered). True when a prefetch started."""
        cfg = self.cfg
        try:
            if cfg.ready_target <= 0 or self._bg is not None or self._ending() or not cfg.backlog.exists():
                return False
            # W-feed 4: what counts is what ready() can START now (not READY rows held back by a clash, a term or a
            # dependency), and the bar is the pool ceiling, not the old queue target
            ready = len(self._startable(tasks, state, now))
            ceiling = max(cfg.ready_target, getattr(factory_cloud_gate, "MAX_LIVE", 30))
            if ready >= ceiling:
                return False
            wait = min(cfg.ready_triage_s * 2 ** int(ls.get("ready_triage_idle") or 0), cfg.triage_retry_s)
            if now - float(ls.get("ready_triage_at") or 0) < wait:
                return False
            ls["ready_triage_at"] = now
            return self._triage_prefetch(state, tasks, ls, now, limit=max(cfg.triage_limit, ceiling - ready), topup=True)
        except Exception as e:                     # an aid: it never stops the loop
            self.err("ready top-up", e)
            return False

    @staticmethod
    def _contract(task):
        try:
            value = json.loads(getattr(task, "contract", "") or "{}")
            return value if isinstance(value, dict) else {}
        except (ValueError, TypeError):
            return {}

    def _slice_light(self, budget, text, *, max_tokens, role, temperature=0):
        """W-path A: one slicing call that does not give up at the first refusal. 429/500/503: the channel is cooled by
        _light_ask, so the next call takes another channel of the step at once (up to SLICE_HOPS, then a short wait). no_channel:
        wait the time the booking names (``why``), outside _ask_lock, within SLICE_WAIT_CALL_S per call and the job's
        ``budget`` (SLICE_WAIT_JOB_S); a channel closed for the day is not waited for; STOP ends the waiting."""
        waited, hops = 0.0, 0
        while True:
            why = {}
            result = self._light_ask(text, attempt=1, section="loop-architect", quotas=self._arch_quotas,
                                     max_tokens=max_tokens, role=role, why=why, temperature=temperature)
            status = result[0]
            if status == "ok":
                return result
            if status in ("http_429", "http_500", "http_503"):
                hops += 1
                if hops <= SLICE_HOPS:
                    continue
                hops, wait = 0, 5.0
            elif status == "no_channel":
                if why.get("reason") == "rpd":
                    return result               # closed for the day: nothing to wait for
                wait = float(why.get("wait_s") or 0) or 5.0
            else:
                return result
            wait = min(wait, SLICE_WAIT_CALL_S - waited, budget["left"])
            if wait <= 0 or self.stop.exists():
                return result
            slept = 0.0
            while slept < wait and not self.stop.exists():
                step = min(5.0, wait - slept)
                self._sleep(step)
                slept += step
            waited += slept
            budget["left"] -= slept

    def _asks(self, root=None) -> dict:
        from tools import factory_architect as A, factory_paid_critic as PK
        asks = {}
        budget = {"left": SLICE_WAIT_JOB_S}       # W-path A: the waits of ONE slicing job (one _asks per job) share this
        for engine in self.cfg.architect_rungs:
            if engine in ("free", "free_main"):
                role = "architect" if engine == "free" else "code"
                def ask(system, user, role=role):
                    status, _, answer, _ = self._slice_light(budget, system + "\n\n" + user, max_tokens=12000, role=role)
                    if status != "ok":
                        raise A.ContractFault(status)
                    return answer
                asks[engine] = ask
            elif engine == "free_small":
                small = self._small_ask()
                if small is not None:
                    asks[engine] = small
            elif engine == "paid":
                if PK.key_available():              # read now, on every slicing: a revived key brings the stage back
                    asks[engine] = A.ask_paid
            elif engine == "agent" and callable(getattr(A, "ask_agent", None)) and shutil.which("claude"):
                if PK.key_available() and not PK.agent_credit_dead():
                    asks[engine] = lambda system, user, _root=root: A.ask_agent(system, user, cwd=_root)
        return asks

    SMALL_SLICE_MAX = 6        # W-gslice 3 / W-prio 1: slicing ensembles of the small tier at one time (was 3)

    @staticmethod
    def _is_base_tid(tid) -> bool:
        """W-prio 1: a card of the old baseline debt rel-base-<n> (its task id is bl_rel_base_<n>...)."""
        return str(tid or "").startswith("bl_rel_base_")

    SMALL_YIELD_S = 20         # a card that waits for the small tier longer than this goes before the slicing

    def _small_wait_note(self, tid, now):
        """W-gslice 3: a card was deferred by the minute limit of its channel: the editors wait for the small tier from ``now``."""
        waits = self.__dict__.setdefault("_small_waits", {})
        if self._is_base_tid(tid):
            return      # W-prio 1: the slicing does not give way to the rel-base cards
        if tid and (tid not in waits or now - waits[tid] > 300):
            waits[tid] = now

    def _small_yield(self) -> bool:
        """W-gslice 3: True when an editor card has waited for the small tier longer than SMALL_YIELD_S (within 5 minutes
        of its deferral): the slicing gives way."""
        now = self.clock()
        waits = self.__dict__.setdefault("_small_waits", {})
        for tid in [t for t, since in waits.items() if now - since > 300]:
            waits.pop(tid, None)
        return any(now - since > self.SMALL_YIELD_S for since in waits.values())

    def _small_ask(self):
        """W-gslice 1/3: the ask of the 'free_small' step: ``ask(system, user, temperature=, channel=)`` -> the answer of one
        small-tier model (Gemma), max 4096 tokens, reasoning as the model body says (minimal); ``ask.channels`` are the
        small-tier models (one voice each by the circle), ``ask.gate`` limits the ensembles to SMALL_SLICE_MAX at a time and
        lets the editors go first. None when no small channel is registered."""
        from tools import factory_architect as A, factory_ensemble as ENS
        try:
            configured = json.loads(Path(self.cfg.channels).read_text(encoding="utf-8"))["channels"]
        except (OSError, ValueError, KeyError):
            return None
        models = sorted({c["model"] for c in configured if CH.tier_of(c) == "small" and not CH.is_reserve(c)})
        if not models:
            return None
        sem = self.__dict__.setdefault("_small_sem", threading.BoundedSemaphore(self.SMALL_SLICE_MAX))
        loop = self

        def ask(system, user, temperature=None, channel=None):
            if loop._small_yield():
                raise ENS.ChannelRefused("editors wait for the small tier", kind="yield")
            if self._arch_quotas is None:
                self._arch_quotas = {}
            why = {}
            status, _, answer, _ = loop._light_ask(system + "\n\n" + user, attempt=1, section="loop-architect",
                quotas=loop._arch_quotas, max_tokens=A.SMALL_MAX_TOKENS, role="slice", only_tier="small",
                only_model=channel or "", temperature=0.2 if temperature is None else temperature, why=why)
            if status == "ok":
                if not answer.strip():
                    raise ENS.ChannelRefused("empty answer", kind="other")
                return answer
            if status == "http_503":
                raise ENS.ChannelRefused(status, kind="overload")
            if status == "http_429":
                raise ENS.ChannelRefused(status, kind="minute", wait_s=20)
            if status == "http_0":
                raise ENS.ChannelRefused(status, kind="timeout")
            if status == "no_channel":        # W-prio3: the booking gave no channel; its reason says what to do
                reason, wait = why.get("reason", ""), float(why.get("wait_s") or 0)
                if reason in ("tpm_window", "rpm"):     # our own minute booking: the branch waits ITS channel to the end of the window
                    raise ENS.ChannelRefused(status + ":" + reason, kind="minute_local", wait_s=min(60.0, max(1.0, wait)))
                if reason == "rpd":
                    raise ENS.ChannelRefused(status + ":" + reason, kind="day")
                if reason == "cool":
                    raise ENS.ChannelRefused(status + ":" + reason, kind="minute", wait_s=min(60.0, max(1.0, wait)))
            raise ENS.ChannelRefused(status)       # the rest: no answer, the branch gives up after a few tries

        class Gate:
            def __enter__(self):
                if loop._small_yield() or not sem.acquire(blocking=False):
                    raise A.ContractFault("no_channel")     # no ensemble now: the row waits (SliceWait), no cost
                return self

            def __exit__(self, *exc):
                sem.release()
                return False
        ask.channels = models if len(models) > 1 else None
        ask.gate = Gate()
        small_ids = [c["id"] for c in configured if CH.tier_of(c) == "small" and not CH.is_reserve(c)]

        def capacity():
            """W-a2: the head's free places of the small channels (None: no head; HeadDown: it does not answer)."""
            from tools import factory_head as HD
            state = Path(loop.cfg.channels).resolve().parent / HD.STATE_NAME
            return HD.capacity(state, small_ids) if HD.alive(state) else None
        ask.capacity = capacity
        return ask

    def _ladder_sig(self):
        return ",".join(self._asks())

    TRACE_CLUE_CHARS = 1800

    def _trace_clue(self, tid, rec) -> str:
        """A reading of one card's red base for the architect: the failing tests, the first lines of the failure and the
        functions the failing run went through, by file (the trace of base_red), so a part names the right function
        and file instead of the one the first slicing guessed."""
        result = (rec.get("base_red") or {}).get("result") or {}
        try:
            trace = F.get_trace(self.cfg.state_dir, rec)
        except (TypeError, ValueError, AttributeError):
            trace = ()
        by_file: dict = {}
        for call in trace:
            by_file.setdefault(str(call[0]), [])
            if str(call[1]) not in by_file[str(call[0])]:
                by_file[str(call[0])].append(str(call[1]))
        lines = ["red base of %s: failing %s" % (tid, ", ".join(map(str, result.get("failed_ids") or [])) or "?"),
                 str(result.get("diag") or "")[:600], "the failing run went through:"]
        lines += ["  %s: %s" % (f, ", ".join(q[:60] for q in qs[:12])) for f, qs in list(by_file.items())[:20]]
        if not by_file:
            lines.append("  (no trace kept)")
        return "\n".join(lines)[:self.TRACE_CLUE_CHARS]

    DOSSIER_CHARS = 40000

    def _hard_dossier(self, previous, state, entry, root) -> str:
        """W-hard 4: the full package for the architect at rung >= 2 (agent / paid): the text of the red test, the code
        along the path of its failure (the functions of the base_red trace, whole), the diff and the failure of the two
        last red fixes, and the contracts of the earlier generations. Private text is cut, everything is redacted."""
        from tools import factory_architect as A
        def safe(value, cap):
            text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
            return "" if F.is_private_text(text) else F.redact(text)[:cap]
        out = []
        tests = []
        for task in previous:
            tests.extend(t for t in task.tests if t not in tests)
        guard = str(entry.get("guard") or "").partition("::")[0]
        if guard and guard not in tests:
            tests.append(guard)
        for rel in tests[:4]:
            try:
                path = (Path(root) / F.safe_path(rel)).resolve()
                if path.is_relative_to(Path(root).resolve()) and path.is_file():
                    if text := safe(path.read_text(encoding="utf-8-sig"), 6000):
                        out.append("RED TEST FILE %s\n%s" % (rel, text))
            except (OSError, ValueError, UnicodeError):
                continue
        ranked, seen = [], set()
        for task in previous:
            rec = state["tasks"].get(task.id, {})
            try:
                trace = F.get_trace(self.cfg.state_dir, rec) if rec.get("base_red") else ()
            except (TypeError, ValueError, AttributeError):
                trace = ()
            for call in trace:
                key = (str(call[0]), str(call[1]))
                if key not in seen and not key[0].startswith("tests/"):
                    seen.add(key)
                    ranked.append((key[0], key[1], 0))
        if ranked:
            if bodies := A.hint_sources(root, ranked[:40], places=8, cap=16000):
                out.append("CODE ALONG THE PATH OF THE RED TEST (functions of the base_red trace, whole):\n" + bodies)
        reds = [t for t in previous if t.kind == "code" and state["tasks"].get(t.id, {}).get("reason") == "reslice"]
        reds.sort(key=lambda t: (int((re.search(r"_r(\d+)$", t.id) or [None, "0"])[1]), t.id))
        for task in reds[-2:]:
            rec = state["tasks"].get(task.id, {})
            diff = self.stage / "prev-diff" / (task.id + ".diff")
            body = diff.read_text(encoding="utf-8", errors="replace") if diff.is_file() else ""
            out.append("RED FIX %s: failure:\n%s\ndiff:\n%s" % (
                task.id, safe("\n".join(map(str, rec.get("feedback", [])[-2:])), 3000), safe(body, 4000) or "(no diff kept)"))
        if len(reds) >= 2:      # W-path D: two red fixes of product code with the same failure: the stand itself may be out of date
            ends = [" ".join(str((state["tasks"].get(t.id, {}).get("feedback") or [""])[-1]).split())[:200] for t in reds[-2:]]
            if ends[0] and ends[0] == ends[1]:
                out.append(self.STAND_HINT)
        for task in sorted(previous, key=lambda t: t.id)[-6:]:
            if task.contract and (text := safe(task.contract, 4000)):
                out.append("CONTRACT OF AN EARLIER GENERATION (%s):\n%s" % (task.id, text))
        return "\n\n".join(out)[:self.DOSSIER_CHARS]

    STAND_HINT = ("CHECK WHETHER THE STAND IS OUT OF DATE: two fixes of the product code failed with the same failure. If the "
                  "test, its fixture or conftest is what is broken (a parameter or attribute that does not exist, an expectation "
                  "of a setting that was changed), answer a rig contract (rig: true, ready code or file_text of the stand, the "
                  "checks themselves untouched) instead of a third product fix.")

    # ---- W-redrow 1, 2: a row with a ready red test carries the proof of the red --------------------------------------
    RED_SOURCE_CHARS = 6000
    RED_HELPER_CHARS = 2000
    RED_HELPERS_TOTAL = 4000

    @staticmethod
    def _is_red_row(row, entry) -> bool:
        """A row that comes with a ready red test: the guard of the entry, or a rel-... regression / baseline-debt row."""
        return bool((entry or {}).get("guard")) or str(row).startswith("rel-")

    @classmethod
    def _red_test_source(cls, root, name) -> list:
        """[the text of the red test (the whole function, with its decorators), then one piece per helper it calls that lives
        in the same file (module functions: called by name or taken as fixtures)]; [] when it cannot be read."""
        import ast
        rel, _, rest = str(name).partition("::")
        path = (Path(root) / F.safe_path(rel)).resolve()
        if not rel.endswith(".py") or not path.is_relative_to(Path(root).resolve()) or not path.is_file():
            return []
        text = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(text)
        lines = text.splitlines()

        def segment(node):
            first = min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])])
            return "\n".join(lines[first - 1:node.end_lineno])
        scope, target = tree.body, None
        for part in [p.split("[", 1)[0] for p in rest.split("::") if p]:
            target = next((n for n in scope if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                           and n.name == part), None)
            if target is None:
                break
            scope = target.body
        if target is None:
            return []
        out = ["TEST SOURCE (%s)\n%s" % (name, segment(target)[:cls.RED_SOURCE_CHARS])]
        top = {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        wanted = [n.func.id for n in ast.walk(target) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
        if isinstance(target, (ast.FunctionDef, ast.AsyncFunctionDef)):
            wanted += [a.arg for a in target.args.args + target.args.kwonlyargs]
        total = 0
        for helper in dict.fromkeys(w for w in wanted if w in top and w != getattr(target, "name", "")):
            body = segment(top[helper])[:cls.RED_HELPER_CHARS]
            if total + len(body) > cls.RED_HELPERS_TOTAL:
                break
            total += len(body)
            out.append("HELPER OF THE TEST %s (same file):\n%s" % (helper, body))
        return out

    def _measure_red(self, name, sha, root) -> str:
        """The failure text of a red test of a base the build did not report: ONE short cloud run of its file, once per
        (test, sha) (the answer, text or none, is cached in <state>/release/measure.json).  '' when the cloud gave nothing
        (not cached: it is tried again)."""
        from tools import factory_release as REL
        if self.sweep_fn is None or not sha:
            return ""
        book_path = REL.release_dir(self.cfg.state_dir) / "measure.json"
        key = "%s@%s" % (name, sha)
        book = REL._read_json(book_path, {})
        if key in book:
            return str(book[key] or "")
        rel = str(name).partition("::")[0]
        if not rel.endswith(".py") or not (Path(root) / rel).is_file():
            return ""       # W-gate: a test the base does not have (a card's own new guard) has no red to measure on it
        try:
            _p, res, _id = self.sweep_fn(src=root, files=[rel], shards=1, wait_s=900,
                                         label=REL.next_label(self.cfg.state_dir, sha, prefix="rel-m"))
        except Exception as exc:                    # the cloud is down / queued / blocked: no measure now, no cache
            self.err("red measure", exc)
            return ""
        row = (res or {}).get(rel)
        if not isinstance(row, dict) or row.get("missing"):
            return ""
        texts = row.get("failures") or {}
        text = str(texts.get(name) or next((t for n, t in texts.items() if n.split("::")[-1] == str(name).split("::")[-1]), ""))
        book = REL._read_json(book_path, {})
        book[key] = text[-REL.FAILURE_CHARS:]
        if len(book) > 400:
            book = dict(list(book.items())[-400:])
        REL._write_json(book_path, book)
        return book[key]

    def _red_clues(self, row, entry, root) -> list:
        """Pieces of the packet's evidence for a row with a red test: the failure text the build saved (or the one cloud
        measure of the base), the test's source and its helpers.  Each piece passes the packet's filters on its own."""
        from tools import factory_release as REL
        name = str(entry.get("guard") or "")
        if not name:
            rec = REL.regressions(self.cfg.state_dir)
            name = next((n for n, r in rec.items() if r.get("row") == row), "")
        if not name:
            return []
        out = ["THE TEST %s IS RED ON THIS TREE (measured)." % name]
        text = REL.failure_of(self.cfg.state_dir, name)
        if not text:
            text = self._measure_red(name, str(getattr(self, "base_sha", "") or ""), root)
        out.append(("FAILURE OF THE RED TEST (assert, message, last frames):\n" + text) if text
                   else "No failure text of this test was saved or measured: read the test and the code yourself.")
        try:
            out.extend(self._red_test_source(root, name))
        except (OSError, ValueError, SyntaxError, UnicodeError):
            pass
        return out

    SOLVER_MAX_TOKENS = 4000        # W-solver: the answer of one step (reasoning + one command)
    SOLVE_SILENT_S = 900.0          # fac-55: the waits for a channel of ONE solve (503/429/no channel are not steps), and the age at
                                    # which a solve no model has answered yet lets its row go (live 26-27.11: the answers of the slice
                                    # role came at most 647 s apart, <id> 389 s; the old 3600 s wait equalled HYPO_STALE_S, so no
                                    # solve ever ended as no_channel: it was dropped as stale after an hour instead)
    SOLVER_TEMPERATURE = 0.4
    SOLVER_RETRY_S = 4.0            # a pause between two askings of the open channels

    def _solver_channels(self) -> list:
        """W-solver: the free channels a solve may use (main and small tiers, not reserve); [] when channels.json does not read."""
        try:
            configured = json.loads(Path(self.cfg.channels).read_text(encoding="utf-8"))["channels"]
            return [c for c in configured if CH.tier_of(c) in ("main", "small") and not CH.is_reserve(c)]
        except (OSError, ValueError, KeyError, TypeError):
            return []

    def _solver_limit(self) -> int:
        """W-solver: as many solves at once as there are free channels (each step of a solve takes one booking of one)."""
        return len(self._open_channels())

    def _open_channels(self) -> list:
        """The solver's channels without those the day's mark closed: the solves and the slicings at one time are as many as the open
        channels can answer (live 25.11 14:00: 10 solves and 12 slicings on 4 channels answered nobody)."""
        from tools import factory_quota as Q
        channels = self._solver_channels()
        try:
            held = Q.gate_closed(Path(self.cfg.channels).resolve().parent / "quota",
                                 since={c["id"]: CH.quota_day(c["model"], self.clock())[0] for c in channels})
        except (OSError, ValueError, KeyError, TypeError):
            held = ()
        return [c for c in channels if c["id"] not in held] or channels[:1]

    def _slice_parallel(self) -> int:
        """SLICE_PARALLEL while a main or a small (Gemma) channel is open; else half of the open small channels (the solves have the other half)."""
        live = self._open_channels()
        from tools import factory_paid_critic as PK
        try:
            money = "paid" in self._asks() and not PK.credit_dead() and PK.left(PK._today()) - PK._external("FACTORY_BUILDERS_WAITING", ("usd",)) > 0.3
        except Exception:       # noqa: BLE001  unknown money: none
            money = False
        if any(CH.tier_of(c) in ("main", "small") for c in live) or money:     # <id>: Gemma open is full width too
            return SLICE_PARALLEL
        return max(1, len(live) // 2)

    def _solver_ctx(self, root, packet, avoid=""):
        """W-solver: the environment of one solve over the loop's own parts: the ask of the free channels (Gemma first on the compact
        text to the small tier, then the waiting route of the slicer) and the cloud batch. Never raises a refusal as a step:
        NoChannel after the waits."""
        from tools import factory_hypo as HY, factory_solver as SV
        if self._arch_quotas is None:
            self._arch_quotas = {}
        loop, budget, info = self, {"left": self.SOLVE_SILENT_S}, {}
        me = threading.current_thread()

        def heard(answer):      # fac-55: the collector lets a solve go when no model has answered it for SOLVE_SILENT_S
            me.heard = time.monotonic()
            budget["left"] = loop.SOLVE_SILENT_S    # the wait is of ONE silence (between two answers), not a sum over the solve
            return answer
        cancel = getattr(threading.current_thread(), "cancel", None)    # fac-choke: the Event of the Prefetch job (None off a job)

        def dropped():
            return cancel is not None and cancel.is_set()

        def ask(text, small=None):
            if dropped():
                raise SV.Cancelled("solve dropped")
            for _ in range(10):         # a waiting review of a green candidate takes the channels first (at most ~20 s a step)
                if not loop._review_hold() or loop.stop.exists() or dropped():
                    break
                loop._sleep(2.0)
            if avoid:       # the second pass of a STALE answer goes to another model (another channel) than the first one
                for chan in loop._solver_channels():
                    if chan["model"] == avoid:
                        continue
                    status, model, answer, _ = loop._light_ask(small if small is not None and CH.tier_of(chan) == "small" else text,
                                                               attempt=1, section="loop-architect", quotas=loop._arch_quotas,
                                                               max_tokens=loop.SOLVER_MAX_TOKENS, role="slice",
                                                               only_channel=chan["id"], temperature=loop.SOLVER_TEMPERATURE)
                    if status == "ok" and str(answer).strip():
                        info["model"] = model
                        return heard(answer)
            # a refused minute is waited out, the steps made are never thrown away: the open channels are asked again every few seconds
            while True:
                for body, tier, role in ((small, "small", "slice"), (text, "main", "slice")):    # fac-53: role slice (routes as a review / Gemma first); owner: Gemma (57 600 calls a day) solves first, Flash-Lite is for slicing
                    if body is None:
                        continue
                    status, model, answer, _ = loop._light_ask(body, attempt=1, section="loop-architect", quotas=loop._arch_quotas,
                                                               max_tokens=loop.SOLVER_MAX_TOKENS, role=role, only_tier=tier,
                                                               temperature=loop.SOLVER_TEMPERATURE)
                    if status == "ok" and str(answer).strip():
                        info["model"] = model
                        return heard(answer)
                if dropped():
                    raise SV.Cancelled("solve dropped")
                if budget["left"] <= 0 or loop.stop.exists():
                    break
                budget["left"] -= loop.SOLVER_RETRY_S
                loop._sleep(loop.SOLVER_RETRY_S)
            raise SV.NoChannel(status)
        return SV.Ctx(root=root, ask=ask, cloud=lambda r, ids, files: HY.cloud_batch(r, ids, files, tid="s" + str(packet.get("bid"))),
                      info=info, sleep=self._sleep, cancel=cancel)

    def _solver_suspects(self, root, packet, ids, failure) -> list:
        """W-solver: the product functions of the red test, most suspicious first: the failure stack, the guilty commit's diff, the
        trace of the guard, the rest in the repomap order of the row's own words (up to 15 lines 'file :: symbol')."""
        from tools import factory_hypo as HY
        trace = [(t[0], t[1], 0) for t in packet.get("trace_path") or ()]
        diff = HY.diff_funcs_of(packet.get("bisect_clue"))      # the functions of the guilty commit's diff (the bisect proof of the packet)
        title = str(packet.get("title") or "")
        key = (str(self.base_sha), title)       # the heavy pure work once per base and words, one thread at a time
        cache = self.__dict__.setdefault("_rank_cache", {})
        with self.__dict__.setdefault("_rank_lock", threading.Lock()):
            if key not in cache:
                try:
                    from tools import repomap
                    found = [(r[0], r[1]) for r in repomap.rank(root, title)] if title else []
                except (ImportError, OSError, ValueError):
                    found = []
                for old in [k for k in cache if k[0] != key[0]]:
                    cache.pop(old, None)
                cache[key] = found
            ranked = cache[key]
        funcs = HY.rank_functions(root, stack=HY.stack_from_failure(failure), diff=diff, trace=trace, ranked=ranked, k=15)
        if not funcs:       # no trace and no rank: the product functions the test itself imports or calls
            funcs = HY.rank_functions(root, ranked=HY.test_functions(root, ids[0]), k=15)
        return ["%s :: %s" % (f["file"], f["symbol"]) for f in funcs]

    def _solver_run(self, row, ids, packet, root) -> dict:
        """W-solver: ONE solve of the row (a worker thread: reads and asks only). The ids of ONE failure signature (the biggest group
        not searched lately) are the target; the result is a Result of factory_solver in a dict with its group."""
        from tools import factory_hypo as HY, factory_solver as SV
        groups = HY.group_ids(ids, self._hypo_failure_of)
        skip = self._hypo_cooled_groups()
        sig, gids = next((g for g in groups if g[0] not in skip), groups[0])
        evidence = str(packet.get("evidence") or "")
        marker = "FAILURE OF THE RED TEST (assert, message, last frames):\n"
        failure = self._hypo_failure_of(gids[0]) or (evidence.partition(marker)[2][:4000] if marker in evidence else "")
        suspects = self._solver_suspects(root, packet, gids, failure)
        vote = (self.ls().get("stale_votes") or {}).get(row)
        avoid = str(vote.get("model") or "") if isinstance(vote, dict) and vote.get("test") == gids[0] else ""
        t0 = time.monotonic()
        res = SV.solve(self._solver_ctx(root, packet, avoid=avoid), row, gids, failure, HY._test_body(root, gids[0]), suspects)
        if not getattr(res, "why", "") == "cancelled":     # fac-choke: a dropped solve leaves no stats and no trace (it must not overwrite a newer attempt of the row)
            SV.STATS.add(res)
            self._solver_save_trace(row, res, gids)
        return dict(result=res, group=sig, ids=gids, secs=time.monotonic() - t0)

    SOLVER_TRACE_FILES = 60     # the saved full traces of the solves: the newest files only

    def _solver_save_trace(self, row, res, ids) -> None:
        """W-solver: the full trace (every reply and result, redacted, up to 40 KB) in <state>/solver_trace/<row>.json, at most
        SOLVER_TRACE_FILES files (the oldest go). An aid: a failure here never stops the solve."""
        from tools import factory_solver as SV
        try:
            folder = Path(self.cfg.state_dir) / "solver_trace"
            folder.mkdir(parents=True, exist_ok=True)
            (folder / (re.sub(r"[^\w.-]", "_", str(row)) + ".json")).write_text(
                SV.trace_text(res, row, ids, redact=F.redact), encoding="utf-8")
            files = sorted(folder.glob("*.json"), key=lambda f: f.stat().st_mtime)
            for old in files[:-self.SOLVER_TRACE_FILES]:
                old.unlink(missing_ok=True)
        except Exception as exc:        # noqa: BLE001  an aid
            self.err("solver trace", exc)

    def _solver_stale(self, row, gids, res) -> bool:
        """W-solver: a proven STALE answer. The first one is a vote (the model, the test, the proof); the second pass by ANOTHER model
        on the same test that also says STALE puts the row into ls['outdated_tests'] (source 'solver', no cards, no slicing, 24 h).
        True when the row was booked as outdated now. Loop thread only."""
        ls, now = self.ls(), self.clock()
        test, model, stale = str(gids[0]), str(res.model or ""), res.stale or {}
        votes = ls.setdefault("stale_votes", {})
        vote = votes.get(row)
        if not (isinstance(vote, dict) and vote.get("test") == test and vote.get("model") != model and model):
            votes[row] = dict(test=test, model=model, ref=stale.get("ref"), phrase=stale.get("phrase"), at=now, base=str(self.base_sha))
            self.save_ls(ls)
            self.event("solver", backlog_id=row, status="stale_vote", why=self.rs(stale.get("phrase"), 200), model=model or None)
            return False
        votes.pop(row, None)
        ls.setdefault("outdated_tests", {})[row] = {
            "test": test, "names": [{"kind": "assert against code", "name": str(stale.get("ref")), "last": ""}], "at": now,
            "sha": str(self.base_sha)[:12], "source": "solver", "why": self.rs(stale.get("phrase"), 200), "models": [vote.get("model"), model]}
        for key in ("to_slice", "slice_wait", "reslices", "quarantine"):
            if isinstance(ls.get(key), dict):
                ls[key].pop(row, None)
        self.save_ls(ls)

        def supersede(st):
            for tid, rec in st["tasks"].items():
                if F.row_of(rec.get("backlog_id") or tid) == row and rec.get("status") == "READY":
                    rec.update(status="FAILED", reason="superseded:outdated_test")
        try:
            self._tx(supersede)
        except Exception as exc:        # noqa: BLE001  a busy plan: the cards are no longer admitted anyway
            self.err("solver stale: supersede", exc)
        try:
            from tools import factory_outdated as OD
            (self.cfg.state_dir / "outdated_tests.md").write_text(OD.report_md(ls["outdated_tests"]), encoding="utf-8")
        except OSError as exc:
            self.err("solver stale: report", exc)
        self.event("supply", status="outdated_test", backlog_id=row,
                   reason="outdated_test: two models say STALE: %s" % self.rs(stale.get("phrase"), 160))
        return True

    def _red_last_keys(self, ids=()):
        """W-part 2: the red test keys of the last full verdict when its sha is the base or an ancestor of it, else None (unknown)."""
        from tools import factory_release as REL
        rec = REL.red_last(self.cfg.state_dir)
        sha, base = str(rec.get("sha") or ""), str(self.base_sha or "")
        if not sha or not base or not isinstance(rec.get("red"), list):
            return None
        if sha != base:
            seen = self.__dict__.setdefault("_ancestor_cache", {})
            if (sha, base) not in seen:
                try:
                    git_run(self.cfg.repo, "merge-base", "--is-ancestor", sha, base)
                    seen[(sha, base)] = True
                except subprocess.CalledProcessError as exc:
                    if exc.returncode != 1:         # not a git answer (a missing sha...): unknown, not cached
                        return None
                    seen[(sha, base)] = False
                except OSError:
                    return None
            if not seen[(sha, base)]:
                return None
        red = {REL._key(n) for n in rec["red"]}
        if sha != base:                     # an ancestor: a test red only later is unknown there, so only ids known earlier may be dropped
            prev = REL.red_pair(REL.release_dir(self.cfg.state_dir)).get("prev") or set()
            return red | {REL._key(i) for i in ids if REL._key(i) not in prev}
        return red

    def _hypo_ids(self, row, packet, raw=False):
        """W-hyp 1: the red test ids of the row in the order guard -> rel-<sha> regression -> rel-base-<n> debt (runnable ids only).
        W-part 2: the ids that are not red in the last full build (its sha the base or an ancestor) are dropped (``raw``: kept)."""
        ids = self._hypo_ids_all(row, packet)
        if raw or not ids:
            return ids
        from tools import factory_release as REL
        red = self._red_last_keys(ids)
        return ids if red is None else [i for i in ids if REL._key(i) in red]

    def _packet_green_on_row(self, row, packet) -> bool:
        """W-part 2: the row has runnable ids and none is red in red_last; cached per (row, base, red_last sha) - the loop thread
        builds packets on every pass."""
        from tools import factory_release as REL
        key = (str(row), str(self.base_sha), str(REL.red_last(self.cfg.state_dir).get("sha") or ""))
        cache = self.__dict__.setdefault("_row_green_cache", {})
        if key not in cache:
            if len(cache) > 500:
                cache.clear()
            cache[key] = bool(self._hypo_ids_all(row, packet) and not self._hypo_ids(row, packet))
        return cache[key]

    def _hypo_ids_all(self, row, packet):
        from tools import factory_hypo as HY, factory_release as REL
        rel = base = None
        try:
            if str(row).startswith("rel-base-"):
                from tools import factory_bisect as BIS
                base = BIS.row_tests(self.cfg.state_dir, row)
            elif str(row).startswith("rel-"):
                rel = [n for n, r in REL.regressions(self.cfg.state_dir).items() if r.get("row") == row]
        except Exception as exc:        # noqa: BLE001  an aid: no ids, no search
            self.err("hypo ids", exc)
        return [i for i in HY.pick_red(packet.get("guard_red"), rel, base) if "::" in i]

    def _hypo_take_spare(self, row, root, packet):
        """W-hyp 4: the next green candidate kept from the search of this base (the smaller diff went first), None when none is left."""
        from tools import factory_architect as A
        keep = self.ls()
        rec = (keep.get("hypo_spare") or {}).get(row)
        if not isinstance(rec, dict):
            return None
        left = list(rec.get("contracts") or ()) if rec.get("base") == str(self.base_sha) else []
        while left:
            contract = left.pop(0)
            if not A.validate(contract, root, bid=row, known_ids=packet.get("known_ids"), engine="solver"):
                break
            contract = None
        else:
            contract = None
        if left:
            keep["hypo_spare"][row] = dict(base=str(self.base_sha), contracts=left)
        else:
            keep["hypo_spare"].pop(row, None)
        self.save_ls(keep)
        if contract is not None:
            self.event("solver", backlog_id=row, status="spare", steps=0, calls=0, tests=0)
        return contract

    def _hypo_state(self, row, packet):
        """W-feed2 2: what a row needs from the search, by reads only: ('off' | 'none' (no red id) | 'spare' (a kept green
        candidate of this base) | 'cooled' (searched less than 12 h ago) | 'search', the red ids)."""
        from tools import factory_hypo as HY
        if self.cfg.self_repo:
            return "off", []
        ids = self._hypo_ids(row, packet)
        if not ids:
            return ("already_green" if self._hypo_ids(row, packet, raw=True) else "none"), []
        keep = self.ls()
        rec = (keep.get("hypo_spare") or {}).get(row)
        if isinstance(rec, dict) and rec.get("base") == str(self.base_sha) and rec.get("contracts"):
            return "spare", ids
        sigs = self._hypo_sigs(row, ids)     # W-part 5: the cooldown is of (base, group signature)
        if all(HY.cooled(keep.get("hypo_seen", {}), str(self.base_sha), s, time.time()) for s in sigs):
            return "cooled", ids
        return "search", ids

    def _hypo_sigs(self, row, ids) -> list:
        """Group signatures of the row's ids. The failures book is read once per change of the file (stat key), the grouping is
        cached per (row, base, red_last sha, ids): the feeder asks about many rows on every pass."""
        from tools import factory_hypo as HY, factory_release as REL
        state_dir = self.cfg.state_dir
        key = (str(row), str(self.base_sha), str(REL.red_last(state_dir).get("sha") or ""), tuple(ids))
        cache = self.__dict__.setdefault("_hypo_sig_cache", {})
        if key not in cache:
            if len(cache) > 500:
                cache.clear()
            try:
                st = (REL.release_dir(state_dir) / REL.FAILURES_FILE).stat()
                stamp = (st.st_mtime_ns, st.st_size)
            except OSError:
                stamp = None
            held = self.__dict__.get("_hypo_book")
            if held is None or held[0] != stamp:
                held = self.__dict__["_hypo_book"] = (stamp, REL.failures(state_dir))
            book = held[1]

            def failure_of(test_id):
                try:
                    return REL.failure_of(state_dir, test_id, book)
                except Exception:       # noqa: BLE001  an aid
                    return ""
            cache[key] = [s for s, _g in HY.group_ids(ids, failure_of)]
        return list(cache[key])

    def _hypo_cooled_groups(self) -> set:
        """W-part 5: the failure signatures searched on this base less than ROW_COOLDOWN_S ago (the key is (base sha, signature))."""
        from tools import factory_hypo as HY
        prefix, now = str(self.base_sha) + "|", time.time()
        table = self.ls().get("hypo_seen") or {}
        return {k[len(prefix):] for k in table if k.startswith(prefix) and HY.cooled(table, str(self.base_sha), k[len(prefix):], now)}

    def _hypo_failure_of(self, test_id):
        """W-part 4: the failure text kept by the builds for one red test ('' when none)."""
        from tools import factory_release as REL
        try:
            return REL.failure_of(self.cfg.state_dir, test_id)
        except Exception:       # noqa: BLE001  an aid
            return ""

    def _hypo_post(self, row, packet, root, ids, found):
        """W-solver: what the loop thread does with a finished solve: the event (span 'solver'), the searched mark of the group, the
        evidence for the slicer when it ended not green; a contract result (green overlay as whole functions, engine 'solver') or
        None. Writes the loop state: loop thread only."""
        from tools import factory_hypo as HY, factory_solver as SV, factory_architect as A
        try:
            res, gids = found["result"], found.get("ids") or ids
            status = res.status if res.status in ("green", "cloud", "no_channel", "already_green", "stale") else "red"
            self.event("solver", backlog_id=row, status=status, steps=res.steps, calls=res.calls, tests=res.tests,
                       model=res.model or None, secs=round(float(found.get("secs") or 0), 1), why=res.why or None, group_ids=len(gids))
            if status == "stale" and self._solver_stale(row, gids, res):
                return None                 # booked as an outdated test: no evidence, no card
            if status in ("green", "red", "already_green"):     # no channel, a cloud failure or a STALE vote: no run, no penalty
                fresh = self.ls()
                HY.mark_searched(fresh.setdefault("hypo_seen", {}), str(self.base_sha), found.get("group") or ids[0], time.time())
                self.save_ls(fresh)
            if res.green:
                contract = SV.to_contract(row, gids, res, root, group=found.get("group"), rep=gids[0])
                faults = A.validate(contract, root, bid=row, known_ids=packet.get("known_ids"), engine="solver") if contract else ["not whole functions"]
                if not faults:
                    return dict(contract=contract, engine="solver", faults=[], repaired=[])
                res.last_fail = "the green change was refused as a card: " + "; ".join(str(x) for x in faults[:3])
            if status in ("red", "green", "stale") and res.evidence():
                text = "\nTRIED BEFORE YOU (a free model with read/grep/edit and the cloud test, all red):\n" + "\n".join(res.evidence())
                packet["evidence"] = str(packet.get("evidence") or "") + text
                keep = self.ls()        # the row goes back the usual way: the next packet of the slicer carries what was tried
                keep.setdefault("hypo_evidence", {})[row] = dict(base=str(self.base_sha), text=text[:3000])
                self.save_ls(keep)
        except Exception as exc:        # noqa: BLE001  an aid: the slicer goes on as before
            self.err("solver", exc)
        return None

    HYPO_SCAN_S = 5.0           # the candidates are looked through at most this often
    HYPO_RETRY_S = 600.0        # a row with nothing to search (no red id, cooled, no channel, cloud failure) is looked at again after this
    HYPO_STALE_S = 3600.0       # a solve older than this is dropped (its result ignored; 16 steps with a cloud run each)

    def _hypo_candidates(self, tasks, state, ls, now, tfirst=False) -> list:
        """W-feed2 2: the rows that may be searched now, ECHO (guard) -> rel-<sha> -> rel-base: rows of the to_slice book (the wait
        and the barred steps do not matter: the search needs neither) and rows of READY cards that no card runs; a red row only
        (the entry's guard or a rel- row); not a row that is under a search or a slicer already, not one that has nothing to search.
        (fac-55 review: the READY rows stay - a rel- row lives as a READY card only, and a waiting card does not run its row.)"""
        from tools import factory_hypo as HY
        running, ready, related = set(), set(), {}
        for tid, task in tasks.items():
            row = F.row_of(task.backlog_id or tid)
            related.setdefault(row, []).append(task)
            status = state["tasks"].get(tid, {}).get("status")
            if status in ("RUNNING", "REVIEW") or (status == "READY" and state["tasks"][tid].get("engine") == "solver"):
                running.add(row)
            elif status == "READY":
                ready.add(row)
        out, first = [], []
        for row in (set(ls.get("to_slice", {})) | ready) - running - set(self._hypers) - set(self._slicers):
            entry = ls.get("to_slice", {}).get(row, {})
            red = Loop._is_red_row(row, entry)
            if not red and not (tfirst and row in ls.get("to_slice", {}) and not str(row).startswith(("rel-", "fac-"))):
                continue            # test first (``tfirst``): a to_slice row of ECHO without a red test follows the red rows
            skipped = self._hypo_skip.get(row)
            if skipped and skipped[0] == str(self.base_sha) and now - skipped[1] < self.HYPO_RETRY_S:
                continue
            if entry.get("private") or entry.get("only_opus") or F.is_private_text(str(entry.get("text", ""))) \
                    or row in (ls.get("outdated_tests") or {}) \
                    or any(t.only_opus or not t.privacy_safe for t in related.get(row, [])):
                continue
            (out if red else first).append(row)
        red = sorted(out, key=lambda r: (HY.row_class(r), r))       # owner: ECHO before the old reds, with or without a red test
        return [r for r in red if not r.startswith("rel-")] + sorted(first) + [r for r in red if r.startswith("rel-")]

    def _solver_first(self, tasks, state, ls, now) -> set:
        """Red rows the solver has not tried on the current base (bench 25.11: 4 of 8 and 8 of 19 against 3.4 % of the cards): no card
        and no slicing call goes to them before it. Read anew at most once per HYPO_SCAN_S; [] without a free channel."""
        rows = self._solver_first_rows(tasks, state, ls, now)
        if rows:        # fac-53: an unsolved row does not hold its ready cards back while the cards of its rank or higher fill READY
            to_slice = ls.get("to_slice", {})
            rows = {r for r in rows if self._slice_exempt(r, to_slice.get(r))
                    or not self._cards_first(tasks, state, ls, now, rank=F.row_rank(r))}
        return rows

    def _solver_first_rows(self, tasks, state, ls, now) -> set:
        if self.cfg.self_repo or now - self.__dict__.get("_first_at", -1e9) < self.HYPO_SCAN_S:
            return self.__dict__.get("_first_rows", set())
        self._first_at = now
        try:
            base = str(self.base_sha)
            tried = {row for row, (sha, _at) in self._hypo_skip.items() if sha == base}
            self._first_rows = set(self._hypo_candidates(tasks, state, ls, now)) - tried if self._solver_channels() else set()
        except Exception as exc:        # noqa: BLE001  an aid: the cards go on as before
            self.err("solver first", exc)
            self._first_rows = set()
        return self._first_rows

    HYPO_REVIEW_HOLD_S = 900.0      # W-hypo3 3: the longest the search yields to a waiting review (a stuck card must not starve it)
    _review_since = None

    @staticmethod
    def _has_candidate(state, tid) -> bool:
        row = (state.get("tasks") or {}).get(tid) or {}
        return row.get("status") == "REVIEW" or (row.get("status") == "READY" and isinstance(row.get("candidate"), dict))

    def _hypo_review_gate(self, state) -> bool:
        """W-hypo3 3: True while the review of a candidate with green gates (REVIEW, or READY with its candidate kept) waits: the
        search starts nothing and the solvers wait a few seconds a step (``_review_hold``), so the review takes the minute before edits and search.
        Yields for at most HYPO_REVIEW_HOLD_S."""
        mono = time.monotonic()
        if not any(self._has_candidate(state, tid) for tid in (state.get("tasks") or {})):
            self._review_since = None
            return False
        if self._review_since is None:
            self._review_since = mono
        return mono - self._review_since < self.HYPO_REVIEW_HOLD_S

    def _review_hold(self) -> bool:
        since = self._review_since
        return since is not None and time.monotonic() - since < self.HYPO_REVIEW_HOLD_S

    HYPO_GATE_S = 2.0           # the review gate re-reads the state at most this often (bounds a stale _review_since)

    def _hypo_gate_tick(self) -> bool:
        """W-hypo3 fix1: the review gate on every feed tick (rate-limited), whatever the search limit or scan timer say."""
        mono = time.monotonic()
        if mono - self.__dict__.get("_hypo_gate_at", -1e9) >= self.HYPO_GATE_S:
            self._hypo_gate_at = mono
            self._hypo_gate_on = self._hypo_review_gate(self.load()[1])
        return bool(self.__dict__.get("_hypo_gate_on"))

    def _hypo_feed(self, now) -> None:
        """W-solver: the independent feeder of the solves (a tick of the loop thread): finished solves are applied, then rows with a
        red test id on the current base start theirs, as many at once as there are free channels (``_solver_limit``). A row under a
        solve neither starts with a card nor goes to the slicer. The threads only read and ask; every write of the state is here."""
        from tools import factory_hypo as HY
        if self.cfg.self_repo:
            return
        try:
            self._hypo_collect(now)
            if self._hypo_gate_tick():          # W-hypo3 fix1: the gate looks at the state, not at the scan moment (also while the limit is full)
                return
            limit = self._solver_limit()
            if len(self._hypers) >= limit or now - getattr(self, "_hypo_scan_at", -1e9) < self.HYPO_SCAN_S:
                return
            self._hypo_scan_at = now
            tasks, state = self.load()
            ls = self.ls()
            copies = None
            looked = 0
            for row in self._hypo_candidates(tasks, state, ls, now, tfirst=True):
                if len(self._hypers) >= limit or looked >= 40:
                    break
                entry = ls.get("to_slice", {}).get(row, {})
                if not self._slice_exempt(row, entry) and self._cards_first(tasks, state, ls, now, rank=F.row_rank(row)):
                    continue            # fac-53: the ready cards take the free models first; a row passed over is not counted in `looked`
                looked += 1
                if not Loop._is_red_row(row, entry):        # test first: no red test, the model writes it (after the rows with a red one)
                    if HY.cooled(ls.get("hypo_seen", {}), str(self.base_sha), "tfirst:" + row, time.time()) or not self._solver_channels():
                        self._hypo_skip[row] = (str(self.base_sha), now)
                        continue
                    if copies is None:
                        copies = copy.deepcopy((tasks, state, ls))
                    self._hypo_start_tfirst(row, copies)
                    continue
                try:
                    red = Loop._guard_red_ids(self, row, entry)
                except Exception as exc:        # noqa: BLE001  nothing known: the ids of the row's own books only
                    self.err("hypo guard ids", exc)
                    red = None
                kind, _ids = self._hypo_state(row, {"guard_red": red})
                if kind == "already_green":         # fac-55: checked before a solve starts (no thread, no model)
                    self._hypo_green(row, now)
                    continue
                if kind in ("off", "none", "cooled"):
                    self._hypo_skip[row] = (str(self.base_sha), now)
                    continue
                if copies is None:
                    copies = copy.deepcopy((tasks, state, ls))
                self._hypo_start(row, copies, HY)
        except Exception as exc:                # noqa: BLE001  an aid: the cards and the slicer go on as before
            self.err("hypo feed", exc)

    def _hypo_green(self, row, now) -> None:
        """fac-55: a row whose tests are not red in the last full build leaves the solver's queue for the base (HYPO_RETRY_S, then a
        free re-read); its event once per (row, base, last full build) - <id> told it 6 times a morning."""
        from tools import factory_release as REL
        base = str(self.base_sha)
        self._hypo_skip[row] = (base, now)
        key = (str(row), base, str(REL.red_last(self.cfg.state_dir).get("sha") or ""))
        told = self.__dict__.setdefault("_hypo_green_told", set())
        if key not in told:
            if len(told) > 500:
                told.clear()
            told.add(key)
            self.event("solver", backlog_id=row, status="already_green", steps=0, calls=0, tests=0, why="not red in the last full build")

    def _hypo_start(self, row, copies, HY) -> None:
        base, root = str(self.base_sha), self._snapshot(self.base_sha)
        tasks_c, state_c, ls_c = copies

        def work():
            packet = self._row_packet(row, "first", "", tasks=tasks_c, state=state_c, ls=ls_c, root=root, rung=0)
            kind, ids = self._hypo_state(row, packet)
            if kind != "search":
                return packet, ids, kind, None
            if not self._solver_channels():
                return packet, ids, "none", None
            return packet, ids, "search", self._solver_run(row, ids, packet, root)
        job = self._hypers[row] = Prefetch("solver", work, dict(row=row, base=base, root=root))
        job.thread.start()

    def _hypo_start_tfirst(self, row, copies) -> None:
        """Test first: the solve of a row WITHOUT a red test (the same feeder, the same Prefetch slot ``_hypers``)."""
        base, root = str(self.base_sha), self._snapshot(self.base_sha)
        tasks_c, state_c, ls_c = copies

        def work():
            packet = self._row_packet(row, "first", "", tasks=tasks_c, state=state_c, ls=ls_c, root=root, rung=0)
            return packet, [], "tfirst", self._solver_run_tfirst(row, packet, root)
        job = self._hypers[row] = Prefetch("solver", work, dict(row=row, base=base, root=root))
        job.thread.start()

    def _solver_run_tfirst(self, row, packet, root) -> dict:
        """Test first: ONE solve (a worker thread: reads and asks only) of a row with the text, the acceptance, the quotes and the hints."""
        from tools import factory_solver as SV, agent_factory_import as imp
        try:
            back = next((r for r in imp.parse_section4(self.cfg.backlog.read_text(encoding="utf-8-sig")) if r["backlog_id"] == row), {})
        except (ValueError, OSError):
            back = {}
        acceptance = F.redact(str(back.get("row") or "")) if not F.is_private_text(str(back.get("row") or "")) else ""
        suspects = self._solver_suspects(root, packet, [], "")
        t0 = time.monotonic()
        res = SV.solve_row(self._solver_ctx(root, packet), row, packet["title"], acceptance, suspects,
                           quotes="\n".join(str(q) for q in packet.get("quotes") or ()),
                           hints="\n".join(str(h) for h in packet.get("hints") or ()))
        if not getattr(res, "why", "") == "cancelled":
            SV.STATS.add(res)
            self._solver_save_trace(row, res, [res.test["id"]] if res.test else [])
        return dict(result=res, group="tfirst:" + row, ids=[], secs=time.monotonic() - t0)

    def _hypo_post_tfirst(self, row, packet, root, found):
        """Test first: what the loop thread does with a finished solve: the event, the cooldown mark, then the contract (a test task and
        a code task, or the test task alone when the fix is not green) or None. Loop thread only."""
        from tools import factory_hypo as HY, factory_solver as SV, factory_architect as A
        try:
            res = found["result"]
            status = res.status if res.status in ("green", "cloud", "no_channel", "already_green", "stale") else "red"
            self.event("solver", backlog_id=row, status=status, steps=res.steps, calls=res.calls, tests=res.tests, model=res.model or None,
                       secs=round(float(found.get("secs") or 0), 1), why=("test first: " + (res.why or "")) or None, group_ids=0,
                       tfirst=True, test=bool(res.test))
            if status in ("green", "red"):
                fresh = self.ls()
                HY.mark_searched(fresh.setdefault("hypo_seen", {}), str(self.base_sha), "tfirst:" + row, time.time())
                self.save_ls(fresh)
            contract = SV.to_contract_tfirst(row, res, root)
            if contract is None:
                return None
            faults = A.validate(contract, root, bid=row, known_ids=packet.get("known_ids"), engine="solver")
            if faults and contract.get("parts"):         # the fix is refused as a card: the red test alone still goes
                contract = SV.to_contract_tfirst(row, res, root, with_fix=False)
                faults = A.validate(contract, root, bid=row, known_ids=packet.get("known_ids"), engine="solver") if contract else ["no test"]
            if faults:
                self.err("solver tfirst", RuntimeError("; ".join(str(x) for x in faults[:3])))
                return None
            return dict(contract=contract, engine="solver", faults=[], repaired=[], test_only=bool(contract.get("test_only")),
                        guard=str(res.test["id"]))
        except Exception as exc:        # noqa: BLE001  an aid: the slicer goes on as before
            self.err("solver tfirst", exc)
        return None

    def _hypo_collect(self, now) -> None:
        """Apply the searches that have finished (loop thread). A green or a STALE of an older base is carried (_hypo_carry)."""
        for row, job in list(self._hypers.items()):
            if not job.done.is_set():
                age = time.monotonic() - job.t0
                silent = getattr(getattr(job, "thread", None), "heard", None) is None and age > self.SOLVE_SILENT_S
                if age > self.HYPO_STALE_S or silent:       # fac-55: a solve no model answered lets its row go now, not in an hour
                    del self._hypers[row]
                    if getattr(job, "cancel", None) is not None:
                        job.cancel.set()    # fac-choke: stopped, not abandoned: a dropped solve walking a pruned tree held the GIL (26.11)
                    self.__dict__.setdefault("_hypo_dropped", []).append(job)
                    self._hypo_skip[row] = (job.ctx["base"], now)
                    self.event("solver", backlog_id=row, status="stale", why=("no model answer in %d s" % self.SOLVE_SILENT_S) if silent
                               else "solve older than %d s dropped" % self.HYPO_STALE_S)
                continue
            del self._hypers[row]
            base = job.ctx["base"]
            try:
                if job.error is not None:
                    raise job.error
                packet, ids, kind, found = job.result
                root = job.ctx["root"]
                if base != str(self.base_sha):      # fac-55: a green or a STALE of an older base is carried, never dropped silently
                    if kind not in ("search", "tfirst") or not self._hypo_carry(row, base, root, found):
                        continue
                    root = str(self._snapshot(self.base_sha))
                if kind == "spare":
                    spare = self._hypo_take_spare(row, job.ctx["root"], packet)
                    result = dict(contract=spare, engine="solver", faults=[], repaired=[]) if spare is not None else None
                elif kind == "tfirst":
                    result = self._hypo_post_tfirst(row, packet, root, found)
                    if result is None:
                        self._hypo_skip[row] = (base, now)
                elif kind == "search":
                    result = self._hypo_post(row, packet, root, ids, found)
                    if result is None:
                        self._hypo_skip[row] = (base, now)      # red or no result: the row goes the usual way, evidence kept
                else:
                    result = None
                    if kind == "already_green":     # W-part 2: the row's tests are green in the last full build: nothing to search
                        self._hypo_green(row, now)
                    else:
                        self._hypo_skip[row] = (base, now)
                if result is not None:
                    self._hypo_adopt(row, packet, result)
            except Exception as exc:            # noqa: BLE001  one search never stops the loop
                self.err("hypo collect", exc)
                self._hypo_skip[row] = (base, now)

    def _hypo_carry(self, row, base, root, found) -> bool:
        """fac-55: a solve that ended on an older base (the base moves every 3-30 min, a solve takes 13-55) is carried, not dropped.
        A green overlay is put onto the current base file by file with the merge's own three_way_merge (old snapshot = the merge
        base, current snapshot = ours, the overlay = theirs); then it goes the usual way of a green (a card with ready code, the
        gates of the new base judge it). A STALE answer goes as it is. True = carried (event 'carried'); False = nothing to carry,
        or the overlay does not apply (event 'carried_conflict': the row goes the usual way). Loop thread only."""
        res = (found or {}).get("result")
        if res is None or not (res.green or res.status == "stale"):
            return False
        now_base = str(self.base_sha)

        def text_of(tree, path):
            p = Path(tree) / path
            return p.read_bytes().decode("utf-8-sig").replace("\r\n", "\n") if p.is_file() else ""
        if res.green and res.overlay:
            moved, bad = {}, []
            try:
                if not Path(root).is_dir():
                    raise FileNotFoundError("the tree of the solve's base is gone")
                new_root = self._snapshot(now_base)
                for path, text in sorted(res.overlay.items()):
                    merged, conflict = three_way_merge(text_of(root, path), text_of(new_root, path), str(text).replace("\r\n", "\n"), path)
                    if conflict:
                        bad.append(path)
                    moved[path] = merged
            except (OSError, ValueError, RuntimeError) as exc:
                bad = bad or ["%s: %s" % (type(exc).__name__, str(exc)[:120])]
            if bad:
                self.event("solver", backlog_id=row, status="carried_conflict", files=len(res.overlay),
                           why="solved on %s, does not apply onto %s: %s" % (base[:12], now_base[:12], ", ".join(bad[:5])))
                return False
            res.overlay = moved
        self.event("solver", backlog_id=row, status="carried", files=len(res.overlay or ()),
                   why="%s of %s carried onto %s" % ("green" if res.green else "STALE", base[:12], now_base[:12]))
        return True

    def _hypo_adopt(self, row, packet, result) -> int:
        """A green candidate becomes the row's code card by the same path as the slicer's contract (_apply_portion): the earlier
        cards of the row are superseded there. A row that has a card running now keeps the candidate as a spare instead."""
        from tools import factory_architect as A
        tasks, state = self.load()
        mine = {tid: t for tid, t in tasks.items() if F.row_of(t.backlog_id or tid) == row}
        contract, engine = result["contract"], result["engine"]
        if any(state["tasks"].get(tid, {}).get("status") in ("RUNNING", "REVIEW") for tid in mine):
            keep = self.ls()
            rec = (keep.get("hypo_spare") or {}).get(row)
            old = list(rec.get("contracts") or ()) if isinstance(rec, dict) and rec.get("base") == str(self.base_sha) else []
            keep.setdefault("hypo_spare", {})[row] = dict(base=str(self.base_sha), contracts=[contract] + old)
            self.save_ls(keep)
            return 0
        prior = sorted((t for t in mine.values() if t.kind == "code"),
                       key=lambda t: (int((re.search(r"_r(\d+)$", t.id) or [None, "0"])[1]), t.id))
        base_id = F.RESLICE_ID.sub("", prior[-1].id) if prior else "bl_" + re.sub(r"[^A-Za-z0-9_]", "_", row)
        top = max((int((re.search(r"_r(\d+)$", t.id) or [None, "0"])[1]) for t in mine.values()), default=0)
        gen = max(int(self.ls().get("reslices", {}).get(row, {}).get("n", 0)), top) + 1
        priority = int(str(packet["priority"]).removeprefix("P"))
        portion = dict(engine=engine, rung=0, tasks=A.to_tasks(contract, bid=row, base_id=base_id, gen=gen, priority=priority,
                                                                 title=packet["title"], author=A.author_model(engine)))
        entry_before = copy.deepcopy(self.ls().get("to_slice", {}).get(row)) if result.get("test_only") else None
        try:
            added = self._apply_portion(row, gen, portion, "first")
            if entry_before is not None and added and result.get("guard"):      # test first: the row stays in the book with the new test as its red id
                kept = self.ls()
                kept.setdefault("to_slice", {})[row] = dict(entry_before, guard=str(result["guard"]))
                self.save_ls(kept)
        except F.LockBusy:          # W-ask 4c: the state is locked: the green candidate is kept as a spare, not lost
            keep = self.ls()
            rec = (keep.get("hypo_spare") or {}).get(row)
            old = list(rec.get("contracts") or ()) if isinstance(rec, dict) and rec.get("base") == str(self.base_sha) else []
            keep.setdefault("hypo_spare", {})[row] = dict(base=str(self.base_sha), contracts=[contract] + old)
            self.save_ls(keep)
            return 0
        fresh = self.ls()
        fresh.setdefault("contracts_by_engine", {}).setdefault(engine, {"made": 0, "merged": 0})["made"] += 1
        self.save_ls(fresh)
        self.event("slice", backlog_id=row, engine=engine, status="fix", rung=0, ladder="", via="hypo_feed", added=added)
        return added

    def _guard_red_ids(self, row, entry):
        """W-guard 1: the red ids of the row's guard on the current base, from the newest sweep (its file keys): a list
        (first = the test the card runs; EMPTY = the guard is green on the base) or None when nothing is known (then the
        packet stays as it was).  The guard is the entry's own or the rel-<sha> regression's test."""
        from tools import factory_release as REL, factory_autofeed as AF
        name = str((entry or {}).get("guard") or "")
        if not name and str(row).startswith("rel-"):
            name = next((n for n, r in REL.regressions(self.cfg.state_dir).items() if r.get("row") == row), "")
        if not name:
            return None
        file = name.partition("::")[0].replace("\\", "/")
        try:
            latest = AF.latest_sweep(self._sweep_dir())
            sweep = AF.read_sweep(latest) if latest is not None else {}
            sweep_ids = AF.read_sweep_ids(latest) if latest is not None else {}
        except Exception as exc:                    # noqa: BLE001 - no sweep, no rule: the packet stays as it was
            self.err("guard red ids", exc)
            return None
        mine = {k: red for k, red in sweep.items() if str(k).partition("::")[0] == file}
        if not mine:
            return None
        reds = sorted(k for k, red in mine.items() if red is True)
        if not reds and not Loop._sweep_is_of_base(self):      # W-guard fix3: green is proven only by a sweep of the CURRENT base
            return None
        ids: list = []                              # W-guardid 2: the red ids of the guard file (its red_ids), else keys with '::'
        for k in reds:
            if "::" in k:
                found = [k]
            elif k in sweep_ids:
                found = sweep_ids[k]
            else:
                return None                         # a red file whose ids are unknown (an old sweep): _sweep_tick measures it again
            ids.extend(x for x in found if x not in ids)
        want = name.split("[", 1)[0]
        if "::" in name and not reds:
            return []
        if "::" in name and want in ids:
            return [want] + [k for k in ids if k != want and "::" in k]
        return [k for k in ids if "::" in k] or ([name] if "::" in name else (reds or []))

    def _sweep_is_of_base(self) -> bool:
        """W-guard fix3: the newest sweep file was measured on the current base: no sweep job runs now and the book's sweep
        record carries this base sha (unknown or different sha = not proven)."""
        if getattr(self, "_sw", None) is not None:
            return False
        sha = str((self.ls().get("sweep") or {}).get("sha") or "")
        return bool(sha) and sha == str(self.base_sha)

    def _row_packet(self, row, cause, evidence, *, tasks, state, ls, root, rung=0):
        from tools import factory_architect as A, factory_classes as CL, agent_factory_import as imp
        entry = ls.get("to_slice", {}).get(row, {})
        try:
            backlog = next((r for r in imp.parse_section4(self.cfg.backlog.read_text(encoding="utf-8-sig"))
                            if r["backlog_id"] == row), {})
        except (ValueError, OSError):
            backlog = {}
        previous = [t for t in tasks.values() if F.row_of(t.backlog_id or t.id) == row]
        title = str(entry.get("text") or backlog.get("text") or
                    next((t.goal or t.title for t in previous), row))
        def safe(value):
            text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
            return "" if F.is_private_text(text) else F.redact(text)
        quotes = [backlog.get("owner_cell", "")]
        try:
            from tools import backlog_register
            quotes.extend(backlog_register.owner_excerpts(row, k=3, chars=600))
        except ImportError:
            pass
        clues = [cause, evidence, entry.get("done", ""), entry.get("guard", "")]
        tried = (ls.get("hypo_evidence") or {}).get(row)        # W-feed2 2: what the hypotheses search tried on this base
        if isinstance(tried, dict) and tried.get("base") == str(self.base_sha):
            clues.append(tried.get("text", ""))
        files = list(entry.get("hints") or [])
        for task in previous:
            files.extend(task.touch_files)
            rec = state["tasks"].get(task.id, {})
            clues.extend([rec.get("reason", ""), task.contract or ""])
            clues.extend(rec.get("feedback", [])[-2:])
            diff = self.stage / "prev-diff" / (task.id + ".diff")
            if diff.is_file():
                clues.append(diff.read_text(encoding="utf-8", errors="replace"))
            if rec.get("base_red"):
                clues.append(rec["base_red"])
                clues.append(self._trace_clue(task.id, rec))
        guard_trace = self._guard_traces(state).get(row)
        clues.append(guard_trace or [])
        red_given = Loop._is_red_row(row, entry)
        if red_given:
            try:
                clues.extend(Loop._red_clues(self, row, entry, root))
            except Exception as exc:                # an addition to the packet: without it the packet is as before
                if hasattr(self, "err"):
                    self.err("row red evidence", exc)
        bisect_clue, bisect_key = "", ""
        if F.is_base_debt(row):
            # W-bisect 4: the proof of what broke the test (the commit after which it turned red and its diff): in the packet of every step
            try:
                from tools import factory_bisect as BIS
                found = BIS.clue(self.cfg.state_dir, BIS.row_tests(self.cfg.state_dir, row) or [str(entry.get("guard") or "")],
                                 trace=[(t[0], t[1]) for t in (guard_trace or [])], contracts=[t.contract or "" for t in previous])
                if found and (text := safe(found["text"])):
                    bisect_clue, bisect_key = text, found["key"]
            except Exception as exc:                # an addition to the packet: without it the packet is as before
                if hasattr(self, "err"):
                    self.err("row bisect clue", exc)
        row_trace = [t for t in (guard_trace or []) if not str(t[0]).startswith("tests/")]
        if red_given and row_trace and rung < 2:
            # W-free 4: the bodies of up to 4 functions of the trace nearest to the assert (rung >= 2 has the whole dossier)
            try:
                near, seen_fn = [], set()
                for rel, name, _line in reversed(row_trace):
                    if (rel, name) not in seen_fn:
                        seen_fn.add((rel, name))
                        near.append((rel, name, 0))
                if bodies := A.hint_sources(root, near[:40], places=4, cap=8000):
                    clues.append("CODE ALONG THE PATH OF THE RED TEST (the functions of its trace nearest to the assert):\n" + bodies)
            except Exception as exc:                # an addition to the packet: without it the packet is as before
                if hasattr(self, "err"):
                    self.err("row red path", exc)
        def keywords(system, user):
            status, _, answer, _ = self._light_ask(system + "\n" + user, attempt=1,
                section="loop-keywords", quotas=getattr(self, "_kw_quotas", {}), max_tokens=800, role="aux", thrifty=True)
            return answer if status == "ok" else ""
        words = A.keywords_en(title, keywords, cache=self.dir / "keywords")
        hints = [safe(x) for x in entry.get("hints", [])]
        try:
            from tools import repomap
            # the row's own words travel too: rank() expands their Russian stems through repomap.expand (glossary)
            ranked = repomap.rank(root, title + " " + " ".join(words)) if not F.is_private_text(title) else []
            hints.append(safe(repomap.hints(ranked)))
            files.extend(r[0] for r in ranked)
            if sources := A.hint_sources(root, ranked):     # the text of the 3 best places, verbatim (private pieces cut)
                hints.append(sources)
        except ImportError:
            pass
        dossier = {}
        if rung >= 2:
            try:
                if text := self._hard_dossier(previous, state, entry, root):
                    dossier["red_dossier"] = text
            except Exception as exc:               # an addition to the packet: without it the packet is as before
                self.err("row dossier", exc)
        if red_given:                               # W-guard 1: the card runs the guard's red test, the model does not choose it
            try:
                red_ids = Loop._guard_red_ids(self, row, entry)
            except Exception as exc:                # an addition to the packet: without it the packet is as before
                red_ids = None
                self.err("row guard ids", exc)
            if red_ids is not None:
                dossier["guard_red"] = red_ids
                if not red_ids:
                    dossier["guard_green"] = True
        return dict(bid=row, title=safe(title), priority=entry.get("priority") or backlog.get("priority") or 9,
                    **dossier, **({"red_given": True} if red_given else {}),
                    **({"guard_test": str(entry["guard"])} if entry.get("guard") else {}),
                    **({"bisect_clue": bisect_clue, "bisect_key": bisect_key} if bisect_clue else {}),
                    **({"trace_path": [[t[0], t[1]] for t in row_trace]} if red_given and row_trace else {}), quotes=[s for q in quotes if (s := safe(q))], hints=hints,
                    examples=[s for x in CL.contract_examples([f for f in files if isinstance(f, str)], k=2)
                              if (s := safe(x))], evidence="\n".join([s for x in clues if (s := safe(x))] + ([str(entry["rule"])] if entry.get("rule") else [])),
                    known_ids=list(ls.get("to_slice", {})) + list({t.backlog_id for t in tasks.values()}))

    def _blind_rows(self) -> set:
        """Baseline debt rows whose test file reads a top directory of the tree that is never published (echo_cloud.blind): it is
        red in the cloud whatever the product does. Once per base sha."""
        cached = self.__dict__.get("_blind")
        if cached and (cached[0] == self.base_sha or time.monotonic() - cached[2] < self.OD_EVERY_S):
            return cached[1]
        rows = set()
        try:
            from tools import echo_cloud as EC, factory_release as REL
            root = Path(self._snapshot(self.base_sha))
            rows = {"rel-base-%d" % rec["n"] for file, rec in REL.debt(self.cfg.state_dir).items()
                    if not rec.get("closed") and EC.blind(root, file)}
        except Exception as exc:        # noqa: BLE001  an aid: the rows stay as they were
            self.err("blind rows", exc)
        self._blind = (self.base_sha, rows, time.monotonic())
        return rows

    DONE_READ_S = 300.0

    def _done_rows(self) -> set:
        """Rows of the closures table whose own guard file (test_v_<ID>.py) is green in a sweep of the current base: nothing is left
        to slice for them, whatever old failed cards they have. Read at most once per DONE_READ_S."""
        now = time.monotonic()
        if now - self.__dict__.get("_done_at", -1e9) < self.DONE_READ_S:
            return self.__dict__.get("_done", set())
        self._done_at, done = now, set()
        try:
            from tools import factory_autofeed as AF
            latest = AF.latest_sweep(self._sweep_dir())
            files = {str(k).partition("::")[0] for k in (AF.read_sweep(latest) if latest is not None else {})}
            by_name = {f.rsplit("/", 1)[-1]: f for f in files}
            for bid in factory_closures.table_ids(self.cfg.backlog):
                file = by_name.get("test_v_%s.py" % re.sub(r"[^A-Za-z0-9]", "_", bid))
                if file and self._guard_red_ids(bid, {"guard": file}) == []:
                    done.add(bid)
        except Exception as exc:        # noqa: BLE001  an aid: the rows stay as they were
            self.err("done rows", exc)
        self._done = done
        return done

    def _box_rows(self) -> set:
        """W-box: rows with a ready contract in ``<state>/contracts/<row>.json``: the architect's answer given as a file. It takes the
        place of the model calls of the ladder only; validation, gates, cloud and reviews are those of every contract."""
        box = self.cfg.state_dir / "contracts"
        rows = {row for row, job in self._slicers.items() if job.ctx.get("boxed")}      # at work: its result must be collected
        return rows | ({p.stem for p in box.glob("*.json")} if box.is_dir() else set())

    def _proof_base_ok(self, sha) -> bool:
        """W-intake: the base of a cloud run's proof is the current base or one of its ancestors (git, no model)."""
        return bool(re.fullmatch(r"[0-9a-f]{7,40}", str(sha))) and bool(self.base_sha) and subprocess.run(
            ["git", "-C", str(self.cfg.repo), "merge-base", "--is-ancestor", str(sha), str(self.base_sha)],
            capture_output=True).returncode == 0

    def _proof_ledger(self) -> dict:
        """W-intake: {run_id: entry} of the cloud runs roots/cloudtry.py wrote (state_dir/proofs.jsonl, one JSON per line)."""
        out = {}
        try:
            lines = (self.cfg.state_dir / "proofs.jsonl").read_text(encoding="utf-8").splitlines()
        except OSError:
            return out
        for line in lines:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if isinstance(entry, dict) and isinstance(entry.get("run_id"), str):
                out[entry["run_id"]] = entry
        return out

    def _box_contract(self, row, root):
        """The valid contract of the box, or None; the file goes to used/ or (with its faults) to refused/: it is read once.
        W-intake: ready code without the proof of a green cloud run on an ancestor of the current base goes to rejected/ with the
        reason (A.proof_faults) for its author."""
        from tools import factory_architect as A
        path = self.cfg.state_dir / "contracts" / (row + ".json")
        try:
            contract = json.loads(path.read_text(encoding="utf-8"))
            faults = A.validate(contract, root, bid=row, engine=A.BOX_ENGINE, base_ok=self._proof_base_ok,
                                proofs=self._proof_ledger())
            if not faults and contract.get("decision") != "fix":
                faults = ["only a fix goes through the box"]
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as exc:
            contract, faults = None, ["unreadable: %s" % type(exc).__name__]
        proof = any(str(f).startswith("proof:") for f in faults)
        self._box_file(row, path, ("rejected" if proof else "refused") if faults else "used", faults)
        return None if faults else contract

    def _box_file(self, row, path, where, faults=()) -> None:
        """W-box: a contract file goes to <box>/<where>/ once; refused or rejected, its faults go beside it for its author."""
        from tools import factory_architect as A
        dest = self.cfg.state_dir / "contracts" / where
        dest.mkdir(parents=True, exist_ok=True)
        retry_fs(os.replace, path, dest / path.name)
        if faults:
            (dest / (path.name + ".faults.txt")).write_text("\n".join(map(str, faults)), encoding="utf-8")
            self.event("slice", backlog_id=row, status="box_refused", engine=A.BOX_ENGINE, reason=F.redact("; ".join(map(str, faults)))[:300])

    BOX_RETURN_WAIT_S = 1800.0      # fac-52: a returned row waits this long for its author's next contract before the ladder slices it

    def _box_returned(self, bid, res, ls, now) -> None:
        """fac-52: the station sent a card of the box back (not green on its base, contract rules, or it does not fit): the contract
        it came from (contracts/used/<row>.json with the very digest the card carries: an older or newer contract of the row stays
        where it is) goes to contracts/refused/ with the runner's reason, as a refused contract of the box does; the row waits
        BOX_RETURN_WAIT_S for the author's next contract (a contract in the box is sliced at once, whatever the wait)."""
        from tools import agent_factory_runner as R, factory_architect as A
        if R.READY_RETURNED not in (res.get("events") or ()) or not bid:
            return
        waits = ls.setdefault("slice_wait", {})
        waits[F.row_of(str(bid))] = max(waits.get(F.row_of(str(bid)), 0), now + self.BOX_RETURN_WAIT_S)
        for row in dict.fromkeys((str(bid), F.row_of(str(bid)))):
            path = self.cfg.state_dir / "contracts" / "used" / (row + ".json")
            if not path.is_file():
                continue
            try:
                if A.parts_digest(json.loads(path.read_text(encoding="utf-8"))) != str(res.get("ready_box") or ""):
                    return
                self._box_file(row, path, "refused", [str(res.get("ready_return") or res.get("reason_detail") or "returned")])
            except (OSError, ValueError) as exc:
                self.err("box return", exc)
            return

    def _slice(self, row, cause, rung, evidence, *, gen, tasks, state, ls, now):
        from tools import factory_architect as A
        job = self._slicers.get(row)
        if job is None:
            boxed = row in self._box_rows()
            if len(self._slicers) >= self._slice_parallel() and not boxed:
                return None
            my_rank = F.row_rank(row)       # W-prio2 1: "ahead of time" counts only the cards of the row's own rank or higher
            if not boxed and not self._slice_exempt(row, ls.get("to_slice", {}).get(row)) \
                    and self._cards_first(tasks, state, ls, now, rank=my_rank):
                return None             # fac-53: the cards of its rank or higher take the free models first; sliced once READY thins
            ahead = [t for t in self._startable(tasks, state, now)
                     if F.row_rank(F.row_of(tasks[t].backlog_id or t)) <= my_rank]
            memo = self.__dict__.get("_tick_memo")
            cap = memo["cap"] if memo is not None and "cap" in memo else self._slice_pool_cap()
            if memo is not None:
                memo["cap"] = cap
            if len(ahead) >= 2 * cap and not boxed:
                return None
            if self._arch_quotas is None:
                self._arch_quotas = copy.deepcopy(ls.get("architect_quotas") or {})
            root = self._snapshot(self.base_sha)
            asks = self._asks(root)
            barred = self._barred_engines(ls.get("row_hist", {}).get(row))
            if barred & set(asks):                     # W-hard 1: its contract gave two red fixes on this unchanged row
                left = {k: v for k, v in asks.items() if k not in barred}
                self.event("slice", backlog_id=row, status="barred", engine=",".join(sorted(barred & set(asks))),
                           rung=rung, ladder=",".join(left))
                if not left and not boxed:
                    raise SliceWait()
                asks = left
            base_debt = F.is_base_debt(row)
            if base_debt:                      # W-base0: the old debt is sliced by the free steps only, whatever waits in the queue
                left = {k: v for k, v in asks.items() if k in ("free", "free_main", "free_small")}
                if not left and not boxed:
                    self.event("slice", backlog_id=row, status="barred", engine="paid,agent", rung=rung, ladder="")
                    raise SliceWait()
                asks = left
            if ls.get("to_slice", {}).get(row, {}).get("only") == "free_small":     # W-lost 4: the small tier's ensemble only
                left = {k: v for k, v in asks.items() if k == "free_small"}
                if not left and not boxed:
                    self.event("slice", backlog_id=row, status="barred", engine="free,free_main,paid,agent", rung=rung, ladder="")
                    raise SliceWait()
                asks = left
            cached = dict(self._wait_record(ls, row).get("engines") or {})
            yields, probe = self._yield_pick(ls)       # W-a4: the steps ordered by the cohort's measured yield
            weak = A.weak_steps(tuple(asks), yields) if not probe and not boxed else set()
            if weak & set(asks):                       # W-yfloor: a step under a tenth of the best measured yield does not slice: the row waits, no fine
                left = {k: v for k, v in asks.items() if k not in weak}
                self.event("slice", backlog_id=row, status="weak", engine=",".join(sorted(weak & set(asks))),
                           rung=rung, ladder=",".join(left))
                if not left:
                    raise SliceWait()
                asks = left
            ctx = dict(root=root, gen=gen, rung=rung, cause=cause, ladder=",".join(asks), boxed=boxed)
            task_copy, state_copy, ls_copy = copy.deepcopy((tasks, state, ls))
            dry_now = self._edit_dry(state)       # W-dry 1: with the edit channels dry the contract asks for finished code
            def work():
                packet = self._row_packet(row, cause, evidence, tasks=task_copy, state=state_copy, ls=ls_copy, root=root,
                                         rung=rung)
                ready = self._box_contract(row, root) if boxed else None
                if ready is not None:
                    # fac-52: the stamp of the box on its cards (runner.ready_card): the digest of the file that goes back if it cannot merge
                    return packet, dict(contract=dict(ready, box=A.parts_digest(ready)), engine=A.BOX_ENGINE, faults=[], repaired=[])
                if dry_now:
                    packet["edit_dry"] = True
                if base_debt:
                    packet["base_debt"] = True
                if self.cfg.self_repo:      # the second instance: a new test imports only the modules the mirror publishes
                    packet["publishable"] = ", ".join(A.publishable_modules())
                extra = {"named_ok": True} if self.cfg.self_repo else {}      # 8.1: the factory's own files are the contract's subject
                A._samples_dir = self.cfg.state_dir        # W-rig 7: the black box of the rejected answers (<state>/slice_samples.json)
                if cached:      # W-pay 2: the steps that already answered this row (or refused it) on this version and sha
                    extra["skip"] = cached
                if yields:      # W-a4: the order of the steps by the cohort's measured yield
                    extra.update(yields=yields, probe=probe)
                if not packet.get("guard_green") and str(row).startswith("rel-") and not self.cfg.self_repo \
                        and self._packet_green_on_row(row, packet):
                    packet["guard_green"] = True    # W-part 2: no test of the row is red in the last full build (red_last): already_fixed
                if packet.get("guard_green"):       # W-guard 1: no red id on this base (the proof = a sweep of the current base, _guard_red_ids): no card
                    self.event("guard_green", backlog_id=row, reason="guard %s is green on base %s" % (
                        self.rs(str(packet.get("guard_test") or row), 120), str(self.base_sha)[:12]))
                    return packet, dict(contract=dict(decision="already_fixed", why="guard_green: the red test of the guard is green on the base"),
                                        engine="guard", faults=[], repaired=[])
                try:
                    result = self.architect_fn(packet, rung=rung, root=root, asks=asks, **extra)
                except A.Exhausted as exc:
                    try:
                        system, user = A.build_prompt(dict(packet, rung=rung))
                        exc.prompt_chars = len(system) + len(user)
                    except Exception:
                        pass
                    raise
                return packet, result
            ctx["small"] = asks.get("free_small")       # W-gslice 4: its ``vgs`` (the ensemble's stats) goes to the slice event
            job = self._slicers[row] = Prefetch("slice", work, ctx)
            self._slice_act = now
            job.thread.start()
            return None
        if not job.done.is_set():
            return None
        self._slice_act = now
        del self._slicers[row]
        fresh = self.ls()
        with self._ask_lock:
            fresh["architect_quotas"] = copy.deepcopy(self._arch_quotas)
        self.save_ls(fresh)
        engine, outcome, extra = "", "error", {}
        try:
            if job.error is not None:
                if isinstance(job.error, A.Exhausted):
                    engine = ",".join(str(f.get("engine", "")) for f in job.error.faults)
                    faults = [{"engine": str(f.get("engine", "")), "fault": F.redact(str(f.get("fault", "")))[:300]}
                              for f in job.error.faults]
                    extra["faults"] = faults
                    if getattr(job.error, "prompt_chars", None) is not None:
                        extra["prompt_chars"] = job.error.prompt_chars
                    if faults:
                        keep = self.ls()
                        log = [x for x in keep.get("slice_faults", []) if now - x[0] < 3600]
                        log += [[now, fault_class(f["fault"])] for f in faults]
                        keep["slice_faults"] = log
                        self.save_ls(keep)
                    keep = self.ls()
                    if job.error.answered:
                        (keep.get("slice_cache") or {}).pop(row, None)         # a counted void: the next generation asks anew
                    else:       # the row waits: what the steps answered (or refused) is kept for the repeat
                        self._wait_record(keep, row, create=True)["engines"].update(getattr(job.error, "cache", None) or {})
                    self.save_ls(keep)
                    outcome = "void" if job.error.answered else "unavailable"
                    if job.error.answered:
                        return {"engine": engine, "rung": job.ctx["rung"]}
                    raise SliceWait()
                raise job.error
            packet, result = job.result
            contract, engine = result["contract"], result["engine"]
            outcome = contract["decision"]
            if result.get("repaired"):
                extra["repaired"] = list(result["repaired"])      # W-free 1: what the machine mended in the contract
            portion = dict(engine=engine, rung=job.ctx["rung"])
            if outcome == "fix":
                prior = [t for t in tasks.values() if t.kind == "code" and F.row_of(t.backlog_id or t.id) == row]
                prior.sort(key=lambda t: (int((re.search(r"_r(\d+)$", t.id) or [None, "0"])[1]), t.id))
                base = F.RESLICE_ID.sub("", prior[-1].id) if prior else "bl_" + re.sub(r"[^A-Za-z0-9_]", "_", row)
                priority = packet["priority"]
                priority = int(str(priority).removeprefix("P"))
                portion["tasks"] = A.to_tasks(contract, bid=row, base_id=base, gen=job.ctx["gen"],
                                              priority=priority, title=packet["title"], author=A.author_model(engine))
            elif outcome == "split" and (self.ls().get("split") or {}).get(row):
                # W-supply 3: a row is split once; the second split answer is an ordinary hold with the reason
                portion["holds"] = [dict(backlog_id=row, question="split already made once: " + str(contract.get("why", ""))[:150],
                                         decision="hold")]
            elif outcome == "split":
                portion["priority"] = packet["priority"]
                portion["split"] = self._split_children(row, contract)
            elif outcome == "not_code":
                portion["not_code"] = [dict(backlog_id=row, reason=contract.get("why", ""))]
            else:
                if self._free_no_fix_unproven(row, engine, outcome, contract):
                    # W-lost 2: a free step's already_fixed / cannot_reproduce / duplicate_of closes nothing without a mechanical proof:
                    # the row stays in to_slice one rung higher, no quarantine budget is spent
                    portion["escalate"] = "%s of %s without a proof (guard / test green on the base)" % (outcome, engine)
                else:
                    portion["holds"] = [dict(backlog_id=row, question=contract.get("why", outcome), decision=str(outcome))]
            fresh = self.ls()
            (fresh.get("slice_cache") or {}).pop(row, None)
            made = fresh.setdefault("contracts_by_engine", {}).setdefault(engine, {"made": 0, "merged": 0})
            made["made"] += 1
            self._cohort_first(fresh, row, engine)
            vgs = getattr(job.ctx.get("small"), "vgs", None)
            if vgs and engine.endswith("free_small"):       # W-gslice 4: the ensemble's own counters of this engine
                for name in ("asked", "answered", "valid"):
                    made["vgs_" + name] = int(made.get("vgs_" + name) or 0) + int(vgs.get(name) or 0)
                made["vgs_votes_top"] = max(int(made.get("vgs_votes_top") or 0), int(vgs.get("votes_top") or 0))
            if packet.get("bisect_key"):        # W-bisect 4: this row's cards were cut WITH the proof (its segment): no re-cut for it
                fresh.setdefault("bisect_sliced", {})[row] = str(packet["bisect_key"])
            self.save_ls(fresh)
            return portion
        except SliceWait:
            raise
        except Exception as exc:
            self.err("slice", exc)
            raise SliceWait() from exc
        finally:
            vgs = getattr(job.ctx.get("small"), "vgs", None)
            if vgs and "free_small" in str(engine) + job.ctx.get("ladder", ""):
                extra["vgs"] = {k: vgs[k] for k in ("k", "asked", "answered", "valid", "unique", "votes_top", "retries_503", "rejected")
                                if k in vgs}
                extra["vgs"]["refused"] = {k[len("refused_"):]: int(v or 0) for k, v in vgs.items()      # W-prio3 2: by kind
                                           if k.startswith("refused_") and type(v) is int}
            self.event("slice", backlog_id=row, engine=engine, status=outcome, rung=job.ctx["rung"],
                       ladder=job.ctx.get("ladder", ""), **extra)

    def _yield_pick(self, ls):
        """W-a4: (the cohort yield of the steps, whether this row is a probe): one row in PROBE_EVERY with data is led by the
        step of the worst confirmed yield, the others by the best one."""
        from tools import factory_architect as A
        yields = A.engine_yield(ls.get("cohort") or {}, self.clock(), ls.get("contracts_by_engine"))
        if not yields:
            return yields, False
        self._yield_picks = getattr(self, "_yield_picks", 0) + 1
        return yields, self._yield_picks % A.PROBE_EVERY == 0

    def _cohort_first(self, ls, row, engine) -> None:
        """W-a4: the cohort of the rows: the engine of a row's FIRST contract and whether the row merged in the end (_after_merge).
        The oldest records beyond twice the window are dropped."""
        from tools import factory_architect as A
        cohort = ls.setdefault("cohort", {})
        if row in cohort or not engine:
            return
        cohort[row] = dict(engine=str(engine), at=self.clock(), merged=False)
        if len(cohort) > 2 * A.YIELD_WINDOW:
            for old in sorted(cohort, key=lambda k: float(cohort[k].get("at") or 0))[:len(cohort) - 2 * A.YIELD_WINDOW]:
                del cohort[old]

    NO_FIX_FREE = ("already_fixed", "cannot_reproduce")
    LOST_ESCALATIONS = 3

    def _free_no_fix_unproven(self, row, engine, kind, contract) -> bool:
        """W-lost 2: True when ``kind`` is a no-fix answer (already_fixed / cannot_reproduce / duplicate_of) of free / free_main /
        free_small only and the loop cannot prove it mechanically."""
        kind = str(kind)
        if not (kind in self.NO_FIX_FREE or kind.startswith("duplicate_of")):
            return False
        if not all(e in ("free", "free_main", "free_small") for e in str(engine).split("+")):
            return False                            # the agent / paid steps read the code themselves; guard_green is its own engine
        try:
            return not self._no_fix_evidence(row, contract)
        except Exception as exc:                    # noqa: BLE001 - no proof can be read: the row is not closed
            self.err("no-fix proof", exc)
            return True

    def _no_fix_evidence(self, row, contract) -> str:
        """The mechanical proof of a no-fix answer on the CURRENT base: the row's guard is green in the sweep of this base, or the
        test the answer names (file.py::name, an existing one) is green in that sweep (cloud). '' when there is none."""
        from tools import factory_autofeed as AF, factory_architect as A
        if not Loop._sweep_is_of_base(self):
            return ""
        entry = (self.ls().get("to_slice") or {}).get(row) or {}
        if self._guard_red_ids(row, entry) == []:
            return "guard"
        latest = AF.latest_sweep(self._sweep_dir())
        sweep = AF.read_sweep(latest) if latest is not None else {}
        text = " ".join(str(x) for x in (contract.get("proof"), contract.get("why")) if x)
        for file, symbol in A._PROOF_NAME.findall(text):
            file = file.replace("\\", "/")
            mine = [red for k, red in sweep.items() if str(k).partition("::")[0] == file]
            if mine and all(red is False for red in mine):
                return "%s::%s" % (file, symbol)
        return ""

    def _escalate_row(self, row, gen, portion) -> int:
        """W-lost 2: the row stays in to_slice; the next pass runs one rung higher (reslices.rung), `used` is not spent."""
        now = self.clock()
        ls = self.ls()
        old = ls.setdefault("reslices", {}).get(row, {})
        ls["reslices"][row] = {"n": max(gen, old.get("n", 0)), "used": old.get("used", 0), "stale": False, "at": now,
                               "version": F.slicer_version(), "rung": int(portion.get("rung") or 0) + 1,
                               "esc": True}                 # one rung higher: the next pass starts there, `stuck` adds nothing
        count =ls.setdefault("lost_escalated", {}).get(row) or {}
        count = {"ver": F.slicer_version(), "n": (count.get("n", 0) if count.get("ver") == F.slicer_version() else 0) + 1}
        ls["lost_escalated"][row] = count
        if count["n"] >= self.LOST_ESCALATIONS:         # the top of the ladder keeps saying it: the row waits, it is not closed
            ls.setdefault("slice_wait", {})[row] = now + self.LOST_AGAIN_S
        self.save_ls(ls)
        self.event("reslice", status="escalate", backlog_id=row, gen=gen, reason=str(portion.get("escalate"))[:200])
        return 0

    SPLIT_MAX = 3

    def _split_children(self, row, contract) -> list:
        """W-supply 3: the children of a decision split as queue rows <ID>.s1.. with their own text (defect, place, acceptance)."""
        out = []
        for n, child in enumerate((contract.get("children") or [])[:self.SPLIT_MAX], 1):
            place = " ".join(str(child.get(k)) for k in ("file", "symbol") if child.get(k))
            if not place:
                place = "сценарий: " + str(child.get("phrase") or child.get("scenario") or "")
            text = "%s (%s). Приёмка: %s" % (str(child.get("text", "")).strip(), place, str(child.get("acceptance", "")).strip())
            out.append({"id": "%s.s%d" % (row, n), "text": self._scrub(F.redact(text))[:1500],
                        "hints": [str(child["file"])] if child.get("file") else []})
        return out

    def _wait_record(self, ls, bid, create=False):
        """The row's wait record: the cached answers/refusals of the steps and the count of waits, valid for one slicer
        version and one base sha (any change of either starts a new record)."""
        version, sha = F.slicer_version(), self.base_sha
        rec = (ls.get("slice_cache") or {}).get(bid)
        if not isinstance(rec, dict) or rec.get("ver") != version or rec.get("sha") != sha:
            rec = {"ver": version, "sha": sha, "waits": 0, "engines": {}}
            if create:
                ls.setdefault("slice_cache", {})[bid] = rec
        return rec

    def _slice_pool_cap(self):
        if _cloud_up(self.cloud_fn):
            return max(1, getattr(factory_cloud_gate, "MAX_LIVE", 30))
        cap = max(1, int((self.free_ram_fn() - LIGHT_FLOOR) / max(1, self._estimate())))
        if Path(self.cfg.channels).is_file():
            cap = min(cap, max(1, self._headroom(None, self.load()[1])))
        return cap

    def _reenter_rows(self, bids):
        version = F.slicer_version()
        def reopen(st):
            for tid, row in st["tasks"].items():
                if F.row_of(row.get("backlog_id") or tid) in bids and row.get("reason") == "quarantine":
                    row["reason"] = "reenter"
                    st.setdefault("strikes", {}).pop(F._strike_key(row, tid), None)
            for bid in bids:
                st.setdefault("strikes", {}).pop("bl:" + bid, None)
        self._tx(reopen)

    SLIM_FEEDBACK, SLIM_CHARS = 2, 800

    def _slim_state(self) -> int:
        """Rows nobody runs again (superseded, DONE) keep what the slicer reads of them (the last SLIM_FEEDBACK remarks, cut); their
        red traces and the rest go to state_archive.jsonl. Every claim and snapshot parses the whole file under one lock (25.11: 3.9 MB,
        2.5 of it of such rows, 'state_locked' waits of 10 s with 20 workers)."""
        out = []

        def slim(state):
            for tid, row in state["tasks"].items():
                if not (row["status"] == "DONE" or (row["status"] == "FAILED" and str(row.get("reason") or "").startswith("superseded"))):
                    continue
                items = row.get("feedback") or []
                short = [dict(x, text=str(x.get("text") or "")[:self.SLIM_CHARS]) if isinstance(x, dict) else str(x)[:self.SLIM_CHARS]
                         for x in items[-self.SLIM_FEEDBACK:]]
                if "base_red" not in row and short == items:
                    continue
                out.append(dict(id=tid, base_red=row.pop("base_red", None), feedback=items))
                if items:
                    row["feedback"] = short
            if out:             # on disk before the state drops them
                with (self.cfg.state_dir / "state_archive.jsonl").open("a", encoding="utf-8") as f:
                    f.writelines(json.dumps(x, ensure_ascii=False) + chr(10) for x in out)
        self._tx(slim)
        return len(out)

    def _reenter_on_new_slicer(self) -> int:
        tasks, state = self.load()
        version, now, ls = F.slicer_version(), self.clock(), self.ls()
        bids = {F.row_of(row.get("backlog_id") or tid) for tid, row in state["tasks"].items()
                if row["status"] == "FAILED" and row.get("reason") == "quarantine" and row.get("q_ver") != version}
        bids |= {bid for bid, rec in ls.get("quarantine", {}).items() if rec.get("version") != version}
        bids = {bid for bid in bids if not self._hard_held(ls, bid)}      # W-hard 1: only a new CONTRACT_REV opens these
        if not bids:
            return 0
        self._reenter_rows(bids)
        tasks, state = self.load()
        owned = {F.row_of(r.get("backlog_id") or t) for t, r in state["tasks"].items()
                 if r["status"] in ("READY", "BLOCKED", "FAILED", "RUNNING", "REVIEW") and not F.is_terminal(r.get("reason"))}
        for bid in bids:
            ls.get("quarantine", {}).pop(bid, None)
            # A row record can exist without any task: only such a row goes back to the queue.
            # A row with a re-entered task is stuck, and the slicer takes it from there.
            if bid not in owned:
                ls.setdefault("to_slice", {}).setdefault(bid, {"at": now, "hints": [], "guard": ""})
        ls["reentry"] = {"version": version, "at": now, "rows": sorted(bids)}
        self.save_ls(ls)
        return len(bids)

    @staticmethod
    def _code_sha() -> str:
        """The SHA of the factory's own code (HEAD of the repository that holds this file); '' when it cannot be read."""
        try:
            return code_sha(Path(__file__).resolve().parent.parent)
        except Exception:  # noqa: BLE001 - no SHA, no return: a tree without git never loops on it
            return ""

    def _rel_entry_back(self, ls, bid):
        """The to_slice entry of a rel-... row as it was (text, guard, priority): the kept one, else rebuilt from the build's own
        books (the baseline debt for rel-base-<n>, the regressions for rel-<sha>-<n>); None when neither knows the row."""
        from tools import factory_release as REL
        kept = (ls.get("rel_entry") or {}).get(bid)
        if isinstance(kept, dict) and kept.get("guard"):
            return {"at": self.clock(), "hints": [], **kept}
        found = REL.DEBT_ROW.match(bid)
        if found:
            for file, rec in REL.debt(self.cfg.state_dir).items():
                if rec.get("n") == int(found.group(1)) and rec.get("tests"):
                    names = [str(t).split("::", 1)[-1] for t in rec["tests"][:5]]
                    sha = str((ls.get("release") or {}).get("sha") or "")[:8]
                    return {"at": self.clock(), "hints": [], "priority": 2, "guard": str(rec["tests"][0]),
                            "text": "тест %s красный на базе %s: %s" % (file, sha, ", ".join(names))}
            return None
        for name, rec in REL.regressions(self.cfg.state_dir).items():
            if rec.get("row") == bid:
                return {"at": self.clock(), "hints": [], "priority": 0, "guard": name,
                        "text": "после слияний упал тест %s" % name}
        return None

    def _lift_rel_decisions(self) -> int:
        """W-redrow 3: a no-fix answer (not_code / cannot_reproduce / already_fixed / duplicate_of) written for a rel-... row (its test
        is red) by a step other than the agent is taken off ONCE at the start of a new slicer version: the row goes back to
        to_slice with its own text, guard and priority.  Places: the not_code book, holds (+ hold_ver / hold_hash / hold_arch) and
        the architect's decision record.  A row the agent decided stays."""
        version = F.slicer_version()
        ls = self.ls()
        if (ls.get("redrow_lift") or {}).get("version") == version:
            return 0
        book, holds, arch = ls.setdefault("not_code", {}), ls.setdefault("holds", {}), ls.get("arch_decision") or {}
        lifted = []
        for bid in sorted({b for b in list(book) + list(holds) + list(arch) if str(b).startswith("rel-")}):
            rec = arch.get(bid) if isinstance(arch.get(bid), dict) else {}
            nc = book.get(bid) if isinstance(book.get(bid), dict) else None
            kind = "not_code" if bid in book else str(rec.get("decision") or "")
            engine = str((nc or {}).get("engine") or rec.get("engine") or "")
            if bid in holds and bid not in book and not rec and bid not in (ls.get("hold_arch") or {}):
                continue                                    # a hold of unknown origin: not the architect's no-fix answer
            if kind == "hold" or engine == "agent":
                continue
            if kind and kind not in ("not_code", "cannot_reproduce", "already_fixed") and not kind.startswith("duplicate"):
                continue
            entry = self._rel_entry_back(ls, bid)
            if entry is None:
                continue
            book.pop(bid, None)
            for key in ("holds", "hold_ver", "hold_hash", "hold_arch", "arch_decision", "slice_wait", "reslices"):
                (ls.get(key) or {}).pop(bid, None)
            ls.setdefault("to_slice", {}).setdefault(bid, entry)
            lifted.append(bid)
        ls["redrow_lift"] = {"version": version, "at": self.clock(), "rows": lifted[:200]}
        self.save_ls(ls)
        if lifted:
            self.event("loop", action="RECOVER", status="ok", reason="rel_decisions_lifted", count=len(lifted), rows=lifted[:20])
        return len(lifted)

    def _return_worker_exceptions(self) -> int:
        """W-name 3: cards BLOCKED / FAILED by a ``worker_exception`` (a fault of the factory's code, not of the card) go
        back to READY when the loop starts on a code SHA it has not seen: no strike, the reslice budget untouched
        (``unblock`` resets the strikes of the row and attempts only). Once per SHA (loop_state ``wx_returned``)."""
        sha = self._code_sha()
        ls = self.ls()
        if not sha or ls.get("wx_returned", {}).get("sha") == sha:
            return 0
        def lift(st):
            ids = []
            for tid, row in st["tasks"].items():
                text = " ".join(str(row.get(k) or "") for k in ("blocked_reason", "reason"))
                if row.get("status") in ("BLOCKED", "FAILED") and "worker_exception" in text and not F.is_terminal(row.get("reason")):
                    F.unblock(st, tid, None)
                    ids.append(tid)
            return ids
        ids = self._tx(lift)
        ls = self.ls()
        ls["wx_returned"] = {"sha": sha, "at": self.clock(), "tasks": sorted(ids)[:50]}
        self.save_ls(ls)
        if ids:
            self.event("loop", action="RECOVER", status="ok", reason="worker_exception_returned", count=len(ids), sha=sha[:12])
        return len(ids)

    # ---- W-hard 1: the history of a row does not depend on the slicer version ---------------------------------------
    def _base_tree(self) -> dict:
        """<id>: {path: blob id} of the whole base tree, ONE git call per base sha (was one rev-parse per file of every queued
        row: 166 calls, 25 of 33 s of the reslice tick on the live state 26.11). {} when git cannot read it."""
        sha = str(getattr(self, "base_sha", "") or "") or "HEAD"
        cached = self.__dict__.get("_tree_cache")
        if cached is not None and cached[0] == sha:
            return cached[1]
        tree = {}
        try:
            out = subprocess.run(["git", "-C", str(self.cfg.repo), "ls-tree", "-r", "-z", "--full-tree", sha],
                                 capture_output=True, timeout=30)
            if out.returncode == 0:
                for entry in out.stdout.split(b"\0"):
                    meta, _, path = entry.partition(b"\t")
                    parts = meta.split()
                    if path and len(parts) == 3:
                        tree[path.decode("utf-8", "surrogateescape")] = parts[2].decode("ascii")
        except (OSError, subprocess.SubprocessError):
            pass
        self._tree_cache = (sha, tree)
        self.__dict__.setdefault("_blob_cache", {}).clear()
        return tree

    def _row_blob(self, rel) -> str:
        """The id of a file's content in the base (git), or of the file in the checkout; '' when it is not there."""
        tree = self._base_tree()
        cache = self.__dict__.setdefault("_blob_cache", {})
        rel = str(rel).replace("\\", "/")
        if rel not in cache:
            value = tree.get(rel, "")
            if not value:
                try:
                    value = hashlib.sha1((Path(self.cfg.repo) / rel).read_bytes()).hexdigest()
                except OSError:
                    value = ""
            cache[rel] = value
        return cache[rel]

    def _hist_sync(self, ls, bid, tasks, state, texts=None, by_row=None) -> dict:
        """ls['row_hist'][bid]: failed_gens (generations that reached a red fix), red (red fixes by the engine whose
        contract made them), blobs/text (what the bars were earned on). Idempotent; a changed row text or a changed
        file of the row clears the bars, never the count of generations."""
        hist = ls.setdefault("row_hist", {}).setdefault(bid, {"failed_gens": 0, "red": {}, "seen": [], "free_first": False})
        try:
            text = (texts if texts is not None else self._row_hashes("text")).get(bid, "")
        except Exception:                      # an unreadable backlog is no change
            text = hist.get("text", "")
        blobs = hist.setdefault("blobs", {})
        changed = hist.get("text", text) != text or any(self._row_blob(f) != b for f, b in blobs.items())
        if changed:
            hist["red"] = {}
        hist["text"] = text
        mine = by_row.get(bid, []) if by_row is not None else [
            (tid, t) for tid, t in tasks.items() if F.row_of(t.backlog_id or tid) == bid]
        for _, task in mine:
            for rel in task.touch_files:
                if rel not in blobs or changed:
                    blobs[rel] = self._row_blob(rel)
        for rel in list(blobs):
            if changed:
                blobs[rel] = self._row_blob(rel)
        gens: dict = {}
        for tid, _ in mine:
            rec = state["tasks"].get(tid, {})
            if rec.get("status") == "FAILED" and rec.get("reason") == "reslice" and tid not in hist.setdefault("seen", []):
                hist["seen"].append(tid)
                m = re.search(r"_r(\d+)$", tid)
                gens.setdefault(m.group(1) if m else "0", []).append(str(rec.get("engine") or ""))
        for engines in gens.values():
            hist["failed_gens"] += 1
            engine = next((e for e in engines if e), "")
            if engine:
                hist["red"][engine] = hist["red"].get(engine, 0) + F.RESLICE_AFTER
        hist["seen"] = hist.get("seen", [])[-200:]
        return hist

    @staticmethod
    def _barred_engines(hist) -> set:
        return {e for e, n in (hist or {}).get("red", {}).items() if n >= RED_EDITS_BAR}

    @staticmethod
    def _hard_held(ls, bid) -> bool:
        return ls.get("quarantine", {}).get(bid, {}).get("kind") == "failed_gens"

    def _hard_reopen(self, ls, now) -> set:
        """A failed_gens quarantine opens only by a new CONTRACT_REV, and not more than once a day."""
        from tools import factory_architect as A
        out = set()
        for bid, rec in list(ls.get("quarantine", {}).items()):
            if rec.get("kind") == "failed_gens" and rec.get("rev") != str(A.CONTRACT_REV) \
                    and now - float(rec.get("at", 0)) >= HARD_REOPEN_S:
                ls["quarantine"].pop(bid)
                ls.setdefault("row_hist", {}).setdefault(bid, {})["failed_gens"] = HARD_FAILED_GENS - 1
                out.add(bid)
        return out

    def _quarantine_rows(self, tasks, state, ls, now):
        version, ladder = F.slicer_version(), self._ladder_sig()
        from tools import factory_architect as A
        reopened_hard = self._hard_reopen(ls, now)
        if reopened_hard:
            self._reenter_rows(reopened_hard)
            for bid in reopened_hard:
                ls.get("reslices", {}).get(bid, {})["used"] = 0
                ls.setdefault("to_slice", {}).setdefault(bid, {"at": now, "hints": [], "guard": ""})
            self.save_ls(ls)
            tasks, state = self.load()
        reopened = {bid for bid, rec in ls.get("quarantine", {}).items()
                    if rec.get("kind") != "failed_gens" and
                    (rec.get("ladder", "") != ladder or now - float(rec.get("at", 0)) >= QUARANTINE_TTL_S)}
        if reopened:
            self._reenter_rows(reopened)
            for bid in reopened:
                ls["quarantine"].pop(bid, None)
                ls.get("reslices", {}).get(bid, {})["used"] = 0
                ls.setdefault("to_slice", {}).setdefault(bid, {"at": now, "hints": [], "guard": ""})
            self.save_ls(ls)
            tasks, state = self.load()
        candidates = set(F.stuck_rows(state, tasks)) | set(ls.get("to_slice", {}))
        synced = False
        try:                                       # read once for all rows: 200 queued rows must not parse the backlog 200 times
            texts = self._row_hashes("text")
        except Exception:
            texts = None
        by_row = {}
        for tid, t in tasks.items():
            by_row.setdefault(F.row_of(t.backlog_id or tid), []).append((tid, t))
        for bid in sorted(candidates - set(ls.get("quarantine", {}))):
            try:
                self._hist_sync(ls, bid, tasks, state, texts=texts, by_row=by_row)
                synced = True
            except Exception as exc:               # the history is an aid: it never stops the pass
                self.err("row history", exc)
        if synced:
            self.save_ls(ls)
        for bid in sorted(candidates - set(ls.get("quarantine", {}))):
            rec = ls.get("reslices", {}).get(bid, {})
            hard = ls.get("row_hist", {}).get(bid, {}).get("failed_gens", 0) >= HARD_FAILED_GENS
            if not hard and (rec.get("version") != version or rec.get("used", 0) < F.MAX_RESLICES):
                continue
            # A stale return gets its free retry even when the charged budget is spent.
            stuck = F.stuck_rows(state, tasks).get(bid, [])
            if stuck and not rec.get("stale") and all(state["tasks"][t].get("reason") == "reslice:stale" for t in stuck):
                continue
            if ls.get("slice_wait", {}).get(bid, 0) > now:
                continue
            with self.txn() as (fresh, st):
                for tid, task in fresh.items():
                    row = st["tasks"][tid]
                    if F.row_of(task.backlog_id or tid) == bid and row["status"] in ("READY", "BLOCKED", "FAILED") and not F.is_terminal(row.get("reason")):
                        row.update(status="FAILED", reason="quarantine", q_ver=version)
            ls.setdefault("quarantine", {})[bid] = {"version": version, "ladder": ladder, "at": now, "why": "reslice budget exhausted"}
            if hard:
                ls["quarantine"][bid].update(kind="failed_gens", rev=str(A.CONTRACT_REV),
                                             why="%d generations reached a red fix" % ls["row_hist"][bid]["failed_gens"])
            ls.get("to_slice", {}).pop(bid, None)
            ls.get("slice_wait", {}).pop(bid, None)
            self.save_ls(ls)
            self.event("reslice", status="quarantine", backlog_id=bid, reason="reslice budget exhausted")

    def _expire_slicer_decisions(self, ls):
        version, now = F.slicer_version(), self.clock()
        arch = ls.setdefault("hold_arch", {})
        for bid in list(arch):                     # the architect's duplicate/cannot_reproduce/already_fixed hold
            if bid not in ls["holds"]:
                arch.pop(bid, None)
            elif float(arch[bid] or 0) <= now:     # its term is over: the hold goes, the row is looked at again
                arch.pop(bid, None)
                ls["holds"].pop(bid, None)
                ls.get("hold_ver", {}).pop(bid, None)
                ls.get("hold_hash", {}).pop(bid, None)
        for bid in list(ls["holds"]):
            why = str(ls["holds"][bid]).lower()
            if any(rule in why for rule in ("only_opus", "private", "приватн")) or bid in arch:
                continue
            if ls.get("hold_ver", {}).get(bid, version) != version:
                ls["holds"].pop(bid, None)
                ls.get("hold_ver", {}).pop(bid, None)
                ls.get("hold_hash", {}).pop(bid, None)
        for bid, rec in list(ls.get("not_code", {}).items()):
            if rec.get("slicer") != version and rec.get("engine") not in self.ARCH_ENGINES:
                ls["not_code"].pop(bid, None)
        for bid in list(ls.get("arch_decision") or {}):        # the answer lives as long as the hold / not_code record it explains
            if bid not in ls["holds"] and bid not in (ls.get("not_code") or {}):
                ls["arch_decision"].pop(bid, None)
        for bid in list(ls.get("split") or {}):                # a split parent closed in the backlog leaves reconcile.json
            if bid in (ls.get("closed") or {}):
                ls["split"].pop(bid, None)

    def _resliceable(self, tasks, state, ls, now) -> dict:
        stuck = F.stuck_rows(state, tasks)
        out = {}
        by_row, running = {}, set()             # one pass over the plan, not one per row (200 queued rows must not slow the step)
        for tid, t in tasks.items():
            row_id = F.row_of(t.backlog_id or tid)
            by_row.setdefault(row_id, []).append(t)
            if state["tasks"][tid]["status"] in ("RUNNING", "REVIEW"):
                running.add(row_id)
        dry_rows = {F.row_of(tasks[t].backlog_id or t) for t in self._dry_blocked(tasks, state)}   # W-dry 1: code, not a channel
        boxed, done = self._box_rows(), self._done_rows()
        blind = self._blind_rows() - boxed
        for bid in sorted(set(stuck) | set(ls.get("to_slice", {})) | dry_rows | boxed):
            related = by_row.get(bid, [])
            if any(t.only_opus or not t.privacy_safe or F.is_private_text(t.title + " " + (t.goal or "")) for t in related):
                continue
            entry = ls.get("to_slice", {}).get(bid, {})
            if entry.get("private") or entry.get("only_opus") or F.is_private_text(str(entry.get("text", ""))):
                continue
            if bid in blind:
                continue                # its tests read what the cloud does not get: red there is no defect, no gate could turn it green
            if bid in boxed:            # W-box: a ready contract: no wait, no quarantine, no budget; a card of the row at work is finished first
                if bid not in running:
                    out[bid] = "first"
                continue
            if bid in done:
                continue                # closed, and its own guard is green: old failed cards are no reason to slice it
            if bid in (ls.get("outdated_tests") or {}):
                continue                # W-prio 3: the test names what the product no longer has: no cards, no slicing
            if bid in ls.get("quarantine", {}) or ls.get("slice_wait", {}).get(bid, 0) > now:
                continue
            if bid in running or bid in self._hypers or bid in self._solver_first(tasks, state, ls, now):  # the solver goes first: no slicing call is spent before it
                continue
            if bid in dry_rows and bid not in stuck and bid not in ls.get("to_slice", {}):
                # W-dry 1: the row of a READY card without code goes to the slicer for the code: no penalty, no spent
                # reslice (cause "dry"); asked once per base sha (a card that comes back without code waits for the next)
                if bid in self._slicers or ls.get("dry_tried", {}).get(bid) != self.base_sha:
                    out[bid] = "dry"
                continue
            rec = ls.get("reslices", {}).get(bid, {})
            if rec.get("version") != F.slicer_version():
                cause = "first"
            elif (stuck.get(bid) and not rec.get("stale") and all(
                    state["tasks"][t].get("reason") == "reslice:stale" for t in stuck[bid])):
                cause = "stale"
            else:
                cause = "stuck"
            if cause == "stuck" and rec.get("used", 0) >= F.MAX_RESLICES:
                continue
            out[bid] = cause
        return out

    def _slice_record(self, ls, row, gen, cause, now, void=False):
        old = ls.setdefault("reslices", {}).get(row, {})
        used = 0 if cause == "first" else old.get("used", 0) + (cause == "stuck" or void)
        if cause == "first" and not void and ls.get("row_hist", {}).get(row, {}).get("failed_gens"):
            used = max(0, F.MAX_RESLICES - 1)      # W-hard 1: a new version gives a row with a red history one generation
        ls["reslices"][row] = {"n": max(gen, old.get("n", 0)), "used": used,
            "stale": cause == "stale", "at": now, "version": F.slicer_version()}

    def _apply_portion(self, row, gen, portion, cause) -> int:
        if portion.get("escalate"):
            return self._escalate_row(row, gen, portion)
        now = self.clock()
        items = list(portion.get("tasks") or [])
        ids = {t["id"] for t in items}
        why = "empty portion"
        # a decision counts only if it names the row (or a part of it): a hold/not_code record under a foreign id would
        # supersede the row's tasks below and leave the row with no task and no decision (the lost row)
        decided = any(F.row_of(str(x.get("backlog_id", row))) == row
                      for x in list(portion.get("holds") or []) + list(portion.get("not_code") or []))
        decided = decided or bool(portion.get("split"))
        valid = bool(items or decided)
        added = []
        if valid:
            self._tx(lambda st: st.setdefault("strikes", {}).pop("bl:" + row, None))
            try:
                added = F.append_tasks(self.plan_path, items)
                tasks, state = self.load()
                valid = ids <= set(tasks)
                if not valid:
                    why = "portion tasks were skipped"
            except F.LockBusy:      # W-ask 4c: a busy lock is not an invalid portion: the caller keeps it for the next step
                raise
            except F.InvalidPlan as exc:
                valid, why = False, str(exc)
        ls = self.ls()
        if not valid:
            self._slice_record(ls, row, ls.get("reslices", {}).get(row, {}).get("n", 0), cause, now, void=True)
            if "rung" in portion:
                ls["reslices"][row]["rung"] = portion["rung"]
                if ls["reslices"][row]["used"] >= F.MAX_RESLICES:
                    ls.setdefault("quarantine", {})[row] = dict(version=F.slicer_version(), ladder=self._ladder_sig(),
                                                                at=now, why="reslice budget exhausted")
            self.save_ls(ls)
            self.event("reslice", status="void", backlog_id=row, cause=cause, reason=why)
            return 0
        with self.txn() as (tasks, state):
            for tid, task in tasks.items():
                rec = state["tasks"][tid]
                if tid in ids and portion.get("engine"):
                    rec["engine"] = portion["engine"]
                if F.row_of(task.backlog_id or tid) == row and tid not in ids and rec["status"] in ("READY", "BLOCKED", "FAILED"):
                    rec.update(status="FAILED", reason="superseded:reslice%d" % gen)
        self._slice_record(ls, row, gen, cause, now)
        if "rung" in portion:
            ls["reslices"][row]["rung"] = portion["rung"]
        if row.startswith("rel-") and (portion.get("holds") or portion.get("not_code")) and not items:
            kept = ls.get("to_slice", {}).get(row)       # W-redrow 3: what the row was, so a lift can give it back as it was
            if isinstance(kept, dict):
                ls.setdefault("rel_entry", {})[row] = {k: kept[k] for k in ("text", "guard", "priority", "hints", "at") if k in kept}
        for key in ("to_slice", "slice_wait", "parents", "slice_cache"):
            ls.get(key, {}).pop(row, None)
        if portion.get("split"):                   # W-supply 3: the parent is in the state split, the children are rows of the queue
            children = portion["split"][:self.SPLIT_MAX]
            ls.setdefault("split", {})[row] = {"children": [c["id"] for c in children], "at": now, "slicer": F.slicer_version(),
                                               "engine": str(portion.get("engine") or "")}
            for c in children:
                entry = {"at": now, "hints": list(c.get("hints") or []), "guard": "", "text": c["text"]}
                if portion.get("priority") is not None:
                    entry["priority"] = portion["priority"]
                ls.setdefault("to_slice", {})[c["id"]] = entry
                ls.get("reslices", {}).pop(c["id"], None)
        for hold in portion.get("holds") or []:
            bid = hold.get("backlog_id", row)
            ls["holds"][bid] = self._scrub(str(hold.get("question", "")))
            ls.setdefault("hold_ver", {})[bid] = F.slicer_version()
            kind = str(hold.get("decision") or "")
            if kind in A_NO_FIX or kind.startswith("duplicate"):
                self._decision_set(ls, bid, kind, hold.get("question", ""), portion.get("engine", ""), now)
            if portion.get("engine") in self.ARCH_ENGINES and (kind in A_NO_FIX or kind.startswith("duplicate")):
                try:        # the architect's own no-fix answer: kept until the row's text changes or the term ends
                    ls.setdefault("hold_hash", {})[bid] = self._row_hashes("text")[bid]
                    ls.setdefault("hold_arch", {})[bid] = now + self.cfg.not_code_term_s
                except Exception as e:
                    self.err("hold fingerprint", e)
        for rec in portion.get("not_code") or []:
            self._decision_set(ls, rec.get("backlog_id", row), "not_code", rec.get("reason", ""), portion.get("engine", ""), now)
            self._not_code_set(ls, rec.get("backlog_id", row), rec.get("reason", ""), self._row_hashes("text").get(row, ""),
                               engine=portion.get("engine", ""))
        self.save_ls(ls)
        self.event("reslice", status="applied", backlog_id=row, gen=gen, added=len(added), cause=cause)
        return len(added)

    def _slice_watch(self, tasks, state, ls, now) -> None:
        """W-prio2 2-3: a slicer older than SLICE_STALE_S is dropped (event, place freed, its result ignored); fresh rows
        (rank above rel-base) with an expired wait and no slice started or ended for SLICE_STARVED_S -> infra slicer_starved
        once per SLICE_STARVED_S, with the reason (startable, slots, holder)."""
        for row, job in list(self._slicers.items()):
            age = time.monotonic() - job.t0
            if age > SLICE_STALE_S:
                del self._slicers[row]
                job.ctx["dropped"] = True
                self.__dict__.setdefault("_hypo_dropped", []).append(job)    # fac-choke: a dropped slicer keeps its snapshot while its thread runs (no walk over a pruned tree)
                self._slice_act = now
                self.event("slice", backlog_id=row, status="stale", age_s=round(age), reason="slicer older than %d s dropped, result ignored" % SLICE_STALE_S)
        waits = ls.get("slice_wait", {})
        holders = sorted(b for b in ls.get("to_slice", {}) if F.row_rank(b) < 2 and waits.get(b, 0) <= now and b not in self._slicers)
        act = getattr(self, "_slice_act", None)
        if act is None or not holders:
            self._slice_act = now if act is None else act
            return
        if now - act < SLICE_STARVED_S or now - getattr(self, "_starved_at", -SLICE_STARVED_S) < SLICE_STARVED_S:
            return
        self._starved_at = now
        self.event("infra", status="slicer_starved",
                   reason="no slice started or ended for %d s; startable=%d slots=%d/%d holder=%s waiting=%d" % (
                       now - act, len(self._startable(tasks, state, now)), len(self._slicers), SLICE_PARALLEL, holders[0], len(holders)))

    PARKED_TRIES = 20       # W-ask 4c: a portion that meets a busy state lock this many steps in a row is given up (event)

    def _park_portion(self, bid, gen, portion, cause) -> None:
        parked = self.__dict__.setdefault("_parked_portions", {})
        old = parked.get(bid)
        parked[bid] = dict(gen=gen, portion=portion, cause=cause, tries=(old["tries"] + 1) if old else 1)
        self.event("reslice", status="lock_busy", backlog_id=bid, cause=cause, reason="state locked: the portion is applied on the next step")

    def _apply_parked(self) -> int:
        """W-ask 4c: the portions the state lock refused are applied first (the slicer's work is not lost, the slicer is not asked again)."""
        parked = self.__dict__.get("_parked_portions")
        count = 0
        for bid in list(parked or ()):
            rec = parked[bid]
            try:
                count += self._apply_portion(bid, rec["gen"], rec["portion"], rec["cause"])
            except F.LockBusy:
                rec["tries"] += 1
                if rec["tries"] >= self.PARKED_TRIES:
                    del parked[bid]
                    self.event("reslice", status="error", backlog_id=bid, reason="state locked %d steps: the portion is dropped" % rec["tries"])
                continue
            except Exception as exc:
                parked.pop(bid, None)
                self.event("reslice", status="error", backlog_id=bid, reason=F.redact(str(exc)))
                continue
            del parked[bid]
        return count

    def _reslice_tick(self, tasks, state, ls, now) -> int:
        if self.slice_fn is None:
            return 0
        try:
            self._slice_watch(tasks, state, ls, now)
        except Exception as exc:
            self.event("reslice", status="error", reason="slice watch: " + F.redact(str(exc)))
        try:
            self._quarantine_rows(tasks, state, ls, now)
        except Exception as exc:                  # a failure of the quarantine pass is an event, not a brake
            self.event("reslice", status="error", reason="quarantine pass: " + F.redact(str(exc)))
        tasks, state = self.load()
        ls = self.ls()
        count = self._apply_parked()
        if count:
            tasks, state = self.load()
            ls = self.ls()
        if self.cfg.architect_rungs:
            changed = False
            ladder_now = self._ladder_sig() if ls.get("quarantine") else ""      # fac-reslice: ONE read of the ladder per tick (was one per quarantine row: which() + env + channels.json each)
            for bid, rec in list(ls.get("quarantine", {}).items()):
                if rec.get("kind") == "failed_gens":
                    continue
                if rec.get("version") != F.slicer_version() or rec.get("ladder") != ladder_now:
                    ls["quarantine"].pop(bid)
                    ls.get("reslices", {}).pop(bid, None)
                    changed = True
            if changed:
                self.save_ls(ls)
        eligible = self._resliceable(tasks, state, ls, now)
        boxed = self._box_rows()
        prios = {}          # <id>: the priorities of every row in one pass over the plan (was one pass per row: 1.2 s a tick)
        for t in tasks.values():
            prios.setdefault(F.row_of(t.backlog_id or t.id), []).append(t.priority)
        def order(bid):
            entry = ls.get("to_slice", {}).get(bid, {})
            priority = entry.get("priority")
            if priority is None:
                priority = min(prios.get(bid, ()), default=9)
            tier = (2 if F.is_base_debt(bid) else 1 if bid.startswith("rel-") else 0) if eligible.get(bid) == "dry" else 0
            return (bid not in boxed, F.row_rank(bid), tier, self._bisect_rank(bid), int(entry.get("lane") or 0), int(str(priority).removeprefix("P")), not bool(entry.get("guard")), bid)
        first_waits = any(c == "first" and b not in self._slicers for b, c in eligible.items())
        tasks, state = self.load()                # W-tick2 2: one fresh read right before the rows (a tick of this step may have moved the plan)
        moved = False
        begun = time.monotonic()
        self._tick_memo = {}            # <id>: what every row of this pass shares (the pool cap) is computed once
        stuck_memo = None               # fac-reslice: stuck_rows of the plan, once per read of the plan (was once per row)
        paid_rung = None                # fac-reslice: "paid" in the ladder, read once per tick
        for bid in sorted(eligible, key=order)[:RESLICE_PER_STEP]:
            if time.monotonic() - begun > RESLICE_STEP_S:
                break                   # the rest goes on with the next step: merges and starts do not wait for the slicer's bookkeeping
            cause = eligible[bid]
            if bid in self.__dict__.get("_parked_portions", {}):
                continue                # its finished portion waits for the lock: the slicer is not asked again
            if cause == "dry" and bid not in self._slicers and sum(
                    j.ctx["cause"] == "dry" for j in self._slicers.values()) >= DRY_SLICE_MAX:
                continue                # W-dry 1: at most DRY_SLICE_MAX rows at once go to the slicer for code
            if first_waits and cause != "first" and bid not in self._slicers and sum(
                    j.ctx["cause"] != "first" for j in self._slicers.values()) >= SLICE_PARALLEL // 3:
                continue
            try:
                if moved:                         # W-tick 4: read anew only after a row moved the plan (not once per row)
                    tasks, state = self.load()
                    moved = False
                    stuck_memo = None
                ls = self.ls()
                rec = ls.get("reslices", {}).get(bid, {})
                used = rec.get("used", 0)
                rung = 0 if cause == "first" else used + (cause == "stuck")
                if self.cfg.architect_rungs and self.slice_fn == self._slice:
                    guarded = ls.get("to_slice", {}).get(bid, {}).get("guard") or self._guard_traces(state).get(bid)
                    if paid_rung is None:
                        paid_rung = "paid" in self._ladder_sig().split(",")
                    hard_rung = self.cfg.hard_first_rung if paid_rung else 0
                    hist = ls.get("row_hist", {}).get(bid, {})
                    free_ok = bool(guarded) and not hist.get("free_first")     # W-hard 2: free once in the life of the row
                    rung = (0 if free_ok else hard_rung) if cause == "first" else rec.get("rung", used) + (cause == "stuck" and not rec.get("esc"))
                    if ls.get("to_slice", {}).get(bid, {}).get("done"):
                        rung = 0 if free_ok else hard_rung
                    if cause == "first" and (hist.get("failed_gens") or rec.get("esc")):
                        rung = max(rung, rec.get("rung", 0))               # W-hard 1: the history goes on, not from the start
                if cause == "dry":
                    rung = 0                   # W-dry 1: no step of the ladder is spent
                    if bid not in self._slicers:
                        mark = self.ls()
                        mark.setdefault("dry_tried", {})[bid] = self.base_sha
                        self.save_ls(mark)
                if stuck_memo is None:
                    stuck_memo = F.stuck_rows(state, tasks)
                evidence = "\n".join(tid + ": " + str(state["tasks"][tid].get("reason") or "")
                    for tid in stuck_memo.get(bid, []))
                portion = self.slice_fn(bid, cause, rung, evidence, gen=rec.get("n", 0) + 1,
                                       tasks=tasks, state=state, ls=ls, now=now)
                if portion is not None:
                    moved = True
                    if rung == 0 and cause == "first" and self.slice_fn == self._slice:
                        fresh = self.ls()
                        fresh.setdefault("row_hist", {}).setdefault(bid, {})["free_first"] = True
                        self.save_ls(fresh)
                    try:
                        count += self._apply_portion(bid, rec.get("n", 0) + 1, portion, cause)
                    except F.LockBusy:      # W-ask 4c: the slicer's finished portion is kept and applied on the next step
                        self._park_portion(bid, rec.get("n", 0) + 1, portion, cause)
            except Exception as exc:
                moved = True
                ls = self.ls()
                rec = self._wait_record(ls, bid, create=True)
                pause = SLICE_PAUSES[min(rec["waits"], len(SLICE_PAUSES) - 1)]
                if isinstance(exc, SliceWait) and self._slice_hopeless():
                    pause = max(pause, SLICE_HOPELESS_S)     # W-gemma2 4: no money and no main: not oftener than every 10 minutes
                ls.setdefault("slice_wait", {})[bid] = now + pause
                rec["waits"] += 1
                self.save_ls(ls)
                if not isinstance(exc, SliceWait):
                    self.event("reslice", status="error", backlog_id=bid, reason=F.redact(str(exc)))
        self._tick_memo = None
        return count

    def _triage_prefetch(self, state, tasks, ls, now, limit=None, topup=False) -> bool:
        """The same portion in the background thread: the loop keeps admitting and reaping meanwhile."""
        if self._bg is not None:
            return False
        quotas = copy.deepcopy(ls.get("locate_quotas") or {})     # private: merged back when the result is applied
        ctx = self._triage_prepare(state, tasks, ls, now, quotas=quotas)
        if limit:
            ctx["kwargs"]["limit"] = limit
        ctx["topup"] = topup
        self.save_ls(ls)                                          # the seen reset and the weak drops are kept
        ctx["quotas"] = quotas
        return self._bg_start("triage", lambda: ctx["fn"](**ctx["kwargs"]), ctx)

    def _triage_apply(self, job) -> None:
        ctx = job.ctx
        ls = self.ls()                                  # fresh: the state moved on while the portion was asked
        ls["locate_quotas"] = ctx["quotas"]
        ctx["dur_s"] = round(job.dur_s, 3)
        if job.error is None:
            out = self._triage_finish(job.result, ctx, ls)
            if out is not None and out.proof:
                self._series_ok()                       # triage worked while a runner works: the infra series ends
        elif isinstance(job.error, (ValueError, NotImplementedError)):
            self._triage_failed(job.error, ctx, ls)
        else:
            raise job.error

    @staticmethod
    def _task_rows(state, tasks) -> set:
        """Backlog ids (a part '<ID>#k' and its row_of) that have at least one task that is not terminal. A FAILED task
        whose reason is terminal (superseded, not_code, sliced, closed, quarantine) holds nothing: a row with only such
        tasks is not known by its tasks."""
        live = set()
        for tid, row in state["tasks"].items():
            t = tasks.get(tid)
            bid = row.get("backlog_id") or (t.backlog_id if t else "")
            if not bid or (row.get("status") == "FAILED" and F.is_terminal(row.get("reason"))):
                continue
            live.add(bid)
            live.add(F.row_of(bid))
        return live

    def _triage_prepare(self, state, tasks, ls, now, quotas=None) -> dict:
        cfg = self.cfg
        fn = self.triage_fn
        if fn is None:
            from tools.agent_factory_import import triage_portion as fn
        self._expire_slicer_decisions(ls)
        known = self._task_rows(state, tasks)
        mtime = cfg.backlog.stat().st_mtime
        if ls.get("seen_mtime") != mtime:  # backlog edited: stale/skipped rows get a fresh look
            ls["seen"], ls["seen_mtime"] = {}, mtime
            self._refresh_profile_attempts(ls)
        dropped = self._drop_weak_candidates(ls, now)
        known |= set(ls["holds"]) | set(ls["closed"])
        known |= {b for b, rec in ls["seen"].items() if not self._seen_expired(rec, now)}
        known |= self._not_code_known(ls, now)              # <id>: survives edits until the row's own text changes
        known |= {b for b, rec in (ls.get("parents") or {}).items()
                  if rec.get("children") and all(c in known for c in rec["children"])}   # all parts exist: no re-import
        known |= set(ls.get("to_slice", {})) | set(ls.get("quarantine", {})) | set(ls.get("split") or {})
        # invariant "no lost row": a row whose tasks are all terminal (_task_rows leaves it out) is known only through a
        # live decision above (parents, to_slice, quarantine); an expired not_code/hold makes it unknown and the triage
        # hands it to the slicer. The source of the loss is closed in _apply_portion (a decision for another id).
        t0 = self.clock()
        kwargs = dict(backlog_path=cfg.backlog, head_root=cfg.worktree,
                      known_backlog_ids=known, limit=cfg.triage_limit)
        if _accepts(fn, "self_repo"):
            kwargs["self_repo"] = cfg.self_repo
        if _accepts(fn, "profile_attempts"):
            kwargs["profile_attempts"] = dict(ls.get("profile_attempts") or {})
        scopes = {b: s for b, s in (ls.get("head_scope") or {}).items() if b not in known and isinstance(s, dict)}
        if scopes and _accepts(fn, "scopes"):
            kwargs["scopes"] = scopes
        if _accepts(fn, "trace"):
            kwargs["trace"] = self._guard_traces(state)
        if _accepts(fn, "ask"):
            kwargs["ask"] = self._locate_ask(ls, quotas)
        return {"fn": fn, "kwargs": kwargs, "mtime": mtime, "dropped": dropped, "t0": t0, "now": now}

    def _guard_traces(self, state) -> dict:
        """<id>: {backlog_id: [(rel, qualname, line)]} - the cloud trace of the failing guard the gate returned (base_red.result.path
        of the row's task), for the slicer to narrow each one-file part's guard to its file's functions."""
        # fac-reslice: a trace file is written once per measurement of the base (base_red.at is its stamp), so the parsed trace is
        # kept per row under (file, at, key) and the disk is read only for a new or changed measurement (was: every call
        # re-read and re-parsed ~350 trace files, 2-4 calls a tick on the main thread, ~half of the reslice tick).
        cache = self.__dict__.setdefault("_trace_cache", {})
        out = {}
        seen = set()
        for tid, row in (state.get("tasks") or {}).items():
            try:
                bid = row.get("backlog_id")
                red = row.get("base_red") or {}
                result = red.get("result") or {}
                sig = (str(result.get("path_file") or ""), red.get("at"), red.get("key"))
                seen.add(tid)
                hit = cache.get(tid)
                if hit is not None and hit[0] == sig and sig[0]:
                    path = hit[1]
                else:
                    raw = F.load_trace(self.cfg.state_dir, row)     # <id>: the trace lives beside the state
                    path = [(str(c[0]), str(c[1]), int(c[2])) for c in raw][:400] if raw else None
                    if raw is not None and sig[0]:
                        cache[tid] = (sig, path)       # a file's empty trace is a real answer and is kept too; unreadable (None) or inline is read again
                    else:
                        cache.pop(tid, None)
                if bid and path:
                    out[str(bid)] = list(path)
            except (TypeError, ValueError, IndexError, AttributeError):
                continue
        for tid in [t for t in cache if t not in seen]:
            cache.pop(tid, None)
        return out

    def _triage_failed(self, e, ctx, ls) -> Outcome:
        cfg, now, mtime = self.cfg, ctx["now"], ctx["mtime"]
        ls["triage_empty"] = {"mtime": mtime, "until": now + cfg.triage_retry_s}
        self._defer_seen(ls, now)
        self.save_ls(ls)
        if isinstance(e, ValueError):  # the backlog cannot be parsed: not infrastructure, try after an edit
            self.event("triage", status="empty", reason="backlog_unparsable: " + F.redact(str(e))[:120])
            return Outcome(action="TRIAGE", reason="backlog_unparsable", status="empty",
                           sleep=cfg.triage_idle_sleep)
        self.event("triage", status="empty",
                   reason="triage_not_implemented: " + F.redact(str(e))[:120])
        return Outcome(action="TRIAGE", reason="triage_not_implemented", status="empty")

    def _triage_finish(self, res, ctx, ls) -> Outcome:
        cfg, now, mtime, dropped, t0 = self.cfg, ctx["now"], ctx["mtime"], ctx["dropped"], ctx["t0"]
        self._book_seen(ls, res, now)
        portion = list(res.get("tasks") or [])
        new_holds = []
        added = []
        skipped_by_append = []
        try:
            added = F.append_tasks(self.plan_path, portion)
            skipped_by_append = [
                {k: self.rs(v) for k, v in x.items() if k in ("id", "backlog_id", "reason")}
                for x in (getattr(added, "skipped", None) or [])][:10]
        except F.InvalidPlan as e:  # one bad task must not repeat forever or trip the brake
            why = self._scrub("invalid plan portion: " + F.redact(str(e))[:200])
            for t in portion:
                bid = (t.get("backlog_id") or t.get("id")) if isinstance(t, dict) else None
                if bid and bid not in ls["holds"]:
                    ls["holds"][bid] = why
                    new_holds.append(bid)
        for h in res.get("holds") or []:
            bid = h.get("backlog_id")
            if bid and bid not in ls["holds"]:
                ls["holds"][bid] = self._scrub(F.redact(str(h.get("question", ""))))[:500]
                new_holds.append(bid)
        queued = list(res.get("to_slice") or [])
        for entry in queued:
            bid = entry["backlog_id"]
            ls.setdefault("to_slice", {}).setdefault(bid, dict(entry, at=now))
        self._sync_stale_rows(res.get("stale") or ())
        if res.get("not_code"):       # <id>: rows the triage cut by structure (documentation only) join the not_code book
            try:
                texts = self._row_hashes("text")
            except Exception as e:
                self.err("not_code: backlog unreadable", e)
                texts = {}
            for x in res["not_code"]:
                if isinstance(x, dict) and texts.get(x.get("backlog_id")):
                    self._not_code_set(ls, x["backlog_id"], x.get("reason") or "", texts[x["backlog_id"]])
        if ls.get("head_scope"):
            # <id>: a picked scope is used up once the triage reported its row (tasks, a hold or a skip); a deferred
            # row keeps it for the next portion; a row that left the backlog loses it
            done = {t.get("backlog_id") for t in portion if isinstance(t, dict) and added} | set(new_holds)
            for key in ("skipped", "stale"):
                done |= {x.get("backlog_id") if isinstance(x, dict) else x for x in res.get(key) or []}
            done |= {h.get("backlog_id") for h in res.get("holds") or [] if isinstance(h, dict)}
            try:
                rows = set(self._row_hashes("text"))
            except Exception:
                rows = None
            for b in list(ls["head_scope"]):
                if b in done or (rows is not None and b not in rows):
                    ls["head_scope"].pop(b, None)
        if isinstance(res.get("profile_attempts"), dict):
            ls.setdefault("profile_attempts", {}).update(res["profile_attempts"])
        for bid in new_holds:
            ls.setdefault("hold_ver", {})[bid] = F.slicer_version()
            ls.get("profile_attempts", {}).pop(bid, None)
        deferred = list(res.get("deferred") or [])  # postponed by the portion deadline: not seen
        events = [self.rs(str(x)) for x in (res.get("events") or [])[:10]]
        if new_holds:
            try:
                texts = self._row_hashes("text")
                for b in new_holds:
                    if b in texts:
                        ls["hold_hash"][b] = texts[b]
            except Exception as e:
                self.err("hold fingerprint", e)
        progress = bool(added) or bool(new_holds) or bool(queued)
        if ctx.get("topup"):                         # <id>: an empty top-up portion lengthens the wait of the next one
            ls["ready_triage_idle"] = 0 if progress else min(int(ls.get("ready_triage_idle") or 0) + 1, 4)
        ls["triage_empty"] = None if (progress or deferred) else {"mtime": mtime,
                                                                   "until": now + cfg.triage_retry_s}
        self.save_ls(ls)
        tasks2, state2 = self.load()
        if new_holds or dropped:
            self._write_questions(tasks2, state2, ls)
        self._write_reconcile(tasks2, state2, ls, now)
        self.event("triage", status="added" if progress else "empty", dur_s=ctx.get("dur_s") or round(
            self.clock() - t0, 3), prefetch=True if "quotas" in ctx else None, reason="added=%d holds=%d skipped=%d stale=%d" % (
            len(added), len(new_holds), len(res.get("skipped") or ()), len(res.get("stale") or ())),
            append_skipped=skipped_by_append or None, deferred=len(deferred) or None,
            events=events or None)
        status = "added" if added else ("holds" if new_holds else "empty")
        return Outcome(action="TRIAGE", reason="added=%d holds=%d" % (len(added), len(new_holds)),
                       status=status,
                       sleep=0 if (added or new_holds) else cfg.triage_idle_sleep)

    def _drop_weak_candidates(self, ls, now) -> int:
        """<id>: a candidates hold whose row has no strong code signal any more (raised by the older words-only rule,
        or its signal is gone at HEAD) leaves the holds before the triage: booked as a seen skip «кандидаты слабые»
        with a term (cfg.seen_retry_s), never asked to the head. Independent of the triage's portion limit. A
        failure keeps the holds (the next triage tries again)."""
        from tools import factory_holds as H
        ids = [b for b, q in (ls.get("holds") or {}).items() if H.kind_of(q) == "candidates"]
        ids += [b for b in (ls.get("head_scope") or {}) if b not in ids]     # a pick made on a weak hold: same rule
        if not ids:
            return 0
        try:
            from tools import agent_factory_import as imp
            weak = imp.weak_candidate_holds(self.cfg.worktree, self.cfg.backlog, ids)
        except Exception as e:
            self.err("weak candidates recheck", e)
            return 0
        for bid, why in weak.items():
            ls["holds"].pop(bid, None)
            ls.get("hold_hash", {}).pop(bid, None)
            (ls.get("head_scope") or {}).pop(bid, None)
            ls["seen"][bid] = {"kind": "skipped", "reason": self._scrub(F.redact("нет упомянутых файлов; " + why))[:200],
                               "until": now + self.cfg.seen_retry_s}
        if weak:
            self.event("triage", status="hold_dropped", reason="weak candidates: %d (%s)" % (
                len(weak), ", ".join(sorted(weak)[:10])))
        return len(weak)

    PARENTS_MAX = 100

    def _close_parents(self, tasks, state, ls: dict) -> dict:
        """A cut row is closed (the durable close path) once ALL its code tasks are DONE or PROMOTED."""
        if not isinstance(ls.get("parents"), dict):
            ls["parents"] = {}
        book = ls["parents"]
        for bid, rec in list(book.items()):
            if bid in ls["closed"]:
                book.pop(bid, None)
                self.save_ls(ls)
                continue
            rows = [state["tasks"].get(t) for t in rec.get("code_tasks") or []]
            if not rows or any(r is None or r.get("status") not in ("DONE", "PROMOTED") for r in rows):
                continue
            try:
                self._close_answer({}, "", bid, tasks, state, "all %d parts of the row are done" % len(rows))
            except _Later as e:
                self.event("answer", status="deferred", reason="parent %s: %s" % (
                    self.rs(bid, 64), F.redact(str(e))[:150]))
                continue                      # the backlog is unreadable now: the next step tries again
            except F.InvalidPlan as e:
                self.event("answer", status="error", reason="parent %s not closed: %s" % (
                    bid, F.redact(str(e))[:150]))
                book.pop(bid, None)           # the row is not in the backlog (any more): nothing to close
                self.save_ls(ls)
                continue
            ls = self.ls()                    # _close_answer saved its own copy of the loop state
            ls.get("parents", {}).pop(bid, None)
            self.save_ls(ls)
            book = ls.get("parents") or {}
            self.event("answer", status="applied", reason="parent %s closed: all parts done" % bid)
        return ls                             # the freshest copy: _close_answer saved its own

    def _answer_cmd(self, bid, tid="", touch="<файлы>", tests="<тесты>") -> str:
        return ('python -m tools.factory_loop answer --state-dir "%s" --backlog-id %s%s '
                '--touch %s --tests %s --note "<указание кодеру>"' % (
                    self.dir, bid or "<ID>", " --task-id " + tid if tid else "", touch, tests))

    def _row_hashes(self, field: str = "row") -> dict:
        """{backlog_id: hash}. field='text' hashes the wording only (evidence/state updates of the
        coordinator must not reopen a closed row); 'row' hashes the whole line."""
        from hashlib import sha256
        from tools import agent_factory_import as imp
        raw = Path(self.cfg.backlog).read_bytes()
        key = (sha256(raw).hexdigest(), field)     # <id>: the parse (1.9 s on the live backlog) runs once per content, not per tick
        memo = self.__dict__.setdefault("_row_hash_memo", {})
        if key not in memo:
            md = raw.decode("utf-8-sig")
            if len(memo) > 8:
                memo.clear()
            memo[key] = {r["backlog_id"]: sha256(r[field].encode("utf-8")).hexdigest()[:16]
                         for r in imp.parse_section4(md)}
        return dict(memo[key])

    def _refresh_profile_attempts(self, ls: dict) -> None:
        """A counter lives while its row is unchanged: only rows that vanished or changed lose it."""
        attempts = ls.get("profile_attempts") or {}
        try:
            now = self._row_hashes()
        except Exception as e:  # unreadable backlog: keep the counters, say why
            self.err("profile attempts refresh", e)
            return
        old = ls.get("profile_hash") or {}
        ls["profile_attempts"] = {b: n for b, n in attempts.items()
                                  if b in now and old.get(b, now[b]) == now[b]}
        ls["profile_hash"] = now
        try:
            texts = self._row_hashes("text")
            for b, h in list(ls.get("hold_hash", {}).items()):  # rewritten row: back to triage
                if b not in ls["holds"]:
                    ls["hold_hash"].pop(b, None)
                elif b in texts and texts[b] != h:
                    ls["holds"].pop(b, None)
                    ls["hold_hash"].pop(b, None)
                    self.event("triage", status="hold_dropped", reason="row %s was rewritten" % b)
            ls["closed"] = {b: h for b, h in (ls.get("closed") or {}).items()
                            if h == "closed" or (b in texts and texts[b] == h)}
        except Exception as e:
            self.err("closed rows refresh", e)

    # the task state that speaks for a backlog row with several tasks: the least finished one
    RECONCILE_ORDER = ("RUNNING", "REVIEW", "READY", "BLOCKED", "FAILED", "DONE", "PROMOTED")

    def _iso_safe(self, value, default) -> str | None:
        """A term of a ledger record as a time; a broken one (text, None) never stops the report of the other rows."""
        try:
            return self._iso(float(value or default))
        except (TypeError, ValueError, OverflowError, OSError):
            return None

    RECONCILE_TICK_S = 300.0
    SUPPLY_RETURN_S = 86400.0

    def _supply_invariant(self, tasks, state, ls, now):
        """W-supply 1: every OPEN backlog row is in exactly one state. A row with tasks that are all terminal (superseded / closed /
        not_code / sliced / quarantine) and with no full-closure PROMOTED task, hold, not_code, closed, quarantine, to_slice,
        parts, split or running slicer has lost its place (live 23.11: 61 ECHO rows 'FAILED' nowhere): it returns to to_slice,
        once per CONTRACT_REV and not oftener than every 24 h, with the event supply status=returned. Returns the saved ls or None."""
        from tools import agent_factory_import as imp, factory_architect as A
        rev = str(A.CONTRACT_REV)
        md = Path(self.cfg.backlog).read_bytes().decode("utf-8-sig")
        try:
            rows4 = imp.parse_section4(md)
        except ValueError:                           # no bounded section 4 (a bare backlog): no rows to keep, no event
            return None
        open_rows = {r["backlog_id"]: r for r in rows4 if r.get("open", True)}
        if not open_rows:
            return None
        by_row = {}
        for tid, row in state["tasks"].items():
            t = tasks.get(tid)
            bid = F.row_of(row.get("backlog_id") or (t.backlog_id if t else "") or "")
            if bid in open_rows:
                by_row.setdefault(bid, []).append(row)
        if not by_row:
            return None
        cur = self.ls()
        placed = set()
        for key in ("holds", "not_code", "closed", "quarantine", "to_slice", "parents", "split"):
            placed |= set(cur.get(key) or {})
        placed |= set(getattr(self, "_slicers", {}) or {})
        disp = self._dispositions(now, strict=True)
        if disp is None:                                 # W-tick2 1: unknown, not empty: no tick, nothing written
            return None
        mem = cur.setdefault("supply_returned", {})
        returned = []
        for bid, rows in sorted(by_row.items()):
            if bid in placed or bid in disp:
                continue
            if any(r.get("status") == "PROMOTED" for r in rows):
                continue
            if not all(r.get("status") == "FAILED" and F.is_terminal(r.get("reason")) for r in rows):
                continue
            rec = mem.get(bid) or {}
            if rec and (rec.get("rev") == rev or now - float(rec.get("at") or 0) < self.SUPPLY_RETURN_S):
                continue
            entry = {"at": now, "hints": [], "guard": ""}
            if open_rows[bid].get("priority"):
                entry["priority"] = open_rows[bid]["priority"]
            cur.setdefault("to_slice", {})[bid] = entry
            cur.get("slice_wait", {}).pop(bid, None)
            cur.get("reslices", {}).pop(bid, None)      # a fresh first pass, not a spent budget
            mem[bid] = {"rev": rev, "at": now}
            returned.append(bid)
        if not returned:
            return None
        self.save_ls(cur)
        for bid in returned:
            self.event("supply", status="returned", backlog_id=bid, reason="all tasks terminal, no record: back to the slicer")
        return cur

    LOST_TICK_S = 60.0                  # W-lost 1: the feed invariant looks once a minute (one pass over the plan, no model, no git)
    LOST_AGAIN_S = 6 * 3600.0           # one row is given back not oftener than every 6 h on the same slicer version
    OLD_HOLD_TEXT = ("выбрать область", "spec: not a testable")        # the wording of the old triage
    KEPT_HOLD_WORDS = ("only_opus", "private", "приватн", "влад" "ельц", "owner")      # privacy / only_opus / the owner's rules stay
    NOT_CODE_DOC = "не код: строка описывает документ"
    SLICE_LANES = {"guard": 0, "lost": 1, "hold": 2, "not_code": 3}     # the order of the feed: red guard, lost, old holds, not_code

    def _lost_tick(self, tasks, state, ls, now):
        """W-lost: returns the ls the caller goes on with (the pass may have saved a newer one)."""
        if now - float(getattr(self, "_lost_at", -1e9)) < self.LOST_TICK_S:
            return ls
        self._lost_at = now
        try:
            return self._lost_rows(tasks, state, now) or ls
        except Exception as e:                       # the feed invariant never stops the loop
            self.err("lost rows", e)
            return ls

    def _lost_entry(self, bid, rows, cur, now, lane, open_rows, **extra) -> dict:
        """A to_slice record of a row given back: hints from its earlier tasks, the guard test when the row has one."""
        hints = []
        for _tid, _row, t in rows:
            for name in (tuple(t.touch_files) + tuple(t.read_files)) if t else ():
                if name and name not in hints:
                    hints.append(name)
        guard = self._guard_of_row(bid, cur)
        entry = {"at": now, "hints": hints[:8], "guard": guard, "lane": self.SLICE_LANES["guard"] if guard else lane}
        if guard:
            entry["priority"] = 0
        elif (open_rows.get(bid) or {}).get("priority"):
            entry["priority"] = open_rows[bid]["priority"]
        entry.update(extra)
        return entry

    def _lost_rows(self, tasks, state, now):
        """W-lost 1/3/4, one pass: (1) an open ECHO row with no live task and no place in any book goes to to_slice (event
        supply status=lost_row, counter ``lost_count`` -> stats.json lost); (3) holds of the old triage (no slicer-version label
        or the old wording) go to to_slice once per slicer version; (4) not_code marks set without a paid/agent step on a
        «document» wording go through free_small once per version. Returns the saved ls or None."""
        from tools import agent_factory_import as imp
        try:
            rows4 = imp.parse_section4(Path(self.cfg.backlog).read_bytes().decode("utf-8-sig"))
        except ValueError:
            return None
        open_rows = {r["backlog_id"]: r for r in rows4 if r.get("open", True)
                     and not str(r["backlog_id"]).lower().startswith(("rel-", "fac-", "cl-"))}
        if not open_rows:
            return None
        version = F.slicer_version()
        by_row, live, last_gen, private = {}, set(), {}, set()
        for tid, row in state["tasks"].items():
            t = tasks.get(tid)
            bid = F.row_of(row.get("backlog_id") or (t.backlog_id if t else "") or "")
            if bid not in open_rows or not isinstance(row.get("status"), str):
                continue
            by_row.setdefault(bid, []).append((tid, row, t))
            if t is not None and (t.only_opus or not t.privacy_safe or F.is_private_text(t.title)):
                private.add(bid)
            m = re.search(r"_r(\d+)$", tid)
            if m and (t is None or t.kind == "code") and int(m.group(1)) >= last_gen.get(bid, (-1, ""))[0]:
                last_gen[bid] = (int(m.group(1)), row["status"])
            if row["status"] == "PROMOTED":
                continue                              # counts only as the LAST generation (below)
            if not (row["status"] == "FAILED" and F.is_terminal(row.get("reason"))):
                live.add(bid)
        live |= {b for b, (_, st) in last_gen.items() if st == "PROMOTED"}
        live |= {b for b, rows in by_row.items() if b not in last_gen and any(r["status"] == "PROMOTED" for _t, r, _x in rows)}
        for bid, rec in open_rows.items():
            if F.is_private_text(str(rec.get("text") or "")):
                private.add(bid)
        cur = self.ls()
        disp = self._dispositions(now, strict=True)
        if disp is None:                                 # W-tick2 1: unknown, not empty: no tick, no version mark written
            return None
        placed = set()
        for key in ("to_slice", "closed", "split", "outdated_tests", "arch_decision", "deferred", "head_scope", "holds"):
            placed |= {F.row_of(b) for b in (cur.get(key) or {})}
        placed |= set(getattr(self, "_slicers", {}) or {})
        for bid, rec in (cur.get("quarantine") or {}).items():
            if isinstance(rec, dict) and (rec.get("version") == version or rec.get("kind") == "failed_gens"):
                placed.add(F.row_of(bid))
        for bid, rec in (cur.get("not_code") or {}).items():
            if isinstance(rec, dict) and (rec.get("slicer") == version or rec.get("engine") in self.ARCH_ENGINES):
                placed.add(F.row_of(bid))
        for bid, rec in (cur.get("seen") or {}).items():
            if not (isinstance(rec, dict) and self._seen_expired(rec, now)):
                placed.add(F.row_of(bid))
        mem = cur.setdefault("lost_rows", {})
        events, changed = [], False
        for bid in sorted(by_row):                                                      # (1) the lost rows
            if bid in placed or bid in disp or bid in live or bid in private:
                continue
            rec = mem.get(bid) or {}
            if rec.get("ver") == version and now - float(rec.get("at") or 0) < self.LOST_AGAIN_S:
                continue
            cur.setdefault("to_slice", {})[bid] = self._lost_entry(bid, by_row[bid], cur, now, self.SLICE_LANES["lost"], open_rows)
            cur.get("slice_wait", {}).pop(bid, None)
            cur.get("reslices", {}).pop(bid, None)                                      # a fresh first pass, not a spent budget
            mem[bid] = {"ver": version, "at": now}
            cur["lost_count"] = int(cur.get("lost_count") or 0) + 1
            events.append(("lost_row", bid, "no live task and no place in the books: back to the slicer"))
            changed = True
        if cur.get("holds_lift_ver") != version:                                        # (3) the holds of the old triage, once per version
            cur["holds_lift_ver"] = version
            changed = True
            for bid, why in list((cur.get("holds") or {}).items()):
                row, low = F.row_of(bid), str(why).lower()
                if (row not in open_rows or row in disp or row in private or bid in (cur.get("hold_arch") or {})
                        or any(w in low for w in self.KEPT_HOLD_WORDS)):
                    continue
                if not any(m in low for m in self.OLD_HOLD_TEXT):
                    continue                          # a hold in the current wording (scope question, contract) stays
                if low.startswith(self.OLD_HOLD_TEXT[0]) and "[" in low:
                    continue                          # candidates with signal tags are the current hold; the old one had paths only
                for key in ("holds", "hold_ver", "hold_hash", "arch_decision"):
                    if isinstance(cur.get(key), dict):
                        cur[key].pop(bid, None)
                if row not in cur.setdefault("to_slice", {}):
                    cur["to_slice"][row] = self._lost_entry(row, by_row.get(row, []), cur, now, self.SLICE_LANES["hold"], open_rows)
                cur.get("slice_wait", {}).pop(row, None)
                cur.get("reslices", {}).pop(row, None)
                events.append(("hold_lifted", row, "hold of the old triage: back to the slicer"))
        if cur.get("not_code_recheck_ver") != version:                                  # (4) not_code without a paid/agent step
            cur["not_code_recheck_ver"] = version
            changed = True
            for bid, rec in list((cur.get("not_code") or {}).items()):
                row = F.row_of(bid)
                if not isinstance(rec, dict) or row not in open_rows or row in disp or row in private:
                    continue
                engine = str(rec.get("engine") or "")
                if (not str(rec.get("reason") or "").startswith(self.NOT_CODE_DOC) or engine in self.ARCH_ENGINES
                        or "+" in engine or (cur.get("not_code_free") or {}).get(bid) == version):
                    continue                          # the answer of two different models stays
                cur["not_code"].pop(bid, None)
                cur.setdefault("not_code_free", {})[bid] = version
                if row not in cur.setdefault("to_slice", {}):
                    cur["to_slice"][row] = self._lost_entry(row, by_row.get(row, []), cur, now, self.SLICE_LANES["not_code"], open_rows,
                                                            only="free_small", rule=self.W_SUPPLY_RULE)
                cur.get("slice_wait", {}).pop(row, None)
                cur.get("reslices", {}).pop(row, None)
                events.append(("not_code_recheck", row, "not_code without a paid/agent step: free_small once per version"))
        if not changed:
            return None
        self.save_ls(cur)
        for status, bid, reason in events:
            self.event("supply", status=status, backlog_id=bid, reason=reason)
        return cur

    W_SUPPLY_RULE = ("W-supply: a general row (a document, a process, a whole area) is not_code only when no concrete defect follows from its "
                     "text and the code; otherwise answer split with 1-3 concrete defects.")

    GUARD_FILE = re.compile(r"(?:^|/)tests/verify/(?:[^/]+/)*test_v_[^/]+\.py$")

    @staticmethod
    def _guard_id_guess(path) -> str:
        """The row ID of a guard file the backlog does not know: <id>.py -> <id>, <id>.py -> <id> (a number part
        with a leading zero is a dash, a single number part is a dot); '' when the name has no ID."""
        stem = Path(str(path)).stem
        if not stem.lower().startswith("test_v_") or len(stem) <= 7:
            return ""
        tail = stem[7:]
        found = re.match(r"^([A-Za-z]+\d+)_(\d+)$", tail)
        if found:
            return found.group(1) + ("-" if found.group(2).startswith("0") else ".") + found.group(2)
        return tail if re.match(r"^[A-Za-z]+\d+([._-]\d+)?$", tail) else ""

    OD_BUDGET_S = 15.0         # W-prio fix2: all `git log -S` calls of one outdated tick together

    OD_EVERY_S = 1800.0

    def _outdated_tick(self, now) -> int:
        """W-prio 3: once per base sha, every open red baseline row rel-base-<n> is checked before slicing: when every red test of the row
        names (a settings key, a setattr/setitem target, a getattr, an import from the product) something that is nowhere in the product
        tree, the row is outdated_test: no cards, READY cards superseded:outdated_test, the test stays in the red list.  A row whose names
        came back goes to to_slice again.  Returns the number of rows that changed."""
        sha = self.base_sha
        if not sha:
            return 0
        from tools import factory_outdated as OD, factory_release as REL
        by_row = {}
        for file, rec in REL.debt(self.cfg.state_dir).items():
            if not rec.get("closed") and rec.get("tests") and rec.get("n"):
                by_row["rel-base-%d" % int(rec["n"])] = [str(t) for t in rec["tests"]]
        od_key = (sha, tuple(sorted(by_row)))       # W-prio fix2: a row that appears/reopens at the same sha is checked too
        if od_key == getattr(self, "_od_key", None):
            return 0
        if time.monotonic() - getattr(self, "_od_at", -1e9) < self.OD_EVERY_S:
            return 0                    # 20-60 s of parsing; a merge every few minutes rarely changes the verdict
        self._od_at = time.monotonic()
        index = OD.Index(self.mirror)
        verdict = {}
        for bid, tests in by_row.items():
            found = [OD.missing_names(self.mirror, t, index) for t in tests]
            if found and all(found):
                verdict[bid] = (tests[0], found[0])
        ls = self.ls()
        book = ls.setdefault("outdated_tests", {})
        new, back = [], []
        deadline = time.monotonic() + self.OD_BUDGET_S      # W-prio fix2: one budget for all git log -S of this tick
        def last_seen(name):
            left = deadline - time.monotonic()
            return OD.last_seen(self.cfg.repo, name, timeout=min(8.0, left)) if left > 0.5 else ""
        for bid in sorted(set(verdict) - set(book)):
            names = [{"kind": k, "name": n, "last": last_seen(n)} for k, n in verdict[bid][1][:6]]
            book[bid] = {"test": verdict[bid][0], "names": names, "at": now, "sha": sha[:12]}
            for key in ("to_slice", "slice_wait", "reslices", "quarantine"):
                if isinstance(ls.get(key), dict):
                    ls[key].pop(bid, None)
            new.append(bid)
        for bid in sorted(set(book) - set(verdict)):
            kept = book.get(bid)
            if isinstance(kept, dict) and kept.get("source") == "solver" and now - float(kept.get("at") or 0) < 86400:
                continue                            # W-solver: two models said the assert is outdated: it stays 24 h
            if bid in by_row:                       # the names are back in the tree: the row is a live red row again
                entry = self._rel_entry_back(ls, bid)
                if entry:
                    ls.setdefault("to_slice", {}).setdefault(bid, entry)
            book.pop(bid, None)                     # (a row that left the debt book leaves this one)
            back.append(bid)
        self._od_key = od_key
        if not (new or back):
            return 0
        self.save_ls(ls)
        if new:
            def supersede(st):
                for tid, row in st["tasks"].items():
                    bid = F.row_of(row.get("backlog_id") or tid)
                    if bid in new and row.get("status") == "READY":
                        row.update(status="FAILED", reason="superseded:outdated_test")
            try:
                self._tx(supersede)
            except Exception as e:      # noqa: BLE001 - a busy plan: the cards are no longer admitted anyway (no slicing, no new ones)
                self.err("outdated tests: supersede", e)
        try:
            (self.cfg.state_dir / "outdated_tests.md").write_text(OD.report_md(ls["outdated_tests"]), encoding="utf-8")
        except OSError as e:
            self.err("outdated tests: report", e)
        for bid in new:
            self.event("supply", status="outdated_test", backlog_id=bid,
                       reason="outdated_test: %s names %s" % (self.rs(book[bid]["test"], 120), ", ".join(n["name"] for n in book[bid]["names"][:4])))
        for bid in back:
            self.event("supply", status="outdated_test_lifted", backlog_id=bid, reason="the names are back in the product tree")
        return len(new) + len(back)

    def _guard_red_tick(self, now, AF) -> None:
        """W-echo 1: on every NEW record of the sweep (its file or its modification changed) the red-guard invariant runs once."""
        latest = AF.latest_sweep(self._sweep_dir())
        if latest is None:
            return
        sig = (latest.name, latest.stat().st_mtime_ns)
        if sig == getattr(self, "_gr_sig", None):
            return
        try:
            tasks, state = self.load()
        except Exception as e:      # a busy plan lock: the next tick tries again
            if type(e).__name__ != "LockBusy":
                raise
            return
        self._gr_sig = sig
        self._guard_red_invariant(tasks, state, AF.read_sweep(latest), now)

    def _guard_red_invariant(self, tasks, state, sweep, now):
        """W-echo 1: a red tests/verify/**/test_v_<ID>.py is open work. A file with no live card (READY/RUNNING/REVIEW) and with no
        to_slice / slice_wait / quarantine record of this slicer version goes back to to_slice as row <ID> (guard = its first red test,
        priority 0), even when the row is closed in the backlog or DONE (supply status=guard_red_closed). An old rel-base-<n> record
        on the same file is taken off (superseded:guard). Once per row and CONTRACT_REV per 24 h; a 'could not find a fix' hold
        of an older CONTRACT_REV expires with it. Returns the number of rows returned."""
        from tools import agent_factory_import as imp, factory_architect as A, factory_autofeed as AF
        rev = str(A.CONTRACT_REV)
        reds = {}
        for name in sorted(k for k, red in sweep.items() if red is True):
            path = str(name).partition("::")[0]
            if self.GUARD_FILE.search(path):
                reds.setdefault(path, name)
        if not reds:
            return 0
        try:
            rows4 = imp.parse_section4(Path(self.cfg.backlog).read_bytes().decode("utf-8-sig"))
        except ValueError:
            rows4 = []
        is_open = {r["backlog_id"]: bool(r.get("open", True)) for r in rows4}
        keys = AF._keys(list(is_open))
        live_rows, live_files, done_rows = set(), set(), set()
        for tid, row in state["tasks"].items():
            t = tasks.get(tid)
            bid = F.row_of(row.get("backlog_id") or (t.backlog_id if t else "") or tid)
            if row.get("status") in ("READY", "RUNNING", "REVIEW"):
                live_rows.add(bid)
                live_files |= {str(x).partition("::")[0] for x in (t.tests if t else ())}
            elif row.get("status") in ("DONE", "PROMOTED"):
                done_rows.add(bid)
        cur = self.ls()
        version = F.slicer_version()
        mem = cur.setdefault("guard_red", {})
        to_slice = cur.setdefault("to_slice", {})
        guard_of = {b: str(e.get("guard") or "").partition("::")[0] for b, e in to_slice.items() if isinstance(e, dict)}
        returned, taken_off, seen_ids = [], [], set()
        for path, test in reds.items():
            bid = AF.id_of_guard(path, keys) or self._guard_id_guess(path)
            if not bid or bid in seen_ids or bid in live_rows or path in live_files or bid in getattr(self, "_slicers", {}):
                continue
            quarantine = (cur.get("quarantine") or {}).get(bid)
            if bid in to_slice or bid in (cur.get("slice_wait") or {}) or (isinstance(quarantine, dict) and quarantine.get("version") == version):
                continue
            if any(g == path and not b.startswith("rel-base-") for b, g in guard_of.items()):
                continue                       # a row of its own already works on this red test
            why = str((cur.get("holds") or {}).get(bid) or "").lower()
            if any(rule in why for rule in ("only_opus", "private", "приватн")):
                continue
            rec = mem.get(bid) or {}
            if rec.get("rev") == rev and now - float(rec.get("at") or 0) < self.SUPPLY_RETURN_S:
                continue
            if "could not find a fix" in why and rec.get("rev") == rev:
                continue                       # that hold expires only with a NEW CONTRACT_REV, not with the 24 h term
            seen_ids.add(bid)
            closed = (not is_open.get(bid, True)) or bid in (cur.get("closed") or {}) or bid in done_rows
            for key in ("holds", "hold_ver", "hold_hash", "hold_arch", "arch_decision", "not_code", "closed", "parents",
                        "slice_wait", "reslices", "quarantine"):
                if isinstance(cur.get(key), dict):
                    cur[key].pop(bid, None)
            for old, g in list(guard_of.items()):          # the old baseline record of the same file: the ECHO row works now
                if g == path and old.startswith("rel-base-"):
                    to_slice.pop(old, None)
                    cur.get("slice_wait", {}).pop(old, None)
                    cur.get("reslices", {}).pop(old, None)
                    taken_off.append((old, bid))
            to_slice[bid] = {"at": now, "hints": [], "guard": test, "priority": 0}
            mem[bid] = {"rev": rev, "at": now}
            returned.append((bid, closed, test))
        if not returned:
            return 0
        self.save_ls(cur)
        for old, bid in taken_off:
            try:
                from tools import factory_release as REL
                REL.close_debt(self.cfg.state_dir, old)
            except Exception as e:                          # noqa: BLE001 - the debt book never stops the supply
                self.err("guard red: debt", e)
            self.event("supply", status="superseded", backlog_id=old, reason="superseded:guard by %s" % bid)
        for bid, closed, test in returned:
            self.event("supply", status="guard_red_closed" if closed else "guard_red", backlog_id=bid,
                       reason="red guard test %s: back to the slicer" % self.rs(test, 160))
        return len(returned)

    def _reconcile_tick(self, tasks, state, ls, now) -> dict:
        """W-supply 4: reconcile.json was written only on HOLD and after a triage, so a loop that kept working never
        refreshed it (live 23.11: not written since 16:53). Now also every RECONCILE_TICK_S of any step.
        Returns the ls the caller must go on with (the invariant may have saved a newer one: never save the old dict over it)."""
        if now - float(getattr(self, "_reconcile_at", 0.0)) < self.RECONCILE_TICK_S:
            return ls
        self._reconcile_at = now
        return self._write_reconcile(tasks, state, ls, now)

    def _write_reconcile(self, tasks, state, ls, now) -> dict:
        """<id> («Утром сверка с бэклогом: ни одной забытой задачи»): <state>/reconcile.json maps EVERY backlog row
        to where the loop holds it, with a reason and a term: the queue (the task state wins), a triage hold, the
        closed book, a cut parent, a stale or skipped row (seen, with its term), a deferred row, a row whose state
        wording is not recognised, or a row the triage has not reached yet. Ids and the loop's own words only."""
        try:
            try:
                ls = self._supply_invariant(tasks, state, ls, now) or ls
            except Exception as e:                   # W-supply 1: the return of lost rows never stops the report
                self.err("supply invariant", e)
            self._write_reconcile_now(tasks, state, ls, now)
        except Exception as e:                       # the report never stops the loop
            self.err("reconcile", e)
        return ls

    def _dispositions(self, now, strict=False):
        """imp.row_dispositions of the live backlog, kept for 10 minutes per backlog edit (it reads git).
        W-tick fix3: never computed in the calling (main) thread: the pass runs in the background.
        W-tick2 1: strict=True (the state-changing ticks) answers None while there is no answer for the CURRENT backlog
        (first call, backlog edited, failed pass): the tick is skipped and writes nothing. strict=False (the report) gets
        the last known answer or {}. A ValueError (no bounded section 4) is a known empty answer."""
        try:
            mtime = self.cfg.backlog.stat().st_mtime
            cache = getattr(self, "_disp_cache", None)       # (mtime, at, answer, known)
            job = getattr(self, "_disp_job", None)
            if job is not None and job.done.is_set():       # W-tick 3: the finished background pass is booked here, in one step
                self._disp_job = None
                if job.error is None:
                    cache = self._disp_cache = (job.ctx["mtime"], now, job.result, True)
                elif isinstance(job.error, ValueError):
                    cache = self._disp_cache = (job.ctx["mtime"], now, {}, True)
                else:
                    self.err("reconcile: dispositions", job.error)
                    cache = self._disp_cache = (job.ctx["mtime"], now, cache[2] if cache else {}, False)   # W-tick 5: back-off, no thread per tick; the old answer is for the report only
                job = None
            known = bool(cache and cache[0] == mtime and cache[3])
            fresh = bool(cache and cache[0] == mtime and now - cache[1] < 600)     # a pass (even a failed one) is not repeated within its term
            if known and fresh:
                return cache[2]
            if job is None and not fresh:
                from tools import agent_factory_import as imp
                backlog, wt, own = self.cfg.backlog, self.cfg.worktree, bool(self.cfg.self_repo)
                self._disp_job = Prefetch("dispositions", lambda: imp.row_dispositions(backlog, wt, self_repo=own), {"mtime": mtime})
                self._disp_job.thread.start()
            if strict:
                return cache[2] if known else None           # same backlog, term over: the answer stands while it is refreshed
            return cache[2] if cache else {}
        except ValueError:                           # a backlog with no bounded section 4: no dispositions, not an error
            return {}
        except Exception as e:
            self.err("reconcile: dispositions", e)
            return None if strict else {}

    def _write_reconcile_now(self, tasks, state, ls, now) -> None:
        from tools import factory_requeue
        rows = {}
        try:
            from tools import agent_factory_import as imp
            md = Path(self.cfg.backlog).read_bytes().decode("utf-8-sig")
            backlog = [(r["backlog_id"], bool(r.get("open", True))) for r in imp.parse_section4(md)]
        except ValueError:                           # a backlog with no bounded section 4 has no rows: the report is empty, not an error
            backlog = []
        except Exception as e:
            self.err("reconcile: backlog unreadable", e)
            backlog = []
        try:
            ledger = json.loads((self.cfg.state_dir / "requeue_ledger.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            ledger = {}
        order = {s: i for i, s in enumerate(self.RECONCILE_ORDER)}
        # what speaks for a row: the answer of the architect or the slicer's queue beat tasks that were superseded; a PROMOTED code task
        # of the row's LAST generation (..._r<n>) is the row, whatever the older generations ended as
        spoken = {b for b, r in (ls.get("arch_decision") or {}).items() if isinstance(r, dict)} | set(ls.get("to_slice") or {}) | set(ls.get("split") or {}) | set(ls.get("outdated_tests") or {})
        live, last_gen = set(), {}
        for tid, row in state["tasks"].items():
            t = tasks.get(tid)
            b = row.get("backlog_id") or (t.backlog_id if t else "")
            if not b:
                continue
            if not isinstance(row.get("status"), str):       # W-supply 4: a task without a status is skipped, not fatal
                self.err("reconcile: task " + str(tid)[:60], KeyError("status"))
                continue
            if not (row["status"] == "FAILED" and str(row.get("reason") or "").startswith("superseded")):
                live.add(b)
            m = re.search(r"_r(\d+)$", tid)
            if m and (t is None or t.kind == "code") and int(m.group(1)) >= last_gen.get(b, (-1, ""))[0]:
                last_gen[b] = (int(m.group(1)), row["status"])
        promoted = {b for b, (_, st) in last_gen.items() if st == "PROMOTED"}
        def task_row(tid, row):
            t = tasks.get(tid)
            bid = row.get("backlog_id") or (t.backlog_id if t else "")
            if not bid:
                return
            if row["status"] == "FAILED" and str(row.get("reason") or "").startswith("superseded") and (bid in spoken or bid in live):
                return
            if bid in promoted and row["status"] != "PROMOTED":
                return
            old = rows.get(bid)
            if old and order.get(old["state"], 99) <= order.get(row["status"], 99):
                return
            rec = {"state": row["status"], "task_id": tid,
                   "reason": self.rs(row.get("blocked_reason") or row.get("reason") or row["status"].lower(), 200),
                   "until": self._iso(float(row["block_until"])) if type(row.get("block_until")) in (int, float)
                   else None}
            if row["status"] in ("FAILED", "BLOCKED"):
                used = len(ledger.get(tid) or [])
                rec["returns"] = "%d/3" % used
                if t is not None and (t.only_opus or not t.privacy_safe):
                    rec["owner"] = "only_opus/private: делает Opus"
                elif used < 3 and rec["until"] is None:
                    rec["until"] = self._iso(max(now, factory_requeue.last_try(ledger, tid) + self.cfg.requeue_term_s))
            rows[bid] = rec
        for tid, row in sorted(state["tasks"].items()):
            try:
                task_row(tid, row)
            except Exception as e:                   # W-supply 4: one broken row never costs the report of the others
                self.err("reconcile: task " + str(tid)[:60], e)

        def put(bid, state_name, reason, until=None):
            if bid and bid not in rows:
                rows[bid] = {"state": state_name, "reason": self.rs(reason or state_name, 200), "until": until}
        for bid, rec in (ls.get("outdated_tests") or {}).items():    # W-prio 3: the test names what the product no longer has
            if isinstance(rec, dict):
                put(bid, "outdated_test", "устаревший тест %s: нет в продукте %s" % (
                    rec.get("test"), ", ".join(str(n.get("name")) for n in (rec.get("names") or [])[:4])))
        for bid, rec in (ls.get("arch_decision") or {}).items():     # the architect's own answer, in its own word
            if isinstance(rec, dict):
                kind = str(rec.get("decision") or "")
                put(bid, "closed_by_guard" if str(rec.get("why") or "").startswith("guard_green") else
                    kind if kind in ("already_fixed", "not_code") else "hold",
                    "архитектор: %s%s" % (kind, (": " + str(rec.get("why"))) if rec.get("why") else ""))
        for bid, q in (ls.get("holds") or {}).items():
            put(bid, "hold", q)
        for bid in ls.get("closed") or {}:
            put(bid, "closed", "закрыта в книге петли")
        for bid, rec in (ls.get("parents") or {}).items():
            if isinstance(rec, dict):
                put(bid, "parts", "разрезана на %s частей: %s" % (rec.get("parts"), ",".join(str(c) for c in (rec.get("children") or []))))
        for bid, rec in (ls.get("split") or {}).items():
            if isinstance(rec, dict):
                put(bid, "split", "разбита на дочерние дефекты: %s" % ",".join(str(c) for c in (rec.get("children") or [])))
        for bid, rec in (ls.get("not_code") or {}).items():
            if isinstance(rec, dict):
                try:
                    until = self._iso(float(rec.get("until") or now))
                except (TypeError, ValueError):
                    until = None
                put(bid, "not_code", rec.get("reason") or "не код", until)
        for bid, rec in (ls.get("head_scope") or {}).items():
            if isinstance(rec, dict):
                put(bid, "scoped", "область выбрана головной моделью (%s); ждёт триажа" % ", ".join(
                    str(x) for x in (rec.get("touch_files") or [])[:3]))
        for bid, rec in (ls.get("seen") or {}).items():
            if isinstance(rec, dict):
                put(bid, "stale" if rec.get("kind") == "stale" else "seen", rec.get("reason"),
                    self._iso_safe(rec.get("until"), now))
            else:
                put(bid, "stale" if rec == "stale" else "seen", "пропущена триажем (без срока, старая запись)", None)
        for bid, why in (ls.get("deferred") or {}).items():
            put(bid, "deferred", why)
        for bid in ls.get("to_slice") or {}:
            put(bid, "to_slice", "ждёт нарезчика")
        for bid in list(rows):                         # a part "<ID>#k" speaks for its row (row_of)
            if "#" in bid:
                put(F.row_of(bid), rows[bid]["state"], rows[bid].get("reason"), rows[bid].get("until"))
        disp = self._dispositions(now)
        # unknown state wording is an OPEN row (triaged like any other); its words are only reported
        unknown_words = {}
        for bid, st in (ls.get("skipped_unknown") or {}).items():
            word = (st or "?").strip() or "?"
            unknown_words[word] = unknown_words.get(word, 0) + 1
        for bid, is_open in backlog:
            if is_open:
                if bid in disp:
                    put(bid, disp[bid][0], disp[bid][1])
                else:
                    put(bid, "untriaged", "триаж ещё не дошёл до строки")
            else:
                put(bid, "closed_in_backlog", "закрыта в бэклоге")
        counts = {}
        for r in rows.values():
            counts[r["state"]] = counts.get(r["state"], 0) + 1
        body = {"backlog_rows": len(backlog), "counts": dict(sorted(counts.items())), "rows": dict(sorted(rows.items()))}
        if unknown_words:
            body["unknown_words"] = dict(sorted(unknown_words.items()))
        try:                                           # the table of skip reasons over the live backlog (no model)
            from tools import agent_factory_import as imp
            body["skip_reasons"] = imp.skip_reason_table(
                {b: d for b, d in disp.items() if b in rows and rows[b]["state"] == d[0]},
                [b for b, r in rows.items() if r["state"] == "untriaged"])
        except Exception as e:
            self.err("reconcile: skip reasons", e)
        if self._lk_unlinked is not None:
            body["unlinked_requirements"] = self._lk_unlinked
        path = self.cfg.state_dir / "reconcile.json"
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
            old.pop("updated", None)
        except (OSError, ValueError):
            old = None
        if old != body:
            F.save_atomic(path, {"updated": self.ts(), **body})

    def _write_questions(self, tasks, state, ls) -> None:
        lines = ["# Вопросы к Opus (обновлено %s)\n" % self.ts(), "## Задачи BLOCKED / FAILED"]
        for tid, row in state["tasks"].items():
            if row["status"] not in ("BLOCKED", "FAILED"):
                continue
            t = tasks.get(tid)
            bid = row.get("backlog_id") or (t.backlog_id if t else "")
            reason = row.get("blocked_reason") or row.get("reason") or "?"
            fb_all = (F.last_feedback(state, tid) or "").replace("\n", " ")
            fb = fb_all[-400:]  # the tail: the newest remark is what Opus needs
            touch = " ".join(t.touch_files) if t else "<файлы>"
            tests = " ".join(t.tests) if t else "<тесты>"
            head = "- %s [%s] %s: %s" % (tid, bid, row["status"], reason)
            if reason in ("already_green", "no_diff"):
                q = ("тест(ы) %s зелёные на базе %s. Закрыть строку %s или дать тест/область?"
                     % (tests, self.base_sha[:12] or "?", bid))
            elif reason in ("scope_violation", "context_too_large") or "no_changes" in fb_all \
                    or "no change" in fb_all.lower():
                cand = ", ".join(sorted(set((t.touch_files + t.read_files) if t else ())))
                q = "область задачи не подошла. Кандидаты (touch/read): %s. Какие файлы менять?" % cand
                # the refusal itself (live 20.11: six rows read "which files?" while the cause was a size cap of
                # the factory, invisible here; the head cannot answer a cause it is not shown)
                q += " Причина: " + (fb[-200:] or reason)
            else:
                q = "последнее замечание: " + (fb or "нет")
            lines += [head, "  вопрос: " + q,
                      "  ответ: " + self._answer_cmd(bid, tid, touch, tests)]
        for tid, t in tasks.items():
            if t.only_opus or not t.privacy_safe:
                lines.append("- %s [%s] only_opus/private: делает Opus сам" % (tid, t.backlog_id))
        lines.append("\n## Вопросы триажа")
        for b, q in ls["holds"].items():
            lines += ["- %s: %s" % (b, q), "  ответ: " + self._answer_cmd(b)]
        text = self._scrub("\n".join(lines) + "\n")
        old = self.questions.read_text(encoding="utf-8") if self.questions.exists() else ""
        if text.split("\n", 1)[1] != old.split("\n", 1)[-1]:
            self.questions.write_text(text, encoding="utf-8")

    # -- RUN
    def _call_budget(self) -> int:
        """<id>/<id>, no self-imposed brake (live 20.11 02:35: 259 of a hand-set 400 model calls were spent by 02:30; the
        loop would have stood from about 04:00 to midnight while every channel still had quota): the day's call budget
        is the daily capacity of the verified channels whose key is set (the sum of their rpd), never a hand number;
        each channel's own rpd stays its limit. An explicit cfg.max_model_calls wins; an unreadable registry gives
        the old 400."""
        from tools import agent_factory_runner as R
        if self.cfg.max_model_calls:
            return self.cfg.max_model_calls
        env = {**os.environ, **self.extra_env}
        try:
            rows = json.loads(Path(self.cfg.channels).read_text(encoding="utf-8"))["channels"]
            total = sum(int(r.get("rpd") or 0) for r in rows
                        if isinstance(r, dict) and r.get("verified") is not False and env.get(r.get("key_env") or ""))
        except Exception as e:
            self.err("call budget", e)
            return 400
        return max(1, min(R.MAX_MODEL_CALLS, total)) if total else 400

    @staticmethod
    def _peak_for_estimate(w) -> int:
        """fac-58: what a finished worker adds to the admission estimate: the largest working set measured while it lived
        (RAM), else the job peak (Windows commit: 260-415 MB where the working set stood at 90-135 MB)."""
        ws = int(getattr(w, "ws_peak", 0) or 0)
        if ws and int(getattr(w, "ws_n", 0) or 0) >= WS_MIN_SAMPLES:      # a thin series misses the git/pytest bursts: the job peak stands
            return ws
        return int(getattr(w, "peak", 0) or 0) or ws

    def _estimate(self) -> int:
        """What one more worker may need: the <id> of the job peaks of the last EST_KEEP workers (a fixed guess until
        EST_MIN_SAMPLES are measured)."""
        peaks = sorted(self._peaks)
        if len(peaks) < EST_MIN_SAMPLES:
            return EST_DEFAULT_BYTES
        return peaks[min(len(peaks) - 1, int(len(peaks) * 0.9))]

    def _mem_plan(self, live=None) -> tuple:
        """(median, burst, shortfall) in bytes. A live worker is booked at the median of its usual size (the median of the
        measured sizes of the live workers, EST_MEDIAN_DEFAULT without a measure), not at the short peak of a git/pytest
        child; the peaks are not simultaneous, so the whole pool shares ONE burst reserve = max(est_peak, BURST_SHARE x
        live x est_peak). The shortfall is what workers younger than YOUNG_S still lack up to the median."""
        live = list(self.pool.workers.values()) if live is None else live
        seen = []
        for w in live:
            try:
                got = (w.owned.current_bytes() if w.owned is not None else None) or 0
            except Exception:
                got = 0
            seen.append(int(got))
            if got:
                try:
                    w.ws_n = int(getattr(w, "ws_n", 0) or 0) + 1
                    if got > (getattr(w, "ws_peak", 0) or 0):
                        w.ws_peak = int(got)
                except AttributeError:
                    pass
        measured = sorted(s for s in seen if s > 0)
        med = measured[len(measured) // 2] if measured else EST_MEDIAN_DEFAULT
        now = time.monotonic()
        shortfall = sum(max(0, med - s) for w, s in zip(live, seen)
                        if float(getattr(w, "t_start", 0.0) or 0.0) > 0
                        and 0 <= now - float(w.t_start) < YOUNG_S)
        peak = self._estimate()
        burst = int(max(peak, BURST_SHARE * len(live) * max(0, peak - med)))   # med is already booked
        return med, burst, shortfall

    @staticmethod
    def _floor(task) -> int:
        """The free-RAM floor for admitting this task's worker: LIGHT_FLOOR for the light engine (and for an unknown
        task: the per-task check follows), the gate's MIN_FREE_RAM for a task that needs the Kilo engine."""
        if task is None:
            return LIGHT_FLOOR
        files = task.get("touch_files") if isinstance(task, dict) else getattr(task, "touch_files", None)
        if not isinstance(files, (list, tuple)):
            return MIN_FREE_RAM
        return LIGHT_FLOOR if _engine_for("code", SimpleNamespace(touch_files=tuple(files))) == "light" else MIN_FREE_RAM

    def _capacity(self, task, state=None) -> str:
        """'' when one more worker may start now, else the reason. K is nothing but this: free RAM (the floor, plus what
        the live workers have not used yet, plus one more estimate) and free quota (first calls that can still be
        booked beyond those the live workers have not booked). With no live worker only today's rules count. While the cloud
        gate answers (``cloud_fn``) the checks of a candidate run there and hold no slot: RAM is not counted per worker
        (only CLOUD_FLOOR of the machine stays) and the pool takes up to factory_cloud_gate.MAX_LIVE tasks."""
        self._headroom_seen = None
        free = self.free_ram_fn()
        cloud_fn = getattr(self, "cloud_fn", None)
        cloud = _cloud_up(cloud_fn)       # the checks of a candidate run in the cloud: no RAM budget
        floor = CLOUD_FLOOR if cloud_fn is not None else self._floor(task)
        if free < floor:
            return "low_ram"
        live = list(self.pool.workers.values())
        if cloud_fn is not None and not cloud:
            # the cloud does not answer: no check can run (nothing runs on the laptop in its place). The cards wait; one
            # trial card per CLOUD_TRIAL_S goes through to ask the cloud again (triage, slicer and links go on meanwhile).
            now = self.clock()
            if live or now - float(getattr(self, "_cloud_trial_at", 0.0) or 0.0) < CLOUD_TRIAL_S:
                self._cloud_was_down = True
                return "cloud_down"
            self._cloud_trial_at = now
            self._cloud_was_down = True
            return ""
        if cloud_fn is not None and getattr(self, "_cloud_was_down", False):
            self._cloud_was_down = False
            self._wake_cloud_defers()         # the first answer of the cloud: every card waiting for it starts now
        if not live:
            return ""
        if cloud and len(live) >= getattr(factory_cloud_gate, "MAX_LIVE", 30):     # (no gate module in the mirror: the same 30 as at the ceiling)
            return "cloud_cap"
        if self._ending() or self._brake_due is not None:
            return "ending"                      # STOP, the deadline or a due brake: the pool only drains
        if self.cfg.once:
            return "once"                        # --once is one pass
        try:
            if (self.ls().get("brake") or {}).get("half_open"):
                return "brake_trial"             # the half-open brake lets ONE trial pass through
        except Exception as e:
            self.err("capacity brake", e)
        # memory by the measure, with the cloud or without it: the <id> of the peaks of the last workers (``_estimate``)
        med, burst, pending = self._mem_plan(live)
        if free - pending - _reserved_bytes() < floor + med + burst:
            return "low_ram"
        if task is not None and Loop._has_code(task) and self._edit_dry():
            return ""                            # W-dry 1: a card with the code of all its parts needs no edit channel: no headroom
        try:
            if not isinstance(state, dict):
                state = self.load()[1]           # (W-tick 4: _fill hands the state it already read)
            unbooked = sum(1 for w in live if not (state["tasks"].get(w.tid, {}).get("began") or {}).get("booked"))
            try:
                gate = self._head_gate(task, state)
            except (OSError, ValueError, KeyError, TypeError) as e:   # the head's state is unreadable: no head verdict, the ledger's count decides
                self.err("capacity head gate", e)
                gate = None
            if gate is None:
                self._headroom_seen = self._headroom(task, state)
            else:                                # fac-68: the number is only the report's (stats.json headroom)
                try:
                    self._headroom_seen = self._headroom(task, state)
                except Exception:
                    self._headroom_seen = None
                return gate
        except (OSError, ValueError, KeyError, TypeError):
            return "quota"                       # the quota is unknown: no second worker
        except Exception as e:
            self.err("capacity", e)
            return "quota"
        return "quota" if self._headroom_seen <= unbooked else ""

    def _head_gate(self, task, state):
        """fac-68: None without a live head (the ledger's count decides, as before). With one the head is the only pacer of
        Google calls and a ticket waiting in its queue is no harm: '' (memory and cloud already passed) unless NO channel of
        the route can take a ticket today (all closed by the day / no keys): then 'quota', the card would wait for the reset."""
        path = Path(self.cfg.channels)
        from tools import factory_head as HD
        if not HD.alive(path.resolve().parent / HD.STATE_NAME):
            return None
        configured = CH.validate(json.loads(path.read_text(encoding="utf-8"))["channels"])
        tokens = int(getattr(task, "estimated_tokens", 0) or 0)
        role = "edit" if getattr(task, "contract", "") else "code"
        order = CH.route_order(configured, role, 1, tokens) or CH.route_order(configured, role, 1, 0)
        order = [c for c in order if not CH.is_reserve(c)] or order
        env = {**os.environ, **self.extra_env}
        quota = state.get("channel_quotas") if isinstance(state.get("channel_quotas"), dict) else {}
        seen = quota_ledger.view(quota, quota_ledger.others(path.resolve().parent / "quota", str(self.ckpt)), now=self.clock())
        return "" if CH.route_open_today(order, seen, env, now=self.clock()) else "quota"

    def _headroom(self, task, state) -> int:
        """First model calls that could be booked now on the code route (0 when the quota is unknown)."""
        path = Path(self.cfg.channels)
        configured = json.loads(path.read_text(encoding="utf-8"))["channels"]
        configured = CH.validate(configured)
        tokens = int(getattr(task, "estimated_tokens", 0) or 0)
        role = "edit" if getattr(task, "contract", "") else "code"     # the cards of a contract are edit calls
        order = CH.route_order(configured, role, 1, tokens) or CH.route_order(configured, role, 1, 0)
        order = [c for c in order if not CH.is_reserve(c)] or order    # W-gemma 4: spare channels of others hold no pool
        env = {**os.environ, **self.extra_env}
        from tools import factory_head as HD
        head_state = path.resolve().parent / HD.STATE_NAME
        if HD.alive(head_state):
            # W-bucket: a live head decides for every channel it serves: the pool's "quota" refusal follows the head's real
            # free places (tokens of its buckets free within 30 s minus the queued tokens), not the ledger's cooling marks
            served = [c for c in order if HD.serves(c)]     # the route's channels (its size rule), never the spares
            try:
                head_free = HD.capacity(head_state, [c["id"] for c in served], tokens=tokens or None, role=role)
            except HD.HeadDown as error:
                head_free = 0 if error.alive else None
            if head_free is not None:
                order = [c for c in order if not HD.serves(c)]
                if not order:
                    return head_free
        else:
            head_free = None
        quota = state.get("channel_quotas") if isinstance(state.get("channel_quotas"), dict) else {}
        seen = quota_ledger.view(quota, quota_ledger.others(path.resolve().parent / "quota", str(self.ckpt)))
        if head_free is not None:      # the channels the head does not serve keep the ledger's count
            live = CH.usable(order, seen, env)
            return head_free + (CH.headroom(order, seen, min(tokens, max(c["tpm"] for c in live)), env) if live else 0)
        # W-gemma 4: every main channel closed by the day's mark but Gemma open: the pool counts Gemma (2 calls a channel)
        gemma = CH.big_headroom(configured, seen, env)
        live = CH.usable(order, seen, env)
        if not live:
            return gemma
        return max(gemma, CH.headroom(order, seen, min(tokens, max(c["tpm"] for c in live)), env))

    def _snapshot(self, head: str) -> Path:
        """The tree a worker reads: a versioned copy of the mirror (hard links), never swapped under it."""
        target = self.snap_dir / head[:12]
        if target.is_dir():
            return target
        self.snap_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.snap_dir / (head[:12] + ".new")
        shutil.rmtree(tmp, ignore_errors=True)

        def link(src, dst):
            try:
                os.link(src, dst)
            except OSError:
                shutil.copy2(src, dst)
        shutil.copytree(self.mirror, tmp, copy_function=link)
        try:        # the last finished neighbour map rides in the snapshot: the worker reads it, it never builds the graph
            from tools.agent_factory_runner import NEIGHBORS_FILE
            shutil.copyfile(Path(self.cfg.state_dir) / "neighbors" / "latest.json", tmp / NEIGHBORS_FILE)
        except OSError:
            pass
        os.replace(tmp, target)
        return target

    def _prune_snapshots(self) -> None:
        """Every snapshot but the newest and those a live worker reads goes (one that cannot be deleted waits)."""
        try:
            keep = {r.resolve() for r in self.pool.roots()}
            keep.update(Path(j.ctx["root"]).resolve() for j in self._slicers.values())
            keep.update(Path(j.ctx["root"]).resolve() for j in list(self._hypers.values()))     # W-hypo3 5: the base of a live search stays
            dropped = [j for j in self.__dict__.get("_hypo_dropped", ()) if getattr(j, "thread", None) is not None and j.thread.is_alive()]
            self._hypo_dropped = dropped        # fac-choke: a dropped solve still ending its step keeps its tree until its thread is gone
            keep.update(Path(j.ctx["root"]).resolve() for j in dropped)
            if self.base_sha:
                keep.add((self.snap_dir / self.base_sha[:12]).resolve())
            if self._rel_snap:                          # the final build reads its snapshot for as long as it sweeps
                keep.add(Path(self._rel_snap).resolve())
            for d in self.snap_dir.iterdir() if self.snap_dir.is_dir() else ():
                if d.resolve() in keep:
                    continue
                if not d.name.endswith(".dead"):
                    dead = d.with_name(d.name + ".dead")    # out of the way FIRST: a half-deleted tree is never reused
                    shutil.rmtree(dead, ignore_errors=True)
                    try:
                        os.replace(d, dead)
                    except OSError:
                        continue                            # held by a scanner: it waits for the next prune
                    d = dead
                shutil.rmtree(d, ignore_errors=True)
        except OSError as e:
            self.err("snapshots", e)

    def _unclaim(self, tid: str, token: str) -> None:
        """The pass never began (its process died or never started): READY again, the attempt back (fenced)."""
        try:
            def back(state):
                row = state["tasks"].get(tid)
                if row and row.get("status") == "RUNNING" and row.get("lease") == token and "began" not in row:
                    F.unclaim(state, tid, token)
            self._tx(back)
        except F.LockBusy:
            raise                                  # the claim is still ours: the caller retries (a row held for a lease)
        except (F.InvalidPlan, OSError) as e:
            self.err("unclaim " + tid, e)

    def _wake_cloud_defers(self) -> None:
        """The cloud answered again: every task postponed for ``cloud_down`` / ``cloud_busy`` may start now."""
        def wake(state):
            now = time.time()
            for row in state["tasks"].values():
                if (isinstance(row, dict) and row.get("status") == "READY"
                        and row.get("defer_reason") in ("cloud_down", "cloud_busy")
                        and float(row.get("not_before") or 0) > now):
                    row["not_before"] = now
        try:
            self._tx(wake)
        except Exception as e:      # noqa: BLE001  the defers expire by themselves in a minute
            self.err("wake cloud defers", e)

    def _note_gate(self, res: dict) -> None:
        """The seconds of the gate of a finished pass by where they ran (``gate_secs``: cloud / local_fast / local). One
        ``gate`` event per place; when the local share of the last hour is above FAST_LOCAL_SHARE the next workers get
        ``--fast-local-s 0`` (every test to the cloud) for an hour (``gate status=fast_local_off``)."""
        if isinstance(res, dict) and res.get("cloud_stage"):       # why the cloud gave no verdict, written before a later answer forgets it
            self.event("gate", status="cloud_down", stage=self.rs(res.get("cloud_stage"), 40),
                       error_type=self.rs(res.get("cloud_error_type"), 80), error=self.rs(res.get("cloud_error"), 200))
        secs = res.get("gate_secs") if isinstance(res, dict) else None
        if not isinstance(secs, dict):
            return
        now = self.clock()
        log = [e for e in (getattr(self, "_gate_log", None) or []) if now - e[0] <= 3600]
        for where in ("cloud", "local_fast", "local"):
            value = secs.get(where)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
                log.append((now, where, float(value)))
                self.event("gate", status="where", where=where, secs=round(float(value), 3))
        self._gate_log = log
        total = sum(e[2] for e in log)
        local = sum(e[2] for e in log if e[1] != "cloud")
        if total > 0 and local / total > FAST_LOCAL_SHARE and now >= getattr(self, "_fast_local_off_until", 0.0):
            self._fast_local_off_until = now + FAST_LOCAL_HOLD_S
            self.event("gate", status="fast_local_off", reason="local share %.0f%% of %.0f s" % (100 * local / total, total))

    def _admit(self, tid: str, tasks, ls):
        """Claim ``tid`` in one transaction and start its runner. 1 = started, 0 = not runnable any more, an Outcome =
        the iteration ends here (a locked state is WAIT state_locked; an exhausted budget is today's WAITING_CHANNEL)."""
        cfg = self.cfg
        small, large, review = cfg.small_model, cfg.large_model, cfg.review_model    # fac-43: the router picks the coder per call
        t_claim = time.monotonic()
        budget = self._call_budget()
        base = self.base_sha
        try:
            for attempt in range(self.CLAIM_RETRIES):         # W-feed2 4g: a busy lock is retried, not the end of the step
                try:
                    with self.txn(self.CLAIM_WAIT_S) as (tasks2, state):
                        state["max_model_calls"] = budget     # the day's capacity: the loop claims, so the loop writes it
                        token = F.acquire(tasks2, state, tid, now=self.clock(), charge=False)
                    self._claimed_state = state
                    break
                except F.LockBusy:
                    if attempt + 1 >= self.CLAIM_RETRIES:
                        raise
                    self.sleep_fn(self.CLAIM_PAUSE_S)
        except F.BudgetExhausted:
            res = {"status": "WAITING_CHANNEL", "reason": "budget_exhausted", "task_id": tid, "task": tid, "calls": [],
                   "stages": {}, "events": [], "infra": False, "wait_s": round(F.seconds_to_local_midnight(), 1)}
            return self._account(Worker(slot=-1, tid=tid, token=None, base_sha=base, hint=tid), res=res)
        except F.LockBusy:
            return Outcome(sleep=STATE_LOCKED_SLEEP_S, action="WAIT", reason="state_locked")
        except F.InvalidPlan:                                 # no longer runnable (another writer): choose again
            return 0
        try:
            root = self._snapshot(base)
            fresh = self.ls()
            fresh["bases"][tid] = base                        # the worker's base, recorded at the claim
            self.save_ls(fresh)
            cmd = self.runner_cmd + [
                "--root", str(root), "--plan", str(self.plan_path),
                "--checkpoint", str(self.ckpt), "--staging", str(self.stage),
                "--small-model", small, "--large-model", large,
                "--review-model", review, "--channels", str(cfg.channels),
                "--task", tid, "--lease", token, "--max-attempts", str(cfg.max_attempts),
                "--reslice-after", str(F.RESLICE_AFTER),
                "--max-model-calls", str(budget), "--base-sha", base,
                "--port-repo", str(cfg.repo),    # the runner's --root is a plain copy: a port task's old commit lives here
                "--execute", "--ack-host-access-risk"]
            if cfg.self_repo:
                cmd += ["--self-repo"]                        # 8.1: the gate of the second instance is the cloud only
            if self.clock() < getattr(self, "_fast_local_off_until", 0.0):
                cmd += ["--fast-local-s", "0"]                # local runs took too much: every test goes to the cloud
            slot = self.pool.free_slot()
            self.workers_dir.mkdir(parents=True, exist_ok=True)
            out_p, err_p = self.workers_dir / ("%d.out" % slot), self.workers_dir / ("%d.err" % slot)
            fho, fhe = out_p.open("wb"), err_p.open("wb")     # truncated: a result is never the previous worker's
            free = self.free_ram_fn()
            try:
                owned = factory_process.start_owned(cmd, cwd=str(_ROOT), env={**os.environ, **self.extra_env},
                                                    stdout=fho, stderr=fhe)
            except BaseException:
                fho.close()
                fhe.close()
                raise
        except BaseException:
            self._unclaim(tid, token)                         # a spawn failure leaves no claim (as before)
            raise
        w = self.pool.start(Worker(slot=slot, tid=tid, token=token, base_sha=base, root=root, owned=owned, out=out_p,
                                   err=err_p, fhs=(fho, fhe), t_claim=t_claim, t_start=time.monotonic(),
                                   k=len(self.pool.workers) + 1, free_ram=free, hint=tid))
        self._max_k = max(self._max_k, len(self.pool.workers))
        self._k_sum, self._k_n = self._k_sum + w.k, self._k_n + 1
        return 1

    def _reap(self, w: Worker, timed_out: bool) -> dict:
        """The worker's result. Its job closes (the whole tree dies); on a timeout the pass is NO_RESULT."""
        rc = None
        if w.owned is not None:
            try:
                now_ws = int(w.owned.current_bytes() or 0)       # the last sample before the job closes
            except Exception:  # noqa: BLE001 - an aid
                now_ws = 0
            if now_ws:
                w.ws_n = int(getattr(w, "ws_n", 0) or 0) + 1
            w.ws_peak = max(int(getattr(w, "ws_peak", 0) or 0), now_ws)
            w.peak = w.owned.peak_bytes()
            if timed_out:
                w.owned.kill()
            else:
                w.owned.close()
            rc = w.owned.proc.returncode
            for fh in w.fhs:
                try:
                    fh.close()
                except OSError:
                    pass
        self.pool.remove(w)
        est_peak = self._peak_for_estimate(w)
        if est_peak:
            self._peaks = (self._peaks + [est_peak])[-EST_KEEP:]
        if timed_out:
            return {"status": "NO_RESULT", "error": "runner timeout"}

        def read(path):
            try:
                return path.read_bytes() if path else b""
            except OSError:
                return b""
        proc = argparse.Namespace(stdout=read(w.out), stderr=read(w.err), returncode=rc)
        return self._parse(proc)

    def _release_claim(self, w: Worker) -> None:
        if w.token:
            self._unclaim(w.tid, w.token)

    def _brake_or_wait(self, streak: int, out: Outcome) -> Outcome:
        """The brake waits for the live workers (one of them may prove the pipeline works); alone, it brakes now."""
        if self.pool.workers:
            self._brake_due = streak
            return out
        return self._brake(streak, out)

    def _account(self, w: Worker, timed_out: bool = False, res: dict | None = None) -> Outcome:
        """Everything the loop does with one finished pass (what ``_run`` did after the runner returned)."""
        cfg = self.cfg
        if res is None:
            res = w.res if w.res is not None else self._reap(w, timed_out)
        w.res = res
        try:
            self._release_claim(w)
            tasks, state = self.load()
        except F.LockBusy:
            if w.slot >= 0 and w.slot not in self.pool.workers:
                self.pool.start(w)             # the result is kept: the next look accounts it (nothing is lost)
            raise
        w.res = None
        self.pool.remove(w)                    # (a parked worker leaves now)
        self._prune_snapshots()
        base = w.base_sha
        ls = self.ls()
        dur = res.get("dur_s") if isinstance(res.get("dur_s"), (int, float)) else round(
            time.monotonic() - (w.t_start or time.monotonic()), 3)
        st = res.get("status")
        tid = res.get("task_id") or res.get("task") or ""
        calls = [c for c in (res.get("calls") or []) if isinstance(c, dict)]
        tin = self._sum_known(calls, "input_tokens", "input")
        tout = self._sum_known(calls, "output_tokens", "output")
        model = next((c.get("model") for c in calls if c.get("model")), None)
        reason = res.get("reason") or res.get("blocked_reason") or res.get("error")
        bid = self._bid(state, tasks, tid)
        self._note_gate(res)
        self.event("run", task_id=tid or None, backlog_id=bid, dur_s=dur, status=st,
                   model=self.rs(model), base_sha=base, calls=len(calls) or None,
                   reason=F.redact(str(reason))[:200] if reason else None,
                   attempt=res.get("attempt"), kind=self.rs(res.get("kind")),
                   wait_s=res.get("wait_s"),
                   changed=res.get("changed"), receipt_sha256=res.get("receipt_sha256"),
                   model_note=self.rs(res.get("model_note"), 300),
                   events=self._events(res.get("events")) or None,
                   reason_detail=self.rs(res.get("reason_detail"), 300),
                   error_class=self._failure_class(reason, res),
                   error_type=self.rs(res.get("error_type") or res.get("cloud_error_type")),
                   cloud_stage=self.rs(res.get("cloud_stage"), 40),
                   channel_reason=self.rs(res.get("channel_reason")),
                   edit_by=self.rs(res.get("edit_by"), 12),
                   vgs={k: v for k, v in res["vgs"].items() if type(v) is int} if isinstance(res.get("vgs"), dict) else None,
                   context_chars=res.get("context_chars") if isinstance(res.get("context_chars"), int) else None,
                   context_sections=[self.rs(x, 40) for x in res["context_sections"][:12]]
                   if isinstance(res.get("context_sections"), list) and res.get("context_sections") else None,
                   worker=w.slot, pid=getattr(w.owned, "pid", None), lease=(w.token or "")[:8] or None, k=w.k,
                   free_ram_mb=int(w.free_ram / 2 ** 20) or None,
                   peak_mb=round(w.peak / 2 ** 20, 1) if w.peak else None,
                   ws_peak_mb=round(w.ws_peak / 2 ** 20, 1) if getattr(w, "ws_peak", 0) else None,
                   self_peak_mb=res.get("self_peak_mb") if isinstance(res.get("self_peak_mb"), (int, float)) else None,
                   queue_s=round(w.t_start - w.t_claim, 3) if w.t_start else None,
                   slot_wait_s=(res.get("stages") or {}).get("slot_wait_s"))
        self._box_returned(bid, res, ls, self.clock())
        if tid and res.get("scope_add"):
            self._scope_add(tid, tasks, res["scope_add"], state)
        for c in calls:  # one event per model call: run (code/repair) or review
            self.event("review" if c.get("role") == "review" else "run",
                       task_id=tid or None, backlog_id=bid, role=self.rs(c.get("role")),
                       attempt=c.get("attempt"), channel=self.rs(c.get("channel")),
                       model=self.rs(c.get("model")),
                       reserved_tokens=self._num(c, "reserved_tokens", "reserved"),
                       actual_tokens=self._num(c, "actual_tokens", "actual"),
                       tokens_in=self._num(c, "input_tokens", "input"),
                       tokens_out=self._num(c, "output_tokens", "output"),
                       tokens_reasoning=self._num(c, "reasoning_tokens", "reasoning"),
                       tokens_cache_read=self._num(c, "cache_read_tokens", "cache_read"),
                       tokens_cache_write=self._num(c, "cache_write_tokens", "cache_write"),
                       http_status=self._num(c, "http_status"), dur_s=c.get("dur_s"),
                       tool_events=c.get("tool_events"), steps=self._num(c, "steps"),
                       finish_reason=self.rs(c.get("finish_reason")),
                       files_read=[self.rs(str(x)) for x in (c.get("files_read") or [])[:10]] or None,
                       error_class=self.rs(c.get("error_class")), status="error" if c.get(
                           "error_class") else "ok", base_sha=base,
                       # the channel cooled after this call: why and for how long (factory_channels.note_outcome)
                       cool_reason=self.rs(c.get("cool_reason")), cool_s=self._num(c, "cool_s"),
                       # fac-farm 1: which quota refused (quotaId) and its dimension (unit/window); counts by kind are in slice vgs
                       quota_id=self.rs(c.get("quota_id"), 120), dim=self.rs(c.get("quota_dim"), 24))
        for name, secs in (res.get("stages") or {}).items():
            span = "gate" if str(name).startswith(("gate", "red_before", "neighbors")) else (
                "review" if str(name).startswith("review") else "run")
            rev = span == "review" and name == "review_s"        # W-review 3: the verdict and the voices of the critics
            votes = [v for v in (res.get("review_votes") or []) if isinstance(v, dict)] if rev else []
            self.event(span, task_id=tid or None, backlog_id=bid, stage=str(name), dur_s=secs,
                       status="ok", base_sha=base,
                       verdict=self.rs(res.get("review_verdict")) if rev else None,
                       n_votes=len(votes) if rev else None,
                       models=[self.rs(v.get("model")) for v in votes] or None,
                       votes=[bool(v.get("ok")) for v in votes] or None)
        if res.get("cross_review") is not None:
            self.event("review", task_id=tid or None, status="approved" if res["cross_review"]
                       else "rejected", model=self.rs(model), base_sha=base)
        paid = res.get("paid_critic")          # owner rule 4: the paid control critic (never the key)
        if isinstance(paid, dict):
            self.event("paid_critic", task_id=tid or None, backlog_id=bid, status="ok", verdict=self.rs(paid.get("verdict")),
                       model=self.rs(paid.get("model")), usd=paid.get("usd"), tokens_in=self._num(paid, "tokens_in"),
                       tokens_out=self._num(paid, "tokens_out"), error_class=self.rs(paid.get("class")) or None,
                       base_sha=base)
        from tools import factory_classes as K_
        try:        # owner rule 3: the registry counts the failure by class; a pass says the lesson shown before it helped
            if reason:
                K_.record_failure(tid, getattr(tasks.get(tid), "touch_files", ()), str(reason), str(res.get("reason_detail") or ""))
            elif tid:
                K_.record_pass(tid)
        except Exception as e:
            self.err("class registry", e)
        tot = ls["totals"]
        tot["tokens_in"] = tot.get("tokens_in", 0) + (tin or 0)     # unknown usage adds nothing, it is not a zero
        tot["tokens_out"] = tot.get("tokens_out", 0) + (tout or 0)
        tot["seconds"] = round(tot.get("seconds", 0) + (dur or 0), 3)
        if tid:
            ls["bases"][tid] = base
        if str(reason or "").startswith(REJECT_PREFIXES):
            tot["rejected"] = tot.get("rejected", 0) + 1
        wait_s = res.get("wait_s")
        rkey, ckey = str(res.get("reason") or ""), str(res.get("channel_reason") or "")
        channel_wide = st == "WAITING_CHANNEL" or rkey in CHANNEL_REASONS or ckey in CHANNEL_REASONS
        if st == "WAITING_CHANNEL":
            wait_s = wait_s or 75
        if channel_wide and isinstance(wait_s, (int, float)) and wait_s > 0:
            named = next((str(c.get("channel")) for c in (res.get("calls") or []) if isinstance(c, dict)
                          and c.get("channel")), "") or str(res.get("channel") or "")
            if named:                   # its own channel only; the global wait is for a fault no channel owns
                self._tx(lambda st, n=named, s=float(wait_s): CH.cool_channel(
                    st.setdefault("channel_quotas", {}), {"id": n}, now=self.clock(), seconds=s))
            else:
                ls["channel_until"] = max(float(ls.get("channel_until", 0)),
                                          self.clock() + min(float(wait_s), GLOBAL_WAIT_MAX_S))
        self.save_ls(ls)
        out = Outcome(action="RUN", reason=str(reason or st), status=str(st))
        # Infra = no result / timeout of the process, the runner's own honest flag (dead channel,
        # Kilo launcher, OSError of the pass) or a dead channel named in the reason. gate_unknown,
        # reviewer_failed, provider_error are properties of the task or model: not infra.
        no_result = st == "NO_RESULT"
        temp = self._temporary(rkey, ckey, res, no_result) if st != "REVIEW" else ""
        if temp:                                        # a temporary fault: its own pause, no brake series
            self._learn_from_run(tid, tasks, rkey, res)
            return self._defer_temporary(temp, res, calls, tid, ls, out, wait_s)
        infra = no_result or res.get("infra") is True or rkey in DEAD_CHANNEL or ckey in DEAD_CHANNEL
        key = tid or w.hint
        counters = ls.setdefault("no_result", {})
        if infra:
            if no_result and key:
                rec = counters.setdefault(key, {"n": 0, "epoch": ls.get("proof_epoch", 0)})
                if isinstance(rec, int):  # an old counter format
                    rec = counters[key] = {"n": rec, "epoch": ls.get("proof_epoch", 0)}
                rec["n"] += 1
                # parked only when ANOTHER task proved the pipeline alive between its failures:
                # otherwise it is the environment (dead runner) and the failures go to the series
                if rec["n"] >= self.NO_RESULT_PARK and ls.get("proof_epoch", 0) > rec["epoch"]:
                    counters.pop(key, None)
                    self._park(key, "runner_no_result", "the runner gave no result %d times in a row"
                               % self.NO_RESULT_PARK)
                    self.save_ls(ls)
                    out.status, out.reason = "blocked", "runner_no_result"
                    return out                     # neutral: neither a failure nor a proof
            self.save_ls(ls)
            # one incident counts once: a pass that started BEFORE the previous infrastructure result was accounted
            # failed from the same blip (a flapping proxy fails every live pass at once), so it adds nothing
            counted = (w.t_start or 0.0) >= self._infra_mono
            self._infra_mono = time.monotonic()
            streak = self.note_infra() if counted else int(self.load()[1].get("infra_streak", 0))
            out.sleep, out.status = 60, "infra"
            self.event("infra", task_id=tid or None, status="run_failed", infra_streak=streak,
                       reason=F.redact(str(reason or st))[:200], same_incident=None if counted else True)
            if counted:
                # 21.11: the failure is the channel's, not the factory's: that channel cools, the others work on.
                # A dead runner (no result) owns no channel and charges the whole path.
                names = [] if no_result else list(dict.fromkeys(
                    [str(c["channel"]) for c in calls if c.get("channel")]
                    + ([str(res["channel"])] if res.get("channel") else [])))
                self._series_charge(names, self.clock())
                if streak >= cfg.max_infra:
                    if self._series_all_failed():
                        return self._brake_or_wait(streak, out)
                    out.sleep = 5                           # other channels are free: no brake, no 60 s pause
        else:
            self._learn_from_run(tid, tasks, rkey, res)
            out.proof = self._is_proof(res, calls, st, rkey)
            if out.proof:
                ls["proof_epoch"] = ls.get("proof_epoch", 0) + 1
                counters.pop(key, None)
                ls["no_proof"] = {}                       # proof of work empties the spread
                ls["backoff"] = {}                        # and the pauses of temporary faults
                self.save_ls(ls)
            elif key and self._ran_model_or_gate(res, calls, st, rkey) and not self._judged_by_gate(rkey, res, calls):
                # A run that reached the model or the gates and proved nothing. The set of DIFFERENT
                # tasks failing like that since the last proof is the second brake counter: one task
                # with an eternal error does not grow it, a dying Kilo or broken gates do.
                label = self._scrub(rkey or str(res.get("blocked_reason") or st))[:80]
                ls.setdefault("no_proof", {})[key] = label
                self.save_ls(ls)
                return self._spread_brake(ls, out)
            if st == "IDLE":
                out.sleep = 60  # runner sees nothing to take although the checkpoint has READY
        return out

    # -- memory of typical errors: the same signature twice = "do not repeat" in the brief + a higher channel tier
    def _mem_path(self) -> Path:
        return self.dir / "error_memory.json"

    @staticmethod
    def _failure_class(reason, res: dict):
        """<id> clause 1: the class of a refusal, recorded on the loop's RUN event (None for a pass without a reason)."""
        if not reason:
            return None
        from tools import factory_classes as K
        try:
            return K.classify(str(reason), str(res.get("reason_detail") or ""))
        except Exception:
            return "unknown"

    @staticmethod
    def _reason_class(rkey: str) -> str:
        """The class of a rejection key WITHOUT its free text. In the runner a key is 'gate:no_changes' (a fixed
        word) or 'review: <the reviewer's remarks>' / 'gate: <why>' / 'weakening: <text>' (free text that may be
        private): a fixed word stays, any other text becomes a short hash, so a repeat still matches and no
        remark reaches the brief, error_memory.json or the telemetry (<id> critic, criterion 1)."""
        head, _, rest = rkey.partition(":")
        rest = rest.strip()
        if not rest or re.fullmatch(r"[a-z_]{1,40}", rest):
            return head + (":" + rest if rest else "")
        return head + ":#" + hashlib.sha256(rest.encode("utf-8", "replace")).hexdigest()[:10]

    def _signature(self, rkey: str, remark: str):
        """(signature, words): the reason class plus the first normalised words of the critic's remark. The
        remark goes through the public screen: a private text never reaches the memory (words stay empty)."""
        from tools import agent_factory_import as imp
        words = ""
        if remark:
            clean, classes = imp.screen(remark, 0)
            if clean is not None and not classes and not self._privacy_hit(remark):
                text = re.sub(r"\d+", "N", clean.lower())
                words = " ".join(re.findall(r"[a-zа-яё_]{2,}", text)[:6])
        return (self._reason_class(rkey) + "|" + words), words

    def _audit_factory_test(self, tid: str, res: dict) -> None:
        """<id>: when two or more models of one pass were red on the same test of the row's promoted factory test task,
        that test goes back to its task at once (factory_requeue.audit_after_pass); a fault never stops the loop."""
        from tools import factory_requeue
        try:
            tasks, state = self.load()
            test = factory_requeue.audit_after_pass(
                self.cfg.state_dir, state, tid, res, _ROOT.name,
                lambda t: tasks[t].tests if t in tasks else (), check=self._check_note)
            if test:
                self.event("audit", task_id=tid, status="test_sent_back", reason=test)
        except Exception as e:
            self.err("audit after pass", e)

    CLASS_CASES = 3

    def _public_case(self, text: str, width: int = 240):
        """A failure case that may go to a free model (the coder's class note, the self-fix head's question): the
        privacy check and the public screen pass it, cut to ``width``; else None."""
        from tools import agent_factory_import as imp
        if self._privacy_hit(text):
            return None
        ok, bad = imp.screen(text, 0)
        return ok[:width] if ok is not None and not bad else None

    def _class_note(self, tid: str, tasks, rkey: str, res: dict) -> None:
        """<id> clause 3: a refusal of a known, non-infrastructure class gives the task's next coder one line (a repeat
        line, so fresh_feedback shows it until a newer attempt and rejected_for keeps it from the critic): the class,
        its known remedy and the newest cases of the same class from other tasks. A case comes only from a task of
        this plan known as public (privacy_safe, not only_opus: a missing flag is private, agent_factory.Task), and
        it passes the public screen and the privacy check; no case, no line; the same line is not written twice for
        one attempt."""
        from tools import factory_classes as K
        try:
            cls = K.classify(rkey, str(res.get("reason_detail") or ""))
            if cls == "unknown" or cls in K.INFRASTRUCTURE_CLASSES:
                return

            def clean(text):
                return self._public_case(text, 240)
            public = {k for k, t in (tasks or {}).items()
                      if getattr(t, "privacy_safe", False) is True and not getattr(t, "only_opus", True)}
            rows = list(collections.deque((r for r in self._telemetry_rows() if r.get("span") == "run" and r.get("attempt")
                                           and r.get("reason") and r.get("task_id") in public), maxlen=3000))   # the newest 3000: bounded by count
            mine = getattr(tasks.get(tid), "touch_files", ()) if tasks else ()

            def files_of(t):
                return getattr(tasks.get(t), "touch_files", ())
            examples = K.cases(rows, cls, exclude_task=tid, k=K.LESSON_CASES, clean=clean, files_of=files_of, mine=mine)
            if not examples:
                return
            lesson = K.lesson(cls, tid, mine, examples=examples)     # '' while the lesson is a weak hypothesis
            if not lesson:
                return
            note = F.redact(F.REPEAT_MARK + " " + lesson)[:F.FEEDBACK_MAX_CHARS]

            def add(st):
                row = st["tasks"].get(tid)
                if row is None:
                    return
                items = [x for x in row.get("feedback") or [] if isinstance(x, dict)]
                last = max((i for i, x in enumerate(items) if x.get("source") in ("gate", "review")
                            and not str(x.get("text") or "").startswith(F.REPEAT_MARK)), default=-1)
                if any(str(x.get("text") or "") == note for x in items[last + 1:]):
                    return
                F.add_feedback(st, tid, "gate", note)
            self._tx(add)
        except Exception as e:                           # an aid: it must never stop the loop
            self.err("class note", e)

    def _learn_from_run(self, tid: str, tasks, rkey: str, res: dict) -> None:
        """A rejection (gate:*, weakening:*, review:*) is remembered per task and per file; the second time the
        same signature comes back the next brief says so and the task's channel tier goes one step up."""
        if tid and rkey:
            self._class_note(tid, tasks, rkey, res)
        if not tid or not rkey.startswith(REJECT_PREFIXES) or rkey == "gate:no_changes":
            return
        if rkey.startswith("gate:") and res.get("gate_red"):
            self._audit_factory_test(tid, res)
        try:
            tasks2, state = self.load()
            remark = next((str(x.get("text") or "") for x in reversed(state["tasks"].get(tid, {}).get("feedback") or [])
                           if x.get("source") in ("gate", "review") and not str(x.get("text") or "").startswith(
                               (F.REPEAT_MARK, "[infra]"))), "")
            sig, words = self._signature(rkey, remark)
            mem = {}
            try:
                mem = json.loads(self._mem_path().read_text(encoding="utf-8"))
            except FileNotFoundError:
                pass
            except (OSError, ValueError) as e:
                self.err("error memory unreadable, starting empty", e)
            if not isinstance(mem, dict):
                mem = {}
            per_task, per_file = mem.setdefault("tasks", {}), mem.setdefault("files", {})
            if not isinstance(per_task, dict) or not isinstance(per_file, dict):
                per_task, per_file = mem["tasks"], mem["files"] = {}, {}
            seen = per_task.setdefault(tid, [])
            repeat = sig in seen
            if not repeat:
                seen.append(sig)
                del seen[:-5]
            task = tasks2.get(tid)
            for f in (task.touch_files if task else ())[:10]:
                bucket = per_file.setdefault(f, {})
                bucket[sig] = bucket.get(sig, 0) + 1
                while len(bucket) > 5:
                    bucket.pop(next(iter(bucket)))
            for table in (per_task, per_file):          # rotation: the oldest entries go first
                while len(table) > ERROR_MEMORY_MAX:
                    table.pop(next(iter(table)))
            F.save_atomic(self._mem_path(), mem)
            if repeat and tid in state["tasks"]:
                note = F.REPEAT_MARK + " " + (words or self._reason_class(rkey))
                self._tx(lambda st: F.add_feedback(st, tid, "gate", note))
        except Exception as e:                           # memory is an aid: it must never stop the loop
            self.err("error memory", e)

    @staticmethod
    def _num(c: dict, *names):
        """A non-negative int usage field of one call, or None (unknown, never 0)."""
        for n in names:
            v = c.get(n)
            if isinstance(v, int) and not isinstance(v, bool) and v >= 0:
                return v
        return None

    @classmethod
    def _sum_known(cls, calls, *names):
        vals = [cls._num(c, *names) for c in calls]
        vals = [v for v in vals if v is not None]
        return sum(vals) if vals else None

    @staticmethod
    def _scope_limit(state, tid: str) -> int:
        """The same file bound applies to every free editor."""
        return SCOPE_MAX_FILES

    def _scope_add(self, tid: str, tasks: dict, add, state=None) -> None:
        """The runner's path check found a module the failing test runs outside the task, and the model named it
        (report scope_add): the plan row gains it, so the next pass measures the base and its path again (the staged
        files change the base key). Refused (event scope_add_refused): an unknown task, a forbidden path, more than
        SCOPE_MAX_FILES files, a task that is RUNNING/REVIEW again or a locked plan."""
        from tools import factory_gate
        t = tasks.get(tid)
        old = list(t.touch_files) if t else []
        new = old + [p for p in dict.fromkeys(add if isinstance(add, list) else [])
                     if isinstance(p, str) and p not in old]
        why = "" if t else "unknown task"
        if not why and len(new) == len(old):
            return
        limit = self._scope_limit(state, tid)
        if not why and len(new) > limit:
            why = "more than %d files" % limit
        for path in ([] if why else new[len(old):]):
            why = why or (factory_gate.is_forbidden(path, t.kind) or "")
        if not why:
            try:
                F.amend_task(self.plan_path, tid, touch_files=new)
            except (F.InvalidPlan, F.LockBusy, OSError) as e:   # the same refusals an answer meets (line of apply)
                why = "%s: %s" % (type(e).__name__, str(e))
        if why:
            self.event("run", task_id=tid, status="scope_add_refused", reason=F.redact(why)[:200],
                       events=["scope_add_refused"])
        else:
            self.event("run", task_id=tid, status="scope_add", events=["scope_add:" + p for p in new[len(old):]])

    @staticmethod
    def _ran_model_or_gate(res: dict, calls: list, st, rkey: str) -> bool:
        """The run reached the model or the gates (so a failure is about the pipeline), and it was
        not a wait, a budget stop or a block BEFORE the model."""
        blocked = str(res.get("blocked_reason") or "")
        waits = {"cloud_down", "cloud_busy", "reslice:stale", "SliceWait"}
        if (st in waits or rkey in waits or blocked in waits or res.get("channel_reason") in waits):
            return False
        if (st in ("WAITING_CHANNEL", "IDLE", "NO_RESULT") or rkey in CHANNEL_REASONS
                or rkey in BEFORE_MODEL or blocked in BEFORE_MODEL
                or rkey == "review_chain_short"):   # a wait for a free critic model, not a failed run: never brakes
            return False
        return bool(calls) or rkey.startswith(REJECT_PREFIXES) or rkey in (
            "gate_unknown", "reviewer_failed", "no_independent_reviewer", "provider_error")

    @staticmethod
    def _judged_by_gate(rkey: str, res: dict, calls: list) -> bool:
        """The model answered and the gates or a critic judged the candidate (no change, red test, off path, a
        reject): the pipeline is alive, the task or the model is weak. Rule 3 of 21.11 (tactical brakes do not stop
        work): such outcomes never grow the spread brake; live 21.11 15:15 and 15:40 six of them held the whole
        factory 20-30 min each time. Only pipeline faults (gate_unknown, reviewer_failed, provider_error, no
        independent reviewer) still do."""
        if not any(isinstance(c, dict) and (c.get("output_tokens") or c.get("returncode") == 0) for c in calls):
            return False            # no model answered (a dying Kilo: rc 1, 0 tokens): that is the pipeline's fault
        blocked = str(res.get("blocked_reason") or "")
        return (rkey.startswith(REJECT_PREFIXES) or rkey.startswith(("gate:", "gate ")) or
                rkey in JUDGED_OUTCOMES or blocked in JUDGED_OUTCOMES)

    def _spread_brake(self, ls: dict, out: Outcome) -> Outcome:
        """At least five different failures, covering half the live cards, warrant a trial pause."""
        state = self.load()[1]
        live = sum(row.get("status") not in F.SATISFIED | {"FAILED"} for row in state["tasks"].values())
        if len(ls["no_proof"]) < max(5, (live + 1) // 2):
            return out
        hist: dict = {}
        for label in ls["no_proof"].values():
            hist[label] = hist.get(label, 0) + 1
        self._series_charge([], self.clock())       # K different tasks, no channel to blame: the global brake stands
        self._tx(lambda fresh: fresh.__setitem__("infra_streak", max(int(fresh.get("infra_streak", 0)),
                                                                     self.cfg.max_infra)))
        out.reason = "%d different tasks failed without any proof of work: %s" % (
            len(ls["no_proof"]), ", ".join("%s x%d" % kv for kv in sorted(hist.items())))
        out.status = "infra"
        return self._brake_or_wait(self.cfg.max_infra, out)

    @staticmethod
    def _gate_collected(res: dict) -> bool:
        """The gates really ran only if tests were collected (0 collected / a timeout say nothing)."""
        for key in ("tests", "counts"):
            t = res.get(key)
            if isinstance(t, dict) and isinstance(t.get("collected"), int) and t["collected"] > 0:
                return True
        return False

    @staticmethod
    def _is_proof(res: dict, calls: list, st, rkey: str) -> bool:
        """Evidence that the pipeline works: a model call that really answered (rc 0, no error,
        some output) AND a real candidate went through the gates/reviewer. NOT proof: an empty
        answer (gate:no_changes), a dead Kilo (rc != 0 / unknown kind), BLOCKED worker_exception or
        os_error (even after good calls), no calls at all."""
        if res.get("blocked_reason") in ("worker_exception", "os_error") or rkey in (
                "worker_exception", "os_error"):
            return False
        real_call = any(
            c.get("returncode") == 0 and not c.get("error_class") and not c.get("provider_error")
            and ((c.get("output_tokens") or 0) > 0 or (c.get("steps") or 0) > 0
                 or (c.get("tool_events") or 0) > 0) for c in calls)
        candidate = (st == "REVIEW" or res.get("cross_review") is not None
                     or rkey.startswith(("review:", "weakening:"))
                     or (rkey.startswith("gate:") and rkey != "gate:no_changes"
                         and "timeout" not in rkey and Loop._gate_collected(res)))
        return real_call and candidate

    def _events(self, raw) -> list:
        """<= 5 distinct runner events; housekeeping ones go last so they never crowd out the rest."""
        seen, main, tail = set(), [], []
        for x in raw or []:
            x = str(x)
            if x in seen:
                continue
            seen.add(x)
            (tail if x in CLEANUP_EVENTS else main).append(x)
        return [self.rs(x) for x in (main + tail)[:5]]

    @staticmethod
    def _parse(proc) -> dict:
        text = (proc.stdout or b"").decode("utf-8", "replace") if isinstance(
            proc.stdout, bytes) else (proc.stdout or "")
        for line in reversed(text.strip().splitlines()):
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if isinstance(obj, dict) and obj.get("status"):
                return obj
        err = proc.stderr.decode("utf-8", "replace") if isinstance(proc.stderr, bytes) else (
            proc.stderr or "")
        return {"status": "NO_RESULT", "rc": proc.returncode,
                "error": "no result: " + F.redact(err[-200:])}

    @staticmethod
    def _bid(state, tasks, tid) -> str | None:
        if not tid:
            return None
        row = state["tasks"].get(tid) or {}
        return row.get("backlog_id") or (tasks[tid].backlog_id if tid in tasks else None) or None

    # -- PROMOTE
    @staticmethod
    def _id_path(red_id) -> str:
        """'tests.verify.x.test_y.Class::name[p]' (the gate's id) -> 'tests/verify/x/test_y.py::name'."""
        head, _, name = str(red_id).partition("::")
        parts = head.split(".")
        at = next((i for i, p in enumerate(parts) if p.startswith("test_")), len(parts) - 1)
        return "/".join(parts[:at + 1]) + ".py::" + name.split("[", 1)[0]

    def _after_merge(self, tid: str, sha: str, *, recovered: bool = False, ls: dict | None = None,
                     base_sha: str | None = None, head: str | None = None,
                     dur_s: float | None = None) -> None:
        """Complete the durable post-merge effects on both normal and recovery paths.  ``ls``: the caller's own loop state, which it
        saves itself (a second copy saved here would be overwritten by it); without it the state is read and saved here."""
        from tools import factory_architect as A
        tasks, state = self.load()
        own = ls is None
        ls = self.ls() if own else ls
        task = tasks.get(tid)
        bid = self._bid(state, tasks, tid)
        dirty = False
        if bid and not str(bid).lower().startswith("fac-"):     # every merge of a product row counts, a repeated one too: a final build is due
            ls["promoted_total"] = int(ls.get("promoted_total") or 0) + 1
            dirty = True
        if tid not in ls.setdefault("slicer_merges", {}):
            ls["slicer_merges"][tid] = sha
            ls.setdefault("merged_at", {}).setdefault(tid, self.clock())    # W-refresh 1: merge time for the sweep refresh
            engine = state["tasks"].get(tid, {}).get("engine")
            if engine:
                ls.setdefault("contracts_by_engine", {}).setdefault(engine, {"made": 0, "merged": 0})["merged"] += 1
            for key in {bid, F.row_of(bid)} if bid else ():         # W-a4: the row merged: its first engine scores
                rec = (ls.get("cohort") or {}).get(key)
                if isinstance(rec, dict):
                    rec["merged"] = True
            left = list(state["tasks"].get(tid, {}).get("reds_left") or ())       # W-part 3: other reds of the same file stay: the row is not done
            more = self._contract(task).get("more") or ("still red in the same file: " + ", ".join(left[:6]) if left else "")
            if task and task.kind == "code" and more:
                bid = F.row_of(task.backlog_id or tid)
                step = ls.setdefault("row_steps", {}).get(bid, 0) + 1
                ls["row_steps"][bid] = step
                if step < A.MAX_STEPS:
                    ls.setdefault("to_slice", {})[bid] = dict(at=self.clock(), hints=list(task.touch_files),
                        guard=self._id_path(left[0]) if left else "", priority=task.priority, done=F.redact("Merged " + tid + ": " + str(more)))
                else:
                    ls["holds"][bid] = "architect step limit reached"
            dirty = True
        if dirty and own:
            self.save_ls(ls)
        if self._closes_row(task, ls.get("parents")) and not state["tasks"].get(tid, {}).get("reds_left"):
            self._write_closure(tid, self._bid(state, tasks, tid), {"commit": sha}, "promoted")
        self.event("promote", task_id=tid, backlog_id=self._bid(state, tasks, tid),
                   status="promoted", reason="already_merged" if recovered else "promoted",
                   commit=sha, recovered=recovered, base_sha=base_sha, head=head, dur_s=dur_s)

    def _promote(self, tid, tasks, state, ls) -> Outcome:
        cfg, wt = self.cfg, Path(self.cfg.worktree)
        t0 = self.clock()
        src = self.stage / "for-review" / tid
        files = sorted(p for p in src.rglob("*") if p.is_file()) if src.exists() else []
        if not files:  # REVIEW without a package can never be merged: back to the queue
            n = ls.setdefault("requeues", {}).get(tid, 0) + 1
            if n >= self.REQUEUE_PARK:  # a third time: stop the circle, ask Opus
                ls["requeues"].pop(tid, None)
                self._tx(lambda st: F.requeue(st, tid, "нет пакета for-review"))
                self.save_ls(ls)
                self._park(tid, "no_package", "REVIEW without a package %d times" % n)
                self.event("promote", task_id=tid, status="requeued", reason="no_package_parked")
                return Outcome(action="PROMOTE", reason="no_package_parked", status="requeued")
            ls["requeues"][tid] = n
            self._tx(lambda st: F.requeue(st, tid, "нет пакета for-review"))
            ls["bases"].pop(tid, None)
            self.save_ls(ls)
            self.event("promote", task_id=tid, backlog_id=self._bid(state, tasks, tid),
                       status="requeued", reason="no_package", dur_s=round(self.clock() - t0, 3))
            return Outcome(action="PROMOTE", reason="no_package", status="requeued")
        rel = [p.relative_to(src).as_posix() for p in files]
        cur = git_run(cfg.repo, "rev-parse", cfg.branch).strip()
        base = ls["bases"].get(tid)
        fields = dict(task_id=tid, backlog_id=self._bid(state, tasks, tid), base_sha=base or cur)

        def finish(status, reason, outcome_status=None, proof=False, **kw):
            self.event("promote", status=status, reason=reason, head=cur,
                       dur_s=round(self.clock() - t0, 3), **fields, **kw)
            return Outcome(action="PROMOTE", reason=reason, status=outcome_status or status,
                           proof=proof)

        def package_done():
            done = self.stage / "promoted"
            done.mkdir(parents=True, exist_ok=True)
            shutil.rmtree(done / tid, ignore_errors=True)
            shutil.move(str(src), str(done / tid))
            ls["bases"].pop(tid, None)
            self.save_ls(ls)

        # idempotency: the commit may exist although the state was not written
        done_sha = ""
        prefix = "factory(%s):" % tid
        rejected = set(ls.get("rejected", {}).get(tid, []))
        for line in git_run(cfg.repo, "log", "--format=%H %s", "-F", "--grep=" + prefix,
                            cfg.branch).splitlines():
            sha_, _, subject = line.partition(" ")
            if subject.startswith(prefix) and sha_ not in rejected:
                done_sha = sha_
                break
        if done_sha:
            self._tx(lambda st: F.mark_promoted(st, tid, done_sha))
            self._after_merge(tid, done_sha, recovered=True, ls=ls, base_sha=fields["base_sha"],
                              head=cur, dur_s=round(self.clock() - t0, 3))
            package_done()
            return Outcome(action="PROMOTE", reason="already_merged", status="promoted")
        try:
            why = self._refuse_reason(rel, src, tasks.get(tid))
        except Exception as e:  # a package we cannot even read is a package failure
            return self._promote_failed(tid, tasks, state, ls, e, finish)
        if why:
            self._tx(lambda st: self._block_review(st, tid, "scope_violation", "promote refused: " + why,
                                                       self.clock()))
            shutil.rmtree(src, ignore_errors=True)
            ls["bases"].pop(tid, None)
            self.save_ls(ls)
            return finish("refused", F.redact(why)[:200])
        moved, keep = "", False
        if not base:
            moved = "база не записана"
        elif base != cur:
            changed = set(git_run(cfg.repo, "diff", "--name-only", base, cur).split("\n"))
            mine = {x.casefold() for x in (rel + list(tasks[tid].touch_files)
                                           + list(tasks[tid].tests))}
            hit = sorted(c for c in changed if c.casefold() in mine)
            if hit:
                moved = "база сдвинулась: " + ", ".join(hit[:5]) + "; " + self._merge_verdict(cfg.repo, base, cur, hit, src, rel)
            else:
                # the factory's own promotes that landed while this pass worked: the candidate was gated without them
                near = self._own_neighbours(tid, tasks.get(tid), base, cur, ls)
                if near:
                    moved, keep = "рядом сдвинулось (свой promote): " + ", ".join(near[:5]), True
                    near_gen = self._near_gen(tasks.get(tid))
        if moved and "3-way: конфликт слияния" in moved and getattr(tasks.get(tid), "contract", ""):
            # W-optim 3: a card of a contract whose merge conflicts: READY again, no strike, no reslice (the next pass applies
            # the edit onto the fresh snapshot and runs the gates again)
            return self._conflict_back(tid, ls, moved, src, finish)
        if moved:
            if keep:
                ls.setdefault("near_once", {})[tid] = near_gen   # counted only when the card really goes back
            kept = self._tx(lambda st: self._requeue_review(st, tid, moved, keep))
            if not kept:
                shutil.rmtree(src, ignore_errors=True)  # runner refuses an existing package
            ls["bases"].pop(tid, None)
            self.save_ls(ls)
            return finish("requeued", "base_moved" if base else "base_unknown")
        if git_run(wt, "rev-parse", "--abbrev-ref", "HEAD").strip() != cfg.branch:
            raise RuntimeError("merge worktree is not on " + cfg.branch)
        self._restore(wt, rel)  # leftovers of an interrupted promote
        outside = [p for p in self._dirty_paths(wt) if p not in set(rel)]
        if outside:
            raise RuntimeError("merge worktree is dirty outside the package: " + ", ".join(outside[:5]))
        no_diff = False
        try:
            git_run(cfg.repo, "tag", "-f", "factory/known-good", cur)    # #64: instant rollback point = pre-promote HEAD
            conflicts = []
            for path, name in zip(files, rel):
                dst = wt.joinpath(*name.split("/"))
                dst.parent.mkdir(parents=True, exist_ok=True)
                if base and base != cur and dst.exists():
                    merged, bad = self._merge_file(cfg.repo, base, name, dst, path)
                    if bad:
                        conflicts.append(name)
                    else:
                        dst.write_bytes(merged.encode("utf-8"))
                    continue
                shutil.copyfile(path, dst)
            if conflicts:
                self._restore(wt, rel)
                if getattr(tasks.get(tid), "contract", ""):       # W-optim 3: a card of a contract: READY again, no strike
                    return self._conflict_back(tid, ls, "3-way: конфликт слияния: " + ", ".join(conflicts[:5]), src, finish)
                kept = self._tx(lambda st: self._requeue_review(st, tid, "3-way: конфликт слияния: " + ", ".join(conflicts[:5]), False))
                shutil.rmtree(src, ignore_errors=True)
                ls["bases"].pop(tid, None)
                self.save_ls(ls)
                return finish("requeued", "merge_conflict")
            git_run(wt, "add", "--", *rel)
            if subprocess.run(["git", "-C", str(wt), "diff", "--cached", "--quiet"]).returncode == 0:
                no_diff = True
            else:
                title = F.redact((tasks[tid].title if tid in tasks else tid).splitlines()[0])[:72]
                git_run(wt, "-c", "user.name=agent-factory", "-c",
                        "user.email=agent-factory@localhost", "commit", "-q", "-m",
                        "factory(%s): %s\n\nCandidate from free models, NOT accepted (review by "
                        "Opus/owner).\nbase=%s files=%s\n" % (tid, title, base, ",".join(rel)))
        except Exception as e:
            try:
                self._restore(wt, rel)
            except Exception as e2:
                self.event("infra", status="error", reason="restore: " + F.redact(str(e2))[:200])
            lock_trouble = isinstance(e, subprocess.CalledProcessError) and "index.lock" in str(
                getattr(e, "stderr", "") or "")
            err_text = str(getattr(e, "stderr", "") or "") + str(getattr(e, "output", "") or "")
            machine = (isinstance(e, PermissionError) or getattr(e, "errno", None) in (errno.ENOSPC, errno.EACCES)
                       or getattr(e, "winerror", None) in (5, 32, 112)
                       or (isinstance(e, subprocess.CalledProcessError)
                           and ("No space left on device" in err_text or "Permission denied" in err_text)))
            if lock_trouble or machine or not isinstance(e, (OSError, subprocess.CalledProcessError)):
                raise    # the environment (antivirus, a full disk, a held lock, dying git) is not the package's fault
            return self._promote_failed(tid, tasks, state, ls, e, finish)
        except BaseException:
            try:
                self._restore(wt, rel)
            except Exception as e2:
                self.event("infra", status="error", reason="restore: " + F.redact(str(e2))[:200])
            raise
        if no_diff:  # the candidate equals HEAD: nothing to merge, never record a foreign sha
            self._tx(lambda st: self._block_review(st, tid, "no_diff", "promote: candidate equals branch HEAD (no diff)",
                                                       self.clock()))
            shutil.rmtree(src, ignore_errors=True)
            ls["bases"].pop(tid, None)
            self.save_ls(ls)
            return finish("no_diff", "no_diff", "no_diff")
        sha = git_run(wt, "rev-parse", "HEAD").strip()
        self._tx(lambda st: F.mark_promoted(st, tid, sha))
        self._after_merge(tid, sha, ls=ls, base_sha=fields["base_sha"], head=cur,
                          dur_s=round(self.clock() - t0, 3))
        self._clear_requeues(ls, tid)
        ls.get("near_once", {}).pop(tid, None)
        ls.get("promote_fail", {}).pop(tid, None)
        ls.get("merge_retry", {}).pop(tid, None)
        package_done()
        return Outcome(action="PROMOTE", reason="promoted", status="promoted", proof=True)

    @staticmethod
    def _block_review(state, tid, reason, note, now=None) -> None:
        row = state["tasks"][tid]
        F._block(row, reason, time.time() if now is None else now)     # <id>: a reason and a term
        row.pop("candidate", None)
        F.add_feedback(state, tid, "gate", note)

    @staticmethod
    def _blob(repo, rev, name) -> str:
        # W-flow 3: bytes, not text mode: a CRLF file keeps its CRLF (text mode turns every CRLF into LF)
        proc = subprocess.run(["git", "-c", "core.quotepath=off", "-C", str(repo), "show", rev + ":" + name],
                              capture_output=True)
        return proc.stdout.decode("utf-8", errors="replace") if proc.returncode == 0 else ""

    @staticmethod
    def _read_exact(path: Path) -> str:
        return path.read_bytes().decode("utf-8", errors="replace")      # newline='' semantics: nothing translated

    def _merge_file(self, repo, base, name, dst: Path, cand: Path) -> tuple[str, bool]:
        """Candidate file onto the branch file as a 3-way merge from the candidate's base (never a blind copy)."""
        ours = self._read_exact(dst)
        theirs = self._read_exact(cand)
        b = self._blob(repo, base, name)
        if not b and ours != theirs:
            # both sides added the file: an empty side gives way, otherwise Python additions that do not meet are joined
            if not ours.strip():
                return theirs, False
            if not theirs.strip():
                return ours, False
            return three_way_merge(b, ours, theirs, name)
        return three_way_merge(b, ours, theirs, name)

    def _merge_verdict(self, repo, base, cur, hit, src, rel) -> str:
        """Why the candidate goes back: would a 3-way merge onto the new HEAD be clean (re-gate) or conflict."""
        bad = []
        for name in hit:
            if name not in rel:
                continue
            try:
                ours = self._blob(repo, cur, name)
                theirs = self._read_exact(src.joinpath(*name.split("/")))
                if three_way_merge(self._blob(repo, base, name), ours, theirs, name)[1]:
                    bad.append(name)
            except Exception:
                bad.append(name)
        return "3-way: конфликт слияния: " + ", ".join(bad[:5]) if bad else "3-way: слияние чистое, нужен перепрогон ворот"

    def _conflict_back(self, tid, ls, note, src, finish) -> Outcome:
        """W-optim 3: a merge conflict of a contract card. No reslice, no throw-away, no strike: REVIEW -> READY with
        not_before = now. The first time the next pass repeats the application of the edit (REPLACE FUNCTION/SEARCH) onto a
        fresh snapshot and the gates; a repeated conflict goes back the same way, and the previous edits stay as a hint in
        the feedback (the note names the conflicting files)."""
        n = int(ls.setdefault("merge_retry", {}).get(tid, 0)) + 1
        ls["merge_retry"][tid] = n
        if n > self.MERGE_RETRY_MAX:         # a constant conflict does not circle for ever: the card goes up as a merge failure
            ls["merge_retry"].pop(tid, None)
            shutil.rmtree(src, ignore_errors=True)
            ls["bases"].pop(tid, None)
            self.save_ls(ls)
            self._park(tid, "promote_failed", "the merge conflicted %d times in a row: %s" % (n - 1, note))
            return finish("parked", "merge_conflict")
        # the package is deleted below, so the previous edit travels in the feedback: a diff of the candidate against its base
        edit = self._edit_hint(src, ls["bases"].get(tid), room=F.FEEDBACK_MAX_CHARS - len(note) - 160)
        hint = note + (" (repeat %d)" % n if n >= 2 else "")
        if edit:
            hint += "; the previous edit is a hint, apply it onto the fresh code:\n" + edit
        now = self.clock()
        def back(st):
            F.requeue(st, tid, hint)
            st["tasks"][tid]["not_before"] = now
        self._tx(back)
        shutil.rmtree(src, ignore_errors=True)
        ls["bases"].pop(tid, None)
        self.save_ls(ls)
        return finish("requeued", "merge_conflict", retry=n)

    def _edit_hint(self, src, base, room=1200) -> str:
        """W-optim fix3: the candidate's edit as a unified diff against its base (cut to ``room`` chars); '' when unknown."""
        if not base or room < 200:
            return ""
        import difflib
        parts = []
        try:
            for p in sorted(q for q in Path(src).rglob("*") if q.is_file()):
                name = p.relative_to(src).as_posix()
                old = self._blob(self.cfg.repo, base, name).splitlines()
                new = self._read_exact(p).splitlines()
                parts.extend(difflib.unified_diff(old, new, "a/" + name, "b/" + name, n=1, lineterm=""))
        except Exception:
            return ""
        text = "\n".join(parts)
        return text if len(text) <= room else text[:room] + "\n...(cut)"

    @staticmethod
    def _lease_and_fail(state, tid) -> str:
        """A REVIEW row holds no lease: it takes one for this write, then AF.fail_row sends the row back to the slicer
        (reslice:stale, no strike)."""
        token = "promote-" + uuid.uuid4().hex
        state["tasks"][tid].update(status="RUNNING", lease=token)
        return F.fail_row(state, tid, token, "reslice:stale")

    def _requeue_review(self, state, tid, note, keep) -> bool:
        """REVIEW -> READY. ``keep``: the approved candidate resumes at the gates on the new base, no coder call."""
        had = isinstance(state["tasks"][tid].get("candidate"), dict)
        F.requeue(state, tid, note, keep_candidate=keep)
        return keep and had

    def _own_neighbours(self, tid, task, base: str, cur: str, ls: dict | None = None) -> list:
        """Files of the factory's OWN promotes in base..cur that touch what this candidate was gated against: its tests
        and their one-hop neighbours, through everything the changed files affect. Two candidates that were built
        together are tested together by the gates of the second one on the new base."""
        if task is None:
            return []
        own_ls = ls is None
        ls = self.ls() if own_ls else ls
        if ls.get("near_once", {}).get(tid) == self._near_gen(task):
            return []     # W-base 1: one return to the gates per generation of the card; the final build catches the rest
        log = git_run(self.cfg.repo, "log", "--format=%H %s", base + ".." + cur)
        own = [x.split(" ", 1)[0] for x in log.splitlines() if x.split(" ", 1)[-1].startswith("factory(")]
        if not own:
            return []
        files = set()
        for sha in own:
            files.update(x for x in git_run(self.cfg.repo, "show", "--name-only", "--format=", sha).split("\n") if x)
        from tools import affected_tests
        graph = affected_tests.Graph(Path(self.mirror))
        # only changed CODE counts: a merged test (or a data file) cannot change what this card was gated against
        code = sorted(f for f in files if f.endswith(".py") and f in graph.files and not graph.is_test(f))
        if not code:
            return []
        return self._near_code(task, code, graph, base)

    @staticmethod
    def _near_gen(task) -> str:
        """The generation of a card: its contract and files. A resliced or re-cut card has another one, so the single
        return to the gates is counted per generation, not for the whole life of the id."""
        raw = "%s|%s|%s" % (getattr(task, "contract", ""), list(getattr(task, "touch_files", ()) or ()),
                            list(getattr(task, "tests", ()) or ()))
        return hashlib.sha1(raw.encode("utf-8", "replace")).hexdigest()[:12]

    def _near_code(self, task, code, graph, base) -> list:
        """The changed code files the card's own files or functions depend on: the same file, or radius 1 (the card's
        files and tests import it and use a name that the merged change touched)."""
        from tools import affected_tests
        from tools import factory_cards as K
        touch = set(task.touch_files)
        funcs = {}      # file -> top-level names of the card's functions (empty: the whole file)
        try:
            parts = K.contract_of(task).get("parts") or []
        except Exception:
            parts = []
        for part in parts:
            if isinstance(part, dict) and isinstance(part.get("file"), str):
                names = {s.split(".")[0] for s in (part.get("symbols") or []) if isinstance(s, str)}
                if part["file"] in funcs and not funcs[part["file"]]:
                    continue
                funcs.setdefault(part["file"], set()).update(names)
        used = {}       # identifiers the card's code and tests mention
        for f in sorted(touch | set(task.tests)):
            if f not in graph.defs:
                continue
            defs = graph.defs[f]
            want = funcs.get(f) if f in touch else None
            ids = set()
            for name, idents in defs.items():
                if not want or name in want or name == "<module>":
                    ids.update(idents)
                    ids.add(name)
            used[f] = ids
        out = []
        for c in code:
            if c in touch:
                out.append(c)
                continue
            owners = [f for f in used if c in graph.edges.get(f, ())]
            if not owners:
                continue
            names = affected_tests.changed_symbols(c, graph.root, base)
            if names is None or any(used[f] & names for f in owners):
                out.append(c)
        return sorted(out)

    def _promote_failed(self, tid, tasks, state, ls, e, finish) -> Outcome:
        """A deterministic failure caused by the package (copy, git add, scope): count per task, park
        at ESCALATE_AFTER; never a CRASH, never the brake."""
        n = ls.setdefault("promote_fail", {}).get(tid, 0) + 1
        why = "%s: %s" % (type(e).__name__, F.redact(str(getattr(e, "stderr", "") or e))[:200])
        if n >= ESCALATE_AFTER:
            ls["promote_fail"].pop(tid, None)
            self.save_ls(ls)
            shutil.rmtree(self.stage / "for-review" / tid, ignore_errors=True)
            self._park(tid, "promote_failed", "merging the package failed %d times: %s" % (n, why))
            return finish("parked", "promote_failed")
        ls["promote_fail"][tid] = n
        self.save_ls(ls)
        self.event("promote", task_id=tid, status="failed", reason=why, attempt=n)
        return Outcome(action="PROMOTE", reason="promote_failed", status="promote_failed", sleep=60)

    def _refuse_reason(self, rel, src, task) -> str:
        """Last line before git: scope and the gate's own forbidden paths (imported, not copied)."""
        from tools import factory_gate
        allowed = {x.casefold() for x in (task.touch_files + task.tests)} if task else set()
        for r in rel:
            parts = r.split("/")
            if ".." in parts or ".git" in parts or Path(r).is_absolute():
                return "bad path " + r
        extra = [r for r in rel if r.casefold() not in allowed]
        if extra:
            return "outside task scope: " + ", ".join(extra[:5])
        texts = {r: (src.joinpath(*r.split("/"))).read_text(encoding="utf-8", errors="replace")
                 for r in rel}
        named = tuple(task.touch_files) if getattr(getattr(self, "cfg", None), "self_repo", False) and task else ()   # 8.1: only the second instance merges the factory's
        own = bool(getattr(getattr(self, "cfg", None), "self_repo", False))
        rig = bool(task) and factory_gate.is_rig_task(task)
        named = tuple(task.touch_files) if rig else named                                      # W-rig: the card's named files open tests/**
        bad = factory_gate.weakening_violations(self.mirror, texts, task.kind, named, own, rig=rig)   # own code (and its tests, no weaker), only files the contract names
        return "; ".join(bad[:3]) if bad else ""

    @staticmethod
    def _dirty_paths(wt: Path) -> list[str]:
        out = git_run(wt, "status", "--porcelain", "--untracked-files=all", retry_lock=False)
        paths = []
        for line in out.splitlines():
            p = line[3:].split(" -> ")[-1].strip().strip('"')
            if p:
                paths.append(p)
        return paths

    def _restore(self, wt: Path, rel: list[str]) -> None:
        """Put the package paths back to HEAD: index, tracked files, new untracked files."""
        for r in rel:
            tracked = subprocess.run(["git", "-C", str(wt), "cat-file", "-e", "HEAD:" + r],      # in HEAD, not in the index: a
                                     capture_output=True).returncode == 0                        # file that was just `add`ed is new
            subprocess.run(["git", "-C", str(wt), "reset", "-q", "--", r], capture_output=True)
            if tracked:  # content from HEAD written directly: works while index.lock is held
                blob = subprocess.run(["git", "-C", str(wt), "cat-file", "--filters", "HEAD:" + r],
                                      capture_output=True)
                if blob.returncode == 0:
                    wt.joinpath(*r.split("/")).write_bytes(blob.stdout)
            else:
                wt.joinpath(*r.split("/")).unlink(missing_ok=True)
        left = [p for p in self._dirty_paths(wt) if p in set(rel)]
        if left:
            raise RuntimeError("could not restore: " + ", ".join(left[:5]))

    # -- stats
    def _channel_rows(self, state) -> list:
        """stats.json: per channel the calls of today, what closes it and until when (the view of the shared ledger)."""
        path = Path(self.cfg.channels)
        configured = CH.validate(json.loads(path.read_text(encoding="utf-8"))["channels"], warn=False)
        env = {**os.environ, **self.extra_env}
        quota = state.get("channel_quotas") if isinstance(state.get("channel_quotas"), dict) else {}
        seen = quota_ledger.view(quota, quota_ledger.others(path.resolve().parent / "quota", str(self.ckpt)),
                                 now=self.clock())
        return CH.channel_report(configured, seen, env, now=self.clock())

    def _watch_pool(self, state, rows) -> None:
        """The pool watchdog: headroom 0 while READY work waits for longer than POOL_DRY_S -> ONE probe of the
        earliest-cooled channel of every tier (probe_fn; the answer lifts or extends its marks) and a pool event
        status="probe" with the outcome. Repeats at most once per POOL_DRY_S. Never stops the loop."""
        try:
            now = self.clock()
            if not any(r["status"] == "READY" for r in rows):
                self._dry_since = None
                return
            if not Path(self.cfg.channels).is_file():   # no registry: nothing to probe, and the pass already reported it
                return
            try:
                gate = self._head_gate(None, state)
            except (OSError, ValueError, KeyError, TypeError):
                gate = None
            # fac-68: with a live head the pool is dry only when no channel can take a ticket today (the head's own
            # verdict); the ledger's headroom 0 is then just the head's queue, not a dry pool
            dry = (gate == "quota") if gate is not None else self._headroom(None, state) <= 0
            if not dry:
                self._dry_since = None
                return
            if self._dry_since is None:
                self._dry_since = now
            if now - self._dry_since < POOL_DRY_S or now - self._probed_at < POOL_DRY_S:
                return
            self._probed_at = now
            path = Path(self.cfg.channels)
            configured = CH.validate(json.loads(path.read_text(encoding="utf-8"))["channels"], warn=False)
            env = {**os.environ, **self.extra_env}
            quota = state.get("channel_quotas") if isinstance(state.get("channel_quotas"), dict) else {}
            ledger = path.resolve().parent / "quota"
            seen = quota_ledger.view(quota, quota_ledger.others(ledger, str(self.ckpt)), now=now)
            for channel in CH.probe_targets(configured, seen, env, now=now):
                info = self.probe_fn(channel, env[channel["key_env"]])
                if info is None:
                    self.event("pool", status="probe", channel=channel["id"], tier=CH.tier_of(channel), result="no_probe")
                    continue
                done = {}

                def apply(st, channel=channel, info=info):
                    quotas = st.setdefault("channel_quotas", {})
                    CH.note_sent(quotas, channel, now=now)         # W-dry 3: the probe is a real request: counted
                    done.update(CH.probe_outcome(quotas, channel, info, env=env, now=now, channels=configured))
                    quota_ledger.publish(ledger, str(self.ckpt), quotas)
                self._tx(apply)
                self.event("pool", status="probe", channel=channel["id"], tier=CH.tier_of(channel),
                           result=done.get("result"), http=info.get("status"), cool_s=done.get("cool_s") or None,
                           lifted=done.get("lifted"))
        except Exception as e:  # the watchdog must never stop the loop
            self.err("pool watchdog", e)

    REPORT_S = 600.0

    def _report(self, name, fn):
        """A report over the whole telemetry (tens of megabytes), made at most once per REPORT_S: no step pays for it."""
        kept = self.__dict__.setdefault("_reports", {}).get(name)
        if kept is None or not 0 <= time.monotonic() - kept[0] < self.REPORT_S:
            kept = self._reports[name] = (time.monotonic(), fn())
        return kept[1]

    def _stats(self) -> None:
        try:
            tasks, state = self.load()
            ls = self.ls()
            rows = state["tasks"].values()
            tot = ls["totals"]
            blocked: dict = {}
            for r in rows:
                if r["status"] == "BLOCKED":
                    key = str(r.get("blocked_reason") or "unknown")
                    blocked[key] = blocked.get(key, 0) + 1
            stats = {
                "contracts_by_engine": ls.get("contracts_by_engine", {}),
                "promoted": sum(r["status"] == "PROMOTED" for r in rows),     # merged into the factory branch
                "accepted": len(ls["accepted"]) if isinstance(ls.get("accepted"), dict) else 0,   # taken by the coordinator
                "rejected": tot.get("rejected", 0),
                "quarantine": sum(r["status"] == "FAILED" and r.get("reason") == "quarantine"
                                  for r in rows),
                "blocked": sum(r["status"] == "BLOCKED" for r in rows),
                "blocked_by_reason": blocked,
                "opus_questions": len(ls["holds"]) + sum(
                    r["status"] in ("BLOCKED", "FAILED") for r in rows) + sum(
                    t.only_opus or not t.privacy_safe for t in tasks.values()),
                "tokens_in": tot.get("tokens_in", 0), "tokens_out": tot.get("tokens_out", 0),
                "seconds": tot.get("seconds", 0), "infra_streak": state.get("infra_streak", 0),
                "last_iteration": self.ts(), "run_id": self.run_id,
                "iterations": self.iterations,
                "max_workers": self._max_k, "mean_k": round(self._k_sum / self._k_n, 2) if self._k_n else None}
            stats["blockers"] = F.hold_census(state, tasks)
            try:
                from tools import factory_architect as A
                stats["agent"] = A.agent_stats()
                stats["agent"]["usd_per_merged_by_engine"] = A.price_per_merged(ls.get("contracts_by_engine", {}))
            except Exception as e:      # statistics never stop the loop
                self.err("agent stats", e)
            try:        # W-a4: the cohort yield of each step (rows of its first contract -> merged in the end)
                from tools import factory_architect as A
                stats["engine_yield"] = A.engine_yield(ls.get("cohort") or {}, self.clock())
            except Exception as e:      # statistics never stop the loop
                stats["engine_yield"] = {"error": F.redact(type(e).__name__)}
            try:
                from tools import factory_bisect as BIS
                stats["bisect"] = BIS.counts(self.cfg.state_dir)        # W-bisect 5: {done, regression, never_green, moved}
            except Exception as e:      # statistics never stop the loop
                stats["bisect"] = {"error": F.redact(type(e).__name__)}
            try:        # W-vgs 5: the ensemble of the small tier over 24 h
                stats["vgs"] = self._report("vgs", lambda: factory_metrics.vgs_report(self.dir, now=self.ts()))
            except Exception as e:      # statistics never stop the loop
                stats["vgs"] = {"error": F.redact(type(e).__name__)}
            stats["outdated"] = len(ls.get("outdated_tests") or {})      # W-prio 4: red tests that name what the product no longer has
            stats["lost"] = int(ls.get("lost_count") or 0)              # W-lost 1: rows given back to the slicer by the supply invariant
            stats["queues"] = {"to_slice": len(ls.get("to_slice", {})),
                "slicing": len(ls.get("slicing", {})),
                "slice_wait": sum(until > self.clock() for until in ls.get("slice_wait", {}).values()),
                "ready": sum(r["status"] == "READY" for r in rows),
                "running": sum(r["status"] == "RUNNING" for r in rows),
                "review": sum(r["status"] == "REVIEW" for r in rows),
                "quarantine": len(set(ls.get("quarantine", {})) | {
                    F.row_of(r.get("backlog_id") or tid) for tid, r in state["tasks"].items()
                    if r.get("reason") == "quarantine"})}
            # W-gemma 5: keys of two projects that seem to share one daily quota (a note only, nothing is silenced)
            stats["shared_project_suspect"] = (state.get("channel_quotas") or {}).get("shared_project_suspect", {})
            try:        # W-dry 1: the day's refusal of the edit channels, and what waits for code because of it
                dry = self._edit_dry(state)
                waiting = self._dry_blocked(tasks, state) if dry else set()
                stats["edit_dry"] = {"on": dry, "ready_without_code": len(waiting),
                                     "rows_for_code": sum(1 for j in self._slicers.values() if j.ctx.get("cause") == "dry")}
            except Exception as exc:
                stats["edit_dry"] = {"error": F.redact(type(exc).__name__)}
            counts: dict = {}
            for at, kind in ls.get("slice_faults", []):
                if self.clock() - at < 3600:
                    counts[kind] = counts.get(kind, 0) + 1
            stats["slice_faults"] = counts
            try:        # W-money 4: the owner's money numbers
                money = self._report("money", lambda: factory_metrics.money_report(self.dir, now=self.ts()))
                stats["accepted_hour"] = money["accepted_hour"]
                stats["accepted_per_1000_calls"] = money["accepted_per_1000_calls"]
                stats["accepted_per_1000_wire"] = money["accepted_per_1000_wire"]      # fac-farm 2: per network request
                stats["edit_first_try_pct"] = money["edit_first_try_pct"]
                stats["first_try_model"] = money["first_try_model"]
                stats["first_try_code"] = money["first_try_code"]
                stats["allowance_left"] = money["allowance_left"]
            except Exception as exc:
                stats["money"] = {"error": F.redact(type(exc).__name__)}
            try:
                from tools import factory_paid_critic as PK
                stats["paid"] = dict(PK.day_report(), ladder=self._ladder_sig())
            except Exception as exc:                  # no state file or a busy lock: the stats still go out
                stats["paid"] = {"error": F.redact(type(exc).__name__)}
            try:
                stats["channels"] = self._channel_rows(state)
            except Exception as exc:                  # no channel file: the stats still go out
                stats["channels"] = {"error": F.redact(type(exc).__name__)}
            try:        # W-solver: the solves of the loop (counters of the main instance only)
                from tools import factory_solver as SV
                if not self.cfg.self_repo:
                    stats["solver"] = SV.STATS.snapshot()
            except Exception as exc:
                stats["solver"] = {"error": F.redact(type(exc).__name__)}
            if getattr(self, "_head", None) is not None:
                stats["head"] = self._head.stats()     # fac-40: per channel ok / 503 / 429 of the hour, tokens in the minute, queue by role
            F.save_atomic(self.stats_path, stats)
            self._watch_pool(state, rows)
            if blocked or stats["quarantine"] or ls["holds"] or any(
                    t.only_opus or not t.privacy_safe for t in tasks.values()):
                self._write_questions(tasks, state, ls)
        except F.LockBusy:
            return                  # a writer holds the state this instant: the numbers wait for the next iteration
        except Exception as e:  # stats must never stop the loop
            self.event("infra", status="error", reason="stats: " + F.redact(str(e))[:200])

    # -- main loop
    def _snapshot_answers(self) -> None:
        try:
            self._known_names = {f.name for f in (self.dir / "answers").glob("*.json")}
        except OSError:
            self._known_names = set()

    def _answer_waiting(self, since: float = 0) -> bool:
        """A name we have not seen wakes the sleeping loop once (then it is known)."""
        try:
            new = {f.name for f in (self.dir / "answers").glob("*.json")} - self._known_names
        except OSError:
            return False
        self._known_names |= new
        return bool(new)

    def _sleep(self, total: float) -> None:
        start = time.time()
        left = total
        while left > 0 and not self.stop.exists():
            if self.cfg.until and dt.datetime.fromtimestamp(self.clock()) >= self.cfg.until:
                return
            if self._answer_waiting(start):  # an Opus answer arrived while we slept
                return
            d = min(self.cfg.chunk, left)
            self.sleep_fn(d)
            left -= d

    def _clean_state_tmp(self) -> None:
        """Files in <state-dir>/tmp older than a day are leftovers of earlier runs."""
        cutoff = time.time() - 86400
        try:
            for item in (self.dir / "tmp").iterdir():
                try:
                    if item.stat().st_mtime < cutoff:
                        shutil.rmtree(item, ignore_errors=True) if item.is_dir() else item.unlink()
                except OSError as e:
                    self.err("tmp cleanup", e)
        except OSError:
            pass

    def _use_state_tmp(self):
        """Temp files (gate mkdtemp, triage profile, pytest basetemp) live in <state-dir>/tmp: their
        paths end up in test output and model remarks, so they must not carry the user's name."""
        saved = (tempfile.tempdir, os.environ.get("TEMP"), os.environ.get("TMP"))
        try:
            tmp = self.dir / "tmp"
            tmp.mkdir(exist_ok=True)
            tempfile.tempdir = str(tmp)
            os.environ["TEMP"] = os.environ["TMP"] = str(tmp)
        except OSError as e:
            self.err("state tmp", e)
        return saved

    @staticmethod
    def _restore_tmp(saved) -> None:
        tempfile.tempdir = saved[0]
        for name, value in (("TEMP", saved[1]), ("TMP", saved[2])):
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    def _drain_before_exit(self) -> None:
        """STOP, the deadline or --once with workers still live: no admission, every worker is accounted first."""
        if self.pool.workers:
            try:
                self._drain()
            except Exception as e:
                self.err("drain", e)

    def run(self) -> int:
        cfg = self.cfg
        if not self.acquire():
            return EXIT_LOCK_ERROR if self._lock_error else EXIT_RUNNING
        self.power_fn(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
        saved_tmp = self._use_state_tmp()
        try:
            if cfg.clear_brake:  # only the instance that owns loop.pid may touch the state
                self.clear_brake()
            if self._brake_gate():
                if not self._wait_out_brake():
                    return EXIT_BRAKE if not cfg.until or cfg.once else EXIT_OK
            self.clear_stale_lockdir()
            self.release_orphan_leases()
            self._snapshot_answers()   # before the first step: a failing step must still sleep
            self._clean_state_tmp()
            for note in self.startup_notes:
                self.event("infra", status="skipped_channel", reason=note)
            self.event("loop", action="START", status="ok", reason="start", pid=os.getpid(),
                       branch=cfg.branch, until=str(cfg.until) if cfg.until else None)
            self._reenter_on_new_slicer()
            try:
                self._slim_state()
            except Exception as e:  # noqa: BLE001 - housekeeping
                self.err("slim state", e)
            try:
                self._return_worker_exceptions()
            except Exception as e:  # noqa: BLE001 - a fault of the lift never stops the loop
                self.err("worker_exception lift", e)
            try:
                self._lift_rel_decisions()
            except Exception as e:  # noqa: BLE001 - a fault of the lift never stops the loop
                self.err("rel decision lift", e)
            self._build_router_table()
            self._discover_keys()
            self._start_head()
            while True:
                if self.stop.exists():
                    self._drain_before_exit()
                    self.event("loop", action="EXIT", status="stop", reason="STOP")
                    return EXIT_OK
                if cfg.until and dt.datetime.fromtimestamp(self.clock()) >= cfg.until:
                    self._drain_before_exit()
                    self.event("loop", action="EXIT", status="deadline", reason="deadline")
                    return EXIT_OK
                self._survive_tick()                # <id>: reaper, idle watchdog
                self._keep_head()                   # W-bucket: a head whose pump stopped is started again
                self._head_holds()                # idle: at once, busy: every 20 min (<id>/<id>)
                out = self.step()
                self._last_out = out
                if out.code == EXIT_BRAKE and self.cfg.until and not self.cfg.once:
                    if self._wait_out_brake():
                        continue                    # the term is over: the trial pass runs in this process
                    self._drain_before_exit()       # STOP or the deadline came during the term: a normal end
                    self.event("loop", action="EXIT", status="stop" if self.stop.exists() else "deadline",
                               reason="STOP" if self.stop.exists() else "deadline")
                    return EXIT_OK
                if out.code is not None:
                    return out.code
                if cfg.once:
                    self._drain_before_exit()
                    return EXIT_OK
                self._sleep(min(out.sleep, WAIT_CHUNK_S) if self.pool.workers else out.sleep)
        finally:
            if getattr(self, "_head_close", None) is not None:
                self._head_close()                         # fac-40: the state file goes first, so no caller finds a dead host
            self._bg_cancel.set()                          # a background ask in flight ends; nothing of it was applied
            for w in list(self.pool.workers.values()):     # an exit with live workers (an error): their jobs die
                try:
                    if w.owned is not None:
                        w.owned.kill()
                except Exception as e:
                    self.err("kill worker", e)
            self._restore_tmp(saved_tmp)
            self.power_fn(ES_CONTINUOUS)
            self.release()


# ---- summary: the ONE reader of the telemetry format ------------------------------------------------

TEL_FILES = ("telemetry.jsonl", "telemetry.jsonl.1", "telemetry.jsonl.2")
SUMMARY_SCHEMA = 3


def _label(value) -> str:
    value = value if isinstance(value, str) else "unknown"
    return value if re.fullmatch(r"[A-Za-z0-9._:/-]{1,60}", value) else "other"


def _count(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _tally() -> dict:
    return {"rows": 0, "calls": 0, "tokens_in": 0, "tokens_out": 0, "errors": {}, "status": {},
            "calls_usage_unknown": 0, "http_429": 0}


def summary(state_dir, backlog=None, free_ram_fn=free_ram_bytes) -> dict:
    """Numbers only: no task text, no ids, no paths, no keys (it goes to the public mirror).
    Keys of the per-model/per-span tallies are the mirror's (rows, calls, tokens_in, tokens_out, errors, status) plus
    calls_usage_unknown and http_429; ``funnel`` runs found -> triaged -> ready -> claimed -> coded -> gate_pass ->
    reviewed -> promoted -> accepted and is followed by blocked / requeued / parked.  Unknown usage is never a 0."""
    root = Path(state_dir)
    spans: dict = {}
    models: dict = {}
    status_all: dict = {}
    rows = bad = skipped = 0
    claimed, coded, gated, reviewed, promoted_ev, accepted_ev = set(), set(), set(), set(), set(), set()
    requeued = parked_ev = 0
    ks: list = []
    for fname in TEL_FILES:
        path = root / fname
        try:
            if not path.is_file():
                continue
            if path.stat().st_size > 200_000_000:
                skipped += 1
                continue
            with path.open(encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if not line.strip():
                        continue
                    try:
                        row = json.loads(line)
                    except (ValueError, RecursionError):
                        bad += 1
                        continue
                    if not isinstance(row, dict) or not isinstance(row.get("span"), str) or not (
                            "ts" in row or "run_id" in row):
                        bad += 1
                        continue
                    rows += 1
                    span = _label(row["span"])
                    span_t = spans.setdefault(span, _tally())
                    span_t["rows"] += 1
                    st = row.get("status") if isinstance(row.get("status"), str) else None
                    if st:
                        lab = _label(st)
                        span_t["status"][lab] = span_t["status"].get(lab, 0) + 1
                        status_all[lab] = status_all.get(lab, 0) + 1
                    tid = row.get("task_id") if isinstance(row.get("task_id"), str) else None
                    role = row.get("role") if isinstance(row.get("role"), str) else None
                    if role:
                        model_t = models.setdefault(_label(row.get("model")), _tally())
                        for t in (span_t, model_t):
                            t["calls"] += 1
                            tin, tout = _count(row.get("tokens_in")), _count(row.get("tokens_out"))
                            if tin is None and tout is None:
                                t["calls_usage_unknown"] += 1
                            t["tokens_in"] += tin or 0
                            t["tokens_out"] += tout or 0
                            if row.get("http_status") == 429:
                                t["http_429"] += 1
                            if row.get("error_class"):
                                cls = _label(row["error_class"])
                                t["errors"][cls] = t["errors"].get(cls, 0) + 1
                        if tid and role == "code" and not row.get("error_class"):
                            coded.add(tid)
                    if span == "run" and not role and isinstance(row.get("k"), int) and not isinstance(row.get("k"), bool):
                        ks.append(row["k"])         # workers live when this pass started (itself included)
                    if tid and span == "run" and not role and st not in (None, "WAITING_CHANNEL", "IDLE", "NO_RESULT"):
                        claimed.add(tid)
                        if st == "REVIEW":
                            gated.add(tid)
                    if tid and span == "review":
                        reviewed.add(tid)
                    if span == "promote":
                        if tid and st == "promoted":
                            promoted_ev.add(tid)
                        if st == "requeued":
                            requeued += 1
                        if st == "parked":
                            parked_ev += 1
                    if span == "accept" and tid and st == "accepted":
                        accepted_ev.add(tid)
        except OSError:
            skipped += 1
    for t in models.values():
        del t["rows"], t["status"]
    # the state: counts by status, never the rows themselves
    by_status: dict = {}
    triaged = set()
    state_promoted = set()
    try:
        plan = json.loads((root / "plan.json").read_text(encoding="utf-8"))
        for r in (plan.get("tasks") if isinstance(plan, dict) else plan) or []:
            if isinstance(r, dict) and isinstance(r.get("backlog_id"), str):
                triaged.add(r["backlog_id"])
    except (OSError, ValueError):
        pass
    try:
        st_rows = json.loads((root / "state.json").read_text(encoding="utf-8")).get("tasks") or {}
        for tid, r in st_rows.items():
            if isinstance(r, dict):
                lab = _label(r.get("status"))
                by_status[lab] = by_status.get(lab, 0) + 1
                if r.get("status") == "PROMOTED":
                    state_promoted.add(tid)
    except (OSError, ValueError, AttributeError):
        pass
    ls = {}
    try:
        ls = json.loads((root / "loop_state.json").read_text(encoding="utf-8"))
        if not isinstance(ls, dict):
            ls = {}
    except (OSError, ValueError):
        pass
    accepted = set(ls["accepted"]) if isinstance(ls.get("accepted"), dict) else set()
    known_rows = triaged | set(ls.get("holds") or {}) | set(ls.get("seen") or {}) | set(ls.get("closed") or {})
    found = None
    if backlog is not None:
        try:
            from tools import agent_factory_import as imp
            found = len(imp.parse_open_rows(Path(backlog), root, include_closed=False))
        except Exception:
            found = None
    blocked = by_status.get("BLOCKED", 0)
    promoted = promoted_ev | state_promoted
    funnel = {"found_in_backlog": found if found is not None else "unknown",
              "known_to_loop": len(known_rows), "triaged": len(triaged), "ready": by_status.get("READY", 0),
              "claimed": len(claimed), "coded": len(coded), "gate_pass": len(gated), "reviewed": len(reviewed),
              "promoted": len(promoted), "accepted": len(accepted | accepted_ev)}
    try:
        ram = round(free_ram_fn() / 2 ** 30, 2)
        ram = ram if ram < 10 ** 6 else "unknown"
    except Exception:
        ram = "unknown"
    return {"schema": SUMMARY_SCHEMA, "funnel": funnel,
            "side": {"blocked": blocked, "requeued": requeued, "parked": parked_ev},
            "tasks_now": by_status, "span": spans, "model": models, "status": status_all,
            "accepted": len(accepted | accepted_ev), "promoted": len(promoted),
            "rows_recognized": rows, "unrecognized_rows": bad, "skipped_files": skipped,
            "free_ram_gb": ram,
            "workers": {"max": max(ks), "mean_k": round(sum(ks) / len(ks), 2)} if ks else None}


def factory_metrics_spend_file():
    try:
        from tools import factory_paid_critic
        return factory_paid_critic._spend_file()
    except Exception:
        return None


def summary_main(argv) -> int:
    p = argparse.ArgumentParser(prog="factory_loop summary", description="funnel, spend per model, free RAM")
    p.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR)
    p.add_argument("--backlog", type=Path, help="counts the open rows for the first funnel step")
    a = p.parse_args(argv)
    print(json.dumps(summary(a.state_dir, a.backlog), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


# ---- CLI --------------------------------------------------------------------------------

def _accepts(fn, name: str) -> bool:
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False
    return name in params or any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())


def _dt(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.strip())


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="autonomous factory loop (single instance)")
    p.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR)
    p.add_argument("--repo", type=Path, default=WORK / "CLOUD_REPO")
    p.add_argument("--branch", default="factory/night-20261119")
    p.add_argument("--worktree", type=Path, default=WORK / "W7" / "stage" / "factory_night_wt")
    p.add_argument("--backlog", type=Path, default=WORK / "BACKLOG_ECHO.md")
    p.add_argument("--channels", type=Path, default=WORK / "W7" / "factory" / "channels.json")
    p.add_argument("--until", type=_dt, help='"YYYY-MM-DD HH:MM" local time (may cross midnight)')
    p.add_argument("--once", action="store_true", help="one iteration (debugging)")
    p.add_argument("--clear-brake", action="store_true", help="remove BRAKE and start")
    p.add_argument("--no-cloud-sweep", action="store_true", help="do not refresh the red-guard sweep in the cloud")
    p.add_argument("--self-repo", action="store_true", help="the repository is the factory's own code: fac-* rows only, named files mergeable")
    p.add_argument("--exit-when-idle", action="store_true", help="end the loop when nothing is left to do (the canary)")
    p.add_argument("--env-file", type=Path, help="read ONLY the channels' key_env names from it")
    p.add_argument("--small-model", default=Config.small_model)
    p.add_argument("--large-model", default=Config.large_model)
    p.add_argument("--review-model", default=Config.review_model)
    return p.parse_args(argv)


def _known_kind(plan: Path, tid: str | None, bid: str | None, touch=()) -> str:
    """kind of the answered task when the plan knows it (fast refusal only); a hold is 'code'.
    A missing plan is a hold; a broken one is an error (ValueError), never a silent 'code'."""
    if not plan.exists():
        return "code"
    try:
        rows = F.read_plan(json.loads(plan.read_text(encoding="utf-8")))
    except Exception as e:
        raise ValueError("plan.json is unreadable: %s" % type(e).__name__) from e
    found = [t for t in rows.values() if (tid and t.id == tid) or (not tid and bid and t.backlog_id == bid)]
    want_unit = any(str(x).startswith("tests/") for x in touch)
    found.sort(key=lambda t: (t.kind == "unit_test") != want_unit)
    return found[0].kind if found else "code"


def answer_main(argv) -> int:
    """`answer` subcommand: validate Opus' answer and drop it into <state-dir>/answers/."""
    from tools import factory_gate
    p = argparse.ArgumentParser(prog="factory_loop answer",
                                description="Opus answer to a factory question")
    p.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR)
    p.add_argument("--backlog-id")
    p.add_argument("--task-id")
    p.add_argument("--touch", nargs="+")
    p.add_argument("--tests", nargs="+")
    p.add_argument("--read", nargs="+")
    p.add_argument("--target", nargs="+", help="path:selector")
    p.add_argument("--depends-on", nargs="*", help="empty list clears the dependencies")
    p.add_argument("--close", action="store_true", help="close the row/task (needs --note)")
    p.add_argument("--accept", action="store_true",
                   help="the coordinator accepts a PROMOTED task (PROMOTED = merged, ACCEPTED = taken)")
    p.add_argument("--reject", action="store_true", help="the coordinator rejects a PROMOTED task: back to READY with --note")
    p.add_argument("--revert", action="store_true",
                   help="with --reject: the loop also reverts the merged commit (task FAILED superseded:revert, the row to the slicer)")
    p.add_argument("--release-private", action="store_true",
                   help="allow a public --goal for a row private by content (keys, passwords, recordings); "
                        "other rows need no flag")
    p.add_argument("--goal", help="technical wording for the coder (checked: no owner words)")
    p.add_argument("--kind", choices=("code", "unit_test"), help="for a new task from a hold")
    p.add_argument("--port", help="a port task: the old-branch commit whose behaviour it brings over (its diff is "
                                  "shown to the coder as a reference)")
    p.add_argument("--contract", help="JSON architect contract")
    p.add_argument("--note", default="")
    p.add_argument("--package", type=Path, help="W-pack: the folder of a verified root package (files/ and verdict.json)")
    a = p.parse_args(argv)
    if a.package and not a.backlog_id:
        a.backlog_id = "rel-pack"
    if a.port is not None and not F.PORT_SHA.fullmatch(a.port):
        p.error("--port must be a commit sha (7-40 hex characters)")
    if not a.backlog_id and not a.task_id:
        p.error("--backlog-id or --task-id is required")
    if not Path(a.state_dir).is_dir():
        p.error("--state-dir does not exist: %s" % a.state_dir)
    if len(a.note) > 2000:
        p.error("--note is longer than 2000 characters")
    if any(len(x or "") > 64 for x in (a.backlog_id, a.task_id)):
        p.error("--backlog-id/--task-id are longer than 64 characters")
    if a.goal:
        from tools import agent_factory_import as imp
        clean, bad = imp.screen(a.goal, imp.MIN_PUBLIC_CHARS)
        if clean is None or bad or len(a.goal) > F.GOAL_MAX:
            p.error("--goal fails the public check (%s): give a technical wording without the "
                    "owner's words, quotes or times (up to %d characters)" % (",".join(bad), F.GOAL_MAX))
        hit = Loop._privacy_hit(a.goal)
        if hit:
            p.error("--goal contains %s: it can never go to an external model" % hit)
    if a.accept and (not a.task_id or a.close or any(x is not None for x in (
            a.touch, a.tests, a.read, a.target, a.depends_on)) or a.goal):
        p.error("--accept needs --task-id and nothing else but --note")
    if a.reject and (not a.task_id or not a.note.strip() or a.accept or a.close or a.goal or any(x is not None for x in (a.touch, a.tests, a.read, a.target, a.depends_on))):
        p.error("--reject needs --task-id and --note and nothing else")
    if a.revert and not a.reject:
        p.error("--revert goes with --reject")
    if a.close and not a.note.strip():
        p.error("--close needs --note with the reason")
    if a.close and any(x is not None for x in (a.touch, a.tests, a.read, a.target, a.depends_on)):
        p.error("--close closes the row: do not combine it with --touch/--tests/--read/--target/--depends-on")
    if a.close and not a.task_id:
        try:
            plan_rows = F.read_plan(json.loads((Path(a.state_dir) / "plan.json").read_text(encoding="utf-8")))
        except (OSError, ValueError, F.InvalidPlan):
            plan_rows = {}
        same = [t for t, tk in plan_rows.items() if tk.backlog_id == a.backlog_id]
        if len(same) > 1:
            p.error("several tasks share %s (%s): give --task-id" % (a.backlog_id, ", ".join(same[:5])))
    ans = {"backlog_id": a.backlog_id, "task_id": a.task_id, "note": F.redact(a.note),
           "goal": a.goal}
    if a.contract is not None:
        try:
            if not isinstance(json.loads(a.contract), dict):
                raise ValueError("contract must be an object")
        except ValueError as exc:
            p.error(str(exc))
        ans["contract"] = a.contract
    if a.package:
        ans["package"] = str(a.package)
    if a.release_private:
        ans["release_private"] = True
    if a.port:
        ans["port_from"] = a.port
    if a.close:
        ans["close"] = True
    if a.accept:
        ans["accept"] = True
    if a.reject:
        ans["reject"] = True
        if a.revert:
            ans["revert"] = True
    if a.kind == "unit_test":
        if set(a.touch or []) != set(a.tests or []) or not a.touch:
            p.error("a unit_test task touches exactly its tests: --touch must equal --tests")
        ans["kind"] = "unit_test"
    try:
        for key, vals in (("touch_files", a.touch), ("tests", a.tests), ("read_files", a.read)):
            if vals is not None:
                ans[key] = [F.safe_path(v) for v in vals]
        kind = "unit_test" if a.kind == "unit_test" else _known_kind(
            Path(a.state_dir) / "plan.json", a.task_id, a.backlog_id, ans.get("touch_files", []))
        for path in ans.get("touch_files", []):
            why = factory_gate.is_forbidden(path, kind)
            if why:
                raise F.InvalidPlan("%s: %s" % (path, why))
        if a.target:
            targets = {}
            for item in a.target:
                path, sep, selector = item.partition(":")
                if not sep or not selector:
                    raise F.InvalidPlan("--target must be path:selector: " + item)
                path = F.safe_path(path)
                if path not in set(ans.get("touch_files", []) + ans.get("read_files", [])
                                   + ans.get("tests", [])):
                    raise F.InvalidPlan("--target file is not in --touch/--read/--tests: " + path)
                targets[path] = selector
            ans["context_targets"] = targets
        if a.depends_on is not None:
            ans["depends_on"] = list(a.depends_on)
    except (F.InvalidPlan, ValueError) as e:
        p.error(str(e))
    if a.note.strip() and (a.task_id or a.backlog_id):
        try:  # a note of a PUBLIC task goes into the external prompt: same check, fast refusal
            plan = F.read_plan(json.loads((Path(a.state_dir) / "plan.json").read_text(encoding="utf-8")))
            known = [t for t in plan.values()
                     if (a.task_id and t.id == a.task_id) or (not a.task_id and t.backlog_id == a.backlog_id)]
            if known and known[0].privacy_safe and not known[0].only_opus:
                Loop._check_note(a.note)
        except F.InvalidPlan as e:
            p.error(str(e))
        except (OSError, ValueError):
            pass
    ans = {k: v for k, v in ans.items() if v not in (None, "")}
    if not any(k in ans for k in ("touch_files", "tests", "read_files", "context_targets",
                                  "depends_on", "note", "close", "goal", "accept", "port_from", "contract")):
        p.error("empty answer: give fields or --note")
    box = Path(a.state_dir) / "answers"
    box.mkdir(parents=True, exist_ok=True)
    name = "%d-%s.json" % (time.time_ns(), re.sub(r"[^A-Za-z0-9_-]", "_", a.backlog_id or a.task_id))
    payload = json.dumps(ans, ensure_ascii=False, indent=2)
    target = box / name
    for n in range(1, 1000):
        try:
            with open(target, "x", encoding="utf-8") as fh:  # exclusive: never overwrite an answer
                fh.write(payload)
            break
        except FileExistsError:
            target = box / (name[:-5] + "-%d.json" % n)
    else:
        p.error("could not find a free file name in " + str(box))
    print("answer saved:", target)
    return 0


RIG_ROOTS = ("tests/", "echo_sync/")


def rig_main(argv) -> int:
    """W-rig 4: `rig --cand DIR --ids FILE --why TEXT --state-dir DIR [--repo DIR]`: a rel-rig-<sha8> card (priority 0, rig contract with the
    whole changed files as parts) from the directory of changed files (paths tests/**, echo_sync/**). Idempotent: the same files and ids
    give the same card id and the plan keeps the first one."""
    from tools import factory_architect as A
    p = argparse.ArgumentParser(prog="factory_loop rig", description="a test-stand (rig) card from a directory of changed files")
    p.add_argument("--cand", type=Path, required=True)
    p.add_argument("--ids", type=Path, required=True, help="a file with the target test ids, one per line")
    p.add_argument("--why", required=True)
    p.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR)
    p.add_argument("--repo", type=Path, default=Path("."))
    a = p.parse_args(argv)
    if not a.cand.is_dir():
        p.error("--cand is not a directory: %s" % a.cand)
    if not Path(a.state_dir).is_dir():
        p.error("--state-dir does not exist: %s" % a.state_dir)
    try:
        ids = [x.strip() for x in a.ids.read_text(encoding="utf-8").splitlines() if x.strip()]
    except OSError as exc:
        p.error("--ids is unreadable: %s" % exc)
    if not ids:
        p.error("--ids is empty")
    files = {}
    for path in sorted(a.cand.rglob("*")):
        if path.is_file():
            rel = path.relative_to(a.cand).as_posix()
            if "__pycache__" in rel or rel.endswith((".pyc", ".pyo")):
                continue            # a cache is never a card file, wherever it lies
            if not rel.startswith(RIG_ROOTS):
                p.error("%s: a rig card carries only tests/** and echo_sync/**" % rel)
            try:
                files[rel] = path.read_bytes().decode("utf-8")      # bytes: CRLF stays CRLF (the card text and its hash are the file's own)
            except (OSError, UnicodeDecodeError) as exc:
                p.error("%s: unreadable as utf-8 text: %s" % (rel, exc))
    if not files:
        p.error("--cand holds no files")
    digest = hashlib.sha1(json.dumps([files, ids], sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    bid = "rel-rig-" + digest[:8]
    test = {"use": ids[0]}
    if len(ids) > 1:
        test["also"] = ids[1:]
    contract = dict(row=bid, decision="fix", rig=True, why=F.redact(a.why)[:500], test=test,
                    parts=[dict(file=name, file_text=text, instruction="Replace the whole file with the text verified in the cloud run of the rig candidate.")
                           for name, text in files.items()])
    # engine="coordinator" is deliberate: this submission is made by the coordinator, so the strong-engine check always
    # passes here; the engine check bites where the card is validated again for the engine that really runs it
    faults = A.validate(contract, Path(a.repo), bid=bid, engine="coordinator")
    if faults:
        print("rig refused: " + "; ".join(faults[:5]), file=sys.stderr)
        return 2
    rows = A.to_tasks(contract, bid=bid, base_id=bid.replace("-", "_"), gen=1, priority=0, title="rig: " + F.redact(a.why)[:80])
    added = F.append_tasks(Path(a.state_dir) / "plan.json", rows)
    print("rig card %s: %s" % (bid, "added " + ",".join(added) if added else "already there"))
    return 0


def _cloud_sweep_fn(a):
    """The existing cloud sweep (tools.echo_cloud.sweep), or None with --no-cloud-sweep / when the module is absent."""
    if getattr(a, "no_cloud_sweep", False):
        return None
    try:
        from tools import echo_cloud
        return echo_cloud.sweep
    except Exception:
        return None


def _release_fn(a):
    """The final build (tools.factory_release.run over the cloud sweep), or None with --no-cloud-sweep / --self-repo (the second
    instance has no product to build) / when a module is absent."""
    if getattr(a, "no_cloud_sweep", False) or getattr(a, "self_repo", False):
        return None
    try:
        from tools import echo_cloud, factory_release
    except Exception:
        return None

    def build(**kw):
        def recheck(names):                         # one short cloud run of the red files; a file that did not finish counts as reproduced
            files = sorted({n.split("::", 1)[0] for n in names})
            _p, res, _id = echo_cloud.sweep(src=kw["snapshot"], files=files, shards=min(len(files), 4) or 1,
                                            label=factory_release.next_label(kw["state_dir"], kw["sha"], prefix="rel-re"))
            if any(isinstance(r, dict) and r.get("missing") for r in res.values()):
                return list(names)
            return [n for r in res.values() for n in (r.get("failed_ids") or ())]
        return factory_release.run(sweep_fn=echo_cloud.sweep, recheck_fn=recheck,
                                   drop_fn=lambda info: echo_cloud.delete_branch(info["branch"]), **kw)
    return build


def _bisect_fn(a):
    """The history search step (tools.factory_bisect.step over the cloud sweep), or None with --no-cloud-sweep / --self-repo / when a
    module is absent."""
    if getattr(a, "no_cloud_sweep", False) or getattr(a, "self_repo", False):
        return None
    try:
        from tools import echo_cloud, factory_bisect
    except Exception:
        return None

    def step(**kw):
        return factory_bisect.step(sweep_fn=echo_cloud.sweep, drop_fn=lambda info: echo_cloud.delete_branch(info["branch"]), **kw)
    return step


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv and argv[0] == "answer":
        return answer_main(argv[1:])
    if argv and argv[0] == "summary":
        return summary_main(argv[1:])
    if argv and argv[0] == "rig":
        return rig_main(argv[1:])
    a = parse_args(argv)
    absent: list = []
    keys = load_keys(a.env_file, a.channels, absent) if a.env_file else {}
    cfg = Config(state_dir=a.state_dir, repo=a.repo, branch=a.branch, worktree=a.worktree,
                 backlog=a.backlog, channels=a.channels, until=a.until, once=a.once,
                 small_model=a.small_model, large_model=a.large_model,
                 review_model=a.review_model, env_file=a.env_file, clear_brake=a.clear_brake,
                 self_repo=a.self_repo, exit_when_idle=a.exit_when_idle)
    from tools import factory_paid_critic as PK, factory_architect as A
    rungs = ["free", "free_main", "free_small"]
    # The paid stages are candidates for the whole run; Loop._asks decides on every slicing which of them is live.
    rungs += ["paid", "agent"]
    cfg.architect_rungs = tuple(rungs)
    try:
        loop = Loop(cfg, extra_env=keys, startup_notes=["no key for channel env " + n for n in absent],
                    cloud_fn=getattr(factory_cloud_gate, "available", None), sweep_fn=_cloud_sweep_fn(a), release_fn=_release_fn(a), bisect_fn=_bisect_fn(a), reap_fn=lambda **kw: SV.reap(procs_fn=SV.list_processes, kill_fn=SV.kill_tree, **kw))
    except ValueError as e:
        raise SystemExit(str(e))
    if loop.cloud_fn is not None:       # W-hyp2: the main instance with a live cloud route lets the hypotheses batch publish its tree (the gate's other routes stay as they were)
        factory_cloud_gate.enable_batch()
    return loop.run()


if __name__ == "__main__":
    sys.exit(main())
