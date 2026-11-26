"""U07-S3: the recorder of the call's sound through controlled_host.serve (helpers_s6_fault.HostRig).

A phone call is always recorded (no switch); a probe (``echo_trace=1``) only when it asks: ``echo_pcm_record=1``.
The recorder never changes what the phone sees, and a disk that fails costs the call nothing. The state of the recording is in call_close.
"""
import base64
import hashlib
import json
from pathlib import Path

import helpers_s6_fault as F
from echo_sync import call_audio
from test_ux_call_trace_host import dictation, normal_end, read_trace, settings_file, what_the_phone_saw

PACKET = bytes(range(256)) * 4        # 1024 bytes of known content, not silence


def pcm_root(home):
    return Path(home) / 'logs' / 'echo_pcm'


def data_of(path):
    return Path(path).read_bytes()[call_audio.HEADER:]


async def call(host, packets=5):
    await host.handshake()
    for _ in range(packets):
        host.ws.push({'type': 'input_audio_buffer.append', 'audio': base64.b64encode(PACKET).decode()})
    await dictation(host)
    await host.advance(20)


def run_call(tmp_path, monkeypatch, prepare=None, packets=5, **rig):
    async def main():
        F.patch_clock(monkeypatch)
        async with F.HostRig(tmp_path, monkeypatch, **rig) as host:
            if prepare:
                prepare(host)
            await call(host, packets)
        return host
    return F.run(main)


def only_call_dir(home):
    dirs = [p for p in pcm_root(home).iterdir() if p.is_dir()]
    assert len(dirs) == 1, dirs
    return dirs[0]


def test_on_the_mic_and_the_cues_are_written_byte_for_byte(tmp_path, monkeypatch):
    real = call_audio.CallAudio       # a frozen clock: real time between two virtual-time frames would be filled with silence (a gap line), which is the recorder's job but not this test's
    monkeypatch.setattr(call_audio, 'CallAudio', lambda root, call_id, **k: real(root, call_id, clock=lambda: 0.0, **k))
    host = run_call(tmp_path, monkeypatch)
    folder = only_call_dir(host.home)
    sent = b''.join(PACKET for _ in range(5))
    assert hashlib.sha256(data_of(folder / 'mic.wav')).hexdigest() == hashlib.sha256(sent).hexdigest()
    cues = b''.join(base64.b64decode(f.data['delta']) for f in host.audio())
    assert cues, 'the scenario speaks'
    assert hashlib.sha256(data_of(folder / 'cue.wav')).hexdigest() == hashlib.sha256(cues).hexdigest()
    assert (folder / 'timeline.jsonl').is_file()


def test_a_phone_call_is_recorded_with_no_key_in_the_profile(tmp_path, monkeypatch):
    host = run_call(tmp_path, monkeypatch)
    assert (only_call_dir(host.home) / 'mic.wav').is_file()
    assert 'pcm_record' not in __import__('echo_sync.settings', fromlist=['DEFAULTS']).DEFAULTS


def test_a_probe_records_only_when_it_asks(tmp_path, monkeypatch):
    host = run_call(tmp_path / 'plain', monkeypatch, query={'echo_trace': '1'})
    assert not pcm_root(host.home).exists(), 'the profile switch is the phone call\'s; a probe has its own'
    host = run_call(tmp_path / 'asked', monkeypatch, query={'echo_trace': '1', 'echo_pcm_record': '1'})
    assert (only_call_dir(host.home) / 'mic.wav').is_file()


def test_the_phone_sees_exactly_the_same_with_the_recorder_working_and_broken(tmp_path, monkeypatch):
    on = run_call(tmp_path / 'on', monkeypatch)
    with monkeypatch.context() as patched:
        patched.setattr(call_audio, 'CallAudio', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('no recorder')))
        off = run_call(tmp_path / 'off', patched)
    assert what_the_phone_saw(on) == what_the_phone_saw(off) and len(what_the_phone_saw(on)) > 10
    assert normal_end(on.outcome) and normal_end(off.outcome)


def test_call_close_carries_the_state_of_the_recording(tmp_path, monkeypatch):
    host = run_call(tmp_path, monkeypatch)
    close = [r for r in read_trace(host.home) if r.get('ev') == 'call_close'][0]
    rec = close['pcm_rec']
    assert rec['state'] == 'on' and rec['bytes'] >= 5 * len(PACKET) and rec['dropped'] == 0


def test_a_disk_that_fails_leaves_the_call_untouched(tmp_path, monkeypatch):
    def broken_opener(path, mode='r', *a, **k):
        raise OSError(28, 'No space left on device')
    real = call_audio.CallAudio.__init__

    def init(self, root, call_id, cap_mb=200, opener=open, clock=call_audio.time.monotonic):
        real(self, root, call_id, cap_mb, broken_opener, clock)
    with monkeypatch.context() as patched:
        patched.setattr(call_audio.CallAudio, '__init__', init)
        broken = run_call(tmp_path / 'broken', patched)
    free = run_call(tmp_path / 'free', monkeypatch)
    assert what_the_phone_saw(broken) == what_the_phone_saw(free) and normal_end(broken.outcome)
    close = [r for r in read_trace(broken.home) if r.get('ev') == 'call_close'][0]
    assert close['pcm_rec']['state'] in ('no_space', 'failed:OSError')


def test_a_recorder_that_cannot_start_costs_the_call_nothing(tmp_path, monkeypatch):
    def explode(*a, **k):
        raise RuntimeError('bug in the recorder')
    with monkeypatch.context() as patched:
        patched.setattr(call_audio, 'CallAudio', explode)
        broken = run_call(tmp_path / 'broken', patched)
    free = run_call(tmp_path / 'free', monkeypatch)
    assert what_the_phone_saw(broken) == what_the_phone_saw(free) and normal_end(broken.outcome)
    assert 'pcm_rec' not in [r for r in read_trace(broken.home) if r.get('ev') == 'call_close'][0]


def test_old_calls_are_pruned_to_the_profile_limit(tmp_path, monkeypatch):
    def prepare(host):
        settings_file(host.home, pcm_record_calls=2)
        for name in ('old1', 'old2', 'old3'):
            d = pcm_root(host.home) / name
            d.mkdir(parents=True)
            (d / 'mic.wav').write_bytes(b'x')
    host = run_call(tmp_path, monkeypatch, prepare=prepare)
    names = sorted(p.name for p in pcm_root(host.home).iterdir())
    assert len(names) == 2 and any(n not in ('old1', 'old2', 'old3') for n in names)

