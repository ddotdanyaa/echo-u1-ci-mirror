"""U237 breakD, class «the server restarts / the line flaps / the laptop sleeps on a call» (what the owner did again and again: the call drops on the tunnel, the helper is restarted, the clock jumps).
The new connection is a NEW ControlledMedia over the same session database (Dictation.reconnect: built as the host builds it). Nothing may be said by itself, nothing may move by itself, and the owner's next word works.
Existing tests (test_bad_network) take ONE drop with the portion waiting; here: a flap, a stale cue, a stop that must outlive the restart, a clock that jumps."""
import pytest

import helpers_s6_ack as H
from bw_common import silence, speaks, waiting


def test_w01_after_a_restart_the_waiting_portion_is_where_it_was_and_next_goes_exactly_one_on(tmp_path):
    d = waiting(tmp_path)
    index, plan = d.index, d.chunks
    nd = d.reconnect()
    assert nd.index == index and nd.chunks == plan, 'the restart lost or moved the portion'
    out = nd.say('Дальше.')
    assert out.after == index + 1 and out.speaks == [plan[index + 1]], out.actions
    assert out.model_calls == 0 and not out.destroyed


def test_w02_five_restarts_in_ten_seconds_then_two_minutes_of_silence_say_nothing_and_move_nothing(tmp_path):
    d = waiting(tmp_path)
    index, plan = d.index, d.chunks
    nd = d
    heard = []
    for _ in range(5):
        d.clock.advance(2.0)
        nd = nd.reconnect()
        heard += silence(nd, 1.0, step=0.5)
    assert heard == [], f'a flapping line made the app talk by itself: {heard}'
    later = silence(nd, 120, step=2.0)
    assert (nd.index, nd.chunks) == (index, plan), 'a flap of the line moved the answer'
    assert set(later) <= {plan[index]}, f'silence after the flap said something but the waiting portion: {later}'
    assert nd.say(nd.current).after == index + 1, 'the owner\'s repeat after the flap does not count'


def test_w03_the_end_of_a_cue_of_the_dead_connection_reported_to_the_new_one_arms_nothing(tmp_path):
    d = waiting(tmp_path)
    stale = d.cues[-1]                                  # the cue the old connection played
    index = d.index
    nd = d.reconnect()
    nd.clock.advance(1.0)
    nd.controller.playback_done(stale, now=nd.clock())  # the transport of the old line reports late
    assert not nd.controller.authorized(stale), 'a cue of the dead connection is still authorized'
    assert silence(nd, 20, step=2.0) == [], 'a stale end of cue made the new line speak at once'
    later = silence(nd, 300, step=2.0)
    assert nd.index == index and set(later) <= {nd.current}, f'a stale end of cue made the new line speak another portion: {later}'


def test_w04_a_stop_given_before_the_restart_still_holds_after_it(tmp_path):
    d = waiting(tmp_path)
    assert d.say('Стоп.').types == ['cancel'] and d.state.get('paused')
    index = d.index
    nd = d.reconnect()
    assert nd.state.get('paused'), 'the pause was forgotten by the restart'
    assert silence(nd, 3600, step=60.0) == [], 'after a restart the app started reading again although the owner said stop'
    assert nd.index == index


def test_w05_the_laptop_sleeps_for_hours_one_tick_after_it_is_one_cue_at_most(tmp_path):
    d = waiting(tmp_path)
    index = d.index
    total = []
    for _ in range(3):
        d.clock.advance(3 * 3600.0)                     # the clock jumps three hours between two ticks
        actions = d.controller.tick(now=d.clock())
        assert len(speaks(actions)) <= 1, f'one tick after a long sleep said {len(speaks(actions))} cues: a storm'
        total += speaks(actions)
        d.play(actions)
    assert d.index == index, 'the sleep moved the cursor'
    assert len(total) <= 3
    assert d.say(d.current).after == index + 1
