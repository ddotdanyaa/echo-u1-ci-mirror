"""What an utterance means while a portion waits (WAVE 2 / Task A; DEF-ACK-12, 15, 16, 17, 18, MT-G4).

Decision order under test (classifier.analyze): a repeat attempt first (full -> ack, partial / near -> never a new
question), then the commands (stop, repeat request), then a new turn (clarification, correction, «ли»-question, topic
change), and silence for everything else. Through the real ``analyze`` with the production profile
(ack_match=ru_aligned, on_mismatch=silent) and, where the classic profiles must agree, with ``stem``, ``exact`` and the
default ``replay_if_attempt``.
"""
import pytest

import helpers_s6_ack as H
from echo_sync.classifier import ACK, CLARIFY_REPAIR, CORRECTION, QUESTION, QUIET, REPEAT, REPLAY, STOP, analyze

PORTION = 'Наклон земной оси'
WAITING = H.waiting(PORTION)
COMPLETED = dict(H.waiting(PORTION), completed=True)
PENDING = dict(H.waiting(PORTION), completed=True, pending_turn='t1')
PROD = H.PROD_SETTINGS
CLASSIC = {'ack_match': 'stem'}                      # settings.DEFAULTS: replay_if_attempt
CLASSIC_SILENT = {'ack_match': 'stem', 'on_mismatch': 'silent'}
EXACT = {'ack_match': 'exact'}


def kind(text, state=WAITING, settings=PROD, portion=None):
    if portion is not None:
        state = H.waiting(portion)
    return analyze(text, state, [], settings).kind


def ids(values):
    return [f'{i:02d}' for i in range(len(values))]


# -- a repeat attempt comes first ----------------------------------------------------------------------------------------

@pytest.mark.parametrize('settings', [PROD, CLASSIC, CLASSIC_SILENT, EXACT], ids=['ru_aligned', 'stem', 'stem-silent', 'exact'])
@pytest.mark.parametrize('heard,portion', [
    ('Наклон?', 'Наклон земной оси'), ('земной оси?', 'Наклон земной оси'), ('Когда температура падает', 'Когда температура падает ниже нуля'),
    ('Как правило', 'Как правило, вода кипит'), ('вода кипит?', 'Как правило, вода кипит'), ('около 300', 'около 300 000 километров'),
    ('300 000?', 'около 300 000 километров'), ('Что такое', 'Что такое налоги и сборы'), ('почему так?', 'Вот почему так получилось'),
    ('Зависит ли инерция', 'Зависит ли инерция от массы'), ('инерция от массы?', 'Зависит ли инерция от массы'),
    ('расскажи про', 'Расскажи про сублимацию'), ('про сублимацию?', 'Расскажи про сублимацию'),
])
def test_a_part_of_the_waiting_portion_is_an_attempt_never_a_new_question_in_every_matcher(heard, portion, settings):
    assert kind(heard, settings=settings, portion=portion) in (REPLAY, QUIET), (heard, portion, analyze(heard, H.waiting(portion), [], settings))


@pytest.mark.parametrize('settings', [PROD, CLASSIC], ids=['ru_aligned', 'stem'])
def test_a_full_repeat_is_an_ack_even_when_it_looks_like_a_question_or_a_command(settings):
    for portion in ('Что такое инерция', 'Расскажи подробнее об этом', 'Зависит ли инерция от массы', 'Теперь про сублимацию',
                    'Повтори я не расслышал', 'Это неверно потому что'):
        assert kind(portion + '?', settings=settings, portion=portion) == ACK, portion


# -- stop (DEF-ACK-18) ------------------------------------------------------------------------------------------------------

STOPS = ('стоп', 'Стоп!', 'стоп стоп', 'стоп-стоп', 'стоп, стоп, стоп', 'стоп пожалуйста', 'стоп, пожалуйста', 'пожалуйста стоп',
         'стой', 'Стойте', 'хватит', 'Хватит уже', 'замолчи', 'Замолчите', 'остановись', 'Остановитесь, пожалуйста',
         'отмена', 'прекрати', 'Прекратите', 'ну стоп', 'так, стоп!', 'э-э стоп', 'stop', 'cancel', 'стоп, хватит')


@pytest.mark.parametrize('state', [WAITING, COMPLETED, PENDING, None], ids=['waiting', 'completed', 'pending', 'no-state'])
@pytest.mark.parametrize('text', STOPS, ids=ids(STOPS))
def test_stop_is_a_stop_whenever_the_utterance_is_essentially_the_command(text, state):
    assert analyze(text, state, [], PROD).kind == STOP, text


@pytest.mark.parametrize('settings', [PROD, CLASSIC, CLASSIC_SILENT, EXACT], ids=['ru_aligned', 'stem', 'stem-silent', 'exact'])
def test_stop_does_not_depend_on_the_matcher(settings):
    for text in ('стой', 'хватит', 'стоп стоп'):
        assert analyze(text, WAITING, [], settings).kind == STOP


NOT_STOPS = ('не стоп а продолжай говорить дальше', 'стоп стоп стоп стоп', 'остановись на красный свет иначе будет авария',
             'стоп кадр', 'остановка', 'хватит ли денег на эту покупку', 'стоп сигнал горит красным цветом', 'не хватит',
             'тише', 'пока', 'до свидания', 'это всё')


@pytest.mark.parametrize('text', NOT_STOPS, ids=ids(NOT_STOPS))
def test_a_stop_word_inside_other_speech_is_not_a_stop(text):
    assert analyze(text, WAITING, [], PROD).kind != STOP, text


def test_a_full_repeat_wins_over_a_stop_word_and_a_stop_word_wins_over_a_partial_attempt():
    assert kind('Стоп сигнал горит красным', portion='Стоп сигнал горит красным') == ACK
    assert kind('стоп', portion='Стоп сигнал горит красным') == STOP
    assert kind('хватит', portion='Хватит ли нам времени') == STOP


# -- repeat requests (DEF-ACK-17) --------------------------------------------------------------------------------------------

REPEAT_REQUESTS = ('повтори', 'Повторите', 'повтор', 'повторить', 'ещё раз', 'еще разок', 'повтори пожалуйста', 'пожалуйста повтори',
                   'повтори ещё раз', 'повтори, пожалуйста, ещё раз', 'ещё раз пожалуйста', 'ещё раз, пожалуйста', 'повторить пожалуйста',
                   'можешь повторить', 'Можете повторить, пожалуйста', 'можно ещё раз', 'давай ещё раз', 'повтори это', 'ну повтори',
                   'Повтори, я не расслышал.', 'Я не расслышал, повтори', 'Повторите, пожалуйста, я не услышала', 'ещё раз?')


@pytest.mark.parametrize('settings', [PROD, CLASSIC, CLASSIC_SILENT], ids=['ru_aligned', 'stem', 'stem-silent'])
@pytest.mark.parametrize('text', REPEAT_REQUESTS, ids=ids(REPEAT_REQUESTS))
def test_every_polite_form_of_a_repeat_request_is_a_repeat_request(text, settings):
    assert analyze(text, WAITING, [], settings).kind == REPEAT, text


@pytest.mark.parametrize('text', ['повтори другое определение', 'повтори пожалуйста что такое налоги', 'можно ещё раз про налоги',
                                  'ещё раз скажу что это неверно', 'повтори я не расслышал 15 процентов', 'можно ли так'])
def test_a_repeat_word_inside_a_longer_request_is_not_a_repeat_request(text):
    assert analyze(text, WAITING, [], PROD).kind != REPEAT, text


# -- hearing repair: «не расслышал», «что?», «а?», «как?» (DEF-ACK-15, 16) -------------------------------------------------------

HEARING_REPAIR = ('не расслышал', 'не расслышала', 'не услышал', 'не услышала', 'не понял', 'не поняла', 'я не понял', 'не слышу',
                  'не слышно', 'ну не понял', 'что', 'Что?', 'что-что?', 'что что', 'чего?', 'ась?', 'а?', 'А?', 'прости?', 'извини?',
                  'простите?', 'как?', 'Как?', 'еще?')


@pytest.mark.parametrize('text', HEARING_REPAIR, ids=ids(HEARING_REPAIR))
def test_a_hearing_repair_request_replays_the_portion_in_the_production_profile(text):
    """A REPLAY (the same portion, at once), not a REPEAT: after a reconnect only an explicit «повтори» may present the stored position."""
    d = analyze(text, WAITING, [], PROD)
    assert d.kind == REPLAY, (text, d)


@pytest.mark.parametrize('text', ['не расслышал', 'не понял', 'не слышу', 'что', 'Что?', 'а', 'ещё', 'чего?', 'что-что?',
                                  'ась?', 'как?', 'прости?'], ids=ids(range(12)))
def test_a_hearing_repair_request_replays_in_the_default_profile_and_never_asks_a_question(text):
    assert analyze(text, WAITING, [], CLASSIC).kind == REPLAY, text
    assert analyze(text, WAITING, [], CLASSIC_SILENT).kind in (REPLAY, QUIET), text


def test_a_bare_a_or_a_bare_ishche_is_not_a_request_in_the_production_profile_but_with_a_question_mark_it_is():
    assert analyze('а', WAITING, [], PROD).kind == QUIET
    assert analyze('ещё', WAITING, [], PROD).kind == QUIET
    assert analyze('а?', WAITING, [], PROD).kind == REPLAY
    assert analyze('ещё?', WAITING, [], PROD).kind == REPLAY


def test_how_is_a_repeat_request_only_while_a_portion_waits():
    """«как?» is «what did you say?» while a portion waits; with nothing waiting it is the follow-up question «how?»."""
    assert analyze('как?', WAITING, [], PROD).kind == REPLAY
    for state in (COMPLETED, PENDING, None):
        assert analyze('как?', state, [], PROD).kind == QUESTION, state
    assert analyze('как', WAITING, [], PROD).kind not in (REPLAY, REPEAT, QUESTION)       # no «?»: not a request, not a question
    assert analyze('как это работает', WAITING, [], PROD).kind == QUESTION


def test_the_other_interjections_are_follow_up_questions_when_nothing_waits():
    for text in ('чего?', 'что-что?', 'ась?', 'прости?'):
        assert analyze(text, COMPLETED, [], PROD).kind == QUESTION, text


def test_an_interjection_that_is_also_the_first_word_of_the_portion_is_still_a_repeat_request():
    assert kind('что?', portion='Что-то вроде электронной') == REPLAY
    assert kind('как?', portion='Как правило, вода кипит') == REPLAY
    assert analyze('что?', H.waiting('Что такое налоги'), [], PROD).reason == 'replay_hearing_repair'
    assert kind('как правило', portion='Как правило, вода кипит') in (REPLAY, QUIET)      # two words: a quotation of the portion
    assert kind('что такое', portion='Что такое налоги') in (REPLAY, QUIET)


def test_a_hearing_repair_with_a_real_question_after_it_is_a_question_not_a_repeat():
    assert analyze('не понял что такое налоги', WAITING, [], PROD).reason != 'replay_hearing_repair'
    assert analyze('что? а почему так происходит', WAITING, [], PROD).reason != 'replay_hearing_repair'


# -- a new turn: clarification, «ли», topic change, correction (MT-G4) -------------------------------------------------------

CLARIFICATIONS = ('Расскажи подробнее', 'расскажите подробнее', 'Объясни проще', 'Объясни попроще', 'Покажи пример', 'Приведи пример',
                  'Дай пример', 'А подробнее', 'Подробнее', 'а подробнее?', 'Другой пример', 'Ещё один пример', 'ещё пример',
                  'А почему', 'а зачем', 'А если наоборот', 'а если нет', 'Скажи проще', 'Объясни другими словами')
LI_QUESTIONS = ('Зависит ли инерция от массы', 'Правда ли что вода кипит при ста градусах', 'Можно ли так делать', 'Есть ли исключения',
                'Может ли быть иначе', 'А верно ли это', 'Будет ли это работать', 'Не знаешь ли ты точно')
TOPIC_CHANGES = ('А теперь про сублимацию', 'теперь про налоги', 'Вернёмся к инерции', 'вернемся к началу', 'Давай теперь про бюджет',
                 'давай лучше о погоде', 'Поговорим о массе', 'расскажи про сублимацию', 'А что насчёт налогов',
                 'Скажи единицу массы')
# Candidate 7 (c7-meta round 2, W4 oral exam): «Перейдём к следующей теме» names no topic - it is an examiner's move-on line (a word of going
# on + an exam unit, user_intents.MOVE_ON_*), like «Переходим к следующему вопросу»: the waiting answer is retired quietly and the next topic
# phrase is the question. It was in TOPIC_CHANGES above; what it must still never be is an ACK, a repeat or a «go on» with the old answer.
MOVE_ON_LINES = ('Перейдём к следующей теме', 'Переходим к следующему вопросу')


@pytest.mark.parametrize('state', [WAITING, COMPLETED, None], ids=['waiting', 'completed', 'idle'])
@pytest.mark.parametrize('text', CLARIFICATIONS + LI_QUESTIONS + TOPIC_CHANGES,
                         ids=ids(CLARIFICATIONS + LI_QUESTIONS + TOPIC_CHANGES))
def test_a_clarification_a_li_question_or_a_topic_change_without_a_question_mark_is_a_new_question(text, state):
    d = analyze(text, state, [], PROD)
    assert d.kind == QUESTION, (text, d)
    assert d.question, (text, d)


@pytest.mark.parametrize('state', [WAITING, COMPLETED, None], ids=['waiting', 'completed', 'idle'])
@pytest.mark.parametrize('text', MOVE_ON_LINES, ids=ids(MOVE_ON_LINES))
def test_a_move_on_line_without_a_topic_is_no_command_on_the_old_answer(text, state):
    d = analyze(text, state, [], PROD)
    assert (d.kind, d.reason) == (QUIET, 'move_on_without_content'), (text, d)


def test_a_new_question_keeps_the_words_the_listener_said():
    assert analyze('А подробнее', WAITING, [], PROD).question == 'А подробнее'
    assert analyze('Зависит ли инерция от массы', WAITING, [], PROD).question == 'Зависит ли инерция от массы'
    assert analyze('Ну а теперь про сублимацию', WAITING, [], PROD).question in ('а теперь про сублимацию', 'теперь про сублимацию')


def test_a_clarification_that_is_only_a_part_of_the_portion_is_an_attempt():
    assert kind('подробнее', portion='Подробнее об этом позже') in (REPLAY, QUIET)
    assert kind('расскажи подробнее', portion='Расскажи подробнее о нём не могу') in (REPLAY, QUIET)


@pytest.mark.parametrize('text', ['да', 'угу', 'ага хорошо', 'почему', 'где', 'объясни', 'пример', 'ну', 'как так', 'вряд ли это так',
                                  'то ли да то ли нет', 'едва ли', 'мы вчера обсуждали совсем другую тему в офисе и она всем понравилась',
                                  'теперь понятно', 'Хорошо подробнее потом', 'проще говоря да'])
def test_stray_words_and_background_talk_still_never_cancel_a_waiting_answer(text):
    assert analyze(text, WAITING, [], PROD).kind not in (QUESTION, CORRECTION, STOP, REPEAT), text


@pytest.mark.parametrize('text', ['Это неверно', 'Нет, это неверно', 'Это неправильно', 'Нет, это не так', 'Это не так', 'Нет не так',
                                  'Не так', 'Это неправда', 'Ты ошибся', 'Вы ошиблись', 'Ты неправ', 'Ты ошибаешься'])
def test_a_free_form_disagreement_retires_the_answer_in_the_production_profile(text):
    d = analyze(text, WAITING, [], PROD)
    assert d.kind == CORRECTION and d.question == text, (text, d)


@pytest.mark.parametrize('text', ['Нет, не так, инерция не сила', 'Это неверно, масса не зависит от цвета',
                                  'Нет, я имел в виду массу', 'Ты ошибся, это не масса', 'Неверно, скорость звука больше'])
def test_a_correction_with_a_target_is_a_correction_in_every_profile(text):
    for settings in (PROD, CLASSIC, CLASSIC_SILENT):
        d = analyze(text, WAITING, [], settings)
        assert d.kind == CORRECTION and d.question == text, (text, settings, d)


def test_a_contrast_without_a_marker_is_not_taken_for_a_correction():
    """«не знаю, а ты?» has the shape of «не масса, а скорость»; without a disagreement marker it stays background talk."""
    for text in ('Не знаю, а ты как', 'Не рыба, а млекопитающее', 'Не масса, а скорость'):
        assert analyze(text, WAITING, [], PROD).kind not in (CORRECTION, QUESTION), text


def test_the_default_profile_still_asks_what_to_correct_for_a_bare_disagreement():
    assert analyze('Это неверно', WAITING, [], CLASSIC).kind == CLARIFY_REPAIR
    assert analyze('Нет, это не так', WAITING, [], CLASSIC).kind == CLARIFY_REPAIR
    assert analyze('Неправильно', WAITING, [], CLASSIC).kind == QUIET
    assert analyze('Неправильно', WAITING, [], PROD).kind == QUIET


def test_a_disagreement_needs_something_to_disagree_with_and_never_interrupts_a_generation():
    assert analyze('Это неверно', None, [], PROD).kind not in (CORRECTION, CLARIFY_REPAIR)
    assert analyze('Это неверно', PENDING, [], PROD).kind == QUIET


def test_a_disagreement_that_is_a_quotation_of_the_portion_is_only_an_attempt_or_an_ack():
    assert kind('Это неверно', portion='Это неверно потому что') in (REPLAY, QUIET)
    assert kind('Это неверно потому что', portion='Это неверно потому что') == ACK


# -- what stays as it was ----------------------------------------------------------------------------------------------------

def test_a_wrong_number_or_term_is_silent_not_a_question_and_not_an_ack():
    assert kind('наклон земной оси', portion='Наклон земной оси') == ACK
    assert kind('наклон земного вала', portion='Наклон земной оси') in (REPLAY, QUIET)
    assert kind('ставка 14 процентов', portion='Ставка 13 процентов') in (REPLAY, QUIET)
    assert kind('ставка не 13 процентов', portion='Ставка 13 процентов') in (REPLAY, QUIET)


# -- the same decisions through ControlledMedia, built as the host builds it ------------------------------------------------------

def fresh(tmp_path, answer=None):
    return H.Dictation(tmp_path / 'd', answer or H.LONG_ANSWERS[1])


@pytest.mark.parametrize('phrase', ['Расскажи подробнее', 'Объясни проще', 'А подробнее', 'Приведи пример', 'Зависит ли инерция от массы',
                                    'А теперь про сублимацию', 'Вернёмся к инерции', 'Это неверно', 'Нет, не так, инерция не сила'])
def test_dispatch_a_new_turn_without_a_question_mark_retires_the_waiting_portion_and_starts_an_answer(tmp_path, phrase):
    d = fresh(tmp_path)
    out = d.say(phrase)
    assert out.types[0] == 'cancel' and out.types[1] in ('route', 'lookup'), (phrase, out.types)
    assert out.speaks == [], 'the old portion must not be spoken again'


@pytest.mark.parametrize('phrase', ['да', 'угу', 'почему', 'где', 'объясни', 'пример', 'мы вчера обсуждали совсем другую тему в офисе',
                                    'Неправильно'])
def test_dispatch_stray_words_do_not_retire_the_waiting_portion(tmp_path, phrase):
    d = fresh(tmp_path)
    out = d.say(phrase)
    assert not out.destroyed and out.after == out.before and out.model_calls == 0, (phrase, out.types)


@pytest.mark.parametrize('phrase', ['что?', 'как?', 'чего?', 'а?', 'не понял', 'Что?', 'не расслышал'])
def test_dispatch_a_hearing_repair_speaks_the_same_portion_at_once(tmp_path, phrase):
    d = fresh(tmp_path)
    portion = d.current
    out = d.say(phrase)
    assert out.speaks == [portion] and out.after == out.before and out.model_calls == 0 and not out.destroyed, (phrase, out.actions)


def test_dispatch_how_is_a_question_once_the_answer_is_complete(tmp_path):
    d = fresh(tmp_path)
    for _ in range(len(d.chunks)):
        d.say(d.current)
    assert d.completed
    out = d.say('как?')
    assert out.types[0] == 'cancel' and out.types[1] in ('route', 'lookup'), out.types


@pytest.mark.parametrize('phrase', ['хватит', 'замолчи', 'стой', 'стоп стоп', 'Остановись, пожалуйста'])
def test_dispatch_stop_variants_end_the_dictation(tmp_path, phrase):
    d = fresh(tmp_path)
    chunks = d.chunks
    out = d.say(phrase)
    # CL2, ruling 1: the dictation stops (the audio is cut, nothing more is said) and the answer is paused, its plan kept.
    assert out.types == ['cancel'] and d.state.get('paused') and d.chunks == chunks, (phrase, out.types)


def test_dispatch_a_stray_what_in_a_reopened_call_does_not_present_the_stored_position(tmp_path):
    """After a reconnect only an explicit «повтори» may present the persisted portion (quiet_reopen); «что?» is not explicit."""
    a = H.Dictation(tmp_path / 'session', H.LONG_ANSWERS[4])
    a.say(a.current)                                   # one portion confirmed, the next one is stored
    b = a.reconnect()                                  # a new call over the same database, built as the host builds it
    for text in ('что?', 'а?', 'не понял', 'как?', 'не расслышал'):
        assert b.say(text).speaks == [], text
    assert b.say('повтори').speaks == [a.chunks[1]]
