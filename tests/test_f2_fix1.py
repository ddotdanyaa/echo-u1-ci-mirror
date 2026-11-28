"""Wave F / F2, fix round 1 (the coordinator's review of 709e203..819095a, 3 Nov): two critical and eleven important regressions against
9062f3b, settled by seven rulings. Each block below is one ruling; the wordings are the reviewers' (scratchpad cases*.json) and new ones.

1. a question the provider splits («Сколько стоит» | «баррель нефти») keeps its head: a topic-phrase tail goes on with the question;
2. a complaint and a direct question in one sentence («Ты молчишь, а сколько стоит баррель нефти?») ask the question clause;
3. a remark needs the singular «ты» (never «вы»); a clause that names something is never one; «, ты сказал,» is a parenthesis;
4. no topic phrase while an accepted question is in flight, nor a name, a vocative, a roll call, a hold word, an interjection-like or an
   evaluative-only phrase, a caption in capitals; thanks and farewells are small talk;
5. the explicit marker «Вопрос (такой / получается) …» counts only before a question or a topic phrase (and in marker form after the first
   sentence);
6. a comma-joined chatty preface: the marker at any clause start; with nothing waiting, the last clause that asks and names something.
"""
import pytest

import helpers_s6_ack as H
from echo_sync.classifier import CORRECTION, GREETING, QUESTION, QUIET, analyze
from echo_sync.textutil import norm_words
from test_f2_questions import DONE, PROD, RETIRED, WAITING, ids, republished

STATES = {'idle': None, 'retired': RETIRED, 'done': DONE}


def decide(text, state=None):
    return analyze(text, state, [], PROD)


def words(text):
    return ' '.join(norm_words(text))


# =====================================================================================================================================
# 1. A question split by the provider keeps its head (critical)
# =====================================================================================================================================

SPLIT = (('Сколько стоит', 'баррель нефти'), ('Когда родился', 'Пушкин'), ('Что такое', 'налоговый вычет'),
         ('Когда был основан', 'Санкт-Петербург.'), ('Как называется наука, которая изучает', 'грибы'), ('Кто написал', 'Войну и мир'),
         ('Где находится', 'Марианская впадина'), ('Сколько процентов составляет', 'ставка НДС'), ('Чем отличается', 'вирус от бактерии'),
         ('В каком году произошло', 'крещение Руси'), ('Какая столица', 'Австралии'), ('Объясни принцип', 'работы двигателя'),
         ('Сколько весит', 'взрослый слон.'), ('Расскажи про', 'ледниковый период.'), ('Кто открыл', 'закон всемирного тяготения'))


@pytest.mark.parametrize('gap', [0.5, 1.5])
@pytest.mark.parametrize('head,tail', SPLIT, ids=ids(SPLIT))
def test_dispatch_a_question_split_by_the_provider_keeps_its_head(tmp_path, head, tail, gap):
    d = H.Dictation(tmp_path / 'split', None)
    d.say(head, tid='q-head')
    out = d.say(tail, gap=gap, tid='q-tail')
    kept = words(d.controller.question_text)
    assert words(head).split()[-1] in kept.split() and words(tail) in kept, (d.controller.question_text, out.types)


@pytest.mark.parametrize('head,tail', SPLIT[:4], ids=ids(SPLIT[:4]))
def test_dispatch_a_split_question_after_a_completed_answer_keeps_its_head(tmp_path, head, tail):
    d = H.Dictation(tmp_path / 'after', H.LONG_ANSWERS[0])
    while not d.completed:
        d.say(d.current, gap=2.0)
    d.say(head, tid='q-head')
    d.say(tail, gap=0.5, tid='q-tail')
    kept = words(d.controller.question_text)
    assert words(head).split()[-1] in kept.split() and words(tail) in kept, d.controller.question_text


# =====================================================================================================================================
# 2. A complaint and a direct question in one sentence: the question clause is asked (critical)
# =====================================================================================================================================

COMPLAINT_AND_QUESTION = (
    ('Ты молчишь, а сколько стоит баррель нефти?', 'сколько стоит баррель нефти?'),
    ('Опять ты тормозишь, когда было крещение Руси?', 'когда было крещение Руси?'),
    ('Ты опять завис, а где находится Эверест?', 'где находится Эверест?'),
    ('Чего ты молчишь, кто открыл пенициллин?', 'кто открыл пенициллин?'),
    ('Ты снова тупишь, а какая столица Канады', 'какая столица Канады'),
    ('Ты опять тормозишь, сколько длится футбольный матч?', 'сколько длится футбольный матч?'),
    ('Ты сломался, что ли, когда началась Первая мировая война?', 'когда началась Первая мировая война?'),
)


@pytest.mark.parametrize('state', ['retired', 'waiting'])
@pytest.mark.parametrize('text,question', COMPLAINT_AND_QUESTION, ids=ids(COMPLAINT_AND_QUESTION))
def test_a_complaint_with_a_direct_question_asks_the_question_clause(text, question, state):
    d = decide(text, RETIRED if state == 'retired' else WAITING)
    assert (d.kind, d.question) == (QUESTION, question), (text, d)
    assert republished(d).kind == QUESTION


# =====================================================================================================================================
# 3. Remarks narrowed: the singular «ты» only; a clause that names something is never one; «, ты сказал,» is a parenthesis
# =====================================================================================================================================

STAY_QUESTIONS = (
    'А когда, ты сказал, была Куликовская битва?', 'Ты говоришь по-английски?', 'На каких языках ты говоришь?',
    'За что вы отвечали на прошлой работе?', 'Что ты скажешь о себе?', 'Как ты отвечаешь на критику?',
    'Что ты ответишь клиенту, если он скажет, что дорого?', 'Ты часто молчишь на совещаниях?', 'Можно ли молчать на допросе?',
    'Почему нельзя тянуть с оплатой налогов?', 'А сколько, ты говорил, там процентов?', 'Как ты сказал, называется этот закон?',
    'Где, как ты говоришь, находится Эверест?', 'Ты говоришь, инфляция растёт. Почему?', 'Сколько, вы сказали, длится испытательный срок?',
    'Что вы можете сказать о своём опыте?', 'Ты отвечаешь за продажи?', 'Что бы ты сказал своему руководителю?',
    'Как ты настроишь CRM для отдела продаж?', 'Ты умеешь говорить на публике?', 'Как правильно тормозить на скользкой дороге?',
    'Почему нельзя тормозить двигателем?', 'Зачем издеваться над животными?', 'Почему ты не ответил на письмо?',
    'Как вы настраиваете Kubernetes?', 'Что вы скажете в заключение?', 'Почему нельзя молчать при задержании',
    'Когда, как вы сказали, был подписан договор?', 'В каком году, ты сказал, отменили крепостное право?',
    'Ты сказал, НДС двадцать процентов. А для продуктов сколько?', 'Что ты скажешь, если тебя спросят про зарплату?',
    'Вы говорите на китайском?', 'Как не тормозить на экзамене?', 'Хорошо. А почему, как ты говоришь, план важнее рынка?',
    'Подожди. Ты говоришь, рубль падает. А из-за чего?', 'Когда это было, ты говоришь?', 'Сколько стоит баррель нефти, ты сказал?',
    'Как, ты говоришь, звали первого космонавта?', 'А ты говоришь, когда это было?', 'Почему вы молчите?',
    'Как часто вы отвечаете на звонки вне работы?', 'Ты сказал, Русь крестили в 988. Почему именно тогда?',
)


@pytest.mark.parametrize('state', ['retired', 'waiting'])
@pytest.mark.parametrize('text', STAY_QUESTIONS, ids=ids(STAY_QUESTIONS))
def test_a_content_question_to_the_listener_stays_a_question(text, state):
    d = decide(text, RETIRED if state == 'retired' else WAITING)
    assert d.kind == QUESTION, (text, d)


SINGULAR_REMARKS = ('Почему ты опять молчишь?', 'Ты чего тормозишь?', 'Зачем ты отвечаешь по одному слову?', 'Ты завис, что ли?',
                    'Сколько можно тянуть с ответом?', 'Хватит тупить', 'Ты сломался вообще', 'Ты молчишь. Почему?')


@pytest.mark.parametrize('state', ['retired', 'waiting'])
@pytest.mark.parametrize('text', SINGULAR_REMARKS, ids=ids(SINGULAR_REMARKS))
def test_a_remark_said_to_the_prompter_with_the_singular_you_stays_a_remark(text, state):
    d = decide(text, RETIRED if state == 'retired' else WAITING)
    assert (d.kind, d.reason) == (QUIET, 'remark_to_prompter'), (text, d)


# =====================================================================================================================================
# 4. Topic phrases narrowed
# =====================================================================================================================================

NO_TOPIC = (
    'Петров', 'Иван Петрович', 'Мария Ивановна', 'Дмитрий Сергеевич', 'Пушкин', 'Здравствуйте, Мария Ивановна', 'Спасибо, удачи.',
    'Петров, к доске', 'Следующий, Сидоров', 'Так, Петров', 'Спасибо, Мария Ивановна', 'Добрый день, Иван Петрович',
    'Иван Петрович, доброе утро', 'До свидания, Иван Петрович', 'Секунду', 'Минуту', 'Момент', 'Одну минуту', 'Секундочку', 'Так, секунду',
    'Минуточку', 'Удачи', 'Ну, удачи', 'Красота', 'Кошмар', 'Ужас', 'Жесть', 'Тишина', 'Тишина в классе', 'Хорошая работа.',
    'Интересная мысль.', 'Отличная работа', 'Прекрасная идея', 'Хорошая погода', 'Плохая связь', 'Хорошая работа, Иван',
    'Отличная работа, коллеги', 'ДИНАМИЧНАЯ МУЗЫКА', 'АПЛОДИСМЕНТЫ ЗРИТЕЛЕЙ', 'Красивое платье', 'Имя, фамилия',
)


@pytest.mark.parametrize('state', STATES)
@pytest.mark.parametrize('text', NO_TOPIC, ids=ids(NO_TOPIC))
def test_names_vocatives_hold_words_interjections_and_evaluations_are_no_topic(text, state):
    assert decide(text, STATES[state]).kind != QUESTION, text


COURTESY = ('Спасибо, удачи.', 'До свидания', 'Удачи', 'Всего хорошего', 'Хорошего дня', 'Спокойной ночи', 'До встречи', 'Всего доброго')


@pytest.mark.parametrize('text', COURTESY, ids=ids(COURTESY))
def test_thanks_and_farewells_are_small_talk(text):
    for state in (None, RETIRED, WAITING):
        assert decide(text, state).kind == GREETING, text


STILL_TOPICS = (('Ну хоть девятая статья налогового кодекса', 'девятая статья налогового кодекса'), ('Закон Ома', 'Закон Ома'),
                ('Теорема Пифагора', 'Теорема Пифагора'), ('Ну, эффект Доплера', 'эффект Доплера'), ('Момент инерции', 'Момент инерции'),
                ('Холодная война', 'Холодная война'), ('Статья 145 НК РФ', 'Статья 145 НК РФ'), ('Инфляция', 'Инфляция'),
                ('Так, МСФО', 'МСФО'), ('Смысл плановой экономики', 'Смысл плановой экономики'))


@pytest.mark.parametrize('state', STATES)
@pytest.mark.parametrize('text,phrase', STILL_TOPICS, ids=ids(STILL_TOPICS))
def test_named_topics_are_still_questions(text, phrase, state):
    d = decide(text, STATES[state])
    assert (d.kind, d.question) == (QUESTION, phrase), (text, d)


@pytest.mark.parametrize('first,second', [('Когда было крещение Руси?', 'Крещение Руси.'), ('Что такое инфляция?', 'Секунду.'),
                                          ('Что такое инфляция?', 'Хорошая работа.'), ('Что такое инфляция?', 'Инфляция.'),
                                          ('Расскажи, как работает биржа.', 'Биржа.'), ('Когда родился Пушкин?', 'Ну, Пушкин')])
def test_dispatch_no_topic_phrase_replaces_a_question_whose_answer_is_still_coming(tmp_path, first, second):
    d = H.Dictation(tmp_path / 'flight', None)
    d.say(first, tid='q1')
    asked = d.controller.question_text
    out = d.say(second, gap=4.0, tid='q2')
    assert 'cancel' not in out.types and d.controller.question_text == asked and d.controller.question_id == 'q1', (second, out.types)


def test_dispatch_a_topic_phrase_after_a_completed_answer_is_a_new_question(tmp_path):
    d = H.Dictation(tmp_path / 'after', H.LONG_ANSWERS[0])
    while not d.completed:
        d.say(d.current, gap=2.0)
    out = d.say('Ну хоть плановая экономика', gap=3.0)
    assert out.types[:1] == ['cancel'] and d.controller.question_text == 'плановая экономика', out.types


# =====================================================================================================================================
# 5. The explicit marker counts only before a question or a topic phrase
# =====================================================================================================================================

NOT_A_MARKER = ('Блин. Вопрос такой сложный.', 'Да уж. Вопрос получается риторический.', 'Он задал мне вопрос. Вопрос был сложный.',
                'Да нет. Вопрос не в этом.', 'Вопрос такой сложный', 'Ох. Вопрос получается непростой.', 'Ой. Вопрос такой, я не знаю.',
                'Хм. Вопрос получается с подвохом.', 'Так. Вопрос следующий, наверное.', 'Понятно. Вопрос такой интересный, конечно.',
                'Вопрос не в этом', 'Это вопрос времени.')


@pytest.mark.parametrize('state', ['idle', 'retired', 'waiting'])
@pytest.mark.parametrize('text', NOT_A_MARKER, ids=ids(NOT_A_MARKER))
def test_the_word_question_before_no_question_is_no_marker(text, state):
    d = decide(text, {'idle': None, 'retired': RETIRED, 'waiting': WAITING}[state])
    assert d.kind not in (QUESTION, CORRECTION), (text, d)


MARKERS = (('Ну и короче я готов. А какой вопрос? Вопрос, получается, двадцать первая статья налогового кодекса',
            'двадцать первая статья налогового кодекса'),
           ('Следующий вопрос: статья 146 НК РФ', 'статья 146 НК РФ'), ('Новый вопрос: закон Ома', 'закон Ома'),
           ('Вопрос получается закон Ома', 'закон Ома'), ('Другой вопрос: как работает насос', 'как работает насос'),
           ('Вопрос такой: почему небо голубое?', 'почему небо голубое?'), ('Вопрос: финансовая система', 'финансовая система'),
           ('Так. Вопрос такой: сколько ног у паука', 'сколько ног у паука'))


@pytest.mark.parametrize('state', ['idle', 'waiting'])
@pytest.mark.parametrize('text,question', MARKERS, ids=ids(MARKERS))
def test_the_marker_before_a_question_or_a_topic_asks_it(text, question, state):
    d = decide(text, None if state == 'idle' else WAITING)
    assert (d.kind, d.question) == (QUESTION, question), (text, d)
    assert republished(d).kind == QUESTION


# =====================================================================================================================================
# 6. A comma-joined chatty preface
# =====================================================================================================================================

COMMA_PREFACE = (
    ('Ну и короче я готов, а какой вопрос, вопрос получается 21-ая статья налогового кодекса', '21-ая статья налогового кодекса'),
    ('Короче, тут такой вопрос, что такое энтропия', 'что такое энтропия'),
    ('Хорошо, с этим разобрались, теперь другое, когда отменили крепостное право', 'когда отменили крепостное право'),
    ('Слушай, я тут подумал, а вот ещё вопрос, сколько клеток на шахматной доске', 'сколько клеток на шахматной доске'),
    ('Ну короче, я всю ночь думал, и вот что хотел спросить: когда была Куликовская битва', 'когда была Куликовская битва'),
    ('Ладно, проехали, вопрос такой, где находится Марианская впадина', 'где находится Марианская впадина'),
    ('Окей, я готов, в каком году основан Рим', 'в каком году основан Рим'),
    ('Значит так, слушай внимательно, сколько ног у паука', 'сколько ног у паука'),
)


@pytest.mark.parametrize('state', ['idle', 'retired', 'done'])
@pytest.mark.parametrize('text,question', COMMA_PREFACE, ids=ids(COMMA_PREFACE))
def test_a_comma_joined_preface_is_dropped_when_nothing_waits(text, question, state):
    d = decide(text, STATES[state])
    assert (d.kind, d.question) == (QUESTION, question), (text, d)
    assert republished(d).kind == QUESTION


RELATIVE_CLAUSES = ('Мы гуляли в парке, где растут дубы', 'Я помню время, когда был студентом', 'Он рассказал историю, как поймал щуку',
                    'Это тот самый дом, где жил Пушкин')


@pytest.mark.parametrize('text', RELATIVE_CLAUSES, ids=ids(RELATIVE_CLAUSES))
def test_a_relative_clause_after_a_noun_is_no_question(text):
    assert decide(text, RETIRED).kind != QUESTION, text


WAITING_UNCHANGED = ('Короче, тут такой вопрос, что такое энтропия', 'Значит так, слушай внимательно, сколько ног у паука',
                     'Хорошо, с этим разобрались, теперь другое, когда отменили крепостное право')


@pytest.mark.parametrize('text', WAITING_UNCHANGED, ids=ids(WAITING_UNCHANGED))
def test_the_last_clause_rule_never_retires_a_waiting_portion(text):
    """Silent on 9062f3b while a portion waits, and still: the waiting-state guard is unchanged."""
    assert decide(text, WAITING).kind not in (QUESTION, CORRECTION), text


# =====================================================================================================================================
# Review notes settled with the rulings (cases*.json G01-G05, C21, M10, F07, B10/B11)
# =====================================================================================================================================

SHORT_IMPERATIVES = ('Скажи, где ключи', 'Подскажи, где туалет', 'Скажи, когда обед', 'Подскажи, где выход')


@pytest.mark.parametrize('text', SHORT_IMPERATIVES, ids=ids(SHORT_IMPERATIVES))
def test_a_two_word_request_never_retires_a_waiting_portion(text):
    assert decide(text, WAITING).kind not in (QUESTION, CORRECTION), text


@pytest.mark.parametrize('text,question', [
    ('Слушай, ну ты можешь хотя бы сказать, когда была Куликовская битва, или ты опять будешь молчать?', 'когда была Куликовская битва'),
    ('Ну ты хотя бы подскажи, в чём смысл плановой экономики, а то я сейчас завалюсь', 'в чём смысл плановой экономики'),
    ('Тебе надо объяснить, что такое ВВП, иначе я завалю экзамен', 'что такое ВВП')])
def test_the_embedded_question_ends_before_the_remark_that_follows_it(text, question):
    assert decide(text, RETIRED).question == question


def test_the_marker_takes_the_question_of_the_next_sentence_while_a_portion_waits():
    d = decide('Так, следующий вопрос. Закон Ома.', WAITING)
    assert (d.kind, d.question) == (QUESTION, 'Закон Ома.'), d


@pytest.mark.parametrize('text', ['Музыка', 'Аплодисменты', 'Смех', 'Шум'])
def test_a_sound_caption_alone_is_no_topic(text):
    assert decide(text, RETIRED).kind != QUESTION
    assert decide(text + ' барокко' if text == 'Музыка' else 'Теория шума', RETIRED).kind == QUESTION
