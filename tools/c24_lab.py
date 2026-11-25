"""C24-d: the bank understands a question without a heavy model. Gold ``cloud_context/bank/holdout/gold_c24.json`` (rounds 1+2 = dev, round 3 = holdout).
python -m tools.c24_lab [--system base_off|base_on|NAME] [--split dev|holdout|all] [--show]. A hit is right when its answer is one of the gold entries' answers,
wrong otherwise; a question with no gold that gets any hit is a false answer (worse than a refusal)."""
import argparse, json, statistics, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from echo_sync import instant  # noqa: E402
from tools.bank_eval import feed, find  # noqa: E402

BANK = ROOT / 'cloud_context' / 'bank'


def load(bank='instant_bank_7.json', gold='holdout/gold_c24.json', bank_dir=BANK):
    rows = [r for r in (instant.clean_entry(x) for x in json.load(open(find(bank_dir, bank), encoding='utf-8'))) if r]
    return rows, json.load(open(find(bank_dir, gold), encoding='utf-8'))


def judge(rows, g, hit_id):
    if hit_id is None:
        return 'none'
    answers = {r['answer'] for r in rows if r['id'] in g['gold']}
    me = next(r for r in rows if r['id'] == hit_id)
    return 'right' if me['answer'] in answers else 'wrong'


def run(system, rows, gold, split='all', kinds=None):
    """system: text -> (entry id or None, early). -> counts and the per-question table."""
    c = {'right': 0, 'wrong_pos': 0, 'false_neg': 0, 'miss': 0, 'n_pos': 0, 'n_neg': 0, 'early': 0}
    table, ms = [], []
    for g in gold:
        if split != 'all' and g['split'] != split or kinds and g['kind'] not in kinds:
            continue
        t = time.perf_counter()
        hid, early = system(g['q'])
        ms.append((time.perf_counter() - t) * 1000)
        v = judge(rows, g, hid)
        if g['gold']:
            c['n_pos'] += 1
            c['right' if v == 'right' else 'wrong_pos' if v == 'wrong' else 'miss'] += 1
            c['early'] += v == 'right' and bool(early)
        else:
            c['n_neg'] += 1
            c['false_neg'] += v != 'none'
        table.append((g['id'], g['kind'], g['q'], g['gold'], hid, v if g['gold'] else ('FALSE' if v != 'none' else 'refused')))
    c['ms_med'] = round(statistics.median(ms), 2) if ms else 0
    c['ms_max'] = round(max(ms), 2) if ms else 0
    return c, table


def fmt(name, c):
    wrong = c['wrong_pos'] + c['false_neg']
    return (f"{name}: right {c['right']}/{c['n_pos']} | wrong on gold {c['wrong_pos']} | false answers on no-gold {c['false_neg']}/{c['n_neg']} | "
            f"all wrong {wrong} | precision {c['right'] / max(c['right'] + wrong, 1):.0%} | ms med {c['ms_med']} max {c['ms_max']}")


def instant_system(rows, **kw):
    ins = instant.Instant([dict(r) for r in rows], adapters=(), **kw)

    def system(text):
        hit, early = feed(ins, text)
        return (hit.id if hit else None), early
    return system


def lookup_system(rows, **kw):
    ins = instant.Instant([dict(r) for r in rows], adapters=(), **kw)

    def system(text):
        hit = ins.lookup(text, final=True, bank_only=True)
        return (hit.id if hit else None), False
    return system


SYSTEMS = {'v2_feed': lambda rows: instant_system(rows), 'v2_lookup': lambda rows: lookup_system(rows)}      # the ranked reading is the rule of every call: the off-systems of the comparison left with the second path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--system', default='v2_feed')
    ap.add_argument('--split', default='all')
    ap.add_argument('--show', action='store_true')
    ap.add_argument('--kind')
    ap.add_argument('--gold', default='holdout/gold_c24.json')
    ap.add_argument('--bank-dir', default=str(BANK))
    ap.add_argument('--bank', default='instant_bank_7.json')
    a = ap.parse_args()
    rows, gold = load(a.bank, a.gold, a.bank_dir)
    for name in a.system.split(','):
        c, table = run(SYSTEMS[name](rows), rows, gold, a.split, a.kind.split(',') if a.kind else None)
        print(fmt(f'{name} [{a.split}{"/" + a.kind if a.kind else ""}]', c))
        if a.show:
            for r in table:
                if r[5] in ('wrong', 'FALSE', 'miss'):
                    print('   ', r[5], r[0], r[1], '|', r[2][:70], '| gold', r[3], 'got', r[4])


if __name__ == '__main__':
    main()
