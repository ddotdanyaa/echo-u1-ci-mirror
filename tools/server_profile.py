"""U102: the server profile - a named overlay of ``settings.DEFAULTS`` keys written into ``materials/echo_settings.json`` of the profile home.

    python -m tools.server_profile show TARGET     # the loaded SHA and the profile from TARGET/current.json

``shadow`` is today's server: the defaults, no overlay. ``live`` is an explicit list of keys (the shadow flags turned on). Only keys that exist in
``settings.DEFAULTS`` are allowed. shadow -> live needs the coordinator's flag and a replay-evidence file that exists (``check_switch``).
The ``live`` content is a proposal until the coordinator decides it after the replay of the recorded calls."""
import json
import sys
from pathlib import Path

from echo_sync import settings

PROFILES = {
    'shadow': {},
    'live': {'local_ear': 'act', 'v5_answer_gate': 'on', 'keep_ready': 'on', 'local_onset': 'on'},
}
SETTINGS_FILE = Path('materials') / 'echo_settings.json'


def validate(name):
    if name not in PROFILES:
        raise ValueError(f'unknown profile {name!r}: {sorted(PROFILES)}')
    bad = sorted(set(PROFILES[name]) - set(settings.DEFAULTS))
    if bad:
        raise ValueError(f'profile {name!r}: keys not in settings.DEFAULTS: {bad}')
    return PROFILES[name]


def overlay(name):
    return dict(validate(name))


def managed_keys():
    return {k for n in PROFILES for k in validate(n)}


def check_switch(name, confirmed=False, evidence=None):
    """Refuse the way to ``live`` without the coordinator's flag and a replay-evidence file; returns the file's sha256 (or None)."""
    validate(name)
    if name != 'live':
        return None
    if not confirmed:
        raise ValueError('live needs --confirmed-by-coordinator (the coordinator decides after the replay of the recorded calls)')
    if not evidence or not Path(evidence).is_file():
        raise ValueError('live needs --replay-evidence PATH of an existing replay-evidence file')
    import hashlib
    return hashlib.sha256(Path(evidence).read_bytes()).hexdigest()


def apply(profile_home, name):
    """Write the overlay over the owner's own keys: the keys of every named profile are dropped first, so live -> shadow gives the defaults back."""
    path = Path(profile_home) / SETTINGS_FILE
    try:
        current = json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}
    except ValueError as exc:
        raise ValueError(f'{path} is not JSON: {exc}') from exc
    if not isinstance(current, dict):
        raise ValueError(f'{path} is not a JSON object')
    merged = {k: v for k, v in current.items() if k not in managed_keys()}
    merged.update(overlay(name))
    if merged != current:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(merged, ensure_ascii=False, indent=1, sort_keys=True), encoding='utf-8')
    return merged


def show(target):
    path = Path(target) / 'current.json'
    if not path.is_file():
        return None
    cur = json.loads(path.read_text(encoding='utf-8'))
    return {'sha': cur['sha'], 'profile': cur['profile'], 'release': cur['release']}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2 or argv[0] != 'show':
        print(__doc__)
        return 2
    found = show(argv[1])
    print(f"sha={found['sha']} profile={found['profile']} release={found['release']}" if found else 'nothing deployed')
    return 0 if found else 1


if __name__ == '__main__':
    sys.exit(main())
