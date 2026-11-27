"""Bounded short contextual follow-ups; real classifier/engine, no model calls."""
import tempfile
import threading
import unittest
from pathlib import Path

from echo_sync.classifier import ACK, QUESTION, QUIET, REPLAY, analyze
from echo_sync.engine import EchoEngine, SILENT
from engine_say import engine_reply


PHRASES = ('Почему так', 'Что это', 'А пример')
PRESETS = ('strict_triples', 'adaptive', 'slow')


def prior_state(*, completed=False, chunk='Первая часть ответа.'):
    return {
        'revision': 1,
        'question': 'Что такое налоговая база?',
        'answer': 'Полный ответ содержит несколько частей и уже сохранён.',
        'chunks': [chunk],
        'chunk_index': 0,
        'completed': completed,
        'pending_turn': None,
        'history': [{'question': 'Что такое налоговая база?',
                     'answer': 'Полный ответ содержит несколько частей и уже сохранён.'}],
    }


class ShortFollowupClassifierTests(unittest.TestCase):
    def test_bounded_followups_are_questions_with_context_or_without_state(self):
        for phrase in PHRASES:
            for state in (prior_state(), prior_state(completed=True), None):
                with self.subTest(phrase=phrase, state='none' if state is None else state['completed']):
                    decision = analyze(phrase, state, [])
                    self.assertEqual(decision.kind, QUESTION)
                    self.assertEqual(decision.question, phrase)

    def test_configured_leading_fillers_preserve_the_short_followup_intent(self):
        for phrase in ('Ну почему так', 'Так а что это', 'Ну а пример'):
            with self.subTest(phrase=phrase):
                decision = analyze(phrase, prior_state(), [])
                self.assertEqual(decision.kind, QUESTION)
                self.assertEqual(decision.question, phrase)
        self.assertNotEqual(analyze('пример', prior_state(), []).kind, QUESTION)

    def test_exact_current_chunk_stays_ack_and_partial_phrase_stays_attempt(self):
        for phrase in ('Почему так', 'Что это', 'А пример'):
            with self.subTest(exact=phrase):
                self.assertEqual(analyze(phrase, prior_state(chunk=phrase), []).kind, ACK)
        for phrase, chunk in (('Почему так', 'Почему так происходит'),
                              ('Почему так', 'Сначала выясним почему так происходит'),
                              ('Что это', 'Что это значит'),
                              ('Что это', 'Что это такое'),
                              ('А пример', 'пример такого процесса')):
            with self.subTest(partial=phrase):
                self.assertEqual(analyze(phrase, prior_state(chunk=chunk), []).kind, REPLAY)
        for phrase in ('Объясни почему так', 'Приведи пример'):
            with self.subTest(explicit=phrase):
                self.assertEqual(analyze(phrase, prior_state(), []).kind, QUESTION)

    def test_partial_overlap_replay_precedes_matching_prepared_bank_question(self):
        state = prior_state(chunk='Что это такое')
        bank = [{'question': 'Что это', 'answer': 'Подготовленный ответ.'}]
        self.assertEqual(analyze('Что это', state, bank).kind, REPLAY)

    def test_background_filler_and_pending_generation_are_not_short_questions(self):
        waiting = prior_state()
        for phrase in ('а', 'да', 'угу', 'ну', 'А пример приводился выше и показан в таблице'):
            with self.subTest(phrase=phrase):
                self.assertNotEqual(analyze(phrase, waiting, []).kind, QUESTION)
        pending = dict(prior_state(), chunks=[], answer='', completed=True, pending_turn='in-flight')
        for phrase in PHRASES:
            for said in (phrase, phrase + '?'):
                with self.subTest(pending=said):
                    self.assertEqual(analyze(said, pending, []).kind, QUIET)
        for said in ('Ну почему так?', 'Так а что это?', 'Ну а пример?'):
            with self.subTest(pending=said):
                self.assertEqual(analyze(said, pending, []).kind, QUIET)
        self.assertEqual(analyze('Вопрос: что такое НДС?', pending, []).kind, QUESTION)


class ShortFollowupEngineTests(unittest.TestCase):
    def _run_case(self, phrase, preset, completed):
        with tempfile.TemporaryDirectory() as td:
            calls = []

            def generate(question, history, *args):
                calls.append((question, list(history)))
                return 'Ответ продолжает тему и содержит несколько слов для проверки состояния.'

            engine = EchoEngine(Path(td) / 'state.db', generate, settings={'preset': preset})
            engine_reply(engine, session_id='s', turn_id='q1', text='Что такое налоговая база?', request={}, model='fixture')
            if completed:
                turn = 0
                while not engine.state('s')['completed']:
                    current = engine.state('s')['chunks'][engine.state('s')['chunk_index']]
                    engine_reply(engine, session_id='s', turn_id=f'ack{turn}', text=current, request={}, model='fixture')
                    turn += 1
            before = engine.state('s')
            reply = engine_reply(engine, session_id='s', turn_id='followup', text=phrase, request={}, model='fixture')
            after = engine.state('s')
            self.assertEqual(len(calls), 2)
            self.assertEqual(calls[1][0], phrase)
            self.assertEqual(calls[1][1], [{'question': 'Что такое налоговая база?',
                                           'answer': 'Ответ продолжает тему и содержит несколько слов для проверки состояния.'}])
            self.assertEqual(after['revision'], before['revision'] + 1)
            self.assertEqual(after['question'], phrase)
            self.assertTrue(reply)

    def test_each_followup_generates_once_with_full_history_while_waiting_and_completed(self):
        for preset in PRESETS:
            for phrase in PHRASES:
                for completed in (False, True):
                    with self.subTest(preset=preset, phrase=phrase, completed=completed):
                        self._run_case(phrase, preset, completed)

    def test_no_state_passes_bounded_followup_verbatim_without_fabricating_history(self):
        for phrase in PHRASES:
            with self.subTest(phrase=phrase), tempfile.TemporaryDirectory() as td:
                calls = []
                engine = EchoEngine(Path(td) / 'state.db',
                                    lambda question, history, *args: calls.append((question, history)) or 'Краткий ответ.')
                self.assertEqual(engine_reply(engine, session_id='s', turn_id='standalone', text=phrase,
                                              request={}, model='fixture'), 'Краткий ответ.')
                self.assertEqual(calls, [(phrase, [])])
                self.assertEqual(engine.state('s')['revision'], 1)

    def test_prepared_short_followup_uses_bank_without_extra_generation(self):
        for phrase in PHRASES:
            with self.subTest(phrase=phrase), tempfile.TemporaryDirectory() as td:
                calls = []
                qa = [{'question': phrase, 'answer': 'Подготовленный ответ из локального банка.'}]
                engine = EchoEngine(Path(td) / 'state.db',
                                    lambda question, history, *args: calls.append(question) or
                                    'Первоначальный ответ содержит несколько понятных частей.', qa=qa)
                engine_reply(engine, session_id='s', turn_id='initial', text='Как изменился ВВП?',
                             request={}, model='fixture')
                reply = engine_reply(engine, session_id='s', turn_id='prepared', text=phrase,
                                     request={}, model='fixture')
                self.assertTrue(reply.startswith('Подготовленный ответ'))
                self.assertEqual(calls, ['Как изменился ВВП?'])
                self.assertEqual(engine.state('s')['revision'], 2)

    def test_partial_followup_overlap_does_not_use_prepared_bank(self):
        with tempfile.TemporaryDirectory() as td:
            calls = []
            bank = [{'question': 'Что это', 'answer': 'Подготовленный ответ из банка.'}]
            engine = EchoEngine(Path(td) / 'state.db',
                                lambda question, history, *args: calls.append(question) or
                                'Ответ содержит несколько слов для проверки.', qa=bank)
            engine_reply(engine, session_id='s', turn_id='initial', text='Как изменился ВВП?',
                         request={}, model='fixture')
            state = engine.state('s')
            state.update(answer='Что это такое', chunks=['Что это такое'], chunk_index=0, completed=False)
            with engine._db() as db:
                db.execute('UPDATE sessions SET state=? WHERE session_id=?',
                           (__import__('json').dumps(state, ensure_ascii=False), 's'))
            reply = engine_reply(engine, session_id='s', turn_id='partial', text='Что это', request={}, model='fixture')
            self.assertEqual(reply, 'Что это такое')
            self.assertEqual(len(calls), 1)
            after = engine.state('s')
            self.assertEqual((after['revision'], after['chunk_index']), (state['revision'], 0))

    def test_short_followup_during_pending_generation_does_not_restart_or_queue(self):
        with tempfile.TemporaryDirectory() as td:
            started, release = threading.Event(), threading.Event()
            calls = []

            def generate(question, history, *args):
                calls.append((question, list(history)))
                if question == 'Что такое налоговая база?':
                    started.set()
                    self.assertTrue(release.wait(2))
                    return 'Первичный ответ содержит достаточно слов для частей.'
                return 'Первичный ответ содержит достаточно слов для частей.'

            engine = EchoEngine(Path(td) / 'state.db', generate)
            original = threading.Thread(target=lambda: engine_reply(engine, 
                session_id='s', turn_id='initial', text='Что такое налоговая база?', request={}, model='fixture'))
            original.start()
            self.assertTrue(started.wait(1))
            pending = engine.state('s')
            self.assertTrue(pending['pending_turn'])
            for index, phrase in enumerate(PHRASES):
                self.assertEqual(engine_reply(engine, session_id='s', turn_id=f'pending-{index}', text=phrase + '?',
                                              request={}, model='fixture'), SILENT)
            still_pending = engine.state('s')
            self.assertEqual(still_pending['revision'], pending['revision'])
            self.assertEqual(still_pending['pending_turn'], pending['pending_turn'])
            self.assertEqual(len(calls), 1)
            replacement = engine_reply(engine, session_id='s', turn_id='explicit', text='Вопрос: что такое НДС?',
                                       request={}, model='fixture')
            self.assertTrue(replacement)
            self.assertEqual(engine.state('s')['revision'], pending['revision'] + 1)
            self.assertEqual(len(calls), 2)
            release.set()
            original.join(2)
            self.assertFalse(original.is_alive())

    def test_partial_portion_overlap_replays_without_replacing_turn(self):
        cases = (('Что это', 'Что это такое'),
                 ('Почему так', 'Почему так происходит'),
                 ('Почему так', 'Сначала выясним почему так происходит'),
                 ('А пример', 'пример такого процесса'))
        for preset in PRESETS:
            for phrase, chunk in cases:
                with self.subTest(preset=preset, phrase=phrase), tempfile.TemporaryDirectory() as td:
                    calls = []
                    engine = EchoEngine(Path(td) / 'state.db',
                                        lambda question, history, *args: calls.append(question) or 'Неважно.')
                    engine_reply(engine, session_id='s', turn_id='q', text='Что такое налоговая база?',
                                 request={}, model='fixture')
                    state = engine.state('s')
                    state.update(answer=chunk, chunks=[chunk], chunk_index=0, completed=False)
                    with engine._db() as db:
                        db.execute('UPDATE sessions SET state=? WHERE session_id=?',
                                   (__import__('json').dumps(state, ensure_ascii=False), 's'))
                    reply = engine_reply(engine, session_id='s', turn_id='partial', text=phrase,
                                         request={}, model='fixture')
                    after = engine.state('s')
                    self.assertEqual(reply, chunk)
                    self.assertEqual((after['revision'], after['chunk_index']), (state['revision'], 0))
                    self.assertEqual(len(calls), 1)


if __name__ == '__main__':
    unittest.main()
