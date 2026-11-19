"""<id> (owner: the second critic gets the first answer with the first critic's critique, the third gets
the original and both critiques). Every next critic of the chain gets the remarks of all earlier critics of the same
candidate and is told to find what they missed or got wrong; an approving critic's remarks are kept, not dropped; the
pass report lists every critique in order."""
import json

from tests.test_factory_runtime import FIX_BLOCK, TWO_CHANNELS, Rig
from tests.test_factory_tournament import _wire


def test_the_second_critic_sees_the_first_critique_and_the_report_lists_both(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    third = dict(id='c3', group='p3', model='google/z', key_env='KEY', tpm=100000, rpd=100, verified=True)
    cfg = tmp_path / 'three.json'
    cfg.write_text(json.dumps(dict(channels=TWO_CHANNELS + [third])))
    first = '{"approved": true, "reasons": ["the error message is not checked"]}'
    sent = _wire(rig, monkeypatch, lambda model: FIX_BLOCK,
                 lambda model, n: first if n == 1 else '{"approved": true, "reasons": []}')
    result = rig.once(channel_config=cfg)
    reviews = [s for s in sent if s['review']]
    assert [s['model'] for s in reviews] == ['y', 'z']
    assert 'Earlier critics' not in reviews[0]['prompt']
    assert 'Earlier critics' in reviews[1]['prompt']
    assert 'the error message is not checked' in reviews[1]['prompt']
    assert result['status'] == 'REVIEW'
    assert result['critiques'] == ['critic 1 approved: the error message is not checked',
                                   'critic 2 approved: no remarks']


def test_a_rejection_after_an_approval_is_listed_after_it(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    third = dict(id='c3', group='p3', model='google/z', key_env='KEY', tpm=100000, rpd=100, verified=True)
    cfg = tmp_path / 'three.json'
    cfg.write_text(json.dumps(dict(channels=TWO_CHANNELS + [third])))
    rejection = '{"approved": false, "reasons": ["the test does not pin 40 000"]}'
    sent = _wire(rig, monkeypatch, lambda model: FIX_BLOCK,
                 lambda model, n: '{"approved": true}' if n == 1 else rejection)
    result = rig.once(channel_config=cfg)
    assert result['status'] == 'READY' and result['reason'].startswith('review:')
    assert result['critiques'] == ['critic 1 approved: no remarks', 'critic 2 rejected: the test does not pin 40 000']
    assert 'critic 1 approved: no remarks' in [s for s in sent if s['review']][1]['prompt']
