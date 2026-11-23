"""c22: a failing seed down to its smallest scene (delta debugging, Zeller-Hildebrandt ddmin) - the stand's own tool, no product code.

A seed of ``stand.run`` is a long conversation; what the owner of the finding needs is the 2-6 utterances that still give the same violation.
  1. record      the seed is run once and every move of its listener is written down: ``(index, t, kind, barge)`` (a move is an utterance or a reconnect)
  2. prefix      the shortest ``length`` (the run is causal: a shorter run is the same conversation cut) that still has the violation of the same group
  3. ddmin       the moves are played from the list (``Scripted``: each move has its own random stream, so a move removed does not change the others) and the list
                 is cut by ddmin (drop chunks of moves while the same group of violation stays)
  4. plain       the same without the stand's random faults (``faults=False``), when the violation holds without them
The group of a violation is ``fuzz.signature`` (the invariant and the message without numbers and quoted texts).

    python -m tools.replay.ddmin SEED [--inv A2] [--sig 'A2 cue ...'] [--length 90] [--json out.json]
    python -m tools.replay.ddmin --fuzz fuzz.json [--jobs 3] [--json out.json]     # the smallest seed of every group of a fuzz run
``play_scene(seed, moves, length, faults)`` is what a test calls to play a minimal scene again. Seconds are the stand's clock, not a laptop's or a phone's.
"""
import argparse
import json
import logging
import random
import sys
from functools import partial
from multiprocessing import Pool

from tools.replay import stand as ST
from tools.replay.fuzz import signature

SCAN = 400                      # seeds to look through (in the recorder's streams) for the violation of a group
NEEDS_CUE = ('repeat', 'partial', 'wrong', 'stop', 'doubt')


class Recorder(ST.Stand):
    """The seed's own conversation, with the moves of its listener written down."""

    def __init__(self, *a, **k):
        self.moves = []
        super().__init__(*a, **k)

    def decide(self):
        """The listener decides from a stream of its own, so that the moves (each with a stream of its own, as ``Scripted``) are the same conversation when played from the list."""
        if not hasattr(self, 'drng'):
            self.drng = random.Random(f'{self.seed}-decide')
        self.rng, kept = self.drng, self.rng
        try:
            super().decide()
        finally:
            self.rng = kept

    def speak(self, kind, cue, barge=False):
        self.moves.append([len(self.moves), round(self.now(), 3), kind, bool(barge)])
        self.rng = random.Random(f'{self.seed}-move-{self.moves[-1][0]}')
        super().speak(kind, cue, barge)

    def reconnect(self):
        if getattr(self, 'zero', None) is not None and self.now() > 0:
            self.moves.append([len(self.moves), round(self.now(), 3), 'reconnect', False])
        super().reconnect()


class Scripted(ST.Stand):
    """A conversation played from a list of moves ``[index, t, kind, barge]``; the listener decides nothing."""

    def __init__(self, seed, moves, **keywords):
        self.moves = moves
        super().__init__(seed, **keywords)

    def decide(self):
        pass

    def play(self):
        for move in self.moves:
            self.later(move[1], partial(self._move, move))
        return super().play()

    def _move(self, move):
        index, t, kind, barge = move
        if kind == 'reconnect':
            self.reconnect()
            return
        if self.now() < self.free - 1e-9:
            self.later(self.free, partial(self._move, move))
            return
        self.rng = random.Random(f'{self.seed}-move-{index}')
        cue = self.last_cue()
        last = self.said[-1] if self.said else None
        fresh = cue is not None and (last is None or cue.t - self.zero > last.offset) and self.following and not self.stopped
        if kind == 'fix' and (self.current is None or self.current.family not in ('money', 'mult')):
            kind = 'question'
        if kind in NEEDS_CUE and not fresh:
            kind = 'chatter'
        playing = self.w.open is not None and not self.w.open.diagnostic
        self.speak(kind, cue if fresh else None, barge=barge and playing)


def _play(cls, seed, length, faults, moves=None, **keywords):
    saved = logging.root.manager.disable                 # c23: given back after (a test of logging may run next in the same process)
    logging.disable(logging.WARNING)
    try:
        stand = cls(seed, moves, length=length, faults=faults, **keywords) if moves is not None else cls(seed, length=length, faults=faults, **keywords)
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
    finally:
        logging.disable(saved)
    out = stand.out
    out.violations += ST.check(out)
    return stand, out


def play_scene(seed, moves, length, faults=True, **keywords):
    """The outcome of the scene (its violations in ``.violations``) played from its moves."""
    return _play(Scripted, seed, length, faults, moves, **keywords)[1]


def hits(out, inv, sig):
    return [v for v in out.violations if v[0] == inv and signature(v[0], v[2]) == sig]


def ddmin(items, test):
    """The classic ddmin over a list: the smallest sublist (1-minimal) for which ``test`` still holds. ``test(items)`` must hold for the whole list."""
    n = 2
    while len(items) >= 2:
        size = max(1, len(items) // n)
        chunks = [items[i:i + size] for i in range(0, len(items), size)]
        for i, chunk in enumerate(chunks):
            rest = [x for j, c in enumerate(chunks) if j != i for x in c]
            if rest and test(rest):
                items, n = rest, max(n - 1, 2)
                break
        else:
            if n >= len(items):
                break
            n = min(len(items), n * 2)
    return items


def shrink(seed, inv=None, sig=None, length=90.0, keywords=None):
    """The smallest scene of the seed for the violation (``inv``, ``sig``; default: its first violation). A dict, ``None`` if the seed is clean."""
    keywords = dict(keywords or {})
    faults = keywords.pop('faults', True)
    stand, out = _play(Recorder, seed, length, faults, **keywords)
    if sig is None:
        if not out.violations:
            return None
        inv = out.violations[0][0]
        sig = signature(inv, out.violations[0][2])
    first = hits(out, inv, sig)
    scanned = 0
    while not first and scanned < SCAN:
        # the recorder's listener has streams of its own: the seed of the plain stand may be clean here; the next seeds are the same kind of conversation
        seed, scanned = seed + 1, scanned + 1
        stand, out = _play(Recorder, seed, length, faults, **keywords)
        first = hits(out, inv, sig)
    if not first:
        return None
    t_hit = first[0][1]
    # 2. the shortest prefix of the same conversation
    best = length
    for extra in (1, 2, 4, 8, 15, 30, 60):
        cut = round(t_hit + extra, 1)
        if cut >= length:
            break
        if hits(_play(Recorder, seed, cut, faults, **keywords)[1], inv, sig):
            best = cut
            break
    stand, out = _play(Recorder, seed, best, faults, **keywords)
    moves = [m for m in stand.moves if m[1] <= best]
    result = {'seed': seed, 'seed_asked': seed - scanned, 'inv': inv, 'sig': sig, 'length': best, 'full_length': length, 'faults': faults, 'moves_recorded': len(moves), 'scripted': False,
              'message': hits(out, inv, sig)[0][2], 't': hits(out, inv, sig)[0][1]}
    # 3. the moves, from the list
    holds = lambda ms, flt=faults, ln=best: bool(hits(play_scene(seed, ms, ln, flt, **keywords), inv, sig))      # noqa: E731
    if not holds(moves):
        result['note'] = 'the seed does not repeat from its list of moves (the violation depends on the random stream of the whole conversation): the prefix is the result'
        result['moves'] = moves
        return result
    result['scripted'] = True
    small = ddmin(moves, holds)
    # 4. without the stand's random faults, when it holds
    if faults and holds(small, False):
        result['faults'], small = False, ddmin(small, lambda ms: holds(ms, False))
    # the scene ends where the violation is
    scene = play_scene(seed, small, best, result['faults'], **keywords)
    again = hits(scene, inv, sig)
    result.update(moves=small, message=again[0][2], t=again[0][1])
    cut = round(again[0][1] + 1.0, 1)
    if cut < best and hits(play_scene(seed, small, cut, result['faults'], **keywords), inv, sig):
        result['length'] = cut
    result['scene'] = describe(seed, small, result['length'], result['faults'], **keywords)
    return result


def describe(seed, moves, length, faults=True, **keywords):
    return ST.describe(play_scene(seed, moves, length, faults, **keywords))


def _job(task):
    seed, inv, sig, length, keywords = task
    try:
        return shrink(seed, inv, sig, length, keywords)
    except Exception as error:                                   # noqa: BLE001 - the tool met a stand crash: a row
        return {'seed': seed, 'inv': inv, 'sig': sig, 'error': f'{type(error).__name__}: {error}'[:300]}


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument('seed', nargs='?', type=int)
    p.add_argument('--inv')
    p.add_argument('--sig')
    p.add_argument('--length', type=float, default=90.0)
    p.add_argument('--fuzz', help='the --json of a fuzz run: the smallest seed of every group')
    p.add_argument('--jobs', type=int, default=3)
    p.add_argument('--json')
    a = p.parse_args(argv)
    tasks = []
    if a.fuzz:
        data = json.load(open(a.fuzz, encoding='utf-8'))
        for sig, rows in data['groups'].items():
            inv = sig.split(' ', 1)[0]
            tasks.append((min(r[0] for r in rows), inv, sig, data['keywords'].get('length', a.length), {k: v for k, v in data['keywords'].items() if k in ('cloud', 'faults')}))
    elif a.seed is not None:
        tasks.append((a.seed, a.inv, a.sig, a.length, {}))
    else:
        p.error('a seed or --fuzz')
    with Pool(a.jobs) as pool:
        results = pool.map(_job, tasks, chunksize=1)
    for r in results:
        if r is None:
            print('clean')
            continue
        print(f"\n== seed {r['seed']} {r.get('sig', '')[:100]}")
        if 'error' in r:
            print('   tool error', r['error'])
            continue
        print(f"   {r['moves_recorded']} -> {len(r['moves'])} moves, length {r['full_length']} -> {r['length']}, faults {r['faults']}, scripted {r['scripted']}")
        print(r.get('scene', r.get('note', '')))
    if a.json:
        with open(a.json, 'w', encoding='utf-8') as f:
            json.dump([r for r in results if r], f, ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
