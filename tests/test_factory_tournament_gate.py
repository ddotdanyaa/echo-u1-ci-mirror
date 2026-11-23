"""<id>: a candidate that fails the test gate for real no longer ends the pass while the tournament has room.
The next candidate is another model; its prompt carries the previous failing test output; the whole pass still settles
ONE rejection (one attempt) on the last gate failure."""
import json

from tests.test_factory_runtime import FIX_BLOCK, TWO_CHANNELS, Rig, gr
from tests.test_factory_tournament import APPROVE, _wire

BAD = FIX_BLOCK.replace('return a-b\n=======\ndef add(a,b): return a+b', 'return a-b\n=======\ndef add(a,b): return a*b')
WRONG = FIX_BLOCK.replace('return a-b', 'return b - a', 1)        # a SEARCH that is not in the file


def _three(rig, tmp_path):
    third = dict(id='c3', group='p3', model='google/z', key_env='KEY', tpm=100000, rpd=100, verified=True)
    cfg = tmp_path / 'three.json'
    cfg.write_text(json.dumps(dict(channels=TWO_CHANNELS + [third])))
    return cfg


def _coders(sent):
    return [s for s in sent if not s['review']]


def test_a_gate_failure_hands_the_pass_to_another_model_that_sees_the_failing_output(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    sent = _wire(rig, monkeypatch, lambda model: BAD if model == 'x' else FIX_BLOCK, lambda model, n: APPROVE)
    result = rig.once()
    assert result['status'] == 'REVIEW'
    coders = _coders(sent)
    assert [s['model'] for s in coders] == ['x', 'y']
    note = 'its change was applied and the tests failed'
    assert note in coders[1]['prompt'] and note not in coders[0]['prompt']
    assert 'Failing test output:\nassert add(2,3)==5 -> got -1' in coders[1]['prompt']
    assert 'return a*b' in coders[1]['prompt'].split('Its diff')[1]            # the previous candidate's diff
    assert (tmp_path / 'stage' / 'for-review' / 'T1' / 'calc.py').read_text() == 'def add(a,b): return a+b\n'
    assert result['tournament']['candidates'] == 2 and result['tournament']['gate_failed'] == ['google/x']
    assert 'tournament_gate_retry_1' in result['events']


def test_when_every_candidate_fails_the_gate_the_pass_is_rejected_once(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    cfg = _three(rig, tmp_path)
    sent = _wire(rig, monkeypatch, lambda model: BAD, lambda model, n: APPROVE)
    result = rig.once(channel_config=cfg)
    assert result['status'] == 'READY' and result['reason'].startswith('gate:')
    assert 'got -1' in result['reason_detail']
    coders = _coders(sent)
    assert len(coders) == rig.w.TOURNAMENT_SIZE and len({s['model'] for s in coders}) == len(coders)
    assert rig.state()['tasks']['T1']['attempts'] == 1                   # one strike for the pass
    assert result['tournament']['gate_failed'] == ['google/x', 'google/y', 'google/z']
    assert not [s for s in sent if s['review']]


def test_an_environment_failure_in_the_gate_ends_the_pass_with_one_coder_call(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)

    def run(root, tests, timeout_s):
        if 'a-b' in (root / 'calc.py').read_text():
            return gr(False, diag='red on base')
        return gr(False, env_reason='pytest slot: no free slot')
    rig.run_tests_fn = run
    sent = _wire(rig, monkeypatch, lambda model: BAD, lambda model, n: APPROVE)
    result = rig.once()
    assert [s['model'] for s in _coders(sent)] == ['x']
    assert result['reason'] == 'transient' and 'env_shortage' in result['events']
    assert rig.state()['tasks']['T1']['attempts'] == 0


def test_an_unusable_candidate_then_a_gate_failure_then_a_pass_uses_three_calls(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    cfg = _three(rig, tmp_path)
    answers = dict(x=WRONG, y=BAD, z=FIX_BLOCK)
    sent = _wire(rig, monkeypatch, lambda model: answers[model], lambda model, n: APPROVE)
    result = rig.once(channel_config=cfg)
    assert result['status'] == 'REVIEW'
    coders = _coders(sent)
    assert [s['model'] for s in coders] == ['x', 'y', 'z']
    assert 'SEARCH not found' in coders[1]['prompt'] and 'got -1' in coders[2]['prompt']
    assert result['tournament']['gate_failed'] == ['google/y']
