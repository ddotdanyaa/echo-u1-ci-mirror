"""V1b / E12: точность ACK: число, отрицание, слова-числа, и подсказка, услышанная микрофоном. Через настоящий ControlledMedia (helpers_s6_ack.Dictation, как test_s6_ack_properties).
Не прогонялось на ноутбуке. Часть про эхо подсказки ВОСПРОИЗВОДИТСЯ на 980c85a0 по коду и по test_own_voice_guard (подозрительный final двигает курсор, это свидетель, а не отказ): карточка для K."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
import helpers_s6_ack as H
from test_own_voice_guard import echo_like

NUMBER = 'Срок уплаты через 10 дней после этого. Налог по ставке 20 % не уплачивается.'
NEGATION = 'Налог не уплачивается при доходе ниже порога. Срок уплаты через 10 дней после этого.'


def fresh(tmp_path, name, answer, marker):
    d = H.Dictation(tmp_path / name, answer)
    assert marker in d.current, d.chunks
    return d


@pytest.mark.parametrize('how', ['number', 'number_word', 'negation'])
def test_a_protected_difference_confirms_nothing(tmp_path, how):
    if how == 'negation':
        d = fresh(tmp_path, how, NEGATION, ' не ')
        heard = d.current.replace(' не ', ' ')
    else:
        d = fresh(tmp_path, how, NUMBER, '10 дней')
        heard = d.current.replace('10 дней', '12 дней' if how == 'number' else 'двенадцать дней')
    assert heard != d.current
    out = d.say(heard.rstrip('.').lower())
    assert out.after == out.before, how


@pytest.mark.parametrize('how', ['words', 'number_word'])
def test_the_right_repeat_moves_on_exactly_one_step(tmp_path, how):
    d = fresh(tmp_path, 'right-' + how, NUMBER, '10 дней')
    heard = d.current if how == 'words' else d.current.replace('10 дней', 'десять дней')
    out = d.say(heard.rstrip('.').lower())
    assert out.after == out.before + 1, how


def test_the_cue_heard_back_in_the_microphone_is_accepted_and_logged_as_suspect(tmp_path, caplog):
    """E12, ruling DEF-ACK-20 (timer_policy.py: «there is no drop»): a final that sounds like the cue itself is NOT dropped (a repeat begun before the auto-repeat was once dropped as own voice and the
    portion came back for ever); the cursor moves one step and the line ``reason=own_voice_suspect`` is the witness. A drop would be the owner's decision and a phone test."""
    import logging
    d, portion = echo_like(tmp_path, 'e12-echo')
    with caplog.at_level(logging.INFO, logger='echo-sync'):
        d.controller.provider(H.done('echo', 'user', portion))
    assert d.index == 1, 'the accepted repeat moves on exactly one step'
    assert 'reason=own_voice_suspect' in caplog.text
