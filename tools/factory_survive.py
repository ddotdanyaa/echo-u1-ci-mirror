"""<id> overnight survivability, pure parts (every OS call is injected; tests use fake lists and clocks).

- find_orphans / reap: factory-owned children (python, pytest, node/kilo) whose command line holds a factory
  marker (the staging or state dir), older than REAP_AGE_S, that are neither the loop, nor a live worker, nor a
  descendant of one. The live voice server (port 9131) and the main Hermes trees are protected by name: they never
  match, whatever else the command line says. (<id>: an orphan pytest of 20.11 blocked work for hours.)
- rotate_tail: a log over max_bytes keeps its last lines (under keep_bytes) and the old body once as <name>.1.
- IdleWatch / heal: READY > 0 and RUNNING = 0 for IDLE_LIMIT_S -> the caller writes one event and heals the stale
  global wait and the absurd task waits (no human). Channel cooldowns are NOT touched (they are real 429s).
- supervise: restart after crashes, deadline exits and brakes; STOP and another live loop end supervision.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

REAP_AGE_S = 3 * 3600          # a runner pass lives <= one lease; a pytest/kilo older than 3 h is an orphan
REAP_EVERY_S = 300
STALE_S = 300
IDLE_LIMIT_S = 600
STALE_TASK_WAIT_S = 2 * 3600   # a task wait further away than this is not a backoff (BACKOFF_MAX_S is 30 min)
RESTART_MAX, RESTART_WINDOW_S = 5, 1800
REAPABLE_NAMES = ("python", "pythonw", "pytest", "node", "kilo")
PROTECTED = ("9131", "hermes-agent", "home\\profiles", "home/profiles", "\\appdata\\local\\hermes\\",
             "/appdata/local/hermes/", "happ", "tools.factory_loop")


def _protected(cmd: str) -> bool:
    low = cmd.lower()
    return any(p in low for p in PROTECTED)


def _kind_ok(name: str) -> bool:
    base = (name or "").lower()
    if base.endswith(".exe"):
        base = base[:-4]
    return base in REAPABLE_NAMES


def find_orphans(procs, *, now, markers, live_pids=(), self_pid=0, max_age_s=REAP_AGE_S):
    by_pid = {p["pid"]: p for p in procs}
    keep = set(live_pids) | {self_pid}

    def under_kept(p):
        seen = set()
        while p is not None and p["pid"] not in seen:
            if p["pid"] in keep:
                return True
            seen.add(p["pid"])
            p = by_pid.get(p.get("ppid"))
        return False

    marks = [m.lower() for m in markers if m]
    out = []
    for p in procs:
        cmd = p.get("cmd") or ""
        if not cmd or not marks or not _kind_ok(p.get("name", "")):
            continue
        low = cmd.lower()
        if not any(m in low for m in marks) or _protected(cmd):
            continue
        if now - float(p.get("created") or now) <= max_age_s or under_kept(p):
            continue
        out.append(p)
    return out


def reap(*, procs_fn, kill_fn, now, markers, live_pids=(), self_pid=0, max_age_s=REAP_AGE_S):
    """The pids actually killed. A failing listing or kill is swallowed: the reaper is an aid, never a crash."""
    try:
        procs = list(procs_fn())
    except Exception:
        return []
    done = []
    for p in find_orphans(procs, now=now, markers=markers, live_pids=live_pids, self_pid=self_pid,
                          max_age_s=max_age_s):
        try:
            kill_fn(p["pid"])
            done.append(p["pid"])
        except Exception:
            continue
    return done


_PS = ("Get-CimInstance Win32_Process | ForEach-Object { [pscustomobject]@{pid=[int]$_.ProcessId;"
       "ppid=[int]$_.ParentProcessId;name=$_.Name;cmd=$_.CommandLine;"
       "created=$(if($_.CreationDate){[DateTimeOffset]::new($_.CreationDate).ToUnixTimeSeconds()}else{0})} }"
       " | ConvertTo-Json -Compress")


def list_processes():
    """Windows process list (pid, ppid, name, cmd, created epoch). Raises on failure: reap() swallows it."""
    out = subprocess.run(["powershell", "-NoProfile", "-Command", _PS], capture_output=True, text=True,
                         encoding="utf-8", errors="replace", timeout=60, check=True).stdout
    data = json.loads(out or "[]")
    return [data] if isinstance(data, dict) else data


def kill_tree(pid: int) -> None:
    subprocess.run(["taskkill", "/PID", str(int(pid)), "/T", "/F"], capture_output=True, timeout=60)


def rotate_tail(path, *, max_bytes, keep_bytes) -> bool:
    path = Path(path)
    try:
        if not path.is_file() or path.stat().st_size <= max_bytes:
            return False
        data = path.read_bytes()
        tail = data[-keep_bytes:]
        nl = tail.find(b"\n")
        tail = tail[nl + 1:] if 0 <= nl < len(tail) - 1 else tail
        one = path.with_name(path.name + ".1")
        os.replace(path, one)
        path.write_bytes(tail)
        return True
    except OSError:
        return False


class IdleWatch:
    def __init__(self, limit_s=IDLE_LIMIT_S):
        self.limit, self.since, self.fired_at = limit_s, None, None
        self.telemetry_mark, self.telemetry_at = None, None

    def stale(self, telemetry, *, now) -> bool:
        try:
            stat = Path(telemetry).stat()
            mark = (stat.st_ino, stat.st_size, stat.st_mtime_ns)
        except OSError:
            mark = None
        if self.telemetry_at is None or mark != self.telemetry_mark:
            self.telemetry_mark, self.telemetry_at = mark, now
            return False
        return now - self.telemetry_at >= STALE_S

    def observe(self, *, ready, running, now) -> bool:
        if ready <= 0 or running > 0:
            self.since = self.fired_at = None
            return False
        if self.since is None:
            self.since = now
            return False
        if now - self.since < self.limit:
            return False
        if self.fired_at is not None and now - self.fired_at < self.limit:
            return False
        self.fired_at = now
        return True


def heal(state: dict, ls: dict, *, now) -> dict:
    """Clear the loop-wide wait and the READY tasks' absurdly far waits, in place. Returns what was changed."""
    got = {"global_wait": False, "tasks": []}
    if float(ls.get("channel_until", 0) or 0) > 0:
        ls["channel_until"] = 0
        got["global_wait"] = True
    for tid, row in (state.get("tasks") or {}).items():
        nb = float(row.get("not_before") or 0)
        if row.get("status") == "READY" and nb > now + STALE_TASK_WAIT_S:
            row.pop("not_before", None)
            got["tasks"].append(tid)
    return got


def should_restart(rc: int) -> bool:
    """Only another live loop (4) ends supervision independently of STOP."""
    return rc != 4


def supervise(cmd, *, run_fn, stop_exists, clock=time.time, sleep=time.sleep, note=print,
              max_restarts=RESTART_MAX, window_s=RESTART_WINDOW_S) -> int:
    """Keep the loop alive; a crash loop retries every two minutes instead of giving up."""
    starts: list = []
    cmd = list(cmd)
    rc = 0
    while not stop_exists():
        error = None
        try:
            rc = run_fn(cmd)
        except (OSError, subprocess.SubprocessError) as e:
            rc, error = 1, type(e).__name__
        if not should_restart(rc) or stop_exists():
            return rc
        if rc == 0:
            # The absolute deadline belongs to the completed run. Keeping it would make every successor exit.
            args, next_cmd = iter(cmd), []
            for arg in args:
                if arg == "--until":
                    next(args, None)
                elif not arg.startswith("--until="):
                    next_cmd.append(arg)
            cmd = next_cmd
        now = clock()
        starts = [t for t in starts if now - t < window_s] + [now]
        crash_loop = len(starts) >= max_restarts
        note(json.dumps({"span": "survive", "status": "crash_loop" if crash_loop else "restart",
                         "rc": rc, "error": error, "restarts": len(starts), "window_s": window_s}))
        sleep(120 if crash_loop else 10)
    return rc


def run_watched(cmd, *, telemetry, clock=time.time, sleep=time.sleep, kill_fn=kill_tree):
    """Watch the child's telemetry independently of its threads and terminate a silent process tree."""
    proc = subprocess.Popen(cmd)
    watch = IdleWatch()
    while proc.poll() is None:
        if watch.stale(telemetry, now=clock()):
            try:
                kill_fn(proc.pid)
                return proc.wait(timeout=5)
            except (OSError, subprocess.SubprocessError):
                # Never launch a replacement until this tree has exited. A failed taskkill is retried.
                pass
        sleep(1)
    return proc.wait()


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) >= 4 and argv[0] == "supervise" and argv[2] == "--":
        stop = Path(argv[1])
        telemetry = stop.parent / "telemetry.jsonl"
        def note(message):
            print(message, flush=True)
            try:
                row = json.loads(message)
                row["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
                with telemetry.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(row) + "\n")
            except (OSError, ValueError):
                pass
        return supervise(argv[3:], run_fn=lambda c: run_watched(c, telemetry=telemetry),
                         stop_exists=stop.exists, note=note)
    print("usage: factory_survive supervise STOPFILE -- cmd...", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
