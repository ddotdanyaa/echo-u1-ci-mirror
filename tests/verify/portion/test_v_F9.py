"""V4 Ф9: the cycle of dictation. Backlog: about five words a portion, a repeat in 1-2 s of silence, the last word leads on, a continuation from the named word, the pause of writing is no stumble. The recorded call is
c24-c; the stand and the check with a friend are not here.

Real ControlledMedia, NativeMediaSocket, ShadowEar (rig ``call``: dictation said before the call, the rule of repeats and the cycle on). Not run on the laptop. A red test is a defect card for the family P
(``repeat_rule``, ``cm_portion``) or T (the terms).
"""
import pytest

from portion_kit import (DICTATION_CYCLE_SECONDS, DICTATION_START_SECONDS, GRID, P1, P2, RULE, TICK, after, call, utter, walk)      # noqa: F401 - call is the fixture

CYCLE = dict(dictation='on', **RULE)


def test_silence_while_dictating_brings_the_same_portion_again_in_about_a_second(call):
    rig = walk(call, **CYCLE)
    end = rig.ended()
    cue = rig.next_cue(DICTATION_CYCLE_SECONDS + 1.5)
    assert cue is not None and cue.text == P1, rig.said()
    assert DICTATION_CYCLE_SECONDS - GRID <= cue.t - end <= DICTATION_CYCLE_SECONDS + 1.0 + GRID, f'the repeat came {cue.t - end:.2f} s after the end of the portion'


def test_the_cycle_is_bounded_it_is_no_loop_with_nobody_there(call):
    rig = walk(call, **CYCLE, cycle_max_repeats=3)
    rig.pump(120)
    assert rig.said().count(P1) == 1 + 3, rig.said()


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
