"""<id>, the register of failure classes: every failed attempt of the loop gets a class, classes are counted over the telemetry, a class that repeated and has no open self-fix becomes a self-fix question for the head."""

import json
import os
import re
from datetime import datetime
from pathlib import Path

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


def cases(rows, cls, exclude_task='', k=3, clean=None, files_of=None, mine=None):
    """The newest distinct 'reason: detail' examples of class ``cls`` from tasks other than ``exclude_task``; ``clean``
    (text -> text or None) screens each one, a refused example is skipped. With ``mine`` (the files of the asking task)
    and ``files_of`` (task id -> its files) only a case of a task touching one of those files counts: a failure of an
    unrelated task never goes into a prompt (live 21.11: <id> was shown <id>, <id> and <id>)."""
    res = []
    want = set(_names(mine)) if mine is not None else None
    for r in reversed(list(rows)):
        reason = r.get('reason')
        if not reason or r.get('task_id') == exclude_task:
            continue
        if want is not None and not want & set(_names(files_of(r.get('task_id')) if files_of else ())):
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
    """One line for the coder of a task refused with class ``cls``: the class, its known remedy, past cases
    (the same text as lesson(), without the registry's counters)."""
    return _compose(cls, examples)


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


# ---- the living registry (rule 3 of 21.11): hits, last cases, lesson counters of every class, built-in or paid ------
LESSON_MAX = 400      # one lesson, whatever the class: it is the only registry text a coder or a critic ever reads
LESSON_CASES = 2      # past cases in a lesson, of the same class and related files
CASES_KEPT = 5        # last cases the registry keeps per class
WEAK_AFTER = 5        # a lesson shown this often with no pass after it is a weak hypothesis and is not shown
_CASE_WIDTH = 95


def registry_dir():
    """Where classes.json lives: FACTORY_CLASSES_DIR, else the paid critic's state dir; None inside a test without
    either (a test never touches the live registry)."""
    d = os.environ.get('FACTORY_CLASSES_DIR') or os.environ.get('FACTORY_PAID_DIR')
    if d:
        return Path(d)
    if os.environ.get('PYTEST_CURRENT_TEST'):
        return None
    from tools import factory_paid_critic
    return factory_paid_critic.state_dir()


def _path(base):
    base = Path(base) if base else registry_dir()
    return base / 'classes.json' if base else None


def _load(base):
    path = _path(base)
    try:
        data = json.loads(path.read_text(encoding='utf-8')) if path else {}
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault('classes', {})
    data.setdefault('pending', {})
    return data


def _save(base, data):
    path = _path(base)
    if not path:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + '.tmp')
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
        os.replace(tmp, path)
    except OSError:
        pass


def _names(files):
    return [str(f).replace('\\', '/').rsplit('/', 1)[-1].lower() for f in (files or ()) if str(f).strip()]


def _builtin(cls):
    return next(((sym, rem) for cid, _, sym, rem in CLASSES if cid == cls), None)


def _blank(cls):
    b = _builtin(cls)
    return {'hits': 0, 'shown': 0, 'helped': 0, 'weak': False, 'last_cases': [], 'paid': b is None,
            'hypothesis': ('showing this lesson makes the next attempt pass: ' + b[0]) if b else '',
            'lock': b[1] if b else ''}


def _slot(data, cls):
    e = data['classes'].setdefault(cls, _blank(cls))
    for k, v in _blank(cls).items():
        e.setdefault(k, v)
    return e


def entry(cls, base=None):
    """The registry row of ``cls`` (a copy; zero counters when the class was never seen)."""
    return dict(_slot(_load(base), cls))


_TEST_ONLY = re.compile(r'(?:^|-)test-only|no-source-fix')


def is_test_only(cls) -> bool:
    """A class born of the paid critic's blindness to test cards (test-only-no-fix, no-source-fix-test-only, ...):
    a test card adds only a test by design and a code card follows it, so these never go into a prompt (W-critic 1)."""
    return bool(_TEST_ONLY.search(str(cls).lower()))


def match(reason, detail='', base=None):
    """The class of a failure, mechanically: the built-in regex table first, then the paid classes whose slug words
    all occur in the text; 'unknown' otherwise."""
    text = f"{reason} {detail}".lower()
    for cid, e in _load(base)['classes'].items():       # a paid class is the more specific: its slug words, all of them
        words = [w for w in re.split(r'[^a-z0-9]+', cid) if len(w) > 2]
        if e.get('paid') and len(words) >= 2 and all(w[:max(3, len(w) - 2)] in text for w in words):
            return cid
    return classify(reason, detail)


def _case(task_id, files, text, ts):
    text = _LOCAL_PATH.sub('<path>', str(text)).replace('\r', ' ').replace('\n', ' ')[:300]
    return {'task': task_id, 'files': _names(files)[:6], 'text': text, 'ts': ts or datetime.now().isoformat(timespec='seconds')}


def _add_case(e, case):
    e['hits'] += 1
    e['last_cases'] = (e['last_cases'] + [case])[-CASES_KEPT:]


def _settle(data, task_id, passed):
    """The lesson shown to ``task_id`` before this attempt did its work if the attempt passed."""
    cls = data['pending'].pop(task_id, None)
    if cls and passed:
        _slot(data, cls)['helped'] += 1


def record_failure(task_id, files, reason, detail='', *, ts='', base=None):
    """A failed attempt: count it in its class, keep it as a last case, and the pending lesson did not help."""
    if not reason or (base is None and registry_dir() is None):
        return 'unknown'
    data = _load(base)
    cls = match(reason, detail, base)
    _settle(data, task_id, False)
    if cls != 'unknown':
        _add_case(_slot(data, cls), _case(task_id, files, f"{reason}: {detail}".strip(': '), ts))
    _save(base, data)
    return cls


def record_pass(task_id, base=None):
    """A passed attempt: the lesson shown to the task before it, if any, helped."""
    if base is None and registry_dir() is None:
        return
    data = _load(base)
    if task_id in data['pending']:
        _settle(data, task_id, True)
        _save(base, data)


def record_paid(task_id, title, files, cls, symptom, *, ts='', base=None):
    """A catch of the paid critic that the free chain missed: the same registry, marked paid."""
    if not cls or (base is None and registry_dir() is None):
        return
    data = _load(base)
    e = _slot(data, cls)
    if _builtin(cls) is None:
        e['paid'] = True
        e['lock'] = e['lock'] or str(symptom)[:160]
        e['hypothesis'] = e['hypothesis'] or 'checking for this defect makes the free critic catch it: ' + str(symptom)[:160]
    c = _case(task_id, files, symptom, ts)
    c['title'] = str(title)[:80]
    _add_case(e, c)
    _save(base, data)


def _compose(cls, examples, limit=LESSON_MAX):
    b = _builtin(cls)
    cases = [str(x).replace('\n', ' ')[:_CASE_WIDTH] for x in examples][:LESSON_CASES]
    tail = ('; past cases: ' + ' | '.join(cases)) if cases else ''
    room = limit - len(tail)
    for head in ((f"[класс {cls}] {b[0]}; known remedy: {b[1]}", f"[класс {cls}] known remedy: {b[1]}") if b
                 else (f"[класс {cls}] known defect",)):
        if len(head) <= room:
            return head + tail
    return (head[:max(room, 60)] + tail)[:limit]


def lesson(cls, task_id, files, *, base=None, clean=None, examples=None):
    """The one short lesson of class ``cls`` for the next coder of ``task_id`` (touching ``files``): '' while the class
    is a weak hypothesis (shown WEAK_AFTER times and never followed by a pass). Past cases are the registry's, of the same
    class and files that overlap ``files`` (or the ``examples`` the caller already chose); the show is counted and left
    pending until the task's next outcome (record_failure / record_pass) says whether it helped."""
    data = _load(base)
    e = _slot(data, cls)
    if e.get('weak') or is_test_only(cls):
        return ''
    if examples is None:
        mine = set(_names(files))
        examples = []
        for c in reversed(e['last_cases']):
            if c['task'] == task_id or not mine & set(c.get('files') or ()):
                continue
            t = clean(c['text']) if clean else c['text']
            if t and t not in examples:
                examples.append(t)
            if len(examples) >= LESSON_CASES:
                break
    text = _compose(cls, examples)
    if base is not None or registry_dir() is not None:
        e['shown'] += 1
        if e['shown'] >= WEAK_AFTER and e['helped'] == 0:
            e['weak'] = True
        data['pending'][task_id] = cls
        _save(base, data)
    return text


def critic_lesson(task, failure='', *, base=None):
    """For the free critic: the lesson of the class matched to the earlier rejections (no cases) and the paid catches
    related by files, all in LESSON_MAX characters. '' when nothing matches."""
    if base is None and registry_dir() is None:
        return ''
    data = _load(base)
    parts = []
    cls = match('review: ' + str(failure), str(failure), base) if failure else 'unknown'
    if cls != 'unknown' and not is_test_only(cls) and not (data['classes'].get(cls) or {}).get('weak'):
        b = _builtin(cls)
        parts.append(f"{cls}: {b[0]}; look for it" if b else f"{cls}: {(data['classes'][cls].get('lock') or '')[:120]}")
    mine = set(_names(getattr(task, 'touch_files', ())))
    paid = []
    for cid, e in data['classes'].items():
        if e.get('paid') and cid != cls and not is_test_only(cid) and e.get('last_cases') and mine & {n for c in e['last_cases'] for n in c.get('files') or ()}:
            paid.append(f"{cid}: {(e['lock'] or '')[:100]}")
    parts += paid[:LESSON_CASES]
    if not parts:
        return ''
    head = 'Known defect classes to check:'
    out = head
    for p in parts:
        if len(out) + len(p) + 3 > LESSON_MAX:
            break
        out += '\n- ' + p
    return out if out != head else ''


def record_contract(bid, files, contract_json, *, base=None):
    """Keep an accepted contract for future architects; acceptance owns this call."""
    if base is None and registry_dir() is None:
        return
    data = _load(base)
    records = data.setdefault('contracts', [])
    record = {'bid': str(bid), 'files': _contract_files(files), 'contract': contract_json}
    records.append(record)
    _save(base, data)


def _contract_files(files):
    return sorted({str(f).replace(chr(92), '/').removeprefix('./') for f in files or () if str(f).strip()})


def contract_examples(files, k=2, *, base=None) -> list[str]:
    """Prefer the same full path, then a sibling file; retain the entire history."""
    if k <= 0:
        return []
    mine = set(_contract_files(files))
    directories = {str(Path(f).parent).replace(chr(92), '/') for f in mine}
    same, nearby = [], []
    for record in reversed(_load(base).get('contracts', [])):
        other = set(record['files'])
        if mine & other:
            same.append(record['contract'])
        elif directories & {str(Path(f).parent).replace(chr(92), '/') for f in other}:
            nearby.append(record['contract'])
    return (same + nearby)[:k]
