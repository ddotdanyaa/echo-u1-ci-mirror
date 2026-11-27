"""Deterministic teacher-questioning conversation stress scenarios for EchoEngine."""
import random
import tempfile
import unittest
from pathlib import Path

from echo_sync.engine import EchoEngine, SILENT
from engine_say import engine_reply


SEED = 20261021
PRESETS = ('strict_triples', 'adaptive', 'slow')
LONG_QUESTION = (
    'Почему учитель после объяснения правила просит ученика сравнить два примера, назвать каждое условие, '
    'проверить исходные данные, объяснить порядок действий, указать возможное исключение, привести '
    'контрпример, оценить результат и рассказать, как этот способ применить в новой задаче на следующем уроке, '
    'а затем проверить правильность окончательного ответа вместе?'
)
ANSWER_BY_QUESTION = {
    'Почему?': '12 важных показателей помогают учителю объяснить работу сложной вычислительной системы и проверить понимание ученика в конкретной ситуации.',
    'Почему учитель задаёт этот вопрос?': '24 ключевых признака помогают связать объяснение с новой учебной задачей и проверить понимание ученика.',
    'Что делает другой ученик?': '6 важных этапов помогают другому ученику повторить решение и проверить результат самостоятельно.',
    'Что означает определение налога?': 'Налоговая база — это стоимостная, физическая или иная характеристика объекта налогообложения, используемая для расчёта обязательного платежа. Размер базы определяется отдельно для каждого налога и периода.',
    'Как показать это на примере?': 'Представьте школьный сад, где каждый класс ухаживает за одной грядкой; например, ученики записывают дату посадки, измеряют рост растений и сравнивают результаты в конце месяца.',
    'Как рассчитать скорость?': '15 километров за 3 часа дают среднюю скорость 5 километров в час, если движение было равномерным и остановки не учитывались при измерении времени.',
    'Как прочитать номер статьи?': 'Статья 228 закона № 12 описывает отдельное правило, а дата 2024 года относится к редакции документа и служит идентификатором нужной версии текста.',
    'Что означает ВВП в долгосрочном прогнозе?': 'ВВП показывает совокупную стоимость произведённых товаров и услуг; долгосрочный прогноз сравнивает несколько лет, учитывая изменения цен, производительности и населения.',
    'Как действует отрицательное правило?': 'Если условие не выполнено, действие не разрешается; исключение действует только тогда, когда отдельное правило прямо отменяет этот запрет для указанного случая.',
    'Приведите пример': 'Пример показывает правило на конкретном случае и помогает проверить, понял ли ученик связь между условием и результатом.',
    'Уточните ход вычисления': 'Сначала выполняется умножение, затем сложение, поэтому порядок действий сохраняет однозначный результат при одинаковых исходных числах.',
    'Уточните определение': 'Определение называет основные признаки понятия и помогает отличить его от похожих терминов в учебной теме.',
    'Почему учитель просит привести пример после длинного объяснения?': 'Короткий пример помогает связать правило с реальным действием и проверить понимание материала.',
    LONG_QUESTION: 'Короткий пример помогает связать правило с реальным действием и проверить понимание материала.',
}

CONTENT_FIXTURES = (
    ('definition', 'Что означает определение налога?', {}),
    ('explanation_example', 'Как показать это на примере?', {}),
    ('arithmetic_units', 'Как рассчитать скорость?', {}),
    ('date_law_number', 'Как прочитать номер статьи?', {}),
    ('abbreviation_long_term', 'Что означает ВВП в долгосрочном прогнозе?', {'abbreviations': {'ВВП': 'валовой внутренний продукт'}}),
    ('negated_rule', 'Как действует отрицательное правило?', {}),
)


class TeacherScenarioTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def make_engine(self, preset, name, extra_settings=None):
        calls = []

        def generate(question, history, context, request, model):
            calls.append((question, tuple(history)))
            return ANSWER_BY_QUESTION[question]

        path = Path(self.tmp.name) / f'{name}.sqlite3'
        settings = {'preset': preset, **(extra_settings or {})}
        return EchoEngine(path, generate, settings=settings), calls, path

    @staticmethod
    def send(engine, session, turn, text):
        return engine_reply(engine, session_id=session, turn_id=turn, text=text, request={}, model='scenario-fixture')

    def assert_waiting_invariants(self, state, index, revision):
        self.assertIsNotNone(state)
        self.assertEqual(state['chunk_index'], index)
        self.assertEqual(state['revision'], revision)
        self.assertFalse(state['pending_turn'])
        self.assertFalse(state['completed'])
        self.assertTrue(state['chunks'])

    def test_teacher_clarification_and_stt_noise_do_not_advance_under_each_preset(self):
        """Short/long question entry followed by silence, partial/wrong ACKs and clarification."""
        failure_events = [
            ('teacher_clarification', 'не расслышал'),
            ('repeat', 'повтори пожалуйста'),
            ('partial_ack', '12'),
            ('reordered_ack', 'показателей важных 12'),
            ('missing_word_ack', '12 показателей'),
            ('wrong_number', '13'),
            ('silence', ''),
            ('unrelated_background', 'я сегодня принёс тетрадь и ручку'),
        ]
        observed = 0
        for preset in PRESETS:
            with self.subTest(preset=preset):
                engine, calls, _ = self.make_engine(preset, f'noise-{preset}')
                first = self.send(engine, 'learner', 'short-question', 'Почему?')
                state = engine.state('learner')
                self.assertEqual(first, state['chunks'][0])
                self.assertEqual(state['question'], 'Почему?')
                self.assertEqual(state['revision'], 1)
                self.assertEqual(len(calls), 1)
                waiting = state['chunks'][0]
                self.assertIn('12', waiting)

                # The seed fixes the event order while varying it reproducibly per preset.
                ordered = list(failure_events)
                random.Random(SEED + PRESETS.index(preset)).shuffle(ordered)
                for index, (label, utterance) in enumerate(ordered):
                    with self.subTest(preset=preset, event=label):
                        before = engine.state('learner')
                        result = self.send(engine, 'learner', f'noise-{index}', utterance)
                        after = engine.state('learner')
                        self.assert_waiting_invariants(after, 0, 1)
                        self.assertEqual(after['answer'], before['answer'])
                        self.assertIn(result, (SILENT, waiting))
                        self.assertEqual(len(calls), 1, 'noise and partial replies must not generate a new answer')
                        observed += 1

                # Case and punctuation differences are acceptable ACK evidence.
                moved = self.send(engine, 'learner', 'case-ack', waiting.upper() + '!')
                state = engine.state('learner')
                self.assertEqual(state['chunk_index'], 1)
                self.assertIn(moved, (SILENT, state['chunks'][state['chunk_index']]))

    def test_teacher_new_question_supersedes_and_old_turns_stay_silent_after_reconnect(self):
        for preset in PRESETS:
            with self.subTest(preset=preset):
                engine, calls, path = self.make_engine(preset, f'reconnect-{preset}')
                original = self.send(engine, 'learner', 'q-short', 'Почему?')
                self.assertEqual(original, engine.state('learner')['chunks'][0])
                replacement = self.send(engine, 'learner', 'teacher-followup', 'Почему учитель задаёт этот вопрос?')
                state = engine.state('learner')
                self.assertEqual(state['revision'], 2)
                self.assertEqual(state['question'], 'Почему учитель задаёт этот вопрос?')
                self.assertEqual(replacement, state['chunks'][0])
                self.assertEqual(len(calls), 2)
                # An old client retry must not resurrect the replaced answer.
                self.assertEqual(self.send(engine, 'learner', 'q-short', 'Почему?'), SILENT)
                self.assertEqual(engine.state('learner')['revision'], 2)

                ack = self.send(engine, 'learner', 'followup-ack', replacement.upper())
                state = engine.state('learner')
                self.assertEqual(state['chunk_index'], 1)
                restarted = EchoEngine(path, lambda *args: self.fail('reconnect retry must use durable state'), settings={'preset': preset})
                # Replayed IDs from before progress are obsolete after process restart.
                self.assertEqual(self.send(restarted, 'learner', 'teacher-followup', 'Почему учитель задаёт этот вопрос?'), SILENT)
                before_retry = restarted.state('learner')
                self.assertEqual(self.send(restarted, 'learner', 'followup-ack', replacement.upper()), ack)
                after_retry = restarted.state('learner')
                self.assertEqual(after_retry['chunk_index'], before_retry['chunk_index'],
                                 'retrying the same current ACK may re-deliver its reply but cannot advance twice')
                current = EchoEngine.current(restarted.state('learner'))
                self.assertEqual(self.send(restarted, 'learner', 'resume-current', current),
                                 SILENT if restarted.state('learner')['completed'] else restarted.state('learner')['chunks'][restarted.state('learner')['chunk_index']])
                self.assertEqual(restarted.state('learner')['revision'], 2)

    def test_background_session_continues_independently_while_teacher_switches_topics(self):
        for preset in PRESETS:
            with self.subTest(preset=preset):
                engine, calls, _ = self.make_engine(preset, f'background-{preset}')
                learner = self.send(engine, 'learner-a', 'a-question', 'Почему?')
                observer = self.send(engine, 'learner-b', 'b-question', 'Что делает другой ученик?')
                a_before, b_before = engine.state('learner-a'), engine.state('learner-b')
                self.assertEqual(a_before['chunk_index'], 0)
                self.assertEqual(b_before['chunk_index'], 0)
                self.assertEqual(len(calls), 2)

                self.send(engine, 'learner-b', 'b-ack', observer.upper())
                a_after, b_after = engine.state('learner-a'), engine.state('learner-b')
                self.assertEqual(a_after['revision'], a_before['revision'])
                self.assertEqual(a_after['chunk_index'], 0, 'another learner must not advance this answer')
                self.assertEqual(b_after['chunk_index'], 1)

                # A long follow-up in one session replaces that session only.
                self.send(engine, 'learner-a', 'a-followup', 'Почему учитель задаёт этот вопрос?')
                a_final, b_final = engine.state('learner-a'), engine.state('learner-b')
                self.assertEqual(a_final['revision'], 2)
                self.assertEqual(b_final['revision'], b_after['revision'])
                self.assertEqual(b_final['chunk_index'], 1)

    def test_six_content_fixtures_drain_with_midanswer_noise_and_restart_retries(self):
        """Drain each answer across all chunking modes with mismatch and reconnect events."""
        completed = 0
        for preset in PRESETS:
            for fixture_index, (label, question, extra_settings) in enumerate(CONTENT_FIXTURES):
                with self.subTest(preset=preset, fixture=label):
                    engine, calls, path = self.make_engine(preset, f'content-{preset}-{label}', extra_settings)
                    session = f'{preset}-{label}'
                    first = self.send(engine, session, 'question', question)
                    state = engine.state(session)
                    self.assertEqual(first, state['chunks'][0])
                    self.assertEqual(len(calls), 1)
                    self.assertGreaterEqual(len(state['chunks']), 3)
                    injection_index = 0 if label == 'arithmetic_units' else fixture_index % len(state['chunks'])
                    injected = False
                    last_ack_turn = None
                    last_ack_text = None
                    last_ack_reply = None
                    while not state['completed']:
                        position = state['chunk_index']
                        chunk = state['chunks'][position]
                        if not injected and position == injection_index:
                            if label == 'arithmetic_units':
                                # Same full spoken phrase, but change the numeric value.
                                wrong = chunk.replace('15', '16', 1)
                                self.assertNotEqual(wrong, chunk)
                                expected_number = wrong
                            else:
                                expected_number = None
                                wrong = 'Это посторонний рассказ о погоде и школьном расписании.'
                            before = state
                            response = self.send(engine, session, f'mismatch-{position}', wrong)
                            after = engine.state(session)
                            self.assertEqual(after['chunk_index'], position)
                            self.assertEqual(after['revision'], before['revision'])
                            self.assertEqual(after['answer'], before['answer'])
                            self.assertIn(response, (SILENT, chunk))
                            if expected_number is not None:
                                self.assertNotEqual(response, state['chunks'][position + 1] if position + 1 < len(state['chunks']) else None,
                                                    'changing a number in the complete phrase must not advance')
                            self.assertEqual(len(calls), 1, 'mismatch events cannot invoke the answer generator')
                            injected = True
                            state = after
                        last_ack_turn = f'ack-{position}'
                        last_ack_text = chunk
                        last_ack_reply = self.send(engine, session, last_ack_turn, chunk)
                        state = engine.state(session)
                        self.assertEqual(state['chunk_index'], position + 1)
                        self.assertEqual(state['revision'], 1)
                        self.assertEqual(len(calls), 1)
                        if position == 0:
                            # Simulate a reconnect at the middle of a multi-part answer.
                            engine = EchoEngine(path, lambda *args: self.fail('ACK retry should be served from SQLite'),
                                                settings={'preset': preset, **extra_settings})
                            before_retry = engine.state(session)
                            self.assertEqual(self.send(engine, session, last_ack_turn, last_ack_text), last_ack_reply)
                            self.assertEqual(engine.state(session)['chunk_index'], before_retry['chunk_index'])
                            self.assertEqual(self.send(engine, session, 'question', question), SILENT)
                            state = engine.state(session)
                    self.assertTrue(injected, f'{label} should have received one mismatch at index {injection_index}')
                    self.assertTrue(state['completed'])
                    self.assertEqual(state['chunk_index'], len(state['chunks']))
                    self.assertEqual(len(state['history']), 1)
                    completed += 1
        self.assertEqual(completed, len(PRESETS) * len(CONTENT_FIXTURES))

    def test_long_question_and_teacher_imperatives_are_exercised_explicitly(self):
        long_question = LONG_QUESTION
        self.assertGreaterEqual(len(long_question.split()), 40)
        for preset in PRESETS:
            with self.subTest(preset=preset, case='long_question'):
                engine, calls, _ = self.make_engine(preset, f'long-{preset}')
                self.send(engine, 'learner', 'initial', 'Почему?')
                result = self.send(engine, 'learner', 'long-followup', long_question)
                state = engine.state('learner')
                self.assertEqual(state['revision'], 2)
                self.assertEqual(state['question'], long_question)
                self.assertEqual(result, state['chunks'][0])
                self.assertEqual(len(calls), 2)
                self.assertEqual([entry['question'] for entry in state['history']], ['Почему?', long_question])

            for label, command in (('teacher_imperative_example', 'Приведите пример'),
                                   ('teacher_imperative_clarify', 'Уточните определение')):
                with self.subTest(preset=preset, case=label):
                    engine, calls, _ = self.make_engine(preset, f'{label}-{preset}')
                    self.send(engine, 'learner', 'initial', 'Почему?')
                    result = self.send(engine, 'learner', 'teacher-command', command)
                    state = engine.state('learner')
                    self.assertEqual(state['revision'], 2,
                                     f'teacher instruction {command!r} should replace the waiting answer')
                    self.assertEqual(state['question'], command)
                    self.assertEqual(result, state['chunks'][0])
                    self.assertEqual(len(calls), 2)
                    self.assertEqual([entry['question'] for entry in state['history']], ['Почему?', command])


if __name__ == '__main__':
    unittest.main()
