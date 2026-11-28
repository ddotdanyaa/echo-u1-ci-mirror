"""reserve_text, the night of 13.11.2026 (REVIEW_20261112/night/H_roads.md, L4_answers.md): which roads there are by default, and (the budget, always)
which of them a question is asked first: the one whose minute, as the provider's own headers tell it, still holds the question."""
import json
import sys
import threading
import types

import pytest

from echo_sync import fast_text, reserve_text
from echo_sync.reserve_text import ReserveError, ReserveStream

MODEL = 'openai/gpt-oss-120b'


@pytest.fixture(autouse=True)
def _fresh():
    for table in (reserve_text._REST, reserve_text._BUDGET):
        table.clear()
    yield
    for table in (reserve_text._REST, reserve_text._BUDGET):
        table.clear()


def sse(*texts):
    return [f'data: {json.dumps({"choices": [{"delta": {"content": t}}]})}' for t in texts] + ['data: [DONE]']


def cost(prompt, out=70, cached=0):
    """The last chunk of a Groq stream: no choice, the usage of the request."""
    usage = {'prompt_tokens': prompt, 'completion_tokens': out, 'total_tokens': prompt + out, 'prompt_tokens_details': {'cached_tokens': cached}}
    return 'data: ' + json.dumps({'choices': [], 'x_groq': {'usage': usage}})


def told(left, back='30s', limit=8000, day_left=990, day_limit=1000):
    """The headers of a Groq answer that speak of the key's limits."""
    return {'x-ratelimit-limit-tokens': str(limit), 'x-ratelimit-remaining-tokens': str(left), 'x-ratelimit-reset-tokens': back,
            'x-ratelimit-limit-requests': str(day_limit), 'x-ratelimit-remaining-requests': str(day_left)}


def request(chars=0):
    return fast_text.build_request('Когда была Полтавская битва?', instructions='Ты суфлёр.' + ' правило' * (chars // 8))


def test_the_default_roads_are_the_ones_that_answer_and_the_stronger_model_stands_first():
    roads = [(name, model) for name, _, model in reserve_text.ROADS]
    assert roads == [('GROQ_API_KEY', 'openai/gpt-oss-120b'), ('GROQ_API_KEY_2', 'openai/gpt-oss-120b'),
                     ('GROQ_API_KEY', 'openai/gpt-oss-20b'), ('GROQ_API_KEY_2', 'openai/gpt-oss-20b'),
                     ('GEMINI_API_KEY', 'gemini-3.5-flash-lite'), ('GEMINI_API_KEY_2', 'gemini-3.5-flash-lite'),
                     ('GROQ_API_KEY', 'qwen/qwen3.8-27b'), ('GROQ_API_KEY_2', 'qwen/qwen3.8-27b')]
    assert not any('openrouter' in base for _, base, _ in reserve_text.ROADS)      # 13.11 00:05: its free model answers 429 (H_roads.md)


def test_a_key_that_no_road_uses_is_not_read(tmp_path):
    path = tmp_path / 'providers.env'
    path.write_text('OPENROUTER_API_KEY=aaa\nGROQ_API_KEY="bbb"\nGEMINI_API_KEY_2=ccc # note\nOTHER_API_KEY=ddd\n', encoding='utf-8')
    assert reserve_text.read_keys(str(path)) == {'GROQ_API_KEY': 'bbb', 'GEMINI_API_KEY_2': 'ccc'}
    assert {name for name, _, _ in reserve_text.ROADS} <= {'GROQ_API_KEY', 'GROQ_API_KEY_2', 'GEMINI_API_KEY', 'GEMINI_API_KEY_2'}


# --- what the provider says of a road's limits ------------------------------------------------------------------------------------

def test_the_durations_of_a_provider_are_read_in_seconds():
    assert [reserve_text._seconds(text) for text in ('7.66s', '360ms', '1m2.5s', '2h', '12', '1h2m3s')] == [7.66, 0.36, 62.5, 7200.0, 12.0, 3723.0]
    assert [reserve_text._seconds(text) for text in ('', None, 'soon', '5 parsecs', '-3s')] == [None] * 5


def test_what_the_headers_say_of_a_road_is_kept_by_numbers_and_the_cost_of_the_answer_goes_with_it():
    def post(url, headers, body, timeout):
        yield told(3438, '34.2s')
        yield from sse('В 1709 ', 'году.')[:-1]
        yield cost(4562, cached=4096)
        yield 'data: [DONE]'
    stream = ReserveStream({'GROQ_API_KEY': 'one'}, post=post, clock=lambda: 100.0)
    got = list(stream(request(), threading.Event()))
    assert ''.join(piece for piece in got if isinstance(piece, str)) == 'В 1709 году.'
    assert [piece for piece in got if not isinstance(piece, str)] == [{'usage': {'input_tokens': 4562, 'output_tokens': 70, 'total_tokens': 4632, 'cached_tokens': 4096,
                                                                               'road': 'GROQ_API_KEY', 'model': MODEL}}]
    known = reserve_text.limits('GROQ_API_KEY', MODEL)
    assert (known['limit'], known['left'], known['back'], known['at']) == (8000, 3438, 34.2, 100.0)
    assert (known['day_limit'], known['day_left']) == (1000, 990)
    assert (known['prompt'], known['cached'], known['out']) == (4562, 4096, 70)
    assert reserve_text.limits('GROQ_API_KEY_2', MODEL) == {}
    assert all(isinstance(value, (int, float)) for value in known.values())      # numbers only: never a word, never a key


def test_headers_that_say_nothing_of_limits_change_nothing():
    def post(url, headers, body, timeout):
        yield {'x-ratelimit-limit-tokens': 'many', 'x-ratelimit-remaining-tokens': ''}
        yield from sse('Ответ.')
    assert list(ReserveStream({'GEMINI_API_KEY': 'k'}, post=post)(request(), threading.Event())) == ['Ответ.']
    assert reserve_text.limits('GEMINI_API_KEY', 'gemini-3.5-flash-lite') == {}


class _Response:
    def __init__(self, status, headers, lines=(), body=b''):
        self.status_code, self.headers, self.lines, self.body = status, headers, lines, body

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def iter_lines(self):
        return iter(self.lines)

    def read(self):
        return self.body


def _httpx(monkeypatch, response):
    class Client:
        def __init__(self, **_):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def stream(self, method, url, headers=None, json=None):
            return response
    monkeypatch.setitem(sys.modules, 'httpx', types.SimpleNamespace(Client=Client))


def test_the_real_post_hands_over_the_limit_headers_first_and_nothing_else_of_the_headers(monkeypatch):
    headers = {'X-RateLimit-Remaining-Tokens': '3438', 'x-ratelimit-limit-tokens': '8000', 'Retry-After': '7', 'Set-Cookie': 'secret', 'x-request-id': 'req_1', 'Authorization': 'Bearer no'}
    _httpx(monkeypatch, _Response(200, headers, sse('Ответ.')))
    got = list(reserve_text._post('https://example.invalid/chat/completions', {}, {}, 6.0))
    assert got[0] == {'x-ratelimit-remaining-tokens': '3438', 'x-ratelimit-limit-tokens': '8000', 'retry-after': '7'}
    assert got[1:] == sse('Ответ.')


def test_a_refusal_of_the_real_post_carries_what_the_provider_said_of_the_wait(monkeypatch):
    body = json.dumps({'error': {'message': 'Rate limit reached for model `openai/gpt-oss-120b` in organization `org_secret` service tier `on_demand` on tokens per minute (TPM): '
                                            'Limit 8000, Used 6540, Requested 4562. Please try again in 23.265s. Need more tokens? Upgrade', 'code': 'rate_limit_exceeded'}}).encode()
    _httpx(monkeypatch, _Response(429, {'retry-after': '24', 'x-ratelimit-remaining-tokens': '1460'}, body=body))
    with pytest.raises(ReserveError) as refused:
        list(reserve_text._post('https://example.invalid/chat/completions', {}, {}, 6.0))
    assert str(refused.value) == 'http_429'
    assert refused.value.headers == {'retry-after': '24', 'x-ratelimit-remaining-tokens': '1460'}
    assert refused.value.said == {'kind': 'TPM', 'limit': 8000, 'used': 6540, 'asked': 4562, 'again': 23.265}      # numbers and the kind of the limit: no organization, no text


# --- reserve_budget: a question goes first to the road whose minute holds it ----------------------------------------------------------
# Measured 13.11 03:41-03:49, 60 answers of Groq (REVIEW_20261112/night/L4_answers.md): a request is charged its prompt and the whole of max_tokens when it is asked, the tokens return at
# limit / 60 a second (the reset header is exactly (limit - left) * 60 / limit), and what the answer did not write of max_tokens comes back after it.

KEYS = {'GROQ_API_KEY': 'one', 'GROQ_API_KEY_2': 'two'}
SMALL = 'openai/gpt-oss-20b'


class Provider:
    """Two keys' roads: an answer tells what is left of the minute of the road asked (``left``, 8 000 when not named) and costs a third of a token a character; a road in ``refuse`` raises."""

    def __init__(self, left=None, refuse=None):
        self.asked, self.left, self.refuse = [], dict(left or {}), dict(refuse or {})

    def __call__(self, url, headers, body, timeout):
        road = (headers['Authorization'].split()[-1], body['model'])
        self.asked.append(road)
        if road in self.refuse:
            raise self.refuse[road]
        yield told(self.left.get(road, 8000))
        yield from sse('Ответ.')[:-1]
        yield cost(sum(len(message['content']) for message in body['messages']) // 3, out=60)
        yield 'data: [DONE]'


def text(stream, asked):
    return ''.join(piece for piece in stream(asked, threading.Event()) if isinstance(piece, str))


def spent(*roads, now=100.0, left=300):
    for road in roads:
        reserve_text._note(road, now, told(left))


def test_the_weight_of_a_request_is_its_prompt_and_the_whole_allowance_of_the_answer():
    body = reserve_text.chat_body(request(chars=6000), MODEL)
    chars = sum(len(message['content']) for message in body['messages'])
    assert reserve_text._weight(body) == int(chars * reserve_text.TOKENS_PER_CHAR) + reserve_text.MAX_TOKENS      # nothing told yet: the stated share of a token a character
    reserve_text._note(('GROQ_API_KEY', MODEL), 100.0, cost={'input_tokens': 2000, 'output_tokens': 60}, chars=6400)
    assert reserve_text._weight(body) == int(chars * 2000 / 6400) + reserve_text.MAX_TOKENS      # an answer told what a character costs
    reserve_text._note(('GROQ_API_KEY_2', MODEL), 100.0, cost={'input_tokens': 900, 'output_tokens': 60}, chars=30)
    assert reserve_text._weight(body) == chars + reserve_text.MAX_TOKENS      # a tiny request tells nothing of a big one: never more than a token a character


def test_the_room_of_a_road_is_what_was_left_what_the_answer_did_not_write_and_what_returned_since():
    road = ('GROQ_API_KEY', MODEL)
    assert reserve_text._room(road, 100.0) is None      # the provider has said nothing
    reserve_text._note(road, 100.0, told(1000))
    assert reserve_text._room(road, 100.0) == 1000 and reserve_text._room(road, 106.0) == 1800      # 8 000 a minute
    reserve_text._note(road, 101.0, cost={'input_tokens': 2000, 'output_tokens': 60}, chars=6400, allowance=900)
    assert reserve_text._room(road, 100.0) == 1840      # the 840 tokens of the answer's allowance that were not written come back
    assert reserve_text._room(road, 400.0) == 8000      # never more than the limit
    reserve_text._note(road, 110.0, told(4000))
    assert reserve_text._room(road, 110.0) == 4000      # the next headers are the provider's own word again


def test_a_road_whose_minute_is_spent_is_asked_after_the_roads_that_have_room(caplog):
    provider, now = Provider(left={('one', MODEL): 1000}), [100.0]
    stream = ReserveStream(KEYS, post=provider, clock=lambda: now[0])
    big = request(chars=6000)      # about 2 000 tokens and the 900 of the answer
    assert text(stream, big) == 'Ответ.'      # nothing known: the first road, and it says 1 000 are left
    now[0] += 2.0
    with caplog.at_level('INFO', logger='echo-sync'):
        assert text(stream, big) == 'Ответ.'      # the second question in a row: the other key, with no refusal on the way
    assert provider.asked == [('one', MODEL), ('two', MODEL)]
    assert any('reserve_text budget road=GROQ_API_KEY model=openai/gpt-oss-120b' in record.getMessage() for record in caplog.records)
    now[0] += 30.0      # half a minute returns 4 000 tokens
    text(stream, big)
    assert provider.asked[-1] == ('one', MODEL)


def test_a_small_question_is_asked_of_a_road_that_a_big_one_would_not_fit():
    provider = Provider()
    stream = ReserveStream(KEYS, post=provider, clock=lambda: 100.0)
    spent(('GROQ_API_KEY', MODEL), left=1500)
    text(stream, request(chars=6000))
    text(stream, request())
    assert provider.asked == [('two', MODEL), ('one', MODEL)]


def test_when_no_road_has_room_they_are_asked_in_their_usual_order():
    provider = Provider()
    stream = ReserveStream(KEYS, post=provider, clock=lambda: 100.0)
    spent(*[(name, model) for name, _, model in stream.roads])
    assert text(stream, request(chars=6000)) == 'Ответ.'
    assert provider.asked == [('one', MODEL)]


def test_a_spent_road_is_still_asked_when_the_roads_with_room_fail():
    provider = Provider(refuse={(key, model): ReserveError('http_503') for key in ('one', 'two') for model in (SMALL, 'qwen/qwen3.8-27b')} | {('two', MODEL): ReserveError('http_503')})
    stream = ReserveStream(KEYS, post=provider, clock=lambda: 100.0)
    spent(('GROQ_API_KEY', MODEL))
    assert text(stream, request(chars=6000)) == 'Ответ.'      # the estimate is no verdict: the road answers when nobody else does
    assert provider.asked[0] == ('two', MODEL) and provider.asked[-1] == ('one', MODEL) and len(provider.asked) == 6


def refusal(wait='8', again=7.66, left='310'):
    refused = ReserveError('http_429')
    refused.headers = {'retry-after': wait, 'x-ratelimit-limit-tokens': '8000', 'x-ratelimit-remaining-tokens': left}
    refused.said = {'kind': 'TPM', 'limit': 8000, 'used': 7690, 'asked': 2900, 'again': again}
    return refused


def test_a_refusal_rests_the_road_as_long_as_its_provider_said():
    provider, now = Provider(refuse={('one', MODEL): refusal()}), [100.0]
    stream = ReserveStream(KEYS, post=provider, clock=lambda: now[0])
    assert text(stream, request()) == 'Ответ.' and provider.asked == [('one', MODEL), ('two', MODEL)]
    assert reserve_text._REST[('GROQ_API_KEY', MODEL)] == 108.0      # the longer of the waits it named, not the flat minute
    assert reserve_text.limits('GROQ_API_KEY', MODEL)['left'] == 310      # what the refusal said of the minute is kept too
    provider.refuse.clear()
    now[0] += 5.0
    text(stream, request())
    assert provider.asked[-1] == ('two', MODEL)      # still resting
    now[0] += 4.0
    text(stream, request())
    assert provider.asked[-1] == ('one', MODEL)      # nine seconds on, a small question: asked again


def test_a_refusal_that_names_no_wait_and_a_wait_of_hours_keep_within_the_stated_rests():
    silent, long = ReserveError('http_429'), refusal(wait='3600', again=3600.0)
    provider = Provider(refuse={('one', MODEL): silent, ('two', MODEL): long})
    stream = ReserveStream(KEYS, post=provider, clock=lambda: 100.0)
    assert text(stream, request()) == 'Ответ.'
    assert reserve_text._REST[('GROQ_API_KEY', MODEL)] == 100.0 + reserve_text.REST_S
    assert reserve_text._REST[('GROQ_API_KEY_2', MODEL)] == 100.0 + reserve_text.PRIMARY_QUOTA_REST_S      # a day's limit is asked again in ten minutes, not in an hour and not every question


class _Controller:
    settings = {}
    fast_exchanges = staticmethod(lambda: [])
    fast_in_play = staticmethod(lambda: None)
    fast_carry = staticmethod(lambda: '')      # the memory of earlier calls (``for_call`` hands it to the channel): none here
    ear_ended = None
    source_segment_id = None
    refuse_deadline = decision_due = staticmethod(lambda *a: None)      # the real controller's two moments: no question open, no bound


def test_the_budget_is_the_rule_of_every_reserve_of_a_call_and_no_key_asks_for_it(monkeypatch):
    from echo_sync import settings
    assert not [key for key in settings.DEFAULTS if key.startswith('reserve_')]
    assert not [key for key in settings.resolve({'fast_text': 'on', 'reserve_budget': 'on'}) if key.startswith('reserve_')]
    monkeypatch.setattr(reserve_text, 'read_keys', lambda path=None: {'GROQ_API_KEY': 'k'})
    profile = {'fast_text': 'on', 'local_ear': 'act'}
    channel = fast_text.for_call(profile, _Controller(), credentials=None)
    assert isinstance(channel.stream, reserve_text.Roads) and channel.stream.backup.roads
    assert reserve_text.for_stream(None, keys={'GROQ_API_KEY': 'k'}).backup.roads
