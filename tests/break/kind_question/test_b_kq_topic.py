"""BREAK kind_question 8: the topic changes. An answer in play and another question; a return to the older answer; two questions in one breath; the jobs fail twice; the same question after the end of its answer.
Class of problem: К13 (the answer begins again), A2 of the stand (the older answer said for a newer question), «всегда отвечает» (never silent), К26. Real ControlledMedia, not run on the laptop."""
from break_kit import ACCOUNT, AMORT, AMORT_ANSWER, INERTIA, LIVE_RULES, MATERIALS, NOTICE, S, TICK, answered, asked, call, chunks_of, fails, heard, job_mark, job_text, plan, said_to_the_room, spoken_failures, user_turn    # noqa: F401,E501 - call is the fixture


def test_b21_a_new_topic_ends_the_old_plan_and_none_of_its_later_portions_is_said(call):
    rig = call(**LIVE_RULES)
    plan(rig, asked=ACCOUNT, answer=MATERIALS)
    old = chunks_of(rig)
    rig.pump(0.5)
    asked(rig, AMORT, uid='u1')
    answered(rig, 1, AMORT_ANSWER)
    began = len(rig.said())
    rig.pump(30.0)
    assert old[1] not in rig.said(), rig.said()
    assert not any(text in old for text in rig.said()[began:]), 'the old answer came back into the new one'
    assert heard(rig, 'Амортизация')


def test_b22_a_return_to_the_older_answer_says_its_portion_not_the_newer_one(call):
    rig = call(**LIVE_RULES)
    plan(rig, asked=ACCOUNT, answer=MATERIALS)
    old = chunks_of(rig)
    rig.pump(0.5)
    asked(rig, AMORT, uid='u1')
    answered(rig, 1, AMORT_ANSWER)
    rig.pump(1.0)
    said_to_the_room(rig, 'u2', 'Вернись к прошлому ответу, про материалы')
    job_mark(rig, 2, '[продолжай]')
    rig.pump(TICK * 2)
    assert rig.said()[-1] in old, rig.said()


def test_b23_both_jobs_of_a_question_fail_and_the_call_is_not_left_silent(call):
    rig = call(**LIVE_RULES)
    asked(rig, ACCOUNT, uid='u1')
    fails(rig, 0)
    if rig.fake.runs[1:]:
        fails(rig, 1)
    rig.pump(15.0)
    assert rig.said() or spoken_failures(rig), 'the question failed twice and nothing was said in 15 s'


def test_b24_the_same_question_after_the_end_of_its_answer_is_answered_again(call):
    rig = call(**LIVE_RULES)
    plan(rig, asked=INERTIA, answer=NOTICE)
    rig.w.feed(S.turn_done('u1', 'user', NOTICE))
    rig.pump(TICK * 3)
    assert rig.c.state()['completed'] is True
    asked(rig, INERTIA, uid='u2')
    rig.pump(2.0)
    if rig.fake.runs[1:]:
        answered(rig, 1, NOTICE)
    rig.pump(2.0)
    assert rig.said().count(NOTICE) >= 2, rig.said()


def test_b25_two_questions_in_one_breath_reach_the_job_together(call):
    rig = call(**LIVE_RULES)
    user_turn(rig, 'u1', 'Что такое амортизация, и когда платить налог')
    rig.pump(1.0)
    assert rig.fake.runs, 'the double question never reached a job'
    text = job_text(rig, 0).lower()
    assert 'амортизац' in text and 'налог' in text, text
