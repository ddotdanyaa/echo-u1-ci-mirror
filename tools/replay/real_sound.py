"""I1 (U128, U83, U106, U81): the real sound of recorded calls, cut into words, composed into new phrases and given to the real chain packet by packet.

A call the laptop recorded (``echo_pcm/<call>/mic.wav``, 24 kHz 16-bit mono, ``timeline.jsonl`` with the holes) and an index of its words (``words_of``: the word, where it began and ended in the file, the
recognizer's confidence, ``clean``: no cue was playing over it) make a ``Bank``. ``compose`` joins the owner's own words, with room noise between them (never digital zero: a hole of the recording is no silence),
into phrases he did not say; ``Scene`` lines the phrases up on one time line; ``arrivals`` cuts the sound into the phone's packets and gives them stalls (a burst after a pause) and losses. ``stand.SoundStand``
feeds that to the real controller: the speech detector is the repo's own ``local_ear.SpeechOnset`` on the real samples, the ear's text of a segment is the labels of the words inside it, the cloud and the text
model are scripted as everywhere in the stand. Decisions and times come out as in ``stand.run``.

What is real and what is not: the sound, the detector, the controller, the wire, the ShadowEar and the FastText channel are real. The recognizer (its text is the labels, so a bank of the ear's own words
is not re-recognized here: ``ear`` may be given to say what the real ear made of a segment), the cloud, the model, the speech synthesis and the network are scripted; the clock is virtual. So the times are
the stand's order of events, never a measurement on a laptop or a phone (``07_METRICS_PROVENANCE.md`` §6). The recordings and their words are the owner's: nothing of them is kept in the repository, the
tests use sound made on the spot.
"""
import json
import math
import random
import re
import struct
import wave
from array import array
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

from echo_sync.local_ear import FRAME_MS, SAMPLE_RATE, SpeechOnset, frame_level
from echo_sync.textutil import normalize

RATE = SAMPLE_RATE                  # 24000, what the phone sends
HEADER = 44
MIN_WORD_S = 0.12                   # a shorter piece is a click, not a word
WORD_PAD_S = 0.03                   # room around a word's own limits
FADE_S = 0.008                      # in and out of a cut, so a join does not click
ZERO_RUN_S = 0.010                  # a run of digital zero this long is a hole of the recording
NOISE_WINDOW_S = 0.5
NOISE_FALLBACK = 12                 # amplitude of the made-up room tone when a recording has no quiet stretch without holes


# =====================================================================================================================================
# the recording
# =====================================================================================================================================

def read_wav(path):
    """``(pcm bytes, rate)`` of a 16-bit mono WAV. The recorder writes the header with size 0 and fixes it at close: a call cut short has size 0 there, so the data is everything after the header."""
    data = Path(path).read_bytes()
    if len(data) < HEADER or data[:4] != b'RIFF':
        raise ValueError(f'not a call recording: {path}')
    rate = struct.unpack('<I', data[24:28])[0] or RATE
    body = data[HEADER:]
    return body[:len(body) - len(body) % 2], rate


def write_wav(path, pcm, rate=RATE):
    with wave.open(str(path), 'wb') as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(rate)
        f.writeframes(bytes(pcm))


@dataclass
class Recording:
    pcm: bytes
    rate: int = RATE
    holes: list = field(default_factory=list)           # [(at_s, length_s)] where the recorder filled a missing stretch with silence
    start_s: float = 0.0                                # where the file starts on the call's clock

    @property
    def seconds(self):
        return len(self.pcm) / 2 / self.rate


def load_call(directory, channel='mic'):
    """The recording of one call from its directory (``<channel>.wav`` and ``timeline.jsonl``)."""
    root = Path(directory)
    pcm, rate = read_wav(root / f'{channel}.wav')
    holes, start = [], 0.0
    line_file = root / 'timeline.jsonl'
    if line_file.exists():
        for line in line_file.read_text(encoding='utf-8', errors='replace').splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get('ch') != channel:
                continue
            if row.get('ev') == 'gap':
                holes.append((row.get('at_ms', 0) / 1000, row.get('ms', 0) / 1000))
            elif row.get('ev') == 'channel':
                start = float(row.get('t', 0.0))
    return Recording(pcm, rate, holes, start)


@dataclass(frozen=True)
class Word:
    text: str
    on: float                          # seconds in the file
    off: float
    conf: float = 1.0
    clean: bool = True

    @property
    def key(self):
        return normalize(self.text)


def words_of(index, min_conf=0.0, only_clean=True):
    """The words of an index of a call (``utterances[].words[{w, start, end, conf, clean}]``) that a bank may take."""
    out = []
    for utterance in index.get('utterances', ()):
        for w in utterance.get('words', ()):
            text = str(w.get('w', '')).strip()
            on, off = float(w.get('start', 0.0)), float(w.get('end', 0.0))
            conf = w.get('conf')
            conf = 1.0 if conf is None else float(conf)
            clean = bool(w.get('clean', True))
            if not normalize(text) or off - on < MIN_WORD_S or conf < min_conf or (only_clean and not clean):
                continue
            out.append(Word(text, on, off, conf, clean))
    return out


# =====================================================================================================================================
# samples
# =====================================================================================================================================

def samples(pcm):
    a = array('h')
    a.frombytes(bytes(pcm)[:len(pcm) - len(pcm) % 2])
    return a


def pcm_of(a):
    return a.tobytes()


def seconds_of(n_samples, rate=RATE):
    return n_samples / rate


def _frame_samples(rate):
    return rate * FRAME_MS // 1000


def zero_runs(a, rate=RATE, min_s=ZERO_RUN_S):
    """``[(first sample, length)]`` of the runs of digital zero at least ``min_s`` long (holes of the recording, the silence of a synth)."""
    need = max(1, int(min_s * rate))
    runs, start = [], None
    for i, v in enumerate(a):
        if v == 0:
            if start is None:
                start = i
        elif start is not None:
            if i - start >= need:
                runs.append((start, i - start))
            start = None
    if start is not None and len(a) - start >= need:
        runs.append((start, len(a) - start))
    return runs


def fade(a, rate=RATE, seconds=FADE_S):
    n = min(len(a) // 2, int(seconds * rate))
    for i in range(n):
        k = i / n
        a[i] = int(a[i] * k)
        a[len(a) - 1 - i] = int(a[len(a) - 1 - i] * k)
    return a


class Noise:
    """The room's tone, taken from the quietest stretch of the recording without holes, looped from random places."""

    def __init__(self, a, rate=RATE):
        self.a, self.rate = a, rate

    @classmethod
    def of(cls, pcm, rate=RATE):
        a = samples(pcm)
        step = _frame_samples(rate)
        window = max(1, int(NOISE_WINDOW_S * rate) // step)
        frames = [a[i:i + step] for i in range(0, len(a) - step + 1, step)]
        levels = [frame_level(f) if any(f) else None for f in frames]            # None: a hole
        best, best_mean = None, None
        for i in range(0, max(0, len(levels) - window + 1), max(1, window // 2)):
            part = levels[i:i + window]
            if any(v is None for v in part):
                continue
            mean = sum(part) / len(part)
            if best_mean is None or mean < best_mean:
                best, best_mean = i, mean
        if best is None:
            return cls(None, rate)
        return cls(a[best * step:(best + window) * step], rate)

    def take(self, n, rng):
        """``n`` samples of room tone (never digital zero)."""
        if n <= 0:
            return array('h')
        if self.a is None or len(self.a) < 2:
            return array('h', (rng.choice((-1, 1)) * rng.randint(1, NOISE_FALLBACK) for _ in range(n)))
        out = array('h')
        while len(out) < n:
            at = rng.randrange(0, max(1, len(self.a) - 1))
            out.extend(self.a[at:at + n - len(out)])
        return out


def denull(a, noise, rng, rate=RATE):
    """Fill the runs of digital zero with room tone (a hole of the recording is no silence: the detector holds speech over it and the ear hears a dead line)."""
    for at, n in zero_runs(a, rate):
        a[at:at + n] = noise.take(n, rng)
    return a


# =====================================================================================================================================
# the bank and the composition
# =====================================================================================================================================

class Bank:
    """The owner's words of a recording, cut and ready; ``noise`` the room's tone."""

    def __init__(self, pcm, words, rate=RATE, noise=None):
        self.a, self.rate = samples(pcm), rate
        self.noise = noise or Noise.of(pcm, rate)
        self.by = {}
        for w in sorted(words, key=lambda w: (not w.clean, -w.conf)):
            self.by.setdefault(w.key, []).append(w)

    @classmethod
    def of(cls, recording, words):
        return cls(recording.pcm, words, recording.rate)

    def has(self, text):
        return normalize(text) in self.by

    def missing(self, phrase):
        return [t for t in _tokens(phrase) if t not in self.by]

    def vocabulary(self):
        return sorted(self.by)

    def cut(self, word, rng=None):
        a = self.a
        pad = int(WORD_PAD_S * self.rate)
        piece = array('h', a[max(0, int(word.on * self.rate) - pad):min(len(a), int(word.off * self.rate) + pad)])
        return fade(piece, self.rate)

    def compose(self, phrase, rng, pause=(0.06, 0.14)):
        """``(samples, [(text, on_s, off_s)])`` of ``phrase`` said with the owner's words; ``KeyError`` names the words the bank has not."""
        tokens = _tokens(phrase)
        absent = [t for t in tokens if t not in self.by]
        if absent:
            raise KeyError(' '.join(absent))
        out, spans = array('h'), []
        for n, token in enumerate(tokens):
            if n:
                out.extend(self.noise.take(int(rng.uniform(*pause) * self.rate), rng))
            variants = self.by[token][:2]
            piece = self.cut(rng.choice(variants))
            on = len(out) / self.rate
            out.extend(piece)
            spans.append((token, on, len(out) / self.rate))
        return denull(out, self.noise, rng, self.rate), spans


def _tokens(phrase):
    return [t for t in normalize(phrase).split() if t]


# =====================================================================================================================================
# scenes: phrases on one time line
# =====================================================================================================================================

@dataclass
class Step:
    kind: str                           # question fix doubt stop again resume chatter repeat partial
    text: str
    gap: float = None                   # silence before it (seconds); None: the seed's 0.6-1.5
    answer: str = None                  # a question's answer, as the ideal mind will give it
    of: str = None                      # a repeat's or partial's: the words of the cue it repeats (the answer the stand will say)


@dataclass
class Item:
    kind: str
    text: str
    on: float                           # seconds of the scene's sound
    off: float
    words: list                         # [(token, on, off)] on the scene's time line
    answer: str = None
    of: str = None


@dataclass
class Audio:
    pcm: bytes
    rate: int
    items: list
    skipped: list = field(default_factory=list)         # [(step, [absent words])]

    @property
    def seconds(self):
        return len(self.pcm) / 2 / self.rate


LEAD_S, TAIL_S = 1.5, 4.0


def build(bank, steps, seed=0, lead=LEAD_S, tail=TAIL_S, strict=False):
    """The scene's sound: the steps' phrases composed from ``bank``, room tone between. A step the bank cannot say (a word it lacks) is skipped and listed in ``skipped``; ``strict``: ``KeyError`` instead."""
    rng = random.Random(f'scene-{seed}')
    out = bank.noise.take(int(lead * bank.rate), rng)
    items, skipped = [], []
    for step in steps:
        try:
            body, spans = bank.compose(step.text, rng)
        except KeyError as absent:
            if strict:
                raise
            skipped.append((step, str(absent.args[0]).split()))
            continue
        gap = step.gap if step.gap is not None else rng.uniform(0.6, 1.5)
        out.extend(bank.noise.take(int(gap * bank.rate), rng))
        base = len(out) / bank.rate
        out.extend(body)
        items.append(Item(step.kind, step.text, base, len(out) / bank.rate, [(t, base + a, base + b) for t, a, b in spans], step.answer, step.of))
    out.extend(bank.noise.take(int(tail * bank.rate), rng))
    return Audio(pcm_of(out), bank.rate, items, skipped)


def scenes(phrases):
    """The owner's scenes as steps, from the phrases the bank can say (``question``, ``question2``, ``answer``, ``answer2``, ``fix``, ``fixed_answer``, ``stop``, ``again``, ``resume``, ``chatter``, ``doubt``, ``topic``,
    ``topic_answer``). Gaps are fixed in the sound; a scene cannot react to what the controller does, so «under the hand» and «barging in» are timed to where an answer of this stand usually is (the check tells when
    they missed): the stand reports which cue each utterance fell over.
    """
    p = phrases

    def q(text, answer, gap=None):
        return Step('question', text, gap, answer)
    return {
        'question_under_the_hand': [q(p['question'], p['answer'], 1.0), q(p['question2'], p['answer2'], 0.35)],
        'barge_in': [q(p['question'], p['answer'], 1.0), Step('stop', p['stop'], 4.0), q(p['question2'], p['answer2'], 1.2)],
        'repeat_the_last_word': [q(p['question'], p['answer'], 1.0), Step('repeat', _last_words(p['answer'], 1), 3.0, of=p['answer'])],
        'fix_the_number': [q(p['question'], p['answer'], 1.0), Step('fix', p['fix'], 8.5, p.get('fixed_answer', p['answer']))],
        'quick_questions': [q(p['question'], p['answer'], 1.0), q(p['question2'], p['answer2'], 0.3), q(p['question'], p['answer'], 0.3)],
        'change_of_topic': [q(p['question'], p['answer'], 1.0), Step('chatter', p['chatter'], 1.0), q(p.get('topic', p['question2']), p.get('topic_answer', p['answer2']), 2.0)],
        'silence': [q(p['question'], p['answer'], 1.0), Step('chatter', p['chatter'], 20.0), q(p['question2'], p['answer2'], 1.0)],
        'doubt': [q(p['question'], p['answer'], 1.0), Step('doubt', p['doubt'], 3.0)],
    }


def _last_words(text, n):
    return ' '.join(re.findall(r'[\w-]+', text)[-n:])


def long_call(bank, phrases, minutes, seed=0):
    """A call of about ``minutes`` of sound: the catalog's scenes one after another, a pause between (U81: the long session, the virtual clock; the telephone's own 180 minutes are the owner's)."""
    rng = random.Random(f'long-{seed}')
    catalog = scenes(phrases)
    names = sorted(catalog)
    steps, total = [], 0.0
    while total < minutes * 60:
        name = rng.choice(names)
        for step in catalog[name]:
            steps.append(Step(step.kind, step.text, step.gap, step.answer, step.of))
            total += (step.gap or 1.0) + 0.5 * max(1, len(_tokens(step.text)))
        steps.append(Step('chatter', phrases['chatter'], rng.uniform(4.0, 12.0)))
        total += 8.0
    return build(bank, steps, seed)


# =====================================================================================================================================
# packets
# =====================================================================================================================================

class Packet(NamedTuple):
    t: float                            # when it reaches the controller (seconds of the conversation)
    data: bytes
    at: float                           # where its sound begins in the source (seconds)


def arrivals(pcm, *, rate=RATE, packet_ms=20, stalls=(), loss=0.0, holes=(), seed=0):
    """The sound as the phone's packets arrive: one every ``packet_ms``; ``stalls`` ``[(at_s, length_s)]``: what would arrive inside arrives together at the end of the stall (a burst), nothing lost;
    ``loss``: the share of packets that never arrive; ``holes`` ``[(at_s, length_s)]``: no packet of that stretch arrives (the recorder's own gaps replayed as lost time)."""
    rng = random.Random(f'packets-{seed}')
    size = rate * packet_ms // 1000 * 2
    out = []
    for i in range(len(pcm) // size):
        at = i * packet_ms / 1000
        if any(a <= at < a + n for a, n in holes) or (loss and rng.random() < loss):
            continue
        t = at
        for a, n in stalls:
            if a <= at < a + n:
                t = a + n + (at - a) * 1e-4              # together, in their order
                break
        out.append(Packet(t, bytes(pcm[i * size:(i + 1) * size]), at))
    out.sort(key=lambda p: p.t)
    return out


# =====================================================================================================================================
# the detector on the real samples
# =====================================================================================================================================

class Watch:
    """The repo's own ``SpeechOnset`` (the energy rule), watched: after each ``feed`` ``take`` says what happened in it, ``'onset'`` and ``'end'``. Same contract as the detector the ear is given."""
    engine = 'energy'

    def __init__(self, rate=RATE):
        self.inner = SpeechOnset(sample_rate=rate)
        self.events = []

    @property
    def speaking(self):
        return self.inner.speaking

    @property
    def quiet_ms(self):
        return self.inner.quiet_ms

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def feed(self, pcm):
        was = self.inner.speaking
        verdict = self.inner.feed(pcm)
        if verdict == 'onset':
            if was:
                self.events.append('end')
            self.events.append('onset')
        if (was or verdict == 'onset') and not self.inner.speaking:
            self.events.append('end')
        return verdict

    def take(self):
        got, self.events = self.events, []
        return got


# =====================================================================================================================================
# U81: what grows along a long call
# =====================================================================================================================================

def growth_verdict(rows, *, warmup_s=300.0, threads=3, bytes_ratio=1.5, columns=('threads', 'traced')):
    """Did a long conversation hold: after ``warmup_s`` the thread count has not grown by more than ``threads`` and the traced memory by more than ``bytes_ratio`` of the figure at the end of the warmup.
    ``rows``: ``[{'t', 'threads', 'agenda', 'traced'}]``. Returns ``(held, why)``; ``why`` lists what grew. The figures are those of a stand on a virtual clock: «held» says the chain does not leak by itself over this
    much sound, not that a phone held 180 minutes."""
    rows = [r for r in rows if r['t'] >= warmup_s]
    if len(rows) < 2:
        return None, ['too short: no row after the warmup']
    first, last = rows[0], rows[-1]
    why = []
    if 'threads' in columns and last['threads'] - first['threads'] > threads:
        why.append(f"threads {first['threads']} -> {last['threads']}")
    if 'traced' in columns and first.get('traced') and last.get('traced') and last['traced'] > first['traced'] * bytes_ratio:
        why.append(f"traced memory {first['traced']} -> {last['traced']} bytes")
    return (not why), why


def level_db(pcm):
    """The level of a piece of sound in dBFS (for a test or a report)."""
    a = samples(pcm)
    return frame_level(a) if len(a) else -90.0


def tone(seconds, freq, rate=RATE, amp=9000):
    """A voiced stand-in for a word (a test's own sound: the stand's tests keep no recording)."""
    n = int(seconds * rate)
    return array('h', (int(amp * math.sin(2 * math.pi * freq * i / rate) * (0.6 + 0.4 * math.sin(2 * math.pi * 4 * i / rate))) for i in range(n)))
