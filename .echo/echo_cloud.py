"""Run the ECHO product tests on the free GitHub Actions of the public mirror, in parallel shards, and bring the result back.

  python -m tools.echo_cloud sweep [--src PATH] [--files GLOB ...] [--shards N] [--label L]   -> prints results.json path
  python -m tools.echo_cloud scan [--src PATH]                                                  -> secrets scan only
  python .echo/echo_cloud.py merge JUNIT_DIR SHARDS_DIR OUT.json                                (this file, inside the cloud job)

The owner's order of 21.11 lets ECHO code and tests go to the public mirror; passwords, keys, tokens, .env files,
SECRETS_LOCAL, call recordings and call logs, evidence/ audio never do. So:

  build()    copies echo_sync/ tests/ tools/ and the root pytest files from a product tree, drops the secret/log/recording
             names, and scans every copied text file; one hit (class and file:line, never the value) writes nothing.
  publish()  one fresh orphan commit on a NEW branch ``echo/<label>`` of the mirror (never main, never forced), with the
             generated workflow, the shard lists and the pinned requirements; returns the run id of the push-triggered run.
  wait_results()  polls ``gh run view``; a run that does not start within START_S is dead (CloudDead: the caller falls back);
             downloads the merged results.json (or merges the shards' JUnit itself when the merge job failed).

Reused from tools/factory_mirror.py: git environment and prompts policy, the credential-failure text, the whole-directory
marker/rmtree helpers, the LPT shard packing, the mirror address; from tools/factory_cloud_gate.py: the git/gh runner.
This module needs no network or gh to import; the ``merge`` half is stdlib only (it runs in the cloud without the factory).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import contextlib
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from collections import namedtuple
from pathlib import Path

try:                                    # inside the cloud job this file runs as a plain script: no package, no factory
    from . import factory_mirror as fm
    from . import factory_cloud_gate as gate
except ImportError:
    fm = gate = None

Hit = namedtuple('Hit', 'cls file line')

# --------------------------------------------------------------------------------------------------------- constants
DEFAULT_SRC = str(Path.home().anchor) + os.path.join('УСТРОЙСТВО 1', 'U1', '05_WORK', 'W7', 'stage', 'factory_night_wt')
DEFAULT_WORK = os.environ.get('ECHO_CLOUD_WORK') or str(Path(tempfile.gettempdir()) / 'echo_cloud')
TOP_DIRS = ('echo_sync', 'tests', 'tools')
ROOT_FILE_RE = re.compile(r'(?:conftest|pytest|setup|host_patch|install_echo|echo_provider_ui_patch)\.py|pytest\.ini|tox\.ini'
                          r'|setup\.cfg|pyproject\.toml|requirements[A-Za-z0-9_.-]*\.txt|MANIFEST\.json')
DROP_DIRS = frozenset(('__pycache__', '.git', '.hypothesis', '.pytest_cache', 'SECRETS_LOCAL', 'evidence', 'echo_calls',
                       'recordings', 'call_logs', 'calls', '.venv', 'venv', 'site-packages', '.test-venv', '.test-deps',
                       'node_modules'))
DROP_PREFIXES = ('tests/fixtures/harvest/',)         # harvested call material: git-ignored in the product, never copied
DROP_NAME = re.compile(r'(?i)\.env(\..*)?|.*\.(?:key|pem|log|pyc|pyo)|auth\.json')
GENERATED = ('.echo', '.github')                     # written by publish(): not product files, not scanned as product
WORKFLOW_PATH = '.github/workflows/echo-tests.yml'
SHARD_DIR = '.echo/shards'
REQ_PATH = '.echo/requirements.txt'
SELF_PATH = '.echo/echo_cloud.py'
PROFILE_PLUGIN_PATH = '.echo/factory_profile_plugin.py'   # the factory's profile plugin (tools/factory_gate._PROFILE_PLUGIN), shipped when a trace is asked
TRACE_PATH = '.echo/trace.txt'                           # its source prefixes, one per line
PROFILE_RE = 'profile-*.json'                            # one per shard, uploaded next to the shard's JUnit
TRACE_PREFIX = re.compile(r'[A-Za-z0-9_][A-Za-z0-9_./-]*')
ARTIFACT = 'echo-results'
BRANCH_PREFIX = 'echo/'
START_S = 300                                        # a run that has not started by then is dead: the caller falls back
QUEUED_MAX_S = 900                                   # a run in GitHub's queue ('queued') is alive: it is waited for this long, no dead mark
QUEUED_STATES = ('queued', 'waiting', 'requested', 'pending')
POLL_S = 10
RUNS_TTL_S = 8                                       # the shared list of the mirror's runs is fetched again after this long
RUNS_LIST_LIMIT = 100
RUNS_CACHE = Path(tempfile.gettempdir()) / 'factory_cloud_runs.json'      # tests replace these attributes
RUNS_LOCK = Path(tempfile.gettempdir()) / 'factory_cloud_runs.lock'
PUSH_RETRY_S = (10, 30)                               # pauses before the 2nd and 3rd push of one tree
PUSH_JITTER_S = (5, 20)                               # a '! [remote rejected] ... (failed)' push: the pause before it is repeated (random in this range)
PUSH_REFUSED_RETRIES = 4                              # ... repeated this many times at most (live 23.11 08:58: four cards at once, all refused)
PUSH_LOCK = Path(tempfile.gettempdir()) / 'factory_cloud_push.lock'   # a folder: one push of this machine at a time (tests replace it)
PUSH_LOCK_STALE_S = 180                               # a push never lasts this long: its owner died
PUSH_LOCK_WAIT_S = 240                                # waits for its turn at most this long, then pushes anyway
WAIT_MIN_S, WAIT_MAX_S, WAIT_UNKNOWN_S = 1800, 7200, 3600   # the wait for a run: from the measured longest shard, these bounds; no measure: the last
SHARD_JOB_MIN = 30                                    # the workflow's job limit (minutes) of a shard with no measure; a measured one gets 2x its time
PYTHON = '3.12'
TEST_TIMEOUT_S = 120
# the pinned test environment: cloud_context/SETUP_CLOUD.sh + echo_sync/plugin.yaml (+ websockets, numpy, pytest-timeout)
REQUIREMENTS = ('RapidFuzz==3.14.6', 'razdel==0.5.0', 'pymorphy3==2.0.6', 'pymorphy3-dicts-ru==2.4.417150.4580142',
                'DAWG2-Python==0.9.0', 'setuptools==84.2.1', 'diskcache==5.6.3', 'snowballstemmer==3.1.1',
                'websockets==15.0.1', 'numpy==2.2.6', 'pytest==9.1.1', 'pytest-timeout==2.4.0',
                'hypothesis==6.170.14', 'httpx==0.28.1', 'httpcore==1.0.9')


class Blocked(RuntimeError):
    """The secrets scan found something: nothing was written or published. ``hits`` are Hit(class, file, line)."""

    def __init__(self, hits):
        super().__init__('secrets scan blocked the publication:\n' + report(hits))
        self.hits = hits


class CloudDead(RuntimeError):
    """The cloud route did not answer (no run, never started, timeout, no result): the caller takes its fallback."""


class PushRefused(RuntimeError):
    """The mirror refused the push ('remote rejected', after every repeat): a busy mirror, not a dead cloud (no dead mark)."""


class CloudQueued(RuntimeError):
    """The cloud is alive, but the run stayed in GitHub's queue longer than QUEUED_MAX_S (or no place came): wait, not dead."""


# ------------------------------------------------------------------------------------------------- secrets scan
_SECRET_PATTERNS = (
    ('google-key', re.compile(r'AIza[0-9A-Za-z_-]{10,}')),
    ('sk-key', re.compile(r'(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{10,}')),
    ('github-token', re.compile(r'gh[pousr]_[A-Za-z0-9]{10,}|github_pat_[A-Za-z0-9_]{10,}')),
    ('slack-token', re.compile(r'xox[bp]-[A-Za-z0-9-]{5,}')),
    ('private-key', re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----')),
    # the classes of tools/push_guard.py and of the mirror's scanner that were missing here (Groq, AWS, GitLab, npm, Google OAuth, JWT, Bearer)
    ('provider-key', re.compile(r'(?<![A-Za-z0-9])(?:gsk_[A-Za-z0-9]{10,}|(?:AKIA|ASIA)[0-9A-Z]{16}|glpat-[A-Za-z0-9_-]{10,}'
                                r'|npm_[A-Za-z0-9]{20,}|ya29\.[A-Za-z0-9_-]{10,})')),
    ('jwt', re.compile(r'(?<![A-Za-z0-9])eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}')),
    ('bearer', re.compile(r'(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{20,}')),
    ('assigned-secret', re.compile(r'''(?i)(api[_-]?key|token|secret|password)\s*[:=]\s*['"][^'"]{12,}''')),
)
# Lines read by hand: a test sentinel such as SECRET = '<a word>' is no key. sha256(stripped line)[:16] + class, the factory
# mirror's own mechanism: an edited line is a new hit again. Keys are never listed here; they are removed from the code.
REVIEWED = frozenset(('5e831fee732374b1assigned-secret', '96a146109b53d76eassigned-secret', 'a85f5015f01509acassigned-secret',
                      'f5d1c6e35cde552fassigned-secret', '4309659aad7c8118assigned-secret', '567313e08d4af3cfassigned-secret'))


def _line_id(line):
    return hashlib.sha256(line.strip().encode('utf-8')).hexdigest()[:16]


def scan_text(rel, text):
    """Hits (class, file, line) of one text file; the matched text is never returned."""
    hits = []
    for number, line in enumerate(text.splitlines(), 1):
        for cls, pattern in _SECRET_PATTERNS:
            if pattern.search(line) and _line_id(line) + cls not in REVIEWED:
                hits.append(Hit(cls, rel, number))
    return hits


def scan_bytes(rel, data):
    """UTF-8 text is scanned as it is (NUL bytes dropped: a UTF-16 file without a BOM is still read); UTF-16 with a BOM and any
    other single-byte text (cp1251) are scanned too, so a key cannot hide in an encoding. Only a real binary (a WAV, a pickle:
    NUL bytes at its head and no valid text decoding) has no lines to scan."""
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError:
        if data[:2] in (b'\xff\xfe', b'\xfe\xff'):
            text = data.decode('utf-16', 'replace')
        elif b'\0' in data[:8192]:
            return []
        else:
            text = data.decode('latin-1')
    return scan_text(rel, text.replace('\0', ''))


def scan_tree(root):
    """The exact tree about to be committed; the generated .echo/.github files are ours and are not scanned."""
    root = Path(root)
    hits = []
    for path in sorted(p for p in root.rglob('*') if p.is_file()):
        rel = path.relative_to(root).as_posix()
        if rel.split('/', 1)[0] in GENERATED or (fm and path.name == fm.MARKER):
            continue
        hits += scan_bytes(rel, path.read_bytes())
    return hits


def report(hits):
    return '\n'.join('  %s %s:%d' % (h.cls, h.file, h.line) for h in sorted(hits, key=lambda h: (h.file, h.line, h.cls)))


# ------------------------------------------------------------------------------------------------------- build
def keep(rel):
    """True when the product-relative path may go to the mirror."""
    parts = rel.split('/')
    name = parts[-1]
    if len(parts) == 1:
        return bool(ROOT_FILE_RE.fullmatch(name)) and not DROP_NAME.fullmatch(name)
    if parts[0] not in TOP_DIRS or any(p in DROP_DIRS for p in parts[:-1]) or DROP_NAME.fullmatch(name):
        return False
    return not any(rel.startswith(prefix) for prefix in DROP_PREFIXES)


def _git_listing(src):
    """Tracked + untracked-but-not-ignored files of a git product tree (a git-ignored file never goes), or None."""
    if not (src / '.git').exists() or fm is None:
        return None
    try:
        done = subprocess.run([*fm.GIT_PREFIX, 'ls-files', '-z', '--cached', '--others', '--exclude-standard'], cwd=src,
                              capture_output=True, env=fm._git_env(), timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode:
        return None
    return [x.decode('utf-8', 'replace') for x in done.stdout.split(b'\0') if x]


def list_source(src):
    """Sorted product-relative posix paths that pass keep() and exist."""
    src = Path(src)
    rels = _git_listing(src)
    if rels is None:
        rels = [p.relative_to(src).as_posix() for p in src.rglob('*') if p.is_file()]
    return sorted({r for r in rels if keep(r) and (src / r).is_file() and not _recording(src, r)})


RECORDING_EXT = ('.wav', '.pcm', '.m4a', '.mp3', '.ogg', '.opus', '.flac', '.jsonl')


def _recording(src, rel):
    """True for an audio file or a .jsonl journal that may be a call's own (tools/push_guard.py's rule, the product's own
    gate before a push: allowed only where a manifest says the recordings are synthesized). A binary has no scan, so its
    NAME is the only guard; code (.py) is never dropped here (a test would lose a helper and turn red for nothing)."""
    if not rel.lower().endswith(RECORDING_EXT):
        return False
    try:
        from . import push_guard
        return bool(push_guard.forbidden_path(rel, src))
    except Exception:                       # noqa: BLE001  no push_guard in this tree: every such file stays at home
        return True


def build(src_root=None, out_dir=None, scan=True):
    """Copy the publishable part of a product tree into ``out_dir`` after scanning every copied file (``scan=False``: the
    caller scanned this base itself, once for its commit - the scan is cached per SHA). Returns
    ``{'out', 'files', 'hits', 'src'}``; with hits nothing is written."""
    src = Path(src_root or DEFAULT_SRC)
    if not src.is_dir():
        raise FileNotFoundError('product tree not found')
    rels = list_source(src)
    data, hits = {}, []
    for rel in rels:
        data[rel] = (src / rel).read_bytes()
        if scan:
            hits += scan_bytes(rel, data[rel])
    out = Path(out_dir) if out_dir else Path(tempfile.mkdtemp(prefix='echo_tree_'))
    if hits:
        return {'out': str(out), 'files': [], 'hits': hits, 'src': str(src)}
    out = Path(fm._prepare_out(out))          # empties it only when it carries the marker (or is new): never another folder
    for rel, blob in data.items():
        target = out / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(blob)
    _write_manifest(out, rels)
    return {'out': str(out), 'files': rels, 'hits': [], 'src': str(src)}


def _write_manifest(out, rels):
    (Path(out) / fm.MARKER).write_text(json.dumps({'files': sorted(rels)}), encoding='utf-8')


# ------------------------------------------------------------------------------------------------- test selection
def select_tests(tree, patterns=None):
    """Sorted posix paths of the test files to run: the glob ``patterns`` (relative to the tree, ``**`` allowed) or, without
    patterns, every tests/**/test_*.py. A path of a file that is not there is ignored."""
    tree = Path(tree)
    found = set()
    for pattern in (patterns or ['tests/**/test_*.py']):
        pattern = pattern.replace('\\', '/')
        for path in tree.glob(pattern):
            if path.is_file() and path.suffix == '.py':
                found.add(path.relative_to(tree).as_posix())
    return sorted(found)


def split_shards(files, n=20, durations=None, sizes=None):
    """Deterministic split of ``files`` into at most ``n`` shards, every file exactly once. Balanced by LPT (the factory
    mirror's own packer) on the measured seconds of an earlier run, else on the file sizes; ``[]`` for no files."""
    ordered = sorted(set(files))
    if not ordered:
        return []
    n = max(1, min(int(n), len(ordered)))
    weight = {f: v for f, v in (durations or {}).items() if f in ordered}
    if not weight:
        weight = {f: float(s) for f, s in (sizes or {}).items() if f in ordered}
    if not weight or n == 1:
        return [ordered] if n == 1 else _hash_split(ordered, n)
    return fm.shards(ordered, -(-len(ordered) // n), weight)


def _hash_split(ordered, n):
    parts = [[] for _ in range(n)]
    for f in ordered:
        parts[int(hashlib.sha1(f.encode('utf-8')).hexdigest()[:8], 16) % n].append(f)
    return [p for p in parts if p]


# --------------------------------------------------------------------------------------------------- generated files
def requirements_for(conftest_text=''):
    """The pinned list plus any REQUIRED_LIBRARIES name of the product's conftest that the list does not cover."""
    have = {re.split(r'[=<>~ ]', r, maxsplit=1)[0].lower().replace('_', '-') for r in REQUIREMENTS}
    extra = [n for n in (fm.required_libraries(conftest_text) if fm else ()) if n.lower().replace('_', '-') not in have]
    return list(REQUIREMENTS) + extra


def trace_prefixes(trace):
    """The usable source prefixes of a ``trace`` (relative, no option-like or odd characters: they reach a shell line)."""
    return sorted({t.replace('\\', '/') for t in trace or () if TRACE_PREFIX.fullmatch(t.replace('\\', '/'))
                   and '..' not in t.replace('\\', '/').split('/')})


def predicted_shards(parts, durations):
    """Seconds each shard is expected to take (the sum of the measured seconds of its files; a file with no measure counts as the
    median of the measured ones), or [] when nothing in ``parts`` was ever measured."""
    known = sorted(v for p in parts for f in p for v in [(durations or {}).get(f)] if isinstance(v, (int, float)))
    if not known:
        return []
    median = known[len(known) // 2]
    return [round(sum(float((durations or {}).get(f, median)) for f in p), 1) for p in parts]


def wait_for(predicted):
    """How long a run is waited for: twice the longest expected shard plus 15 minutes (GitHub's queue and the merge job), within
    WAIT_MIN_S..WAIT_MAX_S; with no measure WAIT_UNKNOWN_S. Live 23.11: a constant 1866 s was shorter than a sweep that ran on."""
    if not predicted:
        return WAIT_UNKNOWN_S
    return int(max(WAIT_MIN_S, min(WAIT_MAX_S, 2 * max(predicted) + 900)))


def shard_job_minutes(predicted):
    """The job limit of the workflow's shards: 2x the longest expected shard (minutes) plus 5, never under SHARD_JOB_MIN."""
    if not predicted:
        return SHARD_JOB_MIN
    return int(max(SHARD_JOB_MIN, min(360, -(-2 * max(predicted) // 60) + 5)))


def render_workflow(shards, python=PYTHON, timeout_s=TEST_TIMEOUT_S, trace=False, job_min=SHARD_JOB_MIN, hypo=False):
    """The cloud job: ``shards`` parallel jobs on ubuntu-latest (each reads its own list file), per-test timeout, one JUnit
    artifact per shard, and a merge job that turns them into results.json. ``trace``: every shard runs the profile plugin
    (the functions each test ran, PROFILE_PLUGIN_PATH) and uploads its profile-N.json next to its JUnit."""
    shard_ids = ', '.join(str(i) for i in range(1, shards + 1))
    pytest_line = ('            python -m pytest "${T[@]}" -q -p no:cacheprovider --tb=short --continue-on-collection-errors'
                   ' --timeout=%d --junitxml=junit-${{ matrix.shard }}.xml' % timeout_s)
    if trace:
        pytest_line = ('            PYTHONPATH="$PWD/.echo" FACTORY_PROFILE_ROOT="$PWD" FACTORY_PROFILE_PREFIXES="$(paste -sd"|" ' + TRACE_PATH
                       + ')" FACTORY_PROFILE_OUT="profile-${{ matrix.shard }}.json" ' + pytest_line.lstrip()
                       + ' -p factory_profile_plugin')
    run_steps = [pytest_line, '          fi']
    upload = (['          path: |', '            junit-${{ matrix.shard }}.xml', '            profile-${{ matrix.shard }}.json']
              if trace else ['          path: junit-${{ matrix.shard }}.xml'])
    if hypo:      # W-hyp: ONE shard: every candidate of hypo/cands.json is applied in turn and the red ids are run
        run_steps = ['          python ' + SELF_PATH + ' hypo hypo/cands.json hypo/ids.txt hypo-result-${{ matrix.shard }}.json'
                     ' --stub junit-${{ matrix.shard }}.xml', '          fi']
        upload = ['          path: |', '            junit-${{ matrix.shard }}.xml', '            hypo-result-${{ matrix.shard }}.json']
    return '\n'.join([
        'name: echo-tests', 'on:', '  push:', "    branches: ['echo/**']", '  workflow_dispatch:', 'permissions:',
        '  contents: read', 'jobs:', '  tests:', '    name: shard ${{ matrix.shard }}', '    runs-on: ubuntu-latest',
        '    timeout-minutes: %d' % job_min, '    strategy:', '      fail-fast: false', '      matrix:',
        '        shard: [' + shard_ids + ']', '    env:', "      PYTHONUTF8: '1'", '    steps:',
        '      - uses: actions/checkout@v4', '        with:', '          persist-credentials: false',
        '      - uses: actions/setup-python@v5', '        with:', "          python-version: '" + python + "'",
        '          cache: pip', '          cache-dependency-path: ' + REQ_PATH,
        '      - name: Install test dependencies',
        '        run: python -m pip install --disable-pip-version-check -r ' + REQ_PATH,
        '      - name: Run shard', '        shell: bash', '        run: |',
        '          f=' + SHARD_DIR + '/${{ matrix.shard }}.txt',
        '          if [ -s "$f" ]; then', '            mapfile -t T < "$f"',
        *run_steps,
        '      - uses: actions/upload-artifact@v4', '        if: always()', '        with:',
        '          name: junit-${{ matrix.shard }}',
        *upload,
        '          if-no-files-found: ignore',
        '  merge:', '    needs: tests', '    if: always()', '    name: merge', '    runs-on: ubuntu-latest',
        '    timeout-minutes: 10', '    steps:', '      - uses: actions/checkout@v4', '        with:',
        '          persist-credentials: false', '      - uses: actions/download-artifact@v4', '        with:',
        '          pattern: junit-*', '          path: junit', '          merge-multiple: true',
        '      - name: Merge JUnit into results.json',
        '        run: python3 ' + SELF_PATH + ' merge junit ' + SHARD_DIR + ' results.json',
        '      - uses: actions/upload-artifact@v4', '        with:', '          name: ' + ARTIFACT,
        '          path: results.json']) + '\n'


def write_generated(tree, parts, requirements, trace=(), job_min=SHARD_JOB_MIN, hypo=None):
    """Write the workflow, shard lists, requirements and this very file (the merge half) into the tree. ``trace``: source
    prefixes; with any usable one the profile plugin and its prefixes ride along and the workflow runs it."""
    trace = trace_prefixes(trace)
    tree = Path(tree)
    shard_dir = tree / SHARD_DIR
    if shard_dir.exists():
        shutil.rmtree(shard_dir)
    shard_dir.mkdir(parents=True)
    for number, files in enumerate(parts, 1):
        (shard_dir / ('%d.txt' % number)).write_text('\n'.join(files) + '\n', encoding='utf-8', newline='\n')
    texts = [(REQ_PATH, '\n'.join(requirements) + '\n'),
             (WORKFLOW_PATH, render_workflow(len(parts), trace=bool(trace), job_min=job_min, hypo=bool(hypo)))]
    if hypo:      # W-hyp: the candidates file and the red ids ride along (one shard, see hypo_batch)
        texts += [(HYPO_DIR + '/cands.json', json.dumps(hypo['files'])), (HYPO_DIR + '/ids.txt', '\n'.join(hypo['ids']) + '\n')]
    if trace:
        from . import factory_gate     # the ONE source of the plugin: the local gate writes the very same text
        texts += [(PROFILE_PLUGIN_PATH, factory_gate._PROFILE_PLUGIN), (TRACE_PATH, '\n'.join(trace) + '\n')]
    for rel, text in texts:
        (tree / rel).parent.mkdir(parents=True, exist_ok=True)
        (tree / rel).write_text(text, encoding='utf-8', newline='\n')
    shutil.copyfile(__file__, tree / SELF_PATH)


# ------------------------------------------------------------------------------------------------- junit -> results
def _split_ids(classname, name, known):
    """(file, nodeid) of a JUnit testcase. ``known``: {dotted module: path}, the shard lists, decides when it can."""
    classname, name = str(classname or ''), str(name or '')
    parts = classname.split('.') if classname else []
    for i in range(len(parts), 0, -1):
        dotted = '.'.join(parts[:i])
        if dotted in known:
            return known[dotted], '::'.join([known[dotted], *parts[i:], name])
    for text in (classname, name):            # a collection error has classname '' and the dotted module as name
        walked = []
        for part in text.split('.') if text else []:
            walked.append(part)
            if part.startswith('test_'):
                rel = '/'.join(walked) + '.py'
                return rel, '::'.join([rel, *text.split('.')[len(walked):], name if text == classname else '<collection>'])
    return (classname.replace('.', '/') + '.py') or 'unknown', name or 'unknown'


def parse_junit(text, known=None):
    """[(file, nodeid, status, seconds)], status in passed / failed / error / skipped. Unparseable XML gives []."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []
    out = []
    for case in root.iter('testcase'):
        rel, nodeid = _split_ids(case.get('classname'), case.get('name'), known or {})
        if case.find('error') is not None:
            status = 'error'
        elif case.find('failure') is not None:
            status = 'failed'
        elif case.find('skipped') is not None:
            status = 'skipped'
        else:
            status = 'passed'
        try:
            seconds = float(case.get('time') or 0.0)
        except ValueError:
            seconds = 0.0
        out.append((rel, nodeid, status, seconds))
    return out


FAILURE_CHARS = 1500       # the failure text kept per red test (W-redrow 2): the assert line, the message, the last frames


def _tail_text(text, cap=FAILURE_CHARS):
    """The text of a failure cut to ``cap`` characters from the END (the assert line and the last frames are at the bottom)."""
    text = (text or '').strip()
    return text if len(text) <= cap else '...' + text[-(cap - 3):]


def parse_failures(text, known=None):
    """{nodeid: failure text (<= FAILURE_CHARS)} of the red testcases of one JUnit XML; unparseable XML gives {}."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return {}
    out = {}
    for case in root.iter('testcase'):
        node = case.find('failure')
        node = case.find('error') if node is None else node
        if node is None:
            continue
        _rel, nodeid = _split_ids(case.get('classname'), case.get('name'), known or {})
        body = ((node.get('message') or '') + '\n' + (node.text or '')).strip() if (node.text or '').strip() \
            else (node.get('message') or '').strip()
        out[nodeid] = _tail_text(body)
    return out


def merge_junit(xml_texts, shard_files=(), failures=False):
    """results ``{file: {passed, failed, errors, failed_ids, skipped, seconds[, missing]}}`` from the JUnit XML of all
    shards. A file named by a shard list that produced no testcase at all (the shard died) is an error, never a pass.
    ``failures=True``: a file with red tests also carries ``failures`` = {nodeid: failure text} (the text the build keeps)."""
    shard_files = sorted(set(shard_files))
    known = {f[:-3].replace('/', '.'): f for f in shard_files if f.endswith('.py')}
    results = {}
    if failures:
        for text in xml_texts:
            for nodeid, body in parse_failures(text, known).items():
                row = results.setdefault(nodeid.split('::', 1)[0], {'passed': 0, 'failed': 0, 'errors': 0, 'failed_ids': [],
                                                                    'skipped': 0, 'seconds': 0.0})
                row.setdefault('failures', {})[nodeid] = body

    def slot(rel):
        return results.setdefault(rel, {'passed': 0, 'failed': 0, 'errors': 0, 'failed_ids': [], 'skipped': 0, 'seconds': 0.0})

    for text in xml_texts:
        for rel, nodeid, status, seconds in parse_junit(text, known):
            row = slot(rel)
            row['seconds'] = round(row['seconds'] + seconds, 3)
            if status == 'passed':
                row['passed'] += 1
            elif status == 'skipped':
                row['skipped'] += 1
            else:
                row['failed' if status == 'failed' else 'errors'] += 1
                row['failed_ids'].append(nodeid)
    for rel in shard_files:
        if rel not in results:
            results[rel] = {'passed': 0, 'failed': 0, 'errors': 1, 'failed_ids': [rel + '::<no result: its shard did not finish>'],
                            'skipped': 0, 'seconds': 0.0, 'missing': True}
    return dict(sorted(results.items()))


def read_shard_lists(shards_dir):
    files = []
    for path in sorted(Path(shards_dir).glob('*.txt')):
        files += [x.strip() for x in path.read_text(encoding='utf-8').splitlines() if x.strip()]
    return files


def merge_dirs(junit_dir, shards_dir, out_path):
    texts = [p.read_text(encoding='utf-8', errors='replace') for p in sorted(Path(junit_dir).rglob('*.xml'))] \
        if Path(junit_dir).exists() else []
    results = merge_junit(texts, read_shard_lists(shards_dir) if Path(shards_dir).exists() else (), failures=True)
    Path(out_path).write_text(json.dumps(results, indent=1, sort_keys=True) + '\n', encoding='utf-8')
    return results


def summarize(results):
    """(files_green, files_red, tests_passed, tests_red) of a results dict."""
    red = [r for r in results.values() if r['failed'] or r['errors']]
    return (len(results) - len(red), len(red), sum(r['passed'] for r in results.values()),
            sum(r['failed'] + r['errors'] for r in results.values()))


def durations_of(results):
    return {f: r['seconds'] for f, r in results.items() if not r.get('missing')}


# ---------------------------------------------------------------------------------------------------- cloud route
def _slug():
    return fm._remote_slug(fm.DEFAULT_REMOTE)


def _runner(runner):
    return runner or gate._default_runner


def _json(out):
    try:
        return json.loads(out.decode('utf-8', 'replace') or 'null')
    except ValueError:
        return None


_TAKEN = re.compile(r'already exists|non-fast-forward|fetch first|cannot lock ref|\(rejected\)', re.I)
_REFUSED = re.compile(r'remote rejected', re.I)


@contextlib.contextmanager
def _push_turn(clock, sleep):
    """The pushes of one machine go one by one: a folder made with mkdir is the turn (dead or old owner: taken over).
    After PUSH_LOCK_WAIT_S (or a lock folder that cannot be made) the push goes without a turn, never stalls."""
    mine = False
    waited = 0.0
    while True:
        try:
            os.mkdir(PUSH_LOCK)
            mine = True
            break
        except FileExistsError:
            try:
                if time.time() - os.stat(PUSH_LOCK).st_mtime > PUSH_LOCK_STALE_S:
                    os.rmdir(PUSH_LOCK)
                    continue
            except OSError:
                pass
        except OSError:
            break
        if waited >= PUSH_LOCK_WAIT_S:
            break
        sleep(1)
        waited += 1
    try:
        yield
    finally:
        if mine:
            try:
                os.rmdir(PUSH_LOCK)
            except OSError:
                pass


_ADDRESS = re.compile(r'(?:[a-z][a-z0-9+.-]*://|git@)\S+|\b[\w.-]+\.(?:com|org|net|io|dev)\b\S*', re.I)


def _push_said(out) -> str:
    """What a refused push said: the last stderr lines of the default runner plus its stdout, as one text."""
    try:
        err = gate.last_stderr() if gate else ''
    except Exception:       # noqa: BLE001  a runner of another kind has no stderr to give
        err = ''
    return ((out.decode('utf-8', 'replace') if isinstance(out, (bytes, bytearray)) else str(out or '')) + '\n' + err).strip()


def _push_line(said: str) -> str:
    """The last non-empty line of ``said`` with no address and no secret, at most 160 characters."""
    from . import agent_factory as F
    lines = [ln.strip() for ln in said.splitlines() if ln.strip()]
    cause = [ln for ln in lines if not ln.startswith('hint:') and not ln.startswith('error: failed to push')]
    lines = cause or lines
    return F.redact(_ADDRESS.sub('<address>', lines[-1]))[:160] if lines else ''


def publish(tree, branch, files=None, shards=20, runner=None, clock=time.monotonic, sleep=time.sleep, start_s=START_S,
            durations=None, tests=None, trace=(), scan_only=None, on_branch=None, on_plan=None, hypo=None):
    """Push ``tree`` as ONE orphan commit to the NEW branch ``echo/<label>`` of the mirror and return the run id of the
    push-triggered workflow run. ``files``: glob patterns of the tests to run (default all tests/**/test_*.py); ``shards``:
    how many parallel jobs at most. ``tests``: an explicit list of pytest ids (a file or ``file::node``) that replaces ``files``
    (the candidate gate runs exactly the tests its local run would). ``trace``: source prefixes; the shards then also record which
    functions each test ran (the profile plugin) and upload it next to the JUnit (read_profiles). Raises Blocked (scan), CloudDead (no run appeared in START_S), RuntimeError (git/gh)."""
    if not branch.startswith(BRANCH_PREFIX) or not re.fullmatch(r'echo/[A-Za-z0-9._-]{1,80}', branch):
        raise ValueError('only new branches named echo/<label> are allowed, never main')
    tree = Path(tree)
    runner = _runner(runner)
    if scan_only is None:
        hits = scan_tree(tree)                          # the exact bytes that are about to leave
    else:                                               # the base was scanned once per SHA: only the files that differ from it
        hits = []
        for rel in sorted(set(scan_only)):
            if (tree / rel).is_file():
                hits += scan_bytes(rel, (tree / rel).read_bytes())
    if hits:
        raise Blocked(hits)
    tests = sorted(set(tests)) if tests else select_tests(tree, files)
    if not tests:
        raise ValueError('no test files selected')
    sizes = {}
    for t in tests:
        path = tree / t.split('::', 1)[0]
        sizes[t] = path.stat().st_size if path.is_file() else 1
    for t in tests:
        if t.startswith(('-', '/')) or '..' in t.split('::', 1)[0].split('/') or '\n' in t:
            raise ValueError('test id not allowed: ' + t[:80])
    parts = split_shards(tests, shards, durations, sizes)
    conftest = tree / 'tests' / 'conftest.py'
    predicted = predicted_shards(parts, durations)
    if on_plan:
        on_plan(parts, predicted)                       # the caller learns the split (and the expected time) before the push
    write_generated(tree, parts, requirements_for(conftest.read_text(encoding='utf-8') if conftest.is_file() else ''), trace,
                    job_min=shard_job_minutes(predicted), hypo=hypo)
    deadline = clock() + start_s
    work = Path(tempfile.mkdtemp(prefix='echo_cloud_'))

    def git(*args):
        code, out = runner(['git', *args], str(work))
        if code:
            raise RuntimeError('git ' + args[0] + ' failed')
        return out

    try:
        git('init', '-q')
        git('config', 'core.autocrlf', 'false')
        git('symbolic-ref', 'HEAD', 'refs/heads/' + branch)
        git('remote', 'add', 'origin', fm.DEFAULT_REMOTE)
        shutil.copytree(tree, work, dirs_exist_ok=True, ignore=shutil.ignore_patterns(fm.MARKER, '.git'))
        git('add', '-A')
        git('-c', 'user.name=' + fm.AUTHOR[0], '-c', 'user.email=' + fm.AUTHOR[1], 'commit', '-q',
            '--author=' + fm.AUTHOR[0] + ' <' + fm.AUTHOR[1] + '>', '-m', 'echo tests ' + branch[len(BRANCH_PREFIX):])
        sha = git('rev-parse', 'HEAD').decode().strip()
        def push(name):
            refused = tries = 0                     # live 21.11: big pushes that meet in time are refused now and then
            while True:
                if gate:
                    gate._STDERR.text = ''              # only this push's own stderr is read below
                with _push_turn(clock, sleep):          # 23.11: four cards pushed at once and were all refused: one at a time
                    code, out = runner(['git', 'push', '-q', 'origin', 'HEAD:refs/heads/' + name], str(work))   # new branch, never forced
                said = _push_said(out)
                if not code or _TAKEN.search(said):
                    return code, said
                if _REFUSED.search(said):
                    if refused >= PUSH_REFUSED_RETRIES:
                        return code, said
                    refused += 1
                    wait = random.uniform(*PUSH_JITTER_S)       # a spread, so the cards do not meet again
                else:
                    wait = PUSH_RETRY_S[tries] if tries < len(PUSH_RETRY_S) else None
                    tries += 1
                if wait is None or clock() + wait > deadline:
                    return code, said
                sleep(wait)

        code, said = push(branch)
        if not code and on_branch:
            on_branch(branch)                           # the branch that is ours (pushed by us): the only one to delete later
        for _ in range(2 if code and _TAKEN.search(said) else 0):   # the name is busy (23.11, two cards at once): a new one
            name = branch[:75] + '-' + os.urandom(2).hex()
            code, said = push(name)
            if not code:
                branch = name
                if on_branch:
                    on_branch(name)
                break
        if code:
            kind = PushRefused if _REFUSED.search(said) else RuntimeError
            raise kind('push to the mirror failed' + (': ' + _push_line(said) if _push_line(said) else
                                                                ' (credentials or a taken branch name)'))
    finally:
        fm._rmtree_force(work)
    while True:
        code, out = runner(['gh', 'run', 'list', '-R', _slug(), '--branch', branch, '--json', 'databaseId,headSha'], None)
        rows = _json(out) if not code else None
        for row in rows if isinstance(rows, list) else []:
            if isinstance(row, dict) and row.get('headSha') == sha and row.get('databaseId'):
                return int(row['databaseId'])
        if clock() + POLL_S > deadline:
            raise CloudDead('no workflow run appeared on %s within %d s' % (branch, start_s))
        sleep(5)


def shared_runs(runner=None, clock=time.time, slug=None):
    """``{str(run id): {'status', 'conclusion'}}`` of the mirror's last RUNS_LIST_LIMIT runs: ONE shared list for every
    process of the factory. The list is a file; the first process that sees it older than RUNS_TTL_S fetches it again
    (a lock made with mkdir, as the places are), the others read the file. None when nothing was ever read. ``slug``: another
    mirror of the account (its own cache and lock files); default is the main mirror."""
    runner = _runner(runner)
    slug = slug or _slug()
    RUNS_CACHE, RUNS_LOCK = globals()['RUNS_CACHE'], globals()['RUNS_LOCK']
    if slug != _slug():
        suffix = '.' + re.sub(r'[^A-Za-z0-9._-]', '_', slug)
        RUNS_CACHE, RUNS_LOCK = (p.with_name(p.name + suffix) for p in (RUNS_CACHE, RUNS_LOCK))
    try:
        cached = json.loads(RUNS_CACHE.read_text(encoding='utf-8'))
        rows, at = cached['rows'], float(cached['at'])
        if not isinstance(rows, dict):
            raise ValueError('rows')
    except (OSError, ValueError, KeyError, TypeError):
        rows, at = None, None
    if rows is not None and 0 <= clock() - at < RUNS_TTL_S:
        return rows
    try:
        os.mkdir(RUNS_LOCK)
    except FileExistsError:
        try:
            if time.time() - os.stat(RUNS_LOCK).st_mtime > 30:       # a fetch never lasts this long: its owner died
                os.rmdir(RUNS_LOCK)
        except OSError:
            pass
        return rows                                                  # somebody else is fetching: the last list will do
    except OSError:
        return rows
    try:
        code, out = runner(['gh', 'run', 'list', '-R', slug, '--limit', str(RUNS_LIST_LIMIT),
                            '--json', 'databaseId,status,conclusion'], None)
        listed = _json(out) if not code else None
        if not isinstance(listed, list):
            return rows
        fresh = {str(r['databaseId']): {'status': r.get('status'), 'conclusion': r.get('conclusion')}
                 for r in listed if isinstance(r, dict) and r.get('databaseId')}
        try:
            tmp = RUNS_CACHE.with_name(RUNS_CACHE.name + '.%d' % os.getpid())
            tmp.write_text(json.dumps({'at': clock(), 'rows': fresh}), encoding='utf-8')
            os.replace(tmp, RUNS_CACHE)
        except OSError:
            pass
        return fresh
    finally:
        try:
            os.rmdir(RUNS_LOCK)
        except OSError:
            pass


def _wait_completed(run_id, timeout_s, runner, clock, sleep, poll_s, start_s, shared=False):
    """The ``gh run view`` dict of a completed run (``shared``: its row of the shared list of the mirror's runs, with no
    ``gh run view`` at all). CloudDead when it never starts within ``start_s``, does not finish within ``timeout_s`` or cannot
    be read; a run in GitHub's queue is alive: it is waited for QUEUED_MAX_S, and past that CloudQueued (not dead)."""
    began_by, ends_by = clock() + start_s, clock() + timeout_s
    queued_by = clock() + max(QUEUED_MAX_S, start_s)
    began, failures, queued = False, 0, False
    while True:
        if shared:
            rows = shared_runs(runner, time.time if clock is time.monotonic else clock)
            info = None if rows is None else rows.get(str(run_id), {})
            code = 0 if info is not None else 1
        else:
            code, out = runner(['gh', 'run', 'view', str(run_id), '-R', _slug(), '--json', 'status,conclusion,jobs'], None)
            info = _json(out) if not code else None
        if not isinstance(info, dict):
            failures += 1
            if failures >= 6:
                raise CloudDead('gh cannot read the run')
        else:
            failures = 0
            jobs = info.get('jobs') or []
            queued = info.get('status') in QUEUED_STATES
            began = began or info.get('status') in ('in_progress', 'completed') or any(
                isinstance(j, dict) and j.get('status') in ('in_progress', 'completed') for j in jobs)
            if info.get('status') == 'completed':
                return info
        now = clock()
        if not began and queued and now > queued_by:
            raise CloudQueued('run %s stayed in the queue for %d s' % (run_id, QUEUED_MAX_S))
        if not began and not queued and now > began_by:
            raise CloudDead('run %s did not start within %d s' % (run_id, start_s))
        if now > ends_by:
            if queued and not began:
                raise CloudQueued('run %s was still queued after %d s' % (run_id, timeout_s))
            raise CloudDead('run %s did not finish within %d s' % (run_id, timeout_s))
        sleep(poll_s)


def wait_junit(run_id, timeout_s=3600, runner=None, clock=time.monotonic, sleep=time.sleep, poll_s=POLL_S,
               start_s=START_S, dest=None, shared=False):
    """``(xml_texts, conclusion)`` of a finished run: the raw JUnit of every shard that wrote one (the candidate gate judges
    them with its own JUnit code). CloudDead as wait_results, and when no shard left a JUnit file. ``shared``: the state of the
    run comes from the shared list (shared_runs); ``gh run download`` is called only after ``completed``."""
    runner = _runner(runner)
    info = _wait_completed(run_id, timeout_s, runner, clock, sleep, poll_s, start_s, shared)
    dest = Path(dest) if dest else Path(tempfile.mkdtemp(prefix='echo_junit_'))
    code, _ = runner(['gh', 'run', 'download', str(run_id), '-R', _slug(), '-p', 'junit-*', '-D', str(dest / 'junit')], None)
    texts = [p.read_text(encoding='utf-8', errors='replace') for p in sorted((dest / 'junit').rglob('*.xml'))] \
        if (dest / 'junit').exists() else []
    if code or not texts:
        raise CloudDead('run %s left no JUnit' % run_id)
    return texts, info.get('conclusion')


def read_profiles(dest):
    """The parsed profile of every shard of a run downloaded under ``dest`` (wait_junit): [{'tests': {nodeid: {outcome, calls}}}];
    a missing or unreadable file adds nothing (the path stays empty, the verdict is the JUnit's)."""
    out = []
    for path in sorted((Path(dest) / 'junit').rglob(PROFILE_RE)) if (Path(dest) / 'junit').exists() else []:
        data = _json(path.read_bytes())
        if isinstance(data, dict) and isinstance(data.get('tests'), dict):
            out.append(data)
    return out


def _add_failure_texts(results, run_id, runner, dest):
    """A merged artifact made by an older merge job has no failure texts: when it has red tests, the shard JUnit files are read for
    them (best effort: the results stand without)."""
    if not any(isinstance(r, dict) and r.get('failed_ids') and not r.get('failures') and not r.get('missing')
               for r in results.values()):
        return
    try:
        runner(['gh', 'run', 'download', str(run_id), '-R', _slug(), '-p', 'junit-*', '-D', str(Path(dest) / 'junit')], None)
        known = {f[:-3].replace('/', '.'): f for f in results if f.endswith('.py')}
        for path in sorted((Path(dest) / 'junit').rglob('*.xml')):
            for nodeid, body in parse_failures(path.read_text(encoding='utf-8', errors='replace'), known).items():
                row = results.get(nodeid.split('::', 1)[0])
                if isinstance(row, dict) and nodeid in (row.get('failed_ids') or ()):
                    row.setdefault('failures', {})[nodeid] = body
    except Exception:       # noqa: BLE001  the texts are an aid, never the verdict
        pass


def wait_results(run_id, timeout_s=3600, runner=None, clock=time.monotonic, sleep=time.sleep, poll_s=POLL_S,
                 start_s=START_S, dest=None):
    """The results dict ``{file: {...}}`` of a finished run. CloudDead when the run never starts within START_S, does not
    finish within ``timeout_s``, or leaves no results at all (the caller then falls back)."""
    runner = _runner(runner)
    _wait_completed(run_id, timeout_s, runner, clock, sleep, poll_s, start_s)
    dest = Path(dest) if dest else Path(tempfile.mkdtemp(prefix='echo_results_'))
    code, _ = runner(['gh', 'run', 'download', str(run_id), '-R', _slug(), '-n', ARTIFACT, '-D', str(dest / 'merged')], None)
    merged = dest / 'merged' / 'results.json'
    if not code and merged.is_file():
        parsed = _json(merged.read_bytes())
        if isinstance(parsed, dict):
            _add_failure_texts(parsed, run_id, runner, dest)
            return parsed
    code, _ = runner(['gh', 'run', 'download', str(run_id), '-R', _slug(), '-p', 'junit-*', '-D', str(dest / 'junit')], None)
    texts = [p.read_text(encoding='utf-8', errors='replace') for p in sorted((dest / 'junit').rglob('*.xml'))]
    if code or not texts:
        raise CloudDead('run %s left no results' % run_id)       # the merge job failed AND no shard wrote a JUnit file
    return merge_junit(texts, failures=True)


def delete_branch(branch, runner=None):
    """Remove the run's branch from the mirror (the run and its logs stay). False when gh refuses."""
    code, _ = _runner(runner)(['gh', 'api', '-X', 'DELETE', 'repos/%s/git/refs/heads/%s' % (_slug(), branch)], None)
    return not code


def _src_label(src):
    try:
        done = subprocess.run([*fm.GIT_PREFIX, 'rev-parse', '--short=8', 'HEAD'], cwd=src, capture_output=True,
                              env=fm._git_env(), timeout=20)
        text = done.stdout.decode().strip()
        if done.returncode == 0 and re.fullmatch(r'[0-9a-f]{7,12}', text):
            return text
    except (OSError, subprocess.SubprocessError):
        pass
    return 'tree'


def sweep(src=None, files=None, shards=20, label=None, work=None, keep_branch=False, wait_s=3600, runner=None,
          durations_path=None, places=True, sleep=time.sleep, clock=time.monotonic, on_run=None, resume=None):
    """build -> publish -> wait -> results.json. Returns ``(results_path, results, run_id)``; raises Blocked / CloudDead.
    ``wait_s=None``: the wait comes from the measured seconds of the longest shard (wait_for). ``on_run(info)`` is called as soon as
    the run exists (``run_id``, ``branch``, ``shards``, ``parts`` = files per shard, ``predicted``, ``files``, ``wait_s``, ``at``) and
    the branch of a run that did not end is then KEPT, so the caller can store the info and pick the run up later: ``resume=info``
    waits for that run and reads its artifacts, with no build, no push and no place taken (the run already holds its own).
    ``places`` (the guard sweep): at most GUARD_SHARDS shards, one shared place of the account per shard
    (factory_cloud_gate._take_run_slot), taken only when no card has waited for a place longer than a minute and freed after
    the run; CloudQueued when they do not come. ``places=False``: the caller counted the places itself."""
    src = src or DEFAULT_SRC
    label = re.sub(r'[^A-Za-z0-9._-]', '-', label or '%s-%s' % (_src_label(src), time.strftime('%Y%m%d-%H%M%S')))[:80]
    work = Path(work or Path(DEFAULT_WORK) / label)
    work.mkdir(parents=True, exist_ok=True)
    durations = {}
    if durations_path and Path(durations_path).is_file():
        loaded = _json(Path(durations_path).read_bytes())
        durations = loaded if isinstance(loaded, dict) else {}
    if resume:
        return _resume_run(work, resume, wait_s, runner, durations, durations_path, keep_branch)
    built = build(src, work / 'tree')
    if built['hits']:
        raise Blocked(built['hits'])
    slot = None
    if places:
        shards = max(1, min(int(shards), gate.GUARD_SHARDS, len(select_tests(work / 'tree', files)) or 1))
        slot = gate._take_run_slot(gate.SLOT_QUEUE_S, sleep=sleep, clock=clock, weight=shards, urgent=True,
                                   busy_fn=lambda: gate._account_busy(runner))
        if slot is None:
            raise CloudQueued('no %d free places for the guard sweep (cards are waiting for theirs)' % shards)
    try:
        return _sweep_run(work, label, files, shards, wait_s, runner, durations, durations_path, keep_branch, on_run)
    finally:
        gate._free_run_slot(slot)


def _sweep_run(work, label, files, shards, wait_s, runner, durations, durations_path, keep_branch, on_run=None):
    branch = BRANCH_PREFIX + label
    ours = []                                           # the branch name our push really made (a busy name is renamed)
    plan = {}

    def pushed(name):
        ours[:] = [name]

    def planned(parts, predicted):
        plan.update(parts=parts, predicted=predicted)
    started = time.monotonic()
    try:
        run_id = publish(work / 'tree', branch, files, shards, runner=runner, durations=durations, on_branch=pushed, on_plan=planned)
    except Exception:
        if ours and not keep_branch:
            try:
                delete_branch(ours[0], runner)
            except Exception:       # noqa: BLE001  a stale branch is harmless
                pass
        raise
    branch = ours[0] if ours else branch
    parts, predicted = plan.get('parts') or [], plan.get('predicted') or []
    wait_s = wait_for(predicted) if wait_s is None else wait_s
    shards = len(parts) or shards
    gate.register_run(run_id, shards)
    if on_run:
        on_run({'run_id': run_id, 'branch': branch, 'shards': shards, 'parts': parts, 'predicted': predicted,
                'files': sorted(f for p in parts for f in p), 'wait_s': wait_s, 'at': time.time()})
    return _wait_and_finish(work, run_id, branch, wait_s, runner, durations, durations_path, keep_branch, started, bool(on_run))


def _resume_run(work, resume, wait_s, runner, durations, durations_path, keep_branch):
    """The run of an earlier call (``resume`` = the ``on_run`` info): wait for it and read its artifacts; it is not published again."""
    run_id = int(resume['run_id'])
    left = max(float(resume.get('wait_s') or WAIT_UNKNOWN_S) - max(0.0, time.time() - float(resume.get('at') or time.time())),
               WAIT_MIN_S if wait_s is None else wait_s)
    gate.register_run(run_id, int(resume.get('shards') or 1))
    return _wait_and_finish(work, run_id, resume.get('branch'), left, runner, durations, durations_path, keep_branch,
                            time.monotonic(), True)


def _wait_and_finish(work, run_id, branch, wait_s, runner, durations, durations_path, keep_branch, started, keep_on_fail):
    done = False
    try:
        results = wait_results(run_id, wait_s, runner=runner, dest=work / 'dl')
        done = True
    finally:
        if branch and not keep_branch and (done or not keep_on_fail):     # a run that did not end keeps its branch: it can be picked up
            delete_branch(branch, runner)
    path = work / 'results.json'
    path.write_text(json.dumps(results, indent=1, sort_keys=True) + '\n', encoding='utf-8')
    (work / 'run.json').write_text(json.dumps({'run_id': run_id, 'branch': branch, 'seconds': round(time.monotonic() - started, 1),
                                               'slug': _slug()}, indent=1) + '\n', encoding='utf-8')
    if durations_path:
        Path(durations_path).write_text(json.dumps({**durations, **durations_of(results)}, indent=1, sort_keys=True) + '\n',
                                        encoding='utf-8')
    return str(path), results, run_id


# ------------------------------------------------------------------------------------------- W-hyp: batch of hypotheses
HYPO_DIR = 'hypo'
HYPO_TEST_TIMEOUT_S = 30
HYPO_FILE_TIMEOUT_S = 240       # one whole test file of a candidate (the 'no new red' run)


def hypo_batch(cands_path, ids_path, out_path, stub=None, timeout_s=HYPO_TEST_TIMEOUT_S, runner=None):
    """(cloud side) ``cands_path`` = json n -> {file: new text}; ``ids_path`` = the red ids, one per line. For every candidate:
    write its files, run each id with pytest (timeout ``timeout_s`` each), put the files back, next. ``out_path`` gets json
    n -> {passed, failed, text} (text = 400 chars of the first failure). ``runner(cmd, timeout)`` -> (rc, output) is replaceable."""
    def run(cmd, timeout):
        try:
            done = subprocess.run(cmd, capture_output=True, text=True, errors='replace', timeout=timeout)
            return done.returncode, (done.stdout or '') + (done.stderr or '')
        except subprocess.TimeoutExpired:
            return 124, 'timeout after %d s' % timeout
    runner = runner or run
    cands = json.loads(Path(cands_path).read_text(encoding='utf-8'))
    ids = [x.strip() for x in Path(ids_path).read_text(encoding='utf-8').splitlines() if x.strip()]
    out = {}
    for n, files in cands.items():
        saved = {}
        passed, failed, text = [], [], ''
        try:
            for rel, new in files.items():
                path = Path(rel)
                saved[rel] = path.read_bytes() if path.is_file() else None
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(new.encode('utf-8'))
            for tid in ids:
                if tid.startswith('@'):     # W-part 3/4: a whole file once: every test of it is passed / failed (the 'no new red' proof)
                    rc, said = runner([sys.executable, '-m', 'pytest', tid[1:], '-q', '-rA', '-p', 'no:cacheprovider', '--tb=short',
                                       '--timeout=%d' % timeout_s], HYPO_FILE_TIMEOUT_S)
                    for line in said.splitlines():
                        word, _, node = line.strip().partition(' ')
                        node = node.split(' - ', 1)[0].strip()
                        if '::' not in node:
                            continue
                        if word == 'PASSED' and node not in passed:
                            passed.append(node)
                        elif word in ('FAILED', 'ERROR'):
                            if node in passed:      # a fall in the whole-file run beats an earlier single pass
                                passed.remove(node)
                            if node not in failed:
                                failed.append(node)
                    continue
                rc, said = runner([sys.executable, '-m', 'pytest', tid, '-q', '-p', 'no:cacheprovider', '--tb=short',
                                   '--timeout=%d' % timeout_s], timeout_s + 10)
                if rc == 0:
                    if tid not in passed and tid not in failed:     # a fall (single or whole-file run) beats any pass
                        passed.append(tid)
                else:
                    if tid in passed:
                        passed.remove(tid)
                    if tid not in failed:
                        failed.append(tid)
                    if not text:
                        lines = [l for l in said.splitlines() if l.strip()]
                        text = '\n'.join(lines[-12:])[-400:]
        finally:
            for rel, old in saved.items():
                if old is None:
                    Path(rel).unlink(missing_ok=True)
                else:
                    Path(rel).write_bytes(old)
        out[n] = {'passed': passed, 'failed': failed, 'text': text}
    Path(out_path).write_text(json.dumps(out), encoding='utf-8')
    if stub:
        Path(stub).write_text('<?xml version="1.0" encoding="utf-8"?><testsuites/>', encoding='utf-8')
    return out


# ------------------------------------------------------------------------------------------------------------- CLI
def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('sweep', help='run the product tests in the cloud and print the results.json path')
    s.add_argument('--src', default=DEFAULT_SRC)
    s.add_argument('--files', nargs='*', default=None, help='glob patterns relative to the tree (default tests/**/test_*.py)')
    s.add_argument('--shards', type=int, default=20)
    s.add_argument('--label', default=None)
    s.add_argument('--work', default=None)
    s.add_argument('--keep-branch', action='store_true')
    s.add_argument('--wait-s', type=int, default=3600)
    s.add_argument('--durations', default=None, help='JSON {file: seconds}: balances the shards, updated after the run')
    c = sub.add_parser('scan', help='secrets scan of what would be published; prints file:line, never a value')
    c.add_argument('--src', default=DEFAULT_SRC)
    m = sub.add_parser('merge', help='(cloud) merge the shards JUnit into results.json')
    m.add_argument('junit_dir')
    m.add_argument('shards_dir')
    m.add_argument('out')
    h = sub.add_parser('hypo', help='(cloud) W-hyp: apply each candidate of hypo/cands.json, run the red ids, write the verdicts')
    h.add_argument('cands')
    h.add_argument('ids')
    h.add_argument('out')
    h.add_argument('--stub', default=None, help='an empty JUnit file the run leaves for wait_junit')
    args = p.parse_args(argv)
    if args.cmd == 'hypo':
        hypo_batch(args.cands, args.ids, args.out, stub=args.stub)
        return 0
    if args.cmd == 'merge':
        results = merge_dirs(args.junit_dir, args.shards_dir, args.out)
        print('merged %d files: %d green, %d red, %d tests passed, %d tests red' % ((len(results),) + summarize(results)))
        return 0
    try:
        if args.cmd == 'scan':
            hits = []
            for rel in list_source(args.src):
                hits += scan_bytes(rel, (Path(args.src) / rel).read_bytes())
            print(report(hits) if hits else 'scan: clean')
            return 2 if hits else 0
        path, results, run_id = sweep(args.src, args.files, args.shards, args.label, args.work, args.keep_branch, args.wait_s,
                                      durations_path=args.durations)
    except Blocked as error:
        print('echo_cloud: ' + str(error), file=sys.stderr)
        return 2
    except (CloudDead, CloudQueued) as error:
        print('echo_cloud: cloud route dead or busy: ' + str(error), file=sys.stderr)
        return 3
    except (OSError, RuntimeError, ValueError) as error:
        print('echo_cloud: ' + type(error).__name__ + ': ' + str(error), file=sys.stderr)
        return 1
    green, red, passed, bad = summarize(results)
    print('run %s: %d files green, %d files red, %d tests passed, %d tests red' % (run_id, green, red, passed, bad), file=sys.stderr)
    print(path)
    return 0


if __name__ == '__main__':
    sys.exit(main())
