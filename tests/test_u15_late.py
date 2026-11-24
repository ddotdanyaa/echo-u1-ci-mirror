"""U15-S6: the late cloud correction: ``meaning_guard`` drives it, DIFFERS cancels, UNKNOWN keeps playing."""
from types import SimpleNamespace

from echo_sync import settings as cfg
from echo_sync.controlled_media import ControlledMedia


def _late(ear, cloud):
    stub = SimpleNamespace(settings={})
    return ControlledMedia._late_correction(stub, ear, cloud)


def test_the_switch_is_gone():
    assert 'judge_guard' not in cfg.resolve({'judge_guard': 'on'})


def test_on_a_changed_number_cancels():
    assert _late('по статье 17 налогового кодекса', 'по статье 18 налогового кодекса') is True


def test_on_a_dropped_not_keeps_playing():
    assert _late('это не разрешено законом', 'это разрешено законом') is False


def test_on_a_same_text_keeps_playing():
    assert _late('как открыть расчетный счет', 'ну как открыть расчетный счет') is False
