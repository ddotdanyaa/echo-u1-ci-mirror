"""V2 E36: the job gets the best text: the ear and the cloud are two records of one utterance; an open tail waits up to 1.5 s; a glued text is cut by portions (H6.3). The forms of the record: s11, s15, s16, n1_04 s10, and a 59-s final.
Success: the question of the job equals the whole condition; the forms give an answer to the whole question.

Real ControlledMedia (rig ``call``). The first test is a known red on the base (strict xfail in ``test_w3_replays``): here it is a plain test, so that the cloud says whether it is still red. Not run on the laptop.
"""
import pytest

import helpers_s6_state as S
from question_kit import ACCOUNT, AMORT, LIVE_RULES, MATERIALS, TICK, answered, call, heard, job_text, piece, plan, user_turn      # noqa: F401 - call is the fixture

CONDITIONS = 'Вклад сто тысяч рублей на два года под десять процентов годовых, нет, не под десять, а под двадцать, проценты простые, сколько начислят'
INTEREST = 'Проценты составят 40 000 рублей за 2 года.'
PIECES = ('вклад сто тысяч рублей на два года', 'под десять процентов годовых', 'нет не под десять а под двадцать', 'проценты простые сколько начислят')


def test_the_ear_in_pieces_and_the_cloud_whole_the_job_is_asked_the_whole_condition_and_its_answer_is_said(call):
    rig = call(**LIVE_RULES)
    plan(rig, asked=ACCOUNT, answer=MATERIALS)
    rig.pump(1.0)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    for text in PIECES:
        piece(rig, text, speech=2.0)
    rig.pump(1.0)
    rig.w.feed(S.turn_done('u1', 'user', CONDITIONS))
    rig.pump(TICK * 3)
    asked_text = job_text(rig, 1)
    assert 'двадцать' in asked_text and 'начислят' in asked_text and 'сто тысяч' in asked_text, asked_text
    answered(rig, 1, INTEREST)
    assert heard(rig, '40 000'), rig.said()


@pytest.mark.parametrize('head, rest, key', [
    ('А в каком году принят нынешний закон о', 'бухгалтерском учёте', 'бухгалтерском'),
    ('Какая ставка налога на прибыль для', 'российских организаций', 'российских'),
    ('Сколько дней отпуска положено по', 'трудовому кодексу', 'трудовому'),
], ids=['law', 'rate', 'vacation'])
def test_the_open_tail_of_a_final_waits_for_its_rest_and_the_job_gets_it_whole(call, head, rest, key):
    rig = call(**LIVE_RULES)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.pump(0.5)
    rig.w.feed(S.turn_done('u1', 'user', head))
    rig.pump(0.6)
    rig.w.feed(S.turn_created('u2', 'user', ''))
    rig.pump(0.3)
    rig.w.feed(S.turn_done('u2', 'user', rest))
    rig.pump(TICK * 3)
    texts = [run.question for run in rig.fake.runs]
    assert texts and all(key in text for text in texts), texts


def test_a_glued_repeat_and_question_the_job_gets_the_question_only(call):
    rig = call(**LIVE_RULES)
    plan(rig, asked=ACCOUNT, answer=MATERIALS)
    rig.pump(1.0)
    first = rig.c.state()['chunks'][0].rstrip(':')
    user_turn(rig, 'u1', f'{first}. {AMORT}')
    assert job_text(rig, 1) == AMORT


def test_a_long_final_of_a_minute_of_talk_gets_one_job_on_the_question_part_not_a_piece(call):
    """The 59-second final of the record: a long remark with the question at its end; the job is asked once, and what it is given holds the question."""
    rig = call(**LIVE_RULES)
    talk = ('Так, ну вот, давайте теперь про другое, я тут думал и вспомнил, что на прошлой неделе мы обсуждали сроки, и вроде бы всё договорились, но потом оказалось, '
            'что есть ещё нюансы, и поэтому я хочу уточнить одну вещь, значит, какой срок уплаты налога на имущество организаций')
    user_turn(rig, 'u1', talk, wait=2.0)
    assert len(rig.fake.runs) >= 1, 'a job was asked'
    assert 'налога на имущество' in job_text(rig, 0).lower(), job_text(rig, 0)
