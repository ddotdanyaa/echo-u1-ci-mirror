# factory-backlog-id: W17
from echo_sync.fast_text import adds_nothing

import pytest
pytestmark = pytest.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)


def test_adds_nothing_general_formulation():
    heard = "человек на экзамене, на собеседовании или перед презентацией"
    said = ["общий вопрос"]
    # On the current code, this specific phrase or its handling has a certain output;
    # we assert the behavior under the general formulation requirement.
    # If the old code hardcodes or handles it specifically, this test fails or checks the exact condition.
    assert adds_nothing(heard, said) is True
