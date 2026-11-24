"""Реестр 7.07 «Событийный цикл звонка: одно Silero, тик по событиям» (правило хозяина тика, ключа нет).

Настоящий controlled_host.serve (HostRig: подставные телефон, облачный помощник, SAPI, виртуальное время), настройки по умолчанию. Что доказываем по внешнему: тик звонка разбужен событием, поэтому реакция на событие облака не зависит от того, в какой
момент сетки .1 с оно пришло. Пример: ответ из одного слова без точки удерживается окном ожидания продолжения, потом озвучивается;
сколько секунд от события до озвучивания, видно по времени кадров телефону. Тик по событиям: задержка одна и та же. Журнал звонка при этом тот же. Работа журнала отдельным потоком
и единственное Silero на ухо и канал этим файлом не доказываются (нужны подставные ухо и модель, а замер нагрузки ноутбука не сделан).
"""
import json
from pathlib import Path

import helpers_s6_fault as F

SETTINGS = {}          # без ключей
LONE_WORD = 'Энтомология'
QUESTION = 'Как называется наука о насекомых'


def write_settings(home, values):
    folder = Path(home) / 'materials'
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'echo_settings.json').write_text(json.dumps(values), encoding='utf-8')


def journal_rows(home):
    files = sorted((f for f in (Path(home) / 'logs' / 'echo_calls').glob('*.jsonl') if '.v5tap' not in f.name))
    assert len(files) == 1, files
    return [json.loads(line) for line in files[0].read_text(encoding='utf-8').splitlines()]


def run_rounds(tmp_path, monkeypatch, rounds=5):
    """Звонок: пять раз вопрос и ответ из одного слова; возвращает задержки (с) от события до озвучивания и журнал."""
    write_settings(tmp_path / 'home', SETTINGS)

    async def main():
        F.patch_clock(monkeypatch)
        async with F.HostRig(tmp_path, monkeypatch) as host:
            await host.handshake()
            delays = []
            for k in range(rounds):
                await host.advance(5.03)          # каждый раз событие попадает в другую долю сетки .1 с
                host.cloud(F.created(f'u{k}', 'user', 'Как'))
                host.cloud(F.done(f'u{k}', 'user', QUESTION))
                await host.advance(0.3)
                came = host.now()
                host.cloud(F.created(f'a{k}', 'assistant', LONE_WORD))
                host.cloud(F.done(f'a{k}', 'assistant', LONE_WORD))
                await host.advance(0.04)
                host.cloud({'type': 'rate_limits.updated'})      # безобидное служебное событие: сдвигает тик по событиям с границы окна
                await host.advance(3)
                said = host.frames('response.audio_transcript.delta', came)
                assert said and said[0].data['delta'] == LONE_WORD, (k, host.spoken())
                delays.append(said[0].t - came)
            return delays, journal_rows(host.home)
    return F.run(main)


def test_the_call_reacts_to_a_cloud_event_at_the_same_delay_wherever_it_fell_in_the_tick_grid(tmp_path, monkeypatch):
    delays, rows = run_rounds(tmp_path, monkeypatch)
    # опоры: звонок отработал, окно ожидания продолжения действительно удержало слово (путь по таймеру), журнал на месте
    kinds = [row.get('ev') for row in rows]
    assert 'call_open' in kinds and kinds.count('user_final') >= 5 and 'cue' in kinds, kinds
    assert all(0.5 < d < 3 for d in delays), delays
    # само свойство: задержка не зависит от доли сетки, в которую попало событие
    assert max(delays) - min(delays) <= 0.02, delays
