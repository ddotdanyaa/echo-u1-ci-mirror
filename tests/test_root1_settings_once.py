"""ROOT-1 (09.11 code review): a call's controller is BUILT with the profile's settings. Before, it was built with the defaults and
18 listed flags were copied in afterwards, so the flags the controller reads in ``__init__`` could never be switched on by a profile."""
from echo_sync.controlled_media import ControlledMedia
from echo_sync.settings import CALL_SETTINGS, controller_settings, resolve

INIT_FLAGS = {'local_ear': 'act'}


def test_init_time_flags_of_the_profile_reach_the_controller(tmp_path):
    c = ControlledMedia(tmp_path / 's.sqlite3', session_id='root1', settings=controller_settings(resolve(INIT_FLAGS)))
    assert c.flow is not None, 'the acting ear is read in __init__ (the pace of FlowAhead)'


def test_a_default_profile_adds_nothing_but_the_call_settings():
    got = controller_settings(resolve(None))
    assert set(got) == set(CALL_SETTINGS)
    assert {k: got[k] for k in CALL_SETTINGS} == CALL_SETTINGS


def test_call_settings_keys_stay_the_calls():
    assert controller_settings(resolve({'preset': 'slow_assistive'}))['preset'] == CALL_SETTINGS['preset']


def test_the_host_profile_of_a_default_profile_is_in_effect_the_call_settings_the_harnesses_use():
    """ROOT-1: the harnesses build ControlledMedia with CALL_SETTINGS; the host with controller_settings(defaults). Every resolved value is the same."""
    assert resolve(controller_settings(resolve(None))) == resolve(dict(CALL_SETTINGS))
