"""factory_loop: requeue counters, machine failures, lock error (git3 group)."""
import json
import os
import subprocess
import sys
import time

import pytest

from tools import agent_factory as F
from tools import factory_loop as L
from test_factory_loop import Env, Clock, task_row, env, empty_env, git, BRANCH, PY  # noqa: <id>
from test_factory_loop_git2 import head, clean, _review  # noqa: <id>


def test_requeue_loop_with_proofs_in_between_still_reaches_the_park(env):
    """REVIEW without a package -> requeue -> a proof run -> REVIEW without a package ... must park."""
    loop = env.loop()
    for _ in range(3):
        env.set_row("T1", status="REVIEW", attempts=1)       # nothing in stage/for-review/<id>
        loop.step()                                           # the real _promote requeues (or parks)
        if env.state()["tasks"]["T1"]["status"] == "BLOCKED":
            break
        env.runner_says({"status": "REVIEW", "task": "T1", "calls": [REAL_CALL]})
        loop.step()                                           # the real _run sees a proof
    row = env.state()["tasks"]["T1"]
    assert row["status"] == "BLOCKED" and row["blocked_reason"] == "no_package"


def test_a_real_merge_clears_the_requeue_counter(env):
    env.set_loop_state(requeues={"T1": 2}, bases={})
    _review(env)
    env.set_loop_state(requeues={"T1": 2}, bases={"T1": head(env)})
    env.loop().step()
    ls = json.loads((env.state_dir / "loop_state.json").read_text(encoding="utf-8"))
    assert env.state()["tasks"]["T1"]["status"] == "PROMOTED" and "T1" not in ls["requeues"]


@pytest.mark.parametrize("make", [
    lambda: PermissionError(13, "sharing violation", None, 32),
    lambda: OSError(28, "No space left on device"),
])
def test_antivirus_and_full_disk_are_infrastructure_not_a_package_fault(env, monkeypatch, make):
    import shutil as _sh
    _review(env)

    def broken(*a, **k):
        raise make()
    monkeypatch.setattr(_sh, "copyfile", broken)
    loop = env.loop()
    for _ in range(3):
        loop.step()
    row = env.state()["tasks"]["T1"]
    assert row["status"] == "REVIEW"                      # never parked for the machine's fault
    assert env.state()["infra_streak"] == 3 and clean(env)


def test_a_read_only_git_dir_is_a_lock_error_not_already_running(env, monkeypatch):
    def broken(self, lock):
        raise OSError(30, "Read-only file system")
    monkeypatch.setattr(L.Loop, "_make_lock", broken)
    assert env.loop(once=True).run() == L.EXIT_LOCK_ERROR
    assert L.EXIT_LOCK_ERROR != L.EXIT_RUNNING
    assert any(x.get("status") == "lock_error" for x in env.events())


REAL_CALL = {"role": "code", "model": "m/x", "returncode": 0, "error_class": None,
             "provider_error": False, "output_tokens": 50, "steps": 2, "tool_events": 1}
