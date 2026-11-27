"""U07-S2: the recorder of one call's sound (opt-in, the laptop only, nothing leaves it). Not wired to the call yet (U07-S3 does that, behind ``pcm_record``).

One directory per call: ``<root>/<call_id>/<channel>.wav`` (16-bit mono PCM, 24 kHz: the phone's mic, the cues sent to it) and ``timeline.jsonl`` (one JSON line per event: open, channel (where a file starts on the call's clock), gap, cap, no_space, failed:<Type>, close).
The call never waits for the disk: ``write`` only puts the packet on a bounded queue (a full queue drops the packet and counts it); a writer thread does the file work. A disk fault (full: ``no_space``; any other: ``failed:<Type>``) or the cap stops the recording, never the call, and nothing here raises into it.
A channel keeps real time: when a packet arrives more than DRIFT_MS after the sound written so far, the hole is filled with silence and a ``gap`` line says where. The WAV header is written with size 0 and fixed at close (``fix_header`` also repairs the file of a call that died).
``prune`` keeps the newest calls and at most so many MB."""
import errno
import json
import queue
import shutil
import struct
import threading
import time
from pathlib import Path

from .timer_policy import CLOSE_WAIT_S

RATE = 24000
BYTES_PER_SAMPLE = 2
DRIFT_MS = 40                   # a packet later than this after the written sound is a gap (silence fills it, a line says it)
QUEUE_PACKETS = 4000            # about 80 s of 20 ms packets; a full queue drops
MAX_FILL_MS = 60000             # one gap is filled by at most this much silence
HEADER = 44
TIMELINE = 'timeline.jsonl'
ON, CAP, NO_SPACE = 'on', 'cap', 'no_space'


def minutes(cap_mb, channels=1):
    """How many minutes of the call a cap of ``cap_mb`` MB holds: 48,000 bytes a second per channel (the microphone alone: 1; the microphone and the cues together: 2 - the cap is for both). 200 MB: 72.8 and 36.4."""
    return cap_mb * 1024 * 1024 / (RATE * BYTES_PER_SAMPLE * max(1, channels)) / 60


def _header(data_bytes):
    return (b'RIFF' + struct.pack('<I', 36 + data_bytes) + b'WAVEfmt ' + struct.pack('<IHHIIHH', 16, 1, 1, RATE, RATE * BYTES_PER_SAMPLE, BYTES_PER_SAMPLE, 16)
            + b'data' + struct.pack('<I', data_bytes))


def fix_header(path):
    """Set the RIFF and data sizes of a WAV from the file length (a recording cut short has size 0 there). Returns the data bytes, or -1 when it is not our file."""
    path = Path(path)
    try:
        with open(path, 'r+b') as f:
            head = f.read(HEADER)
            if len(head) < HEADER or head[:4] != b'RIFF' or head[36:40] != b'data':
                return -1
            data = max(0, path.stat().st_size - HEADER)
            data -= data % BYTES_PER_SAMPLE
            f.seek(0)
            f.write(_header(data))
            f.truncate(HEADER + data)
            return data
    except OSError:
        return -1


class CallAudio:
    def __init__(self, root, call_id, cap_mb=200, opener=open, clock=time.monotonic):
        self.dir = Path(root) / str(call_id)
        self.cap_bytes = int(cap_mb * 1024 * 1024)
        self._open = opener
        self._clock = clock
        self._q = queue.Queue(QUEUE_PACKETS)
        self._files = {}            # channel -> [file, data bytes written, t of the first packet]
        self._state = ON
        self._bytes = 0
        self._gaps = 0
        self._dropped = 0
        self._closed = False
        self._t0 = clock()
        self._thread = threading.Thread(target=self._run, name='call-audio', daemon=True)
        self._thread.start()
        self._put(('line', {'ev': 'open', 'call': str(call_id), 'rate': RATE, 'drift_ms': DRIFT_MS, 'cap_mb': cap_mb}))

    # ---- the call's side: cheap and silent ----
    @property
    def state(self):
        return self._state

    def summary(self):
        """What call_close may carry: numbers and labels only."""
        return {'state': self._state, 'bytes': self._bytes, 'gaps': self._gaps, 'dropped': self._dropped}

    def _put(self, item):
        try:
            self._q.put_nowait(item)
            return True
        except queue.Full:
            return False

    def write(self, channel, pcm, t=None):
        """Queue one packet of 16-bit mono PCM heard at ``t`` (seconds of the injected clock; now when None). Never raises, never waits."""
        if self._closed or self._state != ON or not pcm:
            return
        if not self._put(('pcm', channel, bytes(pcm), self._clock() if t is None else t)):
            self._dropped += 1

    def mark(self, event, **fields):
        """A line of the timeline from the call (a cue played, a question): numbers and labels only."""
        if not self._closed and self._state == ON:
            fields['ev'] = event
            fields['t'] = round(self._clock() - self._t0, 3)
            self._put(('line', fields))

    def close(self):
        """Drain, fix the headers, write the close line. Safe to call twice."""
        if self._closed:
            return self.summary()
        self._closed = True
        self._q.put(('end',))
        self._thread.join(CLOSE_WAIT_S)
        return self.summary()

    # ---- the writer thread ----
    def _line(self, fields):
        if 't' not in fields:
            fields['t'] = round(self._clock() - self._t0, 3)
        with self._open(self.dir / TIMELINE, 'a', encoding='utf-8') as f:
            f.write(json.dumps(fields, ensure_ascii=False) + '\n')

    def _fault(self, exc):
        full = isinstance(exc, OSError) and (exc.errno == errno.ENOSPC or getattr(exc, 'winerror', None) == 112)
        self._state = NO_SPACE if full else 'failed:' + type(exc).__name__

    def _channel(self, name, t):
        rec = self._files.get(name)
        if rec is None:
            f = self._open(self.dir / (name + '.wav'), 'wb')
            f.write(_header(0))
            rec = self._files[name] = [f, 0, t]
            self._line({'ev': 'channel', 'ch': name, 't': round(t - self._t0, 3)})      # where this file starts on the call's clock: the files line up with each other and with the marks
        return rec

    def _pcm(self, name, data, t):
        rec = self._channel(name, t)
        f, written, t_first = rec
        per_ms = RATE * BYTES_PER_SAMPLE / 1000.0
        late_ms = (t - t_first) * 1000.0 - written / per_ms
        if late_ms > DRIFT_MS:
            self._gaps += 1
            fill = int(min(late_ms, MAX_FILL_MS) * RATE / 1000.0) * BYTES_PER_SAMPLE
            if self._bytes + fill + len(data) > self.cap_bytes:
                fill = 0
            self._line({'ev': 'gap', 'ch': name, 'at_ms': int(written / per_ms), 'ms': int(late_ms)})
            if fill:
                f.write(b'\0' * fill)
                rec[1] += fill
                self._bytes += fill
        if self._bytes + len(data) > self.cap_bytes:
            self._state = CAP
            self._line({'ev': CAP, 'bytes': self._bytes})
            return
        f.write(data)
        rec[1] += len(data)
        self._bytes += len(data)

    def _run(self):
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            self._fault(e)
        while True:
            item = self._q.get()
            if item[0] == 'end':
                break
            if self._state != ON:
                continue                       # stopped: drain without touching the disk
            try:
                if item[0] == 'pcm':
                    self._pcm(item[1], item[2], item[3])
                else:
                    self._line(item[1])
            except Exception as e:
                self._fault(e)
                try:
                    self._line({'ev': self._state, 'bytes': self._bytes})
                except Exception:
                    pass
        self._finish()

    def _finish(self):
        for rec in self._files.values():
            try:
                rec[0].close()
            except Exception:
                pass
        for name in self._files:
            fix_header(self.dir / (name + '.wav'))
        try:
            self._line({'ev': 'close', 'state': self._state, 'bytes': self._bytes, 'gaps': self._gaps, 'dropped': self._dropped})
        except Exception:
            pass


def _size(path):
    return sum(p.stat().st_size for p in path.rglob('*') if p.is_file())


def prune(root, keep_calls=20, max_mb=2048, protect=None):
    """Remove the oldest call directories under ``root`` until at most ``keep_calls`` stay and they weigh at most ``max_mb`` MB; ``protect`` (a call id) is never removed. Returns the removed names."""
    root = Path(root)
    try:
        calls = sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: (p.stat().st_mtime, p.name))
    except OSError:
        return []
    sizes = {p: _size(p) for p in calls}
    total = sum(sizes.values())
    removed = []
    for p in calls:
        if len(calls) - len(removed) <= keep_calls and total <= max_mb * 1024 * 1024:
            break
        if p.name == str(protect):
            continue
        try:
            shutil.rmtree(p)
        except OSError:
            continue
        total -= sizes[p]
        removed.append(p.name)
    return removed
