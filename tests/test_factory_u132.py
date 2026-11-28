# factory-backlog-id: U132
from tools.harvest import measure as M


def test_passport_states_the_latency_target_and_its_origin():
    passport = M.stage_table([])['passport']
    assert passport.get('target') == {
        'plain_s': [0.3, 0.6],
        'search_s': 1.0,
        'from': 'the end of the owner phrase to the first sound',
    }
