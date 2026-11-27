"""U25-R2: the interaction matrix and the full denominator. Every question of a call gets exactly one status of STATUSES, so correct + wrong + missed + timeout +
invalid + unjudged is the number asked (nothing leaves the denominator). Rightness is only against a reference (scenes ``expected``, gold); a question without one is
``unjudged``. For each PAIR of mechanisms on the dev calls the runner is called four times (base, a, b, a+b); ``interaction_wrong`` = wrong(ab) - wrong(a) - wrong(b) + wrong(base):
what the two do together that neither does alone, one axis at a time. The runner is injected (``runner(fixture, flags) -> [status, ...]``); without one every question is
``unjudged`` (no controller attached: the table then only shows the denominator and its passport says PARTIAL: it is not matrix evidence; U25-R2 stays open until a runner replays a fixture through the controller). Run: python -m tools.replay.matrix [folder]
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from echo_sync.settings import resolve             # noqa: E402
from tools import harvest                          # noqa: E402
from tools.replay import contract                  # noqa: E402

STATUSES = ('correct', 'wrong', 'missed', 'timeout', 'invalid', 'unjudged')
TIMEOUT_S = 12.0
# the axes are NUMERIC settings of the call (settings.DEFAULTS has no on/off behaviour keys); each set differs from the default, ``check_axes`` proves it
FLAGS = {
    'repeat': {'max_auto_repeats': 2}, 'repeat_wait': {'repeat_seconds': 4.0}, 'portion': {'words_per_portion': 4}, 'cover': {'repeat_cover': 0.6},
    'window': {'question_window': 5}, 'cancel': {'cancel_min_words': 2}, 'early': {'ear_early_ms': 200}, 'bank': {'bank_min_words': 3},
}
PAIRS = (('repeat', 'repeat_wait'), ('portion', 'repeat'), ('cover', 'repeat'), ('window', 'cancel'), ('early', 'repeat_wait'), ('bank', 'window'))


def denominator(verdicts):
    """Counts per status in the fixed order; a label outside STATUSES is ``invalid``, never dropped."""
    got = dict.fromkeys(STATUSES, 0)
    for verdict in verdicts:
        got[verdict if verdict in got else 'invalid'] += 1
    return got


def judge(ask, answer, latency, timeout=TIMEOUT_S):
    """One question: ``ask`` has ``text`` and ``expected`` (None: no reference); ``answer`` the text said (None: nothing), ``latency`` seconds to it."""
    if answer is not None and not isinstance(answer, str):
        return 'invalid'
    if answer is None or not answer.strip():
        return 'missed'
    if latency is not None and latency > timeout:
        return 'timeout'
    if not ask.get('expected'):
        return 'unjudged'
    return 'correct' if harvest.said_back(answer, ask['expected']) else 'wrong'


def _unjudged(fixture, flags):
    return ['unjudged' for row in fixture.get('cloud', ()) if row[1] == 'user']


def _flags(*names):
    out = {}
    for name in names:
        out.update(FLAGS[name])
    return out


def check_axes(pairs=PAIRS):
    """Each set (a, b, a+b) must resolve to settings that differ from the base: a value the resolver clamps back to the default would make a set equal to the base and
    book a solo effect as an 'interaction'. Raises ValueError naming the pair and the set."""
    base = resolve({})
    for a, b in pairs:
        for key, names in (('a', (a,)), ('b', (b,)), ('ab', (a, b))):
            if resolve(_flags(*names)) == base:
                raise ValueError(f'matrix pair {a} x {b}: set {key} resolves to the base (a forced-off axis)')


def run(calls, runner=None, manifest=None, pairs=PAIRS):
    """``calls``: {id: fixture}. One row per pair: the denominator of base / a / b / a+b over all calls, and the interaction."""
    runner = runner or _unjudged
    check_axes(pairs)
    rows = []
    for a, b in pairs:
        parts = {key: [] for key in ('base', 'a', 'b', 'ab')}
        for fixture in calls.values():
            for key, names in (('base', ()), ('a', (a,)), ('b', (b,)), ('ab', (a, b))):
                parts[key] += list(runner(fixture, _flags(*names)))
        den = {key: denominator(value) for key, value in parts.items()}
        rows.append({'pair': (a, b), 'n_calls': len(calls), 'asked': len(parts['base']), 'den': den,
                     'interaction_wrong': den['ab']['wrong'] - den['a']['wrong'] - den['b']['wrong'] + den['base']['wrong']})
    return {'rows': rows, 'passport': dict(manifest or {}, n_calls=len(calls), runner='injected' if runner is not _unjudged else 'none (all unjudged)',
                                          status='measured by the injected runner' if runner is not _unjudged else 'PARTIAL: no controller runner, nothing measured; not matrix evidence',
                                          open_replay=None if runner is not _unjudged else 'n/a', border=contract.BORDER)}


def table(out):
    cols = ' '.join(f'{s[:5]:>5}' for s in STATUSES)
    lines = [f'{"pair":<36} {"set":<4} {cols}  interaction_wrong']
    for row in out['rows']:
        for n, key in enumerate(('base', 'a', 'b', 'ab')):
            vals = ' '.join(f'{row["den"][key][s]:>5}' for s in STATUSES)
            lines.append(f'{(" x ".join(row["pair"]) if n == 0 else ""):<36} {key:<4} {vals}  {row["interaction_wrong"] if n == 3 else ""}')
    p = out['passport']
    lines.append('passport ' + ' '.join(f'{k}={v}' for k, v in p.items()))
    return '\n'.join(lines)


def dev_calls(folder=None):
    folder = Path(folder or harvest.OUT_DEFAULT)
    return {one: json.loads((folder / (one + '.json')).read_text(encoding='utf-8')) for one in sorted(harvest.DEV) if (folder / (one + '.json')).exists()}


def main(argv=None):
    folder = (argv if argv is not None else sys.argv[1:] or [None])[0]
    calls = dev_calls(folder)
    got = contract.corpus(folder) if folder else contract.corpus()
    print(table(run(calls, manifest={'count': got['count'], 'sha256': got['sha256'], 'verifier_sha256': got['verifier_sha256'], 'dev': len(calls)})))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
