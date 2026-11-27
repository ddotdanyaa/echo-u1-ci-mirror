"""``python -m tools.ladder [--levels L0-L5] [--scenes 200] [--seed0 0] [--jobs 4] [--flags k:v,...] [--all] [--json out.json] [--show N]``

The table: level, passed of N, the first cause (the commonest fault of the level, a seed of it, the controller's lines before it). From the bottom: a level that is not
a hundred of a hundred stops the climb unless ``--all``. ``--show N``: the first N failed scenes of the first red level, each with its conversation.
"""
import argparse
import json
import sys
import time
from collections import Counter
from multiprocessing import Pool

from tools.ladder import scenes as L


def _one(task):
    level, seed, flags = task
    try:
        r = L.scene(level, seed, flags)
    except Exception as error:                                     # noqa: BLE001 - the stand broke: a row, not a crash of the table
        return {'level': level, 'seed': seed, 'passed': False, 'faults': [('stand_crash', 0.0, f'{type(error).__name__}: {error}'[:200], '')], 'stand': [], 'to_cue': []}
    out = r.pop('out')
    asked = [u for u in out.said if u.kind == 'question' and getattr(u, 'who', '') == 'friend']
    to_cue = []
    for u in asked:
        hit = [c[0] - u.offset for c in out.cues if not c[6] and c[0] > u.onset and u.meaning[1].fits(' '.join(c[4]))]
        if hit:
            to_cue.append(round(max(0.0, hit[0]), 2))
    r['to_cue'] = to_cue
    return r


def levels(text):
    lo, _, hi = text.partition('-')
    a, b = L.LEVELS.index(lo), L.LEVELS.index(hi or lo)
    return list(L.LEVELS[a:b + 1])


def quantile(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round((len(xs) - 1) * q)))] if xs else None


def climb(names, scenes, *, seed0=0, jobs=4, flags=None, every=False, progress=True):
    rows = {}
    with Pool(jobs) as pool:
        for level in names:
            began = time.time()
            got = sorted(pool.map(_one, [(level, s, flags) for s in range(seed0, seed0 + scenes)], chunksize=4), key=lambda r: r['seed'])
            rows[level] = got
            if progress:
                bad = sum(not r['passed'] for r in got)
                print(f'  {level}: {len(got) - bad}/{len(got)} in {time.time() - began:.0f} s', file=sys.stderr)
            if not every and any(not r['passed'] for r in got):
                break
    return rows


def first_cause(got):
    kinds = Counter(r['faults'][0][0] for r in got if not r['passed'])
    if not kinds:
        return ''
    kind, n = kinds.most_common(1)[0]
    ex = next(r for r in got if not r['passed'] and r['faults'][0][0] == kind)
    f = ex['faults'][0]
    rest = ', '.join(f'{k} {c}' for k, c in kinds.most_common()[1:4])
    return f'{kind} ×{n} (seed {ex["seed"]} @{f[1]}: {f[2][:150]}' + (f' | {f[3][:150]}' if f[3] else '') + ')' + (f'; also {rest}' if rest else '')


def table(rows):
    lines = ['| уровень | прошло | p90 до подсказки, с | стенд | первая причина |', '|---|---|---|---|---|']
    for level, got in rows.items():
        ok = sum(r['passed'] for r in got)
        stand = sum(bool(r['stand']) for r in got)
        p90 = quantile([x for r in got for x in r['to_cue']], 0.9)
        lines.append(f'| {level} | {ok}/{len(got)} | {p90 if p90 is not None else "—"} | {stand} | {first_cause(got) or "—"} |')
    return '\n'.join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(prog='python -m tools.ladder')
    ap.add_argument('--levels', default='L0-L5')
    ap.add_argument('--scenes', type=int, default=200)
    ap.add_argument('--seed0', type=int, default=0)
    ap.add_argument('--jobs', type=int, default=4)
    ap.add_argument('--flags', default='')
    ap.add_argument('--all', action='store_true', help='every level, even above a red one')
    ap.add_argument('--json')
    ap.add_argument('--show', type=int, default=0)
    a = ap.parse_args(argv)
    flags = dict(kv.split(':', 1) for kv in a.flags.split(',') if kv) or None
    began = time.time()
    rows = climb(levels(a.levels), a.scenes, seed0=a.seed0, jobs=a.jobs, flags=flags, every=a.all)
    print(table(rows))
    print(f'\n{time.time() - began:.0f} s wall, {sum(len(g) for g in rows.values())} scenes; seconds are the stand\'s')
    if a.json:
        with open(a.json, 'w', encoding='utf-8') as fh:
            json.dump({k: [{x: r[x] for x in ('seed', 'passed', 'faults', 'stand', 'to_cue')} for r in g] for k, g in rows.items()}, fh, ensure_ascii=False, indent=1)
    if a.show:
        from tools.replay.stand import describe
        red = next((g for g in rows.values() if any(not r['passed'] for r in g)), [])
        for r in [r for r in red if not r['passed']][:a.show]:
            out = L._play(L.Scene(r['level'], r['seed'], flags=flags))
            print(f'\n--- {r["level"]} seed {r["seed"]}: {r["faults"][0][:3]}')
            print(describe(out))
    return 0 if all(r['passed'] for g in rows.values() for r in g) else 1


if __name__ == '__main__':
    sys.exit(main())
