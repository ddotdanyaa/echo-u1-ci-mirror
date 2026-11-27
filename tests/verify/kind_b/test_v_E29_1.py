"""V1b / E29.1: пары «оборвано / закончено» для open_tail и мутанты. Приёмка строки: ≥20 случаев, ≥10 убитых мутаций. Числа считает сам тест (не слово «≥» в отчёте).
Новые 14 пар идут через настоящий ControlledMedia (``_release_wait``), старые 26 пар и 14 мутантов берутся из tests/test_open_tail_pairs.py. Не прогонялось на ноутбуке."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
import test_open_tail_pairs as P
from echo_sync.classifier import open_tail
from echo_sync.controlled_media import EAR_RELEASE_SILENCE_SECONDS, EAR_TAIL_SILENCE_SECONDS
from test_h3_tempo import call       # noqa: F401 - call is the fixture

NEW_PAIRS = [
    ('как рассчитать амортизацию по', 'как рассчитать амортизацию'), ('объясни разницу между', 'объясни разницу между доходом и прибылью'),
    ('мне нужно узнать про', 'мне нужно узнать про налог на имущество'), ('сколько будет двадцать плюс', 'сколько будет двадцать плюс пять'),
    ('какая ставка у', 'какая ставка у НДС'), ('расскажи про налог на доходы и', 'расскажи про налог на доходы'),
    ('что такое ставка рефинансирования и', 'что такое ставка рефинансирования'), ('в каком году был принят закон о', 'в каком году был принят закон о бухгалтерском учёте'),
    ('ну и', 'ну и что дальше'), ('скажи а', 'скажи а что такое НДС'), ('сто двадцать', 'сто двадцать рублей'), ('я думаю что', 'я думаю что это неверно'),
    ('или', 'или нет'), ('за', 'за год'),
]


def test_the_acceptance_counts_are_met():
    killed = set(P.MUTANTS) - P.EQUIVALENT
    assert len(P.PAIRS) + len(NEW_PAIRS) >= 20 and len(killed) >= 10, (len(P.PAIRS), len(NEW_PAIRS), len(killed))


@pytest.mark.parametrize('name', sorted(set(P.MUTANTS) - P.EQUIVALENT))
def test_every_mutant_of_open_tail_is_killed_by_the_pairs(name):
    assert P._noticed(P._mutant(*P.MUTANTS[name])), f'survived: {name}'


@pytest.mark.parametrize('opened,closed', NEW_PAIRS)
def test_new_pairs_through_the_controller(call, opened, closed):
    rig = call()
    assert open_tail(opened) and not open_tail(closed), (opened, closed)
    assert rig.c._release_wait(opened) == EAR_TAIL_SILENCE_SECONDS
    assert rig.c._release_wait(closed) <= EAR_RELEASE_SILENCE_SECONDS


@pytest.mark.parametrize('text', ['что будет если не платить налоги', 'это нужно чтобы платить меньше'])
def test_a_finished_clause_after_a_head_is_not_held(call, text):
    """E29.1: held 1,6 s extra before the fix (open_tail read «если/чтобы» with no question word after it as an open tail); a clause with no head of its own stays open."""
    rig = call()
    assert rig.c._release_wait('если он опоздает') == EAR_TAIL_SILENCE_SECONDS
    assert rig.c._release_wait(text) <= EAR_RELEASE_SILENCE_SECONDS
