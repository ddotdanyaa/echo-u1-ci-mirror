"""fac-87 (<id>): the author knows the kinds of a change in tests and what its code is judged on; a program refuses a ready
contract (its code applied by the executor's own applier, judged by G.contract_rules) before a card is cut. No network."""
import json

import pytest

from tools import agent_factory_runner as R
from tools import factory_architect as A

ENGINE = "class Engine:\n    def on_barge_in(self):\n        return 1\n\n    def other(self):\n        return 5\n"
TEST = "def test_reply_is_cut():\n    assert A_VALUE == 1\n"
FILES = {"echo_sync/engine.py": ENGINE, "echo_sync/table.md": "| a | b |\n",
         "tests/test_guard.py": "A_VALUE = 2\n\n\ndef test_reply_is_cut():\n    assert A_VALUE == 1\n"}
PACKET = {"bid": "B1", "title": "t", "text": "row", "quotes": [], "evidence": "", "hints": "", "examples": [], "rung": 0}
RED = dict(PACKET, red_given=True)
INSTRUCTION = "Mend the stand of the red test so that the scene can run; every check of the file stays as it is."
HELPER = "def helper():" + chr(10) + "    return 1" + chr(10)
SENTENCE = "reviewers judge your code after the tests pass"


@pytest.fixture
def root(tmp_path):
    for name, text in FILES.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="")
    return tmp_path


def rig(file_text, **extra):
    part = {"file": "tests/test_guard.py", "file_text": file_text, "code": HELPER, "instruction": INSTRUCTION}
    return dict({"row": "B1", "decision": "fix", "rig": True, "why": "the stand is broken",
                 "test": {"use": "tests/test_guard.py::test_reply_is_cut"}, "parts": [part]}, **extra)


CLEAN = "A_VALUE = 1\n\n\ndef helper():\n    return 1\n\n\ndef test_reply_is_cut():\n    assert A_VALUE == 1\n"
WEAK = "A_VALUE = 1\n\n\ndef test_reply_is_cut():\n    assert A_VALUE == 2\n"
CODE = {"row": "B1", "decision": "fix", "why": "the tail of a cut reply is still spoken",
        "test": {"use": "tests/test_guard.py::test_reply_is_cut"},
        "parts": [{"file": "echo_sync/engine.py", "symbols": ["Engine.on_barge_in"], "code": "def on_barge_in(self):\n    return 2\n",
                   "instruction": "Drop the queued tail of the reply when the listener starts to speak, in the one method named here."}]}


def asker(*answers):
    """An ask that returns the answers in turn and keeps the user texts it was given."""
    seen = []

    def ask(system, user):
        seen.append(user)
        return json.dumps(answers[min(len(seen), len(answers)) - 1])
    ask.seen = seen
    return ask


# ---- 1-3. the prompt
def test_the_agent_on_a_red_row_gets_repair_restate_and_what_its_code_is_judged_on():
    system = A.build_prompt(RED, "agent")[0]
    assert "character for character" in system and '"restate": true' in system and '"rule"' in system
    assert SENTENCE in system and "alone may answer cannot_reproduce" in system
    assert "do not write a fix with a test part" not in system and "RESTATE" in system and "REPAIR" in system
    # cannot_reproduce is named only for a test out of date with no rule to quote
    stand = system[system.index("(a)"):]
    assert "cannot_reproduce" not in stand[:stand.index("(c)")] and "no rule to quote" in stand.split("(c)")[1]
    assert system.index("(a)") < system.index("(b)") < system.index("(c)")


def test_a_free_step_on_a_red_row_gets_repair_and_the_product_rule_only():
    system = A.build_prompt(RED, "free")[0]
    assert "character for character" in system and "never the test" in system
    assert "restate" not in system and "RESTATE" not in system and SENTENCE not in system
    assert "cannot_reproduce" not in system[system.index("REPAIR"):].split(chr(10))[0]


def test_a_row_that_is_not_red_has_none_of_it():
    for engine in ("agent", "paid", "free"):
        system = A.build_prompt(PACKET, engine)[0]
        assert "character for character" not in system and '"restate": true' not in system
    assert SENTENCE in A.build_prompt(PACKET, "paid")[0] and SENTENCE not in A.build_prompt(PACKET, "free")[0]


# ---- 4-6. the check at contract time
def test_a_stand_that_changes_an_assert_is_asked_again_once_with_the_guidance_then_it_is_the_steps_fault(root):
    ask = asker(rig(WEAK), rig(CLEAN))
    got = A.contract_for(RED, rung=0, root=root, asks={"agent": ask})
    assert len(ask.seen) == 2 and "rig_weakens:" in ask.seen[1] and "Fix these problems" in ask.seen[1]
    assert "keeps every check" in ask.seen[1] and "restate" in ask.seen[1]
    assert got["engine"] == "agent" and got["contract"]["parts"][0]["file_text"] == CLEAN
    ask = asker(rig(WEAK))
    with pytest.raises(A.Exhausted) as spent:
        A.contract_for(RED, rung=0, root=root, asks={"agent": ask})
    assert len(ask.seen) == 2 and any("rig_weakens:" in f["fault"] for f in spent.value.faults)


def test_an_edit_outside_the_named_function_goes_through_the_same_re_ask(root):
    wide = rig(ENGINE.replace("return 5", "return 6"), parts=None)
    wide["parts"] = [{"file": "echo_sync/engine.py", "symbols": ["Engine.on_barge_in"], "instruction": INSTRUCTION,
                      "code": HELPER, "file_text": ENGINE.replace("return 5", "return 6")}]
    ask = asker(wide, CODE)
    got = A.contract_for(PACKET, rung=0, root=root, asks={"agent": ask})
    assert len(ask.seen) == 2 and "off_contract:" in ask.seen[1] and "Engine.other" in ask.seen[1]
    assert "keeps every check" not in ask.seen[1] and got["contract"]["parts"][0]["code"]


def test_a_clean_ready_contract_costs_no_extra_ask_and_a_part_without_code_is_not_checked(root):
    ask = asker(CODE)
    assert A.contract_for(PACKET, rung=0, root=root, asks={"agent": ask})["engine"] == "agent" and len(ask.seen) == 1
    ask = asker(rig(CLEAN))
    assert A.contract_for(RED, rung=0, root=root, asks={"agent": ask})["engine"] == "agent" and len(ask.seen) == 1
    mixed = json.loads(json.dumps(CODE))
    mixed["parts"].append({"file": "echo_sync/table.md", "symbols": [], "anchor": "| a | b |", "instruction": INSTRUCTION})
    calls = []
    real = A.applied_texts
    A.applied_texts = lambda *a, **k: calls.append(1) or real(*a, **k)
    try:
        ask = asker(mixed)
        A.contract_for(PACKET, rung=0, root=root, asks={"agent": ask})
    finally:
        A.applied_texts = real
    assert len(ask.seen) == 2 and calls == []      # the second ask is the old one for the code of every part


# ---- 7. the applier is the executor's
def test_a_method_replaced_by_name_keeps_the_other_text_byte_for_byte(root, tmp_path):
    texts, faults = A.applied_texts(CODE, root)
    assert faults == []
    blocks = [("echo_sync/engine.py", R._FuncTarget(sym), text)
              for sym, text in A.K.split_part_code(CODE["parts"][0]["code"], ["Engine.on_barge_in"])]
    folder = tmp_path / "executor"
    (folder / "echo_sync").mkdir(parents=True)
    (folder / "echo_sync/engine.py").write_bytes(ENGINE.encode("utf-8"))
    applied, failed = R.apply_edit_blocks(folder, blocks, None, {"echo_sync/engine.py": ["Engine.on_barge_in"]})
    assert not failed
    expect = (folder / "echo_sync/engine.py").read_bytes().decode("utf-8")
    assert texts["echo_sync/engine.py"] == expect and "return 5" in expect and "return 2" in expect
    assert (root / "echo_sync/engine.py").read_text(encoding="utf-8") == ENGINE       # the snapshot itself is never written


def test_code_that_does_not_apply_is_a_fault_of_the_part(root):
    bad = json.loads(json.dumps(CODE))
    bad["parts"][0]["code"] = "def nothing(self):\n    return 2\n"
    texts, faults = A.applied_texts(bad, root)
    assert faults and faults[0].startswith("part echo_sync/engine.py: the code does not apply:")
