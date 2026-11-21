"""U25-R1: the replay contract, closed against open. A replay feeds the call's own inputs (ear, cloud, time) to the controller on an injected clock. What
the owner did in the journal answers the cues of the journal and only them: from the first cue the controller says differently, the owner's later reactions
(a repeat, a silence, a new question) answered another cue, so every metric from that second on is ``open_replay=true`` - the controller's border, not the
owner's experience. ``divergence`` finds that point; ``mark`` stamps the metrics; ``run`` is the shared runner the acceptances call with their own replay.
"""
import hashlib
import json
from pathlib import Path

from tools.harvest import manifest, words

BORDER = 'controller bound only'


def _text(cue):
    return ' '.join(words(str(cue[1] if isinstance(cue, (list, tuple)) else cue.get('text', ''))))


def _at(cue):
    return float(cue[0] if isinstance(cue, (list, tuple)) else cue.get('t', 0))


def divergence(journal_cues, replay_cues):
    """The first place the replay's cues differ from the journal's: ``None`` when they are the same (a closed replay), else ``{'index', 'at', 'journal', 'replay'}``.
    A cue differs by its words (case and punctuation do not count); a cue only one side has differs too. ``at`` is the earlier second of the two."""
    a, b = list(journal_cues), list(replay_cues)
    for n in range(max(len(a), len(b))):
        if n < len(a) and n < len(b) and _text(a[n]) == _text(b[n]):
            continue
        times = [_at(side[n]) for side in (a, b) if n < len(side)]
        return {'index': n, 'at': min(times), 'journal': _text(a[n]) if n < len(a) else None, 'replay': _text(b[n]) if n < len(b) else None}
    return None


def mark(metrics, point):
    """The metrics (dicts with ``t``, seconds of the call) with ``open_replay``: true from the divergence second on; all false for a closed replay."""
    out = []
    for metric in metrics:
        opened = point is not None and float(metric.get('t', 0)) >= point['at']
        row = dict(metric, open_replay=opened)
        if opened:
            row['bound'] = BORDER
        out.append(row)
    return out


def run(fixture, replay_cues, metrics):
    """One call of an acceptance: the divergence of ``replay_cues`` from the fixture's cues, the marked metrics and the share of them that stay closed."""
    point = divergence(fixture.get('cues', ()), replay_cues)
    marked = mark(metrics, point)
    closed = sum(1 for row in marked if not row['open_replay'])
    return {'divergence': point, 'closed': point is None, 'metrics': marked, 'metrics_closed': closed, 'metrics_open': len(marked) - closed}


def verifier_hash(*paths):
    """The sha256 of the verifier's own files (the manifest names it next to the set's hash)."""
    whole = hashlib.sha256()
    for path in paths:
        whole.update(Path(path).read_bytes())
    return whole.hexdigest()


def corpus(folder=None):
    """The one manifest every acceptance cites: the journals, the hash of the set and of this verifier."""
    got = manifest(folder) if folder else manifest()
    return dict(got, verifier_sha256=verifier_hash(__file__))
