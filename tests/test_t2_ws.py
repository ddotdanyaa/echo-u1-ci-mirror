"""W12 (E59.1): the text channel over the Responses WebSocket (echo_sync.ws_transport.WsTransport) behind ``text_transport: "ws"``. No network: the server is a fake on a local socket
(websockets.sync.server on 127.0.0.1), the HTTP fallback is test_t1_transport's scripted client.

What the laptop measured (06.11 02:36, 12 triples): warm HTTP median 982 ms, p90 1572; the socket 656, p90 795; the socket with a ``generate:false`` warm-up 694, p90 950. The protocol, the headers and the frames are those of
cloud_context/scripts/exp_transport.py (WsArm). The guarantees are T1's: one connection per call, prepared when the call opens, pinged, a cancelled job does not cost the connection, two jobs in a row and prepare_wide,
a second connection for a job at the same time, a drop before the first text gets one retry; a drop again, a refused socket or a 426 put the call on HTTP for the rest of it, silently; the journal is the same; usage is read.
"""
import json
import logging
import threading
import time

import pytest

websockets = pytest.importorskip('websockets', reason='the laptop venv has websockets (exp_transport.py runs on it); pip install websockets==15.0.1')
from websockets.sync.server import serve  # noqa: E402

from echo_sync import fast_text as FT  # noqa: E402
from echo_sync import codex_road as CR
from echo_sync import ws_transport as WS  # noqa: E402
from echo_sync.settings import resolve  # noqa: E402
from test_h1_fast_text import until  # noqa: E402
from test_t1_transport import SECRET, Client, Factory, Resp, sse  # noqa: E402

HTTP_TEXT = [{'type': 'response.output_text.delta', 'delta': 'По HTTP.'}, {'type': 'response.completed'}]
USAGE = {'input_tokens': 900, 'output_tokens': 12, 'total_tokens': 912, 'input_tokens_details': {'cached_tokens': 640}, 'output_tokens_details': {'reasoning_tokens': 0}}


class Server:
    """The fake Responses socket. ``on(server, conn, number, request)`` answers one ``response.create`` (``number``: of the connection, from 0); the default warm-up answers ``response.completed`` with an id, a job ``Да.`` and
    ``response.completed`` with ``USAGE``. ``refuse``: the handshake is answered with that status."""

    def __init__(self, on=None, refuse=None):
        self.on, self.refuse = on, refuse
        self.connections, self.headers, self.requests, self.handshakes = [], [], [], 0
        self.lock = threading.Lock()
        self.server = serve(self._handler, '127.0.0.1', 0, process_request=self._process)
        self.url = f'ws://127.0.0.1:{self.server.socket.getsockname()[1]}/backend-api/codex/responses'
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def _process(self, connection, request):
        with self.lock:
            self.handshakes += 1
            self.headers.append(dict(request.headers.raw_items()))
        if self.refuse:
            return connection.respond(self.refuse, 'no\n')
        return None

    def _handler(self, conn):
        with self.lock:
            number = len(self.connections)
            self.connections.append(conn)
        try:
            for message in conn:
                request = json.loads(message)
                with self.lock:
                    self.requests.append((number, request))
                if self.on is not None and self.on(self, conn, number, request) is not None:
                    continue
                answer(conn, request)
        except websockets.ConnectionClosed:
            pass

    def jobs(self):
        return [(n, r) for n, r in self.requests if r.get('generate') is not False]

    def close(self):
        self.server.shutdown()


def answer(conn, request, text='Да.'):
    if request.get('generate') is False:
        conn.send(json.dumps({'type': 'response.completed', 'response': {'id': 'resp_warm', 'usage': {'input_tokens': 800}}}))
        return
    conn.send(json.dumps({'type': 'response.created', 'response': {'id': 'resp_1'}}))
    conn.send(json.dumps({'type': 'codex.rate_limits', 'rate_limits': {'primary': {'used_percent': 12}}}))
    conn.send(json.dumps({'type': 'response.output_text.delta', 'delta': text}))
    conn.send(json.dumps({'type': 'response.completed', 'response': {'id': 'resp_1', 'usage': USAGE}}))


@pytest.fixture
def server():
    made = []

    def make(**keywords):
        made.append(Server(**keywords))
        return made[-1]
    yield make
    for one in made:
        one.close()


def transport(srv, *clients, credentials=None, **keywords):
    factory = Factory(*(clients or (Client(),)))
    stream = WS.ws_stream(credentials or (lambda: (SECRET, 'acct-1')), url=srv.url, client_factory=factory, **keywords)
    return stream, factory


def run(stream, request=None, cancelled=None):
    return list(stream(request or {'model': 'm', 'instructions': 'i', 'input': []}, cancelled or threading.Event()))


def texts(deltas):
    return [d for d in deltas if isinstance(d, str)]


# =====================================================================================================================================
# 0. the setting and the point of choice
# =====================================================================================================================================

def test_text_transport_is_http_by_default_and_ws_on_request():
    assert resolve({})['text_transport'] == 'http'
    assert resolve({'text_transport': 'ws'})['text_transport'] == 'ws'
    assert resolve({'text_transport': 'carrier pigeon'})['text_transport'] == 'http'


class Controller:
    settings, ear_ended, source_segment_id = {}, None, None
    refuse_deadline = decision_due = staticmethod(lambda *a: None)      # no question open, no bound (``for_call`` reads both, hold8)

    def fast_exchanges(self):
        return []

    def fast_in_play(self):
        return None

    def fast_carry(self):
        return ''      # the memory of earlier calls (``for_call`` hands it to the channel)


def test_for_call_picks_the_transport_by_the_setting():
    creds = lambda: (SECRET, 'acct-1')  # noqa: E731
    plain = FT.for_call({'fast_text': 'on'}, Controller(), credentials=creds)
    ws = FT.for_call({'fast_text': 'on', 'text_transport': 'ws'}, Controller(), credentials=creds)
    assert isinstance(plain.stream, CR.CodexTransport) and not isinstance(plain.stream, WS.WsTransport)
    assert isinstance(ws.stream, WS.WsTransport) and isinstance(ws.stream.http, CR.CodexTransport)
    assert FT.for_call({'fast_text': 'off', 'text_transport': 'ws'}, Controller(), credentials=creds) is None


# =====================================================================================================================================
# 1. the protocol of exp_transport.py
# =====================================================================================================================================

def test_the_job_is_a_response_create_frame_with_the_request_and_the_headers_of_the_codex_sign_in(server, caplog):
    srv = server()
    stream, factory = transport(srv)
    caplog.set_level(logging.DEBUG, logger='echo-sync')
    request = {'model': CR.FAST_MODEL, 'instructions': 'i', 'stream': True, 'store': False, 'input': [{'type': 'message'}]}
    assert texts(run(stream, request)) == ['Да.']
    (number, sent), = srv.requests
    assert sent == {'type': 'response.create', **request}
    headers = {k.lower(): v for k, v in srv.headers[0].items()}
    assert headers['authorization'] == 'Bearer ' + SECRET and headers['chatgpt-account-id'] == 'acct-1'
    assert headers['openai-beta'] == WS.WS_BETA == 'responses_websockets=2026-02-06' and headers['originator'] == 'codex_cli_rs' and headers['user-agent'] == CR.USER_AGENT
    assert WS.WS_URL == 'wss://chatgpt.com/backend-api/codex/responses'
    assert SECRET not in caplog.text, 'the token is never logged'
    assert factory.made == [] or not factory.made[0].calls, 'nothing went over HTTP'
    stream.close()


def test_usage_of_response_completed_is_yielded_as_on_http(server):
    srv = server()
    stream, _ = transport(srv)
    out = run(stream)
    assert out == ['Да.', {'usage': {'input_tokens': 900, 'output_tokens': 12, 'total_tokens': 912, 'cached_tokens': 640, 'reasoning_tokens': 0}}]
    stream.close()


def test_a_failed_response_raises_and_the_socket_stays_the_channel(server):
    def on(srv, conn, number, request):
        if len(srv.jobs()) == 1:
            conn.send(json.dumps({'type': 'response.failed', 'response': {'error': {'code': 'server_error'}}}))
            return True
    srv = server(on=on)
    stream, factory = transport(srv)
    with pytest.raises(CR.FastTextError, match='response_failed'):
        run(stream)
    assert texts(run(stream)) == ['Да.'] and stream.mode == 'ws', 'a refusal of the model is the job\'s, not the transport\'s'
    assert not factory.made or not factory.made[0].calls
    stream.close()


def test_a_stream_that_never_completes_is_no_finished_answer(server, monkeypatch):
    monkeypatch.setattr(WS, 'FIRST_TEXT_S', 0.3)

    def on(srv, conn, number, request):
        conn.send(json.dumps({'type': 'response.output_text.delta', 'delta': 'Обры'}))
        return True                   # and nothing more: silent
    srv = server(on=on)
    stream, _ = transport(srv)
    got = []
    with pytest.raises(CR.FastTextError, match='timeout'):
        for delta in stream({'model': 'm'}, threading.Event()):
            got.append(delta)
    assert got == ['Обры'] and stream.mode == 'ws', 'slowness is no dead socket'
    stream.close()


# =====================================================================================================================================
# 2. one connection per call, warmed, pinged
# =====================================================================================================================================

def test_every_job_of_a_call_goes_over_the_one_socket(server):
    srv = server()
    stream, _ = transport(srv)
    for _ in range(3):
        assert texts(run(stream)) == ['Да.']
    assert srv.handshakes == 1 and [n for n, _ in srv.jobs()] == [0, 0, 0]
    stream.close()


def test_warm_opens_the_socket_and_sends_one_generate_false_with_the_instructions(server):
    srv = server()
    stream, _ = transport(srv, ping_s=60)
    stream.warm()
    assert until(lambda: len(srv.requests) == 1) and until(lambda: len(stream._idle) == 1), 'a question during the warm-up would get a second socket: wait for the first to be back'
    (number, warm), = srv.requests
    assert warm['type'] == 'response.create' and warm['generate'] is False and warm['instructions'] == FT.BRAIN_POLICY and warm['model'] == CR.FAST_MODEL
    assert warm['store'] is False and warm['input'] == []
    assert texts(run(stream)) == ['Да.'] and srv.handshakes == 1, 'the job goes over the warmed socket'
    assert 'previous_response_id' not in srv.jobs()[0][1], 'a job carries its whole request, nothing hangs on the warm-up'
    stream.close()


def test_a_warm_up_with_an_empty_input_refused_is_sent_once_more_with_one_short_line(server):
    def on(srv, conn, number, request):
        if request.get('generate') is False and not request['input']:
            conn.send(json.dumps({'type': 'error', 'status': 400, 'error': {'code': 'invalid_request'}}))
            return True
    srv = server(on=on)
    stream, _ = transport(srv)
    assert stream.prepare() is True
    warms = [r for _, r in srv.requests if r.get('generate') is False]
    assert len(warms) == 2 and warms[1]['input'][0]['content'][0]['text'] == 'Начало разговора.'
    assert texts(run(stream)) == ['Да.'] and srv.handshakes == 1
    stream.close()


def test_the_ping_keeps_the_socket_and_a_socket_the_server_closed_is_made_again_before_a_job_needs_it(server):
    srv = server()
    stream, _ = transport(srv, ping_s=60)
    assert texts(run(stream)) == ['Да.']
    assert stream.ping() is True and srv.handshakes == 1
    srv.connections[0].close()
    assert until(lambda: stream.ping() is True) and srv.handshakes == 2
    assert texts(run(stream)) == ['Да.'] and [n for n, _ in srv.jobs()] == [0, 1] and stream.mode == 'ws'
    stream.close()


def test_the_keep_alive_pings_every_ping_s(server, monkeypatch):
    srv = server()
    stream, _ = transport(srv, ping_s=0.05)
    pings = []
    real = WS.WsTransport.ping
    monkeypatch.setattr(WS.WsTransport, 'ping', lambda self: pings.append(1) or real(self))
    stream.warm()
    assert until(lambda: len(pings) >= 3)
    stream.close()


# =====================================================================================================================================
# 3. cancel, two in a row, two at once
# =====================================================================================================================================

def test_a_cancelled_job_does_not_cost_the_socket(server):
    gate = threading.Event()

    def on(srv, conn, number, request):
        if len(srv.jobs()) == 1:
            conn.send(json.dumps({'type': 'response.output_text.delta', 'delta': 'Перв'}))
            gate.wait(3)
            conn.send(json.dumps({'type': 'response.output_text.delta', 'delta': 'ое.'}))
            conn.send(json.dumps({'type': 'response.completed', 'response': {}}))
            return True
    srv = server(on=on)
    stream, _ = transport(srv)
    cancelled = threading.Event()
    for delta in stream({'model': 'm'}, cancelled):
        assert delta == 'Перв'
        cancelled.set()
        break
    gate.set()
    assert until(lambda: len(stream._idle) == 1), 'the rest of the cancelled answer is read off and the socket goes back'
    assert texts(run(stream)) == ['Да.'] and srv.handshakes == 1 and not srv.connections[0].close_code
    stream.close()


def test_a_job_while_another_holds_the_socket_gets_a_second_one_and_both_are_kept(server):
    gate, both = threading.Event(), threading.Barrier(2, timeout=3)

    def on(srv, conn, number, request):
        if request.get('generate') is False:
            return None
        if len(srv.jobs()) <= 2:
            both.wait()
            gate.wait(3)
        answer(conn, request, text=f'conn{number}')
        return True
    srv = server(on=on)
    stream, _ = transport(srv)
    results = []
    workers = [threading.Thread(target=lambda: results.append(texts(run(stream)))) for _ in range(2)]
    for worker in workers:
        worker.start()
    assert until(lambda: srv.handshakes == 2)
    gate.set()
    for worker in workers:
        worker.join(3)
    assert sorted(results) == [['conn0'], ['conn1']], 'prepare_wide: two jobs at once, two sockets'
    assert texts(run(stream)) in (['conn0'], ['conn1']) and texts(run(stream)) in (['conn0'], ['conn1']) and srv.handshakes == 2, 'both sockets are reused'
    stream.close()


def test_a_cancelled_job_that_still_streams_leaves_the_next_job_a_second_socket(server):
    gate = threading.Event()

    def on(srv, conn, number, request):
        if len(srv.jobs()) == 1:
            conn.send(json.dumps({'type': 'response.output_text.delta', 'delta': 'Долг'}))
            gate.wait(3)
            conn.send(json.dumps({'type': 'response.completed', 'response': {}}))
            return True
    srv = server(on=on)
    stream, _ = transport(srv)
    cancelled = threading.Event()
    for _ in stream({'model': 'm'}, cancelled):
        cancelled.set()
        break
    assert texts(run(stream)) == ['Да.'] and srv.handshakes == 2, 'the next question does not wait for the old answer to run out'
    gate.set()
    assert until(lambda: len(stream._idle) == 2)
    stream.close()


# =====================================================================================================================================
# 4. drops, 426: one retry, then HTTP for the rest of the call
# =====================================================================================================================================

def test_a_drop_before_the_first_text_gets_one_retry_on_a_new_socket(server, caplog):
    def on(srv, conn, number, request):
        if number == 0:
            conn.close()
            return True
    srv = server(on=on)
    stream, factory = transport(srv)
    caplog.set_level(logging.INFO, logger='echo-sync')
    assert texts(run(stream)) == ['Да.'] and srv.handshakes == 2 and stream.mode == 'ws'
    assert 'fast_text reconnect transport=ws' in caplog.text
    assert not factory.made or not factory.made[0].calls
    stream.close()


def test_a_second_drop_before_the_first_text_answers_the_job_over_http_and_the_call_stays_there(server, caplog):
    def on(srv, conn, number, request):
        conn.close()
        return True
    srv = server(on=on)
    stream, factory = transport(srv, Client(Resp(sse(*HTTP_TEXT)), Resp(sse(*HTTP_TEXT))))
    caplog.set_level(logging.INFO, logger='echo-sync')
    assert texts(run(stream)) == ['По HTTP.'] and stream.mode == 'http'
    assert texts(run(stream)) == ['По HTTP.'] and srv.handshakes == 2, 'no socket is tried again in this call'
    assert len(factory.made[0].calls) == 2 and 'fast_text ws_off' in caplog.text and SECRET not in caplog.text
    stream.close()


@pytest.mark.parametrize('status', [426, 403, 500])
def test_a_refused_socket_puts_the_call_on_http_silently(server, status):
    calls = []
    srv = server(refuse=status)
    stream, factory = transport(srv, Client(Resp(sse(*HTTP_TEXT)), Resp(sse(*HTTP_TEXT))), credentials=lambda: calls.append(1) or (SECRET, 'acct-1'))
    assert texts(run(stream)) == ['По HTTP.'] and stream.mode == 'http'
    assert texts(run(stream)) == ['По HTTP.'] and srv.handshakes == 1
    assert (len(calls) == 2) == (status == 403), 'a refusal of the sign-in drops the read of it, as on HTTP'
    stream.close()


def test_a_426_frame_before_the_first_text_moves_the_job_to_http(server):
    def on(srv, conn, number, request):
        conn.send(json.dumps({'type': 'error', 'status': 426, 'error': {'code': 'upgrade_required'}}))
        return True
    srv = server(on=on)
    stream, _ = transport(srv, Client(Resp(sse(*HTTP_TEXT))))
    assert texts(run(stream)) == ['По HTTP.'] and stream.mode == 'http'
    stream.close()


def test_a_drop_after_a_text_fails_the_job_and_puts_the_call_on_http(server):
    def on(srv, conn, number, request):
        conn.send(json.dumps({'type': 'response.output_text.delta', 'delta': 'Полов'}))
        time.sleep(0.05)
        conn.close()
        return True
    srv = server(on=on)
    stream, factory = transport(srv, Client(Resp(sse(*HTTP_TEXT))))
    got = []
    with pytest.raises(Exception):
        for delta in stream({'model': 'm'}, threading.Event()):
            got.append(delta)
    assert got == ['Полов'] and stream.mode == 'http', 'a text said is never said twice'
    assert texts(run(stream)) == ['По HTTP.'] and srv.handshakes == 1
    stream.close()


def test_without_the_websockets_package_the_call_goes_over_http(server, monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, 'websockets.sync.client', None)
    srv = server()
    stream, _ = transport(srv, Client(Resp(sse(*HTTP_TEXT))))
    assert texts(run(stream)) == ['По HTTP.'] and stream.mode == 'http' and srv.handshakes == 0
    stream.close()


def test_a_refusal_at_the_warm_up_puts_the_call_on_http_and_keeps_http_warm(server):
    srv = server(refuse=426)
    stream, factory = transport(srv, ping_s=60)
    stream.warm()
    assert until(lambda: stream.mode == 'http') and until(lambda: factory.made and factory.made[0].pings), 'HTTP is prepared and pinged instead'
    stream.close()


# =====================================================================================================================================
# 5. the call's end, and the channel above it
# =====================================================================================================================================

def test_close_closes_the_sockets_and_nothing_is_served_after(server):
    srv = server()
    stream, factory = transport(srv)
    assert texts(run(stream)) == ['Да.']
    stream.close()
    assert until(lambda: srv.connections[0].close_code is not None)
    with pytest.raises(CR.FastTextError, match='closed'):
        run(stream)
    assert srv.handshakes == 1 and (not factory.made or not factory.made[0].calls)


def test_the_fast_job_line_is_the_same_on_both_transports(server):
    srv = server()
    lines = {}
    for name in ('http', 'ws'):
        notes = []
        if name == 'ws':
            stream, _ = transport(srv)
        else:
            stream = CR.codex_stream(lambda: (SECRET, 'acct-1'), client_factory=Factory(Client(Resp(sse({'type': 'response.output_text.delta', 'delta': 'Да.'},
                                                                                                        {'type': 'response.completed', 'response': {'usage': USAGE}})))))
        channel = FT.FastText(stream, instructions=lambda: FT.BRAIN_POLICY, history=lambda: [], report=lambda ev, **fields: notes.append((ev, fields)))
        channel.release(qid='q1', turn=1, epoch=1, question='Сколько будет пять на пять?')
        assert until(lambda: channel.job is None or channel.job.outcome is not None)
        until(lambda: [e for e in channel.poll() if e['kind'] == 'done'] or channel.job is None)
        jobs = [fields for ev, fields in notes if ev == 'fast_job']
        assert len(jobs) == 1 and jobs[0]['outcome'] == 'ok' and jobs[0]['cached_tokens'] == 640
        lines[name] = jobs[0]
        channel.close()
    assert set(lines['ws']) == set(lines['http'])


def test_a_call_closed_under_a_job_ends_it_quietly_and_goes_nowhere_else(server, caplog):
    gate = threading.Event()

    def on(srv, conn, number, request):
        gate.wait(3)
        return True
    srv = server(on=on)
    stream, factory = transport(srv)
    caplog.set_level(logging.INFO, logger='echo-sync')
    errors = []

    def job():
        try:
            run(stream)
        except Exception as error:  # noqa: BLE001
            errors.append(error)
    worker = threading.Thread(target=job)
    worker.start()
    assert until(lambda: srv.jobs())
    stream.close()
    worker.join(3)
    gate.set()
    assert len(errors) == 1 and isinstance(errors[0], CR.FastTextError) and str(errors[0]) == 'closed'
    assert 'ws_off' not in caplog.text and 'reconnect' not in caplog.text and (not factory.made or not factory.made[0].calls)
