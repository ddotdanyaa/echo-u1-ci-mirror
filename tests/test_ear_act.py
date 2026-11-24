"""R-EAR-ACT (wave R, 3 Nov; scripts/DUAL_SYSTEM_DESIGN.md §3.3; brief .superpowers/sdd/wave2/task-r-briefs.md «R-EAR-ACT»): the local ear
ACTS on the listener's repeats and commands.

In mode ``local_ear = "act"`` (opt-in; the profile's default stays as it was) a verdict of the shadow ear (ear_shadow.py: sherpa-onnx +
Vosk small-ru, the controller's own classifier) that is a confirmation, a repeat request, a stop or «дальше» for the portion that waits
is applied at once through the controller's existing paths - the way a cloud final would be - instead of waiting ~1 s for the cloud's
final transcript. Questions and everything else stay the cloud's. Idempotency reuses the early-ACK reconciliation of the stable partial
(Task B / Task E ruling 3): the ear takes the cloud's open turn of the same utterance, so its later partials and final never act a second
time, and only what the listener said AFTER the part the ear decided is still classified (``_early_tail``).

Time is injected and nothing sleeps (except the wire test, which runs the real NativeMediaSocket and a real ShadowEar on a fake
recognizer). The controller, its engine and the classifier are the production ones.
"""
import base64
import logging
import threading
import time

import pytest

import helpers_s6_ack as H
from echo_sync import ear_shadow
from echo_sync.controlled_media import ACK_STABLE_SECONDS, EAR_BIND_SECONDS, EAR_COMMAND_SETTLE_SECONDS, EAR_JOIN_GAP_SECONDS, EAR_PIECE_SECONDS
from echo_sync.settings import resolve
from test_ear_shadow import FakeRecognizer, ScriptedDetector
from test_stable_partial_ack import ANSWER, AT, NUMBER_ANSWER, NUMBER_AT, PORTION, TICK, Speaker, dictation, speaks

SAID = 'при ста градусах Цельсия'           # the waiting portion as the local ear writes it: no capitals, no punctuation
# F1 (integ9): the plan of NUMBER_ANSWER is «Закон был принят в 1945.» | «Он действует до сих пор.»; the number ends the 1st portion
NUMBER_PORTION = 'Закон был принят в 1945.'
NUMBER_LEAD = 'Закон был принят '


def types(actions):
    return [a['type'] for a in actions]


class Ear:
    """The local ear as the controller meets it in act mode (ear_shadow.ShadowEar built by ``for_call`` for "act"): ``onset()`` when its
    detector hears speech begin (``ControlledMedia.ear_onset``), ``heard(text)`` when the recognizer's text of that utterance is ready -
    the record ``ShadowEar._poll`` makes, handed over by the transport's tick (``ControlledMedia.ear_heard``). Time is the dictation's;
    ``input_ms`` is the transport's count of microphone audio (the provider's input clock)."""

    def __init__(self, d, input_ms=20_000):
        self.d, self.uid, self.actions, self.input_ms = d, 0, [], input_ms

    def onset(self):
        self.uid += 1
        self.started_ms = self.input_ms
        self.d.controller.ear_onset(self.uid)
        return self

    def heard(self, text, *, speech=1.0, lag=0.1):
        """The speech goes on for ``speech`` seconds; the detector's end comes then and the text ``lag`` seconds after it."""
        self.d.clock.advance(speech)
        self.input_ms += int(speech * 1000)
        self.offset = self.d.clock()
        record = {'uid': self.uid, 'text': text, 'offset': self.offset,
                  'onset_input_ms': self.started_ms, 'offset_input_ms': self.input_ms}
        self.d.clock.advance(lag)
        actions = self.d.controller.ear_heard(record)
        self.actions += actions
        return actions

    def settle(self):
        """The quiet after the last utterance lasts until a command may act (EAR_COMMAND_SETTLE_SECONDS after its end): the transport's
        tick then. Returns what that tick did."""
        self.d.clock.now = max(self.d.clock(), self.offset + EAR_COMMAND_SETTLE_SECONDS + 0.01)
        actions = self.d.controller.tick(now=self.d.clock())
        self.actions += actions
        return actions

    def says(self, text, **kwargs):
        return self.onset().heard(text, **kwargs)


def created(tid, start_ms=None, end_ms=None, text=''):
    turn = {'id': tid, 'role': 'user', 'transcript': text}
    if start_ms is not None:
        turn.update(start_ms=start_ms, end_ms=end_ms if end_ms is not None else start_ms + 200)
    return {'type': 'turn.created', 'turn': turn}


# ====================================================================================================================
# the setting: opt-in, and nothing acts unless it says "act"
# ====================================================================================================================

def test_act_is_a_mode_of_local_ear_and_the_default_is_unchanged():
    assert resolve({'local_ear': 'act'})['local_ear'] == 'act'
    assert resolve({})['local_ear'] == 'off', 'the code default stays what it was (the deployed profile says "shadow")'
    assert resolve({'local_ear': 'on'})['local_ear'] == 'off', 'an unknown mode is off'


def test_for_call_builds_an_acting_ear_only_for_act(tmp_path):
    d = H.Dictation(tmp_path / 'for-call', ANSWER)
    worker = ear_shadow.EarWorker(lambda: FakeRecognizer([]))
    shadow = ear_shadow.for_call(resolve({'local_ear': 'shadow'}), d.controller, detector_factory=lambda: ScriptedDetector([]),
                                 worker=worker)
    act = ear_shadow.for_call(resolve({'local_ear': 'act'}), d.controller, detector_factory=lambda: ScriptedDetector([]), worker=worker)
    assert shadow.acting is False and shadow.on_onset is None, 'shadow: the controller is only read'
    assert act.acting is True and act.on_onset == d.controller.ear_onset
    assert ear_shadow.for_call(resolve({}), d.controller, detector_factory=lambda: ScriptedDetector([]), worker=worker) is None


# ====================================================================================================================
# a confirmation: at once, once
# ====================================================================================================================

def test_a_repeat_heard_by_the_ear_moves_on_without_waiting_for_the_cloud_final(tmp_path):
    d = dictation(tmp_path)
    assert d.current == PORTION, 'precondition: the portion under test waits'
    ear, cloud = Ear(d), Speaker(d)
    ear.onset()
    d.clock.advance(0.3)
    cloud.start().words('при ста')                         # the cloud has announced the utterance and has its first words
    out = ear.heard(SAID, speech=0.4)
    assert speaks(out) == [d.chunks[AT + 1]] and d.index == AT + 1, 'the next portion is spoken on the ear\'s verdict'


def test_the_cloud_never_confirms_the_same_utterance_a_second_time(tmp_path):
    d = dictation(tmp_path)
    ear, cloud = Ear(d), Speaker(d)
    ear.onset()
    d.clock.advance(0.3)
    cloud.start().words('при ста')
    ear.heard(SAID, speech=0.4)
    assert d.index == AT + 1
    cloud.words('градусах Цельсия')
    assert cloud.wait(1.0) == [], 'the stable partial of the turn the ear took confirms nothing more'
    assert cloud.final(PORTION) == [] and d.index == AT + 1, 'nor does its final'
    assert cloud.final(PORTION.rstrip('.') + ' и всё') == [] and d.index == AT + 1, 'nor a revised final of the same turn'


def test_a_stop_said_after_the_repeat_in_the_same_breath_is_still_acted_on(tmp_path):
    """The reconciliation of the stable partial (Task E, ruling 3): what was said AFTER the part the ear decided is classified on the final."""
    d = dictation(tmp_path)
    ear, cloud = Ear(d), Speaker(d)
    ear.onset()
    d.clock.advance(0.3)
    cloud.start().words('при ста')
    ear.heard(SAID, speech=0.4)
    cloud.words('градусах Цельсия стоп')
    cloud.wait(0.5)
    out = d.controller.provider(H.done('u-live', 'user', 'При ста градусах Цельсия, стоп.'))
    assert 'cancel' in types(out) and d.state.get('paused'), 'the stop after the portion was lost'


@pytest.mark.parametrize('said', [
    'не при ста градусах цельсия',
    'при двухстах градусах цельсия',
    'при ста градусах фаренгейта',
    'при ста цельсия',
    'при ста градусах цельсия два',
], ids=['negated', 'other-number', 'other-word', 'word-missing', 'extra-number'])
def test_a_wrong_repeat_is_never_taken_by_the_ear(tmp_path, said):
    d = dictation(tmp_path)
    ear, cloud = Ear(d), Speaker(d)
    ear.onset()
    d.clock.advance(0.3)
    cloud.start().words(said.split()[0])
    assert ear.heard(said, speech=0.6) == [] and d.index == AT
    cloud.words(' '.join(said.split()[1:]))
    cloud.final()
    assert d.index == AT, 'and the cloud final decides as before'


# ====================================================================================================================
# commands: at once, once
# ====================================================================================================================

@pytest.mark.parametrize('said', ['повтори', 'не расслышал'], ids=['repeat', 'hearing-repair'])
def test_a_repeat_request_replays_once(tmp_path, said):
    d = dictation(tmp_path)
    ear, cloud = Ear(d), Speaker(d)
    ear.onset()
    d.clock.advance(0.3)
    cloud.start()
    out = ear.heard(said, speech=0.4) + ear.settle()
    assert speaks(out) == [PORTION] and d.index == AT, 'the portion is said again at once'
    cloud.words(said.capitalize() + '.')
    assert cloud.final() == [] and d.index == AT, 'the cloud final of the request did not replay it a second time'


def test_a_command_right_after_another_one_the_ear_took_is_judged_alone(tmp_path):
    """«Стоп.» … «Повтори.»: the first was a whole utterance and was acted on; the second is not glued to it."""
    d = dictation(tmp_path)
    ear = Ear(d)
    ear.onset()
    d.clock.advance(0.3)
    Speaker(d, 'u-stop').start()
    assert 'cancel' in types(ear.heard('стоп', speech=0.4) + ear.settle())
    d.clock.advance(0.3)
    ear.onset()
    d.clock.advance(0.3)
    Speaker(d, 'u-again').start()
    assert speaks(ear.heard('повтори', speech=0.4) + ear.settle()) == [PORTION]


@pytest.mark.parametrize('said,final', [('стоп', 'Стоп. Стоп.'), ('повтори', 'Повтори, повтори.')], ids=['stop', 'repeat'])
def test_the_same_command_said_twice_in_one_breath_acts_once(tmp_path, said, final):
    d = dictation(tmp_path)
    ear, cloud = Ear(d), Speaker(d)
    ear.onset()
    d.clock.advance(0.3)
    cloud.start()
    ear.heard(said, speech=0.4) + ear.settle()
    epoch = d.controller.epoch
    cloud.words(final)
    assert cloud.final() == [] and d.controller.epoch == epoch, 'the command was acted on a second time'


def test_a_stop_stops_once(tmp_path):
    d = dictation(tmp_path)
    ear, cloud = Ear(d), Speaker(d)
    ear.onset()
    d.clock.advance(0.3)
    cloud.start()
    out = ear.heard('стоп', speech=0.4) + ear.settle()
    assert 'cancel' in types(out) and d.state.get('paused')
    epoch = d.controller.epoch
    cloud.words('Стоп.')
    assert cloud.final() == [] and d.controller.epoch == epoch, 'the cloud final stopped it a second time'


def test_a_question_after_a_stop_in_the_same_breath_is_not_lost(tmp_path):
    d = dictation(tmp_path)
    ear, cloud = Ear(d), Speaker(d)
    ear.onset()
    d.clock.advance(0.3)
    cloud.start()
    ear.heard('стоп', speech=0.4) + ear.settle()
    cloud.words('Стоп. А почему при ста?')
    out = cloud.d.controller.provider(H.done('u-live', 'user', 'Стоп. А почему при ста?'))
    assert 'cancel' in types(out) and ({'route', 'lookup'} & set(types(out))), types(out)
    assert d.controller.question_id == 'u-live'


def test_next_goes_on_once(tmp_path):
    d = dictation(tmp_path)
    ear, cloud = Ear(d), Speaker(d)
    ear.onset()
    d.clock.advance(0.3)
    cloud.start()
    out = ear.heard('дальше', speech=0.4) + ear.settle()
    assert speaks(out) == [d.chunks[AT + 1]] and d.index == AT + 1
    cloud.words('Дальше.')
    assert cloud.final() == [] and d.index == AT + 1, 'the cloud final skipped a second portion'


def test_a_question_is_left_to_the_cloud(tmp_path):
    d = dictation(tmp_path)
    before = dict(d.state)
    ear, cloud = Ear(d), Speaker(d)
    ear.onset()
    d.clock.advance(0.3)
    cloud.start().words('а что такое')
    assert ear.heard('а что такое кипение', speech=0.8) == [] and d.state == before
    cloud.words('кипение?')
    out = d.controller.provider(H.done('u-live', 'user', 'А что такое кипение?'))
    assert 'cancel' in types(out) and d.controller.question_id == 'u-live', 'the cloud took the question as before'


def test_the_decision_line_says_it_was_the_ear_and_carries_no_words(tmp_path, caplog):
    d = dictation(tmp_path)
    ear, cloud = Ear(d), Speaker(d)
    with caplog.at_level(logging.INFO, logger='echo-sync'):
        ear.onset()
        d.clock.advance(0.3)
        cloud.start().words('при ста')
        ear.heard(SAID, speech=0.4)
    lines = [r.getMessage() for r in caplog.records if 'reason=local_ear' in r.getMessage()]
    assert len(lines) == 1 and lines[0].startswith('echo-sync decision kind=ack reason=local_ear'), lines
    assert not any('градус' in r.getMessage() or 'цельси' in r.getMessage().lower() for r in caplog.records)


# ====================================================================================================================
# the ear's own pieces of one utterance (its detector cuts at 300 ms of quiet)
# ====================================================================================================================

def test_a_negation_cut_off_by_a_pause_is_judged_with_the_rest(tmp_path):
    """S1's one false ACK: «Не а, у насекомых шесть ног.» cut after «не»; the rest alone was the portion."""
    d = dictation(tmp_path)
    ear, cloud = Ear(d), Speaker(d)
    ear.onset()
    d.clock.advance(0.2)
    cloud.start()
    assert ear.heard('не', speech=0.2) == []
    d.clock.advance(0.2)
    assert ear.onset().heard(SAID, speech=0.9) == [] and d.index == AT, 'the ear confirmed a negated repeat'


def test_a_repeat_cut_in_two_by_the_ear_is_joined(tmp_path):
    d = dictation(tmp_path)
    ear, cloud = Ear(d), Speaker(d)
    ear.onset()
    d.clock.advance(0.3)
    cloud.start().words('при ста')
    assert ear.heard('при ста', speech=0.3) == []
    d.clock.advance(0.3)
    out = ear.onset().heard('градусах цельсия', speech=0.6)
    assert speaks(out) == [d.chunks[AT + 1]] and d.index == AT + 1


def test_a_command_the_listener_goes_on_speaking_after_is_judged_with_the_rest(tmp_path):
    """Live 03.11 09:11:35 (w1_09) and 09:30:05 (w2_06): «Подожди, лучше скажи другое: …?» - the ear's detector heard the next piece begin
    before its verdict on «подожди» came. That verdict waits: the next piece is judged with it (here: a question, the cloud's)."""
    d = dictation(tmp_path)
    ear, cloud = Ear(d), Speaker(d)
    ear.onset()
    d.clock.advance(0.2)
    cloud.start().words('Подожди')
    d.clock.advance(0.4)
    end = ear.input_ms + 400
    first = {'uid': ear.uid, 'text': 'подожди', 'offset': d.clock(), 'onset_input_ms': ear.input_ms, 'offset_input_ms': end}
    ear.input_ms = end
    d.clock.advance(0.05)
    ear.onset()                                            # the next piece begins before the verdict on the first one
    d.clock.advance(0.05)
    assert d.controller.ear_heard(first) == [] and not d.state.get('paused'), 'stopped on half an utterance'
    cloud.words('лучше скажи')
    assert ear.heard('лучше скажи сколько рук у осьминога', speech=1.5) == [] and not d.state.get('paused')


def test_a_command_that_is_only_the_start_of_an_utterance_waits_for_its_end(tmp_path):
    """Replay of the S1 bake-off (noisy, negated:0238/0239): «Не понял, | давай уточню» - the next piece began 0.05-0.23 s AFTER the ear's
    verdict on «не понял» (a request to hear it again), so it was replayed in the middle of the utterance (on the phone's open speaker the
    cue closes the microphone: the rest is cut off). A command acts only after EAR_COMMAND_SETTLE_SECONDS of quiet after its end; speech
    that begins meanwhile is judged with it («повтори, что ты сейчас сказал» is a question: the cloud's)."""
    d = dictation(tmp_path)
    ear, cloud = Ear(d), Speaker(d)
    ear.onset()
    d.clock.advance(0.3)
    cloud.start()
    assert ear.heard('повтори', speech=0.4, lag=0.1) == [], 'replayed before the utterance was over'
    d.clock.advance(0.1)
    ear.onset()                                            # the listener goes on, after the verdict
    assert d.controller.tick(now=d.clock()) == []
    assert ear.heard('что ты сейчас сказал', speech=1.0) == []
    d.clock.advance(EAR_COMMAND_SETTLE_SECONDS)
    assert speaks(d.controller.tick(now=d.clock())) == [] and d.index == AT


def test_a_command_acts_once_the_quiet_after_it_has_lasted(tmp_path):
    d = dictation(tmp_path)
    ear, cloud = Ear(d), Speaker(d)
    ear.onset()
    d.clock.advance(0.3)
    cloud.start()
    assert ear.heard('повтори', speech=0.4, lag=0.1) == []
    d.clock.advance(EAR_COMMAND_SETTLE_SECONDS / 2 - 0.1)
    assert speaks(d.controller.tick(now=d.clock())) == [], 'not before the quiet has lasted'
    d.clock.advance(EAR_COMMAND_SETTLE_SECONDS / 2 + 0.01)
    assert speaks(d.controller.tick(now=d.clock())) == [PORTION], 'the portion is said again once the quiet has lasted'


def test_pieces_further_apart_than_the_join_gap_are_left_to_the_cloud(tmp_path):
    d = dictation(tmp_path)
    ear, cloud = Ear(d), Speaker(d)
    ear.onset()
    d.clock.advance(0.3)
    cloud.start().words('при ста')
    ear.heard('при ста', speech=0.3)
    d.clock.advance(EAR_JOIN_GAP_SECONDS + 0.2)
    assert ear.onset().heard('градусах цельсия', speech=0.6) == [] and d.index == AT


def test_speech_the_ear_could_not_recognize_just_before_stops_it(tmp_path):
    """An utterance whose text never came (dropped by the ear, or failed) may have been «не»: what follows it is the cloud's."""
    d = dictation(tmp_path)
    ear, cloud = Ear(d), Speaker(d)
    ear.onset()                                            # uid 1: heard, never recognized
    d.clock.advance(0.5)
    cloud.start()
    assert ear.onset().heard(SAID, speech=0.9) == [] and d.index == AT


# ====================================================================================================================
# the cloud has not announced the utterance yet
# ====================================================================================================================

@pytest.mark.parametrize('said,cloud_said', [('дальше', 'Дальше.'), (SAID, PORTION)], ids=['next', 'confirmation'])
def test_a_verdict_waits_for_the_cloud_to_announce_the_utterance(tmp_path, said, cloud_said):
    d = dictation(tmp_path)
    ear, cloud = Ear(d), Speaker(d)
    assert ear.says(said, speech=0.6) == [] and d.index == AT, 'no turn of the cloud to take yet'
    d.clock.advance(EAR_COMMAND_SETTLE_SECONDS)
    out = d.controller.provider(H.created('u-live', 'user', ''))
    assert speaks(out) == [d.chunks[AT + 1]] and d.index == AT + 1, 'taken when the cloud announced it'
    cloud.words(cloud_said)
    assert cloud.final() == [] and d.index == AT + 1


def test_a_verdict_the_cloud_never_announces_is_given_up(tmp_path):
    d = dictation(tmp_path)
    ear = Ear(d)
    ear.says('дальше', speech=0.4)
    d.clock.advance(EAR_COMMAND_SETTLE_SECONDS + EAR_BIND_SECONDS + 0.1)
    out = d.controller.tick(now=d.clock())
    assert d.controller.ear_pending is None and d.index == AT
    assert speaks(out) in ([], [PORTION]), 'at most the silence auto-repeat of the same portion, never the next one'
    later = Speaker(d, 'u-later').start()
    assert d.index == AT and later.final('при ста градусах') == [] and d.index == AT, 'a later turn is not that utterance'


def test_new_speech_gives_up_a_verdict_that_waits(tmp_path):
    d = dictation(tmp_path)
    ear = Ear(d)
    ear.says('дальше', speech=0.4)
    d.clock.advance(EAR_JOIN_GAP_SECONDS + 0.5)
    ear.onset()                                            # the listener goes on speaking: the cloud may join the two
    d.controller.provider(H.created('u-live', 'user', ''))
    assert d.index == AT and d.controller.ear_pending is None


# ====================================================================================================================
# the cloud got there first: nothing twice
# ====================================================================================================================

def test_after_the_stable_partial_took_the_utterance_the_ear_does_nothing(tmp_path):
    d = dictation(tmp_path)
    ear, cloud = Ear(d), Speaker(d)
    ear.onset()
    d.clock.advance(0.2)
    cloud.start().words(PORTION)
    assert cloud.wait(ACK_STABLE_SECONDS + TICK) == [d.chunks[AT + 1]] and d.index == AT + 1, 'precondition: the cloud took it'
    assert ear.heard(SAID, speech=0.1) == [] and d.index == AT + 1, 'advanced twice'


def test_after_the_cloud_final_the_ear_does_nothing(tmp_path):
    d = dictation(tmp_path)
    ear, cloud = Ear(d), Speaker(d)
    ear.onset()
    d.clock.advance(0.3)
    cloud.start().words('Повтори')
    assert cloud.final() == [PORTION], 'precondition: the cloud replayed the portion'
    # Fix round 1 (review): the verdict of the ear is not acted on at once when it is a command - it may wait for the quiet to last and
    # for a cloud turn to take. So the quiet lasts here, and another turn of the cloud appears inside the bind window: still no replay.
    first = ear.heard('повтори', speech=0.1) + ear.settle()
    d.clock.advance(0.3)
    later = Speaker(d, 'u-next').start()
    assert speaks(first + later.actions + ear.settle()) == [], 'replayed twice'


def test_a_decision_the_cloud_made_while_the_utterance_was_said_leaves_it_to_the_cloud(tmp_path):
    """The cloud's late final of an earlier utterance («стоп», which the ear misheard) pauses the answer while the listener is already
    saying the portion: the ear's verdict was not said to what is there now."""
    d = dictation(tmp_path)
    ear, earlier = Ear(d), Speaker(d, 'u-0')
    ear.onset()
    d.clock.advance(0.2)
    earlier.start().words('Стоп')
    assert ear.heard('сто', speech=0.3) == []
    d.clock.advance(EAR_JOIN_GAP_SECONDS + 0.3)
    ear.onset()
    d.clock.advance(0.2)
    earlier.final('Стоп.')
    assert d.state.get('paused'), 'precondition: the cloud paused the answer'
    Speaker(d, 'u-1').start().words('при ста')
    assert ear.heard(SAID, speech=0.6) == [] and d.index == AT


# ====================================================================================================================
# own voice and the cue, a disagreeing cloud, a reopened call
# ====================================================================================================================

def test_speech_that_began_before_the_cue_was_over_is_the_clouds(tmp_path):
    d = H.Dictation(tmp_path / 'cue', ANSWER, play_first=False)        # the first cue is in flight
    ear, cloud = Ear(d), Speaker(d)
    d.controller.cue_started(d.cues[0], voiced_seconds=1.0)
    d.clock.advance(0.5)
    ear.onset()                                            # inside the cue: its own sound, or talk-over
    d.clock.advance(0.3)
    cloud.start().words('Вода')
    assert ear.heard('вода кипит', speech=0.5) == [] and d.index == 0


@pytest.mark.parametrize('cloud_heard', ['не при ста', 'при двухстах градусах', 'при двухстах'],
                         ids=['negation', 'other-number', 'other-number-still-growing'])
def test_a_cloud_that_heard_another_number_or_a_negation_is_not_overruled(tmp_path, cloud_heard):
    d = dictation(tmp_path)
    ear, cloud = Ear(d), Speaker(d)
    ear.onset()
    d.clock.advance(0.3)
    cloud.start().words(cloud_heard)
    assert ear.heard(SAID, speech=0.5) == [] and d.index == AT


@pytest.mark.parametrize('cloud_so_far', ['в тысяча девятьсот', 'в 19'], ids=['words', 'digits'])
def test_a_number_the_cloud_is_still_hearing_is_no_disagreement(tmp_path, cloud_so_far):
    """Replay through the controller (S1 bake-off, clean): 23 of 300 correct repeats were left to the cloud only because its words so far
    ended in a number still being said - «в тысяча девятьсот» on the way to «1914», «четыреста двадцать» to «421» (and a partial «1945» is
    «19» for a moment: ``_may_still_grow``). The number at the end of the cloud's growing words disagrees only when it cannot be the start
    of a number of the portion."""
    d = dictation(tmp_path, NUMBER_ANSWER, at=0)
    for n in range(NUMBER_AT):
        assert d.say(d.current, gap=4.0).after == n + 1
    d.clock.advance(4.0)
    # integ9: F1 cuts by meaning, so the portion that ends in a number is the whole sentence «Закон был принят в 1945.» (it was «в 1945.»)
    assert d.current == NUMBER_PORTION, 'precondition: the portion that ends in a number waits'
    ear, cloud = Ear(d), Speaker(d)
    ear.onset()
    d.clock.advance(0.3)
    cloud.start().words(NUMBER_LEAD + cloud_so_far)
    assert speaks(ear.heard(NUMBER_LEAD.casefold() + 'в тысяча девятьсот сорок пять', speech=1.4) + ear.settle()) == [d.chunks[NUMBER_AT + 1]]


def test_a_cloud_turn_announced_before_the_utterance_began_is_not_its_turn(tmp_path):
    """The cloud's open turn holds speech from before (a «не» the ear heard as a separate utterance long before, merged by the cloud)."""
    d = dictation(tmp_path)
    ear, cloud = Ear(d), Speaker(d)
    cloud.start()
    d.clock.advance(EAR_JOIN_GAP_SECONDS + 0.5)
    ear.onset()
    assert ear.heard(SAID, speech=0.6) == [] and d.index == AT


def test_with_the_providers_clock_a_cloud_turn_whose_speech_began_elsewhere_is_not_taken(tmp_path):
    d = dictation(tmp_path)
    ear = Ear(d, input_ms=20_000)
    sent = {'ms': ear.input_ms}
    d.controller.bind_input_clock(lambda: sent['ms'])
    ear.onset()
    d.clock.advance(0.3)
    d.controller.speech_started()
    d.controller.provider(created('u-a', start_ms=20_000 - 2_000))      # its speech began 2 s before the ear heard any
    sent['ms'] = ear.input_ms + 600
    assert ear.heard(SAID, speech=0.6) == [] and d.index == AT


def test_a_reopened_call_is_not_moved_by_the_ear(tmp_path):
    old = dictation(tmp_path)
    d = old.reconnect()                                    # quiet_reopen: nothing issued in this call yet
    d.clock.advance(4.0)
    ear, cloud = Ear(d), Speaker(d)
    ear.onset()
    d.clock.advance(0.3)
    cloud.start().words('при ста')
    assert ear.heard(SAID, speech=0.5) == [] and d.index == AT


# ====================================================================================================================
# the cloud cut the utterance where the ear did not (live 03.11 08:55:28: attempt «…» | stable partial of the rest)
# ====================================================================================================================

def test_a_later_piece_the_cloud_cut_off_is_part_of_what_the_ear_took(tmp_path):
    d = dictation(tmp_path)
    ear, first = Ear(d), Speaker(d, 'u-a')
    ear.onset()
    d.clock.advance(0.3)
    first.start().words('при ста')
    assert speaks(ear.heard(SAID, speech=0.6)) == [d.chunks[AT + 1]]
    assert first.final('При ста') == [] and d.index == AT + 1
    d.clock.advance(0.3)
    second = Speaker(d, 'u-b')
    d.controller.provider(H.created('u-b', 'user', ''))
    assert d.controller.user_boundaries.get('u-b') == 'local_ear_piece', 'the transcript the phone gets says whose piece it is'
    second.words('градусах Цельсия')
    assert second.wait(1.0) == [] and second.final() == [] and d.index == AT + 1, 'the rest of the repeat moved or stopped something'


def test_a_question_in_a_later_piece_is_not_lost(tmp_path):
    """The ear heard only the portion; the cloud cut the turn and its second piece is a question. A piece is a tail of the take, and a
    question in a tail is always acted on."""
    d = dictation(tmp_path)
    ear, first = Ear(d), Speaker(d, 'u-a')
    ear.onset()
    d.clock.advance(0.3)
    first.start().words('при ста')
    ear.heard(SAID, speech=0.6)
    first.final(PORTION)
    d.clock.advance(0.3)
    d.controller.provider(H.created('u-b', 'user', ''))
    out = d.controller.provider(H.done('u-b', 'user', 'А почему при ста?'))
    assert 'cancel' in types(out) and d.controller.question_id == 'u-b', 'the question in the cut-off piece was lost'


def test_when_nothing_waits_the_ear_leaves_it_to_the_cloud(tmp_path):
    """After the last portion was confirmed nothing waits: «повтори» is the cloud's (it says the last portion once more)."""
    d = H.Dictation(tmp_path / 'done', 'Вода кипит.')
    assert d.say(d.current).completed, 'precondition: the answer is over'
    d.clock.advance(4.0)
    ear, cloud = Ear(d), Speaker(d)
    ear.onset()
    d.clock.advance(0.3)
    cloud.start()
    assert speaks(ear.heard('повтори', speech=0.4) + ear.settle()) == [], 'the ear replayed what the cloud is to decide'


def _taken_then_next_repeat(d, *, gap, onset):
    """The ear took the portion; ``gap`` seconds after its end the cloud announces the listener's repeat of the NEXT portion (the ear
    heard that speech begin, or missed it: ``onset``). Returns the actions of that repeat's final."""
    ear, first = Ear(d), Speaker(d, 'u-a')
    ear.onset()
    d.clock.advance(0.3)
    first.start().words('при ста')
    ear.heard(SAID, speech=0.6)
    first.final()
    d.clock.advance(gap)
    if onset:
        ear.onset()
    d.clock.advance(0.3)
    nxt = Speaker(d, 'u-next').start().words(d.current)
    return d.controller.provider(H.done('u-next', 'user', nxt.sent))


def test_a_turn_after_new_speech_is_not_a_piece(tmp_path):
    d = dictation(tmp_path)
    out = _taken_then_next_repeat(d, gap=0.3, onset=True)
    assert d.index == AT + 2 and speaks(out) == [d.chunks[AT + 2]], 'a new repeat was swallowed as a piece of the old utterance'


def test_a_turn_long_after_the_take_is_not_a_piece(tmp_path):
    d = dictation(tmp_path)
    _taken_then_next_repeat(d, gap=2.5, onset=False)            # the ear missed that speech begin
    assert d.index == AT + 2


def test_with_the_providers_clock_a_turn_that_began_after_the_utterance_is_not_a_piece(tmp_path):
    d = dictation(tmp_path)
    ear = Ear(d, input_ms=20_000)
    sent = {'ms': ear.input_ms}
    d.controller.bind_input_clock(lambda: sent['ms'])
    ear.onset()
    d.clock.advance(0.3)
    d.controller.speech_started()
    d.controller.provider(created('u-a', start_ms=20_000))
    ear.heard(SAID, speech=0.6)
    sent['ms'] = ear.input_ms + 400
    assert d.index == AT + 1
    assert d.controller.ear_piece({'role': 'user', 'start_ms': ear.input_ms - 400, 'end_ms': ear.input_ms - 200}), 'a piece of it'
    assert not d.controller.ear_piece({'role': 'user', 'start_ms': ear.input_ms + 200, 'end_ms': ear.input_ms + 400}), \
        'speech that began after the end the ear heard is new speech'


# ====================================================================================================================
# through the wire: the real transport and a real ShadowEar (fake recognizer and detector), mode "act"
# ====================================================================================================================

def packet(tag):
    return bytes([tag % 251, 0]) * 2400


async def _wire_at_the_portion(wire):
    await wire.begin(ANSWER)
    for n in range(AT):
        await wire.user(wire.chunks[n], tid=f'cue-{n}')
    assert wire.index == AT and wire.chunks[AT] == PORTION
    wire.skew += 4.0
    wire.freeze()               # from here on time passes when the test says so: the bounds under test are not the machine's


class _Worker(ear_shadow.EarWorker):
    """The real worker, with its thread known (``_drained``)."""

    def _run(self):
        self.thread = threading.current_thread()
        super()._run()


class _Behind:
    """A job behind the others in the worker's queue, by the sink's contract: when the worker has it, all before it has been done."""
    token = 0

    def __init__(self):
        self.reached = threading.Event()

    def _consumed(self, nbytes):
        self.reached.set()


def _drained(ear):
    """The worker has done all the ear gave it, and its texts wait for the tick. The thread says so; a clock cannot: a thread the machine has not
    scheduled yet is late, not broken. Nor do passes of the tick wait for it: each moves the transport's time, past the bounds under test."""
    behind = _Behind()
    ear.worker.submit(behind, 0, 'audio', b'')
    while not behind.reached.wait(1):
        assert ear.worker.thread.is_alive(), 'the worker thread is gone'


def _ear_on_the_wire(wire, mode, script):
    worker = _Worker(lambda: FakeRecognizer([SAID]))
    assert worker.wait_ready(5)
    wire.socket.ear = ear_shadow.for_call(resolve({'local_ear': mode}), wire.controller, worker=worker,
                                          detector_factory=lambda: ScriptedDetector(script))
    return wire.socket.ear


async def _mic(wire, count):
    pcm = base64.b64encode(packet(1)).decode('ascii')
    for _ in range(count):
        await wire.socket.client({'type': 'input_audio_buffer.append', 'audio': pcm})


def test_through_the_wire_the_ear_acts_on_the_tick_and_a_later_piece_does_not_cut_the_next_cue(tmp_path):
    import asyncio

    async def run(stall=0.0):
        wire = H.Wire(tmp_path / f'wire-{stall}')
        try:
            await _wire_at_the_portion(wire)
            ear = _ear_on_the_wire(wire, 'act', ['onset', 'speech', 'speech', 'end'])
            await _mic(wire, 1)                                                                     # onset
            await wire.socket.provider(H.created('u-a', 'user', ''))
            await wire.socket.provider({'type': 'turn.delta', 'turn_id': 'u-a', 'delta': 'При ста'})
            await _mic(wire, 3)                                                                     # speech, speech, end
            _drained(ear)
            time.sleep(stall)
            await wire.elapse(0.1)                        # the transport's tick polls the ear
            assert wire.index == AT + 1 and wire.synthesized[-1] == wire.chunks[AT + 1], 'the ear acted through the tick'
            await wire.settle()
            cleared = wire.cleared()
            await wire.socket.provider(H.done('u-a', 'user', 'При ста'))
            await wire.socket.provider(H.created('u-b', 'user', ''))                               # the cloud's cut-off rest
            await wire.socket.provider({'type': 'turn.delta', 'turn_id': 'u-b', 'delta': 'градусах Цельсия'})
            await wire.socket.provider(H.done('u-b', 'user', 'градусах Цельсия.'))
            await wire.settle()
            assert wire.cleared() == cleared and wire.index == AT + 1, 'the rest of the repeat cut the next cue'
        finally:
            await wire.close()
    asyncio.run(run())
    asyncio.run(run(stall=EAR_PIECE_SECONDS + 0.1))      # the machine stops for longer than the bound of a piece: the call's time has not passed


def test_through_the_wire_shadow_mode_only_listens(tmp_path):
    import asyncio

    async def run():
        wire = H.Wire(tmp_path / 'wire-shadow')
        try:
            await _wire_at_the_portion(wire)
            ear = _ear_on_the_wire(wire, 'shadow', ['onset', 'speech', 'end'])
            await wire.socket.provider(H.created('u-a', 'user', ''))
            await _mic(wire, 3)
            _drained(ear)
            heard = ear.poll()                            # the record the tick would have taken: polled here, not lost
            assert heard and heard[0]['kind'] == 'ack', 'precondition: the ear heard the repeat'
            await wire.elapse(0.1)
            assert wire.index == AT, 'shadow acted'
        finally:
            await wire.close()
    asyncio.run(run())


def test_an_ear_that_fails_to_act_goes_back_to_shadow_and_the_call_goes_on(tmp_path, monkeypatch):
    import asyncio

    async def run():
        wire = H.Wire(tmp_path / 'wire-broken')
        try:
            await _wire_at_the_portion(wire)
            ear = _ear_on_the_wire(wire, 'act', ['onset', 'speech', 'end'])

            def broken(record):
                raise RuntimeError('ear bug')
            monkeypatch.setattr(wire.controller, 'ear_heard', broken)
            await wire.socket.provider(H.created('u-a', 'user', ''))
            await _mic(wire, 3)
            _drained(ear)
            await wire.elapse(0.1)
            assert ear.acting is False and wire.index == AT
            assert wire.controller.ear_off and wire.controller.ear_pending is None, 'the transport and the controller share one switch'
            await wire.socket.provider(H.done('u-a', 'user', PORTION))
            await wire.settle()
            assert wire.index == AT + 1, 'the cloud final still confirms as before'
        finally:
            await wire.close()
    asyncio.run(run())


# ====================================================================================================================
# Fix round 1 (review of 03.11, two lenses, adversarial verification; probes in the scratchpad rearact_review / earprobe)
# ====================================================================================================================

def _cut_by_the_cloud(d, head, *, ear_heard=SAID):
    """The listener repeats the portion; the cloud cuts the utterance after ``head`` (its turn 'u-a', final: an attempt) and goes on in a
    new turn 'u-b'; the ear heard the utterance whole and takes the open turn 'u-b'. Returns (speaker of 'u-b', what the ear did)."""
    ear = Ear(d)
    ear.onset()
    d.clock.advance(0.3)
    first = Speaker(d, 'u-a')
    first.start().words(head)
    first.wait(0.3)
    d.controller.provider(H.done('u-a', 'user', head))
    second = Speaker(d, 'u-b')
    second.start().words('Цельсия')
    return second, ear.heard(ear_heard, speech=0.3)


@pytest.mark.parametrize('rest,check', [
    ('Цельсия, а почему именно при ста?', 'question'),
    ('Цельсия. Стоп.', 'stop'),
    ('Цельсия, повтори.', 'repeat'),
], ids=['question', 'stop', 'repeat'])
def test_what_follows_the_repeat_is_heard_when_the_cloud_cut_the_utterance(tmp_path, rest, check):
    """Review item 1 (sim5): the take landed on the cloud's LATER piece and its tail was looked for at the start of that piece only: the
    question, «стоп» or «повтори» after the repeat was lost. The tail is now found in the cloud's pieces of the utterance joined."""
    d = dictation(tmp_path)
    second, acted = _cut_by_the_cloud(d, 'При ста градусах')
    assert speaks(acted) == [d.chunks[AT + 1]], 'precondition: the ear confirmed the repeat'
    out = d.controller.provider(H.done('u-b', 'user', rest))
    if check == 'question':
        assert 'cancel' in types(out) and d.controller.question_id == 'u-b', types(out)
    elif check == 'stop':
        assert 'cancel' in types(out) and d.state.get('paused'), types(out)
    else:
        assert speaks(out) == [PORTION] and d.index == AT, 'the portion just said is said again'


def test_an_earlier_open_turn_of_the_utterance_is_taken_too(tmp_path):
    """Review item 1 (sim1; an order of provider events not observed live): two open turns of one utterance when the ear acts - it takes
    the later one and must take the earlier one too, or its final («При ста градусах» = the NEXT portion here) confirms a second time."""
    d = dictation(tmp_path)
    c = d.controller
    sent = {'ms': 20_000}
    c.bind_input_clock(lambda: sent['ms'])
    ear = Ear(d, input_ms=20_000)
    ear.onset()
    ear.input_ms = 21_200
    d.clock.advance(0.3)
    c.speech_started()
    c.provider(created('u-a', start_ms=20_000, end_ms=20_200, text='при'))
    sent['ms'] = 20_600
    d.clock.advance(0.3)
    c.provider({'type': 'turn.delta', 'turn_id': 'u-a', 'delta': ' ста градусах', 'start_ms': 20_200, 'end_ms': 20_800})
    sent['ms'] = 21_200
    d.clock.advance(0.2)
    c.provider(created('u-b', start_ms=21_000, end_ms=21_200, text='Цельсия'))
    assert speaks(ear.heard(SAID, speech=0.3)) == [d.chunks[AT + 1]]
    for _ in range(4):
        d.clock.advance(0.1)
        c.tick(now=d.clock())
    c.provider(H.done('u-a', 'user', 'При ста градусах'))
    c.provider(H.done('u-b', 'user', 'Цельсия.'))
    assert d.index == AT + 1, 'confirmed a second time'


def test_a_negation_the_cloud_heard_in_an_earlier_piece_stops_the_ear(tmp_path):
    """Review item 2 (sim3): the cloud cut «Не при ста | градусах Цельсия» and its first piece (with «не») was final before the ear's verdict;
    the ear misheard «не» as «ну». The cross-check reads the cloud's pieces of the utterance, not only the open turn."""
    d = dictation(tmp_path)
    second, acted = _cut_by_the_cloud(d, 'Не при ста', ear_heard='ну при ста градусах цельсия')
    assert acted == [] and d.index == AT, 'the ear confirmed a negated repeat'


@pytest.mark.parametrize('final', ['Не при ста градусах Цельсия.', 'При двухстах градусах Цельсия.'], ids=['negation', 'other-number'])
def test_a_cloud_final_that_contradicts_the_ears_confirmation_takes_it_back(tmp_path, final):
    """Review item 2 (sim3 S4): the ear confirmed, the cloud had heard nothing yet; its final says «не» / another number. The step is taken
    back - the cloud-alone outcome: the portion still waits, the next cue is cancelled."""
    d = dictation(tmp_path)
    ear, cloud = Ear(d), Speaker(d)
    ear.onset()
    d.clock.advance(0.3)
    cloud.start()
    assert speaks(ear.heard(SAID, speech=0.6)) == [d.chunks[AT + 1]], 'precondition: the ear confirmed'
    out = d.controller.provider(H.done('u-live', 'user', final))
    assert d.index == AT and 'cancel' in types(out) and speaks(out) == [], types(out)


def test_a_cloud_final_with_another_year_takes_the_ears_confirmation_back(tmp_path):
    """Review item 2 (sim3 S4): «в 1945.» waits; the ear misheard «…сорок четыре» as «…сорок пять», the cloud's words were still growing
    («в тысяча девятьсот») when it confirmed; the cloud's final says 1944."""
    d = dictation(tmp_path, NUMBER_ANSWER, at=0)
    for n in range(NUMBER_AT):
        assert d.say(d.current, gap=4.0).after == n + 1
    d.clock.advance(4.0)
    assert d.current == NUMBER_PORTION, 'precondition: the portion that ends in a number waits'
    ear, cloud = Ear(d), Speaker(d)
    ear.onset()
    d.clock.advance(0.3)
    cloud.start().words(NUMBER_LEAD + 'в тысяча девятьсот')
    assert speaks(ear.heard(NUMBER_LEAD.casefold() + 'в тысяча девятьсот сорок пять', speech=1.4) + ear.settle()) == [d.chunks[NUMBER_AT + 1]],         'precondition'
    cloud.words('сорок четыре')
    out = d.controller.provider(H.done('u-live', 'user', NUMBER_LEAD + 'в 1944.'))
    assert d.index == NUMBER_AT and 'cancel' in types(out) and speaks(out) == []


def test_a_cloud_final_that_agrees_keeps_the_ears_confirmation(tmp_path):
    d = dictation(tmp_path)
    ear, cloud = Ear(d), Speaker(d)
    ear.onset()
    d.clock.advance(0.3)
    cloud.start()
    ear.heard(SAID, speech=0.6)
    out = d.controller.provider(H.done('u-live', 'user', 'При 100 градусах Цельсия.'))
    assert d.index == AT + 1 and out == []


TWENTY = 'Ему было 20. Потом он уехал в другой город.'


def test_a_portion_ending_in_a_number_waits_for_the_quiet_after_it(tmp_path):
    """Review item 3 (earprobe test_wrong_number_with_a_pause_inside_it): «Ему было 20.» waits; the listener says «ему было двадцать…
    пять» with a pause inside the number. The confirmation of a portion that ends in a number (a number can still grow, as for the stable
    partial: ``_may_still_grow``) waits for the quiet like a command; speech meanwhile joins it: 25 is not 20."""
    d = H.Dictation(tmp_path / 'num', TWENTY)
    d.clock.advance(4.0)
    assert d.current == 'Ему было 20.', 'precondition'
    ear, cloud = Ear(d), Speaker(d)
    ear.onset()
    d.clock.advance(0.3)
    cloud.start().words('Ему было')
    assert ear.heard('ему было двадцать', speech=0.6, lag=0.1) == [], 'confirmed a number that was still being said'
    d.clock.advance(0.1)
    ear.onset()
    assert d.controller.tick(now=d.clock()) == []
    assert ear.heard('пять', speech=0.3) == [] and d.index == 0
    d.clock.advance(EAR_COMMAND_SETTLE_SECONDS)
    assert speaks(d.controller.tick(now=d.clock())) == [] and d.index == 0


def test_a_portion_ending_in_a_number_is_confirmed_once_the_quiet_has_lasted(tmp_path):
    d = H.Dictation(tmp_path / 'num2', TWENTY)
    d.clock.advance(4.0)
    ear, cloud = Ear(d), Speaker(d)
    ear.onset()
    d.clock.advance(0.3)
    cloud.start().words('Ему было')
    assert ear.heard('ему было двадцать', speech=0.6, lag=0.1) == []
    assert speaks(ear.settle()) == [d.chunks[1]] and d.index == 1


def _broken(*args, **kwargs):
    raise RuntimeError('a bug in the ear')


def test_a_failure_of_the_ear_on_the_providers_path_leaves_the_call_to_the_cloud(tmp_path, monkeypatch):
    """Review item 4 (earprobe test_probe_isolation2): a waiting verdict binds when the cloud announces the utterance; a bug in the take
    escaped ControlledMedia.provider and ended the call. Now the ear is switched off (once), and the cloud's final confirms as before."""
    d = dictation(tmp_path)
    c = d.controller
    ear = Ear(d)
    assert ear.says(SAID, speech=0.6) == [] and c.ear_pending is not None, 'precondition: the verdict waits'
    monkeypatch.setattr(c, '_ear_take', _broken)
    c.provider(H.created('u-live', 'user', ''))
    assert c.ear_off and c.ear_pending is None and c.ear_take is None
    c.provider({'type': 'turn.delta', 'turn_id': 'u-live', 'delta': PORTION})
    out = c.provider(H.done('u-live', 'user', PORTION))
    assert speaks(out) == [d.chunks[AT + 1]] and d.index == AT + 1, 'the cloud final confirms as before'


def test_a_failure_of_the_ear_on_the_tick_leaves_the_rest_of_the_tick(tmp_path, monkeypatch):
    d = dictation(tmp_path)
    c = d.controller
    ear, cloud = Ear(d), Speaker(d)
    ear.onset()
    d.clock.advance(0.3)
    cloud.start()
    assert ear.heard('стоп', speech=0.4) == [] and c.ear_pending is not None
    monkeypatch.setattr(c, '_ear_take', _broken)
    d.clock.advance(EAR_COMMAND_SETTLE_SECONDS)
    assert c.tick(now=d.clock()) == [] and c.ear_off


def test_once_the_ear_is_off_it_does_nothing_more(tmp_path, monkeypatch, caplog):
    d = dictation(tmp_path)
    c = d.controller
    monkeypatch.setattr(c, '_ear_mark', _broken)
    ear, cloud = Ear(d), Speaker(d)
    with caplog.at_level(logging.WARNING, logger='echo-sync'):
        ear.onset()                                        # the bug: the ear is switched off here
        monkeypatch.undo()
        d.clock.advance(0.3)
        cloud.start().words('при ста')
        assert ear.heard(SAID, speech=0.5) == [] and ear.settle() == [] and d.index == AT
        assert ear.says(SAID, speech=0.5) == [] and c.ear_piece({'role': 'user'}) is False
    assert c.ear_off and len([r for r in caplog.records if 'ear act=off' in r.getMessage()]) == 1, 'switched off and logged once'


def test_a_different_command_after_the_one_the_ear_took_acts(tmp_path):
    """Review item 5 (sim2): «Подожди. … Повтори ещё раз.» in one turn of the cloud; the ear paused on «подожди»; the request to hear the
    portion again in the rest of the turn was dropped (the answer stayed paused). The cloud alone replays the portion here."""
    d = dictation(tmp_path)
    ear, cloud = Ear(d), Speaker(d)
    ear.onset()
    d.clock.advance(0.3)
    cloud.start()
    assert 'cancel' in types(ear.heard('подожди', speech=0.4) + ear.settle()) and d.state.get('paused'), 'precondition: paused'
    cloud.words('Подожди. Повтори ещё раз.')
    out = d.controller.provider(H.done('u-live', 'user', 'Подожди. Повтори ещё раз.'))
    assert speaks(out) == [PORTION], types(out)


def test_the_final_of_an_earlier_piece_of_the_take_is_not_a_tail(tmp_path):
    """Fix round 1, item 1: the cloud's earlier open piece of the utterance the ear took ('head') holds words said BEFORE the portion
    («Стоп, при ста…» would be acted on as if said after it): its final is the take's own words, never classified again."""
    d = dictation(tmp_path)
    c = d.controller
    before = c.state()
    c.speech_started()
    c.provider(H.created('u-head', 'user', ''))
    c._note_early('u-head', before, 'ack', piece='head', ear={'earlier': []})
    c.seen.add('u-head')
    assert c.provider(H.done('u-head', 'user', 'Стоп.')) == [] and not d.state.get('paused')


def test_a_failure_leaves_nothing_of_the_ear_waiting(tmp_path, monkeypatch):
    """Fix round 1, item 4: the switch clears what the ear has waiting - a verdict that waits for the cloud when the next onset fails."""
    d = dictation(tmp_path)
    c = d.controller
    ear = Ear(d)
    assert ear.says(SAID, speech=0.6) == [] and c.ear_pending is not None, 'precondition: a verdict waits'
    monkeypatch.setattr(c, '_ear_mark', _broken)
    ear.onset()
    assert c.ear_off and c.ear_pending is None and c.ear_take is None
