import tempfile
import unittest
from pathlib import Path

try:
    from echo_sync.plugin import EchoPlugin, raw_response
except ImportError:
    EchoPlugin = raw_response = None


class PluginTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(EchoPlugin, 'Hermes middleware plugin has not been implemented')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.generations = []
        def generate(*args):
            self.generations.append(args)
            return 'Первый второй третий четвёртый пятый шестой'
        self.plugin = EchoPlugin(Path(self.tmp.name), generate=generate)
        self.next_calls = []
        self.kw = dict(provider='openai-codex', api_mode='codex_responses', base_url='https://chatgpt.com/backend-api/codex', model='gpt-5-codex', session_id='s1', turn_id='1')

    def execute(self, text, turn='1', **kw):
        params = {**self.kw, 'turn_id': turn, **kw}
        self.plugin.capture(user_message=text, **params)
        return self.plugin.execute(request={'input': []}, next_call=lambda r: self.next_calls.append(r), **params)

    def test_captures_original_text_and_replies_without_outer_provider(self):
        r = self.execute('Что это?')
        self.assertEqual(r.output[0].content[0].text, 'Первый второй третий')
        self.assertEqual(self.execute('первый второй третий', '2').output_text, 'четвёртый пятый шестой')
        self.assertEqual(len(self.generations), 1)
        self.assertEqual(self.next_calls, [])

    def test_wrong_provider_returns_local_error_never_falls_through(self):
        for provider, api_mode, url in [('openai', 'codex_responses', 'https://api.openai.com/v1'), ('openrouter', 'chat_completions', 'https://openrouter.ai/api/v1'), ('openai-codex', 'codex_app_server', 'https://chatgpt.com/backend-api/codex')]:
            r = self.execute('Что это?', provider=provider, api_mode=api_mode, base_url=url)
            self.assertEqual(r.output_text, 'NO_REPLY')
        self.assertEqual(self.next_calls, [])
        self.assertEqual(self.generations, [])

    def test_missing_capture_does_not_make_provider_request(self):
        r = self.plugin.execute(request={}, next_call=lambda r: self.next_calls.append(r), **self.kw)
        self.assertEqual(r.output_text, 'NO_REPLY')
        self.assertEqual(self.next_calls, [])

    def test_prepared_bank_works_offline(self):
        materials = Path(self.tmp.name) / 'materials'
        materials.mkdir()
        (materials / 'qa.json').write_text('[{"question":"Что такое бюджет?","answer":"Доходы покрывают наши расходы."}]', encoding='utf-8')
        self.assertEqual(self.execute('Что такое бюджет?').output_text, 'Доходы покрывают наши')
        self.assertEqual(self.generations, [])

    def test_internal_failure_is_a_local_response(self):
        self.plugin.engine.reply = lambda **kwargs: (_ for _ in ()).throw(RuntimeError('database locked'))
        self.assertEqual(self.execute('Что это?').output_text, 'NO_REPLY')
        self.assertEqual(self.next_calls, [])

    def test_registration_does_not_create_state_before_a_chat_turn(self):
        self.assertFalse((Path(self.tmp.name) / 'echo-sync' / 'state.sqlite3').exists())

    def write_settings(self, text):
        materials = Path(self.tmp.name) / 'materials'
        materials.mkdir(exist_ok=True)
        path = materials / 'echo_settings.json'
        path.write_text(text, encoding='utf-8')
        return path

    def test_settings_file_is_re_read_on_every_turn(self):
        path = self.write_settings('{"words_per_portion": 2}')
        self.assertEqual(self.execute('Что это?').output_text, 'Первый второй')
        self.write_settings('{"words_per_portion": 4}')
        self.assertEqual(self.execute('Как это работает?', '2').output_text, 'Первый второй третий четвёртый')
        path.unlink()
        self.assertEqual(self.execute('Почему это так?', '3').output_text, 'Первый второй третий')

    def test_broken_settings_file_falls_back_to_defaults_instead_of_stopping_the_session(self):
        self.write_settings('{this is not json')
        self.assertEqual(self.execute('Что это?').output_text, 'Первый второй третий')
        self.write_settings('{"on_mismatch": "loud", "words_per_portion": "много"}')
        self.assertEqual(self.execute('первый второй третий', '2').output_text, 'четвёртый пятый шестой')

    def test_default_policy_replays_a_related_wrong_repeat_and_settings_can_restore_silence(self):
        self.execute('Что это?')
        self.assertEqual(self.execute('первый второй', '2').output_text, 'Первый второй третий')
        self.write_settings('{"on_mismatch": "silent"}')
        self.assertEqual(self.execute('первый второй', '3').output_text, 'NO_REPLY')
        self.assertEqual(self.execute('первый второй третий', '4').output_text, 'четвёртый пятый шестой')

    def test_settings_file_location_can_be_configured(self):
        other = Path(self.tmp.name) / 'elsewhere.json'
        other.write_text('{"words_per_portion": 2}', encoding='utf-8')
        plugin = EchoPlugin(Path(self.tmp.name), generate=lambda *args: 'Первый второй третий четвёртый', settings_file=other)
        plugin.capture(user_message='Что это?', **self.kw)
        text = plugin.execute(request={}, next_call=lambda r: None, **self.kw).output_text
        self.assertEqual(text, 'Первый второй')


if __name__ == '__main__':
    unittest.main()
