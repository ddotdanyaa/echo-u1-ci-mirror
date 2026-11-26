"""Реестр 8.09: измерение слышимой задержки до наушника. Вердикт needs_phone: ядро (звук в наушнике iPhone, паспорт замера) вне репозитория.

Здесь доказана только серверная часть: настоящий controlled_host.serve (HostRig, виртуальное время, подставные телефон, облачный
помощник и SAPI) после ответа пишет строку лога 'echo-sync audible first_cue_ms=<мс> clock=<часы>', и это число равно времени от
конца речи вопроса до первого кадра звука ответа, пришедшего телефону. Рецепт замера на телефоне читает именно эту строку.
Настроек у функции нет (реестр: «—»), все ключи профиля - умолчания кода.
"""
import logging
import re

import helpers_s6_fault as F
from helpers_spoken_diagnostics import run_host

QUESTION = 'Что такое равновесие весов?'
ANSWER = 'Равновесие весов наступает, когда обе чаши весят одинаково, и стрелка стоит ровно посередине.'
TICK = 0.02       # телефон шлёт звук кадрами по 20 мс: это часы ввода, на которых сервер считает конец речи
LINE = re.compile(r'echo-sync audible first_cue_ms=(\d+) clock=(\w+)')


def audible_lines(caplog):
    return [m.groups() for m in map(LINE.search, (r.getMessage() for r in caplog.records)) if m]


def one_call(tmp_path, monkeypatch, caplog, name, delay):
    """Звонок: вопрос (речь 1 с), потом тишина delay секунд, потом ответ. Возвращает (строки лога, мс от конца речи до первого звука ответа)."""
    caplog.set_level(logging.INFO, logger='echo-sync')
    caplog.clear()
    out = {}

    async def body(host):
        async def pump(seconds):
            for _ in range(round(seconds / TICK)):
                host.phone_audio()
                await host.advance(TICK)
        await pump(0.5)
        host.cloud(F.created('u1', 'user', 'Что', start=0))
        await pump(0.5)
        host.cloud(F.done('u1', 'user', QUESTION, start=0))      # конец речи вопроса: 1000 мс на часах ввода
        speech_end = host.now()
        await pump(delay)
        await host.answer(ANSWER, tid='a1')
        await pump(1.5)
        first = host.audio()
        assert first, 'ответ не дошёл до телефона звуком'
        out['heard_ms'] = (first[0].t - speech_end) * 1000
        assert 'error' not in {f.type for f in host.ws.frames}
    run_host(tmp_path / name, monkeypatch, body)
    return audible_lines(caplog), out['heard_ms']


def test_server_logs_the_time_from_end_of_question_to_first_audio_frame(tmp_path, monkeypatch, caplog):
    lines, heard_ms = one_call(tmp_path, monkeypatch, caplog, 'a', 0.5)
    assert len(lines) == 1, lines                      # одна оценка на ответ, не на каждую подсказку
    logged, clock = int(lines[0][0]), lines[0][1]
    assert clock == 'input'
    assert abs(logged - heard_ms) <= 60, (logged, heard_ms)       # допуск 60 мс: шаг кадра 20 мс и порядок событий
    assert logged >= 400                              # не нуль и не пустышка: задержка до ответа действительно прошла


def test_logged_number_follows_the_real_delay_of_the_answer(tmp_path, monkeypatch, caplog):
    short = one_call(tmp_path, monkeypatch, caplog, 'a', 0.5)
    long = one_call(tmp_path, monkeypatch, caplog, 'b', 2.0)
    assert len(short[0]) == len(long[0]) == 1, (short, long)
    short_ms, long_ms = int(short[0][0][0]), int(long[0][0][0])
    assert abs((long_ms - short_ms) - 1500) <= 100, (short_ms, long_ms)      # задержка ответа выросла на 1,5 с, число выросло так же
    assert abs(long_ms - long[1]) <= 60 and abs(short_ms - short[1]) <= 60, (short, long)
