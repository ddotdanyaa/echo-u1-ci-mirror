"""factory_loop round <id>: per-key pauses (d8e group)."""
import json
import random
import pytest
from tools import agent_factory as F
from tools import factory_loop as L
from test_factory_loop import Env, Clock, git, task_row, two_tasks, env, empty_env, BRANCH, PY  # noqa: <id>
from test_factory_loop_d8a import _events, _ls, _says  # noqa: <id>
from test_factory_loop_git3 import REAL_CALL  # noqa: <id>


def test_pause_doubles_while_the_series_is_fresh_and_stops_at_the_cap(env):
    loop = env.loop(rng=random.Random(3))
    delays = []
    for _ in range(8):
        _says(env, "T1", "transient")
        loop.step()
        delays.append(_events(env, "deferred")[-1]["delay_s"])
        env.clock.t += 130
        env.set_row("T1", not_before=0)
    # fac-68 (replaces 60, 120 ... 1800): a transient (5xx) is a refusal of one request, not an overload: 5 s, doubling only
    # for repeats in a row, 120 s at most
    expect = [5, 5, 10, 20, 40, 80, 120, 120]
    for got, want in zip(delays, expect):
        assert want * 0.9 - 0.01 <= got <= want * 1.1 + 0.01
    assert max(delays) <= 132


def test_a_channel_fault_pauses_the_channel_not_the_task(env):
    _says(env, "T1", "rate_limited_suspect", calls=[{"channel": "c1"}])
    loop = env.loop(rng=random.Random(1))
    now = env.clock.now()
    loop.step()
    ls = _ls(env)
    assert not ls.get("channel_until")                          # the loop does not wait: only c1 cools (21.11)
    assert env.state()["channel_quotas"]["channel_cool"]["c1"] >= now + 54
    assert not env.state()["tasks"]["T1"].get("not_before")
    ev = _events(env, "deferred")[-1]
    assert ev["scope"] == "channel" and ev["key"] == "ch:c1" and ev["backoff_n"] == 1


def test_a_task_fault_pauses_the_task_not_the_channel(env):
    _says(env, "T1", "env_shortage")
    loop = env.loop(rng=random.Random(1))
    now = env.clock.now()
    loop.step()
    assert env.state()["tasks"]["T1"]["not_before"] >= now + 54
    assert not _ls(env).get("channel_until")
    assert _events(env, "deferred")[-1]["scope"] == "task"


def test_proof_of_work_empties_the_pauses(env):
    loop = env.loop(rng=random.Random(1))
    _says(env, "T1", "transient")
    loop.step()
    assert _ls(env)["backoff"]
    env.set_row("T1", not_before=0)
    env.runner_says({"status": "REVIEW", "task": "T1", "calls": [REAL_CALL]})
    loop.step()
    assert _ls(env)["backoff"] == {}


# ---- env_shortage is a defer reason: no strike, no block ------------------------------------------------------

def test_env_shortage_is_a_defer_reason_and_never_blocks_or_strikes():
    assert "env_shortage" in F.DEFER_REASONS
    tasks = F.read_plan([task_row(1)])
    state = F.initial_state(tasks)
    for n in range(1, 8):
        token = F.acquire(tasks, state, "T1", now=n * 1000, charge=False)
        F.defer(state, "T1", token, "env_shortage", 5, now=n * 1000)
    row = state["tasks"]["T1"]
    assert row["status"] == "READY" and not state.get("strikes") and row["defer_reason"] == "env_shortage"


@pytest.mark.parametrize("reason", ["rate_limited_suspect", "channel_timeout", "429"])
def test_channel_faults_do_not_brake_even_when_flagged_infra(tmp_path, monkeypatch, reason):
    e = two_tasks(tmp_path, monkeypatch, n=5)
    loop = e.loop(rng=random.Random(1))
    for i in range(1, 6):
        _says(e, "T%d" % i, reason)
        out = loop.step()
        assert out.code is None and out.status == "deferred"
        e.clock.t += 2000                                  # the channel pause is over
    assert e.state()["infra_streak"] == 0 and not (e.state_dir / "BRAKE").exists()
    assert len(_events(e, "deferred")) == 5
