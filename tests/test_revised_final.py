"""WAVE 2 / Task B, item 2 (DEF-STATE-03): a revised final of the CURRENT question must not mute the call.

The provider may deliver a second, different ``turn.done`` for a user turn that is already final (a refined transcript). The ledger used
to mark such a turn conflicted for good; the transport then refused to play anything until the next question (``_can_play`` wants a
valid, final question turn), and the cursor moved without a sound. Required: a revision of the same user turn updates it and silences
nothing; it is still never taken for a new utterance (the words of a turn count once); a turn that changes its ROLE, or an answer that is
rewritten, is still a conflict.
"""
import asyncio

import helpers_s6_ack as H
from echo_sync.voice_turns import FramelessTurns

ANSWER = 'Свойство тела сопротивляться изменению своего движения. Это называется инерцией. Чем больше масса, тем сильнее инерция.'
PORTION = 'Свойство тела сопротивляться изменению своего движения.'


def done(tid, role, text):
    return {'type': 'turn.done', 'turn': {'id': tid, 'role': role, 'transcript': text}}


def test_a_revised_final_of_a_user_turn_updates_it_and_keeps_it_valid():
    f = FramelessTurns()
    f.apply(done('u', 'user', '15 процентов'))
    revised = f.apply(done('u', 'user', '50 процентов'))
    assert revised is not None and revised['text'] == '50 процентов' and revised['final'] and revised['valid']
    assert revised['revisions'] == 1 and not revised['conflicted']
    assert f.latest_user()['text'] == '50 процентов'


def test_each_new_revision_is_counted_and_the_same_text_again_is_a_duplicate():
    f = FramelessTurns()
    f.apply(done('u', 'user', 'раз'))
    f.apply(done('u', 'user', 'два'))
    assert f.apply(done('u', 'user', 'два')) is None, 'the same final once more is a duplicate'
    assert f.apply(done('u', 'user', 'три'))['revisions'] == 2


def test_an_empty_revision_does_not_wipe_the_turn():
    f = FramelessTurns()
    f.apply(done('u', 'user', 'Что такое инерция'))
    assert f.apply(done('u', 'user', '   ')) is None, 'nothing was said: not a revision'
    assert f.snapshot('u')['text'] == 'Что такое инерция' and f.snapshot('u')['valid']


def test_a_turn_that_changes_its_role_is_still_a_conflict():
    f = FramelessTurns()
    f.apply(done('x', 'user', 'слово'))
    f.apply(done('x', 'assistant', 'слово'))
    assert f.snapshot('x')['conflicted'] and not f.snapshot('x')['valid']


def test_a_rewritten_answer_is_still_a_conflict():
    f = FramelessTurns()
    f.apply(done('a', 'assistant', 'Инерция — это свойство тела.'))
    f.apply(done('a', 'assistant', 'Инерция — это другое.'))
    assert f.snapshot('a')['conflicted'] and not f.snapshot('a')['valid'], 'what was dictated must not change under the listener'


def test_the_revised_question_does_not_mute_the_call_and_the_answer_goes_on(tmp_path):
    async def run():
        wire = H.Wire(tmp_path / 'revised')
        try:
            await wire.begin(ANSWER)
            first = wire.chunks[0]
            assert wire.synthesized == [first]
            cleared = wire.cleared()
            await wire.socket.provider(done('q1', 'user', H.Dictation.QUESTION + ' пожалуйста'))     # same id, new text
            await wire.settle()
            assert wire.cleared() == cleared, 'a revision restarts nothing'
            await wire.user(first, tid='ack-1')
            assert wire.index == 1, 'the cursor moved ...'
            assert wire.synthesized[-1] == wire.chunks[1], '... and the next portion was SPOKEN, not parked'
            assert wire.socket.pending_cue is None
        finally:
            await wire.close()
    asyncio.run(run())


def test_a_revision_of_the_confirming_turn_is_never_a_second_confirmation(tmp_path):
    async def run():
        wire = H.Wire(tmp_path / 'twice')
        try:
            await wire.begin(ANSWER)
            await wire.user(wire.chunks[0], tid='ack-1')
            assert wire.index == 1
            spoken = list(wire.synthesized)
            await wire.socket.provider(done('ack-1', 'user', wire.chunks[1]))        # the refined transcript says the NEXT portion
            await wire.settle()
            assert wire.index == 1 and wire.synthesized == spoken, 'the words of one turn confirm once'
        finally:
            await wire.close()
    asyncio.run(run())


def test_the_revised_question_does_not_start_another_lookup_or_answer(tmp_path):
    d = H.Dictation(tmp_path / 'dict', ANSWER)
    out = d.deliver(done('q1', 'user', 'Совсем другой вопрос про фотосинтез?'))
    assert out.actions == [] and out.after == 0 and out.model_calls == 0, 'a revision is not a new question'
    assert d.say(d.current, gap=4.0).after == 1
