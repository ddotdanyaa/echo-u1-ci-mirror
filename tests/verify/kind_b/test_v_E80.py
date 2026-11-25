"""V1b / E80: говорящий сам повторил вопрос, который плохо расслышал: повтор считается вопросом, не шагом ACK прошлой порции и не отбрасывается как чужая реплика.
Через настоящий ControlledMedia (rig_of из test_repeat_cases) и через решение ворот (gate_text.decide на фразе из набора). Не прогонялось на ноутбуке.
Подсказка «≤1–2 с после паузы» и замер долей реплик собеседника в этот тест не входят (нужен живой звонок)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
import helpers_s6_state as S
from echo_sync.gate_text import QUESTION, decide
from test_h3_tempo import TICK, call       # noqa: F401 - call is the fixture
from test_repeat_cases import ASK, P1, P2, P3, rig_of


def test_the_gate_reads_the_repeated_question_as_a_question():
    said = 'Сколько будет девятнадцать умножить на три?'
    assert decide(said, [{'text': said, 'kind': 'speech'}]).kind == QUESTION


def test_the_owner_repeats_the_question_while_an_answer_waits_it_is_no_step_and_no_stranger(call):
    rig = rig_of(call)
    rig.asks('u1', ASK, 0, f'{P1} {P2} {P3}')
    rig.pump(0.5)
    cues, runs = len(rig.said()), len(rig.fake.runs)
    rig.w.feed(S.turn_created('u2', 'user', ASK.split()[0]))
    rig.w.feed(S.turn_done('u2', 'user', ASK))
    rig.pump(TICK * 3)
    assert P2 not in rig.said(), 'the repeated question is no step of the answer in play'
    assert len(rig.fake.runs) > runs or len(rig.said()) > cues, 'the repeat is a question: asked or answered, not dropped'
