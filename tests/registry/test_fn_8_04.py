"""Реестр 8.04: повтор звонка по записанному звуку.

Доказана только основа: настоящий controlled_host.serve (HostRig, подставные телефон и облако на виртуальном времени) при живых
настройках сервера (файл materials/echo_settings.json: три лимита, запись звонка без ключа) пишет звук звонка: <home>/logs/echo_pcm/<звонок>/
mic.wav, cue.wav и timeline.jsonl. Читателя записи и повтора через ухо и контроллер в единой ветке нет (цель xfail ниже:
вход tools.replay.acoustic.replay есть только в боковой ветке u13, там он гонит звук через ухо без контроллера).
"""
import base64
import importlib
import importlib.util
import json
import math
import struct
import wave
from pathlib import Path

import pytest

import helpers_s6_fault as F
from test_ux_call_trace_host import dictation, settings_file

RATE, BURSTS = 24000, 3
# живые значения сервера (Приложение А реестра, функция 1.06); умолчания кода: off, 20, 2048, 200
LIVE = dict(pcm_record_calls=200, pcm_record_mb=8192, pcm_record_call_mb=1200)


def tone(ms, amp):
    return b''.join(struct.pack('<h', int(amp * math.sin(2 * math.pi * 300 * i / RATE))) for i in range(RATE * ms // 1000))


MIC = tone(1000, 5) + (tone(600, 12000) + tone(1200, 5)) * BURSTS       # выдуманный звук: тишина и три всплеска
PACKETS = [MIC[i:i + 4800] for i in range(0, len(MIC), 4800)]           # пакеты по 100 мс, как шлёт телефон


def record_call(tmp_path, monkeypatch, **settings):
    """Один звонок: телефон шлёт MIC, потом диктовка. Возвращает папку записи звонка (или None, если её нет)."""
    async def main():
        F.patch_clock(monkeypatch)
        async with F.HostRig(tmp_path, monkeypatch) as host:
            settings_file(host.home, **settings)
            await host.handshake()
            for pcm in PACKETS:
                host.ws.push({'type': 'input_audio_buffer.append', 'audio': base64.b64encode(pcm).decode()})
            await dictation(host)
            await host.advance(20)
        return host
    host = F.run(main)
    root = Path(host.home) / 'logs' / 'echo_pcm'
    dirs = [p for p in root.iterdir() if p.is_dir()] if root.is_dir() else []
    assert len(dirs) <= 1, dirs
    return dirs[0] if dirs else None


def test_the_call_leaves_wav_per_channel_and_a_timeline(tmp_path, monkeypatch):
    folder = record_call(tmp_path, monkeypatch, **LIVE)
    assert folder is not None, 'запись включена, а папки звонка нет'
    for name in ('mic.wav', 'cue.wav', 'timeline.jsonl'):
        assert (folder / name).is_file() and (folder / name).stat().st_size > 44, name
    with wave.open(str(folder / 'mic.wav')) as w:         # читается стандартным разбором: заголовок исправлен при закрытии
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, RATE)
        frames = w.readframes(w.getnframes())
    # длительность записи согласуется с поданным звуком (тишина на разрывах может только добавить)
    assert len(frames) >= len(MIC) and len(frames) % 2 == 0
    assert len(frames) / (2 * RATE) == pytest.approx(len(MIC) / (2 * RATE), abs=1.0)
    assert frames.startswith(PACKETS[0]), 'начало записи не совпало с поданным звуком'
    lines = [json.loads(x) for x in (folder / 'timeline.jsonl').read_text(encoding='utf-8').splitlines()]
    kinds = {row['ev'] for row in lines}
    assert 'open' in kinds and {row.get('ch') for row in lines if row['ev'] == 'channel'} >= {'mic', 'cue'}
    assert all('t' in row for row in lines), 'у строки временной шкалы нет времени'


@pytest.mark.xfail(strict=True, reason='реестр 8.04: НЕ СДЕЛАНО, заготовка только в ветке u13')
def test_target_replay_of_the_recorded_call_finds_the_same_speech(tmp_path, monkeypatch):
    """Цель: записанный звонок прогоняется заново (вход ветки u13: tools.replay.acoustic.replay(папка))."""
    folder = record_call(tmp_path, monkeypatch, **LIVE)
    assert folder is not None
    spec = importlib.util.find_spec('tools.replay.acoustic')
    assert spec is not None, 'в единой ветке нет tools/replay/acoustic.py (читателя записанного звонка)'
    got = importlib.import_module('tools.replay.acoustic').replay(folder)
    assert got['status'] == 'ok'
    assert got['onsets'] == got['offsets'] == BURSTS       # ухо нашло столько же фраз, сколько было всплесков
