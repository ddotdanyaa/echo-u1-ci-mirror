"""Integration coverage for provider and reusable-worker latency traces."""
import json
import queue
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from echo_sync.sapi_provider import EchoSapiProvider
    from echo_sync.sapi_worker import SapiWorkerManager
    from echo_sync.tts_telemetry import TtsLatencyCollector, current_trace
    from test_sapi_worker import FakeProcess
except ImportError:
    EchoSapiProvider = SapiWorkerManager = TtsLatencyCollector = FakeProcess = None


@unittest.skipIf(EchoSapiProvider is None, 'run with the configured Echo/Hermes environment')
class ProviderTraceIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.windows = patch.object(EchoSapiProvider, '_is_windows', return_value=True)
        self.windows.start()
        self.addCleanup(self.windows.stop)
        self.home_patch = patch('hermes_constants.get_hermes_home', return_value=self.home)
        self.home_patch.start()
        self.addCleanup(self.home_patch.stop)

    def _rows(self):
        path = self.home / 'echo-sync' / 'tts-latency.jsonl'
        return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]

    def test_actual_provider_records_worker_success(self):
        class Manager:
            def synthesize(self, text, output, end=None):
                return output

        provider = EchoSapiProvider()
        with patch.object(provider, '_manager', return_value=Manager()):
            result = provider.synthesize('fixture', str(self.home / 'ok.wav'))
        self.assertEqual(result, str(self.home / 'ok.wav'))
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['outcome'], 'success')
        self.assertFalse(rows[0]['fallback'])
        self.assertIsNone(current_trace())

    def test_worker_failure_is_recorded_with_its_fixed_code_and_propagates_there_is_no_second_road(self):
        class Manager:
            def synthesize(self, text, output, end=None):
                raise RuntimeError('worker_timeout')

        provider = EchoSapiProvider()
        with patch.object(provider, '_manager', return_value=Manager()):
            with self.assertRaisesRegex(RuntimeError, 'worker_timeout'):
                provider.synthesize('fixture', str(self.home / 'failed.wav'))
        row, = self._rows()
        self.assertEqual((row['fallback'], row['outcome'], row['error_code']), (False, 'error', 'worker_timeout'))
        self.assertIsNone(current_trace())

    def test_collector_write_failure_does_not_change_success(self):
        class Manager:
            def synthesize(self, text, output, end=None):
                return output

        provider = EchoSapiProvider()
        with patch.object(provider, '_manager', return_value=Manager()), \
             patch.object(TtsLatencyCollector, 'write', side_effect=OSError('telemetry disk error')):
            expected = str(self.home / 'disk-failure.wav')
            self.assertEqual(provider.synthesize('fixture', expected), expected)
        self.assertIsNone(current_trace())


@unittest.skipIf(SapiWorkerManager is None or FakeProcess is None, 'run with the configured Echo/Hermes environment')
class WorkerTraceIntegrationTests(unittest.TestCase):
    def test_two_calls_emit_cold_then_warm_rows_with_shared_request_trace_ids(self):
        from echo_sync import sapi_worker

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            collector = TtsLatencyCollector(root / 'latency.jsonl')
            manager = SapiWorkerManager(str(root), popen_factory=lambda *a, **kw: None, telemetry=collector)
            processes = []

            def start_fake_worker():
                if manager._process is not None and manager._process.poll() is None:
                    return
                process = FakeProcess()
                processes.append(process)
                process.stdout.readline()  # Consume its ready line; the worker reports result rows below.
                manager._process = process
                manager._responses = queue.Queue()
                manager._reader = threading.Thread(target=manager._read_lines,
                                                   args=(process.stdout, manager._responses), daemon=True)
                manager._reader.start()

            request_ids = []
            original_write = None

            def boot_and_capture():
                start_fake_worker()
                process = manager._process
                if process not in getattr(manager, '_captured_processes', []):
                    original = process.stdin.write

                    def capture(line):
                        request_ids.append(json.loads(line)['id'])
                        return original(line)

                    process.stdin.write = capture
                    manager._captured_processes = getattr(manager, '_captured_processes', []) + [process]

            with patch.object(manager, '_start_locked', side_effect=boot_and_capture):
                # First request is deliberately cold: no process exists when _request_locked checks.
                paths = [root / 'one.wav', root / 'two.wav']
                for text, path in zip(('first', 'second'), paths):
                    if manager._process is None:
                        manager._process = None
                    manager.synthesize(text, str(path))
                manager.close()

            self.assertEqual(len(processes), 1)
            self.assertEqual(len(request_ids), 2)
            rows = [json.loads(line) for line in (root / 'latency.jsonl').read_text(encoding='utf-8').splitlines()]
            self.assertEqual(len(rows), 2)
            self.assertEqual([row['cold_warm'] for row in rows], ['cold', 'warm'])
            self.assertEqual(request_ids, [row['trace_id'] for row in rows])
            for row in rows:
                self.assertEqual(row['outcome'], 'success')
                for phase in ('lock_wait_ms', 'startup_ms', 'write_wait_ms', 'synth_wait_ms', 'validate_ms', 'total_ms'):
                    if phase in row:
                        self.assertIsInstance(row[phase], (int, float))
                        self.assertGreaterEqual(row[phase], 0)
            self.assertEqual(len(list(root.glob('*.wav'))), 2)

    def test_broken_trace_set_and_finish_do_not_break_worker_wav(self):
        from echo_sync import tts_telemetry

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            collector = TtsLatencyCollector(root / 'latency.jsonl')
            manager = SapiWorkerManager(str(root), popen_factory=lambda *a, **kw: None, telemetry=collector)
            processes = []

            def start_fake_worker():
                if manager._process is not None and manager._process.poll() is None:
                    return
                process = FakeProcess()
                processes.append(process)
                process.stdout.readline()
                manager._process = process
                manager._responses = queue.Queue()
                manager._reader = threading.Thread(target=manager._read_lines,
                                                   args=(process.stdout, manager._responses), daemon=True)
                manager._reader.start()

            target = root / 'telemetry-failure.wav'
            with (patch.object(manager, '_start_locked', side_effect=start_fake_worker),
                  patch.object(tts_telemetry.TtsLatencyTrace, 'set', side_effect=RuntimeError('telemetry')),
                  patch.object(tts_telemetry.TtsLatencyTrace, 'finish', side_effect=RuntimeError('telemetry'))):
                result = manager.synthesize('still succeeds', str(target))
            manager.close()
            self.assertEqual(result, str(target))
            self.assertTrue(target.is_file())
            self.assertEqual(len(processes), 1)


if __name__ == '__main__':
    unittest.main()
