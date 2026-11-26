"""U102: the server profile («тень» / «боевой») is a named overlay of real settings keys; shadow → live only with the coordinator's flag and a replay-evidence file that exists."""
import json

import pytest

from echo_sync import settings
from tools import deploy as dp
from tools import server_profile as sp


def _src(tmp_path):
    src = tmp_path / 'src'
    (src / 'echo_sync').mkdir(parents=True)
    (src / 'echo_sync' / '__init__.py').write_text('x = 1\n', encoding='utf-8')
    return src


def test_every_profile_key_exists_in_the_settings_defaults():
    for name, overlay in sp.PROFILES.items():
        assert set(overlay) <= set(settings.DEFAULTS), name


def test_the_profile_values_survive_settings_resolve_unrepaired():
    for name in sp.PROFILES:
        resolved = settings.resolve(dict(sp.overlay(name)))
        for key, value in sp.overlay(name).items():
            assert resolved[key] == value, (name, key)


def test_shadow_is_the_defaults_and_live_differs_from_them():
    assert sp.overlay('shadow') == {}
    assert sp.overlay('live') and all(settings.DEFAULTS[k] != v for k, v in sp.overlay('live').items())


def test_an_unknown_key_is_refused(monkeypatch):
    monkeypatch.setitem(sp.PROFILES, 'bad', {'no_such_key': 1})
    with pytest.raises(ValueError, match='no_such_key'):
        sp.validate('bad')
    with pytest.raises(ValueError):
        sp.overlay('nonexistent')


def test_live_is_refused_without_the_flag_or_without_the_evidence_file(tmp_path):
    src, target = _src(tmp_path), tmp_path / 'srv'
    ev = tmp_path / 'replay.txt'
    ev.write_text('replay of recorded calls: ok', encoding='utf-8')
    with pytest.raises(ValueError, match='coordinator'):
        dp.deploy(src, target, profile='live', sha='abc1234', evidence=ev)
    with pytest.raises(ValueError, match='evidence'):
        dp.deploy(src, target, profile='live', sha='abc1234', confirmed=True)
    with pytest.raises(ValueError, match='evidence'):
        dp.deploy(src, target, profile='live', sha='abc1234', confirmed=True, evidence=tmp_path / 'missing.txt')
    assert not (target / 'current.json').exists()


def test_live_with_flag_and_evidence_is_applied_logged_and_shown(tmp_path, capsys):
    src, target = _src(tmp_path), tmp_path / 'srv'
    ev = tmp_path / 'replay.txt'
    ev.write_text('replay ok', encoding='utf-8')
    dp.deploy(src, target, profile='shadow', sha='aaa1111')
    dp.deploy(src, target, profile='live', sha='bbb2222', confirmed=True, evidence=ev)
    home = json.loads((target / 'profile' / 'materials' / 'echo_settings.json').read_text(encoding='utf-8'))
    assert home == sp.overlay('live')
    last = json.loads((target / 'deploy.log').read_text(encoding='utf-8').splitlines()[-1])
    assert last['profile'] == 'live' and last['confirmed_by_coordinator'] is True and len(last['evidence_sha256']) == 64
    assert sp.show(target) == {'sha': 'bbb2222', 'profile': 'live', 'release': last['release']}
    sp.main(['show', str(target)])
    assert 'bbb2222' in capsys.readouterr().out


def test_going_back_to_shadow_needs_no_evidence_and_keeps_the_owners_own_keys(tmp_path):
    src, target = _src(tmp_path), tmp_path / 'srv'
    home = target / 'profile' / 'materials'
    home.mkdir(parents=True)
    (home / 'echo_settings.json').write_text(json.dumps({'words_per_portion': 4}), encoding='utf-8')
    ev = tmp_path / 'r.txt'
    ev.write_text('ok', encoding='utf-8')
    dp.deploy(src, target, profile='live', sha='bbb2222', confirmed=True, evidence=ev)
    assert json.loads((home / 'echo_settings.json').read_text(encoding='utf-8'))['words_per_portion'] == 4
    dp.deploy(src, target, profile='shadow', sha='ccc3333')
    assert json.loads((home / 'echo_settings.json').read_text(encoding='utf-8')) == {'words_per_portion': 4}


def test_show_before_any_deploy_says_so(tmp_path):
    assert sp.show(tmp_path / 'none') is None
