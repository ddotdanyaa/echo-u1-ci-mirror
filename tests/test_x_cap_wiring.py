"""x-cap-2: the one cap of the silent repeats in the controller (``repeat_rule.repeat_cap``), its counters. The rig of ``test_h3_tempo`` on the injected clock; nothing here
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


def writing(rig, places=2):
    """U141: the owner is WRITING, told from their speech: they went on from ``places`` places of this answer (``_record_progress``), the record state is earned. No key."""
    with_settings(rig, cycle_max_repeats=15)
    revision = rig.c.state()['revision']
    for i in range(places):
        rig.c._record_progress((revision, i))
    return rig


def test_the_defaults_keep_the_cap_of_before(call):
    rig = rig_of(call, max_auto_repeats=3)
    rig.asks('u1', ASK, 0, f'{P1} {P2} {P3}')
    assert rig.c._silence()[1:3] == (3, 'plain')
    writing(rig)
    assert rig.c._silence().cap == 15, 'K6: the cycle of about a minute stands with the defaults'
    assert rig.c._silence()[2] == 'record'


def test_the_setter_zero_is_the_owner_and_resets_everything(call):
    c = call(max_auto_repeats=3).c
    c.auto_repeats, c.unconfirmed_repeats, c.unplaced = 2, 1, True
    c.auto_repeats = 3
    assert (c.unconfirmed_repeats, c.unplaced) == (1, True), 'a count is not the owner'
    c.auto_repeats = 0
    assert (c.auto_repeats, c.unconfirmed_repeats, c.unplaced) == (0, 0, False)


def test_unplaced_gives_max_auto_repeats_even_in_the_cycle(call):
    rig = rig_of(call, max_auto_repeats=3)
    rig.asks('u1', ASK, 0, f'{P1} {P2} {P3}')
    writing(rig)
    rig.c.unplaced = True
    assert rig.c._silence()[1:3] == (3, 'unplaced')


def test_a2_matrix_at_most_one_plus_cap_shows_in_a_row(call):
    rig = rig_of(call, max_auto_repeats=3)
    with_settings(rig, cycle_max_repeats=3)
    rig.asks('u1', ASK, 0, f'{P1} {P2} {P3}')
    rig.pump(120.0)
    assert rig.said().count(P1) <= 1 + 3, rig.said()
    assert rig.c._silence().cap == 3


def test_the_cycle_needs_no_dictation_command_and_one_place_gives_wait_and_cap(call):
    """The ONE place of the silent repeat (``repeat_rule.silence``) as the controller reads it: the owner writing (told from their speech), dictation off: the cycle's wait (1 s, then one more for each repeat past 5) and its cap together."""
    rig = rig_of(call, max_auto_repeats=3)
    rig.asks('u1', ASK, 0, f'{P1} {P2} {P3}')
    writing(rig)
    sil = rig.c._silence()
    assert sil.cycling and sil.wait == 1.0 and sil.cap == 15 and sil.why == 'record'
    revision = rig.c.state()['revision']
    rig.c.state = lambda: {'revision': revision, 'chunk_index': 0}      # a portion waits: the count is its own (the same answer the owner went on in)
    rig.c.auto_repeat_of = (revision, 0)
    rig.c.auto_repeats = 7
    assert rig.c._silence().wait == 4.0, 'h28: one second more for each repeat past DICTATION_CYCLE_EASY'


def test_the_gate_is_one_ordered_table():
    from echo_sync.repeat_rule import gate
    assert gate() is None
    assert gate(stale=True, input_act='hold', held=True) == 'stale_slot'
    assert gate(input_act='hold', held=True) == 'input_hold' and gate(input_act='defer') == 'input_defer'
    assert gate(input_act='unconfirmed') is None and gate(input_act='repeat', held=True) == 'tempo_hold'
