"""U38: the bank's answer after the ear's words waits for the cloud at most BANK_WAIT_S - on the cloud's silence (no turn announced, or one that says nothing yet),  as well as on.
Before: with the flag off the answer of the base waited for the cloud's turn ``EAR_FIRST_BIND_SECONDS`` (3.9 s on the rig). Through the real controller (rig of test_h3 / test_h4)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import helpers_s6_state as S      # noqa: E402
from test_h3_tempo import HEAD, TICK, WAIT_OF_H3, call      # noqa: E402,F401 - call is the fixture
from test_h4_ear_first import EAR_17      # noqa: E402

BANK_WAIT_S = 0.5


@pytest.mark.parametrize('cloud', ['silent', 'behind'])
def test_the_bank_does_not_wait_for_a_silent_cloud(call, cloud):
    rig = call(fast_text='on', **WAIT_OF_H3)
    uid = rig.onset()
    rig.pump(1.0)
    if cloud == 'behind':
        rig.w.feed(S.turn_created('u1', 'user', 'Семнадцатая'))
    rig.pump(0.5)
    rig.offset()
    rig.pump(0.15)
    heard = rig.w.clock.t
    rig.worker.heard(uid, EAR_17)
    while not rig.cues() and rig.w.clock.t - heard < 5.0:
        rig.pump(TICK)
    assert rig.said() == [HEAD] and rig.cues()[0].t - heard <= BANK_WAIT_S, rig.cues()[0].t - heard if rig.cues() else None
