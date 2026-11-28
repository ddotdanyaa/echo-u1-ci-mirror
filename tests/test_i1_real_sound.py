"""I1 (U128 U83 U106 U81, the part that needs no phone): the stand of real sound.

A recording of a call is made here on the spot (tones for the owner's words, room tone between, one hole of digital zero): the repository keeps no recording and no transcript. The words are cut, composed into
phrases, cut into packets with stalls and losses, and the conversation goes through the real chain (``stand.SoundStand``: the real ControlledMedia, the wire, the ShadowEar with the repo's own ``SpeechOnset`` on these
samples, the FastText channel). Nothing here measures time on a laptop or a phone: the clock is virtual.
"""
import random
from array import array

import pytest

from tools.replay import input_replay
from tools.replay import real_sound as RS
from tools.replay import stand

VOCABULARY = 'сколько будет два умножить на три плюс четыре стоп ну подожди ещё раз'.split()


def make_call(seed=0):
    """A synthetic recording: each word of the vocabulary a tone of its own, room tone between them, a digital hole in the middle; and the index of its words."""
    rng = random.Random(seed)

    def room(seconds):
        return array('h', (rng.randint(-15, 15) for _ in range(int(seconds * RS.RATE))))
    a, words = room(1.0), []
    for n, text in enumerate(VOCABULARY * 2):
        body = RS.tone(0.30 + 0.04 * (n % 3), 180 + 37 * n)
        words.append({'w': text, 'start': len(a) / RS.RATE, 'end': (len(a) + len(body)) / RS.RATE, 'conf': 0.9, 'clean': True})
        a.extend(body)
        a.extend(room(0.40))
    hole_at = len(a)
    a.extend(array('h', [0] * int(0.5 * RS.RATE)))                  # the recorder's hole
    a.extend(room(1.0))
    index = {'utterances': [{'words': words}]}
    return RS.Recording(RS.pcm_of(a), RS.RATE, [(hole_at / RS.RATE, 0.5)]), index


@pytest.fixture(scope='module')
def bank():
    recording, index = make_call()
    return RS.Bank.of(recording, RS.words_of(index))


PHRASES = {'question': 'сколько будет два умножить на три', 'answer': 'Шесть.', 'question2': 'сколько будет три плюс четыре', 'answer2': 'Семь.', 'stop': 'стоп', 'chatter': 'ну подожди',
           'fix': 'сколько будет два умножить на четыре', 'fixed_answer': 'Восемь.', 'doubt': 'ну ещё раз'}


# ---- the bank and the composition --------------------------------------------------------------------------------------------

def test_words_of_takes_only_clean_and_sure_words():
    index = {'utterances': [{'words': [{'w': 'да', 'start': 1.0, 'end': 1.4, 'conf': 0.9, 'clean': True}, {'w': 'нет', 'start': 2.0, 'end': 2.4, 'conf': 0.9, 'clean': False},
                                       {'w': 'вот', 'start': 3.0, 'end': 3.4, 'conf': 0.1, 'clean': True}, {'w': 'и', 'start': 4.0, 'end': 4.05, 'conf': 0.9, 'clean': True}]}]}
    assert [w.text for w in RS.words_of(index)] == ['да', 'вот']
    assert [w.text for w in RS.words_of(index, min_conf=0.5)] == ['да']
    assert [w.text for w in RS.words_of(index, only_clean=False)] == ['да', 'нет', 'вот']


def test_a_composed_phrase_has_every_word_in_order_and_no_digital_hole(bank):
    a, spans = bank.compose('сколько будет два умножить на три', random.Random(1))
    assert [t for t, _, _ in spans] == 'сколько будет два умножить на три'.split()
    assert all(spans[i][2] <= spans[i + 1][1] for i in range(len(spans) - 1))
    assert RS.zero_runs(a) == []


def test_the_room_tone_is_taken_from_a_stretch_without_the_recorders_hole():
    recording, _ = make_call()
    noise = RS.Noise.of(recording.pcm, recording.rate)
    assert noise.a is not None and RS.zero_runs(noise.a) == [] and RS.level_db(RS.pcm_of(noise.a)) < -60
    assert RS.zero_runs(noise.take(48000, random.Random(3))) == []


def test_denull_fills_a_hole_with_room_tone():
    recording, _ = make_call()
    a = RS.samples(recording.pcm)
    assert RS.zero_runs(a)
    RS.denull(a, RS.Noise.of(recording.pcm), random.Random(2))
    assert RS.zero_runs(a) == []


def test_a_word_the_bank_does_not_have_is_named_and_the_step_is_skipped(bank):
    assert bank.missing('сколько будет миллион') == ['миллион']
    with pytest.raises(KeyError):
        bank.compose('сколько будет миллион', random.Random(0))
    audio = RS.build(bank, [RS.Step('question', 'сколько будет миллион', answer='x'), RS.Step('chatter', 'ну подожди')], seed=1)
    assert [i.text for i in audio.items] == ['ну подожди'] and audio.skipped[0][1] == ['миллион']
    with pytest.raises(KeyError):
        RS.build(bank, [RS.Step('chatter', 'миллион')], strict=True)


def test_the_catalog_has_the_owners_scenes_and_every_scene_can_be_built(bank):
    catalog = RS.scenes(PHRASES)
    assert {'question_under_the_hand', 'barge_in', 'repeat_the_last_word', 'fix_the_number', 'quick_questions', 'change_of_topic', 'silence'} <= set(catalog)
    for name, steps in catalog.items():
        missing = {w for s in steps for w in bank.missing(s.text)}
        assert missing <= {'шесть', 'восемь'} or not missing, (name, missing)


# ---- the packets ------------------------------------------------------------------------------------------------------------

def test_packets_are_twenty_ms_and_carry_the_whole_sound():
    pcm = bytes(48000 * 3)
    got = RS.arrivals(pcm)
    assert len(got) == 150 and b''.join(p.data for p in got) == pcm and got[1].t == pytest.approx(0.02) and got[1].at == pytest.approx(0.02)


def test_a_stall_gives_a_burst_in_the_order_of_the_sound_and_loses_nothing():
    got = RS.arrivals(bytes(48000 * 3), stalls=[(1.0, 0.5)])
    inside = [p for p in got if 1.0 <= p.at < 1.5]
    assert len(inside) == 25 and all(1.5 <= p.t < 1.51 for p in inside) and [p.at for p in inside] == sorted(p.at for p in inside)
    assert not any(1.0 < p.t < 1.5 for p in got) and len(got) == 150


def test_loss_and_holes_remove_packets_and_the_seed_makes_it_the_same_every_time():
    pcm = bytes(48000 * 3)
    assert RS.arrivals(pcm, loss=0.2, seed=4) == RS.arrivals(pcm, loss=0.2, seed=4) and 90 < len(RS.arrivals(pcm, loss=0.2, seed=4)) < 150
    assert len(RS.arrivals(pcm, holes=[(1.0, 0.5)])) == 125


def test_the_detector_finds_each_composed_phrase_on_the_real_samples(bank):
    audio = RS.build(bank, [RS.Step('question', PHRASES['question'], 1.0, 'Шесть.'), RS.Step('chatter', PHRASES['chatter'], 1.5)], seed=3)
    watch = RS.Watch()
    for p in RS.arrivals(audio.pcm):
        watch.feed(p.data)
    got = watch.take()
    assert got == ['onset', 'end', 'onset', 'end']


# ---- the real chain on the sound -------------------------------------------------------------------------------------------

def scene(bank, name, seed=5):
    return RS.build(bank, RS.scenes(PHRASES)[name], seed=seed)


def test_a_question_said_with_the_owners_words_is_heard_and_answered_once(bank):
    audio = RS.build(bank, [RS.Step('question', PHRASES['question'], 1.0, 'Шесть.')], seed=2)
    out = stand.run_sound(1, audio)
    row = stand.decisions(out)[0]
    assert row['ear_at'] is not None, 'the ear heard nothing of the composed phrase'
    assert row['first_cue'] and 'Шесть' in row['first_cue'], stand.describe(out)
    assert [v for v in out.violations if v[0] != 'A2e'] == [], stand.describe(out)


@pytest.mark.parametrize('name', ['quick_questions', 'barge_in', 'change_of_topic', 'fix_the_number'])
def test_the_scenes_of_the_owner_keep_the_invariants(bank, name):
    audio = scene(bank, name)
    if audio.skipped:
        pytest.skip(f'the synthetic bank lacks {audio.skipped[0][1]}')
    out = stand.run_sound(2, audio)
    assert out.crash is None, out.crash
    assert [v for v in out.violations if v[0] != 'A2e'] == [], stand.describe(out)


def test_a_stall_in_the_packets_still_gives_one_answer_and_no_exception(bank):
    audio = RS.build(bank, [RS.Step('question', PHRASES['question'], 1.0, 'Шесть.')], seed=2)
    packets = RS.arrivals(audio.pcm, stalls=[(2.0, 1.2)], loss=0.02, seed=9)
    out = stand.run_sound(3, audio, packets=packets)
    assert out.crash is None and [v for v in out.violations if v[0] != 'A2e'] == [], stand.describe(out)


def test_a_question_without_an_answer_is_refused(bank):
    audio = RS.build(bank, [RS.Step('question', PHRASES['question'], 1.0)], seed=2)
    with pytest.raises(ValueError):
        stand.SoundStand(1, audio)


def test_the_conversation_of_one_seed_is_the_same_twice(bank):
    audio = RS.build(bank, [RS.Step('question', PHRASES['question'], 1.0, 'Шесть.')], seed=2)
    a, b = stand.run_sound(4, audio), stand.run_sound(4, audio)
    assert [c[:3] for c in a.cues] == [c[:3] for c in b.cues] and stand.decisions(a) == stand.decisions(b)


def test_the_conversation_by_packets_goes_through_the_input_replay(bank):
    audio = RS.build(bank, [RS.Step('question', PHRASES['question'], 1.0, 'Шесть.')], seed=2)
    packets = RS.arrivals(audio.pcm)
    out = stand.run_sound(1, audio, packets=packets)
    rows = input_replay.rows_of(packets)
    assert sum(r[3] for r in rows) == 960 * len(packets) and rows[0][2] == 50
    got = input_replay.run_sound(out, packets)
    assert got['closed'] is True and any(m['name'] == 'A2_shows' for m in got['metrics'])


# ---- U81: what grows -----------------------------------------------------------------------------------------------------------

def test_growth_verdict_says_held_for_flat_rows_and_names_what_grew():
    flat = [{'t': 300.0 + 60 * n, 'threads': 5, 'agenda': 3, 'traced': 1000000} for n in range(10)]
    assert RS.growth_verdict(flat) == (True, [])
    growing = [dict(r, threads=5 + n, traced=1000000 * (1 + n)) for n, r in enumerate(flat)]
    held, why = RS.growth_verdict(growing)
    assert held is False and len(why) == 2
    assert RS.growth_verdict(flat[:1])[0] is None


def test_a_longer_call_of_the_catalog_has_the_asked_length_and_the_stand_samples_its_growth(bank):
    audio = RS.long_call(bank, PHRASES, 1, seed=1)
    assert audio.seconds >= 30 and audio.items
    out = stand.run_sound(5, RS.build(bank, [RS.Step('chatter', PHRASES['chatter'], 1.0)] * 3, seed=1), length=130)
    assert out.growth and {'t', 'threads', 'agenda', 'traced'} <= set(out.growth[0])
