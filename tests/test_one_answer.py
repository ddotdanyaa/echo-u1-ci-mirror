"""Lane answer (M3, owner ``cm-route``): an answer is released only through ``_adopt_reply`` / ``_reply`` -> ``_bind_answer(answer, tid)``; there is no other road. Locks by the AST plus one run.

* the controller has ONE call of ``engine.reply``: inside ``_reply``; the engine is built with ONE generator, ``_generate``, which reads only what ``_bind_answer`` bound;
* ``_bind_answer`` is called from ``_reply`` (and nowhere else);
* every ``StreamingAnswer(...)`` made by the controller sits in a function that sends it through a ``_reply(..., answer=...)``: the places are ``_publish_reference``, ``_source``, ``_lead_cue`` (a new one is a new road: add it here with its reason);
* a ``_reply`` without ``answer=`` (a verdict, a command, a stop) publishes nothing: ``_generate`` refuses it;
* the binding is refused for another turn, an unbound call, and another epoch."""
import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))

import cm_patch                                         # noqa: E402

ROADS = {'_publish_reference', '_source', '_lead_cue'}      # the functions that make an answer to publish


def _functions():
    for module in cm_patch.controller_modules():
        tree = ast.parse(Path(module.__file__).read_text(encoding='utf-8'))
        for fn in ast.walk(tree):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                yield Path(module.__file__).name, fn


def _calls(fn, name=None, attr=None):
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            f = node.func
            if (name and isinstance(f, ast.Name) and f.id == name) or (attr and isinstance(f, ast.Attribute) and f.attr == attr):
                yield node


def test_the_engine_is_replied_to_from_one_place_the_reply():
    sites = [(file, fn.name, node.lineno) for file, fn in _functions() for node in _calls(fn, attr='reply')
             if isinstance(node.func.value, ast.Attribute) and node.func.value.attr == 'engine']
    assert [(f, name) for f, name, _ in sites] == [('cm_answer.py', '_reply')], sites      # the answer owner (cm_answer after the split U94.0)


def test_the_answer_is_bound_by_the_reply_only():
    callers = sorted({fn.name for _, fn in _functions() for _ in _calls(fn, attr='_bind_answer')})
    assert callers == ['_reply'], callers


def test_the_engine_has_one_generator_and_it_reads_the_binding():
    built = [(fn.name, [ast.unparse(a) for a in node.args]) for _, fn in _functions() for node in _calls(fn, name='EchoEngine')]
    assert built and all(args[1] == 'self._generate' for _, args in built), built
    generate = next(fn for _, fn in _functions() if fn.name == '_generate')
    read = {n.attr for n in ast.walk(generate) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == 'self'}
    assert '_answer' in read and read <= {'_answer', 'epoch', 'state'}, read


def test_every_answer_made_goes_out_through_a_reply_with_answer():
    made = {fn.name for _, fn in _functions() if any(True for _ in _calls(fn, name='StreamingAnswer'))}
    assert made == ROADS, made
    for _, fn in _functions():
        if fn.name in ROADS:
            replies = list(_calls(fn, attr='_reply'))
            assert replies and all('answer' in [k.arg for k in node.keywords] for node in replies), fn.name


def _bound(c):
    from echo_sync.generator import StreamingAnswer
    return StreamingAnswer('Ответ.', [], final=False, retrieval_status='unverified', first_chunk='Ответ.', raw_text='Ответ.')


def _asked(turn, revision):
    """What ``EchoEngine._produce`` hands the generator (U94.2): the question, the history, the context, the request that carries the claim (the turn and the revision it claimed), the model."""
    return ('q', (), '', {'claim': {'turn': turn, 'revision': revision}}, 'm')


def test_an_unbound_or_another_turns_answer_is_refused():
    from echo_sync.controlled_media import ControlledMedia
    c = ControlledMedia.__new__(ControlledMedia)
    c.epoch = 3
    c.state = lambda: {'pending_turn': 'u1', 'revision': 6}      # the engine has claimed the question: revision 5 -> 6
    c._answer = None
    c.question_text, c.witness_note = '', None      # what ``_bind_answer`` reads for the trace of the question's condition (U80)
    with pytest.raises(RuntimeError, match='not authorized'):
        c._generate(*_asked('u1', 6))
    answer = _bound(c)
    c.state = lambda: {'pending_turn': 'u1', 'revision': 5}      # bound before the claim: the revision the engine then claims is the next
    c._bind_answer(answer, 'u1')
    assert c._answer == (answer, 'u1', 3, 5)
    c.state = lambda: {'pending_turn': 'u1', 'revision': 6}
    assert c._generate(*_asked('u1', 6)) is answer
    with pytest.raises(RuntimeError, match='another turn'):
        c._generate(*_asked('u2', 6))      # the engine claims another turn
    with pytest.raises(RuntimeError, match='another turn'):
        c._generate(*_asked('u1', 7))      # another revision than the one standing
    with pytest.raises(RuntimeError, match='another turn'):
        c._generate('q', (), '', {}, 'm')      # no claim, no answer
    c._answer = (answer, 'u2', 3, 5)
    with pytest.raises(RuntimeError, match='another turn'):
        c._generate(*_asked('u1', 6))
    c._answer = (answer, 'u1', 3, 5)
    c.epoch = 4
    with pytest.raises(RuntimeError, match='another turn'):
        c._generate(*_asked('u1', 6))
    c.epoch = 3
    c._bind_answer(None, None)
    with pytest.raises(RuntimeError, match='not authorized'):
        c._generate(*_asked('u1', 6))
