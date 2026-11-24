"""W13 item 10: the W03 fingerprint on the server. The deploy (cloud_context/scripts/deploy_controlled_media_binding.py) copies every module of
echo_sync but ``__init__.py`` and ``plugin.py`` into ``echo_controlled`` and writes a 66-byte ``__init__.py``: ``from . import fingerprint`` failed
silently and no «echo-sync loaded» line came. The fingerprint lives in a module that is deployed (``build_info``)."""
import importlib.util
import logging
import shutil
import sys
from pathlib import Path

import echo_sync

STUB = '"""Echo adapters only; never registers the legacy controller."""\n'


def deployed(tmp_path):
    source = Path(echo_sync.__file__).parent
    target = tmp_path / 'echo_controlled'
    target.mkdir()
    for item in source.glob('*.py'):
        if item.name not in {'__init__.py', 'plugin.py'}:
            shutil.copy2(item, target / item.name)
    (target / '__init__.py').write_text(STUB, encoding='utf-8')
    (target / 'BUILD').write_text('abcdef012345\n', encoding='utf-8')
    name = 'echo_controlled_w13'
    spec = importlib.util.spec_from_file_location(name, target / '__init__.py', submodule_search_locations=[str(target)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return name


def test_the_deployed_package_has_the_fingerprint(tmp_path):
    name = deployed(tmp_path)
    try:
        info = importlib.import_module(name + '.build_info')
        loaded = info.fingerprint({'fast_text': 'on'})
        assert loaded['build'] == 'abcdef012345' and loaded['digest'] and loaded['prompt'] != 'unreadable' and loaded['flags']
        assert any(key.startswith(name + '.') for key in loaded['modules']), loaded['modules']
    finally:
        for key in [k for k in sys.modules if k == name or k.startswith(name + '.')]:
            sys.modules.pop(key)


def test_the_host_and_the_plugin_take_it_from_the_deployed_module():
    root = Path(echo_sync.__file__).parent
    for name in ('controlled_host.py', 'plugin.py'):
        text = (root / name).read_text(encoding='utf-8')
        assert 'from .build_info import fingerprint' in text and 'from . import fingerprint' not in text, name


def test_the_package_still_exports_it():
    assert echo_sync.fingerprint is echo_sync.build_info.fingerprint and echo_sync.build_id is echo_sync.build_info.build_id
