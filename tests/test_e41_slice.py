"""Public synthetic E41 cases only. No private transcripts, keys, network or fixtures."""
import pytest

from e41_slice import _vocative, _last_sentence, public_address_allowed


@pytest.mark.parametrize("spoken", [
    "Лена, сколько будет два плюс два?",
    "Миша, в каком году произошла битва?",
    "Лена сколько будет два плюс два",
    "лена сколько будет два плюс два",
    "Миша где находится Москва",
    "Лена, проверь запись. В каком году построили мост?",
    "Миша, посмотри. Что такое гравитация?",
    "Саша, куда отправить письмо? Давай посмотрим.",
    "Когда была битва? Лена, проверь дату.",
    "Лена, а сколько будет пять плюс три?",
])
def test_named_person_disallowed_for_public_services(spoken):
    assert not public_address_allowed(spoken), spoken


@pytest.mark.parametrize("spoken", [
    "В каком году состоялось событие?",
    "Что такое гравитация?",
    "Сколько будет два плюс два?",
    "Сколько будет два плюс два",
    "Вчера, в каком году состоялось событие?",
    "Сегодня, сколько будет два плюс два?",
    "Например, сколько будет три плюс пять?",
    "Кстати, что такое налоговая база?",
    "Скажите, что такое гравитация?",
    "Приведи пример",
    "Почему небо голубое?",
])
def test_plain_public_question_remains_eligible(spoken):
    assert public_address_allowed(spoken), spoken


@pytest.mark.parametrize("text,expected", [
    ("Лена, расскажи", True),
    ("Миша, где Москва?", True),
    ("Скажите, что такое масса?", False),
    ("Сегодня, сколько будет два плюс два?", False),
    ("Вчера, что такое экономический рост?", False),
])
def test_first_word_vocative_detection(text,expected):
    assert _vocative(text) == expected


def test_last_sentence_boundary_is_shared_by_judge_and_public_gate():
    text = "Сегодня, подводим итоги. Миша, что такое гравитация?"
    assert _last_sentence(text) == "Миша, что такое гравитация?"
    assert not public_address_allowed(text)


@pytest.mark.parametrize("spoken", [
    "",
    " ",
    "\t",
])
def test_empty_material_is_never_authorized(spoken):
    assert not public_address_allowed(spoken)


@pytest.mark.parametrize("spoken", [
    "Миша, посмотри. Сколько будет 2+2?",
    "Миша, посмотри! Сколько будет 2+2?",
    "Миша, посмотри? Сколько будет 2+2?",
])
def test_mixed_speech_act_never_leaks_original(spoken):
    assert not public_address_allowed(spoken)


@pytest.mark.parametrize("spoken", [
    "Закончим с первой темой. Миша сколько будет три плюс четыре",
    "Теперь о второй задаче! Лена где находится река",
    "Лена объясни почему небо голубое",
    "Миша подскажи что такое гравитация",
    "Саша расскажи в каком году была битва",
    "Лена? Сколько будет два плюс два?",
])
def test_asr_missing_comma_or_sentence_split_stays_private(spoken):
    assert not public_address_allowed(spoken), spoken
