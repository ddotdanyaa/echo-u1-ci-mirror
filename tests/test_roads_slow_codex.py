"""The triple coincidence (ALWAYS_ANSWER_REPORT §9): a slow but correct first road (Codex), a hanging reserve host and a dead Gemini. ``Roads.step`` frees a place for a next road by
letting go a walker silent ``2 * NEXT_ROAD_S``; that must be a silent RESERVE walker, never the first road: its answer, though late, is the one that is correct, and it lives to the time to give up.
Through ``FastText`` over the real ``Roads`` with the scripted roads of ``test_roads_channel`` and a clock the test drives."""
import time

import pytest

from echo_sync import reserve_text
from echo_sync.reserve_text import PRIMARY, ReserveError
from test_roads_channel import ANSWER, GEM, T0, _fresh, at_time, channel, drain, fail, flying, kinds, open_question, scene, tick  # noqa: F401 - the fixtures are the harness of the roads

@pytest.mark.parametrize('cloud', [False, True])
def test_a_slow_but_correct_first_road_is_not_let_go_for_a_reserve_road_that_is_silent_too(scene, cloud):
    """Codex's first word comes at 5 s, the Groq host hangs on every road, Gemini refuses: the places are freed by the silent RESERVE walkers, never by the first road
    (it lives to the time to give up), so the answer heard is Codex's and it is not given a stall."""
    fast, clock = channel(scene, cloud=cloud)
    scene.plan(PRIMARY, at_time(clock, T0 + 5.0))
    scene.plan(GEM, fail(ReserveError('http_429')))      # Groq: no plan left, every road of it hangs
    assert open_question(fast) == 'started'
    events = tick(fast, clock, T0 + 7.0)
    texted = [e for e in events if e['kind'] == 'text' and not e.get('provisional')]
    assert texted and texted[0]['text'] == ANSWER and texted[0]['at'] >= 5.0, events
    assert 'failed' not in kinds(events) and scene.asked.count(PRIMARY) == 1 and not scene.cancelled[0].is_set(), (scene.asked, events)
    assert reserve_text._PRIMARY['until'] == 0.0 and not fast.roads._stalls.get(PRIMARY)      # no stall of the first road, no rest
    assert len([road for road in scene.asked if road != PRIMARY]) >= 1      # the reserve was asked while it waited
    events += [] if 'done' in kinds(events) else drain(fast)
    assert 'done' in kinds(events) and fast._spent is None


def test_two_walkers_fly_at_most_when_the_first_road_waits_for_the_silent_reserve_to_be_let_go(scene):
    fast, clock = channel(scene, cloud=False)
    scene.plan(PRIMARY, at_time(clock, T0 + 9.0))
    scene.plan(GEM, fail(ReserveError('http_429')))
    assert open_question(fast) == 'started'
    most = 0
    while clock.t < T0 + 8.0:
        clock.t = round(clock.t + 0.1, 6)
        fast.poll()
        most = max(most, len(flying(fast)))
        time.sleep(0.004)
    assert 1 <= most <= 2
    assert not scene.cancelled[0].is_set()      # the first road is still asked at 8 s: the sentence is the controller's to say, not a reason to cancel it
