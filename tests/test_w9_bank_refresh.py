"""w9-game N196: one command refreshes the question bank (qa.json) and the spoken-audio cache of its answers."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import bank_refresh  # noqa: E402

QA = [{'question': 'Что такое НДС?', 'answer': 'Налог на добавленную стоимость.'},
      {'question': 'Сколько дней в году?', 'answer': 'Триста шестьдесят пять.'}]


def setup(td, qa=QA):
    home = Path(td)
    (home / 'qa.json').write_text(json.dumps(qa, ensure_ascii=False), encoding='utf-8')
    return home / 'qa.json', home / 'bank_audio'


class BankRefreshTests(unittest.TestCase):
    def test_first_run_plans_everything_and_apply_writes_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            qa, audio = setup(td)
            plan = bank_refresh.refresh(qa, audio)
            self.assertEqual((len(plan['new']), plan['changed'], plan['stale'], plan['same']), (2, [], [], []))
            self.assertFalse((audio / 'manifest.json').exists())          # a plan never writes
            bank_refresh.refresh(qa, audio, apply=True)
            self.assertEqual(len(json.loads((audio / 'manifest.json').read_text(encoding='utf-8'))['items']), 2)

    def test_second_run_after_synthesis_is_clean_and_edit_is_found(self):
        with tempfile.TemporaryDirectory() as td:
            qa, audio = setup(td)
            bank_refresh.refresh(qa, audio, apply=True)
            for entry in bank_refresh.refresh(qa, audio)['new']:
                (audio / entry['file']).write_bytes(b'RIFF')               # the laptop synthesised it
            plan = bank_refresh.refresh(qa, audio)
            self.assertEqual((plan['new'], plan['changed'], len(plan['same'])), ([], [], 2))
            qa.write_text(json.dumps([QA[0], {**QA[1], 'answer': 'Триста шестьдесят шесть.'}], ensure_ascii=False), encoding='utf-8')
            plan = bank_refresh.refresh(qa, audio)
            self.assertEqual((len(plan['changed']), len(plan['same'])), (1, 1))

    def test_removed_question_makes_its_audio_stale_and_apply_deletes_only_that_file(self):
        with tempfile.TemporaryDirectory() as td:
            qa, audio = setup(td)
            bank_refresh.refresh(qa, audio, apply=True)
            files = [e['file'] for e in bank_refresh.refresh(qa, audio)['new']]
            for f in files:
                (audio / f).write_bytes(b'RIFF')
            (audio / 'mine.txt').write_text('keep')
            qa.write_text(json.dumps(QA[:1], ensure_ascii=False), encoding='utf-8')
            plan = bank_refresh.refresh(qa, audio, apply=True)
            self.assertEqual(len(plan['stale']), 1)
            self.assertEqual(sorted(p.name for p in audio.iterdir() if p.suffix == '.wav'), [f for f in files if f not in plan['stale']])
            self.assertTrue((audio / 'mine.txt').exists())

    def test_voice_change_invalidates_all_audio(self):
        with tempfile.TemporaryDirectory() as td:
            qa, audio = setup(td)
            bank_refresh.refresh(qa, audio, apply=True, voice='Irina')
            for e in bank_refresh.refresh(qa, audio, voice='Irina')['new']:
                (audio / e['file']).write_bytes(b'RIFF')
            plan = bank_refresh.refresh(qa, audio, voice='Pavel')
            self.assertEqual((len(plan['changed']), plan['new'], plan['stale']), (2, [], []))      # the old audio stays until the new exists

    def test_broken_bank_is_refused_and_nothing_is_touched(self):
        with tempfile.TemporaryDirectory() as td:
            qa, audio = setup(td, [{'question': 'x'}])
            with self.assertRaises(ValueError):
                bank_refresh.refresh(qa, audio, apply=True)
            self.assertFalse(audio.exists())
            qa.write_text('{', encoding='utf-8')
            with self.assertRaises(ValueError):
                bank_refresh.refresh(qa, audio, apply=True)

    def test_duplicate_questions_are_reported(self):
        with tempfile.TemporaryDirectory() as td:
            qa, audio = setup(td, QA + [QA[0]])
            self.assertEqual(bank_refresh.refresh(qa, audio)['duplicates'], 1)


if __name__ == '__main__':
    unittest.main()
