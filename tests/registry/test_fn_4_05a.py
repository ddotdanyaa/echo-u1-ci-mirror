"""Реестр 4.05a «Запасные дороги моделей» (одна дорога: Roads всегда, ключа reserve_text больше нет): когда первая дорога (Codex) отказывает до первого слова, то же задание идёт по запасным дорогам, и человек получает подсказку.
Граница: ключи лежат файлом (H.play roads=, выдуманные значения), сеть подменена на httpx.Client; Codex это Model стенда (исключение = отказ). Судим по подсказкам, журналу и тому, что ушло в сеть.
Состояние дорог (отказы, покой Codex) помощник делает чистым в каждом звонке, поэтому тесты от порядка и соседей не зависят."""
import json
import _h4 as H

QUESTION = 'Как называется самая длинная река Южной Америки?'
ANSWER = 'Самая длинная река Южной Америки — Амазонка. Она впадает в Атлантический океан.'
NO_ANSWER = 'Нет ответа. Повторите вопрос.'
HOSTS = {'groq': 'api.groq.com', 'gemini': 'generativelanguage.googleapis.com', 'openrouter': 'openrouter.ai'}


class Net:
    """Сеть на границе (httpx.Client): plan = {(имя ключа, модель или None): текст ответа | код отказа}; ключ в файле = его имя (значение выдумано). seen: (имя ключа, адрес, модель, последний вопрос в запросе)."""

    def __init__(self, plan): self.plan, self.seen = plan, []

    def client(self, **_):
        net = self

        class Response:
            def __init__(self, status, text): self.status_code, self.headers, self.text = status, {}, text
            def read(self): return b'{}'
            def iter_lines(self):
                yield 'data: ' + json.dumps({'choices': [{'delta': {'content': self.text}}]})
                yield 'data: [DONE]'

        class Stream:
            def __init__(self, url, headers, body):
                key = headers['Authorization'].split()[-1]
                net.seen.append((key, url, body['model'], body['messages'][-1]['content']))
                plan = net.plan.get((key, body['model']), net.plan.get((key, None), 503))
                self.response = Response(plan if isinstance(plan, int) else 200, '' if isinstance(plan, int) else plan)
            def __enter__(self): return self.response
            def __exit__(self, *_): return False

        class Client:
            def __init__(self, **_): pass
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def stream(self, method, url, headers=None, json=None): return Stream(url, headers, json)
        return Client

    def hosts(self): return [next(n for n, h in HOSTS.items() if h in url) for _, url, _, _ in self.seen]


def call(tmp_path, monkeypatch, keys, plan, codex, questions=(QUESTION,)):
    net, model = Net(plan), H.Model(codex)
    monkeypatch.setattr('httpx.Client', net.client())

    async def body(host):
        for question in questions:
            await H.say(host, question)
            await host.advance(3)
        return H.journal(host), host.spoken()
    rows, spoken = H.play(tmp_path, monkeypatch, body, model=model, roads={name: name for name in keys})      # ключи файлом и чистое состояние дорог даёт помощник
    return net, model, rows, spoken


def refuses(question, request):
    raise RuntimeError('Codex quota: HTTP 429')


def test_control_codex_answers_and_the_reserve_is_not_asked(tmp_path, monkeypatch):
    net, model, rows, spoken = call(tmp_path, monkeypatch, ['GROQ_API_KEY'], {('GROQ_API_KEY', None): 'Резерв.'}, {'река': ANSWER})
    assert 'Амазонка' in spoken[0] and net.seen == [] and model.questions() == [QUESTION]


def test_codex_refuses_and_the_question_is_answered_by_the_reserve_and_codex_then_rests(tmp_path, monkeypatch):
    second = 'Какой океан самый маленький по площади?'
    net, model, rows, spoken = call(tmp_path, monkeypatch, ['GROQ_API_KEY'], {('GROQ_API_KEY', None): ANSWER}, refuses, (QUESTION, second))
    assert 'Амазонка' in spoken[0], spoken
    assert NO_ANSWER not in spoken and ('answer', 'fast_text_owns') in H.decisions(rows), H.decisions(rows)
    assert net.hosts() == ['groq', 'groq'] and QUESTION in net.seen[0][3] and second in net.seen[1][3], net.seen
    assert model.questions() == [QUESTION], 'a refused Codex is not asked again at once: %s' % model.questions()


def test_a_road_that_refuses_is_followed_by_the_next_and_gemini_comes_after_groq(tmp_path, monkeypatch):
    plan = {('GROQ_API_KEY_2', None): 429, ('GEMINI_API_KEY', None): ANSWER}
    net, model, rows, spoken = call(tmp_path, monkeypatch, ['GROQ_API_KEY_2', 'GEMINI_API_KEY'], plan, refuses)
    assert 'Амазонка' in spoken[0] and NO_ANSWER not in spoken, spoken
    assert net.hosts() == ['groq', 'groq', 'gemini'], net.seen
    assert all(QUESTION in item[3] for item in net.seen)


def test_every_road_refuses_and_the_job_fails_and_no_other_provider_is_asked(tmp_path, monkeypatch):
    plan = {('GEMINI_API_KEY_2', None): 403, ('OPENROUTER_API_KEY', None): ANSWER}      # OpenRouter ответил бы, но дорогой в ветке не является
    net, model, rows, spoken = call(tmp_path, monkeypatch, ['GEMINI_API_KEY_2', 'OPENROUTER_API_KEY'], plan, refuses)
    assert not any('Амазонка' in cue for cue in spoken), spoken
    assert ('answer', 'fast_text_failed_asked_again') in H.decisions(rows) and ('answer', 'fast_text_failed_handed_back') in H.decisions(rows), H.decisions(rows)
    assert 'openrouter' not in net.hosts() and set(net.hosts()) == {'gemini'}, net.seen
