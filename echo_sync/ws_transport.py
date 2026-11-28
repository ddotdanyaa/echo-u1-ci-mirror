"""W12 (E59.1): the text channel over the Responses WebSocket, behind ``text_transport: "ws"`` (``fast_text.for_call``). The laptop, 06.11 02:36, 12 triples: warm HTTP (T1) median 982 ms, p90 1572; the socket 656,
p90 795; the socket with a ``generate:false`` warm-up just before the request 694, p90 950 (C-A -330 ms p=0.04, B-A -354 ms p=0.15).

The protocol is the experiment's (cloud_context/scripts/exp_transport.py, WsArm, after codex-rs/core/src/client.rs): ``wss://chatgpt.com/backend-api/codex/responses`` with ``OpenAI-Beta: responses_websockets=2026-02-06``
and the headers of the Codex sign-in (as ``CodexTransport``: the token in the handshake only, never logged); a request is ONE text frame ``{"type": "response.create", **body}`` (the very body of the HTTP request), the answer the
same events as the SSE lines, one per frame: ``response.output_text.delta``, ``response.completed`` (``usage``), ``response.failed`` / ``response.incomplete`` / ``error``; ``codex.rate_limits`` and the rest are skipped.

* ``WsTransport`` is ``CodexTransport``'s shape: ``transport(request, cancelled) -> deltas`` (and ``{'usage': ...}`` last), ``warm``, ``prepare``, ``ping``, ``close``. It holds the call's HTTP transport (``http``): the sign-in is
  read through it (one read, one TTL for both) and it is where the call goes when the socket does not.
* ONE socket per call, opened by ``warm`` (with one ``generate:false`` request with ``BRAIN_POLICY``: the server has the instructions before the first question; nothing hangs on its id, a job carries its whole request) or by
  the first job, and kept: a socket serves one answer at a time, so a job that finds every socket busy (``prepare_wide``, the tail's twin, a cancelled answer still running out) opens another, and up to ``KEEP`` idle ones are kept.
* A cancelled job leaves its socket to a thread that reads the rest of that answer off (``DRAIN_S`` at most) and gives the socket back; nothing is torn down. A ping frame every ``PING_S`` while no job runs; a socket that does
  not answer it is let go and one is opened again.
* A drop before the first text: one retry on a new socket (``reconnect transport=ws`` in the log). A drop again, a drop after a text (that job fails: no word is said twice), a socket refused at the handshake (426, 403, no
  ``websockets``, anything) or a 426 frame: the call goes over HTTP to its end (``ws_off`` in the log), silently, and the job that saw it, if nothing was said, is answered there.
"""
import contextlib
import json
import logging
import threading
import time

from .diagnostics import reason_of
from .codex_road import FAST_EFFORT, FAST_MODEL, FAST_URL, PING_S, PING_TIMEOUT_S, USER_AGENT, CodexTransport, FastTextError, _usage, failed_token, wire
from .fast_text import BRAIN_POLICY, FIRST_TEXT_S, WHOLE_S
from .timer_policy import POLL_SLICE_S

logger = logging.getLogger('echo-sync')

WS_URL = 'wss://chatgpt.com/backend-api/codex/responses'
WS_BETA = 'responses_websockets=2026-02-06'       # codex-rs/core/src/client.rs RESPONSES_WEBSOCKETS_V2_BETA_HEADER_VALUE (exp_transport.py)
KEEP = 2                     # idle sockets kept: the second is prepare_wide's, more would be sockets nobody uses
DRAIN_S = WHOLE_S            # the rest of a cancelled answer: the socket is nobody's until its answer is over
WARM_LINE = 'Начало разговора.'      # the warm-up's input when the server will not take an empty one (exp_transport.WsArm.warm)
_TERMINAL = ('response.completed', 'response.failed', 'response.incomplete', 'error')
_DEAD = frozenset({'ConnectionClosed', 'ConnectionError', 'BrokenPipeError', 'EOFError', 'InvalidState'})


class _Off(Exception):
    """The socket is no way for this call (refused at the handshake, a 426): HTTP to the end."""


def _dead(error):
    """A socket that was there and is gone (by the names in the lineage: websockets need not be imported). A timeout is slowness, not a dead socket."""
    names = {kind.__name__ for kind in type(error).__mro__}
    return 'TimeoutError' not in names and bool(names & _DEAD or (isinstance(error, OSError)))


def _status(error):
    response = getattr(error, 'response', None)
    status = getattr(response, 'status_code', None)
    return status if isinstance(status, int) else None


def _connect(url, headers):
    from websockets.sync.client import connect   # noqa: PLC0415 - only a real call needs it; without it the call is on HTTP
    return connect(url, additional_headers=headers, open_timeout=FIRST_TEXT_S)      # the proxy is the system's, as httpx's (exp_transport.py)


def _close_quietly(sock):
    with contextlib.suppress(Exception):
        sock.close()


def _closer(sock):
    threading.Thread(target=_close_quietly, args=(sock,), name='echo-fast-text-ws-close', daemon=True).start()


class WsTransport:
    """The call's text channel over the socket, HTTP (``http``, a ``CodexTransport``) behind it. ``connect(url, headers) -> socket`` (``send``, ``recv(timeout)``, ``ping() -> Event``, ``close``) is the seam of the tests."""

    def __init__(self, credentials, *, connect=None, client_factory=None, url=WS_URL, http_url=FAST_URL, ping_s=PING_S, instructions=BRAIN_POLICY, ready=0):
        self.http = CodexTransport(credentials, client_factory=client_factory, url=http_url, ping_s=ping_s)
        self.first_text_s = FIRST_TEXT_S      # h31 (F21): the wait for a message; ``for_call`` moves it to GIVE_UP_S when the tail guard is on
        self.connect, self.url, self.ping_s = connect or _connect, url, ping_s
        self.instructions, self.ready, self._filling = instructions, ready, False     # f2-model: what the warm-up primes (the jobs' own: the short BRAIN under brain_short); idle sockets kept ready beside a job
        self.mode = 'ws'
        self._state = threading.Lock()
        self._idle, self._all = [], set()
        self._active = 0
        self._closed = self._warmed = False
        self._thread = None
        self._stop = threading.Event()

    # -- the sockets ----------------------------------------------------------------------------------------------------------------
    def _headers(self):
        token, account = self.http._sign_in()
        return {'Authorization': 'Bearer ' + token, 'ChatGPT-Account-Id': account, 'originator': 'codex_cli_rs', 'User-Agent': USER_AGENT, 'OpenAI-Beta': WS_BETA}

    def _open(self):
        """A new socket, or ``_Off`` (with the reason) when the socket is refused; ``FastTextError('closed')`` after the call."""
        headers = self._headers()
        try:
            sock = self.connect(self.url, headers)
        except Exception as error:
            status = _status(error)
            if status in (401, 403):
                self.http._signed = None          # as on HTTP: a refusal drops the read of the sign-in
            raise _Off(f'connect_{status}' if status else reason_of(error)) from None
        with self._state:
            late = self._closed
            if not late:
                self._all.add(sock)
        if late:
            _closer(sock)
            raise FastTextError('closed')
        return sock

    def _take(self):
        with self._state:
            if self._closed:
                raise FastTextError('closed')
            sock = self._idle.pop() if self._idle else None
        self._refill()
        return sock or self._open()

    def _refill(self):
        """f2-model: a job took the last idle socket: the next one is opened beside it, in a thread, so that the tail's twin, a job while a cancelled answer runs out or ``prepare_wide`` find a socket and pay no
        handshake before their first token (live, all on: 1.5 s against 1.09). A handshake costs no quota; ``KEEP`` bounds what is kept. A refusal puts the call on HTTP, as on a ping; anything else is silent."""
        with self._state:
            if self._closed or self.mode != 'ws' or self._filling or len(self._idle) >= self.ready:
                return
            self._filling = True

        def fill():
            try:
                self._give(self._open())
            except _Off as error:
                self._to_http(str(error))
            except Exception as error:             # noqa: BLE001 - the job opens its own, as before
                logger.debug('echo-sync fast_text ready transport=ws failed reason=%s', reason_of(error))
            finally:
                self._filling = False
        threading.Thread(target=fill, name='echo-fast-text-ws-ready', daemon=True).start()

    def _give(self, sock):
        with self._state:
            if not self._closed and self.mode == 'ws' and sock in self._all and len(self._idle) < KEEP:
                self._idle.append(sock)
                return
            self._all.discard(sock)
        _closer(sock)

    def _drop(self, sock):
        with self._state:
            self._all.discard(sock)
            if sock in self._idle:
                self._idle.remove(sock)
        _closer(sock)

    def _to_http(self, reason):
        """The rest of the call goes over HTTP: the sockets are let go, and if the call was warmed, HTTP is warmed and pinged instead."""
        with self._state:
            if self.mode == 'http':
                return
            self.mode = 'http'
            socks, self._idle, self._all = list(self._all), [], set()
            warm = self._warmed and not self._closed
        logger.warning('echo-sync fast_text ws_off reason=%s', reason)
        for sock in socks:
            _closer(sock)
        if warm:
            self.http.warm()

    # -- the job's call -------------------------------------------------------------------------------------------------------------
    def __call__(self, request, cancelled):
        if self.mode == 'http':
            yield from self.http(request, cancelled)
            return
        with self._state:
            self._active += 1
        try:
            retried = False
            while True:
                if cancelled.is_set():
                    return
                said = False
                try:
                    sock = self._take()
                    for delta in self._once(sock, request, cancelled):
                        said = said or isinstance(delta, str)
                        yield delta
                    return
                except _Off as error:
                    self._to_http(str(error))
                    if said:
                        raise FastTextError('ws_off') from None
                except FastTextError:
                    raise
                except Exception as error:
                    if self._closed:
                        raise FastTextError('closed') from None
                    if not _dead(error) or cancelled.is_set():
                        raise
                    if said:
                        self._to_http(reason_of(error))
                        raise
                    if not retried:
                        retried = True
                        logger.info('echo-sync fast_text reconnect transport=ws reason=%s', reason_of(error))
                        continue
                    self._to_http(reason_of(error))
                break
        finally:
            with self._state:
                self._active -= 1
        if not cancelled.is_set():
            yield from self.http(request, cancelled)

    def _once(self, sock, request, cancelled):
        """One answer on ``sock``. Whatever way it ends, the socket is given back (completed), read off (cancelled, timed out, abandoned) or dropped (dead, refused)."""
        over = False
        try:
            try:
                sock.send(json.dumps({'type': 'response.create', **wire(request)}, ensure_ascii=False))
            except Exception:
                over = True
                self._drop(sock)
                raise
            deadline = time.monotonic() + self.first_text_s
            while True:
                if cancelled.is_set():
                    return
                try:
                    message = sock.recv(timeout=POLL_SLICE_S)
                except TimeoutError:
                    if time.monotonic() > deadline:
                        raise FastTextError('ws_timeout') from None
                    continue
                except Exception:
                    over = True
                    self._drop(sock)
                    raise
                deadline = time.monotonic() + self.first_text_s
                event = self._event(message)
                kind = event.get('type')
                if kind == 'response.output_text.delta':
                    delta = event.get('delta')
                    if isinstance(delta, str) and delta:
                        yield delta
                elif kind == 'response.completed':
                    over = True
                    self._give(sock)
                    spent = _usage(event)
                    if spent:
                        yield {'usage': spent}
                    return
                elif kind in _TERMINAL:
                    over = True
                    self._drop(sock)           # what a socket is worth after a refused answer nobody knows: a new one costs one handshake
                    if event.get('status') == 426:
                        raise _Off('frame_426')
                    raise FastTextError(failed_token(event, kind))
        finally:
            if not over:
                self._read_off(sock)

    @staticmethod
    def _event(message):
        if isinstance(message, bytes):
            return {}
        try:
            event = json.loads(message)
        except ValueError:
            return {}
        return event if isinstance(event, dict) else {}

    def _read_off(self, sock):
        """The answer on ``sock`` is nobody's any more: its rest is read off in a thread (``DRAIN_S`` at most) and the socket given back at its end; anything else and it is let go."""
        def read():
            end = time.monotonic() + DRAIN_S
            try:
                while time.monotonic() < end:
                    try:
                        kind = self._event(sock.recv(timeout=max(0.01, end - time.monotonic()))).get('type')
                    except TimeoutError:
                        break
                    if kind == 'response.completed':
                        self._give(sock)
                        return
                    if kind in _TERMINAL:
                        break
            except Exception:                 # noqa: BLE001 - a socket being let go
                pass
            self._drop(sock)
        threading.Thread(target=read, name='echo-fast-text-ws-drain', daemon=True).start()

    # -- the call's opening and the socket kept --------------------------------------------------------------------------------------
    def _warm_up(self, sock):
        """``generate:false`` with the instructions (exp_transport.WsArm.warm): empty input first, one short line if the server will not take it. True when one was completed."""
        for line in ((), (WARM_LINE,)):
            body = {'type': 'response.create', 'model': FAST_MODEL, 'instructions': self.instructions, 'stream': True, 'store': False, 'reasoning': {'effort': FAST_EFFORT}, 'generate': False,
                    'input': [{'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text': text}]} for text in line]}
            sock.send(json.dumps(body, ensure_ascii=False))
            end = time.monotonic() + FIRST_TEXT_S
            while True:
                left = end - time.monotonic()
                if left <= 0:
                    raise FastTextError('ws_timeout')
                event = self._event(sock.recv(timeout=left))
                kind = event.get('type')
                if kind == 'response.completed':
                    return True
                if kind in _TERMINAL:
                    if event.get('status') == 426:
                        raise _Off('frame_426')
                    break
        return False

    def prepare(self):
        """In the calling thread: the sign-in, the socket, the warm-up. True when all worked. A refused socket puts the call on HTTP (and HTTP is prepared); anything else is silent and the first job goes as it would have."""
        if self.mode == 'http':
            return self.http.prepare()
        started, opened, warmed, reason, sock = time.monotonic(), False, False, '-', None
        try:
            sock = self._take()
            opened = True
            warmed = self._warm_up(sock)
            self._give(sock)
        except _Off as error:
            reason = str(error)
            self._to_http(reason)
        except Exception as error:            # noqa: BLE001 - the first job opens its own
            reason = reason_of(error)
            if sock is not None:
                self._drop(sock)
        logger.info('echo-sync fast_text warm transport=ws ok=%s opened=%s warmed=%s ms=%s reason=%s', int(opened and warmed), int(opened), int(warmed), round((time.monotonic() - started) * 1000), reason)
        return opened and warmed

    def ping(self):
        """A ping frame on an idle socket: True when it was answered. Skipped while a job runs and after ``close``. A socket that does not answer is let go and one is opened again (one try). Never raises."""
        with self._state:
            if self._closed or self._active or self.mode != 'ws':
                return False
            sock = self._idle.pop(0) if self._idle else None      # f2-model: the oldest: ``_give`` puts it back last, so every idle socket is pinged in turn
        if sock is not None:
            try:
                if sock.ping().wait(PING_TIMEOUT_S):
                    self._give(sock)
                    return True
            except Exception as error:         # noqa: BLE001 - a ping is never anybody's failure
                logger.debug('echo-sync fast_text ping transport=ws failed reason=%s', reason_of(error))
            self._drop(sock)
        try:
            sock = self._open()
            self._give(sock)
            return True
        except _Off as error:
            self._to_http(str(error))
        except Exception as error:             # noqa: BLE001
            logger.debug('echo-sync fast_text ping transport=ws reopen failed reason=%s', reason_of(error))
        return False

    def warm(self):
        """The call opened: ``prepare`` and a ping every ``ping_s`` until ``close``, in ONE daemon thread. Returns at once, once."""
        with self._state:
            if self._closed or self._thread is not None:
                return
            self._warmed = True
            self._thread = threading.Thread(target=self._keep_warm, name='echo-fast-text-ws-keepalive', daemon=True)
        if self.mode == 'http':
            self.http.warm()
        self._thread.start()

    def _keep_warm(self):
        with contextlib.suppress(Exception):
            if self.mode == 'ws':
                self.prepare()
        while not self._stop.wait(self.ping_s):
            if self.mode != 'ws':
                return                          # HTTP keeps itself warm (``_to_http``)
            with contextlib.suppress(Exception):
                self.ping()

    def close(self):
        """With the call: every socket closed (in threads), the pings stopped, HTTP closed; nothing is served after it. Twice is harmless."""
        with self._state:
            self._closed = True
            socks, self._idle, self._all = list(self._all), [], set()
        self._stop.set()
        for sock in socks:
            _closer(sock)
        self.http.close()


def ws_stream(credentials, *, connect=None, client_factory=None, url=WS_URL, http_url=FAST_URL, ping_s=PING_S, instructions=BRAIN_POLICY, ready=0):
    """The transport of ONE call over the socket, HTTP behind it (``WsTransport``)."""
    return WsTransport(credentials, connect=connect, client_factory=client_factory, url=url, http_url=http_url, ping_s=ping_s, instructions=instructions, ready=ready)
