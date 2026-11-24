"""WAVE 2 / Task C-seg, item 2: numbers stay with their units and are never split.

The adversarial module ``test_s6_segmentation.py`` holds the acceptance cases (DEF-SEG-01..11, 18, 21); this module adds
what it does not pin: the exact example of the brief («при ста | градусах»), writing variants (no space before the
degree sign, a sign before the number), the fixed-size ``words`` mode, and the NEGATIVE cases - text that looks like a
number with a unit but is not one, which the portioner must keep free to cut.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import helpers_s6_seg as H                                                   # noqa: E402
from echo_sync.portioner import portions                                    # noqa: E402

SYLLABLE = list(H.SYLLABLE_PROFILES)
EVERY = list(H.PROFILES)


def whole(text, atom, profiles):
    """Profiles whose plan of ``text`` cuts ``atom`` (a boundary strictly inside it)."""
    return [(p, portions(text, H.PROFILES[p])) for p in profiles
            if H.cut_atoms(text, [atom], portions(text, H.PROFILES[p]))]


# --- 4a: degree sign, currency sign after the number, century ----------------------------------------------------

@pytest.mark.parametrize('text,atom', [
    ('Вода кипит при температуре 100 °C на уровне моря.', '100 °C'),
    ('Вода кипит при температуре 100°C на уровне моря.', '100°C'),
    ('Температура тела человека составляет около 36,6 °C в норме.', '36,6 °C'),
    ('Ночью было минус 20 °C и дул ветер.', '20 °C'),
    ('Вода замерзает при 0 °C на уровне моря.', '0 °C'),
    ('Вода кипит при 212 °F по шкале Фаренгейта.', '212 °F'),
    ('Абсолютный нуль равен 0 K по шкале Кельвина.', '0 K'),
    ('Вода кипит при 100 °С на уровне моря.', '100 °С'),                      # a Cyrillic «С»
])
def test_a_temperature_is_one_unit(text, atom):
    assert not whole(text, atom, SYLLABLE), whole(text, atom, SYLLABLE)


def test_the_degree_glue_does_not_swallow_a_following_word():
    parts = portions('Угол наклона равен 90° к горизонту плоскости.', H.PROFILES['controlled'])
    assert not H.cut_atoms('Угол наклона равен 90° к горизонту плоскости.', ['90°'], parts)
    assert 'горизонту' not in parts[parts.index(next(p for p in parts if '90' in p))].split()[-1:], parts


@pytest.mark.parametrize('text,atom', [
    ('Штраф составляет 500 ₽ за нарушение правил движения.', '500 ₽'),
    ('Проезд обойдётся в 1 500 ₽ за месяц поездок по городу.', '1 500 ₽'),
    ('Прибыль составила 2,3 млн ₽ за прошедший год работы.', '2,3 млн ₽'),
    ('Подписка стоит 100 $ в месяц для одного человека.', '100 $'),
    ('Билет стоит 20 € в одну сторону без багажа.', '20 €'),
])
def test_a_currency_sign_after_the_number_goes_with_the_number(text, atom):
    assert not whole(text, atom, SYLLABLE), whole(text, atom, SYLLABLE)


@pytest.mark.parametrize('text', ['Цена составляет $100 за штуку без доставки.', 'Бюджет равен №5 по плану работ.',
                                  'Это написано в § 3 настоящего договора полностью.'])
def test_a_sign_BEFORE_a_number_still_travels_with_the_next_word(text):
    for profile in SYLLABLE:
        for part in portions(text, H.PROFILES[profile]):
            assert part.split()[-1] not in ('$', '№', '§'), (profile, part)
            assert not part.rstrip().endswith(('$', '№', '§')), (profile, part)


@pytest.mark.parametrize('text,atom', [
    ('Это произошло в XIX веке в России, как известно.', 'в XIX веке'),
    ('Город основали в 18 веке на берегу Невы, как известно.', 'в 18 веке'),
    ('В XXI веке люди учатся всю жизнь, как известно.', 'XXI веке'),
    ('Пушкин жил в XIX веке и писал стихи, как известно.', 'XIX веке'),
    ('Это случилось в начале XX века, как известно.', 'XX века'),
    ('С тех пор прошло три века, как известно.', 'три века'),
])
def test_a_century_is_one_unit(text, atom):
    assert not whole(text, atom, SYLLABLE), whole(text, atom, SYLLABLE)


@pytest.mark.parametrize('text', [
    'Он родился в 1990 в Москве и жил там долго.',          # «в» after a number is a preposition, not a unit
    'Мы взяли 5 а потом ещё три штуки по списку.',
])
def test_the_new_glue_leaves_alone_what_is_not_a_unit(text):
    parts = portions(text, H.PROFILES['controlled'])
    assert H.lossless_problem(text, parts) is None


# --- 4b: range, time, ratio, fraction, compound unit, arithmetic -------------------------------------------------------

@pytest.mark.parametrize('text,atom', [
    ('Война шла с 1941–1945 годов, как всем известно.', '1941–1945'),
    ('Взрослому нужно спать 7–9 часов в сутки, как известно.', '7–9'),
    ('Это длилось с 2020—2022 годы, как всем известно.', '2020—2022'),
    ('Рост составил 15—20 % за год, как всем известно.', '15—20'),
    ('Это было в XIX–XX веках, как всем известно.', 'XIX–XX'),
    ('Идёт 1941 – 1945 год, как всем известно.', '1941 – 1945'),
])
def test_a_numeric_range_is_one_value_in_every_mode(text, atom):
    assert not whole(text, atom, EVERY), whole(text, atom, EVERY)


@pytest.mark.parametrize('text,atom', [
    ('Встреча назначена на 10:15, как всем известно.', '10:15'),
    ('Урок начинается в 9:45 утра, как всем известно.', '9:45'),
    ('Занятие начнётся сегодня в 12:30, как всем известно.', '12:30'),
    ('Соотношение сторон экрана составляет 16:9, как известно.', '16:9'),
    ('Масштаб карты равен 1:100 000, как всем известно.', '1:100 000'),
    ('Счёт был 3 : 1 в пользу гостей, как всем известно.', '3 : 1'),
])
def test_a_time_or_a_ratio_is_one_value_in_every_mode(text, atom):
    assert not whole(text, atom, EVERY), whole(text, atom, EVERY)


@pytest.mark.parametrize('text,atom', [
    ('Добавьте 1/2 стакана воды, как всем известно.', '1/2'),
    ('Выпала 3/4 нормы осадков, как всем известно.', '3/4'),
    ('Скорость света около 300 000 км/с в вакууме.', '300 000 км/с'),
    ('Самолёт летит со скоростью 900 км/ч, как известно.', '900 км/ч'),
    ('Звук идёт со скоростью 340 м/с в воздухе.', '340 м/с'),
    ('Плотность воды равна 1 г/см³ при обычных условиях.', '1 г/см³'),
    ('Подходит вариант и/или другой, как всем известно.', 'и/или'),
])
def test_a_fraction_or_a_compound_unit_is_one_value(text, atom):
    assert not whole(text, atom, SYLLABLE), whole(text, atom, SYLLABLE)


@pytest.mark.parametrize('text,atom', [
    ('Два плюс два равно 4, то есть 2 + 2 = 4, как известно.', '2 + 2 = 4'),
    ('Пять на шесть будет 30, то есть 5 × 6 = 30, как известно.', '5 × 6 = 30'),
    ('Десять минус четыре будет 6, то есть 10 − 4 = 6, как известно.', '10 − 4 = 6'),
    ('Пусть x = 3 в этом уравнении, как всем известно.', 'x = 3'),
])
def test_an_arithmetic_expression_is_one_value(text, atom):
    assert not whole(text, atom, SYLLABLE), whole(text, atom, SYLLABLE)


@pytest.mark.parametrize('text,first,second', [
    ('Ответ: 5 яблок в корзине, как всем известно.', 'Ответ', '5'),            # a colon after a WORD is not a time
    ('Страница 5, пункт 3, как всем известно, важны.', '5', 'пункт'),            # a comma is not a joint
    ('Число 5 — это нечётное число, как известно.', '5', 'это'),                # a dash before a WORD is not a range
    ('Берите яблоки / груши / сливы, как всем известно.', 'яблоки', 'груши'),   # a spaced slash between words
    ('Результат 5, 7 и 9 лучше прежнего, как известно.', '5', '7'),              # numbers in a list
    ('Вес 3 кг - это немного, как всем известно.', 'кг', 'это'),                  # a spaced hyphen after a word
])
def test_a_sign_between_things_that_are_no_value_joins_nothing(text, first, second):
    from echo_sync import portioner
    tokens = portioner._tokenize(text)
    marks = portioner._joint_marks(tokens)
    i = [t.text for t in tokens].index(first)
    assert tokens[i + 1].text == second and not marks[i], (text, first, second)


# --- 4c: a number written in words, and units the lexicon did not know --------------------------------------------------

@pytest.mark.parametrize('text,atom', [
    ('При нормальном давлении вода кипит при ста градусах, как всем известно.', 'при ста градусах'),   # the brief's example
    ('В развёрнутом угле сто восемьдесят градусов, как всем известно.', 'сто восемьдесят градусов'),
    ('Это двадцать пять процентов от всего числа, как всем известно.', 'двадцать пять процентов'),
    ('Между городами три тысячи километров пути, как всем известно.', 'три тысячи километров'),
    ('Прошло две тысячи пятьсот лет с тех пор, как всем известно.', 'две тысячи пятьсот лет'),
    ('Вес груза равен сорока килограммам, как всем известно.', 'сорока килограммам'),
    ('Дорога занимает пятнадцать минут пешком, как всем известно.', 'пятнадцать минут'),
    ('С тех пор прошло три века и два года, как известно.', 'три века'),
])
def test_a_number_written_in_words_stays_with_its_unit(text, atom):
    assert not whole(text, atom, SYLLABLE), whole(text, atom, SYLLABLE)


@pytest.mark.parametrize('text,first,second', [
    ('Один из них сказал правду, как всем известно.', 'Один', 'из'),
    ('Три раза в день и два раза ночью, как известно.', 'день', 'и'),
    ('Сто лет назад всё было иначе, как всем известно.', 'лет', 'назад'),
    ('Пять шесть семь восемь девять, как всем известно.', 'девять', 'как'),
])
def test_a_number_word_does_not_glue_what_is_not_a_number_or_a_unit(text, first, second):
    from echo_sync import portioner
    tokens = portioner._tokenize(text)
    glue = portioner._unit_marks(tokens)
    i = [t.text for t in tokens].index(first)
    assert tokens[i + 1].text == second and not glue[i], (text, first, second)


@pytest.mark.parametrize('text,atom', [
    ('Стакан вмещает 250 миллилитров воды, как всем известно.', '250 миллилитров'),
    ('Объём диска равен 2,5 гигабайта, как всем известно.', '2,5 гигабайта'),
    ('Лампа потребляет 10 ватт энергии, как всем известно.', '10 ватт'),
    ('Сеть рассчитана на 220 В напряжения, как всем известно.', '220 В'),
    ('Это длится 10 суток подряд, как всем известно.', '10 суток'),
    ('Длина стола равна 120 сантиметров, как всем известно.', '120 сантиметров'),
    ('Размер файла составляет 40 мегабайт, как всем известно.', '40 мегабайт'),
    ('Сила тока равна 5 ампер в цепи, как всем известно.', '5 ампер'),
    ('Частота равна 50 герц в сети, как всем известно.', '50 герц'),
])
def test_common_units_outside_the_first_lexicon_stay_with_their_number(text, atom):
    assert not whole(text, atom, SYLLABLE), whole(text, atom, SYLLABLE)


# --- 4d: abbreviations with a period, initials, personal names -----------------------------------------------------------

@pytest.mark.parametrize('text,atom', [
    ('Аристотель жил в IV веке до н. э. и был учителем Александра Македонского.', 'до н. э.'),
    ('Рим был основан в 753 году до н. э. на берегу Тибра, как известно.', 'н. э.'),
    ('Население города — около 70 тыс. человек, и оно медленно растёт.', '70 тыс. человек'),
    ('Годовой доход составил 5 тыс. рублей в этот раз, как известно.', '5 тыс. рублей'),
    ('Склад вмещает 3 млн. тонн груза без остатка, как известно.', 'млн. тонн'),
    ('Яблоки, груши и т. д. продаются на рынке каждый день.', 'и т. д.'),
    ('Сокращение «т. е.» значит «то есть» и вводит уточнение.', 'т. е.'),
])
def test_an_abbreviation_with_a_period_is_not_cut_at_the_period(text, atom):
    assert not whole(text, atom, SYLLABLE), whole(text, atom, SYLLABLE)


@pytest.mark.parametrize('text,atom', [
    ('Это написал Александр Сергеевич Пушкин в юности, как известно.', 'Александр Сергеевич Пушкин'),
    ('Закон открыл Исаак Ньютон в семнадцатом веке, как известно.', 'Исаак Ньютон'),
    ('На Луну первым ступил Нил Армстронг в тот день, как известно.', 'Нил Армстронг'),
    ('Композитор Римский-Корсаков писал оперы, как всем известно.', 'Римский-Корсаков'),
    ('Исаак Ньютон открыл закон всемирного тяготения давным-давно.', 'Исаак Ньютон'),
])
def test_a_full_personal_name_that_fits_is_not_cut(text, atom):
    """Only a name that fits the profile's hard limits can stay whole (a longer one would overrun them); the owner's
    «не рвать имена» holds for every profile in which the name fits."""
    from echo_sync.portioner import syllables
    from echo_sync.settings import resolve
    checked = 0
    for profile in SYLLABLE:
        cfg = resolve(H.PROFILES[profile])
        if H.product_words(atom) <= cfg['max_words'] and syllables(atom) <= cfg['max_syllables']:
            checked += 1
            parts = portions(text, H.PROFILES[profile])
            assert not H.cut_atoms(text, [atom], parts), (profile, parts)
    assert checked, 'the name fits no profile: the test proves nothing'


@pytest.mark.parametrize('text,first,second', [
    ('Москва — столица России и большой город, как известно.', 'Москва', 'столица'),     # one capital word
    ('Это важно. Москва большая, как известно, и красивая.', 'важно', 'Москва'),          # a sentence end between
    ('Иванов, Петров и Сидоров пришли вовремя, как известно.', 'Иванов', 'Петров'),       # a list with commas
    ('Вторая мировая война закончилась в 1945 году, как известно.', 'Вторая', 'мировая'),  # a capital + a lower-case word
    ('Россия и Китай торгуют давно, как всем известно.', 'Россия', 'и'),
])
def test_capital_letters_that_do_not_make_a_name_glue_nothing(text, first, second):
    from echo_sync import portioner
    tokens = portioner._tokenize(text)
    glue = portioner._unit_marks(tokens)
    i = [t.text for t in tokens].index(first)
    assert tokens[i + 1].text == second and not glue[i], (text, first, second)


def test_an_initial_that_looks_like_a_function_word_glues_nothing_after_it():
    from echo_sync import portioner
    text = 'Приказ подписал Иванов И. И., а утвердил директор.'
    tokens = portioner._tokenize(text)
    func = portioner._function_marks(tokens)
    initials = [i for i, t in enumerate(tokens) if t.initial]
    assert len(initials) == 2 and not any(func[i] for i in initials)
    assert func[[t.text for t in tokens].index('а')]          # the real conjunction «а» still needs the next word


@pytest.mark.parametrize('text,atoms', [
    ('Доклад сделал Иванов И. И., Петров П. П. его дополнил, как известно.', ['Иванов И. И.', 'Петров П. П.']),
    ('Авторы: Иванов И. И., Петров П. П. и Сидоров С. С., как известно.', ['Иванов И. И.', 'Петров П. П.', 'Сидоров С. С.']),
    ('Это стихотворение написал А. С. Пушкин в юности, как известно.', ['А. С. Пушкин']),
])
def test_initials_stay_with_their_own_surname_in_a_list(text, atoms):
    for profile in SYLLABLE:
        parts = portions(text, H.PROFILES[profile])
        assert not H.cut_atoms(text, atoms, parts), (profile, parts)
