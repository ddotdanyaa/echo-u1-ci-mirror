"""f4-noise: the ear's partial text in what near_voice calls no speech (noise decoded into a bank question) opens no instant answer."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import helpers_s6_state as S
import helpers_w5_instant as fx
from echo_sync.instant import Instant
from test_h3_tempo import TICK, call       # noqa: F401 - call is the fixture
from test_w10_ear_command import _Gate


def _hit(call, kind):
    rig = call(fast_text='on', instant='on')
    rig.c.instant = Instant(fx.bank())
    if kind:rig.c.speaker_gate = _Gate(kind)
    uid = rig.onset()
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.pump(0.6)
    rig.ear.partials.append({'uid': uid, 'text': 'когда пал константинополь', 'decode_ms': 30})
    rig.pump(2 * TICK)
    return rig


def test_noise_opens_no_instant_answer(call):
    assert _hit(call, 'quiet').said() == []


def test_a_voice_still_opens_it(call):
    for kind in (None, 'own', 'unknown', 'other'):
        assert _hit(call, kind).said(), kind
