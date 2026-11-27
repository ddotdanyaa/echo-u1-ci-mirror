"""U21-S6: C2 the weight of the rival in the margin; bank_rival_weight (1.0 = as it was), the lost 'Виды финансов организаций' hits at 0.0, the 500-row table has no new false accept."""
import json
import sys
from pathlib import Path

import pytest

from echo_sync import instant
from echo_sync.settings import DEFAULTS, resolve

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
BANK10 = ROOT.parents[1] / 'МАТЕРИАЛЫ' / 'БАНК' / 'instant_bank_10.json'
ROWS = [{'id': 'a1', 'q': 'что такое абсолютная ссылка', 'alt': [], 'answer': 'Ссылка, которая не меняется при копировании формулы.', 'trust': 'Д'},
        {'id': 'a2', 'q': 'что такое абсолютная ссылка на ячейку', 'alt': [], 'answer': 'Адрес ячейки со знаками доллара.', 'trust': 'Д'},
        {'id': 'a3', 'q': 'что такое налог на прибыль', 'alt': [], 'answer': 'Налог на прибыль организаций.', 'trust': 'Д'}]


@pytest.fixture(autouse=True)
def small(monkeypatch):
    monkeypatch.setattr(instant, 'RANK_MIN_MASS', 0.1)


def ranker(w):
    return instant.Instant([dict(r) for r in ROWS], adapters=(), rival_w=w).ranker


def test_the_rival_weight_moves_the_margin_and_explain_mirrors_best():
    q = 'что такое абсолютная ссылка'
    full, mild, none = ranker(1.0), ranker(0.6), ranker(0.0)
    assert (full.rival_w, mild.rival_w, none.rival_w) == (1.0, 0.6, 0.0)
    for r in (full, mild, none):
        for gap in (None, 0.3, 0.9):
            assert (r.best(q, gap=gap) is None) == bool(r.explain(q, gap=gap))
    assert full.best(q, gap=0.3) is None and full.explain(q, gap=0.3) == 'rival'      # the rival weighs 0.78: the margin is 0.22
    assert mild.best(q, gap=0.3) is not None and none.best(q, gap=0.9) is not None
    assert none.best(q, gap=0.9)[2] == pytest.approx(1.0) and mild.best(q, gap=0.3)[2] > full.best(q)[2]


def test_a_sure_question_is_the_same_at_every_weight():
    for w in (1.0, 0.6, 0.0):
        got = ranker(w).best('что такое налог на прибыль')
        assert got is not None and ranker(w).entries[got[0]]['id'] == 'a3'


def test_the_default_is_the_old_weight_and_a_wrong_value_is_the_default():
    assert DEFAULTS['bank_rival_weight'] == 1.0 and resolve({})['bank_rival_weight'] == 1.0
    assert resolve({'bank_rival_weight': 0.3})['bank_rival_weight'] == 0.3
    for bad in ('x', True, -0.1, 1.5, None):
        assert resolve({'bank_rival_weight': bad})['bank_rival_weight'] == 1.0


def test_the_weight_is_in_the_cache_key():
    s = {'instant': 'on', 'instant_rank': 'on', 'bank_rival_weight': 0.3}
    instant._built.clear()
    try:
        assert instant.from_settings(s).ranker.rival_w == 0.3
        assert instant.from_settings({**s, 'bank_rival_weight': 1.0}).ranker.rival_w == 1.0
        assert instant.from_settings({**s, 'bank_rival_weight': 7}).ranker.rival_w == 1.0      # out of 0..1: the old weight
    finally:
        instant._built.clear()


@pytest.mark.skipif(not BANK10.exists(), reason='the owner materials are not here')
def test_vidy_finansov_organizatsiy_hits_at_zero_and_not_at_one():
    rows = [r for r in (instant.clean_entry(x) for x in json.load(open(BANK10, encoding='utf-8'))) if r]
    q = 'Виды финансов организаций'
    assert instant.Instant([dict(r) for r in rows], adapters=(), rank2=True, rival_w=1.0).ranker.best(q) is None
    assert instant.Instant([dict(r) for r in rows], adapters=(), rank2=True, rival_w=0.0).ranker.best(q) is not None


def test_the_table_of_500_has_no_false_accept_at_the_chosen_weight():
    from tools import c24_table
    sys.path.insert(0, str(ROOT / 'tests'))
    base = c24_table.run_table(True, True, 1.0)[0]
    now = c24_table.run_table(True, True, instant.FITTED_RIVAL_W)[0]
    assert len(now) <= len(base) and {x[1] for x in now} <= {x[1] for x in base}
