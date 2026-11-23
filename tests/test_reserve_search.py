"""reserve_search: the web search has a second road when the call's own search has no cloud (the owner's order of 11.11.2026)."""
import pytest

from echo_sync import reserve_search, reserve_text
from echo_sync.controlled_media import public_sources


@pytest.fixture(autouse=True)
def _fresh():
    reserve_text._REST.clear()
    yield
    reserve_text._REST.clear()


def answer(text, output='1. Weather https://open-meteo.com/kazan today'):
    return {'choices': [{'message': {'content': text, 'executed_tools': [{'type': 'browser_search', 'output': output}]}}]}


def test_what_was_found_comes_back_as_a_row_the_call_takes_for_a_source():
    asked = []

    def post(url, headers, body, timeout):
        asked.append(body)
        return answer('В Казани облачно, около трёх градусов.【1†L3-L9】')
    rows = reserve_search.search('Какая погода в Казани', keys={'GROQ_API_KEY': 'k'}, post=post)
    assert asked[0]['tools'] == [{'type': 'browser_search'}] and asked[0]['messages'][-1]['content'] == 'Какая погода в Казани'
    assert rows[0]['url'] == 'https://open-meteo.com/kazan' and rows[0]['text'].startswith('В Казани облачно, около трёх градусов.')
    assert '【' not in rows[0]['text']
    assert public_sources(rows) and public_sources(rows)[0]['url'] == rows[0]['url']


def test_a_road_that_refuses_rests_and_the_next_one_is_asked_and_no_key_is_no_search():
    asked = []

    def post(url, headers, body, timeout):
        asked.append((headers['Authorization'][-3:], body['model']))
        if headers['Authorization'].endswith('one'):
            raise reserve_text.ReserveError('http_429')
        return answer('Найдено.', output='')
    keys = {'GROQ_API_KEY': 'one', 'GROQ_API_KEY_2': 'two'}
    rows = reserve_search.search('вопрос', keys=keys, post=post, clock=lambda: 10.0)
    assert rows[0]['url'] == reserve_search.NO_URL and [a[0] for a in asked] == ['one', 'two']
    asked.clear()
    reserve_search.search('вопрос', keys=keys, post=post, clock=lambda: 11.0)
    assert [a[0] for a in asked] == ['two']                      # the road that said no is not asked again at once
    assert reserve_search.search('вопрос', keys={}, post=post) == []


def test_an_empty_answer_of_every_road_is_no_row():
    assert reserve_search.search('вопрос', keys={'GROQ_API_KEY': 'k'}, post=lambda *a: answer('')) == []
