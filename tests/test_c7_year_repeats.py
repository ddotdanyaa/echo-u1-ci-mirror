"""C7-B (live run 20261103-164741, w3_10 steps 6-9 and w3_03 step 6): a correct repeat of a portion with a year is confirmed.

The portion «1853 года и продлилась до 1856-го.» was repeated and the cloud ASR wrote «Одна тысяча восемьсот пятьдесят третьего года
и продлилась до тысячи восемьсот пятьдесят шестого»: «до тысячи восемьсот пятьдесят шестого» is the year 1856 said the way people say
it, with the scale word in the case the preposition asks for. ``ru_alignment._word_item`` took an oblique «тысячи» for a word unless a
number stood before it, so the repeat was an «attempt» and the portion was spoken again, four times. The class: a scale word in any case
followed by a number word is the scale of that number; with no number word after it («тысячи людей») it stays a word. A year or a
decade written «2024-м», «1990-х» is the ordinal said for it.

R2a stays: a different number, a scale with nothing after it never confirm. Expected values are written by hand.
"""
from __future__ import annotations

import pytest

from echo_sync.ru_alignment import match_current


def ack(heard, expected):
    return match_current(heard, expected) == 'ack'


# --- the live evidence -------------------------------------------------------------------------------------------------------------

def test_the_crimean_war_repeat_of_the_live_run_is_confirmed():
    assert ack('Одна тысяча восемьсот пятьдесят третьего года и продлилась до тысячи восемьсот пятьдесят шестого',
               '1853 года и продлилась до 1856-го.')


# --- the class: a scale word in any case, followed by a number word ----------------------------------------------------------------

@pytest.mark.parametrize('heard,expected', [
    ('до тысячи восемьсот пятьдесят шестого', 'до 1856-го'),
    ('с тысячи восемьсот пятьдесят третьего года', 'с 1853 года'),
    ('к тысяче девятисотому году', 'к 1900 году'),
    ('с тысяча девятьсот девяносто второго года', 'с 1992 года'),
    ('в тысяча восемьсот восемьдесят девятом году', 'в 1889 году'),
    ('около тысячи двухсот человек', 'около 1200 человек'),
    ('с тысячей двумястами рублями', 'с 1200 рублями'),
    ('до миллиона двухсот тысяч рублей', 'до 1 200 000 рублей'),
    ('до тысячи пятисот рублей', 'до 1500 ₽'),
])
def test_a_scale_word_in_an_oblique_case_before_a_number_is_that_number(heard, expected):
    assert ack(heard, expected)


@pytest.mark.parametrize('heard,expected', [
    ('тысяча восемьсот пятьдесят шестого', '1856-го'),
    ('в двухтысячном году', 'в 2000 году'),
    ('в две тысячи двадцать четвёртом', 'в 2024-м'),
    ('в две тысячи двадцать четвертом году', 'в 2024-м году'),
    ('в тысяча девятьсот девяностых', 'в 1990-х'),
    ('полтора миллиона', '1,5 млн'),
    ('двадцать процентов', '20 процентов'),
    ('тринадцать процентов НДФЛ', '13 % НДФЛ'),
    ('полторы тысячи рублей', '1500 рублей'),
    ('полторы тысячи рублей', '1,5 тыс. рублей'),
    ('полторы тысячи рублей', 'полторы тысячи рублей'),
    ('две тысячи двадцать четвёртого года', '2024 года'),
])
def test_years_money_and_percents_said_in_words_are_the_written_numbers(heard, expected):
    assert ack(heard, expected)


# --- R2a: a different number never confirms ------------------------------------------------------------------------------------------

@pytest.mark.parametrize('heard,expected', [
    ('до тысячи восемьсот пятьдесят шестого', 'до 1855-го'),
    ('с тысячи восемьсот пятьдесят четвёртого года', 'с 1853 года'),
    ('Одна тысяча восемьсот пятьдесят третьего года и продлилась до тысячи восемьсот пятьдесят седьмого',
     '1853 года и продлилась до 1856-го.'),
    ('в две тысячи двадцать пятом', 'в 2024-м'),
    ('в тысяча девятьсот восьмидесятых', 'в 1990-х'),
    ('до тысячи пятисот рублей', 'до 1400 ₽'),
    ('двадцать один процент', '20 процентов'),
    ('полторы тысячи рублей', '1400 рублей'),
    ('тысячи людей', '1000 людей'),
    ('тысячи людей', '2000 людей'),
    ('в 2-х экземплярах', 'во вторых экземплярах'),
])
def test_a_different_number_is_never_confirmed(heard, expected):
    assert not ack(heard, expected)


def test_a_scale_word_with_no_number_after_it_stays_a_word():
    # «тысячи людей» is a crowd, not 1000: it matches itself, never a written number
    assert ack('тысячи людей', 'тысячи людей')
    assert not ack('тысячи людей', '1000 людей')
    assert ack('о тысячах людей', 'о тысячах людей')


# --- C7-B2 (w3_03 step 6): the ASR writes a year it heard as a cardinal before «году» ---------------------------------------------------

def test_the_eiffel_tower_repeat_of_the_live_run_is_confirmed():
    # «В 1889 году,» was repeated, the cloud ASR wrote «В одна тысяча восемьсот восемьдесят девять году»: the same year, its ordinal
    # ending lost in recognition
    assert ack('В одна тысяча восемьсот восемьдесят девять году', 'В 1889 году,')
    assert ack('датируют тысяча девятьсот сорок пять годом', 'датируют 1945 годом')


@pytest.mark.parametrize('heard,expected', [
    ('В одна тысяча восемьсот восемьдесят восемь году', 'В 1889 году,'),
    ('тысяча восемьсот восемьдесят девять лет', '1889 году'),
    ('в тысяча восемьсот восемьдесят девять', 'в 1889 году'),
    ('две тысячи три года', 'с 2003 года'),
    ('к двадцати одному году', 'к 21-му году'),
])
def test_a_cardinal_is_a_year_only_from_1000_and_only_before_an_oblique_year_word(heard, expected):
    assert not ack(heard, expected)


def test_a_cardinal_below_1000_before_a_year_word_stays_a_count():
    assert ack('к двадцати одному году', 'к 21 году')


def test_the_kant_repeat_of_the_w4_run_is_confirmed():
    # W4 run 20261103-171237, w4_05 step 3: «В 1724 году.» repeated, the cloud ASR wrote the year as a cardinal; it waited ~10 s for a
    # replay of the same portion (the class of C7-B2)
    assert ack('В одна тысяча семьсот двадцать четыре году', 'В 1724 году.')


def test_a_three_digit_year_said_as_a_cardinal_before_godom_confirms_the_portion():
    # Candidate 9 (w3_02): the cloud writes «девятьсот восемьдесят восемь годом» for the portion «988 годом,».
    from echo_sync.ru_alignment import match_current
    assert match_current('Крещение Руси обычно датируют девятьсот восемьдесят восемь годом', 'Крещение Руси обычно датируют 988 годом,', ()) == 'ack'
    assert match_current('Крещение Руси обычно датируют девятьсот восемьдесят девять годом', 'Крещение Руси обычно датируют 988 годом,', ()) != 'ack'


# --- G3, the live run on candidate 11 (W3 w3_02 steps 5-9, five wasted repeats): a spoken cardinal of 100 or more before «год» / «года» -----------

def test_the_live_repeat_of_the_year_988_is_confirmed():
    assert ack('Обычно называют девятьсот восемьдесят восемь год', 'Обычно называют 988 год —')


@pytest.mark.parametrize('heard,expected', [
    ('девятьсот восемьдесят восемь год', '988 год'),
    ('девятьсот восемьдесят восьмой год', '988 год'),
    ('девятьсот восемьдесят восемь года', '988 года'),
    ('девятьсот восемьдесят восьмого года', '988 года'),
    ('девятьсот восемьдесят восемь году', '988 году'),
    ('девятьсот восемьдесят восьмом году', '988 году'),
    ('девятьсот восемьдесят восемь годом', '988 годом'),
    ('девятьсот восемьдесят восьмым годом', '988 годом'),
    ('988 год', 'девятьсот восемьдесят восьмой год'),
    ('988 года', 'девятьсот восемьдесят восьмого года'),
    ('988-го года', '988 года'),
    ('1945-го года', '1945 года'),
    ('сто двадцать пять год', '125 год'),
    ('тысяча девятьсот сорок пять год', '1945 год'),
    ('тысяча девятьсот сорок пять года', '1945 года'),
    ('одна тысяча девятьсот сорок пять года', '1945 года'),
    ('две тысячи двадцать четыре год', '2024 год'),
    ('две тысячи двадцать четыре года', '2024 года'),
    ('двадцать один год', '21 год'),
    ('двадцать два года', '22 года'),
])
def test_any_spelling_of_a_year_is_the_digits_of_that_year(heard, expected):
    assert ack(heard, expected)


@pytest.mark.parametrize('heard,expected', [
    ('девятьсот восемьдесят девять год', '988 год'),
    ('девятьсот восемьдесят восемь год', '989 год'),
    ('девятьсот восемьдесят восьмого года', '989 года'),
    ('девятьсот восемьдесят девять года', '988 года'),
    ('988-го года', '989 года'),
    ('тысяча девятьсот сорок шесть год', '1945 год'),
    ('две тысячи двадцать пять года', '2024 года'),
    ('двадцать один год', '22 года'),
    ('двадцать один год', '1921 год'),
    ('двадцать первый год', '21 год'),
    ('сто год', '200 год'),
])
def test_another_year_is_never_confirmed(heard, expected):
    assert not ack(heard, expected)
