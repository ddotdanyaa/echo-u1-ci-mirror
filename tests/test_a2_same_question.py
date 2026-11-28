"""A2: ``same_question`` takes two texts as one question only when the roles of their numbers, their «не» and their closed words are the same, not only the counts.

The confirmed defect (cloud_context/RESTORED_WORK_ORDER.md, H6 snapshot 8d86939): «Если у меня было 80 рублей и я потратил 20 рублей сколько денег осталось» and the same with 20 and 80 changed over were ONE question,
and so were «нужно не нагревать а охлаждать эту жидкость при таком давлении» and «нужно нагревать а не охлаждать …»: the counts of the numbers and of «не» are alike, the roles and the scope of the negation are not.
``FastText._fits`` (a prepared job serves the final) and ``ControlledMedia._ear_agrees`` (the cloud's words go the way the ear heard them) both take that comparison, so a ready answer could be adopted for another question.

The table is the contract. REFUSE rows: a wrong acceptance is a wrong answer said aloud, so each is checked in BOTH directions (the ear's text may be either side). ACCEPT rows: the paraphrases and the fillers that must still pass,
in the direction the code is used (``heard`` the ear's, ``asked`` the cloud's: ``asked`` may hold less than ``heard``, never a word more). SLOW rows are refusals the code makes on purpose while it cannot tell (a refusal costs one more request,
a wrong acceptance a wrong answer): they pin that choice, they are not a claim that the questions differ.
No network, no clock; the real functions on the real lemmatizer.
"""
import re

import pytest

from echo_sync import fast_text as FT
from echo_sync.classifier import strip_fillers

STRIP = strip_fillers

# --- REFUSE: the same bag of words, numbers and «не», other roles ------------------------------------------------------------------------------------------------------------
REFUSE = [
    # numbers changed over
    ('number-swap-defect', 'Если у меня было 80 рублей и я потратил 20 рублей сколько денег осталось', 'Если у меня было 20 рублей и я потратил 80 рублей сколько денег осталось'),
    ('number-swap-words', 'Если у меня было восемьдесят рублей и я потратил двадцать рублей сколько денег осталось', 'Если у меня было 20 рублей и я потратил 80 рублей сколько денег осталось'),
    ('divide', 'Сколько будет 100 разделить на 4', 'Сколько будет 4 разделить на 100'),
    ('minus', 'Сколько будет пять минус три', 'Сколько будет 3 минус 5'),
    ('order-of-operations', 'Сколько будет 2 плюс 3 умножить на 4', 'Сколько будет 3 плюс 2 умножить на 4'),
    ('percent-of', 'Сколько процентов составляют 20 рублей от 80 рублей', 'Сколько процентов составляют 80 рублей от 20 рублей'),
    ('dates', 'Сколько дней с 3 мая по 17 июня', 'Сколько дней с 17 мая по 3 июня'),
    ('range', 'Сколько нужно времени чтобы дойти с 5 до 10 километров', 'Сколько нужно времени чтобы дойти с 10 до 5 километров'),
    ('article-and-part', 'Что говорит статья 18 часть 2 налогового кодекса', 'Что говорит статья 2 часть 18 налогового кодекса'),
    ('deposit', 'Какая будет сумма если вложить 100 тысяч под 8 процентов годовых', 'Какая будет сумма если вложить 8 тысяч под 100 процентов годовых'),
    ('who-has-what', 'Если у меня 80 рублей а у него 20 сколько у нас вместе', 'Если у меня 20 рублей а у него 80 сколько у нас вместе'),
    ('whose-number', 'Если у меня 80 рублей а у него 20 сколько у нас вместе', 'Если у него 80 рублей а у меня 20 сколько у нас вместе'),
    # units
    ('unit-swap', 'Сколько будет 20 процентов от 80 рублей', 'Сколько будет 20 рублей от 80 процентов'),
    ('unit-order', 'Подскажите пожалуйста сколько будет 5 километров в метрах', 'Подскажите пожалуйста сколько будет 5 метров в километрах'),
    ('unit-other', 'Вода кипит при 100 градусах по Цельсию', 'Вода кипит при 100 градусах по Фаренгейту'),
    ('unit-speed', 'Какая скорость 10 метров в секунду', 'Какая скорость 10 метров в минуту'),
    ('unit-money', 'Сколько будет 20 рублей в долларах', 'Сколько будет 20 долларов в рублях'),
    # the scope of «не»
    ('not-defect', 'нужно не нагревать а охлаждать эту жидкость при таком давлении', 'нужно нагревать а не охлаждать эту жидкость при таком давлении'),
    ('not-moved', 'Почему мы не считаем что налог нужен', 'Почему мы считаем что налог не нужен'),
    ('not-other-verb', 'Правда ли что он не обещал вернуть деньги', 'Правда ли что он обещал не возвращать деньги'),
    ('not-subject', 'Не он сказал что опоздает', 'Он сказал что не опоздает'),
    ('not-before-number', 'Нужно оплатить не 80 рублей а 20 рублей', 'Нужно оплатить 80 рублей а не 20 рублей'),
    ('not-or-yes', 'Налог нужно платить не раз в год а каждый месяц', 'Налог нужно платить раз в год а не каждый месяц'),
    ('cannot', 'Можно ли платить налог в рассрочку', 'Нельзя ли платить налог в рассрочку'),
    ('is-or-isnt', 'Есть ли у меня право на вычет', 'Нет ли у меня права на вычет'),
    ('not-count', 'Что будет если не платить налог вовремя', 'Что будет если платить налог вовремя'),
    # the case that makes the role
    ('who-killed-whom', 'Кто убил Каина', 'Кого убил Каин'),
    ('who-gave-whom', 'Сколько яблок осталось в корзине если вчера утром Вася дал Пете три яблока', 'Сколько яблок осталось в корзине если вчера утром Петя дал Васе три яблока'),
    ('he-or-i', 'Что мне сказать если он дал мне деньги', 'Что мне сказать если я дал ему деньги'),
    ('who-whom-love', 'Кому нравится Мария', 'Кто нравится Марии'),
    ('pushkin-lermontov', 'Что сказал Пушкин Лермонтову', 'Что сказал Лермонтов Пушкину'),
    ('planets', 'Во сколько раз Юпитер по массе больше Земли', 'Во сколько раз Земля по массе больше Юпитера'),
    ('bank-client', 'Банк выдал клиенту кредит на 5 лет', 'Клиент выдал банку кредит на 5 лет'),
    ('ticket-from-to', 'Сколько стоит билет из Москвы в Питер', 'Сколько стоит билет из Питера в Москву'),
    ('percent-turned', 'Сколько будет 10 процентов от 50', 'Сколько будет 50 процентов от 10'),
    ('times-turned', 'Сколько будет в два раза больше трёх', 'Сколько будет в три раза больше двух'),
    ('me-or-him', 'Можно ли мне получить вычет за обучение детей', 'Можно ли ему получить вычет за обучение детей'),
    ('whom-owes', 'Кому я должен 500 рублей', 'Кто мне должен 500 рублей'),
    ('whom-fired', 'Кого уволили из компании после проверки', 'Кто уволил из компании после проверки'),
    ('not-over-must', 'Почему налог не нужно платить с подарков', 'Почему налог нужно не платить с подарков'),
    ('date-before-after', 'Сколько дней до 1 января осталось', 'Сколько дней после 1 января осталось'),
    ('with-or-without-experience', 'Сколько зарабатывает инженер без опыта в Москве', 'Сколько зарабатывает инженер с опытом в Москве'),
    ('rate-turned', 'Если ставка выросла с 5 до 7 процентов то что будет с ценами', 'Если ставка выросла с 7 до 5 процентов то что будет с ценами'),
    ('not-over-sum', 'Почему мне не вернули 3000 рублей за билет', 'Почему мне вернули не 3000 рублей за билет'),
    ('deposit-terms', 'Какой вклад выгоднее на 6 месяцев под 10 процентов или на 12 месяцев под 8', 'Какой вклад выгоднее на 6 месяцев под 8 процентов или на 12 месяцев под 10'),
    ('must-or-cannot', 'Надо ли платить налог если я продал машину', 'Нельзя ли платить налог если я продал машину'),
    ('for-me-him', 'Что лучше для меня взять ипотеку сейчас или подождать', 'Что лучше для него взять ипотеку сейчас или подождать'),
    ('he-and-i', 'Сколько заплатит он если я не заплачу', 'Сколько заплачу я если он не заплатит'),
    ('percent-of-sum', 'Сколько процентов от 2400 рублей составляет 15 процентов', 'Сколько процентов от 15 рублей составляет 2400 процентов'),
    ('minus-sign', 'Какая температура воды минус 5 градусов', 'Какая температура воды 5 градусов'),
    ('plus-sign-lost', 'Сколько будет если к 5 прибавить плюс 3', 'Сколько будет если к 5 прибавить 3'),
    ('mother-daughter', 'Подскажите пожалуйста правда ли что в нашей семье мать любит дочь больше чем сына', 'Подскажите пожалуйста правда ли что в нашей семье дочь любит мать больше чем сына'),
    # the person
    ('i-or-you', 'Сколько я должен заплатить налога с этой суммы', 'Сколько ты должен заплатить налога с этой суммы'),
    ('he-or-she', 'Что будет если он не заплатит налог с этой суммы', 'Что будет если она не заплатит налог с этой суммы'),
    # the closed words that change the question
    ('before-after', 'Что происходило в стране до революции семнадцатого года', 'Что происходило в стране после революции семнадцатого года'),
    ('from-to', 'Сколько километров от Москвы до Питера на машине', 'Сколько километров от Питера до Москвы на машине'),
    ('into-from', 'Сколько стоит билет в Москву', 'Сколько стоит билет из Москвы'),
    ('when-where', 'Когда началась Вторая мировая война', 'Где началась Вторая мировая война'),
    ('must-may', 'Нужно ли подавать декларацию при продаже квартиры', 'Можно ли подавать декларацию при продаже квартиры'),
    ('or-and', 'Что выгоднее взять кредит или копить деньги на машину', 'Что выгоднее взять кредит и копить деньги на машину'),
    ('with-without', 'Можно ли работать с лицензией на этом оборудовании', 'Можно ли работать без лицензии на этом оборудовании'),
    # what already was refused (the table keeps the old rows)
    ('one-number', 'Когда началась война в 1941 году', 'Когда началась война в 1914 году'),
    ('one-word', 'Что такое инерция', 'Что такое фотосинтез'),
    ('negation-count', 'Это правильно', 'Это не правильно'),
    ('ordinal', 'что говорит 27-я статья налогового кодекса', 'что говорит 28-я статья налогового кодекса'),
]

# --- SLOW: refused on purpose (the sequence of the words or of the numbers differs, the roles cannot be told) -----------------------------------------------------------------------------
SLOW = [
    ('multiply-commutes', 'Сколько будет 48 умножить на 10', 'Сколько будет 10 умножить на 48'),
    ('clauses-turned', 'Сколько осталось если было 80 рублей и потратил 20', 'Сколько осталось если потратил 20 и было 80 рублей'),
    ('short-reorder', 'В каком году родился Пушкин', 'Пушкин родился в каком году'),
]

# --- ACCEPT: one question said another way ----------------------------------------------------------------------------------------------------------------------------------
ACCEPT = [
    # punctuation, capitals, ё, a leading filler
    ('question-mark', 'Что такое амортизация', 'Что такое амортизация?'),
    ('capital', 'что такое амортизация', 'Что такое амортизация'),
    ('yo', 'Сколько будет всё вместе', 'Сколько будет всё вместе?'),
    ('leading-so', 'так что такое амортизация', 'Что такое амортизация'),
    ('leading-well', 'ну так в каком году было крещение руси', 'В каком году было крещение Руси?'),
    # numbers said and written
    ('number-words', 'Сколько будет сорок восемь умножить на десять', 'Сколько будет 48 умножить на 10'),
    ('defect-words', 'Если у меня было восемьдесят рублей и я потратил двадцать рублей сколько денег осталось', 'Если у меня было 80 рублей и я потратил 20 рублей, сколько денег осталось?'),
    ('defect-commas', 'Если у меня было 80 рублей и я потратил 20 рублей сколько денег осталось', 'Если у меня было 80 рублей, и я потратил 20 рублей, сколько денег осталось?'),
    ('year-ordinal', 'в каком году началась война в тысяча девятьсот сорок первом году', 'В каком году началась война в 1941 году?'),
    ('article', 'что говорит двадцать первая статья налогового кодекса', 'Что говорит 21 статья Налогового кодекса?'),
    ('decimal', 'сколько будет три и пять десятых умножить на два', 'Сколько будет 3,5 умножить на 2?'),
    # units, said and written
    ('unit-sign', 'Сколько будет 80 рублей в долларах по курсу 90', 'Сколько будет 80 ₽ в долларах по курсу 90?'),
    ('unit-celsius', 'Что будет с водой при ста градусах Цельсия', 'Что будет с водой при 100 °C?'),
    ('unit-percent', 'Сколько будет десять процентов от двухсот', 'Сколько будет 10 % от 200?'),
    ('unit-short', 'Сколько метров в пяти километрах', 'Сколько метров в 5 км?'),
    ('unit-minutes', 'Сколько секунд в пяти минутах', 'Сколько секунд в 5 минутах?'),
    # an ending, a case at the same role, a form of the same word
    ('ending', 'что такое амортизации', 'Что такое амортизация'),
    ('case-same-role', 'Что такое налог на прибыль организаций', 'Что такое налог на прибыль организации?'),
    ('case-place', 'Сколько стоит доставка в Москву', 'Сколько стоит доставка в Москве?'),
    ('in-vo', 'Сколько стоит поездка во Францию', 'Сколько стоит поездка в Францию?'),
    ('same-roles-other-order', 'Сколько яблок осталось если Вася дал Пете три яблока', 'Сколько яблок осталось если Пете Вася дал три яблока'),
    # words more in the ear's text (the cloud said less), fillers inside
    ('plus-please', 'Скажите пожалуйста что такое амортизация основных средств', 'Что такое амортизация основных средств?'),
    ('half-filler', 'Если у меня было э-э 80 рублей и я потратил ну вот 20 рублей сколько денег осталось', 'Если у меня было 80 рублей и я потратил 20 рублей сколько денег осталось?'),
    ('so-to-say', 'Сколько будет пять умножить на пять э-э', 'Сколько будет 5 умножить на 5?'),
    ('plus-my', 'Если у меня было 80 рублей и я потратил 20 рублей сколько денег осталось', 'Если у меня было 80 рублей, и я потратил 20 рублей, сколько денег у меня осталось?'),
    ('not-same-scope', 'нужно не нагревать а охлаждать эту жидкость при таком давлении', 'Нужно не нагревать, а охлаждать эту жидкость при таком давлении.'),
    ('not-filler-lead', 'ну нужно не нагревать а охлаждать эту жидкость при таком давлении', 'Нужно не нагревать а охлаждать эту жидкость при таком давлении'),
    ('not-plus-word', 'Почему он не пришёл вчера на работу', 'Почему он не пришёл на работу?'),
    ('not-yearly-comma', 'Налог нужно платить не раз в год а каждый месяц', 'Налог нужно платить не раз в год, а каждый месяц?'),
    ('who-whom-same', 'Кто убил Каина', 'Кто убил Каина?'),
    ('plus-sign', 'сколько будет два плюс три', 'Сколько будет 2 + 3?'),
    ('ordinal-year', 'что случилось в двухтысячном году', 'Что случилось в 2000 году?'),
    ('percent-sign', 'сколько будет пятнадцать процентов от двух тысяч', 'Сколько будет 15% от 2000?'),
    ('ear-drops-unit', 'если у меня было восемьдесят рублей я потратил двадцать сколько осталось', 'Если у меня было 80 рублей и я потратил 20 рублей, сколько осталось?'),
    ('ear-drops-preposition', 'налог прибыль организаций ставка', 'Налог на прибыль организаций ставка'),
    ('thousands', 'какой налог платит самозанятый с дохода в триста тысяч рублей', 'Какой налог платит самозанятый с дохода в 300 000 рублей?'),
    ('not-comma', 'я не понимаю как считать налог на имущество', 'Я не понимаю, как считать налог на имущество.'),
    ('not-you', 'почему вы не согласны с этой оценкой', 'Почему вы не согласны с этой оценкой?'),
    ('two-numbers-words', 'сколько человек в классе если девочек двенадцать а мальчиков пятнадцать', 'Сколько человек в классе, если девочек 12, а мальчиков 15?'),
    ('title-quotes', 'кто написал войну и мир', 'Кто написал «Войну и мир»?'),
    ('place-name', 'в каком году была битва на калке', 'В каком году была битва на Калке?'),
    ('mother-daughter-same', 'Подскажите пожалуйста правда ли что в нашей семье мать любит дочь больше чем сына', 'Правда ли что в нашей семье мать любит дочь больше чем сына?'),
    ('prep-same', 'Сколько километров от Москвы до Питера на машине', 'Сколько километров от Москвы до Питера на машине?'),
    ('ask-first', 'Сколько денег осталось если у меня было 80 рублей и я потратил 20 рублей', 'Если у меня было 80 рублей и я потратил 20 рублей, сколько денег осталось?'),
    ('ask-last', 'Если у меня было 80 рублей и я потратил 20 рублей сколько денег осталось', 'Сколько денег осталось, если у меня было 80 рублей и я потратил 20 рублей?'),
    ('modal-same', 'Нужно ли подавать декларацию при продаже квартиры', 'Нужно ли подавать декларацию при продаже квартиры?'),
]


def both(heard, asked):
    return FT.same_question(heard, asked, strip=STRIP), FT.same_question(asked, heard, strip=STRIP)


@pytest.mark.parametrize('name, heard, asked', REFUSE, ids=[row[0] for row in REFUSE])
def test_the_roles_differ_the_texts_are_not_one_question(name, heard, asked):
    assert both(heard, asked) == (False, False)


@pytest.mark.parametrize('name, heard, asked', SLOW, ids=[row[0] for row in SLOW])
def test_the_roles_cannot_be_told_so_it_refuses(name, heard, asked):
    assert both(heard, asked) == (False, False)


@pytest.mark.parametrize('name, heard, asked', ACCEPT, ids=[row[0] for row in ACCEPT])
def test_one_question_said_another_way_passes(name, heard, asked):
    assert FT.same_question(heard, asked, strip=STRIP) is True


def test_the_table_has_no_row_twice_and_every_class_of_the_task():
    rows = [row[0] for row in REFUSE + SLOW + ACCEPT]
    assert len(rows) == len(set(rows)) and len(REFUSE) >= 40 and len(ACCEPT) >= 30


# --- the start of an utterance (the cloud's words so far) -----------------------------------------------------------------------------------------------------------------------
PARTIAL_REFUSE = [
    ('numbers-turned', 'Если у меня было 80 рублей и я потратил 20 рублей сколько денег осталось', 'Если у меня было 20 рублей и я потратил 80'),
    ('not-moved', 'нужно не нагревать а охлаждать эту жидкость при таком давлении', 'нужно нагревать а не охлаждать эту'),
    ('not-pending', 'нужно не нагревать а охлаждать эту жидкость при таком давлении', 'нужно нагревать а не'),
    ('from-to', 'Сколько километров от Москвы до Питера на машине', 'Сколько километров от Питера до Москвы'),
    ('whose-number', 'Если у меня 80 рублей а у него 20 сколько у нас вместе', 'Если у него 80 рублей а у меня 20 сколько у нас'),
    ('before-after', 'Что происходило в стране до революции семнадцатого года', 'Что происходило в стране после революции'),
    ('who-whom', 'Кто убил Каина и почему его не наказали', 'Кого убил Каин и почему его не'),
]
PARTIAL_ACCEPT = [
    ('defect-start', 'Если у меня было 80 рублей и я потратил 20 рублей сколько денег осталось', 'Если у меня было 80 рублей и я потратил 20'),
    ('defect-words', 'Если у меня было восемьдесят рублей и я потратил двадцать рублей сколько денег осталось', 'Если у меня было 80 рублей и я потр'),
    ('not-start', 'нужно не нагревать а охлаждать эту жидкость при таком давлении', 'Нужно не нагревать, а охлаж'),
    ('not-cut-after-not', 'нужно не нагревать а охлаждать эту жидкость при таком давлении', 'Нужно не'),
    ('from-to', 'Сколько километров от Москвы до Питера на машине', 'Сколько километров от Москвы до Пит'),
    ('whose-number', 'Если у меня 80 рублей а у него 20 сколько у нас вместе', 'Если у меня 80 рублей а у него'),
]


@pytest.mark.parametrize('name, heard, partial', PARTIAL_REFUSE, ids=[row[0] for row in PARTIAL_REFUSE])
def test_a_start_with_other_roles_does_not_go_the_way_the_ear_heard(name, heard, partial):
    assert FT.same_start(heard, partial, strip=STRIP) is False
    assert FT.same_start(heard, partial, strip=STRIP, open_end=False) is False


@pytest.mark.parametrize('name, heard, partial', PARTIAL_ACCEPT, ids=[row[0] for row in PARTIAL_ACCEPT])
def test_a_start_with_the_same_roles_goes_the_way_the_ear_heard(name, heard, partial):
    assert FT.same_start(heard, partial, strip=STRIP) is True


# --- the table made wide: mutants of spoken questions -------------------------------------------------------------------------------------------------------------------------
# The same rows by rule: a base question, then (a) every pair of its different numbers turned round, (b) its «не» moved over the next word, (c) the harmless changes of an ear and a cloud (a mark, a capital, numbers in words,
# a filler inside, a polite word in front). (a) and (b) are wrong answers if accepted, (c) are the paraphrases that must pass.
BASES = [
    'Если у меня было 80 рублей и я потратил 20 рублей сколько денег осталось',
    'Сколько будет 48 умножить на 10',
    'Какой налог нужно заплатить с 120 тысяч рублей при ставке 13 процентов',
    'Сколько часов ехать от Москвы до Казани со скоростью 80 километров в час если путь 800 километров',
    'Через сколько часов поезд проедет 300 километров если скорость 60 километров в час',
    'Что говорит статья 18 часть 2 налогового кодекса о вычете',
    'Сколько воды нужно взять на 5 литров сиропа если разводить 1 к 4',
    'Нужно не нагревать а охлаждать эту жидкость при таком давлении',
    'Почему вы не считаете что налог на прибыль нужно платить раз в квартал а не раз в год',
    'Можно ли не платить налог если доход меньше 50 тысяч рублей в год',
    'Что произойдёт если вода нагреется до 100 градусов при давлении в 2 атмосферы',
    'Сколько составляет 15 процентов от 2400 рублей',
    'Почему он не пришёл на встречу в 10 утра а пришёл только в 12',
    'Сколько мне платить за аренду 45 квадратных метров по 500 рублей за метр',
    'Что весит больше 3 килограмма яблок или 2 килограмма груш',
    'Если я вложу 100 тысяч под 8 процентов на 3 года сколько получу',
    'Сколько дней между 12 марта и 25 апреля',
    'Нужно ли подавать декларацию при продаже квартиры которой владел 4 года',
    'Как перевести 5 миль в километры по курсу 1 миля к 1,6 километра',
    'Какая температура плавления железа в градусах Цельсия 1538 или 1200',
    'Кто победил в войне 1812 года Россия или Франция и сколько лет прошло с 1812 до 1941 года',
    'Скажите сколько будет 7 умножить на 8 и потом прибавить 6',
    'Мы не должны превышать бюджет в 30 тысяч рублей на 2 месяца',
    'Если на складе было 500 коробок и вчера отгрузили 120 а сегодня 80 сколько осталось',
    'Сколько будет если из 1000 вычесть 250 и потом разделить на 3',
    'Какой процент составляют 30 студентов от 120 человек в группе',
    'В магазине яблоки стоят 90 рублей за килограмм а груши 140 сколько стоит 2 килограмма яблок и 3 килограмма груш',
    'Кредит 500 тысяч на 24 месяца под 12 процентов какой будет ежемесячный платёж',
    'Не нужно подавать заявление до 1 июня а нужно после 15 июля',
    'Он не позвонил в 8 вечера а написал только в 11 ночи',
    'Она не купила 3 билета а взяла только 2 и сколько это стоит по 700 рублей',
    'Скорость света около 300 тысяч километров в секунду а звука около 340 метров в секунду',
    'Из 200 студентов сдали экзамен 150 а 50 не сдали сколько это процентов',
]
SPOKEN = {'1': 'один', '2': 'два', '3': 'три', '4': 'четыре', '5': 'пять', '8': 'восемь', '10': 'десять', '12': 'двенадцать', '15': 'пятнадцать', '20': 'двадцать', '25': 'двадцать пять', '30': 'тридцать',
          '50': 'пятьдесят', '60': 'шестьдесят', '80': 'восемьдесят', '100': 'сто', '120': 'сто двадцать', '300': 'триста', '500': 'пятьсот', '800': 'восемьсот'}


def number_swaps(text):
    spots = list(re.finditer(r'\d+(?:,\d+)?', text))
    for i, first in enumerate(spots):
        for second in spots[i + 1:]:
            if first.group() != second.group():
                yield text[:first.start()] + second.group() + text[first.end():second.start()] + first.group() + text[second.end():]


def not_moved(text):
    words = text.split()
    for at, word in enumerate(words[:-2]):
        if word.lower() == 'не' and len(words[at + 1]) >= 5:
            yield ' '.join(words[:at] + [words[at + 1], 'не'] + words[at + 2:])


def spoken_numbers(text):
    return re.sub(r'\b\d+\b(?!,)', lambda found: SPOKEN.get(found.group(), found.group()), text)


def with_filler(text):
    words = text.split()
    return ' '.join(words[:3] + ['э-э'] + words[3:-1] + ['ну', words[-1]])


SWAPS = [(f'b{n}-{i}', base, other) for n, base in enumerate(BASES) for i, other in enumerate(number_swaps(base))]
MOVES = [(f'b{n}-{i}', base, other) for n, base in enumerate(BASES) for i, other in enumerate(not_moved(base))]
HARMLESS = [(f'b{n}-{kind}', base, other) for n, base in enumerate(BASES) for kind, other in (
    ('mark', base + '?'), ('capital', base.lower()), ('words', spoken_numbers(base)), ('filler', with_filler(base)), ('polite', 'скажите пожалуйста ' + base[0].lower() + base[1:]))]


@pytest.mark.parametrize('name, base, other', SWAPS, ids=[row[0] for row in SWAPS])
def test_every_pair_of_numbers_turned_round_is_another_question(name, base, other):
    assert both(base, other) == (False, False)


@pytest.mark.parametrize('name, base, other', MOVES, ids=[row[0] for row in MOVES])
def test_a_not_over_the_next_word_is_another_question(name, base, other):
    assert both(base, other) == (False, False)


@pytest.mark.parametrize('name, base, other', HARMLESS, ids=[row[0] for row in HARMLESS])
def test_the_harmless_changes_of_an_ear_and_a_cloud_pass(name, base, other):
    asked, heard = (base, other) if name.endswith('polite') or name.endswith('filler') else (other, base)
    assert FT.same_question(heard, asked, strip=STRIP) is True


def test_the_wide_table_is_wide():
    assert len(SWAPS) >= 50 and len(MOVES) >= 9 and len(HARMLESS) >= 150, (len(SWAPS), len(MOVES), len(HARMLESS))


# --- where the comparison is used ---------------------------------------------------------------------------------------------------------------------------------------------
from test_h1_fast_text import manager      # noqa: E402 - the scripted stream and the fake clock of the H1 tests

DEFECT = 'Если у меня было 80 рублей и я потратил 20 рублей сколько денег осталось'
TURNED = 'Если у меня было 20 рублей и я потратил 80 рублей сколько денег осталось'
HEATING = 'нужно не нагревать а охлаждать эту жидкость при таком давлении'
COOLING = 'нужно нагревать а не охлаждать эту жидкость при таком давлении'


@pytest.mark.parametrize('ear, final', [(DEFECT, TURNED), (HEATING, COOLING)], ids=['numbers', 'not'])
def test_a_prepared_job_is_not_adopted_for_the_question_with_the_roles_turned_round(ear, final):
    fast, fake, _ = manager()
    assert fast.prepare(ear) is True
    first = fake.run(0)
    first.say('Осталось 60 рублей.')
    assert fast.release(qid='u1', turn='fast-1', epoch=1, question=final) == 'started'
    second = fake.run(1)
    assert first.cancelled.is_set() and second.question == final, 'the job of the other question is cancelled, a new one starts on the final'
    fast.close()


@pytest.mark.parametrize('ear, final', [(DEFECT, 'Если у меня было 80 рублей, и я потратил 20 рублей, сколько денег осталось?'), (HEATING, 'Нужно не нагревать, а охлаждать эту жидкость при таком давлении.')], ids=['numbers', 'not'])
def test_a_prepared_job_is_adopted_for_the_same_question_said_another_way(ear, final):
    fast, fake, _ = manager()
    fast.prepare(ear)
    fake.run(0).say('Осталось 60 рублей.')
    assert fast.release(qid='u1', turn='fast-1', epoch=1, question=final) == 'adopted' and len(fake.runs) == 1
    fast.close()


import logging                                                                    # noqa: E402
from test_h3_tempo import TICK, call                                             # noqa: E402, F401 - call is the fixture
from test_h4_ear_first import SILENCE, decisions, final, question                # noqa: E402


@pytest.mark.parametrize('ear, partial', [('сколько будет сто разделить на четыре', 'Сколько будет 4 разделить на'),
                                          ('сколько часов ехать от москвы до казани', 'Сколько часов ехать от Казани до'),
                                          ('почему нужно не нагревать а охлаждать жидкость', 'Почему нужно нагревать а не охлаждать')], ids=['numbers', 'from-to', 'not'])
def test_a_start_of_the_cloud_with_the_roles_turned_round_leaves_the_question_to_the_final(call, caplog, ear, partial):
    rig = call(fast_text='on')
    with caplog.at_level(logging.INFO, logger='echo-sync'):
        question(rig, ear, partial=partial)
        rig.pump(SILENCE)
        rig.job_says(0, 'Осталось 60 рублей.')
        rig.pump(TICK * 2)
    assert rig.c.question_id is None and rig.said() == [] and decisions(caplog, 'ear first=dropped reason=cloud_disagrees'), 'nothing is said on the ear before the final'
    final(rig, 'u1', partial + ' ещё')


# --- said_within: a part cut out of the whole (the cloud cut an utterance of the ear elsewhere) -------------------------------------------------------------------------------------
# ControlledMedia._ear_first_again takes a final of another turn for a PIECE of what the ear opened when ``said_within`` says so, and then says nothing to it: a piece with the numbers turned round is no piece.
WHOLE_RUB = 'Если у меня было 80 рублей и я потратил 20 рублей сколько денег осталось'
WITHIN_REFUSE = [
    ('numbers-turned', WHOLE_RUB, 'Если у меня было 20 рублей и я потратил 80 рублей'),
    ('number-of-another-role', WHOLE_RUB, 'Если у меня было 20 рублей'),
    ('number-of-another-role-2', WHOLE_RUB, 'я потратил 80 рублей сколько денег осталось'),
    ('not-moved', HEATING, 'нужно нагревать а не охлаждать эту жидкость'),
    ('not-lost', HEATING, 'нужно нагревать эту жидкость'),
    ('from-to', 'Сколько километров от Москвы до Питера на машине', 'Сколько километров от Питера до Москвы'),
    ('whose-number', 'Если у меня 80 рублей а у него 20 сколько у нас вместе', 'Если у него 80 рублей а у меня 20'),
    ('whom-who', 'Скажите пожалуйста кого уволили из компании после проверки', 'кто уволил из компании после проверки'),
    ('person', 'Скажите пожалуйста сколько я должен заплатить налога с этой суммы', 'сколько ты должен заплатить налога'),
    ('before-after', 'Что происходило в стране до революции семнадцатого года', 'в стране после революции семнадцатого года'),
    ('unit', 'Сколько будет 20 процентов от 80 рублей', 'Сколько будет 20 рублей от 80'),
    ('sign', 'Какая температура воды минус 5 градусов', 'Какая температура воды 5 градусов минус'),
]
WITHIN_ACCEPT = [
    ('whole', WHOLE_RUB, WHOLE_RUB + '?'),
    ('first-clause', WHOLE_RUB, 'Если у меня было 80 рублей'),
    ('both-numbers', WHOLE_RUB, 'Если у меня было 80 рублей и я потратил 20 рублей'),
    ('second-clause', WHOLE_RUB, 'я потратил 20 рублей сколько денег осталось'),
    ('cut-in-the-unit', WHOLE_RUB, 'рублей и я потратил 20 рублей'),
    ('the-question', WHOLE_RUB, 'сколько денег осталось'),
    ('the-last-number', WHOLE_RUB, '20 рублей сколько денег осталось'),
    ('not-head', HEATING, 'нужно не нагревать'),
    ('not-tail', HEATING, 'а охлаждать эту жидкость при таком давлении'),
    ('not-cut-after-not', HEATING, 'нагревать а охлаждать эту жидкость'),
    ('not-middle', HEATING, 'не нагревать а охлаждать'),
    ('from-to', 'Сколько километров от Москвы до Питера на машине', 'от Москвы до Питера на машине'),
    ('whose-number', 'Если у меня 80 рублей а у него 20 сколько у нас вместе', 'а у него 20 сколько у нас вместе'),
    ('article', 'Что говорит 21 статья Налогового кодекса', 'Статья 21'),
    ('article-said', 'двадцать первая статья налогового кодекса', 'Статья 21'),
    ('cases-of-code', 'Что говорит 21 статья Налогового кодекса', 'Налогового кодекса'),
]


@pytest.mark.parametrize('name, whole, piece', WITHIN_REFUSE, ids=[row[0] for row in WITHIN_REFUSE])
def test_a_piece_with_other_roles_is_no_piece_of_the_whole(name, whole, piece):
    assert FT.said_within(whole, piece, strip=STRIP) is False


@pytest.mark.parametrize('name, whole, piece', WITHIN_ACCEPT, ids=[row[0] for row in WITHIN_ACCEPT])
def test_a_piece_with_the_same_roles_is_a_piece_of_the_whole(name, whole, piece):
    assert FT.said_within(whole, piece, strip=STRIP) is True
