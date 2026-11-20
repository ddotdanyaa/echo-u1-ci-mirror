"""fac-tournament (owner: «турнир нескольких кандидатов с последовательной цепочкой критиков»).
A pass of the light engine asks up to TOURNAMENT_SIZE coders, each another model, and every next one is told why the
previous candidate could not be used; the first candidate that passes the mechanical checks goes to the gate. The
critics review one after another, each another model with its own lens; the first rejection ends the chain, and a
missing further model shortens the tournament or the chain instead of failing the pass."""
import json

from tests.test_factory_runtime import FIX_BLOCK, TWO_CHANNELS, Rig, approval_json

APPROVE = approval_json()      # a critic's approval answers the rubric: it cites a real line of the test


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
    # the critics are not the author of the candidate that stands (y): x, then the third model z
    assert [s['model'] for s in sent if s['review']] == ['x', 'z'] and result['critics'] == ['google/x', 'google/z']


def test_small_follow_up_off_keeps_a_small_model_out_of_the_later_candidates(tmp_path, monkeypatch):
    """<id> small_follow_up (20.11 02:05): Gemma as a later candidate won 0 of ~20 coder calls of the night at ~175 s
    each. 'off': after the first candidate no small-tier model is asked; 'on' asks it as before."""
    wrong = FIX_BLOCK.replace('return a-b', 'return a - b', 1)
    small = dict(id='c3', group='p3', model='google/z', key_env='KEY', tpm=100000, rpd=100, verified=True,
                 tier='small')
    for arm, coders in ((False, ['x', 'y']), (True, ['x', 'y', 'z'])):
        sub = tmp_path / ('on' if arm else 'off')
        sub.mkdir()
        rig = Rig(sub, monkeypatch)
        cfg = sub / 'three.json'
        cfg.write_text(json.dumps(dict(channels=TWO_CHANNELS + [small])))
        sent = _wire(rig, monkeypatch, lambda model: wrong, lambda model, n: APPROVE)
        result = rig.once(channel_config=cfg, small_follow_up=arm)
        assert [s['model'] for s in sent if not s['review']] == coders, arm
        assert result['reason'] == 'gate:no_changes'


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
    two = tmp_path / 'two.json'
    two.write_text(json.dumps(dict(channels=TWO_CHANNELS)))
    result = rig.once(channel_config=two)
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


def test_the_retry_after_a_cooled_model_takes_another_model_without_the_pause(tmp_path, monkeypatch):
    """Live 20.11: a 503 of Gemma 4 cost ~67 s, 20 of them the transient pause, though the cooled model was never
    asked again by that retry."""
    rig = Rig(tmp_path, monkeypatch)
    slept, asked = [], []

    def post(url, key, body, timeout):
        asked.append(body['model'])
        review = body['messages'][0]['content'] == rig.w.LIGHT_REVIEW_RULES
        if body['model'] == 'x' and not review:
            return 503, json.dumps([dict(error=dict(code=503, message='high demand'))]).encode()
        content = APPROVE if review else FIX_BLOCK
        return 200, json.dumps(dict(choices=[dict(message=dict(content=content), finish_reason='stop')],
                                    usage=dict(prompt_tokens=900, completion_tokens=40))).encode()
    monkeypatch.setattr(rig.w, 'engine_for', lambda role, task: 'light')
    monkeypatch.setattr(rig.w, '_light_post', post)
    monkeypatch.setattr(rig.w.time, 'sleep', lambda s: slept.append(s))
    result = rig.once()
    assert asked[:2] == ['x', 'y']                      # the cooled x is not asked again by the retry
    # y wrote it; x is cooled, so z is the only critic: a short chain keeps the candidate pending, never approves
    assert result['status'] == 'READY' and result['reason'] == 'review_chain_short' and result['pending_review']
    assert rig.w.channels.TRANSIENT_RETRY_S not in slept
