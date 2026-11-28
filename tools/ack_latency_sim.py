"""Simulated ACK timeline: what the stable-partial confirmation (WAVE 2 / Task B, item 5) gains over waiting for the final.

The inputs are REAL event timings, read from a probe report such as ``03_TESTS/gpt_live_webrtc/native_controlled_socket.json``
(``ack_steps``: for every spoken repeat the instant its audio began and ended, the instant the provider delivered its final
transcript, and the instant the next portion's first PCM frame was sent). The recorded steps carry no partial transcripts, so the
moment the transcript is already complete is modelled from the one measurement that exists (LATENCY_BASELINE.md, section 3): the
final's text is known 731-899 ms (median 810) BEFORE the final arrives. Everything after that is the real controller:
``ControlledMedia`` is driven with those events on an injected clock and ticked every 100 ms, as ``controlled_host.serve`` does,
once with the stable-partial confirmation off (the final decides: the base 5dcbf8d) and once on. The time from the controller's
decision to the first PCM frame is the measured reaction of the controller (final -> next PCM, median 52 ms) added to both.

Not measured: a real phone, the network, Bluetooth, the ear. The model of the partial is an assumption and is printed as such.

Run (cwd = addon_dev):  python tools/ack_latency_sim.py [report.json ...]
"""
from __future__ import annotations

import json
import statistics
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))

DEFAULT_REPORT = next((parent / '03_TESTS' / 'gpt_live_webrtc' / 'native_controlled_socket.json' for parent in ROOT.parents
                      if (parent / '03_TESTS').is_dir()), Path('native_controlled_socket.json'))
WAIT_AFTER_TEXT_MS = (731, 810, 899)          # LATENCY_BASELINE section 3: final minus the moment its text was known (min/median/max)
CONTROLLER_REACTION_MS = 52                   # LATENCY_BASELINE 2.4: final -> next PCM, the controller's own part (median)
TICK_MS = 100                                 # controlled_host.serve ticks the wire every 0.1 s
ANSWER = ('Инерция — это свойство тела сохранять своё состояние движения. Вода кипит при ста градусах. '
          'Свет не нуждается в среде для распространения.')


def ack_steps(report):
    """Every confirming spoken repeat in a probe report (and in the earlier attempts it carries): the timings of the real run."""
    reports = [report] + [r for r in report.get('previous_attempts', []) if isinstance(r, dict)]
    steps = []
    for r in reports:
        for step in r.get('ack_steps') or []:
            keys = ('input_start_ms', 'input_end_ms', 'asr_final_ms', 'first_pcm_ms')
            if step.get('case') != 'full' or not all(isinstance(step.get(k), (int, float)) for k in keys):
                continue
            if not (isinstance(step.get('cursor_before'), int) and step.get('cursor_after') == step['cursor_before'] + 1):
                continue                                         # only a repeat that the base accepted
            steps.append({k: step[k] for k in keys})
    return steps


def simulate(step, *, wait_after_text_ms, stable_seconds, reaction_ms=CONTROLLER_REACTION_MS):
    """Milliseconds from the end of the listener's repeat to the first PCM frame of the next portion, for one recorded step.

    ``stable_seconds=0`` is the base: only the final confirms. Otherwise the transcript is complete ``wait_after_text_ms`` before
    the final and the controller confirms it once it has been unchanged for ``stable_seconds``.
    """
    import helpers_s6_ack as H
    t0 = step['input_start_ms'] / 1000.0
    end = step['input_end_ms'] / 1000.0
    final = step['asr_final_ms'] / 1000.0
    complete = max(t0 + 0.3, final - wait_after_text_ms / 1000.0)
    with tempfile.TemporaryDirectory() as directory:
        clock = H.FakeClock(0.0)
        d = H.Dictation(Path(directory) / 'sim', ANSWER, clock=clock)
        c = d.controller
        c.ack_stable_seconds = stable_seconds
        portion = d.current
        words = portion.split()
        # the partial transcript grows word by word and is complete at ``complete``
        events = [(t0, 'start', None)]
        for n in range(1, len(words) + 1):
            when = t0 + (complete - t0) * n / len(words)
            events.append((when, 'partial', ' '.join(words[:n])))
        events.append((final, 'final', portion))
        events.sort(key=lambda e: e[0])
        decided = None
        sent = ''
        grid = -(-int(t0 * 1000) // TICK_MS) * TICK_MS / 1000.0   # the host ticks on a 0.1 s grid; nothing happens before the listener starts
        pending = list(events)
        horizon = final + 3.0
        while decided is None and grid <= horizon:
            while pending and pending[0][0] <= grid + 1e-9:
                when, kind, text = pending.pop(0)
                clock.now = when
                if kind == 'start':
                    c.speech_started()
                    actions = c.provider(H.created('u-sim', 'user', ''))
                elif kind == 'partial':
                    delta = text[len(sent):]
                    sent = text
                    actions = c.provider({'type': 'turn.delta', 'turn_id': 'u-sim', 'delta': delta,
                                          'start_ms': int(when * 1000), 'end_ms': int(when * 1000) + 1})
                else:
                    actions = c.provider(H.done('u-sim', 'user', text))
                if any(a['type'] == 'speak' for a in actions):
                    decided = when
            if decided is None:
                clock.now = grid
                if any(a['type'] == 'speak' for a in c.tick(now=grid)):
                    decided = grid
            grid = round(grid + TICK_MS / 1000.0, 6)
        if decided is None:
            return None
        return round((decided - end) * 1000 + reaction_ms)


def summarize(steps, *, stable_seconds):
    rows = []
    for wait in WAIT_AFTER_TEXT_MS:
        before = [simulate(s, wait_after_text_ms=wait, stable_seconds=0) for s in steps]
        after = [simulate(s, wait_after_text_ms=wait, stable_seconds=stable_seconds) for s in steps]
        rows.append((wait, before, after))
    return rows


def report_text(path, steps, stable_seconds):
    recorded = [s['first_pcm_ms'] - s['input_end_ms'] for s in steps]
    lines = [f'source: {path}', f'confirming spoken repeats with real timings: {len(steps)}',
             f'recorded (base build), end of repeat -> next PCM, ms: median {statistics.median(recorded):.0f}, '
             f'min {min(recorded)}, max {max(recorded)}',
             f'stable window: {stable_seconds * 1000:.0f} ms; controller reaction added to both: {CONTROLLER_REACTION_MS} ms; '
             f'tick {TICK_MS} ms', '',
             'text known before the final | base median | stable-partial median | gain median | gain min..max']
    for wait, before, after in summarize(steps, stable_seconds=stable_seconds):
        gains = [b - a for b, a in zip(before, after)]
        lines.append(f'{wait:>27} ms | {statistics.median(before):>9.0f} ms | {statistics.median(after):>18.0f} ms | '
                     f'{statistics.median(gains):>9.0f} ms | {min(gains)}..{max(gains)} ms')
    return '\n'.join(lines)


def main(argv):
    from echo_sync.controlled_media import ACK_STABLE_SECONDS
    paths = [Path(a) for a in argv] or [DEFAULT_REPORT]
    for path in paths:
        report = json.loads(path.read_text(encoding='utf-8'))
        steps = ack_steps(report)
        if not steps:
            print(f'{path}: no confirming repeats with timings')
            continue
        print(report_text(path, steps, ACK_STABLE_SECONDS))


if __name__ == '__main__':
    main(sys.argv[1:])
