"""V5 / E33, E33.1: the H5 release went out without a full set and with five reds (own echo counted as an ack, the tail of a repeat cleared the next portion, two SAPI, one more in test_ear_shadow). The
release rule itself («0 failed on the SHA by the final line») is a run of the cloud, not a code path: nothing here replaces it. What this file guards is that the tests of the five reds are still in the tree and
cannot go quiet: no unconditional skip / xfail on them, the worker wait of test_ear_act is tied to the thread being alive (the unbounded wait of the first F5 version has a stop). A text of the tests, not a call."""
import ast
from pathlib import Path

TESTS = Path(__file__).resolve().parent.parent.parent
FILES = ['test_cue_in_flight.py', 'test_ear_act.py', 'test_ear_shadow.py', 'test_tts_trace_integration.py']


def decorators(node):
    return [ast.unparse(d) for d in node.decorator_list]


def test_the_files_of_the_five_reds_exist_and_have_tests():
    for name in FILES:
        text = (TESTS / name).read_text(encoding='utf-8')
        assert 'def test_' in text, name


def test_none_of_the_five_reds_is_silenced_by_a_skip_or_an_xfail():
    quiet = []
    for name in FILES:
        for node in ast.walk(ast.parse((TESTS / name).read_text(encoding='utf-8'))):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                for d in decorators(node):
                    if 'xfail' in d or d.startswith('pytest.mark.skip(') or d == 'pytest.mark.skip' or d.startswith('unittest.skip(') or d == 'unittest.skip':
                        quiet.append((name, node.name, d))
    assert quiet == [], quiet


def test_the_worker_wait_of_the_ear_act_tests_watches_the_thread():
    source = (TESTS / 'test_ear_act.py').read_text(encoding='utf-8')
    assert 'worker thread is gone' in source and 'is_alive()' in source
