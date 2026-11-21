"""Network retries must never replay an older position or bypass the timed echo guard."""
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from echo_sync.engine import EchoEngine, SILENT
from engine_say import engine_reply


class RetryCursorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'state.db'
        self.now = 100.0
        self.calls = 0

        def generate(*args):
            self.calls += 1
            return 'Первый второй третий, четвёртый пятый шестой. Седьмой восьмой.'

        self.generate = generate
        self.engine = EchoEngine(self.path, generate, clock=lambda: self.now)

    def turn(self, text, turn):
        return engine_reply(self.engine, session_id='s', turn_id=turn, text=text, request={}, model='fixture')

    def test_late_question_retry_after_ack_is_silent(self):
        first = self.turn('Что это?', 'question')
        second = self.turn(first, 'ack1')
        self.assertNotEqual(first, second)
        self.assertEqual(self.turn('Что это?', 'question'), SILENT)
        self.assertEqual(self.engine.state('s')['chunk_index'], 1)
        self.assertEqual(self.calls, 1)

    def test_late_ack_retry_after_next_ack_cannot_replay_previous_chunk(self):
        first = self.turn('Что это?', 'question')
        second = self.turn(first, 'ack1')
        third = self.turn(second, 'ack2')
        self.assertNotEqual(second, third)
        self.assertEqual(self.turn(first, 'ack1'), SILENT)
        self.assertEqual(self.engine.state('s')['chunk_index'], 2)

    def test_restart_retains_cache_position(self):
        first = self.turn('Что это?', 'question')
        second = self.turn(first, 'ack1')
        self.engine = EchoEngine(self.path, self.generate, clock=lambda: self.now)
        self.assertEqual(self.turn('Что это?', 'question'), SILENT)
        self.assertEqual(self.turn(first, 'ack1'), second)

    def test_legacy_cache_without_position_is_silent_after_migration(self):
        first = self.turn('Что это?', 'question')
        state = self.engine.state('s')
        legacy = Path(self.tmp.name) / 'legacy.db'
        with closing(sqlite3.connect(legacy)) as db:
            db.execute('CREATE TABLE sessions (session_id TEXT PRIMARY KEY, state TEXT NOT NULL)')
            db.execute('CREATE TABLE turns (session_id TEXT, turn_id TEXT, reply TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(session_id,turn_id))')
            db.execute('INSERT INTO sessions VALUES (?,?)', ('s', json.dumps(state)))
            db.execute('INSERT INTO turns VALUES (?,?,?,?)', ('s', 'question', first, 1))
            db.commit()
        migrated = EchoEngine(legacy, self.generate)
        result = engine_reply(migrated, session_id='s', turn_id='question', text='Что это?', request={}, model='fixture')
        self.assertEqual(result, SILENT)
        self.assertEqual(migrated.state('s')['chunk_index'], 0)

    def test_completed_answer_cannot_be_replayed_by_old_turn(self):
        first = self.turn('Что это?', 'question')
        self.turn(first, 'ack1')
        while not self.engine.state('s')['completed']:
            state = self.engine.state('s')
            self.turn(state['chunks'][state['chunk_index']], f'ack-{state["chunk_index"]}')
        self.assertEqual(self.turn('Что это?', 'question'), SILENT)
        self.assertTrue(self.engine.state('s')['completed'])


if __name__ == '__main__':
    unittest.main()
