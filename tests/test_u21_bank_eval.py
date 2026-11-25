"""U21-S1: the bank harness takes its bank from ``--bank-dir`` / ``--bank`` instead of a hard-coded path, and prints a passport with the baseline. Tiny synthetic bank; no network."""
import json
import subprocess
import sys
from pathlib import Path

from tools import bank_eval, c24_lab

ROOT = Path(__file__).resolve().parents[1]
ROW = {'id': 'a1', 'q': 'что такое абсолютная ссылка', 'answer': 'Ссылка, которая не меняется при копировании формулы.', 'trust': 'Д'}


def make(tmp_path):
    (tmp_path / 'b.json').write_text(json.dumps([ROW]), encoding='utf-8')
    (tmp_path / '16_BANK_TEST.json').write_text(json.dumps([{'q': ROW['q'], 'answerable': True}, {'q': 'какая сегодня погода', 'answerable': False}]), encoding='utf-8')
    (tmp_path / 'gold.json').write_text(json.dumps([{'i': 0, 'gold': 'a1'}, {'i': 1}]), encoding='utf-8')
    return tmp_path


def test_load_reads_the_given_dir_and_bank(tmp_path):
    rows, tests, gold = bank_eval.load(make(tmp_path), 'b.json')
    assert [r['id'] for r in rows] == ['a1'] and len(tests) == 2 and set(gold) == {0, 1}


def test_a_file_in_the_eval_subdir_is_found(tmp_path):
    make(tmp_path)
    (tmp_path / 'eval').mkdir()
    (tmp_path / 'gold.json').replace(tmp_path / 'eval' / 'gold.json')
    assert bank_eval.load(tmp_path, 'b.json')[2][0]['gold'] == 'a1'


def test_the_passport_names_what_was_measured(tmp_path):
    make(tmp_path)
    p = bank_eval.passport(tmp_path, 'b.json', 'test', 1, 2)
    assert p['n'] == 1 and p['of'] == 2 and p['half'] == 'test' and p['bank'] == 'b.json'
    assert len(p['bank_sha256']) == 64 and len(p['gold_sha256']) == 64 and len(p['checker_sha256']) == 64


def test_cli_full_prints_a_baseline_with_passport(tmp_path):
    make(tmp_path)
    out = subprocess.run([sys.executable, '-m', 'tools.bank_eval', '--full', '--half', 'all', '--bank-dir', str(tmp_path), '--bank', 'b.json'],
                         cwd=ROOT, capture_output=True, text=True, encoding='utf-8', timeout=120)
    assert out.returncode == 0, out.stderr
    assert 'passport' in out.stdout and 'right 1/1' in out.stdout


def test_c24_lab_load_takes_the_dir(tmp_path):
    make(tmp_path)
    (tmp_path / 'g24.json').write_text('[]', encoding='utf-8')
    rows, gold = c24_lab.load('b.json', 'g24.json', tmp_path)
    assert len(rows) == 1 and gold == []
