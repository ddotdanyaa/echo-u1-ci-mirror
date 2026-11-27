"""w8-repeat / E84: the guard set of repeats. What the owner praised stays accepted, what must never move the cursor never does.

Every verdict is the production ``analyze`` with the production call profile (helpers_s6_ack.verdict); the heard texts are what the
local ear wrote (cloud_context/analysis/14_EAR_N2_raw.jsonl) or the usual damage of a repeat. ``ack_garble`` (off by default) lets ONE
word that the recogniser garbled into a non-word count as the portion's word; it never touches a number, a negation, a short word or
a word that is a real other word.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import helpers_s6_ack as H                                                    # noqa: E402
from echo_sync.classifier import ACK                                          # noqa: E402

GARBLE = dict(H.PROD_SETTINGS, ack_garble=True)


def acks(heard, portion, settings=None):
    return H.verdict(heard, portion, settings).kind == ACK


GOOD = [   # (portion, heard): a repeat the owner would call a repeat
    ('Течение реки два километра в час', 'течение реки два километра в час'),
    ('Течение реки два километра в час', 'Течение реки 2 километра в час'),
    ('Один час работы стоит полторы тысячи рублей', 'один час работы стоит полторы тысячи рублей'),
    ('Сколько это в рублях', 'ну сколько это в рублях'),
    ('Давай прикинем. До озера четыреста пятьдесят километров', 'давай прикинем до озера четыреста пятьдесят километров'),
    ('Горит она не меньше восьми часов в день', 'горит она не меньше восьми часов в день'),
    ('Плотность — это масса вещества в единице объёма', 'значит плотность это масса вещества в единице объёма'),
]
NEVER = [  # (portion, heard): must not be an ACK in any profile
    ('Течение реки два километра в час', 'течение реки три километра в час'),
    ('Горит она не меньше восьми часов в день', 'горит она меньше восьми часов в день'),
    ('Горит она не меньше восьми часов в день', 'горит она не меньше девяти часов в день'),
    ('Один час работы стоит полторы тысячи рублей', 'один час работы стоит полторы тысячи'),
    ('Один час работы стоит полторы тысячи рублей', 'работы стоит полторы тысячи рублей'),
    ('Через сколько лет после основания города появился Эрмитаж', 'через лет после основания города появился Эрмитаж'),
    ('Сколько энергии экономит переработка алюминиевой банки', 'энергии экономит переработка алюминиевой банки'),
    ('Вы точно не ошиблись, что-то маловато получается, давайте ещё раз посчитаем', 'вы не ошиблись что-то маловато получается давайте ещё раз посчитаем'),
    ('Давайте сначала про безубыточность. Постоянные расходы у вас девяносто тысяч в месяц', 'давайте про безубыточность постоянные расходы у вас девяносто тысяч в месяц'),
    ('Это не опасно для здоровья человека', 'это опасно для здоровья человека'),
    ('Течение реки два километра в час', 'температура воды двадцать градусов в час'),
    ('Течение реки два километра в час', 'течение реки'),
    ('Теперь уравнение. В листе углекислый газ и вода превращаются в глюкозу и кислород', 'в листе углекислый газ и вода превращаются в глюкозу и кислород'),
]


@pytest.mark.parametrize('portion,heard', GOOD)
@pytest.mark.parametrize('flag', [False, True])
def test_a_good_repeat_stays_accepted(portion, heard, flag):
    assert acks(heard, portion, GARBLE if flag else None), (portion, heard)


@pytest.mark.parametrize('portion,heard', NEVER)
@pytest.mark.parametrize('flag', [False, True])
def test_a_wrong_repeat_never_moves_the_cursor(portion, heard, flag):
    assert not acks(heard, portion, GARBLE if flag else None), (portion, heard)


GARBLED = [   # one word of the portion garbled by the ear into a non-word
    ('Один час работы стоит полторы тысячи рублей', 'один час рахоты стоит полторы тысячи рублей'),
    ('Давай прикинем. До озера четыреста пятьдесят километров', 'давай прхкинем до озера четыреста пятьдесят километров'),
    ('Всё, я вернулся, продолжаем, ну, с того места, где остановились', 'все я вехнулся продолжаем ну с того места где остановились'),
    ('Горит она не меньше восьми часов в день', 'горит она не мехьше восьми часов в день'),
]


@pytest.mark.parametrize('portion,heard', GARBLED)
def test_a_garbled_word_is_refused_without_the_flag(portion, heard):
    assert not acks(heard, portion), 'the flag is off by default: nothing changes'


@pytest.mark.parametrize('portion,heard', GARBLED)
def test_a_garbled_word_is_accepted_with_the_flag(portion, heard):
    assert acks(heard, portion, GARBLE), (portion, heard)


EAR_S = [   # the ear swallows (or invents) the one-letter «с»: 14 of the 64 refusals of a full repeat in 14_EAR_N2_raw.jsonl
    ('Всё, я вернулся, продолжаем, ну, с того места, где остановились', 'все я вернулся продолжаем ну того места где остановились'),
    ('Уточните, эти четырнадцать дней считаются с какого момента, а то я могу не успеть', 'уточните эти четырнадцать дней считаются какого момента а то я могу не успеть'),
    ('Угу, ага, понятно, ну да, так и есть, спасибо', 'угу ага понятно ну да так и есть с спасибо'),
]


@pytest.mark.parametrize('portion,heard', EAR_S)
def test_a_swallowed_or_invented_s_is_refused_without_the_flag(portion, heard):
    assert not acks(heard, portion)


@pytest.mark.parametrize('portion,heard', EAR_S)
def test_a_swallowed_or_invented_s_is_accepted_with_the_flag(portion, heard):
    assert acks(heard, portion, GARBLE), (portion, heard)


PROTECTED = [   # damage that must stay a refusal even with the flag
    ('Давай начнём с пяти утра и до обеда', 'давай начнём пяти утра и до обеда пять'),
    ('Всё, я вернулся, продолжаем, ну, с того места, где остановились', 'все я вернулся продолжаем ну того места где остановимся'),
    ('Течение реки два километра в час', 'течение реки двадцать километра в час'),      # a number is never healed
    ('Течение реки два километра в час', 'течение рыки два километра в час'),            # a garbled word of 4+ letters is ok only from 6
    ('Горит она не меньше восьми часов в день', 'горит она ни меньше восьми часов в день'),
    ('Один час работы стоит полторы тысячи рублей', 'один час рахоты стоит полторы тысячи рублеи рубли'),
    ('Один час работы стоит полторы тысячи рублей', 'один чат рахоты стоит палторы тысячи рублей'),   # two garbles in a 7-word portion
    ('Заказ принят на вторник утром', 'заказ принят на среду утром'),                      # another real word is another word
    ('Заказ принят на вторник утром', 'заказ принят на вторник утро вечером'),
    ('Ставка составляет пять процентов годовых', 'ставка составляет пять процентов годовых или меньше'),
]


@pytest.mark.parametrize('portion,heard', PROTECTED)
def test_the_flag_never_heals_what_it_must_not(portion, heard):
    assert not acks(heard, portion, GARBLE), (portion, heard)


def test_the_setting_is_a_validated_flag_off_by_default():
    from echo_sync.settings import DEFAULTS, resolve
    assert DEFAULTS['ack_garble'] is False
    assert resolve({'ack_garble': True})['ack_garble'] is True
    assert resolve({'ack_garble': 'yes'})['ack_garble'] is False


def test_the_own_cue_heard_back_in_drop_mode_is_not_an_ack(tmp_path):
    """E10: the text of the cue itself, announced inside its window, never confirms it (the transport tests are test_cue_in_flight.py)."""
    import test_cue_in_flight as C
    d, cue = C.playing(tmp_path)
    before, after, actions = C.hear(d, C.PORTION, began=1.0)
    assert after == before and C.speaks(actions) == []
