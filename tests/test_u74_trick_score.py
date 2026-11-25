"""U74: the trick set with independent labels (tools/trick_set.json) and its scorer (tools/trick_score.py): «issued» and «correct» are two numbers per road, each with a 95% Wilson interval, and the answers that broke a
condition of the question are counted. Synthetic answers only: a measurement on the roads is the laptop's (no road is called here)."""
import json
from collections import Counter

import pytest

from tools import trick_score as T

SET = T.load_set()
BY = {q['id']: q for q in SET['questions']}


def rows(road, texts):
    return [{'id': i, 'road': road, 'text': t} for i, t in texts.items()]


def test_the_set_is_large_labelled_and_covers_the_conditions():
    qs = SET['questions']
    assert len(qs) >= 30 and len({q['id'] for q in qs}) == len(qs)
    assert {'false_premise', 'units', 'period', 'negation', 'reasoning'} <= {q['kind'] for q in qs}
    assert all(q['labelled_by'] and q['rules'] and q['gold'] and q['wrong'] for q in qs)
    assert SET['labelled_by'] and 'not the answering model' in SET['labelled_by']
    assert all(set(q['rules']) <= T.RULES for q in qs)


@pytest.mark.parametrize('qid', sorted(BY))
def test_the_rules_tell_the_gold_from_the_wrong_sample(qid):
    q = BY[qid]
    assert T.judge(q, q['gold']) == [], (qid, T.judge(q, q['gold']))
    assert T.judge(q, q['wrong']) != [], qid


def test_a_number_without_its_unit_breaks_the_condition():
    q = BY['u01']
    assert T.judge(q, 'Около 300 тысяч.') == ['units']
    assert T.judge(q, 'Около 300 тысяч километров в секунду.') == []


def test_a_false_premise_taken_is_a_broken_condition():
    assert T.judge(BY['fp02'], 'В 1815 году.') == ['premise']
    assert T.judge(BY['fp06'], 'Это написал Толстой, не Пушкин.') == []


def test_a_number_is_a_whole_number():
    assert T.judge(BY['r02'], 'За 360 минут.') != []      # «3» is not in «360»
    assert T.judge(BY['u02'], 'В часе 3 600 секунд.') == []      # a thousands space is no break


def test_wilson_interval():
    lo, hi = T.wilson(0, 0)
    assert (lo, hi) == (0.0, 0.0)
    lo, hi = T.wilson(5, 10)
    assert round(lo, 3) == 0.237 and round(hi, 3) == 0.763
    lo, hi = T.wilson(10, 10)
    assert hi == 1.0 and 0.72 < lo < 0.73


def test_issued_and_correct_are_counted_apart_per_road():
    ids = list(BY)
    good = {i: BY[i]['gold'] for i in ids}
    bad = {i: BY[i]['wrong'] for i in ids}
    half = {i: (BY[i]['gold'] if n % 2 else BY[i]['wrong']) for n, i in enumerate(ids)}
    silent = {i: ('—' if n % 2 else 'Точно не знаю.') for n, i in enumerate(ids)}
    got = T.score(rows('a', good) + rows('b', bad) + rows('c', half) + rows('d', silent), SET)
    assert got['a']['issued'] == got['a']['asked'] == len(ids) and got['a']['correct'] == len(ids)
    assert got['b']['issued'] == len(ids) and got['b']['correct'] == 0
    assert got['c']['issued'] == len(ids) and 0 < got['c']['correct'] < len(ids)
    assert got['d']['issued'] == 0 and got['d']['correct'] == 0      # a dash and an honest «не знаю» are no answer issued
    for road in got.values():
        assert 0 <= road['issued_ci'][0] <= road['issued_ci'][1] <= 1 and 0 <= road['correct_ci'][0] <= road['correct_ci'][1] <= 1
    assert got['a']['issued_ci'][1] == 1.0 and got['b']['correct_ci'][0] == 0.0


def test_a_missing_answer_is_asked_but_not_issued():
    got = T.score(rows('a', {'u01': BY['u01']['gold']}), SET)
    assert got['a']['asked'] == len(BY) and got['a']['issued'] == 1 and got['a']['correct'] == 1 and got['a']['missing'] == len(BY) - 1


def test_the_answers_that_broke_a_condition_are_counted_by_the_condition():
    answers = {'u01': 'Около 300 тысяч.', 'fp02': 'В 1815 году.', 'fp01': 'Потому что теория важная.', 'p01': 'Джордж Буш.', 'r01': 'Восемь яблок.', 'n06': 'Москва.'}
    got = T.score(rows('a', answers), SET)['a']
    assert got['broke'] == 5 and got['wrong_other'] == 1 and got['correct'] == 0
    assert got['broke_by'] == Counter({'units': 1, 'premise': 2, 'period': 1, 'negation': 1})


def test_an_answer_for_an_unknown_id_is_set_aside_and_the_last_of_an_id_counts():
    got = T.score(rows('a', {'zz': 'x'}) + rows('a', {'u01': 'Около 300 тысяч.'}) + rows('a', {'u01': BY['u01']['gold']}), SET)['a']
    assert got['unknown'] == 1 and got['duplicates'] == 1 and got['issued'] == 1 and got['correct'] == 1


def test_the_cli_prints_two_numbers_per_road(tmp_path, capsys):
    path = tmp_path / 'a.jsonl'
    path.write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in rows('fast', {'u01': BY['u01']['gold']}) + rows('cloud', {'u01': 'Около 300 тысяч.'})) + '\n', encoding='utf-8')
    assert T.main([str(path)]) == 0
    out = capsys.readouterr().out
    assert 'fast' in out and 'cloud' in out and 'issued' in out and 'correct' in out and '95%' in out and 'laptop' in out
