"""x-cap-2: the one cap of the silent repeats in the controller (``repeat_rule.repeat_cap``), its counters and the scope. The rig of ``test_h3_tempo`` on the injected clock; nothing here
is a measurement of a call."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from echo_sync.settings import resolve      # noqa: E402
from test_h3_tempo import HEAD, PORTION, call       # noqa: E402,F401 - call is the fixture
from test_repeat_cases import ASK, P1, P2, P3, rig_of      # noqa: E402


def with_settings(rig, **flags):
    rig.c.settings = {**rig.c.settings, **flags}
    rig.c.engine.settings = rig.c.settings
    return rig


def test_the_defaults_keep_the_cap_of_before(call):
    rig = call(max_auto_repeats=3)
    assert rig.c._cap_count() == (0, 3, 'plain', 'portion')
    with_settings(rig, dictation_cycle='on')
    assert rig.c._repeat_cap() == 15, 'K6: the cycle of about a minute stands with the defaults'
    assert rig.c._cap_count()[2] == 'cycle'


def test_the_setter_zero_is_the_owner_and_resets_everything(call):
    c = call(max_auto_repeats=3).c
    c.auto_repeats, c.answer_repeats, c.unconfirmed_repeats, c.unplaced = 2, 5, 1, True
    c.auto_repeats = 3
    assert (c.answer_repeats, c.unconfirmed_repeats, c.unplaced) == (5, 1, True), 'a count is not the owner'
    c.auto_repeats = 0
    assert (c.auto_repeats, c.answer_repeats, c.unconfirmed_repeats, c.unplaced) == (0, 0, 0, False)


def test_unplaced_gives_max_auto_repeats_even_in_the_cycle(call):
    rig = with_settings(call(max_auto_repeats=3), dictation_cycle='on')
    rig.c.unplaced = True
    assert rig.c._cap_count()[1:3] == (3, 'unplaced')


def test_a_new_portion_keeps_the_answer_count_and_a_new_revision_resets_it(call):
    rig = call(max_auto_repeats=3)
    rig.second_portion()
    rig.c.repeat_at = rig.w.clock.t       # tick reads the state; the count of the answer is what is under test
    rig.pump(10.0)
    assert rig.c.answer_repeats >= 1
    before = rig.c.answer_repeats
    rig.c.auto_repeat_of = (rig.c.state()['revision'] - 1, 0)
    rig.c._auto_repeats = 0
    rig.c.repeat_at = rig.w.clock.t
    rig.pump(0.5)
    assert rig.c.answer_repeats <= 1 and before >= 1, 'another revision: a new answer'


def test_answer_scope_two_portions_give_three_shows(call):
    rig = with_settings(rig_of(call, max_auto_repeats=3), repeat_scope='answer')
    rig.asks('u1', ASK, 0, f'{P1} {P2} {P3}')
    assert rig.said() == [P1]
    rig.pump(rig.c.repeat_seconds + 0.5)
    assert rig.said() == [P1, P1]
    real = rig.c.state
    rig.c.state = lambda: {**real(), 'chunk_index': 1}      # the plan goes on to its second portion with no word of the owner
    rig.pump(60.0)
    shows = rig.said()
    assert shows[:2] == [P1, P1] and P2 in shows, shows
    assert len(shows) - 1 == 3 and rig.c.answer_repeats == 3, 'one repeat of the first portion, two of the second: the answer is capped, not each portion'


@pytest.mark.parametrize('cycle', ['on', 'off'])
@pytest.mark.parametrize('scope', ['portion', 'answer'])
@pytest.mark.parametrize('record', ['off', 'earned'])
def test_a2_matrix_at_most_one_plus_cap_shows_in_a_row(call, cycle, scope, record):
    rig = rig_of(call, max_auto_repeats=3)
    with_settings(rig, dictation_cycle=cycle, repeat_scope=scope, record_mode=record, cycle_max_repeats=3)
    rig.asks('u1', ASK, 0, f'{P1} {P2} {P3}')
    rig.pump(120.0)
    assert rig.said().count(P1) <= 1 + 3, (cycle, scope, record, rig.said())
    assert rig.c._repeat_cap() == 3
