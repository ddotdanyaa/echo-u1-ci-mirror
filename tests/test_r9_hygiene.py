"""R9 / R31-1 / H31-11 / E33.2 / E33.3: the hygiene of the suite.
(1) A substitution that a test leaves in a module is put back whatever its name is (not only the two that were once found).
(2) The reds are two lists with two meanings: known_red.txt (defects of the code) and cloud_env_red.txt (the cloud's environment, each under a reason); they do not overlap and name existing tests.
(3) The ratchet does not call a cut or hung run green, and it prints a load-flaky name as something to rerun alone."""
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
from tools import red_ratchet as R  # noqa: E402
import importlib.util  # noqa: E402
_spec = importlib.util.spec_from_file_location('echo_root_conftest_r9', ROOT / 'tests' / 'conftest.py')      # by its file: ``import conftest`` gives the LAST conftest collected (tests/break/answer_route/conftest.py in a shard that has it)
C = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(C)

PROBE = types.ModuleType('helpers_r9_probe')
PROBE.original = lambda: 'original'
PROBE.threading = types
PROBE.data = {'k': 1}
sys.modules['helpers_r9_probe'] = PROBE
ORIGINAL = PROBE.original


# 1. R31-1: every leaked callable, class or module comes back

pytestmark = pytest.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)


def test_a_third_substitution_that_nobody_listed_is_put_back():
    before = C.snapshot()
    PROBE.original = lambda: 'a patch that nobody closed'
    PROBE.threading = sys
    PROBE.data = {'k': 2}                       # data is not a substitution: it is left as the test left it
    try:
        put = C.restore(before, 'probe')
        assert sorted(put) == ['helpers_r9_probe.original', 'helpers_r9_probe.threading']
        assert PROBE.original is ORIGINAL and PROBE.threading is types and PROBE.data == {'k': 2}
        assert [item for who, item in C.LEAKS if who == 'probe'] == put
    finally:
        C.LEAKS[:] = [leak for leak in C.LEAKS if leak[0] != 'probe']
        PROBE.data = {'k': 1}


def test_a_module_that_was_replaced_is_not_dragged_back():
    before = C.snapshot()
    replacement = types.ModuleType('helpers_r9_probe')
    replacement.original = 'new module'
    sys.modules['helpers_r9_probe'] = replacement
    try:
        assert C.restore(before, 'probe') == []
    finally:
        sys.modules['helpers_r9_probe'] = PROBE


def test_the_leak_of_this_test_is_gone_in_the_next_one_a():
    PROBE.original = lambda: 'left on purpose by the first of two tests'


def test_the_leak_of_this_test_is_gone_in_the_next_one_b():
    assert PROBE.original is ORIGINAL, 'the autouse fixture put the module back after the test before'


# 2. the two lists of reds

def test_the_code_reds_and_the_cloud_environment_reds_are_apart_and_real():
    known, env = R.load_known(), R.load_env()
    assert not known & set(env), 'a name is either a defect or the environment, not both'
    for name in [*known, *env]:
        assert (ROOT / name.split('::')[0]).exists(), f'{name}: the test is gone, delete the line'
    assert all(env.values()), 'every cloud-environment red stands under a "## reason:" header'
    assert set(env.values()) and all(len(reason.split()) >= 4 for reason in env.values())


# 3. the ratchet

def run(text, tmp_path, *extra):
    path = tmp_path / 'run.txt'
    path.write_text(text, encoding='utf-8')
    return R.main([str(path), *extra])


CUT = '============ test session starts ============\ntests/test_a.py ..F.\n'
DONE = '============ test session starts ============\nFAILED tests/test_a.py::test_x - boom\n=== 1 failed, 5 passed in 3.2s ===\n'


def test_a_cut_run_is_not_green(tmp_path, capsys):
    assert run(CUT, tmp_path) == 2
    assert 'NO SUMMARY LINE' in capsys.readouterr().out


def test_a_summary_that_counts_more_failures_than_the_run_names_is_not_green(tmp_path, capsys):
    assert run('=== test session starts ===\n=== 3 failed, 5 passed in 3.2s ===\n', tmp_path) == 3


def test_a_finished_run_is_judged_by_its_names(tmp_path, capsys):
    known, env = tmp_path / 'known.txt', tmp_path / 'env.txt'
    known.write_text('', encoding='utf-8')
    env.write_text('## reason: the cloud has no speech engine\ntests/test_a.py::test_x\n', encoding='utf-8')
    assert run(DONE, tmp_path, '--known', str(known), '--env', str(env)) == 0
    out = capsys.readouterr().out
    assert 'cloud-env: 1' in out and 'new: 0' in out
    env.write_text('', encoding='utf-8')
    assert run(DONE, tmp_path, '--known', str(known), '--env', str(env)) == 1


def test_a_load_flaky_red_is_named_as_one_to_rerun_alone(tmp_path, capsys):
    known, env = tmp_path / 'known.txt', tmp_path / 'env.txt'
    known.write_text('', encoding='utf-8')
    env.write_text('', encoding='utf-8')
    name = 'tests/test_ear_shadow.py::test_an_endless_utterance_is_cut_and_goes_on_as_a_new_one'
    text = f'=== test session starts ===\nFAILED {name} - boom\n=== 1 failed in 3.2s ===\n'
    assert run(text, tmp_path, '--known', str(known), '--env', str(env)) == 1
    assert 'rerun it ALONE' in capsys.readouterr().out


def test_an_xpass_is_reported_as_a_fixed_defect(tmp_path, capsys):
    known, env = tmp_path / 'known.txt', tmp_path / 'env.txt'
    known.write_text('', encoding='utf-8')
    env.write_text('', encoding='utf-8')
    run('=== test session starts ===\nXPASS tests/test_a.py::test_b - DEF-3\n=== 1 xpassed in 1.0s ===\n', tmp_path, '--known', str(known), '--env', str(env))
    assert 'XPASS (fixed' in capsys.readouterr().out


def test_a_strict_xpass_is_a_fixed_defect_and_not_only_a_new_red(tmp_path, capsys):
    known, env = tmp_path / 'known.txt', tmp_path / 'env.txt'
    known.write_text('', encoding='utf-8')
    env.write_text('', encoding='utf-8')
    run('=== test session starts ===\nFAILED tests/test_a.py::test_b - [XPASS(strict)] DEF-3\n=== 1 failed in 1.0s ===\n', tmp_path, '--known', str(known), '--env', str(env))
    assert 'XPASS (fixed' in capsys.readouterr().out
