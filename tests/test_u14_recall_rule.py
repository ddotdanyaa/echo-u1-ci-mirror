"""U14-S6: recall is the first rule of the U15 judge (``recall_words`` on, the ledger on). Off: the old verdict stands."""
import json
import logging
import pathlib

import pytest

from echo_sync.controlled_media import ControlledMedia
from echo_sync.conversation_ledger import _words

SCENES = pathlib.Path(__file__).parent / 'fixtures' / 'harvest_scenes' / 'scenes.json'
if not SCENES.exists():      # RED-C: a module-level read was a collection error in a checkout without the owner's scenes
    pytest.skip('data outside the repository: tests/fixtures/harvest_scenes/scenes.json (real call scenes of the owner are kept out of git)', allow_module_level=True)
SETTINGS = {'conversation_ledger': 'memory', 'recall_words': 'on', 'words_per_portion': 30}
S11 = next(s for s in json.loads(SCENES.read_text(encoding='utf-8'))['scenes'] if s['id'] == 'S11')['text']


def turn(tid, text):
    return {'type': 'turn.done', 'turn': {'id': tid, 'role': 'user', 'transcript': text}}


def spoken(actions):
    return [a['text'] for a in actions if a.get('type') == 'speak']


def call(tmp_path, **settings):
    c = ControlledMedia(tmp_path / 's.db', session_id='s', settings={**SETTINGS, **settings})
    c.begin_call()
    c.provider(turn('u1', S11))
    return c


def test_s11_then_the_command_speaks_the_20_verbatim_words(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    c = call(tmp_path)
    cues = spoken(c.provider(turn('u2', 'повтори мои последние 20 слов')))
    assert cues, 'a recall is answered at once'
    assert cues[0].split() == _words(S11)[-20:]
    judge = [r.getMessage() for r in caplog.records if r.getMessage().startswith('echo-sync judge ') and 'tid=u2' in r.getMessage()]
    assert len(judge) == 1 and 'rule=recall' in judge[0] and judge[0].count('analyses=0') == 1
    assert c.resolutions.records['u2']['rule'] == 'recall'


def test_the_command_itself_is_not_in_its_own_words(tmp_path):
    c = call(tmp_path)
    cues = spoken(c.provider(turn('u2', 'повтори мои последние 3 слова')))
    assert cues[0].split() == _words(S11)[-3:]


def test_the_heard_words_of_the_cue_without_an_owner(tmp_path):
    c = call(tmp_path)
    cue = {'revision': 1, 'index': 0, 'text': 'раз два три четыре пять'}
    c._cue_event('began', cue, 10.0)
    c._cue_event('done', cue, 13.0)
    cues = spoken(c.provider(turn('u2', 'повтори последние три слова')))
    assert cues[0].split() == ['три', 'четыре', 'пять']


def test_goes_on_restores_the_plan_after_the_recall(tmp_path):
    c = call(tmp_path)
    c.provider(turn('u2', 'повтори мои последние 5 слов'))
    assert c.suspended is not None or c.local_answer
    c.provider(turn('u3', 'продолжай'))
    assert c.resolutions.records['u3']['resolution'] in ('resume', 'question')


def test_an_ear_partial_then_the_full_final_is_one_recall(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    c = call(tmp_path)
    c.ear_partial({'uid': 'u2', 'text': 'повтори'})
    c.provider({'type': 'turn.delta', 'turn_id': 'u2', 'delta': 'повтори'})
    first = spoken(c.provider(turn('u2', 'повтори мои последние 20 слов')))
    again = spoken(c.provider(turn('u2', 'повтори мои последние 20 слов')))
    assert len(first) == 1 and again == []
    assert sum('echo-sync recall tid=u2' in r.getMessage() for r in caplog.records) == 1


def test_flag_off_the_old_verdict_stands(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    c = call(tmp_path, recall_words='off')
    c.provider(turn('u2', 'повтори мои последние 20 слов'))
    assert 'echo-sync recall' not in caplog.text
    assert c.resolutions.records['u2']['rule'] != 'recall'


def test_ledger_off_the_flag_is_off_too(tmp_path):
    c = ControlledMedia(tmp_path / 's.db', session_id='s', settings={'recall_words': 'on'})
    assert c.recall_words == 'off' and c.convo is None


def test_nothing_to_repeat_goes_to_the_other_rules(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    c = ControlledMedia(tmp_path / 's.db', session_id='s', settings=SETTINGS)
    c.begin_call()
    c.provider(turn('u2', 'повтори мои последние 20 слов'))
    assert 'echo-sync recall' not in caplog.text


def test_goes_on_restores_the_dictation_after_a_recall_in_it(tmp_path):
    from test_stable_partial_ack import Speaker, dictation
    d = dictation(tmp_path / 'r', settings=SETTINGS)
    assert d.controller.convo is not None
    portion, index = d.current, d.index
    s = Speaker(d, 'u-r').start().words('повтори мои последние 4 слова')
    s.wait(0.8)
    said = s.final()
    assert said and len(said[0].split()) == 4, said
    s.wait(0.3)
    s2 = Speaker(d, 'u-go').start().words('продолжай')
    s2.wait(0.8)
    back = s2.final() + s2.wait(0.5)
    assert back and 'Цельсия' in ' '.join(back), (said, back)      # the plan the recall set aside comes back, as after any intruder
