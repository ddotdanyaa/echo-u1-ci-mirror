"""U21-S7: content audit of the answer bank (python -m tools.bank_audit [--bank-dir D --bank F] [--resolve OUT]). Prints counts per check and the findings.

Checks: ``number`` two rows of one source say two near numbers (50,01 / 50,02) | ``alt`` a question or alt that two rows with different answers both hold |
``first`` the first sentence of an answer is longer than FIRST_WORDS words (the first portion is spoken at once) | ``unit`` a «сколько / какая доля» answer with numbers and no unit |
``source`` a row with no source | ``volatile`` wording that goes stale (now, current, last, rate) with no date in the answer.
A number conflict is resolved from the source, never by the audit: ``tools/data/bank_number_resolutions.tsv`` (wrong<TAB>right<TAB>basis); ``--resolve OUT`` writes the bank with
those numbers set right (bank 11) and leaves every other row as it was."""
import argparse, json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import bank_eval  # noqa: E402

RESOLUTIONS = ROOT / 'tools' / 'data' / 'bank_number_resolutions.tsv'
NUM = re.compile(r'(?<![\d,.])\d+(?:,\d+)?(?![\d])')
NEAR = 0.0205                                                         # two numbers of one source with the same decimals and this close are one fact written twice
FIRST_WORDS = 28
UNITS = re.compile(r'%|процент|руб|млрд|млн|тыс|дн|год|лет|месяц|недел|час|минут|шт|раз|коп|\bдол|ставк|балл|пункт|штук|человек|\bг\.', re.I)
ASKS_QUANTITY = re.compile(r'^\s*(?:сколько|какая доля|какой процент|какова ставка|какая ставка)', re.I)
VOLATILE = re.compile(r'сейчас|в настоящее время|на сегодня|текущ|последн|\bкурс[а-я]* (?:доллар|евро|валют)|ключев[а-я]+ ставк', re.I)
DATE = re.compile(r'\b(?:19|20)\d\d\b|\d{1,2}\.\d{1,2}\.\d{2,4}')


def norm(text):
    return ' '.join(str(text).lower().replace('ё', 'е').replace('?', ' ').replace('.', ' ').split())


def value(token):
    return float(token.replace(',', '.'))


def decimals(token):
    return len(token.split(',')[1]) if ',' in token else 0


def numbers(row):
    return sorted(set(NUM.findall(str(row.get('answer') or ''))))


def rid(row, n):
    return str(row.get('id') or n)


def number_conflicts(rows):
    """-> [(a, b, [ids of rows saying a], [ids of rows saying b], source)]: near numbers, same decimals, of rows that cite one source."""
    by_source = {}
    for n, row in enumerate(rows):
        src = norm(row.get('source') or '')
        if src:
            by_source.setdefault(src, []).append((rid(row, n), numbers(row)))
    out = []
    for src, items in by_source.items():
        tokens = sorted({t for _, toks in items for t in toks if decimals(t)})
        for i, a in enumerate(tokens):
            for b in tokens[i + 1:]:
                if decimals(a) == decimals(b) and abs(value(a) - value(b)) <= NEAR and value(a) >= 10:
                    out.append((a, b, [i_ for i_, toks in items if a in toks], [i_ for i_, toks in items if b in toks], src))
    return out


def alt_drift(rows):
    """-> [(text, [ids])]: one question text that rows with different answers all hold (the lookup meets two answers and keeps silent or picks one)."""
    seen = {}
    for n, row in enumerate(rows):
        for text in {norm(t) for t in [row.get('q'), *(row.get('alt') or ())] if t}:
            seen.setdefault(text, {}).setdefault(norm(row.get('answer') or ''), rid(row, n))
    return [(t, sorted(ids.values())) for t, ids in seen.items() if len(ids) > 1]


def first_portion(rows):
    out = []
    for n, row in enumerate(rows):
        first = re.split(r'(?<=[.!?])\s+(?=[А-ЯЁA-Z])', str(row.get('answer') or '').strip(), maxsplit=1)[0]
        if len(first.split()) > FIRST_WORDS:
            out.append((rid(row, n), len(first.split())))
    return out


def unit_gaps(rows):
    return [rid(r, n) for n, r in enumerate(rows) if ASKS_QUANTITY.match(str(r.get('q') or '')) and numbers(r) and not UNITS.search(str(r.get('answer') or ''))]


def no_source(rows):
    return [rid(r, n) for n, r in enumerate(rows) if not str(r.get('source') or '').strip()]


def volatile(rows):
    return [rid(r, n) for n, r in enumerate(rows) if VOLATILE.search(str(r.get('answer') or '')) and not DATE.search(str(r.get('answer') or ''))]


def audit(rows):
    return {'number': number_conflicts(rows), 'alt': alt_drift(rows), 'first': first_portion(rows), 'unit': unit_gaps(rows), 'source': no_source(rows), 'volatile': volatile(rows)}


def read_resolutions(path=RESOLUTIONS):
    out = {}
    try:
        for line in Path(path).read_text(encoding='utf-8').splitlines():
            p = line.split('\t')
            if len(p) >= 2 and p[0].strip() and p[1].strip():
                out[p[0].strip()] = p[1].strip()
    except OSError:
        pass
    return out


def resolve(rows, resolutions):
    """-> (new rows, [ids changed]): a number written wrong (``resolutions``) is set right in the rows of a conflict that name it; nothing else is touched."""
    wrong_ids = {i for a, b, ia, ib, _ in number_conflicts(rows) for tok, ids in ((a, ia), (b, ib)) if tok in resolutions for i in ids}
    out, changed = [], []
    for n, row in enumerate(rows):
        text = str(row.get('answer') or '')
        new = NUM.sub(lambda m: resolutions.get(m.group(0), m.group(0)), text) if rid(row, n) in wrong_ids else text
        if new != text:
            changed.append(rid(row, n))
            row = {**row, 'answer': new}
        out.append(row)
    return out, changed


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--bank-dir', default=str(bank_eval.BANK))
    ap.add_argument('--bank', default='instant_bank_10.json')
    ap.add_argument('--resolve', help='write the bank with the resolved numbers here (bank 11)')
    ap.add_argument('--resolutions', default=str(RESOLUTIONS))
    ap.add_argument('--show', action='store_true')
    a = ap.parse_args(argv)
    path = bank_eval.find(a.bank_dir, a.bank)
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    data = data.get('bank', []) if isinstance(data, dict) else data
    res = audit(data)
    print('passport', json.dumps({'bank': a.bank, 'bank_sha256': bank_eval.sha(path), 'checker_sha256': bank_eval.sha(__file__), 'rows': len(data)}, ensure_ascii=False))
    print('findings', json.dumps({k: len(v) for k, v in res.items()}))
    for x, y, ix, iy, src in res['number']:
        print(f'number {x} / {y}: rows {",".join(ix)} vs {",".join(iy)}  [{src[:60]}]')
    if a.show:
        for k in ('alt', 'first', 'unit', 'source', 'volatile'):
            for item in res[k]:
                print(f'{k} {item}')
    if a.resolve:
        fixed, changed = resolve(data, read_resolutions(a.resolutions))
        Path(a.resolve).write_text(json.dumps(fixed, ensure_ascii=False, indent=1), encoding='utf-8')
        print('resolved', json.dumps({'changed': changed, 'left': len(audit(fixed)['number'])}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
