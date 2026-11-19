"""fac-tournament (owner: «турнир нескольких кандидатов с последовательной цепочкой критиков»).
A pass of the light engine asks up to TOURNAMENT_SIZE coders, each another model, and every next one is told why the
previous candidate could not be used; the first candidate that passes the mechanical checks goes to the gate. The
critics review one after another, each another model with its own lens; the first rejection ends the chain, and a
missing further model shortens the tournament or the chain instead of failing the pass."""
import json

from tests.test_factory_runtime import FIX_BLOCK, TWO_CHANNELS, Rig

APPROVE = '{"approved": true, "reasons": []}'


def _wire(rig, monkeypatch, code_for, review_for):
    sent = []

    def post(url, key, body, timeout):
        review = body['messages'][0]['content'] == rig.w.LIGHT_REVIEW_RULES
        prompt = body['messages'][1]['content']
        sent.append(dict(model=body['model'], review=review, prompt=prompt))
        content = review_for(body['model'], sum(s['review'] for s in sent)) if review else code_for(body['model'])
        reply = dict(choices=[dict(message=dict(content=content), finish_reason='stop')],
                     usage=dict(prompt_tokens=900, completion_tokens=40))
        return 200, json.dumps(reply).encode()
    monkeypatch.setattr(rig.w, 'engine_for', lambda role, task: 'light')
    monkeypatch.setattr(rig.w, '_light_post', post)
    return sent


def test_a_candidate_that_changes_nothing_hands_the_pass_to_another_model(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    wrong = FIX_BLOCK.replace('return a-b', 'return a - b', 1)        # a SEARCH that is not in the file
    sent = _wire(rig, monkeypatch, lambda model: wrong if model == 'x' else FIX_BLOCK, lambda model, n: APPROVE)
    result = rig.once()
    assert result['status'] == 'REVIEW'
    coders = [s for s in sent if not s['review']]
    assert [s['model'] for s in coders] == ['x', 'y']
    assert 'Another model already tried this task' in coders[1]['prompt']
    assert 'SEARCH not found' in coders[1]['prompt']                     # it is told why the first one failed
    assert 'Another model already tried this task' not in coders[0]['prompt']
    assert result['tournament'] == dict(size=3, candidates=2, models=['google/x', 'google/y'])
    assert [c.get('candidate') for c in result['calls'] if c['role'] != 'review'] == [0, 1]
    # the reviewer is not the author of the candidate that stands; no third model: the chain is short, not failed
    assert [s['model'] for s in sent if s['review']] == ['x'] and result['critics'] == ['google/x']


def test_a_usable_first_candidate_needs_no_second_coder(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    sent = _wire(rig, monkeypatch, lambda model: FIX_BLOCK, lambda model, n: APPROVE)
    result = rig.once()
    assert result['status'] == 'REVIEW'
    assert [s['model'] for s in sent if not s['review']] == ['x']
    assert result['tournament']['candidates'] == 1


def test_when_every_model_failed_the_pass_is_rejected_once_with_the_last_reason(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    wrong = FIX_BLOCK.replace('return a-b', 'return a - b', 1)
    sent = _wire(rig, monkeypatch, lambda model: wrong, lambda model, n: APPROVE)
    result = rig.once()
    assert result['status'] == 'READY' and result['reason'] == 'gate:no_changes'
    assert [s['model'] for s in sent if not s['review']] == ['x', 'y']      # two models exist: a short tournament
    assert rig.state()['tasks']['T1']['attempts'] == 1                       # one strike for the pass, not one per model


def test_the_second_critic_is_another_model_with_its_own_lens_and_its_rejection_counts(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    third = dict(id='c3', group='p3', model='google/z', key_env='KEY', tpm=100000, rpd=100, verified=True)
    cfg = tmp_path / 'three.json'
    cfg.write_text(json.dumps(dict(channels=TWO_CHANNELS + [third])))
    rejection = '{"approved": false, "reasons": ["the test does not pin the result of 40 000"]}'
    sent = _wire(rig, monkeypatch, lambda model: FIX_BLOCK, lambda model, n: APPROVE if n == 1 else rejection)
    result = rig.once(channel_config=cfg)
    reviews = [s for s in sent if s['review']]
    assert [s['model'] for s in reviews] == ['y', 'z']
    assert 'SECOND critic' in reviews[1]['prompt'] and 'SECOND critic' not in reviews[0]['prompt']
    assert result['status'] == 'READY' and result['reason'].startswith('review:') and '40 000' in result['reason']
    assert result['critics'] == ['google/y', 'google/z']
