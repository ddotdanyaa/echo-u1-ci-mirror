"""V2 E44: a dispute and a doubt reach the job («Нет, год вы назвали неверный», «<порция>, ты уверена»); «ты уверена» after a right answer gives a short confirmation, not «—» (1 of 8); a wrong year «1988» and the correction «888».

Real ControlledMedia (rig ``call``): a table of neighbouring phrases both ways (the doubt/dispute forms reach the job; a right repeat does not), the whole order of the call of 20:34 in miniature. Not run on the laptop.
"""
import pytest

from question_kit import BAPTISM, LIVE_RULES, RIGHT, answered, call, heard, job_text, plan, user_turn      # noqa: F401 - call is the fixture

DOUBT = [
    'Ты уверена',
    'Ты уверена, что в 988 году',
    'Крещение Руси в 988 году, ты уверена',
    'Точно в 988',
    'А ты не ошибаешься',
]
DISPUTE = [
    'Нет, год вы назвали неверный',
    'Это неверно',
    'Нет, это неправильно, был не тысяча девятьсот восемьдесят восьмой',
    'Нет, в 988, а не в 1988',
]


@pytest.mark.parametrize('said', DOUBT + DISPUTE, ids=range(len(DOUBT + DISPUTE)))
def test_a_doubt_or_a_dispute_after_an_answer_goes_to_the_job_and_the_cursor_stands(call, said):
    rig = call(**LIVE_RULES)
    plan(rig, asked=BAPTISM, answer='Крещение Руси было в 988 году. Это князь Владимир.')
    cursor = rig.c.state().get('chunk_index')
    rig.pump(1.0)
    user_turn(rig, 'u1', said)
    assert rig.fake.runs[1:], 'the job heard the doubt'
    assert rig.c.state().get('chunk_index') == cursor


def test_are_you_sure_after_a_right_answer_gets_a_short_confirmation_not_a_dash(call):
    rig = call(**LIVE_RULES)
    plan(rig, asked=BAPTISM, answer=RIGHT)
    before = len(rig.said())
    rig.pump(1.0)
    user_turn(rig, 'u1', 'Ты уверена')
    rig.job_says(1, '—')                         # the brain's own «no question» sign: the exact failure of the backlog
    rig.job_ends(1)
    rig.pump(3.0)
    new = rig.said()[before:]
    assert new, 'the listener doubted aloud and got silence (1 of 8 in the table of the backlog)'
    assert any(w in ' '.join(new) for w in ('988', 'Да', 'да', 'Верно', 'верно')), new


def test_the_wrong_year_is_corrected_by_the_listener_and_the_corrected_answer_is_said_once(call):
    """The call of 20:34, A3: the answer said «1988»; the listener corrects with «888»/«988»; the job answers the correction; the wrong year does not come back."""
    rig = call(**LIVE_RULES)
    plan(rig, asked=BAPTISM, answer='Крещение Руси было в 1988 году.')
    rig.pump(1.0)
    user_turn(rig, 'u1', 'Нет, не в тысяча девятьсот восемьдесят восьмом, а в девятьсот восемьдесят восьмом')
    assert rig.fake.runs[1:], 'the correction reached the job'
    answered(rig, 1, 'Верно: крещение Руси было в 988 году.')
    rig.pump(4.0)
    said = ' '.join(rig.said())
    assert '988' in said and said.count('1988') <= 1, said


def test_the_right_repeat_is_no_dispute_and_asks_nobody(call):
    """The neighbour the other way: what is a repeat of the waiting portion moves the cursor by one and does not become a question for the job."""
    rig = call(**LIVE_RULES)
    plan(rig, asked=BAPTISM, answer='Крещение Руси было в 988 году. Это князь Владимир.')
    index, portion = rig.c.state()['chunk_index'], rig.said()[0]
    rig.pump(0.5)
    user_turn(rig, 'u1', portion.rstrip('.:,').lower())
    rig.pump(1.0)
    assert rig.c.state()['chunk_index'] == index + 1, 'a right repeat is a step on'
    assert not rig.fake.runs[1:], 'a repeat asks the job nothing'
