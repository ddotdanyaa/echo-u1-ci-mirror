"""BREAK kind_question 7: numbers and a very long question. «Счёт 58» in four forms; a portion repeated with a wrong number; a long task said in pieces with a correction in the middle of it; a long speech over a plan in play.
Class of problem: К11 (a question with a number waits for a second witness), К14 (a new question taken for an attempt), К2 (garbage and length), n1_01 (any speech with content stops the timer until its final is judged). Real ControlledMedia, not run on the laptop."""
import pytest

from break_kit import ACCOUNT, INERTIA, INTEREST, LIVE_RULES, MATERIALS, NOTICE, TASK, answered, asked, call, chunks_of, heard, index_of, job_text, piece, plan, user_turn    # noqa: F401 - call is the fixture

NUMBERED = ['Счёт 58', 'Какой счёт пятьдесят восьмой', 'Статья 19 налогового кодекса о чём', 'Сколько будет 7 умножить на 8']


@pytest.mark.parametrize('said', NUMBERED, ids=range(len(NUMBERED)))
def test_b18_a_question_with_a_number_is_one_job_and_one_answer(call, said):
    rig = call(**LIVE_RULES)
    asked(rig, said, uid='u1')
    rig.pump(1.5)
    local = {'Счёт 58': 'Счёт 58 — финансовые вложения.', 'Какой счёт пятьдесят восьмой': 'Счёт 58 — финансовые вложения.',
             'Статья 19 налогового кодекса о чём': 'Статья 19 Налогового кодекса — налогоплательщики,', 'Сколько будет 7 умножить на 8': 'Пятьдесят шесть.'}
    if not rig.fake.runs:    # the code answers this itself (instant.py: chart of accounts, laws, sums): no job; the silent listener hears the portion again, never another text
        assert set(rig.said()) == {local[said]}, rig.said()
        rig.pump(1.0)
        assert set(rig.said()) == {local[said]}, rig.said()
        return
    assert len(rig.fake.runs) == 1, [r.question for r in rig.fake.runs]
    answered(rig, 0, 'Ответ про этот номер.')
    rig.pump(1.0)
    assert rig.said() == ['Ответ про этот номер.'], rig.said()


def test_b19_a_long_task_said_in_pieces_with_a_correction_reaches_the_job_whole_and_is_answered_once(call):
    rig = call(**LIVE_RULES)
    for text in TASK.split(', '):
        piece(rig, text, speech=1.5)
    asked(rig, TASK, uid='u1')
    rig.pump(1.0)
    assert rig.said() == [], f'something was said before the job: {rig.said()}'
    last = len(rig.fake.runs) - 1
    assert last >= 0 and 'начислят' in job_text(rig, last) and 'двадцать' in job_text(rig, last), job_text(rig, last)
    answered(rig, last, INTEREST)
    rig.pump(1.0)
    assert rig.said() == [INTEREST], rig.said()


def test_b20_a_long_speech_in_pieces_over_a_plan_brings_no_replay_into_it(call):
    rig = call(**LIVE_RULES)
    plan(rig, asked=INERTIA, answer=NOTICE)
    rig.pump(0.5)
    for text in ['Подожди, я хочу сначала понять', 'вот эту часть про срок', 'потому что у нас в договоре', 'написано немного иначе']:
        piece(rig, text, speech=1.5, lag=0.1, gap=0.3)
    assert rig.said() == [NOTICE], f'the portion was said into his speech: {rig.said()}'


def test_b26_a_portion_repeated_with_a_wrong_number_does_not_move_the_cursor(call):
    rig = call(**LIVE_RULES)
    plan(rig, asked=ACCOUNT, answer=MATERIALS)
    first = chunks_of(rig)[0]
    rig.pump(1.0)
    user_turn(rig, 'u1', first.rstrip(':').lower().replace('10 000', '100 000'))
    rig.pump(8.0)
    assert index_of(rig) == 0, 'a wrong number was accepted as the repeat of the portion'
    assert rig.said()[-1] == first

import pytest as _pt_no_lead
pytestmark = _pt_no_lead.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)
