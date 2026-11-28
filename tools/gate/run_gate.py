"""N182/N183: run pytest under the heavy slot and return its verdict as the exit code (0 green; 1 red; 5 nothing collected counts as red; 75 slot busy).
A summary json line (passed/failed/skipped/xfailed/...) is printed last, so a pipe to tail still shows it; use PIPESTATUS / pipefail for the code."""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.gate.slot import HeavySlot, SlotBusy

KEYS = ('passed', 'failed', 'error', 'skipped', 'xfailed', 'xpassed', 'deselected')


def summarize(text):
    tail = [l for l in text.splitlines() if re.search(r'\d+ (passed|failed|error|skipped|xfailed|xpassed|deselected)|no tests ran', l)]
    counts = {k: 0 for k in KEYS}
    for n, k in re.findall(r'(\d+) (passed|failed|errors?|skipped|xfailed|xpassed|deselected)', tail[-1] if tail else ''):
        counts['error' if k.startswith('error') else k] = int(n)
    return counts


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    mine, _, pytest_args = (argv[:argv.index('--')], '--', argv[argv.index('--') + 1:]) if '--' in argv else (argv, '', [])
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--lock', default=os.environ.get('ECHO_HEAVY_LOCK', str(Path(__file__).resolve().parents[2] / '.heavy-slot.lock')))
    p.add_argument('--wait', type=float, default=0.0, help='seconds to wait for the slot')
    p.add_argument('--owner', default=os.environ.get('USER', 'gate'))
    a = p.parse_args(mine)
    try:
        with HeavySlot(a.lock, owner=a.owner, wait=a.wait):
            started = time.time()
            run = subprocess.run([sys.executable, '-m', 'pytest', '-p', 'no:cacheprovider', *pytest_args], capture_output=True, text=True)
    except SlotBusy as e:
        print(f'{{"slot_busy": {json.dumps(str(e))}}}')
        return 75
    sys.stdout.write(run.stdout)
    sys.stderr.write(run.stderr)
    counts = summarize(run.stdout)
    ran = counts['passed'] + counts['failed'] + counts['error'] + counts['xfailed'] + counts['xpassed']
    red = run.returncode != 0 or counts['failed'] or counts['error'] or ran == 0 or counts['xpassed']
    print(json.dumps({**counts, 'pytest_code': run.returncode, 'seconds': round(time.time() - started, 1), 'verdict': 'red' if red else 'green'}))
    return 1 if red else 0


if __name__ == '__main__':
    sys.exit(main())
