"""Mutation check of the T-B suite (tests/test_t_new_classes.py): breaks the product on purpose, one way at a time, and reports which tests notice.

V3 section 10: "Mutation-test deliberately breaks negation, speaker/subject, cursor +2, stale revision, ACK idempotency, source version,
compression of a protected condition, cancel after await and the semantic metrics. For each of them a correct test must FAIL."

How it works
  * ``MUTANTS`` below: every mutant is one or more exact text replacements in a production (or, for the metric mutants, a test-helper) file.
    A replacement whose old text is not found exactly once is reported as INVALID (the production code moved: update the mutant).
  * Each mutant is applied to a SCRATCH COPY of ``echo_sync/``, ``tests/`` and ``tools/`` (the working tree is never written to) and the
    selected tests are run in a separate pytest process, without ``-x``, so that every failing test is listed.
  * "Unmutated" runs first and must be green, or the table means nothing.
  * KILLED: at least one test failed. A strict-xfail that turned into XPASS is listed as ``flipped`` and is NOT a kill (the mutant
    made a known defect disappear; that says nothing about the tests catching a break).
  * SURVIVED: nothing failed. Either a test is missing (add it) or the mutant is equivalent: ``EQUIVALENT`` documents why. A survivor
    that is not documented makes the exit code 1.

usage:  python tools/mutate_check.py [--only NAME ...] [--family F] [--full] [--workers N] [--json OUT.json] [--md OUT.md] [--list]
  default: each mutant runs the tests of its own family (``select``); ``--full`` runs the whole module for every mutant.
The default python is the one running this script; the dependencies come from PYTHONPATH (the suite command of WAVE 2 sets it).
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = 'tests/test_t_new_classes.py'
CM = 'echo_sync/controlled_media.py'
NS = 'echo_sync/native_media_socket.py'
EN = 'echo_sync/engine.py'
RA = 'echo_sync/ru_alignment.py'
TU = 'echo_sync/textutil.py'
VT = 'echo_sync/voice_turns.py'
NP = 'echo_sync/native_prefetch.py'
HE = 'tests/helpers_t_new_classes.py'


def mutant(name, family, edits, why, select=None, expect=()):
    """``edits``: [(file, old, new), ...]; ``select``: a pytest -k expression naming the tests of the family; ``expect``: substrings, at
    least one of which should appear in the id of a killing test (a kill by an unrelated test is reported as ``collateral``)."""
    return {'name': name, 'family': family, 'edits': edits, 'why': why, 'select': select, 'expect': tuple(expect)}


MUTANTS = [
    # --- negation ------------------------------------------------------------------------------------------------------------
    mutant('neg-lost-in-alignment', 'negation',
           [(RA, "        else:\n            atoms.append(Atom(read.atom,' '.join(item.surface for item in items[index:read.end]),'n'));index=read.end\n",
             "        else:\n            atoms.append(Atom(read.atom,' '.join(item.surface for item in items[index:read.end]),'n'));index=read.end\n"
             "    atoms=[a for a in atoms if a.atom not in ('не','ни')]\n")],
           'the ACK matcher no longer sees «не»/«ни»: a repeat without the negation (or with an added one) equals the portion',
           'n03 or mm2 or mm1 or n05', ('n03', 'mm2')),
    mutant('neg-may-end-a-portion', 'negation',
           [(TU, "PARTICLES = _words('не ни бы ли же", "PARTICLES = _words('бы ли же")],
           'the portioner may cut right after «не»/«ни»: the negation is separated from the word it negates',
           'n01 or n04 or n14 or n20', ('n01', 'n04', 'n14')),
    mutant('neg-dropped-from-the-answer', 'negation',
           [(CM, "            withheld=text!=whole and not _ENDS_SENTENCE.search(whole)\n            text=definition_body(text,self._part())\n",
             "            withheld=text!=whole and not _ENDS_SENTENCE.search(whole)\n            text=re.sub(r'\\bне\\s+','',text)\n            text=definition_body(text,self._part())\n")],
           'the spoken answer loses every «не ...» (a compression of the text before it is portioned)',
           'n01 or n03 or n04 or n13 or n20 or n18', ('n01', 'n03', 'n04')),
    # --- speaker / subject ---------------------------------------------------------------------------------------------------
    mutant('subject-order-ignored', 'speaker-subject',
           [(RA, "    return tuple(atoms)\n\n\ndef _canonical", "    return tuple(sorted(atoms,key=lambda a:a.atom))\n\n\ndef _canonical")],
           'the matcher compares the words of a repeat as a set: who does what to whom no longer matters',
           'n05 or mm2 or n07', ('n05', 'mm2')),
    # --- cursor +2 ------------------------------------------------------------------------------------------------------------
    mutant('cursor-plus-two-on-ack', 'cursor+2',
           [(EN, "                    state['chunk_index'] += 1\n                    state['completed'] = state['chunk_index'] >= len(state['chunks'])\n",
             "                    state['chunk_index'] += 2\n                    state['completed'] = state['chunk_index'] >= len(state['chunks'])\n")],
           'a confirmation moves the cursor two portions: one portion is never spoken',
           'n01 or n03 or n04 or mm1 or n20', ('n01', 'n03', 'n04', 'mm1')),
    mutant('cursor-plus-two-at-the-frontier', 'cursor+2',
           [(EN, "            if state.get('stream_waiting_next') and added:\n                state['chunk_index'] += 1\n",
             "            if state.get('stream_waiting_next') and added:\n                state['chunk_index'] += 2\n")],
           'when the rest of a streamed answer arrives the cursor skips a portion',
           'n01 or n12', ('n01',)),
    # --- stale revision -------------------------------------------------------------------------------------------------------
    mutant('late-answer-overwrites-the-state', 'stale-revision',
           [(EN, "            if not latest or latest['revision'] != claimed_revision or latest.get('pending_turn') != turn_id:\n",
             "            if not latest:\n")],
           'the answer to an older question, finished after a newer question / «стоп», replaces the state',
           'n11', ('n11',)),
    mutant('epoch-not-bumped-by-a-new-question', 'stale-revision',
           [(CM, "        'open_question':('supersede',(('epoch','open_question'),('timers',),('cut',),('wire',)),False,True),\n",      # night-gate: the row of the gate (``_act``) moves the token now
             "        'open_question':('supersede',(('timers',),('cut',),('wire',)),False,True),\n")],
           'a new question does not change the epoch: every cue and lookup result of the old question stays authorised',
           'n06 or n11 or n18', ('n06', 'n11', 'n18')),
    mutant('cue-authorised-without-epoch', 'stale-revision',
           [(CM, "cue.get('nonce')==self.nonce and cue.get('epoch')==self.epoch and cue.get('revision')==state['revision']",
             "cue.get('nonce')==self.nonce and cue.get('revision')==state['revision']")],
           'a cue of an older epoch is still authorised when the synthesis finishes',
           'n11 or n18 or n06', ('n11', 'n18')),
    mutant('rewrite-of-a-published-prefix-accepted', 'stale-revision',
           [(EN, "            if not answer.startswith(previous):\n                return None\n", "            if False:\n                return None\n"),
            (CM, "        if self.published and (not prefix.startswith(self.published) or len(prefix)<len(self.published)):\n            self.blocked.add(tid);return []\n",
             ""),
            # INTEG7: since E3c a rewrite is taken by ``_rewritten`` (explicit correction / silent replacement) before the two checks above; the
            # mutant opens that layer too, so that the rewritten text reaches extend_answer as it did before E3c.
            (CM, "            same=self._same_words(text)\n            if same is None:return self._fast_closed() if tid==self.fast_turn and self.fast_done else self._rewritten(turn,text,settled)\n            text=same\n",
             "            same=self._same_words(text)\n            text=same if same is not None else text\n")],
           'a rewritten prefix is appended to the stream instead of being rejected',
           'n01 or n12 or n20', ('n01',)),
    # --- ACK idempotency ------------------------------------------------------------------------------------------------------
    mutant('engine-retry-not-recognised', 'ack-idempotency',
           [(EN, "            if cached:\n                if state is None", "            if False and cached:\n                if state is None")],
           'the engine answers the same turn id again as a new turn: a retried confirmation moves the cursor again',
           'n19 or mm1', ('n19',)),
    mutant('controller-seen-set-off', 'ack-idempotency',
           [(CM, "        if tid in self.seen and not tail:return self._early_tail(turn)\n",
             "        if False and tid in self.seen and not tail:return self._early_tail(turn)\n")],
           'the controller forgets which user turns it already acted on (one layer of three)',
           'n19', ()),
    mutant('ledger-duplicate-final-accepted', 'ack-idempotency',
           [(VT, "            if turn is not None and turn['final'] and text==turn['text'] and role==turn['role']:return None\n", "")],
           'the ledger lets an identical second final through (one layer of three)',
           'n19', ()),
    mutant('all-duplicate-guards-off', 'ack-idempotency',
           [(EN, "            if cached:\n                if state is None", "            if False and cached:\n                if state is None"),
            (CM, "        if tid in self.seen and not tail:return self._early_tail(turn)\n",
             "        if False and tid in self.seen and not tail:return self._early_tail(turn)\n"),
            (VT, "            if turn is not None and turn['final'] and text==turn['text'] and role==turn['role']:return None\n", "")],
           'a retransmitted final is acted on again by every layer: a double advance',
           'n19', ('n19',)),
    # --- source version -------------------------------------------------------------------------------------------------------
    mutant('stale-lookup-grounds-the-new-question', 'source-version',
           [(CM, "        if epoch!=self.epoch or not self.question_id or (self.direct_content and not self.lookup_served):return []\n",
             "        if not self.question_id or (self.direct_content and not self.lookup_served):return []\n")],
           'the result of a lookup for an older question is accepted as the sources of the current one',
           'n06', ('n06',)),
    mutant('answer-before-the-sources-is-spoken', 'source-version',
           [(CM, "            if not self.direct_content and not self.delivery_ready and tid!=self.fast_turn:return []", "            pass")],
           'text the cloud wrote before the sources reached it is dictated',
           'n06', ('n06',)),
    mutant('stale-delivery-accepted', 'source-version',
           [(CM, "        if epoch!=self.epoch or not self.context_requested:return False\n", "        if not self.context_requested:return False\n")],
           'the delivery report of an older question marks the sources of the current one as delivered',
           'n06', ('n06',)),
    # --- compression of a protected condition ---------------------------------------------------------------------------------
    mutant('restriction-clause-compressed', 'protected-condition',
           [(CM, "            text=definition_body(text,self._part())\n        if not self.published:\n",
             "            text=definition_body(text,self._part())\n            text=re.sub(r',\\s*(?:кроме|только если|если)[^.]*','',text)\n        if not self.published:\n")],
           'the clause that starts with «кроме» / «если» is cut from the answer before it is portioned',
           'n01 or n03 or n04 or n13 or n20', ('n01', 'n03')),
    mutant('history-keeps-the-first-sentence-only', 'protected-condition',
           [(EN, "                stored.append({'question':question, 'answer':answer, **provenance,\n",
             "                stored.append({'question':question, 'answer':answer.split('.')[0], **provenance,\n")],
           'the stored history is compressed to the first sentence: a negation or condition said later is gone',
           'n13', ('n13',)),
    mutant('history-extension-compressed', 'protected-condition',
           [(EN, "            history['answer'] = answer\n            if final:\n                history.pop('incomplete',None)\n",
             "            history['answer'] = answer.split(',')[0]\n            if final:\n                history.pop('incomplete',None)\n")],
           'a streamed answer\'s history entry is cut at the first comma when the rest arrives',
           'n13 or n01', ('n13',)),
    # --- cancel after await ---------------------------------------------------------------------------------------------------
    mutant('frames-sent-after-the-fence', 'cancel-after-await',
           [(NS, "                    if self.closed or generation!=self.audio_generation:return False\n"
                 "                    if not authorized():return await self._abandoned(opened)\n                    if offset==0:\n",
             "                    if self.closed:return False\n                    if offset==0:\n")],
           'the paced sender no longer checks the fence before each frame (the task cancel is still there)',
           'n11', ('n11',)),
    mutant('cancel-does-not-fence', 'cancel-after-await',
           [(NS, "                self.pending_cue=None\n                self._fast_retain()\n                self.audio_generation+=1\n                if self.audio and not self.audio.done():self.audio.cancel()\n",
             "                self.pending_cue=None\n                self._fast_retain()\n                if self.audio and not self.audio.done():self.audio.cancel()\n")],
           'a cancel cancels the task but does not move the fence',
           'n11', ('n11',)),
    mutant('cancel-fences-nothing', 'cancel-after-await',
           [(NS, "                self.pending_cue=None\n                self._fast_retain()\n                self.audio_generation+=1\n                if self.audio and not self.audio.done():self.audio.cancel()\n",
             "                self.pending_cue=None\n                self._fast_retain()\n")],
           'a cancel neither moves the fence nor cancels the sender: the response goes on after the clear (only the phone\'s clear is sent)',
           'n11', ('n11',)),
    mutant('cancel-does-not-clear-the-phone', 'cancel-after-await',
           [(NS, "                if self.audio and not self.audio.done():self.audio.cancel()\n                await self._send({'type':'output_audio_buffer.clear'})\n            elif typ=='unanswered':",
             "                if self.audio and not self.audio.done():self.audio.cancel()\n            elif typ=='unanswered':")],
           'the phone is never told to drop what it has buffered',
           'n11', ('n11',)),
    mutant('speech-start-cancels-nothing', 'cancel-after-await',
           [(CM, "        self.hearing=True      # the transport cuts a playing cue off\n        return self._act('cut_sound','speech_started')[1]\n",      # night-gate: the cut is the gate's
             "        self.hearing=True      # the transport cuts a playing cue off\n        self._act('cut_sound','speech_started')\n        return []\n")],
           'the listener\'s speech does not cut the cue that is playing',
           'n11 or n19 or n08', ('n11',)),
    # --- semantic metrics (the oracles of the suite itself) -------------------------------------------------------------------
    mutant('metric-drops-failures-from-the-denominator', 'semantic-metrics',
           [(HE, "    useful = [a.first_useful if a.outcome == 'useful' and a.first_useful is not None else INF for a in attempts]\n",
             "    useful = [a.first_useful for a in attempts if a.outcome == 'useful' and a.first_useful is not None]\n")],
           'the latency report forgets the attempts that failed: a pretty percentile on the survivors',
           'n16', ('n16',)),
    mutant('support-oracle-ignores-numbers', 'semantic-metrics',
           [(HE, "    found |= {('num', n.replace(',', '.')) for n in re.findall(r'\\d+(?:[.,]\\d+)?', flat)}\n", "")],
           'the independent source oracle does not look at numbers: a made-up value is "supported"',
           'n15', ('n15',)),
    mutant('judge-sensitivity-counts-the-accepted', 'semantic-metrics',
           [(HE, "    flagged = sum(1 for answer in planted if not judge(answer))\n", "    flagged = sum(1 for answer in planted if judge(answer))\n")],
           'a judge that accepts every planted error is called sensitive',
           'n17', ('n17',)),
    mutant('judge-overrides-the-gold', 'semantic-metrics',
           [(HE, "    gold = gold_verdict(spoken_text, fact)\n    return {'verdict': gold,", "    gold = 'PASS' if judge_ok else gold_verdict(spoken_text, fact)\n    return {'verdict': gold,")],
           'the judge\'s "ok" turns a gold FAIL into a pass (shared wrong premise wins)',
           'n17', ('n17',)),
    mutant('match-accepts-a-near-miss', 'semantic-metrics',
           [(RA, "        if _close(tuple(atom.atom for atom in variant),b,distance):return 'attempt'\n",
             "        if _close(tuple(atom.atom for atom in variant),b,distance):return 'ack'\n")],
           'a close-enough repeat (similarity instead of identity) is a confirmation',
           'n03 or mm2 or n05', ('n03', 'mm2', 'n05')),
    mutant('question-key-ignores-negation', 'semantic-metrics',
           [(NP, "        return ('ru',_canonical(text,()),tuple(lexical))\n",
             "        return ('ru',tuple(a for a in _canonical(text,()) if a not in ('не','ни')),tuple(w for w in lexical if w.casefold() not in ('не','ни')))\n")],
           'a prefetched lookup of «правда ли, что X» would serve «правда ли, что не X» (the key forgets the negation)',
           'mm3', ('mm3',)),
]

# Survivors that are not a gap of the tests: the mutant changes nothing the product can show. One line each, with the reason.
EQUIVALENT = {
    'cue-authorised-without-epoch': 'authorized() also compares the engine revision, the portion index and the call nonce, and every epoch change of the '
                                    'controller comes with an engine revision change (a new question, «стоп») or happens before any cue exists '
                                    '(the answer watchdog): the epoch term is a second fence nothing can get past the first one',
    'ledger-duplicate-final-accepted': 'a duplicate final that the ledger lets through is still stopped by the controller\'s seen set and by the engine\'s '
                                       'turn cache; the three layers are tested together (all-duplicate-guards-off) and the other two alone',
    'frames-sent-after-the-fence': 'every path that moves the fence also cancels the sender task (cancel, replace, diagnostic takeover, close), and the task '
                                   'cancel stops it at its next await: the per-frame check is a second fence (cancel-fences-nothing removes both)',
    'cancel-does-not-fence': 'the task cancel alone stops the sender at its next await; the fence is the second layer (cancel-fences-nothing removes both)',
}


# --------------------------------------------------------------------------------------------------------------------------------

def normalised(path):
    return path.read_bytes().replace(b'\r\n', b'\n').decode('utf-8')


def resolve_file(root, file, old):
    """The file that holds ``old`` exactly once. An edit aimed at the controller (``CM``) is looked for in ``controlled_media.py`` and in every
    ``echo_sync/cm_*.py``, so a mutant keeps its meaning when the controller is cut into modules. Returns ``(path, count)``."""
    names = [file]
    if file == CM:
        names += sorted(p.relative_to(root).as_posix() for p in (root / 'echo_sync').glob('cm_*.py'))
    found = [(name, normalised(root / name).count(old)) for name in names]
    hits = [(name, count) for name, count in found if count]
    if len(hits) == 1 and hits[0][1] == 1:
        return hits[0][0], 1
    return file, sum(count for _, count in found)


def validate(mut):
    """The line of the first pattern of the mutant in the working tree, or an error text."""
    first = None
    for file, old, _ in mut['edits']:
        file, count = resolve_file(ROOT, file, old)
        if count != 1:
            return None, f'pattern found {count} times in {file}: {old[:70]!r}'
        text = normalised(ROOT / file)
        first = first or (text[:text.index(old)].count('\n') + 1, file)
    return first, None


def scratch_copy(target):
    for part in ('echo_sync', 'tests', 'tools'):
        shutil.copytree(ROOT / part, target / part, ignore=shutil.ignore_patterns('__pycache__', '.hypothesis', '.pytest_cache'))


def pytest_env(deps):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8')
    if deps:
        env['PYTHONPATH'] = deps
    return env


def run_pytest(directory, python, env, k, timeout, extra=()):
    command = [python, '-m', 'pytest', '-q', '-p', 'no:cacheprovider', '-rfE', '--no-header', MODULE, *extra]
    if k:
        command += ['-k', k]
    started = time.time()
    try:
        result = subprocess.run(command, cwd=directory, env=env, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout)
        output, code = result.stdout + result.stderr, result.returncode
    except subprocess.TimeoutExpired as error:
        output, code = (error.stdout or '') if isinstance(error.stdout, str) else '', -9
    failed, flipped = [], []
    for line in re.findall(r'^(?:FAILED|ERROR) (\S+)(.*)$', output, flags=re.M):
        (flipped if 'XPASS(strict)' in line[1] else failed).append(line[0].split('::', 1)[-1])
    summary = (output.strip().splitlines() or [''])[-1]
    return {'failed': failed, 'flipped': flipped, 'summary': summary, 'seconds': round(time.time() - started, 1), 'code': code,
            'tail': output[-1500:] if code not in (0, 1) else ''}


def run_one(mut, args, env):
    where, error = validate(mut)
    if error:
        return {'status': 'INVALID', 'detail': error}
    with tempfile.TemporaryDirectory(prefix='mutate-') as folder:
        folder = Path(folder)
        scratch_copy(folder)
        for file, old, new in mut['edits']:
            target = folder / resolve_file(folder, file, old)[0]
            target.write_bytes(normalised(target).replace(old, new, 1).encode('utf-8'))
        result = run_pytest(folder, args.python, env, args.k if args.k else None if args.full else mut['select'], args.timeout)
    result.update(line=where[0], file=where[1])
    if result['code'] == -9:
        result['status'] = 'TIMEOUT'
    elif result['failed']:
        result['status'] = 'KILLED'
    elif result['code'] not in (0, 1) or 'error' in result['summary'].lower() and 'passed' not in result['summary']:
        result['status'] = 'INVALID'
        result['detail'] = result['tail']
    else:
        result['status'] = 'SURVIVED'
    expect = mut['expect']
    result['collateral'] = bool(result['failed']) and bool(expect) and not any(e in f for f in result['failed'] for e in expect)
    return result


def markdown(rows, baseline):
    out = ['| mutant | family | where | tests that failed | verdict |', '|---|---|---|---|---|']
    for mut, res in rows:
        status = res['status']
        if status == 'SURVIVED' and mut['name'] in EQUIVALENT:
            status = 'EQUIVALENT: ' + EQUIVALENT[mut['name']]
        failed = res.get('failed', [])
        names = sorted({f.split('[')[0].replace('test_', '', 1) for f in failed})
        shown = f'{len(failed)} ({", ".join(names[:3])}{", …" if len(names) > 3 else ""})' if failed else '0'
        if res.get('flipped'):
            shown += f'; {len(res["flipped"])} known defect(s) flipped to XPASS'
        if res.get('collateral'):
            status += ' (collateral only)'
        where = f'{res["file"]}:{res["line"]}' if 'line' in res else '-'
        out.append(f'| `{mut["name"]}` | {mut["family"]} | {where} | {shown} | {status} |')
    out.append('')
    out.append(f'Unmutated baseline: {baseline["summary"]}')
    return '\n'.join(out)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--only', nargs='*', default=[])
    parser.add_argument('--family')
    parser.add_argument('--full', action='store_true', help='run the whole module for every mutant (not only the tests of its family)')
    parser.add_argument('--workers', type=int, default=3)
    parser.add_argument('--timeout', type=int, default=900)
    parser.add_argument('--python', default=sys.executable)
    parser.add_argument('--deps', default=os.environ.get('PYTHONPATH', ''))
    parser.add_argument('--skip-baseline', action='store_true', help='(debugging) do not run the unmutated suite first')
    parser.add_argument('--k', help='override the -k expression of every mutant (debugging)')
    parser.add_argument('--json')
    parser.add_argument('--md')
    parser.add_argument('--list', action='store_true')
    args = parser.parse_args()
    chosen = [m for m in MUTANTS if (not args.only or m['name'] in args.only) and (not args.family or m['family'] == args.family)]
    if args.list:
        for mut in chosen:
            where, error = validate(mut)
            print(f'{mut["name"]:46s} {mut["family"]:22s} {where[1] + ":" + str(where[0]) if where else "INVALID " + error}')
        return 0
    env = pytest_env(args.deps)
    print(f'baseline: {MODULE} unmutated ...', flush=True)
    if args.skip_baseline:
        baseline = {'failed': [], 'flipped': [], 'code': 0, 'summary': 'skipped (debugging run)', 'seconds': 0}
    else:
        with tempfile.TemporaryDirectory(prefix='mutate-base-') as folder:
            scratch_copy(Path(folder))
            baseline = run_pytest(Path(folder), args.python, env, None, args.timeout)
    print(f'  {baseline["summary"]} ({baseline["seconds"]} s)', flush=True)
    if baseline['failed'] or baseline['flipped'] or baseline['code'] not in (0,):
        print('the unmutated suite is not green: nothing to compare', baseline['failed'][:5], baseline['flipped'][:5])
        return 2
    rows = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [(mut, pool.submit(run_one, mut, args, env)) for mut in chosen]
        for mut, future in futures:
            res = future.result()
            rows.append((mut, res))
            names = sorted({f.split('[')[0] for f in res.get('failed', [])})
            print(f'{res["status"]:9s} {mut["name"]:46s} failed={len(res.get("failed", []))} flipped={len(res.get("flipped", []))} {names[:2]} ({res.get("seconds", 0)} s)', flush=True)
    survivors = [m['name'] for m, r in rows if r['status'] == 'SURVIVED' and m['name'] not in EQUIVALENT]
    invalid = [m['name'] for m, r in rows if r['status'] in ('INVALID', 'TIMEOUT')]
    if args.json:
        Path(args.json).write_text(json.dumps({'baseline': baseline, 'mutants': [{'mutant': {k: v for k, v in m.items() if k != 'edits'}, 'result': r} for m, r in rows],
                                               'equivalent': EQUIVALENT}, ensure_ascii=False, indent=1), encoding='utf-8')
    table = markdown(rows, baseline)
    if args.md:
        Path(args.md).write_text(table, encoding='utf-8')
    print('\n' + table)
    print(f'\nkilled {sum(1 for _, r in rows if r["status"] == "KILLED")} / {len(rows)}; survivors without a documented equivalence: {survivors}; invalid: {invalid}')
    return 1 if survivors or invalid else 0


if __name__ == '__main__':
    raise SystemExit(main())
