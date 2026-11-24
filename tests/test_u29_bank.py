"""U29: the bank supplement ``tools/data/bank_u29.json`` closes the gaps of the photo run (rates, понятые, выемка, ... and the accounting chain): every row is clean, no question
has two answers, the gap questions are answered through the real matcher with the expected fact, and the accounting facts hold by computation."""
import json
import re
from pathlib import Path

from echo_sync import instant
from tools import bank_u29_coverage as cov, build_instant_bank

DATA = Path(__file__).resolve().parents[1] / 'tools' / 'data'
RAW = json.loads((DATA / 'bank_u29.json').read_text(encoding='utf-8'))
ROWS = instant.load_bank(DATA / 'bank_u29.json')
QUESTIONS = cov.read_questions(DATA / 'bank_u29_questions.tsv')


def _key(text):
    return ' '.join(text.casefold().replace('?', ' ').split())


def test_every_row_passes_clean_entry():
    assert len(RAW) >= 30 and len(ROWS) == len(RAW)
    for r in RAW:
        c = instant.clean_entry(r)
        assert c is not None, r['q']
        assert c['source'] and c['subject'] in ('налоги', 'бухучёт') and c['trust'] in instant.TRUST and c['alt'], r['q']
        assert len(c['answer'].split()) <= 60, r['q']


def test_no_question_has_two_answers():
    seen = {}
    for r in ROWS:
        for text in [r['q']] + r['alt']:
            assert seen.setdefault(_key(text), r['answer']) == r['answer'], text
    rows, counts = build_instant_bank.build([DATA / 'bank_u29.json'])
    assert counts['dropped_conflicts'] == 0 and counts['rows'] == len(ROWS) and counts['not_self_found'] == 0, counts


def test_gap_questions_are_all_answered_with_the_fact():
    assert len(QUESTIONS) >= 11
    for rank2 in (False, True):
        got = cov.coverage(ROWS, QUESTIONS, rank2)
        assert got['coverage'] == 1.0, got['missed']


def test_the_state_duty_row_holds_no_amount():
    duty = [r for r in ROWS if 'пошлин' in r['q'].casefold()]
    assert duty and not any(re.search(r'\d', re.sub(r'(?:пункт\w*|стать\w+|глав\w+)\s+[\d.]+', '', r['answer'])) for r in duty)      # an article is no amount


# --- the accounting chain by computation: the same sample the rows speak of ---
POSTINGS = [('51', '80', 100000), ('08', '60', 40000), ('01', '08', 40000), ('10', '60', 30000), ('20', '10', 20000), ('43', '20', 20000),
            ('62', '90.1', 36000), ('90.2', '43', 15000), ('90.3', '68', 6000)]
ACTIVE = {'01', '08', '10', '20', '43', '51', '62'}


def test_posting_set_debit_equals_credit_and_balance_identity():
    osv = {}
    for d, k, s in POSTINGS:
        osv.setdefault(d, [0, 0])[0] += s
        osv.setdefault(k, [0, 0])[1] += s
    assert sum(v[0] for v in osv.values()) == sum(v[1] for v in osv.values())      # the check of the ОСВ the rows speak of
    assets = sum(v[0] - v[1] for a, v in osv.items() if a in ACTIVE)
    capital_and_debts = sum(v[1] - v[0] for a, v in osv.items() if a in ('80', '60', '68'))
    profit = osv['90.1'][1] - osv['90.2'][0] - osv['90.3'][0]                         # the ОФР: revenue less cost less tax
    assert (assets, profit) == (191000, 15000) and assets == capital_and_debts + profit      # актив = капитал + обязательства


def test_chain_row_names_every_step_in_order():
    by_q = {_key(r['q']): r for r in ROWS}
    chain = by_q[_key('Как от проводки дойти до баланса и отчёта о финансовых результатах')]['answer'].casefold()
    pos = [chain.find(s) for s in ('проводк', 'карточк', 'главн', 'оборотно-сальдов', 'баланс', 'финансов')]
    assert -1 not in pos and pos == sorted(pos), pos
