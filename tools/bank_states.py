"""U21-S2: where a question is lost between the bank and the voice, in five states (python -m tools.bank_states [--bank-dir D --bank F --questions T.tsv]).
S0 the bank holds no right answer | S1 it holds one, the lookup gave none | S2 the lookup gave a wrong one | S3 the right one was found, the
controller did not admit it | S4 it was admitted, not spoken. 'ok' is the way out of all five (what is not measured yet, ``admitted``/``spoken`` None, is not a failure). A row of the questions file is ``question<TAB>key<TAB>label``: the key is the
fact the right answer must say (several: ``a;b``), the label tells where the key came from (``given``, ``sheet``, ``textbook``, ``self-labelled``)."""
import argparse, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import bank_eval  # noqa: E402

STATES = {'S0': 'no right answer in the bank', 'S1': 'in the bank, lookup found none', 'S2': 'lookup found a wrong one', 'S3': 'found, not admitted', 'S4': 'admitted, not spoken'}
QUESTIONS = ROOT.parents[1] / 'МАТЕРИАЛЫ' / 'БАНК' / 'eval' / 'sheet_questions.tsv'      # the checkout sits in U1/05_WORK/<tree>: overridden by --questions
HONEST = ('given', 'sheet', 'textbook')                                                   # any other label (``self-labelled``) says the key is the author's own


def norm(text):
    return ' '.join(str(text).lower().replace('ё', 'е').split())


def facts(key):
    return [f for f in (norm(p) for p in str(key).split(';')) if f]


def completeness(answer, key):
    """-> (the facts of ``key`` the answer says, the facts it does not). The check that an answer is the right one and not only a near one."""
    text = norm(answer)
    got, miss = [], []
    for f in facts(key):
        (got if f in text else miss).append(f)
    return got, miss


def right(text, key):
    """Does ``text`` say every fact of ``key``."""
    return bool(facts(key)) and not completeness(text, key)[1]


def entry_text(row, label='given'):
    """What a key is checked against: the ANSWER only, so a topic word of the entry's question cannot make a wrong hit right. Only the owner's own keys (``given``,
    set before any tuning, often a topic word) may also match the entry's question."""
    return ' '.join([row['q'], *(row.get('alt') or ()), row['answer']]) if label == 'given' else row['answer']


def classify(*, in_bank, hit=None, hit_ok=False, admitted=None, spoken=None):
    """-> 'S0'..'S4', or 'ok'. ``hit``: what the lookup gave (None: nothing); ``admitted`` / ``spoken``: False when the controller held it / it was not
    heard, None when that layer was not measured."""
    if hit is None:
        return 'S1' if in_bank else 'S0'
    if not hit_ok:
        return 'S2'
    if admitted is False:
        return 'S3'
    return 'S4' if spoken is False else 'ok'


def read_rows(path=QUESTIONS):
    """-> [(question, key, label)]; a row with no key has label ``unlabelled`` and is left out of the states."""
    rows = []
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        p = line.split('\t')
        if p[0].strip():
            rows.append((p[0].strip(), p[1].strip() if len(p) > 1 else '', (p[2].strip() if len(p) > 2 else 'given') if len(p) > 1 and p[1].strip() else 'unlabelled'))
    return rows


def measure(rows, ins, questions, admitted=None, spoken=None):
    """Each labelled question through ``Instant`` (as bank_eval.feed). -> [(question, state, label, missing facts of a wrong hit)]"""
    out = []
    for q, key, label in questions:
        if label == 'unlabelled':
            continue
        hit, _ = bank_eval.feed(ins, q)
        state = classify(in_bank=any(right(entry_text(r, label), key) for r in rows), hit=hit, hit_ok=bool(hit) and right(entry_text({'q': hit.q, 'answer': hit.answer}, label), key),
                         admitted=admitted, spoken=spoken)
        out.append((q, state, label, completeness(entry_text({'q': hit.q, 'answer': hit.answer}, label), key)[1] if hit else []))
    return out


def tally(results, honest=None):
    """Counts per state. ``honest`` True: only rows labelled from the source (``HONEST``); False: only the author's own (self-labelled); None: all."""
    count = {s: 0 for s in (*STATES, 'ok')}
    for _, state, label, _ in results:
        if honest is None or (label in HONEST) == honest:
            count[state] += 1
    return count


def main():
    from echo_sync import instant
    ap = argparse.ArgumentParser()
    ap.add_argument('--bank-dir', default=str(bank_eval.BANK))
    ap.add_argument('--bank', default='instant_bank_2.json')
    ap.add_argument('--questions', default=str(QUESTIONS), help='tsv: question, key, label (sheet_questions.tsv); --also adds more files')
    ap.add_argument('--also', action='append', default=[], help='more tsv files (real_questions.tsv)')
    ap.add_argument('--rank2', default='on', choices=('on', 'off'), help='the ranked reading of a spoken question (C24) as the live profile has it')
    ap.add_argument('--show', action='store_true')
    a = ap.parse_args()
    rows = [r for r in (instant.clean_entry(x) for x in json.load(open(bank_eval.find(a.bank_dir, a.bank), encoding='utf-8'))) if r]
    r2 = a.rank2 == 'on'
    questions = [x for f in [a.questions, *a.also] for x in read_rows(f)]
    results = measure(rows, instant.Instant([dict(r) for r in rows], adapters=(), rank2=r2), questions)
    own = sum(label not in HONEST for _, _, label, _ in results)
    print('passport', json.dumps({'bank': a.bank, 'bank_sha256': bank_eval.sha(bank_eval.find(a.bank_dir, a.bank)), 'checker_sha256': bank_eval.sha(__file__),
                                  'rank2': a.rank2, 'n': len(results), 'of': len(questions), 'self_labelled': own}, ensure_ascii=False))
    print('from the source (counts for S2 acceptance):', '  '.join(f'{s} {n}' for s, n in tally(results, True).items()), '|', '; '.join(f'{s}: {t}' for s, t in STATES.items()))
    print('self-labelled (author own keys, NOT counted):', '  '.join(f'{s} {n}' for s, n in tally(results, False).items()))
    if a.show:
        for q, state, label, miss in results:
            if state != 'ok':
                print(f'  {state} [{label}] {q}' + (f'  (answer lacks {miss})' if miss else ''))


if __name__ == '__main__':
    main()
