"""g24 / N178, N176: a backup of the profile before a rollout, and the way back with one command. No secrets are copied, nothing is half-restored."""
import pytest

from tools import profile_backup as pb


@pytest.fixture
def profile(tmp_path):
    p = tmp_path / 'profile'
    (p / 'materials').mkdir(parents=True)
    (p / 'materials' / 'qa.json').write_text('[{"question":"а","answer":"б"}]', encoding='utf-8')
    (p / 'materials' / 'echo_settings.json').write_text('{"preset":"x"}', encoding='utf-8')
    (p / 'logs').mkdir()
    (p / 'logs' / 'big.jsonl').write_text('x' * 100, encoding='utf-8')
    (p / 'auth.json').write_text('{"token":"secret"}', encoding='utf-8')
    return p


def test_backup_copies_materials_and_skips_logs_and_secrets(profile, tmp_path):
    dest = pb.backup(profile, tmp_path / 'bk', stamp='t1')
    names = {str(f.relative_to(dest)) for f in dest.rglob('*') if f.is_file()}
    assert 'materials/qa.json' in names and 'materials/echo_settings.json' in names and 'manifest.json' in names
    assert not any('logs' in n or 'auth' in n for n in names)


def test_restore_brings_the_old_files_back_and_keeps_the_changed_ones_aside(profile, tmp_path):
    dest = pb.backup(profile, tmp_path / 'bk', stamp='t1')
    (profile / 'materials' / 'qa.json').write_text('[]', encoding='utf-8')
    pb.restore(dest, profile)
    assert (profile / 'materials' / 'qa.json').read_text(encoding='utf-8') == '[{"question":"а","answer":"б"}]'
    assert (profile / 'auth.json').exists()
    assert list(profile.glob('materials/qa.json.before-restore*'))


def test_a_damaged_backup_restores_nothing(profile, tmp_path):
    dest = pb.backup(profile, tmp_path / 'bk', stamp='t1')
    (dest / 'materials' / 'qa.json').write_text('tampered', encoding='utf-8')
    (profile / 'materials' / 'echo_settings.json').write_text('{"new":1}', encoding='utf-8')
    with pytest.raises(ValueError):
        pb.restore(dest, profile)
    assert (profile / 'materials' / 'echo_settings.json').read_text(encoding='utf-8') == '{"new":1}'


def test_latest_picks_the_newest_stamp(profile, tmp_path):
    pb.backup(profile, tmp_path / 'bk', stamp='20261106-0100')
    b = pb.backup(profile, tmp_path / 'bk', stamp='20261106-0200')
    assert pb.latest(tmp_path / 'bk') == b
    assert pb.latest(tmp_path / 'none') is None


def test_the_same_stamp_twice_does_not_overwrite(profile, tmp_path):
    a = pb.backup(profile, tmp_path / 'bk', stamp='t')
    b = pb.backup(profile, tmp_path / 'bk', stamp='t')
    assert a != b and a.exists() and b.exists()
