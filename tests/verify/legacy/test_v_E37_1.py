"""V5 / E37.1: a «стоп» the ear heard is dropped (act=no reason=changed_since_onset) because an answer was admitted while it was said, and that answer is said (F5 of a1-fuzz: 25 seeds of 2000 at ≈1.25 %).
The stand plays seeded whole conversations through the real ControlledMedia, ShadowEar, wire and FastText (tools/replay/stand.py); invariant A2 after «стоп» is its check. The sweep is the guard: 0 cues after a
stop that the system had. A red seed is a defect card for the family K/M1 (the judge keeps the stop), not an excuse. Seconds are the stand's clock."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pytest  # noqa: E402

from tools.replay import stand  # noqa: E402


def after_a_stop(out):
    return [v for v in out.violations if v[0] == 'A2' and 'after «стоп»' in v[2]]


@pytest.mark.parametrize('seed', range(0, 60, 3))
def test_e37_1_no_cue_after_a_stop_the_system_had(seed):
    out = stand.run(seed, length=60)
    assert out.crash is None, stand.describe(out)
    assert after_a_stop(out) == [], stand.describe(out)


def test_e37_1_the_seed_of_the_finding_f5_stays_gone():
    out = stand.run(88, length=22.0)
    assert [v for v in out.violations if v[0] == 'A2' and abs(v[1] - 21.48) < 0.05] == [], stand.describe(out)
