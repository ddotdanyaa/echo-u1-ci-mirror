"""Stand of the track «the system always answers»: the REAL host (controlled_host.serve, ControlledMedia, NativeMediaSocket, fast_text.for_call, reserve_text) with only its boundaries faked.

Faked: the phone, the GPT-Live helper pipe and SAPI (helpers_s6_fault), the local ear (the words of the owner's question), and the roads of the text: the first road (``CR.codex_stream``)
and the network of the reserve (``reserve_text._post``, ``reserve_search._post``), each by a scenario of its own (ok, fail, empty, blank, hang, late, cut). Everything between runs for real.

Determinism (the loop runs on virtual time while the jobs of the text channel are real threads):
1. the clocks of fast_text and reserve_text are the clock of the loop that was captured (``Clock``);
2. a job thread (a thread started through ``fast_text.threading.Thread`` with a job as its first argument) is started SYNCHRONOUSLY (``Walker``): the loop waits until the thread has ended or
   has parked in a faked road (a hang, a late answer), so the virtual clock never runs while a job thread works;
3. a late answer is a timer of the loop (``call_at``): at its time the loop opens the gate of the parked thread and waits until the thread has said its text and ended (or parked again);
4. every call starts with the health of the roads clean (``fresh_health``); every parked thread is let go at the end of the call.
"""
import asyncio
import json
import threading
import time as real_time
import types

import pytest

import helpers_s6_fault as F
from helpers_spoken_diagnostics import responses
from echo_sync import controlled_host, diagnostics, ear_shadow, fast_text as FT, native_media_socket as NMS, reserve_search, reserve_text
from echo_sync import codex_road as CR
from echo_sync.classifier import QUESTION

# The live profile of the owner (the keys that matter here; the rest is the default).
LIVE = {'local_ear': 'act', 'fast_text': 'on', 'text_transport': 'http', 'instant': 'on',
        'stop_in_flight': 'on'}
# The numbers of SPEC.md section 1, kept here as the stand's own (a mutant that changes the module must still be seen by the matrix).
N, M, STALLS = 2.0, 8.0, 2
SYNTH_TICK_S = 1.5            # what the synthesis and one tick of the host may add to the first word of a road
GAP_S = 0.3                   # the next road after a refusal before the first word: at once (one tick of 0.1 s and some)
KEYS = {'GROQ_API_KEY': 'k1', 'GROQ_API_KEY_2': 'k2', 'GEMINI_API_KEY': 'g1'}
ALIASES = {('GROQ_API_KEY', 'openai/gpt-oss-120b'): 'groq1', ('GROQ_API_KEY_2', 'openai/gpt-oss-120b'): 'groq2', ('GEMINI_API_KEY', 'gemini-3.5-flash-lite'): 'gemini'}
# The answer of a road is of the question (the controller does not say an answer twice, and does not say one of another question) and ends in the mark of the road: what the phone hears says which road gave it.
TOPICS = ['Свойство тела сохранять скорость', 'Процесс создания органики на свету', 'Воздух рассеивает синий свет', 'Капли дождя разлагают свет на цвета']
MARKS = {'codex': 'Кодекс', 'groq1': 'Грок один', 'groq2': 'Грок два', 'gemini': 'Гемини', 'other': 'запасной'}
# The questions of general knowledge no local base answers, each with the answer of the cloud and a word of it that the phone must hear (the controller drops an answer that is of another question).
QA = [('Что такое инерция?', F.DIRECT_ANSWER, 'покоя'), (F.OTHER_DIRECT_QUESTION, F.OTHER_DIRECT_ANSWER, 'органических'),
      ('Почему небо голубое?', 'Воздух рассеивает синий свет, поэтому небо голубое.', 'рассеивает'),
      ('Как работает радуга?', 'Капли дождя разлагают свет на цвета.', 'капли')]
QUESTIONS = [q for q, _, _ in QA]
QUESTIONS_NO_MARK = [q.rstrip('?') for q in QUESTIONS]


def answer_of(alias, text):
    """The answer ``alias`` gives to the question whose words are in ``text`` (a request of the job, a body of the reserve)."""
    at = max(range(len(QA)), key=lambda n: str(text).rfind(QA[n][0].rstrip('?')))
    return f'{TOPICS[at]}, отвечает {MARKS[alias]}.'


def cloud_answer(question):
    """(the answer of the cloud, its mark) for a question of QA, with or without its question mark."""
    return next((answer, mark) for q, answer, mark in QA if q.rstrip('?') == question.rstrip('?'))


class ConnectError(Exception):
    """The name is what ``Roads._rest`` reads (httpx's own is not imported: nothing leaves the stand)."""


class RemoteProtocolError(Exception):
    pass


class ReadTimeout(Exception):
    """What a reserve road that says nothing ends in when its transport gives up (the ``timeout`` of ``_post``)."""


# ---- scenarios of a road -----------------------------------------------------------------------------------------------------------
def ok(text=None):
    return ('ok', text)


def fail(kind):
    return ('fail', kind)


def empty():
    return ('empty',)


def hang():
    return ('hang',)


def late(delay, text=None):
    return ('late', delay, text)


def blank():
    """A road that says white space only (a space, a line feed) and ends: no word."""
    return ('blank',)


def cut(kind, text=None):
    return ('cut', text, kind)


def fault(kind, primary):
    """The exception of a refusal ``kind``: for the first road a FastTextError (a fixed token), for the reserve a ReserveError; two network errors are named like httpx's."""
    if kind == 'ConnectError':
        return ConnectError('connect failed')
    if kind == 'RemoteProtocolError':
        return RemoteProtocolError('peer closed connection')
    return (CR.FastTextError if primary else reserve_text.ReserveError)(kind)


def fresh_health():
    with reserve_text._LOCK:
        reserve_text._REST.clear()
        reserve_text._BUDGET.clear()
        reserve_text._PRIMARY['until'] = 0.0


def service_phrases():
    """The whole list of what the system says of itself (never an answer)."""
    return set(diagnostics.PHRASES.values()) | set(NMS.LOCAL_PHRASES.values())


def is_service(text):
    """A phrase of the system: the whole text of one, or one of its sentences (the host speaks a phrase by sentences), or a text that begins with the refusal of the tail guard."""
    text = ' '.join(str(text or '').split())
    if not text:
        return False
    refusal = reserve_text.REFUSAL
    sentences = [sentence.strip() + '.' for sentence in refusal.split('.') if sentence.strip()]
    return text in service_phrases() or text.startswith(refusal) or text in sentences


# ---- the clock and the threads --------------------------------------------------------------------------------------------------
class Clock:
    """``time`` for fast_text and reserve_text: monotonic() is the clock of the captured loop (a job thread may read it, a running loop is not needed), the rest is the real module."""

    def __init__(self, loop):
        self._loop = loop

    def monotonic(self):
        return self._loop.time()

    def __getattr__(self, name):
        return getattr(real_time, name)


class Walker:
    """A job thread whose ``start`` waits (real 2 s at most) until the thread has ended or has parked in a faked road."""

    def __init__(self, stand, target, args, name):
        self.stand, self.target, self.args, self.name = stand, target, args, name
        self.settled = threading.Event()
        self.thread = None

    def _go(self):
        self.stand.tls.walker = self
        try:
            self.target(*self.args)
        finally:
            self.settled.set()

    def start(self):
        self.thread = threading.Thread(target=self._go, name=self.name, daemon=True)
        self.stand.walkers.append(self)
        self.thread.start()
        self.settled.wait(2.0)

    def is_alive(self):
        return self.thread is not None and self.thread.is_alive()

    def join(self, timeout=None):
        if self.thread is not None:
            self.thread.join(timeout)


class Threads:
    """``fast_text.threading``: Event, Lock and the rest are the real ones; the thread of a job is a Walker, any other thread (close, drain, keepalive) is an ordinary one."""

    def __init__(self, stand):
        self.stand = stand
        self.Event, self.Lock = threading.Event, threading.Lock

    def Thread(self, group=None, target=None, name=None, args=(), kwargs=None, *, daemon=None):      # noqa: N802 - the name of threading's
        if args and hasattr(args[0], 'request') and not kwargs:
            return Walker(self.stand, target, args, name)
        return threading.Thread(target=target, name=name, args=args, kwargs=kwargs or {}, daemon=True)

    def __getattr__(self, name):
        return getattr(threading, name)


class Ear:
    """The local ear of the call (``ear_shadow.for_call_async``): it hands the transport what the test put into ``records``."""
    acting = True
    current = None

    def __init__(self):
        self.records, self.fed = [], 0

    def poll(self):
        out, self.records = self.records, []
        return out

    def feed(self, pcm, input_ms=None):
        self.fed += len(pcm)

    def close(self):
        pass


def ear_record(uid, text):
    return {'uid': uid, 'text': text, 'kind': QUESTION, 'reason': 'x', 'revision': None, 'index': None, 'speech_ms': 900, 'lag_ms': 300, 'decode_ms': 200,
            'onset_input_ms': 0, 'offset_input_ms': 900, 'onset': 0.0, 'offset': 0.0}


# ---- the stand ---------------------------------------------------------------------------------------------------------------------
class Stand:
    """The scenarios of the roads (``plan``: alias -> scenario, changeable between the questions of a call) and the journal of what each road was asked: ``calls`` = (virtual time, alias)."""

    def __init__(self, plan=None, *, default=None, profile=None):
        self.plan, self.profile = dict(plan or {}), dict(profile or {})      # ``profile``: what a cell changes of the live profile (``LIVE``)
        self.default = default or fail('http_429')            # a reserve road the plan does not name refuses at once
        self.calls, self.cancels, self.walkers, self.searches = [], [], [], []
        self.tls = threading.local()
        self.stop = threading.Event()
        self.ear = Ear()
        self.loop = None
        self.asked = []                                       # (virtual time, text) of the questions given
        self.closed_early = []

    # -- installing ---------------------------------------------------------------------------------------------------------------
    def install(self, mp, loop):
        self.loop = loop
        fresh_health()
        mp.setattr(CR, 'codex_stream', lambda credentials: self._codex)
        mp.setattr(reserve_text, 'read_keys', lambda path=None: dict(KEYS))
        mp.setattr(reserve_text, '_post', self._post)
        mp.setattr(reserve_search, '_post', self._search_post)
        mp.setattr(FT, 'time', Clock(loop))
        mp.setattr(reserve_text, 'time', Clock(loop))
        mp.setattr(FT, 'threading', Threads(self))
        real_read = controlled_host.read_profile_settings
        ear = self.ear

        async def read(home):
            settings = dict(await real_read(home))
            settings.update(LIVE)
            settings.update(self.profile)
            return settings

        async def hear(settings, controller, **kw):
            return ear
        mp.setattr(controlled_host, 'read_profile_settings', read)
        mp.setattr(ear_shadow, 'for_call_async', hear)
        mp.setattr(ear_shadow, 'for_call', lambda settings, controller, **kw: ear)      # serve takes ``for_call`` (the transport's shared verdict) whenever the onset detector is built, ``for_call_async`` when it is not

    def release_all(self):
        self.stop.set()
        for walker in self.walkers:
            walker.join(1.0)

    # -- the roads ----------------------------------------------------------------------------------------------------------------
    def scenario(self, alias):
        return self.plan.get(alias, ok() if alias == 'codex' else self.default)

    def _codex(self, request, cancelled, *rest):
        yield from self._road('codex', cancelled, True, None, json.dumps(request, ensure_ascii=False))

    def _post(self, url, headers, body, timeout):
        name = next((n for n, key in KEYS.items() if headers.get('Authorization') == 'Bearer ' + key), '?')
        alias = ALIASES.get((name, body.get('model')), 'other')
        for piece in self._road(alias, None, False, timeout, json.dumps(body.get('messages'), ensure_ascii=False)):
            yield 'data: ' + json.dumps({'choices': [{'delta': {'content': piece}}]}, ensure_ascii=False)
        yield 'data: [DONE]'

    def _search_post(self, url, headers, body, timeout):
        self.searches.append(self.loop.time())
        raise reserve_text.ReserveError('http_429')

    def _road(self, alias, cancelled, primary, timeout=None, question=''):
        """What a road does when it is asked: the generator of its text (the exception, the silence, the late word). A reserve road knows no ``cancelled`` (a blocked post is blocked) and
        ends a silence in a ReadTimeout after its ``timeout``; the first road is silent until it is cancelled."""
        scenario = self.scenario(alias)
        self.calls.append((self.loop.time(), alias))
        kind = scenario[0]
        text = scenario[-1] if kind in ('ok', 'late') and scenario[-1] else answer_of(alias, question)
        if kind == 'fail':
            raise fault(scenario[1], primary)
        if kind == 'empty':
            return
        if kind == 'blank':
            yield ' '
            yield '\n'
            return
        if kind == 'ok':
            yield from self._pieces(text)
        elif kind == 'cut':
            yield text.split('.')[0].split(' ')[0] + ' '
            raise fault(scenario[2], primary)
        elif kind == 'hang':
            gate = threading.Event()
            if timeout is not None:
                walker = getattr(self.tls, 'walker', None)
                self.loop.call_soon_threadsafe(self.loop.call_at, self.loop.time() + timeout, self._open, walker, gate, cancelled)
            self._park(alias, cancelled, gate if timeout is not None else None)
            if gate.is_set() and not self.stop.is_set():
                raise ReadTimeout('read timed out')
        elif kind == 'late':
            gate = threading.Event()
            walker = getattr(self.tls, 'walker', None)
            assert walker is not None, 'a late road asked from a thread the stand does not hold'
            at = self.loop.time() + scenario[1]
            self.loop.call_soon_threadsafe(self.loop.call_at, at, self._open, walker, gate, cancelled)
            self._park(alias, cancelled, gate)
            if gate.is_set() and not (cancelled is not None and cancelled.is_set()):
                yield from self._pieces(text)
        else:
            raise AssertionError(f'unknown scenario {scenario!r}')

    @staticmethod
    def _pieces(text):
        words = text.split(' ')
        half = max(1, len(words) // 2)
        return [' '.join(words[:half]) + ' ', ' '.join(words[half:])]

    def _park(self, alias, cancelled, gate=None):
        walker = getattr(self.tls, 'walker', None)
        if walker is not None:
            walker.settled.set()
        while not (self.stop.is_set() or (gate is not None and gate.is_set()) or (cancelled is not None and cancelled.is_set())):
            real_time.sleep(0.002)
        if cancelled is not None and cancelled.is_set():
            self.cancels.append((self.loop.time(), alias))

    @staticmethod
    def _open(walker, gate, cancelled):
        """On the loop at the time of a late answer: the thread says its text and ends (or parks again) before the loop goes on."""
        if (cancelled is not None and cancelled.is_set()) or not walker.is_alive():
            return
        walker.settled.clear()
        gate.set()
        walker.settled.wait(2.0)

    # -- the questions ------------------------------------------------------------------------------------------------------------
    async def ask(self, host, text, *, cloud=True, lag=0.0, pre=0.0, uid='u1'):
        """The ear hears the question (``pre``: s of the tick it falls in), the cloud's final follows after ``lag`` s (only with a live GPT-Live: ``cloud``). Returns the virtual time."""
        if pre:
            await host.advance(pre)
        at = host.now()
        self.ear.records.append(ear_record(uid, text))
        self.asked.append((at, text))
        if cloud:
            if lag:
                await host.advance(lag)
            await host.ask(text, tid=uid)
        return at

    def calls_since(self, at):
        return [(t - at, alias) for t, alias in self.calls if t >= at - 1e-9]


def run_stand(tmp_path, stand, body, *, handshake=True, patches=(), **rig):
    """``controlled_host.serve`` on the virtual loop with the stand installed; ``body(host, stand)``. Returns what the body returns."""
    __tracebackhide__ = True
    with pytest.MonkeyPatch.context() as mp:
        async def main():
            __tracebackhide__ = True
            F.patch_clock(mp)
            stand.install(mp, asyncio.get_running_loop())
            for target, name, value in patches:
                mp.setattr(target, name, value)
            try:
                async with F.HostRig(tmp_path, mp, **rig) as host:
                    try:
                        if handshake:
                            await host.handshake()
                        return await body(host, stand)
                    finally:
                        stand.release_all()
            finally:
                stand.release_all()
                fresh_health()
        return F.run(main)


async def open_local(host, *, within=6.0 + 0.2):
    """The opening of a call whose GPT-Live is dead (setup=['no_offer'] or a refusing helper): session.update, the readiness marker. Returns (seconds to session.updated or None, ready received)."""
    t = host.now()
    host.ws.push({'type': 'session.update', 'session': {}})
    got = await host.until(lambda: any(f.type == 'session.updated' for f in host.ws.frames), 40)
    updated = next((f.t - t for f in host.ws.frames if f.type == 'session.updated'), None) if got else None
    ready = False
    if got:
        host.ws.push({'type': 'response.create', 'response': {'conversation': 'none', 'input': [{'content': [{'text': 'conduit-ready-s6'}]}]}})
        ready = await host.until(lambda: any(f.type == 'conduit.turn' for f in host.ws.frames), 5)
        if ready:
            marker = next(f for f in host.ws.frames if f.type == 'conduit.turn')
            host.ws.push({'type': 'conduit.turn.done', 'turn_id': marker.data['turn_id']})
    return updated, ready


# ---- what the phone heard -----------------------------------------------------------------------------------------------------------
def heard(host, since):
    """The spoken responses since ``since``: ``answers`` (completed, not a phrase of the system), ``service`` (a phrase of the system, any status), ``other`` (the rest: cut off, empty)."""
    out = {'answers': [], 'service': [], 'other': []}
    for item in responses(host.ws.frames):
        if item['start'] < since or not item['text']:
            continue
        item['first'] = item['times'][0] if item['times'] else item['start']
        if is_service(item['text']):
            out['service'].append(item)
        elif item['status'] == 'completed':
            out['answers'].append(item)
        else:
            out['other'].append(item)
    return out


def text_of(items):
    return ' '.join(str(item['text']) for item in items)
