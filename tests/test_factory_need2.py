"""A model that asks to see the code first is answered, not thrown away."""
import json

import pytest

from tools import factory_architect as A


def test_a_decision_need_is_a_source_request():
    got = A.parse('```json\n{"row": "B1", "decision": "need", "need": [{"file": "echo_sync/a.py", "symbols": ["f"], "anchor": "exact line"}]}\n```')
    assert got == {"need": [{"file": "echo_sync/a.py", "symbols": ["f"]}]}


def test_the_list_of_the_second_object_or_of_the_prose_is_used():
    two = json.dumps({"decision": "need", "why": "x"}) + "\n" + json.dumps({"need": [{"file": "echo_sync/b.py", "symbols": ["g"]}]})
    assert A.parse(two)["need"][0]["file"] == "echo_sync/b.py"
    prose = json.dumps({"decision": "need", "why": "see 'extract' in echo_sync/c.py", "more": ""})
    assert A.parse(prose) == {"need": [{"file": "echo_sync/c.py", "symbols": ["extract"]}]}
    with pytest.raises(A.ContractFault):
        A.parse(json.dumps({"decision": "need", "why": "more code"}))


def test_a_fix_is_not_taken_for_a_request():
    fix = {"decision": "fix", "why": "w", "parts": [{"file": "echo_sync/a.py", "symbols": ["f"], "instruction": "i" * 50, "keep": ""}]}
    assert A.parse(json.dumps(fix))["decision"] == "fix"
    assert A.need_rounds(0, "free_small") == 3 and A.need_rounds(0, "agent") == 2
