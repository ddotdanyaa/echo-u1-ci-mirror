"""V2 Н4 (the Cyrillic letter; the file name is Latin): do not repeat the old portion while the model is thinking over the NEW question (call 12:31, c25).

Real ControlledMedia (rig ``call``): an answer in play; a new question is said; its job is silent for a while (less than the job's own bound, FIRST_TEXT_S); no cue of the old plan may sound in that time, whatever the timer says.
Not run on the laptop: the verdict is the cloud's.
"""
import pytest

from echo_sync.fast_text import FIRST_TEXT_S
from echo_sync.timer_policy import TEMPO_REPEAT_SECONDS
from question_kit import ACCOUNT, AMORT, AMORT_ANSWER, LIVE_RULES, MATERIALS, TICK, answered, call, heard, plan, user_turn      # noqa: F401 - call is the fixture

THINK = FIRST_TEXT_S - 1.0       # the job has said nothing yet and its bound has not come


@pytest.mark.parametrize('into_the_wait', [0.2, TEMPO_REPEAT_SECONDS - 0.5, TEMPO_REPEAT_SECONDS + 0.5], ids=['at_once', 'timer_near', 'timer_passed'])
def test_the_old_portion_is_not_repeated_while_the_job_thinks_over_the_new_question(call, into_the_wait):
    rig = call(**LIVE_RULES)
    plan(rig, asked=ACCOUNT, answer=MATERIALS)
    rig.pump(into_the_wait)
    user_turn(rig, 'u1', AMORT, wait=0.3)
    heard_before = list(rig.said())
    assert rig.fake.runs[1:], 'the job of the new question is asked'
    rig.pump(THINK)
    assert rig.said() == heard_before, f'the old portion sounded while the model thought: {rig.said()[len(heard_before):]}'
    answered(rig, 1, AMORT_ANSWER)
    rig.pump(2.0)
    assert heard(rig, 'перенос стоимости')


def test_the_old_portion_is_not_repeated_by_the_timer_after_the_new_answer_either(call):
    rig = call(**LIVE_RULES)
    plan(rig, asked=ACCOUNT, answer=MATERIALS)
    old = rig.said()[0]
    rig.pump(1.0)
    user_turn(rig, 'u1', AMORT)
    answered(rig, 1, AMORT_ANSWER)
    rig.pump(TEMPO_REPEAT_SECONDS * 3)
    assert old not in rig.said()[1:], rig.said()
