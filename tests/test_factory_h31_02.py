# factory-backlog-id: H31-02
import time
from echo_sync.call_trace import CallTrace

class DummyMeter:
    def __init__(self, packets=5, cue_span_s=0.2, audio_in_cue_s=0.1):
        self.packets = packets
        self.cue_span_s = cue_span_s
        self.audio_in_cue_s = audio_in_cue_s
        self.anchor = 0.0

def test_ready_verdict_short_call_failure():
    """
    The current implementation returns None for short calls.
    We assert that for a short call (cue_span_s < 0.5), 
    the system should explicitly set mic_kept=False and a specific reason.
    """
    records = []
    def fake_record(kind, fields):
        records.append((kind, fields))

    trace = CallTrace(call_id="test_short", directory=None, clock=time.time)
    trace.meter = DummyMeter(packets=5, cue_span_s=0.2, audio_in_cue_s=0.0)
    trace.facts = ["some_fact"]
    trace._record = fake_record

    trace._ready_verdict()

    verdict_record = next(r for r in records if r[0] == "ready_verdict")
    # This assertion is expected to fail on current code because it returns 'cue_too_short_to_judge' with mic_kept=None
    assert verdict_record[1]["mic_kept"] is False
    assert verdict_record[1]["reason"] == "call_too_short_to_judge"
