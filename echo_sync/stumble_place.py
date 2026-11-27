"""G26: where the speaker is now inside a portion, when they stumbled and did not go from its first word: a stammer inside a word («у-у-условия»), a false start of a word
(«усл условия»), a jump over words («общие условия налогов»), a start in the middle («условия установления налогов»), a synonym («общие правила установления»), a number in other words, a
restart from the middle. The reader of a clean start (``ControlledMedia._said_of`` / ``_said_by_value``) goes first; this one is asked only when that found nothing.

Pure: no clock, no I/O. In: the words heard (normalized, the fillers told off by the caller) and the portion. Out: ``(the rest of the portion from the word after the place, words said twice)``,
``None`` when the place is not sure: never a guess. A wrong place is worse than the whole portion, so the evidence asked for is: two words of the portion in order (or its first word alone), at
most one word that is not the portion's, at most one synonym, never a number or «не» changed, the last word heard is the portion's (or the word it stands for, or the word it begins), and words left.
``tail_of``: does the heard run end the portion (the speaker finished it from its middle)?"""
import re

from .ru_alignment import _LOCK, _canonical, _lemma

MAX_SKIP = 3            # words of the portion jumped over between two words said
LONE_LETTERS = 5        # letters of a word that names a place alone, in the middle of a portion
LEAD_GARBLE = 2         # words heard wrong in front of the first right one, standing for the words before it (the call of 12:59: «у меня стоимости» of «мера стоимости»)
MIN_CUT = 3             # letters of a word cut off at the end that name the word they are on
ASKING = frozenset({'что', 'как', 'почему', 'зачем', 'сколько', 'какой', 'какая', 'какое', 'какие', 'каких', 'где', 'когда', 'кто', 'ли', 'чем', 'чему', 'разве', 'неужели'})
NEGATION = frozenset({'не', 'ни', 'нет'})
_LETTERS = re.compile(r'[^0-9a-zа-я]+')


def _flat(text):
    return _LETTERS.sub('', str(text).casefold().replace('ё', 'е'))


def _key(atom):
    return re.sub(r'^#ord:', '#', atom.atom)


def _destammer(words, own):
    """«у-у-условия» -> «условия», «усл условия» -> «условия», «о о общие» -> «общие»: a piece that only begins the next word, and is no word of the portion, is dropped."""
    out = []
    for word in words:
        parts = [part for part in str(word).split('-') if part]
        while len(parts) > 1 and parts[1].startswith(parts[0]) and (parts[0] != parts[1] or len(parts) > 2):parts = parts[1:]      # «м-м-материально-вещественной» -> «материально-вещественной»
        word = '-'.join(parts) if parts else word
        out.append(word)
    kept = []
    for at, word in enumerate(out):
        nxt = out[at + 1] if at + 1 < len(out) else None
        if nxt and nxt != word and nxt.startswith(word) and _lemma(word) not in own and not word.isdigit():continue
        kept.append(word)
    return kept


def _pos(surface):
    """The parts of speech the word may be («правила»: a noun and a verb)."""
    _lemma(surface)
    from . import ru_alignment as R
    with _LOCK:
        try:parses = R._MORPH.parse(surface)
        except Exception:return frozenset()
    return frozenset(parse.tag.POS for parse in parses if parse.score >= 0.1)


def _synonym(heard, written):
    """One word for another of the same part of speech: never a number, a negation, a short word or a symbol."""
    if heard.kind != 'w' or written.kind != 'w' or heard.atom in NEGATION or written.atom in NEGATION or len(heard.surface) < 4 or len(written.surface) < 4:return False
    kinds = _pos(written.surface) & {'NOUN', 'ADJF', 'ADJS', 'VERB', 'INFN', 'PRTF', 'PRTS', 'ADVB', 'GRND'}
    return bool(kinds & _pos(heard.surface))


def _offsets(portion, atoms):
    """The char offset in ``portion`` where each atom begins, or None when the atoms cannot be laid on its words. U16 (RANGES on): when the words do not carry them
    («XIII–XV» is one word of three atoms) they are laid on its letters, and no offset falls inside a written range."""
    marks = [(m.start(), _flat(m.group())) for m in re.finditer(r'\S+', portion)]
    marks = [(start, flat) for start, flat in marks if flat]
    at, out = 0, []
    for atom in atoms:
        want = _flat(atom.surface)
        if at >= len(marks) or not want:return _letter_offsets(portion, atoms)
        begin, got = marks[at][0], ''
        while at < len(marks) and len(got) < len(want):got += marks[at][1];at += 1
        if got != want:return _letter_offsets(portion, atoms)
        out.append(begin)
    return _whole_units(portion, out)


def _letter_offsets(portion, atoms):
    """U16: the same on the letters of the portion (the dash of a range has none: it begins where the next atom does). None with RANGES off."""
    from . import ru_alignment as R
    if not R.RANGES:return None
    flat = [(i, _flat(c)) for i, c in enumerate(portion)]
    flat = [(i, c) for i, c in flat if c]
    at, out = 0, []
    for atom in atoms:
        want = _flat(atom.surface)
        if not want:out.append(flat[at][0] if at < len(flat) else len(portion));continue
        if ''.join(c for _, c in flat[at:at + len(want)]) != want or at + len(want) > len(flat):return None
        out.append(flat[at][0]);at += len(want)
    return _whole_units(portion, out)


def _whole_units(portion, starts):
    """U16: no start inside a written range: it is the start of the range (``ru_alignment.unit_start``; the same list with RANGES off)."""
    from . import ru_alignment as R
    return [R.unit_start(portion, s) for s in starts] if R.RANGES else starts


def _cut(atom, written, pos):
    """The last word heard is cut off («сбо»): the word of the portion it begins, a little ahead of the place."""
    near = [k for k in range(pos + 1, min(len(written), pos + 2 + MAX_SKIP)) if written[k].kind == 'w' and _flat(written[k].surface).startswith(_flat(atom.surface)) and _flat(written[k].surface) != _flat(atom.surface)]
    return near[0] if near else None


def _walk(heard, written):
    """The heard atoms laid on the portion's, left to right: ``(last place, matched, extra, synonyms, twice, last heard on the portion, first word not said as written, first)``. The first word not
    said as written is one jumped over, put in another word, or cut off: the cue begins there (r07: a skipped «не», a misheard word is what is cued), never after it."""
    pos, matched, extra, subs, twice, on, miss, first = -1, 0, 0, 0, False, False, None, None
    keys = [_key(a) for a in written]
    restart, last = None, -1

    def missed(k):
        return k if miss is None else min(miss, k)
    for i, atom in enumerate(heard):
        key = _key(atom)
        ahead = [k for k in range(pos + 1, len(written)) if keys[k] == key and (pos < 0 or k - pos - 1 <= MAX_SKIP)]
        back = [k for k in range(0, pos + 1) if keys[k] == key]
        last = max(last, pos)
        if ahead:
            if pos >= 0 and ahead[0] > pos + 1:miss = missed(pos + 1)
            if pos >= 0 and ahead[0] == pos + 2 and not on and matched and i and _synonym(heard[i - 1], written[pos + 1]):extra -= 1;subs += 1     # «общие правила установления»: a word in the place of one
            pos = ahead[0];matched += 1;on = True
            if first is None:first = pos
        elif back and atom.atom not in NEGATION:
            pos = back[-1];twice = True;on = True       # a word again, or a restart from it
            if first is not None and pos < first and restart is None:restart = (pos, last, miss, extra)      # a restart from before the first word heard: the head may be lost (the closed microphone)
            if miss is not None and miss > pos:miss = None       # a restart before the word jumped over: it is said again from there
        elif i == len(heard) - 1 and atom.kind == 'w' and len(atom.surface) >= MIN_CUT and pos >= 0 and _cut(atom, written, pos) is not None:
            k = _cut(atom, written, pos);miss = missed(k if k == pos + 1 else pos + 1);on = True
        elif matched >= 2 and on and pos + 1 < len(written) and _synonym(atom, written[pos + 1]):       # H5: one word of the portion and one of its own is no start
            miss = missed(pos + 1);pos += 1;subs += 1;on = True
        else:
            if atom.atom in NEGATION:return None         # a «не» of their own: never a place
            extra += 1;on = False
    if restart is not None and pos >= restart[1] and miss == restart[2] and extra == restart[3]:first = restart[0]      # the restart said the words after it in order, as far as the run before it went: the run begins where the restart does, not in the middle (the head was lost)
    return pos, matched, extra, subs, twice, on, miss, first


def _lone_word(written, at):
    """h25: one word said alone names a place only when it cannot be another one: a long word, once in the portion."""
    atom = written[at]
    return atom.kind == 'w' and len(atom.surface) >= LONE_LETTERS and sum(_key(a) == _key(atom) for a in written) == 1


def _read(words, portion):
    words = [str(w).casefold().replace('ё', 'е') for w in words if str(w).strip()]
    if not words or frozenset(words) & ASKING - frozenset(_flat(w) for w in str(portion).split()):return None
    written = tuple(a for a in _canonical(portion, (), True))
    if not written:return None
    own = frozenset(a.atom for a in written)
    clean = _destammer(words, own)
    heard = tuple(_canonical(' '.join(clean), (), True))
    if not heard:return None
    walked = _walk(heard, written)
    if walked is None or len(heard) >= len(written):return None      # a try as long as the portion is a wrong repeat, not a stop (G3 rule 1: the whole portion)
    pos, matched, extra, subs, twice, on, miss, first = walked
    if subs and pos == len(written) - 1:return None
    skipped = range(0, first) if first else ()
    if miss is not None:skipped = list(skipped) + list(range(miss, pos + 1))
    said_past = lambda k: first is not None and k < first and matched >= 2      # h27: a number at the head of the portion, two words on from it: the place is theirs («Шесть видов: между государством…», the call of 16:15)
    if any(written[k].atom in NEGATION or (written[k].kind == 'n' and not said_past(k)) for k in skipped if not any(_key(h) == _key(written[k]) for h in heard)):return None    # a «не» or a number left out: the whole portion
    if first:      # h26: a word cut at the start of a breath comes out as other words in front of the first right one: they stand in the place of the words before it, not beside them
        lead = next((i for i, a in enumerate(heard) if _key(a) == _key(written[first])), 0)
        if lead <= min(first, LEAD_GARBLE):extra -= lead
    if not on or pos < 0 or subs > 1 or extra > 1 or (extra and matched < 3) or first is None:return None
    if matched < 2 and not (matched == 1 and not extra and (first == 0 or _lone_word(written, first))):return None
    if first > 0 and (miss is not None or subs or extra or twice):return None     # h25, the owner's rule: help goes on from the word they stopped at: a start in the middle is two words of it in a row, or one long word found once in the portion, and nothing else
    if any(a.kind == 'n' for a in heard) and not any(a.kind == 'n' and _key(a) in {_key(w) for w in written} for a in heard):return None
    return written, pos, miss, twice or len(words) > len(clean)


def place(words, portion):
    """``(rest, twice)``: the portion from the word after where the speaker is, or None (see the module)."""
    try:
        read = _read(words, str(portion))
        if read is None:return None
        written, pos, miss, twice = read
        nxt = pos + 1 if miss is None else min(miss, pos + 1)
        if nxt >= len(written):return None
        starts = _offsets(str(portion), written)
        if starts is None:return None
        begin = starts[nxt]
        while begin and str(portion)[begin - 1] in '«"„“(\'':begin -= 1
        rest = str(portion)[begin:].strip()
        return (rest, twice) if rest else None
    except ImportError:
        return None


def tail_of(words, portion):
    """The heard run ends the portion: two words of it or more, in order, up to its last."""
    try:
        read = _read(words, str(portion))
        return bool(read) and read[2] is None and read[1] == len(read[0]) - 1
    except ImportError:
        return False
