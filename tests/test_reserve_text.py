"""reserve_text: the text job has a second road when the first refuses (the evening of 10.11.2026: the Codex quota was out before a talk)."""
import json
import threading

import pytest

from echo_sync import fast_text, reserve_text
from echo_sync import codex_road as CR
from echo_sync.reserve_text import ReserveError, ReserveStream, Roads, chat_body


@pytest.fixture(autouse=True)
def _fresh():
    reserve_text._REST.clear()
    reserve_text._PRIMARY['until'] = 0.0
    yield
    reserve_text._REST.clear()
    reserve_text._PRIMARY['until'] = 0.0


def sse(*texts):
    return [f'data: {json.dumps({"choices": [{"delta": {"content": t}}]})}' for t in texts] + ['data: [DONE]']


def request():
    return fast_text.build_request('Когда была Полтавская битва?', instructions='Ты суфлёр.', material='Справка: 1709 год.')


def test_the_request_of_the_job_becomes_a_chat_with_the_same_instructions_and_words():
    body = chat_body(request(), 'openai/gpt-oss-120b')
    assert body['messages'][0] == {'role': 'system', 'content': 'Ты суфлёр.'}
    assert [m['content'] for m in body['messages'][1:]] == ['Справка: 1709 год.', 'Когда была Полтавская битва?']
    assert body['stream'] is True and body['reasoning_effort'] == 'low'


def test_the_first_road_that_answers_gives_the_answer_and_a_refusing_road_rests():
    asked = []

    def post(url, headers, body, timeout):
        asked.append((headers['Authorization'], body['model']))
        if headers['Authorization'].endswith('one'):
            raise ReserveError('http_429')
        yield from sse('В 1709 ', 'году.')
    stream = ReserveStream({'GROQ_API_KEY': 'one', 'GROQ_API_KEY_2': 'two'}, post=post, clock=lambda: 100.0)
    assert ''.join(stream(request(), threading.Event())) == 'В 1709 году.'
    assert [a[0][-3:] for a in asked] == ['one', 'two']
    asked.clear()
    assert ''.join(stream(request(), threading.Event())) == 'В 1709 году.'
    assert [a[0][-3:] for a in asked] == ['two']                 # the road that said no is not asked again at once


def test_no_road_is_a_failure_of_the_job_and_no_key_is_no_reserve():
    def post(url, headers, body, timeout):
        raise ReserveError('http_400')
        yield
    stream = ReserveStream({'GEMINI_API_KEY': 'k'}, post=post)
    with pytest.raises(ReserveError):
        list(stream(request(), threading.Event()))
    assert not ReserveStream({})
    primary = object()
    alone = reserve_text.for_stream(primary, keys={})      # one road: the first road alone is still Roads
    assert isinstance(alone, reserve_text.Roads) and alone.primary is primary and not alone.backup


def test_a_primary_that_refuses_before_its_first_word_is_answered_by_the_reserve_and_rests():
    calls = []

    class Primary:
        first_text_s = 4.0

        def __call__(self, request, cancelled):
            calls.append('primary')
            raise CR.FastTextError('http_429')
            yield

        def warm(self):
            return 'warm'
    now = [0.0]
    reserve = ReserveStream({'GROQ_API_KEY': 'k'}, post=lambda *a: iter(sse('Ответ.')), clock=lambda: now[0])
    stream = Roads(Primary(), reserve, clock=lambda: now[0])
    assert ''.join(stream(request(), threading.Event())) == 'Ответ.'
    assert ''.join(stream(request(), threading.Event())) == 'Ответ.'
    assert calls == ['primary']                                  # a quota refusal is not asked again every question
    now[0] = reserve_text.PRIMARY_QUOTA_REST_S + 1
    list(stream(request(), threading.Event()))
    assert calls == ['primary', 'primary']
    assert stream.warm() == 'warm' and stream.reserve
    stream.first_text_s = 9.0
    assert stream.primary.first_text_s == 9.0


def test_a_primary_that_fails_after_its_first_word_is_the_failure_of_the_job():
    def primary(request, cancelled):
        yield 'Начало '
        raise CR.FastTextError('no_terminal_event')
    stream = Roads(primary, ReserveStream({'GROQ_API_KEY': 'k'}, post=lambda *a: iter(sse('другое'))))
    got = []
    with pytest.raises(CR.FastTextError):
        for delta in stream(request(), threading.Event()):
            got.append(delta)
    assert got == ['Начало ']


def test_the_channel_of_a_call_is_always_the_roads_with_the_reserve_of_the_keys_there_are(monkeypatch):
    class Controller:
        settings = {}
        fast_exchanges = staticmethod(lambda: [])
        fast_in_play = staticmethod(lambda: None)
        ear_ended = None
        source_segment_id = None
        refuse_deadline = decision_due = staticmethod(lambda *a: None)      # no question open, no bound
    profile = {'fast_text': 'on', 'local_ear': 'act'}
    monkeypatch.setattr(reserve_text, 'read_keys', lambda path=None: {'GROQ_API_KEY': 'k'})
    on = fast_text.for_call(profile, Controller(), credentials=lambda: ('t', 'a'))
    alone = fast_text.for_call(profile, Controller(), credentials=None)
    monkeypatch.setattr(reserve_text, 'read_keys', lambda path=None: {})
    bare = fast_text.for_call(profile, Controller(), credentials=lambda: ('t', 'a'))
    nothing = fast_text.for_call(profile, Controller(), credentials=None)
    try:
        assert on.roads is on.stream and on.stream.primary is not None and on.stream.backup
        assert alone.stream.primary is None and alone.stream.backup
        assert bare.roads is bare.stream and bare.stream.primary is not None and not bare.stream.backup      # no keys: the first road alone, still the roads
        assert nothing is None      # no sign-in and no key: no road, no channel
    finally:
        for channel in (on, alone, bare):
            close = getattr(channel, 'close', None)
            if close:
                close()
