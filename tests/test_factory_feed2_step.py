"""W-feed2 4: the step of the loop starts the cards before its heavy ticks, a busy lock does not end the fill, the fill does not
recount the plan, the rarely-changing ticks keep their term, a slow tick shows in the loop event. Fake runner, no model."""
from tools import agent_factory as F
from tools import factory_loop as L
from test_factory_loop import task_row
from test_factory_pool_loop import pool_env, plog


def _starts(env):
    return [e["tid"] for e in plog(env) if e["ev"] == "start"]


def test_the_first_step_starts_cards_before_the_expensive_ticks(tmp_path, monkeypatch):
    monkeypatch.setenv("POOL_SLEEP", "2.0")
    monkeypatch.setenv("POOL_STATUS", "DONE")
    env = pool_env(tmp_path, monkeypatch, [task_row(1), task_row(2), task_row(3)])
    loop = env.make_loop()
    seen = {}

    def costly(name):
        def tick(*_a, **_k):
            seen.setdefault(name, len(loop.pool.workers))       # the workers live when the tick starts
            loop.clock = (lambda base=loop.clock: base() + 5.0)  # the tick costs 5 s of the loop's clock
        return tick
    for name in ("_sweep_tick", "_links_tick", "_release_tick", "_bisect_tick", "_reslice_tick"):
        monkeypatch.setattr(loop, name, costly(name))
    loop.step()
    assert seen and all(n >= 1 for n in seen.values()), seen


def test_a_busy_lock_once_does_not_end_the_fill(tmp_path, monkeypatch):
    monkeypatch.setenv("POOL_SLEEP", "2.0")
    monkeypatch.setenv("POOL_STATUS", "DONE")
    env = pool_env(tmp_path, monkeypatch, [task_row(1), task_row(2), task_row(3)])
    loop = env.make_loop()
    monkeypatch.setattr(L.Loop, "CLAIM_PAUSE_S", 0.0)
    real, boom = loop.txn, [1]

    def txn(*a, **k):
        if a and boom:                  # only the claim passes a wait
            boom.pop()
            raise F.LockBusy("held")
        return real(*a, **k)
    loop.txn = txn
    out = loop.step()
    assert not (out.action == "WAIT" and out.reason == "state_locked")
    assert len(_starts(env)) >= 2 and not boom


def test_the_fill_does_not_recount_the_resliceable_set_per_card(tmp_path, monkeypatch):
    monkeypatch.setenv("POOL_SLEEP", "2.0")
    monkeypatch.setenv("POOL_STATUS", "DONE")
    env = pool_env(tmp_path, monkeypatch, [task_row(i) for i in range(1, 21)])
    loop = env.make_loop()
    loop.slice_fn = lambda *a, **k: None
    loop.base_sha = L.refresh_mirror(loop.cfg.repo, loop.cfg.branch, loop.mirror)
    calls = []
    monkeypatch.setattr(loop, "_resliceable", lambda *a, **k: calls.append(1) or {})
    tasks, state = loop.load()
    ls = loop.ls()
    now = loop.clock()
    act = loop._act(state, tasks, ls, now)
    calls.clear()
    loop._fill(act, tasks, state, ls, now)
    assert len(calls) <= 2


def test_ticks_of_rare_data_keep_their_term_and_a_slow_tick_is_in_the_event(tmp_path, monkeypatch):
    env = pool_env(tmp_path, monkeypatch, [task_row(1)])
    loop = env.make_loop()
    now = [1000.0]
    monkeypatch.setattr(loop, "clock", lambda: now[0])
    ran = []
    assert loop._tick("x", lambda: ran.append(1) or "a", every=60.0, skipped="s") == "a"
    now[0] += 59
    assert loop._tick("x", lambda: ran.append(1), every=60.0, skipped="s") == "s" and len(ran) == 1      # before its term: costs nothing
    now[0] += 2
    assert loop._tick("x", lambda: ran.append(1) or "b", every=60.0, skipped="s") == "b" and len(ran) == 2

    def slow():
        now[0] += 0.9
    loop._ticks_ms = {}
    loop._tick("slow_one", slow)
    loop._tick("quick", lambda: None)
    assert loop._ticks_ms["slow_one"] > 500 and loop._ticks_ms["quick"] < 500
