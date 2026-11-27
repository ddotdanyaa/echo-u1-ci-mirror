"""U21-S5: C3 a word the ear tore in two is joined back (at most REJOIN_MAX joins), C4 the part after a self-correction is ranked; flag bank_rejoin, off by default."""
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
    return instant.Instant(ROWS, adapters=(), rank2=True, rejoin=rejoin).ranker


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


def test_flag_default_and_resolve():
    assert DEFAULTS['bank_rejoin'] == 'off' and resolve({})['bank_rejoin'] == 'off'
    assert resolve({'bank_rejoin': 'on'})['bank_rejoin'] == 'on' and resolve({'bank_rejoin': 1})['bank_rejoin'] == 'off'
