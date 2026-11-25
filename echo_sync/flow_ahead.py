"""w5-flow: the next portion on time - released AHEAD of the end of the repeat, the length of the rest following the listener.

Pure: no I/O, no clock of its own, no sound. The controller feeds it what the ear hears and asks what to do; nothing here acts.

Today the next portion waits for the confirmation of the repeat (the cloud's stable partial or, with an acting ear, the ear's text after
300 ms of quiet): the speaker stands in silence ~2 s after the last word of each portion (chain: ``cloud_context/reports/w5-flow.md``).
Here: the ear's growing text of the repeat (``ShadowEar`` peeks, one record per change) is aligned to the waiting portion word by word.
When every word but the last has been said cleanly, the tempo of THIS speaker in THIS call says when the last word will end, and the
next portion is sent so that its sound reaches the ear 100-300 ms after that end (``FLOW_TARGET_S``): its synthesis is done before (at
the cue: ``prepare``). Something goes wrong - another word, a hesitation, back to the start, a pause too long for the tempo, the end
heard not saying the last word - and the portion is withdrawn (``withdraw``): before it was sent nothing was heard; after, the cue is
stopped and the cursor goes back, as the ear's late veto does today. Never ahead: the last portion of an answer, a portion whose last
word is a number, a sign or a unit or «не»/«ни» (``protected``: numbers and «не» are confirmed by hearing them, never by a guess), a
portion of one word, before the tempo of the speaker is known (``MIN_TEMPO_WORDS``), after a hesitation in this portion.

The length of the portions not yet said is ``portioner.PortionAdapter`` (fed by ``ControlledMedia._adapt_observe``, cut by ``EchoEngine.adapt_rest``): the one rule.

Setting ``flow_ahead`` ("off" | "on"), off by default. The integration patch for ``controlled_media.py`` is in the report.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from .textutil import syllables

# --- the path after the decision, seconds (estimates: ``analysis/08_LATENCY_BRAINSTORM.md`` §3 steps 17-20; none measured on the phone)
SYNTH_S = 0.054          # SAPI, C14 median; 0 when the synthesis was done ahead (``prepare``)
DOWN_S = 0.125           # laptop -> Cloudflare -> iPhone, estimate 0.07-0.18
PLAY_S = 0.175           # iOS voice mode to the ear, estimate 0.10-0.25
MIC_PACKET_S = 0.10      # the phone sends the microphone in 100 ms packets; a packet still being filled when the gate closes is lost
EAR_SEEN_S = 0.35        # end of a word -> the ear's peek shows it: up 0.05+0.12, the streaming model's own delay ~0.15, the peek ~0.03 (estimate)
FLOW_TARGET_S = (0.10, 0.30)    # the next cue is to be heard this long after the end of the last word (the task)
FLOW_AIM_S = 0.20               # aimed at inside it
MIN_TEMPO_WORDS = 6      # words of this speaker timed in this call before anything is released ahead
TEMPO_WINDOW = 24        # the last N timed words make the tempo
SLOWING_FACTOR = 1.35    # this portion's words so far are this much slower per syllable than the speaker's tempo: nothing ahead (yet)
PAUSE_FACTOR = 2.5       # a pause between words longer than this many times the speaker's usual one is a stumble: nothing ahead
MIN_PAUSE_S = 0.6        # ... and never shorter than this
LATE_FACTOR = 2.0        # the last word not seen by predicted end + this many words' time (and at least LATE_MIN_S): withdrawn
LATE_MIN_S = 0.6
MARGIN_SD = {'half': 3.0, 'full': 0.5}   # the aim moves later by this many standard deviations of the speaker's time for the last word: full duplex,
                                # so as not to speak over its end; half duplex, more, as the gate closes on the first event of the cue and a clipped
                                # last word is never confirmed


def _atoms(text):
    """The canonical atoms of ``text`` (ru_alignment: lemmas, numbers by value, units), hesitation sounds marked; () on any failure."""
    try:
        from .ru_alignment import _canonical, _hesitation
        atoms = _canonical(text, (), True)
        return tuple((a, _hesitation(atoms, i)) for i, a in enumerate(atoms))
    except Exception:
        return ()


def protected(atom):
    """A number, a sign, a unit, «не»/«ни»: confirmed only by hearing it."""
    return atom.kind != 'w' or atom.atom in ('не', 'ни')


@dataclass(frozen=True)
class Progress:
    said: int            # words of the portion said, in order, from its start
    total: int           # words of the portion
    clean: bool          # no hesitation, no restart, nothing else said among them
    deviates: bool       # a word the portion does not have where its next word should be (not a number still growing at the end)
    restarted: bool      # the start of the portion said again after more of it
    hesitated: bool      # «э», «мм» after the first word
    last_protected: bool # the portion's last word is a number / sign / unit / «не»


def progress(heard, portion, fillers=('ну', 'вот')):
    """How far ``heard`` (the ear's text of the repeat so far) has gone through ``portion``. Fillers before the first word are skipped."""
    want = [a for a, _ in _atoms(portion)]
    got = list(_atoms(heard))
    total = len(want)
    last_protected = bool(want) and protected(want[-1])
    said, hesitated, restarted, deviates = 0, False, False, False
    lead = True
    for i, (atom, hes) in enumerate(got):
        if hes or (lead and atom.atom in fillers):
            hesitated |= not lead
            continue
        lead = False
        if said < total and atom.atom == want[said].atom:
            said += 1
            continue
        if said and atom.atom == want[0].atom and said < total:
            restarted, said = True, 1        # «при ста ... при ста градусах»: the speaker went back to the start
            continue
        tail = i == len(got) - 1
        if tail and said < total and atom.kind == 'n' and want[said].kind == 'n':
            continue                          # «тысяча девятьсот» on the way to 1945: not yet said, not wrong
        deviates = True
        break
    clean = not (deviates or restarted or hesitated)
    return Progress(said, total, clean, deviates, restarted, hesitated, last_protected)


class Tempo:
    """The speaker's time per syllable in this call, from the moments the ear first showed each word (consecutive words of one utterance)."""

    def __init__(self):
        self.per_syllable = []      # seconds per syllable, one per timed word
        self.pauses = []            # the time between words beyond what their syllables explain is not separated: it is in per_syllable

    def add(self, seconds, word):
        n = max(1, syllables(word))
        if 0 < seconds < 4.0:
            self.per_syllable = (self.per_syllable + [seconds / n])[-TEMPO_WINDOW:]

    @property
    def known(self):
        return len(self.per_syllable) >= MIN_TEMPO_WORDS

    def word_time(self, word):
        """(median, standard deviation) of the time the next word takes to show, seconds."""
        n = max(1, syllables(word))
        med = statistics.median(self.per_syllable)
        sd = 1.4826 * statistics.median(abs(x - med) for x in self.per_syllable)     # robust: «и», «в» shown with the next word do not blow it up
        return med * n, sd * n


@dataclass
class Decision:
    action: str          # 'wait' | 'prepare' | 'release' | 'withdraw' | 'off'
    at: float | None = None        # 'release': when to send (now or later); the controller sends then unless a later decision withdraws
    reason: str = ''


@dataclass
class _Portion:
    text: str
    next_text: str | None
    cued_at: float
    words: list = field(default_factory=list)    # surfaces of the portion's words
    seen: dict = field(default_factory=dict)     # index of a word -> when the ear first showed it
    rates: list = field(default_factory=list)    # this portion's seconds per syllable, word by word
    prepared: bool = False
    release_at: float | None = None
    released: bool = False
    predicted_end: float | None = None
    last_text: str = ''
    off: str = ''        # why nothing goes ahead for this portion any more


class FlowAhead:
    """One per call. ``cue(portion, next_portion, now)`` when a portion has been cued; ``heard(text, now)`` on every new ear text of the
    repeat (a peek or the end of the utterance); ``decide(now)`` on every tick. ``confirmed()`` / ``withdrawn()`` when the controller acted."""

    def __init__(self, *, duplex='half', ear_seen_s=EAR_SEEN_S, down_s=DOWN_S, play_s=PLAY_S, aim_s=None, lookahead=2):
        self.duplex, self.ear_seen_s, self.down_s, self.play_s = duplex, ear_seen_s, down_s, play_s
        self.aim_s = FLOW_AIM_S if aim_s is None else aim_s
        self.lookahead = lookahead
        self.tempo = Tempo()
        self.p = None
        self.trace = []

    # --- input
    def cue(self, portion, next_portion, now):
        self.p = _Portion(portion, next_portion or None, now)
        self.p.words = [a.surface for a, _ in _atoms(portion)]
        if not next_portion:
            self.p.off = 'last_portion'

    def heard(self, text, now):
        p = self.p
        if p is None or not isinstance(text, str):
            return
        p.last_text = text
        pr = progress(text, p.text)
        for k in range(pr.said):
            if k not in p.seen:
                p.seen[k] = now
                if k and k - 1 in p.seen and pr.clean:
                    self.tempo.add(now - p.seen[k - 1], p.words[k])
                    p.rates.append((now - p.seen[k - 1]) / max(1, syllables(p.words[k])))
        if pr.restarted:
            p.seen, p.rates = {0: now}, []
        p.progress = pr

    # --- output
    def decide(self, now):
        p = self.p
        if p is None:
            return Decision('off', reason='no_portion')
        pr = getattr(p, 'progress', None)
        if p.released:
            if pr is not None and (pr.deviates or pr.restarted or pr.hesitated):
                return self._withdraw('changed_after_release')
            if pr is not None and pr.said < pr.total and p.predicted_end is not None:
                w, _ = self.tempo.word_time(p.words[-1])
                if now > p.predicted_end + self.ear_seen_s + max(LATE_FACTOR * w, LATE_MIN_S):
                    return self._withdraw('last_word_not_heard')
            return Decision('wait', reason='released')
        if p.off:
            return Decision('off', reason=p.off)
        if not p.prepared:
            p.prepared = True
            return Decision('prepare', reason='synthesis_ahead')
        if p.release_at is not None:
            if pr is not None and not pr.clean:
                return self._withdraw('changed_before_send')
            if now >= p.release_at:
                p.released = True
                self.trace.append(('release', p.text, round(p.release_at, 3)))
                return Decision('release', now, 'scheduled')
            return Decision('release', p.release_at, 'scheduled')
        if pr is None or pr.said == 0:
            return Decision('wait', reason='nothing_heard')
        why = self._why_not(pr, now)
        if why:
            if why in ('number_at_the_end', 'hesitation', 'restart', 'deviates', 'one_word'):
                p.off = why
            return Decision('wait', reason=why)
        if pr.said == pr.total:
            p.predicted_end = p.seen[pr.total - 1] - self.ear_seen_s
        else:
            times = [self.tempo.word_time(word) for word in p.words[pr.said:]]
            margin = MARGIN_SD.get(self.duplex, 1.5) * sum(sd * sd for _, sd in times) ** 0.5
            p.predicted_end = p.seen[pr.said - 1] + sum(w for w, _ in times) - self.ear_seen_s + margin
        p.release_at = max(now, p.predicted_end + self.aim_s - self.down_s - self.play_s)
        if self.duplex == 'half':
            p.release_at = max(p.release_at, p.predicted_end + MIC_PACKET_S - self.down_s)
        return self.decide(now)

    def _why_not(self, pr, now):
        p = self.p
        if pr.total < 2:
            return 'one_word'
        if pr.last_protected:
            return 'number_at_the_end'
        if pr.hesitated:
            return 'hesitation'
        if pr.restarted:
            return 'restart'
        if pr.deviates:
            return 'deviates'
        if not self.tempo.known:
            return 'tempo_unknown'
        if p.rates and statistics.median(p.rates[-2:]) > SLOWING_FACTOR * statistics.median(self.tempo.per_syllable):
            return 'slowing'
        last = p.seen.get(pr.said - 1)
        w, _ = self.tempo.word_time(p.words[pr.said]) if pr.said < pr.total else (0.0, 0.0)
        if pr.said < pr.total and last is not None and now - last > max(PAUSE_FACTOR * w, MIN_PAUSE_S):
            return 'pause'              # a stumble in the middle: w5-stumble's, nothing ahead (not final: it may go on)
        if pr.total - pr.said > self._unsaid_allowed(pr):
            return 'not_yet'
        return ''

    def _unsaid_allowed(self, pr):
        """Words of the portion that may still be unsaid at the decision: 1 (the last word); 2 when the last word is too short for the
        path (the ear shows a word ``ear_seen_s`` after its end, the cue takes ``down_s + play_s`` to the ear) and the portion has 4 words or
        more and neither of the two is protected - otherwise the cue would always come late after a short last word."""
        p = self.p
        if self.lookahead < 2 or pr.total < 4:
            return 1
        lead = self.ear_seen_s + self.down_s + self.play_s - self.aim_s
        last, _ = self.tempo.word_time(p.words[-1])
        two = [a for a, _ in _atoms(p.text)][-2:]
        return 2 if last < lead and not any(protected(a) for a in two) else 1

    def _withdraw(self, why):
        p = self.p
        was = p.released
        p.release_at, p.released, p.off = None, False, why
        self.trace.append(('withdraw', p.text, why, was))
        return Decision('withdraw', reason=why + (':sent' if was else ':held'))
