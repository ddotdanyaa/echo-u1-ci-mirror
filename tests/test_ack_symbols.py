"""ACK candidates must preserve semantic marks lost by ordinary text normalization."""
import unittest
import tempfile
from pathlib import Path

try:
    from echo_sync.ack_semantics import ack_symbols_compatible
except ImportError:
    ack_symbols_compatible = None
from engine_say import engine_reply


class AckSymbolTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(ack_symbols_compatible, 'ACK semantic-symbol guard has not been implemented')

    def test_arithmetic_operator_changes_are_not_ack_compatible(self):
        for current, heard in (
            ('a + b', 'a - b'),
            ('5 + 3', '5 - 3'),
            ('8 / 2', '8 * 2'),
            ('x = 3', 'x < 3'),
            ('a + b c', 'a b + c'),
            ('Тут 5 - 3', 'Тут 5 3'),
        ):
            with self.subTest(current=current, heard=heard):
                self.assertFalse(ack_symbols_compatible(heard, current))

    def test_signed_values_percent_and_decimal_marks_are_preserved(self):
        for current, heard in (
            ('-5', '5'),
            ('−5', '5'),
            ('5%', '5'),
            ('5%', '5‰'),
            ('3,14', '3 14'),
            ('3.14', '3 14'),
        ):
            with self.subTest(current=current, heard=heard):
                self.assertFalse(ack_symbols_compatible(heard, current))

    def test_equivalent_symbol_forms_and_nonsemantic_punctuation_stay_compatible(self):
        for heard, current in (
            ('−5', '-5'),
            ('5,14', '5.14'),
            ('22 05 2026', '22.05.2026'),
            ('2026 10 22', '2026-10-22'),
            ('one, two!', 'one two'),
            ('one — two', 'one - two'),
            ('из-за правила', 'из за правила'),
        ):
            with self.subTest(heard=heard, current=current):
                self.assertTrue(ack_symbols_compatible(heard, current))

    def test_double_ack_requires_the_same_symbol_pattern_twice(self):
        self.assertTrue(ack_symbols_compatible('5 + 3 5 + 3', '5 + 3'))
        self.assertFalse(ack_symbols_compatible('5 + 3 5 - 3', '5 + 3'))

    def test_anchor_offsets_handle_fillers_nfkc_dash_forms_and_hyphen_segments(self):
        for heard, current in (
            ('ну, 5 + 3!', '5 + 3'),
            ('５ ＋ ３', '5 + 3'),
            ('5 – 3', '5 - 3'),
            ('5 — 3', '5 − 3'),
            ('a - b + c', 'a-b+c'),
        ):
            with self.subTest(heard=heard, current=current):
                self.assertTrue(ack_symbols_compatible(heard, current, fillers={'ну'}))

    def test_engine_cursor_does_not_advance_when_semantic_marks_are_lost_or_changed(self):
        try:
            from echo_sync.engine import EchoEngine
        except ImportError:
            self.fail('EchoEngine is unavailable')
        for current, heard in (
            ('a + b', 'a - b'),
            ('5 + 3', '5 - 3'),
            ('-5', '5'),
            ('5%', '5'),
            ('5,14', '5 14'),
            ('Тут 5 - 3', 'Тут 5 3'),
            ('5%', '5‰'),
            ('a + b c', 'a b + c'),
        ):
            with self.subTest(current=current, heard=heard), tempfile.TemporaryDirectory() as tmp:
                engine = EchoEngine(Path(tmp) / 'state.db', lambda *args: self.fail('no generation expected'))
                db = __import__('sqlite3').connect(str(engine.path))
                try:
                    state = {'schema': 2, 'revision': 1, 'question': 'q', 'answer': current + ' more',
                             'chunks': [current, 'more'], 'chunk_index': 0, 'completed': False,
                             'pending_turn': None, 'history': [], 'issued_at': 0, 'issued_syl': 0}
                    db.execute('INSERT INTO sessions VALUES (?,?)', ('s', __import__('json').dumps(state)))
                    db.commit()
                finally:
                    db.close()
                engine_reply(engine, session_id='s', turn_id='heard', text=heard, request={}, model='offline')
                self.assertEqual(engine.state('s')['chunk_index'], 0)

    def test_engine_accepts_same_double_ack_and_leading_filler(self):
        try:
            from echo_sync.engine import EchoEngine
        except ImportError:
            self.fail('EchoEngine is unavailable')
        for heard in ('5 + 3 5 + 3', 'ну, 5 + 3!'):
            with self.subTest(heard=heard), tempfile.TemporaryDirectory() as tmp:
                engine = EchoEngine(Path(tmp) / 'state.db', lambda *args: self.fail('no generation expected'),
                                    settings={'fillers': ['ну']})
                db = __import__('sqlite3').connect(str(engine.path))
                try:
                    state = {'schema': 2, 'revision': 1, 'question': 'q', 'answer': '5 + 3 more',
                             'chunks': ['5 + 3', 'more'], 'chunk_index': 0, 'completed': False,
                             'pending_turn': None, 'history': [], 'issued_at': 0, 'issued_syl': 0}
                    db.execute('INSERT INTO sessions VALUES (?,?)', ('s', __import__('json').dumps(state)))
                    db.commit()
                finally:
                    db.close()
                engine_reply(engine, session_id='s', turn_id='heard', text=heard, request={}, model='offline')
                self.assertEqual(engine.state('s')['chunk_index'], 1)


if __name__ == '__main__':
    unittest.main()
