"""V1b / E78: что делают ворота сегодня, когда собеседник не молчит (письменный ответ строки) и пределы удержаний. Решение «чей голос» остаётся за владельцем (ухо не различает говорящего,
near_voice по умолчанию выключен, shadow только числа); сцена с живым собеседником требует телефона. Здесь: таблица пределов и живой порядок «детектор не даёт конца речи» через ControlledMedia.
Не прогонялось на ноутбуке."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from echo_sync.cm_base import FIRST_HOLD_SECONDS
from echo_sync.controlled_media import HOLD_BOUNDS
from echo_sync.settings import resolve
from echo_sync.timer_policy import ONSET_HOLD_MAX_S
from test_h3_tempo import call       # noqa: F401 - call is the fixture
from test_h5_live import ACCOUNT, LIVE, MATERIALS, asked


def test_the_written_answer_first_cue_waits_for_speech_at_most_the_table_other_cues_one_second():
    assert HOLD_BOUNDS['first_cue'][0] == FIRST_HOLD_SECONDS <= 8.0
    assert HOLD_BOUNDS['cue_in_speech'][0] == ONSET_HOLD_MAX_S <= 1.0
    assert resolve({})['near_voice'] == 'off', 'the ear does not tell the speaker: whose voice is the owner\'s decision'


def test_somebody_who_never_pauses_still_gets_the_first_cue_within_the_bound(call):
    """Детектор речи не даёт конца (собеседник говорит без пауз): первая подсказка не молчит дольше предела таблицы."""
    rig = call(**LIVE)
    asked(rig, ACCOUNT)
    rig.onset()
    rig.job_says(0, MATERIALS)
    rig.job_ends(0)
    rig.pump(HOLD_BOUNDS['first_cue'][0] + 2.0)
    assert rig.said(), 'the first cue is said though the speech never ended'
