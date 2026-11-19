"""factory_loop: spread of failures without proof (report4 group)."""
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


def test_five_gate_unknown_on_different_tasks_brake_without_any_infra_flag(tmp_path, monkeypatch):
    """A systematic failure with no proof of work between: 5 DIFFERENT tasks -> BRAKE."""
    e = two_tasks(tmp_path, monkeypatch, n=5)
    loop = e.loop()
    for i in range(1, 6):
        e.runner_says({"status": "READY", "task": "T%d" % i, "reason": "gate_unknown",
                       "infra": False, "wait_s": 300, "calls": [REAL_CALL]})
        out = loop.step()
        e.set_row("T%d" % i, not_before=e.clock.t + 300)
    assert out.code == 3 and "gate_unknown" in (e.state_dir / "BRAKE").read_text(encoding="utf-8")


def test_one_task_failing_ten_times_does_not_brake(env):
    loop = env.loop()
    for _ in range(10):
        env.runner_says({"status": "READY", "task": "T1", "reason": "gate_unknown",
                         "infra": False, "calls": [REAL_CALL]})
        assert loop.step().code is None
    assert not (env.state_dir / "BRAKE").exists()


def test_a_proof_clears_the_spread(tmp_path, monkeypatch):
    e = two_tasks(tmp_path, monkeypatch, n=6)
    loop = e.loop()
    for i in range(1, 5):
        e.runner_says({"status": "READY", "task": "T%d" % i, "reason": "gate:no_changes",
                       "calls": [REAL_CALL]})
        loop.step()
    e.runner_says({"status": "REVIEW", "task": "T5", "calls": [REAL_CALL]})
    loop.step()                                            # proof: the set is emptied
    e.runner_says({"status": "READY", "task": "T6", "reason": "gate:no_changes",
                   "calls": [REAL_CALL]})
    assert loop.step().code is None


def test_no_proof_labels_are_scrubbed_in_loop_state_and_brake_file(tmp_path, monkeypatch):
    e = two_tasks(tmp_path, monkeypatch, n=5)
    key = "plainsecretvalue-0777"
    loop = e.loop(extra={"extra_env": {"K": key}})
    for i in range(1, 6):
        e.runner_says({"status": "READY", "task": "T%d" % i, "reason": "gate:no_changes " + key,
                       "calls": [REAL_CALL]})
        out = loop.step()
    assert out.code == 3
    assert key not in (e.state_dir / "loop_state.json").read_text(encoding="utf-8")
    assert key not in (e.state_dir / "BRAKE").read_text(encoding="utf-8")
