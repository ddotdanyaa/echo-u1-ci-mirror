"""P13 / U94.8 lock: ``settings.DEFAULTS`` holds no behaviour key, and the engine reads no new name from the environment (ARCH_ONE §1 M8, §3 rule 2).

A BEHAVIOUR key picks a path: a bool, an ``on`` / ``off`` / ``shadow`` / ``auto`` word, or any value ``settings.resolve`` takes through ``_choice`` / ``_flag`` (a choice among named paths). What stays in
the table is a NUMBER (a threshold, a window), a TEXT (the subject of the talk), a PATH or a key of access: a quantity the owner of a family reads, never a fork it takes. A function that was
off becomes an always-on rule of its owner and its key goes, with its row of ``SETTINGS.md`` and its reader (CLAUDE.md: «Поведенческих ключей нет»).

The two locks are different in kind: the keys are a CLOSED set that must be empty (this test is the target and is red until the last key is deleted: it names every key left, with its value,
so the merge step knows what to delete), the environment is a ratchet (the names read today are the allowance; a new name is a new switch and fails)."""
import ast
import re
from pathlib import Path

from echo_sync import settings

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / 'echo_sync'
WORDS = frozenset({'on', 'off', 'shadow', 'auto', 'true', 'false', 'yes', 'no', 'enabled', 'disabled', 'earned', 'memory'})      # the words of a switch (a value that names a path, not a quantity)
# The names of the environment the engine reads: the allowance, only ever smaller. LOCALAPPDATA / HERMES_HOME place the profile of the host; ECHO_LAW_DB and ECHO_DIRECT_CACHE are the paths of data files.
ENV_ALLOWED = frozenset({'ECHO_DIRECT_CACHE', 'ECHO_LAW_DB', 'HERMES_HOME', 'LOCALAPPDATA'})
# A name the code builds (``os.environ.get(key)``), by file: the provider keys of ``reserve_text.ROADS`` (access keys, no behaviour) and the user profile of the ear's model folder.
DYNAMIC_ENV_ALLOWED = frozenset({'echo_sync/reserve_text.py', 'echo_sync/ear_sherpa.py'})


import pytest
pytestmark = pytest.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)


def choice_keys(source=None):
    """The keys ``resolve`` reads through ``_choice`` or ``_flag``: ``pick('key', _choice(...))`` / ``out['key'] = _flag(...)``, found by the AST of ``resolve``, not listed here."""
    tree = ast.parse(Path(settings.__file__).read_text(encoding='utf-8') if source is None else source)
    resolve = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'resolve')
    found = set()
    for node in ast.walk(resolve):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'pick' and len(node.args) == 2 and isinstance(node.args[0], ast.Constant):
            inner = node.args[1]
            if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Name) and inner.func.id in ('_choice', '_flag'):
                found.add(node.args[0].value)
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name) and node.value.func.id in ('_choice', '_flag'):
            found |= {target.slice.value for target in node.targets if isinstance(target, ast.Subscript) and isinstance(getattr(target.slice, 'value', None), str)}
    return found


def behaviour_keys(defaults=None, by_resolve=None):
    """``{key: why}`` for every key of ``defaults`` (``settings.DEFAULTS``) that is a switch."""
    by_resolve = choice_keys() if by_resolve is None else by_resolve
    out = {}
    for key, value in (settings.DEFAULTS if defaults is None else defaults).items():
        if isinstance(value, bool):
            out[key] = 'a bool (%r)' % value
        elif isinstance(value, str) and value.strip().lower() in WORDS:
            out[key] = 'the word %r' % value
        elif key in by_resolve:
            out[key] = 'a choice of named paths (%r) by resolve' % (value,)
    return out


def test_defaults_has_no_bool_on_off_shadow_or_choice_value():
    left = behaviour_keys()
    assert left == {}, '%d behaviour keys are left in settings.DEFAULTS, each is an always-on rule of its owner and its key goes with its reader, its SETTINGS.md row and its resolve line:\n%s' % (
        len(left), '\n'.join('  %s: %s' % pair for pair in sorted(left.items())))


def test_the_detector_tells_a_switch_from_a_quantity_a_text_or_a_path():
    toy = {'window_s': 2.5, 'count': 3, 'subject': 'Главный бухгалтер', 'bank_file': 'tools/bank.json', 'fillers': ['ну'], 'preset': None,
           'live': True, 'mode': 'shadow', 'gate': 'off', 'transport': 'http', 'scope': 'answers'}
    assert set(behaviour_keys(toy, {'transport', 'scope'})) == {'live', 'mode', 'gate', 'transport', 'scope'}
    assert behaviour_keys({key: toy[key] for key in ('window_s', 'count', 'subject', 'bank_file', 'fillers', 'preset')}, set()) == {}


def test_the_ast_finds_the_keys_resolve_takes_through_choice_or_flag():
    toy = chr(10).join(["def resolve(raw):", "    pick('mode', _choice(raw.get('mode'), 'a', ('a', 'b')))", "    pick('live', _flag(raw.get('live'), False))",
                        "    pick('window', _number(raw.get('window'), 2, 1, 9, integer=True))", "    out['gate'] = _choice(1, 2, ())", ""])
    assert choice_keys(toy) == {'mode', 'live', 'gate'}
    assert choice_keys() <= set(settings.DEFAULTS), sorted(choice_keys() - set(settings.DEFAULTS))


def env_names():
    """``(names read by a literal, files that read a name they build)`` over echo_sync/**.py: ``os.environ.get('X')``, ``os.environ['X']``, ``os.getenv('X')``, ``'X' in os.environ``, ``environ.pop/setdefault``."""
    names, dynamic = {}, set()
    for path in sorted(PACKAGE.rglob('*.py')):
        rel = path.relative_to(ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding='utf-8'))

        def is_env(node):
            return (isinstance(node, ast.Attribute) and node.attr == 'environ') or (isinstance(node, ast.Name) and node.id == 'environ')
        for node in ast.walk(tree):
            key = None
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.args and (
                    (node.func.attr in ('get', 'pop', 'setdefault') and is_env(node.func.value)) or (node.func.attr == 'getenv' and isinstance(node.func.value, ast.Name) and node.func.value.id == 'os')):
                key = node.args[0]
            elif isinstance(node, ast.Subscript) and is_env(node.value):
                key = node.slice
            elif isinstance(node, ast.Compare) and any(isinstance(op, (ast.In, ast.NotIn)) for op in node.ops) and any(is_env(c) for c in node.comparators):
                key = node.left
            if key is None:
                continue
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                names.setdefault(key.value, set()).add(rel)
            else:
                dynamic.add(rel)
    return names, dynamic


def test_the_engine_reads_no_new_name_from_the_environment():
    names, dynamic = env_names()
    new = {name: sorted(files) for name, files in names.items() if name not in ENV_ALLOWED}
    assert new == {}, 'a new name is read from the environment (a switch the host cannot see in the profile): %s' % new
    assert dynamic <= DYNAMIC_ENV_ALLOWED, 'a name is built and read from the environment in %s' % sorted(dynamic - DYNAMIC_ENV_ALLOWED)


def test_no_name_of_the_environment_gates_a_behaviour():
    """The allowed names place the profile (a folder, a file); none may be compared with ``on`` / ``off`` / ``1`` to take a path: the reader of an allowed name only joins it into a path."""
    gating = []
    for path in sorted(PACKAGE.rglob('*.py')):
        text = path.read_text(encoding='utf-8')
        for name in ENV_ALLOWED:
            for match in re.finditer(r'environ(?:\.get\(|\[)\s*[\'"]%s[\'"][^\n]*?(?:==|!=)\s*[\'"](?:on|off|1|0|true|false)[\'"]' % name, text):
                gating.append((path.name, match.group(0)))
    assert gating == [], gating
