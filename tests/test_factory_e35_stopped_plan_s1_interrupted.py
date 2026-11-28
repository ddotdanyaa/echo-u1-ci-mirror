# factory-backlog-id: E35-stopped-plan.s1
import echo_sync.engine as engine

def test_close_entry_resets_state():
    state = {
        'history': [{
            'question': 'test?',
            'chunks': ['part1', 'part2'],
            'spoken': 0,
            'status': 'active'
        }],
        'entry': 0,
        'active': True,
        'current_index': 0,
    }
    
    # _close_entry calls _current_entry which uses state['entry']
    # and _sync_entry which uses _current_entry.
    # We want to see if _close_entry clears 'active' and 'current_index'
    # when the entry is interrupted.
    
    engine._close_entry(state)
    
    assert state['active'] is False, "state['active'] should be False after closing entry"
    assert state['current_index'] is None, "state['current_index'] should be None after closing entry"
