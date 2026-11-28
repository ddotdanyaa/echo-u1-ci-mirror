"""V2 E44: a dispute and a doubt reach the job («Нет, год вы назвали неверный», «<порция>, ты уверена»); «ты уверена» after a right answer gives a short confirmation, not «—» (1 of 8); a wrong year «1988» and the correction «888».

Real ControlledMedia (rig ``call``): a table of neighbouring phrases both ways (the doubt/dispute forms reach the job; a right repeat does not), the whole order of the call of 20:34 in miniature. Not run on the laptop.
"""
import pytest

from echo_sync.cm_base import FAST_TAIL_SECONDS, probe
from echo_sync.textutil import norm_words
from echo_sync.user_intents import disagreement
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


def retired_by_the_classifier(said):
    """The product's rule for «the answer was called wrong»: classifier.py 1894-1910 (step 5): ``disagreement`` of the words (not a question: no '?') is a CORRECTION («explicit_answer_repair» with
    what is wrong, «answer_disagreement» bare): the answer is retired and the job told. Every other doubt or dispute is the dispute of the portion (``_disputes``): the cursor stands."""
    return disagreement(' '.join(norm_words(said))) is not None and not said.rstrip().endswith('?')


@pytest.mark.parametrize('said', DOUBT + DISPUTE, ids=range(len(DOUBT + DISPUTE)))
def test_a_doubt_or_a_dispute_after_an_answer_goes_to_the_job_and_the_cursor_stands(call, said):
    rig = call(**LIVE_RULES)
    plan(rig, asked=BAPTISM, answer='Крещение Руси было в 988 году. Это князь Владимир.')
    cursor = rig.c.state().get('chunk_index')
    rig.pump(1.0)
    user_turn(rig, 'u1', said)
    waited = 0.0                                 # the job is asked within FAST_TAIL_SECONDS of the final (a final that stops on a number waits that long for it to grow, cm_answer ``_fast_tail_waits``; the dispute row hands the rest on at once): the time is asserted, not a fixed pump
    while not rig.fake.runs[1:] and waited <= FAST_TAIL_SECONDS + 0.5:
        rig.pump(0.25)
        waited += 0.25
    assert rig.fake.runs[1:], f'the job heard the doubt within {waited} s'
    if retired_by_the_classifier(said):          # the answer is retired into revision 2 (the plan is empty until the job answers) and the job runs
        assert rig.c.state().get('revision') == 2, 'the answer was retired by the correction'
    else:                                        # the portion is kept: same revision, same cursor
        assert rig.c.state().get('revision') == 1
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
    state = rig.c.state()
    index, portion = state['chunk_index'], probe('waiting_portion', state=state).value      # the portion that waits (the lead cue, cm_answer ``_lead_passed``, has moved the plan on to the substance)
    assert portion and portion in rig.said(), 'the waiting portion is the one said last'
    rig.pump(0.5)
    user_turn(rig, 'u1', portion.rstrip('.:,').lower())
    rig.pump(1.0)
    assert rig.c.state()['chunk_index'] == index + 1, 'a right repeat is a step on'
    assert not rig.fake.runs[1:], 'a repeat asks the job nothing'


def test_a_doubt_after_the_answer_is_fully_said_is_never_silence(call):
    """No portion waits (the listener repeated the only one), the answer is still in play (``fast_in_play``, PLAYED_FRESH_S): «Ты уверена, что в 988 году» is no dispute of a portion, so it stays a question: the job is asked or a short confirmation (H6 item 7, ``_doubt_held``) is said."""
    rig = call(**LIVE_RULES)
    plan(rig, asked=BAPTISM, answer=RIGHT)
    portion = probe('waiting_portion', state=rig.c.state()).value
    rig.pump(0.5)
    user_turn(rig, 'u1', portion.rstrip('.:,').lower())
    rig.pump(1.0)
    assert probe('waiting_portion', state=rig.c.state()).value is None, 'nothing waits: the answer is said to its end'
    assert rig.c.fast_in_play(), 'the answer is still in play'
    before, said_before = len(rig.fake.runs), len(rig.said())
    user_turn(rig, 'u2', 'Ты уверена, что в 988 году')
    waited = 0.0
    while len(rig.fake.runs) == before and len(rig.said()) == said_before and waited <= FAST_TAIL_SECONDS + 0.5:
        rig.pump(0.25)
        waited += 0.25
    assert len(rig.fake.runs) > before or len(rig.said()) > said_before, 'the doubt got silence'
