"""<id>, the register of failure classes: every failed attempt of the loop gets a class, classes are counted over the telemetry, a class that repeated and has no open self-fix becomes a self-fix question for the head."""

import re
from datetime import datetime

CLASSES = (
    ('search-miss', r'SEARCH not found|SEARCH is not in the file', 'the coder could not copy the code it had to edit', 'ERROR_PATTERNS repairs (a row of the outline kept in SEARCH and REPLACE stands for the real header), the exact missing line in the note, a wider view of the file'),
    ('no-edit-block', r'had no SEARCH/REPLACE edit block', 'the coder answered without an edit block', 'the format rules and an example in the retry note'),
    ('cannot', r'answered CANNOT', 'the coder asked for code it was not shown (CANNOT: name)', 'the code a model asks for is shown first and whole, to the next candidate of the pass too; the spec stage rewrites a task that is no code change'),
    ('test-hang', r'timeout after \d+ ?s|process tree killed', 'the written test hangs: it waits on a device, a network or a sleep', 'the example test of the same code shows its fakes and fixtures; never wait on real audio, network or time'),
    ('weak-test', r'stub|does not actually verify|MagicMock|не ловит дефект|green on the old code|already pass', 'the written test does not catch the defect', 'the second critic lens and the red-by-assert gate; the spec stage writes the test'),
    ('test-crash', r'crashes before its assertion|collection|does not compile|SyntaxError|ImportError|AttributeError', 'the test or the candidate breaks before any check', 'the test sees the reason and traceback in the note'),
    ('gate-red', r'AssertionError|rc=1', 'the candidate failed the test gate', 'the test failure diff and the candidate code'),
    ('review-reject', r'\breview: |rejected by the critic|critic rejected', 'the critic rejected the change', 'the critic remarks go to the next attempt and three different models try in one pass'),
    ('quota', r'rate_day', 'hit the API rate limit', 'retry later or switch the provider'),
    ('overload', r'transient|503', 'temporary overload or server error', 'automatic retry'),
)

INFRASTRUCTURE_CLASSES = {'quota', 'overload'}


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


def question(cls, info):
    remedy = ''
    for cid, _, _, rem in CLASSES:
        if cid == cls:
            remedy = rem
            break
    tasks = ', '.join(info.get('tasks', []))
    n = info.get('n', 0)
    examples = '\n'.join(f"- {e}" for e in info.get('examples', []))
    return f"Self-fix {cls}: failed {n} times (tasks: {tasks}). Examples:\n{examples}\nknown remedy: {remedy}"
