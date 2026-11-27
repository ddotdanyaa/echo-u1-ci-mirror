"""Lane A (13.11, map §7.4/§8.4): ``classifier.portion_share``, the feature that tells a try at the waiting answer from talk around it.

The share is how much of what was said is the waiting answer's own words (content stems found among the answer's, over all content stems of
what was said; a number said for the answer's number counts as one item). It is a feature: it decides nothing, the verdicts of ``analyze``
are the ones of before. All phrases are made up; none is from a recorded call.
"""
import pytest

from echo_sync.classifier import analyze, portion_share
from echo_sync.settings import CALL_SETTINGS

PORTION = ' Амортизация это постепенный перенос стоимости имущества на расходы.'
STATE = {'revision': 30, 'chunks': [PORTION], 'chunk_index': 0, 'completed': False, 'question': 'Что такое амортизация?', 'history': []}
TALK = ' Стоимость билетов на электричку опять выросла с понедельника и теперь мы ездим на работу на автобусе'
NUMBERED = {**STATE, 'chunks': [' Счёт 19 налог по приобретённым ценностям активный.']}
FINE = {**STATE, 'chunks': [' Штраф 118 рублей.']}


def share(text, state=STATE):
    return portion_share(text, state, CALL_SETTINGS)


def test_a_try_of_the_last_words_is_the_portion():
    assert share(' постепенный перенос стоимости ну это понятно') >= 0.5


def test_long_talk_with_one_shared_word_is_not_the_portion():
    assert share(TALK) < 0.2


def test_a_number_for_the_portions_number_is_one_shared_item():
    assert share(' девятнадцатый счёт активный', NUMBERED) == pytest.approx(1.0)
    assert share(' десять умножить на двадцать', NUMBERED) == 0.0          # two numbers of its own: not the portion's
    assert share(' сто восемнадцать рублей', FINE) == pytest.approx(1.0)


def test_nothing_waits_or_nothing_said_is_none():
    assert share(TALK, {}) is None
    assert share(TALK, {**STATE, 'completed': True}) is None
    assert share(' ну э-э') is None


def test_the_whole_answer_is_the_base_not_one_portion():
    two = {**STATE, 'chunks': [' Первое слагаемое налог на прибыль.', ' Второе слагаемое налог на имущество организаций.'], 'chunk_index': 0}
    assert share(' налог на имущество организаций', two) >= 0.5


@pytest.mark.parametrize('said', [TALK, ' постепенный перенос стоимости ну это понятно', ' Что такое амортизация?', ' ну э-э',
                                  ' десять умножить на двадцать', ' Мы вчера ходили в кино там было шумно и душно'])
def test_the_share_decides_nothing(said):
    """``analyze`` gives the same verdict with the feature called or not: it is read-only."""
    before = analyze(said, STATE, [], CALL_SETTINGS)
    share(said)
    assert analyze(said, STATE, [], CALL_SETTINGS) == before


def test_the_share_is_one_row_of_the_probe_registry():
    """HARVEST U103: ``portion_share`` is a probe of the registry (S1) that P07's ``_abandons`` reads, a feature with no verdict: ``UNKNOWN`` where the function says ``None``."""
    from echo_sync.cm_probes import UNKNOWN, probe
    found = probe('portion_share', ' постепенный перенос стоимости ну это понятно', state=STATE, settings=CALL_SETTINGS)
    assert found.value == share(' постепенный перенос стоимости ну это понятно') and found.value >= 0.5 and found.origin == 'cm_probes.portion_share'
    assert probe('portion_share', TALK, state={}, settings=CALL_SETTINGS).value == UNKNOWN
    assert probe('portion_share', ' девятнадцатый счёт', state=NUMBERED, settings=CALL_SETTINGS, loose_numbers=True).value == pytest.approx(1.0)
