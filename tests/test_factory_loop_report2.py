"""factory_loop: channel stop, infra classification, run event fields (report2 group)."""
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


def test_task_level_deferral_does_not_stop_the_other_tasks(tmp_path, monkeypatch):
    e = two_tasks(tmp_path, monkeypatch)
    e.runner_says({"status": "READY", "task": "T1", "reason": "gate_unknown", "wait_s": 300,
                   "calls": []})
    loop = e.loop()
    loop.step()
    e.set_row("T1", not_before=e.clock.t + 300)       # what the runner does for this task
    out = loop.step()
    assert out.action == "RUN"                        # <id> runs, no channel cooldown
    ls = json.loads((e.state_dir / "loop_state.json").read_text(encoding="utf-8"))
    assert ls.get("channel_until", 0) <= e.clock.t


@pytest.mark.parametrize("reason", ["rate_minute", "region", "key_invalid", "budget_exhausted",
                                    "channel_wait"])
def test_channel_reasons_stop_everything(tmp_path, monkeypatch, reason):
    e = two_tasks(tmp_path, monkeypatch)
    e.runner_says({"status": "READY", "task": "T1", "reason": reason, "wait_s": 120, "calls": []})
    loop = e.loop()
    loop.step()
    assert loop.step().action == "WAIT"
