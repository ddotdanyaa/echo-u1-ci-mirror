"""U21-S9: the offline semantic probe. A fake char-trigram encoder stands in for rubert-tiny2 (no model, no network, no onnxruntime); the probe never touches the engine."""
import json
import math
import subprocess
import sys
import zlib
from pathlib import Path

from tools import bank_semantic_probe as P

ROOT = Path(__file__).resolve().parents[1]
ROWS = [
    {'id': 'a1', 'q': 'что такое абсолютная ссылка', 'alt': ['как закрепить ячейку в формуле'], 'answer': 'Ссылка с долларами.', 'trust': 'Д'},
    {'id': 'a2', 'q': 'какая ставка налога на прибыль', 'alt': [], 'answer': 'Двадцать процентов.', 'trust': 'Д'},
    {'id': 'a3', 'q': 'какая ставка налога на добавленную стоимость', 'alt': [], 'answer': 'Двадцать процентов, но другой налог.', 'trust': 'Д'},
]


def fake_encode(texts):
    out = []
    for t in texts:
        v, s = [0.0] * 64, f' {t.lower()} '
        for i in range(len(s) - 2):
            v[zlib.crc32(s[i:i + 3].encode('utf-8')) % 64] += 1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        out.append([x / n for x in v])
    return out


def test_veto_needs_the_same_numbers_and_nots():
    assert P.veto_ok('ставка 20 процентов', 'ставка 20 процентов')
    assert not P.veto_ok('ставка 20 процентов', 'ставка 10 процентов')
    assert not P.veto_ok('это не облагается', 'это облагается')
    assert P.veto_ok('что такое ссылка', 'ссылка что такое')


def test_a_paraphrase_the_lexical_path_missed_is_a_rescue_and_nothing_is_wrong():
    tests = [{'q': 'как закрепить ячейку в формуле'}, {'q': 'как варить борщ'}]
    gold = {0: {'i': 0, 'gold': 'a1'}, 1: {'i': 1}}
    forms, owner = P.forms_of(ROWS)
    res = P.evaluate(fake_encode, ROWS, tests, gold, forms, owner, half='all', lexical={0: None, 1: None}, t=0.9, m=0.02)
    assert (res['right'], res['wrong'], res['neg_hit'], res['rescued']) == (1, 0, 0, 1)


def test_a_close_rival_with_another_answer_blocks_the_hit():
    forms, owner = P.forms_of(ROWS)
    res = P.evaluate(fake_encode, ROWS, [{'q': 'какая ставка налога'}], {0: {'i': 0}}, forms, owner, half='all', lexical={0: None}, t=0.5, m=0.3)
    assert res['wrong'] == 0 and res['neg_hit'] == 0


def test_the_grid_choice_is_made_on_dev_and_has_no_wrong():
    tests = [{'q': ROWS[0]['q']}, {'q': 'как закрепить ячейку в формуле'}, {'q': 'как варить борщ'}, {'q': 'какая ставка налога на прибыль'}]
    gold = {0: {'i': 0, 'gold': 'a1'}, 1: {'i': 1, 'gold': 'a1'}, 2: {'i': 2}, 3: {'i': 3, 'gold': 'a2'}}
    forms, owner = P.forms_of(ROWS)
    t, m, dev = P.tune(fake_encode, ROWS, tests, gold, forms, owner, lexical={})
    assert dev['wrong'] == 0 and dev['neg_hit'] == 0 and 0.5 <= t <= 1.0 and m >= 0.0


def test_the_verdict_is_a_gate_on_quantities():
    ok = {'wrong': 0, 'neg_hit': 0, 'rescued': P.GATE_MIN_RESCUE}
    assert P.verdict(ok, p95_ms=P.GATE_P95_MS)[0] == 'PASS'
    v, why = P.verdict({**ok, 'wrong': 1}, p95_ms=1.0)
    assert v == 'FAIL' and 'wrong' in ' '.join(why)
    assert P.verdict({**ok, 'rescued': P.GATE_MIN_RESCUE - 1}, p95_ms=1.0)[0] == 'FAIL'
    assert P.verdict(ok, p95_ms=P.GATE_P95_MS + 1)[0] == 'FAIL'
    assert P.verdict(None, p95_ms=None)[0] == 'NOT_MEASURED'


def test_cli_without_a_model_prints_not_measured_with_passport(tmp_path):
    (tmp_path / 'b.json').write_text(json.dumps(ROWS), encoding='utf-8')
    (tmp_path / '16_BANK_TEST.json').write_text(json.dumps([{'q': ROWS[0]['q'], 'answerable': True}]), encoding='utf-8')
    (tmp_path / 'gold.json').write_text(json.dumps([{'i': 0, 'gold': 'a1'}]), encoding='utf-8')
    lex = tmp_path / 'lex.json'
    lex.write_text(json.dumps({'0': None}), encoding='utf-8')
    r = subprocess.run([sys.executable, '-m', 'tools.bank_semantic_probe', '--bank-dir', str(tmp_path), '--bank', 'b.json', '--model-dir',
                        str(tmp_path / 'no_model'), '--lexical', str(lex)], cwd=ROOT, capture_output=True, text=True, encoding='utf-8')
    assert r.returncode == 0, r.stderr
    assert 'verdict NOT_MEASURED' in r.stdout and 'passport' in r.stdout and 'model_missing' in r.stdout
