"""WAVE 2 / Task E, ruling 4 (fix round on d4c15e9): the missing-answer phrase is exempt from the 10 s rate limit of spoken diagnostics.

The review (ratelimit.py): the watchdog gives a question up and the listener hears «Нет ответа. Повторите вопрос.»; the phrase itself tells them
to ask again, and they do so at once, over it; the cloud stays silent again. The second report falls within DIAGNOSTIC_MIN_INTERVAL_S of the
first, the wire sent the error frame only (``diagnostic=rate_limited``) and the listener, who had just been told to repeat the question, heard
nothing. The phrase is already limited to once per question (the controller gives the question up with a new epoch), so it needs no second limit.
Every other diagnostic keeps the 10 s limit. Time is virtual (the transport's own clock): nothing here sleeps.
"""
import helpers_s6_fault as F
from echo_sync.controlled_media import ANSWER_WAIT_SECONDS
from echo_sync.timer_policy import DIAGNOSTIC_MIN_INTERVAL_S
from helpers_spoken_diagnostics import ANSWER, LOOKUP_EMPTY, phrases_heard, responses, run_wire


async def silent_then_reasked_over_the_phrase(rig, reask_final_after=1.5):
    """A silent cloud; the first phrase; the listener asks again over it (cutting it); the cloud stays silent. Returns the phrase's start."""
    await rig.ask(F.DIRECT_QUESTION)
    await rig.advance(ANSWER_WAIT_SECONDS + 0.5)
    first = responses(rig.frames)
    F.precondition([r['text'] for r in first] == [ANSWER], 'the first phrase was spoken: ' + str(rig.timeline()))
    started = first[0]['start']
    await rig.advance(max(0.0, started + 0.6 - rig.now()))
    await rig.feed(F.created('u2', 'user', 'Что'))                       # speaks over the phrase: the wire cuts it
    await rig.advance(reask_final_after - 0.6)
    await rig.feed(F.done('u2', 'user', F.DIRECT_QUESTION))
    return started


def test_the_second_missing_answer_phrase_is_spoken_within_ten_seconds_of_the_first(tmp_path, monkeypatch):
    async def body(rig):
        started = await silent_then_reasked_over_the_phrase(rig)
        await rig.advance(ANSWER_WAIT_SECONDS + 6)
        heard = responses(rig.frames)
        assert [r['text'] for r in heard] == [ANSWER, ANSWER], 'the listener told to ask again heard nothing the second time: ' + str(rig.timeline())
        assert heard[1]['start'] - started < DIAGNOSTIC_MIN_INTERVAL_S, 'precondition: the second report is inside the 10 s of the first'
        assert heard[1]['status'] == 'completed'
        assert rig.errors() == ['controlled_answer_timeout'] * 2
    run_wire(tmp_path, monkeypatch, body)


def test_it_is_still_once_per_question(tmp_path, monkeypatch):
    async def body(rig):
        await silent_then_reasked_over_the_phrase(rig)
        await rig.advance(ANSWER_WAIT_SECONDS + 6)
        assert phrases_heard(rig.frames) == [ANSWER, ANSWER]
        quiet_from = rig.now()
        await rig.advance(120)
        assert not [f for f in rig.frames if f.type == 'response.created' and f.t >= quiet_from], 'the phrase repeats itself'
        assert rig.errors() == ['controlled_answer_timeout'] * 2, 'one report per question'
    run_wire(tmp_path, monkeypatch, body)


def test_every_other_diagnostic_keeps_the_ten_second_limit(tmp_path, monkeypatch):
    """A lookup that fails twice in a row (two questions, 3 s apart) is announced once: the phrase of the second would be the first's echo."""
    async def body(rig):
        # c8: a lookup with no source is now answered from memory; the immediate report is the path of a controller that cannot do that.
        rig.controller.without_source = lambda epoch, why: None
        await rig.ask(F.LOOKUP_QUESTION, 'u1')
        await rig.advance(3.0)
        await rig.ask(F.LOOKUP_QUESTION + ' Ещё раз.', 'u2')
        await rig.advance(14.0)
        assert rig.errors() == ['controlled_sources_unavailable'] * 2, rig.timeline()
        assert phrases_heard(rig.frames) == [LOOKUP_EMPTY], 'the second lookup failure was spoken inside the 10 s as well'
    run_wire(tmp_path, monkeypatch, body, lookup=['raise'])
