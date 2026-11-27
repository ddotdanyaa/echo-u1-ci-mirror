"""G2: the marathon. One call, 60 questions in a row over two hours of the stand's clock: the a1 families (the model), the bank of subjects (material), questions
outside the subjects (search), laws; between them repeats of every portion, stutters, a stumble (the user stops mid-answer), a doubt, a question asked again, short
and long pauses, chatter. The real chain of the stand (``tools.rehearsal.sim.Rehearsal``: ControlledMedia, NativeMediaSocket, ShadowEar, FastText), all the
candidate's flags on.

What is counted, per question (an episode: from its asking to the next question):
  answered   a cue whose plan fits the question began in the episode           lost     none did
  order      the answers came in the order of the questions (no cue of an older question inside a later episode: the stand's A2, ``score.board`` old_answer)
  clean      the episode has no violation of the stand's invariants (``stand.check``) and no ``score.board`` episode (old_answer lost_place false_step false_cue missed)
After each answer (the episode's end, before the next question) a snapshot of the state: the size of every list, dict, set, deque of the controller, the wire, the
ear, the fast channel (one level into their own objects), the wire's tasks, the loop's timers, the live threads; and the controller's flags while nothing is asked.
``growth``: what grows with the number of answers; ``stuck``: a flag or a portion still up at the end of an episode, after the 3rd, 15th, 40th answer.

    python -m tools.replay.marathon --seeds 0:500 --jobs 4 [--questions 60] [--hours 2] [--show 3] [--flags k=v] [--json out.jsonl] [--idle 0.5]
Seconds are seconds of the stand's clock, not a measurement on a laptop or a phone.
"""
import argparse
import asyncio
import collections
import logging
import random
import sys
import threading
import time
from multiprocessing import Pool

from tools.replay import stand as A
from tools.rehearsal import sim as R
from tools.rehearsal import score as SC

FLAGS = {'fast_text': 'on', 'local_ear': 'act', 'ear_release': 'on', 'instant': 'on', 'material_pick': 'on',
         'spare_helper': 'on', 'warm_start': 'on', 'open_overlap': 'on'}
MIX = ('money', 'mult', 'verb', 'year', 'article', 'op09', 'tax', 'op05', 'op01', 'def', 'num', 'out', 'law', 'acct')
LINE = 'Марафон | ask=' + ','.join(MIX) + ' st=mid,filler,first,restart,cut,skip'
FOLLOW = {'repeat': 50, 'stutter': 14, 'partial': 8, 'wrong': 3, 'stumble': 8, 'doubt': 3, 'again': 2, 'chatter': 2}
WAIT, ASK_AGAIN = 12.0, 2                  # seconds the friend waits for an answer before asking again; how many times a question is asked at most
CHECKS = (3, 15, 40)
STATE_FLAGS = ('hearing',)                 # attributes of the controller that must be down while nobody speaks and nothing is asked


def sizes(root, name, out, depth=1, seen=None):
    """The size of every container of ``root`` (``name.attr``), one level into its own objects (of echo_sync)."""
    seen = set() if seen is None else seen
    if id(root) in seen:
        return out
    seen.add(id(root))
    for key, value in list(getattr(root, '__dict__', {}).items()):
        if isinstance(value, (list, dict, set, frozenset, collections.deque, tuple)):
            out[f'{name}.{key}'] = len(value)
        elif depth > 0 and type(value).__module__.startswith('echo_sync') and hasattr(value, '__dict__'):
            sizes(value, f'{name}.{key}', out, depth - 1, seen)
    return out


class Marathon(R.Rehearsal):
    def __init__(self, seed, *, questions=60, hours=2.0, flags=None, idle_step=0.5):
        self.idle_step = idle_step
        spec = R.Spec('marathon', LINE)
        spec.minutes = hours * 60.0 + 10.0
        self.total, self.hours = questions, hours
        self.episodes, self.snaps = [], []           # episodes: dict(q, asks, start, end); snaps: (answer number, t, sizes, flags)
        super().__init__(spec, seed, flags={**FLAGS, **(flags or {})})
        self.rng = random.Random(f'marathon-{seed}')
        self.phase, self.last_seen = 'pause', None

    # -- the script ------------------------------------------------------------------------------------------------------------------------------------
    def _schedule(self):
        pass

    def play(self):
        self.later(self.rng.uniform(1.0, 3.0), self.decide)
        while self.now() < self.length and not (self.phase == 'done' and not self.speaking):
            while self.agenda and self.agenda[0][0] <= self.now() + 1e-9:
                _, _, call, action = A.heapq.heappop(self.agenda)
                if call is None or call == self.call:
                    action()
            if self.idle_step and self.idle():
                self.w.advance(self.idle_step, step=self.idle_step)          # a long pause with nothing on: the host's ticks, coarser; no packets of the microphone
            else:
                self._packet()
                self.w.advance(A.TICK, step=A.TICK)
            self._sample()
        self._collect()
        return self.out

    def idle(self):
        """Nothing can happen for a while: a pause between questions, nothing said or played for 15 s, no job alive, nothing due within a second."""
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

    def cues_since(self, t):
        return [c for c in self.w.cues if not c.diagnostic and c.t - self.zero > t]

    def episode(self):
        return self.episodes[-1] if self.episodes else None

    def decide(self):
        r, now, e = self.rng, self.now(), self.episode()
        if self.phase == 'done':
            return
        if self.phase == 'pause':
            if len(self.episodes) >= self.total:
                self.phase = 'done'
                return
            self.ask()
            return
        playing = self.w.open is not None and not self.w.open.diagnostic
        if playing:
            self.later(now + 0.2, self.decide)
            return
        fits = [c for c in self.cues_since(e['asks'][-1].onset) if e['q'].fits(' '.join(c.snap.get('chunks') or ()))]
        if self.phase == 'wait':
            if fits:
                self.phase = 'follow'
            elif now - e['asks'][-1].offset > WAIT and len(e['asks']) < ASK_AGAIN:
                self.ask(again=True)
                return
            elif now - e['asks'][-1].offset > WAIT + 20.0:
                return self.close_episode()                              # lost: the friend gives up and goes on
            else:
                self.later(now + 0.5, self.decide)
                return
        cue = self.last_cue()
        last = self.said[-1]
        fresh = cue is not None and cue.t - self.zero > last.offset and cue is not self.last_seen
        state = self.w.controller.state() or {}
        if not fresh:
            quiet = now - max(last.offset, (cue.t - self.zero) if cue else 0.0)
            if quiet > (9.0 if not state.get('completed') else 2.5):
                return self.close_episode()
            self.later(now + 0.4, self.decide)
            return
        self.last_seen = cue
        kinds = list(FOLLOW)
        kind = r.choices(kinds, [FOLLOW[k] for k in kinds])[0]
        if kind == 'stumble':                                            # the user stops: the portion is said again by itself, then they go on
            self.later(now + r.uniform(4.0, 7.0), self.decide)
            return
        if kind == 'again':
            kind = 'again' if r.random() < 0.5 else 'repeat'
        self.later(max(now + r.uniform(0.3, 1.0), self.free), lambda: self.speak(kind, cue))

    def speak(self, kind, cue, barge=False):
        super().speak(kind, cue, barge)

    def ask(self, again=False):
        """The friend asks: a new question, or the same again (not answered in ``WAIT`` s)."""
        r = self.rng
        if again:
            q = self.episode()['q']
            text = q.text
        else:
            q = self.question(self.current)
            text = q.text if r.random() > 0.12 else r.choice(R.P.INTROS[:1] + A.CHATTER[:3]) + ' ' + q.text
        self.utter('question', text, ('q', q), 'friend', None, False)
        u = self.said[-1]
        if again:
            self.episode()['asks'].append(u)
        else:
            self.episodes.append({'q': q, 'asks': [u], 'start': u.onset, 'end': None, 'n': len(self.episodes) + 1})
        self.phase = 'wait'
        self.later(u.offset + 0.5, self.decide)

    def close_episode(self):
        e, r, now = self.episode(), self.rng, self.now()
        e['end'] = now
        self.snap(len(self.episodes))
        left = max(0.0, self.hours * 3600.0 - now)
        n_left = self.total - len(self.episodes)
        if n_left <= 0:
            self.phase = 'done'
            return
        mean = left / n_left
        pause = mean * r.uniform(0.2, 1.8) if r.random() > 0.1 else r.uniform(1.0, 3.0)       # one in ten: the next question at once
        pause = max(1.0, pause)
        self.phase = 'pause'
        if pause > 20 and r.random() < 0.4:                              # chatter in a long pause
            self.later(now + r.uniform(3.0, pause - 10.0), lambda: self.utter('chatter', r.choice(A.CHATTER[3:]), None, 'user', None, False))
        self.later(now + pause, self.decide)

    def snap(self, n):
        w = self.w
        c, wire = w.controller, w.wire
        out = {}
        for name, obj in (('cm', c), ('wire', wire), ('ear', self.ear), ('fast', self.fast)):
            sizes(obj, name, out)
        out['wire.tasks.live'] = sum(1 for t in getattr(wire, 'tasks', ()) if not t.done())
        loop = w.loop
        out['loop.timers'] = len(getattr(loop, '_scheduled', ()))
        out['loop.ready'] = len(getattr(loop, '_ready', ()))
        out['threads'] = threading.active_count()
        out['fast.runs.alive'] = sum(1 for run in self.runs.values() if run.thread.is_alive())
        s = c.state() or {}
        flags = {'hearing': bool(c.hearing), 'waiting_next': bool(s.get('stream_waiting_next')), 'open': w.open is not None and not w.open.diagnostic,
                 'speaking': self.speaking is not None}
        self.snaps.append((n, round(self.now(), 2), out, flags))


def growth(snaps, lo=5, slack=3):
    """The containers whose size after the last answer is more than after the ``lo``-th by more than ``slack`` and that grew in most steps: a leak."""
    if len(snaps) <= lo:
        return {}
    base, last = snaps[lo - 1][2], snaps[-1][2]
    out = {}
    for key, value in last.items():
        b = base.get(key, 0)
        if value - b > slack:
            series = [s[2].get(key, 0) for s in snaps[lo - 1:]]
            ups = sum(1 for x, y in zip(series, series[1:]) if y > x)
            if ups >= len(series) // 3:
                out[key] = (b, value)
    return out


def leaks(snaps, slack=2):
    """Of what grew, what still grows in the last third of the call (a bounded map has reached its cap by then): a leak with no bound."""
    if len(snaps) < 9:
        return {}
    mid, last = snaps[len(snaps) * 2 // 3 - 1][2], snaps[-1][2]
    return {key: (mid.get(key, 0), value) for key, value in last.items() if value - mid.get(key, 0) > slack and key in growth(snaps)}


def score(st, out):
    """Per episode: answered, lost, order, clean."""
    eps, cues = st.episodes, [c for c in out.cues if not c[6]]
    starts = [e['start'] for e in eps] + [float('inf')]
    rows = []
    out.cancelled = {}
    m, board = SC.board(out)
    for k, e in enumerate(eps):
        lo, hi = e['start'], starts[k + 1]
        mine = [c for c in cues if lo <= c[0] < hi]
        answered = any(e['q'].fits(SC.plan_of(c)) for c in mine)
        older = [k2 for k2 in range(k) if any(eps[k2]['q'].fits(SC.plan_of(c)) and not e['q'].fits(SC.plan_of(c)) for c in mine)]
        bad = sorted({v[0] for v in out.violations if lo <= v[1] < hi})
        rows.append({'n': k + 1, 'family': e['q'].family, 'answered': answered, 'older': older, 'violations': bad, 'start': lo})
    out.cancelled = {}
    return rows, board


def one(seed, questions=60, hours=2.0, flags=None, keep=False, idle_step=0.5):
    level = logging.root.manager.disable
    logging.disable(logging.WARNING)                                   # the controller's warnings of a fault the seed made; given back after (the tests of logging run after this)
    st = Marathon(seed, questions=questions, hours=hours, flags=flags, idle_step=idle_step)
    try:
        try:
            st.play()
        except Exception as error:                                     # noqa: BLE001 - a crash of the chain is a finding
            import traceback
            st.out.crash = ''.join(traceback.format_exception(error))[-1500:]
            st.out.violations.append(('A0', round(st.now(), 2), f'{type(error).__name__}: {error}'[:300]))
            st._collect()
    finally:
        st.close()
        logging.disable(level)
    out = st.out
    out.violations += A.check(out)
    rows, board = score(st, out)
    stuck = [(n, t, {k: v for k, v in f.items() if v}) for n, t, _, f in st.snaps if any(f.values())]
    result = {'seed': seed, 'asked': len(rows), 'answered': sum(r['answered'] for r in rows), 'lost': [r['n'] for r in rows if not r['answered']],
              'order': [(r['n'], r['older']) for r in rows if r['older']], 'violations': [v for v in out.violations],
              'unclean': [r['n'] for r in rows if r['violations']], 'growth': growth(st.snaps), 'leaks': leaks(st.snaps), 'stuck': stuck, 'crash': out.crash,
              'end': round(st.now(), 1), 'checks': {n: st.snaps[n - 1][2] for n in CHECKS if len(st.snaps) >= n},
              'board': board}
    if keep:
        result['out'], result['stand'] = out, st
    return result


def _one(args):
    return one(*args)


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument('--seeds', default='0:20')
    p.add_argument('--jobs', type=int, default=4)
    p.add_argument('--questions', type=int, default=60)
    p.add_argument('--hours', type=float, default=2.0)
    p.add_argument('--show', type=int, default=3)
    p.add_argument('--flags', default='', help='profile keys on top of the candidate\'s, k=v,k=v (e.g. prepare_wide=on)')
    p.add_argument('--json', help='one line of JSON per seed, as each ends')
    p.add_argument('--idle', type=float, default=0.5, help='the tick in a long pause with nothing on (0: always 0.1 s)')
    a = p.parse_args(argv)
    lo, hi = (int(x) for x in a.seeds.split(':'))
    flags = dict(item.split('=', 1) for item in a.flags.split(',') if '=' in item) or None
    began = time.time()
    import json
    results, sink = [], open(a.json, 'w') if a.json else None
    with Pool(a.jobs) as pool:
        for r in pool.imap_unordered(_one, [(s, a.questions, a.hours, flags, False, a.idle) for s in range(lo, hi)], chunksize=1):
            results.append(r)
            if sink:
                sink.write(json.dumps(r, ensure_ascii=False, default=str) + '\n')
                sink.flush()
    results.sort(key=lambda r: r['seed'])
    full = [r for r in results if r['answered'] == r['asked'] == a.questions and not r['order'] and not r['crash']]
    print(f'seeds {lo}:{hi}: {len(full)} of {len(results)} with {a.questions} of {a.questions} answered in order')
    print(f'questions: {sum(r["answered"] for r in results)} answered of {sum(r["asked"] for r in results)}; '
          f'clean episodes {sum(r["asked"] - len(r["unclean"]) for r in results)}')
    inv = collections.Counter(v[0] for r in results for v in r['violations'])
    print('violations by invariant:', dict(inv.most_common()))
    grow = collections.Counter(k for r in results for k in r['growth'])
    print('growing:', dict(grow.most_common(10)))
    print('still growing in the last third (no bound):', dict(collections.Counter(k for r in results for k in r.get('leaks', {})).most_common(10)))
    stuck = collections.Counter(k for r in results for _, _, f in r['stuck'] for k in f)
    print('stuck at the end of an episode:', dict(stuck.most_common()))
    bad = [r for r in results if r not in full]
    for r in bad[:a.show]:
        print(f'  seed {r["seed"]}: answered {r["answered"]}/{r["asked"]} lost {r["lost"][:8]} order {r["order"][:3]} crash {bool(r["crash"])} '
              f'first {r["violations"][:2]}')
    print(f'{time.time() - began:.0f} s wall')
    return 0 if len(full) == len(results) else 1


if __name__ == '__main__':
    sys.exit(main())
