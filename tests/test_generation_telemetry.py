import json
import tempfile
import unittest
from pathlib import Path

from echo_sync.generation_telemetry import GenerationTelemetryCollector, GenerationTrace
from echo_sync.generator import PrivateCodexGenerator
from types import SimpleNamespace as S


class GenerationTelemetryTests(unittest.TestCase):
    def test_numeric_trace_id_cannot_replace_validated_random_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'trace.jsonl'
            self.assertTrue(GenerationTelemetryCollector(path).write({'trace_id': 12, 'outcome': ['private']}))
            row = json.loads(path.read_text())
            self.assertRegex(row['trace_id'], r'^[0-9a-f]{32}$')
            self.assertEqual(row['outcome'], 'error')

    def test_finish_is_idempotent_and_mark_does_not_overwrite_first_offset(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'trace.jsonl'
            trace = GenerationTrace(GenerationTelemetryCollector(path), lambda: 1.0)
            trace.mark('first_event')
            trace.mark('first_event')
            self.assertTrue(trace.finish('success'))
            self.assertFalse(trace.finish('error'))
            self.assertEqual(len(path.read_text().splitlines()), 1)
            self.assertEqual(json.loads(path.read_text())['outcome'], 'success')

    def test_trace_writes_only_allowlisted_timings_and_rotates_bounded_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'trace.jsonl'
            ticks = iter([1.0, 1.001, 1.002])
            trace = GenerationTrace(GenerationTelemetryCollector(path), lambda: next(ticks))
            trace.mark('first_event')
            trace.row['question'] = 'private'; trace.row['token'] = 'secret'
            trace.finish('success')
            row = json.loads(path.read_text())
            self.assertEqual(row['outcome'], 'success')
            self.assertTrue(set(row) <= GenerationTelemetryCollector.FIELDS)
            self.assertNotIn('private', path.read_text())

    def test_rotation_keeps_current_and_one_backup_below_256_kib(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'trace.jsonl'
            collector = GenerationTelemetryCollector(path)
            for _ in range(3000):
                collector.write({'outcome':'success'})
            backup = path.with_name(path.name + '.1')
            self.assertTrue(backup.exists())
            self.assertLessEqual(path.stat().st_size, 256 * 1024)
            self.assertLessEqual(backup.stat().st_size, 256 * 1024)

    def test_diagnostic_write_failure_is_best_effort(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'blocked'; path.mkdir()
            trace = GenerationTrace(GenerationTelemetryCollector(path), lambda: 1.0)
            self.assertFalse(trace.finish('error'))

    def test_generator_records_phase_marks_and_redacts_all_request_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            ticks = iter(i / 1000 for i in range(10))
            class Client:
                def __init__(self, **kw): self.responses = self
                def create(self, **kw): return iter([S(type='response.output_text.delta'), S(type='response.completed', response=S(output=[S(type='message', content=[S(type='output_text', text='private reply')])]))])
                def close(self): pass
            gen = PrivateCodexGenerator(resolve=lambda: {'api_key':'a.b.c','base_url':'https://chatgpt.com/backend-api/codex'}, client_factory=Client, headers=lambda *a, **k: {}, trace_path=Path(tmp)/'g.jsonl', clock=lambda: next(ticks))
            self.assertEqual(gen('secret question', [], 'secret context', {}, 'secret model'), 'private reply')
            payload = (Path(tmp)/'g.jsonl').read_text()
            row = json.loads(payload)
            self.assertEqual(row['outcome'], 'success')
            for phase, expected in [('credentials_resolve_ms',1),('client_setup_ms',2),('request_create_ms',3),('first_event_ms',4),('first_delta_ms',5),('completed_ms',6),('total_ms',7)]:
                self.assertEqual(row[phase], float(expected))
            self.assertTrue({'credentials_resolve_ms','client_setup_ms','request_create_ms','first_event_ms','first_delta_ms','completed_ms','total_ms'} <= row.keys())
            self.assertNotIn('secret', payload); self.assertNotIn('private', payload)

    def test_generator_reports_cancelled_and_error_when_resolve_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'g.jsonl'
            cancelled = PrivateCodexGenerator(trace_path=path, clock=lambda: 1.0)
            event = __import__('threading').Event(); event.set()
            with self.assertRaises(RuntimeError): cancelled.generate_cancellable('', [], '', {}, '', cancellation_event=event, is_current=lambda: True)
            self.assertEqual(json.loads(path.read_text())['outcome'], 'cancelled')
            failing = PrivateCodexGenerator(resolve=lambda: (_ for _ in ()).throw(ValueError()), trace_path=path, clock=lambda: 1.0)
            with self.assertRaises(ValueError): failing('', [], '', {}, '')
            self.assertEqual([json.loads(x)['outcome'] for x in path.read_text().splitlines()], ['cancelled','error'])

    def test_clock_failure_does_not_change_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            class Client:
                def __init__(self, **kw): self.responses = self
                def create(self, **kw): return iter([S(type='response.completed', response=S(output=[S(type='message', content=[S(type='output_text', text='ok')])]))])
                def close(self): pass
            gen = PrivateCodexGenerator(resolve=lambda: {'api_key':'a.b.c','base_url':'https://chatgpt.com/backend-api/codex'}, client_factory=Client, headers=lambda *a, **k: {}, trace_path=Path(tmp)/'g.jsonl', clock=lambda: (_ for _ in ()).throw(OSError()))
            self.assertEqual(gen('', [], '', {}, ''), 'ok')

    def test_write_failure_and_client_close_failure_preserve_generator_outcomes(self):
        class Client:
            def __init__(self, **kw): self.responses = self
            def create(self, **kw): return iter([S(type='response.completed', response=S(output=[S(type='message', content=[S(type='output_text', text='ok')])]))])
            def close(self): raise OSError('close')
        with tempfile.TemporaryDirectory() as tmp:
            blocked = Path(tmp)/'blocked'; blocked.mkdir()
            gen = PrivateCodexGenerator(resolve=lambda: {'api_key':'a.b.c','base_url':'https://chatgpt.com/backend-api/codex'}, client_factory=Client, headers=lambda *a, **k: {}, trace_path=blocked, clock=lambda: 1.0)
            with self.assertRaises(OSError): gen('', [], '', {}, '')
            self.assertEqual(gen.trace_path, blocked)


if __name__ == '__main__': unittest.main()
