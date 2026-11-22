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
import datetime as dt
import contextlib
import ctypes
import copy
import errno
import hashlib
import inspect
import json
import os
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
from tools.factory_gate import MIN_FREE_RAM  # noqa: <id>  (one floor for the loop and the gates)
EST_DEFAULT_BYTES = 300 * 2 ** 20     # a worker's memory before the pool has measured five (job peaks: 36 + 87 MB)
EST_KEEP, EST_MIN_SAMPLES = 20, 5
# A worker of the light engine is one HTTP call with the files in the prompt (peak 40-120 MB); only a Kilo worker
# needs the gate's 2 GB floor. The floor admits light workers on a 3 GB machine; the estimate still limits how many.
LIGHT_FLOOR = 768 * 2 ** 20
# While the cloud answers the candidate checks run there (no local slot, no RAM budget): the pool counts no RAM per worker
# and takes up to factory_cloud_gate.MAX_LIVE tasks; only this emergency floor of the whole machine stays.
CLOUD_FLOOR = 256 * 2 ** 20
WAIT_CHUNK_S = 3.0                    # real seconds between two looks at the pool while workers run
STALE_INDEX_LOCK_S = 120
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
# Channel-wide reasons stop every task; everything else is the task's own not_before.
from tools.agent_factory_runner import ESCALATE_AFTER, INFRA_CHANNEL_REASONS, INFRA_DEFERS, LIGHT_MAX_FILES  # noqa: <id>
from tools.agent_factory_runner import engine_for as _engine_for  # noqa: <id>
from tools.agent_factory_runner import _light_post  # noqa: <id>  (the <id> spec pass; tests replace this name)
from tools import factory_ab  # noqa: <id>


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
    status, _ = _light_post(LIGHT_ENDPOINTS[provider], key, body, 60)
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

# <id>: A/B experiments. A new one = one line here plus the place that reads Loop.arm(tid, name).
EXPERIMENTS = {
    "spec_pass": ("on", "off"),
    "coder_model": ("google/gemini-3.5-flash-lite", "google/gemini-3.1-flash-lite"),
    # 20.11 02:05: a small-tier model (Gemma 4) as a later tournament candidate won 0 of ~20 coder calls of the
    # night and took ~175 s per call (503s, answers cut at the output cap): the runner's --small-follow-up
    "small_follow_up": ("on", "off"),
}
# Decided by passes per hour of the arm's own run time, not per run: an arm that only costs time wins nothing per
# run but loses per hour.
PER_HOUR_EXPERIMENTS = frozenset(("small_follow_up",))

DEAD_CHANNEL = INFRA_DEFERS | INFRA_CHANNEL_REASONS   # real infrastructure faults: the runner's sets
CHANNEL_REASONS = DEAD_CHANNEL | frozenset(("rate_minute", "rate_day", "region", "budget_exhausted",
                                            "channel_wait"))
# Temporary faults: they postpone only their own channel (channel_until) or their own task (not_before) with
# an exponential, jittered pause. They never grow the brake series. A permanent break (a dead channel, a dead
# runner, "infra" without such a reason) still does.
TEMPORARY_CHANNEL = frozenset(("rate_limited_suspect", "rate_limited", "429", "channel_timeout"))
TEMPORARY_TASK = frozenset(("transient", "env_shortage", "fresh_model_busy"))
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
try:    # 22.11: the paid escalation tier takes up to factory_paid_coder.MAX_FILES files; optional like in the runner
    from tools import factory_paid_coder as _paid_coder
except ImportError:  # pragma: no cover
    _paid_coder = None
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


def three_way_merge(base: str, ours: str, theirs: str) -> tuple[str, bool]:
    """git merge-file on three texts: (merged text, conflict). ``ours`` is the branch now, ``theirs`` the candidate."""
    if ours == base or ours == theirs:
        return theirs, False
    if theirs == base:
        return ours, False
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


class _Later(Exception):
    """A temporary obstacle: the answer file stays in answers/ for the next iteration."""


@dataclass
class Outcome:
    code: int | None = None
    sleep: float = 0
    action: str = ""
    reason: str = ""
    status: str = "ok"
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
    exps: dict | None = None
    hint: str = ""
    peak: int | None = None
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
        self.thread = threading.Thread(target=self._run, name="factory-" + kind, daemon=True)

    def _run(self) -> None:
        try:
            self.result = self._work()
        except BaseException as e:          # handed to the loop thread, which raises or books it as before
            self.error = e
        finally:
            self.dur_s = time.monotonic() - self.t0
            self.done.set()


def _cloud_up(fn) -> bool:
    """True when the cloud-gate probe ``fn`` says the cloud answers; no probe or any fault of it: the local rules."""
    try:
        return bool(fn and fn())
    except Exception:           # noqa: BLE001  a probe that breaks is "no cloud", never a stopped pool
        return False


class Loop:
    TXN_WAIT_S = 10.0       # a transaction on the state waits at most this long for the lock (a commit lasts ms)
    CLAIM_WAIT_S = 2.0      # the claim waits less: a held lock is WAIT state_locked, not a stalled loop

    def __init__(self, cfg: Config, *, triage_fn=None, runner_cmd=None, clock=time.time,
                 sleep=time.sleep, power_fn=set_execution_state, free_ram_fn=free_ram_bytes,
                 extra_env=None, startup_notes=None, rng=None, wait_fn=None, cloud_fn=None, reap_fn=None, sweep_fn=None):
        if cfg.review_model in (cfg.small_model, cfg.large_model):
            raise ValueError("review model must differ from the code model: " + cfg.review_model)
        self.cfg = cfg
        self.rng = rng or random.Random()
        self.extra_env = dict(extra_env or {})
        self.startup_notes = list(startup_notes or [])
        self.triage_fn = triage_fn
        self.sweep_fn = sweep_fn        # None: no cloud sweep (tests); main passes tools.echo_cloud.sweep
        self._sw = None                 # the cloud sweep job in flight (Prefetch) or None
        self._sw_refresh_at = 0.0
        self.runner_cmd = list(runner_cmd or [sys.executable, "-B", "-m",
                                              "tools.agent_factory_runner"])
        self.clock, self.sleep_fn = clock, sleep
        self.power_fn, self.free_ram_fn = power_fn, free_ram_fn
        self.cloud_fn = cloud_fn      # () -> bool: does the cloud gate answer now (main gives factory_cloud_gate.available)
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
        self._run_exps = None      # the experiments of the RUN in progress, written to its loop event
        self._bg = None            # the one background job in flight (Prefetch) or None
        self._bg_cancel = threading.Event()
        self._tel_lock = threading.RLock()
        self.reap_fn = reap_fn          # None: no reaping (tests); main passes the real one
        self._idle = SV.IdleWatch()
        self._reap_at = -1e18

    def arm(self, tid: str, name: str, ls: dict | None = None) -> str:
        """<id>: the decided winner of the experiment, else the task's stable hash arm."""
        arms = EXPERIMENTS[name]
        try:
            won = ((ls if ls is not None else self.ls()).get("experiments") or {}).get(name) or {}
            if won.get("winner") in arms:
                return won["winner"]
        except Exception as e:
            self.err("arm", e)
        return factory_ab.assign(tid, name, arms)

    def _task_experiments(self, tid: str, task, ls: dict) -> dict:
        names = ["coder_model", "small_follow_up"] + (
            ["spec_pass"] if task is not None and task.kind == "unit_test" else [])
        return {n: self.arm(tid, n, ls) for n in names}

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

    def _decide_experiments(self) -> None:
        """<id>: at START every undecided experiment is decided from the telemetry (enough cases, a clear margin);
        the decision goes to loop_state, the growth journal and an event. A fault never stops the loop."""
        try:
            rows = self._telemetry_rows()
            ls = self.ls()
            done = ls.setdefault("experiments", {})
            changed = False
            for name in EXPERIMENTS:
                if isinstance(done.get(name), dict) and done[name].get("winner"):
                    continue
                per_arm = factory_ab.outcomes(rows, name)
                decision = (factory_ab.decide(per_arm, margin=0.25, per_hour=True) if name in PER_HOUR_EXPERIMENTS
                            else factory_ab.decide(per_arm))
                if decision is None:
                    continue
                at = self.ts()
                done[name] = {"winner": decision["winner"], "at": at, "per_arm": per_arm}
                changed = True
                factory_ab.record(self.dir / "growth.jsonl", name, decision, at)
                self.event("experiment", status="decided", reason=("%s: %s" % (name, decision["winner"]))[:200])
            if changed:
                self.save_ls(ls)
        except Exception as e:
            self.err("experiments", e)

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
        try:
            out = self._step()
        except F.LockBusy:      # the state is locked by a live writer: the same wait as always, no failure
            out = Outcome(sleep=60, action="WAIT", reason="state_locked")
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
        exps, self._run_exps = (self._run_exps if out.action == "RUN" else None), None
        self.event("loop", action=out.action, reason=out.reason, status=out.status,
                   sleep_s=out.sleep, dur_s=round(self.clock() - t0, 3),
                   base_sha=self.base_sha or None, iteration=self.iterations,
                   experiments=exps or None)
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
            live = CH.usable(configured, quota if isinstance(quota, dict) else {}, {**os.environ, **self.extra_env})
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

    def _act(self, state, tasks, ls, now) -> dict:
        wait_s = max(0.0, float(ls.get("channel_until", 0)) - now)
        free = 1 if (self.pool.workers and not self._capacity(None)) else 0
        return F.next_action(state, now, wait_s, self._has_more(ls, now), tasks, free=free, skip=self.pool.tids())

    def _step(self) -> Outcome:
        cfg, now = self.cfg, self.clock()
        try:
            self.base_sha = refresh_mirror(cfg.repo, cfg.branch, self.mirror)
        except (subprocess.CalledProcessError, OSError) as e:
            return self._git_wait(e)
        ls = self.ls()
        if ls.pop("git_wait", None) is not None:
            self.save_ls(ls)
        self.apply_answers()  # Opus answers first: before anything else touches the state
        self._bg_poll()       # a finished background triage / hold pick is applied here, in this thread
        self._sweep_tick(now)  # the red-guard supply follows the loop's own results and a periodic cloud sweep
        with self.txn() as (_tasks, state):       # a lease a live worker still holds is ended by the loop, not freed
            freed = F.release_expired(state, now, keep=self.pool.tids())
        if freed:
            self.event("infra", status="released", reason="lease_expired:" + ",".join(freed))
        tasks, state = self.load()
        ls = self.ls()
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
            if out.status == "empty":           # the backlog gave nothing: a FAILED task past its term instead
                return self._idle_requeue(tasks, state, now) or out
            return out
        if self.pool.workers:                  # nothing more to start now: wait for the next worker to end
            return self._await_workers()
        if name == "RUN":                      # work is ready but no worker may start: the reason is the wait
            return Outcome(sleep=60, action="WAIT", reason=self._refused or "not_runnable")
        if name == "WAIT":
            if why == "not_before_or_lease":       # 21.11 rule 3: only delayed tasks are left; the jam gives FAILED ones back
                got = self._idle_requeue(tasks, state, now)
                if got is not None:
                    return got
            return Outcome(sleep=min(max(float(act.get("wait_s") or 0), 5), 60),
                           action="WAIT", reason=why)
        if name in ("HOLD", "DONE"):
            got = self._idle_requeue(tasks, state, now)
            if got is not None:
                return got
        if name == "HOLD":
            self._write_questions(tasks, state, ls)
            self._write_reconcile(tasks, state, self.ls(), now)
            sleep = cfg.hold_sleep
            if isinstance(act.get("wait_s"), (int, float)):     # the earliest block term ends the HOLD
                sleep = min(sleep, max(5.0, float(act["wait_s"])))
            return Outcome(sleep=sleep, action="HOLD", reason=why)
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
        if used >= F.AUTO_UNBLOCK_MAX or why == "already_green":
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
        for _ in range(64):                                 # bounded: every round starts a worker or ends the loop
            if act["action"] != "RUN":
                break
            tid = next((t for t in (act.get("task_ids") or [act.get("task_id")])
                        if t and t not in self.pool.tids()), "")
            if not tid:
                break
            refused = self._capacity(tasks.get(tid))
            if refused:
                break
            if not self._spec_pass(tid, tasks, state, ls):
                got = self._admit(tid, tasks, ls)
                if isinstance(got, Outcome):
                    self._pool_event(admitted, refused, live0)
                    return got, act, tasks, state, ls
                admitted += got
            tasks, state = self.load()          # the claim changed the state, the loop state: nothing stale is kept
            ls = self.ls()
            act = self._act(state, tasks, ls, now)
        self._refused = refused
        self._pool_event(admitted, refused, live0)
        return None, act, tasks, state, ls

    def _pool_event(self, admitted: int, refused: str, live0: int) -> None:
        live = len(self.pool.workers)
        if live >= 2 or (refused and live >= 1):
            est = self._estimate()
            self.event("pool", status="admitted" if admitted else "held", live=live, admitted=admitted or None,
                       refused_by=refused or None, free_ram_mb=int(self.free_ram_fn() / 2 ** 20),
                       est_mb=int(est / 2 ** 20), headroom=self._headroom_seen)

    _headroom_seen = None

    def _ending(self) -> bool:
        cfg = self.cfg
        return self.stop.exists() or bool(cfg.until and dt.datetime.fromtimestamp(self.clock()) >= cfg.until)

    def _await_workers(self) -> Outcome:
        """Workers are live: wait for the next one to end (a short look every WAIT_CHUNK_S: a cooled channel or freed
        RAM may admit one more). STOP, the deadline or a due brake: no admission, drain every live worker."""
        while True:
            if self._ending() or self._brake_due is not None:
                return self._drain()
            done = self.pool.wait_any(0.25 if self._bg is not None else WAIT_CHUNK_S)
            if done:
                return self._account_done(done[0])
            late = [w for w in self.pool.workers.values()
                    if w.owned is not None and w.res is None and time.monotonic() - w.t_claim > RUNNER_TIMEOUT_S]
            if late:
                return self._account_done(late[0], timed_out=True)
            self._bg_poll()                     # a finished portion becomes tasks now, not after the next worker ends
            self._head_holds()                  # the gate decides; a pick runs in the background
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

    def _drain(self) -> Outcome:
        """No admission: wait for every live worker and account it. A brake that is due waits for the last one, and a
        proof of work during the drain cancels it."""
        out = Outcome(action="RUN", reason="drain", status="ok")
        proof = False
        while self.pool.workers:
            done = self.pool.wait_any(WAIT_CHUNK_S)
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

    # -- <id> spec pass: one free model call turns a unit_test row into a spec before the test is written
    SPEC_CODE_MAX = 40000          # all files shown together; a file above LARGE_FILE_CHARS is shown as a view
    SPEC_FILE_ROOM = 14000         # the view of one large file: outline + the parts the row names
    SPEC_FINAL = frozenset(("ok", "not_testable", "failed", "too_large"))   # "later": no channel or HTTP error

    def _spec_pass(self, tid: str, tasks, state, ls) -> bool:
        """True when the task's goal changed or the task was parked (the caller chooses again). Never raises."""
        task = tasks.get(tid)
        if (task is None or task.kind != "unit_test" or not task.privacy_safe or task.only_opus
                or ls.get("specs", {}).get(tid) in self.SPEC_FINAL
                or self.arm(tid, "spec_pass", ls) == "off"):
            return False
        try:
            return self._spec_one(tid, task, state, ls)
        except Exception as e:
            self.err("spec", e)
            try:
                ls.setdefault("specs", {})[tid] = "failed"
                self.save_ls(ls)
            except Exception as e2:
                self.err("spec mark", e2)
            return False

    def _spec_one(self, tid: str, task, state, ls) -> bool:
        from tools import factory_context as X
        from tools import factory_requeue
        from tools import factory_spec
        specs = ls.setdefault("specs", {})
        code, total = {}, 0
        words = X.keywords_from(task.title or "", task.goal or "", strict=False)
        for rel in task.read_files:
            try:
                text = (self.mirror / rel).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if len(text) > X.LARGE_FILE_CHARS:   # live 20.11: 10 of 16 test tasks read a file above 24k chars
                text = X.large_view(rel, text, words, self.SPEC_FILE_ROOM, hint="", tools=False)
            code[rel], total = text, total + len(text)
        if not code:
            specs[tid] = "failed"
            self.save_ls(ls)
            self.event("spec", task_id=tid, status="failed", reason="no code to show")
            return False
        if total > self.SPEC_CODE_MAX:
            specs[tid] = "too_large"
            self.save_ls(ls)
            self.event("spec", task_id=tid, status="too_large", chars=total)
            return False
        bid = task.backlog_id or ""
        row = F.redact(((task.title or "") + chr(10) + (task.goal or "")).strip())
        text = factory_spec.prompt(row, code)
        status, model, answer, used = self._light_ask(text, attempt=1, section="loop-spec",
                                                      quotas=ls.setdefault("spec_quotas", {}), max_tokens=1500)
        later = status != "ok"          # no channel or an HTTP error: not the row's fault, the next RUN asks again
        if not later:
            status = "failed"           # until the answer parses
        spec = factory_spec.parse(answer, code) if answer else None
        changed = False
        if later:
            specs[tid] = "later"
        elif spec is None:
            specs[tid] = "failed"
        elif spec["testable"]:
            payload = {"task_id": tid, "goal": factory_spec.goal(spec, bid) + " Row: " + (task.goal or "")[:600]}
            factory_requeue._write_answer(self.dir / "answers", payload, tid)
            specs[tid], status = "ok", "ok"
        else:
            why = "spec: not a testable code defect: " + spec["why"]
            ls["holds"][bid] = why
            specs[tid], status = "not_testable", "not_testable"
        self.save_ls(ls)
        self.event("spec", task_id=tid, model=self.rs(model), status=status, tokens=used)
        if specs[tid] == "ok":
            self.apply_answers()
            changed = True
        elif specs[tid] == "not_testable":
            self._park(tid, "spec_not_testable", why)
            self._write_questions(*self.load(), self.ls())
            changed = True
        return changed

    def _light_ask(self, text: str, *, attempt: int, section: str, quotas: dict, max_tokens: int):
        """One free model call outside the runner (the <id> spec pass, the <id> self-fix head): a registry channel in
        route_order (attempt 1: main first; 2: escalation first), booked in the shared quota ledger under `section`
        and cooled there on 429/5xx. Returns (status, model, answer, tokens): status 'ok', 'no_channel' or
        'http_<code>'; tokens = the usage of the answer, else the estimate."""
        from tools import agent_factory_runner as R
        from tools import factory_channels as C
        from tools import factory_quota as Q
        tokens = C.estimate_tokens(len(text), 0, 500)
        channels = json.loads(Path(self.cfg.channels).read_text(encoding="utf-8"))["channels"]
        env = {**os.environ, **self.extra_env}
        folder = Path(self.cfg.channels).resolve().parent / "quota"

        def publish():
            try:
                Q.publish(folder, section, quotas)
            except OSError as e:
                self.err(section + " ledger", e)
        try:
            channel = C.choose(C.route_order(channels, "code", attempt, tokens),
                               Q.view(quotas, Q.others(folder, section)), tokens, env, now=self.clock())
        except C.ChannelUnavailable:
            return "no_channel", None, "", tokens
        model = channel["model"]
        C.reserve(quotas, channel, tokens, now=self.clock())
        publish()
        provider, _, model_id = model.partition("/")
        body = {"model": model_id, "temperature": 0, "max_tokens": max_tokens,       # ERROR_PATTERNS inline-thought
                "messages": [{"role": "user", "content": R.NO_THOUGHT + "\n\n" + text}]}
        code_http, raw = _light_post(R.LIGHT_ENDPOINTS[provider], env[channel["key_env"]], body, 120)
        if code_http != 200:
            if code_http in (429, 500, 503):      # the next call takes another channel for a while
                C.cool(quotas, channel, now=self.clock())
                publish()
            return "http_%s" % code_http, model, "", tokens
        try:
            data = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
            answer = data["choices"][0]["message"].get("content") or ""
            used = (data.get("usage") or {}).get("total_tokens")
        except (ValueError, KeyError, IndexError, TypeError, AttributeError):
            answer, used = "", None
        return "ok", model, answer, used or tokens

    # -- <id> self-fix: a failure class that repeated becomes a self-build task designed by a free head model
    SELFFIX_EVERY_S = 3600
    SELF_DIR = None     # the self-build folder: plans, trees, queue pid, the self-fix ledger; None: self_dir()

    def self_dir(self) -> Path:
        """The factory's self-build folder next to this project's state dir (<id>: the register lives in the factory,
        not in ECHO; it came from the hard-coded ECHO default before)."""
        return Path(self.SELF_DIR) if self.SELF_DIR is not None else Path(self.cfg.state_dir).parent / "self"

    def _telemetry_rows(self) -> list:
        """The rows of telemetry.jsonl and .1 (a broken line is skipped)."""
        rows = []
        for name in (self.tel_path.name, self.tel_path.name + ".1"):
            try:
                text = (self.dir / name).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for line in text.splitlines():
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict):
                    rows.append(row)
        return rows

    def _selffix(self) -> None:
        """At most once an hour: the most frequent failure class that repeated (<id>) and has no open self-fix gets ONE
        self-build plan from a free head model (strongest channel first): a red-by-assert test in a copy of the
        factory source and the exact change (tools/factory_selffix.py). The plan goes to the self-build queue when
        none runs; its candidate waits for the coordinator's acceptance. A fault never stops the loop."""
        from tools import factory_selffix as X
        try:
            ls = self.ls()
            since = self.clock() - float(ls.get("selffix_at") or 0)
            if since < self.SELFFIX_EVERY_S:
                return
            if self.pool.workers and since < 4 * self.SELFFIX_EVERY_S:
                return          # its pytest is a third one beside the gates' two slots: it waits for an idle pool
            ls["selffix_at"] = self.clock()
            self.save_ls(ls)
            self_dir = self.self_dir()
            if X.queue_running(self_dir):
                self.event("selffix", status="queue_busy")
                return
            src_root, base_sha = (self_dir / "src_path.txt").read_text(encoding="utf-8").split()[:2]
            # one row per finished runner attempt (the loop's own RUN event repeats it: counted twice, a single
            # failure would look like a repeat)
            rows = [r for r in self._telemetry_rows()
                    if r.get("span") == "run" and r.get("attempt") and r.get("reason")]
            # the ledger is the factory's, one for every project (X.LEDGER); a project's old entries move in once
            stored = X.load_ledger(self_dir)
            ledger = X.load_ledger(self_dir, seed=ls.get("selffix"))
            quotas = ls.setdefault("selffix_quotas", {})
            asked = {}
            # only the cases of public tasks go to the free head, as for the coder's class note (_class_note)
            tasks, _ = self.load()
            public = {k for k, t in (tasks or {}).items()
                      if getattr(t, "privacy_safe", False) is True and not getattr(t, "only_opus", True)}

            def ask(prompt):
                status, model, answer, used = self._light_ask(prompt, attempt=2, section="loop-selffix",
                                                              quotas=quotas, max_tokens=4000)
                asked.update(status=status, model=model, tokens=used)
                return answer
            stamp = dt.datetime.fromtimestamp(self.clock()).strftime("%m%d%H%M")
            before = json.loads(json.dumps(ledger))
            report = X.run(rows, ledger, ask=ask, repo_root=src_root, src_root=src_root, self_dir=self_dir,
                           base_sha=base_sha, python=sys.executable, now_iso=self.ts(), stamp=stamp,
                           clean=lambda text: self._public_case(text, 300), public=public)
            if asked and asked.get("status") != "ok":     # the head was not reached: ask again next hour
                # the class's entry as it was before this turn, whole: an open one keeps its plan, a closed or
                # reopened one its tests (a filtered copy dropped them, and the reopened class lost its variation
                # check); a failed open entry ages out again next hour, so its tries are not lost
                cls = report.get("cls")
                if cls in before:
                    ledger[cls] = before[cls]
                else:
                    ledger.pop(cls, None)
            X.save_ledger(self_dir, ledger, stored)
            ls.pop("selffix", None)                     # moved into the factory's ledger
            self.save_ls(ls)
            launched = report.get("status") == "open" and X.launch(_ROOT, report["plan"], self_dir, sys.executable)
            self.event("selffix", status=report.get("status"), reason=self.rs(
                "%s: %s" % (report.get("cls"), report.get("plan") or report.get("why") or ""), 300),
                model=self.rs(asked.get("model") or None), tokens=asked.get("tokens"), launched=launched or None)
        except Exception as e:
            self.err("selffix", e)

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

    def _not_code_set(self, ls, bid, why, digest) -> None:
        """The ONE writer of the not_code book (the head's answer and the triage's structural cut, <id>)."""
        ls.setdefault("not_code", {})[bid] = {
            "hash": digest, "reason": ("не код: " + self._scrub(F.redact(str(why))))[:200],
            "until": self.clock() + self.cfg.not_code_term_s}
        ls["holds"].pop(bid, None)
        ls.get("hold_hash", {}).pop(bid, None)

    def _not_code_known(self, ls, now) -> set:
        """Rows of the not_code book whose term is live and whose text is unchanged; the rest leave the book."""
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
                                           "context_targets", "depends_on", "port_from")
                  if ans.get(k) is not None}
        kind = tasks[tid].kind if tid in tasks else (ans.get("kind") or "code")
        if ans.get("accept"):
            return self._accept_answer(tid, bid, state, note)
        if ans.get("reject"):
            if tid in tasks and note and tasks[tid].privacy_safe and not tasks[tid].only_opus:
                self._check_note(raw_note)
            return self._reject_answer(tid, bid, state, note)
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
        (one atomic idempotent writer); fac-* never, and a row without a commit sha never (closed by the head, a duplicate)."""
        sha = row.get("commit")
        if not bid or not sha or str(bid).lower().startswith("fac-"):
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
                try:
                    tasks, state = self.load()
                except Exception as e:      # a busy plan lock: the refresh waits for the next minute, it is no fault
                    if type(e).__name__ != "LockBusy":
                        raise
                    return
                rows = {tid: {"status": r.get("status"), "tests": list(tasks[tid].tests) if tid in tasks else [],
                              "base_red": r.get("base_red")} for tid, r in state["tasks"].items()}
                got = AF.refresh_from_tasks(self._sweep_dir(), rows)
                if got and (got["green"] or got["red"]):
                    self.event("sweep", status="refreshed", reason="green=%d red=%d" % (len(got["green"]), len(got["red"])))
            if self.sweep_fn is None or self._sw is not None or self._ending():
                return
            ls = ls or self.ls()
            if not AF.sweep_due(ls.get("sweep"), self.base_sha, now, self.cfg.sweep_every_s):
                return
            out = self._sweep_dir()
            latest = AF.latest_sweep(out) if out.is_dir() else None
            prev = sorted(AF.read_sweep(latest)) if latest is not None else []
            ls["sweep"] = {"sha": self.base_sha, "at": now, "prev": dict(ls.get("sweep") or {})}
            self.save_ls(ls)
            fn, wt = self.sweep_fn, self.cfg.worktree
            self._sw = Prefetch("sweep", lambda: AF.run_cloud_sweep(fn, wt, out, previous=prev), {})
            self._sw.thread.start()
            self.event("sweep", status="started", reason="cloud sweep of %d guard files" % len(prev), base_sha=self.base_sha)
        except Exception as e:
            self.err("sweep", e)

    @staticmethod
    def _closes_row(task, parents=None) -> bool:
        """A promoted task closes its backlog row only when it is the whole row's code task: a test sub-task or one part of
        a cut row shares the backlog ID but proves nothing about the row (the parents path closes a cut row)."""
        return (task is not None and getattr(task, "kind", "code") == "code"
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

    def _reject_answer(self, tid, bid, state, note) -> dict:
        if not tid or tid not in state["tasks"]:
            raise F.InvalidPlan("reject needs a known task (--task-id)")
        status = state["tasks"][tid]["status"]
        if status != "PROMOTED":
            raise F.InvalidPlan("only a PROMOTED task can be rejected (it is %s)" % status)
        ls = self.ls()
        if tid in (ls.get("accepted") or {}):
            raise F.InvalidPlan("task %s is already accepted" % tid)
        row = state["tasks"][tid]
        ls.setdefault("rejected", {}).setdefault(tid, []).append(row.get("commit"))
        self.save_ls(ls)

        def reset(st):
            r = st["tasks"][tid]
            if r["status"] != "PROMOTED":
                raise F.InvalidPlan("only a PROMOTED task can be rejected (it is %s)" % r["status"])
            r.update(status="READY", attempts=0, commit=None, lease=None, deadline=None)
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

    def _ready_topup(self, state, tasks, ls, now) -> bool:
        """<id>: READY below cfg.ready_target and the backlog may give more: the next portion is prefetched at once, without
        the empty-portion term (triage_retry_s) and without READY having to be empty. A portion that gave nothing doubles
        the wait (up to triage_retry_s), so an exhausted backlog is not read every minute. Rows of the not_code book stay
        known (never offered). True when a prefetch started."""
        cfg = self.cfg
        try:
            if cfg.ready_target <= 0 or self._bg is not None or self._ending() or not cfg.backlog.exists():
                return False
            ready = sum(1 for r in state["tasks"].values() if r.get("status") == "READY")
            if ready >= cfg.ready_target:
                return False
            wait = min(cfg.ready_triage_s * 2 ** int(ls.get("ready_triage_idle") or 0), cfg.triage_retry_s)
            if now - float(ls.get("ready_triage_at") or 0) < wait:
                return False
            ls["ready_triage_at"] = now
            return self._triage_prefetch(state, tasks, ls, now, limit=max(cfg.triage_limit, cfg.ready_target - ready), topup=True)
        except Exception as e:                     # an aid: it never stops the loop
            self.err("ready top-up", e)
            return False

    def _stalled_path(self) -> Path:
        return self.dir / "stalled_tasks.json"

    def _stalled(self) -> dict:
        """<id> rule 3 book {"quarantine": {task id: record}, "slice": {backlog id: record}}. Its own file, not loop_state:
        the pass that accounts a result saves its older copy of the loop state after the learning step."""
        try:
            book = json.loads(self._stalled_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            book = {}
        book = book if isinstance(book, dict) else {}
        for key in ("quarantine", "slice"):
            if not isinstance(book.get(key), dict):
                book[key] = {}
        return book

    def _quarantined(self) -> set:
        """<id> rule 3: task ids that get no more attempts (quarantine record, or sliced into one-file parts)."""
        book = self._stalled()
        out = set(book["quarantine"])
        out |= {str(rec.get("task")) for rec in book["slice"].values() if isinstance(rec, dict) and rec.get("task")}
        return out

    def _stall(self, tid, tasks, state, sig, tier, rkey) -> None:
        """<id> rule 3: the same failure again after the tier was raised ESC_FAILS times: no more attempts. A task of 2+
        files goes to the slicer (ls['slice'][backlog_id]: the next triage cuts its row into one-file parts); any other
        goes to a quarantine record with the reason. Either way the row is FAILED and never requeued."""
        task = tasks.get(tid)
        row0 = state["tasks"].get(tid) or {}
        bid = str(row0.get("backlog_id") or (task.backlog_id if task else "") or "")
        cls = self._reason_class(rkey)
        book = self._stalled()
        now = self.clock()
        files = list(task.touch_files) if task else []
        slice_it = bool(bid) and len(files) >= 2 and not (task and (task.only_opus or not task.privacy_safe))
        if slice_it:
            book["slice"][bid] = {"task": tid, "reason": cls, "at": now}
            reason = ("sliced:" + cls)[:80]
        else:
            book["quarantine"][tid] = {"backlog_id": bid, "tier": tier, "reason": cls, "sig": sig[:120], "at": now}
            reason = "quarantine"
        F.save_atomic(self._stalled_path(), book)

        def settle(st):
            row = st["tasks"].get(tid)
            if row is None:
                return
            row.update(status="FAILED", reason=reason, lease=None, deadline=None)
            for key in ("pending_review", "candidate", "not_before", "began", "blocked_reason"):
                row.pop(key, None)
        self._tx(settle)
        self.event("route", task_id=tid, backlog_id=bid or None, status="sliced" if slice_it else "quarantined",
                   reason=self.rs(cls, 80), tier_from=tier, signature=self.rs(sig, 120))

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

    def _triage_prepare(self, state, tasks, ls, now, quotas=None) -> dict:
        cfg = self.cfg
        fn = self.triage_fn
        if fn is None:
            from tools.agent_factory_import import triage_portion as fn
        known = {r.get("backlog_id") for r in state["tasks"].values() if r.get("backlog_id")}
        known |= {t.backlog_id for t in tasks.values() if t.backlog_id}
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
        slicing = {b for b in self._stalled()["slice"] if b not in (ls.get("parents") or {})}
        known -= slicing                                    # <id>: a row whose task stalled is imported again, cut into one-file parts
        refeed = self._refeed_pick(state, tasks, ls)        # owner rule 3: a red guard is a new method for a failed row
        known -= set(refeed)
        t0 = self.clock()
        kwargs = dict(backlog_path=cfg.backlog, head_root=cfg.worktree,
                      known_backlog_ids=known, limit=cfg.triage_limit)
        if _accepts(fn, "profile_attempts"):
            kwargs["profile_attempts"] = dict(ls.get("profile_attempts") or {})
        if _accepts(fn, "known_parts"):
            kwargs["known_parts"] = self._known_parts()
        scopes = {b: s for b, s in (ls.get("head_scope") or {}).items() if b not in known and isinstance(s, dict)}
        if scopes and _accepts(fn, "scopes"):
            kwargs["scopes"] = scopes
        if slicing and _accepts(fn, "force_slice"):
            kwargs["force_slice"] = slicing
        if _accepts(fn, "trace"):
            kwargs["trace"] = self._guard_traces(state)
        if _accepts(fn, "ask"):
            kwargs["ask"] = self._locate_ask(ls, quotas)
        if refeed and _accepts(fn, "refeed"):
            kwargs["refeed"] = set(refeed)
        else:
            refeed = {}
        return {"fn": fn, "kwargs": kwargs, "mtime": mtime, "dropped": dropped, "t0": t0, "now": now, "refeed": refeed}

    def _refeed_pick(self, state, tasks, ls) -> dict:
        """{backlog_id: {guards, supersede}} of the rows to re-feed by their red guard (tools.factory_autofeed.refeed_rows);
        a row the loop holds or closed is left alone. A fault is no re-feed."""
        try:
            from tools import factory_autofeed as AF
            ids = {str(r.get("backlog_id") or "").split("#")[0] for r in state["tasks"].values()} - {""}
            guards = AF.guard_map(AF.load_sweep(self.cfg.worktree), sorted(ids))
            got = AF.refeed_rows(state["tasks"], tasks, guards, ls.get("refed") or {})
            return {b: v for b, v in got.items() if b not in ls["holds"] and b not in ls["closed"]}
        except ImportError:          # the public mirror withholds the feed module: no re-feed there
            return {}
        except Exception as e:
            self.err("refeed pick", e)
            return {}

    def _refeed_book(self, ctx, portion, added, ls) -> None:
        """The rows whose _g task was really added: one re-feed per row per guard file is recorded, and the old READY code tasks
        that waited on a FAILED dependency of the row are closed (FAILED superseded_by_guard, no more attempts)."""
        refeed = ctx.get("refeed") or {}
        done = [t["backlog_id"] for t in portion if isinstance(t, dict) and str(t.get("id", "")).endswith(F.REFEED_SUFFIX)
                and t.get("backlog_id") in refeed and t["id"] in set(added)]
        if not done:
            return
        stalled = self._stalled()
        close = []
        for bid in done:
            ls.setdefault("refed", {})[bid] = sorted(set(ls.get("refed", {}).get(bid, [])) | set(refeed[bid]["guards"]))
            close += refeed[bid]["supersede"]
            for tid in refeed[bid]["supersede"]:
                stalled["quarantine"][tid] = {"backlog_id": bid, "reason": "superseded_by_guard", "at": self.clock()}
        F.save_atomic(self._stalled_path(), stalled)

        def settle(st):
            for tid in close:
                row = st["tasks"].get(tid)
                if row is not None and row.get("status") == "READY":
                    row.update(status="FAILED", reason="superseded_by_guard", lease=None, deadline=None)
                    for key in ("pending_review", "candidate", "not_before", "began", "blocked_reason"):
                        row.pop(key, None)
        self._tx(settle)
        self.event("triage", status="refed", reason="guard re-feed of %s; closed %d waiting tasks" % (
            ",".join(done)[:100], len(close)))

    def _guard_traces(self, state) -> dict:
        """<id>: {backlog_id: [(rel, qualname, line)]} - the cloud trace of the failing guard the gate returned (base_red.result.path
        of the row's task), for the slicer to narrow each one-file part's guard to its file's functions."""
        out = {}
        for row in (state.get("tasks") or {}).values():
            try:
                path = F.get_trace(self.cfg.state_dir, row)      # <id>: the trace lives beside the state
                bid = row.get("backlog_id")
                if bid and path:
                    out[str(bid)] = [(str(c[0]), str(c[1]), int(c[2])) for c in path][:400]
            except (TypeError, ValueError, IndexError, AttributeError):
                continue
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
        self._take_parents(res.get("parents"), ls)
        try:
            self._refeed_book(ctx, portion, added, ls)
        except Exception as e:
            self.err("refeed book", e)
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
        progress = bool(added) or bool(new_holds)
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

    def _known_parts(self) -> dict:
        """{child backlog id: [files of that part]} of the parts that are already tasks (fields parent/part of the
        plan rows; ids are never parsed): lets the triage see a changed file layout of a known part."""
        try:
            rows = json.loads(self.plan_path.read_text(encoding="utf-8")).get("tasks") or []
        except (OSError, ValueError, AttributeError) as e:
            self.err("known_parts: plan unreadable", e)
            return {}
        out = {}
        for r in rows:
            if (isinstance(r, dict) and r.get("parent") and r.get("part") and r.get("backlog_id")
                    and r.get("kind", "code") != "unit_test" and isinstance(r.get("touch_files"), list)):
                out[str(r["backlog_id"])] = [str(x) for x in r["touch_files"]][:20]
        return out

    def _take_parents(self, records, ls: dict) -> None:
        """Remember the cut rows (E's ``parents`` records) until every code part is DONE/PROMOTED."""
        if not isinstance(records, list):
            return
        if not isinstance(ls.get("parents"), dict):
            ls["parents"] = {}
        book = ls["parents"]
        for rec in records:
            try:
                bid = str(rec["backlog_id"])
                code = [str(x) for x in rec["code_tasks"]]
                kids = [str(x) for x in rec["children"]]
                tests = [str(x) for x in rec.get("test_tasks") or []]
            except (KeyError, TypeError):
                continue
            if bid in ls["closed"]:
                continue
            if (not bid or not code or len(bid) > 64 or len(code) > 20 or len(kids) > 20
                    or (bid not in book and len(book) >= self.PARENTS_MAX)):
                self.event("triage", status="parent_dropped", reason="cut row %s is not remembered (%s)" % (
                    self.rs(bid, 64), "table full" if len(book) >= self.PARENTS_MAX else "bad record"))
                continue
            book2 = self._stalled()
            if book2["slice"].pop(bid, None) is not None:   # <id>: the stalled row is cut: its slice request is used up
                F.save_atomic(self._stalled_path(), book2)
            book[bid] = {"backlog_id": bid, "parts": len(code), "children": kids,
                         "code_tasks": code, "test_tasks": tests[:20]}      # idempotent merge by backlog id
            files = rec.get("files")
            if isinstance(files, (list, dict)) and len(files) <= 20:
                book[bid]["files"] = files

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
        md = Path(self.cfg.backlog).read_bytes().decode("utf-8-sig")
        return {r["backlog_id"]: sha256(r[field].encode("utf-8")).hexdigest()[:16]
                for r in imp.parse_section4(md)}

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

    def _write_reconcile(self, tasks, state, ls, now) -> None:
        """<id> («Утром сверка с бэклогом: ни одной забытой задачи»): <state>/reconcile.json maps EVERY backlog row
        to where the loop holds it, with a reason and a term: the queue (the task state wins), a triage hold, the
        closed book, a cut parent, a stale or skipped row (seen, with its term), a deferred row, a row whose state
        wording is not recognised, or a row the triage has not reached yet. Ids and the loop's own words only."""
        try:
            self._write_reconcile_now(tasks, state, ls, now)
        except Exception as e:                       # the report never stops the loop
            self.err("reconcile", e)

    def _write_reconcile_now(self, tasks, state, ls, now) -> None:
        from tools import factory_requeue
        rows = {}
        try:
            from tools import agent_factory_import as imp
            md = Path(self.cfg.backlog).read_bytes().decode("utf-8-sig")
            backlog = [(r["backlog_id"], bool(r.get("open", True))) for r in imp.parse_section4(md)]
        except Exception as e:
            self.err("reconcile: backlog unreadable", e)
            backlog = []
        try:
            ledger = json.loads((self.cfg.state_dir / "requeue_ledger.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            ledger = {}
        order = {s: i for i, s in enumerate(self.RECONCILE_ORDER)}
        for tid, row in sorted(state["tasks"].items()):
            t = tasks.get(tid)
            bid = row.get("backlog_id") or (t.backlog_id if t else "")
            if not bid:
                continue
            old = rows.get(bid)
            if old and order.get(old["state"], 99) <= order.get(row["status"], 99):
                continue
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

        def put(bid, state_name, reason, until=None):
            if bid and bid not in rows:
                rows[bid] = {"state": state_name, "reason": self.rs(reason or state_name, 200), "until": until}
        for bid, q in (ls.get("holds") or {}).items():
            put(bid, "hold", q)
        for bid in ls.get("closed") or {}:
            put(bid, "closed", "закрыта в книге петли")
        for bid, rec in (ls.get("parents") or {}).items():
            put(bid, "parts", "разрезана на %s частей: %s" % (rec.get("parts"), ",".join(rec.get("children") or [])))
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
                    self._iso(float(rec.get("until") or now)))
            else:
                put(bid, "stale" if rec == "stale" else "seen", "пропущена триажем (без срока, старая запись)", None)
        for bid, why in (ls.get("deferred") or {}).items():
            put(bid, "deferred", why)
        for bid, st in (ls.get("skipped_unknown") or {}).items():
            put(bid, "unknown_state", "формулировка состояния не распознана: " + (st or "?"))
        for bid, is_open in backlog:
            if is_open:
                put(bid, "untriaged", "триаж ещё не дошёл до строки")
            else:
                put(bid, "closed_in_backlog", "закрыта в бэклоге")
        counts = {}
        for r in rows.values():
            counts[r["state"]] = counts.get(r["state"], 0) + 1
        body = {"backlog_rows": len(backlog), "counts": dict(sorted(counts.items())), "rows": dict(sorted(rows.items()))}
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

    def _estimate(self) -> int:
        """What one more worker may need: the <id> of the job peaks of the last EST_KEEP workers (a fixed guess until
        EST_MIN_SAMPLES are measured)."""
        peaks = sorted(self._peaks)
        if len(peaks) < EST_MIN_SAMPLES:
            return EST_DEFAULT_BYTES
        return peaks[min(len(peaks) - 1, int(len(peaks) * 0.9))]

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

    def _capacity(self, task) -> str:
        """'' when one more worker may start now, else the reason. K is nothing but this: free RAM (the floor, plus what
        the live workers have not used yet, plus one more estimate) and free quota (first calls that can still be
        booked beyond those the live workers have not booked). With no live worker only today's rules count. While the cloud
        gate answers (``cloud_fn``) the checks of a candidate run there and hold no slot: RAM is not counted per worker
        (only CLOUD_FLOOR of the machine stays) and the pool takes up to factory_cloud_gate.MAX_LIVE tasks."""
        self._headroom_seen = None
        free = self.free_ram_fn()
        cloud = _cloud_up(getattr(self, "cloud_fn", None))   # the checks of a candidate run in the cloud: no RAM budget
        floor = CLOUD_FLOOR if cloud else self._floor(task)
        if free < floor:
            return "low_ram"
        live = list(self.pool.workers.values())
        if not live:
            return ""
        if cloud and len(live) >= factory_cloud_gate.MAX_LIVE:
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
        if not cloud:
            est = self._estimate()
            pending = 0
            for w in live:
                seen = (w.owned.peak_bytes() if w.owned is not None else None) or 0
                pending += max(0, est - seen)    # the memory a live worker has not used yet is not free
            if free - pending < floor + est:
                return "low_ram"
        try:
            state = self.load()[1]
            unbooked = sum(1 for w in live if not (state["tasks"].get(w.tid, {}).get("began") or {}).get("booked"))
            self._headroom_seen = self._headroom(task, state)
        except (OSError, ValueError, KeyError, TypeError):
            return "quota"                       # the quota is unknown: no second worker
        except Exception as e:
            self.err("capacity", e)
            return "quota"
        return "quota" if self._headroom_seen <= unbooked else ""

    def _headroom(self, task, state) -> int:
        """First model calls that could be booked now on the code route (0 when the quota is unknown)."""
        path = Path(self.cfg.channels)
        configured = json.loads(path.read_text(encoding="utf-8"))["channels"]
        CH.validate(configured)
        tokens = int(getattr(task, "estimated_tokens", 0) or 0)
        order = CH.route_order(configured, "code", 1, tokens) or CH.route_order(configured, "code", 1, 0)
        env = {**os.environ, **self.extra_env}
        quota = state.get("channel_quotas") if isinstance(state.get("channel_quotas"), dict) else {}
        seen = quota_ledger.view(quota, quota_ledger.others(path.resolve().parent / "quota", str(self.ckpt)))
        live = CH.usable(order, seen, env)
        if not live:
            return 0
        return CH.headroom(order, seen, min(tokens, max(c["tpm"] for c in live)), env)

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
        os.replace(tmp, target)
        return target

    def _prune_snapshots(self) -> None:
        """Every snapshot but the newest and those a live worker reads goes (one that cannot be deleted waits)."""
        try:
            keep = {r.resolve() for r in self.pool.roots()}
            if self.base_sha:
                keep.add((self.snap_dir / self.base_sha[:12]).resolve())
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

    def _admit(self, tid: str, tasks, ls):
        """Claim ``tid`` in one transaction and start its runner. 1 = started, 0 = not runnable any more, an Outcome =
        the iteration ends here (a locked state is WAIT state_locked; an exhausted budget is today's WAITING_CHANNEL)."""
        cfg = self.cfg
        small, large, review = cfg.small_model, cfg.large_model, cfg.review_model
        exps = None
        try:
            exps = self._task_experiments(tid, tasks.get(tid), ls)
            coder = exps["coder_model"]                       # <id>: the task's arm is the code model
            small = large = coder
            if review == coder:                               # the review model must differ from the code model
                review = next(m for m in EXPERIMENTS["coder_model"] if m != coder)
        except Exception as e:
            self.err("experiments arm", e)
        t_claim = time.monotonic()
        budget = self._call_budget()
        base = self.base_sha
        try:
            with self.txn(self.CLAIM_WAIT_S) as (tasks2, state):
                state["max_model_calls"] = budget             # the day's capacity: the loop claims, so the loop writes it
                token = F.acquire(tasks2, state, tid, now=self.clock(), charge=False)
        except F.BudgetExhausted:
            res = {"status": "WAITING_CHANNEL", "reason": "budget_exhausted", "task_id": tid, "task": tid, "calls": [],
                   "stages": {}, "events": [], "infra": False, "wait_s": round(F.seconds_to_local_midnight(), 1)}
            return self._account(Worker(slot=-1, tid=tid, token=None, base_sha=base, exps=exps, hint=tid), res=res)
        except F.LockBusy:
            return Outcome(sleep=60, action="WAIT", reason="state_locked")
        except F.InvalidPlan:                                  # no longer runnable (another writer): choose again
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
                "--max-model-calls", str(budget), "--base-sha", base,
                "--port-repo", str(cfg.repo),    # the runner's --root is a plain copy: a port task's old commit lives here
                "--execute", "--ack-host-access-risk"]
            if (exps or {}).get("small_follow_up") in EXPERIMENTS["small_follow_up"]:
                cmd += ["--small-follow-up", exps["small_follow_up"]]
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
                                   k=len(self.pool.workers) + 1, free_ram=free, exps=exps, hint=tid))
        self._max_k = max(self._max_k, len(self.pool.workers))
        self._k_sum, self._k_n = self._k_sum + w.k, self._k_n + 1
        return 1

    def _reap(self, w: Worker, timed_out: bool) -> dict:
        """The worker's result. Its job closes (the whole tree dies); on a timeout the pass is NO_RESULT."""
        rc = None
        if w.owned is not None:
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
        if w.peak:
            self._peaks = (self._peaks + [w.peak])[-EST_KEEP:]
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
        self._run_exps = w.exps
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
                   error_type=self.rs(res.get("error_type")),
                   channel_reason=self.rs(res.get("channel_reason")),
                   worker=w.slot, pid=getattr(w.owned, "pid", None), lease=(w.token or "")[:8] or None, k=w.k,
                   free_ram_mb=int(w.free_ram / 2 ** 20) or None,
                   peak_mb=round(w.peak / 2 ** 20, 1) if w.peak else None,
                   queue_s=round(w.t_start - w.t_claim, 3) if w.t_start else None,
                   slot_wait_s=(res.get("stages") or {}).get("slot_wait_s"))
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
                       cool_reason=self.rs(c.get("cool_reason")), cool_s=self._num(c, "cool_s"))
        for name, secs in (res.get("stages") or {}).items():
            span = "gate" if str(name).startswith(("gate", "red_before", "neighbors")) else (
                "review" if str(name).startswith("review") else "run")
            self.event(span, task_id=tid or None, backlog_id=bid, stage=str(name), dur_s=secs,
                       status="ok", base_sha=base)
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
            rows = [r for r in self._telemetry_rows() if r.get("span") == "run" and r.get("attempt")
                    and r.get("reason") and r.get("task_id") in public]
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
            stalled, tier0 = False, None
            if repeat:                        # <id> rule 3: the same failure again after the tier was raised
                tier0 = (state["tasks"].get(tid) or {}).get("tier_floor")
                if tier0 in TIER_ORDER and tier0 != TIER_ORDER[0]:
                    esc = mem.setdefault("esc", {})
                    old = esc.get(tid) if isinstance(esc, dict) else None
                    n = (old.get("n", 0) if isinstance(old, dict) and old.get("sig") == sig else 0) + 1
                    if isinstance(esc, dict):
                        esc[tid] = {"sig": sig, "n": n}
                    stalled = n >= self.ESC_FAILS
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
            if stalled and tid in state["tasks"]:
                self._stall(tid, tasks2, state, sig, tier0, rkey)
                return
            if repeat and tid in state["tasks"]:
                note = F.REPEAT_MARK + " " + (words or self._reason_class(rkey))
                marks = {}

                def raise_floor(st):
                    row = st["tasks"][tid]
                    F.add_feedback(st, tid, "gate", note)
                    cur = row.get("tier_floor") if row.get("tier_floor") in TIER_ORDER else TIER_ORDER[0]
                    new = TIER_ORDER[min(TIER_ORDER.index(cur) + 1, len(TIER_ORDER) - 1)]
                    row["tier_floor"] = new
                    marks.update(cur=cur, new=new)
                self._tx(raise_floor)
                cur, new = marks["cur"], marks["new"]
                # the runner does not read tier_floor yet (backlog fac-tier-floor): "requested", never a false "raised"
                self.event("route", task_id=tid, status="requested", reason="repeated_error",
                           signature=self.rs(sig, 120), tier_from=cur, tier_to=new, applied=False)
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
        """SCOPE_MAX_FILES, or the paid tier's limit for a task whose tier_floor is 'escalation'."""
        row = ((state or {}).get("tasks") or {}).get(tid) or {}
        if _paid_coder is None or row.get("tier_floor") != "escalation":
            return SCOPE_MAX_FILES
        try:
            return max(SCOPE_MAX_FILES, int(_paid_coder.files_limit(int(row.get("attempts") or 0), "escalation")))
        except Exception:  # noqa: BLE001 - an extra: without it the free limit stands
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
    def _after_merge(self, tid: str, sha: str, *, recovered: bool = False,
                     base_sha: str | None = None, head: str | None = None,
                     dur_s: float | None = None) -> None:
        """Complete the durable post-merge effects on both normal and recovery paths."""
        tasks, state = self.load()
        if self._closes_row(tasks.get(tid), self.ls().get("parents")):
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
            self._after_merge(tid, done_sha, recovered=True, base_sha=fields["base_sha"],
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
                near = self._own_neighbours(tid, tasks.get(tid), base, cur)
                if near:
                    moved, keep = "рядом сдвинулось (свой promote): " + ", ".join(near[:5]), True
        if moved:
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
        self._after_merge(tid, sha, base_sha=fields["base_sha"], head=cur,
                          dur_s=round(self.clock() - t0, 3))
        self._clear_requeues(ls, tid)
        ls.get("promote_fail", {}).pop(tid, None)
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
        try:
            return git_run(repo, "show", rev + ":" + name)
        except subprocess.CalledProcessError:
            return ""

    def _merge_file(self, repo, base, name, dst: Path, cand: Path) -> tuple[str, bool]:
        """Candidate file onto the branch file as a 3-way merge from the candidate's base (never a blind copy)."""
        ours = dst.read_text(encoding="utf-8", errors="replace")
        theirs = cand.read_text(encoding="utf-8", errors="replace")
        b = self._blob(repo, base, name)
        if not b and ours != theirs:
            return ours, True     # both sides added the file
        return three_way_merge(b, ours, theirs)

    def _merge_verdict(self, repo, base, cur, hit, src, rel) -> str:
        """Why the candidate goes back: would a 3-way merge onto the new HEAD be clean (re-gate) or conflict."""
        bad = []
        for name in hit:
            if name not in rel:
                continue
            try:
                ours = self._blob(repo, cur, name)
                theirs = src.joinpath(*name.split("/")).read_text(encoding="utf-8", errors="replace")
                if three_way_merge(self._blob(repo, base, name), ours, theirs)[1]:
                    bad.append(name)
            except Exception:
                bad.append(name)
        return "3-way: конфликт слияния: " + ", ".join(bad[:5]) if bad else "3-way: слияние чистое, нужен перепрогон ворот"

    def _requeue_review(self, state, tid, note, keep) -> bool:
        """REVIEW -> READY. ``keep``: the approved candidate resumes at the gates on the new base, no coder call."""
        had = isinstance(state["tasks"][tid].get("candidate"), dict)
        F.requeue(state, tid, note, keep_candidate=keep)
        return keep and had

    def _own_neighbours(self, tid, task, base: str, cur: str) -> list:
        """Files of the factory's OWN promotes in base..cur that touch what this candidate was gated against: its tests
        and their one-hop neighbours, through everything the changed files affect. Two candidates that were built
        together are tested together by the gates of the second one on the new base."""
        if task is None:
            return []
        log = git_run(self.cfg.repo, "log", "--format=%H %s", base + ".." + cur)
        own = [x.split(" ", 1)[0] for x in log.splitlines() if x.split(" ", 1)[-1].startswith("factory(")]
        if not own:
            return []
        files = set()
        for sha in own:
            files.update(x for x in git_run(self.cfg.repo, "show", "--name-only", "--format=", sha).split("\n") if x)
        from tools import affected_tests
        from tools import agent_factory_runner as R
        graph = affected_tests.Graph(Path(self.mirror))
        found, _, _ = affected_tests.affected(sorted(files), radius=None, g=graph)
        mine = set(task.tests) | set(R.neighbor_tests(Path(self.mirror), task)) | set(task.touch_files) | set(task.read_files)
        return sorted(set(found) & mine) or sorted(files & mine)

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
        bad = factory_gate.weakening_violations(self.mirror, texts, task.kind)   # no names: the loop never
        return "; ".join(bad[:3]) if bad else ""                                  # merges the factory's own code

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
            tracked = subprocess.run(["git", "-C", str(wt), "ls-files", "--error-unmatch", "--", r],
                                     capture_output=True).returncode == 0
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
            F.save_atomic(self.stats_path, stats)
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

    def _idle_requeue(self, tasks, state, now):
        """<id> (live 20.11: HOLD only_opus_or_blocked with 7 FAILED tasks of a retryable class that only a new factory
        version would have given back): nothing runnable, so every F.BLOCK_TERM_S the FAILED/BLOCKED tasks whose last
        return is older than cfg.requeue_term_s go back through the answer box (factory_requeue, max 3 shared). Only
        Opus and private tasks are never given back to an external model. Outcome, or None (nothing given back)."""
        from tools import factory_requeue
        if not any(r.get("status") in ("FAILED", "BLOCKED") for r in state["tasks"].values()):
            return None
        ls = self.ls()
        if now - float(ls.get("requeue_at") or 0) < F.BLOCK_TERM_S:
            return None
        ls["requeue_at"] = now
        self.save_ls(ls)
        skip = {tid for tid, t in tasks.items() if t.only_opus or not t.privacy_safe}
        skip |= set(state["tasks"]) - set(tasks)    # no plan row: privacy unknown, never given to an external model
        skip |= self._quarantined()                 # <id> rule 3: no more attempts
        # 21.11 rule 3: a jam (nothing runnable, nothing running) lifts the max_times ceiling and the unclassified skip
        # for the tasks above (one round per jam episode, factory_requeue.jam_of); FAILED test tasks that READY code
        # tasks wait for come first. The skip above (owner rules, quarantine) is never lifted.
        runnable = [] if self.pool.workers else F.ready(tasks, state, now=now)
        jam = factory_requeue.jam_of(state, runnable) and not self.pool.workers
        blocking = {dep for tid, t in tasks.items() if (state["tasks"].get(tid) or {}).get("status") == "READY"
                    for dep in t.depends_on if (state["tasks"].get(dep) or {}).get("status") in ("FAILED", "BLOCKED")}
        try:
            done = factory_requeue.run(self.cfg.state_dir, _ROOT.name, skip=skip, check=self._check_note,
                                       now=now, term_s=self.cfg.requeue_term_s, jam=jam, blocking=blocking)
        except Exception as e:
            self.err("idle requeue", e)
            return None
        if not done:
            return None
        text = "term %ds: %s" % (self.cfg.requeue_term_s, ",".join(done))
        self.event("loop", action="REQUEUE", status="ok", reason=text[:200])
        return Outcome(sleep=1, action="REQUEUE", reason=self.rs(text, 200))

    def _requeue_on_new_version(self) -> None:
        """<id>: a new factory version gets one more try at the FAILED/BLOCKED tasks whose failure class it may have
        fixed (tools/factory_requeue.py); the answers go through the Opus answer box; a fault never stops the loop."""
        from tools import factory_requeue
        try:
            tasks, _ = self.load()
            skip = {tid for tid, t in tasks.items() if t.only_opus or not t.privacy_safe} | self._quarantined()
            done = factory_requeue.run(self.cfg.state_dir, _ROOT.name, skip=skip, check=self._check_note)
        except Exception as e:
            self.err("requeue", e)
            return
        if done:
            self.event("loop", action="REQUEUE", status="ok",
                       reason="version %s: %s" % (_ROOT.name, ",".join(done))[:200])

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
            self._requeue_on_new_version()
            self._decide_experiments()
            self._discover_keys()
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
                self._selffix()                     # at most once an hour (<id>)
                self._head_holds()                  # idle: at once, busy: every 20 min (<id>/<id>)
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
    p.add_argument("--release-private", action="store_true",
                   help="allow a public --goal for a row private by content (keys, passwords, recordings); "
                        "other rows need no flag")
    p.add_argument("--goal", help="technical wording for the coder (checked: no owner words)")
    p.add_argument("--kind", choices=("code", "unit_test"), help="for a new task from a hold")
    p.add_argument("--port", help="a port task: the old-branch commit whose behaviour it brings over (its diff is "
                                  "shown to the coder as a reference)")
    p.add_argument("--note", default="")
    a = p.parse_args(argv)
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
                                  "depends_on", "note", "close", "goal", "accept", "port_from")):
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


def _cloud_sweep_fn(a):
    """The existing cloud sweep (tools.echo_cloud.sweep), or None with --no-cloud-sweep / when the module is absent."""
    if getattr(a, "no_cloud_sweep", False):
        return None
    try:
        from tools import echo_cloud
        return echo_cloud.sweep
    except Exception:
        return None


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv and argv[0] == "answer":
        return answer_main(argv[1:])
    if argv and argv[0] == "summary":
        return summary_main(argv[1:])
    a = parse_args(argv)
    absent: list = []
    keys = load_keys(a.env_file, a.channels, absent) if a.env_file else {}
    cfg = Config(state_dir=a.state_dir, repo=a.repo, branch=a.branch, worktree=a.worktree,
                 backlog=a.backlog, channels=a.channels, until=a.until, once=a.once,
                 small_model=a.small_model, large_model=a.large_model,
                 review_model=a.review_model, env_file=a.env_file, clear_brake=a.clear_brake)
    try:
        loop = Loop(cfg, extra_env=keys, startup_notes=["no key for channel env " + n for n in absent],
                    cloud_fn=getattr(factory_cloud_gate, "available", None), sweep_fn=_cloud_sweep_fn(a), reap_fn=lambda **kw: SV.reap(procs_fn=SV.list_processes, kill_fn=SV.kill_tree, **kw))
    except ValueError as e:
        raise SystemExit(str(e))
    return loop.run()


if __name__ == "__main__":
    sys.exit(main())
