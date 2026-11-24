"""x-tick: the one ordered repeat gate in ``tick``: stale slot (U20) -> input state (U17) -> language hold (U19 ``tempo_hold``) -> the cap. One combined test per pair of the four (6 pairs).
Injected clock; the input meter is fed by hand (nothing here measures a call)."""
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from echo_sync.controlled_media import TEMPO_HOLD_SECONDS      # noqa: E402
from echo_sync.input_state import InputMeter      # noqa: E402
from test_h3_tempo import call       # noqa: E402,F401 - call is the fixture
from test_repeat_cases import ASK, P1, P2, P3, rig_of      # noqa: E402

LOG = 'echo-sync'


def armed(call):
    rig = rig_of(call, max_auto_repeats=3)
    rig.asks('u1', ASK, 0, f'{P1} {P2} {P3}')
    rig.pump(0.5)
    c = rig.c
    c.tempo_live = True
    return rig, c, c.state()


def lost_input(c, now):
    c.input_meter = InputMeter(now - 30.0)      # no packet ever: row 1, hold


def with_cause(c, name, now, state):
    if name == 'stale':
        c.repeat_at = now
        c.epoch += 1      # armed under the old token, the owner's token moved without the clear
    elif name == 'input':
        lost_input(c, now)
    elif name == 'language':
        c.tempo_hold = (c._position(state), now)
    elif name == 'cap':
        c.auto_repeat_of = (state['revision'], state['chunk_index'])
        c.auto_repeats = c.max_auto_repeats


PAIRS = [('stale', 'input', 'stale_slot'), ('stale', 'language', 'stale_slot'), ('stale', 'cap', 'stale_slot'),
         ('input', 'language', 'input_hold'), ('input', 'cap', 'input_hold'), ('language', 'cap', 'tempo_hold')]


@pytest.mark.parametrize('first,second,expected', PAIRS)
def test_the_earlier_gate_of_a_pair_speaks_first(call, first, second, expected):
    rig, c, state = armed(call)
    now = c.clock()
    for name in (second, first):
        with_cause(c, name, now, state)
    assert c._repeat_gate(state, now) == expected, (first, second)
    if second == 'cap':
        assert c._silence()[0] >= c._silence()[1], 'the cap holds too: it comes last'


def test_the_tick_blocks_without_counting_and_the_cap_comes_last(call, caplog):
    rig, c, state = armed(call)
    now = c.clock()
    lost_input(c, now)
    c.repeat_at = now
    c.auto_repeat_of = (state['revision'], state['chunk_index'])
    c.auto_repeats = c.max_auto_repeats
    before = (c.auto_repeats, len(rig.said()))
    with caplog.at_level(logging.INFO, logger=LOG):
        assert c.tick(now=now) == []
    assert (c.auto_repeats, len(rig.said())) == before, 'hold is not counted and says nothing'
    assert c.repeat_at is not None, 'the timer stays: the gate asks again when the input changes'
    assert 'reason=repeat_gate' in caplog.text and 'gate=input_hold' in caplog.text
    assert 'auto_repeat_cap' not in caplog.text


def test_unconfirmed_speech_sets_unplaced_and_passes_to_the_cap(call):
    rig, c, state = armed(call)
    now = c.clock()
    m = c.input_meter = InputMeter(now - 10.0)
    for i in range(40):
        m.packet(now - 9.0 + i * 0.2, 6400, dbfs=-30.0)
    m.vad(now - 5.0, 800)
    m.ear(now - 4.0, '', speech_ms=800)
    m.packet(now - 0.1, 6400, dbfs=-30.0)
    assert m.repeat_action(now).act == 'unconfirmed'
    assert c._repeat_gate(state, now) is None
    assert c.unplaced is True and c.unconfirmed_repeats == 0, 'counted where the repeat is said, not at the gate'
    assert c._silence()[1:3] == (3, 'unplaced')


def test_the_defaults_have_no_meter_and_no_gate(call):
    rig, c, state = armed(call)
    assert getattr(c, 'input_meter', None) is None
    assert c._repeat_gate(state, c.clock()) is None


def test_language_hold_ends_by_itself(call):
    rig, c, state = armed(call)
    now = c.clock()
    c.tempo_hold = (c._position(state), now)
    assert c._repeat_gate(state, now + 0.1) == 'tempo_hold'
    assert c._repeat_gate(state, now + TEMPO_HOLD_SECONDS + 0.1) is None


import pytest as _pytest_mic  # noqa: E402


@_pytest_mic.fixture(autouse=True)
def _own_microphone(monkeypatch):
    """This file feeds its own microphone packets (or none: a lost line): the live line of the world stays off (helpers_live_line)."""
    import helpers_s6_state
    monkeypatch.setattr(helpers_s6_state.World, 'mic_stream', False)
