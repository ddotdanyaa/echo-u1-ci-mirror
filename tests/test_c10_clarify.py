"""Candidate 10 / c10-clarify: the cloud sometimes answers with a question to the LISTENER instead of an answer - «Можешь чуть точнее?» (live
run 20261103-220527, w3_02 step 1, an early cue), «Какой именно?» (W4 run 20261103-171237, w4_04 step 4), «Если нужен другой кодекс или
юрисдикция, уточни, пожалуйста, страну или документ.» (owner call 20:10). The listener repeats every portion aloud to the examiner, so such a
sentence is never a portion: it goes with the cloud's other talk about itself (``strip_process_prefix`` / ``drop_process_sentences``), and a reply
made only of such sentences is not an answer (nothing is cued; the watchdog decides as before)."""
import pytest

import helpers_s6_ack as H
from echo_sync.textutil import drop_process_sentences, strip_process_prefix
from test_f2_questions import ids

BAPTISM = 'Когда было крещение Руси'
CODE = 'Что такое девятая статья налогового кодекса'

# -- sentences that ask the listener something: dropped, alone or among others ---------------------------------------------------------
ASKS = (
    'Можешь чуть точнее?',                                    # w3_02 step 1
    'Какой именно?',                                          # w4_04 step 4
    'Если нужен другой кодекс или юрисдикция, уточни, пожалуйста, страну или документ.',    # owner call 20:10
    'Что именно?',
    'А что именно?',
    'А о чём речь?',
    'Какой именно вопрос?',
    'О чём именно?',
    'Про какой именно?',
    'В каком смысле?',
    'Какое именно?',
    'Можете уточнить?',
    'Не мог бы ты уточнить вопрос?',
    'Не могли бы вы уточнить?',
    'Сможешь сказать точнее?',
    'Ты имеешь в виду налоговый кодекс?',
    'Что вы имеете в виду?',
    'Уточни, пожалуйста.',
    'Уточните вопрос.',
    'Скажи, какой кодекс тебе нужен?',
    'Дай контекст.',
    'Дайте чуть больше контекста.',
    'Тебе нужен какой-то конкретный кодекс?',
    'Ты про какой кодекс?',
    'Поясни, что ты хочешь узнать.',
)


@pytest.mark.parametrize('reply', ASKS, ids=ids(ASKS))
def test_a_question_back_to_the_listener_is_no_answer(reply):
    assert strip_process_prefix(reply, BAPTISM) == ''


@pytest.mark.parametrize('reply', ASKS, ids=ids(ASKS))
def test_the_question_back_goes_before_the_answer(reply):
    assert strip_process_prefix(reply + ' Крещение Руси было в 988 году.', BAPTISM) == 'Крещение Руси было в 988 году.'


@pytest.mark.parametrize('reply', ASKS, ids=ids(ASKS))
def test_the_question_back_goes_after_the_first_sentence(reply):
    text = 'Крещение Руси было в 988 году. ' + reply
    assert drop_process_sentences(text, BAPTISM, final=True) == 'Крещение Руси было в 988 году.'


LEADS = ('Можешь чуть', 'Можете', 'Какой', 'Какой именно', 'Что именно', 'Уточни', 'Ты имеешь в', 'Ты про какой')


@pytest.mark.parametrize('lead', LEADS, ids=ids(LEADS))
def test_the_lead_of_a_question_back_is_withheld_while_it_arrives(lead):
    assert strip_process_prefix(lead, BAPTISM) == ''


def test_the_whole_cloud_reply_of_questions_is_no_answer():
    assert strip_process_prefix('Какой именно? Можешь чуть точнее?', BAPTISM) == ''
    assert strip_process_prefix('Понял. Какой именно? Уточни, пожалуйста.', BAPTISM) == ''


# -- real answers: kept -----------------------------------------------------------------------------------------------------------------
ANSWERS = (
    ('Почему небо голубое? Потому что воздух рассеивает синий свет сильнее.', 'Почему небо голубое'),
    ('Что такое масса? Масса — это мера инертности тела.', 'Что такое масса'),
    ('Какой кодекс действует? Действует Налоговый кодекс РФ.', 'Какой кодекс действует'),
    ('Крещение Руси было в 988 году.', BAPTISM),
    ('Я могу уточнить, если нужно: речь о 988 годе.', BAPTISM),
    ('Если нужно, уточню по источнику.', BAPTISM),
    ('Он может уточнить вопрос, но год известен: 988.', BAPTISM),
    ('Вы можете подать заявление в течение месяца.', 'Как подать заявление'),
    ('Укажите в заявлении ИНН и адрес.', 'Как заполнить заявление'),
    ('Рад вас видеть.', 'Здравствуйте'),
    ('Нормально. А у вас как дела?', 'Как дела'),
    ('Именно так: крещение произошло в 988 году.', BAPTISM),
    ('Какой именно кодекс имеется в виду, зависит от страны: в России это Налоговый кодекс.', CODE),
    ('Да, я говорю по-английски свободно.', 'Вы говорите по-английски?'),
)


@pytest.mark.parametrize('reply,question', ANSWERS, ids=ids(ANSWERS))
def test_a_real_answer_stays(reply, question):
    assert strip_process_prefix(reply, question) == reply
    assert drop_process_sentences(reply, question, final=True) == reply


def test_a_question_form_inside_the_content_stays_in_the_middle():
    text = 'Вода кипит при ста градусах. Почему так? Потому что давление пара сравнивается с атмосферным.'
    assert drop_process_sentences(text, 'При какой температуре кипит вода', final=True) == text


def test_the_rest_of_a_growing_answer_is_monotone():
    """What is published from a shorter text is the start of what a longer text gives (the drop never takes back a published word)."""
    text = 'Крещение Руси было в 988 году. Можешь чуть точнее? Это произошло при князе Владимире.'
    expected = 'Крещение Руси было в 988 году. Это произошло при князе Владимире.'
    shown = ''
    for end in range(1, len(text) + 1):
        now = drop_process_sentences(text[:end], BAPTISM)
        assert now.startswith(shown), (text[:end], shown, now)
        shown = now
    assert drop_process_sentences(text, BAPTISM, final=True) == expected


# -- through the controller: the cloud's reply is a question back, nothing is cued ---------------------------------------------------------
def _asked(tmp_path, reply):
    d = H.Dictation(tmp_path, None)
    c = d.controller
    c.speech_started()
    c.provider(H.created('q1', 'user', ''))
    c.provider(H.done('q1', 'user', BAPTISM + '?'))
    types = [a['type'] for a in c.provider(H.done('a1', 'assistant', reply))]
    return d, types


def test_dispatch_a_question_back_is_never_cued(tmp_path):
    d, types = _asked(tmp_path / 'ask', 'Можешь чуть точнее?')
    for _ in range(6):
        d.clock.advance(1.0)
        types += [a['type'] for a in d.controller.tick(now=d.clock())]
    assert 'speak' not in types, types


def test_dispatch_the_answer_after_a_question_back_is_cued_without_it(tmp_path):
    d, types = _asked(tmp_path / 'both', 'Какой именно? Крещение Руси было в 988 году, при князе Владимире.')
    assert 'speak' in types, types
    first = d.state['chunks'][0].casefold()
    assert 'именно' not in first and '988' in first, d.state['chunks']
