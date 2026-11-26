"""night-gate, step 1: the lock on the ONE place that does what cannot be taken back (``ControlledMedia._act`` and its table ``ACTS``).

Static, by the AST, the engine is not started: in ``echo_sync/controlled_media.py`` a call of ``_new_epoch``, ``_cancelled`` or ``….retire``, an assignment
``….question_id = None`` (or a ``setattr`` of it) and the literal ``'cancel'`` stand only inside ``_act`` and its table. A new place outside the gate fails this file:
the lock counts places, it lists no phrase. The wire (``native_media_socket.py``) keeps exactly one ``'cancel'``: the branch that carries the cut out, and its service
phrases ask the gate. No other module of ``echo_sync`` does any of it.

``census(source)`` is also the meter of the night: the numbers of places before and after are taken with it (``python tests/test_night_gate_lock.py <file>``)."""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CM = ROOT / 'echo_sync' / 'controlled_media.py'
CONTROLLER = [CM, *sorted((ROOT / 'echo_sync').glob('cm_*.py'))]      # the core and the family modules it is split into
NMS = ROOT / 'echo_sync' / 'native_media_socket.py'
GATE = '_act'                                   # the one function; its steps (``_step_*``, the verbs of ``STEPS``) are its body: the places inside them are the gate's
STEP_PREFIX = '_step_'
TABLE = ('ACTS', 'ACT_WIRE', 'ACT_KINDS')      # its table: class-level names of ControlledMedia
CALLS = ('_new_epoch', '_cancelled', 'retire')   # methods only the gate may call
WIRE = 'cancel'
FIELD = 'question_id'
KINDS = ('cut_sound', 'pause', 'reset_portion', 'close_question', 'supersede', 'speak')
STEPS = ('epoch', 'timers', 'cut', 'clear', 'clear_own', 'retire', 'note', 'wire', 'owner', 'authorized', 'held', 'may_sound', 'speak')      # M6: the last five are the steps of the sound and of the owner's cut; fix5: 'clear_own' clears only what is of the question being closed


import pytest
pytestmark = pytest.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)


def _is_none(node):
    return isinstance(node, ast.Constant) and node.value is None


def census(source, gate=GATE, table=TABLE):
    """Every place of ``source`` that does the irreversible, as ``[(kind, function, line)]``; ``kind``: 'new_epoch' | 'cancelled' | 'retire' | 'question_none' | 'cancel_literal' | 'wire_name'.
    ``inside``: the same list for the places inside the gate and its table. Returns ``(outside, inside)``. ``__init__`` may give ``question_id`` its first None."""
    tree = ast.parse(source)
    outside, inside = [], []

    def note(kind, function, node, allowed):
        (inside if allowed else outside).append((kind, function, node.lineno))

    def walk(node, function, allowed, compared=False):
        for child in ast.iter_child_nodes(node):
            name, ok = function, allowed
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name, ok = child.name, child.name == gate or (gate == GATE and child.name.startswith(STEP_PREFIX))
            elif isinstance(child, (ast.Assign, ast.AnnAssign)) and function is None:
                targets = child.targets if isinstance(child, ast.Assign) else [child.target]
                if any(isinstance(t, ast.Name) and t.id in table for t in targets):
                    ok = True
            if isinstance(child, ast.Call):
                f = child.func
                if isinstance(f, ast.Attribute) and f.attr in CALLS:
                    note({'_new_epoch': 'new_epoch', '_cancelled': 'cancelled', 'retire': 'retire'}[f.attr], name, child, ok)
                if isinstance(f, ast.Name) and f.id == 'setattr' and len(child.args) >= 2 and isinstance(child.args[1], ast.Constant) and child.args[1].value == FIELD:
                    note('question_none', name, child, ok)
            if isinstance(child, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                targets = child.targets if isinstance(child, ast.Assign) else [child.target]
                flat = [e for t in targets for e in (t.elts if isinstance(t, (ast.Tuple, ast.List)) else [t])]
                value = getattr(child, 'value', None)
                if any(isinstance(t, ast.Attribute) and t.attr == FIELD for t in flat) and (value is None or _is_none(value) or isinstance(value, (ast.Tuple, ast.List))):
                    note('question_none', name, child, ok or name == '__init__')
            if isinstance(child, ast.Constant) and child.value == WIRE:
                note('cancel_literal', name, child, ok)
            # the table's word for the wire may be READ outside the gate only to compare with it: building an action of it is the gate's
            if isinstance(child, (ast.Name, ast.Attribute)) and (child.id if isinstance(child, ast.Name) else child.attr) == 'ACT_WIRE' and isinstance(child.ctx, ast.Load) and not ok and not compared:
                note('wire_name', name, child, False)
            walk(child, name, ok, isinstance(child, ast.Compare))
    walk(tree, None, False)
    return outside, inside


def table_of(source):
    """``ACTS`` and ``ACT_KINDS`` of the class, read from the source by the AST (literals only: the table is data)."""
    tree = ast.parse(source)
    out = {}
    for cls in [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'ControlledMedia']:
        for node in cls.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id in ('ACTS', 'ACT_KINDS', 'ACT_WIRE'):
                out[node.targets[0].id] = ast.literal_eval(node.value)
    return out


def gate_calls(source):
    """Every ``….​_act(act, reason, …)`` of the source as ``[(act, reason, function, line, keywords)]``; a non-literal argument is given as None."""
    found = []

    def walk(node, function):
        for child in ast.iter_child_nodes(node):
            name = child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else function
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute) and child.func.attr == GATE:
                args = [a.value if isinstance(a, ast.Constant) and isinstance(a.value, str) else None for a in child.args[:2]] + [None, None]
                found.append((args[0], args[1], name, child.lineno, sorted(k.arg or '**' for k in child.keywords)))
            walk(child, name)
    walk(ast.parse(source), None)
    return found


# --- the lock ------------------------------------------------------------------------------------------------------------------

def test_nothing_irreversible_stands_outside_the_gate():
    outside, inside = census(CM.read_text(encoding='utf-8'))
    assert outside == [], 'a place outside ControlledMedia._act does the irreversible: ' + ', '.join('%s in %s (line %s)' % place for place in outside)
    held = sorted((kind, function) for kind, function, _ in inside)
    # each of them stands ONCE: three calls in the steps of the gate (M6: ``_act`` runs the steps of the row, ``STEPS``), the wire's word in the table, the first None of ``question_id`` in the constructor (the gate clears it through ``QuestionSlot.CLOSED``)
    assert held == [('cancel_literal', None), ('cancelled', '_step_cut'), ('new_epoch', '_step_epoch'), ('question_none', '__init__'), ('retire', '_step_retire')], held


def test_the_gate_stands_right_before_new_epoch_and_has_the_agreed_signature():
    tree = ast.parse(CM.read_text(encoding='utf-8'))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'ControlledMedia')
    methods = [n for n in cls.body if isinstance(n, ast.FunctionDef)]
    names = [m.name for m in methods]
    assert names.count(GATE) == 1 and names.count('_new_epoch') == 1
    assert names[names.index(GATE) + 1] == '_new_epoch', 'the gate stands right before _new_epoch'
    gate = methods[names.index(GATE)]
    assert [a.arg for a in gate.args.args] == ['self', 'act', 'reason'] and [a.arg for a in gate.args.kwonlyargs] == ['basis', 'by_reflex']
    assert [ast.literal_eval(d) for d in gate.args.kw_defaults] == [None, False]
    assert gate.args.kwarg is not None and gate.args.kwarg.arg == 'args' and gate.args.vararg is None, 'the only open door is ``**args`` (what the steps of a speak row read); any other widening of the signature loosens the lock'
    assert "if args and kind!='speak':raise TypeError" in ast.get_source_segment(CM.read_text(encoding='utf-8'), gate), 'a row that is not of sound takes no argument but basis and by_reflex: a misspelled basis must not be swallowed'


def test_the_table_is_closed_data():
    from echo_sync.cm_question import QuestionSlot
    from echo_sync.controlled_media import ControlledMedia
    assert not hasattr(ControlledMedia, 'ACT_EMPTY'), 'one table of what a closing leaves: QuestionSlot.CLOSED'
    table = table_of(CM.read_text(encoding='utf-8'))
    assert table['ACT_KINDS'] == KINDS and table['ACT_WIRE'] == WIRE
    assert table['ACTS'], 'the table has rows'
    for reason, row in table['ACTS'].items():
        act, steps, reversible, witness = row
        assert act in KINDS, reason
        assert isinstance(reversible, bool) and isinstance(witness, bool), reason
        assert steps and all(step[0] in STEPS for step in steps), reason
        cleared = [name for step in steps if step[0] in ('clear', 'clear_own') for name in step[1]]
        assert all(name in QuestionSlot.CLOSED for name in cleared), reason
        # what moves the reply token, retires an answer or clears a field cannot be taken back, and the row says so
        if any(step[0] in ('epoch', 'retire', 'clear', 'clear_own') for step in steps):
            assert reversible is False, reason
        assert not witness or act == 'supersede', reason      # this night only a superseding asks for a confirmed witness


def test_every_call_of_the_gate_names_a_row_and_every_row_is_called():
    rows = table_of(CM.read_text(encoding='utf-8'))['ACTS']
    calls = [call for path in CONTROLLER for call in gate_calls(path.read_text(encoding='utf-8'))]      # P01: the callers live in the family modules
    assert calls, 'the gate is called'
    for act, reason, function, line, keywords in calls:
        assert act is not None and reason is not None, 'the act and the reason are literals (%s, line %s)' % (function, line)
        assert reason in rows and rows[reason][0] == act, 'no row %s/%s (%s, line %s)' % (act, reason, function, line)
        if act != 'speak':
            assert set(keywords) <= {'basis', 'by_reflex'}, 'a call of %s/%s passes a keyword the gate would swallow: %s (%s, line %s)' % (act, reason, keywords, function, line)
    assert set(rows) == {reason for _, reason, _, _, _ in calls}, 'rows nobody calls: %s' % sorted(set(rows) - {reason for _, reason, _, _, _ in calls})


def test_the_closing_sets_stay_as_they_were_site_by_site():
    """Step 1 unifies nothing: what each closing clears is what that site cleared on 671d2fe (read off the code line by line)."""
    rows = table_of(CM.read_text(encoding='utf-8'))['ACTS']
    cleared = lambda reason: tuple(name for step in rows[reason][1] if step[0] == 'clear' for name in step[1])      # noqa: E731
    retired = lambda reason: tuple(step[1] for step in rows[reason][1] if step[0] == 'retire')      # noqa: E731
    # B (lane of the kind and the answer): ``_answer`` is cleared where a question ends or a new one opens; a stop keeps it (the paused answer is kept) and so do the rows that never touched it
    assert cleared('provider') == ('question_id', 'grounded', 'held_source', 'unsettled', 'settled_segment', '_answer') and retired('provider') == ('revised_nonquestion',)
    assert cleared('move_on') == ('question_id', 'grounded', 'held_source', 'unsettled', 'settled_segment', '_answer') and retired('move_on') == ('move_on',)
    assert cleared('stop') == ('held_source',) and retired('stop') == ()
    assert cleared('stop_closes') == ('question_id', 'grounded', 'unsettled', 'settled_segment', '_answer')
    assert cleared('drop_question') == ('question_id', 'grounded', 'held_source', 'unsettled', 'settled_segment', 'refused_attempt', '_answer') and retired('drop_question') == ()
    # fix5: the drop clears the candidate only when it is the dropped question's own; a candidate of a newer turn keeps its job (w3 n2_d06 step 2, test_silence_kinds: a newer candidate outlives the older drop)
    assert tuple(name for step in rows['drop_question'][1] if step[0] == 'clear_own' for name in step[1]) == ('candidate',)
    assert cleared('abandon') == ('question_id', 'grounded', 'held_source', 'unsettled', 'settled_segment', 'abandon', 'suspended', '_answer') and retired('abandon') == ('abandoned',)
    assert 'rejected_at_publish' not in rows      # B: the engine reads no text again at the publication: there is no «not a question after all» to give up for
    assert cleared('going_on') == ('question_id', 'grounded', 'held_source', 'unsettled', 'settled_segment', '_answer') and retired('going_on') == ()
    assert cleared('open_question') == ('_answer',) and retired('new_question') == ('new_question',) and retired('utterance_continued') == ('utterance_continued',)
    assert cleared('v5_stale') == () and retired('v5_stale') == ('utterance_continued',)
    assert retired('new_call') == ('new_call',) and retired('ear_first_overruled') == ('ear_first_overruled',)
    assert cleared('new_call') == ('_answer',) and cleared('ear_first_overruled') == ('_answer',)


def test_the_wire_keeps_one_cancel_and_its_phrases_ask_the_gate():
    source = NMS.read_text(encoding='utf-8')
    outside, _ = census(source, gate='actions')
    assert outside == [], 'the wire does nothing irreversible of the controller\'s: %s' % outside
    tree = ast.parse(source)
    literals = [n.lineno for n in ast.walk(tree) if isinstance(n, ast.Constant) and n.value == WIRE]
    assert len(literals) == 1, 'one branch carries the cut out: %s' % literals
    say = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == '_say')
    plays = [n for n in ast.walk(say) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == '_play']
    assert len(plays) == 1
    freshness = plays[0].args[3]
    constant = isinstance(freshness, ast.Lambda) and isinstance(freshness.body, ast.Constant)
    assert not constant, 'a service phrase is released by the gate, not by a constant «yes»'


def test_no_other_module_does_it():
    """The controller's ``_new_epoch`` / ``_cancelled`` / ``engine.retire`` and its ``question_id`` are nobody else's to touch. A module that has a method of the same name of
    its own (``engine.retire`` itself, the generator's ``_cancelled(event)``) calls its own."""
    method = {'new_epoch': '_new_epoch', 'cancelled': '_cancelled', 'retire': 'retire'}
    for path in sorted((ROOT / 'echo_sync').glob('*.py')):
        if path.name in ('controlled_media.py', 'native_media_socket.py'):
            continue
        source = path.read_text(encoding='utf-8')
        own = {n.name for n in ast.walk(ast.parse(source)) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        outside, _ = census(source, gate='\0')
        mine = [place for place in outside if place[0] == 'question_none' or method.get(place[0]) not in own | {None}]
        assert mine == [], '%s: %s' % (path.name, mine)


# --- the lock can fail: a place added outside the gate is seen ---------------------------------------------------------------

SAMPLE = '''
class ControlledMedia:
    ACT_WIRE='cancel'
    ACTS={'x':('cut_sound',(('cut',),('wire',)),True,False)}
    def _act(self,act,reason,*,basis=None,by_reflex=False):
        self._new_epoch('x');self._cancelled();self.engine.retire(self.session_id,'x');self.question_id=None
        return 'do',[{'type':self.ACT_WIRE,'epoch':self.epoch}]
    def __init__(self):self.question_id=None
    def reads(self,rest):return any(action['type']==self.ACT_WIRE for action in rest)
    def other(self):
        %s
'''


def _outside(line):
    return [kind for kind, function, _ in census(SAMPLE % line)[0] if function == 'other']


def test_the_sample_without_a_new_place_is_clean():
    assert census(SAMPLE % 'return self._act("cut_sound","x")[1]')[0] == []


def test_a_new_place_outside_the_gate_is_caught_whatever_its_kind():
    assert _outside("self._new_epoch('mine')") == ['new_epoch']
    assert _outside('self._cancelled()') == ['cancelled']
    assert _outside("self.engine.retire(self.session_id,'mine')") == ['retire']
    assert _outside('self.question_id=None') == ['question_none']
    assert _outside('self.question_id=self.other_id=None') == ['question_none']
    assert _outside("setattr(self,'question_id',None)") == ['question_none']
    assert _outside("return [{'type':'cancel','epoch':self.epoch}]") == ['cancel_literal']
    assert _outside("return [{'type':self.ACT_WIRE,'epoch':self.epoch}]") == ['wire_name']
    assert _outside('self.question_id=turn_id') == []            # a new question takes the place: not a clearing
    assert _outside("return [a for a in self.x if a['type']!=self.ACT_WIRE]") == []      # reading the wire's word to compare is no cut


if __name__ == '__main__':      # the meter: python tests/test_night_gate_lock.py [file]
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else CM
    out, ins = census(target.read_text(encoding='utf-8'))
    for label, places in (('outside the gate', out), ('inside the gate', ins)):
        counts = {}
        for kind, _, _ in places:
            counts[kind] = counts.get(kind, 0) + 1
        print(label, len(places), dict(sorted(counts.items())))
        for kind in sorted(counts):
            print('   %-15s %s' % (kind, ' '.join('%s:%s' % (function, line) for k, function, line in places if k == kind)))
