# factory-backlog-id: U62.s1
import pytest
import json
from echo_sync.engine import EchoEngine

def test_engine_reports_stalled_when_fuse_active_with_non_empty_queue(tmp_path):
    e = EchoEngine(tmp_path / 'engine.sqlite3', lambda *a, **kw: 'ответ')
    # Setup a state with chunks (non-empty queue) and an active quarantine/fuse condition
    with e._db() as db:
        state = {
            'session_id': 's1',
            'revision': 1,
            'chunks': ['часть 1', 'часть 2'],
            'chunk_index': 0,
            'completed': False,
            'paused': False,
            'quarantine': True,
        }
        db.execute('INSERT OR REPLACE INTO sessions (session_id, state) VALUES (?, ?)', ('s1', json.dumps(state)))
    
    # The requirement is to verify the engine reports 'stalled'. 
    # Since status() doesn't exist, this test proves the missing functionality by asserting the expected state key.
    current_state = e.state('s1')
    assert current_state.get('quarantine') is True
    assert len(current_state.get('chunks', [])) > 0
    assert e.status('s1') == 'stalled'
