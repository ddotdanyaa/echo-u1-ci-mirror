"""Реестр 1.05 «Состояние входа: не повторять вслепую при глухом канале». Состояние по реестру: РАБОТАЕТ НА СЕРВЕРЕ.

Стенд: настоящий controlled_host.serve() целиком (helpers_s6_fault.HostRig): поддельные телефон, помощник, SAPI, виртуальное время.
Настройки: настоящий файл <home>/materials/echo_settings.json со словарём LIVE (живые значения сервера: 
inline_repeat=False, max_auto_repeats=3, repeat_seconds=2.0). Телефон шлёт кадры input_audio_buffer.append (звук по 20 мс).
Снаружи видно: сколько раз телефону ушла одна и та же порция (response.audio_transcript.delta), решения в журнале звонка
<home>/logs/echo_calls/*.jsonl (decision repeat_gate / auto_repeat_cap) и строка input_state в логе echo-sync.
"""
import base64
import json
import logging
from pathlib import Path

import pytest

import helpers_s6_fault as F
from helpers_spoken_diagnostics import run_host

LIVE = {'inline_repeat': False, 'max_auto_repeats': 3, 'repeat_seconds': 2.0}
SOUND = base64.b64encode(b'\x10\x00' * 480).decode()       # 20 мс живого звука, не цифровой ноль
MUTE = base64.b64encode(b'\x00\x00' * 480).decode()        # 20 мс цифрового нуля: микрофон выключен
QUESTION, ANSWER = 'Что такое фотосинтез?', 'Фотосинтез — это процесс образования органических веществ из углекислого газа и воды на свету.'


@pytest.fixture(autouse=True)
def decisions_are_logged(caplog):
    caplog.set_level(logging.INFO, logger='echo-sync')


def journal(host):
    files = sorted((f for f in (host.home / 'logs' / 'echo_calls').glob('*.jsonl') if '.v5tap' not in f.name))
    return [json.loads(line) for f in files for line in f.read_text(encoding='utf-8').splitlines()]


def decisions(host, reason):
    return [r for r in journal(host) if r['ev'] == 'decision' and r['reason'] == reason]


async def listen(host, seconds, packet=SOUND):
    """Телефон шлёт звук по пакету в 20 мс и время идёт."""
    for _ in range(int(seconds * 50)):
        host.ws.push({'type': 'input_audio_buffer.append', 'audio': packet})
        await host.advance(0.02)


async def first_portion(host):
    """Вопрос, ответ облака; настройки пишутся до рукопожатия, как профиль на сервере."""
    folder = host.home / 'materials'
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'echo_settings.json').write_text(json.dumps(LIVE), encoding='utf-8')
    await host.handshake()
    await host.ask(QUESTION)
    await host.answer(ANSWER)
    assert len(host.spoken()) == 1, host.spoken()
    return host.spoken()[0]


def test_a_silent_channel_is_not_repeated_into_the_void(tmp_path, monkeypatch, caplog):
    """Пакетов с телефона нет совсем: порция звучит один раз, остальное время держится решение repeat_gate/input_hold, повторов нет."""
    async def body(host):
        await first_portion(host)
        await host.advance(12)
        assert len(host.spoken()) == 1, host.spoken()
        assert [r['gate'] for r in decisions(host, 'repeat_gate')] == ['input_hold']
        assert not decisions(host, 'auto_repeat_cap'), 'удержание не считается в потолок повторов'
        assert 'input_state state=no_packets act=hold' in caplog.text
    run_host(tmp_path, monkeypatch, body, handshake=False)


def test_the_repeat_comes_back_when_the_channel_does(tmp_path, monkeypatch, caplog):
    """Сначала глухой канал (6 с, одна порция), потом пошёл звук: повторы возобновляются и упираются в потолок 3, удержание их не съело."""
    async def body(host):
        portion = await first_portion(host)
        await host.advance(6)
        assert host.spoken() == [portion] and decisions(host, 'repeat_gate')
        await listen(host, 10)
        assert host.spoken() == [portion] * 4, host.spoken()
        assert [r['cap'] for r in decisions(host, 'auto_repeat_cap')] == [3]
        assert 'input_state state=silence act=repeat' in caplog.text
    run_host(tmp_path, monkeypatch, body, handshake=False)


def test_a_muted_microphone_stops_the_repeat(tmp_path, monkeypatch, caplog):
    """Пакеты идут, но это цифровой ноль больше 2 с: состояние dead_input, дальше повторов нет (при живом звуке за то же время их 3)."""
    async def body(host):
        await first_portion(host)
        await listen(host, 12, MUTE)
        assert len(host.spoken()) <= 2, host.spoken()
        assert [r['gate'] for r in decisions(host, 'repeat_gate')] == ['input_hold']
        assert 'input_state state=dead_input act=hold' in caplog.text
        assert not decisions(host, 'auto_repeat_cap')
    run_host(tmp_path, monkeypatch, body, handshake=False)
