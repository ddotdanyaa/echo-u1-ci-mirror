"""World and conversation model for the S6 state-axis tests (tests/test_s6_state_machine.py).

REAL, the same code as production:
  ControlledMedia, built with the keywords read from ``echo_sync/controlled_host.py`` itself;
  EchoEngine and its SQLite file; FramelessTurns; portioner; first_useful; ru_alignment;
  NativeMediaSocket (``provider``, ``tick``, ``actions``, ``_speak``): the code that turns controller
  actions into audio frames.
FAKE, only at the external boundary:
  the GPT-Live helper (``FakeSource``: records what the product sends upstream),
  SAPI synthesis (instant 20 ms PCM, optionally held open to build a race),
  the public lookup (instant rows),
  the websocket ``send`` (a recorder that classifies frames),
  and time: one injected clock, also patched in as ``native_media_socket.time.monotonic``.

The world never raises inside the emit callback (``NativeMediaSocket._speak`` would swallow it and turn it
into an error frame); it records wire-level violations and lets the caller read ``world.violations``.
"""
import ast
import asyncio
import base64
import copy
import json
import re
import shutil
import tempfile
import time as _time
import types
from dataclasses import dataclass, field
from pathlib import Path

import echo_sync
from echo_sync import native_media_socket as _nms
from echo_sync.classifier import QUESTION_WORDS, alternative_question
from echo_sync.controlled_media import ANSWER_WAIT_SECONDS, ControlledMedia
from echo_sync.diagnostics import PHRASES as DIAGNOSTIC_PHRASES
from echo_sync.native_media_socket import NativeMediaSocket
from echo_sync.settings import resolve as resolve_settings
from echo_sync.textutil import norm_words, normalize

_REAL_TIME, _REAL_ASYNCIO = _nms.time, _nms.asyncio     # restored by World.close(); one World at a time
START_TIME = 1000.0
FRAME = b'\x00\x00' * 480             # 960 bytes = one 20 ms frame of 24 kHz 16-bit mono, the unit the sender paces
PLAYOUT_FRAMES = 10                   # every portion is 200 ms of audio: long enough to be interrupted half way
SOURCE_ROWS = [{'url': 'https://example.org/reference', 'text': 'Reference excerpt for the fake lookup.'}]
DIAGNOSTIC_TEXTS = frozenset(DIAGNOSTIC_PHRASES.values())      # the spoken diagnostics (Wave 2 / Tasks 4 and D): a response, but never a portion


# --- the host configuration, read from production source, never copied -----------------------------------

def _profile_key(node):
    """``'repeat_seconds'`` for the node ``profile_settings['repeat_seconds']``, else None: a value the host takes from the PROFILE."""
    if (isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id == 'profile_settings'
            and isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str)):
        return node.slice.value
    return None


def host_kwargs():
    """Keywords of the single ``ControlledMedia(...)`` call in controlled_host.py (all but session_id).

    A keyword the host takes from the profile's settings (UX-trace: ``repeat_seconds=profile_settings['repeat_seconds']``) has the
    value of a profile with no settings file: the default of settings.DEFAULTS."""
    source = (Path(echo_sync.__file__).parent / 'controlled_host.py').read_text(encoding='utf-8')
    calls = [n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Call)
             and getattr(n.func, 'id', None) == 'ControlledMedia']
    assert len(calls) == 1, 'controlled_host.py must build ControlledMedia exactly once'
    result = {}
    for keyword in calls[0].keywords:
        if keyword.arg == 'session_id':
            continue
        if keyword.arg == 'settings' and isinstance(keyword.value, ast.Call) and getattr(keyword.value.func, 'id', None) == 'controller_settings':
            from echo_sync.controlled_host import controller_settings      # noqa: PLC0415 - ROOT-1: the host builds the controller's settings once, with this
            result['settings'] = controller_settings(resolve_settings(None))
            continue
        if _profile_key(keyword.value) is not None:
            result[keyword.arg] = resolve_settings(None)[_profile_key(keyword.value)]
            continue
        if isinstance(keyword.value, ast.Name):      # a constant of the one table of time (timer_policy: COALESCE_SECONDS ...), the host imports it by name
            from echo_sync import timer_policy      # noqa: PLC0415
            assert hasattr(timer_policy, keyword.value.id), f'host keyword {keyword.arg} reads {keyword.value.id}, which is not of timer_policy: update the world'
            result[keyword.arg] = getattr(timer_policy, keyword.value.id)
            continue
        assert isinstance(keyword.value, ast.Constant), f'host keyword {keyword.arg} is not a constant: update the world'
        result[keyword.arg] = keyword.value.value
    return result


# --- provider wire events (shapes of tests/fixtures/controlled_silent_inertia_20261101.json) --------------

def turn_created(tid, role, text=''):
    return {'type': 'turn.created', 'turn': {'id': tid, 'role': role, 'transcript': text}}


def turn_done(tid, role, text):
    return {'type': 'turn.done', 'turn': {'id': tid, 'role': role, 'transcript': text}}


def turn_delta(tid, text, n):
    return {'type': 'turn.delta', 'turn_id': tid, 'delta': text, 'start_ms': n * 40, 'end_ms': n * 40 + 39}


def describe(event):
    """One short line for a failure report."""
    kind = event.get('type')
    turn = event.get('turn') if isinstance(event.get('turn'), dict) else None
    if turn:
        return f"{kind} {turn.get('role')} {turn.get('id')} {turn.get('transcript', '')!r}"
    if kind == 'turn.delta':
        return f"{kind} {event.get('turn_id')} {event.get('delta')!r}"
    return str(event)[:120]


def norm(text):
    return normalize(text)


# --- fakes -------------------------------------------------------------------------------------------------

class FakeClock:
    def __init__(self, start=START_TIME):
        self.t = start

    def now(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


class VirtualAsyncio:
    """``asyncio`` as seen by native_media_socket: the paced sender's ``sleep`` advances the injected clock
    instead of waiting, so a 200 ms portion plays in no wall-clock time but still takes one loop turn per frame."""

    def __init__(self, clock):
        self._clock = clock

    def __getattr__(self, name):
        return getattr(asyncio, name)

    async def sleep(self, delay, result=None):
        if delay and delay > 0:
            self._clock.advance(delay)
        await asyncio.sleep(0)
        return result


class FakeSource:
    """What the product would send to the GPT-Live helper (``frames``, all of it). Each of them is a model-visible call, except a quiet
    note (also listed in ``notes``: a ``session.context.append`` on the ``commentary`` channel, CL2 ruling 5), which asks the model nothing."""

    def __init__(self):
        self.frames = []
        self.notes = []
        self.closed = False

    async def send(self, kind, payload=b''):
        self.frames.append((kind, payload))
        if kind == 'E':
            try:
                frame = json.loads(payload)
            except ValueError:
                frame = None
            if isinstance(frame, dict) and frame.get('type') == 'session.context.append' and frame.get('channel') == 'commentary':
                self.notes.append((kind, payload))

    async def close(self):
        self.closed = True


@dataclass
class Cue:
    """One audible response, as the phone would see it (response.created ... response.done / clear)."""
    rid: str
    seq: int
    t: float
    text: str = ''
    audio_frames: int = 0
    done: bool = False
    cleared: bool = False
    replaced: bool = False
    diagnostic: bool = False     # a spoken diagnostic of the wire, not a portion of an answer
    snap: dict = field(default_factory=dict)


class World:
    wire_cls = NativeMediaSocket
    wire_kw = {}      # c22-nocloud: extra keywords of the wire (``local_fallback``), set by a subclass

    def __init__(self, root=None, *, session_id='s6-state'):
        self._own_root = root is None
        self.root = Path(tempfile.mkdtemp(prefix='s6state-') if root is None else root)
        self.db = self.root / 'controlled-state.sqlite3'
        self.session_id = session_id
        self.loop = asyncio.new_event_loop()
        self.loop_errors = []
        self.loop.set_exception_handler(lambda loop, context: self.loop_errors.append(context))
        self.clock = FakeClock()
        patched = {name: getattr(_time, name) for name in dir(_time) if not name.startswith('_')}
        patched['monotonic'] = self.clock.now
        _nms.time = types.SimpleNamespace(**patched)
        _nms.asyncio = VirtualAsyncio(self.clock)
        self.log = []                       # human-readable trail of everything the world did
        self.frames = []                    # (seq, time, frame) in emission order, across connections
        self.cues = []                      # every Cue ever emitted, in order
        self.violations = []
        self.errors = []                    # {'type': 'error'} frames sent to the phone
        self.seq = 0
        self.open = None                    # the Cue whose response is created but not done/cleared
        self.synth_calls = []
        self.lookup_calls = []
        self.hold = False
        self.gate = None
        self.connections = 0
        self.version = 0                    # bumped by everything that can change the controller's state
        self.controller = self.wire = self.source = None
        self.connect_peer()

    # -- connection life cycle ------------------------------------------------------------------------------

    def connect_peer(self):
        """A new call: new controller object (new nonce) over the SAME SQLite file, new wire, new fake helper."""
        self.connections += 1
        self.open = None
        self.source = FakeSource()
        self.controller = ControlledMedia(self.db, session_id=self.session_id, clock=self.clock.now, **host_kwargs())
        self.wire = self.wire_cls(self.controller, self._emit, self._connect, self._lookup, self._synthesize,
                                      clock=self.clock.now, **self.wire_kw)
        self.run(self._handshake())
        self.note(f'-- call #{self.connections} ready (quiet_reopen={self.controller.quiet_reopen})')

    def reconnect(self):
        self.version += 1
        self.note('-- reconnect: old call closed, new call on the same session')
        self.run(self.wire.close())
        self.settle()
        self.connect_peer()

    def close(self):
        try:
            self.run(self.wire.close())
            if self.gate is not None:
                self.gate.set()
            self.settle()
        finally:
            _nms.time, _nms.asyncio = _REAL_TIME, _REAL_ASYNCIO
            self.loop.close()
            if self._own_root:
                shutil.rmtree(self.root, ignore_errors=True)

    # -- boundary fakes ----------------------------------------------------------------------------------------

    async def _emit(self, frame):
        self.on_frame(frame)

    async def _connect(self):
        return self.source

    async def _lookup(self, question):
        self.lookup_calls.append(question)
        return list(SOURCE_ROWS)

    async def _synthesize(self, text, end=None):
        self.synth_calls.append(text)
        if self.hold:
            await self.gate.wait()
        return FRAME * PLAYOUT_FRAMES

    async def _handshake(self):
        sent = len(self.frames)
        await self.wire.client({'type': 'session.update', 'session': {}})
        await self.wire.client({'type': 'response.create', 'response': {
            'conversation': 'none', 'input': [{'content': [{'text': 'conduit-ready-s6'}]}]}})
        marker = [f for _, _, f in self.frames[sent:] if f.get('type') == 'conduit.turn']
        assert marker, 'the wire did not answer the readiness probe'
        await self.wire.client({'type': 'conduit.turn.done', 'turn_id': marker[-1]['turn_id']})
        assert self.wire.ready

    # -- driving ----------------------------------------------------------------------------------------------

    def run(self, coroutine):
        return self.loop.run_until_complete(coroutine)

    async def _settle(self):
        for _ in range(80):
            if not any(not task.done() for task in self.wire.tasks):
                return
            await asyncio.sleep(0)

    def settle(self):
        self.run(self._settle())

    async def _pump_until(self, frames, max_turns=60):
        for _ in range(max_turns):
            cue = self.open
            if cue is not None and cue.audio_frames >= frames:
                return
            if cue is None and not any(not task.done() for task in self.wire.tasks):
                return                                                  # nothing is open and nothing is on its way: the portion ended
            await asyncio.sleep(0)

    def pump_until(self, frames):
        """Let the sender run until ``frames`` frames of the portion in the ear were sent (or it ended)."""
        self.run(self._pump_until(frames))

    def note(self, line):
        self.log.append(line)

    def feed(self, event, settle=True):
        """Deliver one provider event through the production wire; return the frames it caused."""
        before = self.seq
        self.version += 1
        self.note(f't={self.clock.t - START_TIME:7.2f} provider {describe(event)}')
        self.run(self.wire.provider(event))
        if settle:
            self.settle()
        return [f for s, _, f in self.frames if s > before]

    def client(self, event):
        before = self.seq
        self.version += 1
        self.note(f't={self.clock.t - START_TIME:7.2f} phone    {event.get("type")}')
        self.run(self.wire.client(event))
        self.settle()
        return [f for s, _, f in self.frames if s > before]

    def advance(self, seconds, step=0.5):
        """Silence: the host calls ``wire.tick()`` every 0.1 s; here every ``step`` seconds of fake time."""
        before = self.seq
        self.version += 1
        self.note(f't={self.clock.t - START_TIME:7.2f} silence {seconds:g}s')
        left = float(seconds)
        while left > 1e-9:
            piece = min(step, left)
            self.clock.advance(piece)
            left -= piece
            self.run(self.wire.tick())
            self.settle()
        return [f for s, _, f in self.frames if s > before]

    # -- synthesis gate (a race: synthesis still running while the conversation moves on) ---------------------

    def hold_synthesis(self):
        async def make():
            return asyncio.Event()
        self.note('-- synthesis held open')
        self.gate = self.run(make())
        self.hold = True

    def release_synthesis(self):
        self.version += 1
        self.note('-- synthesis released')
        self.hold = False
        if self.gate is not None:
            self.gate.set()
        self.settle()

    # -- observation ------------------------------------------------------------------------------------------

    def state(self):
        return self.controller.state()

    def snapshot(self):
        key = (self.version, id(self.controller))
        cached = getattr(self, '_snapshot_cache', None)
        if cached is not None and cached[0] == key:
            return dict(cached[1])
        snap = self._snapshot()
        self._snapshot_cache = (key, snap)
        return dict(snap)

    def _snapshot(self):
        state = self.controller.state() or {}
        return {'revision': state.get('revision'), 'index': state.get('chunk_index'),
                'chunks': list(state.get('chunks') or []), 'completed': state.get('completed'),
                'streaming': state.get('streaming'), 'waiting': state.get('stream_waiting_next'), 'paused': bool(state.get('paused')),
                'hearing': self.controller.hearing, 'question_id': self.controller.question_id,
                'epoch': self.controller.epoch}

    def violate(self, message):
        self.violations.append(f'{message}\n  last frames: {[f.get("type") for _, _, f in self.frames[-6:]]}')

    def on_frame(self, frame):
        self.seq += 1
        self.frames.append((self.seq, self.clock.t, frame))
        kind = frame.get('type')
        if kind == 'response.created':
            if self.open is not None:
                self.open.replaced = True
                self.violate(f'two portions in flight: a response was created while {self.open.text!r} is still open '
                             f'(neither finished nor cleared)')
            cue = Cue(rid=frame['response']['id'], seq=self.seq, t=self.clock.t)
            self.cues.append(cue)
            self.open = cue
        elif kind == 'response.audio_transcript.delta':
            cue = self.open
            if cue is None or cue.rid != frame.get('response_id'):
                self.violate('transcript of a response that is not the open one')
                return
            cue.text = frame['delta']
            cue.diagnostic = cue.text in DIAGNOSTIC_TEXTS
            cue.snap = self.snapshot()
        elif kind == 'response.audio.delta':
            cue = self.open
            if cue is None or cue.rid != frame.get('response_id'):
                self.violate('audio of a response that is not the open one (stale audio after clear/replace)')
                return
            cue.audio_frames += 1
            base64.b64decode(frame['delta'], validate=True)
        elif kind == 'response.done':
            if frame['response'].get('id') is None:
                return                      # the answer to the readiness probe, not a portion
            cue = self.open
            if cue is None or cue.rid != frame['response'].get('id'):
                self.violate('response.done for a response that is not the open one')
                return
            cue.done = True
            self.open = None
        elif kind == 'output_audio_buffer.clear':
            if self.open is not None:
                self.open.cleared = True
                self.open = None
        elif kind == 'error':
            self.errors.append(frame)

    def trail(self, count=40):
        return '\n'.join(self.log[-count:])


# =====================================================================================================
# The conversation model: delivers events through the world and checks the invariants after EVERY step
# =====================================================================================================

@dataclass(frozen=True)
class Topic:
    key: str
    question: str
    answer: str


# Model-knowledge questions of the direct route (verified with the host configuration: every one gets a
# first cue). Vocabulary differs from topic to topic, so a portion of one answer is never a slice of another.
TOPICS = (
    Topic('inertia', 'Что такое инерция?',
          'Инерция — это свойство тела сохранять своё состояние движения или покоя. Чем больше масса, тем сильнее инерция.'),
    Topic('seasons', 'Почему меняются времена года?',
          'Времена года меняются из-за наклона земной оси. Поэтому полушария получают разное количество тепла.'),
    Topic('planets', 'Сколько планет в Солнечной системе?',
          'В Солнечной системе 8 планет, не считая карликовых. Самая большая из них — Юпитер.'),
    Topic('war', 'Когда началась Великая Отечественная война?',
          'Великая Отечественная война началась 22 июня 1941 года. Она закончилась победой в мае 1945 года.'),
    Topic('photosynthesis', 'Что такое фотосинтез?',
          'Фотосинтез — это процесс образования органических веществ из углекислого газа и воды на свету. '
          'Он происходит в хлоропластах растений.'),
    Topic('whale', 'Правда ли что кит рыба?',
          'Нет, кит не рыба, а млекопитающее, которое дышит лёгкими. Детёнышей он выкармливает молоком.'),
    Topic('angle', 'Сколько градусов в прямом угле?',
          'В прямом угле 90 градусов, а в развёрнутом угле 180 градусов. Полный угол равен 360 градусам.'),
    Topic('republic', 'Что такое республика?',
          'Республика — это форма правления, при которой высшая власть принадлежит выборным органам. '
          'Монархия устроена иначе.'),
    Topic('river', 'Какая самая длинная река в России?',
          'Самая длинная река России — Лена, её длина около 4400 километров. Она впадает в море Лаптевых.'),
    Topic('insects', 'Как называется наука о насекомых?',
          'Энтомология. Эта наука изучает строение и образ жизни насекомых.'),
    Topic('ice', 'Почему лёд плавает в воде?',
          'Лёд плавает, потому что он легче воды. Его плотность примерно 900 килограммов на кубометр.'),
    Topic('sound', 'С какой скоростью звук распространяется в воздухе?',
          'Звук распространяется в воздухе со скоростью около 340 метров в секунду. В воде он движется заметно быстрее.'),
)

# Defects that are OPEN. The random machine steps around exactly these triggers so that one known defect does
# not hide the next one; each has its own xfail(strict) test in test_s6_state_machine.py. When one is fixed
# its xfail test XPASSes (strict, so the suite fails) and the entry must be removed here and from the test.
TOLERATED = {
    'DEF-STATE-07': 'a late repeat of an EARLIER portion that starts with a question word is taken as a new question '
                    'and wipes the answer',
    'DEF-STATE-04': 'only the «Как?» case is left (the rest was fixed in bb879e0): while a portion waits, a bare «Как?» is read '
                    'as "what did you say?" (Task A) and replayed, not answered; the question pool of the machine avoids such questions',
}

REPEAT_PHRASES = ('повтори', 'повтори пожалуйста', 'ещё раз')
NOISE_PHRASES = ('э-э', 'ну', 'ага', 'м-м', 'хм')
OTHER_WORDS = ('кошка', 'трактор', 'бегемот', 'лампочка')


def word_groups(text, size):
    """The words of ``text`` in groups of ``size``, whitespace kept, exactly as a provider streams deltas."""
    pieces = re.findall(r'\s*\S+', text)
    return [''.join(pieces[i:i + size]) for i in range(0, len(pieces), size)]


def relaxed(text):
    """What an ASR returns for a perfect repeat: lower case, no punctuation (and still the same words)."""
    return ' '.join(re.sub(r'[^\w\s-]|—', ' ', text.casefold()).split())


@dataclass
class AssistantTurn:
    tid: str
    question: object
    groups: list
    sent: int = 0
    done: bool = False
    live: bool = True            # False after a reconnect: the new provider session never continues it


@dataclass
class Question:
    uid: str
    topic: Topic
    final_seq: int = 0
    seen: str = ''               # the answer text the provider has delivered so far
    assistant: AssistantTurn = None
    first_cue_owed: bool = False
    final_at: float = 0.0        # the clock at the moment its final was delivered


class Dialogue:
    """Delivers provider/phone events to the real wire and checks, after every single step, that the
    requirements hold. Invariant ids (used in failure messages and in the report):

    S0  a plain question is accepted as the current question
    S1  portion index never decreases or skips; the revision never decreases
    S2  the cursor advances only on a fresh full correct repeat (or when text arrives for a waiting frontier)
    S3  a full correct repeat advances exactly one portion and the next portion is spoken at once
    S4  partial/wrong repeats, noise, duplicates, stale and out-of-order events never advance or speak
    S5  never two portions in flight; no audio of a response that was cleared, replaced or finished
    S6  every spoken portion is a slice of the CURRENT question's answer (nothing of an old question)
    S7  the spoken portion is the controller's current portion
    S8  a final answer yields a first portion (unless the user is speaking)
    S9  «стоп» silences everything until a new question or a request to hear the portion again (CL2, ruling 1: «стоп» PAUSES the
        answer, its plan kept); «повтори» repeats the same portion, after «стоп» too; no model call
    S10 a reconnect never changes the cursor, never speaks by itself, never double-advances
    S11 no exception escapes, no error frame, no unhandled task error
    S12 nothing is spoken while the controller believes the user is speaking
    S13 the stored state is sane (0 <= index <= len(chunks), completed consistent)
    S14 a question the cloud never answered is reported once, ANSWER_WAIT_SECONDS after its final and not before (the one error
        frame and spoken phrase a fault-free run may produce), and is over then like after «стоп»; the report is never late
        while nobody is speaking and the cloud has sent nothing
    """

    def __init__(self, world=None):
        self.w = world or World()
        self.n_user = 0
        self.n_assistant = 0
        self.q = None
        self.taken_over = None           # the question whose plan was waiting when the current one was asked (G3, rules 4-5)
        self.old_turns = []              # unfinished assistant turns of earlier questions, still on this call
        self.dictating = None            # (uid, topic, prefix) of an open user turn
        self.sent = []                   # [(label, event)] delivered on the current call
        self.stopped = False
        self.conn_seq = 0
        self.presented = True
        self.cues_checked = 0
        self.errors_seen = 0             # error frames of the world that the invariants have looked at
        self.prev_cue = None
        self.acks = {}                   # revision -> ids of fresh correct repeats delivered
        self.advances = {}               # revision -> cursor advances seen
        self.last_ack = None             # the last correct-repeat event, kept across reconnects
        self.stats = {'events': 0, 'cues': 0, 'advances': 0, 'questions': 0, 'ticks': 0, 'reconnects': 0, 'holds': 0,
                      'frontier_waits': 0, 'frontier_releases': 0, 'auto_repeats': 0, 'parked_cues': 0,
                      'stale_events': 0, 'duplicates': 0, 'completed_answers': 0, 'stopped': 0, 'orphans': 0, 'replays': 0,
                      'answer_reports': 0, 'diagnostics': 0}

    # -- plumbing -------------------------------------------------------------------------------------------

    def close(self):
        self.w.close()

    def fail(self, invariant, message):
        raise AssertionError(f'[{invariant}] {message}\n--- last events ---\n{self.w.trail(30)}')

    def _uid(self):
        self.n_user += 1
        return f'u{self.n_user}'

    def _aid(self):
        self.n_assistant += 1
        return f'a{self.n_assistant}'

    def snap(self):
        return self.w.snapshot()

    def _calls(self):
        # A quiet note (CL2, ruling 5) goes upstream but asks the model nothing: it is not a call.
        return len(self.w.source.frames) - len(self.w.source.notes), len(self.w.lookup_calls)

    def cue_ready(self):
        """The cue a user could now repeat: played to its end on THIS call, still the current portion."""
        w = self.w
        cue = w.cues[-1] if w.cues else None
        if cue is None or cue.diagnostic or not cue.done or cue.seq <= self.conn_seq or w.open is not None or w.hold:
            return None
        s = w.snapshot()
        if s['completed'] or s['hearing'] or s['waiting'] or self.dictating is not None:
            return None
        if (cue.snap.get('revision'), cue.snap.get('index')) != (s['revision'], s['index']):
            return None
        return cue

    def active_answer(self):
        s = self.snap()
        return s['revision'] is not None and not s['completed'] and not self.stopped

    def _deliver(self, label, event, *, cause=None, settle=True):
        """One provider event through the wire; run the generic checks; return the cues it caused."""
        before = self.snap()
        calls = self._calls()
        turn = event.get('turn') if isinstance(event.get('turn'), dict) else {}
        try:
            self.w.feed(event, settle=settle)
        except Exception as error:   # S11: nothing may escape the production dispatch
            self.fail('S11', f'{type(error).__name__} escaped while delivering {describe(event)}: {error}')
        self.stats['events'] += 1
        self.sent.append((label, event))
        return self._after(label, before, calls, cause or label)

    def _after(self, label, before, calls, cause):
        w = self.w
        after = self.snap()
        fresh = w.cues[self.cues_checked:]
        self.cues_checked = len(w.cues)
        new_cues = [cue for cue in fresh if not cue.diagnostic]       # a spoken diagnostic is not a portion: no portion invariant applies
        self.stats['cues'] += len(new_cues)
        self.stats['diagnostics'] += len(fresh) - len(new_cues)
        self._check_wire()
        self._check_state(after)
        self._check_transition(cause, before, after)
        if self.w.wire.pending_cue is not None:
            self.stats['parked_cues'] += 1
        for cue in new_cues:
            self._check_cue(cue, cause)
            if cause == 'tick' and cue.snap['index'] == before['index'] and cue.snap['revision'] == before['revision']:
                self.stats['auto_repeats'] += 1
        if self._calls() != calls:
            self.fail('S9', f'a model/lookup call was made while handling {label} (the direct route never calls upstream)')
        self._check_owed_cue(after)
        self._check_answer_report_due(after)
        return new_cues

    # -- generic checks ---------------------------------------------------------------------------------------

    def _check_wire(self):
        w = self.w
        if w.violations:
            self.fail('S5', w.violations[0])
        while self.errors_seen < len(w.errors):
            frame = w.errors[self.errors_seen]
            self.errors_seen += 1
            if not self._take_answer_report(frame):
                self.fail('S11', f'error frame sent to the phone in a fault-free run: {frame}')
        if w.loop_errors:
            self.fail('S11', f'unhandled exception in a wire task: {w.loop_errors[-1]}')

    def _unanswered_since_final(self):
        """Has the current question had no cue at all since its final (a spoken diagnostic is not a cue)?"""
        q = self.q
        return q is not None and not any(c.seq > q.final_seq and not c.diagnostic for c in self.w.cues)

    def _take_answer_report(self, frame):
        """S14, the one error a fault-free run may send: ``controlled_answer_timeout``. It is legitimate only for the current question
        of THIS call, when no cue was made for it and ANSWER_WAIT_SECONDS have passed since its final. From then on the question is
        over, like after «стоп»: nothing of it is spoken until a new question. False for every other error frame."""
        if (frame.get('error') or {}).get('code') != 'controlled_answer_timeout':
            return False
        q, w = self.q, self.w
        if q is None or self.stopped or not self._unanswered_since_final():
            self.fail('S14', f'a missing-answer report without a question that is waiting for its first cue (question {q and q.uid}, '
                             f'stopped={self.stopped})')
        waited = w.clock.t - q.final_at
        if waited < ANSWER_WAIT_SECONDS - 1e-6:
            self.fail('S14', f'the question was given up after {waited:.2f} s, before the {ANSWER_WAIT_SECONDS:g} s wait was over')
        self.stats['answer_reports'] += 1
        q.first_cue_owed = False
        self.stopped = True
        return True

    def _check_answer_report_due(self, s):
        """S14, the other side: a question the cloud has sent NOTHING for, with nobody speaking, is reported within a few ticks of the
        wait (the listener speaking, a user turn left open and a held synthesis excuse it)."""
        q, w = self.q, self.w
        if q is None or self.stopped or q.assistant is not None or self.dictating is not None or w.hold or s['hearing']:
            return
        if w.controller.question_id != q.uid or not self._unanswered_since_final():
            return
        waited = w.clock.t - q.final_at
        if waited > ANSWER_WAIT_SECONDS + 3.5:
            self.fail('S14', f'the cloud has sent nothing for {waited:.1f} s since the final of {q.topic.key!r}, the listener is quiet, '
                             f'and the missing answer was not reported')

    def _check_state(self, s):
        if s['revision'] is None:
            return
        n = len(s['chunks'])
        if not 0 <= s['index'] <= n:
            self.fail('S13', f"index {s['index']} outside 0..{n}")
        if s['completed'] and s['chunks'] and s['index'] < n:
            self.fail('S13', f"completed but index {s['index']} < {n} portions")
        if not s['completed'] and s['index'] >= n and not s['waiting']:
            self.fail('S13', f"not completed but index {s['index']} >= {n} portions")

    def _check_transition(self, cause, before, after):
        if before['revision'] is None or after['revision'] is None:
            return
        if after['revision'] < before['revision']:
            self.fail('S1', f"revision went back {before['revision']} -> {after['revision']}")
        if after['revision'] != before['revision']:
            return
        delta = after['index'] - before['index']
        if delta not in (0, 1):
            self.fail('S1', f"portion index jumped {before['index']} -> {after['index']} on {cause}")
        if not before['waiting'] and after['waiting']:
            self.stats['frontier_waits'] += 1
        if not before['completed'] and after['completed']:
            self.stats['completed_answers'] += 1
        if delta == 1:
            self.stats['advances'] += 1
            if cause == 'assistant':
                self.stats['frontier_releases'] += 1
            if not (cause == 'ack_correct' or (cause == 'assistant' and before['waiting'])):
                self.fail('S2', f"cursor advanced {before['index']} -> {after['index']} on {cause}, "
                                f"which is not a fresh full correct repeat")
            rev = after['revision']
            self.advances[rev] = self.advances.get(rev, 0) + 1
            if self.advances[rev] > len(self.acks.get(rev, ())):
                self.fail('S10', f'{self.advances[rev]} advances from {len(self.acks.get(rev, ()))} distinct '
                                 f'confirmations in revision {rev}: a double advance')

    def _check_cue(self, cue, cause):
        s = cue.snap
        if not cue.text or not s:
            self.fail('S7', f'a response without portion text: {cue}')
        if self.stopped and cause != 'repeat':
            self.fail('S9', f'audio {cue.text!r} after «стоп», before a new question or a request to hear it again (cause: {cause})')
        if s['hearing']:
            self.fail('S12', f'portion {cue.text!r} spoken while the controller believes the user is speaking')
        # G3, rule 3 (changed on purpose): or the missing tail of it, after a try at its start
        if s['index'] >= len(s['chunks']) or not s['chunks'][s['index']].endswith(cue.text):
            self.fail('S7', f"spoken {cue.text!r} is not the current portion {s['chunks'][s['index']:s['index'] + 1]}")
        if self.q is None:
            self.fail('S6', f'audio {cue.text!r} with no question asked on this call')
        old = self.taken_over
        if (norm(cue.text) not in norm(self.q.seen) and self.q.assistant is None and old is not None and norm(cue.text) in norm(old.seen)
                and self.w.clock.t - self.q.final_at >= ANSWER_WAIT_SECONDS - 1e-6):
            # c23-final(B): G3, rules 4-5 (controlled_media._answer_watchdog → _resume_after_nothing, pinned by test_h6 n1_03 step 18): the cloud sent no turn at all for the
            # question that took a waiting plan over: that plan goes on. Its question is current again; nothing of a third question may come
            self.q, self.taken_over = old, None
        if norm(cue.text) not in norm(self.q.seen):
            self.fail('S6', f'portion {cue.text!r} is not part of the answer text delivered so far for the current '
                            f'question {self.q.topic.key!r}: text of an older question')
        if not self.presented:
            self.fail('S10', f'{cue.text!r} spoken by itself after a reconnect, before the user asked for it')
        prev = self.prev_cue
        if prev is not None:
            if s['revision'] < prev.snap['revision']:
                self.fail('S1', f"cue revision went back {prev.snap['revision']} -> {s['revision']}")
            elif s['revision'] == prev.snap['revision']:
                if s['index'] - prev.snap['index'] not in (0, 1):
                    self.fail('S1', f"spoken portions skip or go back: index {prev.snap['index']} -> {s['index']}")
            elif s['index'] != 0:
                # CL2, ruling 1: «стоп» pauses - a new revision with the same plan and cursor - so the dictation may go on from where
                # it stopped (the paused portion again, or the next one after a repeat of it). Any other new revision starts at 0.
                spoken = prev.snap['index'] + 1
                if s['chunks'][:spoken] != prev.snap['chunks'][:spoken] or s['index'] - prev.snap['index'] not in (0, 1):
                    self.fail('S1', f"first portion of a new revision has index {s['index']}")
        self.prev_cue = cue
        if cue.seq > self.q.final_seq:
            self.q.first_cue_owed = False

    def _check_owed_cue(self, after):
        q = self.q
        if q is None or not q.first_cue_owed:
            return
        w = self.w
        if w.hold or after['hearing'] or self.dictating is not None or self.stopped:
            return
        if not any(c.seq > q.final_seq and not c.diagnostic for c in w.cues):
            self.fail('S8', f'the final answer for {q.topic.key!r} produced no first portion')

    def _assert_no_move(self, name, before, after):
        if (before['revision'], before['index']) != (after['revision'], after['index']):
            self.fail('S4', f"{name} moved the cursor {before['revision']}/{before['index']} -> "
                            f"{after['revision']}/{after['index']}")

    # -- the user and the provider ----------------------------------------------------------------------------

    def ask(self, topic, *, partial_first=False, finish_open=False):
        w = self.w
        if finish_open and self.dictating is not None:
            uid, topic, _ = self.dictating
            self.dictating = None
        else:
            uid = self._uid()
            if partial_first:
                self._deliver('question_partial', turn_created(uid, 'user', topic.question.split()[0]), cause='partial')
        before = self.snap()
        final_at = self.w.clock.t
        cues = self._deliver('question', turn_done(uid, 'user', topic.question), cause='question')
        after = self.snap()
        if cues:
            self.fail('S6', f'audio {cues[0].text!r} was spoken while a new question was being accepted')
        if self.q is not None and self.q.assistant is not None and not self.q.assistant.done:
            self.old_turns.append(self.q.assistant)
        self.taken_over = self.q if before['revision'] is not None and not before['completed'] else None
        self.q = Question(uid=uid, topic=topic, final_seq=w.seq, final_at=final_at)
        self.stopped = False
        self.presented = True
        self.stats['questions'] += 1
        if w.controller.question_id != uid:
            self.fail('S0', f'a plain question {topic.question!r} was not accepted as the current question')
        if after['hearing']:
            self.fail('S12', 'still believes the user is speaking after the question was finalized')
        if before['revision'] is not None and after['revision'] is not None and after['revision'] <= before['revision']:
            self.fail('S6', f"a new question did not retire the old answer (revision {before['revision']} -> {after['revision']})")
        if after['revision'] is not None and not after['completed']:
            self.fail('S6', 'portions of the old question are still waiting after a new question')
        return cues

    def dictate(self, topic):
        uid = self._uid()
        prefix = ' '.join(topic.question.split()[:2])
        before = self.snap()
        self._deliver('dictate', turn_created(uid, 'user', prefix), cause='partial')
        self.dictating = (uid, topic, prefix)
        if self.q is not None:
            self.q.first_cue_owed = False
        if not self.w.controller.hearing:
            self.fail('S12', 'the controller does not know the user started speaking')
        if self.w.open is not None:
            self.fail('S5', 'audio still open after the user started speaking')
        self._assert_no_move('a partial utterance', before, self.snap())

    def finish_dictation_without_a_question(self, phrase):
        """The open user turn ends as something that is not a question (a cough, «ну»): a parked cue may play."""
        uid, topic, prefix = self.dictating
        self.dictating = None
        before = self.snap()
        self._deliver('dictation_noise', turn_done(uid, 'user', phrase), cause='dictation_noise')
        self._assert_no_move('the end of a dictation that was not a question', before, self.snap())

    def assistant_begin(self, group):
        q = self.q
        turn = AssistantTurn(tid=self._aid(), question=q, groups=word_groups(q.topic.answer, group))
        q.assistant = turn
        turn.sent = 1
        q.seen = turn.groups[0]
        return self._deliver('assistant', turn_created(turn.tid, 'assistant', turn.groups[0]), cause='assistant')

    def assistant_delta(self):
        turn = self.q.assistant
        group = turn.groups[turn.sent]
        turn.sent += 1
        self.q.seen += group
        return self._deliver('assistant', turn_delta(turn.tid, group, turn.sent), cause='assistant')

    def assistant_done(self):
        q = self.q
        turn = q.assistant
        turn.done = True
        turn.sent = len(turn.groups)
        q.seen = q.topic.answer
        q.first_cue_owed = not self.stopped and self.dictating is None and not self.w.controller.hearing
        return self._deliver('assistant', turn_done(turn.tid, 'assistant', q.topic.answer), cause='assistant')

    def assistant_only_done(self):
        """The whole answer as ONE turn.done, with no turn.created and no deltas before it (a short, fast answer)."""
        q = self.q
        turn = AssistantTurn(tid=self._aid(), question=q, groups=word_groups(q.topic.answer, 1))
        turn.done = True
        turn.sent = len(turn.groups)
        q.assistant = turn
        q.seen = q.topic.answer
        q.first_cue_owed = not self.stopped and self.dictating is None and not self.w.controller.hearing
        return self._deliver('assistant', turn_done(turn.tid, 'assistant', q.topic.answer), cause='assistant')

    def assistant_open(self):
        turn = self.q.assistant if self.q else None
        return turn is not None and turn.live and not turn.done

    def assistant_can_stream(self):
        turn = self.q.assistant if self.q else None
        return self.assistant_open() and turn.sent < len(turn.groups)

    def assistant_can_begin(self):
        return (self.q is not None and self.q.assistant is None and not self.stopped
                and self.dictating is None and self.presented)

    def utter(self, label, text, *, partial_first=False):
        """A user turn; with ``partial_first`` its turn.created comes first, as the provider sends it."""
        uid = self._uid()
        if partial_first and text.split():
            self._deliver('utterance_partial', turn_created(uid, 'user', text.split()[0]), cause='partial')
        cues = self._deliver(label, turn_done(uid, 'user', text), cause=label)
        return uid, cues

    HUMAN_REACTION = 0.5     # seconds: a listener starts repeating after the cue is over, not inside it (CUE_TAIL_SECONDS)

    def ack(self, *, relaxed_text=False, partial_first=False, cue=None):
        """A full correct repeat of the portion the user just heard."""
        w = self.w
        cue = cue or self.cue_ready()
        # Wave 2 / Task B: speech that begins while a cue can still be heard is not a repeat. A listener gets ready, and when the silence
        # timer repeats the portion meanwhile they let that cue end before they speak.
        spoken = len(w.cues)
        w.advance(self.HUMAN_REACTION)
        for _ in range(3):
            if len(w.cues) == spoken:
                break
            spoken = len(w.cues)
            w.advance(self.HUMAN_REACTION)
        text = relaxed(cue.text) if relaxed_text else cue.text
        uid = self._uid()
        if partial_first:
            self._deliver('utterance_partial', turn_created(uid, 'user', text.split()[0]), cause='partial')
        before = self.snap()
        self.acks.setdefault(before['revision'], set()).add(uid)
        event = turn_done(uid, 'user', text)
        self.last_ack = event
        cues = self._deliver('ack_correct', event, cause='ack_correct')
        after = self.snap()
        if before['revision'] != after['revision']:
            self.fail('S3', 'a full correct repeat changed the revision')
        if before['waiting']:
            if after['index'] != before['index']:
                self.fail('S4', 'a second ack at a waiting frontier advanced the cursor')
        elif before['streaming'] and before['index'] + 1 >= len(before['chunks']):
            if not after['waiting'] or after['index'] != before['index']:
                self.fail('S3', 'a repeat at the live frontier of a streaming answer must wait for text, not advance')
        else:
            if after['index'] != before['index'] + 1:
                self.fail('S3', f"a full correct repeat of {cue.text!r} did not advance exactly one portion "
                                f"(index {before['index']} -> {after['index']})")
            if not after['completed'] and not w.hold and not any(c.snap['index'] == after['index'] for c in cues):
                self.fail('S3', f"after the repeat of {cue.text!r} the next portion was not spoken at once")
            if after['completed'] and cues:
                self.fail('S3', 'a portion was spoken after the answer was completed')
        return cues

    def partial_repeat(self, take, *, partial_first=False):
        cue = self.cue_ready()
        words = cue.text.split()
        text = ' '.join(words[:max(1, min(take, len(words) - 1))])
        before = self.snap()
        self.utter('partial_repeat', text, partial_first=partial_first)
        self._assert_no_move('a partial repeat', before, self.snap())

    def wrong_repeat(self, how, *, partial_first=False):
        cue = self.cue_ready()
        words = cue.text.split()
        if how == 'negate':
            text = 'не ' + cue.text
        elif how == 'drop_negation' and any(norm(x) == 'не' for x in words):
            text = ' '.join(x for x in words if norm(x) != 'не')
        elif how == 'digit' and any(ch.isdigit() for ch in cue.text):
            text = re.sub(r'\d+', lambda m: str(int(m.group()) + 7), cue.text, count=1)
        else:
            text = ' '.join(words[:-1] + [OTHER_WORDS[len(words) % len(OTHER_WORDS)]])
        if not norm(text) or norm(text) == norm(cue.text):
            return
        before = self.snap()
        self.utter('wrong_repeat', text, partial_first=partial_first)
        self._assert_no_move('a wrong repeat', before, self.snap())

    def noise(self, phrase):
        before = self.snap()
        self.utter('noise', phrase)
        self._assert_no_move('noise', before, self.snap())

    def repeat(self, phrase, *, partial_first=False):
        """«повтори»: the same portion again, no model call."""
        w = self.w
        self.presented = True
        before = self.snap()
        uid, cues = self.utter('repeat', phrase, partial_first=partial_first)
        after = self.snap()
        self._assert_no_move('«повтори»', before, after)
        if self.active_answer() and not w.hold and not after['hearing'] and not cues and not after['waiting']:
            self.fail('S9', f'«{phrase}» on an active answer repeated nothing')   # waiting: DEF-STATE-06
        if before['paused']:
            if after['paused']:
                self.fail('S9', f'«{phrase}» after «стоп» did not end the pause')
            self.stopped = False                     # CL2, ruling 1: the paused portion is spoken again and the dictation goes on
        for cue in cues:
            if cue.snap['index'] != after['index'] or cue.snap['revision'] != after['revision']:
                self.fail('S9', f'«{phrase}» spoke a portion other than the current one')
        return cues

    def stop(self, *, partial_first=False):
        uid, cues = self.utter('stop', 'стоп', partial_first=partial_first)
        self.stats['stopped'] += 1
        self.stopped = True
        self.dictating = None
        if self.q is not None:
            self.q.first_cue_owed = False
        after = self.snap()
        if after['revision'] is not None and not after['completed'] and not after['paused']:
            self.fail('S9', '«стоп» left portions waiting that are neither paused nor over')     # CL2, ruling 1: a pause
        if cues:
            self.fail('S9', f'audio {cues[0].text!r} spoken in answer to «стоп»')
        if self.w.open is not None:
            self.fail('S9', 'audio still open after «стоп»')
        return cues

    def interrupt_a_portion(self, kind, frames, topic):
        """Start the current portion again («повтори»), let ``frames`` of its 10 audio frames reach the phone, then
        disturb it. The half-played portion must be cut off (every kind but ``silence``) and never continue."""
        w = self.w
        self.presented = True
        self._deliver('repeat', turn_done(self._uid(), 'user', 'повтори'), cause='repeat', settle=False)
        w.pump_until(frames)
        before, calls = self.snap(), self._calls()
        self._after('half played portion', before, calls, 'repeat')
        playing = w.open
        if playing is None:
            w.settle()
            return None
        if kind == 'silence':
            self.silence(0.5)
            if not playing.done:
                self.fail('S5', f'a quiet half second cut off the portion {playing.text!r}')
        else:
            if kind == 'stop':
                self.stop()
            elif kind == 'new_question':
                self.ask(topic)
            elif kind == 'barge_in':
                self.barge_in('client_cancel')
                self.noise('ну')
            elif kind == 'speech_started':
                self.barge_in('provider_speech_started')
                self.noise('ну')
            else:                                           # the user starts a question and says «ну» instead
                self.dictate(topic)
                self.finish_dictation_without_a_question('ну')
            if playing.done or not playing.cleared:
                self.fail('S5', f'the half-played portion {playing.text!r} was not cut off by {kind} '
                                f'(done={playing.done}, cleared={playing.cleared})')
            if w.open is playing:
                self.fail('S5', f'the portion {playing.text!r} is still open after {kind}')
        return playing

    def silence(self, seconds):
        before = self.snap()
        calls = self._calls()
        asked = self.q
        self.w.advance(seconds)
        self.stats['ticks'] += 1
        cues = self._after('silence', before, calls, 'tick')
        after = self.snap()
        # c23-final(B): the other move silence may make: G3, rules 4-5 (``_check_cue``): nothing came for the question, the plan it took over goes on, in a revision of its own
        resumed = self.q is not asked and cues and before['revision'] is not None and after['revision'] is not None and after['revision'] > before['revision']
        # F1 round 2 (ControlledMedia._rescue_first_cue): an answer whose producer stalled inside its first sentence, its turn open and
        # nothing published, gets its first cue from the text that arrived when the answer watchdog would give the question up - the
        # one move silence may make: from no answer to the first portion of a new revision
        q = self.q
        # c23-final(B): «no answer» is also the retired one a new question left (revision kept, no portions, completed): the F1 rescue is the same move then
        rescued = ((before['revision'] is None or (before['completed'] and not before['chunks'])) and after['revision'] is not None and after['index'] == 0 and (cues or self.w.hold)
                   and q is not None and q.assistant is not None and not q.assistant.done)
        if not (rescued or resumed):
            self._assert_no_move('silence', before, after)
        return cues

    def duplicable(self):
        """Indexes (from the end) of delivered events that may be retransmitted (the user's ``turn.created`` too: DEF-STATE-02
        is fixed, a repeated one is not a start of speech)."""
        return list(range(len(self.sent[-6:])))

    def duplicate(self, back):
        """Deliver an already delivered event once more, verbatim (a retransmit)."""
        label, event = self.sent[-1 - back]
        before = self.snap()
        calls = self._calls()
        hearing = self.w.controller.hearing
        self.w.feed(copy.deepcopy(event))
        self.stats['events'] += 1
        self.stats['duplicates'] += 1
        cues = self._after(f'duplicate of {label}', before, calls, 'duplicate')
        after = self.snap()
        self._assert_no_move(f'a duplicate of {label}', before, after)
        if cues:
            self.fail('S4', f'a duplicate of {label} caused audio {cues[0].text!r}')
        if after['hearing'] != hearing:
            self.fail('S4', f'a duplicate of {label} changed the "user is speaking" flag {hearing} -> {after["hearing"]}')

    def stale_assistant(self):
        """The next event of an answer that belongs to an OLD question (its question was replaced mid-stream)."""
        turn = next(t for t in self.old_turns if t.live and not t.done)
        before = self.snap()
        if turn.sent < len(turn.groups):
            group = turn.groups[turn.sent]
            turn.sent += 1
            event = turn_delta(turn.tid, group, turn.sent)
        else:
            turn.done = True
            event = turn_done(turn.tid, 'assistant', turn.question.topic.answer)
        calls = self._calls()
        self.w.feed(event)
        self.stats['events'] += 1
        self.stats['stale_events'] += 1
        cues = self._after('stale assistant event', before, calls, 'stale')
        self._assert_no_move('a late event of an old answer', before, self.snap())
        if cues:
            self.fail('S6', f'a late event of the OLD answer caused audio {cues[0].text!r}')

    def has_stale(self):
        return any(t.live and not t.done for t in self.old_turns)

    def orphan_delta(self):
        self.stats['orphans'] += 1
        before = self.snap()
        calls = self._calls()
        self.w.feed(turn_delta('a-never-created', ' лишние слова', 1))
        cues = self._after('delta of an unknown turn', before, calls, 'stale')
        self._assert_no_move('a delta of an unknown turn', before, self.snap())
        if cues:
            self.fail('S4', 'a delta of an unknown turn caused audio')

    def reconnect(self):
        w = self.w
        before = self.snap()
        cues_before = len(w.cues)
        w.reconnect()
        self.stats['reconnects'] += 1
        after = self.snap()
        keys = ('revision', 'index', 'chunks', 'completed')
        changed = {k for k in keys if before[k] != after[k]}
        # Wave 2 / Task B (ruling 2): the new call closes a stream the old one left open. A listener who had confirmed all the text
        # there was (waiting at the frontier) has then finished the answer: the one change a reconnect may make by itself.
        repaired = bool(before['streaming'] and before['waiting'] and not after['streaming'] and changed <= {'index', 'completed'})
        if changed and not repaired:
            self.fail('S10', f'the reconnect itself changed the stored state {before} -> {after}')
        if len(w.cues) != cues_before:
            self.fail('S10', 'the reconnect itself produced audio')
        self.conn_seq = w.seq
        self.presented = False
        self.sent = []
        self.dictating = None
        if self.q is not None:
            self.q.first_cue_owed = False
        for turn in ([self.q.assistant] if self.q and self.q.assistant else []) + self.old_turns:
            turn.live = False
        self.old_turns = []
        self.cues_checked = len(w.cues)
        self.prev_cue = next((c for c in reversed(w.cues) if not c.diagnostic), None)

    def can_replay_ack(self):
        """A retransmitted ack is only distinguishable from a fresh repeat when its words differ from the portion
        that is current now (the same words ARE a fresh confirmation: the controller cannot tell them apart)."""
        if self.last_ack is None or self.w.connections < 2 or not self.presented:
            return False
        s = self.snap()
        current = s['chunks'][s['index']] if s['revision'] is not None and s['index'] < len(s['chunks']) else ''
        words = norm(self.last_ack['turn']['transcript']).split()
        if len(words) >= 3 and words[0] in QUESTION_WORDS:      # DEF-STATE-07: it would read as a new question
            return False
        if alternative_question(norm_words(self.last_ack['turn']['transcript'])):      # Fable 10.11: a choice of two at the END of an utterance asks («… движения или покоя.»): a late repeat of that form is a new question, as DEF-STATE-07's is
            return False
        return norm(self.last_ack['turn']['transcript']) != norm(current)

    def replay_last_ack(self):
        """The same correct-repeat event delivered again on the new call (a retransmit across a reconnect)."""
        self.stats['replays'] += 1
        before = self.snap()
        calls = self._calls()
        self.w.feed(copy.deepcopy(self.last_ack))
        self.stats['events'] += 1
        cues = self._after('replayed ack after reconnect', before, calls, 'duplicate')
        self._assert_no_move('a replayed ack after a reconnect', before, self.snap())
        if cues:
            self.fail('S10', f'a replayed ack after a reconnect caused audio {cues[0].text!r}')

    def barge_in(self, how):
        """The phone (or the cloud VAD) reports speech: the portion in the ear is cut off."""
        w = self.w
        before = self.snap()
        calls = self._calls()
        if how == 'client_cancel':
            w.client({'type': 'response.cancel'})
        elif how == 'client_clear':
            w.client({'type': 'input_audio_buffer.clear'})
        else:
            w.feed({'type': 'input_audio_buffer.speech_started'})
        self._after(f'barge-in {how}', before, calls, 'barge_in')
        if self.q is not None:
            self.q.first_cue_owed = False
        if not w.controller.hearing:
            self.fail('S12', f'{how} did not mark the user as speaking')
        if w.open is not None:
            self.fail('S5', f'{how} left audio open')

    def hold_synthesis(self):
        self.stats['holds'] += 1
        self.w.hold_synthesis()

    def release_synthesis(self):
        before = self.snap()
        calls = self._calls()
        self.w.release_synthesis()
        self._after('release synthesis', before, calls, 'release')
