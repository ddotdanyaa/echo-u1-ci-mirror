"""U27: phone packet loss is not silence. Proved from the code, pinned here: (1) the ear's clock is the audio received (sample count), never the wall clock, so
packets that did not come cost no silence frames and cannot end an utterance; (2) the input meter reads a lost channel / digital zero as ``hold``, never as
``silence`` -> ``repeat``; (3) call_audio's DRIFT_MS gap fill is a recording tap only, nothing of the live path reads it. The zero fill of a stall that
really reaches the cloud is the helper's (MicQueue docstring) and not in this repo."""
import asyncio
import base64
import inspect

from echo_sync import call_audio, call_trace
from echo_sync.controlled_media import ControlledMedia
from echo_sync.input_state import InputMeter
from echo_sync.local_ear import SpeechOnset
from echo_sync.native_media_socket import NativeMediaSocket

from test_w8_net import Source, quiet, tone


def test_the_ear_counts_audio_received_not_time_passed():
    ear = SpeechOnset()
    ear.feed(quiet(100))                 # the floor
    for _ in range(5):
        ear.feed(tone(100))
    assert ear.speaking
    assert ear.speaking and ear.quiet_ms == 0, 'seconds with no packet fed: nothing is counted as silence'
    ear.feed(tone(100))
    assert ear.speaking and ear.quiet_ms == 0, 'speech goes on across the hole'


def test_a_stall_in_the_packets_does_not_end_the_utterance_on_the_wire(tmp_path):
    async def main():
        now = [0.0]
        async def emit(frame):pass
        wire = NativeMediaSocket(ControlledMedia(tmp_path / 's.db', session_id='s'), emit, lambda: None, lambda _: None, lambda _: None, clock=lambda: now[0])
        wire.source = Source();wire.ready = True
        for at in (0.0, 0.1, 0.2, 0.3, 0.4, 3.4, 3.5):        # 3 s without a packet in the middle of the speech
            now[0] = at
            await wire.client({'type': 'input_audio_buffer.append', 'audio': base64.b64encode(quiet(100) if at == 0.0 else tone(100)).decode()})
            if at == 0.4:
                assert wire.onset.speaking
        assert wire.onset.speaking and wire.onset.quiet_ms == 0
        await wire.close()
    asyncio.run(main())


def test_lost_packets_and_dead_input_hold_the_repeat_they_are_not_silence():
    step = 0.1
    m = InputMeter(0.0)
    t = 0.0
    for _ in range(10):
        t += step
        m.packet(t, int(step * call_trace.PCM_BYTES_PER_SECOND), -30.0)
    m.vad(t, 600)
    assert m.repeat_action(t + 3.0).state == 'no_packets' and m.repeat_action(t + 3.0).act == 'hold', 'a hole in the packets'
    m2 = InputMeter(0.0)
    t = 0.0
    for _ in range(30):                  # three seconds of exact zeros: what a fill looks like
        t += step
        m2.packet(t, int(step * call_trace.PCM_BYTES_PER_SECOND), -90.0)
    assert m2.repeat_action(t).state == 'dead_input' and m2.repeat_action(t).act == 'hold'


def test_the_recording_gap_fill_is_not_read_by_the_live_path():
    src = inspect.getsource(call_audio)
    for live in ('local_ear', 'input_state', 'vad_silero', 'native_media_socket', 'ear_shadow'):
        assert 'import ' + live not in src and 'from .' + live not in src, live
