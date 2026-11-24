"""V1b / E72: длинная реплика с вопросом в конце получает job и ответ, а не «Нет ответа» (слово «я» в начале не делает её личной). Исправление: 1214bbb (h7 п.0a), предок 980c85a0.
Через настоящий ControlledMedia (стенд test_h3_tempo, профиль звонка 10:27). Не прогонялось на ноутбуке.
Реплей настоящего звонка (CALL_1027_REPLAY) на 980c85a0 в облачном прогоне падает до результата (TypeError 'NoneType' в test_h7 test_the_replay_of_the_call_of_1027, НОВЫЙ красный волны 4):
тест ниже станет осмысленным, когда это починят; он не заменяет остальные."""
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from test_h3_tempo import call       # noqa: F401 - call is the fixture
from test_h5_live import asked, decisions, spoken_failures
from test_h7 import CALL_1027, NO_89, SAID_INFLATION, SAID_KALKA, job_answers, replay_1027

REMARKS = [
    ('Я вот сейчас договорю, ну так, значит что такое факторинг', 'Факторинг — продажа долга финансовой компании.'),
    ('Я сегодня полдня думал, мне кажется, ладно, в чём разница между активами и пассивами', 'Активы принадлежат компании, пассивы — источники их появления.'),
    ('Я тут думал над этим весь вечер, значит налог на добавленную стоимость', 'НДС — налог на добавленную стоимость.'),
    (SAID_KALKA, 'Битва при Калке произошла в 1223 году.'),
    (SAID_INFLATION, 'Инфляция — это устойчивый рост общего уровня цен.'),
]


@pytest.mark.parametrize('said, answer', REMARKS, ids=['factoring', 'assets', 'topic_no_what_is', 'kalka', 'inflation'])
def test_a_long_remark_with_i_in_it_and_a_question_or_a_topic_at_the_end_is_answered(call, caplog, said, answer):
    caplog.set_level(logging.INFO, 'echo-sync')
    rig = call(**CALL_1027)
    asked(rig, said)
    rig.pump(0.4)
    if rig.fast.count:
        job_answers(rig, 0, answer)
        rig.pump(0.2)
    assert rig.said() and spoken_failures(rig) == [], rig.said()
    assert not decisions(caplog, 'personal_unanswerable') and not decisions(caplog, 'no_source_current_data')


def test_the_replay_of_the_real_call_the_remarks_at_151_and_253_are_answered_not_failed(call, monkeypatch):
    rig = call(fast_text='on', max_auto_repeats=3)
    zero = rig.w.clock.now() - 20.0
    cues = replay_1027(rig, monkeypatch)
    window_89, window_55 = (151.01, 164.49), (253.69, 279.29)
    assert any(text == NO_89 and window_89[0] < at < window_89[1] for at, text, _ in cues), 'the remark of 151.0 got its answer'
    assert any(window_55[0] < at < window_55[1] for at, _, _ in cues), 'the remark of 253.7 got an answer'
    failed = [round(cue.t - zero, 2) for cue in spoken_failures(rig)]
    assert not [at for at in failed if window_89[0] < at < window_89[1] or window_55[0] < at < window_55[1]], failed
