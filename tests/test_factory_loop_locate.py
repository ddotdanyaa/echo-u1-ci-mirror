"""The loop hands the triage a localization ``ask`` built on the free-model head call (same channel choice, ledger and
redaction); a triage run with it reaches the localization of a row that named no file."""
from tests.test_factory_loop import Env
from tests.test_factory_loop_candidates import _backlog, _commit
from tools import agent_factory_import as I


def test_triage_gets_an_ask_that_goes_through_the_light_call(tmp_path, monkeypatch):
    env = Env(tmp_path, monkeypatch, tasks=[])
    _backlog(env)
    seen = []

    def triage(ask=None, **kw):
        seen.append(ask)
        return {"tasks": [], "holds": [], "stale": [], "skipped": []}
    loop = env.loop(triage_fn=triage)
    calls = []

    def light(text, **kw):
        calls.append((text, kw["section"], kw["quotas"]))
        return "ok", "google/x", "answer", 3
    monkeypatch.setattr(loop, "_light_ask", light)
    loop.step()
    assert seen and callable(seen[-1])
    assert seen[-1]("find it") == "answer"
    assert calls[0][1] == "loop-locate" and calls[0][0] == "find it"
    monkeypatch.setattr(loop, "_light_ask", lambda text, **kw: ("no_channel", None, "", 1))
    assert seen[-1]("again") == ""
    loop.LOCATE_CALLS = 1
    assert seen[-1]("third") == ""          # the pass budget is spent


def test_a_loop_triage_with_the_ask_reaches_the_localization(tmp_path, monkeypatch):
    env = Env(tmp_path, monkeypatch, tasks=[])
    _backlog(env)
    _commit(env, "echo_sync/x.py", "# B9: the slow path\ndef slow():\n    return 1\n")
    reached = []

    def fake_localized(root, bid, text, ask, events):
        reached.append((bid, ask("q")))
        return [], ""
    monkeypatch.setattr(I, "_localized_scope", fake_localized)
    loop = env.loop()           # the real triage
    monkeypatch.setattr(loop, "_light_ask", lambda text, **kw: ("ok", "google/x", "reply", 3))
    loop.step()
    assert reached and reached[0][1] == "reply"
