"""U16-S7: a written range of numbers is read as its two ends and a plural century in its own paradigm on every call: the owner's rule, no key (the profile's ``number_ranges`` is gone)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from echo_sync import ru_alignment, speech_text      # noqa: E402
from echo_sync.settings import DEFAULTS, resolve      # noqa: E402


def test_the_key_is_gone_and_a_profile_that_still_has_it_changes_nothing():
    assert 'number_ranges' not in DEFAULTS and 'number_ranges' not in resolve({'number_ranges': 'off'})


def test_the_two_readers_have_no_switch_and_a_call_does_not_touch_them():
    for module in (ru_alignment, speech_text):      # always on, one reading: no flag and no setter (modes/host-serve-wiring)
        assert not hasattr(module, 'RANGES') and not hasattr(module, 'set_ranges')
    from echo_sync import repeat_rule
    assert not hasattr(repeat_rule, 'CROSS_SCRIPT') and not hasattr(repeat_rule, 'set_cross_script')


def test_the_cache_key_of_a_cue_always_says_the_century_paradigm():
    from echo_sync.controlled_host import voice_key
    assert voice_key('sapi').endswith(':ranges') and voice_key('sapi', 'fall', True).endswith(':ranges')
