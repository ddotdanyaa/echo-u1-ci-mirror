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


