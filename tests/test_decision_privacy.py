"""Ordinary decision logs must not contain conversational content or identifiers."""
import unittest

from echo_sync.classifier import classify
from echo_sync.engine import EchoEngine


class DecisionPrivacyTests(unittest.TestCase):
    def test_classifier_does_not_log_transcript(self):
        secret = 'почему PRIVATE_TRANSCRIPT_501 остается в журнале'
        with self.assertLogs('echo-sync', level='INFO') as captured:
            classify(secret, None, [])
        logged = '\n'.join(captured.output)
        self.assertNotIn('PRIVATE_TRANSCRIPT_501', logged)
        self.assertNotIn('почему', logged)
        self.assertIn('kind=', logged)
        self.assertIn('reason=', logged)

    def test_engine_does_not_log_transcript_or_session_identifiers(self):
        with self.assertLogs('echo-sync', level='INFO') as captured:
            EchoEngine._log('PRIVATE_SESSION_502', 'PRIVATE_TURN_503', 'ack', 'ack_exact',
                            {'revision': 7, 'chunk_index': 2}, 'PRIVATE_TRANSCRIPT_504')
        logged = '\n'.join(captured.output)
        for value in ('PRIVATE_SESSION_502', 'PRIVATE_TURN_503', 'PRIVATE_TRANSCRIPT_504'):
            self.assertNotIn(value, logged)
        self.assertIn('revision=7', logged)
        self.assertIn('index=2', logged)

    def test_engine_logging_does_not_need_text_conversion(self):
        class Sensitive:
            def __str__(self):
                raise AssertionError('Conversational content must not be formatted for logging')
            def __getitem__(self, key):
                raise AssertionError('Conversational content must not be sliced for logging')
        with self.assertLogs('echo-sync', level='INFO'):
            EchoEngine._log('s', 't', 'silent', 'empty', None, Sensitive())


if __name__ == '__main__':
    unittest.main()
