"""g12: the engine falls back silently without its libraries, and a fallback hides or invents verdicts (DEF-FAULT-06 was green without RapidFuzz, 25 tests of test_h2_brain red).
A run on a bare interpreter must say so at once, not show a different suite: install with cloud_context/SETUP_CLOUD.sh."""
import importlib

import pytest

REQUIRED = ('rapidfuzz', 'razdel', 'pymorphy3', 'snowballstemmer', 'diskcache')


@pytest.mark.parametrize('name', REQUIRED)
def test_the_library_the_engine_needs_is_installed(name):
    try:
        importlib.import_module(name)
    except ImportError as error:
        pytest.fail(f'{name} is missing ({error}): the engine takes a silent fallback and other tests lie. Run bash cloud_context/SETUP_CLOUD.sh')


def test_the_morphology_dictionary_is_installed():
    import pymorphy3
    assert pymorphy3.MorphAnalyzer().parse('люди')[0].normal_form == 'человек', 'pymorphy3-dicts-ru is missing or broken'
