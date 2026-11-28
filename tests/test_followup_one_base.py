"""followup-base -> the one base of a follow-up: ``engine.asked_of`` takes the floor of the call (``state['call_began']``) itself, so the classifier, the
judge's rows and the controller see the same questions: «а почему?» is no follow-up to yesterday's question (A4)."""
from echo_sync.engine import asked_of

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


def test_engine_history_is_the_one_selector_of_the_calls_past_and_an_unasked_exchange_is_in_none_of_its_readers():
    """memory / engine-history: ``engine.call_history`` is read by the follow-up base, the controller's ``call_exchanges`` and the model's ``model_history``; an exchange whose entry says
    ``unasked`` (the ear opened it, the cloud's final took it back) is in none of them - no controller keeps a list of its own (``ear_unasked`` is gone)."""
    from echo_sync.engine import UNASKED, call_history, model_history
    rows = [{'question': 'Что такое инерция?', 'answer': 'a', 'at': 100.0, 'status': 'complete'},
            {'question': 'Что такое тоска?', 'answer': 'b', 'at': 120.0, 'status': UNASKED}]
    state = {'history': rows, 'question': 'Что такое тоска?', 'issued_at': 121.0}
    assert [e['question'] for e in call_history(state)] == ['Что такое инерция?']
    assert asked_of(state) == ['Что такое инерция?'], 'the question in play of an exchange that never happened is no topic either'
    assert [e['question'] for e in model_history(rows)] == ['Что такое инерция?']
    assert [e['question'] for e in call_history({**state, 'call_began': 110.0})] == []
    assert [e['question'] for e in call_history(state, floor=100.0)] == ['Что такое инерция?']


def test_a_repair_of_the_text_channel_keeps_the_question_as_the_topic_of_a_follow_up():
    """A revised entry (its answer replaced) is an exchange that happened: the question stays the topic (before, a revised entry with nothing heard dropped every question of that text)."""
    state = {'history': [{'question': 'Что такое инерция?', 'answer': 'a', 'at': 100.0, 'status': 'revised', 'spoken': 0},
                         {'question': 'Что такое инерция?', 'answer': 'b', 'at': 110.0, 'status': 'complete', 'spoken': 1}]}
    assert asked_of(state) == ['Что такое инерция?', 'Что такое инерция?']


def test_a_late_repeat_is_read_in_the_window_of_this_call_by_the_one_reader_of_what_was_told():
    """memory / heard-back -> followup-base: ``followup.told_back`` (the classifier's ``_heard_back`` is gone) reads the answers of ``call_history`` (the one window the engine keeps), and the answer in play:
    the repeat of an answer of THIS call is no new topic; the same words of a call before it are (A4: yesterday's answers are not «already said», as in the controller's ``_said_already``)."""
    from echo_sync.classifier import analyze
    from echo_sync.followup import told_back
    entry = {'question': 'Что такое инерция?', 'answer': 'Инерция это свойство тел сохранять скорость', 'chunks': ['Инерция это свойство тел', 'сохранять скорость'], 'at': 100.0, 'status': 'complete'}
    state = {'history': [entry], 'chunks': ['Инерция это свойство тел', 'сохранять скорость'], 'completed': True}
    assert told_back('свойство тел сохранять', {'history': [entry]}) is False       # a stretch over two portions is no stretch of one
    assert told_back('свойство тел', {'history': [entry]}) is True
    assert told_back('свойство тел', {'history': [entry], 'call_began': 200.0}) is False      # an earlier call's answer
    assert told_back('свойство тел', {'history': [entry], 'call_began': 50.0}) is True
    assert told_back('', state) is False and told_back('свойство', None) is False
    assert analyze('Ну, свойство тел', {**state, 'call_began': 50.0}, [], None).kind != 'question'
