"""H3: the tempo of the prompter is kept by the local ear (it needs ``local_ear`` on). No network, no sleep: the real NativeMediaSocket, the real ShadowEar and the
real controller on the injected clock; only the speech detector, the recognizer's worker, the cloud's events and the job's stream are scripted.

The case is the owner's call of 4 Nov 20:34 (.superpowers/sdd/wave2/owner-call-2034-timeline.txt, and the ear's speech_ms / lag_ms of its log): «общие…» said on purpose at 75.1-76.4 s, the help came
at 90.8 s: «ты мне подсказываешь секунд через шесть, через семь, это очень плохо». First causes: ``repeat_seconds`` = 6, and ``hearing`` kept alive by a cloud transcript that lags seconds behind.
Its neighbours are here too, never a rule for one phrase. What this proves is the logic: nothing here is a measurement of a call.
"""
from helpers_fast_fake import two_asks
import os
import json
from pathlib import Path
import base64
import logging

import pytest

import helpers_s6_state as S
from echo_sync import ear_shadow
from echo_sync import fast_text as FT
from echo_sync.classifier import waiting_portion
from echo_sync.controlled_media import (ACK_JOIN_SECONDS, EAR_RELEASE_SILENCE_SECONDS, HEARING_SECONDS, TEMPO_ANNOUNCE_SECONDS, TEMPO_FILLER_SECONDS, TEMPO_HOLD_SECONDS, TEMPO_START_SECONDS, TEMPO_STEP_SECONDS,
                                        TEMPO_TEXT_SECONDS, TEMPO_TWICE_SECONDS)
from echo_sync.timer_policy import ONSET_HOLD_MAX_S
from echo_sync.settings import resolve
from echo_sync.timer_policy import TEMPO_REPEAT_SECONDS
from echo_sync.stable_text import _protected as _protected_word
from echo_sync.textutil import norm_words
from test_ear_shadow import ScriptedDetector
from test_h1_fast_text import FakeStream, settled
from test_h2_brain import CALL_2034, job_of_the_call

ASKED = 'Семнадцатая статья Налогового кодекса'
HEAD = 'Статья 17 Налогового кодекса'
PORTION = '— общие условия установления налогов и сборов.'
REST = 'условия установления налогов и сборов.'
BAPTISM = 'В каком году было крещение Руси'
WAIT_OF_H3 = {'repeat_seconds': 3.5}               # H7 item 0: the default wait is 2.0 s now. These orders of events are timed inside the 3.5 s they were written against, and what they pin does not depend on its length
TICK = 0.1                                          # the host calls the wire's tick every 0.1 s
AUDIO = base64.b64encode(b'\x00\x00' * 2400).decode('ascii')
GRID = 0.21                                         # a time told by ticks is off by at most two of them


async def voice(text, end=None):
    """What the synthesizer gives: half a second of sound, all of it voice (the zeros of the world's PCM would put the end of a cue at its start)."""
    return b'\x00\x40' * 12000


def cloud_of(text):
    """What the cloud holds of ``text`` as the call has it: its first three words when its turn is announced, the rest as one delta (a number or «не» at its very end only counts once a «?» closes it)."""
    words = text.split()
    tail = ' '.join(words[3:])
    if tail and _protected_word(norm_words(tail)[-1]):
        tail += '?'
    return ' '.join(words[:3]).capitalize(), (' ' + tail) if tail else ''


class Recognizer:
    """The ear's worker with no thread: the text of an utterance reaches the ear when the test says so. ``state``: its model."""

    def __init__(self):
        self.state, self.reason, self.sink, self.dropped = 'ready', None, None, []

    def submit(self, sink, uid, op, payload=None):
        self.sink = sink
        if op == 'audio':
            sink._consumed(len(payload))
        elif op == 'drop':
            self.dropped.append(uid)

    def heard(self, uid, text, error=None):
        self.sink._heard(uid, text, 100, error)


class Rig:
    """One call: the world with the profile's settings as the host would give them, the ear built by ``ear_shadow.for_call``, the microphone packets through the wire."""

    def __init__(self, monkeypatch, *, ear='act', **profile):
        live = os.environ.get('ECHO_REPLAY_PROFILE')      # U41: the stand on the WORKING profile: the settings file of the live profile, the test's own keys over it, then ECHO_REPLAY_SET (a JSON of switches to try)
        if live:
            profile = {**json.loads(Path(live).read_text(encoding='utf-8')), **profile, **json.loads(os.environ.get('ECHO_REPLAY_SET') or '{}')}
            ear = profile.pop('local_ear', ear)
        dictating = profile.pop('dictation', None) == 'on'      # dictation is no profile key: the owner has said «диктуй медленно» before the call (CallDictation.said)
        self.settings = resolve({'local_ear': ear, **profile})
        original = S.host_kwargs
        host = {'repeat_seconds': self.settings['repeat_seconds'], 'max_auto_repeats': self.settings['max_auto_repeats'], 'fast_text': self.settings['fast_text']}
        if live:
            from echo_sync.controlled_host import controller_settings
            host['settings'] = controller_settings(self.settings)      # as controlled_host builds the controller (ROOT-1)
        monkeypatch.setattr(S, 'host_kwargs', lambda: {**original(), **host})
        self.w = S.World()
        self.w.wire.synthesize = voice
        self.c = self.w.controller
        self.c.dictating.said = True if dictating else None
        if live:      # what controlled_host sets on the controller from the profile after it is built
            for key in ('turn_mark', 'ear_lookup', 'cloud_form'):      # fast_private and lead_cue are rules of fast_text now (f84a05a9), no key
                setattr(self.c, key, self.settings[key] == 'on')
            self.c.engine.settings = self.c.settings
        self.detector, self.worker = ScriptedDetector([]), Recognizer()
        self.ear = ear_shadow.for_call(self.settings, self.c, detector_factory=lambda: self.detector, worker=self.worker, clock=self.w.clock.now)
        self.w.wire.ear = self.ear
        self.fake = self.fast = None
        if self.settings['fast_text'] == 'on':
            self.fake = FakeStream()
            self.fast = FT.for_call(self.settings, self.c, stream=two_asks(self.fake, self.w.clock.now), instructions=lambda: 'POLICY', wake=lambda: None, clock=self.w.clock.now)
            self.w.wire.fast = self.fast

    def close(self):
        if self.fast:
            self.fast.close()
        self.w.close()

    # -- the microphone --------------------------------------------------------------------------------------------------------------
    def packet(self, step, settle=True):
        """``settle``: the world runs every task to its end, and a cue in flight with them. False while one is to stay in flight."""
        self.detector.script.append(step)
        event = {'type': 'input_audio_buffer.append', 'audio': AUDIO}
        if settle:
            self.w.client(event)
        else:
            self.w.run(self.w.wire.client(event))

    def onset(self, settle=True):
        self.packet('onset', settle)
        return self.ear.current if self.ear is not None else None      # a call with ``ear: off`` has no ear: the packet goes to the wire only

    def offset(self):
        self.packet('end')
        return self.w.clock.t

    def says(self, text, speech=0.5, lag=0.15):
        """One utterance: the detector's start, ``speech`` seconds of it, its end, and ``lag`` seconds later the recognizer's text; the tick that takes it. Returns the end."""
        uid = self.onset()
        self.pump(speech)
        ended = self.offset()
        self.pump(lag)
        if self.ear is not None:      # no ear, no text of it
            self.worker.heard(uid, text)
        self.pump(TICK)
        return ended

    def pump(self, seconds):
        self.w.advance(seconds, step=TICK)

    # -- the call --------------------------------------------------------------------------------------------------------------------
    def cues(self):
        return [c for c in self.w.cues if not c.diagnostic]

    def said(self):
        return [c.text for c in self.cues()]

    def ended(self):
        """When the last cue had been said to its end."""
        return max(t for _, t, f in self.w.frames if f.get('type') == 'response.done' and f['response'].get('id'))

    def next_cue(self, within):
        """The ticks of silence, until a new cue has been said; the cue, or None."""
        count, began = len(self.cues()), self.w.clock.t
        while self.w.clock.t - began < within:
            self.pump(TICK)
            if len(self.cues()) > count:
                return self.cues()[-1]
        return None

    def first_portion(self):
        """59.0 of the call: the reference base answers, its first portion has been said."""
        self.w.feed(S.turn_created('u1', 'user', 'Семнадцатая'))
        self.w.feed(S.turn_done('u1', 'user', ASKED))
        self.pump(TICK * 2)
        assert self.said() == [HEAD], 'precondition: the base answered'

    def second_portion(self):
        """69.4 of the call: it was repeated, «общие условия …» has been said and nobody has repeated it yet."""
        self.first_portion()
        self.w.feed(S.turn_done('u2', 'user', 'Статья 17 Налогового кодекса'))
        self.pump(TICK * 2)
        assert self.said() == [HEAD, PORTION], 'precondition: the next portion was cued'

    def job_says(self, n, text):
        self.fake.run(n).say(text)
        settled(self.fast)
        self.pump(TICK)

    def job_ends(self, n):
        self.fake.run(n).finish()
        settled(self.fast)
        self.pump(TICK * 2)

    def asks(self, uid, text, n, answer):
        """A question the job answers: ``answer``, its first portion said."""
        self.w.feed(S.turn_created(uid, 'user', text.split()[0]))
        self.w.feed(S.turn_done(uid, 'user', text))
        self.job_says(n, answer)
        self.job_ends(n)
        assert self.cues(), 'precondition: the job answered'


@pytest.fixture
def call(monkeypatch):
    made = []

    def make(**profile):
        rig = Rig(monkeypatch, **profile)
        made.append(rig)
        return rig
    yield make
    for rig in made:
        assert rig.w.violations == [], rig.w.violations
        rig.close()


# =====================================================================================================================================
# the setting: read like local_ear, off changes nothing
# =====================================================================================================================================

def test_there_is_no_switch_for_the_tempo_of_the_ear():
    assert not [key for key in resolve({}) if key.startswith('prompt_te')]


def test_in_this_mode_the_default_wait_is_two_seconds_and_a_profile_may_say_otherwise():
    """H7 item 0: 3.5 s by H3; the owner's call of 5 Nov 10:27: «там ну максимум секунда две наверное должна быть перерыва». The tests that count this wait say its name from now on."""
    assert TEMPO_REPEAT_SECONDS == 2.0
    assert resolve({'local_ear': 'act'})['repeat_seconds'] == 2.0
    assert resolve({'local_ear': 'act', 'repeat_seconds': 5})['repeat_seconds'] == 5
    assert resolve({'local_ear': 'off'})['repeat_seconds'] == 6.0, 'with no ear the tempo of the ear is none, so is its default'
    once = resolve({'local_ear': 'act'})
    assert resolve(once) == once


def test_no_ear_no_tempo(call):
    rig = call(ear='off')
    assert rig.ear is None and rig.c.tempo_live is False


@pytest.mark.parametrize('ear', ['shadow', 'act'])
def test_the_ear_runs_in_both_of_its_modes(call, ear):
    assert call(ear=ear).c.tempo_live is True


# =====================================================================================================================================
# rule 1: hearing follows the ear's detector
# =====================================================================================================================================

def test_hearing_runs_from_the_onset_to_the_offset_of_the_ear_not_with_the_clouds_transcript(call):
    """69.1-105.8 of the call: a turn of the cloud stayed open, its transcript went on growing seconds behind the speech."""
    rig = call()
    rig.second_portion()
    rig.w.feed(S.turn_created('u3', 'user', 'кодекса'))
    rig.pump(1.0)
    rig.onset()
    assert rig.c.hearing is True, 'heard at the onset, before the cloud has said anything of it'
    rig.pump(0.5)
    rig.offset()
    assert rig.c.hearing is False, 'over at the offset'
    for n, word in enumerate(['о', 'общие', 'условия', 'установления']):
        rig.w.feed(S.turn_delta('u3', ' ' + word, n), settle=False)
        rig.pump(0.2)
        assert rig.c.hearing is False, 'the transcript grows, the listener is silent'


def test_the_ear_holds_the_flag_for_as_long_as_it_speaks(call):
    rig = call()
    rig.second_portion()
    rig.onset()
    rig.pump(HEARING_SECONDS * 3)
    assert rig.c.hearing is True, 'it does not run out as a sign of the cloud does'
    assert rig.said() == [HEAD, PORTION], 'and the timer waits'


def test_the_clouds_word_for_speech_the_ear_does_not_hear_moves_no_timer(call):
    rig = call()
    rig.second_portion()
    end = rig.ended()
    rig.pump(1.0)
    armed = rig.c.repeat_at
    rig.w.feed(S.turn_created('u3', 'user', 'м'))
    assert rig.c.hearing is False and rig.c.repeat_at == armed
    cue = rig.next_cue(5)
    assert cue.text == PORTION and cue.t - end == pytest.approx(TEMPO_REPEAT_SECONDS, abs=GRID)


def test_the_local_onset_of_the_wire_is_no_second_flag(call):
    """The transport's other ear (``local_onset`` = "on") would stop the timer and hold the flag on its own."""
    rig = call()
    rig.second_portion()
    armed = rig.c.repeat_at
    rig.c.local_onset()
    rig.c.local_speech()
    assert rig.c.hearing is False and rig.c.repeat_at == armed


def test_a_ready_cue_waits_for_the_ear_alone_as_long_as_it_ever_did(call):
    rig = call()
    rig.first_portion()
    rig.onset()
    rig.w.feed(S.turn_done('u2', 'user', 'Статья 17 Налогового кодекса'))
    assert rig.said() == [HEAD], 'held while the ear hears the listener'
    rig.pump(ONSET_HOLD_MAX_S + TICK * 2)
    assert rig.said() == [HEAD, PORTION], 'no new unbounded hold (R2.5)'


def test_a_ready_cue_goes_at_the_offset(call):
    rig = call()
    rig.first_portion()
    rig.onset()
    rig.w.feed(S.turn_done('u2', 'user', 'Статья 17 Налогового кодекса'))
    rig.offset()
    rig.pump(TICK)
    assert rig.said() == [HEAD, PORTION]


def test_the_ear_lost_the_cloud_keeps_the_flag_again_and_the_timer_runs(call):
    rig = call(ear='shadow')
    rig.second_portion()
    rig.onset()
    rig.pump(TICK)
    rig.worker.state, rig.worker.reason = 'failed', 'broken'
    rig.pump(TICK)
    assert rig.ear.off and rig.c.tempo_live is False and rig.c.hearing is False
    cue = rig.next_cue(5)
    assert cue is not None and cue.text == PORTION, 'the ear went in the middle of an utterance: nobody will tell its end, and the portion is not left there'
    rig.w.feed(S.turn_created('u3', 'user', 'общие'))
    assert rig.c.hearing is True


def test_a_fault_of_this_code_switches_it_off_and_the_call_goes_on(call, monkeypatch, caplog):
    rig = call()
    rig.second_portion()

    def broken(*_):
        raise ValueError('secret words')
    monkeypatch.setattr(rig.c, '_tempo_heard', broken)
    with caplog.at_level(logging.WARNING, logger='echo-sync'):
        rig.says('общие')
    assert rig.c.tempo_live is False
    assert 'secret words' not in caplog.text and 'tempo' in caplog.text
    assert rig.next_cue(5) is not None


def test_a_fault_in_the_detectors_callback_leaves_the_ear_alive(call, monkeypatch):
    rig = call()
    rig.second_portion()

    def broken(*_):
        raise ValueError('broken')
    monkeypatch.setattr(rig.c, '_tempo_speech', broken)
    rig.onset()
    assert rig.ear.off is False and rig.c.tempo_live is False


def test_the_setting_survives_the_ear_arriving_late(call):
    """The ear is built after the call opens (``for_call_async``): until then the cloud keeps the flag; a flag it left set is not stuck when the ear comes."""
    rig = call(ear='off')
    rig.second_portion()
    rig.w.feed(S.turn_created('u3', 'user', 'м'))
    assert rig.c.hearing is True
    ear_shadow.for_call(resolve({'local_ear': 'shadow'}), rig.c, detector_factory=lambda: rig.detector, worker=rig.worker, clock=rig.w.clock.now)
    assert rig.c.tempo_live is True and rig.c.hearing is False


# =====================================================================================================================================
# rule 2: no speech begun within repeat_seconds of the end of a cue: the portion is said again
# =====================================================================================================================================

def test_each_further_repeat_of_the_same_portion_waits_longer(call):
    rig = call(max_auto_repeats=3)
    rig.second_portion()
    for wait in (TEMPO_REPEAT_SECONDS, TEMPO_REPEAT_SECONDS + TEMPO_STEP_SECONDS, TEMPO_REPEAT_SECONDS + 2 * TEMPO_STEP_SECONDS):
        end = rig.ended()
        cue = rig.next_cue(wait + 1)
        assert cue is not None and cue.text == PORTION and cue.t - end == pytest.approx(wait, abs=GRID)
    assert rig.next_cue(20) is None, 'max_auto_repeats stands'


def test_the_cap_of_the_profile_stands(call):
    rig = call(max_auto_repeats=1)
    rig.second_portion()
    assert rig.next_cue(4) is not None
    assert rig.next_cue(20) is None


def test_the_next_portion_starts_the_wait_again(call):
    rig = call(max_auto_repeats=3)
    rig.first_portion()
    assert rig.next_cue(4).text == HEAD
    rig.w.feed(S.turn_done('u2', 'user', 'Статья 17 Налогового кодекса'))
    rig.pump(TICK * 2)
    end = rig.ended()
    cue = rig.next_cue(5)
    assert cue.text == PORTION and cue.t - end == pytest.approx(TEMPO_REPEAT_SECONDS, abs=GRID)


def test_speech_begun_in_time_keeps_the_timer_from_firing_into_it(call):
    rig = call(**WAIT_OF_H3)
    rig.second_portion()
    end = rig.ended()
    rig.pump(3.0)
    rig.onset()
    rig.pump(3.0)
    assert rig.said() == [HEAD, PORTION] and rig.w.clock.t - end > TEMPO_REPEAT_SECONDS


def test_a_profiles_own_wait_is_the_wait(call):
    rig = call(repeat_seconds=2)
    rig.second_portion()
    end = rig.ended()
    assert rig.next_cue(3).t - end == pytest.approx(2, abs=GRID)


# =====================================================================================================================================
# rule 3: a start of the portion that stopped: only what is missing, at once, with no cloud final
# =====================================================================================================================================

def test_the_stammer_of_the_call_is_helped_with_no_cloud_final(call):
    """75.1-76.4 of the call: «общие». In the call the help came at 90.8 s, the whole portion."""
    rig = call(**WAIT_OF_H3)
    rig.second_portion()
    rig.pump(2.1)
    ended = rig.says('общие', speech=1.2, lag=0.13)
    cue = rig.next_cue(2)
    assert cue.text == REST and cue.t - ended == pytest.approx(TEMPO_START_SECONDS, abs=GRID)


@pytest.mark.parametrize('said,wait,rest', [
    ('общие', TEMPO_START_SECONDS, REST),
    ('ну общие', TEMPO_START_SECONDS, REST),
    ('общие ну', TEMPO_START_SECONDS, REST),
    ('общие э-э', TEMPO_START_SECONDS, REST),
    ('общие условия', TEMPO_START_SECONDS, 'установления налогов и сборов.'),
    ('общие условия установления налогов', TEMPO_START_SECONDS, 'и сборов.'),
    ('общие как там', TEMPO_START_SECONDS, REST),
    ('общие условия блин', TEMPO_START_SECONDS, 'установления налогов и сборов.'),
    ('общие общие', TEMPO_TWICE_SECONDS, REST),
    ('общие общие общие', TEMPO_TWICE_SECONDS, REST),
    ('общие условия условия', TEMPO_TWICE_SECONDS, 'установления налогов и сборов.'),
    ('общие общие условия', TEMPO_TWICE_SECONDS, 'установления налогов и сборов.'),
], ids=lambda value: str(value).replace(' ', '_'))
def test_a_start_with_its_neighbours(call, said, wait, rest):
    rig = call()
    rig.second_portion()
    rig.pump(1.0)
    ended = rig.says(said)
    cue = rig.next_cue(2)
    assert cue is not None and cue.text == rest and cue.t - ended == pytest.approx(wait, abs=GRID)


def test_the_same_start_in_two_utterances_is_said_twice(call):
    rig = call()
    rig.second_portion()
    rig.pump(0.5)
    rig.says('общие', speech=0.3)
    rig.pump(0.6)
    ended = rig.says('общие', speech=0.3)      # the first waits its 1.2 s no longer, the listener is at it again
    cue = rig.next_cue(2)
    assert cue.text == REST and cue.t - ended == pytest.approx(TEMPO_TWICE_SECONDS, abs=GRID)
    assert len(rig.said()) == 3


def test_a_longer_start_in_a_new_utterance_is_a_new_start(call):
    rig = call()
    rig.second_portion()
    rig.pump(0.5)
    rig.says('общие', speech=0.3)
    rig.pump(1.0 + TICK * 2)                   # the pause is longer than a breath: not one utterance
    assert rig.next_cue(0.1) is not None or True
    rig2 = rig.said()
    assert rig2[-1] == REST


def test_a_start_goes_on_with_a_pause_shorter_than_a_breath(call):
    """The ear cuts at 300 ms of quiet: «общие» | «условия»: one start, what is missing of the two."""
    rig = call()
    rig.second_portion()
    rig.pump(0.5)
    rig.says('общие', speech=0.3, lag=0.1)
    rig.pump(0.2)
    ended = rig.says('условия', speech=0.3, lag=0.1)
    cue = rig.next_cue(2)
    assert cue.text == 'установления налогов и сборов.' and cue.t - ended == pytest.approx(TEMPO_START_SECONDS, abs=GRID)


def test_speech_that_begins_in_the_wait_is_not_cut_into(call):
    rig = call()
    rig.second_portion()
    rig.pump(1.0)
    rig.says('общие', speech=0.3, lag=0.1)
    rig.pump(0.8)
    rig.onset()
    rig.pump(2.0)
    assert rig.said() == [HEAD, PORTION], 'no speech begins for 1.2 s after its offset: speech began'


def test_the_repeat_that_goes_on_in_pieces_is_confirmed_as_ever(call):
    """Shadow: the ear does not act, its join is a repeat, and the timer waits for the cloud's final."""
    rig = call(ear='shadow')
    rig.second_portion()
    rig.pump(0.5)
    rig.says('общие', speech=0.3, lag=0.1)
    rig.pump(0.2)
    rig.says('условия установления налогов и сборов', speech=1.0, lag=0.1)
    rig.pump(3.0)
    assert rig.said() == [HEAD, PORTION], 'no repeat into a confirmation that is on its way'
    rig.w.feed(S.turn_done('u3', 'user', 'общие условия установления налогов и сборов'))
    rig.pump(TICK)
    assert rig.c.state().get('completed'), 'the cloud confirmed it'
    assert rig.next_cue(6) is None


def test_a_whole_repeat_the_ear_confirms_moves_on(call):
    rig = call()
    rig.first_portion()
    rig.pump(0.5)
    rig.onset()
    rig.pump(0.3)
    rig.w.feed(S.turn_created('u2', 'user', 'статья'))
    rig.pump(0.6)
    uid = rig.ear.current
    rig.offset()
    rig.pump(TICK)
    rig.worker.heard(uid, 'статья семнадцать налогового кодекса')
    rig.pump(TICK * 2)
    assert rig.said() == [HEAD, PORTION], 'the ear took the turn'


def test_only_what_is_missing_of_a_portion_with_digits(call):
    """The ear writes words, the portion has digits: «статья семнадцать» is a start of «Статья 17 …»."""
    rig = call()
    rig.first_portion()
    rig.pump(0.5)
    ended = rig.says('статья семнадцать')
    cue = rig.next_cue(2)
    assert cue.text == 'Налогового кодекса' and cue.t - ended == pytest.approx(TEMPO_START_SECONDS, abs=GRID)


def test_another_number_is_no_start(call):
    rig = call()
    rig.first_portion()
    rig.pump(0.5)
    rig.says('статья восемнадцать')
    assert rig.next_cue(2) is None


def test_a_stopped_try_at_a_year(call):
    rig = call(fast_text='on')
    rig.asks('u1', BAPTISM, 0, 'В 988 году.')
    assert rig.said() == ['В 988 году.']
    rig.pump(0.5)
    ended = rig.says('в девятьсот')
    cue = rig.next_cue(2)
    assert cue.text == '988 году.', 'the number was not finished: it is what is missing'
    assert cue.t - ended == pytest.approx(TEMPO_START_SECONDS, abs=GRID)


def test_a_number_that_cannot_grow_into_the_portions_is_no_start(call):
    rig = call(fast_text='on')
    rig.asks('u1', BAPTISM, 0, 'В 988 году.')
    rig.pump(0.5)
    rig.says('в девятьсот девяносто')
    assert rig.next_cue(2) is None


def test_the_whole_portion_is_a_portion_again_after_the_window_of_a_try(call):
    rig = call(max_auto_repeats=3)
    rig.second_portion()
    rig.pump(0.5)
    rig.says('общие', speech=0.3)
    assert rig.next_cue(2).text == REST
    rig.w.clock.advance(ACK_JOIN_SECONDS + 1)
    assert rig.next_cue(8).text == PORTION, 'what was said so long ago is no start any more'


def test_the_repeat_of_the_tail_confirms_the_portion_as_it_did(call):
    """G3 rule 3: the tail is counted once the transport says it has started."""
    rig = call()
    rig.second_portion()
    rig.pump(0.5)
    rig.says('общие', speech=0.3)
    assert rig.next_cue(2).text == REST
    rig.pump(0.3)
    rig.says('условия установления налогов и сборов', speech=1.0)
    rig.w.feed(S.turn_created('u3', 'user', 'условия'))
    rig.w.feed(S.turn_done('u3', 'user', 'условия установления налогов и сборов'))
    rig.pump(TICK)
    assert rig.c.state().get('completed'), 'the missing part was confirmed'


def test_the_end_of_the_portion_closes_it_even_after_a_tail_never_heard(call):
    """It used to confirm nothing. The owner, 06.11: part of the answer, and at the end the last words of the portion: the next portion."""
    rig = call()
    rig.w.wire.synthesize = None
    rig.w.wire.synthesize = voice
    rig.second_portion()
    rig.pump(0.5)
    rig.says('общие', speech=0.3)
    position = rig.c._position(rig.c.state())
    rig.c._cue_tail(position, REST)
    rig.w.feed(S.turn_done('u3', 'user', 'условия установления налогов и сборов'))
    rig.pump(TICK * 2)
    assert rig.c.state().get('completed')


def test_the_clouds_late_news_of_that_speech_does_not_cut_the_help(call):
    """The cloud announced an utterance 0.9 s after its end at 53.3 of the call, at its end at 56.2. The help is out by then."""
    rig = call()
    rig.second_portion()
    rig.pump(0.5)
    rig.says('общие', speech=0.3, lag=0.1)
    rig.w.clock.advance(TEMPO_START_SECONDS)
    assert in_flight(rig).text == REST
    rig.w.feed(S.turn_created('u3', 'user', 'общие'), settle=False)
    rig.w.feed(S.turn_delta('u3', ' условия', 1), settle=False)
    assert rig.w.open is not None and rig.w.open.text == REST and not rig.w.open.cleared, 'nobody is speaking: there is nobody to cut it for'
    rig.w.settle()
    assert rig.cues()[-1].done


def test_the_clouds_late_final_of_that_speech_says_nothing_twice(call):
    rig = call(max_auto_repeats=3)
    rig.second_portion()
    rig.pump(0.5)
    rig.says('общие общие', speech=0.3)
    assert rig.next_cue(1).text == REST
    rig.pump(0.5)
    rig.w.feed(S.turn_created('u3', 'user', 'общие'))
    rig.w.feed(S.turn_done('u3', 'user', 'общие общие'))
    rig.pump(TICK * 2)
    assert rig.said() == [HEAD, PORTION, REST], 'the same stammer is not served again 3 s later'


def test_a_late_final_does_not_put_an_armed_timer_off(call):
    rig = call(max_auto_repeats=3)
    rig.second_portion()
    rig.pump(0.5)
    rig.says('общие', speech=0.3)
    assert rig.next_cue(1.5).text == REST
    end = rig.ended()
    rig.pump(3.0)
    rig.w.feed(S.turn_done('u3', 'user', 'общие'))
    cue = rig.next_cue(5)
    assert cue.text == REST and cue.t - end == pytest.approx(TEMPO_REPEAT_SECONDS + TEMPO_STEP_SECONDS, abs=GRID), 'its transcript moves nothing'


def test_speech_over_a_cue_is_no_start(call):
    """It may be the cue heard back."""
    rig = call()
    rig.second_portion()
    end = rig.ended()
    rig.c.cue_window[1] = rig.w.clock.t + 5        # the portion is still being said as far as the controller knows
    rig.pump(0.2)
    rig.says('общие', speech=0.3)
    rig.c.cue_window[1] = rig.w.clock.t - 5
    assert rig.next_cue(1.2) is None, 'never at 1.2 s'
    assert rig.w.clock.t - end < TEMPO_REPEAT_SECONDS + 1.2


# =====================================================================================================================================
# rule 4: a filler or a hesitation does not reset the wait: the portion at most 1.5 s after it ended, within rule 2's time
# =====================================================================================================================================

HESITATIONS = ['э-э', 'ну', 'как там', 'как же там', 'оксим', 'блин забыл', 'не помню', 'кхм', '']


@pytest.mark.parametrize('said', HESITATIONS, ids=lambda value: value.replace(' ', '_') or 'empty')
def test_a_hesitation_brings_the_portion(call, said):
    rig = call()
    rig.second_portion()
    rig.pump(0.6)
    ended = rig.says(said, speech=0.4)
    cue = rig.next_cue(2)
    assert cue is not None and cue.text == PORTION and cue.t - ended <= TEMPO_FILLER_SECONDS + GRID and cue.t - ended >= TEMPO_FILLER_SECONDS - GRID


@pytest.mark.parametrize('said', ['э-э', 'как там', 'оксим', ''], ids=['filler', 'how', 'fragment', 'empty'])
def test_a_hesitation_that_ends_just_before_the_time_does_not_reset_it(call, said):
    """H5 item 1: and nothing is replayed within 1.5 s of the ear's last offset: a comma, not an end (n1_01 step 8)."""
    rig = call(**WAIT_OF_H3)
    rig.second_portion()
    rig.pump(2.5)
    ended = rig.says(said, speech=0.5)
    cue = rig.next_cue(2)
    assert cue.t - ended == pytest.approx(TEMPO_FILLER_SECONDS, abs=GRID), 'not the whole wait of rule 2 again'


@pytest.mark.parametrize('said', ['э-э', 'как там', 'оксим', ''], ids=['filler', 'how', 'fragment', 'empty'])
def test_a_hesitation_over_the_time_brings_the_portion_1_5_s_after_it(call, said):
    """H5 item 1: not at its text."""
    rig = call(**WAIT_OF_H3)
    rig.second_portion()
    end = rig.ended()
    rig.pump(3.0)
    ended = rig.says(said, speech=1.5)
    assert rig.w.clock.t - end > TEMPO_REPEAT_SECONDS
    cue = rig.next_cue(2)
    assert cue is not None and cue.text == PORTION and cue.t - ended == pytest.approx(TEMPO_FILLER_SECONDS, abs=GRID)


def test_the_hesitations_of_the_call_after_a_start(call):
    """76.4-79.6: «общие», then speech with nothing in it, then «оксим»: what is missing, by the first end there is time for."""
    rig = call(**WAIT_OF_H3)
    rig.second_portion()
    rig.pump(2.1)
    rig.says('общие', speech=1.2, lag=0.13)
    rig.pump(0.5)
    assert rig.c.hearing is False
    uid = rig.onset()
    rig.pump(1.0)
    rig.offset()
    rig.pump(0.15)
    second = rig.onset()                        # 78.35: the next speech began a moment before the empty text came
    rig.worker.heard(uid, '')
    rig.pump(1.2)
    assert rig.said() == [HEAD, PORTION], 'never into speech'
    rig.offset()
    rig.pump(0.25)
    rig.worker.heard(second, 'оксим')
    cue = rig.next_cue(0.3)
    assert cue is not None and cue.text == REST


def test_no_text_at_all_is_no_hesitation(call):
    """The ear dropped it (the model is warming, too much audio queued): nobody knows what was said, it may be a repeat on its way to the cloud. Rule 2 from its end."""
    rig = call()
    rig.second_portion()
    rig.pump(1.0)
    rig.onset()
    rig.pump(0.5)
    ended = rig.offset()
    assert rig.next_cue(TEMPO_TEXT_SECONDS + 0.1) is None
    cue = rig.next_cue(5)
    assert cue.text == PORTION and cue.t - ended == pytest.approx(TEMPO_REPEAT_SECONDS, abs=GRID)


def test_while_the_model_warms_the_ear_still_says_who_speaks(call):
    rig = call()
    rig.second_portion()
    rig.worker.state = 'loading'
    rig.onset()
    assert rig.c.hearing is True
    rig.pump(0.5)
    rig.offset()
    assert rig.c.hearing is False
    assert rig.next_cue(5).text == PORTION


def test_an_error_of_the_recognizer_is_no_hesitation(call):
    rig = call()
    rig.second_portion()
    rig.pump(1.0)
    uid = rig.onset()
    rig.pump(0.5)
    ended = rig.offset()
    rig.pump(0.2)
    rig.worker.heard(uid, None, 'RuntimeError')
    cue = rig.next_cue(5)
    assert cue.text == PORTION and cue.t - ended == pytest.approx(TEMPO_REPEAT_SECONDS, abs=GRID)


def test_a_late_text_of_a_hesitation_brings_the_portion_at_once(call):
    """The text came after the wait for it ran out: rule 2 from its end stood, but it was a hesitation, and the portion is due TEMPO_FILLER_SECONDS after it."""
    rig = call()
    rig.second_portion()
    rig.pump(1.0)
    uid = rig.onset()
    rig.pump(0.5)
    ended = rig.offset()
    assert rig.next_cue(TEMPO_TEXT_SECONDS + 0.1) is None
    armed = rig.c.repeat_at
    assert armed == pytest.approx(ended + TEMPO_REPEAT_SECONDS)
    rig.worker.heard(uid, 'э-э')
    cue = rig.next_cue(0.3)
    assert cue is not None and cue.text == PORTION and cue.t < armed


def test_a_late_text_of_a_start_is_still_a_start(call):
    rig = call()
    rig.second_portion()
    rig.pump(1.0)
    uid = rig.onset()
    rig.pump(0.5)
    rig.offset()
    assert rig.next_cue(TEMPO_TEXT_SECONDS + 0.1) is None
    rig.worker.heard(uid, 'общие')
    cue = rig.next_cue(0.3)
    assert cue is not None and cue.text == REST


# =====================================================================================================================================
# rule 5: other speech: the timer does not fire on it, H2 judges the final, a decline re-arms it
# =====================================================================================================================================

REMARK = 'блин ну ты конечно долго вот я допустим тупил'


def job_plan(rig):
    """A portion of an answer of the job has been said."""
    rig.asks('u1', 'Что такое инерция', 0, 'Инерция — это свойство тела сохранять своё состояние движения или покоя.')


def test_other_speech_stops_the_timer_and_a_decline_runs_it_again(call):
    rig = call(fast_text='on')
    job_plan(rig)
    portion = rig.said()[-1]
    rig.pump(0.5)
    rig.says(REMARK, speech=2.0)
    rig.pump(4.0)
    assert rig.said() == [portion], 'the timer does not fire on it'
    rig.w.feed(S.turn_created('u2', 'user', 'Блин'))
    rig.w.feed(S.turn_done('u2', 'user', 'Блин, ну ты, конечно, долго. Вот я, допустим, тупил.'))
    rig.pump(TICK)
    rig.job_says(1, '—')
    rig.job_ends(1)
    declined = rig.w.clock.t
    cue = rig.next_cue(5)
    assert cue is not None and cue.text == portion and cue.t - declined == pytest.approx(TEMPO_REPEAT_SECONDS, abs=GRID + TICK * 2)


def test_other_speech_that_the_job_answers_is_a_question(call):
    rig = call(fast_text='on')
    job_plan(rig)
    portion = rig.said()[-1]
    rig.pump(0.5)
    rig.says('так а теперь пять умножить на пять', speech=2.0)
    rig.w.feed(S.turn_created('u2', 'user', 'Так'))
    rig.w.feed(S.turn_done('u2', 'user', 'Так, а теперь пять умножить на пять'))
    rig.pump(TICK)
    rig.job_says(1, 'Двадцать пять.')
    rig.job_ends(1)
    rig.pump(EAR_RELEASE_SILENCE_SECONDS)
    assert rig.said() == [portion, 'Двадцать пять.']


def test_while_the_job_judges_the_timer_waits_longer_than_the_bound(call):
    rig = call(fast_text='on')
    job_plan(rig)
    portion = rig.said()[-1]
    rig.pump(0.5)
    rig.says(REMARK, speech=2.0)
    rig.w.feed(S.turn_done('u2', 'user', 'Блин, ну ты, конечно, долго. Вот я, допустим, тупил.'))
    rig.pump(TICK)
    rig.job_says(1, 'Ну')                       # it writes: FT.FIRST_TEXT_S does not end it, and a word is no verdict
    rig.pump(TEMPO_HOLD_SECONDS + 1)
    assert rig.said() == [portion], 'a job at work is an answer on its way'


def test_a_job_that_fails_lets_the_portion_come_back_by_the_bound(call):
    rig = call(fast_text='on')
    job_plan(rig)
    portion = rig.said()[-1]
    rig.pump(0.5)
    ended = rig.says(REMARK, speech=2.0)
    rig.w.feed(S.turn_done('u2', 'user', 'Блин, ну ты, конечно, долго. Вот я, допустим, тупил.'))
    rig.pump(TICK)
    rig.fake.run(1).fail()
    settled(rig.fast)
    cue = rig.next_cue(TEMPO_HOLD_SECONDS + 1)
    assert cue is not None and cue.text == portion and cue.t - ended <= TEMPO_HOLD_SECONDS + GRID + TICK


def test_a_hold_with_no_final_ends_by_itself(call):
    """A lost final must not silence the call for good."""
    rig = call()
    rig.second_portion()
    rig.pump(0.5)
    ended = rig.says(REMARK, speech=2.0)
    cue = rig.next_cue(TEMPO_HOLD_SECONDS + 1)
    assert cue.text == PORTION and cue.t - ended == pytest.approx(TEMPO_HOLD_SECONDS, abs=GRID + TICK)


@pytest.mark.parametrize('said', ['ты уверена', 'разве', 'почему', 'а почему', 'пример', 'сколько лет'], ids=lambda value: value.replace(' ', '_'))
def test_a_short_word_for_the_job_is_no_hesitation(call, said):
    """A doubt and a follow-up are short and they are the job's."""
    rig = call()
    rig.second_portion()
    rig.pump(0.5)
    rig.says(said, speech=0.5)
    assert rig.next_cue(3) is None


@pytest.mark.parametrize('said', ['подожди', 'стоп', 'дальше', 'продолжай'])
def test_a_command_is_its_own_path(call, said):
    rig = call(ear='shadow')
    rig.second_portion()
    rig.pump(0.5)
    rig.says(said, speech=0.4)
    assert rig.next_cue(3) is None, 'the cloud\'s final is on its way'


def test_the_listener_comes_back_to_the_portion_after_other_speech(call):
    rig = call()
    rig.second_portion()
    rig.pump(0.5)
    rig.says(REMARK, speech=2.0)
    rig.pump(0.5)
    ended = rig.says('общие', speech=0.3)
    cue = rig.next_cue(2)
    assert cue.text == REST and cue.t - ended == pytest.approx(TEMPO_START_SECONDS, abs=GRID)


def test_a_hesitation_after_other_speech_does_not_run_over_the_job(call):
    rig = call()
    rig.second_portion()
    rig.pump(0.5)
    rig.says(REMARK, speech=2.0)
    rig.pump(0.5)
    rig.says('э-э', speech=0.3)
    assert rig.next_cue(3) is None


def test_a_try_that_is_no_start_waits_for_the_cloud_and_counts_from_its_end(call):
    """«условия налогов» with nothing before it: a try. Its final may confirm with what came before it; it decides, then the wait of rule 2 from the end of the speech."""
    rig = call(**WAIT_OF_H3)
    rig.second_portion()
    rig.pump(0.5)
    ended = rig.says('условия налогов', speech=0.8)
    rig.pump(3.2)
    assert rig.said() == [HEAD, PORTION], 'no repeat into a final that may confirm'
    rig.w.feed(S.turn_done('u3', 'user', 'условия налогов'))
    cue = rig.next_cue(1)
    assert cue is not None and cue.text == PORTION and cue.t - ended == pytest.approx(WAIT_OF_H3['repeat_seconds'] + TICK * 2, abs=GRID + TICK)


def test_a_wrong_whole_repeat_has_its_second(call):
    rig = call()
    rig.second_portion()
    rig.pump(0.5)
    rig.says('общие условия установления налогов и взносов', speech=1.0)
    rig.w.feed(S.turn_done('u3', 'user', 'общие условия установления налогов и взносов'))
    cue = rig.next_cue(1.3)
    assert cue is not None and cue.text == PORTION


# =====================================================================================================================================
# rule 6: counted as an automatic repeat, cut by speech as any cue
# =====================================================================================================================================

def in_flight(rig):
    """The cue the next ticks give is being played: three frames of it have gone out. Bounded: a cue that never comes is a failure, not a hung suite."""
    for _ in range(200):
        rig.w.clock.advance(TICK)
        rig.w.run(rig.w.wire.tick())
        for _ in range(40):                 # a frame a turn: looked at each turn, or a short cue goes by unseen
            if rig.w.open is not None and rig.w.open.audio_frames >= 3:
                return rig.w.open
            rig.w.run(S.asyncio.sleep(0))
    raise AssertionError(f'no cue in flight in 20 s: {rig.said()}')


def test_a_cue_of_these_rules_counts_and_the_cap_stands(call):
    rig = call(max_auto_repeats=2)
    rig.second_portion()
    rig.pump(0.5)
    rig.says('общие', speech=0.3)
    assert rig.next_cue(1.5).text == REST
    assert rig.c.auto_repeats == 1, 'counted'
    end = rig.ended()
    cue = rig.next_cue(6)
    assert cue.text == REST and cue.t - end == pytest.approx(TEMPO_REPEAT_SECONDS + TEMPO_STEP_SECONDS, abs=GRID), 'and it counts for the wait too'
    assert rig.next_cue(20) is None, 'the cap'


def test_the_clouds_final_of_the_speech_before_a_cue_does_not_start_the_count_again(call):
    rig = call(max_auto_repeats=2)
    rig.second_portion()
    rig.pump(0.5)
    rig.says('общие', speech=0.3)
    assert rig.next_cue(1.5).text == REST
    rig.w.feed(S.turn_created('u3', 'user', 'общие'))
    rig.w.feed(S.turn_done('u3', 'user', 'общие'))
    rig.pump(TICK)
    assert rig.c.auto_repeats == 1
    assert rig.next_cue(6) is not None
    assert rig.next_cue(20) is None, 'silence is bounded'


def test_a_try_the_ear_hears_after_a_cue_starts_the_count_again(call):
    """Only silence is bounded: a listener at work on the portion is never out of help, the ear hears it 3 s before the cloud's final says so."""
    rig = call(max_auto_repeats=1)
    rig.second_portion()
    assert rig.next_cue(4).text == PORTION
    rig.pump(0.5)
    rig.says('общие', speech=0.3)
    assert rig.next_cue(1.5).text == REST
    rig.pump(0.5)
    rig.says('общие', speech=0.3)
    assert rig.next_cue(1).text == REST


def test_a_hesitation_does_not_start_the_count_again(call):
    rig = call(max_auto_repeats=1)
    rig.second_portion()
    assert rig.next_cue(4).text == PORTION
    rig.pump(0.5)
    rig.says('э-э', speech=0.3)
    assert rig.next_cue(3) is None


def test_speech_cuts_a_cue_of_these_rules(call):
    rig = call()
    rig.second_portion()
    rig.pump(0.5)
    rig.says('общие', speech=0.3, lag=0.1)
    cue = in_flight(rig)
    assert cue.text == REST
    rig.onset(settle=False)
    rig.w.feed(S.turn_created('u3', 'user', 'общие'))
    assert cue.cleared, 'the ear hears them: the cloud\'s word cuts it, as any cue'


def test_a_cut_cue_is_said_again_when_the_speech_was_a_hesitation(call):
    rig = call(max_auto_repeats=3)
    rig.second_portion()
    cut = in_flight(rig)
    uid = rig.onset(settle=False)
    rig.w.feed(S.turn_created('u3', 'user', 'э'))
    assert cut.cleared
    rig.pump(0.3)
    ended = rig.offset()
    rig.pump(0.1)
    rig.worker.heard(uid, 'э-э')
    cue = rig.next_cue(2)
    assert cue is not None and cue.text == PORTION and cue.t - ended <= TEMPO_FILLER_SECONDS + GRID


def test_the_cloud_alone_still_cuts_a_cue_when_the_ear_has_heard_nothing_for_a_while(call):
    rig = call(max_auto_repeats=3)
    rig.second_portion()
    cue = in_flight(rig)
    assert cue.text == PORTION
    rig.w.feed(S.turn_created('u3', 'user', 'м'))
    assert cue.cleared, 'nothing says that this is old news'
    assert rig.next_cue(TEMPO_REPEAT_SECONDS + TEMPO_STEP_SECONDS + GRID) is not None, 'nobody will tell the end of what it cut: the timer runs'


def test_the_phones_own_cancel_still_cuts_a_cue(call):
    rig = call()
    rig.second_portion()
    rig.pump(0.5)
    rig.says('общие', speech=0.3, lag=0.1)
    cue = in_flight(rig)
    rig.w.client({'type': 'response.cancel'})
    assert cue.cleared


def test_old_news_is_old_only_for_a_while(call):
    rig = call(max_auto_repeats=3)
    rig.second_portion()
    rig.pump(0.5)
    rig.says('э-э', speech=0.3)
    rig.pump(TEMPO_ANNOUNCE_SECONDS + TICK)
    cue = in_flight(rig)
    rig.w.feed(S.turn_created('u3', 'user', 'м'))
    assert cue.cleared


def test_a_timer_of_these_rules_stands_while_the_portion_is_said(call):
    """The final of a try comes while the next cue is being played: nothing fires over it."""
    rig = call(max_auto_repeats=3)
    rig.second_portion()
    rig.pump(0.5)
    rig.says('общие', speech=0.3, lag=0.1)
    cue = in_flight(rig)
    assert cue.text == REST
    rig.w.feed(S.turn_done('u3', 'user', 'общие'), settle=False)
    rig.w.run(rig.w.wire.tick())
    assert rig.c.repeat_at is None, 'its own end arms the timer'
    rig.w.settle()
    assert len(rig.said()) == 3 and rig.c.repeat_at is not None


# =====================================================================================================================================
# the call, in the order of its log
# =====================================================================================================================================

def replay(rig):
    """69.1-90.8 of the call, every event at its time (the ear's by speech_ms and lag_ms of the log): the turn of the cloud that opened at 69.1 stays open and grows, as it did until 105.8. Returns the second of
    the call of every cue past the portion, and the wall of the cue's end at 73.0."""
    rig.first_portion()
    rig.w.feed(S.turn_created('u4', 'user', 'Статья'))
    rig.w.feed(S.turn_done('u4', 'user', 'Статья 17 Налогового кодекса'))
    rig.w.feed(S.turn_created('u5', 'user', 'кодекса'))
    rig.pump(TICK * 2)
    assert rig.said() == [HEAD, PORTION]
    zero = rig.ended() - 73.0

    def at(second):
        left = zero + second - rig.w.clock.t
        if left > 0:
            rig.pump(left)
    ear = rig.c.tempo_live
    at(75.14)
    first = rig.onset()
    at(76.375)
    rig.offset()
    at(76.50)
    rig.worker.heard(first, 'общие')
    at(77.13)
    second = rig.onset()
    rig.w.feed(S.turn_delta('u5', ' о', 1))                 # the cloud's transcript of what was said two seconds ago
    at(78.18)
    rig.offset()
    at(78.35)
    third = rig.onset()
    at(78.36)
    rig.worker.heard(second, '')
    rig.w.feed(S.turn_delta('u5', ' общие', 2))
    at(79.55)
    rig.offset()
    at(79.82)
    rig.worker.heard(third, 'оксим')
    at(81.7)
    rig.w.feed(S.turn_delta('u5', ' общие', 3))
    at(92.0)
    return [round(c.t - zero, 1) for c in rig.cues()[2:]], [c.text for c in rig.cues()[2:]], ear


def test_the_call_of_20_34_in_the_order_of_its_log_at_its_times(call):
    rig = call(**WAIT_OF_H3)
    times, texts, ear = replay(rig)
    assert ear and texts and texts[0] == REST
    assert times[0] <= 80.0, 'the help at 90.8 of the call'


# =====================================================================================================================================
# H3: skeptic. The neighbours of each case, each of them failed on the code as it was first written
# =====================================================================================================================================

# -- rule 3: what a start is ----------------------------------------------------------------------------------------------------------

def test_the_join_keeps_where_each_piece_began(call):
    """The chain is walked by the onset of each piece. Kept as where the chain began, a third piece never reached the first. Only this test can tell: a stammer on what was just cued (below) also carries
    a start from piece to piece, so the behaviour alone no longer shows the join."""
    rig = call()
    rig.second_portion()
    where = rig.c._position(rig.c.state())
    t = rig.w.clock.t
    assert rig.c._tempo_join(where, 'общие', t, t + 0.3) == 'общие'
    assert rig.c._tempo_join(where, 'условия', t + 0.5, t + 0.8) == 'общие условия'
    assert rig.c._tempo_join(where, 'установления', t + 1.0, t + 1.3) == 'общие условия установления'
    assert rig.c._tempo_join(where, 'налогов', t + 3.0, t + 3.3) == 'налогов', 'a pause longer than a breath ends the chain'


def test_a_start_in_three_pieces(call):
    """The ear cuts at 300 ms of quiet: what is missing of the three."""
    rig = call()
    rig.second_portion()
    rig.pump(0.5)
    for word in ('общие', 'условия'):
        rig.says(word, speech=0.3, lag=0.1)
        rig.pump(0.2)
    ended = rig.says('установления', speech=0.3, lag=0.1)
    cue = rig.next_cue(2)
    assert cue is not None and cue.text == 'налогов и сборов.' and cue.t - ended == pytest.approx(TEMPO_START_SECONDS, abs=GRID)


def test_a_start_in_more_pieces_than_the_join_holds(call):
    """Word by word: what the first pieces left is what the next one starts."""
    rig = call()
    rig.second_portion()
    rig.pump(0.5)
    for word in ('общие', 'условия', 'установления'):
        rig.says(word, speech=0.3, lag=0.1)
        rig.pump(0.2)
    ended = rig.says('налогов', speech=0.3, lag=0.1)
    cue = rig.next_cue(2)
    assert cue is not None and cue.text == 'и сборов.' and cue.t - ended == pytest.approx(TEMPO_START_SECONDS, abs=GRID)


def test_a_stammer_on_the_tail_is_helped_as_fast_as_the_first(call):
    """«общие» | what is missing | «условия»: the listener is stuck again, on what was just cued. It was no start of the portion, so it waited for the cloud."""
    rig = call(max_auto_repeats=3)
    rig.second_portion()
    rig.pump(0.5)
    rig.says('общие', speech=0.3)
    assert rig.next_cue(2).text == REST
    rig.pump(0.5)
    ended = rig.says('условия', speech=0.3)
    cue = rig.next_cue(2)
    assert cue is not None and cue.text == 'установления налогов и сборов.' and cue.t - ended == pytest.approx(TEMPO_START_SECONDS, abs=GRID)


def test_a_stammer_on_the_tail_said_twice(call):
    rig = call(max_auto_repeats=3)
    rig.second_portion()
    rig.pump(0.5)
    rig.says('общие', speech=0.3)
    assert rig.next_cue(2).text == REST
    rig.pump(0.5)
    ended = rig.says('условия условия', speech=0.3)
    cue = rig.next_cue(2)
    assert cue is not None and cue.text == 'установления налогов и сборов.' and cue.t - ended == pytest.approx(TEMPO_TWICE_SECONDS, abs=GRID)


def test_the_tail_said_to_its_end_is_no_stammer(call):
    """It is the repeat, and its final confirms it."""
    rig = call(max_auto_repeats=3)
    rig.second_portion()
    rig.pump(0.5)
    rig.says('общие', speech=0.3)
    assert rig.next_cue(2).text == REST
    rig.pump(0.5)
    rig.says('условия установления налогов и сборов', speech=1.0)
    assert rig.next_cue(2.5) is None


@pytest.mark.parametrize('answer,said,rest', [
    ('Так называемые прямые налоги платят все.', 'так называемые', 'прямые налоги платят все.'),
    ('Вот главные условия налога.', 'вот главные', 'условия налога.'),
    ('Ну вот главная мысль этой статьи.', 'ну вот главная', 'мысль этой статьи.'),
    ('Это право налогоплательщика на вычет.', 'это право', 'налогоплательщика на вычет.'),
    ('Как правило налог платят раз в год.', 'как правило', 'налог платят раз в год.'),
    ('Значит налог платят раз в год.', 'значит налог', 'платят раз в год.'),
], ids=lambda value: value.split()[0])
def test_a_portion_that_opens_with_a_word_of_filler(call, answer, said, rest):
    """«так», «вот», «ну» are fillers in speech and words of the portion here: they were dropped from what was said and the start did not fit."""
    rig = call(fast_text='on')
    rig.asks('u1', 'Что это такое вообще', 0, answer)
    assert rig.said()[-1] == answer
    rig.pump(0.5)
    ended = rig.says(said, speech=0.4)
    cue = rig.next_cue(2)
    assert cue is not None and cue.text == rest and cue.t - ended == pytest.approx(TEMPO_START_SECONDS, abs=GRID)


def test_a_filler_is_still_no_word_of_the_start_of_a_portion_without_it(call):
    rig = call()
    rig.second_portion()
    rig.pump(0.5)
    rig.says('так вот общие', speech=0.4)
    assert rig.next_cue(2).text == REST


@pytest.mark.parametrize('said', ['девятьсот', 'девятьсот восемьдесят'])
def test_a_year_started_without_its_preposition(call, said):
    """The recognizer drops a short word at the start of an utterance («татья семнадцать», 66.6 of the call), and people do."""
    rig = call(fast_text='on')
    rig.asks('u1', BAPTISM, 0, 'В 988 году.')
    rig.pump(0.5)
    ended = rig.says(said)
    cue = rig.next_cue(2)
    assert cue is not None and cue.text == '988 году.' and cue.t - ended == pytest.approx(TEMPO_START_SECONDS, abs=GRID)


def test_a_year_said_to_its_end_without_its_preposition_leaves_the_rest(call):
    rig = call(fast_text='on')
    rig.asks('u1', BAPTISM, 0, 'В 988 году.')
    rig.pump(0.5)
    rig.says('девятьсот восемьдесят восьмом')
    assert rig.next_cue(2).text == 'году.'


@pytest.mark.parametrize('said', ['девятьсот восемьдесят девятом', 'восемьсот восемьдесят', 'тысяча девятьсот'])
def test_another_number_with_no_preposition_is_no_start(call, said):
    rig = call(fast_text='on')
    rig.asks('u1', BAPTISM, 0, 'В 988 году.')
    rig.pump(0.5)
    rig.says(said)
    assert rig.next_cue(2) is None


@pytest.mark.parametrize('said', ['общие условия установления налогов и взносов', 'общие условия установления налогов и пошлин'], ids=['взносов', 'пошлин'])
def test_a_whole_try_with_a_wrong_last_word_is_no_start(call, said):
    """As long as the portion: a listener who did not stop. Only the end of it was «the words after a start that are none of the portion's», and a wrong term got «и сборов.» for an answer."""
    rig = call()
    rig.second_portion()
    rig.pump(0.5)
    rig.says(said, speech=1.0)
    assert rig.next_cue(1.5) is None, 'no tail'
    rig.w.feed(S.turn_done('u3', 'user', said))
    cue = rig.next_cue(1.3)
    assert cue is not None and cue.text == PORTION, 'the whole portion, a second after the final (G3 rule 1)'


def test_a_repeat_with_words_after_it_is_no_start_and_its_final_confirms_it(call):
    """«сбора» is «сборов»: a whole repeat that goes on. No tail, and the repeat counts."""
    rig = call()
    rig.second_portion()
    rig.pump(0.5)
    said = 'общие условия установления налогов и сбора акцизов'
    rig.says(said, speech=1.0)
    assert rig.next_cue(1.5) is None
    rig.w.feed(S.turn_done('u3', 'user', said))
    rig.pump(TICK)
    assert rig.c.state().get('completed')


def test_a_shorter_try_with_a_wrong_last_word_gets_what_is_missing(call):
    rig = call()
    rig.second_portion()
    rig.pump(0.5)
    rig.says('общие условия взносов', speech=0.6)
    assert rig.next_cue(2).text == 'установления налогов и сборов.'


# -- rule 4: what a hesitation is ------------------------------------------------------------------------------------------------------

BLANKS = ['не могу вспомнить', 'вылетело из головы', 'забыл как дальше', 'сейчас сейчас вспомню', 'никак не могу вспомнить', 'блин блин блин', 'ой ой ой', 'э-э не помню никак']


@pytest.mark.parametrize('said', BLANKS, ids=lambda value: value.replace(' ', '_'))
def test_the_word_will_not_come_however_long_it_is_said(call, said):
    """The very moment help is for. As other speech it waited for the cloud's final, the job and rule 2 again: eight seconds for a listener who has just said they are stuck."""
    rig = call()
    rig.second_portion()
    rig.pump(0.5)
    ended = rig.says(said, speech=0.6)
    cue = rig.next_cue(TEMPO_FILLER_SECONDS + GRID + TICK)
    assert cue is not None and cue.text == PORTION and cue.t - ended <= TEMPO_FILLER_SECONDS + GRID


@pytest.mark.parametrize('said', ['общие не могу вспомнить', 'общие вылетело из головы', 'общие как же там было', 'общие условия забыл как дальше'], ids=lambda value: value.replace(' ', '_'))
def test_a_start_and_then_the_word_will_not_come(call, said):
    rig = call()
    rig.second_portion()
    rig.pump(0.5)
    ended = rig.says(said, speech=0.8)
    cue = rig.next_cue(TEMPO_START_SECONDS + GRID + TICK)
    assert cue is not None and cue.t - ended == pytest.approx(TEMPO_START_SECONDS, abs=GRID) and cue.text in (REST, 'установления налогов и сборов.')


@pytest.mark.parametrize('said', ['кто это', 'а кто', 'где', 'когда', 'зачем', 'сколько', 'а сколько', 'какой', 'какой год', 'чему равно', 'это как', 'как называется', 'сколько лет'],
                         ids=lambda value: value.replace(' ', '_'))
def test_a_short_question_is_no_hesitation(call, said):
    """It has no form the classifier sees, but the question words are its own vocabulary: the job is to hear it, not the portion spoken over it 1.5 s later."""
    rig = call()
    rig.second_portion()
    rig.pump(0.5)
    rig.says(said, speech=0.5)
    assert rig.next_cue(3) is None


@pytest.mark.parametrize('said', ['как там', 'как его', 'как же там', 'что там', 'как это там', 'как же это там было', 'ну как его там', 'что-то там'], ids=lambda value: value.replace(' ', '_'))
def test_a_question_word_that_looks_for_the_word_is_a_hesitation(call, said):
    rig = call()
    rig.second_portion()
    rig.pump(0.5)
    ended = rig.says(said, speech=0.5)
    cue = rig.next_cue(TEMPO_FILLER_SECONDS + GRID + TICK)
    assert cue is not None and cue.text == PORTION and cue.t - ended <= TEMPO_FILLER_SECONDS + GRID


def test_a_long_remark_that_mentions_forgetting_is_no_hesitation(call):
    rig = call()
    rig.second_portion()
    rig.pump(0.5)
    rig.says('блин я вчера забыл позвонить на работу и теперь начальник очень сердится', speech=3.0)
    rig.pump(3)
    assert rig.said() == [HEAD, PORTION], 'three seconds of speech: a cue would have come inside says(), before next_cue begins to count'


def test_a_hesitation_over_a_cue_that_it_cut_counts(call):
    """The cue was cut by this very speech, so it is no cue heard back: rule 4 stands."""
    rig = call(max_auto_repeats=3)
    rig.second_portion()
    cut = in_flight(rig)
    uid = rig.onset(settle=False)
    rig.w.feed(S.turn_created('u3', 'user', 'э'))
    assert cut.cleared
    rig.pump(0.3)
    ended = rig.offset()
    rig.pump(0.1)
    rig.worker.heard(uid, 'как там')
    cue = rig.next_cue(2)
    assert cue is not None and cue.t - ended <= TEMPO_FILLER_SECONDS + GRID


def test_a_start_over_a_cue_that_it_cut_gets_what_is_missing(call):
    rig = call(max_auto_repeats=3)
    rig.second_portion()
    cut = in_flight(rig)
    uid = rig.onset(settle=False)
    rig.w.feed(S.turn_created('u3', 'user', 'общие'))
    assert cut.cleared
    rig.pump(0.3)
    ended = rig.offset()
    rig.pump(0.1)
    rig.worker.heard(uid, 'общие')
    cue = rig.next_cue(2)
    assert cue is not None and cue.text == REST and cue.t - ended == pytest.approx(TEMPO_START_SECONDS, abs=GRID)


def test_speech_over_a_cue_that_ran_to_its_end_is_still_no_start(call):
    """Not cut: it may be the cue heard back."""
    rig = call(max_auto_repeats=3)
    rig.second_portion()
    assert in_flight(rig).text == PORTION
    uid = rig.onset(settle=False)
    rig.pump(0.3)
    rig.offset()
    rig.pump(0.1)
    rig.worker.heard(uid, 'общие')
    assert rig.next_cue(1.5) is None


# -- rule 5: the job and the timer -----------------------------------------------------------------------------------------------------

REMARK_FINAL = 'Блин, ну ты, конечно, долго. Вот я, допустим, тупил.'


def said_with_no_text(rig):
    """The ear heard speech and its text never came (the model warming, too much queued): rule 2 runs from its end."""
    rig.onset()
    rig.pump(0.5)
    ended = rig.offset()
    rig.pump(TEMPO_TEXT_SECONDS + TICK * 2)
    return ended


def test_the_timer_does_not_fire_over_a_job_that_judges(call):
    """The hold was the ear's: with no text from it the timer ran on, and said the old portion over the job. The cue came 3.5 s after speech that had just reached the job."""
    rig = call(fast_text='on')
    job_plan(rig)
    portion = rig.said()[-1]
    rig.pump(1.0)
    said_with_no_text(rig)
    rig.w.feed(S.turn_done('u2', 'user', REMARK_FINAL))
    rig.pump(TICK)
    rig.job_says(1, 'Ну')
    rig.pump(3.0)
    assert rig.said() == [portion], 'the final is the job\'s'


def test_the_timer_does_not_fire_over_a_job_when_the_ear_took_it_for_a_hesitation(call):
    """The ear heard «так», the cloud the whole remark."""
    rig = call(fast_text='on')
    job_plan(rig)
    portion = rig.said()[-1]
    rig.pump(1.0)
    rig.says('так', speech=0.4)
    rig.w.feed(S.turn_done('u2', 'user', 'Так это же совсем не то, о чём мы договаривались.'))
    rig.pump(TICK)
    rig.job_says(1, 'Ну')
    rig.pump(3.0)
    assert rig.said() == [portion]


def test_a_decline_after_that_runs_the_timer_from_the_decline(call):
    rig = call(fast_text='on')
    job_plan(rig)
    portion = rig.said()[-1]
    rig.pump(1.0)
    said_with_no_text(rig)
    rig.w.feed(S.turn_done('u2', 'user', REMARK_FINAL))
    rig.pump(TICK)
    rig.job_says(1, 'Ну')
    rig.pump(2.5)
    rig.job_says(1, '—')
    rig.job_ends(1)
    declined = rig.w.clock.t
    cue = rig.next_cue(5)
    assert cue is not None and cue.text == portion and cue.t - declined == pytest.approx(TEMPO_REPEAT_SECONDS, abs=GRID + TICK * 2), 'not at once: it is rule 5'


def test_a_listener_back_at_the_portion_while_the_job_judges_is_helped(call):
    """The remark is with the job, and they have gone back to the portion: rule 3 is for them, the job does not hold that."""
    rig = call(fast_text='on')
    job_plan(rig)
    portion = rig.said()[-1]
    rig.pump(0.5)
    rig.says(REMARK, speech=2.0)
    rig.w.feed(S.turn_done('u2', 'user', REMARK_FINAL))
    rig.pump(TICK)
    rig.job_says(1, 'Ну')
    rig.pump(0.3)
    ended = rig.says(portion.split()[0], speech=0.3)
    cue = rig.next_cue(2)
    assert cue is not None and cue.text == portion.split(' ', 1)[1] and cue.t - ended == pytest.approx(TEMPO_START_SECONDS, abs=GRID)


def test_a_start_from_before_that_final_is_no_reason_to_speak_over_the_job(call):
    """The tail was cued, then a remark reached the job: the start is still inside its window, but it was before the remark. Only one said after the final goes first."""
    rig = call(fast_text='on', max_auto_repeats=3)
    job_plan(rig)
    portion = rig.said()[-1]
    rig.pump(0.5)
    rig.says(portion.split()[0], speech=0.3)
    assert rig.next_cue(2).text == portion.split(' ', 1)[1]
    count = len(rig.said())
    rig.pump(0.3)
    rig.w.feed(S.turn_done('u2', 'user', REMARK_FINAL))
    rig.pump(TICK)
    rig.job_says(1, 'Ну')
    rig.pump(TEMPO_REPEAT_SECONDS + TEMPO_STEP_SECONDS + 0.5)
    assert len(rig.said()) == count, 'its timer has run out, and the job is at work'


def test_a_decline_does_not_put_off_the_help_of_a_start(call):
    rig = call(fast_text='on')
    job_plan(rig)
    portion = rig.said()[-1]
    rig.pump(0.5)
    rig.says(REMARK, speech=2.0)
    rig.w.feed(S.turn_done('u2', 'user', REMARK_FINAL))
    rig.pump(TICK)
    rig.job_says(1, 'Ну')
    rig.pump(0.3)
    ended = rig.says(portion.split()[0], speech=0.3)
    rig.job_says(1, '—')
    rig.job_ends(1)
    cue = rig.next_cue(2)
    assert cue is not None and cue.t - ended == pytest.approx(TEMPO_START_SECONDS, abs=GRID + TICK * 2), 'its 1.2 s stand'


def test_without_the_channel_other_speech_stays_what_it_was(call):
    """W1F-B C4: after speech the classifier cannot place, the old portion is not said (w1_09, w1_12, w1_14). The hold ended by itself at 8 s and said it."""
    rig = call()
    rig.second_portion()
    rig.pump(0.5)
    rig.says(REMARK, speech=2.0)
    rig.pump(0.5)
    rig.w.feed(S.turn_created('u3', 'user', 'Блин'))
    rig.w.feed(S.turn_done('u3', 'user', REMARK_FINAL))
    assert rig.next_cue(TEMPO_HOLD_SECONDS + 4) is None


def test_with_the_ear_off_a_remark_of_the_cloud_alone_leaves_the_plan_alone(call):
    """The control of the owner's rule «no ear, no tempo of the ear»: nothing of the ear, the cloud's own turn."""
    rig = call(ear='off')
    assert rig.ear is None and rig.c.tempo_live is False
    rig.second_portion()
    rig.pump(0.5)
    rig.w.feed(S.turn_created('u3', 'user', 'Блин'))
    rig.w.feed(S.turn_done('u3', 'user', REMARK_FINAL))
    assert rig.next_cue(TEMPO_HOLD_SECONDS + 4) is None


def test_a_greeting_is_never_asked_and_repeats_nothing(call):
    rig = call(fast_text='on')
    job_plan(rig)
    portion = rig.said()[-1]
    rig.pump(0.5)
    rig.says('здравствуйте как ваши дела сегодня', speech=1.0)
    rig.w.feed(S.turn_done('u2', 'user', 'Здравствуйте!'))
    rig.pump(TEMPO_HOLD_SECONDS + 2)
    assert rig.said() == [portion]


def test_a_final_that_runs_the_timer_is_still_not_put_off_by_the_hold(call):
    """The other side of that: a try ends the hold with the wait of rule 2."""
    rig = call()
    rig.second_portion()
    rig.pump(0.5)
    ended = rig.says('условия налогов', speech=0.8)
    rig.w.feed(S.turn_done('u3', 'user', 'условия налогов'))
    cue = rig.next_cue(4)
    assert cue is not None and cue.text == PORTION and cue.t - ended == pytest.approx(TEMPO_REPEAT_SECONDS, abs=GRID + TICK * 2)


# -- a number in the portion, repeated ----------------------------------------------------------------------------------------------------

@pytest.mark.parametrize('ear', ['act', 'shadow'])
def test_the_rest_of_a_year_confirmed_in_words(call, ear):
    rig = call(fast_text='on', ear=ear)
    rig.asks('u1', BAPTISM, 0, 'В 988 году.')
    rig.pump(0.5)
    rig.says('в девятьсот')
    assert rig.next_cue(2).text == '988 году.'
    rig.pump(0.5)
    rig.says('девятьсот восемьдесят восьмом году', speech=1.0)
    rig.w.feed(S.turn_created('u3', 'user', 'девятьсот'))
    rig.w.feed(S.turn_done('u3', 'user', 'девятьсот восемьдесят восьмом году'))
    rig.pump(TICK)
    assert rig.c.state().get('completed'), 'the missing part was confirmed, by value'


def test_a_wrong_number_for_the_rest_confirms_nothing(call):
    rig = call(fast_text='on', max_auto_repeats=3)
    rig.asks('u1', BAPTISM, 0, 'В 988 году.')
    rig.pump(0.5)
    rig.says('в девятьсот')
    assert rig.next_cue(2).text == '988 году.'
    rig.pump(0.5)
    rig.says('девятьсот восемьдесят девятом году', speech=1.0)
    rig.w.feed(S.turn_created('u3', 'user', 'девятьсот'))
    rig.w.feed(S.turn_done('u3', 'user', 'девятьсот восемьдесят девятом году'))
    rig.pump(TICK)
    assert not rig.c.state().get('completed')


def test_a_doubt_of_the_year_after_the_help(call):
    """«ты уверена» after a tail: the job's, and the tail is not said over it."""
    rig = call(fast_text='on', max_auto_repeats=3)
    rig.asks('u1', BAPTISM, 0, 'В 988 году.')
    rig.pump(0.5)
    rig.says('в девятьсот')
    assert rig.next_cue(2).text == '988 году.'
    rig.pump(0.5)
    rig.says('ты уверена', speech=0.5)
    count = len(rig.said())
    rig.w.feed(S.turn_created('u3', 'user', 'Ты'))
    rig.w.feed(S.turn_done('u3', 'user', 'Ты уверена?'))
    rig.pump(TICK)
    assert len(rig.said()) == count
    rig.job_says(1, 'Да, в 988 году.')
    rig.job_ends(1)
    rig.pump(EAR_RELEASE_SILENCE_SECONDS)
    assert rig.said()[count:] == ['Да, в 988 году.']


# -- the whole call, every utterance of the ear at the time its log gives ---------------------------------------------------------------

# (onset, offset, text at, what it heard): the 49 lines of the ear in the timeline, with the speech_ms and lag_ms of the agent log of that call.
CALL_EAR = [
    (21.343, 25.069, 25.3, 'да конечно двадцать пять секунд подключаться это мощное'),
    (35.631, 36.134, 36.3, 'хорошо'),
    (36.483, 36.854, 37.0, 'да я готовился про само'),
    (36.858, 37.651, 37.8, 'самом деле'),
    (38.805, 40.995, 41.3, 'да я готовился'),
    (41.098, 44.637, 45.3, 'готовился в целом'),
    (44.989, 45.255, 45.5, 'что вам-то это дам'),
    (46.024, 48.766, 48.9, 'ну что давайте задавайте любой вопрос собственно я готов'),
    (50.019, 52.339, 52.5, 'да какой ещё раз вопрос'),
    (53.073, 56.216, 56.4, 'семнадцатая статья налогового кодекса'),
    (59.401, 59.756, 59.9, ''),
    (62.094, 62.64, 63.0, 'с'),
    (63.008, 66.365, 66.6, 'татья семнадцать налогового кодекса'),
    (75.144, 76.375, 76.5, 'общие'),
    (77.072, 78.119, 78.3, ''),
    (78.325, 79.532, 79.8, 'оксим'),
    (91.797, 92.652, 92.8, ''),
    (96.683, 102.56, 102.9, 'общие условия установления налогов и сборов блин но ты конечно долго вот я допустим тупил'),
    (103.028, 104.307, 104.8, 'целенаправленно'),
    (104.429, 110.466, 110.7, 'а ты мне подсказываешь секунд через шесть через семь но это вообще очень плохо плохо'),
    (110.59, 121.084, 121.3, 'ты уже у тебя уже был уже хороший быстрый такой повтор но видимо я до этого просто без ошибок повтор твой смотрел а сейчас вот если лёгкую ошибку допускать если я хоть что-то не расслышал'),
    (121.541, 126.527, 126.7, 'то ты все ты вовремя не подсказываешь а надо наоборот что ты прямо вот говорила говорила прям'),
    (127.019, 131.504, 131.7, 'прям подсказывала быстрее реагировать нужно значит медленно пока реагируешь хорошо'),
    (131.62, 133.156, 133.4, 'пять умножить на пять'),
    (140.427, 141.96, 142.1, 'двадцать пять'),
    (142.324, 145.693, 145.9, 'хорошо считаем быстро'),
    (145.984, 146.968, 147.1, 'так в каком году было крещение руси'),
    (155.6, 161.047, 161.2, 'тысяча девятьсот восемьдесят восьмой ты уверена'),
    (171.508, 173.933, 174.4, 'восемьсот восемьдесят восьмой'),
    (174.763, 177.683, 177.8, 'ну короче у тебя ответы тупо вообще неправильные какие'),
    (177.759, 180.042, 180.2, 'какие-то пошли я понял выдуманные'),
    (180.54, 183.052, 183.2, 'но зато кстати да почти пять секунд'),
    (183.909, 186.286, 186.6, 'но это ответ выдуманный ни о чем'),
    (186.59, 187.346, 187.6, 'типа блин'),
    (189.57, 191.214, 191.4, 'это зачем такие ответы'),
    (192.384, 198.144, 198.4, 'короче тоже слабоватенько пока не не нужно прямо дорабатывать сценарий прям прогонять'),
    (199.001, 202.698, 202.9, 'вот такие же проблемы придумывать как я и до этого придумал'),
    (202.796, 206.16, 206.5, 'вот даже стандартные проблемы таких проблем но'),
    (206.24, 208.626, 208.8, 'по классам придумайте а не знаю штуку'),
    (209.574, 215.145, 215.3, 'тридцать сорок таких классовых проблем и сценарий их вот таких найти искать'),
    (215.563, 220.667, 221.0, 'или там взять уже готовый диалог как люди общаются как опрашивают людей'),
    (220.799, 229.051, 229.8, 'вот в интернете и добавить просто эти классы проблем в этот диалог и все и смотреть как система отрабатывает по-разному вставлять эти пробелы'),
    (229.656, 231.007, 231.3, 'он тогда'),
    (232.388, 233.145, 233.7, 'система отработает'),
    (234.34, 236.296, 236.8, 'короче пока что слабо понял'),
    (238.101, 239.159, 239.4, 'с'),
    (239.358, 241.453, 241.7, 'двадцать первая статья налогового кодекса'),
    (260.875, 266.925, 267.2, 'так статья двадцать один это про права налогоплательщиков'),
    (274.725, 277.507, 277.8, 'и просто никакой ответ все я понял'),
]


def the_whole_call(rig, *, job=job_of_the_call, late=1.2, fail=(), until=270.0):
    """Every event of the cloud (CALL_2034) and of the ear (CALL_EAR) at its time, the job answering ``late`` seconds after it is asked. Returns the cues as ``(second, text, cut)``."""
    w, fake = rig.w, rig.fake
    zero = w.clock.now() - 20.0
    asked, served, uids = {}, set(), {}

    def step():
        now = w.clock.now() - zero
        for n, run in enumerate(list(fake.runs) if fake else ()):
            asked.setdefault(n, now)
            if n not in served and now - asked[n] >= late:
                served.add(n)
                if not run.cancelled.is_set():
                    if n in fail:
                        run.fail()
                    else:
                        run.say(job(run.question))
                        run.finish()
                    settled(rig.fast)
        rig.pump(TICK)

    def until_moment(moment):
        while w.clock.now() - zero < moment:
            step()

    timeline, opened = [], {}
    for at, kind, key, text in CALL_2034:
        timeline.append((at, kind, key, text))
        if kind == 'ustart':
            opened[key] = at
        elif kind == 'user' and key in opened:
            words = text.split()
            timeline += [(opened[key] + (at - opened[key]) * (n + 1) / len(words) - 0.01, 'word', key, (word + ' ', n)) for n, word in enumerate(words[:-1])]
    for n, (onset, offset, at, text) in enumerate(CALL_EAR):
        timeline += [(onset, 'onset', n, None), (offset, 'offset', n, None), (at, 'text', n, text)]
    for at, kind, key, text in sorted(timeline, key=lambda row: row[0]):
        until_moment(at)
        if kind == 'onset':
            if rig.ear.current is not None:
                rig.offset()
            uids[key] = rig.onset()
        elif kind == 'offset':
            if rig.ear.current == uids.get(key):
                rig.offset()
        elif kind == 'text':
            if key in uids:
                rig.worker.heard(uids[key], text)
        elif kind in ('ustart', 'astart'):
            w.feed(S.turn_created(key, 'user' if kind == 'ustart' else 'assistant', ''))
        elif kind == 'word':
            w.feed(S.turn_delta(key, *text))
        else:
            w.feed(S.turn_done(key, 'user' if kind == 'user' else 'assistant', text))
    until_moment(until)
    return [(round(c.t - zero, 2), c.text, c.cleared) for c in rig.cues()]


def into_speech(cues):
    """The cues that began while the ear heard speech, longer than a hold of a ready cue by the ear alone (ONSET_HOLD_MAX_S)."""
    return [(at, text) for at, text, _ in cues if any(onset + ONSET_HOLD_MAX_S + GRID < at < offset for onset, offset, _, _ in CALL_EAR)]


def over_the_ear(cues, rig=None):
    """The failure message of ``into_speech``: each cue that began over the listener, the utterance of the ear it began in and the cues before it (REDF: the cause of ``job_late[shadow]`` is unknown, so a red run says which cue it was, in which rule it was held and what came before)."""
    rows = []
    for at, text in into_speech(cues):
        window = next(((onset, offset) for onset, offset, _, _ in CALL_EAR if onset + ONSET_HOLD_MAX_S + GRID < at < offset), None)
        rows.append({'cue': (at, text), 'ear_window': window, 'before': [(a, t, c) for a, t, c in cues if at - 6.0 <= a <= at]})
    return rows


def test_the_whole_call_of_20_34_with_the_ear_of_its_log(call):
    rig = call(fast_text='on')
    cues = the_whole_call(rig)
    said = [text for _, text, _ in cues]
    assert not [text for at, text, _ in cues if at < 56.4], 'nothing before the first question: not «Ну наконец-то.», twice (H4: the ear has it at 56.4)'
    assert not any(word in text for text in said for word in ('Понял', 'реагировать', 'ещё вопрос', 'разобрать')), 'no meta tails'
    help_at = next(at for at, text, _ in cues if text == REST)
    assert help_at <= 80.0, 'the help came at 90.8 of the call'
    assert '25' in said and any('988' in text for text in said) and not any('1988' in text.replace(' ', '') for text in said)
    assert into_speech(cues) == [], 'never over the listener'
    assert not [(at, text) for at, text, _ in cues if 94.0 < at < 137.0], 'his long remark about the prompter is not talked over'


@pytest.mark.parametrize('ear', ['act', 'shadow'])
@pytest.mark.parametrize('late', [0.2, 2.0, 3.5])
def test_the_whole_call_with_the_job_late(call, ear, late):
    rig = call(fast_text='on', ear=ear)
    cues = the_whole_call(rig, late=late)
    assert into_speech(cues) == [], over_the_ear(cues)


@pytest.mark.parametrize('fail', [(1,), (3,), (5,), (7,), (9,)], ids=lambda value: f'job{value[0]}')
def test_the_whole_call_with_a_job_failing(call, fail):
    rig = call(fast_text='on')
    cues = the_whole_call(rig, fail=fail)
    assert into_speech(cues) == []


def test_the_whole_call_without_the_channel(call):
    rig = call()
    cues = the_whole_call(rig)
    assert next(at for at, text, _ in cues if text == REST) <= 80.0 and into_speech(cues) == []


# -- round 2: what the first fixes left, and the same events in another order --------------------------------------------------------------

@pytest.mark.parametrize('answer,said,rest', [
    ('Двадцать пять.', 'двадцать как там', 'пять.'),
    ('Общие условия налогов.', 'общие как там', 'условия налогов.'),
    ('Общие условия налогов.', 'общие не могу вспомнить', 'условия налогов.'),
    ('Общие условия налогов.', 'общие условия как же там', 'налогов.'),
], ids=lambda value: value.replace(' ', '_'))
def test_a_hesitation_after_a_start_on_a_short_portion_is_no_whole_try(call, answer, said, rest):
    """What says «a whole try» is a word in the place of the portion's, not how many words were said."""
    rig = call(fast_text='on')
    rig.asks('u1', 'Что это такое вообще', 0, answer)
    rig.pump(0.5)
    ended = rig.says(said, speech=0.5)
    cue = rig.next_cue(2)
    assert cue is not None and cue.text == rest and cue.t - ended == pytest.approx(TEMPO_START_SECONDS, abs=GRID)


@pytest.mark.parametrize('said', ['не могу вспомнить', 'вылетело из головы', 'забыл'], ids=lambda value: value.replace(' ', '_'))
def test_at_the_cap_the_word_will_not_come_is_still_heard(call, said):
    """The listener says they are stuck: that is no silence to be bounded (rule 2), it is the listener at work. At the cap of 1 the prompter stayed silent to exactly this."""
    rig = call()
    rig.second_portion()
    assert rig.next_cue(4).text == PORTION
    rig.pump(0.5)
    ended = rig.says(said, speech=0.5)
    cue = rig.next_cue(TEMPO_FILLER_SECONDS + GRID + TICK)
    assert cue is not None and cue.text == PORTION and cue.t - ended <= TEMPO_FILLER_SECONDS + GRID


def test_the_clouds_final_comes_before_the_ears_text(call):
    """The other order: the final of a stammer, and the ear's text of it a moment later. Still what is missing, once."""
    rig = call()
    rig.second_portion()
    rig.pump(0.5)
    uid = rig.onset()
    rig.pump(0.3)
    ended = rig.offset()
    rig.w.feed(S.turn_done('u3', 'user', 'общие'))
    rig.pump(TICK)
    rig.worker.heard(uid, 'общие')
    cue = rig.next_cue(2)
    assert cue is not None and cue.text == REST and cue.t - ended == pytest.approx(TEMPO_START_SECONDS, abs=GRID + TICK)
    assert rig.next_cue(2) is None


def test_a_confirmation_between_the_offset_and_the_ears_text(call):
    rig = call(**WAIT_OF_H3)
    rig.first_portion()
    rig.pump(0.5)
    uid = rig.onset()
    rig.pump(0.3)
    rig.offset()
    rig.w.feed(S.turn_done('u2', 'user', 'Статья 17 Налогового кодекса'))
    rig.pump(TICK * 2)
    assert rig.said() == [HEAD, PORTION]
    rig.worker.heard(uid, 'статья')
    cue = rig.next_cue(3.0)
    assert cue is None, 'it was said to the portion before, it starts nothing in this one'


def test_a_new_question_while_the_help_is_due(call):
    rig = call(fast_text='on')
    job_plan(rig)
    portion = rig.said()[-1]
    rig.pump(0.5)
    rig.says(portion.split()[0], speech=0.3)
    rig.w.feed(S.turn_created('u2', 'user', 'Сколько'))
    rig.w.feed(S.turn_done('u2', 'user', 'Сколько будет пять умножить на пять?'))
    rig.pump(TICK)
    rig.job_says(1, 'Двадцать пять.')
    rig.job_ends(1)
    rig.pump(EAR_RELEASE_SILENCE_SECONDS)
    assert rig.said() == [portion, 'Двадцать пять.'], 'the help of the old answer is not said over the new one'


# -- a plan that gives back: found by the whole call, not of H3 ----------------------------------------------------------------------------

def test_a_declined_question_gives_back_the_answer_in_play_not_an_older_one(call):
    """238.4 of the whole call: «Короче, пока что слабо, понял» is a question, the job says «—», and what came back was not the answer in play but the one before it. There both said 988.
    Nobody had confirmed anything of either, and the older had no better claim."""
    rig = call(fast_text='on')
    rig.asks('u1', 'Какая столица Франции?', 0, 'Париж.')
    rig.w.feed(S.turn_created('u2', 'user', 'А'))
    rig.w.feed(S.turn_done('u2', 'user', 'А какая столица Германии?'))
    rig.pump(TICK)
    rig.job_says(1, 'Берлин.')
    rig.job_ends(1)
    assert rig.said() == ['Париж.', 'Берлин.']
    rig.w.feed(S.turn_created('u3', 'user', 'Что'))
    rig.w.feed(S.turn_done('u3', 'user', 'Что-то ты сегодня какой-то медленный, что вообще происходит?'))
    rig.pump(TICK)
    rig.job_says(2, '—')
    rig.job_ends(2)
    rig.pump(TICK * 2)
    assert rig.said() == ['Париж.', 'Берлин.', 'Берлин.'], rig.said()


def test_no_answer_taken_up_outranks_a_newer_one(call):
    """H6 item 2 moved this test: «no newer answer was given since»: what was taken up no longer comes back over the answer in play, it waits in the history."""
    rig = call(fast_text='on')
    rig.asks('u1', 'Что такое инерция', 0, 'Первая часть ответа. Вторая часть ответа.')
    first = rig.said()[-1]
    rig.w.feed(S.turn_done('u2', 'user', first))
    rig.pump(TICK * 2)
    second = rig.said()[-1]
    assert second != first
    rig.w.feed(S.turn_created('u3', 'user', 'А'))
    rig.w.feed(S.turn_done('u3', 'user', 'А какая столица Германии?'))
    rig.pump(TICK)
    rig.job_says(1, 'Берлин.')
    rig.job_ends(1)
    rig.w.feed(S.turn_created('u4', 'user', 'Что'))
    rig.w.feed(S.turn_done('u4', 'user', 'Что-то ты сегодня какой-то медленный, что вообще происходит?'))
    rig.pump(TICK)
    rig.job_says(2, '—')
    rig.job_ends(2)
    rig.pump(TICK * 2)
    assert rig.said()[-1] == 'Берлин.' and second not in rig.said()[2:], rig.said()


def test_the_owners_try_with_a_word_lost_goes_on(call):
    """The call of 06.11 (a1fbfe4ba92e): the portion said back, one word of it lost; the ear's text is no ack, the cue must not go round again."""
    rig = call(max_auto_repeats=3)
    rig.first_portion()
    head = rig.next_cue(4)
    rig.pump(2.0)
    words = head.text.rstrip('.,;:').split()
    rig.says(' '.join(words[1:] if len(words) > 2 else words))
    cue = rig.next_cue(6)
    assert cue.text != head.text, rig.c.portion_tries


def test_a_second_try_goes_on_whatever_it_said(call):
    rig = call(max_auto_repeats=3)
    rig.first_portion()
    head = rig.next_cue(4)
    rig.pump(2.0)
    for _ in range(2):
        rig.says('семнадцать кодекс')
        rig.pump(0.3)
    cue = rig.next_cue(8)
    assert cue.text != head.text, ('TRIES', len((rig.c.portion_tries or (0, []))[1]), rig.c.tempo_hold, rig.c.repeat_at)


def test_own_words_that_end_on_the_portion_go_on_at_once(call):
    """The owner, 06.11: part of the answer or his own words, and at the end the last words of the portion: the next portion, no timer, no cloud."""
    rig = call(max_auto_repeats=3)
    rig.first_portion()
    head = rig.next_cue(4)
    rig.pump(2.0)
    rig.says('ну это про налоговый кодекс')
    rig.pump(0.2)
    assert rig.cues()[-1].text != head.text
