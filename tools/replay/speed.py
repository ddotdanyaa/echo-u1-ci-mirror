"""G38: the way to the first cue, step by step, on the stand (``first_clock``), with a search that takes time and the flags of a cut on top.

One clean question in silence, no faults. Fixed boundaries, so what is left is what the code waits by itself:
  ``cloud``   the cloud's final this long after the end of speech (stand 1.5 s; the phone: 3.30 s, BACKLOG E93, n=3)
  ``job``     the model's first text this long after its job began (stand 0.6 s; the phone 1.89 s with a source, E93)
  ``search``  the public search this long (the phone 2.01 s, E93; the stand's own lookup is instant)
  ``early``   the early lookup (``controlled_prefetch_enabled`` of the laptop, off there): the search starts from the ear's text or the cloud's still partial
The steps from the end of speech: ``ear`` text of the ear, ``final`` the cloud's, ``search``/``found`` the lookup that grounded the answer, ``job``/``text`` the job whose text
became the first cue and its first text, ``cue`` the first cue on the wire. Times of the stand, not of a laptop nor a phone.

``python -m tools.replay.speed [N] [--phone] [--flags k=v,k=v]`` prints the medians by family.
"""
import argparse
import asyncio
import statistics

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
    a = p.parse_args()
    times = PHONE if a.phone else STAND
    seeds = range(*(int(x) for x in a.seeds.split(':'))) if a.seeds else range(a.n)
    _, out = table(seeds, profile={**F.candidate(), **overlay(a.flags)}, early=a.early, **times)
    show(out)
