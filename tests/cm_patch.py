"""Split-proof seams for the tests of the controller (U22 P0-2).

``echo_sync/controlled_media.py`` is to be cut into ``cm_*`` mixin modules. A test that does ``monkeypatch.setattr(controlled_media, 'analyze', ..)``
patches one module's global; once the code that calls ``analyze`` lives in a ``cm_*`` module the patch silently does nothing. These helpers
patch the name wherever the controller's modules bind it, and read the controller's source from all of its modules.
"""
import importlib
import inspect
import pkgutil
from pathlib import Path

import echo_sync

CONTROLLER = 'echo_sync.controlled_media'
PREFIX = 'echo_sync.cm_'


def controller_modules():
    """``controlled_media`` and every ``echo_sync/cm_*.py`` (imported), in a stable order."""
    names = [CONTROLLER] + sorted(PREFIX + info.name[3:] for info in pkgutil.iter_modules(echo_sync.__path__) if info.name.startswith('cm_'))
    return [importlib.import_module(name) for name in names]


def controller_source():
    """The text of all controller modules, for the tests that read the source."""
    return '\n'.join(Path(module.__file__).read_text(encoding='utf-8') for module in controller_modules())


def patch_controller(patcher, name, value):
    """``patcher.setattr`` on every controller module that binds ``name``; fails when none does (a typo would patch nothing)."""
    hit = [module for module in controller_modules() if name in vars(module)]
    if not hit:
        raise AttributeError(f'no controller module binds {name!r}')
    for module in hit:
        patcher.setattr(module, name, value)
    return hit


def override(function):
    """Mark a method that is a deliberate override of another class's method in the controller's MRO."""
    function.cm_override = True
    return function


def duplicate_methods(cls):
    """``{name: [class, ..]}`` for each method defined by two or more controller classes of the MRO, unless the class that comes first in the
    MRO (the one that wins) marks it ``@override``."""
    seen, duplicates = {}, {}
    for klass in cls.__mro__:
        if klass.__module__ != CONTROLLER and not klass.__module__.startswith(PREFIX):
            continue
        for name, member in vars(klass).items():
            raw = member.__func__ if isinstance(member, (staticmethod, classmethod)) else member
            if not inspect.isfunction(raw) and not isinstance(raw, property):
                continue
            if name in seen:
                first, marked = seen[name]
                if not marked:
                    duplicates.setdefault(name, [first]).append(klass)
            else:
                seen[name] = (klass, bool(getattr(raw, 'cm_override', False)))
    return duplicates
