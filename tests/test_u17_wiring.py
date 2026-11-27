"""U17-S4: the input meter wired in shadow. The socket and the controller feed it (mic_packet, input_vad, input_fault, the cue events, the ear's text, the owner's words); the tick logs
state= act= got_s= duplex= with numbers only; nothing is held (shadow); the call_close counters carry the summary. Injected clock."""
import logging
import sys
import timeit
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from echo_sync.controlled_media import ControlledMedia      # noqa: E402
from echo_sync.native_media_socket import NativeMediaSocket, pcm_dbfs      # noqa: E402
from echo_sync.settings import resolve      # noqa: E402
from test_h3_tempo import call       # noqa: E402,F401 - call is the fixture
from test_x_tick_order import armed      # noqa: E402

LOG = 'echo-sync'
PACKET = b'\x10\x00' * 480      # 20 ms of 24 kHz mono 16-bit, not digital zero


def feed(c, n, start, step=0.02):
    for i in range(n):
        c.mic_packet(len(PACKET), -30.0, now=start + i * step)


def test_the_default_is_shadow_and_off_is_inert(tmp_path):
    assert resolve({})['input_state'] == 'shadow'
    assert resolve({'input_state': 'bogus'})['input_state'] == 'shadow'
    c = ControlledMedia(tmp_path / 's.db', session_id='s', settings={'input_state': 'off'})
    c.mic_packet(len(PACKET), -30.0)
    c.input_vad(100)
    c.input_fault('x')
    assert c.input_counts() == {} and getattr(c, 'input_meter', None) is None


def test_twenty_packets_log_silence_and_nothing_is_held(call, caplog):
    rig, c, state = armed(call)
    now = c.clock()
    feed(c, 20, now - 0.5)
    c.repeat_at = now
    with caplog.at_level(logging.INFO, logger=LOG):
        c.tick(now=now)
    line = [r.getMessage() for r in caplog.records if 'input_state' in r.getMessage()]
    assert line and 'state=silence' in line[0] and 'act=repeat' in line[0] and 'got_s=0.4' in line[0] and 'duplex=' in line[0], line
    assert getattr(c, 'input_meter', None) is None, 'shadow: the gate has no meter to obey'


def test_a_gap_logs_no_packets_while_the_cue_is_still_emitted(call, caplog):
    rig, c, state = armed(call)
    now = c.clock()
    feed(c, 25, now - 2.5)      # the last packet 2.0 s ago: a gap of more than the 1.0 s
    c.repeat_at = now
    before = len(rig.said())
    with caplog.at_level(logging.INFO, logger=LOG):
        out = c.tick(now=now)
    assert any('state=no_packets' in r.getMessage() and 'act=hold' in r.getMessage() for r in caplog.records)
    assert out, 'shadow: the repeat is still emitted'
    assert len(rig.said()) >= before


def test_the_cue_events_and_the_ears_text_reach_the_meter(tmp_path):
    c = ControlledMedia(tmp_path / 's.db', session_id='s', settings={'words_per_portion': 3})
    feed(c, 25, 100.0)
    m = c.input_probe
    assert m.packets == 25
    cue = {'revision': 1, 'index': 0, 'text': 'a'}
    c._cue_event('began', cue, 101.0)
    assert m._in_cue
    c._cue_event('done', cue, 102.0)
    assert not m._in_cue and m._cue_end == 102.0
    c.input_vad(400)
    assert m.voiced_ms == 400
    c.input_fault('ear')
    assert m.fault_at is not None
    summary = c.input_counts()
    assert summary['input_packets'] == 25 and all(isinstance(v, (int, float, str)) for v in summary.values())


def test_the_ears_final_is_given_to_the_meter(call):
    rig, c, state = armed(call)
    c.tempo_heard({'uid': 1, 'text': 'слова', 'offset': c.clock(), 'kind': 'final'})
    assert c.input_probe.heard_at is not None
    c.tempo_heard({'uid': 2, 'text': '', 'offset': c.clock(), 'reason': 'ear_other_language', 'speech_ms': 500})
    assert c.input_probe.pending_until is not None


def test_the_socket_hands_packets_with_their_level_to_the_controller(tmp_path):
    seen = []

    class Spy:
        input_mode = 'shadow'

        def mic_packet(self, nbytes, dbfs, now=None):
            seen.append((nbytes, dbfs))

    wire = NativeMediaSocket.__new__(NativeMediaSocket)
    wire.controller = Spy()
    wire._meter_packet(PACKET)
    assert seen and seen[0][0] == len(PACKET) and seen[0][1] < 0
    wire.controller = object()
    wire._meter_packet(PACKET)      # a controller with no meter: nothing happens


def test_pcm_dbfs_cost_per_packet():
    n = 200
    per = timeit.timeit(lambda: pcm_dbfs(PACKET), number=n) / n
    print(f'pcm_dbfs 20 ms packet: {per * 1e6:.0f} us')
    assert per < 0.005      # a packet comes every 20 ms; this is a generous bound, the measured number is printed
