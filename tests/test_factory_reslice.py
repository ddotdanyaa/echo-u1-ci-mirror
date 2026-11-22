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


def test_a_row_with_old_strikes_gets_a_live_new_generation(tmp_path, monkeypatch):
    e = Env(tmp_path, monkeypatch, tasks=[task_row(1)])
    e.set_row("T1", status="FAILED", reason="reslice")
    loop = _loop(e, lambda *a, **k: dict(EMPTY, tasks=[task_row(1, id="T1_r1")]))
    loop._tx(lambda st: st.setdefault("strikes", {}).update({"bl:B1": 6}))
    loop.step()
    assert e.state()["tasks"]["T1_r1"]["status"] == "READY"


def test_a_portion_already_in_the_plan_is_applied_again_harmlessly(tmp_path, monkeypatch):
    e = Env(tmp_path, monkeypatch, tasks=[task_row(1)])
    e.set_row("T1", status="FAILED", reason="reslice")
    loop = _loop(e, None)
    portion = dict(EMPTY, tasks=[task_row(1, id="T1_r1")])
    F.append_tasks(loop.plan_path, portion["tasks"])
    loop._apply_portion("B1", 1, portion, "first")
    loop._apply_portion("B1", 1, portion, "first")
    assert e.state()["tasks"]["T1_r1"]["status"] == "READY"
    assert loop.ls()["reslices"]["B1"]["n"] == 1


def test_queue_preserves_guard_and_optional_row_fields(tmp_path, monkeypatch):
    e = Env(tmp_path, monkeypatch)
    entry = {"backlog_id": "B7", "hints": [], "guard": "tests/test_x7.py::test_red", "text": "row", "priority": 1}
    loop = _loop(e, lambda *a, **k: None, lambda **kw: dict(EMPTY, to_slice=[entry]))
    loop.step()
    rec = loop.ls()["to_slice"]["B7"]
    assert all(rec[key] == value for key, value in entry.items())


def test_a_slicer_error_waits_for_only_its_row(tmp_path, monkeypatch):
    e = Env(tmp_path, monkeypatch)
    seen = []
    def slicer(row, *a, **kw):
        seen.append(row)
        if row == "B1":
            raise RuntimeError("broken response")
    loop = _loop(e, slicer)
    ls = loop.ls()
    ls["to_slice"] = {b: {"at": 0, "hints": [], "guard": ""} for b in ("B1", "B3")}
    loop.save_ls(ls)
    loop.step()
    assert seen == ["B1", "B3"] and set(loop.ls()["slice_wait"]) == {"B1"}
    assert e.state()["infra_streak"] == 0


def test_the_loop_starts_workers_with_the_ladder(tmp_path, monkeypatch):
    e = Env(tmp_path, monkeypatch, tasks=[task_row(1)])
    seen, commands = [], []
    loop = _loop(e, lambda row, cause, *a, **kw: seen.append((row, cause)))
    from tools import factory_process
    class Captured(Exception):
        pass
    def capture(cmd, **kw):
        commands.append(cmd)
        raise Captured()
    monkeypatch.setattr(factory_process, "start_owned", capture)
    loop.base_sha = "a" * 40
    monkeypatch.setattr(loop, "_snapshot", lambda base: e.repo)
    tasks, state = loop.load()
    with pytest.raises(Captured):
        loop._admit("T1", tasks, loop.ls())
    cmd = commands[0]
    assert cmd[cmd.index("--reslice-after") + 1] == "2"
    for _ in range(2):
        with loop.txn() as (tasks, state):
            token = F.acquire(tasks, state, "T1", now=e.clock.t)
            F.settle(state, "T1", token, tests_ok=False, evidence="a" * 64, reslice_after=F.RESLICE_AFTER)
    assert e.state()["tasks"]["T1"]["reason"] == "reslice"
    tasks, state = loop.load()
    loop._reslice_tick(tasks, state, loop.ls(), e.clock.t)
    assert seen == [("B1", "first")]


def test_a_row_out_of_reslices_is_quarantined_with_the_version(tmp_path, monkeypatch):
    e = Env(tmp_path, monkeypatch, tasks=[task_row(1)])
    e.set_row("T1", status="FAILED", reason="reslice")
    loop = _loop(e, lambda *a, **k: pytest.fail("no budget is left: the slicer must not be asked"))
    ls = loop.ls(); ls["reslices"] = {"B1": {"n": 2, "used": F.MAX_RESLICES, "version": F.slicer_version()}}; loop.save_ls(ls)
    loop.step()
    row = e.state()["tasks"]["T1"]
    assert (row["reason"], row["q_ver"]) == ("quarantine", F.slicer_version())
    assert loop.ls()["quarantine"]["B1"]["version"] == F.slicer_version()

def test_three_void_slicings_quarantine_a_row_that_has_no_task(tmp_path, monkeypatch):
    seen = []
    e = Env(tmp_path, monkeypatch)
    loop = _loop(e, lambda row, cause, rung, evidence, **kw: seen.append((cause, rung)) or dict(EMPTY)); _queue(loop)
    for _ in range(5):
        loop.step()
    assert seen == [("first", 0), ("stuck", 1), ("stuck", 2)]                 # free model, paid Sonnet, Claude Code: then no more
    assert "B1" in loop.ls()["quarantine"] and "B1" not in loop.ls()["to_slice"]

def test_a_new_slicer_version_reopens_quarantine_once(tmp_path, monkeypatch):
    e = Env(tmp_path, monkeypatch, tasks=[task_row(1), task_row(3), task_row(5)])
    e.set_row("T1", status="FAILED", reason="quarantine", q_ver="s0")        # quarantined by an old slicer
    e.set_row("T3", status="FAILED", reason="quarantine")                    # an old strike quarantine: no version at all
    e.set_row("T5", status="FAILED", reason="superseded_by_guard")           # owned by a guard task: not a quarantine
    loop = _loop(e, lambda row, cause, rung, evidence, **kw: dict(EMPTY, tasks=[task_row(1, id="T1_r3")]) if row == "B1" else None)
    ls = loop.ls(); ls["reslices"] = {"B1": {"n": 2, "used": 2, "version": "s0"}}
    ls["quarantine"] = {"B9": {"version": "s0", "at": 0.0, "why": "void"}}; loop.save_ls(ls)
    assert loop._reenter_on_new_slicer() == 3                                # <id>, <id> by their tasks, <id> by its row record
    st = e.state()["tasks"]
    assert st["T1"]["reason"] == st["T3"]["reason"] == "reenter" and st["T5"]["reason"] == "superseded_by_guard"
    assert "B9" in loop.ls()["to_slice"] and "B9" not in loop.ls()["quarantine"]
    assert loop._reenter_on_new_slicer() == 0                                # the same version: nothing is given back twice
    loop.step()                                                              # <id> is sliced again, free of charge, ids go on from n
    rec = loop.ls()["reslices"]["B1"]
    assert (rec["n"], rec["used"], rec["version"]) == (3, 0, F.slicer_version()) and "T1_r3" in e.state()["tasks"]

def test_holds_and_not_code_of_an_old_slicer_expire_at_once(tmp_path, monkeypatch):
    e = Env(tmp_path, monkeypatch); loop = e.loop(triage_fn=lambda **kw: EMPTY)
    ls = loop.ls()
    ls["holds"] = {"B%d" % i: "old question" for i in range(30)}; ls["hold_ver"] = {"B%d" % i: "s0" for i in range(30)}
    loop.save_ls(ls)
    known = loop._triage_prepare(e.state(), {}, loop.ls(), e.clock.t)["kwargs"]["known_backlog_ids"]
    assert [b for b in known if b.startswith("B")] == []                 # all 30 expire in one pass: no trickle

def test_a_quarantined_row_returns_after_six_hours_or_when_a_new_rung_appears(tmp_path, monkeypatch):
    e = Env(tmp_path, monkeypatch); loop = _loop(e, lambda *a, **k: None)              # the slicer says "not yet"
    v, now = F.slicer_version(), e.clock.t
    ls = loop.ls()
    ls["quarantine"] = {"B1": {"version": v, "ladder": "", "at": now, "why": "void"},
                        "B2": {"version": v, "ladder": "", "at": now - 90000, "why": "void"}}
    ls["reslices"] = {b: {"n": 3, "used": 2, "version": v} for b in ("B1", "B2")}; loop.save_ls(ls)
    loop.step()
    assert "B2" in loop.ls()["to_slice"] and "B1" in loop.ls()["quarantine"]            # six hours have passed for <id> only
    monkeypatch.setattr(loop, "_ladder_sig", lambda: "free,free_main,paid")             # the key has come
    loop.step()
    assert "B1" in loop.ls()["to_slice"] and loop.ls()["reslices"]["B1"]["used"] == 0


def test_a_hold_names_what_holds_it():
    tasks = _plan(*_row_pair()); s = F.initial_state(tasks)
    s["tasks"]["T3"].update(status="FAILED", reason="quarantine")
    act = F.next_action(s, 0.0, 0, False, tasks)
    assert act["action"] == "HOLD" and act["blockers"] == {"ready_dead_dep": 1, "quarantine": 1}

def test_the_hold_event_and_stats_carry_the_blockers(tmp_path, monkeypatch):
    e = Env(tmp_path, monkeypatch, tasks=[task_row(1, only_opus=True)])
    loop = e.loop(triage_fn=lambda **kw: EMPTY)
    outs = [loop.step() for _ in range(3)]
    assert outs[-1].action == "HOLD" and e.loop_events()[-1]["blockers"] == {"only_opus": 1}
    assert json.loads((e.state_dir / "stats.json").read_text(encoding="utf-8"))["blockers"] == {"only_opus": 1}


# ---- review findings: re-entry, void stale, error isolation, reds ---------------------------------------------------

def test_reentry_queues_only_a_row_that_has_no_task(tmp_path, monkeypatch):
    e = Env(tmp_path, monkeypatch, tasks=[task_row(1)])
    e.set_row("T1", status="FAILED", reason="quarantine", q_ver="s0")
    loop = _loop(e, lambda *a, **k: None)
    ls = loop.ls(); ls["quarantine"] = {"B9": {"version": "s0", "at": 0.0, "why": "void"}}; loop.save_ls(ls)
    assert loop._reenter_on_new_slicer() == 2
    assert e.state()["tasks"]["T1"]["reason"] == "reenter"
    assert "B9" in loop.ls()["to_slice"] and "B1" not in loop.ls()["to_slice"]      # <id> is stuck: the slicer takes it as stuck

def test_a_void_stale_slicing_counts_as_an_attempt(tmp_path, monkeypatch):
    e = Env(tmp_path, monkeypatch, tasks=[task_row(1)])
    e.set_row("T1", status="FAILED", reason="reslice:stale")
    seen = []
    loop = _loop(e, lambda row, cause, rung, evidence, **kw: seen.append((cause, rung)) or dict(EMPTY))
    ls = loop.ls(); ls["reslices"] = {"B1": {"n": 1, "used": 0, "stale": False, "version": F.slicer_version()}}; loop.save_ls(ls)
    loop.step()
    assert seen == [("stale", 0)] and loop.ls()["reslices"]["B1"]["used"] == 1

def test_a_failing_quarantine_pass_is_an_event_and_slicing_goes_on(tmp_path, monkeypatch):
    e = Env(tmp_path, monkeypatch, tasks=[task_row(1)])
    e.set_row("T1", status="FAILED", reason="reslice")
    seen = []
    loop = _loop(e, lambda row, cause, rung, evidence, **kw: seen.append(row) or dict(EMPTY))
    def boom(*a, **k): raise RuntimeError("disk gone")
    monkeypatch.setattr(loop, "_quarantine_rows", boom)
    out = loop.step()
    assert seen == ["B1"] and out.action != "CRASH"
    assert any(x["span"] == "reslice" and x.get("status") == "error" for x in e.events())

def test_one_row_that_fails_does_not_stop_the_next_one(tmp_path, monkeypatch):
    e = Env(tmp_path, monkeypatch, tasks=[task_row(1), task_row(3, backlog_id="B2")])
    e.set_row("T1", status="FAILED", reason="reslice"); e.set_row("T3", status="FAILED", reason="reslice")
    seen = []
    def slicer(row, cause, rung, evidence, **kw):
        seen.append((row, evidence))
        if row == "B1": raise RuntimeError("broken row")
        return dict(EMPTY, tasks=[task_row(5, id="T3_r1", backlog_id="B2")])
    loop = _loop(e, slicer)
    out = loop.step()
    assert [r for r, _ in seen] == ["B1", "B2"] and out.action != "CRASH"
    assert "T3_r1" in e.state()["tasks"] and loop.ls()["slice_wait"]["B1"] > 0
    assert "T3" in seen[1][1] and "T1" not in seen[1][1]                              # the evidence is the row's own
    assert any(x["span"] == "reslice" and x.get("status") == "error" for x in e.events())

def test_a_rejected_task_starts_again_with_no_red_attempts(tmp_path, monkeypatch):
    e = Env(tmp_path, monkeypatch, tasks=[task_row(1)])
    e.set_row("T1", status="PROMOTED", commit="a" * 10, reds=2, attempts=3)
    loop = e.loop(triage_fn=lambda **kw: EMPTY)
    tasks, state = loop.load()
    loop._reject_answer("T1", "B1", state, "bad")
    row = e.state()["tasks"]["T1"]
    assert (row["status"], row["reds"], row["attempts"]) == ("READY", 0, 0)
