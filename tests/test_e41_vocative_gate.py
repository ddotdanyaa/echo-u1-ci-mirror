"""E41 text-only guard: do not leak direct-address knowledge questions.

Scope is single-sentence vocatives. Multi-sentence speaker handoffs and the
transport/public-lookup gate still require integration and voice replay tests.
"""
import pytest

from echo_sync.gate_text import QUESTION, TALK, decide, talk_without_flag, public_address_allowed


@pytest.mark.parametrize('spoken', [
    'Лена, в каком году началась Отечественная война 1812 года?',
    'Сергей, сколько будет девятнадцать умножить на три?',
    'Миша, что такое налоговая база?',
    'Катя, вспомни, сколько будет два плюс два?',
])
def test_single_sentence_vocative_blocks_model_job(spoken):
    verdict = decide(spoken)
    assert verdict.kind == TALK and verdict.reason == 'to_person', verdict
    assert talk_without_flag(spoken, verdict)


@pytest.mark.parametrize('spoken', [
    'В каком году основали Петербург?',
    'Слушай, а в каком году Гагарин полетел в космос?',
    'Скажите, а что такое ВВП?',
])
def test_without_vocative_keeps_regular_knowledge_question(spoken):
    assert decide(spoken).kind == QUESTION


@pytest.mark.parametrize('spoken', [
    'Лен, ты меня слышишь? Ага. Тогда такой вопрос: в каком году образовался СССР?',
    'Пап, подожди секунду, я тут с человеком разговариваю. Так, о чём я? Да, сколько градусов в прямом угле?',
    'Милан, по-моему.',
])
def test_handoff_or_short_answer_is_not_silenced(spoken):
    assert decide(spoken).kind != TALK


def test_multisentence_named_recipient_is_not_auto_silenced_or_published():
    # Without speaker attribution, a later factual question is ambiguous.
    # The local judge must not force TALK, yet no original third-party
    # speech can leave for public search. Both assertions are green in the
    # sanitized real-judge CI mirror; audio attribution remains untested.
    spoken = 'Лена, проверь запись. В каком году основали Петербург?'
    assert decide(spoken).kind != TALK
    assert not public_address_allowed(spoken)


@pytest.mark.parametrize('spoken', [
    'Сейчас обсудим план. Лена, в каком году основали Петербург?',
    'Как дела? Сергей, сколько будет два плюс два?',
    'Сначала ответь мне. Миша, что такое налоговая база?',
])
def test_explicit_final_sentence_vocative_is_to_person(spoken):
    verdict = decide(spoken)
    assert verdict.kind == TALK and verdict.reason == 'to_person', verdict
    assert talk_without_flag(spoken, verdict), 'controller must consume last-act verdict'
    assert not public_address_allowed(spoken), 'public search must not publish third-person speech'


@pytest.mark.parametrize('spoken', [
    'Лена, подожди. А ты подскажи, сколько будет два плюс два?',
    'Лена, закрой окно. А ты подскажи, какой сейчас курс?',
])
def test_compound_handoff_must_not_be_silenced(spoken):
    assert decide(spoken).kind != TALK


@pytest.mark.parametrize('spoken', [
    'Лена, проверь запись. В каком году основали Петербург?',
    'Лена сколько будет два плюс два',
    'лена сколько будет два плюс два',
    'Миша что такое налоговая база',
    'Лена, открой тетрадь. Тогда вопрос: что такое НДС?',
])
def test_public_recipient_denies_named_or_asr_ambiguous_utterances(spoken):
    assert not public_address_allowed(spoken)


@pytest.mark.parametrize('spoken', [
    'Сколько будет два плюс два?',
    'В каком году основали Петербург?',
    'Приведи пример',
])
def test_public_recipient_does_not_deny_generic_questions(spoken):
    assert public_address_allowed(spoken)


def test_controller_public_lookup_is_blocked_but_local_route_stays_available():
    from echo_sync.controlled_media import ControlledMedia
    question = 'Лена, в каком году основали Петербург?'
    assert not ControlledMedia.public_lookup_allowed(question, search=True)
    assert ControlledMedia.public_lookup_allowed(question, search=False)


@pytest.mark.parametrize('spoken', [
    'Лена, в каком году основали Петербург?',
    'Лена сколько будет два плюс два',
    'Миша, проверь запись. Что такое НДС?',
])
def test_e41_reserve_model_last_mile_rejects_speech(spoken):
    from echo_sync import reserve_text
    body = {'messages': [{'role': 'system', 'content': 'Предмет занятия: экономика'},
                         {'role': 'user', 'content': spoken}]}
    assert reserve_text._sendable(body) is None


def test_e41_reserve_history_drops_addressed_turn_not_public_question():
    from echo_sync import reserve_text
    history = 'Последние реплики этого разговора (для связи с вопросом):\nВопрос: Лена, что такое ВВП?\nОтвет: Это разговор с Леной.\nВопрос: Когда была Полтавская битва?\nОтвет: В 1709 году.\n'
    body = {'messages': [{'role': 'system', 'content': 'Правила.\n' + history},
                         {'role': 'user', 'content': 'Что такое инерция?'}]}
    approved = reserve_text._sendable(body)
    assert approved is not None
    assert 'Лена, что такое ВВП?' not in approved['messages'][0]['content']
    assert 'Когда была Полтавская битва?' in approved['messages'][0]['content']


@pytest.mark.parametrize('spoken', [
    'Вчера, в каком году основали Петербург?',
    'Сегодня, сколько будет два плюс два?',
    'Например, сколько будет три плюс пять?',
    'Кстати, что такое налоговая база?',
])
def test_disclosure_gate_does_not_misread_adverbs_as_named_people(spoken):
    assert public_address_allowed(spoken)
    assert decide(spoken).kind != TALK


@pytest.mark.parametrize('spoken', [
    'Закончим с первой темой. Миша сколько будет три плюс четыре',
    'Теперь о второй задаче! Лена где находится река',
    'Лена объясни почему небо голубое',
    'Миша подскажи что такое гравитация',
    'Саша расскажи в каком году была битва',
    'Лена? Сколько будет два плюс два?',
])
def test_e41_ASR_missing_comma_and_later_named_act_never_public(spoken):
    assert not public_address_allowed(spoken)
