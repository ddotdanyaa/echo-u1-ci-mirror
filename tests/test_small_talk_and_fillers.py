"""The owner's call of 2 Nov 16:09 and the lookup case of the candidate run: small talk is no question, and a chat greeting or praise
before a comma is never dictated."""
import pytest

from echo_sync.classifier import GREETING, QUESTION, analyze
from echo_sync.textutil import strip_process_prefix

WAITING = {'schema': 2, 'revision': 1, 'question': 'Что такое инерция?', 'answer': 'Инерция это свойство тел.',
           'chunks': ['Инерция это', 'свойство тел.'], 'chunk_index': 0, 'completed': False, 'pending_turn': None, 'history': []}


@pytest.mark.parametrize('text', ['Привет, ну что скажешь', 'Привет', 'Алло, слышишь меня?', 'Как дела?', 'Здравствуйте! Как дела?',
                                  'Ну привет', 'Добрый вечер, ты тут?', 'Проверка связи'])
@pytest.mark.parametrize('state', [None, WAITING])
def test_small_talk_starts_nothing(text, state):
    assert analyze(text, state, [], None).kind == GREETING


@pytest.mark.parametrize('text', ['Привет, расскажи про сублимацию', 'Что такое сублимация?', 'Как дела у экономики Японии?',
                                  'Здравствуйте, сколько ног у паука?'])
def test_a_greeting_before_a_real_question_keeps_the_question(text):
    assert analyze(text, None, [], None).kind == QUESTION


@pytest.mark.parametrize('text,expected', [
    ('Хороший вопрос, ставка налога 20 процентов.', 'ставка налога 20 процентов.'),
    ('Отличный вопрос — да, это так.', 'да, это так.'),
    ('Хороший вопрос. Инерция это свойство тел.', 'Инерция это свойство тел.'),
    ('Привет! Сублимация это переход вещества.', 'Сублимация это переход вещества.'),
    ('Чем могу помочь? Сублимация это переход.', 'Сублимация это переход.'),
    ('Вопрос о налогах сложный, но ставка 20 процентов.', 'Вопрос о налогах сложный, но ставка 20 процентов.'),
    ('Привет и пока - так прощаются.', 'Привет и пока - так прощаются.'),
])
def test_chat_greetings_and_praise_are_not_dictated(text, expected):
    assert strip_process_prefix(text) == expected
