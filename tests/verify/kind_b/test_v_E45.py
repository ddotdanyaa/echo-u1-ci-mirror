"""V1b / E45: защита «речь ещё не оценена»: final чужой реплики её не снимает (R2), и не зависит от позиции курсора (R10). Исправление: 2eea847, предок 980c85a0.
Через настоящий ControlledMedia (стенд test_h3_tempo). Счёт реплик относительный (число после плана), без опоры на точный список: облачный прогон показывает перед планом «лишнюю» первую подсказку.
Не прогонялось на ноутбуке."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
import helpers_s6_state as S
from echo_sync.timer_policy import TEMPO_REPEAT_SECONDS
from test_h3_tempo import call       # noqa: F401 - call is the fixture
from test_h5_live import ACCOUNT, LIVE, MATERIALS, plan


@pytest.mark.parametrize('other', ['Ну да', 'Понятно', 'Хорошо, ага'])
def test_the_final_of_other_speech_does_not_lift_the_protection(call, other):
    rig = call(**LIVE)
    plan(rig, asked=ACCOUNT, answer=MATERIALS)
    count = len(rig.said())
    rig.pump(TEMPO_REPEAT_SECONDS - 1.0)
    uid = rig.onset()
    rig.w.feed(S.turn_done('u0x', 'user', other))
    rig.pump(TEMPO_REPEAT_SECONDS)
    assert len(rig.said()) == count, 'never into the speech nobody has judged'
    rig.offset()
    rig.pump(0.1)
    rig.worker.heard(uid, 'вот')
    assert rig.c is not None


@pytest.mark.parametrize('lead', [0.3, TEMPO_REPEAT_SECONDS - 1.0, TEMPO_REPEAT_SECONDS - 0.5])
def test_speech_begun_before_the_timer_holds_it_for_any_cursor(call, lead):
    rig = call(**LIVE)
    plan(rig, asked=ACCOUNT, answer=MATERIALS)
    count = len(rig.said())
    rig.pump(lead)
    rig.onset()
    rig.pump(TEMPO_REPEAT_SECONDS)
    assert len(rig.said()) == count
