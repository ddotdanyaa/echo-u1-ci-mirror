"""V4 Ф9: the cycle of dictation. Backlog: about five words a portion, a repeat in 1-2 s of silence, the last word leads on, a continuation from the named word, the pause of writing is no stumble. The recorded call is
c24-c; the stand and the check with a friend are not here.

Real ControlledMedia, NativeMediaSocket, ShadowEar (rig ``call``: dictation said before the call, the rule of repeats and the cycle on). Not run on the laptop. A red test is a defect card for the family P
(``repeat_rule``, ``cm_portion``) or T (the terms).

U141: the cycle (its 1 s pace and its cap ``cycle_max_repeats``) is told from the owner's speech, the places they went on from (``_recording``), not from the word «dictation». A dictating owner not yet seen writing
is waited for by the pen (``pen_wait``) and bounded by ``max_auto_repeats``.
"""
import pytest

from portion_kit import (DICTATION_CYCLE_SECONDS, DICTATION_START_SECONDS, GRID, P1, P2, RULE, TICK, after, call, utter, walk)      # noqa: F401 - call is the fixture
from echo_sync.timer_policy import DICTATION_WORD_SECONDS, pen_wait      # noqa: E402

CYCLE = dict(dictation='on', **RULE)


def test_silence_while_dictating_brings_the_same_portion_again_in_about_a_second(call):
    rig = walk(call, **CYCLE)
    end = rig.ended()
    pen = pen_wait(DICTATION_WORD_SECONDS, len(P1.split()))
    cue = rig.next_cue(pen + 1.5)
    assert cue is not None and cue.text == P1, rig.said()
    assert pen - GRID <= cue.t - end <= pen + 1.0 + GRID, f'the repeat came {cue.t - end:.2f} s after the end of the portion'


def test_the_cycle_is_bounded_it_is_no_loop_with_nobody_there(call):
    rig = walk(call, **CYCLE, cycle_max_repeats=3)
    rig.pump(120)
    assert rig.said().count(P1) == 1 + rig.c.max_auto_repeats, rig.said()


def test_the_last_word_said_leads_on_to_the_next_portion(call):
    rig = walk(call, **CYCLE)
    assert after(rig, 'в листьях') == [P2]


def test_a_continuation_from_the_named_word_says_the_rest_from_it(call):
    rig = walk(call, **CYCLE)
    assert after(rig, 'повтори со слова хлорофилл', wait=1.5) == ['хлорофилл в листьях.'], rig.said()


def test_the_last_word_written_named_goes_on_after_it(call):
    rig = walk(call, **CYCLE)
    assert after(rig, 'последнее записанное слово хлорофилл', wait=1.5) == ['в листьях.'], rig.said()


def test_a_stop_inside_the_portion_while_writing_waits_for_the_pen_not_a_stumble_help(call):
    rig = walk(call, **CYCLE)
    utter(rig, 'свет попадает', speech=0.8, turn='u5', final='свет попадает.')
    rig.pump(DICTATION_START_SECONDS - 1.0)
    assert rig.said() == [P1], f'the pen was taken for a stumble: {rig.said()}'

import pytest as _pt_no_lead
pytestmark = _pt_no_lead.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)
