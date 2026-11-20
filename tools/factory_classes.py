"""<id>, the register of failure classes: every failed attempt of the loop gets a class, classes are counted over the telemetry, a class that repeated and has no open self-fix becomes a self-fix question for the head."""

import re
from datetime import datetime

CLASSES = (
    # first: a leak or a waste is named by its own word whatever gate, critic or block reported it
    ('secret-leak', r'private material|\bcontains (a secret|a phone number)|\bleak(s|ed|ing|age)?\b[^|]{0,60}\b(secret|key|token|password|private|e-?mail|phone)|\b(secret|key|token|password)s?\b[^|]{0,40}\bleak(s|ed|ing|age)?\b', 'a secret or private material reached a candidate, a note or an output', 'the public screen and redact() on every text that leaves the factory; the candidate never prints keys or personal data'),
    ('token-waste', r'context_too_large|steps_exhausted|max_tokens', 'tokens were spent without a result: the prompt was too large or the model ran out of steps', 'a narrower context (outline, the named functions only) and a short answer format with the edit block first'),
    ('search-miss', r'SEARCH not found|SEARCH is not in the file', 'the coder could not copy the code it had to edit', 'ERROR_PATTERNS repairs (a row of the outline kept in SEARCH and REPLACE stands for the real header), the exact missing line in the note, a wider view of the file'),
    ('no-edit-block', r'had no SEARCH/REPLACE edit block', 'the coder answered without an edit block', 'the format rules and an example in the retry note'),
    ('cannot', r'answered CANNOT', 'the coder asked for code it was not shown (CANNOT: name)', 'the code a model asks for is shown first and whole, to the next candidate of the pass too; the spec stage rewrites a task that is no code change'),
    ('gate-cut', r'[\w./\\-]+\.py(?:::\S+)?(?: \(\+\d+ more\))?: timeout after \d+ ?s', 'a test of the task does not finish within the 30 s limit here, slow or hanging', 'the gate goes on by single tests within the limit; a test that hangs alone or lacks a package on the base too is not measured, the rest decides'),
    ('test-hang', r'timeout after \d+ ?s|process tree killed','the written test hangs: it waits on a device, a network or a sleep', 'the example test of the same code shows its fakes and fixtures; never wait on real audio, network or time'),
    ('weak-test', r'stub|does not actually verify|MagicMock|не ловит дефект|green on the old code|already pass', 'the written test does not catch the defect', 'the second critic lens and the red-by-assert gate; the spec stage writes the test'),
    ('test-crash', r'crashes before its assertion|collection|does not compile|SyntaxError|ImportError|AttributeError', 'the test or the candidate breaks before any check', 'the test sees the reason and traceback in the note'),
    ('gate-red', r'AssertionError|rc=1', 'the candidate failed the test gate', 'the test failure diff and the candidate code'),
    ('review-reject', r'\breview: |rejected by the critic|critic rejected', 'the critic rejected the change', 'the critic remarks go to the next attempt and three different models try in one pass'),
    ('quota', r'rate_day', 'hit the API rate limit', 'retry later or switch the provider'),
    ('overload', r'transient|503', 'temporary overload or server error', 'automatic retry'),
)

INFRASTRUCTURE_CLASSES = {'quota', 'overload'}
# registered and counted, but a FAILED/BLOCKED task of these classes is not requeued as is: the same input would spend
# the same tokens again or carry the same leak (factory_requeue)
NO_REQUEUE_CLASSES = {'token-waste', 'secret-leak'}


def classify(reason, detail=''):
    if not reason:
        return 'unknown'
    text = f"{reason} | {detail}"
    for class_id, pattern, _, _ in CLASSES:
        if re.search(pattern, text, re.I):
            return class_id
    return 'unknown'


def count(rows, since):
    res = {}
    for r in rows:
        ts = r.get('ts')
        if ts and since and ts < since:
            continue
        reason = r.get('reason')
        detail = r.get('reason_detail', '')
        if not reason:
            continue
        cls = classify(reason, detail)
        if cls == 'unknown':
            continue
        task_id = r.get('task_id', '')
        ex = f"{reason}: {detail}".strip(': ')
        if cls not in res:
            res[cls] = {'n': 0, 'tasks': [], 'examples': []}
        res[cls]['n'] += 1
        if task_id and task_id not in res[cls]['tasks']:
            res[cls]['tasks'].append(task_id)
        if ex and ex not in res[cls]['examples']:
            res[cls]['examples'].append(ex)
    return res


def due(counts, open_classes, threshold=2):
    res = []
    for cls, info in counts.items():
        if cls in INFRASTRUCTURE_CLASSES:
            continue
        if cls in open_classes:
            continue
        if info.get('n', 0) >= threshold:
            res.append(cls)
    return res


def remedy_of(cls):
    return next((rem for cid, _, _, rem in CLASSES if cid == cls), '')


def cases(rows, cls, exclude_task='', k=3, clean=None):
    """The newest distinct 'reason: detail' examples of class ``cls`` from tasks other than ``exclude_task``; ``clean``
    (text -> text or None) screens each one, a refused example is skipped."""
    res = []
    for r in reversed(list(rows)):
        reason = r.get('reason')
        if not reason or r.get('task_id') == exclude_task:
            continue
        detail = r.get('reason_detail') or ''
        if classify(reason, detail) != cls:
            continue
        ex = f"{reason}: {detail}".strip(': ')
        ex = clean(ex) if clean else ex
        if ex and ex not in res:
            res.append(ex)
            if len(res) >= k:
                break
    return res


def note(cls, examples):
    """One line for the coder of a task refused with class ``cls``: the class, its known remedy, past cases."""
    return f"[класс {cls}] known remedy: {remedy_of(cls)}; past cases: " + ' | '.join(e.replace('\n', ' ') for e in examples)


# a local path (drive or UNC) up to the next blank, quote or separator: it names the machine, never the defect
_LOCAL_PATH = re.compile(r'(?:\b[A-Za-z]:[\\/]|\\\\)[^\s\'"|,;()<>]*')


def question(cls, info, k=6, clean=None, width=300, max_tasks=12):
    """The head's question for class ``cls``: the newest ``k`` distinct examples (count() keeps them newest last),
    local paths hidden, each screened by ``clean`` (text -> text or None, a refused one is dropped) and cut to
    ``width``. Live 20.11: all 96 gate-red examples went in, 30.7 KB with local stage paths."""
    remedy = remedy_of(cls)
    names = list(info.get('tasks', []))
    tasks = ', '.join(names[-max_tasks:]) + (f" (+{len(names) - max_tasks} more)" if len(names) > max_tasks else '')
    n = info.get('n', 0)
    picked = []
    for e in reversed(list(info.get('examples', []))):
        e = _LOCAL_PATH.sub('<path>', str(e)).replace('\r', ' ').replace('\n', ' ')
        e = clean(e) if clean else e
        if not e:
            continue
        e = str(e)[:width]
        if e not in picked:
            picked.append(e)
            if len(picked) >= k:
                break
    examples = '\n'.join(f"- {e}" for e in reversed(picked))
    return f"Self-fix {cls}: failed {n} times (tasks: {tasks}). Examples:\n{examples}\nknown remedy: {remedy}"
