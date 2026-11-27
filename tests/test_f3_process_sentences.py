"""Wave F / F3, item 1 (the owner's REAL call of 3 Nov 09:55): the cloud's sentences about its own actions are never cued.

Seen as cues or cloud texts: «Сейчас коротко сформулирую.» (cued twice, the owner repeated it), «Сейчас уточню формулировку.», «Уточню дату.»,
«Понял, гляну детали статьи.», «Сейчас скажу коротко по делу.», «Понял, сейчас уточню кратко по девятой статье.», «Слышу твою оценку, сейчас
кратко отвечу на это.». The old filter (textutil.strip_process_prefix) was a list of phrases: a verb out of the list, an adverb between «сейчас» and
the verb, an acknowledgement in front of an unlisted verb - and the sentence was spoken. The class (pymorphy3): a leading sentence whose predicate is
a 1st-person-singular non-past verb of the act of answering (формулировать, уточнить, глянуть, проверить, ответить, ...), or an acknowledgement-only
sentence, that adds nothing - no number, no negation, no clause of its own, no noun that is neither the act's own object (формулировка, дата,
детали, оценка, ...) nor a word of the question - is stripped from the start of an answer; a reply made only of such sentences is not an answer.
Content answers in the first person stay.

Every rule is shown on NEW wordings (the call's own sentences are only the first parametrisation).
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import helpers_s6_seg as H                                           # noqa: E402
from echo_sync import textutil                                       # noqa: E402
from echo_sync.textutil import strip_process_prefix                  # noqa: E402

BODY = 'Крещение Руси относят к девятьсот восемьдесят восьмому году.'
Q = 'Когда было крещение Руси'

# --- 1. the owner's call (sentence, the question of that turn) ------------------------------------------------------------------------
CALL = [
    ('Сейчас коротко сформулирую.', 'В чём заключается смысл экономики плановой'),                       # cued twice
    ('Сейчас уточню формулировку.', '21-ая статья налогового кодекса. Что такое'),
    ('Уточню дату.', Q),
    ('Понял, гляну детали статьи.', '21-ая статья налогового кодекса. Что такое'),                      # «статьи» is the question's own word
    ('Сейчас скажу коротко по делу.', 'ну хоть девятая статья налогового кодекса'),
    ('Понял, сейчас уточню кратко по девятой статье.', 'ну хоть девятая статья налогового кодекса'),
    ('Слышу твою оценку, сейчас кратко отвечу на это.', 'Зачем вот это вот всё тянуть надо было'),
]


@pytest.mark.parametrize('sentence,question', CALL)
def test_the_calls_own_sentences_are_stripped_from_the_start_of_an_answer(sentence, question):
    assert strip_process_prefix(sentence + ' ' + BODY, question) == BODY


@pytest.mark.parametrize('sentence,question', CALL)
def test_a_reply_made_only_of_the_calls_sentences_is_not_an_answer(sentence, question):
    assert strip_process_prefix(sentence, question) == ''
    assert strip_process_prefix(sentence + ' ' + sentence, question) == ''


# --- 2. NEW wordings of the same class --------------------------------------------------------------------------------------------------
# (sentence, question). The verbs come from the act of answering (formulate, specify, look, check, say, answer, explain, search, find, think, adapt,
# tell, recall, count, convert ...) in both aspects, with the adverbs and objects such a sentence takes.
NEW = [
    ('Сейчас аккуратно сформулирую ответ.', Q),
    ('Секунду, проверю цифры.', Q),
    ('Одну секунду, формулирую ответ.', Q),
    ('Хорошо, посмотрю и отвечу коротко.', Q),
    ('Принял, думаю над формулировкой.', Q),
    ('Секундочку, вспоминаю дату.', Q),
    ('Ага, сейчас найду точную дату.', Q),
    ('Так, подготовлю краткий ответ.', Q),
    ('Попробую объяснить проще.', 'Что такое диффузия'),
    ('Могу сказать это короче.', 'Что такое диффузия'),
    ('Буду отвечать коротко и по делу.', 'Что такое диффузия'),
    ('Сейчас посчитаю.', 'Сколько будет пятнадцать процентов от двухсот'),
    ('Сейчас пересчитаю.', 'Сколько секунд в часе'),
    ('Объясню проще.', 'Что такое диффузия'),
    ('Расскажу вкратце.', 'Что такое диффузия'),
    ('Проверю данные и отвечу.', Q),
    ('Слышу тебя, сейчас отвечу.', Q),
    ('Принято, учту и отвечу короче.', Q),
    ('Хорошо, исправлюсь.', Q),
    ('Понимаю, сейчас объясню по-другому.', 'Что такое диффузия'),
    ('Секунду, уточню название.', 'Как называется самая длинная река'),
    ('Так, сейчас разберусь.', Q),
    ('Подожди, сейчас подумаю.', Q),
    ('Дам краткий ответ.', Q),
    ('Сейчас выясню.', Q),
    ('Понял, сейчас подберу формулировку.', Q),
    ('Ладно, перефразирую.', Q),
    ('Сейчас гляну информацию по этой теме.', 'Что такое диффузия'),                                   # «теме» is the act's own object
    ('Сейчас ещё раз сформулирую.', Q),
    ('Так, смотрю по статье.', Q),
    ('Я смотрю в деталях.', Q),
    ('Сейчас отвечу по существу.', Q),
    ('Секунду, пересчитаю.', 'Сколько будет пятнадцать процентов от двухсот'),
]


@pytest.mark.parametrize('sentence,question', NEW)
def test_new_wordings_of_the_class_are_stripped_from_the_start_of_an_answer(sentence, question):
    assert strip_process_prefix(sentence + ' ' + BODY, question) == BODY


@pytest.mark.parametrize('sentence,question', NEW)
def test_a_reply_made_only_of_a_new_wording_is_not_an_answer(sentence, question):
    assert strip_process_prefix(sentence, question) == ''


def test_two_such_sentences_in_a_row_are_both_stripped():
    assert strip_process_prefix('Хорошо, понял. Сейчас аккуратно сформулирую ответ. Сейчас проверю дату. ' + BODY, Q) == BODY


# --- 3. the class is about the verb, not about a phrase: every lemma of the act, in the forms of both aspects ----------------------------------

def first_person_forms(lemma):
    """The 1st-person-singular non-past form of ``lemma`` that pymorphy3 makes (future of a perfective verb, present of an imperfective one)."""
    from echo_sync import ru_alignment as ru
    ru._lemma(lemma)
    with ru._LOCK:
        parse = next((p for p in ru._MORPH.parse(lemma) if p.normal_form == lemma and p.tag.POS in ('INFN', 'VERB')), None)
        if parse is None:
            return []
        out = []
        for tense in ('futr', 'pres'):
            form = parse.inflect({'1per', 'sing', tense, 'indc'})
            if form is not None and form.word not in out:
                out.append(form.word)
    return out


def test_the_act_lemmas_are_a_real_class():
    lemmas = sorted(getattr(textutil, 'ACT_LEMMAS', ()))
    assert len(lemmas) >= 40
    for brief_lemma in ('сформулировать', 'уточнить', 'глянуть', 'проверить', 'посмотреть', 'сказать', 'ответить', 'объяснить', 'поискать', 'найти',
                        'подумать', 'подстроиться', 'рассказать'):
        assert brief_lemma in lemmas, brief_lemma
    for lemma in ('сформулировать', 'формулировать', 'вспомнить', 'вспоминать', 'пояснить', 'разобраться', 'подсказать', 'сообщить', 'подготовить',
                  'выяснить', 'посчитать', 'прикинуть', 'перевести', 'повторить', 'вернуться'):
        assert lemma in lemmas, lemma


@pytest.mark.parametrize('lemma', sorted(getattr(textutil, 'ACT_LEMMAS', ())))
def test_every_act_lemma_announces_in_its_first_person_forms(lemma):
    forms = first_person_forms(lemma)
    assert forms, lemma
    for form in forms:
        sentence = 'Сейчас коротко ' + form + '.'
        assert strip_process_prefix(sentence + ' ' + BODY, Q) == BODY, sentence
        assert strip_process_prefix(sentence, Q) == '', sentence


# --- 4. an acknowledgement-only sentence -------------------------------------------------------------------------------------------------
ACK_ONLY = ['Угу.', 'Ага.', 'Хорошо.', 'Хорошо, спасибо.', 'Ладно.', 'Понял.', 'Понял, спасибо.', 'Ясно.', 'Понятно.', 'Согласен.', 'Слышу.',
            'Принято.', 'Спасибо.', 'Окей, понял.', 'Поняла, спасибо.', 'Ну ладно, хорошо.', 'Угу, ясно.', 'Согласна.', 'Я понял.',
            'Я вас понял.', 'Ага, я услышал.']


@pytest.mark.parametrize('sentence', ACK_ONLY)
def test_an_acknowledgement_only_sentence_is_stripped_and_a_reply_of_such_sentences_is_nothing(sentence):
    assert strip_process_prefix(sentence + ' ' + BODY, Q) == BODY
    assert strip_process_prefix(sentence, Q) == ''
    assert strip_process_prefix(sentence + ' ' + sentence, Q) == ''


def test_an_acknowledgement_before_a_real_sentence_goes_and_the_sentence_stays():
    assert strip_process_prefix('Хорошо, стоило сразу начать с 988 года.', 'Зачем вот это вот всё тянуть надо было') == 'стоило сразу начать с 988 года.'
    assert strip_process_prefix('Ясно, на сфере сумма углов больше.', Q) == 'на сфере сумма углов больше.'
    # round 1: «согласен / принял / слышал» are whole acknowledgements, never a lead - they are the stance of an answer
    assert strip_process_prefix('Согласен, стоило сразу начать с 988 года.', Q) == 'Согласен, стоило сразу начать с 988 года.'
    assert strip_process_prefix('Согласна, на сфере сумма углов больше.', Q) == 'Согласна, на сфере сумма углов больше.'


# --- 5. content in the first person stays -------------------------------------------------------------------------------------------------
KEEP = [
    'Я работаю бухгалтером пять лет.',
    'Я считаю, что план важнее рынка.',
    'Скажу честно: масса не зависит от места.',
    'Отвечаю на ваш вопрос: вода кипит при ста градусах.',
    'Найду производную по определению.',
    'Скажу, что это не так.',
    'Отвечу через пять минут.',
    'Расскажу о Менделееве подробно.',
    'Объясню на примере яблока.',
    'Я смотрю фильмы по вечерам.',
    'Я думаю о тебе.',
    'Я смотрю на тебя.',
    'Я найду тебя.',
    'Я скажу ему.',
    'Я говорю по-русски.',
    'Я отвечаю за качество.',
    'Я рассказываю детям сказки.',
    'Скажу вам одно: нет.',
    'Не скажу.',
    'Я не знаю, что ответить.',
    'Посмотрю на график и скажу, что рост составил 5%.',
    'Я работаю в «Газпроме».',
    'Могу рассказать про Ньютона.',
    'Буду дома в шесть.',
    'Да.', 'Нет.', 'Конечно.', 'Верно.',
    'Согласен, что план важнее рынка.',
    'Понял, что вы имели в виду другое.',
    'Да, слышу тебя отлично.', 'Да, слышу.', 'Думаю, да.',
    'Давайте разберёмся, что такое масса.', 'Посмотрим на график скорости.', 'Хороший вопрос о массе: это мера.',
    'Момент силы — это произведение силы на плечо.', 'Секунда — единица времени.', 'Понял — это прошедшее время глагола.',
    'Сейчас около нуля утром, после полудня плюс два градуса.',
]


@pytest.mark.parametrize('sentence', KEEP)
def test_content_in_the_first_person_is_left_alone(sentence):
    assert strip_process_prefix(sentence, Q) == sentence
    assert strip_process_prefix(sentence) == sentence


def test_the_briefs_content_answers_keep_their_content():
    assert strip_process_prefix('Скажу так: план важнее рынка', 'Что важнее: план или рынок') == 'план важнее рынка'
    assert strip_process_prefix('Скажу так: план важнее рынка') == 'план важнее рынка'
    assert strip_process_prefix('Я считаю, что план важнее рынка') == 'Я считаю, что план важнее рынка'
    assert strip_process_prefix('Я работаю бухгалтером пять лет') == 'Я работаю бухгалтером пять лет'


# --- 6. an announcement before a colon or a dash ------------------------------------------------------------------------------------------
COLON = [
    ('Скажу так: план важнее рынка', 'план важнее рынка'),
    ('Сейчас скажу коротко: 988 год.', '988 год.'),
    ('Объясню просто: вода кипит при 100 градусах.', 'вода кипит при 100 градусах.'),
    ('Возвращаюсь: молекулы воды окружают жир.', 'молекулы воды окружают жир.'),
    ('Отвечу кратко: нет, не должен.', 'нет, не должен.'),
    ('Скажу так — план важнее рынка.', 'план важнее рынка.'),
    ('Скажу по-другому: ставка выросла вдвое.', 'ставка выросла вдвое.'),
]


@pytest.mark.parametrize('text,expected', COLON)
def test_an_announcement_before_a_colon_or_a_dash_goes_and_the_content_after_it_stays(text, expected):
    assert strip_process_prefix(text, 'Что важнее: план или рынок') == expected


# --- 7. the question makes the topic words harmless, and only those -------------------------------------------------------------------------
def test_a_word_of_the_question_makes_the_sentence_an_answer_and_the_acts_own_objects_do_not():
    s = 'Понял, гляну детали рецепта.'
    assert strip_process_prefix(s, 'Как приготовить борщ по рецепту') == 'гляну детали рецепта.'     # «рецепта» is the question's word: an answer, kept
    assert strip_process_prefix(s, Q) == 'гляну детали рецепта.'                                      # not the question's, not the act's object: content
    assert strip_process_prefix(s) == 'гляну детали рецепта.'
    assert strip_process_prefix('Сейчас уточню по девятой статье.', 'девятая статья налогового кодекса') == ''
    assert strip_process_prefix('Понял, гляну детали статьи.', '21-ая статья налогового кодекса. Что такое') == ''


def test_what_the_cloud_consults_is_no_new_information_with_or_without_the_question():
    """Only «статья» (the coordinator's ruling) is the product of a search: the call's «Понял, гляну детали статьи.» goes either way. A document, a
    source, a text is a real answer («Посмотрю документы.» to «Что вы сделаете первым делом?»)."""
    assert strip_process_prefix('Понял, гляну детали статьи.') == ''
    assert strip_process_prefix('Понял, гляну детали статьи.', Q) == ''
    assert strip_process_prefix('Проверю по материалам и отвечу.') == ''                      # the older filter: «проверю …» to the end of the sentence
    assert strip_process_prefix('Сейчас загляну в статью.') == ''
    assert strip_process_prefix('Сейчас загляну в источник.') == 'Сейчас загляну в источник.'
    assert strip_process_prefix('Сейчас прочитаю материалы и отвечу.') == 'Сейчас прочитаю материалы и отвечу.'
    assert strip_process_prefix('Посмотрю документы.', 'Что вы сделаете первым делом на новом месте?') == 'Посмотрю документы.'
    assert strip_process_prefix('Я читаю книги по вечерам.') == 'Я читаю книги по вечерам.'


def test_a_number_the_question_does_not_have_is_information():
    assert strip_process_prefix('Сейчас вспоминаю статью 218.', 'Что устанавливает статья 218 ГК РФ') == ''
    assert strip_process_prefix('Сейчас вспоминаю статью 219.', 'Что устанавливает статья 218 ГК РФ') == 'Сейчас вспоминаю статью 219.'
    assert strip_process_prefix('Сейчас вспоминаю статью 218.') == 'Сейчас вспоминаю статью 218.'


# --- 8. a partial sentence is withheld, a word that may still grow is not judged ------------------------------------------------------------
def test_a_process_sentence_without_its_end_is_withheld_not_spoken():
    for text in ('Сейчас коротко сформулирую', 'Понял, подумаю как отвечать ровнее', 'Слышу твою оценку, сейчас кратко отвечу на это'):
        assert strip_process_prefix(text, Q) == '', text


def test_a_word_that_may_still_grow_is_not_judged():
    assert strip_process_prefix('Сейчас коротко сформулиру', Q) == 'Сейчас коротко сформулиру'
    assert strip_process_prefix('Сейчас коротко', Q) == 'Сейчас коротко'


def test_a_sentence_that_turns_out_to_be_content_is_released_whole():
    assert strip_process_prefix('Отвечу на ваш', Q) == ''                             # still looks like an announcement: withheld
    assert strip_process_prefix('Отвечу на ваш вопрос', Q) == 'Отвечу на ваш вопрос'


# --- 9. through the controller: the first cue is the answer, whatever the slicing ---------------------------------------------------------------
THROUGH = [   # (the cloud talking about itself, the question, the answer, the stems that must never be spoken)
    ('Сейчас коротко сформулирую.', 'Когда было крещение Руси?', 'Крещение Руси относят к 988 году, когда князь Владимир крестился.',
     ('сформулир', 'коротк')),
    ('Хорошо, посмотрю и отвечу коротко.', 'Сколько планет в Солнечной системе?', 'В Солнечной системе восемь планет.',
     ('посмотрю', 'отвечу', 'коротк')),
    ('Слышу твою оценку, сейчас кратко отвечу на это.', 'Почему небо голубое?',
     'Небо голубое, потому что воздух сильнее рассеивает синий свет.', ('слышу', 'оценк', 'кратко', 'отвечу')),
    ('Секундочку, вспоминаю дату.', 'Когда началась Первая мировая война?', 'Первая мировая война началась в 1914 году.',
     ('вспомина', 'секундочк', 'дату')),
    ('Так, подготовлю краткий ответ.', 'Почему лёд плавает на воде?', 'Лёд плавает на воде, потому что он легче воды.',
     ('подготов', 'кратк', 'ответ')),
    ('Сейчас пересчитаю.', 'Сколько секунд в часе?', 'Три тысячи шестьсот секунд, потому что в минуте их шестьдесят.', ('пересчита',)),
]


@pytest.mark.parametrize('how', ['words', 'chars5', 'chars1'])
@pytest.mark.parametrize('stall,question,body,banned', THROUGH)
def test_the_first_cue_is_the_answer_not_the_cloud_talking_about_itself(stall, question, body, banned, how):
    run = H.stream(question, stall + ' ' + body, how, walk=False)
    assert run.cues, 'the answer after the cloud talking about itself must still be cued'
    for text in run.cues + run.chunks:
        for stem in banned:
            assert stem not in text.casefold(), (stem, text, run.chunks)
    assert H.nospace(''.join(run.chunks)) == H.nospace(body)


@pytest.mark.parametrize('how', ['words', 'chars5', 'chars1'])
def test_a_reply_that_is_only_the_cloud_talking_about_itself_is_cued_nowhere(how):
    run = H.stream('Когда было крещение Руси?', 'Понял, подумаю, как отвечать ровнее и сразу по делу.', how, walk=False)
    assert run.cues == [] and run.chunks == [], (run.cues, run.chunks)


def test_the_owners_call_sentence_by_sentence_slicing_never_speaks_it():
    """«Сейчас коротко сформулирую.» was cued whole, twice. Whatever the slicing of the stream, no cue holds a word of it."""
    answer = 'Сейчас коротко сформулирую. В том, что ресурсы и производство распределяются централизованно по плану, а не рынком.'
    for how in ('words', 'chars5', 'chars1'):
        run = H.stream('Так, значит в чём заключается смысл экономики плановой', answer, how, walk=False)
        assert run.cues, how
        for cue in run.cues + run.chunks:
            assert 'сформулир' not in cue.casefold() and 'коротко' not in cue.casefold(), (how, cue)
        assert H.nospace(''.join(run.chunks)) == H.nospace('В том, что ресурсы и производство распределяются централизованно по плану, а не рынком.')


# --- 10. the controller's other user of the filter -----------------------------------------------------------------------------------------
def test_a_reply_to_the_listener_in_the_middle_of_an_answer_is_chatter():
    from echo_sync.controlled_media import _chatter
    assert _chatter('Слышу твою оценку, сейчас кратко отвечу на это.', 'Когда было крещение Руси')
    assert _chatter('Понял, подумаю, как отвечать ровнее.', 'Когда было крещение Руси')
    assert not _chatter('Крещение Руси относят к 988 году.', 'Когда было крещение Руси')


# --- 11. the class as a matrix: any act verb with a content object stays, with the act's own object goes ---------------------------------------
# Verbs the older phrase filter does not take unconditionally (it strips «проверю …» / «уточню …» to the end of the sentence whatever follows).
MATRIX_VERBS = ['сформулирую', 'расскажу', 'отвечу', 'подумаю', 'найду', 'посмотрю', 'скажу', 'вспоминаю', 'подготовлю', 'повторю', 'дам', 'объясню']
CONTENT = ['рост цен', 'яблоко', 'Менделеева', 'вторую мировую', 'квадратное уравнение', 'сорок два', 'в Москве', 'пять процентов',
           'не знаю', 'что вода мокрая', 'как работает двигатель', 'про Ньютона и его законы', 'в 1914 году', 'за счёт трения', 'им', 'ему']
OWN_OBJECTS = ['ответ', 'формулировку', 'дату', 'детали', 'по делу', 'по сути', 'краткий ответ', 'это', 'информацию по этой теме',
               'коротко', 'точное значение', 'всё']


def test_an_act_verb_with_a_content_object_is_content():
    kept, lost = [], []
    for verb in MATRIX_VERBS:
        for obj in CONTENT:
            sentence = f'{verb.capitalize()} {obj}.'
            (kept if strip_process_prefix(sentence, Q) == sentence else lost).append(sentence)
    assert not lost, lost


def test_an_act_verb_with_the_acts_own_object_is_an_announcement():
    stripped, left = [], []
    for verb in MATRIX_VERBS:
        for obj in OWN_OBJECTS:
            sentence = f'{verb.capitalize()} {obj}.'
            (stripped if strip_process_prefix(sentence + ' ' + BODY, Q) == BODY else left).append(sentence)
    assert not left, left


def test_a_stall_that_is_still_being_said_is_not_a_cue_yet():
    from echo_sync.first_useful import first_cue
    settings = {'preset': 'slow_assistive', 'max_words': 4, 'min_words': 2}
    for partial in ('Сейчас коротко', 'Слышу твою оценку, сейчас кратко', 'Понял, подумаю как отвечать', 'Секундочку, вспоминаю'):
        assert first_cue(partial, Q, settings, final=False, last=False) is None, partial
    assert first_cue('Крещение Руси относят к 988 году', Q, settings, final=True, last=True)


def test_a_character_pymorphy_cannot_describe_never_raises_into_the_wire_reader():
    """pymorphy3 raises on some characters (a Tangut letter). The cloud's text can hold anything: such a sentence is content, never an error."""
    for text in ('Сейчас 𗀀 скажу. Ответ.', 'Скажу 𗀀.', '𗀀', 'Сейчас 𘀀𘀁 сформулирую'):
        out = strip_process_prefix(text, Q)
        assert isinstance(out, str)
    assert strip_process_prefix('Сейчас 𗀀 сформулирую. Ответ.', Q) == 'Сейчас 𗀀 сформулирую. Ответ.'
