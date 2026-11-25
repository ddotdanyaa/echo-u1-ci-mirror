"""S6 / axis "seg": adversarial tests of the segmentation of answers into spoken portions.

These tests encode what the owner REQUIRES (OWNER_DIRECTIVES_2026-11-01 §1, §3), not what the code does today:

* portions reproduce the answer in order, without loss or duplication, and only ever cut between words;
* numbers (decimal, grouped, time, range, ratio, fraction), a number with its unit (%, °C, ₽, км/с, «век»,
  spelled-out numbers), «не»/«ни» with the next word, abbreviations, initials and names are never torn apart;
* no empty or punctuation-only portion; word counts stay inside the configured bounds;
* the first portion is not an echo of the question; abbreviation expansion is consistent.

Oracles are independent of the code under test: the corpus (tests/helpers_s6_seg.py) DECLARES the pieces that
must stay whole, a boundary falling into one of them is a violation. The streaming checks run the real
``ControlledMedia`` built exactly like ``controlled_host.serve`` builds it; only the provider events are fed.

A test marked ``xfail(strict=True, reason="DEF-SEG-NN ...")`` is a REPORTED DEFECT: it fails today for the stated
reason and turns into XPASS (= error) the day the defect is fixed, so the mark must then be removed. Every other
test passes today and guards against regressions. Production code is not touched.

Defects:  DEF-SEG-01 range with a dash          02 time / ratio with a colon     03 fraction / «км/с» with a slash
          04 «100 °C»                            05 currency symbol after a number 06 century numeral + «век»
          07 «н. э.» / «тыс. человек»            08 full personal names           09 spelled-out numbers + unit
          10 units missing from the lexicon      11 initial = function word       12 stable_prefix + odd whitespace
          13 answer without terminal punctuation 14 abbreviation expansion, streaming
          15 first cue cut at an abbreviation period  16 first cue is an echo of the question
          17 streamed continuation breaks min_words   18 surname-first initials in a list
          19 first cue is a lone word of a phrase     20 first cue is a phrase the phone handles itself
          21 arithmetic expression / spaced ratio cut at the operator
"""
from __future__ import annotations

import ast
import collections
import copy
import functools
import json
import os
import random
import re
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

import echo_sync
import helpers_s6_seg as H
from echo_sync.engine import EchoEngine, SILENT
from echo_sync.abbrev_state import expand_abbreviations
from echo_sync.portioner import portions, stable_prefix, syllables
from echo_sync.portioner import MEANING_FIRST_MAX_WORDS, MEANING_NUMBER_FIRST_MAX_WORDS
from echo_sync.first_useful import asks_for_number
from echo_sync.settings import CALL_SETTINGS, PRESETS, resolve
from echo_sync.textutil import CONDUIT_LOCAL_PHRASES, normalize
from engine_say import engine_reply

COUNTS = collections.Counter()


pytestmark = pytest.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)


@pytest.fixture(scope='module', autouse=True)
def _case_counts():
    """With S6_SEG_COUNTS=<file> the number of generated cases of this run is written there (for the report)."""
    yield
    target = os.environ.get('S6_SEG_COUNTS')
    if target:
        Path(target).write_text(json.dumps(dict(COUNTS), indent=1, sort_keys=True), encoding='utf-8')


def P(text, config):
    COUNTS['portions_calls'] += 1
    return portions(text, config)


@functools.lru_cache(maxsize=None)
def _planned(text, profile):
    COUNTS['portions_calls'] += 1
    return tuple(portions(text, H.PROFILES[profile]))


def Pc(text, profile):
    """The plan of ``text`` in a named profile, computed once (callers never modify it)."""
    return list(_planned(text, profile))


FUZZ = dict(deadline=None, derandomize=True, database=None, suppress_health_check=list(HealthCheck))
PROFILES = list(H.PROFILES)
SYLLABLE = list(H.SYLLABLE_PROFILES)
CONTROLLED = H.CONTROLLED_SETTINGS

# Independent of echo_sync.textutil on purpose: words that must stay with the word that follows them.
DANGLING = frozenset('в во на с со к ко по о об от из за для до при у или и а но не ни что как бы ли же чтобы если '
                     'над под перед между через без около после кроме вместо против среди вокруг ради'.split())
# Broader, used only to decide that a cut INSIDE a long portion would have been acceptable (a smaller list would
# invent "free cuts" the engine rightly refuses): half-conjunctions, determiners and the tails of «в течение», «по сравнению с».
DETERMINERS = frozenset('все весь вся всех всем каждый каждая каждое любой любая любое всякий'.split())
HALF_CONJUNCTIONS = frozenset('потому поскольку хотя пока когда где куда откуда зачем почему отчего ибо пусть пускай чем '
                              'нежели едва будто словно также так зато однако причём притом даже лишь только именно уж '
                              'хоть разве неужели мол вот вон то давай давайте ведь'.split())
LOCUTION_TAILS = frozenset('течение связи целях качестве случае отношении рамках результате ходе мере счёт счет области '
                           'зрения основании основе помощью сравнению соответствии пределах течении отличие зависимости '
                           'направлении силу пользу причине'.split())
KEEP_WITH_NEXT = DANGLING | DETERMINERS | HALF_CONJUNCTIONS
SENTENCE_FINAL = '.!?…'


def show(rows, limit=4):
    return '\n  '.join(str(row) for row in rows[:limit]) + (f'\n  … and {len(rows) - limit} more' if len(rows) > limit else '')


# =====================================================================================================
# A. the corpus, the harness and the oracles guard themselves
# =====================================================================================================

REQUIRED_CATEGORIES = {'definition': 10, 'number_unit': 10, 'date_year': 8, 'percent': 8, 'negation': 8,
                       'abbreviation': 8, 'enumeration': 8, 'compound_term': 8, 'name': 8, 'two_sentences': 8,
                       'no_final_punct': 8, 'spelled_numbers': 6, 'numeric_forms': 8, 'long_sentence': 4,
                       'quotes_parens': 4, 'short': 4, 'alignment_sweep': 100}


def test_the_corpus_is_large_varied_and_deterministic():
    assert len(H.CORPUS) >= 150 and len(H.HAND_CORPUS) >= 150
    counts = collections.Counter(item.category for item in H.CORPUS)
    for category, minimum in REQUIRED_CATEGORIES.items():
        assert counts[category] >= minimum, (category, counts[category])
    assert len({item.id for item in H.CORPUS}) == len(H.CORPUS)
    assert len({item.answer for item in H.CORPUS}) >= 0.95 * len(H.CORPUS)
    rebuilt = H._build()
    assert [(i.id, i.question, i.answer, i.atoms, i.elide) for i in rebuilt] == \
           [(i.id, i.question, i.answer, i.atoms, i.elide) for i in H.CORPUS]
    for item in H.CORPUS:
        assert item.answer == H.squeeze(item.answer) and item.question.endswith('?'), item
        for kind, atom in item.atoms:
            assert H.atom_spans(item.answer, atom), (item.id, kind, atom)   # a declared piece really is in the answer
    assert sum(not item.punctuated for item in H.CORPUS) >= 10          # answers without terminal punctuation
    assert {k for item in H.CORPUS for k, _ in item.atoms} >= {'unit', 'neg', 'decimal', 'grouped', 'abbr', 'initials',
                                                              'name2', 'name3', 'spelled', 'time', 'range', 'degree'}


def test_the_streaming_harness_is_built_exactly_like_the_host(tmp_path):
    source = (Path(echo_sync.__file__).parent / 'controlled_host.py').read_text(encoding='utf-8')
    calls = [n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Call)
             and getattr(n.func, 'id', None) == 'ControlledMedia']
    assert len(calls) == 1
    host = {k.arg: ast.literal_eval(k.value) for k in calls[0].keywords if isinstance(k.value, ast.Constant)}
    assert {k: v for k, v in host.items() if k != 'session_id'} == H.HOST_KWARGS
    assert [ast.unparse(k.value) for k in calls[0].keywords if k.arg == 'settings'] == ['controller_settings(profile_settings)']      # ROOT-1: the host builds the controller's settings once, at construction
    assert H.host_controller(tmp_path).settings == CALL_SETTINGS           # F1 (wave F): the meaning profile (was the short-cue dict)


def test_the_oracles_can_fail():
    """Each oracle must be able to see the thing it is named after (otherwise a green run proves nothing)."""
    answer = 'Война шла с 1941–1945 годов.'
    assert H.cut_atoms(answer, ['1941–1945'], ['Война шла', 'с 1941–', '1945 годов.']) == ['1941–1945']
    assert H.cut_atoms(answer, ['1941–1945'], ['Война шла', 'с 1941–1945', 'годов.']) == []
    assert H.cut_atoms('Нет, кит не рыба.', ['не рыба'], ['Нет, кит не', 'рыба.']) == ['не рыба']
    assert H.cut_atoms('Нет, кит не рыба.', ['не рыба'], ['Нет,', 'кит не рыба.']) == []
    assert H.cut_atoms('а не рыба. не рыба', ['не рыба'], ['а не', 'рыба. не рыба']) == ['не рыба']   # every occurrence
    assert H.cut_atoms('Вторая: 100 °C', ['100 °C'], ['Вторая: 100', '°C'], shift=0) == ['100 °C']
    assert H.cut_atoms('Это 100 °C', ['100 °C'], ['100', '°C'], shift=len('Это')) == ['100 °C']
    assert H.lossless_problem('а б в', ['а б', 'в']) is None
    assert H.lossless_problem('а б в', ['а', 'в']) and H.lossless_problem('а б', ['а б', 'а б']) \
           and H.lossless_problem('а б', ['а б б'])
    assert H.cut_words('рассеивает синий свет', ['рассеивает си', 'ний свет']) == ['синий']
    assert H.cut_words('рассеивает синий свет', ['рассеивает', 'синий свет']) == []
    assert H.echoes_question('Третий закон', 'Что гласит третий закон Ньютона?')
    assert H.echoes_question('К планетам земной группы', 'Перечисли планеты земной группы?')
    assert not H.echoes_question('В Солнечной системе восемь планет.', 'Сколько планет в Солнечной системе?')
    assert not H.echoes_question('Нет.', 'Правда ли что кит рыба?')
    assert not H.echoes_question('За кражу судят по УК РФ,', 'По какому кодексу судят за кражу?')
    item = H.Item('t', 't', 'q?', 'Мама мыла раму папа пилил дрова', [], '')
    cfg = resolve({'portion_mode': 'syllables', 'min_words': 2, 'max_words': 3})
    assert bound_problems(item, ['Мама', 'мыла раму', 'папа пилил дрова'], cfg)            # avoidable one-word portion
    assert bound_problems(item, ['Мама мыла раму папа', 'пилил дрова'], cfg)               # a free cut inside, 4 > 3 words
    assert not bound_problems(item, ['Мама мыла раму', 'папа пилил дрова'], cfg)


# =====================================================================================================
# B. universal invariants of the portioner, every profile, the whole corpus
# =====================================================================================================

@pytest.mark.parametrize('profile', PROFILES)
def test_portions_are_the_answer_in_order_without_loss_or_duplication(profile):
    bad = []
    for item in H.CORPUS:
        parts = Pc(item.answer, profile)
        problem = H.lossless_problem(item.answer, parts)
        if problem or not parts or ' '.join(normalize(p) for p in parts) != normalize(item.answer):
            bad.append((item.id, problem or 'normalised text differs', parts))
    assert not bad, show(bad)


@pytest.mark.parametrize('profile', PROFILES)
def test_no_portion_is_empty_punctuation_only_unclean_or_a_phone_command(profile):
    bad = []
    for item in H.CORPUS:
        for portion in Pc(item.answer, profile):
            if (not any(c.isalnum() for c in portion) or portion != ' '.join(portion.split()) or not normalize(portion)
                    or normalize(portion) in CONDUIT_LOCAL_PHRASES):
                bad.append((item.id, portion))
    assert not bad, show(bad)


@pytest.mark.parametrize('profile', PROFILES)
def test_portions_only_cut_between_words(profile):
    bad = []
    for item in H.CORPUS:
        cut = H.cut_words(item.answer, Pc(item.answer, profile))
        if cut:
            bad.append((item.id, cut))
    assert not bad, show(bad)


@pytest.mark.parametrize('profile', PROFILES)
def test_portions_are_deterministic_and_leave_the_settings_alone(profile):
    config = copy.deepcopy(H.PROFILES[profile])
    before = copy.deepcopy(config)
    resolved = resolve(config)
    for item in H.HAND_CORPUS:
        first = P(item.answer, config)
        assert first == P(item.answer, config) == P(item.answer, resolved), item.id
    assert config == before


@pytest.mark.parametrize('profile', PROFILES)
def test_a_portion_never_ends_on_a_word_that_needs_the_next_one(profile):
    bad = []
    for item in H.CORPUS:
        parts = Pc(item.answer, profile)
        for i, portion in enumerate(parts[:-1]):
            last = (normalize(portion).split() or [''])[-1]
            ends_on_an_initial = re.search(r'(?:^|\s)[А-ЯЁA-Z]\.[,;:)»]*$', portion.rstrip()) is not None   # «Иванов И. И.,»
            if last in DANGLING and portion.rstrip()[-1:] not in SENTENCE_FINAL and not ends_on_an_initial:
                bad.append((item.id, portion))
    assert not bad, show(bad)


@pytest.mark.parametrize('profile', PROFILES)
def test_negation_stays_with_the_word_it_negates(profile):
    bad, checked = [], 0
    for item in H.CORPUS:
        atoms = item.atoms_of('neg')
        if atoms:
            checked += 1
            hit = H.cut_atoms(item.answer, atoms, Pc(item.answer, profile))
            if hit:
                bad.append((item.id, hit))
    assert checked >= 25 and not bad, show(bad)


@pytest.mark.parametrize('profile', PROFILES)
def test_decimal_grouped_and_numeric_date_numbers_are_never_split(profile):
    bad, checked = [], 0
    for item in H.CORPUS:
        atoms = item.atoms_of('decimal', 'grouped', 'numdate')
        if atoms:
            checked += 1
            hit = H.cut_atoms(item.answer, atoms, Pc(item.answer, profile))
            if hit:
                bad.append((item.id, hit, Pc(item.answer, profile)))
    assert checked >= 40 and not bad, show(bad)


@pytest.mark.parametrize('profile', SYLLABLE)
def test_number_with_a_documented_unit_abbreviation_and_initials_are_never_split(profile):
    bad, checked = [], 0
    for item in H.CORPUS:
        atoms = item.atoms_of('unit', 'abbr', 'initials')
        if atoms:
            checked += 1
            hit = H.cut_atoms(item.answer, atoms, Pc(item.answer, profile))
            if hit:
                bad.append((item.id, hit, Pc(item.answer, profile)))
    assert checked >= 80 and not bad, show(bad)


# --- bounds -----------------------------------------------------------------------------------------

def inner_cuts(item, parts, index, shift=0):
    """Positions inside portion ``index`` where a listener would accept a cut: not after a word that needs the next
    one, not next to a digit, not inside a declared piece. A portion with such a cut is NOT one indivisible unit."""
    words = parts[index].split()
    offset = shift + len(H.nospace(''.join(parts[:index])))
    flat = H.nospace(item.answer)
    spans = [span for _, atom in item.atoms for span in H.atom_spans(item.answer, atom)]
    free = []
    for t in range(len(words) - 1):
        left, right = words[t], words[t + 1]
        if not (any(c.isalnum() for c in left) and any(c.isalnum() for c in right)):
            continue    # a dash or a bracket on its own is not a word to cut around
        position = offset + len(H.nospace(' '.join(words[:t + 1])))
        if any(a < position < b for a, b in spans):
            continue
        # The end of a declared piece (an initial «И.» looks like the conjunction «и») is always a place to cut.
        ends_a_piece = any(position >= b and not any(c.isalnum() for c in flat[b:position]) for _, b in spans)
        last = (normalize(left).split() or [''])[-1]
        before = (normalize(words[t - 1]).split() or [''])[-1] if t else ''
        needs_next = last in KEEP_WITH_NEXT or (last in LOCUTION_TAILS and before in KEEP_WITH_NEXT)
        if not ends_a_piece and needs_next and left[-1:] not in SENTENCE_FINAL:
            continue
        if any(c.isdigit() for c in left + right):
            continue
        free.append(t)
    return free


def bound_problems(item, parts, cfg, *, shift=0, skip_first=False):
    """Breaches of the configured bounds that were AVOIDABLE: the engine's own contract is that only one
    indivisible unit may overrun max_words/max_syllables, and that a portion below min_words exists only when no
    neighbour could take it. ``skip_first``: the streamed first cue follows the first-cue gate's own rules."""
    problems = []
    if cfg['portion_mode'] not in ('syllables', 'meaning'):
        return problems
    for i, portion in enumerate(parts):
        if skip_first and i == 0:
            continue
        words, syl = H.product_words(portion), syllables(portion)
        if (words > cfg['max_words'] or syl > cfg['max_syllables']) and inner_cuts(item, parts, i, shift):
            problems.append((i, portion, f'{words} words / {syl} syllables, yet it can be cut'))
        # a meaning plan never joins across a sentence end: a short whole sentence is no breach of min_words there
        if (cfg['portion_mode'] == 'syllables' and words < cfg['min_words'] and len(parts) > 1
                and not (words == 1 and syl >= cfg['long_word_syllables'])):
            for j in (i - 1, i + 1):
                if 0 <= j < len(parts) and not (skip_first and j == 0):
                    merged = ' '.join((parts[j], portion) if j < i else (portion, parts[j]))
                    if H.product_words(merged) <= cfg['max_words'] and syllables(merged) <= cfg['max_syllables']:
                        problems.append((i, portion, f'{words} word(s) < min_words {cfg["min_words"]}; '
                                                     f'{parts[j]!r} could take it'))
                        break
    return problems


PROTECTED_KINDS = frozenset({'neg', 'decimal', 'grouped', 'numdate', 'unit', 'abbr'})


@pytest.mark.parametrize('profile', SYLLABLE)
def test_word_and_syllable_bounds_hold_unless_one_indivisible_unit_overruns(profile):
    """Items that contain a piece of a kind with its own DEFECT (SEG-01..11) are left out here: the stray fragments
    ('с.' after 'км/', 'C.' after '100 °') are consequences of those defects, reported there."""
    cfg = resolve(H.PROFILES[profile])
    bad, checked = [], 0
    for item in H.CORPUS:
        if {kind for kind, _ in item.atoms} <= PROTECTED_KINDS:
            checked += 1
            for problem in bound_problems(item, Pc(item.answer, profile), cfg):
                bad.append((item.id,) + problem)
    assert checked >= 150 and not bad, show(bad)


@pytest.mark.parametrize('profile', ['words2', 'words3', 'words4'])
def test_fixed_size_mode_keeps_its_size_apart_from_moving_a_dangling_word(profile):
    size = resolve(H.PROFILES[profile])['words_per_portion']
    bad = []
    for item in H.CORPUS:
        parts = Pc(item.answer, profile)
        for i, portion in enumerate(parts[:-1]):
            if H.product_words(portion) > size + 3 or H.product_words(portion) < 1:
                bad.append((item.id, portion))
    assert not bad, show(bad)


# =====================================================================================================
# C. DEFECTS of the portioner: pieces that are torn apart
# =====================================================================================================

GRID_PREFIX = ('Это', 'было', 'давно', 'когда', 'мы', 'жили', 'тихо', 'вместе')
GRID_SUFFIX = ('и', 'потом', 'всё', 'стало', 'иначе')
GRID_ATOMS = {
    'range': ['1941–1945', '5–10', '2010–2020', '3–4'],
    'time': ['12:30', '9:45', '18:00', '10:15'],
    'ratio': ['3:1', '1:100 000', '16:9'],
    'fraction': ['3/4', '1/2', '2/3'],
    'slashunit': ['300 000 км/с', '60 км/ч', '5 м/с'],
    'degree': ['100 °C', '36,6 °C', '0 °C'],
    'currency': ['100 ₽', '1 500 ₽', '2,3 млн ₽', '500 ₽', '100 $'],
    'century': ['в XIX веке', 'XX век', 'в 18 веке', 'в XXI веке'],
    'abbr_era': ['до н. э.', 'н. э.'],
    'unit_abbr': ['70 тыс. человек', '5 тыс. рублей'],
    'name2': ['Исаак Ньютон', 'Нил Армстронг', 'Альберт Эйнштейн'],
    'name3': ['Александр Сергеевич Пушкин', 'Лев Николаевич Толстой', 'Юрий Алексеевич Гагарин'],
    'spelled': ['двадцать пять процентов', 'сто восемьдесят градусов', 'пятнадцать минут', 'три тысячи километров'],
    'unit_ext': ['250 миллилитров', '220 В', '2,5 гигабайта', '10 ватт', '3 суток', '20 вольт'],
    'expression': ['2 + 2 = 4', '3 : 1', '5 × 6 = 30', '10 − 4 = 6'],
}


def grid_texts(atom):
    for k in range(len(GRID_PREFIX)):
        for m in range(4):
            yield ' '.join(list(GRID_PREFIX[:k]) + [atom] + list(GRID_SUFFIX[:m])) + '.'


def cutting_cases(kinds, minimal, profiles=SYLLABLE):
    """``(cases, checked)``: every answer in which a boundary falls inside a declared piece of one of ``kinds``,
    shortest first. Looked at: the natural ``minimal`` sentences, the corpus, and a grid of contexts (0-7 words
    before the piece, 0-3 after) so that every cut position of every planner meets the piece."""
    cases, checked = [], 0
    jobs = [(text, [atom]) for text, atom in minimal]
    jobs += [(item.answer, item.atoms_of(*kinds)) for item in H.CORPUS if item.atoms_of(*kinds)]
    for kind in kinds:
        for atom in GRID_ATOMS.get(kind, ()):
            jobs += [(text, [atom]) for text in grid_texts(atom)]
    for text, atoms in jobs:
        for profile in profiles:
            checked += 1
            parts = P(text, H.PROFILES[profile])
            hit = H.cut_atoms(text, atoms, parts)
            if hit:
                cases.append((len(text.split()), profile != 'controlled', profile, text, hit, parts))
    cases.sort(key=lambda case: case[:4])
    return cases, checked


def assert_whole(kinds, minimal):
    cases, checked = cutting_cases(kinds, minimal)
    COUNTS['defect_cases_checked'] += checked
    seen, shortest = set(), []
    for case in cases:
        if (case[2], case[3]) not in seen:
            seen.add((case[2], case[3]))
            shortest.append(case)
    assert not cases, (f'{len(cases)} of {checked} answer/profile cases cut a piece. Shortest:\n  '
                       + '\n  '.join(f'[{c[2]}] {c[3]!r} -> {c[5]}' for c in shortest[:3]))


def test_a_numeric_range_with_a_dash_is_not_cut():
    assert_whole(['range'], [('Война шла с 1941–1945 годов.', '1941–1945'), ('1941–1945.', '1941–1945'),
                             ('Взрослому нужно спать 7–9 часов в сутки.', '7–9')])


def test_a_time_of_day_or_a_ratio_is_not_cut():
    assert_whole(['time', 'ratio'], [('Встреча назначена на 10:15.', '10:15'), ('Урок начинается в 9:45 утра.', '9:45'),
                                     ('Занятие начнётся сегодня в 12:30.', '12:30'), ('1:100 000.', '1:100 000')])


def test_a_fraction_or_a_compound_unit_with_a_slash_is_not_cut():
    assert_whole(['fraction', 'slashunit'], [('Добавьте 1/2 стакана воды.', '1/2'),
                                             ('Скорость света около 300 000 км/с в вакууме.', '300 000 км/с'),
                                             ('Самолёт летит со скоростью 900 км/ч.', '900 км/ч')])


def test_a_temperature_in_degrees_is_not_cut():
    assert_whole(['degree'], [('Вода кипит при температуре 100 °C на уровне моря.', '100 °C'),
                              ('Нормальная температура тела — около 36,6 °C.', '36,6 °C'), ('100 °C.', '100 °C')])


def test_a_currency_sign_after_the_number_stays_with_the_number():
    assert_whole(['currency'], [('Штраф составляет 500 ₽ за нарушение.', '500 ₽'),
                                ('Проезд обойдётся в 1 500 ₽ за месяц.', '1 500 ₽'),
                                ('Прибыль составила 2,3 млн ₽ за год.', '2,3 млн ₽'),
                                ('Услуга стоит 100 $ в месяц.', '100 $')])


def test_a_century_is_not_cut_between_the_numeral_and_the_word_century():
    assert_whole(['century'], [('Это произошло в XIX веке в России.', 'в XIX веке'),
                               ('Город основали в 18 веке на Неве.', 'в 18 веке')])


def test_era_and_thousand_abbreviations_are_not_cut_at_their_period():
    assert_whole(['abbr_era', 'unit_abbr'], [
        ('Аристотель жил в IV веке до н. э. и был учителем Александра Македонского.', 'н. э.'),
        ('Население города — около 70 тыс. человек, и оно медленно растёт.', '70 тыс. человек')])


def test_a_personal_name_that_fits_is_not_cut():
    # Only names that fit the profile's hard limits are demanded: a name longer than max_syllables/max_words cannot stay
    # whole without overrunning them (see QUESTION-SEG-06 in the report).
    cases, checked = [], 0
    jobs = [(item.answer, atom) for item in H.CORPUS for kind, atom in item.atoms if kind in ('name2', 'name3')]
    jobs += [(text, atom) for kind in ('name2', 'name3') for atom in GRID_ATOMS[kind] for text in grid_texts(atom)]
    jobs += [('Это написал Александр Сергеевич Пушкин.', 'Александр Сергеевич Пушкин')]
    for text, atom in jobs:
        for profile in SYLLABLE:
            cfg = resolve(H.PROFILES[profile])
            fits = H.product_words(atom) <= cfg['max_words'] and syllables(atom) <= cfg['max_syllables']
            if not fits:
                continue
            checked += 1
            parts = P(text, H.PROFILES[profile])
            if H.cut_atoms(text, [atom], parts):
                cases.append((len(text.split()), profile != 'controlled', profile, text, parts))
    cases.sort(key=lambda case: case[:4])
    COUNTS['defect_cases_checked'] += checked
    assert checked > 100 and not cases, (f'{len(cases)} of {checked} cases cut a name that fits. Shortest:\n  '
                                         + '\n  '.join(f'[{c[2]}] {c[3]!r} -> {c[4]}' for c in cases[:3]))


def test_a_spelled_out_number_stays_with_its_unit():
    # A voice transcript writes numbers in words as often as in digits.
    assert_whole(['spelled'], [('В развёрнутом угле сто восемьдесят градусов.', 'сто восемьдесят градусов'),
                               ('Это двадцать пять процентов.', 'двадцать пять процентов'),
                               ('Между городами три тысячи километров.', 'три тысячи километров')])


def test_units_missing_from_the_lexicon_stay_with_their_number():
    assert_whole(['unit_ext'], [('Стакан вмещает 250 миллилитров.', '250 миллилитров'),
                                ('Это 250 миллилитров.', '250 миллилитров'), ('Это длится 10 суток.', '10 суток')])


def test_an_initial_that_looks_like_a_function_word_does_not_glue_what_follows():
    bad = []
    texts = ['Приказ подписал Иванов И. И., а утвердил директор.', 'Письмо отправил Петров В. В., потом позвонил.',
             'Акт составил Сидоров К. К., и мы его подписали.']
    for text in texts:
        item = H.Item('t', 't', 'q?', text, [('initials', text.split(' ', 2)[2].split(',')[0])], '')
        for profile in SYLLABLE:
            cfg = resolve(H.PROFILES[profile])
            parts = P(text, H.PROFILES[profile])
            bad += [(profile, text, parts, p) for p in bound_problems(item, parts, cfg)]
    assert not bad, show(bad)


def test_an_arithmetic_expression_is_not_cut_at_its_operator():
    assert_whole(['expression'], [('Два плюс два равно 4, то есть 2 + 2 = 4.', '2 + 2 = 4'),
                                  ('Счёт был 3 : 1 в пользу гостей.', '3 : 1')])


def test_surname_first_initials_in_a_list_stay_with_their_surname():
    cases = [('Доклад сделал Иванов И. И., Петров П. П. его дополнил.', ['Иванов И. И.', 'Петров П. П.']),
             ('Авторы: Иванов И. И., Петров П. П. и Сидоров С. С.', ['Иванов И. И.', 'Петров П. П.', 'Сидоров С. С.']),
             ]   # «Пушкин А. С. Москва» is ambiguous (the surname first, or the initials of «А. С. Москва»): not demanded
    bad = []
    for text, atoms in cases:
        for profile in SYLLABLE:
            parts = P(text, H.PROFILES[profile])
            hit = H.cut_atoms(text, atoms, parts)
            if hit:
                bad.append((profile, text, hit, parts))
    assert not bad, show(bad)


# =====================================================================================================
# D. property-based: pieces the portioner DOES protect stay whole in any context
# =====================================================================================================

CONTENT = ('система', 'работает', 'стабильно', 'проверили', 'результат', 'записали', 'показатель', 'изменился',
           'заметно', 'утром', 'вчера', 'коллеги', 'говорят', 'давно', 'жили', 'тихо', 'вместе', 'потом', 'Москва',
           'электроэнцефалография', 'лес', 'река', 'большой', 'новый')
SAFE = {
    'neg': ['не рыба', 'ни один', 'не является', 'не менее', 'ни кислород', 'не может'],
    'decimal': ['6,5', '17,1', '0,5', '36,6'],
    'grouped': ['384 400', '1 500', '10 000', '300 000'],
    'numdate': ['22.06.1941', '01.01.2000'],
    'unit': ['15 %', '5 лет', '90 градусов', '3 кг', '22 июня', '1941 года', '21 %', '11 человек', '45 минут',
             '5 млн долларов', '384 400 километров', '2 литров', '60%'],
    'abbr': ['и т. д.', 'т. е.', 'и т. п.', 'и др.', 'УК РФ', 'ГК РФ'],
    'initials': ['А. С. Пушкин', 'В. В. Путин'],      # initials FIRST; surname-first is DEF-SEG-18
}
ALL_MODE_KINDS = ('neg', 'decimal', 'grouped', 'numdate')
SYLLABLE_KINDS = ALL_MODE_KINDS + ('unit', 'abbr', 'initials')


@st.composite
def contexts(draw):
    before = draw(st.lists(st.tuples(st.sampled_from(CONTENT), st.sampled_from([' ', ' ', ', '])), max_size=8))
    after = draw(st.lists(st.tuples(st.sampled_from(CONTENT), st.sampled_from([' ', ' ', ', '])), max_size=5))
    end = draw(st.sampled_from(['', '.', '!', '?']))
    return before, after, end


def compose(before, atom, after, end):
    text = ''.join(word + sep for word, sep in before) + atom
    if after:
        text += ' ' + ''.join(word + sep for word, sep in after).rstrip(', ')
    return text + end


@given(context=contexts(), kind=st.sampled_from(SYLLABLE_KINDS), pick=st.integers(0, 50))
@settings(max_examples=250, **FUZZ)
def test_property_protected_pieces_are_never_cut_whatever_surrounds_them(context, kind, pick):
    atom = SAFE[kind][pick % len(SAFE[kind])]
    before, after, end = context
    text = compose(before, atom, after, end)
    COUNTS['hypothesis_examples_protected_pieces'] += 1
    for profile in (PROFILES if kind in ALL_MODE_KINDS else SYLLABLE):
        parts = P(text, H.PROFILES[profile])
        assert not H.cut_atoms(text, [atom], parts), (profile, text, parts)


SOUP = (list(CONTENT) + ['в', 'на', 'и', 'не', 'ни', 'что', 'как', 'если', 'но', 'или', 'бы', 'ли', 'же', 'при', 'до', 'у',
                         'для', 'из', 'за', 'по', 'с', 'о'] * 2
        + ['15', '2026', '228', '6,5', '1 500', '12:30', '1941–1945', '3/4', '100 °C', 'км/с', '15 %', '№ 5', '$100',
           'и т. д.', 'н. э.', 'А. С. Пушкин', 'УК РФ', 'ВВП', 'XIX', 'Стоп', 'Пока', 'Тише', 'Хватит', 'ещё раз',
           'Hermes', 'iPhone', '«кавычки»', '(скобки)', 'кто-то', 'по-русски'])
SEPARATORS = [' ', ' ', ' ', ', ', ', ', '. ', '; ', ': ', ' — ', '! ', '? ', '… ', '\n', '  ', '\u00a0', '\u202f', '\t', ' - ']


@st.composite
def soups(draw):
    count = draw(st.integers(1, 40))
    parts = []
    for _ in range(count):
        parts += [draw(st.sampled_from(SOUP)), draw(st.sampled_from(SEPARATORS))]
    return ''.join(parts).strip()


@given(text=soups(), profile=st.sampled_from(PROFILES), table=st.booleans())
@settings(max_examples=300, **FUZZ)
def test_property_any_text_is_reproduced_losslessly_in_clean_portions(text, profile, table):
    config = dict(H.PROFILES[profile])
    abbreviations = {'ВВП': 'валовой внутренний продукт', 'УК РФ': 'Уголовный кодекс Российской Федерации'}
    if table:
        config['abbreviations'] = abbreviations
    COUNTS['hypothesis_examples_soup'] += 1
    expected = expand_abbreviations(text, abbreviations if table else {})
    parts = P(text, config)
    assert parts == P(text, config)
    if not parts:
        # Only an answer that is nothing but a phone command (or has no words at all) may vanish.
        assert normalize(expected) in CONDUIT_LOCAL_PHRASES | {''}, (text, config)
        return
    assert H.lossless_problem(expected, parts) is None, (text, config, parts)
    assert ' '.join(normalize(p) for p in parts) == normalize(expected)
    for i, portion in enumerate(parts):
        assert any(c.isalnum() for c in portion) and portion == ' '.join(portion.split()), (text, portion)
        assert normalize(portion) not in CONDUIT_LOCAL_PHRASES, (text, config, portion)
        last = (normalize(portion).split() or [''])[-1]
        if i < len(parts) - 1 and last in DANGLING and not portion.rstrip().endswith(tuple(SENTENCE_FINAL)):
            pytest.fail(f'ends on {last!r}: {text!r} {config} {parts}')


@given(text=soups(), final=st.booleans())
@settings(max_examples=150, **FUZZ)
def test_property_first_cue_never_raises_and_is_a_whole_word_prefix_of_what_arrived(text, final):
    from echo_sync.first_useful import first_cue
    COUNTS['hypothesis_examples_first_cue'] += 1
    cue = first_cue(text, 'Что такое система?', CONTROLLED, final=final, last=final)
    if cue is None:
        return
    arrived = text.lstrip()
    assert arrived.startswith(cue) and cue.strip(), (text, final, cue)
    assert not cut_inside_a_word(arrived, cue), (text, final, cue)
    if not final and arrived[-1:].isalnum():
        # the last word may be unfinished: it is never part of the cue
        last = list(re.finditer(r'[^\W_]+(?:[-’\'][^\W_]+)*', arrived))[-1]
        assert len(cue) <= last.start(), (text, cue)


# =====================================================================================================
# E. abbreviation expansion
# =====================================================================================================

TABLE = {'ВВП': 'валовой внутренний продукт', 'УК РФ': 'Уголовный кодекс Российской Федерации', 'ЦБ': 'Центральный банк'}
ABBREVIATION_TEXTS = [
    'ВВП растёт быстро. Рост ВВП важен для страны. Поэтому ВВП считают каждый квартал.',
    'За кражу судят по УК РФ, а за мошенничество тоже по УК РФ.',
    'ЦБ следит за ценами, а ВВП показывает рост экономики. Позже ЦБ снова обсудит ВВП.',
    'Валовой внутренний продукт (ВВП) растёт, а ВВП на душу населения тоже растёт.',
    'Статья 228 УК РФ предусматривает ответственность. Ответственность по УК РФ наступает с 16 лет.',
    'Рост ВВП говорит о расширении экономики, а ЦБ следит за ценами.',
    'Что такое ЦБ? ЦБ — это банк банков.',
]


@pytest.mark.parametrize('profile', PROFILES)
def test_abbreviations_are_expanded_once_in_one_piece_and_the_two_entry_points_agree(profile):
    bad = []
    for text in ABBREVIATION_TEXTS:
        config = {**H.PROFILES[profile], 'abbreviations': TABLE}
        spoken = expand_abbreviations(text, TABLE)
        parts = P(text, config)
        if H.lossless_problem(spoken, parts):
            bad.append((text, 'portions differ from expand_abbreviations()', parts))
        if expand_abbreviations(spoken, TABLE) != spoken:
            bad.append((text, 'expansion is not idempotent', spoken))
        for key, full in TABLE.items():
            found = list(re.finditer(r'(?<![\w-])' + re.escape(key) + r'(?![\w-])', text))
            if not found:
                continue
            # The first occurrence is replaced by the full term unless that term was already spelled out before it.
            spelled_before = normalize(full) in normalize(text[:found[0].start()])
            terms = normalize(text).count(normalize(full)) + (0 if spelled_before else 1)
            keys = len(found) - (0 if spelled_before else 1)
            got_terms = normalize(spoken).count(normalize(full))
            got_keys = len(re.findall(r'(?<![\w-])' + re.escape(key) + r'(?![\w-])', spoken))
            if (got_terms, got_keys) != (terms, keys):
                bad.append((text, f'{key!r}: expected {terms} full term(s) and {keys} short, got {got_terms} and {got_keys}', spoken))
            if H.cut_atoms(spoken, [full], parts):
                bad.append((text, f'the term {full!r} is cut in half', parts))
    assert not bad, show(bad)


# =====================================================================================================
# F. the streaming continuation: stable_prefix
# =====================================================================================================

def commits(text, config, how='words', seed=1):
    """What ControlledMedia._source commits after the first cue: growing prefixes of ``text`` into stable_prefix."""
    pieces = H.slices(text, how, random.Random(seed))
    committed, current, out = '', '', []
    for piece in pieces:
        current += piece
        COUNTS['stable_prefix_calls'] += 1
        nxt = stable_prefix(current, config, committed=committed)
        assert nxt is not None
        if nxt != committed:
            out.append(nxt)
            committed = nxt
    return out


def cut_inside_a_word(text, prefix):
    return bool(prefix) and len(prefix) < len(text) and prefix[-1].isalnum() and text[len(prefix)].isalnum()


def commit_problems(text, config, how):
    problems, previous = [], ''
    for nxt in commits(text, config, how):
        if not text.lstrip().startswith(nxt) or not nxt.startswith(previous):
            problems.append(('not a growing prefix of the text', nxt))
        elif cut_inside_a_word(text.lstrip(), nxt):
            problems.append(('a word is cut', nxt))
        previous = nxt
    return problems


SAMPLE = random.Random(20261101).sample([i for i in H.HAND_CORPUS if i.punctuated], 45)


@pytest.mark.parametrize('how', ['words', 'chars5'])
def test_stable_prefix_commits_whole_words_and_only_grows(how):
    bad = [(i.id, p) for i in SAMPLE for p in commit_problems(i.answer, CONTROLLED, how)]
    assert not bad, show(bad)


def with_whitespace(text, nth, replacement):
    spaces = [m.start() for m in re.finditer(' ', text)]
    at = spaces[nth % len(spaces)]
    return text[:at] + replacement + text[at + 1:]


ODD_WHITESPACE = ('\u00a0', '  ', '\n', '\t', '\u202f')


def test_stable_prefix_survives_non_breaking_spaces_double_spaces_and_newlines():
    minimal = 'Мама мыла раму папа пилил дрова дети ели кашу '
    for odd in ODD_WHITESPACE:
        text = minimal.replace(' ', odd, 1)
        prefix = stable_prefix(text, CONTROLLED, committed='')
        assert not cut_inside_a_word(text, prefix), (text, prefix)
    bad = []
    for item in SAMPLE[:25]:
        for n, odd in enumerate(ODD_WHITESPACE):
            text = with_whitespace(item.answer, n + 1, odd)
            COUNTS['whitespace_variants'] += 1
            bad += [(item.id, repr(odd), p) for p in commit_problems(text, CONTROLLED, 'words')]
    assert not bad, f'{len(bad)} commits cut a word or lose the prefix:\n  ' + show(bad)


# =====================================================================================================
# G. the streamed answer through the real ControlledMedia (host-like), hand-written corpus
# =====================================================================================================

PORTION_CAP_WORDS = PRESETS['meaning']['max_words']
PUNCTUATED = [i for i in H.HAND_CORPUS if i.punctuated][::2]      # every second answer of every category
UNPUNCTUATED = [i for i in H.HAND_CORPUS if not i.punctuated]
WALK_IDS = {item.id for item in PUNCTUATED[::4]}
RESLICED = random.Random(7).sample(PUNCTUATED, 16)
_RUNS = {}


def streamed(item, how='words', seed=0, config=None):
    key = (item.id, how, seed, json.dumps(config, sort_keys=True, ensure_ascii=False))
    if key not in _RUNS:
        COUNTS['stream_runs'] += 1
        _RUNS[key] = H.stream(item.question, item.answer, how, seed=seed, settings=config,
                              walk=(item.id in WALK_IDS and how == 'words' and config is None))
    return _RUNS[key]


def spoken_part(item, chunks):
    """How the chunks relate to the answer: ('whole'|'head'|'tail_lost'|'head_and_tail_lost'|'modified', shift).
    'head' = only the head the system may elide («Инерция — это») is missing; shift = non-space chars dropped in front."""
    flat, got = H.nospace(item.answer), H.nospace(''.join(chunks))
    if got == flat:
        return 'whole', 0
    if flat.endswith(got):
        shift = len(flat) - len(got)
        return ('head' if H.nospace(item.elide).startswith(flat[:shift]) else 'modified'), shift
    if flat.startswith(got):
        return 'tail_lost', 0
    for shift in range(1, len(flat)):
        if flat[shift:].startswith(got):
            return ('head_and_tail_lost' if H.nospace(item.elide).startswith(flat[:shift]) else 'modified'), shift
    return 'modified', 0


def test_every_punctuated_answer_gets_a_first_cue_and_its_words_arrive_in_order():
    bad = []
    for item in PUNCTUATED:
        run = streamed(item)
        kind, _ = spoken_part(item, run.chunks)
        if not run.cues or kind not in ('whole', 'head') or run.cues[0] != run.chunks[0]:
            bad.append((item.id, kind, run.cues[:1], run.chunks))
    assert not bad, show(bad)


def test_the_streamed_text_does_not_depend_on_how_the_provider_slices_it():
    bad = []
    for item in RESLICED:
        base = H.nospace(''.join(streamed(item).chunks))
        for how, seed in (('chars5', 0), ('random', 3), ('random', 11)):
            if H.nospace(''.join(streamed(item, how, seed).chunks)) != base:
                bad.append((item.id, how, seed))
    assert not bad, show(bad)


def test_the_streamed_portions_never_cut_a_word():
    bad = []
    for item in PUNCTUATED:
        run = streamed(item)
        kind, shift = spoken_part(item, run.chunks)
        cut = H.cut_words(item.answer, run.chunks, shift=shift)
        if cut:
            bad.append((item.id, cut, run.chunks))
    assert not bad, show(bad)


def test_every_streamed_cue_is_short_enough_to_repeat():
    # C7-A: a question for a number or a date runs on to its number, in the wider window of such a question (up to 12 words).
    # c20-first-cue (G15): any other first cue is a finished thought of at most the profile's documented word cap (PRESETS['meaning']['max_words'] = 9), not 8:
    # the 8-word window is where the planner's cut may fall, G15 lengthens that cue to its sentence end while the sentence still fits a portion
    bad = [(item.id, streamed(item).cues[0]) for item in PUNCTUATED
           if streamed(item).cues
           and H.product_words(streamed(item).cues[0]) > (MEANING_NUMBER_FIRST_MAX_WORDS if asks_for_number(item.question) else PORTION_CAP_WORDS)]
    assert not bad, show(bad)


@pytest.mark.parametrize('kinds', [('neg',), ('decimal', 'grouped', 'numdate'), ('unit',)])
def test_streamed_portions_keep_negations_numbers_and_documented_units_together(kinds):
    bad = []
    for item in PUNCTUATED:
        atoms = item.atoms_of(*kinds)
        if atoms:
            run = streamed(item)
            kind, shift = spoken_part(item, run.chunks)
            hit = H.cut_atoms(item.answer, atoms, run.chunks, shift=shift)
            if hit:
                bad.append((item.id, hit, run.chunks))
    assert not bad, show(bad)


def test_every_streamed_portion_repeated_verbatim_advances_exactly_once():
    bad, checked = [], 0
    for item in PUNCTUATED:
        run = streamed(item)
        if run.walk is not None and run.cues:
            checked += 1
            if run.walk != run.chunks:
                bad.append((item.id, run.walk, run.chunks))
    assert checked >= 25 and not bad, show(bad)


def test_character_by_character_streaming_keeps_numbers_negations_and_units_whole():
    """The harshest slicing a provider could use: one character per delta."""
    ids = {'percent-02', 'negation-01', 'number_unit-01', 'number_unit-04', 'date_year-01', 'percent-04'}
    checked, bad = 0, []
    for item in H.HAND_CORPUS:
        if item.id in ids:
            checked += 1
            run = H.stream(item.question, item.answer, 'chars1', walk=False)
            COUNTS['stream_runs'] += 1
            kind, shift = spoken_part(item, run.chunks)
            hit = H.cut_atoms(item.answer, item.atoms_of('neg', 'decimal', 'grouped', 'unit'), run.chunks, shift=shift)
            if kind not in ('whole', 'head') or hit or H.cut_words(item.answer, run.chunks, shift=shift):
                bad.append((item.id, kind, hit, run.chunks))
    assert checked == len(ids) and not bad, show(bad)


ANSWERS_THAT_BEGIN_WITH_A_PIECE = [
    ('Какое расстояние от Земли до Луны?', '384 400 километров — таково среднее расстояние от Земли до Луны.', ['384 400 километров']),
    ('Какая доля расходов на питание?', '6,5 процента — такова доля расходов на питание в бюджете семьи.', ['6,5 процента']),
    ('Сколько человек учится в классе?', '25 человек — столько учеников в этом классе.', ['25 человек']),
    ('Работает ли магазин в воскресенье?', 'Не работает, так как в воскресенье у магазина выходной день.', ['Не работает']),
]


@pytest.mark.parametrize('how', ['chars1', 'chars5'])
def test_a_cue_is_never_made_of_the_first_half_of_a_piece_that_is_still_arriving(how):
    """The answer starts with the piece, so the first complete-looking portion of the partial text IS the piece's
    beginning ('384 ', '6,5', 'Не '): the first cue must wait for the portion after it."""
    bad = []
    for question, answer, atoms in ANSWERS_THAT_BEGIN_WITH_A_PIECE:
        run = H.stream(question, answer, how, walk=False)
        COUNTS['stream_runs'] += 1
        item = H.Item('t', 't', question, answer, [], '')
        kind, shift = spoken_part(item, run.chunks)
        if kind not in ('whole', 'head') or H.cut_atoms(answer, atoms, run.chunks, shift=shift):
            bad.append((answer, kind, run.cues[:1], run.chunks))
    assert not bad, show(bad)


def test_an_unpunctuated_answer_never_gets_a_cut_word_or_a_reordered_one():
    bad = []
    for item in UNPUNCTUATED:
        run = streamed(item)
        kind, shift = spoken_part(item, run.chunks)
        if run.chunks and (kind == 'modified' or H.cut_words(item.answer, run.chunks, shift=shift)):
            bad.append((item.id, kind, run.chunks))
    assert not bad, show(bad)


@pytest.mark.xfail(strict=True, reason="DEF-SEG-13: an answer without terminal punctuation is never delivered completely: the last portion(s) are "
                                       "withheld for ever (a short one is total silence) - Stream('Как называется столица Франции?', 'Столица Франции — Париж') -> no cue at all. "
                                       "WAVE 2 / Task C-seg: delivered completely once the host's 0.1 s tick runs (ControlledMedia._settle, fix round 2): "
                                       "tests/test_task_c_unpunctuated.py, 14 of 14. This harness never ticks, so it stays red by construction.")
def test_an_answer_without_terminal_punctuation_is_still_delivered_completely():
    bad = []
    for item in UNPUNCTUATED:
        run = streamed(item)
        kind, _ = spoken_part(item, run.chunks)
        if not run.cues or kind not in ('whole', 'head'):
            bad.append((item.id, item.answer, kind, run.chunks))
    assert not bad, f'{len(bad)} of {len(UNPUNCTUATED)} answers lose their tail or are silent:\n  ' + show(bad, 5)


def test_the_first_cue_is_not_cut_at_an_abbreviation_period():
    cases = [('Что значит т. е.?', 'Сокращение «т. е.» значит «то есть» и вводит уточнение.', 'т. е.'),
             ('Кто подписал этот приказ?', 'Приказ подписал Иванов И. И., а утвердил директор.', 'Иванов И. И.'),
             ('Какие бывают фрукты?', 'Яблоки, груши и т. д. продаются на рынке каждый день.', 'и т. д.')]
    bad = []
    for question, answer, atom in cases:
        run = H.stream(question, answer, 'words', walk=False)
        kind, shift = spoken_part(H.Item('t', 't', question, answer, [], ''), run.chunks)
        if H.cut_atoms(answer, [atom], run.chunks, shift=shift):
            bad.append((answer, run.chunks))
    for item in PUNCTUATED:
        atoms = item.atoms_of('abbr', 'initials')
        if atoms:
            run = streamed(item)
            kind, shift = spoken_part(item, run.chunks)
            if H.cut_atoms(item.answer, atoms, run.chunks, shift=shift):
                bad.append((item.answer, run.chunks))
    assert not bad, show(bad)


# --- the first cue is not an echo of the question --------------------------------------------------------

RESTATING_BUT_FINE = [
    ('Сколько планет в Солнечной системе?', 'В Солнечной системе восемь планет.'),
    ('Какая столица у Франции?', 'Столица Франции — Париж.'),
    ('Где находится Эльбрус?', 'Эльбрус находится на Кавказе.'),
    ('Какая самая высокая гора в мире?', 'Самая высокая гора в мире — Эверест.'),
    ('Сколько градусов в прямом угле?', 'В прямом угле девяносто градусов.'),
    ('Зачем нужны витамины?', 'Витамины нужны для нормальной работы организма.'),
    ('Правда ли что кит рыба?', 'Нет, кит не рыба.'),
]
ECHOING = [
    ('Перечисли планеты земной группы?', 'К планетам земной группы относятся Меркурий, Венера, Земля и Марс.'),
    ('Что устанавливает первый закон Ньютона?', 'Первый закон Ньютона устанавливает, что тело сохраняет покой или движение.'),
    ('Что гласит третий закон Ньютона?', 'Третий закон Ньютона гласит, что действие равно противодействию.'),
    ('Кто был вторым президентом США?', 'Вторым президентом США был Джон Адамс.'),
    ('Когда закончилась Вторая мировая война?', 'Вторая мировая война закончилась 2 сентября 1945 года.'),
    ('Когда началась Первая мировая война?', 'Первая мировая война началась в 1914 году и закончилась в 1918 году.'),
    ('Чем отличается вирус от бактерии?', 'Вирус отличается от бактерии тем, что не имеет клеточного строения.'),
]


def a_short_cue_could_say_more(answer, question, atoms=()):
    """WAVE 2 / L2: a first cue is 2-4 words (5 only to keep a unit whole). True when some prefix of 2-4 words says more than
    the question AND is a place where a cue may end: it does not end on a word that needs the next one and it tears none of
    the declared pieces. An opening that restates the question for longer than that has no short cue that says more."""
    words = answer.split()
    for k in range(2, min(4, len(words)) + 1):
        last = (normalize(words[k - 1]).split() or [''])[-1]
        if last in KEEP_WITH_NEXT and words[k - 1][-1:] not in SENTENCE_FINAL:
            continue
        prefix = ' '.join(words[:k])
        if H.cut_atoms(answer, list(atoms), [prefix, ' '.join(words[k:])]):
            continue
        if not H.echoes_question(prefix, question):
            return True
    return False


def test_an_answer_that_restates_the_question_is_cued_from_its_first_new_word():
    """The cue says more than the question whenever a cue of 2-4 (5) words can; an opening that restates it for longer than
    that («Самая высокая гора в мире — Эверест.») is cued as the restatement, in a short unit, and the new word follows."""
    bad = []
    for question, answer in RESTATING_BUT_FINE:
        run = H.stream(question, answer, 'words', walk=False)
        if not run.cues or H.product_words(run.cues[0]) > MEANING_FIRST_MAX_WORDS:    # F1: a meaning first cue (it was 5 words)
            bad.append((question, run.cues))
        elif H.echoes_question(run.cues[0], question) and a_short_cue_could_say_more(answer, question):
            bad.append((question, run.cues))
    assert not bad, show(bad)


def test_the_first_cue_is_never_just_an_echo_of_the_question():
    """DEF-SEG-16 as WAVE 2 / L2 settles it: the first cue is not the question read back when a cue of 2-4 words can say more
    (the old gate took an ordinal or a mis-lemmatised word for new: 'Вторая', 'Третий закон'). An opening that restates the
    question for longer than a cue may be has no such cue; it is then cued as the restatement, never longer than a cue."""
    bad = []
    for question, answer in ECHOING:
        run = H.stream(question, answer, 'words', walk=False)
        if run.cues and H.echoes_question(run.cues[0], question):
            if a_short_cue_could_say_more(answer, question) or H.product_words(run.cues[0]) > 5:
                bad.append((question, run.cues[0]))
    for item in PUNCTUATED:
        run = streamed(item)
        if run.cues and H.echoes_question(run.cues[0], item.question):
            if a_short_cue_could_say_more(item.answer, item.question, [a for _, a in item.atoms]) \
                    or H.product_words(run.cues[0]) > 5:
                bad.append((item.question, run.cues[0]))
    assert not bad, show(bad, 6)


def lone_fragment(cue):
    """One word that is neither a whole clause (it does not end at a punctuation mark) nor a long word that could
    not be joined to its neighbour: the listener is asked to repeat half a phrase."""
    cfg = resolve(CONTROLLED)
    return (H.product_words(cue) == 1 and cue.rstrip()[-1:] not in ',;:.!?…—–'
            and syllables(cue) < cfg['long_word_syllables'])


def test_the_first_cue_is_not_a_lone_word_cut_out_of_a_phrase():
    bad = []
    for item in PUNCTUATED:
        run = streamed(item)
        if run.cues and lone_fragment(run.cues[0]) and len(run.chunks) > 1:
            bad.append((item.id, run.cues[0], run.chunks[:3]))
    assert not bad, f'{len(bad)} of {len(PUNCTUATED)} first cues are a lone word that continues:\n  ' + show(bad, 5)


def test_a_one_word_cue_that_ends_a_clause_or_is_the_whole_answer_is_fine():
    """Positive control of the check above: an enumeration item «Монархия,» and a yes/no «Нет.» are whole thoughts."""
    assert not lone_fragment('Монархия,') and not lone_fragment('Нет.') and not lone_fragment('Электроэнцефалография')
    assert lone_fragment('конечная') and lone_fragment('Расстояние') and lone_fragment('Вторая')
    run = H.stream('Правда ли что кит рыба?', 'Нет.', 'words', walk=False)
    assert run.cues == ['Нет.'] and run.chunks == ['Нет.']
    run = H.stream('Какие бывают формы правления?', 'Монархия, республика и теократия — три основные формы правления.',
                   'words', walk=False)
    # WAVE 2 / L2: the cue is the two-word unit (it was the one-word «Монархия,» only because the plan was made over a text
    # that ended in the middle of the sentence); a first cue of one word is only a long word or a whole one-word answer.
    # F1 (wave F): the first clause, up to its dash. c22-merge (WAVE23 c22 item 3): a first cue never ends on a dash; the clause after it fits
    # the cap (8 words), so the cue is the whole sentence (G15 at c22-base already gave it, c22-base is red on the old line)
    assert run.cues[0] == 'Монархия, республика и теократия — три основные формы правления.' and not lone_fragment(run.cues[0])


def test_no_streamed_portion_of_the_corpus_is_a_phrase_the_phone_handles_itself():
    bad = [(item.id, c) for item in PUNCTUATED + UNPUNCTUATED for c in streamed(item).chunks
           if normalize(c) in CONDUIT_LOCAL_PHRASES]
    assert not bad, show(bad)


def test_a_streamed_portion_is_never_a_phrase_the_phone_handles_itself():
    cases = [('Как попрощаться вежливо?', 'До свидания. Всего доброго вам и удачи.'),
             ('Как завершить звонок вежливо?', 'Закончить разговор. Затем положите трубку.'),
             ('Как попрощаться по-русски?', 'До свидания.'), ('Какая команда завершает вызов?', 'Закончить разговор.')]
    bad = []
    for question, answer in cases:
        run = H.stream(question, answer, 'words', walk=False)
        bad += [(answer, c) for c in run.chunks if normalize(c) in CONDUIT_LOCAL_PHRASES]
    assert not bad, show(bad)


# --- bounds of the STREAMED portions ----------------------------------------------------------------------

def test_streamed_portions_respect_the_configured_bounds_like_the_offline_plan_does():
    cfg = resolve(CALL_SETTINGS)                 # F1 (wave F): the bounds of the profile the stream runs on (the call's)
    bad = []
    for item in PUNCTUATED:
        run = streamed(item)
        kind, shift = spoken_part(item, run.chunks)
        if kind in ('whole', 'head'):
            bad += [(item.id,) + p for p in bound_problems(item, run.chunks, cfg, shift=shift, skip_first=True)]
    assert not bad, f'{len(bad)} avoidable breaches in {len(PUNCTUATED)} streamed answers:\n  ' + show(bad, 5)


# --- abbreviations while streaming ---------------------------------------------------------------------

def test_abbreviation_expansion_is_consistent_when_the_answer_streams():
    config = {**CONTROLLED, 'abbreviations': TABLE}
    bad = []
    for text in ABBREVIATION_TEXTS:
        run = H.stream('Расскажи про экономику?', text, 'words', settings=config, walk=False)
        spoken = expand_abbreviations(text, TABLE)
        problem = H.lossless_problem(spoken, run.chunks)
        cut = [full for full in TABLE.values() if H.cut_atoms(spoken, [full], run.chunks)]
        if problem or cut:
            bad.append((text, problem or f'term cut: {cut}', run.chunks))
    assert not bad, show(bad)


# =====================================================================================================
# H. the classic engine path: stored plan, and every portion repeated verbatim advances
# =====================================================================================================

@pytest.mark.parametrize('config', [CONTROLLED, {}], ids=['ru_aligned_controlled', 'stem_default'])
def test_engine_serves_exactly_the_portioner_plan_in_order(tmp_path, config):
    bad = []
    for n, item in enumerate(PUNCTUATED[::6]):
        engine = EchoEngine(tmp_path / f'{n}.sqlite3', lambda *a, answer=item.answer: answer, settings=config)
        spoken = [engine_reply(engine, session_id='s', turn_id='q', text=item.question, request={}, model='m')]
        for step in range(60):
            if spoken[-1] == SILENT:
                break
            COUNTS['engine_replies'] += 1
            spoken.append(engine_reply(engine, session_id='s', turn_id=f'a{step}', text=spoken[-1], request={}, model='m'))
        plan = P(item.answer, config)
        if spoken != plan + [SILENT] or (engine.state('s') or {}).get('chunks') != plan:
            bad.append((item.id, spoken, plan))
    assert not bad, show(bad)


# =====================================================================================================
# I. quality statistics (the report is produced from the same function)
# =====================================================================================================

def test_the_quality_statistics_are_consistent():
    for profile in ('controlled', 'words3', 'range_2_8'):
        q = H.quality(H.HAND_CORPUS, H.PROFILES[profile])
        assert sum(q['hist_words'].values()) == q['portions'] > 400
        assert q['boundaries'] == q['portions'] - q['answers']
        assert 0.0 < q['share_at_punctuation'] < 1.0
        assert q['boundaries_at_punctuation'] == q['boundaries_at_sentence_end'] + q['boundaries_at_clause_punctuation']
        assert len(q['worst']) == 10 and all(reasons for _, _, reasons in q['worst'])
        assert 0 <= q['one_word_portions'] <= q['portions'] and q['portions_spanning_a_sentence_end'] >= 0
    # the same statistics for what the host-like controller really produced
    sample = PUNCTUATED[:24]
    q = H.quality(sample, CALL_SETTINGS, plans={item.id: streamed(item).chunks for item in sample})
    assert q['answers'] == 24 and sum(q['hist_words'].values()) == q['portions'] > q['answers']   # F1: 40 meaning portions (was > 50)
    assert q['boundaries'] == q['portions'] - q['answers']
