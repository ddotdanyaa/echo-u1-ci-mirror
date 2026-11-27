"""U21-S5: C3 a word the ear tore in two is joined back (at most REJOIN_MAX joins), C4 the part after a self-correction is ranked; always on with the ranked path (the key bank_rejoin is gone)."""
import pytest

from echo_sync import instant
from echo_sync.settings import DEFAULTS, resolve

ROWS = [
    {'id': 'a', 'q': 'что такое стимулирующая функция налогов', 'alt': [], 'answer': 'Это побуждение к нужному поведению через налоговые льготы.', 'trust': 'Д'},
    {'id': 'b', 'q': 'что такое фискальная функция налогов', 'alt': [], 'answer': 'Это наполнение бюджета государства.', 'trust': 'Д'},
    {'id': 'c', 'q': 'что такое регулирующая функция налогов', 'alt': [], 'answer': 'Это управление экономикой через налоги.', 'trust': 'Д'},
    {'id': 'd', 'q': 'что такое косвенные налоги', 'alt': [], 'answer': 'Это налоги в цене товара.', 'trust': 'Д'},
]


@pytest.fixture(autouse=True)
def small(monkeypatch):
    monkeypatch.setattr(instant, 'RANK_MIN_MASS', 0.1)      # four rows: the IDF mass is small


def ranker(rejoin):
    return instant.Instant(ROWS, adapters=(), rejoin=rejoin).ranker


def hit(r, q):
    got = r.best(q)
    return None if got is None else r.entries[got[0]]['id']


def test_torn_word_hits_only_with_the_flag():
    q = 'что такое стимулиру ющая функция налогов'
    assert hit(ranker(False), q) is None
    assert hit(ranker(True), q) == 'a'


def test_unknown_words_stay_unknown():
    assert hit(ranker(True), 'что такое гугл казахстан') is None


def test_the_number_of_joins_is_capped(monkeypatch):
    monkeypatch.setattr(instant, 'REJOIN_MAX', 0)
    assert hit(ranker(True), 'что такое стимулиру ющая функция налогов') is None


def test_correction_part_follows_the_stands_part():
    r = ranker(True)
    q = 'что такое гугл казахстан нет что такое косвенные налоги'
    assert hit(r, q) == 'd'


def test_a_known_question_is_not_touched():
    q = 'что такое фискальная функция налогов'
    assert hit(ranker(True), q) == hit(ranker(False), q) == 'b'


def test_the_key_is_gone_the_ranked_path_always_rejoins():
    assert 'bank_rejoin' not in DEFAULTS and 'bank_rejoin' not in resolve({'bank_rejoin': 'on'})
    instant._built.clear()
    assert instant.from_settings({'instant': 'on'}) is not None and next(iter(instant._built.values())).ranker.rejoin is True
