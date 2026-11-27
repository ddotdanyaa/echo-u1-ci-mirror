"""Compare two flag-replay folders (tests/test_x_flag_replay.py): per counter totals, per-journal regressions, decision multiset change.
python -m tools.replay.flag_compare BASE OTHER [--json]"""
import json
import sys
from collections import Counter
from pathlib import Path

BAD = ('loops', 'stale', 'failures', 'stuck', 'back', 'timeouts')
CRITICAL_UP = ('stale', 'failures', 'stuck', 'back', 'timeouts')   # any rise in ONE journal blocks: stale audio, a failure, a lost position
CRITICAL_DOWN = ('questions',)                                      # any drop in ONE journal blocks until each lost question is explained


def load(folder):
    return {p.stem: json.loads(p.read_text(encoding='utf-8')) for p in sorted(Path(folder).glob('*.json'))}


def compare(base, other):
    a, b = load(base), load(other)
    common = sorted(set(a) & set(b))
    tot_a, tot_b = Counter(), Counter()
    worse, better, dec_changed, critical = [], [], 0, []
    for j in common:
        ca, cb = a[j]['checks'], b[j]['checks']
        tot_a.update({k: v for k, v in ca.items() if isinstance(v, (int, float))})
        tot_b.update({k: v for k, v in cb.items() if isinstance(v, (int, float))})
        bad_a = sum(ca.get(k, 0) for k in BAD)
        bad_b = sum(cb.get(k, 0) for k in BAD)
        if bad_b > bad_a:
            worse.append((j, {k: (ca.get(k, 0), cb.get(k, 0)) for k in BAD if ca.get(k, 0) != cb.get(k, 0)}))
        elif bad_b < bad_a:
            better.append((j, {k: (ca.get(k, 0), cb.get(k, 0)) for k in BAD if ca.get(k, 0) != cb.get(k, 0)}))
        crit = {k: (ca.get(k, 0), cb.get(k, 0)) for k in CRITICAL_UP if cb.get(k, 0) > ca.get(k, 0)}
        crit.update({k: (ca.get(k, 0), cb.get(k, 0)) for k in CRITICAL_DOWN if cb.get(k, 0) < ca.get(k, 0)})
        if crit:                                                    # judged per journal, never netted against loops gone elsewhere
            critical.append((j, crit))
        if Counter(a[j]['decisions']) != Counter(b[j]['decisions']):
            dec_changed += 1
    keys = sorted(set(tot_a) | set(tot_b))
    return {'journals': len(common), 'missing': sorted(set(a) ^ set(b)),
            'flags': next(iter(b.values()), {}).get('flags'),
            'totals': {k: (tot_a[k], tot_b[k]) for k in keys},
            'bad_total': (sum(tot_a[k] for k in BAD), sum(tot_b[k] for k in BAD)),
            'worse': worse, 'better': better, 'decisions_changed': dec_changed,
            'critical': critical, 'blocking': bool(critical) or bool(set(a) ^ set(b))}


if __name__ == '__main__':
    r = compare(sys.argv[1], sys.argv[2])
    if '--json' in sys.argv:
        print(json.dumps(r, ensure_ascii=False))
    else:
        print(f"flags={r['flags']} journals={r['journals']} missing={len(r['missing'])} bad {r['bad_total'][0]}->{r['bad_total'][1]} "
              f"worse={len(r['worse'])} better={len(r['better'])} decisions_changed={r['decisions_changed']} "
              f"critical={len(r['critical'])} {'BLOCKING' if r['blocking'] else 'no-critical'}")
        for k, (x, y) in r['totals'].items():
            if x != y:
                print(f"  {k}: {x} -> {y}")
        for j, d in r['critical']:
            print('  CRITICAL', j, d)
        for j, d in r['worse']:
            print('  WORSE', j, d)
        for j, d in r['better']:
            print('  better', j, d)
        sys.exit(1 if r['blocking'] else 0)
