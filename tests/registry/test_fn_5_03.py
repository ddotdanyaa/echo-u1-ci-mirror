"""Registry 5.03 «Удержание и подача звука: обрезка очереди микрофона». The head of a cue (audio_head_ms, Б11) was off, never measured, and is deleted (w4 speech/wire-playout).

Proved through the real controlled_host.serve (tests/helpers_s6_fault.HostRig: real controller + NativeMediaSocket + engine; only the phone,
the helper pipe, SAPI, the lookup and the clock are fake). No profile file is written (U77: mic_path is gone, the trim of the microphone queue is always on).
 1 trim of the microphone queue: the phone stalls 0.6 s and its late QUIET packets arrive in a burst; the helper must get fewer packets than
   the phone sent (the quiet backlog is given back), and every loud (speech) packet must still reach the helper
Cloud stand on virtual time: a calculation of the code's schedule, not a measurement of the laptop or the phone."""
import base64
import math
import struct


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
