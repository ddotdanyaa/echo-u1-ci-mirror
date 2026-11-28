"""U79: the Codex route is ONE file (``echo_sync/codex_road.py``; ``ws_transport.py`` is its socket variant) and the engine reaches it only as the first road of ``reserve_text.Roads``: replacing the route edits
one file. And the end of the story it was made for: Codex is silent and the reserve answer goes out after ``NEXT_ROAD_S``, not after the 8.5 s of the old wait (through ``FastText`` over the real ``Roads`` with scripted
roads on the virtual clock of ``test_roads_channel``)."""
import ast
import pathlib

from echo_sync import codex_road, reserve_text
from echo_sync.reserve_text import NEXT_ROAD_S, PRIMARY, ReserveError
from test_roads_channel import ANSWER, G120, T0, _fresh, channel, drain, fail, kinds, open_question, scene, say, tick, until      # noqa: F401 - the fixtures are the harness of the roads

PACKAGE = pathlib.Path(codex_road.__file__).parent
THE_ROUTE = {'codex_road.py', 'ws_transport.py'}      # the route and its socket variant
ANOTHER_ROAD = {'generator.py'}      # the engine's own generator (a road of the answers outside the text channel: ARCH_ONE R row, ``plugin-codex``): not the first road of the roads
NAMES = {'CodexTransport', 'codex_stream', 'FAST_MODEL', 'FAST_EFFORT', 'FAST_URL', 'PING_URL', 'WS_READY'}


import pytest
pytestmark = pytest.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)


def code_of(path):
    """The AST of a module without its docstrings: what the code says, not what its comments tell."""
    tree = ast.parse(path.read_text(encoding='utf-8'))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body and isinstance(node.body[0], ast.Expr) and isinstance(getattr(node.body[0], 'value', None), ast.Constant):
            node.body[0].value = ast.Constant(value='')
    return tree


def test_the_codex_route_is_named_in_one_file_and_the_engine_reaches_it_only_through_the_first_road():
    found = []
    for path in sorted(PACKAGE.glob('*.py')):
        if path.name in THE_ROUTE | ANOTHER_ROAD:
            continue
        for node in ast.walk(code_of(path)):
            named = ({node.id} if isinstance(node, ast.Name) else {node.attr} if isinstance(node, ast.Attribute) else {a.name for a in node.names} if isinstance(node, ast.ImportFrom) else set()) & NAMES
            wire = isinstance(node, ast.Constant) and isinstance(node.value, str) and ('chatgpt.com' in node.value or 'codex_cli_rs' in node.value)
            if named or wire:
                found.append(f'{path.name}:{getattr(node, "lineno", 0)} {sorted(named) or node.value[:30]}')
    assert not found, found
    # fast_text asks for the first road by the name of the module, in one place (``for_call``)
    assert (PACKAGE / 'fast_text.py').read_text(encoding='utf-8').count("fromlist=['primary']") == 1


def test_the_first_road_of_a_call_is_what_the_route_gives_and_nothing_else_of_it_is_asked(monkeypatch):
    import types

    from echo_sync import fast_text
    seen = []

    def fake_first_road(resolved, credentials):
        seen.append((resolved['text_transport'], credentials))
        return lambda request, cancelled: iter(['Да.'])
    monkeypatch.setattr(codex_road, 'primary', fake_first_road)
    controller = types.SimpleNamespace(fast_exchanges=lambda: [], fast_in_play=lambda: None, fast_carry=lambda: '', settings={}, ear_ended=None, source_segment_id=None, refuse_deadline=lambda *a: None, decision_due=lambda *a: None)
    monkeypatch.setattr(reserve_text, 'read_keys', lambda path=None: {})
    channel_ = fast_text.for_call({'fast_text': 'on'}, controller, credentials=lambda: ('t', 'a'))
    try:
        assert [mode for mode, _ in seen] == ['http'] and channel_.stream.primary is not None
        assert list(channel_.stream.primary({}, None)) == ['Да.']      # the route replaced in ONE place: the channel runs over whatever ``primary`` gave
    finally:
        channel_.close()


def test_codex_silent_the_reserve_answer_goes_out_after_the_next_road_s_not_after_eight_and_a_half_seconds(scene):
    """The question is asked; Codex says nothing; the reserve (a road that answers at once) is asked at ``NEXT_ROAD_S`` and its answer is the answer the listener gets, within a tick of it. The first road, silent,
    is let go as the loser of the race (``Roads.lost``): its silence is counted, it is not the reason the answer waits."""
    scene.plan(G120, say())      # Groq answers at once; the first road has no plan: it hangs
    fast, clock = channel(scene, cloud=False)
    assert open_question(fast) == 'started' and until(lambda: scene.asked == [PRIMARY])
    events = tick(fast, clock, T0 + 3.0)
    texted = [e for e in events if e['kind'] == 'text' and not e.get('provisional')]
    assert texted and texted[0]['text'] == ANSWER, events
    assert NEXT_ROAD_S <= texted[0]['at'] <= NEXT_ROAD_S + 0.5, f'the answer came at {texted[0]["at"]} s (the next road is asked at {NEXT_ROAD_S} s)'
    assert texted[0]['at'] < 8.5 and scene.asked == [PRIMARY, G120] and scene.cancelled[0].is_set()
    events += [] if 'done' in kinds(events) else drain(fast)
    assert 'done' in kinds(events) and 'failed' not in kinds(events) and not fast.off and reserve_text.REFUSAL not in ''.join(e['text'] for e in events)
