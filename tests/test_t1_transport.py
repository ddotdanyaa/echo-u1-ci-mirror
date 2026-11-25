"""T1: ONE connection per call for the text channel (CR.CodexTransport), warmed when the call opens. No network: the HTTP client is a scripted fake (the ``client_factory`` seam).

What the measurement said (U1/05_WORK/ANALYSIS_20261105/08_LATENCY_BRAINSTORM.md, section 3 step 11): a new httpx.Client for every job costs 272 ms on every answer, httpx keeps an idle connection 5 s,
and questions come less often. So: the client lives as long as the call (``keepalive_expiry`` >= 120 s), a ping every 30 s keeps the connection warm, a dead socket gets exactly one retry, a cancelled
job closes its response and not the client, the client closes with the call, and nothing is shared between calls. Item 2: the client, the TLS and the sign-in are prepared when the call opens, in the
background, and a failure of that is silent. The default client and the real endpoint are measured apart (scripts/exp_transport.py, 03_TESTS/fast_text/transport_*.json); the tests pin the contract.
"""
import json
import logging
import queue
import re
import ssl
import sys
import threading
import time
from urllib.parse import urlsplit

import httpcore
import httpx
import pytest

from echo_sync import fast_text as FT
from echo_sync import codex_road as CR
from echo_sync.settings import resolve
from test_h1_fast_text import until

SECRET = 'tok-SECRET-0123456789'
DONE = [{'type': 'response.output_text.delta', 'delta': 'Да.'}, {'type': 'response.completed'}]


def sse(*events):
    return [('data: ' + json.dumps(e)) if not isinstance(e, str) else e for e in events] + ['']


class Resp:
    """One scripted response (a context manager like httpx's). ``error`` is raised on entering (``error_after`` None) or after that many lines were read; ``gate`` holds the end of the body back."""

    def __init__(self, lines=None, status=200, error=None, error_after=None, gate=None):
        self.lines, self.status_code, self.error, self.error_after, self.gate = sse(*DONE) if lines is None else lines, status, error, error_after, gate
        self.closed = self.exhausted = self.entered = self.read_called = False

    def __enter__(self):
        self.entered = True
        if self.error is not None and self.error_after is None:
            raise self.error
        return self

    def __exit__(self, *exc):
        self.closed = True
        return False

    def iter_lines(self):
        for number, line in enumerate(self.lines):
            if self.error is not None and self.error_after == number:
                raise self.error
            yield line
        if self.gate is not None:
            assert self.gate.wait(3)
        self.exhausted = True

    def read(self):
        self.read_called = True
        return b'{}'


class Client:
    """A scripted client: ``stream`` takes the next of ``script`` (an exception is raised, a ``Resp`` returned; an empty script is a plain answer), ``get`` is the ping."""

    def __init__(self, *script, ping_error=None):
        self.script, self.calls, self.pings, self.responses, self.closed, self.ping_error = list(script), [], [], [], False, ping_error
        self.lock = threading.Lock()

    def stream(self, method, url, **keywords):
        with self.lock:
            self.calls.append((method, url, keywords))
            item = self.script.pop(0) if self.script else Resp()
        if isinstance(item, BaseException):
            raise item
        self.responses.append(item)
        return item

    def get(self, url, **keywords):
        with self.lock:
            self.pings.append((url, keywords))
        if self.ping_error is not None:
            raise self.ping_error
        return type('Pong', (), {'status_code': 200})()

    def close(self):
        self.closed = True


class Factory:
    def __init__(self, *clients):
        self.clients, self.made = list(clients), []

    def __call__(self):
        client = self.clients.pop(0) if self.clients else Client()
        self.made.append(client)
        return client


def transport(*clients, credentials=None, **keywords):
    factory = Factory(*clients)
    return CR.codex_stream(credentials or (lambda: (SECRET, 'acct-1')), client_factory=factory, **keywords), factory


def run(stream, request=None, cancelled=None):
    return list(stream(request or {'model': 'm'}, cancelled or threading.Event()))


def dead(kind=httpx.RemoteProtocolError):
    return kind('Server disconnected without sending a response.')


# =====================================================================================================================================
# 1. one connection per call
# =====================================================================================================================================

def test_the_default_client_keeps_an_idle_connection_two_minutes_or_more(monkeypatch):
    made = []

    class Recorder:
        def __init__(self, **keywords):
            made.append(keywords)
    monkeypatch.setattr(httpx, 'Client', Recorder)
    CR._httpx_client()
    (keywords,) = made
    assert keywords['http2'] is False and keywords['limits'].keepalive_expiry >= 120.0, 'httpx keeps an idle connection 5 s by default; questions come less often'


def test_the_ping_comes_every_thirty_seconds():
    assert CR.PING_S == 30.0 and CR.KEEPALIVE_S >= 120.0


def test_every_job_of_a_call_goes_through_the_one_client():
    stream, factory = transport()
    for _ in range(3):
        assert run(stream) == ['Да.']
    assert len(factory.made) == 1 and len(factory.made[0].calls) == 3 and not factory.made[0].closed, 'a client per job cost 272 ms on every answer'


def test_the_client_is_made_when_it_is_first_needed_not_when_the_channel_is():
    stream, factory = transport()
    assert factory.made == []
    run(stream)
    assert len(factory.made) == 1


def test_the_client_is_closed_with_the_call_and_serves_nothing_after_it():
    stream, factory = transport()
    run(stream)
    client = factory.made[0]
    stream.close()
    assert until(lambda: client.closed)
    stream.close()                                                      # twice is harmless
    with pytest.raises(CR.FastTextError) as error:
        run(stream)
    assert str(error.value) == 'closed' and len(factory.made) == 1, 'a job after the call made a new client that nobody closes'


def test_the_channel_closing_closes_its_transport_and_a_plain_stream_needs_nothing():
    stream, factory = transport()
    fast = FT.FastText(stream, instructions=lambda: 'P', history=lambda: [])
    fast.prepare('Что такое инерция')
    assert until(lambda: factory.made and factory.made[0].calls)
    fast.close()
    assert until(lambda: factory.made[0].closed)
    plain = FT.FastText(lambda request, cancelled: iter(()), instructions=lambda: 'P', history=lambda: [])
    plain.prepare('Что такое инерция')
    plain.close()                                                       # a fake stream has no close: nothing to do, nothing raised
    plain.warm()


def test_failed_jobs_never_put_the_channel_out_and_the_call_closes_the_transport():
    stream, factory = transport(Client(*[Resp(status=500) for _ in range(3)]))
    fast = FT.FastText(stream, instructions=lambda: 'P', history=lambda: [], clock=lambda: 0.0)
    for _ in range(3):
        fast.prepare('Что такое инерция')
        assert until(lambda: fast.job.done)
        fast.poll()
    assert not fast.off and not factory.made[0].closed      # the roads own the verdict on a road (its rest): no breaker, the client stays for the next job
    fast.close()
    assert until(lambda: factory.made[0].closed)


def test_a_cancelled_stream_closes_its_response_not_the_client():
    gate = threading.Event()
    first = Resp(sse({'type': 'response.output_text.delta', 'delta': 'a'}, {'type': 'response.output_text.delta', 'delta': 'b'}), gate=gate)
    stream, factory = transport(Client(first))
    cancelled, got = threading.Event(), []
    for delta in stream({}, cancelled):
        got.append(delta)
        cancelled.set()
    client = factory.made[0]
    assert got == ['a'] and first.closed and not first.exhausted and not client.closed
    assert run(stream) == ['Да.'] and len(factory.made) == 1 and len(client.calls) == 2, 'the next job goes through the same client'


def test_a_cancelled_job_re_warms_the_pool_in_the_background():
    """A response left unread cannot go back to the pool (httpcore closes that connection): one light request makes the next job find a connection again."""
    first = Resp(sse({'type': 'response.output_text.delta', 'delta': 'a'}, {'type': 'response.output_text.delta', 'delta': 'b'}))
    stream, factory = transport(Client(first))
    cancelled = threading.Event()
    for _ in stream({}, cancelled):
        cancelled.set()
    assert until(lambda: len(factory.made[0].pings) == 1)
    time.sleep(0.05)
    assert len(factory.made[0].pings) == 1


def test_after_completed_the_job_is_over_and_the_rest_of_the_body_is_read_off_for_the_pool():
    """The measured fact (exp_transport.py): a response left unread at ``response.completed`` closes its connection, so every job reconnected even on one client. The job
    does not wait for that (the end of the body came 50-130 ms after completed): a thread reads it off."""
    gate = threading.Event()
    body = Resp(sse({'type': 'response.output_text.delta', 'delta': 'Да.'}, {'type': 'response.completed'}, {'type': 'response.output_text.delta', 'delta': 'NEVER'}), gate=gate)
    stream, _ = transport(Client(body))
    assert run(stream) == ['Да.'] and not body.closed and not body.exhausted, 'the job is over at completed, the response is not closed under the reader'
    gate.set()
    assert until(lambda: body.exhausted and body.closed)


def test_the_rest_of_the_body_failing_after_completed_is_nothing_to_the_job():
    body = Resp(error=dead(httpx.ReadError), error_after=2)
    stream, _ = transport(Client(body))
    assert run(stream) == ['Да.']
    assert until(lambda: body.closed)


@pytest.mark.parametrize('kind', [httpx.RemoteProtocolError, httpx.ReadError, httpx.ConnectError, httpx.WriteError, ConnectionResetError])
def test_a_dead_socket_gets_exactly_one_retry(kind):
    stream, factory = transport(Client(Resp(error=dead(kind))))
    assert run(stream) == ['Да.']
    assert sum(len(client.calls) for client in factory.made) == 2


def test_a_dead_socket_is_found_on_the_first_line_too():
    stream, factory = transport(Client(Resp(error=dead(httpx.ReadError), error_after=0)))
    assert run(stream) == ['Да.'] and sum(len(client.calls) for client in factory.made) == 2


def test_the_retry_is_the_only_one():
    stream, factory = transport(Client(Resp(error=dead())), Client(Resp(error=dead())))
    with pytest.raises(httpx.RemoteProtocolError):
        run(stream)
    assert sum(len(client.calls) for client in factory.made) == 2, 'a third try is a job that has been waiting for seconds'


def test_a_dead_socket_after_a_text_is_not_retried_the_text_would_be_said_twice():
    stream, factory = transport(Client(Resp(sse({'type': 'response.output_text.delta', 'delta': 'Да.'}), error=dead(httpx.ReadError), error_after=1)))
    got = []
    with pytest.raises(httpx.ReadError):
        for delta in stream({}, threading.Event()):
            got.append(delta)
    assert got == ['Да.'] and sum(len(client.calls) for client in factory.made) == 1


@pytest.mark.parametrize('failure', [httpx.ReadTimeout('slow'), httpx.ConnectTimeout('slow'), CR.FastTextError('http_500'), CR.FastTextError('response_failed')])
def test_a_timeout_or_a_refusal_is_not_a_dead_socket(failure):
    if isinstance(failure, CR.FastTextError):
        item = Resp(status=int(str(failure)[5:])) if str(failure).startswith('http_') else Resp(sse({'type': 'response.failed'}))
    else:
        item = Resp(error=failure)
    stream, factory = transport(Client(item))
    with pytest.raises(Exception):
        run(stream)
    assert sum(len(client.calls) for client in factory.made) == 1


def test_a_cancelled_job_is_not_retried_after_a_socket_died_under_it():
    cancelled = threading.Event()

    class Cancelling(Resp):
        def __enter__(self):
            cancelled.set()
            return super().__enter__()
    stream, factory = transport(Client(Cancelling(error=dead())))
    with pytest.raises(httpx.RemoteProtocolError):
        run(stream, cancelled=cancelled)
    assert sum(len(client.calls) for client in factory.made) == 1


def test_through_the_channel_a_dead_socket_is_no_failure_of_its_own(caplog):
    caplog.set_level(logging.INFO, logger='echo-sync')
    stream, _ = transport(Client(Resp(error=dead())))
    fast = FT.FastText(stream, instructions=lambda: 'P', history=lambda: [])
    fast.release(qid='u1', turn='fast-1', epoch=1, question='Что такое инерция')
    events, end = [], time.monotonic() + 3
    while time.monotonic() < end and not any(e['kind'] == 'done' for e in events):
        events += fast.poll()
        time.sleep(0.005)
    assert [e['kind'] for e in events] == ['text', 'done'] and ''.join(e['text'] for e in events) == 'Да.'
    assert not fast.off
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING] and SECRET not in caplog.text


def test_a_refusal_drops_the_cached_sign_in_and_the_body_is_never_read():
    asked = []
    refused = Resp(status=401)
    stream, _ = transport(Client(refused, Resp(status=403)), credentials=lambda: asked.append(1) or (SECRET, 'a'))
    for _ in range(2):
        with pytest.raises(CR.FastTextError):
            run(stream)
    run(stream)
    assert len(asked) == 3 and not refused.read_called


def test_the_ping_is_a_plain_request_to_the_same_host_that_uses_no_model_and_no_token():
    stream, factory = transport()
    assert stream.ping() is True
    (url, keywords), = factory.made[0].pings
    assert urlsplit(url).netloc == urlsplit(CR.FAST_URL).netloc and url == CR.PING_URL and url != CR.FAST_URL
    assert not factory.made[0].calls, 'no stream, no POST: no model request, no quota'
    assert not {k.lower() for k in keywords.get('headers', {})} & {'authorization', 'chatgpt-account-id'} and 'json' not in keywords and 'content' not in keywords


def test_the_ping_is_made_on_the_one_client_and_a_ping_answered_with_any_status_is_an_answer():
    stream, factory = transport()
    run(stream)
    stream.ping()
    assert len(factory.made) == 1 and len(factory.made[0].pings) == 1 and len(factory.made[0].calls) == 1


def test_pings_go_on_while_the_call_is_open_and_stop_with_it():
    stream, factory = transport(ping_s=0.01)
    stream.warm()
    assert until(lambda: factory.made and len(factory.made[0].pings) >= 4)
    stream.close()
    assert until(lambda: not [t for t in threading.enumerate() if t.name == 'echo-fast-text-keepalive' and t.is_alive()])
    count = len(factory.made[0].pings)
    time.sleep(0.05)
    assert len(factory.made[0].pings) == count and len(factory.made) == 1


def test_no_ping_while_a_job_is_in_flight():
    gate = threading.Event()
    stream, factory = transport(Client(Resp(sse({'type': 'response.output_text.delta', 'delta': 'a'}, {'type': 'response.completed'}), gate=gate)))
    generator = stream({}, threading.Event())
    assert next(generator) == 'a'
    assert stream.ping() is False and not factory.made[0].pings, 'the job keeps its own connection alive'
    list(generator)
    assert stream.ping() is True
    gate.set()


@pytest.mark.parametrize('failure', [dead(httpx.ReadError), httpx.ReadTimeout('slow'), httpx.ConnectError('down')])
def test_a_failed_ping_is_silent_drops_the_client_and_tries_once_on_a_new_one_and_the_next_job_goes(failure, caplog):
    """A connection that does not answer is not to be trusted by the next job: it would sit 4 s on it. Whatever the ping died of, the client goes and one fresh try re-warms."""
    caplog.set_level(logging.DEBUG, logger='echo-sync')
    bad, good = Client(ping_error=failure), Client()
    stream, factory = transport(bad, good)
    assert stream.ping() is True
    assert len(bad.pings) == 1 and len(good.pings) == 1 and factory.made == [bad, good]
    assert until(lambda: bad.closed), 'the client with the dead connection is let go'
    assert run(stream) == ['Да.'] and len(good.calls) == 1 and not bad.calls
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_a_ping_that_fails_twice_is_false_and_never_raises_and_the_job_connects_itself():
    stream, factory = transport(Client(ping_error=dead(httpx.ReadError)), Client(ping_error=httpx.ConnectError('down')))
    assert stream.ping() is False
    assert run(stream) == ['Да.'], 'the next job connects itself, as today'
    assert len(factory.made) == 3


def test_no_state_is_shared_between_calls():
    asked = []
    first, first_factory = transport(credentials=lambda: asked.append('a') or (SECRET, 'one'))
    second, second_factory = transport(credentials=lambda: asked.append('b') or (SECRET, 'two'))
    run(first)
    run(second)
    assert asked == ['a', 'b'] and first_factory.made[0] is not second_factory.made[0]
    headers = {s: f.made[0].calls[0][2]['headers']['ChatGPT-Account-Id'] for s, f in ((first, first_factory), (second, second_factory))}
    assert list(headers.values()) == ['one', 'two']
    first.close()
    assert until(lambda: first_factory.made[0].closed) and not second_factory.made[0].closed
    assert run(second) == ['Да.'], 'the end of one call does not touch the connection of another'


# =====================================================================================================================================
# 2. warm up when the call opens
# =====================================================================================================================================

def test_the_warm_up_prepares_the_client_the_sign_in_and_the_connection_without_waiting_for_any_of_them():
    release, asked = threading.Event(), []

    def credentials():
        asked.append(1)
        assert release.wait(3)
        return SECRET, 'acct-1'
    stream, factory = transport(credentials=credentials)
    started = time.monotonic()
    stream.warm()
    assert time.monotonic() - started < 0.3, 'the call does not wait for its own warm-up'
    assert until(lambda: asked), 'the sign-in is being read in the background'
    release.set()
    assert until(lambda: factory.made and factory.made[0].pings), 'client made, sign-in read, one light request sent'
    assert run(stream) == ['Да.']
    assert len(asked) == 1 and len(factory.made) == 1, 'the first job found the sign-in and the client ready'
    assert factory.made[0].calls[0][2]['headers']['Authorization'] == 'Bearer ' + SECRET
    stream.close()


def test_the_warm_up_is_one_thread_that_is_also_the_keepalive():
    stream, _ = transport(ping_s=60)
    stream.warm()
    stream.warm()
    assert until(lambda: [t for t in threading.enumerate() if t.name == 'echo-fast-text-keepalive'])
    assert len([t for t in threading.enumerate() if t.name == 'echo-fast-text-keepalive' and t.is_alive()]) == 1
    stream.close()


def test_a_failed_warm_up_is_silent_and_the_first_job_goes_as_today(caplog):
    caplog.set_level(logging.DEBUG, logger='echo-sync')
    asked = []

    def credentials():
        asked.append(1)
        if len(asked) == 1:
            raise RuntimeError('no sign-in just now ' + SECRET)
        return SECRET, 'acct-1'
    stream, factory = transport(credentials=credentials)
    assert stream.prepare() is False
    fast = FT.FastText(stream, instructions=lambda: 'P', history=lambda: [])
    assert not fast.off
    assert run(stream) == ['Да.'] and len(asked) == 2, 'the first job reads the sign-in itself'
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING] and SECRET not in caplog.text


def test_a_warm_up_that_cannot_reach_the_host_is_silent_too(caplog):
    caplog.set_level(logging.DEBUG, logger='echo-sync')
    stream, factory = transport(Client(ping_error=httpx.ConnectError('down')), Client(ping_error=httpx.ConnectError('down')))
    assert stream.prepare() is False
    assert run(stream) == ['Да.']
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_a_client_that_cannot_be_made_is_a_silent_warm_up_and_the_job_fails_as_it_would_have():
    def broken():
        raise OSError('no certificates')
    stream = CR.codex_stream(lambda: (SECRET, 'a'), client_factory=broken)
    assert stream.prepare() is False
    stream.warm()
    with pytest.raises(OSError):
        run(stream)
    stream.close()


def test_the_warm_up_logs_numbers_only(caplog):
    caplog.set_level(logging.INFO, logger='echo-sync')
    stream, _ = transport()
    assert stream.prepare() is True
    lines = [r.getMessage() for r in caplog.records if 'fast_text warm' in r.getMessage()]
    assert len(lines) == 1 and 'ok=1' in lines[0] and 'ms=' in lines[0] and SECRET not in caplog.text and 'acct-1' not in caplog.text


def test_the_channel_warms_its_transport_once_and_closes_it_once():
    class Transport:
        def __init__(self):
            self.warmed, self.closed = 0, 0

        def __call__(self, request, cancelled):
            return iter(())

        def warm(self):
            self.warmed += 1

        def close(self):
            self.closed += 1
    transport_ = Transport()
    fast = FT.FastText(transport_, instructions=lambda: 'P', history=lambda: [])
    fast.warm()
    assert transport_.warmed == 1
    fast.close()
    fast.shutdown()
    assert transport_.closed == 1
    fast.warm()
    assert transport_.warmed == 1, 'a closed channel is not warmed'
    off = FT.FastText(transport_, instructions=lambda: 'P', history=lambda: [])
    off.off = True
    off.warm()
    assert transport_.warmed == 1, 'nor one that is out for the call'


def test_a_transport_that_fails_to_warm_leaves_the_channel_as_it_was():
    class Transport:
        def __call__(self, request, cancelled):
            return iter(())

        def warm(self):
            raise RuntimeError('bug')
    fast = FT.FastText(Transport(), instructions=lambda: 'P', history=lambda: [])
    fast.warm()
    assert not fast.off


def test_the_host_warms_the_channel_when_the_call_opens_and_closes_it_with_the_call(tmp_path, monkeypatch):
    import asyncio
    import helpers_s6_fault as F

    class Transport:
        def __init__(self):
            self.warmed = self.closed = 0

        def __call__(self, request, cancelled):
            return iter(())

        def warm(self):
            self.warmed += 1

        def close(self):
            self.closed += 1
    transport_ = Transport()
    monkeypatch.setattr(CR, 'codex_stream', lambda credentials: transport_)

    async def main():
        F.patch_clock(monkeypatch)
        async with F.HostRig(tmp_path, monkeypatch) as host:
            (host.home / 'materials').mkdir(parents=True, exist_ok=True)
            (host.home / 'materials' / 'echo_settings.json').write_text(json.dumps({'fast_text': 'on'}), encoding='utf-8')
            await host.handshake()
            await asyncio.sleep(0)
            assert transport_.warmed == 1 and transport_.closed == 0
        return transport_.warmed, transport_.closed
    assert F.run(main) == (1, 1)


def test_the_host_without_the_channel_warms_nothing(tmp_path, monkeypatch):
    import helpers_s6_fault as F
    made = []
    monkeypatch.setattr(CR, 'codex_stream', lambda credentials: made.append(1))

    async def main():
        F.patch_clock(monkeypatch)
        async with F.HostRig(tmp_path, monkeypatch) as host:
            await host.handshake()
    F.run(main)
    assert made == []


# =====================================================================================================================================
# 3. the skeptic: the real httpx and httpcore over sockets in memory (no network). Everything above is a scripted client; this is what the pool, the proxy road and a closing client really do
# =====================================================================================================================================

HEAD = b'HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nTransfer-Encoding: chunked\r\n\r\n'
END = b'0\r\n\r\n'
PONG = b'HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok'
TUNNEL = b'HTTP/1.1 200 Connection established\r\n\r\n'
PROXY = 'http://127.0.0.1:10809'
COMPLETED = {'type': 'response.completed'}
TLS = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)


def delta(text):
    return {'type': 'response.output_text.delta', 'delta': text}


def chunk(*events):
    body = '\n'.join(sse(*events)).encode() + b'\n'
    return b'%x\r\n%s\r\n' % (len(body), body)


class Sock(httpcore.NetworkStream):
    """One socket in memory: ``read`` gets what the peer put in ``inbox`` and, as a real one, gives up at the timeout httpcore passes it."""

    def __init__(self, net):
        self.net, self.inbox, self.closed, self.got, self.timeouts = net, queue.Queue(), False, b'', []

    def read(self, max_bytes, timeout=None):
        self.timeouts.append(timeout)
        try:
            item = self.inbox.get(timeout=timeout)
        except queue.Empty:
            raise httpcore.ReadTimeout('silent') from None
        if isinstance(item, Exception):
            raise item
        return item

    def write(self, buffer, timeout=None):
        self.got += buffer
        head, mark, body = self.got.partition(b'\r\n\r\n')
        length = re.search(rb'content-length: (\d+)', head, re.I)
        if mark and len(body) >= (int(length[1]) if length else 0):
            self.got = b''
            self.net.answer(self, head)

    def close(self):
        self.closed = True
        self.inbox.put(httpcore.ReadError('closed under the read'))

    def start_tls(self, *arguments, **keywords):
        return self

    def get_extra_info(self, info):
        return None


class Net(httpcore.NetworkBackend):
    """The peer. ``posts`` / ``pongs`` / ``tunnels``: what it says to each POST / GET / CONNECT, a list of pieces (bytes, or an exception the read raises; an empty list is silence); past the script a plain answer."""

    def __init__(self, *posts, pongs=(), tunnels=()):
        self.posts, self.pongs, self.tunnels, self.socks, self.heads, self.clients, self.down = list(posts), list(pongs), list(tunnels), [], [], [], None

    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        if self.down is not None:
            raise self.down
        self.socks.append(Sock(self))
        return self.socks[-1]

    def answer(self, sock, head):
        self.heads.append(head)
        if head.startswith(b'CONNECT'):
            pieces = self.tunnels.pop(0) if self.tunnels else [TUNNEL]
        elif head.startswith(b'GET'):
            pieces = self.pongs.pop(0) if self.pongs else [PONG]
        else:
            pieces = self.posts.pop(0) if self.posts else [HEAD, chunk(*DONE), END]
        for piece in pieces:
            sock.inbox.put(piece)

    def client(self, proxy=None):
        """A real httpx client whose real pool dials this net, the way ``_httpx_client`` sets it up."""
        road = httpx.HTTPTransport(verify=False)
        limits = {'keepalive_expiry': CR.KEEPALIVE_S, 'network_backend': self, 'ssl_context': TLS}          # without one httpcore loads the certificates for every socket, 230 ms each
        road._pool = httpcore.HTTPProxy(proxy_url=proxy, **limits) if proxy else httpcore.ConnectionPool(**limits)
        self.clients.append(httpx.Client(http2=False, transport=road))
        return self.clients[-1]


def on(net, **keywords):
    return CR.codex_stream(lambda: (SECRET, 'acct-1'), client_factory=net.client, **keywords)


def fast_threads(*kinds):
    return [t for t in threading.enumerate() if t.name.startswith('echo-fast-text') and t.is_alive() and (not kinds or t.name.rsplit('-', 1)[-1] in kinds)]


def read_off():
    assert until(lambda: not fast_threads('drain')), 'the rest of a body was never read off'


# -- reproduced: each of these failed before its fix -----------------------------------------------------------------------------------

def test_a_ping_that_dies_while_a_job_speaks_does_not_close_the_client_under_the_job():
    """A ping that gets no answer costs the client, but a job may have begun while it waited, on a socket of its own. Closing the client closes every socket of it, and the answer stopped in the middle (a failed ping is 5 s long, a re-warm ping right after a cancel is the usual moment)."""
    net = Net([HEAD, chunk(delta('Первая фраза. '))], pongs=[[]])
    stream = on(net)
    pinger = threading.Thread(target=stream.ping, daemon=True)
    pinger.start()
    assert until(lambda: net.heads), 'the ping is on the wire, its socket is silent'
    job = stream({}, threading.Event())
    assert next(job) == 'Первая фраза. ' and len(net.socks) == 2, 'the job went on a socket of its own'
    net.socks[0].inbox.put(httpcore.ReadTimeout('no answer'))
    pinger.join(3)
    time.sleep(0.05)
    net.socks[1].inbox.put(chunk(delta('Вторая.'), COMPLETED))
    net.socks[1].inbox.put(END)
    assert list(job) == ['Вторая.'], 'the rest of the answer'
    read_off()
    assert not net.clients[0].is_closed and stream.ping() is True, 'the next ping looks at the client again'
    stream.close()


def test_a_proxy_that_refuses_the_tunnel_gets_the_one_retry_like_a_dead_socket():
    """The road is the VPN's local proxy, and one that is rebuilding its way out answers the CONNECT with an error: httpx calls that ProxyError, which is no NetworkError. The new client also reads the proxy anew (it can have changed)."""
    net = Net(tunnels=[[b'HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\n\r\n']])
    stream = CR.codex_stream(lambda: (SECRET, 'a'), client_factory=lambda: net.client(PROXY))
    assert run(stream) == ['Да.']
    assert len(net.clients) == 2 and sum(head.startswith(b'POST') for head in net.heads) == 1
    stream.close()


def test_after_the_close_the_sign_in_is_not_read_either():
    """The warm-up's thread can be scheduled after the close (a call that ended at once), and a job's too: the sign-in goes through the loop's executor and may refresh a token for nobody."""
    asked = []
    stream, factory = transport(credentials=lambda: asked.append(1) or (SECRET, 'a'))
    stream.close()
    assert stream.prepare() is False
    with pytest.raises(CR.FastTextError) as error:
        run(stream)
    assert str(error.value) == 'closed' and asked == [] and factory.made == []


def test_a_job_cancelled_during_the_sign_in_sends_no_request():
    """A model request for nobody, and it took the one warm connection with it: the first line would have seen the cancel and closed it."""
    cancelled = threading.Event()
    stream, factory = transport(credentials=lambda: cancelled.set() or (SECRET, 'a'))
    assert run(stream, cancelled=cancelled) == []
    time.sleep(0.05)
    assert not sum(len(client.calls) for client in factory.made), 'no POST'
    assert not sum(len(client.pings) for client in factory.made), 'nor a re-warm: no connection was lost, and a ping would take the warm one from the job that replaces this one'
    assert stream._active == 0
    stream.close()


def test_a_body_that_trickles_on_after_completed_does_not_hold_its_reader_for_ever(monkeypatch):
    """httpx's timeout is per read: a body that says a little every few seconds outlives it, and the thread would sit there as long as the peer likes."""
    monkeypatch.setattr(CR, 'DRAIN_S', 0.1, raising=False)
    net, stop = Net([HEAD, chunk(*DONE)]), threading.Event()
    stream = on(net)
    assert run(stream) == ['Да.']

    def trickle():
        while not stop.wait(0.01):
            net.socks[0].inbox.put(chunk(': still here'))
    threading.Thread(target=trickle, daemon=True).start()
    try:
        assert until(lambda: not fast_threads('drain'), 1.0) and net.socks[0].closed, 'the reader lets go of a body that does not end'
    finally:
        stop.set()
        net.socks[0].inbox.put(END)
    stream.close()


@pytest.mark.parametrize('opening', [True, False])
def test_an_exception_in_the_ping_thread_does_not_end_the_pings(monkeypatch, opening):
    """The thread that lets a client go may fail to start, at the warm-up or on any tick after it. Nobody sees the keep-alive die: the connection just goes cold for the rest of the call."""
    first = Client(ping_error=dead(httpx.ReadError) if opening else None)
    stream, factory = transport(first, ping_s=0.01)
    renew, broken = stream._renew, []

    def once(*arguments, **keywords):
        if not broken:
            broken.append(1)
            raise RuntimeError("can't start new thread")
        return renew(*arguments, **keywords)
    monkeypatch.setattr(stream, '_renew', once)
    stream.warm()
    if not opening:
        assert until(lambda: len(first.pings) >= 2), 'the keep-alive is on its ticks'
        first.ping_error = dead(httpx.ReadError)
    assert until(lambda: len(factory.made) == 2 and factory.made[1].pings), 'the next ping came all the same'
    stream.close()


def test_a_response_that_fails_to_close_after_completed_is_nothing_to_anybody(monkeypatch):
    class Broken(Resp):
        def __exit__(self, *exc):
            self.closed = True
            raise httpx.ReadError('the socket was gone')
    caught, body = [], Broken()
    monkeypatch.setattr(threading, 'excepthook', lambda arguments: caught.append(arguments.exc_type))
    stream, _ = transport(Client(body))
    assert run(stream) == ['Да.']
    assert until(lambda: body.closed)
    read_off()
    assert caught == [], 'a traceback on the server log for a socket nobody wants'
    stream.close()


def test_a_call_that_dies_before_its_loop_leaves_no_keepalive_behind(tmp_path, monkeypatch):
    """The ``finally`` that closes the channel belongs to the ``try`` of the message loop. Warmed before it, a call that dies in between (an ear that cannot be set) leaves a thread pinging for the life of the server."""
    import helpers_s6_fault as F
    from echo_sync import controlled_host

    class Transport:
        def __init__(self):
            self.warmed = self.closed = 0

        def __call__(self, request, cancelled):
            return iter(())

        def warm(self):
            self.warmed += 1

        def close(self):
            self.closed += 1

    def dies(coro, *args, **kwargs):                                    # the last step before the message loop: the ear's task. The call dies there, after the channel is built (``hear_better`` is off the loop now, so the ear itself kills nothing)
        if getattr(coro, '__name__', '') == 'hear_better':
            coro.close()
            raise RuntimeError('no ear')
        return create_task(coro, *args, **kwargs)
    transport_, outcome, create_task = Transport(), [], controlled_host.asyncio.create_task
    monkeypatch.setattr(CR, 'codex_stream', lambda credentials: transport_)

    async def main():
        F.patch_clock(monkeypatch)
        monkeypatch.setattr(controlled_host.asyncio, 'create_task', dies)
        async with F.HostRig(tmp_path, monkeypatch) as host:
            (host.home / 'materials').mkdir(parents=True, exist_ok=True)
            (host.home / 'materials' / 'echo_settings.json').write_text(json.dumps({'fast_text': 'on'}), encoding='utf-8')
            assert await host.until(lambda: host.finished, 30)
            outcome.append(host.outcome)
    F.run(main)
    assert isinstance(outcome[0], RuntimeError), 'the call died where this test wants it to'
    assert transport_.warmed == transport_.closed, 'nothing warmed stays open after the call'


# -- not reproduced: the suspicion stands refuted here, on the real stack ---------------------------------------------------------------

def test_on_the_real_stack_the_jobs_and_the_pings_of_a_call_ride_one_socket():
    net = Net()
    stream = on(net)
    for _ in range(3):
        assert run(stream) == ['Да.']
        read_off()
        assert stream.ping() is True
    assert len(net.socks) == 1 and len(net.clients) == 1 and not net.socks[0].closed
    assert not [head for head in net.heads if head.startswith(b'GET') and b'authorization' in head.lower()], 'no token on the wire of a ping'
    stream.close()
    assert until(lambda: net.socks[0].closed and net.clients[0].is_closed)


def test_on_the_real_stack_a_stalled_body_ends_at_the_timeout_of_its_request_and_no_five_seconds_of_httpx_survive(monkeypatch):
    monkeypatch.setattr(CR, 'FIRST_TEXT_S', 0.05)
    net = Net([HEAD, chunk(*DONE)])
    stream = on(net)
    assert run(stream) == ['Да.']
    assert until(lambda: not fast_threads('drain') and net.socks[0].closed), 'a body that stops is given up by the read itself'
    assert set(net.socks[0].timeouts) == {0.05}, 'the job and its reader both read under the timeout of the request'
    stream.close()


def test_the_proxy_road_keeps_a_connection_as_long_as_the_direct_one(monkeypatch):
    """httpx builds the proxy's transport apart (this laptop's road): the limits have to reach it, and nothing there may cap the pool."""
    monkeypatch.setenv('HTTPS_PROXY', PROXY)
    monkeypatch.delenv('NO_PROXY', raising=False)
    client = CR._httpx_client()
    pools = [road._pool for road in client._mounts.values() if road is not None] + [client._transport._pool]
    client.close()
    assert len(pools) >= 2 and {pool._keepalive_expiry for pool in pools} == {CR.KEEPALIVE_S}
    assert {pool._max_connections for pool in pools} == {sys.maxsize}, 'nothing to exhaust'


def test_on_the_real_stack_a_cancel_between_deltas_closes_that_socket_and_nothing_else():
    net = Net([HEAD, chunk(delta('Раз. '))])
    stream = on(net)
    fast = FT.FastText(stream, instructions=lambda: 'P', history=lambda: [])
    fast.prepare('Что такое инерция')
    assert until(lambda: fast.job.buffer == 'Раз. ')
    job, sock = fast.job, net.socks[0]
    fast.drop()
    sock.inbox.put(chunk(delta('Два.')))
    assert until(lambda: sock.closed and stream._active == 0) and job.buffer == 'Раз. '
    assert until(lambda: len(net.socks) == 2 and not fast_threads('rewarm')), 'one light request put a connection back in the pool'
    assert run(stream) == ['Да.'] and len(net.socks) == 2 and len(net.clients) == 1 and not net.clients[0].is_closed
    fast.close()


def test_on_the_real_stack_cancels_do_not_use_the_pool_up():
    rounds = 40
    net = Net(*[[HEAD, chunk(delta('a'), delta('b'))] for _ in range(rounds)])
    stream = on(net)
    for _ in range(rounds):
        cancelled = threading.Event()
        for _ in stream({}, cancelled):
            cancelled.set()
    assert run(stream) == ['Да.'] and len(net.clients) == 1
    assert until(lambda: sum(not sock.closed for sock in net.socks) <= 3), 'every cancel closed its socket'
    stream.close()


def test_on_the_real_stack_a_socket_gone_before_the_first_byte_retries_once_and_says_the_answer_once():
    net = Net([b''], [HEAD, chunk(delta('Раз. '), delta('Два.'), COMPLETED), END])
    stream = on(net)
    assert run(stream) == ['Раз. ', 'Два.'] and len(net.clients) == 2
    stream.close()


def test_on_the_real_stack_a_socket_gone_after_a_text_is_never_retried():
    net = Net([HEAD, chunk(delta('Раз. ')), b''])
    stream = on(net)
    said = []
    with pytest.raises(httpx.RemoteProtocolError):
        for piece in stream({}, threading.Event()):
            said.append(piece)
    assert said == ['Раз. '] and sum(head.startswith(b'POST') for head in net.heads) == 1
    stream.close()


def test_a_long_call_outlives_its_token_on_the_one_client():
    """The token is in the headers of each job, never in the client: the cache runs out, the next job signs in anew on the same connection. A token that died inside the cache (Hermes refreshes 120 s before the end, the cache lives 300 s) costs
    that one job a 401, nothing else: the cached one is dropped, the failure is no broken channel (and the controller asks again, H5 item 7)."""
    tokens = iter(['first', 'second', 'third'])
    stream, factory = transport(Client(Resp(), Resp(status=401), Resp()), credentials=lambda: (next(tokens), 'a'))
    assert run(stream) == ['Да.']
    stream._signed = (time.monotonic() - CR.CREDENTIALS_TTL_S - 1, *stream._signed[1:])
    with pytest.raises(CR.FastTextError):
        run(stream)
    assert run(stream) == ['Да.']
    assert [call[2]['headers']['Authorization'] for call in factory.made[0].calls] == ['Bearer first', 'Bearer second', 'Bearer third'] and len(factory.made) == 1


def test_a_call_that_opens_with_no_network_is_silent_and_the_network_coming_back_is_enough(caplog):
    caplog.set_level(logging.DEBUG, logger='echo-sync')
    net = Net()
    net.down = httpcore.ConnectError('no route')
    stream = on(net, ping_s=60)
    stream.warm()
    assert until(lambda: 'fast_text warm ok=0' in caplog.text)
    with pytest.raises(httpx.ConnectError):
        run(stream)
    net.down = None
    assert run(stream) == ['Да.']
    stream.close()
    assert until(lambda: all(client.is_closed for client in net.clients)), 'no client is left open'
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING] and SECRET not in caplog.text


def test_two_calls_one_after_the_other_leave_nothing_of_the_first():
    for _ in range(2):
        others = set(fast_threads())
        net = Net()
        stream = on(net, ping_s=0.01)
        stream.warm()
        assert until(lambda: sum(head.startswith(b'GET') for head in net.heads) >= 2)
        assert run(stream) == ['Да.']
        stream.close()
        assert until(lambda: not set(fast_threads()) - others), 'no thread of a call outlives it'
        pings = len(net.heads)
        time.sleep(0.03)
        assert len(net.heads) == pings and all(client.is_closed for client in net.clients) and all(sock.closed for sock in net.socks)


def test_a_silent_road_found_by_a_job_is_left_by_the_re_warm_that_follows_it():
    """A timeout is no dead socket and gets no retry, and a client reads the proxy only when it is made. The job's bound cancels it, the re-warm ping meets the same silence and that costs the client: the next job is on a new road (a proxy changed mid call)."""
    cancelled = threading.Event()

    class Silent(Resp):
        def __enter__(self):
            cancelled.set()
            return super().__enter__()
    stale, fresh = Client(Silent(error=httpx.ReadTimeout('silent')), ping_error=httpx.ConnectTimeout('silent')), Client()
    stream, _ = transport(stale, fresh)
    with pytest.raises(httpx.ReadTimeout):
        run(stream, cancelled=cancelled)
    assert until(lambda: fresh.pings) and run(stream) == ['Да.'] and len(fresh.calls) == 1
    stream.close()


def test_a_client_made_during_the_close_is_closed_and_serves_nobody():
    made, release = threading.Event(), threading.Event()
    late = Client()

    def slow():
        made.set()
        assert release.wait(3)
        return late
    stream = CR.codex_stream(lambda: (SECRET, 'a'), client_factory=slow)
    failed = []

    def job():
        try:
            run(stream)
        except CR.FastTextError as error:
            failed.append(str(error))
    worker = threading.Thread(target=job, daemon=True)
    worker.start()
    assert made.wait(3)
    stream.close()
    release.set()
    worker.join(3)
    assert failed == ['closed'] and late.closed and not late.calls and stream._active == 0
