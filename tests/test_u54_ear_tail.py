"""U54: the next portion on the ear's partial text. The tail of the partial matched the end of the waiting portion: the portion is counted as said once that text has stood ``ack_stable_seconds``
(the rule of the cloud's stable partial), without waiting for the ear's end-of-speech pause; a word after the tail cancels. Scripted ear: only the partial text is given, the detector never says 'end'."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from test_h3_tempo import TICK, call, in_flight      # noqa: E402,F401 - call is the fixture
from test_repeat_cases import P1, P2, photosynthesis      # noqa: E402

SAID = 'свет попадает на хлорофилл в листьях'


def partial(rig, uid, text):
    """The ear's text so far as the transport hands it over (native_media_socket._ear_partial): its actions are carried out."""
    rig.w.run(rig.w.wire.actions(rig.c.ear_partial({'uid': uid, 'text': text})))


def at_second_portion(call):
    rig = photosynthesis(call)
    return rig, rig.onset()


def test_the_next_portion_goes_on_the_partial_before_the_offset_pause(call):
    rig, uid = at_second_portion(call)
    before = len(rig.cues())
    rig.pump(0.4)
    partial(rig, uid, SAID)
    rig.pump(0.15 + TICK * 3)
    assert rig.ear.current is not None, 'the detector has not ended the speech: this is before the offset pause'
    assert len(rig.cues()) == before + 1, rig.said()
    assert rig.said()[-1] == P2


def test_a_word_after_the_tail_cancels(call):
    rig, uid = at_second_portion(call)
    before = len(rig.cues())
    rig.pump(0.4)
    partial(rig, uid, SAID)
    rig.pump(TICK)
    rig.c.ear_partial({'uid': uid, 'text': SAID + ' и ещё'})      # the speaker went on: the tail was not the end
    rig.pump(1.0)
    assert len(rig.cues()) == before, rig.said()


def test_a_word_after_the_issued_tail_cuts_the_cue(call):
    rig, uid = at_second_portion(call)
    rig.pump(0.4)
    partial(rig, uid, SAID)
    cue = in_flight(rig)
    assert cue is not None and cue.text == P2 and not cue.cleared, 'precondition: the portion went on the tail'
    partial(rig, uid, SAID + ' и ещё')
    rig.pump(TICK * 2)
    assert cue.cleared, 'the speaker went on: what is being said now cuts the cue'


def test_half_of_the_portion_is_no_tail(call):
    rig, uid = at_second_portion(call)
    before = len(rig.cues())
    rig.pump(0.4)
    partial(rig, uid, 'свет попадает на')
    rig.pump(0.15 + TICK * 3)
    assert len(rig.cues()) == before
