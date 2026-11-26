"""L3 (the night of 12-13 Nov): the local ear under LOAD - the recognizer cannot keep up. The only way (a dropped utterance was silent loss):

The ear falls behind by at most ``MAX_PENDING_S`` and SAYS what it lost. The window that could not be recognized has
what was recognized of it, marked ``cut = "overflow"``, and is deaf until the recognizer has caught up (the utterances before it that wait are
recognized); then the speech goes on as a new window, heard again with the whole queue before it - one window with a hole per overflow. Every
record says how much of its audio was not recognized (``lost_ms``) and how much audio waited for the recognizer (``behind_ms``).
A window that lost audio is speech nobody knows for whoever acts on the record - no ``text``, ``kind = "error"``, ``reason = "overflow"``, as a
dropped utterance was nobody's text - and the words recognized of it are written down as ``heard``.
(Before, behind the setting ``ear_overflow``, deleted: the whole rest of the utterance was dropped, with no record, and the journal said so once per call.)

The recognizer never runs twice at once, whatever the calls do: one thread owns it (pinned here; it was so before).

The recognizer and the detector are the fakes of test_l3_ear_long.py.
"""
import threading
import time

import helpers_s6_ack as H
import test_ear_shadow as T
from echo_sync import ear_shadow
from echo_sync.settings import resolve
from test_l3_ear_long import WordsRecognizer, feed, make, rest, settle, spoken, window  # noqa: F401 - ``window`` is a fixture


# --- no setting ------------------------------------------------------------------------------------------------------------------------

def test_there_is_no_setting_for_it_any_more():
    assert 'ear_overflow' not in resolve({}) and 'ear_overflow' not in resolve({'ear_overflow': 'drop'})


# --- the recognizer cannot keep up ------------------------------------------------------------------------------------------------------------

def test_live_what_was_recognized_is_written_down_the_loss_is_counted_and_the_speech_is_heard_again():
    gate = threading.Event()
    recognizer = WordsRecognizer(gate=gate)
    ear, _ = make(['onset'] + ['speech'] * 58 + ['end', 'quiet', 'onset'] + ['speech'] * 7 + ['end'], recognizer=recognizer)
    feed(ear, 1, wait=False)
    deadline = time.monotonic() + 5
    while not recognizer.active and time.monotonic() < deadline:        # the recognizer has taken the first packet and is stuck in it
        time.sleep(0.001)
    assert recognizer.active == 1
    feed(ear, 39, start=1, wait=False)        # 4 s in all: 30 packets wait (MAX_PENDING_S, the one being recognized among them), 10 do not fit
    assert ear.current == 1 and ear.poll() == [], 'the window goes on, deaf, until the recognizer has caught up'
    gate.set()
    settle(ear)
    records = rest(ear, feed(ear, 30, start=40), 3)
    first, second, third = records
    assert first['cut'] == 'overflow' and first['lost_ms'] == 3900, 'what waited of it was given up (29 packets), and what came while it waited (10)'
    assert (first['kind'], first['reason'], first['text']) == ('error', 'overflow', None), 'speech with a hole in it is speech nobody knows: no text to act on'
    assert first['heard'] == 'сл~', 'what the recognizer had taken of it is written down'
    assert (first['onset_input_ms'], first['offset_input_ms'], second['onset_input_ms']) == (100, 4100, 4100), 'it ends where the speech is heard again'
    assert (second['kind'], second['text'], second['lost_ms']) == ('silent', 'сл~ ' + spoken(40, 59), 0) and 'heard' not in second and 'cut' not in second, \
        'from the moment the recognizer had caught up every word is heard (the one being said then: its end) and judged as any other'
    assert (third['kind'], third['text'], third['lost_ms']) == ('silent', spoken(60, 69) + ' сл~', 0), 'and so is the next utterance'
    heard = sum(len(stream['tags']) for stream in recognizer.streams)
    assert sum(r['lost_ms'] for r in records) == (70 - heard) * 100 == 3900, 'every packet is either recognized or counted as lost'
    assert first['behind_ms'] == 3000 and second['behind_ms'] <= 100 and third['behind_ms'] <= 100, 'how much audio waited for the recognizer'
    assert [fields.get('state') for ev, fields in ear.test_notes if ev == 'ear_state'] == ['overflow']
    assert [(f.get('cut'), f.get('lost_ms'), f['kind'], f['text']) for ev, f in ear.test_notes if ev == 'ear_final'] == \
        [('overflow', 3900, 'error', None), (None, 0, 'silent', 'сл~ ' + spoken(40, 59)), (None, 0, 'silent', spoken(60, 69) + ' сл~')], \
        'the journal has the same records'


def test_live_what_waits_of_the_utterances_before_is_recognized_and_an_overflow_is_one_window_with_a_hole():
    """The queue is full of an utterance already over (A) when the next one (B) is being said: B gives up what waits of it and is deaf until A has
    been recognized - then it ends and the speech goes on, heard. Three records, not a row of scraps cut wherever a packet happened to fit."""
    gate = threading.Event()
    recognizer = WordsRecognizer(gate=gate)
    ear, _ = make(['onset'] + ['speech'] * 18 + ['end', 'quiet', 'onset'] + ['speech'] * 23 + ['end'], recognizer=recognizer)
    feed(ear, 36, wait=False)                 # A: packets 0-19; B from 20 (its pre-roll): 10 packets fit, the one of 30 does not, 31-35 come while A waits
    assert ear.current == 2 and ear.poll() == []
    gate.set()
    settle(ear)
    records = rest(ear, feed(ear, 10, start=36), 3)
    assert [(r['uid'], r['kind'], r['lost_ms']) for r in records] == [(1, 'silent', 0), (2, 'error', 1600), (3, 'silent', 0)]
    assert records[0]['text'] == spoken(0, 17) + ' сл~', 'the utterance that waited is recognized whole, late'
    assert records[1]['cut'] == 'overflow' and records[1]['text'] is None and records[1]['heard'] == ''
    assert records[2]['text'] == spoken(36, 45) + ' сл~', 'the rest of the speech is heard from the packet at which nothing waited any more'
    assert len(recognizer.streams) == 3


def test_live_every_overflow_of_a_call_is_in_the_journal():
    gate = threading.Event()
    recognizer = WordsRecognizer(gate=gate)
    ear, _ = make((['onset'] + ['speech'] * 33 + ['end', 'quiet']) * 2, recognizer=recognizer)
    feed(ear, 36, wait=False)
    gate.set()
    settle(ear)
    records = rest(ear, [], 1)
    gate.clear()
    feed(ear, 36, start=36, wait=False)
    gate.set()
    settle(ear)
    records = rest(ear, records, 2)
    assert [(r.get('cut'), r['kind'], r['reason']) for r in records] == [('overflow', 'error', 'overflow')] * 2
    assert all(r['lost_ms'] > 0 for r in records), 'the first time and every time after it'
    assert [fields.get('state') for ev, fields in ear.test_notes if ev == 'ear_state'] == ['overflow'], 'the state is told once, the records every time'


def test_live_with_carry_an_overflow_ends_the_stream_carried_over_a_bound_and_no_word_is_given_twice(window, monkeypatch):
    """Both settings on. A stretch goes over the window bound as one stream (L3), then the recognizer stalls. The window before
    the bound is whole and stays so; the window of the overflow has the words the stream got after those given - the one held back at the bound among
    them - and its hole; when the recognizer has caught up the speech goes on as a new stream."""
    monkeypatch.setattr(ear_shadow, 'MAX_PENDING_S', 1.0)      # 10 packets may wait: less than a window (20), so the overflow is inside the second one
    gate = threading.Event()
    gate.set()
    recognizer = WordsRecognizer(gate=gate)
    ear, _ = make(['onset'] + ['speech'] * 48 + ['end'], recognizer=recognizer)
    records = feed(ear, 23)                   # the bound comes with packet 19; the window after it has the packets 20-22 so far
    gate.clear()
    feed(ear, 1, start=23, wait=False)
    deadline = time.monotonic() + 5
    while not recognizer.active and time.monotonic() < deadline:        # the recognizer is stuck in packet 23
        time.sleep(0.001)
    assert recognizer.active == 1
    feed(ear, 14, start=24, wait=False)       # 24-32 wait behind it, 33-37 do not fit
    assert ear.current == 2
    gate.set()
    settle(ear)
    records = rest(ear, records + feed(ear, 12, start=38), 3)
    first, second, third = records
    assert (first['uid'], first['text'], first.get('more'), first['lost_ms']) == (1, spoken(0, 17), True, 0) and 'cut' not in first
    assert (second['uid'], second.get('part'), second['cut'], second['lost_ms']) == (2, 2, 'overflow', 1400)
    assert (second['kind'], second['reason'], second['text']) == ('error', 'overflow', None)
    assert second['heard'] == spoken(18, 23), 'the word held back at the bound and the one after it: what the stream had got, after the words given'
    assert (second['onset_input_ms'], second['offset_input_ms'], third['onset_input_ms']) == (2000, 3900, 3900)
    assert (third['uid'], third['kind'], third['text'], third['lost_ms']) == (3, 'silent', 'сл~ ' + spoken(38, 49) + ' сл~', 0)
    assert 'part' not in third and 'cut' not in third, 'a new stream, heard from where the recognizer had caught up'
    assert len(recognizer.streams) == 2 and all(stream['finished'] for stream in recognizer.streams)
    heard = sum(len(stream['tags']) for stream in recognizer.streams)
    assert sum(r['lost_ms'] for r in records) == (50 - heard) * 100 == 1400, 'every packet is either recognized or counted as lost'


def test_live_with_carry_a_bound_that_waits_in_the_queue_is_kept_when_the_window_after_it_overflows(window):
    """The recognizer stalls from the start: the window bound itself waits in the queue when the window after it overflows. What waits of the window
    before the bound is recognized and its words are given; the window of the overflow has only the word that was held back for it."""
    gate = threading.Event()
    recognizer = WordsRecognizer(gate=gate)
    ear, _ = make(['onset'] + ['speech'] * 44 + ['end'], recognizer=recognizer)
    feed(ear, 1, wait=False)
    deadline = time.monotonic() + 5
    while not recognizer.active and time.monotonic() < deadline:
        time.sleep(0.001)
    assert recognizer.active == 1
    feed(ear, 35, start=1, wait=False)        # the bound with packet 19; 20-29 fit, 30 does not, 31-35 come while the window before the bound waits
    assert ear.current == 2 and ear.poll() == []
    gate.set()
    settle(ear)
    records = rest(ear, feed(ear, 10, start=36), 3)
    assert [(r['uid'], r['kind'], r['lost_ms']) for r in records] == [(1, 'silent', 0), (2, 'error', 1600), (3, 'silent', 0)]
    assert records[0]['text'] == spoken(0, 17) and records[0].get('more') is True and records[0]['behind_ms'] == 2000
    assert (records[1].get('part'), records[1]['cut'], records[1]['text'], records[1]['heard']) == (2, 'overflow', None, 'сл~')
    assert records[2]['text'] == spoken(36, 45) + ' сл~' and 'part' not in records[2]
    assert len(recognizer.streams) == 2 and all(stream['finished'] for stream in recognizer.streams)


def test_live_the_ear_is_never_more_than_the_bound_behind():
    recognizer = WordsRecognizer(slow=0.02)                    # every packet costs 20 ms: fed without a pause the recognizer is far too slow
    ear, _ = make(['onset'] + ['speech'] * 198 + ['end'], recognizer=recognizer)
    peak = 0
    for i in range(200):
        ear.feed(T.packet(i % 240), input_ms=100 * (i + 1))
        peak = max(peak, ear.pending)
    settle(ear, timeout=20)
    records = rest(ear, [])
    assert peak <= ear_shadow.MAX_PENDING_S * ear_shadow.BYTES_PER_SECOND
    assert records and all(r['behind_ms'] <= ear_shadow.MAX_PENDING_S * 1000 for r in records)
    heard = sum(len(stream['tags']) for stream in recognizer.streams)
    assert sum(r['lost_ms'] for r in records) == (200 - heard) * 100, 'every packet is either recognized or counted as lost'
    assert not ear.off and not ear.spans


def test_the_recognizer_never_runs_twice_at_once_whatever_the_calls_do(window):
    recognizer = WordsRecognizer(slow=0.001)
    worker = ear_shadow.EarWorker(lambda: recognizer)
    assert worker.wait_ready(5)
    ears = [ear_shadow.ShadowEar(worker, lambda text: ('silent', 'measure', None, None), detector=T.ScriptedDetector(['onset'] + ['speech'] * 43 + ['end']),
                                 partial_ms=100) for _ in range(3)]

    def call(ear):
        for i in range(45):
            ear.feed(T.packet(i), input_ms=100 * (i + 1))
            time.sleep(0.002)
            ear.poll()
    threads = [threading.Thread(target=call, args=(ear,), daemon=True) for ear in ears]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(20)
    deadline = time.monotonic() + 10
    while any(ear.spans for ear in ears) and time.monotonic() < deadline:
        for ear in ears:
            ear.poll()
        time.sleep(0.005)
    assert recognizer.overlaps == 0, 'one thread owns the recognizer: a second call, a text so far, a window bound all wait their turn'
    assert sum(len(stream['tags']) for stream in recognizer.streams) > 0 and not any(ear.spans for ear in ears)
