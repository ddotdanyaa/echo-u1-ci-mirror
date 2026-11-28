"""V1b / E26.1: порог ACK по реальным ошибкам распознавания пользователя при сохранённых защищённых токенах. Механизма настройки под пользователя в коде нет (поиск по echo_sync/ пуст),
для замера нужны записи владельца: отдельно. Здесь только то, что уже держит один общий порог: типичные подмены разбираются без потери защищённых токенов (число, отрицание).
Через настоящий ControlledMedia (helpers_s6_ack.Dictation). Не прогонялось на ноутбуке."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
import helpers_s6_ack as H

NUMBER = 'Срок уплаты через 10 дней после этого. Налог по ставке 20 % не уплачивается.'
NEGATION = 'Налог не уплачивается при доходе ниже порога. Срок уплаты через 10 дней после этого.'
SLIPS = [(NUMBER, '10 дней', 'десять дней', True), (NUMBER, '10 дней', 'двенадцать дней', False), (NEGATION, ' не ', ' ', False), (NEGATION, ' не ', ' не ', True)]


@pytest.mark.parametrize('answer, old, new, accepted', SLIPS, ids=['digits_as_words', 'teen_for_ten', 'negation_lost', 'negation_kept'])
def test_typical_slips_keep_the_protected_tokens(tmp_path, answer, old, new, accepted):
    d = H.Dictation(tmp_path / 'slip', answer)
    assert old in d.current, d.chunks
    out = d.say(d.current.replace(old, new).rstrip('.').lower())
    assert (out.after == out.before + 1) is accepted, (d.chunks, new)
