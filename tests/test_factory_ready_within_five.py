# factory-backlog-id: U03-03
from echo_sync.call_trace import DuplexMeter


def test_summary_reports_ready_within_five_seconds():
    meter = DuplexMeter(anchor=100.0)
    meter.packet(102.0, 960)

    summary = meter.summary(103.0)
    ready_entries = {k: v for k, v in summary.items() if k.startswith('ready_')}

    assert ready_entries == {'ready_s': 1.02, 'ready_after_s': 1.98, 'ready_fast': True}
