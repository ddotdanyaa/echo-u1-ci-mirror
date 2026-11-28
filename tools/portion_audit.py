"""g27-portions: what each meaning portion of the bank answers and of 200 model-style texts gets wrong. ``python -m tools.portion_audit [-v]``.

A portion that is not the last one of its text must not end on a dash, a function word (preposition, conjunction, particle), a word that needs
its head («это», «является»), a comma with no predicate before it; it must not tear «X — это Y» or a number from its unit; it holds 4-9 words
(a whole short sentence may be shorter); an item of a list («1) …; 2) …») is not torn when it fits a portion.
"""
from __future__ import annotations

import collections
import glob
import json
import os
import random
import re
import sys

from echo_sync import portioner as P
from echo_sync.portioner import stable_prefix
from echo_sync.settings import CALL_SETTINGS, resolve

SETTINGS = dict(CALL_SETTINGS)      # the sense rules are always on (no key)
from echo_sync.textutil import COPULAS, FUNCTION_WORDS, NEEDS_HEAD, WORDS, normalize, is_unit

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'cloud_context', 'bank')
DASH_END = re.compile(r'(?:[—–]|\s-)\W*$')
_PREDICATE = frozenset({'VERB', 'INFN', 'PRTS', 'ADJS', 'PRED', 'GRND'})
_CORRELATIVES = frozenset('то того тому тем том та той ту те тех теми такой такая такое такие таким так столько'.split())
_BOUNDS = frozenset('менее более позднее ранее позже раньше около примерно приблизительно свыше'.split())
_ITEM = re.compile(r'(?:^|\s)(?:\d{1,2}[).]|[а-е]\))\s')


def bank_answers():
    seen = {}
    for path in sorted(glob.glob(os.path.join(ROOT, 'merged', '*.json'))) + [os.path.join(ROOT, 'instant_bank_2.json')]:
        try:
            rows = json.load(open(path, encoding='utf-8'))
        except OSError:
            continue
        for row in rows:
            a = str(row.get('answer') or '').strip()
            if a:
                seen.setdefault(a, row.get('q', ''))
    return list(seen.items())


_DEF_Q = re.compile(r'^(?:что такое|что значит|что означает|кто такой|кто такая)\s+(.+?)\??$', re.I)
_LEADS = ('Коротко: ', 'Если по сути, ', 'Смотри, ', '', 'Значит так. ', 'По определению, ')
_ENUMS = ('Основные моменты: 1) {}; 2) {}; 3) {}.', 'Тут три пункта. Первое — {}. Второе — {}. Третье — {}.', 'Во-первых, {}; во-вторых, {}; в-третьих, {}.')


def model_texts(n=200, seed=27):
    """``n`` texts the way the text model answers (deterministic): «X — это …» definitions from the bank's «Что такое X?», a lead-in before an
    answer, lists by items built from the clauses of an answer, an answer with its article and number. Built from the bank: no text is invented."""
    rng, rows, out = random.Random(seed), bank_answers(), []
    defs = [(m.group(1), a) for a, q in rows for m in [_DEF_Q.match(str(q).strip())] if m]
    lists = [a for a, _ in rows if len([c for c in re.split(r'[,;.]\s+', a) if len(c.split()) >= 2]) >= 3]
    numbers = [a for a, _ in rows if re.search(r'\d', a)]
    rng.shuffle(defs), rng.shuffle(lists), rng.shuffle(numbers)
    for term, a in defs[:70]:
        out.append(f'{term[:1].upper() + term[1:]} — это {a[:1].lower() + a[1:]}')
    for a in lists[:60]:
        parts = [c.strip(' .;') for c in re.split(r'[,;.]\s+', a) if len(c.split()) >= 2][:3]
        out.append(rng.choice(_ENUMS).format(*(p[:1].lower() + p[1:] for p in parts)))
    for a in numbers[:70]:
        out.append(rng.choice(_LEADS) + (a if not out or rng.random() < 0.5 else a[:1].lower() + a[1:]))
    return out[:n]


def _pos(word):
    return P._tag(normalize(word))[0]


def problems(text, cfg=None):
    """``[(kind, portion index, portion)]`` of ``text`` planned with the call profile."""
    cfg = cfg or resolve(SETTINGS)
    parts = P.portions(text, cfg)
    out = []
    sentence_ends = set()
    for i, p in enumerate(parts):
        words = WORDS.findall(p)
        last = i == len(parts) - 1
        ends_sentence = bool(re.search(r'[.!?…]["»)]*$|["»)][.!?…]$', p)) and not re.search(r'\b(?:ст|п|т\.\s?е|т\.\s?д|тыс|руб|г)\.$', p)
        if ends_sentence:
            sentence_ends.add(i)
        if not words:
            continue
        if len(words) > cfg['max_words']:
            out.append(('long', i, p))
        whole = ends_sentence and (i == 0 or i - 1 in sentence_ends)
        said = any(_pos(w) in _PREDICATE or normalize(w) in COPULAS for w in words) or re.search(r'\w\s+[—–]\s+\w', p)
        if not re.search(r'\d{6}', p) and (len(words) < 3 or (len(words) < 4 and not said)) and not whole and not last:
            out.append(('short', i, p))
        if last or ends_sentence:
            continue
        tail = normalize(words[-1])
        if DASH_END.search(p):
            out.append(('dash', i, p))
        if tail in FUNCTION_WORDS and not P._title(tail):
            out.append(('function', i, p))
        elif tail in NEEDS_HEAD and not re.search(r'[,;:.!?…)»]\W*$', p):
            out.append(('head', i, p))
        if re.search(r'(?:^|\s)(?:\d{1,2}|[а-е])\)$|(?:^|\s)(?:во-первых|во-вторых|в-третьих|в-четв[её]ртых|в-пятых|первое|второе|третье)\W*$', p, re.I):
            out.append(('item', i, p))                  # «1) | первичные», «во-вторых, | это …»: the mark goes with its item
        if p.rstrip().endswith(',') and tail in _CORRELATIVES:
            out.append(('comma', i, p))                 # «и те, | кто …»: the thought is the clause after the comma
        nxt = parts[i + 1]
        first = normalize(WORDS.findall(nxt)[0]) if WORDS.findall(nxt) else ''
        if ((re.search(r'\d\W*$', p) and (is_unit(first) or first in ('процентов', 'процента', 'процент')))
                or (tail in _BOUNDS and re.match(r'\W*\d', nxt)) or (re.search(r'\bрубл\w*$', p) and re.match(r'\d+\s+копе', nxt))):
            out.append(('unit', i, p))
        before = re.search(r'^[\s—–-]*(?:это|является|являются)\b', nxt, re.I) and not re.search(r'[,;:.!?…)]\s*$', p)
        fits = (i == 0 or i - 1 in sentence_ends) and re.search(r'[.!?…]["»)]*$', nxt) and len(words) + len(WORDS.findall(nxt)) <= cfg['max_words']
        if (before and fits) or tail in COPULAS:
            out.append(('definition', i, p))
    return out


def audit(texts, verbose=False):
    cfg = resolve(SETTINGS)
    counts, examples = collections.Counter(), collections.defaultdict(list)
    bad = 0
    for t in texts:
        found = problems(t, cfg)
        bad += bool(found)
        for kind, i, p in found:
            counts[kind] += 1
            if len(examples[kind]) < 6:
                examples[kind].append(' | '.join(P.portions(t, cfg)))
    return bad, counts, examples


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    verbose = '-v' in argv
    for name, texts in (('bank', [a for a, _ in bank_answers()]), ('model', model_texts())):
        bad, counts, examples = audit(texts, verbose)
        print(f'{name}: {len(texts)} texts, {bad} with a defect; ' + ', '.join(f'{k} {v}' for k, v in sorted(counts.items())))
        if verbose:
            for k, ex in examples.items():
                print(' ', k)
                for e in ex:
                    print('    ', e)


if __name__ == '__main__':
    main()


# --- the stream: what the first cue and stable_prefix let go while the text arrives -------------------------------------------------

def _chunks(text, rng):
    i = 0
    while i < len(text):
        j = min(len(text), i + rng.randint(2, 14))
        yield text[:j]
        i = j


def _end_defect(piece):
    """The defect of a piece of text that a stream lets go before the rest: a dash, a function word, a copula, a bound, a list mark."""
    words = WORDS.findall(piece)
    if not words or re.search(r'[.!?…]["»)]*$', piece.rstrip()):
        return None
    tail = normalize(words[-1])
    if DASH_END.search(piece):
        return 'dash'
    if tail in FUNCTION_WORDS:
        return 'function'
    if tail in COPULAS:
        return 'definition'
    if re.search(r'(?:^|\s)(?:\d{1,2}|[а-е])\)$', piece.rstrip()):
        return 'item'
    return None


def stream_problems(text, question, seed=0, cfg=None):
    """``[(kind, where, piece)]``: the first cue (first_useful.first_cue) and every stable_prefix step (eager and not) of ``text`` streamed in
    random 2-14 character chunks."""
    from echo_sync.first_useful import first_cue
    cfg = cfg or resolve(SETTINGS)
    rng, out = random.Random(seed), []
    for prefix in _chunks(text, rng):
        cue = first_cue(prefix, question, cfg, final=prefix == text, last=prefix == text)
        if cue:
            kind = _end_defect(cue) if len(cue) < len(text.rstrip()) else None
            if kind:
                out.append((kind, 'first_cue', cue))
            break
    for eager in (False, True):
        committed = ''
        for prefix in _chunks(text, random.Random(seed + 1)):
            got = stable_prefix(prefix, cfg, committed=committed, eager=eager)
            if got and len(got) > len(committed):
                kind = _end_defect(got) if len(got.rstrip()) < len(text.rstrip()) else None
                if kind:
                    out.append((kind, 'eager' if eager else 'stable', got[len(committed):]))
                committed = got
    return out


def stream_audit(rows, seeds=3, cfg=None):
    counts, examples = collections.Counter(), collections.defaultdict(list)
    for text, question in rows:
        for seed in range(seeds):
            for kind, where, piece in stream_problems(text, question, seed, cfg):
                counts[(kind, where)] += 1
                if len(examples[(kind, where)]) < 5:
                    examples[(kind, where)].append(piece)
    return counts, examples
