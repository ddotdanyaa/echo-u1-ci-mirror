"""U120: one command puts a build out, one brings the previous one back (build + profile materials byte for byte); the release carries a sha256 manifest; the time is measured."""
import json
import shutil

import pytest

from tools import deploy as dp


@pytest.fixture
def src(tmp_path):
    s = tmp_path / 'src'
    (s / 'echo_sync' / 'sub').mkdir(parents=True)
    (s / 'echo_sync' / '__init__.py').write_text('x = 1\n', encoding='utf-8')
    (s / 'echo_sync' / 'sub' / 'm.py').write_text('y = 2\n', encoding='utf-8')
    (s / 'echo_sync' / '__pycache__').mkdir()
    (s / 'echo_sync' / '__pycache__' / 'm.pyc').write_bytes(b'\0')
    (s / 'echo_sync' / 'auth.json').write_text('{"token":"SECRET"}', encoding='utf-8')
    return s


@pytest.fixture
def target(tmp_path):
    t = tmp_path / 'srv'
    (t / 'profile' / 'materials').mkdir(parents=True)
    (t / 'profile' / 'materials' / 'qa.json').write_text('[{"question":"а","answer":"б"}]', encoding='utf-8')
    (t / 'profile' / 'materials' / 'echo_settings.json').write_text('{"words_per_portion": 4}', encoding='utf-8')
    (t / 'profile' / 'auth.json').write_text('{"token":"SECRET"}', encoding='utf-8')
    return t


def _log(target):
    return [json.loads(x) for x in (target / 'deploy.log').read_text(encoding='utf-8').splitlines()]


def _snap(profile):
    return {p.relative_to(profile).as_posix(): p.read_bytes() for p in sorted(profile.rglob('*')) if p.is_file()}


def test_deploy_points_current_at_the_new_release_and_logs_sha_and_profile(src, target):
    out = dp.deploy(src, target, sha='abc1234')
    cur = json.loads((target / 'current.json').read_text(encoding='utf-8'))
    assert cur['sha'] == 'abc1234' and cur['profile'] == 'shadow' and cur['release'] == out['release']
    rel = target / 'releases' / out['release']
    assert (rel / 'echo_sync' / 'sub' / 'm.py').read_text(encoding='utf-8') == 'y = 2\n'
    assert (rel / 'echo_sync' / 'BUILD').read_text(encoding='utf-8').strip() == 'abc1234'
    (line,) = _log(target)
    assert line['action'] == 'deploy' and line['sha'] == 'abc1234' and line['profile'] == 'shadow' and line['previous'] is None
    assert line['duration_s'] >= 0 and line['time']
    assert not list((target / 'releases').glob('.tmp*'))


def test_secrets_and_caches_are_never_copied(src, target):
    out = dp.deploy(src, target, sha='abc1234')
    rel = target / 'releases' / out['release']
    names = {p.relative_to(rel).as_posix() for p in rel.rglob('*') if p.is_file()}
    assert not any('auth' in n or 'pyc' in n for n in names)
    assert not any('auth' in str(p) for p in (target / 'backups').rglob('*'))
    assert 'SECRET' not in json.dumps(json.loads((rel / 'manifest.json').read_text(encoding='utf-8')))
    assert (target / 'profile' / 'auth.json').read_text(encoding='utf-8') == '{"token":"SECRET"}'


def test_the_release_manifest_is_verified_and_tampering_is_detected(src, target):
    out = dp.deploy(src, target, sha='abc1234')
    assert dp.verify(target) == []
    f = target / 'releases' / out['release'] / 'echo_sync' / 'sub' / 'm.py'
    f.write_text('y = 3\n', encoding='utf-8')
    assert dp.verify(target) == ['echo_sync/sub/m.py']
    f.write_text('y = 2\n', encoding='utf-8')
    (f.parent / 'extra.py').write_text('z', encoding='utf-8')
    assert dp.verify(target) == ['echo_sync/sub/extra.py']
    (f.parent / 'extra.py').unlink()
    f.unlink()
    assert dp.verify(target) == ['echo_sync/sub/m.py']
    assert dp.main(['verify', str(target)]) == 1


def test_the_same_source_gives_the_same_manifest(src, target):
    a = dp.deploy(src, target, sha='abc1234')
    b = dp.deploy(src, target, sha='abc1234')
    ma = (target / 'releases' / a['release'] / 'manifest.json').read_text(encoding='utf-8')
    mb = (target / 'releases' / b['release'] / 'manifest.json').read_text(encoding='utf-8')
    assert a['release'] != b['release'] and ma == mb


def test_rollback_brings_back_the_previous_release_and_the_profile_byte_for_byte(src, target):
    dp.deploy(src, target, sha='aaa1111')
    before = _snap(target / 'profile')
    (src / 'echo_sync' / 'sub' / 'm.py').write_text('y = 99\n', encoding='utf-8')
    (target / 'profile' / 'materials' / 'qa.json').write_text('[]', encoding='utf-8')   # the owner edits between the deploys
    before = _snap(target / 'profile')
    ev = target.parent / 'ev.txt'
    ev.write_text('ok', encoding='utf-8')
    second = dp.deploy(src, target, profile='live', sha='bbb2222', confirmed=True, evidence=ev)
    assert (target / 'profile' / 'materials' / 'echo_settings.json').read_text(encoding='utf-8') != '{"words_per_portion": 4}'
    out = dp.rollback(target)
    assert out['sha'] == 'aaa1111' and out['profile'] == 'shadow' and out['from'] == second['release']
    assert json.loads((target / 'current.json').read_text(encoding='utf-8'))['sha'] == 'aaa1111'
    after = {k: v for k, v in _snap(target / 'profile').items() if not k.endswith('.before-restore')}
    assert after == before
    last = _log(target)[-1]
    assert last['action'] == 'rollback' and last['sha'] == 'aaa1111' and isinstance(last['duration_s'], float) and last['duration_s'] >= 0
    assert out['duration_s'] == last['duration_s'] and dp.verify(target) == []


def test_rollback_removes_a_settings_file_the_deploy_created(src, target):
    (target / 'profile' / 'materials' / 'echo_settings.json').unlink()
    ev = target.parent / 'ev.txt'
    ev.write_text('ok', encoding='utf-8')
    dp.deploy(src, target, sha='aaa1111')
    dp.deploy(src, target, profile='live', sha='bbb2222', confirmed=True, evidence=ev)
    assert (target / 'profile' / 'materials' / 'echo_settings.json').exists()
    dp.rollback(target)
    assert not (target / 'profile' / 'materials' / 'echo_settings.json').exists()


def test_deploy_three_times_then_rollback_twice_and_the_third_refuses(src, target):
    shas = ['aaa1111', 'bbb2222', 'ccc3333']
    snaps = []
    for s in shas:
        snaps.append(_snap(target / 'profile'))
        (target / 'profile' / 'materials' / 'note.json').write_text(json.dumps({'after': s}), encoding='utf-8')
        dp.deploy(src, target, sha=s)
    assert dp.rollback(target)['sha'] == 'bbb2222'
    assert dp.rollback(target)['sha'] == 'aaa1111'
    with pytest.raises(ValueError, match='no previous'):
        dp.rollback(target)
    assert json.loads((target / 'current.json').read_text(encoding='utf-8'))['sha'] == 'aaa1111'
    assert [x['action'] for x in _log(target)] == ['deploy'] * 3 + ['rollback'] * 2


def test_rollback_refuses_a_tampered_previous_release_and_changes_nothing(src, target):
    a = dp.deploy(src, target, sha='aaa1111')
    dp.deploy(src, target, sha='bbb2222')
    (target / 'releases' / a['release'] / 'echo_sync' / '__init__.py').write_text('evil', encoding='utf-8')
    with pytest.raises(ValueError, match='manifest'):
        dp.rollback(target)
    assert json.loads((target / 'current.json').read_text(encoding='utf-8'))['sha'] == 'bbb2222'


def test_a_damaged_profile_backup_stops_the_rollback_before_anything_moves(src, target):
    dp.deploy(src, target, sha='aaa1111')
    dp.deploy(src, target, sha='bbb2222')
    for f in (target / 'backups').rglob('qa.json'):
        f.write_text('tampered', encoding='utf-8')
    with pytest.raises(ValueError):
        dp.rollback(target)
    assert json.loads((target / 'current.json').read_text(encoding='utf-8'))['sha'] == 'bbb2222'


def test_an_unknown_or_dirty_sha_is_refused_without_the_flag(src, target):
    with pytest.raises(ValueError, match='--sha'):
        dp.deploy(src, target)          # src is not a git checkout
    with pytest.raises(ValueError, match='sha'):
        dp.deploy(src, target, sha='not a sha!')
    assert not (target / 'current.json').exists()


def test_a_dirty_checkout_is_refused_and_a_clean_one_gives_its_commit(tmp_path, target):
    import subprocess
    assert shutil.which('git'), 'deploy reads the commit with git: a host without git cannot run this check, and that is a red, not a skip'
    repo = tmp_path / 'repo'
    (repo / 'echo_sync').mkdir(parents=True)
    (repo / 'echo_sync' / '__init__.py').write_text('x = 1\n', encoding='utf-8')
    run = lambda *a: subprocess.run(['git', '-C', str(repo), '-c', 'user.name=t', '-c', 'user.email=t@t', *a], check=True, capture_output=True, text=True).stdout.strip()
    run('init', '-q')
    run('add', '.')
    run('commit', '-qm', 'one')
    out = dp.deploy(repo, target)
    assert out['sha'] == run('rev-parse', '--short=12', 'HEAD')
    (repo / 'echo_sync' / '__init__.py').write_text('x = 2\n', encoding='utf-8')
    with pytest.raises(ValueError, match='dirty'):
        dp.deploy(repo, target)
    assert dp.deploy(repo, target, sha='deadbee')['sha'] == 'deadbee'


def test_the_command_line_deploy_and_rollback(src, target, capsys):
    assert dp.main(['deploy', str(src), str(target), '--sha', 'aaa1111']) == 0
    assert dp.main(['deploy', str(src), str(target), '--sha', 'bbb2222']) == 0
    assert dp.main(['rollback', str(target)]) == 0
    assert 'aaa1111' in capsys.readouterr().out
    assert dp.main(['rollback', str(target)]) == 2
    assert dp.main(['deploy', str(src), str(target), '--sha', 'ccc3333', '--profile', 'live']) == 2
