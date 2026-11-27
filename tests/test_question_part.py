"""W2 / R06: ``question_part.extract`` - the question WITH its conditions out of a long utterance, the remark around it left out. Table of 300+ rows both ways:
every row is built from parts whose role is known by construction (an aside, a condition, a question), the expectation is not read off the module."""
import itertools
import pytest

from echo_sync.question_part import extract, extract_pair

ASIDES = [    # (text, why it is no part of the question)
    'Я вчера сдавал экзамен, всё прошло нормально.', 'Сейчас третья минута идёт.', 'Так, подождите секунду.', 'Мне немного страшно.',
    'Ответ шёл 13 секунд.', 'Подсказка пришла слишком долго.', 'Ну ладно, начинаем.', 'Сейчас я выпью воды.', 'Мы с коллегой вчера это обсуждали.',
]
CONDITIONS = [    # (text, needs_current_data of it)
    ('', False), ('Берём 2024 год, ставка 10%, без НДС.', True), ('Допустим, оборот 5 миллионов рублей.', False), ('Пусть срок вклада 3 года.', False),
    ('Считаем, что налоговый период квартал.', False), ('Не 15, а 50.', False),
]
QUESTIONS = [     # (text, needs_current_data of it)
    ('Какова ставка НДС?', True), ('Сколько получится?', False), ('Что такое пятнадцатый счёт в плане счетов?', False), ('Почему амортизация начисляется ежемесячно?', False),
    ('Чему равен налог?', False), ('Объясни, чем отличается дебет от кредита.', False),
]
ROWS = [(a, c, q) for a, c, q in itertools.product(ASIDES, CONDITIONS, QUESTIONS)]
PERSONAL_Q = ['Сколько у меня на счёте?', 'Какой у меня остаток по кредиту?', 'Мой билет какой номер?', 'Что я должен сдать завтра?']


def test_table_is_big_enough():
    assert len(ROWS) + len(ASIDES) * len(PERSONAL_Q) >= 300


@pytest.mark.parametrize('aside,cond,question', ROWS)
def test_aside_dropped_condition_and_question_kept(aside, cond, question):
    part = extract(' '.join(x for x in (aside, cond[0], question[0]) if x))
    assert part.kind == 'question'
    assert part.text == ' '.join(x for x in (cond[0], question[0]) if x)
    assert part.question == question[0] and part.conditions == ((cond[0],) if cond[0] else ())
    assert [d[0] for d in part.dropped] == [aside]
    assert not part.personal and part.scope == 'public' and part.current == (cond[1] or question[1])
    assert part.public_query == part.text


@pytest.mark.parametrize('aside,cond,question', ROWS[::7])
def test_same_without_aside_changes_nothing(aside, cond, question):
    part = extract(' '.join(x for x in (cond[0], question[0]) if x))
    assert part.text == ' '.join(x for x in (cond[0], question[0]) if x) and part.dropped == ()


@pytest.mark.parametrize('aside', ASIDES)
@pytest.mark.parametrize('question', PERSONAL_Q)
def test_personal_request_stays_personal(aside, question):
    part = extract(aside + ' ' + question)
    assert part.question == question and part.personal and part.scope == 'personal' and part.public_query == ''
    assert [d[0] for d in part.dropped] == [aside]


def test_personal_intro_does_not_make_a_public_question_personal():
    part = extract('Я вчера плохо спал, мне тревожно. Что такое проводка?')
    assert part.question == 'Что такое проводка?' and not part.personal and part.public_query == 'Что такое проводка?'


def test_personal_condition_is_kept_and_blocks_the_public_lookup_of_it():
    part = extract('У меня доход 100 тысяч рублей. Какой налог платить?')
    assert part.conditions == ('У меня доход 100 тысяч рублей.',) and part.personal and part.text.startswith('У меня доход')
    assert part.public_query == 'Какой налог платить?'


def test_sey_chas_in_the_aside_is_not_current_but_in_the_request_it_is():
    assert not extract('Вот сейчас третья минута идёт, что такое пятнадцатый счёт в плане счетов').current
    assert extract('Какая сейчас ставка НДС?').current
    assert extract('Вот сейчас жарко. Какая сейчас ставка НДС?').current


@pytest.mark.parametrize('text,aside', [('Ответ шёл 13 секунд. Сколько будет 13 на 4?', 'Ответ шёл 13 секунд.'), ('Я ждал 20 секунд. Что такое НДС?', 'Я ждал 20 секунд.'),
                                       ('Что такое НДС? 13 секунд.', '13 секунд.'), ('Что такое НДС?13 секунд', '13 секунд')])
def test_number_as_a_time_measure_is_dropped(text, aside):
    assert [d[0] for d in extract(text).dropped] == [aside]


@pytest.mark.parametrize('text', ['Срок 13 дней, ставка 10%. Сколько процентов набежит?', 'Через 5 минут курс какой?', 'Депозит на 13 секунд? Сколько это в часах?',
                                  'Мне 25 лет. Какой вычет положен?', 'Пауза 20 секунд, потом 30. Сколько всего?'])
def test_number_as_a_condition_is_kept(text):
    part = extract(text)
    assert part.text == text and part.dropped == ()


def test_correction_is_kept_with_the_short_question():
    part = extract('Не 15, а 50. Сколько это в процентах?')
    assert part.correction == ('15', '50') and part.text == 'Не 15, а 50. Сколько это в процентах?' and part.conditions == ('Не 15, а 50.',)
    part = extract('Ну, не пятнадцать, а пятьдесят, сколько получится')
    assert part.correction == ('пятнадцать', 'пятьдесят') and 'не пятнадцать, а пятьдесят' in part.text


def test_the_year_rate_vat_case():
    part = extract('Берём 2024 год, ставка 10%, без НДС. Какова сумма?')
    assert part.conditions == ('Берём 2024 год, ставка 10%, без НДС.',) and part.question == 'Какова сумма?'


def test_condition_after_the_question_is_kept():
    part = extract('Какова сумма? Берём 2024 год, ставка 10%, без НДС.')
    assert part.question == 'Какова сумма?' and part.conditions == ('Берём 2024 год, ставка 10%, без НДС.',)


def test_unpunctuated_run():
    part = extract('так вот сейчас третья минута идёт и значит что такое пятнадцатый счёт в плане счетов')
    assert part.kind == 'question' and part.question.startswith('что такое пятнадцатый счёт') and not part.current


@pytest.mark.parametrize('text,scope', [('Вот по этому материалу: как считается износ?', 'material'), ('А в тексте что сказано про амортизацию?', 'material'),
                                        ('Что такое износ?', 'public'), ('Из лекции: почему проводка двойная?', 'material')])
def test_material_without_its_title(text, scope):
    part = extract(text)
    assert part.scope == scope and (part.public_query == '') == (scope == 'material')


def test_material_with_a_title():
    part = extract('В лекции про амортизацию что сказано о линейном способе?', titles=('Лекция про амортизацию',))
    assert part.scope == 'material' and part.material == 'Лекция про амортизацию'


@pytest.mark.parametrize('text,topic', [('Так, подождите секунду. Пятнадцатый счёт в плане счетов.', 'Пятнадцатый счёт в плане счетов.'),
                                        ('Мне немного страшно. Семнадцатая статья налогового кодекса', 'Семнадцатая статья налогового кодекса'),
                                        ('Ну ладно. Статья 218', 'Статья 218'), ('Сейчас третья минута. Амортизация линейным способом', 'Амортизация линейным способом')])
def test_topic_without_a_question_word_after_a_remark(text, topic):
    part = extract(text)
    assert part.kind == 'topic' and part.question == topic and part.text == topic


@pytest.mark.parametrize('text', ['Привет, ты меня слышишь?', 'Ну ладно, начинаем.', 'Мне немного страшно.', 'Пятнадцатый счёт', 'Берём 2024 год, ставка 10%, без НДС.', 'Спасибо, хорошо.'])
def test_nothing_to_extract_returns_the_text_unchanged(text):
    part = extract(text)
    assert part.kind == 'none' and part.text == text


@pytest.mark.parametrize('text', ['Я не знаю, сколько это.', 'Как обычно, всё хорошо.', 'Я думаю, что всё получится.', 'Когда я шёл, было жарко.'])
def test_indirect_and_conjunction_words_are_no_question(text):
    assert extract(text).kind == 'none'


def test_numbers_and_not_of_the_kept_parts_survive():
    for text in ['Я устал. Это не 15 процентов, а 50. Сколько будет?', 'Ставка не 20, ладно. Сколько налог?', 'Ответ шёл 7 секунд. Не берём НДС, сумма 1000. Сколько итого?']:
        part = extract(text)
        for token in ('не', '15', '50', '20', '1000'):
            assert (token in text.split() or token in text.replace(',', '').replace('.', '').split()) <= (token in part.text.replace(',', '').replace('.', '').casefold().split())


def test_two_recognitions_keep_the_longer_condition():
    heard = 'Берём 2024 год ставка 10% сколько получится'
    cloud = 'Берём 2024 год, ставка 10%, без НДС. Сколько получится?'
    pair = extract_pair(heard, cloud)
    assert 'без НДС' in pair.text and not pair.conflict
    split = extract_pair('Ставка 10%. Сколько получится?', 'Ставка 15%. Сколько получится?')
    assert split.conflict


def test_compound_question_keeps_both_and_the_aside_between_goes():
    part = extract('Что такое проводка? Я немного волнуюсь. И сколько будет пять на пять?')
    assert part.kind == 'compound' and part.text == 'Что такое проводка? И сколько будет пять на пять?'


def test_abbreviation_is_no_sentence_end():
    part = extract('Согласно ст. 218 НК РФ, что такое стандартный вычет?')
    assert part.question.endswith('что такое стандартный вычет?') and 'ст. 218' in part.text


def test_empty_and_garbage():
    for text in ('', None, '   ', '...', '?'):
        assert extract(text).kind == 'none'


# ---- w3-integ item 9: one cut, ``classifier.question_part`` (H7 item 0), with ``extract`` for what goes with the question. The same table through it. -------------------
from echo_sync.classifier import question_part      # noqa: E402

TOPIC_KEPT = {('Так, подождите секунду.', 'Сколько получится?'), ('Подсказка пришла слишком долго.', 'Сколько получится?')}   # H7: a question of two words takes the sentence before it for its topic; extract calls this one 'unrelated', no positive sign of talk


@pytest.mark.parametrize('aside,cond,question', ROWS)
def test_the_one_cut_keeps_the_condition_with_its_question_and_leaves_the_aside(aside, cond, question):
    part = question_part(' '.join(x for x in (aside, cond[0], question[0]) if x))
    if not cond[0] and (aside, question[0]) in TOPIC_KEPT:
        assert part.strip(' .?') == f'{aside} {question[0]}'.strip(' .?'); return
    assert part.strip(' .?') == ' '.join(x for x in (cond[0], question[0]) if x).strip(' .?')


@pytest.mark.parametrize('text', ['Двадцать пять. Хорошо, считаем быстро. Так, в каком году было крещение Руси', 'значит вопрос по экономике, допустим, скажем что такое инфляция'])
def test_a_number_read_back_or_a_preface_is_no_condition(text):
    assert question_part(text) in ('в каком году было крещение Руси', 'что такое инфляция')
