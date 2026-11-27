"""Task R-VAD test helpers: a scripted Silero model, the packaged SAPI phrases as real speech, and the "is the real model installed" gate."""
import array
import asyncio
import json
import math
import time
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from echo_sync import controlled_host, settings as cfg, vad_silero
from echo_sync.vad_silero import SileroOnset
from helpers_s0_audio import PACKET_MS, RATE, ROOM, mix, ms, noise, packets, pcm

DIAG = Path(__file__).resolve().parents[1] / 'echo_sync' / 'diag_audio'
WINDOW = 512                                    # samples of 16 kHz audio per model call (32 ms)


class ScriptedModel:
    """The boundary of sherpa-onnx's ``VadModel``: ``window_size()``, ``is_speech(window)``, ``reset()``. The verdict of window k is
    ``script[k]`` (silence once the script is over). sherpa-onnx EXITS THE WHOLE PROCESS on a window of the wrong size, so this
    boundary records every such call (``wrong``) for the test to see even if the code under test swallows the exception."""

    def __init__(self, script=(), *, fail_at=None):
        self.script, self.fail_at = list(script), fail_at
        self.calls, self.wrong, self.windows = 0, [], []

    def window_size(self):
        return WINDOW

    def is_speech(self, window):
        if len(window) != WINDOW or not all(-1.0 <= value <= 1.0 for value in window):
            self.wrong.append(len(window))
            raise ValueError('wrong window')
        self.windows.append(list(window))
        k, self.calls = self.calls, self.calls + 1
        if self.fail_at is not None and k >= self.fail_at:
            raise RuntimeError('onnx runtime failed: some words')
        return bool(self.script[k]) if k < len(self.script) else False

    def reset(self):
        pass


def _model_ready():
    try:
        import sherpa_onnx  # noqa: F401
    except ImportError:
        return False
    return Path(vad_silero.default_model_path()).is_file()


MODEL_READY = _model_ready()
needs_model = pytest.mark.skipif(not MODEL_READY, reason='sherpa-onnx or the Silero VAD model is not installed here')


def phrase(name):
    """A packaged SAPI phrase (Microsoft Irina, 24 kHz) as samples."""
    with wave.open(str(DIAG / f'{name}.wav'), 'rb') as handle:
        assert handle.getframerate() == RATE and handle.getnchannels() == 1 and handle.getsampwidth() == 2
        samples = array.array('h')
        samples.frombytes(handle.readframes(handle.getnframes()))
    return list(samples)


def voiced_span(samples, rate=RATE):
    """(start, end) in seconds of the speech: first/last 10 ms frame within 40 dB of the loudest one (the bake-off's definition)."""
    size = rate // 100
    levels = [10 * math.log10(max(sum(v * v for v in samples[i:i + size]) / size, 1.0)) for i in range(0, len(samples) - size + 1, size)]
    loud = [i for i, level in enumerate(levels) if level >= max(levels) - 40]
    return loud[0] * 0.01, (loud[-1] + 1) * 0.01


def active_dbfs(samples):
    """The level of the speech itself (dBFS RMS between its first and last voiced frame)."""
    start, end = voiced_span(samples)
    body = samples[int(start * RATE):int(end * RATE)]
    return 10 * math.log10(sum(v * v for v in body) / len(body) / 32768.0 ** 2)


def scene(name, *, lead_ms=1500, tail_ms=2500, background=None):
    """The phrase between stretches of room tone (or ``background``: a function of the number of ms -> noise samples), as PCM, and the
    phrase's voiced span (start s, end s) on the audio's timeline."""
    samples = phrase(name)
    start, end = voiced_span(samples)
    background = background or (lambda n: noise(n, ROOM, seed=3))
    body = [0.0] * ms(lead_ms) + samples + [0.0] * ms(tail_ms)
    data = pcm(mix(background(lead_ms + 1000 * len(samples) // RATE + tail_ms), body))
    return data, (lead_ms / 1000 + start, lead_ms / 1000 + end)


def play(name, **options):
    """``scene`` through the real model packet by packet: (events, speaking after each packet, the voiced span)."""
    data, span = scene(name, **options)
    detector = SileroOnset()
    events, speaking = [], []
    for packet in packets(data, PACKET_MS):
        events.append(detector.feed(packet))
        speaking.append(detector.speaking)
    return events, speaking, span


def _varint(number):
    out = bytearray()
    while True:
        low, number = number & 0x7F, number >> 7
        out.append(low | (0x80 if number else 0))
        if not number:
            return bytes(out)


def _field(number, wire, payload):
    return _varint((number << 3) | wire) + payload


def _delimited(number, data):
    return _field(number, 2, _varint(len(data)) + data)


def _info(name):
    """ValueInfoProto of a float tensor of 4 values."""
    tensor = _field(1, 0, _varint(1)) + _delimited(2, _delimited(1, _field(1, 0, _varint(4))))
    return _delimited(1, name.encode()) + _delimited(2, _delimited(1, tensor))


def not_silero_onnx():
    """65 bytes of VALID ONNX (one Identity node) that onnxruntime loads and that are not a Silero graph: what sherpa-onnx answers to
    it is «Unsupported silero vad model» and exit(-1) - the same as for the recognizer's own decoder.onnx / joiner.int8.onnx."""
    node = _delimited(1, b'x') + _delimited(2, b'y') + _delimited(4, b'Identity')
    graph = _delimited(1, node) + _delimited(2, b'g') + _delimited(11, _info('x')) + _delimited(12, _info('y'))
    return _field(1, 0, _varint(8)) + _delimited(7, graph) + _delimited(8, _delimited(1, b'') + _field(2, 0, _varint(13)))


class Hangup(Exception):
    pass


def serve_timed(home, settings=None, *, until=None, patience=5.0):
    """``test_s0_onset_modes.serve_with`` (one call opened with controlled_host.serve against fakes: no helper, no SAPI, no network), but the
    phone does not hang up at once: it keeps the call open until ``until(wire)`` is true (at most ``patience`` s) - and it notes when the host
    first reads the phone and what the transport's ear was then. Returns (the transport, {'first_receive_s', 'engine_then'})."""
    (home / 'echo-sync').mkdir(parents=True)
    if settings is not None:
        (home / 'materials').mkdir()
        (home / 'materials' / cfg.SETTINGS_FILE).write_text(json.dumps(settings), encoding='utf-8')
    built, seen = {}, {}

    class Spy(controlled_host.NativeMediaSocket):
        def __init__(self, *args, **options):
            super().__init__(*args, **options)
            built['wire'] = self

            async def no_pre_render(synthesize):
                return
            self.diagnostic_audio.prerender = no_pre_render

    class Phone:
        query_params = {}

        async def receive_text(self):
            wire = built['wire']
            seen.setdefault('first_receive_s', time.perf_counter() - seen['began'])
            seen.setdefault('engine_then', wire.onset.engine if wire.onset is not None else None)
            deadline = time.monotonic() + patience
            while until is not None and not until(wire) and time.monotonic() < deadline:
                await asyncio.sleep(0.02)
            raise Hangup()

        async def send_text(self, text):
            pass

    class Worker:
        def keep_resident(self):
            pass

        def release(self):
            pass

    async def run_scoped(profile, function, executor=None):
        return function()

    api = SimpleNamespace(__file__=str(home / 'plugin_api.py'), _run_scoped=run_scoped, _gpt_live_settings=lambda: {},
                          _watch_audio_runtime=SimpleNamespace(python=lambda: ('python', {}, [], None)))
    with patch.object(controlled_host, 'profile_sapi_worker', return_value=Worker()), patch.object(controlled_host, 'NativeMediaSocket', Spy):
        with pytest.raises(Hangup):
            seen['began'] = time.perf_counter()
            asyncio.run(controlled_host.serve(Phone(), api=api, profile=None, home=home))
    return built['wire'], seen
