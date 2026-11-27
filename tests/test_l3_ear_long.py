"""L3 (the night of 12-13 Nov): the local ear on LONG speech. The only way, no setting:

L3: a stretch of speech longer than the window bound (``ear_shadow.MAX_UTTERANCE_S``) stays ONE recognizer stream. At the
bound the ear gives the words the recognizer has so far as the final of that window - all but the last one, which may still be growing - and the
stream goes on: no word is cut in two and none is heard by neither stream. (Before: the stream was finished at the bound and a new one began in the
middle of a word.) A window with no words resets nothing: the word held back and the stream itself go on into the next one.

The recognizer and the detector are fakes; the last tests run the real model where it is installed (the packaged SAPI phrases), skipped elsewhere.
The ear under load (the recognizer cannot keep up): test_l3_ear_load.py.
"""
import collections
import sys
import threading
import time
import wave
from pathlib import Path

import pytest

import helpers_s6_ack as H
import test_ear_shadow as T
from echo_sync import ear_shadow, ear_sherpa, timer_policy
from echo_sync.settings import resolve

PER = 3                                             # packets of audio (100 ms each) one spoken word takes
WORDS = [f'слово{j:02d}' for j in range(80)]


class WordsRecognizer:
    """A streaming recognizer whose text follows the audio: ``WORDS[j]`` is spoken in the packets ``j*PER .. j*PER+PER-1`` (a packet says its number
    in its first byte, ``test_ear_shadow.packet``). A stream reads a word whole when it got ALL its packets; a word it got a part of - the one being
    said now, or one cut by the end of the stream - reads as its first letters and a tilde, never as the word. ``peek`` is the text so far."""

    def __init__(self, *, gate=None, slow=0.0):
        self.streams, self.gate, self.slow = [], gate, slow
        self.active = self.overlaps = 0
        self.lock = threading.Lock()

    def start(self, hotwords=None):
        stream = {'tags': [], 'hotwords': hotwords, 'finished': False, 'peeks': 0}
        self.streams.append(stream)
        return stream

    def _enter(self):
        with self.lock:
            self.active += 1
            self.overlaps += self.active > 1

    def _leave(self):
        with self.lock:
            self.active -= 1

    def accept(self, stream, pcm):
        self._enter()
        try:
            if self.gate is not None:
                self.gate.wait(10)
            if self.slow:
                time.sleep(self.slow)
            stream['tags'] += [pcm[at] for at in range(0, len(pcm), 4800)]
        finally:
            self._leave()

    def text(self, stream):
        got = collections.Counter(tag // PER for tag in stream['tags'])
        return ' '.join(WORDS[j] if got[j] == PER else WORDS[j][:2] + '~' for j in sorted(got))

    def peek(self, stream):
        self._enter()
        try:
            stream['peeks'] += 1
            return self.text(stream)
        finally:
            self._leave()

    def finish(self, stream):
        self._enter()
        try:
            stream['finished'] = True
            return self.text(stream)
        finally:
            self._leave()


class NoPeek(WordsRecognizer):
    """A recognizer that cannot say its text so far."""
    peek = None


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def make(script, *, recognizer=None, **kwargs):
    recognizer = recognizer or WordsRecognizer()
    worker = ear_shadow.EarWorker(lambda: recognizer)
    assert worker.wait_ready(5)
    notes, clock = [], Clock()
    ear = ear_shadow.ShadowEar(worker, lambda text: ('silent', 'measure', None, None), detector=T.ScriptedDetector(script), clock=clock,
                               report=lambda ev, **fields: notes.append((ev, fields)), **kwargs)
    ear.test_clock, ear.test_notes = clock, notes
    return ear, recognizer


def settle(ear, timeout=5.0):
    """The worker has taken everything queued so far (the packets of a call come 100 ms apart: the recognizer has its turn)."""
    deadline = time.monotonic() + timeout
    while ear.pending > 0 and time.monotonic() < deadline:
        time.sleep(0.001)
    assert ear.pending == 0, 'the worker did not take the audio'


def feed(ear, count, start=0, *, wait=True):
    records = []
    for i in range(start, start + count):
        ear.test_clock.now = 0.1 * (i + 1)
        ear.feed(T.packet(i), input_ms=100 * (i + 1))
        if wait:
            settle(ear)
            records += ear.poll()
    return records


def rest(ear, records, want=None, timeout=5.0):
    """Poll (the transport's tick) until ``want`` records are there; None: until every window that began has given its record."""
    deadline = time.monotonic() + timeout
    while (len(records) < want if want is not None else bool(ear.spans)) and time.monotonic() < deadline:
        records += ear.poll()
        time.sleep(0.005)
    return records + ear.poll()


def spoken(first, last):
    """The words whose packets are ``first .. last`` (whole words only)."""
    return ' '.join(WORDS[j] for j in range(80) if first <= j * PER and j * PER + PER - 1 <= last)


@pytest.fixture
def window(monkeypatch):
    """A window bound of 2 s (20 packets): the 7th word (packets 18, 19, 20) is being said when it comes."""
    monkeypatch.setattr(ear_shadow, 'MAX_UTTERANCE_S', 2.0)
    return 20


# --- no setting ------------------------------------------------------------------------------------------------------------------------

def test_there_is_no_setting_for_it_any_more():
    assert 'ear_window' not in resolve({}) and 'ear_window' not in resolve({'ear_window': 'cut'})


def test_the_new_time_constant_is_in_the_table_of_timers():
    assert 'ear_shadow.MAX_STREAM_S' in timer_policy.TIMERS
    assert [key for key in timer_policy.unregistered() + timer_policy.stale() if key.startswith('ear_shadow.')] == []


# --- the window bound: carry ---------------------------------------------------------------------------------------------------------------

def test_carry_keeps_one_stream_and_every_word_is_given_once(window):
    onsets, speech = [], []
    ear, recognizer = make(['onset'] + ['speech'] * 28 + ['end'], on_onset=onsets.append,
                           on_speech=lambda uid, what: speech.append((uid, what)))
    records = rest(ear, feed(ear, 30), 2)
    assert len(recognizer.streams) == 1, 'the stream of the stretch goes on over the bound'
    first, second = records
    assert first['text'] == spoken(0, 17), 'the words the recognizer has, without the one still being said'
    assert second['text'] == spoken(18, 29), 'the word that was being said at the bound comes whole with the next window'
    assert ' '.join(r['text'] for r in records) == spoken(0, 29)
    assert (first['uid'], second['uid']) == (1, 2) and onsets == [1, 2], 'a window is an utterance of its own for whoever listens, as before'
    assert speech == [(1, 'onset'), (1, 'offset'), (2, 'onset'), (2, 'offset')]
    assert (first['onset_input_ms'], first['offset_input_ms'], second['onset_input_ms'], second['offset_input_ms']) == (100, 2000, 2000, 3000)
    assert (first['speech_ms'], second['speech_ms']) == (1900, 1000)
    assert first.get('more') is True and 'part' not in first, 'the first window says that the stretch goes on'
    assert second.get('part') == 2 and 'more' not in second, 'the next one says which window of the stretch it is'
    finals = [fields for ev, fields in ear.test_notes if ev == 'ear_final']
    assert [(f.get('more'), f.get('part')) for f in finals] == [(True, None), (None, 2)], 'the journal has the marks too'


def test_carry_over_several_windows_gives_the_text_of_one_stream(window):
    ear, recognizer = make(['onset'] + ['speech'] * 73 + ['end'])
    records = rest(ear, feed(ear, 75), 4)
    assert len(recognizer.streams) == 1
    assert ' '.join(r['text'] for r in records) == spoken(0, 74)
    assert [r.get('part') for r in records] == [None, 2, 3, 4] and [r.get('more') for r in records] == [True, True, True, None]


def test_carry_a_stretch_that_ends_right_after_the_bound_has_no_empty_tail(window):
    ear, recognizer = make(['onset'] + ['speech'] * 20 + ['end'])         # 22 packets: the word of 18-20 ends, the next has one packet
    records = rest(ear, feed(ear, 22), 2)
    assert [r['text'] for r in records] == [spoken(0, 17), WORDS[6] + ' сл~']
    assert all(r['text'] for r in records), 'the word held back at the bound is the text of the tail: an empty final does not follow a window of words'


def test_carry_a_window_without_words_resets_nothing(window, monkeypatch):
    """20 packets in which the recognizer hears one word at most: the window's final is empty (as an empty utterance was), the stream, the word held
    back and what was given so far go on."""
    monkeypatch.setattr(sys.modules[__name__], 'PER', 25)     # a word takes 2.5 s: at the bound of 2 s none is whole
    ear, recognizer = make(['onset'] + ['speech'] * 73 + ['end'])
    records = rest(ear, feed(ear, 75), 4)
    assert len(recognizer.streams) == 1
    assert records[0]['text'] == '' and records[0].get('more') is True
    assert ' '.join(r['text'] for r in records if r['text']) == spoken(0, 74) == ' '.join(WORDS[:3])


def test_carry_the_text_so_far_of_a_window_is_its_own_words(window):
    ear, recognizer = make(['onset'] + ['speech'] * 38 + ['end'], partial_ms=100)
    partials = []
    for i in range(40):
        ear.test_clock.now = 0.1 * (i + 1)
        ear.feed(T.packet(i), input_ms=100 * (i + 1))
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:                  # the recognizer has its turn: the audio taken, the text so far back
            ear.poll()
            partials += ear.take_partials()
            if ear.pending == 0 and not any(span.get('partial_flight') for span in ear.spans.values()):
                break
            time.sleep(0.001)
    later = [p['text'] for p in partials if p['uid'] == 2]
    assert later, 'the second window has its text so far'
    assert all(WORDS[0] not in text.split() and WORDS[5] not in text.split() for text in later), 'never the words of the window before'
    assert any(text.split()[0] == WORDS[6] for text in later), 'it begins with the word held back at the bound'


def test_carry_needs_a_recognizer_that_can_say_its_text_so_far(window):
    ear, recognizer = make(['onset'] + ['speech'] * 28 + ['end'], recognizer=NoPeek())
    records = rest(ear, feed(ear, 30), 2)
    assert len(recognizer.streams) == 2 and len(records) == 2, 'without ``peek`` the bound cuts as before'
    assert all('part' not in r and 'more' not in r for r in records)


def test_carry_a_stream_does_not_live_longer_than_its_bound(window, monkeypatch):
    monkeypatch.setattr(ear_shadow, 'MAX_STREAM_S', 6.0)       # three windows of 2 s
    ear, recognizer = make(['onset'] + ['speech'] * 88 + ['end'])
    records = rest(ear, feed(ear, 90), 5)
    assert [len(stream['tags']) for stream in recognizer.streams] == [60, 30], 'after three windows the stream is finished and a new one begins'
    assert [r.get('part') for r in records] == [None, 2, 3, None, 2] and [r.get('more') for r in records] == [True, True, None, True, None]


def test_carry_a_recognizer_error_at_the_bound_costs_the_two_windows_and_the_ear_goes_on(window):
    class Breaks(WordsRecognizer):
        def peek(self, stream):
            raise RuntimeError('decoder')
    ear, recognizer = make(['onset'] + ['speech'] * 28 + ['end', 'quiet', 'onset', 'speech', 'speech', 'end'], recognizer=Breaks())
    records = rest(ear, feed(ear, 36), 3)
    assert [r['kind'] for r in records] == ['error', 'error', 'silent'], 'the window, what went on of it, and then the next utterance is heard'
    assert not ear.spans and ear.current is None and not ear.off


@pytest.mark.parametrize('given, words, at, revised', [
    ([], ['а', 'б'], 0, False),
    (['а', 'б'], ['а', 'б', 'в', 'г'], 2, False),
    (['а', 'б', 'в'], ['а', 'б', 'В', 'г', 'д'], 3, True),              # the last word given reads differently now: the place is the same
    (['а', 'б', 'в'], ['а', 'б1', 'б2', 'в', 'г'], 4, True),            # a word given became two: what was given ends where its last word is now
    (['а', 'бв', 'г'], ['а', 'б', 'в', 'г', 'д'], 4, True),
    (['а', 'б', 'в', 'г'], ['а', 'бв', 'г', 'д'], 3, True),             # two words given became one
    (['а', 'б', 'в'], ['а', 'б'], 2, True),                             # the text got shorter: nothing new
    (['а', 'б', 'в'], [], 0, True),
])
def test_where_the_new_words_begin_when_the_recognizer_changed_what_it_gave(given, words, at, revised):
    assert ear_shadow._resume(given, words) == (at, revised)


# --- the real model (skipped where it is not installed) -----------------------------------------------------------------------------------

def _model_ready():
    try:
        import sherpa_onnx  # noqa: F401
    except ImportError:
        return False
    return all((Path(ear_sherpa.default_model_dir()) / name).is_file() for name in ear_sherpa.MODEL_FILES)


needs_model = pytest.mark.skipif(not _model_ready(), reason='sherpa-onnx or the local ear model is not installed here')
DIAG = Path(__file__).resolve().parents[1] / 'echo_sync' / 'diag_audio'
PHRASES = ('channel', 'answer', 'synthesis', 'lookup_empty', 'other', 'lookup_degraded')


def _long_speech():
    """The packaged SAPI phrases one after another with nothing between them: 18 s of speech with no pause of the detector's size."""
    pcm = b''
    for name in PHRASES:
        with wave.open(str(DIAG / (name + '.wav')), 'rb') as handle:
            assert (handle.getframerate(), handle.getnchannels(), handle.getsampwidth()) == (24000, 1, 2)
            pcm += handle.readframes(handle.getnframes())
    return pcm[:len(pcm) - len(pcm) % 4800]


def _through_the_ear(pcm, **kwargs):
    engine = ear_sherpa.SherpaEngine()
    worker = ear_shadow.EarWorker(lambda: engine)
    assert worker.wait_ready(60)
    count = len(pcm) // 4800
    ear = ear_shadow.ShadowEar(worker, lambda text: ('silent', 'measure', None, None), detector=T.ScriptedDetector(['onset'] + ['speech'] * (count - 2) + ['end']),
                               hotwords=lambda: ear_sherpa.hotwords_for(None), **kwargs)
    records = []
    for i in range(count):
        ear.feed(pcm[i * 4800:(i + 1) * 4800], input_ms=100 * (i + 1))
        deadline = time.monotonic() + 30
        while ear.pending > 0 and time.monotonic() < deadline:
            time.sleep(0.001)
        records += ear.poll()
    deadline = time.monotonic() + 30
    while ear.spans and time.monotonic() < deadline:
        records += ear.poll()
        time.sleep(0.005)
    return records


@needs_model
def test_the_real_model_carried_over_the_bounds_says_what_one_stream_says(monkeypatch):
    pcm = _long_speech()
    engine = ear_sherpa.SherpaEngine()
    stream = engine.start(ear_sherpa.hotwords_for(None))
    for at in range(0, len(pcm), 4800):
        engine.accept(stream, pcm[at:at + 4800])
    whole = engine.finish(stream)
    assert len(whole.split()) >= 15, 'the model hears the phrases'
    monkeypatch.setattr(ear_shadow, 'MAX_UTTERANCE_S', 2.5)    # seven bounds in 18 s, wherever they fall
    records = _through_the_ear(pcm)
    assert len(records) >= 6
    assert ' '.join(r['text'] for r in records if r['text']) == whole, 'window by window the ear gives the very text of one stream: nothing lost at a bound'


@needs_model
def test_the_real_model_cut_at_the_bounds_does_not(monkeypatch):
    """The reason for ``carry``, on the same audio: finished and begun anew every 2.5 s the model loses or breaks words. (If a newer model ever
    hears across a cut as well as one stream does, this test may go: it only shows that the one above measures something.)"""
    pcm = _long_speech()
    engine = ear_sherpa.SherpaEngine()
    stream = engine.start(ear_sherpa.hotwords_for(None))
    for at in range(0, len(pcm), 4800):
        engine.accept(stream, pcm[at:at + 4800])
    whole = engine.finish(stream)
    monkeypatch.setattr(ear_shadow, 'MAX_UTTERANCE_S', 2.5)
    records = _through_the_ear(pcm)
    assert ' '.join(r['text'] for r in records if r['text']) != whole
