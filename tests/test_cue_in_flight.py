"""WAVE 2 / Task B, item 3 (DEF-ACK-20): the prompter's own voice never confirms itself.

Required: a cue-in-flight window, from the first PCM frame sent until the end of the VOICED part of the cue plus a tail margin
(``CUE_TAIL_SECONDS``, about 300 ms), and text that matches the portion and was spoken inside that window is not an ACK. On by
default, in the production profile (the engine's ``echo_guard`` stays off). Every SAPI cue carries about 0.78 s of trailing
silence in its PCM and the repeat timer is armed from the PCM length: the window must end at the last voiced sample, not at the PCM
end, or a genuine fast repeat would be rejected as an echo.

Decision on the trailing silence: in WAVE 2 it was NOT trimmed and the repeat timer was armed from the PCM end. Task S0 reverses
that (the phone keeps its microphone closed until the PCM is over): the transport cuts the silence to pcm_trim.TAIL_KEEP_MS, and the
window AND the repeat timer both count from the last voiced sample (``voiced_seconds``), so how long the listener has to start the
repeat no longer depends on the silence the PCM carries (tests/test_s0_cue_tail.py). Time is injected: nothing here sleeps, except
the tests through the real pacing.

WAVE 2 / Task E: the cue's PCM and the transport (the first frame and the voiced end of every cue are reported, the repeat timer counts from the voiced
end). The drop of an echo (the window of a cue in flight) is gone: the echo is a witness only (tests/test_own_voice_guard.py); the iPhone cancels our
playback and a genuine fast repeat begins inside the cue.
"""
import asyncio
import time
from array import array

import pytest

import helpers_s6_ack as H
from echo_sync import pcm_trim
from echo_sync.controlled_media import CUE_TAIL_SECONDS
from echo_sync.native_media_socket import NativeMediaSocket

ANSWER = 'Свойство тела сопротивляться изменению своего движения. Это называется инерцией. Чем больше масса, тем сильнее инерция.'
# F1 (wave F): the first cue is the first meaning portion - the whole first sentence again (WAVE 2 / L2 had cut it to «Свойство тела»)
PORTION = 'Свойство тела сопротивляться изменению своего движения.'
VOICED, PCM_TAIL = 2.0, 0.78            # a 2 s cue followed by the 0.78 s of trailing silence every SAPI cue carries


def speaks(actions):
    return [a['text'] for a in actions if a['type'] == 'speak']


def playing(tmp_path, *, voiced=VOICED):
    """The first cue is issued and the transport has just sent its first PCM frame (the cue is in flight)."""
    d = H.Dictation(tmp_path / 'flight', ANSWER, play_first=False)
    assert d.current == PORTION
    cue = d.cues[-1]
    d.t0 = d.clock()
    d.controller.cue_started(cue, voiced_seconds=voiced)
    return d, cue


def hear(d, text, *, began, arrived=None, tid=None):
    """A user turn whose speech began at ``began`` (seconds after the first PCM frame) and whose final arrives at ``arrived``."""
    tid = tid or f'u{len(d.controller.seen) + 1}'
    c = d.controller
    d.clock.now = d.t0 + began
    c.speech_started()
    c.provider(H.created(tid, 'user', ''))
    d.clock.now = d.t0 + (arrived if arrived is not None else began)
    before = d.index
    actions = c.provider(H.done(tid, 'user', text))
    return before, d.index, actions


def test_the_repeat_timer_is_armed_from_the_voiced_end(tmp_path):
    """Task S0: the silence after the voice is trimmed (tests/test_s0_cue_tail.py), so the silence timer counts from where the voice
    stopped, not from the PCM end: how long the listener has to begin no longer depends on how much silence the PCM carries."""
    d, cue = playing(tmp_path)
    d.clock.now = d.t0 + VOICED + PCM_TAIL
    d.controller.playback_done(cue, now=d.clock(), voiced_until=d.t0 + VOICED)
    assert d.controller.repeat_at == pytest.approx(d.t0 + VOICED + d.controller.repeat_seconds)


def test_a_genuine_fast_repeat_inside_the_trailing_silence_of_the_pcm_is_accepted(tmp_path):
    d, cue = playing(tmp_path)
    began = VOICED + 0.5                                   # after the margin, before the 0.78 s of silence is over
    assert began < VOICED + PCM_TAIL, 'precondition: inside the PCM'
    before, after, actions = hear(d, PORTION, began=began, arrived=began + 2.0)
    assert after == before + 1 and speaks(actions) == [d.chunks[1]]


def test_speech_that_began_before_the_first_pcm_frame_is_not_the_cue(tmp_path):
    d = H.Dictation(tmp_path / 'late', ANSWER, play_first=False)
    cue = d.cues[-1]
    d.t0 = d.clock() + 0.8                                 # the synthesis took 0.8 s: the first PCM frame goes out now
    c = d.controller
    d.clock.advance(0.3)
    c.speech_started()
    c.provider(H.created('early', 'user', ''))             # the listener already speaks: nothing of ours is audible yet
    d.clock.now = d.t0
    c.cue_started(cue, voiced_seconds=VOICED)
    d.clock.now = d.t0 + 1.0
    actions = c.provider(H.done('early', 'user', PORTION))
    assert d.index == 1 and speaks(actions) == [d.chunks[1]]


def test_a_cue_that_was_never_played_does_not_block_a_repeat_for_ever(tmp_path):
    d = H.Dictation(tmp_path / 'lost', ANSWER, play_first=False)    # issued; the transport never reports anything
    d.clock.advance(30.0)
    out = d.say(PORTION, gap=0, play=False)
    assert out.after == 1, 'a lost cue is not a reason to ignore the listener for ever'


def test_a_cue_whose_end_was_never_reported_does_not_block_a_repeat_for_ever(tmp_path):
    d, cue = playing(tmp_path)                             # started, never finished (a diagnostic took over the audio)
    before, after, _ = hear(d, PORTION, began=VOICED + 10.0)
    assert after == before + 1


def test_commands_and_other_speech_inside_the_window_are_not_blocked(tmp_path):
    d, cue = playing(tmp_path)
    before, after, actions = hear(d, 'повтори', began=0.5)
    assert speaks(actions) == [PORTION] and after == before, '«повтори» is a command, not a confirmation'


# --------------------------------------------------------------------------------------------------------------------
# the PCM and the transport
# --------------------------------------------------------------------------------------------------------------------

RATE = 24000


def pcm_of(voiced_ms, silence_ms, *, lead_ms=0):
    samples = [0] * (RATE * lead_ms // 1000)
    samples += [6000 if (i // 40) % 2 == 0 else -6000 for i in range(RATE * voiced_ms // 1000)]
    samples += [0] * (RATE * silence_ms // 1000)
    return array('h', samples).tobytes()


def test_voiced_seconds_is_the_end_of_the_last_audible_sample():
    assert pcm_trim.voiced_seconds(pcm_of(2000, 780)) == pytest.approx(2.0, abs=0.001)
    assert pcm_trim.voiced_seconds(pcm_of(500, 1000, lead_ms=100)) == pytest.approx(0.6, abs=0.001)


def test_voiced_seconds_ignores_the_quiet_decay_below_the_audible_threshold():
    quiet = array('h', [60 if i % 2 else -60 for i in range(RATE // 10)]).tobytes()      # peaks 60: the engine's own noise floor
    assert pcm_trim.voiced_seconds(pcm_of(1000, 0) + quiet + bytes(RATE)) == pytest.approx(1.0, abs=0.001)


def test_voiced_seconds_of_silence_or_nothing_is_zero():
    assert pcm_trim.voiced_seconds(b'') == 0.0
    assert pcm_trim.voiced_seconds(bytes(RATE * 2)) == 0.0


def test_voiced_seconds_of_a_long_silent_tail_is_the_whole_length_not_a_guess():
    long_tail = pcm_of(300, 0) + bytes(RATE * 2 * 5)                  # 5 s of silence: beyond the scan, unknown
    assert pcm_trim.voiced_seconds(long_tail) == pytest.approx(5.3, abs=0.001)


def test_the_transport_reports_the_first_frame_and_the_voiced_end_of_every_cue():
    calls = []

    class Recorder:
        def authorized(self, cue):
            return True

        def cue_started(self, cue, *, voiced_seconds=None):
            calls.append(('started', time.monotonic(), voiced_seconds))

        def playback_done(self, cue, *, now, voiced_until=None):
            calls.append(('done', now, voiced_until))

    async def run():
        frames = []

        async def emit(frame):
            frames.append(frame)

        async def synthesize(text):
            return pcm_of(200, 300)

        socket = NativeMediaSocket(Recorder(), emit, None, None, synthesize)
        await socket._speak({'text': 'тест'}, socket.audio_generation)
        return frames

    frames = asyncio.run(run())
    assert [c[0] for c in calls] == ['started', 'done'], calls
    (_, began, voiced), (_, ended, voiced_until) = calls
    kept = pcm_trim.TAIL_KEEP_MS / 1000                                 # Task S0: the 0.3 s of silence is cut to this
    assert voiced == pytest.approx(0.2, abs=0.002), 'the voiced length goes with the start'
    assert ended - voiced_until == pytest.approx(kept, abs=0.002), 'done is reported at the end of the PCM sent, the voice stopped before'
    assert ended - began == pytest.approx(0.2 + kept, abs=0.05), 'the PCM sent, paced out in real time'
    assert frames[0]['type'] == 'response.created' and any(f['type'] == 'response.audio.delta' for f in frames[:3])


def test_a_cue_that_is_cut_off_reports_its_start_but_not_its_end():
    calls = []

    class Recorder:
        generation_ok = True

        def authorized(self, cue):
            return self.generation_ok

        def cue_started(self, cue, *, voiced_seconds=None):
            calls.append('started')
            self.generation_ok = False                                  # cancelled right after the first frame

        def playback_done(self, cue, *, now, voiced_until=None):
            calls.append('done')

    async def run():
        async def emit(frame):
            pass

        async def synthesize(text):
            return pcm_of(200, 300)

        socket = NativeMediaSocket(Recorder(), emit, None, None, synthesize)
        await socket._speak({'text': 'тест'}, socket.audio_generation)

    asyncio.run(run())
    assert calls == ['started']
