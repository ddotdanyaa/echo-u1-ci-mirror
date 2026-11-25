"""W-exact: executable contracts, one small voice, the strong free steps first. No network, no model."""
import copy
import json
import pytest
from tools import factory_architect as A

ENGINE = "class Engine:\n    def on_barge_in(self):\n        self.tail = list(self.queue)\n        return 1\n"
FILES = {"echo_sync/engine.py": ENGINE, "tests/test_guard.py": "def test_reply_is_cut():\n    assert False\n"}
VAGUE = "Ensure the logic of on_barge_in drops the queued tail of the reply when the listener starts to speak."
EXACT = "In `on_barge_in` replace `self.tail = list(self.queue)` with `self.tail = []` so the queued tail is dropped."
PACKET = {"bid": "B1", "title": "t", "text": "row", "quotes": [], "evidence": "", "examples": [], "rung": 0,
          "hints": [ENGINE]}


def contract(instruction, **part):
    return {"row": "B1", "decision": "fix", "why": "the tail of a cut reply is still spoken",
            "test": {"use": "tests/test_guard.py::test_reply_is_cut"},
            "parts": [dict({"file": "echo_sync/engine.py", "symbols": ["Engine.on_barge_in"], "instruction": instruction,
                            "keep": "the signature"}, **part)]}


@pytest.fixture
def root(tmp_path):
    for name, text in FILES.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text, encoding="utf-8")
    return tmp_path


def test_exact_validate_refuses_a_vague_instruction_and_takes_a_quoted_line(root):
    assert any(e.startswith(A.VAGUE_FAULT) for e in A.validate(contract(VAGUE), root, bid="B1", exact=True))
    assert A.validate(contract(VAGUE), root, bid="B1") == []                      # only new contracts are asked for it
    assert A.validate(contract(EXACT), root, bid="B1", exact=True) == []
    # a quote of another function (not in the named body) and a quote without its replacement are vague too
    assert A.validate(contract("In `on_barge_in` replace `return something_else(1)` with `return 2` now."), root, bid="B1", exact=True)
    assert A.validate(contract("In `on_barge_in` look at `self.tail = list(self.queue)` and think about it."), root, bid="B1", exact=True)
    # ready code, a removal and rig / hypo contracts are not vague
    assert A.validate(contract(VAGUE, code="def on_barge_in(self):\n    self.tail = []\n    return 1\n"), root, bid="B1", exact=True) == []
    assert A.validate(contract("Remove the line `self.tail = list(self.queue)` from on_barge_in entirely."), root, bid="B1", exact=True) == []


def test_exact_prompt_asks_for_it_and_names_the_banned_words(root):
    system, _ = A.build_prompt(dict(PACKET, rung=0), "free_main")
    assert "EXACT line" in system and "Never write \"ensure\"" in system and "Good:" in system and "Bad:" in system
    red_system, _ = A.build_prompt(dict(PACKET, rung=0, red_given=True), "free_main")
    assert "EXACT line" in red_system                                             # red (guard, rel-*) rows are asked for it too


def test_exact_one_reask_of_the_same_step_with_the_flaw_text(root):
    answers, seen = [json.dumps(contract(VAGUE)), json.dumps(contract(EXACT))], []

    def ask(system, user):
        seen.append(user)
        return answers[len(seen) - 1]
    got = A.contract_for(PACKET, rung=0, root=root, asks={"free_main": ask})
    assert len(seen) == 2 and "vague: " in seen[1] and got["contract"]["parts"][0]["instruction"] == EXACT
    # the second vague answer is not asked a third time
    seen.clear(); answers[:] = [json.dumps(contract(VAGUE))] * 3
    with pytest.raises(A.Exhausted):
        A.contract_for(PACKET, rung=0, root=root, asks={"free_main": ask})
    assert len(seen) == 2


GOOD_SMALL = json.dumps(contract(EXACT))


def _voices(answers):
    calls = []

    def ask(system, user, temperature=None, channel=None):
        calls.append(temperature)
        return answers[(len(calls) - 1) % len(answers)]
    ask.channels = None
    ask.calls = calls
    return ask


def test_exact_small_tier_is_one_generation_and_a_second_only_when_the_first_is_void(root):
    assert (A.SMALL_K, A.SMALL_K_MAX) == (1, 2)
    one = _voices([GOOD_SMALL, GOOD_SMALL])
    got = A.contract_for(PACKET, rung=0, root=root, asks={"free_small": one})
    assert len(one.calls) == 1 and got["engine"] == "free_small"
    void = _voices([json.dumps(contract(VAGUE)), GOOD_SMALL])          # a vague first voice is void: one more, not three
    A.contract_for(PACKET, rung=0, root=root, asks={"free_small": void})
    assert len(void.calls) == 2


def test_exact_free_strong_steps_are_asked_before_the_small_one_in_every_order():
    rungs = ("free", "free_main", "free_small", "paid", "agent")
    for kind in (dict(), dict(red=True), dict(dry=True), dict(base_debt=True)):
        for rung in (0, 1, 2):
            order = A.ladder(rung, rungs=rungs, **kind)
            assert order.index("free") < order.index("free_main") < order.index("free_small")


def _pool():
    return [dict(id="s1", group="gs", model="google/gemma-x", key_env="K", tpm=100000, rpd=100, verified=True, tier="small"),
            dict(id="m1", group="gm", model="google/flash-lite", key_env="K", tpm=100000, rpd=100, verified=True, tier="main")]


def test_exact_a_red_row_is_asked_for_it_too(root):
    answers, seen = [json.dumps(contract(VAGUE)), json.dumps(contract(EXACT))], []

    def ask(system, user):
        seen.append(user)
        return answers[len(seen) - 1]
    got = A.contract_for(dict(PACKET, red_given=True), rung=0, root=root, asks={"agent": ask})
    assert len(seen) == 2 and "vague: " in seen[1] and got["contract"]["parts"][0]["instruction"] == EXACT


def test_split_gemma_edits_first_and_main_only_while_most_of_its_day_is_left():
    import time
    from tools import factory_channels as CH
    now = time.time()
    fresh = [c["id"] for c in CH.route_order(_pool(), "edit", 1, 3000, state={}, now=now)]
    assert fresh == ["s1", "m1"]
    main = next(c for c in _pool() if c["id"] == "m1")
    used = {main["group"]: {"request_times": [now] * (main["rpd"] * 4 // 10)}}
    assert [c["id"] for c in CH.route_order(_pool(), "edit", 1, 3000, state=used, now=now)] == ["s1"]
    assert "m1" in [c["id"] for c in CH.route_order(_pool(), "architect", 1, 3000, state=used, now=now)]
