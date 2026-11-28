"""W5 stumble on the real controller, the H3 rig (``test_h3_tempo``: the real NativeMediaSocket, ShadowEar and ControlledMedia on the injected clock). ``prompt_pace`` = "on" asks the controller to take
the wait of a start that stopped from ``echo_sync.pace``. Today nothing reads that setting: these rows fail (xfail strict) and pass with the patch of ``cloud_context/reports/w5-stumble_controlled_media.diff``.
The ear's detector ends an utterance 300 ms after the speech (``Rig.says``: the end it returns is that offset); the text comes ``lag`` later."""
import pytest

from echo_sync.controlled_media import TEMPO_START_SECONDS
from echo_sync.settings import resolve
from test_h3_tempo import GRID, PORTION, REST, TICK, Rig

QUIET = 0.3                    # the detector's offset after the last word
PATCH = 'needs the patch cloud_context/reports/w5-stumble_controlled_media.diff (prompt_pace is read by nobody today)'


@pytest.fixture
def call(monkeypatch):
    made = []

    def make(**profile):
        rig = Rig(monkeypatch, **profile)
        made.append(rig)
        return rig
    yield make
    for rig in made:
        rig.close()


def help_after(rig, ended, within=3.0):
    """The first cue after ``ended``: it may have gone out on the tick that took the text."""
    while rig.w.clock.t - ended < within and not [c for c in rig.cues() if c.t > ended]:
        rig.pump(TICK)
    cue = next((c for c in rig.cues() if c.t > ended), None)
    return cue, (None if cue is None else cue.t - ended)


def test_today_a_start_that_stopped_waits_rule_3_from_the_offset(call):
    """What is: the help 1.2 s after the offset, 1.5 s after the last word, whoever speaks and wherever they stopped."""
    rig = call()
    rig.second_portion()
    rig.pump(0.5)
    ended = rig.says('общие', speech=0.3, lag=0.15)
    cue, after = help_after(rig, ended)
    assert cue.text == REST and after == pytest.approx(TEMPO_START_SECONDS, abs=GRID)


def test_the_setting_is_known_and_off_by_default():
    assert resolve({})['prompt_pace'] == 'off' and resolve({'local_ear': 'act', 'prompt_pace': 'on'})['prompt_pace'] == 'on'


def test_a_stop_inside_a_group_is_helped_within_the_target(call):
    """«общие» | silence: the help 0.7-1.2 s after the last word, i.e. at most 0.9 s after the offset with its ~0.13 s to the sound; today 1.2 s after the offset."""
    rig = call(prompt_pace='on')
    rig.second_portion()
    rig.pump(0.5)
    ended = rig.says('общие условия', speech=0.6, lag=0.15)
    cue, after = help_after(rig, ended)
    assert cue.text == 'установления налогов и сборов.' and after <= 1.2 - QUIET - 0.13 + GRID


def test_a_filler_after_a_start_is_help_at_once(call):
    """«общие э-э»: the word will not come: help within 0.6 s of the filler's end (0.3 s after the offset), today 1.2 s after the offset."""
    rig = call(prompt_pace='on')
    rig.second_portion()
    rig.pump(0.5)
    ended = rig.says('общие э-э', speech=0.7, lag=0.15)
    cue, after = help_after(rig, ended)
    assert cue.text == REST and after <= 0.6 - QUIET + GRID


def test_off_by_default_nothing_changes(call):
    rig = call()
    rig.second_portion()
    rig.pump(0.5)
    ended = rig.says('общие э-э', speech=0.7, lag=0.15)
    cue, after = help_after(rig, ended)
    assert cue.text == REST and after == pytest.approx(TEMPO_START_SECONDS, abs=GRID)


def test_speech_that_goes_on_is_never_cut_with_the_setting_on(call):
    """«общие» | 0.25 s | «условия установления налогов и сборов»: the whole portion said, no help in between."""
    rig = call(prompt_pace='on')
    rig.second_portion()
    rig.pump(0.5)
    rig.says('общие', speech=0.3, lag=0.1)
    count = len(rig.said())
    rig.says('условия установления налогов и сборов', speech=1.6, lag=0.15)
    rig.pump(TICK * 3)
    assert len(rig.said()) == count or rig.said()[-1] != REST


@pytest.mark.parametrize('said', ['общие', 'общие условия'])
def test_w10_with_the_pace_a_silent_stop_is_helped_inside_the_owners_window(call, said):
    """w10 item 16: «запинка за 0,7-1,2 с»: a SILENT stop: the pace chooses its wait inside PACE_HELP_SECONDS after the last word (QUIET before the offset), never at 0.35 s (a breath).
    A filler or a stammer says the word will not come: that is help at once (test_a_filler_after_a_start_is_help_at_once)."""
    from echo_sync.controlled_media import PACE_HELP_SECONDS
    rig = call(prompt_pace='on')
    rig.second_portion()
    rig.pump(0.5)
    ended = rig.says(said, speech=0.5 + 0.2 * len(said.split()), lag=0.15)
    cue, after = help_after(rig, ended)
    assert cue is not None and PACE_HELP_SECONDS[0] - GRID <= after + QUIET <= PACE_HELP_SECONDS[1] + GRID, after
