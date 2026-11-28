"""WAVE 2 / Task B, DEF-STATE-05 (P1): a word from the listener between the question and the first event of its answer must not
swallow the answer.

An assistant turn is owned by the latest user turn at its first event, so that an answer to an OLD question is never spoken as the answer
to a new one. But a user turn that the controller took and did NOT take for a question («повтори», «ну», a cough, another voice) leaves the
question where it was, and the answer that begins after it is the answer to that question: it used to be dropped for good (silence).
What stays: an answer after «стоп» is never spoken; a user turn that is still being spoken is not a verdict; a reply of the model to a
listener's repeat in the MIDDLE of an answer is chatter and stays muted (tests/test_task2_stuck_endless_complete.py).
"""
import helpers_s6_ack as H
from echo_sync.controlled_media import ControlledMedia

ANSWER = 'Свойство тела сопротивляться изменению своего движения. Это называется инерцией. Чем больше масса, тем сильнее инерция.'
FIRST_CUE = 'Свойство тела сопротивляться изменению своего движения.'   # F1: the first meaning portion (WAVE 2 / L2 had «Свойство тела»)
QUESTION = 'Что такое инерция'


def controller(tmp_path):
    c = ControlledMedia(tmp_path / 'owner.sqlite3', session_id=H.SESSION, clock=H.FakeClock(), **H.HOST_KWARGS)
    c.speech_started()
    c.provider(H.created('u1', 'user', 'Что'))
    asked = c.provider(H.done('u1', 'user', QUESTION))
    assert [a['type'] for a in asked] == ['cancel', 'route'], asked
    return c


def answer(c, tid='a1'):
    c.provider(H.created(tid, 'assistant', 'Свойство'))
    return [a['text'] for a in c.provider(H.done(tid, 'assistant', ANSWER)) if a['type'] == 'speak']


def test_a_repeat_request_between_the_question_and_its_answer_does_not_swallow_the_answer(tmp_path):
    c = controller(tmp_path)
    c.provider(H.done('u2', 'user', 'повтори'))
    assert answer(c) == [FIRST_CUE], 'the answer to the question was never spoken'


def test_noise_between_the_question_and_its_answer_does_not_swallow_the_answer(tmp_path):
    for n, noise in enumerate(('ну', 'Продолжение следует', 'ага')):
        c = controller(tmp_path / f'noise{n}')
        c.provider(H.created('u2', 'user', noise.split()[0]))
        c.provider(H.done('u2', 'user', noise))
        assert answer(c), f'{noise!r} swallowed the answer'


def test_two_asides_in_a_row_do_not_swallow_it_either(tmp_path):
    c = controller(tmp_path)
    c.provider(H.done('u2', 'user', 'ну'))
    c.provider(H.done('u3', 'user', 'повтори'))
    assert answer(c)


def test_an_answer_after_stop_is_never_spoken(tmp_path):
    c = controller(tmp_path)
    c.provider(H.done('u2', 'user', 'стоп'))
    assert answer(c) == [], 'the listener said «стоп»: a late answer must stay silent'


def test_a_user_turn_that_is_still_being_spoken_is_not_a_verdict(tmp_path):
    c = controller(tmp_path)
    c.provider(H.created('u2', 'user', 'Свойство'))                # begun, not finished, not taken yet
    assert answer(c) == [], 'whose answer this is cannot be told while the listener is still speaking: unchanged'


def test_a_new_question_in_between_still_takes_the_answer_for_itself(tmp_path):
    c = controller(tmp_path)
    again = c.provider(H.done('u2', 'user', 'Что такое масса'))
    assert [a['type'] for a in again][:1] == ['cancel'], 'a second question replaces the first'
    c.provider(H.created('a1', 'assistant', 'Свойство'))
    c.provider(H.done('a1', 'assistant', ANSWER))
    assert c.question_id == 'u2' and c.owners['a1'] == 'u2', 'owned by the newest question, as before'


def test_the_chatter_that_answers_a_repeat_in_the_middle_of_an_answer_is_still_muted(tmp_path):
    c = controller(tmp_path)
    assert answer(c)
    first = c.engine.current(c.state())
    c.provider(H.done('ack-1', 'user', first))
    c.provider(H.created('chatter', 'assistant', 'Хорошо'))
    assert c.provider(H.done('chatter', 'assistant', 'Хорошо, продолжаем.')) == []


def test_noise_after_the_clouds_filler_does_not_swallow_the_answer_that_comes_after_it(tmp_path):
    """Candidate 12, W3 w3_07 step 1 (order of the live run): the cloud began its filler, the sources reached it, the filler ended, it heard noise
    («russian coat») and answered in a turn of its own. The filler published nothing, so the answer had not begun: that turn is the question's, it
    used to be owned by the noise and thrown away (30 s of silence and «Нет ответа»)."""
    from test_e3c_lookup import POSITIVES, VERIFY, lookup_question
    c = lookup_question(tmp_path, VERIFY)
    question = c.question_id
    c.provider({'type': 'delegation.created', 'item': {'id': 'd1', 'type': 'delegation', 'target': 'client', 'user_bidi_turn_id': question}})
    c.provider(H.created('a0', 'assistant', 'Понял'))
    assert [a['type'] for a in c.grounding(c.epoch, [{'url': 'https://example.org/x', 'text': POSITIVES['subject']}])] == ['context']
    assert c.delivery_sent(c.epoch, 'd1')
    c.provider(H.done('a0', 'assistant', 'Понял, сейчас уточню кратко по теме.'))
    assert c.source_segment_id == 'a0' and not c.published, 'precondition: the filler is the segment and published nothing'
    c.provider(H.created('u2', 'user', 'russian'))
    c.provider(H.done('u2', 'user', 'russian coat'))
    c.provider(H.created('a1', 'assistant', 'Гидравлический'))
    assert c.owners['a1'] == question
    cues = c.provider(H.done('a1', 'assistant', POSITIVES['subject']))
    assert [a['type'] for a in cues] == ['speak'], cues
