"""E66: the 30 reference answers of the bank, checked each in its own way (python -m tools.bank_etalons [--bank-dir D --bank F] [--law law.sqlite] [--list]).

``tools/data/bank_etalons_30.tsv``, one row per etalon: ``id<TAB>kind<TAB>subject<TAB>origin<TAB>key<TAB>check<TAB>date<TAB>status``.
kind: definition | difference | cause | calc | norm | material | ambiguous (every kind of the task is in the list).
origin: where the bank row took the fact (its ``source``). key: the facts the answer must say, ``;`` between (all of them, after ё->е and lower case).
check: ``calc:<expression>=<number>`` the number is worked out here by Python from the numbers of the task, independent of the bank | ``law:<code>:<article>:<needle>`` the needle is a verbatim piece of the article in the law base
(the primary source; its edition date is the ``date``) | ``none`` the fact is the material's own: only the owner can say it is right.
status: ``tool`` the check above passed on the data | ``owner`` goes on the one list «верно / нет» for the owner (every row with check ``none`` and every calc whose source number was not opened).
The tool says per row ``ok`` / ``key-missing`` / ``calc-differs`` / ``law-missing`` / ``law-differs`` / ``row-missing`` / ``no-law-base`` (the base is data of the laptop: without ``--law`` the law rows are not checked and are NOT counted as passed)."""
import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import bank_eval  # noqa: E402

ETALONS = ROOT / 'tools' / 'data' / 'bank_etalons_30.tsv'
KINDS = ('definition', 'difference', 'cause', 'calc', 'norm', 'material', 'ambiguous')
NUMBER = re.compile(r'^[0-9+\-*/(). ]+$')


def norm(text):
    return ' '.join(str(text).lower().replace('ё', 'е').replace('\xa0', ' ').split())


def read(path=ETALONS):
    rows = []
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        p = line.rstrip('\n').split('\t')
        if len(p) >= 8 and p[0] and not p[0].startswith('#') and p[0] != 'id':
            rows.append(dict(zip(('id', 'kind', 'subject', 'origin', 'key', 'check', 'date', 'status'), p[:8])))
    return rows


def calc(expression):
    """The value of ``a+b*c`` of numbers only (nothing else is evaluated: the string is refused when it holds a letter or a call)."""
    if not NUMBER.match(expression):
        raise ValueError(expression)
    return eval(expression, {'__builtins__': {}}, {})  # noqa: S307 - digits and + - * / ( ) . only, checked above


def law_text(conn, code, article):
    rows = conn.execute("SELECT text FROM rows WHERE doc = ? AND article = ? AND kind != 'cut' ORDER BY seq", (code, article)).fetchall()
    return norm(' '.join(r[0] for r in rows)) if rows else None


def check_one(et, bank, law=None):
    row = bank.get(et['id'])
    if row is None:
        return 'row-missing'
    text = norm(row.get('answer') or '')
    if any(norm(f) not in text for f in et['key'].split(';') if f.strip()):
        return 'key-missing'
    kind, _, rest = et['check'].partition(':')
    if kind == 'calc':
        expression, _, want = rest.rpartition('=')
        try:
            ok = abs(calc(expression) - float(want.replace(',', '.'))) < 0.006
        except (ValueError, SyntaxError, ZeroDivisionError):
            return 'calc-differs'
        return 'ok' if ok else 'calc-differs'
    if kind == 'law':
        if law is None:
            return 'no-law-base'
        code, article, needle = rest.split(':', 2)
        body = law_text(law, code, article)
        if body is None:
            return 'law-missing'
        return 'ok' if norm(needle) in body else 'law-differs'
    return 'ok' if et['check'] == 'none' else 'row-missing'


def run(bank_rows, etalons, law=None):
    bank = {str(r.get('id')): r for r in bank_rows}
    return [(et['id'], et['kind'], check_one(et, bank, law)) for et in etalons]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--bank-dir', default=str(bank_eval.BANK))
    ap.add_argument('--bank', default='instant_bank_11.json')
    ap.add_argument('--law', help='the law base file (sqlite) of the laptop')
    ap.add_argument('--etalons', default=str(ETALONS))
    ap.add_argument('--list', action='store_true', help='print the one list «верно / нет» for the owner')
    a = ap.parse_args(argv)
    path = bank_eval.find(a.bank_dir, a.bank)
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    data = data.get('bank', []) if isinstance(data, dict) else data
    law = sqlite3.connect('file:%s?mode=ro' % a.law, uri=True) if a.law else None
    etalons = read(a.etalons)
    result = run(data, etalons, law)
    count = {}
    for _, _, state in result:
        count[state] = count.get(state, 0) + 1
    print('passport', json.dumps({'bank': a.bank, 'bank_sha256': bank_eval.sha(path), 'checker_sha256': bank_eval.sha(__file__), 'etalons': len(etalons), 'kinds': sorted({e['kind'] for e in etalons}), 'law': a.law}, ensure_ascii=False))
    print('findings', json.dumps(count, ensure_ascii=False))
    for rid, kind, state in result:
        if state != 'ok':
            print(f'{state} {rid} {kind}')
    if a.list:
        byid = {str(r.get('id')): r for r in data}
        n = 0
        for et in etalons:
            if et['status'] == 'owner':
                n += 1
                r = byid.get(et['id'], {})
                print(f'{n}. [{et["id"]}] {r.get("q")} -> {r.get("answer")}  (источник: {et["origin"]}) верно / нет')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
