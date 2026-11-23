"""U151: take the answers out of the bank that are not fit to be spoken (python -m tools.bank_clean [--bank-dir D --bank F] [--show] [--ids OUT.tsv] [--apply OUT.json]).

Quality before size: an answer is dropped when a listener who has not seen the material could not use it. Checks, each one a rule (no phrase list that grows per case):
DROP: ``short`` fewer than MIN_WORDS words | ``echo`` every content word of the answer is already in the question (it says nothing new) | ``nonanswer`` the answer says it does not know |
``stale`` the question is bound to a day («на 6 ноября», «завтра»): its answer is true on that day only | ``noise`` the question carries speech noise in front («заказ отменен», «так, значит») that no real asker writes.
REPAIR: ``context`` a sentence of the answer points at a paper the listener has not got (the task, the journal, the slide, the variant): the sentence is cut, the row stays when words are left.
REVIEW (listed, never dropped): ``casequestion`` the question asks about a case or task of the course | ``nosource`` the row has no source (it cannot be checked).
``--ids`` writes ``id<TAB>reason`` (the file ``tools/data/bank_clean_ids.tsv`` is the list kept in the repository, the way the numbers of ``bank_number_resolutions.tsv`` are); ``--apply`` writes the bank without those rows
(a new file: the bank on disk is never overwritten). A row of ``KEEP`` is a reviewed row the rules took wrongly: it stays.
The rate on a question list is ``unfit_rate``: the share of questions whose best bank row is in the dropped set (the lookup itself is run by ``bank_states``, not here)."""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import bank_eval  # noqa: E402

IDS = ROOT / 'tools' / 'data' / 'bank_clean_ids.tsv'
MIN_WORDS = 2
STOP = frozenset('и в во на не что как это то а но или для по из за от до при с со к ко у о об же ли бы там тут его ее ей их он она они мы вы я есть быть был была были будет'.split())
NONANSWER = re.compile(r'^\s*(?:не знаю|не могу сказать|нет данных|в материале (?:нет|не сказано)|не указано|затрудняюсь|информации нет)', re.I)
CONTEXT = re.compile(r'как (?:указано|сказано|дано|написано|задано) в (?:задании|условии|варианте|таблице|журнале|файле)|'
                     r'в журнале это|в (?:этом|данном) (?:задании|варианте|кейсе|примере выше)|на (?:этом|данном) слайде|см\.? (?:выше|ниже|таблицу|рисунок)|'
                     r'(?:таблица|рисунок|схема) (?:выше|ниже)|в вашем (?:варианте|задании)|по условию задачи|в тексте (?:выше|задания)', re.I)
CASEQ = re.compile(r'^\s*(?:о чём|про что|что (?:в|за)|кто (?:такой|такая) [а-я]+ из)\s+(?:кейс|задач|вариант|пример|практическ)', re.I)
STALE_Q = re.compile(r'\b(?:сегодня|завтра|вчера|послезавтра|на этой неделе|на следующей неделе|на \d{1,2} (?:января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря))\b', re.I)
NOISE = re.compile(r'^\s*(?:заказ отмен[её]н|так,? значит|значит,? (?:так|что такое)|вот,? значит|ну,? вот)', re.I)
KEEP = frozenset()


def norm(text):
    return ' '.join(str(text).lower().replace('ё', 'е').replace('?', ' ').replace('.', ' ').replace(',', ' ').split())


def content(text):
    return {w[:5] for w in norm(text).split() if w not in STOP and len(w) > 2}


def split_sentences(text):
    return [x for x in re.split(r'(?<=[.!?])\s+', str(text).strip()) if x]


def repaired(answer):
    """-> the answer without the sentences that point at a paper the listener has not got (unchanged when none does)."""
    return ' '.join(x for x in split_sentences(answer) if not CONTEXT.search(x))


def reasons(row):
    """-> (drop, repair, review): lists of reason names of a bank row; all empty = fit."""
    q, a = str(row.get('q') or ''), str(row.get('answer') or '')
    drop, repair, review = [], [], []
    if len(a.split()) < MIN_WORDS:
        drop.append('short')
    elif not content(a) - content(q):
        drop.append('echo')
    if NONANSWER.search(a):
        drop.append('nonanswer')
    if STALE_Q.search(q):
        drop.append('stale')
    if NOISE.search(q):
        drop.append('noise')
    if CONTEXT.search(a):
        if len(repaired(a).split()) >= MIN_WORDS:
            repair.append('context')
        else:
            drop.append('context')
    if CASEQ.search(q):
        review.append('casequestion')
    if not str(row.get('source') or '').strip():
        review.append('nosource')
    return drop, repair, review


def clean(rows, keep=KEEP):
    """-> (rows to keep with the repairs made, [(id, reasons)] dropped, [(id, reasons)] repaired, [(id, reasons)] to review)."""
    kept, dropped, fixed, review = [], [], [], []
    for n, row in enumerate(rows):
        rid = str(row.get('id') or n)
        drop, repair, rev = ([], [], []) if rid in keep else reasons(row)
        if rev:
            review.append((rid, rev))
        if drop:
            dropped.append((rid, drop))
            continue
        if repair:
            fixed.append((rid, repair))
            row = {**row, 'answer': repaired(row.get('answer') or '')}
        kept.append(row)
    return kept, dropped, fixed, review


def unfit_rate(best_ids, dropped_ids):
    """Share of the questions whose best row is a dropped one (``best_ids`` one id or None per question; None counts as «no answer», not unfit)."""
    asked = [b for b in best_ids if b]
    return (sum(1 for b in asked if b in set(dropped_ids)) / len(asked)) if asked else 0.0


def read_ids(path=IDS):
    out = {}
    try:
        for line in Path(path).read_text(encoding='utf-8').splitlines():
            p = line.split('\t')
            if len(p) >= 2 and p[0].strip() and not p[0].startswith('#'):
                out[p[0].strip()] = p[1].strip()
    except OSError:
        pass
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--bank-dir', default=str(bank_eval.BANK))
    ap.add_argument('--bank', default='instant_bank_11.json')
    ap.add_argument('--show', action='store_true')
    ap.add_argument('--ids', help='write id<TAB>reason of the dropped rows here')
    ap.add_argument('--apply', help='write the bank without the dropped rows here')
    a = ap.parse_args(argv)
    path = bank_eval.find(a.bank_dir, a.bank)
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    data = data.get('bank', []) if isinstance(data, dict) else data
    kept, dropped, fixed, review = clean(data)
    count = {}
    for _, why in dropped:
        for w in why:
            count[w] = count.get(w, 0) + 1
    print('passport', json.dumps({'bank': a.bank, 'bank_sha256': bank_eval.sha(path), 'checker_sha256': bank_eval.sha(__file__), 'rows': len(data), 'kept': len(kept), 'dropped': len(dropped), 'repaired': len(fixed), 'review': len(review)}, ensure_ascii=False))
    print('findings', json.dumps(count, ensure_ascii=False))
    if a.show:
        byid = {str(r.get('id')): r for r in data}
        for tag, items in (('drop', dropped), ('repair', fixed), ('review', review)):
          for rid, why in items:
            print(tag, rid, ','.join(why), '|', byid[rid].get('q'), '=>', str(byid[rid].get('answer'))[:120])
    if a.ids:
        Path(a.ids).write_bytes(''.join(f'{rid}\t{",".join(why)}\n' for rid, why in dropped).encode('utf-8'))
    if a.apply:
        Path(a.apply).write_bytes(json.dumps(kept, ensure_ascii=False, indent=1).encode('utf-8'))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
