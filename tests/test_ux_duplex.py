"""UX-trace, the duplex evidence: did the phone's microphone keep sending while a cue played (full duplex) or go silent (half duplex)?

Coordinator addition to Task UX-trace (research: DUAL_SYSTEM_DESIGN.md sections 1.2-1.4 and 4 P0). The trace records, as numbers only and
never audio: the arrival of the phone's microphone packets (per second: how many, how many bytes, first and last arrival), the first and
last PCM send time of every cue, and at the close of the call ONE summary line - packets, mean packet length, the seconds the microphone
was missing while a cue played and while none did, and a verdict 'half' | 'full' | 'unknown'.

These tests drive echo_sync.call_trace.CallTrace on a fake clock with a fake phone. The same inside serve() is in test_ux_duplex_host.py.
"""
import base64
import json
import re
from pathlib import Path

import pytest

from echo_sync import call_trace
from echo_sync.call_trace import CallTrace

CALL = '0123456789ab'
READY_MARKER = {'type': 'response.done', 'response': {'status': 'completed', 'output': []}}


class Clock:
    def __init__(self):
        self.now = 5000.0

    def __call__(self):
        return self.now


def append(nbytes=4800):
    """One input_audio_buffer.append: 4800 bytes of 24 kHz 16-bit mono PCM are 100 ms - what the owner's phone sends ten times a second."""
    return {'type': 'input_audio_buffer.append', 'audio': base64.b64encode(b'\0' * nbytes).decode()}


def records(path):
    return [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines()]


class Call:
    """A fake call against a CallTrace: a phone that sends 100 ms packets, and cues of 20 ms frames paced like the transport does."""

    def __init__(self, tmp_path=None, **keywords):
        self.clock = Clock()
        self.trace = CallTrace(tmp_path / 'echo_calls' if tmp_path else None, CALL, clock=self.clock, **keywords)
        self.trace.open(source='phone')
        self.trace.frame(READY_MARKER)

    def listen(self, seconds, nbytes=4800):
        """The microphone is open: a packet every 100 ms (of ``nbytes`` bytes, so 4800 is 100 ms)."""
        for _ in range(round(seconds * 10)):
            self.clock.now += 0.1
            self.trace.mic(append(nbytes))

    def silence(self, seconds):
        self.clock.now += seconds

    def cue(self, seconds, *, text='порция', mic_open=False, end='done'):
        """One spoken response: ``seconds`` of 20 ms frames. ``mic_open`` = a full-duplex phone, which goes on sending packets meanwhile."""
        trace = self.trace
        trace.frame({'type': 'response.created', 'response': {'id': 'r'}})
        trace.frame({'type': 'response.audio_transcript.delta', 'response_id': 'r', 'delta': text})
        for k in range(round(seconds / 0.02)):
            trace.frame({'type': 'response.audio.delta', 'response_id': 'r', 'delta': 'AAAA'})
            self.clock.now += 0.02
            if mic_open and k % 5 == 4:
                trace.mic(append())
        if end == 'done':
            trace.frame({'type': 'response.done', 'response': {'id': 'r', 'status': 'completed'}})
        elif end == 'cut':
            trace.frame({'type': 'output_audio_buffer.clear'})

    def close(self, **fields):
        return self.trace.close(**fields)


def owners_call(tmp_path, *, half_duplex, cues=4):
    """ready -> [4 s of listening, a 2 s cue, 0.35 s more of an echo guard on a half-duplex phone] x cues."""
    call = Call(tmp_path)
    for _ in range(cues):
        call.listen(4)
        call.cue(2.0, mic_open=not half_duplex)
        if half_duplex:
            call.silence(0.35)
    summary = call.close(elapsed_ms=1)
    return call, summary


def duplex_record(call):
    found = [r for r in records(call.trace.path) if r['ev'] == 'duplex']
    assert len(found) == 1
    return found[0]


# --- the verdict -------------------------------------------------------------------------------------------------------------

def test_a_phone_that_goes_silent_while_a_cue_plays_is_half_duplex(tmp_path):
    """The owner's call 35115fb1a8e5 in miniature: packets keep coming between cues, none while a cue plays."""
    call, summary = owners_call(tmp_path, half_duplex=True)
    duplex = duplex_record(call)
    assert duplex['verdict'] == 'half' and summary['duplex'] == 'half'
    assert duplex['packets'] == 160 and duplex['mean_packet_ms'] == 100.0 and duplex['cues'] == 4
    assert duplex['cue_span_s'] == pytest.approx(8.0, abs=0.1)
    assert duplex['mic_missing_cue_s'] == pytest.approx(8.0, abs=0.1)         # the whole of every cue
    assert duplex['mic_missing_idle_s'] == pytest.approx(1.4, abs=0.1)         # only the 0.35 s after each cue
    assert duplex['cue_coverage'] == pytest.approx(0.0, abs=0.02) and duplex['idle_coverage'] > 0.9


def test_a_phone_that_keeps_sending_while_a_cue_plays_is_full_duplex(tmp_path):
    call, summary = owners_call(tmp_path, half_duplex=False)
    duplex = duplex_record(call)
    assert duplex['verdict'] == 'full' and summary['duplex'] == 'full'
    assert duplex['mic_missing_cue_s'] < 0.5 and duplex['cue_coverage'] > 0.9
    assert duplex['packets'] == 4 * (40 + 20)                                         # the packets sent during the cues count too


def test_no_cue_no_verdict(tmp_path):
    """A call in which nothing was spoken (the 16:10 call of the research) cannot show anything about the microphone during a cue."""
    call = Call(tmp_path)
    call.listen(30)
    summary = call.close()
    duplex = duplex_record(call)
    assert duplex['verdict'] == 'unknown' and duplex['cues'] == 0 and duplex['cue_coverage'] is None
    assert duplex['packets'] == 300 and summary['duplex'] == 'unknown'


def test_a_muted_phone_gives_no_verdict(tmp_path):
    """No packets at all (a muted or paused call sends none): not 'half' - nothing was measured."""
    call = Call(tmp_path)
    call.silence(5)
    call.cue(3.0)
    call.silence(5)
    call.close()
    assert duplex_record(call)['verdict'] == 'unknown'


def test_one_short_cue_is_too_little_to_say(tmp_path):
    call = Call(tmp_path)
    call.listen(5)
    call.cue(1.0)
    call.listen(5)
    call.close()
    assert duplex_record(call)['verdict'] == 'unknown'


def test_a_half_covered_cue_is_not_called_either_way(tmp_path):
    """Packets during one cue and none during the other: a changing mode, a Bluetooth route, jitter - the numbers are kept, the verdict honest."""
    mixed = Call(tmp_path)
    mixed.listen(5)
    mixed.cue(4.0, mic_open=True)
    mixed.cue(4.0, mic_open=False)
    mixed.listen(5)
    mixed.close()
    duplex = duplex_record(mixed)
    assert duplex['cue_coverage'] == pytest.approx(0.5, abs=0.05) and duplex['verdict'] == 'unknown'


def test_the_mean_packet_length_is_taken_from_the_bytes(tmp_path):
    call = Call(tmp_path)
    for size in (2400, 7200, 4800):
        call.clock.now += 0.1
        call.trace.mic(append(size))
    call.close()
    assert duplex_record(call)['mean_packet_ms'] == 100.0 and duplex_record(call)['packets'] == 3
    other = Call(tmp_path / 'other')
    for _ in range(4):
        other.clock.now += 0.064
        other.trace.mic(append(3072))                                          # 64 ms
    other.close()
    assert duplex_record(other)['mean_packet_ms'] == 64.0


def test_the_summary_for_the_log_is_numbers_only(tmp_path):
    """The host puts these into the "Controlled call closed" line of the agent log: a verdict and numbers, no text, no audio."""
    call, summary = owners_call(tmp_path, half_duplex=True)
    assert set(summary) == {'duplex', 'mic_packet_ms', 'mic_missing_cue_s', 'mic_missing_idle_s', 'cue_span_s'}
    assert summary['duplex'] == 'half' and summary['mic_packet_ms'] == 100.0
    assert all(isinstance(v, (int, float)) for k, v in summary.items() if k != 'duplex')


# --- what the file shows ------------------------------------------------------------------------------------------------------

def test_the_ready_marker_is_recorded_once(tmp_path):
    call = Call(tmp_path)
    call.trace.frame(READY_MARKER)                    # a repeated marker is not a second start
    call.close()
    assert [r['ev'] for r in records(call.trace.path)] == ['call_open', 'ready', 'duplex', 'call_close']


def test_the_microphone_is_recorded_per_second_with_the_first_and_last_arrival(tmp_path):
    """Per-second counts are enough to see a gap; the first/last arrival make the edge of the gap exact."""
    call = Call(tmp_path)
    call.listen(5)
    call.silence(3.0)
    call.listen(5)
    call.close()
    mic = [r for r in records(call.trace.path) if r['ev'] == 'mic']
    assert sum(r['n'] for r in mic) == 100 and sum(r['bytes'] for r in mic) == 100 * 4800
    assert all(r['n'] >= 1 and r['first_ms'] <= r['last_ms'] for r in mic)
    assert [r['sec'] for r in mic] == sorted(set(r['sec'] for r in mic))
    assert all(isinstance(r['sec'], int) for r in mic)
    gaps = [(a['last_ms'], b['first_ms']) for a, b in zip(mic, mic[1:]) if b['first_ms'] - a['last_ms'] > 1000]
    assert len(gaps) == 1 and 3000 <= gaps[0][1] - gaps[0][0] <= 3200           # the silent 3 s, with its exact edges


def test_a_cue_records_when_its_first_and_its_last_pcm_were_sent(tmp_path):
    call = Call(tmp_path)
    call.listen(2)
    call.cue(2.0)
    call.close()
    cue, end = [r for r in records(call.trace.path) if r['ev'] in {'cue', 'cue_end'}]
    assert cue['text'] == 'порция' and end['status'] == 'completed' and end['frames'] == 100
    assert cue['t'] == end['first_ms'] == 2000
    assert end['last_ms'] == 2000 + 99 * 20
    assert duplex_record(call)['cue_span_s'] == 2.0 and duplex_record(call)['cues'] == 1       # 100 frames of 20 ms, the last one included


def test_a_cut_cue_records_the_span_it_had_reached(tmp_path):
    call = Call(tmp_path)
    call.cue(0.5, end='cut')
    call.close()
    cut = [r for r in records(call.trace.path) if r['ev'] == 'cue_cut'][0]
    assert cut['frames'] == 25 and cut['first_ms'] == 0 and cut['last_ms'] == 24 * 20


def test_a_clear_with_no_cue_in_flight_is_a_plain_cut(tmp_path):
    call = Call(tmp_path)
    call.trace.frame({'type': 'output_audio_buffer.clear'})
    call.close()
    cut = [r for r in records(call.trace.path) if r['ev'] == 'cue_cut'][0]
    assert 'frames' not in cut and 'first_ms' not in cut


def test_a_cue_abandoned_without_done_or_clear_is_closed_by_the_next_one(tmp_path):
    """The latent deafness bug of the research (section 1.4.6): a started cue is dropped with no response.done and no clear."""
    call = Call(tmp_path)
    call.trace.frame({'type': 'response.created', 'response': {'id': 'a'}})
    for _ in range(10):
        call.trace.frame({'type': 'response.audio.delta', 'response_id': 'a', 'delta': 'AAAA'})
        call.clock.now += 0.02
    call.cue(0.2)
    call.close()
    ends = [r for r in records(call.trace.path) if r['ev'] == 'cue_end']
    assert [r['status'] for r in ends] == ['abandoned', 'completed'] and ends[0]['frames'] == 10


def test_a_cue_still_in_flight_when_the_call_ends_is_closed_by_the_close(tmp_path):
    call = Call(tmp_path)
    call.cue(1.0, end=None)
    call.close()
    rows = records(call.trace.path)
    assert [r['ev'] for r in rows][-3:] == ['cue_end', 'duplex', 'call_close']
    assert rows[-3]['status'] == 'open' and rows[-3]['frames'] == 50


def test_the_summary_is_the_line_just_before_the_close(tmp_path):
    call, _ = owners_call(tmp_path, half_duplex=True, cues=1)
    rows = records(call.trace.path)
    assert [r['ev'] for r in rows[-2:]] == ['duplex', 'call_close']


def test_a_phone_that_is_silent_even_between_cues_is_not_called_half_duplex(tmp_path):
    """Half duplex means: the microphone works when no cue plays. A phone that sends nothing at all for most of the call is paused or
    muted - the cue-time numbers are kept, the verdict stays unknown."""
    call = Call(tmp_path)
    call.listen(3)
    for _ in range(3):
        call.silence(10)
        call.cue(3.0)
    call.close()
    duplex = duplex_record(call)
    assert duplex['cue_coverage'] == 0.0 and duplex['idle_coverage'] < 0.5 and duplex['verdict'] == 'unknown'


def test_without_a_ready_marker_the_first_packet_starts_the_window(tmp_path):
    """The marker is the handshake's response.done. If it was not seen, the call is taken to be ready when the microphone starts."""
    call = Call(tmp_path)
    call.trace.meter.ready_at = None                   # as if the marker had never come
    call.listen(10)
    call.close()
    assert duplex_record(call)['ready_s'] == pytest.approx(10.0, abs=0.01)


def test_the_seconds_of_the_microphone_count_from_the_moment_the_file_opened(tmp_path):
    clock = Clock()
    trace = CallTrace(tmp_path / 'echo_calls', CALL, clock=clock)
    clock.now += 0.9                                    # the object is made a little before the file is opened
    trace.open()
    trace.frame(READY_MARKER)
    clock.now += 0.3
    trace.mic(append())
    trace.close()
    mic = [r for r in records(trace.path) if r['ev'] == 'mic']
    assert [r['sec'] for r in mic] == [0] and mic[0]['first_ms'] == 300


@pytest.mark.parametrize('size', [0, 1, 2, 3, 4, 958, 960, 962, 4800, 4802, 4804, 95998])
def test_the_length_of_a_packet_is_read_from_its_base64_text_alone(size):
    audio = base64.b64encode(b'\0' * size).decode()
    assert call_trace._pcm_length(audio) == size


def test_a_response_that_has_sent_no_audio_yet_is_not_a_cue_in_flight(tmp_path):
    """A cue is in flight from its FIRST PCM frame; packets that arrive before it are the microphone of a quiet moment."""
    call = Call(tmp_path)
    call.listen(3)
    call.trace.frame({'type': 'response.created', 'response': {'id': 'r'}})
    call.listen(1)                                     # created, but no PCM frame sent yet
    for _ in range(100):
        call.trace.frame({'type': 'response.audio.delta', 'response_id': 'r', 'delta': 'AAAA'})
        call.clock.now += 0.02
    call.trace.frame({'type': 'response.done', 'response': {'id': 'r', 'status': 'completed'}})
    call.listen(3)
    call.close()
    duplex = duplex_record(call)
    assert duplex['cue_coverage'] == 0.0 and duplex['verdict'] == 'half'


def test_a_call_that_is_all_cue_and_has_no_packet_says_nothing(tmp_path):
    """With no idle time to compare with, only the packets themselves tell the microphone from a phone that sent nothing."""
    call = Call(tmp_path)
    call.cue(5.0)
    call.close()
    duplex = duplex_record(call)
    assert duplex['packets'] == 0 and duplex['cue_coverage'] == 0.0 and duplex['idle_coverage'] is None
    assert duplex['verdict'] == 'unknown'


# --- bounded and safe ----------------------------------------------------------------------------------------------------------

def test_the_per_second_lines_have_a_budget_of_their_own_and_the_summary_does_not_need_them(tmp_path, monkeypatch):
    """Break: a long lecture fills the file with microphone seconds and the decisions after that are lost."""
    monkeypatch.setattr(call_trace, 'MIC_BUDGET_BYTES', 600)
    call = Call(tmp_path)
    call.listen(120)
    call.trace.provider({'type': 'turn.done', 'turn': {'id': 'u', 'role': 'user', 'transcript': 'ещё слышно'}})
    summary = call.close()
    rows = records(call.trace.path)
    assert [r['ev'] for r in rows].count('mic_full') == 1
    assert 3 <= len([r for r in rows if r['ev'] == 'mic']) <= 8
    assert any(r['ev'] == 'user_final' for r in rows), 'the budget of the microphone lines never takes the room of the others'
    assert duplex_record(call)['packets'] == 1200 and summary['mic_packet_ms'] == 100.0


def test_an_inert_trace_still_measures_for_the_log(tmp_path):
    """call_trace=off writes no file, but the numbers of the log line (agent.log, no text) are still wanted."""
    call = Call(None)
    for _ in range(4):
        call.listen(4)
        call.cue(2.0)
        call.silence(0.35)
    summary = call.close()
    assert summary['duplex'] == 'half' and summary['mic_missing_cue_s'] == pytest.approx(8.0, abs=0.1)
    assert call.trace.path is None


def test_close_can_be_repeated_and_writes_the_summary_once(tmp_path):
    call, first = owners_call(tmp_path, half_duplex=True, cues=1)
    call.silence(60)                                   # time passes; a second close() must not measure it
    again = call.close()
    assert again == first
    assert [r['ev'] for r in records(call.trace.path)].count('duplex') == 1


def test_a_failed_trace_still_reports_the_numbers(tmp_path, monkeypatch):
    call = Call(tmp_path)
    call.listen(10)
    call.cue(3.0)
    def disk_full(self, line):
        raise OSError(28, 'No space left on device')
    monkeypatch.setattr(CallTrace, '_write_line', disk_full)
    call.listen(1)                                     # the first line that has to be written finds the disk full
    summary = call.close()
    assert call.trace.failure == 'OSError' and not call.trace.active
    assert summary['duplex'] == 'half' and summary['cue_span_s'] == pytest.approx(3.0, abs=0.05)


@pytest.mark.parametrize('event', [None, 7, 'x', [], {}, {'audio': None}, {'audio': 5}, {'audio': ''}, {'type': 'input_audio_buffer.append'}])
def test_a_malformed_append_is_ignored(tmp_path, event):
    call = Call(tmp_path)
    call.trace.mic(event)
    call.close()
    assert duplex_record(call)['packets'] == 0


def test_the_audio_itself_is_never_in_the_file(tmp_path):
    call = Call(tmp_path)
    mic_audio = base64.b64encode(bytes(range(256)) * 20).decode()
    cue_audio = base64.b64encode(bytes(range(255, -1, -1)) * 20).decode()
    call.trace.mic({'type': 'input_audio_buffer.append', 'audio': mic_audio})
    call.trace.frame({'type': 'response.created', 'response': {'id': 'r'}})
    call.trace.frame({'type': 'response.audio.delta', 'response_id': 'r', 'delta': cue_audio})
    call.close()
    text = Path(call.trace.path).read_text(encoding='utf-8')
    assert mic_audio[:40] not in text and cue_audio[:40] not in text
    assert not re.search(r'[A-Za-z0-9+/]{60,}', text), 'no long base64 run anywhere in the file'
