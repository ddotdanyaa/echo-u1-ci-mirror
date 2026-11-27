"""Registry 5.05a: «Цикл повторов без команд, пока человек пишет» (the dictation cycle: silence repeats the portion on its own).

Registry state: РАБОТАЕТ НА СЕРВЕРЕ. Proved here, through the real ControlledMedia + NativeMediaSocket (tests/helpers_s6_state.World; fakes only at the boundary):
the cloud answers a question, the phone streams live (quiet, non-zero) microphone packets and the person says nothing, because they are writing. Then the same
portion is voiced again and again on its own, with no voice command, at a pace that stretches from about 1 s to 8 s, and the cycle is not cut at max_auto_repeats
(3): 14 repeats in a minute. With dictation_cycle=off the same silence gives the plain behaviour (about 2.2 s apart, three repeats and quiet).
Live profile: dictation_cycle=on (code default off), cycle_max_repeats=15, repeat_rule=on, input_state=on, repeat_seconds=2.0 (code default 6.0), max_auto_repeats=3.
Live record_mode=earned: pure silence on the first portion stops at 3 repeats (test 2), but once the person has gone on 2 places (3.07) the silence repeats the portion up to the
cycle ceiling 15, with no command (test 4, the live path). The cap test with record_mode=off shows the ceiling without the record state.
Dummy check: dictation_cycle=off (the CYCLE constant below)."""
import base64
import struct
from contextlib import contextmanager

import helpers_night_memory as M      # the stand's own controller_settings and resolve: the test survives a move of that code
import helpers_s6_fault as F
import helpers_s6_state as S

CYCLE = 'on'      # the key under test (the live server value; the code default is off)
MIC = {'type': 'input_audio_buffer.append', 'audio': base64.b64encode(struct.pack('<480h', *[(i % 7 - 3) * 40 for i in range(480)])).decode()}      # quiet, not digital zero


@contextmanager
def call(**flags):
    """A World whose controller gets the live profile (as tests/helpers_night_memory.Call does); the substitution is undone and the stand closed."""
    profile = M.resolve({'repeat_rule': 'on', 'input_state': 'on', 'repeat_seconds': 2.0, 'max_auto_repeats': 3, 'cycle_max_repeats': 15, **flags})
    original = S.host_kwargs
    host = {'settings': M.controller_settings(profile), 'repeat_seconds': profile['repeat_seconds'], 'max_auto_repeats': profile['max_auto_repeats']}
    S.host_kwargs = lambda: {**original(), **host}
    world = S.World()
    try:
        yield world
    finally:
        world.close()
        S.host_kwargs = original


ANSWER = ('Инерция — это свойство тела сохранять покой или равномерное движение. Оно проявляется, когда на тело не действуют другие силы. '
          'Масса тела служит мерой его инертности. Поэтому тяжёлую тележку труднее раскачать.')      # four short portions


def silence(w, seconds, goes_on=0):
    """The person writes and says nothing; the phone keeps sending microphone packets. goes_on: how many portions they first say aloud, one after another (the record state, 3.07).
    Returns (the cue of the portion they are on, the repeats of it, the cloud frames sent meanwhile)."""
    w.feed(S.turn_done('u1', 'user', F.DIRECT_QUESTION))
    w.feed(S.turn_done('a1', 'assistant', ANSWER if goes_on else F.DIRECT_ANSWER))
    for i in range(goes_on):
        w.advance(3.0)
        w.feed(S.turn_done(f'u{i + 2}', 'user', w.cues[-1].text))      # the portion said back: the cloud's final of it moves the plan on
        w.advance(1.0)
    first, sent, base = w.cues[-1], len(w.source.frames), len(w.cues)
    for _ in range(int(seconds / 0.5)):
        for _ in range(3):
            w.client(MIC)
        w.advance(0.5)
    assert not w.errors and not w.violations, (w.errors, w.violations)
    return first, [c for c in w.cues[base:] if not c.diagnostic], w.source.frames[sent:]


def gaps(first, repeats):
    times = [first.t] + [c.t for c in repeats]
    return [round(b - a, 1) for a, b in zip(times, times[1:])]


def test_silence_repeats_the_portion_every_few_seconds_without_a_command():
    with call(dictation_cycle=CYCLE, record_mode='off') as w:
        first, repeats, to_cloud = silence(w, 60)
        gap = gaps(first, repeats)
        assert len(repeats) >= 10, f'{len(repeats)} repeats in a minute of silence, gaps {gap}'      # the registry: 13 in a minute
        assert all(c.text == first.text and c.audio_frames and c.done for c in repeats), 'every repeat is the same portion, voiced whole'
        assert w.synth_calls == [first.text] * (1 + len(repeats)), 'the portion went to synthesis each time, and nothing else did'
        assert min(gap) >= 1.0 and max(gap) <= 8.7 and gap[-1] >= 6.0, gap      # the pause stretches to the 8 s ceiling
        assert gap[0] <= 4.0 and max(gap[1:5]) <= 1.5 < gap[-1], gap      # the first wait includes the mic warming up; then the cycle's pace
        assert w.cues[-1].t - w.clock.t > -10, 'the cycle goes on at the end of the minute: it is not cut by a ceiling'
        assert len(repeats) > 3, 'past max_auto_repeats'
        assert not [f for k, f in to_cloud if k != 'P'], 'only the microphone audio went to the cloud: no command, no model call'


def test_the_live_profile_repeats_at_the_cycle_pace_and_stops_at_three_until_the_person_goes_on():
    with call(dictation_cycle=CYCLE, record_mode='earned') as w:      # the live pair: the cap is lifted only by the record state (3.07)
        first, repeats, _ = silence(w, 40)
        gap = gaps(first, repeats)
        assert len(repeats) == 3 and max(gap[1:]) <= 1.5, gap      # the cycle's 1 s pace (the plain pace is 2.2 s), then the plain cap of 3


def test_without_the_cycle_the_silence_gives_the_plain_three_repeats():
    with call(dictation_cycle='off', record_mode='off') as w:      # the contrast: this is what the person got before the cycle
        first, repeats, _ = silence(w, 60)
        gap = gaps(first, repeats)
        assert len(repeats) == 3 and min(gap[1:]) >= 2.0, gap


def test_the_live_profile_after_the_person_went_on_two_places_repeats_up_to_the_cycle_ceiling_without_commands():
    with call(dictation_cycle=CYCLE, record_mode='earned') as w:      # the live pair, no record_mode change: the record state lifts the cap (3.07)
        first, repeats, to_cloud = silence(w, 100, goes_on=2)
        gap = gaps(first, repeats)
        assert first.text.startswith('Масса тела') and not w.cues[-1].diagnostic, 'the person is on the third portion'
        assert len(repeats) == 15, f'{len(repeats)} repeats, gaps {gap}'      # past the plain 3, up to cycle_max_repeats, then quiet
        assert all(c.text == first.text and c.audio_frames and c.done for c in repeats) and w.synth_calls[-16:] == [first.text] * 16, 'the same portion, voiced whole each time'
        assert max(gap[1:5]) <= 1.5 < gap[-1] <= 8.7, gap      # the cycle's pace, stretching to the ceiling pause
        assert not [f for k, f in to_cloud if k != 'P'], 'only microphone audio went to the cloud while the person wrote: no command'
