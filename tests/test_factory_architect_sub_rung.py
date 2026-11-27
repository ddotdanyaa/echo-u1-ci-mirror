"""The agent step of the architect on the subscription rung when the key cannot pay."""
import json
import subprocess

import pytest

from tools import factory_architect as A
from tools import factory_paid_critic as PK

GOOD = {'decision': 'hold', 'why': 'x'}


def _ok(calls):
    def run(argv, **kw):
        calls.append((argv, kw))
        body = dict(type='result', is_error=False, subtype='success', result='{}')
        return subprocess.CompletedProcess(argv, 0, json.dumps(body).encode(), b'')
    return run


@pytest.fixture
def rung(tmp_path, monkeypatch):
    monkeypatch.setenv('FACTORY_PAID_DIR', str(tmp_path / 'state'))
    (tmp_path / 'state').mkdir()
    monkeypatch.setenv('FACTORY_BUILDERS_SPEND', str(tmp_path / 'absent.json'))
    monkeypatch.setenv('FACTORY_BUILDERS_WAITING', str(tmp_path / 'absent_waiting'))
    monkeypatch.setenv('FACTORY_SUB_USAGE', str(tmp_path / 'usage.json'))
    monkeypatch.setenv('FACTORY_SUB_SETTINGS', str(tmp_path / 'settings_sub.json'))
    monkeypatch.setattr(A, '_agent_count', 0)
    from tools import factory_gate as G
    monkeypatch.setattr(G, '_free_ram', lambda: 10 ** 12)
    return tmp_path


def weekly(path, pct):
    path.joinpath('usage.json').write_text(json.dumps({'weekly': pct, 'at': 1}), encoding='utf-8')


def test_dead_key_and_low_weekly_runs_on_the_subscription_without_booking(rung, monkeypatch):
    weekly(rung, 41)
    monkeypatch.setattr(PK, 'credit_dead', lambda now=None: True)
    monkeypatch.setattr(PK, 'reserve', lambda *a, **k: pytest.fail('a subscription run books no money'))
    calls = []
    assert A.ask_agent('s', 'u', cwd=rung, run=_ok(calls), argv_fn=lambda: ['claude']) == '{}'
    argv, kw = calls[0]
    assert '--bare' not in argv and '--max-budget-usd' not in argv
    assert argv[argv.index('--model') + 1] == 'sonnet'
    assert argv[argv.index('--allowedTools') + 1] == 'Read,Grep,Glob'
    assert argv[argv.index('--settings') + 1] == str(rung / 'settings_sub.json')
    assert not any('KEY' in k.upper() for k in kw['env'])
    assert A.last_agent_source() == 'sub'


def test_weekly_at_the_stop_closes_the_step(rung, monkeypatch):
    weekly(rung, 99)
    monkeypatch.setattr(PK, 'credit_dead', lambda now=None: True)
    with pytest.raises(A.ContractFault, match='agent budget'):
        A.ask_agent('s', 'u', cwd=rung, run=lambda *a, **k: pytest.fail('no run'), argv_fn=lambda: ['claude'])


def test_missing_usage_file_does_not_forbid(rung):
    assert A.sub_available() is True


def test_refused_login_pauses_the_step_for_an_hour(rung, monkeypatch):
    weekly(rung, 10)
    monkeypatch.setattr(PK, 'credit_dead', lambda now=None: True)

    def refused(argv, **kw):
        body = dict(type='result', is_error=True, subtype='error', result='Not logged in - please run /login')
        return subprocess.CompletedProcess(argv, 1, json.dumps(body).encode(), b'')
    with pytest.raises(A.ContractFault, match='agent sub login'):
        A.ask_agent('s', 'u', cwd=rung, run=refused, argv_fn=lambda: ['claude'])
    assert A.sub_available() is False
    assert A.sub_available(now=__import__('time').time() + 3601) is True


def test_ladder_keeps_the_agent_step_while_the_subscription_is_open(rung, monkeypatch):
    monkeypatch.setattr(PK, 'credit_dead', lambda now=None: True)
    weekly(rung, 41)
    assert 'agent' not in A.no_money()
    weekly(rung, 100)
    assert {'paid', 'agent'} <= A.no_money()


def test_key_with_money_keeps_the_key_path(rung, monkeypatch):
    weekly(rung, 41)
    monkeypatch.setattr(PK, 'credit_dead', lambda now=None: False)
    monkeypatch.setattr(PK, 'agent_credit_dead', lambda now=None: False)
    monkeypatch.setattr(PK, 'reserve', lambda *a, **k: True)
    monkeypatch.setattr(PK, 'settle', lambda *a, **k: None)
    monkeypatch.setattr(PK, 'left', lambda day: 5.0)
    monkeypatch.setattr(A, '_agent_settings', lambda cwd: rung / 'k.json')
    calls = []
    A.ask_agent('s', 'u', cwd=rung, run=_ok(calls), argv_fn=lambda: ['claude'])
    argv = calls[0][0]
    assert '--bare' in argv and '--max-budget-usd' in argv
    assert A.last_agent_source() == 'key'


def test_refused_reservation_falls_to_the_subscription(rung, monkeypatch):
    weekly(rung, 41)
    monkeypatch.setattr(PK, 'credit_dead', lambda now=None: False)
    monkeypatch.setattr(PK, 'agent_credit_dead', lambda now=None: False)
    monkeypatch.setattr(PK, 'reserve', lambda *a, **k: False)
    monkeypatch.setattr(PK, 'left', lambda day: 0.0)
    calls = []
    A.ask_agent('s', 'u', cwd=rung, run=_ok(calls), argv_fn=lambda: ['claude'])
    assert '--bare' not in calls[0][0] and A.last_agent_source() == 'sub'
