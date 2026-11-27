"""Registry 6.02 «Повтори последние N слов»: state by the registry - РАБОТАЕТ НА СЕРВЕРЕ (включено, действие не измерено).
Proved through the real controller (helpers_night_memory.Call: World + ControlledMedia + CallTrace journal, the cloud turns fed as events, the text model only at the boundary):
the owner says a fixed sentence, then «повтори мои последние N слов» for several N; the phone hears (and the synthesis gets) exactly the last N words of the owner, verbatim and
in order (a long one in portions, the owner says each back); the model is not asked; the call journal holds the verdict (judge rule=recall, kind question). With ``recall_words`` off the same words go the old way (rule base, no cue).
A second test (xfail strict, a find): after a redial past CONVERSATION_GAP_S the recall still repeats words of the EARLIER call.
Keys set by the test (live server values; code defaults are off / 1.0-style): conversation_ledger=memory, recall_words=on, fast_text=on, words_per_portion=3, topic_recap=off, v6_memory=off
(the stand's MEMORY set would turn the last two on; the server has them off). Dummy check: recall_words switched to 'off' in a private copy (the test goes red on the cue)."""
import logging
import re

import helpers_night_memory as N
import pytest

LIVE = {'conversation_ledger': 'memory', 'recall_words': 'on', 'fast_text': 'on', 'words_per_portion': 3, 'topic_recap': 'off'}
SAID = 'Сегодня обсудим устройство велосипеда: цепь передаёт вращение на заднее колесо, а тормоза замедляют обод.'
WORDS = re.findall(r'\w+', SAID.lower())
CMD = 'повтори мои последние %d слов'


@pytest.fixture
def make(tmp_path, caplog):
    caplog.set_level(logging.INFO)          # the journal gets the controller's decisions from the log
    calls = []

    def factory(**profile):
        calls.append(N.Call(tmp_path / ('c%d' % len(calls)), **{**LIVE, **profile}))
        return calls[-1]
    try:
        yield factory
    finally:
        for call in calls:
            call.close()


def recall(call, n):
    """Say the command, return (new cues, model asks, judge records of the journal about it)."""
    heard, asked = len(call.cues()), len(call.all_requests())
    uid = call.say(CMD % n)
    call.owner_follows()                                            # a long answer comes in portions: the owner says each back to get the next
    judges = [r for r in call.journal() if r['ev'] == 'judge' and r['tid'] == uid]
    return call.cues()[heard:], len(call.all_requests()) - asked, judges


@pytest.mark.parametrize('n', [3, 5, 12])
def test_last_n_words_of_the_owner_verbatim(make, n):
    call = make()
    call.say(SAID)
    call.pump(2.0)
    cues, asked, judges = recall(call, n)
    assert ' '.join(cues).split() == WORDS[-n:], (n, cues)          # the last n words, in order, nothing added (long ones in portions)
    assert call.w.synth_calls[-len(cues):] == cues                  # and exactly those texts went to the synthesis
    assert asked == 0                                               # a local answer: the text model is not asked
    assert [(j['rule'], j['kind'], j['reason']) for j in judges] == [('recall', 'question', 'recall')]      # the verdict is in the journal
    assert not call.w.errors and not call.w.violations


def test_flag_off_the_words_go_the_old_way(make):
    call = make(recall_words='off')        # the key is gone from settings.DEFAULTS (an unknown key is ignored): the recall is a rule of the call
    call.say(SAID)
    call.pump(2.0)
    cues, _, judges = recall(call, 5)
    assert ' '.join(cues).split() == WORDS[-5:] and [j['rule'] for j in judges] == ['recall']


@pytest.mark.xfail(strict=True, reason='реестр 6.02: РАБОТАЕТ, на деле после повторного набора через 30 минут (новый разговор) повтор читает слова ПРОШЛОГО звонка: память звонка живёт в процессе, recall не режет по началу разговора')
def test_a_new_call_does_not_repeat_the_earlier_calls_words(make):
    call = make()
    call.say(SAID)
    call.pump(2.0)
    recall(call, 3)
    call.redial(1800.0)                                             # a new conversation: well past the 600 s gap
    cues, _, _ = recall(call, 3)
    assert cues == [], cues                                         # nothing was said in this call yet: nothing to repeat (actual: the earlier call's words)

import pytest as _pt_no_lead
pytestmark = _pt_no_lead.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)
