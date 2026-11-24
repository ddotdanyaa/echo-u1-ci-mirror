"""G38: the way to the first cue, step by step, on the stand (``first_clock``), with a search that takes time and the flags of a cut on top.

One clean question in silence, no faults. Fixed boundaries, so what is left is what the code waits by itself:
  ``cloud``   the cloud's final this long after the end of speech (stand 1.5 s; the phone: 3.30 s, BACKLOG E93, n=3)
  ``job``     the model's first text this long after its job began (stand 0.6 s; the phone 1.89 s with a source, E93)
  ``search``  the public search this long (the phone 2.01 s, E93; the stand's own lookup is instant)
  ``early``   the early lookup (the call's ``ear_lookup``, off by default): the search starts from the ear's text or the cloud's still partial
The steps from the end of speech: ``ear`` text of the ear, ``final`` the cloud's, ``search``/``found`` the lookup that grounded the answer, ``job``/``text`` the job whose text
became the first cue and its first text, ``cue`` the first cue on the wire. Times of the stand, not of a laptop nor a phone.

``python -m tools.replay.speed [N] [--phone] [--flags k=v,k=v]`` prints the medians by family.

U218/U121 (I4), one build against another on the same scenes: ``python -m tools.replay.speed N --phone --json --out run_<sha>.json`` in each checkout (the scenes are fixed by seed and
family, so both builds get the same questions), then ``python -m tools.replay.speed --compare old.json new.json``: per family and in total the silent and wrong cues, violations, median
and p90 of the cue after the end of speech, per scene fixed / remained / new / same, and «faster» only when median AND p90 fall and no scene is new. The stand has no tokens: they are
``unknown`` here (the journals' tokens: ``tools.harvest.measure.build_numbers``). Times are the stand's, not a laptop's nor a phone's.
"""
import argparse
import asyncio
import json
import statistics
import subprocess

from tools.replay import first_clock as F
from tools.replay import stand as A

PHONE = {'cloud': 3.3, 'job': 1.9, 'search': 2.0}
STAND = {'cloud': 1.5, 'job': 0.6, 'search': 0.0}
FAMILIES = ('money', 'mult', 'verb', 'year', 'article')


class Timed(F.One):
    """``first_clock.One`` with a search that lasts ``search`` s of the stand's clock and the early lookup on or off."""

    def __init__(self, seed, question, *, search=0.0, early=False, ear=None, **keywords):
        self.search, self.early, self.lookups, self.ear_of = search, early, [], ear
        super().__init__(seed, question, **keywords)

    def heard_by_ear(self, text, kind, exact=False):
        heard = super().heard_by_ear(text, kind, exact)
        return self.ear_of(heard) if self.ear_of and not exact and heard else heard      # c22-speed: the ear heard another thing than the cloud

    def _attach(self):
        super()._attach()
        w, stand = self.w, self
        clock = w.clock

        async def lookup(question):
            w.lookup_calls.append(question)
            row = {'at': stand.now(), 'question': question, 'end': None}
            stand.lookups.append(row)
            due = clock.now() + stand.search
            while clock.now() < due - 1e-9:
                await asyncio.sleep(0)
            row['end'] = stand.now()
            return list(A.S.SOURCE_ROWS)
        w.wire.lookup = lookup
        w.wire.early.fetch = lookup
        w.wire.early.enabled = bool(self.early)


def scene(seed, *, family=None, profile=None, cloud=1.5, job=0.6, search=0.0, early=False, length=25.0, question=None, ear=None):
    """The steps of one question of ``family`` (seconds from the end of its speech); ``cue`` None: no cue. ``question``: a ``stand.Q`` of one's own,
    or a function of the drawn one; ``ear``: what the ear makes of its words (c22-speed: an ear that heard another number or «не»)."""
    import random
    rng = random.Random(seed)
    q = A.ask(rng)
    while family and q.family != family:
        q = A.ask(rng)
    q = question(q) if callable(question) else question or q
    stand = Timed(seed, q, length=length, cloud=(cloud, cloud), job=(job, job), profile=dict(profile or F.candidate()), search=search, early=early, ear=ear)
    try:
        out = stand.play()
    finally:
        stand.close()
    u = out.said[0]
    cues = [c for c in out.cues if not c[6]]
    rel = lambda t: None if t is None else round(t - u.offset, 2)
    row = {'seed': seed, 'family': q.family, 'question': q.text, 'ear': rel(u.ear_at), 'final': rel(u.final_at), 'cue': rel(cues[0][0]) if cues else None,
           'said': cues[0][1] if cues else None, 'right': bool(cues) and q.fits(cues[0][1]), 'violations': [v[0] for v in A.check(out)]}
    before = [j for j in out.jobs if cues and j['at'] <= cues[0][0] and j['answer'] != '—']
    used = before[-1] if before else None
    row['job'] = rel(used['at']) if used else None
    row['text'] = rel(used['at'] + used['first']) if used else None
    found = [r for r in stand.lookups if r['end'] is not None and (not cues or r['end'] <= cues[0][0])]
    row['search'] = rel(found[-1]['at']) if found else None
    row['found'] = rel(found[-1]['end']) if found else None
    row['lookups'] = len(stand.lookups)
    return row


def p90(xs):
    """The 90th percentile, nearest rank (of 20: the 18th)."""
    xs = sorted(xs)
    return xs[max(0, -(-9 * len(xs) // 10) - 1)] if xs else None


def table(seeds, families=FAMILIES, **keywords):
    rows = [scene(seed, family=family, **keywords) for family in families for seed in seeds]
    out = {}
    for family in families:
        mine = [r for r in rows if r['family'] == family]
        med = lambda key: (lambda xs: round(statistics.median(xs), 2) if xs else None)([r[key] for r in mine if r[key] is not None])
        out[family] = {key: med(key) for key in ('ear', 'final', 'search', 'found', 'job', 'text', 'cue')}
        out[family].update(n=len(mine), right=sum(r['right'] for r in mine), silent=sum(r['cue'] is None for r in mine),
                           violations=sum(bool(r['violations']) for r in mine), p90=p90([r['cue'] for r in mine if r['cue'] is not None]))
    return rows, out


def sha_of(root=None):
    """The git sha of the checkout the run was made on (``unknown`` outside git): the table is only «one sha» if it says which."""
    try:
        return subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=root, capture_output=True, text=True, timeout=20).stdout.strip() or 'unknown'
    except (OSError, subprocess.SubprocessError):
        return 'unknown'


def run(seeds, families=FAMILIES, **keywords):
    """A run as data: ``{'sha', 'times', 'rows', 'families'}``; ``rows`` one per scene with its key ``family:seed`` (numbers, labels and the question text of the stand)."""
    rows, out = table(seeds, families, **keywords)
    seeds = list(seeds)
    for row in rows:
        row['key'] = f"{row['family']}:{row['seed']}"
    return {'sha': sha_of(), 'times': {k: keywords[k] for k in ('cloud', 'job', 'search') if k in keywords}, 'early': bool(keywords.get('early')), 'seeds': [seeds[0], seeds[-1] + 1] if seeds else [],
            'rows': rows, 'families': out}


def _bad(row):
    return row['cue'] is None or not row['right'] or bool(row['violations'])


def compare_runs(old, new):
    """Old against new on the same scenes. Per scene exactly one of ``fixed`` (bad on old, good on new), ``remained`` (bad on both), ``new`` (good on old, bad on new), ``same`` (good on both);
    scenes are the same only with equal key, question text and times. ``faster``: the same scenes, median and p90 of the cue both lower, no ``new`` scene."""
    a, b = {r['key']: r for r in old['rows']}, {r['key']: r for r in new['rows']}
    keys = sorted(set(a) & set(b))
    differ = sorted(k for k in keys if a[k]['question'] != b[k]['question'])
    kinds = {}
    for k in keys:
        x, y = _bad(a[k]), _bad(b[k])
        kinds[k] = 'remained' if x and y else 'fixed' if x else 'new' if y else 'same'

    def numbers(rows):
        cues = [r['cue'] for r in rows if r['cue'] is not None]
        return {'n': len(rows), 'silent': sum(r['cue'] is None for r in rows), 'wrong': sum(r['cue'] is not None and not r['right'] for r in rows),
                'violations': sum(bool(r['violations']) for r in rows), 'median': round(statistics.median(cues), 2) if cues else None, 'p90': p90(cues), 'tokens_per_useful_answer': None}
    per = {}
    for fam in sorted({a[k]['family'] for k in keys}):
        mine = [k for k in keys if a[k]['family'] == fam]
        per[fam] = {'old': numbers([a[k] for k in mine]), 'new': numbers([b[k] for k in mine]), 'counts': {c: sum(kinds[k] == c for k in mine) for c in ('fixed', 'remained', 'new', 'same')}}
    total = {'old': numbers([a[k] for k in keys]), 'new': numbers([b[k] for k in keys])}
    verdict = {}
    for key in ('median', 'p90', 'silent', 'wrong', 'violations'):
        p, q = total['old'][key], total['new'][key]
        verdict[key] = 'unknown' if p is None or q is None else 'better' if q < p else 'worse' if q > p else 'same'
    counts = {c: sum(v == c for v in kinds.values()) for c in ('fixed', 'remained', 'new', 'same')}
    same = old.get('times') == new.get('times') and old.get('early') == new.get('early') and not differ and set(a) == set(b)
    return {'old_sha': old.get('sha'), 'new_sha': new.get('sha'), 'same_scenes': same, 'question_differs': differ, 'only_old': sorted(set(a) - set(b)), 'only_new': sorted(set(b) - set(a)),
            'times': new.get('times'), 'families': per, 'total': total, 'counts': counts, 'verdict': verdict, 'scenes': {k: v for k, v in kinds.items() if v != 'same'},
            'faster': same and not counts['new'] and verdict['median'] == 'better' and verdict['p90'] == 'better', 'not_worse': same and not counts['new']}


def show_compare(c):
    print(f"old={c['old_sha']} new={c['new_sha']} same_scenes={c['same_scenes']} counts={c['counts']} faster={c['faster']} not_worse={c['not_worse']} times={c['times']}")
    print('family       n  silent old/new  wrong old/new  viol old/new   median old/new    p90 old/new   fixed/remained/new')
    for fam, m in list(c['families'].items()) + [('TOTAL', {'old': c['total']['old'], 'new': c['total']['new'], 'counts': c['counts']})]:
        o, n = m['old'], m['new']
        print(f"{fam:8} {o['n']:5}  {o['silent']:>6}/{n['silent']:<6} {o['wrong']:>6}/{n['wrong']:<6} {o['violations']:>6}/{n['violations']:<6} {o['median']!s:>8}/{n['median']!s:<8} {o['p90']!s:>6}/{n['p90']!s:<6}  "
              f"{m['counts']['fixed']}/{m['counts']['remained']}/{m['counts']['new']}")
    for k, kind in c['scenes'].items():
        print(f'  {kind:8} {k}')


def overlay(text):
    return {k: A._value(v) for k, v in (item.split('=', 1) for item in (text or '').split(',') if '=' in item)}


def show(out):
    keys = ('ear', 'final', 'search', 'found', 'job', 'text', 'cue')
    print('family  ' + ' '.join(f'{k:>6}' for k in keys) + '    p90  right/n silent bad')
    for family, m in out.items():
        print(f'{family:8}' + ' '.join(f"{'-' if m[k] is None else m[k]:>6}" for k in keys) + f"  {'-' if m['p90'] is None else m['p90']:>5}  {m['right']}/{m['n']} {m['silent']} {m['violations']}")


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('n', nargs='?', type=int, default=20)
    p.add_argument('--phone', action='store_true')
    p.add_argument('--early', action='store_true')
    p.add_argument('--flags', default='')
    p.add_argument('--seeds', default='', help='lo:hi instead of 0:n')
    p.add_argument('--json', action='store_true', help='the run as data (rows per scene, the sha of the checkout) instead of the table')
    p.add_argument('--out', default='', help='write the --json run to this file')
    p.add_argument('--compare', nargs=2, metavar=('OLD', 'NEW'), help='two --json runs of two builds: the table old / new')
    a = p.parse_args()
    if a.compare:
        c = compare_runs(*(json.loads(open(f, encoding='utf-8').read()) for f in a.compare))
        print(json.dumps(c, ensure_ascii=False) if a.json else '', end='')
        if not a.json:
            show_compare(c)
        raise SystemExit(0 if c['not_worse'] else 1)
    times = PHONE if a.phone else STAND
    seeds = range(*(int(x) for x in a.seeds.split(':'))) if a.seeds else range(a.n)
    if a.json or a.out:
        data = run(seeds, profile={**F.candidate(), **overlay(a.flags)}, early=a.early, **times)
        text = json.dumps(data, ensure_ascii=False)
        if a.out:
            with open(a.out, 'w', encoding='utf-8', newline='\n') as f:
                f.write(text)
        print(text if a.json and not a.out else f"{data['sha']} {len(data['rows'])} scenes")
    else:
        _, out = table(seeds, profile={**F.candidate(), **overlay(a.flags)}, early=a.early, **times)
        show(out)
