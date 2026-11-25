"""U77: jitter and overload of the ear's queue. With NO switch (mic_path is gone): the helper's microphone queue is modelled and bounded on every call;
a quiet backlog is given back, speech is never dropped; and every loss of freshness leaves a journal line WITH A REASON (why_journal, kind=drop
subject=mic): ``mic_backlog_trim`` (quiet packets given back) and ``mic_queue_cap`` (the helper's cap was reached, the oldest sound is lost)."""
import asyncio
import base64
import logging

from echo_sync.native_media_socket import MIC_QUEUE_TRIM_MS, MicQueue, NativeMediaSocket

from test_w8_net import Source, burst, feed, quiet, tone, wire_for


def lines(caplog):
    return [r.getMessage() for r in caplog.records if 'echo-sync why kind=drop subject=mic' in r.getMessage()]


def jitter(kind, rounds=6):
    """100 ms packets with a stall of 600 ms every second, the late ones in a burst: ``rounds`` of them."""
    out, t = [], 0.0
    for _ in range(rounds):
        out += [(t + i * 0.1, kind(100)) for i in range(4)]
        t += 1.0
        out += [(t, kind(100)) for _ in range(6)]
    return out


def test_the_queue_is_bounded_on_a_default_wire_under_artificial_jitter(tmp_path):
    wire, source = feed(tmp_path, jitter(quiet))
    assert wire.mic_queue.max_ms <= MIC_QUEUE_TRIM_MS + 100 and wire.mic_queue.dropped_ms > 0
    assert len(source.frames) < 6 * 10


def test_speech_is_never_dropped_and_the_queue_never_passes_the_cap(tmp_path):
    wire, source = feed(tmp_path, jitter(tone, rounds=12))
    assert len(source.frames) == 12 * 10 and wire.mic_queue.dropped_ms == 0
    assert wire.mic_queue.max_ms <= MicQueue.cap_ms


def test_a_trim_is_a_journal_record_with_a_reason(tmp_path, caplog):
    caplog.set_level(logging.INFO, logger='echo-sync')
    async def main():
        now = [0.0]
        wire, _ = wire_for(tmp_path, clock=lambda: now[0])
        wire.facts_why = True;wire.source = Source();wire.ready = True
        for at, pcm in burst(quiet):
            now[0] = at
            await wire.client({'type': 'input_audio_buffer.append', 'audio': base64.b64encode(pcm).decode()})
        await wire.close()
    asyncio.run(main())
    got = lines(caplog)
    assert len(got) == 1 and 'rule=mic_backlog_trim' in got[0] and 'const=MIC_QUEUE_TRIM_MS' in got[0] and 'ms=' in got[0], got


def test_a_queue_that_hits_the_cap_loses_sound_with_a_record(tmp_path, caplog):
    caplog.set_level(logging.INFO, logger='echo-sync')
    async def main():
        now = [0.0]
        wire, _ = wire_for(tmp_path, clock=lambda: now[0])
        wire.facts_why = True;wire.source = Source();wire.ready = True
        for i in range(30):                                  # speech, 3 s at once after a stall: more than the helper's cap
            await wire.client({'type': 'input_audio_buffer.append', 'audio': base64.b64encode(tone(100)).decode()})
        await wire.close()
        return wire
    wire = asyncio.run(main())
    got = lines(caplog)
    assert any('rule=mic_queue_cap' in g for g in got) and wire.mic_queue.lost_ms > 0, got


def test_the_close_line_carries_the_totals_with_no_flag_needed(tmp_path, caplog):
    caplog.set_level(logging.INFO, logger='echo-sync')
    feed(tmp_path, burst(quiet))
    assert any('echo-sync mic queue' in r.getMessage() and 'dropped_ms=' in r.getMessage() and 'lost_ms=' in r.getMessage() for r in caplog.records)
