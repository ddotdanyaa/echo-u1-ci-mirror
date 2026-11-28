"""V1b / Н7: короткое «нет» сразу после подсказки снимает порцию и просит другой ответ. Исправление: 776bdc06 (c25 wave a), предок 980c85a0. Через стенд no_cloud.Scene над настоящим ControlledMedia
(сцена и помощники из tests/test_c25_a_live.py). Не прогонялось на ноутбуке. Исходный тест исправления в облачном прогоне 980c85a0 зелёный (его нет в списке красных)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from test_c25_a_live import OLD, Q1, _no, rec_jobs, scene


@pytest.mark.parametrize('text', ['Неверно.', 'Не так.', 'Нет, не так.', 'Неа.'])
def test_other_short_rejections_take_the_portion_off_and_ask_for_another_answer(text):
    said = []
    s, rec = scene(lambda s: (s.ask(1.0, Q1), _no(s, said, text)))
    assert said
    assert [c for c in rec.cues if c[0] > said[0].onset and c[1] == OLD] == []
    assert any('другой ответ' in j['heard'].lower() for j in rec_jobs(s) if j['at'] >= said[0].offset)


def test_a_no_that_says_the_opposite_is_no_rejection():
    said = []
    s, rec = scene(lambda s: (s.ask(1.0, Q1), _no(s, said, 'Нет, это так.')))
    assert said
    assert not any('другой ответ' in j['heard'].lower() for j in rec_jobs(s))
