"""<id> foundation: one shared ledger of key usage per channel registry folder. Each task state publishes its own channel quotas as one section file (one writer per state: its checkpoint lock); a call chooses on the union of its own quotas and the other sections; old sections stop counting; an unreadable file is skipped, never a crash."""
import copy
import hashlib
import json
import os
import time
from pathlib import Path

STALE_S = 2 * 86400
LISTS = ('request_times', 'rpm_times', 'minute')


def section_file(folder, section) -> Path:
    return Path(folder) / (hashlib.sha1(str(section).encode('utf-8')).hexdigest()[:16] + '.json')


def publish(folder, section, quotas, *, now=None) -> None:
    now = time.time() if now is None else now
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    target = section_file(folder, section)
    tmp = target.with_name(target.name + '.tmp%d' % os.getpid())
    tmp.write_text(json.dumps({'section': str(section), 'saved': now, 'quotas': quotas}), encoding='utf-8')
    os.replace(tmp, target)


def _same_section(a, b) -> bool:
    """Two section names that are one path spelled differently (the section is the state file's path)."""
    if not isinstance(a, str) or not a or not b:
        return False
    try:
        return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(str(b)))
    except (OSError, ValueError):
        return False


def others(folder, section, *, now=None) -> list:
    now = time.time() if now is None else now
    folder = Path(folder)
    if not folder.is_dir():
        return []
    mine = section_file(folder, section).name
    out = []
    for path in sorted(folder.glob('*.json')):
        if path.name == mine:
            continue
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except Exception:
            continue
        if not isinstance(data, dict) or not isinstance(data.get('quotas'), dict):
            continue                   # not a section: skipped, never a crash
        if _same_section(data.get('section'), section):
            continue                   # my own section under another spelling of the path (relative, other case, ..)
        if now - float(data.get('saved') or 0) > STALE_S:
            continue
        out.append(data['quotas'])
    return out


def view(own, others_list) -> dict:
    seen = copy.deepcopy(own)
    for other in others_list:
        for k, v in other.items():
            if k == 'model_cool':
                if 'model_cool' not in seen:
                    seen['model_cool'] = {}
                for m, t in v.items():
                    seen['model_cool'][m] = max(seen['model_cool'].get(m, 0), t)
            elif k == 'channel_cool':
                if 'channel_cool' not in seen:
                    seen['channel_cool'] = {}
                for c_id, t in v.items():
                    if isinstance(t, (int, float)):
                        seen['channel_cool'][c_id] = max(seen['channel_cool'].get(c_id, 0), t)
            elif k == 'dead':
                if 'dead' not in seen:
                    seen['dead'] = {}
                for c_id, info in v.items():
                    if c_id not in seen['dead']:
                        seen['dead'][c_id] = info
            elif isinstance(v, dict):
                if k not in seen:
                    seen[k] = {}
                for sub_k, sub_v in v.items():
                    if sub_k in LISTS and isinstance(sub_v, list):
                        if sub_k not in seen[k]:
                            seen[k][sub_k] = []
                        # joined, never sorted: own bookings are tuples, the file's are lists (20.11 00:37 a sort of
                        # the mix crashed the runner: "'<' not supported between list and tuple")
                        seen[k][sub_k] = list(seen[k][sub_k]) + list(sub_v)
                    elif sub_k == 'cool_until':
                        seen[k]['cool_until'] = max(seen[k].get('cool_until', 0), sub_v)
                    else:
                        if sub_k not in seen[k]:
                            seen[k][sub_k] = copy.deepcopy(sub_v)
            else:
                if k not in seen:
                    seen[k] = copy.deepcopy(v)
    return seen
