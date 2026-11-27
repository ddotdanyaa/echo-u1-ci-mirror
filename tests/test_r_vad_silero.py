"""Task R-VAD: Silero VAD (through sherpa-onnx) as the engine of the transport's own ear - the contract of S0's ``SpeechOnset``.

``echo_sync.vad_silero.SileroOnset`` takes the phone's microphone PCM (PCM16LE mono 24 kHz, ~100 ms packets of any size), resamples it to
16 kHz (echo_sync/resample.py), cuts it into the 512-sample windows the model takes and turns the model's verdict per window into S0's
events: ``feed(pcm)`` -> ``'onset'`` (speech started in this packet) | ``'speech'`` (it goes on) | ``None``, plus ``speaking``,
``level`` and ``floor``. The model's own smoothing says when speech starts (60 ms of it) and when it is over (300 ms without), the same
numbers as the energy detector.

Two kinds of tests. The state machine around the model is checked with a scripted model (the verdict per window is given): that is the
boundary replaced, the resampler, the windowing and the events are production code. Whether the REAL model hears real speech - the SAPI
phrases packaged in echo_sync/diag_audio, 24 kHz - and ignores noise is checked where sherpa-onnx and the model are installed, and
skipped (never faked) elsewhere. The synthetic tone "speech" of the S0 tests is NOT speech to a neural model, on purpose: those tests
stay on the energy engine.
"""
import logging
import math
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from echo_sync import local_ear, vad_silero
from echo_sync.vad_silero import SherpaVad, SileroOnset
from helpers_r_vad import (WINDOW, ScriptedModel, active_dbfs, needs_model, not_silero_onnx, phrase, play)
from helpers_s0_audio import PACKET_MS, RATE, ROOM, VOICE, mix, ms, noise, packets, pcm, speech, tone


def heard(data, packet_ms=PACKET_MS, detector=None):
    """What the detector says for each packet, as the transport feeds it."""
    detector = detector or SileroOnset(model=ScriptedModel())
    return [detector.feed(packet) for packet in packets(data, packet_ms)]


def onsets(events):
    return [index for index, event in enumerate(events) if event == 'onset']


def room_pcm(n_ms, seed=1):
    return pcm(noise(n_ms, ROOM, seed=seed))


# --- the state machine around the model (scripted verdicts) -------------------------------------------------------------------------

def test_the_model_only_ever_gets_whole_windows_of_16_khz_floats_whatever_the_packets_are():
    model = ScriptedModel()
    detector = SileroOnset(model=model)
    data = pcm(noise(3000, VOICE))
    for size in (4800, 1, 2, 37, 960, 9600, 4799):                  # bytes: including odd ones
        for start in range(0, len(data), size):
            detector.feed(data[start:start + size])
    assert model.wrong == [], 'a window of any other size would exit the whole process in sherpa-onnx'
    assert model.calls > 100


def test_the_audio_reaches_the_model_at_16_khz_with_its_level():
    model = ScriptedModel()
    detector = SileroOnset(model=model)
    data = pcm(tone(1000, -20))                                      # one second of 150 Hz at -20 dBFS RMS
    heard(data, detector=detector)
    samples = [value for window in model.windows for value in window]
    assert abs(len(samples) - 16000) <= 2 * WINDOW                   # whole windows only, a little still waiting
    level = 20 * math.log10(math.sqrt(sum(v * v for v in samples[200:]) / len(samples[200:])))
    assert abs(level - -20) < 0.3, level
    crossings = sum(1 for a, b in zip(samples, samples[1:]) if a < 0 <= b)
    assert abs(crossings - 150 * len(samples) / 16000) <= 2, 'the pitch changed: the rate is not 16 kHz'


def voiced_pcm(n_ms, voice_from_ms, voice_ms, seed=1):
    """Room tone with a voice in it from ``voice_from_ms`` for ``voice_ms`` (a «speech» event needs sound that stands out of the floor)."""
    return pcm(mix(noise(n_ms, ROOM, seed=seed), [0.0] * ms(voice_from_ms) + speech(voice_ms, VOICE)))


def test_the_first_window_of_speech_is_an_onset_in_the_packet_that_carries_its_end():
    script = [False] * 12 + [True] * 8                               # window 12 ends 13 * 32 ms = 416 ms into the audio, window 19 at 640 ms
    events = heard(voiced_pcm(2000, 380, 280), detector=SileroOnset(model=ScriptedModel(script)))   # the voice is there while the model says speech
    assert events[:4] == [None] * 4, events
    assert events[4:8] == ['onset', 'speech', 'speech', None], events   # the packet of windows 18-19 is still speech, then it is over
    assert events[8:] == [None] * 12, events


def test_while_the_model_hears_speech_the_detector_is_speaking_and_says_speech_in_every_packet():
    script = [False] * 4 + [True] * 40 + [False] * 30                # speech from window 4 (ends 160 ms) to window 43 (ends 1408 ms)
    detector = SileroOnset(model=ScriptedModel(script))
    seen = []
    for packet in packets(voiced_pcm(3000, 160, 840), PACKET_MS):    # the voice: 0.16-1.0 s; the model's own hangover goes on to 1.4 s
        event = detector.feed(packet)
        seen.append((event, detector.speaking))
    assert seen[0] == (None, False)
    assert seen[1] == ('onset', True), seen[:3]
    assert seen[2:9] == [('speech', True)] * 7, seen[2:9]
    assert seen[11:14] == [(None, True)] * 3, 'the voice is over, the model is still in its hangover: speaking, but no «speech» (review fix 5)'
    assert seen[14] == (None, False), 'the packet in which the model says it is over'
    assert seen[15:] == [(None, False)] * 15, 'well after the speech ended nothing is heard and nobody speaks'


def test_a_new_start_after_the_end_is_an_onset_again():
    script = [True] * 10 + [False] * 12 + [True] * 10                # the model's own smoothing has ended the first stretch
    events = heard(room_pcm(1500), detector=SileroOnset(model=ScriptedModel(script)))
    assert len(onsets(events)) == 2, events


def test_an_onset_wins_over_speech_in_the_same_packet():
    script = [True, True, True, True]                                # 128 ms: one packet holds the start and a continuation
    events = heard(room_pcm(130), detector=SileroOnset(model=ScriptedModel(script)))
    assert events[0] == 'onset', events


def test_the_packet_size_does_not_change_when_speech_is_heard():
    script = [False] * 20 + [True] * 12 + [False] * 14 + [True] * 12
    data = room_pcm(2500)
    reference = [index + 1 for index in onsets(heard(data, packet_ms=1, detector=SileroOnset(model=ScriptedModel(script))))]   # exact to a ms
    assert len(reference) == 2, reference
    for packet_ms in (100, 37, 250, 20):
        found = onsets(heard(data, packet_ms=packet_ms, detector=SileroOnset(model=ScriptedModel(script))))
        assert len(found) == len(reference), (packet_ms, found)
        for index, onset_ms in zip(found, reference):
            assert index * packet_ms < onset_ms <= (index + 1) * packet_ms, (packet_ms, index, onset_ms)


def test_empty_and_odd_packets_are_tolerated():
    detector = SileroOnset(model=ScriptedModel())
    assert detector.feed(b'') is None
    assert detector.feed(b'\x01') is None                            # half a sample waits for its other half
    data = room_pcm(500)
    assert detector.feed(data[:333]) is None and detector.feed(data[333:]) is None


def test_a_split_sample_is_put_back_together():
    whole, split = ScriptedModel(), ScriptedModel()
    data = pcm(noise(1000, VOICE))
    SileroOnset(model=whole).feed(data)
    detector = SileroOnset(model=split)
    for start in range(0, len(data), 1001):                          # every packet ends inside a sample
        detector.feed(data[start:start + 1001])
    assert split.windows == whole.windows[:len(split.windows)] and len(split.windows) == len(whole.windows)


def test_level_and_floor_are_the_numbers_of_the_energy_meter_beside_it():
    detector = SileroOnset(model=ScriptedModel())
    heard(pcm(mix(noise(3000, ROOM), [0.0] * ms(2000) + speech(800, VOICE))), detector=detector)
    reference = local_ear.SpeechOnset()
    heard(pcm(mix(noise(3000, ROOM), [0.0] * ms(2000) + speech(800, VOICE))), detector=reference)
    assert (detector.level, detector.floor) == (reference.level, reference.floor)
    assert detector.level is not None and detector.floor is not None


def test_a_failing_model_hands_the_ear_over_to_the_energy_detector_once(caplog):
    model = ScriptedModel(fail_at=3)
    detector = SileroOnset(model=model)
    assert detector.engine == 'silero'
    room = noise(4000, ROOM)
    talk = [0.0] * ms(1500) + speech(1200, VOICE)
    with caplog.at_level(logging.INFO, logger='echo-sync'):
        events = heard(pcm(mix(room, talk)), detector=detector)     # nothing escapes into the transport
    assert detector.engine == 'energy', 'the ear goes on with S0 energy detector'
    assert len(onsets(events)) == 1, events
    assert detector.speaking is False
    lines = [r for r in caplog.records if 'engine=silero failed' in r.getMessage()]
    assert len(lines) == 1 and lines[0].levelno == logging.WARNING
    assert 'RuntimeError' in lines[0].getMessage() and 'words' not in lines[0].getMessage(), 'the type, never the message'
    calls = model.calls
    detector.feed(room_pcm(100))
    assert model.calls == calls, 'a failed model is not asked again'


def test_the_cost_beside_the_model_is_bounded():
    """A minute of microphone audio at the phone's cadence: the resampler, the windows and the meter, with a model that costs nothing."""
    data = pcm(mix(noise(5000, ROOM), [0.0] * ms(1000) + speech(2500, VOICE))) * 12
    chunks = packets(data)
    detector = SileroOnset(model=ScriptedModel([False] * 3 + [True] * 60 + [False] * 1000))
    started = time.process_time()
    for chunk in chunks:
        detector.feed(chunk)
    elapsed = time.process_time() - started
    assert len(chunks) == 600 and elapsed < 4.0, f'{elapsed:.2f} s of CPU for 60 s of audio'


# --- «speech» follows the voice, not the model's hangover (review fix 5) ------------------------------------------------------------------

def test_voiced_says_whether_a_frame_of_the_last_packet_stood_out_of_the_floor():
    meter = local_ear.SpeechOnset()
    seen = []
    for packet in packets(pcm(mix(noise(4000, ROOM), [0.0] * ms(1500) + speech(1000, VOICE)))):
        meter.feed(packet)
        seen.append(meter.voiced)
    assert not any(seen[:15]), 'room tone alone never stands out of its own floor'
    assert all(seen[15:25]), 'the voice does'
    assert not any(seen[29:]), 'after the voice it is room tone again'


def test_speech_events_stop_with_the_voice_while_the_model_is_still_in_its_hangover():
    """sherpa-onnx keeps saying "speech" for min_silence (0.3 s) after the last speech window - and for as long as it is not asked, e.g. across a
    gap in the phone's microphone stream (no audio while a cue plays). In mode 'on' every 'speech' event re-arms the controller's «the listener is
    speaking» flag (local_speech): the hangover, and room tone after a gap, must not. The model here says "speech" from 0.32 s to 3.2 s;
    the voice is there from 1.0 to 2.5 s."""
    script = [False] * 10 + [True] * 90
    detector = SileroOnset(model=ScriptedModel(script))
    seen = []
    for packet in packets(pcm(mix(noise(5000, ROOM), [0.0] * ms(1000) + speech(1500, VOICE)))):
        seen.append((detector.feed(packet), detector.speaking))
    events = [event for event, _speaking in seen]
    assert events[3] == 'onset', 'the model decides when speech STARTS, as before'
    assert events[4:9] == [None] * 5, 'room tone while the model says speech: no «speech» (nothing stands out of the floor)'
    assert events[11:24] == ['speech'] * 13, 'the voice'
    assert events[26:] == [None] * (len(events) - 26), 'the hangover (0.3 s) and everything after it'
    assert seen[28][1] is True, 'the detector is still SPEAKING in the hangover - only the «speech» events are gone'
    assert seen[-1][1] is False


@needs_model
def test_the_real_model_says_speech_only_while_the_voice_is_there():
    data, (start, end) = scene_for_events()
    detector = SileroOnset()
    events = [detector.feed(packet) for packet in packets(data)]
    last_voiced_packet = int(end * 10)
    late = [i for i, event in enumerate(events) if event == 'speech' and i > last_voiced_packet + 1]
    assert late == [], f'«speech» in packets {late} after the voice ended at {end:.2f} s'
    assert sum(1 for event in events if event == 'speech') >= 8


def scene_for_events():
    from helpers_r_vad import scene
    return scene('lookup_degraded', lead_ms=1000, tail_ms=1500)


# --- the real model on real speech (where it is installed) ----------------------------------------------------------------------------

@needs_model
def test_the_real_model_hears_a_spoken_phrase_once_and_the_room_before_it_not_at_all():
    events, speaking, (start, end) = play('lookup_degraded')
    found = onsets(events)
    assert len(found) == 1, events
    heard_at = (found[0] + 1) * PACKET_MS / 1000
    assert start < heard_at < start + 0.45, f'speech from {start:.2f} s was heard at {heard_at:.2f} s'
    assert all(e is None for e in events[:found[0]]), 'the room is not speech'
    over = next(i for i in range(found[0], len(speaking)) if not speaking[i])
    assert (over + 1) * PACKET_MS / 1000 - end < 0.65, f'the speech ended at {end:.2f} s and was over at {(over + 1) / 10:.1f} s'


@needs_model
def test_a_pause_between_two_sentences_ends_the_utterance_and_the_next_one_is_an_onset_again():
    events, _speaking, _span = play('lookup_empty')                  # «Не нашёл.» ... «Повторите вопрос.»
    assert len(onsets(events)) == 2, events


@needs_model
def test_speech_over_noise_fifteen_db_below_it_is_one_utterance_that_ends_promptly():
    """The case the energy detector fails (S1: at 15 dB SNR it ended 29 % of the utterances late, p95 1.34 s)."""
    level = active_dbfs(phrase('lookup_degraded')) - 15
    events, speaking, (start, end) = play('lookup_degraded', background=lambda n: noise(n, level, seed=9))
    found = onsets(events)
    assert len(found) == 1, events
    over = next(i for i in range(found[0], len(speaking)) if not speaking[i])
    assert (over + 1) * PACKET_MS / 1000 - end < 1.0, f'ended at {end:.2f} s, over at {(over + 1) / 10:.1f} s'


@needs_model
@pytest.mark.parametrize('name, source', [
    ('steady white noise at -40 dBFS', lambda: noise(15_000, -40, seed=5)),
    ('loud white noise at -25 dBFS', lambda: noise(15_000, -25, seed=6)),
    ('a 100 Hz mains hum with its harmonics at -30 dBFS', lambda: [sum(math.sin(2 * math.pi * 100 * h * i / RATE) / h for h in range(1, 6))
                                                                     * 32768 * 10 ** (-30 / 20) for i in range(ms(15_000))]),
    ('keyboard clicks over the room', lambda: mix(noise(15_000, ROOM, seed=7),
                                                  [0.0] * ms(500) + sum(([0.0] * ms(700) + tone(15, -12) for _ in range(20)), []))),
])
def test_noises_that_are_not_speech_are_not_heard(name, source):
    detector = SileroOnset()
    events = [detector.feed(packet) for packet in packets(pcm(source()))]
    assert onsets(events) == [] and not any(events), name


@needs_model
def test_the_real_model_costs_a_few_milliseconds_per_packet():
    samples = phrase('lookup_empty')
    data = pcm(mix(noise(5000, ROOM), [0.0] * ms(500) + samples)) * 8
    chunks = packets(data)
    detector = SileroOnset()
    started = time.process_time()
    for chunk in chunks:
        detector.feed(chunk)
    per_packet = (time.process_time() - started) / len(chunks) * 1000
    assert per_packet < 12.0, f'{per_packet:.1f} ms of CPU per 100 ms packet'


# --- the model file is pinned: sherpa-onnx EXITS THE WHOLE PROCESS on any other graph -----------------------------------------------------

ROOT = Path(__file__).resolve().parents[1]


def sherpa_installed():
    try:
        import sherpa_onnx  # noqa: F401
    except ImportError:
        return False
    return True


def test_a_file_of_the_wrong_size_is_refused_before_sherpa_sees_it(tmp_path):
    path = tmp_path / vad_silero.MODEL_FILE
    path.write_bytes(not_silero_onnx())
    with pytest.raises(ValueError):
        SherpaVad(path)


def test_a_file_of_the_right_size_and_other_content_is_refused(tmp_path):
    path = tmp_path / vad_silero.MODEL_FILE
    path.write_bytes(bytes(vad_silero.MODEL_SIZE))
    with pytest.raises(ValueError):
        SherpaVad(path)


@needs_model
def test_the_pinned_model_is_hashed_once_per_version_of_the_file(tmp_path, monkeypatch):
    copy = tmp_path / vad_silero.MODEL_FILE
    shutil.copyfile(vad_silero.default_model_path(), copy)
    hashed = []
    real = vad_silero._sha256_of
    monkeypatch.setattr(vad_silero, '_sha256_of', lambda path: hashed.append(path) or real(path))
    vad_silero.verify_model(copy)
    vad_silero.verify_model(copy)
    assert len(hashed) == 1, 'the same file (path, size, mtime) is trusted after the first check'
    os.utime(copy, (1_700_000_000, 1_700_000_000))
    vad_silero.verify_model(copy)
    assert len(hashed) == 2, 'a file that changed is checked again'


@pytest.mark.skipif(not sherpa_installed(), reason='sherpa-onnx is not installed here')
def test_a_valid_onnx_that_is_not_silero_gives_the_energy_detector_and_the_process_lives(tmp_path):
    """The reviewers' reproduction: at the model path a file onnxruntime can load but that is not a Silero graph (the recognizer's own
    decoder.onnx / joiner.int8.onnx). sherpa-onnx then prints «Unsupported silero vad model» and exit(-1)s the process inside
    VadModel.create - in serve that kills the server at every call open. In a child process, so that a dead process is a failed test."""
    (tmp_path / vad_silero.MODEL_FILE).write_bytes(not_silero_onnx())
    code = 'from echo_sync.local_ear import make_onset; print("engine=" + make_onset("silero").engine)'
    done = subprocess.run([sys.executable, '-c', code], cwd=str(ROOT), capture_output=True, text=True, timeout=120,
                          env={**os.environ, 'ECHO_EAR_MODEL_DIR': str(tmp_path), 'PYTHONDONTWRITEBYTECODE': '1'})
    assert done.returncode == 0, f'the process died with {done.returncode}: {done.stderr[-300:]}'
    assert 'engine=energy' in done.stdout
    assert 'requested=silero reason=ValueError' in done.stderr, done.stderr
