"""Production gate_text algorithm with synthetic-only inputs; no sensitive corpus."""
import pytest

from echo_sync.gate_text import TALK, QUESTION, UNKNOWN, decide, talk_without_flag, public_address_allowed


@pytest.mark.parametrize("spoken", [
    "Лена, в каком году была битва?",
    "Миша, что такое налоговая база?",
    "Сергей, сколько будет девятнадцать умножить на три?",
])
def test_explicit_named_person_single_act_is_quiet(spoken):
    v = decide(spoken)
    assert (v.kind, v.reason) == (TALK, "to_person"), v
    assert talk_without_flag(spoken, v)
    assert not public_address_allowed(spoken)


@pytest.mark.parametrize("spoken", [
    "В каком году была битва?",
    "Что такое налоговая база?",
    "Сколько будет девятнадцать умножить на три?",
    "Скажите, а что такое ВВП?",
])
def test_public_factual_questions_are_not_silenced(spoken):
    assert decide(spoken).kind == QUESTION
    assert public_address_allowed(spoken)


@pytest.mark.parametrize("spoken", [
    "Вчера, в каком году была битва?",
    "Сегодня, сколько будет два плюс два?",
    "Например, сколько будет три плюс пять?",
    "Кстати, что такое налоговая база?",
])
def test_adverbs_are_not_confused_with_people(spoken):
    assert decide(spoken).kind != TALK
    assert public_address_allowed(spoken)


@pytest.mark.parametrize("spoken", [
    "Сейчас обсудим план. Лена, в каком году была битва?",
    "Как дела? Сергей, сколько будет два плюс два?",
    "Сначала ответь мне. Миша, что такое налоговая база?",
])
def test_named_person_in_final_act_suppresses_only_that_act(spoken):
    v = decide(spoken)
    assert (v.kind, v.reason) == (TALK, "to_person"), v
    assert talk_without_flag(spoken, v)
    assert not public_address_allowed(spoken)


@pytest.mark.parametrize("spoken", [
    "Лена, подожди. А ты подскажи, сколько будет два плюс два?",
    "Лена, закрой окно. А ты подскажи, какой сейчас курс?",
    "Лена, проверь запись. В каком году построили мост?",
])
def test_ambiguous_or_assistant_handoff_not_automatically_silenced(spoken):
    # A new act without reliable speaker attribution must not be forced to TALK.
    assert decide(spoken).kind != TALK
    # But original speech addressed to someone cannot be published verbatim.
    assert not public_address_allowed(spoken)


@pytest.mark.parametrize("spoken", [
    "Закончим с первой темой. Миша сколько будет три плюс четыре",
    "Теперь о второй задаче! Лена где находится река",
    "Лена объясни почему небо голубое",
    "Миша подскажи что такое гравитация",
    "Саша расскажи в каком году была битва",
    "Лена? Сколько будет два плюс два?",
])
def test_asr_missing_comma_not_public_but_keeps_local_judgement(spoken):
    assert not public_address_allowed(spoken)
