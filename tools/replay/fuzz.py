"""A1: many seeds of ``stand.run`` in parallel; the violations grouped by invariant and first message, each group with its smallest seed.

    python -m tools.replay.fuzz --seeds 0:2000 --jobs 4 [--length 90] [--cloud 0.5,5] [--no-faults] [--json out.json] [--show 3]
"""
import argparse
import json
import re
import sys
import time
from collections import defaultdict
from multiprocessing import Pool


def _one(args):
    seed, keywords = args
    import logging
    logging.disable(logging.WARNING)                  # the controller's warnings of a fault the seed made: the record has what matters
    from tools.replay import stand
    out = stand.run(seed, **keywords)
    return seed, out.profile, [(inv, t, msg) for inv, t, msg in out.violations], len(out.said), len([c for c in out.cues if not c[6]]), out.crash


def signature(inv, message):
    """The group of a violation: the invariant and its message without the numbers and quoted texts."""
    text = re.sub(r"'[^']*'|\"[^\"]*\"", '«…»', message)
    text = re.sub(r'\d+(\.\d+)?', 'N', text)
    return f'{inv} {text[:110]}'


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument('--seeds', default='0:200')
    p.add_argument('--jobs', type=int, default=4)
    p.add_argument('--length', type=float, default=90.0)
    p.add_argument('--cloud', default='0.5,5')
    p.add_argument('--no-faults', action='store_true')
    p.add_argument('--json')
    p.add_argument('--show', type=int, default=0, help='print the whole conversation of the smallest seed of each group')
    a = p.parse_args(argv)
    lo, hi = (int(x) for x in a.seeds.split(':'))
    keywords = {'length': a.length, 'cloud': tuple(float(x) for x in a.cloud.split(',')), 'faults': not a.no_faults}
    began = time.time()
    groups, seeds_with, said, cues, crashes, done = defaultdict(list), defaultdict(set), 0, 0, [], 0
    with Pool(a.jobs) as pool:
        for seed, profile, violations, n_said, n_cues, crash in pool.imap_unordered(_one, [(s, keywords) for s in range(lo, hi)], chunksize=4):
            said, cues, done = said + n_said, cues + n_cues, done + 1
            if done % 250 == 0:
                print(f'.. {done} seeds, {time.time() - began:.0f} s', file=sys.stderr, flush=True)
            if crash:
                crashes.append(seed)
            for inv, t, msg in violations:
                groups[signature(inv, msg)].append((seed, t, msg, profile))
                seeds_with[inv].add(seed)
    total = hi - lo
    print(f'{total} seeds, {said} utterances, {cues} cues, {time.time() - began:.0f} s wall, crashes {sorted(crashes)[:10]}')
    for inv in sorted(seeds_with):
        print(f'{inv}: {len(seeds_with[inv])} seeds ({100 * len(seeds_with[inv]) / total:.1f}%)')
    ranked = sorted(groups.items(), key=lambda kv: (-len({s for s, *_ in kv[1]}), kv[0]))
    for sig, rows in ranked:
        rows.sort()
        seed, t, msg, profile = rows[0]
        print(f'\n[{len({s for s, *_ in rows})} seeds] {sig}\n   min seed {seed} @{t}: {msg[:300]}\n   seeds {sorted({s for s, *_ in rows})[:12]}')
    if a.show:
        from tools.replay import stand
        for sig, rows in ranked[:a.show]:
            print('\n' + '=' * 100 + f'\n{sig}\n' + stand.describe(stand.run(min(s for s, *_ in rows), **keywords)))
    if a.json:
        with open(a.json, 'w', encoding='utf-8') as f:
            json.dump({'seeds': [lo, hi], 'keywords': keywords, 'groups': {sig: [r[:3] for r in rows] for sig, rows in ranked}}, f, ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
