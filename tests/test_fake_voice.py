"""SYNTH: the synthetic voice of a machine without SAPI (tests/helpers_fake_voice.py) is deterministic, has the format and the lengths of the real layer, and does not loosen what the real layer checks.

It is forced on here (``installed(force=True)``), so the file means the same on Windows (where the fixture installs nothing) and in the cloud.
"""
import os
import sys
import tempfile
import wave
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import helpers_fake_voice as FV  # noqa: E402

pcm_trim = pytest.importorskip('echo_sync.pcm_trim')
sapi_worker = pytest.importorskip('echo_sync.sapi_worker')
SapiWorkerError, SapiWorkerManager = sapi_worker.SapiWorkerError, sapi_worker.SapiWorkerManager


def seconds(pcm):
    return len(pcm) / 2 / FV.SAMPLE_RATE


# 1. the sound: a function of the text, in the format of the real voice, with the lengths the product trims

def test_the_same_text_gives_the_same_bytes():
    assert FV.pcm_for('Столица Австралии Канберра.') == FV.pcm_for('Столица Австралии Канберра.')


def test_the_length_follows_the_text_with_the_floor_and_the_cap():
    short, medium, long_, huge = FV.pcm_for('Да.'), FV.pcm_for('а' * 150), FV.pcm_for('а' * 300), FV.pcm_for('а' * 5000)
    lead, tail = FV.LEAD_SILENCE_S, FV.TAIL_SILENCE_S
    assert seconds(short) == pytest.approx(lead + FV.MIN_VOICED_S + tail, abs=0.001), 'the floor'
    assert seconds(medium) == pytest.approx(lead + 10.0 + tail, abs=0.001), '150 characters at 15 a second'
    assert seconds(long_) == pytest.approx(lead + 20.0 + tail, abs=0.001)
    assert seconds(huge) == pytest.approx(lead + FV.MAX_VOICED_S + tail, abs=0.001), 'the cap'
    assert pcm_trim.valid_pcm(huge), 'even the longest text stays under the 30 s the wire accepts'


def test_the_product_reads_the_voice_where_the_stand_in_put_it():
    pcm = FV.pcm_for('а' * 150)
    voiced = pcm_trim.voiced_seconds(pcm)
    assert voiced == pytest.approx(FV.LEAD_SILENCE_S + 10.0, abs=0.01), 'the voice stops where the body stops: the cue is not read as silent'
    assert pcm_trim.valid_pcm(pcm)
    trimmed = pcm_trim.trim_trailing_silence(pcm)
    assert seconds(trimmed) == pytest.approx(voiced + pcm_trim.TAIL_KEEP_MS / 1000, abs=0.01), 'the SAPI tail is cut to what the product keeps'
    front = pcm_trim.trim_leading_silence(pcm)
    assert seconds(pcm) - seconds(front) == pytest.approx(FV.LEAD_SILENCE_S - pcm_trim.LEAD_IN_KEEP_MS / 1000, abs=0.01)


def test_the_body_is_audible_but_quiet():
    from array import array
    samples = array('h')
    samples.frombytes(FV.pcm_for('Привет, как дела?'))
    peak = max(abs(value) for value in samples)
    assert pcm_trim.AUDIBLE_THRESHOLD < peak <= 1000, 'above the product threshold (so the timing sees a voice), far below a real voice'


# 2. the real manager over the stand-in child: the checks of the real layer are all still made

def make_manager(**options):
    return SapiWorkerManager(tempfile.mkdtemp(prefix='fakevoice-'), startup_timeout=2, request_timeout=2, **options)


def test_the_real_manager_writes_a_valid_wav_through_its_own_validation(tmp_path):
    with FV.installed(force=True):
        manager = make_manager()
        try:
            target = tmp_path / 'cue.wav'
            before = FV.USED['cues']
            assert manager.synthesize('Столица Австралии Канберра.', str(target)) == str(target)
            with wave.open(str(target), 'rb') as audio:
                assert (audio.getframerate(), audio.getnchannels(), audio.getsampwidth()) == (24000, 1, 2)
                assert audio.getnframes() > 0
            assert FV.USED['cues'] == before + 1, 'the cue is counted (and the priming of the worker is not)'
            assert not [item for item in tmp_path.iterdir() if item.name.startswith('.echo-sapi-')], 'the atomic temporary file is gone'
        finally:
            manager.close()


@pytest.mark.parametrize('text', ['', '   ', 'а' * (SapiWorkerManager.MAX_TEXT + 1), None])
def test_a_bad_text_is_refused_as_before(tmp_path, text):
    with FV.installed(force=True):
        manager = make_manager()
        try:
            with pytest.raises(SapiWorkerError, match='bad_text'):
                manager.synthesize(text, str(tmp_path / 'x.wav'))
            assert not (tmp_path / 'x.wav').exists()
        finally:
            manager.close()


def test_a_wav_of_the_wrong_format_is_still_refused(tmp_path, monkeypatch):
    """The validation is the real one: a stand-in that wrote 22 kHz would fail like the real layer fails."""
    def wrong(path, text):
        with wave.open(str(path), 'wb') as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(22050)
            audio.writeframes(b'\x01\x02' * 100)
    with FV.installed(force=True):
        monkeypatch.setattr(FV, 'write_wav', wrong)
        manager = make_manager()
        try:
            with pytest.raises(SapiWorkerError, match='wav_format_mismatch'):
                manager.synthesize('Да.', str(tmp_path / 'x.wav'))
        finally:
            manager.close()


def test_a_worker_closed_and_used_again_starts_again(tmp_path):
    with FV.installed(force=True):
        manager = make_manager()
        try:
            manager.synthesize('Да.', str(tmp_path / 'a.wav'))
            manager.close()
            manager.synthesize('Нет.', str(tmp_path / 'b.wav'))
            assert (tmp_path / 'b.wav').is_file()
        finally:
            manager.close()


def test_a_manager_with_a_fake_popen_keeps_the_real_code_path():
    """Only a manager that would start powershell.exe is stood in; the tests that script the child's protocol (test_sapi_resident) are not touched."""
    with FV.installed(force=True):
        scripted = SapiWorkerManager('scripted', popen_factory=lambda *args, **kwargs: None)
        stock = SapiWorkerManager('stock')
        try:
            assert not FV._stock(scripted) and FV._stock(stock)
            if os.name != 'nt':
                with pytest.raises(SapiWorkerError, match='windows_only'):
                    scripted._start_locked()
        finally:
            scripted.close()
            stock.close()


def test_the_class_is_put_back_after_the_block():
    class Probe(SapiWorkerManager):
        pass
    start, request = Probe._start_locked, Probe._request_locked
    undo = FV.install(Probe, force=True)
    assert undo is not None and Probe._start_locked is not start and Probe._request_locked is not request
    assert FV.install(Probe, force=True) is None, 'twice is once'
    undo()
    assert Probe._start_locked is start and Probe._request_locked is request


# 3. the host's own rendering (``controlled_host.render_cue_pcm``) over the stand-in: the product's trims, not the helper's

def test_the_host_renders_a_cue_from_the_stand_in_with_the_product_trims(tmp_path):
    controlled_host = pytest.importorskip('echo_sync.controlled_host')
    with FV.installed(force=True):
        worker = sapi_worker.profile_sapi_worker(tmp_path / 'profile')
        try:
            short = controlled_host.render_cue_pcm(worker, 'Да.', tmp_path)
            long_ = controlled_host.render_cue_pcm(worker, 'Столица Австралии Канберра, а крупнейший город Сидней.', tmp_path)
            assert pcm_trim.valid_pcm(short) and pcm_trim.valid_pcm(long_)
            assert pcm_trim.voiced_seconds(long_) > pcm_trim.voiced_seconds(short) + 1.0, 'a longer text is a longer voice'
            assert seconds(short) - pcm_trim.voiced_seconds(short) == pytest.approx(FV.TAIL_SILENCE_S, abs=0.01), 'render_cue_pcm cuts the front only; the tail is the transport\'s'
        finally:
            worker.close()
