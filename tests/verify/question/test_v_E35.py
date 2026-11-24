"""V2 E35: the old plan does not come back by itself after the job's refusal; it waits for an explicit «продолжай»; a stopped plan stays stopped (H6.2). The record: in c14 all 3 cases of ``plan_goes_on_after_no_answer``
returned a portion aged 71.5 / 73.8 / 172.5 s over new answers. M14 (the skeptic): the condition «not newer» of ``_plan_stands`` survived a mutation, so it is dead or not pinned by a test; the order of events where it decides is built HERE.

Real ControlledMedia (rig ``call``): the timer's repeats are off (``max_auto_repeats = 0``) so that what comes back is the PLAN's return, not the silence timer. Not run on the laptop.
"""
import pytest

from question_kit import ACCOUNT, AMORT, AMORT_ANSWER, INERTIA, LIVE_RULES, MATERIALS, NOTICE, TICK, TWO_NOTICE, answered, call, heard, job_declines, plan, remark, said_to_the_room, user_turn      # noqa: F401


@pytest.mark.parametrize('age', [32.0, 74.0, 172.0], ids=['32s', '74s', '172s'])
def test_the_old_plan_is_not_said_again_over_a_refused_remark_at_any_age_over_30_s(call, age):
    """The three ages of c14: 71.5, 73.8 and 172.5 s."""
    rig = call(**LIVE_RULES)
    plan(rig, asked=INERTIA, answer=NOTICE)
    before = rig.said()                       # the lead of «что такое …» (question_lead, owner rule) is part of the plan's say: «Инерция —», then the job's portion
    assert NOTICE in before
    rig.c.max_auto_repeats = 0
    rig.pump(age)
    remark(rig, 'u1', 1)
    rig.pump(10.0)
    assert rig.said() == before, f'the old portion came back over the remark: {rig.said()}'
    assert rig.c.state()['history'][-1]['status'] == 'interrupted'


def test_a_newer_answer_than_the_plan_is_not_followed_by_the_plan_after_a_refused_remark(call):
    """The order where the condition «not newer» decides (the mutant M14): plan A, then answer B (newer), then a refused remark 15 s later (younger than 30 s): A must not come back over B."""
    rig = call(**LIVE_RULES)
    plan(rig, asked=ACCOUNT, answer=MATERIALS)
    rig.c.max_auto_repeats = 0
    rig.pump(1.0)
    user_turn(rig, 'u1', AMORT)
    answered(rig, 1, AMORT_ANSWER)
    rig.pump(15.0)
    seen = len(rig.said())
    remark(rig, 'u2', 2)
    rig.pump(10.0)
    back = [t for t in rig.said()[seen:] if 'материал' in t.lower() or 'дебет' in t.lower()]
    assert back == [], f'the old plan came back over a newer answer: {back}'


def test_a_stopped_plan_stays_stopped_over_a_refused_remark(call):
    rig = call(**LIVE_RULES)
    plan(rig, asked=INERTIA, answer=TWO_NOTICE)
    before = rig.said()
    rig.c.max_auto_repeats = 0
    rig.pump(1.0)
    user_turn(rig, 'u1', 'Стоп')
    rig.pump(0.5)
    assert rig.c.state().get('paused') is True
    remark(rig, 'u2', 1)
    rig.pump(10.0)
    assert rig.c.state().get('paused') is True and rig.said() == before, rig.said()


def test_after_a_refusal_an_explicit_continue_brings_the_old_plan_back_and_only_then(call):
    rig = call(**LIVE_RULES)
    plan(rig, asked=INERTIA, answer=TWO_NOTICE)
    before = rig.said()
    rig.c.max_auto_repeats = 0
    rig.pump(32.0)
    remark(rig, 'u1', 1)
    rig.pump(5.0)
    assert rig.said() == before
    user_turn(rig, 'u2', 'Продолжай')
    rig.pump(3.0)
    assert len(rig.said()) > len(before), 'only the listener brings it back, and he did'


def test_a_new_question_asked_over_the_old_plan_is_not_lost(call):
    """PRT-4: the question that comes while the old portion waits still gets its job and its answer."""
    rig = call(**LIVE_RULES)
    plan(rig, asked=ACCOUNT, answer=MATERIALS)
    rig.pump(1.5)
    user_turn(rig, 'u1', AMORT)
    assert rig.fake.runs[1:]
    answered(rig, 1, AMORT_ANSWER)
    rig.pump(3.0)
    assert heard(rig, 'перенос стоимости')
