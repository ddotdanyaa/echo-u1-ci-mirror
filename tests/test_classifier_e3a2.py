"""Task E3a-rest (WAVE 2): rulings 3, 4 and 5 of the coordinator (T-A findings DEF-T-04, DEF-T-03, DEF-T-06). Rulings 1 and 2 are in
tests/test_classifier_e3a.py.

Every case goes through the real ``analyze`` with the production profile (on_mismatch=silent) and, where the classic
profiles must agree, with those. The dispatch tests drive the real ControlledMedia, built as the host builds it (``helpers_s6_ack.Dictation``),
so they show what the listener would hear: the waiting portion retired, or left alone.

  3. «Нет, я про X, а не Y» retires the wrong answer and makes X the question                    DEF-T-04
  4. «Не понял это слово» asks for the term to be explained, it is not a replay                  DEF-T-03
  5. a statement that merely contains a modal word is not a question                             DEF-T-06
"""
import pytest

import helpers_s6_ack as H
from echo_sync.classifier import ACK, CLARIFY_REPAIR, CORRECTION, QUESTION, QUIET, REPEAT, REPLAY, STOP, analyze
from echo_sync.engine import EchoEngine
from engine_say import engine_reply

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


def ids(values):
    return [f'{i:02d}' for i in range(len(values))]


# =====================================================================================================================================
# 5. A statement that merely contains a modal word (DEF-T-06)
# =====================================================================================================================================

MODAL_STATEMENTS = (
    'Нужно остановить платёж по счёту.', 'Повторить опыт можно через неделю.',                  # the two statements of the T-A finding
    'Надо подумать над этим вопросом', 'Верно, это было вчера вечером', 'Правда, я этого не помню', 'Стоит подождать до вечера',
    'Можешь не торопиться с ответом', 'Можете не волноваться за результат', 'Нужно ещё немного времени', 'Надо ещё подумать',
    'Дело решено, можно идти домой', 'Для этого нужно три свидетеля', 'Это верно только для воды', 'Правда жизни в том, что все устали',
    'Ну нужно остановить платёж по счёту',                                                      # fillers in front do not make it a request
    # fix round 1 (coordinator): a request verb followed by «что» is a statement
    'Можно сказать, что он прав.', 'Можно сказать что он прав', 'Можешь сказать, что это неправда', 'Можно идти домой', 'Можно подождать до вечера',
    # fix round 2 (coordinator): an obligation modal followed by a verb phrase about the world, or by an object word and more than two words
    'Нужно повторить опыт через неделю.', 'Надо повторить опыт через неделю', 'Необходимо рассказать подробнее', 'Нужно объяснить разницу между весом и массой',
    'Нужно уточнить условия договора с поставщиком', 'Нужно подробнее про налоги на прибыль', 'Нужно ещё раз проверить все расчёты',
)


@pytest.mark.parametrize('profile', PROFILES)
@pytest.mark.parametrize('state', STATES)
@pytest.mark.parametrize('text', MODAL_STATEMENTS, ids=ids(MODAL_STATEMENTS))
def test_a_statement_that_merely_contains_a_modal_word_is_not_a_question(text, state, profile):
    """DEF-T-06: «Нужно остановить платёж по счёту.» / «Повторить опыт можно через неделю.» leave a waiting answer alone (and start nothing)."""
    d = decide(text, STATES[state], PROFILES[profile])
    assert d.kind not in (QUESTION, CORRECTION, STOP), (text, d)


@pytest.mark.parametrize('text', MODAL_STATEMENTS, ids=ids(MODAL_STATEMENTS))
def test_a_modal_statement_leaves_the_waiting_answer_silent_in_the_production_profile(text):
    assert decide(text).kind == QUIET, text


MODAL_QUESTIONS_WITH_A_MARK = (
    'Нужно остановить платёж по счёту?', 'Повторить опыт можно через неделю?', 'Можно остановить платёж?', 'Надо подумать?',
    'Стоит подождать до вечера?', 'Верно это было вчера?', 'Правда я этого не помню?',
    'Нужно ли остановить платёж по счёту', 'Можно ли повторить опыт через неделю', 'Стоит ли подождать до вечера', 'Надо ли подумать',
    'Верно ли это', 'Правда ли что вода кипит при ста градусах',
)


@pytest.mark.parametrize('state', STATES)
@pytest.mark.parametrize('text', MODAL_QUESTIONS_WITH_A_MARK, ids=ids(MODAL_QUESTIONS_WITH_A_MARK))
def test_a_modal_word_with_a_question_mark_or_with_li_is_still_a_question(text, state):
    """(a) the trailing «?» and (b) the particle «ли» keep making it a question."""
    assert decide(text, STATES[state]).kind == QUESTION, text


MODAL_REQUESTS = (
    'Можешь объяснить', 'Можете рассказать подробнее', 'Можешь пояснить', 'Можешь объяснить проще', 'Можно объяснить', 'Можете пожалуйста рассказать',
    'Можешь объяснить проще и короче',
    'Ну можешь объяснить', 'А можете рассказать подробнее',                                       # (c): after the fillers the modal is first
    # fix round 1: the examples of the recall regression (live finals often lack «?»)
    'Можно узнать про налоги', 'Можешь сказать цену', 'Можешь показать пример', 'Можно спросить', 'Можно вопрос', 'Можешь подсказать',
    'Можешь объяснить разницу между весом и массой',                                              # 7 words
    'Можно ещё чаю', 'Можно услышать подробнее', 'Можешь привести пример', 'Можешь назвать столицу', 'Можешь перечислить причины',
    'Можешь описать процесс', 'Можешь сравнить два метода', 'Можешь дать определение', 'Можете помочь с налогами', 'Можно мне вопрос',
    'Могли бы вы объяснить', 'Не могли бы вы рассказать подробнее', 'Мог бы ты пояснить', 'Не мог бы ты уточнить',
    'Можешь объяснить мне разницу между весом и массой простыми словами',                         # 10 words
    'Не могли бы вы рассказать мне про принцип работы насоса',                                      # 10 words
)


@pytest.mark.parametrize('profile', PROFILES)
@pytest.mark.parametrize('state', STATES)
@pytest.mark.parametrize('text', MODAL_REQUESTS, ids=ids(MODAL_REQUESTS))
def test_a_modal_of_permission_first_with_a_request_verb_is_a_question_even_while_a_portion_waits(text, state, profile):
    """(c), fix round 1: the utterance starts with можно / можешь / можете / могли бы …, has at most ten words and a request verb or word follows."""
    d = decide(text, STATES[state], PROFILES[profile])
    assert d.kind == QUESTION, (text, d)


def test_a_modal_request_is_passed_on_as_it_was_said_without_the_fillers():
    assert decide('Ну можешь объяснить').question == 'можешь объяснить'
    assert decide('Можете рассказать подробнее').question == 'Можете рассказать подробнее'
    assert decide('Можно узнать про налоги').question == 'Можно узнать про налоги'


def test_a_request_longer_than_ten_words_is_a_statement():
    assert decide('Можешь объяснить мне разницу между весом и массой простыми словами пожалуйста').kind == QUIET
    assert decide('Можешь объяснить мне разницу между весом и массой простыми словами').kind == QUESTION


OBLIGATION_STATEMENTS = ('Нужно повторить опыт через неделю', 'Надо повторить опыт через неделю', 'Необходимо рассказать подробнее', 'Стоит подождать до вечера',
                         'Нужно уточнить условия договора с поставщиком', 'Следует сообщить об этом в налоговую', 'Надо ещё подумать', 'Нужно ещё немного времени')


@pytest.mark.parametrize('state', STATES)
@pytest.mark.parametrize('text', OBLIGATION_STATEMENTS)
def test_an_obligation_modal_before_a_verb_phrase_asks_only_with_a_question_mark_or_with_li(text, state):
    """(b), fix rounds 1-2: нужно / надо / стоит / следует / необходимо before a verb phrase about the world are statements: «?» or «ли» make the question."""
    assert decide(text, STATES[state]).kind not in (QUESTION, CORRECTION), text
    assert decide(text + '?', STATES[state]).kind == QUESTION, text + '?'
    head, _, rest = text.partition(' ')
    assert decide(f'{head} ли {rest}', STATES[state]).kind == QUESTION, f'{head} ли {rest}'


OBLIGATION_REQUESTS = ('Нужно подробнее', 'Надо ещё пример', 'Стоит уточнить', 'Нужен пример', 'Надо проще', 'Нужно короче', 'Нужны примеры', 'Следует объяснить иначе',
                       'Необходимо пояснить', 'Нужно объяснить иначе', 'Нужно ещё раз объяснить', 'Нужно бы подробнее', 'Нужно подробнее про налоги', 'Надо повторить',
                       'Нужно ещё', 'Нужно ещё один пример', 'Нужно проще и короче',
                       'Ну нужно подробнее', 'А надо ещё пример')                                # after the fillers the modal is first


@pytest.mark.parametrize('profile', PROFILES)
@pytest.mark.parametrize('state', STATES)
@pytest.mark.parametrize('text', OBLIGATION_REQUESTS, ids=ids(OBLIGATION_REQUESTS))
def test_an_obligation_modal_directly_before_a_request_object_is_a_question_even_while_a_portion_waits(text, state, profile):
    """Fix round 2: «Нужно подробнее», «Надо ещё пример», «Стоит уточнить», «Нужен пример», «Надо проще», «Нужно короче» are requests (the interlocutor asks for them)."""
    d = decide(text, STATES[state], PROFILES[profile])
    assert d.kind == QUESTION and d.reason == 'modal_request', (text, d)


def test_an_obligation_request_is_passed_on_as_it_was_said_without_the_fillers():
    assert decide('Нужно подробнее').question == 'Нужно подробнее'
    assert decide('Ну нужно подробнее').question == 'нужно подробнее'
    assert decide('А надо ещё пример').question == 'надо ещё пример'


@pytest.mark.parametrize('state', STATES)
@pytest.mark.parametrize('text', ['Можно сказать, что он прав.', 'Можно сказать что он прав', 'Можешь сказать, что это неправда'])
def test_a_request_verb_followed_by_that_is_a_statement_not_a_question_word(state, text):
    """(b), fix round 1: the «что» after the verb is the conjunction; it is not the question word of the first three words."""
    d = decide(text, STATES[state])
    assert d.kind not in (QUESTION, CORRECTION), (text, d)
    assert decide(text.rstrip('.') + '?', STATES[state]).kind == QUESTION


@pytest.mark.parametrize('state', STATES)
@pytest.mark.parametrize('text', ['Можешь сказать, что такое налог', 'Можешь объяснить, что значит энтропия', 'Можете пояснить что такое инерция',
                                  'Не могли бы вы сказать, что такое налог'])
def test_a_definition_request_with_what_stays_a_request_without_a_question_mark(state, text):
    """My reading of (b): «объяснить, что такое X» is no «сказать, что он прав»; without it the literal rule would silence a request that master heard."""
    assert decide(text, STATES[state]).kind == QUESTION, text


def test_a_modal_word_later_in_the_utterance_does_not_ask_with_a_request_object_after_it():
    assert decide('Объяснить можно проще').kind == QUIET
    assert decide('Здесь можно объяснить иначе').kind == QUIET


def test_the_other_question_words_still_ask_next_to_a_modal_word():
    for text in ('Как можно объяснить проще', 'Почему нужно платить налоги', 'Нужно знать как работает насос', 'Что можно сделать',
                 'Можно пример', 'Можно ещё раз пример', 'Расскажи подробнее'):
        d = decide(text)
        assert d.kind == QUESTION and d.question == text, (text, d)


def test_a_repeat_request_with_a_modal_word_stays_a_repeat_request():
    for text in ('можешь повторить', 'Можете повторить, пожалуйста', 'можно ещё раз', 'давай ещё раз'):
        assert decide(text).kind == REPEAT, text


@pytest.mark.parametrize('text', MODAL_STATEMENTS[:6] + ('Можно сказать, что он прав.', 'Надо повторить опыт через неделю', 'Нужно повторить опыт через неделю.'))
def test_dispatch_a_modal_statement_leaves_the_waiting_portion_alone_and_speaks_nothing(tmp_path, text):
    d = fresh(tmp_path)
    out = d.say(text)
    assert not out.destroyed and out.after == out.before and out.model_calls == 0 and out.speaks == [], (text, out.types, out.speaks)


@pytest.mark.parametrize('text', ['Можешь объяснить', 'Можно узнать про налоги', 'Можешь сказать цену', 'Нужно подробнее', 'Нужен пример',
                                  'Нужно остановить платёж по счёту?'])
def test_dispatch_a_modal_request_retires_the_waiting_portion_and_starts_an_answer(tmp_path, text):
    d = fresh(tmp_path)
    out = d.say(text)
    assert out.types[0] == 'cancel' and out.types[1] in ('route', 'lookup'), (text, out.types)
    assert out.speaks == [], 'the old portion must not be spoken again'
    assert d.controller.question_text == text


# =====================================================================================================================================
# 4. A word that is not understood (DEF-T-03)
# =====================================================================================================================================

TERM_PORTION = 'Гидравлический удар возникает'                 # its longest content word: «Гидравлический» (asked about in lower case, fix round 1)
TERM_WAITING = H.waiting(TERM_PORTION, 'при резком закрытии')
TERM_STATES = {'waiting': TERM_WAITING, 'completed': dict(TERM_WAITING, completed=True),
               'pending': dict(TERM_WAITING, completed=True, pending_turn='t1'), 'idle': None}

UNNAMED_WORD = (
    'Не понял это слово.', 'Не поняла этого слова', 'Я не понял это слово', 'Не понимаю это слово', 'Не знаю этого слова',
    'Это слово мне незнакомо.', 'Это слово мне непонятно', 'Слово мне незнакомо', 'Мне незнакомо это слово',
    'Непонятно слово', 'Мне непонятно слово', 'Непонятно это слово', 'Что это за слово?', 'Что за слово', 'Что это за слово такое?',
    'Ну не понял это слово', 'А что это за слово?', 'Эм, это слово мне незнакомо',
)


@pytest.mark.parametrize('profile', PROFILES)
@pytest.mark.parametrize('text', UNNAMED_WORD, ids=ids(UNNAMED_WORD))
def test_a_word_not_understood_while_a_portion_waits_asks_what_the_longest_word_of_the_portion_means(text, profile):
    """DEF-T-03: not a replay of the same portion: a question «Что значит «T»?», T = the longest content word of the waiting portion."""
    d = decide(text, TERM_WAITING, PROFILES[profile])
    assert (d.kind, d.reason, d.question) == (QUESTION, 'term_explanation_request', 'Что значит «гидравлический»?'), (text, d)


NAMED_WORD = (
    ('Непонятно слово энтропия.', 'энтропия'), ('Мне непонятно слово сублимация', 'сублимация'), ('Слово инерция мне незнакомо', 'инерция'),
    ('Мне незнакомо слово адиабата', 'адиабата'), ('Непонятно слово гидравлический удар', 'гидравлический удар'),
    ('Ну непонятно слово Энтропия', 'энтропия'),                       # fix round 1: lower case, whatever the recogniser made of the capital
    ('Непонятно слово Гидравлический Удар', 'гидравлический удар'),
    ('Непонятно слово интернет-магазин', 'интернет-магазин'), ('Непонятно слово Интернет-Магазин', 'интернет-магазин'),
    ('Непонятно слово удар', 'удар'),                                  # a word of the portion, not its longest
    ('Непонятно слово это', 'гидравлический'),                         # «это» names nothing: the portion's longest word
    # an all-caps abbreviation stays as it is
    ('Непонятно слово ВВП', 'ВВП'), ('Непонятно слово НАТО', 'НАТО'), ('Мне незнакомо слово ЭКГ', 'ЭКГ'), ('Слово ГОСТ мне незнакомо', 'ГОСТ'),
    ('Непонятно слово ГОСТ-Р', 'ГОСТ-Р'), ('Непонятно слово ЭКГ и ЭЭГ', 'ЭКГ и ЭЭГ'),
    ('Непонятно слово Профнастил', 'профнастил'), ('Непонятно слово ПрофНастил', 'профнастил'),     # a capital inside a word is no abbreviation
)


@pytest.mark.parametrize('profile', PROFILES)
@pytest.mark.parametrize('text,named', NAMED_WORD, ids=ids(NAMED_WORD))
def test_a_named_word_that_is_not_understood_asks_what_that_word_means(text, named, profile):
    d = decide(text, TERM_WAITING, PROFILES[profile])
    assert (d.kind, d.reason, d.question) == (QUESTION, 'term_explanation_request', f'Что значит «{named}»?'), (text, d)


@pytest.mark.parametrize('portion,longest', [
    ('Наклон земной оси', 'наклон'),                                        # a tie: the first of the longest (lower case: fix round 1)
    ('Ёмкость конденсатора', 'конденсатора'),
    ('Электроёмкость проводника', 'электроёмкость'),                       # ё kept
    ('ОСАГО нужно', 'ОСАГО'), ('СНИЛС и ИНН', 'СНИЛС'),                    # an all-caps abbreviation stays as it is
    ('В 1939 году', 'году'),                                               # a number is no word to explain
    ('Это очень важный интернет-магазин', 'интернет-магазин'),             # a hyphenated compound is one word
    ('Да, это самая простая модель', 'простая'),
])
def test_the_word_asked_about_is_the_longest_content_word_of_the_waiting_portion(portion, longest):
    d = decide('Не понял это слово', H.waiting(portion, 'и так далее'))
    assert (d.kind, d.question) == (QUESTION, f'Что значит «{longest}»?'), (portion, d)


@pytest.mark.parametrize('portion', ['Да, это так.', 'Он и она', '1939', 'А потом'])
def test_a_portion_without_a_content_word_has_no_word_to_explain(portion):
    waiting = H.waiting(portion, 'и так далее')
    assert decide('Не понял это слово', waiting).kind == QUIET
    # «Что это за слово» is then the question it always was (the word in front of it is «что»): as it was said
    d = decide('Что это за слово', waiting)
    assert (d.kind, d.reason, d.question) == (QUESTION, 'question_word', 'Что это за слово'), d




# With nothing waiting the rewrite does not apply. Some of the forms are the question they always were: «что …» makes «Что за слово» a question
# ('question_word' / the question mark) and «Мне непонятно …» is the indirect request of ruling 1. They stay as they were said.
ASKS_ANYWAY = {
    'Что это за слово?': ('question_mark', 'Что это за слово?'), 'Что за слово': ('question_word', 'Что за слово'),
    'Что это за слово такое?': ('question_mark', 'Что это за слово такое?'), 'А что это за слово?': ('question_mark', 'что это за слово?'),
    'Мне непонятно слово': ('indirect_request', 'Мне непонятно слово'), 'Мне непонятно это слово': ('indirect_request', 'Мне непонятно это слово'),
    'Мне непонятно слово сублимация': ('indirect_request', 'Мне непонятно слово сублимация'),
}


@pytest.mark.parametrize('state', ['completed', 'pending', 'idle'])
@pytest.mark.parametrize('text', [t for t in [*UNNAMED_WORD, *(t for t, _ in NAMED_WORD)] if t not in ASKS_ANYWAY])
def test_the_word_request_needs_a_portion_that_waits(text, state):
    d = decide(text, TERM_STATES[state])
    assert d.reason != 'term_explanation_request' and d.kind not in (QUESTION, CORRECTION), (text, state, d)


@pytest.mark.parametrize('state', ['completed', 'pending', 'idle'])
@pytest.mark.parametrize('text', ASKS_ANYWAY)
def test_with_nothing_waiting_the_forms_that_already_asked_are_not_rewritten(text, state):
    d = decide(text, TERM_STATES[state])
    assert (d.kind, d.reason, d.question) == (QUESTION, *ASKS_ANYWAY[text]), (text, state, d)


def test_a_portion_that_is_the_request_itself_is_confirmed_by_repeating_it():
    waiting = H.waiting('Не понял это слово', 'и так далее')
    assert decide('Не понял это слово', waiting).kind == ACK


@pytest.mark.parametrize('text', ['Не понял вопрос', 'Слово дня', 'Это слово часто встречается', 'Не понял эти слова',
                                  'Непонятно слово одно другое третье четвёртое', 'Я знаю это слово'])
def test_other_talk_about_words_stays_quiet(text):
    assert decide(text, TERM_WAITING).kind == QUIET, text


@pytest.mark.parametrize('text', ['Что такое слово?', 'Что значит это слово?', 'Какое это слово?', 'Что это за слово означает?'])
def test_a_question_of_its_own_about_a_word_is_not_rewritten(text):
    d = decide(text, TERM_WAITING)
    assert (d.kind, d.reason, d.question) == (QUESTION, 'question_mark', text), (text, d)


@pytest.mark.parametrize('text', ['Не понял', 'не расслышал', 'Что?', 'Как?', 'А?', 'ну не понял'])
def test_the_hearing_repairs_still_ask_to_hear_the_portion_again(text):
    assert decide(text, TERM_WAITING).kind == REPLAY, text


# W1F-A (brief task-w1fix-briefs.md, «a cut PENALTY in the planner»): the first portion of this fixture keeps the adjective with its
# noun - 'В Солнечной системе', it was 'В Солнечной'. F1 (wave F): the call cuts by meaning, so it is the first clause
# 'В Солнечной системе 8 планет,'. The dispatch under test is unchanged. c23-final: c22-merge (R21-04, G15 «число с оговоркой договаривается»)
# finishes a number with its qualifier in the first portion: 'В Солнечной системе 8 планет, не считая карликовых.' (c22-merge.md, item 1).
FIRST_PORTION = 'В Солнечной системе 8 планет, не считая карликовых.'


def test_dispatch_a_word_not_understood_retires_the_waiting_portion_and_asks_what_the_word_means(tmp_path):
    d = fresh(tmp_path)
    assert d.current == FIRST_PORTION
    out = d.say('Не понял это слово')
    assert out.types[0] == 'cancel' and out.types[1] in ('route', 'lookup'), out.types
    assert out.speaks == [], 'the portion must not be replayed'
    assert d.controller.question_text == 'Что значит «карликовых»?'      # c23: the longest content word of the portion (it was «солнечной» before the qualifier joined it)


def test_dispatch_a_named_word_asks_what_that_word_means(tmp_path):
    d = fresh(tmp_path)
    out = d.say('Непонятно слово планет')
    assert out.types[0] == 'cancel' and out.types[1] in ('route', 'lookup'), out.types
    assert out.speaks == []
    assert d.controller.question_text == 'Что значит «планет»?'


def test_dispatch_the_hearing_repair_is_still_a_replay(tmp_path):
    d = fresh(tmp_path)
    out = d.say('Не понял')
    assert not out.destroyed and out.speaks == [FIRST_PORTION] and out.after == out.before     # the plan, see above


# =====================================================================================================================================
# 3. A spoken correction of the topic (DEF-T-04)
# =====================================================================================================================================

CORRECTIONS = (
    # «Нет, я про X(, а не (про) Y)»
    ('Нет, я про причины, а не определение.', 'причины'), ('Нет, я про причины', 'причины'), ('Нет, я об инфляции', 'инфляции'),
    ('Нет, подождите, я про причины инфляции', 'причины инфляции'), ('Нет, я про Первую мировую войну', 'Первую мировую войну'),
    # «Нет, я спрашивал(а) (про|о) X»
    ('Нет, я спрашивал про причины.', 'причины'), ('Нет, я спрашивала о причинах', 'причинах'),
    ('Нет, я спрашивал про причины, а не про определение', 'причины'),
    # «Я спросил(а) не про Y, а про X» (and its twins «спрашивал не про Y, а про X», «Речь идёт не о Y, а о X»)
    ('Я спросил не про определение, а про причины.', 'причины'), ('Я спросила не об определении, а о причинах', 'причинах'),
    ('Я спрашивал не про определение, а про причины', 'причины'), ('Речь идёт не об определении, а о причинах', 'причинах'),
    # «Речь (идёт)? (про|о) X, а не (про|о) Y»
    ('Речь про причины, а не про определение.', 'причины'), ('Речь идёт о причинах, а не об определении.', 'причинах'),
    # «Не про Y, а про X»
    ('Не про определение, а про причины.', 'причины'), ('Нет, не про определение, а про причины', 'причины'),
    # «Тема сейчас X, а не Y»
    ('Тема сейчас причины, а не определение.', 'причины'),
    # «Я не об этом, я про X»
    ('Я не об этом, я про причины.', 'причины'), ('Не об этом, я про причины инфляции', 'причины инфляции'),
    # «про то, как …»
    ('Нет, я про то, как работает насос', 'как работает насос'), ('Нет, я о том, почему небо голубое', 'почему небо голубое'),
    # the fillers in front are not part of it
    ('Ну нет, я про причины, а не определение', 'причины'), ('Так, не про определение, а про причины', 'причины'),
)


@pytest.mark.parametrize('profile', PROFILES)
@pytest.mark.parametrize('state', ['waiting', 'completed', 'pending'])
@pytest.mark.parametrize('text,x', CORRECTIONS, ids=ids(CORRECTIONS))
def test_a_spoken_correction_of_the_topic_retires_the_answer_and_the_corrected_request_is_the_question(text, x, state, profile):
    """DEF-T-04: a CORRECTION whose question text is X: the wrong tail is retired and X is what is asked now."""
    d = decide(text, STATES[state], PROFILES[profile])
    assert (d.kind, d.reason, d.question) == (CORRECTION, 'corrected_request', x), (text, d)


@pytest.mark.parametrize('text,x', CORRECTIONS, ids=ids(CORRECTIONS))
def test_a_correction_needs_an_answer_to_correct(text, x):
    """Like «я имел в виду …»: with no answer and no question before it there is nothing to correct."""
    assert decide(text, None).kind not in (CORRECTION, QUESTION), text


@pytest.mark.parametrize('text', ['Нет, я имел в виду причины', 'Нет, подождите, я хотел спросить про причины', 'Исправь, я спрашивал про США',
                                  'Ой, нет, я хотела спросить про кита', 'Нет, это неверно, я про причины'])
def test_the_older_repair_forms_keep_the_whole_utterance_as_the_question(text):
    d = decide(text)
    assert d.kind in (CORRECTION, QUESTION) and d.question.strip() == text, (text, d)


NOT_A_CORRECTION = (
    'Нет, я про это', 'Нет, я про такое', 'Нет, я про него не слышал', 'Нет, я о нём ничего не знаю', 'Нет, я про то', 'Нет, я о том',
    'Я про причины', 'Он сказал нет я про причины', 'Мы вчера спрашивали про причины', 'Она спросила не про определение а про причины',
    'Речь идёт о налогах', 'Речь про причины', 'Тема сейчас причины', 'Не про определение', 'Нет, не про определение',
    'Не про это, а про то', 'Не масса, а скорость', 'Не рыба, а млекопитающее', 'Не знаю, а ты как', 'Это не про определение, а про причины',
    'Нет', 'Нет, я', 'Нет, я про',
)


@pytest.mark.parametrize('profile', PROFILES)
@pytest.mark.parametrize('state', ['waiting', 'completed', 'pending'])
@pytest.mark.parametrize('text', NOT_A_CORRECTION, ids=ids(NOT_A_CORRECTION))
def test_words_that_only_resemble_a_correction_of_the_topic_retire_nothing(text, state, profile):
    d = decide(text, STATES[state], PROFILES[profile])
    assert d.kind not in (CORRECTION, QUESTION, STOP), (text, d)


def test_a_correction_that_is_only_a_part_of_the_waiting_portion_is_an_attempt_not_a_correction():
    waiting = H.waiting('Не про определение, а про причины и следствия', 'дальше')
    for settings in PROFILES.values():
        assert decide('Не про определение, а про причины', waiting, settings).kind in (REPLAY, QUIET), settings
    assert decide('Не про определение, а про причины и следствия', waiting).kind == ACK


@pytest.mark.parametrize('text,x', [('Нет, я про причины, а не определение', 'причины'), ('Нет, я спрашивал про причины', 'причины'),
                                    ('Не про определение, а про причины', 'причины'), ('Речь идёт о причинах, а не об определении', 'причинах'),
                                    ('Я не об этом, я про причины', 'причины'), ('Тема сейчас причины, а не определение', 'причины'),
                                    ('Я спросил не про определение, а про причины', 'причины')])
def test_dispatch_a_correction_of_the_topic_retires_the_wrong_answer_and_asks_the_corrected_request(tmp_path, text, x):
    d = fresh(tmp_path)
    out = d.say(text)
    assert out.types[0] == 'cancel' and out.types[1] in ('route', 'lookup'), (text, out.types)
    assert out.speaks == [], 'the wrong answer must not be spoken again'
    assert d.controller.question_text == x


@pytest.mark.parametrize('text,x', [('Нет, я про причины, а не определение', 'причины'), ('Нет, я спрашивал про причины', 'причины'),
                                    ('Речь идёт о причинах, а не об определении', 'причинах'), ('Я спросил не про определение, а про причины', 'причины')])
def test_dispatch_the_answer_to_a_corrected_request_is_dictated_and_x_is_what_was_asked(tmp_path, text, x):
    """INTEG7 (T-A C04: after «Нет, я спрашивал про причины.» the listener heard nothing). The model is asked the corrected request X, but
    the engine classifies again the text it is given when the answer is published: «причины» alone is no question (not_a_question), and the
    answer was dropped. The engine is given what the listener said, and X is what it records as asked."""
    d = fresh(tmp_path)
    d.say(text)
    out = d.deliver(H.done('a2', 'assistant', 'Причины в том, что наклон оси меняет угол падения солнечных лучей.'))
    assert out.speaks, (text, out.types)
    assert d.state['question'] == x and 'Причины' in d.state['answer'], d.state


@pytest.mark.parametrize('text', ['Нет, я про это', 'Нет, я про него не слышал', 'Речь идёт о налогах', 'Не про это, а про то'])
def test_dispatch_words_that_only_resemble_a_correction_leave_the_waiting_portion_alone(tmp_path, text):
    d = fresh(tmp_path)
    out = d.say(text)
    assert not out.destroyed and out.after == out.before and out.model_calls == 0 and out.speaks == [], (text, out.types, out.speaks)


def test_the_engine_answers_the_corrected_request_and_keeps_the_history(tmp_path):
    calls = []

    def generate(question, history, *args):
        calls.append((question, list(history)))
        return 'Инфляция — это рост цен.' if len(calls) == 1 else 'Причины инфляции перечислены в исправленном ответе.'

    engine = EchoEngine(tmp_path / 'state.db', generate)
    engine_reply(engine, session_id='s', turn_id='q', text='Что такое инфляция?', request={}, model='offline')
    before = engine.state('s')
    engine_reply(engine, session_id='s', turn_id='fix', text='Нет, я про причины, а не определение', request={}, model='offline')
    after = engine.state('s')
    assert [question for question, _ in calls] == ['Что такое инфляция?', 'причины']
    # CL2's conversation map adds delivery facts (at, chunks, spoken, status) to each entry and updates them on retire: compare the exchange.
    exchange = lambda rows: [(row.get('question'), row.get('answer')) for row in rows]
    assert exchange(calls[-1][1]) == exchange(before['history']), 'the exchange before stays in the history'
    assert after['revision'] == before['revision'] + 1 and after['question'] == 'причины' and after['chunk_index'] == 0
    assert 'Причины' in after['answer'], 'the old answer is gone'
