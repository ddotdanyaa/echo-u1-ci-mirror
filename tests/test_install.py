import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import install_echo


class InstallTests(unittest.TestCase):
    def test_rejects_paid_or_appserver_route_before_creating_profile(self):
        for model in ({'provider': 'openai', 'default': 'x'},
                      {'provider': 'openai-codex', 'default': 'x', 'openai_runtime': 'codex_app_server'}):
            with self.assertRaises(ValueError):
                install_echo.select_model(model)

    def test_preserves_existing_oauth_model_without_inheriting_other_settings(self):
        result = install_echo.select_model({'provider': 'openai-codex', 'default': 'my-current-model',
                                            'api_key': 'do-not-copy', 'base_url': 'https://chatgpt.com/backend-api/codex'})
        self.assertEqual(result['default'], 'my-current-model')
        self.assertNotIn('api_key', result)
        self.assertEqual(result['provider'], 'openai-codex')

    def test_generated_profile_has_no_paid_voice_or_automatic_background_work(self):
        cfg = install_echo.profile_config({'provider': 'openai-codex', 'default': 'test'})
        self.assertEqual(cfg['tts'], {'provider': 'echo_sapi'})      # the plugin's own provider; no command script
        self.assertFalse(cfg['compression']['enabled'])
        self.assertEqual(cfg['fallback_model'], [])
        self.assertEqual(cfg['platform_toolsets']['cli'], [])
        self.assertFalse(cfg['auxiliary']['background_review']['enabled'])
        self.assertFalse(cfg['auxiliary']['title_generation']['enabled'])
        self.assertFalse(cfg['file_tools']['hosted_ocr'])
        self.assertNotIn('api_key', json.dumps(cfg))

    def test_uses_actual_cli_profile_root_with_spaces_and_composes_native_path(self):
        with tempfile.TemporaryDirectory(prefix='Hermes profile ') as tmp:
            reported = Path(tmp).resolve()
            output = f'Profile: default\nPath:    {reported}\nModel: x\n'
            value = install_echo.parse_profile_path(output)
            self.assertEqual(value, reported)
            self.assertEqual(value / 'profiles' / 'echo-sync', reported / 'profiles' / 'echo-sync')

    def test_rejects_relative_and_mismatched_runtime_profile_paths(self):
        invalid_paths = ['relative']
        if install_echo.os.name == 'nt':
            invalid_paths.extend(['/custom/Hermes data', r'\custom\Hermes data'])
        else:
            invalid_paths.append(r'C:\Hermes data')
        for path in invalid_paths:
            with self.subTest(path=path), self.assertRaises(ValueError):
                install_echo.parse_profile_path(f'Profile: default\nPath: {path}\n')

    def test_installation_refuses_existing_profile_without_touching_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = Path(tmp) / 'echo-sync'
            profile.mkdir()
            marker = profile / 'config.yaml'
            marker.write_text('original', encoding='utf-8')
            with self.assertRaises(FileExistsError):
                install_echo.write_new_profile(profile, {}, Path(__file__).resolve().parents[1])
            self.assertEqual(marker.read_text(), 'original')

    def test_creates_self_contained_profile_with_sample_qa_and_no_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = Path(tmp) / 'echo-sync'
            install_echo.write_new_profile(profile, {'model': {'provider': 'openai-codex'}},
                                            Path(__file__).resolve().parents[1])
            cfg = json.loads((profile / 'config.yaml').read_text())
            self.assertEqual(cfg['model']['provider'], 'openai-codex')
            self.assertTrue((profile / 'plugins' / 'echo-sync' / 'plugin.yaml').is_file())
            self.assertFalse((profile / 'scripts').exists())
            self.assertTrue((profile / 'materials' / 'qa.json').is_file())
            self.assertFalse((profile / 'auth.json').exists())
            self.assertFalse((profile / '.env').exists())

    def test_failed_new_install_preserves_files_but_allows_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = Path(tmp) / 'echo-sync'
            profile.mkdir()
            (profile / 'config.yaml').write_text('new-install', encoding='utf-8')
            saved = install_echo.preserve_failed_profile(profile)
            self.assertFalse(profile.exists())
            self.assertTrue(saved.name.startswith('.echo-sync-failed-'))
            self.assertEqual((saved / 'config.yaml').read_text(), 'new-install')


if __name__ == '__main__':
    unittest.main()
