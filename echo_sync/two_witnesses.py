"""E86 (H8, WAVE6 item 11, WAVE10 item 4): sound without the cloud's final when two witnesses of the utterance agree: the local ear's text and the
STABLE piece of the cloud's open turn (``stable_text.LocalAgreement`` over its deltas: a word is the cloud's only once two deltas in a row keep it
and the word after it; a number or «не» at its end waits). The ear's numbers are wrong in 2-20 %, its «не» lost in 5-15 % (analysis/14_EAR_N2):
so every number, every «не»/«ни» and the roles around them (``fast_text._roles_agree``) the ear heard must already be in the stable piece and agree;
a question with neither may go on the ear and a piece that agrees with its head and holds a content word of it. A piece that goes another way cuts (the ear's question is not the
cloud's). Pure; the controller reads it behind ``two_witnesses`` (off)."""
from .fast_text import _atoms, _protected, _roles_agree, _words, same_start
from .stable_text import LocalAgreement, _protected as _protected_word
from .textutil import norm_words

SOUND, WAIT, CUT = 'sound', 'wait', 'cut'
MIN_PIECE_WORDS = 2              # less than this of the cloud is no witness of a question
CLOSING = '?!'                   # G32: a mark that ends a number (a point or a comma may be inside one: «2.5», «2,5»)
_negation = lambda word: word in ('не', 'ни')


def verdict(ear, piece, *, strip=None):
    """``SOUND``: the stable piece agrees with the ear on every number, «не» and role the ear heard (or there are none, and it agrees with its head);
    ``WAIT``: not enough of the cloud yet; ``CUT``: the piece goes another way."""
    try:
        if strip is not None:
            ear, piece = strip(ear), strip(piece)
        heard, have = _atoms(ear), _atoms(piece)
        if not heard:
            return WAIT
        if len(have) < MIN_PIECE_WORDS:
            return WAIT
        if not same_start(ear, piece, open_end=False):
            return CUT
        guarded = _protected(heard)
        if not guarded:
            return SOUND if _words(have) else WAIT        # «что такое» is a witness of no question yet
        if _protected(have) != guarded:
            return WAIT if not _protected(have) - guarded else CUT
        return SOUND if _roles_agree(heard[:len(have)] if len(have) < len(heard) else heard, have, partial=len(have) < len(heard)) else CUT
    except Exception:                     # noqa: BLE001 - not sure they agree: no sound
        return WAIT


class Pieces:
    """The stable piece of each open cloud turn: one ``LocalAgreement`` per turn, fed with the turn's text as it grows. A text the cloud has held
    unchanged since the last look (``still``: it stopped growing) is stable to its last word, but for a number or «не» at its end."""
    def __init__(self, n=2, keep=8):
        self.n, self.keep, self.turns = n, keep, {}

    def feed(self, tid, text, still=False):
        agree, last = self.turns.get(tid, (None, None))
        if agree is None:
            if len(self.turns) >= self.keep:
                self.turns.pop(next(iter(self.turns)))
            agree = LocalAgreement(self.n)
        if text != last:
            agree.push(text)
        elif still and len(agree.peeks) >= agree.n - 1:
            words = norm_words(text)
            closed = text.rstrip()[-1:] in CLOSING and words and not _negation(words[-1])     # G32: «… на 8?» is the cloud's to its end: no number grows past a «?»
            while words and _protected_word(words[-1]) and not closed:
                words.pop()
            if len(words) > len(agree.words) and words[:len(agree.words)] == agree.words:
                agree.words = words          # a pause: the turn has stopped growing, its last word is the cloud's
        self.turns[tid] = (agree, text)
        return agree.committed

    def piece(self, tid):
        agree = self.turns.get(tid, (None,))[0]
        return agree.committed if agree else ''
