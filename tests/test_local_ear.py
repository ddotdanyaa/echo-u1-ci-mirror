"""Task S0, ruling 2 (scripts/DUAL_SYSTEM_DESIGN.md §3.2, §3.8 b): a cheap local detector of the START of the listener's speech.

The cloud announces a user turn 0.3-2.3 s after the speech began; in that gap the silence auto-repeat could fire into the listener's
speech (and on the open speaker a cue closes the phone's microphone). The transport hears the microphone PCM first (PCM16LE mono
24 kHz, ~100 ms packets from the phone): an energy detector on 20 ms frames with a noise floor (the quietest frame of the last
FLOOR_WINDOW_MS) and hysteresis says when speech STARTS (ONSET_MS above floor + ONSET_DB, and above MIN_SPEECH_DBFS) and when it is
over (OFFSET_MS below floor + OFFSET_DB). Pure Python, no numpy.

Synthetic PCM only: digital silence, steady noise at several levels, a sudden noise that stays, short clicks, speech-like bursts
(a voiced 150 Hz tone in syllables of 180 ms with 70 ms dips), fed at the phone's 100 ms cadence and at other packet sizes.
"""
import time

import pytest

from echo_sync import local_ear
from echo_sync.local_ear import SpeechOnset
from helpers_s0_audio import PACKET_MS, RATE, ROOM, VOICE, mix, ms, noise, packets, pcm, speech, tone


def heard(data, packet_ms=PACKET_MS, detector=None):
    """What the detector says for each packet, as the transport feeds it."""
    detector = detector or SpeechOnset()
    return [detector.feed(packet) for packet in packets(data, packet_ms)]


def onsets(events):
    return [index for index, event in enumerate(events) if event == 'onset']


def test_digital_silence_is_never_speech():
    assert set(heard(pcm([0] * ms(10_000)))) == {None}


@pytest.mark.parametrize('level', [-65, ROOM, -40, -30])
def test_steady_noise_is_never_speech(level):
    assert onsets(heard(pcm(noise(10_000, level)))) == [], f'steady noise at {level} dBFS'


def test_a_word_over_room_noise_is_heard_in_the_packet_where_it_starts():
    room = noise(4000, ROOM)
    word = [0.0] * ms(2000) + speech(600, VOICE)
    events = heard(pcm(mix(room, word)))
    assert onsets(events) == [20], events                     # the word starts at 2.0 s: packet 20 (2.0-2.1 s)


def test_speech_that_starts_inside_a_packet_is_heard_within_two_hundred_ms():
    for start_ms in (2010, 2050, 2090):
        room = noise(4000, ROOM, seed=start_ms)
        word = [0.0] * ms(start_ms) + speech(600, VOICE)
        found = onsets(heard(pcm(mix(room, word))))
        assert len(found) == 1, (start_ms, found)
        heard_at = (found[0] + 1) * PACKET_MS                 # the end of the packet that carried the onset
        assert heard_at - start_ms <= 200, f'speech from {start_ms} ms was heard at {heard_at} ms'


def test_in_a_noisy_room_a_voice_fifteen_db_louder_is_heard():
    room = noise(5000, -42)
    word = [0.0] * ms(3000) + speech(800, -27)
    assert onsets(heard(pcm(mix(room, word)))) == [30]


def test_dips_between_syllables_keep_one_utterance_and_its_packets_are_speech():
    room = noise(5000, ROOM)
    utterance = [0.0] * ms(2000) + speech(1500, VOICE)
    events = heard(pcm(mix(room, utterance)))
    assert onsets(events) == [20], events
    assert all(event == 'speech' for event in events[21:35]), events[21:35]


def test_a_pause_of_three_hundred_ms_or_more_ends_the_utterance():
    room = noise(6000, ROOM)
    for pause_ms, count in ((200, 1), (400, 2)):
        talk = [0.0] * ms(2000) + speech(500, VOICE) + [0.0] * ms(pause_ms) + speech(500, VOICE)
        assert len(onsets(heard(pcm(mix(room, talk))))) == count, f'a pause of {pause_ms} ms'


def test_after_the_utterance_the_detector_is_quiet_again():
    room = noise(6000, ROOM)
    talk = [0.0] * ms(2000) + speech(800, VOICE)
    events = heard(pcm(mix(room, talk)))
    assert set(events[32:]) == {None}, 'well after the speech ended (2.8 s + the 300 ms of offset) nothing is heard'


def test_a_click_too_short_to_be_a_syllable_is_not_speech_wherever_it_falls():
    room = noise(4000, ROOM)
    for offset_ms in (0, 7, 13):
        click = [0.0] * (ms(2000) + RATE * offset_ms // 1000) + tone(20, -10)
        assert onsets(heard(pcm(mix(room, click)))) == [], f'a 20 ms click {offset_ms} ms into a frame'


def test_sound_too_quiet_to_be_speech_is_not_speech_even_over_digital_silence():
    quiet = [0.0] * ms(2000) + speech(1000, local_ear.MIN_SPEECH_DBFS - 10)
    assert onsets(heard(pcm(quiet))) == []


def test_a_noise_that_starts_and_stays_is_one_start_at_most_and_is_then_ignored():
    before = noise(2000, -65, seed=3)
    fan = noise(10_000, -35, seed=4)
    events = heard(pcm(before + fan))
    assert len(onsets(events)) <= 1, onsets(events)
    assert set(events[-50:]) == {None}, 'five seconds into the steady noise the detector has adapted to it'


def test_the_packet_size_does_not_change_when_speech_is_heard():
    room = noise(6000, ROOM, seed=7)
    talk = [0.0] * ms(1530) + speech(500, VOICE) + [0.0] * ms(600) + speech(700, VOICE)
    data = pcm(mix(room, talk))
    reference = [(index + 1) * 20 for index in onsets(heard(data, packet_ms=20))]   # exact to a frame
    assert len(reference) == 2, reference
    for packet_ms in (100, 37, 250):
        found = onsets(heard(data, packet_ms=packet_ms))
        assert len(found) == len(reference), (packet_ms, found)
        for index, onset_ms in zip(found, reference):
            assert index * packet_ms < onset_ms <= (index + 1) * packet_ms, (packet_ms, index, onset_ms)


def test_empty_and_odd_packets_are_tolerated():
    detector = SpeechOnset()
    assert detector.feed(b'') is None
    assert detector.feed(b'\x01') is None
    data = pcm(noise(500, ROOM))
    assert detector.feed(data[:333]) is None and detector.feed(data[333:]) is None


def test_the_cost_is_bounded():
    """60 s of microphone audio at the phone's cadence, with speech in it, in well under a second of CPU (the laptop is a 4-core N95)."""
    room = noise(5000, ROOM)
    talk = mix(room, [0.0] * ms(1000) + speech(2500, VOICE))
    data = pcm(talk) * 12
    detector = SpeechOnset()
    chunks = packets(data)
    started = time.perf_counter()
    for chunk in chunks:
        detector.feed(chunk)
    elapsed = time.perf_counter() - started
    assert len(chunks) == 600 and elapsed < 1.0, f'{elapsed:.3f} s for 60 s of audio'
