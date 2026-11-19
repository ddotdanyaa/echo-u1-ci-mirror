"""<id>/<id> wiring: an idle loop lets a free head model answer mechanical holds; private rows are never sent;
a 20 minute gate; a fault goes to infra. The model call and the backlog text are faked."""
import json

from tests.test_factory_loop import Env, L, task_row

AMB = "локализация неоднозначна: echo_sync/a.py (1.00: f1); echo_sync/b.py (1.00: g1)"
PY = '{"touch_files": ["echo_sync/b.py"], "note": "Change g1 in b"}'


def setup(tmp_path, monkeypatch, answer=PY, status="ok", private=False, bids=("B9",)):
    tmp_path.mkdir(parents=True, exist_ok=True)
    env = Env(tmp_path, monkeypatch, tasks=[task_row(1)])
    mirror = tmp_path / "mirror"
    (mirror / "tests" / "verify" / "kind_a").mkdir(parents=True)
    (mirror / "echo_sync").mkdir()
    for b in bids:
        (mirror / "tests" / "verify" / "kind_a" / ("test_v_%s.py" % b.lower())).write_text("", encoding="utf-8")
    (mirror / "echo_sync" / "b.py").write_text("def g1():\n    pass\n", encoding="utf-8")
    loop = env.loop()
    loop.mirror = mirror
    ls = loop.ls()
    ls["holds"] = {b: AMB for b in bids}
    loop.save_ls(ls)
    calls = []

    def ask(text, **kw):
        calls.append((text, kw))
        return status, "google/x", answer if status == "ok" else "", 7
    monkeypatch.setattr(loop, "_light_ask", ask)
    monkeypatch.setattr(loop, "_backlog_text", lambda bid: ("", True, False) if private else ("speed it up", False, False))
    loop._last_out = L.Outcome(action="HOLD")
    return env, loop, calls


def answers(env):
    box = env.state_dir / "answers"
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(box.glob("*.json"))] if box.exists() else []


def test_idle_loop_answers_an_ambiguous_hold(tmp_path, monkeypatch):
    env, loop, calls = setup(tmp_path, monkeypatch)
    loop._head_holds()
    assert answers(env) == [{"backlog_id": "B9", "touch_files": ["echo_sync/b.py"],
                             "tests": ["tests/verify/kind_a/test_v_b9.py"], "note": "Change g1 in b"}]
    assert calls[0][1]["section"] == "loop-holds" and calls[0][1]["attempt"] == 2
    assert loop.ls()["head_holds"]["B9"]["status"] == "answered"
    ev = [e for e in env.events() if e.get("span") == "head"][-1]
    assert ev["backlog_id"] == "B9" and ev["status"] == "answered" and ev["tokens"] == 7
    assert AMB not in json.dumps(ev, ensure_ascii=False)


def test_not_idle_does_nothing(tmp_path, monkeypatch):
    env, loop, calls = setup(tmp_path, monkeypatch)
    loop._last_out = L.Outcome(action="RUN")
    loop._head_holds()
    assert not calls and not answers(env)


def test_private_row_is_never_sent(tmp_path, monkeypatch):
    env, loop, calls = setup(tmp_path, monkeypatch, private=True)
    loop._head_holds()
    assert not calls and not answers(env)
    assert loop.ls()["head_holds"]["B9"]["status"] == "private"


def test_skip_is_recorded_and_no_test_is_not_asked(tmp_path, monkeypatch):
    env, loop, calls = setup(tmp_path, monkeypatch, answer='{"skip": "none fits"}')
    loop._head_holds()
    assert not answers(env) and loop.ls()["head_holds"]["B9"]["status"] == "skip"
    env2, loop2, calls2 = setup(tmp_path / "n", monkeypatch, bids=())
    ls = loop2.ls()
    ls["holds"] = {"B8": AMB}
    loop2.save_ls(ls)
    loop2._head_holds()
    assert not calls2 and loop2.ls()["head_holds"]["B8"]["status"] == "no_test"


def test_unreached_head_is_later_and_garbage_is_invalid(tmp_path, monkeypatch):
    env, loop, calls = setup(tmp_path, monkeypatch, status="no_channel")
    loop._head_holds()
    assert loop.ls()["head_holds"]["B9"]["status"] == "later"
    env2, loop2, _ = setup(tmp_path / "g", monkeypatch, answer="hmm")
    loop2._head_holds()
    assert loop2.ls()["head_holds"]["B9"]["status"] == "invalid"


def test_the_20_minute_gate(tmp_path, monkeypatch):
    env, loop, calls = setup(tmp_path, monkeypatch, status="no_channel", bids=("B9", "B7"))
    loop._head_holds()
    n = len(calls)
    assert n == 2
    loop._head_holds()
    assert len(calls) == n
    env.clock.sleep(L.Loop.HOLDS_EVERY_S + 1)
    loop._head_holds()
    assert len(calls) == 2 * n


def test_a_fault_goes_to_infra(tmp_path, monkeypatch):
    env, loop, calls = setup(tmp_path, monkeypatch)

    def boom(bid):
        raise OSError("disk")
    monkeypatch.setattr(loop, "_backlog_text", boom)
    loop._head_holds()
    assert any(e.get("span") == "infra" and "head_holds" in e.get("reason", "") for e in env.events())
