"""w3-scenes: every step of scenarios_n1.json and scenarios_n2.json through the real ControlledMedia; the table for cloud_context/reports/w3-scenes.md.

    python tests/w3_scenes_report.py [--jobs 4] [--json out.json] [--ids n1_01_exam_accounting,...] [--show 3]
"""
import argparse
import collections
import json
import logging
import sys
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import w3_scenes_rig as R                                                              # noqa: E402


def one(index):
    logging.disable(logging.WARNING)
    name, scene = R.load()[index]
    try:
        rows = R.run_scene(name, scene)
    except Exception as error:                                                          # noqa: BLE001 - a crash of the rig is reported, never hidden
        return index, scene['id'], None, f'{type(error).__name__}: {error}'
    return index, scene['id'], [{'n': r.n, 'op': r.op, 'label': r.label, 'verdict': r.verdict, 'skipped': r.skipped, 'failures': r.product, 'ref': r.ref, 'cascade': r.cascade,
                                 'unchecked': r.unchecked, 'ref_notes': len(r.ref), 'log': r.log, 'material': r.material, 'checked': r.checked, 'cues': r.cues[:4], 'spoken': r.spoken[:160],
                                 'before': r.before and [r.before['revision'], r.before['index']], 'after': r.after and [r.after['revision'], r.after['index']]} for r in rows], None


CAUSES = {
    'P1': 'a number cut by a pause: the ear judges the second piece alone and takes the cloud\'s advance back (_ear_late_veto / _ear_other_number); patch w3-scenes.controlled_media.diff',
    'P2': 'a stammer on the only word / number of a portion is «unrelated_speech», never a try: the portion is abandoned (portion_abandoned tried=False) and the answer closed',
    'P3': 'a repeat with a new question in its tail: the whole utterance is compared with the portion; a number of the tail is «another number» (local_ear_number_veto), no model job',
    'P4': '«продолжайте» after a stop at the cursor restores the answer from its first portion (engine plan "restore": unfinished_answer_restored, index 0)',
    'P5': 'the timer repeats the waiting portion of the old answer in the pauses inside a question said in parts: old sound before the question is over, a second answer after it',
    'P6': 'a question with its conditions in three parts over 12 s: answer_timeout counts from the first part, the job of the last part is cancelled',
    'P7': 'a bare «продолжай» returns to a suspended answer other than the one the scene means (suspended_answer_resumed / suspended_plan_taken_back): the scene is ambiguous, the stand cannot name a plan',
    'P8': 'the first portions are cut at «:» «/» «=» and carry the lead-in, the key is in the third (the reference works first, the result last; first_cue never waits beyond 5 words)',
    'P9': 'a portion over the 9-word cap (a formula)',
    'P11': 'a word-for-word repeat of a portion with a formula / decimal («450 / 90», «200 x 0,15») is not accepted; with the sign said as a word («минус») one case is (c02 step 9), three still are not',
    'P12': 'a self-correction («тысяча шестьсот сорок три, нет, сорок два…») is a long speech: speech_too_long_for_an_attempt, the cursor stays',
    'P10': 'while others talk (no question), the controller resumes the suspended answer by itself (plan_goes_on_after_no_answer) and it sounds',
}


def cause_of(scene, row, previous):
    fails, label = {f[0] for f in row['failures']}, row['label']
    log = ' '.join(row['log'])
    if 'split_number' in label:
        return 'P1'
    if 'stammer' in label:
        return 'P2'
    if 'self_correct' in label:
        return 'P12'
    if label.startswith('repeat_current/full') and fails & {'ack', 'advance'} and 'then' not in label and not fails & {'audio'}:
        return 'P11'
    if 'resumes' in fails:
        return 'P4' if 'unfinished_answer_restored' in log else 'P7'
    if scene == 'n2_d10_finance_startup' and row['n'] == 2:
        return 'P6'
    if fails & {'cue_bound', 'answer_after_last_part'}:
        return 'P5'
    if label.startswith('repeat_current') and fails & {'audio'}:
        return 'P3'
    if 'plan_stays_in_the_history' in log:
        return 'P7'
    if fails == {'audio'} and 'plan_goes_on_after_no_answer' in log:
        return 'P10'
    if fails & {'says', 'says_cue', 'plan_covers', 'new_responses'}:
        return 'P8'
    if fails == {'short'}:
        return 'P9'
    return previous or 'P?'


def signature(check, message):
    import re
    text = re.sub(r"'[^']*'|\"[^\"]*\"|\[[^\]]*\]|\([^)]*\)", '…', message)
    return f'{check}: ' + re.sub(r'\d+(\.\d+)?', 'N', text)[:90]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--jobs', type=int, default=4)
    ap.add_argument('--json')
    ap.add_argument('--ids')
    ap.add_argument('--show', type=int, default=0)
    ap.add_argument('--csv', help='one line per step: scene, step, op, verdict, checks, cause')
    ap.add_argument('--known', help='write the table of known mismatches (scene -> step -> checks) for tests/test_w3_scenes.py')
    args = ap.parse_args(argv)
    wanted = set(args.ids.split(',')) if args.ids else None
    todo = [i for i, (_, scene) in enumerate(R.load()) if not wanted or scene['id'] in wanted]
    with Pool(args.jobs) as pool:
        results = sorted(pool.map(one, todo))
    if args.json:
        Path(args.json).write_text(json.dumps(results, ensure_ascii=False), encoding='utf-8')
    if args.known:
        known = {scene: {str(row['n']): sorted({f[0] for f in row['failures']}) for row in rows if row['verdict'] == 'product'} for _, scene, rows, crash in results if rows}
        Path(args.known).write_text(json.dumps({k: v for k, v in known.items() if v}, ensure_ascii=False, indent=1, sort_keys=True) + '\n', encoding='utf-8')
    if args.csv:
        import csv
        by_cause = collections.Counter()
        with open(args.csv, 'w', encoding='utf-8', newline='') as handle:
            writer = csv.writer(handle)
            writer.writerow(['scene', 'step', 'op', 'step_label', 'verdict', 'failed_checks', 'cause', 'first_sound', 'detail'])
            for _, scene, rows, crash in results:
                previous = None
                for row in rows or ():
                    cause = ''
                    if row['verdict'] in ('product', 'cascade'):
                        cause = cause_of(scene, row, previous) if row['verdict'] == 'product' else (previous or 'P?')
                        previous = cause
                        by_cause[cause] += 1
                    elif row['verdict'] in ('ref', 'unknown', 'na'):
                        cause = (row['ref'][0][0] if row['ref'] else row['skipped'] or ('material' if row['material'] else ''))[:60]
                    writer.writerow([scene, row['n'], row['op'], row['label'], row['verdict'], ' '.join(sorted({f[0] for f in row['failures']})), cause, (row['cues'][0][1] if row['cues'] else ''),
                                     (row['failures'][0][1] if row['failures'] else (row['ref'][0][1] if row['ref'] else ''))[:200]])
        print('causes (product + cascade):', dict(sorted(by_cause.items())))
    total, verdicts, checks, groups, crashes = 0, collections.Counter(), collections.Counter(), collections.defaultdict(list), []
    for _, scene, rows, crash in results:
        if crash:
            crashes.append((scene, crash))
            continue
        for row in rows:
            total += 1
            verdicts[row['verdict']] += 1
            checks.update(row['checked'])
            for check, message in row['failures']:
                if row['verdict'] == 'product':
                    groups[signature(check, message)].append((scene, row['n'], row['label'], message))
    print(f'steps {total}: {dict(verdicts)}; crashes {crashes}')
    for sig, items in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        print(f'{len(items):4d}  {sig}   e.g. {items[0][0]} step {items[0][1]} {items[0][2]}')
        for item in items[:args.show]:
            print('        ', item[0], item[1], item[2], '|', item[3][:200])
    return 1 if crashes else 0


if __name__ == '__main__':
    sys.exit(main())
