"""Best-effort, content-free bounded Private Codex generation timings."""
from __future__ import annotations

import json
import math
import os
import threading
import builtins
import uuid
from datetime import datetime, timezone
from pathlib import Path

MAX_BYTES = 256 * 1024
if not hasattr(builtins, '_echo_generation_telemetry_lock'):
    builtins._echo_generation_telemetry_lock = threading.RLock()
_LOCK = builtins._echo_generation_telemetry_lock


class GenerationTelemetryCollector:
    """Writes a strict numeric allowlist; no request or response data is accepted."""
    FIELDS = frozenset({'trace_id', 'at_utc', 'outcome', 'credentials_resolve_ms', 'client_setup_ms',
                        'request_create_ms', 'first_event_ms', 'first_delta_ms',
                        'completed_ms', 'total_ms'})

    def __init__(self, path):
        self.path = Path(path)

    def write(self, row):
        try:
            outcome = row.get('outcome')
            trace_id = row.get('trace_id')
            clean = {'trace_id': trace_id if isinstance(trace_id, str) and len(trace_id) == 32 and all(c in '0123456789abcdef' for c in trace_id) else uuid.uuid4().hex,
                     'at_utc': datetime.now(timezone.utc).isoformat(timespec='milliseconds'),
                     'outcome': outcome if isinstance(outcome, str) and outcome in {'success', 'cancelled', 'error'} else 'error'}
            for key in self.FIELDS - {'trace_id', 'at_utc', 'outcome'}:
                value = row.get(key)
                if type(value) in {int, float} and math.isfinite(value) and 0 <= value <= 86_400_000:
                    clean[key] = round(float(value), 3)
            payload = (json.dumps(clean, separators=(',', ':')) + '\n').encode('utf-8')
            if len(payload) > 2048:
                return False
            with _LOCK:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                size = self.path.stat().st_size if self.path.exists() else 0
                if size > MAX_BYTES:
                    self.path.unlink(missing_ok=True)
                    size = 0
                if size + len(payload) > MAX_BYTES and size:
                    backup = self.path.with_name(self.path.name + '.1')
                    if backup.exists() and backup.stat().st_size > MAX_BYTES:
                        backup.unlink()
                    os.replace(self.path, backup)
                with self.path.open('ab') as stream:
                    stream.write(payload)
            return True
        except Exception:
            return False


class GenerationTrace:
    """Offsets are elapsed milliseconds from trace start, not adjacent phase durations."""
    def __init__(self, collector, clock):
        self.collector, self.clock = collector, clock
        self.started = clock()
        self.row = {'trace_id': uuid.uuid4().hex}
        self._last = self.started
        self._finished = False

    def mark(self, name):
        if self._finished:
            return 0.0
        now = self.clock()
        elapsed = max(0.0, (now - self.started) * 1000)
        key = name + '_ms'
        if key not in GenerationTelemetryCollector.FIELDS or key in self.row:
            return 0.0
        self.row[key] = min(86_400_000.0, elapsed)
        phase = (now - self._last) * 1000
        self._last = now
        return phase

    def finish(self, outcome):
        if self._finished:
            return False
        self._finished = True
        try:
            self.row['total_ms'] = min(86_400_000.0, max(0.0, (self.clock() - self.started) * 1000))
            self.row['outcome'] = outcome
            return self.collector.write(self.row)
        except Exception:
            return False
