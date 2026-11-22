import json
import sys
from pathlib import Path

from tools import factory_selffix as F

PY = sys.executable
GOOD_TEST = "from tools.mod import f\n\ndef test_f():\n    assert f() == 2\n"
GOOD_VARIATION = "from tools.mod import f\n\ndef test_f_again():\n    assert f() + 1 == 3\n"


def rows(n, reason='edit failed', detail='SEARCH not found', ts='2026-11-20T10:00:00'):
    return [{'ts': ts, 'task_id': f't{i}', 'reason': reason, 'reason_detail': detail} for i in range(n)]


def make_repo(tmp_path):
    (tmp_path / 'tools').mkdir(parents=True)
    (tmp_path / 'tools' / '__init__.py').write_text('')
    (tmp_path / 'tools' / 'mod.py').write_text('def f():\n    return 1\n')
    (tmp_path / 'tests').mkdir()
    return tmp_path


def answer(**kw):
    d = {'title': 'fix', 'touch_files': ['tools/mod.py'], 'test_file': 'tests/test_selffix_a.py',
         'test_code': GOOD_TEST, 'variation_code': GOOD_VARIATION,
         'goal': 'Change f in tools/mod.py so that it returns 2 instead of 1.'}
    d.update(kw)
    return 'Here you go:\n```json\n' + json.dumps(d) + '\n```'


def test_due_counts_since_ledger_and_skips_open():
    r = rows(3)
    assert [c for c, _ in F.due(r, {})] == ['search-miss']
    assert F.due(r, {'search-miss': {'at': '2026-11-20T11:00:00', 'status': 'skipped'}}) == []
    assert F.due(r, {'search-miss': {'at': '2026-11-20T09:00:00', 'status': 'open'}}) == []
    assert F.due(rows(1), {}) == []


def test_gate_red_and_token_waste_become_selffix_tasks():
    """<id> audit 20.11: gate-red (212 rows) and token-waste (27) were left out of WHERE and never became tasks."""
    r = rows(5, 'gate: rc=1', 'tests/test_x.py::test_a AssertionError: 1 != 2') + rows(3, 'context_too_large', '')
    assert [c for c, _ in F.due(r, {})] == ['gate-red', 'token-waste']
    assert 'tools/factory_gate.py' in F.WHERE['gate-red'] and 'tools/factory_context.py' in F.WHERE['token-waste']


def test_gate_red_prompt_allows_skip_and_names_factory_side(tmp_path):
    info = {'n': 5, 'tasks': ['t1'], 'examples': ['gate: rc=1: AssertionError: 1 != 2']}
    prompt = F.head_prompt('gate-red', info, {})
    assert F.SCOPE['gate-red'] in prompt and '"skip"' in prompt and 'product' in F.SCOPE['gate-red']
    root, sd = _setup(tmp_path, 'gate-red')
    led = {}
    rep = F.run(rows(3, 'gate: rc=1', 'AssertionError'), led, ask=lambda p: '{"skip": "a product defect"}',
                repo_root=root, src_root=root, self_dir=sd, base_sha='b', python=PY,
                now_iso='2026-11-20T12:00:00', stamp='s1')
    assert rep == {'cls': 'gate-red', 'status': 'skipped', 'why': 'a product defect'}
    assert led['gate-red']['status'] == 'skipped'


def test_a_skipped_class_waits_skip_hold():
    """A skipped class is not asked again every hour (gate-red brings 5-39 rows an hour and would take every turn)."""
    led = {'gate-red': {'at': '2026-11-20T12:00:00', 'status': 'skipped'}}
    r = rows(5, 'gate: rc=1', 'AssertionError', ts='2026-11-20T12:30:00')
    assert F.due(r, led, now_iso='2026-11-20T13:00:00') == []
    assert [c for c, _ in F.due(r, led, now_iso='2026-11-21T12:01:00')] == ['gate-red']


def test_due_most_frequent_first():
    r = rows(2) + rows(4, 'no-block', 'had no SEARCH/REPLACE edit block')
    assert [c for c, _ in F.due(r, {})] == ['no-edit-block', 'search-miss']


def test_parse_good_and_skip(tmp_path):
    root = make_repo(tmp_path)
    p = F.parse(answer(), root)
    assert p['touch_files'] == ['tools/mod.py'] and p['test_file'] == 'tests/test_selffix_a.py'
    assert F.parse('{"skip": "not a defect"}', root) == {'skip': 'not a defect'}


def test_parse_refuses_bad(tmp_path):
    root = make_repo(tmp_path)
    assert F.parse('no json', root) is None
    assert F.parse(answer(touch_files=['tools/nope.py']), root) is None
    assert F.parse(answer(touch_files=['tests/x.py']), root) is None
    assert F.parse(answer(touch_files=[]), root) is None
    assert F.parse(answer(test_file='tests/test_other.py'), root) is None
    (root / 'tests' / 'test_selffix_a.py').write_text('')
    assert F.parse(answer(), root) is None
    (root / 'tests' / 'test_selffix_a.py').unlink()
    assert F.parse(answer(test_code='def test_x(:\n'), root) is None
    assert F.parse(answer(test_code='def test_x():\n    assert 0\n'), root) is None
    assert F.parse(answer(goal='short'), root) is None
    assert F.parse(answer(title=''), root) is None


def test_parse_requires_variation(tmp_path):
    """A closed class keeps a NEW example of the same error green: no variation, no task."""
    root = make_repo(tmp_path)
    assert F.parse(answer(variation_code=None), root) is None
    assert F.parse(answer(variation_code='def test_v():\n    assert 1\n'), root) is None     # imports no tools
    assert F.parse(answer(variation_code='def test_v(:\n'), root) is None
    p = F.parse(answer(), root)
    assert p['variation_file'] == 'tests/test_selffix_a_variation.py' and p['variation_code'] == GOOD_VARIATION
    (root / 'tests' / 'test_selffix_a_variation.py').write_text('')
    assert F.parse(answer(), root) is None


def test_materialize_writes_both_tests(tmp_path):
    root = make_repo(tmp_path / 'repo')
    sd = tmp_path / 'self'
    sd.mkdir(parents=True)
    path = F.materialize(F.parse(answer(), root), root, sd, 's1', 'abc123', 'search-miss')
    tree = sd / 'src_fx_search-miss_s1' / 'tests'
    assert (tree / 'test_selffix_a_variation.py').read_text(encoding='utf-8') == GOOD_VARIATION
    assert json.loads(path.read_text(encoding='utf-8'))[0]['tests'] == ['tests/test_selffix_a.py',
                                                                         'tests/test_selffix_a_variation.py']


def _closed_case(tmp_path, status='REVIEW', tests_in_source=True):
    root = make_repo(tmp_path / 'src')
    sd = tmp_path / 'self'
    sd.mkdir(parents=True)
    tests = ['tests/test_selffix_a.py', 'tests/test_selffix_a_variation.py']
    if tests_in_source:
        (root / tests[0]).write_text('from tools.mod import f\n\ndef test_f():\n    assert f() == 1\n')
        (root / tests[1]).write_text('from tools.mod import f\n\ndef test_v():\n    assert f() + 1 == 2\n')
    (sd / 'state_plan_fx_a.json').write_text(json.dumps({'tasks': {'fx_a': {'status': status}}}), encoding='utf-8')
    ledger = {'search-miss': {'at': '2026-11-20T09:00:00', 'status': 'open', 'plan': 'plan_fx_a.json',
                              'tries': 0, 'tests': tests}}
    return root, sd, ledger


def test_open_entry_closes_when_its_tests_are_in_the_source(tmp_path):
    root, sd, ledger = _closed_case(tmp_path)
    assert F.due(rows(3), ledger, self_dir=sd, now_iso='2026-11-20T12:00:00', repo_root=root) == []
    assert ledger['search-miss']['status'] == 'closed' and ledger['search-miss']['closed_at'] == '2026-11-20T12:00:00'
    root2, sd2, ledger2 = _closed_case(tmp_path / 'b', tests_in_source=False)     # a candidate not yet accepted
    assert F.due(rows(3), ledger2, self_dir=sd2, now_iso='2026-11-20T12:00:00', repo_root=root2) == []
    assert ledger2['search-miss']['status'] == 'open'


def test_closed_class_reopens_on_recurrence(tmp_path):
    root, sd, ledger = _closed_case(tmp_path)
    F.due([], ledger, self_dir=sd, now_iso='2026-11-20T12:00:00', repo_root=root)
    assert F.due(rows(1, ts='2026-11-20T13:00:00'), ledger, now_iso='2026-11-20T13:30:00') == []
    assert ledger['search-miss']['status'] == 'closed'
    got = F.due(rows(2, ts='2026-11-20T13:00:00'), ledger, now_iso='2026-11-20T13:30:00')
    assert [c for c, _ in got] == ['search-miss'] and ledger['search-miss']['status'] == 'reopened'
    assert ledger['search-miss']['reopened_at'] == '2026-11-20T13:30:00' and ledger['search-miss']['tries'] == 0


def _check_closed(tmp_path, variation):
    root, sd, ledger = _closed_case(tmp_path)
    (root / 'tests' / 'test_selffix_a_variation.py').write_text(variation)
    F.due([], ledger, self_dir=sd, now_iso='2026-11-20T12:00:00', repo_root=root)
    asked = []
    rep = F.run([], ledger, ask=lambda p: asked.append(p) or '{"skip": "x"}', repo_root=root, src_root=root,
                self_dir=sd, base_sha='b', python=PY, now_iso='2026-11-20T14:00:00', stamp='s2')
    return ledger, rep, asked


def test_closed_class_reopens_when_variation_turns_red(tmp_path):
    red = 'from tools.mod import f\n\ndef test_v():\n    assert f() == 2\n'
    root, sd, ledger = _closed_case(tmp_path / 'direct')
    (root / 'tests' / 'test_selffix_a_variation.py').write_text(red)
    F.due([], ledger, self_dir=sd, now_iso='2026-11-20T12:00:00', repo_root=root)
    assert F.check_closed(ledger, root, PY, '2026-11-20T14:00:00') == 'search-miss'
    entry = ledger['search-miss']
    assert entry['status'] == 'reopened' and entry['checked_at'] == '2026-11-20T14:00:00'
    assert 'test_selffix_a_variation' in entry['why'] and len(entry['why']) <= 300
    ledger, rep, asked = _check_closed(tmp_path, red)
    # reopened and due at once (n=0): the head gets the red lines as an example
    assert rep['cls'] == 'search-miss' and asked and 'test_selffix_a_variation' in asked[0]
    assert ledger['search-miss']['status'] == 'skipped'
    assert F.still_green({'tests': ['tests/test_selffix_a_variation.py']}, tmp_path / 'src', PY)[0] is False
    assert F.still_green({'tests': ['tests/test_selffix_a.py']}, tmp_path / 'src', PY)[0] is True


def test_closed_green_stays_closed(tmp_path):
    ledger, rep, asked = _check_closed(tmp_path, 'from tools.mod import f\n\ndef test_v():\n    assert f() == 1\n')
    assert rep == {'status': 'none'} and not asked
    assert ledger['search-miss']['status'] == 'closed' and ledger['search-miss']['checked_at'] == '2026-11-20T14:00:00'


def test_ledger_file_round_trip_and_merge(tmp_path):
    """The registry lives in the factory's self dir: the old per-project entries move in once; a concurrent writer's
    change of another class is kept."""
    assert F.load_ledger(tmp_path) == {}
    led = F.load_ledger(tmp_path, seed={'cannot': {'status': 'open'}})
    before = F.load_ledger(tmp_path)
    led['search-miss'] = {'status': 'skipped'}
    F.save_ledger(tmp_path, {'gate-red': {'status': 'skipped'}}, {})          # another project's loop meanwhile
    F.save_ledger(tmp_path, led, before)
    assert F.load_ledger(tmp_path) == {'cannot': {'status': 'open'}, 'search-miss': {'status': 'skipped'},
                                       'gate-red': {'status': 'skipped'}}
    assert not list(tmp_path.glob('*.tmp'))


def test_materialize(tmp_path):
    root = make_repo(tmp_path / 'repo')
    plan = F.parse(answer(), root)
    sd = tmp_path / 'self'
    sd.mkdir(parents=True)
    path = F.materialize(plan, root, sd, 's1', 'abc123', 'search-miss')
    assert path.name == 'plan_fx_search-miss_s1.json'
    # utf-8 reads: materialize writes utf-8; a locale (cp1251) read mangled the Cyrillic profile path of tmp_path
    assert (sd / 'src_fx_search-miss_s1' / 'tests' / 'test_selffix_a.py').read_text(encoding='utf-8') == GOOD_TEST
    data = json.loads(path.read_text(encoding='utf-8'))
    assert data[0]['id'] == 'fx_search-miss_s1' and data[0]['tests'] == ['tests/test_selffix_a.py',
                                                                         'tests/test_selffix_a_variation.py']
    ptr = (sd / 'src_plan_fx_' 'search-miss_s1.txt').read_text(encoding='utf-8').split()
    assert ptr == [str(sd / 'src_fx_search-miss_s1'), 'abc123']


def test_red_on_base(tmp_path):
    root = make_repo(tmp_path)
    (root / 'tests' / 'test_red.py').write_text(GOOD_TEST)
    (root / 'tests' / 'test_imp.py').write_text('from tools.nothing import g\n\ndef test_g():\n    assert g()\n')
    ok, _ = F.red_on_base(root, 'tests/test_red.py', PY)
    assert ok is True
    ok, _ = F.red_on_base(root, 'tests/test_imp.py', PY)
    assert ok is False


def _setup(tmp_path, cls='search-miss'):
    root = make_repo(tmp_path / 'repo')
    for rel in F.WHERE[cls]:
        (root / rel).write_text('def g():\n    return 1\n')
    sd = tmp_path / 'self'
    sd.mkdir(parents=True)
    return root, sd


def _run(tmp_path, text, ledger):
    root, sd = _setup(tmp_path)
    return F.run(rows(3), ledger, ask=lambda p: text, repo_root=root, src_root=root, self_dir=sd, base_sha='b',
                 python=PY, now_iso='2026-11-20T12:00:00', stamp='s1')


def test_run_open_skipped_invalid(tmp_path):
    led = {}
    rep = _run(tmp_path / 'a', answer(), led)
    assert rep['status'] == 'open' and led['search-miss']['status'] == 'open' and led['search-miss']['plan'] == rep['plan']
    assert led['search-miss']['tests'] == ['tests/test_selffix_a.py', 'tests/test_selffix_a_variation.py']
    led = {}
    green_variation = answer(variation_code='from tools.mod import f\n\ndef test_v():\n    assert f() == 1\n')
    assert _run(tmp_path / 'e', green_variation, led)['status'] == 'invalid'        # the variation is red too
    led = {}
    assert _run(tmp_path / 'b', '{"skip": "model quality"}', led)['status'] == 'skipped'
    assert led['search-miss']['status'] == 'skipped'
    led = {}
    assert _run(tmp_path / 'c', 'garbage', led)['status'] == 'invalid'
    assert led['search-miss']['status'] == 'invalid'
    led = {}
    green = answer(test_code='from tools.mod import f\n\ndef test_f():\n    assert f() == 1\n')
    rep = _run(tmp_path / 'd', green, led)
    assert rep['status'] == 'invalid' and not (tmp_path / 'd' / 'self' / 'src_fx_search-miss_s1').exists()


def test_an_invalid_answer_holds_the_class_so_others_get_turns():
    """Critic 20.11: gate-red is the most frequent class; an invalid answer was asked again every hour, the others
    never got a turn."""
    led = {'gate-red': {'at': '2026-11-20T12:00:00', 'status': 'invalid', 'tries': 0}}
    r = rows(9, 'gate: rc=1', 'AssertionError', ts='2026-11-20T12:30:00') + rows(2, ts='2026-11-20T12:30:00')
    assert [c for c, _ in F.due(r, led, now_iso='2026-11-20T13:00:00')] == ['search-miss']
    assert [c for c, _ in F.due(r, led, now_iso='2026-11-20T18:01:00')] == ['gate-red', 'search-miss']


def test_closing_resets_tries_and_a_timeout_does_not_reopen(tmp_path, monkeypatch):
    root, sd, ledger = _closed_case(tmp_path)
    ledger['search-miss']['tries'] = 2
    F.due([], ledger, self_dir=sd, now_iso='2026-11-20T12:00:00', repo_root=root)
    assert ledger['search-miss']['status'] == 'closed' and ledger['search-miss']['tries'] == 0
    monkeypatch.setattr(F, '_pytest', lambda *a, **k: (None, 'timeout'))
    assert F.check_closed(ledger, root, PY, '2026-11-20T14:00:00') == 'search-miss'
    assert ledger['search-miss']['status'] == 'closed' and ledger['search-miss']['checked_at'] == '2026-11-20T14:00:00'


def test_private_task_cases_never_reach_the_head(tmp_path):
    """Critic 20.11: the coder's class note took only public tasks' cases, the self-fix head took every task's."""
    root, sd = _setup(tmp_path)
    r = rows(3, detail='SEARCH not found: private words') + [
        {'ts': '2026-11-20T10:00:00', 'task_id': 'pub1', 'reason': 'edit failed', 'reason_detail': 'SEARCH not found: open'}]
    prompts = []
    rep = F.run(r, {}, ask=lambda p: prompts.append(p) or '{"skip": "x"}', repo_root=root, src_root=root,
                self_dir=sd, base_sha='b', python=PY, now_iso='2026-11-20T12:00:00', stamp='s1', public={'pub1'})
    assert rep['status'] == 'skipped'
    assert 'SEARCH not found: open' in prompts[0] and 'private words' not in prompts[0]
    assert 'tasks: pub1)' in prompts[0] and 't0' not in prompts[0].split('Examples:')[0]
