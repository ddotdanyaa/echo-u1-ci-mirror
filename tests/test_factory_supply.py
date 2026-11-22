"""<id> (owner): the slicer keeps 15-20 independent one-file tasks READY; a row of more than 3 files is cut into
one-file parts (each with its own guard narrowed to the file's functions); a task that fails twice on the same reason
after a tier escalation is quarantined (or sliced), never retried for budget."""
import json

from tools import agent_factory as F
from tools import agent_factory_import as imp
from tools import factory_loop as L
from test_factory_decompose import _repo, _paths, MODULES
from test_factory_loop import Env, task_row, env, empty_env  # noqa: <id>
from test_factory_loop import _reject


FOUR = "Правим контроллер реплик: " + _paths(["a3", "a4", "a5", "a6"]) + ", все вместе при живом плане и тишине в канале"
TWO = "Правим контроллер реплик: " + _paths(["a3", "a4"]) + ", все вместе при живом плане и тишине в канале"


# ---- 1. more than 3 files -> a chain of one-file sub-tasks ------------------------------------------------------

def test_slice_threshold_is_three_files():
    assert imp.SLICE_FILES == 3


def test_a_row_of_four_files_is_cut_into_one_file_parts(tmp_path):
    root, b = _repo(tmp_path, FOUR)
    r = imp.triage_portion(b, root, set(), 20)
    assert r["holds"] == [] and r["skipped"] == []
    code = [t for t in r["tasks"] if t["kind"] == "code"]
    assert sorted(t["touch_files"][0] for t in code) == ["echo_sync/a%d.py" % i for i in (3, 4, 5, 6)]
    assert all(len(t["touch_files"]) == 1 and t["parent"] == "B1" and t["parts"] == 4 for t in code)
    assert all(not t.get("depends_on") or all(d.endswith("_test") for d in t["depends_on"]) for t in code)   # independent of each other
    F.read_plan(r["tasks"])


def test_three_files_stay_one_task(tmp_path):
    row = "Правим контроллер реплик: " + _paths(["a3", "a4", "a5"]) + ", все вместе при живом плане и тишине в канале"
    root, b = _repo(tmp_path, row)
    r = imp.triage_portion(b, root, set(), 20)
    code = [t for t in r["tasks"] if t["kind"] == "code"]
    assert len(code) == 1 and len(code[0]["touch_files"]) == 3 and not r["parents"]


def test_each_part_has_its_guard_narrowed_to_its_file_functions(tmp_path):
    root, b = _repo(tmp_path, FOUR)
    trace = {"B1": [("echo_sync/a3.py", "f_a3", 1), ("echo_sync/a4.py", "f_a4", 1), ("echo_sync/zzz.py", "other", 3)]}
    r = imp.triage_portion(b, root, set(), 20, trace=trace)
    code = {t["touch_files"][0]: t for t in r["tasks"] if t["kind"] == "code"}
    assert code["echo_sync/a3.py"]["guard_functions"] == ["f_a3"] and "f_a3" in code["echo_sync/a3.py"]["goal"]
    assert code["echo_sync/a4.py"]["guard_functions"] == ["f_a4"]
    assert "guard_functions" not in code["echo_sync/a5.py"]          # the trace names no function there: no invented narrowing
    assert "f_a4" not in code["echo_sync/a3.py"]["goal"]
    F.read_plan(r["tasks"])


def test_a_failed_row_is_force_sliced_even_with_two_files(tmp_path):
    root, b = _repo(tmp_path, TWO)
    plain = imp.triage_portion(b, root, set(), 20)
    assert not plain["parents"]
    r = imp.triage_portion(b, root, set(), 20, force_slice={"B1"})
    code = [t for t in r["tasks"] if t["kind"] == "code"]
    assert [t["touch_files"] for t in code] == [["echo_sync/a3.py"], ["echo_sync/a4.py"]]
    assert r["parents"][0]["parts"] == 2


# ---- 2. READY kept at 15 ----------------------------------------------------------------------------------------

def _tri(calls):
    def fn(**kw):
        calls.append(kw)
        return {"tasks": [], "holds": [], "stale": [], "skipped": [], "events": [], "deferred": [],
                "profile_attempts": {}, "parents": []}
    return fn


def _topup(e, loop):
    tasks, state = loop.load()
    ls = loop.ls()
    started = loop._ready_topup(state, tasks, ls, loop.clock())
    if loop._bg is not None:
        loop._bg.done.wait(10)
        loop._bg_poll()
    return started


def test_ready_below_target_prefetches_a_triage_without_waiting(tmp_path, monkeypatch):
    e = Env(tmp_path, monkeypatch, tasks=[task_row(i) for i in range(1, 4)])
    e.backlog.write_text("# backlog\n| x |\n", encoding="utf-8")
    calls = []
    loop = e.loop(triage_fn=_tri(calls), ready_target=15)
    assert _topup(e, loop) is True
    assert len(calls) == 1 and calls[0]["limit"] >= 12
    assert _topup(e, loop) is False                       # not twice inside ready_triage_s
    e.clock.sleep(loop.cfg.triage_retry_s + 1)           # the empty portion doubled the wait, never past triage_retry_s
    assert _topup(e, loop) is True and len(calls) == 2


def test_ready_at_target_does_not_triage(tmp_path, monkeypatch):
    e = Env(tmp_path, monkeypatch, tasks=[task_row(i) for i in range(1, 16)])
    calls = []
    loop = e.loop(triage_fn=_tri(calls), ready_target=15)
    assert _topup(e, loop) is False and not calls


def test_target_zero_switches_the_topup_off(tmp_path, monkeypatch):
    e = Env(tmp_path, monkeypatch, tasks=[task_row(1)])
    calls = []
    loop = e.loop(triage_fn=_tri(calls), ready_target=0)
    assert _topup(e, loop) is False and not calls


def test_a_not_code_row_is_never_offered_to_the_slicer(tmp_path, monkeypatch):
    e = Env(tmp_path, monkeypatch, tasks=[task_row(1)])
    e.backlog.write_text("# backlog\n| x |\n", encoding="utf-8")
    calls = []
    loop = e.loop(triage_fn=_tri(calls), ready_target=15)
    ls = loop.ls()
    ls["not_code"] = {"NC1": {"until": loop.clock() + 1000, "hash": "h"}}
    loop.save_ls(ls)
    loop._row_hashes = lambda field="row": {"NC1": "h"}
    assert _topup(e, loop) is True
    assert "NC1" in calls[0]["known_backlog_ids"]


# ---- 3. no progress after an escalation -> quarantine (or a slice) ---------------------------------------------

def _escalate_and_fail(e, loop, n=4):
    for _ in range(n):
        _reject(e, loop)


# <id> replaced the old stall book (stalled_tasks.json: a quarantine / slice record per task) with the slicer's own
# ladder: a failed row goes back to the slicer one rung up (tests/test_factory_reslice.py, test_factory_slicer_pool.py),
# and a row the ladder gave up on sits in loop_state["quarantine"] until the slicer version changes.

def test_three_failures_are_not_yet_a_quarantine(env):
    loop = env.loop()
    _escalate_and_fail(env, loop, 3)
    assert env.state()["tasks"]["T1"]["status"] != "FAILED"


def test_a_failed_row_is_offered_to_the_slicer_not_booked_as_a_stalled_task(env):
    loop = env.loop()
    env.set_row("T1", status="FAILED", reason="reslice")
    tasks, state = loop.load()
    assert loop._resliceable(tasks, state, loop.ls(), loop.clock()) == {"B1": "first"}
    assert not (env.state_dir / "stalled_tasks.json").exists()


def test_a_row_the_ladder_quarantined_is_not_resliced_again(env):
    loop = env.loop()
    env.set_row("T1", status="FAILED", reason="reslice")
    ls = loop.ls()
    ls["quarantine"] = {"B1": {"version": F.slicer_version()}}
    loop.save_ls(ls)
    tasks, state = loop.load()
    assert loop._resliceable(tasks, state, loop.ls(), loop.clock()) == {}
