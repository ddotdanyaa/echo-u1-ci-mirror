"""w9-game N126/N192: the after-call step report next to the journal, built on cloud_context/scripts/latency_chain.py. Numbers and labels only."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import call_report  # noqa: E402

SECRET = 'СЕКРЕТНАЯ-РЕПЛИКА'
ROWS = [
    {'t': 0, 'ev': 'call_open', 'wall': 'x', 'source': 'phone'},
    {'t': 3000, 'ev': 'ready'},
    {'t': 10000, 'ev': 'user_start'},
    {'t': 12000, 'ev': 'provider', 'type': 'input_transcript.added'},
    {'t': 12100, 'ev': 'ear_final', 'text': SECRET, 'kind': 'question', 'reason': 'question_word', 'lag_ms': 120, 'decode_ms': 50, 'speech_ms': 2000},
    {'t': 12500, 'ev': 'decision', 'kind': 'question', 'reason': 'ear_first'},
    {'t': 13950, 'ev': 'decision', 'kind': 'question', 'reason': 'admitted_answer'},
    {'t': 14000, 'ev': 'cue_end', 'status': 'completed', 'first_ms': 14000, 'last_ms': 17000, 'frames': 150, 'text': SECRET},
    {'t': 14100, 'ev': 'user_final', 'text': SECRET},
    {'t': 20000, 'ev': 'call_close', 'elapsed_ms': 20000},
]


def write(directory, rows, name='20261105-120000-abc.jsonl'):
    path = Path(directory) / name
    path.write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in rows) + '\n', encoding='utf-8')
    return path


class CallReportTests(unittest.TestCase):
    def test_report_lands_next_to_journal_with_steps_summing_to_the_interval(self):
        with tempfile.TemporaryDirectory() as td:
            journal = write(td, ROWS)
            out = call_report.write_report(journal)
            self.assertEqual(out.parent, journal.parent)
            self.assertEqual(out.name, journal.stem + '.report.json')
            rep = json.loads(out.read_text(encoding='utf-8'))
            self.assertEqual(len(rep['episodes']), 1)
            ep = rep['episodes'][0]
            self.assertEqual(ep['pcm_ms'], 14000 - 11980)
            self.assertEqual(sum(ms for _, ms in ep['steps']), ep['pcm_ms'])
            self.assertEqual(ep['class'], 'модель')
            self.assertEqual(rep['summary']['episodes'], 1)
            self.assertEqual(rep['summary']['biggest_step'][0], ep['steps'][max(range(len(ep['steps'])), key=lambda i: ep['steps'][i][1])][0])

    def test_no_reply_text_anywhere_in_the_report(self):
        with tempfile.TemporaryDirectory() as td:
            out = call_report.write_report(write(td, ROWS))
            self.assertNotIn(SECRET, out.read_text(encoding='utf-8'))

    def test_empty_or_broken_journal_gives_an_empty_report_not_a_crash(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'x.jsonl'
            path.write_text('not json\n{"t": 1}\n', encoding='utf-8')
            rep = json.loads(call_report.write_report(path).read_text(encoding='utf-8'))
            self.assertEqual(rep['episodes'], [])
            self.assertEqual(rep['summary']['episodes'], 0)

    def test_latest_picks_the_newest_journal_and_skips_reports(self):
        with tempfile.TemporaryDirectory() as td:
            write(td, ROWS, '20261105-100000-a.jsonl')
            newest = write(td, ROWS, '20261105-110000-b.jsonl')
            (Path(td) / '20261105-120000-b.report.json').write_text('{}')
            self.assertEqual(call_report.latest(td), newest)
            self.assertIsNone(call_report.latest(Path(td) / 'nope'))


if __name__ == '__main__':
    unittest.main()
