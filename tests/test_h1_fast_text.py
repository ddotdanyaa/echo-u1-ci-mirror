"""H1: the fast text channel (prepare on the ear, release on the cloud's final). No network: every request goes to a scripted fake.

Three layers, all on the production code:
  C  the pure helpers (same_question, build_request, the SSE reader of the Codex call with a fake HTTP client);
  M  the job manager (FastText) with a scripted stream and a fake clock: adopt, restart, timeouts, the breaker, one job at a time;
  A  the controller (ControlledMedia.fast_feed and the ``fast`` actions) driven directly: owners, the filler, the epoch (H2 replaced the race: tests/test_h2_brain.py);
  W  the real NativeMediaSocket through helpers_s6_state.World with a fake ear and a fake stream: one whole exchange.
Words and the token never reach a log line (numbers only): pinned here too.
"""
from helpers_fast_fake import two_asks
import json
import logging
import queue
import threading
import time

from cm_patch import patch_controller
import pytest

import helpers_s6_ack as H
import helpers_s6_state as S
from echo_sync import fast_text as FT
from echo_sync import codex_road as CR
from echo_sync import reserve_text as RT
from echo_sync.classifier import QUESTION
from echo_sync.controlled_media import ControlledMedia
from echo_sync.native_media_socket import context_frames, native_result_text
from echo_sync.settings import resolve

INERTIA = S.TOPICS[0]                                      # 'Что такое инерция?' - the model-knowledge route, verified with the host configuration
PHOTO = S.TOPICS[4]                                        # 'Что такое фотосинтез?'
FIRST = 'Инерция — это свойство тела сохранять своё состояние движения или покоя.'
SECOND = 'Чем больше масса, тем сильнее инерция.'
ANSWER = FIRST + ' ' + SECOND
STORED = 'свойство тела сохранять своё состояние движения или покоя. ' + SECOND         # the answer as the state keeps it (definition_body)
FIRST_CUE = 'свойство тела сохранять своё состояние движения или покоя.'     # what the ordinary path makes of FIRST (definition_body drops the subject)
VERIFY = 'Проверь, пожалуйста, что такое гидравлический удар.'
HAMMER = {'url': 'https://example.org/hammer', 'text': 'Гидравлический удар — резкий скачок давления в трубопроводе при внезапной остановке потока жидкости.'}
CURRENT = 'Проверь, какая сейчас ставка НДС в России.'
SECRET = 'tok-SECRET-0123456789'


def until(condition, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if condition():
            return True
        time.sleep(0.002)
    return False


class FakeRun:
    """One scripted streaming request: the test says what the cloud-less channel yields, and when."""

    def __init__(self, request, cancelled):
        self.request, self.cancelled = request, cancelled
        self.script = queue.Queue()
        self.acked = threading.Event()
        self.ended = threading.Event()

    def say(self, text):
        self.acked.clear()
        self.script.put(('delta', text))
        assert self.acked.wait(3), 'the job thread did not take the text'

    def finish(self):
        self.script.put(('end', None))
        assert self.ended.wait(3)

    def fail(self, message='boom'):
        self.script.put(('fail', message))
        assert self.ended.wait(3)

    def generate(self):
        try:
            while True:
                try:
                    kind, value = self.script.get(timeout=0.02)
                except queue.Empty:
                    if self.cancelled.is_set():
                        return
                    continue
                if kind == 'delta':
                    yield value
                    self.acked.set()
                elif kind == 'end':
                    return
                else:
                    raise RuntimeError(value)
        finally:
            self.ended.set()

    @property
    def question(self):
        return self.request['input'][-1]['content'][0]['text']


class FakeStream:
    def __init__(self):
        self.runs = []

    def __call__(self, request, cancelled):
        run = FakeRun(request, cancelled)
        self.runs.append(run)
        return run.generate()

    def run(self, n=0):
        assert until(lambda: len(self.runs) > n), f'request {n} was never made'
        return self.runs[n]


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


def manager(clock=None, **keywords):
    fake = FakeStream()
    clock = clock or Clock()
    fast = FT.FastText(fake, instructions=lambda: 'POLICY', history=lambda: [], clock=clock, wake=lambda: None, **keywords)
    return fast, fake, clock


def settled(fast):
    """The job thread has pushed everything it was given and is waiting (or is over)."""
    time.sleep(0.01)


def texts(events):
    return ''.join(e['text'] for e in events if e['kind'] == 'text')


def kinds(events):
    return [e['kind'] for e in events]


# =====================================================================================================================================
# C. helpers
# =====================================================================================================================================

def test_the_setting_is_off_by_default_and_read_like_local_ear():
    assert resolve({})['fast_text'] == 'off' and resolve({'fast_text': 'on'})['fast_text'] == 'on'
    assert resolve({'fast_text': 'yes'})['fast_text'] == 'off', 'an unknown value is off'
    assert resolve({'fast_text': True})['fast_text'] == 'off'


def test_the_host_passes_the_profile_setting_and_nothing_else_changes_for_the_world():
    assert 'fast_text' not in S.host_kwargs(), 'the host passes no fast_text: the controller reads it from the call settings (ControlledMedia.modes)'
    assert S.host_kwargs()['settings'].get('fast_text', 'off') == 'off'


def test_for_call_is_none_when_the_profile_says_off(tmp_path):
    c = ControlledMedia(tmp_path / 'off.sqlite3', session_id=H.SESSION, clock=H.FakeClock(), **H.HOST_KWARGS)
    assert FT.for_call(resolve({}), c, stream=FakeStream()) is None
    assert FT.for_call(resolve({'fast_text': 'off'}), c, stream=FakeStream()) is None
    assert isinstance(FT.for_call(resolve({'fast_text': 'on'}), c, stream=FakeStream()), FT.FastText)


@pytest.mark.parametrize('heard, final, same', [
    ('Что такое амортизация', 'Что такое амортизация?', True),
    ('что такое амортизации', 'Что такое амортизация', True),                      # an ending
    ('так что такое амортизация', 'Что такое амортизация', True),                  # a leading filler (the controller strips it from the question)
    ('Когда было крещение Руси', 'Когда было крещение Руси', True),
    ('Когда началась война в 1941 году', 'Когда началась война в 1914 году', False),     # other numbers
    ('Сколько будет сорок восемь умножить на десять', 'Сколько будет 48 умножить на 10', True),    # the same numbers, said and written
    ('Сколько будет сорок восемь умножить на десять', 'Сколько будет 48 умножить на 11', False),
    ('Что такое инерция', 'Что такое фотосинтез', False),                          # other words
    ('Это правильно', 'Это не правильно', False),                                  # one word more, the meaning turned round
    ('Почему небо голубое', 'Почему трава зелёная', False),
    ('', 'Что такое инерция', False),
])
def test_same_question(heard, final, same):
    assert FT.same_question(heard, final, strip=lambda t: t.replace('так ', '', 1)) is same


def test_similarity_threshold_is_three_quarters():
    assert FT.same_question('кошка собака мышка слон волк', 'кошка собака мышка') is True          # 6 of the 8 words: 0.75
    assert FT.same_question('кошка собака мышка слон волк лиса', 'кошка собака мышка') is False    # 6 of the 9 words: 0.667


def test_native_result_text_is_what_context_frames_give_the_model():
    action = {'epoch': 3, 'question': VERIFY, 'sources': [HAMMER], 'marker': '[ECHO:x]', 'delegation_id': None, 'source_transport': 'session_context'}
    joined = ''.join(frame['content'][0]['text'] for frame in context_frames(action))
    assert joined == native_result_text(VERIFY, [HAMMER])


def test_the_request_has_the_fixed_model_effort_and_no_tools():
    body = FT.build_request('Что такое инерция?', instructions='POLICY TEXT', history=[{'question': 'q%d' % i, 'answer': 'a%d' % i} for i in range(9)])
    assert 'model' not in body and 'stream' not in body      # what is asked: the road words it on its wire
    wired = CR.wire(body)
    assert wired['model'] == CR.FAST_MODEL == 'gpt-5.6-luna' and wired['reasoning'] == {'effort': 'low'} and wired['stream'] is True and wired['store'] is False
    assert wired['instructions'] == body['instructions'] and wired['input'] == body['input']
    assert 'tools' not in wired and 'tool_choice' not in wired
    assert body['instructions'].startswith('POLICY TEXT')
    assert 'q8' in body['instructions'] and 'a8' in body['instructions'] and 'q3' in body['instructions'] and 'q2' not in body['instructions'], 'the last 6 exchanges'
    assert body['input'] == [{'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text': 'Что такое инерция?'}]}]


def test_the_material_goes_in_front_of_the_question_as_a_user_message():
    body = FT.build_request('Что такое X?', instructions='P', material='SOURCES TEXT')
    assert [m['content'][0]['text'] for m in body['input']] == ['SOURCES TEXT', 'Что такое X?'] and {m['role'] for m in body['input']} == {'user'}


class FakeResponse:
    def __init__(self, status, lines):
        self.status_code, self.lines, self.read_called = status, lines, False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def iter_lines(self):
        yield from self.lines

    def read(self):
        self.read_called = True
        return b'{"detail":"%s"}' % SECRET.encode()


class FakeHttp:
    def __init__(self, response):
        self.response, self.calls, self.closed = response, [], False

    def stream(self, method, url, **keywords):
        self.calls.append((method, url, keywords))
        return self.response

    def close(self):
        self.closed = True


def sse(*events):
    return ['data: ' + json.dumps(e) if not isinstance(e, str) else e for e in events]


def test_the_codex_call_reads_the_text_deltas_and_stops_at_completed():
    lines = sse({'type': 'response.created'}, {'type': 'response.output_text.delta', 'delta': 'Инер'}, ': keep-alive',
                {'type': 'response.output_text.delta', 'delta': 'ция.'}, 'data: not json', {'type': 'response.completed'},
                {'type': 'response.output_text.delta', 'delta': 'NEVER'})
    http = FakeHttp(FakeResponse(200, lines))
    stream = CR.codex_stream(lambda: (SECRET, 'acct-1'), client_factory=lambda: http)
    assert list(stream({'model': 'm'}, threading.Event())) == ['Инер', 'ция.']
    (method, url, keywords), = http.calls
    assert method == 'POST' and url == CR.FAST_URL == 'https://chatgpt.com/backend-api/codex/responses'
    assert keywords['headers']['Authorization'] == 'Bearer ' + SECRET and keywords['headers']['ChatGPT-Account-Id'] == 'acct-1'
    assert keywords['headers']['originator'] == 'codex_cli_rs' and keywords['headers']['Accept'] == 'text/event-stream' and keywords['json'] == CR.wire({'model': 'm'})
    assert not http.closed, 'T1: the client lives as long as the call, not as long as a job (tests/test_t1_transport.py)'
    stream.close()
    assert until(lambda: http.closed)


def test_a_refused_call_raises_with_the_status_only(caplog):
    http = FakeHttp(FakeResponse(401, []))
    stream = CR.codex_stream(lambda: (SECRET, 'acct-1'), client_factory=lambda: http)
    with pytest.raises(CR.FastTextError) as error:
        list(stream({}, threading.Event()))
    assert str(error.value) == 'http_401' and SECRET not in repr(error.value) and not http.response.read_called


def test_the_credentials_are_asked_once_in_a_while_and_again_after_a_refusal():
    asked = []
    def credentials():
        asked.append(1)
        return SECRET, 'a'
    responses = [FakeResponse(200, sse({'type': 'response.completed'})), FakeResponse(200, sse({'type': 'response.completed'})), FakeResponse(403, []),
                 FakeResponse(200, sse({'type': 'response.completed'}))]
    http = FakeHttp(None)                                              # T1: ONE client for the call, each request of it takes the next response
    http.stream = lambda method, url, **keywords: responses.pop(0)
    stream = CR.codex_stream(credentials, client_factory=lambda: http)
    list(stream({}, threading.Event()))
    list(stream({}, threading.Event()))
    assert len(asked) == 1
    with pytest.raises(CR.FastTextError):
        list(stream({}, threading.Event()))
    list(stream({}, threading.Event()))
    assert len(asked) == 2, 'a refusal drops the cached sign-in'


def test_a_cancelled_call_yields_nothing_more():
    cancelled = threading.Event()
    lines = sse({'type': 'response.output_text.delta', 'delta': 'a'}, {'type': 'response.output_text.delta', 'delta': 'b'})
    stream = CR.codex_stream(lambda: (SECRET, 'a'), client_factory=lambda: FakeHttp(FakeResponse(200, lines)))
    got = []
    for delta in stream({}, cancelled):
        got.append(delta)
        cancelled.set()
    assert got == ['a']


# =====================================================================================================================================
# M. the job manager
# =====================================================================================================================================

def test_prepare_starts_one_request_for_the_ears_text_and_keeps_it_quiet():
    fast, fake, _ = manager()
    assert fast.prepare('Что такое инерция') is True
    run = fake.run(0)
    assert run.question == 'Что такое инерция' and 'model' not in run.request      # the wire fields are the road's (``CR.wire``)
    run.say('Инерция — это ')
    settled(fast)
    assert fast.poll() == [], 'a prepared job is not released: nothing reaches the controller'
    assert fast.prepare('Что такое инерция') is True and len(fake.runs) == 1, 'the same text again does not start a second job'
    fast.close()


def test_a_different_text_replaces_the_prepared_job_one_job_at_a_time():
    fast, fake, _ = manager()
    fast.prepare('Что такое инерция')
    first = fake.run(0)
    fast.prepare('Что такое фотосинтез')
    second = fake.run(1)
    assert first.cancelled.is_set() and not second.cancelled.is_set() and second.question == 'Что такое фотосинтез'
    fast.close()


def test_a_released_job_is_not_replaced_by_a_prepare():
    fast, fake, _ = manager()
    assert fast.release(qid='u1', turn='fast-1', epoch=1, question='Что такое инерция') == 'started'
    assert fast.prepare('Что такое фотосинтез') is False and len(fake.runs) == 1 and not fake.run(0).cancelled.is_set()
    fast.close()


def test_release_adopts_a_matching_prepared_job_and_replays_what_it_had():
    fast, fake, _ = manager()
    fast.prepare('Что такое инерция')
    run = fake.run(0)
    run.say('Инерция — это ')
    run.say('свойство тела.')
    settled(fast)
    assert fast.release(qid='u1', turn='fast-1', epoch=1, question='Что такое инерция?') == 'adopted'
    events = fast.poll()
    assert kinds(events) == ['text'] and texts(events) == 'Инерция — это свойство тела.' and events[0]['turn'] == 'fast-1' and events[0]['qid'] == 'u1'
    run.say(' Чем больше масса.')
    settled(fast)
    assert texts(fast.poll()) == ' Чем больше масса.'
    run.finish()
    assert until(lambda: fast.job.done)
    assert kinds(fast.poll()) == ['done'] and len(fake.runs) == 1


def test_release_adopts_a_job_that_had_already_finished():
    fast, fake, _ = manager()
    fast.prepare('Что такое инерция')
    run = fake.run(0)
    run.say(FIRST)
    run.finish()
    assert until(lambda: fast.job.done)
    assert fast.release(qid='u1', turn='fast-1', epoch=1, question='Что такое инерция') == 'adopted'
    assert kinds(fast.poll()) == ['text', 'done']


@pytest.mark.parametrize('heard, final', [('Что такое инерция', 'Что такое фотосинтез'), ('Когда началась война в 1941 году', 'Когда началась война в 1914 году')])
def test_release_cancels_a_prepared_job_that_does_not_match_and_starts_on_the_final(heard, final):
    fast, fake, _ = manager()
    fast.prepare(heard)
    first = fake.run(0)
    first.say('Не то.')
    assert fast.release(qid='u1', turn='fast-1', epoch=1, question=final) == 'started'
    second = fake.run(1)
    assert first.cancelled.is_set() and second.question == final
    second.say(FIRST)
    settled(fast)
    assert texts(fast.poll()) == FIRST, 'the cancelled job left nothing in the released one'
    fast.close()


def test_a_job_with_a_material_is_never_adopted_from_a_prepared_one():
    fast, fake, _ = manager()
    fast.prepare('Что такое гидравлический удар')
    assert fast.release(qid='u1', turn='fast-1', epoch=1, question='Что такое гидравлический удар', material='SOURCES') == 'started'
    assert fake.run(0).cancelled.is_set() and fake.run(1).request['input'][0]['content'][0]['text'] == 'SOURCES'
    fast.close()


def test_a_prepared_job_older_than_the_whole_bound_is_not_adopted():
    fast, fake, clock = manager()
    fast.prepare('Что такое инерция')
    clock.advance(FT.WHOLE_S + 0.1)
    assert fast.release(qid='u1', turn='fast-1', epoch=1, question='Что такое инерция') == 'started' and len(fake.runs) == 2
    fast.close()


def test_drop_cancels_only_an_unreleased_job():
    fast, fake, _ = manager()
    fast.prepare('Что такое инерция')
    fast.drop()
    assert fake.run(0).cancelled.is_set() and fast.job is None
    fast.release(qid='u1', turn='fast-1', epoch=1, question='Что такое инерция')
    fast.drop()
    assert not fake.run(1).cancelled.is_set()
    fast.retain('u2')
    assert fake.run(1).cancelled.is_set(), 'a released job of another question is cancelled'


def test_the_whole_job_is_bounded_to_fifteen_seconds():
    fast, fake, clock = manager()
    fast.release(qid='u1', turn='fast-1', epoch=1, question='Что такое инерция')
    run = fake.run(0)
    clock.advance(1)
    run.say('Инерция')
    settled(fast)
    assert kinds(fast.poll()) == ['text']
    clock.advance(FT.WHOLE_S)
    events = fast.poll()
    assert kinds(events) == ['failed'] and run.cancelled.is_set()


def test_a_failing_stream_is_a_failed_event_with_the_text_that_came_first():
    fast, fake, _ = manager()
    fast.release(qid='u1', turn='fast-1', epoch=1, question='Что такое инерция')
    run = fake.run(0)
    run.say('Инерция')
    run.fail()
    assert until(lambda: fast.job.done)
    events = fast.poll()
    assert kinds(events) == ['text', 'failed']


def test_an_empty_answer_is_a_failure():
    fast, fake, _ = manager()
    fast.release(qid='u1', turn='fast-1', epoch=1, question='Что такое инерция')
    fake.run(0).finish()
    assert until(lambda: fast.job.done)
    assert kinds(fast.poll()) == ['failed']      # no word of any road: the roads are dead and the question is given back


def test_a_cancelled_job_is_no_failure():
    fast, fake, _ = manager()
    fast.release(qid='u1', turn='fast-1', epoch=1, question='Что такое инерция')
    fast.retain('u2')
    assert until(lambda: fake.run(0).ended.is_set())
    assert fast.poll() == [] and not fast.off


def test_the_log_has_numbers_only_never_words_or_the_token(caplog):
    caplog.set_level(logging.INFO, logger='echo-sync')
    fast, fake, _ = manager()
    fast.release(qid='u1', turn='fast-1', epoch=1, question='Что такое инерция', material=SECRET)
    run = fake.run(0)
    run.say(FIRST)
    run.finish()
    assert until(lambda: fast.job.done)
    fast.poll()
    lines = [r.getMessage() for r in caplog.records if 'fast_text' in r.getMessage()]
    assert lines and all(l.startswith('echo-sync fast_text job=') and 'ttft_ms=' in l and 'chars=' in l and 'outcome=ok' in l for l in lines), lines
    everything = '\n'.join(r.getMessage() for r in caplog.records)
    assert SECRET not in everything and 'инерци' not in everything.casefold() and 'свойство' not in everything.casefold()


# =====================================================================================================================================
# A. the controller
# =====================================================================================================================================

def make(tmp_path, name='c', **keywords):
    return ControlledMedia(tmp_path / (name + '.sqlite3'), session_id=H.SESSION, clock=H.FakeClock(), **{**H.HOST_KWARGS, 'fast_text': 'on', **keywords})


def ask(c, text=INERTIA.question, uid='u1'):
    c.speech_started()
    c.provider(H.created(uid, 'user', text.split()[0]))
    return c.provider(H.done(uid, 'user', text))


def types(actions):
    return [a['type'] for a in actions]


def speaks(actions):
    return [a['text'] for a in actions if a['type'] == 'speak']


def lookup_controller(tmp_path, question=VERIFY, **keywords):
    c = make(tmp_path, **keywords)
    actions = ask(c, question)
    assert 'lookup' in types(actions), actions
    return c, actions


def test_off_a_question_opens_exactly_as_before_and_nothing_is_asked_of_the_channel(tmp_path):
    c = make(tmp_path, fast_text='off')
    assert types(ask(c)) == ['cancel', 'route']
    assert c.fast_prepare({'kind': QUESTION, 'text': 'Что такое инерция'}) == []
    assert c.fast_feed('fast-1', 'u1', 'text', FIRST) == (False, []) and c.fast_turn is None
    default = ControlledMedia(tmp_path / 'd.sqlite3', session_id=H.SESSION, clock=H.FakeClock(), **H.HOST_KWARGS)
    assert types(ask(default)) == ['cancel', 'route'], 'no keyword, no change'
    lookup = make(tmp_path, 'l', fast_text='off')
    assert types(ask(lookup, VERIFY)) == ['cancel', 'lookup']
    assert types(lookup.grounding(lookup.epoch, [HAMMER])) == ['context']


def test_a_question_on_the_model_route_asks_the_channel_for_its_release(tmp_path):
    c = make(tmp_path)
    actions = ask(c)
    assert types(actions) == ['cancel', 'route', 'fast']
    assert actions[2] == {'type': 'fast', 'op': 'release', 'epoch': c.epoch, 'qid': 'u1', 'turn': 'fast-1', 'question': c.question_text, 'route': 'model'}


def test_the_lookup_route_drops_what_the_ear_prepared(tmp_path):
    c, actions = lookup_controller(tmp_path)
    assert types(actions) == ['cancel', 'lookup', 'fast'] and actions[2]['op'] == 'drop'


def test_the_ear_prepares_only_a_question_of_three_words_that_needs_no_lookup(tmp_path):
    c = make(tmp_path)
    ok = c.fast_prepare({'kind': QUESTION, 'text': 'Так, что такое инерция'})
    assert ok == [{'type': 'fast', 'op': 'prepare', 'text': 'что такое инерция'}]
    assert c.fast_prepare({'kind': 'ack', 'text': 'что такое инерция'}) == []
    assert c.fast_prepare({'kind': QUESTION, 'text': 'что это'}) == [], 'fewer than three words'
    assert c.fast_prepare({'kind': QUESTION, 'text': VERIFY}) == [], 'the lookup route is no preparation'
    assert c.fast_prepare({'kind': QUESTION, 'text': CURRENT}) == []
    assert c.fast_prepare({'kind': QUESTION, 'text': None}) == [] and c.fast_prepare({}) == []
    assert c.question_id is None and c.state() is None, 'preparing changes no state'


def test_the_first_text_takes_the_answer_and_is_cued_like_the_clouds(tmp_path):
    c = make(tmp_path)
    ask(c)
    keep, actions = c.fast_feed('fast-1', 'u1', 'text', ANSWER)
    assert keep is True and speaks(actions) == [FIRST_CUE] and c.fast_turn == 'fast-1' and c.owners['fast-1'] == 'u1' and c.published
    cloud = make(tmp_path, 'cloud', fast_text='off')
    ask(cloud)
    cloud.provider(H.created('a1', 'assistant', 'Инерция'))
    assert speaks(cloud.provider(H.done('a1', 'assistant', ANSWER))) == [FIRST_CUE], 'the same first portion as the cloud text gives'


def test_the_text_arriving_in_pieces_is_one_turn_and_the_end_closes_it(tmp_path):
    c = make(tmp_path)
    ask(c)
    assert c.fast_feed('fast-1', 'u1', 'text', 'Инерция — это свойство')[1] == []
    heard = speaks(c.fast_feed('fast-1', 'u1', 'text', ' тела сохранять своё состояние движения или покоя.')[1])
    assert heard == [FIRST_CUE]
    c.fast_feed('fast-1', 'u1', 'text', ' ' + SECOND)
    keep, _ = c.fast_feed('fast-1', 'u1', 'done')
    assert keep is False and c.ledger.snapshot('fast-1')['text'] == ANSWER and c.ledger.snapshot('fast-1')['final']
    assert c.state()['answer'] == STORED and not c.state()['streaming']


def test_after_the_job_owns_the_answer_the_clouds_turns_of_the_question_are_ignored(tmp_path):
    c = make(tmp_path)
    ask(c)
    c.fast_feed('fast-1', 'u1', 'text', FIRST)
    published = c.published
    c.provider(H.created('a1', 'assistant', 'Другой'))
    assert c.provider(H.done('a1', 'assistant', 'Другой ответ облака. Он длиннее и совсем иной.')) == []
    assert c.published == published and c.source_segment_id == 'fast-1'


def test_a_filler_the_cloud_said_before_the_first_text_is_forgotten(tmp_path):
    c = make(tmp_path)
    ask(c)
    c.provider(H.created('a0', 'assistant', 'Понял'))
    c.provider(H.done('a0', 'assistant', 'Понял, сейчас уточню кратко по теме'))
    assert c.source_segment_id is None and not c.published, 'precondition: the filler is set aside'
    keep, actions = c.fast_feed('fast-1', 'u1', 'text', ANSWER)
    assert keep and speaks(actions) == [FIRST_CUE]
    assert c.source_segment_id == 'fast-1' and c.source_segment_prefix == '' and c.answer_head == ('u1', 'fast-1')
    assert c.unsettled is None and c.held_source is None


def test_a_stale_question_drops_the_job_and_a_new_question_asks_again(tmp_path):
    c = make(tmp_path)
    ask(c)
    second = ask(c, PHOTO.question, 'u2')
    assert second[-1]['turn'] == 'fast-2' and second[-1]['qid'] == 'u2'
    assert c.fast_feed('fast-1', 'u1', 'text', FIRST) == (False, []), 'the job of the old question'
    assert c.fast_turn is None and not c.published
    keep, actions = c.fast_feed('fast-2', 'u2', 'text', PHOTO.answer)
    assert keep and speaks(actions)


def test_a_late_delta_after_the_answer_was_closed_is_dropped(tmp_path):
    c = make(tmp_path)
    ask(c)
    c.fast_feed('fast-1', 'u1', 'text', ANSWER)
    c.fast_feed('fast-1', 'u1', 'done')
    before = c.state()['answer']
    assert c.fast_feed('fast-1', 'u1', 'text', ' позже') == (False, [])
    assert c.state()['answer'] == before and c.ledger.snapshot('fast-1')['text'] == ANSWER


def test_stop_before_anything_is_published_drops_the_job(tmp_path):
    c = make(tmp_path)
    ask(c)
    c.fast_feed('fast-1', 'u1', 'text', 'Инерция — это свойство')            # owns the answer, the gate has not cued yet
    assert not c.published and c.fast_turn == 'fast-1'
    c.provider(H.done('u2', 'user', 'стоп'))
    assert c.question_id is None
    assert c.fast_feed('fast-1', 'u1', 'text', ' тела сохранять своё состояние движения или покоя.') == (False, [])
    assert not c.published


def test_stop_after_the_answer_began_pauses_it_and_the_rest_of_the_job_stays_in_the_plan(tmp_path):
    c = make(tmp_path)
    ask(c)
    c.fast_feed('fast-1', 'u1', 'text', FIRST)
    assert c.published
    c.provider(H.done('u2', 'user', 'стоп'))
    assert c.state()['paused'] and c.question_id == 'u1'
    keep, actions = c.fast_feed('fast-1', 'u1', 'text', ' ' + SECOND)
    assert keep is True and speaks(actions) == [], 'paused: nothing is spoken'
    assert c.state()['answer'] == STORED, 'the text that still arrives stays in the plan, as the cloud text does'


def test_a_failure_before_any_text_changes_nothing(tmp_path):
    c = make(tmp_path)
    ask(c)
    keep, again = c.fast_feed('fast-1', 'u1', 'failed')
    assert keep is False and [a['turn'] for a in again] == ['fast-2'], 'H5 item 7: one more job first'
    assert c.fast_feed('fast-2', 'u1', 'failed') == (False, []) and c.fast_turn is None
    c.provider(H.created('a1', 'assistant', 'Инерция'))
    assert speaks(c.provider(H.done('a1', 'assistant', ANSWER))) == [FIRST_CUE], 'the cloud goes on'


def test_a_failure_after_the_first_text_and_before_anything_is_said_hands_the_answer_back(tmp_path):
    c = make(tmp_path)
    ask(c)
    c.fast_feed('fast-1', 'u1', 'text', 'Инерция — это')
    assert c.fast_turn == 'fast-1' and not c.published
    c.provider(H.created('a1', 'assistant', 'Инерция'))
    assert c.provider(H.done('a1', 'assistant', ANSWER)) == [], 'ignored while the job owns the answer'
    keep, again = c.fast_feed('fast-1', 'u1', 'failed')
    assert keep is False and c.fast_turn is None and 'fast-1' in c.retired_assistants and [a['turn'] for a in again] == ['fast-2']
    keep, actions = c.fast_feed('fast-2', 'u1', 'failed')
    assert speaks(actions) == [FIRST_CUE], 'the cloud turn that came meanwhile is the answer now'


def test_a_failure_after_the_answer_began_ends_it_where_it_broke(tmp_path):
    c = make(tmp_path)
    ask(c)
    c.fast_feed('fast-1', 'u1', 'text', FIRST)
    keep, _ = c.fast_feed('fast-1', 'u1', 'failed')
    assert keep is False and c.fast_turn == 'fast-1' and c.ledger.snapshot('fast-1')['final']
    assert c.state()['answer'] == FIRST_CUE and not c.state()['streaming']


def test_the_lookup_route_starts_the_job_with_the_sources_the_model_gets(tmp_path):
    c, _ = lookup_controller(tmp_path)
    actions = c.grounding(c.epoch, [HAMMER])
    assert types(actions) == ['fast', 'context']
    fast, context = actions
    assert fast['op'] == 'release' and fast['route'] == 'sources' and fast['sources'] == context['sources'] == [HAMMER] and fast['turn'] == 'fast-1'
    assert fast['question'] == context['question'] and fast['qid'] == 'u1' and fast['epoch'] == c.epoch


def test_a_fast_turn_counts_as_delivered(tmp_path):
    c, _ = lookup_controller(tmp_path)
    c.grounding(c.epoch, [HAMMER])
    assert not c.delivery_ready, 'precondition: the sources have not been sent to the cloud yet'
    keep, actions = c.fast_feed('fast-1', 'u1', 'text', 'Гидравлический удар — резкий скачок давления в трубопроводе. Он возникает при внезапной остановке потока.')
    assert keep and speaks(actions), actions
    assert c.engine.state(c.session_id)['retrieval_status'] == 'source_backed'
    assert c.delivery_sent(c.epoch, None) is True, 'the cloud gets its context all the same'
    assert c.fast_turn == 'fast-1'


def test_the_lookup_route_releases_once_per_question(tmp_path):
    c, _ = lookup_controller(tmp_path)
    assert 'fast' in types(c.grounding(c.epoch, [HAMMER]))
    assert 'fast' not in types(c._context_action()) and 'fast' not in types(c._release_result())


def test_a_lookup_without_a_source_asks_for_the_answer_from_knowledge(tmp_path):
    c, _ = lookup_controller(tmp_path)
    assert c.grounding(c.epoch, []) == []
    actions = c.without_source(c.epoch,'failed')
    assert types(actions) == ['fast', 'context'] and actions[0]['route'] == 'unsourced' and actions[1]['why'] == 'unsourced'
    keep, spoken = c.fast_feed('fast-1', 'u1', 'text', 'Гидравлический удар — резкий скачок давления в трубопроводе. Он возникает при остановке потока.')
    assert keep and speaks(spoken) and c.engine.state(c.session_id)['retrieval_status'] == 'unsourced'


def test_current_data_without_a_source_gets_no_job(tmp_path):
    c, _ = lookup_controller(tmp_path, CURRENT)
    assert c.without_source(c.epoch,'failed') is None
    assert c.fast_feed('fast-1', 'u1', 'text', 'Двадцать процентов.') == (False, [])


def test_a_reference_answer_drops_what_was_prepared_and_asks_for_no_job(tmp_path, monkeypatch):
    import echo_sync.controlled_media as cm
    patch_controller(monkeypatch, 'reference_lookup', lambda text, history=(), **_: 'Статья 19 Налогового кодекса — налогоплательщики и плательщики сборов.')
    c = make(tmp_path)
    actions = ask(c, 'Что такое девятнадцатая статья налогового кодекса')
    assert [a.get('route') for a in actions if a['type'] == 'route'] == ['local_reference']
    assert [a['op'] for a in actions if a['type'] == 'fast'] == ['drop'] and c.fast_asked is None, actions
    assert c.fast_feed('fast-1', 'u1', 'text', 'Своё.') == (False, [])


# =====================================================================================================================================
# W. the real NativeMediaSocket
# =====================================================================================================================================

class FakeEar:
    acting = False

    def __init__(self):
        self.records = []

    def poll(self):
        out, self.records = self.records, []
        return out

    def feed(self, pcm, input_ms=None):
        pass

    def close(self):
        pass


class Rig:
    def __init__(self, world, fake, fast):
        self.w, self.fake, self.fast = world, fake, fast

    def hear(self, text, kind=QUESTION):
        self.w.wire.ear.records.append({'uid': 1, 'text': text, 'kind': kind, 'reason': 'x', 'revision': None, 'index': None, 'speech_ms': 900, 'lag_ms': 300,
                                        'decode_ms': 200, 'onset_input_ms': 0, 'offset_input_ms': 900, 'onset': self.w.clock.t, 'offset': self.w.clock.t})
        self.w.advance(0.1, step=0.1)

    def ask(self, topic=INERTIA, uid='u1', text=None):
        self.w.feed(S.turn_created(uid, 'user', topic.question.split()[0]))
        self.w.feed(S.turn_done(uid, 'user', text or topic.question))

    def pump(self, seconds=0.2):
        self.w.advance(seconds, step=0.1)

    def cues(self):
        return [c.text for c in self.w.cues if not c.diagnostic]

    def say(self, n, text):
        self.fake.run(n).say(text)
        settled(self.fast)
        self.pump()


@pytest.fixture
def rig(monkeypatch):
    original = S.host_kwargs
    monkeypatch.setattr(S, 'host_kwargs', lambda: {**original(), 'fast_text': 'on'})
    world = S.World()
    fake = FakeStream()
    fast = FT.for_call(resolve({'fast_text': 'on'}), world.controller, stream=two_asks(fake, world.clock.now), instructions=lambda: 'POLICY', wake=lambda: None, clock=world.clock.now)
    world.wire.fast = fast
    world.wire.ear = FakeEar()
    yield Rig(world, fake, fast)
    fast.close()
    world.close()


def cloud_cues(topic, answer):
    world = S.World()
    try:
        world.feed(S.turn_created('u1', 'user', topic.question.split()[0]))
        world.feed(S.turn_done('u1', 'user', topic.question))
        world.feed(S.turn_created('a1', 'assistant', answer.split()[0]))
        world.feed(S.turn_done('a1', 'assistant', answer))
        world.advance(0.5)
        return [c.text for c in world.cues if not c.diagnostic]
    finally:
        world.close()


def test_off_nothing_is_asked_and_the_ear_prepares_nothing(monkeypatch):
    world = S.World()
    fake = FakeStream()
    fast = FT.FastText(fake, instructions=lambda: 'P', history=lambda: [], clock=world.clock.now, wake=lambda: None)
    world.wire.fast, world.wire.ear = fast, FakeEar()
    seen = []
    original = world.wire.actions

    async def spy(actions):
        seen.extend(a['type'] for a in actions)
        return await original(actions)
    world.wire.actions = spy
    try:
        world.wire.ear.records.append({'uid': 1, 'text': 'Что такое инерция', 'kind': QUESTION, 'reason': 'x', 'revision': None, 'index': None})
        world.advance(0.2, step=0.1)
        world.feed(S.turn_created('u1', 'user', 'Что'))
        world.feed(S.turn_done('u1', 'user', INERTIA.question))
        world.feed(S.turn_created('a1', 'assistant', 'Инерция'))
        world.feed(S.turn_done('a1', 'assistant', ANSWER))
        world.advance(0.5)
    finally:
        fast.close()
        world.close()
    assert fake.runs == [] and 'fast' not in seen and 'route' in seen
    assert [c.text for c in world.cues if not c.diagnostic][:1] == cloud_cues(INERTIA, ANSWER)[:1]


def test_prepared_on_the_ear_adopted_on_the_final_and_spoken_like_the_cloud(rig):
    rig.hear('Что такое инерция')
    run = rig.fake.run(0)
    assert run.question == 'Что такое инерция' and run.request['instructions'].startswith('POLICY')
    rig.say(0, 'Инерция — это свойство тела')
    assert rig.cues() == [] and rig.w.controller.question_id is None and rig.w.controller.state() is None, 'preparing is quiet and changes no state'
    rig.ask()
    assert len(rig.fake.runs) == 1, 'adopted: no second request'
    rig.say(0, ' сохранять своё состояние движения или покоя. ' + SECOND)
    assert rig.cues()[:1] == cloud_cues(INERTIA, ANSWER)[:1] == [FIRST_CUE]
    assert rig.w.controller.fast_turn == 'fast-1' and rig.w.controller.engine.state(rig.w.session_id)['retrieval_status'] == 'unverified'


def test_prepared_but_not_the_question_that_opened_restarts_on_the_final(rig):
    rig.hear('Что такое инерция')
    first = rig.fake.run(0)
    first.say('Не то.')
    rig.ask(PHOTO)
    second = rig.fake.run(1)
    assert first.cancelled.is_set() and second.question == PHOTO.question.rstrip('?') or second.question.startswith('Что такое фотосинтез')
    rig.say(1, PHOTO.answer)
    assert rig.cues() and rig.cues()[0].startswith('процесс')


def test_the_job_first_the_clouds_text_is_ignored(rig):
    rig.ask()
    rig.say(0, ANSWER)
    assert rig.cues()[:1] == [FIRST_CUE]
    rig.w.feed(S.turn_created('a1', 'assistant', 'Иное'))
    rig.w.feed(S.turn_done('a1', 'assistant', 'Иное облачное объяснение. Оно совсем про другое.'))
    rig.pump()
    assert rig.cues() == [FIRST_CUE] and rig.w.controller.state()['answer'].startswith(FIRST_CUE)


def test_a_failing_job_leaves_the_cloud_to_answer_and_says_nothing(rig):
    rig.ask()
    rig.fake.run(0).fail()
    rig.pump()
    rig.fake.run(1).fail()      # the second chance of the job is the next road (``helpers_fast_fake.two_asks``); both failed: the roads are dead
    rig.pump()
    rig.w.feed(S.turn_created('a1', 'assistant', 'Инерция'))
    rig.w.feed(S.turn_done('a1', 'assistant', ANSWER))
    rig.pump()
    assert rig.cues() == [FIRST_CUE] and rig.w.errors == [] and len(rig.fake.runs) == 2


def test_a_job_that_gives_no_text_in_time_leaves_the_cloud_to_answer(rig):
    rig.ask()
    rig.pump(1.0)
    rig.w.feed(S.turn_created('a1', 'assistant', 'Инерция'))
    rig.w.feed(S.turn_done('a1', 'assistant', ANSWER))
    rig.pump(RT.ALL_DEAD_S + 0.5)      # the cloud has its answer: the roads give the question back at ALL_DEAD_S (a hung job is no failure before it)
    assert rig.fake.run(0).cancelled.is_set() and len(rig.fake.runs) == 1
    assert rig.cues() == [FIRST_CUE] and not [e for e in rig.w.errors if e['error']['code'] != 'controlled_answer_timeout']


def test_a_new_question_while_a_job_runs_cancels_it_and_a_late_delta_is_never_spoken(rig):
    rig.ask()
    first = rig.fake.run(0)
    first.say('Инерция — это свойство')
    rig.pump()
    rig.ask(PHOTO, 'u2')
    second = rig.fake.run(1)
    assert second.question.startswith('Что такое фотосинтез')
    assert until(lambda: first.cancelled.is_set())
    first.script.put(('delta', ' тела сохранять своё состояние движения или покоя.'))
    rig.pump()
    rig.say(1, PHOTO.answer)
    assert all('Инерция' not in cue for cue in rig.cues()) and rig.cues()


def test_stop_while_a_job_runs_silences_it(rig):
    rig.ask()
    rig.say(0, 'Инерция — это свойство')
    rig.w.feed(S.turn_done('u2', 'user', 'стоп'))
    rig.pump()
    rig.fake.run(0).script.put(('delta', ' тела сохранять своё состояние движения или покоя.'))
    rig.pump()
    assert rig.cues() == [] and rig.w.controller.question_id is None


def test_the_ack_of_a_fast_answers_portions_advances_as_usual(rig):
    rig.ask()
    rig.say(0, ANSWER)
    rig.fake.run(0).finish()
    rig.pump(0.5)
    assert rig.cues() == [FIRST_CUE]
    index = rig.w.controller.state()['chunk_index']
    rig.w.feed(S.turn_done('u2', 'user', S.relaxed(FIRST_CUE)))
    rig.pump(0.5)
    assert rig.w.controller.state()['chunk_index'] == index + 1 and rig.cues()[-1] == SECOND
    rig.w.feed(S.turn_done('u3', 'user', S.relaxed(SECOND)))
    rig.pump(0.5)
    assert rig.w.controller.state()['completed']


def test_the_lookup_route_on_the_wire_sends_the_sources_to_the_job_and_the_context_to_the_cloud(rig):
    question = 'Проверь, пожалуйста, что такое гидравлический удар.'
    rig.w.feed(S.turn_created('u1', 'user', 'Проверь'))
    rig.w.feed(S.turn_done('u1', 'user', question))
    rig.pump()
    assert rig.w.lookup_calls, 'the lookup runs'
    run = rig.fake.run(0)
    sent = [m['content'][0]['text'] for m in run.request['input']]
    assert sent[0] == native_result_text(rig.w.controller.question_text, S.SOURCE_ROWS) and sent[-1] == rig.w.controller.question_text
    assert any(json.loads(p).get('type') == 'session.context.append' for k, p in rig.w.source.frames if k == 'E'), 'the cloud still gets its context'
    rig.say(0, 'Гидравлический удар — резкий скачок давления в трубопроводе. Он возникает при внезапной остановке потока.')
    assert rig.cues() and rig.w.controller.engine.state(rig.w.session_id)['retrieval_status'] == 'source_backed'


def test_no_source_on_the_wire_asks_the_job_to_answer_from_knowledge(rig, monkeypatch):
    monkeypatch.setattr(S, 'SOURCE_ROWS', [])
    rig.w.feed(S.turn_created('u1', 'user', 'Проверь'))
    rig.w.feed(S.turn_done('u1', 'user', VERIFY))
    rig.pump()
    run = rig.fake.run(0)
    assert run.request['input'][0]['content'][0]['text'] == FT.NO_SOURCE_BRAIN
    rig.say(0, 'Гидравлический удар — резкий скачок давления в трубопроводе. Он возникает при остановке потока.')
    assert rig.cues() and rig.w.controller.engine.state(rig.w.session_id)['retrieval_status'] == 'unsourced'


def test_current_data_without_a_source_gets_no_job_on_the_wire(rig, monkeypatch):
    monkeypatch.setattr(S, 'SOURCE_ROWS', [])
    rig.w.feed(S.turn_created('u1', 'user', 'Проверь'))
    rig.w.feed(S.turn_done('u1', 'user', CURRENT))
    rig.pump()
    assert rig.fake.runs == []


def test_a_running_ear_does_not_get_in_the_way_when_it_acts(rig):
    rig.w.wire.ear.acting = True
    rig.hear('Что такое инерция')
    assert len(rig.fake.runs) == 1 and rig.w.controller.ear_off is False


def test_one_whole_exchange_on_the_wire(rig, caplog):
    caplog.set_level(logging.INFO, logger='echo-sync')
    rig.hear('Что такое инерция')
    rig.say(0, 'Инерция — это свойство тела ')
    rig.ask()
    rig.say(0, 'сохранять своё состояние движения или покоя. ')
    assert rig.cues() == [FIRST_CUE]
    rig.say(0, SECOND)
    rig.fake.run(0).finish()
    rig.pump(0.5)
    rig.w.feed(S.turn_done('u2', 'user', S.relaxed(FIRST_CUE)))
    rig.pump(0.5)
    assert rig.cues() == [FIRST_CUE, SECOND]
    rig.w.feed(S.turn_done('u3', 'user', S.relaxed(SECOND)))
    rig.pump(0.5)
    state = rig.w.controller.state()
    assert state['completed'] and state['answer'] == STORED and len(rig.fake.runs) == 1 and rig.w.errors == [] and rig.w.violations == []
    lines = [r.getMessage() for r in caplog.records if 'fast_text' in r.getMessage()]
    assert any('outcome=ok' in l for l in lines), lines
    assert 'свойство' not in '\n'.join(lines).casefold()


def test_a_wake_on_the_loop_pumps_the_text_at_once_without_waiting_for_the_tick(rig):
    rig.ask()
    rig.fake.run(0).say(ANSWER)

    async def wake():
        rig.w.wire.fast_wake()
    rig.w.run(wake())
    rig.w.settle()
    assert rig.cues() == [FIRST_CUE], 'no tick was run: the wake alone pumped the job into the controller'


def test_the_host_builds_the_channel_from_the_profile_and_gives_it_the_sign_in_and_the_wake():
    import ast
    from pathlib import Path
    import echo_sync
    source = (Path(echo_sync.__file__).parent / 'controlled_host.py').read_text(encoding='utf-8')
    calls = [n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Call) and getattr(n.func, 'attr', None) == 'for_call'
             and getattr(n.func.value, 'id', None) == 'fast_text']
    assert len(calls) == 1 and {k.arg for k in calls[0].keywords} >= {'credentials', 'instructions', 'wake'}
    assert "api._run_scoped(profile,lambda:api._codex_credentials())" in source, 'the sign-in is read the way every other sign-in of the call is'
    assert "fast_text=profile_settings['fast_text']" not in source and 'settings=controller_settings(profile_settings)' in source


def test_a_released_job_that_is_over_but_not_yet_handed_on_is_not_replaced_by_a_prepare():
    fast, fake, _ = manager()
    fast.release(qid='u1', turn='fast-1', epoch=1, question='Что такое инерция')
    run = fake.run(0)
    run.say(FIRST)
    run.finish()
    assert until(lambda: fast.job.done)
    assert fast.prepare('Что такое фотосинтез') is False and len(fake.runs) == 1
    assert kinds(fast.poll()) == ['text', 'done'], 'the text of the answer of the open question is not lost'


# =====================================================================================================================================
# R. the review round: every test below failed before its fix
# =====================================================================================================================================

def cloud_says(rig, tid, text):
    rig.w.feed(S.turn_created(tid, 'assistant', text.split()[0]))
    rig.w.feed(S.turn_done(tid, 'assistant', text))


def user_says(rig, uid, text):
    rig.w.feed(S.turn_created(uid, 'user', text.split()[0]))
    rig.w.feed(S.turn_done(uid, 'user', text))


def errors_of(rig):
    return [e['error']['code'] for e in rig.w.errors]


def plan_waiting(rig):
    """The first portion of an answer is cued and the listener has not repeated it yet (the job failed, the cloud's answer is the plan)."""
    rig.ask()
    rig.fake.run(0).fail()
    rig.pump(0.2)
    cloud_says(rig, 'a1', ANSWER)
    rig.pump(1.0)
    assert rig.w.controller.state()['chunk_index'] == 0 and rig.cues() == [FIRST_CUE]


PLANETS = 'Сколько всего планет в Солнечной системе?'
EIGHT = 'В Солнечной системе восемь планет.'
BYSTANDER = 'Маш, а ты не видела ключи от машины?'
TEA = 'Маша, ты будешь чай или кофе?'
HEAD = 'Как называется переход вещества в'
JOB1 = 'Это называется конденсация, потому что пар остывает и оседает на стенках сосуда'


# -- the Codex stream: only response.completed is the end of an answer ----------------------------------------------------------------------

@pytest.mark.parametrize('ending, token', [([], 'no_terminal_event'), ([{'type': 'error'}], 'error'), ([{'type': 'response.incomplete'}], 'response_incomplete'),
                                           ([{'type': 'response.failed'}], 'response_failed')])
def test_a_stream_that_does_not_end_in_completed_is_a_failure_not_a_finished_answer(ending, token):
    lines = sse({'type': 'response.output_text.delta', 'delta': 'Амортизация — это постепенн'}, *ending)
    stream = CR.codex_stream(lambda: (SECRET, 'a'), client_factory=lambda: FakeHttp(FakeResponse(200, lines)))
    got = []
    with pytest.raises(CR.FastTextError) as error:
        for delta in stream({}, threading.Event()):
            got.append(delta)
    assert got == ['Амортизация — это постепенн'] and str(error.value) == token


def test_a_call_cancelled_as_its_lines_run_out_is_no_failure():
    cancelled = threading.Event()
    stream = CR.codex_stream(lambda: (SECRET, 'a'), client_factory=lambda: FakeHttp(FakeResponse(200, sse({'type': 'response.output_text.delta', 'delta': 'a'}))))
    got = []
    for delta in stream({}, cancelled):
        got.append(delta)
        cancelled.set()
    assert got == ['a']


def test_when_the_job_and_the_cloud_both_decline_it_is_quiet_as_designed(rig):
    rig.ask()
    rig.say(0, 'Угу.')
    rig.fake.run(0).finish()
    rig.pump(0.3)
    cloud_says(rig, 'a1', 'Угу.')
    rig.pump(20.0)
    assert rig.cues() == [] and errors_of(rig) == []


# -- a fault of the pump hands the answer back to the cloud ----------------------------------------------------------------------------------

def break_once(controller):
    real, calls = controller.fast_feed, []

    def broken(*args, **keywords):
        calls.append(args)
        if len(calls) == 1:
            raise RuntimeError('boom')
        return real(*args, **keywords)
    controller.fast_feed = broken
    return calls


def test_a_fault_of_the_pump_shuts_the_channel_and_the_clouds_answer_is_not_ignored(rig):
    c = rig.w.controller
    rig.ask()
    rig.say(0, 'Инерция — это')
    assert c.fast_turn == 'fast-1' and not c.published
    break_once(c)
    rig.say(0, ' свойство')
    # c23: level 1 of 06.11 (laptop 2416fe0, tests/test_pump_fault.py): one fault of the pump costs its job, the channel stays; was ``rig.fast.off``
    assert not rig.fast.off and c.fast_turn is None and 'fast-1' in c.retired_assistants
    cloud_says(rig, 'a1', ANSWER)
    rig.pump(0.5)
    assert rig.cues() == [FIRST_CUE] and errors_of(rig) == []


def test_a_fault_of_the_pump_after_the_answer_began_ends_it_where_it_broke(rig):
    c = rig.w.controller
    rig.ask()
    rig.say(0, FIRST + ' ')
    assert rig.cues() == [FIRST_CUE]
    break_once(c)
    rig.say(0, SECOND)
    # c23: level 1 of 06.11 (laptop 2416fe0, tests/test_pump_fault.py): one fault of the pump costs its job, the channel stays; was ``rig.fast.off``
    assert not rig.fast.off and c.state()['answer'] == FIRST_CUE and not c.state()['streaming'], 'the stream is closed at once, not after the 30 s stall'


# -- a job that breaks after the answer began ends it at a whole sentence, never in a torn word ---------------------------------------------------

LONG_TAIL = ' Чем больше масса тела и чем сильнее оно разогнано на длинной дистанции, тем труднее его остановить за короткое время, и тем больше тормозной пу'


def acked(rig, seconds=0.5):
    """The listener repeats the last cue; returns the cue."""
    cue = rig.cues()[-1]
    rig.w.feed(S.turn_done('r%d' % len(rig.cues()), 'user', S.relaxed(cue)))
    rig.pump(seconds)
    return cue


def test_a_failure_after_the_answer_began_never_dictates_the_torn_word(rig):
    rig.ask()
    rig.say(0, FIRST + ' ')
    rig.say(0, 'Чем больше ма')
    rig.fake.run(0).fail()
    rig.pump(0.5)
    cloud_says(rig, 'a1', ANSWER)
    rig.pump(0.5)
    acked(rig)
    rig.pump(10.0)
    state = rig.w.controller.state()
    assert rig.cues() == [FIRST_CUE] and state['answer'] == FIRST_CUE and state['completed'] and not state['streaming'], (rig.cues(), state)


def test_a_stream_that_ends_in_a_torn_word_without_completed_is_closed_at_the_last_sentence(rig):
    """The real endpoint can end a stream without ``response.completed``: codex_stream makes that a failure, so the torn word is never dictated."""
    lines = sse({'type': 'response.output_text.delta', 'delta': FIRST + ' Чем больше ма'})
    rig.fast.stream = rig.fast.roads = RT.Roads(CR.codex_stream(lambda: (SECRET, 'a'), client_factory=lambda: FakeHttp(FakeResponse(200, lines))), None, clock=rig.w.clock.now)      # the channel's stream is the roads that own the road
    rig.ask()
    assert until(lambda: rig.fast.job.done)
    rig.pump(0.5)
    cloud_says(rig, 'a1', ANSWER)
    rig.pump(0.5)
    acked(rig)
    rig.pump(10.0)
    state = rig.w.controller.state()
    assert rig.cues() == [FIRST_CUE] and state['answer'] == FIRST_CUE and state['completed'], (rig.cues(), state)


def test_a_failure_after_a_mid_sentence_publication_closes_on_what_was_published_without_a_rewrite(rig):
    rig.ask()
    rig.say(0, FIRST)
    rig.pump(0.3)
    acked(rig, 1.0)
    rig.say(0, LONG_TAIL)
    rig.pump(6.0)
    rig.say(0, 'та')
    rig.pump(0.5)
    published = rig.w.controller.published
    rig.fake.run(0).fail()
    rig.pump(0.5)
    for _ in range(6):
        acked(rig, 1.0)
    state = rig.w.controller.state()
    assert not any('Поправка' in cue for cue in rig.cues()), rig.cues()
    assert not any(cue.rstrip('.,').endswith(('пу', 'пута')) for cue in rig.cues()), rig.cues()
    assert state['completed'] and not state['streaming'] and ' '.join(rig.cues()).startswith(FIRST_CUE) and state['answer'].startswith(published), (rig.cues(), state)


# -- the restorable seam does not restore a dead fast turn -----------------------------------------------------------------------------------

def seam(rig, text):
    """«Как называется переход вещества в» + the job's start of an answer, then «газообразное» joins the question (coalesce): job 1 is dead, job 2 asked."""
    c = rig.w.controller
    user_says(rig, 'u1', HEAD)
    rig.pump(1.6)                              # H6 item 3: a final on an open tail waits 1.5 s for its rest before the job goes
    rig.say(0, text)
    rig.w.feed(S.turn_created('u2', 'user', 'газ'))
    rig.w.feed(S.turn_done('u2', 'user', 'газообразное'))
    rig.pump(0.1)
    assert c.question_id == 'u2' and len(rig.fake.runs) == 2 and rig.fake.run(0).cancelled.is_set(), (c.question_id, len(rig.fake.runs))
    return c


def test_the_join_of_a_cut_question_does_not_block_the_cloud_with_job_ones_text(rig):
    c = seam(rig, 'Это называется сублим')
    assert c.fast_turn is None and c.source_segment_id != 'fast-1' and 'fast-1' in c.retired_assistants
    rig.fake.run(1).fail()
    rig.pump(0.2)
    cloud_says(rig, 'a2', 'Это называется сублимация.')
    rig.pump(30.0)
    assert any('сублимация' in cue for cue in rig.cues()) and errors_of(rig) == [], (rig.cues(), errors_of(rig))


def test_job_twos_failure_after_a_piece_does_not_bring_job_ones_text_back(rig):
    c = seam(rig, JOB1)
    rig.say(1, 'Это назы')
    rig.fake.run(1).fail()
    rig.pump(0.2)
    cloud_says(rig, 'a2', 'Это называется сублимация.')
    rig.pump(10.0)
    assert not any('конденсация' in cue for cue in rig.cues()) and any('сублимация' in cue for cue in rig.cues()), rig.cues()


def test_the_watchdog_does_not_dictate_job_ones_text_when_job_two_fails_and_the_cloud_answers(rig):
    seam(rig, JOB1)
    rig.fake.run(1).fail()
    rig.pump(0.2)
    cloud_says(rig, 'a2', 'Это называется сублимация.')
    rig.pump(30.0)
    assert any('сублимация' in cue for cue in rig.cues()) and not any('конденсация' in cue for cue in rig.cues()), rig.cues()


def test_the_watchdog_does_not_dictate_job_ones_text_when_job_two_fails_and_the_cloud_is_silent(rig):
    seam(rig, JOB1)
    rig.fake.run(1).fail()
    rig.pump(30.0)
    assert not any('конденсация' in cue for cue in rig.cues()), rig.cues()


def test_when_job_two_wins_after_the_join_it_is_the_answer(rig):
    seam(rig, 'Это называется сублим')
    rig.say(1, 'Это называется сублимация.')
    rig.fake.run(1).finish()
    rig.pump(10.0)
    assert any('сублимация' in cue for cue in rig.cues()), rig.cues()


def test_the_clouds_scaffolding_before_the_join_survives_it(rig):
    c = rig.w.controller
    user_says(rig, 'u1', HEAD)
    rig.w.feed(S.turn_created('a1', 'assistant', 'Это'))
    rig.w.feed(S.turn_done('a1', 'assistant', 'Это называется'))
    rig.pump(1.6)
    rig.say(0, JOB1)
    rig.w.feed(S.turn_created('u2', 'user', 'газ'))
    rig.w.feed(S.turn_done('u2', 'user', 'газообразное'))
    rig.pump(0.1)
    rig.fake.run(1).fail()
    rig.pump(0.2)
    cloud_says(rig, 'a2', 'сублимация.')
    rig.pump(RT.ALL_DEAD_S + 1.0)      # the roads give a hung job up at ALL_DEAD_S (there is no first-text bound of 4 s)
    assert any('сублимация' in cue for cue in rig.cues()) and not any('конденсация' in cue for cue in rig.cues()), rig.cues()


def test_a_job_that_finished_its_sentence_before_the_join_is_retired_and_the_cloud_goes_on(rig):
    c = rig.w.controller
    user_says(rig, 'u1', HEAD)
    rig.pump(1.6)
    rig.say(0, 'Это называется конденсация.')
    rig.fake.run(0).finish()
    rig.pump(0.1)
    rig.w.feed(S.turn_created('u2', 'user', 'газ'))
    rig.w.feed(S.turn_done('u2', 'user', 'газообразное'))
    rig.pump(0.1)
    rig.fake.run(1).fail()
    rig.pump(0.2)
    cloud_says(rig, 'a2', 'Это называется сублимация.')
    rig.pump(RT.ALL_DEAD_S + 1.0)      # the roads give a hung job up at ALL_DEAD_S (there is no first-text bound of 4 s)
    assert any('сублимация' in cue for cue in rig.cues()), rig.cues()


# -- the host's wake pumps inside the call's trace -------------------------------------------------------------------------------------------

def test_the_wake_driven_pump_runs_in_the_calls_trace_context(tmp_path, monkeypatch, caplog):
    """controlled_host.serve with the real fast_text.for_call and the host's own wake, a job thread that wakes the loop and no tick before the wake: the
    decisions the pump makes (fast_text_owns, the question's) are rows of the call trace, as when the tick pumps."""
    import asyncio
    from pathlib import Path
    import helpers_s6_fault as F
    fake = FakeStream()
    monkeypatch.setattr(CR, 'codex_stream', lambda credentials: fake)
    caplog.set_level(logging.INFO, logger='echo-sync')

    async def main():
        F.patch_clock(monkeypatch)
        async with F.HostRig(tmp_path, monkeypatch) as host:
            folder = host.home / 'materials'
            folder.mkdir(parents=True, exist_ok=True)
            (folder / 'echo_settings.json').write_text(json.dumps({'fast_text': 'on', 'call_trace': 'on'}), encoding='utf-8')
            await host.handshake()
            await host.ask(F.DIRECT_QUESTION, tid='u1')
            fake.run(0).say(F.DIRECT_ANSWER)
            for _ in range(5):
                await asyncio.sleep(0)              # no virtual time passes: no tick can run, only the wake
            await host.advance(3)
            spoken = host.spoken()
            files = sorted((f for f in (Path(host.home) / 'logs' / 'echo_calls').glob('*.jsonl') if '.v5tap' not in f.name))
            assert len(files) == 1, files
            rows = [json.loads(line) for line in files[0].read_text(encoding='utf-8').splitlines()]
            fake.run(0).finish()
            await host.advance(1)
        return rows, spoken
    rows, spoken = F.run(main)
    assert spoken, 'the fast text was spoken'
    assert any(r['ev'] == 'decision' and r.get('reason') == 'fast_text_owns' for r in rows), [(r['ev'], r.get('reason')) for r in rows]


pytestmark = pytest.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)
