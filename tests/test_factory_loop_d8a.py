"""factory_loop round <id>: addressed deferral instead of an endless brake, a brake with a term (d8a group)."""
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


# ---- temporary faults never grow the brake series ---------------------------------------------------

@pytest.mark.parametrize("reason", ["transient", "env_shortage"])
def test_temporary_faults_do_not_brake_even_when_flagged_infra(tmp_path, monkeypatch, reason):
    e = two_tasks(tmp_path, monkeypatch, n=5)
    loop = e.loop(rng=random.Random(1))
    for i in range(1, 6):
        _says(e, "T%d" % i, reason)
        out = loop.step()
        assert out.code is None and out.status == "deferred"
        e.clock.t += 2000                                  # the channel pause is over
    assert e.state()["infra_streak"] == 0 and not (e.state_dir / "BRAKE").exists()
    assert len(_events(e, "deferred")) == 5


def test_a_permanent_fault_still_brakes_after_five_tasks(tmp_path, monkeypatch):
    e = two_tasks(tmp_path, monkeypatch, n=5)
    loop = e.loop(rng=random.Random(1))
    for i in range(1, 6):
        _says(e, "T%d" % i, "runner_dead")
        out = loop.step()
    assert out.code == 3 and (e.state_dir / "BRAKE").exists()


def test_a_dead_channel_reason_is_never_temporary(tmp_path, monkeypatch):
    e = two_tasks(tmp_path, monkeypatch, n=5)
    loop = e.loop(rng=random.Random(1))
    for i in range(1, 6):
        _says(e, "T%d" % i, "dead")
        out = loop.step()
    assert out.code == 3


# ---- exponential, jittered, per key --------------------------------------------------------------------
