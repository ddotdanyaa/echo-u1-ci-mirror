"""An explicit repair supersedes content; ambiguous disagreement only asks clarification."""
import tempfile
import threading
import unittest
from pathlib import Path

from echo_sync.classifier import analyze
from echo_sync.engine import EchoEngine, SILENT, model_history
from engine_say import engine_reply


def prior(chunk='Ставка равна пяти процентам'):
    return {'schema': 2, 'revision': 4, 'question': 'Какая ставка?', 'answer': chunk,
            'chunks': [chunk, 'Следующая часть'], 'chunk_index': 0, 'completed': False,
            'pending_turn': None, 'history': [{'question': 'Какая ставка?', 'answer': chunk}]}


class RepairClassifierTests(unittest.TestCase):
    def test_explicit_repairs_have_separate_intent_and_preserve_spoken_request(self):
        for text in ('Нет, я имел в виду налог на прибыль', 'Я имела в виду другой год',
                     'Исправь число на шестнадцать', 'Исправьте ответ о ставке',
                     'Поправь дату на двадцать второе октября'):
            with self.subTest(text=text):
                d = analyze(text, prior(), [])
                self.assertEqual(d.kind, 'correction')
                self.assertEqual(d.question, text)
                self.assertIsNone(d.prepared)

    def test_ambiguous_disagreement_requests_clarification_without_new_generation(self):
        for text in ('Это неверно', 'Нет, это неверно', 'Это неправильно', 'Нет, я имел в виду'):
            with self.subTest(text=text):
                self.assertEqual(analyze(text, prior(), []).kind, 'clarify_repair')

    def test_exact_and_partial_expected_chunks_precede_repair_intent(self):
        text = 'Нет я имел в виду налог на прибыль'
        self.assertEqual(analyze(text, prior(text), []).kind, 'ack')
        partial = analyze('Это неверно', prior('Это неверно при такой ставке'), [])
        self.assertIn(partial.kind, ('replay', 'silent'))
        self.assertNotEqual(partial.kind, 'clarify_repair')

    def test_repair_requires_existing_context_and_nonempty_target(self):
        for text in ('Нет', 'Неверно', 'Я имел в виду', 'Неправильно'):
            with self.subTest(text=text):
                self.assertNotIn(analyze(text, None, []).kind, ('correction', 'clarify_repair'))
        for text in ('Он сказал нет я имел в виду другую ставку',
                     'В тексте написано это неверно', 'Нет', 'Да нет наверное'):
            with self.subTest(background=text):
                self.assertNotEqual(analyze(text, prior(), []).kind, 'correction')

    def test_ambiguous_disagreement_under_the_silent_policy_is_a_new_turn_not_a_prompt(self):
        # WAVE 2 / Task A (brief section 4, MULTITURN G4): «Это неправильно» was silence while the disputed portion kept being
        # repeated. The silent policy still never SPEAKS the clarification prompt, but a disagreement is no longer ignored:
        # it retires the answer and goes to the model as a correction (the default profile keeps asking what to correct).
        decision = analyze('Это неправильно', prior(), [], {'on_mismatch': 'silent'})
        self.assertEqual((decision.kind, decision.question), ('correction', 'Это неправильно'))
        self.assertEqual(analyze('Неправильно', prior(), []).kind, 'silent')
        self.assertEqual(analyze('Исправь ставку на пять процентов', prior(), [], {'on_mismatch': 'silent'}).kind, 'correction')


class RepairEngineTests(unittest.TestCase):
    def test_own_clarification_prompt_cannot_start_generation(self):
        with tempfile.TemporaryDirectory() as td:
            calls = []
            def generate(*args):
                calls.append(args)
                return 'Первый полный ответ содержит несколько отдельных частей.'
            e = EchoEngine(Path(td)/'state.db', generate, clock=lambda: 50)
            engine_reply(e, session_id='s', turn_id='q', text='Какая ставка налога?', request={}, model='offline')
            engine_reply(e, session_id='s', turn_id='unclear', text='Это неверно', request={}, model='offline')
            before = e.state('s')
            self.assertEqual(engine_reply(e, session_id='s', turn_id='echo', text='Что именно нужно исправить?', request={}, model='offline'), SILENT)
            self.assertEqual(len(calls), 1)
            self.assertEqual(e.state('s')['revision'], before['revision'])
            self.assertEqual(e.state('s')['chunk_index'], before['chunk_index'])

    def test_repair_cancels_pending_generation_and_drops_its_late_result(self):
        with tempfile.TemporaryDirectory() as td:
            started, release = threading.Event(), threading.Event()
            seen, tokens, first_reply, errors = [], [], [], []
            class Generator:
                def generate_cancellable(self, question, history, *args, cancellation_event, is_current):
                    seen.append((question, list(history)))
                    tokens.append(cancellation_event)
                    if len(seen) == 1:
                        started.set()
                        if not release.wait(5):
                            raise AssertionError('Controlled generation timed out')
                        return 'Старый ответ не должен прозвучать.'
                    return 'Новый ответ относится к исправленному вопросу.'
            e = EchoEngine(Path(td)/'state.db', Generator())
            def first():
                try:
                    first_reply.append(engine_reply(e, session_id='s', turn_id='q', text='Какая ставка налога?', request={}, model='offline'))
                except Exception as exc:
                    errors.append(exc)
            worker = threading.Thread(target=first)
            worker.start()
            try:
                self.assertTrue(started.wait(3))
                self.assertEqual(engine_reply(e, session_id='s', turn_id='unclear', text='Это неверно', request={}, model='offline'), SILENT)
                engine_reply(e, session_id='s', turn_id='repair', text='Нет, я имел в виду другой год', request={}, model='offline')
                self.assertTrue(tokens[0].is_set())
                self.assertEqual(seen[1][1][-1], {'question': 'Какая ставка налога?', 'answer': '', 'incomplete': True})
            finally:
                release.set(); worker.join(5)
            self.assertFalse(worker.is_alive())
            self.assertEqual(errors, [])
            self.assertEqual(first_reply, [SILENT])
            self.assertIn('Новый ответ', e.state('s')['answer'])
            self.assertEqual(e.state('s')['revision'], 2)

    def test_repair_generates_once_retains_history_and_invalidates_old_turn(self):
        with tempfile.TemporaryDirectory() as td:
            calls = []
            def generate(question, history, *args):
                calls.append((question, list(history)))
                return 'Первый полный ответ содержит несколько отдельных частей.' if len(calls) == 1 else 'Исправленный ответ содержит новую проверенную формулировку.'
            e = EchoEngine(Path(td)/'state.db', generate)
            engine_reply(e, session_id='s', turn_id='q', text='Какая ставка налога?', request={}, model='offline')
            before = e.state('s')
            text = 'Нет, я имел в виду другой год'
            reply = engine_reply(e, session_id='s', turn_id='repair', text=text, request={}, model='offline')
            after = e.state('s')
            self.assertEqual(len(calls), 2)
            self.assertEqual(calls[-1][0], text)
            # CL2, ruling 3: the stored history also keeps the conversation map (at, chunks, spoken, status); the model is given the
            # questions and answers of it, never that bookkeeping.
            self.assertEqual(calls[-1][1], model_history(before['history']))
            self.assertEqual(after['revision'], before['revision']+1)
            self.assertEqual(after['chunk_index'], 0)
            self.assertIn('Исправленный', after['answer'])
            self.assertEqual(engine_reply(e, session_id='s', turn_id='repair', text=text, request={}, model='offline'), reply)
            self.assertEqual(len(calls), 2)
            self.assertEqual(engine_reply(e, session_id='s', turn_id='q', text='Какая ставка налога?', request={}, model='offline'), SILENT)

    def test_ambiguous_repair_does_not_change_answer_cursor_or_history(self):
        with tempfile.TemporaryDirectory() as td:
            calls = []
            def generate(*args):
                calls.append(1)
                return 'Первый полный ответ содержит несколько отдельных частей.'
            e = EchoEngine(Path(td)/'state.db', generate)
            engine_reply(e, session_id='s', turn_id='q', text='Какая ставка налога?', request={}, model='offline')
            before = e.state('s')
            reply = engine_reply(e, session_id='s', turn_id='unclear', text='Это неверно', request={}, model='offline')
            self.assertEqual(reply, 'Что именно нужно исправить?')
            after = e.state('s')
            for key in ('revision','chunk_index','answer','chunks','history','pending_turn'):
                self.assertEqual(after[key], before[key], key)
            self.assertEqual(len(calls), 1)


if __name__ == '__main__':
    unittest.main()
