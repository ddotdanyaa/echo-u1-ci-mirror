"""fac-red-async, gate part (critic round 1, high; live 19.11 20:51, <id>): a failure message 'Failed: ...' was taken
as a deliberate pytest.fail, but pytest raises Failed itself (an async def test with no async plugin: 'Failed: async
def functions are not natively supported'; a fixture called directly), and such a test never ran its body. Probe
19.11 22:20 on the live pytest: pytest's own fail comes without a frame of the test, pytest.fail(...) and
'DID NOT RAISE' keep one ('test_k.py:18: in test_fail_on_purpose'). A 'Failed:' case is on the merits only with it."""
from tools import factory_gate as G

CASES = '''import pytest


async def test_never_runs():
    assert 1 == 2


@pytest.fixture
def fx():
    return 1


def test_calls_fixture():
    assert fx() == 2


def test_fail_on_purpose():
    pytest.fail("the defect")


def test_did_not_raise():
    with pytest.raises(ValueError):
        int("1")
'''


def test_pytest_own_failed_is_a_crash_and_a_deliberate_one_is_not(tmp_path):
    (tmp_path / 'test_k.py').write_text(CASES, encoding='utf-8')
    result = G.run_tests(tmp_path, ['test_k.py'], 30)
    assert result.failed == 4
    crashed = ' '.join(result.crashed)
    assert 'test_never_runs' in crashed and 'test_calls_fixture' in crashed
    assert 'test_fail_on_purpose' not in crashed and 'test_did_not_raise' not in crashed
    assert G.accept_unit_test(result)[0] is False
