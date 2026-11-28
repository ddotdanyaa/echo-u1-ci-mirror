"""The first road of the roads of text: the Codex route (the sign-in of the profile, ``POST chatgpt.com/backend-api/codex/responses`` or its Responses WebSocket), in ONE file (U79). The engine reaches Codex only
through ``primary(resolved, credentials)``, which gives the first road of ``reserve_text.Roads``; ``wire(request)`` is how this road words the job's request (``fast_text.build_request``: what is asked) on its wire. Replacing the
route means replacing this file (and ``ws_transport.py``, its socket variant). Nothing of the dialogue is logged here: the token is in the headers only."""
import contextlib
import json
import logging
import threading
import time

from .diagnostics import reason_of
from .fast_text import BRAIN_POLICY, FIRST_TEXT_S, _optional

logger = logging.getLogger('echo-sync')

FAST_MODEL = 'gpt-5.6-luna'
FAST_EFFORT = 'low'
FAST_URL = 'https://chatgpt.com/backend-api/codex/responses'
CREDENTIALS_TTL_S = 300.0    # how long a read of the sign-in is kept (a refusal drops it at once)
# T1: httpx closes an idle connection after 5 s by default, a call asks every 20-60 s: the connection lives 2 minutes (``KEEPALIVE_S``) and a light request every ``PING_S`` keeps it so. The ping is a plain GET of Cloudflare's
# trace page of the host (what chatgpt.com answers at the edge, no origin, no model, no quota, 200 in ~60 ms on a warm connection, ``Connection: keep-alive`` on the same socket; scripts/exp_transport.py). No token goes with it.
KEEPALIVE_S = 120.0
PING_S = 30.0
WS_READY = 1                 # f2-model: idle sockets kept ready beside a job on ``text_transport: "ws"`` (the twin, the job after a cancel: no handshake before the first token)
PING_TIMEOUT_S = 5.0
DRAIN_S = 4.0                # the rest of a body after response.completed (0-415 ms on the real endpoint): httpx's timeout is per read, a body that trickles would keep its reader as long as it likes
PING_URL = 'https://chatgpt.com/cdn-cgi/trace'
USER_AGENT = 'codex_cli_rs/0.1'


class FastTextError(Exception):
    """A failure of the call; the message is a fixed token (``http_401``…), never a body or a word of the dialogue."""



def _usage(event):
    """H7 item 1: the numbers of ``usage`` of ``response.completed``, and nothing else of it."""
    response = event.get('response')
    usage = response.get('usage') if isinstance(response, dict) else None
    if not isinstance(usage, dict):
        return {}
    found = {key: usage.get(key) for key in ('input_tokens', 'output_tokens', 'total_tokens')}
    for key, part, name in (('input_tokens_details', 'cached_tokens', 'cached_tokens'), ('output_tokens_details', 'reasoning_tokens', 'reasoning_tokens')):
        found[name] = usage[key].get(part) if isinstance(usage.get(key), dict) else None
    return {key: value for key, value in found.items() if type(value) is int}


def failed_token(event, kind):
    """U107: the fixed token of a refused or cut answer: ``usage_limit`` when the code or type of its error names a limit or a quota (the usage limit of the subscription, a rate limit: ``Roads._rest`` rests the first road
    ``PRIMARY_QUOTA_REST_S``, as after a 429), else the kind of the event. Only the token leaves: never a word of the body."""
    error = event.get('error') if isinstance(event.get('error'), dict) else (event.get('response') or {}).get('error') if isinstance(event.get('response'), dict) else None
    named = ' '.join(str(error.get(key) or '') for key in ('code', 'type')).lower() if isinstance(error, dict) else ''
    return 'usage_limit' if any(mark in named for mark in ('usage_limit', 'rate_limit', 'quota', 'insufficient')) else kind.replace('.', '_')


def _httpx_client():
    import httpx                          # noqa: PLC0415 - only a real call needs it
    return httpx.Client(http2=False, limits=httpx.Limits(keepalive_expiry=KEEPALIVE_S))


# A connection that was there and is gone (the peer closed it, the VPN dropped it, the VPN's local proxy refused the tunnel: httpx's ProxyError is no NetworkError): by the names in the exception's lineage, so that httpx need
# not be imported. A timeout is no dead socket: it is slowness, and a retry would double the wait of a job that has 4 s.
_DEAD_SOCKET = frozenset({'NetworkError', 'RemoteProtocolError', 'ConnectionError', 'ProxyError'})


def _dead_socket(error):
    return any(kind.__name__ in _DEAD_SOCKET for kind in type(error).__mro__)


def _close_quietly(http):
    try:
        close = getattr(http, 'close', None)
        if close:
            close()
    except Exception:                     # noqa: BLE001 - a client being let go
        pass


class CodexTransport:
    """T1: the streaming call as ``transport(request, cancelled) -> iterator of text deltas`` (run in the job's thread) over ONE httpx client for the whole call. ``credentials()`` -> ``(token, account)`` is the host's (the
    profile's Codex sign-in); it is read once in CREDENTIALS_TTL_S and again after a refusal. The token is in the headers only. A refusal raises with the status alone, the body is never read. Only ``response.completed``
    is the end of an answer: a stream that ends otherwise (``response.failed`` / ``response.incomplete``, an ``error`` frame, the lines running out) raises, so a cut text is a failure and never a finished answer.

    ``client_factory`` is the seam of the tests. The client is made when it is first needed (``warm``/``prepare`` or a job) and closed by ``close`` with the call; after it nothing is served and nothing is made. A dead socket
    before the first text is retried once on a new client (``reconnect`` in the log), after a text never (it would be said twice). A job that is cancelled closes ITS response and leaves the client; the connection that response
    held goes with it (httpcore cannot reuse a body left unread), so one light request re-warms the pool in the background. At ``response.completed`` the job is over, and a thread reads the rest of the body off (50-130 ms
    after completed on the real endpoint) so that the connection goes back to the pool: an early return there closed it, and every job reconnected even on one client."""

    def __init__(self, credentials, *, client_factory=None, url=FAST_URL, ping_url=PING_URL, ping_s=PING_S):
        self.credentials, self.client_factory, self.url, self.ping_url, self.ping_s = credentials, client_factory, url, ping_url, ping_s
        self._sign, self._build, self._state = threading.Lock(), threading.Lock(), threading.Lock()      # the sign-in read, the client being made (slow), the few fields below (instant)
        self._signed = self._http = self._thread = None
        self.first_text_s = FIRST_TEXT_S      # h31 (F21): the bound of the wait for bytes; ``for_call`` moves it to reserve_text.GIVE_UP_S
        self._closed = self._rewarming = False
        self._active = 0
        self._uses, self._retired = {}, set()      # w3-integ 15: the jobs on each client (id -> [client, count]) and the clients let go that a job still reads from
        self._stop = threading.Event()

    # -- the sign-in and the client -------------------------------------------------------------------------------------------------
    def _sign_in(self):
        with self._sign:                  # one read at a time: the warm-up's and the first job's are one
            if self._closed:              # it goes through the loop's executor and may refresh a token: not for a call that is over
                raise FastTextError('closed')
            now = time.monotonic()
            if self._signed is None or now - self._signed[0] > CREDENTIALS_TTL_S:
                token, account = self.credentials()
                self._signed = (now, token, account)
            return self._signed[1], self._signed[2]

    def _client(self):
        with self._build:                 # a slow make (the first httpx client took 571 ms) holds up only the others who need a client, never ``close``
            with self._state:
                if self._closed:
                    raise FastTextError('closed')
                http = self._http
            if http is None:
                http = (self.client_factory or _httpx_client)()
                with self._state:
                    late = self._closed
                    if not late:
                        self._http = http
                if late:
                    _close_quietly(http)
                    raise FastTextError('closed')
            return http

    def _renew(self, old, *, idle=False):
        """``old`` has a connection that is gone: it is let go (in a thread, a close must not hold up a job or the loop), the next ``_client`` makes a new one; True then. ``idle``: only while no job is in flight (False): closing a client
        closes every socket of it, and a job that began while a ping waited has a healthy one, with an answer in the middle. A job counts itself in before it takes the client, so the two cannot miss each other under ``_state``."""
        with self._state:
            if idle and self._active:
                return False
            if self._http is old:
                self._http = None
            if self._uses.get(id(old), (None, 0))[1]:     # w3-integ 15 (prepare_wide: two jobs on one client): another job is in the middle of its answer on it; the last one out closes it
                self._retired.add(id(old))
                return True
        threading.Thread(target=_close_quietly, args=(old,), name='echo-fast-text-close', daemon=True).start()
        return True

    def _use(self, client, step):
        """w3-integ 15: a job takes (+1) or leaves (-1) ``client``; a client let go by ``_renew`` while in use is closed by the last job that leaves it."""
        with self._state:
            row = self._uses.setdefault(id(client), [client, 0])
            row[1] += step
            if row[1] > 0:
                return
            del self._uses[id(client)]
            if id(client) not in self._retired:
                return
            self._retired.discard(id(client))
        threading.Thread(target=_close_quietly, args=(client,), name='echo-fast-text-close', daemon=True).start()

    # -- the job's call ---------------------------------------------------------------------------------------------------------------
    def __call__(self, request, cancelled):
        token, account = self._sign_in()
        headers = {'Authorization': 'Bearer ' + token, 'ChatGPT-Account-Id': account, 'originator': 'codex_cli_rs', 'User-Agent': USER_AGENT,
                   'Accept': 'text/event-stream', 'Content-Type': 'application/json'}
        retried = sent = False
        with self._state:
            self._active += 1
        try:
            while True:
                client = self._client()
                if cancelled.is_set():    # during the sign-in or the make: a model request for nobody would also take the one warm connection with it
                    return
                said, sent = False, True
                self._use(client, +1)
                try:
                    for delta in self._once(client, headers, request, cancelled):
                        said = True
                        yield delta
                    return
                except Exception as error:
                    if said or retried or cancelled.is_set() or not _dead_socket(error):
                        raise
                    retried = True
                    logger.info('echo-sync fast_text reconnect reason=%s', reason_of(error))
                    old, client = client, None
                    self._use(old, -1)
                    self._renew(old)
                finally:
                    if client is not None:
                        self._use(client, -1)
        finally:
            with self._state:
                self._active -= 1
            if sent and cancelled.is_set():
                self._rewarm()

    def _once(self, client, headers, request, cancelled):
        with contextlib.ExitStack() as stack:
            response = stack.enter_context(client.stream('POST', self.url, headers=headers, json=wire(request), timeout=self.first_text_s))
            if response.status_code != 200:
                if response.status_code in (401, 403):
                    self._signed = None
                raise FastTextError(f'http_{response.status_code}')
            lines = response.iter_lines()
            for line in lines:
                if cancelled.is_set():
                    return                # the ``with`` closes this response and nothing else
                if not line.startswith('data:'):
                    continue
                payload = line[5:].strip()
                if not payload or payload == '[DONE]':
                    continue
                try:
                    event = json.loads(payload)
                except ValueError:
                    continue
                kind = event.get('type') if isinstance(event, dict) else None
                if kind == 'response.output_text.delta':
                    delta = event.get('delta')
                    if isinstance(delta, str) and delta:
                        yield delta
                elif kind == 'response.completed':
                    self._read_off(stack.pop_all(), lines)
                    spent = _usage(event)
                    if spent:
                        yield {'usage': spent}
                    return
                elif kind in ('response.failed', 'response.incomplete', 'error'):        # a cut or refused answer is no finished one
                    raise FastTextError(failed_token(event, kind))
            if not cancelled.is_set():
                raise FastTextError('no_terminal_event')        # the lines ran out without response.completed: the answer may be cut anywhere

    @staticmethod
    def _read_off(pending, lines):
        """The job is over; the rest of its body (the empty line and the end, nothing wanted) is read off in a thread, for ``DRAIN_S`` at most, and the response then closed, so that its connection goes back to the pool. Whatever goes wrong
        there, the close included, is nothing to the job: the connection is simply made again."""
        def read():
            end = time.monotonic() + DRAIN_S
            with contextlib.suppress(Exception), pending:
                for _ in lines:
                    if time.monotonic() > end:
                        break
        threading.Thread(target=read, name='echo-fast-text-drain', daemon=True).start()

    # -- the connection kept warm ---------------------------------------------------------------------------------------------------
    def ping(self):
        """One light request (``ping_url``) on the call's client: True when the host answered with anything. Skipped while a job is in flight (its own traffic keeps the connection) and after ``close``. A connection that does not
        answer (dead, or silent: the next job would sit 4 s on it) costs the client: it is let go and one try is made on a new one, unless a job began meanwhile (``_renew``; the next ping looks again). No network failure raises."""
        with self._state:
            if self._closed or self._active:
                return False
        for _ in range(2):
            client = None
            try:
                client = self._client()
                client.get(self.ping_url, headers={'User-Agent': USER_AGENT}, timeout=PING_TIMEOUT_S)
                return True
            except Exception as error:     # noqa: BLE001 - a ping is never anybody's failure
                logger.debug('echo-sync fast_text ping failed reason=%s', reason_of(error))
                if self._closed or (client is not None and not self._renew(client, idle=True)):
                    return False
        return False

    def _rewarm(self):
        with self._state:
            if self._closed or self._rewarming:
                return
            self._rewarming = True

        def run():
            try:
                self.ping()
            finally:
                self._rewarming = False
        threading.Thread(target=run, name='echo-fast-text-rewarm', daemon=True).start()

    def prepare(self):
        """T1 item 2, in the calling thread: the sign-in read, the client made, the TLS done (the first ping). Each is tried whatever the other did; True when both worked. A failure is silent (the log has the numbers and the type) and
        the first job goes as it would have. Never raises."""
        started, signed, reason = time.monotonic(), False, '-'
        try:
            self._sign_in()
            signed = True
        except Exception as error:         # noqa: BLE001 - the first job reads it again
            reason = reason_of(error)
        pinged = self.ping()
        logger.info('echo-sync fast_text warm ok=%s signed=%s pinged=%s ms=%s reason=%s', int(signed and pinged), int(signed), int(pinged), round((time.monotonic() - started) * 1000), reason)
        return signed and pinged

    def warm(self):
        """The call opened: ``prepare`` and then a ping every ``ping_s`` until ``close``, in ONE daemon thread. Returns at once, once."""
        with self._state:
            if self._closed or self._thread is not None:
                return
            self._thread = threading.Thread(target=self._keep_warm, name='echo-fast-text-keepalive', daemon=True)
        self._thread.start()

    def _keep_warm(self):
        with contextlib.suppress(Exception):      # nothing of this reaches anybody, and one tick that fails is not the end of the keep-alive
            self.prepare()
        while not self._stop.wait(self.ping_s):
            with contextlib.suppress(Exception):
                self.ping()

    def close(self):
        """With the call: the client is closed (in a thread), the pings stop, nothing is served or made after it. Twice is harmless."""
        with self._state:
            self._closed = True
            http, self._http = self._http, None
        self._stop.set()
        if http is not None:
            threading.Thread(target=_close_quietly, args=(http,), name='echo-fast-text-close', daemon=True).start()


def codex_stream(credentials, *, client_factory=None, url=FAST_URL, ping_s=PING_S):
    """The transport of ONE call (``CodexTransport``): ``stream(request, cancelled)`` is the streaming call, ``stream.warm()`` / ``stream.close()`` the call's opening and end."""
    return CodexTransport(credentials, client_factory=client_factory, url=url, ping_s=ping_s)


def wire(request):
    """The body of a call on this road: the job's request with the fixed model, effort and the flags of a stream that is not stored. No tools, no delegation."""
    return {'model': FAST_MODEL, 'stream': True, 'store': False, 'reasoning': {'effort': FAST_EFFORT}, **request}


def primary(resolved, credentials):
    """The first road of a call by the profile (``settings.resolve``): the socket (``text_transport: "ws"``, HTTP behind it; warmed with the BRAIN the jobs send) or HTTP; None without a sign-in."""
    if credentials is None:
        return None
    if resolved['text_transport'] == 'ws':      # W12 (E59.1): the socket, HTTP behind it (ws_transport.py); f2-model: warmed with the BRAIN the jobs send, one socket kept ready beside a job
        primed = _optional('brain_short', lambda: __import__(__package__ + '.brain_short', fromlist=['SHORT_POLICY']).SHORT_POLICY) if resolved['brain_short'] == 'on' else None
        stream = _optional('ws_transport', lambda: __import__(__package__ + '.ws_transport', fromlist=['ws_stream']).ws_stream(credentials, instructions=primed or BRAIN_POLICY, ready=WS_READY))
        if stream is not None:
            return stream
    return codex_stream(credentials)
