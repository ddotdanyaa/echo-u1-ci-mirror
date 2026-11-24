"""WAVE 2 / Task D, part 2 (DEF-FAULT-11), through controlled_host.serve: the pipe to the WebRTC helper stalls.

The helper stops reading its stdin (frozen, swapped out, deadlocked): ``drain()`` of the pipe never returns. Before this change
that wait sat in the loop that reads the phone, so «стоп» / ``response.cancel`` was never read, nothing timed out, nothing was
logged and the repeat loop went on (17 repeats in 55 s measured).

Required (wave2/task-d-brief.md): writes never block the event loop or the audio path (a bounded writer queue with a timeout);
on a stall the channel diagnostic («Связь прервалась. Повторите вопрос.») and a clean close, per the existing upstream rule of
Task 4: a drop in the middle of a call is spoken, the socket is closed (1011), the phone's reconnect is a new call whose open
has its own retry. The helper is a fake pipe (tests/helpers_s6_fault.FakeBridge) on the virtual clock; the real chain above it
(the writer, NativeMediaSocket, ControlledMedia, serve) is the production code.
"""
import asyncio
import base64
import logging

import pytest

import helpers_s6_fault as F
from helpers_spoken_diagnostics import CHANNEL, EVERY_PHRASE, FIRST_CUE_BOUND, responses, run_host
from echo_sync import diagnostics, helper_bridge
from echo_sync.helper_bridge import HELPER_QUEUE_MAX_BYTES, HELPER_WRITE_TIMEOUT_S

BOUND = HELPER_WRITE_TIMEOUT_S + diagnostics.DIAGNOSTIC_FLUSH_S + 2      # stall -> phrase -> closed


def serve_tasks():
    return sorted(t.get_coro().__qualname__ for t in asyncio.all_tasks()
                  if not t.done() and t is not asyncio.current_task() and t.get_coro().__qualname__.startswith('serve.'))


def writer_tasks():
    return [t.get_coro().__qualname__ for t in asyncio.all_tasks()
            if not t.done() and t is not asyncio.current_task() and 'BoundedWriter' in t.get_coro().__qualname__]


def stall(host, kinds=('P', 'E')):
    """The helper stops reading its stdin: every write of these kinds never returns (the rest is recorded as before)."""
    async def stuck(kind, payload=b''):
        if kind in kinds:
            await asyncio.Event().wait()
        host.bridge.sent.append((kind, payload))
    host.bridge.send = stuck


def packet(size=960):      # U77: loud, not zeros: the queue trim gives quiet backlog back on every call, and this is about audio that must reach a stalled pipe
    return {'type': 'input_audio_buffer.append', 'audio': base64.b64encode(b'\x40\x1f' * (size // 2)).decode()}


def closing_times(host):
    closed_at = []
    real_close = host.ws.close

    async def close(code=1000):
        closed_at.append(host.now())
        await real_close(code)
    host.ws.close = close
    return closed_at


async def a_dictation_is_under_way(host):
    await host.ask(F.DIRECT_QUESTION)
    await host.answer(F.DIRECT_ANSWER)
    await host.advance(1)


# ======================================================================================================
# the phone is still heard
# ======================================================================================================

def test_the_phone_is_still_heard_while_the_helper_pipe_is_stuck(tmp_path, monkeypatch):
    async def body(host):
        stall(host)
        host.phone_audio(3)
        await host.advance(1)
        t0 = host.now()
        host.ws.push({'type': 'response.cancel'})                  # the phone's stop / barge-in
        await host.advance(0.5)
        assert any(f.type == 'output_audio_buffer.clear' and f.t >= t0 for f in host.ws.frames), \
            'the cancel of the phone was not read: the loop is blocked on the helper pipe'
    run_host(tmp_path, monkeypatch, body)


def test_the_phone_audio_never_waits_for_the_pipe_whatever_its_volume(tmp_path, monkeypatch):
    async def body(host):
        stall(host)
        t0 = host.now()
        for _ in range(40):
            host.ws.push(packet(4800))
        host.ws.push({'type': 'response.cancel'})
        await host.advance(0.5)
        assert any(f.type == 'output_audio_buffer.clear' and f.t >= t0 for f in host.ws.frames)
        assert host.now() - t0 < 1.0
    run_host(tmp_path, monkeypatch, body)


def test_a_healthy_helper_gets_every_frame_in_order(tmp_path, monkeypatch):
    """The guard: audio and the context of a lookup reach the pipe in the order they were sent, nothing is dropped."""
    async def body(host):
        host.phone_audio(3)
        await host.advance(0.5)
        await host.ask(F.LOOKUP_QUESTION)                           # the lookup works: its context goes to the helper
        await host.advance(1)
        host.phone_audio(2)
        await host.advance(0.5)
        kinds = [kind for kind, _ in host.bridge.sent if kind in ('P', 'E')]
        middle = kinds[3:-2]
        assert kinds[:3] == ['P'] * 3 and kinds[-2:] == ['P'] * 2 and middle and set(middle) == {'E'}, kinds
        assert not host.finished and not host.errors()
    run_host(tmp_path, monkeypatch, body)


# ======================================================================================================
# the stall is reported and the call ends cleanly
# ======================================================================================================

def test_a_stalled_pipe_ends_in_the_channel_phrase_and_a_clean_close_within_the_bound(tmp_path, monkeypatch):
    async def body(host):
        closed_at = closing_times(host)
        stall(host)
        host.phone_audio(1)
        t_stall = host.now()
        assert await host.until(lambda: host.finished, BOUND), 'serve did not end after the helper pipe stalled'
        elapsed = host.now() - t_stall
        assert elapsed >= HELPER_WRITE_TIMEOUT_S, f'a write that had not had its time was called a stall ({elapsed:.1f} s)'
        assert isinstance(host.outcome, F.WSClosed), f'unexpected exception out of serve: {host.outcome!r}'
        assert host.ws.close_code == 1011
        assert host.errors(t_stall) == ['controlled_upstream_closed']
        phrase = [r for r in responses(host.ws.frames) if r['text'] == CHANNEL]
        assert len(phrase) == 1 and phrase[0]['status'] == 'completed', host.ws.frames[-6:]
        assert closed_at and phrase[0]['end'] <= closed_at[0], 'the socket was closed before the phrase reached the phone'
        assert host.bridge.closed, 'the helper was not closed'
        assert host.worker.releases == 1
        assert not serve_tasks(), serve_tasks()
        closing = [text for level, text in host.logger.lines if text.startswith('Controlled call closed')]
        assert closing and 'controlled_upstream_closed' in closing[-1], host.logger.lines
    run_host(tmp_path, monkeypatch, body)


def test_the_stall_is_logged_with_class_and_reason(tmp_path, monkeypatch):
    async def body(host):
        stall(host)
        host.phone_audio(1)
        assert await host.until(lambda: host.finished, BOUND)
    with F.capture_logs() as logs:
        run_host(tmp_path, monkeypatch, body)
    text = logs.text(logging.WARNING)
    assert 'class=channel' in text and 'code=controlled_upstream_closed' in text and 'reason=helper_write_stalled' in text, text
    assert 'diagnostic=spoken' in text


def test_a_stall_of_the_context_frames_is_a_stall_too(tmp_path, monkeypatch):
    """The context of a lookup is written by the same writer: a pipe that takes audio but not the context is caught the same way."""
    async def body(host):
        stall(host, kinds=('E',))
        t0 = host.now()
        await host.ask(F.LOOKUP_QUESTION)
        assert await host.until(lambda: host.finished, BOUND), 'the call hangs on a context that cannot be written'
        assert host.now() - t0 >= HELPER_WRITE_TIMEOUT_S
        assert host.errors(t0)[-1:] == ['controlled_upstream_closed']
        assert [r['text'] for r in responses(host.ws.frames)][-1:] == [CHANNEL]
    run_host(tmp_path, monkeypatch, body)


def test_phone_audio_that_arrives_after_the_failure_is_ignored_quietly(tmp_path, monkeypatch):
    async def body(host):
        stall(host)
        host.phone_audio(1)
        assert await host.until(lambda: host.errors(), BOUND), 'the stall was never reported'
        host.phone_audio(20)                                       # the phone does not know yet: the phrase is still playing
        assert await host.until(lambda: host.finished, BOUND)
        assert isinstance(host.outcome, F.WSClosed), f'the late audio ended the call with {host.outcome!r}'
    run_host(tmp_path, monkeypatch, body)


def test_a_phone_that_cannot_be_written_to_when_the_stall_is_noticed_still_gets_its_socket_closed(tmp_path, monkeypatch):
    """The announcement may fail (the phone is gone, every send raises): the close must still be tried, or the call stays open for ever."""
    async def body(host):
        stall(host)
        host.phone_audio(1)
        await host.advance(HELPER_WRITE_TIMEOUT_S - 1)
        host.ws.send_fault = lambda frame: F.WSClosed('peer gone')
        assert await host.until(lambda: host.finished, BOUND), 'the call was left open: the failed announcement skipped the close'
        assert host.ws.close_code == 1011
        assert isinstance(host.outcome, F.WSClosed)
        assert 'announcement failed' in host.logger.text(logging.WARNING)
    run_host(tmp_path, monkeypatch, body)


def test_the_helper_dying_while_the_stall_is_announced_does_not_announce_it_twice(tmp_path, monkeypatch):
    """Two paths reach the same loss (the writer's stall, then the reader's end of file once the helper is gone): one phrase, one close."""
    async def body(host):
        stall(host)
        host.phone_audio(1)
        assert await host.until(lambda: host.errors(), BOUND), 'the stall was never reported'
        t_report = host.now()
        host.bridge.inbox.put_nowait(None)                          # the frozen helper is killed meanwhile: the reader sees the end
        assert await host.until(lambda: host.finished, BOUND)
        assert host.errors() == ['controlled_upstream_closed'], host.errors()
        assert [r['text'] for r in responses(host.ws.frames)] == [CHANNEL]
        assert host.now() - t_report < BOUND
    run_host(tmp_path, monkeypatch, body)


def test_a_phone_that_hangs_up_while_the_phrase_plays_leaves_no_task_of_the_call_behind(tmp_path, monkeypatch):
    async def body(host):
        stall(host)
        host.phone_audio(1)
        assert await host.until(lambda: host.errors(), BOUND), 'the stall was never reported'
        await host.advance(1.0)                                     # the phrase is half way
        F.precondition(not host.finished, 'the call is still open while the phrase plays')
        host.ws.inbox.put_nowait(F.WSClosed('the listener hung up'))
        assert await host.until(lambda: host.finished, 3)
        assert not serve_tasks(), f'tasks of the call outlive it: {serve_tasks()}'
        assert host.worker.releases == 1
    run_host(tmp_path, monkeypatch, body, synth=PhrasesFromThePackage())


def test_a_phone_connection_that_hangs_during_the_announcement_leaves_no_task_of_the_call_behind(tmp_path, monkeypatch):
    """The announcement is a task of its own: if the send to the phone never returns (a dead connection that is not closed yet), the end of
    the call must still cancel it."""
    async def body(host):
        stall(host)
        host.phone_audio(1)
        await host.advance(HELPER_WRITE_TIMEOUT_S - 1)

        async def hangs(text):
            await asyncio.Event().wait()
        host.ws.send_text = hangs
        await host.advance(2)                                       # the stall is noticed; its announcement is stuck in a send
        F.precondition(any(name.endswith('helper_lost') for name in serve_tasks()), 'the announcement is stuck in a send')
        host.ws.inbox.put_nowait(F.WSClosed('the listener hung up'))
        assert await host.until(lambda: host.finished, 3)
        assert not serve_tasks(), f'tasks of the call outlive it: {serve_tasks()}'
    run_host(tmp_path, monkeypatch, body)


def test_a_normal_end_of_the_call_leaves_no_writer_task_behind(tmp_path, monkeypatch):
    async def body(host):
        host.phone_audio(3)
        await host.advance(1)
        F.precondition([t for t in writer_tasks()], 'the writer task runs during the call')
        host.ws.inbox.put_nowait(F.WSClosed('the listener hung up'))
        assert await host.until(lambda: host.finished, 5)
        assert not writer_tasks(), f'the writer of the helper pipe outlives the call: {writer_tasks()}'
        assert host.bridge.closed
    run_host(tmp_path, monkeypatch, body)


def test_a_flood_of_phone_audio_into_a_stalled_pipe_has_bounded_memory_and_is_a_stall(tmp_path, monkeypatch):
    peaks = []
    real_put = helper_bridge.BoundedWriter.put

    def watching_put(self, kind, payload=b''):
        accepted = real_put(self, kind, payload)
        peaks.append(self.queued_bytes)
        return accepted
    monkeypatch.setattr(helper_bridge.BoundedWriter, 'put', watching_put)

    async def body(host):
        stall(host)
        t0 = host.now()
        for _ in range(60):                                         # 60 * 96000 B: 5.7 MB in a second, into a pipe that takes nothing
            host.ws.push(packet(96000))
        assert await host.until(lambda: host.finished, BOUND)
        assert host.now() - t0 < HELPER_WRITE_TIMEOUT_S, 'a full queue is a stall at once: it does not wait for the timeout'
        assert host.errors(t0) == ['controlled_upstream_closed']
        assert [r['text'] for r in responses(host.ws.frames)] == [CHANNEL]
    with F.capture_logs() as logs:
        run_host(tmp_path, monkeypatch, body)
    assert peaks and max(peaks) <= HELPER_QUEUE_MAX_BYTES, f'{max(peaks)} bytes queued'
    assert 'reason=helper_queue_full' in logs.text(logging.WARNING)


def test_the_phones_reconnect_after_a_stall_is_a_working_call_on_a_fresh_helper(tmp_path, monkeypatch):
    """\"Close and reopen\" is the existing rule of Task 4: this call ends, the phone's reconnect is a NEW call (its own helper, its own
    open with the retry) over the same stored session, and it answers the next question."""
    async def main():
        F.patch_clock(monkeypatch)
        async with F.HostRig(tmp_path, monkeypatch) as first:
            await first.handshake()
            await a_dictation_is_under_way(first)
            stall(first)
            first.phone_audio(1)
            assert await first.until(lambda: first.finished, BOUND)
            stalled = list(first.bridges)
        assert stalled and all(bridge.closed for bridge in stalled), 'the stalled helper was not closed'
        async with F.HostRig(tmp_path, monkeypatch) as second:
            await second.handshake()
            assert second.bridges and second.bridges[0] is not stalled[0], 'the new call must open its own helper'
            t0 = second.now()
            await second.ask(F.OTHER_DIRECT_QUESTION)
            await second.answer(F.OTHER_DIRECT_ANSWER)
            await second.advance(FIRST_CUE_BOUND)
            assert second.audio(t0) and second.spoken(t0)[0].lower() in F.OTHER_DIRECT_ANSWER.lower(), second.ws.frames[-5:]
            assert not second.errors(t0) and not second.finished
    F.run(main)


# ======================================================================================================
# the phrase is heard whole, however the helper is lost
# ======================================================================================================

LOSSES = {
    'stall': lambda host: (stall(host), host.phone_audio(1)),
    'eof': lambda host: host.bridge.inbox.put_nowait(None),
    'x_frame': lambda host: host.bridge.push('X', b''),
}


def cue_responses(host):
    return [r for r in responses(host.ws.frames) if r['text'] != CHANNEL]


class PhrasesFromThePackage(F.Plan):
    """SAPI renders every cue (0.1 s) but fails on the diagnostic phrases at the start of the call, so the phrase is the PACKAGED
    audio: as long as it is in production (3.8 s), not the 0.1 s the fake worker would write."""

    def next(self, text):
        super().next(text)
        return 'raise' if text in EVERY_PHRASE else 'ok'


def test_control_without_a_loss_the_repeat_loop_does_speak_in_that_window(tmp_path, monkeypatch):
    """The control of the next test: the cue really is repeated 6-9 s after it was first heard, when the phrase would be playing."""
    async def body(host):
        await a_dictation_is_under_way(host)
        t_first = responses(host.ws.frames)[0]['start']
        await host.advance(12)
        starts = [r['start'] - t_first for r in cue_responses(host)]
        assert any(5.5 <= s <= 9.5 for s in starts), starts
    run_host(tmp_path, monkeypatch, body, synth=PhrasesFromThePackage())


@pytest.mark.parametrize('how', list(LOSSES))
def test_a_repeat_that_falls_due_while_the_channel_phrase_plays_does_not_cut_it(tmp_path, monkeypatch, how):
    async def body(host):
        await a_dictation_is_under_way(host)
        t_first = responses(host.ws.frames)[0]['start']
        # The cue is repeated 3.1 s, 6.2 s and 9.3 s after it was first heard. The loss is noticed about 5.6 s after the first cue (EOF / X
        # at once, a stalled pipe HELPER_WRITE_TIMEOUT_S after the first stuck write), so the phrase plays while the repeats at 6.2 and 9.3 fall due.
        await host.advance(max(0.0, 5.6 - (HELPER_WRITE_TIMEOUT_S if how == 'stall' else 0.0) - (host.now() - t_first)))
        LOSSES[how](host)
        assert await host.until(lambda: host.finished, BOUND), 'serve did not end'
        phrase = [r for r in responses(host.ws.frames) if r['text'] == CHANNEL]
        assert len(phrase) == 1 and phrase[0]['status'] == 'completed', \
            f'the channel phrase was cut off (a repeat took the audio over): {[(r["text"], r["status"]) for r in responses(host.ws.frames)]}'
        others = [r for r in cue_responses(host) if phrase[0]['start'] <= r['start'] <= phrase[0]['end']]
        assert not others, f'a cue was started while the phrase played: {others}'
        assert phrase[0]['end'] - phrase[0]['start'] > 3.0, 'precondition: the phrase is the long packaged one'
    run_host(tmp_path, monkeypatch, body, synth=PhrasesFromThePackage())


# ======================================================================================================
# the cleanup of serve: nothing can skip the rest of it (DEF-FAULT-12 is the same hole: a close that fails or hangs)
# ======================================================================================================

def test_a_helper_close_that_raises_does_not_skip_the_release_of_the_worker_or_mask_the_cause(tmp_path, monkeypatch):
    async def body(host):
        host.bridge.close_fault = RuntimeError('helper will not die')
        stall(host)
        host.phone_audio(1)
        assert await host.until(lambda: host.finished, BOUND)
        assert host.worker.releases == 1, 'the SAPI worker lease was never released'
        assert isinstance(host.outcome, F.WSClosed), f'the real cause (the closed websocket) is masked by {host.outcome!r}'
        assert not serve_tasks(), serve_tasks()
        assert 'RuntimeError' in host.logger.text(logging.WARNING), 'the failed close is not logged'
    run_host(tmp_path, monkeypatch, body)
