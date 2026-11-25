"""V7 H31-10 (BACKLOG 4.10: «чистка мусора с сохранением архитектуры (отдельно от правок)»): the measurable part of «мусор» is a module of ``echo_sync/`` that no code reads: no import in ``echo_sync/``
or ``tools/`` or the root files (a shadow that only its own test imports does not count as a reader: CLAUDE.md «функция, которую никто не читает»). The set is a ratchet: the allowance only ever gets smaller.

Read by AST (no import of the package, so a missing dependency of the stand cannot hide a finding). On b7a39401 the set is {search_race} (read by ``tests/test_w9_search.py`` only; the owner of the file is the
package R). Not run on the laptop."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / 'echo_sync'
ALLOWED = frozenset()       # found on b7a39401; delete a name when the module is read or removed, never add one


def modules():
    return {p.stem for p in PACKAGE.glob('*.py') if p.stem != '__init__'}


def readers(mods):
    """{module: the files of echo_sync/, tools/ and the root that read it: an import, a relative import, a ``__import__``/``import_module`` string of its name}."""
    found = {m: set() for m in mods}
    files = list(PACKAGE.rglob('*.py')) + list((ROOT / 'tools').rglob('*.py')) + list(ROOT.glob('*.py'))
    for path in files:
        try:
            tree = ast.parse(path.read_text(encoding='utf-8'))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.ImportFrom):
                base = node.module or ''
                if base.startswith('echo_sync.'):
                    names.append(base.split('.')[1])
                elif base == 'echo_sync' or (node.level and not base):
                    names += [alias.name for alias in node.names]
                elif node.level:
                    names.append(base.split('.')[0])
            elif isinstance(node, ast.Import):
                names += [alias.name.split('.')[1] for alias in node.names if alias.name.startswith('echo_sync.')]
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                value = node.value.strip()
                for prefix in ('echo_sync.', '.'):
                    if value.startswith(prefix) and value[len(prefix):] in found:
                        names.append(value[len(prefix):])
                if value in found:
                    names.append(value)
            for name in names:
                if name in found and path.stem != name:
                    found[name].add(path.name)
    return found


def unread():
    return sorted(m for m, who in readers(modules()).items() if not who)


def test_the_modules_that_no_code_reads_are_the_allowance_and_not_more():
    left = set(unread())
    assert left <= ALLOWED, f'modules of echo_sync/ that nothing reads (a shadow: wire it to its owner or delete it): {sorted(left - ALLOWED)}'


def test_the_allowance_holds_only_what_is_still_unread():
    stale = sorted(ALLOWED - set(unread()))
    assert not stale, f'read or removed now, drop from ALLOWED: {stale}'


def test_the_detector_sees_a_read_and_a_miss():
    mods = modules()
    assert {'engine', 'settings', 'controlled_media'} <= mods
    who = readers(mods)
    assert who['settings'] and who['engine'], 'a module read everywhere has readers'
