"""U16-S7: the profile's ``number_ranges`` reaches ru_alignment.RANGES when a call opens (controlled_host.serve), and the call_open header prints it."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from echo_sync import ru_alignment      # noqa: E402
from echo_sync.settings import resolve      # noqa: E402

HOST = (Path(__file__).parents[1] / 'echo_sync' / 'controlled_host.py').read_text(encoding='utf-8')


def test_the_flag_is_off_by_default_and_unknown_values_are_off():
    assert resolve({})['number_ranges'] == 'off'
    assert resolve({'number_ranges': 'on'})['number_ranges'] == 'on'
    assert resolve({'number_ranges': 'yes'})['number_ranges'] == 'off'


def test_the_controller_gets_the_key_and_the_host_prints_the_flag():
    from echo_sync.settings import controller_settings
    assert controller_settings(resolve({'number_ranges': 'on'}))['number_ranges'] == 'on'
    assert "number_ranges=profile_settings.get('number_ranges')" in HOST


def test_ranges_follow_the_profile():
    try:
        for value, want in (('on', True), ('off', False)):
            ru_alignment.set_ranges(resolve({'number_ranges': value})['number_ranges'] == 'on')
            assert ru_alignment.RANGES is want
    finally:
        ru_alignment.set_ranges(False)
