"""``answer_witness``: the job's number against GPT-Live's, and a third source that decides. In shadow: a line of the call trace, nothing is said.

7:37 of 6 Nov: a job that had heard all of the question said «3 месяца, а для руководителей организаций — 6 месяцев» to the chief accountant; GPT-Live's first sentence with a number said «до шести месяцев». Nothing compared them. A number the model adds
is guarded by nothing else: every other guard reads the question. The logic only: nothing here is a measurement of a call.
"""
import pytest

import helpers_s6_state as S
from echo_sync import answer_witness as W
from echo_sync.settings import resolve
from test_h1_fast_text import settled       # noqa: F401
from test_h3_tempo import TICK, call       # noqa: F401 - call is the fixture

QUESTION = 'Испытательный срок для главного бухгалтера, какой максимум'
SAID = '3 месяца, а для руководителей организаций — 6 месяцев.'
REPLY = 'Сейчас гляну. По российскому ТК для главного бухгалтера испытательный срок может быть до шести месяцев. Для остальных обычно максимум три месяца'
LAW = ('Срок испытания не может превышать трех месяцев, а для руководителей организаций и их заместителей, главных бухгалтеров и их заместителей, руководителей филиалов, представительств или иных обособленных структурных подразделений организаций - '
       'шести месяцев, если иное не установлено федеральным законом.')


def test_the_flag_is_off_by_default_and_is_a_shadow():
    assert resolve({})['answer_witness'] == 'off'
    assert resolve({'fast_text': 'on', 'answer_witness': 'shadow'})['answer_witness'] == 'shadow'
    assert resolve({'fast_text': 'on', 'answer_witness': 'on'})['answer_witness'] == 'off', 'there is no «on» yet: it says nothing'
    assert resolve({'answer_witness': 'shadow'})['answer_witness'] == 'off', 'no job, nothing to compare'


# ---- which sentence of the reply speaks ---------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize('reply,closed,sentence', [
    (REPLY, False, 'По российскому ТК для главного бухгалтера испытательный срок может быть до шести месяцев.'),   # the filler before it holds no number
    ('Сейчас гляну. По российскому ТК', False, ''),                                                               # no sentence with a number yet
    ('Основная ставка — 25 процентов', False, ''),                                                                # not closed: it may go on
    ('Основная ставка — 25 процентов', True, 'Основная ставка — 25 процентов'),                                   # the turn is over
    ('Понял, сейчас посмотрю.', True, ''),
])
def test_the_first_sentence_with_a_number(reply, closed, sentence):
    assert W.first_sentence(reply, QUESTION, closed=closed) == sentence


# ---- do they disagree -----------------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize('said,sentence,asked,agree', [
    (SAID, 'для главного бухгалтера испытательный срок может быть до шести месяцев.', QUESTION, False),    # the job's leading number is not the reply's: they share the 6
    ('22 процента — основная ставка НДС', 'В России основная ставка НДС — 22 процента.', 'Какая ставка НДС', True),
    ('6 месяцев.', 'До шести месяцев, это исключение для главного бухгалтера.', QUESTION, True),              # a number by its value
    ('Двадцать процентов от неуплаченной суммы.', 'Обычно 20% от неуплаченной суммы, а при умысле — 40%.', 'Какой штраф', True),
    ('Указание Банка России 3210-У', 'Это Указание Банка России № 3210-У от 11 марта 2014 года.', 'Что за указание', True),
    ('Счёт 58 — финансовые вложения.', 'Счёт 58 — это финансовые вложения.', 'Счёт 58', None),                 # the number of the question: nobody added one
    ('Финансовые вложения, активный.', 'Обычно за 2 недели.', 'За сколько', None),                            # the job said none: nothing to compare
    ('За 2 недели.', 'Предупредить письменно.', 'За сколько', None),                                          # the reply said none
])
def test_the_job_leads_with_a_number_the_reply_does_not_hold(said, sentence, asked, agree):
    assert W.agree(said, sentence, asked) is agree


# ---- a third decides --------------------------------------------------------------------------------------------------------------------------------

def test_the_clause_of_the_question_decides_not_the_article():
    """Art. 70 holds both numbers: the article decides nothing, the clause does, and a special clause goes before the general one."""
    assert W.decide(QUESTION, [(LAW, 'law_base')], '3', '6') == ('live', 'law_base')


def test_the_general_clause_answers_the_general_question():
    assert W.decide('Срок испытания при приёме на работу какой', [(LAW, 'law_base')], '6', '3') == ('live', 'law_base')


@pytest.mark.parametrize('passages', [
    [],                                                                                       # no third
    [('Статья об испытании, без чисел об этом.', 'law_base')],
    [('Срок для главного бухгалтера от трех до шести месяцев.', 'law_base')],                 # both in one clause: it does not decide
    [('Налог на прибыль составляет 6 процентов.', 'bank')],                                   # a number on other words: no witness of this question
], ids=['none', 'no_number', 'both', 'another_matter'])
def test_a_third_that_cannot_tell_decides_nothing(passages):
    assert W.decide(QUESTION, passages, '3', '6') == (None, None)


def test_a_question_with_its_preface_is_read_by_its_clause():
    """The words of the cloud's turn of 7:37, preface and all: the third source is asked with them."""
    asked = 'Добрый день, садитесь. Чай, кофе будете? Резюме ваше я видела, опыт хороший. Давайте сразу по делу. Испытательный срок для главного бухгалтера, какой максимум'
    assert W.decide(asked, [(LAW, 'law_base')], '3', '6') == ('live', 'law_base')


def test_a_third_may_side_with_the_job():
    assert W.decide(QUESTION, [('Испытательный срок для главного бухгалтера не более трех месяцев.', 'material')], '3', '6') == ('job', 'material')


def test_the_first_third_that_can_tell_decides():
    passages = [('Статья об испытании, без чисел об этом.', 'law_base'), (LAW, 'law_base')]
    assert W.decide(QUESTION, passages, '3', '6') == ('live', 'law_base')


# ---- what it proposes -----------------------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize('sentence,value,said', [
    ('По российскому ТК для главного бухгалтера испытательный срок может быть до шести месяцев.', '6', 'Поправка: до шести месяцев.'),
    ('В России основная ставка НДС — 22 процента.', '22', 'Поправка: 22 процента.'),
    ('Обычно 20% от неуплаченной суммы.', '20', 'Поправка: 20% от неуплаченной суммы.'),
    ('Об этом нет числа.', '6', ''),
])
def test_the_correction_is_in_the_words_of_the_source(sentence, value, said):
    assert W.correction(sentence, value) == said


def test_a_whole_case():
    case = W.judge(QUESTION, SAID, W.first_sentence(REPLY, QUESTION, closed=False), [(LAW, 'law_base')])
    assert (case['verdict'], case['side'], case['source'], case['job'], case['reply']) == ('differ', 'live', 'law_base', '3', '6')
    assert case['proposal'] == 'Поправка: до шести месяцев.'


def test_no_proposal_when_the_third_sides_with_the_job_or_is_silent():
    sentence = W.first_sentence(REPLY, QUESTION, closed=False)
    assert W.judge(QUESTION, SAID, sentence, [('Испытательный срок для главного бухгалтера не более трех месяцев.', 'material')])['proposal'] == ''
    assert W.judge(QUESTION, SAID, sentence, [])['proposal'] == ''
    assert W.judge(QUESTION, SAID, sentence, [])['verdict'] == 'differ'


# ---- in a call: a line, and not a word more -----------------------------------------------------------------------------------------------------------

FLAGS = {'fast_text': 'on', 'answer_witness': 'shadow', 'tempo': None}


def answered(rig):
    """The question, the job's answer is being said, the cloud's own reply comes after its final."""
    rig.w.feed(S.turn_created('u1', 'user', 'Испытательный'))
    rig.w.feed(S.turn_done('u1', 'user', QUESTION))
    rig.pump(TICK * 2)
    rig.job_says(0, SAID)
    rig.pump(TICK * 2)
    return list(rig.said())


def lines(rig):
    return rig.c.witness_cases


def test_in_a_call_it_writes_a_line_and_says_nothing(call):
    rig = call(**FLAGS)
    said = answered(rig)
    assert said, 'precondition: the job is said'
    rig.w.feed(S.turn_created('a1', 'assistant', 'Сейчас гляну. '))
    rig.w.feed(S.turn_delta('a1', REPLY[len('Сейчас гляну. '):], 1))
    rig.pump(TICK * 2)
    assert [(case['job'], case['reply']) for case in lines(rig)] == [('3', '6')]
    assert rig.said() == said, 'a shadow: not a word more, not a word less'


def test_it_looks_once_at_a_reply(call):
    rig = call(**FLAGS)
    answered(rig)
    rig.w.feed(S.turn_created('a1', 'assistant', 'По ТК до шести месяцев. '))
    rig.w.feed(S.turn_delta('a1', 'Да, до шести месяцев. ', 1))
    rig.w.feed(S.turn_delta('a1', 'И снова шесть месяцев. ', 2))
    rig.pump(TICK * 2)
    assert len(lines(rig)) == 1


def test_a_reply_begun_before_the_final_of_the_question_is_no_witness(call):
    """A reply that began before the final is the tail of the one before. Only that: when the cloud cuts the question, a tail may begin after the cut («… с 18 лет» against «за 2 недели» at 7:37 of 6 Nov), and that stays a false «differ», which no third decides."""
    rig = call(**FLAGS)
    rig.w.feed(S.turn_created('u1', 'user', 'Испытательный'))
    rig.w.feed(S.turn_created('a0', 'assistant', 'О полной дееспособности '))
    rig.pump(0.3)
    rig.w.feed(S.turn_done('u1', 'user', QUESTION))
    rig.pump(TICK * 2)
    rig.job_says(0, SAID)
    rig.w.feed(S.turn_delta('a0', 'с 18 лет и когда она наступает раньше. ', 1))
    rig.pump(TICK * 2)
    assert lines(rig) == []


def test_with_the_flag_off_nothing_is_looked_at(call):
    rig = call(fast_text='on', tempo=None)
    answered(rig)
    rig.w.feed(S.turn_created('a1', 'assistant', REPLY))
    rig.pump(TICK * 2)
    assert rig.c.answer_witness is False and lines(rig) == []
