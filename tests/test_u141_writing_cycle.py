"""U141: the owner's cycle of repeats while they WRITE is told from their speech (the places of the answer they went on from), not from a switch: no key is set here and the record state brings the cycle.
Through the real ControlledMedia (the rig of ``test_h3_tempo``, injected clock); nothing here is a measurement of a call."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from test_h3_tempo import call       # noqa: E402,F401 - call is the fixture
from test_repeat_cases import ASK, P1, P2, P3, rig_of      # noqa: E402
from test_x_cap_wiring import with_settings      # noqa: E402
from echo_sync import timer_policy as tp      # noqa: E402


def answered(rig):
    rig.asks('u1', ASK, 0, f'{P1} {P2} {P3}')
    return rig, rig.c.state()['revision']


def test_writing_told_from_speech_brings_the_cycle_without_the_switch(call):
    rig, r = answered(with_settings(rig_of(call, max_auto_repeats=3), cycle_max_repeats=15))
    assert 'dictation_cycle' not in rig.c.settings
    assert rig.c._silence()[1:3] == (3, 'plain'), 'nobody writes yet: the plain cap'
    rig.c._record_progress((r, 0))
    assert rig.c._silence()[1:3] == (3, 'plain')
    rig.c._record_progress((r, 1))
    sil = rig.c._silence()
    assert sil.cycling and (sil.cap, sil.why) == (15, 'record'), 'the owner went on from two places: the pen is what the silence waits for'
    # the owner is seen writing: the cycle's silence waits for the pen, never less than the owner's own writing time of the waiting portion (repeat_rule.silence, c22)
    pen = tp.DICTATION_SPARE * tp.DICTATION_WORD_SECONDS * len(P1.split()) + tp.DICTATION_EXTRA_SECONDS      # six words of P1 at the untrained pace
    assert sil.wait == pen and sil.wait > tp.cycle_wait(0), 'the cycle waits for the pen of a writing owner'


