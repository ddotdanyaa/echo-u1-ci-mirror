"""I1b (U128 U83 U106): the scenes of the lectures (words of the owner's transcripts) through the real chain of the sound stand.

The transcripts are the owner's and stay out of the repository: here a transcript is made on the spot out of invented words, laid out as the real ones (``<folder>/part_NNN.txt``, no punctuation). The sound is
tones (``lecture_scenes.tone_bank``); the controller, the wire, the detector are the real ones (``stand.run_sound``). Nothing here is a measurement of time on a laptop or a phone.
"""
import json

import pytest

from tools.replay import lecture_scenes as LS
from tools.replay import real_sound as RS

FILLER = 'налог ставка доход расчёт период база сумма вычет льгота платёж'.split()


pytestmark = pytest.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)


def filler(n, shift=0):
    return [FILLER[(i + shift) % len(FILLER)] for i in range(n)]


def make_root(tmp_path):
    """Two folders of invented lecture words: questions, a run of «подождите», «то есть», and a long stretch without a marker."""
    head = filler(30) + ['давайте', 'ответим', 'на', 'вопросы', 'первый', 'вопрос', 'что', 'такое', 'налог'] + filler(20, 3)
    mid = filler(20) + ['подождите', 'подождите', 'подождите'] + filler(10, 5) + ['то', 'есть', 'ставка', 'и', 'база'] + filler(5)
    tail = filler(140, 2)
    for folder, parts in {'6_нояб_13_02': {9: mid + head + tail, 16: head + tail}, '10_нояб_13_16': {9: head + tail, 10: filler(200, 1)}}.items():
        (tmp_path / folder).mkdir()
        for part, words in parts.items():
            (tmp_path / folder / f'part_{part:03d}.txt').write_text(' '.join(words), encoding='utf-8')
    return tmp_path


ADDR = (('6_нояб_13_02', 16, 'question'), ('10_нояб_13_16', 9, 'question'), ('6_нояб_13_02', 9, 'stop'), ('10_нояб_13_16', 10, 'long'), ('7_нояб_14_38', 5, 'question'))


# ---- the sources -----------------------------------------------------------------------------------------------------------

def test_a_question_is_the_words_around_the_marker_and_a_stop_is_the_run_as_said(tmp_path):
    root = make_root(tmp_path)
    tokens = LS.read_part(root, '6_нояб_13_02', 9)
    stop = LS.scan(tokens, 'f', 9, 'stop')[0]
    assert stop.words == ('подождите',) * 3
    question = LS.scan(LS.read_part(root, '6_нояб_13_02', 16), 'f', 16, 'question', count=2)
    assert len(question) == 2 and 'вопросы' in question[0].words and len(question[0].words) == LS.QUESTION_LEN
    doubt = LS.scan(tokens, 'f', 9, 'doubt')[0]
    assert doubt.words[:2] == ('то', 'есть') and len(doubt.words) == 5


def test_a_long_speech_has_no_marker_and_a_part_that_is_not_there_is_named(tmp_path):
    root = make_root(tmp_path)
    sources, absent = LS.collect(root, ADDR)
    assert absent == [('7_нояб_14_38', 5)]
    longs = [s for s in sources if s.kind == 'long']
    assert len(longs) == 1 and len(longs[0].words) == LS.LONG_LEN and not (LS.MARKS & set(longs[0].words))
    assert {'question', 'stop', 'long', 'chatter'} <= {s.kind for s in sources}


def test_the_phrases_have_what_the_catalog_wants_and_say_what_they_made_up(tmp_path):
    sources, _ = LS.collect(make_root(tmp_path), ADDR)
    phrases, made_up = LS.phrases_of(sources)
    assert {'question', 'question2', 'answer', 'answer2', 'stop', 'chatter', 'fix', 'fixed_answer', 'doubt', 'long'} <= set(phrases)
    assert phrases['fix'] != phrases['question'] and phrases['question2'] != phrases['question']
    only = [s for s in sources if s.kind == 'question'][:1]
    phrases, made_up = LS.phrases_of(only)
    assert {'question2', 'stop', 'chatter', 'doubt'} <= set(made_up) and 'long' not in phrases
    with pytest.raises(ValueError):
        LS.phrases_of([])


# ---- the sound ---------------------------------------------------------------------------------------------------------------

def test_a_tone_is_the_same_every_time_and_the_bank_can_say_every_phrase(tmp_path):
    assert LS.word_tone('налог') == LS.word_tone('налог') and LS.word_tone('налог') != LS.word_tone('ставка')
    assert len(LS.word_tone('я')) >= int(0.15 * RS.RATE)
    sources, _ = LS.collect(make_root(tmp_path), ADDR)
    phrases, _ = LS.phrases_of(sources)
    bank = LS.tone_bank(LS.vocabulary_of(phrases))
    for key, text in phrases.items():
        if key not in ('answer', 'answer2', 'fixed_answer'):
            assert bank.missing(text) == [], key


# ---- the real chain ------------------------------------------------------------------------------------------------------------

@pytest.fixture(scope='module')
def phrases(tmp_path_factory):
    sources, _ = LS.collect(make_root(tmp_path_factory.mktemp('lectures')), ADDR)
    return LS.phrases_of(sources)[0]


def test_the_question_of_a_lecture_is_answered_under_every_shape_of_the_packets(phrases):
    rows = LS.run_scenes(phrases, seed=3, names=('barge_in', 'fix_the_number'))
    assert len(rows) == 2 * len(LS.SHAPES)
    for r in rows:
        assert r['crash'] is None and r['violations'] == [], (r['scene'], r['shape'], r['violations'])
        first = r['decisions'][0]
        assert first['ear_at'] is not None and first['first_cue'] and 'Ответ' in first['first_cue'], (r['scene'], r['shape'], first)


def test_a_lecture_without_a_question_is_not_answered(phrases):
    rows = LS.run_scenes(phrases, seed=4, shapes=('clean', 'stall'), names=('lecture_without_question',))
    assert rows and all(r['silent_ok'] and r['violations'] == [] and r['crash'] is None for r in rows), rows


def test_the_whole_catalog_runs_without_a_crash_on_the_words_of_a_lecture(phrases):
    rows = LS.run_scenes(phrases, seed=5, shapes=('clean',))
    assert {r['scene'] for r in rows} >= {'quick_questions', 'fix_the_number', 'change_of_topic', 'silence', 'lecture_without_question'}
    assert [r['scene'] for r in rows if r['crash']] == []
    assert LS.summary(rows)['runs'] == len(rows)


def test_the_report_names_places_and_counts_and_has_no_word_of_the_transcript(tmp_path, phrases):
    sources, absent = LS.collect(make_root(tmp_path), ADDR)
    rows = LS.run_scenes(phrases, seed=6, shapes=('clean',), names=('question_under_the_hand',))
    text = json.dumps(LS.report(rows, sources, [], absent), ensure_ascii=False)
    spoken = {w for s in sources for w in s.words} - {'то', 'есть', 'и', 'на', 'что'}
    assert spoken and not [w for w in spoken if w in text], [w for w in spoken if w in text][:5]
    assert 'part_009@' in text and json.loads(text)['summary']['runs'] == 1


def test_the_command_line_wants_a_root_and_a_place_for_the_report():
    assert LS.main([]) == 2
