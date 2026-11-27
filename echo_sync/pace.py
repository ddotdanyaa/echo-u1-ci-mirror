"""W5 stumble: the listener repeats a portion and stops on a word. How long to wait before helping, and from which word: «на одном слове замолчал, с того же слова и должно подсказываться».
Pure: no clock, no I/O, no model. In: the portion (``cue``), the ear's words with their times (``word``), the ear's detector (``voice``). Out (``decide(now)``): ``wait`` N ms, ``prompt`` from word K,
``done`` (the portion is said), ``hold`` (other speech: not this module's business), ``idle`` (no portion waits).

The wait is this person's, in this call: the gaps between their words inside a group and at a comma or the end of a group, the time they take to start after the microphone opens, how long a syllable of
theirs lasts. Before they have said anything, a prior of ordinary Russian speech stands in. A filler, a stretched word, a return to the start, a word said twice, a broken word, «забыл»: help at once (QUICK).
Never later than CAP_SECONDS, the wait of today (``TEMPO_REPEAT_SECONDS``); never over speech the ear hears. A number is never cut, and the help starts at «не» or a preposition left hanging before the word.
"""
import math
import re
from collections import namedtuple

from .settings import TEMPO_REPEAT_SECONDS
from .textutil import normalize
from .timer_policy import EAR_SPEECH_SECONDS

Word = namedtuple('Word', 'text start end joined timed', defaults=(False, True))     # ``joined``: no gap before it was measured; ``timed``: its own length was
Token = namedtuple('Token', 'surface norm number boundary')          # one word of the portion; ``boundary``: a comma or the end of a group comes after it
Decision = namedtuple('Decision', 'kind wait_ms index reason')

CAP_SECONDS = TEMPO_REPEAT_SECONDS
INNER_FLOOR = 0.57                   # inside a group: from 0.57 s, then ~0.13 s from the decision to the first PCM (12_LATENCY_CHAIN: «последнее событие → первый PCM 0.13»): help from 0.7 s after the stumble
BOUNDARY_FLOOR = 0.8                 # at a comma or the end of a group: a breath of this person, never less than this
QUICK_BOUNDS = (0.3, 0.6)            # after a filler and its kin: just long enough for the next word to begin
START_FLOOR = 0.9                    # nothing said yet since the microphone opened (it is shut on a cue and 0.8-1 s after: half duplex)
VOICE_STUCK = EAR_SPEECH_SECONDS     # a detector that has heard speech this long with no end is stuck (timer_policy.EAR_SPEECH_SECONDS, one figure): it holds nothing
TEXT_SECONDS = 1.5                   # speech the ear heard whose text has not come (TEMPO_TEXT_SECONDS): it may be the next words
WARM = 8                             # this many gaps of their own and the prior is dropped
KEEP = 40                            # the last this many of each kind count
FREE_GAP = 1.0                       # a gap of free speech longer than this tells nothing of the tempo
PRIOR_INNER = (0.10, 0.15, 0.2, 0.25, 0.35)
PRIOR_BOUNDARY = (0.35, 0.5, 0.6, 0.75, 0.9)
PRIOR_START = (0.35, 0.5, 0.6, 0.8)
PRIOR_SYLLABLE = 0.13
Z = {'inner': 2.8, 'boundary': 2.3, 'start': 2.3}   # one tail for each: ~8 gaps inside groups to a portion (z 2.8: 0.26 % each), 1-2 breaths (z 2.3: 1 %), one start
SPREAD = (0.35, 0.25)                # the prior spread of log pauses, and the least the spread may be learnt to be
PRIOR_WEIGHT = 4
STRETCH = (1.6, 0.3)                 # a word that lasts 1.6 times its syllables at this person's pace, and 0.3 s more than that
VOWELS = re.compile('[аеёиоуыэюяaeiouy]')
FILLERS = frozenset({'э', 'ээ', 'эээ', 'эм', 'эмм', 'м', 'мм', 'ммм', 'хм', 'а', 'ну', 'это', 'вот', 'так', 'значит', 'типа', 'короче', 'блин', 'сейчас', 'щас', 'ой'})
FILLER_PAIRS = frozenset({('как', 'его'), ('как', 'там'), ('это', 'самое'), ('как', 'бы'), ('в', 'общем'), ('что', 'там'), ('как', 'это')})
INTRO = frozenset({'ну', 'а', 'и', 'вот', 'так'})
DRAWN = re.compile(r'^(?:э+м*|м+|а{2,}|ы+|у{2,}|хм+)$')
BLANK = re.compile(r'^(?:забыл\w*|забыт\w*|вылетел\w*|вспомн\w*|запамятова\w*)$')
CONJ = frozenset({'а', 'но', 'что', 'чтобы', 'который', 'которая', 'которое', 'которые', 'которых', 'если', 'когда', 'потому', 'поэтому', 'где', 'хотя', 'однако'})
PROCLITIC = frozenset({'не', 'ни', 'в', 'во', 'на', 'с', 'со', 'к', 'ко', 'по', 'о', 'об', 'обо', 'от', 'до', 'за', 'из', 'у', 'без', 'для', 'при', 'про', 'через', 'над', 'под', 'перед', 'и', 'а', 'но', 'или'})
NUMERAL = ('ноль', 'нул', 'один', 'одн', 'дв', 'тр', 'четыр', 'четвер', 'пят', 'шест', 'сем', 'седьм', 'восем', 'восьм', 'девят', 'десят', 'сорок', 'девяност', 'сот', 'тысяч', 'миллион',
           'миллиард', 'перв', 'втор', 'полтор', 'половин', 'цел', 'запят')
PUNCT_END = re.compile(r'[,;:.!?…—–)»"]$')


def _norm(text):
    return normalize(text).replace('-', '').replace(' ', '')


def portion_tokens(text):
    """The words of a portion: a run of digit groups is one number («300 000»), a lone dash belongs to the word before it."""
    toks = []
    for raw in str(text or '').split():
        norm = _norm(raw)
        if not norm:
            if toks and PUNCT_END.search(raw):
                toks[-1] = toks[-1]._replace(boundary=True, surface=toks[-1].surface + ' ' + raw)
            continue
        number = any(c.isdigit() for c in norm)
        if number and toks and toks[-1].number and not toks[-1].boundary and norm.isdigit() and len(norm) == 3:
            toks[-1] = toks[-1]._replace(surface=toks[-1].surface + ' ' + raw, norm=toks[-1].norm + norm, boundary=bool(PUNCT_END.search(raw)))
            continue
        toks.append(Token(raw, norm, number, bool(PUNCT_END.search(raw))))
    for i in range(len(toks) - 1):
        if toks[i + 1].norm in CONJ:
            toks[i] = toks[i]._replace(boundary=True)
    return toks


def _syllables(norm):
    return max(1, len(VOWELS.findall(norm)))


def _edit1(a, b):
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) <= 1
    if len(a) > len(b):
        a, b = b, a
    i = 0
    while i < len(a) and a[i] == b[i]:
        i += 1
    return a[i:] == b[i + 1:]


def _match(spoken, tok):
    """Is the spoken unit this word of the portion? A case ending or one letter of the recognizer is the same word; a short word is itself; a number is a run of numerals."""
    if tok.number:
        return spoken.isdigit() and spoken == tok.norm or _numeral_run(spoken)
    if spoken == tok.norm:
        return True
    if min(len(spoken), len(tok.norm)) < 4 or len(spoken) < len(tok.norm) - 3:
        return False
    common = 0
    while common < min(len(spoken), len(tok.norm)) and spoken[common] == tok.norm[common]:
        common += 1
    return common >= max(3, min(len(spoken), len(tok.norm)) - 2) or (len(tok.norm) >= 5 and _edit1(spoken, tok.norm))


def _numeral(norm):
    return norm.isdigit() or norm in ('сто', 'ста') or norm.startswith(NUMERAL)


def _numeral_run(text):
    words = text.split('_')
    return len(words) >= 1 and all(_numeral(w) for w in words) and not text.isdigit()


def _cut(spoken, tok):
    return not tok.number and len(spoken) >= 2 and len(tok.norm) - len(spoken) >= 2 and tok.norm.startswith(spoken)


def _filler(norm):
    return norm in FILLERS or bool(DRAWN.match(norm))


def _tail(own, prior, z):
    """exp(mu + z*sigma) of the log pauses: theirs, with the prior worth PRIOR_WEIGHT of them."""
    lp = math.log(_quantile(prior, 0.5))
    logs = [math.log(max(x, 0.02)) for x in own[-KEEP:]]
    k = PRIOR_WEIGHT
    mu = (sum(logs) + k * lp) / (len(logs) + k)
    var = (sum((x - mu) ** 2 for x in logs) + k * SPREAD[0] ** 2) / (len(logs) + k)
    return math.exp(mu + z * max(SPREAD[1], math.sqrt(var)))


def _quantile(values, q):
    s = sorted(values)
    if not s:
        return 0.0
    x = q * (len(s) - 1)
    i = int(x)
    return s[i] if i + 1 >= len(s) else s[i] + (s[i + 1] - s[i]) * (x - i)


Unit = namedtuple('Unit', 'norm start end words')
Step = namedtuple('Step', 'unit kind index')    # kind: match / filler / blank / intro / stretch / repeat / restart / cut / wrong / foreign; index: the portion word it is about


class Pace:
    """One call. ``cue`` per portion said (or ``prompted`` for its tail), ``word`` per word the ear recognized, ``voice`` per change of its detector, ``decide`` on the tick."""

    def __init__(self, cap=CAP_SECONDS):
        self.cap = float(cap)
        self.inner, self.boundary, self.start, self.syllable = [], [], [], []
        self.toks = None
        self.free_last = None

    # ---- input ---------------------------------------------------------------------------------------------------------------
    def cue(self, portion, mic_open_at):
        """A portion has been said to the listener; the microphone opens at ``mic_open_at``. Words before that belong to nothing."""
        self.toks = portion_tokens(portion)
        self.mic_open_at = float(mic_open_at)
        self.words, self.voiced, self.unvoiced = [], None, None

    def prompted(self, index, mic_open_at):
        """The tail from word ``index`` has been said: it is what waits now."""
        if self.toks is not None:
            self.cue(' '.join(t.surface for t in self.toks[index:]), mic_open_at)

    def voice(self, t, on):
        """The ear's detector: speech began (``on``) or ended at ``t``."""
        if on:
            self.voiced, self.unvoiced = float(t), None
        else:
            self.unvoiced = float(t)
            if self.voiced is None:
                self.voiced = float(t)

    def utterance(self, text, onset, end):
        """The ear as it is today: the text of one utterance and its times, no time for each word. They are spread over it by syllables; the gaps inside it are not learnt, nor is a stretched word seen
        (that wants the recognizer's own times of its tokens)."""
        words = [w for w in (_norm(x) for x in str(text or '').split()) if w]
        if not words:
            return
        weights = [_syllables(w) + 0.5 for w in words]
        t, span = float(onset), max(0.0, float(end) - float(onset))
        for i, (w, k) in enumerate(zip(words, weights)):
            d = span * k / sum(weights)
            self.word(w, t, t + d, joined=i > 0, timed=len(words) == 1)
            t += d

    def word(self, text, start, end, joined=False, timed=True):
        norm = _norm(text)
        if not norm:
            return
        w = Word(norm, float(start), float(end), joined, timed)
        if self.toks is None or w.start < self.mic_open_at:
            self._free(w)
            return
        self.words.append(w)
        self._learn()

    # ---- what this person's tempo is --------------------------------------------------------------------------------------------
    def _free(self, w):
        """Speech that repeats nothing still has its gaps: inside a group, or before a conjunction."""
        last, self.free_last = self.free_last, w
        if last is None or not 0 <= w.start - last.end <= FREE_GAP or _filler(w.text) or _filler(last.text):
            return
        (self.boundary if w.text in CONJ else self.inner).append(w.start - last.end)
        self._trim()

    def _learn(self):
        steps = self._align()[0]
        if not steps:
            return
        last = steps[-1]
        if last.kind != 'match':
            return
        u = last.unit
        if u.words[-1].joined:
            return
        if len(u.words) == 1 and u.words[0].timed and not self.toks[last.index].number:
            self.syllable.append((u.end - u.start) / _syllables(u.norm))
        if len(steps) == 1 and last.index == 0 and len(u.words) == 1:
            self.start.append(max(0.0, u.start - self.mic_open_at))
        elif len(steps) >= 2 and steps[-2].kind == 'match' and steps[-2].index == last.index - 1 and len(u.words) == 1:
            gap = u.start - steps[-2].unit.end
            if gap >= 0:
                (self.boundary if self.toks[last.index - 1].boundary else self.inner).append(gap)
        elif len(u.words) > 1:      # a number grows word by word: its gaps are inside a group
            gap = u.words[-1].start - u.words[-2].end
            if gap >= 0:
                self.inner.append(gap)
        self._trim()

    def _trim(self):
        for pool in (self.inner, self.boundary, self.start, self.syllable):
            del pool[:-KEEP]

    @staticmethod
    def _pool(own, prior):
        return own if len(own) >= WARM else list(prior) + own

    def thresholds(self):
        """``(inner, boundary, quick, start)`` in seconds, for this person now. A pause of a person is log-normal around their median: the wait is the far tail of their own pauses (Z), so that a
        pause of theirs is a prompt about once in TAIL; the prior counts as PRIOR_WEIGHT pauses until their own outweigh it. Never shorter than a pause they have made, never longer than the cap."""
        inner = _tail(self.inner, PRIOR_INNER, Z['inner'])
        own = max(self.inner[-KEEP:]) + 0.1 if self.inner else 0       # a gap this person has made inside a group is no stumble, however slow they are: up to the cap
        t_inner = min(self.cap, max(INNER_FLOOR, inner + 0.1, own))
        own_b = max(self.boundary[-KEEP:]) + 0.15 if self.boundary else 0
        t_boundary = min(self.cap, max(BOUNDARY_FLOOR, t_inner + 0.2, _tail(self.boundary, PRIOR_BOUNDARY, Z['boundary']) + 0.1, own_b))
        t_quick = min(QUICK_BOUNDS[1], max(QUICK_BOUNDS[0], _quantile(self._pool(self.inner, PRIOR_INNER), 0.5) * 2 + 0.1))
        t_start = min(self.cap, max(START_FLOOR, _tail(self.start, PRIOR_START, Z['start']) + 0.1))
        return t_inner, t_boundary, t_quick, t_start

    def _per_syllable(self):
        return _quantile(self.syllable, 0.5) if len(self.syllable) >= 3 else PRIOR_SYLLABLE

    # ---- where they are in the portion ------------------------------------------------------------------------------------------
    def _units(self):
        """Words to units: two words of a filler phrase are one, and a run of numerals where the portion has a number is one."""
        units, i, ws = [], 0, self.words
        while i < len(ws):
            w = ws[i]
            if i + 1 < len(ws) and (w.text, ws[i + 1].text) in FILLER_PAIRS:
                units.append(Unit(w.text + '_' + ws[i + 1].text, w.start, ws[i + 1].end, (w, ws[i + 1])))
                i += 2
                continue
            if _numeral(w.text) and not w.text.isdigit():
                j = i
                while j + 1 < len(ws) and _numeral(ws[j + 1].text) and not ws[j + 1].text.isdigit():
                    j += 1
                if j > i or any(t.number for t in self.toks):
                    run = ws[i:j + 1]
                    units.append(Unit('_'.join(x.text for x in run), run[0].start, run[-1].end, tuple(run)))
                    i = j + 1
                    continue
            units.append(Unit(w.text, w.start, w.end, (w,)))
            i += 1
        return units

    def _align(self):
        """The steps of what was said against the portion; ``(steps, pos, restarted, foreign)``: pos is how many words of the portion this pass has said."""
        toks, n = self.toks, len(self.toks)
        steps, pos, restarted, foreign, best = [], 0, False, 0, 0
        for u in self._units():
            here = toks[pos] if pos < n else None
            if here is not None and _match(u.norm, here):
                kind = 'match'
                if not here.number and len(u.words) == 1 and u.words[0].timed and u.end - u.start >= _syllables(u.norm) * self._per_syllable() * STRETCH[0] + STRETCH[1]:
                    kind = 'stretch'
                steps.append(Step(u, kind, pos)); pos += 1; foreign = 0
            elif here is not None and pos + 1 < n and steps and steps[-1].kind in ('wrong', 'foreign') and foreign == 1 and _match(u.norm, toks[pos + 1]):
                steps[-1] = steps[-1]._replace(kind='misheard'); steps.append(Step(u, 'match', pos + 1)); pos += 2; foreign = 0
            elif BLANK.match(u.norm) or u.norm.startswith('не_помн'):
                steps.append(Step(u, 'blank', pos))
            elif '_' in u.norm and tuple(u.norm.split('_')) in FILLER_PAIRS or _filler(u.norm):
                steps.append(Step(u, 'intro' if pos == 0 and u.norm in INTRO and not any(s.kind == 'match' for s in steps) else 'filler', pos))
            elif pos > 0 and _match(u.norm, toks[pos - 1]):
                steps.append(Step(u, 'repeat', pos))
            elif pos > 1 and _match(u.norm, toks[0]):
                best = max(best, pos); pos = 1; restarted = True
                steps.append(Step(u, 'restart', pos)); foreign = 0
            elif here is not None and _cut(u.norm, here):
                steps.append(Step(u, 'cut', pos))
            elif here is not None and pos + 1 < n and _match(u.norm, toks[pos + 1]):
                steps.append(Step(u, 'match', pos + 1)); pos += 2; foreign = 0       # a word left out: the confirmation is not this module's
            else:
                foreign += 1
                steps.append(Step(u, 'wrong' if pos > 0 and foreign == 1 else 'foreign', pos))
        return steps, pos, restarted, foreign

    def _anchor(self, k):
        """The first word of the help: the word they stopped on, with «не» or a preposition left hanging before it; a number is one word."""
        back = 0
        while k > 0 and back < 2 and self.toks[k - 1].norm in PROCLITIC and not self.toks[k - 1].boundary:
            k -= 1; back += 1
        return k

    def text(self, index):
        return ' '.join(t.surface for t in self.toks[index:]) if self.toks is not None else ''

    # ---- the decision -----------------------------------------------------------------------------------------------------------
    def decide(self, now):
        if self.toks is None:
            return Decision('idle', 0, None, 'no portion')
        steps, pos, restarted, foreign = self._align()
        n = len(self.toks)
        if foreign >= 2 or (foreign and pos == 0):
            return Decision('hold', 0, None, 'other speech')
        if pos >= n and steps and steps[-1].kind in ('match', 'stretch', 'misheard'):
            return Decision('done', 0, None, 'said')
        last_end = steps[-1].unit.end if steps else None
        if self.voiced is not None and (self.unvoiced is None or self.unvoiced < self.voiced) and now - self.voiced < VOICE_STUCK:
            return Decision('wait', 100, None, 'speech')
        t_inner, t_boundary, t_quick, t_start = self.thresholds()
        if self.unvoiced is not None and self.voiced is not None and (last_end is None or self.voiced > last_end + 0.05) and self.unvoiced >= self.mic_open_at:
            if now < self.unvoiced + TEXT_SECONDS:
                return self._wait(now, self.unvoiced + TEXT_SECONDS, 'text')
            return self._due(now, self.unvoiced, self.cap if not steps else t_boundary, min(pos, n - 1), 'no_text')
        if not steps or all(s.kind == 'intro' for s in steps):
            return self._due(now, last_end if steps else self.mic_open_at, t_start, 0, 'start')
        last = steps[-1]
        k = min(pos, n - 1)
        if last.kind in ('filler', 'blank', 'stretch', 'repeat', 'restart', 'cut', 'wrong'):
            return self._due(now, last.unit.end, t_quick, k, last.kind)
        if restarted:
            return self._due(now, last.unit.end, t_quick, k, 'restart')
        if last.kind == 'match' and self.toks[last.index].number:
            return self._due(now, last.unit.end, t_inner, last.index, 'number')
        before = self.toks[pos - 1] if pos > 0 else None
        if before is not None and before.boundary:
            return self._due(now, last.unit.end, t_boundary, k, 'boundary')
        return self._due(now, last.unit.end, t_inner, k, 'inner')

    def _wait(self, now, due, reason):
        return Decision('wait', max(1, int(round((due - now) * 1000))), None, reason)

    def _due(self, now, ref, threshold, k, reason):
        due = ref + min(threshold, self.cap)
        if now < due:
            return self._wait(now, due, reason)
        return Decision('prompt', 0, self._anchor(k), reason)
