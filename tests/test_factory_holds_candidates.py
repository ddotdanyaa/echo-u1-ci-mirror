"""<id>: the candidates hold kind of tools/factory_holds.py (no tests needed, tools/ paths, a not-code answer, the
backlog priority order of the pick)."""
from tools import factory_holds as H

CAND = H.candidate_question("P1", [("echo_sync/x.py", 4.0, ["id"]), ("tools/y.py", 1.0, ["doc"])])
AMB = "локализация неоднозначна: echo_sync/a.py (1.00: f1); echo_sync/b.py (1.00: g1)"


def test_kind_and_paths_of_a_candidates_hold():
    assert CAND.startswith(H.CANDIDATES) and "(P1)" in CAND
    assert H.kind_of(CAND) == "candidates"
    assert H.candidates(CAND) == (["echo_sync/x.py", "tools/y.py"], [])


def test_prompt_offers_not_code_only_for_candidates():
    text = H.prompt("B1", "make it fast", CAND, ["echo_sync/x.py", "tools/y.py"], [], {})
    assert '"not_code"' in text and "proxy" in text
    assert '"not_code"' not in H.prompt("B1", "make it fast", AMB, ["echo_sync/a.py"], ["tests/t.py"], {})


def test_parse_not_code_only_for_the_candidates_kind():
    files = ["echo_sync/x.py"]
    assert H.parse('{"not_code": "proxy  ops"}', files, kind="candidates") == {"not_code": "proxy ops"}
    assert H.parse('{"not_code": "proxy ops"}', files) is None
    assert H.parse('{"not_code": 5}', files, kind="candidates") is None
    assert H.parse('{"touch_files": ["echo_sync/x.py"], "note": "x"}', files, kind="candidates")["touch_files"] == files


def test_select_orders_candidate_holds_by_priority_then_id():
    holds = {"B1": H.candidate_question("P1", [("echo_sync/x.py", 1, ["doc"])]),
             "B9": H.candidate_question("P0", [("echo_sync/x.py", 1, ["doc"])]),
             "BQX10": H.candidate_question("P0", [("echo_sync/x.py", 1, ["doc"])]),
             "B5": H.candidate_question("", [("echo_sync/x.py", 1, ["doc"])])}
    assert [b for b, _ in H.select(holds, {}, 10 ** 6, limit=4)] == ["B9", "BQX10", "B1", "B5"]


def test_select_keeps_the_mechanical_holds_first():
    holds = {"B9": H.candidate_question("P0", [("echo_sync/x.py", 1, ["doc"])]), "B2": AMB}
    assert [b for b, _ in H.select(holds, {}, 10 ** 6)] == ["B2", "B9"]
