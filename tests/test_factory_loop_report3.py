"""factory_loop: what is proof of work (report3 group)."""
import json
import os
import subprocess
import sys
import time

import pytest

from tools import agent_factory as F
from tools import factory_loop as L
from test_factory_loop import Env, two_tasks, Clock, git, task_row, env, empty_env, BRANCH, PY  # noqa: <id>


# ---- critic round 2 -----------------------------------------------------------------------

def _fail_steps(env, loop, n, monkeypatch):
    monkeypatch.setenv("FAKE_RC", "1")
    if env.out.exists():
        env.out.unlink()
    for _ in range(n):
        assert loop.step().code is None


# ---- integration critic: stop only for channel reasons, infra only for real infra -------------

REAL_CALL = {"role": "code", "model": "m/x", "returncode": 0, "error_class": None, "provider_error": False,
              "output_tokens": 50, "steps": 2, "tool_events": 1}


REAL_CALL = {"role": "code", "model": "m/x", "returncode": 0, "error_class": None,
             "provider_error": False, "output_tokens": 50, "steps": 2, "tool_events": 1}


def _streak(env, n):
    st = env.state()
    st["infra_streak"] = n
    F.save_atomic(env.state_dir / "state.json", st)


@pytest.mark.parametrize("answer", [
    # Kilo died: rc != 0, unknown stderr -> kind 'unknown', provider_error False
    {"status": "READY", "task": "T1", "reason": "gate:red",
     "calls": [{"role": "code", "returncode": 1, "error_class": "unknown", "provider_error": False,
                "output_tokens": 0, "steps": 0, "tool_events": 0}]},
    {"status": "READY", "task": "T1", "reason": "gate:red",
     "calls": [{"role": "code", "returncode": 1, "error_class": None, "provider_error": False,
                "output_tokens": 80, "steps": 3, "tool_events": 2}]},
    # an empty answer of a living Kilo: gate:no_changes is no real candidate
    {"status": "READY", "task": "T1", "reason": "gate:no_changes",
     "calls": [{"role": "code", "returncode": 0, "error_class": None, "provider_error": False,
                "output_tokens": 50, "steps": 2, "tool_events": 1}]},
    {"status": "READY", "task": "T1", "reason": "gate:red",
     "calls": [{"role": "code", "returncode": 0, "error_class": None, "provider_error": False,
                "output_tokens": 0, "steps": 0, "tool_events": 0}]},
    # the 3rd os_error: successful calls before the OSError prove nothing
    {"status": "BLOCKED", "task": "T1", "blocked_reason": "worker_exception",
     "calls": [{"role": "code", "returncode": 0, "error_class": None, "provider_error": False,
                "output_tokens": 50, "steps": 2, "tool_events": 1}]},
    {"status": "READY", "task": "T1", "reason": "os_error", "wait_s": 60,
     "calls": [{"role": "code", "returncode": 0, "error_class": None, "provider_error": False,
                "output_tokens": 50, "steps": 2, "tool_events": 1}]},
])
def test_these_results_are_not_proof_of_work(env, answer):
    _streak(env, 3)
    env.runner_says(answer)
    env.loop().step()
    assert env.state()["infra_streak"] == 3


@pytest.mark.parametrize("answer", [
    {"status": "REVIEW", "task": "T1", "calls": [REAL_CALL]},
    {"status": "READY", "task": "T1", "reason": "gate:red", "calls": [REAL_CALL],
     "tests": {"collected": 3, "passed": 1, "failed": 2}},
    {"status": "READY", "task": "T1", "reason": "weakening:skip", "calls": [REAL_CALL]},
    {"status": "READY", "task": "T1", "reason": "review:rejected", "calls": [REAL_CALL]},
])
def test_a_real_candidate_after_a_real_call_is_proof(env, answer):
    _streak(env, 3)
    env.runner_says(answer)
    env.loop().step()
    assert env.state()["infra_streak"] == 0


def test_dying_kilo_on_several_tasks_brakes(tmp_path, monkeypatch):
    e = two_tasks(tmp_path, monkeypatch, n=5)
    loop = e.loop()
    for i in range(1, 6):
        e.runner_says({"status": "READY", "task": "T%d" % i, "reason": "gate:no_changes",
                       "calls": [{"role": "code", "returncode": 1, "error_class": "unknown",
                                  "provider_error": False, "output_tokens": 0, "steps": 0,
                                  "tool_events": 0}]})
        out = loop.step()
        e.set_row("T%d" % i, not_before=e.clock.t + 60)   # the runner postpones the task
    assert out.code == 3


def test_promote_requeue_without_package_three_times_blocks_the_task(env):
    loop = env.loop()
    for i in range(3):
        env.set_row("T1", status="REVIEW", attempts=1)
        loop.step()
    row = env.state()["tasks"]["T1"]
    assert row["status"] == "BLOCKED" and row["blocked_reason"] == "no_package"


def test_neutral_steps_do_not_reset(env):
    st = env.state()
    st["infra_streak"] = 3
    F.save_atomic(env.state_dir / "state.json", st)
    env.runner_says({"status": "WAITING_CHANNEL", "task": "T1"})
    env.loop().step()
    assert env.state()["infra_streak"] == 3
    env.runner_says({"status": "IDLE", "calls": []})
    env.clock.t += 500
    env.loop().step()
    assert env.state()["infra_streak"] == 3


# ---- os_error: a machine-wide failure accumulates across tasks, one task does not ---------------

def test_os_error_is_a_known_deferral_reason():
    from tools import agent_factory as F
    assert "os_error" in F.DEFER_REASONS


def test_os_error_across_tasks_brakes_but_worker_exception_is_neutral(tmp_path, monkeypatch):
    e = two_tasks(tmp_path, monkeypatch, n=5)
    loop = e.loop()
    for i in range(1, 5):                       # the runner's 'os_error' release carries infra=True
        e.runner_says({"status": "READY", "task": "T%d" % i, "reason": "os_error", "infra": True,
                       "wait_s": 60, "calls": []})
        e.set_row("T%d" % i, not_before=e.clock.t + 60)
        assert loop.step().code is None
    assert e.state()["infra_streak"] == 4
    # the 3rd os_error of ONE task: the runner blocks it as worker_exception WITHOUT infra
    e.runner_says({"status": "BLOCKED", "task": "T5", "blocked_reason": "worker_exception",
                   "calls": []})
    e.set_row("T5", status="BLOCKED", blocked_reason="worker_exception")
    loop.step()
    assert e.state()["infra_streak"] == 4 and not (e.state_dir / "BRAKE").exists()
    e.set_row("T5", status="READY", blocked_reason=None)
    e.runner_says({"status": "READY", "task": "T5", "reason": "os_error", "infra": True,
                   "wait_s": 60, "calls": []})
    assert loop.step().code == 3                 # the 5th honest infra result brakes



@pytest.mark.parametrize("tests", [None, {}, {"collected": 0, "passed": 0}, {"collected": None}])
def test_gate_without_collected_tests_is_not_proof(env, tests):
    """Broken gates (0 collected, timeout) say nothing about the pipeline."""
    _streak(env, 3)
    row = {"status": "READY", "task": "T1", "reason": "gate:red", "calls": [REAL_CALL]}
    if tests is not None:
        row["tests"] = tests
    env.runner_says(row)
    env.loop().step()
    assert env.state()["infra_streak"] == 3


def test_gate_timeout_is_not_proof(env):
    _streak(env, 3)
    env.runner_says({"status": "READY", "task": "T1", "reason": "gate:timeout",
                     "calls": [REAL_CALL], "tests": {"collected": 4}})
    env.loop().step()
    assert env.state()["infra_streak"] == 3
