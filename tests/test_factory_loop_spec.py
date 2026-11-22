"""<id> wiring: the spec pass of the loop (one free model call per unit_test task before RUN). _light_post is faked."""
import json

from tests.test_factory_loop import Env, task_row
from tools import factory_loop as L

CODE = "def add(a, b):\n    return a - b\n"
GOOD = {"testable": True, "why": "bug", "function": "add", "call": "add(1, 2)", "now": "-1",
        "expected": "3", "assert": "assert add(1, 2) == 3"}
CHANNEL = {"id": "g1", "model": "google/gemini-x", "group": "g", "key_env": "FAKE_KEY_ENV",
           "tpm": 100000, "rpm": 100, "rpd": 1000}


def make(tmp_path, monkeypatch, **kw):
    row = task_row(1, kind="unit_test", touch_files=["tests/test_x1.py"], read_files=["tools/x1.py"], goal="Add must add two numbers properly.", **kw)
    env = Env(tmp_path, monkeypatch, tasks=[row])
    (tmp_path / "channels.json").write_text(json.dumps({"channels": [CHANNEL]}), encoding="utf-8")
    env.runner_says({"status": "NO_RESULT"})
    return env


def fake_post(calls, answer, status=200):
    def post(url, key, body, timeout):
        calls.append(body)
        data = {"choices": [{"message": {"content": answer}}], "usage": {"total_tokens": 77}}
        return status, json.dumps(data).encode("utf-8")
    return post


def run_step(env, monkeypatch, calls, answer, status=200, code=CODE):
    monkeypatch.setattr(L, "_light_post", fake_post(calls, answer, status))
    (env.repo / "tools" / "x1.py").write_text(code, encoding="utf-8")
    L.git_run(env.repo, "add", "-A")
    L.git_run(env.repo, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", "code")
    loop = env.loop(extra={"extra_env": {"FAKE_KEY_ENV": "k"}})
    loop.step()
    return loop


def plan_goal(env):
    return json.loads((env.state_dir / "plan.json").read_text(encoding="utf-8"))["tasks"][0].get("goal", "")


def answers(env):
    return list((env.state_dir / "answers").rglob("*.json"))


def test_testable_spec_writes_one_answer_with_the_spec_goal(tmp_path, monkeypatch):
    env, calls = make(tmp_path, monkeypatch), []
    run_step(env, monkeypatch, calls, json.dumps(GOOD))
    assert len(calls) == 1
    files = answers(env)
    assert len(files) == 1
    payload = json.loads(files[0].read_text(encoding="utf-8"))
    assert payload["task_id"] == "T1" and "assert add(1, 2) == 3" in payload["goal"]
    assert "factory-backlog-id: B1" in payload["goal"] and "Row: Add must add" in payload["goal"]
    assert any(e["span"] == "spec" and e["status"] == "ok" and e["task_id"] == "T1" for e in env.events())


def test_not_testable_holds_with_reason_and_does_not_run(tmp_path, monkeypatch):
    env, calls = make(tmp_path, monkeypatch), []
    loop = run_step(env, monkeypatch, calls, json.dumps({"testable": False, "why": "a phone check"}))
    assert not answers(env)
    assert env.runs() == 0
    assert "spec: not a testable code defect: a phone check" in loop.ls()["holds"]["B1"]
    assert loop.ls()["specs"]["T1"] == "not_testable"
    assert env.state()["tasks"]["T1"]["status"] == "BLOCKED"


def test_bad_json_writes_nothing_and_run_goes_on(tmp_path, monkeypatch):
    env, calls = make(tmp_path, monkeypatch), []
    loop = run_step(env, monkeypatch, calls, "no json here")
    assert len(calls) == 1 and not answers(env)
    assert loop.ls()["specs"]["T1"] == "failed"
    assert env.runs() == 1


def test_the_pass_runs_once_per_task(tmp_path, monkeypatch):
    env, calls = make(tmp_path, monkeypatch), []
    loop = run_step(env, monkeypatch, calls, "garbage")
    loop.step()
    assert len(calls) == 1


def test_private_and_only_opus_tasks_are_never_sent(tmp_path, monkeypatch):
    for n, extra in enumerate(({"privacy_safe": False}, {"only_opus": True})):
        env, calls = make(_sub(tmp_path, n), monkeypatch, **extra), []
        run_step(env, monkeypatch, calls, json.dumps(GOOD))
        assert calls == [] and not answers(env)


def _sub(path, n):
    sub = path / ("case%d" % n)
    sub.mkdir()
    return sub


def test_a_large_file_is_shown_as_a_view_and_the_spec_still_finds_the_function(tmp_path, monkeypatch):
    # live 20.11: 10 of 16 test tasks read a file above 24k chars; skipping them left the bulk without a spec
    filler = "".join("def helper_%03d(x):\n    return x + %d\n\n\n" % (i, i) for i in range(900))
    env, calls = make(tmp_path, monkeypatch), []
    loop = run_step(env, monkeypatch, calls, json.dumps(GOOD), code=filler + CODE)
    shown = calls[0]["messages"][0]["content"]
    assert "OUTLINE" in shown and "def add(a, b)" in shown
    assert len(shown) < len(filler) // 2
    assert loop.ls()["specs"]["T1"] == "ok"


def test_an_http_error_leaves_the_spec_for_the_next_run_and_cools_the_channel(tmp_path, monkeypatch):
    env, calls = make(tmp_path, monkeypatch), []
    loop = run_step(env, monkeypatch, calls, "", status=429)
    ls = loop.ls()
    assert ls["specs"]["T1"] == "later" and env.runs() == 1          # the RUN went on with the old goal
    assert ls["spec_quotas"]                                          # the 429 is booked for the next choice
    monkeypatch.setattr(L, "_light_post", fake_post(calls, json.dumps(GOOD)))
    tasks, state = loop.load()
    loop._spec_pass("T1", tasks, state, loop.ls())
    assert len(calls) == 1                                            # the only channel is cooling: no call
    start = loop.clock()
    loop.clock = lambda: start + 120                                  # the cool (60 s) is over: it asks again
    tasks, state = loop.load()
    loop._spec_pass("T1", tasks, state, loop.ls())
    assert len(calls) == 2 and loop.ls()["specs"]["T1"] == "ok"


def test_a_task_parked_as_not_testable_is_never_requeued(tmp_path, monkeypatch):
    # was: factory_requeue.pick(...) == []; the requeue is gone, the slicer queue replaces it: a parked row is no
    # stuck row, so the slicer is never asked about it
    from tools import agent_factory as F
    env, calls = make(tmp_path, monkeypatch), []
    sliced = []
    monkeypatch.setattr(L, "_light_post", fake_post(calls, json.dumps({"testable": False, "why": "a phone check"})))
    (env.repo / "tools" / "x1.py").write_text(CODE, encoding="utf-8")
    L.git_run(env.repo, "add", "-A")
    L.git_run(env.repo, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", "code")
    loop = env.loop(extra={"extra_env": {"FAKE_KEY_ENV": "k"}, "slice_fn": lambda *a, **k: sliced.append(a) or None})
    loop.step()
    loop.step()
    state = env.state()
    assert state["tasks"]["T1"]["blocked_reason"] == "spec_not_testable"
    tasks = F.read_plan(json.loads((env.state_dir / "plan.json").read_text(encoding="utf-8")))
    assert F.stuck_rows(state, tasks) == {} and sliced == []

