"""U56: before a push, look in the files that would go out for keys and for call texts/recordings. Exit 1 with a list, 0 when clean.

  python tools/push_guard.py                 files changed in <base>..HEAD plus the staged ones (base: the upstream, else every tracked file)
  python tools/push_guard.py --base origin/main
  python tools/push_guard.py --all           every tracked file

A finding is ``path:line  kind  detail``; a secret never shows: only the public type marker of a key (``ghp_``) and ``***``. ``tools/data/push_guard_allow.txt``:
one path glob per line (``#`` starts a comment, say why), a listed path is not reported at all.
"""
import argparse
import fnmatch
import re
import subprocess
import sys
from pathlib import Path

SECRET_PATTERNS = (
    ('openai-key', re.compile(r'\bsk-(?=[A-Za-z0-9_-]*\d)[A-Za-z0-9_-]{20,}')),
    ('github-token', re.compile(r'\bgh[pousr]_[A-Za-z0-9]{30,}')),
    ('github-pat', re.compile(r'\bgithub_pat_[A-Za-z0-9_]{20,}')),
    ('aws-key', re.compile(r'\b(?:AKIA|ASIA)[0-9A-Z]{16}\b')),
    ('slack-token', re.compile(r'\bxox[bp]-[A-Za-z0-9-]{10,}')),
    ('private-key', re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----')),
    ('jwt', re.compile(r'\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}')),
    ('bearer', re.compile(r'(?i)\bauthorization\s*[:=]\s*["\']?bearer\s+([A-Za-z0-9._~+/=-]{20,})')),
    ('assigned-secret', re.compile(r'(?i)\b(?:password|passwd|secret|token|cookie|api[_-]?key)\b["\']?\s*[:=]\s*["\']((?=[^"\']*\d)(?=[^"\']*[A-Za-z])[^"\'\s{}()%$<>]{16,})["\']')),
    # S3: a short quoted password (6-15 characters, a letter and a digit) and a name with a prefix or suffix (DB_PASSWORD, dashboard_token)
    ('short-secret', re.compile(r'(?i)(?:password|passwd|pwd|secret|token|cookie|api[_-]?key)\w*["\']?\s*[:=]\s*["\']((?=[^"\']*\d)(?=[^"\']*[A-Za-z])[^"\'\s{}()%$<>]{6,15})["\']')),
)
# S3: a value with no quotes after = or : (.env, ini, yaml, shell). Only in files of that kind: in code ``token = get_token`` is a name, not a value.
UNQUOTED = ('unquoted-secret', re.compile(r'(?im)^\s*(?:export\s+|set\s+)?[\w.-]*(?:password|passwd|pwd|secret|token|cookie|api[_-]?key)\w*\s*[:=]\s*(?=[^\s"\'#]*\d)(?=[^\s"\'#]*[A-Za-z])([^\s"\'#{}()<>%$,;]{6,})\s*(?:[#;].*)?$'))
CONFIG_EXT = ('.env', '.ini', '.cfg', '.conf', '.yaml', '.yml', '.toml', '.properties', '.sh', '.ps1', '.bat', '.cmd', '.txt')
AUDIO = ('.wav', '.pcm', '.m4a')
NAME_WORDS = ('transcript', 'звонок', 'доклад')
MAX_BYTES = 2_000_000       # S3: a file past this is read by lines (``scan_file``), not skipped
MAX_SCAN_BYTES = 256_000_000  # S3: past this a file is reported as not scanned (a finding), never passed in silence
MAX_LINE = 1 << 20
MAX_ALLOW = 30              # S3: the allowlist is a short list of verified false positives
DEFAULT_ALLOW = 'tools/data/push_guard_allow.txt'


def git(root, *args):
    done = subprocess.run(['git', *args], cwd=root, capture_output=True)
    if done.returncode:
        raise RuntimeError(f'git {" ".join(args)}: {done.stderr.decode(errors="replace").strip()}')
    return done.stdout.decode('utf-8', errors='replace')


def names(text):
    return [line for line in text.splitlines() if line]


def files_to_check(root, everything, base):
    if everything:
        return sorted(set(names(git(root, '-c', 'core.quotepath=off', 'ls-files'))))
    if base is None:
        try:
            base = git(root, 'rev-parse', '--abbrev-ref', '@{upstream}').strip()
        except RuntimeError:
            return sorted(set(names(git(root, '-c', 'core.quotepath=off', 'ls-files'))))
    out = set(names(git(root, '-c', 'core.quotepath=off', 'diff', '--name-only', '--diff-filter=ACMR', f'{base}..HEAD')))
    out |= set(names(git(root, '-c', 'core.quotepath=off', 'diff', '--cached', '--name-only', '--diff-filter=ACMR')))
    return sorted(out)


def load_allow(path):
    try:
        lines = Path(path).read_text(encoding='utf-8').splitlines()
    except OSError:
        return []
    return [line.split('#', 1)[0].strip() for line in lines if line.split('#', 1)[0].strip()]


def allow_problem(patterns):
    """S3: why the allowlist is not acceptable (too long, or an entry that frees everything), or None."""
    if len(patterns) > MAX_ALLOW:
        return f'allowlist has {len(patterns)} entries (at most {MAX_ALLOW}): a list that long frees what it should hold'
    wide = next((p for p in patterns if not p.strip('*/?[]')), None)
    return f'allowlist entry {wide!r} frees every file' if wide else None


def allowed(path, patterns):
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


KEY_MARKS = ('sk-', 'ghp_', 'gho_', 'ghu_', 'ghs_', 'ghr_', 'github_pat_', 'AKIA', 'ASIA', 'xoxb-', 'xoxp-', 'eyJ')


def mask(value):
    # U187: only the public type marker of a key (like "ghp_") may show; a password or other value shows nothing of itself
    mark = next((m for m in KEY_MARKS if value.startswith(m)), '')
    return mark + '***'


def synthetic_dir(root, path):
    """S3: the directory of ``path`` has a manifest that says its recordings are synthesized (a voice made them, no caller): ``manifest*`` with 'synth', 'синтез' or 'generated_by' in it."""
    if root is None:
        return False
    try:
        for entry in (Path(root) / path).parent.iterdir():
            if entry.name.lower().startswith('manifest') and entry.is_file() and entry.stat().st_size < 1_000_000:
                text = entry.read_text(encoding='utf-8', errors='replace').lower()
                if any(mark in text for mark in ('synth', 'синтез', 'generated_by')):
                    return True
    except OSError:
        return False
    return False


def forbidden_path(path, root=None):
    low = path.lower()
    parts = low.split('/')
    # S3: a directory called fixtures or diag_audio frees a recording or a journal only when its manifest says the recordings are synthesized (a call's own recording laid there goes out otherwise)
    keep = (low.startswith('echo_sync/diag_audio/') or 'fixtures' in parts[:-1]) and synthetic_dir(root, path)
    if any(part in ('.test-venv', '.test-deps', 'site-packages') for part in parts[:-1]):
        return 'virtualenv / installed packages (U186)'
    name = parts[-1]
    if (name == '.env' or (name.startswith('.env.') and not name.endswith(('.example', '.sample', '.template', '.dist'))) or name.endswith('.env') or name in ('auth.json', 'id_rsa', 'id_dsa', 'id_ecdsa', 'id_ed25519', '.netrc', '.pgpass')
            or name.endswith(('.pem', '.key', '.p12', '.pfx', '.jks', '.keystore', '.ppk')) or 'secrets_local' in parts[:-1]):
        return 'credentials file'
    if low.startswith('logs/echo_calls/') or '/logs/echo_calls/' in low:
        return 'call log under logs/echo_calls/'
    if low.endswith(AUDIO) and not keep:
        return 'recording outside diag_audio/fixtures'
    if low.endswith('.jsonl') and not keep:
        return 'jsonl journal outside fixtures'
    word = next((w for w in NAME_WORDS if w in parts[-1]), None)
    return f'name contains «{word}»' if word else None


def is_config(path):
    name = Path(path).name.lower()
    return name.startswith('.env') or name.endswith(CONFIG_EXT)


def scan_text(text, config=False):
    """``(line, kind, masked)`` of every line with a key; ``config``: the file is a settings file (``CONFIG_EXT``, .env), so a value with no quotes counts too."""
    patterns = SECRET_PATTERNS + ((UNQUOTED,) if config else ())
    for number, line in enumerate(text.splitlines(), 1):
        for kind, pattern in patterns:
            found = pattern.search(line)
            if found:
                yield number, kind, mask(found.group(1) if found.groups() else found.group(0))


def scan_file(file, config=False):
    """``(line, kind, masked)`` of a file by lines (S3: a file past ``MAX_BYTES`` is read in a stream, not skipped); a binary file (a zero byte at its head) has none."""
    with open(file, 'rb') as stream:
        if b'\0' in stream.read(8192):
            return
        stream.seek(0)
        number = 0
        while True:
            raw = stream.readline(MAX_LINE)
            if not raw:
                return
            number += 1
            for _, kind, shown in scan_text(raw.decode('utf-8', errors='replace'), config):
                yield number, kind, shown


def check(root, paths, patterns):
    findings = []
    for path in paths:
        if allowed(path, patterns):
            continue
        why = forbidden_path(path, root)
        if why:
            findings.append((path, 0, 'forbidden', why))
        file = Path(root) / path
        try:
            if not file.is_file():
                continue
            if file.stat().st_size > MAX_SCAN_BYTES:
                findings.append((path, 0, 'unscanned', f'larger than {MAX_SCAN_BYTES // 1_000_000} MB: not read, so not passed'))
                continue
            for number, kind, shown in scan_file(file, is_config(path)):
                findings.append((path, number, 'secret', f'{kind} {shown}'))
        except OSError:
            continue
    return findings


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--root', default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument('--all', action='store_true', help='every tracked file')
    parser.add_argument('--base', default=None, help='the commit the push starts from (default: the upstream)')
    parser.add_argument('--allow', default=None, help=f'allowlist file (default: <root>/{DEFAULT_ALLOW})')
    args = parser.parse_args(argv)
    root = Path(args.root)
    paths = files_to_check(root, args.all, args.base)
    patterns = load_allow(args.allow or root / DEFAULT_ALLOW)
    problem = allow_problem(patterns)
    if problem:
        print(f'push_guard: {problem}')
        return 1
    findings = check(root, paths, patterns)
    for path, number, kind, detail in findings:
        print(f'{path}:{number}  {kind}  {detail}')
    if findings:
        print(f'push_guard: {len(findings)} finding(s) in {len(paths)} file(s): do not push')
        return 1
    print(f'push_guard: clean ({len(paths)} file(s))')
    return 0


if __name__ == '__main__':
    sys.exit(main())
