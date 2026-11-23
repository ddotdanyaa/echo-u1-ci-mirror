"""<id> foundation: one shared ledger of key usage per channel registry folder. Each task state publishes its own channel quotas as one section file (one writer per state: its checkpoint lock); a call chooses on the union of its own quotas and the other sections; old sections stop counting; an unreadable file is skipped, never a crash."""
import contextlib
import copy
import hashlib
import json
import os
import time
from pathlib import Path

STALE_S = 2 * 86400
COOL_STALE_S = 1800          # a foreign section older than this keeps no cooling mark of ours
FOREIGN_OVERLOAD_S = 300     # a foreign model mark (a 503) holds this section at most this long
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
        age = now - float(data.get('saved') or 0)
        if age > STALE_S:
            continue
        quotas = data['quotas']
        if age > COOL_STALE_S:
            quotas = _without_cooling(quotas)      # a section nobody has written for 30 minutes holds nobody
        out.append(quotas)
    return out


def _without_cooling(quotas) -> dict:
    """``quotas`` of a stale section without its cooling marks (its bookings still count)."""
    out = {}
    for k, v in quotas.items():
        if k in ('model_cool', 'channel_cool', 'day_probe'):
            continue
        if isinstance(v, dict) and 'cool_until' in v:
            v = {sk: sv for sk, sv in v.items() if sk != 'cool_until'}
        out[k] = v
    return out


GATE_NAME = 'day_gate.json'      # not a section (no 'quotas'): others() skips it
DAY_ASK_PROBE_S = 1200           # W-gemma2 3: a channel closed by the day's mark is probed by ONE slicer ask per 20 minutes


def _gate_read(folder) -> dict:
    try:
        data = json.loads((Path(folder) / GATE_NAME).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    table = data.get('gate') if isinstance(data, dict) else None
    return {k: v for k, v in table.items() if isinstance(v, dict)} if isinstance(table, dict) else {}


def _gate_write(folder, table) -> None:
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / GATE_NAME
    tmp = target.with_name(target.name + '.tmp%d' % os.getpid())
    tmp.write_text(json.dumps({'gate': table}), encoding='utf-8')
    os.replace(tmp, target)


def gate_closed(folder, *, since=None) -> set:
    """Ids of the channels the slicer asks know as closed by the day's mark (until a probe of theirs answers 200).
    ``since``: {channel id: start of its provider's day}: an entry older than that day is of yesterday."""
    since = since or {}
    return {cid for cid, row in _gate_read(folder).items()
            if isinstance(row.get('at'), (int, float)) and row['at'] >= since.get(cid, 0)}


GATE_LOCK_WAIT_S = 5.0           # a gate update waits this long for the other instance's lock
GATE_LOCK_STALE_S = 10.0         # a lock file older than this is a dead holder's: it is broken


@contextlib.contextmanager
def _gate_lock(folder):
    """The read-change-write of day_gate.json is one step: a lock file made with O_EXCL (works across processes on every
    platform). A lock older than GATE_LOCK_STALE_S is a crashed holder's; after GATE_LOCK_WAIT_S the step goes on without
    the lock (an aid must not hang a call: the worst case is the old race, one extra probe)."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (GATE_NAME + '.lock')
    deadline = time.monotonic() + GATE_LOCK_WAIT_S
    held = False
    while True:
        try:
            os.close(os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            held = True
            break
        except FileExistsError:
            try:
                if time.time() - path.stat().st_mtime > GATE_LOCK_STALE_S:
                    # break it by a unique name: of two waiters only one rename succeeds; the stolen file is looked at again
                    # (a fresh one a third party made in between is put back unless the path is taken again): a narrow window
                    mine = path.with_name(path.name + '.stale%d' % os.getpid())
                    os.replace(str(path), str(mine))
                    try:
                        if time.time() - mine.stat().st_mtime <= GATE_LOCK_STALE_S and not path.exists():
                            os.replace(str(mine), str(path))      # it was a live holder's new lock: give it back
                        else:
                            mine.unlink()
                    except OSError:
                        pass
                    continue
            except OSError:
                continue
        except OSError:
            break
        if time.monotonic() >= deadline:
            break
        time.sleep(0.01)
    try:
        yield
    finally:
        if held:
            try:
                path.unlink()
            except OSError:
                pass


def gate_note(folder, channel_id, *, now=None) -> None:
    """The channel answered a daily 429 (or is seen closed by the day's mark): the next probe is DAY_ASK_PROBE_S away."""
    now = time.time() if now is None else now
    with _gate_lock(folder):
        table = _gate_read(folder)
        row = table.get(channel_id)
        table[channel_id] = {'at': now, 'probe_at': row['probe_at'] if isinstance(row, dict)
                             and isinstance(row.get('probe_at'), (int, float)) else now}
        _gate_write(folder, table)


def gate_claim(folder, channel_id, *, now=None) -> bool:
    """True for the ONE ask that may probe this closed channel now (the claim is read and written under the lock of the
    folder both instances share, before the request goes out); False while the last probe is under DAY_ASK_PROBE_S old."""
    now = time.time() if now is None else now
    with _gate_lock(folder):
        table = _gate_read(folder)
        row = table.get(channel_id)
        last = row.get('probe_at') if isinstance(row, dict) else None
        if isinstance(last, (int, float)) and now - last < DAY_ASK_PROBE_S:
            return False
        table[channel_id] = {'at': row.get('at', now) if isinstance(row, dict) else now, 'probe_at': now}
        _gate_write(folder, table)
        return True


def gate_clear(folder, channel_id) -> None:
    with _gate_lock(folder):
        table = _gate_read(folder)
        if table.pop(channel_id, None) is not None:
            _gate_write(folder, table)


def view(own, others_list, *, now=None) -> dict:
    now = time.time() if now is None else now
    seen = copy.deepcopy(own)
    for other in others_list:
        for k, v in other.items():
            if k == 'model_cool':
                if 'model_cool' not in seen:
                    seen['model_cool'] = {}
                for m, t in v.items():
                    if isinstance(t, (int, float)) and not isinstance(t, bool):
                        # a foreign mark (mostly a 503 of the model) holds us FOREIGN_OVERLOAD_S at most; our own
                        # calls will cool it for longer when the model is still bad for us. The shared log cannot tell
                        # a 503 from a per-model daily mark, so a foreign DAILY model mark also holds us 5 minutes
                        # at most (accepted simplification): our own first call probes it and sets our own mark
                        t = min(t, now + FOREIGN_OVERLOAD_S)
                        seen['model_cool'][m] = max(seen['model_cool'].get(m, 0), t)
            elif k == 'day_probe' and isinstance(v, dict):
                table = seen.setdefault('day_probe', {})
                for key, row in v.items():
                    mine = table.get(key)
                    if not isinstance(mine, dict):
                        table[key] = copy.deepcopy(row)
                    elif isinstance(row, dict) and isinstance(row.get('flight'), (int, float)):
                        mine['flight'] = max(mine.get('flight') or 0, row['flight'])
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
