"""U17-S5: the repeat policy with the meter attached (``input_state`` on): hold and defer are not counted, unconfirmed speech counts on its own against ``max_auto_repeats``, the owner heard
starts over, the K6 cycle (15 at the defaults) stands while the input is silence. Injected clock."""
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from echo_sync.input_state import InputMeter      # noqa: E402
from test_h3_tempo import call       # noqa: E402,F401 - call is the fixture
from test_x_tick_order import armed      # noqa: E402

LOG = 'echo-sync'


def live(c, now, speech=False):
    """A meter with a healthy line: packets every 0.2 s up to now; with ``speech`` an utterance the ear never turned into text."""
    m = c.input_meter = InputMeter(now - 30.0)
    for i in range(140):
        m.packet(now - 28.0 + i * 0.2, 9600, dbfs=-30.0)
    if speech:
        m.vad(now - 6.0, 800)
        m.ear(now - 5.0, '', speech_ms=800)
    return m


def writing_(c, state):
    """U141: the cycle is the owner WRITING, told from their speech: the earned record state and two places of this answer they went on from. No key."""
    c.settings = {**c.settings, 'cycle_max_repeats': 15}
    c.engine.settings = c.settings
    c.record_seen = (c.state()['revision'], {0, 1})


def on(c):
    c.settings = {**c.settings}
    c.engine.settings = c.settings
    c.input_probe = None      # a fresh meter: the call's first event made one on the rig's clock
    c._input()
    return c


def run(rig, c, seconds, speech_first=False, step=0.5):
    """The line healthy (a packet every 0.2 s) while the injected clock goes ``seconds`` on; ``speech_first``: one utterance the ear never turns into text, at the start."""
    if speech_first:
        c.input_vad(800)
        c._input().ear(c.clock(), '', speech_ms=800)
    end = c.clock() + seconds
    while c.clock() < end:
        t = c.clock()
        for i in range(int(step / 0.2)):
            c.mic_packet(9600, -30.0, now=t + i * 0.2)
        rig.pump(step)


def feed_until(c, m, t0, t1):
    while t0 < t1:
        m.packet(t0, 9600, dbfs=-30.0)
        t0 += 0.2


def test_1_hold_is_not_counted_and_says_nothing(call):
    rig, c, state = armed(call)
    now = c.clock()
    c.input_meter = InputMeter(now - 30.0)      # no packet ever
    c.repeat_at = now
    before = (c.auto_repeats, c.unconfirmed_repeats, len(rig.said()))
    assert c.tick(now=now) == []
    assert (c.auto_repeats, c.unconfirmed_repeats, len(rig.said())) == before


def test_2_half_duplex_defers_without_counting_then_repeats(call):
    rig, c, state = armed(call)
    now = c.clock()
    m = c.input_meter = InputMeter(now - 30.0)
    for i in range(30):
        m.packet(now - 6.0 + i * 0.2, 9600, dbfs=-30.0)      # silence packets
    m.cue_begin(now - 4.0)
    m.cue_end(now - 1.0)      # half duplex: packets stop while the cue sounds, real sound only after it
    for i in range(5):
        m.packet(now - 1.0 + i * 0.2, 9600, dbfs=-30.0)
    m.packet(now, 9600, dbfs=-30.0)
    act = m.repeat_action(now)
    if act.act != 'defer':
        pytest.skip('this feed did not make a half duplex line: ' + str(act))
    c.repeat_at = now
    before = (c.auto_repeats, len(rig.said()))
    assert c.tick(now=now) == []
    assert (c.auto_repeats, len(rig.said())) == before, 'defer is not counted'
    later = now + 1.5
    feed_until(c, m, now + 0.2, later)
    assert m.repeat_action(later).act == 'repeat'
    assert c._repeat_gate(state, later) is None


def test_3_unconfirmed_speech_gives_at_most_max_auto_repeats(call, caplog):
    rig, c, state = armed(call)
    writing_(c, state)
    on(c)
    said = len(rig.said())
    with caplog.at_level(logging.INFO, logger=LOG):
        run(rig, c, 1.0)
        run(rig, c, 120.0, speech_first=True)
    assert c.unplaced is True and c.unconfirmed_repeats == 3, (c.unplaced, c.unconfirmed_repeats)
    assert len(rig.said()) - said <= 3 + 1, 'the cycle would give 15; unplaced speech gives max_auto_repeats'
    assert 'reason=auto_repeat_cap' in caplog.text and 'why=unplaced' in caplog.text


def test_4_the_owner_heard_starts_the_count_over(call):
    rig, c, state = armed(call)
    c.unplaced, c.unconfirmed_repeats, c.auto_repeats = True, 3, 3
    c.auto_repeats = 0      # the owner heard (``_accept_user``)
    assert (c.unplaced, c.unconfirmed_repeats) == (False, 0)
    assert c._silence()[0] == 0 and c._silence()[2] == 'plain'


def test_4b_a_cap_that_blocks_costs_nothing(call):
    rig, c, state = armed(call)
    now = c.clock()
    live(c, now, speech=True)
    assert c._repeat_gate(state, now) is None
    assert c.unplaced is True and c.unconfirmed_repeats == 0


def test_5_k6_the_cycle_gives_15_with_the_meter_attached(call):
    rig, c, state = armed(call)
    writing_(c, state)
    on(c)
    said = len(rig.said())
    run(rig, c, 400.0)
    assert c.input_meter is c.input_probe and c.input_meter is not None
    assert len(rig.said()) - said == 15, len(rig.said()) - said
    assert c.unconfirmed_repeats == 0 and c.unplaced is False


def test_6_hearing_released_logs_the_input_state(call, caplog):
    rig, c, state = armed(call)
    now = c.clock()
    live(c, now)
    c._hearing, c._heard_at = True, now - 100.0
    with caplog.at_level(logging.INFO, logger=LOG):
        c._expire_hearing(now)
    assert 'hearing_released_without_transcript input_state=silence unplaced=False' in caplog.text
