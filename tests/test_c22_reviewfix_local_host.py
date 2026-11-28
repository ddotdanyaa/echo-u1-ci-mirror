"""c22-reviewfix: review of master 4a91807 (local-lifecycle, local-accuracy) at the host: ``controlled_host.serve`` with ``local_fallback`` on.

A writer stall (helper_write_stalled; helper_write_failed and helper_queue_full take the same helper_lost) falls into local mode while the
call's reader still waits on the old pipe. The reader is stopped BEFORE the old channel is closed (the rule of the host's own teardown:
«Stop the sole pipe reader before communicate()»), so the real pipe's close is not met by it and the old channel delivers nothing more:
no final of the old helper after the fall, and no complaint of it that could close the new channel after the cloud comes back."""
import asyncio

import helpers_s6_fault as F
from helpers_spoken_diagnostics import run_host
from echo_sync import controlled_host
from echo_sync.helper_bridge import HELPER_WRITE_TIMEOUT_S
from test_helper_stall import serve_tasks, stall


def local_on(monkeypatch):
    real = controlled_host.read_profile_settings

    async def read(home):
        settings = dict(await real(home))
        settings['local_fallback'] = 'on'
        return settings
    monkeypatch.setattr(controlled_host, 'read_profile_settings', read)


def watch_pipe(bridge):
    """Like the real pipe: a close while a reader waits in ``receive`` is recorded (the real one raises RuntimeError there)."""
    state = {'waiting': 0, 'met': [], 'delivered_after_close': []}
    receive, close = bridge.receive, bridge.close

    async def watched_receive(timeout=30):
        state['waiting'] += 1
        try:
            item = await receive(timeout)
        finally:
            state['waiting'] -= 1
        if bridge.closed:
            state['delivered_after_close'].append(item)
        return item

    async def watched_close():
        state['met'].append(state['waiting'])
        await close()
    bridge.receive, bridge.close = watched_receive, watched_close
    return state


def test_a_writer_stall_stops_the_reader_before_the_old_channel_is_closed(tmp_path, monkeypatch):
    local_on(monkeypatch)

    async def body(host):
        old = host.bridge
        pipe = watch_pipe(old)
        old.push_event({'type': 'rate_limits.updated'})            # the reader comes back into the watched receive
        await host.advance(0.5)
        assert pipe['waiting'] == 1, 'precondition: the reader waits on the pipe'
        stall(host)
        host.phone_audio(1)
        assert await host.until(lambda: old.closed, HELPER_WRITE_TIMEOUT_S + 5), 'the stalled channel was never closed'
        await host.advance(1)
        assert not host.finished, 'local mode closes no call'
        assert pipe['met'] == [0], f'the old channel was closed with its reader waiting on it: {pipe["met"]}'
        assert not any('read_source' in name for name in serve_tasks()), serve_tasks()
        # the old helper's final that was already in its pipe reaches no one
        old.push_event(F.done('late', 'user', 'Какая ставка НДС'))
        await host.advance(1)
        assert not pipe['delivered_after_close'], pipe['delivered_after_close']
    run_host(tmp_path, monkeypatch, body)
