"""The runner's state lock names its holder; the loop clears a dead holder's lock before EVERY runner pass.

Restart check 19.11 17:42: the loop was killed during a pass, the new loop started seconds later, the anonymous lock
was younger than LOCK_STALE_S (the age rule ran only at start) and the runner refused every pass with
"another controller or stale lock owns state"."""
import os
import subprocess
import sys
import time

from tools import agent_factory as F
from test_factory_loop import Env, env, task_row  # noqa: <id>


def _lock(e):
    return e.state_dir / "state.json.lockdir"


def _dead_pid():
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


def _cleared(e):
    return [x for x in e.events() if x.get("reason") == "stale_lockdir"]


def test_a_dead_holders_fresh_lock_is_cleared_before_the_next_pass(env):
    loop = env.loop()
    lock = _lock(env)
    lock.mkdir()
    (lock / F.LOCK_OWNER).write_text(str(_dead_pid()), encoding="ascii")
    env.runner_says({"status": "READY", "task": "T1", "calls": []})
    loop.step()
    assert not lock.exists()
    assert [x.get("holder") for x in _cleared(env)] == ["dead"]


def test_a_live_holders_lock_is_kept(env):
    loop = env.loop()
    lock = _lock(env)
    lock.mkdir()
    (lock / F.LOCK_OWNER).write_text(str(os.getpid()), encoding="ascii")
    env.runner_says({"status": "READY", "task": "T1", "calls": []})
    loop.step()
    assert (lock / F.LOCK_OWNER).exists() and not _cleared(env)


def test_orphan_leases_go_back_to_ready_at_start_and_are_counted(env):
    env.set_row("T1", status="RUNNING", lease="a" * 32, deadline=time.time() + 9999, attempts=1)
    env.loop().release_orphan_leases()
    row = env.state()["tasks"]["T1"]
    assert row["status"] == "READY" and row["lease"] is None and row["lease_expiries"] == 1
    assert [x.get("tasks") for x in env.events() if x.get("reason") == "orphan_leases"] == [1]


def test_an_anonymous_lock_keeps_the_age_rule(env):
    loop = env.loop()
    lock = _lock(env)
    lock.mkdir()
    env.runner_says({"status": "READY", "task": "T1", "calls": []})
    loop.step()
    assert lock.exists() and not _cleared(env)          # fresh: maybe a runner between mkdir and its pid
    old = time.time() - F.LOCK_STALE_S - 5
    os.utime(lock, (old, old))
    loop.step()
    assert not lock.exists() and [x.get("holder") for x in _cleared(env)] == ["anonymous"]
