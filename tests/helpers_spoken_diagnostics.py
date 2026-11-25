"""Shared oracle helpers of the spoken-diagnostics tests (Wave 2 / Task 4).

Built on the virtual-time rigs of helpers_s6_fault: only the boundaries are fake (SAPI, lookup, helper pipe, phone socket,
clock). ``responses`` reads what the phone would have received: one entry per spoken response, with its transcript, its
PCM and its status, exactly the frames of a normal cue (response.created -> transcript -> paced audio -> response.done).
"""
import base64
import wave
from pathlib import Path

import echo_sync
import helpers_s6_fault as F

LOOKUP_DEGRADED = 'Поиск не ответил.'
LOOKUP_EMPTY = 'Не нашёл. Повторите вопрос.'
SYNTHESIS = 'Ошибка звука. Повторите.'
CHANNEL = 'Связь прервалась. Повторите вопрос.'
OTHER = 'Ошибка. Повторите вопрос.'
ANSWER = 'Нет ответа. Повторите вопрос.'                         # Wave 2 / Task D: the cloud never answered (DEF-FAULT-03)
EVERY_PHRASE = [LOOKUP_DEGRADED, LOOKUP_EMPTY, SYNTHESIS, CHANNEL, OTHER, ANSWER]

ASSET_DIR = Path(echo_sync.__file__).parent / 'diag_audio'      # the committed fallback WAVs, found next to the package
FIRST_CUE_BOUND = 3.0


def run_wire(tmp_path, monkeypatch, body, **rig):
    __tracebackhide__ = True

    async def main():
        __tracebackhide__ = True
        F.patch_clock(monkeypatch)
        async with F.WireRig(tmp_path, **rig) as wire_rig:
            return await body(wire_rig)
    return F.run(main)


def run_host(tmp_path, monkeypatch, body, *, handshake=True, **rig):
    __tracebackhide__ = True

    async def main():
        __tracebackhide__ = True
        F.patch_clock(monkeypatch)
        async with F.HostRig(tmp_path, monkeypatch, **rig) as host:
            if handshake:
                await host.handshake()
            return await body(host)
    return F.run(main)


def wav_pcm(name):
    """The PCM of a committed fallback WAV, read independently of the production loader."""
    with wave.open(str(ASSET_DIR / (name + '.wav')), 'rb') as audio:
        assert (audio.getframerate(), audio.getnchannels(), audio.getsampwidth()) == (24000, 1, 2)
        return audio.readframes(audio.getnframes())


def responses(frames):
    """What the phone received, grouped by spoken response: transcript, PCM, status, timing."""
    out = {}
    for frame in frames:
        data = frame.data
        kind = data.get('type')
        if kind == 'response.created':
            out[data['response']['id']] = {'text': None, 'pcm': b'', 'status': None, 'start': frame.t, 'end': None,
                                           'times': [], 'sizes': []}
        elif kind == 'response.audio_transcript.delta':
            out[data['response_id']]['text'] = data['delta']
        elif kind == 'response.audio.delta':
            item = out[data['response_id']]
            chunk = base64.b64decode(data['delta'])
            item['pcm'] += chunk
            item['times'].append(frame.t)
            item['sizes'].append(len(chunk))
        elif kind == 'response.done' and data.get('response', {}).get('id') in out:
            item = out[data['response']['id']]
            item['status'] = data['response'].get('status')
            item['end'] = frame.t
    return list(out.values())


def phrases_heard(frames):
    return [r['text'] for r in responses(frames) if r['text'] in EVERY_PHRASE]
