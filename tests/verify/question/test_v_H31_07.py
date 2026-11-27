"""V2 H31-07: «P4: „продолжайте“ returns the old unfinished answer when the new one is over» (scenes c05 and c06, step 12). The scenes say what is MEANT: the order is  ask (step 8) -> a clarification answered (step 10) ->
«стоп» (step 11) -> «продолжайте с того места, где остановились» (step 12, ``resumes: 8``): the portion that follows is of the answer of step 8, from where it stood. The title of the row says it the other way round
(the old answer returns when the new one is finished); the test follows the scene's expectation and the report names the ambiguity. Known on the base: ``test_w3_scenes`` has a strict xfail for the same defect at n2_d11 step 16 (restore from the first portion).

Real ControlledMedia (rig ``call``). Not run on the laptop.
"""
import pytest

from question_kit import LIVE_RULES, TICK, answered, call, heard, plan, user_turn      # noqa: F401 - call is the fixture

HOURS_Q = 'А в месяце двадцать два рабочих дня по восемь часов, сколько часов за месяц'
HOURS_A = 'За месяц получается сто семьдесят шесть часов. Это двадцать два дня по восемь часов. Считаем только рабочие дни.'
MEETINGS_Q = 'А зачем вообще нужны планёрки, ну, объясните, а то многие считают, что это потеря времени'
MEETINGS_A = 'Планёрки нужны, чтобы согласовать работу команды и быстро увидеть проблемы.'
RESUME = 'Всё, закончил, продолжайте, ну, с того места, где остановились'


def scene(rig):
    plan(rig, asked=HOURS_Q, answer=HOURS_A)
    rig.c.max_auto_repeats = 0
    rig.pump(0.5)
    first = rig.said()[0]
    user_turn(rig, 'u1', first.rstrip('.:,').lower())                 # step 9: the right repeat, the cursor goes on
    rig.pump(1.0)
    cursor = rig.c.state()['chunk_index']
    chunks = list(rig.c.state()['chunks'])
    user_turn(rig, 'u2', MEETINGS_Q)                                   # step 10
    answered(rig, 1, MEETINGS_A)
    rig.pump(1.0)
    user_turn(rig, 'u3', 'Стоп, подождите, минуточку, мне звонят по работе')      # step 11
    rig.pump(1.0)
    return cursor, chunks


def test_after_the_stop_the_resume_says_a_portion_of_the_answer_before_the_clarification(call):
    rig = call(**LIVE_RULES)
    cursor, chunks = scene(rig)
    before = len(rig.said())
    user_turn(rig, 'u4', RESUME)                                       # step 12
    rig.pump(3.0)
    new = rig.said()[before:]
    assert new, 'the listener asked to go on and heard nothing'
    assert not any('планёрки' in t.lower() for t in new), f'the side answer was said again: {new}'
    assert any(t.strip().lower() in {c.strip().lower() for c in chunks} for t in new), f'not a portion of the answer of step 8: {new}'


def test_the_resume_goes_on_from_the_cursor_not_from_the_first_portion(call):
    rig = call(**LIVE_RULES)
    cursor, chunks = scene(rig)
    assert cursor >= 1, 'precondition: the repeat moved the cursor'
    before = len(rig.said())
    user_turn(rig, 'u4', RESUME)
    rig.pump(3.0)
    new = rig.said()[before:]
    assert new and new[0].strip().lower() != chunks[0].strip().lower(), f'it began again from the first portion: {new}'


def test_without_the_resume_nothing_of_the_old_answer_is_said(call):
    rig = call(**LIVE_RULES)
    cursor, chunks = scene(rig)
    before = len(rig.said())
    rig.pump(30.0)
    assert rig.said()[before:] == [], 'a stopped plan speaks only at the listener\'s word'

import pytest as _pt_no_lead
pytestmark = _pt_no_lead.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)
