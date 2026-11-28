"""one/timers: ``timer_guard`` is a rule of the timer owner, not a switch: always on, no key, no shadow path."""
import logging

from echo_sync import settings as st


def _controller(tmp_path, **settings):
    from echo_sync.controlled_media import ControlledMedia
    return ControlledMedia(tmp_path / 's.db', session_id='s', settings={'words_per_portion': 3, **settings})


def test_the_switches_are_gone():
    for key in ("timer_guard",):
        assert key not in st.DEFAULTS and key not in st.resolve({key: 'off'})


def test_a_stale_slot_is_cleared_by_default(tmp_path, caplog):
    c = _controller(tmp_path)
    c.repeat_at = 12.0
    with caplog.at_level(logging.INFO):
        c._new_epoch('t')
    assert c.repeat_at is None
    assert len([r for r in caplog.records if 'timer_stale' in r.getMessage()]) == 1


def test_a_stale_slot_is_cleared_even_if_a_profile_still_says_off(tmp_path):
    c = _controller(tmp_path, timer_guard='off')
    c.repeat_at = 5.0
    c._new_epoch('t')
    assert c.repeat_at is None


def test_loop_guard_is_gone_and_the_tick_is_woken_by_events():
    import inspect
    from echo_sync import controlled_host
    assert "loop_guard" not in st.DEFAULTS and "loop_guard" not in st.resolve({"loop_guard": "on"})
    src = inspect.getsource(controlled_host)
    assert "profile_settings['loop_guard']" not in src and "await asyncio.sleep(.1)" not in src
