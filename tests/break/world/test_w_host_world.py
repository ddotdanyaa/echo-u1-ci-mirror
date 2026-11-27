"""U237 breakD, class «the call lives long and the world around it breaks» (owner: «молчит», «ответ пришёл поздно», «озвучил старое»): a half-hour of silence, the helper pipe dying, the phone's line dropping in the middle of
an answer, the owner breaking in while the cloud still streams the old answer. The REAL host (controlled_host.serve, ControlledMedia, NativeMediaSocket) with only its boundaries faked
(tests/helpers_always_answer.py, tests/helpers_s6_fault.py). Existing break tests of answer_route take the roads; these take the call around them."""
import logging

import helpers_always_answer as AA
import helpers_s6_fault as F
from bk_common import ALIVE_BOUND_S, BStand, Heard, Q_INERTIA, Q_PHOTO, SYNTH_TICK_S, TOPIC, local_call, ok, run_stand
from test_s6_fault_injection import run_wire

Q, A = F.DIRECT_QUESTION, F.DIRECT_ANSWER
Q2, A2 = F.OTHER_DIRECT_QUESTION, F.OTHER_DIRECT_ANSWER
MARK, MARK2 = 'свойство тела', 'образования органических'


def test_w19_half_an_hour_of_silence_before_the_first_question_says_nothing_and_the_question_is_answered(tmp_path):
    stand = BStand({'codex': ok()})

    async def body(host, stand):
        updated, ready = await AA.open_local(host)
        t0 = host.now()
        await host.advance(1800.0)
        quiet = Heard(host, t0)
        q = await stand.ask(host, Q_INERTIA, cloud=False, uid='u1')
        await host.advance(14.0)
        return ready, quiet, Heard(host, q)
    ready, quiet, saw = run_stand(tmp_path, stand, body, **local_call())
    assert ready, 'the call did not become ready'
    assert not quiet.items, f'the app spoke by itself in half an hour of silence: {quiet.text!r}'
    first = saw.first_sound()
    assert TOPIC[Q_INERTIA] in saw.text and first is not None and first <= ALIVE_BOUND_S + SYNTH_TICK_S, f'after the long silence: {saw.text!r} (first sound {first})'


def test_w20_the_same_question_forty_minutes_after_its_answer_is_answered_again_and_the_quiet_between_is_quiet(tmp_path):
    stand = BStand({'codex': ok()})

    async def body(host, stand):
        q1 = await stand.ask(host, Q_INERTIA, uid='u1', lag=0.0)
        await host.advance(20.0)
        mid = host.now()
        await host.advance(2400.0)
        quiet = Heard(host, mid)
        q2 = await stand.ask(host, Q_INERTIA, uid='u2', lag=0.0)
        await host.advance(16.0)
        return Heard(host, q1), quiet, Heard(host, q2)
    first, quiet, again = run_stand(tmp_path, stand, body)
    assert TOPIC[Q_INERTIA] in first.text, f'precondition: the first answer {first.text!r}'
    assert not quiet.items, f'something was said in forty minutes of quiet: {quiet.text!r}'
    assert TOPIC[Q_INERTIA] in again.text, f'the same question after forty minutes got no answer: {again.text!r}'


def test_w21_the_helper_pipe_dies_in_the_middle_of_the_call_the_next_question_is_not_met_with_silence(tmp_path):
    """The cloud's link goes with the VPN: the pipe to the helper hits EOF. Either the call ends cleanly (the phone reconnects) or the owner still gets an answer or a phrase in time."""
    stand = BStand({'codex': ok()})

    async def body(host, stand):
        await stand.ask(host, Q_INERTIA, uid='u1', lag=0.0)
        await host.advance(20.0)
        host.bridge.inbox.put_nowait(None)               # EOF of the helper pipe
        await host.advance(1.0)
        q = await stand.ask(host, Q_PHOTO, cloud=False, uid='u2')
        await host.advance(ALIVE_BOUND_S + 2.0)
        return q, Heard(host, q), host.finished, host.outcome
    q, saw, finished, outcome = run_stand(tmp_path, stand, body)
    assert not isinstance(outcome, BaseException), f'the host crashed on the death of the helper pipe: {outcome!r}'
    first = saw.first_sound()
    assert finished or (first is not None and first <= ALIVE_BOUND_S + SYNTH_TICK_S), f'the pipe died, the call stayed open and silent: {saw.text!r}'


def test_w22_the_phone_line_drops_in_the_middle_of_the_answer_the_host_ends_cleanly_without_errors(tmp_path):
    stand = BStand({'codex': ok()})

    async def body(host, stand):
        await stand.ask(host, Q_INERTIA, uid='u1', lag=0.0)
        await host.advance(0.5)
        host.ws.inbox.put_nowait(F.WSClosed('the tunnel dropped'))
        await host.advance(10.0)
        return host.finished, host.outcome, host.logger.text(logging.ERROR)
    finished, outcome, errors = run_stand(tmp_path, stand, body)
    assert finished, 'the host kept running with a dead phone line'
    assert outcome == 'returned', f'the host ended with an exception: {outcome!r}'
    assert not errors, f'errors were logged on an ordinary drop of the line: {errors}'


def test_w23_the_owner_breaks_in_while_the_cloud_still_streams_the_old_answer_the_old_rest_is_never_voiced(tmp_path, monkeypatch):
    async def body(rig):
        await rig.ask(Q)
        await rig.feed(F.created('a1', 'assistant', 'Инерция'))
        await rig.feed(F.delta('a1', ' — это свойство', 1))
        await rig.advance(0.05)
        t_q2 = rig.now()
        await rig.ask(Q2)                                # the owner asks the next question
        await rig.feed(F.delta('a1', ' тела сохранять своё состояние покоя', 2))
        await rig.feed(F.done('a1', 'assistant', A))     # the cloud finishes the OLD answer after the new question
        await rig.advance(1.0)
        await rig.answer(A2)
        await rig.advance(10.0)
        said = ' '.join(t for t in rig.spoken(t_q2) if t.strip())
        assert MARK2 in said, f'the new question was not answered: {said!r}'
        assert MARK not in said, f'the rest of the old answer was voiced after the new question: {said!r}'
    run_wire(tmp_path, monkeypatch, body)

import pytest as _pt_no_lead
pytestmark = _pt_no_lead.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)
