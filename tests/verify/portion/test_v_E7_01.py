"""V3 E7-01 (ENV-WORLD): ``tests/break/world`` is collectable: its conftest puts ``tests/break/portion_speech`` (``bps_common``) on ``sys.path``.
Row of the backlog: ``pytest tests/break/world --collect-only`` gives 0 collection errors (before: 3 files with ``ModuleNotFoundError: bps_common``). Not run on the laptop."""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def test_the_break_world_tests_are_collected_with_no_import_error():
    done = subprocess.run([sys.executable, '-m', 'pytest', 'tests/break/world', '--collect-only', '-q', '-p', 'no:cacheprovider'], cwd=ROOT, capture_output=True, text=True, timeout=240)
    out = done.stdout + done.stderr
    assert 'ModuleNotFoundError' not in out, out[-1500:]
    assert done.returncode == 0, out[-1500:]
