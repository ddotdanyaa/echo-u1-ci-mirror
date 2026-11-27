"""``answer_witness`` (off | shadow): a number the job added to the answer, against GPT-Live's reply, and a third source that decides.

7:37 of 6 Nov: a job that had heard all of the question said «3 месяца, а для руководителей организаций — 6 месяцев» to the chief accountant, and the first sentence of GPT-Live's reply with a number said «до шести месяцев». Every guard of a cue reads the
QUESTION (``wide_refusal``, ``caught_up``, ``ear_disputes``, ``answer_keeps``); a number the model adds is read by none of them, and it is the worst error there is.

The owner's idea, the other way round from ``live_first``: the first portion goes from whatever is fastest, and while it is said the slower voice checks it. Pure: the words go in, a verdict comes out. In shadow the verdict is one line of the call trace
(``witness``) with the correction it would have said; nothing is said. The two voices alone decide nothing: on 6 Nov each of them was the wrong one (GPT-Live on accounts 58, 61 and 80, the job here). Only a third source does, and only when it can tell:
the rows of the law, the bank, the material. Those are no answers here: they are read clause by clause for one of two numbers.
"""
import re

from .fast_text import _is_number, _prepared, _value
from .textutil import STOPWORDS, norm_words

_SENTENCE = re.compile(r'(?<=[.!?…])\s+')
_CONTRAST = re.compile(r';|,\s*(?=(?:а|но|однако|за исключением|кроме)\s)', re.I)   # a clause of its own: «трех месяцев, а для … шести месяцев»
_SPECIAL = re.compile(r'^\s*(?:а|но|однако|за исключением|кроме)\s', re.I)
_TOKEN = re.compile(r'\S+')
_LEADS = frozenset('до за в на по от с около более менее через после не'.split())
_MARKS = '.,;:!?…»)'
MIN_SHARED = 2                   # a clause on fewer words of the question is no witness of it
CLAUSE_WORDS = 6                 # the correction: how far it reads on from the number


def numbers(text, asked=''):
    """The numbers of ``text`` by value, in the order they are said, but for those of ``asked``: a number of the question is nobody's answer."""
    try:
        known = {_value(atom) for atom in _prepared(asked) if _is_number(atom)} if asked else set()
        return list(dict.fromkeys(_value(atom) for atom in _prepared(text) if _is_number(atom) and _value(atom) not in known))
    except Exception:                     # noqa: BLE001 - not sure of the numbers: none
        return []


def first_sentence(reply, asked, *, closed=False):
    """The first sentence of the reply that says a number of its own: a filler before it holds none. Not closed: only a sentence with its mark, the last one may go on. '' when there is none yet."""
    parts = [part for part in _SENTENCE.split(str(reply or '').strip()) if part]
    for at, part in enumerate(parts):
        if (closed or (at < len(parts) - 1) or part[-1:] in '.!?…') and numbers(part, asked):
            return part
    return ''


def agree(said, sentence, asked):
    """Does the reply hold the number the job leads with? None when one of them said no number of its own: nothing to compare. The leading one: «3 месяца, а для руководителей — 6» and «до шести месяцев» share a 6, and the listener hears the 3."""
    job, reply = numbers(said, asked), numbers(sentence, asked)
    if not job or not reply:
        return None
    return job[0] in reply


def _stems(text):
    return {word[:5] for word in norm_words(text) if word not in STOPWORDS and len(word) >= 3 and not word[0].isdigit()}


def clauses(text):
    """The clauses of ``text`` that may hold a number of their own: a sentence is cut at «;» and at a contrast, not at any comma."""
    return [clause.strip() for sentence in _SENTENCE.split(str(text or '').strip()) for clause in _CONTRAST.split(sentence) if clause.strip()]


def _clause_of(question, text):
    """The clause of ``text`` on the words of the question, a special one before a general one of as many words, or None. It must share MIN_SHARED of them: a number on other words is no witness."""
    want = _stems(question)
    scored = [(len(want & _stems(clause)), bool(_SPECIAL.match(clause)), clause) for clause in clauses(text)]
    best = max(scored, key=lambda item: item[:2], default=None)
    return best[2] if best and best[0] >= MIN_SHARED else None


def decide(question, passages, job, reply):
    """``(side, source)``: which number the third source holds, 'job' or 'live', by the first passage that can tell. ``(None, None)``: none can: no clause on the question, or its clause holds both or neither."""
    for text, source in passages:
        clause = _clause_of(question, text)
        if clause is None:
            continue
        held = numbers(clause)
        if (job in held) != (reply in held):
            return ('job' if job in held else 'live'), source
    return None, None


def correction(sentence, value):
    """What would be said, in the words of the source, never paraphrased: the number, the word before it when that word binds it, what follows it to the end of its clause. '' when the number cannot be found in them."""
    tokens = _TOKEN.findall(str(sentence or ''))
    for at in range(len(tokens)):
        if not numbers(tokens[at].strip(_MARKS)):      # it begins on the number: «быть до шести» holds a 6 too
            continue
        for size in (1, 2, 3):
            if numbers(' '.join(tokens[at:at + size]).strip(_MARKS)) != [value]:
                continue
            start = at - 1 if at and tokens[at - 1].casefold() in _LEADS else at
            words = tokens[start:at + size]
            for token in tokens[at + size:at + size + CLAUSE_WORDS]:
                if words[-1][-1:] in ',;:.!?…':
                    break
                words.append(token)
            return 'Поправка: ' + ' '.join(words).rstrip(_MARKS) + '.'
    return ''


def judge(question, said, sentence, passages):
    """One case: ``{'verdict': 'differ'|'agree', 'job', 'reply', 'side', 'source', 'proposal'}``, or None when there is nothing to compare. ``proposal``: only when the third source sides with the reply: then the job's number was the wrong one, and the
    next cue would say so. With the job, or undecided: nothing is proposed."""
    same = agree(said, sentence, question)
    if same is None:
        return None
    job, reply = numbers(said, question)[0], numbers(sentence, question)[0]
    case = {'verdict': 'agree' if same else 'differ', 'job': job, 'reply': reply, 'side': None, 'source': None, 'proposal': ''}
    if not same:
        case['side'], case['source'] = decide(question, passages, job, reply)
        if case['side'] == 'live':
            case['proposal'] = correction(sentence, reply)
    return case
