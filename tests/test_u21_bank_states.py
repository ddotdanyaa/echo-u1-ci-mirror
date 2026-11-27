"""U21-S2: five states of a lost question, the key facts check, the labels of the questions file. Synthetic bank for the states; the 68 rows of the owner's files when they are there."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from echo_sync import instant
from tools import bank_states as bs

ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT.parents[1] / 'МАТЕРИАЛЫ' / 'БАНК' / 'eval'
BANK10 = EVAL.parent / 'instant_bank_10.json'
ROWS = [{'id': 'a1', 'q': 'что такое абсолютная ссылка', 'alt': [], 'answer': 'Ссылка, которая не меняется при копировании формулы.', 'trust': 'Д'},
        {'id': 'a2', 'q': 'что такое относительная ссылка', 'alt': [], 'answer': 'Ссылка, которая сдвигается при копировании формулы.', 'trust': 'Д'}]


def test_every_state_is_reachable():
    got = {bs.classify(in_bank=False),                                          # S0
           bs.classify(in_bank=True),                                           # S1
           bs.classify(in_bank=True, hit=object(), hit_ok=False),               # S2
           bs.classify(in_bank=True, hit=object(), hit_ok=True, admitted=False),   # S3
           bs.classify(in_bank=True, hit=object(), hit_ok=True, admitted=True, spoken=False),   # S4
           bs.classify(in_bank=True, hit=object(), hit_ok=True)}                # not measured further: no failure
    assert got == {'S0', 'S1', 'S2', 'S3', 'S4', 'ok'}


def test_a_wrong_hit_is_s2_even_when_the_bank_has_no_right_answer():
    assert bs.classify(in_bank=False, hit=object(), hit_ok=False) == 'S2'


def test_completeness_names_the_missing_facts():
    got, miss = bs.completeness('Ссылка не меняется при копировании.', 'не меняется;формул')
    assert got == ['не меняется'] and miss == ['формул']
    assert bs.right('Ёлка 50,02 процента', '50,02') and not bs.right('x', '') and not bs.right('x', ' ; ')


def test_measure_reaches_s0_s1_ok_s2_on_a_synthetic_bank():
    ins = instant.Instant([dict(r) for r in ROWS], adapters=())
    qs = [('что такое абсолютная ссылка', 'не меняется', 'given'),            # right answer said
          ('что такое абсолютная ссылка', 'квантов', 'given'),                # no entry holds the key: S0 (but the hit is wrong too: S2)
          ('какой сегодня день недели у нас', 'не меняется', 'given'),        # in the bank, nothing heard: S1
          ('что такое абсолютная ссылка', 'сдвигается', 'self-labelled'),     # the other entry's fact: the hit is wrong
          ('что-то без ключа', '', 'unlabelled')]
    res = bs.measure(ROWS, ins, qs)
    assert [r[1] for r in res] == ['ok', 'S2', 'S1', 'S2'] and bs.tally(res)['S2'] == 2 and res[1][3] == ['квантов']
    assert bs.measure(ROWS, ins, [('какой сегодня день недели у нас', 'квантов', 'given')])[0][1] == 'S0'


def test_read_rows_keeps_the_label_and_leaves_the_keyless_row_unlabelled(tmp_path):
    f = tmp_path / 'q.tsv'
    f.write_text('Что такое А\tаа\nЧто такое Б\tбб\tself-labelled\nЧто такое В\nЧто такое Г\tгг\tsheet\n', encoding='utf-8')
    assert bs.read_rows(f) == [('Что такое А', 'аа', 'given'), ('Что такое Б', 'бб', 'self-labelled'), ('Что такое В', '', 'unlabelled'), ('Что такое Г', 'гг', 'sheet')]


@pytest.mark.skipif(not (BANK10.exists() and (EVAL / 'sheet_questions.tsv').exists()), reason='the owner materials are not here')
def test_the_sheet_file_has_no_row_left_without_a_key_and_names_its_own_labels():
    rows = bs.read_rows(EVAL / 'sheet_questions.tsv')
    assert len(rows) == 33 and not [r for r in rows if r[2] == 'unlabelled']
    assert {r[2] for r in rows} <= {'given', 'sheet', 'textbook', 'self-labelled'} and any(r[2] == 'self-labelled' for r in rows)


@pytest.mark.skipif(not (BANK10.exists() and (EVAL / 'sheet_questions.tsv').exists()), reason='the owner materials are not here')
def test_on_the_68_rows_s1_is_6_and_s2_is_0():
    rows = [r for r in (instant.clean_entry(x) for x in json.load(open(BANK10, encoding='utf-8'))) if r]
    qs = bs.read_rows(EVAL / 'sheet_questions.tsv') + bs.read_rows(EVAL / 'real_questions.tsv')
    res = bs.measure(rows, instant.Instant([dict(r) for r in rows], adapters=()), qs)
    count, honest = bs.tally(res), bs.tally(res, True)
    assert len(res) == 68 and count['S1'] == 6 and count['S2'] == 0 and count['S0'] == 0, count
    assert honest['S2'] == 0 and sum(honest.values()) < 68, honest      # S2 acceptance rests on the source-labelled rows only


def test_cli_prints_the_passport_and_the_counts(tmp_path):
    (tmp_path / 'b.json').write_text(json.dumps(ROWS), encoding='utf-8')
    (tmp_path / 'q.tsv').write_text('что такое абсолютная ссылка\tне меняется\n', encoding='utf-8')
    out = subprocess.run([sys.executable, '-m', 'tools.bank_states', '--bank-dir', str(tmp_path), '--bank', 'b.json', '--questions', str(tmp_path / 'q.tsv')],
                         cwd=ROOT, capture_output=True, text=True, encoding='utf-8', timeout=120)
    assert out.returncode == 0, out.stderr
    assert 'passport' in out.stdout and 'ok 1' in out.stdout


def test_a_topic_word_in_the_question_does_not_make_a_wrong_hit_right():
    rows = [{'id': 'a1', 'q': 'что такое денежные средства', 'alt': [], 'answer': 'Ресурсы организации.', 'trust': 'Д'}]
    ins = instant.Instant([dict(r) for r in rows], adapters=())
    res = bs.measure(rows, ins, [('что такое денежные средства', 'денежн', 'self-labelled')])
    assert res[0][1] in ('S0', 'S2') and not bs.right('Ресурсы организации.', 'денежн')


def test_tally_splits_source_labels_from_self_labels():
    res = [('q', 'ok', 'sheet', []), ('q', 'S2', 'self-labelled', []), ('q', 'S1', 'given', [])]
    assert bs.tally(res, True)['S2'] == 0 and bs.tally(res, False)['S2'] == 1 and bs.tally(res)['S2'] == 1


@pytest.mark.skipif(not (EVAL / 'sheet_questions.tsv').exists(), reason='the owner materials are not here')
def test_labels_are_kept_under_git_beside_the_code():
    kept = ROOT / 'tools' / 'data' / 'sheet_questions.labels.tsv'
    assert kept.exists() and bs.read_rows(kept) == bs.read_rows(EVAL / 'sheet_questions.tsv')
