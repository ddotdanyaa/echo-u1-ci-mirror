"""Exact-source guarded patch for command TTS rows in the native provider picker."""
import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import echo_provider_ui_patch as patcher

SOURCE = os.environ.get('HERMES_SOURCE')
TARGET_REL = Path('hermes_cli/tools_config_providers.py')


@unittest.skipUnless(SOURCE, 'HERMES_SOURCE required for exact provider-picker fixture')
class ProviderUiPatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'hermes'
        self.home = Path(self.tmp.name) / 'profile'
        self.target = self.root / TARGET_REL
        self.target.parent.mkdir(parents=True)
        source_target = Path(SOURCE) / TARGET_REL
        source_backup = Path(SOURCE) / patcher.TARGET_BACKUP
        source_bytes = source_target.read_bytes()
        if source_backup.is_file():
            original = source_backup.read_bytes()
            self.assertEqual(hashlib.sha256(original).hexdigest(), patcher.EXPECTED_SHA256)
            self.original = original
        else:
            self.assertEqual(hashlib.sha256(source_bytes).hexdigest(), patcher.EXPECTED_SHA256)
            self.original = source_bytes
        self.target.write_bytes(self.original)

    def _load_provider_module_from_bytes(self, source_bytes):
        import hermes_cli.tools_config_providers as providers
        namespace = providers.__dict__.copy()
        self.addCleanup(lambda: (providers.__dict__.clear(), providers.__dict__.update(namespace)))
        exec(compile(source_bytes, str(self.target), 'exec'), providers.__dict__)
        return providers

    def test_fails_before_patch_command_provider_is_hidden(self):
        providers = self._load_provider_module_from_bytes(self.original)
        config = {'tts': {'provider': 'hostvoice', 'providers': {
            'hostvoice': {'type': 'command', 'command': 'speak {text_path} {output_path}'}}}}
        rows = providers._visible_providers({'name': 'Text-to-Speech', 'providers': []}, config,
                                  features=SimpleNamespace(account_info=None, nous_auth_present=False))
        self.assertNotIn('hostvoice', [row.get('tts_provider') for row in rows])

    def _load_patched_provider_module(self):
        patcher.apply_patch(self.root)
        return self._load_provider_module_from_bytes(self.target.read_bytes())

    def test_patch_visible_active_dynamic_and_profile_scoped_command_row(self):
        providers = self._load_patched_provider_module()
        command = {'type': 'command', 'command': 'host-tts {text_path} {output_path}',
                   'display_name': 'My Voice'}
        selected = {'tts': {'provider': 'windows_sapi', 'providers': {'HostVoice': command}}}
        other_profile = {'tts': {'provider': 'windows_sapi', 'providers': {'HostVoice': command}}}
        cat = {'name': 'Text-to-Speech', 'providers': []}
        features = SimpleNamespace(account_info=None, nous_auth_present=False)
        row = next(p for p in providers._visible_providers(cat, selected, features=features)
                   if p.get('tts_provider') == 'hostvoice')
        self.assertEqual(row['name'], 'My Voice')
        self.assertEqual(row['tts_provider'], 'hostvoice')
        self.assertEqual(row['env_vars'], [])
        self.assertEqual(row['tag'], 'local command; confirm with voice test')
        self.assertEqual(row['badge'], 'local')
        self.assertFalse(providers._is_provider_active(row, selected))
        self.assertFalse(providers._is_provider_active(row, other_profile))
        providers.apply_provider_selection('tts', 'My Voice', selected)
        self.assertEqual(selected['tts']['provider'], 'hostvoice')
        self.assertTrue(providers._is_provider_active(row, selected))
        self.assertNotIn('hostvoice', [p.get('tts_provider') for p in
                                      providers._visible_providers({'name': 'Text-to-Speech', 'providers': []},
                                      {'tts': {'provider': 'windows_sapi'}}, features=features)])

    def test_duplicate_ids_and_labels_and_malformed_settings_are_ignored(self):
        providers = self._load_patched_provider_module()
        features = SimpleNamespace(account_info=None, nous_auth_present=False)
        cat = {'name': 'Text-to-Speech', 'providers': [
            {'name': 'My Voice', 'tts_provider': 'other-id'},
            {'name': 'Existing', 'tts_provider': 'hostvoice'},
            {'name': 'Windows SAPI', 'tts_provider': 'windows_sapi'}]}
        config = {'tts': {'providers': {
            'HostVoice': {'type': 'command', 'command': 'speak', 'display_name': 'duplicate'},
            'other': {'type': 'command', 'command': 'speak', 'display_name': 'My Voice'},
            'bad': {'type': 'command'},
            'windows_sapi': {'type': 'command', 'command': 'must not replace builtin'},
            None: {'type': 'command', 'command': 'speak'},
        }}}
        rows = providers._visible_providers(cat, config, features=features)
        self.assertEqual([p.get('tts_provider') for p in rows].count('hostvoice'), 1)
        self.assertEqual([p.get('name') for p in rows].count('My Voice'), 1)
        self.assertNotIn('bad', [p.get('tts_provider') for p in rows])
        self.assertEqual([p.get('tts_provider') for p in rows].count('windows_sapi'), 1)
        self.assertNotIn('none', [p.get('tts_provider') for p in rows])
        for malformed in (None, [], 'broken', {'providers': 'bad'}):
            with self.subTest(malformed=malformed):
                self.assertIsInstance(providers._visible_providers(
                    {'name': 'Text-to-Speech', 'providers': []}, {'tts': malformed}, features=features), list)

    def test_apply_is_idempotent_rollback_restores_exact_bytes_and_unknown_source_is_refused(self):
        first = patcher.apply_patch(self.root)
        self.assertEqual(first['status'], 'applied')
        patched = self.target.read_bytes()
        self.assertEqual(patcher.apply_patch(self.root)['status'], 'already_applied')
        self.assertEqual(self.target.read_bytes(), patched)
        self.assertEqual(patcher.rollback_patch(self.root)['status'], 'restored')
        self.assertEqual(self.target.read_bytes(), self.original)
        self.target.write_bytes(self.original + b'\n# changed')
        with self.assertRaises(RuntimeError):
            patcher.apply_patch(self.root)
        self.assertFalse((self.root / patcher.TARGET_BACKUP).exists())


if __name__ == '__main__':
    unittest.main()


