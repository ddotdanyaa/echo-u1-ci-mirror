"""The Windows SAPI worker must stay warm for the whole server lifetime.

Field evidence (tts-latency.jsonl, 21.10-01.11): 12 cold starts in 186 worker calls (startup_ms median
1104, +0.7-1.6 s on that cue). Every one of the 12 follows an idle gap of 119 s or more and none follows
an error: the worker is lease-style, SapiWorkerManager kills its own child 45 s after the last use, and
only an open controlled call (controlled_host.keepwarm) or a one-shot Hermes warm hook ever refreshed it.
A crash or a failed cue also left the restart to the next cue, on its critical path.

Everything here runs against a fake PowerShell child that speaks sapi_worker.ps1's JSON-lines protocol,
a fake clock and fake timers: nothing sleeps for the idle period and no real process is started.
"""
import json
import tempfile
import threading
import unittest
import wave
from pathlib import Path

try:
    from echo_sync.sapi_worker import SapiWorkerError, SapiWorkerManager, profile_sapi_worker
except ImportError:
    SapiWorkerError = SapiWorkerManager = profile_sapi_worker = None

VOICE = {'voice': 'Microsoft Irina Desktop', 'culture': 'ru-RU'}


def setUpModule():
    # The first worker start in a process imports these Hermes modules; keep that one-off cost
    # (seconds on a busy machine) out of the timed waits below.
    try:
        import hermes_cli._subprocess_compat  # noqa: F401
        import tools.environments.local  # noqa: F401
    except ImportError:
        pass


class Lines:
    """Stand-in for the child's stdout: iterating yields lines until EOF (None).

    `mute` models a pipe that never reports EOF (a grandchild inherited the handle): close() is ignored
    and the reader thread stays blocked until force_eof() at the end of the test.
    """

    def __init__(self, mute=False):
        self._queue = __import__('queue').Queue()
        self.mute = mute

    def put(self, line):
        self._queue.put(line)

    def __iter__(self):
        return self

    def __next__(self):
        line = self._queue.get()
        if line is None:
            raise StopIteration
        return line

    def close(self):
        if not self.mute:
            self._queue.put(None)

    def force_eof(self):
        self._queue.put(None)


class Child:
    """The PowerShell worker minus PowerShell: same protocol, records every request, answers at once."""

    def __init__(self, harness, index):
        self.harness, self.index = harness, index
        self.requests = []
        self.answered = 0
        self.returncode = None
        self.stdout = Lines(mute=index in harness.mute_eof)
        self.stdin = self
        self.stdout.put(json.dumps({'type': 'ready', **VOICE}) + '\n')

    # --- the subprocess.Popen surface SapiWorkerManager uses
    def poll(self):
        return self.returncode

    def terminate(self):
        self._exit(-15)

    def kill(self):
        self._exit(-9)

    def wait(self, timeout=None):
        return self.returncode

    def flush(self):
        pass

    def close(self):
        self._exit(0)  # stdin EOF: sapi_worker.ps1 leaves its read loop and exits cleanly

    def write(self, line):
        request = json.loads(line)
        with self.harness.cond:
            self.requests.append(request)
            number = len(self.requests)
            self.harness.cond.notify_all()
        if (self.index, number) in self.harness.garbage_requests:
            self.stdout.put('this is not json\n')
        else:
            with wave.open(request['output_path'], 'wb') as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(24000)
                audio.writeframes(b'\x10\x00' * 240)
            self.stdout.put(json.dumps({'type': 'result', 'id': request['id'], 'ok': True, **VOICE}) + '\n')
        with self.harness.cond:
            self.answered += 1
            self.harness.cond.notify_all()

    # --- test controls
    def crash(self, report_exit=True):
        """The child dies and its stdout reaches EOF. With report_exit=False poll() still says "running":
        on Windows the pipe EOF is observed a few ms before Popen.poll() reports the exit."""
        if report_exit:
            self._exit(1)
        else:
            self.stdout.close()

    def _exit(self, code):
        if self.returncode is None:
            self.returncode = code
        self.stdout.close()


class Harness:
    def __init__(self):
        self.cond = threading.Condition()
        self.children = []
        self.start_attempts = 0
        self.fail_start = False
        self.garbage_requests = set()  # {(child index, request number from 1)}
        self.mute_eof = set()  # child indexes whose stdout never reports EOF
        self.gate = None  # an Event: popen blocks until it is set (a slow worker start)

    def shutdown(self):
        for child in self.children:
            child.stdout.force_eof()

    def popen(self, *args, **kwargs):
        with self.cond:
            self.start_attempts += 1
            self.cond.notify_all()
        if self.fail_start:
            raise OSError('powershell is not available')
        if self.gate is not None:
            self.gate.wait(10)
        with self.cond:
            child = Child(self, len(self.children))
            self.children.append(child)
            self.cond.notify_all()
        return child

    def wait_for(self, predicate, timeout=10.0):
        with self.cond:
            return self.cond.wait_for(predicate, timeout)

    def primed(self, index):
        """Child `index` exists and has answered its first request (the priming): it is idle and warm."""
        return lambda: len(self.children) > index and self.children[index].answered >= 1


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class Timers:
    """threading.Timer stand-in: nothing fires by itself; the test fires what is armed."""

    def __init__(self):
        self.armed = []

    def __call__(self, interval, function):
        return FakeTimer(self, interval, function)


class FakeTimer:
    daemon = False

    def __init__(self, owner, interval, function):
        self.owner, self.interval, self.function = owner, interval, function
        self.cancelled = False

    def start(self):
        self.owner.armed.append(self)

    def cancel(self):
        self.cancelled = True
        if self in self.owner.armed:
            self.owner.armed.remove(self)

    def fire(self):
        if not self.cancelled:
            self.function()


class Rows:
    """Telemetry collector: keeps the rows the manager would write to tts-latency.jsonl."""

    def __init__(self):
        self.rows = []

    def write(self, row):
        self.rows.append(dict(row))
        return True


class ResidentWorkerTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SapiWorkerManager is not None and hasattr(SapiWorkerManager, 'keep_resident'),
                        'resident SAPI worker has not been implemented')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.harness, self.clock, self.timers, self.rows = Harness(), Clock(), Timers(), Rows()
        self.addCleanup(self.harness.shutdown)

    def make(self, **overrides):
        options = dict(popen_factory=self.harness.popen, startup_timeout=5, request_timeout=5, idle_timeout=45,
                       telemetry=self.rows, clock=self.clock, timer_factory=self.timers)
        options.update(overrides)
        manager = SapiWorkerManager(self.tmp.name, **options)
        self.addCleanup(manager.close)
        return manager

    def cue(self, manager, text='Верно.'):
        return manager.synthesize(text, str(Path(self.tmp.name) / 'cue.wav'))

    def temperatures(self):
        return [row['cold_warm'] for row in self.rows.rows]

    # --- the root cause, pinned down deterministically ------------------------------------------------

    def test_an_unpinned_worker_expires_after_the_idle_period_and_the_next_cue_is_cold(self):
        manager = self.make()
        self.cue(manager)
        self.assertEqual([timer.interval for timer in self.timers.armed], [45])
        self.clock.advance(46)
        self.timers.armed[0].fire()
        self.assertIsNotNone(self.harness.children[0].returncode, 'the idle timer killed the worker')
        self.cue(manager)
        self.assertEqual(len(self.harness.children), 2, 'the cue had to start a second worker itself')
        self.assertEqual(self.temperatures(), ['cold', 'cold'])

    # --- stays warm ---------------------------------------------------------------------------------

    def test_a_resident_worker_arms_no_idle_expiry_and_is_still_warm_an_hour_later(self):
        manager = self.make(resident=True)
        manager.warm()
        self.cue(manager)
        manager.release()
        self.assertEqual(self.timers.armed, [])
        self.clock.advance(3600)
        self.cue(manager)
        self.assertEqual(len(self.harness.children), 1)
        self.assertEqual(self.temperatures(), ['warm', 'warm'])
        self.assertNotIn('startup_ms', self.rows.rows[0])

    def test_warm_primes_the_voice_with_a_throwaway_request_so_the_first_cue_is_not_the_first_speak(self):
        manager = self.make(resident=True)
        manager.warm()
        child = self.harness.children[0]
        self.assertEqual([request['text'] for request in child.requests], [SapiWorkerManager.PRIME_TEXT])
        self.assertFalse(Path(child.requests[0]['output_path']).exists(), 'the priming WAV is removed')
        self.assertEqual(self.rows.rows, [], 'priming is not a cue: it writes no latency row')
        self.cue(manager)
        self.assertEqual(len(child.requests), 2)
        self.assertEqual(self.temperatures(), ['warm'])

    def test_keep_resident_starts_and_primes_in_the_background_and_never_blocks_its_caller(self):
        manager = self.make(resident=True)
        with manager._lock:  # a cue is being synthesized on another thread
            caller = threading.Thread(target=manager.keep_resident)
            caller.start()
            caller.join(5)
            self.assertFalse(caller.is_alive(), 'keep_resident waited for the worker lock (it runs on the event loop)')
        self.assertTrue(self.harness.wait_for(self.harness.primed(0)))
        self.assertEqual([request['text'] for request in self.harness.children[0].requests],
                         [SapiWorkerManager.PRIME_TEXT])

    def test_release_neither_cools_nor_waits_for_a_resident_worker(self):
        manager = self.make(resident=True)
        manager.warm()
        with manager._lock:
            releaser = threading.Thread(target=manager.release)
            releaser.start()
            releaser.join(5)
            self.assertFalse(releaser.is_alive(), 'release waited for the worker lock (it runs on the event loop)')
        self.assertIsNone(self.harness.children[0].returncode)
        self.assertEqual(self.timers.armed, [])

    def test_an_idle_timer_armed_before_pinning_cannot_cool_the_worker_afterwards(self):
        manager = self.make()
        self.cue(manager)
        stale = self.timers.armed[0]
        manager.keep_resident()
        self.clock.advance(60)
        stale.fire()
        self.assertIsNone(self.harness.children[0].returncode)

    def test_profile_workers_are_resident_and_looking_one_up_starts_nothing(self):
        manager = profile_sapi_worker(Path(self.tmp.name) / 'profile')
        self.addCleanup(manager.close)
        self.assertTrue(manager.resident)
        self.assertIsNone(manager._process)
        self.assertIsNone(manager._supervisor)

    # --- crash / failure: the restart happens off the critical path ------------------------------------

    def test_a_crash_is_repaired_in_the_background_before_the_next_cue(self):
        manager = self.make(resident=True)
        manager.keep_resident()
        self.assertTrue(self.harness.wait_for(self.harness.primed(0)))
        self.clock.advance(1)  # it had been up for a while: no restart back-off applies
        self.harness.children[0].crash()
        self.assertTrue(self.harness.wait_for(self.harness.primed(1)), 'nobody restarted the crashed worker')
        self.cue(manager)
        self.assertEqual(len(self.harness.children), 2)
        self.assertEqual(self.temperatures(), ['warm'])
        self.assertNotIn('startup_ms', self.rows.rows[-1], 'the cue did not pay for a start')

    def test_a_crash_is_repaired_even_when_the_pipe_eof_is_seen_before_the_exit_code(self):
        # Measured on the real worker: after kill() the reader sees EOF ~15 ms before poll() reports the
        # exit. The supervisor is woken by that EOF, finds poll() still "running" and, if it trusted only
        # poll(), slept a full keep-alive interval (15 s) before repairing: the cue after a crash paid.
        manager = self.make(resident=True)
        manager.keep_resident()
        self.assertTrue(self.harness.wait_for(self.harness.primed(0)))
        self.clock.advance(1)
        self.harness.children[0].crash(report_exit=False)
        self.assertTrue(self.harness.wait_for(self.harness.primed(1)),
                        'EOF on the worker pipe was not taken as the end of the worker')
        self.cue(manager)
        self.assertEqual(len(self.harness.children), 2)
        self.assertEqual(self.temperatures(), ['warm'])

    def test_a_cue_after_the_pipe_closed_restarts_the_worker_instead_of_writing_into_it(self):
        manager = self.make()  # lease-style: no supervisor, the cue itself has to notice
        self.cue(manager)
        self.harness.children[0].crash(report_exit=False)
        self.assertTrue(self.harness.wait_for(lambda: manager._eof), 'the manager never saw the EOF')
        self.cue(manager)
        self.assertEqual(len(self.harness.children), 2)
        self.assertEqual(self.temperatures(), ['cold', 'cold'])
        self.assertEqual(self.rows.rows[-1]['outcome'], 'success')

    def test_a_cue_that_breaks_the_protocol_leaves_a_warm_replacement_for_the_next_one(self):
        self.harness.garbage_requests = {(0, 2)}  # request 1 is the priming; request 2 is the first real cue
        manager = self.make(resident=True)
        manager.warm()
        self.clock.advance(1)
        with self.assertRaises(SapiWorkerError):
            self.cue(manager)
        self.assertTrue(self.harness.wait_for(self.harness.primed(1)), 'the stopped worker was not restarted')
        self.cue(manager)
        self.assertEqual(len(self.harness.children), 2)
        self.assertEqual(self.rows.rows[-1]['outcome'], 'success')
        self.assertEqual(self.rows.rows[-1]['cold_warm'], 'warm')

    def test_a_stopped_worker_is_replaced_even_when_its_pipe_never_reports_eof(self):
        # A grandchild that inherited the pipe keeps it open after PowerShell is gone: the reader thread
        # never sees EOF, so the stop itself has to wake the supervisor.
        self.harness.garbage_requests = {(0, 2)}
        self.harness.mute_eof = {0}
        manager = self.make(resident=True)
        manager.warm()
        self.clock.advance(1)
        with self.assertRaises(SapiWorkerError):
            self.cue(manager)
        self.assertTrue(self.harness.wait_for(self.harness.primed(1)), 'the stopped worker was not restarted')
        self.cue(manager)
        self.assertEqual(self.temperatures()[-1], 'warm')

    def test_the_first_cue_alone_pins_the_worker_when_nobody_ever_called_warm(self):
        manager = self.make(resident=True)  # Classic voice: Hermes may never lease/warm before the first reply
        self.cue(manager)  # whoever wins the lock, cue or supervisor, starts the one worker
        self.assertEqual(len(self.harness.children), 1)
        self.clock.advance(1)
        self.harness.children[0].crash()
        self.assertTrue(self.harness.wait_for(self.harness.primed(1)), 'nobody restarted the crashed worker')
        self.cue(manager)
        self.assertEqual(len(self.harness.children), 2)
        self.assertEqual(self.temperatures()[-1], 'warm')

    def test_a_cue_waiting_behind_a_background_restart_does_not_start_a_second_worker(self):
        manager = self.make(resident=True)
        manager.keep_resident()
        self.assertTrue(self.harness.wait_for(self.harness.primed(0)))
        self.clock.advance(1)
        self.harness.gate = threading.Event()  # the replacement starts slowly
        self.harness.children[0].crash()
        self.assertTrue(self.harness.wait_for(lambda: self.harness.start_attempts == 2),
                        'the supervisor never began the restart')
        cue = threading.Thread(target=lambda: self.cue(manager))
        cue.start()
        self.harness.gate.set()
        cue.join(10)
        self.assertFalse(cue.is_alive())
        self.assertEqual(len(self.harness.children), 2, 'one worker only, ever')
        self.assertEqual(self.temperatures(), ['warm'])

    def test_repeated_start_failures_back_off_then_stop_and_an_explicit_request_revives(self):
        self.harness.fail_start = True
        manager = self.make(resident=True, keepalive_interval=7.0)
        backoff = SapiWorkerManager.RESTART_BACKOFF_S
        attempts = SapiWorkerManager.MAX_AUTO_RESTARTS
        delays = []
        for _ in range(attempts + 2):
            delays.append(manager._supervise_step())
            self.clock.advance(delays[-1])
        self.assertEqual(delays, [backoff[min(i, len(backoff) - 1)] for i in range(attempts)] + [7.0, 7.0])
        self.assertEqual(self.harness.start_attempts, attempts, 'no attempts once it has given up')
        self.harness.fail_start = False
        manager.keep_resident()
        self.assertTrue(self.harness.wait_for(self.harness.primed(0)))

    def test_a_worker_that_dies_right_after_every_restart_is_not_restarted_forever(self):
        # Start and priming succeed, then it crashes at once: that must not look like a healthy restart.
        manager = self.make(resident=True, keepalive_interval=7.0)
        attempts = SapiWorkerManager.MAX_AUTO_RESTARTS
        backoff = SapiWorkerManager.RESTART_BACKOFF_S
        for number in range(attempts - 1):
            self.assertEqual(manager._supervise_step(), 7.0, 'the restart itself succeeded')
            self.assertEqual(len(self.harness.children), number + 1)
            self.harness.children[-1].crash()
            held = manager._supervise_step()
            self.assertEqual(held, backoff[min(number, len(backoff) - 1)], 'asked again at once: held back')
            self.assertEqual(len(self.harness.children), number + 1)
            self.clock.advance(held)
        self.assertEqual(manager._supervise_step(), 7.0, 'the last allowed restart succeeded too')
        self.assertEqual(len(self.harness.children), attempts)
        self.harness.children[-1].crash()
        for _ in range(3):
            self.clock.advance(1000)
            self.assertEqual(manager._supervise_step(), 7.0, 'given up: quiet until someone asks again')
        self.assertEqual(len(self.harness.children), attempts, 'no further worker')

    def test_a_restart_that_lives_is_forgiven_by_the_next_healthy_pass(self):
        manager = self.make(resident=True, keepalive_interval=7.0)
        self.assertEqual(manager._supervise_step(), 7.0)
        self.harness.children[-1].crash()
        self.clock.advance(SapiWorkerManager.RESTART_BACKOFF_S[0])
        self.assertEqual(manager._supervise_step(), 7.0)  # second worker, up
        self.assertEqual(manager._supervise_step(), 7.0)  # a pass that finds it healthy
        self.harness.children[-1].crash()
        self.assertEqual(manager._supervise_step(), 7.0, 'forgiven: restarted at once, no back-off')
        self.assertEqual(len(self.harness.children), 3)

    def test_a_cue_that_succeeds_forgives_earlier_restarts(self):
        manager = self.make(resident=True, keepalive_interval=7.0)
        # This test drives the supervisor passes itself. Keep the real thread out (a cue would start it, and
        # its first healthy pass forgives too): here only the cue itself may forgive the earlier restarts.
        finished = threading.Thread(target=lambda: None)
        finished.start()
        finished.join()
        manager._supervisor = finished
        self.assertEqual(manager._supervise_step(), 7.0)
        self.harness.children[-1].crash()
        self.clock.advance(SapiWorkerManager.RESTART_BACKOFF_S[0])
        self.assertEqual(manager._supervise_step(), 7.0)
        self.cue(manager)  # proof of life from real use
        self.harness.children[-1].crash()
        self.assertEqual(manager._supervise_step(), 7.0, 'forgiven: restarted at once, no back-off')
        self.assertEqual(len(self.harness.children), 3)

    def test_back_off_holds_a_restart_that_is_asked_for_too_soon(self):
        self.harness.fail_start = True
        manager = self.make(resident=True)
        first = manager._supervise_step()
        self.assertEqual(manager._supervise_step(), first, 'asked again at the same instant: wait, do not retry')
        self.assertEqual(self.harness.start_attempts, 1)

    # --- cadence, shutdown ---------------------------------------------------------------------------

    def test_a_healthy_pass_is_silent_and_sleeps_for_the_named_interval(self):
        manager = self.make(resident=True)
        manager.warm()
        child = self.harness.children[0]
        before = len(child.requests)
        self.assertEqual(manager.keepalive_interval, SapiWorkerManager.KEEPALIVE_INTERVAL_S)
        for _ in range(3):
            self.assertEqual(manager._supervise_step(), SapiWorkerManager.KEEPALIVE_INTERVAL_S)
        self.assertEqual((len(self.harness.children), len(child.requests)), (1, before),
                         'a healthy worker costs one poll, no process and no request')
        self.assertGreater(SapiWorkerManager.KEEPALIVE_INTERVAL_S, 0)
        self.assertTrue(all(delay > 0 for delay in SapiWorkerManager.RESTART_BACKOFF_S))

    def test_close_stops_the_supervisor_and_never_restarts_the_worker(self):
        manager = self.make(resident=True)
        manager.keep_resident()
        self.assertTrue(self.harness.wait_for(self.harness.primed(0)))
        supervisor = manager._supervisor
        manager.close()
        supervisor.join(5)
        self.assertFalse(supervisor.is_alive())
        self.assertIsNotNone(self.harness.children[0].returncode)
        self.assertFalse(self.harness.wait_for(lambda: len(self.harness.children) > 1, timeout=0.3),
                         'a closed manager must not bring its worker back')


if __name__ == '__main__':
    unittest.main()
