"""WAVE 2 / Task C-seg: the streamed continuation after the first cue (DEF-SEG-17, DEF-SEG-14).

* DEF-SEG-17: ``stable_prefix`` plans the PARTIAL text and commits its first portion; with one portion behind it the syllable
  planner's first cut still moves as the text grows, so the stream left one-word portions the plan of the whole text avoids.
  Three portions behind it, the stream and the plan of the whole text agree.
* DEF-SEG-14: the text of a stream is already spoken text (ControlledMedia expanded the abbreviations once, for the whole
  answer): a fragment is not expanded a second time, and a term that stands in it is never cut.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import helpers_s6_seg as H                                                       # noqa: E402
from echo_sync.portioner import STREAM_LOOKAHEAD_PORTIONS, expand_abbreviations, portions, stable_prefix  # noqa: E402
from echo_sync.settings import CALL_SETTINGS                                     # noqa: E402

CONTROLLED = H.CONTROLLED_SETTINGS


def test_a_streamed_portion_needs_portions_behind_it_in_the_syllable_mode_only():
    assert STREAM_LOOKAHEAD_PORTIONS >= 3
    sentence = 'Зимой солнечные лучи падают на землю под меньшим углом. Поэтому поверхность получает меньше тепла. '
    # W1F-A (brief task-w1fix-briefs.md, «a cut PENALTY in the planner»): no portion ends on an adjective before its noun
    # («солнечные | лучи») where the bounds allow another cut - the plan was ['Зимой солнечные', 'лучи падают', ...].
    assert portions(sentence, CONTROLLED)[:2] == ['Зимой солнечные лучи', 'падают на землю']
    assert stable_prefix('Зимой солнечные лучи падают на землю под меньшим углом. ', CONTROLLED) == ''   # three portions: too few
    assert stable_prefix('Зимой солнечные лучи падают на землю под меньшим углом. Поэтому поверхность ', CONTROLLED) \
        == 'Зимой солнечные лучи'
    # the fixed-size mode keeps its one portion of lookahead
    assert stable_prefix('Первый второй третий четвёртый пятый шестой ', {'portion_mode': 'words', 'words_per_portion': 3}) \
        == 'Первый второй третий'


def test_the_streamed_continuation_is_the_plan_of_the_rest_for_the_whole_corpus():
    bad, checked = [], 0
    for item in [i for i in H.HAND_CORPUS if i.punctuated][::2]:
        run = H.stream(item.question, item.answer, 'words', walk=False)
        if not run.chunks:
            continue
        checked += 1
        rest = (run.answer_state or '')[len(run.chunks[0]):]
        # F1: the stream is planned on the profile the call runs on (ControlledMedia's default, CALL_SETTINGS)
        if run.chunks[1:] != portions(rest, CALL_SETTINGS):
            bad.append((item.id, run.chunks[1:4], portions(rest, CALL_SETTINGS)[:3]))
    assert checked >= 100 and not bad, bad[:4]


# --- DEF-SEG-14 ----------------------------------------------------------------------------------------------------------

TABLE = {'ВВП': 'валовой внутренний продукт', 'УК РФ': 'Уголовный кодекс Российской Федерации', 'ЦБ': 'Центральный банк'}


def test_spoken_text_is_not_expanded_again():
    text = 'Рост ВВП важен для страны. Поэтому ВВП считают каждый квартал.'
    config = {**CONTROLLED, 'abbreviations': TABLE}
    assert ' '.join(portions(text, config)).count('валовой внутренний продукт') == 1                 # the whole answer: once
    spoken = expand_abbreviations(text, TABLE)
    again = portions(spoken, config, spoken=True)
    assert H.lossless_problem(spoken, again) is None                                                   # not a character more
    assert ' '.join(again).count('валовой внутренний продукт') == 1 and 'ВВП считают' in ' '.join(again)


def test_a_term_that_already_stands_in_a_spoken_text_is_never_cut():
    config = {**CONTROLLED, 'abbreviations': TABLE}
    text = 'Рост валовой внутренний продукт говорит о расширении экономики, а Центральный банк следит за ценами.'
    for profile in H.SYLLABLE_PROFILES:
        for part_list in (portions(text, {**H.PROFILES[profile], 'abbreviations': TABLE}, spoken=True),):
            assert not H.cut_atoms(text, ['валовой внутренний продукт', 'Центральный банк'], part_list), (profile, part_list)
    assert config['abbreviations'] == TABLE


@pytest.mark.parametrize('text', [
    'Рост ВВП говорит о расширении экономики, а ЦБ следит за ценами.',
    'ВВП растёт быстро. Рост ВВП важен для страны. Поэтому ВВП считают каждый квартал.',
    'За кражу судят по УК РФ, а за мошенничество тоже по УК РФ.',
])
def test_a_streamed_answer_with_an_abbreviation_table_is_the_expanded_answer_whole_and_uncut(text):
    config = {**CONTROLLED, 'abbreviations': TABLE}
    spoken = expand_abbreviations(text, TABLE)
    for how in ('words', 'chars5'):
        run = H.stream('Расскажи про экономику?', text, how, settings=config, walk=False)
        assert run.cues and H.lossless_problem(spoken, run.chunks) is None, (how, run.chunks)
        assert not H.cut_atoms(spoken, list(TABLE.values()), run.chunks), (how, run.chunks)
