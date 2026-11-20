"""Synthetic state-machine tests for experimental Kilo task coordination."""
import json
from pathlib import Path
import pytest

from tools import agent_factory as F
from tools import agent_factory_runner as W


@pytest.fixture(autouse=True)
def _kilo_engine(monkeypatch):
    """These rigs fake the Kilo agent loop through model_attempt; the light engine (one REST request) has its
    own tests in tests/test_factory_light.py."""
    monkeypatch.setattr(W, 'engine_for', lambda role, task: 'kilo')


def item(id="T1", *, deps=None, scope=None, safe=True, tokens=200):
    return {"id": id, "title": "Synthetic repair", "depends_on": deps or [],
            "touch_files": scope or ["echo_sync/safe.py"], "read_files": [],
            "tests": ["tests/test_safe.py" if id == "T1" else "tests/test_chk_%s.py" % id.lower()],   # a shared test is exclusive (the pool)
            "privacy_safe": safe,
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
    "../secret.py", "/tmp/safe.py", "a/../../b.py", "x\\." "env",
    "a/." "env", "a/.git/config", "secrets/access.py", "private/x.py",
    "materials/personal.txt", "src//target.py", "C" ":/secret", "x/./file.py",
    "src/hidden?.py", "." "env", "src\\secrets.py",
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


def test_expired_running_lease_is_released_once_not_double_run():
    tasks=plan(item())
    s=F.initial_state(tasks)
    F.acquire(tasks,s,"T1",now=0,lifetime=10)
    assert F.release_expired(s,now=11)==["T1"]
    assert F.ready(tasks,s)==["T1"]
    assert F.release_expired(s,now=12)==[]
    assert not hasattr(F,"pause_expired")


def test_dependencies_and_overlapping_writer_scopes():
    tasks=plan(item("A",scope=["src/a.py"]),
               item("B",scope=["src/a.py"]),
               item("C",scope=["src/c.py"],deps=["A"]))
    s=F.initial_state(tasks)
    assert F.ready(tasks,s)==["A"]
    token=F.acquire(tasks,s,"A",now=0)
    assert F.ready(tasks,s)==[]
    F.settle(s,"A",token,tests_ok=True,evidence="1"*64)
    assert F.ready(tasks,s)==[]          # a candidate in REVIEW holds its files until it is promoted (the pool)
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
    (root/"." "env").write_text("MY_SECRET=x")
    t=plan(item(scope=["src/logic.py"]))["T1"]
    out=tmp_path/"sandbox"
    original=W.prepare(root,t,out)
    assert set(original)=={"src/logic.py","tests/test_safe.py","kilo.jsonc"}
    assert (out/"kilo.jsonc").is_file(), "Kilo policy is part of the immutable staging snapshot"
    assert not (out/"." "env").exists()
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





def test_existing_register_import_never_auto_authorizes_tasks():
    from tools.agent_factory_import import suggestions
    rows=[
        {"id":"NQX001","class":"DONE","accepted":False,"what":"Synthetic implemented item",
         "files":["echo_sync/logic.py","tests/test_logic.py"]},
        {"id":"NQX002","class":"OWNER","accepted":False,"what":"Needs phone","files":[]},
        {"id":"NQX003","class":"DONE","accepted":True,"what":"Accepted","files":[]},
    ]
    result=suggestions(rows)
    assert result["not_executable"] is True
    assert [t["id"] for t in result["tasks"]]==["NQX001","NQX002"]
    assert all(not t["privacy_safe"] for t in result["tasks"])
    assert result["tasks"][0]["status"]=="NEEDS_SCOPE_REVIEW"
    assert result["tasks"][1]["status"]=="NEEDS_OWNER"
    assert result["tasks"][0]["proposed_touch_files"]==["echo_sync/logic.py"]
    with pytest.raises(ValueError):
        suggestions([rows[0],rows[0]])



def test_unquoted_secret_assignment_is_not_safe_to_stage(tmp_path):
    src=tmp_path/"logic.py"
    src.write_text("api_key = " + "syntheticKey_123456789",encoding="utf-8")
    with pytest.raises(F.InvalidPlan):
        F.safe_source(src)


def test_symlink_parent_cannot_expose_hidden_private_sources(tmp_path):
    root=tmp_path/"repo";root.mkdir()
    hidden=root/"secrets";hidden.mkdir()
    (hidden/"hidden.py").write_text("unclassified_private_data=1")
    alias=root/"public_alias"
    try:alias.symlink_to(hidden,target_is_directory=True)
    except OSError:pytest.skip("OS does not allow symlinks")
    with pytest.raises(F.InvalidPlan):
        W.source_path(root,"public_alias/hidden.py")


def test_a_reader_must_not_overlap_concurrent_writer():
    a=item("A",scope=["src/ledger.py"])
    b=item("B",scope=["src/report.py"])
    b["read_files"]=["src/ledger.py"]
    tasks=plan(a,b)
    assert F.ready(tasks,F.initial_state(tasks))==["A"]
    s=F.initial_state(tasks)
    F.acquire(tasks,s,"A",now=0)
    assert F.ready(tasks,s)==[]






@pytest.mark.parametrize("name", ["CON", "nul.txt", "COM1.py", "a/LPT3.txt",
                                    "dir/aux", "readme.", "readme "])
def test_windows_reserved_names_never_enter_sandbox_even_on_linux(name):
    with pytest.raises(F.InvalidPlan):
        F.safe_path(name)




def test_executor_never_creates_checkpoint_inside_source_tree(tmp_path):
    root=tmp_path/"repo";root.mkdir()
    planpath=tmp_path/"p.json";planpath.write_text(json.dumps([item()]))
    with pytest.raises(F.InvalidPlan):
        W.once(root=root,plan=planpath,checkpoint=root/"state.json",
               staging=tmp_path/"work",small_model="google/a",large_model="google/b")
    with pytest.raises(F.InvalidPlan):
        W.once(root=root,plan=planpath,checkpoint=tmp_path/"state.json",
               staging=root/"stage",small_model="google/a",large_model="google/b")



def test_cli_max_tasks_is_bounded_and_dry_run_runs_only_once(tmp_path,monkeypatch,capsys):
    root=tmp_path/"repo";root.mkdir()
    planpath=tmp_path/"plan.json"
    planpath.write_text(json.dumps([item()]))
    args=["--root",str(root),"--plan",str(planpath),
          "--checkpoint",str(tmp_path/"state.json"),"--staging",str(tmp_path/"stage"),
          "--small-model","google/a","--large-model","google/b","--max-tasks","10"]
    count=[]
    previous=W.once
    def once_count(**kw):
        count.append(1)
        return previous(**kw)
    monkeypatch.setattr(W,"once",once_count)
    assert W.main(args)==0
    assert len(count)==1
    assert json.loads(capsys.readouterr().out)["status"]=="DRY_RUN"
    with pytest.raises(SystemExit):
        W.main(args[:-1]+["11"])







def test_worker_default_permissions_are_deny_first(tmp_path):
    root=tmp_path/"repo";root.mkdir()
    (root/"src").mkdir();(root/"tests").mkdir()
    (root/"src"/"logic.py").write_text("def value():return 1\n")
    (root/"tests"/"test_safe.py").write_text("def test_ok():assert True\n")
    task=plan(item(scope=["src/logic.py"]))["T1"]
    stage=tmp_path/"stage";baseline=W.prepare(root,task,stage)
    config_path=stage/"kilo.jsonc"
    assert config_path.is_file(), "unrestricted CLI permissions are unsafe for --auto"
    config=json.loads(config_path.read_text(encoding="utf-8"))
    rules=config["permission"]
    assert rules["*"]=="deny" and rules["bash"]=="deny"
    assert rules["external_directory"]=="deny"
    assert "provider" not in config, "project-level env references are intentionally ignored by Kilo"
    assert "synthetic-google-placeholder" not in config_path.read_text(encoding="utf-8")
    assert rules["agent_manager"]=="deny" and rules["task"]=="deny"
    assert rules["edit"]["*"]=="deny"
    assert rules["edit"]["**/src/logic.py"]=="allow"
    assert "kilo.jsonc" in baseline, "the permission file must itself be immutable"
    config_path.write_text('{"permission":"allow"}', encoding="utf-8")
    with pytest.raises(F.InvalidPlan):
        W.inspect_changes(task,stage,baseline)


def test_model_child_env_does_not_inherit_parent_provider_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "synthetic-not-a-real-token")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-not-a-real-key")
    monkeypatch.setenv("CLAUDE_TOKEN", "synthetic-not-a-real-token")
    monkeypatch.setenv("GOOGLE_GENERATIVE_AI_API_KEY", "synthetic-google-placeholder")
    calls=[]
    def fake_run(args, **kwargs):
        calls.append((args,kwargs))
        return type("Result",(),{"returncode":0,"stdout":b"done","stderr":b""})()
    monkeypatch.setattr(W.subprocess,"run",fake_run)
    task=plan(item())["T1"]
    W.model_attempt(task,tmp_path,"google/gemma",timeout=10)
    assert calls
    env=calls[0][1]["env"]
    assert "GITHUB_TOKEN" not in env and "OPENAI_API_KEY" not in env and "CLAUDE_TOKEN" not in env
    assert env.get("GOOGLE_GENERATIVE_AI_API_KEY")=="synthetic-google-placeholder"
    trusted=json.loads(env["KILO_CONFIG_CONTENT"])
    assert trusted["provider"]["google"]["options"]["apiKey"]=="{env:GOOGLE_GENERATIVE_AI_API_KEY}"
    assert "synthetic-google-placeholder" not in env["KILO_CONFIG_CONTENT"]
    assert env["PYTHONUTF8"]=="1"
    assert "kilo" in str(calls[0][0]).lower()





def test_no_google_credential_causes_no_worker_invocation(tmp_path,monkeypatch):
    monkeypatch.delenv("GOOGLE_GENERATIVE_AI_API_KEY",raising=False)
    monkeypatch.setattr(W.shutil,"which",lambda _: "kilo")
    monkeypatch.setattr(W,"model_attempt",lambda *a,**kw:
                        (_ for _ in ()).throw(AssertionError("model invoked without auth")))
    p=tmp_path/"p.json";p.write_text(json.dumps([item()]))
    root=tmp_path/"repo";root.mkdir()
    with pytest.raises(F.InvalidPlan,match="Google"):
        W.once(root=root,plan=p,checkpoint=tmp_path/"s.json",
               staging=tmp_path/"stage",small_model="google/gemma",
               large_model="google/flash",execute=True,acknowledge=True)
    assert not (tmp_path/"s.json").exists()



def test_checkpoint_atomic_replace_retries_transient_windows_sharing_violation(
        tmp_path,monkeypatch):
    tasks=plan(item())
    state=F.initial_state(tasks)
    path=tmp_path/"checkpoint.json"
    original=F.os.replace
    calls=[]
    def transient_replace(src,dst):
        calls.append(1)
        if len(calls)==1:
            raise PermissionError("synthetic WinError 5 sharing violation")
        return original(src,dst)
    monkeypatch.setattr(F.os,"replace",transient_replace)
    monkeypatch.setattr(F.time,"sleep",lambda _:None)
    F.save_atomic(path,state)
    assert len(calls)==2
    assert F.load_state(path,tasks)==state


def test_checkpoint_failed_replace_preserves_old_state_and_cleans_temporary_file(
        tmp_path,monkeypatch):
    tasks=plan(item());path=tmp_path/"checkpoint.json"
    F.save_atomic(path,F.initial_state(tasks))
    previous=path.read_bytes()
    monkeypatch.setattr(F.os,"replace",lambda *args:
                        (_ for _ in ()).throw(PermissionError("WinError 5")))
    monkeypatch.setattr(F.time,"sleep",lambda _:None)
    with pytest.raises(PermissionError):
        F.save_atomic(path,F.initial_state(tasks))
    assert path.read_bytes()==previous
    assert not list(tmp_path.glob(".agent-state-*"))


def test_malformed_running_checkpoint_without_lease_is_never_accepted():
    tasks=plan(item())
    state=F.initial_state(tasks)
    state["tasks"]["T1"]["status"]="RUNNING"
    with pytest.raises(F.InvalidPlan):
        F.validate_state(tasks,state)



def test_markdown_parser_refuses_missing_bounded_source_section():
    from tools.agent_factory_import import active_backlog_review
    with pytest.raises(ValueError):
        active_backlog_review("## 4. Queue\n| EQX21 | unfinished |")
    with pytest.raises(ValueError):
        active_backlog_review("## 5. Historical\n| EQX21 | item |\n")



@pytest.mark.parametrize("path", [
    "src/a\nb.py", "src/a\rb.py", "src/a\tb.py", "src/a\u202eb.py",
    "src/a\u200bb.py", "src/a\u202db.py",
])
def test_control_or_directional_unicode_cannot_hide_paths(path):
    with pytest.raises(F.InvalidPlan):
        F.safe_path(path)


def test_windows_case_insensitive_writer_collision_blocks_second_worker():
    tasks=plan(item("A",scope=["src/Result.py"]),
               item("B",scope=["src/result.py"]))
    state=F.initial_state(tasks)
    assert F.ready(tasks,state)==["A"]
    token=F.acquire(tasks,state,"A",now=0)
    assert F.ready(tasks,state)==[]
    F.settle(state,"A",token,tests_ok=True,evidence="0"*64)


def test_windows_case_alias_within_one_task_is_invalid_plan():
    with pytest.raises(F.InvalidPlan):
        plan(item("A",scope=["src/Report.py","src/report.py"]))


def test_dependency_scheduler_never_picks_racing_scopes_under_many_synthetic_plans():
    import random
    for seed in range(100):
        rng=random.Random(seed)
        filenames=["src/File"+str(i)+".py" for i in range(8)]
        rows=[]
        for n in range(24):
            reads=[rng.choice(filenames)]
            rows.append({"id":"T"+str(n),"title":"Synthetic "+str(n),
                         "depends_on":[],"touch_files":[rng.choice(filenames)],
                         "read_files":reads,"tests":["tests/test_safe.py"],
                         "privacy_safe":True,"estimated_tokens":300})
        tasks=plan(*rows)
        chosen=F.ready(tasks,F.initial_state(tasks))
        readers=set()
        writers=set()
        for tid in chosen:
            task=tasks[tid]
            read={p.casefold() for p in task.read_files + task.tests}
            write={p.casefold() for p in task.touch_files}
            assert not (write & readers) and not (write & writers)
            assert not (read & writers)
            readers.update(read);writers.update(write)


# ---------------------------------------------------------------- K-A (day 19)
import time as _time


def bitem(id, bid=None, **kw):
    row = item(id, **kw)
    if bid:
        row["backlog_id"] = bid
    return row


def test_read_plan_rejects_task_without_tests():
    row = item(); row["tests"] = []
    with pytest.raises(F.InvalidPlan):
        plan(row)


def test_backlog_id_is_kept_in_task_and_state():
    tasks = plan(bitem("T1", "ФQX12"))
    assert tasks["T1"].backlog_id == "ФQX12"
    assert F.initial_state(tasks)["tasks"]["T1"]["backlog_id"] == "ФQX12"


def test_promoted_only_from_review_and_satisfies_dependency():
    tasks = plan(item("A", scope=["src/a.py"]), item("B", scope=["src/b.py"], deps=["A"]))
    s = F.initial_state(tasks)
    with pytest.raises(F.InvalidPlan):
        F.mark_promoted(s, "A", "abc1234")
    tok = F.acquire(tasks, s, "A", now=0)
    with pytest.raises(F.InvalidPlan):
        F.mark_promoted(s, "A", "abc1234")
    F.settle(s, "A", tok, tests_ok=True, evidence="1" * 64)
    assert "PROMOTED" in F.STATES
    assert F.ready(tasks, s) == []
    F.mark_promoted(s, "A", "abc1234")
    assert s["tasks"]["A"]["status"] == "PROMOTED"
    assert s["tasks"]["A"]["commit"] == "abc1234"
    F.validate_state(tasks, s)
    assert F.ready(tasks, s) == ["B"]
    with pytest.raises(F.InvalidPlan):
        F.mark_promoted(s, "A", "abc1234")


def test_plan_growth_adds_ready_rows_and_removal_is_invalid(tmp_path):
    t1 = plan(item("A", scope=["src/a.py"]))
    path = tmp_path / "state.json"
    s = F.initial_state(t1)
    s["tasks"]["A"]["attempts"] = 1
    F.save_atomic(path, s)
    t2 = plan(item("A", scope=["src/a.py"]), item("B", scope=["src/b.py"]))
    loaded = F.load_state(path, t2)
    assert loaded["tasks"]["A"]["attempts"] == 1
    assert loaded["tasks"]["B"]["status"] == "READY"
    with pytest.raises(F.InvalidPlan):
        F.load_state(path, plan(item("Z", scope=["src/z.py"])))
    F.save_atomic(path, loaded)
    with pytest.raises(F.InvalidPlan):
        F.load_state(path, t1)


def test_append_tasks_atomic_and_skips_duplicates(tmp_path):
    p = tmp_path / "plan.json"
    p.write_text(json.dumps({"tasks": [bitem("A", "E1", scope=["src/a.py"])]}))
    added = F.append_tasks(p, [bitem("B", "E2", scope=["src/b.py"]),
                               bitem("A", "E9", scope=["src/c.py"]),
                               bitem("C", "E1", scope=["src/d.py"])])
    assert list(added) == ["B"]
    skipped = {x["id"]: x["reason"] for x in added.skipped}
    assert set(skipped) == {"A", "C"}
    data = json.loads(p.read_text())
    assert [t["id"] for t in data["tasks"]] == ["A", "B"]
    assert not [x for x in tmp_path.iterdir() if x.name.startswith(".")]


def test_append_tasks_validates_and_leaves_file_untouched(tmp_path):
    p = tmp_path / "plan.json"
    p.write_text(json.dumps({"tasks": [item("A")]}))
    before = p.read_bytes()
    bad_rows = []
    r = item("B"); r["tests"] = []; bad_rows.append(r)
    r = item("B"); r["touch_files"] = []; bad_rows.append(r)
    r = item("B", scope=["../x.py"]); bad_rows.append(r)
    r = item("B", scope=["/abs/x.py"]); bad_rows.append(r)
    for r in bad_rows:
        with pytest.raises(F.InvalidPlan):
            F.append_tasks(p, [r])
    assert p.read_bytes() == before


def test_append_tasks_creates_missing_plan_and_allows_batch_dependency(tmp_path):
    p = tmp_path / "new" / "plan.json"
    added = F.append_tasks(p, [item("U1", scope=["tests/test_u1.py"]),
                               item("M1", scope=["src/m.py"], deps=["U1"])])
    assert list(added) == ["U1", "M1"]
    assert set(F.read_plan(json.loads(p.read_text()))) == {"U1", "M1"}


def test_feedback_keeps_last_three_filters_secrets_and_truncates():
    tasks = plan(item())
    s = F.initial_state(tasks)
    assert F.last_feedback(s, "T1") is None
    with pytest.raises(F.InvalidPlan):
        F.add_feedback(s, "T1", "stranger", "x")
    F.add_feedback(s, "T1", "gate", "first")
    F.add_feedback(s, "T1", "review", "second")
    F.add_feedback(s, "T1", "opus", "third")
    F.add_feedback(s, "T1", "gate", "fourth")
    fb = F.last_feedback(s, "T1")
    assert "first" not in fb and all(w in fb for w in ("second", "third", "fourth"))
    F.add_feedback(s, "T1", "gate", "z" * 5000)
    assert all(len(x["text"]) <= 2000 for x in s["tasks"]["T1"]["feedback"])
    assert len(s["tasks"]["T1"]["feedback"]) == 3


@pytest.mark.parametrize("secret", [
    "AI" "za" + "a" * 35, "AQ." + "b" * 40, "s" "k-" + "c" * 30,
    "Bear" "er " + "d" * 30 + ".x", "123456789:" + "e" * 35,
    "someone@example.org", "C" ":\\Us" "ers\\Zq9name\\AppData\\x",
])
def test_feedback_secret_filter(secret):
    tasks = plan(item())
    s = F.initial_state(tasks)
    F.add_feedback(s, "T1", "gate", "log before " + secret + " after")
    out = F.last_feedback(s, "T1")
    assert secret not in out and "before" in out and "after" in out
    if secret.startswith("C:"):
        assert "Zq9name" not in out


def test_strikes_are_global_by_backlog_id_and_quarantine():
    t1 = plan(bitem("A", "Ф1"))
    s = F.initial_state(t1)
    assert F.strikes_for(s, "Ф1") == 0
    for k in range(2):
        tok = F.acquire(t1, s, "A", now=k)
        F.settle(s, "A", tok, tests_ok=False, evidence="a" * 64, max_attempts=9)
    assert F.strikes_for(s, "Ф1") == 2
    # a new task id for the same backlog item continues the count
    t2 = plan(bitem("A", "Ф1"), bitem("A2", "Ф1", scope=["src/other.py"]))
    s = F.sync_state(t2, s)
    tok = F.acquire(t2, s, "A", now=5)
    assert F.settle(s, "A", tok, tests_ok=False, evidence="a" * 64, max_attempts=9) == "FAILED"
    row = s["tasks"]["A"]
    assert row["status"] == "FAILED" and row["reason"] == "quarantine"
    assert F.strikes_for(s, "Ф1") == 3 and F.is_quarantined(s, "Ф1")
    assert s["tasks"]["A2"]["status"] == "FAILED" and s["tasks"]["A2"]["reason"] == "quarantine"


def test_channel_quarantine_and_expiry_are_not_strikes():
    tasks = plan(bitem("A", "Ф2"))
    s = F.initial_state(tasks)
    tok = F.acquire(tasks, s, "A", now=0, lifetime=5)
    F.release_expired(s, now=10)
    assert F.strikes_for(s, "Ф2") == 0
    tok = F.acquire(tasks, s, "A", now=20)
    F.quarantine(s, "A", tok, reason="provider_unavailable")
    assert F.strikes_for(s, "Ф2") == 0


def test_unblock_returns_to_ready_with_opus_feedback():
    tasks = plan(item("A", scope=["src/a.py"]), item("B", scope=["src/b.py"]))
    s = F.initial_state(tasks)
    tok = F.acquire(tasks, s, "A", now=0)
    F.quarantine(s, "A", tok, reason="provider_auth")
    F.unblock(s, "A", "use the other channel")
    assert s["tasks"]["A"]["status"] == "READY"
    assert s["tasks"]["A"].get("blocked_reason") is None
    assert "other channel" in F.last_feedback(s, "A")
    assert s["tasks"]["A"]["feedback"][-1]["source"] == "opus"
    with pytest.raises(F.InvalidPlan):
        F.unblock(s, "B", "not blocked")
    F.validate_state(tasks, s)


def test_release_expired_returns_ready_without_strike_third_expiry_blocks():
    tasks = plan(bitem("A", "Ф3"))
    s = F.initial_state(tasks)
    F.acquire(tasks, s, "A", now=0, lifetime=10)
    assert F.release_expired(s, now=5) == []
    assert F.release_expired(s, now=11) == ["A"]
    row = s["tasks"]["A"]
    assert row["status"] == "READY" and row["lease"] is None and row["attempts"] == 1
    assert F.strikes_for(s, "Ф3") == 0
    F.validate_state(tasks, s)
    assert F.ready(tasks, s) == ["A"]
    F.acquire(tasks, s, "A", now=20, lifetime=10)
    F.release_expired(s, now=31)
    assert s["tasks"]["A"]["status"] == "READY"
    F.acquire(tasks, s, "A", now=40, lifetime=10)
    assert F.release_expired(s, now=51) == ["A"]
    row = s["tasks"]["A"]
    assert row["status"] == "BLOCKED" and row["blocked_reason"] == "lease_expired"
    assert F.strikes_for(s, "Ф3") == 0
    F.validate_state(tasks, s)


def test_acquire_charge_flag_and_charge_call():
    tasks = plan(item())
    s = F.initial_state(tasks)
    F.acquire(tasks, s, "T1", now=0, charge=False)
    assert s["model_calls"] == 0
    F.charge_call(s, "T1")
    F.charge_call(s, "T1")
    assert s["model_calls"] == 2
    s["max_model_calls"] = 2
    with pytest.raises(F.InvalidPlan):
        F.charge_call(s, "T1")
    assert s["model_calls"] == 2


def test_note_infra_counts_streak_and_resets_on_success():
    s = F.initial_state(plan(item()))
    assert [F.note_infra(s, False) for _ in range(3)] == [1, 2, 3]
    assert s["infra_streak"] == 3
    assert F.note_infra(s, True) == 0
    assert F.note_infra(s, False) == 1


def _na(tasks, s, **kw):
    kw.setdefault("now", 1000.0)
    kw.setdefault("channel_wait_s", 0)
    kw.setdefault("backlog_has_more", False)
    return F.next_action(s, kw["now"], kw["channel_wait_s"], kw["backlog_has_more"], tasks)


def test_next_action_run_wait_triage_hold_done():
    tasks = plan(item("A", scope=["src/a.py"]),
                 dict(item("O", scope=["src/o.py"]), only_opus=True))
    s = F.initial_state(tasks)
    r = _na(tasks, s)
    assert r["action"] == "RUN" and r["task_id"] == "A" and r["reason"]
    r = _na(tasks, s, channel_wait_s=30)
    assert r["action"] == "WAIT" and r["wait_s"] == 30
    tok = F.acquire(tasks, s, "A", now=0)
    F.settle(s, "A", tok, tests_ok=True, evidence="1" * 64)
    r = _na(tasks, s, backlog_has_more=True)
    assert r["action"] == "PROMOTE" and r["task_id"] == "A"
    F.mark_promoted(s, "A", "abc1234")
    r = _na(tasks, s, backlog_has_more=True)
    assert r["action"] == "TRIAGE"
    r = _na(tasks, s)
    assert r["action"] == "HOLD"
    s["tasks"]["O"]["status"] = "FAILED"; s["tasks"]["O"]["reason"] = "quarantine"
    assert _na(tasks, s)["action"] == "DONE"


def test_next_action_priority_order_and_dependencies():
    rows = [dict(item("B", scope=["src/b.py"]), priority="P1"),
            dict(item("A", scope=["src/a.py"]), priority="P2"),
            dict(item("C", scope=["src/c.py"], deps=["A"]), priority="P0")]
    tasks = plan(*rows)
    s = F.initial_state(tasks)
    assert _na(tasks, s)["task_id"] == "B"
    assert F.ready(tasks, s)[0] == "B"
    s["tasks"]["B"]["status"] = "PROMOTED"
    assert _na(tasks, s)["task_id"] == "A"


def test_next_action_waits_for_not_before_and_running():
    tasks = plan(item("A", scope=["src/a.py"]))
    s = F.initial_state(tasks)
    s["tasks"]["A"]["not_before"] = 1060.0
    r = _na(tasks, s)
    assert r["action"] == "WAIT" and 59 <= r["wait_s"] <= 60
    s["tasks"]["A"]["not_before"] = 1001.0
    assert _na(tasks, s)["wait_s"] == 5
    s["tasks"]["A"].pop("not_before")
    F.acquire(tasks, s, "A", now=999)
    r = _na(tasks, s)
    assert r["action"] == "WAIT" and r["wait_s"] >= 5


def test_next_action_uses_ready_conflict_rules_and_privacy_flag():
    tasks = plan(item("A", scope=["src/a.py"]),
                 dict(item("B", scope=["src/b.py"]), read_files=["src/a.py"]),
                 dict(item("P", scope=["src/p.py"], safe=False)))
    s = F.initial_state(tasks)
    F.acquire(tasks, s, "A", now=999)
    # B reads what A writes, P is private: nothing runnable, A still running
    r = _na(tasks, s)
    assert r["action"] == "WAIT"
    tok = s["tasks"]["A"]["lease"]
    F.settle(s, "A", tok, tests_ok=True, evidence="1" * 64)
    F.mark_promoted(s, "A", "abc1234")
    assert _na(tasks, s)["task_id"] == "B"
    s["tasks"]["B"]["status"] = "PROMOTED"
    assert _na(tasks, s)["action"] == "HOLD"
    assert F.next_action(s, 1000.0, 0, False, tasks, google=False)["task_id"] == "P"


def test_next_action_hold_for_failed_without_quarantine_and_blocked_dependency():
    tasks = plan(item("A", scope=["src/a.py"]), item("B", scope=["src/b.py"], deps=["A"]))
    s = F.initial_state(tasks)
    s["tasks"]["A"]["status"] = "FAILED"
    assert _na(tasks, s)["action"] == "HOLD"
    F._block(s["tasks"]["A"], "x", 1000.0)                  # <id>: a block has a reason and a term
    assert _na(tasks, s) == {"action": "HOLD", "reason": "blocked_until", "wait_s": 300.0}
    assert _na(tasks, s, now=1300.0)["action"] == "UNBLOCK"  # past the term the loop lifts it itself
    s["tasks"]["A"]["status"] = "FAILED"; s["tasks"]["A"]["reason"] = "quarantine"
    assert _na(tasks, s)["action"] == "HOLD"  # B depends on a dead task
    s["tasks"]["B"]["status"] = "FAILED"; s["tasks"]["B"]["reason"] = "quarantine"
    assert _na(tasks, s)["action"] == "DONE"


def test_next_action_review_promotes_oldest_before_run():
    tasks = plan(item("A", scope=["src/a.py"]), item("B", scope=["src/b.py"]),
                 item("C", scope=["src/c.py"]))
    s = F.initial_state(tasks)
    for tid, now in (("B", 1), ("A", 2)):
        tok = F.acquire(tasks, s, tid, now=now)
        F.settle(s, tid, tok, tests_ok=True, evidence="1" * 64)
        s["tasks"][tid]["reviewed_at"] = now
    r = _na(tasks, s)
    assert r["action"] == "PROMOTE" and r["task_id"] == "B"


def test_settle_strike_false_gives_no_strike():
    tasks = plan(bitem("A", "Ф5"))
    s = F.initial_state(tasks)
    tok = F.acquire(tasks, s, "A", now=0)
    assert F.settle(s, "A", tok, tests_ok=False, evidence="a" * 64, strike=False) == "READY"
    assert F.strikes_for(s, "Ф5") == 0


def test_strike_keys_do_not_collide_between_backlog_id_and_task_id():
    tasks = plan(item("EQX07", scope=["src/a.py"]), bitem("X", "EQX07", scope=["src/b.py"]))
    s = F.initial_state(tasks)
    tok = F.acquire(tasks, s, "EQX07", now=0)
    F.settle(s, "EQX07", tok, tests_ok=False, evidence="a" * 64, max_attempts=9)
    assert F.strikes_for(s, "EQX07") == 0
    assert s["strikes"] == {"task:EQX07": 1}
    tok = F.acquire(tasks, s, "X", now=1)
    F.settle(s, "X", tok, tests_ok=False, evidence="a" * 64, max_attempts=9)
    assert F.strikes_for(s, "EQX07") == 1


def test_quarantine_fails_ready_blocked_and_settling_running_but_not_review():
    tasks = plan(bitem("A", "Ф6", scope=["src/a.py"]), bitem("R", "Ф6", scope=["src/r.py"]),
                 bitem("G", "Ф6", scope=["src/g.py"]), bitem("W", "Ф6", scope=["src/w.py"]))
    s = F.initial_state(tasks)
    tr = F.acquire(tasks, s, "R", now=0)
    F.settle(s, "R", tr, tests_ok=True, evidence="1" * 64)       # REVIEW
    tw = F.acquire(tasks, s, "W", now=0)                           # RUNNING
    tg = F.acquire(tasks, s, "G", now=0)
    F.quarantine(s, "G", tg, reason="provider_auth")               # BLOCKED
    for k in range(3):
        tok = F.acquire(tasks, s, "A", now=k)
        F.settle(s, "A", tok, tests_ok=False, evidence="a" * 64, max_attempts=9)
    assert s["tasks"]["R"]["status"] == "REVIEW"
    assert s["tasks"]["G"]["status"] == "FAILED" and s["tasks"]["G"]["reason"] == "quarantine"
    assert F.settle(s, "W", tw, tests_ok=True, evidence="1" * 64) == "FAILED"
    assert s["tasks"]["W"]["reason"] == "quarantine"


def test_new_synced_task_of_quarantined_backlog_is_failed_at_once():
    t1 = plan(bitem("A", "Ф7"))
    s = F.initial_state(t1)
    for k in range(3):
        tok = F.acquire(t1, s, "A", now=k)
        F.settle(s, "A", tok, tests_ok=False, evidence="a" * 64, max_attempts=9)
    t2 = plan(bitem("A", "Ф7"), bitem("N", "Ф7", scope=["src/n.py"]))
    F.sync_state(t2, s)
    assert s["tasks"]["N"]["status"] == "FAILED" and s["tasks"]["N"]["reason"] == "quarantine"


def test_unblock_from_quarantine_resets_strikes_of_that_backlog_id():
    tasks = plan(bitem("A", "Ф8a"))
    s = F.initial_state(tasks)
    for k in range(3):
        tok = F.acquire(tasks, s, "A", now=k)
        F.settle(s, "A", tok, tests_ok=False, evidence="a" * 64, max_attempts=9)
    assert F.is_quarantined(s, "Ф8a")
    F.unblock(s, "A", "new instructions")
    assert F.strikes_for(s, "Ф8a") == 0 and not F.is_quarantined(s, "Ф8a")
    assert s["tasks"]["A"]["status"] == "READY"


def test_old_state_json_without_new_fields_loads(tmp_path):
    tasks = plan(item("A", scope=["src/a.py"]))
    s = F.initial_state(tasks)
    for k in ("strikes", "infra_streak"):
        s.pop(k)
    for k in ("backlog_id", "priority"):
        s["tasks"]["A"].pop(k, None)
    path = tmp_path / "state.json"
    path.write_text(json.dumps(s), encoding="utf-8")
    loaded = F.load_state(path, tasks)
    assert loaded["strikes"] == {} and loaded["infra_streak"] == 0
    assert loaded["tasks"]["A"]["backlog_id"] == ""


def test_validate_state_checks_feedback_structure():
    tasks = plan(item())
    for bad in ("text", [1], [{"source": "x", "text": "t"}], [{"source": "gate", "text": 5}]):
        s = F.initial_state(tasks)
        s["tasks"]["T1"]["feedback"] = bad
        with pytest.raises(F.InvalidPlan):
            F.validate_state(tasks, s)
    s = F.initial_state(tasks)
    s["tasks"]["T1"]["feedback"] = [{"source": "gate", "text": "ok"}]
    F.validate_state(tasks, s)


def test_append_tasks_rejects_non_string_ids_and_broken_plan_json(tmp_path):
    p = tmp_path / "plan.json"
    p.write_text(json.dumps({"tasks": [item("A")]}))
    for bad in (dict(item("B"), id=5), dict(item("B"), backlog_id=7), dict(item("B"), backlog_id=["x"])):
        with pytest.raises(F.InvalidPlan):
            F.append_tasks(p, [bad])
    p.write_text("{broken", encoding="utf-8")
    with pytest.raises(F.InvalidPlan):
        F.append_tasks(p, [item("B")])


def test_append_tasks_holds_plan_lockdir(tmp_path):
    p = tmp_path / "plan.json"
    p.write_text(json.dumps({"tasks": [item("A")]}))
    lock = p.with_suffix(p.suffix + ".lockdir")
    lock.mkdir()
    before = p.read_bytes()
    with pytest.raises(F.InvalidPlan):
        F.append_tasks(p, [item("B", scope=["src/b.py"])], lock_timeout_s=0.2)
    assert p.read_bytes() == before
    lock.rmdir()
    F.append_tasks(p, [item("B", scope=["src/b.py"])])
    assert not lock.exists()


def test_bearer_is_case_insensitive_and_email_in_source_is_not_rejected(tmp_path):
    s = F.initial_state(plan(item()))
    F.add_feedback(s, "T1", "gate", "header bear" "er " + "q" * 30 + " end")
    assert "q" * 30 not in F.last_feedback(s, "T1")
    src = tmp_path / "ok.py"
    src.write_text("AUTHOR = 'someone@example.org'\n", encoding="utf-8")
    assert F.safe_source(src)


def test_free_text_written_to_state_is_redacted():
    tasks = plan(item())
    s = F.initial_state(tasks)
    tok = F.acquire(tasks, s, "T1", now=0)
    with pytest.raises(F.InvalidPlan):
        F.quarantine(s, "T1", tok, reason="leak s" "k-" + "z" * 30)
    F.unblock  # noqa
    s["tasks"]["T1"]["status"] = "BLOCKED"
    F.unblock(s, "T1", "token s" "k-" + "z" * 30)
    assert "z" * 30 not in json.dumps(s)


def test_requeue_review_back_to_ready_without_strike():
    tasks = plan(bitem("A", "Ф9a"))
    s = F.initial_state(tasks)
    with pytest.raises(F.InvalidPlan):
        F.requeue(s, "A", "not in review")
    tok = F.acquire(tasks, s, "A", now=0)
    F.settle(s, "A", tok, tests_ok=True, evidence="1" * 64)
    before = dict(s["strikes"])
    F.requeue(s, "A", "base moved; token s" "k-" + "z" * 30)
    row = s["tasks"]["A"]
    assert row["status"] == "READY" and row["attempts"] == 0
    assert s["strikes"] == before
    assert row["feedback"][-1]["source"] == "gate"
    assert "base moved" in F.last_feedback(s, "A") and "z" * 30 not in F.last_feedback(s, "A")
    F.validate_state(tasks, s)
    for status in ("DONE", "PROMOTED", "FAILED", "BLOCKED"):
        row["status"] = status
        with pytest.raises(F.InvalidPlan):
            F.requeue(s, "A", "x")


def _ut(tid="U1", path="tests/test_new.py", **kw):
    return dict(item(tid, scope=[path]), tests=[path], kind="unit_test", **kw)


def test_unit_test_kind_may_touch_its_own_test_file_that_does_not_exist_yet():
    tasks = plan(_ut())
    assert tasks["U1"].kind == "unit_test"
    s = F.initial_state(tasks)
    assert s["tasks"]["U1"]["kind"] == "unit_test"
    assert F.ready(tasks, s) == ["U1"]


@pytest.mark.parametrize("bad", [
    dict(touch_files=["echo_sync/x.py"], tests=["echo_sync/x.py"]),
    dict(touch_files=["tests/test_a.py"], tests=["tests/test_b.py"]),
    dict(touch_files=["tests/test_a.py", "src/x.py"], tests=["tests/test_a.py"]),
    dict(touch_files=["tests/helper.py"], tests=["tests/helper.py"]),
])
def test_unit_test_kind_rejects_files_outside_its_test(bad):
    with pytest.raises(F.InvalidPlan):
        plan(dict(_ut(), **bad))


def test_code_kind_default_forbids_touch_and_tests_overlap():
    assert plan(item())["T1"].kind == "code"
    row = item(scope=["tests/test_safe.py"])
    with pytest.raises(F.InvalidPlan):
        plan(row)
    with pytest.raises(F.InvalidPlan):
        plan(dict(item(), kind="other"))
    with pytest.raises(F.InvalidPlan):
        plan(dict(item(), tests=["tests/helper.py"]))


def test_append_tasks_accepts_unit_test_kind_and_checks_it(tmp_path):
    p = tmp_path / "plan.json"
    added = F.append_tasks(p, [_ut()])
    assert list(added) == ["U1"]
    with pytest.raises(F.InvalidPlan):
        F.append_tasks(p, [dict(_ut("U2", "src/x.py"))])


def test_stale_plan_lock_is_removed_and_reported_fresh_one_is_waited_on(tmp_path):
    import os
    p = tmp_path / "plan.json"
    p.write_text(json.dumps({"tasks": [item("A")]}))
    lock = p.with_suffix(p.suffix + ".lockdir")
    lock.mkdir()
    F.LOCK_EVENTS.clear()
    with pytest.raises(F.InvalidPlan):
        F.append_tasks(p, [item("B", scope=["src/b.py"])], lock_timeout_s=0.2)
    assert lock.exists() and not F.LOCK_EVENTS
    old = _time.time() - 500
    os.utime(lock, (old, old))
    assert list(F.append_tasks(p, [item("B", scope=["src/b.py"])])) == ["B"]
    assert F.LOCK_EVENTS and F.LOCK_EVENTS[0]["event"] == "stale_lock_removed"
    assert not lock.exists()


def test_acquire_uses_given_now_for_not_before():
    tasks = plan(item())
    s = F.initial_state(tasks)
    s["tasks"]["T1"]["not_before"] = 500.0
    with pytest.raises(F.InvalidPlan):
        F.acquire(tasks, s, "T1", now=100)
    F.acquire(tasks, s, "T1", now=600)


def test_code_overlap_check_is_case_insensitive():
    row = dict(item(scope=["tests/Test_X.py"]), tests=["tests/test_x.py"])
    with pytest.raises(F.InvalidPlan):
        plan(row)


def test_feedback_structure_limits_in_validate_state():
    tasks = plan(item())
    ok = {"source": "gate", "text": "t"}
    for bad in ([ok] * 4, [{"source": ["gate"], "text": "t"}],
                [{"source": "gate", "text": "x" * 2001}]):
        s = F.initial_state(tasks)
        s["tasks"]["T1"]["feedback"] = bad
        with pytest.raises(F.InvalidPlan):
            F.validate_state(tasks, s)


def test_successful_settle_resets_lease_expiries_and_accept_redacts():
    tasks = plan(item())
    s = F.initial_state(tasks)
    F.acquire(tasks, s, "T1", now=0, lifetime=1)
    F.release_expired(s, now=5)
    assert s["tasks"]["T1"]["lease_expiries"] == 1
    tok = F.acquire(tasks, s, "T1", now=10)
    F.settle(s, "T1", tok, tests_ok=True, evidence="1" * 64)
    assert s["tasks"]["T1"]["lease_expiries"] == 0
    F.accept(s, "T1", reviewer="me@example.org s" "k-" + "z" * 30)
    assert "example.org" not in s["tasks"]["T1"]["reviewer"]
    assert "z" * 30 not in s["tasks"]["T1"]["reviewer"]


def test_accept_and_mark_promoted_both_satisfy_dependencies():
    tasks = plan(item("A", scope=["src/a.py"]), item("B", scope=["src/b.py"]),
                 item("C", scope=["src/c.py"], deps=["A", "B"]))
    s = F.initial_state(tasks)
    for tid in ("A", "B"):
        tok = F.acquire(tasks, s, tid, now=0)
        F.settle(s, tid, tok, tests_ok=True, evidence="1" * 64)
    F.accept(s, "A", reviewer="opus")
    assert F.ready(tasks, s) == []
    F.mark_promoted(s, "B", "abc1234")
    assert s["tasks"]["A"]["status"] == "DONE" and s["tasks"]["B"]["status"] == "PROMOTED"
    assert F.ready(tasks, s) == ["C"]


def test_defer_postpones_without_strike_and_refunds_the_attempt():
    tasks=plan(item());s=F.initial_state(tasks)
    token=F.acquire(tasks,s,"T1",now=1,charge=False)
    assert s["tasks"]["T1"]["attempts"]==1
    assert F.defer(s,"T1",token,"rate_minute",34,now=100)=="READY"
    row=s["tasks"]["T1"]
    assert row["attempts"]==0 and row["not_before"]==134 and row["defer_reason"]=="rate_minute"
    assert row["lease"] is None and not s.get("strikes")
    assert F.ready(tasks,s,now=120)==[] and F.ready(tasks,s,now=135)==["T1"]
    t2=F.acquire(tasks,s,"T1",now=200,charge=False)
    with pytest.raises(F.InvalidPlan,match="reason"):
        F.defer(s,"T1",t2,"free text from a model",5)
    with pytest.raises(F.InvalidPlan,match="lease"):
        F.defer(s,"T1","0"*32,"transient",5)


@pytest.mark.parametrize("reason",["already_green","context_too_large","no_independent_reviewer"])
def test_new_blocked_reasons_are_whitelisted(reason):
    tasks=plan(item());s=F.initial_state(tasks)
    token=F.acquire(tasks,s,"T1",now=1,charge=False)
    F.quarantine(s,"T1",token,reason=reason)
    assert s["tasks"]["T1"]["blocked_reason"]==reason and not s.get("strikes")


# ---- runner gates and provider faults, ported to the factory_gate / structural-error contract ----
# Replaced tests and their successors (same protection):
#   test_real_local_pytest_gate_on_synthetic_sources     -> test_real_pytest_gate_accepts_a_real_fix
#   test_rate_limit_fallback_starts_from_clean_allowlisted_copy -> test_transient_retry_starts_from_clean_allowlisted_copy
#   test_compile_gate_rejects_illegal_top_level_return   -> test_compile_gate_rejects_illegal_top_level_return
#   test_gate_rejects_passing_suite_that_only_skips      -> test_gate_never_accepts_a_suite_that_only_skips
#   test_gate_rejects_test_that_mutates_immutable_fixture_during_pytest -> same name, via once()
#   test_nonrecoverable_provider_failures_quarantine_task -> test_provider_faults_are_postponements_not_strikes
#                                                           + test_timeout_blocks_the_task_as_infrastructure
#                                                           + test_invalid_key_marks_the_channel_dead

def _repo(tmp_path, test_body="from src.logic import value\ndef test_value(): assert value()==2\n"):
    root=tmp_path/"repo";root.mkdir()
    (root/"src").mkdir();(root/"tests").mkdir()
    (root/"src"/"logic.py").write_text("def value(): return 1\n")
    (root/"tests"/"test_safe.py").write_text(test_body)
    p=tmp_path/"plan.json";p.write_text(json.dumps([item(scope=["src/logic.py"])]))
    return root,p


def _once(tmp_path,monkeypatch,root,p,model,**extra):
    monkeypatch.setenv("GOOGLE_GENERATIVE_AI_API_KEY","synthetic-placeholder")
    monkeypatch.setattr(W.shutil,"which",lambda _: "kilo")
    monkeypatch.setattr(W.time,"sleep",lambda _: None)
    monkeypatch.setattr(W,"neighbor_tests",lambda r,t: [])
    monkeypatch.setattr(W,"profile_names",lambda: ())
    def with_reviewer(task, *a, **kw):  # the reviewer (no writable files) approves; the coder is the scripted model
        if not task.touch_files:
            # an approval answers the rubric: it cites a real line of the test the critic sees
            lines=[x for x in (root/"tests"/"test_safe.py").read_text().splitlines() if x.strip()]
            answer=json.dumps(dict(approved=True,reasons=[],defect_assert_line=lines[-1],
                                   fix_changes_value="value() returns 2, the base returned 1",independent_asserts=[]))
            return 0,json.dumps(dict(type="text",part=dict(text=answer))).encode(),b""
        return model(task,*a,**kw)
    monkeypatch.setattr(W,"model_attempt",with_reviewer)
    extra.setdefault("review_model","google/flash")
    if "channel_config" not in extra:   # a full chain of two critics, each another model (a short chain never approves)
        cfg=tmp_path/"channels.json"
        cfg.write_text(json.dumps(dict(channels=[dict(id="c%d"%i,group="g%d"%i,model=m,key_env="GOOGLE_GENERATIVE_AI_API_KEY",
                                                      tpm=100000,rpd=100,verified=True)
                                                 for i,m in enumerate(("google/gemma","google/flash","google/pro","google/lite"))])))
        extra["channel_config"]=cfg
    return W.once(root=root,plan=p,checkpoint=tmp_path/"state.json",staging=tmp_path/"stage",
                  small_model="google/gemma",large_model="google/flash",execute=True,
                  acknowledge=True,**extra)


def _fix(value="2"):
    def model(task, workdir, name, timeout, **kw):
        (workdir/"src"/"logic.py").write_text("def value(): return %s\n"%value)
        return 0,b"",b""
    return model


def test_real_pytest_gate_accepts_a_real_fix(tmp_path,monkeypatch):
    root,p=_repo(tmp_path)
    result=_once(tmp_path,monkeypatch,root,p,_fix())
    assert result["status"]=="REVIEW" and len(result["receipt_sha256"])==64 and result["changed"]==1
    assert (tmp_path/"stage"/"for-review"/"T1"/"src"/"logic.py").read_text()=="def value(): return 2\n"
    assert (root/"src"/"logic.py").read_text()=="def value(): return 1\n"


def test_transient_retry_starts_from_clean_allowlisted_copy(tmp_path,monkeypatch):
    root,p=_repo(tmp_path)
    called=[]
    def fake_kilo(task, workdir, model, timeout, **kw):
        called.append((model,workdir))
        if len(called)==1:
            (workdir/"forbidden.py").write_text("unapproved=1")
            return 1,b"",b"HTTP 503 service unavailable"
        assert not (workdir/"forbidden.py").exists(), "retry contaminated with earlier incomplete work"
        (workdir/"src"/"logic.py").write_text("def value():return 2\n")
        return 0,b"synthetic success",b""
    result=_once(tmp_path,monkeypatch,root,p,fake_kilo)
    assert result["status"]=="REVIEW"
    assert len(called)==2 and called[0][1]!=called[1][1]
    assert (tmp_path/"stage"/"for-review"/"T1"/"src"/"logic.py").exists()
    state=json.loads((tmp_path/"state.json").read_text())
    assert state["model_calls"]==4 and state["tasks"]["T1"]["status"]=="REVIEW" and not state.get("strikes")  # 2 coder tries + 2 critics


def test_compile_gate_rejects_illegal_top_level_return(tmp_path,monkeypatch):
    root,p=_repo(tmp_path)
    def model(task, workdir, name, timeout, **kw):
        (workdir/"src"/"logic.py").write_text("return 5\n")
        return 0,b"",b""
    result=_once(tmp_path,monkeypatch,root,p,model)
    assert result["status"]=="READY" and "compile" in result["reason"]
    assert not (tmp_path/"stage"/"for-review"/"T1").exists()
    assert json.loads((tmp_path/"state.json").read_text())["strikes"]=={"task:T1":1}


def test_gate_never_accepts_a_suite_that_only_skips(tmp_path,monkeypatch):
    root,p=_repo(tmp_path,"import pytest\n" "@pytest.mark.skip(reason='synthetic')\ndef test_synthetic():assert True\n")
    asked=[]
    def model(*a,**kw):
        asked.append(1);return _fix()(*a,**kw)
    result=_once(tmp_path,monkeypatch,root,p,model)
    assert asked==[], "the base is not red: no model call may be spent"
    assert result["status"]=="READY" and result["reason"]=="gate_unknown"
    assert not (tmp_path/"stage"/"for-review"/"T1").exists()


def test_candidate_that_adds_a_skip_is_rejected_as_weakening(tmp_path,monkeypatch):
    root,p=_repo(tmp_path)
    def skipper(task, workdir, name, timeout, **kw):
        (workdir/"src"/"logic.py").write_text("import pytest\ndef value():\n    pytest.skip('x')\n")
        return 0,b"",b""
    result=_once(tmp_path,monkeypatch,root,p,skipper)
    assert result["status"]=="READY" and result["reason"].startswith("weakening")


def test_gate_rejects_test_that_mutates_immutable_fixture_during_pytest(tmp_path,monkeypatch):
    root,p=_repo(tmp_path,
        "from pathlib import Path\nfrom src.logic import value\n"
        "def test_mutates():\n"
        "    Path(__file__).write_text('def test_mutates(): assert True\\n')\n"
        "    assert value()==2\n")
    result=_once(tmp_path,monkeypatch,root,p,_fix())
    assert result["status"]=="READY" and "immutable" in result["reason"]
    assert "assert value()==2" in (root/"tests"/"test_safe.py").read_text(), "the source test was rewritten"


def test_provider_faults_are_postponements_not_strikes(tmp_path,monkeypatch):
    cases=[(b'{"type":"error","error":{"name":"APIError","data":{"statusCode":429,"message":"rate limit"}}}',"rate_minute",False),
           (b'{"type":"error","error":{"name":"APIError","data":{"statusCode":403,"message":"PERMISSION_DENIED"}}}',"region",False)]
    for i,(out,reason,infra) in enumerate(cases):
        sub=tmp_path/str(i);sub.mkdir()
        root,p=_repo(sub)
        result=_once(sub,monkeypatch,root,p,lambda *a,**kw:(1,out,b""),max_attempts=1)
        assert result["status"]=="READY" and result["reason"]==reason and result["infra"] is infra
        state=json.loads((sub/"state.json").read_text())
        assert state["tasks"]["T1"]["status"]=="READY" and not state.get("strikes")
        assert state["tasks"]["T1"]["attempts"]==0 and state["tasks"]["T1"]["not_before"]>0


def test_timeout_blocks_the_task_as_infrastructure(tmp_path,monkeypatch):
    root,p=_repo(tmp_path)
    busy=(b'{"type":"tool_use","part":{"tool":"read","state":{"status":"completed","input":{}}}}\n'
          b'{"type":"step_finish","part":{"reason":"tool-calls","tokens":{"input":100,"output":5}}}\n')
    result=_once(tmp_path,monkeypatch,root,p,lambda *a,**kw:(124,busy,b"worker-timeout"))
    assert result["status"]=="BLOCKED" and result["blocked_reason"]=="worker_timeout" and result["infra"] is True


def test_invalid_key_marks_the_channel_dead(tmp_path,monkeypatch):
    root,p=_repo(tmp_path)
    cfg=tmp_path/"ch.json"
    cfg.write_text(json.dumps(dict(channels=[dict(id="c",group="g",model="google/gemma",key_env="KEY",
                                                  tpm=100000,rpd=100,verified=True)])))
    monkeypatch.setenv("KEY","synthetic")
    body=b'{"type":"error","error":{"name":"APIError","data":{"statusCode":400,"message":"API key not valid"}}}'
    result=_once(tmp_path,monkeypatch,root,p,lambda *a,**kw:(1,body,b""),channel_config=cfg,max_attempts=1)
    assert result["status"]=="READY" and result["reason"]=="key_invalid" and result["infra"] is True
    state=json.loads((tmp_path/"state.json").read_text())
    assert "c" in state["channel_quotas"]["dead"] and not state.get("strikes")


def test_defer_streak_counts_the_same_reason_in_a_row_and_settle_resets_it():
    tasks=plan(item());s=F.initial_state(tasks)
    for n in (1,2,3):
        token=F.acquire(tasks,s,"T1",now=n*1000,charge=False)
        F.defer(s,"T1",token,"gate_unknown",5,now=n*1000)
        assert F.defer_streak(s,"T1","gate_unknown")==n
    token=F.acquire(tasks,s,"T1",now=9000,charge=False)
    F.defer(s,"T1",token,"transient",5,now=9000)
    assert F.defer_streak(s,"T1","gate_unknown")==0 and F.defer_streak(s,"T1","transient")==1
    token=F.acquire(tasks,s,"T1",now=9100,charge=False)
    F.settle(s,"T1",token,tests_ok=True,evidence="a"*64)
    assert F.defer_streak(s,"T1","transient")==0


def test_block_and_unblock_clear_a_stale_pending_review():
    tasks=plan(item());s=F.initial_state(tasks)
    token=F.acquire(tasks,s,"T1",now=1,charge=False)
    s["tasks"]["T1"]["pending_review"]={"workdir":"x","baseline_digest":"y"}
    F.quarantine(s,"T1",token,reason="scope_violation")
    assert "pending_review" not in s["tasks"]["T1"]
    s["tasks"]["T1"]["pending_review"]={"workdir":"x","baseline_digest":"y"}
    F.unblock(s,"T1","retry from scratch")
    assert "pending_review" not in s["tasks"]["T1"]


def test_model_call_budget_is_daily_and_exhaustion_is_a_typed_error():
    import time as _t
    tasks=plan(item());s=F.initial_state(tasks)
    s["max_model_calls"]=2
    F.charge_call(s,"T1");F.charge_call(s,"T1")
    with pytest.raises(F.BudgetExhausted):
        F.charge_call(s,"T1")
    assert issubclass(F.BudgetExhausted,F.InvalidPlan)
    assert 60<=F.seconds_to_local_midnight()<=86400
    s["budget_day"]="2000-01-01"     # yesterday's spending is forgotten at local midnight
    assert F.charge_call(s,"T1")==1 and s["budget_day"]==_t.strftime("%Y-%m-%d")
    s["model_calls"]=2
    with pytest.raises(F.BudgetExhausted):
        F.acquire(tasks,s,"T1",charge=False)


def test_new_blocked_reasons_for_escalation_are_whitelisted():
    for reason in ("gate_unknown","provider_error"):
        tasks=plan(item());s=F.initial_state(tasks)
        token=F.acquire(tasks,s,"T1",now=1,charge=False)
        F.quarantine(s,"T1",token,reason=reason)
        assert s["tasks"]["T1"]["blocked_reason"]==reason



def test_append_deduplicates_by_id_and_by_backlog_id_only_within_the_same_kind(tmp_path):
    path=tmp_path/"plan.json"
    sub=dict(id="EQX15_t",title="tests",touch_files=["tests/test_f_eQX15.py"],tests=["tests/test_f_eQX15.py"],
             privacy_safe=True,backlog_id="EQX15",kind="unit_test")
    main=dict(id="EQX15",title="main",touch_files=["echo_sync/a.py"],tests=["tests/test_f_eQX15.py"],
              privacy_safe=True,backlog_id="EQX15",depends_on=["EQX15_t"])
    twin=dict(main,id="EQX15_again")
    added=F.append_tasks(path,[sub,main,twin])
    assert list(added)==["EQX15_t","EQX15"]
    assert [s["reason"] for s in added.skipped]==["duplicate backlog_id"] and added.skipped[0]["id"]=="EQX15_again"
    again=F.append_tasks(path,[sub,main])
    assert list(again)==[] and {s["reason"] for s in again.skipped}=={"duplicate id"}


def test_no_diff_and_reviewer_failed_are_blocked_reasons_and_base_moved_is_gone():
    for reason in ("no_diff","reviewer_failed"):
        tasks=plan(item());s=F.initial_state(tasks)
        token=F.acquire(tasks,s,"T1",now=1,charge=False)
        F.quarantine(s,"T1",token,reason=reason)
        assert s["tasks"]["T1"]["blocked_reason"]==reason
    assert "base_moved" not in F.DEFER_REASONS


def test_defer_and_streak_survive_corrupt_streak_values():
    tasks=plan(item());s=F.initial_state(tasks)
    for i, junk in enumerate(("junk",5,["x"],None)):
        s["tasks"]["T1"]["defer_streak"]=junk
        assert F.defer_streak(s,"T1","transient")==0
        token=F.acquire(tasks,s,"T1",now=1000*(i+1),charge=False)
        F.defer(s,"T1",token,"transient",1,now=1000*(i+1))
        assert F.defer_streak(s,"T1","transient")==1



def test_append_rejects_a_non_string_kind_and_defer_survives_a_non_int_counter(tmp_path):
    bad=dict(id="K1",title="x",touch_files=["echo_sync/a.py"],tests=["tests/test_a.py"],privacy_safe=True,kind=["code"])
    with pytest.raises(F.InvalidPlan):
        F.append_tasks(tmp_path/"p.json",[bad])
    tasks=plan(item());s=F.initial_state(tasks)
    s["tasks"]["T1"]["defer_streak"]={"reason":"transient","n":"3"}
    token=F.acquire(tasks,s,"T1",now=1,charge=False)
    F.defer(s,"T1",token,"transient",1,now=1)
    assert F.defer_streak(s,"T1","transient")==1


# ---- amend_task: Opus corrects the scope of a live plan ---------------------------------------

def _amend_plan(tmp_path):
    import json as _j
    plan = tmp_path / "plan.json"
    plan.write_text(_j.dumps({"tasks": [
        {"id": "A1", "title": "a", "touch_files": ["tools/a.py"], "tests": ["tests/test_a.py"],
         "privacy_safe": True, "backlog_id": "BA"},
        {"id": "A2", "title": "b", "touch_files": ["tools/b.py"], "tests": ["tests/test_b.py"],
         "privacy_safe": True, "backlog_id": "BB"}]}), encoding="utf-8")
    return plan


def test_amend_task_changes_only_given_fields(tmp_path):
    import json as _j
    from tools import agent_factory as F
    plan = _amend_plan(tmp_path)
    row = F.amend_task(plan, "A1", touch_files=["tools/new.py"], goal="do X",
                       context_targets={"tools/new.py": "func"}, depends_on=["A2"])
    data = _j.loads(plan.read_text(encoding="utf-8"))
    a1 = [r for r in data["tasks"] if r["id"] == "A1"][0]
    assert a1 == row
    assert a1["touch_files"] == ["tools/new.py"] and a1["tests"] == ["tests/test_a.py"]
    assert a1["goal"] == "do X" and a1["depends_on"] == ["A2"]
    assert a1["context_targets"] == {"tools/new.py": "func"}
    assert [r for r in data["tasks"] if r["id"] == "A2"][0]["touch_files"] == ["tools/b.py"]


def test_amend_task_invalid_plan_changes_nothing(tmp_path):
    import pytest
    from tools import agent_factory as F
    plan = _amend_plan(tmp_path)
    before = plan.read_text(encoding="utf-8")
    for bad in ({"touch_files": ["../x.py"]}, {"tests": ["tools/not_a_test.py"]},
                {"depends_on": ["NOPE"]}, {"touch_files": []}):
        with pytest.raises(F.InvalidPlan):
            F.amend_task(plan, "A1", **bad)
    with pytest.raises(F.InvalidPlan):
        F.amend_task(plan, "ZZ", goal="x")
    assert plan.read_text(encoding="utf-8") == before


def test_amend_task_refuses_running_and_review(tmp_path):
    import json as _j
    import pytest
    from tools import agent_factory as F
    plan = _amend_plan(tmp_path)
    tasks = F.read_plan(_j.loads(plan.read_text(encoding="utf-8")))
    st = F.initial_state(tasks)
    for status in ("RUNNING", "REVIEW"):
        st["tasks"]["A1"]["status"] = status
        F.save_atomic(tmp_path / "state.json", st)
        with pytest.raises(F.InvalidPlan):
            F.amend_task(plan, "A1", goal="x")
    st["tasks"]["A1"]["status"] = "BLOCKED"
    F.save_atomic(tmp_path / "state.json", st)
    assert F.amend_task(plan, "A1", goal="x")["goal"] == "x"


# ---- OpenRouter model ids: one optional vendor segment -------------------------------------

import pytest as _pytest_models


@_pytest_models.mark.parametrize("model", [
    "google/gemini-3.5-flash-lite", "openrouter/cohere/north-mini-code:free",
    "openrouter/nvidia/nemotron-3-ultra-" "550b-a" "55b:free", "openrouter/some-model:free"])
def test_model_id_accepts_provider_vendor_model(model):
    from tools import agent_factory as F
    assert F.MODEL_ID.fullmatch(model)


@_pytest_models.mark.parametrize("model", [
    "../x", "a//b", "a/b/c/d", "openrouter/", "/x", "a/../x", "a/..", "openrouter/./x", "a/b:c/d",
    "a b/c", ""])
def test_model_id_rejects_malformed(model):
    from tools import agent_factory as F
    assert not F.MODEL_ID.fullmatch(model)


def test_route_and_channels_accept_the_three_segment_ids():
    from tools import agent_factory as F
    from tools import factory_channels as C
    task = F.read_plan([{"id": "A1", "title": "a", "touch_files": ["tools/a.py"],
                         "tests": ["tests/test_a.py"], "privacy_safe": True}])["A1"]
    m = "openrouter/cohere/north-mini-code:free"
    assert F.route(task, small_model=m, large_model=m) == m
    with _pytest_models.raises(F.InvalidPlan):
        F.route(task, small_model="a//b", large_model=m)
    assert C.MODEL_ID is F.MODEL_ID


# ---- redact: more token shapes; opus feedback is never evicted; unit_test strikes -----------

@_pytest_models.mark.parametrize("text", [
    "gs" "k_" + "A1b2C3d4E5f6" "G7h8I9j0K1l2",
    "xai-" + "A1b2C3d4E5f6" "G7h8I9j0K1l2",
    "hf_" + "A1b2C3d4E5f6" "G7h8I9j0K1l2",
    "GROQ_API_KEY=abcdefgh12345", "MY_TOKEN=abcdefgh12345", "SERVICE_SECRET=abcdefgh12345",
    "name_key = 'abcdefgh12345'"])
def test_redact_new_secret_shapes(text):
    from tools import agent_factory as F
    out = F.redact("before " + text + " after")
    assert "abcdefgh" not in out and "A1b2C3d4" not in out and "[REDACTED]" in out


def test_redact_keeps_short_values_and_plain_words():
    from tools import agent_factory as F
    assert F.redact("SOME_KEY=short and hf_x and the key") == "SOME_KEY=short and hf_x and the key"


def test_opus_feedback_is_not_evicted_by_gate_feedback(tmp_path):
    from tools import agent_factory as F
    plan = [{"id": "A1", "title": "a", "touch_files": ["tools/a.py"], "tests": ["tests/test_a.py"],
             "privacy_safe": True}]
    st = F.initial_state(F.read_plan(plan))
    F.add_feedback(st, "A1", "opus", "scope hint")
    for i in range(6):
        F.add_feedback(st, "A1", "gate", "gate %d" % i)
    text = F.last_feedback(st, "A1")
    assert "scope hint" in text and "gate 5" in text and "gate 2" not in text
    F.validate_state(F.read_plan(plan), st)
    for i in range(4):
        F.add_feedback(st, "A1", "opus", "opus %d" % i)
    text = F.last_feedback(st, "A1")      # the window is 3 in all; the newest failure is never evicted (live 20.11)
    assert text.count("[opus]") == 2 and "gate 5" in text and "opus 3" in text and "opus 1" not in text
    F.validate_state(F.read_plan(plan), st)


def test_the_newest_failure_survives_any_number_of_opus_notes():
    """Live 20.11 02:37: three requeue notes filled the window, every new failure was evicted at once, 14 quarantined
    tasks had no failure class left and factory_requeue could requeue none of them."""
    from tools import agent_factory as F
    plan = [{"id": "A1", "title": "a", "touch_files": ["tools/a.py"], "tests": ["tests/test_a.py"],
             "privacy_safe": True}]
    st = F.initial_state(F.read_plan(plan))
    for i in range(3):
        F.add_feedback(st, "A1", "opus", "retry note %d" % i)
    F.add_feedback(st, "A1", "gate", "[attempt 1] gate: rc=1 (0 required)")
    items = st["tasks"]["A1"]["feedback"]
    assert len(items) == 3 and items[-1] == {"source": "gate", "text": "[attempt 1] gate: rc=1 (0 required)"}
    F.add_feedback(st, "A1", "review", "[attempt 2] review: the test pins nothing")
    sources = [x["source"] for x in st["tasks"]["A1"]["feedback"]]
    assert sources == ["opus", "opus", "review"]          # an older failure goes before any Opus note


def test_unit_test_promotion_resets_its_backlog_strikes():
    from tools import agent_factory as F
    plan = [{"id": "U1", "title": "t", "kind": "unit_test", "touch_files": ["tests/test_u.py"],
             "tests": ["tests/test_u.py"], "privacy_safe": True, "backlog_id": "B9"},
            {"id": "M1", "title": "m", "touch_files": ["tools/m.py"], "tests": ["tests/test_u.py"],
             "privacy_safe": True, "backlog_id": "B9", "depends_on": ["U1"]}]
    st = F.initial_state(F.read_plan(plan))
    st["strikes"] = {"bl:B9": 2, "bl:OTHER": 2}
    st["tasks"]["U1"]["status"] = "REVIEW"
    F.mark_promoted(st, "U1", "abcdef1")
    assert F.strikes_for(st, "B9") == 0 and F.strikes_for(st, "OTHER") == 2


def test_redact_is_linear_on_hostile_long_input():
    import time as _t
    from tools import agent_factory as F
    started = _t.perf_counter()
    out = F.redact("a" * 400_000 + "_KEY=")
    out2 = F.redact("A_" * 200_000)
    assert _t.perf_counter() - started < 2.0
    assert len(out) <= 20_000 and len(out2) <= 20_000


def test_park_is_whitelisted_and_leaves_a_note():
    from tools import agent_factory as F
    plan = [{"id": "A1", "title": "a", "touch_files": ["tools/a.py"], "tests": ["tests/test_a.py"],
             "privacy_safe": True, "backlog_id": "B1"}]
    st = F.initial_state(F.read_plan(plan))
    with _pytest_models.raises(F.InvalidPlan):
        F.park(st, "A1", "any free text", "x")
    F.park(st, "A1", "runner_no_result", "no result 3 times")
    row = st["tasks"]["A1"]
    assert row["status"] == "BLOCKED" and row["blocked_reason"] == "runner_no_result"
    assert "no result 3 times" in F.last_feedback(st, "A1")
    with _pytest_models.raises(F.InvalidPlan):       # only an unsettled task can be parked
        F.park(st, "A1", "no_package", "x")


@pytest.mark.parametrize("model,ok", [
    ("openrouter/vendor/model:free", True), ("openrouter/model:free", True), ("google/gemma", True),
    ("openrouter/vendor/model", False), ("openrouter/model", False), ("openrouter/vendor/model:free2", False),
    ("OpenRouter/vendor/model", False), ("openrouter/vendor/model:free/x", False)])
def test_zero_rouble_guard_openrouter_models_must_be_free(model, ok):
    assert bool(F.MODEL_ID.fullmatch(model)) is ok


def test_paid_openrouter_model_is_refused_by_route():
    t=plan(item())["T1"]
    with pytest.raises(F.InvalidPlan):
        F.route(t,small_model="openrouter/vendor/model",large_model="google/flash")
    assert F.route(t,small_model="openrouter/vendor/model:free",large_model="google/flash")


def test_agent_config_file_is_denied_in_any_case():
    for name in ("AGENTS.md","agents.md","docs/Agents.MD"):
        with pytest.raises(F.InvalidPlan):
            F.safe_path(name)


def test_channels_validate_refuses_a_paid_openrouter_model():
    from tools import factory_channels as C
    base=dict(id="c",group="g",key_env="KEY",tpm=100000,rpd=100,verified=True)
    C.validate([dict(base,model="openrouter/vendor/model:free")])
    C.validate([dict(base,model="google/gemma")])
    with pytest.raises(F.InvalidPlan):
        C.validate([dict(base,model="openrouter/vendor/model")])
