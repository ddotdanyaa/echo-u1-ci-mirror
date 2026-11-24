"""V1b / R2 (R31-R2, источник 12:01: одна подсказка 8 раз подряд, телефон не слышит владельца при звучащей подсказке): серверная часть, ряд одной подсказки без ответа.
Через настоящий ControlledMedia (rig_of, run из test_u17_half_duplex, профиль-кандидат). Маршрут телефона (наушник/тумблер) серверной проверкой не закрывается: нужен телефон.
Не прогонялось на ноутбуке."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from echo_sync import call_trace
from test_h3_tempo import call       # noqa: F401 - call is the fixture
from test_repeat_cases import ASK, P1, P2, P3, rig_of
from test_u17_half_duplex import run


@pytest.mark.parametrize('cap', [3, 6])
def test_a_half_duplex_line_says_the_same_portion_at_most_twice_more_whatever_the_profile_cap(call, monkeypatch, cap):
    monkeypatch.setattr(call_trace, 'DUPLEX_MIN_CUE_S', 0.4)      # реплика стенда 0,5 с звука; настоящая 2-4 с
    rig = rig_of(call, max_auto_repeats=cap)
    rig.asks('u1', ASK, 0, f'{P1} {P2} {P3}')
    run(rig, 90.0)
    assert rig.c.input_probe.duplex(rig.w.clock.t) == 'half', 'precondition: the meter saw a half-duplex line'
    said = rig.said()
    assert said.count(P1) - 1 <= 2, said


def test_with_the_default_profile_a_portion_nobody_answers_is_said_at_most_twice(call):
    rig = rig_of(call)
    rig.asks('u1', ASK, 0, f'{P1} {P2} {P3}')
    run(rig, 90.0, packets=False)
    assert rig.said().count(P1) <= 2, rig.said()


# strict: проверяется ровно одно — без единого пакета микрофона (packets=False) и с max_auto_repeats=4 одна порция не звучит больше чем 2 раза после первого; по коду красный (крышка полудуплекса не видит входа), если пройдёт — xpass упадёт и xfail снимают
@pytest.mark.xfail(strict=True, reason='R2: при потерянном входе (ни одного пакета микрофона) и поднятом max_auto_repeats крышка полудуплекса не действует (duplex не half, input_state=shadow не держит): ряд идёт вслепую до max_auto_repeats; ожидается красным по коду, облачный прогон подтвердит')
def test_a_dead_input_with_a_raised_cap_is_not_said_blindly_more_than_twice_more(call):
    rig = rig_of(call, max_auto_repeats=4)
    rig.asks('u1', ASK, 0, f'{P1} {P2} {P3}')
    run(rig, 90.0, packets=False)
    assert rig.said().count(P1) - 1 <= 2, rig.said()
