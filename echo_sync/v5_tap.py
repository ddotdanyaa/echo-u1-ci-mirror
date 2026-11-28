"""V5 step 1a: one entry and the record, in shadow, always (no switch; the size is ``v5_tap_mb``).

Shadow: every public entry through which the transport, the ear and the helper threads reach the controller (``ENTRIES``, and the read-only ``LOCKED``) passes
through ONE re-entrant lock, so that two entries never run inside the controller at the same time. Every outermost call of ``ENTRIES`` is written as an input
and every action dictionary it returns as an effect, in the record of contract 1 (contracts/v5/01_event.md: v 2; id, kind, key, rev, t_event, t_seen, source,
payload, causes), JSON lines, next to the call journal (logs/echo_calls/<stamp>-<call id>.v5tap.jsonl). The decisions are untouched: the wrappers call the
method that was there and return what it returned (an exception goes through as it came).

The contract has no kind for «a call of the old controller», so both are ``capability`` records of ``["journal"]`` (its ``flags`` is the one free object of
the contract): ``source`` journal:tap_in / journal:tap_out, ``flags.tap`` in | out | raised | open, the entry, its arguments and the action in ``flags``; an
effect names the input that returned it in ``causes``. ``rev`` is the record's own id, so no record is a repeat of another.

Bounded: two halves of ``max_bytes`` / 2 (a ring): when the current file would outgrow its half it becomes ``....v5tap.prev.jsonl`` (the older half is gone) and
a fresh one begins with a header marked ``truncated``. The newest ``KEEP_FILES`` calls stay. A record that cannot be written switches the record off
(``failure``), never the call.
"""
import functools
import inspect
import json
import logging
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path

logger = logging.getLogger('echo-sync')

# What the transport, the ear and the job threads call on the controller and what changes its state: recorded and locked.
ENTRIES = ('begin_call', 'tick', 'provider', 'speech_started', 'local_onset', 'local_speech', 'mic_packet', 'input_vad', 'input_fault', 'cue_started', 'playback_done',
           'cue_abandoned', 'partial_quiet', 'delivery_sent', 'lookup_result', 'answer_diagnosed', 'prepare_speech',
           'ear_failed', 'ear_onset', 'ear_progress', 'ear_heard', 'ear_partial', 'ear_piece', 'ear_speech', 'tempo_heard',
           'fast_prepare', 'fast_feed', 'fast_stable', 'fast_stable_piece', 'fast_lost', 'fast_job_lost', 'v5_stale')
# What they ask of it (a question, no input): locked, not written.
LOCKED = ('authorized', 'diagnostic_line', 'first_cue_hold', 'prefetch_candidate', 'hold', 'heard_only_locally', 'tempo_old_news', 'pace_on', 'state',
          'answer_deadline', 'refuse_deadline', 'fast_questions', 'fast_exchanges', 'fast_carry', 'fast_in_play')
KEEP_FILES = 6                  # calls: the newest this many stay in the folder
DEFAULT_MB = 48                 # a 3-hour call is about 65 MB of lines: the newest 2 hours stay
MAX_TEXT, MAX_ITEMS, MAX_DEPTH = 2000, 60, 6
_NAME = re.compile(r'^\d{8}-\d{6}-[0-9A-Za-z]{1,32}\.v5tap(\.prev)?\.jsonl$')


def plain(value, depth=0):
    """``value`` as JSON: what cannot be is its short repr, bytes are their length, a long text is cut."""
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if value == value and abs(value) != float('inf') else repr(value)
    if isinstance(value, str):
        return value if len(value) <= MAX_TEXT else value[:MAX_TEXT] + '…'
    if isinstance(value, (bytes, bytearray)):
        return {'bytes': len(value)}
    if depth >= MAX_DEPTH:
        return repr(value)[:80]
    if isinstance(value, dict):
        return {str(k)[:80]: plain(v, depth + 1) for k, v in list(value.items())[:MAX_ITEMS]}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [plain(v, depth + 1) for v in list(value)[:MAX_ITEMS]]
    return repr(value)[:200]


def actions_of(result):
    """The action dictionaries of what an entry returned: a list of them, or one."""
    if isinstance(result, dict):
        return [result]
    return [x for x in result if isinstance(x, dict)] if isinstance(result, (list, tuple)) else []


class Tap:
    def __init__(self, path, call_id, clock, max_bytes, mode='shadow'):
        self.path, self.call_id, self.clock, self.mode = Path(path), call_id, clock, mode
        self.prev = self.path.with_name(self.path.name.replace('.v5tap.jsonl', '.v5tap.prev.jsonl'))
        self.half = max(1, int(max_bytes) // 2)
        self.lock = threading.RLock()      # THE lock: every entry, and the record, under it
        self.depth = 0                     # recorded entries inside each other: only the outermost is an input
        self.failure = None                # the type name of the error that switched the record off
        self.next_id = self.size = 0
        self.origin = clock()
        self._file = None
        self._open(first=True)

    # -- the record ---------------------------------------------------------------------------------------------------------

    def _ms(self):
        return max(0, int((self.clock() - self.origin) * 1000))

    def _open(self, first=False):
        self._file = open(self.path, 'ab')
        self.size = 0
        payload = {'wall': datetime.now().astimezone().isoformat(timespec='seconds'), 'flags': {'tap': 'open', 'mode': self.mode, 'call': self.call_id, 'half_bytes': self.half}}
        if not first:
            payload['truncated'] = True
        self._write('capability', ['server'], 'server', payload, [])

    def _rotate(self):
        self._file.close()
        os.replace(self.path, self.prev)
        self._open()

    def _line(self, kind, key, source, payload, causes):
        n, t = self.next_id, self._ms()
        return n, (json.dumps({'v': 2, 'id': n, 'kind': kind, 'key': key, 'rev': n, 't_event': t, 't_seen': t, 'source': source, 'payload': payload, 'causes': causes},
                              ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n').encode('utf-8')

    def _write(self, *record):
        n, line = self._line(*record)
        if self.size and self.size + len(line) > self.half:      # the half is full: it becomes the older one, the fresh one starts with a header
            self._rotate()
            n, line = self._line(*record)
        self._file.write(line)
        self._file.flush()
        self.size += len(line)
        self.next_id = n + 1
        return n

    def _put(self, source, payload, causes):
        if self._file is None:
            return None
        try:
            return self._write('capability', ['journal'], source, payload, causes)
        except Exception as error:      # noqa: BLE001 - the record never costs the call
            self.failure = type(error).__name__
            logger.warning('echo-sync v5_tap switched off reason=%s', self.failure)
            try:
                self._file.close()
            except Exception:       # noqa: BLE001
                pass
            self._file = None
            return None

    def entered(self, name, args, kw):
        return self._put('journal:tap_in', {'reason': name, 'flags': {'tap': 'in', 'entry': name, 'args': plain(args), 'kw': plain(kw), 'thread': threading.current_thread().name}}, [])

    def returned(self, name, iid, result):
        if iid is None:
            return
        found = actions_of(result)
        for n, action in enumerate(found):
            self._put('journal:tap_out', {'reason': name, 'flags': {'tap': 'out', 'entry': name, 'action': plain(action), 'n': n, 'of': len(found)}}, [iid])

    def raised(self, name, iid, error):
        if iid is not None:
            self._put('journal:tap_out', {'reason': name, 'flags': {'tap': 'raised', 'entry': name, 'error': type(error).__name__}}, [iid])

    def note(self, source, reason, flags):
        """A line of another V5 part beside the record (the answer gate's verdict, ``journal:v5_gate``): a ``capability`` of ``["journal"]``, under the lock."""
        with self.lock:
            return self._put(source, {'reason': str(reason)[:200], 'flags': plain(flags)}, [])

    def close(self):
        with self.lock:
            file, self._file = self._file, None
            if file is not None:
                try:
                    file.close()
                except Exception:       # noqa: BLE001
                    pass

    # -- the one entry ------------------------------------------------------------------------------------------------------

    def wrap(self, name, method, record):
        @functools.wraps(method)
        def entry(*args, **kw):
            with self.lock:
                if not record:
                    return method(*args, **kw)
                if self.depth:      # an entry called from inside an entry: part of that input
                    self.depth += 1
                    try:
                        return method(*args, **kw)
                    finally:
                        self.depth -= 1
                iid = self.entered(name, args, kw)
                self.depth = 1
                try:
                    result = method(*args, **kw)
                except BaseException as error:
                    self.raised(name, iid, error)
                    raise
                finally:
                    self.depth = 0
                self.returned(name, iid, result)
                return result
        entry._v5_tap = True
        return entry


def prune(directory, keep, own):
    """The newest ``keep`` calls of this folder's own kind stay (by modification time of the call's newest file); anything else is not ours."""
    calls = {}
    with os.scandir(directory) as scan:
        for e in scan:
            if _NAME.match(e.name) and e.is_file(follow_symlinks=False):
                base = e.name.replace('.prev.', '.')
                calls.setdefault(base, []).append(e)
    ranked = sorted(calls, key=lambda base: (max(x.stat(follow_symlinks=False).st_mtime for x in calls[base]), base))
    for base in ranked[:max(0, len(ranked) - max(1, keep))]:
        if base != own:
            for e in calls[base]:
                try:
                    os.remove(e.path)
                except OSError:
                    pass


def attach(controller, settings, directory, call_id, *, clock=None, max_bytes=None, keep=KEEP_FILES):
    """The tap of this call, or None: there is no folder, or the folder cannot be made. Wraps the instance's own entries in
    place (the class is not touched); call it before anything keeps a method of the controller. An instance-level override that is a plain function is wrapped too."""
    if not directory:
        return None
    try:
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        ident = re.sub(r'[^0-9A-Za-z]', '', str(call_id))[:32] or 'call'
        path = directory / f'{datetime.now().strftime("%Y%m%d-%H%M%S")}-{ident}.v5tap.jsonl'
        mb = (settings or {}).get('v5_tap_mb', DEFAULT_MB)
        tap = Tap(path, ident, clock or time.monotonic, max_bytes if max_bytes is not None else int(mb) * 1024 * 1024)
        prune(directory, keep, path.name)
    except Exception as error:      # noqa: BLE001 - a call opens without it
        logger.warning('echo-sync v5_tap unavailable type=%s', type(error).__name__)
        return None
    cls = type(controller)
    for names, record in ((ENTRIES, True), (LOCKED, False)):
        for name in names:
            static = inspect.getattr_static(cls, name, None)
            if inspect.isfunction(static) and not inspect.iscoroutinefunction(static):
                own = vars(controller).get(name)
                if own is None:
                    setattr(controller, name, tap.wrap(name, getattr(controller, name), record))
                elif callable(own) and not inspect.iscoroutinefunction(own) and not getattr(own, '_v5_tap', False):
                    setattr(controller, name, tap.wrap(name, own, record))
    return tap
