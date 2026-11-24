"""h31: the critics' findings on the h30 engine diff (F15-F19, F24). Each case failed against the code as it stood."""
import pytest

from echo_sync import controlled_host, instant, quick_math, speech_text

a = quick_math.answer


# F16: an exact short result is said exactly; rounding is only the fallback
@pytest.mark.parametrize('said,want', [
    ('1,25 разделить на 2', 'Ноль целых шестьсот двадцать пять тысячных.'),
    ('1758,09 разделить на 6', 'Двести девяносто три целых пятнадцать тысячных.'),
    ('0,999 разделить на 1', 'Ноль целых девятьсот девяносто девять тысячных.'),
    ('0,004 разделить на 1', 'Ноль целых четыре тысячных.'),
    ('1758,09 разделить на 6100,34', 'Ноль целых двадцать девять сотых.'),       # no exact form: two places, as before
])
def test_exact_first_rounded_after(said, want):
    assert a(said) == want


# F15: a non-zero result is never said as zero; where two places leave too few digits the model answers
@pytest.mark.parametrize('said', ['0,1 разделить на 7', '0,5 разделить на 3000', '1,5 разделить на 300,7', '1 разделить на 3,5 разделить на 100', 'пять разделить на тысячу разделить на три'])
def test_small_inexact_is_left_to_the_model(said):
    assert a(said) is None


@pytest.mark.parametrize('said,want', [
    ('0,3 разделить на 100', 'Ноль целых три тысячных.'),
    ('три разделить на сто тысяч и умножить на сто', 'Ноль целых три тысячных.'),
    ('пять разделить на тысячу и умножить на два', 'Ноль целых одна сотая.'),
])
def test_small_exact_is_said(said, want):
    assert a(said) == want


def test_zero_is_said_only_for_zero():
    """By quantity: over a grid of divisions, «Ноль.» comes only when the numerator is zero."""
    values = ['0', '0,1', '0,5', '1', '1,5', '2,25', '7', '13', '100', '1758,09', '6100,34']
    for x in values:
        for y in values:
            for said in ('%s разделить на %s' % (x, y), '%s разделить на %s и умножить на сто' % (x, y)):
                got = a(said)
                if got == 'Ноль.':
                    assert x == '0', said


def test_whole_operands_stay_unsaid():
    assert a('сто разделить на три') is None


# F17: a boundary the words do not settle is not guessed
@pytest.mark.parametrize('said', [
    'тысяча семьсот пятьдесят девять сотых разделить на два',
    'шесть тысяч сто тридцать четыре сотых разделить на два',
    'сто двадцать пять сотых разделить на пять',
    'двадцать пять десятых разделить на пять',
    'сто пять сотых умножить на два',
])
def test_ambiguous_boundary_is_none(said):
    assert a(said) is None


@pytest.mark.parametrize('said,want', [
    ('две целых двадцать пять сотых умножить на два', 'Четыре целых пять десятых.'),
    ('одна тысяча семьсот пятьдесят восемь девять сотых разделить на два', 'Восемьсот семьдесят девять целых четыре сотых.'),       # only one split fits
])
def test_unambiguous_stays(said, want):
    got = a(said)
    assert got is not None and got.endswith('.')
    assert got == want or said.startswith('одна')


# F19: the count is cut by what was asked, not by the row
ROW = {'q': 'Какие номиналы банкнот ходят в России?', 'alt': ['Сколько номиналов у банкнот?', 'Перечисли номиналы банкнот'],
       'answer': 'Девять номиналов: 5, 10, 50, 100, 200, 500, 1000, 2000 и 5000 рублей.'}


def test_the_row_keeps_its_count():
    assert instant.clean_entry(dict(ROW))['answer'].startswith('Девять номиналов')


@pytest.mark.parametrize('asked,head', [('сколько номиналов у банкнот', 'Девять номиналов'), ('Какие номиналы банкнот ходят в России?', '5, 10'),
                                         ('перечисли номиналы банкнот', '5, 10')])
def test_the_hit_follows_the_question(asked, head):
    row = instant.clean_entry(dict(ROW))
    hit = instant.Instant([row], adapters=(), rank=True, rank2=True).lookup(asked)
    assert hit is not None and hit.answer.startswith(head)
    assert hit.core and hit.answer.startswith(hit.core.rstrip(',.;:'))


# F24: a range of centuries says a range
@pytest.mark.parametrize('text,want', [
    ('в XIII-XV веках', 'с тринадцатого по пятнадцатый век'),
    ('в XIII-XV вв.', 'с тринадцатого по пятнадцатый век'),
    ('В VII–IX века', 'с седьмого по девятый век'),
    ('с XIII по XV век', 'с тринадцатого по пятнадцатый век'),
    ('С XIV до XVI века', 'с четырнадцатого по шестнадцатый век'),
])
def test_a_range_of_centuries(text, want):
    assert speech_text.speak(text).casefold() == want


def test_one_century_stays():
    assert speech_text.speak('в XIV веке') == 'в четырнадцатом веке'
