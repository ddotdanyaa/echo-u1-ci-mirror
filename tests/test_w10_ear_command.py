"""w10 item 11 (w8-donors N74): «стоп» on the ear's text so far, behind ``ear_command_early`` (off), through the partials of the ear (``ShadowEar.partials``)."""
import helpers_s6_state as S
from echo_sync.settings import resolve
from test_h3_tempo import TICK, call       # noqa: F401 - call is the fixture
from test_h4_ear_first import slow
from test_h5_live import LIVE
from test_h6 import plan_in_flight


def stopping(call, flag):
    rig = call(**LIVE, ear_command_early=flag)
    slow(rig)
    plan_in_flight(rig)
    uid = rig.onset()
    rig.pump(0.3)
    rig.ear.partials.append({'uid': uid, 'text': 'стоп', 'decode_ms': 30})
    rig.pump(2 * TICK)
    return rig, uid


def test_the_flag_needs_the_channel_and_an_acting_ear():
    assert resolve({})['ear_command_early'] == 'off' and resolve({'ear_command_early': 'on'})['ear_command_early'] == 'off'
    assert resolve({'ear_command_early': 'on', 'fast_text': 'on', 'local_ear': 'act'})['ear_command_early'] == 'on'


def test_on_a_stop_in_the_ears_partial_pauses_the_plan_before_the_end_of_speech(call):
    rig, uid = stopping(call, 'on')
    assert rig.ear.partial_ms and rig.ear.current == uid, 'still speaking'
    assert rig.c.state().get('paused') is True


def test_off_the_partial_does_nothing(call):
    rig, uid = stopping(call, 'off')
    assert not rig.c.state().get('paused')


def test_the_final_of_the_same_utterance_stops_nothing_twice(call, caplog):
    import logging
    with caplog.at_level(logging.INFO, logger='echo-sync'):
        rig, uid = stopping(call, 'on')
        rig.offset()
        rig.pump(0.6)
        rig.w.feed(S.turn_created('u1', 'user', ''))
        rig.w.feed(S.turn_done('u1', 'user', 'Стоп'))
        rig.pump(1.0)
    assert rig.c.state().get('paused') is True
    assert sum('reason=local_ear_stop' in r.getMessage() for r in caplog.records) == 1


def test_a_stop_word_of_the_cue_itself_is_no_early_stop(call):
    rig = call(**LIVE, ear_command_early='on')
    slow(rig)
    plan_in_flight(rig, answer='Стоп, это знак. Стоп-лист ведёт менеджер.')
    uid = rig.onset()
    rig.ear.partials.append({'uid': uid, 'text': 'стоп', 'decode_ms': 30})
    rig.pump(2 * TICK)
    assert not rig.c.state().get('paused')


class _Gate:
    def __init__(self, kind):
        self.kind = kind

    def verdict(self):
        return type('V', (), {'kind': self.kind, 'conf': 1.0})()

    def releases(self, cue):return False

    def other_speaking(self):return False

    def cuts_playing(self):return True

    def is_other_utterance(self, rec):return False


def _gated(call, kind):
    rig = call(**LIVE, ear_command_early='on')
    slow(rig)
    plan_in_flight(rig)
    if kind:rig.c.speaker_gate = _Gate(kind)
    uid = rig.onset()
    rig.pump(0.3)
    rig.ear.partials.append({'uid': uid, 'text': 'стоп', 'decode_ms': 30})
    rig.pump(2 * TICK)
    return rig


def test_f4_a_stop_in_somebody_elses_voice_or_in_noise_is_no_early_stop(call):
    assert _gated(call, 'other').c.state().get('paused') is not True
    assert _gated(call, 'quiet').c.state().get('paused') is not True


def test_f4_the_own_or_unknown_voice_still_stops_early(call):
    assert _gated(call, 'own').c.state().get('paused') is True
    assert _gated(call, 'unknown').c.state().get('paused') is True
    assert _gated(call, None).c.state().get('paused') is True
