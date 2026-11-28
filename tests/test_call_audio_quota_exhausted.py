# factory-backlog-id: U108.s2
import pytest
from echo_sync.call_audio import CallAudio

def test_call_audio_close_quota_exhausted(tmp_path):
    audio = CallAudio(tmp_path, 'call_1', cap_mb=1)
    audio._state = 'quota_exhausted'
    audio._thread = None
    try:
        summary = audio.close()
    except AttributeError as e:
        pytest.fail(f"CallAudio.close failed when quota_exhausted and thread is None: {e}")
    assert summary.get('state') == 'quota_exhausted'
