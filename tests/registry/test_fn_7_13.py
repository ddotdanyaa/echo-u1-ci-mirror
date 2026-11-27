"""Реестр 7.13: отпечаток сборки в журнале звонка.

Настоящий controlled_host.serve принимает звонок (подставные телефон, облачный помощник и SAPI на виртуальном времени, HostRig).
Смотрим на то, что владелец читает потом: строку call_open журнала <home>/logs/echo_calls/*.jsonl. В ней должны быть названы
сборка (build), код процесса (code) и отпечаток настроек звонка (flags), причём отпечаток настроек зависит от настроек.
"""
import json
import re
import subprocess
from pathlib import Path

import helpers_s6_fault as F

REPO = Path(__file__).resolve().parents[2]


def settings_file(home, **values):
    folder = Path(home) / 'materials'
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'echo_settings.json').write_text(json.dumps(values), encoding='utf-8')


def call_header(tmp_path, monkeypatch, name, **settings):
    """Один звонок с заданными настройками профиля; возвращает строку call_open его журнала и все строки."""
    out = {}

    async def main():
        F.patch_clock(monkeypatch)
        async with F.HostRig(tmp_path / name, monkeypatch) as host:
            settings_file(host.home, **settings)
            await host.handshake()
            files = sorted((f for f in (host.home / 'logs' / 'echo_calls').glob('*.jsonl') if '.v5tap' not in f.name))
            assert len(files) == 1, files
            rows = [json.loads(line) for line in files[0].read_text(encoding='utf-8').splitlines()]
            out['rows'] = rows
    F.run(main)
    assert out['rows'] and out['rows'][0]['ev'] == 'call_open', 'журнал звонка не начался со строки call_open'
    return out['rows'][0]


def test_call_open_names_build_code_and_settings_fingerprint(tmp_path, monkeypatch):
    head = call_header(tmp_path, monkeypatch, 'a', repeat_seconds=4)
    assert head['source'] == 'phone'
    # сборка названа: не пусто и не «неизвестно» (в проверяемой копии она берётся из коммита или файла BUILD)
    build = head.get('build')
    assert isinstance(build, str) and build.strip() and build != 'unknown', head.get('build')
    head_commit = subprocess.run(['git', '-C', str(REPO), 'rev-parse', '--short=12', 'HEAD'], capture_output=True, text=True).stdout.strip()
    if head_commit and not (REPO / 'echo_sync' / 'BUILD').exists():
        assert build == head_commit
    # код процесса и отпечаток настроек названы короткими шестнадцатеричными отпечатками
    assert re.fullmatch(r'[0-9a-f]{12}', str(head.get('code'))), head.get('code')
    assert re.fullmatch(r'[0-9a-f]{12}', str(head.get('flags'))), head.get('flags')


def test_settings_fingerprint_follows_the_settings_and_build_stays(tmp_path, monkeypatch):
    first = call_header(tmp_path, monkeypatch, 'a', repeat_seconds=4)
    same = call_header(tmp_path, monkeypatch, 'b', repeat_seconds=4)
    other = call_header(tmp_path, monkeypatch, 'c', repeat_seconds=7, max_auto_repeats=1)
    # те же настройки дают тот же отпечаток настроек, другие настройки дают другой
    assert first['flags'] and first['flags'] == same['flags']
    assert other['flags'] and other['flags'] != first['flags']
    # сборка в одном процессе не меняется от настроек (общий отпечаток code включает и настройки, его не сравниваем)
    assert first['build'] == same['build'] == other['build'] and first['build']
