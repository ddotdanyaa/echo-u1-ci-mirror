"""W13 item 2 (P0, s3#16 «Права налогоплательщика…»): the bank's answer opened on the ear's text so far, the question went on, several
``act=cut``, the cue parked, 55 s of silence, the question unanswered. The rule: the cue either sounds, or the question goes the usual way."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import helpers_s6_state as S
import helpers_w5_instant as fx
from echo_sync.instant import Instant
from test_h3_tempo import TICK, call       # noqa: F401 - call is the fixture

GROWS = ['когда пал константинополь и', 'когда пал константинополь и почему', 'когда пал константинополь и почему это', 'когда пал константинополь и почему это важно',
         'когда пал константинополь и почему это важно для истории']
ASKED = 'Когда пал Константинополь и почему это важно для истории?'


def _cut_five_times(call):
    rig = call(fast_text='on', instant='on')
    rig.c.instant = Instant(fx.bank())
    uid = rig.onset()
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.pump(0.6)
    rig.ear.partials.append({'uid': uid, 'text': 'когда пал константинополь', 'decode_ms': 30})
    rig.pump(2 * TICK)
    for text in GROWS:
        rig.ear.partials.append({'uid': uid, 'text': text, 'decode_ms': 30})
        rig.pump(0.2)
    rig.offset()
    rig.pump(0.15)
    rig.worker.heard(uid, GROWS[-1])
    rig.pump(TICK)
    rig.w.feed(S.turn_done('u1', 'user', ASKED))
    rig.pump(2 * TICK)
    return rig


def _answered(rig):
    said = rig.said()
    if any('Двадцать девятого мая' in s for s in said):
        return True
    rig.job_says(0, 'Константинополь пал в 1453 году, это конец Византии.')
    rig.job_ends(0)
    return any('Византии' in s or '1453' in s or 'тысяча четыреста' in s.lower() for s in rig.said())


def test_with_the_ears_tempo_a_cut_hit_does_not_leave_the_question_silent(call):
    rig = _cut_five_times(call)
    assert _answered(rig), rig.said()


def test_with_the_ear_off_the_bank_answers_on_the_clouds_final(call):
    """The control of «no ear, no tempo of the ear»: the bank opens on the final of the cloud, and the question is not left silent."""
    rig = call(ear='off', fast_text='on', instant='on')
    assert rig.ear is None and rig.c.tempo_live is False
    rig.c.instant = Instant(fx.bank())
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.pump(0.6)
    rig.w.feed(S.turn_done('u1', 'user', ASKED))
    rig.pump(2 * TICK)
    assert _answered(rig), rig.said()


def test_a_cut_is_acted_on_once(call, caplog):
    import logging
    caplog.set_level(logging.INFO)
    _cut_five_times(call)
    assert sum('instant act=cut' in r.getMessage() for r in caplog.records) <= 1
