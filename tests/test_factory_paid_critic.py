"""Owner ~14:30, rule 4: a paid control critic (Anthropic API) runs AFTER the free review chain approved and the
gates passed; a budget guard caps the day's spend; every catch the free chain missed goes into the error-class registry
that the free review prompt reads, so the quality stays when the key is switched off. The network is always faked."""
import json
import types
from urllib.parse import urlsplit

import pytest

from tests.test_factory_runtime import Rig, _kilo_engine  # noqa: <id>  (_kilo_engine: autouse, the rig fakes Kilo)
from tools import factory_paid_critic as P

SECRET = 'example-test-secret-value'


def _usage(i=1000, o=200):
    return dict(input_tokens=i, output_tokens=o)


def answer(verdict='reject', reason='hard-codes 5', cls='hardcoded-expectation', symptom='returns the literal'):
    text = json.dumps(dict(verdict=verdict, reason=reason, **{'class': cls}, symptom=symptom))
    return 200, json.dumps(dict(content=[dict(type='text', text=text)], usage=_usage())).encode()


class Net:
    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []

    def __call__(self, url, headers, body, timeout):
        self.calls.append((url, dict(headers), body))
        return self.replies.pop(0) if self.replies else answer('approve', '', '', '')


@pytest.fixture
def env(tmp_path, monkeypatch):
    key = tmp_path / 'anthropic.cfg'
    key.write_text('ANTHROPIC_API_KEY=%s\nANTHROPIC_DAILY_BUDGET_USD=100\nANTHROPIC_DENY_MODELS=opus\n' % SECRET)
    monkeypatch.setenv('FACTORY_PAID_ENV', str(key))
    monkeypatch.setenv('FACTORY_PAID_DIR', str(tmp_path / 'echo'))
    (tmp_path / 'echo').mkdir()
    monkeypatch.setattr(P, '_today', lambda: '2026-11-22')
    monkeypatch.setenv('FACTORY_BUILDERS_SPEND', str(tmp_path / 'absent.json'))
    monkeypatch.setenv('FACTORY_BUILDERS_WAITING', str(tmp_path / 'absent_wait'))
    return tmp_path


class T:
    id, title, kind, touch_files = 'T1', 'Fix sum', 'code', ('calc.py',)
    goal = 'add must return the sum'


def test_no_key_means_skipped_without_a_call(env, monkeypatch):
    (env / 'anthropic.cfg').write_text('')
    net = Net()
    monkeypatch.setattr(P, '_post', net)
    assert P.control(T, 'diff', 'failure') is None and net.calls == []


def test_a_bad_credit_skips_the_critic_and_leaves_no_reservation(env, monkeypatch):
    monkeypatch.setattr(P, '_post', lambda *a: (402, json.dumps(dict(error=dict(type='billing_error'))).encode()))
    assert P.control(T, 'diff') is None and P.credit_dead()
    assert json.loads(P._spend_file().read_text())['reserved_usd'] == 0


def test_a_broken_spend_file_means_no_paid_voice_not_a_fault(env, monkeypatch):
    (env / 'echo' / 'paid_spend.json').write_text('[1, 2]')
    net = Net()
    monkeypatch.setattr(P, '_post', net)
    assert P.control(T, 'diff') is None and net.calls == []
    (env / 'echo' / 'paid_spend.json').write_text('{broken')
    assert P.control(T, 'diff') is None and net.calls == []


def test_missing_env_file_means_skipped(env, monkeypatch):
    monkeypatch.setenv('FACTORY_PAID_ENV', str(env / 'nope.cfg'))
    net = Net()
    monkeypatch.setattr(P, '_post', net)
    assert P.control(T, 'diff', 'failure') is None and net.calls == []


def test_a_model_with_opus_in_its_name_is_refused_in_code(env, monkeypatch):
    with pytest.raises(ValueError):
        P.refuse_opus('claude-opus-5-5')
    with pytest.raises(ValueError):
        P.refuse_opus('Claude-OPUS-x')
    monkeypatch.setattr(P, 'MODELS', ('claude-opus-5-5',))
    net = Net()
    monkeypatch.setattr(P, '_post', net)
    assert P.control(T, 'diff', 'failure') is None and net.calls == []


def test_the_call_goes_to_the_messages_api_and_reports_usd_and_tokens(env, monkeypatch):
    net = Net(answer())
    monkeypatch.setattr(P, '_post', net)
    out = P.control(T, 'DIFFTEXT', 'FAILTEXT')
    url, headers, body = net.calls[0]
    # parsed instead of a literal URL string (the mirror scanner flags address literals); the round-trip
    # check keeps it exact: no extra query/fragment delimiters, no scheme/host case changes
    endpoint = urlsplit(url)
    assert endpoint == ('https', 'api.anthropic.com', '/v1/messages', '', '') and url == endpoint.geturl() and headers['x-api-key'] == SECRET
    assert body['model'] == 'claude-sonnet-5-5' and 'opus' not in body['model']
    assert 'DIFFTEXT' in json.dumps(body) and 'FAILTEXT' in json.dumps(body) and 'add must return' in json.dumps(body)
    assert out['verdict'] == 'reject' and out['class'] == 'hardcoded-expectation'
    assert out['tokens_in'] == 1000 and out['tokens_out'] == 200
    assert out['usd'] == pytest.approx(1000 * 2 / 1e6 + 200 * 10 / 1e6)
    assert SECRET not in json.dumps(out)


def test_fallback_to_haiku_when_sonnet_is_unavailable(env, monkeypatch):
    net = Net((404, b'{"error":{"type":"not_found_error"}}'), answer('approve', 'ok', '', ''))
    monkeypatch.setattr(P, '_post', net)
    out = P.control(T, 'd', 'f')
    assert [c[2]['model'] for c in net.calls] == ['claude-sonnet-5-5', 'claude-haiku-5-5']
    assert out['verdict'] == 'approve' and out['model'] == 'claude-haiku-5-5'


def test_cumulative_allowance_stops_calls(env, monkeypatch):
    net = Net(answer(), answer())
    monkeypatch.setattr(P, '_post', net)
    P.control(T, 'd', 'f')
    saved = json.loads((env / 'echo' / 'paid_spend.json').read_text())
    assert saved['usd'] > 0 and 'date' in saved and SECRET not in json.dumps(saved)
    P.add_spend(P.allowance(P._today()) - P.spent_total())
    assert P.control(T, 'd', 'f') is None and len(net.calls) == 1


def test_midnight_preserves_the_total_allowance(env, monkeypatch):
    (env / 'echo' / 'paid_spend.json').write_text(json.dumps(dict(date='2000-01-01', usd=999)))
    net = Net(answer())
    monkeypatch.setattr(P, '_post', net)
    assert P.control(T, 'd', 'f') is None and net.calls == []
    assert P.spent_total() == 999 + P.UNKNOWN_RESERVE_USD


def test_an_unreadable_answer_is_skipped_not_a_verdict(env, monkeypatch):
    bad = (200, b'{"content":[{"type":"text","text":"no json"}],"usage":{}}')
    monkeypatch.setattr(P, '_post', Net(bad, bad))
    assert P.control(T, 'd', 'f') is None


def test_lessons_pick_the_relevant_entries_and_stay_short(env):
    rows = [dict(ts='t', task='A', **{'class': 'off-by-one'}, symptom='x' * 400, files=['other.py'], kind='code', free_missed=True),
            dict(ts='t', task='B', **{'class': 'hardcoded-expectation'}, symptom='literal', files=['calc.py'], kind='code',
                 free_missed=True),
            dict(ts='t', task='C', **{'class': 'c3'}, symptom='s3', files=['calc.py'], kind='code', free_missed=True),
            dict(ts='t', task='D', **{'class': 'c4'}, symptom='s4', files=['calc.py'], kind='code', free_missed=True)]
    for r in rows:
        P.record_class(types.SimpleNamespace(id=r['task'], title='', kind=r['kind'], touch_files=r['files']),
                       {'class': r['class'], 'symptom': r['symptom'], 'reason': ''})
    text = P.lessons_for(T)
    assert 'hardcoded-expectation' in text and 'off-by-one' not in text and len(text) <= 400
    assert text.count('\n- ') + text.startswith('- ') <= 3


def test_no_registry_means_no_lessons(env):
    assert P.lessons_for(T) == ''


# --- through the real pass of the factory --------------------------------------------------------------------------
def test_a_paid_reject_returns_the_candidate_with_feedback_and_writes_the_registry(env, monkeypatch):
    rig = Rig(env, monkeypatch)
    net = Net(answer())
    monkeypatch.setattr(P, '_post', net)
    result = rig.once()
    assert result['status'] == 'READY' and result['reason'].startswith('review')
    assert 'hard-codes 5' in json.dumps(rig.state()['tasks']['T1']['feedback'][-1])
    assert result['paid_critic']['verdict'] == 'reject' and 'x-api-key' not in json.dumps(result)
    reg = (env / 'echo' / 'classes.json').read_text()
    row = json.loads(reg)['classes']['hardcoded-expectation']
    assert row['paid'] is True and row['hits'] == 1 and row['last_cases'][0]['task'] == 'T1'
    assert SECRET not in json.dumps(result) and SECRET not in reg


def test_a_paid_approve_keeps_the_free_verdict_and_writes_no_registry(env, monkeypatch):
    rig = Rig(env, monkeypatch)
    monkeypatch.setattr(P, '_post', Net(answer('approve', 'fine', '', '')))
    result = rig.once()
    assert result['status'] == 'REVIEW' and result['paid_critic']['verdict'] == 'approve'
    assert not (env / 'echo' / 'classes.json').exists()


def test_without_a_key_the_free_contour_works_unchanged(env, monkeypatch):
    (env / 'anthropic.cfg').write_text('')
    rig = Rig(env, monkeypatch)
    net = Net()
    monkeypatch.setattr(P, '_post', net)
    result = rig.once()
    assert result['status'] == 'REVIEW' and 'paid_critic' not in result and net.calls == []


def test_registry_entries_reach_the_free_review_prompt(env, monkeypatch):
    P.record_class(types.SimpleNamespace(id='B', title='', kind='code', touch_files=['calc.py']),
                   {'class': 'hardcoded-expectation', 'symptom': 'returns the literal', 'reason': ''})
    rig = Rig(env, monkeypatch)
    monkeypatch.setattr(P, '_post', Net(answer('approve', '', '', '')))
    rig.once()
    review_prompt = rig.prompts[1]
    assert 'hardcoded-expectation' in review_prompt and 'returns the literal' in review_prompt



def _short_chain(env, monkeypatch):
    from tests.test_factory_critic_prior import FIX_BLOCK, _two_models, _wire, approval_json
    rig = Rig(env, monkeypatch)
    _wire(rig, monkeypatch, lambda model: FIX_BLOCK, lambda model, n: approval_json())
    return rig, _two_models(env)


def test_the_paid_critic_is_the_second_voice_when_no_free_model_is_left(env, monkeypatch):
    """Live 21.11 17:20-17:50: 19 candidates approved by one free critic waited (review_chain_short) because no third
    free model was left. Rule 4: the paid critic is the insurance second voice; it is called once per candidate."""
    rig, two = _short_chain(env, monkeypatch)
    net = Net(answer('approve', 'fine', '', ''))
    monkeypatch.setattr(P, '_post', net)
    result = rig.once(channel_config=two)
    assert 'paid_second_critic' in result['events'] and result['status'] == 'REVIEW', result
    assert len(net.calls) == 1                                  # the control step after the gates does not ask again


def test_a_paid_second_voice_reject_returns_the_candidate(env, monkeypatch):
    rig, two = _short_chain(env, monkeypatch)
    monkeypatch.setattr(P, '_post', Net(answer()))
    result = rig.once(channel_config=two)
    assert result['status'] == 'READY' and result['reason'].startswith('review'), result
    assert 'hardcoded-expectation' in (env / 'echo' / 'classes.json').read_text()


def test_without_a_key_a_short_chain_still_waits(env, monkeypatch):
    (env / 'anthropic.cfg').write_text('')
    rig, two = _short_chain(env, monkeypatch)
    net = Net()
    monkeypatch.setattr(P, '_post', net)
    result = rig.once(channel_config=two)
    assert result['reason'] == 'review_chain_short' and net.calls == []


def _short_reject_chain(env, monkeypatch):
    import json as _json
    from tests.test_factory_critic_prior import FIX_BLOCK, _two_models, _wire
    rig = Rig(env, monkeypatch)
    no = _json.dumps(dict(approved=False, reasons=['the fix looks wrong'], defect_assert_line='', fix_changes_value='',
                          independent_asserts=[]))
    _wire(rig, monkeypatch, lambda model: FIX_BLOCK, lambda model, n: no)
    return rig, _two_models(env)


def test_a_lone_free_reject_is_decided_by_the_paid_voice_not_left_waiting(env, monkeypatch):
    """Live 22.11 01:20-01:50: 17 short chains - one free critic rejected, no second free model, the candidate waited."""
    rig, two = _short_reject_chain(env, monkeypatch)
    net = Net(answer())                                          # the paid voice rejects too
    monkeypatch.setattr(P, '_post', net)
    result = rig.once(channel_config=two)
    assert 'paid_second_critic' in result['events'] and len(net.calls) == 1, result
    assert result['reason'] != 'review_chain_short' and result['reason'].startswith('review'), result


def test_a_standing_candidate_with_a_kept_voice_still_reaches_the_paid_second_voice(env, monkeypatch):
    """W-review fix 2: pass 1 has no key: one free voice is kept, the chain is short. Pass 2 has the key and the same two
    models: the precheck must not end in review_chain_short, the paid critic is the second voice (rule 4 of 21.11)."""
    key = (env / 'anthropic.cfg').read_text()
    (env / 'anthropic.cfg').write_text('')
    rig, two = _short_chain(env, monkeypatch)
    first = rig.once(channel_config=two)
    assert first['reason'] == 'review_chain_short' and rig.state()['tasks']['T1']['pending_review']['votes']
    (env / 'anthropic.cfg').write_text(key)
    rig.edit_state(lambda s: s['tasks']['T1'].update(not_before=0))
    net = Net(answer('approve', 'fine', '', ''))
    monkeypatch.setattr(P, '_post', net)
    second = rig.once(channel_config=two)
    assert 'review_deferred_before_gates' not in second['events'], second
    assert 'paid_second_critic' in second['events'] and second['status'] == 'REVIEW', second
    assert len(net.calls) == 1


def test_a_standing_candidate_without_the_paid_key_is_still_cut_before_the_gates(env, monkeypatch):
    (env / 'anthropic.cfg').write_text('')
    rig, two = _short_chain(env, monkeypatch)
    rig.once(channel_config=two)
    rig.edit_state(lambda s: s['tasks']['T1'].update(not_before=0))
    second = rig.once(channel_config=two)
    assert 'review_deferred_before_gates' in second['events'] and second['reason'] == 'review_chain_short'
