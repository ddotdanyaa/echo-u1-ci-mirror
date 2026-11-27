"""U25 runner: every harvested real call replayed through the real controller (the Rig of test_h3_tempo, the host's own ``controller_settings``) with a set of
NUMERIC settings (``ECHO_FLAGS`` = JSON, e.g. {"max_auto_repeats": 2}; behaviour on/off keys are gone, so a flag set is numbers). One file per journal
``{journal}.json`` = counters of the replay (``H.checks``: loops, stale, failures, stuck, back, cues, questions, ...) plus the sorted decision lines. Two folders are
compared by ``python -m tools.replay.flag_compare base other``. The folder is ``ECHO_FLAG_OUT``; without it the runner writes to a temp folder and checks the files:
it always runs, it never skips. With no harvested call on the machine one invented two-question call is replayed (the numbers of a real call need ``python -m tools.harvest``)."""
import json
import os
from pathlib import Path

from echo_sync.settings import DEFAULTS
from tools import harvest as H
from tools.replay import flag_compare

import test_h3_tempo                                           # noqa: F401
from test_h3_tempo import call, the_whole_call                 # noqa: F401 - call is the fixture
from test_harvest import harvested, replayed_checks

FLAGS = json.loads(os.environ.get('ECHO_FLAGS') or '{}')
OUT = os.environ.get('ECHO_FLAG_OUT')
ASKS = ('Почему небо голубое днём?', 'Сколько будет двадцать плюс двадцать два?')
ANSWERS = ('Воздух сильнее рассеивает синий свет, поэтому небо кажется голубым.', 'Сорок два.')


def invented_rows():
    rows = [{'t': 0, 'ev': 'call_open', 'source': 'phone', 'max_auto_repeats': 1, 'repeat_seconds': 6.0}]
    for n, (ask, answer, t0) in enumerate(zip(ASKS, ANSWERS, (2000, 20000)), 1):
        rows += [{'t': t0, 'ev': 'user_start', 'id': f'u{n}'}, {'t': t0 + 1500, 'ev': 'ear_final', 'uid': 'e', 'text': ask, 'kind': 'question', 'speech_ms': 1200, 'lag_ms': 100},
                 {'t': t0 + 1800, 'ev': 'user_final', 'id': f'u{n}', 'text': ask}, {'t': t0 + 3500, 'ev': 'assistant_start', 'id': f'a{n}'},
                 {'t': t0 + 3600, 'ev': 'assistant_final', 'id': f'a{n}', 'text': answer},
                 {'t': t0 + 4000, 'ev': 'decision', 'kind': 'question', 'reason': 'question_mark', 'revision': n, 'index': 0},
                 {'t': t0 + 4100, 'ev': 'cue', 'text': answer}, {'t': t0 + 6000, 'ev': 'cue_end', 'status': 'completed'}]
    return rows


def samples():
    found = [(path.stem, json.loads(path.read_text(encoding='utf-8'))) for path in harvested() if path]
    return found or [('invented', H.fixture(invented_rows()))]


def record(call, monkeypatch, name, fixture, flags, out):
    """One journal through the controller with ``flags``: ``{journal}.json`` in ``out`` (counters and the sorted decision lines)."""
    fast = {'fast_text': 'on'} if 'fast_text' in DEFAULTS else {}      # the text channel of the call, while its switch exists
    rig = call(**{**fast, 'max_auto_repeats': fixture.get('profile', {}).get('max_auto_repeats', 1), **flags})
    rows = []
    got = replayed_checks(rig, monkeypatch, fixture, rows=rows)
    decisions = sorted(f"{row.get('kind')}|{row.get('reason')}" for row in rows if row.get('ev') == 'decision')
    Path(out).mkdir(parents=True, exist_ok=True)
    (Path(out) / (name + '.json')).write_text(json.dumps(
        {'journal': name, 'flags': flags, 'checks': {k: v for k, v in got.items() if isinstance(v, (int, float))}, 'decisions': decisions}, ensure_ascii=False, indent=0), encoding='utf-8')
    return got


def test_replay_with_flags_records_numbers_per_journal(call, monkeypatch, tmp_path):
    out = Path(OUT) if OUT else tmp_path / 'out'
    for name, fixture in samples():
        record(call, monkeypatch, name, fixture, FLAGS, out)
    files = sorted(out.glob('*.json'))
    assert files, 'the replay wrote no file'
    for path in files:
        one = json.loads(path.read_text(encoding='utf-8'))
        assert one['flags'] == FLAGS and isinstance(one['checks'].get('cues'), int) and isinstance(one['decisions'], list), path.name


def test_the_same_numbers_replayed_twice_do_not_differ(call, monkeypatch, tmp_path):
    name, fixture = samples()[0]
    record(call, monkeypatch, name, fixture, {}, tmp_path / 'a')
    record(call, monkeypatch, name, fixture, {}, tmp_path / 'b')
    report = flag_compare.compare(tmp_path / 'a', tmp_path / 'b')
    assert report['journals'] == 1 and report['missing'] == [] and report['critical'] == [] and not report['blocking'] and report['decisions_changed'] == 0
