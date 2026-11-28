# factory-backlog-id: E881.s1
from echo_sync.engine import conversation_map
import pytest

def test_quiz_context_persistence():
    # Mock state with 20 entries. 16 are quiz entries.
    # Assuming 'quiz_id' is the marker for quiz session
    history = []
    for i in range(4):
        history.append({'status': 'complete', 'at': 100, 'question': f'Gen {i}', 'text': 'ans'})
    for i in range(16):
        history.append({'status': 'complete', 'at': 100, 'question': f'Quiz {i}', 'text': 'ans', 'quiz_id': 'quiz_123'})
    
    state = {'history': history}
    # window_s is large enough to include all
    rows = conversation_map(state, now=100, limit=15, window_s=1000)
    
    # We expect all 16 quiz entries to be present
    quiz_rows = [r for r in rows if 'Quiz' in r['question']]
    assert len(quiz_rows) == 16
