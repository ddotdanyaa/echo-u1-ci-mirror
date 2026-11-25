"""U40 (core, portion + timers): the wait of the silence timer has ONE source, ``repeat_rule.silence`` (through ``ControlledMedia._silence``).

Before: ``_tempo_off`` (the local ear is lost: nobody will tell the end of what it was hearing) armed the timer at ``clock + repeat_seconds``, the bare base,
while every other arm asks ``_silence().wait``. A writing owner (the cycle: DICTATION_CYCLE_SECONDS, the owner's pace) whose ear fell silent was repeated after
the plain wait, not the cycle's: two owners of the same number. The test goes through the real ControlledMedia (the world of test_h3_tempo)."""
import pathlib

import pytest

import helpers_s6_state as S      # noqa: F401 - the world of the rig
from echo_sync import cm_timers, timer_policy as tp
from echo_sync.settings import resolve
from test_h3_tempo import call      # noqa: F401 - the fixture


def _writing(c):
    """The owner is seen writing from this answer: the state in which ``_silence`` runs the cycle (``_recording``)."""
    k = resolve(c.settings)['record_engage_k']
    c.record_seen = (c.state()['revision'], set(range(k)))
    assert c._recording() is True


def test_the_ear_lost_while_the_owner_writes_arms_the_cycles_wait_not_the_bare_base(call):
    rig = call(ear='shadow')
    rig.second_portion()
    c = rig.c
    _writing(c)
    assert not c._cue_playing(c.clock()) and c._position(c.state()) is not None, 'precondition: a portion waits and no cue is in flight'
    wait = c._silence().wait
    assert wait == tp.cycle_wait(c.auto_repeats) and wait != c.repeat_seconds, 'precondition: the cycle and the bare base are two different numbers'
    c._arm(None)
    began = c.clock()
    c._tempo_off()
    assert c.repeat_at == pytest.approx(began + wait), 'the ear went: the silence waits as the writing owner is waited for, not repeat_seconds'


def test_the_ear_lost_while_nobody_writes_keeps_the_plain_wait(call):
    rig = call(ear='shadow')
    rig.second_portion()
    c = rig.c
    assert c._recording() is False and not c._cue_playing(c.clock())
    c._arm(None)
    began = c.clock()
    c._tempo_off()
    assert c._silence().wait == c.repeat_seconds and c.repeat_at == pytest.approx(began + c.repeat_seconds)


def test_a_fault_in_the_silence_does_not_fall_out_of_the_emergency_path(call, monkeypatch):
    """``_tempo_off`` is called from ``_tempo_safely``'s except: if ``_silence`` itself raises, the timer still runs, on the plain base."""
    rig = call(ear='shadow')
    rig.second_portion()
    c = rig.c

    def broken():
        raise ValueError('boom')
    monkeypatch.setattr(c, '_silence', broken)
    c._arm(None)
    began = c.clock()
    c._tempo_off()
    assert c.tempo_live is False and c.repeat_at == pytest.approx(began + c.repeat_seconds)


def test_the_timers_module_reads_the_bare_base_only_in_the_emergency_handler():
    import ast
    tree = ast.parse(pathlib.Path(cm_timers.__file__).read_text(encoding='utf-8'))
    inside = {id(n) for h in ast.walk(tree) if isinstance(h, ast.ExceptHandler) for n in ast.walk(h)}
    reads = [n.lineno for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr == 'repeat_seconds' and id(n) not in inside]
    assert reads == [], reads
