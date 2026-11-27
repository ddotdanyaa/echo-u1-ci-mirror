"""FAKES: every stand-in for the synthesizer in tests/ and tools/ takes what the real one takes.

The product speaks the LAST portion of an answer as ``synthesize(text, end='fall')`` (native_media_socket._speak, E76) and a worker as
``worker.synthesize(speech, path, end='fall')`` (sapi_worker.say). A stand-in that knows only ``(text)`` or ``(text, path)`` raised TypeError on that
call, the wire answered ``controlled_synthesis_failed`` and the test went red for a reason that has nothing to do with SAPI. The real signatures are
read here (inspect for the worker, the source of the closure for the wire), the stand-ins are found by AST, and each must accept ``end``.
"""
import ast
import inspect
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOKS = {'synth_pcm'}      # a World's own text -> PCM hook: called by the fake itself, never by the product


def accepts(args, name):
    names = [a.arg for a in args.posonlyargs + args.args + args.kwonlyargs]
    return name in names or args.kwarg is not None


def real_worker_keywords():
    from echo_sync.sapi_worker import SapiWorkerManager
    return [p for p in inspect.signature(SapiWorkerManager.synthesize).parameters if p != 'self']


def real_wire_keywords():
    source = (ROOT / 'echo_sync' / 'controlled_host.py').read_text(encoding='utf-8')
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == 'synthesize':
            return [a.arg for a in node.args.args]
    raise AssertionError('controlled_host has no synthesize(text, end) closure')


def stand_ins():
    """(file, line, name, args) of every function or lambda that plays the synthesizer: a def called synthesize/_synthesize, or the value
    assigned to an attribute ``.synthesize`` / ``synthesize=`` keyword (a name is followed to its def in the same file)."""
    found = []
    for path in sorted(list((ROOT / 'tests').rglob('*.py')) + list((ROOT / 'tools').rglob('*.py'))):
        if path.name == Path(__file__).name:
            continue
        tree = ast.parse(path.read_text(encoding='utf-8'))
        defs = {}
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                defs.setdefault(node.name, []).append(node)
        rel = path.relative_to(ROOT).as_posix()

        def add(fn):
            found.append((rel, fn.lineno, getattr(fn, 'name', '<lambda>'), fn.args))

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in ('synthesize', '_synthesize'):
                add(node)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    pairs = []
                    if isinstance(target, ast.Attribute):
                        pairs = [(target.attr, node.value)]
                    elif isinstance(target, ast.Tuple) and isinstance(node.value, ast.Tuple):
                        pairs = [(t.attr, v) for t, v in zip(target.elts, node.value.elts) if isinstance(t, ast.Attribute)]
                    for attr, value in pairs:
                        if attr != 'synthesize':
                            continue
                        if isinstance(value, ast.Lambda):
                            add(value)
                        elif isinstance(value, ast.Name):
                            for fn in defs.get(value.id, []):
                                add(fn)
            elif isinstance(node, ast.Call):
                for kw in node.keywords:
                    if kw.arg == 'synthesize':
                        if isinstance(kw.value, ast.Lambda):
                            add(kw.value)
                        elif isinstance(kw.value, ast.Name):
                            for fn in defs.get(kw.value.id, []):
                                add(fn)
    return [item for item in found if item[2] not in HOOKS]


def test_the_real_signatures_carry_the_end_keyword():
    assert 'end' in real_worker_keywords()
    assert 'end' in real_wire_keywords()


def test_every_synthesizer_stand_in_accepts_what_the_real_one_is_called_with():
    items = stand_ins()
    assert len(items) > 30, 'the scan found almost no stand-ins: it no longer sees the way the tests plug them in'
    wanted = {'end'} & (set(real_worker_keywords()) | set(real_wire_keywords()))
    bad = [f'{f}:{line} {name}({ast.unparse(args)})' for f, line, name, args in items if any(not accepts(args, k) for k in wanted)]
    assert not bad, 'a stand-in rejects end=: the last portion of an answer would fail as controlled_synthesis_failed\n' + '\n'.join(bad)
