"""Реестр 8.02 «Запись входа (кольцо) в тени»: все входы контроллера за звонок пишутся в кольцо с пределом 48 МБ (основа точного повтора).

Настоящий controlled_host.serve с подставным телефоном и облаком (helpers_s6_fault.HostRig, виртуальное время). Смотрим только на файлы
logs/echo_calls/ профиля: журнал звонка (*.jsonl) и запись входов (*.v5tap*.jsonl). Ключи живые, как на сервере: файл
Ключа-выключателя нет: запись всегда включена, размер кольца v5_tap_mb=48 — умолчание кода. Читателя записи нет ни в единой, ни в боковых ветках, поэтому цели
«звонок повторяется по записи» в файле нет: контракт описан в notes записи registry_proof/8.02.json.
"""
import json
import logging
from pathlib import Path

from helpers_spoken_diagnostics import run_host

QUESTION = 'Почему небо голубое днём?'
ANSWER = 'Воздух сильнее рассеивает синий свет, поэтому небо кажется голубым.'
LIMIT_MB = 48


def rows_of(path):
    return [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines() if line.strip()]


def log_dir(home):
    return Path(home) / 'logs' / 'echo_calls'


def record_files(home):
    folder = log_dir(home)
    return sorted(folder.glob('*.v5tap*.jsonl')) if folder.is_dir() else []


def settings_file(home, **values):
    folder = Path(home) / 'materials'
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'echo_settings.json').write_text(json.dumps(values), encoding='utf-8')


def test_every_input_of_a_call_is_in_a_bounded_record(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger='echo-sync')      # решения контроллера попадают в журнал звонка через лог INFO, как на сервере
    async def body(host):
        await host.handshake()
        await host.ask(QUESTION, tid='u1')
        await host.answer(ANSWER, tid='a1')
        await host.advance(2)
        host.phone_audio(3)                                 # три пакета звука с телефона
        await host.advance(1)

        # опоры: звонок отработал, подсказка произнесена, журнал звонка на месте
        assert host.spoken(), 'подсказка не опубликована: звонок не отработал'
        journal = [p for p in log_dir(host.home).glob('*.jsonl') if '.v5tap' not in p.name]
        assert len(journal) == 1
        jrows = rows_of(journal[0])
        assert any(r['ev'] == 'user_final' and r['text'] == QUESTION for r in jrows)
        assert any(r['ev'] == 'decision' for r in jrows)

        # функция: рядом с журналом лежит запись входов этого звонка
        files = record_files(host.home)
        assert files, 'записи входов нет'
        rows = [r for f in files for r in rows_of(f)]
        inputs = [r for r in rows if r['source'].endswith('tap_in')]
        effects = [r for r in rows if r['source'].endswith('tap_out')]
        entries = [r['payload']['flags']['entry'] for r in inputs]
        # все входы звонка: начало, ход часов, ответ облака, речь человека, подсказка и каждый из трёх пакетов звука
        for name in ('begin_call', 'tick', 'provider', 'speech_started', 'cue_started'):
            assert name in entries, f'вход {name} не записан: {sorted(set(entries))}'
        assert entries.count('mic_packet') == 3, 'не все пакеты звука с телефона записаны'
        assert entries[0] == 'begin_call', 'порядок входов не сохранён: звонок начинается не с begin_call'
        # реплика человека и ответ облака видны во входах; произнесённое видно в действиях контроллера
        text_in = json.dumps([r['payload'] for r in inputs], ensure_ascii=False)
        assert QUESTION[:15] in text_in or 'небо' in text_in, 'реплика человека не попала во входы'
        assert effects, 'действий, которые вернул контроллер, в записи нет'
        text_out = json.dumps([r['payload'] for r in effects], ensure_ascii=False)
        assert host.spoken()[0].split()[0] in text_out, 'произнесённое не попало в записанные действия'
        # записи упорядочены и связаны: у действия есть причина (запись входа, который его вернул), номера не повторяются
        ids = [r['id'] for r in rows]
        assert len(ids) == len(set(ids)) and ids == sorted(ids)
        input_ids = {r['id'] for r in inputs}
        assert all(r['causes'] and set(r['causes']) <= input_ids for r in effects), 'у действия нет причины среди записанных входов'
        # предел: кольцо объявлено не больше 48 МБ (две половины) и файлы в него укладываются
        header = [r['payload']['flags'] for r in rows if r['payload']['flags'].get('tap') == 'open']
        assert len(header) == 1 and header[0]['mode'] == 'shadow'
        assert header[0]['half_bytes'] * 2 <= LIMIT_MB * 1024 * 1024
        assert sum(f.stat().st_size for f in files) <= LIMIT_MB * 1024 * 1024
    run_host(tmp_path, monkeypatch, body, handshake=False)
