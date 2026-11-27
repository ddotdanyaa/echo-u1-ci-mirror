"""U16-S8: the TTS century paradigm and range reading, only behind number_ranges (speech_text.set_ranges); off = the voice as before."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
from echo_sync import speech_text as S      # noqa: E402

HOST = (Path(__file__).parents[1] / 'echo_sync' / 'controlled_host.py').read_text(encoding='utf-8')
CASES = ('в XV веках', 'в XIII–XV веках', 'в 13–15 веках', 'XV веков', 'в XV веке', 'в XX веке', 'Глава IV')


def spoken(text, on):
    S.set_ranges(on)
    try:
        return S.speak(text)
    finally:
        S.set_ranges(False)


def test_on_no_latin_letters_in_a_plural_century():
    for t in CASES:
        out = spoken(t, True)
        assert not re.search('[A-Za-z]', out) and 'икс' not in out and 'вэ' not in out, (t, out)
    assert 'пятнадцат' in spoken('в XV веках', True)
    assert spoken('в XV веках', True).endswith('веках')


def test_on_a_range_of_centuries_reads_both_ends_in_the_plural_paradigm():
    a, b = spoken('в XIII–XV веках', True), spoken('в 13–15 веках', True)
    for out in (a, b):
        assert 'тринадцат' in out and 'пятнадцат' in out and out.endswith('веках'), out
    assert a == b


def test_off_is_as_before():
    S.set_ranges(False)
    base = {t: S.speak(t) for t in CASES}
    assert 'икс' in base['в XV веках']
    S.set_ranges(True)
    S.set_ranges(False)
    assert {t: S.speak(t) for t in CASES} == base


def test_on_leaves_the_singular_century_and_other_text_unchanged():
    for t in ('в XV веке', 'в XX веке', 'Глава IV', 'в 2020–2022 гг.', 'от 5 до 10'):
        assert spoken(t, True) == spoken(t, False), t


def test_a_call_that_opens_binds_the_speech_flag_with_the_other_one(tmp_path):
    from echo_sync import ru_alignment
    from echo_sync.controlled_media import ControlledMedia
    try:
        ControlledMedia(tmp_path / 's.sqlite3', session_id='s', settings={'number_ranges': 'on'}).begin_call()
        assert S.RANGES is True and ru_alignment.RANGES is True
        ControlledMedia(tmp_path / 't.sqlite3', session_id='t', settings={}).begin_call()
        assert S.RANGES is False and ru_alignment.RANGES is False
    finally:
        S.set_ranges(False)
        ru_alignment.set_ranges(False)


def test_flipping_ranges_changes_the_cache_key():
    from echo_sync.controlled_host import voice_key
    assert voice_key('v', None, False, True) == 'v:speech:ranges' != voice_key('v') == 'v:speech'
