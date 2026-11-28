"""U25-R2: controlled changes of a call's input. A mutation changes ONE thing of a fixture (``cloud``/``ear``/``cues`` rows of ``tools.harvest.fixture``) and the rule
that defines what must follow is checked at once: ``apply`` gives ``{'fixture', 'expect', 'status'}`` where status is ``correct`` (the rule holds on the rows),
``wrong`` (the mutation did not do what it says) or ``invalid`` (it does not apply to these rows: no number, no sentence; counted, never dropped). Pure; the original
is never touched. The expectation of a text mutation is a verdict of ``meaning_guard`` (a changed number is DIFFERS; an added or dropped «не» is never SAME).
"""
import copy
import re

from echo_sync.fast_text import meaning_guard
from echo_sync.utterance_judge import DIFFERS, SAME

_DIGITS = re.compile(r'\d+')
_NOT = re.compile(r'(?<![а-яёa-z])не(?![а-яёa-z])', re.IGNORECASE)
_VERB = re.compile(r'(?<![а-яёa-z])(можно|будет|буду|есть|нужно|надо|могу|хочу|стоит|был|была|было|были|работает|понял|знаю)(?![а-яёa-z])', re.IGNORECASE)
_LATIN = dict(zip('абвгдеёжзийклмнопрстуфхцчшщъыьэюя', ['a', 'b', 'v', 'g', 'd', 'e', 'yo', 'zh', 'z', 'i', 'y', 'k', 'l', 'm', 'n', 'o', 'p', 'r', 's', 't', 'u', 'f', 'kh', 'ts', 'ch', 'sh', 'shch', '', 'y', '', 'e', 'yu', 'ya']))
USER, EAR = 'user', 'ear'


def _user_rows(fx):
    return [row for row in fx['cloud'] if row[1] == USER and row[3].strip()]


def _texts(fx):
    return [row[3] for row in _user_rows(fx)]


def _retext(fx, change):
    """``change`` the first user final it applies to (and the ear row that said the same), so ear and cloud keep one question."""
    for n, row in enumerate(fx['cloud']):
        if row[1] == USER and row[3].strip():
            new = change(row[3])
            if new is not None and new != row[3]:
                old = row[3]
                row[3] = new
                for ear in fx['ear']:
                    if ear[3].casefold().strip() == old.casefold().strip():
                        ear[3] = change(ear[3]) or ear[3]
                return old, new
    return None


def pauses(fx, scale):
    """Gaps between ear spans scaled; the spans themselves keep their length and words."""
    prev_end = None
    shift = 0.0
    for row in fx['ear']:
        if prev_end is not None:
            shift += (scale - 1.0) * (row[0] - prev_end)
        prev_end = row[2]
        row[0], row[1], row[2] = (round(v + shift, 3) for v in (row[0], row[1], row[2]))
    return None


def number(fx, step):
    def change(text):
        return _DIGITS.sub(lambda m: str(int(m.group()) + int(step)), text, count=1) if _DIGITS.search(text) else None
    return _retext(fx, change)


def negate(fx, how):
    def change(text):
        if how == 'delete':
            return _NOT.sub('', text, count=1).replace('  ', ' ') if _NOT.search(text) else None
        if _NOT.search(text) or not _VERB.search(text):
            return None
        return _VERB.sub(lambda m: 'не ' + m.group(1), text, count=1)
    return _retext(fx, change)


def language(fx, _how):
    """Every user final and ear text in synthetic Latin script (a call that switched script)."""
    def latin(text):
        return ''.join(_LATIN.get(ch.casefold(), ch) for ch in text)
    first = None
    for row in fx['cloud'] + fx['ear']:
        if (row[1] == USER or row in fx['ear']) and re.search('[а-яё]', row[3], re.IGNORECASE):
            first = first or (row[3], latin(row[3]))
            row[3] = latin(row[3])
    return first


def cloud_delay(fx, seconds):
    for row in fx['cloud']:
        row[0] = round(row[0] + seconds, 3)
    return None


def order(fx, _how):
    """The first turn's order of arrival turned round: a cloud final that came after the ear's final comes before it, and the other way round."""
    finals = [row for row in fx['cloud'] if row[1] == USER]
    if not finals or not fx['ear']:
        return 'invalid'
    ear_end = fx['ear'][0][2]
    finals[0][0] = round(ear_end - 0.5 if finals[0][0] >= ear_end else ear_end + 0.5, 3)
    return None


MUTATIONS = {'pauses': pauses, 'number': number, 'not': negate, 'language': language, 'cloud_delay': cloud_delay, 'order': order}
ARGS = {'pauses': (0.5, 2.0), 'number': (1,), 'not': ('insert',), 'language': ('latin',), 'cloud_delay': (1.0, 3.0, 8.0), 'order': ('swap',)}


def _gaps(fx):
    return [round(b[0] - a[2], 3) for a, b in zip(fx['ear'], fx['ear'][1:])]


def _check(name, arg, old, new, changed):
    """The rule of each mutation, against the rows: returns the expectation and whether it holds."""
    if name == 'pauses':
        want = [round(arg * g, 3) for g in _gaps(old)]
        return f'gaps x{arg}', all(abs(a - b) < 0.01 for a, b in zip(want, _gaps(new))) and [r[3] for r in new['ear']] == [r[3] for r in old['ear']]
    if name == 'cloud_delay':
        return f'cloud +{arg}s', all(abs(b[0] - a[0] - arg) < 0.01 and a[3] == b[3] for a, b in zip(old['cloud'], new['cloud'])) and new['ear'] == old['ear']
    if name == 'language':
        return 'latin script', not any(re.search('[а-яё]', row[3], re.IGNORECASE) for row in new['ear'] + [r for r in new['cloud'] if r[1] == USER])
    if name == 'order':
        was = next(r[0] for r in old['cloud'] if r[1] == USER) >= old['ear'][0][2]
        now = next(r[0] for r in new['cloud'] if r[1] == USER) >= new['ear'][0][2]
        return 'arrival order flipped', was != now
    verdict = meaning_guard(changed[0], changed[1])
    # a value against a value (number) and an added or dropped «не» (not) are both DIFFERS by the design (§3.10). Today meaning_guard says UNKNOWN to a «не» change: the mutation then
    # reports 'wrong' - that is the finding (the guard does not see a negation), not a rule to relax.
    return DIFFERS, verdict == DIFFERS


def apply(fixture, name, arg):
    """One mutation of a copy of ``fixture``: ``{'fixture', 'expect', 'status'}``."""
    new = copy.deepcopy(fixture)
    for key in ('cloud', 'ear'):
        new[key] = [list(row) for row in new.get(key, ())]
    try:
        changed = MUTATIONS[name](new, arg)
    except (KeyError, IndexError, TypeError, ValueError):
        changed = 'invalid'
    text_rule = name in ('number', 'not', 'language')
    if changed == 'invalid' or (text_rule and changed is None) or (name == 'pauses' and len(fixture.get('ear', ())) < 2) or not new.get('cloud'):
        return {'fixture': new, 'expect': None, 'status': 'invalid'}
    expect, holds = _check(name, arg, fixture, new, changed)
    return {'fixture': new, 'expect': expect, 'status': 'correct' if holds else 'wrong'}
