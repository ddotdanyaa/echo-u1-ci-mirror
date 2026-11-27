"""U34 / ROOT-1, the general pin: EVERY key of ``settings.DEFAULTS`` that a profile moves off its default is visible in the settings of a controller
built the way the host builds it (``ControlledMedia(settings=controller_settings(profile))``) - not only the 18 listed keys. A key the call keeps as
its own (CALL_SETTINGS) is the one exception."""
import pytest
from echo_sync.controlled_host import controller_settings
from echo_sync.controlled_media import ControlledMedia
from echo_sync.settings import CALL_SETTINGS, DEFAULTS, resolve

# Some keys only act under others (settings.resolve folds them back to off): the base that lets each one show.
ENABLERS = {'fast_text': 'on', 'local_ear': 'act', 'lang_turn': 'on', 'ear_release': 'on', 'prepare_wide': 'on', 'two_witnesses': 'on', 'ear_job': 'on', 'reserve_text': 'on', 'prompt_tempo': 'ear', 'conversation_ledger': 'disk'}
BASES = (ENABLERS, {k: v for k, v in ENABLERS.items() if k not in ('prepare_wide', 'ear_job')})      # prepare_wide folds adopt_missing_words to 0
WORDS = ('off', 'earned', 'ear', 'disk', 'memory', 'energy', 'answer', 'on', 'act', 'shadow', 'live', 'carry', 'fall', 'follow', 'question', 'syllables', 'meaning', 'trim', 'answers', 'words', 'drop', 'cut', 'stem', 'exact', 'auto', 'ws', 'zzq')


def moved(key):
    """(base, value): a value the profile can set for ``key`` that survives ``resolve`` (with that base) as something else than the default, or None."""
    d = DEFAULTS[key]
    pool = [not d] if isinstance(d, bool) else [d + 1, d * 2 + 1, d + .5, max(d - 1, 0), 100] if isinstance(d, (int, float)) else list(WORDS) if isinstance(d, str) or d is None else [['zzq'], ['zzq', 'yyw']] if isinstance(d, list) else [{'zq': 'yw'}]
    for base in BASES:
        for value in pool:
            if resolve({**base, key: value})[key] != d:
                return {**base, key: value}


KEYS = [key for key in DEFAULTS if key not in CALL_SETTINGS]


@pytest.mark.parametrize('key', KEYS)
def test_a_profile_key_moved_off_its_default_reaches_the_controller(tmp_path, key):
    raw = moved(key)
    assert raw is not None, f'{key!r} has no value that resolve keeps off its default'
    profile = resolve(raw)
    controller = ControlledMedia(tmp_path / 's.sqlite3', session_id='every-key', settings=controller_settings(profile))
    assert resolve(controller.settings)[key] == profile[key] != DEFAULTS[key]


def test_every_key_has_a_moved_value_or_is_the_calls_own():
    """Not one key may drop out of the pin above silently."""
    assert [key for key in KEYS if moved(key) is None] == []
