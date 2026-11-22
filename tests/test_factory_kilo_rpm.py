"""A multi-step Kilo run never goes to a channel whose rpm is below its steps: Kilo sends the steps back to back, the
provider answers 429 inside the run and Kilo sleeps there until the idle ceiling (live: three strong-model calls at
rpm 5, 180 s each, no step). The light engine (one request) keeps every channel."""
import json

from tests.test_factory_runtime import TWO_CHANNELS, Rig
from tools import agent_factory_runner as W


def _cfg(tmp_path, slow_rpm, fast_rpm):
    slow = dict(TWO_CHANNELS[0], id='slow', group='ps', model='google/slow', rpm=slow_rpm)
    fast = dict(TWO_CHANNELS[1], id='fast', group='pf', model='google/fast', rpm=fast_rpm)
    cfg = tmp_path / 'rpm.json'
    cfg.write_text(json.dumps(dict(channels=[slow, fast])))
    return cfg


def test_a_kilo_coder_skips_a_channel_whose_rpm_is_below_its_steps(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    monkeypatch.setattr(W, 'engine_for', lambda role, task: 'kilo' if role != 'review' else 'light')
    result = rig.once(channel_config=_cfg(tmp_path, 5, 30))
    coders = [name for coder, name in rig.models if coder]
    assert coders and 'google/slow' not in coders
    assert 'low_rpm_skipped' in result['events']


def test_when_every_channel_is_slow_the_kilo_coder_still_runs():
    order = [dict(id='a', rpm=5), dict(id='b', rpm=2)]
    events = []
    assert W._kilo_fits(order, W.PROVIDER_STEPS, events) == order and events == []


def test_a_channel_without_rpm_or_with_enough_rpm_stays():
    order = [dict(id='a'), dict(id='b', rpm=W.PROVIDER_STEPS), dict(id='c', rpm=W.PROVIDER_STEPS - 1)]
    events = []
    assert [c['id'] for c in W._kilo_fits(order, W.PROVIDER_STEPS, events)] == ['a', 'b']
    assert events == ['low_rpm_skipped']
