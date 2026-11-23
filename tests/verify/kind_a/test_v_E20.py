"""V1a E20: the roles of a conversation (the speaker, the listener who asks, a colleague, the audience, a person who breaks in) - the table «family -> scene -> result» that the backlog says is missing, as scenes on the real
ControlledMedia (rig ``call``). One row = one role, one scene, one result. The rows with a role that must be silent hold the plan, the cursor, the jobs and the public search at their marks; the row of the one who is asked is the control.
Not run on the laptop. A red row is a defect card for the family K (a role the judge does not know).
"""
import pytest

import helpers_s6_state as S

from kind_a_kit import JOB_TERM, LIVE_RULES, TERM_ANSWER, TERM_QUESTION, TICK, let_jobs_decline, mark, only_the_plan_sounds, plan, said_to_the_room, spoken_failures
from test_h3_tempo import call      # noqa: F401 - the fixture

ROLES = [
    ('speaker_own_text', 'Итак, начнём. Сегодня я расскажу про налоги организаций и про то, как мы сдаём отчётность в этом году.'),
    ('colleague_by_name', 'Миша, ты зарядку мою не видел?'),
    ('colleague_about_his_business', 'А вы во сколько завтра выезжаете?'),
    ('audience_invited_to_ask', 'Ну что, давайте задавайте любой вопрос'),
    ('breaks_in_to_the_speaker', 'Нет, ты не прав, всё было по-другому, я там был.'),
    ('private_chat_aside', 'Короче, мы потом пошли в кино, а там все места заняты были.'),
]


@pytest.mark.parametrize('role, said', ROLES, ids=[r[0] for r in ROLES])
def test_a_role_that_is_not_asking_the_listener_leaves_the_call_where_it_was(call, role, said):
    rig = call(**LIVE_RULES)
    plan(rig, asked=TERM_QUESTION, answer=TERM_ANSWER)
    before = mark(rig)
    said_to_the_room(rig, 'r1', said)
    rig.pump(TICK)
    let_jobs_decline(rig, before['runs'])
    rig.pump(6.0)
    assert not spoken_failures(rig), role
    assert only_the_plan_sounds(rig, before) == [], (role, only_the_plan_sounds(rig, before))
    assert mark(rig)['lookups'] == before['lookups'], role
    after = rig.w.snapshot()
    assert (after['revision'], after['index']) == (before['revision'], before['index']), role


def test_the_role_that_asks_the_listener_is_answered(call):
    """The control row: the listener asks, the job answers, the answer sounds."""
    rig = call(**LIVE_RULES)
    rig.w.feed(S.turn_created('u1', 'user', 'Какой'))
    rig.w.feed(S.turn_done('u1', 'user', TERM_QUESTION))
    rig.pump(TICK)
    rig.job_says(0, JOB_TERM)
    rig.job_ends(0)
    rig.pump(1.0)
    assert any('шест' in text.lower() for text in rig.said()), rig.said()
