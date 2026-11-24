"""h28: the classes found in the calls of 7 Nov, locked by what they are, not by the phrases of that day."""
import json
from types import SimpleNamespace

import pytest

from echo_sync import instant
from echo_sync.repeat_rule import DICTATION_CYCLE_REPEATS, silence

ROWS = [
    {'q': 'Что такое кредит?', 'answer': 'Экономическая категория возвратного движения.', 'alt': ['Дай определение кредита.']},
    {'q': 'Что входит в агрегат М2?', 'answer': 'М1 плюс другие депозиты.', 'alt': ['Что такое М2?', 'М2']},
    {'q': 'Что такое деньги?', 'answer': 'Всеобщий эквивалент стоимости.', 'alt': ['деньги']},
    {'q': 'Что такое денежная масса?', 'answer': 'Все деньги в обращении.', 'alt': ['денежная масса']},
    {'q': 'Что такое страхование?', 'answer': 'Защита интересов при страховых случаях.', 'alt': []},
    {'q': 'Дай определение страхования', 'answer': 'Отношения по защите интересов за счёт фондов.', 'alt': ['Что такое страхование?']},
    {'q': 'Что идёт по дебету, а что по кредиту счёта 01?', 'answer': 'По дебету поступление, по кредиту выбытие.', 'alt': []},
    {'q': 'Счёт 58 активный или пассивный?', 'answer': 'Активный.', 'alt': ['Счёт 58 это активный счёт или пассивный?']},
]


@pytest.fixture(scope='module')
def idx():
    rows = [r for r in (instant.clean_entry(dict(row, source='t', subject='t')) for row in ROWS) if r]
    return instant.Instant(rows, adapters=(), rank=True, rank2=True)


@pytest.mark.parametrize('talk', ['к два', 'в один', 'пока два', 'второй вопрос', 'деньги', 'денег', 'Деньги для', 'организации',
                                  'денежная масса это все деньги в экономике'])
def test_a_scrap_of_talk_is_no_question(idx, talk):
    assert idx.lookup(talk, bank_only=True) is None


@pytest.mark.parametrize('asked', ['Что такое кредит?', 'Дай определение кредита', 'Что такое М2?', 'денежная масса что это',
                                   'Что идёт по дебету, а что по кредиту счёта 01?', 'Счёт 58 это активный счёт или пассивный?'])
def test_a_question_of_the_bank_is_answered(idx, asked):
    assert idx.lookup(asked, bank_only=True) is not None


def test_two_rows_of_one_form_are_an_answer_not_silence(idx):
    assert idx.lookup('Что такое страхование?', bank_only=True).answer.startswith('Защита')


def test_the_cycle_slows_but_runs_about_a_minute():
    waits = [silence(repeats=k, cycling=True).wait for k in range(DICTATION_CYCLE_REPEATS)]
    assert waits[0] == 1.0 and waits == sorted(waits) and max(waits) <= 8.0 and 50 <= sum(waits) <= 90


def test_the_cycle_needs_no_command():
    assert silence(cycling=True).cycling      # the pure place; the controller's reading of the setting is pinned in tests/test_x_cap_wiring.py (the owner writing, told from speech; dictation off)
