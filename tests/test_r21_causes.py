"""R21-core: the first causes behind the findings of tests/test_r21_first_portion.py, one small test each (hand-written expectations).

The table finds a wrong first portion; these pin where it came from: a date torn before its year, a unit left behind its number, a date standing for the number
asked, a bare «Да.» for a conditional question, a cut before a negation, English function words, a reference answered with the question read back. Each test
calls the production function that was wrong (``portions``, ``first_cue``, ``compact_opening``, ``says_the_number_asked``), never the whole controller.
"""
from __future__ import annotations

import re

import pytest

from echo_sync.first_useful import asks_for_number, compact_opening, first_cue
from echo_sync.portioner import portions
from echo_sync.settings import CALL_SETTINGS
from helpers_r21_first import first_portion, words

MONTHS = frozenset('января февраля марта апреля мая июня июля августа сентября октября ноября декабря'.split())


def seams(text):
    """``[(last word, first word)]`` of every place the planner cuts ``text`` at."""
    parts = portions(text, CALL_SETTINGS)
    return [(words(a)[-1].casefold(), words(b)[0].casefold()) for a, b in zip(parts, parts[1:])]


# --- R21-01, R21-02: a date and its era are one unit -------------------------------------------------------------------------------------

@pytest.mark.parametrize('text', [
    'Первая мировая война началась 28 июля 1914 года, после убийства эрцгерцога Франца Фердинанда.',
    'Великая Отечественная война началась 22 июня 1941 года, и вся страна перешла на военное положение.',
    'Александр Сергеевич Пушкин родился 6 июня 1799 года в Москве, в семье небогатого дворянина.',
    'Вторая мировая война закончилась 2 сентября 1945 года, когда Япония подписала акт о капитуляции.',
])
def test_a_date_is_not_cut_between_the_month_and_the_year(text):
    assert not [seam for seam in seams(text) if seam[0] in MONTHS and seam[1].isdigit()]


@pytest.mark.parametrize('text', [
    'Битва при Марафоне состоялась в 490 году до нашей эры, в Греции.',
    'Пирамиду Хеопса построили примерно в 2560 году до нашей эры, при четвёртой династии.',
    'Рим основали в 753 году до н. э., как гласит предание, братья Ромул и Рем.',
    'Конфуций жил в пятом веке до нашей эры, в Китае, и учил почтению к старшим.',
])
def test_the_era_stays_with_its_year(text):
    seen = seams(text)
    assert not [seam for seam in seen if seam[0] in ('году', 'веке', 'год', 'века') and seam[1] in ('до', 'нашей', 'новой')], seen
    assert not [seam for seam in seen if seam[0] in ('до', 'нашей', 'новой') and seam[1] in ('нашей', 'эры', 'н')], seen


# --- R21-03: a rate, a scale or a range goes with its number ---------------------------------------------------------------------------------

@pytest.mark.parametrize('text,tail', [
    ('Скорость света в вакууме составляет примерно 300 000 километров в секунду, как известно.', ('километров', 'в')),
    ('Скорость звука в воздухе составляет около 340 метров в секунду при комнатной температуре.', ('метров', 'в')),
    ('Размер МРОТ с 1 января составляет 19 242 рубля в месяц, и он растёт каждый год.', ('рубля', 'в')),
    ('Температура поверхности Солнца составляет около 5500 градусов по Цельсию, а в центре гораздо выше.', ('градусов', 'по')),
    ('В среднем яблоке около 50 килокалорий на 100 граммов, то есть совсем немного.', ('килокалорий', 'на')),
    ('Ключевая ставка Банка России составляет 16 процентов годовых, и она меняется.', ('процентов', 'годовых')),
])
def test_a_rate_or_a_scale_is_not_cut_from_its_number(text, tail):
    assert tail not in seams(text), portions(text, CALL_SETTINGS)


@pytest.mark.parametrize('text,seam', [
    ('Билет в плацкартном вагоне стоит от 2500 до 3500 рублей, а в купе дороже.', ('2500', 'до')),
    ('Африканский слон весит от четырёх до шести тонн, а индийский немного меньше.', ('четырёх', 'до')),
    ('Столетняя война длилась с 1337 по 1453 год, то есть больше ста лет.', ('1337', 'по')),
])
def test_a_range_is_not_cut_in_the_middle(text, seam):
    assert seam not in seams(text), portions(text, CALL_SETTINGS)


# --- R21-04: the number asked is a quantity, not a date or the number of an article ---------------------------------------------------------

@pytest.mark.parametrize('question', [
    'Какой рост у игроков НБА?', 'Какой вес у слона?', 'Какая мощность у двигателя?', 'Какое давление в шинах?', 'Какая плотность у воды?',
    'Какая толщина у льда?', 'Какой объём у бочки?', 'Какой диаметр у Земли?',
])
def test_more_questions_for_a_quantity_are_recognised(question):
    assert asks_for_number(question)


@pytest.mark.parametrize('question', ['Какая весна в этом году?', 'Какой ростбиф вы любите?', 'Какое весёлое слово вы знаете?'])
def test_a_word_that_only_begins_like_a_quantity_noun_is_none(question):
    assert not asks_for_number(question)


@pytest.mark.parametrize('question,cue,asked', [
    ('Какой размер МРОТ?', 'Размер МРОТ с 1 января', False),
    ('Какой размер МРОТ?', 'Размер МРОТ с 1 января составляет 19 242 рубля', True),
    ('Какая ставка НДС в России?', 'С 2019 года ставка НДС в России составляет', False),
    ('Какая ставка НДС в России?', 'Ставка НДС составляет 20 процентов', True),
    ('Сколько дней отпуска положено по Трудовому кодексу?', 'Статья 115 Трудового кодекса', False),
    ('Сколько дней отпуска положено по Трудовому кодексу?', 'Статья 115 Трудового кодекса устанавливает 28 календарных дней', True),
    ('Сколько стоит проезд?', 'С первого января проезд стоит', False),
    ('Когда началась Первая мировая война?', 'Первая мировая война началась 28 июля', True),
    ('Какого числа День России?', 'День России празднуют ежегодно 12 июня', True),
    ('В каком году была битва на Калке?', 'Битва на Калке была в 1223 году', True),
])
def test_only_a_number_of_the_kind_asked_stands_for_the_number_asked(question, cue, asked):
    from echo_sync.first_useful import says_the_number_asked
    assert says_the_number_asked(cue, question) is asked


# --- R21-05: a conditional question is never answered by a bare «Да.» / «Нет.» -------------------------------------------------------------

CONDITIONAL = 'Можно ли вернуть товар без чека, если прошло десять дней?'


@pytest.mark.parametrize('answer,cue', [
    ('Да. Но только при сохранённом товарном виде и упаковке.', 'Да. Но только при сохранённом товарном виде и упаковке.'),
    ('Нет. Без чека товар можно вернуть только в течение семи дней.', 'Нет. Без чека товар можно вернуть только в течение семи дней.'),
    ('Да. Если товар не использовался, магазин обязан принять его обратно.', 'Да. Если товар не использовался,'),
])
def test_a_bare_verdict_waits_for_the_clause_that_qualifies_it(answer, cue):
    found = first_portion(CONDITIONAL, answer)
    assert found.cue == cue
    assert found.arrived > 1                                    # it was not spoken the moment «Да.» had arrived


def test_a_bare_verdict_is_still_the_answer_when_nothing_follows():
    assert first_portion(CONDITIONAL, 'Да.').cue == 'Да.'
    assert first_portion(CONDITIONAL, 'Нет.').cue == 'Нет.'


def test_a_bare_verdict_is_spoken_at_once_for_a_question_without_a_condition():
    found = first_portion('Работает ли магазин по воскресеньям?', 'Да. Магазин работает с десяти до восемнадцати часов.')
    assert (found.cue, found.arrived) == ('Да.', 1)
    found = first_portion('Это правда?', 'Нет. Это миф, который давно опровергнут.')
    assert (found.cue, found.arrived) == ('Нет.', 1)


@pytest.mark.parametrize('answer', ['Нет, не автоматически. Нужно подать заявление.', 'Да, но только по паспорту. Остальное не принимают.'])
def test_a_verdict_that_already_carries_its_qualifier_is_not_held(answer):
    found = first_portion('Если у меня есть паспорт, меня пустят?', answer)
    assert found.lag <= 1 and found.cue.endswith(('автоматически.', 'паспорту.'))


# --- R21-06, R21-07: an adjective with its noun, a negation with its clause ----------------------------------------------------------------

def test_two_adjectives_before_a_noun_are_not_cut_between_them():
    for text in ('Да, можно, но только при сохранённом товарном виде и упаковке.',
                 'Он купил новый кожаный чемодан и отправился на вокзал вместе с братом.',
                 'У нас большая светлая кухня с видом на реку и старый липовый сад.'):
        seen = seams(text)
        assert ('сохранённом', 'товарном') not in seen and ('новый', 'кожаный') not in seen and ('большая', 'светлая') not in seen, seen


@pytest.mark.parametrize('text,seam', [
    ('Да, детей до семи лет нельзя оставлять без присмотра даже на несколько минут.', ('лет', 'нельзя')),
    ('Нужно нагревать эту жидкость при таком давлении не быстро, а медленно, иначе она закипит.', ('быстро', 'а')),
    ('Нужно не нагревать эту жидкость при таком давлении, а охлаждать, иначе она закипит.', ('давлении', 'а')),
    ('Да, но не горячей водой, а тёплой, потому что горячая сворачивает белок.', ('водой', 'а')),
])
def test_a_negation_stays_with_its_clause_and_its_contrast(text, seam):
    assert seam not in seams(text), portions(text, CALL_SETTINGS)


def test_a_clause_with_a_negation_waits_for_the_word_after_its_comma():
    # «… не горячей водой,» alone is the first half of «не X, а Y»: the cue is not released until the word after the comma is known
    found = first_portion('Нужно ли мыть яйца перед варкой?', 'Да, но не горячей водой, а тёплой.')
    assert found.cue == 'Да, но не горячей водой, а тёплой.'


# --- R21-09: English --------------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize('text,seam', [
    ('No, in most cases recording a call without the consent of the other party is not allowed.', ('without', 'the')),
    ('Yes, but only within fourteen days and with the original packaging.', ('with', 'the')),
    ('Leo Tolstoy wrote War and Peace in the eighteen sixties.', ('in', 'the')),
    ('The speed of light is about 300 000 kilometres per second.', ('is', 'about')),
    ('The deadline is the thirtieth of April of the next year.', ('of', 'the')),
])
def test_an_english_function_word_does_not_end_a_portion(text, seam):
    assert seam not in seams(text), portions(text, CALL_SETTINGS)


@pytest.mark.parametrize('question', ['When did the Berlin Wall fall?', 'How many planets are there?', 'How much does a passport cost?',
                                      'What year was Moscow founded?', 'How long did the war last?', 'What is the speed of light in kilometres per second?'])
def test_an_english_question_for_a_number_is_recognised(question):
    assert asks_for_number(question)


@pytest.mark.parametrize('question', ['Who wrote War and Peace?', 'What is the capital of Australia?', 'Why is the sky blue?', 'Is coffee good for you?'])
def test_an_english_question_for_a_name_is_not_a_number_question(question):
    assert not asks_for_number(question)


# --- R21-10: a reference is answered by what it says ---------------------------------------------------------------------------------------

@pytest.mark.parametrize('question,answer,body', [
    ('Что говорит статья 19 Конституции?', 'Статья 19 Конституции гарантирует равенство всех перед законом.', 'равенство всех перед законом.'),
    ('О чём статья 51 Конституции?', 'Статья 51 Конституции говорит, что никто не обязан свидетельствовать против себя.', 'никто не обязан свидетельствовать против себя.'),
    ('Что такое статья 105 Уголовного кодекса?', 'Статья 105 Уголовного кодекса предусматривает ответственность за убийство.', 'ответственность за убийство.'),
    ('Что устанавливает статья 421 ГК РФ?', 'Статья 421 Гражданского кодекса закрепляет принцип свободы договора.', 'принцип свободы договора.'),
    ('Что регулирует статья 1 Налогового кодекса?', 'Статья 1 Налогового кодекса определяет состав законодательства о налогах.', 'состав законодательства о налогах.'),
])
def test_the_echo_of_the_reference_and_its_verb_is_left_out_of_the_cue(question, answer, body):
    assert compact_opening(answer, question).strip() == body


@pytest.mark.parametrize('question,answer', [
    ('Что говорит статья 19 Конституции?', 'Статья 20 Конституции гарантирует равенство всех перед законом.'),
    ('Что говорит статья 19 Конституции?', 'Статья 19 Конституции не гарантирует равенство всех перед законом.'),
    ('Что говорит статья 19 Конституции?', 'Статья 19 Гражданского кодекса определяет место жительства.'),
])
def test_another_article_or_a_negated_echo_is_no_echo(question, answer):
    assert compact_opening(answer, question).strip().startswith('Статья')


def test_a_reference_header_alone_is_not_a_first_portion():
    # «Статья 20 Гражданского кодекса» (+ «определяет») is what the question named; the cue runs on to what the article says
    found = first_portion('Что говорит статья 20 об аренде?', 'Статья 20 Гражданского кодекса определяет место жительства.')
    assert found.cue == 'Статья 20 Гражданского кодекса определяет место жительства.'


# --- the first portion is not held back by what the continuation brings -----------------------------------------------------------------------

def test_a_short_clause_that_holds_the_number_asked_is_spoken_once_the_word_after_its_comma_is_known():
    found = first_portion('Сколько лет Москве?', 'Москве больше 875 лет, её впервые упоминают в летописи под 1147 годом.')
    assert (found.cue, found.lag) == ('Москве больше 875 лет,', 1)             # the word after the comma is known: it is no qualifier of the number
    found = first_portion('Сколько длилась Столетняя война?', 'Столетняя война длилась 116 лет, с 1337 по 1453 год.')
    assert found.lag <= 1


def test_a_number_with_a_qualifier_after_its_comma_is_not_spoken_bare():
    found = first_portion('Сколько планет в Солнечной системе?', 'Восемь планет, не считая карликовых: Меркурий, Венера, Земля, Марс.')
    assert found.cue == 'Восемь планет, не считая карликовых: Меркурий, Венера, Земля, Марс.'      # fix-c20: g15 finishes the thought (4 words, 9 in all)
