"""Helpers of tests/test_t_new_classes.py (WAVE 2 / Task T-B: the V3 classes N01-N20, the metamorphic group).

Test code only. Nothing here re-implements the product: the controller is ``ControlledMedia`` built with the keywords that
``echo_sync/controlled_host.py`` passes (read from its source), over the real ``EchoEngine`` + SQLite file, and the wire tests
use the real ``NativeMediaSocket`` (through ``helpers_s6_state.World``). Fakes exist only at the boundary: the clock, the cloud
(provider events are plain dicts), the public lookup, SAPI synthesis (PCM), the websocket.

Two drivers:
  ``CtlScene``   the controller driven with provider events and a fake clock; the transport (the part of NativeMediaSocket that
                 tells the controller when a cue starts and ends) is emulated exactly as tests/test_cue_in_flight.py does it.
  ``WireScene``  the same verbs over ``World``: the real NativeMediaSocket frames, pacing, cancel and ``output_audio_buffer.clear``.

A scenario is DISTINCT when the event trace it fed to the production code (event type, role, text, delta shape, time offsets;
never ids) is different from every other one of its class: ``REGISTRY`` counts hashes of traces, not labels.

Oracles (``vowel_syllables``, ``unsupported_specifics``, ``latency_report``, ``judge_sensitivity`` ...) are independent of
the production code on purpose: they are what the generators judge it by.
"""
from __future__ import annotations

import collections
import contextlib
import hashlib
import json
import os
import re
import shutil
import tempfile
import warnings
from array import array
from dataclasses import dataclass, field
from pathlib import Path

import pytest

import helpers_s6_seg as G
import helpers_s6_state as S
from echo_sync.controlled_media import ControlledMedia
from helpers_t_new_packs import BY_KEY, DEV, HOLDOUT, MARKERS, PACKS, SUBJECT_WORDS, Pack

turn_created, turn_done, turn_delta = S.turn_created, S.turn_done, S.turn_delta
SOURCE_ROWS = [{'url': 'https://example.org/reference', 'text': 'Reference excerpt for the fake lookup.'}]
SESSION = 'native-probe-' + 'b' * 32

# --------------------------------------------------------------------------------------------------------------------------
# holdout gate: a marker + a default skip, without a conftest (so that nothing shared with the other test agents changes)
# --------------------------------------------------------------------------------------------------------------------------

with warnings.catch_warnings():
    warnings.simplefilter('ignore')          # «Unknown pytest.mark.holdout»: the marker is registered by the integrator's pytest.ini
    HOLDOUT_MARK = pytest.mark.holdout
SKIP_UNLESS_HOLDOUT = pytest.mark.skipif("'holdout' not in (config.getoption('markexpr') or '')",
                                         reason='holdout scenario: run with  -m holdout  (never look at it while changing tests)')
HOLD = (HOLDOUT_MARK, SKIP_UNLESS_HOLDOUT)


def params(items, *, key=lambda item: item.key, group=lambda item: item.group):
    """pytest params of a pool whose items carry a group: ``holdout`` items are marked and skipped by default."""
    return [pytest.param(item, id=str(key(item)), marks=HOLD if group(item) == 'holdout' else ()) for item in items]


def pack_params(only=None):
    return params([p for p in PACKS if only is None or p.key in only])


# --------------------------------------------------------------------------------------------------------------------------
# the registry of executed scenarios
# --------------------------------------------------------------------------------------------------------------------------

class Registry:
    def __init__(self):
        self.rows = []                         # (class, key, trace hash, group)

    def add(self, cls, key, trace, group='dev'):
        digest = hashlib.sha1(json.dumps(trace, ensure_ascii=False, default=str).encode('utf-8')).hexdigest()[:16]
        self.rows.append((cls, tuple(map(str, key)), digest, group))

    def add_unit(self, cls, key, inputs, group='dev'):
        """A scenario of a pure production function (UNIT level): its inputs are its trace."""
        self.add(cls, ('unit',) + tuple(key), [('unit',) + tuple(map(str, inputs))], group)

    def distinct(self, cls=None, group=None):
        return len({(c, h) for c, _, h, g in self.rows if (cls is None or c == cls) and (group is None or g == group)})

    def executed(self, cls=None, group=None):
        return sum(1 for c, _, _, g in self.rows if (cls is None or c == cls) and (group is None or g == group))

    def labels_distinct(self):
        """Every (class, label) pair was run once: the same label twice would be a retry."""
        seen = collections.Counter((c, k) for c, k, _, _ in self.rows)
        return [pair for pair, n in seen.items() if n > 1]

    def classes(self):
        return sorted({c for c, _, _, _ in self.rows})

    def summary(self):
        by = {c: (self.executed(c), self.distinct(c)) for c in self.classes()}
        return by, self.executed(), self.distinct()

    def dump(self, path):
        data = [{'class': c, 'key': list(k), 'trace': h, 'group': g} for c, k, h, g in self.rows]
        Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')


REGISTRY = Registry()


# --------------------------------------------------------------------------------------------------------------------------
# the controller-level scene
# --------------------------------------------------------------------------------------------------------------------------

class Clock:
    def __init__(self, start=1000.0):
        self.t = float(start)

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds
        return self.t


def _brief(event):
    kind = event.get('type')
    turn = event.get('turn') if isinstance(event.get('turn'), dict) else {}
    return (kind, turn.get('role'), turn.get('transcript', event.get('delta', '')))


class CtlScene:
    """``ControlledMedia`` as the host builds it, driven with provider events and a fake clock (one call, one question at a time).

    The transport is emulated like tests/test_cue_in_flight.py does: the first PCM frame (``cue_started``), the end of the voice
    (``voiced`` s later) and the end of the PCM (``tail`` s after that, ``playback_done``). A cue is held while the controller
    believes the listener speaks (NativeMediaSocket ``pending_cue``) and released by the next event or tick.
    """
    TAIL = 0.78

    def __init__(self, cls, key, *, group='dev', settings=None, voiced=0.6, tail=None, session=SESSION, play=True, directory=None, **host):
        self.cls, self.key, self.group = cls, tuple(key), group
        self.dir = Path(tempfile.mkdtemp(prefix='tb-')) if directory is None else Path(directory)
        self._own_dir = directory is None
        self.clock = Clock()
        self.t0 = self.clock()
        self.voiced, self.tail, self.play, self.session = voiced, self.TAIL if tail is None else tail, play, session
        self.host = dict(S.host_kwargs())
        self.host.update(host)
        if settings is not None:
            self.host['settings'] = settings
        self.c = None
        self.trace = []
        self.cues, self.cue_log, self.actions, self.lookups, self.contexts = [], [], [], [], []
        self.pending = None
        self.n = 0
        self.errors = []
        self._mark = 0
        self._checkpointed = False
        self.open_call()

    # -- the call -----------------------------------------------------------------------------------------------------

    def open_call(self):
        """A new ControlledMedia over the same database (a new call: new nonce, empty ledger)."""
        self.c = ControlledMedia(self.dir / 'controlled-state.sqlite3', session_id=self.session, clock=self.clock, **self.host)
        self.c.engine.clock = self.clock
        self.pending = None

    def reconnect(self):
        self.trace.append(('reconnect',))
        self.open_call()

    def close(self):
        if self._own_dir:
            shutil.rmtree(self.dir, ignore_errors=True)

    def checkpoint(self, *label):
        """Register what was fed since the previous checkpoint as ONE distinct scenario (key + label): the segment of the trace and
        the state it ran against (revision, cursor, the portion that waited). Used by dictations that make several independent
        attempts at successive portions (every failed attempt leaves the state as it was, the join window is let to expire)."""
        state = self.state()
        signature = ('state', state.get('revision'), state.get('chunk_index'), tuple(state.get('chunks') or ()))
        REGISTRY.add(self.cls, self.key + tuple(label), self.trace[self._mark:] + [signature], self.group)
        self._mark = len(self.trace)
        self._checkpointed = True

    def finish(self):
        if not self._checkpointed:
            REGISTRY.add(self.cls, self.key, self.trace, self.group)
        self.close()

    # -- plumbing ------------------------------------------------------------------------------------------------------

    def tid(self, prefix='u'):
        self.n += 1
        return f'{prefix}{self.n}'

    def elapse(self, seconds):
        self.clock.advance(seconds)
        self.trace.append(('dt', round(seconds, 2)))

    def _release(self):
        if self.pending is not None and not self.c.hearing and self.c.authorized(self.pending):
            cue, self.pending = self.pending, None
            self._play(cue)

    def _play(self, cue):
        if not self.c.authorized(cue):
            return
        self.cues.append(cue['text'])
        self.cue_log.append((round(self.clock() - self.t0, 3), cue['text'], cue['revision'], cue['index']))
        if not self.play:
            return
        start = self.clock()
        self.c.cue_started(cue, voiced_seconds=self.voiced)
        self.clock.advance(self.voiced + self.tail)
        self.c.playback_done(cue, now=self.clock(), voiced_until=start + self.voiced)

    def absorb(self, actions):
        for action in actions:
            self.actions.append(action)
            kind = action['type']
            if kind == 'speak':
                if self.c.hearing:
                    self.pending = action
                else:
                    self._play(action)
            elif kind == 'cancel':
                self.pending = None
            elif kind == 'lookup':
                self.lookups.append(action)
            elif kind == 'context':
                self.contexts.append(action)
        self._release()
        return actions

    def feed(self, event):
        self.trace.append(('ev', *_brief(event), round(self.clock() - self.t0, 2)))
        return self.absorb(self.c.provider(event))

    def tick(self, seconds, step=0.1):
        """The host ticks every 0.1 s: ``seconds`` of silence."""
        self.trace.append(('tick', round(seconds, 2)))
        out, left = [], float(seconds)
        while left > 1e-9:
            piece = min(step, left)
            self.clock.advance(piece)
            left -= piece
            out += self.absorb(self.c.tick(now=self.clock()))
        return out

    # -- the user ------------------------------------------------------------------------------------------------------

    def start_speaking(self, tid, text=''):
        self.c.speech_started()
        self.trace.append(('speech_started',))
        return self.feed(turn_created(tid, 'user', text))

    def say(self, text, *, gap=0.8, partial=True, tid=None):
        """One user utterance as NativeMediaSocket.provider feeds it: speech start, turn.created, turn.done."""
        if gap:
            self.elapse(gap)
        tid = tid or self.tid('u')
        if partial:
            self.start_speaking(tid)
        return self.feed(turn_done(tid, 'user', text))

    def ask(self, question, *, tid=None, partial=True, rows=None, ground=True):
        """The question; when it needs the lookup (a ``lookup`` action) and ``ground``, the lookup comes back at once with ``rows``
        and the sources are delivered, as NativeMediaSocket does it."""
        tid = tid or self.tid('q')
        if partial:
            self.start_speaking(tid)
        actions = self.feed(turn_done(tid, 'user', question))
        if ground and any(a['type'] == 'lookup' for a in actions):
            actions = actions + self.ground(rows)
        return tid, actions

    def ground(self, rows=None, epoch=None, deliver=True):
        """The lookup returned ``rows`` (for ``epoch``, the current one by default); ``deliver``: the sources reached the model."""
        epoch = self.c.epoch if epoch is None else epoch
        rows = SOURCE_ROWS if rows is None else rows
        self.trace.append(('ground', epoch - self.c.epoch, json.dumps(rows, ensure_ascii=False, sort_keys=True), deliver))
        actions = self.absorb(self.c.grounding(epoch, rows))
        for action in actions:
            if action['type'] == 'context' and deliver:
                self.c.delivery_sent(action['epoch'], action.get('delegation_id'))
        return actions

    def deliver(self, epoch=None):
        """The sources reached the model (NativeMediaSocket sends the context frames)."""
        epoch = self.c.epoch if epoch is None else epoch
        self.trace.append(('deliver', epoch - self.c.epoch))
        return self.c.delivery_sent(epoch, None)

    def cue_in_flight(self, cue, voiced):
        """The transport sent the first PCM frame of ``cue``; its voice lasts ``voiced`` s (the playback is driven by the test)."""
        self.trace.append(('cue_started', round(voiced, 2)))
        self.c.cue_started(cue, voiced_seconds=voiced)

    # -- the cloud -----------------------------------------------------------------------------------------------------

    def answer(self, text, *, tid=None, shape='whole', gap=0.0, delta_gap=0.0):
        """The cloud's answer. ``shape``: ``whole`` (one turn.done), ``words`` (created + a delta per word + done),
        ``chars`` (5-character deltas), or ``split:K`` (the first K words created, the rest as ONE later delta ``gap`` s after).
        ``delta_gap``: seconds of the (fake) clock between two deltas."""
        tid = tid or self.tid('a')
        if shape == 'whole':
            return tid, self.feed(turn_done(tid, 'assistant', text))
        pieces = re.findall(r'\s*\S+', text)
        if shape.startswith('split:'):
            k = int(shape.split(':')[1])
            pieces = [''.join(pieces[:k]), ''.join(pieces[k:])]
        elif shape == 'chars':
            pieces = [text[i:i + 5] for i in range(0, len(text), 5)]
        out = list(self.feed(turn_created(tid, 'assistant', pieces[0])))
        for number, piece in enumerate(pieces[1:], 1):
            if gap and shape.startswith('split:'):
                self.elapse(gap)
            elif delta_gap:
                self.elapse(delta_gap)
            out += self.feed(turn_delta(tid, piece, number))
        out += self.feed(turn_done(tid, 'assistant', text))
        return tid, out

    # -- observation ---------------------------------------------------------------------------------------------------

    def state(self):
        return self.c.state() or {}

    @property
    def chunks(self):
        return list(self.state().get('chunks') or [])

    @property
    def idx(self):
        return self.state().get('chunk_index')

    @property
    def revision(self):
        return self.state().get('revision')

    @property
    def completed(self):
        return bool(self.state().get('completed'))

    def current(self):
        state = self.state()
        if not state or state.get('completed') or state.get('pending_turn') or state.get('stream_waiting_next'):
            return None
        chunks, index = state.get('chunks') or [], state.get('chunk_index', 0)
        return chunks[index] if 0 <= index < len(chunks) else None

    def walk(self, limit=60, wrong=None, gap=0.8):
        """The listener repeats every portion in turn (word for word) until the answer is complete; ``wrong(portion)`` may return a
        different text for a portion (then that is what is heard instead, once)."""
        for _ in range(limit):
            portion = self.current()
            if portion is None:
                break
            heard = wrong(portion) if wrong else None
            self.say(heard if heard else portion, gap=gap)
            if heard and self.current() == portion:
                self.say(portion, gap=gap)
        return list(self.cues)


@contextlib.contextmanager
def ctl(cls, *key, **kwargs):
    scene = CtlScene(cls, key, **kwargs)
    try:
        yield scene
    finally:
        scene.finish()


# --------------------------------------------------------------------------------------------------------------------------
# the wire-level scene
# --------------------------------------------------------------------------------------------------------------------------

class VoicedWorld(S.World):
    """World whose synthesizer returns a voiced PCM of ``voiced_seconds`` followed by ``tail_seconds`` of silence."""
    voiced_seconds = 0.2
    tail_seconds = 0.0

    async def _synthesize(self, text):
        self.synth_calls.append(text)
        if self.hold:
            await self.gate.wait()
        voiced = int(self.voiced_seconds * 24000) // 480 * 480
        tail = int(self.tail_seconds * 24000) // 480 * 480
        return array('h', [1000] * voiced + [0] * tail).tobytes()


class WireScene:
    """The production wire (NativeMediaSocket over ControlledMedia over EchoEngine) with the same verbs as ``CtlScene``."""

    def __init__(self, cls, key, *, group='dev', voiced=None, tail=None):
        self.cls, self.key, self.group = cls, tuple(key), group
        self.w = VoicedWorld(session_id='tb-wire')
        if voiced is not None:
            self.w.voiced_seconds = voiced
        if tail is not None:
            self.w.tail_seconds = tail
        self.trace = []
        self.n = 0
        self._mark = 0
        self._checkpointed = False

    def checkpoint(self, *label):
        state = self.state()
        signature = ('state', state.get('revision'), state.get('chunk_index'), tuple(state.get('chunks') or ()))
        REGISTRY.add(self.cls, self.key + tuple(label), self.trace[self._mark:] + [signature], self.group)
        self._mark = len(self.trace)
        self._checkpointed = True

    def finish(self):
        if not self._checkpointed:
            REGISTRY.add(self.cls, self.key, self.trace, self.group)
        self.w.close()

    def tid(self, prefix='u'):
        self.n += 1
        return f'{prefix}{self.n}'

    @property
    def c(self):
        return self.w.controller

    def feed(self, event, settle=True):
        self.trace.append(('ev', *_brief(event), round(self.w.clock.t - S.START_TIME, 2)))
        return self.w.feed(event, settle=settle)

    def client(self, event):
        self.trace.append(('client', event.get('type')))
        return self.w.client(event)

    def elapse(self, seconds):
        self.w.clock.advance(seconds)
        self.trace.append(('dt', round(seconds, 2)))

    def tick(self, seconds, step=0.5):
        self.trace.append(('tick', round(seconds, 2)))
        return self.w.advance(seconds, step=step)

    def say(self, text, *, gap=0.8, partial=True, tid=None):
        if gap:
            self.elapse(gap)
        tid = tid or self.tid('u')
        out = []
        if partial:
            out += self.feed(turn_created(tid, 'user', ''))
        return out + self.feed(turn_done(tid, 'user', text))

    def ask(self, question, *, partial=True):
        tid = self.tid('q')
        if partial:
            self.feed(turn_created(tid, 'user', ''))
        self.feed(turn_done(tid, 'user', question))
        return tid

    def answer(self, text, *, tid=None, shape='whole'):
        tid = tid or self.tid('a')
        if shape == 'whole':
            self.feed(turn_done(tid, 'assistant', text))
            return tid
        pieces = re.findall(r'\s*\S+', text)
        self.feed(turn_created(tid, 'assistant', pieces[0]))
        for number, piece in enumerate(pieces[1:], 1):
            self.feed(turn_delta(tid, piece, number))
        self.feed(turn_done(tid, 'assistant', text))
        return tid

    # -- observation ---------------------------------------------------------------------------------------------------
    def state(self):
        return self.w.state() or {}

    @property
    def idx(self):
        return self.state().get('chunk_index')

    @property
    def chunks(self):
        return list(self.state().get('chunks') or [])

    @property
    def completed(self):
        return bool(self.state().get('completed'))

    @property
    def portions(self):
        """The portions the phone was sent (a diagnostic phrase is not one)."""
        return [c for c in self.w.cues if not c.diagnostic]

    def current(self):
        state = self.state()
        if not state or state.get('completed') or state.get('pending_turn') or state.get('stream_waiting_next'):
            return None
        chunks, index = state.get('chunks') or [], state.get('chunk_index', 0)
        return chunks[index] if 0 <= index < len(chunks) else None

    def frames(self, kind=None, since=0):
        return [f for s, _, f in self.w.frames if s > since and (kind is None or f.get('type') == kind)]


@contextlib.contextmanager
def wire(cls, *key, **kwargs):
    scene = WireScene(cls, key, **kwargs)
    try:
        yield scene
    finally:
        scene.finish()


# --------------------------------------------------------------------------------------------------------------------------
# independent oracles
# --------------------------------------------------------------------------------------------------------------------------

_LETTERS = 'абвгдеёжзийклмнопрстуфхцчшщъыьэюя'
_VOWELS = frozenset('аеёиоуыэюя')


def words_of(text):
    """Lower-case words (ё folded into е), punctuation gone; digits stay a word."""
    return re.findall(r'[0-9]+(?:[.,][0-9]+)?|[а-яa-z]+(?:-[а-яa-z]+)*', str(text).casefold().replace('ё', 'е'))


def vowel_syllables(text):
    """Syllables by vowels. A number is counted as the spoken Russian number (the production syllable counter is not used)."""
    from helpers_s6_ack import cardinal, cardinal_big
    total = 0
    for word in words_of(text):
        if word[0].isdigit():
            digits = re.sub(r'\D', '', word)
            number = int(digits) if digits else 0
            total += vowel_syllables(cardinal(number) if number < 1000 else cardinal_big(number) if number < 10 ** 6 else 'много')
        else:
            total += sum(ch in _VOWELS for ch in word)
    return total


def stem5(word):
    return word[:5]


def covers(issued_text, sentence):
    """Does the issued text carry ``sentence``: every content word (4+ letters or a digit group), by its first five letters, in order."""
    issued = [stem5(w) for w in words_of(issued_text)]
    cursor = 0
    for word in words_of(sentence):
        if len(word) < 4 and not word[0].isdigit():
            continue
        wanted = stem5(word)
        try:
            cursor = issued.index(wanted, cursor) + 1
        except ValueError:
            return False
    return True


def squeeze_join(portions):
    return ' '.join(' '.join(str(p).split()) for p in portions)


def dangling_ends(portions):
    """Portions that end on a word that needs the next one (a negation, a condition, a preposition, a conjunction)."""
    needs_next = frozenset('не ни если кроме только без или и а но что чтобы как когда пока потому при для из от до по на в во с со к о об за над под про через между около более менее почти'.split())
    out = []
    for portion in portions:
        last = words_of(portion)
        if last and last[-1] in needs_next and not re.search(r'[.!?…;:]["»)]*\s*$', portion.strip()):
            out.append(portion)
    return out


def restarts(portions):
    """A later portion that starts the answer over: it opens with the first two words of the first portion (a sentence-initial
    word repeated three times in a row counts too)."""
    heads = [words_of(p)[:2] for p in portions]
    found = [i for i in range(1, len(heads)) if len(heads[0]) == 2 and heads[i] == heads[0]]
    for i in range(2, len(heads)):
        if heads[i][:1] and heads[i][:1] == heads[i - 1][:1] == heads[i - 2][:1]:
            found.append(i)
    return sorted(set(found))


# -- ACK variants of a portion (what the listener says) --------------------------------------------------------------------

def drop_word(text, marker):
    return ' '.join(w for w in text.split() if words_of(w) != [marker])


def numbers_of(text):
    return re.findall(r'\d+(?:[.,]\d+)?', text)


# -- the independent source oracle (N15) ----------------------------------------------------------------------------------

_NUMBER_WORDS = {w: i for i, w in enumerate('ноль один два три четыре пять шесть семь восемь девять десять'.split())}


def specifics(text):
    """The specific claims of a text: numbers (digit groups joined, number words up to ten), years, quoted terms and capitalised
    names that do not open a sentence."""
    text = str(text)
    found = set()
    flat = re.sub(r'(?<=\d)[\s  ](?=\d{3}\b)', '', text)
    found |= {('num', n.replace(',', '.')) for n in re.findall(r'\d+(?:[.,]\d+)?', flat)}
    found |= {('num', str(_NUMBER_WORDS[w])) for w in words_of(text) if w in _NUMBER_WORDS}
    found |= {('term', t.casefold()) for t in re.findall(r'«([^»]+)»', text)}
    for match in re.finditer(r'(?<![.!?]\s)(?<!^)\b([А-ЯЁ][а-яё]{3,})\b', text):
        found.add(('name', match.group(1).casefold().replace('ё', 'е')[:6]))
    return found


def unsupported_specifics(answer, sources, question=''):
    """Specific claims of ``answer`` that no source text and not the question carries: the made-up basis."""
    support = specifics(question)
    for source in sources:
        support |= specifics(source.get('text', '') if isinstance(source, dict) else source)
    return sorted(specifics(answer) - support)


# -- latency report with the full denominator (N16) -------------------------------------------------------------------------

INF = float('inf')


@dataclass
class Attempt:
    outcome: str                  # useful | echo | stall | diagnostic | silent
    first_pcm: float | None       # seconds from the end of the question to the first PCM frame of anything (None: no sound)
    first_useful: float | None    # ... to the first cue that carries content the question did not (None: never)


def percentile(values, q):
    """Nearest-rank percentile; ``inf`` is a legal value (an attempt that never produced it)."""
    if not values:
        return INF
    ordered = sorted(values)
    rank = max(1, -(-len(ordered) * q // 100))
    return ordered[int(rank) - 1]


def latency_report(attempts):
    """Percentiles over ALL attempts: silence, an echo of the question, a stall and a diagnostic phrase are failures that stay in
    the denominator (their useful time is infinite). ``first_pcm`` is shown for what it is: the first sound of any kind."""
    n = len(attempts)
    pcm = [a.first_pcm if a.first_pcm is not None else INF for a in attempts]
    useful = [a.first_useful if a.outcome == 'useful' and a.first_useful is not None else INF for a in attempts]
    return {'n': n, 'useful_rate': sum(1 for u in useful if u != INF) / n if n else 0.0,
            'first_pcm_p50': percentile(pcm, 50), 'first_pcm_p90': percentile(pcm, 90),
            'useful_p50': percentile(useful, 50), 'useful_p90': percentile(useful, 90)}


def guardrail(baseline, candidate, *, tolerance=0.0):
    """The reasons to reject ``candidate`` against ``baseline`` (both ``latency_report`` dicts); an empty list accepts it.
    A faster first sound never pays for a slower or rarer USEFUL answer."""
    reasons = []
    if candidate['n'] != baseline['n']:
        reasons.append('denominator')
    if candidate['useful_rate'] < baseline['useful_rate'] - tolerance:
        reasons.append('useful_rate')
    if candidate['useful_p90'] > baseline['useful_p90'] * (1 + tolerance) + 1e-9:
        reasons.append('useful_p90')
    if candidate['useful_p50'] > baseline['useful_p50'] * (1 + tolerance) + 1e-9:
        reasons.append('useful_p50')
    return reasons


# -- the judge and the blind gold (N17) ---------------------------------------------------------------------------------------

@dataclass
class Fact:
    key: str
    question: str
    truth: str                # the one correct statement (invented entities: nothing in any model knows it)
    wrong: tuple              # statements that are wrong


def judge_sensitivity(judge, planted):
    """The share of deliberately wrong answers a judge flags. ``judge(answer) -> True`` means "acceptable"."""
    flagged = sum(1 for answer in planted if not judge(answer))
    return flagged / len(planted) if planted else 0.0


def trusted(judge, planted, *, floor=0.9):
    """A judge's verdict is evidence only when it catches (nearly) all planted errors, the ones that share ITS OWN premise included."""
    return judge_sensitivity(judge, planted) >= floor


def answers_with(spoken_text, sentence, question):
    """``covers``, where the sentence may open with a head the listener asked themselves: a leading run of words that are all the
    question's own (by their first five letters, short words aside) needs no saying. W1F-A (b), brief task-w1fix-briefs.md: «head
    elision instead of the restatement fallback» - «Мост Сильверн построен | в 1873 году.» to «Когда построен мост Сильверн?» is
    dictated «в 1873 году.»; the rest of the sentence, in order, is still required (and a wrong year is still seen)."""
    if covers(spoken_text, sentence):
        return True
    asked = {stem5(w) for w in words_of(question)}
    words = words_of(sentence)
    for k in range(1, len(words)):
        head = [w for w in words[:k] if len(w) >= 4 or w[0].isdigit()]
        if not all(stem5(w) in asked for w in head):
            break
        if covers(spoken_text, ' '.join(words[k:])):
            return True
    return False


def gold_verdict(spoken_text, fact):
    """The blind, independent verdict: the spoken text carries the truth and none of the wrong statements (a head that only
    restates the question may be left out, ``answers_with``)."""
    if any(answers_with(spoken_text, wrong, fact.question) for wrong in fact.wrong):
        return 'FAIL'
    return 'PASS' if answers_with(spoken_text, fact.truth, fact.question) else 'FAIL'


def final_verdict(spoken_text, fact, judge_ok):
    """What the harness reports: the gold decides, the judge only adds a note (it never turns a gold FAIL into a pass)."""
    gold = gold_verdict(spoken_text, fact)
    return {'verdict': gold, 'judge_ok': bool(judge_ok), 'disagreement': (gold == 'FAIL') == bool(judge_ok)}


# --------------------------------------------------------------------------------------------------------------------------
# small shared helpers
# --------------------------------------------------------------------------------------------------------------------------

def collect(violations, scenario, message):
    violations.append(f'{scenario}: {message}')


def assert_none(violations, header, limit=12):
    if violations:
        shown = '\n  '.join(violations[:limit])
        raise AssertionError(f'{header}: {len(violations)} violation(s)\n  {shown}' + ('\n  ...' if len(violations) > limit else ''))


def portions_of(answer, settings=None):
    """The portions the production planner makes of a whole answer (the plan the controller will dictate)."""
    from echo_sync.portioner import portions
    return portions(answer, settings if settings is not None else {'preset': 'slow_assistive', 'max_words': 4, 'min_words': 2})
