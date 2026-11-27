"""Wave F / F3, items 2 and 4 (the owner's REAL call of 3 Nov 09:55, call abcc139fe874): the model's request for a search is answered at
once when there is nothing to search, and a personal question is never told to the listener as «Ошибка. Повторите вопрос.».

The real chain ControlledMedia -> NativeMediaSocket on the virtual-time rig of helpers_s6_fault (fakes only at the boundary: SAPI, lookup,
helper pipe, clock). The cloud model is the ``Model`` below: the trace of the call shows GPT-Live asking the client for a search for many
turns of the listener (13 ``delegation.created`` in its 32 turns), saying a short stall while it waits («Уточню дату.») and going on with its
answer only once the RESULT of that delegation - a ``delegation.context.append`` frame on the same item - has reached it.

Sections: 1. settled facts are not delegated slowly (item 4); 2. a personal question is never an error for the listener (item 2).
"""
import json

import pytest

import helpers_s6_fault as F
from echo_sync.controlled_media import ANSWER_WAIT_SECONDS, ControlledMedia
from echo_sync.generator import route_need
from helpers_spoken_diagnostics import ANSWER, phrases_heard, run_wire
from test_first_cue_never_silent import created, done

# Questions the router keeps on the model-knowledge route (route_need False): the call's own and new wordings and topics.
NO_SEARCH_QUESTIONS = [
    'Когда было крещение Руси?', 'В чём смысл плановой экономики?',
    'Почему небо голубое?', 'Кто написал роман «Война и мир»?', 'Что такое фотосинтез?',
    'Как работает солнечная батарея?', 'Зачем нужна атмосфера Земле?', 'Сколько планет в Солнечной системе?',
]
# Questions that need a search: a code article, a rate, «сейчас», the current law.
VERIFY_QUESTIONS = [
    F.LOOKUP_QUESTION, 'Что говорится в девятой статье Налогового кодекса?', 'Какая сейчас ставка НДС?', 'Какой курс доллара к рублю?',
    'Что изменилось в действующем законе о защите прав потребителей?',
]
# The privacy gate (ControlledMedia.public_lookup_allowed) refuses these.
PERSONAL_QUESTIONS = [
    'Что у меня в календаре на завтра?',                                                       # the pin of the two old tests
    # the call's own: read as personal because of «когда я слова говорю» - and answered with «Ошибка. Повторите вопрос.»
    'почему нельзя настроить как-то, чтобы ты прям мгновенно отвечал, суфлировал, когда я слова говорю, ты же полный ответ можешь уже '
    'сформулировать и держать его, и просто смотреть по токенам, по звукам, что обратно приходит в транскрибации расшифровывается',
    'Где я оставил свои ключи?', 'Что мой врач сказал про анализы?', 'Расскажи обо мне что-нибудь.',
]
# (A personal question that the router also wants verified - «Какая у меня сейчас ставка по кредиту?» - is not answered from the model's memory any
# more: tests/test_f3_round1.py, section 3.)


class Model:
    def __init__(self, rig, latency=1.5):
        self.rig, self.latency, self.stamps = rig, latency, []
        original = rig.source.send

        async def send(kind, payload=b''):
            self.stamps.append((rig.now(), kind, payload))
            await original(kind, payload)
        rig.source.send = send

    def results(self):
        """(when, frame) of every context frame the wire sent up to the cloud: the results of its delegations and the session appends."""
        out = []
        for when, kind, payload in self.stamps:
            if kind == 'E':
                frame = json.loads(payload.decode('utf-8'))
                if frame.get('type') in ('delegation.context.append', 'session.context.append'):
                    out.append((when, frame))
        return out

    async def result_for(self, did, within=60):
        end = self.rig.now() + within
        while self.rig.now() < end:
            hit = next(((when, frame) for when, frame in self.results() if frame.get('delegation_item_id') == did), None)
            if hit:
                return hit
            await self.rig.advance(0.05)
        return None

    async def question(self, text, answer, *, tid='u1', stall='Уточню дату.', delegate=True):
        """The listener's question (final at ``t0``), the model's delegation and stall, then its answer ``latency`` s after the result of the
        delegation reached it. Returns (t0, the result as (when, frame) or None, when the model began to answer or None)."""
        rig = self.rig
        t0 = rig.now()
        await rig.ask(text, tid=tid, delegate=delegate)
        await rig.advance(0.5)
        if stall:
            await rig.answer(stall, tid='s' + tid, parts=1)
        got = None
        if delegate:
            got = await self.result_for('d-' + tid)
            if got is None:
                return t0, None, None
        await rig.advance(self.latency)
        began = rig.now()
        await rig.answer(answer, tid='a' + tid)
        return t0, got, began


def first_cue(rig, since):
    """(when, text) of the first cue the phone was given after ``since``, or None."""
    for frame in rig.frames:
        if frame.type == 'response.audio_transcript.delta' and frame.t >= since:
            return frame.t, frame.data['delta']
    return None


def is_a_result_of_a_search(frame):
    return 'Completed search result: source data' in frame['content'][0]['text']


def says_nothing_was_searched(frame):
    text = frame['content'][0]['text']
    return 'no search' in text.casefold() and 'source data' not in text and ('Поиск не нужен' in text or 'Поиска для этого вопроса нет' in text)


# ===================================================================================================================================
# 1. Settled facts are not delegated slowly (item 4)
# ===================================================================================================================================

@pytest.mark.parametrize('question', NO_SEARCH_QUESTIONS)
def test_the_delegation_for_a_settled_fact_is_answered_at_once_and_no_lookup_runs(tmp_path, monkeypatch, question):
    """The call: «Когда было крещение Руси» - the model said «Уточню дату.» and waited for a lookup; its answer, and the first cue, came
    6.3 s after the question. A question the router does not send to a lookup (route_need False) is answered from the model's own
    knowledge at once, through the SAME channel a finished lookup uses; the (slow) lookup never runs."""
    assert not route_need(question, ()), 'precondition: the router keeps this one on the model-knowledge route'

    async def body(rig):
        model = Model(rig)
        t0, got, began = await model.question(question, 'Крещение Руси традиционно относят к 988 году.')
        assert got is not None, 'the model waited for ever for the result of its delegation'
        when, frame = got
        assert when - t0 < 1.0, f'the delegation was answered {when - t0:.2f}s after the question'
        assert frame['type'] == 'delegation.context.append' and frame['delegation_item_id'] == 'd-u1'   # the channel of a finished lookup
        assert frame['channel'] == 'speakable' and frame['content'][0]['type'] == 'input_text'
        assert says_nothing_was_searched(frame), frame
        assert not rig.lookup_plan.calls, 'a settled fact must not wait for a public lookup'
        await rig.advance(2)
        cue = first_cue(rig, t0)
        assert cue and cue[0] - t0 < 4.0, (cue, rig.timeline())
        assert rig.errors() == []
    run_wire(tmp_path, monkeypatch, body, lookup=[('slow', 6.0)])


@pytest.mark.parametrize('question', VERIFY_QUESTIONS)
def test_a_question_that_route_need_keeps_the_lookup(tmp_path, monkeypatch, question):
    assert route_need(question, ()), 'precondition: the router wants a search for this one'

    async def body(rig):
        model = Model(rig)
        t0, got, began = await model.question(question, 'Статья 218 устанавливает основания приобретения права собственности.')
        assert got is not None
        when, frame = got
        assert is_a_result_of_a_search(frame) and frame['delegation_item_id'] == 'd-u1' and not says_nothing_was_searched(frame), frame
        assert len(rig.lookup_plan.calls) == 1, rig.lookup_plan.calls
        await rig.advance(3)
        assert first_cue(rig, t0), rig.timeline()
    run_wire(tmp_path, monkeypatch, body)


def test_a_model_that_answers_before_the_result_reached_it_is_still_dictated(tmp_path, monkeypatch):
    """Serving the delegation does not close the model-knowledge route: an answer that comes first is the answer, and the late delivery
    does not withdraw it (as for the lookup before)."""
    async def body(rig):
        await rig.ask(F.DIRECT_QUESTION, tid='u1', delegate=True)
        await rig.answer(F.DIRECT_ANSWER, tid='a1')
        await rig.advance(2)
        assert rig.spoken(), rig.timeline()
        state = rig.controller.state()
        assert state['chunks'] and state['retrieval_status'] == 'unverified', state
    run_wire(tmp_path, monkeypatch, body)


def test_a_second_delegation_for_the_same_question_is_not_answered_twice(tmp_path, monkeypatch):
    async def body(rig):
        model = Model(rig)
        await rig.ask(F.DIRECT_QUESTION, tid='u1', delegate=True)
        await rig.feed(F.delegation('d2-u1', 'u1'))
        await rig.advance(1)
        assert len(model.results()) == 1 and not rig.lookup_plan.calls, model.results()
    run_wire(tmp_path, monkeypatch, body)


def test_a_delegation_that_came_before_the_question_was_accepted_is_answered_too(tmp_path, monkeypatch):
    """The model asks while the question is still being spoken (its final has not come): the result goes out when the question is taken."""
    async def body(rig):
        model = Model(rig)
        await rig.feed(created('u1', 'user', 'Что'))
        await rig.feed(F.delegation('d-u1', 'u1'))
        await rig.advance(0.2)
        assert model.results() == []                                       # nothing to answer yet: there is no question
        await rig.feed(done('u1', 'user', 'Что такое фотосинтез?'))
        await rig.advance(0.5)
        got = [frame for _, frame in model.results() if frame.get('delegation_item_id') == 'd-u1']
        assert len(got) == 1 and says_nothing_was_searched(got[0]) and not rig.lookup_plan.calls, model.results()
    run_wire(tmp_path, monkeypatch, body)


def test_the_listeners_own_request_for_a_search_keeps_the_lookup_whatever_the_topic(tmp_path, monkeypatch):
    """«Проверь, пожалуйста, что такое …» is the listener's own request for a verification (route_need): it is not a settled fact."""
    async def body(rig):
        model = Model(rig)
        t0, got, _ = await model.question('Проверь, пожалуйста, что такое гидравлический удар.', 'Это резкий скачок давления.')
        assert is_a_result_of_a_search(got[1]) and len(rig.lookup_plan.calls) == 1, got
    run_wire(tmp_path, monkeypatch, body)


# ===================================================================================================================================
# 2. A personal question is never an error for the listener (item 2)
# ===================================================================================================================================

@pytest.mark.parametrize('question', PERSONAL_QUESTIONS)
def test_a_personal_question_is_never_told_to_the_listener_as_an_error(tmp_path, monkeypatch, question):
    """The call: «почему нельзя настроить как-то, чтобы ты прям мгновенно отвечал … когда я слова говорю» was read as personal and the
    listener heard «Ошибка. Повторите вопрос.»; the cloud's answer was never dictated. Now: the model is told, through the result of its
    delegation, that there is no search for this question; its answer is cued as usual; the public lookup is never reached."""
    assert not ControlledMedia.public_lookup_allowed(question), 'precondition: the privacy gate refuses this one'

    async def body(rig):
        model = Model(rig)
        t0, got, began = await model.question(question, 'У меня нет доступа к вашим личным данным, но могу подсказать общий порядок.')
        assert rig.errors() == [], rig.timeline()
        assert not rig.lookup_plan.calls, 'a personal question must never reach the public lookup'
        assert got is not None, 'the model waited for ever for the result of its delegation'
        assert got[1]['type'] == 'delegation.context.append' and says_nothing_was_searched(got[1]), got
        await rig.advance(3)
        assert first_cue(rig, t0), (question, rig.timeline())               # its answer is cued as usual
        assert all('Ошибка' not in text for text in rig.spoken())
    run_wire(tmp_path, monkeypatch, body)


def test_the_question_of_a_personal_turn_is_not_sent_back_with_the_result(tmp_path, monkeypatch):
    async def body(rig):
        model = Model(rig)
        await rig.ask('Что у меня в календаре на завтра?', tid='u1', delegate=True)
        await rig.advance(1)
        text = json.dumps([frame for _, frame in model.results()], ensure_ascii=False)
        assert model.results() and 'календар' not in text and 'завтра' not in text, text
    run_wire(tmp_path, monkeypatch, body)


def test_a_personal_question_the_model_never_delegates_is_answered_by_the_model_alone(tmp_path, monkeypatch):
    async def body(rig):
        t0 = rig.now()
        await rig.ask('Где я оставил свои ключи?', tid='u1')
        await rig.advance(0.5)
        await rig.answer('Этого я знать не могу, посмотрите дома на привычных местах.', tid='a1')
        await rig.advance(3)
        assert rig.errors() == [] and not rig.lookup_plan.calls
        assert first_cue(rig, t0), rig.timeline()
        assert rig.source.frames == [], 'nothing was asked of a model that was not waiting'
    run_wire(tmp_path, monkeypatch, body)


def test_a_personal_question_whose_delegation_comes_after_the_refusal_is_answered_too(tmp_path, monkeypatch):
    async def body(rig):
        model = Model(rig)
        await rig.ask('Что у меня в календаре на завтра?', tid='u1')
        await rig.advance(0.3)                                             # the lookup was refused; nobody has delegated yet
        assert model.results() == []
        await rig.feed(F.delegation('d-u1', 'u1'))
        await rig.advance(0.3)
        got = [frame for _, frame in model.results() if frame.get('delegation_item_id') == 'd-u1']
        assert len(got) == 1 and says_nothing_was_searched(got[0]) and not rig.lookup_plan.calls and rig.errors() == []
    run_wire(tmp_path, monkeypatch, body)


# 4.09a personal_volatile is always on: a calendar question gets the honest local phrase; this test guards the model road, so it asks a personal question outside the volatile list
def test_a_personal_question_no_cloud_ever_answers_is_reported_by_the_watchdog_once_and_not_as_an_error(tmp_path, monkeypatch):
    """What the two old tests pinned («Ошибка. Повторите вопрос.» straight after the question) is replaced by the honest report of a
    question nobody answered: after the watchdog's budget, once, in its own words."""
    async def body(rig):
        await rig.ask('Что у меня записано в заметках на завтра?')
        await rig.advance(ANSWER_WAIT_SECONDS + 5)
        assert rig.errors() == ['controlled_answer_timeout'], rig.timeline()
        assert phrases_heard(rig.frames) == [ANSWER]
    run_wire(tmp_path, monkeypatch, body)


def test_a_calendar_question_gets_the_honest_local_phrase(tmp_path, monkeypatch):
    async def body(rig):
        await rig.ask('Что у меня в календаре на завтра?')
        await rig.advance(2)
        assert rig.controller.state()['answer'].startswith('Я не вижу ваш календарь'), rig.controller.state()
    run_wire(tmp_path, monkeypatch, body)


def test_the_privacy_gate_of_the_wire_still_refuses_the_lookup_itself(tmp_path, monkeypatch):
    """Whatever a controller asks of the wire, a personal question never reaches ``lookup``: the gate is the wire's own."""
    async def body(rig):
        await rig.wire.actions([{'type': 'lookup', 'epoch': rig.controller.epoch, 'question': 'Что у меня в календаре?',
                                 'lookup_question': 'Что у меня в календаре?', 'input_turn_id': 'u1'}])
        await rig.advance(1)
        assert not rig.lookup_plan.calls and rig.errors() == []
    run_wire(tmp_path, monkeypatch, body)


# ===================================================================================================================================
# 3. The pieces: the frame, the provenance, the engine's guard, the lookup that is kept
# ===================================================================================================================================

def test_the_result_without_a_search_has_the_shape_of_a_finished_lookups_result():
    """No new protocol: the same frame type, item, channel and content type as ``context_frames`` makes for sources - only the wording
    differs, and neither the question nor a source is in it."""
    from echo_sync.native_media_socket import context_frames
    sourced = context_frames({'epoch': 3, 'question': 'Что такое инерция', 'sources': F.SOURCES, 'marker': '[ECHO:x]',
                              'delegation_id': 'd7', 'source_transport': 'delegation'})
    none = context_frames({'epoch': 3, 'sources': [], 'marker': '[ECHO:x]', 'delegation_id': 'd7', 'source_transport': 'delegation',
                           'no_search': True})
    assert len(none) == 1 and len(sourced) >= 1
    assert {k: v for k, v in none[0].items() if k != 'content'} == {k: v for k, v in sourced[0].items() if k != 'content'}
    assert none[0]['content'][0]['type'] == sourced[0]['content'][0]['type'] == 'input_text'
    assert 'question' not in none[0]['content'][0]['text'].casefold().replace('this question', '') and 'sources' not in none[0]['content'][0]['text']
    assert len(none[0]['content'][0]['text'].encode('utf-8')) <= 500                       # one frame, like any context frame


# (The DEF-T-B15 request that needs a search - a delegation whose question turns out to be a code article - is tested without a monkeypatch through the
# partial -> final path in tests/test_f3_round1.py: test_a_delegation_on_a_partial_that_becomes_a_code_article_gets_the_sources_and_only_those.)


# 4.09a personal_volatile is always on: a calendar question gets the honest local phrase; this test guards the model road, so it asks a personal question outside the volatile list
def test_a_personal_answer_is_recorded_as_given_without_any_search(tmp_path, monkeypatch):
    async def body(rig):
        model = Model(rig)
        await model.question('Что у меня записано в заметках на завтра?', 'У меня нет доступа к вашему календарю.')
        await rig.advance(2)
        state = rig.controller.state()
        assert state['retrieval_status'] == 'no_search' and state['sources'] == [], state
        assert state['history'][-1]['retrieval_status'] == 'no_search'
    run_wire(tmp_path, monkeypatch, body)
