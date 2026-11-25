"""W17 (Р-16): the product is universal, so no text that is SENT to a model (the BRAIN and its rows, the short BRAIN, the policy of the call, the reserve's screening line, the no-source line) names a situation or a role of the
listener: no exam, interview, presentation, lesson, teacher, break, subject codes (ОП.0x, МДК), «друг» as a friend. The first guard (test_w3_integ) read ``BRAIN`` only and three words; this one reads every text the roads send, with the wider list
of the owner's backlog row, and fails on a mutant that puts one word back."""
import re

import pytest

from echo_sync import brain_rules, brain_short, fast_text, reserve_text

SITUATION = re.compile(r'экзамен|собеседован|презентац|препод|урок|перемен[аыуе]\b|\bОП\.\s?\d|МДК|\bдруг\b(?!\s+(?:за|друга))|друзь|студент|учител|экзаменатор', re.I)


def texts():
    found = {'BRAIN': fast_text.BRAIN, 'BRAIN_KEEP': fast_text.BRAIN_KEEP, 'BRAIN_POLICY': fast_text.BRAIN_POLICY, 'NO_SOURCE_BRAIN': fast_text.NO_SOURCE_BRAIN,
             'BRAIN_SHORT': brain_short.BRAIN_SHORT, 'SHORT_POLICY': brain_short.SHORT_POLICY, 'brief_instructions': brain_short.brief_instructions(fast_text.BRAIN_POLICY, 'сколько будет пять на пять'),
             }
    screened = brain_short.screen_instructions(fast_text.BRAIN_POLICY)      # None: no material to leave out (the request is its own screen)
    if screened:
        found['screen_instructions'] = screened
    for n, (_, text) in enumerate(brain_rules.BRAIN_ROWS):
        found[f'BRAIN_ROWS[{n}]'] = text
    for n, (_, text) in enumerate(brain_rules.KEEP_ROWS):
        found[f'KEEP_ROWS[{n}]'] = text
    return found


@pytest.mark.parametrize('name', sorted(texts()))
def test_w17_no_text_sent_to_a_model_names_a_situation_or_a_role_of_the_listener(name):
    text = texts()[name]
    assert isinstance(text, str) and text, name
    found = SITUATION.search(text)
    assert found is None, f'Р-16: {name} says {found.group(0)!r}: the universal product speaks of «человек» and the room, not of a situation'


def test_w17_the_guard_sees_a_word_put_back(monkeypatch):
    """The list is not blind: the old line of fast_text.py:49 («человек на экзамене, на собеседовании или перед презентацией») is caught, and the plain words «других слов» / «друг» as the owner's own wording of «other» are not."""
    assert SITUATION.search('человек на экзамене, на собеседовании или перед презентацией')
    assert SITUATION.search('вопрос преподавателя') and SITUATION.search('это МДК.01') and SITUATION.search('на уроке') and SITUATION.search('твой друг спросил')
    assert not SITUATION.search('выведи только метку, без других слов, друг за другом, друг друга')
    monkeypatch.setattr(brain_rules, 'BRAIN_ROWS', brain_rules.BRAIN_ROWS + ((('h2-brain',), 'Подсказывай человеку на экзамене.'),))
    assert SITUATION.search('\n'.join(text for _, text in brain_rules.BRAIN_ROWS))


def test_w17_the_text_the_reserve_road_sends_is_the_same_text(monkeypatch):
    """The reserve's request (``chat_body``) is built from the very instructions of the job: no road has a wording of its own that names a situation."""
    request = {'instructions': fast_text.BRAIN_POLICY, 'input': [{'role': 'user', 'content': [{'type': 'input_text', 'text': 'Что такое инерция?'}]}]}
    body = reserve_text.chat_body(request, 'openai/gpt-oss-120b')
    sent = ' '.join(str(message.get('content', '')) for message in body.get('messages', []))
    assert SITUATION.search(sent) is None
