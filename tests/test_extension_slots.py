"""P13 / harvest11 #8, Р5 of classes/РАСШИРЕНИЕ.md: a NEW mechanic is added through the sockets of the engine and through nothing else.

Five toy mechanics are added here the way ARCH_ONE §2 says (a row in a table the owner reads) and each one is DRIVEN through the real ControlledMedia (``helpers_night_memory.Call``,
the stand of the other whole-call tests), with the control run before the rows are there so the verdict or the call output is seen to CHANGE:

    hush      S1 a probe row (``cm_probes.PROBES``) + S2 a rule row of the judge (``utterance_judge.JUDGE_RULES``) + S3 an ``ACTS`` row with a new verb of ``STEPS``
    promise   S4 a kind of the conversation ledger with a TTL of ``timer_policy`` (held, then ended by the tick of the controller)
    prime     S5 a ``warm.Step`` of the warm plan
    toyroad   S5 a row of the reserve roads (``reserve_text.ROADS``): the road the first road's failure falls through to answers the call
    census    S6 a tool outside the call that reads the call journal and imports no owner

No owner file may change: the blobs of ``controlled_media.py`` and of every ``cm_*.py`` are the same before and after (``tools/extension_contract.OWNER_FILES``), the bodies of ``_act`` and
``_judge`` are the same code objects, and the owner census does not rise. The contract of the catalogue (>= 80 % of a random 30 of the 341 mechanics land with no owner edit) is then MEASURED:
the sockets the toys proved open weigh the catalogue (``tools/extension_contract``); before the sockets stood it was 11 % (S6 only).
A socket that is not open fails ITS test, and the share falls with it: the lock cannot be passed by claiming a socket."""
import json
import logging
import re
import subprocess
import sys
from pathlib import Path

import pytest

import helpers_night_memory as M
from echo_sync import cm_probes, controlled_media, conversation_ledger as CL, reserve_text, timer_policy, utterance_judge as J, warm
from echo_sync.classifier import QUESTION, QUIET
from echo_sync.controlled_media import ControlledMedia

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import extension_contract as X      # noqa: E402
from tools import owner_census as C      # noqa: E402

ANSWER = 'Первая часть ответа про силу. Вторая часть ответа про массу. Третья часть ответа про ускорение.'
TOY_ANSWER = 'Запасная дорога отвечает про силу. Она сказала это сама.'
ASK = 'Что такое сила?'
HUSHED = 'тсс что такое сила?'


pytestmark = pytest.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)


class Journal(logging.Handler):
    """The log lines of the controller: the judge's line of a final (kind, reason, rule) is what a row changes."""

    def __init__(self):
        super().__init__(logging.INFO)
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())

    def judged(self, tid):
        rows = [dict(re.findall(r'(\w+)=(\S+)', line)) for line in self.lines if line.startswith('echo-sync judge ') and ('tid=%s ' % tid) in line]
        return rows[-1] if rows else {}


class Watch:
    """The echo-sync log of one run, with the level raised for it and put back."""

    def __enter__(self):
        self.log, self.handler = logging.getLogger('echo-sync'), Journal()
        self.level, self.log.level = self.log.level, logging.INFO
        self.log.addHandler(self.handler)
        return self.handler

    def __exit__(self, *exc):
        self.log.removeHandler(self.handler)
        self.log.level = self.level


def ask_in_call(tmp_path, said):
    """One whole call of the stand, ``said`` is heard once: (the judge's row of it, the requests the model got, the portions spoken)."""
    with Watch() as seen:
        call = M.Call(tmp_path, mind=lambda request: ANSWER, fast_text='on')
        try:
            tid = call.say(said)
            call.pump(3.0, 0.5)
            return seen.judged(tid), len(call.all_requests()), call.cues(), call
        finally:
            call.close()


# ---- the toys: one function a mechanic; each returns what it observed and which sockets it proved open ------------------------------------------------------------------------------------

def toy_hush(tmp_path):
    """S1 + S2 + S3: a word that hushes the system («тсс»). A probe sees the word, a rule of the judge makes it QUIET, an act row cuts the sound and notes it. Nothing of the judge or the gate is edited."""
    before_row, before_requests, _, _ = ask_in_call(tmp_path / 'before', HUSHED)
    unknown = getattr(cm_probes, 'UNKNOWN', 'unknown')
    notes = []

    def hush_probe(text, **_):
        return 1 if re.search(r'(?:^|\s)тсс(?:\s|$|[,.!?])', text.lower()) else unknown

    def note_step(controller, ctx, step):      # a NEW verb of the gate: S3
        notes.append((step[1], ctx['by']))

    def hush_rule(c):
        found = cm_probes.probe('toy_hush', c.text)
        if getattr(found, 'value', found) != 1 or c.tail or c.utterance:
            return None
        c.cm._act('cut_sound', 'toy_hush')
        return J.command_ruling(QUIET, 'toy_hush', None)

    gate, judge = ControlledMedia._act.__code__.co_code, ControlledMedia._judge.__code__.co_code
    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(cm_probes.PROBES, 'toy_hush', hush_probe)                                                                 # S1: one row
        mp.setitem(ControlledMedia.STEPS, 'toy_note', note_step)                                                             # S3: one verb ...
        mp.setitem(ControlledMedia.ACTS, 'toy_hush', ('cut_sound', (('toy_note', 'hush'), ('cut',)), True, False))           # ... and one row
        rows = list(J.JUDGE_RULES)
        rows.insert([row.name for row in rows].index('long_talk'), J.Rule('toy_hush', hush_rule, (('call', (), HUSHED),), (('call', (), ASK),)))
        mp.setattr(J, 'JUDGE_RULES', tuple(rows))                                                                            # S2: one row
        row, requests, cues, _ = ask_in_call(tmp_path / 'after', HUSHED)
        plain_row, plain_requests, plain_cues, _ = ask_in_call(tmp_path / 'plain', ASK)
    return {'before': (before_row, before_requests), 'hushed': (row, requests, cues), 'plain': (plain_row, plain_requests, plain_cues), 'notes': notes,
            'bodies_same': (gate, judge) == (ControlledMedia._act.__code__.co_code, ControlledMedia._judge.__code__.co_code)}


def toy_promise(tmp_path):
    """S4: the system holds a promise («вернёмся к смете») for a time the clock table gives it. A ledger kind + a TTL row of ``timer_policy``; the controller's tick ends it."""
    class Box:
        t = 1000.0

        def __call__(self):
            return self.t
    box = Box()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(CL, 'TOY_PROMISE_S', 5.0, raising=False)
        mp.setitem(timer_policy.TIMERS, 'conversation_ledger.TOY_PROMISE_S', 's')
        mp.setitem(CL.KINDS, 'toy_promise', CL.Kind('conversation_ledger.TOY_PROMISE_S', 'epoch', ('expired', 'epoch')))
        orphan = CL.kind_problems({'orphan': CL.Kind('conversation_ledger.NO_SUCH_S', 'tid', ('expired',))})
        problems = CL.kind_problems()
        c = ControlledMedia(tmp_path / 's.db', session_id='s', clock=box)
        c.engine.clock = box
        c.begin_call()
        c.convo.hold('toy_promise', 'smeta', None, 'вернуться к смете', box())
        held = c.convo.held('toy_promise', 'smeta', box())
        box.t += 4.0
        c.note_actions()
        still = c.convo.held('toy_promise', 'smeta')
        box.t += 2.0
        c.note_actions()
        gone = c.convo.held('toy_promise', 'smeta')
    return {'held': held, 'still': still, 'gone': gone, 'problems': problems, 'orphan': orphan, 'unregistered': timer_policy.unregistered()}


def toy_prime(tmp_path):
    """S5: a part that needs warming before the first call. A ``warm.Step`` of its own lane; the plan runs it beside the others and a part that fails is a record, never an exception."""
    ready = []

    def prime():
        c = ControlledMedia(tmp_path / 'prime.db', session_id='prime', clock=lambda: 1.0)
        c.begin_call()
        ready.append(c.epoch)

    def broken():
        raise RuntimeError('toy part is down')
    records = warm.run_plan([warm.Step('toy_prime', prime, budget_s=30, lane='toy'), warm.Step('toy_broken', broken, budget_s=1, lane='toy2')])
    return {'records': {record['name']: record for record in records}, 'ready': ready, 'plan': [step.name for step in warm.default_steps(tmp_path)]}


def toy_road(tmp_path):
    """S5: a new road of text. One row in ``reserve_text.ROADS`` (name of the key, host, model); the first road fails, the walk falls through to the toy road, its answer is what the call says."""
    posted = []

    def post(url, headers, body, first_text_s):
        posted.append(url)
        for word in TOY_ANSWER.split(' '):
            yield 'data: ' + json.dumps({'choices': [{'delta': {'content': word + ' '}}]})
        yield 'data: [DONE]'

    def dead(request, cancelled):
        raise reserve_text.ReserveError('first road is down')
        yield
    row = ('TOY_API_KEY', 'https://toy.invalid/v1', 'toy-model')
    reserve_text._REST.clear()
    reserve_text._BUDGET.clear()
    reserve_text._PRIMARY['until'] = 0.0
    with Watch(), pytest.MonkeyPatch.context() as mp:
        call = M.Call(tmp_path, mind=lambda request: '', fast_text='on')
        try:
            mp.setattr(reserve_text, 'ROADS', reserve_text.ROADS + (row,))
            roads = reserve_text.Roads(dead, reserve_text.ReserveStream({'TOY_API_KEY': 'toy'}, post=post, roads=reserve_text.ROADS))
            call.fast.stream = call.fast.roads = roads
            call.say(ASK)
            call.pump(6.0, 0.5)
            spoken = ' '.join(call.cues())
        finally:
            call.close()
            reserve_text._REST.clear()
            reserve_text._BUDGET.clear()
            reserve_text._PRIMARY['until'] = 0.0
    return {'posted': posted, 'spoken': spoken, 'road': row}


def toy_census(tmp_path):
    """S6: a tool outside the call: reads the journal a call wrote and counts what the judge decided. It imports no owner and the call does not know it."""
    source = '''
import json, sys
from pathlib import Path
def count(path):
    kinds = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            kinds[row.get("kind") or row.get("type") or "?"] = kinds.get(row.get("kind") or row.get("type") or "?", 0) + 1
    return kinds
if __name__ == "__main__":
    print(json.dumps(count(sys.argv[1])))
'''
    tool = tmp_path / 'toy_journal_count.py'
    tool.write_text(source, encoding='utf-8')
    with Watch():
        call = M.Call(tmp_path / 'call', mind=lambda request: ANSWER, fast_text='on')
        try:
            call.say(ASK)
            call.pump(3.0, 0.5)
            journal = call.trace.path
            counted = subprocess.run([sys.executable, '-I', str(tool), str(journal)], capture_output=True, text=True, timeout=60) if journal else None
        finally:
            call.close()
    imports = re.findall(r'^\s*(?:from|import)\s+([\w.]+)', source, re.M)
    return {'counted': json.loads(counted.stdout) if counted is not None and counted.returncode == 0 else None, 'imports': imports}


TOYS = {'hush': toy_hush, 'promise': toy_promise, 'prime': toy_prime, 'toyroad': toy_road, 'census': toy_census}


@pytest.fixture(scope='module')
def blobs():
    return X.owner_blobs(ROOT)


@pytest.fixture(scope='module')
def proof(tmp_path_factory, blobs):
    """Every toy once; an exception is kept to be raised by the test of that toy (a socket that is shut fails its test, the others still run)."""
    out = {}
    for name, run in TOYS.items():
        try:
            out[name] = run(tmp_path_factory.mktemp(name))
        except BaseException as error:      # noqa: BLE001 - re-raised by the test of the toy
            out[name] = error
    return out


def got(proof, name):
    if isinstance(proof[name], BaseException):
        raise proof[name]
    return proof[name]


# ---- one test a mechanic ------------------------------------------------------------------------------------------------------------------------------------------------------------

def test_hush_s1_s2_s3_a_probe_row_a_rule_row_and_an_act_row_change_the_call(proof):
    r = got(proof, 'hush')
    row, requests, cues = r['hushed']
    assert r['before'][0].get('kind') == QUESTION and r['before'][1] == 1, ('the control: with no rows the hushed question is a question and the model is asked', r['before'])
    assert row.get('kind') == QUIET and row.get('reason') == 'toy_hush' and row.get('rule') == 'toy_hush', row
    assert requests == 0 and cues == [], 'a hushed question asks the model nothing and says nothing'
    assert r['notes'] and r['notes'][0][0] == 'hush', 'the new verb of the gate ran (S3)'
    assert r['plain'][0].get('kind') == QUESTION and r['plain'][0].get('rule') != 'toy_hush' and r['plain'][1] == 1, 'a plain question goes the usual way: the row is silent'
    assert r['bodies_same'], '_act and _judge are the same code with the rows in'


def test_promise_s4_a_ledger_kind_with_a_ttl_of_the_clock_table_is_held_and_ended_by_the_tick(proof):
    r = got(proof, 'promise')
    assert r['held'] == 'вернуться к смете' and r['still'] == 'вернуться к смете' and r['gone'] is None, r
    assert r['problems'] == [] and r['orphan'], 'a kind with a TTL the clock table does not hold is refused (the row without a clock does not exist)'
    assert 'conversation_ledger.TOY_PROMISE_S' not in str(r['unregistered'])


def test_prime_s5_a_warm_step_runs_in_its_lane_and_a_failing_part_is_a_record(proof):
    r = got(proof, 'prime')
    assert r['records']['toy_prime']['ok'] and r['ready'] == [r['ready'][0]], r['records']
    assert not r['records']['toy_broken']['ok'] and r['records']['toy_broken']['reason'] == 'RuntimeError'
    assert 'toy_prime' not in r['plan'] and {'reference_kb', 'classifier', 'voice', 'ear_model'} <= set(r['plan']), 'the real plan is the one of the product: the toy was no edit of it'


def test_toyroad_s5_a_row_of_roads_answers_the_call_when_the_first_road_is_down(proof):
    r = got(proof, 'toyroad')
    assert r['posted'] and r['posted'][0].startswith('https://toy.invalid/v1'), 'the walk fell through to the toy road'
    assert 'Запасная дорога отвечает' in r['spoken'], r['spoken']


def test_census_s6_a_tool_outside_the_call_reads_the_journal_and_imports_no_owner(proof):
    r = got(proof, 'census')
    assert r['counted'], 'the tool read the journal of a real call'
    assert not [name for name in r['imports'] if name.startswith(('echo_sync', 'tools'))] and set(r['imports']) <= {'json', 'sys', 'pathlib'}


# ---- the locks -----------------------------------------------------------------------------------------------------------------------------------------------------------------------

def test_no_owner_file_changed_while_five_mechanics_were_added(proof, blobs):
    assert set(proof) == set(TOYS)
    assert X.owner_blobs(ROOT) == blobs, 'a blob of controlled_media.py or of a cm_*.py differs after the toys: the mechanics were not added through the sockets'
    assert controlled_media.__file__ and Path(controlled_media.__file__).name == 'controlled_media.py'
    assert (ROOT / 'echo_sync' / 'controlled_media.py').is_file() and 'echo_sync/controlled_media.py' in blobs


def test_the_owner_census_does_not_rise_over_the_toys(proof):
    caps = json.loads((ROOT / 'tools' / 'owner_census_caps.json').read_text(encoding='utf-8'))['families']
    out = C.report(C.load_sites(), C.Tree.from_dir(ROOT))
    now = {family: out['families'][family]['owners'] for family, _ in C.FAMILIES}
    assert {family: count for family, count in now.items() if count > caps[family]} == {}, (now, caps)


def opened(proof):
    """The sockets a toy proved: the toy ran with no exception and saw what the socket gives."""
    sockets = set()
    for name, sockets_of in (('hush', ('S1', 'S2', 'S3')), ('promise', ('S4',)), ('prime', ('S5',)), ('toyroad', ('S5',)), ('census', ('S6',))):
        if not isinstance(proof[name], BaseException):
            sockets |= set(sockets_of)
    return sockets


def test_the_contract_the_catalogue_lands_without_an_owner_edit_is_measured(proof, capsys):
    rows = X.catalog()
    assert len(rows) == 341
    sockets = opened(proof)
    whole = X.share(rows, sockets)
    stats = X.sample_shares(rows, sockets)
    today = X.share(rows, {'S6'})
    with capsys.disabled():
        print('\nEXTENSION CONTRACT: open sockets %s -> %.1f %% of 341 mechanics land with no owner edit (before the slots %.1f %%); a random %d of them: min %.1f %%, mean %.1f %%, %d of %d seeds under 80 %%'
              % (' '.join(sorted(sockets)), 100 * whole, 100 * today, X.SAMPLE, 100 * stats['min'], 100 * stats['mean'], stats['under_target'], stats['seeds']))
    assert abs(today - 39 / 341) < 1e-9, 'the number of the baseline: 39 of 341 (S6 only), 11 %'
    assert whole >= X.TARGET, 'fewer than 80 %% of the catalogue lands with no owner edit: shut sockets are %s' % sorted(set(X.SOCKETS) - sockets)
    assert stats['mean'] >= X.TARGET and X.share(X.sample(rows, 13), sockets) >= X.TARGET, 'a random 30 (seed 13 and the mean of 200 seeds) is not at 80 %'


def test_a_lane_that_adds_a_row_touches_no_owner_and_a_lane_that_edits_an_owner_is_caught(tmp_path):
    def git(*args):
        return subprocess.run(['git', '-C', str(tmp_path), '-c', 'user.name=t', '-c', 'user.email=t@t', *args], capture_output=True, text=True, check=True).stdout
    (tmp_path / 'echo_sync').mkdir()
    for name in ('cm_kind.py', 'cm_probes.py', 'utterance_judge.py', 'controlled_media.py'):
        (tmp_path / 'echo_sync' / name).write_text('ROWS = {}\n', encoding='utf-8')
    git('init', '-q')
    git('add', '-A')
    git('commit', '-qm', 'base')
    base = git('rev-parse', 'HEAD').strip()
    git('checkout', '-qb', 'row')
    (tmp_path / 'echo_sync' / 'cm_probes.py').write_text('ROWS = {"toy": 1}\n', encoding='utf-8')
    git('commit', '-qam', 'a probe row')
    row = git('rev-parse', 'HEAD').strip()
    git('checkout', '-qb', 'owner', base)
    (tmp_path / 'echo_sync' / 'cm_kind.py').write_text('ROWS = {}\nif toy:\n    pass\n', encoding='utf-8')
    git('commit', '-qam', 'a branch in the owner')
    owner = git('rev-parse', 'HEAD').strip()
    assert X.lane_touches(base, row, tmp_path) == []
    assert X.lane_touches(base, owner, tmp_path) == ['echo_sync/cm_kind.py']
    assert X.main(['--lane', base, owner, '--repo', str(tmp_path)]) == 1 and X.main(['--lane', base, row, '--repo', str(tmp_path)]) == 0


def test_the_baseline_before_the_slots_is_11_percent_and_every_socket_is_a_catalogue_row():
    rows = X.catalog()
    counts = X.by_socket(rows)
    assert counts['S6'] == 39 and sum(counts.values()) == 341 and set(counts) == {'S1', 'S2', 'S3', 'S4', 'S5', 'S6', 'S7', 'S8'}
    assert round(100 * X.share(rows, {'S6'})) == 11


# ---- 9c: no field on growth without a consumer -----------------------------------------------------------------------------------------------------------------------------------

CARRIERS = (('echo_sync/utterance_judge.py', 'Rule'), ('echo_sync/utterance_judge.py', 'AcceptCtx'), ('echo_sync/conversation_ledger.py', 'Kind'), ('echo_sync/conversation_ledger.py', 'Rec'),
            ('echo_sync/cm_probes.py', 'Feature'))


def carrier_fields(path, name):
    """The fields of a carrier of a socket (a NamedTuple / dataclass / ``namedtuple`` call), by the AST; None when the carrier is not there (a packet that has not landed)."""
    import ast
    file = ROOT / path
    if not file.is_file():
        return None
    tree = ast.parse(file.read_text(encoding='utf-8'))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == name:
            return [item.target.id for item in node.body if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name)]
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) and getattr(node.value.func, 'id', getattr(node.value.func, 'attr', '')) == 'namedtuple' \
                and getattr(node.targets[0], 'id', '') == name and isinstance(node.value.args[1], ast.Constant):
            return node.value.args[1].value.replace(',', ' ').split()
    return None


def readers():
    """How many times each attribute (or string key) is read in ``echo_sync/`` and in ``tests/``: a field is a consumer's field when somebody reads it."""
    import ast
    from collections import Counter
    count = Counter()
    for path in list((ROOT / 'echo_sync').rglob('*.py')) + list((ROOT / 'tests').glob('*.py')):
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
                count[node.attr] += 1
            elif isinstance(node, ast.Subscript) and isinstance(getattr(node.slice, 'value', None), str):
                count[node.slice.value] += 1
    return count


def test_no_field_of_a_slot_carrier_is_there_for_the_future_without_a_reader():
    """ARCH_ONE §2, 9c: a field of a row (a ``Rule``, a ``Kind``, a ``Feature``), of the judge's context or of a ledger record is written together with the code that reads it. A field nobody reads is a hidden mode of the
    day somebody means to use it, and the owner's rule for the axes of S8 (a second language, a second channel, several owners) is the same: decided first, then the field. The example scenes of a ``Rule`` are read by
    ``tests/test_m1_rules.py``, that is a consumer too."""
    count, unread = readers(), {}
    for path, name in CARRIERS:
        fields = carrier_fields(path, name)
        if fields is None:
            continue
        left = [field for field in fields if count[field] == 0]
        if left:
            unread[name] = left
    assert unread == {}, 'a field with no reader (delete it, or write its consumer in the same commit): %s' % unread


def test_the_carrier_detector_reads_a_dataclass_a_namedtuple_class_and_a_namedtuple_call(tmp_path, monkeypatch):
    (tmp_path / 'echo_sync').mkdir()
    (tmp_path / 'echo_sync' / 'toy.py').write_text('from collections import namedtuple\nfrom typing import NamedTuple\n\n\nclass Row(NamedTuple):\n    name: str\n    spare: int = 0\n\n\nKind = namedtuple("Kind", "ttl binds")\n', encoding='utf-8')
    monkeypatch.setitem(carrier_fields.__globals__, 'ROOT', tmp_path)
    assert carrier_fields('echo_sync/toy.py', 'Row') == ['name', 'spare'] and carrier_fields('echo_sync/toy.py', 'Kind') == ['ttl', 'binds'] and carrier_fields('echo_sync/none.py', 'X') is None
