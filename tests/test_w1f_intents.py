"""W1F-C (wave W1 fixes, 3 Nov): natural forms of commands and intents, ASR-robust (class C3 of the W1 analysis, groups G3-G6).

Evidence: .superpowers/sdd/wave2/w1-analysis-summary.txt and w1-analysis-full.json (runs W1 20261103-031522, v1 20261103-030307). Every
utterance below that is quoted with a leading space is the provider's final as the live call logged it; each one was decided
silent/mismatch_policy_silent (or a wrong question) on 66b29f1 because the intents were CLOSED EXACT-PHRASE LISTS on raw ASR tokens.

The ruling (task-w1fix-briefs.md, W1F-C): replace them by small closed GRAMMARS, no fuzzy matching -
  [lead: так/ладно/окей/ну/хорошо/давай(-ка)/слушай/а]* + CORE + [adjunct: (на) секунду/секундочку/минутку/немного/пока/пожалуйста/-ка]*;
  STOP cores + подожди(те)/погоди(те)/постой(те)/обожди/пауза/хватит;
  REPEAT = [скажи/произнеси/повтори/давай]? + (ещё раз | ещё разок | заново | снова) + [последнее / последнюю часть / фразу / кусок / это]?;
  NEXT = [идём/пошли/поехали/едем/двигаемся/давай(-ка)/продолжай/говори]? + дальше | далее | следующ*;
  disagreement = opener (нет/не/да нет/нет-нет/ну нет)? + at most 2 particles (и, же, ну, ведь, всё-таки, вообще, по-моему, точно) + a marker in
  the first clause (неверно/неправильно/не так/ошибка/ошибаешься/не согласен/не прав); reported speech stays negative;
  return/position meta as clauses inside longer utterances; small talk as a bag of closed tokens after fillers; a request at the start of
  ANY clause after a discourse preamble; ASR token folding («по вто ри») for every closed vocabulary. Every word outside the grammar keeps
  the utterance content («Подожди, я хотел спросить про …» stays a correction).
"""
import re

import pytest

import helpers_s6_ack as H
from echo_sync.classifier import (ACK, CLARIFY_REPAIR, CORRECTION, GREETING, NEXT, QUESTION, QUIET, REPEAT, REPLAY, RESUME, STOP,
                                  analyze)
from echo_sync.engine import going_on
from echo_sync.user_intents import fold_asr, return_topic
from test_first_cue_never_silent import created, delta, done
from test_task1_review_round2 import Session

PROD = H.PROD_SETTINGS
PROFILES = {'prod': PROD}


def ids(values):
    return [f'{i:02d}' for i in range(len(values))]


def decide(text, state=None, settings=PROD, portion='Обычно берут'):
    return analyze(text, H.waiting(portion) if state is None else state, [], settings)


# =====================================================================================================================================
# 1. ASR word-boundary folding: the same letters, only the provider's word boundaries differ (G3 root cause 2)
# =====================================================================================================================================

@pytest.mark.parametrize('heard,folded', [
    ('нет и это невер но', ['нет', 'и', 'это', 'неверно']),
    ('это непра вильно', ['это', 'неправильно']),
    ('по вто ри', ['повтори']),
    ('даль ше', ['дальше']),
    ('подо жди', ['подожди']),
    ('при вет', ['привет']),
])
def test_split_tokens_of_a_closed_vocabulary_word_are_folded(heard, folded):
    assert fold_asr(heard.split()) == folded


@pytest.mark.parametrize('heard', ['сколько рук у осьмин ога', 'не так', 'на секунду', 'стоп кадр', 'еще раз', 'нет нет'])
def test_content_and_two_real_words_are_never_folded(heard):
    """Only a concatenation that IS a word of a closed vocabulary is folded; content words have no lexicon here and stay as heard."""
    assert fold_asr(heard.split()) == heard.split()


# =====================================================================================================================================
# 2. Disagreement (G3: w1_07 step 3, «Нет, и это невер но» was swallowed and the stale «Да, на сфере» auto-repeated)
# =====================================================================================================================================

OBJECTIONS = ('Нет, и это неверно.', ' Нет, и это невер но', 'Нет же, это неверно.', 'Это вообще неверно.', 'Я с этим не согласен.',
              'Не согласен.', 'Да нет, неверно.', 'Не, это неверно.', 'Нет-нет, это неверно.', 'Это ошибка.', 'Нет, по-моему, это неверно.',
              'Нет, всё-таки это неверно.', 'Это непра вильно', 'Нет, это невер но', 'Ошибаешься.', 'Нет, ты не прав.', 'Ну нет, это не так.',
              'Нет, ведь это неверно.', 'Это точно неверно.', 'Я не согласна.')


@pytest.mark.parametrize('text', OBJECTIONS, ids=ids(OBJECTIONS))
def test_a_natural_objection_retires_the_answer_in_the_production_profile(text):
    d = decide(text, portion='Да, на сфере')
    assert d.kind == CORRECTION and d.question == text.strip(), (text, d)


OBJECTIONS_WITH_A_TARGET = ('Нет, и это неверно. На самом деле сумма углов всегда триста шестьдесят градусов.',
                            'Я не согласен, там триста шестьдесят градусов.', 'Это ошибка, там триста шестьдесят.',
                            'Нет же, неверно, сумма больше.')


@pytest.mark.parametrize('profile', PROFILES)
@pytest.mark.parametrize('text', OBJECTIONS_WITH_A_TARGET, ids=ids(OBJECTIONS_WITH_A_TARGET))
def test_an_objection_that_says_what_is_wrong_is_a_correction_in_every_profile(text, profile):
    d = decide(text, settings=PROFILES[profile], portion='Да, на сфере')
    assert (d.kind, d.reason, d.question) == (CORRECTION, 'explicit_answer_repair', text), (text, d)


NOT_OBJECTIONS = ('Он сказал нет я имел в виду другую ставку', 'В тексте написано это неверно', 'Нет', 'Да нет наверное', 'Неправильно',
                  'Ошибка', 'Не знаю, а ты как', 'Не рыба, а млекопитающее', 'Не масса, а скорость', 'Я не прав', 'Мне кажется, я ошибся',
                  'Он не согласен', 'Они ошиблись в расчётах', 'Нет, это так', 'И он сказал, что это неверно')


@pytest.mark.parametrize('profile', PROFILES)
@pytest.mark.parametrize('text', NOT_OBJECTIONS, ids=ids(NOT_OBJECTIONS))
def test_reported_speech_a_bare_no_and_talk_to_oneself_are_no_objection(text, profile):
    assert decide(text, settings=PROFILES[profile], portion='Да, на сфере').kind not in (CORRECTION, CLARIFY_REPAIR), text


def tiles():
    """w1_05 step 5: the answer to the tiles question waits."""
    return dict(H.waiting('Если брать от 20 квадратных', 'метров, с запасом'),
                question='Сколько плитки нужно на комнату четыре на пять метров с запасом десять процентов?')


@pytest.mark.parametrize('text', [' Нет, я ошибся, запас не десять, а двадцать', 'Нет, я ошибся, запас не десять, а двадцать процентов',
                                  'Я оговорился, комната пять на шесть метров', 'Ой, я ошиблась, не четыре, а пять'])
def test_a_self_correction_of_the_condition_is_a_correction_while_a_portion_waits(text):
    """W1 w1_05 step 5. G2 (c) of the W1 analysis: «я ошибся» opens a self-correction when what follows restates the question's terms
    (the classifier is this task's file)."""
    d = decide(text, state=tiles())
    assert (d.kind, d.reason, d.question) == (CORRECTION, 'explicit_answer_repair', text.strip()), (text, d)


@pytest.mark.parametrize('text', ['Я ошибся', 'Мне кажется, я ошибся', 'Он ошибся в расчётах', 'Я ошибся дверью, извините',
                                  'Не масса, а скорость'])
def test_an_admission_without_a_corrected_condition_or_about_somebody_else_is_no_correction(text):
    assert decide(text, state=tiles()).kind not in (CORRECTION, CLARIFY_REPAIR), text


@pytest.mark.parametrize('text,portion', [('Это неверно', 'Это неверно при такой ставке'),
                                          ('Я с этим не согласен', 'Я с этим не согласен, потому что'),
                                          ('Нет, это ошибка', 'Нет, это ошибка в расчёте')])
def test_a_quotation_of_the_waiting_portion_stays_an_attempt(text, portion):
    assert decide(text, portion=portion).kind in (REPLAY, QUIET), text


@pytest.mark.parametrize('state', ['waiting', 'completed', 'pending'])
@pytest.mark.parametrize('text', ['Не согласен?', 'Это ошибка?', 'Ты ошибаешься?'])
def test_an_objection_word_asked_as_a_question_is_a_question_for_the_cloud(text, state):
    """«Не согласен?» asks; it is not the listener's verdict (E3a ruling 2 keeps such forms going to the cloud in every state)."""
    states = {'waiting': H.waiting('Да, на сфере'), 'completed': dict(H.waiting('Да, на сфере'), completed=True),
              'pending': dict(H.waiting('Да, на сфере'), completed=True, pending_turn='t1')}
    assert analyze(text, states[state], [], PROD).kind == QUESTION, text


# =====================================================================================================================================
# 3. Commands: STOP / REPEAT / NEXT as [lead]* CORE [adjunct]* (G6: w1_10, w1_11)
# =====================================================================================================================================

STOPS = (' Стой, подожди секунду', ' Так, хватит на секунду', 'Подожди', 'Подождите', 'Погоди', 'Погодите', 'Погоди минутку', 'Постой',
         'Обожди', 'Пауза', 'Подожди-ка', 'Подожди немного', 'Подожди, пожалуйста', 'Стоп, подожди одну секунду', 'Ладно, подожди',
         'Давай-ка подожди', 'Нет, подожди', 'Нет-нет, хватит', 'Секунду, подожди', 'Подо жди', 'Подождите пока')


@pytest.mark.parametrize('profile', PROFILES)
@pytest.mark.parametrize('text', STOPS, ids=ids(STOPS))
def test_a_natural_stop_is_a_stop(text, profile):
    assert decide(text, settings=PROFILES[profile]).kind == STOP, text


NOT_STOPS = ('Секунду', 'Минутку', 'Пока', 'На секунду', 'Немного', 'Стоит подождать до вечера', 'Подожди, Маша, сейчас приду',
             'Пауза между словами важна', 'Стоп стоп стоп стоп', 'Подождите, я хотел спросить про насекомое')


@pytest.mark.parametrize('text', NOT_STOPS, ids=ids(NOT_STOPS))
def test_an_adjunct_alone_or_a_command_word_inside_content_is_not_a_stop(text):
    assert decide(text).kind != STOP, text


def test_a_hold_word_before_a_spoken_correction_keeps_the_correction():
    for text in ('Подожди, я хотел спросить про насекомое', 'Погоди, я имел в виду насекомое', 'Нет, постой, я хотел спросить про кита'):
        d = decide(text)
        assert d.kind in (CORRECTION, QUESTION) and d.question == text, (text, d)


@pytest.mark.parametrize('heard', ['в секунду', 'секунду', 'метров в секунду'])
def test_an_adjunct_never_beats_an_attempt_at_the_waiting_portion(heard):
    assert decide(heard, portion='Триста метров в секунду').kind in (ACK, REPLAY, QUIET), heard


@pytest.mark.parametrize('heard,portion', [('Подождите', 'Подождите пять минут,'), ('Подожди немного', 'Подожди немного, и вода закипит'),
                                           ('Пауза', 'Пауза между вдохами')])
def test_a_hold_word_the_waiting_portion_itself_says_is_an_attempt_at_it(heard, portion):
    """The provider may split the listener's repeat of such a portion; its first piece must not pause the answer. (The stop words keep
    their CL2 precedence: «стоп» for «Стоп сигнал …» is a stop, tests/test_ack_commands.py.)"""
    assert decide(heard, portion=portion).kind in (REPLAY, QUIET), heard
    assert decide('Стоп', portion='Стоп сигнал горит').kind == STOP


REPEATS = (' Скажи-ка последнюю часть заново', 'Повтори заново', 'Скажи заново', 'Давай снова', 'Давай ещё разок', 'Произнеси ещё раз',
           'Скажи ещё разок, пожалуйста', 'Повтори-ка ещё раз', 'Заново', 'Ещё разок, пожалуйста, последнее', 'Не уловил, давай ещё раз',
           'Пов тори', 'по вто ри, пожалуйста', 'Скажи это снова', 'Ладно, повтори последний кусок ещё раз')


@pytest.mark.parametrize('profile', PROFILES)
@pytest.mark.parametrize('text', REPEATS, ids=ids(REPEATS))
def test_a_natural_repeat_request_is_a_repeat_request(text, profile):
    assert decide(text, settings=PROFILES[profile]).kind == REPEAT, text


NOT_REPEATS = ('Начни заново', 'Давайте ещё раз проверим расчёт.', 'Повтори другое определение', 'Скажи что-нибудь снова',
               'Снова пошёл дождь', 'Заново построили мост', 'Произнеси название города', 'Ещё раз нет', 'Повтори, нет, подожди')


@pytest.mark.parametrize('text', NOT_REPEATS, ids=ids(NOT_REPEATS))
def test_a_repeat_word_inside_other_content_is_not_a_repeat_request(text):
    assert decide(text).kind != REPEAT, text


NEXTS = (' Ладно, поехали дальше', ' Идём дальше', 'Идем далее', 'Поехали дальше', 'Пошли дальше', 'Едем дальше', 'Двигаемся дальше',
         'Давай-ка дальше', 'Продолжай дальше', 'Говори дальше', 'Даль ше', 'Ну, идём дальше, пожалуйста', 'Отлично, дальше', 'Понятно, следующую')


@pytest.mark.parametrize('profile', PROFILES)
@pytest.mark.parametrize('text', NEXTS, ids=ids(NEXTS))
def test_a_natural_next_is_next(text, profile):
    assert decide(text, settings=PROFILES[profile], portion='Масса мера инертности').kind == NEXT, text


NOT_NEXTS = ('Идём дальше по списку покупок', 'Поехали дальше на машине', 'Говори дальше что хочешь', 'Перейдём к следующей теме',
             'не стоп а продолжай говорить дальше', 'Дальше будет интереснее', 'Следующая станция Маяковская', 'Дальше нет',
             'Продолжай, нет, подожди')


@pytest.mark.parametrize('text', NOT_NEXTS, ids=ids(NOT_NEXTS))
def test_a_motion_word_inside_content_is_not_next(text):
    assert decide(text, portion='Масса мера инертности').kind not in (NEXT, RESUME), text


# =====================================================================================================================================
# 4. Going on: position and return meta as clauses (G4: w1_08 steps 4/8, w1_12 step 6)
# =====================================================================================================================================

POSITIONS = (' А что было последним', ' А что было последним? Скажи ещё раз.', ' Где мы там прервались', ' На чём мы там остановились',
             'На чём мы остановились?', 'на чем остановились', 'С какого места продолжаем?', 'Что ты последним сказал?',
             'Напомни, где мы остановились', 'Так, на чём я остановился', 'Где мы закончили?', 'Подожди, на чём мы остановились?',
             ' Хорошо, теперь продолжай с того места, где остановился', ' Хорошо, теперь продолжай с того места, где',
             'Продолжай с того места, где мы прервались')


def tried(state):
    """The listener has just tried the waiting portion (the engine's ``attempt_at``): «продолжай» would now move on."""
    return dict(state, attempt_at=[state['revision'], state['chunk_index']])


@pytest.mark.parametrize('text', POSITIONS, ids=ids(POSITIONS))
def test_a_position_question_says_the_waiting_portion_again_even_after_a_try(text):
    waits = H.waiting('Самое глубокое — это Байкал', 'в России.')
    d = analyze(text, waits, [], PROD)
    assert (d.kind, d.reason) == (RESUME, 'resume_position'), (text, d)
    assert going_on(tried(waits), d, now=1.0, window_s=600) == ('reissue', None), text


@pytest.mark.parametrize('text', [' На чём мы', ' На чём мы там', 'на чем'])
def test_the_cut_beginning_of_a_position_question_is_no_question_of_its_own(text):
    """W1 w1_08 step 4: the provider cut «На чём мы | остановились» and the first piece retired the answer that had just been restored. It asks
    nothing by itself; the joined utterance is the position question (the controller's utterance assembly, W1F-B)."""
    d = analyze(text, H.waiting('всего начинается', 'с внезапного'), [], PROD)
    assert d.kind == QUIET, (text, d)
    assert analyze(text + ' остановились', H.waiting('всего начинается', 'с внезапного'), [], PROD).reason == 'resume_position'


def test_a_real_question_that_starts_like_a_position_question_stays_a_question():
    assert decide('На чём мы основываем этот вывод?').kind == QUESTION
    assert decide('На чём работает двигатель', portion='Масса мера инертности').kind == QUESTION


TSUNAMI_Q = 'Расскажи, как возникает цунами'


def bird_after_tsunami():
    """The tsunami answer left after one confirmed portion, the bird answer waiting (w1_08 step 8, before the return)."""
    return {'schema': 2, 'revision': 3, 'question': 'Как называется самая маленькая птица в мире', 'answer': 'Самая маленькая птица в мире',
            'chunks': ['Самая маленькая', 'птица в мире'], 'chunk_index': 0, 'completed': False, 'pending_turn': None, 'entry': 1,
            'history': [{'question': TSUNAMI_Q, 'answer': 'Цунами чаще всего начинается с внезапного', 'at': 0.5,
                         'chunks': ['Цунами чаще', 'всего начинается', 'с внезапного'], 'spoken': 1, 'status': 'interrupted'},
                        {'question': 'Как называется самая маленькая птица в мире', 'answer': 'Самая маленькая птица в мире', 'at': 0.9,
                         'chunks': ['Самая маленькая', 'птица в мире'], 'spoken': 0, 'status': 'active'}]}


RETURNS_WITH_A_POSITION = (' Ладно, возвращаемся к цунами, где мы там прервались', ' Вернёмся к цунами, на чём мы остановились',
                           ' Вернёмся к цунами. На чём мы остановились?', 'Давай вернёмся к цунами, повтори ещё раз', 'Вер нёмся к цунами')


@pytest.mark.parametrize('text', RETURNS_WITH_A_POSITION, ids=ids(RETURNS_WITH_A_POSITION))
def test_a_return_to_a_topic_said_with_a_position_question_restores_that_answer(text):
    state = bird_after_tsunami()
    d = analyze(text, state, [], PROD)
    assert (d.kind, d.reason) == (QUESTION, 'topic_change'), (text, d)
    assert going_on(state, d, now=1.0, window_s=600) == ('restore', 0), (text, d)


@pytest.mark.parametrize('text', ['Вернёмся к цунами, почему оно такое высокое', 'Вернёмся к цунами и расскажи про его скорость',
                                  'Вернёмся к цунами: сколько оно длится?'])
def test_a_return_followed_by_a_new_question_is_that_question_not_a_restore(text):
    state = bird_after_tsunami()
    d = analyze(text, state, [], PROD)
    assert d.kind == QUESTION and going_on(state, d, now=1.0, window_s=600) == (None, None), (text, d)


def test_a_return_to_where_we_started_is_a_return_to_the_first_question():
    d = analyze('Окей, а теперь вернись к тому, с чего мы начинали', bird_after_tsunami(), [], PROD)     # w1_02 step 5
    assert (d.kind, d.reason) == (RESUME, 'resume_return_first'), d


@pytest.mark.parametrize('words,topic', [('ладно возвращаемся к цунами где мы там прервались', 'цунами'),
                                         ('вернемся к цунами на чем мы остановились', 'цунами'),
                                         ('вернемся к тому что ты говорил про цунами', 'цунами')])
def test_the_topic_of_a_return_leaves_the_position_clause_and_the_pointer_out(words, topic):
    assert topic in return_topic(words.split()), words


def test_a_topic_cut_by_the_recogniser_still_names_its_entry():
    """«Меркур ий»: the return's topic words also carry their adjacent concatenations, so the stem of the whole word is there."""
    assert 'меркурий' in return_topic('вернемся к меркур ий'.split())


# =====================================================================================================================================
# 5. Small talk as a bag of closed tokens (G4: w1_12 steps 3 and 5)
# =====================================================================================================================================

SMALL_TALK = (' Слушай, ты меня хорошо слышишь', ' Ты меня вообще слышишь', ' Спасибо, ты молодец', ' Спасибо', 'Спасибо большое',
              'Понятно, спасибо', 'Отлично, спасибо!', 'Ты молодец', 'Алло, ты меня нормально слышишь?', 'Привет, как дела', 'Спа сибо')


@pytest.mark.parametrize('state', ['waiting', 'idle'])
@pytest.mark.parametrize('text', SMALL_TALK, ids=ids(SMALL_TALK))
def test_thanks_praise_and_a_connection_check_with_an_adverb_are_small_talk(text, state):
    st = H.waiting('Самое глубокое — это Байкал') if state == 'waiting' else None
    assert analyze(text, st, [], PROD).kind == GREETING, text


NOT_SMALL_TALK = ('Спасибо, а почему небо голубое?', 'Ты меня слышишь, сколько ног у паука?', 'Как дела у экономики Японии?',
                  'Спасибо за урок, завтра продолжим', 'Ты', 'Меня', 'Как ты думаешь, почему так')


@pytest.mark.parametrize('text', NOT_SMALL_TALK, ids=ids(NOT_SMALL_TALK))
def test_small_talk_words_next_to_content_are_not_small_talk(text):
    assert analyze(text, H.waiting('Самое глубокое — это Байкал'), [], PROD).kind != GREETING, text


# =====================================================================================================================================
# 6. A request at the start of any clause after a discourse preamble (G5: w1_09 steps 2 and 5; G4: w1_08 step 6)
# =====================================================================================================================================

PREAMBLE_REQUESTS = (' Подожди, лучше скажи другое, сколько рук у осьмин ога', ' Ладно, давай все же про компас, куда показывает его стрелка',
                     ' А про гитару ещё раз, сколько там струн', 'Стой, а теперь скажи, где живут пингвины',
                     'Слушай, подожди, лучше скажи, когда началась война', 'Ладно, давай тогда про погоду', 'Кстати, сколько лет Байкалу',
                     'Подожди, подожди, а почему вода мокрая', 'Нет, лучше скажи, кто изобрёл радио',
                     'Спасибо, понятно, а теперь скажи, сколько ног у паука', 'Привет, слушай, а сколько ног у паука')


@pytest.mark.parametrize('text', PREAMBLE_REQUESTS, ids=ids(PREAMBLE_REQUESTS))
def test_a_request_after_a_discourse_preamble_is_a_question_while_a_portion_waits(text):
    d = decide(text, portion='Внутри компаса есть намагниченная')
    assert d.kind == QUESTION, (text, d)


@pytest.mark.parametrize('text', [' А можно какой-нибудь пример из жизни', 'Можешь привести какой-то пример', 'Можно ещё один пример',
                                  'Можно другой пример?'])
def test_a_modal_request_with_a_determiner_before_its_object_is_a_question(text):
    """W1 w1_01 step 3: «какой-нибудь» stood between «можно» and «пример», and the request was taken for a failed repeat."""
    assert decide(text, portion='происходит, когда природные').kind == QUESTION, text


def test_the_discourse_preamble_is_not_part_of_the_question_but_a_topic_frame_is():
    assert decide(' Подожди, лучше скажи другое, сколько рук у осьмин ога').question == 'сколько рук у осьмин ога'
    assert decide(' А про гитару ещё раз, сколько там струн').question == 'про гитару ещё раз, сколько там струн'


NOT_PREAMBLE_REQUESTS = ('Мы вчера ходили в кино, там было шумно', 'мы вчера обсуждали как работает бюджет', 'Подожди, Маша, сейчас приду',
                         'А про Машу говорили, что она уехала', 'Ладно, где', 'Я вчера была у врача, как же там холодно')


@pytest.mark.parametrize('text', NOT_PREAMBLE_REQUESTS, ids=ids(NOT_PREAMBLE_REQUESTS))
def test_bystander_speech_and_a_lone_question_word_after_a_preamble_stay_quiet(text):
    assert decide(text, portion='Внутри компаса есть намагниченная').kind not in (QUESTION, CORRECTION), text


@pytest.mark.parametrize('heard,portion', [('Ладно, где живут пингвины', 'Где живут пингвины'),
                                           ('Подожди, сколько рук у осьминога', 'Сколько рук у осьминога')])
def test_a_preamble_before_the_waiting_portion_is_still_a_repeat_of_it(heard, portion):
    assert decide(heard, portion=portion).kind in (ACK, REPLAY, QUIET), heard


# =====================================================================================================================================
# 7. Through the real ControlledMedia, built as the host builds it (the live shapes of W1; one provider turn per utterance)
# =====================================================================================================================================

def words_of(text):
    return re.findall(r'\s*\S+', text)


def stream(s, tid, text, start, end):
    pieces = words_of(text)
    s.at(start, created(tid, 'assistant', pieces[0]))
    step = (end - start) / max(1, len(pieces))
    for n, piece in enumerate(pieces[1:], 1):
        s.at(round(start + n * step, 3), delta(tid, piece, n))
    s.at(end, done(tid, 'assistant', text))


def user(s, tid, text, start, end):
    s.at(start, lambda ss: ss.c.speech_started())
    s.at(start + 0.01, created(tid, 'user', words_of(text)[0]))
    s.at(end, done(tid, 'user', text))


def live(tmp_path):
    """Production timer: one silence auto-repeat after 6 s (settings.DEFAULTS)."""
    return Session(tmp_path, repeat_seconds=6.0, max_auto_repeats=1)


TEA_Q = 'Как правильно заварить зеленый чай'
TEA = ' Обычно берут воду примерно 80 градусов, то есть не кипяток. Настаивают две-три минуты, иначе чай горчит.'


def test_w1_10_a_natural_stop_pauses_and_the_silence_timer_leaves_the_paused_answer_alone(tmp_path):
    s = live(tmp_path)
    s.ask(TEA_Q, tid='u1')
    stream(s, 'a1', TEA, 0.05, 2.0)
    s.until(2.5)
    first = s.state()['chunks'][0]
    user(s, 'u2', ' Стой, подожди секунду', 3.0, 4.5)
    s.until(30.0)
    assert [text for at, text in s.cues if at >= 3.0] == [], s.cues
    assert s.state().get('paused') and s.state()['chunks'][0] == first


def test_w1_10_a_natural_repeat_request_says_the_waiting_portion_once(tmp_path):
    s = live(tmp_path)
    s.ask(TEA_Q, tid='u1')
    stream(s, 'a1', TEA, 0.05, 2.0)
    s.until(2.5)
    waiting = s.state()['chunks'][s.state()['chunk_index']]
    user(s, 'u2', ' Скажи-ка последнюю часть заново', 3.0, 4.5)
    s.until(5.5)
    assert [text for at, text in s.cues if at >= 3.0] == [waiting], s.cues


@pytest.mark.parametrize('said', [' Ладно, поехали дальше', ' Идём дальше'])
def test_w1_10_w1_11_a_natural_next_moves_one_portion_forward(tmp_path, said):
    s = live(tmp_path)
    s.ask(TEA_Q, tid='u1')
    stream(s, 'a1', TEA, 0.05, 2.0)
    s.until(2.5)
    chunks, index = s.state()['chunks'], s.state()['chunk_index']
    user(s, 'u2', said, 3.0, 4.5)
    s.until(5.5)
    assert [text for at, text in s.cues if at >= 3.0] == [chunks[index + 1]], s.cues
    assert s.state()['chunk_index'] == index + 1


def test_w1_07_an_objection_retires_the_waiting_portion_and_it_is_never_said_again(tmp_path):
    s = live(tmp_path)
    s.ask('А на сфере сумма углов треугольника тоже сто восемьдесят?', tid='u1')
    stream(s, 'a1', ' Да, на сфере сумма углов треугольника больше 180 градусов и зависит от площади.', 0.05, 2.5)
    s.until(3.0)
    stale = s.state()['chunks'][0]
    user(s, 'u2', ' Нет, и это невер но', 4.0, 5.5)
    s.until(5.6)
    assert s.c.question_id == 'u2' and s.c.question_text.startswith('Нет, и это'), 'the objection is the question now'
    s.until(16.0)
    assert stale not in [text for at, text in s.cues if at >= 4.0], s.cues


def test_w1_12_a_connection_check_starts_nothing_not_even_an_automatic_repeat(tmp_path):
    s = live(tmp_path)
    s.ask('Расскажи про самые глубокие озера в мире', tid='u1')
    stream(s, 'a1', ' Самое глубокое — это Байкал в России, примерно 1642 метра глубины.', 0.05, 2.5)
    s.until(3.0)
    user(s, 'u3', ' Слушай, ты меня хорошо слышишь', 4.0, 6.0)
    stream(s, 'a3', ' Да, слышу тебя отлично.', 6.05, 8.0)
    s.until(16.0)
    assert [text for at, text in s.cues if at >= 4.0] == [], s.cues
    assert s.state().get('chunk_index') == 0


def test_w1_12_a_position_question_says_the_waiting_portion_again_and_nothing_of_the_cloud(tmp_path):
    s = live(tmp_path)
    s.ask('Расскажи про самые глубокие озера в мире', tid='u1')
    stream(s, 'a1', ' Самое глубокое — это Байкал в России, примерно 1642 метра глубины.', 0.05, 2.5)
    s.until(3.0)
    waiting = s.state()['chunks'][0]
    user(s, 'u2', ' А что было последним? Скажи ещё раз.', 4.0, 5.5)
    stream(s, 'a2', ' Если по глубине — последним я назвал Байкал.', 5.55, 7.0)
    s.until(8.0)
    assert [text for at, text in s.cues if at >= 4.0] == [waiting], s.cues
    assert s.state().get('question') == 'Расскажи про самые глубокие озера в мире'


def test_w1_08_a_return_with_a_position_question_restores_the_unfinished_answer(tmp_path):
    s = live(tmp_path)
    s.ask(TSUNAMI_Q, tid='u1')
    stream(s, 'a1', ' Цунами чаще всего начинается с внезапного смещения морского дна — например, при землетрясении.', 0.05, 2.0)
    user(s, 'u2', ' Цунами чаще всего начинается', 3.5, 4.0)             # F1: the listener repeats the first cue (was «Цунами чаще»)
    user(s, 'u3', ' Ещё одно: как называется самая маленькая птица в мире', 6.0, 7.5)
    stream(s, 'a2', ' Самая маленькая птица в мире — это колибри-пчёлка.', 7.55, 8.5)
    s.until(9.5)
    user(s, 'u9', ' Ладно, возвращаемся к цунами, где мы там прервались', 10.0, 11.5)
    stream(s, 'a9', ' Я говорил, что цунами чаще всего начинается со смещения морского дна.', 11.55, 13.0)
    s.until(14.0)
    after = [text for at, text in s.cues if at >= 10.0]
    assert after and after[0] == 'с внезапного смещения морского дна — например, при землетрясении.', after      # F1: the next meaning portion
    assert s.state().get('question') == TSUNAMI_Q


def test_w1_08_a_question_after_a_topic_frame_is_answered(tmp_path):
    s = live(tmp_path)
    s.ask(TSUNAMI_Q, tid='u1')
    stream(s, 'a1', ' Цунами чаще всего начинается с внезапного смещения морского дна.', 0.05, 2.0)
    s.until(3.0)
    user(s, 'u5', ' А про гитару ещё раз, сколько там струн', 4.0, 6.0)
    stream(s, 'a5', ' Шесть струн.', 6.05, 7.2)
    s.until(14.0)
    assert [text for at, text in s.cues if at >= 4.0][:1] == ['Шесть струн.'], s.cues


def test_w1_09_a_barge_in_request_after_a_preamble_retires_the_stale_answer(tmp_path):
    s = live(tmp_path)
    s.ask('Объясни, как работает компас', tid='u1')
    stream(s, 'a1', ' Внутри компаса есть намагниченная стрелка, которая свободно вращается.', 0.05, 2.0)
    s.until(3.0)
    user(s, 'u2', ' Подожди, лучше скажи другое, сколько рук у осьмин ога', 4.0, 6.0)
    stream(s, 'a2', ' У осьминога восемь рук.', 6.05, 7.0)
    s.until(14.0)
    after = [text for at, text in s.cues if at >= 4.0]
    assert not [text for text in after if 'компас' in text.lower()], after
    assert s.c.question_id == 'u2'


@pytest.mark.parametrize('heard,plan', [(None, 'next'), ('reopened', 'present'), ('unheard', 'present'), ('sounded', 'presented')])
def test_next_said_before_the_portion_was_heard_is_the_engines_one_verdict(heard, plan):
    """portion-B (cm-going-on): what «дальше» does with what the listener has heard is ``going_on(heard=)`` of the engine; the controller hands over the fact (``ControlledMedia._heard_after``) and decides nothing."""
    waits = H.waiting('Самое глубокое — это Байкал', 'в России.')
    d = analyze('дальше', waits, [], PROD)
    assert d.kind == NEXT
    assert going_on(waits, d, now=1.0, window_s=600, heard=heard) == (plan, None)


def test_a_new_call_keeps_or_retires_the_plan_by_the_engines_one_rule():
    """portion-B (new-call-plan): what a new call does with the answer an earlier call left is ``engine.new_call_plan`` (not four gates of the controller): a fresh waiting portion stays (a redial), a stale one or a question never answered is retired, a fresh finished answer is left."""
    from echo_sync.engine import CONVERSATION_GAP_S, new_call_plan
    now = 10_000.0
    fresh, stale = {'issued_at': now - 5}, {'issued_at': now - CONVERSATION_GAP_S - 5}
    assert new_call_plan(fresh, now=now, waiting=True) == (False, 'keep')
    assert new_call_plan(stale, now=now, waiting=True) == (True, 'close')
    assert new_call_plan(dict(fresh, pending_turn='t'), now=now, waiting=True) == (False, 'close')
    assert new_call_plan(fresh, now=now, waiting=False) == (False, None)
    assert new_call_plan(stale, now=now, waiting=False) == (True, None)
    assert new_call_plan({}, now=now, waiting=True) == (False, None)
