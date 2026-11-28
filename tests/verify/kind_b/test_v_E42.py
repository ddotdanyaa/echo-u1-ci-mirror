"""V1b / E42: команды только на целой речи, через настоящий ControlledMedia (стенд test_h3_tempo, профиль LIVE). Исправление: 27c11f6 (h6 п.5), предок 980c85a0.
Не прогонялось на ноутбуке. Дефект, который уже виден по облачному прогону 980c85a0 и сюда НЕ дублируется: test_h6 про метку job «[стоп]» в тишине (paused None), см. отчёт."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
import helpers_s6_state as S
from test_h3_tempo import TICK, call       # noqa: F401 - call is the fixture
from test_h5_live import ACCOUNT, LIVE, MATERIALS, plan

DEBIT = 'Что такое амортизация'
DEBIT_ANSWER = 'Амортизация считается линейным способом.'


@pytest.mark.parametrize('said', ['Погодите, а что такое амортизация', 'Секундочку, а какая ставка по вкладу в 2021 году', 'Стой, а что такое вексель'])
def test_a_hold_word_at_the_start_of_a_whole_question_stops_nothing_and_the_job_is_asked(call, said):
    rig = call(**LIVE)
    plan(rig, asked=ACCOUNT, answer=MATERIALS)
    rig.pump(1.0)
    runs = len(rig.fake.runs)
    rig.w.feed(S.turn_created('u1', 'user', said.split()[0]))
    rig.pump(0.5)
    rig.w.feed(S.turn_done('u1', 'user', said))
    rig.pump(TICK * 3)
    assert not rig.c.state().get('paused'), 'a question is no stop'
    assert len(rig.fake.runs) > runs, 'the job is asked'


@pytest.mark.parametrize('word', ['Стоп', 'Подождите'])
def test_the_command_word_of_a_cut_final_waits_for_the_ear_and_the_whole_speech_is_a_question(call, word):
    """Облако отдало final «Стоп» посреди речи, ухо слышит, что речь идёт дальше: ничего не остановлено; ухо принесло целую речь, это вопрос, на него ответ."""
    rig = call(**LIVE)
    plan(rig, asked=ACCOUNT, answer=MATERIALS)
    rig.pump(1.0)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    uid = rig.onset()
    rig.pump(1.0)
    rig.w.feed(S.turn_done('u1', 'user', word))
    rig.pump(1.0)
    assert not rig.c.state().get('paused'), 'the ear hears the speech go on'
    rig.offset()
    rig.pump(0.1)
    rig.worker.heard(uid, f'{word.lower()} а как считается амортизация')
    rig.pump(0.3)
    rig.w.feed(S.turn_created('u2', 'user', ''))
    rig.w.feed(S.turn_done('u2', 'user', 'а как считается амортизация'))
    rig.pump(TICK * 2)
    last = len(rig.fake.runs) - 1
    rig.job_says(last, DEBIT_ANSWER)
    rig.job_ends(last)
    rig.pump(2.0)
    assert 'линейным' in ' '.join(rig.said()) and not rig.c.state().get('paused')


@pytest.mark.parametrize('word', ['стоп', 'подождите'])
def test_a_whole_command_word_alone_stops(call, word):
    rig = call(**LIVE)
    plan(rig, asked=ACCOUNT, answer=MATERIALS)
    rig.pump(1.0)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.says(word, speech=0.6)
    rig.w.feed(S.turn_done('u1', 'user', word.capitalize()))
    rig.pump(1.5)
    assert rig.c.state().get('paused') is True

import pytest as _pt_no_lead
pytestmark = _pt_no_lead.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)
