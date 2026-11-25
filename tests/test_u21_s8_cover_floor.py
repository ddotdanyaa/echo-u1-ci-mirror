"""U21-S8: C5 the whole-form cover floor, bank_cover_min (0.6 = as it was; measure only): the lost 'казначейство' question becomes the best ranked entry at 0.45 (the miss reason form_min -> low_score; NOT a hit: RANK_MIN 0.70 still holds it back, short check not met), the 'ссылка в Excel' rival abstains."""
import json
from pathlib import Path

import pytest

from echo_sync import instant
from echo_sync.settings import DEFAULTS, resolve

ROOT = Path(__file__).resolve().parents[1]
BANK10 = ROOT.parents[1] / 'МАТЕРИАЛЫ' / 'БАНК' / 'instant_bank_10.json'
KAZNA = 'Федеральное казначейство Российской Федерации что это'


def bank():
    return [r for r in (instant.clean_entry(x) for x in json.load(open(BANK10, encoding='utf-8'))) if r]


def ins(rows, c):
    return instant.Instant([dict(r) for r in rows], adapters=(), cover_min=c)


def test_the_default_is_the_old_floor_and_a_wrong_value_is_the_default():
    assert DEFAULTS['bank_cover_min'] == 0.6 == instant.RANK_COVER_MIN and resolve({})['bank_cover_min'] == 0.6
    assert resolve({'bank_cover_min': 0.45})['bank_cover_min'] == 0.45
    for bad in ('x', True, -0.1, 1.5, None):
        assert resolve({'bank_cover_min': bad})['bank_cover_min'] == 0.6


def test_the_floor_is_in_the_cache_key():
    s = {'instant': 'on', 'bank_cover_min': 0.45}
    instant._built.clear()
    try:
        assert instant.from_settings(s).ranker.cover_min == 0.45
        assert instant.from_settings({**s, 'bank_cover_min': 0.6}).ranker.cover_min == 0.6
        assert instant.from_settings({**s, 'bank_cover_min': 7}).ranker.cover_min == 0.6
    finally:
        instant._built.clear()


@pytest.mark.skipif(not BANK10.exists(), reason='the owner materials are not here')
def test_kaznacheystvo_ranks_first_at_045_without_a_hit_and_the_excel_rival_abstains():
    rows = bank()
    old, low = ins(rows, 0.6), ins(rows, 0.45)
    top = lambda r: (lambda sc, ent: (sc[0][0], r.entries[sc[0][1]]['q']))(*r.rank(KAZNA))
    assert top(old.ranker)[0] == 0.0 and old.ranker.explain(KAZNA) == 'form_min'      # the best-scored form fails the cover floor: the entry is out
    score, q = top(low.ranker)
    assert score == pytest.approx(0.4822, abs=1e-3) and 'казнач' in q.casefold()      # at 0.45 it is the best ranked entry; RANK_MIN still holds it back (measure only)
    assert low.ranker.explain(KAZNA) == 'low_score' and low.ranker.best(KAZNA) is None
    # no hit at the default RANK_MIN and gap: the acceptance 'the question hits at 0.45' is not met (BACKLOG); bending min_score/gap would only turn the test green
    x = 'Что такое абсолютная ссылка в Excel'
    assert low.ranker.rank(x) == old.ranker.rank(x) and low.ranker.best(x) == old.ranker.best(x)      # the 'ссылка в Excel' rival is unmoved: it still abstains against the sure entry


def test_the_tuning_tools_still_move_the_module_floor():
    """c24_table / c24_grid set instant.RANK_COVER_MIN: a Ranker built after it reads the new value (cover_min=None resolves late)."""
    keep = instant.RANK_COVER_MIN
    try:
        instant.RANK_COVER_MIN = 0.1
        assert instant.Instant([]).ranker.cover_min == 0.1
        assert instant.Instant([], cover_min=0.45).ranker.cover_min == 0.45
    finally:
        instant.RANK_COVER_MIN = keep
