"""Port tasks: a backlog row whose behaviour was built on an old branch ("реализовано на ветке ... `<sha>`") and whose
guard test is red on the unified head. The commit the row names, the functions it changed, the files that define them
now, and its diff as the coder's reference (code files only, never a test or a key). Written by a free model in the
self-build queue (20.11, all 8 of the coordinator's tests on its first pass); the coordinator's review added: a missing
git is an empty answer like any git error, the walk never enters tests/ or hidden folders, a commit id is lower-case
hex (as the plan's port_from), imports at the top."""
import ast
import os
import re
import subprocess

from tools.agent_factory import secret_in_source

_SHA = re.compile(r'`([0-9a-f]{7,12})`')
_HUNK_NEW = re.compile(r'\+([0-9]+)(?:,([0-9]+))?')


def port_sha(row):
    lower_row = row.lower()
    idx = lower_row.find('реализовано')
    if idx == -1:
        return None
    m = _SHA.search(row[idx:idx + 120])   # a backticked run of 7-12 hex characters after the word
    return m.group(1) if m else None


def _get_code_files(repo, sha):
    try:
        out = subprocess.run(
            ['git', '-C', str(repo), 'show', '--name-only', '--format=', sha],
            capture_output=True, text=True, encoding='utf-8', errors='replace', check=True
        ).stdout.splitlines()
    except (subprocess.CalledProcessError, OSError):
        return []
    files = []
    for line in out:
        line = line.strip()
        if not line:
            continue
        if line.startswith('tests/') or 'tests/' in line or line.startswith('test_') or '/test_' in line:
            continue
        if not line.endswith('.py'):
            continue
        files.append(line)
    return files


def changed_names(repo, sha):
    code_files = _get_code_files(repo, sha)
    if not code_files:
        return []
    try:
        diff_out = subprocess.run(
            ['git', '-C', str(repo), 'show', '--format=', '-U0', sha, '--'] + code_files,
            capture_output=True, text=True, encoding='utf-8', errors='replace', check=True
        ).stdout
    except (subprocess.CalledProcessError, OSError):
        return []

    changed_lines_by_file = {}
    current_file = None
    for line in diff_out.splitlines():
        if line.startswith('+++ '):
            current_file = line[6:].strip() if line.startswith('+++ b/') else None   # a deleted file: no new side
        elif line.startswith('@@ '):
            m = _HUNK_NEW.search(line)
            if m and current_file:
                start = int(m.group(1))
                count = int(m.group(2)) if m.group(2) is not None else 1
                if count == 0:
                    lines = [start]
                else:
                    lines = list(range(start, start + count))
                changed_lines_by_file.setdefault(current_file, set()).update(lines)

    if not changed_lines_by_file:
        return []

    names_in_order = []
    seen = set()

    for path, lines_set in changed_lines_by_file.items():
        try:
            content = subprocess.run(
                ['git', '-C', str(repo), 'show', f'{sha}:{path}'],
                capture_output=True, text=True, encoding='utf-8', errors='replace', check=True
            ).stdout
        except (subprocess.CalledProcessError, OSError):
            continue

        try:
            tree = ast.parse(content, filename=path)
        except SyntaxError:
            continue

        defs = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        for l in sorted(lines_set):
            # the innermost def enclosing line l
            best_node = None
            best_len = float('inf')
            for d in defs:
                start = getattr(d, 'lineno', None)
                end = getattr(d, 'end_lineno', None)
                if start is not None and end is not None:
                    if start <= l <= end:
                        length = end - start
                        if length < best_len:
                            best_len = length
                            best_node = d
            if best_node:
                name = best_node.name
                if name not in seen:
                    seen.add(name)
                    names_in_order.append(name)

    return names_in_order


_PARSED = {}   # absolute path -> ((mtime_ns, size), names): a file is parsed again only when it changed (live 20.11:
               # 18 rows of one triage portion took 64 s, each call parsing the whole tree again)


def _defined_names(full_path):
    st = os.stat(full_path)
    key = (st.st_mtime_ns, st.st_size)
    hit = _PARSED.get(full_path)
    if hit and hit[0] == key:
        return hit[1]
    with open(full_path, 'r', encoding='utf-8', errors='replace') as fh:
        tree = ast.parse(fh.read(), filename=full_path)
    names = frozenset(n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))
    _PARSED[full_path] = (key, names)
    return names


def locate(root, names, limit=2):
    root_path = os.path.abspath(root)
    file_defs = {}  # path -> set of names defined in file

    for dirpath, dirnames, filenames in os.walk(root_path):
        # never enter tests/ or a hidden folder (.git holds thousands of files)
        dirnames[:] = sorted(d for d in dirnames if d != 'tests' and not d.startswith('.'))
        for f in filenames:
            if not f.endswith('.py') or f.startswith('test_'):
                continue
            full_path = os.path.join(dirpath, f)
            rel_path = os.path.relpath(full_path, root_path).replace(os.sep, '/')
            try:
                file_defs[rel_path] = _defined_names(full_path)
            except (SyntaxError, OSError, ValueError):
                continue

    # Name to list of files defining it
    name_to_files = {}
    for name in names:
        defining = []
        for path, defs in file_defs.items():
            if name in defs:
                defining.append(path)
        name_to_files[name] = defining

    scores = {}
    for name in names:
        defining = name_to_files.get(name, [])
        if len(defining) == 1:
            p = defining[0]
            scores[p] = scores.get(p, 0) + 1

    scored_paths = [(score, path) for path, score in scores.items() if score >= 1]
    # Sort by (-score, path)
    scored_paths.sort(key=lambda x: (-x[0], x[1]))

    result = [path for score, path in scored_paths[:limit]]
    return result


def reference(repo, sha, max_chars=6000):
    code_files = _get_code_files(repo, sha)
    if not code_files:
        return ''
    try:
        diff_out = subprocess.run(
            ['git', '-C', str(repo), 'show', '--format=', '-U2', sha, '--'] + code_files,
            capture_output=True, text=True, encoding='utf-8', errors='replace', check=True
        ).stdout
    except (subprocess.CalledProcessError, OSError):
        return ''

    if secret_in_source(diff_out):
        return ''

    if len(diff_out) <= max_chars:
        return diff_out

    cut_text = diff_out[:max_chars]
    last_newline = cut_text.rfind('\n')
    if last_newline != -1:
        cut_text = cut_text[:last_newline + 1]
    
    suffix = f'\n[the reference is cut here at {max_chars} characters]\n'
    return cut_text + suffix
