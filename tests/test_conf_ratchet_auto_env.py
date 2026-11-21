"""CONF: the ratchet reads a cloud run without hand edits: a red whose own message names a missing module or data file is «cloud-env (auto)»; a run of the base makes its reds «base»; everything else stays a new red."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import red_ratchet as R  # noqa: E402

DONE = '=== test session starts ===\n{lines}\n=== {n} failed, 5 passed in 3.2s ===\n'


def run(tmp_path, capsys, lines, base=None):
    run_file, known, env = tmp_path / 'run.txt', tmp_path / 'known.txt', tmp_path / 'env.txt'
    run_file.write_text(DONE.format(lines='\n'.join(lines), n=len(lines)), encoding='utf-8')
    known.write_text('', encoding='utf-8')
    env.write_text('', encoding='utf-8')
    extra = []
    if base is not None:
        base_file = tmp_path / 'base.txt'
        base_file.write_text(DONE.format(lines='\n'.join(base), n=len(base)), encoding='utf-8')
        extra = ['--base', str(base_file)]
    code = R.main([str(run_file), '--known', str(known), '--env', str(env), *extra])
    return code, capsys.readouterr().out


def test_a_missing_module_in_the_message_is_the_environment(tmp_path, capsys):
    code, out = run(tmp_path, capsys, ["FAILED tests/test_a.py::test_x - ModuleNotFoundError: No module named 'razdel'"])
    assert code == 0 and 'cloud-env-auto: 1' in out and 'new: 0' in out and 'razdel' in out


def test_a_missing_cloud_data_file_is_the_environment(tmp_path, capsys):
    code, out = run(tmp_path, capsys, ["FAILED tests/test_a.py::test_x - FileNotFoundError: [Errno 2] No such file or directory: 'cloud_context/bank/instant_bank_2.json'"])
    assert code == 0 and 'cloud-env-auto: 1' in out


def test_a_module_of_the_product_or_an_assert_stays_a_new_red(tmp_path, capsys):
    code, out = run(tmp_path, capsys, ["FAILED tests/test_a.py::test_x - ModuleNotFoundError: No module named 'echo_sync.gone'", "FAILED tests/test_a.py::test_y - KeyError: 'fast_private'"])
    assert code == 1 and 'new: 2' in out and 'cloud-env-auto: 0' in out


def test_a_red_that_is_red_at_the_base_too_is_not_new(tmp_path, capsys):
    code, out = run(tmp_path, capsys, ['FAILED tests/test_a.py::test_x - assert 1 == 2', 'FAILED tests/test_a.py::test_new - boom'], base=['FAILED tests/test_a.py::test_x - assert 1 == 2'])
    assert code == 1 and 'base: 1' in out and 'new: 1' in out and 'NEW RED tests/test_a.py::test_new' in out
    assert 'NEW RED tests/test_a.py::test_x' not in out


def test_a_junit_failure_message_is_read(tmp_path, capsys):
    xml = '<testsuites><testsuite><testcase classname="tests.test_a" name="test_x"><failure message="ModuleNotFoundError: No module named \'pymorphy3\'">tb</failure></testcase></testsuite></testsuites>'
    run_file = tmp_path / 'run.xml'
    run_file.write_text(xml, encoding='utf-8')
    known = tmp_path / 'known.txt'
    known.write_text('', encoding='utf-8')
    assert R.main([str(run_file), '--known', str(known), '--env', str(tmp_path / 'none.txt')]) == 0
    assert 'cloud-env-auto: 1' in capsys.readouterr().out
