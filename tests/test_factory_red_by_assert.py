"""fac-red-by-assert: live 19.11 19:24-20:13, three of three promoted 'write a test' tasks (<id>, <id>, <id>) were red
on the base only because the test crashed while calling the code wrongly (a dict where a list is due, guessed private
methods and constructor arguments): the gate took any failure for 'red'. A new test is red on the merits only when it
reaches its assertion (or fails on purpose with pytest.fail); a case that fails with another exception is a crash."""
from tools import factory_gate as G

CASES = '''import pytest


def f(a):
    return a


def test_assert():
    assert f(1) == 2


def test_fail_on_purpose():
    pytest.fail("the defect: f does not double")


def test_type():
    f(1, 2)
'''


def test_the_gate_names_the_cases_that_crash_before_their_assertion(tmp_path):
    (tmp_path / 'test_k.py').write_text(CASES, encoding='utf-8')
    result = G.run_tests(tmp_path, ['test_k.py'], 15)
    assert result.failed == 3
    crashed = getattr(result, 'crashed', ())
    assert len(crashed) == 1 and 'test_type' in crashed[0] and 'TypeError' in crashed[0]


def test_a_failure_without_a_message_does_not_break_the_gate(tmp_path, monkeypatch):
    """Coordinator's acceptance: the factory's first version took the first line of an empty message."""
    import xml.etree.ElementTree as ET
    (tmp_path / 'test_k.py').write_text('def test_a():\n    assert 1 == 2\n', encoding='utf-8')
    real = ET.parse

    def no_message(path, *a, **k):
        tree = real(path, *a, **k)
        for failure in tree.getroot().iter('failure'):
            failure.set('message', '')
        return tree
    monkeypatch.setattr(G.ET, 'parse', no_message)
    result = G.run_tests(tmp_path, ['test_k.py'], 15)
    assert result.failed == 1 and len(result.crashed) == 1


def test_a_new_test_that_crashes_on_the_base_is_not_red_on_the_merits():
    fields = {name for name in G.GateResult.__dataclass_fields__}
    assert 'crashed' in fields
    crash = G.GateResult(1, 2, 0, 2, 0, 0, True, crashed=('test_k::test_type: TypeError: f() takes 1 argument',))
    ok, why = G.accept_unit_test(crash)
    assert not ok and 'TypeError' in why
    assert G.accept_unit_test(G.GateResult(1, 2, 0, 2, 0, 0, True)) == (True, 'ok')
