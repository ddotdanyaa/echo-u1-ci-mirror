# -*- coding: utf-8 -*-
"""h25: questions read off a sheet, the owner's dictation cycle."""
import pytest

from echo_sync.instant import paper_form
from echo_sync.stumble_place import place
from echo_sync.settings import resolve


@pytest.mark.parametrize('said,form', [
    ('Напишите определение понятию «государственный бюджет»', 'что такое государственный бюджет?'),
    ('дайте определение понятию страховой риск', 'что такое страховой риск?'),
    ('Дайте определение понятия финансы', 'что такое финансы?'),
    ('Раскройте вид страхования – личное страхование и приведите примеры', 'что такое личное страхование?'),
    ('Напишите, где и когда возник термин финансы', 'где и когда возник термин финансы?'),
])
def test_a_question_off_a_sheet_is_asked_as_the_bank_knows_it(said, form):
    assert paper_form(said) == form


@pytest.mark.parametrize('said', ['Перечислите признаки страхования', 'Напишите письмо директору', 'Раскройте контрольную функцию финансов', 'Что такое бюджет?'])
def test_anything_else_stays_as_it_is(said):
    assert paper_form(said) == said


def test_the_cycle_is_off_until_the_profile_asks_for_it():
    assert resolve({})['dictation_cycle'] == 'off'
    assert resolve({'dictation_cycle': 'on'})['dictation_cycle'] == 'on'


PORTION_12_59 = 'Функции денег — мера стоимости, средство обращения, средство платежа,'


def test_h26_garbled_start_of_a_breath_still_names_the_place():
    assert place(['у', 'меня', 'стоимости'], PORTION_12_59)[0].startswith('средство обращения')


def test_h26_more_garble_than_words_before_is_no_place():
    assert place(['купи', 'мне', 'денег'], PORTION_12_59) is None


def test_h26_garble_at_the_very_start_is_no_place():
    assert place(['я', 'думаю', 'функции'], PORTION_12_59) is None


def test_h27_a_number_at_the_head_does_not_lose_the_place():
    portion = 'Шесть видов: между государством и населением, хозяйствующими субъектами,'
    assert place(['между', 'государством'], portion)[0].startswith('и населением')
    assert place(['так', 'между', 'государством'], portion)[0].startswith('и населением')


def test_h27_a_number_inside_a_jump_still_stops_the_place():
    assert place(['налог', 'процентов'], 'Налог 13 процентов с дохода физических лиц') is None


def test_h27_stammer_written_by_the_cloud():
    from echo_sync.textutil import destutter
    assert destutter('Так. Ч-что такое финансы') == 'Так. что такое финансы'
    assert destutter('то-то и оно, еле-еле') == 'то-то и оно, еле-еле'
