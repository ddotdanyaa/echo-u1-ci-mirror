"""Реестр 4.06 «Поиск в интернете и локальных базах»: вопрос о меняющемся или названном по номеру уходит в поиск, найденный источник доходит до ответа, чужая статья и личные данные
в поиск и ответ не попадают, без источника человеку честно говорят «Не нашёл», запасная дорога (Groq browser_search) отвечает, когда поиск облака молчит.
Граница: поиск облака (host.search_module), сеть запасной дороги (httpx.Client); ключи запасной дороги и чистое состояние дорог даёт стенд (roads=); модель сценарная и пересказывает только то, что пришло ей источником.
Ключа reserve_text больше нет (запасная дорога поиска всегда включена, без ключей в файле она пуста); остальные тесты ловит плагин вне репозитория (public_lookup_allowed, search_identity.identity)."""
import re

import _h4 as H

FACT = 'Высота озера Ненунга над уровнем моря составляет 3812 метров.'
FRESH = 'Найди в интернете, на какой высоте лежит озеро Ненунга?'
ARTICLE = 'Что говорит статья 310 Гражданского кодекса?'
GK310 = {'url': 'https://example.org/gk310', 'title': 'Статья 310 Гражданского кодекса', 'text': 'Статья 310 Гражданского кодекса: односторонний отказ от обязательства не допускается.'}
GK311 = {'url': 'https://example.org/gk311', 'title': 'Статья 311 Гражданского кодекса', 'text': 'Статья 311 Гражданского кодекса: обязательство исполняется по частям, если стороны договорились.'}

TK310 = {'url': 'https://example.org/tk310', 'title': 'Статья 310 Трудового кодекса', 'text': 'Статья 310 Трудового кодекса: работодатель ведёт учёт рабочего времени надомников.'}


class Search:
    """Поиск облака (api quick lookup): запоминает вопросы, отдаёт заготовленные строки или заготовленный ответ-отказ."""
    def __init__(self, rows): self.rows, self.asked = rows, []

    def search(self, question, limit, home, timeout=None, force_refresh=False):
        self.asked.append(question)
        return self.rows if isinstance(self.rows, dict) else {'success': True, 'data': {'web': self.rows}}


def retell(question, request):
    """Модель суфлёра: говорит только текст источника из запроса; нет источника в запросе, значит «по памяти»."""
    found = re.search(r'"text": "(.*?)(?:\\n|")', ' '.join(c['text'] for m in request['input'] for c in m['content']))
    return found.group(1) if found else 'Источника нет, отвечаю по памяти.'


def call(tmp_path, monkeypatch, question, rows, roads=None):
    """Один звонок: человек задаёт вопрос, 4 с звонка. Возвращает (поиск, модель, подсказки, журнал)."""
    search, model = Search(rows), H.Model(retell)

    async def body(host):
        host.search_module = search
        await H.say(host, question)
        await host.advance(4)
        return host.spoken(), H.journal(host)
    spoken, rows_ = H.play(tmp_path, monkeypatch, body, model=model, roads=roads)
    return search, model, spoken, rows_


def asked_text(model):
    return ' '.join(c['text'] for item in model.requests for m in item.request['input'] for c in m['content'])


def test_a_fresh_question_is_searched_and_the_found_source_becomes_the_cue(tmp_path, monkeypatch):
    search, model, spoken, rows = call(tmp_path, monkeypatch, FRESH, [{'url': 'https://example.org/lake', 'text': FACT}])
    assert search.asked == [FRESH], 'the question went to the search once'
    assert FACT in asked_text(model) and 'https://example.org/lake' in asked_text(model), 'the found source reached the model'
    assert spoken and spoken[0] == FACT, spoken
    assert ('answer', 'fast_text_owns') in H.decisions(rows)


def test_a_row_of_another_article_is_no_source_and_the_matching_row_is(tmp_path, monkeypatch):
    search, model, spoken, rows = call(tmp_path, monkeypatch, ARTICLE, [GK311, TK310])
    assert search.asked == [ARTICLE]
    assert 'Статья 311' not in asked_text(model) and 'Трудового' not in asked_text(model) + ' '.join(spoken), (asked_text(model), spoken)   # чужая статья и чужой кодекс
    assert ('lookup', 'sources_unrelated') in H.decisions(rows)
    _, model, spoken, rows = call(tmp_path / 'again', monkeypatch, ARTICLE, [TK310, GK311, GK310])           # контроль: с верной строкой та же дорога даёт ответ
    assert 'Гражданского кодекса: односторонний' in asked_text(model) and 'Статья 311' not in asked_text(model) and 'Трудового' not in asked_text(model)
    assert 'односторонний отказ' in spoken[0] and 'Трудового' not in ' '.join(spoken), spoken


def test_no_source_for_changing_data_is_an_honest_not_found_and_the_model_is_not_asked(tmp_path, monkeypatch):
    search, model, spoken, rows = call(tmp_path, monkeypatch, 'Найди в интернете, какой сегодня курс норвежской кроны?', [])
    assert len(search.asked) == 1 and model.questions() == [], 'searched, nothing found, no invented number'
    assert spoken[0].startswith('Не нашёл'), spoken
    assert ('lookup', 'no_source_current_data') in H.decisions(rows)


def test_a_question_with_a_private_number_is_not_sent_to_the_search(tmp_path, monkeypatch):
    private = 'Найди в интернете, чей это номер телефона 8 912 555 01 23?'
    search, model, spoken, rows = call(tmp_path, monkeypatch, private, [{'url': 'https://example.org/x', 'text': 'Номер принадлежит выдуманной фирме Ромашка-Север.'}])
    assert search.asked == [], 'the private question never left for the search'
    assert 'Ромашка' not in ' '.join(spoken) + asked_text(model)
    assert ('lookup', 'no_search_from_memory') in H.decisions(rows)


def test_when_the_cloud_search_is_down_the_reserve_road_searches_the_web(tmp_path, monkeypatch):
    posted = []

    class Reply:
        status_code = 200
        def json(self): return {'choices': [{'message': {'content': FACT + '【1†L1】', 'executed_tools': [{'type': 'browser_search', 'output': '1. Lake https://example.org/lake'}]}}]}

    class Client:                                          # httpx.Client на границе сети: ни одного настоящего запроса
        def __init__(self, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def post(self, url, headers=None, json=None): posted.append(json); return Reply()
    monkeypatch.setattr('httpx.Client', Client)
    search, model, spoken, rows = call(tmp_path, monkeypatch, FRESH, {'success': False, 'error': 'down'}, {'GROQ_API_KEY': 'placeholder-not-a-key'})      # ключ-пустышка и чистое состояние дорог даёт стенд
    assert search.asked == [FRESH] and len(posted) == 1, 'the cloud search was asked first, then the reserve road once'
    assert posted[0]['tools'] == [{'type': 'browser_search'}] and posted[0]['messages'][-1]['content'] == FRESH
    assert FACT in asked_text(model) and '【' not in asked_text(model) and spoken[0] == FACT, spoken
