"""U56: tools/push_guard.py - before a push, no keys and no call texts in the files that would go out."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / 'tools' / 'push_guard.py'
SECRETS = {
    'openai': 'sk-' + 'A1b2C3d4E5f6G7h8I9j0K1l2M3n4',
    'github': 'ghp_' + 'a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8',
    'github_pat': 'github_pat_' + '11ABCDEFG0abcdefgh_ijklmnop1234',
    'aws': 'AKIA' + 'IOSFODNN7EXAMPLE',
    'slack': 'xoxb-' + '123456789012-abcdefABCDEF',
    'private_key': '-----BEGIN RSA ' + 'PRIVATE KEY-----',
    'jwt': 'eyJ' + 'hbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcDEF123456',
    'bearer': 'Authorization: Bearer ' + 'abcdefghijklmnopqrstuvwx0123456789',
    'assign': 'password = "' + 'hunter2hunter2hunter2xx"',
    'assign_cookie': "cookie: '" + "sessionidsessionid1234567890'",
}


def git(repo, *args):
    return subprocess.run(['git', *args], cwd=repo, check=True, capture_output=True, text=True).stdout


def make_repo(tmp_path, files):
    git(tmp_path, 'init', '-q')
    git(tmp_path, 'config', 'user.email', 't@t')
    git(tmp_path, 'config', 'user.name', 't')
    for name, body in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body if isinstance(body, bytes) else body.encode())
    git(tmp_path, 'add', '-A')
    git(tmp_path, 'commit', '-qm', 'x')
    return tmp_path


def run(repo, *args):
    return subprocess.run([sys.executable, str(GUARD), '--root', str(repo), *args], capture_output=True, text=True)


def test_every_secret_shape_is_caught_and_never_printed(tmp_path):
    repo = make_repo(tmp_path, {f'src/{k}.py': f'x = 1\n{v}\n' for k, v in SECRETS.items()})
    got = run(repo, '--all')
    assert got.returncode == 1
    for key, value in SECRETS.items():
        assert f'src/{key}.py:2' in got.stdout, key
        assert value not in got.stdout + got.stderr, key
    assert 'secret' in got.stdout


def test_the_output_shows_only_a_masked_prefix(tmp_path):
    repo = make_repo(tmp_path, {'a.py': f'k = "{SECRETS["github"]}"\n'})
    out = run(repo, '--all').stdout
    assert 'ghp_' in out and SECRETS['github'][8:] not in out


def test_call_texts_and_recordings_are_forbidden(tmp_path):
    bad = ['logs/echo_calls/c1/turns.txt', 'rec/call.wav', 'x/a.pcm', 'x/a.m4a', 'journal/c.jsonl',
           'notes/transcript_1.txt', 'notes/Звонок_5.md', 'docs/Доклад.md', 'a/DOKLAD_transcript.txt']
    repo = make_repo(tmp_path, {name: 'hello' for name in bad})
    got = run(repo, '--all')
    assert got.returncode == 1
    for name in bad:
        assert name in got.stdout, name
    assert 'forbidden' in got.stdout


def test_diag_audio_and_fixtures_may_keep_wav_only_with_a_manifest_that_says_synthesized(tmp_path):
    manifest = '{"generated_by": "tools/make_diag_audio.py (SAPI voice)"}'
    repo = make_repo(tmp_path, {'echo_sync/diag_audio/a.wav': b'RIFF', 'echo_sync/diag_audio/manifest.json': manifest,
                                'tests/fixtures/b.wav': b'RIFF', 'tests/fixtures/c.jsonl': '{}', 'tests/fixtures/MANIFEST.txt': 'synth: all recordings here are synthesized'})
    assert run(repo, '--all').returncode == 0


def test_a_recording_or_a_journal_in_fixtures_with_no_manifest_goes_nowhere(tmp_path):
    """S3: the name of the directory frees nothing: a call's own recording laid under fixtures/ or diag_audio/ is the same recording."""
    repo = make_repo(tmp_path, {'tests/fixtures/call.wav': b'RIFF', 'tests/fixtures/turns.jsonl': '{}', 'echo_sync/diag_audio/real.m4a': b'x',
                                'other/fixtures/manifest.json': '{"voice": "a caller"}', 'other/fixtures/d.wav': b'RIFF'})
    got = run(repo, '--all')
    assert got.returncode == 1
    for name in ('tests/fixtures/call.wav', 'tests/fixtures/turns.jsonl', 'echo_sync/diag_audio/real.m4a', 'other/fixtures/d.wav'):
        assert name in got.stdout, name


def test_a_short_password_a_prefixed_name_and_a_value_without_quotes_are_caught_and_never_printed(tmp_path):
    repo = make_repo(tmp_path, {'src/a.py': 'DASH_PASSWORD = "hunter42"\n', 'conf/b.yaml': 'dashboard:\n  password: Zk39dj2k\n', 'deploy/.env': 'API_KEY=abc123def456\n',
                                'run.sh': 'export TOKEN=Qw8rT5yU\n', 'src/c.py': 'token = get_token()\npassword = ""\nname = token_name\n'})
    got = run(repo, '--all')
    assert got.returncode == 1
    for name, line in (('src/a.py', 1), ('conf/b.yaml', 2), ('deploy/.env', 1), ('run.sh', 1)):
        assert f'{name}:{line}' in got.stdout, name
    assert 'src/c.py' not in got.stdout
    for value in ('hunter42', 'Zk39dj2k', 'abc123def456', 'Qw8rT5yU'):
        assert value not in got.stdout + got.stderr


def test_more_names_of_credential_files_are_forbidden(tmp_path):
    bad = ['.env.local', 'cfg/providers.env', 'ssl/site.p12', 'ssl/site.pfx', 'home/id_rsa', 'home/id_ed25519']
    repo = make_repo(tmp_path, {**{name: 'x' for name in bad}, '.env.example': 'A=1\n'})
    got = run(repo, '--all')
    assert got.returncode == 1
    for name in bad:
        assert name in got.stdout, name
    assert '.env.example' not in got.stdout


def test_a_file_past_two_megabytes_is_read_by_lines_and_its_key_is_found(tmp_path):
    body = (b'x = 1\n' * 400_000) + f'k = "{SECRETS["github"]}"\n'.encode() + (b'y = 2\n' * 10)
    assert len(body) > 2_000_000
    repo = make_repo(tmp_path, {'dump/big.py': body})
    got = run(repo, '--all')
    assert got.returncode == 1 and 'dump/big.py:400001' in got.stdout and SECRETS['github'] not in got.stdout


def test_an_allowlist_that_frees_everything_or_is_too_long_is_refused(tmp_path):
    repo = make_repo(tmp_path, {'a.py': 'x = 1\n'})
    wide = tmp_path / 'wide.txt'
    wide.write_text('**\n', encoding='utf-8')
    assert run(repo, '--all', '--allow', str(wide)).returncode == 1
    long = tmp_path / 'long.txt'
    long.write_text(''.join(f'src/f{n}.py  # why\n' for n in range(31)), encoding='utf-8')
    got = run(repo, '--all', '--allow', str(long))
    assert got.returncode == 1 and 'allowlist' in got.stdout


def test_allowlist_silences_a_known_false_positive(tmp_path):
    repo = make_repo(tmp_path, {'tools/data/doc.py': f'k = "{SECRETS["aws"]}"\n', 'logs/echo_calls/x.txt': 'a'})
    allow = tmp_path / 'allow.txt'
    allow.write_text('# why: a documented example\ntools/data/doc.py\nlogs/echo_calls/*\n', encoding='utf-8')
    assert run(repo, '--all').returncode == 1
    got = run(repo, '--all', '--allow', str(allow))
    assert got.returncode == 0, got.stdout


def test_a_clean_repo_passes_and_prose_about_tokens_is_not_a_key(tmp_path):
    repo = make_repo(tmp_path, {'a.py': 'token = get_token()\npassword = ""\ncookie = request.cookies\nsk = 1\n# sk-short\n'})
    got = run(repo, '--all')
    assert got.returncode == 0, got.stdout
    assert 'clean' in got.stdout


def test_default_mode_checks_the_files_since_base_and_staged(tmp_path):
    repo = make_repo(tmp_path, {'ok.py': 'x = 1\n'})
    base = git(repo, 'rev-parse', 'HEAD').strip()
    (repo / 'new.py').write_text(f'k = "{SECRETS["openai"]}"\n')
    git(repo, 'add', 'new.py')
    assert run(repo, '--base', base).returncode == 1
    git(repo, 'commit', '-qm', 'y')
    assert run(repo, '--base', base).returncode == 1
    assert run(repo, '--base', 'HEAD').returncode == 0
    (repo / 'staged.wav').write_bytes(b'x')
    git(repo, 'add', 'staged.wav')
    assert 'staged.wav' in run(repo, '--base', 'HEAD').stdout


def test_this_repo_has_no_key_and_no_call_text_in_its_tracked_files():
    got = subprocess.run([sys.executable, str(GUARD), '--root', str(ROOT), '--all'], capture_output=True, text=True)
    assert got.returncode == 0, got.stdout
