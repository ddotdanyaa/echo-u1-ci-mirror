"""Pure turn classifier: what did one heard utterance mean for the answer that is waiting?

``analyze(text, state, bank, settings) -> Decision`` has no side effects (its one reader for a call is ``ControlledMedia._classify``). Kinds:

* ``ack``       the user repeated the current portion (exactly, or by Russian word stems);
* ``repeat``    "повтори", "ещё раз пожалуйста", "можно ещё раз": speak the same portion again, no advance, no model;
* ``stop``      "стоп", "хватит", "замолчи" and friends: forget the answer;
* ``question``  a new turn that replaces the waiting answer: a question, a clarification ("расскажи подробнее"),
                a "ли"-question, a change of topic;
* ``correction`` the answer was said to be wrong: "это неверно", "нет, я имел в виду ...";
* ``replay``    not a confirmation, but an attempt or "I did not hear" ("не расслышал", "что?", "а?", "как?"): speak the
                same portion again, no advance, no model;
* ``silent``    anything else; the position never changes.

The order of the decision, for every utterance (the first rule that applies wins; ``analyze`` marks each step):

1. a full repeat of the portion that waits is an ``ack`` (a repeat that merely LOOKS like a question or a command too);
2. ``stop``: the utterance is essentially a stop word (at most three words, all of them stop words);
3. an attempt at the portion (a part of it, or mostly it) is never a new question: ``replay`` / ``silent``;
4. a repeat request (``repeat``) or a hearing repair (``replay``, immediately);
5. a disagreement ("это неверно") or an explicit repair ("нет, я имел в виду ...");
6. a new turn: question, clarification, "ли"-question, change of topic; wave F (``_new_turn``): an indirect question inside a request
   or a complaint, the chat before a question dropped, a topic phrase while nothing waits - and a remark to the prompter about its own
   work is QUIET (``remark_to_prompter``);
7. everything else is silence.

While an answer waits for its confirmation, replacing it needs stronger evidence than
having nothing to lose: one stray word or a short noise never cancels it.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from collections import namedtuple

from .reference_kb import without_tail
from .settings import resolve
from rapidfuzz.distance import Indel
from .textutil import CONJUNCTIONS, MARKER_BASE, NUMBER_WORDS, PARTICLES, PREPOSITIONS, STOPWORDS, WORDS, norm_words, normalize, stems
from .user_intents import (AMBIGUOUS_WITHOUT_QUESTION_MARK, CERTAIN_WITHOUT_QUESTION_MARK, HESITATION_WORDS, STOP_WORDS,
                           clarification_request, disagreement, hearing_repair, is_repeat_request, is_stop, li_question,
                           pause_split, topic_change)

logger = logging.getLogger('echo-sync')
ACK, REPEAT, STOP, QUESTION, REPLAY, QUIET = 'ack', 'repeat', 'stop', 'question', 'replay', 'silent'
GREETING = 'greeting'
CORRECTION, CLARIFY_REPAIR = 'correction', 'clarify_repair'
REPAIR_PROMPT = 'Что именно нужно исправить?'

Decision = namedtuple('Decision', 'kind reason question prepared topic', defaults=(None,))      # ``topic``: the topic words of a return («вернёмся к <тема>», reason 'topic_change'), worked out once here and handed on: the engine's ``going_on`` reads it, never the text again
# The vocabulary of the verdicts' reasons, owned here (the one place; the engine and the controller import it): a try at the waiting portion (a part of it, a sloppy repeat; an uncertain «а?» / «что?», ``attempt_clarification``, is not one: noise),
# and the replays that are a REQUEST to hear the portion («не расслышал», «что?», a phrase of the clarification list: they end a pause like «повтори»).
ATTEMPT_REASONS = frozenset({'attempt_ru_alignment', 'attempt_shared_stem', 'attempt_repeat_cover'})
EXPLICIT_REPLAYS = frozenset({'replay_hearing_repair', 'attempt_clarification'})
_Evidence = namedtuple('_Evidence', 'strong reason asked prepared by_trigger')

_QUESTION_WORDS = (
    'что как почему зачем когда где куда откуда кто какой какая какие какое какого какому каким какую каком каких '
    'какими сколько чем чей чья чье чьи объясни расскажи покажи можно можешь нужно верно правда отчего чего чему '
    'кого кому кем каков какова каково каковы')
QUESTION_WORDS = frozenset(normalize(_QUESTION_WORDS).split())
IMPERATIVE = re.compile(r'\b(?:посчитай(?:те)?|объясни(?:те)?|назови(?:те)?|расскажи(?:те)?|раскрой(?:те)?|опиши(?:те)?|уточни(?:те)?|'
                        r'переформулируй(?:те)?|поясни(?:те)?|исправь(?:те)?|приведи(?:те)?|'
                        r'проверь(?:те)?|найди(?:те)?|поищи(?:те)?|сверь(?:те)?|сформулируй(?:те)?|'
                        r'помоги(?:те)?\s+(?:мне\s+|нам\s+)?(?:понять|вспомнить|разобраться)|'
                        r'дай(?:те)?\s+(?:определени[ея]|понятие|пример|характеристику|расшифровку|классификацию))\b', re.I)      # g1-ladder L1: «Дай определение Плана счетов»
VERIFY_IMPERATIVE = re.compile(r'^(?:проверь(?:те)?|найди(?:те)?|поищи(?:те)?|сверь(?:те)?)\b',re.I)
QUESTION_TAIL = re.compile(r'\b(?:что\s+это|что\s+такое|почему\s+так)\s*[.!?]*$', re.I)
# A bare named reference is a request only when the whole phrase is nominal;
# narrative continuations such as "статья 15 говорит..." are not requests.
REFERENCE_QUERY = re.compile(
    r'^(?:\d+(?:\.\d+)*(?:-[а-я]+)?\s+стать[яюеи]|стать[яюеи]\s+\d+(?:\.\d+)*(?:-[а-я]+)?)'
    r'\s+(?:(?:налогов\w*|уголовн\w*|гражданск\w*|трудов\w*|семейн\w*|'
    r'административн\w*|российск\w*)\s+)*(?:кодекс\w*|конституци\w*|закон\w*|нк|тк|гк|ук|коап|ск)'
    r'(?:\s+(?:рф|российской\s+федерации))?\s*[.!?]*$', re.I)
GREETINGS = frozenset({'привет', 'здравствуйте', 'добрый день', 'доброе утро', 'добрый вечер'})
# Wave F (F2): «Вопрос получается …», «Вопрос такой: …» - the word after «вопрос» belongs to the marker, not to the question.
EXPLICIT = re.compile(r'^\s*(?:(?:новый|следующий|другой)\s+)?вопрос\b(?:[\s:—–,-]*(?:получается|такой|следующий)\b)?[\s:—–,.-]*',
                      re.I)
REPEAT_COMMANDS = frozenset({'повтори', 'повторите', 'повтор', 'повторить', 'еще раз', 'repeat',
                             'повтори пожалуйста', 'повторите пожалуйста'})
_HEARING_REASON=r'(?:я\s+)?не\s+(?:расслышал[аи]?|услышал[аи]?)'
_REPEAT_WITH_REASON=re.compile(r'(?:(?:повтори(?:те)?|еще\s+раз)\s+(?:пожалуйста\s+)?'+_HEARING_REASON+r'|'+_HEARING_REASON+r'\s+(?:повтори(?:те)?|еще\s+раз)(?:\s+пожалуйста)?)')
_REPEAT_FOLDED=frozenset(value.replace(' ','') for value in REPEAT_COMMANDS)
_REPEAT_REASON_FOLDED=re.compile(_REPEAT_WITH_REASON.pattern.replace(r'\s+',''))

def _is_repeat_command(phrase):
    # Same exact letters, only ASR word boundaries differ. No fuzzy match,
    # dropped negations/numbers, or arbitrary trailing command text.
    folded=phrase.replace(' ','')
    return phrase in REPEAT_COMMANDS or bool(_REPEAT_WITH_REASON.fullmatch(phrase)) or folded in _REPEAT_FOLDED or bool(_REPEAT_REASON_FOLDED.fullmatch(folded))
STOP_COMMANDS = STOP_WORDS  # kept for old imports; ``is_stop`` decides ([lead]* CORE [adjunct]*, one to three cores)
# Root cause F3 (scenario sc03): «Нет, подождите, я хотел спросить про насекомое» was not a repair, so the stale «Восемь.» stayed the
# waiting portion. A spoken self-correction of the question, anchored at the start (reported speech is never one). W1F-C: any hold word
# may open it («Погоди, я имел в виду …», «Нет, постой, подожди, я хотел спросить …»), and it is read through the ASR view (fold_asr).
_REPAIR_PREFIX = re.compile(r'^(?:(?:нет|ой)\s+)*(?:(?:подожди(?:те)?|погоди(?:те)?|постой(?:те)?|стой(?:те)?|обожди|секунду|минуту)\s+)*'
                            r'(?:(?:я\s+)?(?:имел[аи]?\s+в\s+виду|хотел[аи]?\s+спросить|спрашивал[аи]?)|исправь(?:те)?|поправь(?:те)?)'
                            r'(?:\s+(.*))?$')
# A restatement lead-in before a repeat of the waiting portion (see analyze, step 1).
_ACK_LEAD_IN = re.compile(r'^\s*(?:значит|то\s+есть|итак|так\s+вот|в\s+общем)\s*[,:—–-]?\s+', re.I)
# H5 item 4 (class 17, n1_04 step 4): the speaker took a word back: «401 штук в месяц, нет, 400 штук в месяц» says what follows the last of these.
_TOOK_BACK = re.compile(r'(?<![\w-])(?:нет|вернее|то\s+есть|точнее|ой)(?![\w-])', re.I)


def self_corrected(text):
    """``(what was taken back, what stands)`` of an utterance with a self-correction: its last marker, with words on both sides of it; else None."""
    said = str(text or '')
    last = None
    for last in _TOOK_BACK.finditer(said):
        pass
    if last is None or not re.search(r'\w', said[:last.start()]) or not re.search(r'\w', said[last.end():]):
        return None
    return said[:last.start()], said[last.end():].strip(' ,.;:!?…—–-')


# H5 item 6: what an utterance that goes on stops on (ECHO_RESEARCH_RESULTS_20261104/02_P2_RUSSIAN_TURN_COMPLETION.md, section 5): evidence for a bounded hold, never a veto, and read on the words alone, with no question in hand.
_OPEN_ENDS = frozenset({'а вот', 'а если', 'потому что', 'так как', 'то есть', 'как бы', 'в смысле', 'имею в виду', 'в виду', 'а также', 'а именно', 'не только', 'и еще', 'а потом', 'думаю что', 'нужно узнать', 'хочу понять', 'хочу узнать'})     # w10 item 7 (w9-open-tail GAPS)
_OPENS_A_CLAUSE = frozenset({'если', 'хотя', 'чтобы'})
_NUMBERED = frozenset(normalize('статья статьи статье статью пункт пункта пункте часть части глава главы главе номер счет счета счете билет билета вариант тема задача').split())
_OPERATORS = frozenset(normalize('плюс минус умножить разделить делить поделить').split())
_WHICH = frozenset(normalize('каком какой какая какую каких каким какого какое').split())


def _stands_alone(words):
    """``words`` end on a number: is it complete without a unit? An operand («пять на пять», «семь плюс восемь»), a number of something («статья 21», «счёт 71»), a year."""
    if words[-1].isdigit() and 1000 <= int(words[-1]) <= 2100:
        return True
    number = lambda word: word.isdigit() or word in NUMBER_WORDS
    at = len(words) - 1
    while at >= 0 and number(words[at]):
        at -= 1
    if at < 0:
        return False
    return words[at] in _NUMBERED or words[at] in _OPERATORS or (words[at] == 'на' and at > 0 and (number(words[at - 1]) or words[at - 1] in _OPERATORS))


def _clause_ends_a_head(words, at):
    """E29.1: a clause of «если/чтобы/хотя» that stands AFTER a head of its own is the tail of a sentence already said: nothing waits for a main clause. A head is two words (lead-ins
    «а/и/ну/вот/…» do not count) that open with a question word, a verb of asking (``IMPERATIVE``) or «это»: «что будет если не платить налоги», «это нужно чтобы платить меньше».
    A preposition, «случае/допустим/пусть/представь/тем более» or a feeling («мне интересно») opens no head: «в случае если я продам квартиру», «допустим у меня есть квартира если …»
    wait for their main clause and stay open. The clause itself must have two words."""
    lead_ins = (PARTICLES | CONJUNCTIONS | HESITATION_WORDS | _HEAD_LEADS) - QUESTION_WORDS      # «что» is a conjunction and a question word: here it opens a question
    head = [word for word in words[:at]]
    while head and head[0] in lead_ins:
        head.pop(0)
    if len(head) < 2 or len(words) - at - 1 < 2:
        return False
    first = head[0]
    return first in QUESTION_WORDS or first == 'это' or bool(IMPERATIVE.match(first))


def open_tail(text):
    """Does ``text`` stop where an utterance goes on: on a conjunction or a preposition, on «а вот», «потому что», on a number with no unit, in a clause of «если» with nothing that goes on from it? A last question word is no
    open tail («а почему это»), and a question after «если» closes it."""
    words = norm_words(text)
    if not words:
        return False
    if words[-1] == 'так' and question_complete(text):
        return False
    if (words[-1] in PREPOSITIONS | CONJUNCTIONS and words[-1] not in QUESTION_WORDS) or ' '.join(words[-2:]) in _OPEN_ENDS or ' '.join(words[-3:]) in _OPEN_ENDS:
        return True
    if words[-1] in _OPERATORS or (words[-1] == 'номер' and len(words) > 1 and words[-2] in _NUMBERED) or (len(words) > 1 and words[-2] in PREPOSITIONS and words[-1] in _WHICH):
        return True                       # w10 item 7: «семь плюс», «статья номер», «в каком»: the number or the noun is still to come
    opens = [at for at, word in enumerate(words) if word in _OPENS_A_CLAUSE]
    if opens and not (frozenset(words[opens[-1] + 1:]) & (QUESTION_WORDS | {'то'})) and not _clause_ends_a_head(words, opens[-1]):
        return True
    return (words[-1].isdigit() or words[-1] in NUMBER_WORDS) and not _stands_alone(words)


def question_complete(text):
    """A question that carries «?» or is only an interrogative word (а/и/так/же/именно allowed: «Почему?», «Как?», «А если?», «Почему так», «Почему именно») is complete as asked: there is nothing to wait for. An unfinished head («…сразу в») never carries «?» in the field logs.
    The one reading of it: the continuation rule (``ControlledMedia._goes_on``, the wait ``_holding``) asks it of the question's text."""
    words = norm_words(text)
    return '?' in text or (bool(words) and set(words) <= QUESTION_WORDS | {'а', 'и', 'так', 'же', 'именно'} and bool(QUESTION_WORDS.intersection(words)))


# one-research (EOT-RU, research/OPEN_REPOS_FUNCTIONS.md): the end of a turn by its text in three values, the probe the release wait reads (livekit/agents
# turn detector: «complete» -> min_delay, «not» -> max_delay; RealtimeVoiceChat turndetect.py: the pause follows the ending). OPEN is ``open_tail`` and nothing else;
# CLOSED is a question asked whole: a «?» of the cloud's text, or a question form at the head (a question word, «в каком», «ли», a verb of «объясни») with a word of
# content after it and at the end; UNSURE is the rest (a statement, a bare question word, a hesitation at the end), today's wait.
OPEN, CLOSED, UNSURE = 'open', 'closed', 'unsure'
_EN_ASKS = frozenset('what how why when where who whom whose which can could is are was were do does did should will would may'.split())
_HEAD_LEADS = frozenset({'а', 'и', 'ну', 'так', 'вот', 'скажи', 'скажите', 'подскажи', 'подскажите', 'еще', 'слушай', 'слушайте'})
_EMPTY = (QUESTION_WORDS | PREPOSITIONS | CONJUNCTIONS | PARTICLES | HESITATION_WORDS | _EN_ASKS | _HEAD_LEADS
          | frozenset(normalize('такое такой такая такие это этот эта эти есть мне нам вам тебе вы ты я он она они мы там тут здесь the a an it this that to of').split()))


def turn_end(text):
    """OPEN | CLOSED | UNSURE: does ``text`` end a turn? Pure, microseconds, no model; a doubt is UNSURE (today's wait), never CLOSED."""
    words = norm_words(text)
    if not words:
        return UNSURE
    if str(text).rstrip().endswith('?') and len(words) >= 3 and words[-1] == 'да' and ',' in str(text).rstrip()[-6:]:
        return CLOSED                     # a tag question «это правда, да?»: «да» reads as a conjunction to open_tail, but the cloud's «?» closes it
    if open_tail(text):
        return OPEN
    if str(text).rstrip().endswith('?') and len(words) >= 2 and words[-1] not in HESITATION_WORDS:
        return CLOSED                     # the cloud's «?»: «это правда, да?», «это так, верно?»
    if words[-1] in _EMPTY and not words[-1].isdigit():
        return UNSURE                     # «что такое ну», «как это э-э», «расскажи»: the speaker stalls or the object is still to come
    head = 0
    while head < len(words) - 1 and words[head] in _HEAD_LEADS:
        head += 1
    first = words[head]
    asks = (first in QUESTION_WORDS or first in _EN_ASKS or bool(IMPERATIVE.match(first))
            or (first in PREPOSITIONS and head + 1 < len(words) and words[head + 1] in QUESTION_WORDS) or li_question(words[head:]))
    content = [w for w in words[head + 1:] if w not in _EMPTY]
    return CLOSED if asks and content else UNSURE


def waiting_portion(state):
    """The portion the user has to repeat now; ``None`` when no answer waits for a confirmation."""
    if not state or state.get('completed') or state.get('pending_turn'):
        return None
    chunks, index = state.get('chunks') or [], state.get('chunk_index', 0)
    return chunks[index] if 0 <= index < len(chunks) else None


def _skip_fillers(words, fillers):
    i = 0
    while i < len(words) and words[i] in fillers:
        i += 1
    return words[i:]


def strip_fillers(text, settings=None):
    """The text from its first word that is not a leading filler ("ну а что такое X" -> "что такое X")."""
    fillers = frozenset(resolve(settings)['fillers']) | HESITATION_WORDS
    text = '' if text is None else str(text)
    for match in WORDS.finditer(text):
        if normalize(match.group()) not in fillers:
            return text[match.start():]
    return ''


# H7 item 0 (the owner's call of 5 Nov 10:27): a minute of remark and a real question at its end. The privacy gate and the rest of the judgements by words read the whole of it: «я» of the preface made «план счетов 89 счет какой» personal, «сейчас» of the
# preface made «что такое пятнадцатый счёт» data that changes. ``question_part`` is what they read with the text channel on; the job reads all of it and decides. A speaker's own seam in a run with no marks (_SEAMS, a run is _RUN_WORDS or more):
# the recognizers write none in a long breath. A clause that opens with a question word leans on the one before it when that one asks too, with nothing between them: «какой налог платят, когда продают квартиру», «проверь, пожалуйста, что такое …».
_PART_SENTENCE = re.compile(r'[.!?…]+\s+')
_PART_CLAUSE = re.compile(r'\s*(?:(?<!\d),|,(?!\d)|[;:—–])+(?!\s*пожалуйста\b)\s*', re.I)  # запятая между цифрами = десятичная точка
_RUN_WORDS = 8
_SEAMS = frozenset(normalize('значит короче допустим скажем итак').split())
_PART_FILLERS = frozenset(normalize('так ну а вот итак да хорошо ладно значит короче допустим скажем типа слушай смотри просто').split())


def _spans(pattern, text):
    """The stretches of ``text`` between the matches of ``pattern``, those with a word in them: ``[(start, end)]``."""
    spans, at = [], 0
    for match in pattern.finditer(text):
        spans.append((at, match.start()))
        at = match.end()
    return [(start, end) for start, end in spans + [(at, len(text))] if WORDS.search(text[start:end])]


def _run_head(clause):
    """Where the question begins in a long ``clause`` with no marks: after the last seam of the speaker, at the first question word after it (with its preposition). 0 when nothing says so."""
    found = list(WORDS.finditer(clause))
    words = [normalize(match.group()) for match in found]
    if len(words) < _RUN_WORDS:
        return 0
    first = 0
    for at, word in enumerate(words[:-1]):
        if word in _SEAMS and words[max(at - 1, 0):at] != ['что']:
            first = at + 1
    for at in range(first, len(words) - 1):
        if words[at] in QUESTION_WORDS:
            return found[at - 1 if at > first and words[at - 1] in PREPOSITIONS else at].start()
    return found[first].start()


def _leaning(clause):
    """Does ``clause`` open with a question word, a preposition before it apart?"""
    words = norm_words(clause)[:2]
    return bool(words) and (words[0] in QUESTION_WORDS or (words[0] in PREPOSITIONS and words[1:] and words[1] in QUESTION_WORDS))


def _sentence_part(sentence):
    """The part of one sentence that asks: the last of its two last clauses with a question word (a clause after that one stays with it: «какая ставка, если продаю товар»), or a bare topic: its last clause."""
    spans = _spans(_PART_CLAUSE, sentence)
    clauses = [sentence[start:end] for start, end in spans]
    meant = [at for at, clause in enumerate(clauses) if not frozenset(norm_words(clause)) <= _PART_FILLERS]
    if not meant:
        return sentence.strip()
    head = _run_head(clauses[meant[-1]])
    if head:
        return sentence[spans[meant[-1]][0] + head:].strip()
    asks = [bool(frozenset(norm_words(clause)) & QUESTION_WORDS or IMPERATIVE.search(clause)) for clause in clauses]
    first = next((at for at in reversed(meant[-2:]) if asks[at]), None)
    if first is None:              # a bare topic: after a remark its last clause; a short sentence has no remark around it («Нынешний закон о бухучёте, год принятия»)
        if len(norm_words(sentence)) < _RUN_WORDS:
            return sentence.strip()
        first = meant[-1]
    while first and asks[first - 1] and _leaning(clauses[first]):
        first -= 1
    return sentence[spans[first][0]:].strip()


def _unseamed(part):
    """Without the speaker's seam at its head: «значит 55 статья …»."""
    first = WORDS.search(part)
    rest = WORDS.search(part, first.end()) if first and normalize(first.group()) in _SEAMS else None
    return part[rest.start():] if rest else part


_CONDITION_FORM = re.compile(r'\W*(?:(?:так|ну|а|и|хорошо|ладно)\W+)?(?:' + MARKER_BASE + r'|считаем,?\s+что|считай,?\s+что|учитывай|если)\b', re.IGNORECASE)      # the words are the one table of question_part


_NOT_THIS_BUT = re.compile(r'(?:^|\s)не\s+\S+(?:\s+\S+)?\s+а\s+\S')


def not_this_but(text):
    """«не X, а Y»: the form of a correction or an argument, in any text (the ear writes no mark)."""
    return bool(_NOT_THIS_BUT.search(' '.join(norm_words(text))))


def question_by_form(text):
    """c24-a1, the ONE reading of a question by its form with no «?» (the ear writes none): a question part (``question_part.extract``: «… сколько денег осталось») or «не X, а Y»."""
    try:
        from .question_part import asks_by_form
        if asks_by_form(text):
            return True
    except Exception:          # noqa: BLE001 - not sure: the form below
        pass
    return not_this_but(text)


def question_part(text):
    """H7 item 0 with R06 (w2-question-part), the one cut of a remark the gates read: ``_h7_part``, and ``question_part.extract`` for what goes with it. A condition of the question (a number, a rate, a year,
    «берём / допустим / пусть», «не 15, а 50») stays with it (R06: «Берём 2024 год. Какова ставка НДС?» is no question about today's rate); a remark around it that is talk on positive evidence (about oneself, a
    preamble, a time measure, the rehearsal) does not become its topic. What extract cannot tell, or a fault of it, leaves the H7 part as it was."""
    whole = str(text or '').strip()
    fix = _TRAILING_FIX.search(whole)
    if fix and fix.start() > 0 and norm_words(fix.group('wrong'))[-1:] and norm_words(fix.group('wrong'))[-1] in norm_words(whole[:fix.start()]):
        # c24-b: «…, сколько осталось? Нет, не 90, а 80.»: a correction of a word the question has, said after it, is a condition of it; cut off it made the plan's question the old one
        return f"{question_part(whole[:fix.start()]).rstrip(' .!?…,;:')}? {fix.group('fix').strip()}"
    part = _h7_part(whole)
    try:
        from .question_part import extract
        found = extract(whole)
    except Exception:          # noqa: BLE001 - the H7 cut alone
        return part
    if found.kind != 'question':
        return part
    from .generator import CHANGES, route_need
    from .question_part import _has_number
    bare = lambda piece: piece.strip(' .!?…,;:—–-')
    talk = lambda body, why: why != 'unrelated' or (route_need(body)==CHANGES and route_need(found.question)!=CHANGES)      # E73: «сейчас третья минута идёт» is no topic of «Сколько получится?»
    if any(talk(body, why) and bare(body) and bare(body) in part for body, why in found.dropped):
        part = _h7_part(found.question)
    # a condition is a sentence of its own or holds a number: a long run before the question word with «допустим» in it is the preface H7 cuts (SAID_INFLATION)
    # A number read back alone («Двадцать пять.», the answer before) is no condition, nor a word of counting that sets nothing («Хорошо, считаем быстро.»): without a number a condition opens with its form.
    head = [condition for condition in found.conditions if (condition.rstrip()[-1:] in '.!?…' or _has_number(condition)) and bare(condition) not in part
            and (_CONDITION_FORM.match(condition) if not _has_number(condition) else not all(_has_number(word) for word in norm_words(condition)))]
    if head and part != found.question and bare(part) not in bare(found.question):
        part = _h7_part(found.question)       # the H7 cut reached back into a condition («что налоговый период квартал. Сколько получится»)
    # E73.1 (package Q): a preface that names a document is the subject of the question («Нынешний закон о бухучёте, какой год принятия»): it goes in front of the part, the way a condition does
    lead = [body for body in found.subject if bare(body) and bare(body) not in part] + head
    return ' '.join(lead + [part]) if lead else part


def topic_tail(text, settings=None):
    """H7: the topic phrase (rule 1) a long remark ends on, said after its preface and a seam of the speaker with no word that asks («…, тогда вот задам вопрос по кодексу, так, значит 55 статья налогового кодекса»):
    read off ``question_part``, the one cut of a remark. ``None`` for a text that was not cut (the whole of it is judged by ``_topic_phrase`` as it is) and for a tail that names no topic."""
    whole, part = str(text or '').strip(), question_part(text)
    if not part or part == whole:
        return None
    return _topic_phrase(part, frozenset(resolve(settings)['fillers']) | HESITATION_WORDS)


_TRAILING_FIX = re.compile(r'(?<=[.!?…])\s*(?P<fix>(?:(?:нет|ой|точнее|вернее)[,.]?\s+)?не\s+(?P<wrong>[\w.,]+?),?\s+а\s+[\w.,]+?[.!?…]?)\s*$', re.I)      # c24-b: a correction after the question


def _h7_part(text):
    """H7 item 0: the part of a final that asks: of a remark with a question at its end, that question; of a plain question, all of it. A short tail that asks nothing goes first (``reference_kb.without_tail``). Then its last sentence, and of that
    ``_sentence_part``. Two words are no question alone: the sentence before them is their topic («Налог на прибыль. Какая ставка?»). Never empty: what cannot be told stays whole."""
    whole = str(text or '').strip()
    rest = without_tail(whole).strip(' .!?…,;:—–-') or whole.strip(' .!?…,;:—–-')
    sentences = [rest[start:end] for start, end in _spans(_PART_SENTENCE, rest)]
    if not sentences:
        return whole
    part = _unseamed(_sentence_part(sentences[-1]))
    at = sentences[-1].rfind(part)
    if len(norm_words(part)) <= 2 and at > 0:              # «испытательный срок для главного бухгалтера, какой максимум»: two words ask about the clause before them, the condition is there
        clause = re.split(r'(?:(?<!\d),|,(?!\d)|[;:—–])\s*', sentences[-1][:at].rstrip(' ,;:—–-'))[-1].strip()
        if clause:
            part = f'{clause}, {part}'
    if len(norm_words(part)) <= 2 and len(sentences) > 1:
        part = f'{_sentence_part(sentences[-2])}. {part}'
    return whole if part == rest else part


# --- acknowledgement -----------------------------------------------------------------

# --- questions ---------------------------------------------------------------------------

def _contains(words, needle):
    n = len(needle)
    return any(words[i:i + n] == needle for i in range(len(words) - n + 1))


# A new turn said in a few well-known words needs no question mark and no third word to retire a waiting answer.
_STRONG_TRIGGERS = frozenset({'clarification_request', 'question_li', 'topic_change', 'modal_request'})


def _strong(trigger, words, cfg, waiting):
    """U94.10, the one formula of strength: may the evidence of ``trigger`` over ``words`` words replace a waiting answer? Nothing waits: any question is welcome; else it must be substantial
    (``cancel_min_words``), an imperative with a word of its own, or a trigger that is strong by its form."""
    return (not waiting or words >= cfg['cancel_min_words'] or (trigger == 'question_imperative' and words >= 2) or trigger in _STRONG_TRIGGERS)
_TELLING_FILLERS = frozenset({'скажи', 'скажите', 'подскажи', 'подскажите'})   # «скажи единицу массы»: a request, not a filler


# Owner call 20:10 (candidate 7): colloquial Russian puts the question word at the END of the clause - «Че там, дважды два сколько будет», «5 и 5
# сколько будет», «71 план счетов про что», «Семьдесят первый счёт это что», «71-й счет у нас относится к чему относится 71-й счет» - and the
# scan of the first ``question_window`` words never saw it (silent/unrelated_speech). A question word that ends its clause, or is followed only
# by a copula or an auxiliary (and at most a restatement of what the clause already named), asks wherever it stands in the clause - when
# something other than a preposition comes before it in that clause (a clause that OPENS with it after a comma is a subordinate one: «Он
# спросил, сколько будет», «то, что было»), the clause names something (a content word or a number), and nothing before it in the sentence is a
# verb of knowing or saying («не знаю, …», «он спросил …»). «как» and «чем» (comparisons: «лучше чем было») and «когда» («посмотрим когда
# будет») are left to the window.
_LATE_QUESTION_WORDS = frozenset(normalize('что чего чему кто кого кому кем сколько какой какая какие какое каков какова каково каковы '
                                           'где куда откуда почему зачем отчего чей чья чье чьи').split())
_LATE_TAIL = frozenset(normalize('будет будут было был была были есть это этот эта эти такой такая такое такие значит означает означают '
                                 'относится относятся называется называются является являются же там вообще именно у нас').split())
_LATE_PREPOSITIONS = frozenset(normalize('про о об обо к ко для от из на в во с со по за при').split())
_KNOWING = re.compile(r'(?:^|\s)(?:зна\w*|спрос\w*|спраш\w*|поня\w*|понима\w*|помн\w*|уверен\w*|сказал\w*|говор\w*|интересн\w*|дума\w*)(?=\s|$)')


def _late_question_word(asked):
    """Does a clause of ``asked`` end with its question word (owner call 20:10, see above)?"""
    said = []
    for part in re.split(r'([,;:—–]+|[.!?…]+)', str(asked or '')):
        if re.fullmatch(r'[.!?…]+', part):
            said = []                                             # a new sentence: what came before it governs nothing
            continue
        clause = fold_words(norm_words(part), QUESTION_WORDS)
        for i, word in enumerate(clause):
            if word not in _LATE_QUESTION_WORDS:
                continue
            before, tail = clause[:i], clause[i + 1:]
            if all(w in _LATE_PREPOSITIONS for w in before) or _KNOWING.search(' '.join(said + before)):
                continue
            named = set(stems(before))
            if any(w not in _LATE_TAIL and (w.isdigit() and w not in before or not w.isdigit() and stems([w])[0] not in named) for w in tail):
                continue
            if any((len(w) >= 3 or w.isdigit()) and w not in STOPWORDS and w not in _LATE_TAIL for w in before):
                return True
        said += clause
    return False


_ALTERNATIVE_POS = frozenset({'NOUN', 'ADJF', 'ADJS', 'INFN', 'VERB', 'NUMR', 'PRTF', 'PRTS', 'ADVB'})


def alternative_question(words):
    """Fable 10.11 (the call of 10:39: «так а седьмой счёт он активный или пассивный» was no question for the ear nor for the judge, the answer waited 4 s for the cloud to admit it). A choice of two offered
    at the END of the utterance asks, with no question word and no «?» (the ear writes none): X «или» Y, Y the last word, both one part of speech, something named before them. A grammatical form, RU and EN
    («active or passive»). A statement of this form («наличными или картой») goes the same way and the job says «—» to it: the verdict on the content is the job's, the form only lets it be asked."""
    words = list(words)
    if len(words) < 4 or words[-2] not in ('или', 'or'):
        return False
    left, right = words[-3], words[-1]
    if words[-2] == 'or':
        return all(word.isascii() and word.isalpha() and len(word) > 2 for word in (left, right))
    kinds = lambda word: {reading[0] for reading in _readings(word)[:2]} & _ALTERNATIVE_POS      # noqa: E731
    return bool(kinds(left) & kinds(right))


# «Она сказала, что приедет», «Спасибо, что пришли», «Я знаю, что налог растёт»: after a verb of saying, knowing, thinking, feeling (not an imperative, not «ты»: «скажи что такое»,
# «знаешь что такое» ask) or a thanks, «что» is the conjunction, not a question word. A feature of the words; ``_trigger`` and the probe ``conjunction_that`` read it.
_THAT_VERBS = frozenset(('знать думать говорить сказать надеяться понимать понять помнить слышать видеть считать ответить написать решить заметить сообщить обещать казаться оказаться '
                         'выяснить полагать верить чувствовать подозревать догадаться догадываться узнать объяснить рассказать подумать предположить утверждать заявить убедиться '
                         'забыть вспомнить заметить представить признать').split())
_THAT_WORDS = frozenset('спасибо жаль оказывается видно слава благодарю'.split())
_THAT_STANDS_ALONE = frozenset(('такое', 'значит', 'означает', 'за'))         # «знаю что такое налог»: what a tax is is what is asked
_WHY_THEY = frozenset('я мы он она они ты вы'.split())


def conjunction_that(words, lead=()):
    """The indices of the «что» of ``words`` that is a conjunction after a governor («сказала что», «спасибо что», «знаю что приедет»), and of the «почему» of «вот почему я …»: no question word."""
    found = []
    for i, word in enumerate(words):
        before = words[i - 1] if i else (lead[-1] if lead else None)      # the leads were taken off the front: «спасибо» of «спасибо, что пришли»
        if before is None or (word == 'что' and words[i + 1:i + 2] and words[i + 1] in _THAT_STANDS_ALONE):
            continue
        if word == 'почему' and before == 'вот' and words[i + 1:i + 2] and words[i + 1] in _WHY_THEY:
            found.append(i)
        elif word == 'что' and (before in _THAT_WORDS or any(
                kind == 'VERB' and 'indc' in grammemes and 'impr' not in grammemes and '2per' not in grammemes and lemma in _THAT_VERBS
                for kind, grammemes, lemma in _readings(before)[:2])):
            found.append(i)
    return found


# The ear writes what it hears: «што такое налог», «пачему», «сколька», «када». A word the dictionary does not know that is a question word (or «пожалуйста») with its vowels reduced is that word.
_HEARD_AS = {'што': 'что', 'шта': 'что', 'чё': 'что', 'чо': 'что', 'када': 'когда', 'кода': 'когда', 'щас': 'щас'}
_HEARD_TARGETS = QUESTION_WORDS - frozenset(('можно', 'можешь', 'нужно', 'верно', 'правда')) | {'пожалуйста'}
_REDUCED = (('а', 'о'), ('и', 'е'), ('я', 'е'), ('ы', 'и'))


def _vowel_swaps(word, limit=2):
    """The words one or two reduced vowels of ``word`` away (а<->о, и<->е)."""
    out = {word}
    for _ in range(limit):
        for form in tuple(out):
            for i, ch in enumerate(form):
                for a, b in _REDUCED:
                    if ch == a:
                        out.add(form[:i] + b + form[i + 1:])
                    elif ch == b:
                        out.add(form[:i] + a + form[i + 1:])
    return out


def heard_spelling(text):
    """``text`` with the ear's phonetic spelling of a question word put right («што такое налог» -> «что такое налог»); every other word, and every word the dictionary knows, as it was."""
    out, changed = [], False
    for token in unicodedata.normalize('NFC', str(text or '')).split(' '):      # a decomposed «й» is one letter, not «и» and a mark
        core = re.sub(r'^\W+|\W+$', '', token)
        fixed = None
        if core and (core.lower() in _HEARD_AS or 2 < len(core) <= 11) and (core.islower() or core.istitle()):
            low = unicodedata.normalize('NFC', core.lower())
            fixed = _HEARD_AS.get(low)
            if fixed is None and normalize(low) not in _HEARD_TARGETS and not _known(low) and not _known(normalize(low)):
                fixed = next((w for w in sorted(_vowel_swaps(normalize(low)) & _HEARD_TARGETS)), None)
        if fixed and fixed != core.lower():
            token, changed = token.replace(core, fixed.capitalize() if core[:1].isupper() else fixed, 1), True
        out.append(token)
    return ' '.join(out) if changed else text      # nothing respelled: the text as it came


_HORTATIVE = frozenset('поехали погнали пошли давай давайте начнем начнём продолжим приступим пойдем пойдём двинемся посмотрим разберем разберём займемся займёмся приступаем начинаем продолжаем'.split())
_HORTATIVE_ADJUNCTS = frozenset('дальше тогда уже теперь ладно пожалуйста вместе потихоньку'.split())


def what_opener(words, fillers=frozenset()):
    """``'opener'`` for «ну что», «ну что, поехали», «так что, начнём», «что, давай дальше»: the «что» of a turn-opening (after the leads) that is followed by nothing or by a call to go on - a
    hortative of the first person plural («поехали», «начнём», «продолжим») with its adjuncts; ``None`` for a «что» that asks («ну что такое налог»). A feature: the kind judge rules."""
    words = list(words)
    i = 0
    while i < len(words) and (words[i] in fillers or words[i] in _OPENER_LEADS):
        i += 1
    if i >= len(words) or words[i] != 'что':
        return None
    rest = [w for w in words[i + 1:] if w not in ('ж', 'же')]
    if not rest:
        return 'opener'
    ours = lambda w: w in _HORTATIVE or any(k == 'VERB' and {'plur', '1per'} <= set(g) for k, g, _ in _readings(w)[:2])      # noqa: E731
    if all(w in _HORTATIVE_ADJUNCTS or ours(w) for w in rest) and any(ours(w) for w in rest):
        return 'opener'
    return None


_OPENER_LEADS = frozenset('ну так а и вот итак ладно хорошо'.split())


_CONTRAST_MIN_WORDS = 5      # words around the «не … а» (the particles and the fillers aside): below it a turn is a remark («Нужно не бояться, а делать»)


def contrast_not_but(words, fillers=frozenset()):
    """``True`` for «Нужно не пять, а шесть сотрудников для проекта»: «не» + one to three words + «а» + more, the first part no finite verb («не знаю, а …» is no contrast of two objects),
    and at least five words around it (a four-word remark of a friend asks nothing). The ear writes no mark: this form is what lets such a turn be taken for a question. A feature."""
    words = list(words)
    for i, word in enumerate(words):
        if word != 'не':
            continue
        for j in range(i + 2, min(i + 5, len(words) - 1)):
            if words[j] != 'а':
                continue
            if any(kind == 'VERB' and 'indc' in grammemes for kind, grammemes, _ in _readings(words[j - 1])[:1]):
                break
            return len([w for w in words if w not in ('не', 'а') and w not in fillers]) >= _CONTRAST_MIN_WORDS
    return False


def _subject_asks(asked):
    from .question_part import asks_by_form      # the same owner as ``question_by_form``
    return asks_by_form(asked, subject=True)


def _trigger(asked, asked_words, cfg, lead=()):
    if clarification_request(asked_words, lead):
        return 'clarification_request'
    if li_question(asked_words):
        return 'question_li'
    if alternative_question(asked_words):
        return 'question_alternative'
    if topic_change(asked_words):
        return 'topic_change'
    scan = fold_words(asked_words, QUESTION_WORDS)    # W1F-C: a question word the recogniser cut in two («скол ько») is that word
    that = modal_that_index(scan)          # «Можно сказать, что он прав»: the «что» after the request verb is a conjunction (ruling 5, fix round 1)
    reported = conjunction_that(scan, lead)      # «Она сказала, что приедет», «Спасибо, что пришли»: so is the «что» after a verb of saying or knowing
    for i, word in enumerate(scan[:cfg['question_window']]):
        if word in QUESTION_WORDS and not (word == 'как' and scan[i + 1:i + 2] == ['бы']):
            if word in MODAL_WORDS or i == that or i in reported:
                continue          # E3a-rest ruling 5: «нужно», «можно», «правда» … ask with «?», with «ли» or as a request (below), never as a statement
            return 'question_word'
    if _late_question_word(asked):
        return 'question_word_end'
    if _subject_asks(asked):
        return 'question_form'      # E73.1: no question word in the window, a preface that names the subject and a question after it («Нынешний закон о бухучёте, какой год принятия»): its own reason, not the ear's strong «question_word»
    if modal_request(asked_words):
        return 'modal_request'
    if IMPERATIVE.search(asked):
        return 'question_imperative'
    if QUESTION_TAIL.search(asked):
        return 'question_tail'
    if REFERENCE_QUERY.fullmatch(asked):
        return 'question_reference'
    if re.search(r'\bстать[яюеи]\b',asked,re.I):
        try:
            from .ru_alignment import _canonical
            canonical=' '.join(_canonical(asked,())).replace('российский федерация','рф')
            canonical=re.sub(r'#(?:ord:)?(\d+(?:\.\d+)*)',r'\1',canonical)
            if REFERENCE_QUERY.fullmatch(canonical):return 'question_spoken_reference'
        except ImportError:pass
    if len(asked_words) >= 2 and _TELLING_FILLERS.intersection(lead):
        return 'question_imperative'
    return None


def _question_evidence(raw, words, bank, cfg, waiting):
    body = strip_fillers(raw, cfg)
    prefix = EXPLICIT.match(body)
    rest = body[prefix.end():].strip() if prefix else body
    # Wave F fix round 1 (ruling 5): the marker counts only before a question or a topic phrase («Вопрос такой сложный» asks nothing).
    explicit = bool(prefix) and bool(norm_words(rest)) and _rest_asks(rest, cfg)
    asked = rest if explicit else body
    asked_words = norm_words(asked)
    if not asked_words:
        return None
    answer = bank.lookup(asked) if bank is not None and hasattr(bank, 'lookup') else None      # the ONE place that takes a prepared answer: ``PreparedAnswers.lookup`` (the same as the controlled route's)
    if answer:
        return _Evidence(True, 'question_bank', asked, {'question': asked, 'answer': answer}, False)
    if explicit:
        return _Evidence(True, 'question_explicit_prefix', asked, None, False)
    if raw.rstrip().endswith('?'):
        return _Evidence(True, 'question_mark', asked, None, False)
    lead = words[:max(0, len(words) - len(norm_words(body)))]
    trigger = _trigger(asked, asked_words, cfg, lead)
    if trigger:
        # Nothing waits for a confirmation: any question is welcome. Otherwise it must be substantial.
        strong = _strong(trigger, len(asked_words), cfg, waiting)
        # A clarification is passed on as it was said: «А подробнее» still means «and in more detail» to the model.
        return _Evidence(strong, trigger, raw if trigger == 'clarification_request' else asked, None, True)
    return _indirect_request_evidence(asked, asked_words, cfg) or _preamble_evidence(asked, cfg, waiting)


# --- Task E3a (WAVE 2): what counts as a question ---------------------------------------------------------------------------
# Rulings 1-5 of the coordinator (T-A findings DEF-T-01 .. DEF-T-06). The vocabularies are in user_intents.py (same heading); this block
# decides what the words amount to: which of them are content, how strong the evidence is, what the question text is.
from .user_intents import indirect_request, is_rhetorical, is_small_talk  # noqa: E402  (the block keeps its own imports: three tasks edit this module's head)


def _content_words(words, fillers):
    """The words that carry a topic: no fillers, pronouns or function words, no 1-2 letter words (numbers count)."""
    return [w for w in words if (len(w) >= 3 or w.isdigit()) and w not in STOPWORDS and w not in fillers]


def _indirect_request_evidence(asked, asked_words, cfg):
    """Ruling 1: «Хочу узнать про …», «Хотелось бы понять …», «Интересно услышать о …», «Было бы здорово узнать …», «В двух словах про …»,
    «<термин> для меня загадка», «Не понимаю, как …», «Мне непонятно, …» ask like «Что такое …?». Strong (it may replace a waiting answer)
    when a content word follows the frame: «Хочу узнать» alone asks nothing. The text goes on as it was said."""
    rest = indirect_request(asked_words)
    if rest is None or not _content_words(rest, frozenset(cfg['fillers']) | HESITATION_WORDS):
        return None
    return _Evidence(True, 'indirect_request', asked, None, True)


# --- CL2 (ruling 4, amendment A): going on ---------------------------------------------------------------------------------
# Two more kinds of ``analyze``: ``next`` («дальше», «далее», «следующая»: one portion forward, without a repeat) and ``resume``
# («продолжай», «доскажи», «на чём мы остановились», «вернёмся к прошлому вопросу»: the unclosed part of an answer). The reason says the
# form: ``next_command``, ``resume_continue``, ``resume_return``, ``resume_return_first``; ``question`` is the text as said (when there is
# nothing to go on with, those words are the question for the model). The vocabulary is in user_intents.py; the engine decides what a
# form does with the state (engine.going_on).
from .user_intents import going_on as _going_on  # noqa: E402  (the block keeps its own import, like the E3a block above)

RESUME, NEXT = 'resume', 'next'


# --- Task E3a-rest (WAVE 2): rulings 3, 4, 5 -----------------------------------------------------------------------------------------
# The coordinator's rulings for the T-A findings DEF-T-04 (a spoken correction of the topic), DEF-T-03 (a word not understood) and DEF-T-06
# (a modal word in a statement). The vocabularies are in user_intents.py (same heading); this block decides what the words amount to.
# ``_trigger`` above asks ``MODAL_WORDS`` / ``modal_request`` / ``modal_that_index`` of it.
from .user_intents import (MODAL_WORDS, corrected_request, modal_request, modal_that_index,  # noqa: E402  (the block keeps its own imports: several tasks edit this module's head)
                           unknown_word_request)


# --- W1F-C (wave W1 fixes, 3 Nov): natural forms of commands and intents, ASR-robust ----------------------------------------------------
# Class C3 of the W1 analysis (G3-G6): the intents were closed exact-phrase lists on raw ASR tokens. They are small closed grammars in
# user_intents.py now (stop / repeat / next / position / return / disagreement / small talk, read through one ASR view, ``fold_asr``); this
# block finds a request at the start of a later clause after a discourse preamble («Подожди, лучше скажи другое, сколько рук у осьминога»).
from .user_intents import (fold_asr, fold_words, is_preamble, is_topic_frame, position_prefix, preamble_ends,  # noqa: E402  (the block keeps its own imports)
                           return_topic)

_CLAUSE_MARK = re.compile(r'[,:;—–.!?]')


def _request_starts(text):
    """Where in ``text`` a request may start after a discourse preamble, as ``[(rest, asked), …]``: the character offsets of the rest to be
    classified and of the question to pass on. First the points inside the preamble that opens the text (the longest preamble first:
    «Подожди лучше скажи другое | сколько …»), then each clause that follows nothing but preamble and topic-frame clauses (a topic frame is
    part of the question: «про гитару ещё раз, | сколько там струн»)."""
    matches = list(WORDS.finditer(text))
    words = [normalize(match.group()) for match in matches]
    starts = [(matches[n].start(), matches[n].start()) for n in preamble_ends(words)]
    clauses, first = [], 0
    for n in range(1, len(matches) + 1):
        if n == len(matches) or _CLAUSE_MARK.search(text, matches[n - 1].end(), matches[n].start()):
            clauses.append((first, n))
            first = n
    frame = None
    for start, stop in clauses:
        if start > 0:
            starts.append((matches[start].start(), matches[start if frame is None else frame].start()))
        if is_topic_frame(words[start:stop]):
            frame = start if frame is None else frame
        elif not is_preamble(words[start:stop]):
            break
    return list(dict.fromkeys(starts))


# W1 w1_05 step 5 (G2 (c) of the W1 analysis): «Нет, я ошибся, запас не десять, а двадцать» corrects the condition of the question; it was
# taken for a failed repeat and the stale portion was said again. «я ошибся / ошиблась / оговорился / оговорилась» opens a self-correction when
# what follows restates the question's own terms (a content stem in common): «Я ошибся дверью, извините» stays somebody's remark.
_SELF_CORRECTION = re.compile(r'^(?:(?:нет|ой)\s+)*(?:(?:подожди(?:те)?|погоди(?:те)?|постой(?:те)?|стой(?:те)?|обожди)\s+)*'
                              r'я\s+(?:ошибся|ошиблась|оговорился|оговорилась)\s+(.+)$')


def _self_correction(heard, state, fillers):
    """The match of a self-correction of the question's condition (its group 1: the corrected words), else ``None``."""
    found = _SELF_CORRECTION.fullmatch(' '.join(fold_asr(heard)))
    if found is None or not isinstance(state.get('question'), str):
        return None
    restated = _content_stems(found.group(1).split(), fillers) & _content_stems(norm_words(state['question']), fillers)
    return found if restated else None


def _preamble_evidence(text, cfg, waiting):
    """W1F-C (W1: w1_09 steps 2 and 5, w1_08 step 6): a request at the start of ANY clause after a discourse preamble is a request, judged
    like a whole utterance (``_trigger`` on the rest: the question word within the first words of the rest, an imperative, a topic change …),
    with the same strength rule. The question passed on is the rest without the preamble, or from the topic frame on when there is one."""
    for rest_at, asked_at in _request_starts(text):
        rest = text[rest_at:]
        rest_body = strip_fillers(rest, cfg)
        rest_words = norm_words(rest_body)
        if not rest_words:
            continue
        said = norm_words(rest)
        if 0 in conjunction_that(rest_words, tuple(norm_words(text[:rest_at]))):
            continue      # «Спасибо, что пришли»: the «что» after the thanks of the preamble is the conjunction, the rest asks nothing
        trigger = _trigger(rest_body, rest_words, cfg, said[:len(said) - len(rest_words)])
        if trigger is None:
            found = _indirect_request_evidence(rest_body, rest_words, cfg)
            if found is not None:
                return found
            continue
        strong = _strong(trigger, len(rest_words), cfg, waiting)
        if asked_at < rest_at:
            asked = text[asked_at:].strip()
        else:
            asked = rest.strip() if trigger == 'clarification_request' else rest_body
        return _Evidence(strong, trigger, asked, None, True)
    return None


def _as_said(raw, words, start, stop):
    """``words[start:stop]`` (``words`` being ``norm_words(raw)``) as the listener said them: case, ё and the punctuation between them kept."""
    spans = [match.span() for match in WORDS.finditer(raw)]
    if len(spans) == len(words) and 0 <= start < stop <= len(spans):
        return raw[spans[start][0]:spans[stop - 1][1]]
    return ' '.join(words[start:stop])


def _longest_content_word(text, fillers):
    """The longest content word of ``text`` as it is written there (a tie: the first one), else ``None``. A number is no word to explain."""
    best = None
    for match in WORDS.finditer(str(text)):
        word = normalize(match.group())
        if len(word) < 3 or word.isdigit() or word in STOPWORDS or word in fillers:
            continue
        if best is None or len(word) > len(best[0]):
            best = (word, match.group())
    return best[1] if best else None


_NUMBER_FIX = re.compile(r'(?:(?:нет|ой|точнее|вернее)[,.]?\s+)?не\s+(?P<wrong>\d[\d ]*?)\s*,?\s+а\s+\d[\d ]*[.!]?', re.I)


def _number_fix(raw, state):
    """c24-b: «Нет, не 9, а 19.» alone, after the answer to a question that has 9: that question corrected (the question, then the correction), else None."""
    match = _NUMBER_FIX.fullmatch(str(raw or '').strip())
    if not match:
        return None
    from .engine import asked_of      # the one base of «what was asked before» (engine-history)
    asked = asked_of(state)
    question = str(asked[-1] if asked else '').strip()
    if match.group('wrong').replace(' ', '') not in re.findall(r'\d+', question.replace('\u00a0', '').replace(' 000', '000')):
        return None
    return f"{question if question[-1:] in '.!?…' else question + '?'} {str(raw).strip()}"


def _corrected_request_text(raw, words, heard, fillers):
    """Ruling 3 (DEF-T-04): «Нет, я про причины, а не определение», «Не про определение, а про причины», «Речь идёт о причинах, а не об
    определении», «Тема сейчас причины, а не определение», «Я не об этом, я про причины»: the corrected request (причины) as it was said, the
    wrong one left out. ``None``: not such a correction, or the request names no content word («Нет, я про это»)."""
    span = corrected_request(heard)
    if span is None:
        return None
    start, stop = span
    if not _content_words(heard[start:stop], fillers):
        return None
    lead = len(words) - len(heard)
    return _as_said(raw, words, lead + start, lead + stop)


def _is_abbreviation(word):
    letters = [char for char in word if char.isalpha()]
    return len(letters) >= 2 and all(char.isupper() for char in letters)


def _lower_case_term(term):
    """«Гидравлический» -> «гидравлический» (the capital is the start of a sentence or the recogniser's); an all-caps abbreviation (ВВП, НАТО, ГОСТ-Р) stays as it is."""
    return WORDS.sub(lambda match: match.group() if _is_abbreviation(match.group()) else match.group().lower(), term)


def _term_question(raw, words, heard, fillers, portion_text):
    """Ruling 4 (DEF-T-03): «Не понял это слово», «Непонятно слово X», «Это слово мне незнакомо», «Что это за слово?» while a portion waits ask what
    a word means: the question «Что значит «X»?» with X the word that was named, else the longest content word of the waiting portion (the
    word as the portion has it). ``None``: not such a request, or the portion has no word to explain."""
    span = unknown_word_request(heard)
    if span is None:
        return None
    start, stop = span
    lead = len(words) - len(heard)
    if stop > start and _content_words(heard[start:stop], fillers):
        term = _as_said(raw, words, lead + start, lead + stop)
    else:
        term = _longest_content_word(portion_text, fillers)
        if term is None:
            return None
    return f'Что значит «{_lower_case_term(term)}»?'


# --- attempts at a portion ----------------------------------------------------------------

def _content_stems(words, fillers):
    """Stems of the words that carry the topic: no fillers, pronouns or function words, no 1-2 letter words."""
    return set(stems(w for w in words if (len(w) >= 3 or w.isdigit()) and w not in STOPWORDS and w not in fillers))


def _repeat_like(heard, portion, cfg, fillers):
    """A question that is mostly the waiting portion itself is a sloppy repeat, not a new question."""
    if cfg['repeat_cover'] <= 0:
        return False
    wanted = _content_stems(portion, fillers)
    if len(wanted) < 2 or len(heard) > len(portion) + cfg['attempt_extra_words']:
        return False
    return len(wanted & _content_stems(heard, fillers)) / len(wanted) >= cfg['repeat_cover']


_ROMAN_WORD = re.compile(r'(?=[ivxlcdm]{2})m{0,3}(?:cm|cd|d?c{0,3})(?:xc|xl|l?x{0,3})(?:ix|iv|v?i{0,3})')


def _own_number(heard, portion):
    """g28: does ``heard`` (words) name a number, in figures or in words, cardinal or ordinal, where ``portion`` (words) has none? A number for the portion's
    number («статья восемнадцать» for «Статья 17 …») is a wrong repeat of it."""
    from .fast_text import _atoms, _values      # noqa: PLC0415 - fast_text imports this module
    try:
        # U16: a written range («xiii–xv») is a number of the portion even where the atoms do not read it: a digit or a roman of 2+ letters.
        if any(word.isdigit() or _ROMAN_WORD.fullmatch(word) for word in portion):
            return False
        return bool(_values(_atoms(' '.join(heard)))) and not _values(_atoms(' '.join(portion)))
    except ImportError:                           # no razdel (the cloud has none): the plain words of numbers read it
        number = lambda word: word.isdigit() or word in NUMBER_WORDS
        return any(map(number, heard)) and not any(map(number, portion))


def _mismatch(cfg, waiting, heard, portion, fillers, tag):
    """The utterance is not a confirmation, command or accepted question: replay (an attempt) or stay quiet."""
    if not waiting:
        return Decision(QUIET, 'clarification_without_answer' if tag == 'clarification' else 'not_a_question', None, None)
    if not cfg['diagnose']:
        return Decision(QUIET, 'mismatch_policy_silent', None, None)
    if tag in ('clarification', 'repeat_cover'):
        return Decision(REPLAY, 'attempt_clarification' if tag == 'clarification' else 'attempt_repeat_cover', None, None)
    if tag == 'answer_words':
        return Decision(REPLAY, 'attempt_answer_words', None, None)
    said, wanted = _content_stems(heard, fillers), _content_stems(portion, fillers)
    if said & wanted:
        # An attempt is about as long as the portion; a long talk that happens to use the same word is not one.
        if len(heard) > len(portion) + cfg['attempt_extra_words']:
            return Decision(QUIET, 'speech_too_long_for_an_attempt', None, None)
        # g28: «пятьдесят девятый счёт это» for «расчётные счета организации в банке» (the owner's call of 06.11 09:03) shares one stem and
        # brings a number where the portion has none and more words of its own than of the portion: a new question or talk, never a wrong repeat of it.
        if len(said & wanted) <= len(said - wanted) and _own_number(heard, portion):
            return Decision(QUIET, 'unrelated_speech', None, None)
        return Decision(REPLAY, 'attempt_shared_stem', None, None)
    return Decision(QUIET, 'weak_question_ignored' if tag == 'weak_question' else 'unrelated_speech', None, None)


def _partial_of(heard, portion):
    """Is what was heard a strict part of the portion that waits, word for word or stem for stem?

    A part of the portion is an attempt at it, whatever it looks like («Наклон?», «Когда температура падает»): it never
    is a new question.
    """
    if not heard or not portion:
        return False
    if len(heard) < len(portion) and _contains(portion, heard):
        return True
    heard_stems, portion_stems = stems(heard), stems(portion)
    return 0 < len(heard_stems) < len(portion_stems) and _contains(portion_stems, heard_stems)


def _answer_words_only(heard, state, cfg, raw=""):
    """integ9 (F1 meaning portions x the classifier): while a portion waits, an utterance EVERY word of which (by stem) is a word of the current
    answer's own text - its portions, confirmed or still to come - and that has at least two content words is the listener's try at the
    answer: a neighbour portion («чем больше масса, у тела,» while «Инерция — это свойство тела» waits) opens with the answer's own
    «чем», never with a question of the listener's. It is never a new question and never retires the answer. One word the answer does not
    have («что такое», «почему», «влияет») leaves the utterance what it was; so does an elliptical «А почему?» (no content word). Asked
    only where a new question would otherwise be returned (step 6), so every other verdict and its reason stay as they were; part of the
    «a question that looks like a repeat» family, so ``repeat_cover`` = 0 switches it off with ``_repeat_like``."""
    chunks = (state or {}).get('chunks') or []
    if cfg['repeat_cover'] <= 0 or not chunks or not heard or sum(1 for word in heard if word not in STOPWORDS) < 2:
        return False
    told = stems(norm_words(' '.join(str(chunk) for chunk in chunks)))
    if not all(part in set(told) for part in stems(heard)):
        return False
    # c8 (w4_07: «Кто написал картину Утро стрелецкой казни?» after an answer about that painting): a repeat follows the answer's word order.
    # An utterance that asks - it opens with an interrogative or ends with «?» - and is not a run of the answer's words in their order is
    # the listener's follow-up question, built from the answer's words; «чем больше масса, у тела?» (a run of a later portion) stays a try.
    return not _asks(raw, heard) or _contains(told, stems(heard))


# c8: the interrogatives an utterance that asks opens with (after a lead particle: «А кто …»); not the request verbs of QUESTION_WORDS.
_INTERROGATIVES = QUESTION_WORDS - frozenset(normalize('объясни расскажи покажи можно можешь нужно верно правда').split())
_ASK_LEADS = frozenset({'а', 'и', 'ну', 'но', 'так'})


def _asks(raw, heard):
    lead = next((word for word in heard if word not in _ASK_LEADS), None)
    return lead in _INTERROGATIVES or str(raw or '').rstrip().endswith('?')


def _tries_at(said, portion, fillers):
    """Is what was taken back a try at the portion: a word of it, or any number where the portion has one (the words of a wrong number share no stem with digits)?"""
    words = norm_words(said)
    number = lambda word: word.isdigit() or word in NUMBER_WORDS
    return bool(_content_stems(words, fillers) & _content_stems(portion, fillers)) or (any(map(number, words)) and any(map(number, portion)))


def _near(heard, portion):
    """Mostly the portion, word for word (the digits not merged into numbers): a repeat with a slip, not a new question."""
    try:
        from rapidfuzz.distance import Levenshtein
    except ImportError:
        return False
    a, b = stems(heard), stems(portion)
    return bool(a) and bool(b) and len(a) <= len(b) + 3 and Levenshtein.normalized_similarity(a, b) >= 0.6


# --- Wave F (F2, 3 Nov): the owner's REAL call 09:55 (abcc139fe874) -----------------------------------------------------------------------
# «ну хоть девятая статья налогового кодекса» and «… тебе нужно обязательно сказать, что такое девятая статья налогового кодекса» were
# not_a_question (silence); «Ну и короче я готов. А какой вопрос? Вопрос получается 21-ая статья налогового кодекса» too. «Зачем вот это вот
# всё тянуть надо было» and «почему нельзя настроить как-то, чтобы ты прям мгновенно отвечал, суфлировал …» were questions: a waiting answer
# retired, the cue «Согласен, стоило», a refused lookup and the spoken «Ошибка». Step 6 of ``analyze`` asks ``_new_turn``:
#   rule 3  an indirect question inside a request or a complaint is that question («что такое девятая статья налогового кодекса»);
#   rule 4  a remark to the prompter about its own work is no question: QUIET 'remark_to_prompter' (rule 3 wins; commands are decided
#           before step 6 and keep their meaning);
#   rule 2  several sentences in one final: the chat before the question is dropped - the last run of question sentences, from an explicit
#           «Вопрос …» when there is one; a sentence that names something (a premise) stays with its question;
#   rule 1  nothing waits: a topic phrase is a question - after lead particles and fillers a noun phrase (a content noun head, no finite
#           verb, at most eight words); the phrase is what is asked. A noun phrase while a portion waits stays what it was.
# The vocabularies are in user_intents.py (same heading); the morphology is pymorphy3's, through the analyzer ru_alignment shares.
import functools  # noqa: E402  (the block keeps its own imports: several tasks edit this module's head)

from .user_intents import (DIALOGUE_NOUNS, EVALUATIVE_ADJECTIVES, HOLD_NOUNS, INTERJECTION_HEADS, MARKER_FORM,  # noqa: E402
                           MOVE_ON_LEADS, MOVE_ON_NEXT, MOVE_ON_UNITS, PROMPTER_MISBEHAVIOUR, PROMPTER_SPEECH, PROMPTER_WORK_NOUNS,
                           REPEAT_VERBS, SOUND_CAPTIONS, SPAN_NOUNS, TICKET_ASPECTS, TICKET_MAX_WORDS, TOPIC_LEADS, TOPIC_MAX_WORDS,
                           TOTALITY_DETERMINERS, courtesy, indirect_question, question_marker_end)
from .textutil import PREPOSITIONS  # noqa: E402

_Token = namedtuple('_Token', 'word surface start end pos grams lemma readings')
_CLAUSE_BREAK = re.compile(r'[,;:—–.!?…]')
_TOPIC_PREPOSITIONS = frozenset({'про', 'о', 'об', 'обо', 'насчет'})
_PERSONS = frozenset({'я', 'мы', 'он', 'она', 'оно', 'они'})
# Fix round 1 (ruling 3): only the singular addresses the prompter; «вы» is the listener's interlocutor («За что вы отвечали …?»).
_YOU = frozenset({'ты', 'твой'})
# «, ты сказал,», «как ты говоришь», «…, ты говоришь?»: a parenthesis inside a content question, never the remark itself.
_PARENTHESIS = re.compile(r'(?:(?:а|и|но|ну|так|вот)\s+)?(?:как\s+)?(?:ты|вы)\s+(?:же\s+)?(?:мне\s+)?'
                          r'(?:сказал|сказала|сказали|говорил|говорила|говорили|говоришь|говорите)(?:\s+мне)?')
# The nouns of the prompter's own work name nothing (ruling 3's closed set, and «вопрос», the pair of «ответ»).
_WORK_NOUNS = PROMPTER_WORK_NOUNS | {'вопрос'}
_NO_CONTENT_PRONOUNS = frozenset({'это', 'то', 'всё', 'все', 'что'})
# «Что ты сказал?», «что ты мне только что сказал про …»: a request to hear the answer again, not a remark on the prompter's work.
_HEARD_WHAT = re.compile(r'\bчто\s+(?:ты|вы)\s+(?:\S+\s+){0,3}?(?:сказал|сказала|сказали|говорил|говорила|говорили|говоришь|говорите)\b')
_NOT_A_TOPIC_ALONE = frozenset({'Name', 'Patr', 'Slng', 'Obsc', 'Infr', 'Erro'})
_POSSESSIVE_PRONOUNS = frozenset({'его', 'ее', 'их'})


@functools.lru_cache(maxsize=16384)
def _readings(word):
    """pymorphy3's readings of a normalized word, best first: ``((POS, grammemes, lemma), …)``; ``()`` without the analyzer."""
    try:
        from . import ru_alignment as ru
        ru._lemma(word)                                   # creates the shared analyzer under its own lock
        with ru._LOCK:
            parses = ru._MORPH.parse(word)
    except Exception:
        return ()
    return tuple((str(p.tag.POS) if p.tag.POS else None, frozenset(str(g) for g in p.tag.grammemes), p.normal_form.replace('ё', 'е'))
                 for p in parses)


@functools.lru_cache(maxsize=16384)
def _known(word):
    """Is ``word`` in pymorphy3's dictionary (not a guess from its ending)?"""
    try:
        from . import ru_alignment as ru
        ru._lemma(word)
        with ru._LOCK:
            return bool(ru._MORPH.word_is_known(word))
    except Exception:
        return False


def _split_second_person(text, matches, i):
    """c7-meta (w3_14: «Ну и что ты замира ешь?»): the end of a 2nd-person-singular verb the recogniser split in two - the pieces
    ``matches[i]``, ``matches[i + 1]`` separated by spaces only, their concatenation a dictionary 2sg verb, one of them no dictionary word
    («тормо зишь», «замира ешь»: «ешь» is a word, «замира» is none). The counterpart of ``user_intents.fold_words`` for the open class of
    verbs that a remark to the prompter is made of; nothing else is ever joined. The index after the pair, else ``None``."""
    if i + 1 >= len(matches) or str(text)[matches[i].end():matches[i + 1].start()].strip():
        return None
    left, right = normalize(matches[i].group()), normalize(matches[i + 1].group())
    if _known(left) and _known(right):
        return None
    joined = _readings(left + right)
    if joined and _known(left + right) and joined[0][0] == 'VERB' and {'2per', 'sing'} <= joined[0][1]:
        return i + 2
    return None


def _tokens(text):
    """The words of ``text`` with their best reading (part of speech, grammemes, lemma) and every reading."""
    out = []
    matches = list(WORDS.finditer(str(text)))
    i = 0
    while i < len(matches):
        match = matches[i]
        joined = _split_second_person(text, matches, i)
        if joined is not None:
            surface = match.group() + matches[i + 1].group()
            word = normalize(surface)
            readings = _readings(word)
            out.append(_Token(word, surface, match.start(), matches[i + 1].end(), readings[0][0], readings[0][1], readings[0][2], readings))
            i = joined
            continue
        word = normalize(match.group())
        readings = _readings(word)
        pos, grams, lemma = readings[0] if readings else (None, frozenset(), word)
        out.append(_Token(word, match.group(), match.start(), match.end(), pos, grams, lemma, readings))
        i += 1
    return out


def _is_number(token):
    return any(char.isdigit() for char in token.word) or token.pos == 'NUMR' or bool(token.grams & {'NUMB', 'ROMN'})


def _phrase_kind(token):
    """What a word may be inside a noun phrase: 'noun', 'adj', 'num', 'prep', 'conj', or ``None`` (a verb, an adverb, a pronoun, a particle,
    a short adjective, a predicative …: the words that make a clause, not a name)."""
    if _is_number(token):
        return 'num'
    if _is_abbreviation(token.surface) or token.grams & {'LATN', 'UNKN'}:
        return 'noun'
    if token.word in _POSSESSIVE_PRONOUNS:
        return 'adj'                                              # c7-meta round 2: «учёт их наличия» - a determiner inside a phrase
    if token.pos == 'ADJF':
        return None if 'Apro' in token.grams else 'adj'          # «этот», «такой», «весь», «мой» point, they name nothing
    return {'NOUN': 'noun', 'PRTF': 'adj', 'PREP': 'prep', 'CONJ': 'conj'}.get(token.pos)


def _names_something(text, governed_too=False):
    """Does ``text`` name something: a number, or a noun that is no pronoun and not «вопрос» / «ответ»? ``governed_too=False``: only one no
    preposition governs («Велосипедист едет …» names something, «Всё, я на месте» does not)."""
    governed = False
    for token in _tokens(text):
        kind = _phrase_kind(token)
        if kind == 'prep':
            governed = True
        elif kind == 'num' or (kind == 'noun' and token.lemma not in DIALOGUE_NOUNS):
            if governed_too or not governed:
                return True
            governed = kind == 'num'
        elif kind != 'adj':
            governed = False
    return False


_HEAD_CASES = ('nomn', 'accs')
_ANY_CASE = ('nomn', 'gent', 'datv', 'accs', 'ablt', 'loct')


def _agreement(token, parts_of_speech, case='nomn'):
    """``{(number, gender), …}`` of the readings of ``token`` in ``case`` as one of ``parts_of_speech`` (no gender in the plural)."""
    found = set()
    for pos, grams, _ in token.readings:
        if pos in parts_of_speech and case in grams:
            number = 'plur' if 'plur' in grams else 'sing'
            gender = next((g for g in ('masc', 'femn', 'neut') if g in grams), None)
            found.add((number, None if number == 'plur' else gender))
    return found


def _agree(heads, modifiers):
    return any(n1 == n2 and (g1 is None or g2 is None or g1 == g2) for n1, g1 in heads for n2, g2 in modifiers)


def _can_head(token, modifiers=(), cases=_HEAD_CASES):
    """A noun that can head a named topic in one of ``cases`` - the nominative, or the accusative of an object said without its verb («Ну хоть
    теорию относительности») - with the adjectives right before it (``modifiers``) agreeing with it in that case: «финансовой системы» is
    no nominative plural. An indeclinable word, an abbreviation, an unknown or Latin word heads too; a number heads nothing («145»)."""
    if _is_number(token):
        return False
    if _is_abbreviation(token.surface) or token.grams & {'LATN', 'UNKN', 'Fixd'}:
        return True
    for case in cases:
        forms = _agreement(token, ('NOUN',), case)
        if forms and all(_is_number(m) or _agree(forms, _agreement(m, ('ADJF', 'PRTF'), case)) for m in modifiers):
            return True
    return False


def _predicative(head, adjective):
    """«Погода хорошая», «Вода мокрая»: a full adjective right after the nominative head that agrees with it in the nominative is the
    predicate of a statement, not a modifier. An ordinal is a modifier («Статья девятая»)."""
    if 'Anum' in adjective.grams:
        return False
    return _agree(_agreement(head, ('NOUN',)), _agreement(adjective, ('ADJF', 'PRTF')))


def _phrase_head(phrase, framed=False):
    """The index of the head of the noun phrase ``phrase`` (tokens), else ``None``: no word outside a noun phrase, the first noun that no
    preposition governs heads it, no phrase starts with a preposition («В первой части» is a fragment), «и» / «или» only between words.
    ``framed``: the phrase follows «про / о / насчёт» (a topic frame: «про закон спроса»), so its head is in the case that preposition takes."""
    head, governed, modifiers = None, False, []
    for k, token in enumerate(phrase):
        kind = _phrase_kind(token)
        if kind is None:
            return None
        if kind in ('adj', 'num'):
            modifiers.append(token)
            if kind == 'adj' and head is not None and k == head + 1 and _predicative(phrase[head], token):
                return None
            continue
        if kind == 'conj':
            if token.word not in ('и', 'или') or k in (0, len(phrase) - 1):
                return None
        elif kind == 'prep':
            if head is None:
                return None
            governed = True
        elif governed:
            governed = False
        elif head is None:
            if not _can_head(token, modifiers, _ANY_CASE if framed else _HEAD_CASES):
                return None
            head = k
        modifiers = []
    return head


def _names_a_topic_alone(token, text):
    """One word is a topic when it is a common inanimate noun, a surname, an abbreviation or an unknown word, and not exclaimed: «Мама»,
    «Лёша» call somebody, «Ужас!» exclaims, a slang or obscene word is no term."""
    if str(text).rstrip().endswith('!') or _is_number(token):
        return False
    if _is_abbreviation(token.surface) or token.grams & {'LATN', 'UNKN'}:
        return True
    if token.pos != 'NOUN' or token.grams & _NOT_A_TOPIC_ALONE or token.lemma in SOUND_CAPTIONS:
        return False                                              # fix round 1: «Музыка», «Аплодисменты» - a caption, no term
    return 'anim' not in token.grams or 'Surn' in token.grams


SAID_BACK_TAIL = 2               # so many last words of an utterance, found in their order in the waiting portion, make its question word the speaker's own way of saying the portion
SAID_BACK_OWN = 0                # ... while it adds no more than so many words of meaning of its own (``_own_meaning``): «что говорит статья 21 …» adds «говорит» and asks
_GARBLE_SIMILAR = 0.6        # a word this like a word of the portion is the ear's spelling of it
_LINKING_POS = frozenset({'CONJ', 'PRCL', 'INTJ', 'ADVB', 'PREP'})      # the best reading of a word that links what is said and carries no meaning of its own


def _lemma_of(word):
    """The lemma of the best reading of a normalized word, the word itself when there is none."""
    return (_readings(word)[:1] or ((None, (), word),))[0][2]


def _introduces(word):
    """Is the best reading of ``word`` the speaker's own frame of speaking, not its subject: a pronoun, a verb in the 1st person, an imperative, a gerund
    («я говорю», «скажем», «говоря»)? «говорит» (3rd person) is the subject's own verb and stays a word of meaning."""
    pos, grams, _ = (_readings(word)[:1] or ((None, frozenset(), word),))[0]
    return pos == 'NPRO' or (pos in ('VERB', 'INFN', 'GRND') and bool(grams & {'1per', 'impr', 'GRND'}))


def _own_meaning(words, portion, fillers, asking, garble=False):
    """How many words of the utterance, other than its question word, the fillers, the introductory words and the waiting portion's own words (by lemma, in
    any case), carry meaning (a verb, a noun, an adjective, a number ...). «что соответственно нужны были» over «Нужны были …»: 0 (an adverb).
    ``garble``: a word that is only the ear's wrong spelling of a word of the portion (similar to it, ``_GARBLE_SIMILAR``) is the portion's own too."""
    have = {_lemma_of(word) for word in portion}
    return sum(1 for i, word in enumerate(words)
               if i != asking and _lemma_of(word) not in have and word not in fillers | _SEAMS | _PART_FILLERS and not _introduces(word)
               and not (garble and any(Indel.normalized_similarity(word, kept) >= _GARBLE_SIMILAR for kept in portion))
               and (_readings(word)[:1] or ((None, (), word),))[0][0] not in _LINKING_POS)


def _topic_phrase(text, fillers, state=None):
    """Rule 1: the topic phrase that ``text`` is after its lead particles, fillers and an explicit «вопрос (получается)», as it was said
    («ну хоть девятая статья налогового кодекса» -> «девятая статья налогового кодекса»), else ``None``."""
    from .followup import told_back      # the one reader of what was told (the follow-up module reads the engine's history for it, as for what was asked)
    tokens = _tokens(text)
    words = [token.word for token in tokens]
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token.word in fillers or token.word in HESITATION_WORDS or token.word in TOPIC_LEADS:
            i += 1
            continue
        end = question_marker_end(words, i)
        if end is not None:
            i = end
            continue
        if token.pos in ('PRCL', 'INTJ', 'CONJ') and token.word not in ('не', 'ни', 'что', 'как'):
            i += 1                                                # «вот», «это» as a particle, «блин», «а»
            continue
        break
    phrase = tokens[i:]
    ticket = _ticket(text, phrase, words)
    if ticket is not None:
        return None if told_back(ticket, state) else ticket
    if not 1 <= len(phrase) <= TOPIC_MAX_WORDS or courtesy(words) or _broken(text, phrase):
        return None                                               # a vocative («Здравствуйте, Мария Ивановна»), a roll call («Петров, к доске»)
    framed = len(phrase) >= 2 and phrase[0].word in _TOPIC_PREPOSITIONS      # «про закон спроса и предложения»
    body = phrase[1:] if framed else phrase
    head = _phrase_head(body, framed)
    if head is None or not _names_a_topic(body, head):
        return None
    if len(phrase) == 1 and not _names_a_topic_alone(phrase[0], text):
        return None
    said = str(text)[phrase[0].start:phrase[-1].end]
    return None if told_back(said, state) else said


def _ticket(text, phrase, words):
    """c7-meta round 2 (W4: «Лизинг. Определение, виды лизинга.», «Факторинг, определение, виды факторинга»): an exam ticket line - a topic
    noun phrase, then after a break (a period, a colon, a comma, a dash) its aspects, each a noun phrase headed by an aspect noun
    (``user_intents.TICKET_ASPECTS``: определение, виды, классификация, учёт, оценка …). It is ONE topic question, the line as it was said;
    else ``None``. The ear hears it without punctuation, as one noun phrase: the same question."""
    if not 2 <= len(phrase) <= TICKET_MAX_WORDS or courtesy(words):
        return None
    parts, current = [], [phrase[0]]
    for left, right in zip(phrase, phrase[1:]):
        if _CLAUSE_BREAK.search(str(text)[left.end:right.start]):
            parts.append(current)
            current = []
        current.append(right)
    parts.append(current)
    if len(parts) < 2:
        return None
    head = _phrase_head(parts[0])
    if head is None or not _names_a_topic(parts[0], head) or (len(parts[0]) == 1 and not _names_a_topic_alone(parts[0][0], 'x')):
        return None
    for part in parts[1:]:
        at = _phrase_head(part)
        if at is None or part[at].lemma not in TICKET_ASPECTS:
            return None
    return str(text)[phrase[0].start:phrase[-1].end]


def _broken(text, phrase):
    """Is there a clause break inside the phrase (a comma, a dash, a colon: «Хорошая работа, Иван», «Имя, фамилия»)? A decimal point or comma
    between two digits is none («статья 25.1»)."""
    for left, right in zip(phrase, phrase[1:]):
        gap = str(text)[left.end:right.start]
        if _CLAUSE_BREAK.search(gap) and not (gap.strip() in ('.', ',') and left.word.isdigit() and right.word.isdigit()):
            return True
    return False


def _ordinary_capitals(token):
    """A word written in capitals that is an ordinary dictionary word (not an abbreviation, a name or an indeclinable word): a caption."""
    return (_is_abbreviation(token.surface) and len(token.word) >= 4 and token.pos is not None
            and not token.grams & {'Abbr', 'Name', 'Surn', 'Patr', 'Geox', 'Orgn', 'Fixd', 'UNKN', 'LATN'})


def _names_a_topic(body, head):
    """Ruling 4 of fix round 1: what heads no topic - a dialogue noun («Хороший вопрос»), a person («Пушкин», «Иван Петрович»), an
    interjection-like noun («Удачи», «Тишина в классе»), only hold words («Секунду», «Момент»), a noun whose only modifiers are evaluations
    («Хорошая работа», «Интересная мысль»), a caption in capitals («ДИНАМИЧНАЯ МУЗЫКА»)."""
    lead = body[head]
    if lead.lemma in DIALOGUE_NOUNS or lead.lemma in INTERJECTION_HEADS:
        return False
    if not _is_abbreviation(lead.surface) and lead.grams & {'Name', 'Surn', 'Patr'}:
        return False
    nouns = [token for token in body if _phrase_kind(token) == 'noun']
    if nouns and all(token.lemma in HOLD_NOUNS for token in nouns):
        return False
    adjectives = [token for token in body if _phrase_kind(token) == 'adj']
    if adjectives and len(body) == len(adjectives) + 1 and all(token.lemma in EVALUATIVE_ADJECTIVES for token in adjectives):
        return False
    capitals = [_ordinary_capitals(token) for token in body]
    return not (all(capitals) or any(a and b for a, b in zip(capitals, capitals[1:])))


def _clauses_of(text, tokens):
    clauses, current = [], []
    for k, token in enumerate(tokens):
        if current and _CLAUSE_BREAK.search(str(text), tokens[k - 1].end, token.start):
            clauses.append(current)
            current = []
        current.append(token)
    return clauses + [current] if current else clauses


def _clause_names(clause):
    """Does the clause name something (ruling 3 of fix round 1): a content noun in any case, after a preposition too, a Latin word, an
    abbreviation or a number; «о себе», «про него» (an «about» phrase with a person); «по-английски». The nouns of the prompter's work
    («по одному слову», «первым ответом», «в итоге») and pronouns name nothing."""
    for k, token in enumerate(clause):
        if _is_number(token) or 'LATN' in token.grams or _is_abbreviation(token.surface):
            return True
        if token.pos == 'NOUN' and token.lemma not in _WORK_NOUNS:
            if token.lemma in SPAN_NOUNS and k and any(lemma in TOTALITY_DETERMINERS for _, _, lemma in clause[k - 1].readings):
                continue                                          # c7-meta: «всё время», «каждый раз» - an adverbial, no name
            return True
        if (token.word in _TOPIC_PREPOSITIONS and k + 1 < len(clause) and clause[k + 1].pos == 'NPRO'
                and clause[k + 1].lemma not in _NO_CONTENT_PRONOUNS):
            return True
        if token.pos == 'ADVB' and token.word.startswith('по-') and token.word.endswith(('ски', 'цки')):
            return True
    return False


def _subject_besides_you(clause):
    return any(token.pos == 'NPRO' and token.lemma in _PERSONS and 'nomn' in token.grams for token in clause)


def _remark_clauses(text):
    """The clauses of ``text`` that may carry a remark: a parenthesis «, ты сказал,» is left out when there is anything else."""
    clauses = _clauses_of(text, _tokens(text))
    if len(clauses) > 1:
        clauses = [clause for clause in clauses if not _PARENTHESIS.fullmatch(' '.join(token.word for token in clause))]
    return clauses


def _asking_clauses(text):
    """c7-meta (w3_05): the clauses a sentence's «?» asks with - from the last clause that holds a question word to the end, else the last
    clause. A fragment the controller joined in front of a remark («сформулировать …, и просто смотреть по звукам, …, ты почему так медленно
    подсказываешь?») is no part of what is asked, so its nouns never turn the remark into a question."""
    clauses = _remark_clauses(text)
    for at in range(len(clauses) - 1, -1, -1):
        if any(token.word in QUESTION_WORDS for token in clauses[at]):
            return clauses[at:]
    return clauses[-1:]


def _remark_to_prompter(text):
    """Rule 4: is ``text`` a remark to the prompter about its own work? A clause with a verb of the prompter's work (a small lemma set,
    ``user_intents.PROMPTER_SPEECH``) that names nothing (``_clause_names``), said TO the prompter - fix round 1, ruling 3: only the
    singular addresses it - a 2nd-person-singular verb («отвечаешь», «молчишь»); a past form or an infinitive with «ты» / «тебе» / «твой» in
    the clause and no other subject («ты должен был … это сказать»); a past of its misbehaviour (``PROMPTER_MISBEHAVIOUR``) when the
    utterance addresses it («ты меня подставил, либо замолчал»); unaddressed, an infinitive or an imperative of its misbehaviour only when
    nothing in the text names anything («Зачем вот это вот всё тянуть надо было»; never «Можно ли молчать на допросе?»). A verb of saying
    followed by a clause that names something is about that content («Ты говоришь, инфляция растёт», «Что ты скажешь, если тебя спросят про
    зарплату?»). A neuter or plural past is never the prompter. «Повтори», «что ты сказал» ask to hear the answer again: never a remark."""
    words = norm_words(text)
    if not words or REPEAT_VERBS.intersection(fold_asr(words)) or _HEARD_WHAT.search(' '.join(words)):
        return False
    clauses = _remark_clauses(text)
    kept = [token for clause in clauses for token in clause]
    addressed = any(token.lemma in _YOU or {'2per', 'sing'} <= token.grams for token in kept)
    names = any(_clause_names(clause) for clause in clauses)
    for at, clause in enumerate(clauses):
        verbs = [token for token in clause if token.pos in ('VERB', 'INFN') and token.lemma in PROMPTER_SPEECH
                 and not token.grams & {'1per', '3per'}]
        if not verbs or _clause_names(clause):
            continue
        said = clauses[at + 1] if at + 1 < len(clauses) else ()
        you, other = any(token.lemma in _YOU for token in clause), _subject_besides_you(clause)
        for verb in verbs:
            misbehaviour = verb.lemma in PROMPTER_MISBEHAVIOUR
            if not misbehaviour and said and _clause_names(said):
                continue                                          # what was said, or the case it is said in, names something
            if '2per' in verb.grams:
                if 'sing' in verb.grams:
                    return True
                continue                                          # «вы отвечаете»: never the prompter
            if other:
                continue                                          # «Я тебе сказал …», «Он молчал»: somebody else's act
            if 'past' in verb.grams:
                if not verb.grams & {'neut', 'plur'} and (you or (misbehaviour and addressed)):
                    return True
            elif you or (misbehaviour and not names):
                return True                                       # an infinitive or an imperative
    return False


def _clause_question(text, bank, cfg, waiting):
    """Ruling 2 of fix round 1: a remark and a direct question in one sentence («Ты молчишь, а сколько стоит баррель нефти?», «Опять ты
    тормозишь, когда было крещение Руси?»): the evidence of the question clause - the last clause, or an earlier one when the sentence ends
    with «?» - that names something and is no remark itself; asked alone, the remark dropped. Else ``None``."""
    clauses = _clauses_of(text, _tokens(text))
    asks = str(text).rstrip().endswith('?')
    for at in range(len(clauses) - 1, 0, -1):
        if at != len(clauses) - 1 and not asks:
            break
        tail = str(text)[clauses[at][0].start:]
        if not any(_clause_names(clause) for clause in clauses[at:]) or _remark_to_prompter(tail):
            continue
        found = _question_evidence(tail, norm_words(tail), bank, cfg, waiting)
        if found is not None:
            return found._replace(by_trigger=True)
    return None


def _embedded_question(text):
    """Rule 3: ``(question, frame)`` - the question embedded in a request or a complaint, as it was said («… тебе нужно обязательно сказать,
    что такое девятая статья налогового кодекса» -> «что такое девятая статья налогового кодекса»), and its frame ('asked' / 'imperative',
    ``user_intents.indirect_question``); else ``None``. It has to name something."""
    words = norm_words(text)
    found = indirect_question(words)
    if found is None:
        return None
    start, frame = found
    spans = [match.span() for match in WORDS.finditer(str(text))]
    asked = str(text)[spans[start][0]:] if len(spans) == len(words) else ' '.join(words[start:])
    # The remark around it is dropped: the question ends before a later clause about the speaker or the prompter («…, или ты опять будешь
    # молчать», «…, а то я сейчас завалюсь», «…, иначе я завалю экзамен»).
    for clause in _clauses_of(asked, _tokens(asked))[1:]:
        if any(token.pos == 'NPRO' and token.lemma in ('я', 'ты', 'мы') and 'nomn' in token.grams for token in clause):
            asked = asked[:clause[0].start]
            break
    asked = asked.strip().rstrip(' .!?…,;:—–-')
    return (asked, frame) if asked and _names_something(asked, governed_too=True) else None


def _sentences(text):
    """``[(start, stop), …]`` of the sentences of ``text`` that have a word (razdel knows «РФ.», «т. е.», initials)."""
    try:
        from razdel import sentenize
        spans = [(sentence.start, sentence.stop) for sentence in sentenize(str(text))]
    except Exception:
        spans, start = [], 0
        for match in re.finditer(r'[.!?…]+(?=\s|$)', str(text)):
            spans.append((start, match.end()))
            start = match.end()
        spans.append((start, len(str(text))))
    return [(a, b) for a, b in spans if WORDS.search(str(text), a, b)]


def _rest_asks(rest, cfg):
    """Ruling 5 of fix round 1: what follows the explicit marker asks - a «?», a question word or another trigger, an indirect question or
    request, or a topic phrase (a noun head). «Вопрос такой сложный», «Вопрос не в этом» ask nothing."""
    rest = str(rest).strip()
    if not norm_words(rest):
        return False
    if rest.endswith('?'):
        return True
    body = strip_fillers(rest, cfg)
    body_words = norm_words(body)
    if body_words and (_trigger(body, body_words, cfg) or indirect_request(body_words) is not None):
        return True
    if indirect_question(norm_words(rest)) is not None:
        return True
    return _topic_phrase(rest, frozenset(cfg['fillers']) | HESITATION_WORDS) is not None


def _marker_rest(text, cfg):
    """The question after the explicit marker in its MARKER FORM (``user_intents.MARKER_FORM``: «вопрос получается / такой …», «вопрос: …»,
    «вопрос — …», «новый / следующий / другой / ещё (один) вопрос …») that opens ``text`` (after its fillers), when it asks; else ``None``."""
    body = strip_fillers(text, cfg)
    found = MARKER_FORM.match(body)
    if not found:
        return None
    rest = body[found.end():].strip()
    return rest if _rest_asks(rest, cfg) else None


def _opens_with_marker(sentence, cfg):
    return _marker_rest(sentence, cfg) is not None


def _clause_marker(text, cfg):
    """Ruling 6 of fix round 1: the marker at the start of a later clause («Ну и короче я готов, а какой вопрос, вопрос получается 21-ая
    статья …»): the evidence of what follows it, else ``None``."""
    clauses = _clauses_of(text, _tokens(text))
    for clause in reversed(clauses[1:]):
        rest = _marker_rest(str(text)[clause[0].start:], cfg)
        if rest is not None:
            return _Evidence(True, 'question_explicit_prefix', rest, None, False)
    return None


def _reports(token):
    """Does ``token`` (a word of a clause) open a report: a verb of saying, knowing, thinking or feeling in the indicative («сказала», «знаю», «думал»; no imperative, no «ты»)?"""
    return token.word in _THAT_WORDS or token.pos == 'VERB' and token.lemma in _THAT_VERBS and 'indc' in token.grams and not {'impr', '2per'} & set(token.grams)


def _last_clause_question(text, fillers):
    """Ruling 6 of fix round 1, nothing waiting: the last clause of a comma-joined preface that starts with a question word (or «что такое»,
    or a preposition and a question word) and names something is the question («Хорошо, с этим разобрались, теперь другое, когда отменили
    крепостное право»). Not a relative clause after a noun («в парке, где растут дубы») nor the complement of a finite verb («Он рассказал,
    как поймал щуку», «Не помню, в каком году …»), unless a colon announces it."""
    clauses = _clauses_of(text, _tokens(text))
    if len(clauses) < 2:
        return None
    clause, before = clauses[-1], clauses[-2][-1]
    k = 0
    while k < len(clause) and (clause[k].word in fillers or clause[k].word in ('а', 'и', 'но')):
        k += 1
    said = [token.word for token in clause[k:]]
    if not said:
        return None
    announced = ':' in str(text)[before.end:clause[0].start]
    if not announced and any(_reports(token) for earlier in clauses[:-1] for token in earlier):
        return None      # «Она сказала, что приедет вечером, когда закончит работу»: the last clause is part of what was reported, not asked
    correlative = before.word in ('то', 'том', 'тем', 'того', 'тому', 'тот', 'та', 'те', 'тех', 'той', 'ту')   # «я про то, как …»
    if not announced and ((before.pos == 'NOUN' and before.lemma not in DIALOGUE_NOUNS) or before.pos == 'VERB' or correlative):
        return None
    asks = ((said[0] in QUESTION_WORDS and said[0] not in MODAL_WORDS and said[0] != 'что')
            or said[:2] in (['что', 'такое'], ['что', 'значит'], ['что', 'означает'])
            or (said[0] in PREPOSITIONS and len(said) > 1 and said[1] in QUESTION_WORDS))
    asked = str(text)[clause[k].start:].strip()
    if not asks or not _names_something(asked, governed_too=True):
        return None
    return _Evidence(True, 'question_word', asked, None, True)


def _attempt_like(heard, portion, cfg, fillers):
    """The attempt condition of ``_mismatch``: shares a content stem with the waiting portion and is about as long as it."""
    return (bool(portion) and bool(_content_stems(heard, fillers) & _content_stems(portion, fillers))
            and len(heard) <= len(portion) + cfg['attempt_extra_words'])


def _sentence_turn(text, bank, cfg, fillers, state, waiting, nothing_waits, known=None, first=True, free=False, whole=True):
    """What one sentence is: ``('q', evidence)`` a question (rule 3, the existing triggers, rule 1 when nothing waits), ``('r', None)`` a
    remark to the prompter (rule 4), ``('n', None)`` anything else (chat, small talk, a premise). ``known``: the evidence already found for
    this very text; ``first``: the first sentence of the utterance; ``free``: no portion waits and nothing is being made (classic route)."""
    words = norm_words(text)
    if not _skip_fillers(words, fillers) or is_small_talk(words, fillers) or is_rhetorical(words):
        return 'n', None
    embedded, remark = _embedded_question(text), _remark_to_prompter(text)
    found = known if known is not None else _question_evidence(text, words, bank, cfg, waiting)
    if found is not None and found.reason == 'question_explicit_prefix' and not first and _marker_rest(text, cfg) is None:
        found = None                                              # ruling 5: after the first sentence only the marker form is one
    # The asked-for frames («тебе нужно сказать, что такое X», «можешь объяснить, …») always give the embedded question; an imperative
    # («Объясни, почему …») only rescues a sentence that asks nothing strong by itself, or one inside a remark («Ты тупишь, лучше скажи, …»).
    if embedded is not None and (embedded[1] == 'asked' or remark or found is None or not found.strong):
        # While a portion waits the strength rule holds as for any question: «Скажи, где ключи» (two words) never retires it.
        strong = not waiting or len(norm_words(embedded[0])) >= cfg['cancel_min_words']
        return 'q', _Evidence(strong, 'indirect_question', embedded[0], None, True)
    if remark:
        clause = _clause_question(text, bank, cfg, waiting)          # ruling 2: «Ты молчишь, а сколько стоит баррель нефти?»
        if clause is not None:
            return 'q', clause
        if not (str(text).rstrip().endswith('?') and any(_clause_names(c) for c in _asking_clauses(text))):
            return 'r', None                                      # a trailing «?» that names something is never dropped as a remark
    if found is None:
        rest = _marker_rest(text, cfg)                            # c7-meta round 2: «Следующий билет: факторинг, определение, виды.»
        if rest is not None:
            found = _Evidence(True, 'question_explicit_prefix', rest, None, False)
    if found is None:
        found = _clause_marker(text, cfg)                         # ruling 6: «…, вопрос получается X»
    if found is None and free:
        found = _last_clause_question(text, fillers)              # ruling 6: «…, теперь другое, когда отменили крепостное право»
    if found is not None:
        return 'q', found
    if nothing_waits:
        topic = _topic_phrase(text, fillers, state)
        if topic is not None:
            return 'q', _Evidence(True, 'topic_phrase', topic, None, True)
    elif waiting and whole and not (state.get('pending_turn') or state.get('asked_in_flight')):   # the whole utterance only
        topic = _topic_phrase(text, fillers, state)
        if topic is not None and _next_ticket(topic, state, fillers, text):
            return 'q', _Evidence(True, 'topic_while_waiting', topic, None, True)
    return 'n', None


_NOT_CONTENT_NOUNS = DIALOGUE_NOUNS | HOLD_NOUNS | INTERJECTION_HEADS | SOUND_CAPTIONS | PROMPTER_WORK_NOUNS


def _move_on(text):
    """Is ``text`` an examiner's «move on» line without content: a word of going on (``MOVE_ON_NEXT``), a unit of the exam
    (``MOVE_ON_UNITS``) and nothing but leads (``MOVE_ON_LEADS``), by lemma?"""
    tokens = _tokens(text)
    lemmas = [token.lemma for token in tokens]
    if not tokens or len(tokens) > 8:
        return False
    going = [lemma in MOVE_ON_NEXT or token.word in MOVE_ON_NEXT for token, lemma in zip(tokens, lemmas)]   # «дальше»: COMP of «далёкий»
    if not any(going) or not any(lemma in MOVE_ON_UNITS for lemma in lemmas):
        return False
    return all(on or lemma in MOVE_ON_UNITS or lemma in MOVE_ON_LEADS or token.word in MOVE_ON_LEADS
               for token, lemma, on in zip(tokens, lemmas, going))


def _next_ticket(topic, state, fillers, said=''):
    """c7-meta round 2 (w4_02: «Оценка основных средств и учёт их наличия.» while a portion of the previous answer waits): in an oral exam the
    examiner moves on without a marker. A topic phrase that is the whole utterance names a NEW question while a portion waits when it has at
    least two content nouns (no name, no dialogue, hold or caption noun) and shares no content stem with the answer that waits or its question
    - a short noun phrase, a name, an evaluation, a one-noun remark, a phrase about the answer stay what they were (bystander protection)."""
    said = str(said or topic).strip()
    if said[-1:] in ',:;—–-' or norm_words(said)[:1] == ['это']:
        # c7-meta's gate tightening (cc4180d), carried into the merge (integ10, teacher scenarios: «Это посторонний рассказ о погоде и
        # школьном расписании.» ended the answer): an open fragment («часть атмосферы на высоте,») or a statement («Это …») is no ticket
        return False
    tokens = _tokens(topic)
    nouns = [token for token in tokens if _phrase_kind(token) == 'noun' and token.lemma not in _NOT_CONTENT_NOUNS
             and not token.grams & {'Name', 'Surn', 'Patr'}]
    # c8 (cc4180d's remaining rules): the head is the phrase's first noun. «Билет номер семнадцать …», «Билет по экономике …»: the exam's
    # unit, no topic of its own (with a topic after a marker it is the explicit «Следующий вопрос: …», decided elsewhere).
    head = next((token for token in tokens if _phrase_kind(token) == 'noun'), None)
    if head is None or head.lemma in MOVE_ON_UNITS:
        return False
    # Coordinator, candidate 7 (decision-diff gate): two nouns alone were also «Звонок телефона», «Конец связи», «Адрес доставки», «Номер
    # заказа» - bystander phrases that would end the answer. A ticket while an answer waits needs three content nouns, or an aspect noun
    # (TICKET_ASPECTS: «Методы ценообразования») AT ITS HEAD (c8, cc4180d: «Фильм про историю», «Телефон для примера» are not headed by
    # their aspect word), or two noun phrases joined by «и» / a comma / a colon.
    joined = bool(re.search(r'\sи\s|[,:;—–]', str(topic)))
    if len(nouns) < 2 or (len(nouns) < 3 and not joined and head.lemma not in TICKET_ASPECTS):
        return False
    told = [str(state.get('question') or ''), str(state.get('answer') or '')] + [str(chunk) for chunk in state.get('chunks') or ()]
    answer = _content_stems(norm_words(' '.join(told)), fillers)
    return not (_content_stems(norm_words(topic), fillers) & answer)


def _asks_anew(turns, sentences, first, last, portion, fillers):
    """Owner call 20:10 («71 план счетов про что? Блядь, не работает.», «… Так, план счетов, семьдесят первый счет, это что? Про что счет? Сейчас
    скажу» while a portion waits): among the sentences of the question run, one that is a strong question by itself, names something and
    has a content word the waiting portion does not is a complete new question - the chat around it does not keep it from retiring the
    portion (one sentence alone already would)."""
    told = _content_stems(portion, fillers)
    return any(turns[k][0] == 'q' and turns[k][1] is not None and turns[k][1].strong and _names_something(sentences[k], True)
               and _content_stems(norm_words(sentences[k]), fillers) - told for k in range(first, last + 1))


def _new_turn(raw, heard, bank, cfg, fillers, state, waiting, portion, evidence):
    """Step 6 with the rules of wave F (see the block comment): a ``Decision`` to give at once (a remark to the prompter), or the evidence
    step 6 goes on with - the existing one, or the question the rules found. ``evidence``: what ``_question_evidence`` found for ``raw``."""
    if evidence is not None and evidence.prepared is not None:
        return evidence                                           # a prepared question keeps its meaning
    free = not waiting and not (isinstance(state, dict) and state.get('pending_turn'))
    # Fix round 1, ruling 4: no topic phrase while the controller holds an accepted question whose answer has not begun (``asked_in_flight``,
    # ControlledMedia._heard_with): a restated topic or the tail of a cut question never replaces it.
    nothing_waits = free and not (isinstance(state, dict) and state.get('asked_in_flight'))
    spans = _sentences(raw) or [(0, len(raw))]
    sentences = [raw[a:b] for a, b in spans]
    turns = [_sentence_turn(sentence, bank, cfg, fillers, state, waiting, nothing_waits, evidence if len(spans) == 1 else None,
                            first=k == 0, free=free, whole=len(spans) == 1) for k, sentence in enumerate(sentences)]
    asking = [k for k, (kind, _) in enumerate(turns) if kind == 'q']
    if any(kind == 'r' for kind, _ in turns) and not any(_names_something(sentences[k], True) for k in asking):
        # A remark, with nothing else asked but a bare «почему?» («Ты опять тупишь. Почему?»). A try at the waiting portion stays one.
        if waiting and _attempt_like(heard, portion, cfg, fillers):
            return evidence
        return Decision(QUIET, 'remark_to_prompter', None, None)
    if not asking:
        return evidence
    last = first = asking[-1]
    while first > 0 and turns[first - 1][0] == 'q':
        first -= 1
    named = [k for k in range(first, last + 1) if _names_something(sentences[k], True)]
    if named:
        first = named[0]                                          # «А какой вопрос?», «Ты готов?» before the question: chat
    marked = next((k for k in range(last, first - 1, -1) if _opens_with_marker(sentences[k], cfg)), None)
    if marked is not None:
        first = marked                                            # «… Вопрос получается X»: everything before the marker is chat
    else:
        while first > 0 and turns[first - 1][0] == 'n' and _names_something(sentences[first - 1]):
            first -= 1                                            # a premise («Велосипедист едет …») stays with its question
    stop = len(spans)
    while stop - 1 > last and turns[stop - 1][0] == 'r':
        stop -= 1
    lead = turns[first][1]
    if len(spans) == 1:
        return lead
    if waiting and not (evidence is not None and evidence.strong) and marked is None and not _asks_anew(turns, sentences, first, last, portion,
                                                                                                         fillers):
        return evidence                                           # bystander sentences never retire a waiting portion by themselves
    if lead is not None and stop - 1 == first:
        return lead._replace(strong=True)                         # one sentence: its own evidence (a prepared question stays one)
    end = spans[stop - 1][1]
    if lead is not None:
        # c7-meta round 2 (w4_04): the lead keeps the mark that ended its sentence - «Лизинг» + « Определение, виды лизинга.» made one broken
        # sentence the engine classified again at publish (not a question: the answer was never published and the watchdog spoke)
        head = lead.asked.rstrip()
        mark = re.search(r'[.!?…]+\s*$', sentences[first])
        if mark and not head.endswith(mark.group().strip()):
            head += mark.group().strip()
        asked = (head + raw[spans[first][1]:end]) if stop - 1 > first else lead.asked
    else:
        asked = strip_fillers(raw[spans[first][0]:end], cfg)
    reason = (lead or turns[last][1]).reason
    return _Evidence(True, reason, asked.strip(), None, True)


_PROCESS_QUESTION = re.compile(r'(?:^|\s)(?:как(?:ой|ая|ое)|что)\s+(?:(?:у\s+нас|там|теперь|же|а)\s+)*(?:(?:дальше|далее|следующ\w+|потом)\s+)?(?:(?:у\s+нас|там|теперь)\s+)*'
                               r'(?:(?:вопрос|пункт|слайд|билет)(?:\s+(?:по\s+списку|из\s+зала|по\s+плану|в\s+плане|на\s+очереди))?|дальше\s+по\s+(?:плану|списку))\s*$')

_NOT_KNOWING = re.compile(r'^(?:(?:да|а|ну|так)\s+)*(?:откуда|почем|почём)\s+(?:ж\s+|же\s+)?(?:я|мне)\s+(?:знаю|знать)\b(?!\s+(?:что|как|где|когда|сколько|почему|зачем|какой|какая|какие|кто|ли)\b)')
_PROCESS_MARK = re.compile(r'по\s+списку|из\s+зала|по\s+плану|на\s+очереди')      # a bare «какой следующий вопрос?» is the job's to decline (H2, BRAIN: «о том, какой вопрос следующий»)


def analyze(text, state, bank, settings=None, *, diagnose=False):
    """Classify one utterance; returns ``Decision(kind, reason, question, prepared)``.

    The order of the decision is the one in the module docstring; the numbers in the comments are its steps. g31: what they leave silent or
    take for a topic of its own and is a follow-up of the exchange before («а пассивный», «а КО-2», «а счёт 62», «и ещё») is that question (``_context``).
    """
    text = heard_spelling(text)      # the ear's «што такое налог» is «что такое налог», once, at the entry
    said = _dictation_said(text, state)
    if said:      # c22-repeat: «диктуй медленно», «хватит диктовать»: a setting of the prompter, nothing to answer, no try (the controller turns dictation on or off)
        return Decision(QUIET, f'dictation_{said}', None, None)
    return _context(_decide(text, state, bank, settings, diagnose), text, state, settings)


def _dictation_said(text, state):
    """c22-repeat: "on" / "off" when ``text`` is the dictation command (``repeat_rule.dictation_command``) and no word of the waiting portion."""
    if not isinstance(text, str):
        return None
    from .repeat_rule import dictation_command
    said = dictation_command(text)
    portion = waiting_portion(state) if state else None
    if said and portion and frozenset(norm_words(text)) & frozenset(norm_words(portion)) - {'я', 'не', 'без', 'как'}:
        return None
    return said


# g31-context: what ``_decide`` leaves silent while it may be a follow-up; a repeat, an attempt, a command keep their decision.
# A follow-up (or a clarification) has nothing to hang on while the answer before it is still being made: the ONE quiet ruling of all the places that judge one.
_HELD_FOR_ANSWER = Decision(QUIET, 'short_followup_while_generation_pending', None, None)
_CONTEXT_SILENT = frozenset({'not_a_question', 'clarification_without_answer', 'mismatch_policy_silent', 'unrelated_speech', 'weak_question_ignored'})


def _context(decision, text, state, settings):
    """g31: ``decision`` stands unless ``text`` is a follow-up that ``followup.complete`` completes with the questions of ``state``: then it is a
    QUESTION as it was said (the controller completes it for the bank and the model), quiet while the answer before it is being made. Words of the
    waiting portion are a try at it, never a follow-up; while a portion waits only a swap is a question: a bare «почему», «то есть» is the owner thinking aloud."""
    if not state or not isinstance(text, str) or not (decision.kind == QUIET and decision.reason in _CONTEXT_SILENT or decision.reason == 'topic_phrase'):
        return decision
    from .engine import asked_of
    from .followup import complete, soft
    raw = text.strip()
    got = complete(raw, asked_of(state))
    if got is None or (decision.reason == 'topic_phrase' and got.kind != 'swap'):
        return decision
    portion = waiting_portion(state)
    if portion is not None:
        cfg = resolve(settings)
        fillers = frozenset(cfg['fillers']) | HESITATION_WORDS
        heard, said = _skip_fillers(norm_words(raw), fillers), norm_words(portion)
        if got.kind != 'swap' or soft(raw) or _contains(said, heard) or _content_stems(heard, fillers) & _content_stems(said, fillers):
            return decision
    if state.get('pending_turn'):
        return _HELD_FOR_ANSWER
    return Decision(QUESTION, 'context_followup', raw, None)


def _decide(text, state, bank, settings=None, diagnose=False):
    """The decision before g31 (``analyze``). ``diagnose``: the reading that tells apart what the call's verdict folds into silence (an attempt at the portion, a repeat cover, a clarification: REPLAY and the reasons ``attempt_*``); the call's own verdict is the silent one."""
    cfg = {**resolve(settings), 'diagnose': diagnose}
    raw = '' if text is None else str(text).strip()
    words = norm_words(raw)
    if not words:
        return Decision(QUIET, 'empty', None, None)
    fillers = frozenset(cfg['fillers']) | HESITATION_WORDS
    clarifications = frozenset(cfg['clarifications'])
    heard = _skip_fillers(words, fillers)
    portion_text = waiting_portion(state)
    waiting = portion_text is not None
    portion = norm_words(portion_text) if waiting else []
    whole, bare = ' '.join(words), ' '.join(heard)
    repeat_requested = _is_repeat_command(whole) or _is_repeat_command(bare) or is_repeat_request(words, fillers)
    # ASR may merge an attempted beginning of the current portion with the
    # explicit hearing-repair command after a pause. Accept only a prefix
    # of this exact waiting portion, never an arbitrary preceding question.
    if waiting and not repeat_requested:
        repeat_requested = any(heard[:i] == portion[:i] and _is_repeat_command(' '.join(heard[i:]))
                               for i in range(1, min(len(heard), len(portion) + 1)))
    # «не расслышал», «что?», «а?», «как?»: a request to hear the portion again, but only while a portion waits (with
    # nothing waiting «как?» is the follow-up question «how?»). A phrase on the clarification list keeps meaning
    # «replay» in the diagnostic reading; every other certain request, and every one in the call's own verdict (the
    # silent one), is a repeat request. A bare «а» or «ещё» is too ambiguous and needs a question mark.
    hearing_request = interjection = False
    if waiting:
        found = hearing_repair(words, fillers)
        if found:
            phrase, how = found
            listed = phrase in clarifications
            certain = (how == 'phrase' or raw.endswith('?') or phrase in CERTAIN_WITHOUT_QUESTION_MARK
                       or (listed and phrase not in AMBIGUOUS_WITHOUT_QUESTION_MARK))
            if certain and not (listed and cfg['diagnose']):
                hearing_request, interjection = True, how == 'interjection'
    asks_repeat = repeat_requested or hearing_request

    # 1. A full repeat of the portion that waits is an ack, whatever else it looks like (a question, a command).
    attempt = False
    if waiting:
        from .ru_alignment import match_current
        # F1: what the listener has confirmed of this answer - a repeat may start with its end («централизованно по плану»)
        index = state.get('chunk_index', 0)
        matched = match_current(raw, portion_text, fillers, before=' '.join((state.get('chunks') or [])[:index]) or None, garble=True)
        if matched == 'ack':
            return Decision(ACK, 'ack_ru_canonical', None, None)
        # Owner-delegated ruling (3 Nov, wave W1): a repeat said as a restatement - «Значит, …», «То есть …», «Итак, …» - is the
        # repeat: the lead-in is dropped and the rest must still be the whole portion (numbers, «не» and every word as always).
        lead = _ACK_LEAD_IN.match(raw)
        if lead and match_current(raw[lead.end():], portion_text, fillers, garble=True) == 'ack':
            return Decision(ACK, 'ack_after_lead_in', None, None)
        # H5 item 4: a try at the portion that takes a word back is judged on what stands. The word taken back says nothing, of a number too.
        corrected = self_corrected(raw)
        if corrected and match_current(corrected[1], portion_text, fillers, lenient=False) == 'ack' and _tries_at(corrected[0], portion, fillers):     # H6 item 4: only when what follows IS the portion
            return Decision(ACK, 'ack_self_corrected', None, None)
        attempt = matched == 'attempt' or _near(heard, portion)
        # U85: «что» + a word of meaning of one's own, said over the ending of the portion («что нужны были пушки обувь» over «Нужны были мундиры, обувь,»), is the
        # question asked, not a try: the alignment forgives one wrong word of a repeat, but the listener's own «что <новое слово>» is no spelling of the portion's word.
        asked_what = next((i for i, word in enumerate(words) if word in QUESTION_WORDS), None)
        if (attempt and matched != 'ack' and asked_what is not None and words[asked_what] == 'что' and words[asked_what + 1:asked_what + 2] not in (['такое'], ['значит'], ['означает'])
                and _own_meaning(words, portion, fillers, asked_what, garble=True) > SAID_BACK_OWN):
            attempt = False
    # 2. Stop: the utterance is essentially a stop word. It outranks a mere attempt («стоп» for the portion «Стоп сигнал ...»). W1F-C: a hold
    #    word that the waiting portion itself says («Подождите» for «Подождите пять минут,») is the first piece of a repeat, not a pause.
    if is_stop(words, fillers) and not (waiting and _partial_of(heard, portion) and not STOP_WORDS.intersection(fold_asr(heard))):
        return Decision(STOP, 'stop_command', None, None)
    # 2b. g29 (both talk at once): the owner's own words of the portion, then the friend's question («Пассивный счёт учитывает | какой срок уплаты НДС»):
    #     the question said over them is the question. Needs the owner's words to be the portion's (two content words of it), a question word
    #     after them, and a rest that is a question by itself and brings a content word the portion does not have.
    if waiting:
        over = _question_over_owner(words, portion, state, bank, cfg, fillers)
        if over is not None:
            return over
    # 3. An attempt at the portion is never a new question. A repeat request outranks it, except when the request is
    #    itself a quotation of the portion («Повтори я не расслышал» inside a longer portion); a one-word «что?» is a request.
    if attempt:
        quoting = bool(heard) and len(heard) < len(portion) and _contains(portion, heard)
        if not asks_repeat or (quoting and not interjection):
            return Decision(REPLAY if cfg['diagnose'] else QUIET, 'attempt_ru_alignment', None, None)
    if state and state.get('repair_clarification') and whole == normalize(REPAIR_PROMPT):
        return Decision(QUIET, 'local_repair_prompt_echo', None, None)
    if (whole in GREETINGS or bare in GREETINGS) and not state:
        return Decision(GREETING, 'initial_greeting', None, None)
    if is_small_talk(words, fillers):
        return Decision(GREETING, 'small_talk', None, None)
    # E3a ruling 2: «Серьёзно?», «Да ладно?», «И что?»: an exclamation, not a question and not a request to hear the portion again.
    if is_rhetorical(words) or _NOT_KNOWING.match(' '.join(w for w in words if w not in fillers)):      # W13 item 9 (2_#18): «Да откуда я знаю, у Светы спроси» is a reply between others
        return Decision(QUIET, 'rhetorical_exclamation', None, None)
    # E3a-rest ruling 4: «Не понял это слово», «Непонятно слово X», «Это слово мне незнакомо», «Что это за слово?» while a portion waits ask what a
    # word means: a question «Что значит «X»?», never a replay of the same portion.
    if waiting:
        term_question = _term_question(raw, words, heard, fillers, portion_text)
        if term_question is not None:
            return Decision(QUESTION, 'term_explanation_request', term_question, None)
    # 3b. g25: a request for time («секунду», «сейчас вспомню»), alone or after a start of the portion: nothing to answer, no job; the prompter's timer helps when it is over.
    if waiting and not asks_repeat:
        paused = pause_split(words, fillers)
        if paused and (not paused[0] or _partial_of(_skip_fillers(paused[0], fillers), portion)) and not _contains(portion, fold_asr(words)[-1:]):
            return Decision(QUIET, 'pause_request', None, None)
    # 4. A repeat request.
    if repeat_requested:
        return Decision(REPEAT, 'repeat_command', None, None)
    if hearing_request:
        # «Не расслышал», «что?»: the same portion again at once. A REPLAY, not a REPEAT: in a call that was just reopened
        # (quiet_reopen) only an explicit «повтори» may present the stored position, and a stray «что?» must not.
        return Decision(REPLAY, 'replay_hearing_repair', None, None)
    # 4b. CL2 (ruling 4, amendment A): «дальше», «продолжай», «вернёмся к прошлому вопросу». Never a question by itself (the engine decides
    #     what it does: engine.going_on); a part of the waiting portion stays an attempt at it («Дальше» for «Дальше будет больше»).
    # c7-meta round 2 (w4_04): «Хорошо. Давайте следующий билет.», «Следующий вопрос.», «Дальше по билету.» with nothing after it: the
    #     current answer ends quietly (the controller retires it, nothing is cued; the cloud's «Какой именно?» to it is its reply to a chat
    #     turn), and the next topic phrase is the question. With content after it («Следующий вопрос: лизинг») it is the explicit marker.
    if _move_on(raw) and not (waiting and _partial_of(heard, portion)):
        return Decision(QUIET, 'move_on_without_content', None, None)
    # W13 item 9 (3_#18, 4_#16): a question about the course of the event («какой у нас дальше вопрос по списку», «что у нас дальше по плану»)
    #     asks nothing of the subject: nothing is dictated, no search.
    plain = ' '.join(w for w in words if w not in fillers)
    if _PROCESS_QUESTION.search(plain) and _PROCESS_MARK.search(plain) and not (waiting and _partial_of(heard, portion)):
        return Decision(QUIET, 'process_question', None, None)
    going = _going_on(words, fillers)
    if going and not (waiting and _partial_of(heard, portion)):
        return Decision(NEXT, 'next_command', raw, None) if going == 'next' else Decision(RESUME, 'resume_' + going, raw, None)
    # 4c. W1F-C (w1_08 step 8): «Ладно, возвращаемся к цунами, где мы там прервались», «Вернёмся к цунами. На чём мы остановились?» - a return
    #     to a named topic, with nothing after it but a position or repeat clause, is the topic change that the engine weighs against the
    #     conversation map (engine.going_on, ruling 4e), whatever the provider's punctuation («?» made it a question_mark question).
    topic = return_topic(words)
    if topic and not (waiting and (_partial_of(heard, portion) or _repeat_like(heard, portion, cfg, fillers))):
        return Decision(QUESTION, 'topic_change', strip_fillers(raw, cfg), None, topic)
    # 4d. W1F-C (w1_08 step 4): «На чём мы» - the beginning of a position question the recogniser cut off - asks nothing by itself; the
    #     utterance it begins is judged when it is whole (the controller's utterance assembly).
    if position_prefix(words, fillers):
        return Decision(QUIET, 'position_question_unfinished', None, None)
    # 5. A repair refers to an existing answer/question. Never infer it from a
    #    stray "нет", and never override an exact or partial expected quotation.
    if state and (state.get('question') or state.get('history')):
        # E3a-rest ruling 3: «Нет, я про X, а не Y» and its kin retire the wrong answer; the corrected request X (not the whole utterance) is asked.
        corrected = _corrected_request_text(raw, words, heard, fillers)
        fixed = _number_fix(raw, state) if corrected is None else None
        if fixed is not None:
            if waiting and heard and len(heard) < len(portion) and _contains(portion, heard):
                return _mismatch(cfg, waiting, heard, portion, fillers, 'repeat_cover')
            return Decision(CORRECTION, 'corrected_number', fixed, None)
        if corrected is not None:
            if waiting and heard and len(heard) < len(portion) and _contains(portion, heard):
                return _mismatch(cfg, waiting, heard, portion, fillers, 'repeat_cover')
            return Decision(CORRECTION, 'corrected_request', corrected, None)
        repair = _REPAIR_PREFIX.fullmatch(' '.join(fold_asr(heard))) or _self_correction(heard, state, fillers)
        dissent = disagreement(bare)
        if dissent and dissent[0] and raw.endswith('?'):
            # W1F-C: «Не согласен?», «Это ошибка?» ask; the listener's verdict is a statement. The question goes to the cloud as one.
            dissent = None
        if repair or dissent:
            if waiting and heard and len(heard) < len(portion) and _contains(portion, heard):
                return _mismatch(cfg, waiting, heard, portion, fillers, 'repeat_cover')
            target = repair.group(1) if repair else dissent[1]
            if target and _skip_fillers(target.split(), fillers):
                return Decision(CORRECTION, 'explicit_answer_repair', raw, None)
            if state.get('pending_turn'):
                return Decision(QUIET, 'repair_clarification_while_pending', None, None)
            if not cfg['diagnose']:
                if dissent:
                    # «Это неверно»: the answer was called wrong. That is a new turn (the answer is retired and the
                    # model is told), not something to ignore while the disputed portion keeps being repeated.
                    return Decision(CORRECTION, 'answer_disagreement', raw, None)
                return Decision(QUIET, 'ambiguous_repair_policy_silent', None, None)
            return Decision(CLARIFY_REPAIR, 'ambiguous_answer_repair', None, None)
    if whole in clarifications or (bare and bare in clarifications):
        return _mismatch(cfg, waiting, heard, portion, fillers, 'clarification')
    if not heard:
        return Decision(QUIET, 'only_fillers', None, None)

    # g13 (wave 17, the owner's calls 06.11): «а счёт пятьдесят восемь», «а РКО», «так а пятьдесят два это какой у нас счёт» while a portion waits
    #     are follow-ups naming a term the portion does not have: a question from the ear, not mismatch_policy_silent and 5 s of the cloud.
    from .followup import term_followup      # the one judge of follow-ups (followup.py) holds the term follow-up too
    term_asked = term_followup(raw, portion_text)
    if term_asked is not None:
        return Decision(QUESTION, 'term_followup', term_asked, None)
    # Only these exact phrasings are promoted. Keep heard wording intact for
    # generation; don't treat arbitrary mentions of "пример" as follow-ups.
    from .followup import is_followup      # U15-S7: the one predicate decides (strict: safe while a portion waits)
    short_followup = ' '.join(words) if is_followup(raw, strict=True) else None
    if short_followup:
        if state and state.get('pending_turn'):
            # A short utterance cannot safely attach to an answer that has not
            # arrived yet. This controller has no queued-follow-up mechanism.
            if not EXPLICIT.match(strip_fillers(raw, cfg)):
                return _HELD_FOR_ANSWER
        prepared_evidence = _question_evidence(raw, words, bank, cfg, waiting)
        if waiting:
            heard_variants = (words, heard)
            portion_variants = (portion, _skip_fillers(portion, fillers))
            if any(heard_variant and len(heard_variant) < len(portion_variant)
                   and any(portion_variant[i:i + len(heard_variant)] == heard_variant
                           for i in range(len(portion_variant) - len(heard_variant) + 1))
                   for heard_variant in heard_variants for portion_variant in portion_variants):
                return _mismatch(cfg, waiting, heard, portion, fillers, 'repeat_cover')
        if prepared_evidence is not None and prepared_evidence.prepared is not None:
            return Decision(QUESTION, prepared_evidence.reason,
                            prepared_evidence.asked, prepared_evidence.prepared)
        if prepared_evidence is not None and prepared_evidence.reason == 'clarification_request':
            return Decision(QUESTION, 'clarification_request', raw, None)      # U118: a short follow-up that is a clarification of the answer says so (the same question, its own reason)
        return Decision(QUESTION, 'short_contextual_followup', raw, None)

    # 6. A new turn: a question, a clarification, a «ли»-question, a change of topic.
    evidence = _question_evidence(raw, words, bank, cfg, waiting)
    # A choice of two that is the waiting portion's own words («… в пределах вклада или акций» said back) is the portion, not a question: the form alone
    # asks only what the answer does not already say.
    said_back_choice = waiting and any(portion[i:i + 3] == words[-3:] for i in range(len(portion) - 2))
    # The call of 11.11 08:45: «Нужны были мундиры, обувь,» said in the speaker's own way, «что соответственно нужны были», was a question by its «что»
    # and the whole talk was retired. A question WORD in an utterance that ENDS with SAID_BACK_TAIL words of the waiting portion in their order is the portion too.
    # Only «что», the one question word that is a conjunction too, and never «что такое / значит / означает …»: that asks about the portion's words
    # («Так что такое финансовая система» over a portion that names it; wide run of 11.11).
    # U85 (chaos search_hang): «что говорит статья 21 налогового кодекса» over «Статья 21 Налогового кодекса …» (the question asked again) ends like the
    # portion too, and was never answered. The speaker's own words of meaning (``_own_meaning``) are counted: more than SAID_BACK_OWN of them ask.
    asking = next((i for i, word in enumerate(words) if word in QUESTION_WORDS), None)
    portion_lemmas = [_lemma_of(word) for word in portion] if waiting else []
    said_back_tail = bool(waiting and len(words) >= SAID_BACK_TAIL and asking is not None and words[asking] == 'что'
                          and words[asking + 1:asking + 2] not in (['такое'], ['значит'], ['означает'])
                          and any(portion_lemmas[i:i + SAID_BACK_TAIL] == [_lemma_of(word) for word in words[-SAID_BACK_TAIL:]] for i in range(len(portion) - SAID_BACK_TAIL + 1))
                          and _own_meaning(words, portion, fillers, asking) <= SAID_BACK_OWN)
    own_words = lambda found: ((said_back_choice and found.reason == 'question_alternative')      # noqa: E731
                               or (said_back_tail and found.reason in ('question_word', 'question_form')))
    if evidence is not None and own_words(evidence):
        evidence = None
    # Wave F (F2): an indirect question, a remark to the prompter, the chat before a question, a topic phrase while nothing waits.
    evidence = _new_turn(raw, heard, bank, cfg, fillers, state, waiting, portion, evidence)
    if isinstance(evidence, (Decision, _Evidence)) and own_words(evidence):
        evidence = None
    # integ9 (F1 x this step): a neighbour portion of the same answer said while one waits is a try at the answer (_answer_words_only)
    if isinstance(evidence, Decision):
        if waiting and evidence.kind == QUESTION and _answer_words_only(heard, state, cfg, raw):
            return _mismatch(cfg, waiting, heard, portion, fillers, 'answer_words')
        return evidence
    if evidence is not None and evidence.strong:
        if waiting and _partial_of(heard, portion):
            return _mismatch(cfg, waiting, heard, portion, fillers, 'repeat_cover')
        if waiting and evidence.by_trigger and _repeat_like(heard, portion, cfg, fillers):
            return _mismatch(cfg, waiting, heard, portion, fillers, 'repeat_cover')
        if waiting and _answer_words_only(heard, state, cfg, raw):
            return _mismatch(cfg, waiting, heard, portion, fillers, 'answer_words')
        if evidence.reason == 'clarification_request' and state and state.get('pending_turn'):
            # Like the short follow-ups: nothing to attach a clarification to while the answer is still being made.
            return _HELD_FOR_ANSWER
        return Decision(QUESTION, evidence.reason, evidence.asked, evidence.prepared)
    # 7. Everything else is silence (or a replay when it looks like an attempt).
    return _mismatch(cfg, waiting, heard, portion, fillers, 'weak_question' if evidence is not None else '')


_ANAPHORA = frozenset('это этот эта эти он она оно они его её ее их ему ей им'.split())
_NOT_ASKING_THAT = frozenset('потому так то чем после тем'.split())      # integ-c19: «потому что», «так что»: no question


def _question_over_owner(words, portion, state, bank, cfg, fillers):
    """g29: ``Decision`` when ``words`` are some of the waiting portion's own words and then a question of someone else, else ``None``."""
    known = set(portion)
    for j in range(2, len(words) - 2):
        if words[j] not in QUESTION_WORDS or words[j] in fillers or (words[j] == 'что' and words[j - 1] in _NOT_ASKING_THAT):
            continue
        cut = j - 1 if words[j - 1] in PREPOSITIONS else j                     # integ-c19: «в каком году» keeps its «в»
        cut = cut - 1 if cut and words[cut - 1] in _ASK_LEADS else cut
        lead = [w for w in words[:cut] if w not in fillers and len(w) >= 3]      # integ-c19: two DIFFERENT words of the portion («рублей … рублей» of a sum is one)
        rest = words[cut:]      # integ-c19: a rest that points back («вторая мировая когда это началось») asks about the words before it: the friend's whole question
        if len(lead) < 2 or len({w for w in lead if w in known}) < 2 or _ANAPHORA.intersection(rest) or len(rest) < 3 or _contains(portion, rest):
            continue
        if not set(_content_stems(rest, fillers)) - set(_content_stems(portion, fillers)):
            continue
        decision = analyze(' '.join(rest), {}, bank, dict(cfg), diagnose=cfg['diagnose'])
        if decision.kind == QUESTION:
            return Decision(QUESTION, 'question_over_owner_words', decision.question or ' '.join(rest), decision.prepared)
        return None
    return None


# --- lane A (13.11): how much of what was said is the waiting answer's own ---------------------------------------------------

def portion_share(text, state, settings=None, loose_numbers=False):
    """Lane A feature (13.11, map §8.4): the share of what was said that is the waiting answer's own words. The content stems of ``text``
    (``_content_stems``) found among the stems of the whole answer in ``state`` (every portion of it: a neighbour portion, a wrong repeat),
    over all content stems of ``text``; the numbers of each side are ONE item, matched when a value is the answer's or when one number is
    said for the answer's number(s) («девятнадцатый» for «19»). ``None``: no portion waits, or nothing of content was said. It decides
    nothing: ``ControlledMedia._question_fate`` (door asleep) reads it (a try that failed is mostly the answer's words, talk around it is not)."""
    if waiting_portion(state) is None:
        return None
    from .fast_text import _atoms, _values      # noqa: PLC0415 - fast_text imports this module (as _own_number)
    fillers = frozenset(resolve(settings)['fillers']) | HESITATION_WORDS

    def split(words):
        numeric = {word for word in words if word.isdigit() or _values(_atoms(word))}
        return _content_stems([word for word in words if word not in numeric], fillers), set(_values(_atoms(' '.join(words))))
    said, said_values = split(norm_words(text))
    wanted, answer_values = split(norm_words(' '.join(str(chunk) for chunk in state.get('chunks') or ())))
    total = len(said) + (1 if said_values else 0)
    if not total:
        return None
    if loose_numbers and said_values and answer_values:
        return 1.0      # the fast call (H2): a wrong number is said in the words of the number the listener means: any number for the answer's number is a try
    number = bool(said_values and answer_values and (said_values & answer_values or len(said_values) == 1))
    return (len(said & wanted) + (1 if number else 0)) / total
