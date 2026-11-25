"""V1b / E29: русская незавершённость и ограниченный hold без вечного veto, на 980c85a0 через настоящий ControlledMedia (стенд test_h3_tempo).
Не прогонялось на ноутбуке (запрет владельца); прогон в облаке. Первое решение: незавершённая речь ждёт EAR_TAIL_SILENCE_SECONDS, законченная короче, и ни одно ожидание не вечное."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
import helpers_s6_state as S
from echo_sync.controlled_media import EAR_RELEASE_SILENCE_SECONDS, EAR_TAIL_SILENCE_SECONDS, HOLD_BOUNDS
from test_h3_tempo import GRID, TICK, call       # noqa: F401 - call is the fixture
from test_h5_live import LIVE

# (оборванная, законченная): одно дыхание остановилось посередине и дошло до конца. Каждая пара проверена на open_tail/turn_end (импорт, без прогона набора).
PAIRS = [
    ('как рассчитать амортизацию по', 'как рассчитать амортизацию'), ('объясни разницу между', 'объясни разницу между доходом и прибылью'),
    ('мне нужно узнать про', 'мне нужно узнать про налог на имущество'), ('сколько будет двадцать плюс', 'сколько будет двадцать плюс пять'),
    ('какая ставка у', 'какая ставка у НДС'), ('расскажи про налог на доходы и', 'расскажи про налог на доходы'),
    ('что такое ставка рефинансирования и', 'что такое ставка рефинансирования'), ('в каком году был принят закон о', 'в каком году был принят закон о бухгалтерском учёте'),
    ('ну и', 'ну и что дальше'), ('скажи а', 'скажи а что такое НДС'),
]


@pytest.mark.parametrize('opened,closed', PAIRS)
def test_an_unfinished_breath_waits_the_tail_silence_and_a_finished_one_waits_less(call, opened, closed):
    rig = call()
    assert rig.c._release_wait(opened) == EAR_TAIL_SILENCE_SECONDS, opened
    assert rig.c._release_wait(closed) <= EAR_RELEASE_SILENCE_SECONDS < EAR_TAIL_SILENCE_SECONDS, closed


def test_the_hold_of_an_open_tail_is_in_the_table_of_bounds_and_below_eight_seconds():
    """«Ограниченный hold»: у удержания по открытому хвосту есть предел в таблице HOLD_BOUNDS, и он не вечный."""
    assert HOLD_BOUNDS['tail_before_cue'][0] == EAR_TAIL_SILENCE_SECONDS
    assert EAR_RELEASE_SILENCE_SECONDS < EAR_TAIL_SILENCE_SECONDS <= 8.0


@pytest.mark.parametrize('ear, final', [
    ('какая ставка налога на имущество организаций в размере двадцать', 'Какая ставка налога на имущество организаций, в размере двадцать'),
])
def test_an_open_tail_is_released_at_the_bound_and_not_earlier_the_answer_is_not_lost(call, ear, final):
    """Живой порядок событий (как у h5, другое слово): ухо слышит обрыв на числе без единицы, облако отдало final, job ответил; подсказка идёт не раньше хвоста и не позже его."""
    rig = call(**LIVE)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    ended = rig.says(ear, speech=2.0)
    rig.w.feed(S.turn_done('u1', 'user', final))
    rig.pump(1.6)
    rig.job_says(0, 'Ставка налога на имущество организаций не выше 2,2 процента.')
    rig.job_ends(0)
    assert rig.next_cue(ended + EAR_TAIL_SILENCE_SECONDS - 3 * GRID - rig.w.clock.t) is None, 'an open tail is held'
    cue = rig.next_cue(3.0)
    assert cue is not None and cue.t - ended == pytest.approx(EAR_TAIL_SILENCE_SECONDS, abs=GRID + TICK), 'a bounded hold, no veto'
