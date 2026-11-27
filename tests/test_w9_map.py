"""w9-map (N133, N136): the map of a compound question's parts and the abbreviation state of a call. Lines are real rows of
scripts/corpus/brain_eval_n2.json; the abbreviation state runs through the real ``portioner.expand_abbreviations`` and ``portions``."""
import json
from pathlib import Path

import pytest

from echo_sync import portioner
from echo_sync.abbrev_state import asks_expansion
from echo_sync.question_map import QuestionMap, split_parts

CORPUS = Path(__file__).resolve().parent / 'fixtures' / 'brain_eval_n2.json'


def _n2_texts():
    return {row['text'] for rows in json.loads(CORPUS.read_text(encoding='utf-8')).values() if isinstance(rows, list)
            for row in rows if isinstance(row, dict) and 'text' in row}


@pytest.mark.parametrize('question, parts', [
    ('Сколько стоит и когда привезут?', ['Сколько стоит', 'когда привезут']),
    ('Где вы учились и сколько лет уже работаете?', ['Где вы учились', 'сколько лет уже работаете']),
    ('Как называется ваша компания и сколько там сотрудников?', ['Как называется ваша компания', 'сколько там сотрудников']),
    ('Над какой задачей вы сейчас работаете и когда сдадите?', ['Над какой задачей вы сейчас работаете', 'когда сдадите']),
    ('Расскажи про НДС, про УСН и про патент', ['про НДС', 'про УСН', 'про патент']),
    ('Что такое маржа, а ещё чем она отличается от наценки?', ['Что такое маржа', 'чем она отличается от наценки']),
])
def test_a_compound_question_splits_into_its_parts(question, parts):
    assert split_parts(question) == parts


@pytest.mark.parametrize('question', ['Что такое маржинальность?', 'Сколько секунд в минуте?', 'Число пи, сколько там, три и сколько?',
                                      'Что вы чувствовали, когда это случилось?', '', None])
def test_a_single_question_is_one_part_or_none(question):
    assert len(split_parts(question)) <= 1


def test_the_corpus_lines_used_here_are_real_rows():
    texts = _n2_texts()
    for line in ('Где вы учились и сколько лет уже работаете?', 'Как называется ваша компания и сколько там сотрудников?',
                 'Над какой задачей вы сейчас работаете и когда сдадите?', 'Число пи, сколько там, три и сколько?'):
        assert line in texts, line


def test_the_second_part_stays_open_after_the_first_is_answered():
    m = QuestionMap()
    q = m.ask('Сколько стоит и когда привезут?', now=10.0)
    m.feed(q, 'Стоит пятьсот рублей.')
    assert [p['text'] for p in m.open_parts(q)] == ['когда привезут']
    m.feed(q, 'Привезут завтра утром.')
    assert m.open_parts(q) == []


def test_a_digit_or_a_number_word_closes_a_how_much_part_and_a_time_word_a_when_part():
    m = QuestionMap()
    q = m.ask('Как называется ваша компания и сколько там сотрудников?', now=1.0)
    m.feed(q, 'Компания называется Ромашка.')
    assert [p['text'] for p in m.open_parts(q)] == ['сколько там сотрудников']
    m.feed(q, 'Работает сорок человек.')
    assert m.open_parts(q) == []
    q2 = m.ask('Над какой задачей вы сейчас работаете и когда сдадите?', now=2.0)
    m.feed(q2, 'Работаем над отчётом, сдадим 15 числа.')
    assert m.open_parts(q2) == []


def test_a_new_question_does_not_close_the_old_ones_parts():
    m = QuestionMap()
    q1 = m.ask('Сколько стоит и когда привезут?', now=0.0)
    q2 = m.ask('Что такое маржа?', now=5.0)
    m.feed(q2, 'Маржа это разница между ценой и себестоимостью.')
    assert [p['text'] for p in m.open_parts(q1)] == ['Сколько стоит', 'когда привезут']


def test_odd_input_is_safe():
    m = QuestionMap()
    q = m.ask('Что такое маржа?', now=1.0)
    assert len(m.parts(q)) == 1
    m.feed(q, None), m.feed(99, 'x')
    assert m.parts(99) == []


# ---- abbreviation state (N136) --------------------------------------------------------------------------------------------------
T = {'НДС': 'налог на добавленную стоимость', 'УСН': 'упрощённая система налогообложения'}


def test_the_stock_expander_spells_it_out_in_every_answer():      # the reason of N136; the once-per-call rule itself is proved through the controller in test_c22_wiring.py
    assert portioner.expand_abbreviations('НДС платят все плательщики.', T).startswith('налог на')


@pytest.mark.parametrize('question', ['Расшифруй НДС', 'Что такое НДС?', 'Что значит НДС', 'как расшифровывается НДС'])
def test_a_question_about_the_abbreviation_asks_for_the_expansion(question):
    assert asks_expansion(question, 'НДС')
    assert not asks_expansion('Какая ставка НДС?', 'НДС')


def test_the_n1_a13_scene_is_one_ask_not_a_false_split():
    text = ('Нет-нет, подождите, статью потом. А вот если, ну, сто тысяч на два года под двадцать процентов, но уже со сложными, с процентами на проценты, '
            'тогда сколько выйдет')
    assert len(split_parts(text)) == 1


def test_the_n2_holdout_has_exactly_three_compound_questions_and_no_false_split():
    cut = {text: split_parts(text) for text in _n2_texts() if len(split_parts(text)) > 1}
    assert sorted(len(p) for p in cut.values()) == [2, 2, 2], cut
    assert {p[0] for p in cut.values()} == {'Где вы учились', 'Как называется ваша компания', 'Над какой задачей вы сейчас работаете'}
