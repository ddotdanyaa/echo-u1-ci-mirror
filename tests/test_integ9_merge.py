"""integ9 (candidate 6): behaviour where the wave-F branches meet. Each test names the two intents it keeps together.

1. F2 (ruling 1: a question split by the provider keeps its head) x F3 (an amount / rate question is looked up): «Сколько процентов
   составляет» | «ставка НДС» is on the lookup route from its head on, and the tail still goes on with it - the lookup is asked again with
   the whole question, never with the head alone.
2. F1 (meaning portions: a neighbour portion of the same answer may open with a question word) x the question classifier: while a portion
   waits, an utterance every word of which (two content words at least) is the answer's own is a try at the answer, never a new question.
3. F3 (amounts are looked up) x T-B N20 (no subject lexicon in production): the verify class names entitlements, not «вычет».
"""
import pytest

import helpers_s6_ack as H
from echo_sync.textutil import norm_words


def words(text):
    return ' '.join(norm_words(text))


def test_a_split_amount_question_on_the_lookup_route_keeps_its_head_and_is_looked_up_whole(tmp_path):
    d = H.Dictation(tmp_path / 'split-lookup', None)
    head = d.say('Сколько процентов составляет', tid='q-head')
    assert 'lookup' in head.types, ('precondition: an amount question is looked up (F3)', head.types)
    out = d.say('ставка НДС', gap=0.5, tid='q-tail')
    asked = [a for a in out.actions if a['type'] == 'lookup']
    assert asked and 'ставка ндс' in words(asked[-1]['question']) and 'составляет' in words(asked[-1]['question']), out.actions
    assert words(d.controller.question_text) == 'сколько процентов составляет ставка ндс', d.controller.question_text


def test_a_tail_long_after_the_head_on_the_lookup_route_is_not_joined(tmp_path):
    """The window is the same as on the model-knowledge route: a topic phrase said well after the question is not its tail."""
    d = H.Dictation(tmp_path / 'late', None)
    d.say('Сколько процентов составляет', tid='q-head')
    d.say('ставка НДС', gap=6.0, tid='q-tail')
    assert words(d.controller.question_text) == 'сколько процентов составляет', d.controller.question_text


INERTIA = H.LONG_ANSWERS[2] if H.LONG_ANSWERS[2].startswith('Инерция') else next(a for a in H.LONG_ANSWERS if a.startswith('Инерция'))


def inertia(tmp_path):
    d = H.Dictation(tmp_path / 'inertia', INERTIA)
    assert d.current == 'Инерция — это свойство тела', ('precondition: the first meaning portion waits', d.chunks)
    neighbour = next(c for c in d.chunks if c.casefold().startswith('чем'))
    return d, neighbour


def test_a_neighbour_portion_of_the_same_answer_said_while_one_waits_is_a_try_not_a_new_question(tmp_path):
    """S6 property (dispatch_a_partial_or_wrong_repeat) under F1: «чем больше масса, у тела,» opens with a question word, but every word
    of it is the answer's own - the listener's try at the answer, never a new question that retires it."""
    d, neighbour = inertia(tmp_path)
    for heard in (neighbour, '. ' + neighbour.casefold(), neighbour.rstrip(',') + '?'):
        out = d.say(heard, gap=4.0)
        assert not out.destroyed and out.after == out.before == 0 and out.model_calls == 0, (heard, out.types)
        assert all(text == d.current for text in out.speaks), (heard, out.speaks)


@pytest.mark.parametrize('question', ['Что такое фотосинтез?', 'А почему?', 'Что такое инерция?', 'Почему масса влияет на инерцию?'])
def test_a_question_with_a_word_the_answer_does_not_have_is_still_a_question(tmp_path, question):
    """The class is narrow: an interrogative or any other word that is not the answer's own («что такое», «почему», «влияет») keeps a
    question a question while a portion waits."""
    d, _ = inertia(tmp_path)
    out = d.say(question, gap=4.0)
    assert out.destroyed and 'cancel' in out.types, (question, out.types)


# 3. F3 (amounts, rates and legal dates are looked up) x T-B N20 (no production module carries the test subjects' words): the verify class
#    names what is ENTITLED by law («положена», «полагается») instead of one tax word («вычет», a subject word of the tax pack).
@pytest.mark.parametrize('question', ['Какая сумма вычета положена на ребёнка?', 'Какой размер компенсации положен за неиспользованный отпуск?',
                                      'Сколько дней отпуска полагается работнику?'])
def test_an_entitlement_amount_question_needs_verification(question):
    from echo_sync.generator import route_need
    assert route_need(question, ())


@pytest.mark.parametrize('question', ['Какое положение занимает Земля в Солнечной системе?', 'Сколько сторон у квадрата?'])
def test_a_settled_question_with_a_look_alike_word_does_not(question):
    from echo_sync.generator import route_need
    assert not route_need(question, ())
