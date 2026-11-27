"""U16 (one-input): a written range is matched by the VALUES of its two ends, whatever the ear wrote between them (a joint, nothing, digits, Roman numerals). Replay 20261106-111421 (stuck 3→5) is laptop-only."""
import pytest
from echo_sync import ru_alignment as ra

ROMAN, YEARS = 'Это было в XIII–XV веках в Европе.', 'Города росли в 1941–1945 годах заметно.'


@pytest.mark.parametrize('portion,heard', [
    (ROMAN, 'это было в тринадцатом пятнадцатом веках в европе'),       # «по» swallowed by the ear
    (ROMAN, 'это было в XIII XV веках в европе'),                       # the ear wrote the numerals apart (was ack with the key off)
    (ROMAN, 'это было в XIII по XV веках в европе'),
    (ROMAN, 'это было в XIII–XV веках в европе'),
    (YEARS, 'города росли в 1941 1945 годах заметно'),
    (YEARS, 'города росли в тысяча девятьсот сорок первом по тысяча девятьсот сорок пятом годах заметно'),
])
def test_a_range_said_by_its_two_ends_counts(portion, heard):
    assert ra.match_current(heard, portion) == 'ack'


@pytest.mark.parametrize('portion,heard', [
    (ROMAN, 'это было в тринадцатом шестнадцатом веках в европе'),      # another end
    (ROMAN, 'это было в тринадцатом четырнадцатом веках в европе'),
    (ROMAN, 'это было в пятнадцатом тринадцатом веках в европе'),       # the ends swapped
    (ROMAN, 'это было в тринадцатом веках в европе'),                   # one end only
    (YEARS, 'города росли в 1941 1946 годах заметно'),
])
def test_another_pair_of_ends_is_no_range_said(portion, heard):
    assert ra.match_current(heard, portion) != 'ack'


def test_said_pair_is_written_back_as_the_portion_writes_it():
    assert ra.spoken_as_written('в тринадцатом пятнадцатом веках', 'в XIII–XV веках') == 'в xiii–xv веках'
