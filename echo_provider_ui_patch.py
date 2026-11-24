"""Exact-source reversible patch adding configured command TTS rows to the provider picker."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import tempfile

TARGET = 'hermes_cli/tools_config_providers.py'
TARGET_BACKUP = TARGET + '.echo-provider-ui.bak'
EXPECTED_SHA256 = 'feb6278c87923ce2ae0e232af926ac04e0a033c273bad57128527aa24ed442a5'
ANCHOR = b'    # Plugin-registered rows render BELOW the hardcoded rows (for web/browser they are the only real provider rows).\n    builder = _PLUGIN_ROW_BUILDERS.get(cat.get("name"))\n    if builder is not None:\n        visible.extend(builder())\n    return visible\n'
INSERTED = b'    # Plugin-registered rows render BELOW the hardcoded rows (for web/browser they are the only real provider rows).\n    builder = _PLUGIN_ROW_BUILDERS.get(cat.get("name"))\n    if builder is not None:\n        visible.extend(builder())\n    # ECHO-PROVIDER-UI: expose only configured command TTS providers in this profile.\n    if cat.get("name") == "Text-to-Speech":\n        try:\n            from tools.tts_command_provider import _iter_command_providers\n            tts_section = config.get("tts", {}) if isinstance(config, dict) else {}\n            if isinstance(tts_section, dict):\n                known_ids = {str(row.get("tts_provider", "")).strip().lower() for row in visible if isinstance(row, dict)}\n                known_labels = {str(row.get("name", "")).strip().casefold() for row in visible if isinstance(row, dict)}\n                for provider_id, provider_cfg in _iter_command_providers(tts_section):\n                    try:\n                        if not isinstance(provider_id, str) or not provider_id.strip() or not isinstance(provider_cfg, dict):\n                            continue\n                        provider_key = provider_id.strip().lower()\n                        display_name = provider_cfg.get("display_name")\n                        if not isinstance(display_name, str) or not display_name.strip():\n                            display_name = provider_id + " (host command)"\n                        else:\n                            display_name = display_name.strip()\n                        label_key = display_name.casefold()\n                        if provider_key in known_ids or label_key in known_labels:\n                            continue\n                        visible.append({"name": display_name, "tts_provider": provider_key,\n                                        "env_vars": [],\n                                        "tag": "local command; confirm with voice test", "badge": "local"})\n                        known_ids.add(provider_key)\n                        known_labels.add(label_key)\n                    except Exception:\n                        continue\n        except Exception:\n            pass\n    return visible\n'


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _paths(root):
    root = Path(root).resolve()
    return root, root / TARGET, root / TARGET_BACKUP


def _validate(root):
    root, target, backup = _paths(root)
    if not target.is_file():
        raise RuntimeError(f'Unsupported Hermes source: missing {TARGET}')
    data = target.read_bytes()
    if backup.is_file() and _digest(backup.read_bytes()) == EXPECTED_SHA256:
        expected_patched = backup.read_bytes().replace(ANCHOR, INSERTED, 1)
        if backup.read_bytes().count(ANCHOR) == 1 and data == expected_patched:
            return root, target, backup, data
        raise RuntimeError(f'Existing patch or backup differs from supported exact form: {TARGET}')
    if _digest(data) != EXPECTED_SHA256:
        raise RuntimeError(f'Unsupported or changed Hermes source: {TARGET}; refusing patch')
    if data.count(ANCHOR) != 1:
        raise RuntimeError('Expected provider-list insertion point was not found exactly once')
    return root, target, backup, data


def _atomic_write(path: Path, data: bytes) -> None:
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def apply_patch(root):
    root, target, backup, data = _validate(root)
    if backup.is_file() and backup.read_bytes().count(ANCHOR) == 1 and data == backup.read_bytes().replace(ANCHOR, INSERTED, 1):
        return {'status': 'already_applied', 'hermes_root': str(root)}
    patched = data.replace(ANCHOR, INSERTED, 1)
    with backup.open('xb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.chmod(backup, target.stat().st_mode)
        _atomic_write(target, patched)
    except Exception:
        backup.unlink(missing_ok=True)
        raise
    return {'status': 'applied', 'hermes_root': str(root)}


def rollback_patch(root):
    root, target, backup, data = _validate(root)
    if not backup.is_file():
        return {'status': 'not_applied', 'hermes_root': str(root)}
    original = backup.read_bytes()
    if _digest(original) != EXPECTED_SHA256 or original.count(ANCHOR) != 1 or data != original.replace(ANCHOR, INSERTED, 1):
        raise RuntimeError('Patch or backup differs from the supported exact form; refusing rollback')
    _atomic_write(target, original)
    backup.unlink()
    return {'status': 'restored', 'hermes_root': str(root)}
