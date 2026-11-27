"""Russian number words and digits as ONE canonical value (WAVE 2 / Task A; DEF-ACK-06, 07, 08).

Pure grammar tests of ``echo_sync.ru_numbers``: no morphology, no I/O. The reader is fed ``Item`` tuples exactly as
``ru_alignment`` builds them from razdel tokens and pymorphy3 lemmas. A tiny spec language keeps the cases readable:

    c<N> cardinal word of value N       o<N> ordinal word          s<N> scale word (1000, 1000000 ...)
    d<N> a digit token (N may be 1.5)   h    «полтора/полторы»      f<E> a fraction word «десятых» (E=1), «сотых» (E=2)
    w:<surface> any other word (its surface is what the contexts «году», «июня», «с», «половиной» look at)
"""
from decimal import Decimal

import pytest

import helpers_s6_ack as H
from echo_sync import ru_numbers as N
from echo_sync.ru_numbers import Item


def items(spec):
    out = []
    for token in spec.split():
        kind, _, rest = token.partition(':') if token.startswith('w:') else (token[0], '', token[1:])
        if token.startswith('w:'):
            out.append(Item('word', rest, rest))
        elif kind == 'c':
            out.append(Item('card', int(rest), rest))
        elif kind == 'o':
            out.append(Item('ord', int(rest), rest))
        elif kind == 's':
            out.append(Item('scale', int(rest), rest))
        elif kind == 'd':
            out.append(Item('digits', Decimal(rest), rest))
        elif kind == 'f':
            out.append(Item('frac', int(rest), rest))
        elif kind == 'h':
            out.append(Item('half', Decimal('1.5'), 'полтора'))
        else:
            raise ValueError(token)
    return out


def read(spec, start=0):
    result = N.read_number(items(spec), start)
    if result is None:
        return None
    if isinstance(result, N.Fail):
        return ('fail', result.end)
    return result.atom, result.end


def atom(spec):
    result = read(spec)
    assert result and result[0] != 'fail', (spec, result)
    return result[0]


# -- integers, scales ----------------------------------------------------------------------------------------------

@pytest.mark.parametrize('spec,expected', [
    ('c0', '#0'), ('c7', '#7'), ('c15', '#15'), ('c20', '#20'), ('c100', '#100'), ('c100 c5', '#105'),
    ('c100 c20 c5', '#125'), ('c900 c90 c9', '#999'), ('c100 c11', '#111'),
    ('c2 s1000', '#2000'), ('c2 s1000 c500', '#2500'), ('s1000', '#1000'), ('s1000 c500', '#1500'),
    ('c20 c1 s1000', '#21000'), ('c11 s1000', '#11000'), ('c8 s1000 c800 c40 c9', '#8849'),
    ('c300 s1000', '#300000'), ('c5 s1000000', '#5000000'), ('s1000000', '#1000000'), ('c17 s1000000', '#17000000'),
    ('s1000000 c200 s1000', '#1200000'), ('c2 s1000000 c300 s1000 c1', '#2300001'),
    ('c1 s1000000000 c1', '#1000000001'), ('c3 s1000000000000', '#3000000000000'),
])
def test_cardinals_up_to_trillions(spec, expected):
    assert atom(spec) == expected


@pytest.mark.parametrize('n', list(range(0, 1000, 7)) + [999, 1000, 1001, 2500, 8849, 21000, 300000, 999999])
def test_the_independent_oracle_agrees_with_the_reader(n):
    """helpers_s6_ack speaks numbers on its own (cardinal/cardinal_big); every number it speaks must read back."""
    spoken = H.cardinal(n) if n < 1000 else H.cardinal_big(n)
    lemma_of = {'две': 'два', 'одна': 'один'}
    spec = []
    for word in spoken.split():
        word = lemma_of.get(word, word)
        spec.append(('s1000' if word in ('тысяча', 'тысячи', 'тысяч') else 'c' + str(_VALUE[word])))
    assert atom(' '.join(spec)) == '#' + str(n)


_VALUE = {w: i for i, w in enumerate('ноль один два три четыре пять шесть семь восемь девять десять одиннадцать двенадцать '
                                     'тринадцать четырнадцать пятнадцать шестнадцать семнадцать восемнадцать девятнадцать'.split())}
_VALUE.update(zip('двадцать тридцать сорок пятьдесят шестьдесят семьдесят восемьдесят девяносто'.split(), range(20, 100, 10)))
_VALUE.update(zip('сто двести триста четыреста пятьсот шестьсот семьсот восемьсот девятьсот'.split(), range(100, 1000, 100)))


@pytest.mark.parametrize('spec', [
    'c5 c6',                # two separate numbers are never added up
    'c20 c10', 'c100 c0', 'c3 c100', 'c20 c20', 's1000 s1000', 's1000 s1000000', 'c5 s1000 s1000000', 'c1 c2 c3',
    'o5 c3', 'o10 o5', 'c5 o10 c1', 'c40 o50',
])
def test_an_invalid_spoken_run_is_a_failure_never_a_guessed_number(spec):
    result = read(spec)
    assert result == ('fail', len(spec.split())), result


# -- ordinals ----------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize('spec,expected', [
    ('o1', '#ord:1'), ('o19', '#ord:19'), ('o20', '#ord:20'), ('c20 o2', '#ord:22'), ('c40 o5', '#ord:45'),
    ('c100 o20', '#ord:120'), ('o100', '#ord:100'), ('o200', '#ord:200'), ('c100 c40 o1', '#ord:141'),
    ('s1000 c900 c40 o5', '#ord:1945'), ('s1000 c900 o50', '#ord:1950'), ('c2 s1000 c20 o6', '#ord:2026'),
    ('c2 s1000 o1', '#ord:2001'), ('c2 s1000 o10', '#ord:2010'), ('c2 s1000 o20', '#ord:2020'),
    ('s1000 c800 o12', '#ord:1812'), ('o1000', '#ord:1000'), ('o2000', '#ord:2000'),
])
def test_ordinals_close_a_number(spec, expected):
    assert atom(spec) == expected


def test_an_ordinal_in_the_middle_of_a_number_is_a_failure():
    assert read('o2 s1000') == ('fail', 2)
    assert read('s1000 o2000') == ('fail', 2)


# -- digits ------------------------------------------------------------------------------------------------------------

def test_digits_are_a_number_of_their_own_and_scale_words_multiply_them():
    assert atom('d1945') == '#1945'
    assert atom('d5 s1000') == '#5000'
    assert atom('d17 s1000000') == '#17000000'
    assert atom('d1.5 s1000000') == '#1500000'
    assert atom('d2.5 s1000') == '#2500'
    assert read('d5 s1000 d300') == ('#5000', 2)         # the next digit token is another number


def test_a_decimal_digit_token_keeps_its_written_digits():
    """«статья 25.1» and «статья 25.10» are two different articles: nothing may be stripped from what is written."""
    assert atom('d3.50') == '#3.50'
    assert atom('d25.10') == '#25.10'
    assert atom('d36.6') == '#36.6'
    assert atom('d3.0') == '#3.0'
    assert atom('d0.5') == '#0.5'
    assert N.decimal_text(Decimal('100')) == '100'
    assert N.decimal_text(Decimal('0.50')) == '0.50'
    assert N.decimal_text(Decimal('1E+3')) == '1000'


# -- contexts that make a digit number an ordinal -------------------------------------------------------------------------

@pytest.mark.parametrize('spec,expected', [
    ('d1945 w:году', '#ord:1945'), ('d1945 w:года', '#ord:1945'), ('d2026 w:год', '#ord:2026'), ('d1812 w:годом', '#ord:1812'),
    ('d988 w:году', '#ord:988'), ('d988 w:года', '#988'), ('d101 w:год', '#ord:101'),
    ('d3 w:года', '#3'), ('d5 w:лет', '#5'), ('d1 w:год', '#1'), ('d21 w:год', '#21'), ('d50 w:году', '#50'),
    ('d21 w:веке', '#ord:21'), ('d19 w:века', '#ord:19'), ('d5 w:веку', '#ord:5'), ('d41 w:веке', '#41'),
    ('d10 w:классе', '#ord:10'), ('d1 w:класс', '#ord:1'), ('d13 w:классе', '#13'),
    ('d22 w:июня', '#ord:22'), ('d1 w:сентября', '#ord:1'), ('d9 w:мая', '#ord:9'), ('d31 w:декабря', '#ord:31'),
    ('d32 w:июня', '#32'), ('d0 w:мая', '#0'), ('d22 w:июнь', '#22'), ('d22 w:человек', '#22'),
])
def test_digits_in_a_date_year_century_or_grade_are_ordinals(spec, expected):
    assert read(spec)[0] == expected


def test_a_decimal_or_a_scaled_digit_number_is_never_an_ordinal():
    assert read('d1.5 w:года')[0] == '#1.5'
    assert read('d5 s1000 w:года')[0] == '#5000'


def test_roman_numerals_are_centuries_only_in_front_of_the_word_century():
    roman = Item('roman', (21, 'xxi'), 'xxi')
    assert N.read_number([roman, Item('word', 'век', 'веке')], 0).atom == '#ord:21'
    assert N.read_number([roman, Item('word', 'год', 'году')], 0) is None
    assert N.read_number([roman], 0) is None
    big = Item('roman', (50, 'l'), 'l')
    assert N.read_number([big, Item('word', 'век', 'веке')], 0) is None


# -- decimals, halves, fractions ------------------------------------------------------------------------------------------

@pytest.mark.parametrize('spec,expected', [
    ('c3 w:целых c5 f1', '#3.5'), ('c0 w:целых c5 f1', '#0.5'), ('c3 w:целых c14 f2', '#3.14'), ('c3 w:целых c5 f2', '#3.05'),
    ('c30 c6 w:целых c6 f1', '#36.6'), ('c1 w:целая c5 f1', '#1.5'), ('c2 w:целых c100 c20 c5 f3', '#2.125'), ('c3 w:целых c50 f2', '#3.50'), ('c3 w:целых c10 f2', '#3.10'),
    ('c5 f1', '#0.5'), ('c40 c5 f2', '#0.45'), ('d3 w:целых d5 f1', '#3.5'), ('c3 w:целых d14 f2', '#3.14'),
    ('c3 w:с w:половиной', '#3.5'), ('c2 w:с w:половиной s1000000', '#2500000'), ('d3 w:с w:половиной', '#3.5'),
    ('c3 w:запятая c5', '#3.5'), ('c3 w:запятая c0 c5', '#3.05'), ('c3 w:запятая c14', '#3.14'),
    ('h', '#1.5'), ('h s1000', '#1500'), ('h s1000000', '#1500000'),
])
def test_spoken_decimals(spec, expected):
    assert atom(spec) == expected


def test_a_broken_decimal_leaves_the_integer_part_alone():
    assert read('c3 w:целых c15 f1') == ('#3', 1)         # 15 tenths is not a decimal digit string
    assert read('c3 w:целых') == ('#3', 1)
    assert read('c3 w:запятая') == ('#3', 1)
    assert read('c3 w:с w:собой') == ('#3', 1)


def test_the_word_half_is_only_a_number_in_its_two_valid_shapes():
    assert read('h c2') == ('fail', 2)
    assert read('c1 h') == ('fail', 2)


# -- what is not a number --------------------------------------------------------------------------------------------------

def test_words_are_not_numbers():
    assert N.read_number(items('w:вода'), 0) is None
    assert N.read_number(items('w:год c5'), 0) is None


def test_reading_stops_at_the_first_word_that_is_not_part_of_the_number():
    assert read('c5 w:процентов') == ('#5', 1)
    assert read('c2 s1000 w:человек') == ('#2000', 2)
    assert read('w:около c5', 1) == ('#5', 2)


# -- thousands grouping (DEF-ACK-08) ----------------------------------------------------------------------------------------

@pytest.mark.parametrize('sep', [' ', ' ', ' ', ' ', ' '])
def test_digit_groups_separated_by_any_space_are_one_number(sep):
    assert N.merge_digit_groups(f'около 1{sep}500 человек') == 'около 1500 человек'
    assert N.merge_digit_groups(f'12{sep}345{sep}678') == '12345678'
    assert N.merge_digit_groups(f'300{sep}000 километров') == '300000 километров'
    assert N.merge_digit_groups(f'1{sep}000,5') == '1000,5'


@pytest.mark.parametrize('text', ['1 2 3', '5 5000', '1 50', '12 3456', '3,14 500', '2.5 500', 'номер 5 из 10', 'с 1 по 15',
                                  'в 1941 22 июня', '10 20 30', '1  500'])
def test_other_digit_sequences_stay_apart(text):
    assert N.merge_digit_groups(text) == text


def test_grouping_needs_exactly_three_digits_after_the_first_group():
    assert N.merge_digit_groups('1 5000') == '1 5000'
    assert N.merge_digit_groups('1 500 00') == '1500 00'


# -- Task E2, ruling 5: «N и M десятых / сотых / тысячных» is N.M, like «N целых M десятых» ---------------------------------------------------------

@pytest.mark.parametrize('spec,expected', [
    ('c30 c6 w:и c6 f1', '#36.6'), ('c3 w:и c5 f1', '#3.5'), ('c0 w:и c5 f1', '#0.5'), ('c3 w:и c14 f2', '#3.14'), ('c3 w:и c5 f2', '#3.05'),
    ('c2 w:и c100 c20 c5 f3', '#2.125'), ('c3 w:и c50 f2', '#3.50'), ('c1 w:и c5 f1', '#1.5'), ('d3 w:и d5 f1', '#3.5'), ('d36 w:и c6 f1', '#36.6'),
    ('c3 w:и c14 f2 w:градусов', '#3.14'),
])
def test_n_and_m_tenths_is_a_decimal(spec, expected):
    assert atom(spec) == expected


def test_an_and_that_does_not_lead_to_a_fraction_word_leaves_the_integer_part_alone():
    assert read('c3 w:и c15 f1') == ('#3', 1)          # 15 tenths is not a decimal digit string
    assert read('c3 w:и c5') == ('#3', 1)              # the colloquial «три и пять» is the alignment's business (it needs the portion)
    assert read('c3 w:и') == ('#3', 1)
    assert read('c3 w:и w:вода') == ('#3', 1)
    assert read('c3 w:или c5 f1') == ('#3', 1)         # another word
    assert read('c3 w:и c5 w:процентов') == ('#3', 1)


def test_two_spoken_numbers_after_an_and_are_never_summed_into_a_decimal():
    assert read('c3 w:и c5 c6 f1') == ('#3', 1)         # «пять шесть» is not a valid number, so no fraction of it is read


@pytest.mark.parametrize('value, word, expected', [
    (15, 'веках', True), (13, 'веков', True), (1, 'веках', True), (40, 'веках', True), (41, 'веках', False), (0, 'веках', False),
    (50, 'годах', False), (99, 'годах', False), (1945, 'годах', True), (100, 'годах', True), (1945, 'годов', True),
    (15, 'веке', False), (15, 'классах', False), (15, None, False),
])
def test_range_end_ordinal_is_a_count_window_on_the_plural_word(value, word, expected):
    assert N.range_end_ordinal(value, word) is expected


def test_plural_forms_are_separate_from_the_singular_ordinal_context():
    assert N.CENTURY_PLURAL == frozenset({'веках', 'веков'}) and N.YEAR_PLURAL == frozenset({'годах', 'годов'})
    assert N.CENTURY_FORMS == N.CENTURY_WORDS | N.CENTURY_PLURAL
    assert read('d15 w:веках') == ('#15', 1)            # read_number is unchanged: the plural alone does not make an ordinal
