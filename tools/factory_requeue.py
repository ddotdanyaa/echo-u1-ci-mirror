"""<id>, the loop never stands while there are tasks: a FAILED or BLOCKED task whose last
failure has a class of the failure register goes back to the queue once per new factory
code version, through the answer box Opus uses; at most max_times per task; a ledger keeps the versions.

Written by the factory (fac_requeue, gemini-3.5-flash-lite, 19.11 23:5x); after 4 passes that left out the class
meaning in note(), the coordinator completed note() and the answer writer to the spec (rule: at most 4 rounds)."""

import json
import re
import time
from pathlib import Path

from tools import factory_classes as C

SKIP = re.compile(r'scope_violation|already_green|only_opus|private|runner_no_result|spec_not_testable', re.I)
LAST_ITEMS = 2      # the newest non-Opus feedback items read for the failure class


def _last(row) -> str:
    """The newest failure: the last LAST_ITEMS feedback items that are not Opus notes (live 20.11 00:11: after a
    requeue the newest items are notes; a gate's 'do not repeat' signature alone names no class), plus the reasons."""
    items = [x for x in row.get('feedback') or [] if isinstance(x, dict) and x.get('source') != 'opus']
    texts = [str(x.get('text', '')) for x in items[-LAST_ITEMS:]]
    return ' '.join(texts + [str(row.get('blocked_reason') or ''), str(row.get('reason') or '')]).strip()


def pick(state, code, ledger, max_times=3, skip=()) -> list:
    result = []
    for tid in sorted(state.get('tasks', {})):
        row = state['tasks'][tid]
        if row.get('status') not in ('FAILED', 'BLOCKED'):
            continue
        if tid in skip:
            continue
        history = ledger.get(tid, [])
        if code in history:
            continue
        if len(history) >= max_times:
            continue
        text = _last(row)
        if SKIP.search(text):
            continue
        cls = C.classify(text)
        if cls == 'unknown' and row.get('backlog_id'):
            # quarantined by the strikes of a sibling of the same backlog row (its test task) without a failure of
            # its own (live 20.11 00:27: 15 of 20 FAILED tasks): the sibling's failure is the class
            cls = _sibling(state, tid, row)[1]
        if cls == 'unknown' or cls in C.INFRASTRUCTURE_CLASSES:
            continue
        result.append((tid, cls))
    return result


def _sibling(state, tid, row):
    """(id, class) of the first other task of the same backlog row whose failure has a class, else (None, 'unknown')."""
    for other, orow in sorted(state['tasks'].items()):
        if other != tid and orow.get('backlog_id') == row.get('backlog_id'):
            cls = C.classify(_last(orow))
            if cls != 'unknown':
                return other, cls
    return None, 'unknown'


def note(cls, code, sibling=None) -> str:
    """The retry note: the version, what the last failure was and what the factory has against it now. It goes to an
    external model unchanged, so no brackets and no quotes (the public check refuses quotes). A class taken from a
    sibling names the sibling: live 20.11 00:53 the coder of <id> was told its own test was weak, while it was the
    test task of the same row that had failed so."""
    meaning, remedy = next(((m, r) for cid, _, m, r in C.CLASSES if cid == cls), ('', ''))
    if sibling:
        text = ('Retry on factory version %s. This task was held back because %s of the same backlog row failed as '
                '%s: %s. Since then the factory has: %s.' % (code, sibling, cls, meaning, remedy))
    else:
        text = ('Retry on factory version %s. Your last attempt failed as %s: %s. Since then the factory has: %s. '
                'Use it now.' % (code, cls, meaning, remedy))
    return ''.join(ch for ch in text if ch not in '()"«»')


def _write_answer(box, payload, label) -> Path:
    """One answer file like the answer command writes it: time first in the name, exclusive create."""
    box = Path(box)
    box.mkdir(parents=True, exist_ok=True)
    name = '%d-%s' % (time.time_ns(), re.sub(r'[^A-Za-z0-9_-]', '_', label))
    target = box / (name + '.json')
    n = 0
    while True:
        try:
            with open(target, 'x', encoding='utf-8') as fh:
                fh.write(json.dumps(payload, ensure_ascii=False, indent=2))
            return target
        except FileExistsError:
            n += 1
            target = box / ('%s-%d.json' % (name, n))


def run(state_dir, code, *, skip=(), check=None, max_times=3) -> list:
    state_dir = Path(state_dir)
    state = json.loads((state_dir / 'state.json').read_text(encoding='utf-8'))
    path = state_dir / 'requeue_ledger.json'
    ledger = json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}
    written = []
    for tid, cls in pick(state, code, ledger, max_times=max_times, skip=skip):
        row = state['tasks'][tid]
        own = C.classify(_last(row)) != 'unknown'
        text = note(cls, code, sibling=None if own else _sibling(state, tid, row)[0])
        if check is not None:
            try:
                check(text)
            except Exception:
                continue
        _write_answer(state_dir / 'answers', {'task_id': tid, 'note': text}, tid)
        ledger.setdefault(tid, []).append(code)
        written.append(tid)
    if written:
        path.write_text(json.dumps(ledger, indent=1), encoding='utf-8')
    return written
