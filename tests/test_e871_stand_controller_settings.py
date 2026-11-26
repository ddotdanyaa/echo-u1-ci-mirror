# factory-backlog-id: E871.s1
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.replay.stand import Stand


def test_stand_controller_gets_the_call_settings_ear_job_on():
    stand = Stand(1, profile={'ear_job': 'on'}, length=5.0)
    try:
        assert bool(stand.w.controller.ear_job) is True
    finally:
        stand.close()
