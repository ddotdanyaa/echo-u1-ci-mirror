# factory-backlog-id: E881.s2
from echo_sync.engine import conversation_map

def test_conversation_map_preserves_options():
    options = ['A: Paris', 'B: London', 'C: Berlin', 'D: Rome']
    state = {'history': [
        {
            'question': 'What is the capital of France?',
            'options': options,
            'status': 'complete',
            'at': 100.0,
        }
    ]}
    rows = conversation_map(state, now=100.5)
    assert rows[0].get('options') == options
