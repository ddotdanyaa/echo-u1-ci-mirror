"""a3-search (R10): the document and article a source is about; honest «не нашёл»; early preparation adopted by meaning, numbers and «не» protected."""
import asyncio
import pytest
from echo_sync import search_identity as si
from echo_sync.native_prefetch import EarlyLookup

Q19_NK = 'Что говорится в девятнадцатой статье Налогового кодекса'
ROW = lambda title, text='': {'url': 'https://example.org/x', 'title': title, 'text': text}


@pytest.mark.parametrize('query, row, verdict', [
    (Q19_NK, ROW('Статья 19. Налогоплательщики и плательщики сборов', 'Налоговый кодекс РФ, часть первая.'), 'match'),
    (Q19_NK, ROW('Статья 19. Права потребителя', 'Закон РФ о защите прав потребителей'), 'document'),
    (Q19_NK, ROW('Статья 19 Трудового кодекса', 'Трудовой кодекс РФ'), 'document'),
    (Q19_NK, ROW('Статья 20. Взаимозависимые лица', 'Налоговый кодекс РФ'), 'article'),
    (Q19_NK, ROW('Налоговый кодекс', 'Статья 19. Налогоплательщики. Статья 20. Взаимозависимые лица.'), 'match'),
    ('Что такое статья 19 НК РФ', ROW('Статья 19', 'Налоговый кодекс Российской Федерации'), 'match'),
    ('ст. 19 ТК РФ', ROW('Статья 19', 'Налоговый кодекс Российской Федерации'), 'document'),
    ('статья 21 Трудового кодекса', ROW('Статья 21. Основные права и обязанности работника', 'Трудовой кодекс'), 'match'),
    ('статья 21 Трудового кодекса', ROW('Статья 22. Основные права и обязанности работодателя', 'Трудовой кодекс'), 'article'),
    ('статья 19 закона о персональных данных', ROW('Статья 19', 'Федеральный закон 152-ФЗ О персональных данных'), 'match'),
    ('статья 19 закона о персональных данных', ROW('Статья 19', 'Закон о защите прав потребителей'), 'document'),
    ('статья 19 закона о персональных данных', ROW('Статья 19', 'Закон о рекламе, 38-ФЗ'), 'document'),
    ('статья 105.1 НК', ROW('Статья 105.1. Основные понятия', 'Налоговый кодекс'), 'match'),
    ('статья 105.1 НК', ROW('Статья 105. Налоговые правонарушения', 'Налоговый кодекс'), 'article'),
    (Q19_NK, ROW('Налоги и сборы', 'Общие сведения о налогах'), 'unknown'),
    (Q19_NK, ROW('Статья 19 Налогового кодекса', 'Утратила силу с 1 января 2019 года.'), 'repealed'),
    ('что такое инерция', ROW('Инерция', 'Свойство тела сохранять скорость.'), 'unknown'),
])
def test_identity_of_a_source(query, row, verdict):
    assert si.identity(query, row) == verdict


@pytest.mark.parametrize('a, b, same', [
    ('Что говорится в девятнадцатой статье Налогового кодекса', 'что в статье 19 НК РФ', True),
    ('Сколько будет 80 минус 20', 'Сколько получится 80 минус 20', True),
    ('Сколько будет восемьдесят минус двадцать', 'сколько будет 80 минус 20', True),
    ('Сколько будет 80 минус 20', 'Сколько будет 20 минус 80', False),
    ('Если у меня было 80 рублей и я потратил 20 сколько осталось', 'Если у меня было 20 рублей и я потратил 80 сколько осталось', False),
    ('нужно не нагревать а охлаждать жидкость', 'нужно нагревать а не охлаждать жидкость', False),
    ('нужно не нагревать а охлаждать жидкость', 'нужно охлаждать а не нагревать жидкость', True),
    ('нужно нагревать жидкость', 'нужно не нагревать жидкость', False),
    ('Статья 19 Налогового кодекса', 'Статья 19 Трудового кодекса', False),
    ('Что такое инерция', 'ну скажи что такое инерция', True),
    ('Что такое инерция тела', 'Что такое инерция', False),
    ('Какая сейчас ключевая ставка', 'какая ключевая ставка сейчас', True),
    ('какая ставка НДС', 'какая ставка налога', False),
    ('Кто написал Войну и мир', 'Кто написал Войну и мир', True),
    ('Кто написал Войну и мир', 'Кто написал Анну Каренину', False),
])
def test_same_meaning_with_numbers_and_negation_protected(a, b, same):
    assert si.same_meaning(a, b) is same


def test_prefetch_is_adopted_for_a_paraphrase_and_refused_for_other_numbers():
    async def run():
        calls = []
        async def fetch(q): calls.append(q); return [{'text': q}]
        async def trace(*a, **k): pass
        e = EarlyLookup(fetch, trace, enabled=True)      # E87.1: adoption by meaning is the rule of the early lookup
        e.observe('u', 'Что говорится в девятнадцатой статье Налогового кодекса', now=0); await e.tick(now=1); await asyncio.sleep(0)
        assert await e.resolve('u', 'что в статье 19 НК РФ?') == [{'text': 'Что говорится в девятнадцатой статье Налогового кодекса'}] and len(calls) == 1
        e2 = EarlyLookup(fetch, trace, enabled=True)
        e2.observe('u', 'Что говорится в девятнадцатой статье Налогового кодекса', now=0); await e2.tick(now=1); await asyncio.sleep(0)
        await e2.resolve('u', 'что в статье 20 НК РФ?'); assert len(calls) == 3
        await e.close(); await e2.close()
    asyncio.run(run())


# --- A3-1: ControlledMedia._relevant (coordinator's file) ignores the code and article a row is about ---------------------------------------
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import helpers_s6_state as S


def _relevant(query, rows):
    world = S.World()
    try:
        c = world.controller
        c.question_id, c.lookup_query = 'u1', query
        return c._relevant(rows)
    finally:
        world.close()


def test_relevant_drops_the_same_article_of_another_law():
    rows = [{'url': 'https://example.org/z', 'title': 'Статья 19. Права потребителя', 'text': 'Закон о защите прав потребителей: статья 19 устанавливает налоговые права потребителя.'}]
    assert _relevant('Что говорится в девятнадцатой статье Налогового кодекса', rows) == []


def test_relevant_keeps_the_row_of_the_right_code():
    rows = [{'url': 'https://example.org/z', 'title': 'Статья 19. Налогоплательщики', 'text': 'Налоговый кодекс: налогоплательщиками признаются организации и физические лица.'}]
    assert _relevant('Что говорится в девятнадцатой статье Налогового кодекса', rows) == rows
