"""factory_loop round <id>: addressed deferral instead of an endless brake, a brake with a term (d8b group: the brake with a term)."""
import json
import random

import pytest

from tools import agent_factory as F
from tools import factory_loop as L
from test_factory_loop import Env, task_row, two_tasks, env, empty_env  # noqa: <id>
from test_factory_loop_git3 import REAL_CALL


def _ls(e):
    return json.loads((e.state_dir / "loop_state.json").read_text(encoding="utf-8"))


def _says(e, tid, reason, **kw):
    e.runner_says(dict({"status": "READY", "task": tid, "reason": reason, "infra": True, "calls": []}, **kw))


def _events(e, status):
    return [x for x in e.events() if x.get("span") == "infra" and x.get("status") == status]


# ---- the brake has a term (half-open) ----------------------------------------------------------------------

def _brake_it(e):
    for i in range(1, 6):
        _says(e, "T%d" % i, "runner_dead")
    assert e.loop(rng=random.Random(1)).run() == 3
    assert (e.state_dir / "BRAKE").exists()


def test_brake_carries_a_term_and_holds_until_it_ends(tmp_path, monkeypatch):
    e = Env(tmp_path, monkeypatch, tasks=[task_row(i) for i in range(1, 6)])
    e.runner_says({"status": "READY", "task": "T1", "reason": "runner_dead", "infra": True, "calls": []})
    t0 = e.clock.now()
    assert e.loop().run() == 3
    b = _ls(e)["brake"]
    assert b["span"] == 1800 and b["until"] >= t0 + 1800 and not b["half_open"]
    assert e.loop().run() == 3                      # inside the term: nothing runs
    assert e.runs() == 5
    assert any(x.get("reason") == "brake_active" and x.get("retry_at") for x in e.events())


def test_after_the_term_one_trial_pass_runs_and_a_proof_closes_the_brake(tmp_path, monkeypatch):
    e = Env(tmp_path, monkeypatch, tasks=[task_row(i) for i in range(1, 6)])
    e.runner_says({"status": "READY", "task": "T1", "reason": "runner_dead", "infra": True, "calls": []})
    assert e.loop().run() == 3
    e.clock.t += 1801
    e.runner_says({"status": "REVIEW", "task": "T%d" % 2, "calls": [REAL_CALL]})
    assert e.loop(once=True).run() == 0
    assert not (e.state_dir / "BRAKE").exists() and _ls(e)["brake"] is None
    assert _events(e, "brake_half_open") and _events(e, "brake_closed")
    assert e.state()["infra_streak"] == 0


def test_a_failed_trial_doubles_the_term_up_to_two_hours(tmp_path, monkeypatch):
    e = Env(tmp_path, monkeypatch, tasks=[task_row(i) for i in range(1, 6)])
    e.runner_says({"status": "READY", "task": "T1", "reason": "runner_dead", "infra": True, "calls": []})
    assert e.loop().run() == 3
    spans = [_ls(e)["brake"]["span"]]
    for _ in range(4):
        e.clock.t += _ls(e)["brake"]["span"] + 1
        assert e.loop().run() == 3
        spans.append(_ls(e)["brake"]["span"])
    assert spans == [1800, 3600, 7200, 7200, 7200]
    assert any(x.get("doubled") for x in _events(e, "brake"))


def test_a_brake_file_without_a_recorded_term_gets_half_an_hour(env):
    (env.state_dir / "BRAKE").write_text("brake: made by hand\n", encoding="utf-8")
    assert env.loop().run() == 3
    b = _ls(env)["brake"]
    assert b["span"] == 1800
    env.clock.t += 1801
    env.runner_says({"status": "REVIEW", "task": "T1", "calls": [REAL_CALL]})
    assert env.loop(once=True).run() == 0 and not (env.state_dir / "BRAKE").exists()


def test_clear_brake_forgets_the_term(env):
    (env.state_dir / "BRAKE").write_text("brake\n", encoding="utf-8")
    assert env.loop().run() == 3
    env.runner_says({"status": "IDLE", "calls": []})
    env.loop(once=True, clear_brake=True).run()
    assert _ls(env)["brake"] is None and not (env.state_dir / "BRAKE").exists()
