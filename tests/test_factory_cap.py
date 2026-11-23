# factory-backlog-id: fac-5
import pytest
from echo_sync.v6_memory import _Builder

def test_take_prioritizes_fresh_and_respects_repeat_limit():
    # Setup: 4 fresh cards, 4 repeat cards.
    # Budget allows all 8, but repeat limit (50% of pool when fresh pending) 
    # should restrict repeats to 4 total (or fewer if fresh are present).
    # Actually, the rule is: repeats <= 50% of the pool if fresh are pending.
    # If we have 4 fresh, we can have at most 4 repeats.
    
    builder = _Builder(budget=100)
    # Mocking structure: units are strings or objects with len()
    fresh = ["f1", "f2", "f3", "f4"]
    repeats = ["r1", "r2", "r3", "r4"]
    units = fresh + repeats
    
    # This should return fresh first, then limited repeats
    taken = builder.take(head=[], units=units)
    
    # Check that fresh are at the start
    assert taken[:4] == fresh
    # Check that repeats are limited (e.g., if 4 fresh, max 4 repeats allowed)
    # If the logic is "repeats <= 50% of pool", and pool is 8, max repeats is 4.
    # If the logic is "repeats <= 50% of fresh", that would be 2.
    # The requirement says "repeats do not exceed 50% of the pool if fresh cards are pending"
    assert len(taken) <= 6  # 4 fresh + 2 repeats (50% of 4 fresh)
