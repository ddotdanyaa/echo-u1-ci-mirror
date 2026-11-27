"""Feeding without idle: while runners work, the slow free-model passes (triage, the head's hold picks) run in one
background thread owned by the loop; the loop's own thread keeps admitting and reaping and is the only writer of the
plan, the state and the loop state. No model, no network: the triage and the model call are fakes with real sleeps."""
import json
import threading
import time

from tools import agent_factory as F
from tools import factory_loop as L
from test_factory_loop import task_row
from test_factory_pool_loop import pool_env, plog, spans
from tests.test_factory_loop_holds import setup as holds_setup, answers


def _empty(**_kw):
    return {"tasks": [], "holds": [], "skipped": [], "stale": [], "deferred": []}


def _portion_row(n):
    return task_row(n)


def _step_until(loop, env, tid, limit=12):
    for _ in range(limit):
        loop.step()
        if any(e["ev"] == "start" and e["tid"] == tid for e in plog(env)):
            return True
    return False


def test_a_slow_triage_does_not_hold_back_the_admission_of_a_ready_task(tmp_path, monkeypatch):
    monkeypatch.setenv("POOL_SLEEP", "3.0")
    monkeypatch.setenv("POOL_STATUS", "DONE")
    env = pool_env(tmp_path, monkeypatch, [task_row(1)])
    started = threading.Event()

    def slow_triage(**_kw):
        started.set()
        time.sleep(5.0)                                  # a free-model pass lasts 17-50 s live
        return _empty()
    added = {}

    def feeder():                                        # a task becomes READY one second into the triage
        started.wait(20)
        time.sleep(1.0)
        F.append_tasks(env.state_dir / "plan.json", [_portion_row(2)])
        added["t"] = time.time()
    th = threading.Thread(target=feeder)
    th.start()
    loop = env.make_loop(triage_fn=slow_triage)
    try:
        assert _step_until(loop, env, "T%d" % 2)
    finally:
        th.join(30)
        loop._bg_cancel.set()
    lag = spans(env)["T%d" % 2]["start"] - added["t"]
    assert lag < 1.0, "the ready task waited %.2f s behind the triage" % lag


def test_one_triage_in_flight_and_its_result_is_applied_by_the_loop_thread(tmp_path, monkeypatch):
    monkeypatch.setenv("POOL_SLEEP", "2.5")
    monkeypatch.setenv("POOL_STATUS", "DONE")
    env = pool_env(tmp_path, monkeypatch, [task_row(1)])
    live, peak, calls, threads = [0], [0], [], set()

    def triage(**_kw):
        live[0] += 1
        peak[0] = max(peak[0], live[0])
        threads.add(threading.get_ident())
        calls.append(1)
        try:
            time.sleep(1.0)
            return dict(_empty(), tasks=[_portion_row(9)]) if len(calls) == 1 else _empty()
        finally:
            live[0] -= 1
    loop = env.make_loop(triage_fn=triage)
    writers = set()
    real_save = loop.save_ls

    def save(ls):
        writers.add(threading.get_ident())
        return real_save(ls)
    loop.save_ls = save
    try:
        assert _step_until(loop, env, "T9")
    finally:
        loop._bg_cancel.set()
    main = threading.get_ident()
    assert peak[0] == 1 and calls
    assert threads and main not in threads               # the triage ran in the background thread
    assert writers == {main}                             # the loop state is written by the loop thread only
    ev = [e for e in env.events() if e["span"] == "triage" and e.get("status") == "added"]
    assert ev and ev[0].get("prefetch") is True


def test_a_triage_cut_by_the_end_of_the_loop_loses_nothing(tmp_path, monkeypatch):
    env = pool_env(tmp_path, monkeypatch, [task_row(1)])
    gate = threading.Event()

    def blocked(**_kw):
        gate.wait(10)
        return dict(_empty(), tasks=[_portion_row(7)])
    loop = env.make_loop(triage_fn=blocked)
    tasks, state = loop.load()
    assert loop._triage_prefetch(state, tasks, loop.ls(), loop.clock())
    assert not loop._triage_prefetch(state, tasks, loop.ls(), loop.clock())      # at most one in flight
    plan = json.loads((env.state_dir / "plan.json").read_text(encoding="utf-8"))
    assert [t["id"] for t in plan["tasks"]] == ["T1"] and loop.ls().get("triage_empty") is None
    loop._bg_cancel.set()                                # the loop ended: the cut portion is never applied
    gate.set()
    loop._bg.done.wait(5)
    # the next start asks the same portion again, synchronously, and keeps everything
    (tmp_path / "again").mkdir()
    again = pool_env(tmp_path / "again", monkeypatch, [task_row(1)])
    second = again.make_loop(triage_fn=lambda **_kw: dict(_empty(), tasks=[_portion_row(7)]))
    t2, s2 = second.load()
    out = second._triage(s2, t2, second.ls(), second.clock())
    assert out.status == "added"


def test_hold_picks_run_in_the_background_while_a_runner_works(tmp_path, monkeypatch):
    env, loop, calls = holds_setup(tmp_path, monkeypatch)
    threads = []

    def slow_ask(text, **kw):
        threads.append(threading.get_ident())
        time.sleep(1.0)
        calls.append((text, kw))
        return "ok", "google/x", '{"touch_files": ["echo_sync/b.py"], "note": "Change g1 in b"}', 7
    monkeypatch.setattr(loop, "_light_ask", slow_ask)
    loop.pool.workers[0] = L.Worker(slot=0, tid="TZ", token=None, base_sha="")
    loop._last_out = L.Outcome(action="HOLD")
    t0 = time.monotonic()
    loop._head_holds()
    assert time.monotonic() - t0 < 0.5                   # the ask is not made in this thread
    assert loop._bg is not None and not answers(env)
    loop._bg.done.wait(10)
    loop._bg_poll()
    assert threading.get_ident() not in threads
    assert answers(env)[0]["backlog_id"] == "B9"
    assert loop.ls()["head_holds"]["B9"]["status"] == "answered"
    loop.pool.workers.clear()


def test_a_low_ready_queue_does_not_wait_for_the_twenty_minute_gate(tmp_path, monkeypatch):
    env, loop, calls = holds_setup(tmp_path, monkeypatch)
    loop.pool.workers[0] = L.Worker(slot=0, tid="TZ", token=None, base_sha="")
    ls = loop.ls()
    ls["holds_at"] = loop.clock() - 60                   # the last pass was a minute ago, the gate says 20 minutes
    loop.save_ls(ls)
    loop._last_out = L.Outcome(action="RUN")             # busy: not the idle trigger
    loop._head_holds()                                   # READY = 1 < the pool: the pick starts
    assert loop._bg is not None
    loop._bg.done.wait(10)
    loop._bg_poll()
    assert len(calls) == 1 and answers(env)[0]["backlog_id"] == "B9"
    loop.pool.workers.clear()


def test_a_full_ready_queue_keeps_the_gate(tmp_path, monkeypatch):
    env, loop, calls = holds_setup(tmp_path, monkeypatch)
    F.append_tasks(loop.plan_path, [_portion_row(2), _portion_row(3)])             # READY = 3
    loop.pool.workers[0] = L.Worker(slot=0, tid="TZ", token=None, base_sha="")
    ls = loop.ls()
    ls["holds_at"] = loop.clock() - 60
    loop.save_ls(ls)
    loop._last_out = L.Outcome(action="RUN")
    loop._head_holds()
    assert loop._bg is None and not calls
    loop.pool.workers.clear()
