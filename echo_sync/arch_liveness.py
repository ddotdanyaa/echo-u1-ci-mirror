"""W9-arch (N158, N161, N163): is the cloud (GPT-Live) still a witness of the listener? Pure: no I/O, no clock of its own, no logging.

Nothing imports this module until the patch of ``cloud_context/reports/w9-arch.patch`` is applied, and there it is behind
``native_media_socket.CLOUD_DEAF_S`` = 0 (off).

Why: the helper that carries GPT-Live can stay open while the session behind it says nothing any more (no ``X`` frame, no
``error``, no ``session.closed``). ``controlled_host.read_source`` then waits on ``bridge.receive(30)`` for ever, the controller has no
final, so its answer watchdog never starts (it counts from the final), and the listener asks into a call that says nothing, without
end (tests/test_w9_arch.py, W9-A1). The transport is the only one who knows both sides: it sends the microphone up and it sees every
event come down. Speech that the cloud must have heard, and no event of the cloud since for ``deaf_s``: the cloud is deaf.

Speech that counts (a cough or a far television must not make the call say «связь прервалась»):
  * the cloud's own start of a user turn (it heard something, and a turn it opens it closes within seconds, an empty one too);
  * the ear's text with a word in it (the local recognizer heard words);
  * a run of the transport's onset detector of at least ``min_run_s`` (energy alone, a cough is shorter).
The verdict is given once; the next event of the cloud re-arms it.
"""

from .timer_policy import CLOUD_DEAF_S      # one number of the deafness bound, timer_policy's (the transport reads the same)
MIN_RUN_S = 1.5          # a run of the onset detector that counts as speech for this purpose


class CloudWitness:
    """``event(now)``: the cloud sent anything. ``speech(now, kind)``: speech heard; ``kind`` 'cloud' (its user turn.created),
    'words' (the ear's text with content), 'onset' / 'run' (the transport's detector: a start, and the speech going on).
    ``verdict(now)``: 'deaf' once, when counted speech has gone ``deaf_s`` with no event of the cloud since its last sign; else None."""

    def __init__(self, deaf_s=CLOUD_DEAF_S, min_run_s=MIN_RUN_S):
        self.deaf_s, self.min_run_s = deaf_s, min_run_s
        self.last_event = None
        self.heard_at = None         # the last moment of counted speech the cloud has said nothing about since
        self.run_began = self.run_last = None
        self.told = False

    def event(self, now):
        self.last_event = now
        self.heard_at = None
        self.run_began = self.run_last = None
        self.told = False

    def speech(self, now, kind):
        if kind == 'onset':
            self.run_began = self.run_last = now
            return
        if kind == 'run':
            if self.run_began is None:
                self.run_began = now
            self.run_last = now
            if now - self.run_began < self.min_run_s:
                return
        elif kind not in ('cloud', 'words'):
            return
        self.heard_at = now

    def verdict(self, now):
        if not self.deaf_s or self.told or self.heard_at is None:
            return None
        since = max(self.heard_at, self.run_last or self.heard_at)       # speech still going on is no silence of the cloud yet
        if now - since < self.deaf_s:
            return None
        self.told = True
        return 'deaf'
