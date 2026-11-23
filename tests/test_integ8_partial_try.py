"""Integration of W1F-B with the S6 invariants (S4, found by test_random_event_sequences_keep_every_invariant on integ8): after the first
cue is out, a bare «Нет,» that is the start of the waiting portion itself («Нет, кит не рыба,») is the listener beginning to repeat it — a
try that moves nothing — never a self-correction opener that re-asks the question (cursor 1/0 -> 2/0 before the fix)."""
from helpers_w1f import Wire

ANSWER = 'Нет, кит не рыба, а млекопитающее, которое дышит лёгкими. Детёнышей он выкармливает молоком.'


def test_a_partial_repeat_of_the_first_cue_right_after_it_is_a_try_not_a_correction(tmp_path):
    w = Wire(tmp_path)
    w.user('u1', 'Правда ли что кит рыба?', 0.2, 0.6)
    w.assistant('a1', ANSWER, 0.6, 0.62)
    w.until(0.75)
    before = w.c.state()
    assert before and before.get('chunks'), before
    w.user('u3', 'Нет,', 0.78, 1.3)
    w.until(6.0)
    after = w.c.state()
    assert after['revision'] == before['revision'], (before['revision'], after['revision'])
    assert after['chunk_index'] == before['chunk_index'], (before['chunk_index'], after['chunk_index'])
    assert w.c.question_id == 'u1', w.c.question_id


def test_a_bare_no_before_the_first_cue_still_opens_a_correction(tmp_path):
    """The W1F-B rule before any cue is unchanged: «Нет» right after the question waits for the correction to come."""
    w = Wire(tmp_path)
    w.user('u1', 'Сколько ног у паука?', 0.2, 0.6)
    w.user('u2', 'Нет', 0.7, 1.0)
    w.user('u3', 'подождите, я хотел спросить про насекомое', 1.3, 3.0)
    w.assistant('a3', 'У насекомых шесть ног.', 3.05, 3.4)
    w.until(9.0)
    played = ' '.join(text for _, text in w.played)
    assert 'шест' in played.lower() or 'шест' in str(w.plan()).lower(), (w.played, w.plan())
