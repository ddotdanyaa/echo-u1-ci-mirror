"""U137 / E21 / E21.1 / U08: the corpus of dialogs and its loader. A dialog is a scene of one area (``AREAS``, E21.1: five, at least four must be present) with turns of the
speaker; a turn with ``expected`` has a reference the answer is judged against (tools.replay.matrix.judge), a turn without one is ``unjudged`` and stays in the denominator.
Every dialog names its source with a licence (``ALLOWED_LICENSES``): a file without one is refused by ``load``. ``kind='tangled'`` scenes (U08) imitate the form of the owner's
tangled messages: ``requirements`` must be kept, ``unclear`` must be marked, not guessed. The holdout is FROZEN: ``MANIFEST.json`` holds the sha256 of each file and of the whole
split; ``load('holdout')`` raises when a byte differs, so a threshold cannot be tuned on a holdout that moved. ``status()`` says what U137 still lacks (external sources, replicas).
"""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
AREAS = ('everyday', 'science_tech', 'humanities', 'law_econ', 'work')
MIN_AREAS = 4                    # E21.1: at least 4 of 5, none of them empty
ALLOWED_LICENSES = frozenset(('CC0-1.0', 'CC-BY-4.0', 'CC-BY-SA-4.0', 'CC-BY-SA-3.0', 'public-domain', 'MIT', 'Apache-2.0'))
KINDS = frozenset(('qa', 'tangled'))
SOURCE_KINDS = frozenset(('authored', 'external'))
LENGTHS = frozenset(('short', 'long'))
TURN_KINDS = frozenset(('question', 'statement', 'ack', 'tangled'))
U137_EXTERNAL_SOURCES, U137_REPLICAS = 5, 200       # the target of U137: replicas from external sources


class CorpusError(ValueError):
    pass


def _digest(files, prefix):
    whole = hashlib.sha256()
    for key in sorted(k for k in files if k.startswith(prefix)):
        whole.update(key.encode())
        whole.update(bytes.fromhex(files[key]))
    return whole.hexdigest()


def manifest(folder=HERE):
    return json.loads((Path(folder) / 'MANIFEST.json').read_text(encoding='utf-8'))


def verify(split, folder=HERE):
    """Raises CorpusError when a file of the split is missing, new or changed against MANIFEST.json (the freeze); returns the split's sha256."""
    folder, man = Path(folder), manifest(folder)
    have = {f'{split}/{p.name}': hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((folder / split).glob('*.json'))}
    want = {k: v for k, v in man['files'].items() if k.startswith(split + '/')}
    if have != want:
        bad = sorted(set(have) ^ set(want)) or sorted(k for k in have if have[k] != want[k])
        raise CorpusError(f'{split} differs from MANIFEST.json (frozen): {bad[:5]}')
    got = _digest(have, split + '/')
    if got != man[f'{split}_sha256']:
        raise CorpusError(f'{split} sha256 differs from MANIFEST.json')
    return got


def check(dialog):
    """The shape of one dialog; raises CorpusError naming it."""
    name = dialog.get('id', '?')
    src = dialog.get('source') or {}
    if dialog.get('area') not in AREAS:
        raise CorpusError(f'{name}: area {dialog.get("area")!r} is not one of {AREAS}')
    if dialog.get('kind') not in KINDS or dialog.get('split') not in ('dev', 'holdout'):
        raise CorpusError(f'{name}: kind or split is wrong')
    if src.get('license') not in ALLOWED_LICENSES or src.get('kind') not in SOURCE_KINDS or not src.get('name'):
        raise CorpusError(f'{name}: the source needs a name, a kind and a licence of {sorted(ALLOWED_LICENSES)}')
    if src['kind'] == 'external' and not src.get('url'):
        raise CorpusError(f'{name}: an external source needs its url')
    turns = dialog.get('turns')
    if not turns:
        raise CorpusError(f'{name}: no turns')
    for turn in turns:
        if not str(turn.get('user', '')).strip() or turn.get('length') not in LENGTHS or turn.get('kind') not in TURN_KINDS:
            raise CorpusError(f'{name}: a turn lacks text, length or kind')
        if turn.get('expected') is not None and not str(turn['expected']).strip():
            raise CorpusError(f'{name}: an empty reference (use null)')
    if dialog['kind'] == 'tangled' and not dialog.get('requirements'):
        raise CorpusError(f'{name}: a tangled scene lists the requirements it must keep')
    return dialog


def load(split=None, folder=HERE):
    """The dialogs of ``split`` ('dev', 'holdout' or None for both). Each split is verified against the freeze first; ids are unique."""
    folder, out, seen = Path(folder), [], set()
    for one in ((split,) if split else ('dev', 'holdout')):
        if one not in ('dev', 'holdout'):
            raise CorpusError(f'unknown split {one!r}')
        verify(one, folder)
        for path in sorted((folder / one).glob('*.json')):
            dialog = check(json.loads(path.read_text(encoding='utf-8')))
            if dialog['id'] in seen or dialog['split'] != one or path.stem != dialog['id']:
                raise CorpusError(f'{path.name}: a repeated id or a file in the wrong split')
            seen.add(dialog['id'])
            out.append(dialog)
    return out


def coverage(dialogs):
    """Per area: dialogs, turns, turns with a reference; and the lengths seen (adaptivity needs both)."""
    got = {area: {'dialogs': 0, 'turns': 0, 'judged': 0} for area in AREAS}
    lengths = set()
    for dialog in dialogs:
        row = got[dialog['area']]
        row['dialogs'] += 1
        for turn in dialog['turns']:
            row['turns'] += 1
            row['judged'] += 1 if turn.get('expected') else 0
            lengths.add(turn['length'])
    return {'areas': got, 'areas_present': sum(1 for row in got.values() if row['judged']), 'lengths': sorted(lengths)}


def status(dialogs):
    """The honest state against U137 (>= 200 replicas from >= 5 external sources) and E21.1 (>= 4 areas of 5, each with a reference, two lengths)."""
    cov = coverage(dialogs)
    external = {d['source']['name'] for d in dialogs if d['source']['kind'] == 'external'}
    replicas = sum(len(d['turns']) for d in dialogs if d['source']['kind'] == 'external')
    return {'e21_1_ok': cov['areas_present'] >= MIN_AREAS and len(cov['lengths']) >= 2, 'areas_present': cov['areas_present'],
            'external_sources': len(external), 'external_replicas': replicas,
            'u137_ok': len(external) >= U137_EXTERNAL_SOURCES and replicas >= U137_REPLICAS,
            'dialogs': len(dialogs), 'turns': sum(len(d['turns']) for d in dialogs)}


def local_scenes():
    """U08: the real scenes of tangled messages, kept out of git (tests/fixtures/harvest_scenes/scenes.json); [] where the file is absent."""
    path = HERE.parents[1] / 'fixtures' / 'harvest_scenes' / 'scenes.json'
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding='utf-8'))
    return data if isinstance(data, list) else list(data.get('scenes', ()))
