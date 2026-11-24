"""F1-midword (scenario sc12_long_dialogue_topic_return, run 20261102-123343, steps 5-6).

Field shape (probe report + agent.log of call 6f1c7614cc87): the provider closes the assistant segment the instant the listener
starts to speak, wherever the model is - here inside «рассеиваются» («…фиолетовые волны рассеи», turn.done at 55219 ms, the
listener's speech start 55232 ms) - and opens the model's next segment right after the listener's turn with the text it held
meanwhile («ваются сильнее, но мы лучше видим именно голубой. Поэтому днём небо выглядит голубым.», first cue 14 ms after the
final). The listener's turn was a NEW question, so ControlledMedia.provider() gave that segment the new question as its owner and
_source() made it the start of the new answer: the first portion was «ваются сильнее,».

Same shape elsewhere in the run: sc07 step 3 «А почему?» -> «ет и не тормозит» («…не толка» | «ет и не тормозит извне.Потому
что…»); sc12 step 4 -> «. Небо кажется» («…тяжелее» | «. Небо кажется голубым…»); sc07 step 5 -> «, он будет лететь».
"""
import pytest

from test_first_cue_never_silent import created, delta, done
from test_task1_review_round2 import Session

OLD = ('Небо кажется голубым из-за рассеяния солнечного света молекулами воздуха. '
       'Короткие синие и фиолетовые волны рассеи')                                    # closed inside «рассеиваются»
REST = 'ваются сильнее, но мы лучше видим именно голубой. Поэтому днём небо выглядит голубым.'
HELD = 'ваются сильнее, но мы'                                                         # what the helper held during the question
QUESTION_AT, FINAL_AT = 1.01, 3.4


def field(tmp_path, order, rest=REST, held=HELD, old=OLD, **session):
    s = Session(tmp_path, **session)
    s.ask('Теперь про цвет неба', tid='u4')
    s.at(0.05, created('a4', 'assistant', old[:40]))
    s.at(0.5, delta('a4', old[40:], 1))
    s.at(1.0, done('a4', 'assistant', old))                       # the listener starts to speak: the segment is closed
    s.at(QUESTION_AT, created('u5', 'user', 'Почему'))
    if order == 'during_question':
        s.at(2.0, created('a5', 'assistant', held))               # the model goes on while the question is being asked
        s.at(FINAL_AT, done('u5', 'user', 'Почему небо днём голубое'))
    else:
        s.at(FINAL_AT, done('u5', 'user', 'Почему небо днём голубое'))
        s.at(FINAL_AT + 0.01, created('a5', 'assistant', held))   # field: right after the final, with the held text
    s.at(FINAL_AT + 0.2, delta('a5', rest[len(held):], 1))
    s.at(6.0, done('a5', 'assistant', rest))
    return s


@pytest.mark.parametrize('order', ['after_the_final', 'during_question'])
def test_the_rest_of_a_word_cut_by_a_new_question_never_starts_its_answer(tmp_path, order):
    s = field(tmp_path, order)
    s.until(12)
    answer = [text for at, text in s.cues if at >= FINAL_AT]
    assert not any(text.lstrip().startswith('ваются') for text in answer), f'cues {s.cues}'
    assert not str(s.state().get('answer') or '').startswith('ваются'), s.state().get('answer')


def test_what_the_model_says_after_the_interrupted_sentence_is_still_the_answer(tmp_path):
    s = field(tmp_path, 'after_the_final', ack_after=0.3, ack_skip=1)   # the listener repeats the new answer only
    s.until(40)
    heard = ' '.join(text for at, text in s.cues if at >= FINAL_AT)
    assert ' '.join(heard.split()) == 'Поэтому днём небо выглядит голубым.', f'cues {s.cues}'


def test_the_old_sentence_s_own_period_never_opens_the_next_answer(tmp_path):
    """sc12 step 4: «…поэтому железо при равном объёме тяжелее» | «. Небо кажется голубым…» -> first portion «. Небо кажется»."""
    s = Session(tmp_path)
    s.ask('Что такое плотность вещества', tid='u3')
    s.at(0.05, created('a3', 'assistant', 'Плотность — это масса'))
    s.at(0.6, done('a3', 'assistant', 'Плотность — это масса единицы объёма, поэтому железо при равном объёме тяжелее'))
    s.at(1.0, created('u4', 'user', 'Теперь'))
    s.at(2.0, done('u4', 'user', 'Теперь про цвет неба'))
    s.at(2.01, created('a4', 'assistant', '. Небо кажется голубым из-за рассеяния'))
    s.at(2.5, done('a4', 'assistant', '. Небо кажется голубым из-за рассеяния солнечного света молекулами воздуха.'))
    s.until(8)
    answer = [text for at, text in s.cues if at >= 2.0]
    assert answer and not any(text.lstrip()[:1] in '.,;:!?…' for text in answer), f'cues {s.cues}'


def test_sc07_shape_the_reply_after_the_old_tail_is_kept_and_the_half_word_dropped(tmp_path):
    """sc07 step 3: «…если ничего его не толка» | «ет и не тормозит извне.Потому что так устроена природа материи…» for «А почему?»."""
    s = Session(tmp_path, ack_after=0.3, ack_skip=1)
    s.ask('Что такое инерция', tid='u1')
    s.at(0.05, created('a1', 'assistant', 'Инерция — это свойство'))
    s.at(1.0, done('a1', 'assistant', 'Инерция — это свойство тела сохранять скорость, если ничего его не толка'))
    s.at(1.01, created('u2', 'user', 'А'))
    s.at(2.0, done('u2', 'user', 'А почему'))
    s.at(2.01, created('a2', 'assistant', 'ет и не тормозит'))
    s.at(2.5, done('a2', 'assistant', 'ет и не тормозит извне.Потому что так устроена природа материи — это один из базовых законов.'))
    s.until(40)
    answer = [text for at, text in s.cues if at >= 2.0]
    assert answer and not answer[0].startswith('ет'), f'cues {s.cues}'
    assert 'природа материи' in ' '.join(answer), f'cues {s.cues}'


def test_a_new_answer_that_begins_with_a_capital_while_the_question_is_asked_is_untouched(tmp_path):
    """Guard (the 1d17bb3 owner rule): a reply that starts during the new question and begins on its own is still its answer."""
    s = Session(tmp_path, ack_after=0.3)
    s.ask('Что такое инерция')
    s.at(1.0, created('a1', 'assistant', 'Инерция'), done('a1', 'assistant', 'Инерция — это свойство тела сохранять'))
    s.at(1.2, created('u2', 'user', 'Что'))
    s.at(1.3, created('a2', 'assistant', 'Масса'))
    s.at(1.5, done('u2', 'user', 'Что такое масса'))
    s.at(2.0, done('a2', 'assistant', 'Масса — это мера инертности тела.'))
    s.until(30)
    assert s.heard == 'мера инертности тела.'
