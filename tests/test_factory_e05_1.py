# factory-backlog-id: E05.1
from tools import call_report


def _rows():
    return [
        {'t': 1000, 'ev': 'fast_refused', 'job': 1, 'rule': 'old'},
        {'t': 1100, 'ev': 'fast_refused', 'job': 1, 'rule': 'words'},
        {'t': 1200, 'ev': 'fast_refused', 'job': 1, 'rule': 'old'},
        # fast_text writes the refusals beyond REFUSED_NOTES_PER_JOB as one summary row
        {'t': 2000, 'ev': 'fast_refused_sum', 'job': 1, 'rules': {'old': 5, 'alike': 4}, 'last_t': 900, 'last_asked': 'x'},
        {'t': 2001, 'ev': 'fast_job', 'job': 1, 'on': 'ear', 'after_ear_ms': 10, 'ttft_ms': 300, 'chars': 5, 'outcome': 'done', 'reason': '-', 'released': 0, 'adopted': 0},
    ]


def test_refusals_over_the_note_cap_are_counted_by_rule():
    call = call_report._call(_rows(), 'c1')
    summary = call_report.jobs_summary([call])
    assert summary['refused_by_rule'].get('old') == 7
    assert summary['refused_by_rule'].get('alike') == 4
    assert summary['refused_by_rule'].get('words') == 1
