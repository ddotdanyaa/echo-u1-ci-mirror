"""W9-arch (N157-N169): what the listener hears when a part of the call dies. The real chain (ControlledMedia + EchoEngine + SQLite ->
NativeMediaSocket, and with the ear and the brain the rig of H3), fakes only at the boundary: the cloud's events, SAPI, the lookup, the ear's
detector and recognizer, the brain's stream. Virtual time: a number of seconds here is the logic's, not a measurement of a phone.

Each W9-A* is ``xfail(strict=True)`` (A2 is no defect: see test_map_a_dead_voice_…): the system is silent where it must not be. The patch of cloud_context/reports/w9-arch.patch turns each
green (checked on a copy, the report says how); then the marker goes. The rest pins the map of cloud_context/reports/w9-arch.md as it is now.
"""
from cm_patch import patch_controller
import pytest

import helpers_s6_fault as F
import helpers_s6_state as S
from echo_sync import controlled_media
from echo_sync.fast_text import FIRST_TEXT_S
from echo_sync.reserve_text import ALL_DEAD_S
from test_h3_tempo import TICK, call       # noqa: F401 - call is the fixture
from test_h1_fast_text import until
from test_s6_fault_injection import assert_audible, run_wire

DEFECTS = {
    1: 'GPT-Live stops sending events (helper open, no X, no error): the question is never answered and nothing is said, for ever',
}


pytestmark = pytest.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)


def defect(number):
    return pytest.mark.xfail(strict=True, raises=AssertionError, reason=f'W9-A{number}: {DEFECTS[number]}')


CLOUD_DEAF_S = 15.0          # the bound the patch uses (echo_sync/arch_liveness.py); off on the base
QUESTION = 'Что такое инерция?'
ANSWER = 'Инерция — это свойство тела сохранять скорость.'


# =====================================================================================================================================
# 1. the defects: silence or a hang
# =====================================================================================================================================

# w10 item 3: the patch is applied (CLOUD_DEAF_S=0 by default, the test turns it on): no longer a defect
def test_w9_a1_a_cloud_that_stops_answering_is_told_to_the_listener(tmp_path, monkeypatch):
    """N158/N163: the cloud heard the listener begin (its user turn.created) and is never heard of again. Nobody else knows: the answer watchdog
    counts from a final that never comes, the helper is open. The listener must hear that the channel is gone, once, within a bound."""
    from echo_sync import native_media_socket
    monkeypatch.setattr(native_media_socket, 'CLOUD_DEAF_S', CLOUD_DEAF_S, raising=False)       # the patch's switch; off on the base

    async def body(rig):
        t0 = rig.now()
        await rig.feed(F.created('u1', 'user', 'Что'))
        await rig.advance(CLOUD_DEAF_S + 10)
        assert_audible(rig, t0, 'a deaf cloud', CLOUD_DEAF_S + 5)
        assert 'controlled_upstream_stalled' in rig.errors(t0), rig.timeline()
        await rig.advance(60)
        assert rig.errors(t0).count('controlled_upstream_stalled') == 1, 'once, not every 15 s'
    run_wire(tmp_path, monkeypatch, body)


def ask_and_cloud_answers(rig, after=1.0):
    t0 = rig.w.clock.t
    rig.w.feed(S.turn_created('u1', 'user', 'Что'))
    rig.w.feed(S.turn_done('u1', 'user', QUESTION))
    rig.pump(after)
    rig.w.feed(S.turn_created('a1', 'assistant', ANSWER))
    rig.w.feed(S.turn_done('a1', 'assistant', ANSWER))
    count = len(rig.cues())
    while rig.w.clock.t - t0 < 30 and len(rig.cues()) == count:
        rig.pump(TICK)
    return rig.w.clock.t - t0 if len(rig.cues()) > count or count else None


# w9_a3 (a hung brain holds a ready cloud answer one timeout only) guarded the dead switch ``fast_cloud_first``; the live rule is ``Roads`` + ``fast_text._cloud_answer`` (tests/test_roads_channel.py: test_with_the_cloud_answer_the_guard_says_no_refusal_at_eight_seconds_...)


# =====================================================================================================================================
# 2. the map as it is: who speaks and after how long (the numbers of the table in the report)
# =====================================================================================================================================

def test_map_a_hung_brain_costs_the_give_up_time_of_the_roads_now(call):
    rig = call(ear='shadow', fast_text='on')
    first = ask_and_cloud_answers(rig)
    assert ALL_DEAD_S <= first <= ALL_DEAD_S + 0.6, first      # one road, one wait: the roads give the question back at ALL_DEAD_S (the cloud has its answer) and it is not asked again (the retry of the controller is off)
    assert len(rig.fake.runs) == 1, 'asked once'


def test_map_a_brain_that_refuses_at_once_costs_nothing(call):
    rig = call(ear='shadow', fast_text='on')
    t0 = rig.w.clock.t
    rig.w.feed(S.turn_created('u1', 'user', 'Что'))
    rig.w.feed(S.turn_done('u1', 'user', QUESTION))
    rig.pump(0.2)
    rig.fake.run(0).fail()
    rig.fake.run(1).fail()      # the one road: a road that refuses at once is followed by the next road (the rig's second one); both refuse: nothing is left of the brain
    assert until(lambda: rig.fast.job is None or rig.fast.job.outcome is not None)      # fix4: the job's thread has met the refusal before virtual time runs on (a loaded runner, 18b27a3)
    rig.pump(0.8)
    rig.w.feed(S.turn_created('a1', 'assistant', ANSWER))
    rig.w.feed(S.turn_done('a1', 'assistant', ANSWER))
    rig.pump(TICK * 2)
    assert rig.cues() and rig.cues()[0].t - t0 <= 1.3, 'the cloud answers as without the brain'


def test_map_without_the_brain_the_cloud_answer_is_cued_at_once(call):
    rig = call(ear='shadow', fast_text='off')
    t0 = rig.w.clock.t
    rig.w.feed(S.turn_created('u1', 'user', 'Что'))
    rig.w.feed(S.turn_done('u1', 'user', QUESTION))
    rig.pump(1.0)
    rig.w.feed(S.turn_created('a1', 'assistant', ANSWER))
    rig.w.feed(S.turn_done('a1', 'assistant', ANSWER))
    rig.pump(TICK * 2)
    assert rig.cues() and rig.cues()[0].t - t0 <= 1.3


EAR_QUESTION = 'в каком году было крещение руси'
EAR_ANSWER = 'Крещение Руси произошло в 988 году.'


def ear_asks_into_a_deaf_cloud(rig):
    """The listener asks; the ear hears it all; the cloud sends nothing at all. Returns (when the job was asked, when the first cue began), from the end of the speech."""
    ended = rig.says(EAR_QUESTION, speech=1.5)
    asked = None
    while rig.w.clock.t - ended < 10 and not rig.fake.runs:
        rig.pump(TICK)
    if rig.fake.runs:
        asked = rig.w.clock.t - ended
        n = len(rig.fake.runs) - 1
        rig.job_says(n, EAR_ANSWER)
        rig.job_ends(n)
    while rig.w.clock.t - ended < 20 and not rig.cues():
        rig.pump(TICK)
    return asked, (rig.cues()[0].t - ended if rig.cues() else None)


def test_map_a_deaf_cloud_with_an_acting_ear_and_the_brain_is_answered_by_them(call):
    """N158, what works without GPT-Live: the ear's text stands in for the final after EAR_FINAL_SECONDS (H6 item 6) and the brain answers."""
    asked, cue = ear_asks_into_a_deaf_cloud(call(fast_text='on'))
    assert asked is not None and asked < 1.0, 'the job was prepared on the ear at once'
    assert cue is not None and controlled_media.EAR_FINAL_SECONDS <= cue <= controlled_media.EAR_FINAL_SECONDS + 1.0, cue


def test_map_a_deaf_cloud_with_a_shadow_ear_is_silence(call):
    """... and in shadow the same ear and brain have the answer ready and nobody lets it go: silence (W9-A1 is what tells it)."""
    asked, cue = ear_asks_into_a_deaf_cloud(call(ear='shadow', fast_text='on'))
    assert asked is not None and cue is None


def test_map_the_reference_base_failing_sends_the_question_the_usual_way(tmp_path, monkeypatch):
    """N159: the base raises: logged, and the cloud's answer is cued as without it."""
    def broken(*a, **k):
        raise RuntimeError('base file is gone')
    patch_controller(monkeypatch, 'reference_lookup', broken)

    async def body(rig):
        t0 = rig.now()
        await rig.ask_direct()
        await rig.advance(3)
        assert_audible(rig, t0, 'base broken', 3)
    run_wire(tmp_path, monkeypatch, body)


def test_map_a_dead_voice_tells_a_repeat_only_after_ten_seconds(tmp_path, monkeypatch):
    """N164: SAPI raises on every cue. The first question hears «Ошибка звука. Повторите.»; a repeat 5 s later hears nothing at all (the phrase is
    rate-limited, DIAGNOSTIC_MIN_INTERVAL_S, and nothing is tried again): by design, test_spoken_diagnostics pins «at most one phrase per 10 s,
    none on its own». A repeat after the 10 s hears the phrase again."""
    async def body(rig):
        await rig.ask_direct()
        await rig.advance(5)
        assert rig.completed(), 'precondition: the first question was told'
        t1 = rig.now()
        await rig.ask_direct(F.OTHER_DIRECT_QUESTION, F.OTHER_DIRECT_ANSWER)
        await rig.advance(30)
        assert not rig.audio(t1) and rig.errors(t1) == ['controlled_synthesis_failed']
        t2 = rig.now()
        await rig.ask_direct()
        await rig.advance(5)
        assert_audible(rig, t2, 'a repeat after the window', 5)
    run_wire(tmp_path, monkeypatch, body, synth=['raise'])
