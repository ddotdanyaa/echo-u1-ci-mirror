"""A hollow unit test passes the gate (night 20.11: five factory tests, all through the gate and one critic). Red only
because it asserts an invented name (<id> 441c6bc7: hasattr(trace, 'environment_consistency')), reads the code text
instead of running it (UQX126 71133258: inspect.getsource), or asserts only `is not None` (UQX61 cQX47f05bf). A brand-new
test file got no content check at all. Deterministic: ast of the test + a symbol index of the base tree."""
from __future__ import annotations

from tools import factory_gate as fg

SRC = (
    "class CallTrace:\n"
    "    def __init__(self, directory=None, call_id=''):\n"
    "        self.directory = directory\n"
    "        self.call_id = call_id\n"
    "\n"
    "    def record(self, event):\n"
    "        return event\n"
    "\n"
    "_TABLE = {'wake': 'on_wake_tick'}\n"
    "\n"
    "def serve():\n"
    "    return 5\n"
)


def base(tmp_path, test_text=None):
    pkg = tmp_path / "echo_sync"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "call_trace.py").write_text(SRC, encoding="utf-8")
    (tmp_path / "tests").mkdir()
    if test_text is not None:
        (tmp_path / "tests" / "test_x.py").write_text(test_text, encoding="utf-8")
    return tmp_path


def check(root, text, kind="unit_test"):
    return fg.weakening_violations(root, {"tests/test_x.py": text}, kind)


INVENTED = (
    "﻿# factory-backlog-id: UQX126\n"
    "from echo_sync import call_trace\n"
    "\n"
    "def test_uQX126():\n"
    "    trace = call_trace.CallTrace(directory=None, call_id='t')\n"
    "    assert hasattr(trace, 'environment_consistency') or hasattr(trace, 'browser_fingerprint_check')\n"
)

GETSOURCE = (
    "import inspect\n"
    "from echo_sync import call_trace\n"
    "\n"
    "def test_uQX126():\n"
    "    source = inspect.getsource(call_trace.serve)\n"
    "    assert 'sleep(5)' not in source\n"
)

NOT_NONE = (
    "from echo_sync import call_trace\n"
    "\n"
    "def test_uQX61():\n"
    "    res = call_trace.CallTrace().record('x')\n"
    "    assert res is not None\n"
)


# ---- red before: each of these returned [] ------------------------------------------------------------------

def test_invented_hasattr_name_is_rejected_with_the_name(tmp_path):
    v = check(base(tmp_path), INVENTED)
    assert v and any("'environment_consistency'" in x and "defined nowhere" in x for x in v), v
    assert any(x.startswith("tests/test_x.py:") for x in v)


def test_reading_the_code_text_is_rejected(tmp_path):
    v = check(base(tmp_path), GETSOURCE)
    assert v and any("inspect.getsource" in x for x in v), v


def test_only_is_not_none_is_rejected(tmp_path):
    v = check(base(tmp_path), NOT_NONE)
    assert v and any("is not None" in x for x in v), v


def test_new_file_without_a_base_copy_is_inspected(tmp_path):
    root = base(tmp_path)
    assert not (root / "tests" / "test_x.py").exists()
    for text in (INVENTED, GETSOURCE, NOT_NONE):
        assert check(root, text), text


def test_existing_file_rejects_only_growth(tmp_path):
    root = base(tmp_path, GETSOURCE)
    assert check(root, GETSOURCE) == []
    more = GETSOURCE + "\n\ndef test_more():\n    assert 'x' not in inspect.getsource(call_trace.CallTrace)\n"
    v = check(root, more)
    assert v and any("inspect.getsource" in x for x in v), v
    # an honest test added next to the old grep-lock inherits nothing
    honest = GETSOURCE + "\n\ndef test_ok():\n    assert call_trace.serve() == 5\n"
    assert check(root, honest) == []


def test_dotted_invented_name_on_a_project_module_is_rejected(tmp_path):
    text = "from echo_sync import call_trace\n\ndef test_a():\n    assert call_trace.fingerprint_check() == 1\n"
    v = check(base(tmp_path), text)
    assert v and any("'fingerprint_check'" in x for x in v), v


# ---- guards: green before and after -------------------------------------------------------------------------

def test_not_hasattr_proves_an_old_name_is_gone(tmp_path):
    text = ("from echo_sync import call_trace\n\ndef test_gone():\n"
            "    assert not hasattr(call_trace, 'old_name')\n    assert call_trace.serve() == 5\n")
    assert check(base(tmp_path), text) == []


def test_name_present_only_as_a_string_in_a_table_is_known(tmp_path):
    text = ("from echo_sync import call_trace\n\ndef test_t():\n"
            "    trace = call_trace.CallTrace()\n    assert hasattr(trace, 'on_wake_tick') is False\n"
            "    assert getattr(trace, 'on_wake_tick', 1) == 1\n")
    assert check(base(tmp_path), text) == []


def test_real_call_with_existing_names_passes(tmp_path):
    text = ("from echo_sync import call_trace\n\ndef test_t():\n"
            "    trace = call_trace.CallTrace(call_id='c')\n    assert hasattr(trace, 'record')\n"
            "    assert trace.record('e') == 'e'\n    assert trace.call_id == 'c'\n")
    assert check(base(tmp_path), text) == []


def test_other_kinds_unchanged(tmp_path):
    root = base(tmp_path)
    for text in (INVENTED, GETSOURCE, NOT_NONE):
        assert fg.weakening_violations(root, {"echo_sync/m.py": text}, "bugfix") == []
        assert fg.weakening_violations(root, {"tests/test_x.py": text}, "bugfix") == [
            "tests/test_x.py: tests/** may be changed only by a unit_test task"]


def test_names_the_test_creates_by_string_are_known(tmp_path):
    # critic 20.11: monkeypatch/mock create a name from a string; these were rejected as "defined nowhere"
    root = base(tmp_path)
    for setup in ("    monkeypatch.setattr('echo_sync.call_trace.zz_hook', lambda: 1, raising=False)\n",
                  "    monkeypatch.setitem(call_trace.__dict__, 'zz_hook', lambda: 1)\n",
                  "    object.__setattr__(call_trace, 'zz_hook', lambda: 1)\n",
                  "    mock.patch.object(call_trace, 'zz_hook', create=True).start()\n",
                  "    mock.patch('echo_sync.call_trace.zz_hook', create=True).start()\n"):
        text = ("from unittest import mock\nfrom echo_sync import call_trace\n\ndef test_t(monkeypatch):\n" + setup
                + "    assert hasattr(call_trace, 'zz_hook')\n    assert call_trace.zz_hook() is not False\n")
        assert check(root, text) == [], setup


def test_aliased_inspect_getsource_is_rejected(tmp_path):
    text = GETSOURCE.replace("import inspect\n", "import inspect as ins\n").replace("inspect.getsource", "ins.getsource")
    v = check(base(tmp_path), text)
    assert v and any("getsource" in x for x in v), v


def test_index_sees_a_name_added_to_the_source_after_the_first_build(tmp_path):
    root = base(tmp_path)
    assert check(root, INVENTED)
    (root / "echo_sync" / "call_trace.py").write_text(
        SRC + "\ndef environment_consistency():\n    return 1\n\ndef browser_fingerprint_check():\n    return 1\n",
        encoding="utf-8")
    assert check(root, INVENTED) == []


# ---- rule G: an OR of lookups by guessed keys ----------------------------------------------------------------

GUESSED = (
    "from echo_sync import call_trace\n"
    "\n"
    "def test_g():\n"
    "    d = call_trace.CallTrace().record({})\n"
    "    assert d.get('env_ok') is True or d.get('browser_fp') is True\n"
)


def test_an_or_of_guessed_keys_is_rejected_with_the_keys(tmp_path):
    for text in (GUESSED, GUESSED.replace("d.get('env_ok') is True or d.get('browser_fp') is True",
                                          "d['env_ok'] or d['browser_fp']")):
        sub = tmp_path / ("a%d" % len(text))
        sub.mkdir()
        v = check(base(sub), text)
        assert v and any("guessed" in x and "'env_ok'" in x and "'browser_fp'" in x for x in v), v


def test_an_or_with_a_key_the_code_has_is_fine(tmp_path):
    root = base(tmp_path)
    text = GUESSED.replace("'env_ok'", "'call_id'")
    assert check(root, text) == []
    # the key lives as a string literal in a table of the base source
    assert check(root, GUESSED.replace("'browser_fp'", "'on_wake_tick'")) == []


def test_an_or_over_keys_the_test_itself_builds_is_fine(tmp_path):
    text = ("def test_g():\n    d = {'env_ok': True}\n"
            "    assert d.get('env_ok') is True or d.get('browser_fp') is True\n")
    assert check(base(tmp_path), text) == []


def test_a_single_lookup_or_a_plain_or_is_not_rule_g(tmp_path):
    root = base(tmp_path)
    one = GUESSED.replace(" or d.get('browser_fp') is True", " or d is None")
    assert check(root, one) == []


def test_rule_g_flags_no_accepted_factory_test():
    """False-positive measure: the accepted tests of the factory's own night tree must not trip rule G."""
    import ast
    import pytest
    from pathlib import Path
    import os
    tree = Path(os.environ.get("ACCEPTED_TESTS_TREE", "."))
    if not (tree / "tests").is_dir() or "ACCEPTED_TESTS_TREE" not in os.environ:
        pytest.skip("set ACCEPTED_TESTS_TREE to a tree whose tests were accepted by the factory")
    names, _ = fg.symbol_index(tree)
    hits = []
    for p in sorted((tree / "tests").glob("test_*.py")):
        t = fg._parse_py(p.read_text(encoding="utf-8", errors="replace"))
        if t is None:
            continue
        known = names | fg._defined_names(p.read_text(encoding="utf-8", errors="replace"))
        hits += [(p.name, w) for _, w in fg._guessed_key_hits(t, known, getattr(names, 'words', frozenset()))]
    assert hits == []


# ---- rule G, membership form: loops and single lookups over keys the code never mentions ----------------------

LOOP_GUESSED = (
    "from echo_sync import call_trace\n"
    "\n"
    "def test_stages():\n"
    "    stages = call_trace.CallTrace().record({})\n"
    "    for stage_key in ('evidence', 'recognition', 'admission', 'approval', 'record', 'call_id'):\n"
    "        assert stage_key in stages\n"
)

OR_GET = (
    "from echo_sync import call_trace\n"
    "\n"
    "def test_state():\n"
    "    state = call_trace.CallTrace().record({})\n"
    "    assert state.get('persistent') is True or state.get('persistent_routing') is True "
    "or state.get('persistent_mode') is True\n"
)


def test_loop_over_mostly_unknown_keys_is_rejected(tmp_path):
    v = check(base(tmp_path), LOOP_GUESSED)
    assert v and any("loops over keys" in x and "'evidence'" in x and "4 of 6" in x for x in v), v


def test_or_of_get_calls_on_unknown_keys_is_rejected(tmp_path):
    v = check(base(tmp_path), OR_GET)
    assert v and any("guessed" in x and "'persistent'" in x for x in v), v


def test_single_membership_on_an_unknown_key_is_rejected(tmp_path):
    root = base(tmp_path)
    for stmt in ("assert 'browser_fp' in d", "assert d['browser_fp'] == 3", "assert d.get('browser_fp') is True"):
        text = ("from echo_sync import call_trace\n\ndef test_m():\n"
                "    d = call_trace.CallTrace().record({})\n    " + stmt + "\n")
        v = check(root, text)
        assert v and any("'browser_fp'" in x for x in v), (stmt, v)


def test_membership_in_keys_the_test_builds_is_fine(tmp_path):
    root = base(tmp_path)
    loop = ("def test_m():\n    d = {'evidence': 1, 'recognition': 2, 'admission': 3}\n"
            "    for k in ('evidence', 'recognition', 'admission'):\n        assert k in d\n")
    assert check(root, loop) == []
    single = "def test_m():\n    d = {'browser_fp': 1}\n    assert d['browser_fp'] == 1\n    assert 'browser_fp' in d\n"
    assert check(root, single) == []


def test_membership_in_keys_the_code_has_is_fine(tmp_path):
    root = base(tmp_path)
    loop = ("from echo_sync import call_trace\n\ndef test_m():\n    d = call_trace.CallTrace().record({})\n"
            "    for k in ('directory', 'call_id', 'record', 'wake_gone'):\n        assert k in d\n")
    assert check(root, loop) == []
    assert check(root, "def test_m():\n    d = {}\n    assert d.get('call_id') == 1\n"
                       "    assert 'on_wake_tick' in d\n") == []
    # absence is not a guess
    assert check(root, "def test_m():\n    d = {}\n    assert 'browser_fp' not in d\n"
                       "    assert d.get('browser_fp') is None\n") == []


def test_membership_in_a_word_the_code_prints_is_fine(tmp_path):
    root = base(tmp_path)
    (root / "echo_sync" / "call_trace.py").write_text(
        SRC + "\nLOG = 'portion taken after_veto here'\n", encoding="utf-8")
    text = "def test_m(caplog):\n    assert 'after_veto' in caplog.text\n"
    assert check(root, text) == []
    assert check(root, text.replace("after_veto", "after_nothing"))
