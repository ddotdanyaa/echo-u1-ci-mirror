# factory-backlog-id: E35-stopped-plan.s1
from echo_sync.engine import _close_entry, _current_entry

def test_close_entry_resets_current():
    state = {
        'history': [{'status': 'active', 'chunks': ['a', 'b'], 'spoken': 1}],
        'current_index': 0,
        'active': True
    }
    _close_entry(state, status='interrupted')
    assert _current_entry(state) is None
    assert state.get('active') is False
    assert state.get('current_index') is None
