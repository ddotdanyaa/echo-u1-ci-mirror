import unittest
from types import SimpleNamespace as S

try:
    from echo_sync.generator import PrivateCodexGenerator
except ImportError:
    PrivateCodexGenerator = None


class GeneratorTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(PrivateCodexGenerator, 'Private no-display generator has not been implemented')

    def test_consumes_private_stream_without_callbacks_and_keeps_full_context(self):
        seen = []
        class Client:
            def __init__(self, **kw):
                self.responses = self
            def create(self, **kw):
                seen.append(kw)
                return iter([S(type='response.output_text.delta', delta='FULL ANSWER SHOULD STAY PRIVATE'), S(type='response.completed', response=S(output=[S(type='message', content=[S(type='output_text', text='Полный приватный ответ на вопрос.')])], status='completed', usage=S(input_tokens=1,output_tokens=1,total_tokens=2)))])
            def close(self):
                pass
        gen = PrivateCodexGenerator(resolve=lambda: {'api_key':'header.payload.signature', 'base_url':'https://chatgpt.com/backend-api/codex'}, client_factory=Client, headers=lambda *a, **k: {})
        answer = gen('Как?', [{'question':'Что?', 'answer':'Полный старый ответ.'}], 'Данные документа', {'input': [], 'instructions':'Original', 'tools':[{'type':'function'}], 'tool_choice':'auto'}, 'gpt-5-codex')
        self.assertEqual(answer, 'Полный приватный ответ на вопрос.')
        self.assertIn('Полный старый ответ.', seen[0]['instructions'])
        self.assertIn('Данные документа', seen[0]['instructions'])
        self.assertNotIn('tools', seen[0])
        self.assertNotIn('tool_choice', seen[0])
        self.assertTrue(seen[0]['stream'])
        self.assertEqual(seen[0]['input'], [{'role': 'user', 'content': [{'type': 'input_text', 'text': 'Как?'}]}])
        self.assertNotIn('Original', seen[0]['instructions'])

    def test_rejects_api_key_or_custom_endpoint_before_creating_client(self):
        for credentials in [{'api_key':'sk-api-key', 'base_url':'https://chatgpt.com/backend-api/codex'}, {'api_key':'a.b.c', 'base_url':'https://api.openai.com/v1'}]:
            gen = PrivateCodexGenerator(resolve=lambda: credentials, client_factory=lambda **kw: self.fail('must not construct client'), headers=lambda *a, **k: {})
            with self.assertRaises(ValueError):
                gen('Что?', [], '', {}, 'gpt-5-codex')


if __name__ == '__main__':
    unittest.main()
