"""U21-S7: the bank content audit. Synthetic rows for each check; the owner's bank 10 (pair 50,01 / 50,02) and bank 11 (after the rebuild) when they are there."""
import json
from pathlib import Path

import pytest

from echo_sync import instant
from tools import bank_audit as ba
from tools import bank_states as bs

ROOT = Path(__file__).resolve().parents[1]
BANKDIR = ROOT.parents[1] / 'МАТЕРИАЛЫ' / 'БАНК'
EVAL = BANKDIR / 'eval'
SRC = 'Контрольная работа 2'


def row(i, q, a, src=SRC, alt=()):
    return {'id': i, 'q': q, 'alt': list(alt), 'answer': a, 'source': src, 'trust': 'М'}


def test_a_number_pair_of_one_source_is_a_conflict_and_other_sources_are_not():
    rows = [row('a', 'доля раз', 'ОФЗ 50,02%.'), row('b', 'доля два', 'ОФЗ 50,01 процента.'), row('c', 'доля три', 'ОФЗ 50,01.', src='другой лист')]
    got = ba.number_conflicts(rows)
    assert len(got) == 1 and (got[0][0], got[0][1]) == ('50,01', '50,02')
    assert got[0][2] == ['b'] and got[0][3] == ['a']
    assert ba.number_conflicts([row('a', 'x', 'ставка 7,25.'), row('b', 'y', 'ставка 19,50.')]) == []


def test_alt_drift_finds_one_question_held_by_two_answers():
    rows = [row('a', 'что такое пеня', 'Неустойка за просрочку.'), row('b', 'что такое штраф', 'Разовая санкция.', alt=['Что такое пеня?'])]
    assert ba.alt_drift(rows) == [('что такое пеня', ['a', 'b'])]
    assert ba.alt_drift([row('a', 'q один', 'ответ'), row('b', 'q один', 'ответ')]) == []


def test_first_portion_unit_source_and_volatile_checks():
    long_first = ' '.join(['слово'] * (ba.FIRST_WORDS + 1)) + '. Конец.'
    assert ba.first_portion([row('a', 'q', long_first), row('b', 'q2', 'Коротко. Ещё.')]) == [('a', ba.FIRST_WORDS + 1)]
    assert ba.unit_gaps([row('a', 'Сколько платить', 'Платить 120.'), row('b', 'Сколько платить ещё', 'Платить 120 рублей.'), row('c', 'Что такое НДС', 'Налог 20.')]) == ['a']
    assert ba.no_source([row('a', 'q', 'a', src=''), row('b', 'q', 'a')]) == ['a']
    assert ba.volatile([row('a', 'q', 'Сейчас ставка выше.'), row('b', 'q', 'Сейчас, в 2024 году, ставка выше.')]) == ['a']


def test_resolve_sets_the_number_right_from_the_table_and_touches_nothing_else():
    rows = [row('a', 'доля раз', 'ОФЗ 50,02%.'), row('b', 'доля два', 'ОФЗ 50,01 процента, было 59,11.'), row('c', 'вне', 'Цена 50,01 рубля.', src='другой лист')]
    fixed, changed = ba.resolve(rows, {'50,01': '50,02'})
    assert changed == ['b'] and fixed[1]['answer'] == 'ОФЗ 50,02 процента, было 59,11.' and fixed[2] == rows[2] and fixed[0] == rows[0]
    assert ba.number_conflicts(fixed) == []


def test_the_resolution_table_names_the_pair_with_its_basis():
    assert ba.read_resolutions() == {'50,01': '50,02'}
    assert '50,0152' in ba.RESOLUTIONS.read_text(encoding='utf-8')


@pytest.mark.skipif(not (BANKDIR / 'instant_bank_10.json').exists(), reason='the owner materials are not here')
def test_the_audit_lists_the_50_01_50_02_pair_in_bank_10():
    data = json.loads((BANKDIR / 'instant_bank_10.json').read_text(encoding='utf-8'))
    pairs = [(a, b) for a, b, *_ in ba.number_conflicts(data)]
    assert ('50,01', '50,02') in pairs


@pytest.mark.skipif(not (BANKDIR / 'instant_bank_11.json').exists(), reason='bank 11 is not built here')
def test_bank_11_has_no_number_conflict_and_the_68_set_wrong_count_stays_0():
    data = json.loads((BANKDIR / 'instant_bank_11.json').read_text(encoding='utf-8'))
    assert not [c for c in ba.number_conflicts(data) if c[0] == '50,01']
    rows = [r for r in (instant.clean_entry(x) for x in data) if r]
    qs = bs.read_rows(EVAL / 'sheet_questions.tsv') + bs.read_rows(EVAL / 'real_questions.tsv')
    res = bs.measure(rows, instant.Instant([dict(r) for r in rows], adapters=()), qs)
    count = bs.tally(res)
    assert len(res) == 68 and count['S2'] == 0 and count['S0'] == 0, count
