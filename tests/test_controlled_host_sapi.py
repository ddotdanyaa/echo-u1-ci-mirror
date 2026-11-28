"""How the controlled host drives the shared SAPI worker.

Before: serve() started a 20 s `worker.warm` loop that lived only as long as the call (and died silently on
its first exception), `release()` armed the 45 s expiry when the call ended, and every cue was sent with the
engine's 105-250 ms of leading silence. Now: the call pins the shared worker once (non-blocking), the
worker supervises itself, and each cue is trimmed in front before it is paced out to the phone.

No network, no TTS engine, no real socket: a fake worker writes the WAV a real one would.
"""
import asyncio
import tempfile
import unittest
import wave
from array import array
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

try:
    from echo_sync import controlled_host, diagnostics, pcm_trim
except ImportError:
    controlled_host = diagnostics = pcm_trim = None

RATE = 24000


def engine_wav_samples():
    """What Irina writes for a cue: 55 ms of exact zero, ~50 ms of quiet pre-roll click, then speech."""
    zeros = [0] * (RATE * 55 // 1000)
    click = [70 if i % 2 == 0 else -70 for i in range(RATE * 50 // 1000)]
    speech = [6000 if (i // 60) % 2 == 0 else -6000 for i in range(RATE * 400 // 1000)]
    return zeros + click + speech


class FakeWorker:
    def __init__(self, samples=None, rate=RATE, resident=True):
        self.samples = engine_wav_samples() if samples is None else samples
        self.rate = rate
        self.events = []
        if not resident:  # an older shared manager that predates the resident mode
            self.keep_resident = None

    def keep_resident(self):
        self.events.append('keep_resident')

    def warm(self):
        self.events.append('warm')

    def release(self):
        self.events.append('release')

    def synthesize(self, text, path, end=None):
        self.events.append('synthesize')
        with wave.open(path, 'wb') as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(self.rate)
            audio.writeframes(array('h', self.samples).tobytes())
        return path


class Stop(Exception):
    pass


class RenderCuePcmTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(controlled_host and getattr(controlled_host, 'render_cue_pcm', None),
                             'trimmed cue rendering has not been implemented')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_the_engine_lead_silence_is_trimmed_and_everything_after_it_is_untouched(self):
        worker = FakeWorker()
        raw = array('h', worker.samples).tobytes()
        pcm = controlled_host.render_cue_pcm(worker, 'Верно.', self.tmp.name)
        self.assertTrue(raw.endswith(pcm), 'only the front is cut; no sample is changed')
        first_sound = RATE * 105 // 1000  # 55 ms zeros + 50 ms click: the 6000s start here
        self.assertEqual((len(raw) - len(pcm)) // 2, first_sound - RATE * pcm_trim.LEAD_IN_KEEP_MS // 1000)
        self.assertEqual(worker.events, ['synthesize'])

    def test_a_wav_in_another_format_is_still_rejected(self):
        with self.assertRaisesRegex(ValueError, 'SAPI format'):
            controlled_host.render_cue_pcm(FakeWorker(rate=16000), 'Верно.', self.tmp.name)

    def test_no_temporary_files_are_left_behind(self):
        controlled_host.render_cue_pcm(FakeWorker(), 'Верно.', self.tmp.name)
        self.assertEqual(list(Path(self.tmp.name).iterdir()), [])


class ServeWorkerWiringTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(controlled_host, 'controlled host is not importable')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        (self.home / 'echo-sync').mkdir()

    def serve(self, worker, during=None, with_diagnostics=False):
        """Run serve() against a fake socket that hands control to `during` and then hangs up.

        serve() also pre-renders the spoken diagnostics (Task 4) through the very same worker, in a background task whose
        progress when the call ends is a race. Unless `with_diagnostics` is set that pre-render is switched off here, so the
        worker traffic of these tests is exactly what each test provokes; the two behaviours together are pinned by
        test_the_diagnostic_pre_render_runs_through_the_pinned_worker (and the pre-render itself by test_spoken_diagnostics).
        """
        captured = {}

        class Spy(controlled_host.NativeMediaSocket):
            def __init__(self, controller, emit, connect, lookup, synthesize, **options):
                captured['synthesize'] = synthesize
                super().__init__(controller, emit, connect, lookup, synthesize, **options)
                captured['wire'] = self
                if not with_diagnostics:
                    async def no_pre_render(synthesize):
                        return
                    self.diagnostic_audio.prerender = no_pre_render

        class Socket:
            query_params = {}

            async def receive_text(self):
                if during is not None:
                    await during(captured)
                raise Stop()

            async def send_text(self, text):
                pass

            async def close(self, code=1000):
                pass

        async def run_scoped(profile, function, executor=None):
            return function()

        api = SimpleNamespace(__file__=str(self.home / 'plugin_api.py'), _run_scoped=run_scoped,
                              _gpt_live_settings=lambda: {},
                              _watch_audio_runtime=SimpleNamespace(python=lambda: ('python', {}, [], None)))
        with patch.object(controlled_host, 'profile_sapi_worker', return_value=worker), \
                patch.object(controlled_host, 'NativeMediaSocket', Spy):
            with self.assertRaises(Stop):
                asyncio.run(controlled_host.serve(Socket(), api=api, profile=None, home=self.home))
        return captured

    def test_a_call_pins_the_worker_once_before_anything_else_and_never_runs_a_warm_loop(self):
        worker = FakeWorker()

        async def linger(captured):
            await asyncio.sleep(0.05)  # the old keepwarm task would have called worker.warm by now

        self.serve(worker, during=linger)
        self.assertEqual(worker.events, ['keep_resident', 'release'])

    def test_cues_are_rendered_through_the_worker_and_arrive_trimmed(self):
        worker = FakeWorker()
        result = {}

        async def speak(captured):
            result['pcm'] = await captured['synthesize']('Верно.')

        self.serve(worker, during=speak)
        raw = array('h', worker.samples).tobytes()
        self.assertEqual(worker.events, ['keep_resident', 'synthesize', 'release'])
        self.assertTrue(raw.endswith(result['pcm']))
        self.assertLess(len(result['pcm']), len(raw), 'the lead silence was sent to the phone')
        self.assertLessEqual(len(raw) - len(result['pcm']), RATE * 2 * 105 // 1000)

    def test_a_failure_to_pin_the_worker_never_fails_the_call(self):
        worker = FakeWorker()

        def cannot_start_a_thread():
            raise RuntimeError("can't start new thread")

        worker.keep_resident = cannot_start_a_thread
        result = {}

        async def speak(captured):
            result['pcm'] = await captured['synthesize']('Верно.')

        self.serve(worker, during=speak)  # the first cue starts the worker lazily, as before
        self.assertEqual(worker.events, ['synthesize', 'release'])
        self.assertTrue(result['pcm'])

    def test_a_shared_manager_without_the_resident_mode_does_not_break_the_call(self):
        worker = FakeWorker(resident=False)
        result = {}

        async def speak(captured):
            result['pcm'] = await captured['synthesize']('Верно.')

        self.serve(worker, during=speak)
        self.assertEqual(worker.events, ['synthesize', 'release'])
        self.assertTrue(result['pcm'])

    def test_the_diagnostic_pre_render_runs_through_the_pinned_worker(self):
        """Resident worker (Task L3) and spoken diagnostics (Task 4) in ONE call: the worker is pinned first, the phrases are then
        rendered through that same worker with the cues' own trimming synthesizer, and the call still ends with the release."""
        worker = FakeWorker()
        raw = array('h', worker.samples).tobytes()

        async def until_pre_rendered(captured):
            for _ in range(500):  # 5 s at most; the fake worker needs a few milliseconds per phrase
                if len(captured['wire'].diagnostic_audio.prerendered) == len(diagnostics.PHRASES):
                    return
                await asyncio.sleep(0.01)

        captured = self.serve(worker, during=until_pre_rendered, with_diagnostics=True)
        audio = captured['wire'].diagnostic_audio
        self.assertEqual(worker.events, ['keep_resident'] + ['synthesize'] * len(diagnostics.PHRASES) + ['release'])
        self.assertEqual(audio.prerendered, sorted(diagnostics.PHRASES))
        for key in diagnostics.PHRASES:
            pcm = audio.get(key)
            self.assertTrue(raw.endswith(pcm), f'{key}: only the front is cut; no sample is changed')
            self.assertLess(len(pcm), len(raw), f'{key}: the lead silence of the engine was kept')


if __name__ == '__main__':
    unittest.main()
