"""tools/factory_holds.py: the pure helpers of the head answering mechanical holds (<id>/<id>)."""
import json

from tools import factory_holds as H

AMB = "локализация неоднозначна: echo_sync/a.py (1.00: f1, f2); echo_sync/b.py (1.00: g1)"
SCOPE = ("уточнить область: тест(ы) tests/x.py, tests/y.py импортируют 2 модулей "
         "(echo_sync/m1.py, echo_sync/m2.py); какие менять?")


def test_kind_of():
    assert H.kind_of(AMB) == "ambiguous"
    assert H.kind_of(SCOPE) == "scope"
    assert H.kind_of("тест tests/x.py зелёный на HEAD") is None
    assert H.kind_of("дать техническую формулировку") is None
    assert H.kind_of(None) is None


def test_candidates_in_order_without_duplicates():
    assert H.candidates(AMB) == (["echo_sync/a.py", "echo_sync/b.py"], [])
    assert H.candidates(SCOPE) == (["echo_sync/m1.py", "echo_sync/m2.py"], ["tests/x.py", "tests/y.py"])
    assert H.candidates("echo_sync/a.py echo_sync/a.py tests/t.py tests/t.py") == (["echo_sync/a.py"], ["tests/t.py"])


def test_row_test_needs_exactly_one(tmp_path):
    d = tmp_path / "tests" / "verify" / "kind_a"
    d.mkdir(parents=True)
    (d / "test_v_fQX09_x_1.py").write_text("", encoding="utf-8")
    assert H.row_test("FQX09-X.1", tmp_path) == "tests/verify/kind_a/test_v_fQX09_x_1.py"
    assert H.row_test("FQX10", tmp_path) is None
    d2 = tmp_path / "tests" / "verify" / "kind_b"
    d2.mkdir()
    (d2 / "test_v_fQX09_x_1.py").write_text("", encoding="utf-8")
    assert H.row_test("FQX09-X.1", tmp_path) is None
    assert H.row_test("FQX09", tmp_path / "nowhere") is None


def test_prompt_holds_rules_goal_question_outlines():
    text = H.prompt("B1", "make it fast", AMB, ["echo_sync/a.py"], ["tests/t.py"], {"echo_sync/a.py": "L1-2 def f"})
    for part in ("ONE JSON object", "touch_files", "skip", "make it fast", AMB, "L1-2 def f", "echo_sync/a.py"):
        assert part in text


FILES = ["echo_sync/a.py", "echo_sync/b.py", "echo_sync/c.py", "echo_sync/d.py"]


def test_parse_good_takes_first_object_and_cleans_note():
    ans = 'Sure: {"touch_files": ["echo_sync/a.py"], "note": "Change \\"f\\" in (a) [x]"} {"skip": "no"}'
    assert H.parse(ans, FILES) == {"touch_files": ["echo_sync/a.py"], "note": "Change f in a x"}


def test_parse_rejects_bad_answers():
    assert H.parse('{"touch_files": ["echo_sync/zzz.py"], "note": "x"}', FILES) is None
    assert H.parse(json.dumps({"touch_files": FILES, "note": "x"}), FILES) is None
    assert H.parse('{"touch_files": [], "note": "x"}', FILES) is None
    assert H.parse('{"touch_files": ["echo_sync/a.py"], "note": "%s"}' % ("w" * 301), FILES) is None
    assert H.parse("no json at all", FILES) is None
    assert H.parse("", FILES) is None


def test_a_pick_fits_the_light_engine():
    """Live 20.11 02:18: three picked files sent <id> to the Kilo engine, three attempts burned in two minutes."""
    from tools import agent_factory_runner as W
    assert H.MAX_FILES <= W.LIGHT_MAX_FILES
    assert H.parse(json.dumps({"touch_files": FILES[:3], "note": "x"}), FILES) is None
    assert H.parse(json.dumps({"touch_files": FILES[:2], "note": "x"}), FILES)["touch_files"] == FILES[:2]


def test_parse_skip():
    assert H.parse('{"skip": "none fits"}', FILES) == {"skip": "none fits"}


def test_select_day_rule_limit_and_kinds():
    holds = {"B4": AMB, "B1": AMB, "B2": SCOPE, "B3": "тест tests/x.py зелёный на HEAD", "B5": SCOPE, "B6": AMB}
    now = 10 ** 6
    assert [b for b, _ in H.select(holds, {}, now)] == ["B1", "B2", "B4"]
    done = {"B1": {"at": now - 3600, "status": "skip"}, "B2": {"at": now - 90000, "status": "skip"}}
    assert [b for b, _ in H.select(holds, done, now)] == ["B2", "B4", "B5"]
    assert [b for b, _ in H.select(holds, done, now, limit=1)] == ["B2"]
    done["B1"] = {"at": now - 10, "status": "later"}
    assert H.select(holds, done, now)[0][0] == "B1"
