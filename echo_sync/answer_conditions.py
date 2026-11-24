"""U80 (audit points 52, 56, 60): the probe of the answer against the conditions of its question (S1: it only REPORTS a feature, it decides nothing; the owner of the answer, ``ControlledMedia._bind_answer``, writes it down).
Narrow on purpose, no model: a rule that cannot tell the right answer tells only a condition that is plainly broken. Cases, each one conservative (a doubt is no flag):
* ``unit``: the question names the unit («в процентах», «в рублях», «в каких единицах») and the answer has a number but not that unit (nor any, for «в каких единицах»);
* ``except``: «кроме X» and the answer names X with no «кроме» / «не» of its own;
* ``period``: «сколько / какой … в 2019 году» (not «когда») and the answer has years, none of them that one.
A false premise («почему Эйнштейн получил премию за теорию относительности») and a negation of the fact need the facts: not here, they are measured on the trick set (``tools/trick_score.py``).
Nothing here changes what is said: the answer is released as it stands, the feature is a line of the log and of the call trace (no words of the dialogue)."""
import logging
import re

from .textutil import NUMBER_WORDS, UNIT_EXACT, UNIT_PREFIXES, norm_words

logger = logging.getLogger('echo-sync')
_SYMBOLS = {'процент': '%', 'рубл': '₽', 'доллар': '$', 'евро': '€', 'градус': '°'}
_SHORT = {'процент': ('проц',), 'рубл': ('руб',), 'градус': ('град',), 'километр': ('км',), 'килограмм': ('кг',), 'грамм': ('г', 'гр'), 'метр': ('м',), 'литр': ('л',), 'секунд': ('сек', 'с'), 'минут': ('мин',), 'тысяч': ('тыс',), 'миллион': ('млн',), 'миллиард': ('млрд',), 'сантиметр': ('см',), 'миллиметр': ('мм',)}
_YEAR = re.compile(r'(?<!\d)(1[0-9]{3}|20[0-9]{2})(?!\d)')
_QUANTITY = re.compile(r'\b(?:сколько|какой|какая|какое|каков|какова|какие)\b', re.I)
_PERIOD = re.compile(r'\b(?:в|за|на)\s+(1[0-9]{3}|20[0-9]{2})\s*(?:-?м)?\s*(?:году|год|г\b)', re.I)


def _has_number(text):
    return bool(re.search(r'\d', text)) or any(w in NUMBER_WORDS for w in norm_words(text))


def _prefix(word):
    return next((p for p in UNIT_PREFIXES if word.startswith(p)), None)


def _unit(question, answer):
    q, a = norm_words(question), norm_words(answer)
    if not _has_number(answer):return False
    asked = [_prefix(w) for i, w in enumerate(q[1:], 1) if q[i - 1] == 'в' and _prefix(w)]
    if asked:return not any(any(w.startswith(p) or w in _SHORT.get(p, ()) for w in a) or _SYMBOLS.get(p, '\0') in answer for p in asked)
    text = ' '.join(q)
    if 'в каких единицах' in text or 'в чем измеря' in text:
        return not any(w in UNIT_EXACT or _prefix(w) for w in a) and not any(s in answer for s in '%₽$€°')
    return False


def _except(question, answer):
    q, a = norm_words(question), norm_words(answer)
    if 'кроме' in a or 'не' in a or 'нет' in a:return False
    return any(w == 'кроме' and len(q[i + 1]) >= 4 and any(x.startswith(q[i + 1][:4]) for x in a) for i, w in enumerate(q[:-1]))


def _period(question, answer):
    year = _PERIOD.search(question)
    if not year or 'когда' in norm_words(question) or not _QUANTITY.search(question):return False
    years = set(_YEAR.findall(answer))
    return bool(years) and year.group(1) not in years


def broken(question, answer):
    """The names of the conditions of ``question`` that ``answer`` plainly breaks (``[]``: none seen, which is not «all kept»)."""
    question, answer = str(question or ''), str(answer or '')
    if not question or not answer:return []
    return [name for name, probe in (('unit', _unit), ('except', _except), ('period', _period)) if probe(question, answer)]


def report(question, answer, note=None):
    """The owner's use: the feature to the log and, when the call has one, to the trace (``note``: ``FastText.note``). Never raises, never touches the answer."""
    names = []
    try:
        names = broken(question, answer)
        if not names:return names
        logger.info('echo-sync answer_condition broken=%s', ','.join(names))
        if note:note('answer_condition', broken=','.join(names))
    except Exception as error:
        logger.warning('echo-sync answer_condition failed type=%s', type(error).__name__)
    return names
