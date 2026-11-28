# factory-backlog-id: U62.s2
import random
from tools.replay.stand import ask

def test_stand_end_to_end():
    # The engine must produce exact strings for the given seed.
    # If the environment (iPhone vs Linux) differs in random generation or string handling,
    # this will fail.
    rng = random.Random(42)
    
    # First call with seed 42
    q1 = ask(rng)
    assert q1.family == 'money'
    assert q1.params == (40, 20)
    assert q1.text == 'Если у меня было 40 рублей и я потратил 20 рублей, сколько денег осталось?'
    
    # Second call
    q2 = ask(rng, last=q1)
    assert q2.family == 'money'
    assert q2.params == (20, 40)
    assert q2.text == 'Если у меня было 20 рублей и я потратил 40 рублей, сколько денег осталось?'
