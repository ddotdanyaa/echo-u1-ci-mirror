# factory-backlog-id: R6

from echo_sync.call_trace import DuplexMeter

def test_duplex_meter_ready_packet_first():
    meter = DuplexMeter(anchor=100.0)
    # Simulate a microphone packet arriving before the handshake marker
    # packet(101.0, 960) sets self.ready_at = 101.0 - 960 / 48000 = 100.98
    meter.packet(101.0, 960)

    expected_ready_at = 101.0 - 960 / 48000

    # First ready() call with a later timestamp
    first_result = meter.ready(101.5)
    # Second ready() call
    second_result = meter.ready(102.0)

    assert first_result is True
    assert second_result is False
    assert meter.ready_at == expected_ready_at
