import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace as S

from echo_sync.engine import EchoEngine
from echo_sync.generator import PrivateCodexGenerator
from engine_say import engine_reply


class BlockingStream:
    def __init__(self, blocked, release, completed):
        self.blocked = blocked
        self.release = release
        self.completed = completed
        self.next_count = 0
        self.closed = False

    def __iter__(self):
        return self

    def __next__(self):
        self.next_count += 1
        if self.next_count == 1:
            return S(type='response.output_text.delta', delta='private delta')
        if self.next_count == 2:
            self.blocked.set()
            if not self.release.wait(5):
                raise RuntimeError('controlled stream timed out')
            return self.completed
        raise StopIteration

    def close(self):
        self.closed = True


class StaleCompletion:
    type = 'response.completed'

    def __init__(self):
        self.response_accesses = 0

    @property
    def response(self):
        self.response_accesses += 1
        return S(output=[S(type='message', content=[S(type='output_text', text='Устаревший ответ.')])])


class StaleGenerationCancellationTests(unittest.TestCase):
    def test_failed_question_claim_removes_only_its_uncommitted_generation_token(self):
        calls = []

        class Generator:
            def generate_cancellable(self, *args, **kwargs):
                calls.append((args, kwargs))
                return 'Should never run.'

        with tempfile.TemporaryDirectory() as tmp:
            engine = EchoEngine(Path(tmp) / 'state.db', Generator())
            other_event = threading.Event()
            engine._active_generations['another-session'] = (4, other_event)
            with engine._db() as db:
                db.execute("CREATE TRIGGER fail_question_claim BEFORE INSERT ON sessions BEGIN SELECT RAISE(ABORT, 'forced'); END")
            with self.assertRaisesRegex(Exception, 'forced'):
                engine_reply(engine, session_id='failed-session', turn_id='question', text='Что произошло?', request={}, model='fixture')
            self.assertNotIn('failed-session', engine._active_generations)
            self.assertIs(engine._active_generations['another-session'][1], other_event)
            self.assertFalse(other_event.is_set())
            self.assertEqual(calls, [])

    def test_out_of_order_claim_cannot_replace_a_newer_session_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = EchoEngine(Path(tmp) / 'state.db', lambda *args: 'unused')
            newer = threading.Event()
            stale = threading.Event()
            engine._active_generations['same-session'] = (3, newer)
            engine._update_generation_tracking('same-session', 2, stale, True)
            self.assertIs(engine._active_generations['same-session'][1], newer)
            self.assertFalse(newer.is_set())
            self.assertTrue(stale.is_set())

    def test_new_question_does_not_cancel_another_session(self):
        release = {'A': threading.Event(), 'B': threading.Event()}
        started = {'A': threading.Event(), 'B': threading.Event()}
        tokens = {}

        class ControlledGenerator:
            def generate_cancellable(self, question, history, context, request, model, *, cancellation_event, is_current):
                label = question[-2]
                if question.startswith('Новая'):
                    return 'Новый ответ для сессии A.'
                tokens[label] = cancellation_event
                started[label].set()
                if not release[label].wait(5):
                    raise RuntimeError('controlled generator timed out')
                if cancellation_event.is_set() or not is_current():
                    raise RuntimeError('generation superseded')
                return f'Ответ старой сессии {label} остался актуальным.'

        with tempfile.TemporaryDirectory() as tmp:
            engine = EchoEngine(Path(tmp) / 'state.db', ControlledGenerator())
            results = {}
            threads = [
                threading.Thread(target=lambda sid=sid, label=label: results.setdefault(label, engine_reply(engine, 
                    session_id=sid, turn_id='old', text=f'Старый вопрос {label}?', request={}, model='fixture')))
                for sid, label in [('session-A', 'A'), ('session-B', 'B')]
            ]
            for thread in threads:
                thread.start()
            self.assertTrue(started['A'].wait(2))
            self.assertTrue(started['B'].wait(2))
            self.assertEqual(engine_reply(engine, session_id='session-A', turn_id='new', text='Новая тема для A?', request={}, model='fixture'), 'Новый ответ')
            self.assertTrue(tokens['A'].is_set())
            self.assertFalse(tokens['B'].is_set())
            release['A'].set()
            release['B'].set()
            for thread in threads:
                thread.join(6)
                self.assertFalse(thread.is_alive())
            self.assertEqual(results['A'], 'NO_REPLY')
            self.assertEqual(engine.state('session-B')['answer'], 'Ответ старой сессии B остался актуальным.')

    def test_stop_cancels_active_generation_in_that_session(self):
        started, release = threading.Event(), threading.Event()
        token = []

        class ControlledGenerator:
            def generate_cancellable(self, question, history, context, request, model, *, cancellation_event, is_current):
                token.append(cancellation_event)
                started.set()
                if not release.wait(5):
                    raise RuntimeError('controlled generator timed out')
                if cancellation_event.is_set() or not is_current():
                    raise RuntimeError('generation stopped')
                return 'This answer must not be saved.'

        with tempfile.TemporaryDirectory() as tmp:
            engine = EchoEngine(Path(tmp) / 'state.db', ControlledGenerator())
            result = []
            thread = threading.Thread(target=lambda: result.append(engine_reply(engine, 
                session_id='stop-session', turn_id='question', text='Объясни?', request={}, model='fixture')))
            thread.start()
            self.assertTrue(started.wait(2))
            self.assertEqual(engine_reply(engine, session_id='stop-session', turn_id='stop', text='стоп', request={}, model='fixture'), 'NO_REPLY')
            self.assertTrue(token[0].is_set())
            release.set()
            thread.join(6)
            self.assertFalse(thread.is_alive())
            self.assertEqual(result, ['NO_REPLY'])
            self.assertEqual(engine.state('stop-session')['answer'], '')

    def test_new_question_cancels_old_same_session_stream_and_closes_resources(self):
        blocked, release = threading.Event(), threading.Event()
        stale_completion = StaleCompletion()
        old_stream = BlockingStream(blocked, release, stale_completion)
        old_client_closed = threading.Event()
        new_client_closed = threading.Event()

        class Client:
            def __init__(self, **kwargs):
                self.responses = self
                self.is_old = False

            def create(self, **kwargs):
                question = kwargs['input'][0]['content'][0]['text']
                self.is_old = question == 'Старый вопрос?'
                if self.is_old:
                    return old_stream
                return [S(type='response.completed', response=S(output=[S(type='message', content=[S(type='output_text', text='Новый ответ актуален.')])]))]

            def close(self):
                (old_client_closed if self.is_old else new_client_closed).set()

        generator = PrivateCodexGenerator(
            resolve=lambda: {'api_key': 'header.payload.signature', 'base_url': 'https://chatgpt.com/backend-api/codex'},
            client_factory=Client,
            headers=lambda *args, **kwargs: {},
        )
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / 'state.db'
            engine = EchoEngine(state_path, generator)
            newer_engine = EchoEngine(state_path, generator)
            old_result = []
            old_thread = threading.Thread(target=lambda: old_result.append(engine_reply(engine, 
                session_id='same-session', turn_id='old', text='Старый вопрос?', request={}, model='fixture')))
            old_thread.start()
            self.assertTrue(blocked.wait(2), 'old generation should be consuming its controlled stream')
            # Candidate 7: «Новый вопрос?» is an examiner's move-on line now (c7-meta round 2: retired quietly, nothing asked); the new question is a content one.
            new_result = engine_reply(newer_engine, session_id='same-session', turn_id='new', text='Почему трава зелёная?', request={}, model='fixture')
            self.assertEqual(new_result, 'Новый ответ актуален.')
            self.assertTrue(new_client_closed.is_set())
            release.set()
            old_thread.join(6)
            self.assertFalse(old_thread.is_alive())
            self.assertEqual(old_result, ['NO_REPLY'])
            self.assertEqual(newer_engine.state('same-session')['answer'], 'Новый ответ актуален.')
        self.assertEqual(old_stream.next_count, 2, 'cancellation is observed at the first event returned after it is requested')
        self.assertEqual(stale_completion.response_accesses, 0, 'a stale completed response must not be parsed')
        self.assertTrue(old_stream.closed)
        self.assertTrue(old_client_closed.is_set())


if __name__ == '__main__':
    unittest.main()





