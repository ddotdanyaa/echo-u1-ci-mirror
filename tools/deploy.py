"""U120: one command puts a build out, one brings the previous one back. Standard library only; no symlinks (Windows): the pointer is TARGET/current.json.

    python -m tools.deploy deploy SRC_DIR TARGET_DIR [--profile shadow|live] [--sha SHA] [--profile-home DIR] [--confirmed-by-coordinator --replay-evidence FILE]
    python -m tools.deploy rollback TARGET_DIR
    python -m tools.deploy verify TARGET_DIR

TARGET/releases/<sha>-<stamp>/echo_sync/ (+ BUILD, manifest.json: sha256 of every file), TARGET/backups/<release>/pre/ (profile_backup of the profile home
taken BEFORE the profile is written), TARGET/current.json (sha, profile, release, history), TARGET/deploy.log (one JSON line per deploy/rollback).
The profile home is TARGET/profile unless ``--profile-home``. Rollback: the manifest of the release it goes back to is checked, the profile backup is
checked and restored (nothing is written when it is damaged), then the pointer moves. Never copied: logs, caches, secret-named non-code files."""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from tools import profile_backup as pb
from tools import server_profile as sp

_SHA = re.compile(r'^[0-9a-f]{7,40}$')


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _write(path, data):
    path = Path(path)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(data, encoding='utf-8')
    os.replace(tmp, path)


def _skip(path):
    return '__pycache__' in path.parts or path.suffix in ('.pyc', '.pyo') or (path.suffix != '.py' and bool(pb._SECRET.search(path.name)))


def _tree(root):
    root = Path(root)
    return {p.relative_to(root).as_posix(): _sha(p) for p in sorted(root.rglob('*')) if p.is_file()}


def _git(src, *args):
    try:
        done = subprocess.run(['git', '-C', str(src), *args], capture_output=True, text=True, timeout=20, check=True)
        return done.stdout.strip()
    except Exception:     # noqa: BLE001 - no git, not a checkout
        return None


def resolve_sha(src, sha=None):
    if sha is not None:
        if not _SHA.match(sha):
            raise ValueError(f'sha {sha!r} is not 7-40 hex characters')
        return sha.lower()
    found = _git(src, 'rev-parse', '--short=12', 'HEAD')
    if not found:
        raise ValueError(f'{src} is not a git checkout: the build is unknown, pass --sha')
    if _git(src, 'status', '--porcelain', '--', 'echo_sync'):
        raise ValueError(f'{src}: echo_sync/ is dirty (uncommitted changes), commit it or pass --sha')
    return found


def _state(target):
    path = Path(target) / 'current.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else None


def _log(target, line):
    with open(Path(target) / 'deploy.log', 'a', encoding='utf-8') as f:
        f.write(json.dumps(line, ensure_ascii=False, sort_keys=True) + '\n')


def verify(target, release=None):
    """The files of the release (default: the current one) that differ from its manifest (changed, missing or not in it); [] = intact."""
    target = Path(target)
    release = release or (_state(target) or {}).get('release')
    if not release:
        raise ValueError('nothing deployed')
    rel = target / 'releases' / release
    manifest = json.loads((rel / 'manifest.json').read_text(encoding='utf-8'))
    actual = _tree(rel / 'echo_sync') if (rel / 'echo_sync').is_dir() else {}
    actual = {f'echo_sync/{k}': v for k, v in actual.items()}
    return sorted(k for k in set(manifest) | set(actual) if manifest.get(k) != actual.get(k))


def deploy(src, target, profile='shadow', sha=None, profile_home=None, confirmed=False, evidence=None):
    t0 = time.perf_counter()
    src, target = Path(src), Path(target)
    if not (src / 'echo_sync').is_dir():
        raise ValueError(f'{src}/echo_sync is not a folder')
    evidence_sha = sp.check_switch(profile, confirmed, evidence)
    sha = resolve_sha(src, sha)
    home = Path(profile_home) if profile_home else target / 'profile'
    prev = _state(target)
    stamp, n = time.strftime('%Y%m%d-%H%M%S'), 1
    name = f'{sha}-{stamp}'
    while (target / 'releases' / name).exists():
        n += 1
        name = f'{sha}-{stamp}-{n}'
    releases = target / 'releases'
    stage = releases / f'.tmp-{name}'
    shutil.rmtree(stage, ignore_errors=True)
    (stage / 'echo_sync').mkdir(parents=True)
    for p in sorted((src / 'echo_sync').rglob('*')):
        rel = p.relative_to(src / 'echo_sync')
        if p.is_file() and not _skip(rel):
            (stage / 'echo_sync' / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, stage / 'echo_sync' / rel)
    (stage / 'echo_sync' / 'BUILD').write_text(sha + '\n', encoding='utf-8')
    manifest = {f'echo_sync/{k}': v for k, v in _tree(stage / 'echo_sync').items()}
    _write(stage / 'manifest.json', json.dumps(manifest, indent=1, sort_keys=True))
    backup = pb.backup(home, target / 'backups' / name, stamp='pre') if home.is_dir() else None
    sp.apply(home, profile)
    os.replace(stage, releases / name)
    entry = {'release': name, 'sha': sha, 'profile': profile, 'backup': backup.relative_to(target).as_posix() if backup else None, 'profile_home': str(home)}
    history = (prev or {}).get('history', []) + [entry]
    _write(target / 'current.json', json.dumps({**entry, 'history': history}, ensure_ascii=False, indent=1, sort_keys=True))
    took = round(time.perf_counter() - t0, 3)
    _log(target, {'action': 'deploy', 'time': time.strftime('%Y-%m-%dT%H:%M:%S'), 'sha': sha, 'profile': profile, 'release': name,
                  'previous': prev['release'] if prev else None, 'duration_s': took, 'backup': entry['backup'], 'overlay_keys': sorted(sp.overlay(profile)),
                  'confirmed_by_coordinator': bool(confirmed), 'evidence_sha256': evidence_sha})
    return {**entry, 'previous': prev['release'] if prev else None, 'duration_s': took}


def rollback(target):
    t0 = time.perf_counter()
    target = Path(target)
    cur = _state(target)
    if not cur or len(cur.get('history', [])) < 2:
        raise ValueError('no previous release to go back to')
    gone, back = cur['history'][-1], cur['history'][-2]
    bad = verify(target, back['release'])
    if bad:
        raise ValueError(f"manifest of release {back['release']} does not match its files: {bad[:5]}")
    home = Path(gone['profile_home'])
    if gone['backup']:
        pb.restore(target / gone['backup'], home)
        saved = json.loads((target / gone['backup'] / 'manifest.json').read_text(encoding='utf-8'))
        if sp.SETTINGS_FILE.as_posix() not in saved and (home / sp.SETTINGS_FILE).is_file():
            (home / sp.SETTINGS_FILE).unlink()      # the deploy created it: there was none before
    _write(target / 'current.json', json.dumps({**back, 'history': cur['history'][:-1]}, ensure_ascii=False, indent=1, sort_keys=True))
    took = round(time.perf_counter() - t0, 3)
    _log(target, {'action': 'rollback', 'time': time.strftime('%Y-%m-%dT%H:%M:%S'), 'sha': back['sha'], 'profile': back['profile'], 'release': back['release'],
                  'previous': gone['release'], 'duration_s': took, 'backup': gone['backup']})
    return {**back, 'from': gone['release'], 'duration_s': took}


def main(argv=None):
    ap = argparse.ArgumentParser(prog='deploy', description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    d = sub.add_parser('deploy')
    d.add_argument('src')
    d.add_argument('target')
    d.add_argument('--profile', default='shadow', choices=sorted(sp.PROFILES))
    d.add_argument('--sha')
    d.add_argument('--profile-home')
    d.add_argument('--confirmed-by-coordinator', action='store_true')
    d.add_argument('--replay-evidence')
    for name in ('rollback', 'verify'):
        sub.add_parser(name).add_argument('target')
    a = ap.parse_args(argv)
    try:
        if a.cmd == 'deploy':
            out = deploy(a.src, a.target, a.profile, a.sha, a.profile_home, a.confirmed_by_coordinator, a.replay_evidence)
            print(f"deployed sha={out['sha']} profile={out['profile']} release={out['release']} previous={out['previous']} in {out['duration_s']} s")
        elif a.cmd == 'rollback':
            out = rollback(a.target)
            print(f"rolled back to sha={out['sha']} profile={out['profile']} release={out['release']} (from {out['from']}) in {out['duration_s']} s")
        else:
            bad = verify(a.target)
            print('release intact' if not bad else 'MISMATCH: ' + ', '.join(bad))
            return 1 if bad else 0
    except (ValueError, OSError) as exc:
        print(f'refused: {exc}', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
