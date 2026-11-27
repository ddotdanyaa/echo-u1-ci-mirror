import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from agent.tts_provider import TTSProvider
    from echo_sync.sapi_provider import EchoSapiProvider
    from echo_sync.sapi_worker import SapiWorkerError
    from echo_sync.speech_text import speak
except ImportError:
    TTSProvider = EchoSapiProvider = SapiWorkerError = None


class RecordingManager:
    def __init__(self, result='written.wav', error=None):
        self.result, self.error = result, error
        self.calls = []
        self.warmed = 0
        self.released = 0

    def synthesize(self, text, path):
        self.calls.append((text, path))
        if self.error:
            raise self.error
        return path if self.result == 'written.wav' else self.result

    def warm(self):
        self.warmed += 1

    def release(self):
        self.released += 1


class EchoSapiProviderTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(EchoSapiProvider, 'native Echo SAPI provider has not been implemented')
        self.tts = {'provider': 'echo_sapi', 'speed': 1.0}

    def test_native_provider_has_unique_id_and_local_irina_schema(self):
        provider = EchoSapiProvider(RecordingManager())
        self.assertIsInstance(provider, TTSProvider)
        self.assertEqual(provider.name, 'echo_sapi')
        self.assertEqual(provider.display_name, 'ECHO — Ирина (быстрый локальный голос)')
        self.assertEqual(provider.get_setup_schema()['badge'], 'local')
        self.assertEqual(provider.get_setup_schema()['env_vars'], [])

    def test_synthesis_uses_profile_worker_and_coerces_output_to_wav(self):
        manager = RecordingManager()
        provider = EchoSapiProvider(manager)
        with patch.object(EchoSapiProvider, '_is_windows', return_value=True), tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'audio.mp3'
            result = provider.synthesize('Это фраза.', str(output), format='mp3', speed=2.0)
        self.assertEqual(result, str(output.with_suffix('.wav')))
        self.assertEqual(manager.calls, [(speak('Это фраза.'), str(output.with_suffix('.wav')))])

    def test_worker_failure_reaches_the_caller_there_is_no_command_fallback(self):
        manager = RecordingManager(error=SapiWorkerError('worker_timeout'))
        provider = EchoSapiProvider(manager)
        with patch.object(EchoSapiProvider, '_is_windows', return_value=True), tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SapiWorkerError):
                provider.synthesize('Это фраза.', str(Path(tmp) / 'audio.wav'))
        self.assertEqual(len(manager.calls), 1)

    def test_warm_and_release_manage_owned_worker(self):
        manager = RecordingManager()
        provider = EchoSapiProvider(manager)
        with patch.object(EchoSapiProvider, '_is_windows', return_value=True):
            provider.warm()
            provider.release()
        self.assertEqual((manager.warmed, manager.released), (1, 1))

    def test_provider_is_not_available_off_windows(self):
        provider = EchoSapiProvider(RecordingManager())
        with patch.object(EchoSapiProvider, '_is_windows', return_value=False):
            self.assertFalse(provider.is_available())


if __name__ == '__main__':
    unittest.main()
