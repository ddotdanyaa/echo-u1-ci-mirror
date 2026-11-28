"""c22-reviewfix: the review of master 4a91807 (cloud_context/tasks/REVIEW_4a91807.md, review:first-cue), confirmed findings only.
The first cue carries the fact the question asked for: not a side number before it, not a number torn from its unit or its second
number, not the negated half of «не X, а Y», not a window wider than the one of before when no number is in it, and «2 года» is a
quantity. Expectations are written here, not read from echo_sync; the stream is the one of tests/helpers_r21_first.py, both channels."""
import re

import pytest

from echo_sync.first_useful import says_the_number_asked
from helpers_r21_first import first_portion, words

CHANNELS = pytest.mark.parametrize('fast', [False, True], ids=['cloud', 'fast'])


def _has(cue, piece):
    return piece.casefold() in str(cue or '').casefold()


# 1. a side number of the asked kind is no answer: the cue goes on to the number asked (the whole sentence fits the cap)
SIDE = [
    ('Когда родился Пушкин?', 'Автор 14 поэм родился в 1799 году.', '1799 году'),
    ('Когда Наполеон вошёл в Россию?', 'Армия в 600 тысяч человек вошла в Россию в 1812 году.', '1812 году'),
    ('Какая ставка НДФЛ для нерезидентов?', 'Обычно 13 процентов, но для нерезидентов 30 процентов.', '30 процентов'),
]


@CHANNELS
@pytest.mark.parametrize('question,answer,fact', SIDE, ids=['pushkin', 'napoleon', 'ndfl'])
def test_a_side_number_is_not_the_number_asked(question, answer, fact, fast):
    first = first_portion(question, answer, fast=fast)
    assert _has(first.cue, fact), first


# 2. a number is never torn from its unit or its second number
TORN = [
    ('Какой размер кровати?', 'Размер кровати 160 на 200 сантиметров.', '160 на 200 сантиметров'),
    ('Какое давление считается нормальным?', 'Нормальное давление 120 на 80 миллиметров ртутного столба.', '120 на 80'),
    ('Какой размер листа А4?', 'Размер листа 210 на 297 миллиметров.', '210 на 297 миллиметров'),
    ('Какая плотность воды?', 'Плотность воды равна 1000 килограммов на кубический метр.', 'на кубический метр'),
    ('Какая плотность населения?', 'Плотность населения составляет 8 тысяч человек на квадратный километр.', 'на квадратный километр'),
]


@CHANNELS
@pytest.mark.parametrize('question,answer,whole', TORN, ids=['bed', 'pressure', 'a4', 'water', 'population'])
def test_a_number_keeps_its_unit_and_its_second_number(question, answer, whole, fast):
    first = first_portion(question, answer, fast=fast)
    assert _has(first.cue, whole), first


# 3. a number or date question with no number in the window: the window of before (no 10-12 word cue that says no number)
NO_NUMBER = [
    ('Когда это будет?', 'Это будет после того как директор подпишет новый приказ о реорганизации, а бухгалтерия закроет старый баланс предприятия за прошлый период.'),
    ('Когда лучше сажать томаты?', 'Томаты лучше сажать поздней весной, когда земля уже хорошо прогрелась, а заморозки точно не вернутся до самого лета.'),
    ('Когда лучше сажать томаты?', 'Томаты обычно лучше всего сажать только поздней весной, когда потеплеет везде.'),
]


@CHANNELS
@pytest.mark.parametrize('question,answer', NO_NUMBER, ids=['order', 'tomatoes', 'tomatoes-short'])
def test_no_number_in_the_window_keeps_the_portion_cap(question, answer, fast):
    first = first_portion(question, answer, fast=fast)
    assert first.cue and len(words(first.cue)) <= 9, first


@CHANNELS
def test_the_cue_does_not_end_on_the_negated_half_of_a_contrast(fast):
    first = first_portion('Что такое кит?', 'Как считают многие биологи, кит это не рыба, а млекопитающее, которое дышит лёгкими и кормит детёнышей молоком.', fast=fast)
    assert first.cue and not re.search(r'не рыба,?$', first.cue.strip()), first


# 4. «2 года» to a question for a quantity is the quantity asked, the same as «5 лет»
def test_two_years_is_a_quantity():
    assert says_the_number_asked('составляет 2 года,', 'Сколько лет гарантия?')
    assert says_the_number_asked('длилась почти 3 года,', 'Сколько лет длилась Крымская война?')
    assert not says_the_number_asked('с 2019 года', 'Сколько лет гарантия?')      # a year is still a date


@CHANNELS
def test_two_years_is_spoken_when_it_arrives(fast):
    first = first_portion('Сколько лет гарантия?', 'Гарантия на этот товар составляет 2 года, если нет другого договора.', fast=fast)
    five = first_portion('Сколько лет гарантия?', 'Гарантия на этот товар составляет 5 лет, если нет другого договора.', fast=fast)
    assert _has(first.cue, '2 года') and first.arrived == five.arrived, (first, five)


# what C7-A was written for stays: a date that is said is not lengthened to a second date
@CHANNELS
def test_the_date_asked_is_not_lengthened_to_a_second_date(fast):
    first = first_portion('Когда началась Крымская война?', 'Крымская война началась в октябре 1853 года и продлилась до 1856-го.', fast=fast)
    assert _has(first.cue, '1853') and not _has(first.cue, '1856'), first
