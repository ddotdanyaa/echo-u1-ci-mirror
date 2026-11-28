# factory-backlog-id: E46.s2
import pytest
from unittest.mock import patch
from echo_sync.first_useful import _first_new

def test_first_new_handles_portions_error():
    text = "some text"
    question = "some question"
    settings = {}
    
    with patch('echo_sync.first_useful.portions', side_effect=Exception("Portions failed")):
        try:
            result = _first_new(text, question, settings)
            assert result is None
        except Exception as e:
            pytest.fail(f"_first_new crashed with {e} instead of returning None")

def test_first_new_handles_adds_nothing_error():
    text = "some text"
    question = "some question"
    settings = {}
    
    with patch('echo_sync.first_useful.portions', return_value=["some"]), \
         patch('echo_sync.first_useful._adds_nothing', side_effect=Exception("Adds nothing failed")):
        try:
            result = _first_new(text, question, settings)
            assert result is None
        except Exception as e:
            pytest.fail(f"_first_new crashed with {e} instead of returning None")