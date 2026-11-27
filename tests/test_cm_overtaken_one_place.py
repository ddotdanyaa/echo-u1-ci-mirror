"""cm-overtaken: whether the question in play is overtaken by a newer one the ear heard is decided in ONE place, ``ControlledMedia._overtaken(where, ...)``; the four old deciders
(``_overtaken`` of G23, ``_newer_asked``, ``_admitted_after_newer``, ``_asked_over``) and the shadow ``Resolutions.void_before`` (nobody read its ``void_by``) are gone. The doors are the real controller's."""
import pathlib

import pytest

from echo_sync.timer_policy import EAR_ASK_HOLD_SECONDS
from tools.replay import quantity as Q

ECHO = pathlib.Path(__file__).resolve().parents[1] / 'echo_sync'
GONE = ('_newer_asked', '_admitted_after_newer', '_asked_over', '_void_before', 'void_before', '_step_void')


@pytest.fixture
def rig():
    rig = Q.rig_of()
    yield rig
    rig.close()
    rig._mp.undo()


def test_no_old_decider_is_left_in_the_code():
    text = '\n'.join(path.read_text(encoding='utf-8') for path in ECHO.glob('*.py'))
    assert [name for name in GONE if name in text] == []
    assert text.count('def _overtaken(') == 1


def test_the_ear_heard_a_newer_question_after_the_one_in_play_holds_the_old_plan_for_the_hold_window(rig):
    c = rig.c
    now = c.clock()
    c.question_clock = now - 1.0
    c.ear_asked = None
    assert c._overtaken('plan', now=now) is False
    c.ear_asked = now - 0.5
    assert c._overtaken('plan', now=now) is True
    assert c._overtaken('plan', now=now + EAR_ASK_HOLD_SECONDS + 0.1) is False      # the hold ends: the old plan may go on
    c.ear_asked = now - 2.0      # heard BEFORE the question in play was asked: not a newer one
    assert c._overtaken('plan', now=now) is False


def test_a_repeat_after_a_newer_question_waits_for_its_answer_only_in_the_plan_the_ear_heard_it_over(rig):
    c = rig.c
    c.tempo_live = True
    c.asked_over = (7, 1.0, 2.0)
    assert c._overtaken('repeat', state={'revision': 7}) is True
    assert c._overtaken('repeat', state={'revision': 8}) is False
    assert c._overtaken('repeat', state={}) is False
    c.tempo_live = False
    assert c._overtaken('repeat', state={'revision': 7}) is False


def test_the_answer_of_no_question_is_overtaken_without_the_ears_word(rig):
    assert rig.c._overtaken('answer') is False
