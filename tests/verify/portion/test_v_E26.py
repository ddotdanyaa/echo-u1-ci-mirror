"""V4 E26: the length of a portion is adapted to the person (preset ``adaptive`` / ``slow``: a constant budget of syllables), and a way to go on that is not the voice. Backlog: the preset is the whole of it;
a manual mode of the control is NOT in SETTINGS (a search for ``manual`` and ``dysarthr`` in ``echo_sync`` gave 0 files), what Conduit gives without a voice is E26.2 (not here).

Real ControlledMedia built as the host builds it (``helpers_s6_ack.Dictation``) with the call's profile and a named preset over it. Not run on the laptop. A red test of the first two is a defect card for the family P
(``portioner``); the last one pins the gap: the manual mode is not made, and no test here says it is.
"""
import pytest

import helpers_s6_ack as H
from echo_sync.settings import CALL_SETTINGS, DEFAULTS, PRESETS
from portion_kit import syllables

ANSWER = ('Налог на прибыль платят все организации. Ставка налога составляет двадцать процентов. Налог платят каждый квартал. '
          'Декларацию подают в налоговую службу. Срок подачи установлен законом.')


def chunks_of(tmp_path, preset):
    d = H.Dictation(tmp_path, ANSWER, settings={**CALL_SETTINGS, 'preset': preset})
    return d.chunks


@pytest.mark.parametrize('preset', ['adaptive', 'slow'])
def test_every_portion_of_an_adaptive_preset_is_inside_its_budget(tmp_path, preset):
    limit = PRESETS[preset]
    chunks = chunks_of(tmp_path, preset)
    assert len(chunks) >= 5, f'precondition: the answer is cut in parts: {chunks}'
    assert all(syllables(c) <= limit['max_syllables'] for c in chunks), f'a portion over the budget of {preset}: {chunks}'
    assert all(len(c.split()) <= limit['max_words'] for c in chunks), chunks


def test_a_slower_preset_cuts_smaller_portions_than_the_meaning_of_the_call(tmp_path):
    meaning = H.Dictation(tmp_path / 'm', ANSWER, settings=dict(CALL_SETTINGS)).chunks
    slow = chunks_of(tmp_path / 's', 'slow')
    assert len(slow) > len(meaning), f'the budget did not change the cut: meaning {meaning} slow {slow}'
    assert max(syllables(c) for c in slow) < max(syllables(c) for c in meaning)


def test_no_manual_or_voiceless_mode_exists_yet_so_the_row_stays_partial():
    """Not a pass of the manual mode: it records that the row's open half is still open (a switch for it would change this line, and the row with it)."""
    assert not [key for key in DEFAULTS if 'manual' in key or 'dysarthr' in key]
