"""W11: how well the ranked path of ``instant`` finds the bank's answer: python -m tools.bank_eval [--half dev|test|all] [--grid] [--partials].
Gold ``cloud_context/bank/gold.json`` (written by hand: the right entry of every blind question or none). The halves: dev = even ``i``, test = odd
``i``; the thresholds are tuned on dev only. A hit is right when its entry is the gold one or one of ``ok`` (the same answer), wrong otherwise."""
import argparse, hashlib, json, statistics, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from echo_sync import instant  # noqa: E402

BANK = ROOT / 'cloud_context' / 'bank'


def find(bank_dir, name):
    """``name`` in ``bank_dir``, else in its ``eval`` subfolder (the gold copies of МАТЕРИАЛЫ/БАНК live there)."""
    bank_dir = Path(bank_dir)
    return bank_dir / name if (bank_dir / name).exists() or not (bank_dir / 'eval' / name).exists() else bank_dir / 'eval' / name


def load(bank_dir=BANK, bank='instant_bank_2.json'):
    rows = [r for r in (instant.clean_entry(x) for x in json.load(open(find(bank_dir, bank), encoding='utf-8'))) if r]
    tests = json.load(open(find(bank_dir, '16_BANK_TEST.json'), encoding='utf-8'))
    gold = {g['i']: g for g in json.load(open(find(bank_dir, 'gold.json'), encoding='utf-8'))}
    return rows, tests, gold


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def passport(bank_dir, bank, half, n, of):
    """What the numbers were measured on: the files by hash, the half and n of N (the questions scored of the questions in the file)."""
    return {'bank': bank, 'bank_sha256': sha(find(bank_dir, bank)), 'tests_sha256': sha(find(bank_dir, '16_BANK_TEST.json')),
            'gold_sha256': sha(find(bank_dir, 'gold.json')), 'checker_sha256': sha(__file__), 'half': half, 'n': n, 'of': of}


def in_half(i, half):
    return not (half == 'dev' and i % 2 or half == 'test' and not i % 2)


def judge(rows, gold, e):
    """'right' | 'wrong' | 'none' for entry index ``e`` (or None) against one gold row."""
    if e is None:
        return 'none'
    ids = {gold.get('gold')} | set(gold.get('ok') or ())
    if rows[e]['id'] in ids:
        return 'right'
    good = [r for r in rows if r['id'] in ids]
    return 'right' if any(r['answer'] == rows[e]['answer'] for r in good) else 'wrong'


def feed(ins, text):
    """The ear's way (score_bank.py): partials word by word, then the cut-off. -> (hit or None, early)"""
    import re
    ins.reset()
    words = re.sub(r'[^\w\s-]', ' ', text.lower().replace('ё', 'е')).split()
    for n in range(1, len(words) + 1):
        hit = ins.feed(' '.join(words[:n]), 0.35 * n, final=n == len(words))
        if hit:
            return hit, n < len(words)
    return None, False


def run_full(ins, rows, tests, gold, half):
    """The whole ``Instant`` (the full match, the ranked path, partials) as score_bank.py feeds it, judged against gold."""
    index = {r['id']: k for k, r in enumerate(rows)}
    out = {'right': 0, 'wrong': 0, 'none': 0, 'neg_hit': 0, 'n_gold': 0, 'n_neg': 0, 'early': 0, 'wrongs': []}
    for i, t in enumerate(tests):
        if not in_half(i, half):
            continue
        g = gold[i]
        hit, early = feed(ins, t['q'])
        v = judge(rows, g, index.get(hit.id) if hit else None)
        out['early'] += bool(hit) and early and v == 'right'
        if g.get('gold'):
            out['n_gold'] += 1
            out[v] += 1
        else:
            out['n_neg'] += 1
            out['neg_hit'] += v != 'none'
            out['wrong'] += v != 'none'
        if v == 'wrong':
            out['wrongs'].append((i, t['q'], hit.q, 'early' if early else 'final'))
    return out


def run(ranker, rows, tests, gold, half, min_score, gap):
    out = {'right': 0, 'wrong': 0, 'none': 0, 'neg_hit': 0, 'n_gold': 0, 'n_neg': 0, 'wrongs': []}
    for i, t in enumerate(tests):
        if not in_half(i, half):
            continue
        g = gold[i]
        got = ranker.best(t['q'], min_score=min_score, gap=gap)
        v = judge(rows, g, got[0] if got else None)
        if g.get('gold'):
            out['n_gold'] += 1
            out[v] += 1
        else:
            out['n_neg'] += 1
            out['neg_hit'] += v != 'none'
            out['wrong'] += v != 'none'
        if v == 'wrong':
            out['wrongs'].append((i, t['q'], rows[got[0]]['q'], got[1]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--half', default='dev')
    ap.add_argument('--bank-dir', default=str(BANK), help='the folder with the bank, 16_BANK_TEST.json and gold.json (or their eval/ subfolder)')
    ap.add_argument('--bank', default='instant_bank_2.json', help='the bank file inside --bank-dir')
    ap.add_argument('--grid', action='store_true')
    ap.add_argument('--show', action='store_true')
    ap.add_argument('--curve', action='store_true', help='precision and recall through Instant.feed as RANK_MIN and RANK_GAP move')
    ap.add_argument('--full', action='store_true', help='through Instant.feed, partials and the cut-off, as score_bank.py')
    a = ap.parse_args()
    rows, tests, gold = load(a.bank_dir, a.bank)
    ranker = instant.Ranker(rows)
    have = sum(bool(g.get('gold')) for g in gold.values())
    print(f'gold: {have} of {len(gold)} questions have the answer in the bank ({have / len(gold):.0%}); of the 200 written as answerable:',
          sum(bool(gold[i].get('gold')) for i, t in enumerate(tests) if t['answerable']), '; of the 40 not:',
          sum(bool(gold[i].get('gold')) for i, t in enumerate(tests) if not t['answerable']))
    print('passport', json.dumps(passport(a.bank_dir, a.bank, a.half, sum(in_half(i, a.half) for i in range(len(tests))), len(tests)), ensure_ascii=False))
    if a.curve:
        ins = instant.Instant([dict(r) for r in rows], adapters=())
        keep = instant.RANK_MIN, instant.RANK_GAP
        print('RANK_MIN RANK_GAP | right/gold | wrong (no-answer) | precision')
        for s, g in [(s, keep[1]) for s in (0.5, 0.6, 0.65, 0.7, 0.75, 0.8, 0.9, 0.95)] + [(keep[0], g) for g in (0.0, 0.05, 0.1, 0.2, 0.25, 0.3)]:
            instant.RANK_MIN, instant.RANK_GAP = s, g
            r = run_full(ins, rows, tests, gold, a.half)
            fired = r['right'] + r['wrong']
            print(f"{s:.2f} {g:.2f} | {r['right']}/{r['n_gold']} ({r['right'] / max(r['n_gold'], 1):.0%}) | {r['wrong']} ({r['neg_hit']}) | {r['right'] / max(fired, 1):.1%}")
        instant.RANK_MIN, instant.RANK_GAP = keep
        return
    if a.full:
        ins = instant.Instant([dict(r) for r in rows], adapters=())
        base = instant.Instant([dict(r) for r in rows], adapters=(), rank=False)
        for name, x in (('full match only (W5)', base), ('full match + ranked (W11)', ins)):
            r = run_full(x, rows, tests, gold, a.half)
            fired = r['right'] + r['wrong']
            print(f"{name}: half {a.half} | right {r['right']}/{r['n_gold']} ({r['right'] / max(r['n_gold'], 1):.0%}), of them early {r['early']} |"
                  f" wrong {r['wrong']} ({r['neg_hit']} of {r['n_neg']} no-answer) | precision {r['right'] / max(fired, 1):.1%}")
            if a.show:
                for w in r['wrongs']:
                    print('   WRONG', w)
        return
    grid = [(s, g) for s in (0.4, 0.45, 0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8) for g in (0.0, 0.05, 0.1, 0.15, 0.2)] if a.grid else [(instant.RANK_MIN, instant.RANK_GAP)]
    print('half', a.half, '| min gap | right/gold (recall) | wrong (of them on no-answer questions) | precision')
    for s, g in grid:
        r = run(ranker, rows, tests, gold, a.half, s, g)
        fired = r['right'] + r['wrong']
        print(f"{s:.2f} {g:.2f} | {r['right']}/{r['n_gold']} ({r['right'] / max(r['n_gold'], 1):.0%}) | {r['wrong']} ({r['neg_hit']} of {r['n_neg']}) |"
              f" {r['right'] / max(fired, 1):.1%}")
        if a.show:
            for w in r['wrongs']:
                print('   WRONG', w)
    ms = []
    for t in tests:
        a0 = time.perf_counter()
        ranker.best(t['q'])
        ms.append((time.perf_counter() - a0) * 1000)
    print('ranked lookup ms median', round(statistics.median(ms), 2), 'max', round(max(ms), 2))


if __name__ == '__main__':
    main()
