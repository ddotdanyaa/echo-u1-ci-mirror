# factory-backlog-id: С5
import os
import sys
import types

import pytest

from echo_sync import sapi_worker
from echo_sync.sapi_worker import SapiWorkerError, SapiWorkerManager

CREATE_NO_WINDOW = 0x08000000


class Nt:
    name = 'nt'

    def __getattr__(self, attr):
        return getattr(os, attr)


def _stub(monkeypatch, name, **attrs):
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    monkeypatch.setitem(sys.modules, name, module)
    return module


def test_worker_is_launched_with_a_hidden_window(tmp_path, monkeypatch):
    _stub(monkeypatch, 'hermes_cli')
    _stub(monkeypatch, 'hermes_cli._subprocess_compat', windows_hide_flags=lambda: 0)
    _stub(monkeypatch, 'tools')
    _stub(monkeypatch, 'tools.environments')
    _stub(monkeypatch, 'tools.environments.local', hermes_subprocess_env=lambda **kwargs: {})
    monkeypatch.setattr(sapi_worker, 'os', Nt())

    script = tmp_path / 'worker.ps1'
    script.write_text('# stub', encoding='utf-8')
    seen = {}

    def popen(command, **kwargs):
        seen['command'] = list(command)
        seen['kwargs'] = kwargs
        raise RuntimeError('stop here')

    manager = SapiWorkerManager('hidden', script_path=str(script), popen_factory=popen)
    try:
        with pytest.raises(SapiWorkerError, match='worker_start_failed'):
            manager._start_locked()
    finally:
        manager.close()

    command = seen['command']
    assert '-WindowStyle' in command, command
    assert command[command.index('-WindowStyle') + 1] == 'Hidden'
    assert seen['kwargs']['creationflags'] & CREATE_NO_WINDOW == CREATE_NO_WINDOW
