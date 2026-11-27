"""fac-reject, part 1 of 3: the coordinator's CLI verb. Live 19.11 19:24: <id>_test was merged with a test that
fails by calling build() wrongly, and the loop had no way back but 'accept'. `answer --reject` needs a task and a
note and nothing else, and writes reject=True into the answer file."""
import json

import pytest

from tools import factory_loop as L
from test_factory_loop import Env, env  # noqa: <id>


def test_cli_reject_needs_a_task_and_a_note_and_nothing_else(env):
    d = str(env.state_dir)
    with pytest.raises(SystemExit):
        L.main(["answer", "--state-dir", d, "--task-id", "T1", "--reject"])                       # no note
    with pytest.raises(SystemExit):
        L.main(["answer", "--state-dir", d, "--backlog-id", "B1", "--reject", "--note", "x"])     # no task
    with pytest.raises(SystemExit):
        L.main(["answer", "--state-dir", d, "--task-id", "T1", "--reject", "--accept", "--note", "x"])
    with pytest.raises(SystemExit):
        L.main(["answer", "--state-dir", d, "--task-id", "T1", "--reject", "--touch", "tools/x1.py", "--note", "x"])
    assert L.main(["answer", "--state-dir", d, "--task-id", "T1", "--reject", "--note", "why"]) == 0
    (name,) = list((env.state_dir / "answers").glob("*.json"))
    assert json.loads(name.read_text(encoding="utf-8"))["reject"] is True
