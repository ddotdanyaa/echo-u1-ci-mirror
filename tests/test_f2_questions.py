"""Wave F / F2 (3 Nov): questions that got silence, and remarks to the prompter that got answered, in the owner's REAL call 09:55.

Evidence: .superpowers/sdd/wave2/owner-call-0955-timeline.txt (call abcc139fe874). Every utterance quoted under «the call» below is a user
final as that call logged it; on 9062f3b it was decided as the comment says. The rules (task-f-briefs.md, F2):

1. nothing waits: a TOPIC PHRASE is a question - the utterance (or its last sentence), after lead particles and fillers, is a noun phrase
   (pymorphy3: a content noun head, no finite verb, at most 8 words); the question passed on is that phrase;
2. several sentences in one final: chat before the question is dropped (the last question run; an explicit «Вопрос …» starts it);
3. an indirect question inside a request or a complaint («… тебе нужно сказать, что такое X») is the question «что такое X»;
4. a remark to the prompter about its own work (addressed to it, with a verb of answering / prompting: a small lemma set read by
   pymorphy3) is no question: QUIET, reason ``remark_to_prompter``; commands keep their meaning and rule 3 wins;
5. the answer policy (v2.3) says a named article, term or topic is a «что это» question answered briefly.

Every rule is shown on NEW wordings written for this file (not the call's sentences only), and the negative controls say what must
stay as it is: a noun phrase while a portion waits, greetings, thanks, reported speech, real questions that use «ты».
"""
import re

import pytest

import helpers_s6_ack as H
from echo_sync import content_policy
from echo_sync.classifier import CORRECTION, GREETING, QUESTION, QUIET, REPEAT, STOP, analyze
from echo_sync.content_policy import ANSWER_POLICY
from echo_sync.textutil import norm_words

PROD = H.PROD_SETTINGS
CLASSIC = {'ack_match': 'stem'}
PROFILES = {'prod': PROD, 'classic': CLASSIC}

# The states an utterance meets. RETIRED is what the controlled route leaves after a question retired the answer (engine.retire): the
# engine classifies the question text again in that state when the answer is published, so a question must be one there as well.
RETIRED = {'schema': 2, 'revision': 26, 'question': 'Когда было крещение Руси?', 'answer': '', 'chunks': [], 'chunk_index': 0,
           'completed': True, 'pending_turn': None,
           'history': [{'question': 'Когда было крещение Руси?', 'answer': 'Крещение Руси традиционно относят к 988 году.'}]}
DONE = {'schema': 2, 'revision': 5, 'question': 'Когда было крещение Руси?', 'answer': 'Крещение Руси традиционно относят к 988 году.',
        'chunks': ['Крещение Руси', 'традиционно относят к 988 году.'], 'chunk_index': 2, 'completed': True, 'pending_turn': None,
        'history': []}
NOTHING_WAITS = {'idle': None, 'retired': RETIRED, 'done': DONE}
WAITING = H.waiting('Согласен, стоило', 'сразу начать с 988 года.')


def decide(text, state=None, settings=PROD):
    return analyze(text, state, [], settings)


def ids(values):
    return [f'{i:02d}' for i in range(len(values))]


def republished(decision):
    """What the engine decides when the answer is published: it classifies the QUESTION TEXT again, after the retire (INTEG7 lesson)."""
    return analyze(decision.question, RETIRED, [], PROD)


# =====================================================================================================================================
# 0. The call (9062f3b decisions in the comments)
# =====================================================================================================================================

CALL_TOPIC = 'ну хоть девятая статья налогового кодекса'                                        # silent / not_a_question
CALL_CHAT_THEN_TOPIC = 'Ну и короче я готов. А какой вопрос? Вопрос получается 21-ая статья налогового кодекса'  # silent (stale portion)
CALL_COMPLAINT = ('Блядь, ты ещё и не отвечаешь, когда я тебе говорю, что это, тебе нужно обязательно сказать, что такое девятая статья '
                  'налогового кодекса')                                                          # silent / not_a_question
CALL_REMARKS = (
    'Зачем вот это вот всё тянуть надо было',                                                  # question / question_word -> «Согласен, стоило»
    'Ну это как очень поздно в итоге сказал, типа 988 года, ты должен был первым ответом мне это сказать',   # question / question_word
    'почему нельзя настроить как-то, чтобы ты прям мгновенно отвечал, суфлировал, когда я слова говорю, ты же полный ответ можешь '
    'уже сформулировать и держать его, и просто смотреть по токенам, по звукам, что обратно приходит в транскрибации '
    'расшифровывается, это же занимает ну по 70 миллисекунд, это же быстро',                    # question -> lookup refused -> «Ошибка»
    'Всё, ты сломался вообще',                                                                 # silent / not_a_question
    'Короче всё, ты ничего отвечать больше не будешь, да? Ты молчишь',                         # silent / not_a_question
)
# «по два слова» names a number: fix round 1, ruling 3 - a clause that names something is never a remark. It stays silent (no question).
CALL_SILENT = 'И ты можешь подсказывать мне по два слова, потому что ты по два слова подсказыва ешь, ну типа это палится'


@pytest.mark.parametrize('state', NOTHING_WAITS)
def test_the_call_a_named_article_after_lead_particles_is_a_question(state):
    d = decide(CALL_TOPIC, NOTHING_WAITS[state])
    assert (d.kind, d.reason, d.question) == (QUESTION, 'topic_phrase', 'девятая статья налогового кодекса'), d


@pytest.mark.parametrize('state', ['retired', 'waiting'])
def test_the_call_the_chat_before_an_explicit_question_is_dropped(state):
    """The call met a portion left waiting by an earlier call (F3 retires it at call open); the explicit «Вопрос …» asks in both states."""
    d = decide(CALL_CHAT_THEN_TOPIC, RETIRED if state == 'retired' else WAITING)
    assert d.kind == QUESTION and d.question == '21-ая статья налогового кодекса', d


@pytest.mark.parametrize('state', ['retired', 'waiting'])
def test_the_call_the_indirect_question_inside_a_complaint_is_asked(state):
    d = decide(CALL_COMPLAINT, RETIRED if state == 'retired' else WAITING)
    assert (d.kind, d.reason, d.question) == (QUESTION, 'indirect_question', 'что такое девятая статья налогового кодекса'), d


@pytest.mark.parametrize('state', ['retired', 'waiting', 'idle'])
@pytest.mark.parametrize('text', CALL_REMARKS, ids=ids(CALL_REMARKS))
def test_the_call_remarks_to_the_prompter_are_quiet_and_never_retire_a_waiting_answer(text, state):
    d = decide(text, {'retired': RETIRED, 'waiting': WAITING, 'idle': None}[state])
    assert (d.kind, d.reason) == (QUIET, 'remark_to_prompter'), (text, d)


@pytest.mark.parametrize('state', ['retired', 'waiting', 'idle'])
def test_the_call_remark_about_two_words_asks_nothing(state):
    d = decide(CALL_SILENT, {'retired': RETIRED, 'waiting': WAITING, 'idle': None}[state])
    assert d.kind not in (QUESTION, CORRECTION), d


@pytest.mark.parametrize('text,question', [
    ('21-ая статья налогового кодекса. Что такое', '21-ая статья налогового кодекса. Что такое'),
    ('Так, ну ладно, Тогда может, Что такое или нет? Когда было крещение Руси', None),
    ('. Так, значит в чём заключается смысл экономики плановой', 'значит в чём заключается смысл экономики плановой'),
])
def test_the_call_questions_that_were_answered_stay_questions(text, question):
    d = decide(text, WAITING)
    assert d.kind == QUESTION, d
    if question:
        assert d.question == question, d


# =====================================================================================================================================
# 1. A topic phrase while nothing waits is a question (NEW wordings)
# =====================================================================================================================================

TOPICS = (
    ('Ну, теорема Пифагора', 'теорема Пифагора'),
    ('Хотя бы закон Ома', 'закон Ома'),
    ('А тогда статья 228 Уголовного кодекса', 'статья 228 Уголовного кодекса'),
    ('Так, значит, принцип работы холодильника', 'принцип работы холодильника'),
    ('Вот, причины Первой мировой войны', 'причины Первой мировой войны'),
    ('Значит, третий закон Ньютона', 'третий закон Ньютона'),
    ('Инфляция', 'Инфляция'),
    ('Ну, денежно-кредитная политика Центрального банка', 'денежно-кредитная политика Центрального банка'),
    ('А теперь эффект Доплера', 'эффект Доплера'),
    ('Тогда период полураспада урана', 'период полураспада урана'),
    ('Ну, строение клетки', 'строение клетки'),
    ('Хоть правило буравчика', 'правило буравчика'),
    ('Так, состав крови человека', 'состав крови человека'),
    ('Ну вот, круговорот воды в природе', 'круговорот воды в природе'),
    ('Хоть бы теорию относительности', 'теорию относительности'),
    ('Короче, смысл плановой экономики', 'смысл плановой экономики'),
    ('Ну хоть статья 145 НК РФ', 'статья 145 НК РФ'),
    ('Типа, фотосинтез', 'фотосинтез'),
)


@pytest.mark.parametrize('state', NOTHING_WAITS)
@pytest.mark.parametrize('text,phrase', TOPICS, ids=ids(TOPICS))
def test_a_topic_phrase_is_a_question_when_nothing_waits_and_the_phrase_is_what_is_asked(text, phrase, state):
    d = decide(text, NOTHING_WAITS[state])
    assert d.kind == QUESTION and d.question == phrase, (text, d)
    assert republished(d).kind == QUESTION, (text, republished(d))


NOT_TOPICS = (
    'Ну и короче я готов',                        # a pronoun and a predicate
    'Непонятно',                                  # an adverb
    'Мне сказали, девятая статья налогового кодекса',   # reported speech
    'Учитель говорил про девятую статью налогового кодекса',
    'Погода сегодня хорошая',                     # a statement
    'Вода мокрая',                                # a predicate adjective after the noun
    'Хороший вопрос',                             # «вопрос» names no topic
    'Ответ на вопрос',
    'Вот это всё',                                # pronouns only
    'Девятая статья налогового кодекса гласит о другом',
    'Ужас!',                                      # an exclamation
    'Мама',                                       # somebody called
    'Лёша',
    'В первой части',                             # a fragment: no head
    'Налогового кодекса',                         # a fragment in the genitive
    'Мы вчера ходили в кино',
    'Всё',
    'Так, хорошо',
    'Финансовой системы',                         # a genitive fragment: «системы» is no nominative plural after «финансовой»
    'Первой части',
)


@pytest.mark.parametrize('state', NOTHING_WAITS)
@pytest.mark.parametrize('text', NOT_TOPICS, ids=ids(NOT_TOPICS))
def test_what_is_no_topic_phrase_stays_no_question(text, state):
    assert decide(text, NOTHING_WAITS[state]).kind != QUESTION, text


@pytest.mark.parametrize('text', ['Привет', 'Спасибо большое', 'Добрый день', 'Спасибо, ты молодец'])
def test_greetings_and_thanks_stay_small_talk(text):
    assert decide(text, RETIRED).kind == GREETING, text


# c7-meta round 2 (the coordinator's ruling on W4, oral exam): a whole utterance that is a topic phrase with two content nouns or more and no
# content stem of the waiting answer IS a new question («Ну, строение клетки», «Хотя бы закон Ома», «Состав крови человека» moved to
# test_c7_meta's class); a one-noun phrase, a name, a phrase about the answer stays what it was.
TOPIC_WHILE_WAITING = ('Ну хоть теорема Пифагора', 'Плановая экономика', 'Ну, клетка', 'Хотя бы Ом', 'Ну, строение 988 года')


@pytest.mark.parametrize('profile', PROFILES)
@pytest.mark.parametrize('text', TOPIC_WHILE_WAITING, ids=ids(TOPIC_WHILE_WAITING))
def test_a_noun_phrase_while_a_portion_waits_stays_what_it_was(text, profile):
    """Ruling: a bystander noun phrase while a portion waits stays an attempt / bystander as today; the answer is never retired by it."""
    assert decide(text, WAITING, PROFILES[profile]).kind not in (QUESTION, CORRECTION), text


@pytest.mark.parametrize('text', ['Крещение Руси', 'Ну, крещение Руси'])
def test_the_last_answer_heard_back_after_it_is_complete_is_no_new_topic(text):
    """A late repeat of a completed answer's own words (a duplicated final, a repeat after the end) is not a new question."""
    assert decide(text, DONE).kind != QUESTION
    assert decide(text, RETIRED).kind != QUESTION


def test_a_topic_phrase_waits_for_the_answer_being_made_in_the_classic_route():
    pending = dict(DONE, pending_turn='t9')
    assert decide('Ну, теорема Пифагора', pending).kind != QUESTION


# =====================================================================================================================================
# 2. Several sentences: chat before the question is dropped (NEW wordings)
# =====================================================================================================================================

CHAT_THEN_QUESTION = (
    ('Так, я готов. Что такое энтропия?', 'Что такое энтропия?'),
    ('Ладно, проехали. Сколько длится беременность у слона?', 'Сколько длится беременность у слона?'),
    ('Я тут подумал. Вопрос такой: почему небо голубое', 'почему небо голубое'),
    ('Ну всё, поехали. Плановая экономика.', 'Плановая экономика'),
    ('Короче, слушай. Девятая статья Налогового кодекса.', 'Девятая статья Налогового кодекса'),
    ('Ну я не знаю. Когда началась Столетняя война?', 'Когда началась Столетняя война?'),
    ('Подожди, сейчас соберусь. Чем отличается вирус от бактерии?', 'Чем отличается вирус от бактерии?'),
    ('Это было давно. Как звали первого космонавта?', 'Как звали первого космонавта?'),
    ('Так, это понятно. Теперь о другом: сколько струн у обычной гитары', None),
    ('Хорошо, с этим ясно. А вот ещё вопрос: сколько клеток на шахматной доске', None),
    ('Ну и короче всё. Вопрос получается про закон спроса и предложения', 'про закон спроса и предложения'),
    ('Ты готов? Что такое кредит?', 'Что такое кредит?'),
    ('Ну ладно. Ну хоть принцип работы турбины', 'принцип работы турбины'),
    ('Всё, я на месте. Теорема Ферма.', 'Теорема Ферма'),
    ('Окей, начинаем. Где находится Марианская впадина?', 'Где находится Марианская впадина?'),
    ('Так, хорошо, понятно. Новый вопрос: как размножаются папоротники', 'как размножаются папоротники'),
)


@pytest.mark.parametrize('text,question', CHAT_THEN_QUESTION, ids=ids(CHAT_THEN_QUESTION))
def test_the_chat_before_a_question_is_dropped_when_nothing_waits(text, question):
    d = decide(text, RETIRED)
    assert d.kind == QUESTION, (text, d)
    if question:
        assert d.question.rstrip('.') == question, (text, d)
    assert republished(d).kind == QUESTION, (text, republished(d))


PREMISES = ('В классе тридцать учеников. Сколько из них девочек, если мальчиков двенадцать?',
            'Поезд вышел в девять утра. Когда он прибудет, если едет четыре часа?',
            'Велосипедист едет со скоростью 12 километров в час. Сколько он проедет за пять? Нет, за п')


@pytest.mark.parametrize('text', PREMISES, ids=ids(PREMISES))
def test_a_premise_with_content_is_kept_with_its_question(text):
    """A word problem's condition is no chat: a sentence that carries content stays in the question."""
    d = decide(text, RETIRED)
    assert d.kind == QUESTION and d.question.startswith(text.split('.')[0]), (text, d)


BYSTANDER_TWO_SENTENCES = ('Мы вчера ходили в кино. Там было очень шумно.', 'Я сегодня задержусь. Как же там холодно',
                           'Лёша, я задержусь. Ужинайте без меня.', 'Он позвонил вечером. Сказал, что приедет завтра.')


@pytest.mark.parametrize('profile', PROFILES)
@pytest.mark.parametrize('text', BYSTANDER_TWO_SENTENCES, ids=ids(BYSTANDER_TWO_SENTENCES))
def test_bystander_sentences_never_retire_a_waiting_portion(text, profile):
    assert decide(text, WAITING, PROFILES[profile]).kind not in (QUESTION, CORRECTION), text


# =====================================================================================================================================
# 3. An indirect question inside a request or a complaint (NEW wordings)
# =====================================================================================================================================

INDIRECT = (
    ('Ты можешь объяснить, что такое инфляция?', 'что такое инфляция'),
    ('Тебе нужно сказать, в чём смысл жизни', 'в чём смысл жизни'),
    ('Нужно объяснить, чем отличается вирус от бактерии', 'чем отличается вирус от бактерии'),
    ('Можешь рассказать, кто написал «Войну и мир»?', 'кто написал «Войну и мир»'),
    ('Скажи вот что: какая самая длинная река в Европе', 'какая самая длинная река в Европе'),
    ('Ну ты хоть скажи, что такое ВВП', 'что такое ВВП'),
    ('Ты должен объяснить, где находится Эверест', 'где находится Эверест'),
    ('Блин, ну можешь подсказать, какой газ преобладает в атмосфере Земли', 'какой газ преобладает в атмосфере Земли'),
    ('Ты опять молчишь, а мне надо сказать, что такое амортизация', 'что такое амортизация'),
    ('Попробуй рассказать, откуда берётся радуга', 'откуда берётся радуга'),
    ('Мне нужно, чтобы ты объяснил, что значит дефолт', 'что значит дефолт'),
    ('Короче, надо срочно сказать, когда отменили крепостное право', 'когда отменили крепостное право'),
    ('Тебе надо объяснить, почему падает рубль', 'почему падает рубль'),
    ('Ты обязательно должен сказать, сколько стоит баррель нефти', 'сколько стоит баррель нефти'),
    ('Можете пояснить, что означает термин «маржа»?', 'что означает термин «маржа»'),
    ('Мне хотелось бы, чтобы ты рассказал, как устроена биржа', 'как устроена биржа'),
    ('Хочу, чтобы ты назвал, кто открыл пенициллин', 'кто открыл пенициллин'),
    ('Ты же можешь подсказать, в каком году основан Петербург', 'в каком году основан Петербург'),
    ('Ты тупишь, лучше объясни, почему небо голубое', 'почему небо голубое'),
    ('Скажи следующее: сколько костей в теле человека', 'сколько костей в теле человека'),
)


@pytest.mark.parametrize('state', ['retired', 'waiting'])
@pytest.mark.parametrize('text,question', INDIRECT, ids=ids(INDIRECT))
def test_an_indirect_question_is_the_embedded_question(text, question, state):
    d = decide(text, RETIRED if state == 'retired' else WAITING)
    assert (d.kind, d.question) == (QUESTION, question), (text, d)
    assert republished(d).kind == QUESTION, (text, republished(d))


IMPERATIVE_REQUESTS = ('Объясни, пожалуйста, почему небо голубое', 'Расскажи мне, как работает ядерный реактор',
                       'Слушай, обязательно назови, сколько планет в Солнечной системе', 'Объясни мне наконец, зачем нужен Центробанк',
                       'Расскажи, как возникает цунами')


@pytest.mark.parametrize('state', ['retired', 'waiting'])
@pytest.mark.parametrize('text', IMPERATIVE_REQUESTS, ids=ids(IMPERATIVE_REQUESTS))
def test_a_request_that_already_asks_keeps_its_words(text, state):
    """«Расскажи, как возникает цунами» was a question before wave F and is passed on as it was said (W1F: the conversation map, the
    return to a topic); rule 3 only RESCUES an imperative that asked nothing strong by itself, or one inside a remark."""
    d = decide(text, RETIRED if state == 'retired' else WAITING)
    assert d.kind == QUESTION and d.reason != 'indirect_question' and text.endswith(d.question), (text, d)    # leading fillers aside


NOT_INDIRECT = (
    'Можно сказать, что он прав',              # «что» is the conjunction (E3a-rest ruling 5)
    'Я тебе говорю, что это неправда',
    'Нужно сказать, как есть',                  # nothing to ask about
    'Нужно объяснить разницу между весом и массой',   # E3a-rest fix round 2: a statement
    'Он объяснил, почему опоздал',              # the past of a saying verb is no request
    'Скажи, что ты согласен',
)


@pytest.mark.parametrize('text', NOT_INDIRECT, ids=ids(NOT_INDIRECT))
def test_a_saying_verb_without_an_embedded_question_is_no_indirect_question(text):
    for state in (RETIRED, WAITING):
        assert decide(text, state).reason != 'indirect_question', text


@pytest.mark.parametrize('text', ['Можно сказать, что он прав', 'Нужно объяснить разницу между весом и массой'])
def test_the_modal_statements_stay_statements_while_a_portion_waits(text):
    assert decide(text, WAITING).kind not in (QUESTION, CORRECTION), text


# =====================================================================================================================================
# 4. Remarks to the prompter about its own work (NEW wordings)
# =====================================================================================================================================

REMARKS = (
    'Почему ты так долго молчишь?', 'Ты опять тормозишь', 'Зачем ты отвечаешь по одному слову?', 'Ты завис, что ли?',
    'Почему ты мне не подсказываешь?', 'Ты вообще меня слушаешь или тупишь?', 'Сколько можно тянуть с ответом?',
    'Зачем было так долго молчать?', 'Ты сломался или как?', 'Ну что ты издеваешься надо мной?',
    'Почему нельзя было сразу сказать, а ты тянешь?', 'Как тебя настроить, чтобы ты отвечал быстрее?',
    'Почему ты суфлируешь так медленно?', 'Ты что, опять замолчал?', 'Зачем ты мне это говоришь?', 'Хватит тупить, отвечай',
)


@pytest.mark.parametrize('state', ['retired', 'waiting', 'idle'])
@pytest.mark.parametrize('text', REMARKS, ids=ids(REMARKS))
def test_a_remark_to_the_prompter_is_quiet(text, state):
    d = decide(text, {'retired': RETIRED, 'waiting': WAITING, 'idle': None}[state])
    assert (d.kind, d.reason) == (QUIET, 'remark_to_prompter'), (text, d)


REAL_QUESTIONS_WITH_YOU = (
    ('Почему ты выбрал эту профессию?', None), ('Ты знаешь, когда родился Пушкин?', None), ('Что ты имеешь в виду?', None),
    ('Хорошо, а что ты говорил про давление?', None), ('Ты можешь сказать дату крещения Руси?', None),
    ('Ты можешь объяснить, что такое инфляция?', 'что такое инфляция'), ('Что мне ответить?', None), ('Почему вулкан молчит?', None),
    ('Почему так?', None), ('А почему?', None), ('Как ответить на вопрос про налоги?', None),
    ('Хорошо, а что ты там говорил про жир?', None), ('А откуда ты это взял?', None),
    ('Ты говорил, что ураган возникает без причины, но ведь причина есть?', None),     # what was said is content (T-A F02)
    ('Почему ты сказал, что Луна больше Солнца?', None),
)


@pytest.mark.parametrize('state', ['retired', 'waiting'])
@pytest.mark.parametrize('text,question', REAL_QUESTIONS_WITH_YOU, ids=ids(REAL_QUESTIONS_WITH_YOU))
def test_real_questions_that_use_you_stay_questions(text, question, state):
    d = decide(text, RETIRED if state == 'retired' else WAITING)
    assert d.kind == QUESTION, (text, d)
    if question:
        assert d.question == question, (text, d)


@pytest.mark.parametrize('text,kind', [('Стоп', STOP), ('Ты ошибся', CORRECTION), ('Повтори', REPEAT), ('Повтори, пожалуйста', REPEAT)])
def test_commands_keep_their_meaning(text, kind):
    assert decide(text, WAITING).kind == kind, text


def test_a_request_to_repeat_what_was_said_is_no_remark():
    """«Повтори, что ты сейчас сказал» and «Что ты сказал?» are about hearing the answer, not remarks on the prompter's work."""
    for text in ('Повтори, что ты сейчас сказал', 'Подожди-ка, а что ты мне только что сказал про вулканы? Повтори.', 'Что ты сказал?'):
        for state in (WAITING, RETIRED):
            assert decide(text, state).reason != 'remark_to_prompter', text


# =====================================================================================================================================
# 5. The answer policy v2.3
# =====================================================================================================================================

def squash(text):
    return text.casefold().replace('ё', 'е')


def paragraph_with(*patterns):
    blocks = [squash(block) for block in re.split(r'\n\s*\n', ANSWER_POLICY.strip()) if block.strip()]
    return any(all(re.search(squash(p), block, re.DOTALL) for p in patterns) for block in blocks)


def test_the_policy_answers_a_named_article_term_or_topic_briefly_as_a_what_is_it_question():
    assert paragraph_with(r'стать', r'термин', r'тем[аы]', r'«что это»', r'коротко')
    assert paragraph_with(r'приветстви', r'фонов', r'учебн\w+ ответ')
    assert 'не начинай учебный ответ на приветствие, фоновый разговор или название темы' not in squash(ANSWER_POLICY)


def test_the_policy_version_moved_and_the_size_cap_holds():
    assert content_policy.POLICY_VERSION == 'answer-v2.5'
    assert len(ANSWER_POLICY) <= 2490, len(ANSWER_POLICY)


# =====================================================================================================================================
# 6. Through the real controller (ControlledMedia -> EchoEngine): a topic is asked and its answer is dictated; a remark changes nothing
# =====================================================================================================================================

def test_dispatch_a_topic_phrase_at_the_start_of_a_call_is_asked_and_its_answer_dictated(tmp_path):
    d = H.Dictation(tmp_path / 'topic', None)
    out = d.say('Ну хоть плановая экономика')
    assert out.types[:1] == ['cancel'] and out.types[1] in ('route', 'lookup'), out.types
    assert d.controller.question_text == 'плановая экономика'
    out = d.deliver(H.done('a9', 'assistant', 'Плановая экономика — это когда ресурсы распределяет государство по единому плану.'))
    assert out.speaks, out.types
    assert d.state['question'] == 'плановая экономика'


def test_dispatch_the_calls_complaint_asks_its_embedded_question(tmp_path):
    d = H.Dictation(tmp_path / 'complaint', None)
    out = d.say(CALL_COMPLAINT)
    assert out.types[:1] == ['cancel'] and out.types[1] in ('route', 'lookup'), out.types
    assert d.controller.question_text == 'что такое девятая статья налогового кодекса'


@pytest.mark.parametrize('head,tail', [('Расскажи про', 'ледниковый период.'), ('Объясни мне про', 'закон Архимеда.'),
                                       ('А что известно о', 'Ганзейском союзе.')])
def test_dispatch_a_topic_tail_after_a_head_cut_at_a_preposition_is_one_question(tmp_path, head, tail):
    """T-A F39/C17 with a topic tail: alone «ледниковый период.» is a question now, after «Расскажи про» (0.5 s, inside the coalescing
    window) it is that question's complement - one question, both halves kept (ControlledMedia._goes_on, the seam)."""
    d = H.Dictation(tmp_path / 'seam', None)
    d.say(head, tid='q-head')
    d.say(tail, gap=0.5, tid='q-tail')
    kept = ' '.join(norm_words(d.controller.question_text))
    assert ' '.join(norm_words(head)[-2:]) in kept and ' '.join(norm_words(tail)) in kept, d.controller.question_text


def test_dispatch_a_remark_while_a_portion_waits_leaves_the_portion_waiting_and_asks_nothing(tmp_path):
    d = H.Dictation(tmp_path / 'remark', H.LONG_ANSWERS[1])
    for text in ('Зачем вот это вот всё тянуть надо было', 'Почему ты так долго молчишь?', 'Ты опять тормозишь'):
        out = d.say(text)
        assert not out.destroyed and out.after == out.before and out.model_calls == 0, (text, out.types)
