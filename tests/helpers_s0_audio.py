"""Synthetic microphone and cue audio for the task S0 tests: PCM16LE mono 24 kHz, as the phone sends it and as SAPI renders it.

Levels are dBFS RMS (a full-scale square wave is 0 dBFS). Deterministic: every noise has a seed.
"""
import base64
import math
import random
from array import array

RATE = 24000
PACKET_MS = 100                 # the phone sends ~10 packets a second (scripts/DUAL_SYSTEM_DESIGN.md §1.3)
ROOM = -50                      # a quiet room
VOICE = -25                     # the listener's voice at the phone


def ms(n):
    return RATE * n // 1000


def amplitude(dbfs):
    return 32768 * 10 ** (dbfs / 20)


def noise(n_ms, dbfs, seed=1):
    rng = random.Random(seed)
    sigma = amplitude(dbfs)
    return [rng.gauss(0.0, sigma) for _ in range(ms(n_ms))]


def tone(n_ms, dbfs, start=0):
    peak = amplitude(dbfs) * math.sqrt(2)                       # the RMS of a sine is its peak / sqrt(2)
    return [peak * math.sin(2 * math.pi * 150 * (start + i) / RATE) for i in range(ms(n_ms))]


def speech(n_ms, dbfs=VOICE):
    """Syllables: 180 ms voiced (a 150 Hz tone), then a 70 ms dip 25 dB down (a closure, a consonant), for ``n_ms``."""
    out = []
    while len(out) < ms(n_ms):
        out += tone(180, dbfs, start=len(out)) + tone(70, dbfs - 25, start=len(out) + ms(180))
    return out[:ms(n_ms)]


def mix(*layers):
    length = max(len(layer) for layer in layers)
    return [sum(layer[i] for layer in layers if i < len(layer)) for i in range(length)]


def pcm(samples):
    return array('h', (max(-32768, min(32767, int(round(s)))) for s in samples)).tobytes()


def packets(data, packet_ms=PACKET_MS):
    step = 48 * packet_ms
    return [data[i:i + step] for i in range(0, len(data), step)]


def appends(data, packet_ms=PACKET_MS):
    """The phone's ``input_audio_buffer.append`` events for ``data``, one per packet."""
    return [{'type': 'input_audio_buffer.append', 'audio': base64.b64encode(chunk).decode('ascii')}
            for chunk in packets(data, packet_ms)]


def room(seconds, dbfs=ROOM, seed=11):
    return appends(pcm(noise(int(seconds * 1000), dbfs, seed=seed)))


def talking(seconds, dbfs=VOICE, seed=12):
    n_ms = int(seconds * 1000)
    return appends(pcm(mix(noise(n_ms, ROOM, seed=seed), speech(n_ms, dbfs))))


def cue_pcm(voiced_ms, silence_ms=0, *, lead_ms=0):
    """A cue as SAPI renders it: voice (a loud square-ish wave), then the engine's silence."""
    samples = [0] * ms(lead_ms)
    samples += [6000 if (i // 40) % 2 == 0 else -6000 for i in range(ms(voiced_ms))]
    samples += [0] * ms(silence_ms)
    return array('h', samples).tobytes()
