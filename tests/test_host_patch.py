import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
try:
    import host_patch
except ImportError:
    host_patch = None


class HostPatchTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(host_patch, 'Version-guarded host silence patch has not been implemented')

    def test_apply_idempotent_and_rollback_preserves_original_bytes(self):
        import os
        source = os.environ.get('HERMES_SOURCE')
        if not source:
            self.skipTest('HERMES_SOURCE required for exact upstream fixture')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'hermes'
            home = Path(tmp) / 'profile'
            for rel in host_patch.REQUIRED_HASHES:
                dest = root / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes((Path(source) / rel).read_bytes())
            # EchoSource may already be patched; seed this fresh-install fixture
            # with its supplied verified original bytes so apply_patch can create
            # a new backup and run its unchanged strict digest checks.
            source_backup = Path(source) / (host_patch.TARGET + '.echo-sync.bak')
            if source_backup.is_file():
                (root / host_patch.TARGET).write_bytes(source_backup.read_bytes())
            original = (root / host_patch.TARGET).read_bytes()
            applied = host_patch.apply_patch(root, home)
            self.assertEqual(applied['status'], 'applied')
            self.assertEqual(host_patch.apply_patch(root, home)['status'], 'already_applied')
            self.assertTrue((home / 'echo-sync' / 'allow_silence').is_file())
            self.assertIn(b'_echo_sync_silence_enabled', (root / host_patch.TARGET).read_bytes())
            self.assertEqual(host_patch.rollback_patch(root, home)['status'], 'restored')
            self.assertEqual((root / host_patch.TARGET).read_bytes(), original)
            self.assertFalse((home / 'echo-sync' / 'allow_silence').exists())

    def test_unknown_source_refused_before_marker_or_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, home = Path(tmp) / 'hermes', Path(tmp) / 'profile'
            (root / 'gateway').mkdir(parents=True)
            (root / host_patch.TARGET).write_text('unknown version')
            with self.assertRaises(RuntimeError):
                host_patch.apply_patch(root, home)
            self.assertFalse((home / 'echo-sync' / 'allow_silence').exists())
            self.assertFalse((root / (host_patch.TARGET + '.echo-sync.bak')).exists())


if __name__ == '__main__':
    unittest.main()
