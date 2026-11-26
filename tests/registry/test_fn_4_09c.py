"""Реестр 4.09c «Оговорка «по памяти», дата проверки, стабильное против текущего»: НЕ СДЕЛАНО. Человек должен знать, где ответу можно верить как факту: ответ без источника несёт оговорку
(«По памяти: ...»), ответ по найденному источнику называет дату проверки. Граница: поиск облака (host.search_module) и сценарная модель; модель сама начинает ответ с оговорки «По памяти:».
Целевые тесты (xfail): оговорка пропадает из подсказки, даты проверки нет. Контроли (зелёные): оговорка своими словами модели (не «По памяти:») доходит до человека; изменчивое без источника честно «Не нашёл», а не ответ по памяти."""
import re

import pytest

import _h4 as H

STABLE = 'Что сказано в статье 214 Гражданского кодекса об аренде?'
CHANGING = 'Найди в интернете, какой сегодня курс валюты острова Тарвал?'
HEDGED = 'По памяти: статья 214 велит платить за пользование чужим имуществом.'
OWN_WORDS = 'Без проверки статья 214 велит платить за пользование чужим имуществом.'
SOURCE = {'url': 'https://example.org/gk214', 'title': 'Статья 214', 'text': 'Статья 214 велит платить за пользование чужим имуществом.'}
CAVEAT = re.compile(r'по памяти|без проверки|насколько (?:я )?помню|не проверен', re.I)
CHECKED = re.compile(r'проверено|по состоянию на|на дату проверки|актуально на', re.I)


class Search:
    """Поиск облака: запоминает вопросы и отдаёт заготовленные строки (пусто: источника нет)."""
    def __init__(self, rows): self.rows, self.asked = rows, []

    def search(self, question, limit, home, timeout=None, force_refresh=False):
        self.asked.append(question)
        return {'success': True, 'data': {'web': self.rows}}


def call(tmp_path, monkeypatch, question, answer, rows):
    """Один звонок: вопрос, 4 с звонка. Возвращает (поиск, модель, подсказки, журнал)."""
    search, model = Search(rows), H.Model(lambda q, request: answer)

    async def body(host):
        host.search_module = search
        await H.say(host, question)
        await host.advance(4)
        return host.spoken(), H.journal(host)
    spoken, rows_ = H.play(tmp_path, monkeypatch, body, model=model)
    return search, model, spoken, rows_


def no_source_from_memory(tmp_path, monkeypatch, answer):
    search, model, spoken, rows = call(tmp_path, monkeypatch, STABLE, answer, [])
    assert search.asked == [STABLE] and model.questions() == [STABLE], 'the search found nothing, the model was asked'
    assert ('lookup', 'no_source_from_memory') in H.decisions(rows), H.decisions(rows)      # условие реестра: ответ без источника, из памяти
    assert spoken and 'статья 214' in spoken[0].casefold(), spoken
    return spoken


@pytest.mark.xfail(strict=True, raises=AssertionError, reason='реестр 4.09c: НЕ СДЕЛАНО, ответ по памяти звучит как факт, оговорка срезается')
def test_an_answer_from_memory_without_a_source_carries_a_caveat(tmp_path, monkeypatch):
    spoken = no_source_from_memory(tmp_path, monkeypatch, HEDGED)
    assert CAVEAT.search(spoken[0]), 'the person is told this is from memory, not a fact: %r' % spoken[0]


def test_control_a_caveat_inside_the_answer_reaches_the_person(tmp_path, monkeypatch):
    spoken = no_source_from_memory(tmp_path, monkeypatch, OWN_WORDS)      # то же условие, оговорка другими словами: срезать нечего
    assert CAVEAT.search(spoken[0]), spoken[0]


@pytest.mark.xfail(strict=True, raises=AssertionError, reason='реестр 4.09c: НЕ СДЕЛАНО, даты проверки в ответе по источнику нет (U80)')
def test_an_answer_by_a_found_source_names_the_date_it_was_checked(tmp_path, monkeypatch):
    search, model, spoken, rows = call(tmp_path, monkeypatch, STABLE, SOURCE['text'], [SOURCE])
    assert search.asked == [STABLE] and 'статья 214' in spoken[0].casefold(), (search.asked, spoken)      # источник дошёл до ответа
    assert 'example.org/gk214' in str(model.requests[0].request), 'the found source reached the model'
    assert CHECKED.search(' '.join(spoken)), 'the answer says when it was checked: %r' % spoken[0]


def test_control_changing_data_without_a_source_is_not_found_not_a_memory_answer(tmp_path, monkeypatch):
    search, model, spoken, rows = call(tmp_path, monkeypatch, CHANGING, 'Курс острова Тарвал сейчас равен трём.', [])
    assert model.questions() == [] and spoken[0].startswith('Не нашёл'), (model.questions(), spoken)
    assert ('lookup', 'no_source_current_data') in H.decisions(rows)
