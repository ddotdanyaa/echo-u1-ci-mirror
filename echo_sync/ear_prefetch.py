"""Q1 / B9: the early lookup is fed from the local ear's text as well as the cloud's partial.

``EarlyLookup`` (native_prefetch.py) prepares the existing public lookup of a question while it is still being said, and nothing else: no cue, no state of the call, no new check of privacy. Fed by the
cloud's partial alone it starts late: the cloud's text of an utterance is complete about a second after the end of speech on the phone (1.06 s, against the ear's 0.14 s) and it must then stand still for
``stable_seconds``. The ear's text of an utterance is whole at once; ``EarFeed`` hands it to the early lookup as a candidate for the cloud's open turn, so that the search of a lookup question starts at the
end of speech.

Every condition of the cloud's partial holds for the ear's text, because the controller is asked about it: ``ControlledMedia.prefetch_candidate(text)`` (a question that needs a lookup, ≥ 3 words, the
privacy gate ``public_lookup_allowed``, not an elliptical follow-up, not an utterance the cloud's turn has already taken, not what the base or ``quick_math`` answers). On top of that the text must not stop where
an utterance goes on (``open_tail``), it must have stood EAR_FEED_SETTLE_SECONDS with no speech after it, a piece the gate refuses keeps the pieces around it from the lookup too (the gate reads the utterance, and
the ear has it in pieces), and it is bound to the cloud's open turn only when that turn does not contradict it. The final adopts what was prepared only for the same turn and the same question (``question_key``); any other words and the
final asks its own (``EarlyLookup.resolve``). Whether the early lookup runs at all is one rule of the call's modes (``ear_lookup``, read by the wire from the controller): with it off ``EarFeed`` does nothing and the
cloud's partial goes to ``EarlyLookup.observe`` as it always did.

Nothing here raises into the call: a fault is logged by type and the piece is dropped.
"""
from __future__ import annotations

import logging

from .classifier import open_tail, strip_fillers
from .fast_text import same_start
from .native_prefetch import question_key

logger = logging.getLogger('echo-sync')

# How long an utterance of the ear waits for the cloud's turn to be announced (the controller's EAR_FIRST_BIND_SECONDS: the cloud's start of speech came up to 3 s behind the ear's on the phone).
EAR_FEED_WAIT_SECONDS = 4.0
# A question cut by a breath: the piece the ear heard before is read with this one when it came this recently.
EAR_FEED_JOIN_SECONDS = 1.2
# A question is often cut by a breath, and its first half is often a question the policy wants searched by itself («какая сейчас ключевая ставка» | «банка казахстана»): a public request for nothing, and the turn's
# one preparation gone. The ear's text is prepared when the quiet after it has lasted this long and speech has not begun again (the reason and the length of the controller's EAR_COMMAND_SETTLE_SECONDS): at about
# 0.55 s after the end of speech, a second before the cloud's partial would start it.
EAR_FEED_SETTLE_SECONDS = 0.4


class EarFeed:
    def __init__(self, controller, early, *, clock, settle=EAR_FEED_SETTLE_SECONDS):
        self.controller, self.early, self.clock, self.settle = controller, early, clock, settle
        self.pending = None           # {'pieces': [text, ...], 'at': when the last came, 'end': when its speech ended}: what the ear heard and no open turn has taken yet
        self.private_until = 0.0      # the ear has heard a personal piece: until then what it hears is the rest of that utterance
        self.held = None              # (turn id, question) the ear prepared and nothing has contradicted

    def _strip(self, text):
        return strip_fillers(text, getattr(self.controller, 'settings', None))

    def heard(self, record):
        """One utterance of the ear (a ``ShadowEar.poll`` record): its text waits for the cloud's open turn."""
        try:
            if not self.early.enabled:
                return
            text = record.get('text') if isinstance(record, dict) else None
            if not isinstance(text, str) or not text.strip():
                return
            now, before = self.clock(), self.pending
            if not self.controller.public_lookup_allowed(text, True):      # E88: the gate of the public search
                self.pending, self.private_until = None, now + EAR_FEED_WAIT_SECONDS
                return
            if now < self.private_until:
                return
            pieces = before['pieces'][-1:] if before and self._joins(before, record, now) else []
            self.pending = {'pieces': pieces + [text.strip()], 'at': now, 'end': record.get('offset')}
        except Exception as error:       # noqa: BLE001 - a preparation is an addition and never fails a call
            self.pending = None
            logger.warning('echo-sync ear prefetch failed reason=%s', type(error).__name__)

    def step(self):
        """On the transport's tick: bind what the ear heard to the cloud's open turn, once there is one it does not contradict, and let the early lookup prepare it."""
        try:
            pending = self.pending
            if pending is None:
                return
            if not self.early.enabled or self.clock() - pending['at'] > EAR_FEED_WAIT_SECONDS:
                self.pending = None
                return
            if self.clock() - pending['at'] < self.settle or self._goes_on(pending):
                return
            user = self.controller.ledger.latest_user()
            if not user or not user.get('valid') or user.get('final'):
                return                # no open turn of the cloud yet: nothing is judged until there is one (the judgement is the classifier's, a few ms, and is made once)
            pieces, judged = pending['pieces'], pending.setdefault('judged', {})
            for text in ([' '.join(pieces)] if len(pieces) > 1 else []) + [pieces[-1]]:
                if open_tail(text):
                    continue
                key = (text, user.get('id'))
                if key not in judged:
                    judged[key] = self.controller.prefetch_candidate(text) or None
                candidate = judged[key]
                if candidate and self._bound(candidate[0], text):
                    self.early.observe_ear(*candidate, now=self.clock())
                    self.held, self.pending = tuple(candidate), None
                    return
        except Exception as error:       # noqa: BLE001
            self.pending = None
            logger.warning('echo-sync ear prefetch failed reason=%s', type(error).__name__)

    @staticmethod
    def _joins(before, record, now):
        """Does this piece go on from the one before? The breath between them says so, not when their texts came: a long second piece comes late."""
        onset, end = record.get('onset'), before.get('end')
        return (now - before['at'] if onset is None or end is None else onset - end) <= EAR_FEED_JOIN_SECONDS

    def _goes_on(self, pending):
        """Has the ear heard speech begin again since the end of this text? Its next piece is read with it (``heard``). The acting ear tells, a shadow ear has only the wait."""
        onset, end = getattr(self.controller, 'ear_onset_at', None), pending.get('end')
        return onset is not None and end is not None and onset > end

    def _bound(self, turn_id, text):
        """Is the cloud's open turn the one ``text`` was said in: it has no word yet (the ear came first), or what it has goes the way the ear heard it (H4's ``same_start``, its last word still open)."""
        user = self.controller.ledger.latest_user()
        if not user or user.get('id') != turn_id:
            return False
        cloud = user.get('text') or ''
        return not cloud.strip() or same_start(text, cloud, strip=self._strip, open_end=True)

    def partial(self, candidate):
        """The cloud's partial offers ``candidate`` (a turn id and a question, or ``None``): the early lookup is told as it always was, unless the ear has prepared this turn and the partial is no more than
        nothing or a head of the same question; other words from the cloud replace it, and so does another turn."""
        try:
            held = self.held
            if held is not None:
                if candidate is None or (candidate[0] == held[0] and (question_key(candidate[1]) == question_key(held[1])
                                                                     or same_start(held[1], candidate[1], strip=self._strip, open_end=True))):
                    return
                self.held = None
        except Exception as error:       # noqa: BLE001
            self.held = None
            logger.warning('echo-sync ear prefetch failed reason=%s', type(error).__name__)
        self.early.observe(*(candidate or (None, None)), now=self.clock())
