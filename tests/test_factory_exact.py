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


def test_exact_prompt_asks_for_it_and_names_the_banned_words(root):
    system, _ = A.build_prompt(dict(PACKET, rung=0), "free_main")
    assert "EXACT line" in system and "Never write \"ensure\"" in system and "Good:" in system and "Bad:" in system
    red_system, _ = A.build_prompt(dict(PACKET, rung=0, red_given=True), "free_main")
    assert "EXACT line" in red_system                                             # red (guard, rel-*) rows are asked for it too




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
    void = _voices(["not json", GOOD_SMALL])          # a void first voice: one more, not three (W-rig: a vague answer is no longer void)
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


def test_path_main_edits_by_tempo_not_by_a_fixed_floor():
    """W-path C (replaces the fixed 70 % floor of W-split): the main channel takes a short edit only while its unused share
    of the day is not below the share of the quota day that is left."""
    from tools import factory_channels as CH
    main = next(c for c in _pool() if c["id"] == "m1")
    start, end = CH.quota_day(main["model"], 1_800_000_000)

    def ids(at, used_share):
        state = {main["group"]: {"request_times": [at] * int(main["rpd"] * used_share)}}
        return [c["id"] for c in CH.route_order(_pool(), "edit", 1, 3000, state=state, now=at)]
    noon = start + 0.5 * (end - start)
    assert ids(noon, 0.0) == ["s1", "m1"]                 # nothing used: the surplus is spent
    assert ids(noon, 0.4) == ["s1", "m1"]                 # 60 % left, 50 % of the day left: ahead of the tempo, still takes edits
    assert ids(noon, 0.6) == ["s1"]                       # 40 % left < 50 %: behind, Gemma only
    early = start + 0.1 * (end - start)
    assert ids(early, 0.2) == ["s1"] and ids(early, 0.05) == ["s1", "m1"]
    late = start + 0.95 * (end - start)
    assert ids(late, 0.9) == ["s1", "m1"]                 # 10 % left, 5 % of the day left: the leftover is used, not kept
    assert "m1" in [c["id"] for c in CH.route_order(_pool(), "architect", 1, 3000, state={}, now=noon)]
