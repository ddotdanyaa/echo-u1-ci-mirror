"""U14 conversation ledger (memory core). Pure: no clock of its own beyond ``at``, no I/O, not wired to anything yet.
Who writes what: the provider writes the listener's final words (``user_final``, with the ``final_rev`` U15 ``Resolutions`` hands out), the engine writes answers, the X-CUE source writes what was played
(``play_began`` / ``play_done`` / ``play_cut``). The ledger has no identity rules of its own: it drops only an exact (tid, final_rev) duplicate; a newer final_rev of the same tid replaces the older text.
What was heard of a cut portion: ``heard_s = clamp(cut - began - PLAY_LAG_S, 0, voiced_s)``, turned into words by syllables."""
import datetime
import importlib
import json
import logging
import math
import re
import time
from collections import deque, namedtuple
from pathlib import Path

from .textutil import WORDS, norm_words, stems, syllables
from . import timer_policy
from .timer_policy import CONVERSATION_GAP_S      # M1-e2, «стартовое»: the figure is timer_policy's

LEDGER_HOT = 6000            # records kept in memory
PLAY_LAG_S = 0.35            # estimate: from the cue's start to the first sound at the listener's ear (to be replaced by SAPI marks)
LEDGER_DAY_BYTES = 8_000_000  # one day file stops growing here (memory goes on)
LEDGER_KEEP_DAYS = 14        # day files older than this are removed (only files that match the name pattern)
LEDGER_CARRY_S = 36 * 3600   # U14-S8: how far back the recap of earlier calls reaches
RECAP_CHARS = 600            # U14-S8: the recap is never longer than this

logger = logging.getLogger('echo-sync')
_DAY_FILE = re.compile(r'^ledger-(\d{4}-\d{2}-\d{2})\.jsonl$')

Rec = namedtuple('Rec', 'kind tid text at final_rev echo ref superseded wall who', defaults=(None, False, None, False, None, None))
USER, CLOUD, ANSWER, PLAY = 'user', 'cloud', 'answer', 'play'
BACK = 'back'      # M1-g: ``who`` of a listener's final that is the prompt said aloud (the judge's ack): our words in the owner's voice, not the room's. None: the room
_SENTENCE_END = '.!?…'


# M9 / slot S4: what the call HOLDS beside its conversation rows (a topic, a promise, a carry) is a kind of the ledger. ONE table, one writer (``hold``), one reader (``held``), one end (``end``).
#   ttl_key      ``module.NAME`` of a time constant that ``timer_policy.TIMERS`` holds: how long the item lives (a kind with no row of the clock does not exist)
#   binds_to     'tid': the item belongs to a question (it ends when ``expire`` is told that turn is no longer live); 'epoch': it belongs to the epoch of the controller (a new epoch ends it)
#   end_reasons  why it may end (``END_REASONS``): ``end(kind, key, reason)`` with another reason is refused; ``expired`` must be there (the TTL is a reason)
# A new thing to hold is one row here; ``ControlledMedia`` expires it on its tick (``cm_memory``) and never learns its name.
END_REASONS = frozenset({'expired', 'epoch', 'superseded', 'call', 'answered', 'dropped'})
Kind = namedtuple('Kind', 'ttl_key binds_to end_reasons')
KINDS = {
    'dictation': Kind('conversation_ledger.LEDGER_CARRY_S', 'epoch', ('expired',)),      # dictation-carry: what the owner said of dictation and the tempo of writing learned from them; a redial of the session goes on with them, a new call does not end them
    'final': Kind('timer_policy.RECONNECT_WINDOW_S', 'epoch', ('expired',)),      # cm-call-carry (U91): the last final a question was opened for, so that the cloud's repeat of it over a redialled line (same turn, same words, the earlier call closed) opens no second question
    'topic': Kind('conversation_ledger.LEDGER_CARRY_S', 'tid', ('expired', 'call', 'superseded')),      # lookup-topic: what a follow-up («а почему?») is about; a new call starts without it (A4)
}


def kind_problems(kinds=None):
    """The rows of ``KINDS`` (or of ``kinds``) that break the rules: a TTL that ``timer_policy`` does not hold, no ``expired`` reason, a reason or a binding the ledger does not know. Must be []."""
    out = []
    for name, k in (KINDS if kinds is None else kinds).items():
        if k.ttl_key not in timer_policy.TIMERS:
            out.append('%s: ttl_key %s is not in timer_policy.TIMERS' % (name, k.ttl_key))
        if k.binds_to not in ('tid', 'epoch'):
            out.append('%s: binds_to %r' % (name, k.binds_to))
        if 'expired' not in k.end_reasons or not set(k.end_reasons) <= END_REASONS:
            out.append('%s: end_reasons %r' % (name, k.end_reasons))
    return out


def kind_ttl(name):
    """Seconds a held item of kind ``name`` lives: the constant ``ttl_key`` names, read when asked (a test or the owner's profile may move it)."""
    key = KINDS[name].ttl_key
    if key not in timer_policy.TIMERS:
        raise KeyError('kind %r: %s is not a timer of timer_policy' % (name, key))
    module, const = key.split('.', 1)
    value = float(getattr(importlib.import_module('.' + module, __package__), const))
    return value / 1000.0 if timer_policy.TIMERS[key] == 'ms' else value


def _words(text):
    return [m.group() for m in WORDS.finditer(str(text or ''))]


def _clip(text, n):
    text = ' '.join(str(text or '').split())
    return text if len(text) <= n else text[:n - 1].rstrip() + '…'


def _heard_count(words, fraction):
    """How many leading words lie fully inside the first ``fraction`` of the syllables."""
    sylls = [max(1, syllables(w)) for w in words]
    budget = sum(sylls) * max(0.0, min(1.0, fraction)) + 1e-9
    used = n = 0
    for s in sylls:
        if used + s > budget:
            break
        used += s
        n += 1
    return n


class ConversationLedger:
    def __init__(self, hot=LEDGER_HOT, lag_s=PLAY_LAG_S, directory=None, wall=time.time, keep_days=LEDGER_KEEP_DAYS, day_bytes=LEDGER_DAY_BYTES, since_on_wall=False):
        """``since_on_wall``: the start of a call the readers are given (``recap``, ``v6_memory.Projection``) is on the ledger's ``wall`` clock (the controller's ``call_began`` is the
        engine's clock, and the controller gives the ledger that clock as ``wall``), not on the clock of the records' ``at`` (``on_records`` turns one into the other). Off: ``since`` is on ``at``."""
        self._dir = Path(directory) if directory else None
        self._wall = wall
        self._since_wall = bool(since_on_wall)
        self._opened = None          # (at, wall) of the last ``open_call``: the two clocks read at one moment
        self._last_before = self._began = None      # M1-e2: the newest record's wall time when the last call opened; the start of the conversation (``conversation``)
        self._day_bytes = day_bytes
        self._disk_ok = self._dir is not None
        self._capped = set()         # day files that reached the cap
        self._replaying = False
        self._recap_key = self._recap_text = None   # U14-S10
        self._rw = None              # the wall time of the line being replayed
        self._open_w = None          # the wall time this call was opened (None: no call opened here)
        self._hot, self._recs, self._nconv, self._nplay = hot, deque(), 0, 0      # U89c: ``hot`` counts the conversation rows only; the playback rows have a quarter of it besides
        self._evicted = 0            # records that fell off the left end (absolute position = index + this)
        self._latest = {}            # (kind, key) -> absolute position of the newest record: a revision finds its predecessor without a scan
        self._seen = set()           # (tid, final_rev) already written
        self._held = {}              # M9: (kind, key) -> [tid, text, at, epoch] of what the call holds (``hold``)
        self._epoch = None           # the epoch ``expire`` saw last
        self.version = 0             # counts every change of the records (a reader that saw this number has seen everything: ``v6_memory.Projection`` does not scan the ledger for nothing)
        self._plays = {}             # cue -> dict(words, began, voiced_s, end, heard_n)
        self._lag = lag_s
        if self._disk_ok:
            self._prune(keep_days)
            if self._disk_ok:
                self._load(hot)

    # --- disk tier: one JSONL file per day, append-only; a failure turns the disk off once and memory goes on ---
    def _fail(self, why):
        if self._disk_ok:
            self._disk_ok = False
            logger.warning('conversation ledger: disk off, memory only (%s)', why)

    def _prune(self, keep_days):
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            edge = datetime.date.fromtimestamp(self._wall()) - datetime.timedelta(days=keep_days)
            for f in self._dir.iterdir():
                m = _DAY_FILE.match(f.name)
                if m and datetime.date.fromisoformat(m.group(1)) < edge:
                    f.unlink()
        except (OSError, ValueError) as e:
            self._fail(e)

    def _load(self, hot):
        """The tail of the newest day files, oldest first, replayed through the ordinary methods."""
        try:
            files = sorted((f for f in self._dir.iterdir() if _DAY_FILE.match(f.name)), key=lambda f: f.name)
            lines = []
            for f in reversed(files):
                lines = f.read_text(encoding='utf-8', errors='replace').splitlines() + lines
                if len(lines) >= hot:
                    break
        except OSError as e:
            self._fail(e)
            return
        self._replaying = True
        try:
            for line in lines[-hot:]:
                try:
                    self._replay(json.loads(line))
                except (ValueError, KeyError, TypeError):
                    continue            # a torn or foreign line is skipped
        finally:
            self._replaying = False

    def _replay(self, d):
        k = d['k']
        self._rw = d.get('w')
        if k == USER:
            self.user_final(d['tid'], d['text'], final_rev=d['rev'], echo=d.get('echo', False), at=d['at'], who=d.get('who'))
        elif k == ANSWER:
            self.answer(d['aid'], d['text'], tid=d.get('tid'), supersedes=d.get('sup'), at=d['at'])
        elif k == PLAY:
            self.play_began(d['cue'], d['text'], d['at'], d.get('voiced'))
        elif k == 'end':
            self._end(d['cue'], d['how'], d['at'])
        elif k == 'who':
            self._mark(d['tid'], d['rev'], d.get('who'))

    def _stamp(self):
        return self._rw if self._replaying else self._wall()

    def _write(self, d):
        if not self._disk_ok or self._replaying:
            return
        d = dict(d, w=self._wall())
        name = 'ledger-%s.jsonl' % time.strftime('%Y-%m-%d', time.localtime(self._wall()))
        if name in self._capped:
            return
        path = self._dir / name
        try:
            line = json.dumps(d, ensure_ascii=False, separators=(',', ':')) + '\n'
            if path.exists() and path.stat().st_size + len(line.encode('utf-8')) > self._day_bytes:
                self._capped.add(name)
                logger.warning('conversation ledger: %s reached the day cap, memory only for the rest of the day', name)
                return
            with open(path, 'a', encoding='utf-8') as fh:
                fh.write(line)
        except OSError as e:
            self._fail(e)

    def _add(self, rec, key=None):
        self.version += 1
        self._recs.append(rec)
        if rec.kind == PLAY:
            self._nplay += 1
            if self._nplay > self._hot // 4:      # U89c: the cues have a quarter of the room beside the conversation rows (a long call speaks thousands, only the last ones are read): the oldest quarter of them goes, from wherever it stands (a rare compaction)
                cut, kept = self._nplay // 4, deque()
                for r in self._recs:
                    if r.kind == PLAY and cut > 0:
                        cut -= 1
                        self._plays.pop(r.ref, None)
                    else:
                        kept.append(r)
                self._recs, self._evicted, self._nplay = kept, 0, sum(r.kind == PLAY for r in kept)
                self._latest = {(r.kind, r.ref if r.kind == ANSWER else r.tid): i for i, r in enumerate(kept) if r.kind != PLAY}      # the positions of the newest records of a key, made again
        else:
            self._nconv += 1
            while self._nconv > self._hot:      # the oldest conversation row goes, with whatever cues stand before it
                gone = self._recs.popleft()
                self._evicted += 1
                if gone.kind == PLAY:
                    self._nplay -= 1
                    self._plays.pop(gone.ref, None)
                else:
                    self._nconv -= 1
        if key is not None:
            self._latest[key] = self._evicted + len(self._recs) - 1
        return rec

    def _supersede(self, key, same=None):
        """Mark the newest record of ``key`` superseded; with ``same``: only when that record holds this question (``tid``)."""
        pos = self._latest.get(key)
        i = None if pos is None else pos - self._evicted
        if i is not None and 0 <= i < len(self._recs) and not self._recs[i].superseded and (same is None or self._recs[i].tid == same[0]):
            self._recs[i] = self._recs[i]._replace(superseded=True)
            self.version += 1

    def open_call(self, at):
        """A call begins (``begin_call``): a marker line for the day files; nothing in memory."""
        if not self._replaying:
            self._last_before = self._last_wall()
            self._open_w = self._wall()
            self._opened = (at, self._open_w)
            self.end_all('call')
        self._write({'k': 'call', 'at': at})

    def _last_wall(self):
        """The wall time of the newest record that has one (None: none)."""
        for r in reversed(self._recs):
            if r.wall is not None:
                return r.wall
        return None

    def conversation(self, began, gap_s):
        """M1-e2: the start of the conversation the readers count from (``since``, on the wall clock), at an ``open_call``. A call opened at most ``gap_s`` after the newest record the
        ledger holds goes on with the conversation it was serving (a dropped line, a redial: the words of 20 s ago are this conversation's); else it starts one at ``began``."""
        last = self._last_before
        if not (last is not None and self._open_w is not None and 0 <= self._open_w - last <= gap_s):
            self._began = began
        return self._began

    # --- M9: what is held (kinds) ---
    def hold(self, kind, key, tid, text, now):
        """Hold ``text`` under (``kind``, ``key``) for the ``tid`` it belongs to; a newer hold of the same key replaces the older. A kind with no row in ``KINDS`` is refused: nothing is held that no rule ends."""
        if kind not in KINDS:
            raise KeyError('ledger kind %r has no row in KINDS' % (kind,))
        kind_ttl(kind)
        self._held[(kind, key)] = [tid, str(text or ''), now, self._epoch]

    def held(self, kind, key, now=None):
        """The text held under (``kind``, ``key``), or ``None`` (nothing, or its time ran out when ``now`` is given)."""
        if kind not in KINDS:
            raise KeyError('ledger kind %r has no row in KINDS' % (kind,))
        item = self._held.get((kind, key))
        if item is None or (now is not None and now - item[2] > kind_ttl(kind)):
            return None
        return item[1]

    def held_for(self, kind, key):
        """The ``tid`` an item is held for, or None."""
        item = self._held.get((kind, key))
        return item[0] if item else None

    def end(self, kind, key, reason):
        """The item ends for ``reason`` (one of the kind's ``end_reasons``; another is a defect). Returns True when something ended."""
        if reason not in KINDS[kind].end_reasons:
            raise ValueError('kind %r does not end for %r' % (kind, reason))
        return self._held.pop((kind, key), None) is not None

    def end_all(self, reason):
        """Every held item whose kind ends for ``reason`` ends (a call begins: ``reason`` 'call')."""
        for kind, key in [k for k in self._held if reason in KINDS[k[0]].end_reasons]:
            self._held.pop((kind, key), None)

    def expire(self, now, epoch=None, live=None):
        """The tick: items older than their TTL end ('expired'); a new ``epoch`` ends the items bound to the epoch; items bound to a ``tid`` that is not in ``live`` (when given) end ('superseded')."""
        new_epoch = epoch is not None and self._epoch is not None and epoch != self._epoch
        for (kind, key), (tid, _, at, ep) in list(self._held.items()):
            spec = KINDS[kind]
            if now - at > kind_ttl(kind):
                self.end(kind, key, 'expired')
            elif spec.binds_to == 'epoch' and new_epoch and ep != epoch and 'epoch' in spec.end_reasons:
                self.end(kind, key, 'epoch')
            elif spec.binds_to == 'tid' and live is not None and tid is not None and tid not in live and 'superseded' in spec.end_reasons:
                self.end(kind, key, 'superseded')
        if epoch is not None:
            self._epoch = epoch

    def use_wall(self, wall):
        """M1-e: a new owner of the ledger (the controller of a redial) gives its wall clock; the records already in it keep their stamps."""
        self._wall = wall

    def on_records(self, since):
        """M1-a: ``since`` (the start of the call) on the clock of the records' ``at``. One clock for the whole ledger: with ``since_on_wall`` it is a time of the ``wall`` clock, moved by the
        difference of the two clocks read together at the last ``open_call``; before any call was opened, the ``at`` of the first record stamped at or after it on the wall clock."""
        if since is None or not self._since_wall:
            return since
        if self._opened is not None:
            return since - self._opened[1] + self._opened[0]
        later = [r.at for r in self._recs if r.wall is not None and r.wall >= since]
        return min(later) if later else since

    # --- what the listener said ---
    def user_final(self, tid, text, *, final_rev, echo=False, at=0.0, who=None):
        """A final of what the microphone heard. ``who``: None, the room; ``BACK``, the prompt said aloud by the owner (M1-g)."""
        key = (tid, final_rev)
        if key in self._seen:
            self._mark(tid, final_rev, who)
            return None
        self._seen.add(key)
        self._supersede((USER, tid))
        line ={'k': USER, 'tid': tid, 'text': str(text or ''), 'rev': final_rev, 'echo': bool(echo), 'at': at}
        self._write(dict(line, who=who) if who else line)
        return self._add(Rec(USER, tid, str(text or ''), at, final_rev, bool(echo), wall=self._stamp(), who=who), (USER, tid))

    def _mark(self, tid, final_rev, who):
        """M1-g: the final is written as soon as it comes, the judge rules on it after: the same (tid, final_rev) again with another ``who`` changes only that."""
        pos = self._latest.get((USER, tid))
        i = None if pos is None else pos - self._evicted
        if i is None or not 0 <= i < len(self._recs) or self._recs[i].final_rev != final_rev or self._recs[i].who == who:
            return
        self._recs[i] = self._recs[i]._replace(who=who)
        self.version += 1
        self._write({'k': 'who', 'tid': tid, 'rev': final_rev, 'who': who})

    def cloud_text(self, tid, text, *, at=0.0):
        """An interim text of the cloud ear: kept for the trace, never counted as the listener's words."""
        self._supersede((CLOUD, tid))
        return self._add(Rec(CLOUD, tid, str(text or ''), at), (CLOUD, tid))

    # --- what the helper answered ---
    def answer(self, aid, text, *, tid=None, supersedes=None, at=0.0):
        """An answer row. ``supersedes``: the row of the revision before it; M1-b: it is marked superseded only when it answered the SAME question (``tid``): the answer to another
        question is the conversation, not an earlier version of this answer."""
        if supersedes is not None:
            self._supersede((ANSWER, supersedes), same=(tid,))
        self._write({'k': ANSWER, 'aid': aid, 'text': str(text or ''), 'tid': tid, 'sup': supersedes, 'at': at})
        return self._add(Rec(ANSWER, tid, str(text or ''), at, None, False, aid, wall=self._stamp()), (ANSWER, aid))

    # --- what was played (X-CUE) ---
    def play_began(self, cue, text, at, voiced_s=None):
        if cue in self._plays:
            return None
        words = _words(text)
        voiced = float(voiced_s) if voiced_s else max(1, sum(max(1, syllables(w)) for w in words)) * timer_policy.SECONDS_PER_SYLLABLE
        self._plays[cue] = {'words': words, 'began': at, 'voiced_s': voiced, 'end': None, 'heard_n': 0}
        self._write({'k': PLAY, 'cue': cue, 'text': str(text or ''), 'at': at, 'voiced': voiced_s})
        return self._add(Rec(PLAY, None, str(text or ''), at, None, False, cue, wall=self._stamp()))

    def _end(self, cue, how, at):
        p = self._plays.get(cue)
        if p is None or p['end'] is not None:
            return None                      # a cue ends once
        p['end'] = how
        self._write({'k': 'end', 'cue': cue, 'how': how, 'at': at})
        if how == 'done':
            p['heard_n'] = len(p['words'])
        else:
            heard_s = max(0.0, min(p['voiced_s'], at - p['began'] - self._lag))
            p['heard_n'] = _heard_count(p['words'], heard_s / p['voiced_s'])
        return p['heard_n']

    def play_done(self, cue, at):
        return self._end(cue, 'done', at)

    def play_cut(self, cue, at):
        return self._end(cue, 'cut', at)

    def heard(self, cue):
        p = self._plays.get(cue)
        return list(p['words'][:p['heard_n']]) if p else []

    # --- reading ---
    def user_words(self, n, skip=None):
        """The last ``n`` words: walks back from the newest record and stops as soon as ``n`` words are in hand. ``skip``: a turn id left out (the command's own final)."""
        if n <= 0:
            return []
        out = []
        for r in reversed(self._recs):
            if r.kind == USER and not r.superseded and not r.echo and r.tid != skip:
                out = _words(r.text) + out
                if len(out) >= n:
                    break
        return out[-n:]

    def played_words(self, n):
        if n <= 0:
            return []
        out = []
        for r in reversed(self._recs):
            if r.kind == PLAY:
                out = self.heard(r.ref) + out
                if len(out) >= n:
                    break
        return out[-n:]

    def last_sentence(self, owner='user'):
        if owner == 'user':
            texts = [r.text for r in self._recs if r.kind == USER and not r.superseded and not r.echo]
        else:
            texts = [' '.join(self.heard(r.ref)) for r in self._recs if r.kind == PLAY and self.heard(r.ref)]
        if not texts:
            return ''
        text = texts[-1].strip()
        body = text.rstrip(_SENTENCE_END + ' ')
        cut = max((body.rfind(c) for c in _SENTENCE_END), default=-1)
        return text[cut + 1:].strip() if cut >= 0 else text

    def recap_calls(self, window_s=LEDGER_CARRY_S, chars=RECAP_CHARS, question=None, only_found=False):
        """U14-S8 / U139: a short, deterministic recap of the exchanges of EARLIER calls (before this call opened), as many as ``chars`` hold: «N ч назад: «question» - the beginning of the answer».
        With a ``question`` the day memory is searched by its words: an exchange of the days kept (``LEDGER_KEEP_DAYS``) that shares a stem with the question (rare stems weigh more: ln((N+1)/(df+.5)) over the exchanges
        held; stems of four letters and more) comes first, best first (token/lemma similarity through ``textutil.stems``: «договорам» finds «договор»; no embedding, no service); what is left of the room is filled with the newest exchanges of the last
        ``window_s`` (newest first), which is also the whole recap without a question. ``only_found``: nothing but what the question found (empty when it found nothing). Empty when nothing qualifies (a memory ledger knows no earlier call)."""
        if only_found and self._open_w is None:
            return ''                                   # no call was opened here: nothing is EARLIER than this conversation
        now = self._wall()
        edge = self._open_w if self._open_w is not None else float('inf')
        reach = max(window_s, LEDGER_KEEP_DAYS * 86400) if question else window_s
        asked = {r.tid: r for r in self._recs if r.kind == USER and not r.superseded and not r.echo}
        pairs = []                                  # (answer record, its question's record), newest first
        for r in reversed(self._recs):
            q = asked.get(r.tid) if r.kind == ANSWER and not r.superseded else None
            if q is not None and r.wall is not None and r.wall < edge and now - r.wall <= reach:
                pairs.append((r, q))
        order = [(r, q) for r, q in pairs if now - r.wall <= window_s]
        qset = {w for w in stems(norm_words(question)) if len(w) >= 4} if question else set()      # a stem of 3 letters is a function word: no clue
        found = []
        if qset and pairs:
            toks = [set(stems(norm_words(q.text + ' ' + r.text))) for r, q in pairs]
            df = {}
            for t in toks:
                for w in t & qset:
                    df[w] = df.get(w, 0) + 1
            n = len(pairs)
            scored = sorted(((sum(math.log((n + 1) / (df[w] + 0.5)) for w in t & qset), -i) for i, t in enumerate(toks) if t & qset), reverse=True)
            found = [pairs[-i] for sc, i in scored if sc > 0][:4]
            order = found + [x for x in order if x not in found]
        if only_found and not found:
            return ''
        head, lines = 'Прошлые разговоры (кратко):', []
        used = len(head)
        for r, q in order:
            ago = now - r.wall
            when = '%d дн' % (ago // 86400) if ago >= 2 * 86400 else '%d ч' % (ago // 3600) if ago >= 3600 else '%d мин' % (ago // 60)
            line = '- %s назад: «%s» - %s' % (when, _clip(q.text, 80), _clip(r.text, 90))
            if used + 1 + len(line) > chars:
                break
            lines.append(line)
            used += 1 + len(line)
        return head + '\n' + '\n'.join(lines) if lines else ''


    def recap(self, since=None, exclude_last_exchanges=6, limit=8, chars=RECAP_CHARS):
        """U14-S10: the topic recap of THIS call for the model: the answered exchanges from ``since`` (the call's start) except the last ``exclude_last_exchanges`` (the model has those word for word),
        at most ``limit`` of them spread evenly from the first to the last, at most ``chars`` in all: «- 10 мин: «question» - the beginning of the answer». The pointer is the minute of the call and the question.
        It is kept until the count of older exchanges changes (an exchange left the window), so the prompt cache holds. Empty when nothing is older than the window."""
        since = self.on_records(since)
        asked ={r.tid: r for r in self._recs if r.kind == USER and not r.superseded and not r.echo}
        rows = []
        for r in self._recs:
            q = asked.get(r.tid) if r.kind == ANSWER and not r.superseded else None
            if q is not None and (since is None or q.at >= since):
                rows.append((q, r))
        older = rows[:max(0, len(rows) - max(0, exclude_last_exchanges))]
        if not older or limit <= 0:
            return ''
        key = (since, len(older), limit, chars, older[-1][1].ref)
        if self._recap_key == key:
            return self._recap_text
        n = min(limit, len(older))
        picked = [older[0]] if n == 1 else [older[i * (len(older) - 1) // (n - 1)] for i in range(n)]
        head = 'Ранее в этом разговоре:'
        room = max(20, (chars - len(head) - len(picked)) // len(picked))       # per line, newline included
        lines = []
        for q, a in picked:
            pre = '- %d мин: «' % ((q.at - (since or 0.0)) // 60)
            body = room - len(pre) - 4
            lines.append(pre + _clip(q.text, max(8, body * 6 // 10)) + '» - ' + _clip(a.text, max(4, body - body * 6 // 10)))
        self._recap_key, self._recap_text = key, (head + '\n' + '\n'.join(lines))[:chars]
        return self._recap_text

    def records(self):
        """V6 memory: a read-only copy of the records in memory, oldest first (a ``Rec`` is immutable). The projections of echo_sync/v6_memory.py are rebuilt from it."""
        return tuple(self._recs)

    def __len__(self):
        return len(self._recs)
