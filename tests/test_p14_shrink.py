"""U33 (P14): a failing rehearsal seed is cut down to its smallest scene by ddmin, through the real controller of the stand (virtual time, no model, no network)."""
import logging
from functools import partial

import pytest

from tools.rehearsal import shrink, sim

SPEC = 'Короткая | min=1 ask=op09'


@pytest.fixture(autouse=True)
def quiet():
    logging.disable(logging.WARNING)
    yield
    logging.disable(logging.NOTSET)


def test_a_broken_controller_seed_shrinks_to_fewer_moves_that_still_fail_and_are_minimal():
    spec = sim.Spec('Т001', SPEC)
    got = shrink.shrink(spec, 0, mutant='mute')
    assert got and got['kind'] == 'missed' and got['scripted'] and got['moves_recorded'] > len(got['moves']) >= 1, got
    holds = lambda items: got['kind'] in shrink.kinds_of(sim.play(spec, 0, mutant='mute', keep_log=False, stand=partial(shrink.Scripted, moves=items)))      # noqa: E731
    assert holds(got['moves'])
    assert not any(holds(got['moves'][:n] + got['moves'][n + 1:]) for n in range(len(got['moves']))), '1-minimal: no single move can be dropped'


def test_a_clean_seed_has_nothing_to_shrink():
    spec = sim.Spec('Т002', 'Тихая | min=0.3 ask=op09 user=silence:1 idle=silence:1')
    assert shrink.shrink(spec, 0, kind='old_answer') is None


def test_a_recorded_conversation_is_the_same_each_time():
    spec = sim.Spec('Т001', SPEC)
    one, two = (shrink.shrink(spec, 0, mutant='mute') for _ in range(2))
    assert one['moves'] == two['moves']
