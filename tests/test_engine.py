import tempfile
import unittest
from pathlib import Path

try:
    from echo_sync.engine import EchoEngine
except ImportError:
    EchoEngine = None
from engine_say import engine_reply


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(EchoEngine, 'EchoEngine feature has not been implemented')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.calls = []
        def generate(question, history, context, request, model):
            self.calls.append((question, history, context))
            return 'Первый второй третий, четвёртый пятый шестой. Седьмой восьмой.'
        self.generate = generate
        self.engine = EchoEngine(Path(self.tmp.name) / 'state.db', generate, context='Документы о компании')

    def turn(self, text, turn='1', sid='s1'):
        return engine_reply(self.engine, session_id=sid, turn_id=turn, text=text, request={}, model='gpt-test')

    def test_one_generation_then_exact_cyrillic_repeats(self):
        self.assertEqual(self.turn('Почему это работает?'), 'Первый второй третий,')
        self.assertEqual(self.turn('Первый второй третий!', '2'), 'четвёртый пятый шестой.')
        self.assertEqual(self.turn('ЧЕТВЕРТЫЙ пятый шестой', '3'), 'Седьмой восьмой.')
        self.assertEqual(self.turn('седьмой восьмой', '4'), 'NO_REPLY')
        self.assertEqual(len(self.calls), 1)

    def test_wrong_missing_and_repeat_never_advance(self):
        # The pre-2026-10-21 contract: a wrong repeat is answered with silence.
        # The default is now on_mismatch="replay_if_attempt" (see test_turn_policy.py).
        self.engine.settings = {'on_mismatch': 'silent'}
        self.turn('Вопрос: объясни систему')
        for i, text in enumerate(['Первый второй', '', 'не знаю']):
            self.assertEqual(self.turn(text, str(i + 2)), 'NO_REPLY')
        for i, text in enumerate(['повтори', 'еще раз']):
            self.assertEqual(self.turn(text, str(i + 10)), 'Первый второй третий,')
        self.assertEqual(len(self.calls), 1)

    def test_default_policy_replays_a_related_wrong_repeat_but_never_advances(self):
        self.turn('Вопрос: объясни систему')
        self.assertEqual(self.turn('Первый второй', '2'), 'Первый второй третий,')
        self.assertEqual(self.turn('', '3'), 'NO_REPLY')
        self.assertEqual(self.turn('не знаю', '4'), 'NO_REPLY')
        self.assertEqual(self.engine.state('s1')['chunk_index'], 0)
        self.assertEqual(len(self.calls), 1)

    def test_same_turn_retry_does_not_double_advance(self):
        self.turn('Что это?')
        a = self.turn('первый второй третий', 'same')
        self.assertEqual(self.turn('первый второй третий', 'same'), a)
        self.assertEqual(self.engine.state('s1')['chunk_index'], 1)

    def test_state_and_full_context_survive_restart_and_new_question(self):
        self.turn('Что это?')
        self.turn('первый второй третий', '2')
        restarted = EchoEngine(Path(self.tmp.name) / 'state.db', self.generate)
        self.assertEqual(engine_reply(restarted, session_id='s1', turn_id='3', text='повтори', request={}, model='gpt-test'), 'четвёртый пятый шестой.')
        self.assertEqual(self.turn('Как это применить?', '4'), 'Первый второй третий,')
        self.assertEqual(self.calls[-1][1][0]['answer'], self.engine.state('s1')['history'][0]['answer'])
        self.assertIn('Седьмой восьмой', self.calls[-1][1][0]['answer'])
        self.assertEqual(self.engine.state('s1')['revision'], 2)

    def test_sessions_are_separate(self):
        self.turn('Что это?')
        self.assertEqual(self.turn('первый второй третий', '2', sid='other'), 'NO_REPLY')
        self.assertEqual(self.engine.state('s1')['chunk_index'], 0)

    def test_failed_new_question_stops_previous_answer_and_preserves_history(self):
        self.turn('Что это?')
        self.engine.generate = lambda *args: (_ for _ in ()).throw(RuntimeError('offline'))
        self.assertEqual(self.turn('Почему сломалось?', '2'), 'NO_REPLY')
        self.assertEqual(self.engine.state('s1')['revision'], 2)
        self.assertEqual(self.turn('повтори', '3'), 'NO_REPLY')
        self.assertEqual(self.turn('первый второй третий', '4'), 'NO_REPLY')
        self.assertEqual(len(self.engine.state('s1')['history']), 1)

    def test_prepared_question_uses_zero_provider_calls(self):
        self.engine.qa = [{'question': 'Как работает бюджет?', 'answer': 'Доходы покрывают наши расходы. Остаток сохраняем.'}]
        self.assertEqual(self.turn('Вопрос: как работает бюджет'), 'Доходы покрывают наши')
        self.assertEqual(self.turn('доходы покрывают наши', '2'), 'расходы. Остаток сохраняем.')
        self.assertEqual(self.calls, [])

    def test_correction_and_exam_imperative_start_new_revisions(self):
        self.turn('Что это?')
        self.turn('Нет, это неверно. Объясните иначе', '2')
        self.turn('Назовите состав финансовой системы', '3')
        self.assertEqual(len(self.calls), 3)
        self.assertEqual(self.engine.state('s1')['revision'], 3)

    def test_new_question_can_finish_before_blocked_old_generation_and_old_result_is_discarded(self):
        import threading
        started, release = threading.Event(), threading.Event()
        returned = []
        def generate(question, *args):
            if question == 'Старый вопрос?':
                started.set()
                if not release.wait(5):
                    raise RuntimeError('test timed out')
                return 'Старый ответ уже запрещен'
            return 'Новый ответ сейчас актуален'
        self.engine.generate = generate
        thread = threading.Thread(target=lambda: returned.append(self.turn('Старый вопрос?', 'old')))
        thread.start()
        self.assertTrue(started.wait(2))
        new_done = threading.Event()
        new_results = []
        # Candidate 7: «Новый вопрос?» is an examiner's move-on line now (c7-meta round 2: retired quietly, nothing asked); the new question is a content one.
        newer = threading.Thread(target=lambda: (new_results.append(self.turn('Почему трава зелёная?', 'new')), new_done.set()))
        newer.start()
        try:
            self.assertTrue(new_done.wait(1), 'A new question must not wait for the old provider request')
            self.assertEqual(new_results, ['Новый ответ сейчас'])
        finally:
            release.set()
            thread.join(6)
            newer.join(6)
        self.assertFalse(thread.is_alive())
        self.assertEqual(returned, ['NO_REPLY'])
        self.assertEqual(self.engine.state('s1')['answer'], 'Новый ответ сейчас актуален')

    def test_stop_invalidates_active_revision(self):
        # CL2, ruling 1: «стоп» is a pause. The revision of what was playing is stale (a retried old turn speaks nothing), but the
        # plan is kept: «повтори» speaks the paused portion again and its repeat goes on to the next one.
        first = self.turn('Что это?', '1')
        revision = self.engine.state('s1')['revision']
        self.assertEqual(self.turn('стоп', '2'), 'NO_REPLY')
        self.assertGreater(self.engine.state('s1')['revision'], revision)
        self.assertEqual(self.turn('Что это?', '1'), 'NO_REPLY')
        self.assertEqual(self.turn('повтори', '3'), first)
        self.assertEqual(self.turn('первый второй третий', '4'), 'четвёртый пятый шестой.')

    def test_retry_of_old_turn_after_new_question_cannot_replay_old_chunk(self):
        self.turn('Что это?', 'old')
        self.turn('Как это работает?', 'new')
        self.assertEqual(self.turn('Что это?', 'old'), 'NO_REPLY')

    def test_standalone_punctuation_is_not_counted_as_a_spoken_word(self):
        self.engine.qa = [{'question':'Что такое доходы?', 'answer':'Доходы — это деньги, полученные нашей компанией.'}]
        self.assertEqual(self.turn('Что такое доходы?'), 'Доходы — это деньги,')
        self.assertEqual(self.turn('доходы это деньги', '2'), 'полученные нашей компанией.')


if __name__ == '__main__':
    unittest.main()
