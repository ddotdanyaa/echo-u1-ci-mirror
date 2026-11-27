"""N178, N176 (g24): a backup of the profile's materials before a rollout, and the rollback in one command.

    python -m tools.profile_backup backup  PROFILE BACKUPS      # copies materials/ (+ top-level *.json except secrets) with a sha256 manifest
    python -m tools.profile_backup restore PROFILE BACKUPS      # the newest backup back; a file that changed is kept as ``<name>.before-restore``

Never copied: logs, anything named like auth/token/secret/cookie/key. A backup whose manifest does not match its files restores nothing (checked
before the first file is written)."""
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

_SECRET = re.compile(r'auth|token|secret|cookie|passw|key|credential', re.I)


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _files(profile):
    profile = Path(profile)
    found = [f for f in (profile / 'materials').rglob('*') if f.is_file()] if (profile / 'materials').is_dir() else []
    found += [f for f in profile.glob('*.json') if f.is_file()]
    return sorted(f for f in found if not _SECRET.search(f.name))


def backup(profile, backups, stamp=None):
    import time
    profile, backups = Path(profile), Path(backups)
    stamp = stamp or time.strftime('%Y%m%d-%H%M%S')
    dest, n = backups / stamp, 1
    while dest.exists():
        n += 1
        dest = backups / f'{stamp}-{n}'
    manifest = {}
    for f in _files(profile):
        rel = f.relative_to(profile)
        (dest / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, dest / rel)
        manifest[rel.as_posix()] = _sha(f)
    (dest / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True), encoding='utf-8')
    return dest


def latest(backups):
    backups = Path(backups)
    dirs = sorted(d for d in backups.iterdir() if (d / 'manifest.json').is_file()) if backups.is_dir() else []
    return dirs[-1] if dirs else None


def restore(src, profile):
    src, profile = Path(src), Path(profile)
    try:
        manifest = json.loads((src / 'manifest.json').read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise ValueError(f'no readable manifest: {type(exc).__name__}') from exc
    for rel, digest in manifest.items():
        f = src / rel
        if Path(rel).is_absolute() or '..' in Path(rel).parts or not f.is_file() or _sha(f) != digest:
            raise ValueError(f'backup is damaged: {rel}')
    for rel in manifest:
        target = profile / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and _sha(target) != manifest[rel]:
            shutil.copy2(target, target.with_name(target.name + '.before-restore'))
        shutil.copy2(src / rel, target)
    return sorted(manifest)


if __name__ == '__main__':
    if len(sys.argv) != 4 or sys.argv[1] not in ('backup', 'restore'):
        sys.exit(__doc__)
    if sys.argv[1] == 'backup':
        print(backup(sys.argv[2], sys.argv[3]))
    else:
        found = latest(sys.argv[3])
        print(restore(found, sys.argv[2]) if found else sys.exit('no backup'))
