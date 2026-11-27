"""factory_loop: waits and blocks before the model never spread (report5 group)."""
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


@pytest.mark.parametrize("answer", [
    {"status": "WAITING_CHANNEL"},
    {"status": "READY", "reason": "rate_day", "wait_s": 600, "calls": []},
    {"status": "READY", "reason": "budget_exhausted", "calls": []},
    {"status": "BLOCKED", "blocked_reason": "already_green", "calls": []},
    {"status": "BLOCKED", "blocked_reason": "context_too_large", "calls": []},
])
def test_waits_and_blocks_before_the_model_do_not_spread(tmp_path, monkeypatch, answer):
    e = two_tasks(tmp_path, monkeypatch, n=6)
    loop = e.loop()
    for i in range(1, 7):
        e.runner_says(dict(answer, task="T%d" % i))
        e.clock.t += 1000
        assert loop.step().code is None


@pytest.mark.parametrize("reason", ["key_invalid", "balance", "model_missing", "dead", "no_key"])
def test_dead_channel_reasons_are_infra(env, reason):
    env.runner_says({"status": "READY", "task": "T1", "reason": reason, "calls": []})
    env.loop().step()
    assert env.state()["infra_streak"] == 1


def test_run_event_carries_detail_and_orders_cleanup_events_last(env):
    env.runner_says({"status": "READY", "task": "T1", "reason": "gate:no_changes",
                     "reason_detail": "d" * 400 + " owner@example.com", "error_type": "APIError",
                     "channel_reason": "rate_minute", "calls": [],
                     "events": ["stale_baseline_kept", "pending_copy_kept", "a", "b", "a", "c",
                               "d", "e", "stale_baseline_kept"]})
    env.loop().step()
    run = [x for x in env.events() if x["span"] == "run" and x.get("status") == "READY"][0]
    assert run["events"] == ["a", "b", "c", "d", "e"]
    assert len(run["reason_detail"]) <= 300 and "owner@example.com" not in run["reason_detail"]
    assert run["error_type"] == "APIError" and run["channel_reason"] == "rate_minute"


# ---- the one rule of the series: proof resets, failures add, everything else is neutral ---------

def test_environment_failure_across_several_tasks_brakes(tmp_path, monkeypatch):
    e = two_tasks(tmp_path, monkeypatch, n=4)
    monkeypatch.setenv("FAKE_RC", "1")        # every pass dies without a result (OSError, no Kilo)
    assert e.loop().run() == 3
