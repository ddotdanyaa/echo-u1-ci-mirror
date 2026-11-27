"""User iPhone transcript regressions; deterministic controller, no cloud calls."""
import tempfile
import unittest
from pathlib import Path

from echo_sync.classifier import analyze
from echo_sync.engine import EchoEngine
from engine_say import engine_reply


class FieldQuestionRegressions(unittest.TestCase):
    def test_teacher_and_user_field_queries_replace_waiting_answer(self):
        queries = (
            'Так а 15-я статья налогового кодекса',
            'Так скажи 15-я статья налогового кодекса что это',
            'Приведите пример',
            'Уточните определение',
            'Закон Архимеда что это',
        )
        for preset in ('strict_triples', 'adaptive', 'slow'):
            for query in queries:
                with self.subTest(preset=preset, query=query), tempfile.TemporaryDirectory() as td:
                    calls = []
                    def generate(question, history, *args):
                        calls.append((question, history))
                        return 'Первый ответ содержит несколько удобных порций для проверки состояния.'
                    engine = EchoEngine(Path(td) / 'state.db', generate, settings={'preset': preset})
                    engine_reply(engine, session_id='s', turn_id='q1', text='Что такое плотность?', request={}, model='fixture')
                    reply = engine_reply(engine, session_id='s', turn_id='q2', text=query, request={}, model='fixture')
                    self.assertEqual(engine.state('s')['revision'], 2)
                    self.assertEqual(len(calls), 2)
                    self.assertEqual(len(calls[-1][1]), 1)
                    self.assertEqual(reply, engine.state('s')['chunks'][0])

    def test_background_reference_narration_and_partial_repeat_do_not_replace(self):
        waiting = {'chunks': ['Статья 15 налогового', 'кодекса упоминается здесь.'],
                   'chunk_index': 0, 'completed': False, 'pending_turn': None}
        for phrase in ('Статья 15', 'Статья 15 говорит о другом', 'я сейчас продолжу объяснение'):
            with self.subTest(phrase=phrase):
                self.assertNotIn(analyze(phrase, waiting, []).kind, ('question', 'ack'))

    def test_initial_greeting_gives_local_readiness_without_model_or_cursor(self):
        with tempfile.TemporaryDirectory() as td:
            calls = []
            engine = EchoEngine(Path(td) / 'state.db', lambda *a: calls.append(a))
            first = engine_reply(engine, session_id='s', turn_id='hello', text='Привет', request={}, model='fixture')
            self.assertEqual(first, 'Я готов. Задайте вопрос.')
            self.assertEqual(engine_reply(engine, session_id='s', turn_id='hello', text='Привет', request={}, model='fixture'), first)
            self.assertEqual(calls, [])
            self.assertIsNone(engine.state('s'))
            engine.generate = lambda *a: 'Новый ответ состоит из нескольких произносимых порций.'
            engine_reply(engine, session_id='s', turn_id='question', text='Что это такое?', request={}, model='fixture')
            self.assertEqual(engine_reply(engine, session_id='s', turn_id='hello', text='Привет', request={}, model='fixture'), 'NO_REPLY')
            self.assertEqual(engine.state('s')['chunk_index'], 0)


if __name__ == '__main__':
    unittest.main()
