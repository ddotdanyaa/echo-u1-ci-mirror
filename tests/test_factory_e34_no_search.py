# factory-backlog-id: E34
import pytest
from echo_sync.native_media_socket import context_frames

def test_no_search_does_not_speak():
    # If no_search is True, it should not be in the 'speakable' channel if we want it to be "quiet"
    # according to the requirement "Ответ облака не звучит без job".
    # Currently, the code puts it in 'speakable'.
    action = {
        'epoch': 123,
        'question': 'Who is the president?',
        'no_search': True,
        'why': 'personal'
    }
    frames = context_frames(action)
    
    # Check if any frame is in the 'speakable' channel
    speakable_frames = [f for f in frames if f.get('channel') == 'speakable']
    
    # The requirement implies it shouldn't be 'speakable' if it's a refusal/no_search
    # Let's see what it actually returns.
    assert len(speakable_frames) == 0, f"Expected no speakable frames for no_search, but got {speakable_frames}"
