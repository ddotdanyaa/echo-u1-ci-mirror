"""factory_loop: runner report fields, streak, clear-brake (report group)."""
import json
import os
import subprocess
import sys
import time

import pytest

from tools import agent_factory as F
from tools import factory_loop as L
from test_factory_loop import Env, Clock, git, task_row, env, empty_env, BRANCH, PY  # noqa: <id>


# ---- critic round 2 -----------------------------------------------------------------------

def _fail_steps(env, loop, n, monkeypatch):
    monkeypatch.setenv("FAKE_RC", "1")
    if env.out.exists():
        env.out.unlink()
    for _ in range(n):
        assert loop.step().code is None


def test_infra_streak_must_be_consecutive(env, monkeypatch):
    loop = env.loop()
    _fail_steps(env, loop, 2, monkeypatch)
    assert env.state()["infra_streak"] == 2
    monkeypatch.delenv("FAKE_RC")
    env.runner_says({"status": "REVIEW", "task": "T1", "calls": [REAL_CALL]})   # the pipeline worked
    assert loop.step().code is None
    assert env.state()["infra_streak"] == 0
    _fail_steps(env, loop, 2, monkeypatch)
    assert not (env.state_dir / "BRAKE").exists()
    monkeypatch.delenv("FAKE_RC")
    env.runner_says({"status": "WAITING_CHANNEL", "task": "T1"})        # neutral: no reset
    loop.step()
    assert env.state()["infra_streak"] == 2


def test_wait_step_leaves_the_series_alone(env, monkeypatch):
    loop = env.loop()
    _fail_steps(env, loop, 2, monkeypatch)
    env.set_row("T1", not_before=env.clock.t + 500)
    out = loop.step()
    assert out.action == "WAIT"
    assert env.state()["infra_streak"] == 2


def test_clear_brake_resets_streak(env, monkeypatch):
    loop = env.loop()
    env.runner_says({"status": "READY", "task": "T1", "infra": True, "reason": "runner_dead",
                     "calls": []})
    assert loop.run() == 3
    assert env.state()["infra_streak"] >= 5
    loop2 = env.loop()
    loop2.clear_brake()
    assert not (env.state_dir / "BRAKE").exists()
    assert env.state()["infra_streak"] == 0
    assert any(x.get("status") == "brake_cleared" for x in env.events())
    assert loop2.step().code is None            # one failure no longer brakes
    assert not (env.state_dir / "BRAKE").exists()


def test_base_sha_passed_to_runner(env):
    env.runner_says({"status": "READY", "task": "T1", "calls": []})
    env.loop().step()
    assert "--base-sha " + git(env.repo, "rev-parse", BRANCH) in env.log.read_text(encoding="utf-8")


def test_runner_infra_and_reason_fields_are_honoured(env):
    env.runner_says({"status": "READY", "task": "T1", "infra": True, "reason": "key_invalid",
                     "wait_s": 300, "calls": []})
    env.loop().step()
    assert env.state()["infra_streak"] == 1
    run = [x for x in env.events() if x["span"] == "run"][-1]
    assert run["reason"] == "key_invalid"
    stats = json.loads((env.state_dir / "stats.json").read_text(encoding="utf-8"))
    assert stats["rejected"] == 0               # a deferral without a strike is not a rejection


def test_calls_and_stages_become_events(env):
    env.runner_says({"status": "READY", "task": "T1", "reason": "gate:tests_red", "calls": [
        {"role": "code", "attempt": 1, "channel": "c1", "model": "m/a", "reserved_tokens": 900,
         "actual_tokens": 700, "input_tokens": 600, "output_tokens": 100, "dur_s": 3.5,
         "error_class": None},
        {"role": "review", "attempt": 1, "channel": "c2", "model": "m/b", "reserved_tokens": 500,
         "actual_tokens": 400, "dur_s": 1.5, "error_class": "rate_minute"}],
        "stages": {"gate_s": 2.0, "code_s": 3.5}})
    env.loop().step()
    ev = env.events()
    code = [x for x in ev if x["span"] == "run" and x.get("role") == "code"][0]
    assert code["channel"] == "c1" and code["reserved_tokens"] == 900 and code["dur_s"] == 3.5
    rev = [x for x in ev if x["span"] == "review" and x.get("role") == "review"][0]
    assert rev["error_class"] == "rate_minute"
    assert any(x["span"] == "gate" and x.get("stage") == "gate_s" and x["dur_s"] == 2.0 for x in ev)
    stats = json.loads((env.state_dir / "stats.json").read_text(encoding="utf-8"))
    assert stats["rejected"] == 1


def test_provider_error_without_infra_flag_is_not_infra(env):
    env.runner_says({"status": "READY", "task": "T1", "reason": "rate_minute", "wait_s": 60,
                     "calls": [{"provider_error": True, "error_class": "rate_minute"}]})
    env.loop().step()
    assert env.state()["infra_streak"] == 0


def test_rejected_alternation_run_wait_run_still_brakes(env):
    env.set_loop_state(wait_triage_at=env.clock.t + 10 ** 9)   # no triage while waiting here
    loop = env.loop()
    for i in range(5):
        env.runner_says({"status": "READY", "task": "T1", "infra": True, "reason": "key_invalid",
                         "wait_s": 300, "calls": []})
        out = loop.step()
        assert out.action == "RUN"
        if i < 4:
            assert out.code is None
            assert loop.step().action == "WAIT"     # a WAIT neither adds nor resets the series
            env.clock.t += 400
    assert out.code == 3 and (env.state_dir / "BRAKE").exists()


def test_hold_and_done_do_not_reset_the_series(empty_env):
    e = empty_env
    st = e.state()
    st["infra_streak"] = 3
    F.save_atomic(e.state_dir / "state.json", st)
    loop = e.loop(triage_fn=lambda **kw: {"tasks": [], "holds": [], "stale": [], "skipped": []})
    loop.step()                                      # an idle TRIAGE does not reset the series
    assert e.state()["infra_streak"] == 3
    st["infra_streak"] = 3
    F.save_atomic(e.state_dir / "state.json", st)
    assert loop.step().action == "DONE"
    assert e.state()["infra_streak"] == 3


def test_second_instance_with_clear_brake_does_not_touch_state(env, monkeypatch):
    # A live loop must pass the <id> process identity check; pytest is not a loop.
    monkeypatch.setattr(L, "proc_info", lambda pid: ("python -m tools.factory_loop", env.clock.t))
    (env.state_dir / "BRAKE").write_text("brake", encoding="utf-8")
    (env.state_dir / "loop.pid").write_text(str(os.getpid()), encoding="utf-8")
    assert env.loop(clear_brake=True).run() == 4
    assert (env.state_dir / "BRAKE").exists()


def test_runner_strings_are_redacted(env):
    env.runner_says({"status": "READY", "task": "T1", "calls": [
        {"role": "code", "channel": "owner@example.com", "model": "m/x",
         "error_class": "C:" + chr(92) + "Users" + chr(92) + "SomeName" + chr(92) + "x"}], "kind": "owner@example.com"})
    env.loop().step()
    raw = (env.state_dir / "telemetry.jsonl").read_text(encoding="utf-8")
    assert "owner@example.com" not in raw and "SomeName" not in raw


def test_loop_state_not_an_object_starts_empty(env):
    (env.state_dir / "loop_state.json").write_text("[1, 2]", encoding="utf-8")
    env.runner_says({"status": "READY", "task": "T1", "calls": []})
    env.loop().step()
    assert any("not an object" in x.get("reason", "") for x in env.events())
    assert json.loads((env.state_dir / "loop_state.json").read_text(encoding="utf-8")).get("bases")


def test_runner_events_and_stage_spans(env):
    env.runner_says({"status": "READY", "task": "T1", "reason": "runner_dead", "calls": [],
                     "events": ["neighbors_unavailable", "pending_dropped", "neighbors_skipped",
                                "output_truncated", "e5", "e6 owner@example.com"],
                     "stages": {"red_before_s": 1.0, "neighbors_s": 2.0, "gate_s": 3.0,
                                "review_s": 4.0, "code_s": 5.0}})
    env.loop().step()
    ev = env.events()
    run = [x for x in ev if x["span"] == "run" and x.get("status") == "READY"][0]
    assert run["events"] == ["neighbors_unavailable", "pending_dropped", "neighbors_skipped",
                             "output_truncated", "e5"]
    stage = {x["stage"]: x["span"] for x in ev if x.get("stage")}
    assert stage == {"red_before_s": "gate", "neighbors_s": "gate", "gate_s": "gate",
                     "review_s": "review", "code_s": "run"}


def test_stats_separate_blocked_from_quarantine(env):
    env.set_row("T1", status="BLOCKED", blocked_reason="context_too_large")
    env.loop(once=True).run()
    stats = json.loads((env.state_dir / "stats.json").read_text(encoding="utf-8"))
    assert stats["quarantine"] == 0 and stats["blocked"] == 1
    assert stats["blocked_by_reason"] == {"context_too_large": 1}
    # a quarantine of the current slicer version (one without a version is reopened at start, 1.3)
    env.set_row("T1", status="FAILED", reason="quarantine", q_ver=F.slicer_version())
    env.loop(once=True).run()
    stats = json.loads((env.state_dir / "stats.json").read_text(encoding="utf-8"))
    assert stats["quarantine"] == 1 and stats["blocked"] == 0


def test_call_fields_whitelist_and_redact(env):
    env.runner_says({"status": "READY", "task": "T1", "reason": "gate:no_changes",
                     "model_note": "n" * 280 + " owner@example.com " + "n" * 300, "calls": [
        {"role": "code", "model": "m/x", "tool_events": 3, "steps": 2, "finish_reason": "stop",
         "files_read": ["f%d.py" % i for i in range(15)] + ["owner@example.com"],
         "secret_field": "AI" + "zaSyA1234567890" + "abcdefghijklmnopqrstuvwx"}]})
    env.loop().step()
    call = [x for x in env.events() if x["span"] == "run" and x.get("role") == "code"][0]
    assert call["tool_events"] == 3 and call["steps"] == 2 and call["finish_reason"] == "stop"
    assert call["files_read"] == ["f%d.py" % i for i in range(10)]
    run = [x for x in env.events() if x["span"] == "run" and x.get("status") == "READY"][0]
    assert 0 < len(run["model_note"]) <= 300 and "owner@example.com" not in run["model_note"]
    assert "model_note" not in call
    assert "secret_field" not in call
    assert "AI" + "za" not in (env.state_dir / "telemetry.jsonl").read_text(encoding="utf-8")


def test_long_channel_wait_triages_the_next_portion_once(env):
    got = []
    env.runner_says({"status": "READY", "task": "T1", "reason": "rate_day", "wait_s": 600,
                     "calls": []})
    loop = env.loop(triage_fn=lambda **kw: got.append(1) or {
        "tasks": [], "holds": [], "stale": [], "skipped": [], "deferred": ["D"]})
    loop.step()                                   # RUN: a channel-wide day limit
    assert loop.step().action == "TRIAGE" and len(got) == 1
    assert loop.step().action == "WAIT" and len(got) == 1     # not again before triage_retry_s


REAL_CALL = {"role": "code", "model": "m/x", "returncode": 0, "error_class": None, "provider_error": False,
              "output_tokens": 50, "steps": 2, "tool_events": 1}
