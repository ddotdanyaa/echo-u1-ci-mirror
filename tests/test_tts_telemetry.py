import json
import tempfile
import unittest
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from echo_sync.tts_telemetry import TtsLatencyCollector, TtsLatencyTrace


class TtsTelemetryTests(unittest.TestCase):
    def test_redacted_correlated_records_and_allowlisted_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            collector = TtsLatencyCollector(Path(tmp) / 'tts-latency.jsonl')
            trace = TtsLatencyTrace(collector)
            trace.set('lock_wait_ms', 1.2)
            trace.set('cold_warm', 'cold')
            trace.set('fallback', True)
            trace.finish('error', 'worker_error')
            trace.finish('success', 'secret raw exception')
            rows = [json.loads(line) for line in (Path(tmp) / 'tts-latency.jsonl').read_text().splitlines()]
            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(row['trace_id'], trace.trace_id)
            self.assertEqual(row['error_code'], 'other')
            self.assertNotIn('raw exception', repr(row))
            self.assertTrue(set(row) <= TtsLatencyCollector.ALLOWED_FIELDS)

    def test_rotation_is_bounded_and_keeps_one_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'tts-latency.jsonl'
            collector = TtsLatencyCollector(path, max_bytes=900)
            for _ in range(20):
                trace = TtsLatencyTrace(collector)
                trace.finish('success')
            self.assertLessEqual(path.stat().st_size, 900)
            self.assertLessEqual(path.with_suffix('.jsonl.1').stat().st_size, 900)

    def test_disk_failure_is_best_effort(self):
        with tempfile.TemporaryDirectory() as tmp:
            blocked = Path(tmp) / 'log.jsonl'
            blocked.mkdir()
            collector = TtsLatencyCollector(blocked)
            trace = TtsLatencyTrace(collector)
            self.assertFalse(trace.finish('success'))

    def test_invalid_values_and_oversized_payload_are_never_persisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'tts-latency.jsonl'
            collector = TtsLatencyCollector(path)
            row = {'trace_id': 'SECRET-TOKEN', 'at_utc': '2020-01-01T/private/path+00:00', 'fallback': 'secret',
                   'cold_warm': 'output path', 'outcome': 'cookie', 'error_code': 'raw exception with token',
                   'total_ms': float('inf'), 'startup_ms': -3, 'synth_wait_ms': 9999999999,
                   'session_id': 'sensitive', 'text': 'private spoken words'}
            self.assertTrue(collector.write(row))
            data = path.read_text(encoding='utf-8')
            parsed = json.loads(data)
            self.assertEqual(parsed['fallback'], False)
            self.assertEqual(parsed['outcome'], 'error')
            self.assertNotIn('error_code', parsed)
            self.assertNotIn('SECRET', data)
            self.assertNotIn('private', data)
            self.assertNotIn('session_id', data)
            self.assertNotIn('/private/path', data)
            self.assertNotIn('total_ms', parsed)

    def test_rotation_failure_skips_append_and_oversized_existing_log_is_rebounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'tts-latency.jsonl'
            collector = TtsLatencyCollector(path, max_bytes=512)
            path.write_bytes(b'x' * 500)
            backup = path.with_name(path.name + '.1')
            backup.write_bytes(b'old')
            with patch('echo_sync.tts_telemetry.os.replace', side_effect=OSError('private exception')):
                self.assertFalse(collector.write({'trace_id': 'a' * 32, 'outcome': 'success'}))
            self.assertEqual(path.stat().st_size, 500)
            self.assertEqual(backup.read_bytes(), b'old')
            path.write_bytes(b'x' * 600)
            self.assertTrue(collector.write({'outcome': 'success'}))
            self.assertLessEqual(path.stat().st_size, 512)
            self.assertLessEqual(backup.stat().st_size, 512)


if __name__ == '__main__':
    unittest.main()
