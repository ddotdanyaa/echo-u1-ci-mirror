"""<id> (owner: the second critic gets the first answer with the first critic's critique, the third gets
the original and both critiques). Every next critic of the chain gets the remarks of all earlier critics of the same
candidate and is told to find what they missed or got wrong; an approving critic's remarks are kept, not dropped; the
pass report lists every critique in order."""
import json

from tests.test_factory_runtime import FIX_BLOCK, TWO_CHANNELS, Rig, approval_json
from tests.test_factory_tournament import _wire


def test_the_second_critic_sees_the_first_critique_and_the_report_lists_both(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    third = dict(id='c3', group='p3', model='google/z', key_env='KEY', tpm=100000, rpd=100, verified=True)
    cfg = tmp_path / 'three.json'
    cfg.write_text(json.dumps(dict(channels=TWO_CHANNELS + [third])))
    first = approval_json(['the error message is not checked'])
    sent = _wire(rig, monkeypatch, lambda model: FIX_BLOCK,
                 lambda model, n: first if n == 1 else approval_json())
    result = rig.once(channel_config=cfg)
    reviews = [s for s in sent if s['review']]
    assert [s['model'] for s in reviews] == ['y', 'z']
    assert 'Earlier critics' not in reviews[0]['prompt']
    assert 'Earlier critics' in reviews[1]['prompt']
    assert 'the error message is not checked' in reviews[1]['prompt']
    assert result['status'] == 'REVIEW'
    assert result['critiques'] == ['critic 1 approved: the error message is not checked',
                                   'critic 2 approved: no remarks']


def test_every_critic_sees_what_earlier_candidates_of_the_task_were_rejected_for(tmp_path, monkeypatch):
    """Skeptic 20.11: a redo of a rejected test kept the very lines the coordinator's rejection named, and two critics
    approved it with 11 and 16 tokens; they never saw that rejection. Requeue notes and repeat markers are left out."""
    from tools import agent_factory as F
    rig = Rig(tmp_path, monkeypatch)
    rig.once()                                                     # creates the state
    rig.edit_state(lambda s: (s['tasks']['T1'].update(status='READY', feedback=[
        {'source': 'opus', 'text': 'a test that needs all five parts down at once pins no real behaviour'},
        {'source': 'gate', 'text': F.REPEAT_MARK + ' gate:#aQX18d34f08f'},
        {'source': 'opus', 'text': 'Retry on factory version v9. Your last attempt failed as gate-red'}]),
        s['tasks']['T1'].pop('pending_review', None)))
    rig.ready_again()
    sent = _wire(rig, monkeypatch, lambda model: FIX_BLOCK, lambda model, n: approval_json())
    rig.once()
    reviews = [s for s in sent if s['review']]
    assert reviews and all('Earlier candidates of this task were rejected for' in s['prompt'] for s in reviews)
    assert all('pins no real behaviour' in s['prompt'] for s in reviews)
    assert not any('Retry on factory version' in s['prompt'] or 'gate:#aQX18d34f08f' in s['prompt'] for s in reviews)


def test_a_task_without_a_rejection_tells_its_critics_nothing(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    sent = _wire(rig, monkeypatch, lambda model: FIX_BLOCK, lambda model, n: approval_json())
    rig.once()
    assert not any('Earlier candidates of this task' in s['prompt'] for s in sent if s['review'])


def test_a_rejection_after_an_approval_is_listed_after_it(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    third = dict(id='c3', group='p3', model='google/z', key_env='KEY', tpm=100000, rpd=100, verified=True)
    cfg = tmp_path / 'three.json'
    cfg.write_text(json.dumps(dict(channels=TWO_CHANNELS + [third])))
    rejection = '{"approved": false, "reasons": ["the test does not pin 40 000"]}'
    sent = _wire(rig, monkeypatch, lambda model: FIX_BLOCK,
                 lambda model, n: approval_json() if n == 1 else rejection)
    result = rig.once(channel_config=cfg)
    assert result['status'] == 'READY' and result['reason'].startswith('review:')
    assert result['critiques'] == ['critic 1 approved: no remarks', 'critic 2 rejected: the test does not pin 40 000']
    assert 'critic 1 approved: no remarks' in [s for s in sent if s['review']][1]['prompt']


def _two_models(tmp_path):
    cfg = tmp_path / 'two.json'
    cfg.write_text(json.dumps(dict(channels=TWO_CHANNELS)))
    return cfg


def test_a_chain_cut_short_never_approves(tmp_path, monkeypatch):
    """Live 20.11 16:46: <id> was approved by ONE critic because no second model was free ("review_chain_short"), and
    the coordinator rejected its commit 4 minutes later. A short chain keeps the candidate pending for a later pass."""
    rig = Rig(tmp_path, monkeypatch)
    sent = _wire(rig, monkeypatch, lambda model: FIX_BLOCK, lambda model, n: approval_json())
    result = rig.once(channel_config=_two_models(tmp_path))
    assert [s['model'] for s in sent if s['review']] == ['y']           # coder x, critic y: no third model
    assert 'review_chain_short' in result['events']
    assert result['status'] != 'REVIEW' and result['reason'] == 'review_chain_short'
    assert result.get('cross_review') is not True
    assert result['pending_review'] is True
    assert rig.state()['tasks']['T1'].get('pending_review')                # the candidate waits for the next critic


def test_a_chain_cut_short_three_times_in_a_row_is_blocked(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    _wire(rig, monkeypatch, lambda model: FIX_BLOCK, lambda model, n: approval_json())
    two = _two_models(tmp_path)
    seen = []
    for _ in range(3):
        result = rig.once(channel_config=two)
        seen.append((result['status'], result['reason']))
        rig.ready_again()
    assert seen[-1] == ('BLOCKED', 'review_chain_short')
    assert all(r == 'review_chain_short' for _, r in seen)


def test_a_full_chain_of_two_other_models_still_approves(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    sent = _wire(rig, monkeypatch, lambda model: FIX_BLOCK, lambda model, n: approval_json())
    result = rig.once()                                                    # the rig's default: three models
    assert [s['model'] for s in sent if s['review']] == ['y', 'z']
    assert result['status'] == 'REVIEW' and 'review_chain_short' not in result['events']


def test_short_chains_of_one_candidate_are_counted_even_with_other_waits_between(tmp_path, monkeypatch):
    """A channel_wait between two short chains resets defer_streak; the term is counted on the candidate itself, so a
    candidate never waits pending forever."""
    rig = Rig(tmp_path, monkeypatch)
    _wire(rig, monkeypatch, lambda model: FIX_BLOCK, lambda model, n: approval_json())
    two = _two_models(tmp_path)
    seen = []
    for _ in range(3):
        result = rig.once(channel_config=two)
        seen.append((result['status'], result['reason']))
        rig.ready_again()
        rig.edit_state(lambda s: s['tasks']['T1'].update(defer_streak={'reason': 'channel_wait', 'n': 1}))
    assert seen[-1] == ('BLOCKED', 'review_chain_short')
    assert not rig.state()['tasks']['T1'].get('pending_review')


def _three_models(tmp_path):
    third = dict(id='c3', group='p3', model='google/z', key_env='KEY', tpm=100000, rpd=100, verified=True)
    cfg = tmp_path / 'three.json'
    cfg.write_text(json.dumps(dict(channels=TWO_CHANNELS + [third])))
    return cfg


def _later_pass(rig):
    rig.edit_state(lambda s: s['tasks']['T1'].update(not_before=0))      # the quota state stays as it is


def test_first_critic_vote_survives_a_short_chain(tmp_path, monkeypatch):
    """W-review 2: pass 1 has one critic only; its voice stays on the candidate, pass 2 asks one new critic."""
    rig = Rig(tmp_path, monkeypatch)
    _wire(rig, monkeypatch, lambda model: FIX_BLOCK, lambda model, n: approval_json(['looks right']))
    first = rig.once(channel_config=_two_models(tmp_path))
    assert first['reason'] == 'review_chain_short'
    votes = rig.state()['tasks']['T1']['pending_review']['votes']
    assert [(v['model'], v['ok']) for v in votes] == [('google/y', True)]
    _later_pass(rig)
    sent = _wire(rig, monkeypatch, lambda model: FIX_BLOCK, lambda model, n: approval_json())
    second = rig.once(channel_config=_three_models(tmp_path))
    assert [s['model'] for s in sent if s['review']] == ['z']             # y is not asked a second time
    assert second['status'] == 'REVIEW' and second['review_verdict'] == 'approve'
    assert second['critiques'] == ['critic 1 approved: looks right', 'critic 2 approved: no remarks']
    assert second['review_votes'] == [dict(model='google/y', ok=True), dict(model='google/z', ok=True)]


def test_same_model_vote_is_not_counted_twice(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    _wire(rig, monkeypatch, lambda model: FIX_BLOCK, lambda model, n: approval_json())
    two = _two_models(tmp_path)
    rig.once(channel_config=two)
    _later_pass(rig)
    sent = _wire(rig, monkeypatch, lambda model: FIX_BLOCK, lambda model, n: approval_json())
    second = rig.once(channel_config=two)                                  # the same two models: still one voice
    assert not [s for s in sent if s['review']]
    assert second['reason'] == 'review_chain_short' and second.get('cross_review') is not True
    assert len(rig.state()['tasks']['T1']['pending_review']['votes']) == 1


def test_vote_reset_when_baseline_moves(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    _wire(rig, monkeypatch, lambda model: FIX_BLOCK, lambda model, n: approval_json())
    rig.once(channel_config=_two_models(tmp_path))
    assert rig.state()['tasks']['T1']['pending_review']['votes']
    rig.edit_state(lambda s: s['tasks']['T1']['pending_review'].update(baseline_digest='moved'))
    _later_pass(rig)
    sent = _wire(rig, monkeypatch, lambda model: FIX_BLOCK, lambda model, n: approval_json())
    second = rig.once(channel_config=_three_models(tmp_path))
    assert 'pending_dropped' in second['events']
    assert [s['model'] for s in sent if s['review']] == ['y', 'z']          # a new candidate: y speaks again


def test_reject_vote_kept_and_second_approve_split_goes_to_mechanical_ranking(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    rejection = '{"approved": false, "reasons": ["the test pins nothing"]}'
    _wire(rig, monkeypatch, lambda model: FIX_BLOCK, lambda model, n: rejection)
    first = rig.once(channel_config=_two_models(tmp_path))
    assert first['reason'] == 'review_chain_short' and first['review_verdict'] == 'unavailable'
    assert [v['ok'] for v in rig.state()['tasks']['T1']['pending_review']['votes']] == [False]
    _later_pass(rig)
    sent = _wire(rig, monkeypatch, lambda model: FIX_BLOCK, lambda model, n: approval_json())
    second = rig.once(channel_config=_three_models(tmp_path))
    assert [s['model'] for s in sent if s['review']] == ['z']
    assert 'review_chain_short' not in second['events'] and second['review_verdict'] in ('approve', 'reject')
    assert second['review_votes'] == [dict(model='google/y', ok=False), dict(model='google/z', ok=True)]


def test_a_standing_candidate_skips_the_gates_while_no_reviewer_is_free(tmp_path, monkeypatch):
    """W-review 1: no reviewer for longer than 30 s: a wait without a strike, the cloud gates are not paid again."""
    import time
    rig = Rig(tmp_path, monkeypatch)
    _wire(rig, monkeypatch, lambda model: FIX_BLOCK, lambda model, n: approval_json())
    two = _two_models(tmp_path)
    rig.once(channel_config=two)
    rig.edit_state(lambda s: (s['tasks']['T1'].update(not_before=0),
                              s.setdefault('channel_quotas', {}).update(channel_cool={'c2': time.time() + 900})))
    sent = _wire(rig, monkeypatch, lambda model: FIX_BLOCK, lambda model, n: approval_json())
    second = rig.once(channel_config=two)
    assert second['status'] == 'WAITING_CHANNEL' and second['reason'] == 'channel_wait'
    assert 'review_deferred_before_gates' in second['events'] and second['wait_s'] > 30
    assert not sent and not second['stages'].get('gate_s')
    assert rig.state()['tasks']['T1']['pending_review']['votes']          # the candidate and its voice are kept
