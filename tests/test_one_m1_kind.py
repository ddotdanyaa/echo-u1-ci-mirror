"""one-input M1 (kind: ``ControlledMedia._judge`` + ``utterance_judge``): U15 a prepared answer survives its matched question, U47 a discourse «что ж» asks nothing, U59 doubt does not break the waiting portion."""
import logging

import pytest

from test_h1_fast_text import rig      # noqa: F401 - rig is the fixture
from test_stable_partial_ack import PORTION, Speaker, dictation


def said_over_the_portion(tmp_path, caplog, text):
    """The portion waits (dictation); the speaker says ``text`` over it. Returns the judge lines, the dictation and the speaker."""
    caplog.set_level(logging.INFO)
    d = dictation(tmp_path / 'm1')
    s = Speaker(d).start().words(text)
    s.wait(0.8)
    caplog.clear()
    s.final()
    s.wait(1.0)
    return [r.getMessage() for r in caplog.records if r.getMessage().startswith('echo-sync judge ')], d, s


def held(d, s, caplog):
    """The same portion still waits and nothing was retired as a new question."""
    state = d.controller.state()
    return state['chunk_index'] == 1 and state['chunks'][1] == PORTION and 'new_question' not in caplog.text and not {'route', 'cancel'} & {a['type'] for a in s.actions}


@pytest.mark.parametrize('text', ['ну что ж, а сейчас наступает моя часть', 'Что ж, начнём.', 'ну что ж'])
def test_u47_a_discourse_what_zh_is_no_question_and_the_portion_stays(tmp_path, caplog, text):
    lines, d, s = said_over_the_portion(tmp_path, caplog, text)
    assert lines and all('kind=question' not in line for line in lines), lines
    assert held(d, s, caplog)


@pytest.mark.parametrize('text', ['что же делать', 'а что ж такое инерция', 'ну что ж, а что такое масса'])
def test_u47_a_what_zh_that_asks_still_asks(tmp_path, caplog, text):
    lines, d, s = said_over_the_portion(tmp_path, caplog, text)
    assert lines and 'kind=question' in lines[-1], lines


def test_u59_a_slide_command_is_no_question_and_does_not_reset_the_portion(tmp_path, caplog):
    lines, d, s = said_over_the_portion(tmp_path, caplog, 'слайд пять')
    assert lines and all('kind=question' not in line for line in lines), lines
    assert held(d, s, caplog)


def test_u59_a_fragment_does_not_drop_the_plan(tmp_path, caplog):
    lines, d, s = said_over_the_portion(tmp_path, caplog, 'а вот')
    assert held(d, s, caplog)


def test_u15_a_prepared_answer_is_not_thrown_away_when_the_question_matched(rig):
    """The ear's job has prepared the answer to the question; the cloud's final of the same question comes: the prepared answer is the one said, once."""
    rig.ask()
    rig.pump(0.3)
    rig.say(0, 'Инерция — это свойство тела сохранять своё состояние движения или покоя. Чем больше масса, тем сильнее инерция.')
    rig.fake.run(0).finish()
    rig.pump(3.0)
    assert len(rig.cues()) == 1 and 'свойство тела' in rig.cues()[0], rig.cues()


@pytest.mark.parametrize('text', ['смотри что получается', 'так вот что я хотел сказать', 'как говорится, что посеешь то и пожнёшь'])
def test_u59_a_remark_with_a_conjunction_what_is_no_question_over_the_waiting_portion(tmp_path, caplog, text):
    """«что» that joins a clause (relative, conjunction) is the only ask feature: doubt does not break the portion."""
    lines, d, s = said_over_the_portion(tmp_path, caplog, text)
    assert lines and all('kind=question' not in line for line in lines), lines
    assert held(d, s, caplog)


@pytest.mark.parametrize('text', ['что такое масса', 'скажи что такое масса', 'а что мы делаем дальше', 'объясни что происходит при кипении'])
def test_u59_a_real_question_with_what_still_breaks_the_portion(tmp_path, caplog, text):
    lines, d, s = said_over_the_portion(tmp_path, caplog, text)
    assert lines and 'kind=question' in lines[-1], lines


def test_u15_a_prepared_answer_survives_a_final_that_comes_after_it(rig):
    """The job prepared on the ear's words is done BEFORE the cloud's final of the same question: the final matches it and the prepared answer is said, once, not thrown away."""
    from test_h1_fast_text import INERTIA
    rig.hear(INERTIA.question)
    rig.pump(0.3)
    rig.say(0, 'Инерция — это свойство тела сохранять своё состояние движения или покоя. Чем больше масса, тем сильнее инерция.')
    rig.fake.run(0).finish()
    rig.pump(0.5)
    rig.ask()
    rig.pump(3.0)
    assert len(rig.cues()) == 1 and 'свойство тела' in rig.cues()[0], rig.cues()
