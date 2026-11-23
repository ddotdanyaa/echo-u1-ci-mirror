# factory-backlog-id: H31-02
import base64
import json
from echo_sync.call_trace import CallTrace

class FakeClock:
    def __init__(self):
        self.t = 100.0
    def __call__(self):
        return self.t
    def advance(self, dt):
        self.t += dt

def test_ready_verdict_short_calls(tmp_path):
    # 1. 'shortnone' call
    clock1 = FakeClock()
    trace1 = CallTrace(tmp_path, 'shortnone', facts=True, clock=clock1)
    assert trace1.open() is True
    clock1.advance(0.5)
    trace1.close()

    # 2. 'shortone' call
    clock2 = FakeClock()
    trace2 = CallTrace(tmp_path, 'shortone', facts=True, clock=clock2)
    assert trace2.open() is True
    audio_bytes = base64.b64encode(b'\x00' * 3200).decode('utf-8')
    trace2.mic({'type': 'input_audio_buffer.append', 'audio': audio_bytes})
    clock2.advance(0.5)
    trace2.close()

    # Read records for shortnone
    files1 = list(tmp_path.glob('*-shortnone.jsonl'))
    assert len(files1) == 1
    records1 = []
    with open(files1[0], 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                records1.append(json.loads(line))

    verdicts1 = [r for r in records1 if r.get('ev') == 'ready_verdict']
    closes1 = [r for r in records1 if r.get('ev') == 'call_close']
    assert len(verdicts1) == 1
    assert len(closes1) == 1
    # verdict must appear before call_close
    v_idx1 = records1.index(verdicts1[0])
    c_idx1 = records1.index(closes1[0])
    assert v_idx1 < c_idx1

    v1 = verdicts1[0]
    assert v1.get('reason') == 'no_packets_at_all_since_the_call_opened'
    assert v1.get('mic_kept') is False
    assert v1.get('packets') == 0

    # Read records for shortone
    files2 = list(tmp_path.glob('*-shortone.jsonl'))
    assert len(files2) == 1
    records2 = []
    with open(files2[0], 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                records2.append(json.loads(line))

    verdicts2 = [r for r in records2 if r.get('ev') == 'ready_verdict']
    closes2 = [r for r in records2 if r.get('ev') == 'call_close']
    assert len(verdicts2) == 1
    assert len(closes2) == 1
    v_idx2 = records2.index(verdicts2[0])
    c_idx2 = records2.index(closes2[0])
    assert v_idx2 < c_idx2

    v2 = verdicts2[0]
    assert v2.get('packets') == 1
    assert v2.get('mic_kept') is None
    assert v2.get('reason') == 'call_closed_before_any_cue_finished'
