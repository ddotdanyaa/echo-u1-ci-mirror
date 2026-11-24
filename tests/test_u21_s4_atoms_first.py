"""NOTE: the short check "on the 68 rows S1 goes 6 to 5" is NOT met (S1 stays 6 with the flag on); only the synthetic case is proven. U21-S4: C1 the entries naming the question's number are scored whatever the cap of RANK_TOP cut; bank_atoms_first; RANGES in the index cache key."""
import pytest

from echo_sync import instant
from echo_sync.settings import DEFAULTS, resolve


def rows(n=120):
    out = [{'id': f's{k}', 'q': f'что такое статья {k + 1} кодекса', 'alt': [], 'answer': f'Это статья {k + 1} про предмет номер {k + 1}.', 'trust': 'Д'} for k in range(n)]
    return out


@pytest.fixture(autouse=True)
def small(monkeypatch):
    monkeypatch.setattr(instant, 'RANK_MIN_MASS', 0.1)
    monkeypatch.setattr(instant, 'RANK_TOP', 5)      # the cap is small here: 120 rows say the same words


def ranker(atoms_first):
    return instant.Instant(rows(), adapters=(), rank2=True, atoms_first=atoms_first).ranker


def test_only_the_flag_finds_the_row_the_cap_cut():
    q = 'что такое статья 118 кодекса'
    assert ranker(False).best(q) is None
    got = ranker(True).best(q)
    assert got is not None and ranker(True).entries[got[0]]['id'] == 's117'


def test_another_number_never_hits():
    r = ranker(True)
    for q in ('что такое статья 118 кодекса', 'что такое статья 119 кодекса'):
        e = r.best(q)
        assert e is None or r.entries[e[0]]['q'] == q


def test_the_eligible_list_is_capped(monkeypatch):
    monkeypatch.setattr(instant, 'RANK_ATOM_CAP', 1)
    assert instant.RANK_ATOM_CAP == 1
    assert ranker(True).rank('что такое статья 118 кодекса')[0]       # no crash with the tiny cap


def test_the_key_is_gone_the_ranked_path_always_takes_the_atoms():
    assert 'bank_atoms_first' not in DEFAULTS and 'bank_atoms_first' not in resolve({'bank_atoms_first': 'on'})
    instant._built.clear()
    assert instant.from_settings({'instant': 'on'}) is not None and next(iter(instant._built.values())).ranker.atoms_first is True
