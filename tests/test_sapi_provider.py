"""Hermes native registry adapter of the profile's one SAPI provider (echo_sapi): telemetry never costs the result, registration is plain."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SOURCE = os.environ.get('HERMES_SOURCE')
if SOURCE:
    sys.path.insert(0, SOURCE)


@unittest.skipUnless(SOURCE, 'HERMES_SOURCE required for native TTS provider integration')
class EchoSapiProviderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)

    def with_home(self):
        return patch.dict(os.environ, {'HERMES_HOME': str(self.home)})

    def test_telemetry_finish_failure_cannot_change_a_successful_result(self):
        from echo_sync.sapi_provider import EchoSapiProvider

        class Manager:
            calls = 0

            def synthesize(self, text, path, end=None):
                self.calls += 1
                return path
        manager = Manager()
        provider = EchoSapiProvider(manager=manager)
        with self.with_home(), patch.object(provider, '_is_windows', return_value=True), \
             patch('echo_sync.tts_telemetry.safe_trace_finish', side_effect=RuntimeError('private telemetry failure')):
            result = provider.synthesize('Проверка', str(self.home / 'voice.wav'))
        self.assertEqual(result, str(self.home / 'voice.wav'))
        self.assertEqual(manager.calls, 1)

    def test_trace_context_reset_failure_cannot_replace_successful_tts_result(self):
        from echo_sync.sapi_provider import EchoSapiProvider

        class Manager:
            calls = 0

            def synthesize(self, text, path, end=None):
                self.calls += 1
                return path
        manager = Manager()
        provider = EchoSapiProvider()
        with self.with_home(), patch.object(provider, '_is_windows', return_value=True), \
             patch.object(provider, '_manager', return_value=manager), \
             patch('hermes_constants.get_hermes_home', return_value=self.home), \
             patch('echo_sync.tts_telemetry.reset_trace', side_effect=ValueError('context reset failed')):
            result = provider.synthesize('Проверка', str(self.home / 'trace.wav'))
        from echo_sync.tts_telemetry import current_trace
        self.assertEqual(result, str(self.home / 'trace.wav'))
        self.assertEqual(manager.calls, 1)
        self.assertIsNone(current_trace(), 'failed cleanup must clear the current trace before the next worker call')

    def test_registration_is_one_provider_on_windows_and_none_on_a_legacy_host(self):
        import echo_sync.plugin as plugin_module

        class Context:
            def __init__(self, has_tts=True):
                self.providers = []
                self.hooks = []
                self.cli = []
                if has_tts:
                    self.register_tts_provider = self.providers.append

            def get_config(self, key, default=None):
                return default

            def register_hook(self, *args):
                self.hooks.append(args)

            def register_middleware(self, *args):
                self.hooks.append(args)

            def register_cli_command(self, *args):
                self.cli.append(args)
        with self.with_home(), patch('os.name', 'nt'):
            modern = Context()
            plugin_module.register(modern)
            self.assertEqual([provider.name for provider in modern.providers], ['echo_sapi'])
            self.assertTrue(modern.hooks)
            legacy = Context(has_tts=False)
            plugin_module.register(legacy)
            self.assertEqual(legacy.providers, [])
            self.assertTrue(legacy.hooks)


if __name__ == '__main__':
    unittest.main()
