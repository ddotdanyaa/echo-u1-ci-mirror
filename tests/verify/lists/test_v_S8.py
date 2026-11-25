"""V7 С8 (BACKLOG 4.9: «выключенные наработки не бросать: оптимизировать и довнедрять»): the measurable form is the table of switches in ``settings.DEFAULTS``. Every function that is off by default must still
have a reader in the code (a switch nobody reads is an abandoned work: wire it or delete it), and the number of switches only goes down (the target is none: ``test_no_behaviour_keys.py``, the closing pass is
the package H). The allowance is the count on b7a39401: 23 switch words, 21 of them off.

Read by AST of ``settings.py`` and a text search of ``echo_sync/`` (no import of the package). A function that is still off in the owner's live profile is no fact of this file: the profile is not in the
repository. Not run on the laptop."""
import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / 'echo_sync'
WORDS = frozenset({'on', 'off', 'shadow', 'auto', 'true', 'false', 'yes', 'no', 'enabled', 'disabled', 'earned', 'memory'})
OFF = frozenset({'off', 'false', 'no', 'disabled'})
SWITCHES_ALLOWED, OFF_ALLOWED = 23, 21       # b7a39401: only ever smaller


def switches():
    tree = ast.parse((PACKAGE / 'settings.py').read_text(encoding='utf-8'))
    table = next(node.value for node in tree.body if isinstance(node, ast.Assign) and any(getattr(t, 'id', '') == 'DEFAULTS' for t in node.targets))
    out = {}
    for key, value in zip(table.keys, table.values):
        if isinstance(value, ast.Constant) and (isinstance(value.value, bool) or (isinstance(value.value, str) and value.value.lower() in WORDS)):
            out[key.value] = value.value
    return out


def readers(key):
    pattern = re.compile(r'''['"]%s['"]''' % re.escape(key))
    return sorted(p.name for p in PACKAGE.glob('*.py') if p.name != 'settings.py' and pattern.search(p.read_text(encoding='utf-8')))


def test_every_switch_of_the_table_is_read_by_some_code_outside_the_table():
    unread = [key for key in switches() if not readers(key)]
    assert not unread, f'a switch nobody reads (an abandoned function: wire it to its owner or delete the key): {unread}'


def test_the_count_of_switches_and_of_those_off_only_goes_down():
    table = switches()
    off = [key for key, value in table.items() if str(value).lower() in OFF]
    assert len(table) <= SWITCHES_ALLOWED and len(off) <= OFF_ALLOWED, (len(table), len(off), sorted(off))


def test_the_detector_sees_a_switch_and_not_a_quantity():
    table = switches()
    assert 'fast_text' in table and 'words_per_portion' not in table and 'preset' not in table
