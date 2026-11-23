"""A unit_test candidate: every test function it ADDS must be red on the base code."""
from tools import factory_gate as G

TWO = "def test_red():\n    assert 0\n\n\ndef test_green():\n    assert 1\n"
OLD = "def test_old():\n    assert 1\n"


def _res(failed_ids, collected, env_failed=()):
    n = len(failed_ids)
    return G.GateResult(1 if n else 0, collected, collected - n, n, 0, 0, True,
                        failed_ids=tuple(sorted(failed_ids)), env_failed=tuple(env_failed))


def test_green_function_among_red_is_rejected_by_name():
    res = _res(['tests.test_x::test_red'], 2)
    assert G.accept_unit_test(res) == (True, 'ok')            # old callers: no added names, no check
    ok, why = G.accept_unit_test(res, added=G.added_tests('', TWO))
    assert not ok
    assert 'test_green' in why and 'passes on the base code' in why and 'test_red' not in why.replace('test_green', '')


def test_all_added_red_is_accepted():
    res = _res(['tests.test_x::test_red', 'tests.test_x::test_green'], 2)
    assert G.accept_unit_test(res, added=G.added_tests('', TWO)) == (True, 'ok')


def test_existing_file_only_added_function_is_checked():
    new = OLD + "\n\ndef test_new():\n    assert 0\n"
    assert G.added_tests(OLD, new) == ['test_new']
    res = _res(['tests.test_x::test_new'], 2)               # test_old is green on base and is not ours to judge
    assert G.accept_unit_test(res, added=G.added_tests(OLD, new)) == (True, 'ok')
    ok, why = G.accept_unit_test(_res(['tests.test_x::test_old'], 2), added=G.added_tests(OLD, new))
    assert not ok and 'test_new' in why


def test_class_methods_and_parametrized_ids():
    text = "class TestA:\n    def test_a(self):\n        assert 0\n\n    def test_b(self):\n        assert 1\n"
    added = G.added_tests('', text)
    assert added == ['TestA.test_a', 'TestA.test_b']
    ok, why = G.accept_unit_test(_res(['tests.test_x.TestA::test_a[1]'], 2), added=added)
    assert not ok and 'TestA.test_b' in why
    assert G.accept_unit_test(_res(['tests.test_x.TestA::test_a[1]', 'tests.test_x.TestA::test_b'], 2),
                              added=added)[0]


def test_env_failed_is_unknown_never_a_pass():
    res = _res(['tests.test_x::test_red', 'tests.test_x::test_green'], 2, env_failed=['tests.test_x::test_green'])
    assert G.accept_unit_test(res, added=G.added_tests('', TWO)) == (True, 'ok')


def test_unparsable_text_is_not_a_verdict():
    assert G.added_tests('', 'def test_(:\n') == []
