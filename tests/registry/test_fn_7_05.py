"""Реестр 7.05 «Ворота выкладки и откат»: часть, что лежит в репозитории: (1) резервная копия профиля перед выкладкой и откат одной командой
(tools/profile_backup, команды backup|restore); (2) «сборка без полного прогона не уходит», N183: tools/gate/run_gate.py отдаёт код возврата по итогу набора.
Ядро выкладки (замок suite_ok, постпроверка, переключение профиля) вне репозитория и здесь не доказывается."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
QA_OLD = '[{"question":"вопрос про погоду","answer":"ответ про зонт"}]'


def run(*args):
    return subprocess.run([sys.executable, '-m', 'tools.profile_backup', *map(str, args)], cwd=ROOT, capture_output=True, text=True, timeout=30)


def make_profile(tmp_path):
    p = tmp_path / 'profile'
    (p / 'materials').mkdir(parents=True)
    (p / 'materials' / 'qa.json').write_text(QA_OLD, encoding='utf-8')
    (p / 'materials' / 'echo_settings.json').write_text('{"preset":"a"}', encoding='utf-8')
    (p / 'logs').mkdir()
    (p / 'logs' / 'big.jsonl').write_text('x' * 50, encoding='utf-8')
    (p / 'auth.json').write_text('{"token":"not-real"}', encoding='utf-8')
    return p


def test_backup_edit_restore_roundtrip_one_command_each(tmp_path):
    prof, bk = make_profile(tmp_path), tmp_path / 'bk'
    done = run('backup', prof, bk)
    assert done.returncode == 0, done.stderr
    dest = Path(done.stdout.strip())
    assert dest.parent == bk and (dest / 'manifest.json').is_file()
    manifest = json.loads((dest / 'manifest.json').read_text(encoding='utf-8'))
    assert 'materials/qa.json' in manifest and 'materials/echo_settings.json' in manifest
    assert not any('auth' in k or 'logs' in k for k in manifest)
    assert not any('auth' in f.name for f in dest.rglob('*'))

    qa = prof / 'materials' / 'qa.json'
    qa.write_text('[]', encoding='utf-8')
    back = run('restore', prof, bk)
    assert back.returncode == 0, back.stderr
    assert 'materials/qa.json' in back.stdout
    assert qa.read_text(encoding='utf-8') == QA_OLD
    kept = prof / 'materials' / 'qa.json.before-restore'
    assert kept.read_text(encoding='utf-8') == '[]'
    assert not (prof / 'materials' / 'echo_settings.json.before-restore').exists()
    assert (prof / 'auth.json').read_text(encoding='utf-8') == '{"token":"not-real"}'


def test_restore_refuses_when_manifest_does_not_match_and_writes_nothing(tmp_path):
    prof, bk = make_profile(tmp_path), tmp_path / 'bk'
    dest = Path(run('backup', prof, bk).stdout.strip())
    (dest / 'materials' / 'qa.json').write_text('подмена', encoding='utf-8')
    (prof / 'materials' / 'echo_settings.json').write_text('{"preset":"new"}', encoding='utf-8')
    (prof / 'materials' / 'qa.json').write_text('[]', encoding='utf-8')
    back = run('restore', prof, bk)
    assert back.returncode != 0
    assert 'damaged' in back.stderr
    assert (prof / 'materials' / 'echo_settings.json').read_text(encoding='utf-8') == '{"preset":"new"}'
    assert (prof / 'materials' / 'qa.json').read_text(encoding='utf-8') == '[]'
    assert not list(prof.rglob('*.before-restore'))


def test_restore_without_any_backup_fails_and_changes_nothing(tmp_path):
    prof = make_profile(tmp_path)
    back = run('restore', prof, tmp_path / 'empty')
    assert back.returncode != 0 and 'no backup' in back.stderr
    assert (prof / 'materials' / 'qa.json').read_text(encoding='utf-8') == QA_OLD


def gate(tmp_path, source):
    """Настоящий инструмент ворот на крошечном наборе во временной папке: код возврата и итоговая json-строка."""
    suite = tmp_path / 'suite'
    suite.mkdir()
    (suite / 'test_tiny.py').write_text(source, encoding='utf-8')
    done = subprocess.run([sys.executable, str(ROOT / 'tools/gate/run_gate.py'), '--lock', str(tmp_path / 'slot.lock'), '--', str(suite)],
                          cwd=tmp_path, capture_output=True, text=True, timeout=60)
    return done.returncode, json.loads(done.stdout.strip().splitlines()[-1])


def test_gate_exits_zero_only_for_a_fully_green_suite(tmp_path):
    code, summary = gate(tmp_path, 'def test_a():\n    assert 1\n\n\ndef test_b():\n    assert 2\n')
    assert code == 0 and summary['verdict'] == 'green' and summary['passed'] == 2


def test_gate_exits_nonzero_when_one_test_is_red(tmp_path):
    code, summary = gate(tmp_path, 'def test_a():\n    assert 1\n\n\ndef test_b():\n    assert 0\n')
    assert code != 0 and summary['verdict'] == 'red' and summary['failed'] == 1 and summary['passed'] == 1


def test_gate_exits_nonzero_on_xpass_even_when_pytest_itself_is_green(tmp_path):
    src = 'import pytest\n\n\n@pytest.mark.xfail(reason="x")\ndef test_a():\n    assert 1\n'
    code, summary = gate(tmp_path, src)
    assert summary['pytest_code'] == 0 and summary['xpassed'] == 1
    assert code != 0 and summary['verdict'] == 'red'


def test_gate_exits_nonzero_on_strict_xpass(tmp_path):
    code, summary = gate(tmp_path, 'import pytest\n\n\n@pytest.mark.xfail(strict=True, reason="x")\ndef test_a():\n    assert 1\n')
    assert code != 0 and summary['verdict'] == 'red' and summary['failed'] == 1


def test_gate_exits_nonzero_when_nothing_is_collected(tmp_path):
    code, summary = gate(tmp_path, 'VALUE = 1\n')
    assert code != 0 and summary['verdict'] == 'red' and summary['passed'] == 0
