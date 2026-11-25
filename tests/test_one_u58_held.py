"""one-input U58: the dispatcher. Without the cloud no first cue waits for the cloud's word (``first_cue_hold``); a cue held before its release is checked against what was said meanwhile
(the listener has said it already: it is dropped and the next one comes from the cursor; it was made for another question than the one open now: it is not said over it); one cue waits at most."""
import helpers_s6_state as S
from echo_sync.controlled_media import ControlledMedia
from test_h3_tempo import call      # noqa: F401 - the fixture


def answered(rig, question='Сколько будет сорок на два', answer='Восемьдесят. Это ответ.'):
    w = rig.w
    w.feed(S.turn_created('u1', 'user', 'Сколько'))
    w.feed(S.turn_done('u1', 'user', question))
    w.feed(S.turn_done('a1', 'assistant', answer))
    return rig.c


def test_the_cloud_is_up_unless_the_wire_says_it_fell():
    assert ControlledMedia.cloud_up is True


def test_without_the_cloud_a_question_handed_back_to_it_holds_no_first_cue(call):
    rig = call()
    c = answered(rig)
    c.tempo_live, c.first_hold_from = True, None
    c.handed_asks = (c.clock(), (c.state() or {}).get('revision'))
    assert c.first_cue_hold() is not None, 'with the cloud: the cue waits for its answer'
    c.cloud_up, c.first_hold_from = False, None
    assert c.first_cue_hold() is None, 'without it nobody will confirm anything: no wait'


def held(rig, text='Восемьдесят.'):
    """A cue the wire holds: made by the controller for the open question, parked in ``pending_cue``."""
    c = rig.c
    state = c.state()
    cue = {'type': 'speak', 'text': text, 'epoch': c.epoch, 'nonce': c.nonce, 'revision': state['revision'], 'index': state['chunk_index'], 'replay': False}
    c.cued_mark = (cue['revision'], cue['index'], c.question_id, c.clock())
    return cue


def test_a_held_cue_whose_content_the_listener_said_meanwhile_is_not_released(call):
    rig = call()
    c = answered(rig)
    cue = held(rig)
    c.fragments.append((c._position(c.state()), 'восемьдесят', c.clock() + 0.5))
    c.engine.clock = c.clock
    assert c.held_cue(cue) == [], 'dropped, nothing said'
    assert c.go_on == c._position(c.state()), 'the next portion comes from the cursor'


def test_a_held_cue_nobody_has_answered_over_stays(call):
    rig = call()
    c = answered(rig)
    assert c.held_cue(held(rig)) is None


def test_the_answer_to_an_old_question_is_not_released_over_a_new_one(call):
    rig = call()
    c = answered(rig)
    cue = held(rig)
    c.question_id = 'u2'      # a new question opened while the cue waited, the plan of the old one stays (G3)
    assert c.held_cue(cue) == []


def test_one_cue_waits_at_most(call):
    rig = call()
    c = answered(rig)
    wire = rig.w.wire
    wire.pending_cue = first = held(rig, 'Первая.')
    second = held(rig, 'Вторая.')
    wire.pending_cue = second
    assert wire.pending_cue is second and first is not second
    assert c.held_cue(second) is None


def test_the_wire_releases_a_held_cue_through_the_check_of_the_controller(call):
    rig = call()
    c = answered(rig)
    wire = rig.w.wire
    cue = held(rig)
    c.question_id = 'u2'
    wire.pending_cue, wire._can_play = cue, lambda cue=None: True      # the ear is quiet: the hold ends
    n = len(rig.cues())
    rig.w.run(wire._release_pending())
    rig.w.settle()
    assert wire.pending_cue is None and len(rig.cues()) == n, 'an answer of the old question is not said over the new one'
