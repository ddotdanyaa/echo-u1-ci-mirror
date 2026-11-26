"""Реестр 7.09: журнал деградации «готово / не готово и почему».

Состояние по реестру: сделано слиянием (раньше strict xfail; он начал проходить, маркер убран). Цель: перед первой репликой в журнале звонка есть строка «что недоступно и почему»,
а сбой, который движок проглатывает, виден не только в тексте лога.
Настоящий controlled_host.serve принимает звонок (подставные: телефон, облако, синтез, поиск; виртуальное время, HostRig).
В стенде модели Silero нет, ухо уходит на запасной способ (энергия): это настоящая деградация, её и ищем в журнале.
Смотрим на внешнее: строки журнала <home>/logs/echo_calls/*.jsonl и то, что услышал телефон. Сопоставление мягкое, по смыслу.
Проверка «готово к звонку» вне движка (одна команда на ноутбуке) сюда не входит, см. registry_proof/7.09.json.
"""
import json
import re
from pathlib import Path

from echo_sync import degradation
from helpers_spoken_diagnostics import run_host

COMPONENT = re.compile(r'\b(silero|vad|ear|onset|energy|ухо|слух\w*|эхо-?слух)\b', re.I)
REASON = re.compile(r'(not.?found|missing|no.?such|filenotfound|unavailable|не найден\w*|отсутств\w*|недоступ\w*|нет модели)', re.I)
QUESTION = 'Какая сейчас ставка НДС?'


def journal(home):
    files = sorted((f for f in (Path(home) / 'logs' / 'echo_calls').glob('*.jsonl') if '.v5tap' not in f.name))
    assert len(files) == 1, files
    return [json.loads(line) for line in files[0].read_text(encoding='utf-8').splitlines()]


def service_text(row):
    """Служебное содержимое строки без слов человека и подсказки, чтобы реплика не сошла за запись о сбое."""
    return json.dumps({k: v for k, v in row.items() if k not in ('text', 'chars')}, ensure_ascii=False)


async def run_call(host):
    await host.ask(QUESTION)
    await host.advance(8)
    rows = journal(host.home)
    assert any(r.get('ev') == 'call_open' for r in rows), 'опора: журнал звонка открыт'
    assert any(r.get('ev') == 'user_final' for r in rows), 'опора: реплика дошла до движка'
    assert any(r.get('ev') == 'ready' for r in rows), 'опора: звонок дошёл до готовности'
    return rows


def test_a_swallowed_lookup_failure_is_visible_in_the_journal(tmp_path, monkeypatch):
    """Часть функции, которая уже есть: сбой поиска виден в журнале звонка (код и вид сбоя), не только в голосе."""
    async def body(host):
        rows = await run_call(host)
        assert host.spoken(), 'опора: телефон услышал подсказку о сбое'
        failed = [r for r in rows if r.get('ev') in ('stage', 'error', 'decision') and re.search(r'fail|unavailable|no_source', service_text(r), re.I)]
        assert failed, 'сбой поиска не виден в журнале: %r' % [r.get('ev') for r in rows]
    run_host(tmp_path, monkeypatch, body, lookup=['raise'])


def test_an_unavailable_ear_is_named_with_its_reason_before_the_first_word(tmp_path, monkeypatch):
    """Модель слуха не найдена, ухо ушло на запасной способ: до первой реплики в журнале одна строка «что и почему»."""
    async def body(host):
        rows = await run_call(host)
        first_user = next(i for i, r in enumerate(rows) if r.get('ev') == 'user_start')
        before = [service_text(r) for r in rows[:first_user]]
        assert any(COMPONENT.search(t) and REASON.search(t) for t in before), (
            'до первой реплики нет строки «что недоступно и почему»: %r' % [r.get('ev') for r in rows[:first_user]])
    def no_model():
        raise FileNotFoundError('silero model')

    # the stand is the same everywhere: whether the ear's model is installed on this machine decides what the check before the call finds, so the model is made absent
    monkeypatch.setattr(degradation, 'default_checks', lambda: {'local_ear.silero': no_model})
    degradation.reset()
    run_host(tmp_path, monkeypatch, body)
