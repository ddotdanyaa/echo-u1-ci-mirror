import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import sys
import time

import pytest

from tools import agent_factory as F

# Values the scrubbers must handle are assembled at run time (same bytes, no literal in the source).
DRIVE = 'C' + ':'
WINHOME = DRIVE + '\\' + 'Users' + '\\'
FAKE_KEY = 'AI' + 'zaSyA1234567890' + 'abcdefghijkl' + 'mnopqrstuv123'


@pytest.fixture(autouse=True)
def _kilo_engine(monkeypatch):
    """These rigs fake the Kilo agent loop through model_attempt; the light engine (one REST request) has its
    own tests in tests/test_factory_light.py."""
    from tools import agent_factory_runner as runner
    monkeypatch.setattr(runner, 'engine_for', lambda role, task: 'kilo')


def task(**extra):
    row = dict(id='T1', title='Repair arithmetic', touch_files=['calc.py'],
               read_files=[], tests=['tests/test_calc.py'], privacy_safe=True,
               estimated_tokens=100)
    row.update(extra)
    return F.read_plan([row])['T1']


def test_opus_only_is_not_dispatched_to_google():
    t = task(only_opus=True)
    assert F.ready({t.id: t}, F.initial_state({t.id: t})) == []


def test_context_ast_retains_decorators_and_direct_dependency_signature():
    from tools.factory_context import slice_source
    source = ('import math\ndef helper(x):\n    return x\n'
              '@staticmethod\ndef target(x):\n    return helper(x)\ndef irrelevant():\n    return 999\n')
    result = slice_source('x.py', source, 'target')
    assert '@staticmethod' in result and 'def target' in result
    assert 'def helper(x)' in result and '999' not in result


def test_context_fallback_does_not_parse_yaml_as_python():
    from tools.factory_context import slice_source
    assert 'value: 42' in slice_source('x.yaml', 'header:\nvalue: 42\nend: true', '2:2')


def test_context_over_budget_refuses_instead_of_silent_truncation():
    from tools.factory_context import packet
    with pytest.raises(F.InvalidPlan, match='budget'):
        packet({'a.md': b'x' * 200}, {}, max_tokens=100)


def test_shared_quota_group_cools_both_keys_and_falls_back():
    from tools.factory_channels import choose, reserve, cool
    channels = [dict(id='a', group='project', model='google/small', key_env='KEY_A', tpm=1000, rpd=10),
                dict(id='b', group='project', model='google/small', key_env='KEY_B', tpm=1000, rpd=10),
                dict(id='c', group='reserve', model='openrouter/x:free', key_env='KEY_C', tpm=1000, rpd=10)]
    state = {}
    env = dict(KEY_A='a', KEY_B='b', KEY_C='c')
    first = choose(channels, state, 100, env, now=100)
    reserve(state, first, 100, now=100)
    cool(state, first, now=100)
    assert choose(channels, state, 100, env, now=101)['id'] == 'c'


def test_quota_reservation_survives_json_and_enforces_daily_limit():
    from tools.factory_channels import choose, reserve
    channel = dict(id='a', group='p', model='google/x', key_env='KEY', tpm=1000, rpd=1)
    state = {}
    reserve(state, channel, 100, now=100)
    state = json.loads(json.dumps(state))
    with pytest.raises(F.InvalidPlan, match='channels'):
        choose([channel], state, 100, dict(KEY='value'), now=200)


def test_node_entrypoint_is_argv_not_cmd(tmp_path):
    from tools.factory_process import kilo_argv
    entry = tmp_path / 'kilo'
    entry.write_text('#!/usr/bin/env node\n')
    args = kilo_argv(entry=str(entry), node=sys.executable)
    assert args == [sys.executable, str(entry.resolve())]


def test_review_is_separate_readonly_and_requires_affirmative_json(tmp_path):
    from tools.agent_factory_runner import prepare, review_candidate
    root = tmp_path / 'project'
    root.mkdir()
    (root / 'calc.py').write_text('def add(a,b): return a+b\n')
    (root / 'tests').mkdir()
    (root / 'tests/test_calc.py').write_text('def test_ok(): assert True\n')
    t = task()
    calls = []
    def invoke(reviewer, directory, model, **kwargs):
        assert reviewer.touch_files == ()
        assert json.loads((directory / 'kilo.jsonc').read_text())['permission']['edit'] == {'*': 'deny'}
        calls.append(model)
        return 0, json.dumps(dict(type='text', part=dict(text='{"approved":true}'))).encode(), b''
    approved, reasons = review_candidate(t, root, 'google/reviewer', invoke)
    assert approved is True and reasons == []
    assert calls == ['google/reviewer']


def test_review_rejects_mutation_even_with_positive_verdict(tmp_path):
    from tools.agent_factory_runner import review_candidate
    root = tmp_path / 'project'
    root.mkdir()
    (root / 'calc.py').write_text('value=1\n')
    (root / 'tests').mkdir()
    (root / 'tests/test_calc.py').write_text('def test_ok(): assert True\n')
    def invoke(reviewer, directory, model, **kwargs):
        (directory / 'calc.py').write_text('value=2\n')
        return 0, b'{"type":"text","part":{"text":"{\\"approved\\":true}"}}', b''
    with pytest.raises(F.InvalidPlan, match='changed'):
        review_candidate(task(), root, 'google/reviewer', invoke)


def test_kilo_event_metadata_does_not_include_tool_arguments():
    from tools.agent_factory_runner import event_summary
    events = [dict(type='tool_use', part=dict(input='private-marker')),
              dict(type='step_finish', part=dict(reason='stop', tokens=dict(input=20, output=4)))]
    result = event_summary('\n'.join(map(json.dumps, events)).encode())
    assert result['input_tokens'] == 20 and result['output_tokens'] == 4
    assert 'private-marker' not in str(result)


def test_multiple_provider_turns_are_reserved_together():
    from tools.factory_channels import choose, reserve, ChannelUnavailable
    channel = dict(id='a', group='p', model='google/x', key_env='KEY', tpm=10000, rpd=5)
    state = {}
    reserve(state, channel, 1000, now=100, requests=5)
    with pytest.raises(ChannelUnavailable):
        choose([channel], state, 1000, dict(KEY='x'), now=101, requests=5)


def test_native_kilo_also_uses_owned_process(tmp_path, monkeypatch):
    from tools import agent_factory_runner as w
    monkeypatch.delenv('FACTORY_KILO_ENTRY', raising=False)
    monkeypatch.setattr(w.shutil, 'which', lambda name: 'kilo.exe')
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, b'', b'')
    monkeypatch.setattr(w, 'run_owned', run)
    w.model_attempt(task(), tmp_path, 'google/x', 10)
    assert calls and calls[0][0] == 'kilo.exe'




def test_systemroot_is_preserved_case_insensitively_for_child(tmp_path, monkeypatch):
    from tools import agent_factory_runner as w
    monkeypatch.setenv('SYSTEMROOT', DRIVE + r'\Windows')
    monkeypatch.delenv('FACTORY_KILO_ENTRY', raising=False)
    monkeypatch.setattr(w.shutil, 'which', lambda name: None)
    seen = []
    def run(args, **kwargs):
        seen.append(kwargs['env'])
        return subprocess.CompletedProcess(args, 0, b'', b'')
    monkeypatch.setattr(w.subprocess, 'run', run)
    w.model_attempt(task(), tmp_path, 'google/x', 10)
    assert seen[0]['SYSTEMROOT'] == DRIVE + r'\Windows'


def test_only_dependencies_are_sliced_and_originals_remain_for_pytest(tmp_path):
    from tools.agent_factory_runner import prepare, worker_policy
    root = tmp_path / 'root'
    (root / 'tests').mkdir(parents=True)
    (root / 'calc.py').write_text('from dep import helper\ndef add(a,b): return helper(a,b)\n')
    source = 'def helper(a,b): return a+b\ndef another(): return 99\n'
    (root / 'dep.py').write_text(source)
    (root / 'tests/test_calc.py').write_text('def test_ok(): assert True\n')
    t = task(read_files=['dep.py'], context_targets={'dep.py': 'helper'})
    stage = tmp_path / 'stage'
    prepare(root, t, stage)
    assert (stage / 'dep.py').read_text() == source
    assert worker_policy(t)['permission']['read'].get('dep.py', 'deny') == 'deny'


def test_policy_matches_kilo_absolute_paths():
    """Kilo matches rules against absolute paths, so bare names would hit `*: deny`."""
    from tools.agent_factory_runner import worker_policy
    t = task(read_files=['dep.py'])
    perm = worker_policy(t)['permission']
    assert perm['edit']['**/calc.py'] == 'allow'
    assert perm['edit']['*'] == 'deny'
    assert perm['read']['**/calc.py'] == 'allow'
    assert perm['read']['**/tests/test_calc.py'] == 'allow'
    assert perm['read'].get('**/dep.py', 'deny') == 'deny'
    assert set(perm['edit']) == {'*', '**/calc.py'}


def test_three_strikes_are_configurable():
    t = task()
    tasks = {t.id: t}
    s = F.initial_state(tasks)
    seen = []
    for k in range(3):
        token = F.acquire(tasks, s, 'T1', now=k)
        seen.append(F.settle(s, 'T1', token, tests_ok=False, evidence='a' * 64, max_attempts=3))
    assert seen == ['READY', 'READY', 'FAILED']






def test_cli_passes_strikes_and_explicit_model_budget(tmp_path, monkeypatch):
    from tools import agent_factory_runner as w
    seen = {}
    def fake_once(**kwargs):
        seen.update(kwargs)
        return {'status': 'IDLE'}
    monkeypatch.setattr(w, 'once', fake_once)
    base = ['--root', str(tmp_path / 'src'), '--plan', str(tmp_path / 'p.json'),
            '--checkpoint', str(tmp_path / 's.json'), '--staging', str(tmp_path / 'stage'),
            '--small-model', 'google/x', '--large-model', 'google/x']
    assert w.main(base + ['--max-attempts', '3', '--max-model-calls', '300']) == 0
    assert seen['max_attempts'] == 3 and seen['max_model_calls'] == 300
    with pytest.raises(SystemExit):
        w.main(base + ['--max-attempts', '0'])




@pytest.mark.skipif(os.name != 'nt', reason='Windows Job Object contract')
def test_windows_job_kills_grandchild_on_timeout(tmp_path):
    from tools.factory_process import run_owned
    pidfile = tmp_path / 'child.pid'
    child = 'import time; time.sleep(60)'
    parent = ('import subprocess,sys,time,pathlib; '
              f'p=subprocess.Popen([sys.executable,"-c",{child!r}]); '
              f'pathlib.Path({str(pidfile)!r}).write_text(str(p.pid)); time.sleep(60)')
    with pytest.raises(subprocess.TimeoutExpired):
        run_owned([sys.executable, '-c', parent], cwd=tmp_path,
                  env=dict(os.environ), timeout=2)
    assert pidfile.exists()
    import ctypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.restype = ctypes.c_void_p
    handle = kernel.OpenProcess(0x1000, False, int(pidfile.read_text()))
    if handle:
        code = ctypes.c_ulong()
        kernel.GetExitCodeProcess(ctypes.c_void_p(handle), ctypes.byref(code))
        kernel.CloseHandle(ctypes.c_void_p(handle))
        assert code.value != 259, 'grandchild is still running'


# =====================================================================================
# Package B round 2: runner on factory_gate, structural errors, feedback, unit_test, neighbours.
# Rewritten (contract K-B): the old once() tests assumed (a) coder and reviewer may be the same
# model, (b) a second coder attempt inside one pass, (c) the review returned a bool. The new
# contract: reviewer is another model, one coder call per pass (the next pass gets the feedback
# and the previous diff), review returns (approved, reasons).
# =====================================================================================
from tools import factory_gate as G
from tools import factory_channels as C

TWO_CHANNELS = [dict(id='c1', group='p', model='google/x', key_env='KEY', tpm=100000, rpd=100, verified=True),
                dict(id='c2', group='p', model='google/y', key_env='KEY', tpm=100000, rpd=100, verified=True)]
# the rig's default: a coder and a FULL chain of two critics, each another model (a short chain never approves)
THREE_CHANNELS = TWO_CHANNELS + [dict(id='c3', group='p3', model='google/z', key_env='KEY', tpm=100000, rpd=100,
                                      verified=True)]


def ev(*events):
    return '\n'.join(json.dumps(e) for e in events).encode()


def finish(i=9000, o=500):
    return dict(type='step_finish', part=dict(reason='stop', tokens=dict(input=i, output=o)))


CALC_LINE = 'def test_add(): assert add(2,3)==5'      # a real line of the rig's code-task test
NEW_LINE = 'def test_new(): assert 1 == 2'              # a real line of the rig's unit_test candidate


def approval_json(reasons=(), line=CALC_LINE) -> str:
    """The same approval as plain JSON text, for the light engine's HTTP answers."""
    return json.dumps(dict(approved=True, reasons=list(reasons), defect_assert_line=line,
                           fix_changes_value='add returns 5 for (2, 3), the base returned -1', independent_asserts=[]))


def verdict(approved, reasons=(), line=CALC_LINE):
    """A critic answer. An approval answers the rubric the runner asks for: it cites a real line of the test it sees."""
    data = dict(approved=approved, reasons=list(reasons))
    if approved:
        data.update(defect_assert_line=line, fix_changes_value='add returns 5 for (2, 3), the base returned -1',
                    independent_asserts=[])
    text = json.dumps(data)
    return ev(dict(type='text', part=dict(text=text)), finish(4000, 100))


def error_out(status=None, name='APIError', message='boom', body=None):
    data = {'message': message}
    if status is not None:
        data['statusCode'] = status
    if body is not None:
        data['responseBody'] = json.dumps(body)
    return ev(dict(type='error', error=dict(name=name, data=data)))


def _refuse_network(*_a, **_k):
    raise AssertionError('a test reached the network through the light engine')


def gr(ok, collected=1, diag='', **extra):
    fields = dict(rc=0 if ok else 1, collected=collected, passed=collected if ok else 0,
                  failed=0 if ok else collected, errors=0, skipped=0, junit_ok=True, diag=diag, env_reason='',
                  failed_ids=() if ok else ('t::red',))
    fields.update(extra)
    return G.GateResult(**fields)


class Rig:
    def __init__(self, tmp_path, monkeypatch, *, kind='code', channels=True, max_attempts=3, **plan_extra):
        from tools import agent_factory_runner as w
        self.w, self.tmp, self.mp = w, tmp_path, monkeypatch
        self.root = tmp_path / 'source'
        (self.root / 'tests').mkdir(parents=True)
        (self.root / 'calc.py').write_text('def add(a,b): return a-b\n')
        (self.root / 'tests/test_calc.py').write_text('from calc import add\ndef test_add(): assert add(2,3)==5\n')
        row = dict(id='T1', backlog_id='BL1', title='Fix sum', touch_files=['calc.py'],
                   tests=['tests/test_calc.py'], privacy_safe=True)
        if kind == 'unit_test':
            row.update(kind='unit_test', touch_files=['tests/test_new.py'], tests=['tests/test_new.py'])
        row.update(plan_extra)
        self.plan = tmp_path / 'plan.json'
        self.plan.write_text(json.dumps([row]))
        self.state_path = tmp_path / 'state.json'
        cfg = tmp_path / 'channels.json'
        cfg.write_text(json.dumps(dict(channels=THREE_CHANNELS)))
        self.channels = cfg if channels else None
        monkeypatch.setenv('KEY', 'synthetic')
        monkeypatch.setenv('GOOGLE_GENERATIVE_AI_API_KEY', 'synthetic')
        monkeypatch.setattr(w.shutil, 'which', lambda _: 'kilo')
        self.sleeps = []
        monkeypatch.setattr(w.time, 'sleep', lambda s: self.sleeps.append(s))
        monkeypatch.setattr(w, 'neighbor_tests', lambda root, task: [])
        self.prompts, self.models, self.runs = [], [], []
        self.gate_workdirs = []
        self.gate_waits = []
        self.coder_script, self.review_script = [], []
        self.max_attempts = max_attempts
        self.marker = True
        monkeypatch.setattr(w, 'profile_names', lambda: ())   # tmp_path lives under the profile; one test re-enables it
        self.kind = kind
        monkeypatch.setattr(w, 'model_attempt', self._model)
        monkeypatch.setattr(w, '_light_post', _refuse_network)     # light_rig() installs its own provider
        monkeypatch.setattr(w.gate, 'run_tests', self._run_tests)
        self.run_tests_fn = self._default_run_tests

    # fake model: scripted outputs, default = write a correct candidate / approve
    def _model(self, t, directory, name, timeout, **kwargs):
        self.models.append((bool(t.touch_files), name))
        self.prompts.append(kwargs.get('prompt_override', ''))
        if t.touch_files:
            script = self.coder_script.pop(0) if self.coder_script else 'good'
            if callable(script):
                return script(directory)
            if isinstance(script, tuple):
                return script
            body = {'good': 'def add(a,b): return a+b\n', 'bad': 'def add(a,b): return a*b\n'}.get(script, script)
            if self.kind == 'unit_test':
                (directory / 'tests').mkdir(exist_ok=True)
                marker = '# factory-backlog-id: BL1\n' if self.marker else ''
                (directory / 'tests/test_new.py').write_text(marker + 'def test_new(): assert 1 == 2\n')
            else:
                (directory / 'calc.py').write_text(body)
            return 0, ev(finish()), b''
        script = self.review_script.pop(0) if self.review_script else verdict(
            True, line=NEW_LINE if self.kind == 'unit_test' else CALC_LINE)
        return (0, script, b'') if isinstance(script, bytes) else script

    def _default_run_tests(self, root, tests, timeout_s):
        if self.kind == 'unit_test':
            return gr(False, diag='test_new fails on the old code', failed_ids=('tests.test_new::test_new',))
        return gr('a+b' in (Path(root) / 'calc.py').read_text(), diag='assert add(2,3)==5 -> got -1')

    def _run_tests(self, root, tests, timeout_s, workdir=None, wait_s=None, hung=(), trace=(), touched=None):
        self.runs.append((str(root), tuple(tests), timeout_s))
        self.gate_workdirs.append(workdir)
        self.gate_waits.append(wait_s)
        return self.run_tests_fn(root, tests, timeout_s)

    def once(self, **extra):
        options = dict(root=self.root, plan=self.plan, checkpoint=self.state_path, staging=self.tmp / 'stage',
                       small_model='google/x', large_model='google/x', review_model='google/y',
                       channel_config=self.channels, execute=True, acknowledge=True,
                       max_attempts=self.max_attempts)
        options.update(extra)
        return self.w.once(**options)

    def state(self):
        # utf-8, never the locale's code page: the runner writes utf-8, and without PYTHONUTF8 a cp1251 read mangled a
        # work-dir path under a Cyrillic profile, so edit_state() wrote it back and the pending candidate was dropped
        return json.loads(self.state_path.read_text(encoding='utf-8'))

    def edit_state(self, fn):
        state = self.state()
        fn(state)
        self.state_path.write_text(json.dumps(state), encoding='utf-8')

    def ready_again(self):
        def fn(s):
            s['tasks']['T1']['not_before'] = 0
            s['channel_quotas'] = {}
        self.edit_state(fn)


@pytest.fixture
def rig(tmp_path, monkeypatch):
    return Rig(tmp_path, monkeypatch)


def test_happy_path_reports_the_pass_in_one_json(rig):
    result = rig.once()
    assert result['status'] == 'REVIEW' and result['cross_review'] is True
    assert result['task_id'] == 'T1' and result['task'] == 'T1' and result['backlog_id'] == 'BL1'
    assert [c['role'] for c in result['calls']] == ['code', 'review', 'review']     # a full chain: two critics
    first = result['calls'][0]
    for key in ('attempt', 'channel', 'model', 'reserved_tokens', 'actual_tokens', 'dur_s', 'error_class',
                'provider_error'):
        assert key in first
    assert first['channel'] == 'c1' and result['calls'][1]['model'] == 'google/y'
    assert result['calls'][2]['model'] == 'google/z' and result['critics'] == ['google/y', 'google/z']
    assert result['tests'] == dict(collected=1, passed=1, failed=0, skipped=0)
    assert set(result['stages']) >= {'red_before_s', 'code_s', 'gate_s', 'review_s'}
    assert result['reason'] is None and 'base_sha' in result
    json.dumps(result)


def test_reservation_follows_prompt_length_and_is_reconciled_with_the_fact(rig):
    result = rig.once()
    call = result['calls'][0]
    assert call['reserved_tokens'] == C.estimate_tokens(len(rig.prompts[0]))
    assert call['reserved_tokens'] < 40000  # the old (budget+8192)*5 formula gave 185 960
    assert call['actual_tokens'] == 9500
    minute = rig.state()['channel_quotas']['p']['minute']
    assert [n for _, n in minute][:1] == [9000]  # TPM counts the INPUT only (9000 of 9000+500); the surplus went back


def test_calls_are_charged_when_made_not_when_leased(rig):
    result = rig.once()
    assert rig.state()['model_calls'] == len(result['calls']) == 3


def test_rate_limit_text_in_a_successful_answer_gives_no_cooling_and_no_strike(rig):
    chatter = ev(dict(type='text', part=dict(text='note: 429 rate limit RESOURCE_EXHAUSTED 503 API_KEY_INVALID')), finish())
    rig.coder_script = [lambda d: ((d / 'calc.py').write_text('def add(a,b): return a+b\n'), (0, chatter, b''))[1]]
    result = rig.once()
    assert result['status'] == 'REVIEW'
    assert 'cool_until' not in rig.state()['channel_quotas']['p']
    assert not rig.state().get('strikes')


def test_rate_limit_per_minute_cools_for_retry_delay_and_is_not_a_strike(rig):
    body = dict(error=dict(code=429, status='RESOURCE_EXHAUSTED', details=[
        dict(**{'@type': 'type.googleapis.com/google.rpc.QuotaFailure'}, violations=[dict(quotaId='RequestsPerMinute')]),
        {'@type': 'type.googleapis.com/google.rpc.RetryInfo', 'retryDelay': '34s'}]))
    rig.coder_script = [(1, error_out(429, body=body), b'')]
    result = rig.once(max_attempts=1)
    state = rig.state()
    assert result['status'] == 'READY' and state['tasks']['T1']['status'] == 'READY'
    assert not state.get('strikes') and result['reason'] == 'rate_minute'
    assert 25 <= state['channel_quotas']['channel_cool']['c1'] - time.time() <= 36      # one channel, not the project
    assert 'cool_until' not in state['channel_quotas']['p']
    assert result['wait_s'] > 0


def test_rate_limit_per_day_cools_until_the_daily_reset(rig):
    body = dict(error=dict(code=429, details=[dict(**{'@type': 'x.QuotaFailure'}, violations=[dict(quotaId='RequestsPerDay')])]))
    rig.coder_script = [(1, error_out(429, body=body), b'')]
    result = rig.once(max_attempts=1)
    assert result['status'] == 'READY' and result['reason'] == 'rate_day'
    now = time.time()
    left = rig.state()['channel_quotas']['p']['cool_until'] - now
    first_hour = now - C.quota_day('google/x', now)[0] < C.DAY_GRACE_S       # the provider's counter may lag
    expected = C.DAY_GRACE_COOL_S if first_hour else C.seconds_to_daily_reset(now, 'google/x')
    assert abs(left - expected) < 10  # exactly until the Pacific midnight, not a fixed hour


def test_invalid_key_kills_that_channel_and_the_task_is_not_failed(rig):
    body = dict(error=dict(code=400, message='API key not valid', details=[dict(reason='API_KEY_INVALID')]))
    rig.coder_script = [(1, error_out(400, body=body), b'')]
    result = rig.once(max_attempts=1)
    state = rig.state()
    assert result['status'] == 'READY' and result['reason'] == 'key_invalid'
    assert state['tasks']['T1']['status'] == 'READY' and not state.get('strikes')
    assert state['channel_quotas']['dead']['c1']


def test_region_refusal_makes_the_channel_unavailable_not_the_task_failed(rig):
    rig.coder_script = [(1, error_out(403, message='User location is not supported for the API use.'), b'')]
    result = rig.once(max_attempts=1)
    assert result['status'] == 'READY' and result['reason'] == 'region'
    assert rig.state()['channel_quotas']['p']['cool_until'] - time.time() > 3000
    assert not rig.state().get('strikes')


def test_server_error_is_retried_once_on_another_model_at_once_without_a_strike(rig):
    """20.11: the 503 cools model x, so the retry never asks x again: no 20 s pause before it (a 503 of Gemma
    cost ~67 s, 20 of them that pause); the pause stays for a failure that cools no model (next test)."""
    rig.coder_script = [(1, error_out(503), b''), 'good']
    cfg = rig.tmp / 'four.json'     # the 503 cools model x: the retry codes on y, the two critics need two more models
    small = dict(id='c3', group='p3', model='google/z', key_env='KEY', tpm=100000, rpd=100, tier='small', verified=True)
    fourth = dict(small, id='c4', group='p4', model='google/w')
    cfg.write_text(json.dumps(dict(channels=TWO_CHANNELS + [small, fourth])))
    result = rig.once(channel_config=cfg)
    assert result['status'] == 'REVIEW' and rig.sleeps == []
    assert [c['role'] for c in result['calls']] == ['code', 'code', 'review', 'review']
    assert rig.state()['model_calls'] == 4 and not rig.state().get('strikes')


def test_apierror_without_a_code_is_transient_and_two_failures_do_not_fail_the_task(rig):
    rig.coder_script = [(1, error_out(None), b''), (1, error_out(None), b'')]
    result = rig.once(max_attempts=1)
    coder = [c for c in result['calls'] if c['role'] == 'code']
    # owner: a transient fault moves the step to another model at once, without the 20 s pause
    assert [c['error_class'] for c in coder[:2]] == ['transient', 'transient'] and len(set(c['model'] for c in coder)) == len(coder)
    assert rig.sleeps == [] and result['status'] == 'REVIEW'
    assert not rig.state().get('strikes')


def test_an_overloaded_reviewer_moves_to_a_third_model_instead_of_deferring_the_candidate(rig):
    """Live 21.11 20:41-21:01: both review channels were one overloaded Gemma family; <id>_test lost three candidates
    that had passed the gate (4-7 min each). The review hops to any other free model in the same call."""
    rig.review_script = [(1, error_out(503), b'')]          # the next model: the rig's approval
    result = rig.once()
    review = [c for c in result['calls'] if c['role'] == 'review']
    assert review[0]['error_class'] == 'transient' and review[1]['error_class'] is None
    assert review[0]['model'] != review[1]['model'] and rig.sleeps == []      # another model at once, no pause
    # the review went on (the rig's 3 models leave no second critic: the chain is short, the candidate stays pending)
    assert result.get('reason') != 'transient' and result.get('pending_review') is True


def test_gate_failure_sends_diag_and_previous_diff_to_the_next_attempt(rig):
    rig.coder_script = ['bad', 'good']
    first = rig.once()
    assert first['status'] == 'READY' and first['reason'].startswith('gate')
    state = rig.state()
    assert state['strikes'] == {'bl:BL1': 1}
    assert state['tasks']['T1']['feedback'][-1]['source'] == 'gate'
    rig.ready_again()
    second = rig.once()
    assert second['status'] == 'REVIEW'
    prompt = rig.prompts[1]
    assert 'got -1' in prompt          # the diag of the failed gate
    assert 'a*b' in prompt             # the diff of the previous candidate
    assert second['calls'][0]['role'] == 'repair' and second['calls'][0]['attempt'] == 2


def test_reviewer_reasons_reach_the_next_attempt_and_count_as_a_strike(rig):
    rig.review_script = [verdict(False, ['hard-codes the expected value 5 instead of fixing the behaviour'])]
    first = rig.once()
    assert first['status'] == 'READY' and first['reason'].startswith('review')
    state = rig.state()
    assert state['tasks']['T1']['feedback'][-1]['source'] == 'review'
    assert state['strikes'] == {'bl:BL1': 1}
    rig.ready_again()
    second = rig.once()
    assert second['status'] == 'REVIEW'
    assert 'hard-codes the expected value' in rig.prompts[2]


def test_reviewer_prompt_has_task_diff_and_the_explicit_checks(rig):
    rig.once()
    review_prompt = rig.prompts[1]
    assert 'Fix sum' in review_prompt and 'a+b' in review_prompt
    assert 'hard-cod' in review_prompt.lower() and 'scope' in review_prompt.lower()


def test_without_another_model_the_review_waits_instead_of_self_review(rig):
    solo = rig.tmp / 'solo.json'
    solo.write_text(json.dumps(dict(channels=TWO_CHANNELS[:1])))
    result = rig.once(channel_config=solo, review_model='google/x')
    assert result['status'] == 'WAITING_CHANNEL' and result['reason'] == 'no_independent_reviewer'
    assert result['pending_review'] is True
    assert [coder for coder, _ in rig.models] == [True]  # the coder ran, nobody reviewed itself
    assert not rig.state().get('strikes') and rig.state()['tasks']['T1']['status'] == 'READY'


def test_already_green_blocks_without_a_call_or_a_strike(rig):
    rig.run_tests_fn = lambda root, tests, timeout_s: gr(True)
    result = rig.once()
    assert result['status'] == 'BLOCKED' and result['reason'] == 'already_green'
    assert result['blocked_reason'] == 'already_green' and result['infra'] is False
    assert rig.models == [] and not rig.state().get('strikes')
    assert rig.state()['tasks']['T1']['status'] == 'BLOCKED'


def test_unknown_base_is_infrastructure_postponed_five_minutes_no_strike(rig):
    rig.run_tests_fn = lambda root, tests, timeout_s: G.GateResult(-1, 0, 0, 0, 0, 0, False, 'timeout after 30s')
    before = time.time()
    result = rig.once()
    state = rig.state()
    assert result['status'] == 'READY' and result['reason'] == 'gate_unknown'
    assert rig.models == [] and not state.get('strikes')
    assert 290 <= state['tasks']['T1']['not_before'] - before <= 320


def test_gate_timeout_is_thirty_seconds(rig):
    rig.once()
    assert rig.runs and all(r[2] == 30 for r in rig.runs)


def test_weakening_is_rejected_before_any_test_runs_on_the_candidate(rig):
    rig.coder_script = ['import pytest\ndef add(a,b):\n    pytest.skip("no")\n    return a+b\n']
    result = rig.once()
    assert result['status'] == 'READY' and result['reason'].startswith('weakening')
    assert len(rig.runs) == 1  # only the red-before run on the base
    assert rig.state()['strikes'] == {'bl:BL1': F.UNSAFE_STRIKE}   # 21.11: a weakened check is an unsafe rejection (was 1)


def test_scope_violation_names_its_reason(rig):
    def sneaky(directory):
        (directory / 'evil.py').write_text('x=1\n')
        return 0, ev(finish()), b''
    rig.coder_script = [sneaky]
    result = rig.once()
    assert result['status'] == 'BLOCKED' and result['blocked_reason'] == 'scope_violation'
    assert 'unapproved' in result['reason_detail']
    assert rig.state()['tasks']['T1']['status'] == 'BLOCKED'




def test_secrets_in_the_task_title_never_reach_the_prompt(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch, title='Fix sum with key ' + FAKE_KEY)
    rig.once()
    assert rig.prompts and all(FAKE_KEY[:17] not in p for p in rig.prompts)


def test_unit_test_task_creates_its_file_and_must_be_red_on_the_old_code(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch, kind='unit_test')
    result = rig.once()
    assert result['status'] == 'REVIEW', result
    assert not (rig.root / 'tests/test_new.py').exists()
    # red_before is not used: the new test runs on the OLD code once
    assert len(rig.runs) == 1


def test_unit_test_that_is_green_on_the_old_code_is_rejected_with_feedback(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch, kind='unit_test')
    rig.run_tests_fn = lambda root, tests, timeout_s: gr(True)
    result = rig.once()
    assert result['status'] == 'READY' and result['reason'].startswith('gate')
    assert rig.state()['tasks']['T1']['feedback'][-1]['source'] == 'gate'
    assert rig.state()['strikes'] == {'bl:BL1': 1}


def test_new_red_neighbour_rejects_but_a_red_on_the_base_is_allowed(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    monkeypatch.setattr(rig.w, 'neighbor_tests', lambda root, task: ['tests/test_neighbor.py'])
    (rig.root / 'tests/test_neighbor.py').write_text('def test_n(): pass\n')

    def runner(base_red):
        def run(root, tests, timeout_s):
            fixed = 'a+b' in (Path(root) / 'calc.py').read_text()
            if list(tests) == ['tests/test_neighbor.py']:
                return gr(not (base_red or fixed), diag='neighbour broke')
            return gr(fixed, diag='task test')
        return run
    # neighbour green on the base, red with the candidate: a regression
    rig.run_tests_fn = runner(False)
    result = rig.once()
    assert result['status'] == 'READY' and 'neighbo' in result['reason']
    # neighbour already red on the base: allowed
    rig.ready_again()
    rig.run_tests_fn = runner(True)
    assert rig.once()['status'] == 'REVIEW'


def test_neighbours_that_do_not_fit_thirty_seconds_are_skipped_with_an_event(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    monkeypatch.setattr(rig.w, 'neighbor_tests', lambda root, task: ['tests/test_neighbor.py'])
    (rig.root / 'tests/test_neighbor.py').write_text('def test_n(): pass\n')

    def run(root, tests, timeout_s):
        if list(tests) == ['tests/test_neighbor.py']:
            return G.GateResult(-1, 0, 0, 0, 0, 0, False, 'timeout after 30s (process tree killed)')
        return gr('a+b' in (Path(root) / 'calc.py').read_text())
    rig.run_tests_fn = run
    result = rig.once()
    assert result['status'] == 'REVIEW' and 'neighbors_skipped' in result['events']


def test_neighbour_list_is_capped_at_six_and_excludes_the_task_tests(monkeypatch, tmp_path):
    from tools import agent_factory_runner as w
    t = task()
    fake = [f'tests/test_n{i}.py' for i in range(9)] + ['tests/test_calc.py']
    seen = {}
    monkeypatch.setattr(w.affected_tests, 'Graph', lambda r: seen.setdefault('root', r) or r)
    monkeypatch.setattr(w.affected_tests, 'affected', lambda changed, radius=None, **kw: (fake, {}, []))
    for name in fake:
        (tmp_path / name).parent.mkdir(exist_ok=True, parents=True)
        (tmp_path / name).write_text('')
    out = w.neighbor_tests(tmp_path, t)
    assert len(out) == 6 and 'tests/test_calc.py' not in out
    assert seen['root'] == tmp_path  # the graph is built over the task's root, not the tool's own tree


def test_gate_runs_on_the_full_tree_with_real_pytest(tmp_path, monkeypatch):
    """No fake gate: real tests import modules the task never names (helpers, conftest)."""
    rig = Rig(tmp_path, monkeypatch)
    monkeypatch.undo()
    from tools import agent_factory_runner as w
    rig.mp = monkeypatch
    monkeypatch.setattr(w, 'profile_names', lambda: ())   # undo() removed the rig's patch; tmp_path is under the profile
    monkeypatch.setattr(w, 'engine_for', lambda role, task: 'kilo')   # undo() also removed the engine pin: the
    monkeypatch.setattr(w, '_light_post', _refuse_network)             # subject here is the gate; never the network
    (rig.root / 'helper.py').write_text('def two(): return 2\n')
    (rig.root / 'tests/conftest.py').write_text('import sys, pathlib\nsys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))\n')
    (rig.root / 'tests/test_calc.py').write_text('from calc import add\nfrom helper import two\ndef test_add(): assert add(two(),3)==5\n')
    monkeypatch.setenv('KEY', 'synthetic')
    monkeypatch.setattr(w.shutil, 'which', lambda _: 'kilo')
    monkeypatch.setattr(w, 'neighbor_tests', lambda root, task: [])

    def model(t, directory, name, timeout, **kwargs):
        assert not (directory / 'helper.py').exists()  # the model still sees only its files
        if not t.touch_files:
            return 0, verdict(True, line='def test_add(): assert add(two(),3)==5'), b''
        (directory / 'calc.py').write_text('def add(a,b): return a+b\n')
        return 0, ev(finish()), b''
    monkeypatch.setattr(w, 'model_attempt', model)
    result = rig.once()
    assert result['status'] == 'REVIEW' and result['cross_review'] is True
    assert (rig.root / 'calc.py').read_text() == 'def add(a,b): return a-b\n'  # source tree untouched


def test_quota_wait_retains_the_candidate_and_resumes_review_without_recoding(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    cfg = tmp_path / 'tight.json'
    tight = [dict(c, rpd=1) for c in TWO_CHANNELS]
    cfg.write_text(json.dumps(dict(channels=tight)))
    first = rig.once(channel_config=cfg)
    assert first['status'] == 'WAITING_CHANNEL' and first['pending_review']
    assert rig.state()['tasks']['T1']['status'] == 'READY'
    assert not rig.state().get('strikes')
    rig.ready_again()
    second = rig.once()                       # room again (the rig's three models): both critics of the kept candidate
    assert second['status'] == 'REVIEW' and second['cross_review'] is True
    assert [bool(t) for t, _ in rig.models] == [True, False, False]  # coded once, reviewed by the chain


def test_three_gate_failures_end_in_failed_quarantine(rig):
    rig.coder_script = ['bad', 'bad', 'bad']
    seen = []
    for _ in range(3):
        seen.append(rig.once()['status'])
        rig.ready_again()
    assert seen == ['READY', 'READY', 'FAILED']
    assert len([m for m in rig.models if m[0]]) == 3


def test_infra_flag_is_false_for_a_rate_limit_and_a_region_refusal(rig):
    rig.coder_script = [(1, error_out(429), b'')]
    result = rig.once()
    assert result['reason'] == 'rate_minute' and result['infra'] is False
    rig.ready_again()
    rig.coder_script = [(1, error_out(403, message='User location is not supported'), b'')]
    result = rig.once()
    assert result['reason'] == 'region' and result['infra'] is False   # a region refusal is the proxy's business, not a dead machine


def test_no_independent_reviewer_is_a_postponement_not_infrastructure(rig):
    solo = rig.tmp / 'solo2.json'
    solo.write_text(json.dumps(dict(channels=TWO_CHANNELS[:1])))
    result = rig.once(channel_config=solo, review_model='google/x')
    assert result['infra'] is False
    row = rig.state()['tasks']['T1']
    assert row['defer_reason'] == 'no_independent_reviewer' and row['attempts'] == 0


def test_base_runs_never_touch_the_live_source_tree(rig):
    rig.once()
    assert rig.runs[0][0] != str(rig.root)  # red-before ran on a scratch copy


# ---- review round (critics, 19.11): pending, neighbours, escalation, reviewer faults, budget -------
import os
from tools import agent_factory_runner as W


def test_infra_defers_are_a_subset_of_the_defer_whitelist():
    assert W.INFRA_DEFERS <= F.DEFER_REASONS and 'base_moved' not in F.DEFER_REASONS


def tight_config(rig):
    cfg = rig.tmp / 'tight.json'
    cfg.write_text(json.dumps(dict(channels=[dict(c, rpd=1) for c in TWO_CHANNELS])))
    return cfg


@pytest.mark.parametrize('damage', ['base_moved', 'workdir_gone'])
def test_pending_candidate_of_a_moved_base_restarts_fresh_instead_of_blocking(rig, damage):
    first = rig.once(channel_config=tight_config(rig))
    assert first['status'] == 'WAITING_CHANNEL' and rig.state()['tasks']['T1'].get('pending_review')
    if damage == 'base_moved':
        (rig.root / 'calc.py').write_text('def add(a,b): return a-b  # HEAD moved\n')
    else:
        import shutil
        shutil.rmtree(rig.tmp / 'stage')
    rig.ready_again()
    second = rig.once()
    state = rig.state()
    assert second['status'] == 'REVIEW', second
    assert 'pending_dropped' in second['events'] and not state.get('strikes')
    assert [c for c, _ in rig.models].count(True) == 2  # recoded from scratch on the new base
    assert 'pending_review' not in state['tasks']['T1']


def test_unavailable_neighbour_graph_is_an_event_not_silence(rig):
    def boom(root, task):
        raise RuntimeError('graph parse failed')
    rig.mp.setattr(rig.w, 'neighbor_tests', boom)
    result = rig.once()
    assert result['status'] == 'REVIEW' and 'neighbors_unavailable:RuntimeError' in result['events']


def test_new_red_neighbours_are_compared_by_name_not_by_count(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    monkeypatch.setattr(rig.w, 'neighbor_tests', lambda root, task: ['tests/test_neighbor.py'])
    (rig.root / 'tests/test_neighbor.py').write_text('def test_n(): pass\n')

    def run(cand_ids, base_ids):
        def f(root, tests, timeout_s):
            fixed = 'a+b' in (Path(root) / 'calc.py').read_text()
            if list(tests) == ['tests/test_neighbor.py']:
                ids = cand_ids if fixed else base_ids
                return gr(not ids, failed_ids=tuple(ids)) if ids else gr(True)
            return gr(fixed)
        return f
    rig.run_tests_fn = run(('n::b',), ('n::a',))   # fixes a, breaks b: same count, a new name
    result = rig.once()
    assert result['status'] == 'READY' and 'neighbo' in result['reason']
    rig.ready_again()
    rig.run_tests_fn = run(('n::a',), ('n::a', 'n::c'))  # strictly fewer, nothing new
    assert rig.once()['status'] == 'REVIEW'


def test_an_idle_reviewer_timeout_is_a_rate_limit_and_keeps_the_candidate_pending(rig):
    rig.review_script = [(124, b'', b'worker-timeout')]      # Kilo slept in its own 429 retries: nothing visible happened
    result = rig.once()
    assert result['reason'] == 'rate_minute' and result['infra'] is False
    assert rig.state()['tasks']['T1'].get('pending_review') and not rig.state().get('strikes')


def test_reviewer_timeout_keeps_the_candidate_pending_instead_of_blocking(rig):
    busy = ev(dict(type='tool_use', part=dict(tool='read', state=dict(status='completed', input={}))), finish(100, 5))
    rig.review_script = [(124, busy, b'worker-timeout')]
    result = rig.once()
    row = rig.state()['tasks']['T1']
    assert result['status'] == 'READY' and result['reason'] == 'reviewer_failed' and result['infra'] is False
    assert row['status'] == 'READY' and row.get('pending_review') and not rig.state().get('strikes')


def test_reviewer_rate_limit_keeps_the_candidate_pending(rig):
    rig.review_script = [(1, error_out(429), b'')]
    result = rig.once()
    assert result['reason'] == 'rate_minute' and result['infra'] is False
    assert rig.state()['tasks']['T1'].get('pending_review')




def test_review_diff_is_trimmed_to_the_room_the_limit_leaves(tmp_path):
    from tools import factory_channels as ch
    root = tmp_path / 'w'
    (root / 'tests').mkdir(parents=True)
    (root / 'calc.py').write_text('\n'.join('line %d = %d' % (i, i) for i in range(1400)) + '\n')
    (root / 'tests/test_calc.py').write_text('def test_ok(): assert True\n')
    sizes = []

    def invoke(reviewer, directory, model, **kwargs):
        sizes.append(len(kwargs['prompt_override']))
        return 0, verdict(True), b''
    old = {'calc.py': b'completely different old content\n' * 900}
    approved, _ = W.review_candidate(task(context_budget=150000), root, 'google/y', invoke, baseline=old)
    assert approved and sizes[0] <= ch.PROMPT_LIMIT_CHARS


def test_review_model_is_mandatory_for_execution(rig):
    with pytest.raises(F.InvalidPlan, match='review'):
        rig.once(review_model=None)


def test_reason_and_feedback_are_redacted_before_they_leave_the_runner(rig):
    secret = FAKE_KEY
    rig.review_script = [verdict(False, ['the key %s sits in the file' % secret])]
    result = rig.once()
    assert secret not in json.dumps(result) and len(result['reason']) <= 300
    assert secret not in json.dumps(rig.state())


def test_one_function_builds_the_coder_prompt(tmp_path, monkeypatch, rig):
    t = F.read_plan(json.loads(rig.plan.read_text()))['T1']
    visible = {'calc.py': (rig.root / 'calc.py').read_bytes(),
               'tests/test_calc.py': (rig.root / 'tests/test_calc.py').read_bytes()}
    expected = W.build_coder_prompt(t, visible, failing='t::red\nassert add(2,3)==5 -> got -1')
    rig.once()
    assert rig.prompts[0] == expected
    monkeypatch.undo()   # from here on the REAL model_attempt: its default branch must use the same function
    work = tmp_path / 'wd'
    W.prepare(rig.root, t, work)
    captured = []
    monkeypatch.setattr(W, 'run_owned', lambda args, **kw: (captured.append(args), subprocess.CompletedProcess(args, 0, b'', b''))[1])
    monkeypatch.delenv('FACTORY_KILO_ENTRY', raising=False)
    monkeypatch.setattr(W.shutil, 'which', lambda name: 'kilo.exe')
    W.model_attempt(t, work, 'google/x', 5)
    assert captured and captured[0][-1] == W.build_coder_prompt(t, {n: (work / n).read_bytes() for n in visible})
    fb = W.build_coder_prompt(t, visible, feedback='[gate] boom', prev_diff='-a\n+b\n')
    assert '[gate] boom' in fb and '+b' in fb


def test_stale_prev_diff_is_removed_on_success_and_on_a_no_change_reject(rig):
    stale = rig.tmp / 'stage' / 'prev-diff' / 'T1.diff'
    stale.parent.mkdir(parents=True)
    stale.write_text('--- stale diff of another cycle\n')
    rig.coder_script = ['def add(a,b): return a-b\n']   # no change at all
    first = rig.once()
    assert first['reason'] == 'gate:no_changes' and not stale.exists()
    rig.coder_script = ['bad']
    rig.ready_again(); rig.once()
    assert stale.exists()
    rig.ready_again(); assert rig.once()['status'] == 'REVIEW'
    assert not stale.exists()


def test_budget_exhaustion_is_a_structured_wait_until_midnight_not_a_traceback(rig):
    first = rig.once()               # one pass spends two calls
    assert first['status'] == 'REVIEW'
    rig.edit_state(lambda s: s['tasks']['T1'].update(status='READY', attempts=0))
    state = rig.state()
    state_max = state['model_calls']
    rig.edit_state(lambda s: s.update(max_model_calls=state_max))
    result = rig.once()
    assert result['status'] == 'WAITING_CHANNEL' and result['reason'] == 'budget_exhausted'
    assert result['wait_s'] >= 60 and result['infra'] is False


def test_budget_ending_between_coder_and_reviewer_keeps_the_candidate(rig):
    result = rig.once(max_model_calls=1)
    assert result['reason'] == 'budget_exhausted' and result['infra'] is False
    assert rig.state()['tasks']['T1'].get('pending_review')


def test_three_gate_unknown_in_a_row_block_the_task(rig):
    rig.run_tests_fn = lambda root, tests, timeout_s: G.GateResult(-1, 0, 0, 0, 0, 0, False, 'timeout after 30s')
    seen = []
    for _ in range(3):
        seen.append(rig.once()['status'])
        rig.ready_again()
    row = rig.state()['tasks']['T1']
    assert seen == ['READY', 'READY', 'BLOCKED'] and row['blocked_reason'] == 'gate_unknown'


def test_three_unclassified_provider_errors_in_a_row_block_the_task(rig):
    rig.coder_script = [(1, error_out(400, message='bad request'), b'')] * 3
    seen = []
    for _ in range(3):
        seen.append(rig.once()['status'])
        rig.ready_again()
    assert seen == ['READY', 'READY', 'BLOCKED']
    assert rig.state()['tasks']['T1']['blocked_reason'] == 'provider_error' and not rig.state().get('strikes')


def test_dead_channel_without_an_alternative_counts_as_infrastructure(rig):
    solo = rig.tmp / 'solo3.json'
    solo.write_text(json.dumps(dict(channels=TWO_CHANNELS[:1])))
    st = F.load_state(rig.state_path, F.read_plan(json.loads(rig.plan.read_text())))
    st['channel_quotas'] = {'dead': {'c1': {'key': C._fingerprint({'KEY': 'synthetic'}, TWO_CHANNELS[0])}}}
    F.save_atomic(rig.state_path, st)
    result = rig.once(channel_config=solo)
    assert result['status'] == 'WAITING_CHANNEL' and result['channel_reason'] == 'dead' and result['infra'] is True


def test_balance_and_missing_model_are_channel_faults_with_infra(rig):
    rig.coder_script = [(1, error_out(402, message='negative balance'), b'')]
    result = rig.once()
    assert result['reason'] == 'balance' and result['infra'] is True and not rig.state().get('strikes')
    rig.ready_again()
    rig.edit_state(lambda s: s['channel_quotas'].pop('p', None))
    rig.coder_script = [(1, error_out(404, message='model not found'), b'')]
    result = rig.once()
    assert result['reason'] == 'model_missing' and 'c1' in rig.state()['channel_quotas']['dead']


# ---- round 3: big real files (80 KB modules), escalation, wait_s, baseline cleanup --------------------
from tools import factory_context as X


def big_module(n=700):
    parts = ['def add(a,b): return a-b\n']
    parts += ['def unrelated_fn_%d(x):\n    """filler"""\n    return x * %d + 7919\n' % (i, i) for i in range(n)]
    return '\n'.join(parts)


def test_big_touch_file_gets_outline_and_mentioned_fragment_not_the_whole_file(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch, title='Fix add so that sum works')
    text = big_module()
    assert len(text) > 40000
    (rig.root / 'calc.py').write_text(text)
    sizes = []
    original = rig._model

    def spy(t, directory, name, timeout, **kwargs):
        if t.touch_files:
            sizes.append((directory / 'calc.py').stat().st_size)
        return original(t, directory, name, timeout, **kwargs)
    monkeypatch.setattr(rig.w, 'model_attempt', spy)
    result = rig.once()
    prompt = rig.prompts[0]
    assert result['status'] == 'REVIEW', result
    assert len(prompt) <= C.PROMPT_LIMIT_CHARS
    assert 'OUTLINE' in prompt and 'unrelated_fn_100' in prompt and 'more definitions' in prompt  # the table of contents (cut when huge)
    assert 'def add(a,b): return a-b' in prompt                          # the mentioned function is inlined
    assert 'return x * 150 + 7919' not in prompt                         # the body of an unrelated one is not
    assert 'read tool' in prompt and 'touch_files' in prompt             # explicit instruction
    assert sizes == [(rig.root / 'calc.py').stat().st_size]                          # the work copy holds the FULL file


def test_big_file_prompt_and_review_prompt_both_fit_eighty_kb(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch, title='Fix add')
    (rig.root / 'calc.py').write_text(big_module(1250))
    assert (rig.root / 'calc.py').stat().st_size > 80000
    result = rig.once()
    assert result['status'] == 'REVIEW'
    assert all(len(p) <= C.PROMPT_LIMIT_CHARS for p in rig.prompts)
    print('PROMPT_SIZES', [len(p) for p in rig.prompts])


def test_reservation_counts_the_big_touch_file_the_model_will_read(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch, title='Fix add')
    (rig.root / 'calc.py').write_text(big_module(700))
    size = (rig.root / 'calc.py').stat().st_size
    result = rig.once()
    call = result['calls'][0]
    assert call['reserved_tokens'] >= C.estimate_tokens(len(rig.prompts[0])) + int(size / 3.5) - 1


def test_policy_lets_the_agent_read_a_big_read_file_but_not_a_small_one(tmp_path):
    root = tmp_path / 'r'
    (root / 'tests').mkdir(parents=True)
    (root / 'calc.py').write_text('def add(a,b): return a-b\n')
    (root / 'big.py').write_text(big_module(300))
    (root / 'small.py').write_text('x = 1\n')
    (root / 'tests/test_calc.py').write_text('def test_ok(): assert True\n')
    t = task(read_files=['big.py', 'small.py'])
    stage = tmp_path / 'stage'
    W.prepare(root, t, stage)
    read = json.loads((stage / 'kilo.jsonc').read_text())['permission']['read']
    assert read['**/big.py'] == 'allow' and read['**/calc.py'] == 'allow'
    assert read.get('**/small.py', 'deny') == 'deny'
    assert (stage / 'big.py').stat().st_size == (root / 'big.py').stat().st_size


def test_outline_lists_classes_methods_and_line_ranges():
    src = 'import os\n\nclass Box:\n    def put(self, x):\n        return x\n\n    def take(self):\n        return 1\n\ndef free(a, b=2):\n    return a\n'
    out = X.outline(src)
    assert 'class Box' in out and 'def put(self, x)' in out and 'def take(self)' in out and 'def free(a, b=2)' in out
    assert 'L3-8' in out and 'L' + '10-11' in out


def test_many_mid_size_files_are_shown_as_outlines_instead_of_refusing_the_task(tmp_path, monkeypatch):
    """Was test_many_mid_size_files_still_stop_as_context_too_large: files below the "large" threshold that do not fit
    together are now shown as outline + parts, largest first (large_names, live 20.11), and the coder is called."""
    rows = dict(context_budget=150000, read_files=['a.py', 'b.py', 'c.py', 'd.py'])
    rig = Rig(tmp_path, monkeypatch, **rows)
    for n in 'abcd':
        (rig.root / (n + '.py')).write_text('# ' + 'x' * 11500 + '\n')   # each below the "large" threshold
    rig.once()
    assert rig.models and 'FILE a.py (LARGE' in rig.prompts[0] and len(rig.prompts[0]) <= C.PROMPT_LIMIT_CHARS


def test_charge_comes_before_reserve_so_an_exhausted_budget_books_nothing(rig):
    result = rig.once(max_model_calls=1)             # coder takes the only call, the reviewer finds none
    assert result['reason'] == 'budget_exhausted'
    minute = rig.state()['channel_quotas']['p']['minute']
    assert len(minute) == 1                          # only the coder's booking exists


def test_reviewer_failing_three_times_in_a_row_blocks_the_task(rig):
    busy = ev(dict(type='tool_use', part=dict(tool='read', state=dict(status='completed', input={}))), finish(100, 5))
    rig.review_script = [(124, busy, b'worker-timeout')] * 3
    seen = []
    for _ in range(3):
        seen.append(rig.once()['status'])
        rig.ready_again()
    row = rig.state()['tasks']['T1']
    assert seen == ['READY', 'READY', 'BLOCKED'] and row['blocked_reason'] == 'reviewer_failed'
    assert 'pending_review' not in row


def test_unmeasured_neighbour_base_with_a_red_candidate_neighbour_defers(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    monkeypatch.setattr(rig.w, 'neighbor_tests', lambda root, task: ['tests/test_neighbor.py'])
    (rig.root / 'tests/test_neighbor.py').write_text('def test_n(): pass\n')

    def run(root, tests, timeout_s):
        fixed = 'a+b' in (Path(root) / 'calc.py').read_text()
        if list(tests) == ['tests/test_neighbor.py']:
            if fixed:
                return gr(False, failed_ids=('n::a',))
            return G.GateResult(-1, 0, 0, 0, 0, 0, False, 'timeout after 30s')   # the base is not measured
        return gr(fixed)
    rig.run_tests_fn = run
    result = rig.once()
    assert result['status'] == 'READY' and result['reason'] == 'gate_unknown'
    assert not rig.state().get('strikes')


def test_corrupt_defer_streak_and_pending_review_are_treated_as_absent(rig):
    st = F.load_state(rig.state_path, F.read_plan(json.loads(rig.plan.read_text())))
    st['tasks']['T1']['defer_streak'] = 'junk'
    st['tasks']['T1']['pending_review'] = 'junk'
    F.save_atomic(rig.state_path, st)
    assert F.defer_streak(st, 'T1', 'transient') == 0
    result = rig.once()
    assert result['status'] == 'REVIEW', result
    rig.coder_script = [(1, error_out(503), b'')] * (1 + W.TRANSIENT_HOPS)
    rig.edit_state(lambda s: s['tasks']['T1'].update(status='READY', defer_streak=['x'], pending_review=5))
    assert rig.once()['reason'] == 'transient'


def test_baseline_copy_is_removed_after_a_pass(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    cfg = tmp_path / 'tight2.json'
    cfg.write_text(json.dumps(dict(channels=[dict(c, rpd=1) for c in TWO_CHANNELS])))
    assert rig.once(channel_config=cfg)['status'] == 'WAITING_CHANNEL'
    rig.ready_again()
    assert rig.once()['status'] == 'REVIEW'
    assert not list((rig.tmp / 'stage').glob('*-baseline'))
    # a pending candidate whose base moved: the fresh copy IS the work dir and must survive
    rig.edit_state(lambda s: s['tasks']['T1'].update(status='READY', attempts=0))
    rig.ready_again()
    (rig.root / 'calc.py').write_text('def add(a,b): return a-b  # moved\n')
    assert rig.once(channel_config=cfg)['status'] == 'WAITING_CHANNEL'
    pend = rig.state()['tasks']['T1']['pending_review']['workdir']
    assert Path(pend).is_dir()


def test_wait_s_is_the_soonest_channel_that_can_serve_the_next_step(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    split = tmp_path / 'split.json'
    split.write_text(json.dumps(dict(channels=[
        dict(id='c1', group='p1', model='google/x', key_env='KEY', tpm=100000, rpd=100, verified=True),
        dict(id='c2', group='p2', model='google/y', key_env='KEY', tpm=100000, rpd=100, verified=True)])))
    body = dict(error=dict(code=429, details=[{'@type': 'x.RetryInfo', 'retryDelay': '300s'}]))
    rig.coder_script = [(1, error_out(429, body=body), b'')]
    result = rig.once(channel_config=split)
    assert result['reason'] == 'rate_minute' and result['wait_s'] <= 5      # c2 is free: no 300 s wait



def test_big_file_prompts_have_outline_and_fragment_and_the_reviewer_may_not_edit(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch, title='Fix add')
    (rig.root / 'calc.py').write_text(big_module(1250))
    rig.coder_script = [big_module(1250).replace('return a-b', 'return a+b')]  # a big candidate
    rig.once()
    coder, reviewer = rig.prompts[0], rig.prompts[1]
    assert 'OUTLINE' in coder and 'def add(a,b): return a-b' in coder and 'touch_files' in coder
    assert 'OUTLINE' in reviewer and 'Do not edit anything' in reviewer and 'edit only the files listed' not in reviewer


def test_a_test_file_over_the_limit_is_shown_as_an_outline_and_the_task_runs(tmp_path, monkeypatch):
    """Was test_a_test_file_over_the_limit_is_context_too_large_without_a_call: tests were always shown whole, so a big
    test refused its task before any call (live 20.11 04:29: four tasks, one test of 50 KB). Now a test over
    LARGE_FILE_CHARS is shown as outline + parts like any file, the failing test first (large_names, failing_names)."""
    rig = Rig(tmp_path, monkeypatch)
    (rig.root / 'tests/test_calc.py').write_text('from calc import add\n' + '# ' + 'y' * 29000 + '\ndef test_add(): assert add(2,3)==5\n')
    rig.once()
    assert rig.models and 'FILE tests/test_calc.py (LARGE' in rig.prompts[0]
    assert 'def test_add()' in rig.prompts[0] and len(rig.prompts[0]) <= C.PROMPT_LIMIT_CHARS


def test_call_refuses_an_over_limit_prompt_without_charging(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    monkeypatch.setattr(rig.w, 'build_coder_prompt', lambda *a, **kw: 'x' * (C.PROMPT_LIMIT_CHARS + 1))
    result = rig.once()
    assert result['status'] == 'BLOCKED' and result['reason'] == 'context_too_large'
    assert rig.models == [] and rig.state()['model_calls'] == 0


def test_too_many_big_files_for_even_an_outline_each_stop_as_context_too_large(tmp_path, monkeypatch):
    names = ['m%d.py' % i for i in range(22)]
    rig = Rig(tmp_path, monkeypatch, read_files=names)
    for n in names:
        (rig.root / n).write_text('def f():\n    return 1\n# ' + 'z' * 13000 + '\n')
    result = rig.once()
    assert result['status'] == 'BLOCKED' and result['reason'] == 'context_too_large' and rig.models == []


def test_reservation_capped_is_reported_and_big_read_files_count(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch, title='Fix add', read_files=['dep.py'])
    (rig.root / 'calc.py').write_text(big_module(700))
    (rig.root / 'dep.py').write_text('# ' + 'q' * 30000 + '\ndef helper(): return 1\n')
    small = rig.tmp / 'small.json'
    small.write_text(json.dumps(dict(channels=[dict(c, tpm=16000) for c in TWO_CHANNELS])))
    result = rig.once(channel_config=small)
    assert 'reservation_capped' in result['events']
    assert result['calls'][0]['reserved_tokens'] == 16000


def test_unmeasured_neighbour_base_does_not_pay_the_coder_twice(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    monkeypatch.setattr(rig.w, 'neighbor_tests', lambda root, task: ['tests/test_neighbor.py'])
    (rig.root / 'tests/test_neighbor.py').write_text('def test_n(): pass\n')
    measured = {'base': False}

    def run(root, tests, timeout_s):
        fixed = 'a+b' in (Path(root) / 'calc.py').read_text()
        if list(tests) == ['tests/test_neighbor.py']:
            if fixed:
                return gr(False, failed_ids=('n::a',))
            return gr(False, failed_ids=('n::a',)) if measured['base'] else G.GateResult(-1, 0, 0, 0, 0, 0, False, 'timeout')
        return gr(fixed)
    rig.run_tests_fn = run
    first = rig.once()
    assert first['reason'] == 'gate_unknown' and first['pending_review'] is True
    measured['base'] = True
    rig.ready_again()
    second = rig.once()
    assert second['status'] == 'REVIEW'
    assert [coder for coder, _ in rig.models].count(True) == 1     # the candidate was kept, not recoded


def test_stale_baseline_copies_older_than_the_lease_are_removed(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    old, fresh = rig.tmp / 'stage' / 'task-T9-aaaa-baseline', rig.tmp / 'stage' / 'task-T8-bbbb-baseline'
    for d in (old, fresh):
        d.mkdir(parents=True)
    past = time.time() - 7200
    os.utime(old, (past, past))
    rig.once()
    assert not old.exists() and fresh.exists()



def test_reviewer_gets_outline_not_a_slice_for_a_big_touch_file(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch, title='Fix add', context_targets={'calc.py': 'add'})
    (rig.root / 'calc.py').write_text(big_module(700))
    rig.coder_script = [big_module(700).replace('return a-b', 'return a+b')]
    rig.once()
    review_prompt = rig.prompts[1]
    assert 'OUTLINE' in review_prompt and 'slice add' not in review_prompt


def test_lease_constant_is_shared_and_the_runner_has_no_private_copy():
    import inspect
    assert inspect.signature(F.acquire).parameters['lifetime'].default == F.LEASE_LIFETIME_S == 1800
    assert not hasattr(W, 'LEASE_S')


def test_a_baseline_copy_that_cannot_be_removed_is_reported(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    old = rig.tmp / 'stage' / 'task-T9-aaaa-baseline'
    old.mkdir(parents=True)
    past = time.time() - 7200
    os.utime(old, (past, past))
    real = rig.w.shutil.rmtree

    def rm(path, *a, **kw):
        if str(path).endswith('-baseline') and not kw.get('ignore_errors'):
            raise OSError('busy')
        return real(path, *a, **kw)
    monkeypatch.setattr(rig.w.shutil, 'rmtree', rm)
    result = rig.once()
    assert 'stale_baseline_kept' in result['events'] and old.exists()


def test_cleanup_keeps_the_pending_directory_and_removes_the_orphan_one(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    cfg = tmp_path / 'tight3.json'
    cfg.write_text(json.dumps(dict(channels=[dict(c, rpd=1) for c in TWO_CHANNELS])))
    assert rig.once(channel_config=cfg)['status'] == 'WAITING_CHANNEL'
    pend = Path(rig.state()['tasks']['T1']['pending_review']['workdir'])
    other = rig.tmp / 'stage' / 'task-T9-aaaa'
    other.mkdir()
    past = time.time() - 7200
    for d in (pend, other):
        os.utime(d, (past, past))
    rig.ready_again()
    assert rig.once()['status'] == 'REVIEW'      # the pending candidate was still there to resume
    assert not other.exists()                   # an old task copy that no task owns is garbage


def neighbour_rig(tmp_path, monkeypatch, base_ids):
    rig = Rig(tmp_path, monkeypatch)
    monkeypatch.setattr(rig.w, 'neighbor_tests', lambda root, task: ['tests/test_neighbor.py'])
    (rig.root / 'tests/test_neighbor.py').write_text('def test_n(): pass\n')
    mode = {'base': base_ids}

    def run(root, tests, timeout_s):
        fixed = 'a+b' in (Path(root) / 'calc.py').read_text()
        if list(tests) == ['tests/test_neighbor.py']:
            if fixed:
                return gr(False, failed_ids=('n::a',))
            if mode['base'] is None:
                return G.GateResult(-1, 0, 0, 0, 0, 0, False, 'timeout')
            return gr(False, failed_ids=mode['base'])
        return gr(fixed)
    rig.run_tests_fn = run
    return rig, mode


def test_a_regression_found_on_the_pending_resume_rejects_and_clears_pending(tmp_path, monkeypatch):
    rig, mode = neighbour_rig(tmp_path, monkeypatch, None)
    first = rig.once()
    assert first['reason'] == 'gate_unknown' and rig.state()['tasks']['T1'].get('pending_review')
    mode['base'] = ('n::z',)                    # now the base is measured: the candidate's red name is NEW
    rig.ready_again()
    second = rig.once()
    row = rig.state()['tasks']['T1']
    assert second['status'] == 'READY' and 'neighbo' in second['reason']
    assert 'pending_review' not in row and rig.state()['strikes'] == {'bl:BL1': 1}


def test_three_unmeasured_neighbour_passes_block_without_paying_the_coder_again(tmp_path, monkeypatch):
    rig, mode = neighbour_rig(tmp_path, monkeypatch, None)
    seen = []
    for i in range(3):
        seen.append(rig.once()['status'])
        if i == 0:
            work = Path(rig.state()['tasks']['T1']['pending_review']['workdir'])
        rig.ready_again()
    row = rig.state()['tasks']['T1']
    assert seen == ['READY', 'READY', 'BLOCKED'] and row['blocked_reason'] == 'gate_unknown'
    assert [c for c, _ in rig.models].count(True) == 1 and 'pending_review' not in row
    assert not work.exists()                    # the void candidate's work copy is gone

import inspect as _inspect


def test_prompt_has_the_task_text_and_what_fails_on_the_base(rig):
    rig.once()
    prompt = rig.prompts[0]
    assert 'Failing on the base now' in prompt and 'got -1' in prompt and 't::red' in prompt
    t = F.read_plan(json.loads(rig.plan.read_text()))['T1']
    vis = {'calc.py': b'def add(a,b): return a-b\n', 'tests/test_calc.py': b'def test_a(): pass\n'}
    text = W.build_coder_prompt(t, vis, goal='Make add() return the sum. ' + FAKE_KEY,
                                failing='tests.test_calc::test_add\nassert 1 == 5')
    assert 'Task text:\nMake add() return the sum.' in text and FAKE_KEY[:17] not in text
    assert 'tests.test_calc::test_add' in text
    long = W.build_coder_prompt(t, vis, goal='g' * 5000, failing='f' * 5000)
    assert 'g' * 1500 in long and 'g' * 1501 not in long and 'f' * 1501 not in long


def test_unit_test_prompt_has_no_failing_block(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch, kind='unit_test')
    rig.once()
    assert 'Failing on the base now' not in rig.prompts[0]



def test_rejections_are_tagged_with_their_attempt_and_blocks_as_infra(rig):
    rig.coder_script = ['bad']
    rig.once()
    assert rig.state()['tasks']['T1']['feedback'][-1]['text'].startswith('[attempt 1] ')
    rig.edit_state(lambda s: s['tasks']['T1'].update(status='READY'))
    rig.run_tests_fn = lambda root, tests, timeout_s: gr(True)
    assert rig.once()['reason'] == 'already_green'
    assert rig.state()['tasks']['T1']['feedback'][-1]['text'].startswith('[infra] ')


def tool_read(path):
    return dict(type='tool_use', part=dict(tool='read', state=dict(input=dict(filePath=str(path)))))


def test_calls_report_what_the_model_did_and_no_change_carries_a_model_note(rig):
    secret = FAKE_KEY

    def lazy(directory):
        out = ev(tool_read(directory / 'calc.py'), tool_read('/etc/passwd'),
                 dict(type='text', part=dict(text='I looked at it and there is nothing to do ' + secret)),
                 finish())
        return 0, out, b''
    rig.coder_script = [lazy]
    result = rig.once()
    call = result['calls'][0]
    assert result['reason'] == 'gate:no_changes'
    assert call['tool_events'] == 2 and call['steps'] == 1 and call['finish_reason'] == 'stop'
    assert call['files_read'] == ['calc.py']
    assert 'nothing to do' in result['model_note'] and secret not in result['model_note']
    assert len(result['model_note']) <= 300


def test_a_reviewer_rejection_carries_the_reviewer_note(rig):
    # the note is the last critic's text and a rejection needs the majority of the panel: two critics reject
    rig.review_script = [verdict(False, ['special-cases the test input'])] * 2
    result = rig.once()
    assert 'special-cases' in result['model_note']


def test_inside_staging_means_strictly_inside(tmp_path):
    stage = tmp_path / 'stage'
    (stage / 'task-x').mkdir(parents=True)
    assert W.inside_staging(stage / 'task-x', stage) is True
    assert W.inside_staging(stage, stage) is False
    assert W.inside_staging(tmp_path / 'elsewhere', stage) is False
    assert W.inside_staging('bad\0path', stage) is False


def test_a_pending_workdir_outside_or_equal_to_staging_is_never_deleted(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'keep.txt').write_text('x')
    (rig.tmp / 'stage').mkdir()
    for target in (outside, rig.tmp / 'stage'):
        st = F.load_state(rig.state_path, F.read_plan(json.loads(rig.plan.read_text())))
        st['tasks']['T1']['pending_review'] = {'workdir': str(target), 'baseline_digest': 'x'}
        F.save_atomic(rig.state_path, st)
        rig.run_tests_fn = lambda root, tests, timeout_s: gr(True)       # already_green -> block()
        rig.once()
        assert (outside / 'keep.txt').exists() and (rig.tmp / 'stage').is_dir()
        rig.edit_state(lambda s: s['tasks']['T1'].update(status='READY', blocked_reason=None))


def test_cleanup_skips_a_vanished_copy_silently_but_reports_other_errors(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    old = rig.tmp / 'stage' / 'task-T9-aaaa-baseline'
    old.mkdir(parents=True)
    past = time.time() - 7200
    os.utime(old, (past, past))
    real = rig.w.shutil.rmtree

    def rm_missing(path, *a, **kw):
        if str(path).endswith('-baseline') and not kw.get('ignore_errors'):
            raise FileNotFoundError('gone')
        return real(path, *a, **kw)
    monkeypatch.setattr(rig.w.shutil, 'rmtree', rm_missing)
    assert 'stale_baseline_kept' not in rig.once()['events']


def test_old_task_copies_that_are_not_pending_are_removed_and_failures_reported(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    gone, stuck = rig.tmp / 'stage' / 'task-T7-aaaa', rig.tmp / 'stage' / 'task-T8-bbbb'
    for d in (gone, stuck):
        d.mkdir(parents=True)
        past = time.time() - 7200
        os.utime(d, (past, past))
    real = rig.w.shutil.rmtree

    def rm(path, *a, **kw):
        if str(path).endswith('task-T8-bbbb') and not kw.get('ignore_errors'):
            raise OSError('busy')
        return real(path, *a, **kw)
    monkeypatch.setattr(rig.w.shutil, 'rmtree', rm)
    result = rig.once()
    assert not gone.exists() and stuck.exists() and 'pending_copy_kept' in result['events']


def test_the_context_target_filter_has_one_owner():
    import re
    source = _inspect.getsource(W)
    assert len(re.findall(r'n not in task\.touch_files \+ task\.tests', source)) == 1
    t = task(read_files=['dep.py'], context_targets={'dep.py': 'f', 'calc.py': 'g'})
    assert W.visible_targets(t) == {'dep.py': 'f'}


# ---- round 3 of the critics: read-path normalisation, feedback cycles, fail-closed cleanup ------------


@pytest.mark.parametrize('raw', ['sub/../../x', 'calc.py/../../x', '../x', '/etc/passwd'])
def test_read_paths_are_normalised_and_anything_outside_the_work_copy_is_dropped(tmp_path, raw):
    work = tmp_path / 'wd'
    work.mkdir()
    result = {'files_read': []}
    W._note_read(result, dict(tool='read', state=dict(input=dict(filePath=raw))), work)
    assert result['files_read'] == []
    W._note_read(result, dict(tool='read', state=dict(input=dict(filePath='sub/./calc.py'))), work)
    W._note_read(result, dict(tool='read', state=dict(input=dict(filePath=str(work / 'tests' / 'test_a.py')))), work)
    assert result['files_read'] == ['sub/calc.py', 'tests/test_a.py']


def test_fresh_feedback_takes_the_tail_after_the_last_opus_note_and_the_last_attempt():
    tasks = {'T1': task()}
    state = F.initial_state(tasks)
    state['tasks']['T1']['feedback'] = [      # set directly: add_feedback would evict old entries
        dict(source='gate', text='[attempt 1] cycle-one failure'),
        dict(source='opus', text='new instructions after the unblock'),
        dict(source='gate', text='[attempt 1] cycle-two failure'),
        dict(source='gate', text='[attempt 2] cycle-two later failure'),
        dict(source='review', text='[attempt 2] reviewer reason'),
        dict(source='review', text='[infra] a reviewer cannot write infra notes'),
        dict(source='gate', text='[infra] context_too_large: narrow task scope'),
    ]
    got = W.fresh_feedback(state, 'T1')
    assert 'new instructions' in got and 'cycle-two later failure' in got and 'reviewer reason' in got
    for gone in ('cycle-one', 'cycle-two failure', 'context_too_large', 'cannot write infra'):
        assert gone not in got


def test_a_reviewer_rejection_reaches_the_next_coder_prompt_without_infra_or_old_notes(rig):
    rig.review_script = [verdict(False, ['hard-codes the value instead of fixing add'])]
    rig.once()
    rig.edit_state(lambda s: s['tasks']['T1']['feedback'].append(
        dict(source='gate', text='[infra] context_too_large: narrow task scope')))
    rig.ready_again()
    rig.once()
    second_coder = rig.prompts[2]
    assert 'hard-codes the value' in second_coder
    assert 'context_too_large' not in second_coder and 'narrow task scope' not in second_coder


def two_task_plan(rig):
    rows = json.loads(rig.plan.read_text())
    rows.append(dict(id='T2a', title='Other', touch_files=['other.py'], tests=['tests/test_other.py'],
                     privacy_safe=True, backlog_id='BL2'))
    rig.plan.write_text(json.dumps(rows))


def aged(path, seconds=7200):
    past = time.time() - seconds
    os.utime(path, (past, past))


def test_cleanup_is_fail_closed_when_any_pending_path_cannot_be_parsed(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    two_task_plan(rig)
    orphan = rig.tmp / 'stage' / 'task-T9-aaaa'
    orphan.mkdir(parents=True)
    aged(orphan)
    st = F.load_state(rig.state_path, F.read_plan(json.loads(rig.plan.read_text())))
    st['tasks']['T2a']['pending_review'] = {'workdir': 'bad\0path', 'baseline_digest': 'x'}
    F.save_atomic(rig.state_path, st)
    result = rig.once()
    assert orphan.exists() and 'cleanup_skipped_unparsed_pending' in result['events']


def test_cleanup_spares_a_foreign_pending_copy_a_live_lease_and_symlinks(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    two_task_plan(rig)
    foreign = rig.tmp / 'stage' / 'task-T2a-bbbb'
    live = rig.tmp / 'stage' / ('task-T3-' + 'c' * 8 + '-retry-1')
    link = rig.tmp / 'stage' / 'task-T6-link'
    for d in (foreign, live, link):
        d.mkdir(parents=True)
        aged(d)
    st = F.load_state(rig.state_path, F.read_plan(json.loads(rig.plan.read_text())))
    st['tasks']['T2a']['pending_review'] = {'workdir': str(foreign), 'baseline_digest': 'x'}
    F.save_atomic(rig.state_path, st)
    tasks = F.read_plan(json.loads(rig.plan.read_text()))
    st = F.load_state(rig.state_path, tasks)
    st['tasks']['T2a'].update(status='RUNNING', lease='c' * 32, deadline=time.time() + 900, attempts=1)
    st['tasks']['T2a']['pending_review'] = {'workdir': str(foreign), 'baseline_digest': 'x'}
    live_name = rig.tmp / 'stage' / ('task-T2a-' + 'c' * 8 + '-retry-1')
    live_name.mkdir()
    aged(live_name)
    F.save_atomic(rig.state_path, st)
    real = Path.is_symlink
    monkeypatch.setattr(Path, 'is_symlink', lambda self: self.name == 'task-T6-link' or real(self))
    rig.once()
    assert foreign.exists() and live_name.exists() and link.exists()      # other task's pending, live lease, symlink
    assert not live.exists()                                              # an ownerless old copy is still collected


def test_a_secret_in_the_base_diagnostics_never_reaches_the_prompt(rig):
    secret = FAKE_KEY
    rig.run_tests_fn = lambda root, tests, timeout_s: gr('a+b' in (Path(root) / 'calc.py').read_text(),
                                                          diag='failure: leaked key ' + secret)
    rig.once()
    assert 'Failing on the base now' in rig.prompts[0] and secret not in rig.prompts[0]
    t = F.read_plan(json.loads(rig.plan.read_text()))['T1']
    text = W.build_coder_prompt(t, {'calc.py': b'x = 1\n'}, failing='ids\n' + secret)
    assert secret not in text



def test_a_goal_that_names_a_method_selects_its_fragment_in_a_big_file(rig):
    big = ('class KindMixin:\n    def _cue_over_before(self, x):\n        return x + 1\n\n'
           + '\n'.join('def pad_%d(): return %d' % (i, i) for i in range(900)) + '\n')
    t = F.read_plan(json.loads(rig.plan.read_text()))['T1']
    vis = {'calc.py': big.encode(), 'tests/test_calc.py': b'def test_a(): pass\n'}
    assert 'return x + 1' not in W.build_coder_prompt(t, vis)                      # outline only without the goal
    text = W.build_coder_prompt(t, vis, goal='Suspects: calc.py: KindMixin._cue_over_before, func')
    assert 'return x + 1' in text
    object.__setattr__(t, 'goal', 'Suspects: calc.py: KindMixin._cue_over_before')   # the reviewer reads it too
    work = rig.tmp / 'wd'
    (work / 'tests').mkdir(parents=True)
    (work / 'calc.py').write_text(big)
    (work / 'tests/test_calc.py').write_text('def test_a(): pass\n')
    seen = []

    def invoke(reviewer, directory, model, **kwargs):
        seen.append(kwargs['prompt_override'])
        return 0, verdict(True), b''
    t2 = F.read_plan(json.loads(rig.plan.read_text()))['T1']
    object.__setattr__(t2, 'goal', t.goal)
    W.review_candidate(t2, work, 'google/y', invoke, baseline={'calc.py': b'old\n'})
    assert 'return x + 1' in seen[0]


def test_local_paths_never_reach_the_coder_prompt(rig):
    leaked = str(rig.root / 'calc.py')

    def run(root, tests, timeout_s):
        fixed = 'a+b' in (Path(root) / 'calc.py').read_text()
        return gr(fixed, diag='failure at %s line 3; home %s' % (Path(root) / 'calc.py', Path.home()))
    rig.run_tests_fn = run
    rig.coder_script = ['bad', 'good']
    rig.once()
    rig.ready_again()
    rig.once()
    user = Path.home().name
    for prompt in (rig.prompts[0], rig.prompts[1]):        # the base block, then the gate feedback of pass 1
        assert user not in prompt and '<repo>/calc.py' in prompt, prompt[:600]
    assert user not in json.dumps(rig.state()['tasks']['T1']['feedback'])


def feedback_state(items):
    state = F.initial_state({'T1': task()})
    state['tasks']['T1']['feedback'] = items
    return state


def test_all_opus_notes_are_kept_and_only_gate_and_review_are_cut_by_the_last_attempt():
    state = feedback_state([
        dict(source='opus', text='first instruction'),
        dict(source='gate', text='[attempt 1] old failure'),
        dict(source='opus', text='second instruction'),
        dict(source='gate', text='[attempt 1] cycle failure'),
        dict(source='review', text='[attempt 2] reviewer reason'),
    ])
    got = W.fresh_feedback(state, 'T1')
    assert 'first instruction' in got and 'second instruction' in got and 'reviewer reason' in got
    assert 'old failure' not in got and 'cycle failure' not in got


def test_an_old_state_without_attempt_tags_gives_the_last_plain_gate_or_review_entry():
    state = feedback_state([
        dict(source='gate', text='an older plain failure'),
        dict(source='gate', text='base moved after the gate'),
        dict(source='gate', text='[infra] context_too_large: narrow'),
    ])
    got = W.fresh_feedback(state, 'T1')
    assert 'base moved after the gate' in got and 'older plain' not in got and 'context_too_large' not in got
    assert W.fresh_feedback(feedback_state([dict(source='gate', text='[infra] only infra')]), 'T1') is None


def test_cleanup_is_skipped_for_any_unparseable_pending_record_with_its_own_event(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    two_task_plan(rig)
    orphan = rig.tmp / 'stage' / 'task-T9-aaaa'
    orphan.mkdir(parents=True)
    aged(orphan)
    for junk in ('not a dict', {'workdir': 5, 'baseline_digest': 'x'}):
        st = F.load_state(rig.state_path, F.read_plan(json.loads(rig.plan.read_text())))
        st['tasks']['T2a']['pending_review'] = junk
        F.save_atomic(rig.state_path, st)
        result = rig.once()
        assert orphan.exists() and 'cleanup_skipped_unparsed_pending' in result['events']
        assert 'pending_copy_kept' not in result['events']
        rig.edit_state(lambda s: s['tasks']['T1'].update(status='READY'))


def test_a_copy_younger_than_two_leases_is_kept_for_a_writer_that_may_still_run(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    young, old = rig.tmp / 'stage' / 'task-T9-aaaa', rig.tmp / 'stage' / 'task-T8-bbbb'
    for d, age in ((young, 3000), (old, 7200)):
        d.mkdir(parents=True)
        aged(d, age)
    rig.once()
    assert young.exists() and not old.exists()


def test_a_real_symlink_is_never_followed_or_removed_by_the_cleanup(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    target = tmp_path / 'precious'
    target.mkdir()
    (target / 'keep.txt').write_text('x')
    link = rig.tmp / 'stage' / 'task-T6-link'
    link.parent.mkdir(parents=True)
    try:
        os.symlink(target, link, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip('no privilege to create symlinks on this machine')
    aged(target)
    rig.once()
    assert (target / 'keep.txt').exists() and link.is_symlink()


@pytest.mark.skipif(os.name != 'nt', reason='Windows path forms')
@pytest.mark.parametrize('raw', ['..\\..\\x', DRIVE + '\\Windows\\x', '\\\\host\\share\\x', 'C:x', '//host/share/x'])
def test_windows_path_forms_never_count_as_files_read(tmp_path, raw):
    work = tmp_path / 'wd'
    work.mkdir()
    result = {'files_read': []}
    W._note_read(result, dict(tool='read', state=dict(input=dict(filePath=raw))), work)
    assert result['files_read'] == []



def test_steps_are_eight_for_the_coder_and_four_for_the_reviewer(tmp_path, monkeypatch):
    work = tmp_path / 'wd'
    work.mkdir()
    seen = []
    monkeypatch.delenv('FACTORY_KILO_ENTRY', raising=False)
    monkeypatch.setattr(W.shutil, 'which', lambda name: 'kilo.exe')
    monkeypatch.setattr(W, 'run_owned', lambda args, **kw: (seen.append(json.loads(kw['env']['KILO_CONFIG_CONTENT'])),
                                                           subprocess.CompletedProcess(args, 0, b'', b''))[1])
    W.model_attempt(task(), work, 'google/x', 5, prompt_override='p')
    W.model_attempt(task(), work, 'google/x', 5, prompt_override='p', steps=W.REVIEW_STEPS)
    assert [c['agent']['factory']['steps'] for c in seen] == [8, 4]




def test_policy_lets_the_agent_search_inside_its_copy_and_nowhere_else():
    perm = W.worker_policy(task())['permission']
    assert perm['grep'] == perm['glob'] == perm['list'] == 'allow'
    assert perm['external_directory'] == 'deny' and perm['bash'] == 'deny' and perm['*'] == 'deny'
    assert set(perm['edit']) == {'*', '**/calc.py'} and perm['edit']['*'] == 'deny'
    assert perm['read']['*.' + 'env'] == 'deny' and perm['read']['**/*.' + 'env'] == 'deny'


def test_the_prompt_says_where_the_files_are_and_how_to_find_things(rig):
    rig.once()
    for prompt in rig.prompts[:2]:
        assert 'working directory' in prompt and 'calc.py' in prompt and 'tests/test_calc.py' in prompt
    coder = rig.prompts[0]
    assert 'read tool' in coder and 'grep' in coder and 'outside' in coder


def test_the_goal_is_scrubbed_of_local_paths(rig):
    t = F.read_plan(json.loads(rig.plan.read_text()))['T1']
    text = W.build_coder_prompt(t, {'calc.py': b'x = 1\n'}, goal='look at ' + WINHOME + r'Q\AppData\work\f.py first')
    assert 'Users' not in text and 'Task text:\nlook at ~' in text


def test_the_previous_diff_is_deliberately_shown_verbatim(rig):
    """It is the user's own code under relative a/ b/ names; scrubbing it would corrupt the diff."""
    t = F.read_plan(json.loads(rig.plan.read_text()))['T1']
    diff = '--- a/calc.py\n+++ b/calc.py\n+x = "' + WINHOME + 'Q\\f"\n'
    text = W.build_coder_prompt(t, {'calc.py': b'x = 1\n'}, prev_diff=diff)
    assert diff in text


def test_the_logged_reason_is_scrubbed_too(rig):
    user = 'Zq7unique'
    rig.mp.setenv('USERPROFILE', WINHOME + user)
    rig.mp.setenv('HOME', WINHOME + user)
    rig.review_script = [verdict(False, ['the file %s breaks it' % (Path.home() / 'x.py')])]
    result = rig.once()
    assert user not in result['reason'] and user not in json.dumps(rig.state()['tasks']['T1']['feedback'])


def test_inside_staging_is_false_when_resolve_leads_outside_even_without_symlink_flags(tmp_path, monkeypatch):
    stage = tmp_path / 'stage'
    (stage / 'task-link').mkdir(parents=True)
    outside = (tmp_path / 'outside').resolve()
    outside.mkdir()
    real = Path.resolve
    monkeypatch.setattr(Path, 'is_symlink', lambda self: False)
    monkeypatch.setattr(Path, 'resolve', lambda self, *a, **k: outside if self.name == 'task-link' else real(self, *a, **k))
    assert W.inside_staging(stage / 'task-link', stage) is False



@pytest.mark.parametrize('case', ['gate_unknown', 'transient', 'reviewer_failed', 'provider_error', 'region'])
def test_task_or_model_trouble_never_counts_toward_the_loop_brake(rig, case):
    if case == 'gate_unknown':
        rig.run_tests_fn = lambda root, tests, timeout_s: G.GateResult(-1, 0, 0, 0, 0, 0, False, 'timeout')
    elif case == 'transient':      # every model of the hop chain is overloaded: only then the pass is deferred
        rig.coder_script = [(1, error_out(503), b'')] * (1 + W.TRANSIENT_HOPS)
    elif case == 'reviewer_failed':
        rig.review_script = [(0, ev(dict(type='text', part=dict(text='prose, not json')), finish()), b'')]
    elif case == 'provider_error':
        rig.coder_script = [(1, error_out(400, message='bad request'), b'')]
    else:
        rig.coder_script = [(1, error_out(403, message='User location is not supported'), b'')]
    result = rig.once()
    assert result['status'] == 'READY' and result['reason'] == case and result['infra'] is False


def test_an_escalated_block_is_not_infrastructure(rig):
    rig.run_tests_fn = lambda root, tests, timeout_s: G.GateResult(-1, 0, 0, 0, 0, 0, False, 'timeout')
    for _ in range(3):
        result = rig.once()
        rig.ready_again()
    assert result['status'] == 'BLOCKED' and result['reason'] == 'gate_unknown' and result['infra'] is False


@pytest.mark.parametrize('kind,body', [('key_invalid', error_out(400, message='API key not valid')),
                                       ('balance', error_out(402, message='negative balance')),
                                       ('model_missing', error_out(404, message='no such model'))])
def test_a_dead_channel_does_count_toward_the_brake(rig, kind, body):
    rig.coder_script = [(1, body, b'')]
    result = rig.once()
    assert result['reason'] == kind and result['infra'] is True


def test_a_permission_error_in_a_pass_is_a_transient_infrastructure_fault_not_a_task_block(rig):
    def boom(*a, **kw):
        raise PermissionError('antivirus holds the file')
    rig.mp.setattr(rig.w, 'candidate_tree', boom)
    result = rig.once()
    row = rig.state()['tasks']['T1']
    assert result['status'] == 'READY' and result['reason'] == 'os_error' and result['infra'] is True
    assert row['status'] == 'READY' and row['attempts'] == 0 and not rig.state().get('strikes')


def test_a_disk_error_while_copying_the_base_is_infrastructure_too(rig):
    rig.mp.setattr(rig.w.shutil, 'copytree', lambda *a, **kw: (_ for _ in ()).throw(OSError(28, 'no space left')))
    result = rig.once()
    assert result['status'] == 'READY' and result['reason'] == 'os_error' and result['infra'] is True


def test_other_exceptions_still_block_the_task(rig):
    def boom(*a, **kw):
        raise RuntimeError('a real bug')
    rig.mp.setattr(rig.w, 'candidate_tree', boom)
    result = rig.once()
    assert result['status'] == 'BLOCKED' and result['blocked_reason'] == 'worker_exception'
    assert result['infra'] is False



def test_a_stuck_os_error_is_retried_twice_as_infrastructure_then_blocks_the_task_without_infra(rig):
    def boom(*a, **kw):
        raise PermissionError('denied: ' + WINHOME + 'Zq9name\\proj\\a is held by a scanner')
    rig.mp.setattr(rig.w, 'candidate_tree', boom)
    results = []
    for _ in range(3):
        results.append(rig.once())
        rig.ready_again()
    assert [(r['status'], r['infra']) for r in results] == [('READY', True), ('READY', True), ('BLOCKED', False)]
    last = results[-1]
    assert last['blocked_reason'] == 'worker_exception'
    assert 'Zq9name' not in json.dumps(results) and len(last['reason_detail']) <= 200
    assert 'Zq9name' not in json.dumps(rig.state())


def test_a_multi_step_call_waits_when_fewer_than_three_requests_are_free(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    cfg = tmp_path / 'rpd5.json'
    cfg.write_text(json.dumps(dict(channels=[dict(c, rpd=5) for c in TWO_CHANNELS])))
    st = F.load_state(rig.state_path, F.read_plan(json.loads(rig.plan.read_text())))
    st['channel_quotas'] = {'p': {'request_times': [time.time()] * 3}}          # used = rpd - 2
    F.save_atomic(rig.state_path, st)
    result = rig.once(channel_config=cfg)
    assert result['status'] == 'WAITING_CHANNEL' and result['channel_reason'] == 'rpd' and rig.models == []


def test_an_empty_channel_set_counts_toward_the_brake(rig):
    def none(*a, **kw):
        raise C.ChannelUnavailable('no channels configured', 'no_channels', 3600)
    rig.mp.setattr(rig.w.channels, 'choose', none)
    first = rig.once()
    assert first['status'] == 'WAITING_CHANNEL' and first['channel_reason'] == 'no_channels' and first['infra'] is True


def test_a_missing_key_counts_toward_the_brake(rig):
    rig.mp.delenv('KEY')
    result = rig.once()
    assert result['status'] == 'WAITING_CHANNEL' and result['channel_reason'] == 'no_key' and result['infra'] is True



def test_a_staging_path_that_holds_the_profile_name_is_refused_before_kilo_runs(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    monkeypatch.setattr(rig.w, 'profile_names', lambda: ('Zq5name',))
    bad = tmp_path / 'ZQ5NAME' / 'stage'                                  # the check ignores case
    with pytest.raises(F.InvalidPlan, match='профил'):
        rig.once(staging=bad)
    assert rig.models == []
    assert 'Zq5name' not in str(pytest.raises(F.InvalidPlan, rig.once, staging=bad).value)   # the name is not echoed
    assert rig.once()['status'] == 'REVIEW'                               # a path without the name passes


def test_the_profile_names_come_from_home_and_username(monkeypatch):
    monkeypatch.setenv('USERNAME', 'Zq5login')
    assert 'Zq5login' in W.profile_names() and Path.home().name in W.profile_names()


def test_kilo_home_lives_next_to_the_work_copy_inside_staging_and_is_removed(tmp_path, monkeypatch):
    stage = tmp_path / 'stage'
    work = stage / 'task-T1-aaaa'
    work.mkdir(parents=True)
    seen = {}
    monkeypatch.delenv('FACTORY_KILO_ENTRY', raising=False)
    monkeypatch.setattr(W.shutil, 'which', lambda name: 'kilo.exe')

    def run(args, **kw):
        seen['home'] = Path(kw['env']['HOME'])
        seen['existed'] = seen['home'].is_dir()
        return subprocess.CompletedProcess(args, 0, b'', b'')
    monkeypatch.setattr(W, 'run_owned', run)
    W.model_attempt(task(), work, 'google/x', 5, prompt_override='p')
    home = seen['home']
    assert seen['existed'] and home.parent == stage and not home.is_relative_to(work)   # beside the copy, not inside
    assert 'Temp' not in str(home) or str(stage) in str(home)
    assert not home.exists()                                                           # removed after the call


def test_the_reviewer_scratch_directory_is_inside_staging_too(tmp_path):
    root = tmp_path / 'w'
    (root / 'tests').mkdir(parents=True)
    (root / 'calc.py').write_text('x = 1\n')
    (root / 'tests/test_calc.py').write_text('def test_a(): pass\n')
    scratch = tmp_path / 'stage'
    scratch.mkdir()
    seen = []

    def invoke(reviewer, directory, model, **kwargs):
        seen.append(Path(directory))
        return 0, verdict(True), b''
    W.review_candidate(task(), root, 'google/y', invoke, scratch=scratch)
    assert seen and seen[0].is_relative_to(scratch)


def test_a_unit_test_without_the_marker_line_is_rejected_with_the_exact_instruction(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch, kind='unit_test')
    rig.marker = False
    result = rig.once()
    assert result['status'] == 'READY' and result['reason'].startswith('gate')
    feedback = rig.state()['tasks']['T1']['feedback'][-1]['text']
    assert '# factory-backlog-id: BL1' in feedback
    assert not (rig.tmp / 'stage' / 'for-review' / 'T1').exists()


def test_a_unit_test_with_the_marker_is_accepted_and_the_prompt_names_the_line(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch, kind='unit_test')
    result = rig.once()
    assert result['status'] == 'REVIEW', result
    assert '# factory-backlog-id: BL1' in rig.prompts[0]


def test_worker_policy_documents_that_grep_sees_everything_in_the_copy():
    import inspect
    assert 'grep sees EVERYTHING' in inspect.getsource(W.worker_policy)


REAL_PROFILE_NAMES = W.profile_names     # captured at import: the rig patches W.profile_names per test


def test_a_multi_step_call_with_a_tiny_daily_limit_is_not_blocked_by_the_booking(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    cfg = tmp_path / 'rpd3.json'
    cfg.write_text(json.dumps(dict(channels=[dict(c, rpd=3) for c in TWO_CHANNELS])))
    # ACCEPTED LIMIT of the contract: coder and reviewer share one quota group, so with rpd=3 the reviewer waits a
    # whole day (it needs min(3, rpd) free requests and only 2 are left)
    result = rig.once(channel_config=cfg)    # the 10-request booking is bigger than the whole day limit
    assert [coder for coder, _ in rig.models] == [True]                     # the coder DID run
    assert len(rig.state()['channel_quotas']['p']['request_times']) == 1    # one real step: the rest went back
    assert result['status'] == 'WAITING_CHANNEL'                            # the reviewer needs 3 free requests: 2 are left


def test_with_room_for_a_second_call_the_whole_pass_runs(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    cfg = tmp_path / 'rpd14.json'      # the coder run needs 9 requests of the day, the reviewer run 5
    cfg.write_text(json.dumps(dict(channels=[dict(c, rpd=14) for c in THREE_CHANNELS])))
    assert rig.once(channel_config=cfg)['status'] == 'REVIEW'
    assert len(rig.state()['channel_quotas']['p']['request_times']) == 2      # the coder and critic 1 (critic 2: p3)


def test_a_channel_with_rpm_and_rpd_of_two_runs_the_coder(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    cfg = tmp_path / 'tiny.json'
    cfg.write_text(json.dumps(dict(channels=[dict(c, rpm=2, rpd=2) for c in TWO_CHANNELS])))
    rig.once(channel_config=cfg)
    assert [coder for coder, _ in rig.models][0] is True and rig.state()['tasks']['T1']['status'] != 'BLOCKED'
    assert len(rig.state()['channel_quotas']['p']['request_times']) == 1   # booking reconciled to the one real step: not below zero


def test_every_temporary_directory_of_a_pass_lives_inside_staging(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    seen = {}
    original = rig._model

    def spy(t, directory, name, timeout, **kwargs):
        seen['tmp'] = Path(tempfile.gettempdir()).resolve()
        seen['env'] = (os.environ['TEMP'], os.environ['TMP'])
        return original(t, directory, name, timeout, **kwargs)
    monkeypatch.setattr(rig.w, 'model_attempt', spy)
    before = tempfile.gettempdir()
    rig.once()
    stage = (rig.tmp / 'stage').resolve()
    assert seen['tmp'] == stage / 'tmp' and seen['env'] == (str(stage / 'tmp'),) * 2
    assert Path(rig.runs[0][0]).resolve().is_relative_to(stage / 'tmp')      # the base copy is not under %TEMP%
    assert tempfile.gettempdir() == before                                   # restored for the rest of the process


def test_old_scratch_orphans_are_swept_inside_staging_only(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    stage = rig.tmp / 'stage'
    old_home, old_review, old_tmp = stage / 'factory-kilo-home-xx', stage / 'factory-review-yy', stage / 'tmp' / 'orphan'
    fresh = stage / 'factory-kilo-home-zz'
    for d in (old_home, old_review, old_tmp, fresh):
        d.mkdir(parents=True)
    for d in (old_home, old_review, old_tmp):
        aged(d, 2 * 86400)
    rig.once()
    assert not (old_home.exists() or old_review.exists() or old_tmp.exists()) and fresh.exists()


def test_the_profile_lock_compares_whole_path_segments(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    monkeypatch.setattr(rig.w, 'profile_names', lambda: ('an', 'dev'))
    assert rig.w.staging_reveals_profile(tmp_path / 'agent-factory' / 'echo') is False   # substrings of other words
    monkeypatch.setattr(rig.w, 'profile_names', lambda: ('Zq5name',))
    assert rig.w.staging_reveals_profile(tmp_path / 'ZQ5NAME' / 'x') is True
    assert rig.w.staging_reveals_profile(tmp_path / 'Zq5names' / 'x') is False


def test_one_pass_runs_with_the_real_profile_names_and_a_staging_outside_the_profile(tmp_path, monkeypatch):
    base = Path(os.environ.get('SystemDrive', 'C:') + os.sep) / 'agent-factory'
    try:
        base.mkdir(exist_ok=True)
        neutral = base / ('unit-' + tmp_path.name.replace('_', '-'))
        neutral.mkdir()
    except OSError:
        pytest.skip('no writable directory outside the profile on this machine')
    try:
        rig = Rig(tmp_path, monkeypatch)
        monkeypatch.setattr(rig.w, 'profile_names', REAL_PROFILE_NAMES)
        assert rig.w.staging_reveals_profile(neutral) is False
        assert rig.once(staging=neutral / 'stage')['status'] == 'REVIEW'
    finally:
        shutil_rmtree(neutral)


def shutil_rmtree(path):
    import shutil
    shutil.rmtree(path, ignore_errors=True)


def test_os_errors_have_their_own_series_apart_from_provider_server_errors(rig):
    rig.coder_script = [(1, error_out(503), b'')] * (1 + W.TRANSIENT_HOPS)   # every hop overloaded: transient streak 1
    assert rig.once()['reason'] == 'transient'
    rig.ready_again()
    rig.coder_script = []
    rig.edit_state(lambda s: s['tasks']['T1'].update(defer_streak={'reason': 'transient', 'n': 2}))

    def boom(*a, **kw):
        raise PermissionError('held')
    rig.mp.setattr(rig.w, 'candidate_tree', boom)
    result = rig.once()
    assert result['status'] == 'READY' and result['reason'] == 'os_error' and result['infra'] is True


def test_the_unit_test_marker_is_read_from_the_first_changed_test_file_before_pytest_runs(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch, kind='unit_test')
    rig.marker = False
    result = rig.once()
    assert result['status'] == 'READY' and '# factory-backlog-id: BL1' in rig.state()['tasks']['T1']['feedback'][-1]['text']
    assert rig.runs == []                                 # rejected before any pytest run


def test_a_unit_test_without_a_backlog_id_skips_the_marker_with_an_event(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch, kind='unit_test', backlog_id='')
    rig.marker = False
    result = rig.once()
    assert result['status'] == 'REVIEW' and 'unit_test_marker_skipped' in result['events']


def test_the_message_of_a_fault_is_scrubbed_before_it_is_cut(rig):
    rig.coder_script = [(1, error_out(400, message='y' * 285 + ' ' + WINHOME + r'Zq9name\proj\a.py'), b'')]
    result = rig.once()
    assert 'Zq9' not in json.dumps(result)


# ---- round 10 ----------------------------------------------------------------------------------------------

def test_the_gate_tree_directory_ignores_cleanup_errors_so_a_held_file_cannot_hide_the_verdict(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    seen = []
    original = tempfile.TemporaryDirectory

    def spy(*args, **kwargs):
        seen.append(dict(kwargs))
        return original(*args, **kwargs)
    monkeypatch.setattr(tempfile, 'TemporaryDirectory', spy)
    rig.once()
    gate_dirs = [k for k in seen if str(k.get('prefix', '')).startswith('factory-gate-tree-')]
    assert gate_dirs and all(k.get('ignore_cleanup_errors') is True for k in gate_dirs)


def test_a_failing_base_holder_is_infrastructure_not_an_uncaught_crash(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    real = tempfile.mkdtemp

    def boom(*args, **kwargs):
        if kwargs.get('prefix') == 'factory-base-':
            raise PermissionError('antivirus')
        return real(*args, **kwargs)
    monkeypatch.setattr(tempfile, 'mkdtemp', boom)
    result = rig.once()
    assert result['status'] == 'READY' and result['reason'] == 'os_error' and result['infra'] is True


def test_the_reservation_cap_looks_only_at_live_channels(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch, title='Fix add', read_files=['dep.py'])
    (rig.root / 'calc.py').write_text(big_module(700))
    (rig.root / 'dep.py').write_text('# ' + 'q' * 30000 + '\ndef helper(): return 1\n')
    cfg = rig.tmp / 'live.json'
    big_dead = dict(id='big', group='pb', model='google/x', key_env='NO_SUCH_KEY_ENV', tpm=400000, rpd=100, verified=True)
    small_live = dict(id='small', group='ps', model='google/y', key_env='KEY', tpm=16000, rpd=100, verified=True)
    cfg.write_text(json.dumps(dict(channels=[big_dead, small_live])))
    result = rig.once(channel_config=cfg)
    assert [coder for coder, _ in rig.models][:1] == [True]                 # the coder ran on the live channel
    assert result['calls'][0]['reserved_tokens'] == 16000 and 'reservation_capped' in result['events']


def test_a_reservation_that_no_live_channel_can_take_is_a_config_fault_for_the_brake(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)

    def refuse(*args, **kwargs):
        raise rig.w.channels.ChannelUnavailable('x', 'reservation_exceeds_tpm', 3600)
    monkeypatch.setattr(rig.w.channels, 'choose', refuse)
    result = rig.once()
    assert result['status'] == 'WAITING_CHANNEL' and result['infra'] is True


def test_an_os_error_before_the_pass_starts_is_released_not_raised(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)

    def boom(*args, **kwargs):
        raise PermissionError('antivirus holds the staging folder')
    monkeypatch.setattr(rig.w, 'sweep_scratch', boom)
    result = rig.once()
    assert result['status'] == 'READY' and result['reason'] == 'os_error' and result['infra'] is True
    assert rig.models == []


def test_a_failed_sweep_leaves_a_trace_in_the_events(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    stage = rig.tmp / 'stage'
    held = stage / 'factory-kilo-home-held'
    held.mkdir(parents=True)
    aged(held, 2 * 86400)
    real = shutil.rmtree

    def fake(path, ignore_errors=False, onerror=None, *, onexc=None, **kwargs):
        if Path(path).name == 'factory-kilo-home-held' and onexc is not None:
            onexc(os.rmdir, str(path), PermissionError('held'))
            return
        return real(path, ignore_errors=ignore_errors, onerror=onerror, onexc=onexc, **kwargs)
    monkeypatch.setattr(shutil, 'rmtree', fake)
    result = rig.once()
    assert 'sweep_failed' in result['events'] and held.exists()


def test_the_sweep_skips_junctions(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    stage = rig.tmp / 'stage'
    junction = stage / 'factory-review-junc'
    junction.mkdir(parents=True)
    aged(junction, 2 * 86400)
    original = os.path.isjunction
    monkeypatch.setattr(os.path, 'isjunction', lambda p: Path(p).name == 'factory-review-junc' or original(p))
    rig.once()
    assert junction.exists()


def test_seam_os_error_is_a_whitelisted_defer_reason_in_agent_factory():
    assert 'os_error' in F.DEFER_REASONS     # the runner defers OS faults under this name


# ---- round 11: telemetry, booking facts, tiers through the runner -----------------------------------------

def step(i=0, o=0, r=0, cr=0, cw=0):
    return dict(type='step_finish', part=dict(reason='tool-calls', tokens=dict(
        input=i, output=o, reasoning=r, cache=dict(read=cr, write=cw))))


def writing(stream):
    def script(directory):
        (directory / 'calc.py').write_text('def add(a,b): return a+b\n')
        return 0, stream, b''
    return script


def test_call_telemetry_keeps_every_token_kind_apart_and_the_channel_state_equals_the_fact(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    cfg = tmp_path / 'rpm.json'
    cfg.write_text(json.dumps(dict(channels=[dict(c, rpm=30) for c in TWO_CHANNELS])))
    rig.coder_script = [writing(ev(step(1000, 50, 7, 200, 30), step(1300, 60, 0, 900, 0), step(1500, 80, 3, 900, 0)))]
    result = rig.once(channel_config=cfg)
    first = result['calls'][0]
    assert first['steps'] == 3 and first['input_tokens'] == 3800 and first['output_tokens'] == 190
    assert first['reasoning_tokens'] == 10 and first['cache_read_tokens'] == 2000 and first['cache_write_tokens'] == 30
    assert first['actual_input_tokens'] == 3800 + 2000 + 30           # what the provider counted against TPM
    assert first['actual_tokens'] == 3800 + 2000 + 30 + 190 + 10
    group = rig.state()['channel_quotas']['p']
    facts = [max(1, c['steps']) for c in result['calls']]
    assert len(group['request_times']) == sum(facts) and len(group['rpm_times']) == sum(facts)
    assert sum(n for _, n in group['minute']) == sum(c['actual_input_tokens'] for c in result['calls'])


def test_a_stream_without_usage_is_recorded_as_unknown_not_zero(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    rig.coder_script = [writing(ev(dict(type='step_finish', part=dict(reason='stop'))))]
    first = rig.once()['calls'][0]
    for key in ('input_tokens', 'output_tokens', 'reasoning_tokens', 'cache_read_tokens', 'cache_write_tokens',
                'actual_input_tokens', 'actual_tokens'):
        assert first[key] is None, key


def test_the_booking_is_what_the_choice_checked(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    cfg = tmp_path / 'rpm5.json'
    cfg.write_text(json.dumps(dict(channels=[dict(c, rpm=5, rpd=100) for c in TWO_CHANNELS])))
    seen = {}
    real = rig.w.channels.reserve

    def spy(state, channel, tokens, **kw):
        seen.setdefault('requests', kw.get('requests'))
        return real(state, channel, tokens, **kw)
    monkeypatch.setattr(rig.w.channels, 'reserve', spy)
    rig.once(channel_config=cfg)
    assert seen['requests'] == rig.w.requests_for(rig.w.PROVIDER_STEPS)      # the same count choose() was asked about


def test_the_runner_sends_the_review_to_the_small_channel_first(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    main = dict(TWO_CHANNELS[0])
    other = dict(id='c3', group='p3', model='google/z', key_env='KEY', tpm=100000, rpd=100, verified=True)
    small = dict(id='c2', group='p2', model='google/y', key_env='KEY', tpm=100000, rpd=100, tier='small', verified=True)
    cfg = tmp_path / 'review.json'
    cfg.write_text(json.dumps(dict(channels=[main, other, small])))
    rig.once(channel_config=cfg)
    # the small channel reviews first; the chain's second critic is the remaining model (owner: a sequential
    # chain of critics, each another model)
    assert [name for _, name in rig.models] == ['google/x', 'google/y', 'google/z']


def test_a_second_coder_attempt_goes_to_the_escalation_channel(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    main = dict(TWO_CHANNELS[0])
    big = dict(id='c3', group='p3', model='google/z', key_env='KEY', tpm=100000, rpd=100, tier='escalation', verified=True)
    cfg = tmp_path / 'escalate.json'
    cfg.write_text(json.dumps(dict(channels=[main, big])))
    rig.coder_script = ['bad']
    rig.once(channel_config=cfg)
    rig.ready_again()
    rig.once(channel_config=cfg)
    coders = [name for is_coder, name in rig.models if is_coder]
    assert coders[0] == 'google/x' and coders[1] == 'google/z'


def test_a_call_that_slept_in_kilo_cools_the_channel_without_infra_or_a_strike(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    rig.coder_script = [(124, b'', b'worker-timeout')]
    result = rig.once()
    row = rig.state()['tasks']['T1']
    assert result['status'] == 'READY' and result['reason'] == 'rate_minute' and result['infra'] is False
    assert 'rate_limited_suspect' in result['events'] and row['attempts'] == 0 and not rig.state().get('strikes')
    assert rig.state()['channel_quotas']['channel_cool']['c1'] > time.time() + 600


def test_a_busy_worker_that_times_out_is_still_a_blocked_timeout(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    busy = ev(dict(type='tool_use', part=dict(tool='read', state=dict(status='completed', input={}))), step(100, 5))
    rig.coder_script = [(124, busy, b'worker-timeout')]
    result = rig.once()
    assert result['status'] == 'BLOCKED' and result['reason'] == 'worker_timeout' and result['infra'] is True


def test_a_failed_call_keeps_the_whole_booking_because_kilo_retried_inside(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    rig.coder_script = [(1, error_out(418, message='teapot'), b'')]
    result = rig.once()
    assert result['reason'] == 'provider_error'
    group = rig.state()['channel_quotas']['p']
    assert len(group['request_times']) == rig.w.requests_for(rig.w.PROVIDER_STEPS)       # nothing returned


def test_an_unknown_fact_keeps_the_booking(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    rig.coder_script = [writing(b'')]                                    # exit 0, no step_finish at all
    rig.once()
    group = rig.state()['channel_quotas']['p']
    coder_requests = [t for t in group['request_times']]
    assert len(coder_requests) >= rig.w.requests_for(rig.w.PROVIDER_STEPS)


def test_a_task_too_big_for_the_budget_is_blocked_not_a_channel_fault(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    body = {'error': {'code': 402, 'message': 'x', 'metadata': {'limit_source': 'weight_exceeds_budget'}}}
    rig.coder_script = [(1, error_out(402, body=body), b'')]
    result = rig.once()
    assert result['status'] == 'BLOCKED' and result['reason'] == 'context_too_large' and result['infra'] is False
    assert 'cool_until' not in rig.state()['channel_quotas'].get('p', {})


def test_a_last_step_without_tools_and_without_an_edit_is_steps_exhausted(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    steps = [step(100, 5) for _ in range(rig.w.PROVIDER_STEPS)]
    rig.coder_script = [(0, ev(*steps), b'')]
    result = rig.once()
    assert result['reason'] == 'gate:steps_exhausted' and 'steps_exhausted' in result['events']
    assert rig.state()['strikes'] == {'bl:BL1': 1}          # exactly one strike (D's whitelist has no free reason yet)


@pytest.mark.parametrize('name', ['AGENTS.md', 'agents.md', 'opencode.json', 'opencode.jsonc', 'kilo.json',
                                  'kilo.jsonc', '.opencode/x.py', '.kilo/a.py', 'pkg/AGENTS.md'])
def test_agent_config_names_are_refused_by_safe_path_alone(tmp_path, name):
    with pytest.raises(F.InvalidPlan):       # one owner of the rule: agent_factory.safe_path / DENY_PARTS
        F.read_plan([dict(id='T', title='t', touch_files=['a.py'], read_files=[name], tests=[], privacy_safe=True)])


def test_the_agent_config_key_set_is_locked():
    cfg = W.kilo_config('google', 'GOOGLE_GENERATIVE_AI_API_KEY', 8)
    assert set(cfg) == {'provider', 'enabled_providers', 'agent'}
    assert set(cfg['agent']['factory']) == {'description', 'mode', 'steps'}      # no prompt/system until the canary says so
    assert cfg['agent']['factory']['steps'] == 8 and cfg['enabled_providers'] == ['google']


def test_run_owned_gives_the_worker_no_stdin_and_a_memory_limited_job():
    from tools import factory_process as P
    assert P.JOB_LIMIT_FLAGS == 0x2000 | 0x100 and P.JOB_PROCESS_MEMORY_BYTES == 1536 * 1024 * 1024
    seen = {}
    real = subprocess.Popen

    class Spy(real):
        def __init__(self, *args, **kwargs):
            seen.update(kwargs)
            super().__init__(*args, **kwargs)
    old = P.subprocess.Popen
    P.subprocess.Popen = Spy
    try:
        done = P.run_owned([sys.executable, '-c', 'import sys; print(repr(sys.stdin.read()))'],
                           cwd=os.getcwd(), env=dict(os.environ), timeout=20)
    finally:
        P.subprocess.Popen = old
    assert seen['stdin'] == subprocess.DEVNULL and done.stdout.strip() == b"''"


# ---- round 12 -----------------------------------------------------------------------------------------------

def next_pass(rig):
    """Back to READY like the loop does after the wait, but WITHOUT wiping the quota state."""
    def fn(s):
        s['tasks']['T1']['not_before'] = 0
        s.get('channel_quotas', {}).pop('channel_cool', None)
        for group in s.get('channel_quotas', {}).values():
            if isinstance(group, dict):
                group.pop('cool_until', None)
    rig.edit_state(fn)


def test_idle_timeouts_are_rate_limits_up_to_the_allowance_and_the_next_is_infrastructure(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    allowed = rig.w.IDLE_SUSPECTS_ALLOWED       # 21.11: 4 (was 2, the third in a row was infrastructure)
    assert allowed == 4
    rig.coder_script = [(124, b'', b'worker-timeout')] * (allowed + 1)
    first = rig.once()
    assert first['reason'] == 'rate_minute' and first['infra'] is False
    for _ in range(allowed - 1):
        next_pass(rig)
        assert rig.once()['reason'] == 'rate_minute'
    next_pass(rig)
    last = rig.once()
    assert last['status'] == 'BLOCKED' and last['reason'] == 'worker_timeout' and last['infra'] is True


def test_a_real_step_resets_the_idle_counter(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    busy = ev(step(100, 5))
    rig.coder_script = [(124, b'', b''), (124, b'', b''), (124, busy, b''), (124, b'', b'')]
    assert rig.once()['reason'] == 'rate_minute'
    next_pass(rig)
    assert rig.once()['reason'] == 'rate_minute'
    next_pass(rig)
    assert rig.once()['reason'] == 'worker_timeout'            # a worker that DID something and timed out: real timeout
    rig.edit_state(lambda s: s['tasks']['T1'].update(status='READY', not_before=0, blocked_reason=None))
    rig.edit_state(lambda s: [g.pop('cool_until', None) for g in s['channel_quotas'].values() if isinstance(g, dict)])
    rig.edit_state(lambda s: s['channel_quotas'].pop('channel_cool', None))
    result = rig.once()
    assert result['reason'] == 'rate_minute'                    # the counter started again from zero


def test_the_third_idle_reviewer_timeout_on_one_task_parks_it_as_reviewer_failed(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    allowed = rig.w.IDLE_SUSPECTS_ALLOWED
    rig.review_script = [(124, b'', b'')] * (allowed + 1)
    seen = []
    for _ in range(allowed + 1):
        seen.append(rig.once()['status'])
        next_pass(rig)
    row = rig.state()['tasks']['T1']
    assert seen == ['READY'] * allowed + ['BLOCKED'] and row['blocked_reason'] == 'reviewer_failed'
    parked = rig.tmp / 'stage' / 'parked' / 'T1.diff'
    assert parked.is_file() and 'a+b' in parked.read_text(encoding='utf-8')      # the paid candidate is kept


def test_the_day_window_covers_the_whole_run(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    cfg = tmp_path / 'rpd.json'
    cfg.write_text(json.dumps(dict(channels=[dict(c, rpd=100) for c in TWO_CHANNELS])))
    seen = []
    real = rig.w.channels.reserve

    def spy(state, channel, tokens, **kw):
        seen.append(kw.get('requests'))
        return real(state, channel, tokens, **kw)
    monkeypatch.setattr(rig.w.channels, 'reserve', spy)
    rig.once(channel_config=cfg)
    assert seen[0] == rig.w.PROVIDER_STEPS + 1 and seen[1] == rig.w.REVIEW_STEPS + 1


def test_four_requests_left_today_refuse_a_coder_run_of_eight_steps(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    cfg = tmp_path / 'left4.json'
    cfg.write_text(json.dumps(dict(channels=[dict(c, rpd=104) for c in TWO_CHANNELS])))
    st = F.load_state(rig.state_path, F.read_plan(json.loads(rig.plan.read_text())))
    st['channel_quotas'] = {'p': {'request_times': [time.time()] * 100}}
    F.save_atomic(rig.state_path, st)
    result = rig.once(channel_config=cfg)
    assert result['status'] == 'WAITING_CHANNEL' and result['channel_reason'] == 'rpd' and rig.models == []


def test_a_failure_without_usage_keeps_the_token_booking(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    rig.coder_script = [(1, error_out(418, message='teapot'), b'')]
    result = rig.once()
    reserved = result['calls'][0]['reserved_tokens']
    assert [n for _, n in rig.state()['channel_quotas']['p']['minute']] == [reserved]


def test_a_recovered_stream_error_does_not_discard_a_finished_edit(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    errored = dict(type='step_finish', part=dict(reason='error', error=dict(code=500)))
    rig.coder_script = [writing(ev(errored, finish(9000, 500)))]
    result = rig.once()
    assert result['status'] == 'REVIEW' and result['reason'] is None


def test_every_gate_run_keeps_its_temp_inside_the_staging_tmp(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    rig.once()
    stage_tmp = (rig.tmp / 'stage' / 'tmp').resolve()
    assert len(rig.gate_workdirs) >= 2 and None not in rig.gate_workdirs          # red_before included
    assert all(Path(w).resolve() == stage_tmp for w in rig.gate_workdirs)
    assert rig.gate_waits[0] == rig.w.RED_BEFORE_WAIT_S                         # red_before: its own ceiling


def slot_failure():
    import dataclasses
    return dataclasses.replace(G.GateResult(-1, 0, 0, 0, 0, 0, False, 'pytest not started: no RAM'),
                               env_reason='pytest slot: no free RAM above 2 GB')


def test_a_gate_without_a_pytest_slot_is_released_not_a_strike_and_the_candidate_is_kept(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    calls = []

    def run(root, tests, timeout_s):
        calls.append(root)
        return rig._default_run_tests(root, tests, timeout_s) if len(calls) == 1 else slot_failure()
    rig.run_tests_fn = run          # red_before is the first call (a real red); the candidate run finds no slot
    result = rig.once()
    row = rig.state()['tasks']['T1']
    assert result['status'] == 'READY' and result['reason'] == 'transient' and result['infra'] is False
    assert 'env_shortage' in result['events'] and 'pytest slot' in result['reason_detail']
    assert not rig.state().get('strikes') and row['attempts'] == 0 and row.get('pending_review')
    assert not row.get('feedback')                                   # the model is told nothing about it
    assert len([c for c, _ in rig.models if c]) == 1                  # the paid coder attempt is not repeated


def test_an_env_prefixed_gate_verdict_is_released_too(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    monkeypatch.setattr(rig.w.gate, 'accept', lambda base, cand, red: (False, 'env: no tests collected here'))
    result = rig.once()
    assert result['reason'] == 'transient' and not rig.state().get('strikes')


def test_the_slot_wait_is_one_budget_for_the_whole_pass(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    monkeypatch.setattr(rig.w, 'neighbor_tests', lambda root, task: ['tests/test_neighbor.py'])
    (rig.root / 'tests/test_neighbor.py').write_text('def test_n(): pass' + chr(10))
    rig.once()
    waits = rig.gate_waits[1:]
    assert waits and waits[0] <= rig.w.SLOT_BUDGET_S and waits == sorted(waits, reverse=True)


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def slot_rig(tmp_path, monkeypatch, first_gate_takes, coder_takes=400):
    rig = Rig(tmp_path, monkeypatch)
    clock = Clock()
    monkeypatch.setattr(rig.w, '_now', clock)       # the runner's own clock, not the global time module
    monkeypatch.setattr(rig.w, 'neighbor_tests', lambda root, task: ['tests/test_neighbor.py'])
    (rig.root / 'tests/test_neighbor.py').write_text('def test_n(): pass' + chr(10))
    rig.coder_script = [lambda directory: (clock.__setattr__('t', clock.t + coder_takes),
                                           (directory / 'calc.py').write_text('def add(a,b): return a+b' + chr(10)),
                                           (0, ev(finish()), b''))[2]]
    calls = []

    def run(root, tests, timeout_s):
        calls.append(len(calls))
        if len(calls) == 2:                   # the candidate run (the first call is red_before)
            clock.t += first_gate_takes
        return rig._default_run_tests(root, tests, timeout_s)
    rig.run_tests_fn = run
    return rig


def test_the_slot_budget_counts_waiting_not_the_run_time_of_the_gates(tmp_path, monkeypatch):
    rig = slot_rig(tmp_path, monkeypatch, first_gate_takes=120)
    rig.once()
    waits = rig.gate_waits[1:]                                  # [0] is red_before, which has its own ceiling
    assert waits[0] == rig.w.SLOT_BUDGET_S                      # the 400 s of the coder call did not eat it
    assert waits[1] == rig.w.SLOT_BUDGET_S                      # nor did the 120 s the first gate run took (<id> pool)


def test_a_long_gate_run_does_not_spend_the_slot_budget(tmp_path, monkeypatch):
    rig = slot_rig(tmp_path, monkeypatch, first_gate_takes=500)
    rig.once()
    waits = rig.gate_waits[1:]
    assert waits[0] == rig.w.SLOT_BUDGET_S and waits[1] == rig.w.SLOT_BUDGET_S    # only waiting is spent (test_factory_pool_runner)


def test_env_shortages_never_block_the_task_or_delete_the_candidate(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    state = {'n': 0}

    def run(root, tests, timeout_s):
        state['n'] += 1
        return rig._default_run_tests(root, tests, timeout_s) if state['n'] == 1 else slot_failure()
    rig.run_tests_fn = run
    seen = []
    for _ in range(5):
        result = rig.once()
        seen.append((result['status'], result.get('reason')))
        assert result.get('reason'), result
        next_pass(rig)
    row = rig.state()['tasks']['T1']
    assert all(item == ('READY', 'transient') for item in seen)
    assert row['status'] == 'READY' and row.get('pending_review') and Path(row['pending_review']['workdir']).exists()
    assert len([c for c, _ in rig.models if c]) == 1            # the paid coder call happened once


def test_many_env_shortages_in_a_row_get_a_long_hold_but_still_keep_the_candidate(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    state = {'n': 0}

    def run(root, tests, timeout_s):
        state['n'] += 1
        return rig._default_run_tests(root, tests, timeout_s) if state['n'] == 1 else slot_failure()
    rig.run_tests_fn = run
    waits = []
    for _ in range(rig.w.ENV_HOLD_AFTER + 1):
        result = rig.once()
        assert result.get('wait_s'), result
        waits.append(result['wait_s'])
        next_pass(rig)
    assert waits[0] == rig.w.INFRA_DEFER_S and waits[-1] == rig.w.ENV_HOLD_S > waits[0]
    assert rig.state()['tasks']['T1'].get('pending_review')


def test_idle_counters_are_per_role_and_cleared_when_the_task_is_blocked(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    rig.coder_script = [(124, b'', b'')] * (rig.w.IDLE_SUSPECTS_ALLOWED + 1)
    for _ in range(rig.w.IDLE_SUSPECTS_ALLOWED + 1):
        rig.once()
        next_pass(rig)
        counters = rig.state().get('factory_env', {}).get('idle', {})
        assert not any(k.endswith(':review') for k in counters)
    assert counters == {} or all(not k.startswith('task:T1') for k in counters)    # BLOCKED cleared the task keys


def test_a_clean_call_resets_the_channel_idle_counter(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    rig.coder_script = [(124, b'', b'')]
    rig.once()
    assert rig.state()['factory_env']['idle'].get('task:T1:code') == 1
    next_pass(rig)
    rig.once()                                                  # a normal pass: coder ok, reviewer ok
    counters = rig.state().get('factory_env', {}).get('idle', {})
    assert not any(k.startswith('channel:') for k in counters) and 'task:T1:code' not in counters


def test_a_persistent_env_failure_is_parked_with_the_env_reason_after_three_passes_and_keeps_the_candidate(tmp_path, monkeypatch):
    import dataclasses
    rig = Rig(tmp_path, monkeypatch)
    state = {'n': 0}
    # a data file outside the repository: a real environment failure (an import the candidate broke is its own
    # defect since 19.11, see test_an_import_error_the_candidate_made_is_its_defect_not_the_environment)
    missing = "FileNotFoundError: [Errno 2] No such file or directory: '" + 'D' + ":/datasets/voice.bin'"
    broken = dataclasses.replace(G.GateResult(-1, 0, 0, 0, 0, 0, False, missing), env_reason=missing)

    def run(root, tests, timeout_s):
        state['n'] += 1
        return rig._default_run_tests(root, tests, timeout_s) if state['n'] % 2 == 1 else broken
    rig.run_tests_fn = run          # odd calls: red_before is fine; even calls: the candidate run fails by the environment
    seen = []
    for _ in range(3):
        seen.append(rig.once())
        next_pass(rig)
    assert [r['status'] for r in seen] == ['READY', 'READY', 'BLOCKED']
    assert seen[0]['reason'] == 'transient' and seen[2]['reason'] == 'gate_unknown' and seen[2]['infra'] is False
    assert 'voice.bin' in seen[2]['reason_detail'] and 'ENV' in seen[2]['reason_detail']
    assert not rig.state().get('strikes')
    parked = rig.tmp / 'stage' / 'parked' / 'T1.diff'
    assert parked.is_file() and 'a+b' in parked.read_text(encoding='utf-8')         # the paid candidate is kept


def test_a_missing_pytest_slot_never_reaches_the_ceiling(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    state = {'n': 0}

    def run(root, tests, timeout_s):
        state['n'] += 1
        return rig._default_run_tests(root, tests, timeout_s) if state['n'] == 1 else slot_failure()
    rig.run_tests_fn = run
    results = []
    for _ in range(6):
        results.append(rig.once()['status'])
        next_pass(rig)
    assert results == ['READY'] * 6


def test_an_env_prefixed_slot_verdict_through_accept_never_reaches_a_ceiling(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    monkeypatch.setattr(rig.w.gate, 'accept', lambda base, cand, red: (False, 'env:pytest slot: no free RAM'))
    statuses = []
    for _ in range(12):
        statuses.append((rig.once()['status'], rig.state()['tasks']['T1']['defer_reason']))
        next_pass(rig)
    assert statuses == [('READY', 'transient')] * 12


def test_env_counters_live_apart_from_the_quota_groups_and_end_with_a_measured_run(tmp_path, monkeypatch):
    import dataclasses
    rig = Rig(tmp_path, monkeypatch)
    state = {'n': 0}
    broken = dataclasses.replace(G.GateResult(-1, 0, 0, 0, 0, 0, False, 'No module named foo'),
                                 env_reason='No module named foo')

    def run(root, tests, timeout_s):
        state['n'] += 1
        return rig._default_run_tests(root, tests, timeout_s) if state['n'] != 2 else broken   # only the 2nd run is broken
    rig.run_tests_fn = run
    assert rig.once()['reason'] == 'transient'                  # pass 1: n=1 red_before, n=2 broken candidate
    env = rig.state()['factory_env']
    assert env['other'] == {'T1': 1} and not {'env_other', 'env_shortages', 'idle_suspects'} & set(rig.state().get('channel_quotas', {}))
    next_pass(rig)
    assert rig.once()['status'] == 'REVIEW'                     # a measured run: the series is over
    assert rig.state()['factory_env']['other'] == {} and rig.state()['factory_env']['shortages'] == {}


def test_two_tasks_on_one_channel_the_second_is_not_blocked_by_the_first_ones_idle_series(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    first = json.loads(rig.plan.read_text())[0]
    second = dict(first, id='T2a', backlog_id='BL2', title='Fix sum again')
    rig.plan.write_text(json.dumps([first, second]))
    allowed = rig.w.IDLE_SUSPECTS_ALLOWED
    rig.coder_script = [(124, b'', b'')] * (allowed + 2)
    for index in range(allowed + 1):
        rig.once()
        if index < allowed:
            next_pass(rig)
    st = rig.state()
    assert st['tasks']['T1']['status'] == 'BLOCKED'
    assert st['channel_quotas']['p']['cool_until'] > time.time() + 800           # the channel is cooled at the ceiling
    # 21.11: with a longer allowance the router moves to the next channel of the group meanwhile; the channel series
    # stay short of the task's allowance and the ceiling popped the last channel's counter
    assert all(v <= 3 for k, v in st.get('factory_env', {}).get('idle', {}).items() if k.startswith('channel:'))
    assert 'channel:c2' not in st.get('factory_env', {}).get('idle', {})
    next_pass(rig)
    result = rig.once()
    assert result['task_id'] == 'T2a' and result['status'] == 'READY' and result['reason'] == 'rate_minute'


# ---- the light engine inside a real pass (owner: small edits and reviews through fast calls)
def light_rig(rig, answers):
    """The pass of ``rig`` on the light engine; ``answers`` maps 'code'/'review' to the provider's reply."""
    sent = []

    def post(url, key, body, timeout):
        role = 'review' if body['messages'][0]['content'] == rig.w.LIGHT_REVIEW_RULES else 'code'
        sent.append(dict(url=url, key=key, role=role, prompt=body['messages'][1]['content'], model=body['model']))
        status, content = answers[role]
        reply = dict(choices=[dict(message=dict(content=content), finish_reason='stop')],
                     usage=dict(prompt_tokens=900, completion_tokens=40,
                                prompt_tokens_details=dict(cached_tokens=100)))
        return status, json.dumps(reply).encode()

    rig.mp.setattr(rig.w, 'engine_for', lambda role, task: 'light')
    rig.mp.setattr(rig.w, '_light_post', post)
    return sent


FIX_BLOCK = 'calc.py\n<<<<<<< SEARCH\ndef add(a,b): return a-b\n=======\ndef add(a,b): return a+b\n>>>>>>> REPLACE\n'


def test_light_engine_passes_a_one_file_task_with_one_request_per_call(rig):
    sent = light_rig(rig, {'code': (200, FIX_BLOCK), 'review': (200, approval_json())})
    result = rig.once()
    assert result['status'] == 'REVIEW' and [c['role'] for c in result['calls']] == ['code', 'review', 'review']
    assert rig.models == []                                   # the Kilo engine was never started
    assert [s['role'] for s in sent] == ['code', 'review', 'review']
    assert [s['model'] for s in sent] == ['x', 'y', 'z']
    assert sent[0]['url'] == rig.w.LIGHT_ENDPOINTS['google'] and sent[0]['key'] == 'synthetic'
    assert 'def add(a,b): return a-b' in sent[0]['prompt']    # the file travels in the prompt, nothing is read
    code = result['calls'][0]
    assert code['steps'] == 1 and code['tool_events'] == 1 and code['input_tokens'] == 800
    assert code['cache_read_tokens'] == 100 and code['output_tokens'] == 40
    assert code['reserved_tokens'] == C.estimate_tokens(len(sent[0]['prompt']), 0,
                                                        overhead=rig.w.LIGHT_OVERHEAD_TOKENS)


def test_light_engine_gives_the_reason_of_an_unapplied_edit_to_the_next_attempt(rig):
    wrong = FIX_BLOCK.replace('return a-b', 'return b - a', 1)    # SEARCH that is not in the file
    light_rig(rig, {'code': (200, wrong), 'review': (200, approval_json())})
    result = rig.once()
    assert result['status'] == 'READY' and result['reason'] == 'gate:no_changes'
    assert 'SEARCH not found exactly once' in json.dumps(rig.state(), ensure_ascii=False)


def test_an_import_error_the_candidate_made_is_its_defect_not_the_environment(rig):
    """Live 19.11 18:06-18:08: tests written by the model imported modules that do not exist; the gate called it
    'environment' (no strike, no feedback) and the task went round."""
    runs = []

    def run_tests(root, tests, timeout_s):
        runs.append(root)
        if len(runs) == 1:                                   # the base: an ordinary red, it collects
            return gr(False, diag='assert add(2,3)==5 -> got -1')
        return gr(False, env_reason='ModuleNotFoundError: nope', diag="error tests.test_calc: collection failure")
    rig.run_tests_fn = run_tests
    rig.coder_script = ['import nope\ndef add(a,b): return a+b\n']     # the candidate's own new import
    result = rig.once()
    assert result['status'] == 'READY' and result['reason'].startswith('gate:')   # judged like any red candidate
    row = rig.state()['tasks']['T1']
    assert row['attempts'] == 1 and 'not available: nope' in json.dumps(rig.state())


def test_a_package_the_project_already_imports_stays_the_environment(rig):
    """Critic 19.11: a package missing from the factory's venv struck every candidate that touched its users."""
    (rig.root / 'plot.py').write_text('import numpy\n')
    runs = []

    def run_tests(root, tests, timeout_s):
        runs.append(root)
        if len(runs) == 1:
            return gr(False, diag='assert add(2,3)==5 -> got -1')
        return gr(False, env_reason='ModuleNotFoundError: numpy', diag="error tests.test_calc: collection failure")
    rig.run_tests_fn = run_tests
    rig.coder_script = ['import numpy\ndef add(a,b): return a+b\n']
    result = rig.once()
    assert result['status'] == 'READY' and not result['reason'].startswith('gate:')
    assert rig.state()['tasks']['T1']['attempts'] == 0 and not rig.state().get('strikes')


def test_a_light_reviewer_that_never_answers_in_time_reaches_the_reviewer_ceiling(rig):
    """Critic 19.11: on the light engine a timeout was 'transient' for ever, the candidate hung in pending_review."""
    light_rig(rig, {'code': (200, FIX_BLOCK), 'review': (200, approval_json())})
    ok_post = rig.w._light_post

    def post(url, key, body, timeout):
        if body['messages'][0]['content'] == rig.w.LIGHT_REVIEW_RULES:
            return None, b'TimeoutError'
        return ok_post(url, key, body, timeout)
    rig.mp.setattr(rig.w, '_light_post', post)
    allowed = rig.w.IDLE_SUSPECTS_ALLOWED
    seen = []
    for _ in range(allowed + 1):
        seen.append(rig.once()['status'])
        next_pass(rig)
    row = rig.state()['tasks']['T1']
    assert seen == ['READY'] * allowed + ['BLOCKED'] and row['blocked_reason'] == 'reviewer_failed'


def test_no_connection_is_infrastructure_and_spends_no_provider_request(rig):
    """Critic 19.11: the light engine's network failure went round as 'transient' and never met the brake."""
    light_rig(rig, {'code': (200, FIX_BLOCK), 'review': (200, approval_json())})
    rig.mp.setattr(rig.w, '_light_post', lambda url, key, body, timeout: (None, b'URLError'))
    result = rig.once()
    assert result['status'] == 'READY' and result['reason'] == 'network' and result['infra'] is True
    quotas = rig.state()['channel_quotas']
    assert not any(g.get('request_times') for g in quotas.values() if isinstance(g, dict))   # both bookings refunded
    assert not rig.state().get('strikes')


def test_a_missing_module_on_the_base_too_stays_the_environment(rig):
    rig.run_tests_fn = lambda root, tests, timeout_s: gr(False, env_reason='ModuleNotFoundError',
                                                          diag="E ModuleNotFoundError: No module named 'numpy'")
    result = rig.once()
    assert result['status'] == 'READY' and result['reason'] != 'gate: import error'
    assert rig.state()['tasks']['T1']['attempts'] == 0 and not rig.models     # never reached the coder, no strike


def test_an_overloaded_coder_model_is_retried_on_another_channel_in_the_same_pass(rig):
    """Live 19.11 18:18-18:20: on a 503 of one model the retry went to the same model and the pass was deferred."""
    sent = light_rig(rig, {'code': (200, FIX_BLOCK), 'review': (200, approval_json())})
    ok_post = rig.w._light_post

    def post(url, key, body, timeout):
        if not sent:                                         # the first request: the model is overloaded
            sent.append(dict(role='code', model=body['model'], url=url, key=key, prompt=''))
            return 503, json.dumps([dict(error=dict(code=503, message='high demand'))]).encode()
        return ok_post(url, key, body, timeout)
    rig.mp.setattr(rig.w, '_light_post', post)
    cfg = rig.tmp / 'four.json'                      # the live set has 7 channels: two reviewer models stay free
    small = dict(id='c3', group='p3', model='google/z', key_env='KEY', tpm=100000, rpd=100, tier='small', verified=True)
    cfg.write_text(json.dumps(dict(channels=TWO_CHANNELS + [small, dict(small, id='c4', group='p4', model='google/w')])))
    result = rig.once(channel_config=cfg)
    coder = [c for c in result['calls'] if c['role'] == 'code']
    assert [c['model'] for c in coder] == ['google/x', 'google/y'] and coder[0]['error_class'] == 'transient'
    assert result['status'] == 'REVIEW'              # not deferred: the edit was made on the second channel, same pass


def test_light_engine_rate_limit_is_a_channel_fault_not_a_strike(rig):
    body = json.dumps([dict(error=dict(code=429, message='quota', status='RESOURCE_EXHAUSTED', details=[
        dict(violations=[dict(quotaId='GenerateRequestsPerMinutePerProjectPerModel-FreeTier')]),
        dict(retryDelay='17s')]))])
    light_rig(rig, {'code': (429, body), 'review': (200, approval_json())})
    result = rig.once()
    assert result['status'] == 'READY' and result['reason'] == 'rate_minute'
    row = rig.state()['tasks']['T1']
    assert row['attempts'] == 0 and not rig.state().get('strikes')   # the provider's limit is never the task's fault


def test_three_empty_truncated_answers_in_a_row_cool_the_channel_in_the_call_row(rig):
    """Live 20.11: k2-g-gemma-4-26b answered 'ok' after ~174 s six times with the whole output limit spent and no word
    of answer; such a call counted as a success and the channel kept getting work. The third failed call in a row
    cools it (reason and term in the call row, which the loop writes to telemetry); the next critic is another model."""
    empty = ev(dict(type='step_finish', part=dict(reason='length', tokens=dict(input=4000, output=0))))
    rig.review_script = [empty, empty, empty]
    rows = []
    for _ in range(3):
        result = rig.once()
        rows += [c for c in result['calls'] if c['role'] == 'review']
        rig.edit_state(lambda s: s['tasks']['T1'].update(not_before=0))     # keep the quota state: the series lives there
    assert [r['model'] for r in rows] == ['google/y'] * 3
    assert [r.get('cool_reason') for r in rows] == [None, None, 'fail_streak']
    assert rows[-1]['cool_s'] == C.STREAK_COOL_S
    quota = rig.state()['channel_quotas']
    others = [c for c in THREE_CHANNELS if c['model'] != 'google/x']
    assert C.choose(others, quota, 10, {'KEY': 'synthetic'})['id'] == 'c3'
