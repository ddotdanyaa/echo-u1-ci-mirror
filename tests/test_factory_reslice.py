"""Slicer queue and generation regressions; replaces the old requeue/refeed owners."""
import json
from pathlib import Path
import pytest
from tools import agent_factory as F
from tools import factory_loop as L
from test_factory_loop import Env, task_row
EMPTY = {"tasks": [], "holds": [], "stale": [], "skipped": []}
def _plan(*rows):
    return F.read_plan({"tasks": list(rows)})

def _row_pair():
    """<id> (code) waits for <id> (its test task); both belong to backlog row <id>."""
    return [task_row(1, depends_on=["T3"]),
            task_row(3, kind="unit_test", backlog_id="B1", touch_files=["tests/test_x3.py"], tests=["tests/test_x3.py"])]

def _loop(e, slice_fn, triage_fn=None):
    return e.loop(triage_fn=triage_fn or (lambda **kw: EMPTY), extra={"slice_fn": slice_fn})

def _queue(loop, row="B1"):
    ls = loop.ls(); ls["to_slice"] = {row: {"at": 0.0, "hints": [], "guard": ""}}; loop.save_ls(ls)

def test_next_action_reslices_or_waits_instead_of_holding():
    tasks = _plan(*_row_pair()); s = F.initial_state(tasks)
    s["tasks"]["T3"].update(status="FAILED", reason="escalated:weak_test")
    assert F.stuck_rows(s, tasks) == {"B1": ["T1", "T3"]}
    assert F.next_action(s, 0.0, 0, False, tasks)["action"] == "HOLD"
    act = F.next_action(s, 0.0, 0, False, tasks, resliceable=frozenset({"B1"}))
    assert act["action"] == "RESLICE" and act["backlog_ids"] == ["B1"]
    wait = F.next_action(s, 0.0, 0, False, tasks, slice_wait_s=120.0)
    assert (wait["action"], wait["reason"], wait["wait_s"]) == ("WAIT", "architect_wait", 120.0)

def test_superseded_rows_do_not_hold_the_loop():
    tasks = _plan(task_row(1), task_row(3, id="T1_r1", backlog_id="B1")); s = F.initial_state(tasks)
    s["tasks"]["T1"].update(status="FAILED", reason="superseded:reslice1"); s["tasks"]["T1_r1"].update(status="PROMOTED")
    assert F.stuck_rows(s, tasks) == {} and F.next_action(s, 0.0, 0, False, tasks)["action"] == "DONE"

def test_the_loop_reslices_a_stuck_row_one_rung_up_each_time(tmp_path, monkeypatch):
    e = Env(tmp_path, monkeypatch, tasks=_row_pair())
    e.set_row("T3", status="FAILED", reason="escalated:weak_test")
    seen = []
    def slicer(row, cause, rung, evidence, **kw):
        seen.append((row, cause, rung))
        return dict(EMPTY, tasks=[task_row(1, id="T1_r%d" % len(seen))])
    loop = _loop(e, slicer)
    out = loop.step()
    st = e.state()["tasks"]
    assert out.action != "HOLD" and seen == [("B1", "first", 0)]
    assert st["T1"]["reason"] == st["T3"]["reason"] == "superseded:reslice1" and st["T1_r1"]["status"] == "READY"
    rec = loop.ls()["reslices"]["B1"]
    assert (rec["n"], rec["used"], rec["version"]) == (1, 0, F.slicer_version())      # the first slicing by this version is free
    e.set_row("T1_r1", status="FAILED", reason="reslice")                              # the new generation fails too
    loop.step()
    assert seen[-1] == ("B1", "stuck", 1) and loop.ls()["reslices"]["B1"]["used"] == 1 and "T1_r2" in e.state()["tasks"]

def test_triage_feeds_the_slicer_queue_and_the_row_is_then_known(tmp_path, monkeypatch):
    seen = []
    feed = lambda **kw: dict(EMPTY, to_slice=[] if "B7" in kw["known_backlog_ids"] else [{"backlog_id": "B7", "hints": [], "guard": ""}])
    e = Env(tmp_path, monkeypatch)
    loop = _loop(e, lambda row, cause, rung, evidence, **kw: seen.append(row), triage_fn=feed)   # the slicer says "not yet"
    outs = [loop.step() for _ in range(3)]
    assert set(seen) == {"B7"} and "B7" in loop.ls()["to_slice"] and all(o.action != "HOLD" for o in outs)

def test_a_void_slicing_keeps_the_old_tasks_and_climbs_a_rung(tmp_path, monkeypatch):
    e = Env(tmp_path, monkeypatch, tasks=[task_row(1)])
    e.set_row("T1", status="FAILED", reason="reslice")
    seen = []
    loop = _loop(e, lambda row, cause, rung, evidence, **kw: seen.append((cause, rung)) or dict(EMPTY))
    loop.step(); loop.step()
    assert seen == [("first", 0), ("stuck", 1)] and e.state()["tasks"]["T1"]["reason"] == "reslice"
    assert [x["status"] for x in e.events() if x["span"] == "reslice"][-1] == "void"

def test_a_slicer_nobody_can_reach_costs_nothing_and_does_not_hold(tmp_path, monkeypatch):
    e = Env(tmp_path, monkeypatch, tasks=[task_row(1)])
    e.set_row("T1", status="FAILED", reason="reslice")
    def nobody(*a, **k): raise L.SliceWait("no channel")
    loop = _loop(e, nobody)
    outs = [loop.step() for _ in range(3)]
    assert "B1" not in (loop.ls().get("reslices") or {}) and loop.ls()["slice_wait"]["B1"] > 0
    assert all(o.action != "HOLD" for o in outs) and outs[-1].reason == "architect_wait"

def test_a_cut_row_is_one_row_and_merged_parts_are_never_touched(tmp_path, monkeypatch):
    parts = [task_row(1, id="P_c1", backlog_id="B1#1"), task_row(3, id="P_c2", backlog_id="B1#2")]
    e = Env(tmp_path, monkeypatch, tasks=parts)
    e.set_row("P_c1", status="PROMOTED", commit="a" * 10); e.set_row("P_c2", status="FAILED", reason="reslice")
    loop = _loop(e, lambda *a, **k: dict(EMPTY, tasks=[task_row(5, id="P_r1", backlog_id="B1")]))
    ls = loop.ls(); ls["parents"] = {"B1": {"code_tasks": ["P_c1", "P_c2"]}}; loop.save_ls(ls)
    loop.step()
    st = e.state()["tasks"]
    assert st["P_c1"]["status"] == "PROMOTED" and st["P_c2"]["reason"] == "superseded:reslice1" and "P_r1" in st
    assert "B1" not in loop.ls()["parents"]                                  # the new whole-row task closes the row itself

def test_no_second_owner_of_a_failed_row_is_left():
    src = Path(L.__file__).read_text(encoding="utf-8")
    for old in ("_idle_requeue", "_requeue_on_new_version", "def _stall(", "factory_requeue.run(", "jam_of(", "_refeed_pick", "_refeed_book"):
        assert old not in src
