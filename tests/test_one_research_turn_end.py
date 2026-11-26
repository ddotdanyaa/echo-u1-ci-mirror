"""one-research (EOT-RU): the three-way end of a Russian turn by its text (``classifier.turn_end``: open / closed / unsure) and the speaker's own pause
(``local_ear.PauseLearner``, the idea of livekit/agents DynamicEndpointing: an EMA of the pauses after which the speaker went on, clamped).
Borrowed ideas, not code: livekit/agents voice/endpointing.py:49-250, utils/exp_filter.py:38; RealtimeVoiceChat turndetect.py (pause by the ending)."""
import pytest

from echo_sync import classifier, local_ear, timer_policy
from echo_sync.classifier import CLOSED, OPEN, UNSURE, open_tail, turn_end
from echo_sync.local_ear import CLOSED_MAX_S, CLOSED_MIN_S, PauseLearner

from test_open_tail_pairs import CLOSED_GAPS, GAPS, PAIRS


@pytest.mark.parametrize('opened,closed', PAIRS)
def test_open_is_exactly_open_tail(opened, closed):
    assert turn_end(opened) == OPEN
    assert turn_end(closed) != OPEN


@pytest.mark.parametrize('text', GAPS + CLOSED_GAPS)
def test_a_listener_open_tail_is_never_closed(text):
    """The breath stopped where a listener waits: never «closed», whatever ``open_tail`` says of it (a false release costs a cut question)."""
    assert turn_end(text) != CLOSED


@pytest.mark.parametrize('text', [
    'что такое НДС?', 'Сколько стоит доставка?', 'это так, верно?', 'всё правильно?',
    'что такое амортизация', 'как рассчитать налог на прибыль', 'сколько дней отпуска положено', 'почему так дорого',
    'зависит ли инерция от массы', 'объясни что такое амортизация', 'расскажи про вычеты', 'в каком году приняли кодекс',
    'кто подписывает акт', 'сколько будет пять на пять', 'можно ли вернуть товар без чека',
    'what is the deadline?', 'how much does it cost',
])
def test_closed_questions(text):
    assert turn_end(text) == CLOSED, text


@pytest.mark.parametrize('text', [
    '', None, '   ', 'налог на прибыль', 'ну вот', 'я думаю', 'хорошо', 'да', 'а', 'э-э', 'что', 'как', 'объясни',
    'что такое', 'сколько', 'расскажи', 'почему', 'это нужно для отчёта', 'что такое НДС и', 'как рассчитать налог на',
    'что такое ну', 'что э-э', 'как это э-э',
])
def test_not_closed(text):
    assert turn_end(text) != CLOSED, text


def test_tag_question_da_is_closed():
    assert turn_end('это правда, да?') == CLOSED


def test_three_values_only():
    assert {turn_end(t) for t in ('налог на', 'что такое НДС?', 'налог на прибыль')} == {OPEN, CLOSED, UNSURE}
    assert turn_end('') == UNSURE and turn_end(None) == UNSURE


def test_open_tail_unchanged_by_the_probe():
    """``open_tail`` stays the one rule of the open half: ``turn_end`` reads it, never the other way round."""
    for opened, closed in PAIRS:
        assert open_tail(opened) and not open_tail(closed)
    assert 'turn_end' not in classifier.open_tail.__code__.co_names


# -- the speaker's own pause -------------------------------------------------------------------------------------------------------------------

def test_learner_starts_at_todays_wait():
    """Nothing learned: the wait of a closed question is the release of today (0.9 s), so a call with no pauses behaves as before."""
    p = PauseLearner()
    assert p.wait() == CLOSED_MAX_S == 0.9
    assert CLOSED_MIN_S == 0.5


def test_short_pauses_bring_the_wait_down_to_the_floor_never_below():
    p = PauseLearner()
    for _ in range(100):
        p.went_on(0.2)
    assert p.wait() == pytest.approx(CLOSED_MIN_S)
    waits = []
    p = PauseLearner()
    for _ in range(10):
        p.went_on(0.3)
        waits.append(p.wait())
    assert all(a >= b for a, b in zip(waits, waits[1:])) and CLOSED_MIN_S <= waits[-1] < CLOSED_MAX_S


def test_ema_step_and_margin():
    p = PauseLearner()
    p.went_on(0.3)
    assert p.wait() == pytest.approx(0.9 * 0.9 + 0.1 * (0.3 + local_ear.PAUSE_MARGIN_S))


def test_a_long_pause_brings_it_back_up_capped():
    p = PauseLearner()
    for _ in range(50):
        p.went_on(0.2)
    for _ in range(50):
        p.went_on(0.85)
    assert p.wait() == pytest.approx(CLOSED_MAX_S)


@pytest.mark.parametrize('bad', [0, -1, None, float('nan'), float('inf'), 5.0, 'x'])
def test_out_of_range_pauses_are_not_learned(bad):
    """livekit learns only ``0 < pause <= max_delay``: a pause longer than the cap is an end, not a pause inside a turn; garbage is ignored."""
    p = PauseLearner()
    p.went_on(bad)
    assert p.wait() == CLOSED_MAX_S and p.count == 0


def test_new_call_forgets():
    p = PauseLearner()
    for _ in range(20):
        p.went_on(0.2)
    p.reset()
    assert p.wait() == CLOSED_MAX_S and p.count == 0


def test_new_time_constants_are_registered():
    """timer_policy lock: a new constant of time is written there the day it is born."""
    for name in ('CLOSED_MIN_S', 'CLOSED_MAX_S', 'PAUSE_MARGIN_S'):
        assert 'local_ear.' + name in timer_policy.TIMERS
    assert not [k for k in timer_policy.unregistered() if k.startswith('local_ear.')]
