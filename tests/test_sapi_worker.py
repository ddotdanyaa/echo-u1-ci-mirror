import json
import tempfile
import threading
import time
import unittest
import wave
from pathlib import Path

try:
    from echo_sync.sapi_worker import SapiWorkerError, SapiWorkerManager, profile_sapi_worker, _PROFILE_WORKERS
except ImportError:
    SapiWorkerError = SapiWorkerManager = profile_sapi_worker = _PROFILE_WORKERS = None


import pytest
pytestmark = pytest.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)


class FakePipe:
    def __init__(self):
        self.lines = __import__('queue').Queue()
        self.closed = False

    def readline(self):
        # As a real pipe does: it waits for a line or EOF, however long that takes. With a limit of its own the fake raised out of the
        # reader, and the manager's reader takes any failure of a read for the end of the pipe: a late reply read as a closed one.
        line = self.lines.get()
        return '' if line is None else line

    def __iter__(self):
        return self

    def __next__(self):
        line = self.readline()
        if not line:
            raise StopIteration
        return line

    def close(self):
        self.closed = True
        self.lines.put(None)


class FakeStdin:
    def __init__(self, process):
        self.process = process
        self.closed = False

    def write(self, line):
        request = json.loads(line)
        if self.process.mode == 'hung_write':
            self.process.write_release.wait()
            raise BrokenPipeError('child closed')
        if self.process.mode == 'timeout':
            return
        def respond():
            if self.process.delay:
                time.sleep(self.process.delay)
            self.process.active -= 1
            self.process.max_active = max(self.process.max_active, self.process.active)
            if self.process.returncode is not None:     # stopped meanwhile: a dead child writes nothing, and its test may have taken the directory
                return
            if self.process.mode == 'bad_response':
                self.process.stdout.lines.put('not-json\n')
                return
            output = Path(request['output_path'])
            with wave.open(str(output), 'wb') as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(24000 if self.process.mode != 'bad_wav' else 16000)
                wav.writeframes(b'\0\0' * 100)
            response = {'type': 'result', 'id': request['id'], 'ok': self.process.mode != 'worker_error',
                        'voice': 'Microsoft Irina Desktop', 'culture': 'ru-RU',
                        'error': 'synthesis_failed' if self.process.mode == 'worker_error' else None}
            self.process.stdout.lines.put(json.dumps(response) + '\n')
        self.process.active += 1
        self.process.max_active = max(self.process.max_active, self.process.active)
        threading.Thread(target=respond, daemon=True).start()

    def flush(self):
        pass

    def close(self):
        self.closed = True
        if self.process.returncode is None and self.process.mode not in {'timeout', 'hung_write'}:
            self.process.returncode = 0
            self.process.stdout.lines.put(None)


class FakeProcess:
    def __init__(self, mode='normal', delay=0):
        self.mode, self.delay = mode, delay
        self.stdout = FakePipe()
        self.stdin = FakeStdin(self)
        self.returncode = None
        self.active = 0
        self.max_active = 0
        self.terminated = False
        self.write_release = threading.Event()
        ready = 'invalid-ready\n' if mode == 'bad_ready' else json.dumps(
            {'type': 'ready', 'voice': 'Microsoft Irina Desktop', 'culture': 'ru-RU'}) + '\n'
        self.stdout.lines.put(ready)

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = 1
        self.write_release.set()
        self.stdout.lines.put(None)

    def kill(self):
        self.terminate()

    def wait(self, timeout=None):
        if self.returncode is None and self.mode in {'timeout', 'hung_write'}:
            raise __import__('subprocess').TimeoutExpired('fake-worker', timeout)
        self.returncode = 0 if self.returncode is None else self.returncode
        return self.returncode


class FakeChildTests(unittest.TestCase):
    def test_the_pipe_of_the_fake_has_no_clock_of_its_own(self):
        pipe = FakePipe()
        calls = []
        pipe.lines.get = lambda *args, **kwargs: calls.append((args, kwargs))
        self.assertEqual(pipe.readline(), '')
        self.assertEqual(calls, [((), {})], 'a limit here reads as EOF: worker_protocol_closed_or_oversized on a child that is only late')

    def test_a_child_stopped_before_its_reply_thread_ran_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'late.wav'
            process = FakeProcess()
            process.stdout.lines.get()                  # its ready line
            process.terminate()
            before = set(threading.enumerate())
            process.stdin.write(json.dumps({'id': 'late', 'output_path': str(target)}) + '\n')
            for thread in set(threading.enumerate()) - before:
                thread.join()
            self.assertFalse(target.exists())
            self.assertEqual(process.stdout.lines.get_nowait(), None, 'the EOF of the terminate, and no reply behind it')
            self.assertTrue(process.stdout.lines.empty())


class SapiWorkerTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(SapiWorkerManager, 'persistent SAPI worker has not been implemented')
        import os
        import sys
        import types
        from unittest import mock
        from echo_sync import sapi_worker as sapi_module

        class NtHost:
            # The host of the worker is Windows here: the worker is driven through the fake popen_factory, so the stand lends the platform.
            name = 'nt'

            def __getattr__(self, attr):
                return getattr(os, attr)

        compat = types.ModuleType('hermes_cli._subprocess_compat')
        compat.windows_hide_flags = lambda: 0
        local = types.ModuleType('tools.environments.local')
        local.hermes_subprocess_env = lambda inherit_credentials=False: {}
        modules = mock.patch.dict(sys.modules, {
            'hermes_cli': types.ModuleType('hermes_cli'),
            'hermes_cli._subprocess_compat': compat,
            'tools.environments': types.ModuleType('tools.environments'),
            'tools.environments.local': local,
        })
        modules.start()
        self.addCleanup(modules.stop)
        host = mock.patch.object(sapi_module, 'os', NtHost())
        host.start()
        self.addCleanup(host.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.processes = []
        self.mode = 'normal'
        self.delay = 0

        def popen(*args, **kwargs):
            proc = FakeProcess(self.mode, self.delay)
            self.processes.append((proc, args, kwargs))
            return proc

        self.manager = SapiWorkerManager(
            r'C:\profiles\echo-sync', popen_factory=popen,
            startup_timeout=0.5, request_timeout=0.2, idle_timeout=10,
        )
        self.addCleanup(self.manager.close)

    def test_reuses_worker_and_validates_atomic_wav(self):
        self.manager.request_timeout = 5  # this test is about reuse, not timeouts: 0.2 s fails on a busy machine
        results = []
        for i in range(2):
            results.append(self.manager.synthesize('Это фраза.', str(Path(self.tmp.name) / 'same.wav')))
        self.assertEqual(len(self.processes), 1)
        self.assertEqual(len(set(results)), 1)
        with wave.open(results[0], 'rb') as wav:
            self.assertEqual((wav.getframerate(), wav.getnchannels(), wav.getsampwidth()), (24000, 1, 2))
        self.assertFalse(self.processes[0][2].get('shell', False))

    def test_profile_registry_isolates_worker_owners(self):
        profile_a = Path(self.tmp.name) / 'profile-a'
        profile_b = Path(self.tmp.name) / 'profile-b'
        worker_a = profile_sapi_worker(profile_a)
        self.addCleanup(worker_a.close)
        worker_b = profile_sapi_worker(profile_b)
        self.addCleanup(worker_b.close)
        self.assertIsNot(worker_a, worker_b)
        self.assertIs(profile_sapi_worker(profile_a), worker_a)

    def test_serializes_concurrent_requests(self):
        self.manager.request_timeout = 5  # serialization is under test, not timeouts: 0.2 s fails on a busy machine
        self.delay = 0.05
        errors = []
        def call(index):
            try:
                self.manager.synthesize('Фраза.', str(Path(self.tmp.name) / f'parallel-{index}.wav'))
            except Exception as exc:
                errors.append(exc)
        threads = [threading.Thread(target=call, args=(i,)) for i in range(3)]
        for thread in threads: thread.start()
        for thread in threads: thread.join(3)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(errors, [])
        self.assertEqual(self.processes[0][0].max_active, 1)

    def test_timeout_and_protocol_errors_kill_worker(self):
        self.mode = 'timeout'
        with self.assertRaises(SapiWorkerError):
            self.manager.synthesize('Таймаут.', str(Path(self.tmp.name) / 'timeout.wav'))
        self.assertTrue(self.processes[-1][0].terminated)

    def test_blocked_stdin_write_is_bounded_and_child_is_killed_before_pipe_close(self):
        self.mode = 'hung_write'
        started = time.monotonic()
        with self.assertRaisesRegex(SapiWorkerError, 'worker_write_timeout'):
            self.manager.synthesize('Проверка блокировки записи.', str(Path(self.tmp.name) / 'hung.wav'))
        self.assertLess(time.monotonic() - started, 1.5)
        process, args, kwargs = self.processes[-1]
        self.assertTrue(process.terminated)
        self.assertTrue(process.stdin.closed)
        self.assertNotIn('-ExecutionPolicy', args[0])

    def test_bad_ready_response_and_invalid_wav_fail_closed(self):
        self.mode = 'bad_ready'
        with self.assertRaises(SapiWorkerError):
            self.manager.synthesize('Старт.', str(Path(self.tmp.name) / 'bad-ready.wav'))
        self.assertIsNotNone(self.processes[-1][0].returncode)
        self.mode = 'bad_wav'
        with self.assertRaises(SapiWorkerError):
            self.manager.synthesize('Неверный WAV.', str(Path(self.tmp.name) / 'bad-wav.wav'))
        self.assertIsNotNone(self.processes[-1][0].returncode)

    def test_worker_error_and_idle_cleanup(self):
        self.manager.request_timeout = 5  # a late reply must not look like a protocol failure on a busy machine
        self.mode = 'worker_error'
        with self.assertRaises(SapiWorkerError):
            self.manager.synthesize('Ошибка.', str(Path(self.tmp.name) / 'error.wav'))
        self.assertFalse(self.processes[-1][0].terminated, 'a valid worker error response does not corrupt protocol state')
        self.manager.close()
        self.assertIsNotNone(self.processes[-1][0].returncode)
        self.mode = 'normal'
        self.manager.idle_timeout = 0.05
        self.manager.synthesize('Идёт.', str(Path(self.tmp.name) / 'idle.wav'))
        deadline = time.monotonic() + 5  # wait for the idle timer, however busy the machine is
        while self.processes[-1][0].returncode is None and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertIsNotNone(self.processes[-1][0].returncode)


if __name__ == '__main__':
    unittest.main()
