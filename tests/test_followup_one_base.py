"""followup-base -> the one base of a follow-up: ``followup.asked_of`` takes the floor of the call (``state['call_began']``) itself, so the classifier, the
judge's rows and the controller see the same questions: «а почему?» is no follow-up to yesterday's question (A4)."""
from echo_sync.followup import asked_of

STATE = {'history': [{'question': 'Что такое инерция?', 'at': 100.0, 'status': 'done', 'spoken': 'x'}], 'question': 'Что такое масса?', 'issued_at': 150.0}


def test_no_floor_sees_the_whole_history():
    assert asked_of(STATE) == ['Что такое инерция?', 'Что такое масса?']


def test_a_call_that_began_later_inherits_nothing_of_the_call_before():
    assert asked_of({**STATE, 'call_began': 200.0}) == []
    assert asked_of({**STATE, 'call_began': 120.0}) == ['Что такое масса?']


def test_the_controller_state_carries_the_floor_and_the_classifier_reads_it(tmp_path):
    from echo_sync.classifier import analyze
    stale = {**STATE, 'call_began': 200.0}
    assert analyze('а почему', stale, [], None).reason != 'context_followup'
