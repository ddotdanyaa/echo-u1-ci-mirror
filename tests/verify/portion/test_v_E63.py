"""V4 E63: sound earlier than the cloud's final (the ear's own release, ``ear_release``). Backlog: deferred with a reason (shadow first, ``overruled`` on the replay); the target: false = 0 on the replay at the
same thresholds. Here: with the release on and the cloud's turn left open for good, the answer of the job is still said at the ear's silence, and only a closed question; an open tail, the ear's silence cut by new speech
and a text the ear did not take are held. The replay of the recorded calls and the count of ``overruled`` are the cloud's.

Real ControlledMedia, NativeMediaSocket, ShadowEar and FastText (rig ``call`` with the live profile: ear_release on). Not run on the laptop. A red test is a defect card for the family T (the terms) or K (the judge).
"""
import pytest

import helpers_s6_state as S
from portion_kit import EAR_BAPTISM, EAR_RELEASE_SILENCE_SECONDS, EAR_TAIL_SILENCE_SECONDS, GRID, LIVE_RULES, TICK, call      # noqa: F401 - call is the fixture

ANSWER = 'Крещение Руси произошло в 988 году.'
CLOUD_BAPTISM = 'Так, в каком году было крещение Руси'      # what the cloud's open turn holds of it (E86: the ear opens a question only on the stable piece of that turn, a turn with no word is no second witness)
CLOUD_TAIL = 'Сколько будет сто тысяч под двадцать'


def ear_asks(rig, said, cloud, speech=2.0):
    """The ear hears the question and the cloud's turn is open with the words of it (``cloud``); the cloud's final never comes."""
    uid = rig.onset()
    rig.pump(speech)
    rig.w.feed(S.turn_created('u1', 'user', cloud))
    ended = rig.offset()
    rig.pump(0.1)
    rig.worker.heard(uid, said)
    rig.pump(TICK)
    rig.job_says(0, ANSWER)
    return ended


def test_a_closed_question_is_answered_at_the_ears_silence_with_no_final_of_the_cloud(call):
    rig = call(**LIVE_RULES)
    ended = ear_asks(rig, EAR_BAPTISM, CLOUD_BAPTISM)
    cue = rig.next_cue(EAR_RELEASE_SILENCE_SECONDS + 0.5)
    assert cue is not None and cue.t - ended == pytest.approx(EAR_RELEASE_SILENCE_SECONDS, abs=GRID + TICK + 0.1), f'the cue came {cue and cue.t - ended}'
    assert rig.c.question_id == 'u1', 'the question the cue answers is the cloud turn that was open'


def test_an_open_tail_is_not_answered_at_the_short_window(call):
    rig = call(**LIVE_RULES)
    ear_asks(rig, 'сколько будет сто тысяч под двадцать', CLOUD_TAIL)
    assert rig.next_cue(EAR_RELEASE_SILENCE_SECONDS + 3 * GRID) is None, f'an answer to a question that has not ended: {rig.said()}'
    assert rig.c.question_id is None


def test_new_speech_inside_the_window_takes_the_early_answer_back(call):
    rig = call(**LIVE_RULES)
    ear_asks(rig, EAR_BAPTISM, CLOUD_BAPTISM)
    rig.pump(0.3)                                 # 0.5 s of silence: inside the window
    rig.onset()
    rig.pump(2.0)
    assert rig.said() == [], f'sound over the speech that went on: {rig.said()}'
