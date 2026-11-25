"""c22-repeat: the owner's rule of repeats, read on one utterance (``repeat_rule.verdict``), the dictation command and the owner's tempo of writing. Pure."""
import pytest

from echo_sync.repeat_rule import DictationPace, dictation_command, verdict
from echo_sync.timer_policy import DICTATION_MAX_SECONDS, DICTATION_MIN_SECONDS

P = 'Свет попадает на хлорофилл в листьях.'
TAX = 'Статья 17 Налогового кодекса —'
NOT = 'Доход от продажи квартиры не облагается налогом.'


@pytest.mark.parametrize('heard', ['листьях', 'в листьях', 'хлорофилл в листьях', 'свет попадает на хлорофилл в листьях', 'ну в листьях', 'свет попадает в листьях'],
                         ids=['last', 'last_two', 'last_three', 'whole', 'filler_left', 'jumped_to_the_end'])
def test_the_last_word_said_moves_on(heard):
    assert verdict(heard, P) == 'next'


@pytest.mark.parametrize('heard', ['свет попадает на хлорофилл', 'свет попадает хлорофилл'], ids=['three_of_four', 'a_function_word_lost'])
def test_most_of_the_portion_moves_on(heard):
    assert verdict(heard, P) == 'next'


@pytest.mark.parametrize('heard,portion', [('ее измеряют индексом', 'Её измеряют индексом потребительских цен.'), ('заявление подают в', 'Заявление подают в налоговую инспекцию.')],
                         ids=['pronoun_first', 'preposition_last'])
def test_most_is_counted_in_words_as_people_count_them(heard, portion):
    """Three words of five: «большая часть», whatever share of them the pronoun or the preposition is."""
    assert verdict(heard, portion) == 'next'


@pytest.mark.parametrize('heard', ['свет', 'свет попадает', 'свет попадает на'], ids=['one', 'half', 'half_and_a_preposition'])
def test_a_stumble_is_no_move_on(heard):
    """Half or less, and not the last word: the controller helps from the word after the stop."""
    assert verdict(heard, P) is None


@pytest.mark.parametrize('heard,portion', [
    ('статья восемнадцать налогового кодекса', TAX),          # another number
    ('статья налогового кодекса', TAX),                       # the number left out inside what was said
    ('облагается налогом', NOT),                              # the «не» before it left out
    ('доход от продажи квартиры облагается налогом', NOT),
    ('а что такое хлорофилл в листьях', P),                   # a question that ends like it
    ('мы гуляли и сидели в листьях', P),                      # talk of its own that ends on its word
], ids=['other_number', 'number_left_out', 'ne_before', 'ne_inside', 'question', 'talk'])
def test_a_wrong_number_a_lost_ne_a_question_or_talk_never_moves_on(heard, portion):
    assert verdict(heard, portion) is None


def test_a_number_said_in_words_ends_the_portion():
    assert verdict('кодекса', TAX) == 'next'
    assert verdict('статья семнадцать налогового кодекса', TAX) == 'next'
    assert verdict('В каком году? в девятьсот восемьдесят восьмом', 'Крещение Руси было в 988 году.') is None


def test_a_sound_is_no_last_word():
    assert verdict('и', 'Монархия и республика и.') is None
    assert verdict('', P) is None


@pytest.mark.parametrize('said,want', [
    ('Диктуй медленно', 'on'), ('диктуй помедленнее', 'on'), ('Включи режим диктовки', 'on'), ('Я буду записывать', 'on'), ('диктуй, я пишу', 'on'),
    ('Хватит диктовать', 'off'), ('диктуй как обычно', 'off'), ('Выключи диктовку', 'off'), ('обычный режим', 'off'),
    ('помедленнее', None), ('Что такое диктатура?', None), ('Мы на уроке писали диктант и учитель диктовал медленно, а я не успевала', None),
])
def test_the_dictation_is_said(said, want):
    assert dictation_command(said) == want


def test_the_wait_of_dictation_is_the_owners_tempo_within_its_bounds():
    pace = DictationPace()
    first = pace.wait(P, base=2.0)
    assert DICTATION_MIN_SECONDS <= first <= DICTATION_MAX_SECONDS and first > 2.0, 'writing is longer than the silence timer of speech'
    pace.observe(P, 18.0)             # 3 s a word: a slow hand
    assert pace.wait(P) > first
    for _ in range(5):
        pace.observe(P, 3.0)          # 0.5 s a word
    assert DICTATION_MIN_SECONDS <= pace.wait(P) < first
    for _ in range(4):
        pace.observe(P, 10_000)       # a portion nobody went on from: bounded all the same
    assert pace.wait(P) == DICTATION_MAX_SECONDS, 'a wait is bounded: the portion comes again'
    assert DictationPace().wait('Да.', base=9.0) == 9.0, 'never shorter than the profile\'s own'
