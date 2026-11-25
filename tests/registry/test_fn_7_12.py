"""Реестр 7.12: «Облако оглохло: заметить и сказать один раз».

Настоящий controlled_host.serve принимает звонок (подставные телефон, облачный помощник и SAPI на виртуальном времени, HostRig).
Облако услышало начало реплики человека (событие начала хода) и после этого замолчало совсем: ни слова, ни ошибки, канал открыт.
Функция работает, если человек слышит фразу о потере связи ровно один раз и в разумный срок, а не спрашивает в пустоту.
Тест описывает работающую функцию при настройках единой ветки по умолчанию (порог выключен), поэтому помечен xfail(strict).
"""
import json

import pytest

import helpers_s6_fault as F
from helpers_spoken_diagnostics import run_host

BOUND_S = 25.0       # порог задуман 15 с, плюс запас на ход таймера и озвучивание


def journal(home):
    files = sorted((f for f in (home / 'logs' / 'echo_calls').glob('*.jsonl') if '.v5tap' not in f.name))
    assert len(files) == 1, files
    return [json.loads(line) for line in files[0].read_text(encoding='utf-8').splitlines()]


def says_link_lost(text):
    return 'связь' in text.lower() and 'прерва' in text.lower()


@pytest.mark.xfail(strict=True, reason='реестр 7.12: ВЫКЛЮЧЕНО, порог native_media_socket.CLOUD_DEAF_S=0, задуманный 15 с')
def test_a_deaf_cloud_is_told_to_the_listener_once(tmp_path, monkeypatch):
    out = {}

    async def body(host):
        # опора 1: звонок живой, облако отвечает на обычный вопрос, человек слышит ответ
        await host.ask(F.DIRECT_QUESTION, tid='u1')
        await host.answer(F.DIRECT_ANSWER, tid='a1')
        await host.advance(8)
        assert host.spoken(), 'опора: звонок не заговорил на обычный вопрос'
        assert not any(says_link_lost(t) for t in host.spoken()), host.spoken()
        # облако услышало начало новой реплики и больше не шлёт ничего
        t0 = host.now()
        host.cloud(F.created('u2', 'user', 'Что'))
        await host.advance(BOUND_S)
        out['early'] = [t for t in host.spoken(since=t0) if says_link_lost(t)]
        out['early_errors'] = host.errors(since=t0)
        await host.advance(90)                                    # дальше тишина облака не должна пересказываться
        out['all'] = [t for t in host.spoken(since=t0) if says_link_lost(t)]
        out['rows'] = journal(host.home)
    run_host(tmp_path, monkeypatch, body)

    assert out['rows'][0]['ev'] == 'call_open'
    assert len(out['early']) == 1, f'за {BOUND_S:.0f} с человек должен услышать «связь прервалась»: {out["early"]}, ошибки {out["early_errors"]}'
    assert len(out['all']) == 1, f'сказать нужно один раз, а не каждые 15 с: {out["all"]}'
