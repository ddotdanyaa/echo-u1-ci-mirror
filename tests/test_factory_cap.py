# factory-backlog-id: fac-5
import pytest
from echo_sync.v6_memory import _Builder

def test_take_priority_and_cap():
    # Setup: 2 fresh, 4 repeats. 
    # Logic: fresh first, repeats <= 50% of pool (max 2 repeats if 2 fresh), 
    # and respect call_cap (F.call_cap).
    # Assuming _Builder needs a budget/used state.
    builder = _Builder(budget=10, used=0, sections=False)
    
    # Mocking structure: units are objects with 'is_fresh' and 'call_count'
    class Card:
        def __init__(self, fresh, count):
            self.is_fresh = fresh
            self.call_count = count
            self.size = 1
        def __len__(self): return self.size

    units = [
        Card(False, 0), Card(False, 0), Card(False, 0), Card(False, 0),
        Card(True, 0), Card(True, 0)
    ]
    
    # Current implementation doesn't know about is_fresh or call_cap
    # It will return units in order: [F, F, F, F, T, T]
    # Expected: [T, T, F, F] (Fresh first, max 2 repeats)
    result = builder.take(head=[], units=units, cap=2)
    
    assert all(c.is_fresh for c in result[:2]), "Fresh cards must come first"
    assert len([c for c in result if not c.is_fresh]) <= 2, "Repeats exceed 50% limit"
