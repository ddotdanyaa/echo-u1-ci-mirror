"""P14: the numbers of a measurement and what they were counted against. Pure functions of call-journal rows (the rows ``tools.harvest.read_rows`` gives); no
echo_sync import, no network, no clock: a number here is a function of the journal, so it is the same on a laptop and in the cloud, and the laptop's own load never
enters it. Numbers and labels only: no word of a call leaves a function.

U167  ``latency_split``   each question of a call is exactly one of right / premature / stale / none, with its question number (``qid``) and the job that gave the cue.
U168  ``pin``/``one_pin`` the measurer, the BRAIN (the code that writes the answer) and the profile hashed under ONE git sha; rows pinned to different shas are MIXED.
U133  ``stage_table``     the stages of the latency per path (search / no search): n, min, median, p90, max; the sum of the stages against the whole (closure).
U132  ``target_report``   the target (0.3-0.6 s, at most 1 s with a search, from the END OF SPEECH) against the median and p90, with the passport of the numbers.
U106/U121 ``compare``     old build against new on the same scenes: median, p90, errors, tokens per useful answer; a change is called faster only when it is.
U137  ``open_set``        a set of open dialogues: at least 200 utterances from at least 5 sources, every source with a licence on the list.
U25   ``holdout_once``    the holdout is read once per checker hash; the second read is refused.
"""
import hashlib
import json
import subprocess
from pathlib import Path

from tools import harvest as H

ROOT = Path(__file__).resolve().parents[2]
VAD_PAUSE_MS = 300                     # the end-of-speech pause of the detector (local_ear OFFSET_MS): the real end of speech is the ear's final minus its lag minus this
TARGET_PLAIN_S = (0.3, 0.6)
TARGET_SEARCH_S = 1.0
CLOSURE = 0.10                         # the stages must add up to the whole within this share
MIN_CALLS = 20
OPEN_MIN_UTTERANCES, OPEN_MIN_SOURCES = 200, 5
LICENCES = frozenset(('CC0-1.0', 'CC-BY-4.0', 'CC-BY-SA-4.0', 'MIT', 'Apache-2.0', 'public-domain', 'OGL-UK-3.0'))
BRAIN_FILES = ('echo_sync/brain_rules.py', 'echo_sync/brain_short.py', 'echo_sync/generator.py', 'echo_sync/fast_text.py', 'echo_sync/content_policy.py')


# -- U167: right / premature / stale / none --------------------------------------------------------------------------------------------

def _job_of(rows, cue_ms, first_ms):
    """The job that gave the cue: the last adopted job between the question's first piece and the cue; else the last finished job that started on its text."""
    adopted = [row for row in rows if row['ev'] == 'fast_adopted' and first_ms - 1000 <= row['t'] <= cue_ms and isinstance(row.get('job'), int)]
    return adopted[-1]['job'] if adopted else None


def latency_split(rows):
    """One row per question of the call: ``{'qid', 'job', 'class', 'latency_s'}``. right: the first useful cue after the end of the question shares a content word with it;
    premature: a useful cue came before the question was over; stale: the cue after it answers an EARLIER question (it shares a word with that one and none with this);
    none: no cue, or one that fits nothing. The classes add up to the number of questions."""
    asks = H.latency_asks(rows)
    out = []
    for qid, ask in enumerate(asks, 1):
        cls, latency, cue_at = 'none', None, None
        if ask['early']:
            cls = 'premature'
        elif ask['cues']:
            want = H._content(ask['text'])
            for at, text in ask['cues']:
                if any(H._alike(word, other) for word in want for other in H._content(text)):
                    cls, latency, cue_at = 'right', round(at - ask['t0'], 3), at
                    break
            else:
                at, text = ask['cues'][0]
                if any(H._alike(word, other) for before in asks[:qid - 1] for word in H._content(before['text']) for other in H._content(text)):
                    cls, cue_at = 'stale', at
        job = _job_of(rows, round(cue_at * 1000), round(ask['first'] * 1000)) if cue_at is not None else None
        out.append({'qid': qid, 'job': job, 'class': cls, 'latency_s': latency})
    return out


def split_counts(split):
    got = dict.fromkeys(('right', 'premature', 'stale', 'none'), 0)
    for one in split:
        got[one['class']] += 1
    return {**got, 'N': len(split)}


# -- U168: one sha ---------------------------------------------------------------------------------------------------------------------

def _sha256(paths):
    digest = hashlib.sha256()
    for path in paths:
        digest.update(Path(path).name.encode())
        digest.update(Path(path).read_bytes())
    return digest.hexdigest()


def _git(*args, root=ROOT):
    done = subprocess.run(['git', *args], cwd=root, capture_output=True, text=True, encoding='utf-8', timeout=30)
    return done.stdout.strip() if done.returncode == 0 else None


def pin(measurer, profile=None, brain=BRAIN_FILES, root=ROOT):
    """What a result was measured with: the git sha of the tree, whether it is dirty, and the hashes of the measurer, of the BRAIN files and of the profile (a JSON-able dict)."""
    root = Path(root)
    return {'sha': _git('rev-parse', 'HEAD', root=root), 'dirty': bool(_git('status', '--porcelain', '--', 'echo_sync', 'tools', root=root)),
            'measurer': _sha256([Path(measurer)]), 'brain': _sha256([root / name for name in brain if (root / name).exists()]),
            'profile': hashlib.sha256(json.dumps(profile or {}, sort_keys=True).encode()).hexdigest()}


def one_pin(pins):
    """``{'status': 'ONE'|'MIXED'|'NONE', 'differs': [...]}`` over the pins of the rows of a table: ONE only when every pin is the same sha, not dirty, with the same three hashes."""
    pins = [one for one in pins if one]
    if not pins:
        return {'status': 'NONE', 'differs': ['no pin']}
    differs = [key for key in ('sha', 'measurer', 'brain', 'profile') if len({one.get(key) for one in pins}) > 1]
    differs += ['dirty'] if any(one.get('dirty') for one in pins) else []
    differs += ['sha unknown'] if any(not one.get('sha') for one in pins) else []
    return {'status': 'MIXED' if differs else 'ONE', 'differs': differs}


# -- U133 / U132: the stages and the target --------------------------------------------------------------------------------------------

def _q(xs, q):
    xs = sorted(xs)
    if not xs:
        return None
    k = (len(xs) - 1) * q
    lo = int(k)
    return round(xs[lo] + (xs[min(lo + 1, len(xs) - 1)] - xs[lo]) * (k - lo))


def episodes(rows):
    """The answered questions of a call as a chain of stages in ms from the END OF SPEECH (the ear's final minus its lag minus the detector's pause): ``{'path', 'stages', 'total'}``.
    Stages: pause (the detector's), ear (lag of the text), start (the final to the job's start), model (first text of the job), pick (first text to the decision), voice (decision to the
    first sound), plus ``search`` (lookup_start to lookup_end) on the search path. ``stages`` are measured fields only; ``total`` is the end of speech to the first sound."""
    out = []
    ears = [row for row in rows if row['ev'] == 'ear_final' and row.get('kind') == 'question' and isinstance(row.get('lag_ms'), (int, float))]
    for k, ear in enumerate(ears):
        stop = ears[k + 1]['t'] if k + 1 < len(ears) else float('inf')
        cue = next((row for row in rows if row['ev'] == 'cue' and ear['t'] <= row['t'] < stop), None)
        decision = next((row for row in rows if row['ev'] == 'decision' and row.get('kind') in ('answer', 'question') and ear['t'] <= row['t'] <= (cue['t'] if cue else stop)), None)
        job = next((row for row in rows if row['ev'] == 'fast_job' and isinstance(row.get('ttft_ms'), (int, float)) and isinstance(row.get('after_ear_ms'), (int, float))
                    and ear['t'] <= row['t'] <= (cue['t'] + 60000 if cue else stop)), None)
        if cue is None or decision is None:
            continue
        origin = ear['t'] - ear['lag_ms'] - VAD_PAUSE_MS
        stages = {'pause': VAD_PAUSE_MS, 'ear': round(ear['lag_ms'])}
        cursor = ear['t']
        if job is not None:
            began = ear['t'] - ear['lag_ms'] + job['after_ear_ms']
            stages['start'] = max(0, round(began - cursor))
            first = max(cursor, began + job['ttft_ms'])
            stages['model'] = round(first - cursor - stages['start'])
            cursor = first
        stages['pick'] = max(0, round(decision['t'] - cursor))
        cursor = max(cursor, decision['t'])
        stages['voice'] = max(0, round(cue['t'] - cursor))
        lo = next((row['t'] for row in rows if row['ev'] == 'stage' and row.get('name') == 'lookup_start' and ear['t'] <= row['t'] <= cue['t']), None)
        hi = next((row['t'] for row in rows if row['ev'] == 'stage' and row.get('name') == 'lookup_end' and ear['t'] <= row['t'] <= cue['t']), None)
        if lo is not None and hi is not None:
            stages['search'] = round(hi - lo)
        out.append({'path': 'search' if 'search' in stages else 'plain', 'stages': stages, 'total': round(cue['t'] - origin)})
    return out


def stage_table(journals):
    """``journals``: a list of row lists (one per call). Per path and per stage: n, min, median, p90, max in ms; the closure (the stages without ``search``, which lies inside
    the model's wait, against the whole) and the passport numbers n calls of N: ``meets_20`` only with MIN_CALLS calls that gave an episode."""
    eps = [(n, ep) for n, rows in enumerate(journals) for ep in episodes(rows)]
    table = {}
    for path in ('plain', 'search'):
        mine = [ep for _, ep in eps if ep['path'] == path]
        stats = {}
        for name in ('pause', 'ear', 'start', 'model', 'pick', 'voice', 'search'):
            xs = [ep['stages'][name] for ep in mine if name in ep['stages']]
            if xs:
                stats[name] = {'n': len(xs), 'min': min(xs), 'median': _q(xs, 0.5), 'p90': _q(xs, 0.9), 'max': max(xs)}
        sums = [(sum(v for k, v in ep['stages'].items() if k != 'search'), ep['total']) for ep in mine]
        table[path] = {'episodes': len(mine), 'stages': stats, 'total': {'median': _q([t for _, t in sums], 0.5), 'p90': _q([t for _, t in sums], 0.9)},
                       'closure_bad': sum(1 for s, t in sums if t and abs(s - t) / t > CLOSURE)}
    calls = len({n for n, _ in eps})
    return {'paths': table, 'passport': {'calls_with_episodes': calls, 'calls': len(journals), 'episodes': len(eps), 'meets_20': calls >= MIN_CALLS,
                                         'clock': 'journal ms of each call (server clock); no laptop or cloud wall clock is in a number',
                                         'target': {'plain_s': list(TARGET_PLAIN_S), 'search_s': TARGET_SEARCH_S, 'from': 'the end of the owner phrase to the first sound'}}}


def target_report(table):
    """U132: against the target, per path: the median and p90 in seconds from the end of speech, and the share of episodes inside the target. An empty path says so."""
    out = {}
    for path, limit in (('plain', TARGET_PLAIN_S[1]), ('search', TARGET_SEARCH_S)):
        row = table['paths'][path]
        median, p90 = row['total']['median'], row['total']['p90']
        out[path] = {'target_s': list(TARGET_PLAIN_S) if path == 'plain' else [None, TARGET_SEARCH_S], 'median_s': None if median is None else round(median / 1000, 3),
                     'p90_s': None if p90 is None else round(p90 / 1000, 3), 'episodes': row['episodes'],
                     'met': None if median is None else median / 1000 <= limit}
    return {'paths': out, 'passport': table['passport']}


# -- U106 / U121: old against new ------------------------------------------------------------------------------------------------------

def build_numbers(journals):
    """The numbers of one build over the same scenes: median and p90 of the end of speech to the first sound (ms), errors (error rows), useful answers (cues) and tokens per useful answer."""
    totals = [ep['total'] for rows in journals for ep in episodes(rows)]
    cues = sum(1 for rows in journals for row in rows if row['ev'] == 'cue' and str(row.get('text') or '') not in H.FAILURES)
    errors = sum(1 for rows in journals for row in rows if row['ev'] == 'error')
    tokens = sum(value for rows in journals for row in rows if row['ev'] == 'fast_job' for key, value in row.items()
                 if 'tokens' in key and isinstance(value, (int, float)) and not isinstance(value, bool))
    return {'n': len(totals), 'N': len(journals), 'median_ms': _q(totals, 0.5), 'p90_ms': _q(totals, 0.9), 'errors': errors, 'useful_answers': cues,
            'tokens_per_useful_answer': round(tokens / cues, 1) if cues else None}


def compare(old, new):
    """The table old / new and the verdict per metric. ``faster`` only when median AND p90 are lower and the errors did not rise; fewer episodes in the new build is no gain."""
    got = {'old': old, 'new': new, 'verdict': {}}
    for key in ('median_ms', 'p90_ms', 'errors', 'tokens_per_useful_answer'):
        a, b = old.get(key), new.get(key)
        got['verdict'][key] = 'unknown' if a is None or b is None else 'better' if b < a else 'worse' if b > a else 'same'
    comparable = old['n'] == new['n'] and old['N'] == new['N']
    got['same_scenes'] = comparable
    got['faster'] = comparable and got['verdict']['median_ms'] == 'better' and got['verdict']['p90_ms'] == 'better' and got['verdict']['errors'] in ('better', 'same')
    return got


# -- U137: open dialogues --------------------------------------------------------------------------------------------------------------

def open_set(manifest):
    """``manifest``: ``{'sources': [{'id', 'licence', 'utterances'}]}``. Checks the licences against LICENCES and the size; returns the findings (an empty list is a pass)."""
    sources = manifest.get('sources') or []
    findings = [f'{one.get("id")}: licence {one.get("licence")!r} is not on the list' for one in sources if one.get('licence') not in LICENCES]
    total = sum(int(one.get('utterances') or 0) for one in sources)
    if total < OPEN_MIN_UTTERANCES:
        findings.append(f'{total} utterances, {OPEN_MIN_UTTERANCES} needed')
    if len({one.get('id') for one in sources}) < OPEN_MIN_SOURCES:
        findings.append(f'{len({one.get("id") for one in sources})} sources, {OPEN_MIN_SOURCES} needed')
    return findings


# -- U25: the holdout is read once -----------------------------------------------------------------------------------------------------

def holdout_once(ledger, checker_sha256, ids):
    """Record that the holdout ``ids`` were read with this checker; a second read with the same checker raises. ``ledger`` is a JSON file of ``{checker: [ids]}``."""
    ledger = Path(ledger)
    seen = json.loads(ledger.read_text(encoding='utf-8')) if ledger.exists() else {}
    if checker_sha256 in seen:
        raise RuntimeError(f'the holdout was already read with checker {checker_sha256[:12]}: a second read is no blind measurement')
    seen[checker_sha256] = sorted(ids)
    ledger.write_text(json.dumps(seen, indent=1), encoding='utf-8')
    return seen


# -- the baseline of a set of journals, counts only -----------------------------------------------------------------------------------

def _numbers(value):
    """Only the numbers of a dict, nested: never a text."""
    if isinstance(value, dict):
        return {key: _numbers(item) for key, item in value.items() if isinstance(item, (dict, int, float)) and not isinstance(item, bool)}
    return value


def baseline(paths, profile_label=None):
    """U05/U06/U57/U167: for each call journal (``*.jsonl``, the tap files of ``.v5tap`` are not calls) the counters of ``tools.harvest`` (loops, stale, ...), its passport latency
    numbers, the split of its questions, the loss classes of ``classes`` and its place in the corpus (dev / holdout / rest). Counts only. ``passport``: the set (n of N), the profile
    label, the checker hashes, the load (none: a function of the text of the journals), the pin. A journal that is not a call is counted in ``skipped``."""
    from tools.harvest import classes as C
    calls, skipped, journals = [], 0, []
    for path in sorted(Path(p) for p in paths):
        if '.v5tap' in path.name or not path.name.endswith('.jsonl'):
            skipped += 1
            continue
        rows = H.read(path)
        if not any(row['ev'] == 'call_open' for row in rows):
            skipped += 1
            continue
        made = H.fixture(rows)
        meter = C.measure(list(rows))
        calls.append({'call': path.stem, 'corpus': 'dev' if path.stem in H.DEV else 'holdout' if path.stem in H.HOLDOUT else 'rest', 'minutes': made['passport']['minutes'],
                      'counters': {key: value for key, value in made['checks'].items() if isinstance(value, (int, float))},
                      'latency_proxy': _numbers(made['passport']['latency_proxy']), 'split': split_counts(latency_split(rows)),
                      'classes': {key: _numbers(value) for key, value in meter.items() if isinstance(value, dict)}})
        journals.append(rows)
    table = stage_table(journals)
    return {'passport': {'set': f'{len(calls)} call journals of the owner laptop (n={len(calls)} of N={len(calls) + skipped} files read; {skipped} not a call)',
                         'profile': profile_label or 'as recorded in each journal (profiles differ between calls)',
                         'checker': {'measure_sha256': pin(Path(__file__))['measurer'], 'harvest_sha256': hashlib.sha256(Path(H.__file__).read_bytes()).hexdigest()},
                         'load': 'none: a function of the journal text, the same on any machine; no latency of a machine is in a number',
                         'clock': 'journal ms of each call', 'privacy': 'counts only; no utterance text, no journal file is in the repo',
                         'pin': pin(Path(__file__)), 'target': table['passport']['target']},
            'corpus': {name: sum(1 for call in calls if call['corpus'] == name) for name in ('dev', 'holdout', 'rest')},
            'total': {key: sum(call['counters'].get(key, 0) for call in calls) for key in ('questions', 'cues', 'repeats', 'loops', 'stale', 'failures', 'silent', 'stuck', 'back', 'timeouts')},
            'split': {key: sum(call['split'][key] for call in calls) for key in ('right', 'premature', 'stale', 'none', 'N')},
            'stages': table, 'calls': calls}


# -- the command -----------------------------------------------------------------------------------------------------------------------

def main(argv=None):
    """``python -m tools.harvest.measure JOURNAL.jsonl ...``: one JSON on stdout: the stage table, the target report, the split of every call and the pin. Numbers and labels only;
    the passport names the journals by their count, never by text. Run it in the cloud for a number that is quoted (the laptop is only for a try)."""
    import sys
    paths = [Path(arg) for arg in (sys.argv[1:] if argv is None else argv) if not arg.startswith('--')]
    if not paths:
        print('no journal given', file=sys.stderr)
        return 1
    journals = [H.read(path) for path in paths]
    table = stage_table(journals)
    split = [split_counts(latency_split(rows)) for rows in journals]
    out = {'table': table, 'target': target_report(table), 'split_per_call': split, 'pin': pin(Path(__file__)), 'n_calls': len(journals)}
    if '--baseline' in (argv if argv is not None else sys.argv[1:]):
        out = baseline([path for path in paths if path.suffix == '.jsonl'])
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
