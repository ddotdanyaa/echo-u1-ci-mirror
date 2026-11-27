"""U17-S6: the offline input replay. The harvest keeps the phone's microphone seconds (the ``mic`` key); ``input_replay`` feeds them to the InputMeter on the call's own time and
checks A3 (a repeat comes after half_listen sound; offline ``got_s >= need - 1.0``, the +-1 s of the seconds-wide rows), A2 and A4 marked open_replay by the U25-R1 contract."""
import pytest

from echo_sync.input_state import HALF_LISTEN_S
from tools.replay import input_replay as R

SEC_BYTES = 48000       # one second of 24 kHz 16-bit mono


def mic(sec, n=10, nbytes=SEC_BYTES):
    return {'t': (sec + 1) * 1000, 'ev': 'mic', 'sec': sec, 'n': n, 'bytes': nbytes, 'first_ms': sec * 1000 + 20, 'last_ms': sec * 1000 + 980}


def fixture_of(mics, cues):
    return {'mic': mics, 'cues': cues, 'profile': {}}


def test_packets_spread_the_bytes_of_a_second():
    got = list(R.packets([[1.0, 2.0, 4, 4000]]))
    assert [round(t, 3) for t, _ in got] == [1.0, 1.333, 1.667, 2.0] and sum(n for _, n in got) == 4000
    assert list(R.packets([[5.0, 5.0, 1, 960]])) == [(5.0, 960)]


def test_a_repeat_after_enough_sound_passes_and_after_too_little_fails():
    cues = [[1.0, 'Первая порция', 'completed'], [6.0, 'Первая порция', 'completed'], [12.0, 'Первая порция', 'completed']]
    mics = [[1.5, 2.5, 10, SEC_BYTES], [2.6, 3.6, 10, SEC_BYTES], [3.7, 4.7, 10, SEC_BYTES]]       # 3 s of sound before the first repeat, none before the second
    got = R.repeats(fixture_of(mics, cues))
    assert [r['t'] for r in got] == [6.0, 12.0]
    assert got[0]['got_s'] == pytest.approx(3.0, abs=0.05) and got[0]['ok'] is True
    assert got[1]['got_s'] == 0.0 and got[1]['ok'] is None and got[1]['why'] == 'no_mic', 'past the last mic second the rows know nothing: unknown, not failed'


def test_offline_need_is_the_live_need_minus_one_second():
    cues = [[0.0, 'Порция один', None], [10.0, 'порция один!', None]]
    below = fixture_of([[8.0, 8.5, 5, int(SEC_BYTES * 0.5)], [9.0, 9.5, 5, int(SEC_BYTES * 0.4)]], cues)       # 0.9 s received, mic rows until 9.5 s
    near = fixture_of([[8.0, 9.0, 10, SEC_BYTES], [9.0, 9.95, 10, int(SEC_BYTES * 0.5)]], cues)                   # 1.5 s received
    row_below, row_near = R.repeats(below)[0], R.repeats(near)[0]
    assert row_below['need'] == HALF_LISTEN_S and row_below['need_offline'] == HALF_LISTEN_S - R.PRECISION_S == 1.0
    assert row_below['ok'] is False and row_near['ok'] is True


def test_run_marks_a2_and_a4_open_after_the_first_changed_cue():
    cues = [[1.0, 'Первый ответ', None], [6.0, 'Первый ответ', None], [20.0, 'Второй ответ', None]]
    fx = fixture_of([[2.0, 5.0, 30, 3 * SEC_BYTES], [6.5, 19.5, 100, 13 * SEC_BYTES]], cues)
    closed = R.run(fx)
    assert closed['closed'] and closed['metrics_open'] == 0
    names = {m['name'] for m in closed['metrics']}
    assert {'A3_repeat', 'A4_state', 'A2_shows'} <= names
    moved = R.run(fx, replay_cues=[(1.0, 'Первый ответ', None), (6.0, 'Иной ответ', None), (20.0, 'Второй ответ', None)])
    assert not moved['closed'] and moved['divergence']['at'] == 6.0
    assert all(m['open_replay'] == (m['t'] >= 6.0) for m in moved['metrics'])


def test_the_report_counts_a3_over_a_fixture_with_mic_rows():
    """U17 A3 over fixtures with ``mic`` rows (the harvest key itself is P14's: tools/harvest must keep ``mic``; until then fixtures carry it by hand)."""
    cues = [[1.0, 'Первая порция', None], [6.0, 'Первая порция', None], [12.0, 'Первая порция', None], [30.0, 'Первая порция', None]]
    fx = fixture_of([[1.5, 2.5, 10, SEC_BYTES], [2.6, 3.6, 10, SEC_BYTES], [3.7, 4.7, 10, SEC_BYTES], [7.0, 8.0, 10, 1000], [10.0, 11.5, 3, 500]], cues)
    got = R.report(fx)
    assert got['repeats'] == 3 and got['a3_ok'] == 1 and got['a3_failed'] == 1 and got['a3_unknown'] == 1 and got['mic_seconds'] == 5
    run = R.run(fx)
    assert run['closed'] and all('open_replay' in m for m in run['metrics'])
