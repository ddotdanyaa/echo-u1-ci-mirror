"""ear-early (R04; C6, C7 of analysis/08_LATENCY_BRAINSTORM.md): an early text on 120-150 ms of silence, thrown away when the speech goes on, and a
recognizer vocabulary from the material without numbers or «не». The recognizer is a FAKE (no model here): the checks are on the ear's order of events, not on
latency. Nothing early ever reaches ``poll`` (what ``ear_heard`` acts on): it goes to ``on_early`` and the trace only."""
import time

import pytest

from echo_sync import ear_shadow, ear_sherpa
from echo_sync.local_ear import FRAME_MS, SpeechOnset

PCM = bytes(2) * 2400


pytestmark = pytest.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)


class Detector:
    """S0's contract plus ``quiet_ms``: script steps 'onset', 'speech', ('quiet', ms) = speaking, ms of silence so far, 'end'."""

    def __init__(self, script):
        self.script, self.speaking, self.quiet_ms = list(script), False, 0
        self.level = self.floor = -40.0

    def feed(self, pcm):
        step = self.script.pop(0) if self.script else 'end'
        if step == 'onset':
            self.speaking, self.quiet_ms = True, 0
            return 'onset'
        if step == 'speech':
            self.quiet_ms = 0
            return 'speech'
        if isinstance(step, tuple):
            self.quiet_ms = step[1]
            return None
        self.speaking, self.quiet_ms = False, 0
        return None


class Recognizer:
    def __init__(self, partials, final):
        self.partials, self.final, self.peeks = list(partials), final, 0

    def start(self, hotwords=None):
        return {}

    def accept(self, stream, pcm):
        pass

    def peek(self, stream):
        self.peeks += 1
        return self.partials.pop(0) if self.partials else ''

    def finish(self, stream):
        return self.final


def make(script, partials, final, *, early_ms=135, recognizer=None):
    recognizer = recognizer or Recognizer(partials, final)
    worker = ear_shadow.EarWorker(lambda: recognizer)
    assert worker.wait_ready(5)
    got = []
    ear = ear_shadow.ShadowEar(worker, lambda text: ('none', 'x', 1, 0), detector=Detector(script), early_ms=early_ms,
                               on_early=lambda **record: got.append(record))
    return ear, got, recognizer


def run(ear, count):
    for i in range(count):
        ear.feed(PCM, input_ms=100 * (i + 1))


def drain(ear, want, timeout=5.0):
    out, end = [], time.monotonic() + timeout
    while len(out) < want and time.monotonic() < end:
        out += ear.poll()
        time.sleep(0.01)
    return out


def settle(ear, got, want, timeout=5.0):
    """Poll until ``want`` early records came; the finals polled on the way are kept in ``ear.finals``."""
    end = time.monotonic() + timeout
    ear.finals = getattr(ear, 'finals', [])
    while len(got) < want and time.monotonic() < end:
        ear.finals += ear.poll()
        time.sleep(0.01)


def test_the_energy_detector_and_silero_report_the_silence_so_far_in_ms():
    d = SpeechOnset()
    loud, quiet = (bytes([0, 64]) * 480) * 5, bytes(2) * 480 * 7        # 100 ms of tone, then 140 ms of nothing
    d.feed(bytes(2) * 480 * 50)                                           # a second of room first: the floor
    d.feed(loud)
    assert d.speaking and d.quiet_ms == 0
    d.feed(quiet)
    assert d.speaking and d.quiet_ms == 7 * FRAME_MS
    d.feed(loud)
    assert d.quiet_ms == 0


def test_the_silero_detector_hands_on_the_meters_silence():
    from echo_sync.vad_silero import SileroOnset

    class Model:
        speech = True
        window_size = lambda self: 512          # noqa: E731
        reset = lambda self: None               # noqa: E731
        is_speech = lambda self, w: self.speech  # noqa: E731
    model = Model()
    d = SileroOnset(model)
    d.feed(bytes(2) * 480 * 50)
    d.feed((bytes([0, 64]) * 480) * 5)
    d.feed(bytes(2) * 480 * 7)
    assert d.speaking and d.quiet_ms == 7 * FRAME_MS
    model.speech = False
    d.feed(bytes(2) * 480 * 7)
    assert not d.speaking and d.quiet_ms == 0


def test_a_text_is_taken_on_135_ms_of_silence_and_never_reaches_poll():
    ear, got, rec = make(['onset', 'speech', ('quiet', 140), 'end'], ['сколько будет'], 'сколько будет два плюс два')
    run(ear, 4)
    settle(ear, got, 1)
    assert [r['text'] for r in got] == ['сколько будет'] and got[0]['discarded'] is False
    [final] = ear.finals or drain(ear, 1)
    assert final['text'] == 'сколько будет два плюс два' and 'early' not in final
    assert rec.peeks == 1 and ear.early_counts['taken'] == 1


def test_no_text_before_the_silence_is_long_enough():
    ear, got, rec = make(['onset', 'speech', ('quiet', 100), 'speech', 'end'], ['x'], 'готово')
    run(ear, 5)
    drain(ear, 1)
    assert rec.peeks == 0 and got == []


def test_speech_that_goes_on_discards_the_early_text():
    ear, got, _ = make(['onset', ('quiet', 140), 'speech', 'speech', 'end'], ['сколько будет'], 'сколько будет два плюс два')
    run(ear, 5)
    drain(ear, 1)
    settle(ear, got, 1)
    assert got[0]['discarded'] is True and got[0]['text'] == 'сколько будет'
    assert ear.early_counts == {'sent': 1, 'taken': 1, 'discarded': 1, 'confirmed': 0}


def test_one_peek_per_pause_and_a_new_one_after_the_speech_resumed():
    ear, got, rec = make(['onset', ('quiet', 140), ('quiet', 240), 'speech', ('quiet', 150), 'end'], ['а', 'а б'], 'а б')
    run(ear, 6)
    drain(ear, 1)
    settle(ear, got, 2)
    assert rec.peeks == 2 and [r['discarded'] for r in got] == [True, False]


def test_an_early_text_equal_to_the_final_is_counted_as_confirmed():
    ear, got, _ = make(['onset', ('quiet', 140), 'end'], ['Сколько, будет два?'], 'сколько будет два')
    run(ear, 3)
    drain(ear, 1)
    assert ear.early_counts['confirmed'] == 1


def test_off_by_default_and_without_a_peeking_recognizer_nothing_happens():
    worker = ear_shadow.EarWorker(lambda: Recognizer([], 'да'))
    ear = ear_shadow.ShadowEar(worker, lambda t: ('none', 'x', 1, 0), detector=Detector(['onset', ('quiet', 200), 'end']))
    assert worker.wait_ready(5)
    run(ear, 3)
    drain(ear, 1)
    assert ear.early_counts['sent'] == 0

    class NoPeek:
        start = lambda self, h=None: {}                # noqa: E731
        accept = lambda self, s, p: None               # noqa: E731
        finish = lambda self, s: 'да'                  # noqa: E731
    ear, got, _ = make(['onset', ('quiet', 200), 'end'], [], '', recognizer=NoPeek())
    run(ear, 3)
    assert [r['text'] for r in drain(ear, 1)] == ['да'] and got == []


def test_a_failing_peek_costs_the_early_text_only():
    class Bad(Recognizer):
        def peek(self, stream):
            raise RuntimeError('boom')
    ear, got, _ = make(['onset', ('quiet', 140), 'end'], [], 'да', recognizer=Bad([], 'да'))
    run(ear, 3)
    assert [r['text'] for r in drain(ear, 1)] == ['да'] and not ear.off


def test_the_profile_switch_builds_the_ear_with_the_early_silence():
    from echo_sync.settings import resolve
    assert resolve({})['ear_early_ms'] == 0
    assert resolve({'ear_early_ms': 135})['ear_early_ms'] == 135
    assert resolve({'ear_early_ms': 20})['ear_early_ms'] == 0, 'under 100 ms is not a pause: off'
    assert resolve({'ear_early_ms': 'x'})['ear_early_ms'] == 0


# --- C6: the vocabulary from the material ------------------------------------------------------------------------------------------

def phrases(hw):
    return hw.split('/')


MATERIAL = ['Сублимация это переход вещества из твёрдого состояния в газообразное.', 'Температура кипения воды при давлении 101 килопаскаль не меняется.',
            'Сублимацию используют при сушке продуктов. Сублимация йода идёт при нагревании.']


def test_material_terms_are_plain_words_by_frequency_without_numbers_or_negation():
    terms = ear_sherpa.material_terms(MATERIAL, limit=6)
    assert terms[0].startswith('сублимаци') and 1 <= len(terms) <= 6
    for banned in ('101', 'не', 'сто', 'один'):
        assert banned not in ' '.join(terms).split()
    assert all(len(t) >= 5 for t in terms)


def test_hotwords_carry_the_waiting_portion_then_the_material_then_the_commands():
    got = phrases(ear_sherpa.hotwords_for('Переход вещества', material=MATERIAL))
    assert got[0] == 'переход вещества' and got[-5:] == list(ear_sherpa.COMMAND_HOTWORDS)
    assert any(p.startswith('сублимаци') for p in got) and len(got) == len(set(got))


def test_the_material_never_adds_a_number_word_even_inside_a_term():
    got = ' '.join(phrases(ear_sherpa.hotwords_for(None, material=['Статья четыреста двадцать вторая не допускает трёх раз', 'в 1914 году'])))
    for word in ('четыреста', 'двадцать', 'вторая', 'трёх', '1914', 'не'):
        assert word not in got.split(), word


def test_the_vocabulary_is_bounded():
    big = [' '.join(f'слово{chr(1072 + i % 30)}{chr(1072 + i // 30)}ыйтест' for i in range(400))]
    hw = ear_sherpa.hotwords_for(None, material=big)
    assert len(phrases(hw)) <= ear_sherpa.MATERIAL_TERMS + len(ear_sherpa.COMMAND_HOTWORDS) and len(hw) <= 1500


def test_controller_hotwords_use_the_whole_answer_as_the_material():
    class C:
        settings = {}
        def state(self):                                  # noqa: E301
            return {'chunks': ['Переход вещества.', 'Сублимация идёт без плавления.'], 'chunk_index': 0}
    got = phrases(ear_shadow.controller_hotwords(C())())
    assert 'переход вещества' in got and any(p.startswith('сублимаци') for p in got)


def test_the_material_vocabulary_has_no_key_and_the_waiting_portion_comes_first():
    from echo_sync.settings import resolve
    assert 'ear_vocab' not in resolve({'ear_vocab': 'on'})

    class C:
        settings = {}
        state = lambda self: {'chunks': ['Переход вещества.', 'Сублимация идёт без плавления.'], 'chunk_index': 0}  # noqa: E731
    got = phrases(ear_shadow.controller_hotwords(C())())
    assert got[0] == 'переход вещества' and any(p.startswith('сублимаци') for p in got)
