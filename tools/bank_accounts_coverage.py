"""S10: does the instant path answer «Что такое счёт NN?» for every account of the plan of accounts (python -m tools.bank_accounts_coverage [--bank-dir D --bank F] [--list]).
The questions are made from ``echo_sync.kb_accounts.ACCOUNTS`` (Order of the Ministry of Finance 94n: the primary source), the fact the answer must hold is the official name of the account
(the first words of it, after ё->е). The matcher is the ear's way (``bank_eval.feed``) of the whole ``Instant``: the bank rows and the code answers of the plan. Prints one JSON line
``{asked, right, wrong, silent, missed}``; exit 1 when an account is not answered right. A wrong or silent account is a gap of the bank (the row to add), never a number to hide."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from echo_sync import instant  # noqa: E402
from echo_sync.kb_accounts import ACCOUNTS  # noqa: E402
from tools import bank_eval  # noqa: E402

FACT_WORDS = 2


def norm(text):
    return ' '.join(str(text).lower().replace('ё', 'е').replace('«', ' ').replace('»', ' ').replace('"', ' ').split())


def questions(accounts=None):
    """-> [(question, fact)]: the on-balance accounts (two digits); the fact is the first ``FACT_WORDS`` words of the official name."""
    out = []
    for number, name in (accounts or ACCOUNTS).items():
        if len(number) == 2:
            out.append((f'Что такое счёт {number}?', ' '.join(norm(name).split()[:FACT_WORDS])))
    return out


def coverage(rows, accounts=None):
    ins = instant.Instant([dict(r) for r in rows])
    right, wrong, silent, missed = 0, 0, 0, []
    asked = questions(accounts)
    for q, fact in asked:
        hit, _ = bank_eval.feed(ins, q)
        if hit is None:
            silent += 1
            missed.append([q, 'silent'])
        elif fact in norm(hit.answer):
            right += 1
        else:
            wrong += 1
            missed.append([q, 'wrong:' + str(hit.id)])
    return {'asked': len(asked), 'right': right, 'wrong': wrong, 'silent': silent, 'missed': missed}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--bank-dir', default=str(bank_eval.BANK))
    ap.add_argument('--bank', default='instant_bank_11.json')
    a = ap.parse_args(argv)
    path = bank_eval.find(a.bank_dir, a.bank)
    out = coverage(instant.load_bank(path))
    out['bank'] = a.bank
    out['bank_sha256'] = bank_eval.sha(path)
    print(json.dumps(out, ensure_ascii=False))
    return 0 if out['right'] == out['asked'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
