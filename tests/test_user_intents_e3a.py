"""Task E3a (WAVE 2): the closed vocabularies behind rulings 1-5, one narrow question each, on ``norm_words`` output.

The expectations are hand-written literals. What the classifier does with them (order of the decision, strength, the question text) is in
tests/test_classifier_e3a.py.
"""
import pytest

from echo_sync.textutil import norm_words
from echo_sync.user_intents import indirect_request, is_rhetorical


def w(text):
    return norm_words(text)


# -- 1. indirect_request: the words after the frame, or None -----------------------------------------------------------------------

@pytest.mark.parametrize('text,rest', [
    ('Хочу узнать про налоги', ['про', 'налоги']),
    ('Я хочу узнать о массе', ['о', 'массе']),
    ('Хочу узнать, как работает насос', ['как', 'работает', 'насос']),
    ('Хотелось бы разобраться в налогах', ['в', 'налогах']),
    ('Хотелось бы услышать про сублимацию', ['про', 'сублимацию']),
    ('Интересно понять об инерции', ['об', 'инерции']),
    ('Было бы здорово узнать про сублимацию', ['про', 'сублимацию']),
    ('В двух словах про инерцию', ['про', 'инерцию']),
    ('Гидравлический удар для меня загадка', ['гидравлический', 'удар']),
    ('Не понимаю, чем масса отличается от веса', ['чем', 'масса', 'отличается', 'от', 'веса']),
    ('Я не понимаю почему так', ['почему', 'так']),
    ('Мне непонятно, как это работает', ['как', 'это', 'работает']),
])
def test_the_words_after_the_request_frame_are_returned(text, rest):
    assert indirect_request(w(text)) == rest


@pytest.mark.parametrize('text,rest', [
    # the speaker's own need to understand (coordinator ruling, INTEG7): мне|нам + нужно|надо|необходимо|хочется|хотелось бы + понять|узнать|
    # разобраться|выяснить|уточнить
    ('Мне нужно понять гидравлический удар', ['гидравлический', 'удар']),
    ('Мне нужно понять, что такое механика', ['что', 'такое', 'механика']),
    ('Нам надо выяснить, как работает насос', ['как', 'работает', 'насос']),
    ('Мне необходимо узнать про налоги', ['про', 'налоги']),
    ('Нам хочется разобраться в налогах', ['в', 'налогах']),
    ('Мне хотелось бы уточнить ставку налога', ['ставку', 'налога']),
])
def test_the_words_after_the_speakers_own_need_to_understand_are_returned(text, rest):
    assert indirect_request(w(text)) == rest


@pytest.mark.parametrize('text', ['Мне нужно понять', 'Нужно понять гидравлический удар', 'Мне нужно остановить платёж по счёту', 'Мне хочется пить',
                                  'Нам хотелось бы поехать на море', 'Тебе нужно понять это', 'Мне нужно', 'Нужно остановить платёж по счёту'])
def test_an_own_need_that_names_no_request_verb_or_nothing_after_it_is_no_frame(text):
    assert indirect_request(w(text)) is None


@pytest.mark.parametrize('text', ['Хочу узнать', 'Хотелось бы понять', 'В двух словах', 'Было бы здорово', 'Мне непонятно', 'Не понимаю',
                                  'Интересно узнать'])
def test_a_frame_with_nothing_after_it_is_no_request(text):
    assert indirect_request(w(text)) is None


@pytest.mark.parametrize('text', ['Хочу узнать у соседей', 'Хочу пить', 'Хотелось бы поехать на море', 'Интересно узнать у кого-нибудь',
                                  'Интересно, что дальше', 'Было бы здорово поехать на море', 'Не понимаю этого человека', 'Что такое налоги',
                                  'Для меня это загадка', 'Загадка', 'Для меня загадка'])
def test_words_outside_the_closed_frames_are_no_frame(text):
    assert indirect_request(w(text)) is None


# -- 2. is_rhetorical: a closed list of at most four words, fillers aside --------------------------------------------------------------

@pytest.mark.parametrize('text', ['Серьёзно?', 'Правда?', 'Неужели?', 'Вот как?', 'Да ладно?', 'Кто бы сомневался?', 'Ну и что с того?', 'И что?',
                                  'Как так?', 'Разве?', 'Ого?', 'Да?', 'Точно?', 'хм, ну, да ладно', 'О, правда?', 'А точно?', 'Ого, серьёзно?',
                                  'Серьёзно, правда, неужели?', 'Кто бы сомневался, ого'])
def test_the_closed_list_of_exclamations_alone_or_in_a_row_is_rhetorical(text):
    assert is_rhetorical(w(text))


@pytest.mark.parametrize('text', ['Что?', 'Как?', 'А?', 'Ну', 'Хм', 'не расслышал', 'Это правда?', 'Серьёзно ли это', 'Да, а почему?',
                                  'Серьёзно, правда, неужели, разве, ого?', 'Да, правда?', 'Что, правда?', 'Правда ли', 'Разве не так',
                                  'Ты шутишь?', 'Так что же?', 'Да ладно, это правда', 'Точно, сто градусов'])
def test_anything_outside_the_closed_list_is_not_rhetorical(text):
    """The hearing repairs «Что?» «Как?» «А?» are in no phrase; «Да» and «Точно» count only said alone (fillers aside)."""
    assert not is_rhetorical(w(text))
