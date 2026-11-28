"""U113: the function count of the registry follows its stated rule. Fixture only; no network."""
import json

from tools import function_count as F

FIXTURE = """# Реестр

## Сводка (5 функций)

1. Всего функций: **5** в двух секциях.

## Выключено или в тени, хотя владелец требовал довнедрить

| № | Функция | Состояние | Что требовал |
|---|---|---|---|
| 1.02 | Ухо | ВЫКЛЮЧЕНО | не считать второй раз |

## 1. Вход

| № | Функция | Где | Состояние | Чем доказано |
|---|---|---|---|---|
| 1.01 | Слушать | a.py | СЛОМАНО | звонок |
| 1.02 | Ухо | b.py | РАБОТАЕТ НА СЕРВЕРЕ (подтверждено на сервере 13.11: звонок или выкладка) — `k` ВЫКЛЮЧЕНО | звонок |
| 1.03 | Длинная речь | c.py | ТОЛЬКО В ВЕТКЕ — ветка x | тест |

## 2. Понимание

| № | Функция | Где | Состояние | Чем доказано |
|---|---|---|---|---|
| 2.01 | Судья | d.py | В ТЕНИ — judge_guard выключен | тест |
| 2.02a | Числа | e.py | РАБОТАЕТ НА СЕРВЕРЕ (проверено тестом или пробой, на телефоне не проверено) | тест |
| 2.03 | Что-то | f.py | ЧТО-ТО НОВОЕ | — |

## Приложение А. Ключи

| № | Функция | Состояние |
|---|---|---|
| 9.99 | не функция | РАБОТАЕТ |
"""


def test_counts_rows_of_section_tables_once_by_status_group():
    got = F.count(FIXTURE)
    assert got['total'] == 6 and got['duplicate_ids'] == 0      # the cross-table row 1.02 and the appendix row 9.99 are not counted
    assert (got['works'], got['tried'], got['in_branch']) == (2, 2, 1)
    assert got['by_status'] == {'В ТЕНИ': 1, 'РАБОТАЕТ': 2, 'СЛОМАНО': 1, 'ТОЛЬКО В ВЕТКЕ': 1}      # words after « — » do not change the status
    assert got['confirmed'] == 1      # only the row that names the server call or the deploy


def test_an_unknown_status_is_unmarked_not_guessed_and_the_summary_is_checked():
    got = F.count(FIXTURE)
    assert got['unmarked'] == 1 and got['works'] + got['tried'] + got['in_branch'] + got['unmarked'] == got['total']
    assert got['summary_total'] == 5 and got['summary_agrees'] is False      # the registry's own sum does not match its rows: the tool says so
    assert (got['target_x2'], got['target_x4']) == (12, 24)


def test_main_prints_one_json_line(tmp_path, capsys):
    path = tmp_path / 'registry.md'
    path.write_text(FIXTURE, encoding='utf-8')
    F.main([str(path), '--date', '2026-11-14'])
    out = capsys.readouterr().out
    assert out.count('\n') == 1
    data = json.loads(out)
    assert data['source'] == 'registry.md' and data['counted_on'] == '2026-11-14' and data['total'] == 6
