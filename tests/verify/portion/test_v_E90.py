"""V4 E90: the two rests of 01 §5. (H4) ``_ear_turn`` answers ``turn_elsewhere`` on the phone's order of events (the ear's text first, the cloud's turn seconds after the onset, its final later). (H3) a profile that
states ``repeat_seconds`` switches off rule 2 of the tempo (the wait of the silent repeat): the release profile names none, so the tempo rule stands.

Real ControlledMedia, NativeMediaSocket, ShadowEar and FastText (rig ``call``). Not run on the laptop. A red test is a defect card for the family K (``_ear_turn``) or T (the terms).
"""
import pytest

import helpers_s6_state as S
from echo_sync.settings import resolve
from portion_kit import GRID, LIVE_RULES, TEMPO_REPEAT_SECONDS, TEMPO_STEP_SECONDS, TICK, call, plan, spoken_failures      # noqa: F401 - call is the fixture


def test_the_release_profile_names_no_repeat_seconds_and_the_tempo_rule_stands():
    for profile in ({'local_ear': 'act', 'fast_text': 'on'}, {'local_ear': 'act'}):
        assert 'repeat_seconds' not in profile
        assert resolve(profile)['repeat_seconds'] == TEMPO_REPEAT_SECONDS


def test_the_phone_order_of_an_ear_turn_does_not_answer_turn_elsewhere(call):
    rig = call(**LIVE_RULES)
    plan(rig, asked='Что такое инерция', answer='Инерция — свойство тела.')
    rig.pump(1.0)
    uid = rig.onset()
    rig.pump(0.6)
    rig.offset()
    rig.pump(0.15)
    rig.worker.heard(uid, 'а какая столица австралии')
    rig.pump(3.0)
    rig.w.feed(S.turn_created('u5', 'user', ''))
    rig.pump(0.7)
    rig.w.feed(S.turn_done('u5', 'user', 'А какая столица Австралии?'))
    rig.pump(0.5)
    n = len(rig.fake.runs) - 1
    rig.job_says(n, 'Канберра.')
    rig.job_ends(n)
    rig.pump(2.0)
    assert 'Канберра.' in rig.said() and not spoken_failures(rig), rig.said()


def test_with_the_tempo_rule_the_first_silent_repeat_waits_about_two_seconds_and_each_next_one_longer(call):
    rig = call(**LIVE_RULES)
    end = plan(rig)
    first = rig.next_cue(TEMPO_REPEAT_SECONDS + 1.0)
    assert first is not None and first.t - end == pytest.approx(TEMPO_REPEAT_SECONDS, abs=GRID + 0.5), f'first repeat after {first and first.t - end}'
    after_first = rig.ended()
    second = rig.next_cue(TEMPO_REPEAT_SECONDS + TEMPO_STEP_SECONDS + 1.5)
    assert second is not None and second.t - after_first >= TEMPO_REPEAT_SECONDS + TEMPO_STEP_SECONDS - GRID, 'rule 2: each repeat waits more'


def test_a_profile_that_names_its_wait_keeps_it_the_tempo_rule_does_not_act(call):
    rig = call(**LIVE_RULES, repeat_seconds=6.0)
    end = plan(rig)
    assert rig.next_cue(5.0) is None, 'no repeat before the wait the profile named'
    cue = rig.next_cue(1.5)
    assert cue is not None and cue.t - end == pytest.approx(6.0, abs=GRID + 0.3)
