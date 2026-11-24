"""Registry 5.02 «Кэш готового звука первых порций»; state by the registry: РАБОТАЕТ НА СЕРВЕРЕ (включено, действие не измерено).

Proves through the real controlled_host.serve() (helpers_s6_fault.HostRig: fake phone, fake cloud, fake SAPI worker, virtual time) that with
``pcm_cache_dir`` set, a first portion spoken in one call is sent to the phone in the next call WITHOUT a SAPI synthesis (same audio bytes),
that the sound lies in the folder, and that another text or another voice is synthesized again. Without the folder (code default: empty)
every call synthesizes. Dummy check: ``pcm_cache_dir`` set / left empty (code default), plus a stub of ``pcm_cache.from_settings`` in a copy.
"""
import base64
import json
import logging
import time
from pathlib import Path

import pytest

import helpers_s6_fault as F
from echo_sync.settings import DEFAULTS


@pytest.fixture(autouse=True)
def quiet():
    logging.disable(logging.CRITICAL)
    yield
    logging.disable(logging.NOTSET)


def put_settings(home, **values):
    folder = Path(home) / 'materials'
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'echo_settings.json').write_text(json.dumps(values), encoding='utf-8')


def one_call(tmp_path, monkeypatch, name, cache, *, question=F.DIRECT_QUESTION, answer=F.DIRECT_ANSWER, voice=None):
    """A whole call on its own home: question, the cloud's answer. -> (texts that reached SAPI, first cue text, its audio bytes)."""
    seen = {}

    async def main():
        F.patch_clock(monkeypatch)
        async with F.HostRig(Path(tmp_path) / name, monkeypatch) as host:
            if voice:
                host.worker.voice = voice                      # the voice the fake SAPI reports (part of the cache key)
            # live server values; the code default of pcm_cache_dir is empty (a folder is a place, not a switch)
            put_settings(host.home, pcm_cache_dir=str(cache) if cache else DEFAULTS['pcm_cache_dir'], pcm_cache_mb=800)
            await host.handshake()
            await host.ask(question, tid='u1')
            await host.answer(answer, tid='a1')
            await host.advance(2)
            seen['sapi'] = [text for _, text in host.synth_plan.calls]
            seen['cue'] = host.spoken()[0]
            seen['audio'] = b''.join(base64.b64decode(f.data['delta']) for f in host.audio())
    F.run(main)
    return seen['sapi'], seen['cue'], seen['audio']


def wait_for_files(folder, count=1):
    """The cache is written by a background thread in real time: wait (bounded) until the folder holds the sound."""
    end = time.monotonic() + 3
    while time.monotonic() < end and len(list(folder.glob('*.pcm'))) < count:
        time.sleep(0.02)
    return sorted(folder.glob('*.pcm'))


def test_first_portion_spoken_once_is_not_synthesized_in_the_next_call(tmp_path, monkeypatch):
    folder = tmp_path / 'pcm-cache'
    sapi1, cue1, audio1 = one_call(tmp_path, monkeypatch, 'c1', folder)
    assert sapi1 and audio1, (sapi1, len(audio1))                 # the first call really synthesized and played
    files = wait_for_files(folder)
    assert files, 'the sound of the first portion must lie in the folder'
    sapi2, cue2, audio2 = one_call(tmp_path, monkeypatch, 'c2', folder)
    assert cue2 == cue1 and audio2 == audio1 and audio2         # the phone gets the same portion, the same sound
    assert sapi2 == [], f'the second call must not call the synthesizer, it did for: {sapi2}'


def test_without_the_folder_every_call_synthesizes(tmp_path, monkeypatch):
    assert DEFAULTS['pcm_cache_dir'] == ''                        # the code default: no cache
    sapi1, cue1, _ = one_call(tmp_path, monkeypatch, 'c1', None)
    sapi2, cue2, audio2 = one_call(tmp_path, monkeypatch, 'c2', None)
    assert cue1 == cue2 and audio2 and sapi1 and sapi2 == sapi1   # nothing saved: the same text goes to synthesis again
    assert not list(tmp_path.rglob('*.pcm'))


def test_another_text_and_another_voice_are_synthesized_again(tmp_path, monkeypatch):
    folder = tmp_path / 'pcm-cache'
    _, cue1, _ = one_call(tmp_path, monkeypatch, 'c1', folder)
    wait_for_files(folder)
    sapi2, cue2, _ = one_call(tmp_path, monkeypatch, 'c2', folder, question=F.OTHER_DIRECT_QUESTION, answer=F.OTHER_DIRECT_ANSWER)
    assert cue2 != cue1 and sapi2, 'another text is another sound'
    wait_for_files(folder, 2)
    sapi3, cue3, _ = one_call(tmp_path, monkeypatch, 'c3', folder, voice='another-voice')
    assert cue3 == cue1 and sapi3, 'the same text with another voice is another sound'
    sapi4, _, _ = one_call(tmp_path, monkeypatch, 'c4', folder)  # the first voice and text again: still served from the folder
    assert sapi4 == [], sapi4
