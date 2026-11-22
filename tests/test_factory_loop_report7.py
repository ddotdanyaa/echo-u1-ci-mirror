"""factory_loop report5, second half (report7 group)."""
import json
import os
import subprocess
import sys
import time
import pytest
from tools import agent_factory as F
from tools import factory_loop as L
from test_factory_loop import Env, Clock, git, task_row, two_tasks, env, empty_env, BRANCH, PY  # noqa: <id>
from test_factory_loop_report5 import REAL_CALL  # noqa: <id>


def test_one_task_with_a_permanent_error_does_not_brake_the_factory(tmp_path, monkeypatch):
    e = two_tasks(tmp_path, monkeypatch, n=2)
    loop = e.loop()
    monkeypatch.setenv("FAKE_RC", "1")
    loop.step()                                # <id> dies once ...
    monkeypatch.delenv("FAKE_RC")
    e.runner_says({"status": "REVIEW", "task": "T%d" % 2, "calls": [REAL_CALL]})   # ... a neighbour works
    loop.step()                                # (proof of life between the failures)
    monkeypatch.setenv("FAKE_RC", "1")
    e.out.unlink()
    for _ in range(2):                         # <id> dies again: the 3rd no-result parks it
        loop.step()
    assert e.state()["tasks"]["T1"]["status"] == "BLOCKED"
    assert e.state()["tasks"]["T1"]["blocked_reason"] == "runner_no_result"
    assert e.state()["infra_streak"] < 5 and not (e.state_dir / "BRAKE").exists()


def test_no_proof_anywhere_means_no_parking_and_the_brake_comes(env, monkeypatch):
    monkeypatch.setenv("FAKE_RC", "1")
    assert env.loop().run() == 3
    assert env.state()["tasks"]["T1"]["status"] != "BLOCKED"


def test_model_answer_without_provider_error_is_proof(env):
    env.runner_says({"status": "READY", "task": "T1", "infra": True, "reason": "runner_dead",
                     "calls": []})
    loop = env.loop()
    loop.step()
    loop.step()
    env.runner_says({"status": "REVIEW", "task": "T1", "calls": [REAL_CALL]})
    loop.step()
    assert env.state()["infra_streak"] == 0
    env.runner_says({"status": "READY", "task": "T1", "reason": "gate_unknown",
                     "infra": True, "calls": [{"role": "code", "provider_error": True}]})
    loop.step()
    env.runner_says({"status": "READY", "task": "T1", "reason": "gate_unknown",
                     "calls": [{"role": "code", "provider_error": True}]})
    loop.step()
    assert env.state()["infra_streak"] == 1      # a provider error is no proof: neutral
