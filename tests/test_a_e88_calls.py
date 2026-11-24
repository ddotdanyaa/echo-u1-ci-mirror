"""E88 on the call: no word of the listener's own affairs reaches the PUBLIC search (``public_lookup_request``), whatever the form of the word.

The gate is ``privacy_gate.allowed`` (unit rows: test_w10_safe, test_w9_safe). This is the same rule seen from the wire: the real ControlledMedia and the real NativeMediaSocket of the
rig of test_h1_fast_text (the lookup route is open there), the question is one that DOES go to the search (the control), with one personal form of the backlog added to it. What the
search (``World.lookup_calls``) was given is read: the refused question takes the designed way (``impersonal`` cuts the frame and looks up what is public), so a query may leave, never a
personal one. Not run on the laptop."""
import pytest

import helpers_s6_state as S
from echo_sync import privacy_gate
from echo_sync.controlled_media import ControlledMedia
from test_h1_fast_text import rig      # noqa: F401 - rig is the fixture

BASE = 'Проверь, пожалуйста, что такое гидравлический удар'
# The forms the backlog lists as passing the old expression (E88): мой/моя/мою/моим/моими, мне/меня/мной/мною, нам/нас/нами, наш and its cases, «я» after a question word.
FORMS = ['на мою зарплату', 'с моими данными', 'с моим долгом', 'для моей компании', 'мне это нужно', 'для меня', 'со мной', 'нам это нужно', 'для нас', 'с нами',
         'в наш договор', 'в нашей компании', 'сколько я заработал', 'как меня зовут', 'кто я такой']


def ask(rig, text):
    rig.w.feed(S.turn_created('u1', 'user', text.split()[0]))
    rig.w.feed(S.turn_done('u1', 'user', text))
    rig.pump()


def test_control_the_public_question_reaches_the_search(rig):
    ask(rig, BASE + '.')
    assert rig.w.lookup_calls, 'precondition: this question goes to the public search'
    assert all(ControlledMedia.public_lookup_allowed(query, True) for query in rig.w.lookup_calls), rig.w.lookup_calls


@pytest.mark.parametrize('form', FORMS)
def test_a_personal_form_never_reaches_the_public_search(rig, form):
    ask(rig, f'{BASE}, {form}.')
    for query in rig.w.lookup_calls:
        assert ControlledMedia.public_lookup_allowed(query, True), f'E88: «{query}» went to the public search'
        assert not privacy_gate.SEARCH_PERSONAL.search(query) and not privacy_gate.PERSONAL_QUERY.search(query), query


@pytest.mark.parametrize('form', FORMS)
def test_the_gate_says_the_same_for_the_form_alone(form):
    assert not ControlledMedia.public_lookup_allowed(f'{BASE}, {form}.', True)


# E88 rest: a verb of the 1st person singular (present/future, with or without «я», any adverb between), a status with no verb («я студент», «я на пенсии») and the English forms are the listener's own affair;
# a frame verb («я хочу узнать», «я думаю», «не понимаю») and the past («я хотел спросить») are the speaker's frame and stay public. The analyzer (pymorphy3) is a required dependency (plugin.yaml, test_env_deps):
# no importorskip here, its absence is a red test.
I_DO = [('я работаю в ООО Ромашка', 'Ромашк'), ('я вот работаю в ООО Ромашка', 'Ромашк'), ('я сейчас живу в Казани', 'Казан'), ('работаю в ООО Ромашка', 'Ромашк'),
        ('я студент третьего курса', 'студент'), ('я на пенсии', 'пенси'), ('я директор ООО Ромашка', 'Ромашк'), ('I work at Romashka', 'Romashka'), ('my salary is high', 'salary')]
I_FRAME = ['я хочу узнать', 'я думаю', 'я не понимаю', 'нет, я хотел спросить', 'вот я сегодня не выспался, но интересно', 'я могу узнать', 'я пытаюсь понять', 'я ищу', 'я не помню', 'я не пойму',
           'я читал про ИП', 'я слышал про ООО', 'я спросил у врача', 'я читал про директора', 'Can you tell me', 'I want to know', 'explain to me']


@pytest.mark.parametrize('form,word', I_DO)
def test_the_gate_refuses_what_is_said_of_oneself(form, word):
    assert not ControlledMedia.public_lookup_allowed(f'{BASE}, {form}.', True)


@pytest.mark.parametrize('form,word', I_DO)
def test_what_is_said_of_oneself_never_reaches_the_public_search(rig, form, word):
    assert not ControlledMedia.public_lookup_allowed(f'{BASE}, {form}.', True), 'the decision itself: the gate refuses (an empty list of searches proves nothing)'
    ask(rig, f'{BASE}, {form}.')
    for query in rig.w.lookup_calls:
        assert word.lower() not in query.lower(), f'E88: «{query}» went to the public search'


@pytest.mark.parametrize('form', I_FRAME)
def test_the_frame_of_the_speaker_stays_public_and_is_searched(rig, form):
    assert ControlledMedia.public_lookup_allowed(f'{form}, что такое гидравлический удар?', True)
    ask(rig, f'{form}, что такое гидравлический удар.')
    assert rig.w.lookup_calls, 'a framed public question must reach the public search'


def test_the_failure_of_the_analyzer_keeps_the_question_from_the_search(monkeypatch):
    from echo_sync import ru_alignment
    monkeypatch.setattr(ru_alignment, '_lemma', lambda word: (_ for _ in ()).throw(RuntimeError('no analyzer')))
    assert privacy_gate.speaks_as_i('какая ставка НДС') is True
