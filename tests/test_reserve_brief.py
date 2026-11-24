"""The brief (always, no key): the instructions of a job in their short form for the reserve roads (their minute is 8 000 tokens): the short BRAIN for the long one and, of the
owner's material, the parts nearest to the question. Every rule stays (``brain_short.KEEP``), the owner's lines and the history stay."""
import json
import re
import threading

import pytest

from echo_sync import brain_short, content_policy, fast_text, material_pick, reserve_text, settings
from echo_sync.reserve_text import ReserveStream

QUESTION = 'Когда была Полтавская битва?'
FILL = 'Это предложение стоит здесь для объёма и не говорит ни о чём важном. '
BODY = '\n\n'.join([      # three parts speak of the battle, one answers; each is about 930 characters, so the job's pick (2 500) holds two and the brief (1 500) one
    '## Рекрутская повинность\nРекрутскую повинность Пётр I ввёл в 1705 году, за четыре года до Полтавской битвы. ' + FILL * 12,
    '## Полтава\nПолтавская битва была 27 июня 1709 года: в Полтавской битве русская армия разбила шведов Карла XII. ' + FILL * 12,
    '## Флот\nГангутское сражение 1714 года, уже после Полтавской битвы, стало первой морской победой флота. ' + FILL * 12,
    '## Устав\nВоинский устав принят в 1716 году. ' + FILL * 12,
])


@pytest.fixture(autouse=True)
def _fresh():
    for table in (reserve_text._REST, reserve_text._BUDGET):
        table.clear()
    yield
    for table in (reserve_text._REST, reserve_text._BUDGET):
        table.clear()


def instructions(question=QUESTION, body=BODY, cap=material_pick.JOB_MATERIAL_CHARS):
    """What the host gives a job with ``material_pick`` on: the long BRAIN, the owner's lines, the parts picked for the question."""
    context = content_policy.CallContext(subject='история — доклад о Петре I', style='простыми словами')
    return material_pick.for_job(body, cap=cap).instructions_and_pick(question, (), context, fast_text.BRAIN_POLICY)[0]


def shown(text):
    """``(what the header says is shown, the material between its marks)``."""
    found = re.search(r'⟦МАТЕРИАЛЫ ([0-9a-f]{12}) — (.*?)\. ' + re.escape(content_policy.MATERIAL_HOW) + r'⟧\n(.*?)\n⟦КОНЕЦ МАТЕРИАЛОВ \1⟧', text, re.S)
    assert found, 'the material block has lost a mark'
    return found.group(2), found.group(3)


def sse(*texts):
    return [f'data: {json.dumps({"choices": [{"delta": {"content": t}}]})}' for t in texts] + ['data: [DONE]']


def test_the_brief_has_the_short_brain_and_every_rule_of_the_long_one():
    long = instructions()
    brief = brain_short.brief_instructions(long, QUESTION)
    assert fast_text.BRAIN not in brief and brain_short.BRAIN_SHORT in brief and fast_text.BRAIN_KEEP in brief
    assert brain_short.missing(brief) == []
    assert len(brief) < len(long)


def test_of_the_material_the_brief_shows_the_part_nearest_to_the_question_within_its_cap():
    long = instructions()
    assert len(shown(long)[1]) > brain_short.MATERIAL_BRIEF_CHARS and len(re.findall(r'(?m)^## ', shown(long)[1])) == 2      # the job's own pick is bigger: two parts
    how, material = shown(brain_short.brief_instructions(long, QUESTION))
    assert len(material) <= brain_short.MATERIAL_BRIEF_CHARS
    assert '27 июня 1709 года' in material and material.startswith('## Полтава')      # the part that answers, whole, with its heading
    assert not any(year in material for year in ('1705', '1714', '1716'))
    assert f'{len(material)} из {len(BODY.strip())} знаков' in how      # the header tells what is shown now


def test_a_part_bigger_than_the_cap_is_cut_at_a_boundary_and_not_dropped():
    long = instructions(cap=4000)
    how, material = shown(brain_short.brief_instructions(long, QUESTION, material_chars=400))
    assert len(material) <= 400 and material.startswith('## Полтава') and '1709' in material
    assert material.endswith('.') and f'{len(material)} из ' in how


def test_what_is_neither_the_brain_nor_the_material_stays_as_it_came():
    request = fast_text.build_request(QUESTION, instructions=instructions(), history=[{'question': 'Кто победил под Нарвой?', 'answer': 'Шведы, в 1700 году.'}])
    brief = brain_short.brief_instructions(request['instructions'], QUESTION)
    for kept in (content_policy.DATA_NOTICE, 'Предмет занятия: история — доклад о Петре I', 'Пожелание к стилю: простыми словами', content_policy.MATERIAL_HOW, content_policy.CLOSING,
                 'Последние реплики этого разговора (для связи с вопросом):\nВопрос: Кто победил под Нарвой?\nОтвет: Шведы, в 1700 году.'):
        assert kept in brief
    assert brief.index(content_policy.DATA_NOTICE) < brief.index('⟦МАТЕРИАЛЫ') < brief.index(content_policy.CLOSING) < brief.index('Последние реплики')


def test_a_text_with_nothing_to_shorten_is_returned_as_it_came():
    assert brain_short.brief_instructions('Ты суфлёр.', QUESTION) == 'Ты суфлёр.'
    assert brain_short.brief_instructions(fast_text.BRAIN_POLICY, QUESTION) == brain_short.SHORT_POLICY
    small = instructions(body='## Полтава\nПолтавская битва была 27 июня 1709 года.')
    assert shown(brain_short.brief_instructions(small, QUESTION)) == shown(small)      # a material within the cap is not touched, nor is its header


def test_a_question_that_names_nothing_of_the_material_keeps_its_first_parts():
    long = instructions('Сколько будет пять на пять?')
    how, material = shown(brain_short.brief_instructions(long, 'Сколько будет пять на пять?'))
    assert 0 < len(material) <= brain_short.MATERIAL_BRIEF_CHARS and shown(long)[1].startswith(material[:200])


def test_the_reserve_always_sends_the_brief():
    request = fast_text.build_request(QUESTION, instructions=instructions())
    brief = brain_short.brief_instructions(request['instructions'], QUESTION)
    assert brief != request['instructions']
    assert reserve_text.chat_body(request, 'openai/gpt-oss-120b')['messages'][0]['content'] == brief
    sent = []

    def post(url, headers, body, timeout):
        sent.append(body['messages'][0]['content'])
        yield from sse('27 июня 1709 года.')
    assert ''.join(ReserveStream({'GROQ_API_KEY': 'k'}, post=post)(request, threading.Event())) == '27 июня 1709 года.'
    assert sent == [brief]


def test_a_brief_that_fails_never_fails_the_job(monkeypatch):
    def broken(*_, **__):
        raise RuntimeError('boom')
    monkeypatch.setattr(brain_short, 'brief_instructions', broken)
    request = fast_text.build_request(QUESTION, instructions=instructions())
    assert reserve_text.chat_body(request, 'openai/gpt-oss-120b')['messages'][0]['content'] == request['instructions']


class _Controller:
    settings = {}
    fast_exchanges = staticmethod(lambda: [])
    fast_in_play = staticmethod(lambda: None)
    ear_ended = None
    source_segment_id = None
    refuse_deadline = decision_due = staticmethod(lambda *a: None)      # the real controller's two moments: no question open, no bound


def test_no_key_asks_for_the_brief_and_the_reserve_of_a_call_has_it(monkeypatch):
    assert not [key for key in settings.DEFAULTS if key.startswith('reserve_')]
    monkeypatch.setattr(reserve_text, 'read_keys', lambda path=None: {'GROQ_API_KEY': 'k'})
    channel = fast_text.for_call({'fast_text': 'on', 'local_ear': 'act'}, _Controller(), credentials=None)
    assert isinstance(channel.stream, reserve_text.Roads) and channel.stream.backup.roads
