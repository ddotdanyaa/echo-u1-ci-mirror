"""S5 part «ear» (packet P11-ear): the ear only produces text and features; the decision stays with the judge (M1/M2).
Stand: helpers_night_memory.Call (real ControlledMedia, NativeMediaSocket, fast_text, call journal) with the real ear (``ear_shadow.for_call`` + ``EarWorker``) as the host builds it; only the recognizer is a toy (a stream keeps the packets it got, its
text says what it holds), so every claim is about what the ear does with sound, not about a model.
  * a toy engine lands through ``warm.default_steps`` (the ear_model step) and ``for_call(worker=...)`` with no edit of the core (the matryoshka's S5 slot);
  * L3 / U92: 17.6 s of speech is one stream, its words arrive whole and once (no cut at 15 s, none torn) with no setting;
  * U27: a hole of digital zeros inside speech is not silence: the utterance is not closed early (energy and Silero engines); a hole older than ZERO_HOLD_MS is, and room noise is;
  * U76: the sound before the detector's verdict (pre-roll) is part of the utterance;
  * U19-S7: the recognizer of an utterance follows the language of its turn (``LangEngine``), the Russian one stays where no English one is."""
import base64
import logging
import math
import struct
import threading
import time

import pytest

import helpers_night_memory as N
from echo_sync import ear_shadow, ear_sherpa, local_ear, vad_silero, warm
from echo_sync.settings import resolve
from test_ear_shadow import ScriptedDetector

PER = 4                                             # packets of 100 ms per word of the long fixture
FACT = 'Перевозка контейнера до порта Находка стоит 1830 долларов.'
TAIL = 'стоит перевозка контейнера до порта Находка'
WORDS = ('вчера мы с женой разбирали антресоль нашли там старые коробки с книгами и посудой потом решили отдать часть вещей соседям и заодно перебрали ящики в гараже а ещё нашли пару лыж и санки которые давно искали весной '
         'сколько стоит перевозка контейнера до порта Находка').split()          # 44 words x 4 packets = 17.6 s; «сколько» (word 37) lies on the 15 s window bound
LIVE = {'fast_text': 'on', 'local_ear': 'act', 'conversation_ledger': 'off', 'topic_recap': 'off', 'v6_memory': 'off'}


def mind(request):
    return FACT if TAIL.split(' ', 1)[1] in N.asked(request) else 'Уточните вопрос.'


def tone(ms, amplitude=8000):
    n = 24 * ms
    return struct.pack('<%dh' % n, *(int(amplitude * math.sin(2 * math.pi * 440 * i / 24000)) for i in range(n)))


def room(ms):
    return struct.pack('<%dh' % (24 * ms), *([3, -3] * (12 * ms)))      # not digital zero: the hiss of a room


def hole(ms):
    return b'\0' * (48 * ms)


class Toy:
    """The recognizer boundary of this file. A stream is the list of the packets it got; its text: ``w<tag>`` for every distinct tag word (tag = first byte of a packet = the index of the word) when the audio is tagged, else the count of sounding packets."""
    tagged = True
    language = 'toy'

    def start(self, hotwords=None):
        self.started = getattr(self, 'started', [])
        self.started.append(hotwords)
        return []

    def accept(self, stream, pcm):
        stream.extend(pcm[at:at + 4800] for at in range(0, len(pcm), 4800))

    def peek(self, stream):
        if self.tagged:
            return ' '.join(WORDS[tag] for tag in dict.fromkeys(p[0] for p in stream))
        return 'heard %d' % sum(1 for p in stream if len(set(p)) > 8)      # the packets with a tone in them (a hole is one byte value, a room two or three)

    finish = peek


def build(tmp_path, caplog, detector, engine=None, **keys):
    caplog.set_level(logging.INFO)
    call = N.Call(tmp_path, mind, **{**LIVE, **keys})
    engine = engine or Toy()
    call.engine = engine
    worker = ear_shadow.EarWorker(lambda: engine)
    assert worker.wait_ready(5)
    call.worker = worker
    call.w.wire.ear = ear_shadow.for_call(resolve({**LIVE, **keys}), call.c, detector_factory=lambda: detector, worker=worker, report=call.trace.note, clock=call.w.clock.now)
    call.finals = lambda: [r for r in call.journal() if r['ev'] == 'ear_final']
    return call


def send(call, packets):
    for pcm in packets:
        call.w.client({'type': 'input_audio_buffer.append', 'audio': base64.b64encode(pcm).decode('ascii')})
        call.w.advance(0.1)
        deadline = time.monotonic() + 0.3
        while call.worker._jobs.qsize() and time.monotonic() < deadline:
            time.sleep(0.0005)


def settle(call, want, limit=3):
    deadline = time.monotonic() + limit
    while len(call.finals()) < want and time.monotonic() < deadline:
        call.pump(0.1, 0.1), time.sleep(0.002)
    call.pump(1.0)
    return call.finals()


def tagged(index):
    return bytes([index // PER, 1]) * 2400


def test_a_toy_engine_lands_through_the_warm_step_and_the_ear_part_without_editing_the_core(tmp_path, caplog):
    toy = Toy()
    worker = ear_shadow.EarWorker(lambda: toy)
    steps = [step for step in warm.default_steps(tmp_path, ear=lambda: worker) if step.name == 'ear_model']
    assert [r['ok'] for r in warm.run_plan(steps)] == [True], 'the ear step of the plan waits for the toy engine and passes'
    script = ['onset'] + ['speech'] * 18 + ['end']
    call = build(tmp_path, caplog, ScriptedDetector(script))
    call.w.wire.ear.worker = worker                  # the very worker the warm step warmed
    send(call, [tagged(i) for i in range(20)])
    first = settle(call, 1)[0]
    assert first['text'] == ' '.join(WORDS[:5]), 'the words of the toy engine come out of the real ear into the journal'


def test_seventeen_point_six_seconds_of_speech_reach_the_model_whole(tmp_path, caplog):
    """L3 / U92 / 1.03 through the ear part: no setting, one stream over the 15 s bound; every word once, none torn, the question whole to the model."""
    call = build(tmp_path, caplog, ScriptedDetector(['onset'] + ['speech'] * (len(WORDS) * PER - 2) + ['end']))
    send(call, [tagged(i) for i in range(len(WORDS) * PER)])
    records = settle(call, 2)
    heard = ' '.join((r.get('text') or '') for r in records).split()
    assert heard == WORDS, 'every word of the 17.6 s once, in order, none cut at 15 s'
    assert records[0].get('more') is True and records[1].get('part') == 2
    asked = [N.asked(r) for r in call.all_requests()]
    assert any(' '.join(WORDS[-6:]) in q or TAIL.split(' ', 1)[1] in q for q in asked) and FACT in [r['first'] for r in call.journal() if r['ev'] == 'fast_job']


def test_a_hole_of_zeros_inside_speech_does_not_close_the_utterance(tmp_path, caplog):
    """U27 with the energy detector: 1 s sound, 1.5 s of digital zeros (a stall someone filled), 1 s sound is ONE utterance; before, the zeros read as silence and made two."""
    toy = Toy()
    toy.tagged = False
    call = build(tmp_path, caplog, local_ear.SpeechOnset(), toy)
    send(call, [hole(100)] * 3 + [tone(100)] * 10 + [hole(100)] * 15 + [tone(100)] * 10 + [room(100)] * 8)
    records = settle(call, 1)
    assert len(records) == 1 and records[0]['text'] == 'heard 20', 'one utterance with both stretches of sound'


@pytest.mark.parametrize('gap', [pytest.param([hole(100)] * 36, id='zeros_older_than_the_hold'), pytest.param([room(100)] * 15, id='room_noise')])
def test_a_hole_longer_than_the_hold_and_room_noise_are_silence(tmp_path, caplog, gap):
    """The hold is a number: zeros older than ZERO_HOLD_MS count as silence, and a quiet room (never digital zero) always did: two utterances."""
    toy = Toy()
    toy.tagged = False
    call = build(tmp_path, caplog, local_ear.SpeechOnset(), toy)
    send(call, [hole(100)] * 3 + [tone(100)] * 10 + gap + [tone(100)] * 10 + [room(100)] * 8)
    assert len(settle(call, 2)) == 2


class SpeechModel:
    """Silero's model boundary: speech while the window has sound."""
    def window_size(self):
        return 512

    def is_speech(self, window):
        return any(abs(v) > 0.01 for v in window)

    def reset(self):
        pass


def test_a_hole_of_zeros_inside_speech_does_not_close_the_utterance_on_the_silero_engine(tmp_path, caplog):
    toy = Toy()
    toy.tagged = False
    call = build(tmp_path, caplog, vad_silero.SileroOnset(SpeechModel()), toy)
    send(call, [hole(100)] * 3 + [tone(100)] * 10 + [hole(100)] * 15 + [tone(100)] * 10 + [room(100)] * 8)
    records = settle(call, 1)
    assert len(records) == 1 and records[0]['text'] == 'heard 20'


def test_the_sound_before_the_verdict_is_part_of_the_utterance(tmp_path, caplog):
    """U76: the ring buffer. The detector is sure of a start only after the first sound; the packets before it (PREROLL_PACKETS) go to the recognizer with it."""
    toy = Toy()
    toy.tagged = False
    seen = []
    toy.accept = lambda stream, pcm: seen.append(len(pcm))
    call = build(tmp_path, caplog, local_ear.SpeechOnset(), toy)
    send(call, [room(100)] * 6 + [tone(100)] * 6 + [room(100)] * 8)
    settle(call, 1)
    assert sum(seen) >= (ear_shadow.PREROLL_PACKETS + 6) * 4800, 'the quiet packets before the start travelled with the speech'


def test_the_recognizer_of_an_utterance_follows_the_language_of_its_turn(tmp_path, caplog):
    """U19-S7: Russian turn -> the Russian recognizer; English turn -> the English one; no English one built -> the Russian ear stays and the call goes on."""
    russian, english = Toy(), Toy()
    russian.language, english.language = 'ru', 'en'
    russian.finish = lambda stream: 'русский текст'
    english.finish = lambda stream: 'english text'
    lang = ear_sherpa.LangEngine(russian, english=lambda: english)
    call = build(tmp_path, caplog, ScriptedDetector(['onset', 'speech', 'end', 'quiet', 'onset', 'speech', 'end']), lang)
    send(call, [tagged(0)] * 3)
    ru_first = settle(call, 1)[0]
    call.c.turn_lang.lang = 'en'
    send(call, [tagged(0)] * 4)
    done = settle(call, 2)
    assert [r['text'] for r in done] == ['русский текст', 'english text'] and ru_first['text'] == 'русский текст'
    assert [r['lang'] for r in done] == ['ru', 'en'], 'the journal says which ear heard the utterance'
    lone = ear_sherpa.LangEngine(russian)
    assert lone.start(ear_sherpa.Bias('', 'en'))[0] is russian, 'no English recognizer: the Russian one hears the English turn'
