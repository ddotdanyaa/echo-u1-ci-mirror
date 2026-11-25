"""x-cap-1: the one pure cap of silent repeats (repeat_rule.repeat_cap) and its settings. Not wired into the controller yet."""
import itertools

import pytest

from echo_sync import settings as cfg
from echo_sync.repeat_rule import repeat_cap

CYCLE, PLAIN = 7, 3


def _cap(**kw):
    args = dict(cycling=True, recording=False, unplaced=False, cycle_max_repeats=CYCLE, max_auto_repeats=PLAIN)
    args.update(kw)
    return repeat_cap(**args)


@pytest.mark.parametrize('cycling,recording,unplaced', list(itertools.product([False, True], [False, True], [False, True])))
def test_table_over_every_combination(cycling, recording, unplaced):
    cap, why = _cap(cycling=cycling, recording=recording, unplaced=unplaced)
    if unplaced or not cycling:
        expect = PLAIN
    else:
        expect = CYCLE if recording else PLAIN
    assert cap == expect
    assert isinstance(why, str) and why


@pytest.mark.parametrize('cycling,recording,cycle_max,plain', list(itertools.product([False, True], [False, True], [0, 15, 30], [0, 1, 10])))
def test_unplaced_always_gives_max_auto_repeats(cycling, recording, cycle_max, plain):
    assert _cap(cycling=cycling, recording=recording, unplaced=True, cycle_max_repeats=cycle_max, max_auto_repeats=plain)[0] == plain


def test_why_names_the_row():
    assert _cap(unplaced=True)[1] == 'unplaced'
    assert _cap(cycling=False)[1] == 'plain'
    assert _cap(recording=True)[1] == 'record'
    assert _cap()[1] == 'plain'


def test_settings_defaults():
    r = cfg.resolve(None)
    assert (r['cycle_max_repeats'], r['record_engage_k']) == (15, 2) and 'record_mode' not in r


def test_resolve_clamps_99_to_30():
    assert cfg.resolve({'cycle_max_repeats': 99})['cycle_max_repeats'] == 30
    assert cfg.resolve({'cycle_max_repeats': 0})['cycle_max_repeats'] == 0
    assert cfg.resolve({'cycle_max_repeats': -4})['cycle_max_repeats'] == 0


def test_resolve_bounds_and_bad_values():
    assert cfg.resolve({'record_engage_k': 5})['record_engage_k'] == 5
    assert cfg.resolve({'record_engage_k': 9})['record_engage_k'] == 2
    assert 'repeat_scope' not in cfg.resolve(None)      # w4: the cap counts the portion's repeats only; the answer scope is gone
