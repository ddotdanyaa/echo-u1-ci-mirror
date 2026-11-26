"""X-TURN (U15 S5): ``Resolutions`` is the single record of an utterance: exactly one per tid, typed revisions, the question taken over by a newer one is told by ``ControlledMedia._overtaken``.
Shadow only records and logs: the actions are the ones of 'off'."""
import json
import logging
import pathlib
import re

import pytest

from echo_sync.settings import CALL_SETTINGS, resolve
from echo_sync.utterance_judge import Resolutions
from test_stable_partial_ack import Speaker, dictation, speaks

SCENES = pathlib.Path(__file__).parent / 'fixtures' / 'harvest_scenes' / 'scenes.json'


def lines(caplog):
    return [r.getMessage() for r in caplog.records if r.getMessage().startswith('echo-sync resolution tid=')]


def test_the_switch_is_gone():      # judge_once is not a setting: the first decision always stands
    assert 'judge_once' not in resolve({'judge_once': 'on'})


def test_ear_take_then_a_cloud_final_is_one_resolution_in_on():
    r = Resolutions()
    rec, out = r.resolve('t1', resolution='question', cause='ear_take', epoch=3)
    assert out == 'new' and rec['final_rev'] == 1
    rec, out = r.resolve('t1', resolution='question', cause='cloud_final', epoch=3)
    assert out == 'revised' and rec['final_rev'] == 2
    assert len(r.records) == 1 and r.untyped == 0


def test_an_untyped_second_decision_is_refused():
    on = Resolutions()
    on.resolve('t1', resolution='question', cause='cloud_final', epoch=1)
    assert on.resolve('t1', resolution='silent', cause=None)[1] == 'untyped'
    assert on.get('t1')['resolution'] == 'question'
    assert on.untyped == 1 and len(on.records) == 1


def test_the_same_decision_again_changes_nothing():
    r = Resolutions()
    r.resolve('t1', resolution='question', cause='cloud_final')
    rec, out = r.resolve('t1', resolution='question', cause='cloud_final')
    assert out == 'same' and rec['final_rev'] == 1


def test_the_record_is_bounded():
    r = Resolutions(keep=3)
    for n in range(10):
        r.resolve('t%d' % n, resolution='question', cause='cloud_final')
    assert list(r.records) == ['t7', 't8', 't9']


def ask(tmp_path, said, caplog=None):
    d = dictation(tmp_path / 'ask', settings={**CALL_SETTINGS})
    s = Speaker(d).start().words(said)
    s.wait(0.8)
    if caplog is not None:
        caplog.clear()
    s.final()
    return d, s


def test_a_question_makes_one_record_with_the_epoch_and_an_unspoken_void(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    d, s = ask(tmp_path, 'а почему вода кипит при ста градусах?', caplog)
    got = lines(caplog)
    assert len(got) == 1 and 'final_rev=1' in got[0] and 'void_by=None' in got[0], got
    assert 'tid=u-live' in got[0] and d.controller.resolutions.get('u-live')['final_rev'] == 1


def shape(actions):
    return [(a.get('type'), a.get('text')) for a in actions if a.get('type') != 'cancel' or True]


def scene_texts(kind):
    data = json.loads(SCENES.read_text(encoding='utf8'))
    return [s['text'] for s in data['scenes'] if s['kind'] == kind]


@pytest.mark.skipif(not SCENES.exists(), reason='data outside the repository: tests/fixtures/harvest_scenes/scenes.json (real call scenes of the owner are kept out of git)')
@pytest.mark.parametrize('kind,count', [('topic_change', 5), ('self_correction', 6)])
def test_scenes_keep_their_actions_in_shadow_and_make_one_record_per_tid(tmp_path, kind, count):
    texts = scene_texts(kind)
    assert len(texts) == count
    d = dictation(tmp_path / kind, settings={**CALL_SETTINGS})
    for n, text in enumerate(texts[:2]):      # two real utterances of the kind are enough
        s = Speaker(d, tid='u-%d' % n).start()
        s.words(text.split('.')[0][:200])
        s.wait(0.5)
        s.final()
    recs = d.controller.resolutions
    assert all(recs.get('u-%d' % n) and recs.get('u-%d' % n)['final_rev'] == 1 for n in range(2)), 'one record, no second look'
