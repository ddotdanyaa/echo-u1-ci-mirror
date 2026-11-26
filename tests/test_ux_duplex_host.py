"""UX-trace, the duplex evidence through controlled_host.serve (coordinator addition).

A fake phone sends a 100 ms microphone packet ten times a second. A HALF-duplex phone (the owner's, on the open speaker) sends nothing
while a cue plays and for 0.35 s after it; a FULL-duplex phone (headphones, or the talk-over switch) keeps sending. The real serve() on
virtual time must show which it was - in the trace file and, as numbers only, in the "Controlled call closed" line of the agent log.
"""
import asyncio
import base64
import json
import math
import struct
from pathlib import Path

import pytest

import helpers_s6_fault as F

PACKET_BYTES = 4800                                   # 100 ms of 24 kHz 16-bit mono PCM
TONE = struct.pack('<%dh' % (PACKET_BYTES // 2), *(round(3000 * math.sin(2 * math.pi * 440 * i / 24000)) for i in range(PACKET_BYTES // 2)))   # a working microphone (about -21 dBFS), not the digital zero the input meter calls dead
APPEND = {'type': 'input_audio_buffer.append', 'audio': base64.b64encode(TONE).decode()}
ECHO_TAIL = 0.35                                      # a half-duplex phone keeps its microphone shut this long after a cue (research 1.2)


def settings_file(home, **values):
    folder = Path(home) / 'materials'
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'echo_settings.json').write_text(json.dumps(values), encoding='utf-8')


def trace_rows(home):
    files = sorted((f for f in (Path(home) / 'logs' / 'echo_calls').glob('*.jsonl') if '.v5tap' not in f.name))
    assert len(files) == 1, files
    return [json.loads(line) for line in files[0].read_text(encoding='utf-8').splitlines()]


def cue_in_flight(host):
    for frame in reversed(host.ws.frames):
        if frame.type in {'response.created', 'response.done', 'output_audio_buffer.clear'}:
            return frame.type == 'response.created'
    return False


async def listen(host, seconds, *, half_duplex):
    """The fake phone's microphone for ``seconds``."""
    end = host.now() + seconds
    quiet_until = 0.0
    while host.now() < end:
        if cue_in_flight(host):
            quiet_until = host.now() + ECHO_TAIL
        if not (half_duplex and (cue_in_flight(host) or host.now() < quiet_until)):
            host.ws.push(APPEND)
        await host.advance(0.1)


def closed_metadata(host):
    """The metadata of the "Controlled call closed" line of the agent log, as the owner (or a script) reads it."""
    line = next(text for level, text in host.logger.lines if text.startswith('Controlled call closed'))
    return json.loads(line.split('metadata=', 1)[1])


def a_call(tmp_path, monkeypatch, *, half_duplex, query=None, ask=True, seconds=22, **profile):
    """A whole call: the question, the cloud's answer, then ``seconds`` of microphone. Cues of 2.5 s, repeated by the silence timer.
    U17: a half-duplex phone (no packets during cues) gets one portion at most 1 + ``HALF_DUPLEX_REPEATS`` = 3 times in a row, a full-duplex one 1 + 3 = 4."""
    async def main():
        F.patch_clock(monkeypatch)
        # the fake phone below is the only microphone: the stand's own always-on line (LiveLine) would read as full duplex to the meter
        async with F.HostRig(tmp_path, monkeypatch, synth=[('long', 2.5)], query=query, mic_stream=False) as host:
            settings_file(host.home, **{'repeat_seconds': 1, 'max_auto_repeats': 3, **profile})
            await host.handshake()
            phone = asyncio.create_task(listen(host, seconds, half_duplex=half_duplex))
            if ask:
                await host.ask(F.DIRECT_QUESTION, tid='u1')
                await host.answer(F.DIRECT_ANSWER, tid='a1')
            await phone
        return host
    return F.run(main)


def test_a_half_duplex_phone_is_reported_half_in_the_trace_and_in_the_agent_log(tmp_path, monkeypatch):
    host = a_call(tmp_path, monkeypatch, half_duplex=True)
    rows = trace_rows(host.home)
    duplex = [r for r in rows if r['ev'] == 'duplex'][0]
    assert rows[-2]['ev'] == 'duplex' and rows[-1]['ev'] == 'call_close'
    assert duplex['verdict'] == 'half' and duplex['cues'] == 3 and duplex['mean_packet_ms'] == 100.0
    assert duplex['cue_span_s'] == pytest.approx(7.5, abs=0.3)
    assert duplex['mic_missing_cue_s'] > 6.5 and duplex['mic_missing_idle_s'] < 3.0 and duplex['cue_coverage'] < 0.05
    meta = closed_metadata(host)
    assert meta['duplex'] == 'half' and meta['mic_packet_ms'] == 100.0 and meta['cue_span_s'] == duplex['cue_span_s']
    assert meta['mic_missing_cue_s'] == duplex['mic_missing_cue_s'] and meta['mic_missing_idle_s'] == duplex['mic_missing_idle_s']
    assert meta['input_pcm_packets'] == duplex['packets'] > 100                    # "input packets" - the existing counter, the same number


def test_a_full_duplex_phone_is_reported_full(tmp_path, monkeypatch):
    host = a_call(tmp_path, monkeypatch, half_duplex=False)
    duplex = [r for r in trace_rows(host.home) if r['ev'] == 'duplex'][0]
    assert duplex['verdict'] == 'full' and duplex['cue_coverage'] > 0.9 and duplex['mic_missing_cue_s'] < 1.0
    assert closed_metadata(host)['duplex'] == 'full'


def test_the_trace_shows_where_the_microphone_was_shut(tmp_path, monkeypatch):
    """Per-second counts with the exact edges: in a half-duplex call no microphone second lies inside a cue, in a full-duplex one many do."""
    def seconds_inside_cues(half_duplex, folder):
        host = a_call(folder, monkeypatch, half_duplex=half_duplex)
        rows = trace_rows(host.home)
        spans = [(r['first_ms'], r['last_ms']) for r in rows if r['ev'] == 'cue_end' and 'first_ms' in r]
        assert len(spans) == (3 if half_duplex else 4) and all(2400 <= b - a <= 2520 for a, b in spans), spans
        mic = [r for r in rows if r['ev'] == 'mic']
        assert mic and all(r['bytes'] == r['n'] * PACKET_BYTES for r in mic)
        return [m for m in mic if any(a < m['first_ms'] and m['last_ms'] < b for a, b in spans)]
    assert seconds_inside_cues(True, tmp_path / 'half') == []
    assert len(seconds_inside_cues(False, tmp_path / 'full')) >= 4


def test_every_cue_has_its_first_and_last_pcm_time_and_the_text_it_spoke(tmp_path, monkeypatch):
    host = a_call(tmp_path, monkeypatch, half_duplex=True)
    rows = trace_rows(host.home)
    cues = [r for r in rows if r['ev'] == 'cue']
    ends = [r for r in rows if r['ev'] == 'cue_end']
    assert len(cues) == len(ends) == 3 and all(e['status'] == 'completed' for e in ends)
    assert all(c['t'] == e['first_ms'] for c, e in zip(cues, ends))
    assert all(e['frames'] == 125 for e in ends)                                   # 2.5 s of 20 ms frames
    assert any(r['ev'] == 'ready' for r in rows)


def test_the_agent_log_has_the_numbers_even_when_the_trace_file_is_off(tmp_path, monkeypatch):
    host = a_call(tmp_path, monkeypatch, half_duplex=True, query={'echo_trace': '1'})      # a probe writes no trace file
    assert not (host.home / 'logs').exists()
    meta = closed_metadata(host)
    assert meta['duplex'] == 'half' and meta['mic_missing_cue_s'] > 6.5


def test_a_call_in_which_nothing_was_spoken_has_no_verdict(tmp_path, monkeypatch):
    host = a_call(tmp_path, monkeypatch, half_duplex=True, ask=False, seconds=12)
    duplex = [r for r in trace_rows(host.home) if r['ev'] == 'duplex'][0]
    assert duplex['verdict'] == 'unknown' and duplex['cues'] == 0 and duplex['packets'] >= 115
    meta = closed_metadata(host)
    assert meta['duplex'] == 'unknown' and meta['cue_span_s'] == 0 and meta['mic_missing_cue_s'] == 0


def test_a_probe_call_reports_numbers_too_and_writes_no_file(tmp_path, monkeypatch):
    host = a_call(tmp_path, monkeypatch, half_duplex=False, query={'echo_trace': '1'}, ask=False, seconds=6)
    assert not (host.home / 'logs').exists()
    assert closed_metadata(host)['duplex'] == 'unknown'


def test_the_log_line_holds_numbers_and_a_verdict_only(tmp_path, monkeypatch):
    host = a_call(tmp_path, monkeypatch, half_duplex=True)
    meta = closed_metadata(host)
    added = {'duplex', 'mic_packet_ms', 'mic_missing_cue_s', 'mic_missing_idle_s', 'cue_span_s'}
    assert added <= set(meta)
    assert all(isinstance(meta[key], (int, float)) for key in added - {'duplex'}) and meta['duplex'] in {'half', 'full', 'unknown'}
    # u13 (U17-S4): the input meter adds its own flat ``input_*`` numbers and two labels from closed sets; nothing else may appear
    meter_keys = {'input_packets', 'input_got_s', 'input_voiced_ms', 'input_duplex', 'input_state'}
    states = {'no_packets', 'warming', 'asr_fault', 'dead_input', 'silence', 'heard'}
    assert set(meta) - {k for k in meta if k.startswith('input_n_') and k[len('input_n_'):] in states} == added | meter_keys | {'input_pcm_packets', 'output_pcm_packets', 'user_segments', 'user_finals', 'last_error'}
    assert meta['input_duplex'] in {'half', 'full', 'unknown'} and meta['input_state'] in states
    assert all(isinstance(meta[k], (int, float)) for k in meta if k.startswith('input_n_') or k in meter_keys - {'input_duplex', 'input_state'})
    line = next(text for level, text in host.logger.lines if text.startswith('Controlled call closed'))
    assert F.DIRECT_QUESTION not in line and F.DIRECT_ANSWER not in line and '\n' not in line
