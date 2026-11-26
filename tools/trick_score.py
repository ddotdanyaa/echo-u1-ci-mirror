"""U74 (S6, outside the call): the scorer of the trick set (``tools/trick_set.json``: questions with a false premise, with conditions of period / units / negation and with a chain to check, labelled by a model that does not answer).
python -m tools.trick_score ANSWERS.jsonl [--set PATH] [--json]       ANSWERS: one object per line, ``{"id": ..., "road": ..., "text": ...}``.
Per road TWO numbers, kept apart: ``issued`` (an answer was given: not empty, not a dash, not an honest «не знаю») and ``correct`` (issued and every rule of the question holds), each of the questions asked, with the 95% Wilson interval; and the count of
the issued answers that broke a CONDITION of the question (a unit not named, the false premise taken, the period of the question, the «не» / «кроме»), by condition. An answer is wrong or right by the rules of the question alone: no model is called here.
The rules (``RULES``): accept_any / accept_all (the value; an item is a word start, ``=`` after it a whole word, a number is a whole number), reject_any (what the negation excludes), units_any (a unit must be named), premise_any (the answer must reject the false premise).
A measurement of the roads needs the laptop (the real models and the phone path); this tool only counts the answers it is given."""
import argparse
import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

SET = Path(__file__).with_name('trick_set.json')
RULES = frozenset(('accept_any', 'accept_all', 'reject_any', 'units_any', 'premise_any'))
CONDITIONS = ('units', 'premise', 'period', 'negation')      # a failure of these names is a broken condition; ``wrong`` is a wrong value or chain only
_KIND_NAME = {'period': 'period', 'negation': 'negation', 'false_premise': 'premise'}
_REFUSAL = re.compile(r'не\s+знаю|не\s+наш[её]л|не\s+могу\s+(?:ответить|сказать)|нет\s+данных')
Z = 1.959964


def load_set(path=None):
    return json.loads(Path(path or SET).read_text(encoding='utf-8'))


def wilson(k, n, z=Z):
    """The 95% Wilson interval of k of n (``(0.0, 0.0)`` for n == 0)."""
    if n <= 0:return 0.0, 0.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return max(0.0, round(c - h, 12)), min(1.0, round(c + h, 12))


def _norm(text):
    text = unicodedata.normalize('NFKC', str(text or '')).casefold().replace('ё', 'е')
    text = re.sub(r'(?<=\d)[  ](?=\d{3}(?!\d))', '', text)      # «3 600» is 3600
    return re.sub(r'\s+', ' ', text)


def _has(text, item):
    item = _norm(item)
    if item.endswith('='):pattern = r'(?<!\w)' + re.escape(item[:-1]) + r'(?!\w)'
    elif item[:1].isdigit():pattern = r'(?<![\d,.])' + re.escape(item) + r'(?!\d|[,.]\d)'
    elif not item[:1].isalpha():pattern = re.escape(item)
    else:pattern = r'(?<!\w)' + re.escape(item)
    return re.search(pattern, text) is not None


def issued(text):
    text = str(text or '').strip()
    return bool(text.strip('—–-.… ')) and not (len(text) < 80 and _REFUSAL.search(_norm(text)))


def judge(question, text):
    """The names of what ``text`` fails of ``question``'s rules: ``units``, ``premise``, ``period``, ``negation`` (a broken condition) or ``wrong`` (the value or the chain); ``[]``: all rules hold."""
    rules, text, failed = question['rules'], _norm(text), []
    if rules.get('units_any') and not any(_has(text, i) for i in rules['units_any']):failed.append('units')
    if rules.get('premise_any') and not any(_has(text, i) for i in rules['premise_any']):failed.append('premise')
    if any(_has(text, i) for i in rules.get('reject_any', ())):failed.append('negation')
    if (rules.get('accept_any') and not any(_has(text, i) for i in rules['accept_any'])) or not all(_has(text, i) for i in rules.get('accept_all', ())):
        failed.append(_KIND_NAME.get(question['kind'], 'wrong'))
    return list(dict.fromkeys(failed))


def _blank():
    return {'asked': 0, 'issued': 0, 'correct': 0, 'missing': 0, 'unknown': 0, 'duplicates': 0, 'broke': 0, 'wrong_other': 0, 'broke_by': Counter()}


def score(answers, trick=None):
    """``{road: numbers}`` from the rows of ``answers`` (the last row of an id on a road counts, rows of an id the set does not have are set aside)."""
    trick = trick or load_set()
    questions = {q['id']: q for q in trick['questions']}
    last, roads = {}, {}
    for row in answers:
        road = str(row.get('road', ''))
        roads.setdefault(road, _blank())
        if row.get('id') not in questions:roads[road]['unknown'] += 1;continue
        roads[road]['duplicates'] += (road, row['id']) in last
        last[(road, row['id'])] = row.get('text')
    for road, got in roads.items():
        got['asked'] = len(questions)
        for qid, question in questions.items():
            if (road, qid) not in last or not issued(last[(road, qid)]):
                got['missing'] += (road, qid) not in last;continue
            got['issued'] += 1
            failed = judge(question, last[(road, qid)])
            if not failed:got['correct'] += 1;continue
            if any(name in CONDITIONS for name in failed):
                got['broke'] += 1;got['broke_by'].update(name for name in failed if name in CONDITIONS)
            else:got['wrong_other'] += 1
        got['issued_ci'], got['correct_ci'] = wilson(got['issued'], got['asked']), wilson(got['correct'], got['asked'])
        got['correct_of_issued_ci'] = wilson(got['correct'], got['issued'])
    return roads


def _pct(k, n, ci):
    return f'{k}/{n} = {100 * k / n if n else 0:.0f}% (95% {100 * ci[0]:.0f}-{100 * ci[1]:.0f}%)'


def render(roads):
    lines = []
    for road, g in sorted(roads.items()):
        lines += [f'road {road or "?"}: asked {g["asked"]}',
                  f'  issued  {_pct(g["issued"], g["asked"], g["issued_ci"])}',
                  f'  correct {_pct(g["correct"], g["asked"], g["correct_ci"])}   (of issued: {_pct(g["correct"], g["issued"], g["correct_of_issued_ci"])})',
                  f'  broke a condition of the question: {g["broke"]} ' + ', '.join(f'{k} {v}' for k, v in sorted(g['broke_by'].items())) + f'; wrong in value or chain only: {g["wrong_other"]}; no row: {g["missing"]}; unknown id: {g["unknown"]}; repeated id: {g["duplicates"]}']
    return '\n'.join(lines + ['These are counts of the answers given to this tool. A measurement on the roads (real models, the phone path) is for the laptop; the labels have no human check yet.'])


def main(argv=None):
    parser = argparse.ArgumentParser(prog='tools.trick_score', description=__doc__.split('\n')[0])
    parser.add_argument('answers', help='jsonl: id, road, text')
    parser.add_argument('--set', default=None)
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)
    rows = [json.loads(line) for line in Path(args.answers).read_text(encoding='utf-8').splitlines() if line.strip()]
    roads = score(rows, load_set(args.set))
    print(json.dumps({k: {**v, 'broke_by': dict(v['broke_by'])} for k, v in roads.items()}, ensure_ascii=False, indent=1) if args.json else render(roads))
    return 0


if __name__ == '__main__':
    sys.exit(main())
