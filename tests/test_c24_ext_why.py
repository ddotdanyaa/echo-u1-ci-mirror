"""C24-d: ``cloud_context/bank/ext_why_c24.json`` — «почему/зачем» candidates, each made only of what verified bank rows already say. Not merged into the bank (the owner's call)."""
import json
from pathlib import Path

import pytest

from echo_sync import instant

BANK = Path(__file__).resolve().parents[1] / 'cloud_context' / 'bank'
B7 = {e['id']: e for e in json.load(open(BANK / 'instant_bank_7.json', encoding='utf-8'))}
EXT = json.load(open(BANK / 'ext_why_c24.json', encoding='utf-8'))


def test_every_row_is_marked_a_candidate_and_names_its_source():
    assert len({r['id'] for r in EXT}) == len(EXT) and not {r['id'] for r in EXT} & set(B7)
    for r in EXT:
        assert r['status'] == 'candidate' and r['from'] and r['derivation'] in ('quote', 'arithmetic')
        assert instant.clean_entry(r), r['id']
        assert instant.qtype2(r['q']) == 'why', r['q']


def test_every_quote_is_in_the_bank_row_it_names():
    for r in EXT:
        text = ' '.join(B7[i]['answer'] for i in r['from'])
        assert all(part in text for part in r['quote']), r['id']


def test_no_row_adds_a_number_or_a_name_the_sources_do_not_have():
    for r in EXT:
        text = ' '.join(B7[i]['answer'] + ' ' + B7[i]['q'] for i in r['from']).casefold().replace('ё', 'е')
        for w in instant._terms(r['answer'])[0]:
            if w[0].isdigit():
                assert w in text, (r['id'], w)
        assert not instant._terms(r['answer'])[1] or all(n.lstrip('#') in text for n in instant._terms(r['answer'])[1]), r['id']


@pytest.fixture(scope='module')
def merged():
    return instant.Instant(list(B7.values()) + EXT, adapters=(), rank=True, rank2=True)


def _hit(ins, text):
    ins.reset()
    return ins.lookup(text, final=True, bank_only=True)


def test_each_new_why_is_answered_by_itself_and_the_old_questions_keep_their_answers(merged):
    for r in EXT:
        got = _hit(merged, r['q'])
        assert got and got.id == r['id'], (r['q'], got and got.id)
    for q, want in (('Что такое инфляция?', 'b01381'), ('Что значит принцип платности?', 'b01216'), ('Чем номинальная ставка отличается от реальной?', 'b01244'),
                    ('Что такое амортизация?', 'b00919'), ('Что такое индекс цен производителей?', 'b01398'), ('Что такое таргетирование инфляции?', 'b01395'),
                    ('Почему при аннуитете переплата больше?', 'b01560'), ('Что такое финансовый контроль по лекции?', 'b01427')):
        got = _hit(merged, q)
        assert got and got.id == want, (q, got and got.id)


def test_the_mortgage_question_is_not_answered_by_the_annuity_row(merged):
    annuity = next(r['id'] for r in EXT if 'аннуитет' in r['q'])
    got = _hit(merged, 'Почему в начале ипотеки почти всё уходит на проценты')
    assert got is None or got.id != annuity
    assert _hit(merged, 'Почему при аннуитетном платеже вначале почти всё уходит на проценты').id == annuity
