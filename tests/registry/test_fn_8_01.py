"""Реестр 8.01 «Журнал фактов и причин, отчёт по звонку»: после звонка видно, что и почему сказано или не сказано; несказанные ответы раскладываются по причинам.

Настоящий controlled_host.serve с подставным телефоном и облаком (helpers_s6_fault.HostRig, виртуальное время). Настройки профиля такие, как на сервере
(столбец реестра): facts_journal=on и call_trace=on, файлом materials/echo_settings.json. Смотрим только на журнал звонка <home>/logs/echo_calls/*.jsonl
и на то, что напечатал инструмент отчёта.
Первый тест (зелёный): журнал звонка и журнал причин (why) работают. Второй и третий (xfail, цель): отчёта «несказанные ответы по причинам» в единой ветке нет
(tools_v6/echo_call_report.py лежит только в боковой ветке и на ноутбуке; tools/call_report.py считает задержки, а не причины), и несказанный ответ на
реплику-благодарность не получает в журнале записи с причиной несказанного.
"""
import collections
import json
import logging
import subprocess
import sys
from pathlib import Path

import pytest

import helpers_s6_fault as F

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / 'tools_v6' / 'echo_call_report.py'     # путь инструмента с ноутбука; в единой ветке его нет
THANKS = 'Спасибо, всё понятно.'          # не вопрос: ответ облака на него не озвучивается
THANKS_REPLY = 'Пожалуйста, обращайтесь.'


@pytest.fixture(autouse=True)
def decisions_are_logged(caplog):
    """Продукт пишет решения контроллера в лог INFO, журнал звонка слушает этот лог."""
    caplog.set_level(logging.INFO, logger='echo-sync')


def call_with_one_said_and_one_unsaid(tmp_path, monkeypatch, facts='on'):
    """Один звонок: вопрос с озвученным ответом, затем реплика-благодарность, ответ на неё не озвучивается. Возвращает папку журналов и сказанное."""
    async def main():
        F.patch_clock(monkeypatch)
        async with F.HostRig(tmp_path, monkeypatch) as host:
            folder = host.home / 'materials'
            folder.mkdir(parents=True, exist_ok=True)
            (folder / 'echo_settings.json').write_text(json.dumps({'facts_journal': facts, 'call_trace': 'on'}), encoding='utf-8')
            await host.handshake()
            await host.ask(F.DIRECT_QUESTION, tid='u1')
            await host.answer(F.DIRECT_ANSWER, tid='a1')
            await host.advance(2)
            await host.ask(THANKS, tid='u2')
            await host.answer(THANKS_REPLY, tid='a2')
            await host.advance(10)
            return host.home, host.spoken()
    home, spoken = F.run(main)
    return home / 'logs' / 'echo_calls', spoken


def journal_rows(folder):
    files = sorted((f for f in Path(folder).glob('*.jsonl') if '.v5tap' not in f.name)) if Path(folder).is_dir() else []
    assert len(files) == 1, files
    return [json.loads(line) for line in files[0].read_text(encoding='utf-8').splitlines() if line.strip()]


def test_the_journal_says_what_was_said_and_the_why_journal_names_the_rule(tmp_path, monkeypatch):
    folder, spoken = call_with_one_said_and_one_unsaid(tmp_path, monkeypatch)
    rows = journal_rows(folder)
    # опоры: звонок открыт, обе реплики и оба ответа облака записаны, сказан только первый ответ
    assert rows[0]['ev'] == 'call_open' and spoken and not any('обращайтесь' in line for line in spoken)
    assert [r['text'] for r in rows if r['ev'] == 'user_final'] == [F.DIRECT_QUESTION, THANKS]
    assert [r['text'] for r in rows if r['ev'] == 'assistant_final'] == [F.DIRECT_ANSWER, THANKS_REPLY]
    # сказанное: решение с причиной и подсказка, совпадающая с тем, что услышал телефон
    decisions = [r for r in rows if r['ev'] == 'decision' and r.get('kind') == 'question']
    assert decisions and decisions[0]['reason']
    assert [r['text'] for r in rows if r['ev'] == 'cue'] == spoken
    # журнал причин (facts_journal=on): строки why с видом (удержание или сброс) и названным правилом
    whys = [r for r in rows if r['ev'] == 'why']
    named = [w for w in whys if w['kind'] in ('hold', 'drop', 'cut')]      # the gate of the irreversible (always on) adds kind=act lines: they name act and reason (tests/test_night_gate_act.py), the cut lines name the rule
    assert whys and all(w['kind'] in ('hold', 'drop', 'act', 'cut') for w in whys), whys
    assert named and all(w['rule'] not in (None, '', '-') for w in named), named
    assert all(w['reason'] not in (None, '', '-') and w['act'] for w in whys if w['kind'] == 'act'), whys
    # несказанное: ответ записан, подсказки на него нет, у реплики есть оценка с видом и причиной
    verdicts = [r for r in rows if r['ev'] == 'judge' and r.get('kind') != 'question']
    assert verdicts and all(r['kind'] and r['reason'] for r in verdicts)
    assert not any(r['ev'] == 'cue' and 'обращайтесь' in r.get('text', '') for r in rows)


@pytest.mark.xfail(strict=True, reason='реестр 8.01: заявлено «работает», отчёт по причинам в единую ветку не влит')
def test_the_report_tool_lays_the_unsaid_answers_out_by_reason(tmp_path, monkeypatch):
    folder, _ = call_with_one_said_and_one_unsaid(tmp_path, monkeypatch)
    done = subprocess.run([sys.executable, str(TOOL), str(folder), '--json', '--out', str(tmp_path / 'report')],
                          capture_output=True, text=True, cwd=ROOT, timeout=60)
    assert done.returncode == 0, done.stderr[-300:]
    report = json.loads(done.stdout)
    counts = report['summary']['counts']
    # сказано + не сказано = всего ответов (два ответа облака, один озвучен), сумма по причинам = числу несказанных
    assert counts['answers'] == 2 and counts['spoken'] + counts['silent'] == counts['answers'] and counts['silent'] == 1
    by_reason = collections.Counter(a['silent_why'] for a in report['answers'] if a['first_sound_s'] is None)
    assert sum(by_reason.values()) == counts['silent'], by_reason


@pytest.mark.xfail(strict=True, reason='реестр 8.01: заявлено «работает», несказанный ответ без причины в журнале')
def test_the_unsaid_answer_has_a_reason_record_in_the_journal(tmp_path, monkeypatch):
    folder, _ = call_with_one_said_and_one_unsaid(tmp_path, monkeypatch)
    rows = journal_rows(folder)
    start = next(i for i, r in enumerate(rows) if r['ev'] == 'user_final' and r['text'] == THANKS)
    assert any(r['ev'] == 'assistant_final' and r['text'] == THANKS_REPLY for r in rows[start:])
    # после реплики-благодарности есть запись о том, почему ответ не сказан: решение «silent» с причиной или сброс why
    reasons = [r for r in rows[start:] if (r['ev'] == 'decision' and r.get('kind') == 'silent' and r.get('reason'))
               or (r['ev'] == 'why' and r.get('kind') == 'drop' and r.get('rule'))]
    assert reasons, 'в журнале нет записи с причиной несказанного ответа'
