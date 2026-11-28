"""accept_unit_test: the new test must carry the backlog marker as its first line."""
from tools import factory_gate as G

RED = G.GateResult(1, 1, 0, 1, 0, 0, True)


def test_marker_not_asked_by_old_callers():
    assert G.accept_unit_test(RED) == (True, "ok")


def test_missing_marker_is_rejected_with_a_remark():
    ok, why = G.accept_unit_test(RED, "def test_x():\n    assert 0\n", "EQX70")
    assert not ok and "# factory-backlog-id: EQX70" in why


def test_marker_present_passes():
    assert G.accept_unit_test(RED, "# factory-backlog-id: EQX70\ndef test_x():\n    assert 0\n", "EQX70") == (True, "ok")


def test_marker_after_blank_lines_and_a_shebang():
    text = "\n\n#!/usr/bin/env python\n\n# factory-backlog-id: EQX70\ndef test_x():\n    assert 0\n"
    assert G.accept_unit_test(RED, text, "EQX70") == (True, "ok")


def test_marker_for_another_row_or_not_first_is_rejected():
    assert not G.accept_unit_test(RED, "# factory-backlog-id: EQX71\ndef test_x():\n    assert 0\n", "EQX70")[0]
    assert not G.accept_unit_test(RED, "import os\n# factory-backlog-id: EQX70\n", "EQX70")[0]


def test_text_without_backlog_id_is_an_error_not_a_pass():
    ok, why = G.accept_unit_test(RED, "# factory-backlog-id: EQX70\ndef test_x():\n    assert 0\n")
    assert not ok and "backlog_id" in why
