"""C7-A (live run 20261103-164741, w3_02, w3_03, w3_10): a question that asks for a number or a date gets it in the FIRST cue.

«Когда началась Крымская война?» was cued «Крымская война началась в октябре» and the year 1853 came in cue 2, 21.7 s after the question;
«Когда было крещение Руси» got «Крещение Руси обычно датируют», «Когда была Полтавская битва?» «Полтавская битва состоялась». The F1 first
portion counted any new content word as new information. The class: when the question asks for a number or a date (an interrogative
«когда», «в каком году», «сколько», «какого числа», «какой процент / какая ставка / какая сумма…», read on the question text), the first
portion extends within its window - raised for this case to MEANING_NUMBER_FIRST_MAX_WORDS words and MEANING_NUMBER_EXTRA_SYLLABLES more
syllables - until it holds a number the question does not (digits or number words). A text that brings no number there is cued as
before, and no other kind of question waits for anything.

Expected cues are written by hand from the texts.
"""
from __future__ import annotations

import re

import pytest

from echo_sync.first_useful import asks_for_number, first_cue
from echo_sync.portioner import MEANING_FIRST_MAX_WORDS, MEANING_NUMBER_FIRST_MAX_WORDS, portions
from echo_sync.settings import CALL_SETTINGS

WORD = re.compile(r"[^\W_]+(?:[-’'][^\W_]+)*")


def words(text):
    return WORD.findall(text)


def streamed_first_cue(question, answer, settings=CALL_SETTINGS):
    """The first cue as the call path releases it: the answer arrives word by word (with its punctuation); ``(cue, words arrived)``."""
    ends = [m.end() for m in WORD.finditer(answer)]
    for k, end in enumerate(ends, 1):
        final = k == len(ends)
        while not final and end < len(answer) and not answer[end].isspace() and not answer[end].isalnum():
            end += 1
        cue = first_cue(answer if final else answer[:end], question, settings, final=final, last=final)
        if cue:
            return cue, k
    return None, None


# --- the live evidence ------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize('question,answer,cue', [
    ('Когда началась Крымская война', 'Крымская война началась в октябре 1853 года и продлилась до 1856-го.',
     'Крымская война началась в октябре 1853 года'),
    ('Когда было крещение Руси', 'Крещение Руси обычно датируют 988-ым годом при князе Владимире.',
     'Крещение Руси обычно датируют 988-ым годом'),
    ('Когда была Полтавская битва?', 'Полтавская битва состоялась в 1709 году. По старому стилю — 27 июня, по новому — 8 июля.',
     'Полтавская битва состоялась в 1709 году.'),
])
def test_the_first_cue_of_a_date_question_of_the_live_run_carries_the_year(question, answer, cue):
    assert streamed_first_cue(question, answer)[0] == cue


# --- the class: other interrogatives, other wordings ----------------------------------------------------------------------------------

@pytest.mark.parametrize('question,answer,number', [
    ('В каком году отменили крепостное право?', 'Крепостное право в России отменили в 1861 году манифестом Александра Второго.', '1861'),
    ('Сколько стоит оформление загранпаспорта?', 'Госпошлина за загранпаспорт нового образца составляет 6000 рублей.', '6000'),
    ('Какой процент НДФЛ в России?', 'Базовая ставка налога на доходы физических лиц составляет 13 процентов.', '13'),
    ('Какая ставка НДС в России?', 'Основная ставка налога на добавленную стоимость в России сейчас составляет 20 процентов.', '20'),
    ('Какого числа празднуют День России?', 'День России празднуют ежегодно 12 июня.', '12'),
    ('Ага, так. Что же я хотел спросить? Когда началась Крымская война?',
     'Крымская война между Россией и коалицией держав началась в 1853 году.', '1853'),
    ('Сколько планет в Солнечной системе', 'В Солнечной системе насчитывается ровно восемь больших планет.', 'восемь'),
])
def test_a_number_question_gets_its_number_in_the_first_cue(question, answer, number):
    cue, _ = streamed_first_cue(question, answer)
    assert cue is not None and number in cue, cue
    assert answer.startswith(cue)
    assert len(words(cue)) <= MEANING_NUMBER_FIRST_MAX_WORDS


def test_the_first_cue_is_the_first_portion_of_the_plan_when_it_carries_the_number():
    # the planner already kept «в октябре 1853 года» together; the first cue now agrees with it
    answer = 'Крымская война началась в октябре 1853 года и продлилась до 1856-го.'
    assert portions(answer, CALL_SETTINGS)[0] == streamed_first_cue('Когда началась Крымская война', answer)[0]


def test_a_number_the_question_already_has_is_not_the_number_asked_for():
    # «Первая мировая» holds the ordinal of the question: the cue goes on to the year
    cue, _ = streamed_first_cue('Когда началась Первая мировая война',
                                'Первая мировая война началась летом 1914 года после убийства эрцгерцога.')
    assert '1914' in cue


# --- what does not change ---------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize('question,answer,cue', [
    # no number in the window: cued as before (these are the cues of the code before C7)
    ('Когда началась Крымская война', 'Точно не знаю, лучше уточнить это в учебнике истории.', 'Точно не знаю,'),
    ('Когда появились первые университеты',
     'Первые университеты появились в средневековой Европе, когда монастырские школы стали слишком тесными для учёных.',
     'Первые университеты появились в средневековой Европе,'),
])
def test_a_number_question_whose_answer_brings_no_number_is_cued_as_before(question, answer, cue):
    got, _ = streamed_first_cue(question, answer)
    assert got == cue
    assert len(words(got)) <= MEANING_FIRST_MAX_WORDS


@pytest.mark.parametrize('question,answer,cue,arrived', [
    # other kinds of question: the same cue at the same word as before C7
    ('Почему началась Крымская война', 'Крымская война началась из-за спора о контроле над проливами в 1853 году.',
     'Крымская война началась из-за спора о контроле', 10),
    ('Что делать, когда болит голова?', 'Обычно помогает отдых в тихой тёмной комнате и стакан воды.', 'Обычно помогает отдых', 10),
    ('Что произошло в 1853 году?', 'В октябре 1853 года началась Крымская война между Россией и Османской империей.',
     'В октябре 1853 года', 10),
])
def test_other_questions_are_not_delayed(question, answer, cue, arrived):
    assert streamed_first_cue(question, answer) == (cue, arrived)


def test_the_number_window_respects_a_profile_that_asks_for_shorter_portions():
    cue, _ = streamed_first_cue('Когда было крещение Руси',
                                'Крещение Руси традиционно относят к 988 году, когда князь Владимир крестился.',
                                {**CALL_SETTINGS, 'max_words': 5})
    assert cue is not None and len(words(cue)) <= 5


# --- reading the question -----------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize('question', [
    'Когда началась Крымская война?', 'В каком году было крещение Руси?', 'Когда была Полтавская битва?',
    'Сколько стоит загранпаспорт?', 'Какого числа День России?', 'Какой процент НДФЛ?', 'Какая ставка НДС?',
    'Какая сумма вычета на ребёнка?', 'Подскажи, когда отменили крепостное право', 'До скольки работает МФЦ?',
    'Ага, так. Что же я хотел спросить? Когда началась Крымская война?', 'Как долго длилась Столетняя война?',
    'С какого возраста можно получить паспорт?', 'В каком веке жил Ломоносов?', 'Какова ставка рефинансирования?',
])
def test_a_question_for_a_number_or_a_date_is_recognised(question):
    assert asks_for_number(question)


@pytest.mark.parametrize('question', [
    'Почему началась Крымская война?', 'Что такое инфляция?', 'Что делать, когда болит голова?', 'Какой налог платит ИП?',
    'Насколько это важно?', 'Как называется столица Австралии?', 'Что произошло в 1853 году?', 'Кто такой Пётр Первый?',
    'Расскажи про Крымскую войну', '',
])
def test_other_questions_are_not_number_questions(question):
    assert not asks_for_number(question)
