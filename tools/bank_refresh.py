"""One command to refresh the question bank and the spoken-audio cache of its answers (w9-game, N196).

    python tools/bank_refresh.py [--qa materials/qa.json] [--audio materials/bank_audio] [--voice NAME] [--apply]

Reads qa.json (the file ``plugin.py`` re-reads on every turn), refuses a broken one before touching anything, and compares it with the
audio folder: one ``<sha256(voice, answer)[:32]>.wav`` per answer. Without ``--apply`` it only prints the plan. With it, it writes
``manifest.json`` (what each question should sound like) and deletes the audio of questions that left the bank. It does not synthesise:
the voice lives on the laptop (Windows SAPI) - the plan names the files to make (``new`` / ``changed``: the text to speak is in the bank,
the file name in the plan). A changed answer keeps its old audio until the new file exists. A different voice makes every file «changed».
Only files named like a hash are ever deleted; anything else in the folder is left alone."""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

_HASHED = re.compile(r'^[0-9a-f]{32}\.wav$')


def _sha(*parts):
    return hashlib.sha256('\0'.join(parts).encode('utf-8')).hexdigest()


def load_bank(path):
    try:
        bank = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError) as exc:
        raise ValueError(f'qa.json cannot be read: {type(exc).__name__}') from exc
    if not isinstance(bank, list) or any(not isinstance(i, dict) or not isinstance(i.get('question'), str) or not isinstance(i.get('answer'), str)
                                         or not i['question'].strip() or not i['answer'].strip() for i in bank):
        raise ValueError('qa.json must be a list of question/answer objects')
    return bank


def refresh(qa_path, audio_dir, *, voice='', apply=False):
    bank, audio = load_bank(qa_path), Path(audio_dir)
    try:
        manifest = json.loads((audio / 'manifest.json').read_text(encoding='utf-8')).get('items', {})
    except (OSError, ValueError, AttributeError):
        manifest = {}
    wanted, plan, seen = {}, {'new': [], 'changed': [], 'same': [], 'stale': [], 'duplicates': 0}, set()
    for item in bank:
        qid = _sha(' '.join(item['question'].split()).casefold())
        if qid in seen:
            plan['duplicates'] += 1
            continue
        seen.add(qid)
        wanted[qid] = _sha(voice, item['answer'].strip())[:32] + '.wav'
    keep_old = set()
    for qid, file in wanted.items():
        entry = {'id': qid[:12], 'file': file}
        if (audio / file).exists():
            plan['same'].append(entry)
            continue
        old = [f for f in (manifest.get(qid, {}).get('file'), manifest.get(qid, {}).get('old')) if f and f != file and (audio / f).exists()]
        if old:
            keep_old.add(old[0])
            plan['changed'].append({**entry, 'old': old[0]})
        else:
            plan['new'].append(entry)
    present = sorted(p.name for p in audio.iterdir() if _HASHED.match(p.name)) if audio.is_dir() else []
    plan['stale'] = [f for f in present if f not in wanted.values() and f not in keep_old]
    if apply:
        audio.mkdir(parents=True, exist_ok=True)
        old_of = {e['id']: e['old'] for e in plan['changed']}
        items = {qid: {'file': file, **({'old': old_of[qid[:12]]} if qid[:12] in old_of else {})} for qid, file in wanted.items()}
        (audio / 'manifest.json').write_text(json.dumps({'voice': voice, 'items': items}, ensure_ascii=False, indent=1), encoding='utf-8')
        for name in plan['stale']:
            (audio / name).unlink()
    return plan


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--qa', default='materials/qa.json')
    ap.add_argument('--audio', default='materials/bank_audio')
    ap.add_argument('--voice', default='')
    ap.add_argument('--apply', action='store_true')
    args = ap.parse_args(argv)
    try:
        plan = refresh(args.qa, args.audio, voice=args.voice, apply=args.apply)
    except ValueError as exc:
        print(f'refused: {exc}', file=sys.stderr)
        return 1
    print(('applied: ' if args.apply else 'plan (nothing written): ') + ', '.join(f'{k} {len(v) if isinstance(v, list) else v}' for k, v in plan.items()))
    return 0


if __name__ == '__main__':
    sys.exit(main())
