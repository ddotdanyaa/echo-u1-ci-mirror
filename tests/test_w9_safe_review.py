"""w9-safe, N179: cloud_context/safe/review_cloud_patch.py, the check of a cloud branch before it is merged. The tokens here are built at run
time, so that this file holds none (and its own check passes)."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('review_cloud_patch', ROOT / 'cloud_context' / 'safe' / 'review_cloud_patch.py')
rc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rc)

TOKEN = 'gh' + 'p_' + 'Q7w' * 12
KEY = 's' + 'k-proj-' + 'R4t9' * 10


def diff(path, added=(), removed=()):
    lines = [f'diff --git a/{path} b/{path}', f'--- a/{path}', f'+++ b/{path}', '@@ -1,3 +10,3 @@']
    return '\n'.join(lines + ['-' + r for r in removed] + ['+' + a for a in added]) + '\n'


def rules(text):
    return [(f['level'], f['rule'], f['line']) for f in rc.review(text)]


def test_a_real_looking_token_is_blocked_and_never_printed():
    found = rc.review(diff('echo_sync/x.py', [f"HEADERS = {{'Authorization': 'Bearer {TOKEN}'}}", f'KEY = "{KEY}"']))
    assert {(f['level'], f['rule']) for f in found} == {('block', 'secret')} and [f['line'] for f in found] == [10, 11]
    printed = rc.table('b', found)
    assert TOKEN not in printed and KEY not in printed and 'R4t9' not in printed


def test_the_fakes_of_the_tests_pass():
    assert rules(diff('tests/test_x.py', ["SECRET = 'tok-SECRET-0123456789'", "creds = {'api_key': 'header.payload.signature'}",
                                          "env = {'OPENAI_API_KEY': 'not-a-real-key-0123456789'}", "token = 'do-not-copy-0123456789'"])) == []


def test_a_password_assigned_in_a_config_is_blocked():
    assert rules(diff('cloud_context/notes.md', ['password: "' + 'k3J9-q' + 'Lm2-zZ81"'])) == [('block', 'secret', 10)]


def test_a_call_trace_added_as_data_is_blocked():
    assert ('block', 'call_trace', 10) in rules(diff('cloud_context/analysis/call.jsonl', ['{"t": 5, "ev": "user_final", "text": "..."}']))
    assert ('block', 'call_trace', None) in rules(diff('cloud_context/logs/echo_calls/20261105-101500-abc123.jsonl', ['{}']))


def test_a_new_network_import_and_a_text_log_in_the_engine_are_warned():
    found = rules(diff('echo_sync/new.py', ['import urllib.request', "logger.info('asked %s', question)", "logger.info('chars=%s', len(question))",
                                            "logger.warning('x', exc_info=True)", "logger.info(f'{text}')"]))
    assert found == [('warn', 'network', 10), ('warn', 'log_text', 11), ('warn', 'log_text', 13), ('warn', 'log_text', 14)]


def test_weakened_tests_are_warned():
    found = rules(diff('tests/test_y.py', ['@pytest.mark.skip(reason="later")', '@pytest.mark.xfail(reason="x")', '@pytest.mark.xfail(strict=True)'],
                       ['    assert a == 1', '    assert b == 2']))
    assert ('warn', 'weak_test', 10) in found and ('warn', 'weak_test', 11) in found and ('warn', 'weak_test', None) in found
    assert ('warn', 'weak_test', 12) not in found


def test_files_with_owners_are_named():
    found = rc.review(diff('echo_sync/controlled_media.py', ['x=1']) + diff('cloud_context/scripts/run.py', ['y=2']))
    assert [(f['rule'], f['note']) for f in found] == [('owner', 'coordinator'), ('owner', 'A4')]


def test_the_check_passes_on_its_own_files():
    for name in ('cloud_context/safe/review_cloud_patch.py', 'tests/test_w9_safe_review.py', 'echo_sync/privacy_gate.py', 'tests/test_w9_safe.py'):
        text = (ROOT / name).read_text(encoding='utf-8')
        found = [f for f in rc.review(diff(name, text.splitlines())) if f['level'] == 'block']
        assert found == [], (name, found)


def test_ids_and_code_that_builds_trace_records_are_not_secrets():
    """The whole history of the repository (git log --all -p, 272 commits) gave these as false blocks before: a session id of a test, a trace record built in code."""
    assert rules(diff('tests/test_z.py', ["c = ControlledMedia(p, session_id='native-probe-' + '0' * 32)"])) == []
    assert rules(diff('cloud_context/scripts/chain.py', ["rows = [{'t': 5, 'ev': 'user_final', 'text': 'x'}]"])) == [('info', 'owner', None)]
