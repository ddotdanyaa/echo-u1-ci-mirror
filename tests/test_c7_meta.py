"""Candidate 7 / c7-meta: the root causes of the live measurement of candidate 6 (runs/20261103-164741, FIRST_DIVERGENCE w3_05, w3_07,
w3_08, w3_14).

1. Remarks to the prompter were answered. (a) The remark rule is robust to the recogniser: a 2nd-person verb split in two («замира ешь») is
   rejoined; a joined earlier fragment does not make the remark name something - the clause that carries the «?» / the question word is what
   is judged; «всё время», «по слову» name nothing. (b) A reply that is the assistant talking about itself and its prompting is no answer.
2. «Да, понял вопрос , сейчас проверю формулировку.» is stripped as a whole, also while it arrives in pieces; a process sentence in the middle of
   an answer is dropped from it.
3. «Непонятно» alone while a portion waits is the hearing repair, like «не понял»: it replays the portion - in the cloud path and in the ear.
"""
import pytest

import helpers_s6_ack as H
from echo_sync.classifier import QUESTION, QUIET, REPEAT, analyze
from echo_sync.controlled_media import ControlledMedia
from echo_sync.textutil import drop_process_sentences, strip_process_prefix
from test_f2_questions import DONE, WAITING, ids

PROD = H.PROD_SETTINGS
STATES = {'idle': None, 'done': DONE, 'waiting': WAITING}


def decide(text, state=None):
    return analyze(text, state, [], PROD)


# =====================================================================================================================================
# 1a. Remarks to the prompter stay remarks: recogniser splits, a joined earlier fragment, «всё время»
# =====================================================================================================================================

REMARKS = (
    # w3_05: the controller joined the tail of the previous remark (a QUIET final) with «подсказываешь? А»
    'сформулировать и держать его, и просто смотреть по звукам, что обратно приходит, ты почему так медленно подсказываешь? А',
    # w3_14 step 1, as the cloud wrote it and as it was said
    'Слушай, а почему ты всё время говоришь по слову? Ты что, глючишь',
    'Слушай, а почему ты всё время говоришь по слову, ты что, глючишь?',
    # w3_14 step 2: the recogniser split «замираешь»; and as said
    'Ну и что ты замира ешь? Я же жду',
    'Ну и что ты замираешь, я же жду.',
    # the same classes in other words
    'Ты чего тормо зишь?',
    'Почему ты каждый раз отвечаешь по одному слову?',
    'А ты что, опять глючишь?',
    'Почему ты всё время замираешь?',
    'Ну что ты молчишь, я же жду ответа?',
)


@pytest.mark.parametrize('state', sorted(STATES))
@pytest.mark.parametrize('text', REMARKS, ids=ids(REMARKS))
def test_a_remark_to_the_prompter_stays_quiet(text, state):
    decision = decide(text, STATES[state])
    assert (decision.kind, decision.reason) == (QUIET, 'remark_to_prompter'), decision


QUESTIONS = (
    'Почему ты говоришь, что время относительно?',
    'Почему ты всё время говоришь про инфляцию?',
    'Когда ты замираешь от страха, что происходит с сердцем?',
    'Слушай, а почему небо голубое?',
    'Ты почему так медленно подсказываешь, а сколько стоит баррель нефти?',
    'сформулировать и держать его, и просто смотреть по звукам, а когда было крещение Руси?',
)


@pytest.mark.parametrize('text', QUESTIONS, ids=ids(QUESTIONS))
def test_a_content_question_with_the_same_words_is_still_a_question(text):
    assert decide(text).kind == QUESTION, decide(text)


@pytest.mark.parametrize('text', ['Допустим, Транссибирская магистраль.', 'Предположим, закон Ома'])
def test_a_topic_after_a_supposing_lead_is_asked_when_nothing_waits(text):
    decision = decide(text)
    assert (decision.kind, decision.reason) == (QUESTION, 'topic_phrase'), decision


# =====================================================================================================================================
# 1b. A reply about the assistant itself and its prompting is no answer
# =====================================================================================================================================

SELF_TALK = (
    ('Если я начну подсказывать слишком рано,', 'ты почему так медленно подсказываешь? А'),
    ('Если я начну подсказывать слишком рано, ты будешь повторять за мной ошибки.', 'ты почему так медленно подсказываешь?'),
    ('Ой, понимаю, со стороны может звучать рвано.', 'почему ты всё время говоришь по слову? Ты что, глючишь'),
    ('Мне лучше делать паузу и не болтать лишнего,', 'что ты замира ешь? Я же жду'),
    ('Мне лучше делать паузу и не болтать лишнего, пока думаю. Скажи, как тебе комфортнее — ждать молча или коротко предупреждать?',
     'что ты замира ешь? Я же жду'),
    ('Я подсказываю по слову, чтобы тебе было легче повторять.', ''),
)


@pytest.mark.parametrize('reply,question', SELF_TALK, ids=ids(SELF_TALK))
def test_a_reply_about_its_own_prompting_is_no_answer(reply, question):
    assert strip_process_prefix(reply, question) == ''


CONTENT_IN_FIRST_PERSON = (
    ('Я выбрал эту профессию, потому что люблю работать с цифрами.', 'Почему вы выбрали эту профессию?'),
    ('Я работаю бухгалтером пять лет.', 'Кем вы работаете?'),
    ('Понимаю.', 'Вы понимаете, что это важно?'),
    ('Я быстро учусь и легко нахожу общий язык с людьми.', 'Какие у вас сильные стороны?'),
    ('Да, я говорю по-английски свободно.', 'Вы говорите по-английски?'),
    ('Я отвечал за закупки и переговоры с поставщиками.', 'За что вы отвечали на прошлой работе?'),
    ('Думаю, да.', 'Это правда?'),
    ('Да, хорошо.', 'Можно я позвоню завтра?'),
)


@pytest.mark.parametrize('reply,question', CONTENT_IN_FIRST_PERSON, ids=ids(CONTENT_IN_FIRST_PERSON))
def test_a_first_person_content_answer_stays(reply, question):
    assert strip_process_prefix(reply, question) == reply


# =====================================================================================================================================
# 2. «Да, понял вопрос» + a process sentence, whole or in pieces; a process sentence in the middle
# =====================================================================================================================================

ARTICLE = 'что такое девятая статья налогового кодекса'
W307 = ('Да, понял вопрос , сейчас проверю формулировку. Девятаяя статья Налогового кодекса РФ перечисляет участников отношений, '
        'регулируемых законодательством о налогах и сборах.')


def test_the_acknowledged_question_and_the_process_sentence_go_as_a_whole():
    assert strip_process_prefix(W307, ARTICLE).startswith('Девятаяя статья Налогового кодекса РФ')


@pytest.mark.parametrize('piece', ['Да, понял вопрос ,', 'Да, понял вопрос', 'Да, понял вопрос , сейчас', 'Да, понял вопрос , сейчас проверю',
                                   'Да, понял вопрос.', 'Да, понял вопрос , сейчас проверю формулировку.'])
def test_the_acknowledged_question_is_never_cued_while_it_arrives(piece):
    assert strip_process_prefix(piece, ARTICLE) == ''


@pytest.mark.parametrize('reply,question', [('Да, хорошо.', 'Можно я позвоню завтра?'),
                                            ('Да, понятно, что налог платит работодатель.', 'Кто платит этот налог?'),
                                            ('Да, ясно одно: вопрос решает суд.', 'Кто решает такой вопрос?')])
def test_yes_before_an_acknowledgement_without_a_process_predicate_stays(reply, question):
    assert strip_process_prefix(reply, question) == reply


ANSWER_WITH_A_STALL = (
    ('Девятая статья перечисляет участников налоговых отношений. Сейчас проверю формулировку. Например, налогоплательщиков.',
     'Девятая статья перечисляет участников налоговых отношений. Например, налогоплательщиков.'),
    ('Девятая статья перечисляет участников налоговых отношений. Секунду, уточню детали статьи. Это налогоплательщики и налоговые агенты.',
     'Девятая статья перечисляет участников налоговых отношений. Это налогоплательщики и налоговые агенты.'),
    ('Девятая статья перечисляет участников налоговых отношений. Сейчас пров',
     'Девятая статья перечисляет участников налоговых отношений.'),
    ('Девятая статья перечисляет участников налоговых отношений. Да, понял вопрос',
     'Девятая статья перечисляет участников налоговых отношений.'),
)


@pytest.mark.parametrize('text,expected', ANSWER_WITH_A_STALL, ids=ids(ANSWER_WITH_A_STALL))
def test_a_process_sentence_in_the_middle_is_dropped(text, expected):
    assert drop_process_sentences(text, ARTICLE) == expected


KEPT_IN_THE_MIDDLE = (
    'Девятая статья перечисляет участников. Я считаю, что это важно знать.',
    'Сначала проверьте договор. Потом договор проверяет юрист.',
    'Крещение Руси относят к 988 году. Скажу честно: точная дата спорна.',
    'Девятая статья перечисляет участников. Например, налогоплательщиков',
)


@pytest.mark.parametrize('text', KEPT_IN_THE_MIDDLE, ids=ids(KEPT_IN_THE_MIDDLE))
def test_a_content_sentence_in_the_middle_stays(text):
    assert drop_process_sentences(text, ARTICLE) == text


def test_dropping_is_monotone_over_a_growing_answer():
    """What is published from a shorter text is a prefix of what a longer one gives (DEF-T-B01: no rewrite)."""
    text = ('Девятая статья перечисляет участников налоговых отношений. Сейчас проверю формулировку. Например, налогоплательщиков и '
            'налоговых агентов.')
    before = ''
    for end in range(1, len(text) + 1):
        now = drop_process_sentences(text[:end], ARTICLE)
        assert now.startswith(before.rstrip()), (text[:end], before, now)
        before = now


# =====================================================================================================================================
# 3. «Непонятно» alone while a portion waits: the hearing repair, one rule for the cloud and the ear
# =====================================================================================================================================

@pytest.mark.parametrize('text', ['Непонятно', 'Непонятно.', 'Не понятно', 'Ничего не понятно.', 'Не понял', 'Не поняла.'])
def test_not_understood_alone_replays_the_waiting_portion(text):
    decision = decide(text, WAITING)
    assert (decision.kind, decision.reason) == ('replay', 'replay_hearing_repair'), decision
    assert ControlledMedia._ear_family(decision) == REPEAT        # the ear acts on the same verdict


@pytest.mark.parametrize('text', ['Непонятно', 'Не понял'])
def test_not_understood_with_nothing_waiting_asks_nothing(text):
    assert decide(text).kind == QUIET


def test_a_word_not_understood_is_still_its_own_request():
    assert decide('Непонятно слово формулировка', WAITING).reason != 'replay_hearing_repair'


# =====================================================================================================================================
# Round 2 (W4, oral exam on candidate 6: runs/20261103-171237)
# =====================================================================================================================================

ANSWER_WAITS = {'schema': 2, 'revision': 3, 'question': 'Приведите пример',
                'answer': '«касса», «банк», «поставщики». Вот простой пример. Купили товар за наличные на 1000 рублей.',
                'chunks': ['«касса», «банк», «поставщики».', 'Вот простой пример.', 'Купили товар за наличные на 1000 рублей.'],
                'chunk_index': 0, 'completed': False, 'pending_turn': None, 'history': []}

TICKETS = ('Лизинг. Определение, виды лизинга.', 'Лизинг: определение, виды лизинга.', 'Факторинг, определение, виды факторинга',
           'Лизинг определение виды лизинга', 'Амортизация основных средств: понятие, методы начисления.',
           'Налоговая система. Структура, функции и принципы.')


@pytest.mark.parametrize('text', TICKETS, ids=ids(TICKETS))
def test_an_exam_ticket_line_is_one_topic_question(text):
    decision = decide(text)
    assert decision.kind == QUESTION, decision
    again = decide(decision.question)                    # the engine classifies the asked text again when the answer is published
    assert again.kind == QUESTION, (decision.question, again)


def test_the_rebuilt_question_keeps_the_mark_of_its_first_sentence():
    assert decide('Лизинг. Определение, виды лизинга.').question == 'Лизинг. Определение, виды лизинга.'


NOT_TICKETS = ('Хорошо, спасибо.', 'Иван, определение.', 'Привет, виды.', 'Лизинг, ну и погода сегодня.', 'Хорошая работа, определение верное.')


@pytest.mark.parametrize('text', NOT_TICKETS, ids=ids(NOT_TICKETS))
def test_a_line_that_is_no_ticket_stays_what_it_was(text):
    assert decide(text).reason != 'topic_phrase'


NEXT_TICKETS = ('Оценка основных средств и учёт их наличия.', 'Факторинг: определение, виды факторинга.',
                'Дебиторская задолженность и её погашение.', 'Структура капитала предприятия.')


@pytest.mark.parametrize('text', NEXT_TICKETS, ids=ids(NEXT_TICKETS))
def test_the_next_ticket_while_a_portion_waits_is_a_new_question(text):
    decision = decide(text, ANSWER_WAITS)
    assert (decision.kind, decision.reason) == (QUESTION, 'topic_while_waiting'), decision


BYSTANDERS = ('Касса.', 'Иван Петрович.', 'Хорошая работа.', 'Простой пример.', 'Наличные деньги.', 'Товар за наличные.',
              'Банк и поставщики.', 'Музыка.', 'Секунду.', 'Да, конечно.', 'Красивая погода.', 'Минуточку, коллеги.',
              'Петров, к доске.')


@pytest.mark.parametrize('text', BYSTANDERS, ids=ids(BYSTANDERS))
def test_bystander_speech_while_a_portion_waits_stays_silent(text):
    decision = decide(text, ANSWER_WAITS)
    assert decision.kind != QUESTION, decision


MOVE_ON = ('Хорошо. Давайте следующий билет.', 'Следующий вопрос.', 'Дальше по билету.', 'Давайте следующий билет',
           'Переходим к следующему вопросу.', 'Так, следующая тема.')


@pytest.mark.parametrize('state', ['idle', 'waiting'])
@pytest.mark.parametrize('text', MOVE_ON, ids=ids(MOVE_ON))
def test_a_move_on_line_without_content_ends_the_answer_quietly(text, state):
    decision = decide(text, {'idle': None, 'waiting': ANSWER_WAITS}[state])
    assert (decision.kind, decision.reason) == (QUIET, 'move_on_without_content'), decision


@pytest.mark.parametrize('text', ['Следующий вопрос: лизинг', 'Следующий билет: факторинг, определение, виды.'])
def test_a_move_on_line_with_content_is_the_explicit_marker(text):
    assert decide(text).kind == QUESTION


@pytest.mark.parametrize('text', ['Дальше', 'Давай дальше', 'Следующую часть'])
def test_going_on_with_the_answer_is_no_move_on(text):
    assert decide(text, ANSWER_WAITS).reason != 'move_on_without_content'


PROMISES = (
    ('Сделаю пример понятным и коротким.', 'Приведите, пожалуйста, пример'),
    ('добавлю наглядный пример.', 'Приведите, пожалуйста, пример'),
    ('Секунду, подниму статью.', 'О чём говорится в сорок пятой статье Налогового кодекса?'),
    ('Сейчас подберу понятный пример.', 'Приведите пример'),
    ('Хорошо, разложу по шагам.', 'Объясните правило двойной записи'),
)


@pytest.mark.parametrize('reply,question', PROMISES, ids=ids(PROMISES))
def test_a_promise_of_the_answer_is_stripped_at_the_start(reply, question):
    assert strip_process_prefix(reply, question) == ''


def test_a_promise_is_stripped_with_the_answer_after_it():
    text = 'добавлю наглядный пример. Сорок пятая статья Налогового кодекса регулирует исполнение обязанности по уплате налога.'
    assert strip_process_prefix(text, 'Приведите, пожалуйста, пример').startswith('Сорок пятая статья')


def test_a_promise_in_the_middle_is_dropped():
    text = 'Статья 45 регулирует уплату налога. Сделаю пример понятным. Например, налог уплачен через банк.'
    assert drop_process_sentences(text, 'Приведите пример') == 'Статья 45 регулирует уплату налога. Например, налог уплачен через банк.'


def test_a_promise_after_a_colon_leaves_the_content():
    assert strip_process_prefix('Приведу пример: купили товар за 1000 рублей.', 'Объясните правило двойной записи') == 'купили товар за 1000 рублей.'


KEPT_PROMISE_LIKE = (
    ('Сделаю отчёт к понедельнику.', 'Что вы сделаете первым делом?'),
    ('Получу сертификат и перейду в аналитику.', 'Какие у вас планы на ближайший год?'),
    ('Подготовлю отчёт к понедельнику.', 'Вы подготовите отчёт к понедельнику?'),
    ('Заплачу налог до 1 декабря.', 'Когда нужно платить налог?'),
    ('Не успею к пятнице.', 'Успеете к пятнице?'),
    ('Позвоню в налоговую, если уведомление не придёт.', 'Что делать, если уведомление не пришло?'),
)


@pytest.mark.parametrize('reply,question', KEPT_PROMISE_LIKE, ids=ids(KEPT_PROMISE_LIKE))
def test_a_first_person_future_that_answers_stays(reply, question):
    assert strip_process_prefix(reply, question) == reply


# -- round 2 through the controller ---------------------------------------------------------------------------------------------------

def _types(actions):
    return [action['type'] for action in actions]


def test_dispatch_move_on_retires_quietly_and_the_next_ticket_is_asked(tmp_path):
    d = H.Dictation(tmp_path / 'move', H.LONG_ANSWERS[0])
    out = d.say('Хорошо. Давайте следующий билет.', tid='mv')
    assert 'speak' not in out.types and not d.current, (out.types, d.state)
    reply = d.controller.provider(H.done('mv-reply', 'assistant', 'Какой именно? Назови номер или тему, и я продолжу.'))
    assert 'speak' not in _types(reply), reply                 # the cloud's reply to a chat turn is never cued
    ticket = d.say('Факторинг: определение, виды факторинга.', tid='t2')
    assert _types(ticket.actions)[:1] == ['cancel'] and d.controller.question_id == 't2', ticket.types


def test_dispatch_the_next_ticket_while_a_portion_waits_retires_the_old_answer(tmp_path):
    d = H.Dictation(tmp_path / 'next', H.LONG_ANSWERS[0])
    assert d.current
    out = d.say('Оценка основных средств и учёт их наличия.', tid='t2')
    assert d.controller.question_id == 't2' and 'cancel' in out.types, out.types


# Deleted (round-2 merge): «a question the engine rejects at publish is given up quietly» asserted the engine reading the text again at publication (a path the
# lanes deleted, engine.publication now only reports refused/failed material, the verdict of the open question is the job's).
# Replaced by tests/test_h2_brain.py::test_the_answer_to_a_question_the_classifier_saw_is_not_judged_again_at_publication (the new rule through the real ControlledMedia)
# and test_with_no_source_a_new_number_is_refused_and_the_listener_is_told (a refused material is never said and the listener is told once).


# Coordinator, candidate 7: the decision-diff gate showed two-noun bystander phrases ending a waiting answer. A ticket while an answer waits
# needs three content nouns, an aspect noun, or two noun phrases joined by «и» / a comma / a colon.
BYSTANDER_PAIRS = ('Звонок телефона', 'Конец связи', 'Адрес доставки', 'Номер заказа', 'Молекулы воздуха')


@pytest.mark.parametrize('text', BYSTANDER_PAIRS, ids=ids(BYSTANDER_PAIRS))
def test_a_two_noun_bystander_phrase_does_not_end_the_answer_that_waits(text):
    decision = decide(text, ANSWER_WAITS)
    assert decision.kind != QUESTION, decision


def test_an_aspect_noun_makes_a_two_noun_line_a_ticket_while_an_answer_waits():
    decision = decide('Методы ценообразования.', ANSWER_WAITS)
    assert (decision.kind, decision.reason) == (QUESTION, 'topic_while_waiting'), decision


# =====================================================================================================================================
# integ10 fix (candidate 7 merge): the mid-answer drop and the next-ticket rule where they meet the rest of the product
# =====================================================================================================================================

ERA = 'Когда построили пирамиды'
ABBREVIATED = ('Великие пирамиды в Гизе построили около 2560 года до н. э.',
               'Пирамиды построили около 2560 года до н. э. Это одно из древнейших сооружений.',
               'Туда входят яблоки, груши и т. д. Всё это фрукты.',
               'Город основан в 1147 г. Это было давно.')


@pytest.mark.parametrize('text', ABBREVIATED, ids=ids(ABBREVIATED))
def test_the_period_of_an_abbreviation_is_no_sentence_end_of_the_drop(text):
    """s6 abbreviation-06: «до н. э.» - «э.» was judged a sentence of its own, a hesitation, and dropped: the answer lost its last word.
    An abbreviation's period is no sentence end here, as for the planner (textutil.ABBREVIATIONS)."""
    assert drop_process_sentences(text, ERA) == text
    before = ''
    for end in range(1, len(text) + 1):                  # and the drop stays monotone over it
        now = drop_process_sentences(text[:end], ERA)
        assert now.startswith(before.rstrip()), (text[:end], before, now)
        before = now


EEG = 'Как называется запись электрической активности головного мозга?'


@pytest.mark.parametrize('text', [' Электроэнцефалограмма. Граф', 'Потому что воздух сильнее рассеивает синий свет. Поэт',
                                  'Электроэнцефалограмма. Графическая запись'])
def test_the_final_text_keeps_its_last_open_content_sentence(text):
    """test_delegated_media / test_task1_review_round2: a segment cut inside a word («… свет. Поэт»): while more may come the open sentence is
    withheld; once the answer is final it is a sentence like any other, and a content sentence stays."""
    assert drop_process_sentences(text, EEG, final=True) == text


def test_the_final_text_still_drops_a_last_process_sentence():
    assert (drop_process_sentences('Девятая статья перечисляет участников налоговых отношений. Сейчас проверю', ARTICLE, final=True)
            == 'Девятая статья перечисляет участников налоговых отношений.')


# test_teacher_scenarios: mid-answer noise. c7-meta's gate tightening (cc4180d, not in the merge): a statement «Это …» and an open fragment
# (ending in , : ; —) are never the next ticket while an answer waits.
NOT_NEXT_TICKETS = ('Это посторонний рассказ о погоде и школьном расписании.', 'Это история денег и банковской системы.',
                    'Часть атмосферы на высоте,', 'Оценка основных средств и учёт их наличия:')


@pytest.mark.parametrize('text', NOT_NEXT_TICKETS, ids=ids(NOT_NEXT_TICKETS))
def test_a_statement_or_an_open_fragment_is_no_next_ticket(text):
    decision = decide(text, ANSWER_WAITS)
    assert decision.reason != 'topic_while_waiting', decision
