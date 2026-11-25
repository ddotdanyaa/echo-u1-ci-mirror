"""Task S1: the recognizer behind the shadow ear - sherpa-onnx 2.0.1 + the Vosk small streaming Russian Zipformer (int8).

Two kinds of checks. The hotwords (the bias towards the waiting portion) are plain text and checked on their own: the bake-off
found that biasing number words turned «статья четыреста двадцать вторая» into the expected «… первая» (a false ACK), so a hotword
never carries a number or a negation. The real model is run on real SAPI audio (the packaged diagnostic phrases) when it is installed
in this environment; elsewhere those checks are skipped, never faked.
"""
import wave
from pathlib import Path

import pytest

from echo_sync import ear_sherpa

DIAG = Path(__file__).resolve().parents[1] / 'echo_sync' / 'diag_audio'


def phrases(hotwords):
    return hotwords.split('/')


@pytest.mark.parametrize('portion, kept, never', [
    ('Статья четыреста двадцать первая', ['статья'], ['четыреста', 'двадцать', 'первая']),
    ('Не больше трёх раз', ['больше'], ['не', 'трёх']),      # «раз» alone is too short to bias (< 4 letters)
    ('Акула не является млекопитающим.', ['акула', 'является млекопитающим'], ['не']),
    ('В 1914 году.', ['году'], ['1914']),
    ('Вода кипит при ста градусах', ['вода кипит при', 'градусах'], ['ста']),
    ('Ни один из них', ['из них'], ['ни', 'один']),
])
def test_a_hotword_never_carries_a_number_or_a_negation(portion, kept, never):
    got = phrases(ear_sherpa.hotwords_for(portion))
    for phrase in kept:
        assert phrase in got
    for word in never:
        assert not any(word in phrase.split() for phrase in got), (word, got)


def test_the_command_words_are_always_among_the_hotwords():
    got = phrases(ear_sherpa.hotwords_for('Сублимация'))
    assert 'сублимация' in got
    assert {'повтори', 'еще раз', 'стоп', 'дальше'} <= set(got)


def test_no_portion_means_only_the_command_words():
    assert set(phrases(ear_sherpa.hotwords_for(None))) == {'повтори', 'еще раз', 'стоп', 'хватит', 'дальше'}


# --- the real model (skipped where it is not installed) ---------------------------------------------------------------------------

def _model_ready():
    try:
        import sherpa_onnx  # noqa: F401
    except ImportError:
        return False
    return all((Path(ear_sherpa.default_model_dir()) / name).is_file() for name in ear_sherpa.MODEL_FILES)


needs_model = pytest.mark.skipif(not _model_ready(), reason='sherpa-onnx or the local ear model is not installed here')


def _hear(engine, path, hotwords=None):
    with wave.open(str(path), 'rb') as handle:
        assert handle.getframerate() == 24000 and handle.getnchannels() == 1 and handle.getsampwidth() == 2
        pcm = handle.readframes(handle.getnframes())
    stream = engine.start(hotwords)
    for start in range(0, len(pcm), 4800):              # the phone's 100 ms packets
        engine.accept(stream, pcm[start:start + 4800])
    return engine.finish(stream)


@pytest.fixture(scope='module')
def engine():
    return ear_sherpa.SherpaEngine()


@needs_model
def test_the_real_model_hears_packaged_sapi_phrases(engine):
    # echo_sync/diag_audio/manifest.json: «Поиск не ответил.», «Не нашёл. Повторите вопрос.» (Microsoft Irina, 24 kHz), the model
    # folder under the Cyrillic profile path (the C++ side needs its short name)
    assert _hear(engine, DIAG / 'lookup_degraded.wav') == 'поиск не ответил'
    assert _hear(engine, DIAG / 'lookup_empty.wav') == 'не нашёл повторите вопрос'


@needs_model
def test_hotwords_for_another_portion_do_not_change_what_was_said(engine):
    assert _hear(engine, DIAG / 'lookup_empty.wav', ear_sherpa.hotwords_for('Не больше трёх раз')) == 'не нашёл повторите вопрос'


@needs_model
def test_a_missing_model_is_an_exception_the_worker_can_catch_not_an_exit(tmp_path):
    # sherpa-onnx checks its files in Python (an AssertionError naming the path): the worker turns it into state 'failed'
    with pytest.raises(Exception):
        ear_sherpa.SherpaEngine(model_dir=tmp_path)


@needs_model
def test_silence_is_heard_as_nothing(engine):
    stream = engine.start()
    for _ in range(10):
        engine.accept(stream, bytes(4800))
    assert engine.finish(stream) == ''
