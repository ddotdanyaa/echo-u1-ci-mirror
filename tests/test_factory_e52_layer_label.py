# factory-backlog-id: E52
from types import SimpleNamespace

from tools.replay.stand import decisions


def test_decisions_rows_are_labelled_server_layer():
    utterance = SimpleNamespace(n=1, kind='say', text='привет', offset=2.0, ear_at=2.1, final_at=2.4, onset=0.5)
    cue = (2.7, 'ok', None, None, None, None, False)
    out = SimpleNamespace(cues=[cue], said=[utterance])

    rows = decisions(out)

    assert len(rows) == 1
    row = rows[0]
    assert row['first_cue'] == 'ok'
    assert row['first_cue_at'] == 2.7
    assert row['after_offset_s'] == 0.7
    assert row.get('layer') == 'серверный слой'
