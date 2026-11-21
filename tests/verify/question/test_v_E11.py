"""V2 E11: a late repeat of the old portion with a NEW question after it: the question is not lost (at worst postponed). Rule 5 of G3 threw the question away; after H2 the state was unknown.

The order of events of the call through the real ControlledMedia (rig ``call``), not a table of phrases: the repeat and the question in one utterance, in two utterances, and over a timer's repeat. Not run on the laptop.
"""
import pytest

import helpers_s6_state as S
from question_kit import ACCOUNT, AMORT, AMORT_ANSWER, LIVE_RULES, MATERIALS, TICK, answered, call, heard, job_text, plan, user_turn      # noqa: F401 - call is the fixture
from echo_sync.timer_policy import TEMPO_REPEAT_SECONDS


def test_a_late_repeat_and_the_question_after_it_in_one_utterance(call):
    rig = call(**LIVE_RULES)
    plan(rig, asked=ACCOUNT, answer=MATERIALS)
    rig.pump(1.0)
    first = rig.c.state()['chunks'][0].rstrip(':')
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.pump(0.3)
    rig.w.feed(S.turn_done('u1', 'user', f'{first.lower()}. {AMORT}'))
    rig.pump(TICK * 3)
    assert job_text(rig, 1) == AMORT, 'the new question is not thrown away by the repeat before it'
    answered(rig, 1, AMORT_ANSWER)
    assert heard(rig, 'перенос стоимости')


def test_the_repeat_and_the_question_in_two_utterances_a_breath_apart(call):
    rig = call(**LIVE_RULES)
    plan(rig, asked=ACCOUNT, answer=MATERIALS)
    rig.pump(1.0)
    first = rig.c.state()['chunks'][0].rstrip(':')
    user_turn(rig, 'u1', first.lower(), wait=0.3)
    rig.pump(0.4)
    user_turn(rig, 'u2', AMORT)
    runs = [n for n in range(len(rig.fake.runs)) if AMORT in rig.fake.runs[n].question]
    assert runs, f'no job was asked the new question: {[r.question for r in rig.fake.runs]}'
    answered(rig, runs[-1], AMORT_ANSWER)
    assert heard(rig, 'перенос стоимости')


def test_a_new_question_over_the_timers_repeat_of_the_old_portion_is_answered(call):
    rig = call(**LIVE_RULES)
    plan(rig, asked=ACCOUNT, answer=MATERIALS)
    rig.pump(TEMPO_REPEAT_SECONDS - 0.2)                 # the timer is about to repeat the old portion
    user_turn(rig, 'u1', AMORT, wait=0.3)
    rig.pump(0.2)
    assert job_text(rig, 1) == AMORT
    answered(rig, 1, AMORT_ANSWER)
    rig.pump(3.0)
    assert heard(rig, 'перенос стоимости')
    assert rig.said().count(rig.said()[0]) <= 2, 'the old portion is not hammered over the question'
