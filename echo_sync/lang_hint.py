"""N134 (E82.1): the language of a question by the ear's text: alphabet and frequent words, pure, no model.

What the system does with an English question (recorded by ``tests/test_w9_fast_no.py`` on the real code, not guessed): ``classifier.analyze`` takes it as a question («?» or not), ``same_question`` compares the Latin words like
Russian ones, BRAIN says «Отвечай по-русски», so the ANSWER IS RUSSIAN and the Windows SAPI Russian voice says it; a Latin word inside a Russian answer is read with a Russian accent. English «not»/«no»/«never» were NOT protected
the way «не» is (``fast_text._protected``): see ``NEGATION_PATCH`` for the exact patch to the owner of ``fast_text.py`` (A2).
``lang_hint`` gives 'ru', 'en', 'mixed' or 'none'. An acronym or a single foreign word inside Russian speech («GDP», «НДС») stays 'ru'; Latin letters alone, without an English function word, are 'none' (a bare «GDP» tells nothing).
"""
from __future__ import annotations

import re

_LATIN = re.compile(r'[A-Za-z]')
_CYRILLIC = re.compile(r'[А-Яа-яЁё]')
_TOKEN = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")
EN_WORDS = frozenset(('the a an is are was were be do does did can could will would should what why how when where who which whose whom this that these those i you he she it we they me my your our '
                      'of to in on at for with from by and or but not no never please hello hi hey thanks thank yes okay ok there here have has had don doesn isn aren didn wasn won can cant').split())


def lang_hint(text):
    """'ru', 'en', 'mixed' or 'none' by the share of Latin letters and the English function words."""
    text = str(text or '')
    latin, cyrillic = len(_LATIN.findall(text)), len(_CYRILLIC.findall(text))
    if not latin and not cyrillic:
        return 'none'
    share = latin / (latin + cyrillic)
    english = sum(word.lower().split("'")[0] in EN_WORDS or word.lower() in EN_WORDS for word in _TOKEN.findall(text))
    if share <= 0.2:
        return 'ru'
    if share >= 0.8:
        return 'en' if english else 'none'
    return 'mixed' if english else 'ru'


def answer_language(text):
    """What the system answers in today: Russian, whatever was asked (BRAIN: «Отвечай по-русски»)."""
    return 'ru'


# Exact patch for echo_sync/fast_text.py (owner A2): English negations count like «не» in ``_protected``; «isn't» and «is not» are one, so the contraction stems fold to «not» and the bare «t» is skipped.
NEGATION_PATCH = '''--- a/echo_sync/fast_text.py
+++ b/echo_sync/fast_text.py
@@ def _protected(atoms):
     found = Counter()
     for atom in atoms:
         if _is_number(atom):
             found['#' + re.split(r'[:#]', atom.atom)[-1]] += 1
         elif atom.atom in ('не', 'ни'):
             found[atom.atom] += 1
+        elif atom.atom in _EN_NOT:
+            found['not'] += 1
     return found
'''
EN_NOT = frozenset(('not', 'no', 'never', 'nor', 'cannot', 'isn', 'aren', 'wasn', 'weren', 'don', 'doesn', 'didn', 'won', 'wouldn', 'shouldn', 'couldn', 'haven', 'hasn', 'hadn'))


# --- U19-S1: the language of THIS turn (pure, not wired; flags in settings are U19-S2) ----------------------------------------------------------------------
_WORD = re.compile(r"[A-Za-zА-Яа-яЁё0-9]*[A-Za-zА-Яа-яЁё]+[A-Za-zА-Яа-яЁё0-9]*(?:'[A-Za-z]+)?")      # a digit inside the token belongs to it: «B2», «mp3» are one token, not «B» + «mp»
_STRIP = re.compile(r'(?:https?://|www\.)\S+|\S+@\S+\.\S+')
_ROMAN = re.compile(r'^[IVXLCDM]+$')
MIN_WORDS = 3                 # an English verdict needs this many Latin words (and one function word); a Russian one needs 2
MARGIN = 0.25                 # |ru-en| / voted words below this abstains
PRIOR = 1.0                   # the previous language starts one vote ahead
EAR_UNKNOWN_SHARE = 0.5
CROSS_MIN_LEN = 4
CROSS_MAX_SHARE = 0.25
LANG_FALLBACKS = {}           # language asked for but not in LANG_RULES -> count (call_trace reads it)


def word_lang(word):
    """'ru', 'en' or None (acronym, roman numeral, name in capitals, a token with digits, mixed script): one word, one vote or none."""
    word = str(word or '')
    latin, cyr = bool(_LATIN.search(word)), bool(_CYRILLIC.search(word))
    if latin == cyr or any(ch.isdigit() for ch in word):      # a cell, a file, a model name («B2», «mp3»): a token with a digit votes for nobody
        return None
    if cyr:
        return 'ru'
    if len(word) > 1 and word.isupper() or _ROMAN.match(word):
        return None
    return 'en'


def _words(text):
    return [(m.start(), m.end(), m.group(0)) for m in _WORD.finditer(_STRIP.sub(lambda m: ' ' * len(m.group(0)), str(text or '')))]


def counts(text):
    """{'ru': n, 'en': n, 'none': n, 'function': n} over the words of the text."""
    out = {'ru': 0, 'en': 0, 'none': 0, 'function': 0}
    for _, _, word in _words(text):
        lang = word_lang(word)
        out[lang or 'none'] += 1
        out['function'] += lang == 'en' and word.lower() in EN_WORDS
    return out


class TurnLang:
    """The language owner of one call: ``observe(text)`` returns the language of this turn, 'ru' by default.
    Too little evidence or a tie keeps the previous language (sticky); the previous language has a one-vote head start."""

    def __init__(self, initial='ru'):
        self.lang, self.history, self.fallbacks = initial, [], 0

    def observe(self, text):
        c = counts(text)
        ru, en = c['ru'] + (PRIOR if self.lang == 'ru' else 0), c['en'] + (PRIOR if self.lang == 'en' else 0)
        voted = c['ru'] + c['en']
        new = self.lang
        if voted and abs(ru - en) / (voted + PRIOR) >= MARGIN:
            winner = 'ru' if ru > en else 'en'
            if winner == 'en' and (c['en'] < MIN_WORDS or not c['function']):
                winner = self.lang
            elif winner == 'ru' and c['ru'] < (1 if self.lang == 'ru' else 2):
                winner = self.lang
            new = winner
        else:
            self.fallbacks += bool(voted)
        self.lang = new
        self.history.append(new)
        del self.history[:-8]
        return new


def lang_spans(text):
    """[(lang, start, end, words)]: runs of one language; a single word joins its neighbour, words with no vote join the run before."""
    runs = []
    for start, end, word in _words(text):
        lang = word_lang(word)
        if lang is None and not runs:
            continue
        if runs and (lang is None or runs[-1][0] == lang):
            runs[-1][2], runs[-1][3] = end, runs[-1][3] + 1
        else:
            runs.append([lang, start, end, 1])
    merged = []
    for i, run in enumerate(runs):
        if run[3] == 1 and len(runs) > 1:
            if merged:
                merged[-1][2], merged[-1][3] = run[2], merged[-1][3] + 1
            else:
                runs[i + 1][1], runs[i + 1][3] = run[1], runs[i + 1][3] + 1
        elif merged and merged[-1][0] == run[0]:
            merged[-1][2], merged[-1][3] = run[2], merged[-1][3] + run[3]
        else:
            merged.append(run)
    return [tuple(r) for r in merged]


def english_runs(text):
    """[(start, end)]: the runs of ``text`` the English voice reads (tts-render): a run of ``lang_spans`` that is English by its own words (two Latin words at least, one of them an English function word). A name, a code or a Latin letter by a number
    («N 204н», «Excel») is no English run: the Russian rules say it. The ONE decision: ``speech_text.speak`` leaves these runs as written and ``sapi_worker.lang_ssml`` puts them in the English voice."""
    runs = []
    for lang, start, end, _ in lang_spans(text):
        words = [w for _, _, w in _words(text[start:end]) if word_lang(w) == 'en']
        if lang == 'en' and len(words) >= 2 and any(w.lower() in EN_WORDS for w in words):
            runs.append((start, end))
    return runs


_CYR2LAT = dict(zip('абвгдеёжзийклмнопрстуфхцчшщъыьэюя', ['a', 'b', 'v', 'g', 'd', 'e', 'e', 'zh', 'z', 'i', 'i', 'k', 'l', 'm', 'n', 'o', 'p', 'r', 's', 't', 'u', 'f', 'h', 'ts', 'ch', 'sh', 'sh', '', 'y', '', 'e', 'yu', 'ya']))


def translit(word):
    """Cyrillic word -> Latin letters (lower case); a Latin word is returned lower-cased."""
    return ''.join(_CYR2LAT.get(c, c) for c in str(word or '').lower())


_PHONE = (('ph', 'f'), ('ts', 's'), ('ch', 'c'), ('sh', 's'), ('zh', 'z'), ('yu', 'iu'), ('ya', 'ia'), ('ce', 'se'), ('ci', 'si'), ('cy', 'sy'), ('c', 'k'), ('q', 'k'), ('x', 'ks'), ('w', 'v'), ('y', 'i'), ('j', 'i'), ('h', ''))


def _key(word):
    word = translit(word)
    for a, b in _PHONE:
        word = word.replace(a, b)
    return re.sub(r'(.)\1+', r'\1', re.sub(r'[^a-z]', '', word))


def _levenshtein(a, b):
    row = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        prev, row[0] = row[0], i
        for j, cb in enumerate(b, 1):
            prev, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, prev + (ca != cb))
    return row[-1]


def cross_equal(a, b):
    """Is a Cyrillic ear word the same word as a Latin one by sound? Same script: plain equality. Short words are no evidence."""
    a, b = str(a or '').lower(), str(b or '').lower()
    if word_lang(a) == word_lang(b):
        return a == b
    ka, kb = _key(a), _key(b)
    if min(len(ka), len(kb)) < CROSS_MIN_LEN:
        return False
    return _levenshtein(ka, kb) / max(len(ka), len(kb)) <= CROSS_MAX_SHARE


LANG_RULES = {
    'ru': {'instruction': '', 'voice': 'Microsoft Irina Desktop', 'culture': 'ru-RU', 'negations': frozenset(('не', 'ни')), 'asr': 'sherpa-ru'},
    'en': {'instruction': 'Answer in English: the question was asked in English. If the user switches language, follow it. Read quoted text verbatim.',
           'voice': 'Microsoft Zira Desktop', 'culture': 'en-US', 'negations': EN_NOT, 'asr': 'sherpa-en'},
}


def answer_instructions(lang):
    """The language line for the brain prompt: '' for Russian (the prompt stays byte-identical); an unknown language is counted and answered as Russian."""
    rule = LANG_RULES.get(lang)
    if rule is None:
        LANG_FALLBACKS[lang] = LANG_FALLBACKS.get(lang, 0) + 1
        rule = LANG_RULES['ru']
    return rule['instruction']


def ear_unknown(text, known):
    """(unknown, total, share): words of the ear's text that are not in ``known`` (a set or a predicate); Latin words are always unknown to the Russian ear."""
    check = known if callable(known) else (lambda w: w in known)
    words = [w.lower() for _, _, w in _words(text)]
    unknown = sum(word_lang(w) == 'en' or not check(w) for w in words)
    return unknown, len(words), (unknown / len(words) if words else 0.0)


def ear_foreign(text, known):
    """True when the ear's text is mostly words it cannot know (share >= EAR_UNKNOWN_SHARE, at least two words)."""
    unknown, total, share = ear_unknown(text, known)
    return total >= 2 and share >= EAR_UNKNOWN_SHARE
