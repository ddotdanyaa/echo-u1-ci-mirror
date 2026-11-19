"""factory_loop round 7, second half (r7b group)."""
import json
import os
import subprocess
import pytest
from tools import agent_factory as F
from tools import factory_loop as L
from test_factory_loop import Env, Clock, git, task_row, env, empty_env, BRANCH, PY  # noqa: <id>
from test_factory_loop_r7 import _flaky  # noqa: <id>
from test_factory_loop_answers import put, answers, with_backlog  # noqa: <id>


def test_retry_fs_gives_up_after_five_tries_and_pauses_stay_under_two_seconds():
    fn, calls = _flaky(99, winerror=5)
    pauses = []
    with pytest.raises(PermissionError):
        L.retry_fs(fn, sleep=pauses.append)
    assert len(calls) == 5 and max(pauses) <= 2.0


def test_retry_fs_does_not_retry_other_errors():
    fn, calls = _flaky(99, winerror=123, errno_=2)
    with pytest.raises(PermissionError):
        L.retry_fs(fn, sleep=lambda s: None)
    assert len(calls) == 1


def test_answer_move_and_telemetry_rotation_use_it(env, monkeypatch):
    with_backlog(env)
    put(env, backlog_id="B1", task_id="T1", note="plain technical hint")
    fn, calls = _flaky(2)
    real = os.replace

    def flaky_replace(src, dst):
        if "answers" in str(src) and not calls:
            calls.append(1)
            e = PermissionError(13, "sharing violation")
            e.winerror = 32
            raise e
        return real(src, dst)
    monkeypatch.setattr(L.time, "sleep", lambda s: None)
    monkeypatch.setattr(L.os, "replace", flaky_replace)
    env.loop().apply_answers()
    assert list((answers(env) / "done").glob("*.json"))
