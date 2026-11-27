"""W5 instant, step «синтез»: the first portion is already spoken. ``PcmCache``: PCM16 of a cue on disk, keyed by the text, the voice and the
rate (sha256), under a size limit (the oldest read go first). ``cached(cache, render, text, voice, rate)`` looks in the cache before it
renders, and keeps what it rendered; ``prerender`` speaks the ``core`` of every bank row before the call (a tool on the laptop, SAPI is there).
A damaged file (odd length, a header that does not match) is a miss and is removed. Never raises on a read; writes go through a temporary
file. No word of a text is written anywhere but in the key's hash."""
from __future__ import annotations

import errno
import hashlib
import logging
import os
import struct
import threading
import time
from pathlib import Path

from . import degradation

logger = logging.getLogger('echo-sync')

MAGIC = b'ECP1'
_HEAD = struct.Struct('<4sII')            # magic, rate, length of the PCM
TRIM_EVERY_SECONDS = 60.0                 # W13 item 3: the background trim walks the directory at most this often


def key(text, voice, rate):
    return hashlib.sha256(('%s\0%s\0%d' % (' '.join(str(text or '').split()), voice or '', int(rate))).encode('utf-8')).hexdigest()


class PcmCache:
    def __init__(self, directory, *, max_bytes=200 * 2 ** 20, clock=time.monotonic):
        self.dir = Path(directory)
        self.max_bytes = max(1, int(max_bytes))
        self.clock, self._trimmed, self._pending, self._lock, self._fresh = clock, None, [], threading.Lock(), {}
        self._failed = False      # a failing write is told once per cache (one line in the call's log), never at every cue

    def path(self, text, voice, rate):
        return self.dir / (key(text, voice, rate) + '.pcm')

    def get(self, text, voice, rate):
        path = self.path(text, voice, rate)
        fresh = self._fresh.get(path.name)
        if fresh is not None:              # W13 item 3: rendered, its write still in the background
            return fresh
        try:
            data = path.read_bytes()
            magic, got_rate, n = _HEAD.unpack_from(data)
            pcm = data[_HEAD.size:]
            if magic != MAGIC or got_rate != int(rate) or n != len(pcm) or n % 2:
                raise ValueError('damaged')
            os.utime(path)                 # read: it is young again
            return pcm
        except FileNotFoundError:
            return None
        except Exception as error:         # noqa: BLE001 - damaged: a miss, and away with it
            degradation.note('pcm_cache', error, what='повреждённый файл')
            try:
                path.unlink()
            except Exception:              # noqa: BLE001
                pass
            return None

    def put(self, text, voice, rate, pcm, *, trim=True):
        pcm = bytes(pcm or b'')
        if not pcm or len(pcm) % 2 or len(pcm) + _HEAD.size > self.max_bytes:
            return False
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            path = self.path(text, voice, rate)
            tmp = path.with_name(path.name + '.%d.tmp' % os.getpid())
            tmp.write_bytes(_HEAD.pack(MAGIC, int(rate), len(pcm)) + pcm)
            os.replace(tmp, path)
            if trim:
                self._trim(keep=path)
            return True
        except Exception as error:         # noqa: BLE001
            self._write_failed(error)
            return False

    def _write_failed(self, error):
        """A write that failed (disk full, a locked directory) is not swallowed: ONE warning per cache names the cause (``disk_full`` for ENOSPC, else the exception's name); the cue is never held by it."""
        if self._failed:
            return
        self._failed = True
        reason = 'disk_full' if getattr(error, 'errno', None) == errno.ENOSPC else type(error).__name__
        logger.warning('echo-sync pcm_cache put failed reason=%s', reason)

    def put_later(self, text, voice, rate, pcm):
        """W13 item 3: write in a daemon thread, the trim at most once in TRIM_EVERY_SECONDS (the first write of the call trims). Never raises."""
        name = self.path(text, voice, rate).name
        self._fresh[name] = bytes(pcm)

        def run():
            try:
                self.put(text, voice, rate, pcm, trim=False)
                self._fresh.pop(name, None)
                now = self.clock()
                with self._lock:
                    due = self._trimmed is None or now - self._trimmed >= TRIM_EVERY_SECONDS
                    if due:
                        self._trimmed = now
                if due:
                    self._trim(keep=self.path(text, voice, rate))
            except Exception as error:     # noqa: BLE001
                self._write_failed(error)
        try:
            worker = threading.Thread(target=run, name='pcm-cache-put', daemon=True)
            with self._lock:
                self._pending = [t for t in self._pending if t.is_alive()] + [worker]
            worker.start()
        except Exception:                  # noqa: BLE001
            pass

    def flush(self, timeout=None):
        """Wait for the background writes (tests, the end of the call). True when none is left."""
        with self._lock:
            pending = list(self._pending)
        for worker in pending:
            worker.join(timeout)
        return not any(worker.is_alive() for worker in pending)

    def _files(self):
        found = []
        try:
            for p in self.dir.glob('*.pcm'):
                try:
                    st = p.stat()
                except Exception:          # noqa: BLE001 - gone meanwhile
                    continue
                found.append((st.st_mtime, st.st_size, p))
        except Exception:                  # noqa: BLE001
            return found
        return found

    def size(self):
        return sum(size for _, size, _ in self._files())

    def _trim(self, keep=None):
        files = sorted(self._files(), key=lambda f: f[0])
        total = sum(size for _, size, _ in files)
        for _, size, path in files:
            if total <= self.max_bytes:
                break
            if path == keep:
                continue
            try:
                path.unlink()
                total -= size
            except Exception:              # noqa: BLE001
                pass


CALL_KEEP = 8          # c24-c: the sound of the last cue texts of a call, kept in memory for their repeats


class CallMemo:
    """c24-c: the PCM a call has made, in memory, for the last CALL_KEEP texts: a portion said again unchanged is never synthesized again (no SAPI, no disk). The key is the whole text, the voice
    key (voice, ending, speech text) and the rate: another text («не» added, a digit changed) or another voice is another sound. Only a valid render is kept. ``reused``: how many repeats it served."""

    def __init__(self, keep=CALL_KEEP):
        import collections
        self.keep, self.kept, self.reused, self.rendered = max(1, int(keep)), collections.OrderedDict(), 0, 0
        self._lock = threading.Lock()

    def get(self, text, voice, rate):
        with self._lock:
            k = key(text, voice, rate)
            pcm = self.kept.get(k)
            if pcm is not None:
                self.kept.move_to_end(k)
                self.reused += 1
            return pcm

    def put(self, text, voice, rate, pcm):
        if not isinstance(pcm, (bytes, bytearray)) or not pcm or len(pcm) % 2:
            return
        with self._lock:
            k = key(text, voice, rate)
            self.kept[k] = bytes(pcm)
            self.kept.move_to_end(k)
            while len(self.kept) > self.keep:
                self.kept.popitem(last=False)


def cached(cache, render, text, voice, rate, memo=None):
    """The PCM of ``text``: from ``memo`` (this call's, c24-c), else from ``cache`` if it is there, else ``render(text)`` (kept for the next time). ``cache`` None: render only."""
    if memo is not None:
        pcm = memo.get(text, voice, rate)
        if pcm is not None:
            return pcm
        pcm = cached(cache, render, text, voice, rate)
        memo.rendered += 1
        memo.put(text, voice, rate, pcm)
        return pcm
    if cache is not None:
        pcm = cache.get(text, voice, rate)
        if pcm is not None:
            return pcm
    pcm = render(text)
    if cache is not None and pcm:
        cache.put_later(text, voice, rate, pcm)      # W13 item 3: the PCM goes back now, the write and the trim after it
    return pcm


def first_portion(answer):
    """The first cue the controller will say of ``answer`` as a base hit: the first of ``portioner.portions`` with the call's profile
    (``settings.CALL_SETTINGS``). Checked equal to what the real controller cued for all 81 rows of the test bank (report)."""
    from .portioner import portions                 # noqa: PLC0415
    from .settings import CALL_SETTINGS, resolve    # noqa: PLC0415
    try:
        cut = portions(str(answer or ''), resolve(CALL_SETTINGS))
        return str(cut[0]) if cut else ''
    except Exception as error:                      # noqa: BLE001
        degradation.note('pcm_cache.portion', error)
        return ''


def prerender(cache, render, bank, voice, rate, *, budget_s=None, clock=time.monotonic):
    """Speak the first portion of every bank row's answer (``first_portion``; the row's ``core`` too when it differs) into ``cache`` before the call. -> counts."""
    from .instant import core_of                    # noqa: PLC0415
    counts = {'rendered': 0, 'cached': 0, 'failed': 0}
    start = clock()
    for row in bank or ():
        if budget_s is not None and clock() - start > budget_s:
            break
        if not isinstance(row, dict):
            continue
        first = first_portion(row.get('answer', ''))
        for text in dict.fromkeys(t for t in (first, row.get('core') or core_of(row.get('answer', ''))) if t):
            if cache.get(text, voice, rate) is not None:
                counts['cached'] += 1
                continue
            try:
                pcm = render(text)
                counts['rendered' if pcm and cache.put(text, voice, rate, pcm) else 'failed'] += 1
            except Exception:                       # noqa: BLE001
                counts['failed'] += 1
    return counts


def from_settings(settings):
    directory = (settings or {}).get('pcm_cache_dir') or ''
    return PcmCache(directory, max_bytes=int((settings or {}).get('pcm_cache_mb', 200)) * 2 ** 20) if directory else None
