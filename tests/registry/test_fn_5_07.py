"""Registry 5.07 «Остановка и перебивание». Registry state: СЛОМАНО в части голоса; `stop_in_flight=on` проверено тестом.

Stand: test_h3_tempo.Rig (real ControlledMedia + NativeMediaSocket + real ShadowEar on a scripted detector/recognizer + real fast_text on a scripted job stream),
profile as the live server gives it (settings file via ECHO_REPLAY_PROFILE, which is how the Rig sets the host's attributes, stop_in_flight among them).
Proved on the server side: speech of the listener or a spoken «стоп» over a sounding cue cuts it (clear frame, the portion is not finished); «стоп» said while the
answer is still on its way (no portion yet) cancels the job and no cue follows (stop_in_flight); a spoken stop keeps the plan away; the phone's button cuts the sound.
NOT proved here (client): the phone sends no microphone during a cue, so the voice never arrives: recipe in registry_proof/5.07.json.
Strict xfail: after the button (response.cancel) the cut portion comes back by the timer (registry R-46, E26.2).
Dummy check: stop_in_flight=off in the settings file (the stop-in-flight test must go red).
"""
import json

import pytest

import helpers_s6_state as S
from test_h1_fast_text import settled
from test_h3_tempo import TICK, Rig, in_flight

# live server values (Appendix A); the code defaults differ: stop_in_flight off, repeat_seconds 6.0, local_ear/ear_release off
LIVE = {'fast_text': 'on', 'local_ear': 'act', 'ear_release': 'on', 'max_auto_repeats': 3, 'repeat_seconds': 2.0, 'stop_in_flight': 'on'}
ASKED = 'Что такое инерция'
ANSWER = 'Срок уведомления две недели. Это статья восемьдесят.'


@pytest.fixture
def make(monkeypatch, tmp_path):
    rigs = []

    def build(**keys):
        path = tmp_path / 'profile.json'
        path.write_text(json.dumps({**LIVE, **keys}), encoding='utf-8')
        monkeypatch.setenv('ECHO_REPLAY_PROFILE', str(path))
        rigs.append(Rig(monkeypatch))
        return rigs[-1]
    yield build
    for rig in rigs:
        # g36 (the owner's rule, always on): a cloud that says nothing for CLOUD_DEAF_S after speech is told once (the stalled notice); this rig's cloud is silent on purpose, the ear acts alone
        failures = [e for e in rig.w.errors if e.get('error', {}).get('code') != 'controlled_upstream_stalled']
        assert rig.w.violations == [] and failures == [], (rig.w.violations, rig.w.errors)
        rig.close()


async def long_voice(text, end=None):
    """20 s of voiced sound in 20 ms frames, paced in virtual time: long enough to be cut half way."""
    return b'\x00\x40' * 480 * 1000


def ask(rig):
    rig.w.feed(S.turn_created('u0', 'user', 'Что'))
    rig.w.feed(S.turn_done('u0', 'user', ASKED))


def playing(rig):
    """The first cue of a two-portion answer is in flight: a few frames out, the rest still to go."""
    rig.w.wire.synthesize = long_voice
    ask(rig)
    rig.job_says(0, ANSWER)
    rig.fake.run(0).finish()
    settled(rig.fast)
    return in_flight(rig)


def test_the_listener_starting_to_speak_cuts_the_cue(make):
    rig = make()
    cue = playing(rig)
    rig.w.feed({'type': 'input_audio_buffer.speech_started'})      # the cloud's voice detector hears the listener begin
    assert cue.cleared and not cue.done and cue.audio_frames < 1000, 'the portion is cut, not played to its end'


def test_a_spoken_stop_over_a_cue_cuts_it_and_the_plan_does_not_return(make):
    rig = make()
    cue = playing(rig)
    rig.says('Стоп', speech=0.3)
    assert cue.cleared and not cue.done
    said = len(rig.said())
    rig.pump(60.0)
    assert len(rig.said()) == said, 'nothing is said by itself after «стоп»'


def test_the_cloud_final_stop_with_the_mic_shut_also_stops_for_good(make):
    rig = make()
    cue = playing(rig)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.w.feed(S.turn_done('u1', 'user', 'Стоп'))
    rig.pump(TICK * 2)
    said = len(rig.said())
    rig.pump(60.0)
    assert cue.cleared and len(rig.said()) == said


def test_stop_while_the_answer_is_on_its_way_cancels_it(make):
    """A «стоп» heard by the ear before any portion exists: the job is cancelled and nothing is said after it."""
    rig = make()
    ask(rig)
    rig.pump(0.5)
    rig.says('Стоп')
    rig.pump(0.5)
    assert rig.fake.run(0).cancelled.is_set(), 'the request to the model was cancelled'
    rig.pump(5.0)
    assert rig.said() == []


def test_the_phone_button_cuts_the_sound(make):
    rig = make()
    cue = playing(rig)
    rig.w.client({'type': 'response.cancel'})
    assert cue.cleared and not cue.done


@pytest.mark.xfail(strict=True, reason='реестр 5.07: СЛОМАНО; запасная кнопка (response.cancel) режет звук, но срезанная порция возвращается по таймеру (Р-46, E26.2)')
def test_after_the_button_the_plan_does_not_come_back_by_itself(make):
    rig = make()
    playing(rig)
    rig.w.client({'type': 'response.cancel'})
    said = len(rig.said())
    rig.pump(60.0)
    assert len(rig.said()) == said, rig.said()
