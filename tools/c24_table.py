"""C24-d: the 500-row adversarial table of W5 (tests/helpers_w5_instant.table: foreign words, number and «не» twins, unfinished questions, ear errors) through
the ear's path with rank2 and the given thresholds. python -m tools.c24_table [--min .7 --gap .15 --form .8 --cover .6] """
import argparse, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
from echo_sync import instant  # noqa: E402
import helpers_w5_instant as fx  # noqa: E402


def run_table(rival_w=1.0):
    ix = instant.Instant(fx.bank(), rival_w=rival_w)
    false, got, wanted, cut_hits = [], 0, 0, 0
    for row in fx.table():
        ix.reset()
        hit, cut = None, False
        for k, text in enumerate(row['partials']):
            h = ix.feed(text, 0.3 * k, final=k == len(row['partials']) - 1)
            hit = hit or h
            if hit and ix.cut:
                cut = True
                break
        hid = hit.id if hit else ''
        if hit and not cut and hid not in row['ok']:
            false.append((row['kind'], row['heard'], hid))
        if row['want']:
            wanted += 1
            got += hid == row['want'] and not cut
    return false, got, wanted


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--min', type=float, default=instant.RANK_MIN)
    ap.add_argument('--gap', type=float, default=instant.RANK_GAP)
    ap.add_argument('--form', type=float, default=instant.RANK_FORM_MIN)
    ap.add_argument('--cover', type=float, default=instant.RANK_COVER_MIN)
    ap.add_argument('--rival', type=float, default=1.0, help='U21-S6: the weight of the rival in the margin')
    a = ap.parse_args()
    instant.RANK_MIN, instant.RANK_GAP, instant.RANK_FORM_MIN, instant.RANK_COVER_MIN = a.min, a.gap, a.form, a.cover
    f, got, wanted = run_table(rival_w=a.rival)
    print(f'min {a.min} gap {a.gap} form {a.form} cover {a.cover} rival {a.rival}: false accepts {len(f)}, wanted hits got {got}/{wanted}')
    for x in f:
        print('   FALSE', x)
