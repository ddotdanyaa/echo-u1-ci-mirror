"""w8-donors N73: the stable part of the ear's text by LocalAgreement-n (Macháček et al. 2023, whisper_streaming; the idea only - the
PyPI port whisper-streaming 0.1.0 is built on word times and faster-whisper, and its n-gram skip pops the wrong indices, so nothing is copied).

The ear (ear_shadow.EarFeed) takes the recognizer's text so far on every pause of ``ear_early_ms`` inside an utterance (a *peek*). A word is
stable when the last ``n`` peeks agree on it AND on the word after it: the last word two peeks share may still grow («билет» -> «билета»).
On top of that the stable text never ends in a number word or «не»/«ни» (what ru_alignment protects): «двадцать» may become «двадцать
пять», «не» waits for what it negates. What is committed is never taken back; a later disagreement only stops it growing. Flag
``stable_text`` (off): nothing reads it yet; the integration patch is in cloud_context/reports/w8-donors.md."""
from collections import deque

from .textutil import norm_words


def _protected(word):
    from .ear_sherpa import _protected as protected      # noqa: PLC0415  (number words in any case, «не», «ни»; no sherpa import)
    return protected(word)


class LocalAgreement:
    def __init__(self, n=2):
        self.n, self.peeks, self.words = max(2, int(n)), deque(maxlen=max(2, int(n))), []

    @property
    def committed(self):
        return ' '.join(self.words)

    def reset(self):
        self.peeks.clear(); self.words = []

    def push(self, text):
        """One more peek of the same utterance; the stable text so far."""
        self.peeks.append(norm_words(text))
        if len(self.peeks) < self.n:
            return self.committed
        shared = 0
        while all(len(p) > shared for p in self.peeks) and len({p[shared] for p in self.peeks}) == 1:
            shared += 1
        closed = shared if all(len(p) > shared for p in self.peeks) else shared - 1     # the last shared word must be followed in every peek
        stable = self.peeks[-1][:max(closed, 0)]
        while stable and _protected(stable[-1]):
            stable.pop()
        if len(stable) > len(self.words) and stable[:len(self.words)] == self.words:
            self.words = stable
        return self.committed
