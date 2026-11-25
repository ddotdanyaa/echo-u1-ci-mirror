"""Best-effort, bounded, content-free SAPI latency traces."""
from __future__ import annotations

import json
import os
import threading
import uuid
import contextvars
import builtins
import math
import re
from datetime import datetime, timezone
from pathlib import Path

MAX_BYTES = 256 * 1024
if not hasattr(builtins, '_echo_sapi_telemetry_locks'):
    builtins._echo_sapi_telemetry_locks = (threading.Lock(), {})
_LOCKS_GUARD, _PATH_LOCKS = builtins._echo_sapi_telemetry_locks
_CURRENT_TRACE = contextvars.ContextVar('echo_sapi_trace', default=None)
_ERROR_CODES = frozenset({
    'bad_text', 'windows_only', 'worker_script_missing', 'worker_start_failed',
    'worker_timeout', 'worker_write_timeout', 'worker_write_failed',
    'worker_protocol_closed_or_oversized', 'worker_protocol_invalid_json',
    'worker_protocol_invalid_shape', 'worker_ready_mismatch', 'worker_response_mismatch',
    'worker_voice_mismatch', 'wav_format_mismatch', 'wav_empty_or_truncated',
    'wav_invalid', 'output_file_failed', 'synthesis_failed', 'bad_request',
    'bad_output_path', 'other',
})


def _path_lock(path: Path):
    key = os.path.normcase(str(path.resolve()))
    with _LOCKS_GUARD:
        return _PATH_LOCKS.setdefault(key, threading.RLock())


class TtsLatencyCollector:
    ALLOWED_FIELDS = frozenset({
        'trace_id', 'at_utc', 'total_ms', 'lock_wait_ms', 'startup_ms',
    'write_wait_ms', 'synth_wait_ms', 'validate_ms', 'fallback_ms', 'fallback',
        'cold_warm', 'outcome', 'error_code',
    })

    def __init__(self, path, *, max_bytes=MAX_BYTES):
        self.path = Path(path)
        self.max_bytes = min(MAX_BYTES, max(512, int(max_bytes)))
        self._lock = _path_lock(self.path)

    def write(self, row):
        try:
            clean = {'trace_id': row.get('trace_id') if isinstance(row.get('trace_id'), str)
                     and re.fullmatch(r'[0-9a-f]{32}', row.get('trace_id')) else uuid.uuid4().hex,
                     'at_utc': row.get('at_utc') if isinstance(row.get('at_utc'), str)
                     and re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}\+00:00', row.get('at_utc'))
                     else datetime.now(timezone.utc).isoformat(timespec='milliseconds'),
                     'fallback': row.get('fallback') is True,
                     'outcome': row.get('outcome') if isinstance(row.get('outcome'), str)
                     and row.get('outcome') in {'success', 'error', 'fallback_error'} else 'error'}
            if isinstance(row.get('cold_warm'), str) and row.get('cold_warm') in {'cold', 'warm'}:
                clean['cold_warm'] = row['cold_warm']
            if isinstance(row.get('error_code'), str) and row.get('error_code') in _ERROR_CODES:
                clean['error_code'] = row['error_code']
            for key in ('total_ms', 'lock_wait_ms', 'startup_ms', 'write_wait_ms', 'synth_wait_ms', 'validate_ms', 'fallback_ms'):
                value = row.get(key)
                if type(value) in {int, float} and math.isfinite(value) and 0 <= value <= 86_400_000:
                    clean[key] = round(float(value), 3)
            line = json.dumps(clean, ensure_ascii=True, separators=(',', ':')) + '\n'
            payload = line.encode('utf-8')
            if len(payload) > min(2048, self.max_bytes):
                return False
            with self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                try:
                    size = self.path.stat().st_size
                except FileNotFoundError:
                    size = 0
                if size > self.max_bytes:
                    self.path.unlink(missing_ok=True)
                    size = 0
                if size + len(payload) > self.max_bytes and size:
                    backup = self.path.with_name(self.path.name + '.1')
                    try:
                        if size <= self.max_bytes:
                            os.replace(self.path, backup)
                        else:
                            return False
                    except OSError:
                        return False
                with self.path.open('ab') as stream:
                    stream.write(payload)
        except Exception:
            # Telemetry must never change synthesis or fallback behavior.
            return False
        return True


class TtsLatencyTrace:
    def __init__(self, collector):
        import time
        self.collector = collector
        self.trace_id = uuid.uuid4().hex
        self.started = time.monotonic()
        self.row = {
            'trace_id': self.trace_id,
            'at_utc': datetime.now(timezone.utc).isoformat(timespec='milliseconds'),
            'fallback': False,
        }
        self._finished = False

    def set(self, key, value):
        if key in TtsLatencyCollector.ALLOWED_FIELDS and key not in {'trace_id', 'at_utc', 'total_ms', 'outcome'}:
            if key.endswith('_ms'):
                try:
                    value = round(max(0.0, float(value)), 3)
                except (TypeError, ValueError):
                    return
            self.row[key] = value

    def finish(self, outcome, error_code=None):
        import time
        if self._finished:
            return None
        self._finished = True
        self.row['total_ms'] = round(max(0.0, (time.monotonic() - self.started) * 1000), 3)
        self.row['outcome'] = outcome if isinstance(outcome, str) and outcome in {'success', 'error', 'fallback_error'} else 'error'
        if error_code is not None:
            self.row['error_code'] = error_code if isinstance(error_code, str) and error_code in _ERROR_CODES else 'other'
        try:
            return self.collector.write(self.row)
        except Exception:
            return False


def current_trace():
    return _CURRENT_TRACE.get()


def use_trace(trace):
    return _CURRENT_TRACE.set(trace)


def reset_trace(token):
    _CURRENT_TRACE.reset(token)


def safe_trace_set(trace, key, value):
    try:
        if trace is not None:
            trace.set(key, value)
    except Exception:
        pass


def safe_trace_finish(trace, outcome, error_code=None):
    try:
        if trace is not None:
            trace.finish(outcome, error_code)
    except Exception:
        pass
