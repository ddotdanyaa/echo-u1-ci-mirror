"""Ordinary decision logs must not contain conversational content or identifiers."""
import logging
import tempfile
import unittest
from pathlib import Path

from echo_sync.engine import EchoEngine
from helpers_w1f import Wire


class DecisionPrivacyTests(unittest.TestCase):
    def test_the_judge_does_not_log_transcript(self):
        # M1: a final is read by the judge of the real controller and the verdict has ONE line (kind, reason, rule): no words of the listener in it
        secret = 'почему PRIVATE_TRANSCRIPT_501 остается в журнале'
        records = []

        class Keep(logging.Handler):
            def emit(self, record):
                records.append(record.getMessage())
        handler, log = Keep(level=logging.INFO), logging.getLogger('echo-sync')
        old = log.level
        log.addHandler(handler)
        log.setLevel(logging.INFO)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                wire = Wire(Path(tmp))
                wire.user('u1', secret, 0.0, 2.0)
                wire.until(6.0)
        finally:
            log.removeHandler(handler)
            log.setLevel(old)
        lines = [line for line in records if line.startswith('echo-sync judge tid=u1')]
        self.assertTrue(lines, records)
        logged = ' | '.join(lines)
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
