"""W5 stumble: the 300-row table (``helpers_w5_pace``) row by row, and a short run of the simulation of tempos: what WAVE5 asks, measured on the pure module, the ear's detector and its text lag
as the phone has them (300 ms of quiet, text 0.2 s after the offset). Nothing here is a measurement of a call."""
from collections import Counter

import pytest

import helpers_w5_pace as H

TABLE = H.run_table()


def test_the_table_has_300_rows_of_every_kind_and_tempo():
    assert len(TABLE) == 300
    kinds = Counter(r.kind for r, *_ in TABLE)
    assert set(kinds) == set(H.KINDS) and min(kinds.values()) >= 10
    assert {r.tempo for r, *_ in TABLE} == {t.name for t in H.TEMPOS}


@pytest.mark.parametrize('n', range(300))
def test_row(n):
    row, d, t, lat, v, text = TABLE[n]
    assert v == 'OK', (row.kind, row.tempo, row.portion, row.stop, row.expect, d, lat, text)


def test_help_on_a_real_stumble_inside_a_group_is_in_the_target_for_all_but_the_slowest():
    lats = [lat + H.DELIVERY for r, d, t, lat, v, _ in TABLE if r.kind in ('stall_inner', 'stall_number') and r.tempo not in ('very_slow',)]
    assert lats and max(lats) <= H.TARGET[1] + 1e-6 and min(lats) >= H.TARGET[0] - 1e-6


def test_help_after_a_filler_and_its_kin_is_sooner_than_any_wait_of_today():
    lats = [lat for r, d, t, lat, v, _ in TABLE if r.kind in ('filler', 'stretch', 'restart', 'cut')]
    assert max(lats) <= 0.6 + 1e-6


@pytest.fixture(scope='module')
def sim():
    return H.simulate(n_per_tempo=60, seed=11)


def test_the_simulation_costs_less_than_today_at_every_tempo(sim):
    for name, r in sim.items():
        for share in (0.1, 0.2, 0.4):
            assert H.price(r['pace'], share)[0] <= H.price(r['today'], share)[0] + 0.02, (name, share)


def test_false_prompts_are_rare_for_the_usual_tempos_and_help_twice_as_soon_inside_a_group(sim):
    for name in ('very_fast', 'fast', 'normal'):
        r = sim[name]
        assert r['pace']['false'] <= 0.02 * r['pace']['fluent'], name       # pauses with no cap: one in 60 portions on this seed for «normal», 0 in 400 on the report's
        assert H.pct(r['pace']['lat'], 0.9) <= H.TARGET[1] and H.pct(r['pace']['lat'], 0.5) * 2 <= H.pct(r['today']['lat'], 0.5) + 0.3
