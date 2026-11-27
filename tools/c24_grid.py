"""C24-d: threshold grid of the ranked path on the dev splits (history rounds 1+2 and W11 even i), the lookup path of rank2. Zero false answers is the constraint,
the right count the aim. python -m tools.c24_grid [--out cloud_context/reports/c24-tables/grid_dev.txt]"""
import argparse, itertools, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from echo_sync import instant  # noqa: E402
from tools import c24_lab as L  # noqa: E402

SETS = (('history', 'holdout/gold_c24.json', 'dev'), ('w11', 'holdout/gold_c24_w11.json', 'dev'))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out')
    ap.add_argument('--rank2', default='1')
    a = ap.parse_args()
    rows, _ = L.load()
    ins = instant.Instant([dict(r) for r in rows], adapters=(), rank=True, rank2=a.rank2 == '1')

    def system(text):
        hit = ins.lookup(text, final=True, bank_only=True)
        return (hit.id if hit else None), False
    golds = [(n, L.load(gold=g)[1], sp) for n, g, sp in SETS]
    lines = ['RANK_MIN RANK_GAP FORM_MIN COVER_MIN | history right/false | w11 right/false | total right  false']
    keep = (instant.RANK_MIN, instant.RANK_GAP, instant.RANK_FORM_MIN, instant.RANK_COVER_MIN)
    for mn, gap, fm, cv in itertools.product((0.5, 0.6, 0.7, 0.8), (0.05, 0.10, 0.15, 0.25), (0.6, 0.7, 0.8), (0.5, 0.6, 0.7)):
        instant.RANK_MIN, instant.RANK_GAP, instant.RANK_FORM_MIN, instant.RANK_COVER_MIN = mn, gap, fm, cv
        res = [L.run(system, rows, g, sp)[0] for _, g, sp in golds]
        r = [x['right'] for x in res]
        f = [x['false_neg'] + x['wrong_pos'] for x in res]
        lines.append(f'{mn:.2f} {gap:.2f} {fm:.2f} {cv:.2f} | {r[0]}/{f[0]} | {r[1]}/{f[1]} | {sum(r)} {sum(f)}')
    instant.RANK_MIN, instant.RANK_GAP, instant.RANK_FORM_MIN, instant.RANK_COVER_MIN = keep
    text = '\n'.join(lines)
    if a.out:
        Path(a.out).write_text(text + '\n', encoding='utf-8')
    best = sorted(lines[1:], key=lambda s: (int(s.split('|')[-1].split()[1]), -int(s.split('|')[-1].split()[0])))
    print('\n'.join([lines[0]] + best[:12]))


if __name__ == '__main__':
    main()
