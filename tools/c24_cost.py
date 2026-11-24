"""C24-d: the price of a query on one core: python -m tools.c24_cost  (run under ``taskset -c 0``). Build time of the index, lookup and the whole feed (word by word), median / p95 / max in ms."""
import json, resource, statistics, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from echo_sync import instant  # noqa: E402
from tools import c24_lab as L  # noqa: E402
from tools.bank_eval import feed  # noqa: E402


def pct(v, p):
    v = sorted(v)
    return v[min(len(v) - 1, int(len(v) * p))]


def main():
    rows, gold = L.load()
    gold += L.load(gold='holdout/gold_c24_w11.json')[1]
    qs = [g['q'] for g in gold]
    for name, kw in (('rank off', dict(rank=False)), ('rank on (W11/F5)', dict(rank=True)), ('rank on + rank2 (C24)', dict(rank=True, rank2=True))):
        t = time.process_time()
        ins = instant.Instant([dict(r) for r in rows], adapters=(), **kw)
        build = time.process_time() - t
        ins.lookup(qs[0], final=True, bank_only=True)                     # the lazy init of the morphology, once
        look, whole = [], []
        for q in qs:
            a = time.process_time()
            ins.lookup(q, final=True, bank_only=True)
            look.append((time.process_time() - a) * 1000)
        for q in qs:
            a = time.process_time()
            feed(ins, q)
            whole.append((time.process_time() - a) * 1000)
        steps = []                                                   # one ``feed`` call = one partial of the ear: the price of a query as the voice pays it
        import re
        for q in qs:
            ins.reset()
            words = re.sub(r'[^\w\s-]', ' ', q.lower().replace('ё', 'е')).split()
            for n in range(1, len(words) + 1):
                a = time.process_time()
                hit = ins.feed(' '.join(words[:n]), 0.35 * n, final=n == len(words))
                steps.append((time.process_time() - a) * 1000)
                if hit:
                    break
        print(f'{name:24s} one partial/final ms: med {statistics.median(steps):5.2f} p95 {pct(steps, .95):5.2f} p99 {pct(steps, .99):6.2f} max {max(steps):6.2f} (n {len(steps)}) | lookup p99 {pct(look, .99):6.2f}')
        print(f'{name:24s} build {build:5.1f} s | lookup ms med {statistics.median(look):5.2f} p95 {pct(look, .95):5.2f} max {max(look):6.2f} | '
              f'feed (all partials) ms med {statistics.median(whole):5.2f} p95 {pct(whole, .95):6.2f} max {max(whole):6.2f} | n {len(qs)}')
    print('peak RSS MB', resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024)


if __name__ == '__main__':
    main()
