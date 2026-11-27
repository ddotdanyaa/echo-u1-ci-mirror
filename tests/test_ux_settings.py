"""UX-trace, part 2: the silence auto-repeat and the call trace are PROFILE settings (materials/echo_settings.json).

The owner's call of 2 Nov 21:46: the prompter repeated a portion every 3 s, up to 3 times, «как запоздалый диктофон с таймером».
The calm defaults are 6 s and ONE repeat; both are validated like every other key (a bad value never stops a call: the default is used).
"""
import json
import logging
import math

import pytest

from echo_sync import settings as cfg


def test_the_defaults_are_the_calm_ones():
    """Break: the owner's complaint comes back (3 s / 3 repeats) or the trace is off by default (nothing to diagnose with)."""
    d = cfg.resolve(None)
    assert d['repeat_seconds'] == 6 and d['max_auto_repeats'] == 1 and d['call_trace'] == 'on'


def test_the_keys_are_part_of_the_declared_defaults():
    """Break: a key missing from DEFAULTS is dropped by resolve() and reported as unknown."""
    for key in ('repeat_seconds', 'max_auto_repeats', 'call_trace'):
        assert key in cfg.DEFAULTS


@pytest.mark.parametrize('value', [1, 1.5, 4, 6, 12.5, 60])
def test_a_valid_repeat_seconds_is_taken(value):
    assert cfg.resolve({'repeat_seconds': value})['repeat_seconds'] == value


@pytest.mark.parametrize('value', [0, 0.99, -1, 60.5, 3600, '6', None, True, [], {}, math.nan, math.inf])
def test_an_invalid_repeat_seconds_falls_back_to_the_default(value):
    """1 s is the floor the controller itself applies; a minute of silence is already far past any sensible wait."""
    assert cfg.resolve({'repeat_seconds': value})['repeat_seconds'] == 6


@pytest.mark.parametrize('value,expected', [(0, 0), (1, 1), (2, 2), (5, 5), (10, 10), (3.0, 3)])
def test_a_valid_max_auto_repeats_is_taken(value, expected):
    assert cfg.resolve({'max_auto_repeats': value})['max_auto_repeats'] == expected


@pytest.mark.parametrize('value', [-1, 11, 1.5, '1', None, True, [], math.nan])
def test_an_invalid_max_auto_repeats_falls_back_to_the_default(value):
    assert cfg.resolve({'max_auto_repeats': value})['max_auto_repeats'] == 1


@pytest.mark.parametrize('value', ['on', 'off'])
def test_call_trace_takes_on_and_off(value):
    assert cfg.resolve({'call_trace': value})['call_trace'] == value


@pytest.mark.parametrize('value', ['ON', 'yes', 'true', True, False, 1, 0, None, ''])
def test_any_other_call_trace_value_means_the_default(value):
    """A trace that quietly switches itself off because of a typo would be found missing exactly when it is needed."""
    assert cfg.resolve({'call_trace': value})['call_trace'] == 'on'


def test_the_values_come_from_the_settings_file(tmp_path):
    path = tmp_path / 'echo_settings.json'
    path.write_text(json.dumps({'repeat_seconds': 4, 'max_auto_repeats': 0, 'call_trace': 'off'}), encoding='utf-8')
    loaded = cfg.load(path)
    assert (loaded['repeat_seconds'], loaded['max_auto_repeats'], loaded['call_trace']) == (4, 0, 'off')


def test_a_profile_preset_does_not_move_them():
    d = cfg.resolve({'preset': 'slow'})
    assert (d['repeat_seconds'], d['max_auto_repeats'], d['call_trace']) == (6, 1, 'on')


def test_an_invalid_value_is_reported_once_like_every_other_key(monkeypatch, caplog):
    monkeypatch.setattr(cfg, '_warned', set())
    with caplog.at_level(logging.WARNING, logger='echo-sync'):
        cfg.resolve({'repeat_seconds': 0, 'max_auto_repeats': 99, 'call_trace': 'sometimes'})
    text = caplog.text
    assert "invalid value for 'repeat_seconds'" in text
    assert "invalid value for 'max_auto_repeats'" in text
    assert "invalid value for 'call_trace'" in text
    assert 'unknown key' not in text


def test_resolve_stays_idempotent_with_the_new_keys():
    once = cfg.resolve({'repeat_seconds': 9, 'max_auto_repeats': 2, 'call_trace': 'off'})
    assert cfg.resolve(once) == once
