"""fac-fit-views (live 20.11 04:29): four tasks were BLOCKED context_too_large before any model call, every time, because
their tests were always shown whole (one test file alone was 50 KB; another task had five test files, 68 KB). Which
file is shown whole and which as outline + parts is ONE rule (large_names) for the coder, the reviewer, prepare() and
the pass's size check: every file over LARGE_FILE_CHARS, tests too, then the largest of the rest until the whole ones
and VIEW_ROOM per view fit FIT_ROOM. The failing test, and what it uses from its file, is shown first."""
import json
from dataclasses import replace
from pathlib import Path

from tools import agent_factory as F
from tools import agent_factory_runner as W
from tools import factory_channels as C
from tools.factory_context import failing_names, identifier_tokens

SRC = Path(__file__).resolve().parents[1] / 'tools' / 'agent_factory_runner.py'


def _task(**kw):
    base = F.read_plan([dict(id='T1', title='Fix the repeat rule', touch_files=['calc.py'],
                             tests=['tests/test_big.py'], privacy_safe=True, estimated_tokens=100)])['T1']
    return replace(base, **kw)


HEAD = '''import pytest
from calc import add


@pytest.fixture
def engine():
    return {"engine": 1}


def _make(value):
    made_marker = value
    return made_marker


def test_target(engine):
    target_marker = _make(2)
    assert add(target_marker, engine["engine"]) == 3
'''


def _big_test(n=560):
    """A test file of about 50 KB: n tests with a unique body marker each, a fixture and a helper of the target."""
    rows = [HEAD]
    rows += ['\n\ndef test_case_%d():\n    body_marker_%d = %d\n    assert add(body_marker_%d, 0) == %d\n'
             % (i, i, i, i, i) for i in range(n)]
    return ''.join(rows).encode()


def _visible(test=None):
    return {'calc.py': b'def add(a, b):\n    return a - b\n', 'tests/test_big.py': test or _big_test()}


def test_a_big_test_is_shown_as_outline_with_the_failing_test_and_what_it_uses_whole():
    visible = _visible()
    assert len(visible['tests/test_big.py']) > 40000
    failing = 'tests.test_big::test_target[p1], tests.test_big::test_target[p2]\nAssertionError: assert -1 == 3'
    prompt = W.build_coder_prompt(_task(), visible, failing=failing, light=True)
    assert len(prompt) <= C.PROMPT_LIMIT_CHARS
    assert 'FILE tests/test_big.py (LARGE' in prompt
    assert 'target_marker = _make(2)' in prompt                    # the failing test, whole
    assert 'made_marker = value' in prompt                         # the helper it calls
    assert 'return {"engine": 1}' in prompt                        # the fixture it takes
    assert 'body_marker_250 = 250' not in prompt                   # a test far from it: only its outline row
    assert 'FILE calc.py\ndef add(a, b):' in prompt                # the small source stays whole


def test_failing_names_are_the_tests_of_the_ids_and_what_they_use_from_their_file():
    names = failing_names('tests.test_big::test_target[p1]\ndiag text', {'tests/test_big.py': _big_test(3)})
    assert {'test_target', '_make', 'engine'} <= names
    assert 'test_case_1' not in names
    assert failing_names('', {'tests/test_big.py': _big_test(3)}) == frozenset()


def test_prepare_stages_a_task_whose_test_alone_overflows_the_prompt(tmp_path):
    root = tmp_path / 'repo'
    for name, data in _visible().items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_bytes(data)
    staged = W.prepare(root, _task(), tmp_path / 'work')
    assert staged['tests/test_big.py'] == _big_test()


def test_the_largest_whole_files_become_views_until_the_rest_fits_the_prompt():
    t = _task(tests=('tests/test_a.py', 'tests/test_b.py', 'tests/test_c.py', 'tests/test_d.py'))
    files = {'calc.py': b'x' * 5000, 'tests/test_a.py': b'a' * 10000, 'tests/test_b.py': b'b' * 9000,
             'tests/test_c.py': b'c' * 8000, 'tests/test_d.py': b'd' * 700}
    big = W.large_names(t, files)
    whole = sum(len(v) for n, v in files.items() if n not in big)
    assert whole + W.VIEW_ROOM * len(big) <= W.FIT_ROOM
    assert 'tests/test_a.py' in big and 'tests/test_d.py' not in big and 'calc.py' not in big
    small = {n: b'y' * 3000 for n in ('calc.py', 'tests/test_a.py')}
    assert W.large_names(_task(tests=('tests/test_a.py',)), small) == set()     # what fits stays whole


def test_the_reviewer_shows_a_big_test_as_outline_and_reviews(tmp_path):
    for name, data in _visible().items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_bytes(data)
    seen = []

    def invoke(reviewer, root, model, prompt_override):
        seen.append(prompt_override)
        return 0, (json.dumps({'type': 'text', 'part': {'text': '{"approved": true}'}}) + '\n').encode(), b''
    verdict = W.review_candidate(_task(), tmp_path, 'google/y', invoke, baseline={'calc.py': b'old\n'})
    assert verdict == (True, []) and 'FILE tests/test_big.py (LARGE' in seen[0]
    assert len(seen[0]) <= C.PROMPT_LIMIT_CHARS


def test_a_long_word_never_makes_the_name_search_quadratic():
    """Live 20.11: a 29 000-character comment word in a test cost 20 s per prompt (each start inside the word
    re-scanned the rest of it); 200 000 characters would have taken hours."""
    import time
    text = 'from calc import add\n# ' + 'y' * 200000 + '\nmod.func_name(x) and file.py and CamelCase 9abc.def'
    start = time.perf_counter()
    found = identifier_tokens(text)
    assert time.perf_counter() - start < 2.0
    assert {'mod', 'func_name', 'CamelCase', 'abc', 'def'} <= found and 'file' not in found and 'py' not in found


def test_the_rule_is_written_once():
    """Three copies of the rule (coder, reviewer, read budget) drifted apart before: one function decides."""
    assert SRC.read_text(encoding='utf-8').count('> LARGE_FILE_CHARS') == 1
