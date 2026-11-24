"""c8 (candidate 7 re-measure, 3 Nov 19:51): the next root causes.

1. w3_01: «Вопрос получается двадцать первая статья налогового кодекса» -> lookup sources_unrelated -> the spoken «Не нашёл. Повторите вопрос.»
   (and KeylessMCPError twice earlier). Rule: when the public lookup fails, times out or returns only unrelated sources, the model is told
   through the same delegation-result channel that no source is available and to answer from its own knowledge with a short hedge as the
   first words («По памяти: …»), never inventing exact rates, sums or dates; its answer is cued normally; «Не нашёл» is said only when the
   model then gives nothing either.
2. w4_07: a follow-up question built from the answer's own words while a portion waits was a try at the answer (integ9 'attempt_answer_words').
   An utterance that opens with an interrogative or ends with «?» and is not a contiguous run of the answer's words is a question.
3. cc4180d's remaining rules in _next_ticket: an aspect noun makes a two-noun line a ticket only as its head; «Билет …» is the exam's unit,
   no ticket; «показатель» is an aspect.
"""
import json

import pytest

import helpers_s6_ack as H
import helpers_s6_fault as F
from echo_sync.classifier import QUESTION, analyze
from echo_sync.native_media_socket import context_frames
from helpers_spoken_diagnostics import EVERY_PHRASE, LOOKUP_EMPTY, phrases_heard, responses, run_wire
from engine_say import engine_reply

PROD = H.PROD_SETTINGS


def decide(text, state):
    return analyze(text, state, [], PROD)


# =====================================================================================================================================
# 1. a lookup with no source: the answer from memory, hedged
# =====================================================================================================================================

FROM_MEMORY = 'По памяти: статья 218 устанавливает основания приобретения права собственности.'


def sent_to_model(rig):
    return [json.loads(payload) for kind, payload in rig.source.frames if kind == 'E']


def model_texts(rig):
    return [part.get('text', '') for frame in sent_to_model(rig) for part in frame.get('content', ())]


@pytest.mark.parametrize('mode', ['raise', 'hang', 'empty', 'garbage'])
def test_a_failed_lookup_tells_the_model_to_answer_from_memory_with_a_hedge_and_says_nothing_yet(tmp_path, monkeypatch, mode):
    async def body(rig):
        await rig.ask(F.LOOKUP_QUESTION)
        await rig.advance(9 if mode == 'hang' else 1)          # the lookup's 8 s budget when it hangs
        assert phrases_heard(rig.frames) == [] and rig.errors() == [], rig.timeline()
        told = model_texts(rig)
        assert len(told) == 1 and 'По памяти:' in told[0] and 'точно не знаю' in told[0], told
        assert F.LOOKUP_QUESTION not in told[0], 'no question text and no source goes in the no-source result'
    run_wire(tmp_path, monkeypatch, body, lookup=[mode])


@pytest.mark.parametrize('mode', ['raise', 'empty'])
def test_the_hedged_answer_from_memory_is_cued_like_any_answer(tmp_path, monkeypatch, mode):
    async def body(rig):
        await rig.ask(F.LOOKUP_QUESTION)
        await rig.advance(1)
        await rig.answer(FROM_MEMORY)
        await rig.advance(4)
        heard = [r['text'] for r in responses(rig.frames)]
        assert heard and heard[0] not in EVERY_PHRASE and heard[0].startswith('Статья 218'), rig.timeline()
        state = rig.controller.state()
        assert 'памяти' not in ' '.join(heard).casefold() and 'памяти' not in state['answer'].casefold(), (heard, state['answer'])
        assert rig.errors() == [], rig.timeline()
        assert state['retrieval_status'] == 'unsourced'
    run_wire(tmp_path, monkeypatch, body, lookup=[mode])


@pytest.mark.parametrize('answer', ['Без проверки: статья 218 устанавливает основания приобретения права собственности.',
                                    'Насколько помню, статья 218 устанавливает основания приобретения права собственности.'])
def test_every_hedge_form_is_kept_off_the_cue(tmp_path, monkeypatch, answer):
    """C8 ruling: the listener repeats every portion aloud in front of the examiner - the hedge is the model's, never spoken."""
    async def body(rig):
        await rig.ask(F.LOOKUP_QUESTION)
        await rig.advance(1)
        await rig.answer(answer)
        await rig.advance(4)
        heard = [r['text'] for r in responses(rig.frames)]
        assert heard and heard[0].startswith('Статья 218'), rig.timeline()
        assert rig.controller.state()['answer'].startswith('Статья 218'), rig.controller.state()['answer']
    run_wire(tmp_path, monkeypatch, body, lookup=['empty'])


def test_an_unhedged_answer_from_memory_to_a_must_verify_question_is_cued_too(tmp_path, monkeypatch):
    """The C8 ruling refused it («Не нашёл» after the wait). Measured on candidate 12 (w3_01): 30 s of silence, then «Не нашёл», for a text the listener
    would have heard word for word had the model opened with the hedge, which the cue never carries. «Не нашёл» is for a model that gives nothing."""
    async def body(rig):
        await rig.ask(F.LOOKUP_QUESTION)
        await rig.advance(1)
        await rig.answer(F.LOOKUP_ANSWER)
        await rig.advance(4)
        assert [r['text'] for r in responses(rig.frames)], rig.timeline()
        assert rig.controller.state()['retrieval_status'] == 'unsourced', rig.timeline()
        await rig.advance(16)
        assert phrases_heard(rig.frames) == [], rig.timeline()
    run_wire(tmp_path, monkeypatch, body, lookup=['empty'])


@pytest.mark.parametrize('mode', ['raise', 'empty'])
def test_not_found_is_said_only_when_the_model_then_gives_nothing_either(tmp_path, monkeypatch, mode):
    async def body(rig):
        t0 = rig.now()
        await rig.ask(F.LOOKUP_QUESTION)
        await rig.advance(30)
        assert phrases_heard(rig.frames) == [LOOKUP_EMPTY], rig.timeline()
        assert rig.errors() == ['controlled_sources_unavailable'], rig.timeline()
        heard = responses(rig.frames)
        assert heard[0]['start'] - t0 <= 20, 'the plain answer wait after the no-source result, not the 20 s budget of a sourced answer'
    run_wire(tmp_path, monkeypatch, body, lookup=[mode])


def test_the_model_that_delegated_is_told_on_the_item_of_its_delegation(tmp_path, monkeypatch):
    async def body(rig):
        await rig.ask(F.LOOKUP_QUESTION, delegate=True)
        await rig.advance(2)
        frames = sent_to_model(rig)
        assert [f['type'] for f in frames] == ['delegation.context.append'], frames
        assert frames[0]['delegation_item_id'].startswith('d-') and frames[0]['channel'] == 'speakable'
        assert 'По памяти:' in frames[0]['content'][0]['text']
    run_wire(tmp_path, monkeypatch, body, lookup=['empty'])


def test_unrelated_sources_take_the_answer_from_memory_path_too(tmp_path):
    """w3_01: every row about something else (sources_unrelated) is no source: the model answers from memory, hedged (pinned on the wire by
    test_e3c_lookup.test_a_row_that_conflicts_takes_the_answer_from_memory_path_on_the_wire)."""
    from test_e3c_lookup import NEGATIVE_PAIRS, lookup_question
    c = lookup_question(tmp_path, NEGATIVE_PAIRS[0][1])
    assert c.grounding(c.epoch, [{'url': 'https://example.org/219', 'text': NEGATIVE_PAIRS[0][2]}]) == [] and not c.grounded
    c.provider({'type': 'delegation.created', 'item': {'id': 'd1', 'type': 'delegation', 'target': 'client', 'user_bidi_turn_id': c.question_id}})
    told = c.without_source(c.epoch,'failed')
    assert [(a['type'], a['why'], a['sources'], a['delegation_id']) for a in told] == [('context', 'unsourced', [], 'd1')], told
    assert c.source_missing and c.direct_content


def test_without_the_hedge_a_number_the_question_does_not_have_is_refused(tmp_path):
    """The owner's rule of c8: «never inventing exact rates, sums or dates». Lifted for plain wording, it stands for what the question did not bring."""
    from echo_sync.engine import EchoEngine, SILENT
    from echo_sync.generator import StreamingAnswer
    question = 'Что устанавливает статья 21 Налогового кодекса?'
    results = {}
    for name, text in {'its_own_number': 'Статья 21 — права налогоплательщиков.', 'a_new_year': 'Её ввели в тысяча девятьсот двадцатом году.',
                       'a_new_sum': 'Штраф 500 рублей.'}.items():
        answer = StreamingAnswer(text, retrieval_status='unsourced', raw_text=text)
        engine = EchoEngine(tmp_path / (name + '.db'), lambda *a, _answer=answer: _answer, settings={'words_per_portion': 3})
        reply = engine_reply(engine, session_id='s', turn_id='q', text=question, request={}, model='m')
        results[name] = reply != SILENT and bool((engine.state('s') or {}).get('chunks'))
    assert results == {'its_own_number': True, 'a_new_year': False, 'a_new_sum': False}, results


def test_the_no_source_result_asks_for_the_hedge_and_no_invented_numbers():
    frames = context_frames({'epoch': 1, 'sources': [], 'marker': '', 'delegation_id': 'd1', 'source_transport': 'delegation',
                             'no_search': True, 'why': 'unsourced'})
    assert len(frames) == 1 and frames[0]['channel'] == 'speakable' and frames[0]['delegation_item_id'] == 'd1'
    text = frames[0]['content'][0]['text']
    assert text.startswith('Completed search result') and 'No more result is pending' in text
    assert '«По памяти:' in text and 'точно не знаю' in text
    assert len(text.encode('utf-8')) <= 500, 'one context frame carries at most 500 UTF-8 bytes'


@pytest.mark.parametrize('text, cued', [
    ('Статья 218 устанавливает основания.', 'Статья 218 устанавливает основания.'),
    ('По памяти: статья 218.', 'Статья 218.'),
    ('без проверки, статья 218.', 'Статья 218.'),
    ('Насколько помню, статья 218.', 'Статья 218.'),
    ('Насколько я помню, это права налогоплательщиков.', 'Это права налогоплательщиков.'),
    ('По статье 218 права возникают так.', 'По статье 218 права возникают так.'),
    ('Насколько это важно, сказать трудно.', 'Насколько это важно, сказать трудно.'),
    ('По', ''), ('По памяти', ''), ('Без про', ''), ('Насколько', ''), ('Насколько я по', ''), ('', ''),
])
def test_the_hedge_is_kept_off_the_cue_and_a_hedge_still_arriving_waits(text, cued):
    from echo_sync.generator import hedged, unhedged
    assert unhedged(text) == cued
    assert hedged(text) == (text != cued and cued != '')


def test_the_engine_takes_an_unsourced_answer_to_a_verify_question_with_or_without_the_hedge(tmp_path):
    from echo_sync.engine import EchoEngine, SILENT
    from echo_sync.generator import StreamingAnswer, route_need
    question = 'Что устанавливает статья 21 Налогового кодекса?'
    assert route_need(question, ())
    results = {}
    model = 'По памяти: права налогоплательщиков.'
    for name, answer in {'hedged': StreamingAnswer('Права налогоплательщиков.', retrieval_status='unsourced', raw_text=model),
                         'bare': StreamingAnswer('Права налогоплательщиков.', retrieval_status='unsourced',
                                                 raw_text='Права налогоплательщиков.'),
                         'unverified': StreamingAnswer('Права налогоплательщиков.', retrieval_status='unverified', raw_text=model)}.items():
        engine = EchoEngine(tmp_path / (name + '.db'), lambda *a, _answer=answer: _answer, settings={'words_per_portion': 3})
        reply = engine_reply(engine, session_id='s', turn_id='q', text=question, request={}, model='m')
        results[name] = reply != SILENT and bool((engine.state('s') or {}).get('chunks'))
    assert results == {'hedged': True, 'bare': True, 'unverified': False}, results


def test_a_personal_question_still_never_reaches_the_public_lookup(tmp_path, monkeypatch):
    async def body(rig):
        await rig.ask('Какая у меня зарплата в этом месяце?')
        await rig.advance(10)
        assert not rig.lookup_plan.calls, 'a personal question must never reach the public lookup'
        assert not rig.controller.source_missing, 'nothing was looked up, so nothing is «not found»'
    run_wire(tmp_path, monkeypatch, body, lookup=['empty'])


# =====================================================================================================================================
# 2. a follow-up question built from the answer's own words is a question
# =====================================================================================================================================

PAINTING = ['Картину «Утро стрелецкой казни»', 'написал Василий Суриков.', 'Кто на ней: стрельцы перед казнью.']
PAINTING_WAITS = {'schema': 2, 'revision': 3, 'question': 'Расскажите о картине «Утро стрелецкой казни»', 'answer': ' '.join(PAINTING),
                  'chunks': PAINTING, 'chunk_index': 1, 'completed': False, 'pending_turn': None, 'history': []}


@pytest.mark.parametrize('text', ['Кто написал картину Утро стрелецкой казни?', 'Кто написал картину «Утро стрелецкой казни»',
                                  'А кто написал картину «Утро стрелецкой казни»?'])
def test_a_question_made_of_the_answers_words_out_of_their_order_is_a_question(text):
    decision = decide(text, PAINTING_WAITS)
    assert decision.kind == QUESTION, decision


@pytest.mark.parametrize('text', ['кто на ней стрельцы?', 'Кто на ней: стрельцы перед казнью', 'картину утро стрелецкой казни?'])
def test_a_run_of_the_answers_words_in_their_order_stays_a_try_even_as_a_question(text):
    """S6: a partial or wrong repeat of a LATER portion changes nothing - it follows the portion's word order."""
    decision = analyze(text, PAINTING_WAITS, [], PROD, diagnose=True)
    assert decision.kind != QUESTION, decision


# =====================================================================================================================================
# 3. cc4180d's remaining rules in _next_ticket
# =====================================================================================================================================

ANSWER_WAITS = {'schema': 2, 'revision': 3, 'question': 'Приведите пример',
                'answer': '«касса», «банк», «поставщики». Вот простой пример. Купили товар за наличные на 1000 рублей.',
                'chunks': ['«касса», «банк», «поставщики».', 'Вот простой пример.', 'Купили товар за наличные на 1000 рублей.'],
                'chunk_index': 0, 'completed': False, 'pending_turn': None, 'history': []}


@pytest.mark.parametrize('text', ['Билет номер семнадцать первой части', 'Билет по экономике предприятия', 'Билеты по экономике предприятия'])
def test_the_exams_unit_at_the_head_is_no_ticket(text):
    assert decide(text, ANSWER_WAITS).kind != QUESTION


@pytest.mark.parametrize('text', ['Фильм про историю.', 'Телефон для примера.'])
def test_an_aspect_noun_that_is_not_the_head_does_not_make_a_two_noun_line_a_ticket(text):
    assert decide(text, ANSWER_WAITS).kind != QUESTION


@pytest.mark.parametrize('text', ['Показатели рентабельности.', 'Методы ценообразования.', 'Кредитная история заёмщика.'])
def test_an_aspect_head_makes_a_two_noun_line_a_ticket(text):
    decision = decide(text, ANSWER_WAITS)
    assert (decision.kind, decision.reason) == (QUESTION, 'topic_while_waiting'), decision


# =====================================================================================================================================
# Owner call 20:10 (candidate 7, trace echo_calls\20261103-201019-72c65a267b59.jsonl): colloquial Russian puts the question word at the
# END of the clause; these were silent/unrelated_speech. A question word that ends its clause, or is followed only by a copula / auxiliary
# («сколько будет», «это что», «про что», «к чему относится», «кто такой») is a question wherever it stands; in an utterance of several
# sentences the sentence carrying it is the question - while a portion waits too, when it names something the portion does not.
# =====================================================================================================================================

SMALL_TALK_WAITS = {'schema': 2, 'revision': 30, 'question': 'Ну что, как дела? Что-то слышишь меня', 'answer': 'Да, слышу хорошо.',
                    'chunks': ['Да, слышу хорошо.'], 'chunk_index': 0, 'completed': False, 'pending_turn': None, 'history': []}
CALL_2010_STATES = {'idle': None, 'waiting': SMALL_TALK_WAITS}

LATE_QUESTIONS = (
    'Все, славно, отлично. Че там, дважды два сколько будет',
    '5 и 5 сколько будет',
    'Так, план счетов , семьдесят первый счет, это что? Про что счет?',
    'А я сейчас всем говорю. Я не уверен, что сейчас вечером станет шесть. Так, план счетов , семьдесят первый счет, это что? Про что счет? '
    'Сейчас скажу',
    '71 план счетов про что?',
    '71 план счетов про что? Блядь, не работает.',
    'семьдесят первый план счетов про что',
    '71-й счет у нас относится к чему относится 71-й счет',
    'Семьдесят первый счёт это что',
    'Кант кто такой',
)


@pytest.mark.parametrize('state', list(CALL_2010_STATES))
@pytest.mark.parametrize('text', LATE_QUESTIONS)
def test_a_question_word_at_the_end_of_the_clause_asks(text, state):
    for diagnose in (False, True):
        decision = analyze(text, CALL_2010_STATES[state], [], PROD, diagnose=diagnose)
        assert decision.kind == QUESTION, (state, decision)


NOT_LATE_QUESTIONS = (            # each a non-question on 9795a77 too (the question word is past the window), and it stays one
    'Я не уверен, что сейчас вечером станет шесть.',
    'Это как бы не то.',
    'Я понял, про что ты.',
    'Там он чуть-чуть десять минут проехать, и мы приедем там, где мы забирали',
    'Он у меня вчера спросил, сколько будет.',
    'Сегодня было гораздо лучше, чем было.',
    'Мы потом посмотрим, когда будет.',
    'Мы всё сделаем так, как было.',
    'Мы сделали то, что было.',
)


@pytest.mark.parametrize('state', list(CALL_2010_STATES))
@pytest.mark.parametrize('text', NOT_LATE_QUESTIONS)
def test_reported_speech_relative_clauses_and_comparisons_still_ask_nothing(text, state):
    for diagnose in (False, True):
        decision = analyze(text, CALL_2010_STATES[state], [], PROD, diagnose=diagnose)
        assert decision.kind != QUESTION, (state, decision)


def test_the_question_asked_starts_with_the_sentence_that_carries_it():
    decision = decide('71 план счетов про что? Блядь, не работает.', SMALL_TALK_WAITS)
    assert decision.kind == QUESTION and decision.question.startswith('71 план счетов про что?'), decision


def test_a_late_question_word_made_only_of_the_waiting_portions_words_does_not_retire_it():
    waits = {**SMALL_TALK_WAITS, 'answer': 'Пять и пять будет десять.', 'chunks': ['Пять и пять будет десять.']}
    decision = decide('пять и пять будет сколько', waits)
    assert decision.kind != QUESTION, decision


# =====================================================================================================================================
# Candidate 8 audit, ruling B: data that changes is never answered from memory when the lookup gives no source
# =====================================================================================================================================
from echo_sync.generator import CHANGES, route_need  # noqa: E402

CURRENT_DATA = ('Какая сейчас ставка НДС?', 'Какой МРОТ в этом году?', 'До какого числа платить НДФЛ?', 'Какой штраф за превышение скорости?',
                'Какой курс доллара сегодня?', 'Какие последние изменения в Налоговом кодексе?', 'Какой лимит доходов на упрощёнке в 2026 году?',
                'Сколько составляет страховой взнос за себя?', 'Действующая редакция закона о защите прав потребителей')
STABLE = ('Что устанавливает статья 218 ГК РФ?', 'Так, что такое пятнадцатая статья Налогового кодекса', 'Как называется статья 21 НК РФ?',
          'Вопрос получается двадцать первая статья налогового кодекса')


@pytest.mark.parametrize('question', CURRENT_DATA)
def test_a_question_for_data_that_changes_is_current_data(question):
    assert route_need(question)==CHANGES, question


@pytest.mark.parametrize('question', STABLE)
def test_a_stable_reference_is_no_current_data(question):
    assert route_need(question)=="lookup", question


def test_an_elliptical_follow_up_asks_what_the_question_before_it_asked():
    assert route_need('А сколько?', [{'question': 'Какая ставка НДФЛ?'}])==CHANGES
    assert route_need('А сколько?', [{'question': 'Что устанавливает статья 218 ГК РФ?'}])!=CHANGES


@pytest.mark.parametrize('question', ['Какая сейчас ставка НДС?', 'Какой лимит доходов на упрощёнке в 2026 году?'])
def test_no_source_for_current_data_leaves_the_honest_not_found(tmp_path, question):
    from test_e3c_lookup import lookup_question
    c = lookup_question(tmp_path, question)
    assert c.grounding(c.epoch, []) == [] and not c.grounded
    c.provider({'type': 'delegation.created', 'item': {'id': 'd1', 'type': 'delegation', 'target': 'client', 'user_bidi_turn_id': c.question_id}})
    assert c.without_source(c.epoch,'failed') is None                        # the transport says «Не нашёл» (controlled_sources_unavailable)
    assert not c.source_missing and not c.direct_content


@pytest.mark.parametrize('mode', ['raise', 'empty'])
def test_a_rate_question_whose_lookup_fails_is_not_found_at_once_and_the_model_is_never_told_to_answer_from_memory(tmp_path, monkeypatch, mode):
    async def body(rig):
        await rig.ask('Какая сейчас ставка НДС?')
        await rig.advance(2)
        assert phrases_heard(rig.frames) == [LOOKUP_EMPTY], rig.timeline()
        assert not any('По памяти' in text for text in model_texts(rig)), model_texts(rig)
    run_wire(tmp_path, monkeypatch, body, lookup=[mode])


@pytest.mark.parametrize('question', list(CURRENT_DATA) + ['Какой тариф на воду?', 'Какой порог по выручке для упрощёнки?', 'Какие изменения в законе о НДС?'])
def test_route_need_is_one_verdict_data_that_changes_is_always_a_lookup(question):
    """Merge route 16.11: ``route_need`` is the one verdict (needs_verification and needs_current_data used to answer the same question twice, and
    the second one only under fast_call): a question whose answer changes is never ``''`` - it needs a source on every route."""
    assert route_need(question) == CHANGES, question
    assert route_need(question, [{'question': 'Что такое вода?'}]) == CHANGES, question


def test_route3_one_rule_for_a_lookup_that_cannot_be_had_both_sides(tmp_path):
    """route (16.11): ``without_source`` is the one rule: a personal question that needs verification goes to the public search on its impersonal remainder (``'refused'``), a stale epoch gives no verdict
    on either side, and the search that gave no source goes to memory, hedged, where the model can be told (``'failed'``)."""
    from test_e3c_lookup import asked, delegation
    c, _ = asked(tmp_path, 'Какая у меня сейчас ставка по кредиту?')
    assert c.without_source(c.epoch + 1, 'refused') is None and c.without_source(c.epoch + 1, 'failed') is None
    told = c.without_source(c.epoch, 'refused')
    assert told and told[0]['type'] == 'lookup' and 'у меня' not in told[0]['lookup_question'], told      # the first-person frame stays home
    (tmp_path / 'b').mkdir()
    c2, _ = asked(tmp_path / 'b', 'Что устанавливает статья 21 Налогового кодекса?')
    c2.provider(delegation('u1'))
    told = c2.without_source(c2.epoch, 'failed')
    assert [a['why'] for a in told] == ['unsourced'] and c2.source_missing
