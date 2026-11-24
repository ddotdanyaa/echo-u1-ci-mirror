"""fac-owner-data (critic round 1, security, low, 19.11 21:33): OWNER_PATHS closed the code of the acceptance tools
but not the data that decides their verdicts. tools/data/push_guard_allow.txt (push_guard's allowlist: one line such
as 'tests/*' silences the secret scan of every test file), tools/data/known_red.txt (red_ratchet's acknowledged reds)
and tools/owner_census_caps.json (the census ceilings) could be put into a factory task by the triage or an Opus
answer and merged by the loop. They are owner paths: only a task the coordinator writes by hand names them."""
from tools import factory_gate as G

DATA = ('tools/data/push_guard_allow.txt', 'tools/data/known_red.txt', 'tools/owner_census_caps.json')


def test_the_data_of_the_acceptance_tools_is_closed_without_a_name():
    for path in DATA:
        assert G.is_forbidden(path, 'code'), path
        assert G.is_forbidden(path, 'unit_test'), path


def test_a_hand_written_task_that_names_the_file_may_change_it():
    for path in DATA:
        assert not G.is_forbidden(path, 'code', (path,)), path
