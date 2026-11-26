"""U38: one stretch of speech, ONE judge. The ear (by breaths) and the cloud (by its final) hear the same utterance; whichever arrives first reacts, the other judges nothing a second time:
exactly one reaction (one cue, no cut of it, the same reply token and plan revision, no ``engine.rewind``), and the wait for the cloud after the ear's words is at most ``BANK_WAIT_S``.
The order is fed BOTH ways through the real controller (rig of test_h3 / test_h4: real NativeMediaSocket, ShadowEar, ControlledMedia on the injected clock)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import helpers_s6_state as S      # noqa: E402
from test_h3_tempo import ASKED, HEAD, TICK, WAIT_OF_H3, call      # noqa: E402,F401 - call is the fixture
from test_h4_ear_first import ANSWER, EAR_17, EAR_QUESTION, FINAL_QUESTION, SILENCE, question      # noqa: E402

BANK_WAIT_S = 0.5      # ARCH_ONE / U38: the bank's answer after the ear's words waits for the cloud no longer than this
SPEECH, LAG = 3.15, 0.15


def watch(rig):
    """Counts of what must not happen twice: rewinds of the plan, cuts of the sound by a judge."""
    seen = {'rewind': 0, 'cut': 0}
    c = rig.c
    rewind, act = c.engine.rewind, c._act

    def counted_rewind(*a, **k):
        seen['rewind'] += 1
        return rewind(*a, **k)

    def counted_act(kind, reason, **k):
        if kind == 'reset_portion':seen['cut'] += 1
        return act(kind, reason, **k)
    c.engine.rewind, c._act = counted_rewind, counted_act
    return seen


def utterance(rig, ear_text, final_text, order, turn='u1'):
    """One utterance, the cloud's turn announced before its end. ``order``: 'ear' - the ear's text, 2.5 s later the cloud's final; 'cloud' - the cloud's final first (0.05 s after the speech ended), the ear's text after it.
    Returns (when the speech ended, when the ear's words arrived)."""
    uid = rig.onset()
    rig.pump(3.1)
    rig.w.feed(S.turn_created(turn, 'user', ''))
    rig.pump(SPEECH - 3.1)
    ended = rig.offset()
    if order == 'cloud':
        rig.pump(0.05)
        rig.w.feed(S.turn_done(turn, 'user', final_text))
        rig.pump(LAG - 0.05)
    else:
        rig.pump(LAG)
    heard = rig.w.clock.t
    rig.worker.heard(uid, ear_text)
    rig.pump(TICK)
    if order == 'ear':
        rig.pump(2.5)
        rig.w.feed(S.turn_done(turn, 'user', final_text))
    rig.pump(0.5)      # not further: the silence timer's own repeat (3.5 s) is no second judge, but it is no part of this test
    return ended, heard


@pytest.mark.parametrize('order', ['ear', 'cloud'])
def test_a_reference_is_answered_once_whichever_comes_first(call, order):
    rig = call(fast_text='on', **WAIT_OF_H3)
    seen = watch(rig)
    utterance(rig, EAR_17, ASKED, order)
    assert rig.said() == [HEAD], rig.said()
    assert not any(cue.cleared for cue in rig.cues()) and len(rig.cues()) == 1
    assert seen == {'rewind': 0, 'cut': 0}, seen
    assert rig.c.question_id == 'u1'


@pytest.mark.parametrize('order', ['ear', 'cloud'])
def test_a_question_the_job_prepared_is_answered_once_whichever_comes_first(call, order):
    rig = call(fast_text='on', **WAIT_OF_H3)
    seen = watch(rig)
    uid = rig.onset()
    rig.pump(0.5)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.pump(0.5)
    rig.offset()
    if order == 'cloud':
        rig.w.feed(S.turn_done('u1', 'user', FINAL_QUESTION))
    rig.pump(LAG)
    rig.worker.heard(uid, EAR_QUESTION)
    rig.pump(TICK)
    rig.pump(SILENCE)
    if rig.fake.runs:
        rig.job_says(0, ANSWER)
        rig.job_ends(0)
    rig.pump(1.0)
    if order == 'ear':
        rig.w.feed(S.turn_done('u1', 'user', FINAL_QUESTION))
        rig.pump(1.0)
    answers = [text for text in rig.said() if '988' in text]
    assert len(answers) == 1, rig.said()
    assert not any(cue.cleared for cue in rig.cues()), 'a second judge cut the first one\'s cue'
    assert seen['rewind'] == 0 and seen['cut'] == 0, seen
    assert len(rig.fake.runs) <= 1, 'the question was given to the job twice'


def test_the_bank_does_not_wait_for_the_cloud_longer_than_half_a_second_after_the_ears_words(call):
    rig = call(fast_text='on', **WAIT_OF_H3)
    ended, heard = utterance(rig, EAR_17, ASKED, 'ear')
    first = rig.cues()[0].t
    assert first - heard <= BANK_WAIT_S, (first - heard, 'the cue waited for the cloud after the ear had spoken')
    assert first - ended <= LAG + BANK_WAIT_S


def test_the_cloud_first_leaves_nothing_for_the_ear_to_judge_a_second_time(call):
    """The final came first: the ear's words of the same utterance arrive later and open no second question, no second cue, no second decision."""
    rig = call(fast_text='on', **WAIT_OF_H3)
    utterance(rig, EAR_17, ASKED, 'cloud')
    revision, epoch, question_id = rig.c.state()['revision'], rig.c.epoch, rig.c.question_id
    rig.pump(1.0)
    assert (rig.c.state()['revision'], rig.c.epoch, rig.c.question_id) == (revision, epoch, question_id)
    assert rig.said() == [HEAD]
