# factory-backlog-id: E35-stopped-plan.s2
from echo_sync.engine import plan_entry

def test_plan_entry_superseded():
    history = [
        {'status': 'interrupted', 'chunks': ['a', 'b'], 'spoken': 1},  # Index 0: Interrupted plan
        {'status': 'complete', 'question': 'New question'}
    ]
    # Index 0 is superseded by index 1
    assert plan_entry(history, 0) is None
