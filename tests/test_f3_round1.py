"""Wave F / F3, fix round 1 (the two-lens review of f-flow; the coordinator's rulings 1-6).

1. The guard of the process-sentence class was INVERTED: «Да, подготовлю отчёт к понедельнику.» to «Вы подготовите отчёт к понедельнику?» was
   stripped to '' (then «Нет ответа»). A sentence whose predicate (or its aspect pair) or any content word occurs in the question ANSWERS it.
2. «согласен / слышал / принял …» are acknowledgement words of a whole sentence, never a lead that cuts the stance of an answer.
3. A personal question the router wants verified is not answered "from memory" any more: its first-person frame is stripped and the PUBLIC lookup
   runs on what remains, or it stays unanswered (the watchdog's phrase, never «Ошибка. Повторите вопрос.»).
4. needs_verification knows amounts, rates, limits and legal dates; a settled fact is answered at once, a verify-class question never hears
   "none is needed"; a result is sent when the question is FINAL (a partial decides nothing) and at most once per delegation item.
5. begin_call retires only a STALE answer: a reconnect inside CONVERSATION_GAP_S keeps the portion (a repeat and an ACK work), 12 h later it is retired.
6. One result per delegation item.
"""
import json
import logging
import sqlite3
import time

import pytest

import helpers_s6_fault as F
from echo_sync import timer_policy
from echo_sync.controlled_media import ANSWER_WAIT_SECONDS, CONVERSATION_GAP_S, ControlledMedia
from echo_sync.generator import route_need
from echo_sync.textutil import strip_process_prefix
from helpers_spoken_diagnostics import ANSWER, phrases_heard, run_wire
from test_f3_delegation import Model, first_cue, is_a_result_of_a_search, says_nothing_was_searched
from test_f3_flow import PHONE_SESSION, age_state, db_of, leave_a_portion_waiting, run_call, stored
from test_first_cue_never_silent import Clock, created, done, host_controller
from engine_say import engine_reply


@pytest.fixture(autouse=True)
def decisions_are_logged(caplog):
    caplog.set_level(logging.INFO, logger='echo-sync')


BODY = 'Крещение Руси относят к девятьсот восемьдесят восьмому году.'
Q = 'Когда было крещение Руси'

# ===================================================================================================================================
# 1. A sentence that repeats the question's predicate or content word is the ANSWER (the reviewers' interview pairs)
# ===================================================================================================================================
INTERVIEW = [   # (answer, question): every one is KEPT, whole
    ('Да, подготовлю отчёт к понедельнику.', 'Вы подготовите отчёт к понедельнику?'),
    ('Подготовлю отчёт к понедельнику.', 'Вы подготовите отчёт к понедельнику?'),
    ('Подготовлю.', 'Вы подготовите отчёт к понедельнику?'),
    ('Да, согласен.', 'Вы согласны работать по выходным?'),
    ('Согласен.', 'Вы согласны работать по выходным?'),
    ('Согласна.', 'Вы согласны работать по выходным?'),
    ('Думаю, да. Продавец обязан принять возврат.', 'Можно ли вернуть товар без чека?'),
    ('Думаю, да.', 'Можно ли вернуть товар без чека?'),
    ('Я думаю, да.', 'Можно ли вернуть товар без чека?'),
    ('Скажу да.', 'Можно ли вернуть товар без чека?'),
    ('Понимаю.', 'Вы понимаете, что работа связана с командировками?'),
    ('Да, понимаю.', 'Вы понимаете, что работа связана с командировками?'),
    ('Да, принимаю.', 'Вы принимаете наше предложение?'),
    ('Принимаю.', 'Вы принимаете наше предложение?'),
    ('Учту.', 'Учтёте наши замечания?'),
    ('Сообщу.', 'Вы сообщите, если заметите ошибку?'),
    ('Да, найду время.', 'Найдёте время на встречу завтра?'),
    ('Да, хорошо.', 'Вам удобно в понедельник?'),
    ('Да, хорошо.', 'Вам удобно встретиться в понедельник?'),
    ('Отвечаю коротко и по делу.', 'Как вы отвечаете на вопросы клиентов?'),
    ('Буду отвечать коротко и по делу.', 'Как вы будете отвечать на вопросы комиссии?'),
    ('Посмотрю документы.', 'Что вы сделаете первым делом на новом месте?'),
    ('Сначала разберусь в документах.', 'Что вы сделаете первым делом на новом месте?'),
    ('Посмотрю в кодексе.', 'Где вы посмотрите ставку налога?'),
    ('Расскажу о себе.', 'Расскажите о себе'),               # the as-written rule: the verb of the request is the verb of the answer
]


@pytest.mark.parametrize('answer,question', INTERVIEW)
def test_a_sentence_that_repeats_the_questions_predicate_or_word_is_an_answer_and_stays(answer, question):
    assert strip_process_prefix(answer, question) == answer


def forms(lemma, person, number, tense):
    from echo_sync import ru_alignment as ru
    ru._lemma(lemma)
    with ru._LOCK:
        parse = next((p for p in ru._MORPH.parse(lemma) if p.normal_form == lemma and p.tag.POS in ('INFN', 'VERB')), None)
        out = []
        if parse is not None:
            for tn in tense:
                form = parse.inflect({person, number, tn, 'indc'})
                if form is not None and form.word not in out:
                    out.append(form.word)
    return out


# verbs the older phrase filter does not strip unconditionally, so that the class alone decides
MATRIX = ['подготовить', 'сообщить', 'посмотреть', 'найти', 'объяснить', 'рассказать', 'ответить', 'подумать', 'вспомнить', 'повторить',
          'подсказать', 'назвать', 'сформулировать', 'подобрать', 'выяснить', 'прикинуть']


@pytest.mark.parametrize('lemma', MATRIX)
def test_the_guard_is_about_the_question_for_every_act_verb(lemma):
    mine = forms(lemma, '1per', 'sing', ('futr', 'pres'))
    yours = forms(lemma, '2per', 'plur', ('futr', 'pres'))
    assert mine and yours, lemma
    question = f'Вы {yours[0]} это для нас?'
    unrelated = 'Когда было крещение Руси'
    for first in mine:
        # (a bare «Скажу.» / «Да, скажу.» is the older phrase filter's whole-sentence stall: untouched)
        sentence = f'{first.capitalize()} коротко.'
        assert strip_process_prefix(sentence, question) == sentence, (sentence, question)           # it answers the question
        assert strip_process_prefix(sentence + ' ' + BODY, unrelated) == BODY, sentence             # the same words, nobody asked for them
        assert strip_process_prefix(f'Да, {first} коротко.', unrelated) == f'Да, {first} коротко.'   # «да» is an answer word


def test_the_acts_own_objects_and_the_questions_numbers_are_no_overlap():
    """«статья», «дата», «детали» are the product of the act, and a number of the question is no answer: the call's sentences still go."""
    assert strip_process_prefix('Понял, гляну детали статьи.', '21-ая статья налогового кодекса. Что такое') == ''
    assert strip_process_prefix('Сейчас уточню формулировку.', '21-ая статья налогового кодекса. Что такое') == ''
    assert strip_process_prefix('Сейчас вспоминаю статью 218.', 'Что устанавливает статья 218 ГК РФ') == ''
    assert strip_process_prefix('Сейчас вспоминаю дату.', 'Когда было крещение Руси') == ''
    assert strip_process_prefix('Сейчас коротко сформулирую.', 'В чём заключается смысл экономики плановой') == ''
    assert strip_process_prefix('Слышу твою оценку, сейчас кратко отвечу на это.', 'Зачем вот это вот всё тянуть надо было') == ''


def test_da_is_an_answer_word_like_net_not_a_filler():
    assert strip_process_prefix('Да, слышу.', Q) == 'Да, слышу.'
    assert strip_process_prefix('Да.', Q) == 'Да.'
    assert strip_process_prefix('Думаю, да. Продавец обязан принять возврат.', Q) == 'Думаю, да. Продавец обязан принять возврат.'
    assert strip_process_prefix('Угу.', Q) == '' and strip_process_prefix('Понял, спасибо.', Q) == ''


@pytest.mark.parametrize('question,answer,first', [
    ('Вы подготовите отчёт к понедельнику?', 'Да, подготовлю отчёт к понедельнику.', 'Да, подготовлю'),
    ('Вы согласны работать по выходным?', 'Да, согласен.', 'Да, согласен.'),
    ('Вы согласны работать по выходным?', 'Согласен.', 'Согласен.'),
    ('Можно ли вернуть товар без чека?', 'Думаю, да. Продавец обязан принять возврат.', 'Думаю, да.'),
    ('Вы понимаете, что работа связана с командировками?', 'Да, понимаю.', 'Да, понимаю.'),
])
def test_an_answer_that_repeats_the_question_is_cued_not_reported_as_missing(tmp_path, monkeypatch, question, answer, first):
    """The reviewers' sim: the answer was stripped, nothing was cued and «Нет ответа» came at 9.1 s."""
    async def body(rig):
        model = Model(rig)
        t0, _, _ = await model.question(question, answer, stall=None, delegate=False)
        await rig.advance(ANSWER_WAIT_SECONDS + 2)
        cue = first_cue(rig, t0)
        assert cue is not None and cue[1].startswith(first.rstrip('.')), (cue, rig.timeline())
        assert rig.errors() == []
    run_wire(tmp_path, monkeypatch, body)


# ===================================================================================================================================
# 2. The stance of an answer is not an acknowledgement lead
# ===================================================================================================================================

@pytest.mark.parametrize('answer', ['Согласен, если график известен заранее.', 'Согласна, но только по договорённости.',
                                    'Принял, оплатим в срок.', 'Услышал, поправлю в договоре.'])
def test_the_new_acknowledgement_words_are_not_a_lead_that_cuts_the_stance(answer):
    assert strip_process_prefix(answer, 'Вы согласны работать по выходным?') == answer
    assert strip_process_prefix(answer, Q) == answer


def test_the_old_leads_are_leads_still_and_the_new_words_are_whole_acknowledgements():
    assert strip_process_prefix('Хорошо, на сфере сумма углов больше 180 градусов.', Q) == 'на сфере сумма углов больше 180 градусов.'
    assert strip_process_prefix('Согласен.', Q) == '' and strip_process_prefix('Принял.', Q) == '' and strip_process_prefix('Слышал, спасибо.', Q) == ''


def test_a_stance_is_the_first_cue_through_the_wire(tmp_path, monkeypatch):
    async def body(rig):
        model = Model(rig)
        t0, _, _ = await model.question('Вы согласны работать по выходным?', 'Согласен, если график известен заранее.', stall=None, delegate=False)
        await rig.advance(3)
        cue = first_cue(rig, t0)
        assert cue is not None and cue[1].startswith('Согласен'), (cue, rig.timeline())
    run_wire(tmp_path, monkeypatch, body)


# ===================================================================================================================================
# 4. needs_verification knows amounts, rates, limits and legal dates; the wording of the no-search result
# ===================================================================================================================================
AMOUNT_QUESTIONS = ['Сколько процентов НДС в России?', 'Какой НДС в России?', 'Какой МРОТ в 2026 году?', 'Какой размер МРОТ?',
                    'Какой лимит доходов для упрощёнки?', 'Сколько процентов НДФЛ с зарплаты?', 'До какого числа надо платить налог?',
                    'С какого возраста положена пенсия?', 'Какой срок уплаты НДС?', 'Какая сумма вычета положена на ребёнка?',
                    'Каков размер пособия по уходу за ребёнком?', 'Какой размер госпошлины за регистрацию?', 'Какой страховой взнос платит ИП?']
STILL_SETTLED = ['Когда было крещение Руси?', 'В чём смысл плановой экономики?', 'Сколько планет в Солнечной системе?',
                 'Какой цвет у неба?', 'Что такое налог?', 'Кто написал роман «Война и мир»?', 'Сколько стоит патент для ИП?',
                 'Какие налоги платит ИП на упрощёнке?', 'Почему небо голубое?']


@pytest.mark.parametrize('question', AMOUNT_QUESTIONS)
def test_an_amount_rate_limit_or_legal_date_question_needs_verification(question):
    assert route_need(question, ())


@pytest.mark.parametrize('question', STILL_SETTLED)
def test_a_settled_question_still_does_not(question):
    assert not route_need(question, ())


@pytest.mark.parametrize('question', AMOUNT_QUESTIONS[:6])
def test_a_delegation_for_an_amount_question_gets_the_sources_not_the_no_search_result(tmp_path, monkeypatch, question):
    async def body(rig):
        model = Model(rig)
        t0, got, _ = await model.question(question, 'Ставка двадцать процентов.')
        assert got is not None and is_a_result_of_a_search(got[1]) and not says_nothing_was_searched(got[1]), got
        assert len(rig.lookup_plan.calls) == 1
        assert all('none is needed' not in json.dumps(f, ensure_ascii=False) for _, f in model.results())
    run_wire(tmp_path, monkeypatch, body)


def test_the_no_search_result_says_what_the_coordinator_ruled():
    from echo_sync.native_media_socket import NO_SEARCH_RESULT, context_frames
    assert 'none is needed' not in NO_SEARCH_RESULT
    assert 'Поиск не нужен: это устойчивое знание — ответь сразу сам.' in NO_SEARCH_RESULT
    frame = context_frames({'epoch': 1, 'sources': [], 'marker': '', 'delegation_id': 'd1', 'source_transport': 'delegation', 'no_search': True})
    assert len(frame) == 1 and NO_SEARCH_RESULT == frame[0]['content'][0]['text']


def test_a_settled_fact_still_gets_it_at_once(tmp_path, monkeypatch):
    async def body(rig):
        model = Model(rig)
        t0, got, _ = await model.question('Когда было крещение Руси?', 'Крещение Руси относят к 988 году.')
        assert got is not None and got[0] - t0 < 1.0 and says_nothing_was_searched(got[1]), got
        assert not rig.lookup_plan.calls
    run_wire(tmp_path, monkeypatch, body, lookup=[('slow', 6.0)])


# --- a partial decides nothing; one result per delegation item (the reviewers' sim_partial_then_verify / sim_double_accept) -------------

def delegation(tid, did='d1'):
    return {'type': 'delegation.created', 'item': {'id': did, 'type': 'delegation', 'target': 'client', 'user_bidi_turn_id': tid}}


def results_on(model, did):
    """The RESULTS sent on a delegation item: the first frame of each (a sourced result is several frames of 500 bytes)."""
    return [frame for _, frame in model.results() if frame.get('delegation_item_id') == did
            and frame['content'][0]['text'].startswith('Completed search result:')]


def test_a_delegation_on_a_partial_that_becomes_a_code_article_gets_the_sources_and_only_those(tmp_path, monkeypatch):
    """The partial «Что говорится в девятой статье» is a settled question; the final names the code. The model must never be told
    "no search" first and then given sources on the same item."""
    partial, final = 'Что говорится в девятой статье', 'Что говорится в девятой статье Налогового кодекса?'
    assert not route_need(partial, ()) and route_need(final, ())

    async def body(rig):
        model = Model(rig)
        await rig.feed(created('u1', 'user', 'Что'))
        await rig.feed(created('u1', 'user', partial))
        await rig.feed(delegation('u1'))
        await rig.advance(0.3)
        assert results_on(model, 'd1') == [], 'a partial must not be answered'
        await rig.feed(done('u1', 'user', final))
        await rig.advance(8)
        got = results_on(model, 'd1')
        assert len(got) >= 1 and all(is_a_result_of_a_search(f) for f in got), [f['content'][0]['text'][:60] for f in got]
        assert not any(says_nothing_was_searched(f) for f in got)
        assert len(rig.lookup_plan.calls) == 1
    run_wire(tmp_path, monkeypatch, body)


def test_a_delegation_on_a_partial_of_a_settled_question_is_answered_when_the_question_is_final(tmp_path, monkeypatch):
    async def body(rig):
        model = Model(rig)
        await rig.feed(created('u1', 'user', 'Когда было'))
        await rig.feed(delegation('u1'))
        await rig.advance(0.3)
        assert results_on(model, 'd1') == []
        await rig.feed(done('u1', 'user', 'Когда было крещение Руси?'))
        await rig.advance(0.3)
        got = results_on(model, 'd1')
        assert len(got) == 1 and says_nothing_was_searched(got[0]) and not rig.lookup_plan.calls, got
    run_wire(tmp_path, monkeypatch, body)


def test_a_final_that_repeats_the_partial_releases_the_result_too(tmp_path, monkeypatch):
    async def body(rig):
        model = Model(rig)
        await rig.feed(created('u1', 'user', 'Когда было крещение Руси'))
        await rig.feed(delegation('u1'))
        await rig.advance(0.3)
        assert results_on(model, 'd1') == []
        await rig.feed(done('u1', 'user', 'Когда было крещение Руси'))
        await rig.advance(0.3)
        assert len(results_on(model, 'd1')) == 1
    run_wire(tmp_path, monkeypatch, body)


def test_a_question_accepted_on_its_delegation_and_re_accepted_gets_one_result(tmp_path, monkeypatch):
    """The call's shape for «Когда было крещение Руси»: delegation while the question is a partial (accepted early), final with other words
    (re-accepted): the same delegation item is answered ONCE, and the model's answer is dictated."""
    async def body(rig):
        model = Model(rig)
        await rig.feed(created('u1', 'user', 'Так, ну ладно, когда было крещение'))
        await rig.feed(delegation('u1'))
        await rig.advance(0.4)
        await rig.feed(done('u1', 'user', 'Так, ну ладно, когда было крещение Руси?'))
        await rig.advance(0.4)
        await rig.answer('Крещение Руси относят к 988 году.', tid='a1', parts=1)
        await rig.advance(3)
        assert len(results_on(model, 'd1')) == 1, [f['content'][0]['text'][:50] for f in results_on(model, 'd1')]
        assert rig.spoken() and rig.errors() == [], rig.timeline()
    run_wire(tmp_path, monkeypatch, body)


def test_a_second_sourced_result_is_not_sent_on_the_same_item(tmp_path, monkeypatch):
    """A verify-class question accepted on its delegation and re-accepted with other words: two lookups may run, one result is sent."""
    async def body(rig):
        model = Model(rig)
        await rig.feed(created('u1', 'user', 'Какой НДС'))
        await rig.feed(delegation('u1'))
        await rig.advance(0.5)
        await rig.feed(done('u1', 'user', 'Какой НДС в России?'))
        await rig.advance(8)
        assert len(results_on(model, 'd1')) == 1
    run_wire(tmp_path, monkeypatch, body)


# ===================================================================================================================================
# 3. A personal question the router wants verified: the first-person frame goes, the PUBLIC lookup runs on the rest, or nothing is said
# ===================================================================================================================================
PERSONAL_VERIFY = [   # (question, a word the public query must keep)
    ('Какая сейчас ставка НДС, когда я продаю товар?', 'ставк'),
    ('Что я должен сказать, если спросят про девятую статью НК?', 'статью'),
    ('Какая у меня сейчас ставка по кредиту?', 'ставк'),
    ('Какой у меня размер МРОТ в этом году?', 'мрот'),
]
UNANSWERABLE = ['Какую ставку НДС платит наша компания сейчас, когда я работаю у нас?']
PERSONAL_WORDS = {'я', 'меня', 'мне', 'мой', 'моя', 'моё', 'мои', 'моего', 'моей', 'моих', 'мной'}


@pytest.mark.parametrize('question,keeps', PERSONAL_VERIFY)
def test_a_personal_question_that_needs_verification_is_looked_up_publicly_without_its_personal_frame(tmp_path, monkeypatch, question, keeps):
    assert route_need(question, ()) and not ControlledMedia.public_lookup_allowed(question), 'precondition'

    async def body(rig):
        model = Model(rig)
        t0, got, _ = await model.question(question, 'Ставка НДС двадцать процентов, она общая для всех.')
        assert rig.errors() == [], rig.timeline()
        assert len(rig.lookup_plan.calls) == 1, rig.lookup_plan.calls
        query = rig.lookup_plan.calls[0][1]
        assert ControlledMedia.public_lookup_allowed(query), query
        assert not PERSONAL_WORDS & set(query.casefold().replace('?', ' ').replace(',', ' ').split()), query
        assert keeps in query.casefold(), query
        assert got is not None and is_a_result_of_a_search(got[1]) and not says_nothing_was_searched(got[1]), got
        assert all('none is needed' not in f['content'][0]['text'] for _, f in model.results())
        await rig.advance(3)
        assert first_cue(rig, t0), rig.timeline()
    run_wire(tmp_path, monkeypatch, body)


@pytest.mark.parametrize('question', UNANSWERABLE)
def test_a_personal_question_with_a_personal_remainder_stays_unanswered_without_an_error_phrase(tmp_path, monkeypatch, question):
    assert route_need(question, ()) and not ControlledMedia.public_lookup_allowed(question), 'precondition'

    async def body(rig):
        model = Model(rig)
        await rig.ask(question, tid='u1', delegate=True)
        await rig.advance(0.5)
        await rig.answer('Уточню, какую ставку платит ваша компания.', tid='s1', parts=1)
        await rig.advance(ANSWER_WAIT_SECONDS + 4)
        assert not rig.lookup_plan.calls, 'a personal question must never reach the public lookup'
        assert model.results() == [], 'the model is told nothing: no "none is needed" for a verify-class question'
        assert 'controlled_private_context_required' not in rig.errors()
        assert all('Ошибка' not in text for text in rig.spoken())
        assert rig.errors() == ['controlled_answer_timeout'] and phrases_heard(rig.frames) == [ANSWER], (rig.errors(), rig.timeline())
    run_wire(tmp_path, monkeypatch, body)


def test_the_engine_guard_is_back_to_what_it_was(tmp_path):
    """The 'no_search' bypass is gone: an unverified answer to a verify-class question is refused whatever it calls itself."""
    from echo_sync.engine import EchoEngine, SILENT
    from echo_sync.generator import StreamingAnswer
    question = 'Какая сейчас ставка НДС?'
    assert route_need(question, ())
    results = {}
    for name, answer in {'unverified': StreamingAnswer('Двадцать процентов', retrieval_status='unverified'),
                         'no_search': StreamingAnswer('Двадцать процентов', retrieval_status='no_search'),
                         'source_backed': StreamingAnswer('Двадцать процентов', F.SOURCES, retrieval_status='source_backed')}.items():
        engine = EchoEngine(tmp_path / (name + '.db'), lambda *a, _answer=answer: _answer, settings={'words_per_portion': 3})
        reply = engine_reply(engine, session_id='s', turn_id='q', text=question, request={}, model='m')
        results[name] = reply != SILENT and bool((engine.state('s') or {}).get('chunks'))
    assert results == {'unverified': False, 'no_search': False, 'source_backed': True}, results


# 4.09a personal_volatile is always on: a calendar question gets the honest local phrase; this test guards the model road, so it asks a personal question outside the volatile list
def test_a_personal_question_that_needs_no_verification_still_goes_to_the_model_with_its_own_wording(tmp_path, monkeypatch):
    async def body(rig):
        model = Model(rig)
        t0, got, _ = await model.question('Что у меня записано в заметках на завтра?', 'У меня нет доступа к вашему календарю.')
        assert got is not None and says_nothing_was_searched(got[1]) and not rig.lookup_plan.calls
        text = got[1]['content'][0]['text']
        assert 'none is needed' not in text and 'устойчивое знание' not in text, text      # a personal question is not "stable knowledge"
        await rig.advance(3)
        assert first_cue(rig, t0), rig.timeline()
    run_wire(tmp_path, monkeypatch, body)


# ===================================================================================================================================
# 5. begin_call retires only a STALE answer; a reconnect keeps the portion and lets a repeat and an ACK work
# ===================================================================================================================================
def seeded(age, answer=None, **kw):
    def before(home):
        leave_a_portion_waiting(db_of(home), **({'answer': answer} if answer else {}))
        age_state(db_of(home), age, **kw)
        state = stored(db_of(home))
        return state['chunks'][state['chunk_index']], state
    return before


def test_the_window_is_ten_minutes_the_one_window_of_the_conversation():
    assert CONVERSATION_GAP_S == 600 and not hasattr(timer_policy, 'RECONNECT_WINDOW_S'), 'one window of the same conversation (the redial window and the memory window are one)'


def test_a_redial_eight_seconds_after_a_drop_keeps_the_portion(tmp_path, monkeypatch, caplog):
    async def body(host, before):
        portion, old = before
        now = stored(db_of(host.home))
        assert now['revision'] == old['revision'] and now['chunks'] == old['chunks'] and now['chunk_index'] == old['chunk_index'] and not now['completed']
        assert any('reason=reconnect_kept' in r.getMessage() for r in caplog.records)
        assert not any('reason=new_call' in r.getMessage() for r in caplog.records)
        assert host.spoken() == [], 'opening a call speaks nothing'
    run_call(tmp_path, monkeypatch, body, before=seeded(8))


def test_after_a_short_drop_a_repeat_replays_the_portion(tmp_path, monkeypatch):
    async def body(host, before):
        portion, _ = before
        host.cloud(F.created('r1', 'user', 'Повтори'))
        host.cloud(F.done('r1', 'user', 'Повтори'))
        await host.advance(3)
        assert host.spoken() == [portion], host.spoken()
    run_call(tmp_path, monkeypatch, body, before=seeded(8))


def test_after_a_short_drop_saying_the_portion_confirms_it_and_the_next_one_comes(tmp_path, monkeypatch):
    async def body(host, before):
        portion, old = before
        following = old['chunks'][old['chunk_index'] + 1]
        host.cloud(F.created('r1', 'user', portion.split()[0]))
        host.cloud(F.done('r1', 'user', portion))
        await host.advance(3)
        assert host.spoken() == [following], (host.spoken(), following)
        assert stored(db_of(host.home))['chunk_index'] == old['chunk_index'] + 1
    # integ9: F1 cuts DIRECT_ANSWER by meaning into two portions, so the one that waits is the last; one more sentence keeps a next portion
    # fix-c20: G15 holds the first sentence whole: a third sentence keeps a next portion after the one that waits
    run_call(tmp_path, monkeypatch, body, before=seeded(8, answer=F.DIRECT_ANSWER + ' Её мерой служит масса тела. Её изучает механика.'))


def test_after_a_short_drop_talk_that_is_not_a_repeat_or_a_confirmation_still_says_nothing(tmp_path, monkeypatch):
    async def body(host, before):
        host.cloud(F.created('r1', 'user', 'Так'))
        host.cloud(F.done('r1', 'user', 'Так, проверка, работает ли связь'))
        await host.advance(8)
        assert host.spoken() == [], host.spoken()
    run_call(tmp_path, monkeypatch, body, before=seeded(8))


@pytest.mark.parametrize('seconds,kept', [(CONVERSATION_GAP_S - 5, True), (CONVERSATION_GAP_S + 5, False), (12 * 3600, False)])
def test_a_portion_older_than_the_window_is_retired_a_younger_one_is_kept(tmp_path, monkeypatch, caplog, seconds, kept):
    async def body(host, before):
        portion, old = before
        now = stored(db_of(host.home))
        if kept:
            assert now['revision'] == old['revision'] and not now['completed']
        else:
            assert now['revision'] == old['revision'] + 1 and now['completed'] and now['chunks'] == []
            assert now['history'][-1]['status'] == 'interrupted'
        assert any(('reason=reconnect_kept' if kept else 'reason=new_call') in r.getMessage() for r in caplog.records)
    run_call(tmp_path, monkeypatch, body, before=seeded(seconds))


def test_twelve_hours_later_a_repeat_says_nothing(tmp_path, monkeypatch):
    async def body(host, before):
        host.cloud(F.created('r1', 'user', 'Повтори'))
        host.cloud(F.done('r1', 'user', 'Повтори'))
        await host.advance(3)
        assert host.spoken() == []
    run_call(tmp_path, monkeypatch, body, before=seeded(12 * 3600))


def test_without_issued_at_the_entry_time_decides(tmp_path):
    path = tmp_path / 'controlled-state.sqlite3'
    leave_a_portion_waiting(path)
    age_state(path, 8, keep_issued_at=False)
    c = ControlledMedia(path, session_id=PHONE_SESSION, clock=Clock(200.0), **F.HOST_KWARGS)
    revision = c.state()['revision']
    c.begin_call()
    assert c.state()['revision'] == revision
    path2 = tmp_path / 'second.sqlite3'
    leave_a_portion_waiting(path2)
    age_state(path2, 12 * 3600, keep_issued_at=False)
    c2 = ControlledMedia(path2, session_id=PHONE_SESSION, clock=Clock(200.0), **F.HOST_KWARGS)
    c2.begin_call()
    assert c2.state()['completed']


def test_an_answer_whose_question_was_never_answered_is_always_retired(tmp_path):
    path = tmp_path / 'controlled-state.sqlite3'
    leave_a_portion_waiting(path)
    db = sqlite3.connect(str(path))
    state = json.loads(db.execute('SELECT state FROM sessions WHERE session_id=?', (PHONE_SESSION,)).fetchone()[0])
    state['pending_turn'] = 'some-turn'
    db.execute('UPDATE sessions SET state=? WHERE session_id=?', (json.dumps(state, ensure_ascii=False), PHONE_SESSION))
    db.commit()
    db.close()
    c = ControlledMedia(path, session_id=PHONE_SESSION, clock=Clock(200.0), **F.HOST_KWARGS)
    c.begin_call()
    assert not c.state().get('pending_turn') and c.state()['completed']


def test_a_clock_that_runs_backwards_never_keeps_a_portion(tmp_path):
    path = tmp_path / 'controlled-state.sqlite3'
    leave_a_portion_waiting(path)
    age_state(path, -3600)                                           # issued an hour in the FUTURE of this machine's clock
    c = ControlledMedia(path, session_id=PHONE_SESSION, clock=Clock(200.0), **F.HOST_KWARGS)
    c.begin_call()
    assert c.state()['completed']
