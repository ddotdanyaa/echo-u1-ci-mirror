"""U22 P0-2: the seams that let the tests survive the cut of ``controlled_media.py`` into ``cm_*`` modules."""
import pytest

from cm_patch import controller_modules, controller_source, duplicate_methods, override, patch_controller
from echo_sync import cm_probes
from echo_sync.controlled_media import ControlledMedia


def scratch_class(name, module, **members):
    return type(name, (), {**members, '__module__': module})


def test_patch_controller_replaces_the_name_in_every_module_that_binds_it_and_gives_it_back(monkeypatch):
    real = cm_probes.analyze
    with pytest.MonkeyPatch.context() as mp:
        hit = patch_controller(mp, 'analyze', lambda *a, **k: None)
        assert cm_probes in hit and all(m.analyze is not real for m in hit)
    assert cm_probes.analyze is real


@pytest.mark.parametrize('name', ['analyze', 'stable_prefix', 'first_cue', 'reference_lookup'])
def test_the_four_names_the_tests_patch_are_bound_in_the_controller(name):
    assert any(name in vars(m) for m in controller_modules()), name


def test_patch_controller_refuses_a_name_no_module_binds():
    with pytest.MonkeyPatch.context() as mp, pytest.raises(AttributeError):
        patch_controller(mp, 'no_such_name_anywhere', None)


def test_the_controller_source_holds_the_class():
    assert 'class ControlledMedia' in controller_source()


def test_no_method_is_defined_twice_in_the_controller_mro():
    """A second ``def`` of a name in another mixin silently wins or loses by MRO order: two fixes then collide in the split file."""
    assert duplicate_methods(ControlledMedia) == {}


def test_a_scratch_duplicate_method_is_found():
    base = scratch_class('Base', 'echo_sync.cm_scratch', work=lambda self: 1)
    top = type('Top', (base,), {'work': lambda self: 2, '__module__': 'echo_sync.cm_other'})
    assert set(duplicate_methods(top)) == {'work'}


def test_a_marked_override_and_a_foreign_class_are_not_duplicates():
    base = scratch_class('Base', 'echo_sync.cm_scratch', work=lambda self: 1)
    top = type('Top', (base,), {'work': override(lambda self: 2), '__module__': 'echo_sync.cm_other'})
    assert duplicate_methods(top) == {}
    foreign = type('Foreign', (scratch_class('B', 'other.module', work=lambda self: 1),), {'work': lambda self: 2, '__module__': 'other.module'})
    assert duplicate_methods(foreign) == {}
