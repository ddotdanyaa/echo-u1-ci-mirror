"""WAVE 2 / Task B, item 1: «the user is speaking» must never stay set for good (DEF-FAULT-14, DEF-STATE-02, DEF-ACK-19).

A start of speech that never becomes a transcript (a cough, a VAD false start, the phone's ``response.cancel`` /
``input_audio_buffer.clear``, a retransmitted ``turn.created``) used to leave ``ControlledMedia.hearing`` set for ever: the
repeat loop was dead and a parked cue was never released. Required: the flag expires after ``HEARING_SECONDS`` without
transcript growth, and then the parked cue is played and the repeat timer runs again; a transcript that keeps growing keeps
the flag; a retransmitted ``turn.created`` of a turn that is already final is not a start of speech at all.
Time is injected: nothing here sleeps.
"""
import asyncio

import helpers_s6_ack as H
from echo_sync.controlled_media import HEARING_SECONDS

ANSWER = 'Свойство тела сопротивляться изменению своего движения. Это называется инерцией. Чем больше масса, тем сильнее инерция.'
# F1 (wave F): the first cue is the first meaning portion - the whole first sentence again (WAVE 2 / L2 had cut it to «Свойство тела»)
PORTION = 'Свойство тела сопротивляться изменению своего движения.'
QUESTION = 'Что такое инерция'


def speaks(actions):
    return [a['text'] for a in actions if a['type'] == 'speak']


def dictation(tmp_path):
    d = H.Dictation(tmp_path / 'hearing', ANSWER)
    assert d.current == PORTION
    return d


def test_a_start_of_speech_without_a_transcript_expires(tmp_path):
    d = dictation(tmp_path)
    c = d.controller
    d.clock.advance(1.0)
    c.speech_started()                                    # a cough: nothing follows
    assert c.hearing
    d.clock.advance(HEARING_SECONDS - 0.1)
    assert c.tick(now=d.clock()) == [] and c.hearing, 'still inside the expiry time'
    d.clock.advance(0.2)                                  # 0.1 s after it ran out
    assert c.tick(now=d.clock()) == [] and not c.hearing, 'expired: nobody is speaking, but nothing is repeated at once'
    d.clock.advance(c.repeat_seconds - 0.2)               # 0.1 s before the silence timer (counted from the release) is due
    assert c.tick(now=d.clock()) == [], 'the repeat timer counts from the release'
    d.clock.advance(0.2)
    assert speaks(c.tick(now=d.clock())) == [PORTION], 'then the unconfirmed portion is repeated again'


def test_the_silence_timer_counts_from_the_release_not_from_the_tick_that_noticed(tmp_path):
    d = dictation(tmp_path)
    c = d.controller
    c.speech_started()
    d.clock.advance(HEARING_SECONDS + c.repeat_seconds + 1.0)         # nobody ticked for a long while
    assert speaks(c.tick(now=d.clock())) == [PORTION], 'the repeat was already due when the tick came'


def test_a_growing_transcript_keeps_the_listener_heard(tmp_path):
    d = dictation(tmp_path)
    c = d.controller
    c.speech_started()
    c.provider(H.created('u2', 'user', 'Свойство'))
    for n in range(8):                                    # 8 s of speech, the transcript grows every second
        d.clock.advance(1.0)
        c.provider({'type': 'turn.delta', 'turn_id': 'u2', 'delta': f' слово{n}', 'start_ms': n * 1000, 'end_ms': n * 1000 + 900})
        assert c.hearing, f'the transcript grew {n + 1} s ago: the listener is still speaking'
        assert c.tick(now=d.clock()) == []
    d.clock.advance(HEARING_SECONDS - 0.1)
    assert c.hearing
    d.clock.advance(0.2)
    assert not c.hearing, 'no growth for HEARING_SECONDS: the flag is released'


def test_a_retransmitted_delta_is_not_growth(tmp_path):
    d = dictation(tmp_path)
    c = d.controller
    c.speech_started()
    c.provider(H.created('u2', 'user', 'Свойство'))
    delta = {'type': 'turn.delta', 'turn_id': 'u2', 'delta': ' вещества', 'start_ms': 100, 'end_ms': 400}   # (not the rest of the cue)
    d.clock.advance(1.5)
    c.provider(delta)
    d.clock.advance(1.0)
    c.provider(delta)                                     # the same words again: no news
    d.clock.advance(HEARING_SECONDS - 1.0 + 0.1)
    assert not c.hearing, 'the duplicate did not keep the flag alive'


def test_an_accepted_final_releases_at_once(tmp_path):
    d = dictation(tmp_path)
    c = d.controller
    d.clock.advance(4.0)
    c.speech_started()
    c.provider(H.created('u2', 'user', ''))
    assert c.hearing
    c.provider(H.done('u2', 'user', 'свойство'))
    assert not c.hearing


def test_a_parked_cue_is_released_when_the_flag_expires(tmp_path):
    async def run():
        wire = H.Wire(tmp_path / 'parked')
        try:
            await wire.socket.provider(H.created('q1', 'user', ''))
            await wire.socket.provider(H.done('q1', 'user', QUESTION))
            await wire.socket.provider({'type': 'input_audio_buffer.speech_started'})    # a stray VAD start, no transcript
            await wire.socket.provider(H.done('a1', 'assistant', ANSWER))
            await wire.settle()
            assert wire.synthesized == [] and wire.socket.pending_cue is not None, 'precondition: the first cue is parked'
            await wire.elapse(HEARING_SECONDS - 0.5)
            assert wire.synthesized == [], 'still inside the expiry time'
            await wire.elapse(0.7)
            assert wire.synthesized == [PORTION], 'the parked cue is played once the listener is no longer heard'
        finally:
            await wire.close()
    asyncio.run(run())


def test_the_repeat_loop_resumes_after_a_phone_barge_in_without_words(tmp_path):
    async def run(signal):
        wire = H.Wire(tmp_path / signal.replace('.', '_').replace(' ', '_'))
        try:
            await wire.begin(ANSWER)
            assert wire.synthesized == [PORTION]
            await wire.socket.client({'type': signal})
            await wire.elapse(HEARING_SECONDS + 0.2)
            await wire.elapse(wire.controller.repeat_seconds + 0.2)
            assert wire.synthesized == [PORTION, PORTION], f'{signal}: the portion is repeated again: {wire.synthesized}'
        finally:
            await wire.close()
    for signal in ('response.cancel', 'input_audio_buffer.clear'):
        asyncio.run(run(signal))


def test_a_retransmitted_turn_created_of_a_final_turn_is_not_a_start_of_speech(tmp_path):
    async def run():
        wire = H.Wire(tmp_path / 'retransmit')
        try:
            await wire.begin(ANSWER)
            await wire.user(PORTION, tid='ack-1')
            assert wire.index == 1 and wire.synthesized[-1] == wire.chunks[1]
            cleared = wire.cleared()
            await wire.socket.provider(H.created('ack-1', 'user', ''))          # the same start, delivered again
            assert not wire.controller.hearing, 'the turn is over: nobody is speaking'
            assert wire.cleared() == cleared, 'and it must not cut off the cue that is playing'
        finally:
            await wire.close()
    asyncio.run(run())


def test_a_retransmitted_turn_created_of_an_unfinished_turn_is_not_news_either(tmp_path):
    async def run():
        wire = H.Wire(tmp_path / 'open')
        try:
            await wire.begin(ANSWER)
            await wire.socket.provider(H.created('u2', 'user', 'Свойство'))
            assert wire.controller.hearing
            wire.controller.hearing = False                                       # (it expired)
            cleared = wire.cleared()
            await wire.socket.provider(H.created('u2', 'user', 'Свойство'))      # the same, still open turn, once more
            assert not wire.controller.hearing and wire.cleared() == cleared, 'a duplicate announces no new speech'
            await wire.socket.provider({'type': 'turn.delta', 'turn_id': 'u2', 'delta': ' вещества', 'start_ms': 5, 'end_ms': 9})   # (not the rest of the cue)
            assert wire.controller.hearing, 'but a transcript that grows again is speech'
        finally:
            await wire.close()
    asyncio.run(run())
