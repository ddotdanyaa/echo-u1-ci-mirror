# factory-backlog-id: rel-base-fn_2_04-one-portion-timer
from echo_sync.timer_policy import pen_wait, DICTATION_EXTRA_SECONDS, DICTATION_MAX_SECONDS, DICTATION_MIN_SECONDS

def test_pen_wait_zero_words_clamped_by_max():
    per_word = 0.2
    # If base is greater than MAX, the result should still be clamped to MAX.
    # Current code: max(base, min(MAX, max(MIN, EXTRA))) -> returns base if base > MAX.
    # Desired: clamp(max(base, EXTRA)) -> returns MAX if base > MAX.
    base = DICTATION_MAX_SECONDS + 1.0
    
    # The requirement says: "The result is the clamped value of DICTATION_EXTRA_SECONDS and base."
    # This implies: clamp(max(base, DICTATION_EXTRA_SECONDS))
    expected = min(DICTATION_MAX_SECONDS, max(DICTATION_MIN_SECONDS, max(base, DICTATION_EXTRA_SECONDS)))
    
    # The current implementation returns: max(base, min(MAX, max(MIN, EXTRA)))
    # If base = MAX + 1, current returns MAX + 1.
    # Expected returns MAX.
    assert pen_wait(per_word, 0, base) == expected
