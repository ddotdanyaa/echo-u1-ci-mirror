"""f2-model (wave 15): ``tail_guard`` + ``brain_short`` + ``text_transport=ws`` together. Live: the first token 1.5 s against 1.09 s. What the code shows (cloud_context/reports/f2-model.md):
1. the socket's warm-up primed the long BRAIN while every job under ``brain_short`` sent the short one: the prefix the server had was not the jobs';
2. a job that found the one socket busy (the tail's twin, a cancelled prepared job reading its rest off) paid a handshake before its first token: the call keeps one socket ready (``ready``);
3. the socket's own slowness (``ws_timeout``) and the move to HTTP after a text (``ws_off``) were the model's errors for the tail: three of them put the channel out for the call; they are stalls, as ReadTimeout on HTTP."""
import json
import threading

import pytest

pytest.importorskip('websockets', reason='pip install websockets==15.0.1 (test_t2_ws.py)')

from echo_sync import brain_short as BS  # noqa: E402
from echo_sync import fast_text as FT  # noqa: E402
from echo_sync import codex_road as CR
from echo_sync import ws_transport as WS  # noqa: E402
from test_h1_fast_text import until  # noqa: E402
from test_t1_transport import SECRET  # noqa: E402
from test_t2_ws import Controller, answer, run, server, texts, transport  # noqa: E402,F401


# -- 1. the warm-up primes what the jobs send -----------------------------------------------------------------------------------------
def test_the_warm_up_sends_the_instructions_it_is_given(server):
    srv = server()
    stream, _ = transport(srv, instructions=BS.SHORT_POLICY)
    assert stream.prepare() is True
    (_, warm), = [(n, r) for n, r in srv.requests if r.get('generate') is False]
    assert warm['instructions'] == BS.SHORT_POLICY
    stream.close()


def test_for_call_warms_the_socket_with_the_short_brain_when_it_is_on():
    creds = lambda: (SECRET, 'acct-1')  # noqa: E731
    short = FT.for_call({'fast_text': 'on', 'text_transport': 'ws', 'brain_short': 'on'}, Controller(), credentials=creds)
    long = FT.for_call({'fast_text': 'on', 'text_transport': 'ws'}, Controller(), credentials=creds)
    assert short.stream.instructions == BS.SHORT_POLICY and long.stream.instructions == FT.BRAIN_POLICY
    job = short._start('Что такое инерция?')
    assert job.request['instructions'].startswith(short.stream.instructions), 'the warmed prefix is the prefix of the job'
    for one in (short, long):
        one.close()


# -- 2. one socket ready: the twin and the job after a cancel pay no handshake ---------------------------------------------------
def test_for_call_keeps_one_socket_ready_on_the_socket():
    fast = FT.for_call({'fast_text': 'on', 'text_transport': 'ws'}, Controller(), credentials=lambda: (SECRET, 'acct-1'))
    assert fast.stream.ready == 1
    fast.close()


def test_without_ready_nothing_more_is_opened(server):
    srv = server()
    stream, _ = transport(srv)
    for _ in range(3):
        assert texts(run(stream)) == ['Да.']
    assert srv.handshakes == 1, 'the default of the class is the old one'
    stream.close()


def test_a_job_on_the_last_socket_has_the_next_one_opened_beside_it(server):
    srv = server()
    stream, _ = transport(srv, ready=1)
    assert texts(run(stream)) == ['Да.']
    assert until(lambda: srv.handshakes == 2 and len(stream._idle) == 2)
    for _ in range(3):
        assert texts(run(stream)) == ['Да.']
    assert srv.handshakes == 2, 'two sockets, kept: no handshake per job'
    stream.close()


def test_the_twin_of_a_silent_job_finds_a_socket_ready(server):
    gate, slow = threading.Event(), []

    def on(srv, conn, number, request):
        if request.get('generate') is not False and not slow:
            slow.append(number)
            gate.wait(5)
        answer(conn, request)
        return True
    srv = server(on=on)
    stream, _ = transport(srv, ready=1)
    assert stream.prepare() is True and until(lambda: len(stream._idle) == 2)
    first = threading.Thread(target=lambda: run(stream))
    first.start()
    assert until(lambda: slow) and srv.handshakes == 2 and len(stream._idle) == 1, 'the first job took one socket, one is left ready'
    assert texts(run(stream)) == ['Да.'] and srv.jobs()[-1][0] in (0, 1), 'the twin went over a socket that was ready: no handshake on its way to the first token'
    assert until(lambda: srv.handshakes == 3 and len(stream._idle) == 2), 'and the next one is opened beside'
    gate.set()
    first.join(3)
    stream.close()


def test_the_job_after_a_cancelled_one_that_still_streams_takes_the_ready_socket(server):
    gate = threading.Event()

    def on(srv, conn, number, request):
        if len(srv.jobs()) == 1:
            conn.send(json.dumps({'type': 'response.output_text.delta', 'delta': 'Долг'}))
            gate.wait(3)
            conn.send(json.dumps({'type': 'response.completed', 'response': {}}))
            return True
    srv = server(on=on)
    stream, _ = transport(srv, ready=1)
    cancelled = threading.Event()
    for _ in stream({'model': 'm'}, cancelled):
        cancelled.set()
        break
    assert until(lambda: srv.handshakes == 2 and len(stream._idle) == 1)
    assert texts(run(stream)) == ['Да.'] and srv.jobs()[-1][0] in {0, 1} - {srv.jobs()[0][0]}, 'the next question went over the socket opened beside, not over a new handshake'
    gate.set()
    stream.close()


def test_the_ping_reaches_every_idle_socket(server):
    srv = server()
    stream, _ = transport(srv, ready=1, ping_s=60)
    assert texts(run(stream)) == ['Да.'] and until(lambda: len(stream._idle) == 2)
    pinged = []
    for sock in list(stream._idle):
        real = sock.ping
        sock.ping = lambda real=real, sock=sock: pinged.append(sock) or real()
    assert stream.ping() and stream.ping()
    assert len(set(map(id, pinged))) == 2, 'a ready socket nobody pings dies at the server and costs the job a reconnect'
    stream.close()


def test_a_closed_call_opens_nothing_beside(server):
    srv = server()
    stream, _ = transport(srv, ready=1)
    stream.close()
    with pytest.raises(CR.FastTextError):
        run(stream)
    assert srv.handshakes == 0
