"""Reversible, exact-source guarded canonical native-chat silence opt-in.

Supported source snapshot: NousResearch/hermes-agent 3cbe7b19db144d73b3ea55ddb1f5d8cd2913f008.
No automatic update or permissive best-effort patching of unknown versions.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

KNOWN_COMMIT = '3cbe7b19db144d73b3ea55ddb1f5d8cd2913f008'
TARGET = 'gateway/response_filters.py'
REQUIRED_HASHES = {
    TARGET: 'c229a2aae6f57be1e75e40df9a2274f46fa7f3c77e1edbaea95b6cba9d280aef',
    'agent/turn_api_call.py': '2897575995d8dcbe94bba666ef66043a64c52a6c99e72c45e7da64a5fbdf576b',
    'agent/turn_context.py': '09a6159b0301da271f1a6bdcf15d924a05dee8d7d6b9e2f4ed46e406aac0aa4e',
    'gateway/session_ingress.py': 'd498954d3867337e3beda70adfbef0f581671e72e73e0526ae0eefe37101127f',
    'gateway/session_settlement_recovery.py': '641e79576b20c6bf21f599bc92ebfc12bb68cf59f222568600bb99128b1bf95e',
}
OLD = b'    return is_machinery_display_kind(display_kind) or reply_expected is False\n'
NEW = b'    return is_machinery_display_kind(display_kind) or reply_expected is False or _echo_sync_silence_enabled()\n'
HELPER = b'''\n\n# ECHO-SYNCHRON: explicit opt-in only in the active profile; no text transform.\ndef _echo_sync_silence_enabled() -> bool:\n    try:\n        from hermes_constants import get_hermes_home\n        marker = get_hermes_home() / "echo-sync" / "allow_silence"\n        return marker.is_file() and marker.read_text(encoding="utf-8").strip() == "ECHO-SYNCHRON-1"\n    except (OSError, UnicodeError):\n        return False\n'''
MAGIC = 'ECHO-SYNCHRON-1\n'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def _validate(root):
    target = root / TARGET
    backup = root / (TARGET + '.echo-sync.bak')
    for rel, expected in REQUIRED_HASHES.items():
        path = root / rel
        if not path.is_file():
            raise RuntimeError(f'Unsupported Hermes source: missing {rel}; expected {KNOWN_COMMIT}')
        content = path.read_bytes()
        if rel == TARGET and backup.is_file() and digest(backup.read_bytes()) == expected:
            patched = backup.read_bytes().replace(OLD, NEW, 1) + HELPER
            if content == patched:
                continue
        if digest(content) != expected:
            raise RuntimeError(f'Unsupported or changed Hermes source: {rel}; tested snapshot {KNOWN_COMMIT}. No file was patched.')
    return target, backup


def _atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.echo-sync.tmp')
    try:
        temporary.write_bytes(data)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def apply_patch(hermes_root, profile_home):
    root, home = Path(hermes_root).resolve(), Path(profile_home).resolve()
    target, backup = _validate(root)
    content = target.read_bytes()
    already = backup.is_file() and content == backup.read_bytes().replace(OLD, NEW, 1) + HELPER
    if not already:
        if backup.exists():
            raise RuntimeError('Existing backup does not match; refusing to overwrite it')
        if content.count(OLD) != 1:
            raise RuntimeError('Expected silence boundary was not found exactly once')
        # Keep exact original bytes and permissions before the single-file mutation.
        with backup.open('xb') as file:
            file.write(content)
        os.chmod(backup, target.stat().st_mode)
        _atomic(target, content.replace(OLD, NEW, 1) + HELPER)
    _atomic(home / 'echo-sync' / 'allow_silence', MAGIC.encode())
    return {'status': 'already_applied' if already else 'applied', 'hermes_root': str(root), 'profile_home': str(home), 'tested_commit': KNOWN_COMMIT, 'restart_required': True}


def rollback_patch(hermes_root, profile_home):
    root, home = Path(hermes_root).resolve(), Path(profile_home).resolve()
    target, backup = _validate(root)
    if not backup.is_file():
        (home / 'echo-sync' / 'allow_silence').unlink(missing_ok=True)
        return {'status': 'not_applied', 'restart_required': False}
    original = backup.read_bytes()
    if digest(original) != REQUIRED_HASHES[TARGET]:
        raise RuntimeError('Backup differs from the supported original; refusing rollback')
    _atomic(target, original)
    backup.unlink()
    (home / 'echo-sync' / 'allow_silence').unlink(missing_ok=True)
    return {'status': 'restored', 'restart_required': True}


def check_patch(hermes_root, profile_home):
    target, backup = _validate(Path(hermes_root))
    marker = Path(profile_home) / 'echo-sync' / 'allow_silence'
    return {'supported': True, 'patched': backup.is_file() and target.read_bytes() == backup.read_bytes().replace(OLD, NEW, 1) + HELPER, 'profile_opted_in': marker.is_file() and marker.read_text(encoding='utf-8') == MAGIC, 'tested_commit': KNOWN_COMMIT}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['apply', 'rollback', 'check'])
    parser.add_argument('--hermes-root', required=True, type=Path)
    parser.add_argument('--profile-home', required=True, type=Path)
    args = parser.parse_args()
    operation = {'apply':apply_patch, 'rollback':rollback_patch, 'check':check_patch}[args.action]
    print(json.dumps(operation(args.hermes_root, args.profile_home), ensure_ascii=False))


if __name__ == '__main__':
    main()
