"""The runner's state lock names its holder; the loop clears a dead holder's lock before EVERY runner pass.

Restart check 19.11 17:42: the loop was killed during a pass, the new loop started seconds later, the anonymous lock
was younger than LOCK_STALE_S (the age rule ran only at start) and the runner refused every pass with
"another controller or stale lock owns state".
Critic 19.11 18:39: a pid is reused (a reboot, hours later), so a holder's lock also has an age ceiling; the orphan
release at start is neutral only twice in a row for one task, so a pass that kills the loop every time still ends."""
import os
import subprocess
import sys
import time

import pytest

from tools import agent_factory as F
from tools import factory_loop as L
from test_factory_loop import Env, env, task_row  # noqa: <id>


def _lock(e):
    return e.state_dir / "state.json.lockdir"


def _dead_pid():
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


@pytest.fixture
def live_pid():
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    yield p.pid
    p.kill()
    p.wait()


def _cleared(e):
    return [x for x in e.events() if x.get("reason") == "stale_lockdir"]


def _hold(e, pid, age=0.0):
    lock = _lock(e)
    lock.mkdir()
    (lock / F.LOCK_OWNER).write_text(str(pid), encoding="ascii")
    if age:
        old = time.time() - age
        os.utime(lock, (old, old))
    return lock


def test_a_dead_holders_fresh_lock_is_cleared_before_the_next_pass(env):
    loop = env.loop()
    lock = _hold(env, _dead_pid())
    env.runner_says({"status": "READY", "task": "T1", "calls": []})
    loop.step()
    assert not lock.exists()
    assert [x.get("holder") for x in _cleared(env)] == ["dead"]


def test_a_live_holders_lock_is_kept_and_the_runner_is_not_started(env, live_pid):
    loop = env.loop()
    lock = _hold(env, live_pid)
    env.runner_says({"status": "READY", "task": "T1", "calls": []})
    loop.step()
    assert (lock / F.LOCK_OWNER).exists() and not _cleared(env)
    assert not env.log.exists()                 # no runner start: it would refuse and count towards the brake


def test_a_live_holder_past_the_pass_ceiling_is_a_reused_pid(env, live_pid):
    loop = env.loop()
    lock = _hold(env, live_pid, age=L.RUNNER_TIMEOUT_S + F.LOCK_STALE_S + 60)
    env.runner_says({"status": "READY", "task": "T1", "calls": []})
    loop.step()
    assert not lock.exists() and [x.get("holder") for x in _cleared(env)] == ["old"]


def test_the_loops_own_pid_is_never_the_holder(env):
    loop = env.loop()
    lock = _hold(env, os.getpid())
    loop.clear_stale_lockdir()
    assert not lock.exists() and [x.get("holder") for x in _cleared(env)] == ["dead"]


def test_an_empty_owner_file_is_an_anonymous_lock(env):
    loop = env.loop()
    lock = _lock(env)
    lock.mkdir()
    (lock / F.LOCK_OWNER).write_text("", encoding="ascii")     # between the runner's create and its write
    loop.clear_stale_lockdir()
    assert lock.exists() and not _cleared(env)
    old = time.time() - F.LOCK_STALE_S - 5
    os.utime(lock, (old, old))
    loop.clear_stale_lockdir()
    assert not lock.exists() and [x.get("holder") for x in _cleared(env)] == ["anonymous"]


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


def _orphan(e, attempts=1):
    e.set_row("T1", status="RUNNING", lease="a" * 32, deadline=time.time() + 9999, attempts=attempts)
    e.loop().release_orphan_leases()
    return e.state()["tasks"]["T1"]


def test_two_restarts_in_a_row_are_neutral_the_third_counts_as_an_expiry(env):
    for _ in range(2):
        row = _orphan(env)
        assert row["status"] == "READY" and row["lease"] is None and row["attempts"] == 0
        assert not row.get("lease_expiries")
    row = _orphan(env)
    assert row["status"] == "READY" and row["attempts"] == 1 and row["lease_expiries"] == 1
    assert [x.get("tasks") for x in env.events() if x.get("reason") == "orphan_leases"] == [1, 1, 1]


def test_a_pass_that_kills_the_loop_every_time_ends_blocked(env):
    statuses = [_orphan(env)["status"] for _ in range(5)]
    assert statuses == ["READY", "READY", "READY", "READY", "BLOCKED"]
    assert env.state()["tasks"]["T1"]["blocked_reason"] == "lease_expired"


def test_a_pass_that_ends_starts_a_new_series_of_free_restarts():
    state = {"tasks": {"T1": {"status": "RUNNING", "lease": "a" * 32, "deadline": 10.0, "attempts": 1}}}
    for _ in range(2):
        state["tasks"]["T1"].update(status="RUNNING", lease="a" * 32, deadline=10.0, attempts=1)
        F.release_expired(state, float("inf"), orphan=True)
    state["tasks"]["T1"].update(status="RUNNING", lease="a" * 32, deadline=10.0, attempts=1)
    F.settle(state, "T1", "a" * 32, tests_ok=False, evidence="0" * 64, max_attempts=3, strike=False)
    assert "orphan_releases" not in state["tasks"]["T1"]
    state["tasks"]["T1"].update(status="RUNNING", lease="a" * 32, deadline=10.0, attempts=2)
    F.release_expired(state, float("inf"), orphan=True)
    assert state["tasks"]["T1"]["attempts"] == 1 and not state["tasks"]["T1"].get("lease_expiries")


def test_orphans_are_kept_while_a_live_holder_keeps_the_lock(env, live_pid):
    env.set_row("T1", status="RUNNING", lease="a" * 32, deadline=time.time() + 9999, attempts=1)
    _hold(env, live_pid)
    loop = env.loop()
    loop.clear_stale_lockdir()
    loop.release_orphan_leases()
    assert env.state()["tasks"]["T1"]["status"] == "RUNNING"
    assert [x.get("reason") for x in env.events() if x.get("status") == "skipped"] == ["orphan_leases: state locked"]


def test_a_lease_past_its_deadline_at_start_is_an_ordinary_expiry(env):
    env.set_row("T1", status="RUNNING", lease="a" * 32, deadline=time.time() - 5, attempts=1)
    env.loop().release_orphan_leases()
    row = env.state()["tasks"]["T1"]
    assert row["status"] == "READY" and row["attempts"] == 1 and row["lease_expiries"] == 1


def test_a_lease_that_expires_by_time_still_counts_and_blocks_at_the_third():
    state = {"tasks": {"T1": {"status": "RUNNING", "lease": "a" * 32, "deadline": 10.0, "attempts": 1}}}
    for n in (1, 2, 3):
        state["tasks"]["T1"].update(status="RUNNING", lease="a" * 32, deadline=10.0)
        assert F.release_expired(state, 11.0) == ["T1"] and state["tasks"]["T1"]["lease_expiries"] == n
    assert state["tasks"]["T1"]["status"] == "BLOCKED" and state["tasks"]["T1"]["blocked_reason"] == "lease_expired"
