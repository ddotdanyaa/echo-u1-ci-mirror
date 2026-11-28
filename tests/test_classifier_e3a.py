"""Task E3a (WAVE 2): what counts as a question. The coordinator's rulings 1-5 that answer the T-A findings DEF-T-01 .. DEF-T-06.

Every case goes through the real ``analyze`` with the production profile (on_mismatch=silent) and, where the
classic profiles must agree, with those. The dispatch tests drive the real ControlledMedia, built as the host builds it
(``helpers_s6_ack.Dictation``), so they show what the listener would hear: the waiting portion retired, or left alone.

  1. an indirect request starts an answer like «Что такое …?» does («Хочу узнать про …»)        DEF-T-01
  2. a rhetorical or backchannel exclamation retires nothing and starts nothing                  DEF-T-02
  3. «Нет, я про X, а не Y» retires the wrong answer and makes X the question                    DEF-T-04
  4. «Не понял это слово» asks for the term to be explained, it is not a replay                  DEF-T-03
  5. a statement that merely contains a modal word is not a question                             DEF-T-06
"""
import pytest

import helpers_s6_ack as H
from echo_sync.classifier import ACK, CLARIFY_REPAIR, CORRECTION, QUESTION, QUIET, REPEAT, REPLAY, STOP, analyze

PORTION = 'Наклон земной оси'
WAITING = H.waiting(PORTION)
COMPLETED = dict(H.waiting(PORTION), completed=True)
PENDING = dict(H.waiting(PORTION), completed=True, pending_turn='t1')
STATES = {'waiting': WAITING, 'completed': COMPLETED, 'pending': PENDING, 'idle': None}
PROD = H.PROD_SETTINGS
PROFILES = {'prod': PROD}


def decide(text, state=WAITING, settings=PROD):
    return analyze(text, state, [], settings)


def fresh(tmp_path, answer=None):
    return H.Dictation(tmp_path / 'd', answer or H.LONG_ANSWERS[1])


# =====================================================================================================================================
# 1. An indirect request (DEF-T-01)
# =====================================================================================================================================

INDIRECT_REQUESTS = (
    # «Хочу узнать (про|о|об|что|как|почему|зачем) …»
    'Хочу узнать про фотосинтез', 'Хочу узнать о фотосинтезе', 'Хочу узнать об инерции', 'Хочу узнать что такое фотосинтез',
    'Хочу узнать, как работает насос', 'Хочу узнать почему небо голубое', 'Хочу узнать зачем нужен налог',
    # «Хотелось бы (узнать|разобраться|понять|услышать) …»
    'Хотелось бы узнать про налоги', 'Хотелось бы разобраться в налогах', 'Хотелось бы понять принцип работы',
    'Хотелось бы услышать про сублимацию',
    # «Интересно (узнать|услышать|понять) (про|о|об) …»
    'Интересно узнать про сублимацию', 'Интересно услышать о массе', 'Интересно понять об инерции',
    # «Было бы здорово (понять|узнать) …»
    'Было бы здорово понять принцип инерции', 'Было бы здорово узнать про сублимацию',
    # «В двух словах (про|о|об) …»
    'В двух словах про инерцию', 'В двух словах о массе', 'В двух словах об энтропии',
    # «<термин> для меня загадка»
    'Инерция для меня загадка', 'Энтропия для меня загадка', 'Гидравлический удар для меня загадка',
    # «Не понимаю, (как|почему|зачем|что|чем) …»
    'Не понимаю, как работает насос', 'Не понимаю, почему небо голубое', 'Не понимаю, зачем нужен налог',
    'Не понимаю, что такое энтропия', 'Не понимаю, чем масса отличается от веса',
    # «Мне непонятно, …»
    'Мне непонятно, как это работает', 'Мне непонятно, зачем нужен налог', 'Мне непонятно определение энтропии',
)


def ids(values):
    return [f'{i:02d}' for i in range(len(values))]


@pytest.mark.parametrize('profile', PROFILES)
@pytest.mark.parametrize('state', STATES)
@pytest.mark.parametrize('text', INDIRECT_REQUESTS, ids=ids(INDIRECT_REQUESTS))
def test_an_indirect_request_is_a_question_with_the_text_as_said(text, state, profile):
    """DEF-T-01: «Хочу узнать про X» starts an answer exactly as «Что такое X?» does, and the text goes on as it was said."""
    d = decide(text, STATES[state], PROFILES[profile])
    assert d.kind == QUESTION and d.question == text, (text, d)


def test_the_fillers_in_front_of_an_indirect_request_are_not_part_of_the_question():
    assert decide('Ну хочу узнать про фотосинтез').question == 'хочу узнать про фотосинтез'
    assert decide('Так, хотелось бы разобраться в налогах').question == 'хотелось бы разобраться в налогах'


FRAMES_WITHOUT_AN_OBJECT = (
    'Хочу узнать', 'Хочу узнать про', 'Хотелось бы', 'Хотелось бы понять', 'Хотелось бы понять в', 'Интересно узнать', 'Интересно узнать про',
    'Было бы здорово', 'Было бы здорово понять', 'В двух словах', 'В двух словах про', 'Для меня загадка', 'Мне непонятно', 'Хочу узнать про это',
)


@pytest.mark.parametrize('state', STATES)
@pytest.mark.parametrize('text', FRAMES_WITHOUT_AN_OBJECT, ids=ids(FRAMES_WITHOUT_AN_OBJECT))
def test_a_request_frame_without_a_content_word_stays_quiet(text, state):
    """«Хочу узнать» alone asks nothing: at least one content word besides the frame is needed, waiting portion or not."""
    assert decide(text, STATES[state]).kind not in (QUESTION, CORRECTION), text


def test_a_request_frame_without_an_object_does_not_retire_the_waiting_portion():
    for text in ('Хочу узнать', 'Хотелось бы понять', 'Было бы здорово узнать', 'В двух словах', 'Мне непонятно'):
        assert decide(text).kind == QUIET, text


NOT_A_REQUEST_FRAME = ('Хочу узнать у соседей', 'Хочу пить', 'Хотелось бы поехать на море', 'Было бы здорово поехать на море',
                       'Интересно узнать у кого-нибудь', 'Для меня это загадка')


@pytest.mark.parametrize('state', STATES)
@pytest.mark.parametrize('text', NOT_A_REQUEST_FRAME, ids=ids(NOT_A_REQUEST_FRAME))
def test_words_that_only_resemble_a_request_frame_are_not_a_question(text, state):
    assert decide(text, STATES[state]).kind not in (QUESTION, CORRECTION), text


def test_the_repeat_of_a_portion_that_is_an_indirect_request_is_an_ack_not_a_question():
    waiting = H.waiting('Хочу узнать про налоги', 'и сборы')
    assert decide('Хочу узнать про налоги', waiting).kind == ACK
    longer = H.waiting('Хочу узнать про налоги и сборы', 'дальше')
    assert decide('Хочу узнать про налоги', longer).kind in (REPLAY, QUIET)


@pytest.mark.parametrize('phrase', ['Хочу узнать про фотосинтез', 'Хотелось бы разобраться в налогах', 'Интересно услышать про сублимацию',
                                    'Было бы здорово понять принцип инерции', 'В двух словах про энтропию', 'Энтропия для меня загадка',
                                    'Мне непонятно определение энтропии'])
def test_dispatch_an_indirect_request_retires_the_waiting_portion_and_starts_an_answer(tmp_path, phrase):
    d = fresh(tmp_path)
    out = d.say(phrase)
    assert out.types[0] == 'cancel' and out.types[1] in ('route', 'lookup'), (phrase, out.types)
    assert out.speaks == [], 'the old portion must not be spoken again'
    assert d.controller.question_text == phrase


# The speaker's own need to understand (coordinator ruling, INTEG7): E3a-rest ruling 5 made «нужно» / «надо» statements, and «Мне нужно понять
# гидравлический удар» went silent (T-A F01 need_to_understand, T-B MM4). «мне|нам (нужно|надо|необходимо|хочется|хотелось бы) (понять|узнать|
# разобраться|выяснить|уточнить) X» is an indirect request: the speaker's own need to understand is never a statement about the world.
OWN_NEED_REQUESTS = (
    'Мне нужно понять гидравлический удар', 'Мне нужно понять, что такое механика', 'Мне нужно понять ледниковую морену',
    'Нам надо понять, как работает насос', 'Мне необходимо узнать про налоги', 'Нам необходимо разобраться в налогах',
    'Мне хочется понять принцип инерции', 'Мне хотелось бы узнать про сублимацию', 'Нам хотелось бы разобраться, почему небо голубое',
    'Мне надо выяснить, что такое энтропия', 'Нам нужно уточнить ставку налога на прибыль',
)
OWN_NEED_STATEMENTS = (
    'Нужно остановить платёж по счёту', 'Мне нужно остановить платёж по счёту', 'Нам надо повторить опыт через неделю', 'Мне нужно понять',
    'Нам надо узнать про это', 'Мне хочется пить', 'Мне хотелось бы поехать на море', 'Мне нужно',
)


@pytest.mark.parametrize('profile', PROFILES)
@pytest.mark.parametrize('state', STATES)
@pytest.mark.parametrize('text', OWN_NEED_REQUESTS, ids=ids(OWN_NEED_REQUESTS))
def test_the_speakers_own_need_to_understand_something_is_a_question_with_the_text_as_said(text, state, profile):
    d = decide(text, STATES[state], PROFILES[profile])
    assert d.kind == QUESTION and d.question == text, (text, d)


@pytest.mark.parametrize('state', STATES)
@pytest.mark.parametrize('text', OWN_NEED_STATEMENTS, ids=ids(OWN_NEED_STATEMENTS))
def test_an_own_need_with_no_request_verb_or_nothing_to_understand_is_no_question(text, state):
    """«Нужно остановить платёж по счёту» stays a statement (E3a-rest ruling 5); so does an own need of something else, or of nothing named."""
    assert decide(text, STATES[state]).kind not in (QUESTION, CORRECTION), text


@pytest.mark.parametrize('phrase', ['Мне нужно понять гидравлический удар', 'Нам надо выяснить, что такое энтропия'])
def test_dispatch_the_speakers_own_need_to_understand_retires_the_waiting_portion_and_starts_an_answer(tmp_path, phrase):
    d = fresh(tmp_path)
    out = d.say(phrase)
    assert out.types[0] == 'cancel' and out.types[1] in ('route', 'lookup'), (phrase, out.types)
    assert out.speaks == [] and d.controller.question_text == phrase


@pytest.mark.parametrize('phrase', ['Хочу узнать', 'Хотелось бы понять', 'В двух словах про', 'Мне непонятно'])
def test_dispatch_a_request_frame_without_an_object_leaves_the_waiting_portion_alone(tmp_path, phrase):
    d = fresh(tmp_path)
    out = d.say(phrase)
    assert not out.destroyed and out.after == out.before and out.model_calls == 0, (phrase, out.types)


# =====================================================================================================================================
# 2. A rhetorical or backchannel exclamation (DEF-T-02)
# =====================================================================================================================================

EXCLAMATIONS = ('Серьёзно?', 'Правда?', 'Неужели?', 'Вот как?', 'Да ладно?', 'Кто бы сомневался?', 'Ну и что с того?', 'И что?', 'Как так?',
                'Разве?', 'Ого?', 'Да?', 'Точно?')
EXCLAMATIONS_WITH_FILLERS = ('Хм, серьёзно?', 'Ну правда?', 'А неужели?', 'О, правда?', 'Хм, ну, да ладно?', 'Ну, и что с того?', 'Э-э, вот как?',
                             'Ну да?', 'А точно?', 'Хм, разве?', 'Ого, серьёзно?', 'Серьёзно? Правда?', 'Да ладно? Серьёзно?')
WITHOUT_THE_QUESTION_MARK = ('Серьёзно', 'Правда.', 'Неужели!', 'Вот как', 'Да ладно!', 'Кто бы сомневался.', 'Ну и что с того', 'И что', 'Как так!',
                             'Разве', 'Ого!', 'Да.', 'Точно!')


@pytest.mark.parametrize('profile', PROFILES)
@pytest.mark.parametrize('state', STATES)
@pytest.mark.parametrize('text', EXCLAMATIONS + EXCLAMATIONS_WITH_FILLERS + WITHOUT_THE_QUESTION_MARK,
                         ids=ids(EXCLAMATIONS + EXCLAMATIONS_WITH_FILLERS + WITHOUT_THE_QUESTION_MARK))
def test_a_rhetorical_exclamation_is_neither_a_question_nor_a_request_to_hear_the_portion_again(text, state, profile):
    """DEF-T-02: «Серьёзно?» retires nothing and asks nothing, «?» or not, with a portion waiting or not."""
    d = decide(text, STATES[state], PROFILES[profile])
    assert (d.kind, d.reason) == (QUIET, 'rhetorical_exclamation'), (text, d)


@pytest.mark.parametrize('text', ['Что?', 'что', 'Как?', 'А?', 'что-что?', 'не расслышал', 'не понял', 'ну не понял', 'Ну как?'])
def test_the_hearing_repairs_keep_their_meaning_next_to_the_exclamations(text):
    """«Что?» and «Как?» are in no exclamation phrase: they still ask to hear the portion again."""
    assert decide(text).kind == REPLAY, text


def test_how_is_still_the_follow_up_question_when_nothing_waits():
    assert decide('Как?', COMPLETED).kind == QUESTION
    assert decide('Как?', None).kind == QUESTION


REAL_QUESTIONS_WITH_AN_EXCLAMATION_WORD = (
    'Это правда?', 'Правда ли что вода кипит при ста градусах', 'Разве вода кипит при ста градусах?', 'Точно сто градусов?', 'Серьёзно ли это',
    'Да, а почему так?', 'Неужели это так работает?', 'Как так получилось?', 'Как так получилось', 'Вот как это работает?',
)


@pytest.mark.parametrize('state', STATES)
@pytest.mark.parametrize('text', REAL_QUESTIONS_WITH_AN_EXCLAMATION_WORD, ids=ids(REAL_QUESTIONS_WITH_AN_EXCLAMATION_WORD))
def test_a_real_question_that_contains_an_exclamation_word_stays_a_question(text, state):
    assert decide(text, STATES[state]).kind == QUESTION, text


OBJECTIONS_IN_A_QUESTION_FORM = ('Хм, интересно, а может, всё не так?', 'Хм, интересно, а может, всё совсем не так?', 'Неправда?', 'Не согласен?',
                                 'Ошибка?', 'Серьёзно? Это неверно?')


@pytest.mark.parametrize('state', STATES)
@pytest.mark.parametrize('text', OBJECTIONS_IN_A_QUESTION_FORM, ids=ids(OBJECTIONS_IN_A_QUESTION_FORM))
def test_an_utterance_with_an_objection_marker_is_not_rhetorical_it_goes_to_the_cloud(text, state):
    """«Хм, интересно, а может, всё не так?» is an objection: it stays a question to the cloud (answer policy v2 checks it)."""
    assert decide(text, STATES[state]).kind in (QUESTION, CORRECTION), text


@pytest.mark.parametrize('phrase', EXCLAMATIONS)
def test_dispatch_an_exclamation_leaves_the_waiting_portion_alone_and_speaks_nothing(tmp_path, phrase):
    d = fresh(tmp_path)
    out = d.say(phrase)
    assert not out.destroyed and out.after == out.before and out.model_calls == 0 and out.speaks == [], (phrase, out.types, out.speaks)
