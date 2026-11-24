"""factory_loop: requeue counters, machine failures, lock error (git5 group)."""
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


def test_environment_failures_of_promote_stay_infra(env):
    _review(env)
    (env.repo / "tools" / "other.py").write_text("dirty\n", encoding="utf-8")   # dirty OUTSIDE
    loop = env.loop()
    loop.step()
    assert env.state()["infra_streak"] == 1 and env.state()["tasks"]["T1"]["status"] == "REVIEW"


def test_reused_pid_does_not_hold_the_worktree_for_ever(env, tmp_path):
    ghost = tmp_path / "ghost-state"
    ghost.mkdir()
    lock = env.repo / ".git" / "factory_loop.lockdir"
    lock.mkdir()
    # an owner whose pid is alive (ours) but whose state dir's loop.pid names another pid: stale
    (lock / "owner").write_text("%d|%s" % (os.getpid(), ghost), encoding="utf-8")
    (ghost / "loop.pid").write_text(str(os.getpid() + 1), encoding="utf-8")
    other = env.loop()
    assert other._lock_worktree() is True
    other.release()


def test_unreadable_git_dir_disables_the_lock_loudly(env, monkeypatch):
    def broken(*a, **k):
        raise OSError("git is gone")
    monkeypatch.setattr(subprocess, "run", broken)
    loop = env.loop()
    assert loop._worktree_lock_dir() is None
    monkeypatch.undo()
    assert any(x.get("status") == "warning" and "lock_disabled" in x.get("reason", "")
               for x in env.events())
