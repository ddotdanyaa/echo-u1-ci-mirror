"""The live pass: the critics answer the rubric and see the mechanical report, and the candidate's gate run is told
which files changed (the cloud gate's eligibility)."""
import pytest

from tests.test_factory_runtime import Rig, verdict


@pytest.fixture(autouse=True)
def _kilo_engine(monkeypatch):
    """The rig fakes the Kilo agent loop through model_attempt (as in test_factory_runtime)."""
    from tools import agent_factory_runner as runner
    monkeypatch.setattr(runner, 'engine_for', lambda role, task: 'kilo')


def test_the_candidate_gate_run_gets_the_changed_files_and_the_base_run_an_empty_list(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    seen = []

    def run_tests(root, tests, timeout_s, workdir=None, wait_s=None, hung=(), trace=(), touched=None):
        seen.append(touched)
        return rig._default_run_tests(root, tests, timeout_s)
    monkeypatch.setattr(rig.w.gate, 'run_tests', run_tests)
    result = rig.once()
    assert result['status'] == 'REVIEW'
    assert seen[0] == ()                                     # the red-before run on the base: no changed files, the cloud may run it
    assert [tuple(t) for t in seen if t] == [('calc.py',)]


def test_an_approval_without_a_real_cited_line_does_not_pass_the_live_chain(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    bare = verdict(True, line='assert nothing_like_this_exists(1)')
    rig.review_script = [bare, bare, bare]
    result = rig.once()
    assert result['status'] == 'READY' and result['reason'].startswith('review')
    assert any('cited line is not in the test' in c for c in result['critiques'])


def test_the_critic_prompt_carries_the_rubric_and_the_execution_report(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    rig.once()
    review_prompt = rig.prompts[1]
    assert 'defect_assert_line' in review_prompt and 'independent_asserts' in review_prompt
    assert 'Mechanical execution report' in review_prompt and 'got -1' in review_prompt
