"""W13 item 9 (3_#18, 4_#16): a question about the course of the event («какой у нас дальше вопрос по списку», «а какой следующий вопрос из
зала») is no question to answer: nothing is dictated, no search. A question about the subject stays one."""
import pytest

from echo_sync.classifier import QUESTION, analyze
from echo_sync.settings import CALL_SETTINGS


@pytest.mark.parametrize('text', ['Так, а какой у нас дальше, ну, вопрос по списку', 'Что-то долго думаешь, ну ладно. А какой у нас следующий, э-э, вопрос из зала',
                                  'А что у нас дальше по плану?', 'Какой там следующий слайд по списку'])
def test_a_question_about_the_course_of_the_event_is_none(text):
    d = analyze(text, {}, [], CALL_SETTINGS)
    assert d.kind != QUESTION and d.reason == 'process_question', d


@pytest.mark.parametrize('text', ['Какой следующий шаг при регистрации ООО?', 'Какой вопрос задают на собеседовании главному бухгалтеру чаще всего?',
                                  'Какой срок по списку уплаты налогов для ИП?'])
def test_a_question_about_the_subject_stays_one(text):
    assert analyze(text, {}, [], CALL_SETTINGS).kind == QUESTION


@pytest.mark.parametrize('text', ['Какой вопрос?', 'Какой у нас следующий вопрос?', 'Жду следующий вопрос.'])
def test_without_a_list_it_is_the_jobs_to_decline(text):
    """H2: a bare «какой следующий вопрос» goes to the job, which declines it (BRAIN: «о том, какой вопрос следующий»): tests/test_h2_brain.py."""
    assert analyze(text, {}, [], CALL_SETTINGS).reason != 'process_question'


@pytest.mark.parametrize('text', ['Да откуда я знаю, у Светы спроси, она недавно людей оформляла', 'А почём я знаю'])
def test_a_reply_between_others_is_no_question(text):
    assert analyze(text, {}, [], CALL_SETTINGS).kind != QUESTION


def test_a_question_that_begins_so_stays_one():
    assert analyze('Откуда я знаю, когда сдавать декларацию по НДС?', {}, [], CALL_SETTINGS).kind == QUESTION
