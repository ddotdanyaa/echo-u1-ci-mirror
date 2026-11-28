"""<id> / variant C: the contract gives the SEARCH lines verbatim from the base file, the free editors write only the REPLACE."""
import json

import pytest

from tools import factory_architect as A

ENGINE = "class Engine:\n    def on_barge_in(self):\n        tail = self.queue\n        return 1\n"


@pytest.fixture
def root(tmp_path):
    files = {"echo_sync/engine.py": ENGINE, "tests/test_guard.py": "def test_reply_is_cut():\n    assert False\n"}
    for name, text in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.replace("\n", "\r\n").encode("utf-8") if name.endswith("engine.py") else text.encode("utf-8"))
    return tmp_path


def contract(search=None, **extra):
    part = {"file": "echo_sync/engine.py", "symbols": ["Engine.on_barge_in"],
            "instruction": "Clear the queued tail of the reply when the listener starts to speak, then return 1."}
    if search is not None:
        part["search"] = search
    part.update(extra)
    return {"row": "B1", "decision": "fix", "why": "the tail is spoken",
            "test": {"use": "tests/test_guard.py::test_reply_is_cut"}, "parts": [part]}


def card_part(c):
    code = [t for t in A.to_tasks(c, bid="B1", base_id="bl_B1", gen=1, priority=1, title="t") if t["kind"] == "code"][0]
    return json.loads(code["contract"])["parts"][0]


def test_an_exact_search_is_kept_and_reaches_the_editor_card_verbatim(root):
    c = contract("        tail = self.queue\n")
    assert A.validate(c, root, bid="B1") == []
    assert c["mode"] == A.SEARCH_LITERAL
    part = card_part(c)
    assert "<<<<<<< SEARCH\n        tail = self.queue\n=======" in part["instruction"]
    assert part["instruction"].startswith("Clear the queued tail")


def test_a_search_with_wrong_indent_is_mended_to_the_file_lines_and_a_missing_one_is_dropped(root):
    c = contract("tail = self.queue")
    assert A.validate(c, root, bid="B1") == []
    assert c["parts"][0]["search"] == "        tail = self.queue"
    gone = contract("tail = self.other\n")
    assert A.validate(gone, root, bid="B1") == []          # a wrong literal never costs the contract
    assert "search" not in gone["parts"][0] and "mode" not in gone
    assert "<<<<<<< SEARCH" not in card_part(gone)["instruction"]


def test_a_search_twice_in_the_file_or_beside_ready_code_is_dropped(root):
    (root / "echo_sync/engine.py").write_text(ENGINE + "    def again(self):\n        tail = self.queue\n", encoding="utf-8")
    twice = contract("        tail = self.queue")
    assert A.validate(twice, root, bid="B1") == [] and "search" not in twice["parts"][0]
    coded = contract("        tail = self.queue", code="def on_barge_in(self):\n    return 2\n")
    A.validate(coded, root, bid="B1")
    assert "search" not in coded["parts"][0]


def test_the_rule_is_asked_of_free_slicers_on_light_rows_only():
    light = {"bid": "B1", "title": "t", "text": "row", "rung": 0}
    assert A.SEARCH_LITERAL_RULE in A.build_prompt(light, "free_small")[0]
    assert A.SEARCH_LITERAL_RULE not in A.build_prompt(light, "free")[0]       # fac-101: free / free_main give ready code, the literal SEARCH rule says "no code"
    assert A.SEARCH_LITERAL_RULE not in A.build_prompt(dict(light, rung=2), "paid")[0]
    assert A.SEARCH_LITERAL_RULE not in A.build_prompt(dict(light, edit_dry=True), "free_small")[0]


def test_first_try_of_search_literal_cards_is_counted_on_their_own(tmp_path):
    lit = json.dumps({"mode": A.SEARCH_LITERAL, "parts": []})
    plan = {"tasks": [{"id": "bl_A_r1", "contract": lit}, {"id": "bl_B_r1", "contract": lit},
                      {"id": "bl_C_r1", "contract": "{}"}]}
    (tmp_path / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    rows = [dict(span="run", kind="code", task_id="bl_A_r1", status="REVIEW", ts="2026-11-26T10:00:00+03:00"),
            dict(span="run", kind="code", task_id="bl_B_r1", status="FAILED", reason="gate: red",
                 ts="2026-11-26T10:01:00+03:00"),
            dict(span="run", kind="code", task_id="bl_C_r1", status="REVIEW", ts="2026-11-26T10:02:00+03:00")]
    (tmp_path / "telemetry.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    assert A.search_literal_ids(tmp_path) == {"bl_A_r1", "bl_B_r1"}
    assert A.search_literal_first_try(tmp_path, now="2026-11-26T11:00:00+03:00") == {"pct": 50.0, "n": 2, "green": 1}
