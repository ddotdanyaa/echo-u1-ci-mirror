"""CORE2 (family speech/kind, the speaker gates): the wait on somebody else's speech and the test «did the utterance repeat the prompt» are ONE rule (near_voice); own_voice no longer has a copy of either."""
import pathlib
import re

from echo_sync import near_voice, own_voice

PACKAGE = pathlib.Path(__file__).resolve().parents[1] / 'echo_sync'


def test_the_two_gates_share_one_hold_policy_and_one_alignment_rule():
    assert own_voice.OtherSpeech is near_voice.OtherSpeech
    assert own_voice.aligned is near_voice.aligned
    for name in ('OTHER_FIRST_HOLD_S', 'UNKNOWN_HOLD_S', 'OTHER_NEXT_HOLD_S', 'UNKNOWN_NEXT_HOLD_S', 'OTHER_RUN_CAP_S', 'ALIGNED_SHARE'):
        assert getattr(own_voice, name) == getattr(near_voice, name), name


def test_no_second_copy_of_the_rule_in_the_package():
    classes = [path.name for path in PACKAGE.glob('*.py') if re.search(r'^class OtherSpeech\b', path.read_text(encoding='utf-8'), re.M)]
    assert classes == ['near_voice.py'], classes
    inline = [path.name for path in PACKAGE.glob('*.py') if 'len(said & given) >= 0.6 * len(said)' in path.read_text(encoding='utf-8')]
    assert inline == [], inline
