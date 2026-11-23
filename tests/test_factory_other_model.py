"""21.11 (owner order): up to MAX_ATTEMPTS attempts per task, each next one on another model where the router allows.
A rejected pass remembers every model it tried (row 'coder_failed'); the next attempt's coder call leaves them out while
another model can take the call, and takes any model when none is left (a preference, never a stop). A plain red is a
retry and never a quarantine; an unsafe one (a weakened check) counts UNSAFE_STRIKE."""
import json

from tests.test_factory_runtime import FIX_BLOCK, TWO_CHANNELS, Rig
from tests.test_factory_tournament import APPROVE, _wire
from tools import agent_factory as F

WRONG = FIX_BLOCK.replace('return a-b', 'return b - a', 1)       # a SEARCH that is not in the file: no change


def _cfg(tmp_path, name, extra=()):
    path = tmp_path / name
    path.write_text(json.dumps(dict(channels=TWO_CHANNELS + list(extra))))
    return path


def _third():
    return dict(id='c3', group='p3', model='google/z', key_env='KEY', tpm=100000, rpd=100, verified=True)


def test_a_rejected_pass_remembers_every_model_it_tried(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    sent = _wire(rig, monkeypatch, lambda model: WRONG, lambda model, n: APPROVE)
    result = rig.once(channel_config=_cfg(tmp_path, 'two.json'), max_attempts=F.MAX_ATTEMPTS)
    assert result['status'] == 'READY' and result['reason'] == 'gate:no_changes'
    assert [s['model'] for s in sent if not s['review']] == ['x', 'y']
    assert F.failed_models_of(rig.state()['tasks']['T1']) == ['google/x', 'google/y']
    assert F.strikes_for(rig.state(), 'BL1') == 1             # one plain strike for the pass


def test_the_next_attempt_starts_on_a_model_that_has_not_failed_the_task(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    sent = _wire(rig, monkeypatch, lambda model: WRONG, lambda model, n: APPROVE)
    rig.once(channel_config=_cfg(tmp_path, 'two.json'), max_attempts=F.MAX_ATTEMPTS)
    rig.ready_again()
    sent.clear()
    second = rig.once(channel_config=_cfg(tmp_path, 'three.json', [_third()]), max_attempts=F.MAX_ATTEMPTS)
    coders = [s['model'] for s in sent if not s['review']]
    assert coders[0] == 'z', coders                     # x and y failed the task already; z has not
    assert 'other_model_than_2' in second['events']


def test_with_no_other_model_left_the_next_attempt_takes_any_model(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    sent = _wire(rig, monkeypatch, lambda model: WRONG, lambda model, n: APPROVE)
    two = _cfg(tmp_path, 'two.json')
    rig.once(channel_config=two, max_attempts=F.MAX_ATTEMPTS)
    rig.ready_again()
    sent.clear()
    second = rig.once(channel_config=two, max_attempts=F.MAX_ATTEMPTS)
    assert [s['model'] for s in sent if not s['review']][:1] == ['x']       # the only models: no stop, no exclusion
    assert not any(e.startswith('other_model_than') for e in second['events'])
    assert second['status'] == 'READY'


def test_a_dead_other_model_is_no_other_model(tmp_path, monkeypatch):
    """21.11 12:22: the only unused model's channel was marked dead; the pre-check ignored the mark (no env), excluded
    every live model, and the call stopped on 'dead' for an hour. A dead channel is no other model: take any model."""
    import os
    from tools import factory_channels as CH
    rig = Rig(tmp_path, monkeypatch)
    sent = _wire(rig, monkeypatch, lambda model: WRONG, lambda model, n: APPROVE)
    rig.once(channel_config=_cfg(tmp_path, 'two.json'), max_attempts=F.MAX_ATTEMPTS)
    rig.ready_again()
    state = rig.state()
    state['channel_quotas'] = {'dead': {'c3': {'key': CH._fingerprint(os.environ, _third()), 'since': 0,
                                               'reason': 'model_missing', 'until': 4e9}}}
    rig.state_path.write_text(json.dumps(state), encoding='utf-8')
    sent.clear()
    second = rig.once(channel_config=_cfg(tmp_path, 'three.json', [_third()]), max_attempts=F.MAX_ATTEMPTS)
    assert second.get('channel_reason') != 'dead' and second['status'] == 'READY', second
    assert [s['model'] for s in sent if not s['review']][:1] == ['x']
    assert not any(e.startswith('other_model_than') for e in second['events'])


def test_an_other_model_that_cannot_take_the_call_now_is_waited_for_then_no_stop(tmp_path, monkeypatch):
    """21.11 13:11: the only unused model had a key (so it passed the pre-check) but could not take the call now; the
    call raised 'no channel' and the task waited 1 h. 13:23: taking any model at once let one flash-lite spend all 6
    attempts in 3 min. Now: the task alone waits a minute for a fresh model (no attempt spent) FRESH_WAITS times,
    then the call is repeated on any model."""
    import time
    from tools import agent_factory_runner as W
    from tools import factory_channels as CH
    rig = Rig(tmp_path, monkeypatch)
    sent = _wire(rig, monkeypatch, lambda model: WRONG, lambda model, n: APPROVE)
    rig.once(channel_config=_cfg(tmp_path, 'two.json'), max_attempts=F.MAX_ATTEMPTS)
    three = _cfg(tmp_path, 'three.json', [_third()])

    def cooled_pass():
        rig.ready_again()
        state = rig.state()
        CH.cool_channel(state.setdefault('channel_quotas', {}), {'id': 'c3'}, now=time.time(), seconds=3600)
        rig.state_path.write_text(json.dumps(state), encoding='utf-8')
        sent.clear()
        return rig.once(channel_config=three, max_attempts=F.MAX_ATTEMPTS)

    second = cooled_pass()
    assert second['status'] == 'READY' and second.get('channel_reason') is None, second
    assert [s['model'] for s in sent if not s['review']][:1] == ['x']
    assert 'other_model_none_free' in second['events']


def test_plain_attempts_end_as_failed_not_quarantine(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    _wire(rig, monkeypatch, lambda model: WRONG, lambda model, n: APPROVE)
    two = _cfg(tmp_path, 'two.json')
    statuses = []
    for _ in range(2):                       # the cap is the runner's argument: 2 here keeps the rig's budget out of it
        statuses.append(rig.once(channel_config=two, max_attempts=2)['status'])
        rig.ready_again()
    row = rig.state()['tasks']['T1']
    assert statuses == ['READY', 'FAILED'] and row['status'] == 'FAILED'
    assert row.get('reason') != 'quarantine' and not F.is_quarantined(rig.state(), 'BL1')
    assert F.strikes_for(rig.state(), 'BL1') == 2


def test_the_cli_takes_up_to_max_attempts(tmp_path, monkeypatch):
    from tools import agent_factory_runner as W
    import pytest
    seen = {}
    monkeypatch.setattr(W, 'once', lambda **kwargs: seen.update(kwargs) or {'status': 'IDLE'})
    base = ['--root', str(tmp_path / 'src'), '--plan', str(tmp_path / 'p.json'),
            '--checkpoint', str(tmp_path / 's.json'), '--staging', str(tmp_path / 'stage'),
            '--small-model', 'google/x', '--large-model', 'google/x']
    assert W.main(base) == 0 and seen['max_attempts'] == F.MAX_ATTEMPTS        # the default is the cap now (was 2)
    assert W.main(base + ['--max-attempts', str(F.MAX_ATTEMPTS)]) == 0
    with pytest.raises(SystemExit):
        W.main(base + ['--max-attempts', str(F.MAX_ATTEMPTS + 1)])
