"""S5 of ARCH_ONE (the family R, ``reserve_text.Roads``): a model source is ONE ROW of ``reserve_text.ROADS`` (key name, base url, model) and its key. A toy road added that way answers through the REAL host
(``controlled_host.serve``, ``ControlledMedia``, ``fast_text.for_call``, ``Roads``) when the first road and every road before it have failed, with no line of the walk, of the channel or of the controller edited.
The control: the same key with no row asks nobody and the question is answered by the phrase of the system, so the test sees the row and not the stand."""
import helpers_always_answer as H
from helpers_always_answer import Stand, fail, heard, ok, run_stand
from echo_sync import reserve_text

TOY = ('TOY_KEY', 'https://toy.invalid/v1', 'toy-model')
TOY_ANSWER = 'Тестовая дорога отвечает: инерция сохраняет скорость тела.'
QUESTION = 'Что такое инерция?'


def play(tmp_path, monkeypatch, *, rows):
    monkeypatch.setitem(H.KEYS, 'TOY_KEY', 'toy-secret')
    monkeypatch.setitem(H.ALIASES, ('TOY_KEY', 'toy-model'), 'toy')
    monkeypatch.setattr(reserve_text, 'ROADS', reserve_text.ROADS + rows)
    stand = Stand({'codex': fail('http_429'), 'toy': ok(TOY_ANSWER)}, default=fail('http_429'))

    async def body(host, stand):
        t_q = await stand.ask(host, QUESTION, cloud=True, lag=0.2)
        await host.advance(7.0)
        return heard(host, t_q), [alias for _, alias in stand.calls]
    return run_stand(tmp_path, stand, body)


def test_a_toy_road_row_answers_through_the_real_host_without_editing_the_core(tmp_path, monkeypatch):
    saw, asked = play(tmp_path, monkeypatch, rows=(TOY,))
    assert 'toy' in asked, asked
    said = ' '.join(str(item['text']) for item in saw['answers'])
    assert 'Тестовая дорога отвечает' in said, (said, asked)
    assert not saw['service'], [item['text'] for item in saw['service']]


def test_the_same_key_without_its_row_asks_nobody_and_the_phrase_of_the_system_is_said(tmp_path, monkeypatch):
    saw, asked = play(tmp_path, monkeypatch, rows=())
    assert 'toy' not in asked, asked
    assert not any('Тестовая дорога' in str(item['text']) for item in saw['answers'])
