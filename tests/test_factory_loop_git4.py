"""factory_loop: requeue counters, machine failures, lock error (git4 group)."""
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


def test_copy_failure_three_times_parks_the_task_without_a_brake(env, monkeypatch):
    import shutil as _sh

    def too_long(src, dst, *a, **k):
        raise OSError(206, "The filename or extension is too long")
    monkeypatch.setattr(_sh, "copyfile", too_long)
    _review(env)
    loop = env.loop()
    for _ in range(3):
        assert loop.step().code is None
    row = env.state()["tasks"]["T1"]
    assert row["status"] == "BLOCKED" and row["blocked_reason"] == "promote_failed"
    assert env.state()["infra_streak"] == 0 and not (env.state_dir / "BRAKE").exists()
    assert clean(env)
    assert any(x["span"] == "promote" and x["status"] == "parked" for x in env.events())


def test_git_add_failure_on_the_package_is_counted_per_task(env, monkeypatch):
    real = L.git_run

    def bad_add(cwd, *args, **kw):
        if "add" in args:
            raise subprocess.CalledProcessError(1, "git add", "", "paths are ignored by .gitignore")
        return real(cwd, *args, **kw)
    monkeypatch.setattr(L, "git_run", bad_add)
    _review(env)
    loop = env.loop()
    for _ in range(3):
        loop.step()
    assert env.state()["tasks"]["T1"]["blocked_reason"] == "promote_failed"
    assert env.state()["infra_streak"] == 0
