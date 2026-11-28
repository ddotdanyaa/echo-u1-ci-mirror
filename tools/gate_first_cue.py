"""c22-merge: the gate of the first cue. Runs the five test files of the first portion and counts the broken first cues of a bank.

    python tools/gate_first_cue.py [BANK.json ...] [--no-tests] [--show N] [--max-broken K]

A bank file is a JSON list of {'q', 'answer'} (cloud_context/bank/merged/*.json, instant_bank_*.json); rows without an answer are skipped.
Every answer is fed whole (final) and word by word (the stream, as tests/test_first_cue_meaning.py does), the meaning profile of a call.
A first cue is broken when it:
  open       ends on a dash, a preposition or a conjunction (the thought is left open: «Штраф двадцать процентов по статье 123 —»);
  torn       is not a prefix of the answer, or ends inside a word of it;
  long       is longer than 12 words (the widest first window: a question for a number or a date);
  silent     the whole answer is known and no cue comes.
Exit code: 0 when the tests pass and the count is at most --max-broken (default 0), else 1. The expectations are written here, not read
from echo_sync."""
import argparse
import glob
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = ['tests/test_r21_first_portion.py', 'tests/test_first_cue_meaning.py', 'tests/test_c7_number_first_cue.py',
         'tests/test_f1_meaning_portions.py', 'tests/test_task_c_first_cue.py']
DASHES = '—–-'
PREP = frozenset(('в во на с со к ко по о об обо от ото из изо за для до при про над под подо перед передо пред между через сквозь без безо у '
                  'ради около возле вокруг среди после кроме вместо против напротив посреди внутри вне вдоль мимо благодаря согласно '
                  'относительно помимо спустя ввиду насчет из-за из-под').split())
# «да», «так», «также», «пока», «где» … are no open end: they close a thought as often as they open one («Да,», «Это не так,»)
CONJ = frozenset(('и а но или либо ни что чтобы чтоб как когда если хотя потому поскольку зато однако причем притом будто '
                  'словно чем нежели едва пусть пускай ибо').split())
WORD = re.compile(r"[^\W_]+(?:[-’'][^\W_]+)*", re.U)
LONG = 12


def open_end(cue):
    """'dash', 'preposition', 'conjunction' or '' - what leaves the thought open at the end of ``cue``. A cue that ends its sentence
    («В момент операции или сразу после.», «Через функции И и ИЛИ.») is a closed thought whatever its last word is."""
    if str(cue or '').rstrip()[-1:] in '.!?…':
        return ''
    body = str(cue or '').rstrip().rstrip('.!?…,;:').rstrip()
    if body[-1:] in DASHES:
        return 'dash'
    words = WORD.findall(body)
    last = words[-1].casefold().replace('ё', 'е') if words else ''
    return 'preposition' if last in PREP else 'conjunction' if last in CONJ else ''


def verdict(answer, cue):
    if not cue:
        return 'silent'
    if not answer.startswith(cue) or answer[len(cue):len(cue) + 1].isalnum():
        return 'torn'
    kind = open_end(cue)
    if kind:
        return 'open:' + kind
    if len(WORD.findall(cue)) > LONG:
        return 'long'
    return ''


def cues(question, answer):
    sys.path.insert(0, ROOT)
    from echo_sync.first_useful import first_cue
    from echo_sync.settings import CALL_SETTINGS as S
    whole = first_cue(answer, question, S, final=True, last=True)
    parts, stream = answer.split(' '), None
    for k in range(1, len(parts) + 1):
        stream = first_cue(' '.join(parts[:k]) + (' ' if k < len(parts) else ''), question, S, final=k == len(parts), last=k == len(parts))
        if stream:
            break
    return {'whole': whole, 'stream': stream}


def sweep(paths):
    rows, broken = 0, []
    for path in paths:
        for row in json.load(open(path, encoding='utf-8')):
            question, answer = row.get('q'), row.get('answer')
            if not question or not isinstance(answer, str) or not answer.strip():
                continue
            rows += 1
            for mode, cue in cues(question, answer).items():
                why = verdict(answer, cue)
                if why:
                    broken.append((os.path.basename(path), row.get('id', ''), mode, why, question, cue))
    return rows, broken


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('banks', nargs='*', default=sorted(glob.glob(os.path.join(ROOT, 'cloud_context', 'bank', 'merged', '*.json'))))
    parser.add_argument('--no-tests', action='store_true')
    parser.add_argument('--show', type=int, default=20)
    parser.add_argument('--max-broken', type=int, default=0)
    args = parser.parse_args()
    ok = True
    if not args.no_tests:
        cmd = [sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider', *TESTS]
        try:
            import xdist  # noqa: F401
            cmd[4:4] = ['-n', 'auto']
        except ImportError:
            pass
        print('$', ' '.join(cmd), flush=True)
        ok = subprocess.call(cmd, cwd=ROOT) == 0
    rows, broken = sweep(args.banks)
    kinds = {}
    for item in broken:
        kinds[item[3]] = kinds.get(item[3], 0) + 1
    print(f'bank: {len(args.banks)} file(s), {rows} answers, {2 * rows} cues (whole + stream)')
    print(f'broken first cues: {len(broken)}' + (' (' + ', '.join(f'{k} {v}' for k, v in sorted(kinds.items())) + ')' if kinds else ''))
    for name, rid, mode, why, question, cue in broken[:args.show]:
        print(f'  {name} {rid} {mode:6} {why:18} {question!r} -> {cue!r}')
    ok = ok and len(broken) <= args.max_broken
    print('GATE', 'PASS' if ok else 'FAIL')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
