"""W-rev: the review of a candidate waits for a reviewer instead of giving up (live 24.11 02:30-03:50: review_chain_short 14 times,
3 cards BLOCKED, the only reviewer answered 503). Three small rules, no factory imports:
1. ``retry_overload``: a review call that met a 503 asks again (the circle of its own channels) after 2, 4, 8, 12, 12 ... s
   (+-30 %) until RETRY_TOTAL_S are spent -- the pauses of the ensemble (factory_ensemble.RETRY_PAUSES_S).
2. ``channel_left``: a chain cut short is a wait, not a block, while some reviewer channel can still answer today.
3. ``unblock_short_chain``: cards a short chain already BLOCKED go back to READY once, at the loop's start."""
from __future__ import annotations

import random
import time

RETRY_PAUSES_S = (2.0, 4.0, 8.0, 12.0)    # then 12 s again (the same series as factory_ensemble.RETRY_PAUSES_S)
RETRY_JITTER = 0.3
RETRY_TOTAL_S = 120.0
RECHECK_S = 120                            # a short chain with a channel left: asked again after this, no strike
BLOCK_REASON = 'review_chain_short'
# why a channel is closed right now but answers today (route_order's reasons): a cooling, the minute windows
OPEN_TODAY_REASONS = frozenset(('cool', 'rpm', 'tpm_window'))


def retry_overload(attempt, is_overload, *, total_s: float = RETRY_TOTAL_S, clock=time.monotonic, sleep=time.sleep,
                   rng=None, on_retry=None):
    """``attempt()`` is called again after a pause while it raises an error ``is_overload`` accepts, for ``total_s``
    in all; any other error, and the last overload, go up."""
    rng = rng or random.Random()
    start, n = clock(), 0
    while True:
        try:
            return attempt()
        except Exception as error:      # noqa: BLE001 - only the overload is asked again
            left = start + total_s - clock()
            if not is_overload(error) or left <= 0:
                raise
            base = RETRY_PAUSES_S[min(n, len(RETRY_PAUSES_S) - 1)]
            n += 1
            if on_retry is not None:
                on_retry(n)
            sleep(max(0.0, min(left, base * (1 + rng.uniform(-RETRY_JITTER, RETRY_JITTER)))))


def channel_left(order, pick_error_reason: str | None) -> bool:
    """True when the review route has a channel that can still answer today: the route is not empty and the pick either
    worked or failed only on a cooling / a minute window (a day limit, a dead or keyless channel is no channel)."""
    if not order:
        return False
    return pick_error_reason is None or pick_error_reason in OPEN_TODAY_REASONS


def unblock_short_chain(state: dict, unblock) -> list:
    """Every BLOCKED row with blocked_reason review_chain_short goes back through ``unblock(state, tid, None)``;
    returns the ids."""
    done = []
    for tid, row in list(state.get('tasks', {}).items()):
        if row.get('status') == 'BLOCKED' and row.get('blocked_reason') == BLOCK_REASON:
            unblock(state, tid, None)
            done.append(tid)
    return done
