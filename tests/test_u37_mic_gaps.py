"""U37: the microphone coverage of a call broken down by the CAUSE of each gap (cue playing / drop of 10 s or more / switch), as data in the
duplex record of the call trace - the input for the owner's decision on the client (Conduit toggle, own client, other). Synthetic timelines."""
import pytest

from tests.test_ux_duplex import Call, duplex_record


def gaps(call):
    return duplex_record(call)['mic_gaps']


def test_a_half_duplex_call_puts_the_whole_hole_on_the_cue(tmp_path):
    call = Call(tmp_path)
    for _ in range(3):
        call.listen(4)
        call.cue(2.0)
        call.silence(0.35)
    call.close()
    d = duplex_record(call)
    by = d['mic_gap_s']
    assert by['cue'] == pytest.approx(7.05, abs=0.35) and by['drop'] == 0 and by['switch'] == 0
    assert d['mic_coverage'] == pytest.approx(12 / 19.05, abs=0.05)
    assert {g['cause'] for g in d['mic_gaps']} == {'cue'} and len(d['mic_gaps']) == 3


def test_a_silence_of_twelve_seconds_outside_a_cue_is_a_drop(tmp_path):
    call = Call(tmp_path)
    call.listen(3)
    call.silence(12.0)
    call.listen(3)
    call.close()
    d = duplex_record(call)
    assert d['mic_gap_s']['drop'] == pytest.approx(12.0, abs=0.3) and d['mic_gap_s']['cue'] == 0
    assert [g['cause'] for g in d['mic_gaps']] == ['drop']


def test_a_short_hole_outside_a_cue_is_a_switch(tmp_path):
    call = Call(tmp_path)
    call.listen(3)
    call.silence(2.0)
    call.listen(3)
    call.close()
    d = duplex_record(call)
    assert d['mic_gap_s']['switch'] == pytest.approx(2.0, abs=0.3) and d['mic_gap_s']['drop'] == 0
    assert [g['cause'] for g in d['mic_gaps']] == ['switch']


def test_a_full_duplex_call_has_no_holes(tmp_path):
    call = Call(tmp_path)
    call.listen(4)
    call.cue(2.0, mic_open=True)
    call.listen(4)
    call.close()
    d = duplex_record(call)
    assert d['mic_gaps'] == [] and d['mic_coverage'] == pytest.approx(1.0, abs=0.03)
    assert sum(d['mic_gap_s'].values()) < 0.3


def test_jitter_below_a_quarter_second_is_not_a_hole(tmp_path):
    call = Call(tmp_path)
    for _ in range(20):
        call.listen(1)
        call.silence(0.15)
    call.close()
    assert gaps(call) == []


def test_the_breakdown_adds_up_to_the_missing_time(tmp_path):
    call = Call(tmp_path)
    call.listen(3)
    call.silence(1.5)
    call.listen(2)
    call.cue(2.0)
    call.silence(11.0)
    call.listen(2)
    call.close()
    d = duplex_record(call)
    total = sum(d['mic_gap_s'].values())
    assert total == pytest.approx(d['ready_s'] * (1 - d['mic_coverage']), abs=0.1)
    assert d['mic_gap_s']['cue'] > 1.5 and d['mic_gap_s']['switch'] >= 1.0
