"""WAVE 2 / Task B, item 5: the simulated ACK timeline (tools/ack_latency_sim.py) built from the real event timings of a probe report.

The simulation drives the REAL ControlledMedia on an injected clock with the recorded timings of the listener's repeat (when it began, ended,
when the provider's final arrived) and a partial transcript that is complete ``wait`` before the final, ticked every 100 ms; once with the
stable-partial confirmation off (the final decides: the base) and once on. Its «base» must reproduce what the probe measured, or the
«after» would mean nothing. The numbers of the real probe report are checked when the report is there.
"""
import json
import statistics
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))

import ack_latency_sim as sim                                     # noqa: E402
from echo_sync.controlled_media import ACK_STABLE_SECONDS         # noqa: E402

# one recorded confirming repeat (native_controlled_socket.json, previous attempt: «Тело сохранять» -> next portion), milliseconds
RECORDED = {'input_start_ms': 47260, 'input_end_ms': 49367, 'asr_final_ms': 50540, 'first_pcm_ms': 50591}


def test_the_base_reproduces_what_was_measured():
    base = sim.simulate(RECORDED, wait_after_text_ms=810, stable_seconds=0)
    measured = RECORDED['first_pcm_ms'] - RECORDED['input_end_ms']
    assert abs(base - measured) <= 5, (base, measured)


@pytest.mark.parametrize('wait', sim.WAIT_AFTER_TEXT_MS)
def test_the_stable_partial_wins_the_time_the_final_waits_less_the_stable_window_and_a_tick(wait):
    base = sim.simulate(RECORDED, wait_after_text_ms=wait, stable_seconds=0)
    after = sim.simulate(RECORDED, wait_after_text_ms=wait, stable_seconds=ACK_STABLE_SECONDS)
    gain = base - after
    ideal = wait - ACK_STABLE_SECONDS * 1000
    assert ideal - sim.TICK_MS - 5 <= gain <= ideal + 5, (gain, ideal)
    assert after < base


def test_a_partial_that_is_never_complete_before_the_final_gives_nothing_and_loses_nothing():
    base = sim.simulate(RECORDED, wait_after_text_ms=810, stable_seconds=0)
    late = sim.simulate(RECORDED, wait_after_text_ms=20, stable_seconds=ACK_STABLE_SECONDS)
    assert late == base, 'text known only at the final: the final decides, no earlier and no later than before'


def test_the_steps_of_a_report_are_the_confirming_spoken_repeats_with_all_four_times():
    report = {'ack_steps': [dict(RECORDED, case='full', cursor_before=0, cursor_after=1),
                            dict(RECORDED, case='full', cursor_before=1, cursor_after=1),        # not confirmed
                            dict(RECORDED, case='partial', cursor_before=0, cursor_after=0),
                            {'case': 'full', 'cursor_before': 0, 'cursor_after': 1, 'input_end_ms': 5}],   # no times
                  'previous_attempts': [{'ack_steps': [dict(RECORDED, case='full', cursor_before=2, cursor_after=3)]}]}
    assert len(sim.ack_steps(report)) == 2


def test_the_real_probe_report():
    path = sim.DEFAULT_REPORT
    if not path.exists():
        pytest.skip('the probe report is not available here')
    steps = sim.ack_steps(json.loads(path.read_text(encoding='utf-8')))
    assert steps, 'the report holds confirming repeats'
    measured = statistics.median(s['first_pcm_ms'] - s['input_end_ms'] for s in steps)
    base = statistics.median(sim.simulate(s, wait_after_text_ms=810, stable_seconds=0) for s in steps)
    after = statistics.median(sim.simulate(s, wait_after_text_ms=810, stable_seconds=ACK_STABLE_SECONDS) for s in steps)
    assert abs(base - measured) <= 20, f'the model does not reproduce the measurement: {base} vs {measured}'
    assert measured - after >= 400, f'the gain on the real timings is only {measured - after:.0f} ms'
