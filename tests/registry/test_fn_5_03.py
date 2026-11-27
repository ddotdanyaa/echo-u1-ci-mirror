"""Registry 5.03 «Удержание и подача звука: голова подсказки, обрезка очереди микрофона»; state by the registry: ВЫКЛЮЧЕНО.

Proved through the real controlled_host.serve (tests/helpers_s6_fault.HostRig: real controller + NativeMediaSocket + engine; only the phone,
the helper pipe, SAPI, the lookup and the clock are fake). No profile file is written: the code defaults of audio_head_ms act (U77: mic_path is gone, the trim of the microphone queue is always on).
The head test describes the WORKING function and is marked xfail strict while its key is off (the microphone-queue test is green, U77); it turns into XPASS when it is switched on.
 1 head of a cue: the owner asks, the cloud answers, the first portion (1 s of voice) goes to the phone with its PCM frames AHEAD of real time
   (the last frame leaves well before the voice has played), while response.done stays at the real end of the voice
 2 trim of the microphone queue: the phone stalls 0.6 s and its late QUIET packets arrive in a burst; the helper must get fewer packets than
   the phone sent (the quiet backlog is given back), and every loud (speech) packet must still reach the helper
Dummy check (private copy, both outcomes): DEFAULTS audio_head_ms=250 and mic_path='trim' in echo_sync/settings.py turn both tests green;
with --runxfail and the defaults they fail on the claims about the function (not on a stand error).
Cloud stand on virtual time: a calculation of the code's schedule, not a measurement of the laptop or the phone."""
import base64
import math
import struct

import pytest

import helpers_s6_fault as F

FRAME = 0.02


async def cue_times(host):
    """Ask, answer, and return (PCM frame times of the first cue relative to its first frame, time of its response.done)."""
    await host.ask(F.DIRECT_QUESTION)
    await host.answer(F.DIRECT_ANSWER)
    assert await host.until(lambda: any(f.type == 'response.done' for f in host.ws.frames), 20)
    audio = [f.t for f in host.audio()]
    done = next(f.t for f in host.ws.frames if f.type == 'response.done')
    return [t - audio[0] for t in audio], done - audio[0]


@pytest.mark.xfail(strict=True, reason="реестр 5.03: ВЫКЛЮЧЕНО (audio_head_ms=0): голова подсказки уходит телефону как обычно, без упреждения")
def test_head_of_the_cue_leaves_ahead_of_real_time(tmp_path, monkeypatch):
    from helpers_spoken_diagnostics import run_host

    async def body(host):
        times, done = await cue_times(host)
        assert len(times) >= 40, len(times)                         # a whole second of voice (50 frames of 20 ms)
        assert times[-1] < (len(times) - 1) * FRAME - 0.1, times[-1]   # the last frame left a head before real time
        assert done >= len(times) * FRAME - 0.05, done                 # but «done» stays at the real end of the voice
    run_host(tmp_path, monkeypatch, body, synth=[('long', 1.0)])


def packet(kind, ms=100):
    n = 24 * ms
    raw = struct.pack('<%dh' % n, *(int(8000 * math.sin(2 * math.pi * 440 * i / 24000)) for i in range(n))) if kind == 'loud' else b'\0' * (48 * ms)
    return base64.b64encode(raw).decode()


def test_quiet_backlog_of_the_microphone_queue_is_given_back(tmp_path, monkeypatch):
    from helpers_spoken_diagnostics import run_host

    async def body(host):
        before = len(host.bridge.sent)
        sent = {'loud': 0, 'quiet': 0}

        def push(kind):
            sent[kind] += 1
            host.ws.push({'type': 'input_audio_buffer.append', 'audio': packet(kind)})
        for _ in range(5):                                         # steady speech, a packet per 100 ms
            push('loud');await host.advance(0.1)
        await host.advance(0.6)                                    # the phone stalls
        for _ in range(6):push('quiet')                            # the late ones in one burst
        await host.advance(0.05)
        for _ in range(10):                                        # steady again, quiet
            push('quiet');await host.advance(0.1)
        await host.advance(0.5)
        audio = [p for k, p in host.bridge.sent[before:] if k == 'P']
        loud = [p for p in audio if any(p)]
        assert len(loud) == sent['loud'], (len(loud), sent)       # speech is never dropped
        assert len(audio) < sent['loud'] + sent['quiet'] - 3, (len(audio), sent)   # a quiet backlog was given back
    run_host(tmp_path, monkeypatch, body)
