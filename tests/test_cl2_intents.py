"""CL2: what the listener's short requests mean to the classifier.

* amendment C (DEF-T-20): «повтори последнее», «повторите последнюю часть», «повтори последний кусок/фразу» ask for the same portion
  again, like every other repeat form (REPEAT: locally, no cloud call). Break caught: the closed list of words a repeat request may
  contain does not know them, and the request is ignored (nothing is spoken).
"""
import pytest

import helpers_s6_ack as H
from echo_sync.classifier import QUESTION, REPEAT, analyze

PORTION = 'Инерция — это свойство'
LAST = ('повтори последнее', 'Повтори последнее.', 'повторите последнюю часть', 'Повторите последнюю часть, пожалуйста.',
        'повтори последний кусок', 'повтори последнюю фразу', 'повтори, пожалуйста, последнюю фразу', 'повторите последний кусок')


@pytest.mark.parametrize('settings', [H.PROD_SETTINGS, H.CLASSIC_STEM], ids=['controlled', 'classic'])
@pytest.mark.parametrize('text', LAST)
def test_a_request_to_repeat_the_last_part_is_a_repeat(text, settings):
    decision = analyze(text, H.waiting(PORTION), [], settings)
    assert decision.kind == REPEAT, (text, decision)


def test_the_same_words_with_content_are_not_a_repeat_request():
    """Only the request itself: «повтори последнюю фразу Пушкина» names something else to say."""
    decision = analyze('повтори последнюю фразу Пушкина', H.waiting(PORTION), [], H.PROD_SETTINGS)
    assert decision.kind != REPEAT


def test_through_the_controller_the_last_part_request_speaks_the_current_portion_without_the_cloud(tmp_path):
    d = H.Dictation(tmp_path / 'repeat-last', H.LONG_ANSWERS[0])
    d.say('Инерция это')                                    # a partial attempt: held, nothing advances
    current = d.current
    out = d.say('Повторите последнюю часть.')
    assert out.speaks == [current] and out.after == out.before
    assert out.model_calls == 0 and not out.destroyed
