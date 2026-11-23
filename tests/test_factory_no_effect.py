"""<id> class "a change without effect": a candidate whose guard test fails with the very output of the unchanged base
edited code off the path the test checks (live 20.11 10:35-10:43: every attempt of six tasks failed exactly like the
base). The gate marks it (event no_effect, '[no effect]' in the rejection) and the next model of the tournament is told
so before the failing output."""
from pathlib import Path

from tests.test_factory_runtime import FIX_BLOCK, Rig, gr
from tests.test_factory_tournament import APPROVE, _wire
from tools import agent_factory_runner as W

BAD = FIX_BLOCK.replace('return a-b\n=======\ndef add(a,b): return a+b', 'return a-b\n=======\ndef add(a,b): return a*b')


def test_same_failure_ignores_addresses_work_folders_and_durations():
    base = 'failure t::x: AssertionError: no job at <FastText object at 0x000001F20E6F> in task-bl_E1-ab12 (1.25s)'
    cand = 'failure t::x: AssertionError: no job at <FastText object at 0x0000028941D5> in task-bl_E1-cd34-cand-1 (3.5s)'
    assert W.same_failure(base, cand)
    assert not W.same_failure(base, cand.replace('no job', 'two jobs'))
    assert not W.same_failure('', '') and not W.same_failure('x', '')


def _coders(sent):
    return [s for s in sent if not s['review']]


def test_a_candidate_that_fails_like_the_base_is_marked_and_the_next_model_is_told(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)          # the fake gate gives the base and a*b the same output
    sent = _wire(rig, monkeypatch, lambda model: BAD if model == 'x' else FIX_BLOCK, lambda model, n: APPROVE)
    result = rig.once()
    coders = _coders(sent)
    assert 'no_effect' in result['events']
    assert 'had NO effect on the failing test' in coders[1]['prompt']
    assert 'had NO effect' not in coders[0]['prompt']
    assert 'Failing test output:\nassert add(2,3)==5 -> got -1' in coders[1]['prompt']


def test_a_candidate_that_changes_the_failure_is_not_marked(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)

    def run_tests(root, tests, timeout_s):
        text = (Path(root) / 'calc.py').read_text()
        if 'a+b' in text:
            return gr(True)
        return gr(False, diag='assert add(2,3)==5 -> got 6' if 'a*b' in text else 'assert add(2,3)==5 -> got -1')
    rig.run_tests_fn = run_tests
    sent = _wire(rig, monkeypatch, lambda model: BAD if model == 'x' else FIX_BLOCK, lambda model, n: APPROVE)
    result = rig.once()
    assert 'no_effect' not in result['events']
    assert all('had NO effect' not in s['prompt'] for s in _coders(sent))
