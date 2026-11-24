"""U07-S2: the call recorder: bytes in = bytes out, gaps are said and filled, the cap and the disk faults stop the recording and never the call, prune keeps the newest."""
import errno
import hashlib
import json
import os
import statistics
import time
import wave

from echo_sync import call_audio as ca, timer_policy as tp

PKT = b'\x01\x02' * 480        # 20 ms at 24 kHz


def _lines(d):
    return [json.loads(x) for x in (d / ca.TIMELINE).read_text(encoding='utf-8').splitlines()]


def _rec(tmp_path, **kw):
    return ca.CallAudio(tmp_path, 'c1', **kw)


def test_a_bytes_in_equal_bytes_out_and_the_header_is_fixed(tmp_path):
    rec = _rec(tmp_path)
    data = {'mic': b'', 'cue': b''}
    for i in range(50):
        for ch in data:
            p = bytes([(i + len(ch)) % 256, 7]) * 480
            data[ch] += p
            rec.write(ch, p, t=i * 0.02)
    assert rec.close()['state'] == 'on'
    for ch, blob in data.items():
        path = tmp_path / 'c1' / (ch + '.wav')
        with wave.open(str(path), 'rb') as w:
            assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (24000, 1, 2)
            assert hashlib.sha256(w.readframes(w.getnframes())).hexdigest() == hashlib.sha256(blob).hexdigest()


def test_b_a_late_packet_is_a_gap_line_and_silence_keeps_real_time(tmp_path):
    rec = _rec(tmp_path)
    rec.write('mic', PKT, t=0.0)
    rec.write('mic', PKT, t=0.02)
    rec.write('mic', PKT, t=0.54)           # 0.5 s late
    rec.close()
    with wave.open(str(tmp_path / 'c1' / 'mic.wav'), 'rb') as w:
        assert abs(w.getnframes() / 24000.0 - 0.56) < 0.001
    gaps = [x for x in _lines(tmp_path / 'c1') if x['ev'] == 'gap']
    assert len(gaps) == 1 and gaps[0]['ch'] == 'mic' and gaps[0]['at_ms'] == 40 and 490 <= gaps[0]['ms'] <= 500


def test_b2_jitter_under_the_drift_is_no_gap(tmp_path):
    rec = _rec(tmp_path)
    for i in range(10):
        rec.write('mic', PKT, t=i * 0.02 + (0.03 if i % 2 else 0.0))
    assert rec.close()['gaps'] == 0


def test_b3_two_channels_line_up_on_the_calls_clock(tmp_path):
    rec = _rec(tmp_path, clock=lambda: 100.0)
    rec.write('mic', PKT, t=100.5)
    rec.write('cue', PKT, t=101.25)           # the cue file starts 0.75 s after the mic file
    rec.write('mic', PKT, t=100.52)
    rec.close()
    start = {x['ch']: x['t'] for x in _lines(tmp_path / 'c1') if x['ev'] == 'channel'}
    assert start == {'mic': 0.5, 'cue': 1.25} and start['cue'] - start['mic'] == 0.75


def test_c_the_cap_stops_the_recording_not_the_call(tmp_path):
    rec = _rec(tmp_path, cap_mb=0.01)       # about 10 kB
    for i in range(100):
        rec.write('mic', PKT, t=i * 0.02)
        time.sleep(0.001)
    summary = rec.close()
    assert summary['state'] == 'cap' and summary['bytes'] <= 0.01 * 1024 * 1024
    assert any(x['ev'] == 'cap' for x in _lines(tmp_path / 'c1'))
    assert ca.fix_header(tmp_path / 'c1' / 'mic.wav') == summary['bytes']


def _failing_opener(exc):
    def opener(path, mode='r', *a, **k):
        if str(path).endswith('.wav'):
            raise exc
        return open(path, mode, *a, **k)
    return opener


def test_d_a_full_disk_is_no_space(tmp_path):
    rec = _rec(tmp_path, opener=_failing_opener(OSError(errno.ENOSPC, 'No space left on device')))
    for i in range(5):
        rec.write('mic', PKT, t=i * 0.02)
    assert rec.close()['state'] == 'no_space'
    assert rec.state == 'no_space'
    assert any(x['ev'] == 'no_space' for x in _lines(tmp_path / 'c1'))


def test_e_any_other_fault_is_failed_type_and_nothing_raises(tmp_path):
    rec = _rec(tmp_path, opener=_failing_opener(PermissionError('denied')))
    rec.write('mic', PKT, t=0.0)
    time.sleep(0.05)
    rec.write('mic', PKT, t=0.02)           # after the fault: ignored, no raise
    rec.mark('cue')
    assert rec.close()['state'] == 'failed:PermissionError'
    assert rec.close()['state'] == 'failed:PermissionError'     # twice is safe


def test_e2_an_unwritable_root_does_not_raise(tmp_path):
    blocker = tmp_path / 'file'
    blocker.write_text('x')
    rec = ca.CallAudio(blocker, 'c1')       # the root is a file: mkdir fails
    rec.write('mic', PKT, t=0.0)
    assert rec.close()['state'].startswith('failed:')


def _call(root, name, kb, age):
    d = root / name
    d.mkdir()
    (d / 'mic.wav').write_bytes(b'\0' * (kb * 1024))
    os.utime(d, (age, age))
    return d


def test_f_prune_keeps_the_newest_calls_and_the_protected_one(tmp_path):
    for i in range(6):
        _call(tmp_path, 'c%d' % i, 1, 1000 + i)
    assert ca.prune(tmp_path, keep_calls=3, max_mb=100) == ['c0', 'c1', 'c2']
    assert ca.prune(tmp_path, keep_calls=1, max_mb=100, protect='c3') == ['c4', 'c5']
    assert sorted(p.name for p in tmp_path.iterdir()) == ['c3']
    assert ca.prune(tmp_path / 'nothing', 3, 100) == []


def test_g_prune_keeps_the_weight(tmp_path):
    for i in range(4):
        _call(tmp_path, 'c%d' % i, 600, 1000 + i)       # 4 x 600 kB
    assert ca.prune(tmp_path, keep_calls=20, max_mb=1) == ['c0', 'c1', 'c2']


def test_h_fix_header_repairs_a_cut_file(tmp_path):
    path = tmp_path / 'x.wav'
    path.write_bytes(ca._header(0) + PKT + b'\x09')      # a call that died: size 0 and a half sample
    assert ca.fix_header(path) == len(PKT)
    with wave.open(str(path), 'rb') as w:
        assert w.getnframes() == 480
    (tmp_path / 'y.wav').write_bytes(b'not a wav at all' * 10)
    assert ca.fix_header(tmp_path / 'y.wav') == -1
    assert ca.fix_header(tmp_path / 'missing.wav') == -1


def test_i_timeline_has_open_marks_and_close(tmp_path):
    rec = _rec(tmp_path, cap_mb=5)
    rec.write('mic', PKT, t=0.0)
    rec.mark('cue', n=1)
    rec.close()
    events = _lines(tmp_path / 'c1')
    assert [x['ev'] for x in events] == ['open', 'channel', 'cue', 'close']
    assert events[0]['rate'] == 24000 and events[2]['n'] == 1 and events[3]['bytes'] == len(PKT)
    assert all(isinstance(x['t'], (int, float)) for x in events)


def test_nothing_written_after_close(tmp_path):
    rec = _rec(tmp_path)
    rec.close()
    rec.write('mic', PKT, t=0.0)
    assert not (tmp_path / 'c1' / 'mic.wav').exists()


def test_the_drift_rows_are_in_the_timer_table():
    assert [k for k in tp.unregistered() + tp.stale() if k.startswith('call_audio.')] == []
    assert 'call_audio.DRIFT_MS' in tp.TIMERS and tp.TIMERS['call_audio.DRIFT_MS'] == 'ms'


def test_microbench_median_per_packet(tmp_path, capsys):
    rec = _rec(tmp_path, cap_mb=500)
    costs = []
    for i in range(1500):
        t0 = time.perf_counter()
        rec.write('mic', PKT, t=i * 0.02)
        costs.append((time.perf_counter() - t0) * 1000.0)
    rec.close()
    med = statistics.median(costs)
    with capsys.disabled():
        print('\nU07-S2 microbench: median %.4f ms per packet, p95 %.4f ms, n=%d' % (med, sorted(costs)[int(len(costs) * 0.95)], len(costs)))
    assert med < 0.2
