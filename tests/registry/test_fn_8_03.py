"""Реестр 8.03 «Повтор записанных звонков через движок».

В единой ветке настоящий инструмент делает одно: журнал звонка (logs/echo_calls/*.jsonl) -> образец и числа по КАЖДОМУ журналу
(`python -m tools.harvest`, файл counters.json). Это доказано зелёными тестами на настоящем звонке через controlled_host.serve
(HostRig, виртуальное время, подставные телефон и облако). Повтор журнала через движок и сравнение флагов по журналам
(tests/test_x_flag_replay.py + python -m tools.replay.flag_compare) перенесены из harvest-u13 (P14): test_c зелёный, флаги — только числовые настройки.
Реплики и журналы выдуманы. Смотрим на подсказки, журнал, вывод инструмента (stdout, код возврата) и его файлы.
"""
import importlib.util
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest

from helpers_spoken_diagnostics import run_host

REPO = Path(__file__).resolve().parents[2]
UTF8 = {**os.environ, 'PYTHONUTF8': '1'}       # a child prints Russian: its pipe is utf-8 on every machine
ASKS = ('Почему небо голубое днём?', 'Сколько будет двадцать плюс двадцать два?')
ANSWERS = ('Воздух сильнее рассеивает синий свет, поэтому небо кажется голубым.', 'Сорок два.')
SIX = ('loops', 'stale', 'failures', 'silent', 'stuck', 'back')
LOOP, FAILURE = 'Инерция — это свойство тела.', 'Поиск не ответил.'


@pytest.fixture(autouse=True)
def decisions_are_logged(caplog):
    caplog.set_level(logging.INFO, logger='echo-sync')      # решения контроллера попадают в журнал звонка через лог INFO, как на сервере


def real_call(tmp_path, monkeypatch, name='call'):
    """Настоящий звонок через движок: вопросы и ответы облака по порядку. Возвращает (путь журнала, подсказки)."""
    seen = {}

    async def body(host):
        for n, (ask, answer) in enumerate(zip(ASKS, ANSWERS), 1):
            await host.ask(ask, tid=f'u{n}')
            await host.answer(answer, tid=f'a{n}')
            await host.advance(2)
        seen['spoken'] = host.spoken()
        files = sorted((f for f in (Path(host.home) / 'logs' / 'echo_calls').glob('*.jsonl') if '.v5tap' not in f.name))
        assert len(files) == 1, files
        seen['path'] = files[0]
    run_host(tmp_path / name, monkeypatch, body)
    return seen['path'], seen['spoken']


def write_journal(path, rows):
    path.write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows), encoding='utf-8')
    return path


def old_call(path, cue, n_cues):
    """Выдуманный старый журнал: один вопрос и n_cues раз одна и та же подсказка."""
    rows = [{'t': 0, 'ev': 'call_open', 'max_auto_repeats': 1}, {'t': 1000, 'ev': 'user_final', 'id': 'u', 'text': 'что такое инерция'},
            {'t': 1100, 'ev': 'decision', 'kind': 'answer', 'reason': 'r', 'revision': 1, 'index': 0}]
    for n in range(n_cues):
        rows += [{'t': 2000 + 1000 * n, 'ev': 'cue', 'text': cue}, {'t': 2500 + 1000 * n, 'ev': 'cue_end', 'status': 'completed'}]
    return write_journal(path, rows)


def heard_call(path):
    """Выдуманный журнал звонка с ухом (ear_final), как пишет телефон: два вопроса, ответ облака и подсказка на каждый."""
    rows = [{'t': 0, 'ev': 'call_open', 'source': 'phone', 'max_auto_repeats': 1, 'repeat_seconds': 6.0}]
    for n, (ask, answer, t0) in enumerate(((ASKS[0], ANSWERS[0], 2000), (ASKS[1], ANSWERS[1], 20000)), 1):
        rows += [{'t': t0, 'ev': 'user_start', 'id': f'u{n}'}, {'t': t0 + 1500, 'ev': 'ear_final', 'uid': 'e', 'text': ask, 'kind': 'question', 'speech_ms': 1200, 'lag_ms': 100},
                 {'t': t0 + 1800, 'ev': 'user_final', 'id': f'u{n}', 'text': ask}, {'t': t0 + 3500, 'ev': 'assistant_start', 'id': f'a{n}'},
                 {'t': t0 + 3600, 'ev': 'assistant_final', 'id': f'a{n}', 'text': answer},
                 {'t': t0 + 4000, 'ev': 'decision', 'kind': 'question', 'reason': 'question_mark', 'revision': n, 'index': 0},
                 {'t': t0 + 4100, 'ev': 'cue', 'text': answer}, {'t': t0 + 6000, 'ev': 'cue_end', 'status': 'completed'}]
    return write_journal(path, rows)


def harvest(journals, out):
    """Настоящий вход `python -m tools.harvest <журналы> --out <папка>`: (код возврата, stdout, counters.json или None)."""
    done = subprocess.run([sys.executable, '-m', 'tools.harvest', *map(str, journals), '--out', str(out)], cwd=REPO, capture_output=True,
                          text=True, encoding='utf-8', timeout=60, env=UTF8)
    counters = Path(out) / 'counters.json'
    return done.returncode, done.stdout, json.loads(counters.read_text(encoding='utf-8')) if counters.exists() else None


def test_a_real_call_journal_becomes_a_sample_and_clean_numbers(tmp_path, monkeypatch):
    path, spoken = real_call(tmp_path, monkeypatch)
    assert len(spoken) >= 2, 'звонок не произнёс подсказок'
    out = tmp_path / 'fixtures'
    code, printed, counters = harvest([path], out)
    assert code == 0 and '1 calls' in printed, printed
    assert counters['calls'] == 1 and len(counters['by_call']) == 1
    assert all(counters['total'][key] == 0 and counters['by_call'][0][key] == 0 for key in SIX), counters
    assert counters['by_call'][0]['finals'] == len(ASKS) and counters['by_call'][0]['cues'] == len(spoken)
    sample = (out / (path.stem + '.json')).read_text(encoding='utf-8')
    assert all(text in sample for text in (*ASKS, *spoken)), 'образец хранит слова пользователя и подсказки журнала'


def test_b_numbers_are_per_journal_not_a_sum(tmp_path):
    loop = old_call(tmp_path / 'loop.jsonl', LOOP, 4)               # подсказка при max_auto_repeats=1 звучит 4 раза: зацикливание
    failure = old_call(tmp_path / 'failure.jsonl', FAILURE, 1)      # голосовая диагностика вместо ответа
    clean = old_call(tmp_path / 'clean.jsonl', LOOP, 1)
    out = tmp_path / 'out'
    code, printed, counters = harvest([loop, failure, clean], out)
    assert code == 0 and '3 calls' in printed, printed
    by_call = {row['call']: row for row in counters['by_call']}
    assert (by_call['loop']['loops'], by_call['failure']['loops'], by_call['clean']['loops']) == (1, 0, 0)
    assert (by_call['loop']['failures'], by_call['failure']['failures'], by_call['clean']['failures']) == (0, 1, 0)
    assert counters['total']['loops'] == 1 and counters['total']['failures'] == 1
    assert all(key in row for row in by_call.values() for key in SIX)
    lines = {line.split(':')[0]: line for line in printed.splitlines() if line.startswith(('loop', 'failure', 'clean'))}
    assert 'loops=1' in lines['loop'] and 'loops=0' in lines['clean'] and 'failures=1' in lines['failure'], printed


def test_c_replay_through_the_engine_and_flag_compare_give_numbers_per_journal(tmp_path):
    assert importlib.util.find_spec('tools.replay.flag_compare') is not None, 'flag_compare нет в единой ветке'     # повтор входа с телефона (input_replay) — P13, свой тест
    runner = REPO / 'tests' / 'test_x_flag_replay.py'                                       # прогон всех образцов через настоящий контроллер
    assert runner.exists(), 'прогона образцов через движок нет в единой ветке'
    heard, loop = heard_call(tmp_path / 'heard.jsonl'), old_call(tmp_path / 'loop.jsonl', LOOP, 4)
    samples = tmp_path / 'samples'
    code, printed, counters = harvest([heard, loop], samples)
    assert code == 0 and counters['calls'] == 2

    def replay(folder, flags):
        env = {**UTF8, 'ECHO_HARVEST_DIR': str(samples), 'ECHO_FLAG_OUT': str(folder), 'ECHO_FLAGS': json.dumps(flags)}
        done = subprocess.run([sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider', str(runner)], cwd=REPO, env=env, capture_output=True,
                              text=True, encoding='utf-8', timeout=120)
        assert done.returncode == 0, done.stdout[-500:]
    base, other = tmp_path / 'base', tmp_path / 'other'
    replay(base, {})
    replay(other, {})                                                                       # кандидат с теми же флагами: отличий от базы быть не должно
    done = subprocess.run([sys.executable, '-m', 'tools.replay.flag_compare', str(base), str(other), '--json'], cwd=REPO, capture_output=True,
                          text=True, encoding='utf-8', timeout=60, env=UTF8)
    assert done.returncode == 0, done.stderr[-500:]
    report = json.loads(done.stdout)
    assert report['journals'] == 2 and report['missing'] == [] and report['critical'] == [] and report['blocking'] is False
    assert sorted(p.stem for p in base.glob('*.json')) == ['heard', 'loop'], 'числа повтора по каждому журналу'
    mine = json.loads((base / 'heard.json').read_text(encoding='utf-8'))['checks']
    assert mine['cues'] == counters['by_call'][0]['cues'] and all(mine[key] == 0 for key in ('loops', 'stale', 'failures', 'stuck', 'back')), 'повтор разошёлся с журналом'
