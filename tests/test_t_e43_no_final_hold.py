"""E43 (package T): no hold without a bound. The last hold of ``ControlledMedia.hold`` - the cue waits for the FINAL of the question it answers - had none: a turn the cloud keeps open, or never announces, held the cue for ever. The real controller, the injected clock:
the cue is held while the final may still come and plays at ANSWER_WAIT_SECONDS from the end of the question's speech."""
import pytest

import helpers_s6_state as S
from echo_sync import timer_policy as tp
from test_h3_tempo import call      # noqa: F401 - the fixture
from test_v5_answer_gate import cue


def open_question(rig, tid='u1', *, ended_ago=0.0):
    rig.w.feed(S.turn_created(tid, 'user', ''))
    rig.c.question_id = tid
    rig.c.speech_ended[tid] = rig.c.clock() - ended_ago


def test_a_final_that_never_comes_holds_the_cue_to_the_bound_and_not_longer(call):
    rig = call()
    open_question(rig)
    held, until = rig.c.hold(cue(), None)
    assert held is True and until is not None, 'while the final may still come the cue waits, and says when to look again'
    rig.w.clock.advance(tp.ANSWER_WAIT_SECONDS - 0.5)
    assert rig.c.hold(cue(), None)[0] is True
    rig.w.clock.advance(0.6)
    assert rig.c.hold(cue(), None)[0] is False, 'past the bound the cue plays: the listener is never left in silence by a missing final'


def test_the_bound_counts_from_the_end_of_the_speech_not_from_when_the_cue_came(call):
    rig = call()
    open_question(rig, ended_ago=tp.ANSWER_WAIT_SECONDS + 1.0)
    assert rig.c.hold(cue(), None)[0] is False


def test_a_final_that_comes_releases_the_cue_at_once(call):
    rig = call()
    open_question(rig)
    assert rig.c.hold(cue(), None)[0] is True
    rig.w.feed(S.turn_done('u1', 'user', 'Сколько будет пять умножить на пять'))
    assert rig.c.hold(cue(), None)[0] is False


def test_the_hold_is_a_row_of_the_table_and_is_explained():
    from echo_sync import controlled_media
    assert controlled_media.HOLD_BOUNDS['no_final'][0] == tp.ANSWER_WAIT_SECONDS
    assert tp.HOLD_NAMES['no_final'] == 'timer_policy.ANSWER_WAIT_SECONDS'
    assert tp.holds_unexplained() == []
