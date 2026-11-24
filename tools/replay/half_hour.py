"""G18: half an hour of conversation on the stand. 80 questions of different subjects (the a1 families, the bank of the four subjects, laws, outside the subjects),
answers of one to four portions; the owner says every portion back as people do: word for word, a word or two lost, in their own words with the portion's last
words at the end, its start and its end, with a stutter, a part and a pause and then the rest, or nothing (and waits); the friend asks a question again later;
strangers, a television, a laugh in between. The real chain of the stand (``tools.rehearsal.sim.Rehearsal``: ControlledMedia, NativeMediaSocket, ShadowEar,
FastText), all the candidate's flags on.

A try that is owed the next portion (the owner's rule of 06.11: most of the portion, or its last words at the end, or the second part of a try): its end ``t``.
  unanswered   a question no cue of which fits it (before the next question)
  extra        the same portion again after a try that was owed the next one (before that next one)
  stuck        a try owed the next portion and no next portion within ``STUCK_S`` s of its end (the plan has more)
  skipped      a portion after the next one came first (a step of two)
Each is counted in the minute of the stand's clock it falls in; the target is zero of each over 300 seeds.

    python -m tools.replay.half_hour --seeds 0:300 --jobs 4 [--questions 80] [--minutes 30] [--show 5] [--json out.jsonl]
Seconds are seconds of the stand's clock, not a measurement on a laptop or a phone.
"""
import argparse
import collections
import heapq
import json
import logging
import random
import re
import sys
import time
from multiprocessing import Pool

from echo_sync import fast_text as FT
from tools.replay import stand as A
from tools.rehearsal import plan as P
from tools.rehearsal import sim as R

FLAGS = {'fast_text': 'on', 'local_ear': 'act', 'ear_release': 'on', 'instant': 'on', 'material_pick': 'on',
         'spare_helper': 'on', 'warm_start': 'on', 'open_overlap': 'on'}
MIX = ('money', 'mult', 'verb', 'year', 'article', 'op09', 'tax', 'op05', 'op01', 'def', 'num', 'acct', 'law', 'out', 'cmp', 'why', 'ex')
LINE = 'Полчаса | ask=' + ','.join(MIX) + ' others=chatter:2,tv:1,laugh:1,aside:1,door:1 orate=0.5 st=mid,filler,first,restart'
TRY = {'verbatim': 30, 'lost': 12, 'retell': 12, 'ends': 8, 'stutter': 10, 'stumble': 10, 'silence': 6, 'partial': 5}
OWED = ('verbatim', 'lost', 'retell', 'ends', 'stutter', 'rest')           # tries the next portion is owed after
OPENERS = ('Ну, если своими словами,', 'Короче, суть такая,', 'То есть получается,', 'Иначе говоря,', 'Ну вот,')
WAIT, STUCK_S, GIVE_UP = 12.0, 6.0, 15.0     # the friend asks again after WAIT s of silence; a next portion later than STUCK_S s is stuck; the owner gives up
AGAIN_P, LONG = 0.06, (0, 0, 0, 1, 1, 2)    # a question asked again later in the call; how many more sentences a bank answer has


def _read_out(atoms):
    """integ-c19: the head's fast_text has no ``_read_out`` (the owner replaced it in ``most_said``); the stand keeps g18's own reading: the spoken
    «тридцать» «два» «десять» are 32 and 10, so 3210."""
    read, held = [], 0
    for value in (int(digits) for digits in (re.sub(r'\D', '', FT._value(atom)) for atom in atoms if FT._is_number(atom)) if digits):
        round_of = 10 ** (len(str(held)) - len(str(held).rstrip('0'))) if held else 0
        if held and value < round_of:
            held += value
        else:
            read.append(held)
            held = value
    return ''.join(str(value) for value in read + [held] if value)


def ear_keeps(ear, said):
    """The ear kept every number (by its digits, read out as spoken) and every «не» of what the owner said: else the portion is said again by design (a number
    changed is a change), and that is the ear's error, not a missed step."""
    try:
        digits = getattr(FT, '_read_out', _read_out)(FT._atoms(ear))
        numbers = [re.sub(r'\D', '', FT._value(a)) for a in FT._atoms(said) if FT._is_number(a)]
    except Exception:                     # noqa: BLE001 - not sure: not owed
        return False
    nots = lambda text: len(re.findall(r'(?i)(?<!\w)не(?!\w)', text))
    return all(n in digits for n in numbers if n) and nots(ear) >= nots(said)


def own_words(words, rng):
    """In one's own words: an opener and the portion's last two or three words (no number or «не» of one's own)."""
    return f'{rng.choice(OPENERS)} {" ".join(words[-3:])}'


def lose_words(words, rng):
    """One or two words of no number and no «не» lost (not the last two)."""
    can = [k for k, w in enumerate(words[:-2]) if not re.search(r'\d', w) and w.lower().strip(',.') not in ('не', 'ни', 'нет')]
    for k in sorted(rng.sample(can, min(len(can), rng.choice((1, 2)))), reverse=True):
        del words[k]
    return ' '.join(words)


class HalfHour(R.Rehearsal):
    def __init__(self, seed, *, questions=80, minutes=30.0, flags=None, idle_step=0.5):
        self.idle_step, self.total, self.minutes = idle_step, questions, minutes
        spec = R.Spec('half_hour', LINE)
        spec.minutes = minutes + 15.0
        self.episodes, self.tries = [], []
        self.phase, self.last_seen, self.pending, self.retried = 'pause', None, None, set()
        super().__init__(spec, seed, flags={**FLAGS, **(flags or {})})
        self.rng = random.Random(f'half-hour-{seed}')

    # -- the script ----------------------------------------------------------------------------------------------------------------------------------------
    def _schedule(self):
        s, r = self.spec, random.Random(f'others-{self.seed}')
        t = r.uniform(5, 20)
        while t < self.length:
            self.later(t, self.other, call=None)
            t += r.expovariate(s.orate / 60.0)

    def question(self, last=None):
        q = super().question(last)
        if isinstance(q, P.Fact) and q.family not in P.LAWS:
            q = R.longer(q, self.rng.choice(LONG))
            self.asked[-1] = q
        return q

    def play(self):
        self.later(self.rng.uniform(1.0, 3.0), self.decide)
        while self.now() < self.length and not (self.phase == 'done' and self.speaking is None and self.now() > self.free + 8.0):
            while self.agenda and self.agenda[0][0] <= self.now() + 1e-9:
                _, _, call, action = heapq.heappop(self.agenda)
                if call is None or call == self.call:
                    action()
            if self.idle_step and self.idle():
                self.w.advance(self.idle_step, step=self.idle_step)
            else:
                self._packet()
                self.w.advance(A.TICK, step=A.TICK)
            self._sample()
        self._collect()
        return self.out

    def idle(self):
        now = self.now()
        if self.phase != 'pause' or self.speaking is not None or self.steps or self.w.open is not None:
            return False
        if self.agenda and self.agenda[0][0] < now + self.idle_step + 1.0:
            return False
        last = max([self.said[-1].offset if self.said else 0.0] + [self.w.cues[-1].t - self.zero if self.w.cues else 0.0])
        if now - last < 15.0 or any(run.thread.is_alive() for run in list(self.runs.values())[-4:]):
            return False
        s = self.w.controller.state() or {}
        return not (self.w.controller.hearing or s.get('stream_waiting_next') or s.get('streaming'))

    def episode(self):
        return self.episodes[-1] if self.episodes else None

    def fresh(self):
        """The last cue, if it began after the owner last spoke and was not reacted to yet."""
        cue = self.last_cue()
        last = self.said[-1].offset if self.said else 0.0
        if cue is None or cue is self.last_seen or cue.t - self.zero <= last:
            return None
        return cue

    def decide(self):
        r, now, e = self.rng, self.now(), self.episode()
        if self.phase in ('done', 'speaking'):
            return
        if self.phase == 'pause':
            if len(self.episodes) >= self.total:
                self.phase = 'done'
                return
            return self.ask()
        if self.w.open is not None and not self.w.open.diagnostic:
            return self.later(now + 0.2, self.decide)                          # the cue is said to its end, then the owner speaks
        if self.phase == 'wait':
            fits = [c for c in self.w.cues if not c.diagnostic and c.t - self.zero > e['asks'][-1].onset and e['q'].fits(' '.join(c.snap.get('chunks') or ()))]
            if fits:
                self.phase = 'follow'
            elif now - e['asks'][-1].offset > WAIT and len(e['asks']) < 2:
                return self.ask(again=True)
            elif now - e['asks'][-1].offset > WAIT + GIVE_UP:
                return self.close()
            else:
                return self.later(now + 0.5, self.decide)
        cue, state = self.fresh(), self.w.controller.state() or {}
        if cue is None:
            quiet = now - max(self.said[-1].offset, (self.last_cue().t - self.zero) if self.last_cue() else 0.0)
            chunks, index = state.get('chunks') or (), state.get('chunk_index')
            last = index is not None and index + 1 >= len(chunks) and not state.get('streaming')
            done = state.get('completed') or (last and self.pending is not None and self.pending['row']['where'][1] == index)
            if quiet > (2.5 if done else GIVE_UP):
                return self.close()
            if self.pending is not None and not done and quiet > STUCK_S + 1.0 and self.pending['row']['where'] not in self.retried:
                self.retried.add(self.pending['row']['where'])                 # nothing came: the owner says the portion once more (a second try)
                return self.try_(self.pending['cue'], 'verbatim', second=True)
            return self.later(now + 0.4, self.decide)
        self.last_seen, self.pending = cue, None
        kinds = list(TRY)
        kind = r.choices(kinds, [TRY[k] for k in kinds])[0]
        if kind == 'silence':
            return self.later(now + r.uniform(4.0, 8.0), self.decide)         # the owner waits: the portion is said again by itself, that is no extra
        self.later(max(now + r.uniform(0.3, 1.0), self.free), lambda: self.try_(cue, kind))

    def try_(self, cue, kind, second=False):
        if not second and self.last_cue() is not cue:
            return self.decide()                                               # a newer cue came while the owner was about to speak: that one is said back
        r, words = self.rng, cue.text.split()
        if not words:
            return self.later(self.now() + 0.4, self.decide)
        snap = cue.snap or {}
        where = (snap.get('revision'), snap.get('index'))
        if kind in ('stumble', 'partial', 'ends') and len(words) < 4 or kind == 'ends' and len(words) < 6:
            kind = 'verbatim'
        if kind in ('retell', 'ends') and re.search(r'\d|(?i:\bне\b)', ' '.join(words[2 if kind == 'ends' else 0:-3])):
            kind = 'lost'                                                      # a number or «не» left out is a change: that one is said again, by design
        if kind == 'lost' and len(words) < 5:
            kind = 'verbatim'
        if kind == 'verbatim':
            text, said = cue.text, 'repeat'
        elif kind == 'lost':
            text, said = lose_words(list(words), r), 'repeat'
        elif kind == 'retell':
            text, said = own_words(words, r), 'repeat'
        elif kind == 'ends':
            text, said = ' '.join(words[:2] + ['...'] + words[-3:]), 'repeat'
        elif kind == 'stutter':
            text, said = self.stuttered(cue.text, r.choice(self.spec.stutter)), 'stutter'
        else:                                                                  # stumble, partial: a part, then a pause
            cut = len(words) // 2 if kind == 'stumble' else r.choice((1, 2))
            text, said = ' '.join(words[:cut]), 'partial'
        self.utter(said, text, None, 'user', cue, False)
        u = self.said[-1]
        row = {'u': u.n, 'kind': kind, 'where': where, 'cue': cue.text, 'cue_t': cue.t - self.zero, 'text': text, 'start': u.onset, 'end': u.offset, 'second': second,
               'owed': (kind in OWED or second) and ear_keeps(u.ear, text), 'q': len(self.episodes)}
        self.tries.append(row)
        self.episode()['tries'].append(row)
        if row['owed']:
            self.pending = {'cue': cue, 'row': row}
        if kind == 'stumble':                                                  # the rest after a pause (it may come over the help)
            rest = ' '.join(words[len(words) // 2:])
            self.later(u.offset + r.uniform(2.0, 4.5), lambda: self.rest(cue, rest, where))
            return
        self.later(u.offset + 0.3, self.decide)

    def rest(self, cue, text, where):
        if self.w.open is not None and not self.w.open.diagnostic:
            return self.later(self.now() + 0.2, lambda: self.rest(cue, text, where))
        self.last_seen = self.last_cue()                                       # the help said again from the word: the owner goes on with the rest, no new try of it
        self.utter('repeat', text, None, 'user', cue, False)
        u = self.said[-1]
        row = {'u': u.n, 'kind': 'rest', 'where': where, 'cue': cue.text, 'cue_t': cue.t - self.zero, 'text': text, 'start': u.onset, 'end': u.offset, 'second': True,
               'owed': ear_keeps(u.ear, text), 'q': len(self.episodes)}
        self.tries.append(row)
        self.episode()['tries'].append(row)
        self.pending = {'cue': cue, 'row': row}
        self.later(u.offset + 0.3, self.decide)

    def ask(self, again=False):
        r = self.rng
        if again:
            q = self.episode()['q']
            text = q.text
        else:
            older = [e['q'] for e in self.episodes[:-3]]
            q = r.choice(older) if older and r.random() < AGAIN_P else self.question(self.current)
            text = q.text if r.random() > 0.12 else r.choice(A.CHATTER[:3]) + ' ' + q.text
        self.utter('question', text, ('q', q), 'friend', None, False)
        u = self.said[-1]
        if again:
            self.episode()['asks'].append(u)
        else:
            self.episodes.append({'q': q, 'asks': [u], 'start': u.onset, 'end': None, 'n': len(self.episodes) + 1, 'tries': []})
        self.phase, self.pending = 'wait', None
        self.later(u.offset + 0.5, self.decide)

    def close(self):
        e, r, now = self.episode(), self.rng, self.now()
        e['end'], self.pending = now, None
        n_left = self.total - len(self.episodes)
        if n_left <= 0:
            self.phase = 'done'
            return
        left = max(0.0, self.minutes * 60.0 - now)
        pause = max(1.0, left / n_left * r.uniform(0.2, 1.8) if r.random() > 0.15 else r.uniform(1.0, 3.0))
        self.phase = 'pause'
        if pause > 12 and r.random() < 0.3:
            self.later(now + r.uniform(2.0, pause - 6.0), lambda: self.utter('chatter', r.choice(A.CHATTER[3:]), None, 'user', None, False))
        self.later(now + pause, self.decide)

    def other(self):
        if self.phase == 'done':
            return
        super().other()


def tally(st, out):
    """The events of one call: (kind, t, what) for unanswered, extra, stuck, skipped; and the per-question rows."""
    cues = [c for c in out.cues if not c[6]]
    eps, said = st.episodes, {u.n: u for u in out.said}
    heard = lambda row: f' [ear {said[row["u"]].ear[:60]!r}{"" if said[row["u"]].final_at else ", no final"}]'
    starts = [e['start'] for e in eps] + [float('inf')]
    events = []
    for k, e in enumerate(eps):
        lo, hi = e['start'], starts[k + 1]
        if not any(e['q'].fits(' '.join(c[4])) for c in cues if lo <= c[0] < hi + 0.5):
            events.append(('unanswered', round(e['asks'][0].offset, 2), f'question {k + 1} {e["q"].text[:80]!r}'))
        for row in e['tries']:
            if not row['owed']:
                continue
            rev, index = row['where']
            if rev is None or index is None:
                continue
            later = [c for c in cues if row['cue_t'] < c[0] < hi and c[2] == rev]
            plan = max((c[4] for c in cues if c[2] == rev), key=len, default=())
            nxt = next((c for c in later if c[3] == index + 1), None)
            until = nxt[0] if nxt else hi
            again = [c for c in later if c[3] == index and row['end'] < c[0] < until]
            if again and not any(r2['u'] > row['u'] and r2['where'] == row['where'] and r2['start'] < again[0][0] for r2 in e['tries']):
                events.append(('extra', again[0][0], f'q{k + 1} portion {index} {row["cue"][:50]!r} again after {row["kind"]} {row["text"][:60]!r}' + heard(row)))
            jump = next((c for c in later if c[3] is not None and c[3] > index + 1), None)
            if jump is not None and (nxt is None or jump[0] < nxt[0]):
                events.append(('skipped', jump[0], f'q{k + 1} portion {index} -> {jump[3]} after {row["kind"]} {row["text"][:60]!r}'))
            if index + 1 < len(plan) and (nxt is None or nxt[0] - row['end'] > STUCK_S):
                if not any(row['end'] < t < row['end'] + STUCK_S for t in out.reconnects):
                    events.append(('stuck', round(row['end'], 2), f'q{k + 1} portion {index}/{len(plan)} {row["cue"][:50]!r} after {row["kind"]} {row["text"][:60]!r}: next '
                                                                  + (f'at +{nxt[0] - row["end"]:.1f} s' if nxt else 'never') + heard(row)))
    return events


KINDS = ('unanswered', 'extra', 'stuck', 'skipped')


def ready():
    """The stand's own trap: without RapidFuzz ``ru_alignment.match_current`` says None of every repeat (its ImportError path), the portion never goes on,
    and the whole call reads as stuck. That is the stand's error, not the product's: refuse to count."""
    try:
        import rapidfuzz  # noqa: F401
    except ImportError as error:
        raise SystemExit('half_hour: RapidFuzz is not installed (echo_sync/plugin.yaml); every repeat would read as a mismatch') from error


def one(seed, questions=80, minutes=30.0, flags=None, keep=False, idle_step=0.5):
    ready()
    level = logging.root.manager.disable
    logging.disable(logging.WARNING)                                   # integ-c19: given back after, as the marathon does (the tests of logging run after this)
    st = HalfHour(seed, questions=questions, minutes=minutes, flags=flags, idle_step=idle_step)
    try:
        try:
            st.play()
        except Exception as error:                                     # noqa: BLE001 - a crash of the chain is a finding
            import traceback
            st.out.crash = ''.join(traceback.format_exception(error))[-1500:]
            st.out.violations.append(('A0', round(st.now(), 2), f'{type(error).__name__}: {error}'[:300]))
            st._collect()
    finally:
        A.Stand.close(st)                                              # integ-c19: ``HalfHour.close`` closes an episode and hid the stand's own: S.host_kwargs and FT.threading stayed patched for every test after
        logging.disable(level)
    out = st.out
    events = tally(st, out)
    result = {'seed': seed, 'asked': len(st.episodes), 'tries': sum(1 for t in st.tries if t['owed']), 'end': round(st.now(), 1), 'crash': out.crash,
              'events': events, 'minutes': {k: collections.Counter(int(t // 60) for kind, t, _ in events if kind == k) for k in KINDS},
              'asked_by_minute': collections.Counter(int(e['asks'][0].onset // 60) for e in st.episodes)}
    if keep:
        result['out'], result['stand'] = out, st
    return result


def _one(args):
    return one(*args)


def table(results, minutes):
    """Per minute of the call over all seeds: questions, unanswered, extra, stuck, skipped."""
    rows = ['min  asked  unanswered  extra  stuck  skipped']
    top = max([minutes] + [m for r in results for c in r['minutes'].values() for m in c] + [m for r in results for m in r['asked_by_minute']])
    for m in range(int(top) + 1):
        asked = sum(r['asked_by_minute'].get(m, 0) for r in results)
        n = [sum(r['minutes'][k].get(m, 0) for r in results) for k in KINDS]
        rows.append(f'{m:>3}  {asked:>5}  {n[0]:>10}  {n[1]:>5}  {n[2]:>5}  {n[3]:>7}')
    return '\n'.join(rows)


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument('--seeds', default='0:20')
    p.add_argument('--jobs', type=int, default=4)
    p.add_argument('--questions', type=int, default=80)
    p.add_argument('--minutes', type=float, default=30.0)
    p.add_argument('--show', type=int, default=5)
    p.add_argument('--flags', default='', help="profile keys on top of the candidate's, k=v,k=v")
    p.add_argument('--json', help='one line of JSON per seed')
    a = p.parse_args(argv)
    lo, hi = (int(x) for x in a.seeds.split(':'))
    flags = dict(item.split('=', 1) for item in a.flags.split(',') if '=' in item) or None
    began, results = time.time(), []
    sink = open(a.json, 'w') if a.json else None
    with Pool(a.jobs) as pool:
        for r in pool.imap_unordered(_one, [(s, a.questions, a.minutes, flags) for s in range(lo, hi)], chunksize=1):
            results.append(r)
            if sink:
                sink.write(json.dumps(r, ensure_ascii=False, default=str) + '\n')
                sink.flush()
    results.sort(key=lambda r: r['seed'])
    print(table(results, a.minutes))
    total = collections.Counter(kind for r in results for kind, *_ in r['events'])
    clean = [r for r in results if not r['events'] and not r['crash'] and r['asked'] == a.questions]
    print(f'seeds {lo}:{hi}: {len(clean)} of {len(results)} clean; questions {sum(r["asked"] for r in results)}, owed tries {sum(r["tries"] for r in results)}; '
          + ', '.join(f'{k} {total.get(k, 0)}' for k in KINDS) + f'; crashes {sum(1 for r in results if r["crash"])}; call ends at {min(r["end"] for r in results)}-{max(r["end"] for r in results)} s')
    for kind in KINDS:
        shown = [(r['seed'], e) for r in results for e in r['events'] if e[0] == kind][:a.show]
        for seed, (k, t, what) in shown:
            print(f'  {k} seed {seed} t={t}: {what}')
    print(f'{time.time() - began:.0f} s wall')
    return 0 if len(clean) == len(results) else 1


if __name__ == '__main__':
    sys.exit(main())
