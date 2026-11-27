"""c22: the tools of the stand - the map of stages, the two new chaos faults, ddmin."""
from tools.replay import chaos, c22_stages, ddmin


def test_map_of_stages_is_sound():
    assert c22_stages.check() == []
    assert c22_stages.counts()['stages'] >= 30


def test_new_faults_are_in_the_table_and_have_a_cause():
    for fault in ('open_down', 'cloud_flicker'):
        assert fault in chaos.FAULTS and fault in chaos.CAUSES


def test_open_down_the_call_comes_back_and_later_questions_are_answered():
    out = chaos.run(0, 'open_down', 2)
    assert chaos.first(out) is None, out.violations
    assert any(e['error']['code'] == 'controlled_upstream_unavailable' for e in out.errors)      # the open really failed once
    assert len(out.reconnects) >= 2


def test_cloud_flicker_survives():
    out = chaos.run(1, 'cloud_flicker', 2)
    assert chaos.first(out) is None, out.violations


def test_ddmin_finds_the_one_failing_item():
    calls = []

    def test(items):
        calls.append(len(items))
        return 3 in items and 7 in items
    assert sorted(ddmin.ddmin(list(range(12)), test)) == [3, 7]
    assert len(calls) < 60


def test_a_scene_repeats_from_its_moves():
    stand, out = ddmin._play(ddmin.Recorder, 6, 40.0, True)
    again = ddmin.play_scene(6, stand.moves, 40.0, True)
    assert [v[0] for v in again.violations] == [v[0] for v in out.violations]
    assert [s.text for s in again.said] == [s.text for s in out.said]
