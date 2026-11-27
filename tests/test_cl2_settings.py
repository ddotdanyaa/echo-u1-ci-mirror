"""CL2, ruling 6 (memory): the window of the conversation map is no setting any more: ``resume_window_s`` is gone, the window of «the same talk» is ONE number of the timer policy (``CONVERSATION_GAP_S``)."""
from echo_sync import settings as cfg, timer_policy
from echo_sync.engine import resume_window


def test_the_window_of_the_map_is_one_number_of_the_timer_policy_not_a_setting():
    assert 'resume_window_s' not in cfg.DEFAULTS
    assert 'resume_window_s' not in cfg.resolve({'resume_window_s': 60})
    assert resume_window(None) == timer_policy.CONVERSATION_GAP_S == 600


def test_the_notes_have_no_key():
    assert 'progress_notes' not in cfg.resolve(None)


# U20-S2: the timer relations are checked once at call open; every violation is a log line, and call_open carries the rules.
def test_timer_policy_check_logs_the_soft_r8_line_once(caplog):
    import logging
    with caplog.at_level(logging.WARNING, logger='echo-sync'):
        rules = cfg.timer_policy_check(cfg.resolve({'repeat_seconds': 1.0}))
    lines = [r.getMessage() for r in caplog.records if 'R8' in r.getMessage()]
    assert len(lines) == 1
    assert rules == ['R8']


OWNER_LIKE = {'ack_match': 'stem', 'on_mismatch': 'replay_if_attempt', 'local_ear': 'act', 'fast_text': 'on', 'prompt_tempo': 'ear', 'ear_release': 'on', 'max_auto_repeats': 3,
              'repeat_rule': 'on', 'dictation_cycle': 'on', 'ear_job': 'on', 'two_witnesses': 'on', 'warm_start': 'on', 'text_transport': 'http'}      # a copy of the owner's profile file (07.11): repeat_seconds is not set there, its resolved value is 2.0


def test_timer_policy_check_with_the_owners_settings_is_silent_so_r8_is_a_relation_for_other_values(caplog):
    """U20-S2 (coordinator to confirm R8): the owner's own profile trips no relation, soft or hard, so the R8 line is NOT expected there; R8 fires only for a repeat_seconds under the answer grace."""
    import logging
    resolved = cfg.resolve(OWNER_LIKE)
    assert resolved['repeat_seconds'] == 2.0
    with caplog.at_level(logging.WARNING, logger='echo-sync'):
        assert cfg.timer_policy_check(resolved) == []
    assert not [r for r in caplog.records if 'timer relation' in r.getMessage()]


def test_timer_policy_check_is_silent_for_the_defaults(caplog):
    import logging
    with caplog.at_level(logging.WARNING, logger='echo-sync'):
        assert cfg.timer_policy_check(cfg.resolve(None)) == []
    assert not [r for r in caplog.records if 'timer' in r.getMessage()]
