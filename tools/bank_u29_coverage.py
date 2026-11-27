"""U29: how many of the gap questions the instant matcher answers with the expected fact: ``python tools/bank_u29_coverage.py --bank B.json [--questions Q.tsv] [--rank2]``.
Q.tsv: question<TAB>fact that the answer must hold (casefold substring). The matcher is the ear's way (``bank_eval.feed``: partials, then the cut-off), the adapters off.
Prints one JSON line: ``{asked, answered, right, wrong, silent, coverage, missed}``; exit 1 when a question is not answered right."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from echo_sync import instant  # noqa: E402
from tools import bank_eval  # noqa: E402

DEFAULT_BANK = ROOT / 'tools' / 'data' / 'bank_u29.json'
DEFAULT_QUESTIONS = ROOT / 'tools' / 'data' / 'bank_u29_questions.tsv'


def read_questions(path):
    out = []
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        q, _, fact = line.partition('\t')
        if q.strip() and fact.strip():
            out.append((q.strip(), fact.strip()))
    return out


def coverage(rows, questions):
    ins = instant.Instant([dict(r) for r in rows], adapters=())
    right = wrong = silent = 0
    missed = []
    for q, fact in questions:
        hit, _ = bank_eval.feed(ins, q)
        if hit is None:
            silent += 1
            missed.append([q, 'silent'])
        elif fact.casefold() in hit.answer.casefold():
            right += 1
        else:
            wrong += 1
            missed.append([q, 'wrong:' + hit.id])
    n = len(questions)
    return {'asked': n, 'answered': right + wrong, 'right': right, 'wrong': wrong, 'silent': silent, 'coverage': round(right / n, 4) if n else 0.0, 'missed': missed}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--bank', default=str(DEFAULT_BANK), help='the bank file (a JSON list of rows); the laptop bank: the output of build_instant_bank.py with the supplement')
    ap.add_argument('--questions', default=str(DEFAULT_QUESTIONS))
    args = ap.parse_args(argv)
    out = coverage(instant.load_bank(args.bank), read_questions(args.questions))
    print(json.dumps(out, ensure_ascii=False))
    return 0 if out['right'] == out['asked'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
