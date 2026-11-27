"""W-tick2: an unknown disposition answer (None) skips the state-changing ticks; reslice reads fresh before its rows."""
import os
import time

from tools import agent_factory_import as imp
from tools import factory_loop as L
from test_factory_loop import task_row
from test_factory_pool_loop import pool_env

F = L.F


def _loop(tmp_path, monkeypatch, answer=None):
    env = pool_env(tmp_path, monkeypatch, [task_row(1)])
    loop = env.make_loop()
    Path = type(tmp_path)
    Path(loop.cfg.backlog).write_text(
        "## 4. Rows\n\n| ID | P | state | text |\n|---|---|---|---|\n| S2 | P1 | open | an open row |\n\n## 5. End\n", encoding="utf-8")
    calls = []
    monkeypatch.setattr(imp, "row_dispositions", lambda *a, **k: calls.append(1) or dict(answer or {}))
    loop.err = lambda *a, **k: None
    return loop, calls


def _state_with_lost_row():
    return {"tasks": {"X_r1": {"backlog_id": "S2", "status": "FAILED", "reason": "gone"}}}


def test_dispositions_strict_is_none_until_the_current_answer_exists(tmp_path, monkeypatch):
    loop, calls = _loop(tmp_path, monkeypatch, {"A": ("closed", "one")})
    gate = __import__("threading").Event()
    monkeypatch.setattr(imp, "row_dispositions", lambda *a, **k: gate.wait(5) and {"A": ("closed", "one")})
    assert loop._dispositions(1000.0, strict=True) is None            # first call: unknown, not {}
    assert loop._dispositions(1000.1) == {}                           # the report: nothing known yet
    gate.set()
    assert loop._disp_job.done.wait(5)
    assert loop._dispositions(1001.0, strict=True) == {"A": ("closed", "one")}
    os.utime(loop.cfg.backlog, (time.time() + 50, time.time() + 50))  # the backlog was edited: the old answer is stale
    assert loop._dispositions(1002.0, strict=True) is None
    job = loop._disp_job
    assert loop._dispositions(1002.1) == {"A": ("closed", "one")}     # the report keeps the last known answer
    assert job.done.wait(5)
    assert loop._dispositions(1003.0, strict=True) == {"A": ("closed", "one")}


def test_dispositions_failed_pass_is_unknown_for_strict(tmp_path, monkeypatch):
    loop, calls = _loop(tmp_path, monkeypatch, {"A": ("closed", "one")})
    loop._dispositions(1000.0)
    assert loop._disp_job.done.wait(5)
    assert loop._dispositions(1000.5, strict=True) == {"A": ("closed", "one")}
    os.utime(loop.cfg.backlog, (time.time() + 50, time.time() + 50))

    def boom(*a, **k):
        raise RuntimeError("git down")
    monkeypatch.setattr(imp, "row_dispositions", boom)
    loop._dispositions(1001.0)
    assert loop._disp_job.done.wait(5)
    assert loop._dispositions(1002.0, strict=True) is None            # the old answer is not the answer for this backlog
    assert loop._dispositions(1002.0) == {"A": ("closed", "one")}


def test_lost_tick_first_call_returns_nothing_and_writes_no_version_mark(tmp_path, monkeypatch):
    loop, calls = _loop(tmp_path, monkeypatch)
    monkeypatch.setattr(F, "is_terminal", lambda reason: True)
    tasks, state = loop.load()
    state = _state_with_lost_row()
    assert loop._lost_rows(tasks, state, 1000.0) is None
    cur = loop.ls()
    assert not cur.get("to_slice") and "holds_lift_ver" not in cur and "not_code_recheck_ver" not in cur, cur
    assert loop._disp_job.done.wait(5)
    out = loop._lost_rows(tasks, state, 1001.0)                       # the answer is ready: as before the branch
    cur = loop.ls()
    assert out is not None
    assert cur.get("holds_lift_ver") == F.slicer_version() and cur.get("not_code_recheck_ver") == F.slicer_version()
    assert "S2" in (cur.get("to_slice") or {}), cur


def test_lost_tick_with_a_known_row_is_not_sliced(tmp_path, monkeypatch):
    loop, calls = _loop(tmp_path, monkeypatch, {"S2": ("closed", "by a commit")})
    monkeypatch.setattr(F, "is_terminal", lambda reason: True)
    tasks, state = loop.load()
    state = _state_with_lost_row()
    assert loop._lost_rows(tasks, state, 1000.0) is None
    assert loop._disp_job.done.wait(5)
    loop._lost_rows(tasks, state, 1001.0)
    assert "S2" not in (loop.ls().get("to_slice") or {})


def test_supply_return_skips_while_dispositions_unknown(tmp_path, monkeypatch):
    loop, calls = _loop(tmp_path, monkeypatch)
    tasks, state = loop.load()
    state = _state_with_lost_row()
    monkeypatch.setattr(F, "is_terminal", lambda reason: True)
    assert loop._supply_invariant(tasks, state, loop.ls(), 1000.0) is None      # unknown: nothing returned
    assert not loop.ls().get("to_slice") and not loop.ls().get("supply_returned")
    assert loop._disp_job.done.wait(5)
    assert loop._supply_invariant(tasks, state, loop.ls(), 1001.0) is not None   # as before the branch
    assert "S2" in (loop.ls().get("to_slice") or {})


def test_reslice_first_row_sees_the_plan_changed_earlier_in_the_same_step(tmp_path, monkeypatch):
    env = pool_env(tmp_path, monkeypatch, [task_row(1)])
    loop = env.make_loop()
    seen = []

    def slicer(bid, cause, rung, evidence, gen=1, tasks=None, state=None, **k):
        seen.append(state.get("probe"))
        return None
    loop.slice_fn = slicer
    tasks, state = loop.load()                                        # the caller's read ...
    monkeypatch.setattr(loop, "_resliceable", lambda *a, **k: {"B1": "first"})
    monkeypatch.setattr(loop, "_slice_watch", lambda *a, **k: None)

    def quarantine(*a, **k):                                          # ... then a tick of the step changes the plan
        loop._tx(lambda st: st.setdefault("probe", []).append("q"))
    monkeypatch.setattr(loop, "_quarantine_rows", quarantine)
    monkeypatch.setattr(loop, "_apply_parked", lambda: 0)
    real = loop.load
    calls = []
    loop.load = lambda: calls.append(1) or real()
    loop._reslice_tick(tasks, state, loop.ls(), loop.clock())
    assert seen == [["q"]], seen
