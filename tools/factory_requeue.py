"""<id>, the loop never stands while there are tasks: a FAILED or BLOCKED task whose last
failure has a class of the failure register goes back to the queue once per new factory
code version, through the answer box Opus uses; at most max_times per task; a ledger keeps the versions.

Written by the factory (fac_requeue, gemini-3.5-flash-lite, 19.11 23:5x); after 4 passes that left out the class
meaning in note(), the coordinator completed note() and the answer writer to the spec (rule: at most 4 rounds)."""

import json
import re
import time
from datetime import datetime
from pathlib import Path

from tools import agent_factory as F
from tools import factory_classes as C

# <id> (a "cannot be fixed" ban without an owner rule is a defect): only the owner's rules ban a
# requeue; scope_violation / already_green / spec_not_testable / runner_no_result blocks have a term instead and the
# loop lifts them itself (factory_loop._auto_unblock).
SKIP = re.compile('|'.join(sorted(F.OWNER_RULES)), re.I)
LAST_ITEMS = 2      # the newest non-Opus feedback items read for the failure class


def _last(row) -> str:
    """The newest failure: the last LAST_ITEMS feedback items that are not Opus notes (live 20.11 00:11: after a
    requeue the newest items are notes; a gate's 'do not repeat' signature alone names no class), plus the reasons."""
    items = [x for x in row.get('feedback') or [] if isinstance(x, dict) and x.get('source') != 'opus']
    texts = [str(x.get('text', '')) for x in items[-LAST_ITEMS:]]
    return ' '.join(texts + [str(row.get('blocked_reason') or ''), str(row.get('reason') or '')]).strip()


def _stamp(entry) -> float:
    """The time of a timed ledger entry ('hold:<iso>' of _auto_unblock, 'term:<iso>' of a term retry), else 0."""
    head, _, iso = str(entry).partition(':')
    if head not in ('hold', 'term') or not iso:
        return 0.0
    try:
        return datetime.fromisoformat(iso).timestamp()
    except ValueError:
        return 0.0


def last_try(ledger, tid) -> float:
    """When the task was last given back (0 = unknown: entries written before the times were kept)."""
    times = [_stamp(x) for x in ledger.get(tid) or []]
    at = ledger.get('at:' + tid)
    if isinstance(at, list) and at and isinstance(at[-1], (int, float)):
        times.append(float(at[-1]))
    return max(times, default=0.0)


def jam_of(state, runnable) -> bool:
    """21.11 rule 3 (a tactical brake lifts itself on a jam): nothing runnable now (``runnable``: the ids of
    agent_factory.ready) and nothing RUNNING or in REVIEW, so only a return of a FAILED task can move the loop."""
    return not runnable and not any(r.get('status') in ('RUNNING', 'REVIEW') for r in state.get('tasks', {}).values())


def _progress(state) -> int:
    """How many tasks are done: a jam round is given again only after this number grew (no progress -> no budget burnt)."""
    return sum(1 for r in state.get('tasks', {}).values() if r.get('status') in F.SATISFIED)


def _jam_round(state, tid, ledger) -> bool:
    """One more round beyond max_times / an unclassified failure per jam episode: the episode ends when a task got done
    since the last jam round of this task; at most F.AUTO_UNBLOCK_MAX jam rounds of one task, ever."""
    rounds = [x for x in ledger.get('jam:' + tid) or [] if isinstance(x, int)]
    return len(rounds) < F.AUTO_UNBLOCK_MAX and (not rounds or _progress(state) > rounds[-1])


def pick(state, code, ledger, max_times=3, skip=(), now=None, term_s=None, jam=False, blocking=(), lifted=None) -> list:
    """<id> (live 20.11: 7 FAILED tasks of a retryable class waited for a new factory version that never came): with
    ``now`` and ``term_s`` a task already tried on this very version is tried again once its last return is older
    than the term; max_times stays shared by every kind of return. ``jam`` (see jam_of): the max_times ceiling and the
    unclassified-failure skip give way, one round per jam episode (_jam_round), the task id goes to ``lifted``;
    ``blocking``: FAILED test tasks whose code tasks are READY and wait for them, tried first. The owner rules in SKIP
    and the infrastructure / no-requeue classes are never lifted."""
    result = []
    blocking = set(blocking)
    for tid in sorted(state.get('tasks', {})):
        row = state['tasks'][tid]
        if row.get('status') not in ('FAILED', 'BLOCKED'):
            continue
        if tid in skip:
            continue
        history = ledger.get(tid, [])
        if now is not None and term_s is not None:
            if now - last_try(ledger, tid) < term_s:     # any timed return (hold:, term:, at:) starts the term
                continue
        elif code in history:
            continue
        text = _last(row)
        if SKIP.search(text):
            continue
        cls = C.classify(text)
        if cls == 'unknown' and row.get('backlog_id'):
            # quarantined by the strikes of a sibling of the same backlog row (its test task) without a failure of
            # its own (live 20.11 00:27: 15 of 20 FAILED tasks): the sibling's failure is the class
            cls = _sibling(state, tid, row)[1]
        if cls == 'unknown':
            cls = _marker_class(row)
        lift = False
        if cls == 'unknown' and jam:
            cls, lift = 'gate-red', True     # a jam: a failure nobody classified is a red gate, tried once more
        if cls == 'unknown' or cls in C.INFRASTRUCTURE_CLASSES or cls in C.NO_REQUEUE_CLASSES:
            continue
        if cls == 'gate-cut' and row.get('kind') == 'unit_test':
            cls = 'test-hang'            # a test task's own new test is what does not finish
        if len(history) >= max_times and not _audit_due(state, tid, row, cls, ledger):
            if not jam:
                continue
            lift = True
        if lift:
            if not _jam_round(state, tid, ledger):
                continue
            if lifted is not None:
                lifted.add(tid)
        result.append((tid, cls))
    result.sort(key=lambda x: x[0] not in blocking)      # stable: the blocking test tasks first
    return result


def _marker_class(row) -> str:
    """The class of a window that holds only the loop's repeat markers. Before add_feedback kept the real failure,
    the marker evicted it (live 20.11: three FAILED code tasks were never returned); a marker is written only for a
    repeated gate, weakening or review rejection, so it names the class itself."""
    own = [str(x.get('text', '')) for x in row.get('feedback') or [] if isinstance(x, dict) and x.get('source') != 'opus']
    if not own or not all(t.startswith(F.REPEAT_MARK) for t in own):
        return 'unknown'
    return 'review-reject' if any('review' in t for t in own) else 'gate-red'


def _audit_due(state, tid, row, cls, ledger) -> bool:
    """A promoted factory test of a code task that kept failing its gate is checked once even after max_times
    returns: pick() used to drop the task first, so the audit could fire only at exactly AUDIT_AFTER returns."""
    if cls != 'gate-red' or row.get('kind') not in (None, 'code'):
        return False
    test = _promoted_test(state, tid, row)
    return bool(test) and ('audit:' + test) not in ledger and len(ledger.get(tid, [])) >= AUDIT_AFTER


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


# A suspected test (20.11 02:55: of five promoted factory tests whose fixes kept failing, three could never be made
# green by a correct fix; each cost its code task three strikes per version). After AUDIT_AFTER requeues of a code
# task that still fails its gate, the factory-written test of its row goes back to its test task instead.
AUDIT_AFTER = 2
AUDIT_NOTE = ('Retry on factory version %s. The code task of this row failed its gate on this test after %d returns. '
              'Check that the test calls the real function with the kind of arguments its signature takes, does not '
              'replace the function the behaviour happens in, and pins a behaviour the row really asks for; else '
              'rewrite it, or answer not testable when the row is no code defect.')


AUDIT_MODELS = 2      # this many different models red on one factory test in ONE pass of its code task: audit at once
AUDIT_PASS_NOTE = ('Retry on factory version %s. In one pass of the code task of this row, %d different models wrote '
                   'fixes and each failed its gate on this test. Check that the test calls the real function with the '
                   'kind of arguments its signature takes, does not replace the function the behaviour happens in, '
                   'and pins a behaviour the row really asks for; else rewrite it, or answer not testable when the '
                   'row is no code defect.')
WAIT_NOTE = 'Wait for the rewritten test of this row: two models failed on the old one in one pass.'


def _module_of(path: str) -> str:
    """'tests/test_a.py' -> 'tests.test_a', the JUnit classname prefix of its test ids."""
    return path[:-3].replace('/', '.') if path.endswith('.py') else path.replace('/', '.')


def audit_after_pass(state_dir, state, tid, report, code, tests_of, check=None):
    """<id> (skeptic verdict test-red-review 20.11: 7 of 7 code tasks red on a promoted factory test had an unfit test,
    the 2 with a fit test passed on their first pass): a code task's pass that ends red on its gate, where AUDIT_MODELS
    or more different models were red on the same test id of the promoted unit_test task of its row, sends that test
    back to its test task at once (the AUDIT answer of run(), once per test: ledger 'audit:<test>') and makes the
    code task wait for it. ``tests_of(task id)`` gives a task's test files. Returns the test task id or None."""
    row = (state.get('tasks') or {}).get(tid) or {}
    if row.get('kind') not in (None, 'code') or not str(report.get('reason') or '').startswith('gate:'):
        return None
    test = _promoted_test(state, tid, row)
    if not test:
        return None
    modules = tuple(_module_of(p) for p in tests_of(test) or ())
    models_of = {}
    for model, ids in report.get('gate_red') or ():
        for i in ids or ():
            if any(i.split('::', 1)[0] == m or i.startswith(m + '.') for m in modules):
                models_of.setdefault(i, set()).add(model)
    shared = max((len(m) for m in models_of.values()), default=0)
    if shared < AUDIT_MODELS:
        return None
    state_dir = Path(state_dir)
    path = state_dir / 'requeue_ledger.json'
    ledger = json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}
    if ('audit:' + test) in ledger:
        return None
    text = AUDIT_PASS_NOTE % (code, shared)
    if check is not None:
        try:
            check(text)
        except Exception:
            return None
    _write_answer(state_dir / 'answers', {'task_id': test, 'reject': True, 'note': text}, test)
    _write_answer(state_dir / 'answers', {'task_id': tid, 'depends_on': [test], 'note': WAIT_NOTE}, tid)
    ledger['audit:' + test] = [code]
    F.save_atomic(path, ledger)
    return test


def _promoted_test(state, tid, row):
    """The PROMOTED unit_test task of the same backlog row: the factory wrote the test the code task fails on."""
    for other, orow in sorted(state['tasks'].items()):
        if (other != tid and orow.get('backlog_id') and orow.get('backlog_id') == row.get('backlog_id')
                and orow.get('kind') == 'unit_test' and orow.get('status') == 'PROMOTED'):
            return other
    return None


def run(state_dir, code, *, skip=(), check=None, max_times=3, now=None, term_s=None, jam=False, blocking=()) -> list:
    """Write the retry answers. ``now``/``term_s``/``jam``/``blocking``: see pick(); a return on the same version is
    booked as 'term:<time>', every return stamps 'at:<task>' so the next term starts from it, a jam round beyond the
    ceiling is booked as 'jam:<task>' (the done count then)."""
    state_dir = Path(state_dir)
    state = json.loads((state_dir / 'state.json').read_text(encoding='utf-8'))
    path = state_dir / 'requeue_ledger.json'
    ledger = json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}
    written = []
    at = time.time() if now is None else float(now)

    def book(tid):
        history = ledger.setdefault(tid, [])
        history.append(('term:' + datetime.fromtimestamp(at).astimezone().isoformat(timespec='seconds'))
                       if code in history else code)
        ledger['at:' + tid] = [at]
        if tid in lifted:
            ledger.setdefault('jam:' + tid, []).append(_progress(state))

    lifted = set()
    for tid, cls in pick(state, code, ledger, max_times=max_times, skip=skip, now=now, term_s=term_s,
                         jam=jam, blocking=blocking, lifted=lifted):
        row = state['tasks'][tid]
        test = (_promoted_test(state, tid, row) if cls == 'gate-red' and row.get('kind') in (None, 'code') else None)
        if test and len(ledger.get(tid, [])) >= AUDIT_AFTER and ('audit:' + test) not in ledger:
            text = AUDIT_NOTE % (code, len(ledger[tid]))
            if check is not None:
                try:
                    check(text)
                except Exception:
                    continue
            _write_answer(state_dir / 'answers', {'task_id': test, 'reject': True, 'note': text}, test)
            ledger['audit:' + test] = [code]
            book(tid)                                    # the code task waits for the rewritten test (depends_on)
            written.append(test)
            continue
        own = C.classify(_last(row)) != 'unknown'
        text = note(cls, code, sibling=None if own else _sibling(state, tid, row)[0])
        if check is not None:
            try:
                check(text)
            except Exception:
                continue
        _write_answer(state_dir / 'answers', {'task_id': tid, 'note': text}, tid)
        book(tid)
        written.append(tid)
    if written:
        path.write_text(json.dumps(ledger, indent=1), encoding='utf-8')
    return written
