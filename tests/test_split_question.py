"""g14-split (the owner's calls of 06.11): the ear cut one question in two at a short pause: «так характеристика счёт» | «пятьдесят два», «а что за указание банка россии у вас по» | «один из стороны четырнадцатого».
The pieces of a pause under 1 s are one question: the job, the bank and the route read the joined text, its numbers and «не» as said. Was: the pieces were joined by «. » (c16), so «так характеристика счёт. пятьдесят два»
read as no question (silent, not_a_question) and nothing was prepared, and «… у вас по. один из стороны четырнадцатого» was cut by ``question_part`` to the bare tail. The logic only: nothing here is a measurement of a call."""
import pytest

import helpers_s6_state as S
from echo_sync.instant import Instant
from test_c16_ear_job import FLAGS, breath, jobs
from test_h1_fast_text import settled       # noqa: F401
from test_h3_tempo import TICK, call       # noqa: F401 - the fixture

SPLITS = [
    (['так характеристика счёт', 'пятьдесят два'], 'пятьдесят два'),
    (['а что за указание банка россии у вас по', 'один из стороны четырнадцатого'], 'указание банка россии'),
]


@pytest.mark.parametrize('pieces,kept', SPLITS)
@pytest.mark.parametrize('gap', [0.3, 0.6, 0.85])
def test_the_pieces_of_a_short_pause_go_to_the_job_as_one_question(call, pieces, kept, gap):
    rig = call(**FLAGS)
    breath(rig, pieces, gap=gap)
    asked = jobs(rig)
    assert asked and kept in asked[-1] and pieces[0].split()[-1] in asked[-1] and pieces[1].split()[-1] in asked[-1], asked


BANK = [{'q': 'Что такое счёт 50?', 'alt': ['Счёт 50 это что'], 'answer': 'Счёт 50 это касса: активный счёт для наличных денег.'},
        {'q': 'Что такое счёт 52?', 'alt': ['Счёт 52 это что', 'Характеристика счёта 52'], 'answer': 'Счёт 52 это валютные счета: активный счёт для валюты в банке.'},
        {'q': 'Какой нормативный акт регулирует кассовые операции?', 'alt': ['Что за указание Банка России по кассовым операциям'],
         'answer': 'Указание Банка России 3210-У от 11 марта 2014 года о порядке ведения кассовых операций.'}]


def banked(call, pieces, final, gap):
    rig = call(**FLAGS, instant='on')
    rig.c.instant = Instant(BANK)
    breath(rig, pieces, gap=gap)
    rig.pump(0.3)
    rig.w.feed(S.turn_done('u1', 'user', final))
    rig.pump(3.0)
    return rig


@pytest.mark.parametrize('gap', [0.3, 0.6, 0.85, 0.95])
@pytest.mark.parametrize('pieces,final', [(['так что такое счёт', 'пятьдесят два'], 'Так, что такое счёт 52?'),
                                          (['что такое счёт пятьдесят', 'два'], 'Что такое счёт 52?'),
                                          (['так характеристика счёта', 'пятьдесят два'], 'Так, характеристика счёта 52.')])
def test_the_bank_answers_the_joined_number_not_the_piece(call, pieces, final, gap):
    """«пятьдесят» | «два» is 52, never 50: no cue of the first piece's number is said, the bank's answer of the whole is."""
    rig = banked(call, pieces, final, gap)
    said = ' '.join(rig.said())
    assert 'касса' not in said and 'Счёт 50' not in said, rig.said()
    assert 'валют' in said, (rig.said(), jobs(rig))


@pytest.mark.parametrize('gap', [0.3, 0.6, 0.85])
@pytest.mark.parametrize('pieces,want,never', [(['когда можно', 'не платить алименты'], 'по соглашению', 'В любое время'),
                                               (['когда можно не платить', 'алименты'], 'по соглашению', 'В любое время'),
                                               (['какая ставка налога на прибыль', 'организаций'], 'двадцать пять', 'двадцать процентов')])
def test_the_not_and_the_words_of_the_rest_are_kept(call, pieces, want, never, gap):
    import helpers_w5_instant as fx
    rig = call(**FLAGS, instant='on')
    rig.c.instant = Instant(fx.bank())
    breath(rig, pieces, gap=gap)
    rig.pump(0.3)
    rig.w.feed(S.turn_done('u1', 'user', ' '.join(pieces).capitalize() + '?'))
    rig.pump(3.0)
    said = ' '.join(rig.said())
    assert never not in said and want in said, (rig.said(), jobs(rig))


# ---- the cloud cut it: its finals --------------------------------------------------------------------------------------------------------------

from helpers_w1f import Wire     # noqa: E402


@pytest.mark.parametrize('flags', [{}, {'fast_text': 'on'}])
@pytest.mark.parametrize('gap', [0.2, 0.6, 0.9])
def test_the_clouds_two_finals_of_one_number_are_one_question(tmp_path, flags, gap):
    """The cloud closed the turn at «пятьдесят»: «Счёт 50 — касса.» was said at once, then «Счёт 52». The base's answer of a number that can still grow waits SPLIT_JOIN_SECONDS."""
    w = Wire(tmp_path, **flags)
    w.user('u1', 'Так, что такое счёт пятьдесят', 10.0, 12.0)
    w.user('u2', ' два.', 12.0 + gap, 12.4 + gap)
    w.until(20.0)
    said = [text for _, text in w.played]
    assert said and all('52' in text for text in said) and 'касса' not in ' '.join(said), w.played


def test_a_round_number_with_no_rest_is_answered_a_second_later(tmp_path):
    w = Wire(tmp_path)
    w.user('u1', 'Что такое счёт пятьдесят?', 10.0, 12.0)
    w.until(16.0)
    assert w.played and w.played[0][1].startswith('Счёт 50') and 12.9 <= w.played[0][0] <= 13.4, w.played


def test_a_number_that_cannot_grow_is_not_held(tmp_path):
    w = Wire(tmp_path)
    w.user('u1', 'Что такое счёт пятьдесят два?', 10.0, 12.0)
    w.until(16.0)
    assert w.played and w.played[0][0] <= 12.2 and '52' in w.played[0][1], w.played


@pytest.mark.parametrize('text,grows', [('что такое счёт пятьдесят', True), ('счёт 50', True), ('статья сто', True), ('тысяча', True), ('что такое стоимость', False),
                                        ('счёт 52', False), ('что такое счёт пятьдесят два', False), ('счёт 0', False), ('', False)])
def test_what_number_can_still_grow(text, grows):
    from echo_sync.controlled_media import _number_grows
    assert _number_grows(text) is grows
