"""H1: the fast text channel. The GPT-Live transcript comes at speech pace (~15 chars/s, nothing changes it), so the first portion of an answer waits ~2.4 s
for its own letters. The plain Codex text channel of the same sign-in (``POST chatgpt.com/backend-api/codex/responses``, ``FAST_MODEL``, effort low) gives
its first text after ~1.2 s and then ~190 chars/s (03_TESTS/fast_text, scripts/exp_fast_text.py: the request, the headers and the SSE reading are copied
from there). 0 RUB: the existing Codex sign-in only. GPT-Live stays: it hears and transcribes.

* A job is ONE streaming request in a daemon thread, with ``cancel``: bounded (FIRST_TEXT_S to the first text, WHOLE_S in all), one job at a time per call,
  the roads own the verdict on a road (``reserve_text.Roads``: its rest, its stalls); no breaker. Logged by numbers only
  (``echo-sync fast_text job=… ttft_ms=… chars=… outcome=…``): never a word of a question or an answer, never the token.
* ``FastText.prepare(text)``: the local ear heard a question - a job is started for its text. Preparation: nothing reaches the controller.
* ``FastText.release(...)``: the arbiter opened a question or left a final to judge (ControlledMedia). A running job whose text matches it (``same_question``)
  is ADOPTED, else it is cancelled and a job starts on it. ``poll()`` then hands the job's text to the controller, which judges it and feeds it through the
  ordinary path as an assistant turn owned by the question (ControlledMedia.fast_feed).
* The sign-in comes from a callable the host gives (``codex_road.codex_stream(credentials)``, the first road: ``codex_road.primary``); this module never reads a file for it.
* T1 (the transport, ``codex_road.CodexTransport``, U79: the Codex route is that one file): ONE httpx client per call, made when the call opens (``warm``) or at the first job, closed with the call. A new client per job cost 272 ms on every answer (338 against 65 ms, n=5),
  and httpx keeps an idle connection 5 s while questions come less often: so ``KEEPALIVE_S`` and one light ping every ``PING_S`` (``PING_URL``: no model, no quota, no token). A dead socket gets exactly one retry, and
  none once a text has been yielded; a cancelled job closes its response, never the client. Nothing here is shared between calls.
* Off unless the profile's ``fast_text`` is ``"on"`` (``for_call``): then nothing of this module runs.

H2 (the owner's call of 4 Nov 20:34: a remark cued as «Ну наконец-то.», 1988 for 988, meta tails as portions): this channel is the BRAIN, GPT-Live the ear. Every final the
arbiter does not take as a repeat, a command or a try at the portion comes here, and the job's text is the verdict and the answer: ``BRAIN`` says «—» to what asks nothing. The
measurement that decided it, on known lines and not on a call: 05_WORK/scripts/exp_text_brain.py, 03_TESTS/fast_text/text_brain_*.json (39 of 39 remarks declined, 10 of 10
questions answered, 7 of 8 doubts held, no voice quota used).
"""
import logging
import re
import threading
import time
from collections import Counter
from difflib import SequenceMatcher

from .classifier import QUESTION_WORDS, _known, question_part, strip_fillers
from .diagnostics import reason_of
from .settings import resolve
from . import reserve_text
from .reserve_text import Roads, Tried, Walk
from .textutil import STOPWORDS, norm_words, normalize, spoken_lead

logger = logging.getLogger('echo-sync')

FIRST_TEXT_S = 4.0           # connect / first text: a job that has said nothing by then is a failure (one cold start in the measurement took 14 s)
WHOLE_S = 15.0               # the whole job; a prepared job older than this is not adopted either
EAR_JOBS = 4                 # c16 ``ear_job``: the same count when the ear's breath starts the jobs: a preface of three pieces must leave the piece that asks its job. What ``_ear_first`` prepares itself is no count of this
REFUSED_NOTES_PER_JOB = 3     # U07-S4: refusals of one job told in full to the call trace; the rest is one fast_refused_sum
PREPARE_JOBS = 2             # H7 (the count on the replays, the quota is real): new prepared jobs in one breath: a question cut in two pieces gets its job, a minute of remark does not get a job per piece
HISTORY_EXCHANGES = 6        # the last exchanges of the call the model is told
HISTORY_CHARS = 600          # of each question / answer
SIMILARITY = 0.75            # word similarity at which the ear's question is the cloud's
# H2: the prompt of a job. H5 item 3: what exp_brain_commands.py measured, byte for byte (exp_text_brain.py and that script read it from here, this is the one copy; real wordings: 71 of 78 right, the 7 mostly reasonable, TTFT 1.08 s
# on an idle machine), and item 5: its last line, the first words of an answer. That line was not in the measurement. The session's content policy is not sent. H7 item 0 («ответы подробнее нужны»): a fact is the fact, a definition or an explanation gets
# two or three sentences, the first a usable answer alone: not in any measurement yet, ``exp_text_brain.py --limit 40`` is the coordinator's.
from .brain_rules import BRAIN, BRAIN_KEEP      # noqa: E402 - U124: the instructions are the rows of ``brain_rules`` (each line tied to the error it was written for); BRAIN_KEEP: what the content policy says of the form of a spoken answer and BRAIN does not
# What the content policy says of the form of a spoken answer and BRAIN does not (content_policy.ANSWER_POLICY: the language, the length of a phrase, the numbers), and what the
# channel is. Its honesty, the order of an answer and its objections are BRAIN's own.
BRAIN_POLICY = BRAIN + '\n' + BRAIN_KEEP
# Rule 6: the lookup gave no source. BRAIN has no hedge, so no «По памяти:» is asked for (the cloud's text, native_media_socket.NO_SOURCE_RESULT); what is refused without one
# (the engine: ``says_a_number``) is told beforehand.
NO_SOURCE_BRAIN = 'Источника для этого вопроса нет: ответь из своих знаний. Числа, даты, суммы и ставки, в которых не уверен, не называй совсем.'
REVISED_MARK = ' (этот ответ был неверным, он исправлен ниже)'
# H5 item 3: a job's whole text is one of these: the listener's command, as the word the arbiter knows.
COMMANDS = {'[стоп]': 'стоп', '[продолжай]': 'продолжай', '[повтори]': 'повтори', '[дальше]': 'дальше'}
# What the arbiter is told for a mark: «дальше» said to «Дальше идёт налог…», «продолжай» to «Продолжайте платить…» are a try at that portion, and the command would go nowhere.
COMMAND_SAID = {'дальше': 'следующая часть', 'продолжай': 'продолжи'}


# --- the match of the ear's question with the cloud's ----------------------------------------------------------------------------

def _atoms(text):
    from .ru_alignment import _canonical      # noqa: PLC0415 - the controller's own comparison form: lemmas, numbers by value
    return _canonical(str(text or ''), (), True)


def _is_number(atom):
    return atom.kind == 'n' or atom.atom.startswith(('#', '!spoken:'))


def _words(atoms):
    """The content words of ``atoms`` (lemmas): no numbers, no function words."""
    return {atom.atom for atom in atoms if not _is_number(atom) and atom.atom not in STOPWORDS}


from .lang_hint import EN_NOT as _EN_NOT      # noqa: E402
from .lang_hint import answer_instructions as _answer_instructions      # noqa: E402


def _protected(atoms):
    """What two texts of one question must agree on: the numbers by value («сорок восемь» and «48» are one), «не», «ни»."""
    found = Counter()
    for atom in atoms:
        if _is_number(atom):
            found['#' + _value(atom)] += 1
        elif atom.atom in ('не', 'ни'):
            found[atom.atom] += 1
        elif atom.atom in _EN_NOT:      # w10 item 8 (w9-fast-no N134): English not/no/never are protected like «не»
            found['not'] += 1
    return found


# --- the roles in a question (A2) -------------------------------------------------------------------------------------------------
# The counts of the numbers and of «не» do not say whose they are: «было 80, потратил 20» and «было 20, потратил 80», «не нагревать, а охлаждать» and «нагревать, а не охлаждать» count alike, and so do «до» and «после»,
# «от Москвы до Питера» and «от Питера до Москвы», «кто убил Каина» and «кого убил Каин». Two texts of one question also agree on what stands next to each of those. A refusal costs one more request (the job is
# started on the final), a wrong acceptance is a wrong answer said aloud: where this cannot tell, it refuses. Words one text has and the other lacks (the ear drops «я», «на»; the cloud drops «э-э») are no conflict
# for the open classes (persons, prepositions, modals); for the closed ones (numbers, «не», question words, «нет», «или», the signs «+», «−», «<») every one counts. ``_roles_agree``: two texts of one question (``same_question``),
# the cut start of one (``same_start``, ``partial``); ``_roles_within``: a part cut out of a whole (``said_within``).
_PERSON = frozenset('я ты мы вы он она оно они мой твой наш ваш свой'.split())
_NEGATORS = frozenset('нет нельзя никто ничто ничего никогда нигде никуда никак никакой нисколько'.split())
_SIGNS = frozenset('+ − × ÷ = < > ≤ ≥ ^'.split())                     # «минус 5 градусов» is not «5 градусов»
_ASKING = frozenset('кто что какой который чей сколько когда где куда откуда зачем почему отчего как каков или либо'.split())
_MODAL = frozenset('нужно надо можно должный обязать необходимо вправе'.split())
_LINKS = frozenset('если чем нежели пока хотя зато чтобы потому поскольку'.split())
_FILLING = frozenset('ну вот'.split())                                       # said to fill the time, never a part of the question
_LIGHT = frozenset('ли же бы ведь уж'.split())                       # said between a word and what it governs, binds nothing
_MODIFIERS = frozenset('ровно примерно приблизительно почти всего только лишь уже еще целых около'.split())     # said between a governor and its number
_KEPT = _PERSON | _NEGATORS | _MODAL | frozenset('не ни быть есть'.split())     # in STOPWORDS, and still what a number or a «не» stands next to
_SKIPPED = (STOPWORDS | _MODIFIERS | _LIGHT) - _KEPT
_BINDING = frozenset('не ни'.split()) | _SIGNS                  # what stands in front of the next word of its own: «не нагревать», «минус 5»
_ALIKE = {'об': 'о', 'обо': 'о', 'во': 'в', 'со': 'с', 'ко': 'к', 'ото': 'от', 'изо': 'из', 'подо': 'под', 'передо': 'перед', 'пред': 'перед', 'безо': 'без'}
_CASE_OF = {'gen1': 'gent', 'gen2': 'gent', 'acc1': 'accs', 'acc2': 'accs', 'loc1': 'loct', 'loc2': 'loct', 'voct': 'nomn'}
CASE_SHARE = 0.15                                # the share of the analyzer's readings of a form in a case below which the form is not taken to stand in it («Пушкину» reads 0.17 as the accusative of an unknown name)
_GRAMMAR = {}                                    # surface -> (is a noun, the cases it may stand in); bounded
_PREPOSITIONS = []                               # made at the first use


def _unfilled(atoms):
    """``atoms`` without the sounds and the words said only to fill the time («э-э», «ну», «вот»): they stand inside a number and its unit too, and then they would part the two."""
    from .ru_alignment import _without_hesitations      # noqa: PLC0415 - the controller's own forms
    return tuple(atom for atom in _without_hesitations(tuple(atoms)) if atom.atom not in _FILLING)


def _prepared(text):
    """The atoms of ``text`` as ``same_question`` compares them: no fillers, a number is its value whether it was said as a cardinal or an ordinal («12 марта» and «двенадцать марта»), and a unit right after a number is
    one atom («80 рублей» and «80 ₽», «100 °C» and «ста градусах Цельсия»)."""
    from .ru_alignment import _units      # noqa: PLC0415
    return _units(tuple(atom._replace(atom='#' + _value(atom)) if atom.kind == 'n' and atom.atom.startswith('#') else atom for atom in _unfilled(_atoms(text))))


def _value(atom):
    """A number by value: no leading zero («ОП.09» and «девять» are one; w9-rehearsal P1)."""
    return re.sub(r'^0+(?=\d)', '', re.split(r'[:#]', atom.atom)[-1])


def _prepositions():
    if not _PREPOSITIONS:
        from .textutil import PREPOSITIONS      # noqa: PLC0415
        _PREPOSITIONS.append(frozenset(_ALIKE.get(word, word) for word in PREPOSITIONS))
    return _PREPOSITIONS[0]


def _grammar(atom):
    """``(is a noun, the cases the word may stand in)``: a noun or a pronoun by its surface form; ``(False, ∅)`` when the analyzer does not know or is not there."""
    found = _GRAMMAR.get(atom.surface)
    if found is None:
        try:
            from . import ru_alignment as ru      # noqa: PLC0415
            ru._lemma(atom.surface)               # makes the shared analyzer
            with ru._LOCK:
                parses = ru._MORPH.parse(atom.surface)
            weight = Counter()
            for parse in parses:
                if parse.tag.POS in ('NOUN', 'NPRO') and parse.tag.case:
                    weight[_CASE_OF.get(parse.tag.case, parse.tag.case)] += parse.score
            found = (bool(parses) and parses[0].tag.POS == 'NOUN', frozenset(case for case, share in weight.items() if share >= CASE_SHARE))
        except Exception:                         # noqa: BLE001 - no analyzer: no case, no unit by its part of speech
            found = (False, frozenset())
        if len(_GRAMMAR) > 4096:
            _GRAMMAR.clear()
        _GRAMMAR[atom.surface] = found
    return found


def _is_unit(atom):
    """A word right after a number that says what is counted («80 рублей», «5 километров», «3 яблока»): a unit atom, a sign («%», «+»), or a noun. «5 умножить» has none."""
    return not _is_number(atom) and atom.atom not in STOPWORDS and (atom.kind == 'u' or (atom.kind == 'p' and not atom.atom.startswith('!')) or (atom.kind == 'w' and _grammar(atom)[0]))


def _target(atoms, at):
    """What ``atoms[at]`` (a «не», a preposition) stands in front of: the next atom that is no function word, particle or modifier; ``None`` at the end."""
    return next(('#' + _value(atom) if _is_number(atom) else atom.atom for atom in atoms[at + 1:] if atom.atom not in _SKIPPED), None)


def _number_roles(atoms):
    """``[(value, unit, around)]`` of the numbers in the order they are said. ``unit``: the noun right after it. ``around``: the words said since the number before it (and its unit) that bind something: «было» and «я» are
    on one number, «потратил» and «я» on the other. Function words, particles and modifiers («ровно», «уже») are no part of it."""
    found, since, at = [], set(), 0
    while at < len(atoms):
        atom = atoms[at]
        if _is_number(atom):
            unit = atoms[at + 1] if at + 1 < len(atoms) and _is_unit(atoms[at + 1]) else None
            found.append((_value(atom), unit and unit.atom, frozenset(since)))
            since, at = set(), at + 1 + (unit is not None)
        else:
            if atom.atom not in _SKIPPED:
                since.add(atom.atom)
            at += 1
    return found


def _numbers_agree(left, right, partial):
    """The same numbers in the same order, each with the unit it was said with and the words said before it (the one has all the other's, or the other all of the one's: the ear says «вот», the cloud «у меня»). With one
    number there is nothing to swap. ``partial``: a cut start, the unit of the last number may not have come."""
    one, other = _number_roles(left), _number_roles(right)
    if [role[0] for role in one] != [role[0] for role in other]:
        return False
    if len(one) < 2:
        return True
    return all((partial or not a[1] or not b[1] or a[1] == b[1]) and (a[2] == b[2] or (a[2] and b[2] and (a[2] <= b[2] or b[2] <= a[2]))) for a, b in zip(one, other))


def _counted(atoms, group):
    """Counter of the words of ``group`` in ``atoms`` (a preposition in its short or long form is one)."""
    return Counter(word for word in (_ALIKE.get(atom.atom, atom.atom) for atom in atoms) if word in group)


def _bound(atoms, words):
    """Counter of ``(word, what it stands in front of)`` for the ``words`` among ``atoms``; a word at the end has nothing yet, and makes no pair."""
    found = Counter()
    for at, atom in enumerate(atoms):
        word = _ALIKE.get(atom.atom, atom.atom)
        target = _target(atoms, at) if word in words else None
        if target is not None:
            found[(word, target)] += 1
    return found


def _rebound(one, other):
    """Did a word of the one go in front of another word in the other, or another word in front of the same? A pair only one text has is no conflict (the ear drops a preposition)."""
    return any(a[0] == b[0] or a[1] == b[1] for a in one - other for b in other - one)


def _stranded(pairs, atoms):
    """Is the word of a pair that the other text has not (a word a «не» stands in front of) said in the other text without it? Of a cut start nothing else can be told: «нагревать» was said, and no «не» before it."""
    names = {'#' + _value(atom) if _is_number(atom) else atom.atom for atom in atoms}
    return any(word in names for _, word in pairs)


def _crossed(left, right):
    """Do two nouns that stand within three words of each other, and that their cases do not tell apart («мать» and «дочь» are both nominative and accusative), come in the other order in the other text?"""
    def spots(atoms):
        seen = Counter(atom.atom for atom in atoms)
        return {atom.atom: (at, _grammar(atom)[1]) for at, atom in enumerate(atoms) if atom.kind == 'w' and seen[atom.atom] == 1 and _grammar(atom)[0]}
    one, other = spots(left), spots(right)
    shared = [word for word in one if word in other]
    return any(abs(one[x][0] - one[y][0]) <= 3 and (one[x][1] & one[y][1] or other[x][1] & other[y][1]) and (one[x][0] < one[y][0]) != (other[x][0] < other[y][0]) for at, x in enumerate(shared) for y in shared[at + 1:])


def _in_a_run(big, small):
    """Do the numbers of a part (``small``, ``_number_roles``) stand in the whole (``big``) as one run, each with its unit and the words said before it? The first number of the part may start at the unit of the one before
    it, and say its own unit before it («рублей и я потратил 20», «статья 21» and «21-я статья»); the next ones are as in ``_numbers_agree``, and a next number the part says with no words before it lacks them only (a cut takes words from its neighbours)."""
    def agrees(at):
        cut = {big[at - 1][1] if at else None}
        return all((not a[1] or not b[1] or a[1] == b[1]) and (b[2] - cut - {a[1]} <= a[2] if i == 0 else not b[2] or a[2] == b[2] or (a[2] and b[2] and (a[2] <= b[2] or b[2] <= a[2]))) for i, (a, b) in enumerate(zip(big[at:], small)))
    return not small or any([role[0] for role in big[at:at + len(small)]] == [role[0] for role in small] and agrees(at) for at in range(len(big) - len(small) + 1))


def _roles_within(whole, part):
    """``_roles_agree`` for a ``part`` cut out of a ``whole``: what the part says of the numbers, «не», the closed words and the cases is said so in the whole. A cut takes words from their neighbours, so what the part
    lacks is no conflict, and what it has must be there: its numbers are a run of the whole's, each with a unit and the words said before it that are not the whole's other ones; its «не» and its signs stand in front
    of the word they stand in front of in the whole, and a word the whole has a «не» in front of is not said without it inside the part."""
    whole, part = _unfilled(whole), _unfilled(part)
    if not _in_a_run(_number_roles(whole), _number_roles(part)):
        return False
    held, said = _bound(whole, _BINDING), _bound(part, _BINDING)
    if said - held or _stranded(held - said, part[1:]) or _rebound(_bound(part, _prepositions()), _bound(whole, _prepositions())):
        return False
    for group in (_NEGATORS | _ASKING | _SIGNS, _PERSON, _MODAL):
        if _counted(part, group) - _counted(whole, group):
            return False
    return _flips(whole, part) < 2 and not _crossed(whole, part)


def _flips(left, right):
    """How many nouns and pronouns, said as often in each text, stand there in a case the other cannot be in («Каина» / «Каин», «кого» / «кто», «мне» / «я»)? The k-th «я» of the one is the k-th of the other. One is an ear's
    slip of an ending, two are two roles turned round. «Кто» and «что» in another case are the question itself turned round («кого уволили» / «кто уволил»): they count twice."""
    def cases(atoms):
        found = {}
        for atom in atoms:
            if atom.kind == 'w':
                found.setdefault(atom.atom, []).append(_grammar(atom)[1])
        return found
    one, other = cases(left), cases(right)
    return sum(2 if word in ('кто', 'что') else 1 for word, found in one.items() if len(found) == len(other.get(word, ())) for mine, theirs in zip(found, other[word]) if mine and theirs and not mine & theirs)


def _roles_agree(left, right, partial=False):
    """Do the atoms of two texts agree on the roles (see above)? ``partial``: ``right`` is the cut start of an utterance and ``left`` its head of the same length: a word at the end has not got what it stands in front of,
    and the unit of the last number may not have come."""
    left, right = _unfilled(left), _unfilled(right)
    if not _numbers_agree(left, right, partial):
        return False
    nots = (_bound(left, _BINDING), _bound(right, _BINDING))
    if partial and (_rebound(*nots) or _stranded(nots[0] - nots[1], right) or _stranded(nots[1] - nots[0], left)) or not partial and nots[0] != nots[1]:
        return False
    if _rebound(_bound(left, _prepositions()), _bound(right, _prepositions())):
        return False
    closed = _NEGATORS | _ASKING | _SIGNS
    if _counted(left, closed) != _counted(right, closed):
        return False
    for opened in (_PERSON, _MODAL, _LINKS, _prepositions()):          # one in each text that the other has not: put in the other's place
        one, other = _counted(left, opened), _counted(right, opened)
        if one - other and other - one:
            return False
    return _flips(left, right) < 2 and not _crossed(left, right)


def _garbled(word, atoms):
    """H7 item 2: did the ear write ``word`` of the final as something no dictionary knows and close to it («прикалки» for «при Калке»)? Two words of the language are two words: «сальто» and «сальдо» stay apart."""
    return any(not _is_number(atom) and atom.kind != 'u' and not _known(atom.atom) and SequenceMatcher(None, atom.atom, word).ratio() >= SIMILARITY for atom in atoms)


# f1-question (WAVE15, 177 'words' with ``prepare_wide`` on): a new word of the final is forgiven when the speaker only filled the time with it (``_DISCOURSE``, by its surface: «типа» is also «какого типа», not here),
# or when it is the ear's word with another ending: one snowball stem and one sound (``instant.phonetic``) at least SIMILARITY alike. Names are exact: «Австралии» / «Австрии»; «сальто» / «сальдо» have two stems.
_DISCOURSE = frozenset('короче собственно вообще значит получается слушайте слушай смотрите смотри скажите скажи подскажите подскажи пожалуйста давайте давай итак кстати допустим скажем ладно хорошо'.split())
_NAMES = frozenset({'Name', 'Surn', 'Patr', 'Geox', 'Orgn', 'Trad'})


def _discourse(word, atoms):
    return all(normalize(atom.surface) in _DISCOURSE for atom in atoms if atom.atom == word)


def _named(atom):
    try:
        from . import ru_alignment as ru      # noqa: PLC0415
        ru._lemma(atom.surface)
        with ru._LOCK:
            return any(_NAMES & set(map(str, parse.tag.grammemes)) for parse in ru._MORPH.parse(atom.surface)[:2])
    except Exception:                         # noqa: BLE001 - not sure it is no name: it is one
        return True


def _recognized(word, heard, asked):
    from .instant import phonetic             # noqa: PLC0415 - instant imports this module
    from .textutil import stem                # noqa: PLC0415
    mine, root = [atom for atom in asked if atom.atom == word], stem(word)
    return bool(mine) and len(root) >= 4 and not any(_named(atom) for atom in mine) and any(
        atom.kind == 'w' and not _is_number(atom) and atom.atom not in STOPWORDS and stem(atom.atom) == root and not _named(atom)
        and SequenceMatcher(None, phonetic(atom.atom), phonetic(word)).ratio() >= SIMILARITY for atom in heard)


# W13 item 4: a number word in a set phrase about the form of the answer is no number of the question («в двух словах»: 'numbers' refused a job of the same question)
_FORM_IDIOMS = re.compile(r'(?<!\w)(?:в\s+дв(?:ух|ух-тр[её]х)\s+(?:словах|предложениях)|одним\s+словом|в\s+одном\s+предложении|(?:в\s+)?пар[уеы]\s+слов(?:ах)?)(?!\w)', re.I)


def _no_form_idioms(text):
    return _FORM_IDIOMS.sub(' ', str(text or ''))


def _from_its_start(left, right):
    """c16: ``left`` from where ``right`` begins in it: the ear has no marks, so nothing cuts the preface off its text; the longest run the two share says where the question stands."""
    block = SequenceMatcher(None, [a.atom for a in left], [a.atom for a in right], autojunk=False).find_longest_match(0, len(left), 0, len(right))
    return left[max(0, block.a - block.b):] if block.size else left


MISSING_TAIL_WORDS = 3       # U07-S7: with no asking word in the question, the tail that ``missing_ok`` never forgives is its last words


def _forgiven(missing, right, limit):
    """U07-S7, ``missing_ok``: at most ``limit`` missing words, all of them outside the asking tail (from the first question word of ``asked`` to its end, else its last ``MISSING_TAIL_WORDS`` words), none a question word or a «нет»-word."""
    if not 0 < len(missing) <= limit:
        return False
    first = next((n for n, atom in enumerate(right) if atom.atom in _ASKING), max(0, len(right) - MISSING_TAIL_WORDS))
    tail = {atom.atom for atom in right[first:]}
    return not any(word in tail or word in _ASKING or word in _NEGATORS or word in _SIGNS for word in missing)


def refusal(heard, asked, *, threshold=SIMILARITY, strip=None, soft=False, tail=False, missing_ok=0):
    """Is ``heard`` (what the local ear made of the speech) the question ``asked`` (the cloud's): the same numbers (and the same «не»), every content word of ``asked`` in
    ``heard`` (half a question, another key word, H2 rule 9: a share of the words cannot tell them, those pairs are at least 0.75 alike), and the words (lemmas, numbers folded)
    alike by at least ``threshold`` (difflib ratio)? A2: and the same roles (``_roles_agree``): the numbers in one order, each with its unit and what was said before it, «не» in front of the same word, the same
    question words, persons, prepositions and cases at the same words. ``strip`` removes the fillers before the comparison. None when it is; else the rule that says no: 'empty', 'numbers', 'words', 'alike', 'roles', 'broken'.
    H7 item 2, ``soft``: «every content word of the final» forgives a word the ear garbled (``_garbled``). The numbers, «не», «ни» and the roles stay exact. c16, ``tail``: of ``heard`` only what stands from the start of ``asked`` (``_from_its_start``).
    U07-S7, ``missing_ok``: up to that many missing words outside the asking tail are forgiven (``_forgiven``); 0 is the rule as it was."""
    try:
        if strip is not None:
            heard, asked = strip(heard), strip(asked)
        heard, asked = _no_form_idioms(heard), _no_form_idioms(asked)
        left, right = _prepared(heard), _prepared(asked)
        if not left or not right:
            return 'empty'
        if tail:
            left = _from_its_start(left, right)
        if _protected(left) != _protected(right):
            return 'numbers'
        missing = _words(right) - {atom.atom for atom in left}
        if missing and not (soft and all(_garbled(word, left) or _discourse(word, right) or _recognized(word, left, right) for word in missing)) and not _forgiven(missing, right, missing_ok):
            return 'words'
        alike = lambda heard_atoms: SequenceMatcher(None, [a.atom for a in heard_atoms], [a.atom for a in right]).ratio() >= threshold      # noqa: E731
        if not alike(left) and not (soft and len(left) > len(right) and alike(left[-len(right):])):     # f1-question: the ear's own preface in front of the part that asks
            return 'alike'
        return None if _roles_agree(left, right) else 'roles'
    except Exception:                     # noqa: BLE001 - not sure it is the same question: it is not
        return 'broken'


def same_question(heard, asked, *, threshold=SIMILARITY, strip=None):
    """``refusal`` has nothing against it."""
    return refusal(heard, asked, threshold=threshold, strip=strip) is None


def same_start(heard, asked, *, threshold=SIMILARITY, strip=None, open_end=True):
    """H4 rule 2: does what the cloud has of an utterance so far (``asked``) go the way the ear heard it (``heard``)? ``same_question`` on what it has: the head of ``heard`` as long as ``asked`` agrees with it on the
    numbers and the words and (A2) the roles, and every content word of ``asked`` is in ``heard``. ``open_end``: a delta stops anywhere, its last word may be cut and is not looked at. No word yet is nothing against it."""
    try:
        if strip is not None:
            heard, asked = strip(heard), strip(asked)
        left, right = _atoms(heard), _atoms(asked)
        right = right[:-1] if open_end else right
        if not right:
            return True
        head = left[:len(right)]
        if not head or _protected(head) != _protected(right) or _words(right) - {atom.atom for atom in left}:
            return False
        return SequenceMatcher(None, [a.atom for a in head], [a.atom for a in right]).ratio() >= threshold and _roles_agree(head, right, partial=True)
    except Exception:                     # noqa: BLE001 - not sure it agrees: it does not
        return False


def said_within(heard, asked, *, strip=None):
    """H4: is all that ``asked`` says in ``heard``: its numbers by value, its «не», its content words, and (A2) its roles (``_roles_within``)? The cloud cut one utterance of the ear elsewhere, and this is a part of it."""
    try:
        if strip is not None:
            heard, asked = strip(heard), strip(asked)
        left, right = _atoms(heard), _atoms(asked)
        return not _protected(right) - _protected(left) and not _words(right) - {atom.atom for atom in left} and _roles_within(left, right)
    except Exception:                     # noqa: BLE001 - not sure it is a part: it is not
        return False


def adds_nothing(heard, said, *, strip=None):
    """The owner's call of 06.11 (65f46fe91e81): the cloud glues the question already answered and the answer said back into one final, the job answers that again, and the cue
    goes round. Does ``heard`` say nothing that ``said`` (the last question and cues) did not: no number, «не» or abbreviation of its own, two words in a row of one of them, at
    most half of its content words new? «Срок камеральной проверки» after «срок выездной проверки» has no two words in a row: a question of its own."""
    try:
        left = _atoms(strip(heard) if strip is not None else heard)
        spoken = [_atoms(text) for text in said]
        known = [atom for atoms in spoken for atom in atoms]
        words = _words(left)
        if not words or _protected(left).keys() - _protected(known).keys():
            return False
        if {found.upper() for found in _ABBREVIATION.findall(str(heard))} - {found.upper() for text in said for found in _ABBREVIATION.findall(str(text))}:
            return False
        if len(words) <= 2 and not words - {atom.atom for atom in known}:     # level 1 of 06.11: the cloud cut a repeat, «… и» | «ответственностью»: a piece of the cue has no pair of words
            return True
        order = [atom.atom for atom in left if atom.atom in words]
        pairs = {pair for atoms in spoken for pair in _pairs(atoms)}
        return len(words - {atom.atom for atom in known}) <= max(1, len(words) // 2) and any(pair in pairs for pair in zip(order, order[1:]))
    except Exception:                     # noqa: BLE001 - not sure: it is heard as usual
        return False


def _last_word_restored(left, right):
    """U53: the ear cut the LAST word of the portion («сбо» for «сборов») or got a letter wrong: it is the portion's word, by the one rule of ``ru_alignment`` (a head needs the word before it said; numbers and «не» stay strict)."""
    from .ru_alignment import _last_word_as_written      # noqa: PLC0415
    restored = _last_word_as_written(tuple(left), tuple(right))
    return left if restored is None else type(left)(restored)


def _changed(left, right):
    """A number of its own. A «не» of the portion lost is ``_nots_agree``'s: only before a word that was said (c23: «25 марта» for «Не позднее 25 марта.» is its end said, «позднее 25 марта» is not)."""
    return bool(_protected(left).keys() - _protected(right).keys())


def ends_like(heard, portion):
    """The owner, 06.11: «говорил часть ответа или другими словами, но главное повторял в конце вот эту кодовую фразу»: the last words of the portion close what was said, whatever
    came before them. A number or a «не» of its own is a change, that one is said again (g17: so is a «не» of the portion lost before its word, and a number read in pairs is the portion's).
    Own words before that end are a few («своими словами», «ну значит»): a text whose own content words outnumber the end it closes with is another utterance that happens to end alike."""
    try:
        left, right = _atoms(heard), _atoms(portion)
        if _changed(left, right) or _runs(left, right) is None:
            return False
        said, key = _ends(left, right), _ends(right, right)[-2:]
        if not key or said is None or said[-len(key):] != key or not _nots_agree(left, right):
            return False
        mine = _said_words(right) | {_digits(atom) for atom in right if _is_number(atom)}
        return len([word for word in said[:-len(key)] if word not in mine]) <= len(key)
    except Exception:                     # noqa: BLE001 - not sure: the portion stays
        return False


def _said(atom):
    """A content word of what is said back: ``_words`` without the signs and brackets the portion is written with («(ФНС России)», «—» read as «−»): those are never said. A unit («%») is a word."""
    return atom.kind in ('w', 'u') and not _is_number(atom) and atom.atom not in STOPWORDS


def _said_words(atoms):
    return {atom.atom for atom in atoms if _said(atom)}


def _digits(atom):
    return re.sub(r'\D', '', _value(atom))


def _composed(run):
    """The numbers a run of numbers said side by side reads as, by their digits: the spoken «тридцать» «два» «десять» are 32 and 10, «две» «тысячи» «двадцать» is 2020, a «ноль» is a number of its own."""
    read, held = [], None
    for said in run:
        if not said.isdigit():                          # «0,2», «68.02»: a number written whole is read as it is
            read += [held, re.sub(r'\D', '', said)]
            held = None
            continue
        value = int(said)
        round_of = 10 ** (len(str(held)) - len(str(held).rstrip('0'))) if held else 0
        if held and value in (1000, 10 ** 6, 10 ** 9) and held < value:
            held *= value
        elif held and 0 < value < round_of:
            held += value
        else:
            read.append(held)
            held = value
    return [str(value) for value in read[1:] + [held] if value is not None] if run else []


def _runs(left, right, *, used=True):
    """g17: the numbers of ``left`` as the numbers of ``right`` they say, in order: numbers side by side are one number when ``right`` has it so («тридцать два десять» for 3210, «шестьдесят восемь ноль два»
    for 68.02). None when one of them is no number of ``right``: a number of its own, a number changed. ``_read_out`` read all the digits as one string, and «2» was found in «26». ``used``: a number of ``right``
    is said once."""
    wanted = Counter(_digits(atom) for atom in right if _is_number(atom))
    groups, run = [], []
    for atom in tuple(_unfilled(left)) + (None,):
        if atom is not None and _is_number(atom):
            run.append(_value(atom))
            continue
        read = _composed(run)
        while read:                                      # the longest head of the run that is a number of ``right``
            end = next((end for end in range(len(read), 0, -1) if wanted[''.join(read[:end])] > 0), 0)
            if not end:
                return None
            joined = ''.join(read[:end])
            wanted[joined] -= used
            groups.append(joined)
            read = read[end:]
        run = []
    return groups


def _ends(atoms, right):
    """The content words and the numbers of ``atoms`` in order, a number by its digits as ``right`` has it (``_runs``); None: a number of its own."""
    out, run = [], []
    for atom in tuple(_unfilled(atoms)) + (None,):
        if atom is not None and _is_number(atom):
            run.append(atom)
            continue
        if run:
            read = _runs(run, right, used=False)
            if read is None:
                return None
            out += read
            run = []
        if atom is not None and _said(atom):
            out.append(atom.atom)
    return out


def _key(atoms, at):
    """A word as a «не» before it is told: a content word by itself, a function word with the word after it («не как ЕНП», «не всю таблицу»: «то» of «про то что» is no «то» of «ни то ни другое»)."""
    return atoms[at].atom if _said(atoms[at]) else (atoms[at].atom, atoms[at + 1].atom if at + 1 < len(atoms) else '')


def _negated(atoms):
    """The words a «не» or «ни» stands in front of (what follows it, past the fillers), and the words no «не» stands in front of."""
    atoms = list(_unfilled(atoms))
    no = lambda atom: atom.atom in ('не', 'ни') or atom.atom in _EN_NOT
    return ({_key(atoms, at + 1) for at, atom in enumerate(atoms[:-1]) if no(atom)},
            {_key(atoms, at) for at, atom in enumerate(atoms) if not no(atom) and not (at and no(atoms[at - 1]))})


def _nots_agree(left, right):
    """g17 (3000 portions of the bank): «Декларация представляется позднее 30 апреля» said to «не позднее 30 апреля», «не облагается» said to «облагается»: the meaning is the other one, and that is
    said again. A «не» of ``left`` stands where ``right`` has one; a word ``right`` says with «не» is not said without it."""
    (mine, plain), (theirs, _) = _negated(left), _negated(right)
    return not mine - theirs and not (plain & theirs) - mine


def reads_out(heard, portion):
    """Do the numbers of ``heard`` read out those of ``portion``, cut wherever («двадцать» | «два процента» for 22 процента)?"""
    try:
        left, right = _atoms(heard), _atoms(portion)
        numbers = [_digits(atom) for atom in right if _is_number(atom)]
        runs = _runs(left, right)
        return bool(numbers) and runs is not None and sorted(runs) == sorted(numbers)
    except Exception:                     # noqa: BLE001 - not sure: it is no reading out
        return False


def most_said(heard, portion):
    """The owner's call of 06.11 (a1fbfe4ba92e): a portion said back as people say it, a word lost («шестьдесят девять расчёты»), a number read in pairs («тридцать два десять»
    for 3210): all its numbers, by their digits, and half of what it says (``said_share`` >= 0.5: 0.6 was tried by c23 and turned two scenes red, so the code is the truth and this line follows it). It was never taken, and the same cue went on for minutes. g17: every number of it said as it is and none of its own
    («кредит 4» is not «кредит 02», «15 ноября» is not «5 ноября»), its «не» where it has them; a portion of function words only («то есть что есть») is said back word for word.
    A text of which more than half of the content words are none of the portion's is another utterance that shares a part of it, not the portion said back."""
    share = said_share(heard, portion)
    if share is None or share < 0.5:
        return False
    try:
        left, right = _atoms(heard), _atoms(portion)
        words = _said_words(right)
        said = [atom.atom for atom in left if atom.atom in _said_words(left)]
        own = [word for word in said if word not in words]
        return 2 * len(own) <= len(said)
    except Exception:                     # noqa: BLE001 - not sure: the portion stays
        return False


def said_share(heard, portion):
    """What share of ``portion`` ``heard`` says back (``most_said``), or None: a word, a number or a «не» of its own, a number of it not said (a word of its own may be a word changed: it is said again once)."""
    try:
        left, right = _atoms(heard), _atoms(portion)
        left = _last_word_restored(left, right)
        numbers = [_digits(atom) for atom in right if _is_number(atom)]
        words = _said_words(right)
        runs = _runs(left, right)
        said = [atom.atom for atom in left if atom.atom in _said_words(left)]
        at = [n for n, word in enumerate(said) if word in words]
        if runs is None or sorted(runs) != sorted(numbers) or set(said[at[0]:at[-1]] if at else ()) - words or not _nots_agree(left, right):       # own words around it are his, inside it they may be a word changed
            return None
        if len(words - set(said)) == 1 and set(said) - words:      # one word of it gone and one of its own: a word changed, said again once
            return None
        if not words | set(numbers):
            return 1.0 if right and [atom.atom for atom in _unfilled(left)] == [atom.atom for atom in _unfilled(right) if atom.kind in ('w', 'u')] else None
        mine, theirs = Counter(atom.atom for atom in right if atom.atom in words), Counter(atom.atom for atom in left if atom.atom in words)      # E875: «half of what it says» counts a word each time the portion says it
        return (sum(min(theirs[word], count) for word, count in mine.items()) + len(numbers)) / (sum(mine.values()) + len(numbers))
    except Exception:                     # noqa: BLE001 - not sure: the portion stays
        return None


_ABBREVIATION = re.compile(r'\b[А-ЯЁA-Z]{2,}\b')


def _pairs(atoms):
    order = [atom.atom for atom in atoms if atom.atom in _words(atoms)]
    return zip(order, order[1:])


def roles_around(heard, asked, *, strip=None):
    """H7 item 2 over A2: the wide rule compares the parts that ask, and what stands around them may be what is asked about: «было 80 рублей, потратил 20, сколько денег осталось» and «было 20 рублей, потратил 80, сколько денег
    осталось» have one part, «сколько денег осталось». So the two whole texts answer for the roles as well: one of them is a part of the other (``_roles_within``). A remark only one of them holds is no conflict, the same
    numbers with other roles are. Two remarks that differ lose an adoption: a lost one costs a request, a false one a wrong answer said aloud."""
    try:
        if strip is not None:
            heard, asked = strip(heard), strip(asked)
        left, right = _prepared(heard), _prepared(asked)
        return _roles_within(left, right) or _roles_within(right, left)
    except Exception:                     # noqa: BLE001 - not sure of the roles: they differ
        return False


def wide_refusal(heard, text, *, strip=None, whole=False):
    """H7 item 2 (61 pairs of the ear and the final on the phone: 17 passed; 'words' refused 25, 'numbers' 16): a final holds the remark around the question, with its words and its numbers, the ear's job the question. The parts
    that ask are compared, and the two whole texts answer for the roles (``roles_around``). None when ``heard`` is what ``text`` asks, else the rule. c16: the one reading of an adoption, and so of the cloud's open turn as a witness.
    ``whole``: the ear has no marks: ``heard`` is also read from where the part of ``text`` starts, and nothing ``text`` says of numbers and «не» may be missing from ``heard``: a job that has not heard a condition does not answer it."""
    asked = question_part(text)
    rules = [refusal(said, asked, strip=strip, soft=True) for said in (question_part(heard), heard)] + ([refusal(heard, asked, strip=strip, soft=True, tail=True)] if whole else [])
    if None not in rules:
        return rules[0]
    try:
        if whole and _protected(_prepared(_no_form_idioms(strip(text) if strip else text))) - _protected(_prepared(_no_form_idioms(strip(heard) if strip else heard))):
            return 'numbers'
    except Exception:                     # noqa: BLE001 - not sure it heard them: it did not
        return 'broken'
    return None if roles_around(heard, text, strip=strip) else 'roles'


def meaning_guard(left, right, *, strip=None):
    """U15-S3, a pure verdict on two texts of one question: SAME, DIFFERS or UNKNOWN (``utterance_judge``). DIFFERS: each text has a number (by value, with its unit), «не» or question word the other lacks, the roles of the
    numbers, «не» and cases are turned round, or each has content words the other lacks and they are not alike. UNKNOWN: one text only lacks an atom (a dropped number, «не» or content word: the ear's drop or the meaning).
    SAME: nothing but fillers and function words is not shared. A dropped «не» is UNKNOWN on purpose (the ear drops it rarely, the controller turns it into DIFFERS where the cloud has it and the ear lacks it, ``_late_correction``); an added one is UNKNOWN too, and the mutation 'not' of tools/replay/mutate.py reports it as the guard's gap (U43: the verdict is M1's, tests/test_u15_guard.py pins it)."""
    from .utterance_judge import DIFFERS, SAME, UNKNOWN      # noqa: PLC0415
    try:
        if strip is not None:
            left, right = strip(left), strip(right)
        one, other = _prepared(_no_form_idioms(left)), _prepared(_no_form_idioms(right))
        if not one or not other:
            return UNKNOWN
        closed = _NEGATORS | _ASKING | _SIGNS
        pairs = ((_protected(one), _protected(other)), (_counted(one, closed), _counted(other, closed)), (Counter(a.atom for a in one if a.kind == 'u'), Counter(a.atom for a in other if a.kind == 'u')))
        if any(a - b and b - a for a, b in pairs):
            return DIFFERS
        dropped = any(a != b for a, b in pairs)
        if not dropped and not _roles_agree(one, other):
            return DIFFERS
        mine, theirs = _words(one) - _words(other), _words(other) - _words(one)
        if mine and theirs:                  # each has a content word the other lacks: another object, unless the ear only garbled it
            return UNKNOWN if all(_garbled(word, other) for word in mine) and all(_garbled(word, one) for word in theirs) else DIFFERS
        return UNKNOWN if dropped or mine or theirs else SAME
    except Exception:                     # noqa: BLE001 - not sure: unknown
        return UNKNOWN


# --- live_first: the cue before the final goes on the cloud's input text ----------------------------------------------------------
# The calls of 6 Nov: a partial still for 0.25 s with the ear silent for 0.9 s was a head of the final in 14 of 18 turns (the recognizer trails the voice). One whose last word is the ear's last word: 26 turns, 18 the very final, 8 a head (the next
# utterance glued to the turn 13-21 s later, or no question), 0 with another word, number or «не». And in 36 turns the last still partial changed no number and no «не».
CAUGHT_UP = 0.7              # how alike the last words of the ear and the cloud must be: the ear's words are rough («идёт»: «идет»), and «счета» is no «расчетные»
HEARD_MISSING = 0.25         # the share of the question's words a job may not have been asked (``heard_all``)


def keep_chatter(heard, asked, words, *, strip=None):
    """U15-S4, the keep of a chatter prefix: the job prepared on ``heard`` lacks words of ``asked`` (rule 'words'), but they all stand in a prefix of at most ``words`` words in front of the question (chatter: «ну слушайте, а»). True when
    the rest of ``asked`` is refused by nothing (``refusal`` is None). A protected atom (number, «не», «ни») or a question word in the prefix is never chatter: the prefix is then discarded and so is the job."""
    try:
        if words < 1:
            return False
        if strip is not None:
            heard, asked = strip(heard), strip(asked)
        pieces = str(asked).split()
        for count in range(1, min(words, len(pieces) - 1) + 1):
            prefix = _prepared(' '.join(pieces[:count]))
            if _protected(prefix) or any(atom.atom in _ASKING or atom.atom in _NEGATORS or atom.atom in _SIGNS or atom.kind == 'u' for atom in prefix):
                return False
            if refusal(heard, ' '.join(pieces[count:])) is None:
                return True
        return False
    except Exception:                     # noqa: BLE001 - not sure: discard
        return False


def caught_up(heard, text, *, strip=None):
    """Has the cloud's input ``text`` come as far as the ear ``heard``: is its last word the ear's last word, a number by its value, a word by likeness? In any doubt no."""
    try:
        one, other = _prepared(strip(heard) if strip else heard), _prepared(strip(text) if strip else text)
        if not one or not other:
            return False
        last, cloud = one[-1], other[-1]
        if _is_number(last) or _is_number(cloud):
            return bool(_is_number(last) and _is_number(cloud) and _value(last) == _value(cloud))
        return last.atom == cloud.atom or SequenceMatcher(None, last.atom, cloud.atom).ratio() >= CAUGHT_UP
    except Exception:                     # noqa: BLE001 - not sure it has: it has not
        return False


def ear_disputes(heard, text, *, strip=None):
    """Do the ear and the cloud differ on a number, a code or a «не»? The ear's are compared with the part of ``text`` that asks, and with all of it: a preface may be said in another utterance. A code the ear cannot read («ка два»: «КО-2») is a
    dispute: the final decides. In any doubt yes."""
    try:
        heard, text = (strip(heard), strip(text)) if strip else (heard, text)
        ear = _protected(_prepared(_no_form_idioms(heard)))
        return ear != _protected(_prepared(_no_form_idioms(question_part(text)))) and ear != _protected(_prepared(_no_form_idioms(text)))
    except Exception:                     # noqa: BLE001
        return True


def heard_all(asked, text, *, strip=None):
    """Was a job ``asked`` what the last sentence of ``text`` says? ``wide_refusal`` lets the end of a question stand for it («какой максимальный срок» of «испытательный срок для главного бухгалтера, какой максимальный срок»); ``refusal``, the rule with
    ``prepare_wide`` off, does not. A safety of the reading of the question only: it says nothing of the answer («3 месяца» of 7:37 on 6 Nov was the answer of a job that had heard all nine pieces). Its words are told by likeness, the ear's are rough; a
    quarter of them may be missing. In any doubt no."""
    try:
        have = [atom.atom for atom in _prepared(strip(asked) if strip else asked)]
        part = re.split(r'(?<=[.!?…])\s+', text.strip())[-1]      # not ``question_part``: that cuts at a comma, and the comma is where the question was lost
        want = [atom.atom for atom in _prepared(strip(part) if strip else part) if not _is_number(atom) and atom.atom not in STOPWORDS]
        missing = [word for word in want if not any(word[:4] == near[:4] or SequenceMatcher(None, word, near).ratio() >= CAUGHT_UP for near in have)]
        return len(missing) <= len(want) * HEARD_MISSING
    except Exception:                     # noqa: BLE001
        return False


def _named_numbers(atoms):
    """``{the start of a word: its numbers}``, each number by the word it is said with, before it or after it («счёт 58», «пятьдесят восьмой счёт»)."""
    found = {}
    for at, atom in enumerate(atoms):
        if _is_number(atom):
            for near in atoms[max(0, at - 1):at] + atoms[at + 1:at + 2]:
                if not _is_number(near) and len(near.atom) >= 4:
                    found.setdefault(near.atom[:4], set()).add(_value(atom))
    return found


def answer_keeps(asked, answer, *, strip=None):
    """Does ``answer`` keep the numbers of what it was ``asked``? It may name none and may add its own; what it says with the word of the question's number must hold that number («Счёт 61»: «Счёт 62 — …» is another account). In any doubt no."""
    try:
        want, said = _named_numbers(_prepared(strip(asked) if strip else asked)), _named_numbers(_prepared(answer))
        return all(values & said[word] for word, values in want.items() if word in said)
    except Exception:                     # noqa: BLE001
        return False


# --- what a job said ------------------------------------------------------------------------------------------------------------

_LEADING_DASH = re.compile(r'[—–]+\s*|-+\s+')       # not the minus of «-5 градусов»
_MARK = re.compile(r'\s*\[(?:' + '|'.join(mark[1:-1] for mark in COMMANDS) + r')\]|\s*\[[^\]]*$', re.I)
# The words of a doubt or a dispute, on ``norm_words`` joined (ё folded, lower case). «может» alone proves nothing: «Может ли налог …» asks, and has a subject of its own (``revises``).
_DOUBT = re.compile(r'(?<![\w-])(?:уверен\w*|точно|правда|разве|неужели|неверн\w*|неправильн\w*|ошиб\w*|действительно|серьезно|сомнева\w*|может|все-таки)(?![\w-])')


def brain_answer(said):
    """What a job has said so far as an answer: ``''`` while there is no word in it (nothing, «—», or a form of it: «—.», «"—"», «…»), else the text (a dash in front of it
    dropped; the end is kept as it came: the next piece goes on from it)."""
    said = str(said or '')
    if not re.search(r'\w', said) or re.fullmatch(r'\W*(?:none|null)\W*', said, re.I):      # a null literal of a road is no word of an answer, as a dash is none
        return ''
    said = _undashed(said.lstrip())
    return '' if said.startswith('[') else said      # a mark, or the start of one: no word of it is for the earpiece (``brain_command``)


def _undashed(said):
    found = _LEADING_DASH.match(said)
    return said[found.end():] if found else said


def brain_command(said):
    """H5 item 3: the word of the command when the text of a job is exactly a mark, else None. A dash in front of it or a capital in it make no answer of it, and read as a decline a stop would be replayed through."""
    return COMMANDS.get(_undashed(str(said or '').strip()).casefold())


def unmarked(text):
    """The answer without a mark the job put inside it, and without what may be the start of one at its end: no word of it is for the earpiece. Other brackets stay the model's."""
    return _MARK.sub('', text)


def asks_by_form(text):
    """U50: has ``text`` the form of a question: a «?», a question word, a figure, or a question part (``question_part.extract``: the ear writes no «?»)? A text with none of them is a remark until a job says otherwise:
    «Ну давай быстрее уже», «понятно, хорошо». The job decides all the same (the prompt knows «пять на пять»); this only says how much it may cost to ask (``reserve_text.Walk.screen``)."""
    text = str(text or '')
    if '?' in text or any(char.isdigit() for char in text) or QUESTION_WORDS & set(norm_words(text)):
        return True
    try:
        from .question_part import extract      # noqa: PLC0415
        return extract(text).kind == 'question'
    except Exception:      # noqa: BLE001 - not sure it is a remark: it asks
        return True


def doubts(heard):
    """Does ``heard`` hold a word of doubt? «Разве?» has no content word and still disputes the answer in play."""
    return bool(_DOUBT.search(' '.join(norm_words(heard))))


_AGAIN = re.compile(r'(?<![\w-])(?:ещ[её] раз|заново|снова|пересчита\w*|перепровер\w*|не сходится|не получается)(?![\w-])')


def asks_again(heard):
    """Does ``heard`` ask for the answer in play to be done again («пересчитайте ещё раз», «что-то не сходится»)? Such words ask for it as a doubt does: the job saying it again is the answer."""
    return bool(_AGAIN.search(' '.join(norm_words(heard))))


def of_the_answer(heard, answer, question):
    """Is ``heard`` a doubt of ``answer`` (to ``question``): a word of doubt and no subject of its own? H2 rule 4; H6 item 7: a job that says «—» to that is confirmed all the same."""
    said = ' '.join(norm_words(heard))
    return bool(_DOUBT.search(said)) and not _words(_atoms(_DOUBT.sub(' ', said))) - _words(_atoms(answer)) - _words(_atoms(question))


def _values(atoms):
    return {_value(atom) for atom in atoms if _is_number(atom)}


def revises(answer, text, *, heard='', question='', disputed=False):
    """H2 rule 4: does ``text``, the job's answer to ``heard`` with ``answer`` (to ``question``) in play, take that answer's place? ``heard`` disputes it: ``disputed`` (the
    classifier saw a correction), or a word of doubt and no subject of its own (with one it is a new question: «Может ли налог …»; «почему?» and «а 27-я?» hold no doubt at all).
    And ``text`` gives it up: an answer with numbers by its numbers (one is gone and none is left, or another came; a shorter retelling that keeps one and adds none confirms: a job
    is told to say two or three short phrases), any other when no word of what it claims beyond the question is in it. A doubt that keeps them confirms."""
    try:
        if not disputed and not of_the_answer(heard, answer, question):
            return False
        old, new = _atoms(answer), _atoms(text)
        if _values(old):
            if disputed and not _values(new):
                return False
            return bool(_values(old) - _values(new)) and (bool(_values(new) - _values(old)) or not _values(old) & _values(new))
        claim = _words(old) - _words(_atoms(question))
        return bool(claim) and not claim & _words(new)
    except Exception:                     # noqa: BLE001 - not sure it replaces the answer: it does not
        return False


# --- the request ---------------------------------------------------------------------------------------------------------------

def _user(text):
    return {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text': text}]}


def build_request(question, *, instructions, history=(), material='', played=None, also=''):
    """The body of the call: the instructions (``BRAIN_POLICY`` with the owner's material), the earlier exchanges of the call, then ``material`` (the text ``context_frames``
    gives the cloud model for a lookup, or the no-source text) and what was heard as the user input. ``played``: the answer in play as ``(its question, the whole answer)``: the
    input then says so, in the shape the experiment measured, so that «ты уверена», «почему», «а 27-я?» have their context. No tools, no delegation. The history is text in the
    instructions: the one shape of the input that the live measurement proved is a user message. An answer a repair took back says so. H6 item 3: ``also``: the ear's words of the same utterance, when they differ from the cloud's:
    the input carries both."""
    lines = []
    rows = [entry for entry in history or () if isinstance(entry, dict)]
    if played:
        rows = [entry for entry in rows if (str(entry.get('question') or ''), str(entry.get('answer') or '')) != tuple(played)]
    for entry in rows[-HISTORY_EXCHANGES:]:
        asked, answer = str(entry.get('question') or '').strip()[:HISTORY_CHARS], str(entry.get('answer') or '').strip()[:HISTORY_CHARS]
        if asked and entry.get('unanswered'):        # ROOT-2: said and not answered (a test question read with its options): the context of a follow-up
            lines.append(f"Прозвучало без ответа: {asked}")
        elif asked and answer:
            lines.append(f"Вопрос: {asked}\nОтвет: {answer}{REVISED_MARK if entry.get('status') == 'revised' else ''}")
    parts = [str(instructions or BRAIN_POLICY)]
    if lines:
        parts.append('Последние реплики этого разговора (для связи с вопросом):\n' + '\n'.join(lines))
    said = f'Распознано: {question} / {also}' if also else question
    heard = f'Вопрос: {played[0]}\nТвой ответ: {played[1]}\nСейчас прозвучало: {said}' if played else said
    messages = ([_user(material)] if material else []) + [_user(heard)]
    return {'instructions': '\n\n'.join(parts), 'input': messages}      # the job's request: what is asked; how a road words it on the wire is the road's (``codex_road.wire``)


# --- the job and the channel of one call -------------------------------------------------------------------------------------------

# g21-brain: the run-up of the model and a confirmation of a repeat are cut at the output (the one place every text passes) by the one rule of the text, ``textutil.spoken_lead``.


class Job:
    """One request. ``outcome`` is set once: ``ok`` / ``error`` (the thread's), ``timeout`` / ``cancelled`` (the manager's)."""

    def __init__(self, number, text, request, started, material, played=None, on='final', after_ear=None):
        self.number, self.text, self.request, self.started, self.has_material, self.played = number, text, request, started, bool(material), played
        self.on, self.after_ear, self.usage, self.refused, self.adopted = on, after_ear, None, set(), False
        self.refused_over = {}      # U07-S4: the refusals beyond REFUSED_NOTES_PER_JOB, by rule; they are told once, as one fast_refused_sum, when the job is accounted
        self.refused_last = None    # (ms after the job started, the words asked) of the last of them      # H7 item 1: what it started on, ms after the ear's offset, ``usage``, the refusals told, a release took it as it was
        self.cancelled = threading.Event()
        self.lock = threading.Lock()
        self.buffer, self.sent, self.first_at = '', 0, None
        self.outcome = self.reason = None
        self.released = None                  # {'qid', 'turn', 'epoch'} once a question has asked for it
        self.twin, self.args = False, None    # w5-tail: it is the second job of its question; what it was made of (text, material, also)
        self.accounted = self.told = False
        self.walk, self.asked = None, None    # the roads of its question (``reserve_text.Walk``) and the moment the question asked for it (``release``)

    @property
    def done(self):
        return self.outcome is not None

    def push(self, delta, now):
        with self.lock:
            if self.cancelled.is_set() or self.outcome is not None:
                return
            if self.first_at is None:
                self.first_at = now
            self.buffer += delta

    def finish(self, outcome, reason=None):
        with self.lock:
            if self.outcome is None:
                self.outcome, self.reason = outcome, reason

    @property
    def spoken(self):
        """The buffer as it may be said (``textutil.spoken_lead``)."""
        return spoken_lead(self.buffer, '', self.outcome is not None)      # no question: the run-up is cut by its own words only (as the fast text's rule did)

    def take(self):
        with self.lock:
            text = self.spoken
            new, self.sent = text[self.sent:], max(self.sent, len(text))
            return new


class FastText:
    """The channel of ONE call: at most one job, the breaker, the match of a prepared job with the question that opens. Everything but the job threads
    runs on the transport's loop (``poll`` on its tick). ``stream(request, cancelled)`` is the call (``codex_stream``; a scripted fake in the tests), ``instructions()`` the
    prompt of a job, ``history()`` the call's exchanges (history entries), ``in_play()`` the answer in play as ``(question, answer)`` or None, ``wake()`` is thread-safe and asks
    the loop to ``poll``."""

    def __init__(self, stream, *, instructions, history, in_play=None, clock=None, wake=None, strip=None, report=None, ear_ended=None):
        self.stream, self.instructions, self.history, self.strip = stream, instructions, history, strip
        self.report, self.ear_ended = report, ear_ended or (lambda: None)      # H7 item 1: the call trace (``CallTrace.note``), the last offset of the ear
        self.carry = lambda: ''         # U14-S8: the recap of earlier calls (always); '' keeps the prompt byte-identical
        self.lang_line = lambda: ''     # U19-S4: set by ``for_call``; '' for a Russian turn
        self.keep_words = 2       # U15-S4: a job whose question has only a chatter prefix more is kept (always, a rule of the channel); the longest chatter prefix, in words
        self.wide = False         # H7: ``prepare_wide`` (``for_call``)
        self.live = False         # ``live_first``, read the same way: a job serves a question only when it was asked all of it (``heard_all``)
        self.answered = None      # c16: (qid, what the job of that question was asked): ``asked_of``
        self.room, self.whole = PREPARE_JOBS, False      # new prepared jobs in one breath; c16 (``ear_job``): EAR_JOBS, and a job is read as ``wide_refusal`` does with ``whole``
        self.in_play = in_play or (lambda: None)
        self.clock = clock or time.monotonic
        self.wake = wake or (lambda: None)
        self.job = None
        self.spare = None         # H7 item 5: the second place: a prepared job kept beside ``job`` (``_prepare_wide``). Only with ``wide``: otherwise H2's ruling of one job stands
        self.breath, self.spent = None, 0     # H7: the breath the controller says it is, and the new jobs it has had
        self.off, self.count, self.closed = False, 0, False      # off: out for the call (``shutdown``)
        self._refused_said, self._replaced = False, False      # h31 (F20): the refusal was handed on as provisional text; a real text has replaced it
        self.twin, self._refuse = None, False
        self.refuse_at = None      # U20-S6: a callable, the controller's deadline of the refusal; None: counted from the job's question (``release``)
        self.due = None            # hold8: a callable, when the listener's decision on the open question is due (``ControlledMedia.decision_due``); the walk of the roads gets what is left of it. None: the roads' own times      # the second job of the open question, the honest refusal to hand on
        self.cloud_answer = lambda: False      # always-answer: the cloud already has its own answer to the open question (``for_call`` sets it); dead roads then hand the question back instead of the refusal. No cloud: always False
        self._stream_closed = False
        self._voiced = None      # the qid whose word the controller got from the job (always-answer: the winner of that question stays)
        self.roads = self.stream = stream if callable(getattr(stream, 'step', None)) else Roads(stream, None, clock=self.clock)      # one road: whatever the stream is (a test's fake included) the roads own it, ``_walk_roads`` decides
        self._spent = None         # always-answer: the qid whose roads were all found dead: its release is 'off' (the question goes on to the cloud), the next question tries the roads again

    # -- the call's side (loop) ----------------------------------------------------------------------------------------------------
    def warm(self):
        """T1 item 2: the call opened, the transport prepares itself in the background (client, TLS, sign-in) and keeps the connection warm. Returns at once; whatever goes wrong there changes nothing."""
        warm = getattr(self.stream, 'warm', None)
        if warm is None or self.off or self.closed:
            return
        try:
            warm()
        except Exception:                 # noqa: BLE001 - the first job goes as it would have
            pass

    def _close_stream(self):
        """The client lives as long as the call: closed once, with the channel (or when the breaker puts it out for the call)."""
        if self._stream_closed:
            return
        self._stream_closed = True
        close = getattr(self.stream, 'close', None)
        if close is not None:
            try:
                close()
            except Exception:             # noqa: BLE001
                pass

    # -- the controller's side (loop) ----------------------------------------------------------------------------------------------
    def prepare(self, text, on='ear', breath=None):
        """The ear heard a question: start a job for its text unless one runs. A prepared job that is another question (or too old, or failed) is
        replaced; a released job is the answer of an open question and is never touched. True when a job for this text runs. ``on``: what it starts on, for the journal."""
        if self._blocked():
            return False
        job = self.job
        if self.wide:
            return self._prepare_wide(text, on, breath)
        if job is not None:
            if job.released is not None:                      # the answer of an open question, even one whose text has not been handed on yet
                return False
            if self._fits(job, text):
                return True
            self._replace(job)
        self.job = self._start(text, on=on)
        return True

    def release(self, *, qid, turn, epoch, question, material='', also=''):
        """A question opened: ``adopted`` (the prepared job is this question's), ``started`` (a job on ``question``; a prepared one that did not match is
        cancelled) or ``off``. A job with a ``material`` (sources, the no-source instruction) is never a prepared one. ``also``: the ear's words of it (``build_request``); a prepared job has them by itself."""
        if self._blocked():
            return 'off'
        if self._spent == qid:      # its roads are dead already: no second round of them for the retry of the controller
            return 'off'
        self._drop_twin()
        self._refuse, self._refused_said, self._replaced = False, False, False
        self._voiced = None      # a release is a new job (a new question, or the retry of a job that failed after its word): its roads are decided anew
        released = {'qid': qid, 'turn': turn, 'epoch': epoch}
        job = self.job
        if job is not None and not material and not job.has_material and self._fits(job, question):
            self._adopted(job, released)
            self._drop_spare()
            self.answered = (qid, job.text)
            return 'adopted'
        spare = self.spare
        if spare is not None and not material and not spare.has_material and self._fits(spare, question):
            if job is not None:
                self._replace(job)
            self.job, self.spare = spare, None
            self._adopted(spare, released)
            self.answered = (qid, spare.text)
            return 'adopted'
        self._drop_spare()
        if job is not None and self.wide and job.released is None and not material and job.outcome in (None, 'ok'):
            self.job, self.spare = None, job      # it may yet be what the final goes on to say: kept until the job on the final has given its text (``poll``)
        elif job is not None:
            self._replace(job)
        self.job = job = self._start(question, material, also)
        job.released, job.asked = released, self.clock()
        self.answered = (qid, question)
        return 'started'

    def spend(self):
        """U107: what this call asked of the first road and of the reserve and what their answers told it cost, by numbers (``Roads.spend``); written to the call trace at the close. Never throws."""
        try:
            return self.roads.spend()
        except Exception:      # noqa: BLE001
            return {}

    def asked_of(self, qid):
        """c16: what the job that answers ``qid`` was asked, over or not; None when there was none. Only a look."""
        return self.answered[1] if self.answered and self.answered[0] == qid else None

    def prepared(self, text):
        """H4 rule 2: what the job prepared on ``text`` has said so far, ``(its text, whether it is over)``; None when no such job runs. Only a look: its text reaches the controller after a release."""
        if self.off or self.closed:
            return None
        job = next((job for job in (self.job, self.spare) if job is not None and self._fits(job, text)), None)
        if job is None:
            return None
        with job.lock:
            return job.spoken, job.outcome == 'ok'

    def _blocked(self):
        """The channel does not take a job now: out for the call or closed. The pause of the quota is the first road's, which rests by itself; the other roads are still there."""
        return self.off or self.closed

    def drop(self):
        """The question went another way (the lookup, the reference base): what was prepared is not wanted."""
        job = self.job
        if job is not None and job.released is None:
            self._replace(job)
        self._drop_spare()

    def retain(self, *qids):
        """A released job of any other final than ``qids`` is cancelled (a new question, «стоп» with nothing to pause)."""
        job = self.job
        if job is not None and job.released is not None and job.released['qid'] not in qids:
            self._replace(job)

    def finish(self, turn):
        """The controller does not want the rest of the job that fed ``turn``."""
        job = self.job
        if job is not None and job.released is not None and job.released['turn'] == turn:
            self._cancel(job)

    def poll(self):
        """The events of the released job for the controller, in order: ``{'turn', 'qid', 'kind': 'text' | 'done' | 'failed', 'text'}``. Applies the
        bounds (the first text, the whole job) and settles the account of a job that is over."""
        self._mind_spare()
        job = self.job
        if job is None:
            return []
        now = self.clock()
        self._walk_roads(now)
        job = self.job
        if job.outcome is None and now - job.started >= WHOLE_S:
            self._expire(job, 'whole')
        outcome = job.outcome                 # read BEFORE the text: everything the thread pushed precedes its outcome
        events = []
        if self._refuse and job.released is not None:                 # w5-tail: nothing by the limit: the refusal in place of silence. h31 (F20): provisional, no end: both jobs stay till reserve_text.GIVE_UP_S and a real text replaces it
            self._refuse, self._refused_said = False, True
            events.append({**self._ids(job.released), 'kind': 'text', 'text': reserve_text.REFUSAL, 'provisional': True})
        if job.released is not None:
            released = job.released
            new = job.take()
            if new:
                self._voiced = released['qid']
                replaces = self._refused_said and not self._replaced
                self._replaced = self._replaced or replaces
                events.append({**self._ids(released), 'kind': 'text', 'text': new, **({'replaces': True} if replaces else {})})
            if outcome in ('error', 'timeout') and not job.told and job.first_at is None and self.twin is not None and self.twin.outcome is None:
                outcome = None                # h31 (F21): the first job failed with no text while the twin runs (it may speak, or be let go at reserve_text.GIVE_UP_S): the tail step lets the twin win; no failed, the job stays
            if outcome is not None and not job.told and job.first_at is None and outcome in ('error', 'timeout') and self._spent != released['qid']:
                outcome = None                # the thread ended with no word between the step and this read: no failed before the owner said dead (``_spent``), or the retry of the controller would walk the roads twice; the next poll tells it
            if outcome is not None and not job.told:
                job.told = True
                if outcome in ('ok', 'error', 'timeout'):
                    spoken = outcome == 'ok' or (self._refused_said and not self._replaced)      # h31: the refusal said and nothing came after it: it stands, the turn ends (not a failure that asks again)
                    events.append({**self._ids(released), 'kind': 'done' if spoken else 'failed', 'text': ''})
        if job.outcome is not None:
            self._account(job)
        if outcome is not None:
            if job.released is not None and job.told:
                self.job = None
                self._drop_twin()
        return events

    def close(self):
        self.closed = True
        self._drop_spare()
        self._drop_twin()
        job, self.job = self.job, None
        if job is not None:
            self._cancel(job)
            self._account(job)
        self._close_stream()

    def shutdown(self):
        """The channel is out for the rest of the call (a bug on the loop's side)."""
        self.off = True
        self.close()

    # -- the jobs -----------------------------------------------------------------------------------------------------------------
    @staticmethod
    def _ids(released):
        return {'turn': released['turn'], 'qid': released['qid']}

    def _played(self):
        try:
            return self.in_play()
        except Exception:                 # noqa: BLE001 - with no context it is still a job
            return None

    def _adopted(self, job, released):
        """A release takes a prepared job. ``ms``: how long it has run; ``ready_ms``: how long its first text has been waiting (None: it has none yet): what a job on the final would have cost."""
        job.released, job.adopted = released, True
        now = job.asked = self.clock()
        self.note('fast_adopted', job=job.number, on=job.on, ms=round((now - job.started) * 1000), ready_ms=None if job.first_at is None else round((now - job.first_at) * 1000))

    def _prepare_wide(self, text, on, breath):
        """H7 item 5 (С3): two places. A text one of them fits runs already; a new one takes a place, and the older prepared job moves to the second one, for what the final may say. The answer of an open question stays where it is, and what is prepared beside it waits."""
        job, spare = self.job, self.spare
        if (spare is not None and self._fits(spare, text)) or (job is not None and job.released is None and self._fits(job, text)):
            return True
        if job is not None and job.released is not None and job.outcome in (None, 'ok') and not job.has_material and refusal(job.text, text, strip=self.strip) is None:
            return True                   # w3-skeptic S2: the answer in flight is this text's: no second request
        if breath is not None:            # the ear's own preparation (H4) is no count of this
            if breath != self.breath:
                self.breath, self.spent = breath, 0
            if self.spent >= self.room:
                return False
            self.spent += 1
        self._drop_spare()
        if job is None:
            self.job = self._start(text, on=on)
        elif job.released is not None:
            self.spare = self._start(text, on=on)
        else:
            self.spare, self.job = job, self._start(text, on=on)
        return True

    def _cloud_has(self):
        """always-answer: the cloud has an answer of its own to the open question. Never throws (the channel never drops a call): any error is False."""
        try:
            return bool(self.cloud_answer())
        except Exception:      # noqa: BLE001
            return False

    def _walk_roads(self, now):
        """always-answer, on ``poll``: ``Roads.step`` looks at the walkers of the open question (the released job and the second one) and says: who won, who is let go (a stall), the next road, or that every road is dead.
        A walker stands from the moment it took its road (``Walk.where``), not from the release. A silent loss of a road (``Roads.lost``) is said here only: a stall, the loser of the race, the walkers flying at dead. The guard's hedge, win, cancel and expire are not done here (one owner decides the roads); of it only the refusal is taken (it says the honest sentence at ``reserve_text.REFUSE_AFTER_S`` when all are silent)."""
        job, twin = self.job, self.twin
        if job.released is None or job.walk is None or job.outcome == 'cancelled':      # a job the controller let go (``finish``, ``release`` of a new question) is not asked again on a new road
            return
        qid = job.released['qid']
        if self._voiced == qid:      # one speaker per question: a word of the job reached the controller, so it stays the one; the second walker is let go whatever it did (flying or ok) and ``step`` is not asked
            if twin is not None:
                if twin.first_at is None and twin.outcome is None:
                    self.roads.lost(twin.walk, twin.cancelled, now)
                self._drop_twin()
            return
        has = self._cloud_has()      # U134/arrival order: the give-up time of a question is ONE value by whether the cloud has an answer, not by which came first, the sentence or the cloud's text (it was GIVE_UP_S after a sentence, ALL_DEAD_S before it)
        # A word is shown to the owner only if it was heard: the job's (it is the one the controller gets), or of a walker still flying or ok (it wins). The word of a twin that broke (or was let go) went nowhere: for the owner
        # that is a walker refused with no word, so the question goes on (the next road, or dead) and never waits on a failure nobody will tell. The job that spoke and broke keeps its word: its failure is its own, no road is asked twice.
        seen = [Tried(j.number, j.cancelled, j.started, None if j is not job and j.outcome not in (None, 'ok') else j.first_at, j.outcome) for j in (job, twin) if j is not None]
        asked = job.asked if job.asked is not None else job.started
        give_up = reserve_text.ALL_DEAD_S if has else reserve_text.GIVE_UP_S
        try:
            due = self.due(qid) if self.due is not None else None
        except Exception:      # noqa: BLE001 - the channel never drops a call
            due = None
        refuse_at = (self.refuse_at(qid) if self.refuse_at is not None else None) or asked + reserve_text.REFUSE_AFTER_S      # the honest sentence counts from the question OF THIS JOB (fix5: not the older open one), not from the job that is left
        sentence = not has and (job.walk.refused or now >= refuse_at)      # fix5 (F20): the provisional sentence is (or is now) the decision of the question at its due
        if due is not None and not sentence:
            give_up = min(give_up, max(due - asked, 0.0))      # hold8: only what is left of the question's bound (a hold before the job, the ear's 4 s, is spent from it). fix5 (F20): once the sentence is the decision (a final after the due: at once) the walk goes on to GIVE_UP_S, and a real text takes the sentence's place
        acts = list(self.roads.step(now, seen, job.walk, asked=asked, give_up=give_up, cloud_silent=not has, refuse_at=refuse_at))
        dumb = all(one.outcome is not None and one.first_at is None for one in seen) and not any(act in ('next', 'dead') for act, _ in acts)      # by what the step saw: nobody flies, no word is heard and the owner decided nothing
        for act, number in acts:
            job, twin = self.job, self.twin
            if act == 'refuse':
                self._refuse = True
                logger.info('echo-sync fast_text refusal job=%s after_s=%.1f', number, now - asked)
                self.note('fast_refusal', job=number, ms=round((now - job.started) * 1000))
            elif act == 'win' and twin is not None and number == twin.number:
                self.twin.released, job.released = job.released, None
                self.job, self.twin = self.twin, job
                self.note('fast_twin_won', job=self.job.number, ms=round((now - self.job.first_at) * 1000))
            elif act == 'cancel':
                loser = next((j for j in (self.job, self.twin) if j is not None and j.number == number and j is not self.job), None)
                if loser is not None:
                    if loser.first_at is None:
                        self.roads.lost(loser.walk, loser.cancelled, now)      # it lost the race with no word: silent on its road if it stood there NEXT_ROAD_S
                    self.twin = None
                    self._cancel(loser)
                    self._account(loser)
            elif act == 'stall':
                gone = next((j for j in (job, twin) if j is not None and j.number == number), None)
                if gone is not None:
                    self.roads.lost(gone.walk, gone.cancelled, now)      # let go for its silence (a stall, or the time to give up): a loss of its road
                    self._expire(gone, 'stall')
                    self._account(gone)
                    if gone is twin:
                        self.twin = None
                    elif twin is not None and twin.outcome is None:      # the released job is let go and the second one flies: it is the answer now
                        twin.released, job.released = job.released, None
                        self.job, self.twin = twin, None
                    elif twin is not None:
                        self._drop_twin()
            elif act == 'next':
                walker = self._start(*job.args, on='road', walk=job.walk)
                walker.asked = job.asked
                if job.outcome is not None and job.first_at is None:      # the released job is over with no word: the next road is its place
                    walker.released, job.released = job.released, None
                    self._account(job)
                    self.job = walker
                else:
                    self._drop_twin()
                    walker.twin, self.twin = True, walker
                self.note('fast_next_road', job=walker.number, ms=round((now - walker.asked) * 1000))
            elif act == 'dead':
                self._spent = qid
                for j in (self.job, self.twin):
                    if j is not None and j.outcome is None:
                        self._expire(j, 'dead')
                self.note('fast_roads_dead', job=self.job.number if self.job is not None else None, ms=round((now - (job.asked or job.started)) * 1000))
        if dumb and self._spent != qid:      # insurance, whatever the cause: a question nobody flies for, with no word, that the owner left undecided is dead at once, or the failure of its job would be held for ever
            self._spent = qid
            logger.warning('echo-sync fast_text roads=dead reason=no_decision after_s=%.1f', now - (job.asked if job.asked is not None else job.started))
            self.note('fast_roads_dead', job=job.number, ms=round((now - (job.asked if job.asked is not None else job.started)) * 1000))

    def begun(self):
        """Has a job of the open question its first word (``first_at``)? The controller's silence timer waits for a job that has begun, not for one that is silent past ``FIRST_TEXT_S``."""
        return any(j is not None and j.first_at is not None and j.outcome in (None, 'ok') for j in (self.job, self.twin))

    def _drop_twin(self):
        twin, self.twin = self.twin, None
        if twin is not None:
            self._cancel(twin)
            self._account(twin)

    def _drop_spare(self):
        spare, self.spare = self.spare, None
        if spare is not None:
            self._cancel(spare)
            self._account(spare)

    def _mind_spare(self):
        """H7 item 5, on ``poll``: the kept job has its bounds as any other, and it goes once the job on the final, begun after it, has given its text. It is never polled for text: only a release makes it the answer."""
        spare, job = self.spare, self.job
        if spare is None:
            return
        now = self.clock()
        if spare.outcome is None and spare.first_at is None and now - spare.started >= reserve_text.GIVE_UP_S:      # F2: the roads own the silence of a job (``Roads.step``), the kept one stands as long as they let a job stand, not FIRST_TEXT_S
            self._expire(spare, 'first_text')
        elif now - spare.started >= WHOLE_S:
            self._expire(spare, 'whole')
        if spare.outcome is not None:
            self._account(spare)
        if spare.outcome not in (None, 'ok') or (job is not None and job.released is not None and job.first_at is not None and job.number > spare.number):
            self._drop_spare()

    def _why_not(self, job, text):
        """The rule that keeps the prepared ``job`` from serving ``text``, None when none does: it is not released yet and has not failed, it is not too old, the same answer is in play, it is the same question (``refusal``)."""
        if job.released is not None:
            return 'released'
        if job.outcome not in (None, 'ok'):
            return 'failed'
        if self.clock() - job.started > WHOLE_S:
            return 'old'
        if job.played != self._played():
            return 'played'
        if not self.wide:
            return refusal(job.text, text, strip=self.strip)
        rule = wide_refusal(job.text, text, strip=self.strip, whole=self.whole)
        return 'words' if rule is None and self.live and not heard_all(job.text, text, strip=self.strip) else rule

    def _fits(self, job, text):
        """May the prepared ``job`` serve ``text``? H7 item 1: when not, the rule is told once: to the log by its name, to the call trace with the words (it keeps them anyway)."""
        rule = self._why_not(job, text)
        if rule == 'words' and keep_chatter(job.text, text, self.keep_words, strip=self.strip) and ('keep', text) not in job.refused:
            job.refused.add(('keep', text))       # U15-S4: counted by the same note cap as a refusal (U07-S4)
            if len(job.refused) > REFUSED_NOTES_PER_JOB:
                job.refused_over['keep'] = job.refused_over.get('keep', 0) + 1
                job.refused_last = (round((self.clock() - job.started) * 1000), str(text)[-300:])
            else:
                self.note('fast_keep', job=job.number, on=job.on, heard=job.text[-300:], asked=str(text)[-300:], ms=round((self.clock() - job.started) * 1000))
        if rule == 'words' and keep_chatter(job.text, text, self.keep_words, strip=self.strip):
            return True
        if rule and (rule, text) not in job.refused:
            job.refused.add((rule, text))
            logger.info('echo-sync fast_text refused job=%s rule=%s on=%s', job.number, rule, job.on)
            if len(job.refused) > REFUSED_NOTES_PER_JOB:      # U07-S4: the single owner of this log: the first few in full, then a count per rule (589 rows once ate the end of a trace)
                job.refused_over[rule] = job.refused_over.get(rule, 0) + 1
                job.refused_last = (round((self.clock() - job.started) * 1000), str(text)[-300:])
                return False
            self.note('fast_refused', job=job.number, rule=rule, on=job.on, heard=job.text[-300:], asked=str(text)[-300:], ms=round((self.clock() - job.started) * 1000))
        return rule is None

    def note(self, ev, **fields):
        """A line of the call trace. It can never touch a call."""
        if self.report:
            try:
                self.report(ev, **fields)
            except Exception:             # noqa: BLE001
                pass

    def _since_ear(self):
        """How long ago, in ms, the ear heard the last speech end; None when it has not."""
        try:
            ended = self.ear_ended()
            return None if ended is None else round((self.clock() - ended) * 1000)
        except Exception:                 # noqa: BLE001
            return None

    def _start(self, text, material='', also='', on='final', walk=None):
        self.count += 1
        try:
            try:
                instructions = self.instructions(text, self.history())     # w5-material: a host that picks the material by the question
            except TypeError:
                instructions = self.instructions()
        except Exception:                 # noqa: BLE001 - the brain alone
            instructions = BRAIN_POLICY
        try:
            line = self.lang_line()          # U19-S4: the language line of the turn; '' for Russian, so the prompt stays byte-identical
            instructions = (instructions + chr(10) * 2 + line) if line else instructions
        except Exception:                 # noqa: BLE001
            pass
        try:
            carry = self.carry()             # U14-S8: stable for the whole call, so the prompt cache holds
            instructions = (instructions + chr(10) * 2 + carry) if carry else instructions
        except Exception:                 # noqa: BLE001
            pass
        try:
            history = self.history()
        except Exception:                 # noqa: BLE001
            history = []
        if getattr(self, 'card', None): instructions, history = self.card(self, text, instructions, history)      # V6 memory (v6_memory.py, set by the host, always): never raises, returns both as they came when it changes nothing
        played = self._played()
        job = Job(self.count, text, build_request(text, instructions=instructions, history=history, material=material, played=played, also=also), self.clock(), material, played, on, self._since_ear())
        job.args = (text, material, also)
        job.walk = walk or Walk(job.request)
        if walk is None:
            job.walk.screen = not material and not played and not doubts(text) and not asks_by_form(text)      # U50: a final with no form of a question is asked of a reserve road in the short form first
        threading.Thread(target=self._run, args=(job,), name='echo-fast-text', daemon=True).start()
        return job

    def _run(self, job):
        try:
            for delta in self.stream(job.request, job.cancelled, job.walk):
                if job.cancelled.is_set():
                    break
                if isinstance(delta, dict):       # H7 item 1: what ``response.completed`` says it cost
                    job.usage = delta.get('usage')
                    continue
                job.push(delta, self.clock())
                self._wake()
            job.finish('cancelled' if job.cancelled.is_set() else 'ok')
        except BaseException as error:    # noqa: BLE001 - a daemon thread: whatever happens is the job's outcome
            job.finish('error', reason_of(error))
        finally:
            self._wake()

    def _wake(self):
        try:
            self.wake()
        except Exception:                 # noqa: BLE001
            pass

    def _cancel(self, job):
        job.cancelled.set()
        job.finish('cancelled')

    def _expire(self, job, reason):
        job.cancelled.set()
        job.finish('timeout', reason)

    def _replace(self, job):
        if job is self.job:
            self._drop_twin()
        self._cancel(job)
        self._account(job)
        if self.job is job:
            self.job = None

    def _account(self, job):
        """Once per job that is over: the log line (numbers only) and the breaker."""
        if job.accounted or job.outcome is None:
            return
        job.accounted = True
        chars = len(job.buffer)
        ttft = None if job.first_at is None else round((job.first_at - job.started) * 1000)
        logger.info('echo-sync fast_text job=%s ttft_ms=%s chars=%s outcome=%s reason=%s released=%s', job.number, ttft, chars, job.outcome,
                    job.reason or '-', int(job.released is not None))
        if job.refused_over:
            self.note('fast_refused_sum', job=job.number, rules=dict(job.refused_over), last_t=job.refused_last[0], last_asked=job.refused_last[1])
        self.note('fast_job', job=job.number, on=job.on, after_ear_ms=job.after_ear, ttft_ms=ttft, chars=chars, outcome=job.outcome, reason=job.reason or '-', released=int(job.released is not None), adopted=int(job.adopted),
                   first=job.buffer[:80], **(job.usage or {}))
        # the roads own the verdict on a road (its rest, its stalls), a silent loss of it is theirs (``_walk_roads`` -> ``roads.lost``): an interruption, a finish or a close of the call is none, and no failure puts the channel out


def _short_brain(instructions):
    from .brain_short import SHORT_POLICY      # noqa: PLC0415

    def short(*args):
        text = instructions(*args)
        return text.replace(BRAIN_POLICY, SHORT_POLICY) if isinstance(text, str) and BRAIN_POLICY in text else text
    return short


def _short_history(history):
    from .brain_short import short_history      # noqa: PLC0415 - imported here, not in the lambda: a failure shows at the start of the call (W14 item 2)
    return lambda: short_history(history())


def _optional(module, make):
    """W14 item 2: an optional part of the channel (``brain_short``, ``ws_transport``) that fails is left out, the log names the module; the night of
    06.11 a failed import of ``brain_short`` raised out of ``for_call`` and the whole call had no text channel."""
    try:
        return make()
    except Exception as error:      # noqa: BLE001 - whatever it is, the channel goes up without it
        logger.warning('Fast text optional part unavailable module=%s type=%s error=%s', module, type(error).__name__, error)
        return None


def _cloud_answer(controller):
    """The open question owns a valid, not retired, non-empty assistant turn that is not the job's own. A turn the cloud has begun but not
    finished counts (``_fast_hand_back`` takes any turn with text). Any error is False."""
    try:
        qid = controller.question_id
        return bool(qid) and any(t['role'] == 'assistant' and t['valid'] and controller.owners.get(t['id']) == qid and t['id'] not in controller.retired_assistants and t['id'] != controller.fast_turn
                                 and t['text'].strip() for t in controller.ledger.history())
    except Exception:      # noqa: BLE001
        return False


def for_call(settings, controller, *, credentials=None, instructions=None, wake=None, stream=None, clock=None, report=None):
    """The channel of one call, or None: off unless the profile's ``fast_text`` is ``"on"`` (read at the start of the call, like ``local_ear``). The
    host gives ``credentials`` (the Codex sign-in of the profile), ``instructions`` (``BRAIN_POLICY`` with the material of the call) and
    ``wake``; without a ``stream`` (a test's fake) and without credentials there is no channel."""
    resolved = resolve(settings)
    if resolved['fast_text'] != 'on':
        return None
    if stream is None:
        stream = _optional('codex_road', lambda: __import__(__package__ + '.codex_road', fromlist=['primary']).primary(resolved, credentials))      # the first road of the roads: the Codex route, in one file (U79)
        stream = _optional('reserve_text', lambda: __import__(__package__ + '.reserve_text', fromlist=['for_stream']).for_stream(stream)) or stream      # the one road: the first road with the reserve behind it (an empty one with no keys)
        if not stream:
            return None

    instructions, history = instructions or (lambda: BRAIN_POLICY), controller.fast_exchanges
    if resolved['brain_short'] == 'on':       # w10 item 13 (w9-brain N117/N118): the short BRAIN, substance first, and 3 exchanges of 200 chars
        instructions, history = _optional('brain_short', lambda: (_short_brain(instructions), _short_history(history))) or (instructions, history)
    channel = FastText(stream, instructions=instructions, history=history, in_play=controller.fast_in_play, clock=clock, wake=wake,
                       strip=lambda text: strip_fillers(text, controller.settings), report=report, ear_ended=lambda: controller.ear_ended)
    channel.cloud_answer = lambda: _cloud_answer(controller)
    controller.job_begun = channel.begun      # the timer of the listener's silence waits for a job that has a word
    channel.carry = controller.fast_carry      # U14-S8: the memory of earlier calls: always (the ledger is always there; '' when it has nothing); the topic of this call is the card of v6_memory
    channel.lang_line = lambda: _answer_instructions(controller.turn_lang.lang)      # U19-S4: the instruction follows the language of the turn, always (the probe of M7 -> the answer of M3)
    if resolved['local_ear'] == 'act':       # H4 rule 2 (the owner's rule, no key): with the ear acting the controller looks at the job prepared on it
        controller.prepared_job = channel.prepared
    def in_my_time(moment):      # a moment of the controller's clock as the channel's clock tells it (one clock in a call; a harness may run the two apart)
        def told(*args):
            at = moment(*args)
            return None if at is None else channel.clock() + (at - controller.clock())
        return told
    channel.refuse_at, channel.due = in_my_time(controller.refuse_deadline), in_my_time(controller.decision_due)      # hold8: the refusal is due before the question is dropped (end of its speech + 7.5), and the walk of the roads ends where the question's decision is due (end of its speech + 8): one bound for the whole chain, not 8 / 12 s after the job began
    for part in (stream, getattr(stream, 'http', None)):      # h31 (F21): the transport must not cut a job before the roads' own limit
        if part is not None and hasattr(part, 'first_text_s'):
            part.first_text_s = reserve_text.GIVE_UP_S
    if resolved['prepare_wide'] == 'on':      # H7, read the same way
        channel.wide = controller.prepare_wide = True
    channel.keep_words = resolved['keep_chatter_words']      # U15-S4
    if resolved['ear_job'] == 'on':           # c16, read the same way
        channel.room, channel.whole, controller.job_asked = EAR_JOBS, True, channel.asked_of      # ``controller.ear_job`` reads the same setting itself (ControlledMedia.modes)
    if resolved['live_first'] == 'on':        # read the same way: a job is read as ``wide_refusal`` does with ``whole``
        channel.whole, channel.live, controller.job_asked = True, True, channel.asked_of
    controller.witness_note = channel.note      # the cloud's reply is read against the job's answer on every call with a text channel: the verdicts go to the call trace by the channel's own line (a rule of the answer, no key; nothing is said)
    return channel
