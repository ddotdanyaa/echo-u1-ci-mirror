"""P13 / U94 (ARCH_ONE §1, §3 rule 3): the old paths of a family stay deleted. A path that was removed «в той же правке, что вводит замену» must not come back by a revert, a merge of an old lane or a copy of a test helper.

Two lists, both written from the places the work of the families named (the census ``tools/owner_census_sites.ndjson`` places that are ``gone`` against the 13.11 base, the deletions in the reports of P01-P12 and the
«что удалить» column of ARCH_ONE §1), each a NAME and nothing else (a lock counts, it lists no phrase):

  GONE     names already removed from ``echo_sync/``: this test is green and fails the day one of them is written again (a ``def``, a ``class``, an import, a call, an attribute, a key of the settings read as a string).
  TARGET   the behaviour keys ARCH_ONE §1 says are deleted (the owner is always on): the readers of these still stand in the tree, and this test is the list the merge step deletes from; it is red until
           the last of them is gone, and names each reader it still finds.

The scan is the AST of every file of ``echo_sync/`` (docstrings and comments are not code and are skipped), not a text search: a word in a comment about a deleted path is history, a call is a path."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / 'echo_sync'

# Names whose function, class or module is gone: the census places of the families that are ``gone`` (answer, kind, question, route, speech) and what the reports of the packets removed.
GONE = {
    'kind': ('_follows_on_legacy', '_followup_cell', '_judge_order', '_short_followup_suffix', 'kind_of'),
    'question': ('allow_job', 'allow_twin', 'note_done'),
    'speech': ('Game', 'game_mode', 'search_race'),
    'portion': ('_tail_step', '_sensed'),
}
# Names that the census lists as gone but a reader of which still stands in the merged tree (route: P10 kept the old names in fast_text / native_media_socket / reserve_text): the target list for the names, red until each is deleted.
TARGET_NAMES = {
    'route': ('_twin_may_still_win', '_roads_alive', '_roads_open', '_roads_step', 'WithReserve'),
}
# The keys of the settings that ARCH_ONE §1 names as deleted (a key never comes back as a string either: ``settings['judge_once']``, ``.get('judge_once')``).
GONE_KEYS = {
    'kind': ('judge_once', 'judge_order', 'judge_guard', 'addressed_gate', 'followup_one'),
    'question': ('question_parts',),
    'speech': ('act_gate',),
    'timers': ('timer_guard', 'refuse_anchor', 'order_guard'),
    'memory': ('resume_next_day', 'abbrev_once', 'ledger_disk_kill'),
    'speech-dead': ('game_mode',),
    'modes': ('end_intonation', 'ear_vocab', 'keep_ready', 'adopt_missing_words', 'pcm_record', 'warm_start', 'material_pick', 'spare_helper', 'open_overlap', 'stop_in_flight', 'prepared_speech', 'facts_journal'),      # 16.11: always-on rules of speech / the ear / the fast channel, no key
}
# Keys ARCH_ONE §1 says go (the function is a rule of its owner, always on) and a reader of which still stands today: the list the merge step works down.
TARGET_KEYS = {
    'memory': ('v6_memory', 'topic_recap', 'ledger_carry'),
    'portion': ('portion_sense',),
}


def code_nodes(path):
    """The AST of ``path`` with the docstrings cut out."""
    tree = ast.parse(path.read_text(encoding='utf-8'))
    for node in ast.walk(tree):
        body = getattr(node, 'body', None)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)) and body and isinstance(body[0], ast.Expr) \
                and isinstance(getattr(body[0], 'value', None), ast.Constant) and isinstance(body[0].value.value, str):
            node.body = body[1:] or [ast.Pass()]
    return tree


def uses(names=(), keys=()):
    """``{name or key: [file:line]}`` for every use of a name (definition, import, call, attribute) and every string constant equal to a key in ``echo_sync/**.py``."""
    names, keys, found = set(names), set(keys), {}
    for path in sorted(PACKAGE.rglob('*.py')):
        rel = path.relative_to(ROOT).as_posix()
        for node in ast.walk(code_nodes(path)):
            hit = None
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name in names:
                hit = node.name
            elif isinstance(node, ast.Name) and node.id in names:
                hit = node.id
            elif isinstance(node, ast.Attribute) and node.attr in names:
                hit = node.attr
            elif isinstance(node, ast.alias) and (node.name in names or node.asname in names):
                hit = node.name if node.name in names else node.asname
            elif isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in keys | names:
                hit = node.value
            if hit is not None:
                found.setdefault(hit, []).append('%s:%d' % (rel, getattr(node, 'lineno', 0)))
    return found


def flat(table):
    return sorted({name for names in table.values() for name in names})


def test_the_names_the_families_deleted_are_not_written_again():
    found = uses(names=flat(GONE), keys=flat(GONE_KEYS))
    assert found == {}, 'an old path of a family is back (delete it, or take it into the rows of its owner): %s' % {name: places[:4] for name, places in found.items()}


def test_every_family_that_deleted_a_path_names_it_and_the_two_lists_do_not_overlap():
    assert not set(flat(GONE)) & set(flat(TARGET_NAMES)) and not set(flat(GONE_KEYS)) & set(flat(TARGET_KEYS)) and not set(flat(GONE)) & set(flat(TARGET_KEYS))
    assert set(GONE) | set(GONE_KEYS) | set(TARGET_NAMES) <= {'kind', 'question', 'answer', 'portion', 'timers', 'speech', 'memory', 'modes', 'route', 'speech-dead'}
    assert all(names for names in GONE.values()) and all(names for names in GONE_KEYS.values())


def test_the_old_names_of_the_route_have_no_reader_left():
    """The target for the names: each is the old road-walking of the cloud text channel (one ``Roads`` walker replaces them); red while a def, a call or an alias stands."""
    found = uses(names=flat(TARGET_NAMES))
    assert found == {}, '%d old name(s) of the route still stand: %s' % (len(found), '; '.join('%s: %s' % (name, ', '.join(places[:5])) for name, places in sorted(found.items())))


def test_the_keys_arch_one_says_are_deleted_have_no_reader_left():
    """The target: each of these keys is an always-on rule of its owner. It is red while a reader (a ``settings['key']``, a ``.get('key')``, a row of ``DEFAULTS`` / ``resolve``) stands; each reader named is one to delete with its test."""
    found = uses(keys=flat(TARGET_KEYS))
    keys_left = {key: places for key, places in found.items()}
    assert keys_left == {}, '%d key(s) of ARCH_ONE §1 still have a reader:\n%s' % (len(keys_left), '\n'.join('  %s: %s' % (key, ', '.join(places[:5])) for key, places in sorted(keys_left.items())))


def test_the_detector_finds_a_def_a_call_an_attribute_an_import_and_a_key_string_and_skips_a_docstring(tmp_path, monkeypatch):
    package = tmp_path / 'echo_sync'
    package.mkdir()
    (package / 'a.py').write_text('"""the old _gone_path is mentioned here only."""\nfrom .x import _gone_path as renamed\n\n\ndef _gone_path():\n    """_gone_path docs"""\n    return None\n', encoding='utf-8')
    (package / 'b.py').write_text('def f(settings, obj):\n    # _gone_path in a comment\n    return obj._gone_path(), settings["gone_key"], settings.get("gone_key")\n', encoding='utf-8')
    monkeypatch.setattr(sys_modules(), 'ROOT', tmp_path)
    monkeypatch.setattr(sys_modules(), 'PACKAGE', package)
    found = uses(names=['_gone_path'], keys=['gone_key'])
    assert sorted(found) == ['_gone_path', 'gone_key']
    assert sorted(place.split(':')[0] for place in found['_gone_path']) == ['echo_sync/a.py', 'echo_sync/a.py', 'echo_sync/b.py'] and len(found['gone_key']) == 2


def sys_modules():
    import sys
    return sys.modules[__name__]
