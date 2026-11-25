"""A1: one whole conversation through the real chain, and its invariants.

REAL: ControlledMedia (built like controlled_host, ``helpers_s6_state.World``), NativeMediaSocket, the ShadowEar (``ear_shadow.for_call``) and the FastText channel (``fast_text.for_call``)
with their own threads. SCRIPTED: the speech detector and the recognizer's worker (the ear's text of an utterance comes when the seed says), the cloud's provider events (its
user turns 0.5-5 s late, sometimes lost; its own assistant turns), the text model (an ideal mind that answers what it is given; its latency, its failures), reconnects. The seed
sets everything: what the listener says, when, what the ear and the cloud make of it, how late each of them is. Nothing here is a measurement of time on a laptop or a phone.

``run(seed)`` -> ``Outcome``: the record of the conversation and the violations of the invariants (``check``):
  A1 one utterance gives at most one answer             A2 no old answer is heard after a new question or «стоп» (until it is asked back)
  A3 the cursor goes only forward, one NEXT per repeat   A4 a plan does not come back by itself
  A5 every wait is bounded (an asked question is answered or reported, the flag of speech falls, a portion is not repeated on its own forever)
  A6 no sound begins over unfinished speech (A6o: only the ear heard it begin, the cloud had not announced it: the ear alone holds a cue 1 s by design)
                                                        A7 the numbers and «не» of an answer agree with the question
  A8 the cloud's own chatter is never said              A9 the job is not given two utterances as one («Распознано: A / B»)
  A2e an older answer begun after the ear (not yet the cloud) had a new question: reported, not counted as a defect
  A0 the wire's own checks: no two portions in flight, no error frame, no exception
"""
import base64
import bisect
import heapq
import queue
import json
import os
import random
import re
import sys
import threading
import tracemalloc
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _path in (str(ROOT / 'tests'), str(ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import helpers_s6_state as S                                                          # noqa: E402
from echo_sync import ear_shadow                                                      # noqa: E402
from echo_sync import fast_text as FT                                                 # noqa: E402
from echo_sync.controlled_media import ANSWER_WAIT_SECONDS, HEARING_SECONDS          # noqa: E402
from echo_sync.timer_policy import ONSET_HOLD_MAX_S                            # noqa: E402
from echo_sync.quick_math import spell                                                # noqa: E402
from echo_sync.reserve_text import REFUSAL                                            # noqa: E402
from echo_sync.settings import resolve                                                # noqa: E402
from echo_sync.textutil import normalize                                              # noqa: E402
from test_ear_shadow import ScriptedDetector                                          # noqa: E402
from tools.replay import real_sound as RS                                              # noqa: E402

TICK = 0.1                    # the host ticks the wire every 0.1 s
GRID = 0.21                   # a time told by ticks is off by at most two of them
AUDIO = base64.b64encode(b'\x00\x00' * 2400).decode('ascii')
CHATTER_OF_THE_CLOUD = ('Мг.', 'Ну наконец-то. Ну что обсудим сегодня?', 'Давай такой', 'Хорошо, слушаю.')


async def voice(text, end=None):
    """Half a second of voiced sound per cue, like test_h3_tempo."""
    return b'\x00\x40' * 12000


def values(text):
    return FT._values(FT._atoms(text))


def lemmas(text):
    return {atom.atom for atom in FT._atoms(text)}


# =====================================================================================================================================
# what was asked: the truth the stand keeps and the ideal mind answers from
# =====================================================================================================================================

EVENTS = (('крещение Руси', 'Крещение Руси', 988), ('Куликовская битва', 'Куликовская битва', 1380), ('отмена крепостного права', 'Крепостное право отменили', 1861),
          ('полёт Гагарина', 'Гагарин полетел', 1961), ('основание Петербурга', 'Петербург основали', 1703))
ARTICLES = (17, 19, 21, 23)
VERBS = (('нагревать', 'охлаждать'), ('увеличивать', 'уменьшать'))


@dataclass(frozen=True)
class Q:
    """A question: ``family`` and its ``params``; ``text`` as said."""
    family: str
    params: tuple
    text: str

    def answer(self):
        p = self.params
        if self.family == 'money':
            return f'Осталось {p[0] - p[1]} рублей.' if p[0] >= p[1] else f'Не хватает {p[1] - p[0]} рублей.'
        if self.family == 'mult':
            return f'{p[0] * p[1]}. Это {p[0]} раз по {p[1]}.'
        if self.family == 'verb':
            return f'Да, при таком давлении жидкость нужно {p[0]}, а не {p[1]}.'
        if self.family == 'year':
            return f'{EVENTS[p[0]][1]} в {EVENTS[p[0]][2]} году.'
        return f'Статья {p[0]} Налогового кодекса о налогах и сборах.'

    def allowed(self):
        p = self.params
        if self.family == 'money':
            return {str(p[0]), str(p[1]), str(abs(p[0] - p[1]))}
        if self.family == 'mult':
            return {str(p[0]), str(p[1]), str(p[0] * p[1])}
        if self.family == 'year':
            return {str(EVENTS[p[0]][2])}
        return None                       # any number (the reference base says more than the question)

    def fits(self, plan):
        """Is ``plan`` (what an answer says so far) an answer to this question: the start of the ideal answer, or the key of it (the result, the year, the article, the verb)?"""
        said, ideal = normalize(plan), normalize(self.answer())
        if said and (ideal.startswith(said) or said.startswith(ideal)):
            return True
        if self.contradicts(plan):
            return False
        p = self.params
        if self.family == 'money':
            return str(abs(p[0] - p[1])) in values(plan) and ('остаться' if p[0] >= p[1] else 'хватать') in lemmas(plan)
        if self.family == 'mult':
            return str(p[0] * p[1]) in values(plan)
        if self.family == 'year':
            return str(EVENTS[p[0]][2]) in values(plan)
        if self.family == 'verb':
            return p[0] in lemmas(plan)
        return str(p[0]) in values(plan) and 'статья' in lemmas(plan)

    def contradicts(self, plan):
        """Does what an answer says so far (``plan``) say another thing than this question asks for: a number it cannot have, the verb the question denies, another article?"""
        if self.family == 'article':
            said = re.findall(r'(?i)стать[ьяеи]\w*\s+(\d+)', plan)
            return any(int(n) != self.params[0] for n in said)
        if self.family == 'verb':
            words = lemmas(plan)
            return self.params[1] in words and not re.search(r'(?i)\bне\s+' + self.params[1][:-2], plan) or ('не' in words and re.search(r'(?i)\bне\s+' + self.params[0][:-2], plan) is not None)
        if self.family == 'money' and ('хватать' if self.params[0] >= self.params[1] else 'остаться') in lemmas(plan):
            return True                        # «осталось» for «не хватает»: the numbers the other way round
        allowed = self.allowed()
        return bool(values(plan) - allowed)


def ask(rng, last=None):
    """A question; after a question of numbers or «не», often the same words with the numbers or the negation the other way round (the defect of a2 is the reason to try it)."""
    if last is not None and last.family in ('money', 'verb') and rng.random() < 0.35:
        a, b = last.params
        if last.family == 'money':
            return Q('money', (b, a), f'Если у меня было {b} рублей и я потратил {a} рублей, сколько денег осталось?')
        return Q('verb', (b, a), f'Нужно не {a}, а {b} эту жидкость при таком давлении?')
    family = rng.choice(('money', 'money', 'mult', 'verb', 'year', 'year', 'article'))
    if family == 'money':
        a, b = rng.sample(range(20, 100, 10), 2)
        return Q('money', (a, b), f'Если у меня было {a} рублей и я потратил {b} рублей, сколько денег осталось?')
    if family == 'mult':
        a, b = rng.randint(2, 9), rng.randint(2, 9)
        return Q('mult', (a, b), f'Сколько будет {a} умножить на {b}?')
    if family == 'verb':
        pos, neg = rng.choice(VERBS)[::rng.choice((1, -1))]
        return Q('verb', (pos, neg), f'Нужно не {neg}, а {pos} эту жидкость при таком давлении?')
    if family == 'year':
        n = rng.randrange(len(EVENTS))
        return Q('year', (n,), f'В каком году было {EVENTS[n][0]}?')
    n = rng.choice(ARTICLES)
    return Q('article', (n,), f'Что говорит статья {n} Налогового кодекса?')


CHATTER = ('Хорошо. Да, я готовился на самом деле.', 'Ну что, давайте задавайте любой вопрос, собственно, готов.', 'Сейчас, подожди, я подумаю.',
           'Маша, закрой дверь, пожалуйста.', 'Ты быстро подсказываешь, молодец.', 'Да, я готовился. Готовился в целом, в целом.', 'Слушай, а ты меня хорошо слышишь?',
           'Так, ну это понятно, идём дальше по билету.', 'Коллеги, у нас ещё десять минут.')
COMMANDS = {'stop': ('Стоп.', 'Стой, подожди.', 'Хватит.'), 'again': ('Повтори.', 'Ещё раз, пожалуйста.'), 'resume': ('Продолжай.', 'Давай дальше.')}
DOUBTS = ('Ты уверен?', 'Точно?', 'Разве?')


class Mind:
    """The text model as an ideal one: it knows what each utterance of this conversation meant (the stand tells it) and answers that, or «—», or a mark of a command."""

    def __init__(self):
        self.meant = {}                   # normalized text -> ('q', Q) | ('cmd', word) | ('doubt', None) | ('fix', Q)

    def learn(self, text, meaning):
        if normalize(text):
            self.meant[normalize(text)] = meaning

    def read(self, text):
        said = normalize(text)
        if said in self.meant:
            return self.meant[said]
        found = [(said.rfind(key) + len(key), len(key), meaning) for key, meaning in self.meant.items() if meaning[0] in ('q', 'fix') and key and key in said]
        return max(found, key=lambda row: row[:2])[2] if found else None          # what was said last of it (a question and its correction: the correction)

    def answer(self, request):
        text = request['input'][-1]['content'][0]['text']
        heard = text.rsplit('Сейчас прозвучало: ', 1)[-1]
        played = re.match(r'Вопрос: (.*)\nТвой ответ: ', text, re.S)
        if heard.startswith('Распознано: '):
            readings = [self.read(part) for part in heard[len('Распознано: '):].split(' / ')]
            meaning = next((m for m in readings if m is not None), None)
        else:
            meaning = self.read(heard)
        if meaning is None:
            return '—'
        kind, value = meaning
        if kind in ('q', 'fix'):
            return value.answer()
        if kind == 'cmd':
            return {'stop': '[стоп]', 'again': '[повтори]', 'resume': '[продолжай]'}[value]
        if kind == 'doubt' and played:
            asked = self.read(played.group(1))
            return asked[1].answer() if asked and asked[0] in ('q', 'fix') else '—'
        return '—'


# =====================================================================================================================================
# the rig: the real chain with the boundaries scripted
# =====================================================================================================================================

class Recognizer:
    """The ear's worker with no thread (test_h3_tempo.Recognizer)."""

    def __init__(self):
        self.state, self.reason, self.sink, self.dropped = 'ready', None, None, []

    def submit(self, sink, uid, op, payload=None):
        self.sink = sink
        if op == 'audio':
            sink._consumed(len(payload))
        elif op == 'drop':
            self.dropped.append(uid)

    def heard(self, uid, text):
        if self.sink is not None:          # c25-c S5: a line begun before a reconnect: its audio went to the old call, this call's ear never heard it
            self.sink._heard(uid, text, 100, None)


class Run:
    """One job of the fast channel: the stand puts what the stream yields, and waits until the job thread has taken it (no sleep, no race of the outcome)."""

    def __init__(self, job, thread, born):
        self.job, self.thread, self.born = job, thread, born
        self.box, self.took = queue.Queue(), threading.Event()

    def stream(self, cancelled):
        while True:
            try:
                kind, value = self.box.get(timeout=0.002)
            except queue.Empty:
                if cancelled.is_set():
                    return
                continue
            if kind == 'delta':
                yield value
                self.took.set()
            elif kind == 'end':
                return
            else:
                raise RuntimeError(value)

    def say(self, text):
        self.took.clear()
        self.box.put(('delta', text))
        while not self.took.wait(0.002):
            if not self.thread.is_alive():
                return

    def end(self, fail=False):
        self.box.put(('fail', 'boom') if fail else ('end', None))
        self.thread.join(2)


class Threads:
    """``fast_text.threading`` as the stand gives it: real threads, each one handed to the stand with its job before it starts."""
    Event, Lock = threading.Event, threading.Lock

    def __init__(self, born):
        self.born = born

    def Thread(self, target, args=(), name=None, daemon=None):                       # noqa: N802 - the name of threading's
        thread = threading.Thread(target=target, args=args, name=name, daemon=True)
        if not args or not hasattr(args[0], 'request'):      # h31: a thread of the channel's own (close, drain, keepalive) is no job of the stand
            return thread
        self.born(args[0], thread)
        return thread


@dataclass
class Said:
    """One utterance of the listener, in seconds of the conversation."""
    n: int
    kind: str                         # question fix doubt repeat partial wrong stop again resume chatter
    text: str
    ear: str
    onset: float
    offset: float
    ear_at: float = None
    final_at: float = None
    meaning: object = None
    cue: object = None                # the cue a repeat is of
    barge: bool = False
    call: int = 1
    created_at: float = None          # when the cloud announced the turn (None: it never did)


@dataclass
class Outcome:
    seed: int
    profile: dict
    said: list = field(default_factory=list)
    cues: list = field(default_factory=list)            # (t, text, revision, index, chunks, cleared, diagnostic, question_id)
    states: list = field(default_factory=list)          # (t, revision, index, completed, waiting, hearing)
    jobs: list = field(default_factory=list)
    reconnects: list = field(default_factory=list)
    growth: list = field(default_factory=list)          # SoundStand: (t, threads, agenda, traced bytes) every GROWTH_EVERY_S of the conversation (U81: what grows along a long call)
    errors: list = field(default_factory=list)
    violations: list = field(default_factory=list)      # (invariant, t, message)
    crash: str = None
    log: list = field(default_factory=list)


def _value(text):
    try:return json.loads(text)
    except ValueError:return text


def profile_of(seed):
    extra = {key: _value(value) for key, value in (item.split('=', 1) for item in os.environ.get('ECHO_REPLAY_FLAGS', '').split(',') if '=' in item)}      # w6-integ: the candidate's flags on top (k=v,k=v)
    return {'local_ear': 'act', 'fast_text': 'on', **extra}      # rule 2 (the ear's release) is the owner's rule, always on: the stand no longer chooses it


class Stand:
    def __init__(self, seed, *, length=90.0, profile=None, cloud=(0.5, 5.0), job=(0.4, 3.0), faults=True):
        self.seed, self.length, self.cloud, self.job_late, self.faults = seed, length, cloud, job, faults
        self.rng = random.Random(seed)
        self.profile = profile or profile_of(seed)
        self.settings = resolve(self.profile)
        self.out = Outcome(seed, dict(self.profile))
        self.mind = Mind()
        self.agenda, self.order = [], 0
        self.runs, self.call = {}, 1
        self.said, self.current, self.stopped, self.following = [], None, False, False
        self.free = 0.0                   # the listener may speak again from here
        self._original = S.host_kwargs, FT.threading
        host = {'repeat_seconds': self.settings['repeat_seconds'], 'max_auto_repeats': self.settings['max_auto_repeats'], 'fast_text': self.settings['fast_text']}
        original = S.host_kwargs
        S.host_kwargs = lambda: {**original(), **host}
        FT.threading = Threads(self._born)
        self.w = S.World(session_id=f'a1-{seed}')
        self.w.wire.synthesize = voice
        self.zero = self.w.clock.now()
        self.audio_zero, self.steps, self.speaking, self.input_clock, self.last_final = 0.0, [], None, [], 0.0
        self._attach()

    # -- the boundaries ------------------------------------------------------------------------------------------------------------
    def _attach(self):
        w = self.w
        self.detector, self.worker = self._detector(), Recognizer()
        self.ear = ear_shadow.for_call(self.settings, w.controller, detector_factory=lambda: self.detector, worker=self.worker, clock=w.clock.now)
        w.wire.ear = self.ear
        self.fast = FT.for_call(self.settings, w.controller, stream=self._stream, instructions=lambda: 'POLICY', wake=lambda: None, clock=w.clock.now)
        w.wire.fast = self.fast
        # w10: what controlled_host sets on the controller from the profile, for the keys a candidate turns on (off by default: nothing changes then)
        w.wire.early.enabled = self.settings.get('ear_lookup') == 'on' or self.profile.get('prefetch') == 'on'                             # the early lookup is the call's rule ``ear_lookup`` (the wire reads it from the controller's modes); the stand's own ``prefetch`` stays a rig switch for the c23 speed sets
        w.controller.turn_mark = self.settings.get('turn_mark') == 'on'                       # c22-speed: as controlled_host sets it
        w.controller.cloud_form = self.settings.get('cloud_form') == 'on'                     # c22-speed: as controlled_host sets it
        w.controller.ear_lookup = self.settings.get('ear_lookup') == 'on'                     # c22-speed: as controlled_host sets it
        w.controller.dictating.said = True if self.profile.get('dictation') == 'on' else None      # the scene's owner has said «диктуй медленно» (dictation is no profile key)

    def _detector(self):
        """The speech detector of the ear: scripted here (what each packet is is the seed's); ``SoundStand`` gives the real one, fed the real sound."""
        return ScriptedDetector([])

    def _stream(self, request, cancelled):
        return self.runs[id(request)].stream(cancelled)

    def _born(self, job, thread):
        """A job started (on the loop): its stream is scripted from here on. Its latency, its failure: the seed's."""
        run = Run(job, thread, self.now())
        self.runs[id(job.request)] = run
        answer = self.mind.answer(job.request)
        r = self.rng
        first = r.uniform(*self.job_late) if r.random() > 0.04 or not self.faults else r.uniform(4.5, 7.0)
        fail = self.faults and r.random() < 0.06
        pieces = [answer] if len(answer) < 12 or r.random() < 0.4 else self._pieces(answer)
        text = job.request['input'][-1]['content'][0]['text']
        heard = text.rsplit('Сейчас прозвучало: ', 1)[-1]
        readings = [self.mind.read(part) for part in heard[len('Распознано: '):].split(' / ')] if heard.startswith('Распознано: ') else []
        parts = heard[len('Распознано: '):].split(' / ') if readings else []
        inside = len(parts) == 2 and any(key in normalize(parts[0]) for key, meaning in self.mind.meant.items() if key and meaning == readings[1])
        mixed = len(readings) == 2 and None not in readings and readings[0] != readings[1] and not inside      # the ear's words are a part of the cloud's: one record
        self.out.jobs.append({'at': round(self.now(), 2), 'heard': text[-160:], 'answer': answer, 'first': round(first, 2), 'fail': fail, 'mixed': mixed})
        at = self.now() + first
        for piece in pieces:
            self.later(at, lambda piece=piece: run.say(piece), call=None)
            at += r.uniform(0.05, 0.4)
        self.later(at, lambda: run.end(fail), call=None)

    @staticmethod
    def _pieces(text):
        words = text.split(' ')
        cut = max(1, len(words) // 2)
        return [' '.join(words[:cut]) + ' ', ' '.join(words[cut:])]

    def close(self):
        try:
            for run in self.runs.values():
                run.box.put(('end', None))
            self.w.close()
            for run in self.runs.values():
                run.thread.join(1)
        finally:
            S.host_kwargs, FT.threading = self._original

    # -- time ----------------------------------------------------------------------------------------------------------------------
    def now(self):
        return self.w.clock.now() - self.zero

    def later(self, at, action, call=0):
        """``call``: 0 the current call (dropped if it is gone by then), None any."""
        self.order += 1
        heapq.heappush(self.agenda, (at, self.order, self.call if call == 0 else None, action))

    def play(self):
        self.later(self.rng.uniform(0.5, 2.0), self.decide)
        while self.now() < self.length:
            while self.agenda and self.agenda[0][0] <= self.now() + 1e-9:
                _, _, call, action = heapq.heappop(self.agenda)
                if call is None or call == self.call:
                    action()
            self._packet()
            self.w.advance(TICK, step=TICK)
            self._sample()
        self._collect()
        return self.out

    def _sample(self):
        c = self.w.controller
        s = c.state() or {}
        row = (round(self.now(), 2), s.get('revision'), s.get('chunk_index'), bool(s.get('completed')), bool(s.get('stream_waiting_next')), bool(c.hearing), self.call)
        if not self.out.states or self.out.states[-1][1:] != row[1:]:
            self.out.states.append(row)

    def _collect(self):
        w = self.w
        self.out.cues = [(round(cue.t - self.zero, 2), cue.text, cue.snap.get('revision'), cue.snap.get('index'), tuple(cue.snap.get('chunks') or ()), cue.cleared, cue.diagnostic,
                          cue.snap.get('question_id')) for cue in w.cues]
        self.out.errors = [frame for frame in w.errors]
        self.out.said = self.said
        if w.violations:
            self.out.violations += [('A0', 0.0, v.split('\n')[0]) for v in w.violations]
        if w.loop_errors:
            self.out.violations.append(('A0', 0.0, f'unhandled error in a wire task: {str(w.loop_errors[0].get("exception") or w.loop_errors[0])[:200]}'))
        self.out.log = w.log[-60:]

    # -- the listener ------------------------------------------------------------------------------------------------------------
    def last_cue(self):
        cues = [c for c in self.w.cues if not c.diagnostic]
        return cues[-1] if cues else None

    def decide(self):
        r, now = self.rng, self.now()
        if self.faults and r.random() < 0.02 and now > 10:
            self.reconnect()
            self.later(now + r.uniform(1.0, 3.0), self.decide)
            return
        cue = self.last_cue()
        playing = self.w.open is not None and not self.w.open.diagnostic
        if playing and r.random() > 0.12:
            self.later(now + 0.2, self.decide)                                           # let it be said to its end
            return
        last = self.said[-1] if self.said else None
        fresh = cue is not None and (last is None or cue.t - self.zero > last.offset) and self.following and not self.stopped
        if self.stopped:
            kind = r.choices(('question', 'chatter', 'resume', 'again', 'silence'), (4, 2, 2, 1, 3))[0]
        elif fresh:
            kind = r.choices(('repeat', 'partial', 'wrong', 'stop', 'doubt', 'question', 'chatter', 'silence', 'fix'), (55, 8, 4, 6, 4, 9, 5, 8, 3))[0]
        else:
            kind = r.choices(('question', 'chatter', 'silence', 'again', 'resume', 'fix'), (45, 20, 20, 4, 4, 5))[0]
        if kind == 'fix' and (self.current is None or self.current.family not in ('money', 'mult')):
            kind = 'question'
        if kind == 'silence':
            self.later(now + r.uniform(2.0, 9.0), self.decide)
            return
        onset = max(now + (r.uniform(0.3, 1.2) if fresh and not playing else r.uniform(0.0, 0.6)), self.free)
        self.later(onset, lambda: self.speak(kind, cue if fresh else None, barge=playing))

    def speak(self, kind, cue, barge=False):
        r = self.rng
        meaning = None
        if kind == 'question':
            q = ask(r, self.current)
            text, meaning = q.text, ('q', q)
            if r.random() < 0.15:
                text = r.choice(CHATTER[:3]) + ' ' + text
        elif kind == 'fix':
            q = self.current
            a, b = q.params
            new = a + r.choice((10, 20, -10)) if a > 20 else a + 10
            q2 = Q(q.family, (new, b), q.text.replace(str(a), str(new), 1))
            text, meaning = f'Нет, не {a}, а {new}.', ('fix', q2)
        elif kind == 'doubt':
            text, meaning = r.choice(DOUBTS), ('doubt', None)
        elif kind in COMMANDS:
            text, meaning = r.choice(COMMANDS[kind]), ('cmd', kind)
        elif kind in ('repeat', 'partial', 'wrong') and cue is not None:
            words = cue.text.split()
            if kind == 'repeat':
                text = cue.text
            elif kind == 'partial':
                text = ' '.join(words[:max(1, min(2, len(words) - 1))])
            else:
                text = re.sub(r'\d+', lambda m: str(int(m.group()) + 7), cue.text, count=1) if re.search(r'\d', cue.text) else ' '.join(words[:-1] + ['капуста'])
        else:
            kind, text = 'chatter', r.choice(CHATTER)
        ear = self.heard_by_ear(text, kind)
        if meaning:
            for said in {text, ear, meaning[1].text if meaning[0] == 'q' else text}:
                self.mind.learn(said, meaning)
                self.mind.learn(self.heard_by_ear(said, kind, exact=True), meaning)
        now = self.now()
        length = max(0.35, len(text.split()) * r.uniform(0.25, 0.42))
        u = Said(len(self.said) + 1, kind, text, ear, round(now, 2), round(now + length, 2), meaning=meaning, cue=cue and (cue.text, cue.snap.get('revision'), cue.snap.get('index')),
                 barge=barge, call=self.call)
        self.said.append(u)
        if kind in ('question', 'fix'):
            self.current, self.stopped, self.following = meaning[1], False, True
        elif kind == 'stop':
            self.stopped = True
        elif kind in ('again', 'resume'):
            self.stopped = False
        self.free = u.offset + 0.15
        self._utter(u)
        gap = r.uniform(0.2, 2.5) if r.random() < 0.8 else r.uniform(3.0, 8.0)
        self.later(u.offset + gap, self.decide)

    def heard_by_ear(self, text, kind, exact=False):
        """The ear's words: lower case, no punctuation, numbers as words mostly; sometimes a word lost, sometimes nothing. ``exact``: only the form (for the mind)."""
        r = self.rng
        words = re.findall(r'[\w-]+', text.lower().replace('ё', 'е'))
        if exact:
            return ' '.join(spell(int(w)) if w.isdigit() else w for w in words)
        if r.random() < 0.03:
            return ''
        if r.random() < 0.7:
            words = [spell(int(w)) if w.isdigit() else w for w in words]
        if len(words) > 4 and r.random() < 0.08:
            gone = r.randrange(len(words))
            if not any(ch.isdigit() for ch in words[gone]) and words[gone] != 'не':
                del words[gone]
        return ' '.join(words)

    def _utter(self, u):
        """The ear's onset, offset and text, the cloud's turn (created, words, final 0.5-5 s late or lost), maybe the cloud's own answer."""
        r = self.rng
        uid = f'u{u.n}'
        box = {}

        def onset():
            self.steps.append(('onset', box))

        def offset():
            self.steps.append(('end', box))

        def text():
            if box.get('ear') is not None:
                u.ear_at = round(self.now(), 2)
                self.worker.heard(box['ear'], u.ear)

        self.later(u.onset, onset)
        self.later(u.offset, offset)
        self.later(u.offset + r.uniform(0.1, 0.5), text)
        self._cloud(u, uid)

    def _cloud(self, u, uid):
        """The cloud's side of one utterance: its turn (created, words, final 0.5-5 s late or lost) and maybe its own answer (shared with ``SoundStand``, which has no scripted onsets)."""
        r = self.rng
        words = u.text.split()
        if r.random() < 0.9:
            created = u.onset + r.uniform(0.2, 1.0)
            def created_now():
                u.created_at = round(self.now(), 2)
                head = self.ms(u.onset) // 200 * 200                             # the provider's input-audio clock, 200 ms grid (tests/fixtures/provider_user_turn_20261025.json)
                self._feed({'type': 'turn.created', 'turn': {'id': uid, 'role': 'user', 'transcript': words[0], 'start_ms': head, 'end_ms': head + 200}})
            self.later(created, created_now)
            for n, word in enumerate(words[1:]):
                at = created + (u.offset - created) * (n + 1) / len(words)
                self.later(at, lambda word=word, n=n: self._feed({**S.turn_delta(uid, ' ' + word, 0), **self.span(u, n + 1, len(words))}))
        if not self.faults or r.random() > 0.04:
            final = max(u.offset + r.uniform(*self.cloud), self.last_final + 0.05)     # the provider finishes its turns in the order they were spoken
            self.last_final = final

            def done():
                u.final_at = round(self.now(), 2)
                done = S.turn_done(uid, 'user', u.text)
                done['turn'].update(start_ms=self.ms(u.onset) // 200 * 200, end_ms=-(-self.ms(u.offset) // 200) * 200)
                self._feed(done)
            self.later(final, done)
            if r.random() < 0.5:
                aid = f'a{u.n}'
                reply = u.meaning[1].answer() if u.meaning and u.meaning[0] in ('q', 'fix') and r.random() < 0.5 else r.choice(CHATTER_OF_THE_CLOUD)
                at = final + r.uniform(0.1, 2.5)
                self.later(at, lambda: self._feed(S.turn_created(aid, 'assistant', '')))
                self.later(at + r.uniform(0.3, 2.0), lambda: self._feed(S.turn_done(aid, 'assistant', reply)))

    def span(self, u, n, of):
        """Where the ``n``-th of ``of`` words of ``u`` was said, on the provider's clock (200 ms grid)."""
        start = self.ms(u.onset + (u.offset - u.onset) * n / of) // 200 * 200
        return {'start_ms': start, 'end_ms': start + 200}

    def ms(self, t):
        """A moment of the conversation on the input-audio clock of the current call: the audio the wire has forwarded by then (it forwards none while the phone's
        microphone is closed under a cue), as the provider counts it."""
        clock = self.input_clock
        at = bisect.bisect_right(clock, (t, float('inf'))) - 1
        if at < 0:
            return 0
        when, ms = clock[at]
        return max(0, int(round(ms + (min(t - when, TICK)) * 1000)))

    def _packet(self):
        """The microphone's 0.1 s of this tick: the detector's step is the onset or end an utterance asked for, else speech or quiet."""
        step, box = self.steps.pop(0) if self.steps else ('speech' if self.speaking else 'quiet', None)
        if step == 'onset' and self.speaking is not None:
            self.detector.script.append('end')
            self.w.client({'type': 'input_audio_buffer.append', 'audio': AUDIO})
        self.detector.script.append(step)
        self.w.client({'type': 'input_audio_buffer.append', 'audio': AUDIO})
        self.input_clock.append((self.now(), self.w.wire.input_ms()))
        if step == 'onset':
            box['ear'], self.speaking = self.ear.current, box
        elif step == 'end':
            if self.speaking is box:
                self.speaking = None
            else:
                self.detector.speaking = self.speaking is not None

    def _feed(self, event):
        self.w.feed(event)

    def reconnect(self):
        self.out.reconnects.append(round(self.now(), 2))
        self.call += 1
        self.w.reconnect()
        self.w.wire.synthesize = voice
        self.audio_zero, self.steps, self.speaking, self.input_clock = self.now(), [], None, []
        self._attach()


# =====================================================================================================================================
# I1: the same conversation from real sound (tools/replay/real_sound.py)
# =====================================================================================================================================

GROWTH_EVERY_S = 60.0


class Fixed:
    """A question of the scene: its words and the answer the ideal mind gives (``Q``'s contract for ``check`` and ``Mind``)."""
    family, params = 'fixed', ()

    def __init__(self, text, answer):
        self.text, self._answer = text, answer

    def answer(self):
        return self._answer

    def allowed(self):
        return None

    def contradicts(self, plan):
        return False

    def fits(self, plan):
        said, ideal = normalize(plan), normalize(self._answer)
        return bool(said) and (ideal.startswith(said) or said.startswith(ideal) or ideal in said)


class SoundStand(Stand):
    """``Stand`` whose listener is a recording: ``audio`` (``real_sound.build``) is cut into packets (``arrivals``) and fed to the wire; the ear's detector is the repo's ``SpeechOnset`` on the real samples. What each
    detected segment says to the recognizer is the labels of the words that lie in it. The cloud's events of an utterance are the stand's own (``_cloud``). Nothing is chosen by the seed but the delays of the cloud and
    the model (and the packets, if ``arrivals`` is not given)."""

    def __init__(self, seed, audio, *, packets=None, length=None, profile=None, cloud=(0.5, 5.0), job=(0.4, 3.0), trace_memory=False, ear=None):
        self.audio, self.watch, self.pos, self._seg, self._used, self._next = audio, None, 0.0, None, set(), 0
        self.packets = list(packets) if packets is not None else RS.arrivals(audio.pcm, rate=audio.rate, seed=seed)
        self._ear_of = ear                              # ``ear(text, item) -> text``: what the real ear made of a segment (default: the labels)
        self._trace = trace_memory and not tracemalloc.is_tracing()
        if self._trace:
            tracemalloc.start()
        super().__init__(seed, length=length or (self.packets[-1].t + 12.0 if self.packets else audio.seconds + 12.0), profile=profile, cloud=cloud, job=job, faults=False)
        self._growth_at = GROWTH_EVERY_S
        try:
            self._plan()
        except Exception:
            self.close()                                # the rig's patches of the host are undone before the refusal goes up
            raise

    def _detector(self):
        self.watch = RS.Watch(self.audio.rate)
        return self.watch

    def _at(self, source_s):
        """When the sound of ``source_s`` reached the controller (the first packet that begins at or after it)."""
        for p in self.packets:
            if p.at >= source_s - 1e-9:
                return p.t
        return self.packets[-1].t if self.packets else source_s

    def _plan(self):
        for n, item in enumerate(self.audio.items, 1):
            kind, text = item.kind, item.text
            if kind in ('question', 'fix'):
                if not item.answer:
                    raise ValueError(f'the scene step {text!r} is a {kind} without an answer')
                meaning = ('q', Fixed(text, item.answer))
            elif kind in COMMANDS:
                meaning = ('cmd', kind)
            elif kind == 'doubt':
                meaning = ('doubt', None)
            elif kind in ('repeat', 'partial', 'chatter'):
                meaning = None
            else:
                raise ValueError(f'unknown kind of a scene step: {kind!r}')
            ear = self.heard_by_ear(text, kind, exact=True)
            cue = (item.of, None, None) if kind in ('repeat', 'partial') and item.of else None
            u = Said(n, kind, text, ear, round(self._at(item.on), 2), round(self._at(item.off), 2), meaning=meaning, cue=cue)
            self.said.append(u)
            if meaning:
                for said in {text, ear}:
                    self.mind.learn(said, meaning)
            self._cloud(u, f'u{n}')

    def decide(self):
        """The listener is the recording: nobody decides."""

    def _packet(self):
        now = self.now()
        chunk, end = bytearray(), None
        while self._next < len(self.packets) and self.packets[self._next].t <= now + 1e-9:
            p = self.packets[self._next]
            self._next += 1
            chunk += p.data
            end = p.at + len(p.data) / 2 / self.audio.rate
        if chunk:
            self.pos = end
            self.w.client({'type': 'input_audio_buffer.append', 'audio': base64.b64encode(bytes(chunk)).decode('ascii')})
            for event in self.watch.take():
                if event == 'onset':
                    self._close()
                    self._seg = {'uid': self.ear.current, 'from': self.pos}
                else:
                    self._close()
        self.input_clock.append((now, self.w.wire.input_ms()))

    def _close(self):
        """A segment of speech ended: the recognizer's worker hears the labels of the words inside it, a little later."""
        seg, self._seg = self._seg, None
        if seg is None or seg['uid'] is None:
            return
        lo, hi = seg['from'] - 0.45, self.pos
        got = []
        for u, item in zip(self.said, self.audio.items):
            for k, (token, on, off) in enumerate(item.words):
                if (id(item), k) not in self._used and lo <= (on + off) / 2 <= hi:
                    self._used.add((id(item), k))
                    got.append((u, item, token))
        text = self.heard_by_ear(' '.join(t for _, _, t in got), 'chatter', exact=True)
        owner = max({id(u): u for u, _, _ in got}.values(), key=lambda u: sum(1 for g in got if g[0] is u), default=None)
        if self._ear_of is not None and owner is not None:
            text = self._ear_of(text, owner)
        uid = seg['uid']

        def heard():
            if owner is not None and owner.ear_at is None:
                owner.ear_at = round(self.now(), 2)
            self.worker.heard(uid, text)
        self.later(self.now() + self.rng.uniform(0.1, 0.5), heard)

    def _sample(self):
        super()._sample()
        if self.now() >= self._growth_at:
            self._growth_at += GROWTH_EVERY_S
            self.out.growth.append({'t': round(self.now(), 1), 'threads': threading.active_count(), 'agenda': len(self.agenda), 'traced': tracemalloc.get_traced_memory()[0] if tracemalloc.is_tracing() else None})

    def close(self):
        try:
            super().close()
        finally:
            if self._trace and tracemalloc.is_tracing():
                tracemalloc.stop()


def run_sound(seed, audio, **keywords):
    """``run`` for a recording: the conversation of ``audio`` through the real chain; the record and its violations (A0-A9)."""
    stand = SoundStand(seed, audio, **keywords)
    try:
        try:
            stand.play()
        except Exception as error:                     # noqa: BLE001 - a crash of the chain is a finding
            import traceback
            stand.out.crash = ''.join(traceback.format_exception(error))[-1500:]
            stand.out.violations.append(('A0', round(stand.now(), 2), f'{type(error).__name__}: {error}'[:300]))
            stand._collect()
    finally:
        stand.close()
    out = stand.out
    out.violations += check(out)
    return out


def decisions(out):
    """The decision and the time of each utterance of a conversation: ``[{n, kind, text, offset, ear_at, final_at, first_cue, first_cue_at, after_offset_s, layer}]``. The times are the stand's order of events on a
    virtual clock («серверный слой», no phone, no network): a measurement of nothing but the controller's own holds. The `layer` marks these times as the server layer, not the audible delay, until a second-phone recording or client playback marks exist."""
    rows, cues = [], [c for c in out.cues if not c[6]]
    for u, nxt in zip(out.said, out.said[1:] + [None]):
        until = nxt.onset if nxt else float('inf')
        first = next((c for c in cues if u.offset - 0.5 <= c[0] < until), None)
        rows.append({'n': u.n, 'kind': u.kind, 'text': u.text, 'offset': u.offset, 'ear_at': u.ear_at, 'final_at': u.final_at, 'first_cue': first[1] if first else None,
                     'first_cue_at': first[0] if first else None, 'after_offset_s': round(first[0] - u.offset, 2) if first else None, 'layer': 'серверный слой'})
    return rows


# =====================================================================================================================================
# the invariants, over the record
# =====================================================================================================================================

def check(out, *, hold=ONSET_HOLD_MAX_S):
    v = []
    said = out.said
    cues = [c for c in out.cues if not c[6]]
    questions = [u for u in said if u.kind in ('question', 'fix') and (u.final_at is not None or u.ear_at is not None)]

    def known(u):
        """When the system had the utterance: the cloud's final, or the ear's text when the cloud lost it."""
        return u.final_at if u.final_at is not None else u.ear_at

    def plan(c):
        return ' '.join(c[4])

    def asked_before(t):
        before = sorted((u for u in questions if known(u) <= t + 1e-6), key=known)
        return before[-1] if before else None

    def followed(after, before_t, text):
        """Did the listener, after ``after``, repeat (or try) a portion of ``text`` they had heard: they took that answer back themselves."""
        return any(u.kind in ('repeat', 'partial', 'wrong') and u.cue and after < u.onset < before_t and normalize(u.cue[0]) and normalize(u.cue[0]) in normalize(text) for u in said)

    def just_before(q, t, text):
        """A cue begun within GRID of the moment the system had ``q`` may still be the answer of the question before it."""
        if known(q) <= t - GRID:
            return False
        before = sorted((u for u in questions if known(u) < known(q)), key=known)
        return bool(before) and before[-1].meaning[1].fits(text)

    def restarted(after, before_t, kinds):
        return any(u.kind in kinds and after < u.onset and (known(u) or u.offset) <= before_t for u in said)

    # A9 the job is given the cloud's words of one utterance and the ear's of another as two records of the same (H6 item 3, ``also``)
    for job in out.jobs:
        if job.get('mixed'):
            v.append(('A9', job['at'], f'one request, two utterances: {job["heard"][-120:]!r}'))

    # A0 the wire
    for frame in out.errors:
        code = (frame.get('error') or {}).get('code')
        if code != 'controlled_answer_timeout':
            v.append(('A0', 0.0, f'error frame {code}'))

    # A6 no sound begins over unfinished speech (the cue's start inside an utterance, later than a ready cue may hold)
    for c in cues:
        for u in said:
            if u.onset + hold + GRID < c[0] < u.offset - 1e-6:
                cloud = u.created_at is not None and u.created_at <= c[0]
                v.append(('A6' if cloud else 'A6o', c[0], f'cue {c[1]!r} began at {c[0]} inside utterance {u.n} {u.text!r} ({u.onset}-{u.offset})'))

    # A2 / A7 / A8 every answer said agrees with the last question the system had; nothing of an older one; no cloud chatter
    for c in cues:
        text = plan(c)
        if any(normalize(chat) and normalize(chat) in normalize(text) for chat in CHATTER_OF_THE_CLOUD):
            v.append(('A8', c[0], f'the cloud\'s chatter said: {c[1]!r}'))
        q = asked_before(c[0])
        if q is None or restarted(q.onset, c[0] + 1e-6, ('resume', 'again')) or followed(q.onset, c[0], text):
            continue
        truth = q.meaning[1]
        if truth.fits(text) or just_before(q, c[0], text):
            continue
        if any(u.onset > q.onset and u.ear_at is not None and u.ear_at <= c[0] and u.meaning[1].fits(text) for u in questions):
            continue                           # a newer question the ear opened (H4 rule 2) before the cloud's final
        older = [u for u in questions if known(u) < known(q) and u.meaning[1].fits(text)]
        if older:
            v.append(('A2', c[0], f'cue {c[1]!r} of plan {text!r} answers the older question {older[-1].n} {older[-1].text!r}, '
                                  f'after question {q.n} {q.text!r} (known at {known(q)})'))
        elif truth.contradicts(text):
            v.append(('A7', c[0], f'cue {c[1]!r} of plan {text!r} contradicts question {q.n} {q.text!r}'))

    # A2e the same by the ear: an answer to an older question begun after the ear had the text of a new one (its cloud final still to come)
    for c in cues:
        heard = [u for u in questions if u.ear_at is not None and u.ear and u.ear_at + GRID < c[0] < (known(u) if u.final_at else min([x.onset for x in questions if x.onset > u.onset] + [float('inf')]))]       # a lost final closes the window at the next question, not at the end of the call
        for u in heard[-1:]:
            if not u.meaning[1].fits(plan(c)) and any(x.meaning[1].fits(plan(c)) for x in questions if x.onset < u.onset) and not restarted(u.onset, c[0], ('resume', 'again')):
                v.append(('A2e', c[0], f'cue {c[1]!r} of another question begun after the ear heard question {u.n} {u.text!r} at {u.ear_at} (its final at {u.final_at})'))

    # A2 after «стоп»: nothing until a new question, «повтори», «продолжай» (from the moment the system had the stop)
    for u in said:
        heard = min([t for t in (u.ear_at if u.ear else None, u.final_at) if t is not None] or [None]) if u.kind == 'stop' else None
        if heard is None:
            continue                           # the ear acts on a stop by itself: the system has it from the earlier of the two
        nxt = [x for x in said if x.n > u.n and x.kind in ('question', 'fix', 'again', 'resume', 'doubt')]
        until = (nxt[0].onset if nxt else float('inf'))
        for c in cues:
            if heard + GRID < c[0] < until:
                v.append(('A2', c[0], f'cue {c[1]!r} after «стоп» (utterance {u.n}, had at {heard})'))
                break

    # A3 the cursor: within a revision the index never goes back or jumps; each advance has its own utterance after the portion was said
    last, used = {}, set()
    for t, rev, index, completed, waiting, hearing, call in out.states:
        if rev is None or index is None:
            continue
        before = last.get(rev)
        if before is not None:
            if index < before[1]:
                v.append(('A3', t, f'revision {rev}: index went back {before[1]} -> {index}'))
            elif index > before[1] + 1:
                v.append(('A3', t, f'revision {rev}: index jumped {before[1]} -> {index}'))
            elif index == before[1] + 1:
                spoken = [c for c in cues if c[2] == rev and c[3] == before[1] and c[0] <= t]
                since = spoken[0][0] if spoken else before[0]
                own = [u for u in said if since - 0.5 < u.onset <= t and u.n not in used]
                if not own:
                    v.append(('A3', t, f'revision {rev}: advance {before[1]} -> {index} with no utterance of its own since the portion was said at {since}'))
                else:
                    used.add(own[0].n)
        last[rev] = (t, index)

    # A4 a plan does not come back by itself: a cue of a plan another answer replaced, with no request to come back in between
    seen = []                                  # (plan text, first t, revision)
    for c in cues:
        text = normalize(plan(c))
        if not text:
            continue
        same = [s for s in seen if s[0] and (text.startswith(s[0][:40]) or s[0].startswith(text[:40]))]
        if same and seen[-1] is not same[-1]:
            left = seen[seen.index(same[-1]) + 1][1]
            if not restarted(left - 30.0, c[0], ('resume', 'again', 'doubt', 'question', 'fix')):
                v.append(('A4', c[0], f'plan {plan(c)!r} came back at {c[0]} with no request after it was left at {left}'))
        if not seen or seen[-1][0] != text and not (same and seen[-1] is same[-1]):
            seen.append((text, c[0], c[2]))

    # A5 bounded waits: an asked question is answered (or reported) unless the listener speaks again first; the flag of speech falls; no endless repeats on its own
    for u in questions:
        start = known(u)
        nxt = [x for x in said if x.onset > u.onset]
        until = nxt[0].onset if nxt else out_end(out)
        bound = start + ANSWER_WAIT_SECONDS + 3.5
        if until > bound and not any(start - 0.5 <= c[0] <= bound for c in out.cues) and u.call == (nxt[0].call if nxt else u.call):
            if not any(start < t <= bound for t in out.reconnects):
                v.append(('A5', bound, f'question {u.n} {u.text!r} known at {start}: no cue and no report in {ANSWER_WAIT_SECONDS + 3.5:g} s'))
    flag = None
    for t, rev, index, completed, waiting, hearing, call in out.states:
        if hearing and flag is None:
            flag = t
        elif not hearing:
            flag = None
        if flag is not None and t - flag > 1.0:
            speaking = [u for u in said if u.onset - 1.0 <= t <= max(u.offset, known(u) or u.offset) + HEARING_SECONDS + 1.0]
            if not speaking and t - flag > HEARING_SECONDS + 6.0:
                v.append(('A5', t, f'the flag of speech has stood since {flag} with nobody speaking'))
                flag = None
    runs = {}
    for c in cues:
        key = (c[2], c[3])
        between = [u for u in said if runs.get('t', -1) < u.onset <= c[0]]
        if runs.get('key') == key and not between:
            runs['n'] += 1
            if runs['n'] == 4:
                v.append(('A5', c[0], f'portion {c[1]!r} said {runs["n"]} times in a row with nobody speaking'))
        else:
            runs.update(key=key, n=1)
        runs['t'] = c[0]

    # A1 one utterance, at most one answer: between two questions (a doubt may give the answer again, a revised one), the distinct plans begun that agree with the question.
    # The roads' provisional sentence (``REFUSAL``, F20) is the honest failure phrase said at the question's due, no answer: the real text that takes its place is the one answer
    asks = [u for u in said if u.kind in ('question', 'fix', 'doubt', 'resume', 'again')]
    for u, nxt in zip(asks, asks[1:] + [None]):
        truth = u.meaning[1] if u.kind in ('question', 'fix') else None
        if truth is None:
            continue
        begun = []
        for c in cues:
            if u.onset <= c[0] < (nxt.onset if nxt else float('inf')) and c[3] == 0 and (truth.fits(plan(c)) or not any(x.meaning[1].fits(plan(c)) for x in questions)):
                text = normalize(plan(c))
                if text and not (text.startswith(normalize(REFUSAL)) or normalize(REFUSAL).startswith(text)) and not any(text.startswith(x[:30]) or x.startswith(text[:30]) for x in begun):
                    begun.append(text)
        if len(begun) > 1:
            v.append(('A1', u.onset, f'{len(begun)} answers to utterance {u.n} {u.text!r}: {begun}'))
    return v


def out_end(out):
    return max([out.states[-1][0] if out.states else 0.0] + [c[0] for c in out.cues])


def run(seed, **keywords):
    stand = Stand(seed, **keywords)
    try:
        try:
            stand.play()
        except Exception as error:                     # noqa: BLE001 - a crash of the chain is a finding, not a crash of the fuzzer
            import traceback
            stand.out.crash = ''.join(traceback.format_exception(error))[-1500:]
            stand.out.violations.append(('A0', round(stand.now(), 2), f'{type(error).__name__}: {error}'[:300]))
            stand._collect()
    finally:
        stand.close()
    out = stand.out
    out.violations += check(out)
    return out


def describe(out, limit=30):
    lines = [f'seed {out.seed} profile {out.profile}']
    events = [(u.onset, f'  {u.onset:6.2f}-{u.offset:6.2f} said#{u.n} {u.kind:8} {u.text!r} ear@{u.ear_at} final@{u.final_at} call{u.call}') for u in out.said]
    events += [(c[0], f'  {c[0]:6.2f} CUE  {c[1]!r} rev{c[2]}/{c[3]} {"cut" if c[5] else ""}{"diag" if c[6] else ""}') for c in out.cues]
    events += [(j['at'], f'  {j["at"]:6.2f} job  {j["heard"][-70:]!r} -> {j["answer"]!r} +{j["first"]}{" FAIL" if j["fail"] else ""}') for j in out.jobs]
    events += [(t, f'  {t:6.2f} RECONNECT') for t in out.reconnects]
    lines += [line for _, line in sorted(events, key=lambda e: e[0])]
    lines += [f'  !! {inv} @{t}: {msg}' for inv, t, msg in out.violations[:limit]]
    return '\n'.join(lines)


def logged(seed, lo, hi, **keywords):
    """The conversation of ``seed`` with the controller's own log lines between ``lo`` and ``hi`` seconds, each with the stand's time: the way to the first cause of a finding."""
    import logging
    lines, box = [], {}

    class Catch(logging.Handler):
        def emit(self, record):
            stand = box.get('stand')
            t = stand.now() if stand and hasattr(stand, 'zero') else -1.0
            if lo <= t <= hi:
                lines.append((t, f'  {t:6.2f} log  {record.getMessage()[:240]}'))
    handler, root = Catch(), logging.getLogger()
    level = root.level
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    original = Stand.__init__

    def init(self, *a, **k):
        box['stand'] = self
        original(self, *a, **k)
    Stand.__init__ = init
    try:
        out = run(seed, **keywords)
    finally:
        Stand.__init__ = original
        root.removeHandler(handler)
        root.setLevel(level)
    text = describe(out).split('\n')
    body = [(float(line.split()[0].split('-')[0]), line) for line in text[1:] if not line.lstrip().startswith('!!')]
    body = [row for row in body if lo - 5 <= row[0] <= hi] + lines
    return '\n'.join([text[0]] + [line for _, line in sorted(body, key=lambda row: row[0])] + [line for line in text if line.lstrip().startswith('!!')])


if __name__ == '__main__':
    import time
    began = time.time()
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    if len(sys.argv) > 3:
        print(logged(seed, float(sys.argv[2]), float(sys.argv[3])))
    else:
        print(describe(run(seed)))
    print(f'{time.time() - began:.1f} s wall')
