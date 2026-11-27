"""Wave 2 / Task 4: an error is never silence. Every server-side failure ends in a SPOKEN diagnostic.

Before this change ``NativeMediaSocket._error()`` only sent an ``error`` frame, which the iPhone (Conduit) does not
speak: for the user every lookup, synthesis or channel failure was plain silence.

These are fault-injection tests of the REAL chain (ControlledMedia + EchoEngine + NativeMediaSocket + controlled_host.serve)
on the virtual-time rig of tests/helpers_s6_fault.py. Only the boundaries are faked: SAPI, the lookup, the helper pipe,
the phone's websocket and the clock. What the oracle reads is what the phone would get: the frames of a spoken response
(response.created -> transcript -> paced response.audio.delta -> response.done), in the same shape as a normal cue.

Requirement (owner directive 2026-11-01, wave2/task-4-brief.md):
  lookup/search error or timeout .. «Поиск не ответил.» (the controller has a model-knowledge answer) or
                                    «Не нашёл. Повторите вопрос.» (it has not)
  synthesis of a cue fails twice .. «Ошибка звука. Повторите.»   (one retry first)
  GPT-Live channel / helper ....... «Связь прервалась. Повторите вопрос.»
  anything else ................... «Ошибка. Повторите вопрос.»
  at most one phrase per 10 s per session, never a loop; every failure logged with class + reason (no user text);
  the session stays usable.
"""
import json
import logging

import pytest

import helpers_s6_fault as F
from echo_sync.native_media_socket import NO_SOURCE_RESULT
from helpers_spoken_diagnostics import (CHANNEL, EVERY_PHRASE, FIRST_CUE_BOUND, LOOKUP_DEGRADED, LOOKUP_EMPTY, OTHER, SYNTHESIS,
                                        phrases_heard, responses, run_host, run_wire, wav_pcm)


# ======================================================================================================
# 1. synthesis: one retry, then the spoken phrase (from the package when SAPI is down)
# ======================================================================================================

def test_a_cue_that_cannot_be_synthesized_twice_is_followed_by_the_spoken_synthesis_phrase(tmp_path, monkeypatch):
    async def body(rig):
        await rig.ask_direct()
        await rig.advance(8)
        heard = responses(rig.frames)
        assert [r['text'] for r in heard] == [SYNTHESIS], rig.timeline()
        phrase = heard[0]
        assert phrase['status'] == 'completed'
        assert phrase['pcm'] == wav_pcm('synthesis'), 'the phrase must be the packaged audio (nothing was pre-rendered here)'
        assert rig.errors() == ['controlled_synthesis_failed'], 'the error frame stays (probes and logs read it)'
        assert len(rig.synth_plan.calls) == 2, 'exactly one try and one retry of the cue'
    run_wire(tmp_path, monkeypatch, body, synth=['raise', 'raise', 'ok'])


def test_a_diagnostic_is_paced_like_any_other_cue(tmp_path, monkeypatch):
    async def body(rig):
        await rig.ask_direct()
        await rig.advance(8)
        first = next(i for i, f in enumerate(rig.frames) if f.type == 'response.created')
        types = [f.type for f in rig.frames[first:] if f.type != 'error']
        assert types[0] == 'response.created' and types[1] == 'response.audio_transcript.delta', types[:3]
        assert types[-1] == 'response.done' and set(types[2:-1]) == {'response.audio.delta'}, set(types)
        phrase = responses(rig.frames)[0]
        gaps = [round(b - a, 3) for a, b in zip(phrase['times'], phrase['times'][1:])]
        assert gaps and all(gap == pytest.approx(0.02, abs=0.002) for gap in gaps), gaps[:6]
        assert set(phrase['sizes'][:-1]) == {960} and 0 < phrase['sizes'][-1] <= 960
    run_wire(tmp_path, monkeypatch, body, synth=['raise'])


@pytest.mark.parametrize('mode', ['raise', 'empty', 'odd', 'none', 'str'])
def test_one_failed_synthesis_is_retried_and_the_retry_is_heard_with_no_diagnostic(tmp_path, monkeypatch, mode):
    async def body(rig):
        await rig.ask_direct()
        await rig.advance(FIRST_CUE_BOUND)
        heard = responses(rig.frames)
        assert len(heard) == 1 and heard[0]['status'] == 'completed', rig.timeline()
        assert heard[0]['text'] not in EVERY_PHRASE and heard[0]['text'] == rig.controller.state()['chunks'][0]
        assert not rig.errors(), 'a retry that worked is not an error'
        assert len(rig.synth_plan.calls) == 2
    with F.capture_logs() as logs:
        run_wire(tmp_path, monkeypatch, body, synth=[mode, 'ok'])
    assert 'class=synthesis attempt=1/2' in logs.text(), 'even a retried failure is logged, with its class'
    assert 'diagnostic=' not in logs.text(), 'but nothing is reported to the listener: the retry worked'


def test_a_hung_synthesis_uses_up_its_budget_once_and_is_then_announced(tmp_path, monkeypatch):
    """SAPI hangs: a retry cannot get through before the worker gives up, so the 15 s budget covers both tries."""
    async def body(rig):
        t0 = rig.now()
        await rig.ask_direct()
        await rig.advance(40)
        assert len(rig.synth_plan.calls) == 1
        phrase = responses(rig.frames)
        assert [r['text'] for r in phrase] == [SYNTHESIS] and phrase[0]['status'] == 'completed'
        assert phrase[0]['start'] - t0 <= 16, 'the user waited longer than the synthesis budget for the phrase'
    run_wire(tmp_path, monkeypatch, body, synth=['hang', 'ok'])


def test_a_send_failure_in_the_middle_of_a_cue_replays_the_whole_cue_from_the_same_audio(tmp_path, monkeypatch):
    sent = {'n': 0}

    def fault(frame):
        if frame.get('type') == 'response.audio.delta':
            sent['n'] += 1
            if sent['n'] == 2:
                return ConnectionResetError('socket write failed')

    async def body(rig):
        await rig.ask_direct()
        await rig.advance(FIRST_CUE_BOUND)
        whole = [r for r in responses(rig.frames) if r['status'] == 'completed']
        assert len(whole) == 1 and whole[0]['text'] == rig.controller.state()['chunks'][0], rig.timeline()
        assert len(rig.synth_plan.calls) == 1, 'a failed WRITE must not synthesize again'
    run_wire(tmp_path, monkeypatch, body, emit_fault=fault)


# ======================================================================================================
# 2. lookup: «Не нашёл» without a model-knowledge answer, «Поиск не ответил» with one
# ======================================================================================================

@pytest.mark.parametrize('mode', ['raise', 'hang', 'empty', 'garbage'])
def test_a_failed_lookup_is_followed_by_the_spoken_not_found_phrase(tmp_path, monkeypatch, mode):
    """c8 (the owner's rule): a lookup with no source sends the model the no-source result («По памяти: …», no source, no question); «Не нашёл»
    is said when the model then gives nothing either (this rig's model never answers) - after the plain answer wait, once."""
    async def body(rig):
        t0 = rig.now()
        await rig.ask(F.LOOKUP_QUESTION)
        await rig.advance(20)
        heard = responses(rig.frames)
        assert [r['text'] for r in heard] == [LOOKUP_EMPTY], rig.timeline()
        assert heard[0]['status'] == 'completed' and heard[0]['pcm'] == wav_pcm('lookup_empty')
        assert rig.errors() == ['controlled_sources_unavailable']
        told = [json.loads(payload) for kind, payload in rig.source.frames if kind == 'E']
        assert len(told) == 1 and told[0]['content'][0]['text'] == NO_SOURCE_RESULT, 'only the no-source result: no source, no question'
        assert heard[0]['start'] - t0 <= 18, 'the lookup budget (8 s) plus the plain answer wait (8 s) plus the phrase'
    run_wire(tmp_path, monkeypatch, body, lookup=[mode])


def test_when_the_controller_has_a_model_knowledge_answer_the_phrase_is_only_that_the_search_did_not_answer(tmp_path, monkeypatch):
    """White-box: in today's routing a model-knowledge question never starts a lookup, so the flag is set by hand. c8: a failed lookup
    is no longer announced at once (neither «Поиск не ответил» nor «Не нашёл»): the model answers from memory, hedged; only when it gives
    nothing either is «Не нашёл» said."""
    async def body(rig):
        await rig.ask(F.LOOKUP_QUESTION)
        rig.controller.direct_content = True
        await rig.advance(2)
        assert phrases_heard(rig.frames) == [] and rig.controller.source_missing, rig.timeline()
        await rig.advance(18)
        assert phrases_heard(rig.frames) == [LOOKUP_EMPTY], rig.timeline()
        assert LOOKUP_DEGRADED not in phrases_heard(rig.frames)
    run_wire(tmp_path, monkeypatch, body, lookup=['raise'])


def test_the_lookup_failure_of_a_superseded_question_is_not_announced(tmp_path, monkeypatch):
    async def body(rig):
        await rig.ask(F.LOOKUP_QUESTION)                          # its lookup hangs for 8 s
        await rig.advance(1)
        await rig.ask_direct()                                    # a new question takes over
        await rig.advance(20)
        assert phrases_heard(rig.frames) == [], rig.timeline()
        assert not rig.errors(), rig.errors()
        heard = {r['text'] for r in responses(rig.frames)}           # (the cue repeats itself while nobody confirms it)
        assert heard == {rig.controller.state()['chunks'][0]}, heard
    run_wire(tmp_path, monkeypatch, body, lookup=['hang'])


# ======================================================================================================
# 3. channel and everything else
# ======================================================================================================

def test_a_failed_upstream_connect_is_followed_by_the_spoken_channel_phrase(tmp_path, monkeypatch):
    async def body(rig):
        async def broken():
            raise ConnectionError('private token must stay out of the log')
        rig.wire.connect, rig.wire.source = broken, None
        await rig.wire.client({'type': 'session.update', 'session': {}})
        await rig.advance(8)
        assert phrases_heard(rig.frames) == [CHANNEL], rig.timeline()
        assert responses(rig.frames)[0]['pcm'] == wav_pcm('channel')
        assert rig.errors() == ['controlled_upstream_unavailable']
    with F.capture_logs() as logs:
        run_wire(tmp_path, monkeypatch, body)
    assert 'class=channel' in logs.text() and 'reason=ConnectionError' in logs.text()
    assert 'private token' not in logs.text(logging.DEBUG)


def test_an_invalid_pcm_packet_from_the_phone_is_followed_by_the_generic_phrase(tmp_path, monkeypatch):
    async def body(rig):
        await rig.wire.client({'type': 'input_audio_buffer.append', 'audio': '!!!!'})
        await rig.advance(8)
        assert phrases_heard(rig.frames) == [OTHER], rig.timeline()
        assert responses(rig.frames)[0]['pcm'] == wav_pcm('other')
        assert rig.errors() == ['controlled_invalid_pcm']
    run_wire(tmp_path, monkeypatch, body)


def test_a_personal_question_that_cannot_use_the_public_lookup_is_not_followed_by_the_generic_phrase(tmp_path, monkeypatch):
    """F3 (item 2, the owner's call of 3 Nov): «Ошибка. Повторите вопрос.» is no longer what a refused personal question sounds like (the
    model is told "no search, answer from what you know" instead; tests/test_f3_delegation.py). The public lookup is still never reached."""
    async def body(rig):
        await rig.ask('Что у меня в календаре на завтра?')
        await rig.advance(7)                                   # inside the budget of a missing answer
        assert phrases_heard(rig.frames) == [], rig.timeline()
        assert rig.errors() == []
        assert not rig.lookup_plan.calls, 'a personal question must never reach the public lookup'
    run_wire(tmp_path, monkeypatch, body)


# ======================================================================================================
# 4. one phrase per ten seconds, never a loop
# ======================================================================================================

def test_ten_failures_in_a_row_make_one_phrase_per_ten_seconds(tmp_path, monkeypatch):
    async def body(rig):
        for _ in range(10):                                       # t = 0 .. 9: ten failures, one per second
            await rig.wire._error('controlled_invalid_pcm', 'invalid_pcm')
            await rig.advance(1)
        assert phrases_heard(rig.frames) == [OTHER], 'ten failures inside 10 s must be one phrase'
        await rig.advance(0.5)                                    # t = 10.5: the window of the first phrase is over
        await rig.wire._error('controlled_invalid_pcm', 'invalid_pcm')
        await rig.advance(5)
        assert phrases_heard(rig.frames) == [OTHER, OTHER]
        starts = [r['start'] for r in responses(rig.frames)]
        assert starts[1] - starts[0] >= 10
        assert rig.errors().count('controlled_invalid_pcm') == 11, 'every failure still gets its error frame'
    run_wire(tmp_path, monkeypatch, body)


def test_the_window_is_ten_seconds_from_the_start_of_the_previous_phrase(tmp_path, monkeypatch):
    async def body(rig):
        await rig.wire._error('controlled_invalid_pcm', 'invalid_pcm')          # t = 0
        await rig.advance(9.5)
        await rig.wire._error('controlled_invalid_pcm', 'invalid_pcm')          # t = 9.5: inside the window
        await rig.advance(0.5)
        await rig.wire._error('controlled_invalid_pcm', 'invalid_pcm')          # t = 10.0: the window is over
        await rig.advance(5)
        assert len(phrases_heard(rig.frames)) == 2
    run_wire(tmp_path, monkeypatch, body)


def test_a_persistent_fault_cannot_make_the_server_talk_in_a_loop(tmp_path, monkeypatch):
    """Every cue fails, the listener keeps asking: at most one phrase per 10 s, none on its own."""
    async def body(rig):
        for n in range(12):                                       # a question every 5 s for a minute
            await rig.ask_direct(F.DIRECT_QUESTION if n % 2 else F.OTHER_DIRECT_QUESTION,
                                 F.DIRECT_ANSWER if n % 2 else F.OTHER_DIRECT_ANSWER)
            await rig.advance(5)
        starts = [r['start'] for r in responses(rig.frames) if r['text'] == SYNTHESIS]
        assert 1 <= len(starts) <= 6, starts
        assert all(b - a >= 10 for a, b in zip(starts, starts[1:])), starts
        quiet_from = rig.now()
        await rig.advance(120)                                    # nobody asks: nothing may talk or repeat
        assert not [f for f in rig.frames if f.type == 'response.created' and f.t >= quiet_from]
    run_wire(tmp_path, monkeypatch, body, synth=['raise'])


# ======================================================================================================
# 5. the phrase obeys barge-in, and the session stays usable
# ======================================================================================================

def test_the_user_starting_to_speak_cuts_a_diagnostic_that_is_still_playing(tmp_path, monkeypatch):
    async def body(rig):
        await rig.ask(F.LOOKUP_QUESTION)
        await rig.advance(8.3)                                    # c8: «Не нашёл» once the model, told to answer from memory, gave nothing
        F.precondition(phrases_heard(rig.frames) == [LOOKUP_EMPTY] and not responses(rig.frames)[0]['status'],
                       'the phrase is playing')
        t_speech = rig.now()
        await rig.feed({'type': 'input_audio_buffer.speech_started'})
        await rig.advance(5)
        phrase = responses(rig.frames)[0]
        assert phrase['status'] is None, 'a cut phrase must not be completed'
        assert all(t <= t_speech + 0.001 for t in phrase['times']), 'audio after the user started to speak'
        assert any(f.type == 'output_audio_buffer.clear' and f.t >= t_speech for f in rig.frames)
    run_wire(tmp_path, monkeypatch, body, lookup=['raise'])


def test_without_any_audio_for_a_phrase_the_failure_is_still_logged_and_the_window_is_not_used_up(tmp_path, monkeypatch):
    from echo_sync import diagnostics

    async def body(rig):
        rig.wire.diagnostic_audio = diagnostics.DiagnosticAudio(tmp_path / 'nothing-here')      # no pre-render, no packaged WAV
        await rig.wire._error('controlled_invalid_pcm', 'invalid_pcm')
        await rig.advance(1)
        assert not responses(rig.frames) and rig.errors() == ['controlled_invalid_pcm']
        rig.wire.diagnostic_audio._rendered['other'] = F.pcm(0.2)                               # audio is there a second later
        await rig.wire._error('controlled_invalid_pcm', 'invalid_pcm')
        await rig.advance(2)
        assert phrases_heard(rig.frames) == [OTHER], 'a failure that could not be spoken must not start the 10 s window'
    with F.capture_logs() as logs:
        run_wire(tmp_path, monkeypatch, body)
    assert 'diagnostic=no_audio' in logs.text(logging.WARNING)


def test_a_failure_after_the_call_has_closed_starts_nothing(tmp_path, monkeypatch):
    async def body(rig):
        await rig.wire.close()
        await rig.wire._error('controlled_invalid_pcm', 'invalid_pcm')
        await rig.advance(5)
        assert not responses(rig.frames) and not rig.wire.tasks and not rig.errors()
        t0 = rig.now()
        await rig.wire.finish_diagnostic()                        # nothing is playing: returns at once
        assert rig.now() == t0
    with F.capture_logs() as logs:
        run_wire(tmp_path, monkeypatch, body)
    assert 'diagnostic=closed' in logs.text(logging.WARNING)


def test_a_diagnostic_never_talks_over_a_cue_that_is_still_playing(tmp_path, monkeypatch):
    """Two spoken responses must never overlap on the phone. U94.6 (the row ``may_sound`` of the one gate, ``ControlledMedia._step_may_sound``) replaced the
    old takeover (the cue cut, the phrase said): a cue of the open question that has begun is the answer the listener waits for, the phrase is parked, the
    cue plays to its end and is not cleared on the phone. The error frame stays for the evidence. (Replaces the two tests of the takeover.)"""
    async def body(rig):
        async def a_second_of_speech(text):
            return F.pcm(1.0)
        rig.wire.synthesize = a_second_of_speech
        await rig.ask_direct()
        await rig.advance(0.3)
        F.precondition(len(responses(rig.frames)) == 1 and not responses(rig.frames)[0]['status'], 'the cue is playing')
        await rig.wire.client({'type': 'input_audio_buffer.append', 'audio': '!!!!'})     # a failure while it plays
        await rig.advance(8)
        heard = responses(rig.frames)
        assert [r['text'] for r in heard if r['text'] == OTHER] == [], 'the phrase talked over the cue'
        assert heard[0]['status'] == 'completed', 'the cue was cut'
        assert not rig.of_type('output_audio_buffer.clear'), 'nothing is cleared on the phone: the cue plays to its end'
        assert rig.errors() == ['controlled_invalid_pcm'], rig.errors()
    run_wire(tmp_path, monkeypatch, body)


def test_a_diagnostic_over_silence_sends_no_clear(tmp_path, monkeypatch):
    async def body(rig):
        await rig.wire.client({'type': 'input_audio_buffer.append', 'audio': '!!!!'})
        await rig.advance(8)
        assert phrases_heard(rig.frames) == [OTHER]
        assert not rig.of_type('output_audio_buffer.clear'), 'nothing was playing: there is nothing to clear'
    run_wire(tmp_path, monkeypatch, body)


def test_a_diagnostic_cancels_a_cue_whose_synthesis_is_still_running(tmp_path, monkeypatch):
    """Not just muted by the generation counter: a superseded cue must not report its own failure 15 s later."""
    async def body(rig):
        await rig.ask_direct()                                   # the synthesis of the first cue hangs
        await rig.advance(1)
        await rig.wire.client({'type': 'input_audio_buffer.append', 'audio': '!!!!'})
        await rig.advance(40)
        assert rig.errors() == ['controlled_invalid_pcm'], rig.errors()
        assert phrases_heard(rig.frames) == [OTHER]
        assert len(rig.synth_plan.calls) == 1, 'the superseded cue was retried'
    run_wire(tmp_path, monkeypatch, body, synth=['hang'])


def test_after_a_spoken_diagnostic_the_next_question_is_answered_normally(tmp_path, monkeypatch):
    async def body(rig):
        await rig.ask(F.LOOKUP_QUESTION)
        await rig.advance(15)
        F.precondition(phrases_heard(rig.frames) == [LOOKUP_EMPTY], 'the diagnostic was spoken')
        rig.lookup_plan.steps = ['ok']
        t1 = rig.now()
        await rig.ask_with_lookup()
        await rig.advance(FIRST_CUE_BOUND)
        cues = [r for r in responses(rig.frames) if r['start'] >= t1 and r['text'] not in EVERY_PHRASE]
        assert cues and cues[0]['status'] == 'completed' and cues[0]['start'] - t1 <= FIRST_CUE_BOUND + 1
        t2 = rig.now()
        await rig.ask_direct(F.OTHER_DIRECT_QUESTION, F.OTHER_DIRECT_ANSWER)
        await rig.advance(FIRST_CUE_BOUND)
        assert [r for r in responses(rig.frames) if r['start'] >= t2 and r['status'] == 'completed']
    run_wire(tmp_path, monkeypatch, body, lookup=['raise', 'ok'])


# ======================================================================================================
# 6. every failure is logged with its class and reason, never with the user's words
# ======================================================================================================

LOGGED_CASES = {
    'lookup': ('class=lookup', 'reason=InjectedLookupFault'),
    'synthesis': ('class=synthesis', 'reason=InjectedSapiFault'),
    'channel': ('class=channel', 'reason=ConnectionError'),
    'other': ('class=other', 'reason=invalid_pcm'),
}


@pytest.mark.parametrize('kind', list(LOGGED_CASES))
def test_a_failure_is_logged_with_class_and_reason_and_without_the_users_words(tmp_path, monkeypatch, kind):
    async def body(rig):
        if kind == 'lookup':
            await rig.ask(F.LOOKUP_QUESTION)
        elif kind == 'synthesis':
            await rig.ask_direct()
        elif kind == 'channel':
            async def broken():
                raise ConnectionError('secret-token-1234 and the private question')
            rig.wire.connect, rig.wire.source = broken, None
            await rig.wire.client({'type': 'session.update', 'session': {}})
        else:
            await rig.wire.client({'type': 'input_audio_buffer.append', 'audio': '!!!!'})
        await rig.advance(20)
        F.precondition(rig.errors(), 'the failure must have happened')
    with F.capture_logs() as logs:
        run_wire(tmp_path, monkeypatch, body, lookup=['raise'], synth=['raise'])
    text = logs.text(logging.WARNING)
    for needle in LOGGED_CASES[kind]:
        assert needle in text, f'{needle!r} missing from the WARNING+ records: {text!r}'
    everything = logs.text(logging.DEBUG)
    for private in ('secret-token-1234', 'private question', 'Что устанавливает', 'Что такое инерция', 'статья 218'):
        assert private not in everything, f'{private!r} leaked into the log'


# ======================================================================================================
# 7. through controlled_host.serve: pre-render at start, packaged audio when SAPI is down, close after the phrase
# ======================================================================================================

def test_the_host_prerenders_every_phrase_once_at_start_and_never_at_failure_time(tmp_path, monkeypatch):
    async def body(host):
        calls = [text for _, text in host.synth_plan.calls]
        assert sorted(calls) == sorted(EVERY_PHRASE), f'pre-render at start: {calls}'
        host.synth_plan.calls.clear()
        host.synth_plan.steps = ['raise']
        await host.ask(F.DIRECT_QUESTION)
        await host.answer(F.DIRECT_ANSWER)
        await host.advance(8)
        assert not [t for _, t in host.synth_plan.calls if t in EVERY_PHRASE], 'a failure must not synthesize its phrase'
    run_host(tmp_path, monkeypatch, body)


def test_the_phrase_comes_from_the_prerendered_pcm_while_sapi_still_worked_at_start(tmp_path, monkeypatch):
    async def body(host):
        host.synth_plan.calls.clear()
        host.synth_plan.steps = ['raise']                          # SAPI breaks AFTER the start of the call
        await host.ask(F.DIRECT_QUESTION)
        await host.answer(F.DIRECT_ANSWER)
        await host.advance(8)
        heard = responses(host.ws.frames)
        assert [r['text'] for r in heard] == [SYNTHESIS], heard
        prerendered = b'\x01\x02' * 2400                            # what FakeWorker writes: 0.1 s of PCM, not the package
        assert heard[0]['pcm'] == prerendered != wav_pcm('synthesis')
    run_host(tmp_path, monkeypatch, body)


def test_when_sapi_is_broken_from_the_start_the_packaged_audio_is_spoken(tmp_path, monkeypatch):
    async def body(host):
        assert len(host.synth_plan.calls) == 1, 'a broken SAPI is tried once at start, not hammered'
        await host.ask(F.DIRECT_QUESTION)
        await host.answer(F.DIRECT_ANSWER)
        await host.advance(8)
        heard = responses(host.ws.frames)
        assert [r['text'] for r in heard] == [SYNTHESIS] and heard[0]['status'] == 'completed'
        assert heard[0]['pcm'] == wav_pcm('synthesis')
        assert host.errors() == ['controlled_synthesis_failed']
    run_host(tmp_path, monkeypatch, body, synth=['raise'])


def test_a_failing_quick_lookup_through_the_real_closure_is_announced_with_the_not_found_phrase(tmp_path, monkeypatch):
    async def body(host):
        await host.ask(F.LOOKUP_QUESTION)
        await host.advance(12)
        assert [r['text'] for r in responses(host.ws.frames)] == [LOOKUP_EMPTY]
        assert host.errors() == ['controlled_sources_unavailable']
    run_host(tmp_path, monkeypatch, body, lookup=['failed'])


def test_a_helper_loss_is_spoken_before_the_socket_is_closed(tmp_path, monkeypatch):
    async def body(host):
        closed_at = []
        real_close = host.ws.close

        async def close(code=1000):
            closed_at.append(host.now())
            await real_close(code)
        host.ws.close = close
        await host.ask(F.DIRECT_QUESTION)
        host.cloud(F.created('a1', 'assistant', 'Инерция — это'))
        await host.advance(0.3)
        t_loss = host.now()
        host.bridge.push('X', b'')
        assert await host.until(lambda: host.finished, 8), 'serve did not end after the helper loss'
        phrase = [r for r in responses(host.ws.frames) if r['text'] == CHANNEL]
        assert phrase and phrase[0]['status'] == 'completed', host.ws.frames[-6:]
        assert closed_at and phrase[0]['end'] <= closed_at[0], 'the socket was closed before the phrase reached the phone'
        assert host.ws.close_code == 1011 and host.now() - t_loss <= 6
        assert 'controlled_upstream_closed' in host.errors(t_loss)
    run_host(tmp_path, monkeypatch, body)


def test_invalid_json_from_the_phone_is_followed_by_the_generic_phrase_and_the_call_goes_on(tmp_path, monkeypatch):
    async def body(host):
        host.ws.push('this is not json')
        await host.advance(6)
        assert not host.finished
        assert [r['text'] for r in responses(host.ws.frames)] == [OTHER]
        assert host.errors() == ['controlled_invalid_json']
    run_host(tmp_path, monkeypatch, body)


def test_the_host_logs_every_error_frame_with_the_call_id_at_warning_level(tmp_path, monkeypatch):
    async def body(host):
        host.ws.push('this is not json')
        await host.advance(1)
        text = host.logger.text(logging.WARNING)
        assert 'controlled_invalid_json' in text and 'call=' in text, text
    run_host(tmp_path, monkeypatch, body)


def test_diagnostics_missing_from_the_deployed_package_are_reported_at_the_start_of_the_call(tmp_path, monkeypatch):
    """The deploy script copies only *.py: a forgotten diag_audio folder must not be a silent hole."""
    from echo_sync import diagnostics
    monkeypatch.setattr(diagnostics, 'ASSET_DIR', tmp_path / 'not-deployed')

    async def body(host):
        await host.advance(1)
        assert not host.errors()
    with F.capture_logs() as logs:
        run_host(tmp_path, monkeypatch, body, synth=['raise'])
    text = logs.text(logging.WARNING).lower()
    assert 'diagnostic' in text and 'missing' in text, text


def test_the_prerender_does_not_delay_the_first_cue_and_leaves_no_task_behind(tmp_path, monkeypatch):
    async def body(host):
        t0 = host.now()
        await host.ask(F.DIRECT_QUESTION)
        await host.answer(F.DIRECT_ANSWER)
        await host.advance(FIRST_CUE_BOUND)
        cue = [r for r in responses(host.ws.frames) if r['text'] not in EVERY_PHRASE]
        assert cue and cue[0]['status'] == 'completed' and cue[0]['start'] - t0 <= FIRST_CUE_BOUND
        assert not host.errors()
    run_host(tmp_path, monkeypatch, body)
