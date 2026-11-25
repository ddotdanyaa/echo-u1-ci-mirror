"""U64 (what is provable without recordings): the prosody features of an utterance - the pitch slope, the loudness fall, the length of the last voiced stretch and the
pause after it - computed from the PCM the ear already sees, written to the call journal in ``ear_final`` (``prosody``) and decide NOTHING: no thresholds, no setting,
the record the controller gets is the record of before. Synthetic PCM (a tone with a pitch glide and an amplitude ramp): the thresholds need the owner's voice (U07)."""
import math
import random
import time
from array import array

import test_ear_shadow as T
import test_l3_ear_long as L
from echo_sync import prosody

RATE, PACKET = 24000, 2400


def pcm_of(f0, level, ms, phase=[0.0]):
    """``ms`` of a harmonic tone: f0(t) and level(t) are functions of the time in ms from the start of the piece (level in 0..1 of 12000)."""
    out, t = array('h'), 0
    for _ in range(RATE * ms // 1000):
        ms_now = t * 1000 / RATE
        phase[0] += 2 * math.pi * f0(ms_now) / RATE
        out.append(int(12000 * level(ms_now) * (math.sin(phase[0]) + 0.4 * math.sin(2 * phase[0]) + 0.2 * math.sin(3 * phase[0])) / 1.6))
        t += 1
    return out.tobytes()


def track_of(*pieces):
    track = prosody.Track()
    data = b''.join(pieces)
    for at in range(0, len(data), PACKET * 2):
        track.add(data[at:at + PACKET * 2])
    return track.features()


def silence(ms): return bytes(2 * RATE * ms // 1000)  # noqa: E704


def test_a_falling_pitch_has_a_negative_slope_and_a_rising_one_a_positive():
    fall = track_of(pcm_of(lambda t: 220 - 0.06 * t, lambda t: 1.0, 1500))        # 220 -> 130 Hz in 1.5 s
    rise = track_of(pcm_of(lambda t: 130 + 0.06 * t, lambda t: 1.0, 1500))
    flat = track_of(pcm_of(lambda t: 160, lambda t: 1.0, 1500))
    assert fall['pitch_slope_st_s'] < -3 and rise['pitch_slope_st_s'] > 3 and abs(flat['pitch_slope_st_s']) < 1.5, (fall, rise, flat)


def test_a_loudness_fall_and_the_pause_after_the_last_voice_are_measured():
    faded = track_of(pcm_of(lambda t: 150, lambda t: 1.0 if t < 1000 else max(0.05, 1 - (t - 1000) / 350), 1600), silence(400))
    level = track_of(pcm_of(lambda t: 150, lambda t: 1.0, 1600), silence(400))
    assert faded['fall_db'] > 6 and level['fall_db'] < 2, (faded, level)
    assert 300 <= faded['trailing_ms'] <= 700 and 300 <= level['trailing_ms'] <= 600, (faded, level)


def test_the_last_voiced_stretch_has_its_length():
    f = track_of(pcm_of(lambda t: 150, lambda t: 1.0, 900), silence(300), pcm_of(lambda t: 150, lambda t: 1.0, 500), silence(100))
    assert 400 <= f['last_voiced_ms'] <= 600 and f['voiced_ms'] >= 1200 and f['trailing_ms'] <= 200, f


def test_noise_and_silence_have_no_pitch_and_never_raise():
    rng = random.Random(1)
    noise = array('h', [rng.randint(-1000, 1000) for _ in range(RATE)]).tobytes()
    assert track_of(noise)['pitch_slope_st_s'] is None
    assert track_of(silence(500))['voiced_ms'] == 0 and prosody.Track().features() is None and track_of(b'')is None


def test_a_packet_costs_next_to_nothing():
    data = pcm_of(lambda t: 150 + t / 20, lambda t: 1.0, 3000)
    track, packets = prosody.Track(), [data[at:at + PACKET * 2] for at in range(0, len(data), PACKET * 2)]
    began = time.perf_counter()
    for packet in packets:
        track.add(packet)
    assert (time.perf_counter() - began) / len(packets) < 0.002, 'a 100 ms packet: well under 2 ms of CPU on any machine that runs the call'


def test_the_ear_writes_the_features_to_the_journal_only():
    speech = pcm_of(lambda t: 220 - 0.06 * t, lambda t: 1.0, 1500)
    packets = [speech[at:at + PACKET * 2] for at in range(0, len(speech), PACKET * 2)] + [silence(100)] * 3
    ear, _ = L.make(['onset'] + ['speech'] * (len(packets) - 4) + ['end'])
    records = []
    for i, packet in enumerate(packets):
        ear.test_clock.now = 0.1 * (i + 1)
        ear.feed(packet, input_ms=100 * (i + 1))
        L.settle(ear), records.extend(ear.poll())
    records = L.rest(ear, records, 1)
    finals = [fields for ev, fields in ear.test_notes if ev == 'ear_final']
    assert len(finals) == 1 and finals[0]['prosody']['pitch_slope_st_s'] < -3 and finals[0]['prosody']['voiced_ms'] > 1000
    assert all('prosody' not in r for r in records), 'it decides nothing: the record for the controller has no such key'
