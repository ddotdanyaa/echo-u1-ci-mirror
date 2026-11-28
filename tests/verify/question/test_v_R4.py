"""V2 R4 (= H31-06, H31-07): an old unfinished answer comes back; the history keeps the TAIL of the question. Scenes c05 and c06 (step 12), d06. The check of the backlog: keep the original question of an answer apart from the history of remarks.

The order of events of the scenes, with their own words, through the real ControlledMedia (rig ``call``). The scenes of the corpus themselves (``cloud_context``) are not in this tree; the text here is copied from the corpus' steps. Not run on the laptop.
"""
import pytest

import helpers_s6_state as S
from question_kit import LIVE_RULES, TICK, answered, call, entry_of, heard, job_input, job_text, plan, user_turn      # noqa: F401 - call is the fixture

HOURS_Q = 'А в месяце двадцать два рабочих дня по восемь часов, сколько часов за месяц'
HOURS_A = 'За месяц получается сто семьдесят шесть часов. Это двадцать два дня по восемь часов. Считаем только рабочие дни.'
MEETINGS_Q = 'А зачем вообще нужны планёрки, ну, объясните, а то многие считают, что это потеря времени'
MEETINGS_A = 'Планёрки нужны, чтобы согласовать работу команды и быстро увидеть проблемы.'
PLAN_WORDS = ('сто семьдесят шесть', 'двадцать два дня', 'рабочие дни')


def old_plan_said(rig, since):
    return [t for t in rig.said()[since:] if any(w in t.lower() for w in PLAN_WORDS)]


def test_the_old_answer_does_not_come_back_by_itself_when_the_new_one_is_over(call):
    """c05 step 10 -> 12 without the stop: after the clarification is answered, the answer before it waits; the timers and the silence do not bring it back (max_auto_repeats off)."""
    rig = call(**LIVE_RULES)
    plan(rig, asked=HOURS_Q, answer=HOURS_A)
    rig.c.max_auto_repeats = 0
    rig.pump(1.0)
    user_turn(rig, 'u1', MEETINGS_Q)
    answered(rig, 1, MEETINGS_A)
    rig.pump(1.0)
    since = len(rig.said())
    rig.pump(40.0)
    assert old_plan_said(rig, since) == [], f'the unfinished old answer came back by itself: {rig.said()[since:]}'


def test_the_history_keeps_the_whole_question_of_an_answer_not_its_tail(call):
    rig = call(**LIVE_RULES)
    plan(rig, asked=HOURS_Q, answer=HOURS_A)
    rig.pump(1.0)
    entry = entry_of(rig, 'рабочих дня')
    assert entry is not None, [e.get('question') for e in rig.c.state()['history']]
    assert 'сколько часов за месяц' in entry['question'] and 'двадцать два' in entry['question']


def test_a_short_remark_in_the_form_of_a_question_does_not_replace_the_question_of_the_answer_in_play(call):
    """The remark is declined by the job: the answer in play keeps ITS question in the history, the remark's words are not the question of the plan."""
    rig = call(**LIVE_RULES)
    plan(rig, asked=HOURS_Q, answer=HOURS_A)
    rig.c.max_auto_repeats = 0
    rig.pump(1.0)
    # W13 item 9: a question about the course of the event with a list in it («... вопрос по списку») is no question (process_question, no job); the bare form goes to the job, which declines it (tests/test_h6.py REMARK)
    S_remark = 'Какой следующий вопрос нам задать сейчас?'
    user_turn(rig, 'u1', S_remark)
    rig.job_says(1, '—')
    rig.job_ends(1)
    rig.pump(2.0)
    entry = entry_of(rig, 'рабочих дня')
    assert entry is not None and 'следующий вопрос' not in entry['question'], entry
