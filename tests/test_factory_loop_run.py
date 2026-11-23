"""factory_loop: runner subprocess, brake, timeout (run group)."""
import json
import os
import subprocess
import sys
import time

import pytest

from tools import agent_factory as F
from tools import factory_loop as L
from test_factory_loop import Env, Clock, git, task_row, env, empty_env, BRANCH, PY  # noqa: <id>


def test_runner_timeout_is_infra(env, monkeypatch):
    monkeypatch.setenv("FAKE_SLEEP", "3")
    monkeypatch.setattr(L, "RUNNER_TIMEOUT_S", 0.3)
    loop = env.loop()
    loop.step()
    assert env.state()["infra_streak"] == 1


def test_five_crashes_write_brake_and_exit_with_the_brake_code(tmp_path, monkeypatch):
    """A dead runner brakes after 5 results whatever the number of tasks (nothing is parked)."""
    env = Env(tmp_path, monkeypatch, tasks=[task_row(i) for i in (1, 2, 3)])
    monkeypatch.setenv("FAKE_RC", "1")  # no JSON at all
    code = env.loop().run()
    assert code == 3
    assert (env.state_dir / "BRAKE").exists()
    assert not (env.state_dir / "STOP").exists()
    assert env.runs() == 5     # no proof anywhere: a dead runner is never parked, it brakes
    assert any(x["span"] == "infra" and x["status"] == "brake" for x in env.events())


def test_runner_infra_flag_series_brakes_but_provider_error_alone_does_not(env):
    env.runner_says({"status": "READY", "task": "T1", "infra": True, "reason": "runner_dead",
                     "calls": [{"provider_error": True}]})
    assert env.loop().run() == 3
    assert env.runs() == 5


def test_success_resets_infra_streak(env, monkeypatch):
    monkeypatch.setenv("FAKE_RC", "1")
    loop = env.loop()
    loop.step()
    loop.step()
    assert env.state()["infra_streak"] == 2
    monkeypatch.delenv("FAKE_RC")
    env.runner_says({"status": "REVIEW", "task": "T1", "calls": [REAL_CALL]})
    loop.step()
    assert env.state()["infra_streak"] == 0


def test_stop_during_sleep_is_noticed(env):
    env.mp.setenv("FAKE_RC", "1")  # no output file -> crash -> infra -> 60 s sleep, chunked
    env.clock.on_sleep = lambda s: (env.state_dir / "STOP").write_text("x", encoding="utf-8")
    assert env.loop().run() == 0
    assert env.runs() == 1
    assert max(env.clock.sleeps) <= 60




def test_env_file_key_reaches_runner_only(env, capsys):
    key = "AI" + "zaFAKEKEY-" + "not-real-123456"
    env.runner_says({"status": "READY", "task": "T1", "infra": True, "reason": "key_invalid",
                     "error": "leak " + key, "calls": []})
    loop = env.loop(extra={"extra_env": {"GEMINI_FAKE": key}})
    loop.step()
    assert "KEY=" + key in env.log.read_text(encoding="utf-8")  # the subprocess got it
    assert "GEMINI_FAKE" not in os.environ
    out = capsys.readouterr()
    for blob in (out.out, out.err, (env.state_dir / "telemetry.jsonl").read_text(encoding="utf-8"),
                 (env.state_dir / "stats.json").read_text(encoding="utf-8"),
                 (env.state_dir / "state.json").read_text(encoding="utf-8")):
        assert key not in blob




def test_plain_env_key_is_scrubbed_from_every_line(env):
    key = "plainsecretvalue-0042"        # matches no known token shape: only the scrub catches it
    env.runner_says({"status": "READY", "task": "T1", "reason": "key_invalid",
                     "reason_detail": "provider said " + key, "calls": []})
    env.loop(extra={"extra_env": {"GEMINI_FAKE": key}}).step()
    raw = (env.state_dir / "telemetry.jsonl").read_text(encoding="utf-8")
    assert key not in raw and "[REDACTED]" in raw


# ---- what is infra and what resets the series (runner flag is honoured; critics' round) -------

def test_five_transient_infra_results_brake_with_the_brake_exit(env):
    """transient + infra=True is an honest runner verdict (OSError of a pass, dead process)."""
    env.runner_says({"status": "READY", "task": "T1", "infra": True, "reason": "runner_dead",
                     "calls": []})
    assert env.loop().run() == 3
    assert (env.state_dir / "BRAKE").exists() and env.runs() == 5


def test_worker_timeout_with_infra_flag_counts(env):
    env.runner_says({"status": "BLOCKED", "task": "T1", "infra": True,
                     "reason": "worker_timeout", "calls": []})
    env.loop().step()
    assert env.state()["infra_streak"] == 1


def test_a_pass_without_infra_resets_the_series(env):
    env.runner_says({"status": "READY", "task": "T1", "infra": True, "reason": "runner_dead",
                     "calls": []})
    loop = env.loop()
    for _ in range(3):
        loop.step()
    assert env.state()["infra_streak"] == 3
    env.runner_says({"status": "READY", "task": "T1", "reason": "gate:red", "calls": [REAL_CALL],
                     "tests": {"collected": 3, "passed": 1, "failed": 2}})
    loop.step()
    assert env.state()["infra_streak"] == 0


def test_holds_only_triage_does_not_reset_the_series(empty_env):
    e = empty_env
    st = e.state()
    st["infra_streak"] = 3
    F.save_atomic(e.state_dir / "state.json", st)
    e.loop(triage_fn=lambda **kw: {"tasks": [], "holds": [{"backlog_id": "H1", "question": "q"}],
                                   "stale": [], "skipped": []}).step()
    assert e.state()["infra_streak"] == 3


def test_questions_file_never_contains_env_file_keys(env):
    key = "plainsecretvalue-0043"
    env.set_row("T1", status="BLOCKED", blocked_reason="gate")
    st = env.state()
    F.add_feedback(st, "T1", "gate", "the provider answered " + key)
    F.save_atomic(env.state_dir / "state.json", st)
    loop = env.loop(extra={"extra_env": {"GEMINI_FAKE": key}})
    loop.step()
    text = (env.state_dir / "opus_questions.md").read_text(encoding="utf-8")
    assert key not in text and "[REDACTED]" in text


REAL_CALL = {"role": "code", "model": "m/x", "returncode": 0, "error_class": None, "provider_error": False,
              "output_tokens": 50, "steps": 2, "tool_events": 1}
