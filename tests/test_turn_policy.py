"""Engine-level behaviour of the turn policy: fillers, noise, stem ACK, mismatch replay, echo guard, inline repeat."""
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

try:
    from echo_sync.engine import EchoEngine
    from echo_sync.portioner import portions
except ImportError:
    EchoEngine = portions = None
from engine_say import engine_reply

ANSWER = 'Первый второй третий, четвёртый пятый шестой. Седьмой восьмой.'
FINANCE = {'question': 'Что такое финансовая система Российской Федерации?',
           'answer': 'Финансовая система Российской Федерации представляет собой совокупность взаимосвязанных сфер финансовых отношений.'}
GDP = {'question': 'Что такое ВВП?', 'answer': 'ВВП показывает стоимость всех товаров. Рост ВВП важен.'}
FIRST = 'Финансовая система Российской'
SECOND = 'Федерации представляет собой'


class Clock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now


class TurnCase(unittest.TestCase):
    settings = None
    bank = (FINANCE, GDP)

    def setUp(self):
        self.assertIsNotNone(EchoEngine, 'EchoEngine feature has not been implemented')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.calls = []
        self.clock = Clock()
        self.count = 0

        def generate(question, history, context, request, model):
            self.calls.append(question)
            return ANSWER

        self.generate = generate
        self.engine = EchoEngine(Path(self.tmp.name) / 'state.db', generate, qa=list(self.bank), settings=self.settings, clock=self.clock)

    def turn(self, text, turn=None, sid='s1'):
        self.count += 1
        return engine_reply(self.engine, session_id=sid, turn_id=turn or f't{self.count}', text=text, request={}, model='gpt-test')

    def state(self, sid='s1'):
        return self.engine.state(sid)

    def start(self):
        reply = self.turn('Что такое финансовая система Российской Федерации')
        self.assertEqual(reply, FIRST)
        return reply


class FieldLogTests(TurnCase):
    """Real iPhone, 2026-10-21: Apple adds no '?' and the user starts with a filler."""

    def test_the_four_phrases_of_the_log_each_in_a_fresh_chat(self):
        self.assertEqual(self.turn('Так что такое финансовая система Российской Федерации', sid='a'), FIRST)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.turn('Так что такое финансовая система', sid='b'), 'Первый второй третий,')
        self.assertEqual(self.calls, ['что такое финансовая система'])
        self.assertEqual(self.turn('Ответь на мой вопрос', sid='c'), 'NO_REPLY')
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.turn('Что такое финансовая система Российской Федерации', sid='d'), FIRST)

    def test_the_same_phrases_one_after_another_in_one_chat(self):
        self.assertEqual(self.turn('Так что такое финансовая система Российской Федерации'), FIRST)
        self.assertEqual(self.turn('Так что такое финансовая система'), 'Первый второй третий,')
        self.assertEqual(self.turn('Ответь на мой вопрос'), 'NO_REPLY')
        self.assertEqual(self.state()['chunk_index'], 0)
        self.assertEqual(self.turn('Что такое финансовая система Российской Федерации'), FIRST)
        self.assertEqual(self.state()['revision'], 3)
        self.assertEqual(len(self.calls), 1)


class AckTests(TurnCase):
    def test_stem_match_is_the_default(self):
        self.start()
        self.assertEqual(self.turn('финансовая система российская'), SECOND)
        self.assertEqual(self.state()['chunk_index'], 1)

    def test_leading_fillers_are_ignored(self):
        self.start()
        self.assertEqual(self.turn('ну вот финансовая система российской'), SECOND)


    def test_words_must_all_be_present_and_in_order(self):
        self.engine.settings = {}
        self.start()
        for i, text in enumerate(('система финансовая российской', 'финансовая система', 'финансовая система российской федерации')):
            self.assertEqual(self.turn(text), 'NO_REPLY', text)
        self.assertEqual(self.state()['chunk_index'], 0)

    def test_acknowledging_the_last_portion_finishes_the_answer(self):
        self.turn('Что это?')
        for text in ('первый второй третий', 'четвёртый пятый шестой', 'седьмой восьмой'):
            reply = self.turn(text)
        self.assertEqual(reply, 'NO_REPLY')
        self.assertTrue(self.state()['completed'])


class MismatchTests(TurnCase):
    def test_related_wrong_repeat_replays_the_same_portion_without_advancing(self):
        self.start()
        revision = self.state()['revision']
        self.assertEqual(self.turn('финансовая система'), FIRST)
        self.assertEqual(self.turn('российская'), FIRST)
        self.assertEqual((self.state()['chunk_index'], self.state()['revision']), (0, revision))

    def test_unrelated_longer_speech_is_silent_and_keeps_the_position(self):
        self.start()
        self.assertEqual(self.turn('мы вчера обсуждали совсем другую тему в офисе'), 'NO_REPLY')
        self.assertEqual(self.state()['chunk_index'], 0)
        self.assertEqual(self.turn('финансовая система российской'), SECOND)

    def test_short_clarifications_replay_the_same_portion(self):
        self.start()
        for text in ('а', 'что', 'не понял', 'не слышу', 'не расслышал'):
            self.assertEqual(self.turn(text), FIRST, text)
        self.assertEqual(self.state()['chunk_index'], 0)

    def test_replay_follows_the_current_portion_after_an_advance(self):
        self.start()
        self.turn('финансовая система российской')
        self.assertEqual(self.turn('представляет'), SECOND)
        self.assertEqual(self.turn('не понял'), SECOND)

    def test_silent_policy_answers_every_mismatch_with_silence(self):
        self.engine.settings = {}
        self.start()
        for text in ('финансовая система', 'а', 'система'):
            self.assertEqual(self.turn(text), 'NO_REPLY', text)
        # WAVE 2 / Task A (DEF-ACK-15): «не понял» is a request to hear the portion again, not a mismatch.
        self.assertEqual(self.turn('не понял'), FIRST)
        self.assertEqual(self.turn('повтори'), FIRST)
        self.assertEqual(self.turn('еще раз'), FIRST)

    def test_a_retried_turn_gets_the_same_answer_and_never_advances_twice(self):
        self.start()
        first = self.turn('финансовая система', 'same')
        self.assertEqual(self.turn('финансовая система', 'same'), first)
        a = self.turn('финансовая система российской', 'ack')
        self.assertEqual(self.turn('финансовая система российской', 'ack'), a)
        self.assertEqual(self.state()['chunk_index'], 1)

    def test_nothing_is_replayed_when_no_answer_is_waiting(self):
        self.assertEqual(self.turn('а'), 'NO_REPLY')
        # A fragment of a portion that names no topic of its own. (Wave F / F2 ruling: «финансовая система» said with nothing before it is
        # a named topic, a question - tests/test_f2_questions.py.)
        self.assertEqual(self.turn('финансовой системы'), 'NO_REPLY')
        self.turn('Что это?')
        self.turn('стоп')
        # CL2, ruling 1: «стоп» pauses the answer. A try at the paused portion does not end the pause; a request to hear it does.
        self.assertEqual(self.turn('первый второй'), 'NO_REPLY')
        self.assertEqual(self.turn('не понял'), 'Первый второй третий,')


class NoiseTests(TurnCase):
    def test_noise_and_stray_words_never_cancel_the_answer(self):
        self.start()
        revision = self.state()['revision']
        # "что это" with prior Q/A is now a bounded contextual follow-up; see test_short_followups.
        for noise in ('да', 'угу', 'как так', 'почему', 'где', 'ага хорошо', 'объясни', 'ну',
                      'мы вчера обсуждали совсем другую тему в офисе и она всем понравилась'):
            self.turn(noise)
            state = self.state()
            self.assertEqual((state['revision'], state['chunk_index'], state['completed']), (revision, 0, False), noise)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.turn('финансовая система российской'), SECOND)

    def test_a_real_question_competes_with_the_waiting_answer_and_wins(self):
        self.start()
        self.assertEqual(self.turn('что такое налоги и сборы'), 'Первый второй третий,')
        self.assertEqual(self.state()['revision'], 2)
        self.assertEqual(self.calls, ['что такое налоги и сборы'])

    def test_a_bank_question_wins_even_when_it_is_buried_in_other_words(self):
        self.turn('Что это?')
        self.assertEqual(self.turn('значит смотри что такое финансовая система российской федерации если коротко'), FIRST)
        self.assertEqual(len(self.calls), 1)

    def test_question_mark_and_explicit_prefix_cancel_even_when_short(self):
        self.start()
        self.assertEqual(self.turn('Почему сломалось?'), 'Первый второй третий,')
        self.assertEqual(self.state()['revision'], 2)
        self.assertEqual(self.turn('вопрос бюджет'), 'Первый второй третий,')
        self.assertEqual(self.state()['revision'], 3)

    def test_a_sloppy_repeat_of_a_portion_that_contains_a_question_word_is_not_a_new_question(self):
        self.engine.generate = lambda *args: 'Что позволяет планировать расходы заранее и точно'
        self.assertEqual(self.turn('Что это?'), 'Что позволяет планировать')
        self.assertEqual(self.turn('что позволяет планировать расходы'), 'Что позволяет планировать')
        self.assertEqual(self.state()['revision'], 1)

    def test_commands_work_through_fillers(self):
        self.start()
        self.assertEqual(self.turn('ну повтори'), FIRST)
        self.assertEqual(self.turn('так стоп'), 'NO_REPLY')
        self.assertTrue(self.state()['paused'])          # CL2, ruling 1: «стоп» pauses, the portion waits
        self.assertEqual(self.turn('ну повтори'), FIRST)


class PortionSettingsTests(TurnCase):
    def test_syllable_mode_walks_through_the_whole_answer(self):
        self.engine.settings = {'portion_mode': 'syllables'}
        expected = portions(ANSWER, {'portion_mode': 'syllables'})
        reply = self.turn('Что это?')
        for portion in expected:
            self.assertEqual(reply, portion)
            reply = self.turn(portion)
        self.assertEqual(reply, 'NO_REPLY')
        self.assertTrue(self.state()['completed'])

    def test_settings_change_applies_to_the_next_answer_not_the_current_one(self):
        self.engine.settings = {'words_per_portion': 3}
        self.assertEqual(self.turn('Что это?'), 'Первый второй третий,')
        self.engine.settings = {'words_per_portion': 2}
        self.assertEqual(self.turn('первый второй третий'), 'четвёртый пятый шестой.')
        self.assertEqual(self.turn('Как это работает?'), 'Первый второй')

    def test_settings_and_bank_can_be_passed_per_call(self):
        self.engine.settings = {'words_per_portion': 3}
        reply = engine_reply(self.engine, session_id='s1', turn_id='x', text='Что это?', request={}, model='m', settings={'words_per_portion': 2})
        self.assertEqual(reply, 'Первый второй')
        bank = [{'question': 'Как дела у бюджета?', 'answer': 'Доходы покрывают расходы.'}]
        reply = engine_reply(self.engine, session_id='s2', turn_id='y', text='ну как дела у бюджета', request={}, model='m', qa=bank)
        self.assertEqual(reply, 'Доходы покрывают расходы.')
        self.assertEqual(self.calls, ['Что это?'])

    def test_abbreviation_is_spoken_in_full_once_and_acknowledged_in_full(self):
        self.engine.settings = {'abbreviations': {'ВВП': 'валовой внутренний продукт'}}
        self.assertEqual(self.turn('Что такое ВВП'), 'валовой внутренний продукт')
        self.assertEqual(self.turn('валовой внутренний продукт'), 'показывает стоимость')
        # The determiner belongs with its noun, never at the prior cue's end.
        self.assertEqual(self.turn('показывает стоимость'), 'всех товаров. Рост')
        self.assertEqual(self.turn('всех товаров'), 'всех товаров. Рост')
        self.assertEqual(self.state()['chunk_index'], 2)
        self.assertIn('ВВП показывает', self.state()['answer'])

    def test_the_text_of_a_stream_is_spoken_text_the_engine_does_not_expand_again(self):
        # speech (abbrev-expand): the controller spells the table out once per call (``_spell``); a later answer keeps the short form and the engine leaves it so
        from echo_sync.generator import StreamingAnswer
        self.engine.settings = {'abbreviations': {'ВВП': 'валовой внутренний продукт'}}
        self.engine.generate = lambda *args: StreamingAnswer('ВВП показывает стоимость.', final=True)
        self.assertTrue(self.turn('Что это?').startswith('ВВП показывает'))

    def test_a_portion_the_phone_would_intercept_is_never_spoken(self):
        # "закончить разговор" / "это всё" / "пока" ... are handled by the phone itself: repeating one would end the session.
        self.engine.generate = lambda *args: 'Закончить разговор. Спасибо вам.'
        self.engine.settings = {'words_per_portion': 2}
        self.assertEqual(self.turn('Что это?'), 'Закончить разговор. Спасибо вам.')
        self.assertEqual(self.state()['chunks'], ['Закончить разговор. Спасибо вам.'])
        self.assertEqual(self.turn('закончить разговор спасибо вам'), 'NO_REPLY')
        self.assertTrue(self.state()['completed'])

    def test_an_answer_that_is_only_a_phone_command_is_dropped_like_a_failed_generation(self):
        self.engine.generate = lambda *args: 'До свидания.'
        self.assertEqual(self.turn('Что это?'), 'NO_REPLY')
        self.assertEqual(self.state()['revision'], 1)
        self.assertEqual(self.state()['chunks'], [])


class LegacyStateTests(TurnCase):
    def make_old_db(self, with_revision=True):
        path = Path(self.tmp.name) / 'old.db'
        with closing(sqlite3.connect(str(path))) as db:
            db.execute('CREATE TABLE sessions (session_id TEXT PRIMARY KEY, state TEXT NOT NULL)')
            revision = ', revision INTEGER NOT NULL DEFAULT 0' if with_revision else ''
            db.execute(f'CREATE TABLE turns (session_id TEXT, turn_id TEXT, reply TEXT NOT NULL{revision}, PRIMARY KEY(session_id,turn_id))')
            state = {'schema': 2, 'revision': 4, 'question': 'Что это?', 'answer': ANSWER,
                     'chunks': ['Первый второй третий,', 'четвёртый пятый шестой.', 'Седьмой восьмой.'],
                     'chunk_index': 1, 'completed': False, 'pending_turn': None,
                     'history': [{'question': 'Что это?', 'answer': ANSWER}]}
            db.execute('INSERT INTO sessions VALUES (?,?)', ('old', json.dumps(state, ensure_ascii=False)))
            db.commit()
        return path

    def test_a_schema_2_state_from_the_previous_version_keeps_working(self):
        engine = EchoEngine(self.make_old_db(), self.generate)
        ask = lambda turn, text: engine_reply(engine, session_id='old', turn_id=turn, text=text, request={}, model='m')
        self.assertEqual(ask('1', 'повтори'), 'четвёртый пятый шестой.')
        self.assertEqual(ask('2', 'четвертый пятый шестой'), 'Седьмой восьмой.')
        self.assertEqual(ask('3', 'а'), 'Седьмой восьмой.')
        self.assertEqual(ask('4', 'Как это применить?'), 'Первый второй третий,')
        state = engine.state('old')
        self.assertEqual(state['revision'], 5)
        self.assertEqual(len(state['history']), 2)
        self.assertEqual(state['schema'], 2)

    def test_the_turns_table_of_an_older_schema_is_upgraded(self):
        engine = EchoEngine(self.make_old_db(with_revision=False), self.generate)
        self.assertEqual(engine_reply(engine, session_id='old', turn_id='1', text='повтори', request={}, model='m'), 'четвёртый пятый шестой.')


class LoggingTests(TurnCase):
    def test_every_decision_is_logged_with_its_reason(self):
        with self.assertLogs('echo-sync', level='INFO') as logs:
            self.turn('Так что такое финансовая система Российской Федерации')
            self.turn('финансовая система российская')
            self.turn('мы вчера обсуждали совсем другую тему')
            self.turn('представляет')
        text = '\n'.join(logs.output)
        self.assertRegex(text, r'kind=question reason=question_bank')
        self.assertRegex(text, r'kind=ack reason=ack\w*')
        self.assertRegex(text, r'kind=silent reason=\w+')
        self.assertRegex(text, r'kind=replay reason=attempt')
        self.assertEqual(len([line for line in logs.output if 'kind=' in line]), 4)


if __name__ == '__main__':
    unittest.main()
