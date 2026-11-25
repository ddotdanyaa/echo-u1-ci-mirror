"""U237 break tests, family «answer»: the ORDER of answers. What the owner did again and again: asked a second question before the first was answered, asked two at once, let the model answer the old
question after the new one, repeated a question that was not answered yet. The REAL host (controlled_host.serve, ControlledMedia) with only its boundaries faked (tests/helpers_always_answer.py).
A red test here is a found defect: it is never to be weakened."""
import helpers_always_answer as H
from bk_common import (ALIVE_BOUND_S, MARKS, Heard, BStand, M, Q_INERTIA, Q_PHOTO, SYNTH_TICK_S, TOPIC, fail, hang, late, local_call, ok, run_stand)


def test_b01_the_late_road_of_the_old_question_is_never_heard_after_the_new_question(tmp_path):
    """Class «the old answer after the new question» (K8). Codex answers question 1 at 6 s; question 2 comes at 1.3 s and Codex answers it at once. The late text of question 1 must be let go."""
    stand = BStand({'codex': late(6.0)})

    async def body(host, stand):
        q1 = await stand.ask(host, Q_INERTIA, uid='u1', lag=0.0)
        await host.advance(1.0)
        stand.plan['codex'] = ok()
        q2 = await stand.ask(host, Q_PHOTO, uid='u2', lag=0.0)
        await host.advance(16.0)
        return Heard(host, q1), q2
    saw, q2 = run_stand(tmp_path, stand, body)
    assert TOPIC[Q_INERTIA] not in saw.text, f'the answer of the OLD question was heard: {saw.text!r}'
    assert TOPIC[Q_PHOTO] in saw.text, f'the NEW question was not answered: {saw.text!r}'


def test_b02_two_questions_in_one_tick_of_the_ear_only_the_second_is_answered_once(tmp_path):
    """Class «two questions in a row» (K13). The ear hands both in one poll (a stumble: the owner starts again at once). One answer, of the second."""
    stand = BStand({'codex': ok()})

    async def body(host, stand):
        t0 = host.now()
        await H.open_local(host)
        await host.advance(1.0)
        q1 = await stand.ask(host, Q_INERTIA, cloud=False, uid='u1')
        await stand.ask(host, Q_PHOTO, cloud=False, uid='u2')          # no await between the two: the same poll
        await host.advance(14.0)
        return Heard(host, q1)
    saw = run_stand(tmp_path, stand, body, **local_call())
    assert TOPIC[Q_PHOTO] in saw.text, f'the second question was not answered: {saw.text!r}'
    assert TOPIC[Q_INERTIA] not in saw.text, f'the answer of the first (abandoned) question was heard: {saw.text!r}'
    assert saw.text.count(MARKS['codex']) == 1, f'the answer was said {saw.text.count(MARKS["codex"])} times: {saw.text!r}'


def test_b03_the_second_question_a_moment_after_the_first_is_not_answered_with_the_first(tmp_path):
    """Class «the old answer after the new question». Question 2 follows question 1 by 0.3 s with the cloud live and silent; Codex needs 0.8 s for each, so the text of question 1 is due 0.5 s AFTER question 2. No response that begins after question 2 may be the answer of question 1."""
    stand = BStand({'codex': late(0.8)})

    async def body(host, stand):
        q1 = await stand.ask(host, Q_INERTIA, uid='u1', lag=0.0)
        q2 = host.now()
        await stand.ask(host, Q_PHOTO, uid='u2', lag=0.0)
        await host.advance(14.0)
        return Heard(host, q1), q2
    saw, q2 = run_stand(tmp_path, stand, body)
    late_items = [i for i in saw.answers + saw.other if i['start'] >= q2 and TOPIC[Q_INERTIA] in i['text']]
    assert not late_items, f'a response of the old question began after the new question: {[i["text"] for i in late_items]}'
    assert TOPIC[Q_PHOTO] in saw.text, f'the new question was not answered: {saw.text!r}'


def test_b04_the_cloud_answers_the_old_question_after_the_new_one_it_is_not_spoken_as_the_new_answer(tmp_path):
    """Class «the answer of an old question after the new» (K8, K13, U94.2). Every road is dead; the model of the cloud answers question 1 after question 2 was asked. Its text is of another question:
    the listener must not hear it, and must not be left in silence about question 2 either."""
    stand = BStand({'codex': fail('http_429')})

    async def body(host, stand):
        await stand.ask(host, Q_INERTIA, uid='u1', lag=0.0)
        await host.advance(0.7)
        q2 = await stand.ask(host, Q_PHOTO, uid='u2', lag=0.0)
        await host.advance(0.5)
        await host.answer(H.cloud_answer(Q_INERTIA)[0], tid='a1')
        await host.advance(18.0)
        return Heard(host, q2), q2
    saw, q2 = run_stand(tmp_path, stand, body)
    assert H.cloud_answer(Q_INERTIA)[1] not in saw.text.lower(), f'the answer of question 1 was spoken after question 2: {saw.text!r}'
    first = saw.first_sound()
    assert first is not None and first <= ALIVE_BOUND_S + SYNTH_TICK_S, f'silence about question 2 (first sound {first}): {saw.text!r}'


def test_b05_the_same_question_three_times_before_the_answer_is_answered_once(tmp_path):
    """Class "the answer starts anew" (K13). The first road hangs, the second answers at 0.8 s; the owner repeats the question twice while he waits. One answer, not three."""
    stand = BStand({'codex': hang(), 'groq1': late(0.8)})

    async def body(host, stand):
        q1 = await stand.ask(host, Q_INERTIA, uid='u1', lag=0.0)
        await host.advance(0.3)
        await stand.ask(host, Q_INERTIA, uid='u2', lag=0.0)
        await host.advance(0.3)
        await stand.ask(host, Q_INERTIA, uid='u3', lag=0.0)
        await host.advance(16.0)
        return Heard(host, q1)
    saw = run_stand(tmp_path, stand, body)
    said = saw.text.count(MARKS['groq1'])
    assert said == 1, f'the answer was heard {said} times (expected once): {saw.text!r}'


def test_b06_the_late_road_after_the_phrase_of_the_system_says_nothing(tmp_path):
    """Class «the late answer after the refusal» (K8, F20). Codex says its text at 15 s, the other roads are dead: the question is let go at 12 s and the listener heard the phrase. A text that comes after
    the phrase is never dictated."""
    stand = BStand({'codex': late(15.0)})

    async def body(host, stand):
        q1 = await stand.ask(host, Q_INERTIA, uid='u1', lag=0.2)
        await host.advance(26.0)
        return Heard(host, q1)
    saw = run_stand(tmp_path, stand, body)
    first = saw.first_sound(saw.service)
    assert first is not None and first <= ALIVE_BOUND_S + 0.5, f'no phrase of the system in time (at {first}): {saw.text!r}'
    assert not saw.answers, f'an answer that came after the question was let go was dictated: {[i["text"] for i in saw.answers]}'


def test_b07_a_blip_of_the_network_that_is_over_in_a_second_does_not_hold_the_next_question(tmp_path):
    """Class «the road rests longer than the failure» (D cells, only 429 there). Every road fails with ConnectError, the network is back after 1 s, the next question comes 3 s later (Codex rests 30 s, the reserve
    60 s: a rest is an order, never a ban): it is answered at once, with no phrase."""
    stand = BStand({'codex': fail('ConnectError'), 'groq1': fail('ConnectError'), 'groq2': fail('ConnectError'), 'gemini': fail('ConnectError')}, default=fail('ConnectError'))

    async def body(host, stand):
        q1 = await stand.ask(host, Q_INERTIA, uid='u1', lag=0.2)

        def alive():
            stand.plan.clear()
            stand.default = ok()
        host.loop.call_at(q1 + 1.0, alive)
        await host.advance(3.0)
        q2 = await stand.ask(host, Q_PHOTO, uid='u2', lag=0.2)
        await host.advance(10.0)
        return Heard(host, q2), q2
    saw, q2 = run_stand(tmp_path, stand, body)
    assert TOPIC[Q_PHOTO] in saw.text, f'question 2 was not answered after the network came back: {saw.text!r}'
    first = saw.first_sound(saw.answers)
    assert first is not None and first <= 4.0, f'the answer after the blip came {first} s after the question'

import pytest as _pt_no_lead
pytestmark = _pt_no_lead.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)
