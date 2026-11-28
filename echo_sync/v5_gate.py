"""V5 slice «answer gate» (setting ``v5_answer_gate``: "off" | "shadow" | "on"; "off" = as before, no gate is built).

The class of actions «speak an answer cue» goes past ONE gate, at the one place where the transport hands a cue on (NativeMediaSocket.actions, ``speak``).
For every answer cue it computes three things:

(1) meaning: the fingerprint of the question the answer was prepared for (the job's own question, ``FastText.asked_of``, else the question the plan was
    published for) against the question as the system knows it NOW (the form the controller would ask it in now, and an utterance said after it that revises
    it: one that shares a content stem with it, or a short one with a number or a negation). A fingerprint is numbers (first_useful._numbers: digits and
    spoken numbers are one atom), dates (first_useful._dated), negations and content stems. «stale»: a number or a date that was not asked, a negation turned,
    or most of what was asked is gone; «fresh»; «unknown» when the question it was prepared for is not known. Refused (on) / «would refuse» (shadow) is only
    the first hand-off of the first portion of an answer made for this question: a job's, or any whose question an utterance after it revised. A plan of an
    older question that the controller gives back on purpose (G3) and a repeat of a portion are told with their meaning and pass.
(2) the hold: which rule held the ready cue (the controller's own rule, ``why_journal.held``, or the wire's), for how long, and whether the speech that held it
    is known to be the owner's (the speaker gate of own_voice / near_voice, its last verdict, only read) or not (``other`` / ``unknown``).
(3) the age of the answer: since its question was asked of the job, or since the question opened.

The rule of «the same question» is the setting ``v5_gate_same``: "answers" (default) or "words". Under "words" (1) is as described: stems decide. Under "answers" no content
stem is read: the closed classes (a number or a date not asked, a negation turned) only FORBID «the same» (``veto``: stale at once); otherwise the relation of the two questions
is UNKNOWN, and the working definition is: one matter if the ANSWER does not change. So, on, the ready first portion is held (``parks``, asked by the wire at its one hook) within
the cap ``hold_unknown_s`` while the answer for the present form is in preparation (a look at the text channel, ``prepared``, nothing is started here), and when that answer is
there the two ANSWERS are compared by their exact things (``judge``: numbers, dates, yes or no): the same, the old one goes; they differ, the old one is refused «ответ изменился»
(through the same ``v5_stale`` as before) and the newer is the one said; no newer answer by the cap, the old one goes marked «тождество не проверено». Shadow holds nothing and
writes BOTH verdicts (``would_words``, ``would_answers``) with a code of ``CODES``: codes, counts and ids, no text.

Rule "answers", the closed classes (``closed``): a number is one name in every spelling (digits, words, an ordinal, a time, a numeral inside a compound), a day is ``DAYS``, a negation is ``NO_WORDS``
(not the «нет» of «или нет»). A veto yields in one case only: the answer for the present form is already there and does not differ in its exact things (code ``veto_overruled``); otherwise it
stops the old answer at once. Of the utterances after a question only the LAST one that may correct it (``revising``: short, no pause request, a number, a day or an answering «нет») counts.
Two answers (``judge``) are compared by their numbers, each with the word before and after it (its unit, its holder), days, polarity (a double negation is a yes), then names, then what is left of the words.
The state (``_memory``) belongs to the call, not to the gate object; every table is bounded (``_put``); the hold counts from the FIRST parking; a re-asking that gives nothing back lets the old answer go;
a failure inside the gate is written once per place and kind to the call journal (``v5_gate_error``) and the v5 record.

Shadow: the verdict («would pass», «would refuse: stale meaning», «would release earlier: held by speech not known to be the owner's») is written next to
each answer cue into the call journal (``v5_gate`` records) and into the v5 record (``journal:v5_gate``), and nothing changes. On (two small branches,
``_refuse`` and the cap in ``held``): a stale FIRST portion is not said, the question stays open and its answer is asked again through the controller
(``ControlledMedia.v5_stale``), at most ``stale_refusals`` times per question; a hold by speech not known to be the owner's ends at its cap. Every number
of the gate is in ``COSTS``. Nothing here raises into the call: a gate that fails passes the cue as today.
"""
import logging
import math
import re

from .classifier import QUESTION_WORDS
from .first_useful import _dated, _numbers
from .ru_alignment import _canonical
from .textutil import DEGREE_WORDS, FILLER_WORDS, FUNCTION_WORDS, NEGATION_WORDS, PAUSE_WORDS, STOPWORDS, norm_words, stems

logger = logging.getLogger('echo-sync')
MODES = ('off', 'shadow', 'on')

# THE cost table of the gate: every number it decides by, here and nowhere else.
COSTS = {
    'hold_other_s': 1.0,        # a ready answer waits this long on speech known to be somebody else's (today: up to 8 s past the last speech with content)
    'hold_unknown_s': 3.0,      # ... on speech whose speaker is not known (no profile, a short piece, no speaker gate): a guess must not cost 8 s, nor cut a question at once
    'stale_refusals': 1,        # a stale answer is refused this many times per question; then it is said as today (never a loop of asking again)
    'newer_words': 6,           # an utterance after the question that shares no stem with it revises it only when it is this short and has a number or a negation («а пятьдесят?»)
    'subject_kept': 0.5,        # (rule "words" only) the share of the content stems of the question then that the question now must keep, or it is another question
}                               # hold_unknown_s is also THE cap of the hold of an answer whose relation to the present question is unknown (rule "answers"): no number of its own
# the closed list of reason codes the journal carries (code -> the phrase; never the text of the conversation)
CODES = {
    'same_words': 'вопрос тот же', 'question_unknown': 'вопрос, на который готовили ответ, не известен', 'not_judged': 'не судится: не первая порция, повтор или план прежнего вопроса',
    'veto_number': 'новое число', 'veto_date': 'новая дата', 'veto_negation': 'сменилось отрицание',
    'answers_agree': 'ответы совпали', 'answer_changed': 'ответ изменился', 'answer_new_no_things': 'ответ изменился: чисел и дат нет',
    'veto_overruled': 'запрет закрытых классов снят: ответ на нынешнюю форму уже готов и не изменился',
    'identity_unchecked': 'тождество не проверено',
    'words_fresh': 'основы слов сохранены', 'words_number': 'новое число', 'words_date': 'новая дата', 'words_negation': 'сменилось отрицание', 'words_subject': 'основы слов не сохранены',
}
SAME = ('answers', 'words')
YES_WORDS = frozenset({'да', 'ага', 'угу', 'конечно', 'разумеется', 'безусловно', 'естественно'})      # the closed class «yes» (стартовое); «no» is textutil.NEGATION_WORDS
NO_WORDS = NEGATION_WORDS | {'без'}      # the closed class of negation in a QUESTION (стартовое): «без сахара» turns a question as «не» does
# the closed class «a day» (стартовое): lemmas of the weekdays, the relative days, the months, the parts of the day and the words that point at a period («следующий», «прошлый»); a day not asked only forbids «the same», as a number does
DAYS = frozenset('понедельник вторник среда четверг пятница суббота воскресенье сегодня завтра послезавтра вчера позавчера '
                 'январь февраль март апрель май июнь июль август сентябрь октябрь ноябрь декабрь '
                 'утро утром вечер вечером ночь ночью будни выходной следующий прошлый будущий предыдущий ближайший'.split())
# the numerals as the first part of a compound («шестиугольник», «двухэтажный», «пятилетка»): (the part, the number, the shortest rest of the word) - стартовое; a rest under 4 letters is «семинар»
COMBINING = (('дву', 2, 4), ('двух', 2, 4), ('трех', 3, 4), ('четырех', 4, 4), ('пяти', 5, 4), ('шести', 6, 4), ('семи', 7, 4), ('восьми', 8, 4), ('девяти', 9, 4), ('десяти', 10, 4), ('треугольн', 3, 0))
_ORDINAL = re.compile(r'^(?:#ord:|!spoken:(?:number|ordinal):)')      # an ordinal and a cardinal of one value, a spoken number and its digits are ONE number (as ru_alignment does)
_WORD = re.compile(r'[^\W\d_]+(?:-[^\W\d_]+)*')
_MEMORY = '_v5_gate_memory'
SPEECH_RULES = frozenset({'speech_with_content', 'cloud_hears_listener', 'local_ear_onset'})      # holds caused by somebody speaking (the rest wait for a text, a job, a final)
_KEPT = 64


def fingerprint(text):
    """The meaning atoms of ``text``: numbers, dates, the count of negations, content stems (numbers, function and question words out: they are the form, not the matter)."""
    text = str(text or '')
    try:
        numbers, dates = frozenset(_numbers(text)), frozenset(_dated(text))
    except Exception:       # noqa: BLE001 - no alignment: digits only
        numbers = dates = frozenset()
    words = norm_words(text)
    spoken = set()
    try:
        from .ru_alignment import _canonical
        spoken = {part for atom in _canonical(text, (), True) if atom.atom.startswith(('#', '!spoken:')) for part in norm_words(atom.surface)}
    except Exception:       # noqa: BLE001
        pass
    content = [w for w in words if w not in STOPWORDS and w not in FUNCTION_WORDS and w not in QUESTION_WORDS and w not in NEGATION_WORDS and w not in spoken and not w.isdigit()]
    return {'numbers': numbers, 'dates': dates, 'negations': sum(w in NEGATION_WORDS for w in words), 'stems': frozenset(stems(content))}


def compare(then, now):
    """``(verdict, why)``: 'fresh' / 'stale' with 'date' | 'number' | 'negation' | 'subject' / 'unknown' (the question then is not known)."""
    if not (then['stems'] or then['numbers']):
        return 'unknown', ''
    new = now['numbers'] - then['numbers']
    if new:
        return 'stale', 'date' if new <= now['dates'] else 'number'
    if now['negations'] != then['negations'] and (then['stems'] & now['stems']):
        return 'stale', 'negation'
    if len(then['stems']) >= 2 and len(then['stems'] & now['stems']) < COSTS['subject_kept'] * len(then['stems']):
        return 'stale', 'subject'
    return 'fresh', ''


def _atoms(text):
    try:
        return tuple(_canonical(str(text or ''), (), True))
    except Exception:       # noqa: BLE001 - no alignment: no atoms (digits are read below)
        return ()


def _value(atom):
    """The number an atom states, one name for an ordinal and a cardinal, digits and spoken words; None for any other atom."""
    return _ORDINAL.sub('#', atom.atom) if atom.kind in ('n', 'p') and atom.atom.startswith(('#', '!spoken:')) else None


def closed(text):
    """The closed classes of ``text``, no stem: ``numbers`` (one name for «второй» / «2» / «18:40» / «восемнадцать сорок»; a spoken «один» alone is the article of «одну вещь»,
    not counted), ``dated`` (those that say when), ``days`` (``DAYS``), ``negations`` (``NO_WORDS``; the «нет» of «или нет» only asks again), ``denial`` (an answering «нет»)."""
    atoms, numbers = _atoms(text), set()
    for atom in atoms:
        value = _value(atom)
        if value is not None and not (value == '#1' and atom.atom == '#1' and not any(ch.isdigit() for ch in atom.surface)):
            numbers.add(value)
    if not atoms:
        numbers = set(re.findall(r'\d+', str(text or '')))
    try:
        dated = {_ORDINAL.sub('#', x) for x in _dated(str(text or ''))}
    except Exception:       # noqa: BLE001
        dated = set()
    words = norm_words(text)
    numbers |= {f'#{value}' for w in words for part, value, rest in COMBINING if w.startswith(part) and len(w) - len(part) >= rest}
    alternative = [k for k, w in enumerate(words) if w == 'нет' and k and words[k - 1] == 'или']
    return {'numbers': frozenset(numbers), 'dated': frozenset(dated & numbers), 'days': frozenset(a.atom for a in atoms if a.atom in DAYS),
            'negations': sum(w in NO_WORDS for w in words) - len(alternative), 'denial': 'нет' in words and len(alternative) < words.count('нет')}


def veto(then, now):
    """The closed classes only forbid «the same» (``then`` / ``now``: ``closed``): ``'date'`` / ``'number'`` (one not asked), ``'negation'`` (the count of negations turned), else None. No stem."""
    new, days = now['numbers'] - then['numbers'], now['days'] - then['days']
    if new or days:
        return 'number' if new - now['dated'] else 'date'
    return 'negation' if now['negations'] != then['negations'] else None


def standalone(text):
    """A new question of its own: it opens with a question word and has a matter of its own (a content stem). «Сколько будет пятьдесят на два» has none: it is the first form again."""
    words = norm_words(text)
    return bool(QUESTION_WORDS.intersection(words[:2]) and fingerprint(text)['stems'])


def revising(text):
    """An utterance after the question that may correct it by the closed classes alone: short, no pause request, no question of its own, with a number, a day or an answering «нет» («нет, пятьдесят на два»)."""
    words = norm_words(text)
    if not words or len(words) > COSTS['newer_words'] or PAUSE_WORDS.intersection(words) or standalone(text):
        return False
    c = closed(text)
    return bool(c['numbers'] or c['days'] or c['denial'])


_PROPER = frozenset({'Name', 'Surn', 'Patr', 'Geox', 'Orgn'})      # the grammemes of a proper name in the dictionary of the morphology


def _proper(word):
    """The dictionary's best reading of ``word`` is a proper name (a name, a surname, a place, an organisation)."""
    try:
        from .classifier import _readings      # noqa: PLC0415
        found = _readings(word.casefold().replace('ё', 'е'))
        return bool(found) and bool(_PROPER & found[0][1])
    except Exception:       # noqa: BLE001 - no dictionary: only the capital inside a sentence tells
        return False


def _capitalized(text):
    """The names in ``text`` as stems: a word with a capital that does not open a sentence, or one that does and is a proper name by the dictionary of the morphology."""
    names, text = set(), str(text or '')
    for m in _WORD.finditer(text):
        word, before = m.group(), text[:m.start()].rstrip()
        if word[0].isupper() and ((before and before[-1] not in '.!?…') or _proper(word)):
            names.add(word.casefold().replace('ё', 'е'))
    return frozenset(stems(sorted(names)))


def _bound(atoms):
    """For each number of ``atoms`` the content word before it and the one after it (a function word, a degree word, a yes or a no is none): ``{(value, before, after)}``."""
    weak = FUNCTION_WORDS | DEGREE_WORDS | FILLER_WORDS | YES_WORDS | NO_WORDS | {'это'}
    near = lambda k: atoms[k].atom if 0 <= k < len(atoms) and atoms[k].kind in ('w', 'u') and atoms[k].atom not in weak and _value(atoms[k]) is None else None      # noqa: E731
    return {(_value(a), near(k - 1), near(k + 1)) for k, a in enumerate(atoms) if _value(a) is not None}


_SKIP = STOPWORDS | FILLER_WORDS | YES_WORDS | NO_WORDS      # what says nothing of the matter of an answer


def _lemma(word):
    try:
        from .classifier import _readings      # noqa: PLC0415
        return _readings(word)[0][2]
    except Exception:       # noqa: BLE001
        return word


def things(text):
    """The exact things of an answer: ``numbers`` (the number with the word before and after it: its unit, its holder), ``days``, ``names``, ``polarity`` ('no' / 'yes': a yes or nothing is yes;
    an answering «нет», or an odd count of «не» / «нельзя» / «без», is no: «нельзя не согласиться» is a yes), ``content`` (stems of what is left)."""
    text = str(text or '')
    atoms, words = _atoms(text), norm_words(text)
    facts = _bound(atoms) if atoms else {(n, None, None) for n in re.findall(r'\d+', text)}
    odd = sum(w in ('не', 'нельзя', 'без') for w in words) % 2
    left = [w for w in words if not w.isdigit() and not ({w, _lemma(w)} & _SKIP)]
    return {'facts': frozenset(facts), 'values': frozenset(f[0] for f in facts) | frozenset(a.atom for a in atoms if a.atom in DAYS), 'names': _capitalized(text),
            'polarity': 'no' if odd or 'нет' in words else 'yes', 'content': frozenset(stems(left))}


def _tied(a, b):
    """Every number the two answers share is tied to the same unit and holder where both name one (a missing one is no conflict)."""
    ok = lambda x, y: x is None or y is None or x == y      # noqa: E731
    return all(any(ok(x[1], y[1]) and ok(x[2], y[2]) for x in a['facts'] if x[0] == v for y in b['facts'] if y[0] == v) for v in a['values'] & b['values'] if v.startswith(('#', '!')))


def judge(old, new, over):
    """Two answers by their exact things: 'agree' / 'changed' (a number, a day or a yes or no differs) / 'no_things' (no number or day in either and the names or the words differ) /
    'wait' (the newer is not far enough to tell; ``over``: it is whole)."""
    if not str(new or '').strip():
        return 'wait'
    a, b = things(old), things(new)
    if a['polarity'] != b['polarity']:
        return 'changed'
    if a['values'] or b['values']:
        if a['values'] == b['values']:
            return 'agree' if _tied(a, b) else 'changed'
        return 'changed' if over or not (a['values'] <= b['values'] or b['values'] <= a['values']) else 'wait'
    if a['names'] or b['names']:
        if a['names'] and b['names']:
            return 'agree' if a['names'] <= b['names'] or b['names'] <= a['names'] else 'no_things' if over else 'wait'
        return 'no_things' if over else 'wait'
    nested = a['content'] == b['content'] or (a['content'] and b['content'] and (a['content'] <= b['content'] or b['content'] <= a['content']))
    return 'agree' if nested else 'no_things' if over else 'wait'


def _count(t):
    return len(t['values']) + (t['polarity'] == 'no')


def _key(cue):
    return (cue.get('epoch'), cue.get('nonce'), cue.get('revision'), cue.get('index'))


def _put(table, key, value):
    """``table[key] = value``; the oldest entries go when the table is over ``_KEPT`` (a dict keeps its order): the state of a call of 180 minutes stays bounded."""
    table[key] = value
    while len(table) > _KEPT:
        table.pop(next(iter(table)))


def _finite(now):
    return isinstance(now, (int, float)) and not isinstance(now, bool) and math.isfinite(now)


def _memory(*owners):
    """The state the gate keeps (what was asked, the holds, the refusals, the plans seen): on the wire (else the controller) of the call, so a gate built again for the same call
    does not forget it and a hold or a re-asking is not given twice; a local one when neither takes an attribute."""
    for owner in owners:
        try:
            mem = getattr(owner, _MEMORY, None)
            if not isinstance(mem, dict):
                mem = {name: {} for name in ('releases', 'holds', 'refused', 'seen', 'parked')}
                setattr(owner, _MEMORY, mem)
            return mem
        except Exception:       # noqa: BLE001
            continue
    return {name: {} for name in ('releases', 'holds', 'refused', 'seen', 'parked')}


class Gate:
    def __init__(self, mode, controller, wire, *, tap=None, note=None, same='answers'):
        self.mode, self.controller, self.wire, self.tap, self.note = mode, controller, wire, tap, note
        mem = _memory(wire, controller)
        self.releases = mem['releases']      # qid -> (the question its job was asked, when)
        self.holds = mem['holds']            # cue key -> [since, rule, last seen, speaker during a speech hold or None, when it let go at the ceiling or None]
        self.refused = mem['refused']        # qid -> stale answers refused
        self.seen = mem['seen']              # (nonce, revision) whose first portion was handed on already: a repeat of it is no new answer
        self.parked = mem['parked']          # cue key -> since: the ready first portion held while the answer for the present form is prepared (rule "answers", on); never reset by a look
        self.failed = set()                  # (where, error) already written to the journal: one line each
        self.same = same if same in SAME else SAME[0]

    def _failed(self, where, error):
        """A failure inside the gate: the cue goes as today, and the call journal and the v5 record say once that the gate failed (the kind of error, no text)."""
        name = type(error).__name__
        if (where, name) in self.failed or len(self.failed) > _KEPT:
            return
        self.failed.add((where, name))
        row = {'mode': self.mode, 'where': where, 'error': name}
        try:
            logger.warning('echo-sync v5_gate failed where=%s reason=%s', where, name)
            if self.note is not None:
                self.note('v5_gate_error', **row)
            if self.tap is not None:
                self.tap.note('journal:v5_gate', 'gate_failed', row)
        except Exception:       # noqa: BLE001
            pass

    # -- what the wire tells it --------------------------------------------------------------------------------------------

    def asked(self, action, now):
        """A ``fast`` release went out: the job of ``qid`` was asked ``question``."""
        try:
            _put(self.releases, action.get('qid'), (str(action.get('question') or ''), now))
        except Exception as error:       # noqa: BLE001
            self._failed('asked', error)

    def speaker(self):
        """Whose speech the ear hears, by the speaker gate's last verdict (only read: nothing is judged here): 'owner', 'other' or 'unknown'."""
        try:
            kind = getattr(getattr(getattr(self.controller, 'speaker_gate', None), '_verdict', None), 'kind', None)
        except Exception:       # noqa: BLE001
            kind = None
        return {'own': 'owner', 'other': 'other'}.get(kind, 'unknown')

    def held(self, cue, rule, now):
        """The ready ``cue`` is held by ``rule`` at ``now``. Returns None (the hold of today stands) or, on, for a hold by speech not known to be the owner's, the
        moment it ends (the caller lets the cue go from then on)."""
        try:
            h = self._hold(cue, rule, now)
            if rule not in SPEECH_RULES:
                return None
            h[3] = self.speaker()
            if self.mode != 'on' or h[3] == 'owner':
                return None
            return h[0] + COSTS['hold_other_s' if h[3] == 'other' else 'hold_unknown_s']      # on: the cap
        except Exception as error:       # noqa: BLE001
            self._failed('held', error)
            return None

    def ceiling(self, cue, now):
        """The ceiling of a speech hold is reached (on): True only over a voice known to be somebody else's, and the exit is written as such; over speech whose speaker is not known the hold of the owner of the cue stands (never a cue over live speech)."""
        try:
            h = self.holds.get(_key(cue))
            if h is None or h[3] != 'other':
                return False
            h[4] = now
            return True
        except Exception as error:       # noqa: BLE001
            self._failed('ceiling', error)
            return False

    def waits(self, cue, now):
        """The wire parked ``cue``: a hold whose rule was not told at this moment waits for the question's final."""
        try:
            h = self.holds.get(_key(cue))
            if h is None or h[2] != now:
                self._hold(cue, 'question_final', now)
        except Exception as error:       # noqa: BLE001
            self._failed('waits', error)

    def _hold(self, cue, rule, now):
        key = _key(cue)
        h = self.holds.get(key)
        if h is None:
            h = [now, rule, now, None, None]
            _put(self.holds, key, h)
        h[1], h[2] = rule, now
        return h

    def handed(self, cue, now):
        """``cue`` is about to be handed to the transport. Writes the verdict. Returns None (it goes on), or, on, the actions that replace it (it is refused)."""
        try:
            row, asked = self._verdict(cue, now)
        except Exception as error:       # noqa: BLE001 - the gate never costs the call
            self._failed('handed', error)
            return None
        result = self._refuse(cue, row, asked) if self.mode == 'on' and row['would'] == 'refuse' else None
        self._write(row)
        return result

    # -- the verdict -------------------------------------------------------------------------------------------------------

    def _view(self):
        """What the gate reads (no side effect): ``(job route, the question then, the question as the controller asks it now, since when, qid)``."""
        c = self.controller
        qid = c.question_id
        job = bool(c.fast_turn) and c.source_id == c.fast_turn
        if job:
            fast = getattr(self.wire, 'fast', None)
            then = fast.asked_of(qid) if fast is not None and hasattr(fast, 'asked_of') else None
            released = self.releases.get(qid)
            then = then or (released[0] if released else None)
            asked = c.fast_text or c.question_text
            at = released[1] if released else c.question_clock
        else:
            then = (c.state() or {}).get('question')
            asked = c.question_tail or c._part()
            at = c.question_clock
        return job, then, asked, at, qid

    def _look(self, asked):
        """The answer for the present form so far, ``(text, over)``, or None: only a look at the text channel, nothing is started."""
        look = getattr(getattr(self.wire, 'fast', None), 'prepared', None)
        try:
            got = look(asked) if look is not None else None
            return (str(got[0] or ''), bool(got[1])) if got else None
        except Exception:       # noqa: BLE001
            return None

    def _old(self, cue):
        """The answer made for the question then, as far as it is known: the portions of its plan, else the cue's own text."""
        try:
            state = self.controller.state() or {}
            if state.get('revision') == cue.get('revision') and state.get('chunks'):
                return ' '.join(str(x) for x in state['chunks'])
        except Exception:       # noqa: BLE001
            pass
        return str(cue.get('text') or '')

    def _answers(self, cue, then, asked, applicable):
        """Rule "answers": ``(meaning, why, code, refuse, n_old, n_new, wait)``; ``wait``: the newer answer is on its way and not far enough to compare."""
        if not str(then or '').strip():
            return 'unknown', '-', 'question_unknown', False, None, None, False
        kind = veto(closed(then), closed(asked))
        if kind:
            if applicable:      # the closed classes forbid «the same» at once; but an answer for the present form that is already there and does not differ is the working definition met
                old, look = self._old(cue), self._look(asked)
                if look is not None and judge(old, look[0], look[1]) == 'agree':
                    return 'fresh', '-', 'veto_overruled', False, _count(things(old)), _count(things(look[0])), False
            return 'stale', kind, 'veto_' + kind, applicable, None, None, False
        if norm_words(then) == norm_words(asked):
            return 'fresh', '-', 'same_words', False, None, None, False
        if not applicable:
            return 'unknown', '-', 'not_judged', False, None, None, False
        old, look = self._old(cue), self._look(asked)
        if look is None:
            return 'unknown', '-', 'identity_unchecked', False, _count(things(old)), None, False
        n_old, n_new = _count(things(old)), _count(things(look[0]))
        got = judge(old, look[0], look[1])
        if got == 'agree':
            return 'fresh', '-', 'answers_agree', False, n_old, n_new, False
        if got == 'wait':
            return 'unknown', '-', 'identity_unchecked', False, n_old, n_new, True
        return 'stale', 'answer', 'answer_changed' if got == 'changed' else 'answer_new_no_things', True, n_old, n_new, False

    def parks(self, cue, now):
        """Rule "answers", on only: the ready ``cue`` is a first portion whose relation to the present question is unknown and the answer for it is on its way: the moment
        (at most ``hold_unknown_s`` after it was FIRST parked: no look, no order of events and no gate built again for the call starts the count anew) when the wire looks at it
        again; None: it goes on (the verdict is made at ``handed``)."""
        try:
            if self.mode != 'on' or self.same != 'answers' or not _finite(now):
                return None
            job, then, asked, at, qid = self._view()
            newer = self._newer(qid, closed=True)
            if newer:
                asked = ' '.join([asked or ''] + newer).strip()
            first = cue.get('index') == 0 and not cue.get('replay_last')
            applicable = first and (cue.get('nonce'), cue.get('revision')) not in self.seen and bool(job or newer)
            key = _key(cue)
            if not self._answers(cue, then, asked, applicable)[6]:
                return None
            since = self.parked.get(key)
            if since is None:
                _put(self.parked, key, since := now)
            return since + COSTS['hold_unknown_s'] if since <= now < since + COSTS['hold_unknown_s'] else None
        except Exception as error:       # noqa: BLE001
            self._failed('parks', error)
            return None

    def _verdict(self, cue, now):
        job, then, asked, at, qid = self._view()
        before = fingerprint(then)
        words_newer, closed_newer = self._newer(qid, before), self._newer(qid, closed=True)
        asked_w = ' '.join([asked or ''] + words_newer).strip() if words_newer else asked
        asked_a = ' '.join([asked or ''] + closed_newer).strip() if closed_newer else asked
        meaning_w, why_w = compare(before, fingerprint(asked_w))
        h = self.holds.pop(_key(cue), None)
        parked = self.parked.pop(_key(cue), None)
        held = round(now - h[0], 2) if h else 0.0
        speaker = h[3] if h and h[3] else self.speaker()
        cap = COSTS['hold_other_s' if speaker == 'other' else 'hold_unknown_s']
        first = cue.get('index') == 0 and not cue.get('replay_last')
        plan = (cue.get('nonce'), cue.get('revision'))
        again = first and plan in self.seen
        if first:
            _put(self.seen, plan, True)
        speech = bool(h and h[3])
        early = speech and speaker != 'owner' and held > cap
        ceiling = bool(h and h[4] is not None)      # the hold ended at its ceiling (on, a voice known to be somebody else's): its own reason, never «pass»
        # a plan of an older question given back (G3) is told, not refused: only an answer made for this question
        refuse_w = first and not again and meaning_w == 'stale' and bool(job or words_newer)
        code_w = 'question_unknown' if meaning_w == 'unknown' else 'words_' + (why_w or 'fresh')
        meaning_a, why_a, code_a, refuse_a, n_old, n_new, _ = self._answers(cue, then, asked_a, first and not again and bool(job or closed_newer))
        by_words = self.same == 'words'
        refuse, code = (refuse_w, code_w) if by_words else (refuse_a, code_a)
        pick = lambda r: 'refuse' if r else 'ceiling' if ceiling else 'release_earlier' if early else 'pass'      # noqa: E731
        row = {'mode': self.mode, 'same': self.same, 'revision': cue.get('revision'), 'index': cue.get('index'), 'first': int(bool(cue.get('first'))), 'route': 'job' if job else 'plan',
               'meaning': meaning_w if by_words else meaning_a, 'why': (why_w or '-') if by_words else why_a, 'newer': len(words_newer if by_words else closed_newer),
               'age_s': round(now - at, 2) if isinstance(at, (int, float)) else None, 'held_s': held, 'rule': h[1] if h else '-', 'speaker': speaker, 'again': int(again),
               'would_words': pick(refuse_w), 'would_answers': pick(refuse_a), 'code_words': code_w, 'code_answers': code_a, 'n_old': n_old, 'n_new': n_new,
               'parked_s': round(now - parked, 2) if parked is not None else None, 'code': code, 'reason_ru': CODES[code], 'would': pick(refuse)}
        if row['would'] in ('release_earlier', 'ceiling'):
            row['earlier_s'] = round(held - cap, 2)
        return row, asked_w if by_words else asked_a

    def _newer(self, qid, before=None, closed=False):
        """The utterances after the question that revise it, oldest first. Rule "words" (``before``: the fingerprint of the question): one that shares a content stem with it, or a short
        one with a number or a negation. ``closed`` (rule "answers"): by the closed classes alone, no stem (``revising``), and only the LAST one counts, the speaker's latest word
        («а пятьдесят?», «ой, всё, сорок» is the first form again); a question said twice, a filler, a pause request revise nothing."""
        turns = self.controller.ledger.history()
        at = next((i for i in range(len(turns) - 1, -1, -1) if turns[i].get('id') == qid), None)
        if at is None:
            return []
        out, after = [], turns[max(at + 1, len(turns) - _KEPT):]      # U89d: the newest _KEPT turns after the question, not the whole call: the cost of a request does not grow with the call
        for t in (reversed(after) if closed else after):
            text = str(t.get('text') or '').strip()
            if t.get('role') != 'user' or not t.get('valid') or not text:
                continue
            if closed:
                if revising(text):
                    return [text]
                continue
            fp = fingerprint(text)
            if (fp['stems'] & before['stems']) or ((fp['numbers'] or fp['negations']) and len(norm_words(text)) <= COSTS['newer_words']):
                out.append(text)
        return out

    # -- on: the one branch that refuses -----------------------------------------------------------------------------------

    def _refuse(self, cue, row, asked):
        c = self.controller
        qid = getattr(c, 'question_id', None)
        ask = getattr(c, 'v5_stale', None)
        if ask is None or getattr(c, 'fast_on', True) is False:
            row['did'] = 'passed_no_reask'
            return None
        if self.refused.get(qid, 0) >= COSTS['stale_refusals']:
            row['did'] = 'passed_refusals_spent'
            return None
        _put(self.refused, qid, self.refused.get(qid, 0) + 1)
        try:
            got = list(ask(cue, asked) or [])
        except Exception as error:       # noqa: BLE001
            self._failed('reask', error)
            got = []
        if not got:      # nothing asked again: the wire would drop the cue (actions([]); continue), so the old answer goes as today
            row['did'] = 'passed_reask_empty'
            return None
        row['did'] = 'refused'
        return got

    # -- the journal and the record ----------------------------------------------------------------------------------------

    def _write(self, row):
        reason = {'pass': 'would_pass', 'refuse': 'would_refuse_stale_meaning', 'release_earlier': 'would_release_earlier_not_owner', 'ceiling': 'released_at_ceiling'}[row['would']]
        try:
            logger.info('echo-sync v5_gate ' + ' '.join(f'{k}={v}' for k, v in row.items()))
            if self.note is not None:
                self.note('v5_gate', **row)
            if self.tap is not None:
                self.tap.note('journal:v5_gate', reason, row)
        except Exception:       # noqa: BLE001
            pass


def attach(settings, controller, wire, *, tap=None, note=None):
    """The gate of this call, or None (``v5_answer_gate`` is "off" or unknown: nothing is built, the wire is as before)."""
    mode = (settings or {}).get('v5_answer_gate')
    if mode not in ('shadow', 'on'):
        return None
    return Gate(mode, controller, wire, tap=tap, note=note, same=(settings or {}).get('v5_gate_same'))
