# factory-backlog-id: U108.s2
from pathlib import Path
from echo_sync.call_audio import CallAudio

def test_call_audio_close_quota_exhausted(tmp_path):
    # We need to mock or ensure the CallAudio instance is created without starting a real thread 
    # if possible, but the instruction says to call the real code.
    # The defect is that audio._thread is None when quota_exhausted, causing AttributeError on .join().
    # We use a minimal setup.
    audio = CallAudio(tmp_path, 'call_1', cap_mb=1)
    
    # Manually trigger the state that causes the bug
    audio._state = 'quota_exhausted'
    audio._thread = None
    
    # This should call close() and return the summary without crashing on audio._thread.join()
    summary = audio.close()
    
    assert summary['state'] == 'quota_exhausted'
