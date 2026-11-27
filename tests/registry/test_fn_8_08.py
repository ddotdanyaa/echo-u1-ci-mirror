"""Реестр 8.08 «Журнал звонка на три часа»: журнал вмещает трёхчасовой звонок, пробы не выталкивают настоящие звонки.

Настоящий controlled_host.serve (HostRig: подставные телефон, облачный помощник, SAPI, виртуальное время). Настройки профиля, как на
сервере (Приложение А реестра): materials/echo_settings.json с facts_journal=on, call_trace=on, mic_gap_ms=1500, mic_ring_s=60.
Читаем только журнал <home>/logs/echo_calls/*.jsonl, как его читает владелец. Проба = запрос echo_trace=1 + echo_call_trace=1 (так на сервере).
"""
import json
from pathlib import Path

import pytest

import helpers_s6_fault as F

LIVE = {'facts_journal': 'on', 'call_trace': 'on', 'mic_gap_ms': 1500, 'mic_ring_s': 60}
PROBE = {'echo_trace': '1', 'echo_call_trace': '1'}
LONG_SAY = ('Длинная реплика собеседника про поставку и условия договора. ' * 40)[:1900]
LONG_ANSWER = ('Развёрнутый ответ суфлёра по делу, с подробностями. ' * 50)[:1900]
STEP_S, TURN_EVERY, CALL_S = 4, 135, 10_800        # шаг микрофона 4 с (2700 строк, больше старых 200 кБ), реплика каждые 9 мин, три часа


def folder(home):
    return Path(home) / 'logs' / 'echo_calls'


def live_profile(tmp_path):
    """Профиль как на сервере: настройки файлом, не monkeypatch."""
    materials = Path(tmp_path) / 'home' / 'materials'
    materials.mkdir(parents=True, exist_ok=True)
    (materials / 'echo_settings.json').write_text(json.dumps(LIVE), encoding='utf-8')


def rows_of(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]


def fill_with_old_calls(tmp_path, count):
    old = folder(tmp_path / 'home')
    old.mkdir(parents=True)
    for k in range(count):
        (old / f'20260101-{k // 60:02d}{k % 60:02d}00-old{k}.jsonl').write_text('{"ev": "call_open", "t": 0}\n', encoding='utf-8')
    return old


async def six_probes_and_a_call(tmp_path, monkeypatch):
    """Шесть проб после выкладки (как на сервере: пишут журнал) и затем один настоящий звонок."""
    F.patch_clock(monkeypatch)
    for _ in range(6):
        async with F.HostRig(tmp_path, monkeypatch, query=PROBE) as probe:
            await probe.handshake()
    async with F.HostRig(tmp_path, monkeypatch) as host:
        await host.handshake()
        await host.ask(F.DIRECT_QUESTION)
        await host.advance(1)


def test_a_three_hour_call_fits_in_one_journal_file(tmp_path, monkeypatch):
    """3 часа плотной беседы: файл не упирается в предел, начало и конец на месте, последняя строка call_close."""
    live_profile(tmp_path)

    async def main():
        F.patch_clock(monkeypatch)
        async with F.HostRig(tmp_path, monkeypatch) as host:
            await host.handshake()
            for step in range(CALL_S // STEP_S):       # пакет микрофона каждые 4 с, длинная реплика и длинный ответ каждые 9 мин
                host.phone_audio(1)
                if step % TURN_EVERY == 0:
                    n = step // TURN_EVERY
                    host.cloud(F.created(f'u{n}', 'user', 'слово'))
                    host.cloud(F.done(f'u{n}', 'user', f'{n}. {LONG_SAY}'))
                    host.cloud(F.created(f'a{n}', 'assistant', 'Ответ'))
                    host.cloud(F.done(f'a{n}', 'assistant', f'{n}. {LONG_ANSWER}'))
                await host.advance(STEP_S)
            return host.home
    files = sorted(f for f in folder(F.run(main)).glob('*.jsonl') if '.v5tap' not in f.name)
    assert len(files) == 1
    rows = rows_of(files[0])
    finals = [r['text'] for r in rows if r['ev'] == 'user_final']
    # опора: звонок и правда был трёхчасовым и записался с начала, журнал фактов включён
    assert rows[0]['ev'] == 'call_open' and rows[-1]['ev'] == 'call_close'
    assert rows[-1]['elapsed_ms'] >= 10_700_000
    assert any(r['ev'] == 'mic_gap' for r in rows), 'журнал фактов (facts_journal=on) не пишет'
    # сама функция: журнал вместил всё, ничего не обрезано пределом
    assert not any(r['ev'] in ('trace_full', 'mic_full') for r in rows), 'журнал упёрся в предел до конца звонка'
    assert len(finals) == -(-(CALL_S // STEP_S) // TURN_EVERY) and finals[-1].startswith(f'{len(finals) - 1}. ')
    assert max(r['t'] for r in rows if r['ev'] == 'mic') >= 10_500_000, 'строки микрофона кончились раньше звонка'
    assert files[0].stat().st_size < 8_000_000


def test_probes_do_not_push_real_calls_out_of_the_folder(tmp_path, monkeypatch):
    """Жизненный случай: 60 настоящих журналов, шесть проб (пишут журнал) и новый звонок: все 60 на месте (при пределе 50 было бы 17 потерь)."""
    live_profile(tmp_path)
    old = fill_with_old_calls(tmp_path, 60)
    F.run(lambda: six_probes_and_a_call(tmp_path, monkeypatch))
    names = [p.name for p in (f for f in old.glob('*.jsonl') if '.v5tap' not in f.name)]
    assert sum('-old' not in n for n in names) == 7, 'шесть проб и новый звонок записали по файлу'
    assert sum('-old' in n for n in names) == 60, 'пробы вытолкнули настоящие звонки'


@pytest.mark.xfail(strict=True, reason='реестр 8.08: только в ветке; пробы считаются наравне со звонками и на полной папке выталкивают настоящие')
def test_probes_do_not_push_real_calls_out_of_a_nearly_full_folder(tmp_path, monkeypatch):
    """Край: 399 настоящих (предел 400), шесть проб и новый звонок = 406 файлов: чистка не должна трогать настоящие."""
    live_profile(tmp_path)
    old = fill_with_old_calls(tmp_path, 399)
    F.run(lambda: six_probes_and_a_call(tmp_path, monkeypatch))
    names = [p.name for p in (f for f in old.glob('*.jsonl') if '.v5tap' not in f.name)]
    assert sum('-old' in n for n in names) == 399, 'на полной папке пробы вытолкнули настоящие звонки'
