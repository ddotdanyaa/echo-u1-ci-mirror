"""U78 журнал деградации: every failure that a guard swallowed on the way to an optional capability (the bank, the law base, the ear, SAPI, the
PCM cache, the diagnostic audio) is written here, and the check before a call prints «готово: X» or «недоступно: X — причина» for each.
``note`` never raises and keeps the exception TYPE only (the message can carry the listener's words, a URL or a token). Process-wide, thread-safe,
bounded (``MAX_COMPONENTS``). ``python -m echo_sync.degradation`` runs the default probes and prints the lines (exit 1 if any is unavailable)."""
from __future__ import annotations

import importlib
import sys
import threading
import time

MAX_COMPONENTS = 200
_lock = threading.Lock()
_journal = {}                                    # component -> row


def _reason(error):
    try:
        if isinstance(error, BaseException):
            return type(error).__name__
        return str(error or 'unspecified').split()[0][:40] if str(error or '').strip() else 'unspecified'
    except Exception:                            # noqa: BLE001
        return 'unspecified'


def note(component, error=None, *, what=''):
    """Record one swallowed failure of ``component``. Never raises."""
    try:
        name, now = str(component)[:80], time.time()
        row_what = what if isinstance(what, str) else ''
        with _lock:
            row = _journal.get(name)
            if row is None:
                if len(_journal) >= MAX_COMPONENTS:
                    return
                _journal[name] = {'component': name, 'reason': _reason(error), 'what': row_what[:80], 'first': now, 'last': now, 'count': 1}
            else:
                row.update(reason=_reason(error), last=now, count=row['count'] + 1)
                if row_what:
                    row['what'] = row_what[:80]
    except Exception:                            # noqa: BLE001 - the journal never costs a call
        pass


def snapshot():
    with _lock:
        return [dict(r) for r in _journal.values()]


def reset():
    with _lock:
        _journal.clear()


def _line(row):
    extra = f' ({row["what"]})' if row.get('what') else ''
    times = f', раз: {row["count"]}' if row.get('count', 1) > 1 else ''
    return f'недоступно: {row["component"]} — {row["reason"]}{extra}{times}'


def _probe(name, fn):
    """(ok, line) of one probe: an exception or a false answer is «недоступно», and is written to the journal too."""
    try:
        if fn() is not False:
            return True, f'готово: {name}'
        note(name, 'probe_false')
        return False, f'недоступно: {name} — probe_false'
    except Exception as error:                   # noqa: BLE001
        note(name, error, what='проверка')
        return False, f'недоступно: {name} — {_reason(error)}'


def readiness(checks=None):
    """Lines for every probe in ``checks`` (name -> callable), then one «недоступно» line for each journal entry no probe has answered for."""
    lines, answered = [], set()
    for name, fn in (checks or {}).items():
        ok, line = _probe(name, fn)
        answered.add(name)
        lines.append(line)
        if ok:
            with _lock:
                _journal.pop(name, None)         # it works now: the old note is stale
    return lines + [_line(r) for r in snapshot() if r['component'] not in answered]


def check_before_call(checks=None):
    """(all_ready, lines): the check before a call."""
    lines = readiness(checks)
    return all(line.startswith('готово: ') for line in lines), lines


def _importable(module):
    return lambda: importlib.import_module(module) and True


def default_checks():
    """Cheap probes of the optional capabilities; nothing is loaded that a call would not load."""
    return {'instant': _importable('echo_sync.instant'), 'law_base': _importable('echo_sync.law_base'), 'materials': _importable('echo_sync.materials'),
            'local_ear': _importable('echo_sync.local_ear'), 'vad_silero': _importable('echo_sync.vad_silero'), 'sherpa_onnx': _importable('sherpa_onnx'),
            'pcm_cache': _importable('echo_sync.pcm_cache'), 'diag_audio': lambda: __import__('echo_sync.diagnostics', fromlist=['x']).DiagnosticAudio().missing() == []}


def main(argv=None):
    ok, lines = check_before_call(default_checks())
    print('\n'.join(lines))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
