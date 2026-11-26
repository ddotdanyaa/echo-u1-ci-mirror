"""Реестр 7.08: приватность. Личное не уходит в публичный поиск.

Настоящий controlled_host.serve принимает звонок (подставные: телефон, помощник облака, синтез и поиск; виртуальное время, HostRig).
Смотрим на внешнее: что получил публичный поиск (его вызовы на границе), что записано в журнале звонка, что услышал телефон.
Часть функции живёт вне движка (проверка пушей на ключи, тексты звонков на ноутбуке): в этом файле её нет, см. registry_proof/7.08.json.
"""
import json
from pathlib import Path

import pytest

import helpers_s6_fault as F
from helpers_spoken_diagnostics import run_host

PUBLIC = 'Какая сейчас ставка НДС?'
# (вопрос, личная примета, которой не должно быть ни в одном запросе к поиску). Всё выдумано.
PERSONAL = [
    ('Какая сейчас ставка НДС, у меня телефон 8 912 345 67 89?', '345 67 89'),
    ('Что говорится в статье 218 ГК РФ для почты ivan.test@example.org?', 'ivan.test'),
    ('Какая сейчас ставка НДС для карты 4111 1111 1111 1111?', '4111'),
    ('Какая сейчас ставка НДС для паспорта 4509 123456?', '123456'),
    ('Почему я сейчас плачу НДС?', 'я сейчас'),
    ('Сколько я должен заплатить НДС?', 'я должен'),
]


def journal(home):
    files = sorted((f for f in (Path(home) / 'logs' / 'echo_calls').glob('*.jsonl') if '.v5tap' not in f.name))
    assert len(files) == 1, files
    return [json.loads(line) for line in files[0].read_text(encoding='utf-8').splitlines()]


async def ask_and_collect(host, question):
    await host.ask(question)
    await host.advance(8)
    rows = journal(host.home)
    assert any(r.get('ev') == 'user_final' for r in rows), 'опора: звонок дошёл до конца реплики'
    return [str(query) for _, query in host.lookup_plan.calls]


def test_a_public_question_is_looked_up(tmp_path, monkeypatch):
    """Опора: без личного вопрос уходит в публичный поиск, иначе отсутствие вызова ничего не доказывает."""
    async def body(host):
        queries = await ask_and_collect(host, PUBLIC)
        assert len(queries) == 1 and 'НДС' in queries[0], queries
    run_host(tmp_path, monkeypatch, body)


@pytest.mark.parametrize('question, mark', PERSONAL)
def test_a_personal_question_never_reaches_the_public_search(tmp_path, monkeypatch, question, mark):
    async def body(host):
        queries = await ask_and_collect(host, question)
        assert all(mark not in query for query in queries), 'личное ушло в публичный поиск: %d вызов(ов)' % len(queries)
        assert not queries, 'личный вопрос не должен вызывать публичный поиск вовсе: %r' % (queries,)
        assert not any(mark in text for text in host.spoken()), 'и не должен звучать в подсказке'
    run_host(tmp_path, monkeypatch, body)


def test_the_personal_frame_is_cut_and_only_the_public_part_is_looked_up(tmp_path, monkeypatch):
    async def body(host):
        queries = await ask_and_collect(host, 'Какой курс доллара, если мой счёт открыт?')
        assert len(queries) == 1, queries
        assert 'курс доллара' in queries[0] and 'мой' not in queries[0].lower(), queries
    run_host(tmp_path, monkeypatch, body)
