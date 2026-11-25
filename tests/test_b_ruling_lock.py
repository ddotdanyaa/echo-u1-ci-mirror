"""Lane B (one owner of the kind of an utterance and of the answer): the locks are on QUANTITIES, by the AST, the code is not started.

* the engine decides no kind: ``engine.py`` has no ``analyze`` at all and ``EchoEngine`` no ``going_on(``; it carries out the verdict it is given (``reply(decided=...)``);
* every ``_reply`` of the controller carries its verdict (``decided=``), and there are exactly as many as there were (16): a new place is a new owner;
* ``_answer`` is written by ONE function (``_bind_answer``), nowhere else, and cleared where a question ends (``QuestionSlot.CLOSED``);
* the places that set a kind (``analyze(``, ``_analyze(``, ``Decision(``, ``._replace(kind=``) do not grow: 82 on c1d2434 (engine 5, judge 0, controller 77).

``python tests/test_b_ruling_lock.py`` prints the numbers (the meter of the lane)."""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))

import cm_patch                                         # noqa: E402
from test_night_gate_lock import table_of               # noqa: E402

EN = ROOT / 'echo_sync' / 'engine.py'
UJ = ROOT / 'echo_sync' / 'utterance_judge.py'
BASE_PLACES = 82          # c1d2434: engine 5, utterance_judge 0, controller 77
BASE_REPLIES = 16
CLEARING = ('provider', 'move_on', 'drop_question', 'abandon', 'going_on', 'stop_closes', 'new_call', 'ear_first_overruled', 'open_question')


def _controller_sources():
    return [Path(module.__file__).read_text(encoding='utf-8') for module in cm_patch.controller_modules()]


def _callee(call):
    f = call.func
    return f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None


def places(source):
    """Every place of ``source`` that sets the kind of an utterance: ``[(what, line)]``."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        name = _callee(node)
        if name in ('analyze', '_analyze', 'Decision'):
            found.append((name, node.lineno))
        elif name == '_replace' and any(k.arg == 'kind' for k in node.keywords):
            found.append(('_replace(kind=)', node.lineno))
    return found


def _names(tree, wanted):
    """Names (and imported names) ``wanted`` anywhere in ``tree``."""
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == wanted:
            out.append(node.lineno)
        elif isinstance(node, ast.Attribute) and node.attr == wanted:
            out.append(node.lineno)
        elif isinstance(node, (ast.ImportFrom, ast.Import)) and any((a.asname or a.name) == wanted for a in node.names):
            out.append(node.lineno)
    return out


def test_the_engine_reads_no_text_for_its_kind():
    tree = ast.parse(EN.read_text(encoding='utf-8'))
    assert _names(tree, 'analyze') == [], 'the engine classifies nothing: the kind is given'
    engine = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'EchoEngine')
    asking = [c.lineno for c in ast.walk(engine) if isinstance(c, ast.Call) and _callee(c) == 'going_on']
    assert asking == [], 'the plan of going on is given with the verdict (going=), not worked out by the engine'
    assert places(EN.read_text(encoding='utf-8')) == [], 'the engine sets no kind of its own'


def test_every_reply_carries_its_verdict():
    calls = [c for source in _controller_sources() for c in ast.walk(ast.parse(source)) if isinstance(c, ast.Call) and _callee(c) == '_reply']
    bare = [c.lineno for c in calls if not any(k.arg == 'decided' for k in c.keywords)]
    assert bare == [], f'_reply without a verdict at {bare}'
    assert len(calls) == BASE_REPLIES, f'{len(calls)} calls of _reply: a new one is a new owner of the kind'
    engine = next(n for n in ast.parse(EN.read_text(encoding='utf-8')).body if isinstance(n, ast.ClassDef) and n.name == 'EchoEngine')
    reply = next(f for f in engine.body if isinstance(f, ast.FunctionDef) and f.name == 'reply')
    kwonly = {a.arg: d for a, d in zip(reply.args.kwonlyargs, reply.args.kw_defaults)}
    assert 'decided' in kwonly and kwonly['decided'] is None, 'decided is required (no default)'
    assert 'admitted' not in kwonly and 'qa' not in kwonly


def test_one_binder_of_the_answer():
    writers = []
    for source in _controller_sources():
        tree = ast.parse(source)
        for fn in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            if fn.name == '_bind_answer':
                continue
            for node in ast.walk(fn):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, (ast.AnnAssign, ast.AugAssign)) else []
                flat = [e for t in targets for e in (t.elts if isinstance(t, (ast.Tuple, ast.List)) else [t])]
                if any(isinstance(t, ast.Attribute) and t.attr == '_answer' for t in flat):
                    writers.append((fn.name, node.lineno))
                if isinstance(node, ast.Call) and _callee(node) == 'setattr' and len(node.args) >= 2 and isinstance(node.args[1], ast.Constant) and node.args[1].value == '_answer':
                    writers.append((fn.name, node.lineno))
    assert writers == [], f'_answer written outside _bind_answer: {writers}'
    from echo_sync.cm_question import QuestionSlot
    assert '_answer' in QuestionSlot.CLOSED and QuestionSlot.CLOSED['_answer'] is None


def test_the_places_of_the_kind_do_not_grow():
    total = {name: places(path.read_text(encoding='utf-8')) for name, path in (('engine', EN), ('judge', UJ))}
    total['controller'] = [p for source in _controller_sources() for p in places(source)]
    count = sum(len(v) for v in total.values())
    assert count <= BASE_PLACES, {k: len(v) for k, v in total.items()}


def test_the_answer_is_cleared_where_a_question_ends():
    table = next(t for t in (table_of(s) for s in _controller_sources()) if 'ACTS' in t)
    acts = table['ACTS']
    for reason in CLEARING:
        cleared = {name for step in acts[reason][1] if step[0] == 'clear' for name in step[1]}
        assert '_answer' in cleared, f'{reason} leaves the answer of the question it ends'
    stop = {name for step in acts['stop'][1] if step[0] == 'clear' for name in step[1]}
    assert '_answer' not in stop, 'a stop keeps its answer'


if __name__ == '__main__':
    for label, path in (('engine', EN), ('judge', UJ)):
        print(label, len(places(path.read_text(encoding='utf-8'))))
    print('controller', sum(len(places(s)) for s in _controller_sources()))
