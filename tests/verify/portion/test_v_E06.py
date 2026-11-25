"""V4 E06: the early release of the cue and its windows (0 / 0.3 / 0.7 / adaptive): the useful delay and the false starts together. Backlog: a table of working points and the Pareto border WITH n in each row, on a fresh
holdout; G3 measured 0.7 s on a stand cloud (final to cue 0.58 to 1.33 s). Here only the logic of the point in force: the window of the profile in force and no start inside a pause of speech. The table and its n are the
cloud's and the holdout's work (family I2: ``tools/replay/hold_sweep.py``), not a test of this directory.

Real ControlledMedia, NativeMediaSocket, ShadowEar (rig ``call`` with the live profile). Not run on the laptop. A red test is a defect card for the family T (the terms).
"""
import pytest

from portion_kit import EAR_RELEASE_SILENCE_SECONDS, EAR_TAIL_SILENCE_SECONDS, GRID, LIVE_RULES, TICK, answer_over_speech, call      # noqa: F401 - call is the fixture


def test_the_window_in_force_is_between_the_two_points_the_table_names():
    assert 0.3 <= EAR_RELEASE_SILENCE_SECONDS <= 0.9, 'the window of the release left the range of the table (0.3 / 0.7 / 0.9)'
    assert EAR_RELEASE_SILENCE_SECONDS < EAR_TAIL_SILENCE_SECONDS, 'an open tail waits longer than a closed question'


def test_a_ready_answer_goes_at_the_window_after_the_end_of_speech_and_not_before(call):
    rig = call(**LIVE_RULES)
    uid = answer_over_speech(rig)
    rig.pump(1.0)
    ended = rig.offset()
    rig.pump(0.1)
    rig.worker.heard(uid, 'э-э')
    assert rig.said() == [], 'not before the window'
    cue = rig.next_cue(EAR_RELEASE_SILENCE_SECONDS + 0.5)
    assert cue is not None and cue.t - ended == pytest.approx(EAR_RELEASE_SILENCE_SECONDS, abs=GRID + TICK), f'the cue came {cue.t - ended:.2f} s after the end of speech'


def test_a_pause_of_speech_shorter_than_the_window_starts_nothing(call):
    """False starts = 0 at the point in force: the breath of a long question is no end of it."""
    rig = call(**LIVE_RULES)
    uid = answer_over_speech(rig)
    rig.pump(1.0)
    rig.offset()
    rig.pump(EAR_RELEASE_SILENCE_SECONDS - 3 * GRID)
    assert rig.said() == []
    rig.onset()                                   # speech again inside the window
    rig.pump(1.5)
    assert rig.said() == [], f'the cue started inside the speech: {rig.said()}'

import pytest as _pt_no_lead
pytestmark = _pt_no_lead.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)
