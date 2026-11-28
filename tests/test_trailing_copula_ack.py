"""Real native failure: a spoken term need not include a typographic copula dash."""
import pytest
from echo_sync.ru_alignment import match_current
from echo_sync.ack_semantics import ack_symbols_compatible


@pytest.mark.parametrize('dash',['—','–'])
def test_trailing_copula_punctuation_is_not_a_spoken_minus(dash):
    expected='Электроэнцефалограмма '+dash
    assert match_current('Электроэнцефалограмма',expected)=='ack'
    assert ack_symbols_compatible('Электроэнцефалограмма',expected)


@pytest.mark.parametrize('expected',['5 —','x —','температура −','температура минус'])
def test_numeric_variable_and_explicit_minus_stay_protected(expected):
    heard=expected.split()[0]
    assert match_current(heard,expected)!='ack'


def test_negation_and_wrong_term_are_not_fixed_by_punctuation_tolerance():
    assert match_current('Не электроэнцефалограмма','Электроэнцефалограмма —')!='ack'
    assert match_current('Электрокардиограмма','Электроэнцефалограмма —')!='ack'
