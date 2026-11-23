"""fac-reject, part 3 of 3: the promote stays idempotent by looking for an earlier 'factory(<task>):' commit; a commit
the coordinator rejected must never count as 'already merged' when the redone task is promoted again."""
import json

from test_factory_loop import Env, git, env, BRANCH  # noqa: <id>


def head(e):
    return git(e.repo, "rev-parse", BRANCH)


def test_the_redone_task_is_merged_again_and_not_taken_for_the_rejected_commit(env):
    (env.repo / "tools" / "x1.py").write_text("a = 3\n", encoding="utf-8")     # the rejected candidate
    git(env.repo, "commit", "-qam", "factory(T1): task 1")
    rejected = head(env)
    env.set_row("T1", status="REVIEW")                     # the redone candidate passed the gate and the review
    env.package("T1", {"tools/x1.py": "a = 2\n"})
    env.set_loop_state(bases={"T1": rejected}, rejected={"T1": [rejected]})
    env.loop().step()
    row = env.state()["tasks"]["T1"]
    assert row["status"] == "PROMOTED" and row["commit"] != rejected
    assert (env.repo / "tools" / "x1.py").read_text(encoding="utf-8") == "a = 2\n"
    ls = json.loads((env.state_dir / "loop_state.json").read_text(encoding="utf-8"))
    assert ls.get("rejected", {}).get("T1") == [rejected]                       # the record stays
