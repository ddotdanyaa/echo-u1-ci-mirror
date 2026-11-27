"""Wave 2 / Task 4: the phrase book of the spoken diagnostics and the audio behind it (pre-render + packaged WAVs).

The behaviour on the wire is tested in test_spoken_diagnostics.py; this module pins the pieces it stands on:
the exact phrases, their classes, the rate-limit constant, the committed fallback WAVs (24 kHz mono PCM16 like every
cue, short, audible, in step with their text) and the pre-render that keeps the PCM in memory.
"""
import asyncio
import hashlib
import json
import wave
from pathlib import Path

import pytest

from echo_sync import diagnostics as D
from echo_sync import pcm_trim

AGREED = {
    'lookup_degraded': 'Поиск не ответил.',
    'lookup_empty': 'Не нашёл. Повторите вопрос.',
    'synthesis': 'Ошибка звука. Повторите.',
    'channel': 'Связь прервалась. Повторите вопрос.',
    'other': 'Ошибка. Повторите вопрос.',
    # Wave 2 / Task D (DEF-FAULT-03): the cloud took the question and no usable answer came within ANSWER_WAIT_SECONDS.
    'answer': 'Нет ответа. Повторите вопрос.',
}


def read_wav(path):
    with wave.open(str(path), 'rb') as audio:
        return (audio.getframerate(), audio.getnchannels(), audio.getsampwidth(), audio.getcomptype(),
                audio.readframes(audio.getnframes()))


def run(coro):
    return asyncio.run(coro)


# --- the phrase book -----------------------------------------------------------------------------------------------

def test_the_phrases_are_the_agreed_ones_verbatim():
    assert D.PHRASES == AGREED


def test_the_rate_limit_is_a_named_constant_of_ten_seconds():
    assert D.DIAGNOSTIC_MIN_INTERVAL_S == 10


@pytest.mark.parametrize('code,kind', [
    ('controlled_sources_unavailable', 'lookup'),
    ('controlled_synthesis_failed', 'synthesis'),
    ('controlled_upstream_unavailable', 'channel'),
    ('controlled_upstream_closed', 'channel'),
    ('controlled_answer_timeout', 'answer'),
    ('controlled_invalid_pcm', 'other'),
    ('controlled_invalid_json', 'other'),
    ('controlled_private_context_required', 'other'),
    ('a_code_nobody_has_heard_of', 'other'),
])
def test_every_error_code_has_a_class_and_the_unknown_ones_fall_into_other(code, kind):
    assert D.failure_class(code) == kind


def test_a_lookup_failure_names_the_model_knowledge_answer_only_when_the_controller_has_one():
    code = 'controlled_sources_unavailable'
    assert D.phrase_key(code, has_model_answer=False) == 'lookup_empty'
    assert D.phrase_key(code, has_model_answer=True) == 'lookup_degraded'
    for other in ('controlled_synthesis_failed', 'controlled_upstream_closed', 'controlled_invalid_pcm'):
        assert D.phrase_key(other, has_model_answer=True) == D.phrase_key(other, has_model_answer=False)
    assert {D.phrase_key(c) for c in ('controlled_synthesis_failed', 'controlled_upstream_closed',
                                      'controlled_invalid_json')} == {'synthesis', 'channel', 'other'}


def test_a_missing_answer_has_its_own_phrase_whatever_the_controller_knows():
    """DEF-FAULT-03: «Нет ответа» is for a question the cloud took and never answered; the model-knowledge flag of a lookup
    failure has nothing to do with it."""
    assert D.phrase_key('controlled_answer_timeout') == 'answer'
    assert D.phrase_key('controlled_answer_timeout', has_model_answer=True) == 'answer'
    assert D.PHRASES['answer'] == 'Нет ответа. Повторите вопрос.'


def trim(pcm):
    return pcm_trim.trim_silence(pcm, threshold=D.TRIM_THRESHOLD)


def samples(values):
    return b''.join(int(v).to_bytes(2, 'little', signed=True) for v in values)


def test_trim_cuts_the_silence_around_speech_and_keeps_every_audible_sample():
    rate = D.SAMPLE_RATE
    loud = [2000, -2500, 3000] * 4000                              # 0.5 s of "speech"
    pcm = samples([0] * rate + [40] * 100 + loud + [-60] * 200 + [0] * rate)   # 1 s of silence, hiss, speech, hiss, silence
    head, tail = round(pcm_trim.LEAD_IN_KEEP_MS * rate / 1000), round(pcm_trim.TAIL_KEEP_MS * rate / 1000)      # 960 and 2880 samples
    assert trim(pcm) == samples([0] * (head - 100) + [40] * 100 + loud + [-60] * 200 + [0] * (tail - 200)), \
        'exactly the head pad, the speech and the tail pad must remain'


def test_trim_leaves_audio_without_any_audible_sample_alone():
    pcm = samples([0, 3, -4, 90] * 100)
    assert trim(pcm) == pcm


def test_trim_never_clips_speech_that_starts_or_ends_the_audio():
    pcm = samples([5000] * 100)
    assert trim(pcm) == pcm


def test_a_reason_is_an_exception_type_or_a_fixed_token_and_never_free_text():
    assert D.reason_of(ValueError('the private question and a token')) == 'ValueError'
    assert D.reason_of(TimeoutError()) == 'TimeoutError'
    assert D.reason_of('no_sources') == 'no_sources'
    assert D.reason_of('Что такое инерция?') == 'unknown'
    assert D.reason_of('x' * 200) == 'unknown'
    assert D.reason_of(None) == 'unspecified'


# --- the committed fallback audio ----------------------------------------------------------------------------------

def test_every_phrase_has_a_packaged_wav_in_the_cue_format():
    assert D.ASSET_DIR == Path(D.__file__).parent / 'diag_audio'
    for key in D.PHRASES:
        rate, channels, width, comp, frames = read_wav(D.ASSET_DIR / (key + '.wav'))
        assert (rate, channels, width, comp) == (24000, 1, 2, 'NONE'), key
        assert frames and len(frames) % 2 == 0


def test_every_packaged_wav_is_short_and_is_not_silence():
    for key in D.PHRASES:
        _, _, _, _, frames = read_wav(D.ASSET_DIR / (key + '.wav'))
        seconds = len(frames) / 48000
        assert 0.3 <= seconds <= D.MAX_SECONDS, f'{key}: {seconds:.2f} s'
        samples = [int.from_bytes(frames[i:i + 2], 'little', signed=True) for i in range(0, len(frames), 2)]
        peak = max(abs(s) for s in samples)
        loud = sum(1 for s in samples if abs(s) > 500)
        assert peak > 3000 and loud > len(samples) * 0.1, f'{key}: peak {peak}, loud samples {loud}/{len(samples)}'


def test_the_manifest_keeps_text_and_audio_in_step():
    manifest = json.loads((D.ASSET_DIR / 'manifest.json').read_text(encoding='utf-8'))
    assert manifest['format'] == {'sample_rate': 24000, 'channels': 1, 'sample_width': 2}
    assert manifest['voice'] == 'Microsoft Irina Desktop'
    assert set(manifest['phrases']) == set(D.PHRASES)
    for key, text in D.PHRASES.items():
        entry = manifest['phrases'][key]
        assert entry['text'] == text, f'{key}: the audio was rendered from other words than the phrase in the code'
        assert entry['sha256'] == hashlib.sha256((D.ASSET_DIR / (key + '.wav')).read_bytes()).hexdigest(), key


# --- DiagnosticAudio: pre-rendered PCM first, the packaged WAV otherwise ----------------------------------------

def pcm(seconds=0.5):
    return b'\x05\x06' * int(24000 * seconds)


def test_without_a_prerender_every_phrase_comes_from_its_packaged_wav():
    audio = D.DiagnosticAudio()
    for key in D.PHRASES:
        assert audio.get(key) == read_wav(D.ASSET_DIR / (key + '.wav'))[4]
    assert audio.missing() == []


def test_prerender_keeps_one_pcm_per_phrase_in_memory_and_prefers_it_to_the_wav():
    texts = []

    async def synthesize(text):
        texts.append(text)
        return pcm()

    async def go():
        audio = D.DiagnosticAudio()
        await audio.prerender(synthesize)
        return audio
    audio = run(go())
    assert sorted(texts) == sorted(D.PHRASES.values()), 'each phrase exactly once'
    assert all(audio.get(key) == pcm() for key in D.PHRASES)


def test_prerender_trims_the_silence_sapi_puts_around_a_phrase():
    padded = samples([0] * 24000 + [2000, -2500, 3000] * 2000 + [0] * 24000)       # 1 s, 0.25 s of speech, 1 s
    audio = D.DiagnosticAudio()
    run(audio.prerender(lambda text: padded))
    assert audio.get('other') == trim(padded) and len(audio.get('other')) < len(padded) / 3


def test_prerender_accepts_a_plain_function_too():
    audio = D.DiagnosticAudio()
    run(audio.prerender(lambda text: pcm(0.2)))
    assert audio.get('other') == pcm(0.2)


def test_the_first_failed_prerender_stops_it_and_the_packaged_wavs_serve_the_phrases():
    calls = []

    async def synthesize(text):
        calls.append(text)
        if len(calls) == 2:
            raise RuntimeError('SAPI is gone')
        return pcm()
    audio = D.DiagnosticAudio()
    run(audio.prerender(synthesize))
    assert len(calls) == 2, 'a broken SAPI is not hammered'
    first, second = list(D.PHRASES)[:2]
    assert audio.get(first) == pcm()
    assert audio.get(second) == read_wav(D.ASSET_DIR / (second + '.wav'))[4]
    assert audio.missing() == []


@pytest.mark.parametrize('bad', [pytest.param(b'', id='empty'), pytest.param(b'\x01\x02\x03', id='odd_length'),
                                 pytest.param(None, id='none'), pytest.param('text', id='str'),
                                 pytest.param(b'\x00' * (48000 * 31), id='thirty_one_seconds')])
def test_a_prerendered_pcm_that_is_not_playable_is_never_used(bad):
    audio = D.DiagnosticAudio()
    run(audio.prerender(lambda text: bad))
    first = next(iter(D.PHRASES))
    assert audio.get(first) == read_wav(D.ASSET_DIR / (first + '.wav'))[4]


def test_a_hung_prerender_is_given_up(monkeypatch):
    monkeypatch.setattr(D, 'PRERENDER_TIMEOUT_S', 0.05)

    async def hang(text):
        await asyncio.Event().wait()
    audio = D.DiagnosticAudio()
    run(asyncio.wait_for(audio.prerender(hang), 5))
    first = next(iter(D.PHRASES))
    assert audio.get(first) == read_wav(D.ASSET_DIR / (first + '.wav'))[4]


def test_with_neither_a_prerender_nor_a_packaged_wav_the_phrase_is_missing_and_says_so(tmp_path):
    audio = D.DiagnosticAudio(tmp_path)                        # an empty folder: the deploy forgot diag_audio
    assert audio.get('other') is None
    assert audio.missing() == list(D.PHRASES)
    run(audio.prerender(lambda text: pcm()))
    assert audio.get('other') == pcm() and audio.missing() == []


def test_a_packaged_wav_in_the_wrong_format_is_refused(tmp_path):
    with wave.open(str(tmp_path / 'other.wav'), 'wb') as target:
        target.setframerate(22050)
        target.setnchannels(1)
        target.setsampwidth(2)
        target.writeframes(pcm())
    audio = D.DiagnosticAudio(tmp_path)
    assert audio.get('other') is None
