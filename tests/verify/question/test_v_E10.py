"""V2 E10: a late OLD answer, a repeat with a tail, a lowercase answer after a cut. The backlog row: «новые варианты сохраняют хвост и позицию; старые результаты не озвучиваются»; open: lowercase answers after a cut.

Real ControlledMedia, NativeMediaSocket and FastText (rig ``call``). Not run on the laptop: the verdict is the cloud's. A red test is a defect card for the family K (the judge) or A (the answer's revision).
"""
import pytest

import helpers_s6_state as S
from question_kit import ACCOUNT, AMORT, AMORT_ANSWER, INERTIA, LIVE_RULES, MATERIALS, TICK, answered, call, cloud, heard, job_text, plan, user_turn      # noqa: F401 - call is the fixture


def asked_old(rig):
    rig.w.feed(S.turn_created('u1', 'user', 'Что'))
    rig.w.feed(S.turn_done('u1', 'user', INERTIA))
    rig.pump(TICK)


def test_a_late_cloud_answer_of_the_old_question_after_the_new_answer_began_is_never_spoken(call):
    rig = call(**LIVE_RULES)
    asked_old(rig)
    user_turn(rig, 'u2', AMORT)
    rig.job_says(1, AMORT_ANSWER)
    rig.pump(TICK * 2)
    cloud(rig, 'a1', 'Инерция — свойство тела сохранять скорость.')
    rig.pump(2.0)
    assert not heard(rig, 'свойство тела'), rig.said()
    assert heard(rig, 'перенос стоимости')


def test_the_job_of_the_old_question_is_cut_by_the_new_one_and_its_late_text_says_nothing(call):
    rig = call(**LIVE_RULES)
    asked_old(rig)
    user_turn(rig, 'u2', AMORT)
    assert rig.fake.run(0).cancelled.is_set()
    rig.pump(2.0)
    assert not heard(rig, 'свойство тела')


def test_a_repeat_of_the_old_portion_glued_to_a_new_question_keeps_the_question_whole(call):
    rig = call(**LIVE_RULES)
    plan(rig, asked=ACCOUNT, answer=MATERIALS)
    rig.pump(1.0)
    first = rig.c.state()['chunks'][0].rstrip(':')
    user_turn(rig, 'u1', f'{first}. {AMORT}')
    assert job_text(rig, 1) == AMORT, 'the repeat is dropped, the words of the question stay whole'
    answered(rig, 1, AMORT_ANSWER)
    assert heard(rig, 'перенос стоимости')


@pytest.mark.parametrize('opening', ['Что', 'Как'], ids=['what', 'how'])
def test_the_first_cue_of_the_answer_after_a_cut_is_not_a_lowercase_tail_of_the_old_one(call, opening):
    """Open in the backlog: lowercase answers after a cut. The listener cuts the old answer with a new question; the first thing said after is a beginning (a capital or a digit), never a portion of the old plan."""
    rig = call(**LIVE_RULES)
    plan(rig, asked=ACCOUNT, answer=MATERIALS)
    old = {c.strip().lower() for c in rig.c.state()['chunks']}
    rig.pump(1.0)
    before = len(rig.said())
    user_turn(rig, 'u1', f'{opening} такое амортизация' if opening == 'Что' else 'Как считается амортизация')
    answered(rig, 1, AMORT_ANSWER)
    rig.pump(3.0)
    new = rig.said()[before:]
    assert new, 'the new answer is said'
    assert new[0].strip().lower() not in old, f'the old plan came back first: {new}'
    assert new[0][0].isupper() or new[0][0].isdigit(), f'the beginning of an answer in lower case: {new[0]!r}'
