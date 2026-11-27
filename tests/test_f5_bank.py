"""F5: the ranked path works: it reaches the index, and the ranked path answers only what the question asks (kind, numbers, margin)."""
from echo_sync import instant, settings


import pytest
pytestmark = pytest.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)


def test_no_switch_for_the_ranked_path_in_settings():
    assert not [key for key in settings.DEFAULTS if key.startswith('instant_ra')]


def test_the_ranked_path_reaches_the_index():
    base = {'instant': 'on'}
    assert instant.from_settings(base).ranker is not None                   # the ranked path is the rule of every call (the owner's profile had it on)


_PAD = [{'id': f'p{n}', 'q': f'Что такое показатель номер {n}?', 'alt': [], 'answer': f'Показатель {n}.'} for n in range(30)]
BANK = _PAD + [
    {'id': 'n1', 'q': 'Какие бывают нематериальные активы?', 'alt': ['Приведи примеры нематериальных активов'], 'answer': 'Патенты, товарные знаки, программы.'},
    {'id': 'n2', 'q': 'Что такое нематериальные активы?', 'alt': [], 'answer': 'Имущество без физической формы; его стоимость переносят амортизацией.'},
    {'id': 't1', 'q': 'Откуда берутся темы для презентации?', 'alt': [], 'answer': 'Из списка по специальности.'},
    {'id': 's80', 'q': 'Что такое статья 80 НК?', 'alt': [], 'answer': 'Статья 80 — налоговая декларация.'},
    {'id': 's88', 'q': 'Что такое статья 88 НК?', 'alt': [], 'answer': 'Статья 88 — камеральная проверка.'},
]


def _hit(text):
    ins = instant.Instant(BANK, adapters=())
    return ins.feed(text, 0.0, final=True)


def test_kind_of_the_entry_not_of_one_form():
    """«что такое НМА, приведи примеры» is no question for «какие бывают НМА», even through its alt of no kind (the strict path too)."""
    hit = _hit('слушай что такое нематериальные активы приведи примеры')
    assert hit is None or hit.id == 'n2'


def test_personal_question_is_no_bank_question():
    assert _hit('слушай а ты какую тему для презентации выбрал') is None


def test_head_word_unsaid_by_the_entry():
    """«амортизация НМА» is not «НМА», though the answer of «что такое НМА» says «амортизацией»."""
    assert _hit('что значит амортизация нематериальных активов простыми словами') is None
    assert _hit('что такое нематериальные активы простыми словами').id == 'n2'


def test_another_number_is_no_rival():
    """«статья 88» can never be the answer to «статья 80»: it does not eat the margin."""
    hit = _hit('про что статья 80 нк')
    assert hit is not None and hit.id == 's80'


def test_the_built_index_is_ranked_and_built_once_per_bank():
    """integ-c17 (coordinator): ``instant._built`` holds one ranked index per bank: every call gets the ranked path."""
    from echo_sync import instant
    instant._built.clear()
    on = instant.from_settings({'instant': 'on'})
    assert on.ranker is not None
    again = instant.from_settings({'instant': 'on'})
    assert again.ranker is not None and len(instant._built) == 1
