"""W-feed2 fix1: the early fill and the step of the loop. No network, no model."""
import json
import threading
import time
import types

from tools import factory_hypo as HY
from tools import factory_loop as L
from test_factory_loop import task_row
from test_factory_pool_loop import pool_env, plog


def test_the_light_ask_can_be_bound_to_one_channel():
    import inspect
    assert 'only_channel' in inspect.signature(L.Loop._light_ask).parameters


def test_sixty_startable_cards_start_before_five_second_ticks(tmp_path, monkeypatch):
    monkeypatch.setenv("POOL_SLEEP", "2.0")
    monkeypatch.setenv("POOL_STATUS", "DONE")
    env = pool_env(tmp_path, monkeypatch, [task_row(i) for i in range(1, 61)])
    loop = env.make_loop()
    seen = {}
    spent = [0.0]

    def started():
        return len([e for e in plog(env) if e["ev"] == "start"])

    def costly(name):
        def tick(*_a, **_k):
            seen.setdefault(name, started())        # the starts made BEFORE this expensive tick
            spent[0] += 5.0
            loop.clock = (lambda base=loop.clock: base() + 5.0)
        return tick
    for name in ("_sweep_tick", "_links_tick", "_release_tick", "_bisect_tick", "_reslice_tick", "_reconcile_tick", "_lost_tick"):
        monkeypatch.setattr(loop, name, costly(name))
    loop.step()
    total = started()
    first = min(seen.values(), default=0)
    assert seen and total >= 2 and first > total // 2, (seen, total)       # most starts of the step went before the first costly tick


def test_the_early_fill_counts_the_resliceable_set_at_most_twice(tmp_path, monkeypatch):
    monkeypatch.setenv("POOL_SLEEP", "2.0")
    monkeypatch.setenv("POOL_STATUS", "DONE")
    env = pool_env(tmp_path, monkeypatch, [task_row(i) for i in range(1, 21)])
    loop = env.make_loop()
    loop.slice_fn = lambda *a, **k: None
    loop.base_sha = L.refresh_mirror(loop.cfg.repo, loop.cfg.branch, loop.mirror)
    calls = []
    monkeypatch.setattr(loop, "_resliceable", lambda *a, **k: calls.append(1) or {})
    loop._early_fill(loop.clock())
    assert 1 <= len(calls) <= 2
    assert len([e for e in plog(env) if e["ev"] == "start"]) >= 2


def test_ready_workers_do_not_stop_the_ticks_of_the_step():
    import inspect
    src = inspect.getsource(L.Loop._step)
    head = src.split('_early_fill')[0]
    assert '_account_done' not in head            # the finished worker is accounted where it always was: after the ticks
