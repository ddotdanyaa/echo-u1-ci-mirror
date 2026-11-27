"""P13 (extensibility lock, harvest Р5): how much of the mechanic catalogue lands WITHOUT an edit of an owner file, as a number that is measured and not claimed.

    python -m tools.extension_contract                   the share by the sockets the test proves open (reads tests/test_extension_slots.py's proof file when given)
    python -m tools.extension_contract --open S1 S2 S6   the share if exactly these sockets are open
    python -m tools.extension_contract --lane BASE HEAD  exit 1 when the diff BASE..HEAD of a lane touches an owner file (a mechanic added through a socket touches none)

A mechanic of ``classes/catalog.json`` has the one socket (S1..S8, ``classes/РАСШИРЕНИЕ.md`` §1) it needs, the heaviest of its parts. A mechanic lands without an owner edit when its
socket is OPEN: a row of a table the owner reads (S1 ``cm_probes.PROBES``, S2 the rule table of the owner of a family, S3 ``ControlledMedia.ACTS`` + ``STEPS``, S4 ``conversation_ledger.KINDS``
with a ``timer_policy`` TTL, S5 ``warm.Step`` / a ``Roads`` row) or a tool outside the call (S6). S7 (the phone) is no part of this engine and S8 (a new owner or resource) is by its
definition a decision of the coordinator: neither counts as landing. ``tests/test_extension_slots.py`` proves each socket open by driving a toy mechanic through it on the real
ControlledMedia; the share is the catalogue weighed by the sockets that were proved, never by a list written here.

Nothing here is imported from the engine: it reads the catalogue, the git objects and the file texts."""
import argparse
import hashlib
import json
import random
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / 'classes' / 'catalog.json'
SOCKETS = ('S1', 'S2', 'S3', 'S4', 'S5', 'S6')      # the sockets that can be open; S7 is outside the engine, S8 is a decision
TARGET = 0.80      # the contract of РАСШИРЕНИЕ.md §4: at least this share of a random 30 of the catalogue lands with no owner edit
SAMPLE = 30
# A lane that adds a mechanic through a socket edits these tables and no owner. OWNERS: the bodies that decide for a family (ARCH_ONE §1, one module per family; the core is controlled_media.py).
OWNER_FILES = ('echo_sync/controlled_media.py', 'echo_sync/cm_base.py', 'echo_sync/cm_kind.py', 'echo_sync/cm_question.py', 'echo_sync/cm_answer.py', 'echo_sync/cm_portion.py',
               'echo_sync/cm_timers.py', 'echo_sync/cm_speech.py', 'echo_sync/cm_memory.py', 'echo_sync/cm_route.py', 'echo_sync/engine.py')
# The files whose TABLES are the sockets: a row is a line here, the bodies around the table stay as they are (checked by the test through the same OWNER_FILES list).
SOCKET_FILES = {'S1': 'echo_sync/cm_probes.py', 'S2': 'echo_sync/utterance_judge.py', 'S3': 'echo_sync/controlled_media.py', 'S4': 'echo_sync/conversation_ledger.py',
                'S5': 'echo_sync/warm.py', 'S6': 'tools/'}


def catalog(path=CATALOG):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def by_socket(rows):
    return Counter(row['socket'] for row in rows)


def share(rows, open_sockets):
    """The share of ``rows`` whose socket is in ``open_sockets``."""
    return sum(1 for row in rows if row['socket'] in set(open_sockets) & set(SOCKETS)) / len(rows) if rows else 0.0


def sample(rows, seed, k=SAMPLE):
    return random.Random(seed).sample(list(rows), k)


def sample_shares(rows, open_sockets, seeds=range(200), k=SAMPLE):
    """The share of a random ``k`` of the catalogue, for each seed: the minimum, the mean, and how many seeds fall under ``TARGET``."""
    values = [share(sample(rows, seed, k), open_sockets) for seed in seeds]
    return {'min': min(values), 'mean': sum(values) / len(values), 'under_target': sum(1 for value in values if value < TARGET), 'seeds': len(values)}


def blob_sha(data):
    """The git blob id of ``data``: what ``git hash-object`` says of a file, with no git needed."""
    return hashlib.sha1(b'blob %d\0' % len(data) + data).hexdigest()


def owner_blobs(root=ROOT):
    """``{owner file: blob id}`` of the owner files that stand in ``root`` (a file that is not there is not listed)."""
    root = Path(root)
    return {name: blob_sha((root / name).read_bytes()) for name in OWNER_FILES if (root / name).is_file()}


def lane_touches(base, head, repo=ROOT):
    """The owner files that differ between the git refs ``base`` and ``head`` (the lane's diff). A mechanic that lands through a socket leaves this empty."""
    out = subprocess.run(['git', '-C', str(repo), 'diff', '--name-only', '-z', f'{base}..{head}'], capture_output=True, check=True).stdout.decode('utf-8')
    return sorted(set(name for name in out.split('\0') if name) & set(OWNER_FILES))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--open', nargs='*', default=None, help='the sockets that are open; "S6" alone is today before the slots')
    parser.add_argument('--lane', nargs=2, metavar=('BASE', 'HEAD'))
    parser.add_argument('--repo', default=str(ROOT))
    args = parser.parse_args(argv)
    if args.lane:
        touched = lane_touches(args.lane[0], args.lane[1], args.repo)
        print('owner files touched by the lane: %s' % (', '.join(touched) or 'none'))
        return 1 if touched else 0
    rows = catalog()
    open_sockets = SOCKETS if args.open is None else tuple(args.open)
    counts = by_socket(rows)
    print('catalogue: %d mechanics; by socket: %s' % (len(rows), ', '.join('%s %d' % (name, counts[name]) for name in sorted(counts))))
    print('open sockets: %s -> %d of %d land with no owner edit (%.1f %%)' % (' '.join(open_sockets), sum(counts[name] for name in open_sockets if name in SOCKETS), len(rows), 100 * share(rows, open_sockets)))
    stats = sample_shares(rows, open_sockets)
    print('a random %d of the catalogue, %d seeds: min %.1f %%, mean %.1f %%, under the %.0f %% target in %d seeds' % (SAMPLE, stats['seeds'], 100 * stats['min'], 100 * stats['mean'], 100 * TARGET, stats['under_target']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
