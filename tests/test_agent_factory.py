"""Synthetic state-machine tests for experimental Kilo task coordination."""
import json
from pathlib import Path
import pytest

from tools import agent_factory as F
from tools import agent_factory_runner as W


def item(id="T1", *, deps=None, scope=None, safe=True, tokens=200):
    return {"id": id, "title": "Synthetic repair", "depends_on": deps or [],
            "touch_files": scope or ["echo_sync/safe.py"], "read_files": [],
            "tests": ["tests/test_safe.py"], "privacy_safe": safe,
            "estimated_tokens": tokens}


def plan(*rows):
    return F.read_plan(list(rows))


def test_accepts_minimal_contract_and_defaults_to_private():
    a=item();del a["privacy_safe"]
    tasks=plan(a)
    assert not tasks["T1"].privacy_safe
    assert F.ready(tasks,F.initial_state(tasks))==[]
    assert F.ready(tasks,F.initial_state(tasks),google=False)==["T1"]


@pytest.mark.parametrize("name", [
    "../secret.py", "/tmp/safe.py", "a/../../b.py", "x\\.env",
    "a/.env", "a/.git/config", "secrets/access.py", "private/x.py",
    "materials/personal.txt", "src//target.py", "C:/secret", "x/./file.py",
    "src/hidden?.py", ".env", "src\\secrets.py",
])
def test_path_denylist_is_canonical_and_cross_platform(name):
    with pytest.raises(F.InvalidPlan):
        F.safe_path(name)


def test_duplicate_ids_or_missing_dependency_or_cycles_are_rejected():
    for items in (
        [item(),item()],
        [item(deps=["T9"])],
        [item("A",deps=["B"]),item("B",deps=["A"])],
        [item("A",deps=["A"])],
    ):
        with pytest.raises(F.InvalidPlan):
            plan(*items)


def test_deployment_block_does_not_stop_development():
    tasks=plan(item())
    s=F.initial_state(tasks)
    assert s["deploy_blocked"] is True
    assert F.ready(tasks,s)==["T1"]
    token=F.acquire(tasks,s,"T1",now=0)
    assert s["tasks"]["T1"]["attempts"]==1
    assert s["tasks"]["T1"]["deadline"]==1800.
    assert token and s["model_calls"]==1


def test_lease_fencing_requires_exact_current_token():
    tasks=plan(item())
    s=F.initial_state(tasks)
    token=F.acquire(tasks,s,"T1",now=0)
    with pytest.raises(F.InvalidPlan):
        F.settle(s,"T1","stale",tests_ok=True,evidence="0"*64)
    assert F.settle(s,"T1",token,tests_ok=True,evidence="0"*64)=="REVIEW"
    assert s["tasks"]["T1"]["status"]=="REVIEW"
    with pytest.raises(F.InvalidPlan):
        F.settle(s,"T1",token,tests_ok=True,evidence="0"*64)
    with pytest.raises(F.InvalidPlan):
        F.accept(s,"T1",reviewer="")
    F.accept(s,"T1",reviewer="separate-reviewer")
    assert s["tasks"]["T1"]["status"]=="DONE"


def test_expired_running_lease_blocks_instead_of_double_running():
    tasks=plan(item())
    s=F.initial_state(tasks)
    F.acquire(tasks,s,"T1",now=0,lifetime=10)
    assert F.pause_expired(s,now=11)==["T1"]
    assert F.ready(tasks,s)==[]
    assert F.pause_expired(s,now=12)==[]


def test_dependencies_and_overlapping_writer_scopes():
    tasks=plan(item("A",scope=["src/a.py"]),
               item("B",scope=["src/a.py"]),
               item("C",scope=["src/c.py"],deps=["A"]))
    s=F.initial_state(tasks)
    assert F.ready(tasks,s)==["A"]
    token=F.acquire(tasks,s,"A",now=0)
    assert F.ready(tasks,s)==[]
    F.settle(s,"A",token,tests_ok=True,evidence="1"*64)
    assert F.ready(tasks,s)==["B"]
    F.accept(s,"A",reviewer="human")
    assert F.ready(tasks,s)==["B","C"]


def test_red_attempts_are_bounded_and_count_model_budget():
    tasks=plan(item())
    s=F.initial_state(tasks)
    for k in range(2):
        token=F.acquire(tasks,s,"T1",now=k)
        result=F.settle(s,"T1",token,tests_ok=False,evidence="a"*64)
        assert result==("READY" if k==0 else "FAILED")
    assert s["model_calls"]==2
    assert F.ready(tasks,s)==[]


def test_global_budget_is_hard_gate_not_a_quota_guess():
    tasks=plan(item())
    s=F.initial_state(tasks);s["max_model_calls"]=0
    with pytest.raises(F.InvalidPlan):
        F.acquire(tasks,s,"T1")


def test_routing_requires_real_provider_ids_and_privacy_opt_in():
    small="google/gemma-id";big="google/gemini-id"
    assert F.route(plan(item(tokens=400))["T1"],small_model=small,large_model=big)==small
    assert F.route(plan(item(tokens=8001))["T1"],small_model=small,large_model=big)==big
    assert F.route(plan(item(tokens=1))["T1"],small_model=small,large_model=big,fallback=True)==big
    with pytest.raises(F.InvalidPlan):
        F.route(plan(item(safe=False))["T1"],small_model=small,large_model=big)
    with pytest.raises(F.InvalidPlan):
        F.route(plan(item())["T1"],small_model="invented-model",large_model=big)
    assert [F.backoff(x) for x in range(5)]==[2.,4.,8.,16.,20.]


def test_atomic_checkpoint_restore_and_unknown_schema(tmp_path):
    tasks=plan(item())
    path=tmp_path/"state.json"
    s=F.initial_state(tasks)
    F.save_atomic(path,s)
    assert F.load_state(path,tasks)==s
    path.write_text(json.dumps({"schema":99,"tasks":{}}))
    with pytest.raises(F.InvalidPlan):
        F.load_state(path,tasks)


def test_junit_failure_groups_do_not_store_unsafe_stacktraces():
    xml="""<testsuite>
      <testcase classname="safe" name="a"><failure type="ValueError" message="personal account 1234">some private data</failure></testcase>
      <testcase classname="safe" name="b"><failure type="ValueError" message="token 5678">do not expose</failure></testcase>
      <testcase classname="safe" name="c"><error type="NameError">hidden</error></testcase>
    </testsuite>"""
    cards=F.grouped_failures(xml)
    assert sum(c["count"] for c in cards)==3
    assert sorted(c["count"] for c in cards)==[1,2]
    assert all(c["status"]=="BLOCKED" and not c["privacy_safe"] for c in cards)
    assert "1234" not in repr(cards) and "5678" not in repr(cards)


def test_secret_pattern_and_file_review(tmp_path):
    good=tmp_path/"safe.py";good.write_text("number=42",encoding="utf-8")
    assert F.safe_source(good)==b"number=42"
    bad=tmp_path/"bad.py";bad.write_text("password" + " = '" + "synthetic_demo_1234" + "'",encoding="utf-8")
    with pytest.raises(F.InvalidPlan):
        F.safe_source(bad)
    link=tmp_path/"link.py"
    try:link.symlink_to(good)
    except OSError:pytest.skip("OS does not allow symlinks")
    with pytest.raises(F.InvalidPlan):
        F.safe_source(link)


def test_prepare_is_explicit_allowlist_not_full_git_worktree(tmp_path):
    root=tmp_path/"src";root.mkdir()
    (root/"src").mkdir();(root/"src"/"logic.py").write_text("x=1")
    (root/"tests").mkdir();(root/"tests"/"test_safe.py").write_text("def test_x():assert True")
    (root/".env").write_text("MY_SECRET=x")
    t=plan(item(scope=["src/logic.py"]))["T1"]
    out=tmp_path/"sandbox"
    original=W.prepare(root,t,out)
    assert set(original)=={"src/logic.py","tests/test_safe.py"}
    assert not (out/".env").exists()
    assert W.inspect_changes(t,out,original)==()
    (out/"src"/"logic.py").write_text("x=2")
    assert W.inspect_changes(t,out,original)==("src/logic.py",)


def test_test_tamper_and_unapproved_outputs_are_rejected(tmp_path):
    root=tmp_path/"src";root.mkdir();(root/"tests").mkdir()
    (root/"tests"/"test_safe.py").write_text("def test_x():assert True")
    t=plan(item(scope=["src/new.py"]))["T1"]
    out=tmp_path/"stage"
    original=W.prepare(root,t,out)
    (out/"src").mkdir();(out/"src"/"new.py").write_text("def f(): return 1")
    assert W.inspect_changes(t,out,original)==("src/new.py",)
    (out/"tests"/"test_safe.py").write_text("def test_x():assert True # weakened")
    with pytest.raises(F.InvalidPlan):
        W.inspect_changes(t,out,original)


def test_dry_run_never_calls_kilo_or_creates_checkpoint(tmp_path,monkeypatch):
    root=tmp_path/"project";root.mkdir()
    planpath=tmp_path/"plan.json"
    planpath.write_text(json.dumps([item()]))
    monkeypatch.setattr(W,"model_attempt",lambda *a,**kw: (_ for _ in ()).throw(AssertionError("Kilo called")))
    path=tmp_path/"state.json"
    outcome=W.once(root=root,plan=planpath,checkpoint=path,
                   staging=tmp_path/"stage",small_model="google/gemma",large_model="google/flash")
    assert outcome["status"]=="DRY_RUN" and outcome["next"]=="T1"
    assert not path.exists()


def test_real_local_pytest_gate_on_synthetic_sources(tmp_path):
    root=tmp_path/"r";root.mkdir();(root/"tests").mkdir()
    (root/"tests"/"test_safe.py").write_text("from src.logic import value\ndef test_value(): assert value()==2\n")
    (root/"src").mkdir();(root/"src"/"logic.py").write_text("def value(): return 1\n")
    t=plan(item(scope=["src/logic.py"]))["T1"]
    stage=tmp_path/"stage";original=W.prepare(root,t,stage)
    (stage/"src"/"logic.py").write_text("def value(): return 2\n")
    ok,receipt,changes=W.gates(t,stage,original)
    assert ok and len(receipt)==64 and changes==("src/logic.py",)



def test_existing_register_import_never_auto_authorizes_tasks():
    from tools.agent_factory_import import suggestions
    rows=[
        {"id":"N001","class":"DONE","accepted":False,"what":"Synthetic implemented item",
         "files":["echo_sync/logic.py","tests/test_logic.py"]},
        {"id":"N002","class":"OWNER","accepted":False,"what":"Needs phone","files":[]},
        {"id":"N003","class":"DONE","accepted":True,"what":"Accepted","files":[]},
    ]
    result=suggestions(rows)
    assert result["not_executable"] is True
    assert [t["id"] for t in result["tasks"]]==["N001","N002"]
    assert all(not t["privacy_safe"] for t in result["tasks"])
    assert result["tasks"][0]["status"]=="NEEDS_SCOPE_REVIEW"
    assert result["tasks"][1]["status"]=="NEEDS_OWNER"
    assert result["tasks"][0]["proposed_touch_files"]==["echo_sync/logic.py"]
    with pytest.raises(ValueError):
        suggestions([rows[0],rows[0]])
