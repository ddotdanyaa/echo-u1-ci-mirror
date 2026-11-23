"""V5 / E37 (stop over a cue, R1; the stopped plan comes alive only by the listener, R4): the records proved in tests/test_w3_replays.py (e37_r1, e37_r4) on the word «стоп»; here the other natural form «стой» and
the order of the W1F stop (the plan is kept, nothing is spoken until the listener goes on). Through the real ControlledMedia (Rig of test_h3_tempo, Wire of helpers_w1f). Not a live stop on a phone (E24)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pytest  # noqa: E402

import helpers_s6_state as S  # noqa: E402
from helpers_w1f import Wire  # noqa: E402
from test_h3_tempo import TICK, call  # noqa: E402,F401
from test_h4_ear_first import slow  # noqa: E402
from test_h5_live import LIVE, plan  # noqa: E402
from test_h6 import INERTIA, TWO_NOTICE, plan_in_flight  # noqa: E402
from echo_sync.timer_policy import TEMPO_REPEAT_SECONDS  # noqa: E402

STOPS = ['стоп', 'стой']


@pytest.mark.parametrize('word', STOPS)
def test_e37_r1_the_stop_over_the_cue_acts_before_the_clouds_final(call, word):
    rig = call(**LIVE)
    slow(rig)
    plan_in_flight(rig)
    rig.says(word, speech=0.4)
    rig.pump(0.5)
    assert rig.c.state().get('paused') is True, 'the ear alone stops: the cloud has not said a word yet'
    rig.pump(1.0)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.pump(0.5)
    rig.w.feed(S.turn_done('u1', 'user', word.capitalize()))
    rig.pump(10.0)
    assert rig.c.state().get('paused') is True and len(rig.said()) == 1, 'nothing comes back by itself'


@pytest.mark.parametrize('word', STOPS)
def test_e37_r4_a_final_that_disagrees_with_the_ear_is_a_pause_not_a_repeat(call, word):
    rig = call(**LIVE)
    plan(rig, asked=INERTIA, answer=TWO_NOTICE)
    rig.pump(1.0)
    rig.says(word, speech=0.5)
    rig.pump(0.5)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.pump(0.3)
    rig.w.feed(S.turn_done('u1', 'user', 'Срок уведомления'))
    rig.pump(TEMPO_REPEAT_SECONDS * 2 + 4.0)
    assert rig.c.state().get('paused') is True and len(rig.said()) == 1


def test_e37_nothing_is_played_between_the_stop_and_the_resume(tmp_path):
    answer = ' Инерция — это свойство тела сохранять своё состояние движения или покоя, пока внешняя сила не заставит его изменить.'
    w = Wire(tmp_path, ack=((30.0, 120.0),))
    w.user('u1', 'Что такое инерция', 0.0, 2.0)
    w.assistant('a1', answer, 2.01, 9.0)
    w.user('u2', ' Стой', 7.0, 7.5)
    w.user('u3', ' Продолжай', 30.0, 30.5)
    w.until(90.0)
    assert w.played and w.played[0][0] < 7.0, w.played
    assert w.played_after(7.5)[:1] == w.played_after(30.0)[:1], w.played
    assert w.plan().endswith('изменить.'), w.plan()
