"""Compare two flag-replay folders (tests/test_x_flag_replay.py): per counter totals, per-journal regressions, decision multiset change.
python -m tools.replay.flag_compare BASE OTHER [--json]

U218/U121 (I4): the same journals replayed on two builds (the folders of ``ECHO_FLAG_OUT`` of the old sha and of the new one) as a table old / new:
``python -m tools.replay.flag_compare BASE OTHER --table [--json]``. Per journal exactly one of fixed / remained / new / same (bad = loops, stale, failures, stuck, back,
timeouts); the totals; median and p90 of the first cue after a question and the tokens per useful answer ONLY when the runner wrote ``latency_ms`` / ``tokens`` into the
journal file (patch ``proposals/I4/x_flag_replay_latency.diff``), otherwise ``unknown``: a number the replay did not write is not guessed. «Faster» only when median AND p90
fall and nothing new fails. ``--overlay SRC DST`` copies the runner and the two tools onto an older checkout that does not have them (the build under test is DST's echo_sync).
"""
import json
import shutil
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


OVERLAY = ('tests/test_x_flag_replay.py', 'tools/replay/flag_compare.py', 'tools/replay/speed.py')    # what an older build lacks; its echo_sync and its harness stay


def overlay(src, dst):
    """Copy the runner and the comparison tools from the new checkout ``src`` onto the old checkout ``dst``; returns the files copied. The build under test is DST's ``echo_sync``."""
    done = []
    for name in OVERLAY:
        a, b = Path(src) / name, Path(dst) / name
        if a.is_file() and (not b.is_file() or a.read_bytes() != b.read_bytes()):
            b.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(a, b)
            done.append(name)
    return done


def _q(xs, q):
    xs = sorted(xs)
    if not xs:
        return None
    k = (len(xs) - 1) * q
    lo = int(k)
    return round(xs[lo] + (xs[min(lo + 1, len(xs) - 1)] - xs[lo]) * (k - lo))


def _bad(checks):
    return sum(checks.get(k, 0) for k in BAD)


def numbers(folder):
    """The numbers of one build over the folder's journals: N, bad counters, cues, errors (failures), median/p90 ms of the first cue (None when no file wrote ``latency_ms``), tokens per cue."""
    data = load(folder)
    lat = [x for d in data.values() for x in d.get('latency_ms', []) if isinstance(x, (int, float)) and not isinstance(x, bool)]
    cues = sum(d['checks'].get('cues', 0) for d in data.values())
    tokens = [d['tokens'] for d in data.values() if isinstance(d.get('tokens'), (int, float)) and not isinstance(d.get('tokens'), bool)]
    return {'N': len(data), 'bad': sum(_bad(d['checks']) for d in data.values()), 'errors': sum(d['checks'].get('failures', 0) for d in data.values()), 'cues': cues,
            'questions': sum(d['checks'].get('questions', 0) for d in data.values()), 'latency_n': len(lat), 'median_ms': _q(lat, 0.5), 'p90_ms': _q(lat, 0.9),
            'tokens_per_useful_answer': round(sum(tokens) / cues, 1) if tokens and cues else None}


def table(base, other):
    """Old (``base``) against new (``other``) on the same journals: per journal fixed / remained / new / same, the numbers of both and the verdict per metric.
    ``new`` = the new build is worse on a journal (bad counters up or a critical rise), whatever got better elsewhere; ``faster`` needs both median and p90 down, no new, same journals."""
    a, b = load(base), load(other)
    rows = {}
    for j in sorted(set(a) & set(b)):
        ca, cb = a[j]['checks'], b[j]['checks']
        crit = any(cb.get(k, 0) > ca.get(k, 0) for k in CRITICAL_UP) or any(cb.get(k, 0) < ca.get(k, 0) for k in CRITICAL_DOWN)
        x, y = _bad(ca), _bad(cb)
        rows[j] = 'new' if (y > x or crit) else 'fixed' if y < x else 'remained' if x else 'same'
    old, new = numbers(base), numbers(other)
    verdict = {}
    for key in ('median_ms', 'p90_ms', 'errors', 'bad', 'tokens_per_useful_answer'):
        p, q = old.get(key), new.get(key)
        verdict[key] = 'unknown' if p is None or q is None else 'better' if q < p else 'worse' if q > p else 'same'
    same = sorted(set(a) ^ set(b)) == [] and old['N'] == new['N']
    count = Counter(rows.values())
    return {'old': old, 'new': new, 'journals': rows, 'counts': dict(count), 'missing': sorted(set(a) ^ set(b)), 'same_journals': same, 'verdict': verdict,
            'old_sha': next((d.get('sha') for d in a.values() if d.get('sha')), None), 'new_sha': next((d.get('sha') for d in b.values() if d.get('sha')), None),
            'faster': same and not count.get('new') and verdict['median_ms'] == 'better' and verdict['p90_ms'] == 'better' and verdict['errors'] in ('better', 'same'),
            'not_worse': same and not count.get('new') and verdict['errors'] in ('better', 'same')}


def show_table(t):
    print(f"old={t['old_sha']} new={t['new_sha']} same_journals={t['same_journals']} missing={len(t['missing'])} counts={t['counts']} faster={t['faster']} not_worse={t['not_worse']}")
    print('metric                      old       new   verdict')
    for key in ('bad', 'errors', 'cues', 'questions', 'median_ms', 'p90_ms', 'tokens_per_useful_answer'):
        print(f"{key:24} {t['old'].get(key)!s:>8}  {t['new'].get(key)!s:>8}   {t['verdict'].get(key, '')}")
    for j, kind in t['journals'].items():
        if kind != 'same':
            print(f'  {kind:8} {j}')


if __name__ == '__main__' and '--overlay' in sys.argv:
    print('\n'.join(overlay(*[x for x in sys.argv[1:] if not x.startswith('--')][:2])) or 'nothing to copy')
    sys.exit(0)

if __name__ == '__main__' and '--table' in sys.argv:
    t = table(*[x for x in sys.argv[1:] if not x.startswith('--')][:2])
    print(json.dumps(t, ensure_ascii=False) if '--json' in sys.argv else '', end='')
    if '--json' not in sys.argv:
        show_table(t)
    sys.exit(0 if t['not_worse'] else 1)

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
