"""F5: ``instant_rank`` works: the flag reaches the index, and the ranked path answers only what the question asks (kind, numbers, margin)."""
from echo_sync import instant, settings


def test_flag_survives_settings():
    on = settings.resolve({'fast_text': 'on', 'local_ear': 'act', 'instant': 'on', 'instant_rank': 'on'})
    assert on['instant_rank'] == 'on'
    assert settings.resolve({})['instant_rank'] == 'off'
    assert settings.resolve({'instant_rank': 'maybe'})['instant_rank'] == 'off'


def test_flag_reaches_the_index():
    base = {'instant': 'on'}
    assert instant.from_settings(base).ranker is None                       # off: the strict path only, as the server believes
    assert instant.from_settings(dict(base, instant_rank='off')).ranker is None
    assert instant.from_settings(dict(base, instant_rank='on')).ranker is not None


_PAD = [{'id': f'p{n}', 'q': f'Что такое показатель номер {n}?', 'alt': [], 'answer': f'Показатель {n}.'} for n in range(30)]
BANK = _PAD + [
    {'id': 'n1', 'q': 'Какие бывают нематериальные активы?', 'alt': ['Приведи примеры нематериальных активов'], 'answer': 'Патенты, товарные знаки, программы.'},
    {'id': 'n2', 'q': 'Что такое нематериальные активы?', 'alt': [], 'answer': 'Имущество без физической формы; его стоимость переносят амортизацией.'},
    {'id': 't1', 'q': 'Откуда берутся темы для презентации?', 'alt': [], 'answer': 'Из списка по специальности.'},
    {'id': 's80', 'q': 'Что такое статья 80 НК?', 'alt': [], 'answer': 'Статья 80 — налоговая декларация.'},
    {'id': 's88', 'q': 'Что такое статья 88 НК?', 'alt': [], 'answer': 'Статья 88 — камеральная проверка.'},
]


def _hit(text, rank=True):
    ins = instant.Instant(BANK, adapters=(), rank=rank)
    return ins.feed(text, 0.0, final=True)


def test_kind_of_the_entry_not_of_one_form():
    """«что такое НМА, приведи примеры» is no question for «какие бывают НМА», even through its alt of no kind (the strict path too)."""
    for rank in (False, True):
        hit = _hit('слушай что такое нематериальные активы приведи примеры', rank)
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


def test_the_built_index_is_keyed_by_rank_and_rank_is_off_by_default():
    """integ-c17 (coordinator): ``instant._built`` keys on ``rank``: a profile that turns ``instant_rank`` on never gets the index built without it."""
    from echo_sync import instant
    from echo_sync.settings import DEFAULTS
    assert DEFAULTS['instant_rank'] == 'off'
    instant._built.clear()
    off = instant.from_settings({'instant': 'on'})
    assert off is not None and off.ranker is None
    on = instant.from_settings({'instant': 'on', 'instant_rank': 'on'})
    assert on.ranker is not None
    assert {key[-1] for key in instant._built} == {True}
