"""P04 (harvest g5-when-cue, w9-rehearsal P2): more words of the stop family, by structure and not by phrase.

A stop is [lead]* CORE [adjunct]* with 1..3 cores. New cores: помолчи/помолчите, достаточно, довольно and the never-mind pair (неважно, проехали: the question the
listener drops); new lead: «тихо»; «не надо больше» / «больше не надо» is «хватит». Any other content word keeps the turn what it is (a remark, a question).
The test drives the real ``ControlledMedia`` (Wire): the answer waits, the listener says it, and the answer is paused (nothing is spoken)."""
import itertools

import pytest

from echo_sync.classifier import STOP, analyze
from echo_sync.cm_probes import UNKNOWN, probe
from echo_sync.settings import CALL_SETTINGS, resolve
from echo_sync.textutil import norm_words
from echo_sync.user_intents import is_stop
from helpers_w1f import Wire

NEW_CORES = ['помолчи', 'помолчите', 'достаточно', 'довольно', 'неважно', 'проехали']
LEADS = ['', 'ну', 'тихо', 'так', 'а', 'нет', 'ладно']
ADJUNCTS = ['', 'пожалуйста', 'уже', 'на секунду']
FILLERS = frozenset(resolve(CALL_SETTINGS)['fillers'])


@pytest.mark.parametrize('core,lead,adjunct', list(itertools.product(NEW_CORES, LEADS, ADJUNCTS)))
def test_the_new_cores_are_a_stop_in_every_frame(core, lead, adjunct):
    text = ' '.join(part for part in (lead, core, adjunct) if part)
    assert is_stop(norm_words(text), FILLERS), text


@pytest.mark.parametrize('text', ['тихо хватит', 'тихо, стоп', 'не надо больше', 'больше не надо', 'ну не надо больше пожалуйста', 'а, неважно, проехали', 'не важно'])
def test_the_listed_forms_are_a_stop(text):
    assert is_stop(norm_words(text), FILLERS), text


@pytest.mark.parametrize('text', [
    'достаточно ли налога?', 'довольно сложный вопрос', 'это неважно для налога, но ставка двадцать процентов', 'тихо', 'не надо', 'больше',
    'помолчи и скажи что такое налог', 'проехали на красный', 'мне достаточно этого', 'неважно какая ставка', 'довольно часто спрашивают про налог'])
def test_a_content_word_keeps_the_turn_a_remark_or_a_question(text):
    assert not is_stop(norm_words(text), FILLERS), text


def test_the_probe_names_the_kind_of_the_stop_and_decides_nothing():
    assert probe('stop_kind', 'проехали').value == 'never_mind'
    assert probe('stop_kind', 'ну неважно пожалуйста').value == 'never_mind'
    assert probe('stop_kind', 'хватит').value == 'stop'
    assert probe('stop_kind', 'подожди').value == 'hold'
    assert probe('stop_kind', 'это неважно для налога').value == UNKNOWN


Q, A = ' Что такое амортизация?', ' Амортизация это постепенный перенос стоимости имущества на расходы. Она считается ежемесячно.'


def wire_after(tmp_path, said):
    w = Wire(tmp_path)
    w.user('u1', Q, 0.0, 1.5)
    w.assistant('a1', A, 1.6, 2.4)
    w.user('s1', said, 4.0, 4.8)
    w.until(7.0)
    return w


@pytest.mark.parametrize('said', ['Помолчи', 'Достаточно', 'Довольно, пожалуйста', 'Тихо, хватит', 'Не надо больше', 'А, неважно, проехали'])
def test_the_call_pauses_on_the_new_stop_words(tmp_path, said):
    w = wire_after(tmp_path, said)
    assert analyze(said, w.state(), [], w.c.settings).kind == STOP
    state = w.state()
    assert state.get('paused') or state.get('completed'), (said, state)


@pytest.mark.parametrize('said', ['Довольно сложный вопрос', 'Достаточно ли налога', 'Это неважно для налога'])
def test_the_call_does_not_pause_on_a_remark_with_the_word(tmp_path, said):
    w = wire_after(tmp_path, said)
    assert analyze(said, w.state(), [], w.c.settings).kind != STOP
    assert not w.state().get('paused')
