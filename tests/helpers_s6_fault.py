"""Fault-injection rig for the S6 "fault" axis. Tests only: no production code is changed or copied.

The code under test is the REAL production chain
    ControlledMedia (+ EchoEngine + SQLite)  ->  NativeMediaSocket  ->  controlled_host.serve
and fakes exist only at the external boundary:

* the clock: a virtual-time event loop, so a 15 s synthesis timeout costs microseconds and
  "audible within 20 s" can be asserted exactly;
* the SAPI synthesis (``synthesize(text)`` for the wire, ``worker.synthesize(text, path)`` for the host);
* the lookup (``lookup(question)`` for the wire, ``api._echo_quick_lookup_module().search`` for the host);
* the GPT-Live helper pipe (``bridge.receive/send``) and the websocket to the phone.

Nothing here decides what is correct: the oracles only report what the wire emitted and when.
"""
import asyncio
import base64
import contextlib
import functools
import json
import logging
import types
from pathlib import Path

from cm_patch import patch_controller
from helpers_live_line import LiveLine
from echo_sync import controlled_host, controlled_media, native_media_socket
from echo_sync.controlled_media import ControlledMedia
from echo_sync.native_media_socket import NativeMediaSocket

# Keywords of the ControlledMedia(...) call in controlled_host.serve (a test pins them with ast).
HOST_KWARGS = dict(source_delivery='delegation', session_context_fallback=True, lookup_policy='required',
                   first_useful_gate=True, coalesce_seconds=3.2, quiet_reopen=True)

PCM_BYTES_PER_SECOND = 48000          # 24 kHz, 16-bit, mono: what NativeMediaSocket paces
FRAME_BYTES = 960                     # one 20 ms paced frame


# ----------------------------------------------------------------------------------------------
# virtual time
# ----------------------------------------------------------------------------------------------

class VirtualClockDeadlock(AssertionError):
    """Nothing is scheduled, nothing is runnable and no worker thread is running: a real hang."""


class VirtualLoop(asyncio.SelectorEventLoop):
    """A selector loop whose clock jumps to the next timer whenever it would otherwise sleep.

    I/O (the self-pipe that a finished ``asyncio.to_thread`` job writes to) is still polled for real.
    While a thread job is in flight the clock stands still, so a job that needs a few real
    milliseconds can never be "timed out" by the jump.
    """

    START = 1000.0

    def __init__(self):
        super().__init__()
        self._vnow = self.START
        self._inflight = 0
        self._stalls = 0
        real_select = self._selector.select
        loop = self

        def select(timeout=None):
            if loop._inflight:
                return real_select(0.002)
            ready = real_select(0)
            if ready:
                loop._stalls = 0
                return ready
            if timeout is None:
                loop._stalls += 1
                if loop._stalls > 60:
                    raise VirtualClockDeadlock('no timer, no ready callback, no worker thread: the system hangs')
                return real_select(0.001)
            loop._stalls = 0
            if timeout > 0:
                loop._vnow += timeout
            return ready

        self._selector.select = select

    def time(self):
        return self._vnow

    def run_in_executor(self, executor, func, *args):
        self._inflight += 1
        future = super().run_in_executor(executor, func, *args)
        future.add_done_callback(self._job_done)
        return future

    def _job_done(self, _future):
        self._inflight -= 1

    async def shutdown_default_executor(self, timeout=None):
        # The stock version waits on a helper thread under a 300 s *loop* timeout: with a clock that jumps
        # it would "expire" at once. Worker jobs here are milliseconds long, so joining them is enough.
        executor, self._default_executor = self._default_executor, None
        if executor is not None:
            executor.shutdown(wait=True)


def run(coro_factory):
    """Run ``coro_factory()`` on a fresh VirtualLoop. Returns what the coroutine returns.

    A failure is carried out of the loop as a value and raised here, so that its traceback holds only the
    frames of the scenario (pytest formats every frame of every expected failure: asyncio's own would cost
    seconds per xfail)."""
    __tracebackhide__ = True

    async def guarded():
        __tracebackhide__ = True
        try:
            return 'ok', await coro_factory()
        except Exception as error:
            return 'error', error

    with asyncio.Runner(loop_factory=VirtualLoop) as runner:
        outcome, value = runner.run(guarded())
    if outcome == 'error':
        raise value
    return value


def patch_clock(monkeypatch):
    """Make the three production modules that read ``time.monotonic()`` use the running virtual loop."""
    shim = types.SimpleNamespace(monotonic=lambda: asyncio.get_running_loop().time())
    patch_controller(monkeypatch, 'time', shim)      # controlled_media and every cm_* module that binds ``time``
    for module in (native_media_socket, controlled_host):
        monkeypatch.setattr(module, 'time', shim)


# ----------------------------------------------------------------------------------------------
# provider events (the GPT-Live wire as ControlledMedia.provider sees it)
# ----------------------------------------------------------------------------------------------

def created(tid, role, text='', start=None):
    turn = {'id': tid, 'role': role, 'transcript': text}
    if start is not None:
        turn.update(start_ms=start, end_ms=start + 100)
    return {'type': 'turn.created', 'turn': turn}


def delta(tid, text, n):
    return {'type': 'turn.delta', 'turn_id': tid, 'delta': text, 'start_ms': n * 40, 'end_ms': n * 40 + 39}


def done(tid, role, text, start=None):
    turn = {'id': tid, 'role': role, 'transcript': text}
    if start is not None:
        turn.update(start_ms=start, end_ms=start + 1000)
    return {'type': 'turn.done', 'turn': turn}


def delegation(did, uid):
    return {'type': 'delegation.created', 'item': {'id': did, 'type': 'delegation', 'target': 'client',
                                                   'user_bidi_turn_id': uid, 'content': []}}


SOURCES = [{'url': 'https://example.org/primary', 'text': 'Первичный источник: норма и дата вступления.'}]

# A question the router sends to a lookup (an article of a code) and one it answers from model knowledge.
LOOKUP_QUESTION = 'Что устанавливает статья 218 ГК РФ?'
LOOKUP_ANSWER = 'Статья 218 устанавливает основания приобретения права собственности.'
DIRECT_QUESTION = 'Что такое инерция?'
DIRECT_ANSWER = 'Инерция — это свойство тела сохранять своё состояние покоя или равномерного движения.'
OTHER_DIRECT_QUESTION = 'Что такое фотосинтез?'
OTHER_DIRECT_ANSWER = 'Фотосинтез — это процесс образования органических веществ из углекислого газа и воды на свету.'


# ----------------------------------------------------------------------------------------------
# injected faults (named exceptions so a log line can be matched to its cause)
# ----------------------------------------------------------------------------------------------

class PreconditionFailed(Exception):
    """The scenario did not reach the state it needs. Deliberately NOT an AssertionError, so that an
    ``xfail(raises=AssertionError)`` defect marker can never hide a broken rig as 'the known defect'."""


def precondition(condition, message):
    __tracebackhide__ = True
    if not condition:
        raise PreconditionFailed(message)


class InjectedFault(Exception):
    """Raised by a fake boundary. Its class name is what a log line must be able to show."""


class InjectedSapiFault(InjectedFault):
    pass


class InjectedLookupFault(InjectedFault):
    pass


class InjectedSegmentationFault(InjectedFault):
    pass


def pcm(seconds=0.1):
    """Valid synthesized PCM: even byte count, whole 20 ms frames."""
    frames = max(1, round(seconds / 0.02))
    return b'\x01\x02' * (FRAME_BYTES // 2) * frames


class Plan:
    """A scripted sequence of outcomes for a fake boundary; the last one repeats."""

    def __init__(self, *steps, now=None):
        self.steps = list(steps) or ['ok']
        self.calls = []                      # (virtual time, argument)
        self.now = now                       # set by the rig; a worker thread has no running loop

    def next(self, argument):
        self.calls.append((self.now() if self.now else 0.0, argument))
        index = min(len(self.calls) - 1, len(self.steps) - 1)
        return self.steps[index]


def synthesis(plan):
    """``synthesize(text)`` for NativeMediaSocket: the SAPI boundary."""
    async def synthesize(text, end=None):
        step = plan.next(text)
        if step == 'ok':
            return pcm(0.1)
        if step == 'raise':
            raise InjectedSapiFault('worker_timeout')
        if step == 'empty':
            return b''
        if step == 'odd':
            return b'\x01\x02\x03'
        if step == 'none':
            return None
        if step == 'str':
            return 'not audio'
        if step == 'hang':
            await asyncio.Event().wait()
        if isinstance(step, tuple) and step[0] == 'slow':
            await asyncio.sleep(step[1])
            return pcm(0.1)
        if isinstance(step, BaseException):
            raise step
        raise AssertionError(f'unknown synthesis step {step!r}')
    return synthesize


def sources_for(question):
    """Public sources whose text names the question they were fetched for (a stale delivery is recognisable)."""
    return [{'url': 'https://example.org/primary', 'text': 'Первичный источник по запросу: ' + question}]


def lookup_fake(plan):
    """``lookup(question)`` for NativeMediaSocket: the retrieval boundary."""
    async def lookup(question):
        step = plan.next(question)
        if step == 'ok':
            return sources_for(question)
        if step == 'raise':
            raise InjectedLookupFault('private question text and token must not leak: ' + question)
        if step == 'empty':
            return []
        if step == 'none':
            return None
        if step == 'garbage':
            return [None, 'x', 7, {'url': 'file:///C:/secret', 'text': 'bad'}]
        if step == 'hang':
            await asyncio.Event().wait()
        if isinstance(step, tuple) and step[0] == 'slow':
            await asyncio.sleep(step[1])
            return sources_for(question)
        raise AssertionError(f'unknown lookup step {step!r}')
    return lookup


# ----------------------------------------------------------------------------------------------
# the wire rig
# ----------------------------------------------------------------------------------------------

class Frame:
    __slots__ = ('t', 'data')

    def __init__(self, t, data):
        self.t, self.data = t, data

    @property
    def type(self):
        return self.data.get('type')

    def __repr__(self):
        return f'<{self.t - VirtualLoop.START:7.2f}s {self.data}>'


class FakeSource:
    """What ``connect()`` returns: the GPT-Live helper pipe seen from NativeMediaSocket."""

    def __init__(self):
        self.frames = []
        self.closed = False

    async def send(self, kind, payload=b''):
        self.frames.append((kind, payload))

    async def close(self):
        self.closed = True


class WireRig:
    """NativeMediaSocket + the real ControlledMedia, driven exactly like controlled_host.serve drives them.

    ``serve`` creates the wire, starts the 0.1 s ticker, and feeds helper events to ``wire.provider``;
    this rig does the same, with the websocket replaced by ``self.frames``.
    """

    def __init__(self, tmp_path, *, synth=None, lookup=None, session_id='s6-fault', settings=None,
                 emit_fault=None, controller_kwargs=None, db='controlled-state.sqlite3', prefetch=False):
        self.tmp_path = Path(tmp_path)
        self.prefetch = prefetch
        self.frames = []
        self.emit_fault = emit_fault              # callable(frame_dict) -> exception to raise, or None
        self.synth_plan = synth if isinstance(synth, Plan) else Plan(*(synth or ['ok']))
        self.lookup_plan = lookup if isinstance(lookup, Plan) else Plan(*(lookup or ['ok']))
        self.loop = asyncio.get_running_loop()
        self.synth_plan.now = self.lookup_plan.now = self.loop.time
        self.session_id, self.db = session_id, db
        self.controller_kwargs = dict(HOST_KWARGS)
        self.controller_kwargs.update(controller_kwargs or {})
        if settings is not None:
            self.controller_kwargs['settings'] = settings
        self.ticker = None
        self.t0 = self.loop.time()
        self._turns = 0
        self.connections = 0
        self._connect_new()

    def _connect_new(self):
        """A new connection to the same session: new ControlledMedia + NativeMediaSocket on the same SQLite file."""
        self.connections += 1
        self.controller = ControlledMedia(self.tmp_path / self.db, session_id=self.session_id, clock=self.loop.time,
                                          **self.controller_kwargs)
        self.source = FakeSource()
        LiveLine(self.controller, self.loop.time()).attach()      # the phone streams its microphone all call long (a28a571d); the meter of the input is not relaxed
        self.wire = NativeMediaSocket(self.controller, self._emit, self._connect, lookup_fake(self.lookup_plan),
                                      synthesis(self.synth_plan), diagnostics=False, prefetch=self.prefetch, clock=self.loop.time)
        self.wire.ready = True
        self.wire.source = self.source

    def _start_ticker(self):
        wire = self.wire

        async def tick():                          # controlled_host.serve.tick, verbatim
            while not wire.closed:
                await asyncio.sleep(.1)
                await wire.tick()
        self.ticker = asyncio.create_task(tick())

    async def reconnect(self):
        """Drop the connection (helper lost) and reconnect: a fresh controller over the persisted session."""
        await self.wire.close()
        self.ticker.cancel()
        await asyncio.gather(self.ticker, return_exceptions=True)
        self._connect_new()
        self._start_ticker()

    # --- the websocket side -------------------------------------------------------------------
    async def _emit(self, frame):
        if self.emit_fault is not None:
            error = self.emit_fault(frame)
            if error is not None:
                raise error
        self.frames.append(Frame(self.loop.time(), frame))

    async def _connect(self):
        return self.source

    # --- lifecycle ----------------------------------------------------------------------------
    async def __aenter__(self):
        self._start_ticker()
        return self

    async def __aexit__(self, *exc):
        with contextlib.suppress(Exception):
            await self.wire.close()
        self.ticker.cancel()
        await asyncio.gather(self.ticker, return_exceptions=True)

    # --- driving ------------------------------------------------------------------------------
    def now(self):
        return self.loop.time()

    async def advance(self, seconds):
        await asyncio.sleep(seconds)

    def next_id(self, prefix):
        self._turns += 1
        return f'{prefix}{self._turns}'

    async def feed(self, event):
        await self.wire.provider(event)

    async def ask(self, text, tid=None, *, delegate=False):
        """A user question: created with the first word, then provider-final with the whole text."""
        tid = tid or self.next_id('u')
        words = text.split(' ', 1)
        await self.feed(created(tid, 'user', words[0]))
        await self.feed(done(tid, 'user', text))
        if delegate:
            await self.feed(delegation('d-' + tid, tid))
        return tid

    async def answer(self, text, tid=None, *, parts=3):
        """An assistant answer delivered as created + deltas + done, like the cloud streams it."""
        tid = tid or self.next_id('a')
        pieces = [text[i:i + max(1, len(text) // parts)] for i in range(0, len(text), max(1, len(text) // parts))]
        await self.feed(created(tid, 'assistant', pieces[0]))
        for n, piece in enumerate(pieces[1:], 1):
            await self.feed(delta(tid, piece, n))
        await self.feed(done(tid, 'assistant', text))
        return tid

    async def answer_words(self, text, tid=None, pause=0.05):
        """Stream the answer word by word (created, one delta per word, done): reaches the incremental paths."""
        tid = tid or self.next_id('a')
        words = text.split(' ')
        await self.feed(created(tid, 'assistant', words[0]))
        for n, word in enumerate(words[1:], 1):
            await self.feed(delta(tid, ' ' + word, n))
            await self.advance(pause)
        await self.feed(done(tid, 'assistant', text))
        return tid

    async def hear(self, text, tid=None):
        """A user utterance that is not a question (a repeat attempt, «повтори», «стоп»)."""
        tid = tid or self.next_id('h')
        await self.feed(done(tid, 'user', text))
        return tid

    def current_portion(self):
        state = self.controller.state() or {}
        chunks, index = state.get('chunks') or [], state.get('chunk_index', 0)
        return chunks[index] if not state.get('completed') and 0 <= index < len(chunks) else None

    async def repeat_current(self):
        """The user repeats the portion they are waiting for, word for word."""
        portion = self.current_portion()
        assert portion is not None, 'no portion is waiting for a repeat'
        await self.hear(portion)
        return portion

    async def ask_direct(self, question=DIRECT_QUESTION, answer=DIRECT_ANSWER):
        await self.ask(question)
        return await self.answer(answer)

    async def ask_with_lookup(self, question=LOOKUP_QUESTION, answer=LOOKUP_ANSWER):
        await self.ask(question)
        await self.advance(0.2)                   # the lookup task runs, grounding, context is sent to the helper
        return await self.answer(answer)

    # --- reading what the phone got ---------------------------------------------------------------
    def of_type(self, kind, since=None):
        since = self.t0 if since is None else since
        return [f for f in self.frames if f.type == kind and f.t >= since]

    def audio(self, since=None):
        return [f for f in self.of_type('response.audio.delta', since) if f.data.get('delta')]

    def spoken(self, since=None):
        """The text of every cue/diagnostic that was started on the wire (response.audio_transcript.delta)."""
        return [f.data['delta'] for f in self.of_type('response.audio_transcript.delta', since)]

    def errors(self, since=None):
        return [f.data['error']['code'] for f in self.of_type('error', since)]

    def completed(self, since=None):
        """Spoken responses that reached the phone whole (response.done after a paced PCM stream)."""
        return [f for f in self.of_type('response.done', since) if f.data.get('response', {}).get('status') == 'completed']

    def first_audio_after(self, t):
        for frame in self.completed(since=t):
            return frame
        return None

    def timeline(self):
        return [f'{f.t - self.t0:6.2f}s {f.type} ' + (f.data.get("error", {}).get("code", "") if f.type == "error" else
                (f.data.get("delta", "")[:40] if f.type == "response.audio_transcript.delta" else ""))
                for f in self.frames if f.type != 'response.audio.delta']


def audible_report(rig, since, within):
    """(is_audible, description): did a whole spoken response reach the phone within ``within`` s of ``since``?"""
    deadline = since + within
    frame = rig.first_audio_after(since)
    if frame is not None and frame.t <= deadline:
        return True, f'audible at +{frame.t - since:.2f}s'
    seen = rig.errors(since)
    return False, (f'nothing audible within {within:.0f}s of the trigger; error frames sent instead: {seen}; '
                   f'timeline: {rig.timeline()[-8:]}')


# ----------------------------------------------------------------------------------------------
# logging oracle
# ----------------------------------------------------------------------------------------------

class LogCatcher(logging.Handler):
    """Collects every record of every logger (also the host's ``api.logger`` when it is a logging.Logger)."""

    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.records = []

    def emit(self, record):
        self.records.append(record)

    def text(self, minimum=logging.WARNING):
        lines = []
        for record in self.records:
            if record.levelno >= minimum:
                lines.append(record.getMessage())
                if record.exc_info and record.exc_info[0]:
                    lines.append(record.exc_info[0].__name__)
        return '\n'.join(lines)


@contextlib.contextmanager
def capture_logs():
    catcher = LogCatcher()
    root = logging.getLogger()
    previous = root.level
    root.addHandler(catcher)
    root.setLevel(logging.DEBUG)
    try:
        yield catcher
    finally:
        root.removeHandler(catcher)
        root.setLevel(previous)


# ----------------------------------------------------------------------------------------------
# the host rig: controlled_host.serve with a fake phone, fake cloud helper, fake SAPI worker, fake lookup
# ----------------------------------------------------------------------------------------------

class WSClosed(Exception):
    """What the websocket raises once the connection is gone (Starlette raises WebSocketDisconnect)."""


class FakeWS:
    """The phone's websocket as ``serve`` uses it: query_params, receive_text, send_text, close."""

    def __init__(self, loop, query=None):
        self.loop = loop
        self.query_params = dict(query or {})
        self.inbox = asyncio.Queue()
        self.frames = []                      # Frame(t, parsed json) of everything sent to the phone
        self.close_code = None
        self.send_fault = None                # callable(frame_dict) -> exception to raise, or None
        self.send_attempts = 0

    async def receive_text(self):
        item = await self.inbox.get()
        if isinstance(item, BaseException):
            raise item
        return item

    async def send_text(self, text):
        self.send_attempts += 1
        if self.close_code is not None:
            raise WSClosed('send after close')
        frame = json.loads(text)
        if self.send_fault is not None:
            error = self.send_fault(frame)
            if error is not None:
                raise error
        self.frames.append(Frame(self.loop.time(), frame))

    async def close(self, code=1000):
        self.close_code = code
        self.inbox.put_nowait(WSClosed(f'closed by the server with {code}'))

    def push(self, event):
        self.inbox.put_nowait(event if isinstance(event, str) else json.dumps(event, ensure_ascii=False))


class FakeBridge:
    """The Conduit Watch helper pipe: ``start/send/receive/close`` like ThreadedHelperBridge.

    ``receive`` returns ``(kind, payload)``, ``None`` at EOF, raises ``asyncio.TimeoutError`` when idle
    and ``ValueError`` on a corrupt pipe: the contract of helper_bridge.read_frame.
    """

    def __init__(self, owner, *args, **kwargs):
        self.owner = owner
        self.inbox = asyncio.Queue()
        self.sent = []
        self.closed = False
        self.close_fault = None
        self.send_fault = None
        self.process = types.SimpleNamespace(returncode=None)
        owner.bridges.append(self)

    async def start(self):
        if self.owner.start_fault:
            raise self.owner.start_fault

    async def send(self, kind, payload=b''):
        if self.send_fault is not None:
            raise self.send_fault
        self.sent.append((kind, payload))
        script = self.owner.setup_script
        if kind == 'C' and 'no_offer' not in script:
            self.inbox.put_nowait(('O', b'v=0\n'))
        if kind == 'A':
            if 'closed_before_ready' in script:
                self.inbox.put_nowait(('X', b''))
            elif 'refused' in script:
                self.inbox.put_nowait(('e', json.dumps({'type': 'error'}).encode()))
            elif 'never_ready' not in script:
                self.inbox.put_nowait(('R', b''))
                self.inbox.put_nowait(('e', json.dumps({'type': 'session.started'}).encode()))

    async def receive(self, timeout=30):
        item = await asyncio.wait_for(self.inbox.get(), timeout)
        if isinstance(item, BaseException):
            raise item
        return item

    async def close(self):
        self.closed = True
        self.process.returncode = 0
        if self.close_fault is not None:
            raise self.close_fault

    def push(self, kind, payload):
        self.inbox.put_nowait((kind, payload))

    def push_event(self, event):
        self.push('e', json.dumps(event, ensure_ascii=False).encode('utf-8'))


def write_wav(path, seconds=0.1, *, rate=24000, channels=1, width=2, frames=None):
    import wave
    count = round(seconds * rate) if frames is None else frames
    with wave.open(str(path), 'wb') as target:
        target.setframerate(rate)
        target.setnchannels(channels)
        target.setsampwidth(width)
        target.writeframes(b'\x01\x02' * (count * channels * width // 2))


class FakeWorker:
    """profile_sapi_worker(home): the persistent SAPI process. ``synthesize`` runs on a worker thread."""

    def __init__(self, plan, warm_failures=0):
        self.plan = plan
        self.warms = 0
        self.releases = 0
        self.pins = 0                            # keep_resident(): the resident worker repairs itself in its own supervisor
        self.warm_failures = warm_failures      # the first N warm-ups raise

    def synthesize(self, text, path, end=None):
        step = self.plan.next(text)
        if step == 'ok':
            write_wav(path)
        elif isinstance(step, tuple) and step[0] == 'long':
            write_wav(path, seconds=step[1])
        elif step == 'raise':
            raise InjectedSapiFault('worker_timeout')
        elif step == 'empty':
            write_wav(path, frames=0)
        elif step == 'rate':
            write_wav(path, rate=22050)
        elif step == 'stereo':
            write_wav(path, channels=2)
        elif step == 'missing':
            pass
        elif step == 'garbage':
            Path(path).write_bytes(b'RIFFnot a wave file')
        elif isinstance(step, BaseException):
            raise step
        else:
            raise AssertionError(f'unknown worker step {step!r}')
        return str(path)

    def warm(self):
        self.warms += 1
        if self.warm_failures > 0:
            self.warm_failures -= 1
            raise InjectedSapiFault('worker_start_failed')

    def keep_resident(self):
        self.pins += 1

    def release(self):
        self.releases += 1


class FakeSearchModule:
    """``api._echo_quick_lookup_module()``: the Hermes quick-lookup that ``serve.lookup`` calls."""

    def __init__(self, plan):
        self.plan = plan

    def search(self, question, limit, home, timeout=None, force_refresh=False):
        step = self.plan.next(question)
        if step == 'ok':
            return {'success': True, 'data': {'web': sources_for(question)}}
        if step == 'raise':
            raise InjectedLookupFault('private question text must not leak: ' + question)
        if step == 'failed':
            return {'success': False, 'error': 'provider quota'}
        if step == 'empty':
            return {'success': True, 'data': {'web': []}}
        if step == 'no_data':
            return {'success': True, 'data': None}
        if step == 'not_a_dict':
            return ['unexpected']
        raise AssertionError(f'unknown search step {step!r}')


class RecordingLogger:
    """``api.logger`` of the host."""

    def __init__(self):
        self.lines = []

    def _add(self, level, message, args):
        try:
            text = message % args if args else message
        except Exception:
            text = f'{message} {args}'
        self.lines.append((level, text))

    def info(self, message, *args, **kwargs):
        self._add(logging.INFO, message, args)

    def warning(self, message, *args, **kwargs):
        self._add(logging.WARNING, message, args)

    def error(self, message, *args, **kwargs):
        self._add(logging.ERROR, message, args)

    def exception(self, message, *args, **kwargs):
        self._add(logging.ERROR, message, args)

    def text(self, minimum=logging.WARNING):
        return '\n'.join(text for level, text in self.lines if level >= minimum)


class HostRig:
    """``controlled_host.serve`` driven end to end by a fake phone, a fake helper pipe and fake SAPI/lookup."""

    def __init__(self, tmp_path, monkeypatch, *, synth=None, lookup=None, query=None, setup=(), warm_failures=0, mic_stream=True):
        loop = asyncio.get_running_loop()
        self.loop = loop
        self.mic_stream = mic_stream          # False: the test's own fake phone sends the microphone packets (as World.mic_stream = False)
        self.home = Path(tmp_path) / 'home'
        (self.home / 'echo-sync').mkdir(parents=True, exist_ok=True)
        self.ws = FakeWS(loop, query)
        self.bridges = []
        self.setup_script = set(setup)
        self.start_fault = None
        self.synth_plan = synth if isinstance(synth, Plan) else Plan(*(synth or ['ok']))
        self.lookup_plan = lookup if isinstance(lookup, Plan) else Plan(*(lookup or ['ok']))
        self.synth_plan.now = self.lookup_plan.now = loop.time
        self.worker = FakeWorker(self.synth_plan, warm_failures)
        self.logger = RecordingLogger()
        self.search_module = FakeSearchModule(self.lookup_plan)
        self.run_scoped_delay = 0.0
        self.api = self._make_api(tmp_path)
        monkeypatch.setattr(controlled_host, 'profile_sapi_worker', lambda home: self.worker)
        real_open = controlled_host.open_subscription
        monkeypatch.setattr(controlled_host, 'open_subscription', functools.partial(
            real_open, bridge_factory=lambda *a, **k: FakeBridge(self, *a, **k)))
        real_init = ControlledMedia.__init__

        def live_init(controller, *args, **kwargs):      # serve builds the controller itself: the phone streams its microphone all call long (a28a571d)
            real_init(controller, *args, **kwargs)
            if self.mic_stream:
                LiveLine(controller, controller.clock()).attach()

        monkeypatch.setattr(ControlledMedia, '__init__', live_init)
        self.served = None                    # asyncio.Task running serve()
        self.outcome = None                   # None while serve runs; 'returned' or the exception it raised
        self.t0 = loop.time()

    def _make_api(self, tmp_path):
        rig = self

        async def run_scoped(profile, fn, executor=None):
            if rig.run_scoped_delay:
                await asyncio.sleep(rig.run_scoped_delay)
            return fn()

        return types.SimpleNamespace(
            __file__=str(Path(tmp_path) / 'api' / 'gpt_live_api.py'),
            WATCH_AUDIO_STUN=('stun:example.test:19302',), WATCH_AUDIO_CONNECT_TIMEOUT_S=5,
            logger=self.logger, _search_executor=None,
            _watch_audio_runtime=types.SimpleNamespace(python=lambda: ('python', {}, (), '')),
            _run_scoped=run_scoped, _limiter_key=lambda profile: 'limiter',
            _gpt_live_settings=lambda: {},
            create_gpt_live_session=lambda *a, **k: {'auth': 'subscription', 'transport': {'sdp': 'answer-sdp'}},
            _echo_quick_lookup_module=lambda: self.search_module)

    # --- lifecycle ----------------------------------------------------------------------------
    async def __aenter__(self):
        async def run():
            try:
                await controlled_host.serve(self.ws, api=self.api, profile='echo-sync', home=self.home)
                self.outcome = 'returned'
            except BaseException as error:        # the host's caller would see this
                self.outcome = error
        self.served = asyncio.create_task(run())
        return self

    async def __aexit__(self, *exc):
        self.ws.inbox.put_nowait(WSClosed('test teardown'))
        try:
            await asyncio.wait_for(asyncio.shield(self.served), 120)
        except BaseException:
            self.served.cancel()
            await asyncio.gather(self.served, return_exceptions=True)

    @property
    def finished(self):
        return self.outcome is not None

    @property
    def bridge(self):
        return self.bridges[-1] if self.bridges else None

    def now(self):
        return self.loop.time()

    async def advance(self, seconds):
        await asyncio.sleep(seconds)

    async def until(self, predicate, within, step=0.05):
        end = self.loop.time() + within
        while self.loop.time() < end:
            if predicate():
                return True
            await asyncio.sleep(step)
        return predicate()

    # --- phone side ---------------------------------------------------------------------------
    def frames(self, kind=None, since=None):
        since = self.t0 if since is None else since
        return [f for f in self.ws.frames if f.t >= since and (kind is None or f.type == kind)]

    def audio(self, since=None):
        return [f for f in self.frames('response.audio.delta', since) if f.data.get('delta')]

    def spoken(self, since=None):
        return [f.data['delta'] for f in self.frames('response.audio_transcript.delta', since)]

    def errors(self, since=None):
        return [f.data['error']['code'] for f in self.frames('error', since)]

    async def handshake(self):
        """session.update -> upstream connect -> conduit-ready marker -> ready (what the Conduit app does)."""
        self.ws.push({'type': 'session.update', 'session': {}})
        assert await self.until(lambda: any(f.type == 'session.updated' for f in self.ws.frames), 120), self.ws.frames
        self.ws.push({'type': 'response.create', 'response': {
            'conversation': 'none', 'input': [{'content': [{'text': 'conduit-ready-s6'}]}]}})
        assert await self.until(lambda: any(f.type == 'conduit.turn' for f in self.ws.frames), 5)
        marker = next(f for f in self.ws.frames if f.type == 'conduit.turn')
        self.ws.push({'type': 'conduit.turn.done', 'turn_id': marker.data['turn_id']})
        assert await self.until(lambda: any(f.type == 'response.done' for f in self.ws.frames), 5)
        self.t0 = self.loop.time()
        self.ws.frames.clear()

    def phone_audio(self, n=1):
        for _ in range(n):
            self.ws.push({'type': 'input_audio_buffer.append', 'audio': base64.b64encode(b'\0' * 960).decode()})

    # --- cloud side (events relayed by the helper) --------------------------------------------------
    def cloud(self, event):
        self.bridge.push_event(event)

    async def ask(self, text, tid='u1'):
        self.cloud(created(tid, 'user', text.split(' ', 1)[0]))
        self.cloud(done(tid, 'user', text))
        await self.advance(0.3)

    async def answer(self, text, tid='a1', pieces=3):
        step = max(1, len(text) // pieces)
        chunks = [text[i:i + step] for i in range(0, len(text), step)]
        self.cloud(created(tid, 'assistant', chunks[0]))
        for n, chunk in enumerate(chunks[1:], 1):
            self.cloud(delta(tid, chunk, n))
        self.cloud(done(tid, 'assistant', text))
        await self.advance(0.3)
