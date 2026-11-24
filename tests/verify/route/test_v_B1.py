"""V6 В1 (written B1): «overload: ``helper_queue_full`` declares the cloud lost and says «Облако недоступно» while the cloud is alive (10:22:04)». On the base the queue of the pipe to the helper (``helper_bridge.BoundedWriter``)
is bounded; when it overflows the helper is dead for this call (the pipe takes nothing): the phone hears the channel phrase («Связь прервалась. Повторите вопрос.», the one of Task 4), the socket is closed 1011,
the reconnect is a new call. The phrase «Облако недоступно. Отвечаю из местных баз.» (``local_opened``) is the phrase of a call opened WITHOUT the cloud and is never said here. What the owner expected («при перегрузе нет ложной фразы, канал не рвётся»)
is half true on the base: no false phrase, but the channel IS closed by design (a queue that overflowed is a pipe that stalled). Whether an overload that is NOT a stall must keep the call is a decision for the
family R (helper_bridge); this test pins what happens, through the real host, and fails if the wrong phrase comes."""
import asyncio

import logging

from test_helper_stall import HELPER_QUEUE_MAX_BYTES, HELPER_WRITE_TIMEOUT_S, packet, stall    # noqa: F401
from helpers_spoken_diagnostics import CHANNEL, responses, run_host

import helpers_s6_fault as F


def test_a_full_queue_says_the_channel_phrase_and_never_the_phrase_of_a_call_without_the_cloud(tmp_path, monkeypatch):
    local_phrase = 'Облако недоступно'

    async def body(host):
        stall(host)
        t0 = host.now()
        for _ in range(60):
            host.ws.push(packet(96000))
        assert await host.until(lambda: host.finished, HELPER_WRITE_TIMEOUT_S + 6)
        said = [r['text'] for r in responses(host.ws.frames)]
        assert said == [CHANNEL], said
        assert not any(local_phrase in text for text in said)
        assert host.errors(t0) == ['controlled_upstream_closed']
    with F.capture_logs() as logs:
        run_host(tmp_path, monkeypatch, body)
    assert 'reason=helper_queue_full' in logs.text(logging.WARNING)
