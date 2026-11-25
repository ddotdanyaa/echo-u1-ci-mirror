"""W1F-B, class C6 (W1 group G4 TR-STALE-HEAD, sc12 step 4): the tail of an answer cut BETWEEN two words never opens the next answer.

F1 (tests/test_f1_segment_head.py) skips the rest of the old sentence when the new answer's first segment goes on with it in the middle of a
word or with a mark. The transport also cuts between words: «…пенопласта могут иметь» | « одинаковую массу, но разную плотность.Небо
кажется голубым…», and deployed (66b29f1) «одинаковую» was the first cue of the answer about the colour of the sky.

The rule now: a first segment that opens with a space and a lower-case word after a segment of ANOTHER question that stopped without a
sentence end is weighed up to its first sentence end. It is the old tail when it shares no content word with the new question and either
the new question is a change of topic or the head shares a content word with the previous answer; an elliptical follow-up («А почему?»)
names nothing of its own, so «␣потому что…» stays its answer.
"""
from helpers_w1f import Wire

DENSITY_Q = 'Что такое плотность вещества?'
WHY_CUT = ' потому что масса не учитывает размер: маленький кусочек свинца и большой кусок пенопласта могут иметь'


def density_then(tmp_path, question, answer, first=' Это масса, приходящаяся на единицу объёма.', why=WHY_CUT):
    """sc12 steps 1-4: the density answer, «Это масса» confirmed, «А почему» answered by a segment cut between two words, then
    ``question`` and the cloud's next segment ``answer``."""
    w = Wire(tmp_path)
    w.user('u1', DENSITY_Q, 0.0, 1.0)
    w.assistant('a1', first, 1.05, 2.0)
    w.user('u2', ' Это масса', 3.5, 4.0)
    w.user('u3', ' А почему', 6.45, 7.5)
    w.assistant('a3', why, 7.55, 12.4)
    if question:
        w.user('u4', question, 12.45, 14.3)
        w.assistant('a4', answer, 14.31, 18.0)
    return w.until(24.0)


def test_sc12_the_tail_of_an_answer_cut_between_words_never_opens_the_next_answer(tmp_path):
    w = density_then(tmp_path, ' Теперь про цвет неба',
                     ' одинаковую массу, но разную плотность.Небо кажется голубым, потому что воздух рассеивает синий свет сильнее.')
    after = w.played_after(14.3)
    assert after and after[0].startswith('Небо'), w.played                     # deployed: «одинаковую»
    assert 'одинаков' not in w.plan(), w.plan()


def test_a_follow_up_that_names_nothing_keeps_its_lower_case_answer(tmp_path):
    """Guard: «А почему» got «␣потому что масса не учитывает…» as its answer in the same run; an elliptical follow-up names no content
    word of its own, so a lower-case first segment after a segment cut between words is its answer."""
    w = density_then(tmp_path, None, None, first=' Это масса, приходящаяся на единицу', why=' потому что масса не учитывает размер тела.')
    assert any('масса' in text or 'учитыва' in text for text in w.played_after(7.5)), w.played
    assert 'учитывает' in w.plan(), w.plan()


def test_a_lower_case_answer_about_the_new_question_is_kept(tmp_path):
    """Guard: a head with the new question's own words is the new answer, even after a segment cut between words."""
    w = density_then(tmp_path, ' А что такое объём', ' объём — это место, которое занимает тело.')
    assert any('место' in text for text in w.played_after(14.3)), w.played     # the definition's body (its head «объём — это» elided)
