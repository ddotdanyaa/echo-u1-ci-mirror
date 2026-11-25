"""Task S1: the local ear in SHADOW mode (scripts/DUAL_SYSTEM_DESIGN.md §3.2, §3.8 S1; bake-off: U1/05_WORK/scripts/local_ear_bakeoff.py).

The ear listens to the phone's microphone next to the cloud, recognizes each utterance with a local model in a worker thread and
writes down what the EXISTING classifier would decide on that text for the portion that waits - nothing else. It never changes the
controller's state, never answers the phone, never holds the call (feed() does no decoding), and any failure only switches it off.
Off unless the profile says ``"local_ear": "shadow"``.

The recognizer and the speech detector are the two boundaries replaced here (a scripted detector with S0's ``SpeechOnset`` contract,
a recognizer whose "heard" texts are given); the controller, its engine and the classifier are the production ones.
"""
import logging
import threading
import time

import pytest

import helpers_s6_ack as H
from echo_sync import ear_shadow
from echo_sync.settings import resolve

ANSWER = 'Свойство тела сопротивляться изменению своего движения. Это называется инерцией. Чем больше масса, тем сильнее инерция.'
# F1 (wave F): the first cue is the first meaning portion - the whole first sentence (WAVE 2 / L2 had «Свойство тела»)
PORTION = 'Свойство тела сопротивляться изменению своего движения.'
FULL = 'свойство тела сопротивляться изменению своего движения'   # F1: a whole repeat of PORTION, as an ASR returns it


pytestmark = pytest.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)


def packet(tag):
    """100 ms of PCM16LE 24 kHz whose bytes say which packet it is (the order the recognizer gets them in is checked)."""
    return bytes([tag % 251, 0]) * 2400


class ScriptedDetector:
    """S0's ``SpeechOnset`` contract (task-s0 echo_sync/local_ear.py): ``feed(pcm)`` -> 'onset' | 'speech' | None, and ``speaking``.
    The script says what each packet is: 'quiet', 'onset', 'speech' or 'end' (the speech stopped: None and not speaking)."""

    def __init__(self, script):
        self.script = list(script)
        self.speaking = False
        self.level = self.floor = -40.0

    def feed(self, pcm):
        step = self.script.pop(0) if self.script else 'quiet'
        if step == 'onset':
            self.speaking = True
            return 'onset'
        if step == 'speech':
            return 'speech'
        if step == 'end':
            self.speaking = False
        return None


class FakeRecognizer:
    """The recognizer boundary: every stream keeps the audio it was given; ``finish`` returns the next scripted text (or raises)."""

    def __init__(self, texts, *, gate=None):
        self.texts = list(texts)
        self.streams = []
        self.gate = gate

    def start(self, hotwords=None):
        stream = {'pcm': bytearray(), 'hotwords': hotwords, 'finished': False}
        self.streams.append(stream)
        return stream

    def accept(self, stream, pcm):
        if self.gate is not None:
            self.gate.wait(10)
        stream['pcm'] += pcm

    def finish(self, stream):
        stream['finished'] = True
        text = self.texts.pop(0)
        if isinstance(text, Exception):
            raise text
        return text


def drain(ear, want, timeout=10.0):
    """Poll the ear (the transport's tick) until ``want`` records came back."""
    records, deadline = [], time.monotonic() + timeout
    while len(records) < want and time.monotonic() < deadline:
        records += ear.poll()
        time.sleep(0.01)
    return records


def run(ear, count, start=0):
    for i in range(start, start + count):
        ear.feed(packet(i), input_ms=100 * (i + 1))


@pytest.fixture
def dictation(tmp_path):
    d = H.Dictation(tmp_path / 'ear', ANSWER)
    assert d.current == PORTION
    return d


def make_ear(d, script, texts, *, report=None, gate=None):
    recognizer = FakeRecognizer(texts, gate=gate)
    worker = ear_shadow.EarWorker(lambda: recognizer)
    assert worker.wait_ready(5)
    ear = ear_shadow.ShadowEar(worker, ear_shadow.controller_decider(d.controller), detector=ScriptedDetector(script),
                               report=report, clock=d.clock)
    return ear, recognizer


# --- off unless asked -------------------------------------------------------------------------------------------------------------

def test_no_ear_unless_the_profile_says_shadow(dictation):
    made = []

    def detector():
        made.append(1)
        return ScriptedDetector([])
    assert ear_shadow.for_call(resolve({}), dictation.controller, detector_factory=detector) is None
    assert resolve({'local_ear': 'on'})['local_ear'] == 'off', 'acting is S3, not this setting: an unknown mode is off'
    assert ear_shadow.for_call(resolve({'local_ear': 'on'}), dictation.controller, detector_factory=detector) is None
    assert made == [], 'off: not even a detector is made'
    worker = ear_shadow.EarWorker(lambda: FakeRecognizer([]))
    ear = ear_shadow.for_call(resolve({'local_ear': 'shadow'}), dictation.controller, detector_factory=detector, worker=worker)
    assert isinstance(ear, ear_shadow.ShadowEar) and made == [1]


# --- what it does with an utterance --------------------------------------------------------------------------------------------------

def test_a_repeat_heard_locally_is_decided_like_a_cloud_final_and_nothing_moves(dictation):
    before = dict(dictation.state)
    ear, _ = make_ear(dictation, ['quiet', 'quiet', 'onset', 'speech', 'speech', 'end'], [FULL])
    run(ear, 6)
    [record] = drain(ear, 1)
    assert (record['kind'], record['reason']) == ('ack', 'ack_ru_canonical')
    assert (record['revision'], record['index']) == (before['revision'], 0)
    assert dictation.state == before, 'shadow: the controller is only read'


def test_a_negated_repeat_heard_locally_is_not_an_ack(dictation):
    ear, _ = make_ear(dictation, ['onset', 'speech', 'end'], ['не ' + FULL])
    run(ear, 3)
    [record] = drain(ear, 1)
    assert record['kind'] != 'ack'


def test_the_recognizer_gets_the_pre_roll_then_the_speech_in_order(dictation):
    script = ['quiet'] * 5 + ['onset', 'speech', 'end', 'quiet']
    ear, recognizer = make_ear(dictation, script, [FULL])
    run(ear, len(script))
    drain(ear, 1)
    [stream] = recognizer.streams
    assert bytes(stream['pcm']) == b''.join(packet(i) for i in (2, 3, 4, 5, 6, 7)), \
        'the 3 packets before the start (300 ms), the start, the speech and the packet in which it ended'


def test_the_log_names_the_verdict_and_never_the_words_the_trace_gets_the_text(dictation, caplog):
    notes = []
    ear, _ = make_ear(dictation, ['onset', 'speech', 'end'], [FULL],
                      report=lambda ev, **fields: notes.append((ev, fields)))
    with caplog.at_level(logging.INFO, logger='echo-sync'):
        run(ear, 3)
        drain(ear, 1)
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith('echo-sync ear ')]
    assert len(lines) == 1 and 'kind=ack' in lines[0]
    assert not any('свойство' in r.getMessage() for r in caplog.records)
    assert not any(r.getMessage().startswith('echo-sync decision ') for r in caplog.records), \
        'a shadow verdict must never look like a controller decision to the call trace tap'
    finals = [fields for ev, fields in notes if ev == 'ear_final']
    assert len(finals) == 1 and finals[0]['text'] == FULL and finals[0]['kind'] == 'ack'
    assert finals[0]['lang'] == 'ru'


def test_times_say_how_long_the_speech_was_and_how_late_the_verdict_came(dictation):
    ear, _ = make_ear(dictation, ['onset', 'speech', 'speech', 'end'], [FULL])
    for i in range(4):
        ear.feed(packet(i), input_ms=100 * (i + 1))
        dictation.clock.advance(0.1)
    dictation.clock.advance(0.25)
    [record] = drain(ear, 1)
    assert record['speech_ms'] == 300, 'from the packet of the start to the packet of the end'
    assert record['lag_ms'] == 350, 'from the end of the speech to the moment the verdict was taken'
    assert (record['onset_input_ms'], record['offset_input_ms']) == (100, 400)


# --- never holds or breaks the call ---------------------------------------------------------------------------------------------------

def test_feed_never_waits_for_the_recognizer(dictation):
    gate = threading.Event()
    ear, _ = make_ear(dictation, ['onset'] + ['speech'] * 8 + ['end'], [FULL], gate=gate)
    done = threading.Event()
    threading.Thread(target=lambda: (run(ear, 10), done.set()), daemon=True).start()
    assert done.wait(2.0), 'the loop of the transport was held by a busy recognizer'
    gate.set()
    assert len(drain(ear, 1)) == 1


def test_too_much_audio_waiting_costs_a_record_and_says_so_once(dictation):
    gate = threading.Event()
    notes = []
    script = ['onset'] + ['speech'] * 45 + ['end'] + ['onset', 'speech', 'end']
    ear, _ = make_ear(dictation, script, [FULL, FULL], gate=gate,
                      report=lambda ev, **fields: notes.append((ev, fields)))
    run(ear, 47)                              # 4.7 s of one utterance while the recognizer is stuck: more than MAX_PENDING_S
    gate.set()
    time.sleep(0.5)                           # the recognizer catches up (what waited of the dropped utterance is skipped)
    run(ear, 3, start=47)
    records = drain(ear, 2)
    time.sleep(0.2)
    records += ear.poll()
    assert [(r['kind'], r['reason'], r.get('cut')) for r in records[:1]] == [('error', 'overflow', 'overflow')] and len(records) == 2 and records[1]['lost_ms'] == 0, \
        'the utterance that did not fit has a record that says so (no verdict on its text), the next one is judged'
    assert [fields.get('state') for ev, fields in notes if ev == 'ear_state'] == ['overflow']


def test_a_model_that_cannot_load_switches_the_ear_off_quietly(dictation, caplog):
    def broken():
        raise OSError('no model')
    notes = []
    worker = ear_shadow.EarWorker(broken)
    assert not worker.wait_ready(5)
    ear = ear_shadow.ShadowEar(worker, ear_shadow.controller_decider(dictation.controller),
                               detector=ScriptedDetector(['onset', 'speech', 'end'] * 3), clock=dictation.clock,
                               report=lambda ev, **fields: notes.append((ev, fields)))
    with caplog.at_level(logging.INFO, logger='echo-sync'):
        run(ear, 9)
        assert ear.poll() == []
    assert [fields.get('state') for ev, fields in notes if ev == 'ear_state'] == ['failed']
    assert len([r for r in caplog.records if r.getMessage().startswith('echo-sync ear') and r.levelno >= logging.WARNING]) == 1


def test_speech_while_the_model_still_loads_is_skipped(dictation):
    loaded = threading.Event()
    recognizer = FakeRecognizer([FULL])

    def slow():
        loaded.wait(10)
        return recognizer
    worker = ear_shadow.EarWorker(slow)
    ear = ear_shadow.ShadowEar(worker, ear_shadow.controller_decider(dictation.controller),
                               detector=ScriptedDetector(['onset', 'speech', 'end'] * 2), clock=dictation.clock)
    run(ear, 3)                               # said while the model loads
    loaded.set()
    assert worker.wait_ready(5)
    run(ear, 3, start=3)
    records = drain(ear, 1)
    assert len(records) == 1 and len(recognizer.streams) == 1, 'only the utterance that began after the load is recognized'


def test_a_recognizer_error_costs_only_that_utterance(dictation):
    ear, _ = make_ear(dictation, ['onset', 'speech', 'end'] * 2, [RuntimeError('decoder'), FULL])
    run(ear, 6)
    records = drain(ear, 2)
    assert [r['kind'] for r in records] == ['error', 'ack']


def test_a_new_start_while_speaking_ends_the_utterance_before_it(dictation):
    ear, recognizer = make_ear(dictation, ['onset', 'speech', 'onset', 'speech', 'end'], ['свойство', FULL])
    run(ear, 5)
    records = drain(ear, 2)
    assert [r['kind'] for r in records][1] == 'ack' and len(recognizer.streams) == 2
    assert all(stream['finished'] for stream in recognizer.streams)


def test_an_endless_utterance_is_cut_and_goes_on_as_a_new_one(dictation):
    n = int(ear_shadow.MAX_UTTERANCE_S * 10)
    ear, recognizer = make_ear(dictation, ['onset'] + ['speech'] * (n + 5) + ['end'], ['свойство', 'тела'])
    for i in range(n + 7):                    # packets come 100 ms apart on the phone: give the recognizer its turn
        ear.feed(packet(i), input_ms=100 * (i + 1))
        time.sleep(0.002)
    assert len(drain(ear, 2)) == 2
    assert len(recognizer.streams) == 2


def test_an_ear_that_breaks_never_breaks_the_call(dictation, caplog):
    class BrokenDetector(ScriptedDetector):
        def feed(self, pcm):
            raise ValueError('detector bug')
    worker = ear_shadow.EarWorker(lambda: FakeRecognizer([FULL]))
    assert worker.wait_ready(5)
    notes = []
    ear = ear_shadow.ShadowEar(worker, ear_shadow.controller_decider(dictation.controller), detector=BrokenDetector([]),
                               clock=dictation.clock, report=lambda ev, **fields: notes.append((ev, fields)))
    with caplog.at_level(logging.INFO, logger='echo-sync'):
        run(ear, 3)                               # nothing escapes into the transport
        assert ear.poll() == []
    assert [fields.get('state') for ev, fields in notes if ev == 'ear_state'] == ['broken']
    assert len([r for r in caplog.records if r.getMessage().startswith('echo-sync ear') and r.levelno >= logging.WARNING]) == 1

    def wrong(text):
        raise RuntimeError('classifier bug')
    second = ear_shadow.ShadowEar(worker, wrong, detector=ScriptedDetector(['onset', 'speech', 'end']), clock=dictation.clock)
    run(second, 3)
    time.sleep(0.3)
    assert second.poll() == []
    assert second.poll() == [], 'switched off for the rest of the call'


def test_the_recognizer_is_biased_towards_the_waiting_portion_without_numbers_or_negation(dictation):
    recognizer = FakeRecognizer([FULL])
    worker = ear_shadow.EarWorker(lambda: recognizer)
    assert worker.wait_ready(5)
    ear = ear_shadow.for_call(resolve({'local_ear': 'shadow'}), dictation.controller,
                              detector_factory=lambda: ScriptedDetector(['onset', 'speech', 'end']), worker=worker)
    run(ear, 3)
    assert len(drain(ear, 1)) == 1
    assert recognizer.streams[0]['hotwords'] == FULL + '/повтори/еще раз/стоп/хватит/дальше'


def test_without_a_speech_detector_there_is_no_ear(dictation):
    def missing():
        raise ImportError('local_ear')           # S0's detector is not in this build
    worker = ear_shadow.EarWorker(lambda: FakeRecognizer([]))
    assert ear_shadow.for_call(resolve({'local_ear': 'shadow'}), dictation.controller, detector_factory=missing, worker=worker) is None


def test_close_drops_the_open_utterance_and_the_worker_serves_the_next_call(dictation):
    recognizer = FakeRecognizer([FULL])
    worker = ear_shadow.EarWorker(lambda: recognizer)
    assert worker.wait_ready(5)
    first = ear_shadow.ShadowEar(worker, ear_shadow.controller_decider(dictation.controller),
                                 detector=ScriptedDetector(['onset', 'speech']), clock=dictation.clock)
    run(first, 2)
    first.close()
    second = ear_shadow.ShadowEar(worker, ear_shadow.controller_decider(dictation.controller),
                                  detector=ScriptedDetector(['onset', 'speech', 'end']), clock=dictation.clock)
    run(second, 3)
    assert len(drain(second, 1)) == 1
    time.sleep(0.2)
    assert first.poll() == []
