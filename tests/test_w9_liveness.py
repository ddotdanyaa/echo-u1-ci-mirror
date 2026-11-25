"""W9-arch: the pure witness of the cloud (echo_sync/arch_liveness.py). No clock, no I/O."""
from echo_sync.arch_liveness import CLOUD_DEAF_S, MIN_RUN_S, CloudWitness


def test_off_says_nothing():
    w = CloudWitness(0)
    w.speech(0, 'cloud')
    assert w.verdict(1e6) is None


def test_a_turn_the_cloud_opened_and_never_spoke_of_again_is_deafness_once():
    w = CloudWitness()
    w.event(0); w.speech(0, 'cloud')
    assert w.verdict(CLOUD_DEAF_S - 0.1) is None
    assert w.verdict(CLOUD_DEAF_S) == 'deaf'
    assert w.verdict(CLOUD_DEAF_S + 60) is None, 'once'


def test_any_event_of_the_cloud_rearms_it():
    w = CloudWitness()
    w.speech(0, 'cloud')
    w.event(5)
    assert w.verdict(30) is None, 'the cloud spoke after the speech: nothing is owed'
    w.speech(31, 'words')
    assert w.verdict(31 + CLOUD_DEAF_S) == 'deaf'
    w.event(50); w.speech(51, 'words')
    assert w.verdict(51 + CLOUD_DEAF_S) == 'deaf', 'told again after the cloud came back and went again'


def test_a_cough_or_a_click_of_the_detector_is_no_speech():
    w = CloudWitness()
    w.speech(0, 'onset'); w.speech(0.4, 'run')
    assert w.verdict(100) is None


def test_a_long_run_of_the_detector_is_speech_counted_from_its_last_sign():
    w = CloudWitness()
    w.speech(0, 'onset')
    t = 0.0
    while t < 20:
        t += 0.1
        w.speech(t, 'run')
    assert w.verdict(t + CLOUD_DEAF_S - 0.2) is None, 'a monologue: the count starts when it stops'
    assert w.verdict(t + CLOUD_DEAF_S) == 'deaf'
    assert MIN_RUN_S < 20


def test_ear_text_without_words_is_not_passed_as_words_by_the_caller_but_words_count():
    w = CloudWitness()
    w.speech(0, 'nonsense')
    assert w.verdict(100) is None
    w.speech(1, 'words')
    assert w.verdict(1 + CLOUD_DEAF_S) == 'deaf'
