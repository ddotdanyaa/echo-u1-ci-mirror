"""REL12-P1: a comma BETWEEN DIGITS is a decimal point, not a seam of the question («курс 92,45 на 15.11.2024», «ставка 7,5 % до 12.03.2024»). The cut of the question (``_PART_CLAUSE``,
the clause split of ``_h7_part``) left a stump («45 на 15.11.2024»): the stump had no lookup route and the public question never reached the search (test_s5_privacy_shapes). Pure functions
of the classifier. Not run on the laptop."""
import pytest

from echo_sync import classifier

BASE = 'Проверь, пожалуйста, что такое гидравлический удар'


@pytest.mark.parametrize('tail', ['курс 92,45 на 15.11.2024', 'ставка 7,5 % до 12.03.2024'])
def test_a_decimal_comma_is_no_seam_of_the_question(tail):
    text = f'{BASE}, {tail}.'
    assert classifier.question_part(text) == text


def test_a_decimal_comma_inside_the_asked_part_keeps_the_part_whole():
    text = 'Какой курс доллара сегодня, 92,45 или 93,1?'
    assert classifier.question_part(text) == text


@pytest.mark.parametrize('text', ['Допустим 1,5 года, какой процент?', 'цена 1,5, какой налог', 'Налог на прибыль 20,5 процента, какой срок'])
def test_a_decimal_comma_in_the_condition_of_a_short_question_stays_in_the_condition(text):
    assert classifier._h7_part(text) == text
