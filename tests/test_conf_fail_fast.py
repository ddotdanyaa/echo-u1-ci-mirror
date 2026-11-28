"""CONF: a cloud session without the engine's libraries stops at once with ONE line; it does not run a suite that lies (hundreds of reds for the environment, not for the code)."""
import importlib
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
_spec = importlib.util.spec_from_file_location('echo_root_conftest', ROOT / 'tests' / 'conftest.py')      # by its file: ``import conftest`` gives the LAST conftest collected (tests/break/answer_route/conftest.py in a shard that has it)
conftest = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(conftest)


def test_the_list_is_the_one_of_setup_cloud():
    assert set(conftest.REQUIRED_LIBRARIES) == {'rapidfuzz', 'razdel', 'pymorphy3', 'snowballstemmer', 'hypothesis', 'httpx'}


def test_a_machine_with_every_library_is_not_stopped():
    assert conftest.missing_libraries() == []


def test_a_missing_library_is_named():
    assert conftest.missing_libraries(('rapidfuzz', 'no_such_library_conf_x')) == ['no_such_library_conf_x']


def test_the_session_stops_with_one_usage_error_that_names_what_is_missing(monkeypatch):
    monkeypatch.setattr(conftest, 'missing_libraries', lambda names=(): ['razdel', 'pymorphy3'])
    with pytest.raises(pytest.UsageError) as raised:
        conftest.pytest_sessionstart(None)
    text = str(raised.value)
    assert 'razdel' in text and 'pymorphy3' in text and '\n' not in text and 'SETUP_CLOUD.sh' in text
