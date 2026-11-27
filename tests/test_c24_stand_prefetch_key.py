"""c24-b: the stand turned the early lookup on only by the key ``prefetch``; the laptop's key is ``controlled_prefetch_enabled`` and the c23 speed set was measured
with that one, so its «prefetch» was never on. Either key turns it on now."""
from tools.replay import stand as A


def early(profile):
    st = A.Stand(0, profile={'local_ear': 'act', 'prompt_tempo': 'ear', 'fast_text': 'on', **profile})
    try:
        return st.w.wire.early.enabled
    finally:
        st.close()


def test_the_laptop_key_turns_the_early_lookup_on():
    assert early({'controlled_prefetch_enabled': 'on'}) is True


def test_the_stand_key_still_does_and_off_is_off():
    assert early({'prefetch': 'on'}) is True and early({}) is False
