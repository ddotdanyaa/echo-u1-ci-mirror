# factory-backlog-id: E871.s1
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.replay.stand import Stand


def test_stand_controller_gets_the_call_settings_ear_job_on():
    profile = {'fast_text': 'on', 'local_ear': 'act', 'prepare_wide': 'on', 'ear_job': 'on'}
    stand = Stand(1, profile=profile, length=5.0)
    try:
        assert stand.settings['ear_job'] == 'on'
        assert stand.w.controller.modes['ear_job'] == 'on'
        assert stand.w.controller.settings['ear_job'] == 'on'
    finally:
        stand.close()
