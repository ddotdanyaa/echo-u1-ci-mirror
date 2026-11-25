"""w5-instant: the wiring on the real controller and transport (the H4 rig: NativeMediaSocket, ShadowEar, ControlledMedia on the injected clock). ``controlled_media.py`` is the
coordinator's file: these tests fail on it as it is (xfail strict) and pass with ``cloud_context/reports/w5-instant.wiring.diff`` applied (checked in a scratch tree, see the report)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import helpers_w5_instant as fx
from echo_sync.instant import Instant
from test_h3_tempo import TICK, call       # noqa: F401 - call is the fixture
from test_h4_ear_first import final, speaks

WIRED = hasattr(__import__('echo_sync.controlled_media', fromlist=['ControlledMedia']).ControlledMedia, 'ear_partial')
xfail = pytest.mark.xfail(not WIRED, reason='the wiring patch is not applied: controlled_media.py is the coordinator\'s', strict=True)


@xfail
def test_a_bank_question_is_cued_from_the_ears_text_before_the_final(call):
    rig = call(fast_text='on')
    rig.c.instant = Instant(fx.bank())
    ended = speaks(rig, 'когда пал константинополь', turn='u1', announced=1.4, speech=1.5)
    assert rig.said() and rig.said()[0].startswith('Двадцать девятого мая'), rig.said()
    assert rig.cues()[0].t - ended <= 0.15 + 2 * TICK + 0.01
    final(rig, 'u1', 'Когда пал Константинополь?')
    assert len(rig.cues()) == 1 and not rig.cues()[0].cleared


def test_a_bank_question_with_another_number_goes_the_usual_way(call):
    rig = call(fast_text='on')
    rig.c.instant = Instant(fx.bank())
    speaks(rig, 'что говорится в статье 16 налогового кодекса', turn='u1', announced=2.0, speech=2.1)
    assert not any('специальные' in s or 'общие условия' in s for s in rig.said())


def test_off_the_controller_has_no_index(call):
    rig = call(fast_text='on')
    assert getattr(rig.c, 'instant', None) is None
    speaks(rig, 'когда пал константинополь', turn='u1', announced=1.4, speech=1.5)
    assert rig.said() == []


@xfail
@pytest.mark.parametrize('row', fx.bank()[::8], ids=lambda r: r['id'])
def test_the_cue_said_is_the_first_portion_the_cache_was_filled_with(call, row):
    """The PCM cache is keyed by text: what ``pcm_cache.prerender`` speaks before the call must be what the controller cues."""
    from echo_sync.pcm_cache import first_portion
    rig = call(fast_text='on')
    rig.c.instant = Instant(fx.bank())
    speaks(rig, row['q'].lower(), turn='u1', announced=1.0, speech=1.1)
    assert rig.said() and rig.said()[0] == first_portion(row['answer'])


def _partial_hit(call):
    import helpers_s6_state as S
    rig = call(fast_text='on', instant='on')
    assert rig.ear.partial_ms == 200
    rig.c.instant = Instant(fx.bank())
    uid = rig.onset()
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.pump(0.6)
    rig.ear.partials.append({'uid': uid, 'text': 'когда пал константинополь', 'decode_ms': 30})
    rig.pump(2 * TICK)
    return rig, uid


@xfail
def test_with_the_ears_tempo_the_ready_answer_waits_for_the_end_and_the_ears_text_of_it(call):
    """The phone is half-duplex: a cue over the speech closes the microphone. H3 holds the first cue while the ear hears speech and until that speech is judged (the ear's text of it, 0.15 s
    after the detector's end); the answer is published and its PCM ready by then, so it sounds at once. Not sooner: that is H3's rule, the coordinator's to change (report)."""
    rig, uid = _partial_hit(call)
    assert rig.said() == [], 'held while the listener speaks'
    ended = rig.offset()
    rig.pump(2 * TICK)
    assert rig.said() == [], 'held until the speech is judged'
    rig.worker.heard(uid, 'когда пал константинополь')
    rig.pump(2 * TICK)
    assert rig.said() and rig.said()[0].startswith('Двадцать девятого мая')
    assert rig.cues()[0].t - ended <= 2 * TICK + 2 * TICK + 0.01


def test_u30_the_ear_that_lost_the_question_word_is_still_answered_from_the_bank(call):
    """U30 (run of 09.11): «кто такое …» for «что такое …»: the ear's text reads as no question, yet every other word is the bank row's: its answer is cued at once, not after the cloud's text."""
    rig = call(fast_text='on')
    rig.c.instant = Instant(fx.bank())
    speaks(rig, 'кто такое транспортный налог', turn='u1', announced=1.4, speech=1.5)
    assert rig.said() and rig.said()[0].startswith('Региональный налог'), rig.said()


def test_u30_another_question_never_takes_the_answer_of_the_row(call):
    rig = call(fast_text='on')
    rig.c.instant = Instant(fx.bank())
    speaks(rig, 'кто такое водный налог', turn='u1', announced=1.4, speech=1.5)
    assert not any('Региональный' in s or 'Местный' in s for s in rig.said()), rig.said()


def test_with_the_ear_off_the_bank_is_cued_on_the_clouds_final(call):
    """The control of «no ear, no tempo of the ear»: no text of the ear, the final of the cloud opens the bank's answer."""
    import helpers_s6_state as S
    rig = call(ear='off', fast_text='on', instant='on')
    assert rig.ear is None and rig.c.tempo_live is False
    rig.c.instant = Instant(fx.bank())
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.pump(0.6)
    rig.w.feed(S.turn_done('u1', 'user', 'Когда пал Константинополь?'))
    rig.pump(2 * TICK)
    assert rig.said() and rig.said()[0].startswith('Двадцать девятого мая'), rig.said()
