"""WAVE 2 / S6, axis "ack": what counts as the user's repeat (adversarial, property-based).

Required behaviour (owner directives 2026-11-01, section 1 and 3): a full correct repeat advances; a partial repeat does
not; a wrong number or a dropped/added «не»/«ни» does not; the system's own TTS never confirms itself; «повтори» repeats
without a model call; «стоп» always stops; a duplicate ACK advances at most once.

The tests encode that requirement, not the current behaviour. A requirement that fails today is kept as
``xfail(strict=True, raises=...)`` with the defect id in the reason (``DEF-ACK-nn``); a point that may be a deliberate design choice is
``QUESTION-ACK-nn``. When a fix lands, the test XPASSes and strict mode forces the marker to be removed.

Everything runs against the real classes: ``analyze`` (the one function that decides "repeat accepted"), ``EchoEngine``,
``ControlledMedia`` built with the keyword arguments of ``controlled_host.serve``, and ``NativeMediaSocket``. Fakes only at
the external boundary (clock, provider events, lookup, SAPI synthesis). See helpers_s6_ack.py.

WAVE 2 / Task A: the markers of DEF-ACK-01..18 and 22 and of QUESTION-ACK-02 and 04 were removed when the defects were
fixed (tests/test_ack_commands.py, test_ack_normalisation.py, test_ru_numbers.py hold the unit tests of the fixes). Still
xfail: QUESTION-ACK-01 (times, fractions,
ranges; «°C» and the other units were closed by WAVE 2 / Task U, tests/test_task_u_unit_repeats.py), -03 (the engine does not
replay a completed answer). WAVE 2 / Task B closed DEF-ACK-19/20/21 and decided
QUESTION-ACK-05 (own voice: the cue-in-flight window) and -06 (a repeat split into consecutive finals: the pieces are joined).

Index (brief, axis "ack"):
  1 a full correct repeat is accepted despite ASR variation ...... section 1 (case, punctuation, ё/е, spaces, fillers, hyphen,
                                                                    digits/words, merges/splits, double-say, verbatim round trip)
  2 a partial repeat does not complete the portion ............... section 2
  3 a different number, added/dropped «не»/«ни», another term ..... section 3 (+ dispatch level: cursor, actions, model calls)
  4 «повтори» / «ещё раз» / «не расслышал» / «что?» ............... section 4
  5 «стоп» / «хватит» / «замолчи» ................................ section 5 (ControlledMedia and NativeMediaSocket)
  6 the same ACK delivered twice advances at most once ............ section 6 (engine threads, controller, reconnect, wire)
  7 the system's own TTS never confirms itself .................... section 7
  8 robustness (no exception for any transcript, purity) .......... section 8
"""
import asyncio
import copy
import re
import tempfile
import threading
import time
from dataclasses import replace
from pathlib import Path

import pymorphy3
import pytest
from hypothesis import assume, example, given
from hypothesis import strategies as st

import helpers_s6_ack as H
from echo_sync.classifier import ACK, CORRECTION, QUESTION
from echo_sync.controlled_media import ACK_JOIN_SECONDS
from echo_sync.engine import EchoEngine
from echo_sync.portioner import portions
from echo_sync.textutil import normalize, stem
from engine_say import engine_reply

PLAIN = H.PLAIN


def numbered(values):
    """ASCII test ids for parametrized Cyrillic values (pytest would print them as unicode escapes)."""
    return [f'{i:02d}' for i in range(len(values))]


ALL_MODES = list(H.MODES)             # loops and fixed lists: ru_aligned (production), stem (classic default), exact
HYP_MODES = ['ru_aligned']   # b63fed3f removed the ack_match key: the aligned comparison is the rule of every call, 'stem' and 'exact' are no modes any more


def tick(name, n=1):
    H.CASES[name] += n


def check_ack(heard, portion, mode='ru_aligned'):
    d = H.verdict(heard, portion, H.MODES[mode])
    assert d.kind == ACK, H.describe(heard, portion, d)


def check_not_ack(heard, portion, mode='ru_aligned'):
    d = H.verdict(heard, portion, H.MODES[mode])
    assert d.kind != ACK, 'FALSE CONFIRMATION: ' + H.describe(heard, portion, d)


@pytest.fixture(scope='module')
def accept_walker(tmp_path_factory):
    return H.Walker(tmp_path_factory.mktemp('accept'), H.LONG_ANSWERS)


@pytest.fixture(scope='module')
def reject_walker(tmp_path_factory):
    return H.Walker(tmp_path_factory.mktemp('reject'), H.LONG_ANSWERS)


@pytest.fixture(scope='module')
def command_walker(tmp_path_factory):
    return H.Walker(tmp_path_factory.mktemp('command'), H.LONG_ANSWERS)


# ====================================================================================================================
# 0. The harness must stay the host
# ====================================================================================================================

def test_harness_runs_the_profile_and_wiring_the_host_runs():
    assert H.HOST_PASSES_SETTINGS, 'ROOT-1: serve() builds the controller with controller_settings(profile); PROD_SETTINGS is derived from it'
    assert {'source_delivery', 'lookup_policy', 'first_useful_gate', 'coalesce_seconds', 'quiet_reopen'} <= set(H.HOST_KWARGS)


def test_the_number_oracle_speaks_known_numbers():
    """The tests generate spoken numbers themselves; a wrong oracle would turn a defect test into noise."""
    known = {0: 'ноль', 15: 'пятнадцать', 21: 'двадцать один', 100: 'сто', 125: 'сто двадцать пять', 340: 'триста сорок',
             999: 'девятьсот девяносто девять'}
    big = {1000: 'тысяча', 1500: 'тысяча пятьсот', 2000: 'две тысячи', 2500: 'две тысячи пятьсот', 5000: 'пять тысяч',
           8849: 'восемь тысяч восемьсот сорок девять', 11000: 'одиннадцать тысяч', 21000: 'двадцать одна тысяча',
           22000: 'двадцать две тысячи', 300000: 'триста тысяч'}
    years = {1945: 'в тысяча девятьсот сорок пятом году', 2026: 'в две тысячи двадцать шестом году',
             1941: 'в тысяча девятьсот сорок первом году', 1950: 'в тысяча девятьсот пятидесятом году',
             1812: 'в тысяча восемьсот двенадцатом году', 2001: 'в две тысячи первом году'}
    assert {n: H.cardinal(n) for n in known} == known
    assert {n: H.cardinal_big(n) for n in big} == big
    assert {y: H.year_in_year(y) for y in years} == years


def test_corpus_is_real_portioner_output_with_the_features_the_properties_need():
    assert len(H.PORTIONS) >= 80              # F1 (wave F): meaning portions, 85 of the corpus (it was >= 150 short portions)
    assert len(H.NUMERIC_PORTIONS) >= 20 and len(H.NEGATED_PORTIONS) >= 10 and len(H.HYPHEN_PORTIONS) >= 3
    for answer in H.ANSWERS:
        assert portions(answer, H.CFG), answer


# ====================================================================================================================
# 1. A full correct repeat is accepted despite ASR variation
# ====================================================================================================================

@pytest.mark.parametrize('mode', ALL_MODES)
def test_a_verbatim_repeat_of_every_issued_portion_is_acknowledged(mode):
    """Self-consistency: whatever the system issues, saying exactly that must be accepted (else the dictation stalls)."""
    for portion in H.CONTENT_PORTIONS:
        tick('verbatim-' + mode)
        check_ack(portion, portion, mode)


@pytest.mark.parametrize('mode', ['ru_aligned'])
@H.properties(120)
@given(portion=st.sampled_from(H.CONTENT_PORTIONS), style=H.styles)
def test_asr_surface_noise_never_prevents_acknowledgement(mode, portion, style):
    """Case, punctuation, spaces of every kind, ё/е, NFC/NFD: the same words are the same repeat."""
    tick('noise-' + mode)
    check_ack(H.apply_style(style, portion), portion, mode)


YO_PAIRS = (('еще раз', 'ещё раз'), ('ее мнение', 'её мнение'), ('зеленый лист', 'зелёный лист'),
            ('твердый шар', 'твёрдый шар'), ('елка', 'ёлка'), ('черный ящик', 'чёрный ящик'))


@pytest.mark.parametrize('mode', ['ru_aligned'])
@pytest.mark.parametrize('portion,heard', YO_PAIRS + tuple((b, a) for a, b in YO_PAIRS), ids=numbered(YO_PAIRS + tuple((b, a) for a, b in YO_PAIRS)))
def test_yo_and_ye_are_one_letter_in_both_directions(mode, portion, heard):
    tick('yo-' + mode)
    check_ack(heard, portion, mode)


LISTED_FILLERS = ('э', 'эм', 'ну', 'ну э', 'э ну', 'ну вот', 'так', 'вот', 'окей', 'и', 'а', 'итак', 'пожалуйста',
                  'хорошо', 'слушайте')
INERT_FILLERS = ('ладно', 'ок', 'скажи', 'скажите', 'подскажи', 'подскажите', 'слушай')   # on the list, yet ignored


@H.properties(120)
@given(portion=st.sampled_from(H.CONTENT_PORTIONS), filler=st.sampled_from(LISTED_FILLERS),
       punct=st.sampled_from(['', ',', '.', '…']), style=H.styles)
def test_listed_fillers_in_front_of_a_repeat_are_ignored(portion, filler, punct, style):
    assert all(w in H.FILLERS for w in filler.split()), 'filler list changed: update LISTED_FILLERS'
    tick('listed-fillers')
    check_ack(filler + punct + ' ' + H.apply_style(style, portion), portion)


@H.properties(120)
@example(portion='Наклон земной оси', filler='ладно', style=PLAIN)
@given(portion=st.sampled_from(H.CONTENT_PORTIONS), filler=st.sampled_from(INERT_FILLERS), style=H.styles)
def test_every_filler_on_the_default_list_is_ignored_in_front_of_a_repeat(portion, filler, style):
    assert filler in H.FILLERS, 'filler list changed: update INERT_FILLERS'
    tick('inert-fillers')
    check_ack(filler + ', ' + H.apply_style(style, portion), portion)


HESITATIONS = ('мм', 'ммм', 'ээ', 'эээ')


@H.properties(120)
@example(portion='Наклон земной оси', filler='мм', style=PLAIN)
@given(portion=st.sampled_from(H.CONTENT_PORTIONS), filler=st.sampled_from(HESITATIONS), style=H.styles)
def test_unlisted_hesitation_sounds_in_front_of_a_repeat_are_ignored(portion, filler, style):
    tick('hesitation-lead')
    check_ack(filler + ', ' + H.apply_style(style, portion), portion)


TRAILING_FILLERS = ('э', 'эм', 'мм', 'ну')


@H.properties(120)
@example(portion='Наклон земной оси', filler='ну', style=PLAIN)
@given(portion=st.sampled_from(H.CONTENT_PORTIONS), filler=st.sampled_from(TRAILING_FILLERS), style=H.styles)
def test_a_hesitation_after_a_repeat_is_ignored(portion, filler, style):
    tick('hesitation-trail')
    check_ack(H.apply_style(style, portion) + ', ' + filler, portion)


# -- punctuation tokens an ASR emits that the matcher does not know -------------------------------------------------

ASR_PUNCTUATION = ('...', '?!', '!!', '??', '“', '”', '’')


@H.properties(150)
@example(portion='Наклон земной оси', mark='...', where=0)
@given(portion=st.sampled_from(H.CONTENT_PORTIONS), mark=st.sampled_from(ASR_PUNCTUATION), where=st.integers(0, 3))
def test_asr_punctuation_marks_do_not_prevent_acknowledgement(portion, mark, where):
    tick('asr-punctuation')
    words = portion.split()
    if where == 0:
        heard = ' '.join(words) + mark
    elif where == 1:
        heard = mark + ' '.join(words)
    else:
        i = max(1, len(words) // 2)
        heard = ' '.join(words[:i]) + mark + ' ' + ' '.join(words[i:])
    assume(not re.search(r'(?<!\S)[—–][^\w\s]', heard))                # DEF-ACK-23 (its own strict test below)
    check_ack(heard, portion)


@pytest.mark.xfail(strict=True, raises=AssertionError,
                   reason='DEF-ACK-23: an ASR mark glued to a standalone dash («Масса —... это мера», «—?!», «—”») is not '
                          'acknowledged (silent/attempt_ru_alignment), while «Масса — ... это мера» is. Pre-existing on 66b29f1 for every '
                          'mark of ASR_PUNCTUATION; the portion corpus reached it once W1F-A kept «Инерция — это свойство» together')
@pytest.mark.parametrize('heard,portion', [('Инерция —... это свойство', 'Инерция — это свойство'),
                                           ('Масса —?! это мера', 'Масса — это мера'),
                                           ('Венера —” из-за плотной атмосферы', 'Венера — из-за плотной атмосферы')],
                         ids=['ellipsis', 'interrobang', 'quote'])
def test_an_asr_mark_glued_to_a_dash_does_not_prevent_acknowledgement(heard, portion):
    check_ack(heard, portion)


# -- hyphen vs space ---------------------------------------------------------------------------------------------------

COMPOUNDS = (('по-русски', 'по русски'), ('из-за', 'из за'), ('кое-что', 'кое что'), ('северо-запад', 'северо запад'),
             ('интернет-магазин', 'интернет магазин'), ('какой-либо', 'какой либо'), ('по-новому', 'по новому'),
             ('всё-таки', 'всё таки'), ('кто-нибудь', 'кто нибудь'), ('юго-восток', 'юго восток'), ('Wi-Fi', 'Wi Fi'))
COMPOUND_FRAMES = ('это {} важно', 'здесь {}', 'там было {} видно')


@pytest.mark.parametrize('mode', [
    'ru_aligned'])
@H.properties(150, defect=False)
@example(pair=COMPOUNDS[0], frame=COMPOUND_FRAMES[0], swap=False, style=PLAIN)
@given(pair=st.sampled_from(COMPOUNDS), frame=st.sampled_from(COMPOUND_FRAMES), swap=st.booleans(), style=H.styles)
def test_hyphen_and_space_in_a_compound_are_the_same_repeat(mode, pair, frame, swap, style):
    tick('hyphen-' + mode)
    hyphenated, spaced = pair
    portion, heard = (frame.format(spaced), frame.format(hyphenated)) if swap else (frame.format(hyphenated), frame.format(spaced))
    check_ack(H.apply_style(style, heard), portion, mode)


# -- digits vs number words -------------------------------------------------------------------------------------------

SMALL_FRAMES = ('ставка {} процентов', 'в {} раз больше', 'около {} километров', 'статья {}', 'всего {} человек',
                'температура {} градусов', 'через {} минут', 'номер {}')


@H.properties(150)
@given(frame=st.sampled_from(SMALL_FRAMES), n=st.integers(0, 999), swap=st.booleans(), style=H.styles)
def test_digits_and_number_words_are_interchangeable_below_1000(frame, n, swap, style):
    tick('numbers-small')
    digits, words = frame.format(n), frame.format(H.cardinal(n))
    portion, heard = (words, digits) if swap else (digits, words)
    check_ack(H.apply_style(style, heard), portion)


OBLIQUE = (('около пятнадцати процентов', 'около 15 процентов'), ('до двадцати пяти лет', 'до 25 лет'),
           ('нет трёх причин', 'нет 3 причин'), ('у четырёх человек', 'у 4 человек'), ('из ста человек', 'из 100 человек'),
           ('с двумя участниками', 'с 2 участниками'), ('к девятнадцати годам', 'к 19 годам'))


@pytest.mark.parametrize('heard,portion', OBLIQUE + tuple((b, a) for a, b in OBLIQUE), ids=numbered(OBLIQUE + tuple((b, a) for a, b in OBLIQUE)))
def test_number_words_in_any_case_match_their_digits(heard, portion):
    tick('numbers-oblique')
    check_ack(heard, portion)


BIG_FRAMES = ('высота {} метров', 'около {} человек', 'стоимость {} рублей', 'в {} раз больше')


@H.properties(150)
@example(frame='высота {} метров', n=2500, swap=False)
@given(frame=st.sampled_from(BIG_FRAMES), n=st.integers(1000, 999_999), swap=st.booleans())
def test_digits_and_number_words_are_interchangeable_from_1000(frame, n, swap):
    tick('numbers-big')
    digits, words = frame.format(n), frame.format(H.cardinal_big(n))
    portion, heard = (words, digits) if swap else (digits, words)
    check_ack(heard, portion)


@H.properties(150)
@example(year=1945, swap=False)
@given(year=st.integers(1001, 2099).filter(lambda y: y % 100), swap=st.booleans())
def test_a_year_in_digits_and_in_words_is_the_same_repeat(year, swap):
    tick('numbers-year')
    digits, words = f'в {year} году', H.year_in_year(year)
    portion, heard = (words, digits) if swap else (digits, words)
    check_ack(heard, portion)


ORDINAL_DATES = (('22 июня', 'двадцать второго июня'), ('1 сентября', 'первого сентября'), ('9 мая', 'девятое мая'),
                 ('5 мая', 'пятого мая'), ('в 21 веке', 'в двадцать первом веке'), ('в 19 веке', 'в девятнадцатом веке'),
                 ('в 10 классе', 'в десятом классе'))


@H.properties(100)
@example(pair=ORDINAL_DATES[0], swap=False)
@given(pair=st.sampled_from(ORDINAL_DATES), swap=st.booleans())
def test_an_ordinal_written_with_digits_matches_its_spoken_form(pair, swap):
    tick('numbers-ordinal')
    digits, words = pair
    portion, heard = (words, digits) if swap else (digits, words)
    check_ack(heard, portion)


GROUPINGS = (' ', '\u00a0', '\u202f', '\u2009', '')


def grouped(n, sep):
    return f'{n:,}'.replace(',', sep)


@H.properties(150)
@example(n=1500, a=' ', b='')
@given(n=st.integers(1000, 9_999_999), a=st.sampled_from(GROUPINGS), b=st.sampled_from(GROUPINGS))
def test_thousands_grouping_does_not_change_the_number(n, a, b):
    if a == b:
        return
    tick('numbers-grouping')
    check_ack(f'около {grouped(n, b)} человек', f'около {grouped(n, a)} человек')


WRITTEN_VS_SPOKEN = (('в 10:30', 'в десять часов тридцать минут'), ('3,5 литра', 'три целых пять десятых литра'),
                     ('3,5 литра', 'три с половиной литра'), ('1/2', 'одна вторая'), ('5–10 минут', 'от пяти до десяти минут'),
                     ('№ 5', 'номер пять'), ('100 °C', 'сто градусов Цельсия'), ('5 мин', 'пять минут'), ('3 л', 'три литра'),
                     ('5 тыс.', 'пять тысяч'), ('5 млн', 'пять миллионов'), ('в XXI веке', 'в двадцать первом веке'))
# WAVE 2 / Task A: decimals («три целых пять десятых», «три с половиной»), «№», «мин/л/тыс./млн» and Roman centuries are bridged
# now (ru_numbers / ru_alignment). Times, fractions and ranges are still open (QUESTION-ACK-01); «°C» and the other units were
# bridged by WAVE 2 / Task U (ru_alignment._units).
STILL_UNSUPPORTED = (('в 10:30', 'в десять часов тридцать минут'), ('1/2', 'одна вторая'), ('5–10 минут', 'от пяти до десяти минут'))
SUPPORTED_FORMS = tuple(pair for pair in WRITTEN_VS_SPOKEN if pair not in STILL_UNSUPPORTED)


@pytest.mark.parametrize('written,spoken', SUPPORTED_FORMS, ids=numbered(SUPPORTED_FORMS))
def test_written_forms_match_their_spoken_forms(written, spoken):
    tick('written-vs-spoken')
    check_ack(spoken, written)
    check_ack(written, spoken)


@pytest.mark.xfail(strict=True, raises=AssertionError, reason='QUESTION-ACK-01: times, fractions and ranges never match their spoken forms; '
                                       'SETTINGS.md lists dates/fractions as unsupported. Both sides are GPT text, so is it enough?')
@pytest.mark.parametrize('written,spoken', STILL_UNSUPPORTED, ids=numbered(STILL_UNSUPPORTED))
def test_written_forms_that_are_still_open_match_their_spoken_forms(written, spoken):
    tick('written-vs-spoken-open')
    check_ack(spoken, written)
    check_ack(written, spoken)


# -- ASR merges and splits of words -------------------------------------------------------------------------------------

MERGE_SPLIT = (('чтобы', 'что бы'), ('поэтому', 'по этому'), ('зато', 'за то'), ('также', 'так же'), ('тоже', 'то же'),
               ('вследствие', 'в следствие'), ('электроэнцефалограмма', 'электро энцефалограмма'),
               ('полупроводник', 'полу проводник'), ('нейросеть', 'нейро сеть'), ('вебсайт', 'веб сайт'),
               ('микроволновая', 'микро волновая'), ('саморазвитие', 'само развитие'), ('полгода', 'пол года'))


@H.properties(120)
@example(pair=MERGE_SPLIT[0], frame='это {} важно', swap=False, style=PLAIN)
@given(pair=st.sampled_from(MERGE_SPLIT), frame=st.sampled_from(('это {} важно', 'здесь {}', 'там было {} видно')),
       swap=st.booleans(), style=H.styles)
def test_asr_word_merges_and_splits_are_the_same_repeat(pair, frame, swap, style):
    tick('merge-split')
    merged, split = pair
    portion, heard = (frame.format(split), frame.format(merged)) if swap else (frame.format(merged), frame.format(split))
    check_ack(H.apply_style(style, heard), portion)


# -- saying the portion twice -------------------------------------------------------------------------------------------

def filler_led(portion):
    words = H.norm_words(portion)
    return bool(words) and words[0] in H.FILLERS


@H.properties(100)
@given(portion=st.sampled_from([p for p in H.CONTENT_PORTIONS if not filler_led(p)]), style=H.styles,
       glue=st.sampled_from([' ', ', ', '. ', ' … ']))
def test_saying_the_portion_twice_in_a_row_confirms_it_once(portion, style, glue):
    tick('double-say')
    assume(not re.match(r'с\s+\d', portion.casefold()))                 # DEF-ACK-24 (its own strict test below)
    first = H.apply_style(replace(style, trail=''), portion)
    check_ack(first + glue + H.apply_style(style, portion), portion)


# DEF-ACK-24 (cured by g7, ru_alignment.without_repeats: a phrase said twice in a row is said once): «с 1939 с 1939» was not acknowledged
@pytest.mark.parametrize('glue', [' ', ', '], ids=['space', 'comma'])
def test_a_preposition_s_portion_said_twice_confirms_it_once(glue):
    check_ack('с 1939' + glue + 'с 1939', 'с 1939')


@pytest.mark.parametrize('portion', ['а млекопитающее,', 'Так называемый эффект', 'и электронов,', 'Вот почему зимой'],
                         ids=['a-mammal', 'tak-nazyvaemyi', 'i-electrons', 'vot-pochemu'])
def test_saying_a_filler_led_portion_twice_confirms_it_once(portion):
    tick('double-say-filler-led')
    check_ack(portion + ' ' + portion, portion)


# -- a portion made only of filler words ---------------------------------------------------------------------------------

FILLER_ONLY_ANSWERS = ('Хорошо.', 'Ну и так.', 'Скажи пожалуйста.', 'Окей. Ладно. Так.')


@H.properties(40)
@example(answer='Хорошо.')
@given(answer=st.sampled_from(FILLER_ONLY_ANSWERS))
def test_every_issued_portion_can_be_confirmed_even_if_it_is_only_fillers(answer):
    issued = portions(answer, H.CFG)
    assert issued, 'the portioner issues it: ' + answer
    for portion in issued:
        tick('filler-only')
        check_ack(portion, portion)


# ====================================================================================================================
# 2. A partial repeat does not complete the portion
# ====================================================================================================================

PARTIAL_PORTIONS = tuple(p for p in H.CONTENT_PORTIONS if len(H.content_words(p)) >= 2 and len(p.split()) >= 2)


MORPH = pymorphy3.MorphAnalyzer()
LOOSE_TAGS = frozenset({'ADVB', 'PRCL', 'CONJ', 'INTJ'})
ADJECTIVE_TAGS = frozenset({'ADJF', 'ADJS', 'PRTF'})


def left_out_by_design(portion, heard):
    """F1 (wave F, brief: ACK of a long portion «по-человечески»): in a portion of 5 words or more ONE word that states nothing (an
    adverb, a particle, a conjunction) may be left out - two words in a portion of 8 or more; never an adjective (candidate 8 audit, ruling A:
    a part of the term), «не»/«ни» or a number. Such a repeat confirms the portion by design (ru_alignment._lenient): it is not a partial repeat.
    Independent of the product: pymorphy3's first reading of each left-out word."""
    words, kept = H.plain_words(portion), H.plain_words(heard)
    if len(words) < 5:
        return False
    rest, dropped = list(kept), []
    for word in words:
        if rest and normalize(rest[0]) == normalize(word):
            rest.pop(0)
        else:
            dropped.append(word)
    if rest or not dropped or len(dropped) > (1 if len(words) < 8 else 2):
        return False
    if any(normalize(w) in ('не', 'ни') or any(c.isdigit() for c in w) for w in dropped):
        return False
    tags = [MORPH.parse(normalize(w))[0].tag.POS for w in dropped]
    return all(t in LOOSE_TAGS for t in tags)


def partial_variants(portion, data):
    """A strict, non-empty part of the portion that leaves out at least one content word."""
    words = H.plain_words(portion)
    n = len(words)
    named = set(H.content_words(portion))
    content = [i for i, w in enumerate(words) if normalize(w) in named]
    shape = data.draw(st.sampled_from(['any', 'first_part', 'last_part']))
    k = data.draw(st.integers(1, n - 1))
    if shape == 'first_part':
        mask = [i < k for i in range(n)]
    elif shape == 'last_part':
        mask = [i >= k for i in range(n)]
    else:
        mask = data.draw(st.lists(st.booleans(), min_size=n, max_size=n))
    victim = data.draw(st.sampled_from(content))
    if all(mask[i] for i in content):
        mask[victim] = False                      # at least one content word is missing
    if not any(mask):
        mask[(victim + 1) % n] = True             # but something was said
    return ' '.join(w for w, keep in zip(words, mask) if keep)


@pytest.mark.parametrize('mode', HYP_MODES)
@H.properties(100)
@given(portion=st.sampled_from(PARTIAL_PORTIONS), data=st.data(), style=H.styles)
def test_a_partial_repeat_never_acknowledges(mode, portion, data, style):
    """A missing content word, only the first half, only the second half: not a confirmation, in every matcher."""
    heard = partial_variants(portion, data)
    assert heard.strip(), 'strategy bug: empty partial'
    assume(mode != 'ru_aligned' or not left_out_by_design(portion, heard))
    tick('partial-' + mode)
    check_not_ack(H.apply_style(style, heard), portion, mode)


@pytest.mark.parametrize('mode', [
    'ru_aligned'])
@H.properties(60)
@example(portion='Наклон земной оси')
@example(portion='Когда температура падает ниже нуля')
@example(portion='Как правило, вода кипит')
@given(portion=st.sampled_from(PARTIAL_PORTIONS))
def test_a_partial_repeat_never_becomes_a_new_question(mode, portion):
    """Rising intonation makes an ASR add «?», and portions often start with «как/что/когда»: still not a new question."""
    words = H.plain_words(portion)
    heard = [' '.join(words[:k]) + mark for k in range(1, len(words)) for mark in ('', '?')]
    heard += [' '.join(words[k:]) + mark for k in range(1, len(words)) for mark in ('', '?')]
    for text in heard:
        tick('partial-not-question-' + mode)
        d = H.verdict(text, portion, H.MODES[mode])
        assert d.kind not in (QUESTION, CORRECTION), 'PARTIAL REPEAT TREATED AS A NEW QUESTION: ' + H.describe(text, portion, d)


def test_after_a_partial_repeat_the_same_portion_comes_back_and_not_the_next_one(tmp_path):
    """A partial repeat leaves the cursor where it was and what is missing of the unconfirmed portion is spoken (not skipped, not the next). G3, rule 3
    (changed on purpose): only the missing tail, not the whole portion again."""
    d = H.Dictation(tmp_path / 'again', H.LONG_ANSWERS[1])
    portion, before = d.current, d.index
    out = d.say(' '.join(portion.split()[:-1]))
    assert out.after == before and out.speaks == [] and not out.destroyed, out.actions
    spoken = []
    for _ in range(8):                                  # silence: the transport ticks about once a second
        d.clock.advance(1.0)
        spoken = [a['text'] for a in d.controller.tick(now=d.clock()) if a['type'] == 'speak']
        if spoken:
            break
    tick('partial-comes-back')
    assert spoken == [portion.split()[-1]] and d.index == before, (spoken, d.index)


@pytest.mark.parametrize('portion,heard', [
    ('Хорошо проводит тепло', 'проводит тепло'),
    ('Так называемый парниковый эффект', 'называемый парниковый эффект')], ids=['khorosho-provodit', 'tak-nazyvaemyi'])
def test_leaving_out_a_content_word_that_is_also_a_filler_is_not_a_confirmation(portion, heard):
    tick('filler-content-word')
    check_not_ack(heard, portion)


@pytest.mark.parametrize('portion,heard', [
    ('Что-то вроде электронной', 'Что то вроде электронной'),
    ('как-то так получилось', 'как то так получилось'),
    ('где-то около десяти', 'где то около десяти'),
    ('почему-то так вышло', 'почему то так вышло'),
    ('когда-нибудь потом узнаем', 'когда нибудь потом узнаем'),
    ('чтобы всё получилось', 'что бы всё получилось')], ids=['chto-to', 'kak-to', 'gde-to', 'pochemu-to', 'kogda-nibud', 'chtoby'])
def test_a_word_split_inside_a_question_word_compound_is_not_a_new_question(portion, heard):
    tick('split-question-word')
    d = H.verdict(heard, portion)
    assert d.kind not in (QUESTION, CORRECTION), 'CORRECT REPEAT DESTROYS THE DICTATION: ' + H.describe(heard, portion, d)


def test_dispatch_a_split_compound_in_a_real_portion_keeps_the_answer(tmp_path):
    answer = next(a for a in H.ANSWERS if a.startswith('Что-то вроде'))
    d = H.Dictation(tmp_path / 'split', answer)
    # F1 (wave F): the sentence is one meaning portion (WAVE 2 / L2 had the 2-word «Что-то вроде»)
    assert d.current == 'Что-то вроде электронной почты используют многие компании.'
    out = d.say('Что то вроде электронной почты используют многие компании')
    tick('dispatch-split-question-word')
    assert not out.destroyed, f'the answer was dropped: {out.types}'
    assert out.after == out.before + 1, f'the repeat did not advance: {out.before} -> {out.after}'


# ====================================================================================================================
# 3. A different number, an added or dropped «не»/«ни», a different key term is not accepted
# ====================================================================================================================

def different(n, how):
    """A number that differs from ``n`` the way an ASR or a speaker gets numbers wrong."""
    s = str(n)
    if how == 'plus_one':
        return n + 1
    if how == 'minus_one':
        return n - 1 if n > 0 else n + 2
    if how == 'plus_ten':
        return n + 10
    if how == 'times_ten':
        return n * 10 if n else 10
    if how == 'div_ten':
        return n // 10 if n >= 10 else n + 3
    if how == 'swap':
        if len(s) >= 2 and s[-1] != s[-2]:
            return int(s[:-2] + s[-1] + s[-2])
        return n + 7
    if how == 'confusable':                # 15 <-> 50, 13 <-> 30 ...
        if 13 <= n <= 19:
            return (n - 10) * 10
        if n in range(30, 100, 10):
            return n // 10 + 10
        return n + 5
    if how == 'append_digit':
        return n * 10 + (n % 7) + 1
    return n // 10 if n >= 10 else n + 11     # drop_digit


NUMBER_ERRORS = ('plus_one', 'minus_one', 'plus_ten', 'times_ten', 'div_ten', 'swap', 'confusable', 'append_digit', 'drop_digit')


@st.composite
def wrong_number_case(draw):
    frame = draw(st.sampled_from(SMALL_FRAMES))
    n = draw(st.integers(0, 2100))
    m = different(n, draw(st.sampled_from(NUMBER_ERRORS)))
    assert m != n and m >= 0
    portion_in_words = n < 1000 and draw(st.booleans())
    heard_in_words = m < 1000 and draw(st.booleans())
    portion = frame.format(H.cardinal(n) if portion_in_words else n)
    heard = frame.format(H.cardinal(m) if heard_in_words else m)
    return portion, heard


@pytest.mark.parametrize('mode', HYP_MODES)
@H.properties(100)
@given(case=wrong_number_case(), style=H.styles)
def test_a_different_number_is_never_acknowledged(mode, case, style):
    portion, heard = case
    tick('wrong-number-' + mode)
    check_not_ack(H.apply_style(style, heard), portion, mode)


WRONG_NUMBER_PAIRS = (('в 1945 году', 'в 1954 году'), ('ставка 15 процентов', 'ставка 50 процентов'), ('3,5 процента', '3,6 процента'),
                      ('3,5 процента', '35 процентов'), ('3,5 процента', '5,3 процента'), ('статья 228', 'статья 282'),
                      ('статья 228', 'статья 229'), ('36,6 градуса', '36,9 градуса'), ('1 500 рублей', '1 600 рублей'),
                      ('1500 рублей', '15000 рублей'), ('0,5 литра', '5 литров'), ('в 2026 году', 'в 2062 году'),
                      ('тринадцать процентов', 'тридцать процентов'), ('пятнадцать лет', 'пятьдесят лет'),
                      ('в 1941 году', 'в сорок первом году'), ('сто двадцать', 'сто двенадцать'))


@pytest.mark.parametrize('mode', ALL_MODES)
@pytest.mark.parametrize('portion,heard', WRONG_NUMBER_PAIRS + tuple((b, a) for a, b in WRONG_NUMBER_PAIRS), ids=numbered(WRONG_NUMBER_PAIRS + tuple((b, a) for a, b in WRONG_NUMBER_PAIRS)))
def test_typical_number_slips_are_never_acknowledged(mode, portion, heard):
    tick('number-slips-' + mode)
    check_not_ack(heard, portion, mode)


SIGN_UNIT_PAIRS = (('минус пять градусов', 'пять градусов'), ('плюс пять градусов', 'минус пять градусов'),
                   ('+5 градусов', '-5 градусов'), ('−5 градусов', '5 градусов'), ('5 кг', '5 г'), ('5 г', '5 мг'),
                   ('5 мг', '5 мм'), ('5 км', '5 м'), ('5 метров', '5 километров'), ('5 сантиметров', '5 миллиметров'),
                   ('5%', '5‰'), ('5 процентов', '5 промилле'), ('2 + 3', '2 - 3'), ('2 × 3', '2 / 3'), ('x > 3', 'x < 3'),
                   ('x ≤ 3', 'x ≥ 3'), ('a + b', 'a - b'))


@pytest.mark.parametrize('mode', ALL_MODES)
@pytest.mark.parametrize('portion,heard', SIGN_UNIT_PAIRS + tuple((b, a) for a, b in SIGN_UNIT_PAIRS), ids=numbered(SIGN_UNIT_PAIRS + tuple((b, a) for a, b in SIGN_UNIT_PAIRS)))
def test_a_changed_sign_unit_or_operator_is_never_acknowledged(mode, portion, heard):
    tick('sign-unit-' + mode)
    check_not_ack(heard, portion, mode)


@pytest.mark.parametrize('mode', HYP_MODES)
@H.properties(100)
@given(portion=st.sampled_from(H.NEGATED_PORTIONS), data=st.data(), style=H.styles)
def test_a_dropped_negation_is_never_acknowledged(mode, portion, data, style):
    words = H.plain_words(portion)
    where = [i for i, w in enumerate(words) if normalize(w) in ('не', 'ни')]
    i = data.draw(st.sampled_from(where))
    heard = ' '.join(words[:i] + words[i + 1:])
    if not heard:
        return
    tick('dropped-negation-' + mode)
    check_not_ack(H.apply_style(style, heard), portion, mode)


@pytest.mark.parametrize('mode', HYP_MODES)
@H.properties(100)
@given(portion=st.sampled_from(H.CONTENT_PORTIONS), data=st.data(), word=st.sampled_from(['не', 'ни']), style=H.styles)
def test_an_added_negation_is_never_acknowledged(mode, portion, data, word, style):
    words = H.plain_words(portion)
    i = data.draw(st.integers(0, len(words)))
    tick('added-negation-' + mode)
    check_not_ack(H.apply_style(style, ' '.join(words[:i] + [word] + words[i:])), portion, mode)


TERM_PAIRS = (('равно', 'неравно'), ('возможно', 'невозможно'), ('важно', 'неважно'), ('верно', 'неверно'),
              ('правильно', 'неправильно'), ('достаточно', 'недостаточно'), ('можно', 'нельзя'), ('есть', 'нет'),
              ('всегда', 'никогда'), ('везде', 'нигде'), ('иногда', 'никогда'), ('и', 'или'), ('до', 'после'),
              ('перед', 'после'), ('над', 'под'), ('вверх', 'вниз'), ('внутри', 'снаружи'), ('выше', 'ниже'),
              ('дальше', 'ближе'), ('раньше', 'позже'), ('чаще', 'реже'), ('быстрее', 'медленнее'), ('сильнее', 'слабее'),
              ('лучше', 'хуже'), ('растёт', 'падает'), ('входит', 'выходит'), ('нагревается', 'охлаждается'),
              ('поглощает', 'выделяет'), ('увеличивает', 'уменьшает'), ('открыт', 'закрыт'), ('включить', 'выключить'),
              ('разрешено', 'запрещено'), ('первый', 'последний'), ('начало', 'конец'), ('максимум', 'минимум'),
              ('север', 'юг'), ('запад', 'восток'), ('левый', 'правый'), ('масса', 'вес'), ('скорость', 'ускорение'),
              ('Москва', 'Минск'), ('кислород', 'водород'), ('азот', 'углерод'), ('меньше', 'больше'), ('вдвое', 'втрое'))
TERM_FRAMES = ('это {} здесь', 'всегда {} вода', 'если {} то', 'значит {} сегодня')


@pytest.mark.parametrize('mode', HYP_MODES)
@H.properties(100)
@given(pair=st.sampled_from(TERM_PAIRS), frame=st.sampled_from(TERM_FRAMES), swap=st.booleans(), style=H.styles)
def test_a_different_key_term_is_never_acknowledged(mode, pair, frame, swap, style):
    a, b = (pair[1], pair[0]) if swap else pair
    tick('key-term-' + mode)
    check_not_ack(H.apply_style(style, frame.format(b)), frame.format(a), mode)


VOCABULARY = tuple(sorted({w for p in H.CONTENT_PORTIONS for w in H.content_words(p) if w.isalpha() and len(w) >= 4}))


def other_lemma(a, b):
    from echo_sync.ru_alignment import _lemma
    return stem(a) != stem(b) and _lemma(a) != _lemma(b)


@pytest.mark.parametrize('mode', HYP_MODES)
@H.properties(100)
@given(portion=st.sampled_from(PARTIAL_PORTIONS), data=st.data())
def test_swapping_any_content_word_for_another_word_is_never_acknowledged(mode, portion, data):
    words = H.plain_words(portion)
    named = set(H.content_words(portion))
    i = data.draw(st.sampled_from([k for k, w in enumerate(words) if normalize(w) in named]))
    replacement = data.draw(st.sampled_from(VOCABULARY))
    if not other_lemma(normalize(words[i]), replacement):
        return
    tick('swapped-term-' + mode)
    check_not_ack(' '.join(words[:i] + [replacement] + words[i + 1:]), portion, mode)


CONSECUTIVE = tuple((a, b) for answer in H.ANSWERS for a, b in zip(portions(answer, H.CFG), portions(answer, H.CFG)[1:])
                    if normalize(a) != normalize(b))


@pytest.mark.parametrize('mode', HYP_MODES)
@H.properties(100)
@given(pair=st.sampled_from(CONSECUTIVE), forward=st.booleans(), style=H.styles)
def test_the_neighbouring_portion_never_acknowledges_the_current_one(mode, pair, forward, style):
    """Locality: only the portion that waits can be confirmed; the next and the previous one cannot."""
    current, neighbour = pair if forward else (pair[1], pair[0])
    tick('neighbour-' + mode)
    check_not_ack(H.apply_style(style, neighbour), current, mode)


@pytest.mark.parametrize('portion,heard', [('Закон был принят', 'Закон будет принят'), ('Налог был отменён', 'Налог будет отменён'),
                                           ('вода кипит', 'вода кипела'), ('он придёт', 'он пришёл')],
                         ids=['byl-budet-zakon', 'byl-budet-nalog', 'kipit-kipela', 'pridet-prishel'])
def test_a_flipped_tense_is_not_the_same_repeat(portion, heard):
    tick('tense-flip')
    check_not_ack(heard, portion)


# ====================================================================================================================
# Dispatch level: the same decisions through ControlledMedia built as the host builds it, events fed the way
# NativeMediaSocket.provider feeds them (speech start, turn.created, turn.done). A cursor move is read from the
# engine's stored state, a "model call" is a lookup/context/route action or a call of the engine's generate function.
# ====================================================================================================================

@H.properties(50, shared_state=True)
@given(style=H.styles)
def test_dispatch_a_correct_repeat_advances_exactly_one_portion_and_calls_no_model(accept_walker, style):
    d = accept_walker.dictation(remaining=2)
    portion = d.current
    heard = H.apply_style(style, portion)
    out = d.say(heard)
    tick('dispatch-accept')
    assert out.after == out.before + 1, f'repeat {heard!r} of {portion!r} moved the cursor {out.before} -> {out.after}: {out.types}'
    assert out.types == ['speak'] and out.speaks == [d.chunks[out.after]], out.actions
    assert out.model_calls == 0


def rejected_text(portion, neighbours, picks):
    """Something a user could say that is NOT a full correct repeat of ``portion``.

    Every choice is read from ``picks`` (integers drawn up front), so the strategy does not depend on the live dictation.
    """
    words = H.plain_words(portion)
    named = set(H.content_words(portion))
    content = [i for i, w in enumerate(words) if normalize(w) in named]
    kinds = ['negation']
    if neighbours:
        kinds.append('neighbour')
    if content and len(words) >= 2:
        kinds.append('partial')
    if content:
        kinds.append('swap')
    if any(w.isdigit() for w in words):
        kinds.append('number')
    kind = kinds[picks[0] % len(kinds)]
    if kind == 'partial':
        mask = [(picks[1] >> i) & 1 == 1 for i in range(len(words))]
        victim = content[picks[2] % len(content)]
        if all(mask[i] for i in content):
            mask[victim] = False
        if not any(mask):
            mask[(victim + 1) % len(words)] = True
        return ' '.join(w for w, keep in zip(words, mask) if keep)
    if kind == 'neighbour':
        return neighbours[picks[1] % len(neighbours)]
    if kind == 'number':
        slots = [k for k, w in enumerate(words) if w.isdigit()]
        i = slots[picks[1] % len(slots)]
        m = different(int(words[i]), NUMBER_ERRORS[picks[2] % len(NUMBER_ERRORS)])
        return ' '.join(words[:i] + [str(m)] + words[i + 1:])
    if kind == 'swap':
        i = content[picks[1] % len(content)]
        for step in range(len(VOCABULARY)):
            replacement = VOCABULARY[(picks[2] + step) % len(VOCABULARY)]
            if other_lemma(normalize(words[i]), replacement):
                return ' '.join(words[:i] + [replacement] + words[i + 1:])
    hits = [i for i, w in enumerate(words) if normalize(w) in ('не', 'ни')]
    if hits and len(words) >= 2:
        return ' '.join(words[:hits[0]] + words[hits[0] + 1:])
    i = picks[1] % (len(words) + 1)
    return ' '.join(words[:i] + ['не'] + words[i:])


@H.properties(90, shared_state=True)
@given(picks=st.lists(st.integers(0, 10 ** 6), min_size=4, max_size=4), style=H.styles)
def test_dispatch_a_partial_or_wrong_repeat_changes_nothing_and_calls_no_model(reject_walker, picks, style):
    d = reject_walker.dictation(remaining=1)
    portion = d.current
    index = d.index
    neighbours = [c for c in d.chunks if normalize(c) != normalize(portion)][:6]
    heard = H.apply_style(style, rejected_text(portion, neighbours, picks))
    # WAVE 2 / Task B (ACK-split): attempts less than ACK_JOIN_SECONDS apart are ONE speech, and two partial slices may spell
    # the portion. The examples of this property are independent attempts, so they are spaced beyond that window.
    out = d.say(heard, gap=ACK_JOIN_SECONDS + 1.0)
    tick('dispatch-reject')
    assert d.index == index and out.after == out.before, f'{heard!r} moved the cursor of {portion!r}: {out.before} -> {out.after}'
    assert not out.destroyed, f'{heard!r} for {portion!r} dropped or restarted the answer: {out.types}'
    assert out.model_calls == 0
    # G3, rule 3 (changed on purpose): a listener stuck on the start of the portion hears what is missing of it
    assert all(portion.endswith(text) for text in out.speaks), f'{heard!r} spoke {out.speaks!r}, the waiting portion is {portion!r}'


def test_confirming_every_portion_in_turn_completes_the_answer_and_a_late_repeat_is_harmless(tmp_path):
    walked = 0
    for n, answer in enumerate(H.LONG_ANSWERS[:4]):
        d = H.Dictation(tmp_path / f'walk{n}', answer)
        total = len(d.chunks)
        # F1 (wave F): 3-6 meaning portions per long answer (it was >= 5 short ones). c23-final: G15 (laptop c18 211f329, cap 9 of c22-merge) makes a whole
        # sentence of <= 9 words one portion: «Кит не рыба, а млекопитающее, которое дышит лёгкими.» | «Ставка налога … 13 процентов.» is 2 (pre-c18: 3+).
        # The walk still crosses a portion boundary, and the four answers give 15 portions (6+3+2+4: the 9-word second sentence of the third answer is one portion).
        assert total >= 2
        walked += total
        for k in range(total):
            tick('walk-through')
            portion = d.current
            out = d.say(portion)
            assert out.after == k + 1 and out.model_calls == 0, (answer, k, out)
            assert out.speaks == ([d.chunks[k + 1]] if k + 1 < total else []), (answer, k, out)
        assert d.completed and d.remaining == 0
        late = d.say(d.chunks[-1])
        assert late.speaks == [] and late.after == late.before and not late.destroyed, late
    assert walked >= 15, walked


# QUESTION-ACK-03 decided (2 Nov, root-cause round): «повтори» after the last confirmed portion speaks that portion once more.
def test_a_repeat_request_after_the_last_confirmation_repeats_the_last_portion(tmp_path):
    d = H.Dictation(tmp_path / 'end', H.LONG_ANSWERS[0])
    for _ in range(len(d.chunks)):
        d.say(d.current)
    assert d.completed
    last = d.chunks[-1]
    out = d.say('повтори')
    assert out.speaks == [last], out.actions


# ====================================================================================================================
# 4. «повтори», «ещё раз», «не расслышал», «что?»: repeat request, no advance, no model call
# ====================================================================================================================

def repeated_promptly(d, out, within=1.0):
    """The portion is spoken again at once, or at the next tick within ``within`` seconds."""
    if d.current in out.speaks:
        return True
    d.clock.advance(within)
    later = d.controller.tick(now=d.clock())
    return d.current in [a['text'] for a in later if a['type'] == 'speak']


REPEAT_REQUESTS = ('повтори', 'повторите', 'ещё раз', 'повтори пожалуйста')


@H.properties(60, shared_state=True)
@given(phrase=st.sampled_from(REPEAT_REQUESTS), style=H.styles)
def test_a_repeat_request_repeats_the_same_portion_without_advance_or_model_call(command_walker, phrase, style):
    d = command_walker.dictation(remaining=1)
    portion = d.current
    out = d.say(H.apply_style(style, phrase))
    tick('repeat-request')
    assert out.after == out.before, f'{phrase!r} moved the cursor'
    assert out.types == ['speak'] and out.speaks == [portion], out.actions
    assert out.model_calls == 0


HEARING_REPAIRS = ('не расслышал', 'не расслышала', 'что?', 'не понял', 'не услышал')


@pytest.mark.parametrize('phrase', HEARING_REPAIRS, ids=numbered(HEARING_REPAIRS))
def test_a_hearing_repair_request_never_advances_and_never_calls_a_model(tmp_path, phrase):
    d = H.Dictation(tmp_path / 'repair', H.LONG_ANSWERS[1])
    portion = d.current
    out = d.say(phrase)
    tick('hearing-repair-safe')
    assert out.after == out.before and d.current == portion
    assert out.model_calls == 0 and not out.destroyed


@pytest.mark.parametrize('phrase', HEARING_REPAIRS, ids=numbered(HEARING_REPAIRS))
def test_a_hearing_repair_request_repeats_the_portion_promptly(tmp_path, phrase):
    d = H.Dictation(tmp_path / 'repair', H.LONG_ANSWERS[1])
    out = d.say(phrase)
    tick('hearing-repair-prompt')
    assert repeated_promptly(d, out), f'{phrase!r}: {d.current!r} was not repeated within 1 s (actions={out.types})'


INTERJECTIONS = ('чего?', 'как?', 'что-что?', 'ась?', 'прости?', 'извини?')


@pytest.mark.parametrize('phrase', INTERJECTIONS, ids=numbered(INTERJECTIONS))
def test_a_hearing_repair_interjection_is_not_a_new_question(tmp_path, phrase):
    d = H.Dictation(tmp_path / 'interjection', H.LONG_ANSWERS[1])
    out = d.say(phrase)
    tick('interjection')
    assert not out.destroyed, f'{phrase!r} dropped the dictation: {out.types}'
    assert out.after == out.before


POLITE_REPEATS = ('ещё раз пожалуйста', 'ещё раз, пожалуйста', 'повтори ещё раз', 'повторить пожалуйста', 'можешь повторить',
                  'можно ещё раз')


@pytest.mark.parametrize('phrase', POLITE_REPEATS, ids=numbered(POLITE_REPEATS))
def test_polite_and_reordered_repeat_requests_repeat_the_portion(tmp_path, phrase):
    d = H.Dictation(tmp_path / 'polite', H.LONG_ANSWERS[1])
    out = d.say(phrase)
    tick('polite-repeat')
    assert not out.destroyed and out.after == out.before and out.model_calls == 0, f'{phrase!r}: {out.types}'
    assert repeated_promptly(d, out), f'{phrase!r}: {d.current!r} was not repeated within 1 s (actions={out.types})'


# ====================================================================================================================
# 5. «стоп», «хватит», «замолчи»: stop, nothing further plays
# ====================================================================================================================

def check_stopped(d, old_portion):
    """CL2, ruling 1: «стоп» cuts the sound and PAUSES the answer: the plan is kept, nothing is said by itself, nothing queued may
    play, a late text of the model stays silent; the listener's repeat of the paused portion goes on; a new question works."""
    c = d.controller
    assert d.state.get('paused') and d.current == old_portion, 'the paused plan was not kept'
    assert c.tick(now=d.clock() + 3600) == [], 'a stopped dictation must not auto-repeat'
    assert all(not c.authorized(cue) for cue in d.cues), 'queued audio of the stopped answer is still authorized'
    late_answer = d.deliver(H.done('a-late', 'assistant', 'Продолжение старого ответа, которое никто не просил.'))
    assert late_answer.actions == [], late_answer.actions
    late_ack = d.say(old_portion)
    assert late_ack.after == late_ack.before + 1 and late_ack.speaks == [d.current] and not late_ack.destroyed, late_ack.actions
    # the session stays usable: a new question gets a new answer
    question = d.say('Расскажи про это')
    assert question.types[:1] == ['cancel']
    fresh = d.deliver(H.done('a-new', 'assistant', 'Новый ответ после остановки сказан полностью.'))
    assert [a['type'] for a in fresh.actions] == ['speak'], fresh.actions


STOP_WORDS = ('стоп', 'остановись', 'отмена', 'прекрати')


@pytest.mark.parametrize('word', STOP_WORDS, ids=numbered(STOP_WORDS))
def test_a_stop_word_stops_and_nothing_further_plays(tmp_path, word):
    d = H.Dictation(tmp_path / 'stop', H.LONG_ANSWERS[2])
    old = d.current
    out = d.say(word)
    tick('stop')
    assert out.types == ['cancel'] and out.model_calls == 0, out.actions
    check_stopped(d, old)


@H.properties(12)
@given(word=st.sampled_from(STOP_WORDS), style=H.styles, filler=st.sampled_from(['', 'ну ', 'э ', 'пожалуйста ']))
def test_a_stop_word_is_a_stop_whatever_the_transcript_punctuation_and_case(word, style, filler):
    with tempfile.TemporaryDirectory() as directory:
        d = H.Dictation(Path(directory) / 'stop', H.LONG_ANSWERS[3])
        old = d.current
        out = d.say(filler + H.apply_style(style, word))
        tick('stop-noise')
        assert out.types == ['cancel'], out.actions
        assert d.state.get('paused') and d.controller.tick(now=d.clock() + 3600) == []   # CL2, ruling 1: a pause
        assert d.say('повтори').speaks == [old], 'the paused portion is the one a repeat request brings back'


STOP_VARIANTS = ('стоп стоп', 'стоп-стоп', 'стоп, стоп, стоп', 'стоп пожалуйста', 'стоп, пожалуйста', 'стой')


@pytest.mark.parametrize('phrase', STOP_VARIANTS, ids=numbered(STOP_VARIANTS))
def test_natural_variants_of_stop_stop(tmp_path, phrase):
    d = H.Dictation(tmp_path / 'stopvar', H.LONG_ANSWERS[2])
    out = d.say(phrase)
    tick('stop-variant')
    assert out.types == ['cancel'] and d.state.get('paused'), f'{phrase!r} did not stop the dictation: {out.types}'


@pytest.mark.parametrize('phrase', ('хватит', 'замолчи'), ids=['khvatit', 'zamolchi'])
def test_stop_words_the_phone_is_documented_to_handle_stop_the_server_too(tmp_path, phrase):
    d = H.Dictation(tmp_path / 'phone-words', H.LONG_ANSWERS[2])
    out = d.say(phrase)
    tick('phone-stop-words')
    assert out.types == ['cancel'] and d.state.get('paused'), f'{phrase!r} did not stop the dictation: {out.types}'


def test_wire_stop_silences_the_stream_cancels_queued_audio_and_stays_quiet(tmp_path):
    async def scenario(directory):
        wire = H.Wire(directory, pcm_ms=600)
        try:
            await wire.begin(H.LONG_ANSWERS[2], settle=False)
            deadline = time.monotonic() + 3                            # wait for the first cue to be streaming
            while wire.audio_frames == 0 and time.monotonic() < deadline:
                await asyncio.sleep(0.005)
            assert 0 < wire.audio_frames < 30, 'precondition: the first cue is being streamed (600 ms = 30 frames)'
            streamed, cleared = wire.audio_frames, wire.cleared()
            await wire.user('стоп')
            frames_at_stop = wire.audio_frames
            assert wire.cleared() > cleared, 'stop did not clear the output audio buffer'
            await asyncio.sleep(0.3)
            await wire.elapse(60)                                      # a minute of silence: no auto-repeat either
            assert wire.audio_frames == frames_at_stop, 'audio went on after stop'
            assert wire.controller.state()['paused']                  # CL2, ruling 1: «стоп» pauses the answer
            # the session stays usable
            await wire.socket.provider(H.created('q2', 'user', ''))
            await wire.socket.provider(H.done('q2', 'user', 'Расскажи про это'))
            await wire.socket.provider(H.done('a2', 'assistant', 'Новый ответ после остановки сказан полностью.'))
            await wire.settle()
            assert wire.audio_frames > frames_at_stop, 'no audio for the next question after a stop'
            return streamed
        finally:
            await wire.close()

    tick('wire-stop')
    asyncio.run(scenario(tmp_path / 'wire-stop'))


# ====================================================================================================================
# 6. The same ACK delivered twice (duplicate / retransmit) advances at most once
# ====================================================================================================================

def test_engine_the_same_turn_delivered_concurrently_advances_once(tmp_path):
    """A retransmit racing the original: four threads, one turn id, one stored cursor."""
    answer = H.LONG_ANSWERS[0]
    for n in range(6):
        clock = H.FakeClock()
        engine = EchoEngine(tmp_path / f'dup{n}.sqlite3', lambda *args: answer, settings=H.PROD_SETTINGS, clock=clock)
        engine_reply(engine, session_id='s', turn_id='q', text='Расскажи подробнее', request={}, model='offline')
        portion = engine.state('s')['chunks'][0]
        clock.advance(10)                              # the user needs time to repeat; an echo guard (if ever on) must not matter
        replies, errors = [], []
        start = threading.Barrier(4)

        def deliver():
            try:
                start.wait(10)
                replies.append(engine_reply(engine, session_id='s', turn_id='ack', text=portion, request={}, model='offline'))
            except BaseException as error:        # noqa: BLE001 - reported below
                errors.append(error)

        threads = [threading.Thread(target=deliver) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(60)
        tick('concurrent-duplicate')
        assert not errors, errors
        state = engine.state('s')
        assert state['chunk_index'] == 1, 'double advance'
        assert set(replies) == {state['chunks'][1]}, replies


@H.properties(10)
@given(copies=st.integers(1, 4), order=st.sampled_from(['done-only', 'created-done', 'interleaved']))
def test_a_retransmitted_final_advances_at_most_once(copies, order):
    """Consecutive portions have the same text here, so only de-duplication (not locality) can protect the cursor."""
    with tempfile.TemporaryDirectory() as directory:
        d = H.Dictation(Path(directory) / 'dup', H.SAME_PORTIONS_ANSWER)
        assert d.chunks[0] == d.chunks[1], 'precondition: a duplicate is observable only if the next portion reads the same'
        portion = d.current
        assert d.say(portion, tid='ack-1').after == 1
        for _ in range(copies):
            tick('retransmit')
            if order in ('created-done', 'interleaved'):
                d.deliver(H.created('ack-1', 'user', ''))
            out = d.deliver(H.done('ack-1', 'user', portion))
            if order == 'interleaved':
                d.deliver(H.created('ack-1', 'user', ''))
            assert out.after == 1 and out.speaks == [], f'retransmit moved the cursor: {out.before} -> {out.after}'
        again = d.say(portion, tid='ack-2')            # a genuinely new utterance with the same words is a new ACK
        assert again.after == 2, 'de-duplication must not swallow a new utterance'


def test_a_reconnect_never_double_advances_a_replayed_ack(tmp_path):
    a = H.Dictation(tmp_path / 'session', H.LONG_ANSWERS[4])
    first = a.current
    assert a.say(first, tid='ack-1').after == 1
    b = a.reconnect()                                   # new connection, same session database, new nonce, empty ledger
    for event in (H.created('ack-1', 'user', ''), H.done('ack-1', 'user', first)):
        out = b.deliver(event)                          # the phone re-sends what it sent before the drop
        assert out.after == 1 and out.actions == [], out.actions
    repeated = b.say('повтори')                         # an explicit repeat is honoured at the stored position
    tick('reconnect')
    assert repeated.after == 1 and repeated.speaks == [a.chunks[1]], repeated.actions
    assert b.deliver(H.done('ack-1', 'user', first)).after == 1
    assert b.say(b.current).after == 2                  # and a fresh correct repeat advances exactly once


def test_an_ack_at_the_streaming_frontier_is_consumed_once(tmp_path):
    """The answer is still streaming and the portion that waits is the last one that exists: a confirmation, its retransmit and a
    second spoken confirmation must together release exactly one next cue, when the text arrives."""
    pieces = re.findall(r'\s*\S+', H.LONG_ANSWERS[0])
    d = H.Dictation(tmp_path / 'stream', None)
    d.say('Расскажи подробнее', play=False)
    d.deliver(H.created('a1', 'assistant', pieces[0]))
    n, first = 0, None
    for n, piece in enumerate(pieces[1:], 1):
        out = d.deliver({'type': 'turn.delta', 'turn_id': 'a1', 'delta': piece, 'start_ms': n * 40, 'end_ms': n * 40 + 39})
        if out.speaks:
            first = out.speaks[0]
            d.play(out.actions)
            break
    assert first and d.index == 0 and len(d.chunks) == 1, 'precondition: the first cue is also the frontier'
    ack = d.say(first, tid='ack-1')
    assert ack.speaks == [] and ack.after == 0, 'the frontier cannot advance: there is no next portion yet'
    d.deliver(H.created('ack-1', 'user', ''))
    assert d.deliver(H.done('ack-1', 'user', first)).speaks == []            # the retransmit
    assert d.say(first, tid='ack-2').speaks == []                            # a second spoken confirmation
    cues = []
    for m, piece in enumerate(pieces[n + 1:], n + 1):
        cues += d.deliver({'type': 'turn.delta', 'turn_id': 'a1', 'delta': piece, 'start_ms': m * 40, 'end_ms': m * 40 + 39}).speaks
    tick('streaming-frontier')
    assert cues == [d.chunks[1]] and d.index == 1, (cues, d.index)


# DEF-ACK-19 (a retransmitted turn.created of a finished turn, or a bare input_audio_buffer.speech_started with no turn after it,
# silenced the dictation for good) was fixed by Wave 2 / Task B: HEARING_SECONDS, and a retransmission is no start of speech.
@pytest.mark.parametrize('disturbance', ['final-only', 'turn-start-and-final', 'stray-speech-started'])
def test_wire_a_retransmitted_or_stray_turn_event_neither_double_advances_nor_freezes_the_dictation(tmp_path, disturbance):
    async def run(directory, disturbed):
        wire = H.Wire(directory)
        try:
            await wire.begin(H.LONG_ANSWERS[4])
            first = wire.chunks[0]
            await wire.user(first, tid='ack-1')
            assert wire.index == 1, 'precondition: the first ACK advances'
            if disturbed and disturbance == 'stray-speech-started':
                await wire.socket.provider({'type': 'input_audio_buffer.speech_started'})      # noise: VAD fired, no transcript follows
                await wire.settle()
            elif disturbed:
                await wire.user(first, tid='ack-1', pair=(disturbance == 'turn-start-and-final'))   # the ACK is retransmitted
                assert wire.index == 1, 'double advance'
            before = wire.audio_frames
            await wire.elapse(10)                       # ten silent seconds: the unconfirmed portion must come back
            return wire.audio_frames - before
        finally:
            await wire.close()

    control = asyncio.run(run(tmp_path / 'control', False))
    assert control > 0, 'harness: the transport does not auto-repeat even without a disturbance'
    tick('wire-retransmit')
    assert asyncio.run(run(tmp_path / 'disturbed', True)) > 0, 'the dictation froze (no repeat after 10 s of silence)'


# ====================================================================================================================
# 7. The system's own TTS never confirms itself
# ====================================================================================================================

# DEF-ACK-20: the own voice heard back is a witness only (``own_voice_suspect``, tests/test_own_voice_guard.py); the engine's echo_guard below is its own switch.
def guarded(directory, answer, **kwargs):
    return H.Dictation(directory, answer, settings=dict(H.PROD_SETTINGS), **kwargs)


# ====================================================================================================================
# 8. Robustness, purity, split deliveries
# ====================================================================================================================

KINDS = frozenset({'ack', 'repeat', 'stop', 'question', 'replay', 'silent', 'greeting', 'correction', 'clarify_repair'})
# U+17000..U+18D08 is the Tangut block: see the explicit test below (DEF-ACK-22)
TRANSCRIPTS = st.text(alphabet=st.characters(exclude_categories=['Cs']).filter(lambda ch: not 0x17000 <= ord(ch) <= 0x18D08),
                      max_size=120)


@pytest.mark.parametrize('mode', HYP_MODES)
@H.properties(120)
@given(heard=TRANSCRIPTS, portion=st.one_of(TRANSCRIPTS, st.sampled_from(H.PORTIONS)),
       shape=st.sampled_from(['waiting', 'none', 'completed', 'pending']))
def test_the_classifier_never_raises_whatever_the_transcript_says(mode, heard, portion, shape):
    state = {'waiting': lambda: H.waiting(portion), 'none': lambda: None,
             'completed': lambda: dict(H.waiting(portion), completed=True),
             'pending': lambda: dict(H.waiting(portion), pending_turn='t')}[shape]()
    tick('never-raises-' + mode)
    assert H.analyze(heard, state, [], H.MODES[mode]).kind in KINDS


@pytest.mark.parametrize('heard,portion', [('\U00017000', 'Наклон земной оси'), ('Наклон', '\U00017000'),
                                           ('Наклон \U00018d00 оси', 'Наклон земной оси')],
                         ids=['tangut-heard', 'tangut-portion', 'tangut-inside'])
def test_a_rare_script_in_a_transcript_cannot_raise(heard, portion):
    tick('rare-script')
    assert H.verdict(heard, portion).kind in KINDS


@H.properties(100)
@given(heard=TRANSCRIPTS, portion=st.sampled_from(H.PORTIONS))
def test_a_decision_is_pure(heard, portion):
    state = H.waiting(portion)
    before = copy.deepcopy(state)
    tick('pure')
    assert H.analyze(heard, state, [], H.PROD_SETTINGS) == H.analyze(heard, state, [], H.PROD_SETTINGS)
    assert state == before, 'analyze must not touch the stored state'


# QUESTION-ACK-06 was decided by WAVE 2 / Task B (item 4, ACK-split): finals within ACK_JOIN_SECONDS are joined for the portion that
# waits (tests/test_split_repeat.py holds the rest of the contract); the strict marker is gone.
def test_a_full_repeat_delivered_as_two_consecutive_finals_is_one_repeat(tmp_path):
    d = H.Dictation(tmp_path / 'split', H.LONG_ANSWERS[0])
    words = d.current.split()
    d.say(' '.join(words[:1]), gap=1.5)
    d.say(' '.join(words[1:]), gap=0.8)
    tick('split-final')
    assert d.index == 1


# ====================================================================================================================
# The generators must really have generated
# ====================================================================================================================

MINIMUM_CASES = {'noise-ru_aligned': 100, 'noise-stem': 100, 'listed-fillers': 100, 'numbers-small': 100, 'double-say': 80,
                 'partial-ru_aligned': 80, 'partial-stem': 80, 'wrong-number-ru_aligned': 80, 'wrong-number-stem': 80,
                 'dropped-negation-ru_aligned': 80, 'added-negation-ru_aligned': 80, 'key-term-ru_aligned': 80,
                 'swapped-term-ru_aligned': 40, 'neighbour-ru_aligned': 80, 'dispatch-accept': 40, 'dispatch-reject': 70,
                 'repeat-request': 40, 'never-raises-ru_aligned': 100, 'never-raises-stem': 100, 'pure': 80,
                 'partial-not-question-ru_aligned': 200, 'verbatim-ru_aligned': 80, 'concurrent-duplicate': 6}   # verbatim: one per corpus portion (F1)


def test_zz_the_properties_generated_enough_cases():
    """Runs last in this module (definition order). An empty strategy or a filter that rejects everything would pass silently."""
    print('GENERATED CASES', dict(sorted(H.CASES.items())), 'TOTAL', sum(H.CASES.values()))
    for name, minimum in MINIMUM_CASES.items():
        if name in H.CASES:                             # a single test selected with -k leaves the others out
            assert H.CASES[name] >= minimum, (name, H.CASES[name], minimum)
