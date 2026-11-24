"""factory_loop: systematic failures in the runner's own form (report6 group)."""
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
    {"status": "READY", "reason": "gate:no_changes"},                        # empty candidates
    {"status": "READY", "reason": "provider_error",
     "calls": [{"role": "code", "returncode": 1, "error_class": "unknown", "provider_error": True,
                "output_tokens": 0, "steps": 0, "tool_events": 0}]},        # dead Kilo
    {"status": "READY", "reason": "reviewer_failed", "calls": [REAL_CALL]},
    {"status": "READY", "reason": "no_independent_reviewer", "calls": [REAL_CALL]},
])
def test_systematic_failure_in_runner_form_brakes(tmp_path, monkeypatch, answer):
    e = two_tasks(tmp_path, monkeypatch, n=5)
    loop = e.loop()
    for i in range(1, 6):
        row = dict(answer, task="T%d" % i)
        row.setdefault("calls", [{"role": "code", "returncode": 1, "error_class": "unknown",
                                  "provider_error": False, "output_tokens": 0, "steps": 0,
                                  "tool_events": 0}])
        e.runner_says(row)
        out = loop.step()
    assert out.code == 3
