"""V1a E08: «a remark to somebody else gets sound» (the scene n1_02 step 18, class 28), on the real ControlledMedia (rig ``call``: real wire, real controller, scripted ear/job/cloud on the world's clock).

Verdict of the author, by reading, NOT by a run (nothing is run on the laptop): H2 of 5 Nov took «Ну наконец-то» out of c14 and the judge rows of ``utterance_judge`` hold a remark to a person; what is still open by the backlog
is the refusal of the job (the question of two others then reaches the cloud). The three tests split exactly that: the job answers (1), the job fails and the cloud answers (2), the same words said to the listener (3, the control).
A red test here is a defect card for the family K (``lane_reports/rules/DEFECT_CARD.md``), not a thing to switch off.
"""
from kind_a_kit import (LIVE_RULES, JOB_TERM, S18_ASK, S18_REPLY, TERM_ANSWER, TERM_QUESTION, TICK, cloud, fails, heard, mark, only_the_plan_sounds, plan, said_to_the_room, sounded_since, spoken_failures,
                        stranger_pair)
from test_h3_tempo import call      # noqa: F401 - the fixture
from echo_sync.textutil import normalize
import helpers_s6_state as S


def test_two_others_say_the_words_of_a_question_and_nothing_new_sounds_while_the_job_answers(call):
    """n1_02 s18: the plan waits; «Слушай, а какой максимум…» (a second voice), 0.9 s, «Да откуда я знаю, у Светы спроси…» (a third). The job on the first piece answers; nothing of that answer is said, no new plan, no search."""
    rig = call(**LIVE_RULES)
    plan(rig, asked=TERM_QUESTION, answer=TERM_ANSWER)
    before = mark(rig)
    stranger_pair(rig)
    rig.pump(8.0)
    assert not spoken_failures(rig), 'nothing is said about a failure either'
    assert 'шест' not in heard(sounded_since(rig, before)), f'the job\'s answer to the others was said: {sounded_since(rig, before)}'
    assert only_the_plan_sounds(rig, before) == [], f'a cue that is not a portion of the plan: {only_the_plan_sounds(rig, before)}'
    assert mark(rig)['lookups'] == before['lookups'], 'the others\' words went to the public search'
    after = rig.w.snapshot()
    assert (after['revision'], after['index']) == (before['revision'], before['index']), 'the plan and the cursor stay where they were'


def test_the_job_refuses_twice_and_the_cloud_answers_the_others_and_nothing_of_it_is_said(call):
    """The residual of the backlog (A01 §1, H6 R5): at the job's refusal the remark passed. The job on the first piece fails, its one more fails too, the cloud (which answers every user turn) answers: the answer is not said."""
    rig = call(**LIVE_RULES)
    plan(rig, asked=TERM_QUESTION, answer=TERM_ANSWER)
    before = mark(rig)
    since = len(rig.fake.runs)
    said_to_the_room(rig, 'x1', S18_ASK)
    rig.pump(0.3)
    for n in range(since, len(rig.fake.runs)):
        if not rig.fake.runs[n].ended.is_set():
            fails(rig, n)
    if len(rig.fake.runs) > since + 1 and not rig.fake.runs[since + 1].ended.is_set():
        fails(rig, since + 1)
    rig.pump(0.5)
    said_to_the_room(rig, 'x2', S18_REPLY)
    cloud(rig, 'a1', 'Максимум полгода.')
    rig.pump(8.0)
    assert 'полгода' not in heard(sounded_since(rig, before)), f'the cloud\'s answer to the others was said: {sounded_since(rig, before)}'
    assert mark(rig)['lookups'] == before['lookups']


def test_control_the_same_words_said_to_the_listener_alone_are_answered(call):
    """The control: a question that nobody answers or sends elsewhere is the listener's, and the job's answer is said (so the silence of the first test is a decision and not a dead rig)."""
    rig = call(**LIVE_RULES)
    rig.w.feed(S.turn_created('u1', 'user', 'Какой'))
    rig.w.feed(S.turn_done('u1', 'user', TERM_QUESTION))
    rig.pump(TICK)
    assert rig.fake.runs, 'a job is asked on a plain question'
    rig.job_says(0, JOB_TERM)
    rig.job_ends(0)
    rig.pump(1.0)
    assert 'шест' in normalize(' '.join(rig.said())), rig.said()

import pytest as _pt_no_lead
pytestmark = _pt_no_lead.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)
