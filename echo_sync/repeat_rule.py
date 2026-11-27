"""c22-repeat: the owner's rule of repeats (setting ``repeat_rule``) and dictation (setting ``dictation``). Pure: no clock, no I/O.

The rule (the owner, c22-repeat): the system follows how far the owner got repeating the cue.
  1. the last word of the portion said (whatever came before it, the words of the portion or nothing), or most of the portion (more than half of what it says): the next portion at once;
  2. a stumble: on from the word they stopped at, not from the start (``ControlledMedia._started``, ``stumble_place``: the controller's own readers);
  3. silence, nothing said: the portion again from its start (the controller's silence timer; its bound is ``repeat_cap``: ``max_auto_repeats``, or ``cycle_max_repeats`` while the owner is dictating in the cycle).
``verdict`` reads 1; 2 and 3 stay the controller's. A wrong number or «не» is never said past: such a try is no verdict (the controller's own rules then).

Dictation (``dictation`` = "on", or said: «диктуй медленно»): the owner says the question, writes the answer by hand and says the last words of each portion. They set the tempo: the silence
timer waits for the writing (``DictationPace``: the seconds a word took them to write, learned portion by portion), a stop inside the portion is not helped too early, nothing cuts in."""
import re

from .ru_alignment import _canonical, spoken_as_written
from .stumble_place import ASKING, NEGATION

CROSS_SCRIPT = False        # U19-S6: the profile's ``cross_script`` ("on" only; shadow = off here); on: a word of the ear in the other script that sounds like a word of the portion is that word. Off = as before

MOST = 0.5                  # more than this share of what the portion says is «большая часть»
FOREIGN_WORDS = 1           # words of its own a try that ends the portion may carry («ну», a word the ear misheard)
LAST_LETTERS = 3            # a last word said alone is a word, not a sound: three letters at least (a number always)
DICTATION_START_SECONDS = 4.0      # a stop inside the portion while dictating: help after this (TEMPO_START_SECONDS otherwise): it may be the pen
DICTATION_WORD_SECONDS = 1.5       # the first guess of the seconds one word takes to write, before the owner's own
DICTATION_SPARE = 1.5              # the wait is this many times the owner's own writing time
DICTATION_EXTRA_SECONDS = 2.0      # and this much more
DICTATION_MIN_SECONDS, DICTATION_MAX_SECONDS = 6.0, 30.0
DICTATION_CYCLE_SECONDS = 1.0      # h25 ``dictation_cycle``: the owner's cycle: silence while dictating, the same portion (or the rest of it) again this long after it ended
DICTATION_CYCLE_REPEATS = 15       # and at most this many times (the default of ``cycle_max_repeats``, see ``repeat_cap``): a cue that goes on with nobody there is noise
DICTATION_CYCLE_EASY = 5            # h28: this many repeats at the cycle's pace, then one second more each, up to DICTATION_CYCLE_MAX_SECONDS: about a minute in all
DICTATION_CYCLE_MAX_SECONDS = 8.0
DICTATION_LEARN = 0.5              # how much one portion moves the learned seconds per word

_WORD = re.compile(r'[0-9a-zа-яё-]+')
_ON = (('диктуй', 'медленно'), ('диктуй', 'медленнее'), ('диктуй', 'помедленнее'), ('диктуй', 'помедленней'), ('диктуй', 'не', 'спеша'), ('диктуйте', 'медленно'), ('диктуйте', 'помедленнее'),
       ('режим', 'диктовки'), ('включи', 'диктовку'), ('включи', 'диктовка'), ('давай', 'диктовку'), ('я', 'буду', 'записывать'), ('буду', 'записывать'), ('диктуй', 'я', 'записываю'),
       ('диктуй', 'я', 'пишу'), ('я', 'записываю', 'диктуй'), ('я', 'пишу', 'диктуй'))
_OFF = (('хватит', 'диктовать'), ('выключи', 'диктовку'), ('выключи', 'диктовка'), ('без', 'диктовки'), ('диктовка', 'выключена'), ('диктуй', 'обычно'), ('диктуй', 'быстрее'),
        ('диктуй', 'как', 'обычно'), ('обычный', 'режим'), ('конец', 'диктовки'), ('я', 'не', 'записываю'), ('не', 'надо', 'диктовать'))
COMMAND_WORDS = 7           # a command is short: a longer utterance with these words is talk


def _words(text):
    return _WORD.findall(str(text).casefold().replace('ё', 'е'))


def set_cross_script(on):
    global CROSS_SCRIPT
    CROSS_SCRIPT = bool(on)


def _fold_script(said, written, keys, own):
    """U19-S6, after the roman/ordinal folding: a word ('w') of ``said`` that is not the portion's but sounds like a word ('w') of the portion in the other script takes its key. Numbers and «не» never."""
    from .lang_hint import cross_equal, word_lang
    out = list(keys)
    for i, atom in enumerate(said):
        if atom.kind != 'w' or keys[i] in own or atom.atom in NEGATION:
            continue
        for w in written:
            if w.kind == 'w' and w.atom not in NEGATION and word_lang(w.surface) != word_lang(atom.surface) and cross_equal(atom.surface, w.surface):
                out[i] = _key(w)
                break
    return out


def _key(atom):
    return re.sub(r'^#ord:', '#', atom.atom)


def _has(words, phrase):
    n = len(phrase)
    return any(tuple(words[i:i + n]) == phrase for i in range(len(words) - n + 1))


def dictation_command(text):
    """«диктуй медленно», «режим диктовки», «я буду записывать» -> "on"; «хватит диктовать», «диктуй обычно», «обычный режим» -> "off"; anything else None."""
    words = _words(text)
    if not words or len(words) > COMMAND_WORDS:
        return None
    if any(_has(words, phrase) for phrase in _OFF):
        return 'off'
    if any(_has(words, phrase) for phrase in _ON):
        return 'on'
    return None


def _share(heard, portion):
    try:
        from .fast_text import said_share
        return said_share(heard, portion)
    except Exception:          # noqa: BLE001 - not sure: no verdict
        return None


def verdict(heard, portion):
    """'next' when ``heard`` (the fillers told off by the caller) moves on by the rule: it ends on the portion's last word, or says most of it. Else None (a stumble, other speech, a wrong
    number or «не»: the controller's own rules)."""
    try:
        words = _words(heard)
        if not words or not str(portion).strip() or frozenset(words) & ASKING - frozenset(_words(portion)):
            return None
        written = [a for a in _canonical(str(portion), (), True)]
        said = [a for a in _canonical(spoken_as_written(' '.join(words), str(portion)), (), True)]      # U16: a range said as its two ends is the range written (RANGES only)
        if not written or not said or len(said) > len(written) + FOREIGN_WORDS:
            return None
        own = [_key(a) for a in written]
        keys = [_key(a) for a in said]
        if CROSS_SCRIPT:
            keys = _fold_script(said, written, keys, own)
        if any(a.kind == 'n' and _key(a) not in own for a in said) or any(a.atom in NEGATION and a.atom not in own for a in said):
            return None             # a number or a «не» of its own
        on = [own.index(k) for k in keys if k in own]
        if on:
            lo, hi = min(on), max(on)
            if any((w.kind == 'n' or w.atom in NEGATION) and _key(w) not in keys for w in written[lo:hi + 1]):
                return None         # a number or a «не» of the portion left out inside what was said
            neg = [i for i, w in enumerate(written) if w.atom in NEGATION]
            if any(i + 1 <= hi and i < lo and i + 1 >= lo for i in neg):
                return None         # «облагается налогом» of «Не облагается налогом.»: the «не» just before the try is part of it
        last = written[-1]
        if keys[-1] != own[-1] and _garbled(said[-1], last):
            keys[-1] = own[-1]      # c24 (half_hour seed 6): «рганизацией» of «организацией»: the ear lost a letter of the last word, it is that word
        foreign = [k for k in keys if k not in own]
        if keys[-1] == own[-1] and len(foreign) <= FOREIGN_WORDS and (last.kind == 'n' or len(last.surface) >= LAST_LETTERS or len(keys) > 1):
            return 'next'
        share = _share(' '.join(words), str(portion))
        if share is not None and share > MOST and len(set(keys) & set(own)) >= 2:
            return 'next'
        if not foreign and _in_order(keys, own) / len(own) > MOST and _in_order(keys, own) >= 2:
            return 'next'           # more than half of its words, in order, as people count them («её измеряют индексом» of five)
        return None
    except ImportError:
        return None


GARBLE_LETTERS = 7          # a word this long that the ear got one letter wrong of (lost, added, changed) is that word


def _garbled(heard, written):
    """Is the word ``heard`` the word ``written`` with one letter wrong (both words, not numbers, ``GARBLE_LETTERS`` long or more)?"""
    if heard.kind != 'w' or written.kind != 'w':
        return False
    a, b = heard.surface.casefold().replace('ё', 'е').strip('.,;:!?'), written.surface.casefold().replace('ё', 'е').strip('.,;:!?')
    if min(len(a), len(b)) < GARBLE_LETTERS - 1 or max(len(a), len(b)) < GARBLE_LETTERS:
        return False
    from rapidfuzz.distance import Levenshtein
    return Levenshtein.distance(a, b) <= 1


def _in_order(keys, own):
    """How many words of the portion ``keys`` says in its order."""
    at, n = 0, 0
    for key in keys:
        if key in own[at:]:
            at = own.index(key, at) + 1
            n += 1
    return n


def record_on(record_mode):
    """x-cap: does the recording (the owner writes by hand) count for the cap? Only ``record_mode`` = "earned"; "off" (default) never."""
    return record_mode == 'earned'


HALF_DUPLEX_REPEATS = 2             # u17: a half-duplex phone does not hear what is said over its own cue: the same portion is not said blindly more than this many times in a row


def repeat_cap(*, cycling, recording, unplaced, record_mode, cycle_max_repeats, max_auto_repeats, duplex='unknown'):
    """x-cap: ``(cap, why)``, the most silent repeats in a row. One table, first row that fits:
      1. ``unplaced`` (speech not understood)   -> ``max_auto_repeats``, 'unplaced'
      2. not ``cycling`` (dictation cycle off)   -> ``max_auto_repeats``, 'plain'
      3. ``record_mode`` not earned (off)        -> ``cycle_max_repeats``, 'cycle'
      4. earned and ``recording``                -> ``cycle_max_repeats``, 'record'
      5. earned, not recording                   -> ``max_auto_repeats``, 'plain'
    u17: a row that gives ``max_auto_repeats`` gives at most HALF_DUPLEX_REPEATS when ``duplex`` is 'half' (the meter saw the phone drop its microphone while a cue sounded), why 'half'; the cycle (3, 4) is the owner's pen, it stands."""
    if unplaced or not cycling:
        cap, why = max_auto_repeats, 'unplaced' if unplaced else 'plain'
    elif not record_on(record_mode):
        return cycle_max_repeats, 'cycle'
    elif recording:
        return cycle_max_repeats, 'record'
    else:
        cap, why = max_auto_repeats, 'plain'
    return (HALF_DUPLEX_REPEATS, 'half') if duplex == 'half' and cap > HALF_DUPLEX_REPEATS else (cap, why)


def cycle_wait(repeats):
    """h28: the seconds of silence before the next repeat of the cycle, ``repeats`` said so far."""
    return min(DICTATION_CYCLE_MAX_SECONDS, DICTATION_CYCLE_SECONDS + max(0, repeats - DICTATION_CYCLE_EASY + 1))


class DictationPace:
    """The owner's tempo of writing: seconds per word of a portion, from the end of its cue to the start of the last words they said of it."""

    def __init__(self, per_word=DICTATION_WORD_SECONDS):
        self.per_word = per_word
        self.seen = 0

    @staticmethod
    def count(portion):
        return max(1, len(_words(portion)))

    def observe(self, portion, seconds):
        if not isinstance(seconds, (int, float)) or seconds <= 0:
            return
        took = min(seconds, DICTATION_MAX_SECONDS) / self.count(portion)
        self.per_word = took if not self.seen else self.per_word + DICTATION_LEARN * (took - self.per_word)
        self.seen += 1

    def wait(self, portion, base=0.0):
        """How long silence after the cue of ``portion`` is writing, not silence: never shorter than ``base`` (the silence timer of the profile)."""
        own = DICTATION_SPARE * self.per_word * self.count(portion) + DICTATION_EXTRA_SECONDS
        return max(base, min(DICTATION_MAX_SECONDS, max(DICTATION_MIN_SECONDS, own)))


# c24-c: the owner names a word of the portion while writing. «последнее записанное слово X», «я записал X», «остановился на X», «после слова X»: on AFTER it (it is written); «повтори со
# слова X», «с X» after a verb of saying: on FROM it (they want it heard). Short, said first; a quote of it inside longer speech is talk.
_FROM = (('повтори', 'со', 'слова'), ('повтори', 'с', 'слова'), ('повтори', 'начиная', 'со', 'слова'), ('повтори', 'начиная', 'с'), ('повтори', 'со'), ('повтори', 'с'), ('повторите', 'со', 'слова'),
         ('повторите', 'с'), ('еще', 'раз', 'со', 'слова'), ('еще', 'раз', 'с'), ('начни', 'со', 'слова'), ('начни', 'с'), ('читай', 'со', 'слова'), ('читай', 'с'), ('продиктуй', 'с'), ('диктуй', 'с'),
         ('давай', 'со', 'слова'), ('давай', 'с'), ('снова', 'с'), ('со', 'слова'), ('с', 'слова'))
_AFTER = (('последнее', 'записанное', 'слово'), ('последнее', 'записанное'), ('последнее', 'слово'), ('я', 'записал', 'до', 'слова'), ('я', 'записала', 'до', 'слова'), ('записал', 'до', 'слова'),
          ('записала', 'до', 'слова'), ('записал', 'до'), ('записала', 'до'), ('я', 'записал'), ('я', 'записала'), ('записал'), ('записала'), ('я', 'дописал'), ('я', 'дописала'), ('дописал'),
          ('дописала'), ('я', 'остановился', 'на', 'слове'), ('я', 'остановилась', 'на', 'слове'), ('остановился', 'на', 'слове'), ('остановилась', 'на', 'слове'), ('я', 'остановился', 'на'),
          ('я', 'остановилась', 'на'), ('остановился', 'на'), ('остановилась', 'на'), ('я', 'на', 'слове'), ('дальше', 'после', 'слова'), ('дальше', 'после'), ('после', 'слова'), ('после',))
_LEAD = frozenset({'ну', 'так', 'а', 'вот', 'э', 'ээ', 'эм', 'мм', 'хорошо', 'так', 'окей', 'теперь'})
_NOT_A_WORD = frozenset({'начала', 'начало', 'конца', 'конец', 'этого', 'этой', 'того', 'места', 'него', 'нее'})
LANDMARK_WORDS = 3          # a landmark is one word, or a few that tell it from its twin


def landmark_command(text):
    """``(mode, words)``: 'after' (on after the words) or 'from' (on from them) and the words named, or None."""
    words = _words(text)
    while words and words[0] in _LEAD:
        words = words[1:]
    if not words or len(words) > COMMAND_WORDS:
        return None
    for mode, phrases in (('from', _FROM), ('after', _AFTER)):
        for phrase in sorted((p if isinstance(p, tuple) else (p,) for p in phrases), key=len, reverse=True):
            if tuple(words[:len(phrase)]) == phrase:
                target = words[len(phrase):]
                if not target or len(target) > LANDMARK_WORDS or target[0] in _NOT_A_WORD or frozenset(target) & ASKING:
                    return None
                return mode, target
    return None


def landmark(text, portion, at=None):
    """Where a named word puts the owner in ``portion``: ``('rest', the portion from there)``, ``('next', None)`` when the last word written is the portion's last, or None (no command, no such
    word in this portion, another number). ``at``: the index of the word the last help of this portion began from (where they are): a twin before it is written already. Without it, or with
    twins both after it, the earlier twin: a few words heard again, nothing unwritten skipped (at 1, past «Налог» of «Налог платят …, и налог платят»: «я записал налог» is that first one)."""
    try:
        said = landmark_command(text)
        if said is None:
            return None
        mode, target = said
        from .stumble_place import _offsets
        written = list(_canonical(str(portion), (), True))
        named = [_key(a) for a in _canonical(' '.join(target), (), True)]
        own = [_key(a) for a in written]
        if not written or not named:
            return None
        places = [k for k in range(len(own) - len(named) + 1) if own[k:k + len(named)] == named]
        if not places:
            return None
        later = [k for k in places if at is not None and k + len(named) >= at]      # the twin they just wrote ends where they are; one wholly before it is written long ago
        k = later[0] if later else places[0]
        start = k + len(named) if mode == 'after' else k
        if start >= len(written):
            return ('next', None)
        starts = _offsets(str(portion), written)
        if starts is None:
            return None
        begin = starts[start]
        while begin and str(portion)[begin - 1] in '«"„“(\'':
            begin -= 1
        rest = str(portion)[begin:].strip()
        return ('rest', rest) if rest else None
    except ImportError:
        return None


RUN_WORDS = 2               # the last words written, said without a command: two of the portion in a row at least (one word, «это», is no place)
_LEAD_FILLERS = frozenset({'ну', 'так', 'э', 'ээ', 'эм', 'мм', 'вот'})


def written_to(text, portion):
    """c24-c: dictating, ``text`` is a run of ``portion``'s words, short of its end, found once in it: the owner says what they wrote last. The portion after the run, or None (one word, the
    portion's end, a run found twice, a word left out or of its own, another number, a question)."""
    try:
        words = _words(text)
        while words and words[0] in _LEAD_FILLERS:
            words = words[1:]
        if not words or frozenset(words) & ASKING:
            return None
        from .stumble_place import _offsets
        written = list(_canonical(str(portion), (), True))
        said = [_key(a) for a in _canonical(spoken_as_written(' '.join(words), str(portion)), (), True)]
        own = [_key(a) for a in written]
        if len(said) < RUN_WORDS or len(said) >= len(own):
            return None
        places = [k for k in range(len(own) - len(said) + 1) if own[k:k + len(said)] == said]
        if len(places) != 1 or places[0] + len(said) >= len(own):
            return None
        starts = _offsets(str(portion), written)
        if starts is None:
            return None
        rest = str(portion)[starts[places[0] + len(said)]:].strip()
        return rest or None
    except ImportError:
        return None
