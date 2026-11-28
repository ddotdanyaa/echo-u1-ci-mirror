"""w9-hold-sweep: the measuring of ``tools/replay/hold_sweep`` on real ControlledMedia: it must tell a window that cuts a speaker in a pause (D=0) from one that waits it out (D=2.5)."""
import pytest

from tools.replay import hold_sweep as H


def _rows(release, tail, seeds=range(14)):
    return [H.one((s, 'x', release, tail, 40.0)) for s in seeds]


def test_measure_counts_on_a_fake_outcome():
    class U:
        def __init__(self, kind, onset, offset):
            self.kind, self.onset, self.offset = kind, onset, offset

    class Out:
        crash = None
        jobs = [{'at': 3.5}]
        cues = [(5.0, 'a', 1, 0, (), False, False, 1)]
        said = []
    a, b = U('question', 1.0, 3.0), U('question', 4.0, 6.0)
    Out.said = [a, b]
    m = H.measure(Out, [(a, b)], 40.0)
    assert (m['splits'], m['false'], m['prepared'], m['asked'], m['missed']) == (1, 1, 1, 1, 1)
    assert m['delays'] == [] or all(d >= 0 for d in m['delays'])


def test_a_short_window_cuts_the_speaker_more_than_a_long_one():
    short, long = _rows(0.0, 0.0), _rows(2.5, 2.5)
    assert sum(r['splits'] for r in short) >= 10, 'the stand split nothing: the test measures nothing'
    assert sum(r['false'] for r in short) > sum(r['false'] for r in long)
    assert not any(r['crash'] for r in short + long)


def test_the_same_seed_gives_the_same_row():
    assert H.one((3, 'x', 0.9, 2.5, 40.0)) == H.one((3, 'x', 0.9, 2.5, 40.0))


def test_table_has_every_config():
    rows = [H.one((1, name, r, t, 25.0)) for name, r, t in H.CONFIGS[:2]]
    assert [r['config'] for r in H.table(rows)] == [H.CONFIGS[0][0], H.CONFIGS[1][0]]


def test_one_leaves_the_controller_and_the_log_as_it_found_them():
    """W14 item 3: ``one`` set ``EAR_RELEASE_SILENCE_SECONDS``/``EAR_TAIL_SILENCE_SECONDS`` of ``controlled_media`` and ``logging.disable`` for the whole
    process: the four ``test_q1_*`` that ran after it on the same xdist worker heard the answer twice, and caplog tests saw no lines."""
    import logging
    from echo_sync import controlled_media as cm
    before = (cm.EAR_RELEASE_SILENCE_SECONDS, cm.EAR_TAIL_SILENCE_SECONDS, logging.root.manager.disable)
    H.one((3, 'x', before[0] + 0.7, before[1] + 0.9, 25.0))
    assert (cm.EAR_RELEASE_SILENCE_SECONDS, cm.EAR_TAIL_SILENCE_SECONDS, logging.root.manager.disable) == before
