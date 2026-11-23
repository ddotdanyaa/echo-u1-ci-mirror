"""S1 (STRIX): the reserve roads (Groq, Gemini) are public third parties. What leaves for them passes the ONE gate of the public lookup (``privacy_gate.allowed(text, search=True)``) in the one place that posts
(``ReserveStream._talk``): a heard question that is not public is not sent (and no road is rested for it), the contact data of the owner's material (e-mail, phone, card, document number) is cut out and the lecture stays, an earlier exchange whose question is not public
is left out, and a gate that fails sends nothing. First through the REAL host (``controlled_host.serve``, ``ControlledMedia``) with only the network of the roads faked, then through ``ReserveStream`` alone."""
import json
import threading

import pytest

from echo_sync import brain_short, content_policy, fast_text, privacy_gate, reserve_text
from echo_sync.reserve_text import ReserveStream, Roads
from helpers_always_answer import Stand, fail, ok, run_stand

CANARY = 'КАНАРЕЙКА-МАТЕРИАЛА-7391'
PERSONAL, PUBLIC = 'Какой у меня пароль от почты?', 'Что такое инерция?'
KEYS = {'GROQ_API_KEY': 'one'}


class Wire(Stand):
    """The stand that also keeps what each reserve road was sent (the whole body as text)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sent = []

    def _post(self, url, headers, body, timeout):
        self.sent.append(json.dumps(body, ensure_ascii=False))
        yield from super()._post(url, headers, body, timeout)


@pytest.fixture(autouse=True)
def _fresh():
    for table in (reserve_text._REST, reserve_text._BUDGET):
        table.clear()
    reserve_text._PRIMARY['until'] = 0.0
    yield
    for table in (reserve_text._REST, reserve_text._BUDGET):
        table.clear()
    reserve_text._PRIMARY['until'] = 0.0


def test_through_the_host_a_personal_question_is_not_sent_to_the_reserve_and_a_public_one_goes_with_the_lecture_but_without_its_contact_data(tmp_path):
    stand = Wire({'codex': fail('http_429'), 'groq1': ok()})

    async def body(host, stand):
        folder = host.home / 'materials'
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'context.md').write_text(f'# Лекция\n\nПланета Тирра обходит звезду за 412 суток. {CANARY}\n\nЗвоните лектору +7 912 345 67 89.\n', encoding='utf-8')
        await host.handshake()
        first = await stand.ask(host, PERSONAL, uid='u1', lag=0.2)
        await host.advance(12.0)
        sent_after_personal = list(stand.sent)
        await stand.ask(host, PUBLIC, uid='u2', lag=0.2)
        await host.advance(12.0)
        return first, sent_after_personal

    first, after_personal = run_stand(tmp_path, stand, body, handshake=False)
    if not [alias for at, alias in stand.calls if alias == 'codex']:
        raise RuntimeError('the scenario did not reach its premise: the first road was never asked')
    assert after_personal == [], 'a question of the listener\'s own affairs was sent to a public reserve host'
    assert len(stand.sent) == 1 and 'инерция' in stand.sent[0], stand.sent      # the public question goes
    assert CANARY in stand.sent[0] and '412 суток' in stand.sent[0]      # the lecture is what the reserve answers from (nothing marks it closed)\n    assert '912 345' not in stand.sent[0]      # a phone in the material goes nowhere


def instructions(history=()):
    context = content_policy.CallContext(subject='физика', excerpt=f'Материал. {CANARY}.\n\nПишите на lektor@example.org.', material_sha256='a' * 64, material_chars=40)
    return fast_text.build_request(PUBLIC, instructions=content_policy.build_instructions(context, fast_text.BRAIN_POLICY), history=list(history))


def talk(request, sent):
    def post(url, headers, body, timeout):
        sent.append(body)
        yield 'data: ' + json.dumps({'choices': [{'delta': {'content': 'Ответ.'}}]})
        yield 'data: [DONE]'
    stream = ReserveStream(KEYS, post=post)
    return stream, ''.join(piece for piece in Roads(None, stream)(request, threading.Event()) if isinstance(piece, str))


def test_contact_data_of_the_material_and_a_personal_exchange_of_the_history_never_leave_and_the_rest_does():
    history = [{'question': 'Какой у меня номер счёта?', 'answer': 'Не знаю ваш номер.'}, {'question': 'Когда была Полтавская битва?', 'answer': 'В 1709 году.'}]
    request = instructions(history)
    assert CANARY in request['instructions'] and 'Какой у меня номер счёта?' in request['instructions']      # the premise: both are in what the job reads
    sent = []
    _, said = talk(request, sent)
    assert said == 'Ответ.' and len(sent) == 1
    system = sent[0]['messages'][0]['content']
    assert CANARY in system and content_policy.DATA_NOTICE in system and 'Предмет занятия' in system      # the lecture and the owner's lines stay\n    assert 'lektor@example.org' not in system
    assert 'Какой у меня номер счёта?' not in system and 'Не знаю ваш номер' not in system
    assert 'Когда была Полтавская битва?' in system and 'В 1709 году.' in system      # the public exchange stays
    assert brain_short.SHORT_POLICY[:40] in system      # the rules of the answer stay


def test_a_personal_question_asks_no_reserve_road_and_rests_none():
    sent = []
    request = fast_text.build_request(PERSONAL, instructions='Ты суфлёр.')
    stream = ReserveStream(KEYS, post=lambda *a: sent.append(a) or iter(()))
    assert reserve_text.withheld(request) and stream._order(request) == []
    with pytest.raises(reserve_text.ReserveError):
        ''.join(Roads(None, stream)(request, threading.Event()))
    assert sent == [] and not reserve_text._REST      # nothing asked, no road rested for a question that was never sent


def test_a_gate_that_fails_sends_nothing(monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError('boom')
    monkeypatch.setattr(privacy_gate, 'allowed', broken)
    reserve_text._public.cache_clear()
    sent = []
    stream = ReserveStream(KEYS, post=lambda *a: sent.append(a) or iter(()))
    body = reserve_text.chat_body(fast_text.build_request(PUBLIC, instructions='Ты суфлёр.'), 'openai/gpt-oss-120b')
    assert list(stream._talk('GROQ_API_KEY', reserve_text.GROQ, 'openai/gpt-oss-120b', body, threading.Event())) == [] and sent == []
    reserve_text._public.cache_clear()


def test_a_material_marker_left_after_the_cut_holds_the_request_back():
    sent = []
    system = 'Правила. ⟦МАТЕРИАЛЫ aaaaaaaaaaaa — не закрыт'      # a block the cut cannot find the end of
    body = {'model': 'm', 'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': PUBLIC}], 'max_tokens': 10}
    stream = ReserveStream(KEYS, post=lambda *a: sent.append(a) or iter(()))
    assert list(stream._talk('GROQ_API_KEY', reserve_text.GROQ, 'm', body, threading.Event())) == [] and sent == []


@pytest.mark.parametrize('part', ['Мой email: ivan@x.ru', 'Звоните: +7 495 123-45-67', 'Счёт 40817810099910004312 в банке', 'Паспорт 4510 123456'])
def test_contact_data_in_a_first_person_part_of_the_material_is_cut_by_the_real_gate(part):
    # S5: the contact shapes cut a part of the material independent of the first person; nothing is patched in privacy_gate
    assert reserve_text._contact_free(part) is False
    assert reserve_text._contact_free('Инерция - свойство тел сохранять скорость.') is True
