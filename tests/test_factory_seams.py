import json
import pytest
from tools import agent_factory as F
from test_factory_loop import task_row, Env, git
from test_factory_runtime import rig

def _plan(*rows):
    return F.read_plan(list(rows))

def cards():
    from tools import factory_cards
    return factory_cards


def test_the_slicer_version_follows_the_slicer_files(tmp_path, monkeypatch):
    f = tmp_path / "slicer.py"; f.write_text("PROMPT = 'a'\n", encoding="utf-8")
    monkeypatch.setattr(F, "SLICER_FILES", (str(f),)); monkeypatch.setattr(F, "_slicer_version", None)
    v1 = F.slicer_version()
    f.write_text("PROMPT = 'b'\n", encoding="utf-8"); monkeypatch.setattr(F, "_slicer_version", None)
    assert F.slicer_version() != v1 and v1.startswith("s") and len(v1) == 11

def test_terminal_reasons_rows_and_the_call_cap():
    assert all(F.is_terminal(r) for r in ("quarantine", "superseded:reslice1", "superseded_by_guard", "closed:dup", "not_code", "sliced:gate:#1"))
    assert not any(F.is_terminal(r) for r in (None, "reslice", "reenter", "escalated:weak_test"))
    assert (F.row_of("B1#2"), F.row_of("B1")) == ("B1", "B1")
    assert (F.call_cap(), F.call_cap(5)) == (14, 38) and F.REASON_CLOUD_DOWN == "cloud_down" and "cloud_down" in F.DEFER_REASONS

def test_the_second_red_attempt_fails_with_reslice_and_channel_faults_do_not_count():
    tasks = _plan(task_row(1)); s = F.initial_state(tasks)
    def attempt(**kw):
        tok = F.acquire(tasks, s, "T1", now=0.0)
        return F.settle(s, "T1", tok, tests_ok=False, evidence="a" * 64, max_attempts=99, reslice_after=F.RESLICE_AFTER, **kw)
    assert [attempt(strike=False) for _ in range(3)] == ["READY"] * 3      # a provider fault is not the card's fault
    assert attempt() == "READY"
    assert attempt() == "FAILED" and s["tasks"]["T1"]["reason"] == "reslice"
    F.unblock(s, "T1", "a contract by hand")
    assert attempt() == "READY"                                            # the red count starts again

def test_the_runner_passes_the_ladder_to_settle(rig, monkeypatch):
    monkeypatch.setattr(rig.w, "engine_for", lambda role, task: "kilo")
    rig.coder_script = ["bad"] * 12
    assert rig.once(reslice_after=F.RESLICE_AFTER)["status"] == "READY"; rig.ready_again()
    rig.once(reslice_after=F.RESLICE_AFTER)
    row = rig.state()["tasks"]["T1"]
    assert row["status"] == "FAILED" and row["reason"] == "reslice"

def test_a_contract_roundtrips_and_garbage_is_refused():
    row = task_row(1, contract=json.dumps({"row": "B1", "decision": "fix"}))
    assert json.loads(_plan(row)["T1"].contract)["row"] == "B1"
    with pytest.raises(F.InvalidPlan):
        _plan(task_row(1, contract="not json"))

def test_resolve_names_a_missing_symbol_a_wrong_case_and_a_missing_anchor(tmp_path):
    (tmp_path / "echo_sync").mkdir()
    (tmp_path / "echo_sync" / "engine.py").write_text("class Engine:\n    def on_barge_in(self):\n        return 1\n", encoding="utf-8")
    (tmp_path / "echo_sync" / "table.md").write_text("| a | b |\n", encoding="utf-8")
    assert cards().resolve(tmp_path, "echo_sync/engine.py", ["Engine.on_barge_in"]) == []
    assert any("Engine.nope" in e for e in cards().resolve(tmp_path, "echo_sync/engine.py", ["Engine.nope"]))
    assert cards().resolve(tmp_path, "echo_sync/Engine.py", [])                  # wrong letter case
    assert any("anchor" in e for e in cards().resolve(tmp_path, "echo_sync/table.md", [], anchor="| no such line |"))

def test_fail_row_fails_without_a_strike_and_refuses_other_reasons():
    tasks = _plan(task_row(1)); s = F.initial_state(tasks)
    tok = F.acquire(tasks, s, "T1", now=0.0)
    assert F.fail_row(s, "T1", tok, "reslice:stale") == "FAILED"
    assert s["tasks"]["T1"]["reason"] == "reslice:stale" and not s.get("strikes")
    with pytest.raises(F.InvalidPlan):
        F.fail_row(s, "T1", tok, "quarantine")

def test_two_far_functions_of_one_file_ride_in_one_card_verbatim():
    text = "A = 1\n\ndef top():\n    return A\n" + "\n" * 400 + "def bottom():\n    return 2\n"
    header, region = cards().part_region(text, ["top", "bottom"])
    assert "def top():\n    return A" in region and "def bottom():\n    return 2" in region and len(region) < 400


def test_reslice_ids_can_share_a_row_but_not_an_id(tmp_path):
    path = tmp_path / "plan.json"
    assert F.append_tasks(path, [task_row(1)]) == ["T1"]
    assert F.append_tasks(path, [task_row(1, id="T1_r1")]) == ["T1_r1"]
    assert F.append_tasks(path, [task_row(1, id="T1_r1_test")]) == ["T1_r1_test"]
    assert not F.append_tasks(path, [task_row(1, id="T1_r1")])


def test_quarantine_always_records_the_slicer_version():
    tasks = _plan(task_row(1), task_row(3, backlog_id="B1"))
    s = F.initial_state(tasks)
    for _ in range(3):
        tok = F.acquire(tasks, s, "T1", now=0)
        F.settle(s, "T1", tok, tests_ok=False, evidence="a" * 64, unsafe=True, max_attempts=99)
    assert s["tasks"]["T1"]["q_ver"] == F.slicer_version()
    assert s["tasks"]["T3"]["q_ver"] == F.slicer_version()
    s = F.initial_state(tasks)
    tok = F.acquire(tasks, s, "T1", now=0)
    s["strikes"] = {"bl:B1": F.MAX_STRIKES}
    F.defer(s, "T1", tok, "network", 60, now=0)
    assert s["tasks"]["T1"]["q_ver"] == F.slicer_version()


def test_contract_limits_and_amendment(tmp_path):
    for bad in ("[]", "null", "1", "x" * 24001, {}, None):
        with pytest.raises(F.InvalidPlan):
            _plan(task_row(1, contract=bad))
    path = tmp_path / "plan.json"
    F.append_tasks(path, [task_row(1)])
    F.amend_task(path, "T1", contract='{"row":"B1"}')
    assert F.read_plan(json.loads(path.read_text(encoding="utf-8")))["T1"].contract == '{"row":"B1"}'


def test_a_recovered_merge_writes_the_closure_too(tmp_path, monkeypatch):
    from tools import factory_closures as C
    e = Env(tmp_path, monkeypatch, tasks=[task_row(1)])
    e.backlog.write_text("# backlog\n\n## \u0417\u0430\u043a\u0440\u044b\u0442\u043e \u043a\u043e\u043c\u043c\u0438\u0442\u0430\u043c\u0438 \u043a\u043e\u043e\u0440\u0434\u0438\u043d\u0430\u0442\u043e\u0440\u0430 21.11\n| ID | Commit | Note |\n|---|---|---|\n\n## 4. Open\n", encoding="utf-8")
    git(e.repo, "commit", "-q", "--allow-empty", "-m", "factory(T1): repair")
    sha = git(e.repo, "rev-parse", "HEAD")
    e.set_row("T1", status="REVIEW")
    e.package("T1", {"tools/x1.py": "a = 2\n"})
    loop = e.loop()
    loop.step()
    assert e.state()["tasks"]["T1"]["status"] == "PROMOTED"
    assert C.table_ids(e.backlog)["B1"] == sha[:8]
    promoted = [x for x in e.events() if x["span"] == "promote" and x.get("status") == "promoted"]
    assert len(promoted) == 1 and promoted[0]["recovered"] is True
    assert promoted[0]["base_sha"] == sha


def test_a_normal_merge_keeps_the_recorded_base_in_the_event(tmp_path, monkeypatch):
    e = Env(tmp_path, monkeypatch, tasks=[task_row(1)])
    base = git(e.repo, "rev-parse", "HEAD")
    e.set_row("T1", status="REVIEW")
    e.set_loop_state(bases={"T1": base})
    e.package("T1", {"tools/x1.py": "a = 2\n"})
    e.loop().step()
    row = e.state()["tasks"]["T1"]
    assert row["status"] == "PROMOTED"
    promoted = [x for x in e.events() if x["span"] == "promote" and x.get("status") == "promoted"]
    assert len(promoted) == 1
    assert promoted[0]["base_sha"] == base
    assert promoted[0]["commit"] == git(e.repo, "rev-parse", "HEAD") != base
    assert promoted[0]["recovered"] is False
