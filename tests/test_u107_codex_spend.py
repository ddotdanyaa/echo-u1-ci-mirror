"""U107, what a call spends of the Codex quota (the owner, 13.11: ten minutes of talk are about 6 % of the five-hour window; the reasoning tokens were not counted): per call, ``Roads`` counts the requests of
the first road and the tokens its answers tell (input, output, reasoning, cached) and of the reserve alike, the channel hands the numbers (``FastText.spend``) to the host, the host writes them to the
call trace at the close (``spend`` of ``call_close``): numbers only, no word of the dialogue. And the rule near the quota: the first road rests ``PRIMARY_QUOTA_REST_S`` after a 429 or a usage limit,
whether it comes as the status of the answer or as an event of the stream (U44, U89)."""
import json
import threading

import pytest

from echo_sync import codex_road as CR
from echo_sync import fast_text as FT
from echo_sync import reserve_text
from echo_sync.reserve_text import PRIMARY, ReserveStream, Roads
from test_h1_fast_text import SECRET, FakeHttp, FakeResponse, sse

KEYS = {'GROQ_API_KEY': 'one'}


@pytest.fixture(autouse=True)
def _fresh():
    for table in (reserve_text._REST, reserve_text._BUDGET):
        table.clear()
    reserve_text._PRIMARY['until'] = 0.0
    yield
    for table in (reserve_text._REST, reserve_text._BUDGET):
        table.clear()
    reserve_text._PRIMARY['until'] = 0.0


def codex_says(text, **usage):
    def road(request, cancelled):
        yield text
        if usage:
            yield {'usage': usage}
    return road


def reserve_post(url, headers, body, timeout):
    yield 'data: ' + json.dumps({'choices': [{'delta': {'content': 'Ответ запаса.'}}]})
    yield 'data: ' + json.dumps({'choices': [], 'usage': {'prompt_tokens': 700, 'completion_tokens': 30, 'total_tokens': 730}})
    yield 'data: [DONE]'


def walk(roads, request):
    return ''.join(piece for piece in roads(request, threading.Event()) if isinstance(piece, str))


REQUEST = FT.build_request('Что такое инерция?', instructions='Ты суфлёр.')
NOTHING = {'requests': 0, 'answered': 0, 'input_tokens': 0, 'output_tokens': 0, 'reasoning_tokens': 0, 'cached_tokens': 0}


def test_the_roads_count_the_requests_and_the_tokens_of_a_call_by_the_first_road_and_by_the_reserve():
    first = codex_says('Ответ Codex.', input_tokens=4000, output_tokens=300, total_tokens=4300, cached_tokens=1000, reasoning_tokens=220)
    roads = Roads(first, ReserveStream(KEYS, post=reserve_post))
    assert roads.spend() == {'codex': NOTHING, 'reserve': NOTHING}      # a call that has asked nothing has spent nothing
    assert walk(roads, REQUEST) == 'Ответ Codex.' and walk(roads, REQUEST) == 'Ответ Codex.'
    reserve_text._PRIMARY['until'] = 1e9      # the first road rests: the reserve answers
    assert walk(roads, REQUEST) == 'Ответ запаса.'
    assert roads.spend() == {'codex': {'requests': 2, 'answered': 2, 'input_tokens': 8000, 'output_tokens': 600, 'reasoning_tokens': 440, 'cached_tokens': 2000},
                             'reserve': {**NOTHING, 'requests': 1, 'answered': 1, 'input_tokens': 700, 'output_tokens': 30}}


def test_a_request_of_the_first_road_that_failed_is_counted_and_has_no_tokens_to_tell():
    def refuses(request, cancelled):
        raise CR.FastTextError('http_503')
        yield
    roads = Roads(refuses, ReserveStream(KEYS, post=reserve_post))
    assert walk(roads, REQUEST) == 'Ответ запаса.'
    spent = roads.spend()
    assert spent['codex'] == {**NOTHING, 'requests': 1} and spent['reserve']['requests'] == 1


def test_the_spend_of_the_channel_is_the_spend_of_its_roads_and_holds_numbers_only():
    first = codex_says('Ответ Codex.', input_tokens=10, output_tokens=2, total_tokens=12)
    fast = FT.FastText(Roads(first, ReserveStream({}, post=reserve_post)), instructions=lambda *a: 'POLICY', history=lambda: [])
    assert fast.release(qid='q', turn='t', epoch=1, question='Что такое инерция?') == 'started'
    for _ in range(400):
        if any(e['kind'] == 'done' for e in fast.poll()):
            break
        threading.Event().wait(0.005)
    spent = fast.spend()
    assert spent['codex']['requests'] == 1 and spent['codex']['input_tokens'] == 10
    assert all(isinstance(value, int) for part in spent.values() for value in part.values())


# --- the call trace ----------------------------------------------------------------------------------------------------------------------------

def test_the_host_writes_the_spend_of_the_call_to_the_trace_at_its_close(tmp_path):
    import helpers_always_answer as H
    from test_ux_call_trace_host import read_trace

    stand = H.Stand()

    async def body(host, stand):
        await stand.ask(host, 'Что такое инерция?', lag=0.2, pre=0.0)
        await host.advance(6.0)
        return host
    host = H.run_stand(tmp_path, stand, body)
    close = [record for record in read_trace(host.home) if record.get('ev') == 'call_close'][0]
    spend = close['spend']
    assert set(spend) == {'codex', 'reserve'} and spend['codex']['requests'] >= 1
    assert all(isinstance(value, int) for part in spend.values() for value in part.values()), spend


# --- near the quota: the first road rests, long ------------------------------------------------------------------------------------------------

@pytest.mark.parametrize('failure', ['http_429', 'usage_limit', 'http_401', 'http_403'])
def test_the_first_road_rests_for_the_quota_rest_after_a_429_a_usage_limit_or_a_sign_in_refusal(failure):
    now = [100.0]

    def refuses(request, cancelled):
        raise CR.FastTextError(failure)
        yield
    roads = Roads(refuses, ReserveStream(KEYS, post=reserve_post, clock=lambda: now[0]), clock=lambda: now[0])
    assert walk(roads, REQUEST) == 'Ответ запаса.'
    assert reserve_text._PRIMARY['until'] == 100.0 + reserve_text.PRIMARY_QUOTA_REST_S
    assert roads.order(REQUEST)[-1] == PRIMARY      # the next question is asked of the reserve first, the first road is the last resort


def test_any_other_failure_of_the_first_road_rests_it_the_short_rest_only():
    now = [100.0]

    def refuses(request, cancelled):
        raise CR.FastTextError('http_503')
        yield
    walk(Roads(refuses, ReserveStream(KEYS, post=reserve_post, clock=lambda: now[0]), clock=lambda: now[0]), REQUEST)
    assert reserve_text._PRIMARY['until'] == 100.0 + reserve_text.PRIMARY_FAIL_REST_S


@pytest.mark.parametrize('event, token', [({'type': 'response.failed', 'response': {'error': {'code': 'usage_limit_reached'}}}, 'usage_limit'),
                                          ({'type': 'error', 'error': {'type': 'usage_limit_reached', 'message': 'The usage limit has been reached'}}, 'usage_limit'),
                                          ({'type': 'response.failed', 'response': {'error': {'code': 'rate_limit_exceeded'}}}, 'usage_limit'),
                                          ({'type': 'response.failed', 'response': {'error': {'code': 'server_error'}}}, 'response_failed'),
                                          ({'type': 'response.failed'}, 'response_failed')])
def test_a_usage_limit_that_comes_as_an_event_of_the_stream_is_named_so_and_rests_the_first_road_long(event, token):
    stream = CR.codex_stream(lambda: (SECRET, 'a'), client_factory=lambda: FakeHttp(FakeResponse(200, sse(event))))
    with pytest.raises(CR.FastTextError) as error:
        list(stream({}, threading.Event()))
    assert str(error.value) == token
    failure = error.value

    def refuses(request, cancelled):
        raise failure
        yield
    with pytest.raises(CR.FastTextError):
        walk(Roads(refuses, None, clock=lambda: 100.0), REQUEST)
    assert reserve_text._PRIMARY['until'] == 100.0 + (reserve_text.PRIMARY_QUOTA_REST_S if token == 'usage_limit' else reserve_text.PRIMARY_FAIL_REST_S)
