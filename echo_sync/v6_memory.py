"""V6 slice «память» (always on: no switch; the card needs the call's ledger).

Memory is NOT a second store. The ledger of verbatim words (conversation_ledger.py) is the truth; here only READS of it are assembled into a CARD for one model request, under a budget of
characters, from a projection that can be erased and rebuilt from the ledger (``Projection``). The order of priority, which is also the order the card is read in; what does not fit goes
from the bottom, and a line is never cut inside a number (``fit``):
  1 pinned lines   the owner's standing lines of this call (subject, audience, style from the call context), never dropped
  2 exchanges      the newest exchanges word for word, as the old history block had them (6 of them, 600 characters a side)
  3 retrieved      earlier utterances that bear on the present question: SQLite FTS5 in memory (bm25 together with recency), or the same bm25 over the projection's own index when FTS5 is missing
  4 exact things   utterances with numbers or dates related to the question, in spoken order: a later correction («не 500, а 450») stands AFTER the line it corrects, both are shown and the heading says the
                   correction is what stands (U88, the coordinator's decision of 15.11: two lines, the correction after); the old value is never told anywhere without its correction after it (``_corrected``)
  5 outline        for every step of several minutes one or two utterances of the whole call, chosen by the rarity of their words in THIS call (no word lists), with their times
  6 carry          the recap of earlier calls the old code already had (``ConversationLedger.recap_calls`` through ``fast.carry``), as it was, if it fits
A line carries its time from the start of the call and its speaker; the ledger knows no faces, so the speaker is the ledger's own kind («в комнате» for the listener's finals, «мы» for our answers;
M1-g: a final the judge took for the prompt said aloud is our words in the owner's voice: it is no row at all, our answer row stands for it).
Modes: shadow builds the card and writes into the call journal only sizes, the time it took, the count of lines of each part and their ids (no text); the request is not changed. On puts the card
into the request at the one point of ``FastText._start`` (it replaces the history block, the recap and the carry) only when the card is not empty; any exception leaves the old request and one
journal line. Off builds nothing. Reused: ``ConversationLedger`` (records, ``recap_calls``), ``_words``, the numerals and dates of first_useful (``_numbers``, ``_dated``: closed grammatical
classes), ``stems`` of textutil. No network, no model, no clock of its own (the timer is injected). Every number that steers is in START (settings or «стартовое»), nothing here is measured."""
import logging
import math
import sqlite3
import threading
import time
from collections import Counter, namedtuple

from .conversation_ledger import ANSWER, USER
from .first_useful import _dated, _numbers
from .textutil import NEGATION_WORDS, NUMBER_WORDS, norm_words, normalize, stems

logger = logging.getLogger('echo-sync')
SPEAKER = 'в комнате'
# E19 (the conditions survive the compaction of a line): the words that carry a condition, a negation or a number are a CLOSED grammatical class (negations of textutil, the conditional and restrictive particles, the numerals
# of textutil): a line cut to the room keeps the run that holds them beside the clues of the question. No phrase list: a class, as ``first_useful._numbers``.
_HOLD = NEGATION_WORDS | frozenset(normalize('если только кроме без пока').split())
_COUNTS = _HOLD | NUMBER_WORDS
OURS = 'мы'           # M1-g: the speaker of our answers (what the prompter gave and the owner said aloud)
PARTS = ('pinned', 'exchanges', 'retrieved', 'exact', 'window', 'brief', 'outline', 'carry')
HEAD = {'pinned': 'Опора этого звонка:',
        'exchanges': 'Последние реплики этого разговора (для связи с вопросом):',      # the heading of the old history block, word for word
        'window': 'Последние реплики подряд, обе стороны (время от начала звонка):',
        'brief': 'Перед этим кратко:',
        'retrieved': 'Раньше в этом разговоре, по теме вопроса (время от начала звонка):',
        'exact': 'Числа и даты из этого разговора по порядку сказанного (поправка стоит после прежнего значения и отменяет его):',
        'outline': 'Ход разговора по шагам (время от начала звонка):',
        'carry': 'Прошлые разговоры (кратко):'}
# THE table of the slice: every number it decides by. All «стартовое»: nothing is measured. The first three are the settings v6_memory_chars / _step_min / _lines.
START = {'chars': 4000,            # the card is never longer
         'step_min': 5,            # the outline: lines per step of this many minutes
         'lines': 4,               # retrieved utterances
         'exchanges': 6,           # the newest exchanges word for word (the old HISTORY_EXCHANGES)
         'reply_chars': 600,       # each side of an exchange (the old HISTORY_CHARS)
         'window': 15,             # one-research (OWNER_REQUIREMENTS U-new-8): the last utterances of both sides in spoken order, what the exchanges did not show (interview-copilot app.js:487: 15)
         'window_share': 0.4,      # the window takes at most this share of the budget (U138: all of the last 15 stand in it, each line clipped to its part of the share); retrieval and exact things above it have been placed already and keep their room
         'window_line_min': 48,    # a window line is never clipped below this many characters (its head with the time and the speaker included): below it the oldest lines of the window go, as before
         'brief_chars': 520,       # the window before it, one line: each utterance's head (HF speech-to-speech chat.py:1373 summarises older turns; here extractive, no model)
         'brief_head': 28,         # characters of each utterance in the brief
         'unanswered': 3,          # said and not answered since the last answer, shown as the old block showed them
         'unanswered_words': 3,    # and only if it has at least this many words
         'pinned_lines': 3, 'pinned_line': 160,      # pinned: at most this many lines of at most this many characters
         'line_chars': 240,        # one retrieved / exact / outline utterance
         'index_chars': 20000,     # an utterance enters the projection whole up to this (a safety cap against a runaway text, not a cut of speech)
         'dup_s': 30.0,            # the same words again within this many seconds (a reconnect re-sends a final under a new id) are one utterance
         'exact_lines': 6,         # exact things
         'history_share': 0.5,     # the exchanges take at most this share of the budget, so the parts below always have room
         'outline_share': 0.4,     # the outline has its own budget (it takes only what the parts above leave): this share
         'carry_chars': 600,       # the old RECAP_CHARS
         'common_from': 10, 'common_df': 0.3,      # from this many utterances on, a word in more than this share of them is no clue for retrieval (rarity in the call, no word list)
         'rel_floor': 0.25,        # a retrieved line scores at least this share of the best one
         'turn_weight': 0.3,       # the words of the last turns (not in the question) count this much beside the words of the question
         'recency_weight': 0.5, 'half_life_min': 30.0,      # score = bm25 * (1 + weight * 0.5 ** (age / half life))
         'outline_core': 0.5,      # the outline picks from this middle share of its step (1 = the whole step)
         'outline_two': 4}         # a step with at least this many utterances gets two outline lines, else one
# The bound for a call of 180 minutes (3000 finals and 3000 answers = the 6000 records the ledger keeps hot), tested on a synthetic call in the cloud: not a measure of the laptop (an N95 is slower).
BOUNDS = {'rows': 6000, 'cold_s': 3.0, 'warm_s': 1.0, 'peak_mb': 40}
_BM25_K1, _BM25_B = 1.2, 0.75     # the defaults of FTS5's bm25(); the plain pass computes the same formula


def fit(text, n):
    """``text`` (spaces collapsed) in at most ``n`` characters: whole, or cut after a whole word with «…», never between the parts of a number («1 500»); '' when not even one word fits."""
    text = ' '.join(str(text or '').split())
    if len(text) <= n:
        return text
    i = text.rfind(' ', 0, max(0, n))
    while i > 0:
        before, after = text[:i].rsplit(' ', 1)[-1], text[i:].lstrip()[:1]
        if not (before.isdigit() and after.isdigit()):
            return text[:i].rstrip() + '…'
        i = text.rfind(' ', 0, i)
    return ''


def window(text, n, keys=()):
    """``text`` in at most ``n`` characters: whole; else the run of whole words (with «…» where it is cut) that holds the most clues (a word whose stem is in ``keys`` counts 2; a word with a digit, a numeral, a negation or a
    condition word 1: E19, what a speaker said under a condition («только если акт подписан», «а не по факту») stays with it; none: the head)."""
    text = ' '.join(str(text or '').split())
    if len(text) <= n:
        return text
    words = text.split(' ')
    keys = frozenset(k for k in keys if len(k) >= 3)      # a stem of one or two letters is a function word of the question («мы», «за», «не»): no clue
    w = [2 if keys and set(stems(norm_words(x))) & keys else 1 if any(c.isdigit() for c in x) or set(norm_words(x)) & _COUNTS else 0 for x in words]
    if not any(w):
        return fit(text, n)
    off, o = [], 0
    for x in words:
        off.append(o)
        o += len(x) + 1
    pre = [0]
    for x in w:
        pre.append(pre[-1] + x)
    room, top, runs, j = max(0, n - 2), 0, [], 0
    for i in range(len(words)):
        j = max(j, i)
        while j < len(words) and off[j] + len(words[j]) - off[i] <= room:
            j += 1
        if pre[j] - pre[i] > top:
            top, runs = pre[j] - pre[i], [(i, j)]
        elif pre[j] - pre[i] == top and top > 0:
            runs.append((i, j))
    if not runs:
        return fit(text, n)
    i, j = runs[len(runs) // 2]      # E19: of the runs that hold the same clues the middle one: a condition is told with the words before it AND the clause after it, not cut right behind its «если»
    return ('… ' if i else '') + ' '.join(words[i:j]) + (' …' if j < len(words) else '')


def _when(seconds):
    m = max(0, int(seconds // 60))
    return '%d мин' % m if m < 60 else '%d ч %02d мин' % (m // 60, m % 60)


def _atoms(text):
    try:
        return frozenset(_numbers(text)) | frozenset(_dated(text))
    except Exception:       # noqa: BLE001 - no alignment: digits only
        return frozenset('#' + d for d in __import__('re').findall(r'\d+', text))


Row = namedtuple('Row', 'pos tid text at toks nums norm who', defaults=(None,))      # one utterance of this call: a final of the room (``who`` None) or our answer (``who`` OURS, ``tid`` the answer's id); ``text`` clipped to index_chars; ``toks`` its stems in order; ``nums`` its numbers and dates, ``norm`` its normalised words
Card = namedtuple('Card', 'text chars parts ids lines nonempty')


class _Card(Card):
    __slots__ = ()

    def part(self, name):
        return list(self.lines.get(name, ()))


def _taken(r, asked):
    """M1-g: a record the projection takes as a row: the room's final (the newest of its turn; not the prompt said aloud, ``who`` BACK) or our answer; not superseded, with words."""
    if r.superseded or not r.text.strip():
        return False
    if r.kind == ANSWER:
        return True
    return r.kind == USER and not r.echo and getattr(r, 'who', None) is None and asked.get(r.tid) is r


class Projection:
    """A view of the ledger that can be erased (``clear``) and rebuilt from it at any moment; it holds nothing the ledger does not: the rows of the call's listener finals (clipped), their stems, an
    inverted index, the answered pairs, and (for retrieval) an in-memory FTS5 table. It follows the ledger by a signature of its records (a revised final, a superseded answer change it).
    A ledger that only grew at its end (new finals, new answers, in spoken order) is followed by appending to the projection; anything else (a revised or superseded record, a late delivery, records that fell off the
    ledger, another start of the call) rebuilds it whole. Both ways give the same projection (tests)."""

    def __init__(self, ledger, fts=True):
        self._led, self._want_fts, self._lock = ledger, fts, threading.RLock()
        self.clear()

    def clear(self):
        with self._lock:
            self._sig = self._since = self._ver = None
            self._rows, self._pairs, self._inv, self._total, self._now, self._rarity = [], [], {}, 0, 0.0, None
            self._cache = {}
            self._pos_of, self._asked, self._last, self._said, self._orphans, self._pair_key, self._ans_of = {}, {}, {}, set(), set(), None, {}
            self._db, self._fts_ok, self._start = None, True, 0.0

    def size(self):
        return len(self._rows)

    def rows(self):
        """The rows of the room's finals (our answers are rows of the index too, M1-g, and are not listed here)."""
        return [r for r in self._rows if r.who is None]

    def refresh(self, since=None):
        """Follow the ledger when it moved (or ``since`` did): append when it only grew at its end, else rebuild. Returns the effective start of the call."""
        with self._lock:
            on_records = getattr(self._led, 'on_records', None)      # M1-a: the start of the call on the clock of the records (the controller gives it on the engine's clock)
            since = on_records(since) if callable(on_records) else since
            ver = getattr(self._led, 'version', None)      # the ledger counts its changes: nothing changed since the last look, nothing to scan (the hot path of a request is a read)
            if ver is not None and ver == self._ver and since == self._since and self._sig is not None:
                return self._start
            records = self._led.records()
            sig =[(pos, r.kind, r.tid, r.ref, r.final_rev, r.superseded, r.echo, len(r.text), getattr(r, 'who', None)) for pos, r in enumerate(records) if r.kind in (USER, ANSWER)]
            old = self._sig
            if old is None or since != self._since or sig != old:
                grown = old is not None and since == self._since and len(sig) > len(old) and sig[:len(old)] == old
                if not (grown and self._append(records, [records[s[0]] for s in sig[len(old):]], [s[0] for s in sig[len(old):]], since)):
                    self._rebuild(records, since)
                self._sig, self._since = sig, since
            self._ver = ver
            return self._start

    def _rebuild(self, records, since):
        asked = {r.tid: r for r in records if r.kind == USER and not r.superseded and not r.echo}
        rows, pairs, cache, pos_of, last, ans_of = [], [], {}, {}, {}, {}
        mine = [(r.at, pos, r) for pos, r in enumerate(records) if _taken(r, asked) and (since is None or r.at >= since)]
        for _, pos, r in sorted(mine, key=lambda m: m[:2]):        # the spoken order (``at``), not the order the records were delivered in
            self._row(r, pos, rows, cache, last, pos_of, ans_of)
        said, key_of_last = set(), None
        for pos, r in sorted(((p, r) for p, r in enumerate(records) if r.kind == ANSWER and not r.superseded and r.tid in pos_of), key=lambda m: (m[1].at, m[0])):
            key_of_last = (r.at, pos)
            if (pos_of[r.tid], normalize(r.text)) not in said:       # the same answer re-sent is one answer
                said.add((pos_of[r.tid], normalize(r.text)))
                pairs.append((pos_of[r.tid], asked[r.tid].text, r))
        self._cache, self._rows, self._pairs = cache, rows, pairs
        self._pos_of, self._asked, self._last, self._said, self._pair_key, self._ans_of = pos_of, asked, last, said, key_of_last, ans_of
        self._orphans = {r.tid for r in records if r.kind == ANSWER and not r.superseded and r.tid not in pos_of}
        self._start = since if since is not None else (rows[0].at if rows else 0.0)
        self._now = max([r.at for r in records if r.kind in (USER, ANSWER)] or [0.0])
        inv = {}
        for i, row in enumerate(rows):
            for t, tf in Counter(row.toks).items():
                inv.setdefault(t, []).append((i, tf))
        self._inv, self._total, self._rarity = inv, sum(len(r.toks) for r in rows), None
        self._drop_db()

    def _append(self, records, fresh, where, since):
        """Take in records that stand after everything already taken, when that gives exactly what a rebuild would; False (the caller rebuilds) when it would not: a final spoken before the last one taken,
        an answer that sorts before the last pair, an answer that was waiting for a final that has come now. May leave the projection half done: the rebuild replaces all of it."""
        rows, pos_of, asked = self._rows, self._pos_of, self._asked
        mine = []
        for pos, r in zip(where, fresh):
            if r.kind == USER and not r.superseded and not r.echo:
                asked[r.tid] = r
            if _taken(r, asked) and (since is None or r.at >= since):
                mine.append((r.at, pos, r))
        mine.sort(key=lambda m: m[:2])
        if mine and rows and mine[0][0] < rows[-1].at:
            return False
        first = len(rows)
        added = []
        for _, pos, r in mine:
            if r.kind == USER and r.tid in self._orphans:
                return False
            row = self._row(r, pos, rows, self._cache, self._last, pos_of, self._ans_of)
            if row is not None:
                added.append(row)
        late = sorted(((p, r) for p, r in zip(where, fresh) if r.kind == ANSWER and not r.superseded), key=lambda m: (m[1].at, m[0]))
        for pos, r in late:
            if r.tid not in pos_of:
                self._orphans.add(r.tid)
                continue
            if self._pair_key is not None and (r.at, pos) < self._pair_key:
                return False
            self._pair_key = (r.at, pos)
            if (pos_of[r.tid], normalize(r.text)) not in self._said:
                self._said.add((pos_of[r.tid], normalize(r.text)))
                self._pairs.append((pos_of[r.tid], asked[r.tid].text, r))
        if since is None and not first and rows:
            self._start = rows[0].at
        self._now = max([self._now] + [r.at for r in fresh])
        for i, row in enumerate(added, first):
            for t, tf in Counter(row.toks).items():
                self._inv.setdefault(t, []).append((i, tf))
            self._total += len(row.toks)
        self._rarity = None
        if self._db is not None and added:
            try:
                self._db.executemany('INSERT INTO d(rowid, t) VALUES (?, ?)', ((i + 1, ' '.join(r.toks)) for i, r in enumerate(added, first)))
            except sqlite3.Error:
                self._drop_db()
        return True

    def _row(self, r, pos, rows, cache, last, pos_of, ans_of):
        """Add the row of ``r`` (a final of the room, or our answer: M1-g) unless it is the twin of one taken just before it (the same words re-sent under a new id within ``dup_s``: one
        utterance). Returns the row added, or None."""
        ours = r.kind == ANSWER
        text = ' '.join(r.text.split())[:START['index_chars']]
        key = ('a', r.ref) if ours else (r.tid, r.final_rev)
        toks, nums, norm = self._cache.get(key) or (tuple(stems(norm_words(text))), _atoms(text), normalize(text))
        cache[key] = (toks, nums, norm)
        index_of, name = (ans_of, r.ref) if ours else (pos_of, r.tid)
        twin = last.get((ours, norm))
        if twin is not None and r.at - rows[twin].at <= START['dup_s']:
            index_of[name] = twin
            return None
        index_of[name] = last[(ours, norm)] = len(rows)
        row = Row(pos, str(name), text, r.at, toks, nums, norm, OURS if ours else None)
        rows.append(row)
        return row

    def _drop_db(self):
        if self._db is not None:
            try:
                self._db.close()
            except sqlite3.Error:
                pass
        self._db = None

    # --- reading ---
    @property
    def now(self):
        return self._now

    def pairs(self):
        """The answered exchanges in the order of their answers: ``(index of the question's row, the question's words, the answer's record)``."""
        return list(self._pairs)

    def df(self, token):
        return len(self._inv.get(token, ()))

    def rarity(self):
        """``[score]`` per row: the rarity of its distinct words in this call (sum of ln((N + 1) / (df + 1)) over them, over the square root of their count). Kept until the ledger moves."""
        if self._rarity is None:
            n = len(self._rows)
            idf = {t: math.log((n + 1) / (len(h) + 1)) for t, h in self._inv.items()}
            self._rarity = [(sum(idf[t] for t in set(r.toks)) / math.sqrt(len(set(r.toks)))) if r.toks else 0.0 for r in self._rows]
        return self._rarity

    def _scores_plain(self, query):
        """bm25 exactly as FTS5 computes it (idf = ln((N - n + .5) / (n + .5)), floored at 1e-6; k1 1.2, b .75), summed over the distinct query words, positive = better."""
        n_rows = len(self._rows)
        avg = (self._total / n_rows) if n_rows else 0.0
        out = {}
        for t in query:
            hits = self._inv.get(t, ())
            if not hits:
                continue
            idf = math.log((n_rows - len(hits) + 0.5) / (len(hits) + 0.5))
            idf = idf if idf > 0 else 1e-6
            for i, tf in hits:
                dl = len(self._rows[i].toks)
                out[i] = out.get(i, 0.0) + idf * (tf * (_BM25_K1 + 1)) / (tf + _BM25_K1 * (1 - _BM25_B + _BM25_B * dl / avg))
        return out

    def _scores_fts(self, query):
        try:
            if self._db is None:
                db = sqlite3.connect(':memory:', check_same_thread=False)
                db.execute('CREATE VIRTUAL TABLE d USING fts5(t, tokenize="unicode61 remove_diacritics 0")')
                db.executemany('INSERT INTO d(rowid, t) VALUES (?, ?)', ((i + 1, ' '.join(r.toks)) for i, r in enumerate(self._rows)))
                self._db = db
            marks = ' OR '.join('"%s"' % t.replace('"', '') for t in query)
            return {rowid - 1: -score for rowid, score in self._db.execute('SELECT rowid, bm25(d) FROM d WHERE d MATCH ?', (marks,))}
        except sqlite3.Error:
            self._fts_ok = False
            self._drop_db()
            return None

    def scores(self, query):
        """``{row index: bm25}`` for the rows that hold at least one of the ``query`` words: by FTS5 when it is there, else by the plain index (the same numbers)."""
        if not query:
            return {}
        found = self._scores_fts(query) if self._fts_ok and self._want_fts else None
        return found if found is not None else self._scores_plain(query)


def _clean(text):
    return ' '.join(str(text or '').split())


class _Builder:
    """The card under the budget: sections in priority order; ``take`` adds the units of one section that fit (a unit is whole or not there)."""

    def __init__(self, budget):
        self.budget, self.sections, self.used, self.seen = budget, [], 0, set()

    def cost(self, head, units):
        return len(head) + sum(1 + len(u) for u in units) + (2 if self.sections else 0)

    def room(self):
        return self.budget - self.used - (2 if self.sections else 0)

    def take(self, head, units, cap=None):
        """The longest prefix of ``units`` (in priority order) that fits the room and ``cap``; the section is not added here."""
        limit = min(self.budget - self.used, cap if cap is not None else self.budget)
        out, size = [], len(head) + (2 if self.sections else 0)
        for u in units:
            if size + 1 + len(u) > limit:
                break
            out.append(u)
            size += 1 + len(u)
        return out

    def add(self, head, units):
        if units:
            self.used += self.cost(head, units)
            self.sections.append(head + '\n' + '\n'.join(units))


def _query(rows, question, last_turns=2):
    """The words of the question, and the words of the last turns that the question does not have (they weigh less: ``turn_weight``)."""
    qtoks = tuple(dict.fromkeys(stems(norm_words(question))))
    return qtoks, tuple(t for t in dict.fromkeys(t for r in rows[-last_turns:] for t in r.toks) if t not in qtoks)


def _is_question(row, qnorm):
    rn = row.norm
    if not rn or (rn != qnorm and rn not in qnorm and qnorm not in rn):      # none of the three holds without one text inside the other
        return False
    return rn == qnorm or (len(rn.split()) >= 2 and rn in qnorm) or (len(qnorm.split()) >= 3 and qnorm in rn)


def build_card(ledger, question, *, since=None, budget=None, step_min=None, lines=None, line_chars=None, pinned=(), carry='', history=(), played=None, fts=True, projection=None):
    """The card for ONE model request, from the ledger only (``history`` entries of the old block stand in only when the ledger holds no exchange). Pure: the same ledger, question and numbers give the same card."""
    budget = int(budget or START['chars'])
    step = int(step_min or START['step_min'])
    n_lines = START['lines'] if lines is None else int(lines)
    line_chars = int(line_chars or START['line_chars'])
    proj = projection if projection is not None else Projection(ledger, fts=fts)
    with proj._lock:
        start = proj.refresh(since)
        return _assemble(proj, start, question, budget, step, n_lines, line_chars, pinned, carry, history, played)


def _render(item, n):
    kind, q, a, mark = item[1:5]
    return 'Прозвучало без ответа: %s' % fit(q, n) if kind == 'un' else 'Вопрос: %s\nОтвет: %s%s' % (fit(q, n), fit(a, n), mark)


def _line(r, start, line_chars, keys=()):
    head = '- %s, %s: «' % (_when(r.at - start), r.who or SPEAKER)
    body = window(r.text, max(0, line_chars - len(head) - 1), keys)
    return head + body + '»' if body else ''


def _assemble(proj, start, question, budget, step, n_lines, line_chars, pinned, carry, history, played):
    rows = proj._rows
    qnorm = normalize(question)
    qrows = {i for i, r in enumerate(rows) if r.who is None and _is_question(r, qnorm)}
    uid = lambda i: ('a:' if rows[i].who else 'u:') + rows[i].tid[:24]      # noqa: E731
    b, lines, ids = _Builder(budget), {}, {}

    # 1 pinned: forced, bounded by their own caps
    pins = [p for p in (fit(p, START['pinned_line']) for p in list(pinned or ())[:START['pinned_lines']]) if p]
    pins = b.take(HEAD['pinned'], pins) or ([x] if pins and (x := fit(pins[0], budget - len(HEAD['pinned']) - 1)) else [])      # the budget is above the pins: a pin that does not fit is shortened or goes
    b.add(HEAD['pinned'], pins)
    lines['pinned'] = pins

    # 2 the newest exchanges, word for word. Items: (row indexes, kind, question, answer, revised mark, ids)
    key = (_clean(played[0]), _clean(played[1])) if played else None
    items, played_rows = [], set()
    for qi, qtext, ans in proj._pairs:
        both = [qi] + ([proj._ans_of[ans.ref]] if ans.ref in proj._ans_of else [])      # M1-g: the answer's own row is told by its pair
        if key and (_clean(qtext), _clean(ans.text)) == key:
            played_rows.update(both)         # the answer in play is told in the input of the request, not twice
        else:
            items.append((both, 'qa', qtext, ans.text, '', [uid(qi), 'a:' + str(ans.ref)[:24]]))
    entries = [e for e in (history or ()) if isinstance(e, dict)]
    n_keep, width = START['exchanges'], START['reply_chars']
    if entries:       # the old block was already cut by the channel (the short brain: 3 exchanges of 200 characters): the card never says more than it did
        n_keep, width = min(n_keep, len(entries)), min(width, max(len(_clean(e.get(k))) for e in entries for k in ('question', 'answer')))
    items = items[-n_keep:]
    last_q = max((qi for qi, _, _ in proj._pairs), default=-1)
    for i in [i for i, r in enumerate(rows) if i > last_q and i not in qrows and r.who is None and len(r.toks) >= START['unanswered_words']][-START['unanswered']:]:
        items.append(([i], 'un', rows[i].text, '', '', [uid(i)]))
    if not items and history and rows:       # the ledger holds finals but no exchange (answers not fed): the entries of the old block stand in; a ledger with nothing in it makes an empty card
        items = _from_history(history)
    cap = int(budget * START['history_share'])
    chosen = b.take(HEAD['exchanges'], [_render(it, width) for it in reversed(items)], cap)      # newest first
    kept_items = items[len(items) - len(chosen):] if chosen else []
    if items and not chosen:        # even the newest does not fit as it is: its two sides are shortened once
        side = max(40, (min(cap, b.room()) - len(HEAD['exchanges']) - 16) // 2)
        chosen = b.take(HEAD['exchanges'], [_render(items[-1], side)], cap)
        kept_items = items[-1:] if chosen else []
    chosen.reverse()
    b.add(HEAD['exchanges'], chosen)
    lines['exchanges'] = [l for u in chosen for l in u.split('\n')]
    ids['exchanges'] = [x for it in kept_items for x in it[5]]
    shown = qrows | played_rows | {i for it in kept_items for i in it[0]}

    # 3 retrieved, 4 exact: one query, one scoring, the words of the question and of the last turns
    qtoks, ttoks = _query([r for i, r in enumerate(rows) if i not in qrows and r.who is None] or rows, question)
    n_rows = len(rows)
    common_of = {}      # one answer per word for the whole request (the stems of a call are a few dozens, its rows are thousands)
    common = lambda t: common_of[t] if t in common_of else common_of.setdefault(t, n_rows >= START['common_from'] and proj.df(t) > START['common_df'] * n_rows)      # noqa: E731 - rarity in THIS call, no word list
    keys = frozenset(t for t in qtoks + ttoks if not common(t))      # E19: the clues a clipped line is cut around are the rare words of the question, as for retrieval (a word of every second utterance clips nothing)
    by_question = proj.scores(tuple(t for t in qtoks if not common(t)))
    by_turns = proj.scores(tuple(t for t in ttoks if not common(t)))
    ranked = []
    for i in set(by_question) | set(by_turns):
        s = by_question.get(i, 0.0) + START['turn_weight'] * by_turns.get(i, 0.0)
        if i not in shown and s > 0:
            age = max(0.0, (proj.now - rows[i].at) / 60.0)
            ranked.append((round(s * (1 + START['recency_weight'] * 0.5 ** (age / START['half_life_min'])), 9), i))
    ranked.sort(key=lambda p: (-p[0], -p[1]))
    ranked = [p for p in ranked if p[0] >= ranked[0][0] * START['rel_floor']] if ranked else []
    exact = _exact(rows, shown, frozenset(t for t in qtoks if not common(t)), _atoms(question), {i for _, i in ranked[:n_lines]}, common)
    got = []
    for _, i in ranked:
        if len(got) < n_lines and i not in exact:
            got.append(i)
    fixed = _corrected(rows, set(got) | set(exact), common)       # U88: an old value and its correction are told together, in spoken order under the heading of the exact things, never split across parts
    pulled = set(fixed) | set(fixed.values())
    got, exact = [i for i in got if i not in pulled], sorted(set(exact) | pulled)
    taken = set(_place(b, 'retrieved', rows, start, line_chars, got, lines, ids, uid, False, keys))
    taken |= set(_place(b, 'exact', rows, start, line_chars, exact, lines, ids, uid, True, keys))

    # 4b one-research (OWNER_REQUIREMENTS U-new-8): the window of the last START['window'] utterances of BOTH sides in spoken order (newest kept first when the room is short), and the
    # window before it in one brief line. Placed after the exact things: retrieval and the numbers choose as before, the window takes what they left (nothing twice).
    n_win = START['window']
    win = [i for i in range(max(0, len(rows) - n_win), len(rows)) if i not in shown and rows[i].norm not in b.seen]
    later = _corrected(rows, set(win) | set(got) | set(exact), common)
    gone = set(later) | set(fixed)
    win = [i for i in win if i not in later or later[i] in win]      # U88: here too an old value stands only with its correction below it (the window is in spoken order); one corrected above is not told again
    pairs, norms = [], set()
    room = min(b.budget - b.used, int(budget * START['window_share'])) - len(HEAD['window']) - (2 if b.sections else 0)
    per = max(START['window_line_min'], room // max(1, len(win)) - 1)      # U138: the last 15 are ALL in the window: when whole lines would not fit the share, every line is clipped to its equal part of it (window() keeps the clues), not the oldest dropped
    for i in reversed(win):              # the same words twice are not shown twice (as ``_place``): the newest stands
        line = _line(rows[i], start, min(line_chars, per))
        if line and rows[i].norm not in norms:
            norms.add(rows[i].norm)
            pairs.append((i, line))
    got = b.take(HEAD['window'], [l for _, l in pairs], int(budget * START['window_share']))
    kept = sorted(pairs[:len(got)])
    b.add(HEAD['window'], [l for _, l in kept])
    lines['window'], ids['window'] = [l for _, l in kept], [uid(i) for i, _ in kept]
    for i, _ in kept:
        b.seen.add(rows[i].norm)
    shown = shown | taken | {i for i, _ in kept}
    before = [i for i in range(max(0, len(rows) - 2 * n_win), max(0, len(rows) - n_win)) if i not in shown]
    brief = fit('; '.join(('%s: ' % rows[i].who if rows[i].who else '') + fit(rows[i].text, START['brief_head']) for i in before), START['brief_chars']) if before else ''
    got = b.take(HEAD['brief'], [brief] if brief else [])
    b.add(HEAD['brief'], got)
    lines['brief'], ids['brief'] = got, [uid(i) for i in before] if got else []

    # 5 outline: its own small budget, and only what the room above leaves
    starved = bool(pairs and not kept) or bool(brief and not lines['brief'])      # the order of PARTS is the order of priority: a part above that found no room takes the outline's away too (a bigger budget never loses a part)
    out_cap = 0 if starved else min(int(budget * START['outline_share']), b.room())
    out = _outline(rows, proj.rarity(), shown | taken | gone | {i for i, r in enumerate(rows) if r.norm in b.seen or r.who is not None}, start, step, out_cap - len(HEAD['outline']) - 2, line_chars)      # M1-g: the outline is the room's
    got = b.take(HEAD['outline'], [t for _, t in out], out_cap)
    b.add(HEAD['outline'], got)
    lines['outline'], ids['outline'] = got, [uid(i) for i, _ in out[:len(got)]]

    # 6 carry: as the old code had it, whole lines or none
    carry_lines = [l for l in str(carry or '').split('\n') if l.strip()]
    if carry_lines and carry_lines[0] == HEAD['carry']:
        carry_lines = carry_lines[1:]
    got = b.take(HEAD['carry'], carry_lines, START['carry_chars'])
    b.add(HEAD['carry'], got)
    lines['carry'] = got

    text = '\n\n'.join(b.sections)
    parts = {n: len(lines.get(n, ())) for n in PARTS}
    parts['exchanges'] = len(kept_items)
    for n in PARTS:
        ids.setdefault(n, [])
    return _Card(text, len(text), parts, ids, lines, any(parts[n] for n in ('exchanges', 'retrieved', 'exact', 'outline')))


def _place(b, name, rows, start, line_chars, idx, lines, ids, uid, newest_first, keys=()):
    """Fit as many of the rows ``idx`` (priority order; for exact things the newest first) as the room holds; shown in spoken order. Returns the indexes shown."""
    pairs, seen = [], b.seen
    for i in (sorted(idx, reverse=True) if newest_first else idx):
        line, norm = _line(rows[i], start, line_chars, keys), rows[i].norm
        if line and norm not in seen:        # the same words twice are not shown twice
            seen.add(norm)
            pairs.append((i, line))
    got = b.take(HEAD[name], [t for _, t in pairs])
    shown = sorted(pairs[:len(got)])
    b.add(HEAD[name], [t for _, t in shown])
    lines[name], ids[name] = [t for _, t in shown], [uid(i) for i, _ in shown]
    return [i for i, _ in shown]


def _from_history(history):
    try:
        from .fast_text import REVISED_MARK
    except Exception:       # noqa: BLE001
        REVISED_MARK = ''
    out = []
    for entry in list(history or ())[-START['exchanges']:]:
        if not isinstance(entry, dict):
            continue
        q, a = _clean(entry.get('question')), _clean(entry.get('answer'))
        if q and entry.get('unanswered'):
            out.append(([], 'un', q, '', '', []))
        elif q and a:
            out.append(([], 'qa', q, a, REVISED_MARK if entry.get('status') == 'revised' else '', []))
    return out


def _corrected(rows, idx, common):
    """``{old: correction}`` over the rows ``idx``: a later row of ``idx`` corrects an earlier one when it is the room's own words, holds every number of the earlier one and more, and shares a rare word with it (the correction
    «не 500, а 700» holds 500). U88 (the coordinator's decision of 15.11): both are told, the correction AFTER the old value, under a heading that says the correction stands; the old value never stands alone."""
    out = {}
    for i in sorted(idx):
        if rows[i].nums:
            j = next((j for j in sorted(idx) if j > i and rows[j].who is None and rows[i].nums < rows[j].nums and any(not common(t) for t in set(rows[i].toks) & set(rows[j].toks))), None)
            if j is not None:
                out[i] = j
    return out


def _exact(rows, shown, qrare, qnums, top, common):
    """Row indexes of the exact things: utterances with numbers or dates that bear on the question (they share a number or a rare word with it), and the LATER number-carrying utterances that share a
    number or a rare word with one already chosen (a correction), grouped in chains. A chain of two or more is always claimed; a lone one only if retrieval does not already carry it."""
    # M1-c: one pass over the rows, each looked up by its own numbers and rare words (``holder``: the first chosen row that has it; every chosen row that has it is in that row's chain,
    # so one is enough), chains joined by union-find: the cost of a request grows with the call, not with its square (it compared every row with every chosen row).
    chosen, parent, holder, chains, seeds = [], {}, {}, {}, set()

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for i, r in enumerate(rows):
        if not r.nums or i in shown:
            continue
        words = set(r.toks)
        keys = [(0, n) for n in r.nums] + [(1, t) for t in words if not common(t)]
        linked = [holder[k] for k in keys if k in holder]
        seed = bool(r.nums & qnums or qrare & words)
        if not (linked or seed):
            continue
        if seed:
            seeds.add(i)
        chosen.append(i)
        parent[i] = i
        for j in linked:            # two chains meet: one chain
            a, b = root(j), root(i)
            if a != b:
                parent[max(a, b)] = min(a, b)
        for k in keys:
            holder.setdefault(k, i)
    for i in chosen:
        chains.setdefault(root(i), []).append(i)
    members = [m for c in chains.values() for m in (c if len(c) > 1 or c[0] not in top else ())]
    members.sort()
    if len(members) > START['exact_lines']:       # whole chains, the newest first, never half a chain unless one chain is longer than the cap
        keep = []
        for c in sorted((c for c in chains.values() if len(c) > 1 or c[0] not in top), key=lambda c: -c[-1]):
            if len(keep) + len(c) <= START['exact_lines']:
                keep += c
            elif not keep:      # M1-g: a chain longer than the cap keeps what bears on the question itself (its seeds, the newest first), then its newest links
                keep = sorted(c, key=lambda i: (i not in seeds, -i))[:START['exact_lines']]
        members = sorted(keep)
    return members


def _outline(rows, rarity, taken, start, step_min, cap, line_chars):
    """``[(row index, line)]`` in spoken order: for every step one or two utterances by the rarity of their words in this call; if the lines do not fit ``cap``, one per step, then the steps grow (by a quarter, or in proportion to what is over)."""
    n = len(rows)
    if cap <= 0 or not n:
        return []
    pool = [i for i, r in enumerate(rows) if i not in taken and len(r.toks) >= 3]
    span = max(1, int(step_min)) * 60.0

    made = {}

    def line_of(i):
        if i not in made:
            head = '- %s, %s: «' % (_when(rows[i].at - start), SPEAKER)
            body = fit(rows[i].text, max(0, line_chars - len(head) - 1))
            made[i] = (i, head + body + '»') if body else None
        return made[i]

    def pick(mult):
        """``(two per busy step, one per step)``"""
        by = {}
        for i in pool:
            by.setdefault(int((rows[i].at - start) // (span * mult)), []).append(i)
        one, two = [], []
        for key, idx in sorted(by.items()):
            mid, half = (key + 0.5) * span * mult + start, span * mult * START['outline_core'] / 2
            core = [i for i in idx if abs(rows[i].at - mid) <= half] or idx      # the rarest of the middle of the step: no stretch of the call is left further than ~3/4 of a step from a line
            top = sorted(core, key=lambda i: (-rarity[i], i))
            one += top[:1]
            two += top[:2 if len(idx) >= START['outline_two'] else 1]
        return [x for x in map(line_of, sorted(two)) if x], [x for x in map(line_of, sorted(one)) if x]

    best, mult = [], 1.0
    while True:
        for lines in pick(mult):
            size = sum(1 + len(t) for _, t in lines)
            if size <= cap:
                return lines
            best = lines
        if mult * span > (rows[-1].at - start + span):
            break
        mult *= max(1.25, min(2.0, size / cap))
    out, size = [], 0
    for i, t in best:
        if size + 1 + len(t) > cap:
            break
        out.append((i, t))
        size += 1 + len(t)
    return out


class Memory:
    """The hook of the channel: ``FastText.card = memory.apply``. Reads the ledger of the controller (it may appear after the call opens), keeps one projection per ledger."""

    def __init__(self, settings, controller, note=None, pinned=None, timer=time.perf_counter, fts=True):
        self.budget = int(settings.get('v6_memory_chars', START['chars']))
        self.step = int(settings.get('v6_memory_step_min', START['step_min']))
        self.lines = int(settings.get('v6_memory_lines', START['lines']))
        self._c, self._note_fn, self._pinned, self._timer, self._fts = controller, note, pinned, timer, fts
        self._proj = self._proj_of = None
        self._sent_total = 0          # M1-d: characters of memory sent to the model in this call so far (numbers only, no words)

    def _note(self, ev, **fields):
        if self._note_fn is not None:
            try:
                self._note_fn(ev, **fields)
            except Exception:       # noqa: BLE001 - the journal never costs the call
                pass

    def _projection(self, ledger):
        if self._proj is None or self._proj_of is not ledger:
            self._proj, self._proj_of = Projection(ledger, fts=self._fts), ledger
        return self._proj

    @staticmethod
    def _call(fn):
        try:
            return str(fn() or '') if callable(fn) else ''
        except Exception:       # noqa: BLE001
            return ''

    def prepare(self):
        """The controller calls it when it has written to the ledger (a final, an answer): the projection follows the ledger THEN, so that the request of a question only reads it (a rebuild of a revised or superseded record is paid
        here, not in the hook). Never raises."""
        try:
            ledger = getattr(self._c, 'convo', None)
            if ledger is not None:
                proj = self._projection(ledger)
                with proj._lock:
                    proj.refresh(getattr(self._c, 'memory_began', getattr(self._c, 'call_began', None)))
                    proj.rarity()      # the rarity of the words of the call is the one number that grows with the call: made here, when the words are written
        except Exception:       # noqa: BLE001 - the request builds it itself then
            pass

    def apply(self, fast, text, instructions, history):
        """The one call at the one point of ``FastText._start``: ``(instructions, history)`` back; with a non-empty card, the card in place of the old blocks; no ledger or an empty card: as they came."""
        ledger = getattr(self._c, 'convo', None)
        if ledger is None:
            return instructions, history
        try:
            began = self._timer()
            pins = self._pinned() if callable(self._pinned) else ()
            old_carry = self._call(getattr(fast, 'carry', None))
            found = self._call(lambda: ledger.recap_calls(question=text, only_found=True))      # U139: the day memory is searched by the words of the question
            carry = found or old_carry
            try:
                played = fast._played()
            except Exception:       # noqa: BLE001
                played = None
            since = getattr(self._c, 'memory_began', getattr(self._c, 'call_began', None))      # M1-e2: the start of the conversation (a redial goes on with it)
            card = build_card(ledger, text, since=since, budget=self.budget, step_min=self.step, lines=self.lines, pinned=pins, carry=carry,
                              history=history, played=played, fts=self._fts, projection=self._projection(ledger))
            ms = round((self._timer() - began) * 1000)
            sent = card.text if card.nonempty or (found and card.part('carry')) else ''      # M1-d: what of the memory goes out in this request (shadow and an empty card: nothing)
            if not sent and old_carry and instructions.endswith('\n\n' + old_carry):
                sent = old_carry
            self._sent_total += len(sent)
            self._note('memory_card', mode='on', budget=self.budget, chars=card.chars, ms=ms, parts=dict(card.parts), ids={k: list(v) for k, v in card.ids.items()}, fts=self._proj._fts_ok and self._fts,
                       sent_chars=len(sent), sent_lines=sent.count('\n') + 1 if sent else 0, sent_total_chars=self._sent_total)
            if not sent:
                return instructions, history
            if old_carry and instructions.endswith('\n\n' + old_carry):          # the old block stands at the end of the instructions; the card holds its place
                instructions = instructions[:-len(old_carry) - 2]
            return instructions + '\n\n' + card.text, []
        except Exception as error:       # noqa: BLE001 - the old request, one line in the journal
            self._note('memory_card_fail', mode='on', error=type(error).__name__)
            return instructions, history


def attach(settings, controller, *, note=None, pinned=None, timer=time.perf_counter, fts=True):
    """The ``Memory`` whose ``apply`` is the hook of the channel (always: memory is not a switch)."""
    memory = Memory(settings, controller, note=note, pinned=pinned, timer=timer, fts=fts)
    controller.memory_ready = memory.prepare      # the controller tells it when the ledger was written (``ControlledMedia._memory_ready``)
    return memory
