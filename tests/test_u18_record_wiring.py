"""u18-s3: the record progress state of the controller (``record_seen``, ``_record_progress``, ``_recording``) feeds ``repeat_cap``. With ``record_mode`` off it is only computed and logged
(``record_shadow=``). The rig of ``test_h3_tempo`` on the injected clock; nothing here is a measurement of a call."""
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from test_h3_tempo import call       # noqa: E402,F401 - call is the fixture
from test_repeat_cases import ASK, P1, P2, P3, rig_of, utter      # noqa: E402,F401
from test_x_cap_wiring import with_settings      # noqa: E402
from cm_patch import patch_controller      # noqa: E402


def answered(rig):
    rig.asks('u1', ASK, 0, f'{P1} {P2} {P3}')
    return rig, rig.c.state()['revision']


def test_the_state_counts_distinct_places_of_one_revision(call):
    rig, r = answered(rig_of(call, max_auto_repeats=3))
    c = rig.c
    assert not c._recording()
    c._record_progress((r, 0))
    c._record_progress((r, 0))      # S36/S37: the same words said twice are one advance
    assert not c._recording() and c.record_seen == (r, {0})
    c._record_progress((r, 1))
    assert c._recording()
    c._record_progress((r + 1, 0))      # a new revision is a new answer
    assert not c._recording() and c.record_seen == (r + 1, {0})
    c._record_progress(None)
    assert c.record_seen == (r + 1, {0})


def test_k_is_the_setting(call):
    rig, r = answered(with_settings(rig_of(call, max_auto_repeats=3), record_engage_k=3))
    for i in range(2):
        rig.c._record_progress((r, i))
    assert not rig.c._recording()
    rig.c._record_progress((r, 2))
    assert rig.c._recording()


def test_earned_the_cap_rises_only_with_two_advances(call):
    rig, r = answered(with_settings(rig_of(call, max_auto_repeats=3), dictation_cycle='on', record_mode='earned', cycle_max_repeats=15))
    assert rig.c._cap_count()[1:3] == (3, 'plain'), 'the invariant 1+max_auto_repeats without a record'
    rig.c._record_progress((r, 0))
    assert rig.c._cap_count()[1:3] == (3, 'plain')
    rig.c._record_progress((r, 1))
    assert rig.c._cap_count()[1:3] == (15, 'record')
    rig.c.unplaced = True
    assert rig.c._cap_count()[1:3] == (3, 'unplaced')


def test_off_the_cap_is_the_cycle_and_the_shadow_is_logged(call, caplog):
    rig, r = answered(with_settings(rig_of(call, max_auto_repeats=3), dictation_cycle='on', cycle_max_repeats=15))
    with caplog.at_level(logging.INFO):
        rig.c._record_progress((r, 0))
        rig.c._record_progress((r, 1))
    assert rig.c._cap_count()[1:3] == (15, 'cycle')
    assert 'record_shadow=True' in caplog.text and 'record_shadow=False' in caplog.text


def _run(call, **flags):
    rig = with_settings(rig_of(call, max_auto_repeats=3), dictation_cycle='on', **flags)
    rig.asks('u1', ASK, 0, f'{P1} {P2} {P3}')
    rig.pump(30.0)
    return rig


def test_off_the_cue_sequence_is_unchanged(call):
    base = _run(call)
    off = _run(call, record_mode='off')
    assert base.said() == off.said()


def test_the_ack_of_a_portion_is_recorded_at_its_position(call):
    rig = with_settings(rig_of(call, max_auto_repeats=3), record_mode='earned')
    rig.asks('u1', ASK, 0, f'{P1} {P2} {P3}')
    rig.pump(0.5)
    utter(rig, P1, turn='u2', final=P1)
    rig.pump(1.0)
    seen = rig.c.record_seen
    assert seen is not None and 0 in seen[1], seen


# -- u18-s4: the tools of writing on the record state ------------------------------------------------------------------------------------
LONG = 'Свет попадает на хлорофилл в листьях растений и запускает реакцию.'


def run_of(portion):
    """The words of the portion after its first, short of its end (not a start of it): what the owner says they wrote last."""
    words = portion.rstrip('.').split()
    return ' '.join(words[1:len(words) - 1])


def _waiting(call, **flags):
    rig = with_settings(rig_of(call, max_auto_repeats=3), dictation='on', **flags)
    rig.asks('u1', ASK, 0, f'{LONG} {P2}')
    rig.pump(1.0)
    state = rig.c.state()
    return rig, state, state and __import__('echo_sync.controlled_media', fromlist=['x']).waiting_portion(state)


def _earn(rig):
    r = rig.c.state()['revision']
    rig.c._record_progress((r, 0))
    rig.c._record_progress((r, 1))
    assert rig.c._recording()


def test_off_the_tools_follow_dictation_as_before(call):
    rig, state, portion = _waiting(call, record_mode='off')
    assert rig.c._record_tools() is True
    run = run_of(portion)
    assert rig.c._tempo_verdict(run, run, state, portion)[0] == 'start'
    rig.c.settings = {**rig.c.settings, 'dictation': 'off'}
    assert rig.c._record_tools() is False


def test_earned_written_to_is_asked_only_in_the_record_state(call, monkeypatch):
    import echo_sync.controlled_media as cm
    asked = []
    real = cm.written_to
    patch_controller(monkeypatch, 'written_to', lambda text, portion: asked.append(text) or real(text, portion))
    rig, state, portion = _waiting(call, record_mode='earned')
    portion = f'{portion} {P2}'      # a long portion: a run in its middle is no start of it
    run = ' '.join(portion.rstrip('.').split()[3:-1])
    assert not rig.c._recording() and rig.c._record_tools() is False
    rig.c._tempo_verdict(run, run, state, portion)
    assert asked == [], 'dictation said is not the record state'
    _earn(rig)
    rig.c._tempo_verdict(run, run, state, portion)
    assert asked == [run]


def test_the_pen_wait_is_the_record_states(call):
    rig, state, portion = _waiting(call, record_mode='earned')
    base = rig.c.repeat_seconds
    assert rig.c._repeat_wait() == base, 'outside the record state the plain wait'
    _earn(rig)
    assert rig.c._repeat_wait() >= 6.0


def test_a_pause_holds_6s_in_record_and_4s_outside(call):
    from echo_sync.controlled_media import HOLD_BOUNDS, RECORD_PAUSE_SECONDS, TEMPO_PAUSE_SECONDS
    assert HOLD_BOUNDS['record_pause'][0] == RECORD_PAUSE_SECONDS <= 8.0
    held = {}
    for name in ('outside', 'record'):
        rig, state, portion = _waiting(call, record_mode='earned')
        if name == 'record':
            _earn(rig)
        rig.pump(0.5)
        ended = rig.says('секунду')
        held[name] = rig.c.repeat_at - ended
    assert held['outside'] >= TEMPO_PAUSE_SECONDS - 0.01 and held['outside'] < 6.0, held
    assert 6.0 <= held['record'] <= RECORD_PAUSE_SECONDS + 0.01, held


def test_a_pause_with_record_mode_off_holds_4s_even_when_dictating(call):
    from echo_sync.controlled_media import TEMPO_PAUSE_SECONDS
    rig, state, portion = _waiting(call, record_mode='off')
    assert rig.c._record_tools() is True      # dictation on: the other tools run as before
    rig.pump(0.5)
    ended = rig.says('секунду')
    assert abs((rig.c.repeat_at - ended) - TEMPO_PAUSE_SECONDS) < 0.01, rig.c.repeat_at - ended
