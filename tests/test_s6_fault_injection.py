"""S6 / axis "fault": fault injection against the REAL ECHO chain.

Required behaviour (owner's directives 2026-11-01, §1 and §3): any error ends in an audible outcome (a cue,
a retried cue or a short spoken diagnostic) within a bounded time, never in silence and never in a hang;
the session stays usable for the next question; the error is logged with a reason; «стоп» always works.

What is real here: ControlledMedia + EchoEngine (SQLite), NativeMediaSocket, controlled_host.serve (its
ticker, reader, lookup and synthesize closures, open_subscription), helper_bridge framing, portioner,
first_useful. What is faked, only at the external boundary: the clock (virtual-time loop), SAPI, the
lookup, the GPT-Live helper pipe and the phone's websocket. See tests/helpers_s6_fault.py.

Tests encode the requirement, not the present behaviour. A requirement that the code does not meet is an
``xfail(strict=True)`` with its defect id: DEF-FAULT-NN (listed in DEFECTS). When a fix lands, the strict
xfail turns into a failure, which is the signal to delete the marker.
"""
import ast
import asyncio
import functools
import json
import logging
import re
import sqlite3
import tempfile
import time
from pathlib import Path

from cm_patch import patch_controller
import pytest
from hypothesis import HealthCheck, example, given, settings, strategies as st

import helpers_s6_fault as F
from echo_sync import cm_probes, controlled_host, controlled_media, engine as engine_module
from engine_say import engine_reply

RECOVERY_BOUND = 30.0     # virtual seconds in which a fault must have ended in an audible outcome
FIRST_CUE_BOUND = 3.0     # directive §1: practical bound for a short question without search
MAX_ATTEMPTS = 10         # a retry of one failing cue must be bounded: no storm

# DEF-FAULT-01 (a failed synthesis is never retried and nothing is spoken), DEF-FAULT-02 (a failed lookup ends in an error frame
# only) and the wire / host / TTS-provider part of DEF-FAULT-09 (failures logged with class and reason) were fixed by Wave 2 /
# Task 4 (spoken diagnostics): their markers are gone, their tests are ordinary tests now. DEF-FAULT-14 (a start of speech with no
# transcript, or a duplicate turn.created, held «the user is speaking» for good) was fixed by Wave 2 / Task B (HEARING_SECONDS), and
# DEF-FAULT-10 (one exception in a tick stopped every timer of the call) by the same task (the host ticker survives a failing tick).
# DEF-FAULT-03 (no watchdog on the answer: a silent cloud left the question silent for ever) was fixed by Wave 2 / Task D (ANSWER_WAIT_SECONDS).
# DEF-FAULT-11 (a stalled helper pipe blocked the loop that reads the phone) and DEF-FAULT-12 (a failing helper close aborted the cleanup of serve)
# by the same task (helper_bridge.BoundedWriter, a bounded close, a cleanup whose steps cannot skip each other).
# The same watchdog is the net under the *audible outcome* tests of DEF-FAULT-04 (five helpers) and DEF-FAULT-05 (portions() swallowed
# by EchoEngine.reply): when the cloud's answer arrives and the segmentation chain fails, no cue is made and, after the wait, the listener
# hears «Нет ответа. Повторите вопрос.» (class=answer reason=no_usable_text in the log). Those six markers are gone. The ROOT causes
# stay open and keep their other tests: the exception still escapes ControlledMedia.provider (DEF-FAULT-04, tests below that say
# "does not escape the wire"), and engine.py still logs no cause (DEF-FAULT-09).
DEFECTS = {
    6: 'the stream frontier waits forever for text from a producer that is gone: the last repeat gets silence (red with RapidFuzz installed, as on the laptop; green only without it)',
    4: 'an exception inside first_useful/portioner/textutil helpers escapes ControlledMedia.provider and tears the call down',
    7: 'one unparsable or non-object helper event ends the whole call (reader dies, ws closed 1011)',
    8: 'an unhashable type/id in a provider or client frame raises TypeError out of the wire (call torn down)',
    13: 'classic engine: a failed generation of a plain question returns NO_REPLY (silent) and logs no reason',
}


def defect(number):
    return pytest.mark.xfail(strict=True, raises=AssertionError, reason=f'DEF-FAULT-{number:02d}: {DEFECTS[number]}')


def run_wire(tmp_path, monkeypatch, body, **rig):
    """Run ``body(rig)`` on a virtual-time loop with the real wire chain."""
    __tracebackhide__ = True

    async def main():
        __tracebackhide__ = True
        F.patch_clock(monkeypatch)
        async with F.WireRig(tmp_path, **rig) as wire_rig:
            return await body(wire_rig)
    return F.run(main)


def run_host(tmp_path, monkeypatch, body, *, handshake=True, **rig):
    """Run ``body(host)`` against controlled_host.serve with a fake phone and a fake helper pipe."""
    __tracebackhide__ = True

    async def main():
        __tracebackhide__ = True
        F.patch_clock(monkeypatch)
        async with F.HostRig(tmp_path, monkeypatch, **rig) as host:
            if handshake:
                await host.handshake()
            return await body(host)
    return F.run(main)


def assert_audible(rig, since, what, within=RECOVERY_BOUND):
    __tracebackhide__ = True
    ok, why = F.audible_report(rig, since, within)
    assert ok, f'{what}: {why}'


def logged(catcher, *needles, minimum=logging.WARNING):
    """True when a log record at ``minimum`` or above mentions every needle (case-insensitive)."""
    text = catcher.text(minimum).lower()
    return all(needle.lower() in text for needle in needles)


# ======================================================================================================
# 0. the rig itself must be faithful and its clock honest
# ======================================================================================================

def test_rig_wires_the_real_classes_exactly_like_controlled_host_serve():
    source = Path(controlled_host.__file__).read_text(encoding='utf-8')
    tree = ast.parse(source)
    media = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, 'id', None) == 'ControlledMedia']
    assert len(media) == 1
    host = {k.arg: ast.literal_eval(k.value) for k in media[0].keywords if isinstance(k.value, ast.Constant)}
    assert host == F.HOST_KWARGS
    assert [ast.unparse(k.value) for k in media[0].keywords if k.arg == 'settings'] == ['controller_settings(profile_settings)']      # ROOT-1: the host builds the controller's settings once, at construction
    wires = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, 'id', None) == 'NativeMediaSocket']
    assert len(wires) == 1
    assert [a.id for a in wires[0].args] == ['controller', 'emit', 'connect', 'lookup', 'synthesize']
    # w8-net: audio_head_ms comes from the profile, off (0) by default - the rig's wire keeps that default (U77: mic_path is gone).
    # c22-merge: c21/0002 (the server's local mode) adds local_fallback, from the profile, off by default - the rig's wire keeps it off too
    # (tests/test_local_fallback.py drives it on)
    assert {k.arg for k in wires[0].keywords} == {'diagnostics', 'prefetch', 'audio_head_ms', 'local_fallback', 'voice_gain', 'voice_presence'}  # + c22-voice
    # the ticker the rig copies (WireRig._start_ticker): a wait of at most 0.1 s, then wire.tick(), until the wire closes
    ticks = [n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == 'tick']
    assert len(ticks) == 1, 'serve() no longer has exactly one ticker: update WireRig._start_ticker'
    calls = [c for c in ast.walk(ticks[0]) if isinstance(c, ast.Call)]
    waits = [c for c in calls if ast.unparse(c.func) == 'waker.wait']      # one-timers: the tick is woken by events, 0.1 s (WAKE_TICK_S) is its ceiling, which the rig's sleep copies
    assert len(waits) == 1 and controlled_host.WAKE_TICK_S == 0.1
    assert any(ast.unparse(c.func) == 'wire.tick' for c in calls)


def test_virtual_clock_makes_long_timeouts_cheap_and_real_hangs_visible():
    async def waits():
        loop = asyncio.get_running_loop()
        t0 = loop.time()
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(asyncio.Event().wait(), 15)
        assert loop.time() - t0 == pytest.approx(15, abs=0.5)
        await asyncio.sleep(100)
        assert loop.time() - t0 >= 115

    started = time.monotonic()
    F.run(waits)
    assert time.monotonic() - started < 5

    async def nothing_will_ever_happen():
        await asyncio.Event().wait()
    with pytest.raises(F.VirtualClockDeadlock):
        F.run(nothing_will_ever_happen)


def test_virtual_clock_never_times_out_a_worker_thread_job_that_is_still_running():
    async def main():
        loop = asyncio.get_running_loop()
        t0 = loop.time()
        await asyncio.wait_for(asyncio.to_thread(time.sleep, 0.2), 15)
        assert loop.time() - t0 < 1
    F.run(main)


# ======================================================================================================
# 1. controls: the unfaulted chain is audible, so a fault test fails for the fault and not for the rig
# ======================================================================================================

def test_control_a_direct_question_is_audible_within_the_first_cue_bound(tmp_path, monkeypatch):
    async def body(rig):
        t0 = rig.now()
        await rig.ask_direct()
        await rig.advance(FIRST_CUE_BOUND)
        assert_audible(rig, t0, 'healthy direct question', FIRST_CUE_BOUND)
        assert rig.spoken() and not rig.errors()
    run_wire(tmp_path, monkeypatch, body)


def test_control_a_lookup_question_reaches_the_helper_and_is_audible(tmp_path, monkeypatch):
    async def body(rig):
        t0 = rig.now()
        await rig.ask_with_lookup()
        await rig.advance(FIRST_CUE_BOUND)
        assert [kind for kind, _ in rig.source.frames] and {kind for kind, _ in rig.source.frames} == {'E'}
        assert_audible(rig, t0, 'healthy lookup question', FIRST_CUE_BOUND + 1)
    run_wire(tmp_path, monkeypatch, body)


def test_control_the_host_chain_is_audible_end_to_end(tmp_path, monkeypatch):
    async def body(host):
        t0 = host.now()
        await host.ask(F.DIRECT_QUESTION)
        await host.answer(F.DIRECT_ANSWER)
        await host.advance(2)
        assert host.audio(t0) and host.spoken(t0) and not host.errors(t0)
        assert not host.finished
    run_host(tmp_path, monkeypatch, body)


# ======================================================================================================
# 2. SAPI synthesis faults (raises / times out / empty or malformed audio)
# ======================================================================================================

TTS_FAULTS = ['raise', 'empty', 'odd', 'none', 'hang']      # exception / 0 bytes / odd length / not bytes / never returns


@pytest.mark.parametrize('mode', TTS_FAULTS)
def test_a_first_cue_that_fails_to_synthesize_still_ends_in_an_audible_outcome(tmp_path, monkeypatch, mode):
    """The first attempt fails, every later one would work: a retry (or a spoken diagnostic) must be heard."""
    async def body(rig):
        t0 = rig.now()
        await rig.ask_direct()
        await rig.advance(RECOVERY_BOUND)
        assert_audible(rig, t0, f'synthesis fault {mode!r} on the first cue')
    run_wire(tmp_path, monkeypatch, body, synth=[mode, 'ok'])


def test_a_persistent_synthesis_fault_is_bounded_reported_and_leaves_the_cursor_alone(tmp_path, monkeypatch):
    async def body(rig):
        await rig.ask_direct()
        await rig.advance(120)
        attempts = len(rig.synth_plan.calls)
        assert 1 <= attempts <= MAX_ATTEMPTS, f'{attempts} synthesis attempts in 120 s: a retry storm or no attempt'
        codes = rig.errors()
        assert codes and all(re.fullmatch(r'[a-z_]{5,60}', code) for code in codes), codes
        state = rig.controller.state()
        assert state['chunk_index'] == 0 and not state['completed'], 'a failed cue must not move the cursor'
    run_wire(tmp_path, monkeypatch, body, synth=['raise'])


def test_the_session_is_usable_after_a_synthesis_fault(tmp_path, monkeypatch):
    # Task 4: a failed cue is retried once, so the fault has to hit the retry too ('raise', 'raise'); the spoken diagnostic
    # then plays instead of the cue (this guard used to assert that nothing at all was completed).
    async def body(rig):
        await rig.ask_direct()
        await rig.advance(2)
        F.precondition(rig.errors(), 'the first cue failed (twice)')
        assert rig.controller.state()['chunks'][0] not in rig.spoken(), 'the cue whose synthesis failed must not be heard'
        t_repeat = rig.now()
        await rig.hear('Повтори')                                # «повтори» replays without a model call
        await rig.advance(FIRST_CUE_BOUND)
        assert_audible(rig, t_repeat, 'repeat after a failed first cue', FIRST_CUE_BOUND)
        assert rig.spoken(t_repeat)[0] == rig.controller.state()['chunks'][0]
        t_next = rig.now()
        await rig.ask_direct(F.OTHER_DIRECT_QUESTION, F.OTHER_DIRECT_ANSWER)
        await rig.advance(FIRST_CUE_BOUND)
        assert_audible(rig, t_next, 'next question after a synthesis fault', FIRST_CUE_BOUND)
    run_wire(tmp_path, monkeypatch, body, synth=['raise', 'raise', 'ok'])


def test_a_hung_synthesis_is_given_up_within_its_budget(tmp_path, monkeypatch):
    async def body(rig):
        t0 = rig.now()
        await rig.ask_direct()
        await rig.advance(40)
        frames = rig.of_type('error')
        assert frames, 'a hung synthesis was never reported'
        assert frames[0].t - t0 <= 20, f'gave up after {frames[0].t - t0:.1f}s'
        # Task 4: the only audio is the spoken diagnostic (this guard used to assert there was no audio at all).
        assert set(rig.spoken()) == {'Ошибка звука. Повторите.'}, 'a cue was played although its synthesis hung'
    run_wire(tmp_path, monkeypatch, body, synth=['hang'])


def test_a_slow_synthesis_result_of_a_superseded_cue_is_never_played(tmp_path, monkeypatch):
    async def body(rig):
        await rig.ask_direct()                                   # cue 1 is requested; SAPI needs 8 s
        await rig.advance(2)
        t_second = rig.now()
        await rig.ask_direct(F.OTHER_DIRECT_QUESTION, F.OTHER_DIRECT_ANSWER)
        await rig.advance(12)                                    # cue 1's PCM arrives at +8 s: stale
        spoken = rig.spoken(t_second)
        assert spoken, 'the second question was never answered aloud'
        for text in spoken:
            assert text.lower() in F.OTHER_DIRECT_ANSWER.lower(), f'a cue of the superseded question was played: {text!r}'
    run_wire(tmp_path, monkeypatch, body, synth=[('slow', 8), 'ok'])


@pytest.mark.parametrize('mode', ['raise', 'hang'])
def test_a_synthesis_fault_is_logged_with_its_reason(tmp_path, monkeypatch, mode):
    async def body(rig):
        await rig.ask_direct()
        await rig.advance(40)
        F.precondition(rig.errors(), 'the synthesis fault must have happened')
    with F.capture_logs() as logs:
        run_wire(tmp_path, monkeypatch, body, synth=[mode])
    assert logged(logs, 'synth'), f'no WARNING+ record names the synthesis failure; records: {logs.text()!r}'
    assert logged(logs, 'InjectedSapiFault' if mode == 'raise' else 'timeout') or logged(logs, 'controlled_synthesis_failed'), \
        'a record exists but gives no cause'


def test_a_send_failure_in_the_middle_of_a_cue_is_recovered_with_a_whole_cue(tmp_path, monkeypatch):
    sent = {'n': 0}

    def fault(frame):
        if frame.get('type') == 'response.audio.delta':
            sent['n'] += 1
            if sent['n'] == 2:
                return ConnectionResetError('socket write failed')

    async def body(rig):
        t0 = rig.now()
        await rig.ask_direct()
        await rig.advance(RECOVERY_BOUND)
        assert_audible(rig, t0, 'a cue cut off by a failed socket write')
    run_wire(tmp_path, monkeypatch, body, emit_fault=fault)


# ======================================================================================================
# 3. lookup faults (raises / exceeds its timeout / empty or garbage result)
# ======================================================================================================

LOOKUP_FAULTS = ['raise', 'hang', 'empty', 'garbage']


@pytest.mark.parametrize('mode', LOOKUP_FAULTS)
def test_a_question_whose_lookup_fails_still_ends_in_an_audible_outcome(tmp_path, monkeypatch, mode):
    async def body(rig):
        t0 = rig.now()
        await rig.ask(F.LOOKUP_QUESTION)
        await rig.advance(RECOVERY_BOUND)
        assert_audible(rig, t0, f'lookup fault {mode!r}')
    run_wire(tmp_path, monkeypatch, body, lookup=[mode])


def test_a_hung_lookup_is_given_up_within_its_budget_and_reported(tmp_path, monkeypatch):
    async def body(rig):
        t0 = rig.now()
        await rig.ask(F.LOOKUP_QUESTION)
        await rig.advance(30)
        frames = rig.of_type('error')
        # c8: given up at its 8 s budget, the model told to answer from memory (no source), reported when it then gives nothing (8 s)
        assert frames and frames[0].t - t0 <= 18, [f.t - t0 for f in frames]
        told = [json.loads(payload) for kind, payload in rig.source.frames if kind == 'E']
        assert len(told) == 1 and 'source_data' not in json.dumps(told, ensure_ascii=False), 'no source may be sent for a failed lookup'
    run_wire(tmp_path, monkeypatch, body, lookup=['hang'])


def test_lookup_failure_never_leaks_the_private_question_or_error_text(tmp_path, monkeypatch):
    async def body(rig):
        await rig.ask(F.LOOKUP_QUESTION)
        await rig.advance(10)                                     # c8: reported once the model, told to answer from memory, gave nothing
        # (the user's own transcript frame legitimately carries the question; the exception text must not appear)
        blob = json.dumps([f.data for f in rig.frames], ensure_ascii=False)
        assert 'private question text' not in blob
        assert rig.errors()
    with F.capture_logs() as logs:
        run_wire(tmp_path, monkeypatch, body, lookup=['raise'])
    assert 'private question text' not in logs.text(logging.DEBUG)


def test_the_session_is_usable_after_a_lookup_fault(tmp_path, monkeypatch):
    async def body(rig):
        await rig.ask(F.LOOKUP_QUESTION)
        await rig.advance(3)
        t1 = rig.now()
        await rig.ask_direct()
        await rig.advance(FIRST_CUE_BOUND)
        assert_audible(rig, t1, 'direct question after a failed lookup', FIRST_CUE_BOUND)
        t2 = rig.now()
        await rig.ask_with_lookup()
        await rig.advance(FIRST_CUE_BOUND)
        assert_audible(rig, t2, 'lookup question after a failed lookup', FIRST_CUE_BOUND + 1)
    run_wire(tmp_path, monkeypatch, body, lookup=['raise', 'ok'])


def test_a_lookup_result_that_arrives_after_a_new_question_is_discarded(tmp_path, monkeypatch):
    second = 'Что устанавливает статья 15 ТК РФ?'

    async def body(rig):
        await rig.ask(F.LOOKUP_QUESTION)                         # its lookup needs 5 s (budget: 8 s)
        await rig.advance(1)
        t_new = rig.now()
        await rig.ask(second)                                    # its lookup needs 6 s: the old result lands first
        await rig.advance(12)
        sent = ''.join(json.loads(payload)['content'][0]['text'] for kind, payload in rig.source.frames if kind == 'E')
        assert 'ТК РФ' in sent, 'precondition: the second question was sent to the model'
        assert '218' not in sent and 'ГК РФ' not in sent, 'the context of the superseded question reached the model'
        assert not rig.errors(t_new), rig.errors(t_new)
    run_wire(tmp_path, monkeypatch, body, lookup=[('slow', 5), ('slow', 6)])


@pytest.mark.parametrize('mode', ['raise', 'hang'])
def test_a_lookup_fault_is_logged_with_its_reason(tmp_path, monkeypatch, mode):
    async def body(rig):
        await rig.ask(F.LOOKUP_QUESTION)
        await rig.advance(20)
        F.precondition(rig.errors(), 'the lookup fault must have happened')
    with F.capture_logs() as logs:
        run_wire(tmp_path, monkeypatch, body, lookup=[mode])
    assert logged(logs, 'lookup') or logged(logs, 'sources'), f'no WARNING+ record names the lookup failure: {logs.text()!r}'
    assert logged(logs, 'InjectedLookupFault' if mode == 'raise' else 'timeout') or logged(logs, 'controlled_sources_unavailable'), \
        'a record exists but gives no cause'


# ======================================================================================================
# 4. the cloud side: no usable answer, an answer cut off by a lost producer
# ======================================================================================================

SILENT_CLOUD = ['nothing_at_all', 'only_a_service_phrase', 'empty_final', 'only_the_question_echoed']


@pytest.mark.parametrize('kind', SILENT_CLOUD)
def test_a_question_that_gets_no_usable_answer_ends_in_an_audible_outcome(tmp_path, monkeypatch, kind):
    """Nobody errors, nobody answers: the user must still be told something within a bounded time."""
    async def body(rig):
        t0 = rig.now()
        await rig.ask(F.DIRECT_QUESTION)
        if kind == 'only_a_service_phrase':
            await rig.answer('Сейчас уточню.')
        elif kind == 'empty_final':
            await rig.feed(F.done('a1', 'assistant', ''))
        elif kind == 'only_the_question_echoed':
            await rig.answer('Инерция — это инерция.')
        await rig.advance(RECOVERY_BOUND)
        assert_audible(rig, t0, f'cloud gave {kind}')
    run_wire(tmp_path, monkeypatch, body)


STREAM = ('Инерция — это свойство тела сохранять своё состояние покоя или равномерного прямолинейного движения, '
          'пока на него не подействует внешняя сила. Чем больше масса, тем сильнее инерция.')


async def stream_part_of_the_answer(rig, words=14):
    """The producer sends the beginning of the answer and never finishes it (no turn.done)."""
    await rig.ask(F.DIRECT_QUESTION)
    pieces = STREAM.split(' ')
    await rig.feed(F.created('a1', 'assistant', pieces[0]))
    for n, word in enumerate(pieces[1:words], 1):
        await rig.feed(F.delta('a1', ' ' + word, n))
        await rig.advance(0.05)
    await rig.advance(1)


async def confirm_every_available_portion(rig):
    """The user repeats each portion they are given, until the system has nothing more to give.

    Returns the time of the last confirmation (the user has now done everything asked of them)."""
    last = rig.now()
    for _ in range(20):
        state = rig.controller.state() or {}
        if state.get('completed') or state.get('stream_waiting_next') or rig.current_portion() is None:
            break
        await rig.repeat_current()
        last = rig.now()
        await rig.advance(1.5)
    return last


@pytest.mark.parametrize('how', [pytest.param('producer_stalls', marks=defect(6)),
                                 pytest.param('helper_lost_then_reconnected', marks=defect(6))])
def test_an_answer_whose_producer_is_gone_never_ends_in_silence_after_the_last_repeat(tmp_path, monkeypatch, how):
    async def body(rig):
        await stream_part_of_the_answer(rig)
        F.precondition((rig.controller.state() or {}).get('streaming'), 'a partial, still-streaming answer')
        if how == 'helper_lost_then_reconnected':
            await rig.reconnect()
            await rig.hear('Повтори')
            await rig.advance(1.5)
        t_last = await confirm_every_available_portion(rig)
        await rig.advance(RECOVERY_BOUND)
        assert_audible(rig, t_last + 0.1, 'after the user repeated the last portion they were given '
                       f'({how}): the rest of the answer never came and nothing says so')
    run_wire(tmp_path, monkeypatch, body)


def test_a_reconnect_after_an_answer_was_cut_off_does_not_replay_or_advance_by_itself(tmp_path, monkeypatch):
    async def body(rig):
        await stream_part_of_the_answer(rig)
        before = dict(rig.controller.state())
        await rig.reconnect()
        await rig.advance(30)
        after = rig.controller.state()
        assert (after['chunk_index'], after['revision']) == (before['chunk_index'], before['revision'])
        assert not rig.spoken(rig.now() - 30), 'a reconnect must stay quiet until an explicit repeat or a new question'
    run_wire(tmp_path, monkeypatch, body)


# ======================================================================================================
# 5. malformed and duplicated provider events (the wire as the reader task of serve() feeds it)
# ======================================================================================================

def unhashable(value):
    return {'turn.delta': {'type': 'turn.delta', 'turn_id': value, 'delta': 'a'},
            'user created': {'type': 'turn.created', 'turn': {'id': value, 'role': 'user', 'transcript': 'a'}},
            'user done': {'type': 'turn.done', 'turn': {'id': value, 'role': 'user', 'transcript': 'a'}},
            'delegation': {'type': 'delegation.created', 'item': {'id': value, 'user_bidi_turn_id': value, 'target': 'client'}},
            'type field': {'type': value}}


CRASHING_EVENTS = {f'{name} / {kind}': event
                   for kind, value in (('list', ['x']), ('dict', {'a': 1}))
                   for name, event in unhashable(value).items()
                   if kind == 'list' or name in ('turn.delta', 'type field')}
CRASHING_EVENTS['start_ms is a 400-digit integer'] = {
    'type': 'turn.created', 'turn': {'id': 'u', 'role': 'user', 'transcript': 'x', 'start_ms': 10**400}}
HARMLESS_EVENTS = {
    'assistant done with a list id': {'type': 'turn.done', 'turn': {'id': ['x'], 'role': 'assistant', 'transcript': 'a'}},
    'turn is a list': {'type': 'turn.done', 'turn': ['x']},
    'transcript is an int': {'type': 'turn.done', 'turn': {'id': 'q', 'role': 'user', 'transcript': 5}},
    'not an object (null)': None, 'not an object (list)': [], 'empty object': {},
    'a 100k-word transcript': {'type': 'turn.done', 'turn': {'id': 'h', 'role': 'user', 'transcript': 'я ' * 100000}},
}


async def feed_or_fail(rig, event, what):
    __tracebackhide__ = True
    try:
        await rig.wire.provider(event)
    except Exception as error:
        raise AssertionError(f'{what}: wire.provider raised {type(error).__name__}: {error}') from None


async def a_normal_question_is_still_answered_aloud(rig):
    t0 = rig.now()
    await rig.ask_direct()
    await rig.advance(FIRST_CUE_BOUND)
    assert_audible(rig, t0, 'a normal question after a malformed event', FIRST_CUE_BOUND)


@pytest.mark.parametrize('name', [pytest.param(n, marks=defect(8)) for n in CRASHING_EVENTS])
def test_a_provider_event_with_an_unhashable_id_or_type_does_not_raise(tmp_path, monkeypatch, name):
    async def body(rig):
        await feed_or_fail(rig, CRASHING_EVENTS[name], name)
        await a_normal_question_is_still_answered_aloud(rig)
    run_wire(tmp_path, monkeypatch, body)


@pytest.mark.parametrize('name', list(HARMLESS_EVENTS))
def test_other_malformed_provider_events_are_ignored_and_the_session_stays_usable(tmp_path, monkeypatch, name):
    async def body(rig):
        await feed_or_fail(rig, HARMLESS_EVENTS[name], name)
        await a_normal_question_is_still_answered_aloud(rig)
    run_wire(tmp_path, monkeypatch, body)


SCALARS = st.one_of(st.none(), st.booleans(), st.integers(min_value=-10**6, max_value=10**6),
                    st.floats(allow_nan=True, allow_infinity=True), st.text(max_size=40))
KEYS = ['type', 'turn', 'turn_id', 'delta', 'start_ms', 'end_ms', 'item', 'id', 'role', 'transcript', 'user_bidi_turn_id', 'target']
VALID_EVENTS = [
    {'type': 'turn.created', 'turn': {'id': 'u9', 'role': 'user', 'transcript': 'Что'}},
    {'type': 'turn.delta', 'turn_id': 'u9', 'delta': ' такое', 'start_ms': 40, 'end_ms': 79},
    {'type': 'turn.done', 'turn': {'id': 'u9', 'role': 'user', 'transcript': 'Что такое масса?'}},
    {'type': 'turn.created', 'turn': {'id': 'a9', 'role': 'assistant', 'transcript': 'Мера'}},
    {'type': 'turn.done', 'turn': {'id': 'a9', 'role': 'assistant', 'transcript': 'Мера инертности тела.'}},
    {'type': 'delegation.created', 'item': {'id': 'd9', 'type': 'delegation', 'target': 'client', 'user_bidi_turn_id': 'u9'}},
    {'type': 'input_audio_buffer.speech_started'},
]


def corrupt(event, path, value):
    """A deep copy of ``event`` with the field at ``path`` replaced; missing dict levels are created."""
    event = json.loads(json.dumps(event))
    node = event
    for key in path[:-1]:
        child = node.get(key)
        if not isinstance(child, dict):
            child = node[key] = {}
        node = child
    node[path[-1]] = value
    return event


@settings(max_examples=24, derandomize=True, database=None, deadline=None, report_multiple_bugs=False,
          suppress_health_check=list(HealthCheck))
@given(base=st.sampled_from(VALID_EVENTS), key=st.sampled_from(KEYS), nested=st.booleans(), value=SCALARS)
def test_scalar_garbage_in_any_field_of_a_provider_event_never_raises(base, key, nested, value):
    path = ('turn', key) if nested and 'turn' in base else ('item', key) if nested and 'item' in base else (key,)
    event = corrupt(base, path, value)

    async def body(rig):
        await feed_or_fail(rig, event, f'{event!r}'[:200])
        await a_normal_question_is_still_answered_aloud(rig)
    mp = pytest.MonkeyPatch()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            run_wire(Path(tmp), mp, body)
    finally:
        mp.undo()


def duplicate_plan():
    """Re-delivery plans. A user turn.created is only ever duplicated at once: after its own turn.done it is
    a different fault (see test_a_start_of_speech_without_a_transcript...), kept out of this property."""
    anywhere = st.sampled_from([None, 0, 1, 2, 3])
    at_once = st.sampled_from([None, 0])
    return st.tuples(at_once, anywhere, at_once, anywhere, anywhere, anywhere, anywhere, anywhere).map(list)


def collapse(texts):
    """Auto-repeats of one portion are consecutive duplicates; a double advance or a stale cue is not."""
    return [t for i, t in enumerate(texts) if i == 0 or t != texts[i - 1]]


async def play_dialogue(rig, plan):
    """Question, streamed answer, two repeats, «повтори», a new question. ``plan[i % 8]`` re-delivers event i
    after ``k`` further events (0 = right away at the same instant); None = delivered once."""
    index = 0
    pending = []                                      # (index after which it is re-delivered, event)

    async def fire(event):
        nonlocal index
        await rig.wire.provider(event)
        await rig.advance(0.05)
        delay = plan[index % len(plan)]
        if delay is not None:
            pending.append((index + delay, event))
        for item in sorted([p for p in pending if p[0] <= index], key=lambda p: p[0]):
            pending.remove(item)
            await rig.wire.provider(item[1])          # same instant: the clock is not moved by a duplicate
        index += 1

    for event in (F.created('u1', 'user', 'Что'), F.done('u1', 'user', F.DIRECT_QUESTION)):
        await fire(event)
    words = F.DIRECT_ANSWER.split(' ')
    for event in ([F.created('a1', 'assistant', words[0])] + [F.delta('a1', ' ' + w, n) for n, w in enumerate(words[1:], 1)]
                  + [F.done('a1', 'assistant', F.DIRECT_ANSWER)]):
        await fire(event)
    for n in range(2):
        await fire(F.done(f'ack{n}', 'user', rig.current_portion() or ''))
    await fire(F.done('rep', 'user', 'Повтори'))
    for event in (F.created('u2', 'user', 'Что'), F.done('u2', 'user', F.OTHER_DIRECT_QUESTION),
                  F.done('a2', 'assistant', F.OTHER_DIRECT_ANSWER)):
        await fire(event)
    await rig.advance(1)
    state = rig.controller.state()
    return collapse(rig.spoken()), (state['revision'], state['chunk_index'], state['answer'])


@functools.lru_cache(maxsize=1)
def clean_dialogue():
    return play_once([None] * 8)


def play_once(plan):
    async def body(rig):
        return await play_dialogue(rig, plan)
    mp = pytest.MonkeyPatch()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            return run_wire(Path(tmp), mp, body)
    finally:
        mp.undo()


@settings(max_examples=10, derandomize=True, database=None, deadline=None, report_multiple_bugs=False,
          suppress_health_check=list(HealthCheck))
@given(plan=duplicate_plan())
def test_duplicated_and_late_redelivered_provider_events_change_nothing(plan):
    clean = clean_dialogue()
    assert clean[0], 'precondition: the clean dialogue is audible'
    noisy = play_once(plan)
    assert noisy == clean, f'duplicates {plan} changed what is spoken or the stored position'


# ======================================================================================================
# 6. a start of speech that never becomes a transcript must not freeze the repeat loop
# ======================================================================================================

SPEECH_STARTS = {
    'provider_speech_started': lambda rig: rig.feed({'type': 'input_audio_buffer.speech_started'}),
    'phone_input_audio_buffer_clear': lambda rig: rig.wire.client({'type': 'input_audio_buffer.clear'}),
    'phone_response_cancel': lambda rig: rig.wire.client({'type': 'response.cancel'}),
}


@pytest.mark.parametrize('how', list(SPEECH_STARTS))
def test_a_start_of_speech_without_a_transcript_does_not_freeze_the_repeat_loop(tmp_path, monkeypatch, how):
    """A cough, a noise gate or an accidental barge-in: ASR produces no turn. The user is still waiting."""
    async def body(rig):
        await rig.ask_direct()
        await rig.advance(1)
        F.precondition(rig.completed(), 'the first cue was spoken and now waits for the user')
        t_noise = rig.now()
        await SPEECH_STARTS[how](rig)
        await rig.advance(RECOVERY_BOUND)
        assert_audible(rig, t_noise + 0.1, f'{how}: the unconfirmed portion is never repeated again '
                       f'(controller.hearing={rig.controller.hearing})')
    run_wire(tmp_path, monkeypatch, body)


def test_a_late_duplicate_of_the_users_turn_created_does_not_hold_back_the_first_cue(tmp_path, monkeypatch):
    async def body(rig):
        t0 = rig.now()
        await rig.feed(F.created('u1', 'user', 'Что'))
        await rig.feed(F.done('u1', 'user', F.DIRECT_QUESTION))
        await rig.feed(F.created('u1', 'user', 'Что'))           # the same turn.created again, after its turn.done
        await rig.answer(F.DIRECT_ANSWER)
        await rig.advance(RECOVERY_BOUND)
        assert_audible(rig, t0, 'duplicate turn.created: the first cue stays pending '
                       f'(pending={rig.wire.pending_cue is not None}, hearing={rig.controller.hearing})')
    run_wire(tmp_path, monkeypatch, body)


def test_an_empty_transcript_after_a_start_of_speech_releases_the_repeat_loop(tmp_path, monkeypatch):
    async def body(rig):
        await rig.ask_direct()
        await rig.advance(1)
        t_noise = rig.now()
        await rig.feed(F.created('n1', 'user', ''))
        await rig.feed(F.done('n1', 'user', ''))                  # ASR heard nothing
        await rig.advance(RECOVERY_BOUND)
        assert_audible(rig, t_noise + 0.1, 'repeat loop after an empty transcript')
    run_wire(tmp_path, monkeypatch, body)


# ======================================================================================================
# 7. exceptions inside first_useful / portioner / textutil (the segmentation chain of ControlledMedia._source)
# ======================================================================================================

def patch_at(monkeypatch, module, attr, value):
    """``setattr`` on the module; on ``controlled_media`` on every controller module that binds the name (the code that calls it lives in the cm_* mixins)."""
    if module is controlled_media:
        patch_controller(monkeypatch, attr, value)
    else:
        monkeypatch.setattr(module, attr, value)


def raising(*args, **kwargs):
    raise F.InjectedSegmentationFault('bug in a segmentation helper')


def raising_once(original):
    state = {'raised': False}

    def wrapper(*args, **kwargs):
        if not state['raised']:
            state['raised'] = True
            raise F.InjectedSegmentationFault('transient bug in a segmentation helper')
        return original(*args, **kwargs)
    return wrapper


GATE_HELPERS = {                      # name -> (module, attribute): every call on the way from provider text to a cue
    'first_useful.first_cue': (controlled_media, 'first_cue'),
    'first_useful.compact_opening': (controlled_media, 'compact_opening'),
    'portioner.expand_abbreviations': (controlled_media, 'expand_abbreviations'),
    'textutil.strip_process_prefix': (controlled_media, 'strip_process_prefix'),
    'textutil.definition_body': (controlled_media, 'definition_body'),
}


@pytest.mark.parametrize('name', [pytest.param(n, marks=defect(4)) for n in GATE_HELPERS]
                         + [pytest.param('portioner.portions (inside EchoEngine.reply)')])
def test_an_exception_in_a_segmentation_helper_does_not_escape_the_wire(tmp_path, monkeypatch, name):
    module, attr = GATE_HELPERS.get(name, (engine_module, 'portions'))

    async def body(rig):
        await rig.ask(F.DIRECT_QUESTION)
        patch_at(monkeypatch, module, attr, raising)
        await feed_or_fail(rig, F.done('a1', 'assistant', F.DIRECT_ANSWER), f'{name} raising')
    run_wire(tmp_path, monkeypatch, body)


@defect(4)
def test_an_exception_in_stable_prefix_does_not_escape_the_wire_while_the_answer_streams(tmp_path, monkeypatch):
    reached = []

    def raising_stable_prefix(*args, **kwargs):
        reached.append(1)
        raise F.InjectedSegmentationFault('bug in stable_prefix')

    async def body(rig):
        await rig.ask(F.DIRECT_QUESTION)
        patch_controller(monkeypatch, 'stable_prefix', raising_stable_prefix)
        words = STREAM.split(' ')
        await feed_or_fail(rig, F.created('a1', 'assistant', words[0]), 'stable_prefix raising')
        for n, word in enumerate(words[1:], 1):
            try:
                await rig.wire.provider(F.delta('a1', ' ' + word, n))
            except Exception as error:
                raise AssertionError(f'stable_prefix raising (delta {n}): wire.provider raised '
                                     f'{type(error).__name__}: {error}') from None
        F.precondition(reached, 'the incremental stable_prefix path was never reached by this answer')
    run_wire(tmp_path, monkeypatch, body)


@pytest.mark.parametrize('name', list(GATE_HELPERS) + ['portioner.portions (inside EchoEngine.reply)'])
def test_an_exception_in_a_segmentation_helper_still_ends_in_an_audible_outcome(tmp_path, monkeypatch, name):
    """Whatever the helper's bug, a fallback (plain portions) or a spoken diagnostic must reach the user."""
    module, attr = GATE_HELPERS.get(name, (engine_module, 'portions'))

    async def body(rig):
        t0 = rig.now()
        await rig.ask(F.DIRECT_QUESTION)
        patch_at(monkeypatch, module, attr, raising)
        try:
            await rig.wire.provider(F.done('a1', 'assistant', F.DIRECT_ANSWER))
        except Exception:
            pass                                                  # (escaping is the previous test's subject)
        await rig.advance(RECOVERY_BOUND)
        assert_audible(rig, t0, f'{name} raised on the only answer the cloud will send')
    run_wire(tmp_path, monkeypatch, body)


@pytest.mark.parametrize('name', ['first_useful.first_cue', 'portioner.portions (inside EchoEngine.reply)'])
def test_the_session_is_usable_after_a_transient_segmentation_fault(tmp_path, monkeypatch, name):
    module, attr = GATE_HELPERS.get(name, (engine_module, 'portions'))

    async def body(rig):
        await rig.ask(F.DIRECT_QUESTION)
        patch_at(monkeypatch, module, attr, raising_once(getattr(module, attr)))
        try:
            await rig.wire.provider(F.done('a1', 'assistant', F.DIRECT_ANSWER))
        except Exception:
            pass
        await rig.advance(1)
        t1 = rig.now()
        await rig.ask_direct(F.OTHER_DIRECT_QUESTION, F.OTHER_DIRECT_ANSWER)
        await rig.advance(FIRST_CUE_BOUND)
        assert_audible(rig, t1, 'next question after a transient segmentation fault', FIRST_CUE_BOUND)
    run_wire(tmp_path, monkeypatch, body)


QUESTION_PATH_FAULTS = {                  # failures on the way from a heard question to its state
    'classifier.analyze': (cm_probes, 'analyze', raising),
    'sqlite: database is locked in EchoEngine.state': (engine_module.EchoEngine, 'state', None),
}


def locked_database(*args, **kwargs):
    raise sqlite3.OperationalError('database is locked')


@pytest.mark.parametrize('name', [pytest.param(n, marks=defect(4)) for n in QUESTION_PATH_FAULTS])
def test_an_exception_while_a_question_is_being_accepted_does_not_escape_the_wire(tmp_path, monkeypatch, name):
    module, attr, replacement = QUESTION_PATH_FAULTS[name]

    async def body(rig):
        patch_at(monkeypatch, module, attr, replacement or locked_database)
        await feed_or_fail(rig, F.done('u1', 'user', F.DIRECT_QUESTION), f'{name} failing')
    run_wire(tmp_path, monkeypatch, body)


@defect(4)
def test_a_question_lost_to_an_internal_exception_is_answered_by_a_spoken_diagnostic(tmp_path, monkeypatch):
    """The question was heard but the classifier crashed on it: the user must be told, not left waiting."""
    async def body(rig):
        t0 = rig.now()
        patch_controller(monkeypatch, 'analyze', raising)
        try:
            await rig.wire.provider(F.done('u1', 'user', F.DIRECT_QUESTION))
        except Exception:
            pass
        await rig.advance(RECOVERY_BOUND)
        assert_audible(rig, t0, 'the classifier raised on the question')
    run_wire(tmp_path, monkeypatch, body)


def test_a_portioner_failure_inside_the_engine_is_logged_with_its_reason(tmp_path, monkeypatch):
    async def body(rig):
        await rig.ask(F.DIRECT_QUESTION)
        monkeypatch.setattr(engine_module, 'portions', raising)
        await rig.wire.provider(F.done('a1', 'assistant', F.DIRECT_ANSWER))
        await rig.advance(1)
    with F.capture_logs() as logs:
        run_wire(tmp_path, monkeypatch, body)
    F.precondition(logs.text(), 'the swallowed failure leaves a record')
    assert logged(logs, 'InjectedSegmentationFault') or logged(logs, 'portion'), \
        f'the record names no cause: {logs.text()!r}'


# ======================================================================================================
# 8. controlled_host.serve end to end: helper loss, malformed frames, a stalled helper, setup, cleanup
# ======================================================================================================

def serve_tasks():
    return sorted(t.get_coro().__qualname__ for t in asyncio.all_tasks()
                  if not t.done() and t is not asyncio.current_task() and t.get_coro().__qualname__.startswith('serve.'))


LOSSES = {
    'X frame': lambda bridge: bridge.push('X', b''),
    'EOF': lambda bridge: bridge.inbox.put_nowait(None),
    'corrupt pipe': lambda bridge: bridge.inbox.put_nowait(ValueError('truncated helper payload')),
}


@pytest.mark.parametrize('how', list(LOSSES))
def test_losing_the_helper_mid_answer_ends_the_call_cleanly_quickly_and_with_a_logged_reason(tmp_path, monkeypatch, how):
    async def body(host):
        await host.ask(F.DIRECT_QUESTION)
        host.cloud(F.created('a1', 'assistant', 'Инерция — это'))
        await host.advance(0.3)
        t_loss = host.now()
        LOSSES[how](host.bridge)
        assert await host.until(lambda: host.finished, 5), 'serve did not return within 5 s of the helper loss'
        assert host.now() - t_loss <= 5
        assert isinstance(host.outcome, F.WSClosed), f'unexpected exception out of serve: {host.outcome!r}'
        assert host.ws.close_code == 1011
        assert 'controlled_upstream_closed' in host.errors(t_loss), 'the loss was not reported before the close'
        assert host.bridge.closed and host.worker.releases == 1
        assert not serve_tasks(), f'serve left tasks running: {serve_tasks()}'
        closing = [text for level, text in host.logger.lines if text.startswith('Controlled call closed')]
        assert closing and 'controlled_upstream_closed' in closing[-1], host.logger.lines
    run_host(tmp_path, monkeypatch, body)


MALFORMED_FRAMES = [b'{not json', b'null', b'[]', b'"x"', b'5']


@pytest.mark.parametrize('payload', [pytest.param(p, marks=defect(7), id=p.decode()) for p in MALFORMED_FRAMES])
def test_one_unparsable_or_non_object_helper_event_does_not_end_the_call(tmp_path, monkeypatch, payload):
    async def body(host):
        host.bridge.push('e', payload)
        await host.advance(1)
        assert not host.finished, f'the call ended: {host.outcome!r}, ws close {host.ws.close_code}, errors {host.errors()}'
        t0 = host.now()
        await host.ask(F.DIRECT_QUESTION)
        await host.answer(F.DIRECT_ANSWER)
        await host.advance(2)
        assert host.audio(t0), 'the next question was not answered aloud'
    run_host(tmp_path, monkeypatch, body)


def test_a_helper_that_stops_reading_does_not_hang_the_call(tmp_path, monkeypatch):
    async def body(host):
        async def stuck(kind, payload=b''):
            if kind == 'P':
                await asyncio.Event().wait()                      # stdin.drain() on a full pipe to a frozen child
            host.bridge.sent.append((kind, payload))
        host.bridge.send = stuck
        host.phone_audio(3)
        await host.advance(1)
        t0 = host.now()
        host.ws.push({'type': 'response.cancel'})                 # the phone's stop / barge-in
        handled = await host.until(lambda: host.finished or any(
            f.type == 'output_audio_buffer.clear' and f.t >= t0 for f in host.ws.frames), 60)
        assert handled, 'neither the phone cancel was processed nor the call ended within 60 s: serve is blocked on the helper pipe'
    run_host(tmp_path, monkeypatch, body)


@pytest.mark.parametrize('script', [['no_offer'], ['closed_before_ready'], ['refused'], ['never_ready']], ids=lambda s: s[0])
def test_a_failed_subscription_setup_is_bounded_reported_logged_and_retryable(tmp_path, monkeypatch, script):
    async def body(host):
        t0 = host.now()
        host.ws.push({'type': 'session.update', 'session': {}})
        assert await host.until(lambda: 'controlled_upstream_unavailable' in host.errors(), 45), host.ws.frames
        assert host.now() - t0 <= 45
        assert not any(f.type == 'session.updated' for f in host.ws.frames), 'ready must not be claimed'
        warning = host.logger.text(logging.WARNING)
        assert 'Controlled media setup failed' in warning and 'phase=' in warning and 'type=' in warning, warning
        assert host.bridges and all(b.closed for b in host.bridges), 'a helper process was leaked'
        assert not host.finished
        host.setup_script.clear()
        host.ws.push({'type': 'session.update', 'session': {}})
        assert await host.until(lambda: any(f.type == 'session.updated' for f in host.ws.frames), 5), 'no retry possible'
    run_host(tmp_path, monkeypatch, body, handshake=False, setup=script)


CLIENT_JUNK = {
    'not json': 'not json', 'json null': 'null', 'json list': '[]', 'json string': '"x"', 'json number': '5',
    'json true': 'true', 'empty object': '{}',
    'audio is a number': '{"type":"input_audio_buffer.append","audio":5}',
    'audio is not base64': '{"type":"input_audio_buffer.append","audio":"!!!!"}',
    'response is a number': '{"type":"response.create","response":5}',
    'response input holds a number': '{"type":"response.create","response":{"input":[5]}}',
    'turn_id is a list': '{"type":"conduit.turn.done","turn_id":["x"]}',
    'type is a list': '{"type": ["session.update"]}',
    'type is an object': '{"type": {"a": 1}}',
}
CRASHING_JUNK = {'type is a list', 'type is an object'}


@pytest.mark.parametrize('name', [pytest.param(n, marks=defect(8)) if n in CRASHING_JUNK else n for n in CLIENT_JUNK])
def test_a_junk_frame_from_the_phone_is_rejected_and_the_call_goes_on(tmp_path, monkeypatch, name):
    async def body(host):
        host.ws.push(CLIENT_JUNK[name])
        await host.advance(0.5)
        assert not host.finished, f'the call ended: {host.outcome!r}'
        before = len([1 for kind, _ in host.bridge.sent if kind == 'P'])
        host.phone_audio(2)
        await host.advance(0.5)
        assert len([1 for kind, _ in host.bridge.sent if kind == 'P']) == before + 2, 'audio no longer reaches the helper'
    run_host(tmp_path, monkeypatch, body)


def test_a_transient_exception_in_a_tick_does_not_stop_the_auto_repeat_for_the_rest_of_the_call(tmp_path, monkeypatch):
    async def body(host):
        await host.ask(F.DIRECT_QUESTION)
        await host.answer(F.DIRECT_ANSWER)
        await host.advance(1)
        F.precondition(len(host.spoken()) == 1, 'the first cue was spoken once')
        real, failures = engine_module.EchoEngine.state, {'left': 1}

        def flaky(self, session_id):
            if failures['left']:
                failures['left'] -= 1
                raise sqlite3.OperationalError('disk I/O error')
            return real(self, session_id)
        monkeypatch.setattr(engine_module.EchoEngine, 'state', flaky)
        t0 = host.now()
        await host.advance(RECOVERY_BOUND)
        F.precondition(failures['left'] == 0, 'the injected fault was hit')
        assert len(host.spoken(t0)) >= 1, f'no repeat for {RECOVERY_BOUND:.0f} s after one transient error; tasks: {serve_tasks()}'
    run_host(tmp_path, monkeypatch, body)


def test_a_failing_helper_close_cannot_skip_the_rest_of_the_cleanup(tmp_path, monkeypatch):
    async def body(host):
        host.bridge.close_fault = RuntimeError('helper will not die')
        host.bridge.push('X', b'')
        assert await host.until(lambda: host.finished, 10)
        await host.advance(2)
        assert host.worker.releases == 1, 'the SAPI worker lease was never released'
        assert isinstance(host.outcome, F.WSClosed), f'the real cause (the closed websocket) is masked by {host.outcome!r}'
        assert not serve_tasks(), serve_tasks()
    run_host(tmp_path, monkeypatch, body)


@pytest.mark.parametrize('mode', ['rate', 'empty', 'garbage', 'raise'])
def test_host_a_cue_whose_wav_is_unusable_still_ends_in_an_audible_outcome(tmp_path, monkeypatch, mode):
    """Through the real ``synthesize`` closure of serve(): 22 kHz WAV / 0 frames / not a WAV / worker error."""
    async def body(host):
        t0 = host.now()
        await host.ask(F.DIRECT_QUESTION)
        await host.answer(F.DIRECT_ANSWER)
        await host.advance(RECOVERY_BOUND)
        assert host.audio(t0), f'WAV fault {mode!r}: silence; error frames {host.errors(t0)}'
    run_host(tmp_path, monkeypatch, body, synth=[mode, 'ok'])


@pytest.mark.parametrize('mode', ['raise', 'failed', 'no_data'])
def test_host_a_failing_quick_lookup_still_ends_in_an_audible_outcome(tmp_path, monkeypatch, mode):
    """Through the real ``lookup`` closure of serve(): the Hermes quick-lookup raises / reports failure / returns nothing."""
    async def body(host):
        t0 = host.now()
        await host.ask(F.LOOKUP_QUESTION)
        await host.advance(RECOVERY_BOUND)
        assert host.audio(t0), f'lookup fault {mode!r}: silence; error frames {host.errors(t0)}; context sent: {[k for k, _ in host.bridge.sent if k == "E"]}'
    run_host(tmp_path, monkeypatch, body, lookup=[mode])


def test_host_a_failed_cue_is_logged_by_the_host_with_its_reason(tmp_path, monkeypatch):
    async def body(host):
        await host.ask(F.DIRECT_QUESTION)
        await host.answer(F.DIRECT_ANSWER)
        await host.advance(2)
        F.precondition(host.errors(), 'the synthesis failed')
        text = host.logger.text(logging.WARNING)
        assert 'synth' in text.lower() and ('InjectedSapiFault' in text or 'controlled_synthesis_failed' in text), \
            f'nothing in the host log (WARNING+) names the failed cue and its cause: {text!r}'
    run_host(tmp_path, monkeypatch, body, synth=['raise'])


# ======================================================================================================
# 9. the classic path (EchoEngine + PrivateCodexGenerator) and the Hermes TTS provider
# ======================================================================================================

def failing_generator(question, history, context, request, model):
    raise F.InjectedFault('cloud 503')


def classic_reply(engine, text, turn_id):
    return engine_reply(engine, session_id='s', turn_id=turn_id, text=text, request={}, model='offline')


@defect(13)
def test_classic_a_failed_generation_of_a_plain_question_is_not_silent(tmp_path):
    engine = engine_module.EchoEngine(tmp_path / 'classic.sqlite3', failing_generator)
    reply = classic_reply(engine, 'Что такое инерция?', 'q1')
    assert reply != engine_module.SILENT, \
        'the hidden NO_REPLY marker was returned: the user hears nothing and nothing says why'


def test_classic_a_failed_generation_is_logged_with_its_reason(tmp_path):
    engine = engine_module.EchoEngine(tmp_path / 'classic.sqlite3', failing_generator)
    with F.capture_logs() as logs:
        classic_reply(engine, 'Что такое инерция?', 'q1')
    F.precondition(logs.text(), 'the failure leaves a record')
    assert logged(logs, 'InjectedFault'), f'the record names no cause: {logs.text()!r}'


def test_classic_the_engine_is_usable_after_a_failed_generation_and_repeat_needs_no_model(tmp_path):
    calls = []

    def generate(question, history, context, request, model):
        calls.append(question)
        if len(calls) == 1:
            raise F.InjectedFault('cloud 503')
        return 'Инерция — это свойство тела сохранять покой.'
    engine = engine_module.EchoEngine(tmp_path / 'classic.sqlite3', generate)
    classic_reply(engine, 'Что такое инерция?', 'q1')
    spoken = classic_reply(engine, 'Что такое инерция?', 'q2')
    assert spoken != engine_module.SILENT and len(calls) == 2
    assert classic_reply(engine, 'Повтори', 'r1') == spoken and len(calls) == 2


def test_classic_a_failed_verification_is_spoken_as_a_diagnostic(tmp_path):
    from echo_sync.generator import PrivateCodexGenerator, VERIFICATION_UNAVAILABLE

    def broken_client(**kwargs):
        raise F.InjectedFault('client construction failed')
    generator = PrivateCodexGenerator(resolve=lambda: {'api_key': 'a.b.c', 'base_url': 'https://chatgpt.com/backend-api/codex'},
                                      headers=lambda *a, **k: {}, client_factory=broken_client)
    engine = engine_module.EchoEngine(tmp_path / 'classic.sqlite3', generator)
    reply = classic_reply(engine, 'Какая сейчас ключевая ставка?', 'q1')
    assert reply != engine_module.SILENT and VERIFICATION_UNAVAILABLE.startswith(reply.split(' … ')[0].rstrip('.,'))


class WorkerManager:
    """The profile-owned reusable SAPI worker as EchoSapiProvider sees it."""

    def __init__(self, error=None):
        self.error, self.calls = error, []

    def synthesize(self, text, path):
        self.calls.append((text, path))
        if self.error:
            raise self.error
        return path


@pytest.fixture
def sapi(monkeypatch):
    module = pytest.importorskip('echo_sync.sapi_provider')          # needs Hermes' agent.tts_provider
    monkeypatch.setattr(module.EchoSapiProvider, '_is_windows', staticmethod(lambda: True))
    return module


def test_sapi_provider_a_worker_failure_reaches_the_caller_after_one_attempt(sapi, monkeypatch, tmp_path):
    manager = WorkerManager(error=F.InjectedSapiFault('worker_timeout'))
    with pytest.raises(F.InjectedSapiFault):
        sapi.EchoSapiProvider(manager).synthesize('Это фраза.', str(tmp_path / 'cue.wav'))
    assert len(manager.calls) == 1, 'one worker attempt, no second road, no retry storm'


def test_sapi_provider_a_worker_failure_is_logged_with_its_reason(sapi, monkeypatch, tmp_path):
    manager = WorkerManager(error=F.InjectedSapiFault('worker_timeout'))
    with F.capture_logs() as logs:
        with pytest.raises(F.InjectedSapiFault):
            sapi.EchoSapiProvider(manager).synthesize('Это фраза.', str(tmp_path / 'cue.wav'))
    F.precondition(logs.text(), 'the failure leaves a record')
    assert logged(logs, 'worker_timeout') or logged(logs, 'InjectedSapiFault'), f'the record names no cause: {logs.text()!r}'


# ======================================================================================================
# 10. random fault schedules over a whole dialogue: the invariants that must hold WHATEVER fails
# ======================================================================================================

PAIRS = {'direct0': (F.DIRECT_QUESTION, F.DIRECT_ANSWER), 'direct1': (F.OTHER_DIRECT_QUESTION, F.OTHER_DIRECT_ANSWER),
         'lookup': (F.LOOKUP_QUESTION, F.LOOKUP_ANSWER)}

SCHEDULE_STEPS = st.one_of(
    st.tuples(st.just('ask'), st.sampled_from(sorted(PAIRS))),
    st.tuples(st.just('confirm'), st.none()),               # the user repeats the portion they wait for
    st.tuples(st.just('repeat_request'), st.none()),        # «повтори»
    st.tuples(st.just('stop'), st.none()),
    st.tuples(st.just('wait'), st.integers(1, 12)),
    st.tuples(st.just('synth'), st.sampled_from(['ok', 'raise', 'empty', 'hang', 'odd', ('slow', 5)])),
    st.tuples(st.just('lookup'), st.sampled_from(['ok', 'raise', 'hang', 'empty', ('slow', 6)])))


async def run_schedule(rig, schedule):
    """Execute the steps; returns [(time, answer text allowed to be spoken from then on)]."""
    allowed = []
    for kind, argument in schedule:
        try:
            if kind == 'ask':
                question, answer = PAIRS[argument]
                allowed.append((rig.now(), answer))
                await rig.ask(question)
                await rig.advance(0.3)
                await rig.answer(answer)
            elif kind == 'confirm':
                if rig.current_portion() is not None:
                    await rig.repeat_current()
            elif kind == 'repeat_request':
                await rig.hear('Повтори')
            elif kind == 'stop':
                allowed.append((rig.now(), ''))
                await rig.hear('Стоп')
            elif kind == 'wait':
                await rig.advance(argument)
            elif kind == 'synth':
                rig.synth_plan.steps = [argument]
            elif kind == 'lookup':
                rig.lookup_plan.steps = [argument]
        except Exception as error:
            raise AssertionError(f'step {kind}:{argument} raised {type(error).__name__}: {error}') from None
        await rig.advance(0.2)
    return allowed


def cue_belongs_to_the_live_question(rig, allowed):
    """Every spoken text is a portion of the live answer or novel text (a diagnostic); never a portion of an
    answer that was superseded (or stopped) when it started to play."""
    every_answer = [answer.lower() for _, answer in PAIRS.values()]
    for frame in rig.of_type('response.audio_transcript.delta'):
        live = [answer for t, answer in allowed if t < frame.t]
        text = frame.data['delta'].lower()
        in_live = bool(live) and text in live[-1].lower()
        if not in_live and any(text in answer for answer in every_answer):
            return f'{text!r} at +{frame.t - rig.t0:.1f}s belongs to an answer that was no longer the live one'
    return None


@settings(max_examples=12, derandomize=True, database=None, deadline=None, report_multiple_bugs=False,
          suppress_health_check=list(HealthCheck))
@given(schedule=st.lists(SCHEDULE_STEPS, min_size=2, max_size=8))
# the sequences that matter most are pinned, the rest is explored:
@example(schedule=[('synth', ('slow', 5)), ('ask', 'direct0'), ('ask', 'direct1'), ('wait', 8)])      # stale audio of a superseded cue
@example(schedule=[('lookup', ('slow', 6)), ('ask', 'lookup'), ('ask', 'direct1'), ('wait', 8)])      # stale lookup result
@example(schedule=[('synth', ('slow', 5)), ('ask', 'direct0'), ('stop', None), ('wait', 8)])          # «стоп» while a cue is being rendered
@example(schedule=[('synth', 'hang'), ('ask', 'direct0'), ('wait', 20), ('synth', 'ok'), ('repeat_request', None), ('wait', 5)])
def test_random_fault_schedules_never_corrupt_the_session_and_the_next_question_is_answered(schedule):
    """Faults in SAPI and lookup are switched on and off between steps. Independently of what is heard
    (DEF-FAULT-01/02/03 are about that), the engine must stay consistent and usable."""
    async def body(rig):
        allowed = await run_schedule(rig, schedule)
        revisions = []
        state = rig.controller.state() or {}
        if state:
            assert 0 <= state['chunk_index'] <= len(state['chunks']), state
            revisions.append(state['revision'])
        problem = cue_belongs_to_the_live_question(rig, allowed)
        assert problem is None, f'a stale portion was spoken: {problem}'
        rig.synth_plan.steps, rig.lookup_plan.steps = ['ok'], ['ok']        # the world heals
        t0 = rig.now()
        await rig.ask_direct(F.OTHER_DIRECT_QUESTION, F.OTHER_DIRECT_ANSWER)
        await rig.advance(FIRST_CUE_BOUND + 1)
        assert_audible(rig, t0, 'the next question after the schedule', FIRST_CUE_BOUND + 1)
        assert (rig.controller.state() or {})['revision'] >= max(revisions or [0]), 'the revision went backwards'
    mp = pytest.MonkeyPatch()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            run_wire(Path(tmp), mp, body)
    finally:
        mp.undo()


# ======================================================================================================
# 11. socket faults, a failing prefetch, «стоп» during recovery, the SAPI keep-warm lease
# ======================================================================================================

def test_a_phone_that_disconnects_in_the_middle_of_a_cue_ends_the_call_cleanly(tmp_path, monkeypatch):
    """The websocket dies while audio is being written: every send now fails, the receive side is gone too."""
    async def body(host):
        await host.ask(F.DIRECT_QUESTION)
        await host.answer(F.DIRECT_ANSWER)
        await host.advance(0.45)                                  # the 1 s cue is half way
        F.precondition(host.audio(), 'the cue must be playing')
        t_drop = host.now()
        host.ws.send_fault = lambda frame: F.WSClosed('peer gone')
        host.ws.inbox.put_nowait(F.WSClosed('peer gone'))
        assert await host.until(lambda: host.finished, 5), 'serve did not return after the phone vanished'
        assert host.now() - t_drop <= 5
        assert isinstance(host.outcome, F.WSClosed), f'unexpected exception out of serve: {host.outcome!r}'
        assert host.bridge.closed and host.worker.releases == 1
        assert not serve_tasks(), serve_tasks()
        assert any('Controlled call closed' in text for _, text in host.logger.lines), 'the call end was not logged'
    run_host(tmp_path, monkeypatch, body, synth=[('long', 1.0)])


def test_the_session_is_usable_after_a_failed_socket_write(tmp_path, monkeypatch):
    sent = {'n': 0}

    def fault(frame):
        if frame.get('type') == 'response.audio.delta':
            sent['n'] += 1
            if sent['n'] == 2:
                return ConnectionResetError('socket write failed')

    async def body(rig):
        await rig.ask_direct()
        await rig.advance(1)
        t1 = rig.now()
        await rig.ask_direct(F.OTHER_DIRECT_QUESTION, F.OTHER_DIRECT_ANSWER)
        await rig.advance(FIRST_CUE_BOUND)
        assert_audible(rig, t1, 'next question after a failed socket write', FIRST_CUE_BOUND)
        assert not rig.wire.closed
    run_wire(tmp_path, monkeypatch, body, emit_fault=fault)


def test_a_failed_speculative_lookup_does_not_prevent_the_real_one(tmp_path, monkeypatch):
    """Early lookup (prefetch) starts while the question is still being heard; its failure must cost nothing."""
    async def body(rig):
        await rig.feed(F.created('u1', 'user', 'Что устанавливает статья 218 ГК РФ'))
        await rig.advance(1.0)
        F.precondition(len(rig.lookup_plan.calls) == 1, 'the speculative lookup must have started on the partial question')
        t0 = rig.now()
        await rig.feed(F.done('u1', 'user', F.LOOKUP_QUESTION))
        await rig.advance(0.3)
        await rig.answer(F.LOOKUP_ANSWER)
        await rig.advance(FIRST_CUE_BOUND)
        assert_audible(rig, t0, 'real lookup after a failed speculative one', FIRST_CUE_BOUND + 1)
        assert {kind for kind, _ in rig.source.frames} == {'E'} and len(rig.lookup_plan.calls) == 2
    run_wire(tmp_path, monkeypatch, body, lookup=['raise', 'ok'], prefetch=True)


@pytest.mark.parametrize('situation', ['lookup_hangs', 'first_cue_fails', 'cloud_never_answers'])
def test_stop_wins_over_every_pending_recovery(tmp_path, monkeypatch, situation):
    """«стоп» always stops: nothing may be spoken or reported afterwards on behalf of the stopped question."""
    async def body(rig):
        if situation == 'lookup_hangs':
            await rig.ask(F.LOOKUP_QUESTION)
        elif situation == 'first_cue_fails':
            await rig.ask_direct()
        else:
            await rig.ask(F.DIRECT_QUESTION)
        await rig.advance(1)
        t_stop = rig.now()
        await rig.hear('Стоп')
        await rig.advance(60)
        assert not rig.audio(t_stop + 0.01), 'something was spoken after «стоп»'
        assert not rig.errors(t_stop + 0.01), f'a stopped question still reports errors: {rig.errors(t_stop + 0.01)}'
    synth = ['raise'] if situation == 'first_cue_fails' else None
    lookup = ['hang'] if situation == 'lookup_hangs' else None
    run_wire(tmp_path, monkeypatch, body, synth=synth, lookup=lookup)


def test_a_failed_warm_up_cannot_leave_the_call_without_a_resident_worker(tmp_path, monkeypatch):
    """DEF-FAULT-15 closed by design: serve() no longer renews a 45 s lease every 20 s (one failed warm-up ended it); it pins the worker once with
    keep_resident(), and the worker's own supervisor repairs and re-primes it (tests/test_sapi_resident.py). A failed warm-up must not stop that pin."""
    async def body(host):
        await host.advance(62)
        assert host.worker.pins >= 1, 'the worker was never pinned resident'
    run_host(tmp_path, monkeypatch, body, handshake=False, warm_failures=1)
