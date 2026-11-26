"""U33: a failing rehearsal seed down to its smallest scene (delta debugging, the classic ddmin of ``tools.replay.ddmin``), for the rehearsals of ``tools.rehearsal``.

    python -m tools.rehearsal.shrink NAME SEED [--kind missed] [--mutant mute] [--json out.json]

A rehearsal seed is a long conversation; the owner of the finding needs the few utterances that still give the same failure. The seed is played once and every move of its
listener is written down ``(index, t, kind, barge)``; the moves are played again from the list (each move has a random stream of its own, so a move taken out does not change
the others) and the list is cut by ddmin while the same KIND of failure stays: an episode kind of the board (``score.board``: missed, false_cue, false_step, lost_place,
old_answer) or an invariant of the stand (``A2`` ...). No product code; seconds are the stand's clock.
"""
import argparse
import json
import random
from functools import partial

from tools.rehearsal import score, sim
from tools.replay import ddmin as D

CUE_KINDS = ('repeat', 'partial', 'wrong', 'stutter', 'own', 'more', 'self')


class Recorded(sim.Rehearsal):
    """The rehearsal's own conversation with the moves of its listener written down; the listener decides from a stream of its own, as ``ddmin.Recorder`` does."""

    def __init__(self, spec, seed, **keywords):
        self.moves = []
        super().__init__(spec, seed, **keywords)

    def decide(self):
        if not hasattr(self, 'drng'):
            self.drng = random.Random(f'{self.spec.name}-{self.seed}-decide')
        self.rng, kept = self.drng, self.rng
        try:
            super().decide()
        finally:
            self.rng = kept

    def speak(self, kind, cue, barge=False):
        self.moves.append([len(self.moves), round(self.now(), 3), kind, bool(barge)])
        self.rng = random.Random(f'{self.spec.name}-{self.seed}-move-{self.moves[-1][0]}')
        super().speak(kind, cue, barge)


class Scripted(sim.Rehearsal):
    """A rehearsal played from a list of moves; the listener decides nothing."""

    def __init__(self, spec, seed, moves=(), **keywords):
        self.script = moves
        super().__init__(spec, seed, **keywords)

    def decide(self):
        pass

    def play(self):
        for move in self.script:
            self.later(move[1], partial(self._move, move))
        return super().play()

    def _move(self, move):
        index, t, kind, barge = move
        if self.now() < self.free - 1e-9:
            self.later(self.free, partial(self._move, move))
            return
        self.rng = random.Random(f'{self.spec.name}-{self.seed}-move-{index}')
        cue = self.last_cue()
        last = self.said[-1] if self.said else None
        fresh = cue is not None and (last is None or cue.t - self.zero > last.offset) and self.following and not self.stopped
        if kind in CUE_KINDS and not fresh:
            kind = 'question'
        playing = self.w.open is not None and not self.w.open.diagnostic
        self.speak(kind, cue if fresh else None, barge=barge and playing)


def kinds_of(out):
    """The failures of one run: the episode kinds of its board and the invariants of its violations."""
    return {e['kind'] for e in score.board(out)[1]} | {inv for inv, *_ in out.violations}


def shrink(spec, seed, kind=None, mutant=None):
    """``None`` when the seed is clean; else a dict with the failure ``kind``, the moves recorded and the smallest list that still fails with it, and the scene as the stand tells it."""
    recorded = {}

    class Mine(Recorded):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            recorded['stand'] = self
    out = sim.play(spec, seed, mutant=mutant, keep_log=False, stand=Mine)
    found = kinds_of(out)
    kind = kind or next(iter(sorted(found, key=lambda k: -score.WEIGHT.get(k, 1))), None)
    if kind is None or kind not in found:
        return None
    moves = list(recorded['stand'].moves)

    def holds(items):
        return kind in kinds_of(sim.play(spec, seed, mutant=mutant, keep_log=False, stand=partial(Scripted, moves=items)))
    if not holds(moves):
        return {'seed': seed, 'rehearsal': spec.name, 'kind': kind, 'moves_recorded': len(moves), 'scripted': False, 'moves': moves,
                'note': 'the failure does not repeat from the list of moves (it depends on the random stream of the whole conversation)'}
    small = D.ddmin(moves, holds)
    return {'seed': seed, 'rehearsal': spec.name, 'kind': kind, 'moves_recorded': len(moves), 'scripted': True, 'moves': small}


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument('name')
    p.add_argument('seed', type=int)
    p.add_argument('--kind')
    p.add_argument('--mutant')
    p.add_argument('--json')
    a = p.parse_args(argv)
    result = shrink(sim.Spec(a.name), a.seed, a.kind, a.mutant)
    if result is None:
        print('clean')
        return 0
    print(f"{result['rehearsal']} seed {result['seed']} {result['kind']}: {result['moves_recorded']} -> {len(result['moves'])} moves, scripted {result['scripted']}")
    if a.json:
        with open(a.json, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=1)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
