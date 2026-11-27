"""WAVE 2 / Task D, part 1 (DEF-FAULT-03): the cloud took the question and never gave a usable answer.

Required (owner directives 2026-11-01, wave2/task-d-brief.md): after a bounded wait the listener hears a short phrase
(«Нет ответа. Повторите вопрос.») and the session accepts the next question; a late answer for the abandoned question is
never spoken afterwards; a diagnostic is never counted as an answer (no cue, no cursor move, nothing repeats it).

Where the wait comes from (``controlled_media.ANSWER_WAIT_SECONDS``, 8 s). 05_WORK/scripts/LATENCY_BASELINE.md, model route:
final of the question -> assistant turn 56 ms (p95 82), -> first useful phrase 805 ms (p95 3425, N=9), synthesis 129 ms (p95 228),
publication + first PCM 42 ms (p95 49) -> the slowest healthy first PCM is about 3.8 s after the final (end of the question to
first PCM: median 2903 ms, p95 4770 ms with the 1.1-1.9 s wait for the final in it). The wait is counted to the first CUE, not to
the first text delta (1.5 s): a delta that never becomes a cue (a service phrase, the question read back, an empty turn) is exactly
the silence this defect is about, and a limit near the first delta would also announce healthy answers whose first useful phrase
is still being formed. 8 s is 2.1 times the slowest healthy first cue, and the same scale as the 8 s lookup budget of the wire.
A question that needs the public lookup is counted from the moment its sources reached the model (the lookup has its own budget
and its own phrase); when that never happens, from the final plus the lookup budget.

WAVE 2 / Task E (fix round on d4c15e9), ruling 1: the count is PROGRESS-based (any event of an assistant turn owned by the question
restarts it) and the lookup route has a budget of its own, ``LOOKUP_ANSWER_WAIT_SECONDS`` (20 s), counted from the REAL delivery.
tests/test_answer_progress_watchdog.py holds that contract (real lookup timelines included); the two tests below that used to pin
the 8 s for a lookup question now pin the lookup budget.

Time is injected or virtual: nothing here sleeps.
"""
import logging

import pytest

import helpers_s6_fault as F
from helpers_spoken_diagnostics import (ANSWER, EVERY_PHRASE, FIRST_CUE_BOUND, LOOKUP_EMPTY, OTHER, phrases_heard, responses,
                                        run_host, run_wire, wav_pcm)
from echo_sync import controlled_media, native_media_socket
from echo_sync.controlled_media import ANSWER_WAIT_SECONDS, LOOKUP_ANSWER_WAIT_SECONDS, LOOKUP_WAIT_SECONDS, ControlledMedia

# LATENCY_BASELINE.md, model route, per-stage p95 (ms): final -> turn.created 82, turn.created -> synthesis start 3425,
# synthesis 228, publication 34 + first PCM 15. Their sum is the slowest healthy first cue after the final.
SLOWEST_HEALTHY_FIRST_CUE_S = (82 + 3425 + 228 + 34 + 15) / 1000


def test_the_wait_is_a_named_constant_chosen_from_the_latency_data():
    assert SLOWEST_HEALTHY_FIRST_CUE_S == pytest.approx(3.784)
    assert ANSWER_WAIT_SECONDS == 8.0
    assert 2 * SLOWEST_HEALTHY_FIRST_CUE_S <= ANSWER_WAIT_SECONDS, 'no margin over the slowest healthy first cue: healthy answers would be announced'
    assert ANSWER_WAIT_SECONDS <= 10, 'the listener would wait in silence for longer than the longest usable bound'


def test_a_lookup_question_gets_the_wire_lookup_budget_on_top():
    assert LOOKUP_WAIT_SECONDS == native_media_socket.LOOKUP_TIMEOUT_S


# ======================================================================================================
# 1. the controller on an injected clock
# ======================================================================================================

class Clock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now


class Call:
    """The production ControlledMedia (the keywords controlled_host.serve passes) on an injected clock."""

    def __init__(self, tmp_path, **keywords):
        self.clock = Clock()
        self.controller = ControlledMedia(tmp_path / 'wd.sqlite3', session_id='wd', clock=self.clock,
                                          **{**F.HOST_KWARGS, **keywords})

    def ask(self, text=F.DIRECT_QUESTION, tid='u1', *, said_for=0.0):
        """A question whose speech lasts ``said_for`` seconds and is final at the end of it."""
        self.controller.provider(F.created(tid, 'user', text.split(' ', 1)[0]))
        self.clock.now += said_for
        return self.controller.provider(F.done(tid, 'user', text))

    def cloud(self, text, tid='a1'):
        out = self.controller.provider(F.created(tid, 'assistant', text[:5]))
        out += self.controller.provider(F.done(tid, 'assistant', text))
        return out

    def run(self, seconds, step=0.1):
        """Tick for ``seconds`` (every 0.1 s like the host ticker); everything the controller returned, as (elapsed, action)."""
        out, start = [], self.clock.now
        while self.clock.now - start < seconds - 1e-9:
            self.clock.now += step
            out += [(round(self.clock.now - start, 3), a) for a in self.controller.tick(now=self.clock())]
        return out


def reports(timed):
    return [(t, a) for t, a in timed if a['type'] == 'unanswered']


def test_a_question_nobody_answers_is_reported_once_when_the_wait_is_over(tmp_path):
    call = Call(tmp_path)
    call.ask()
    epoch = call.controller.epoch
    early = call.run(ANSWER_WAIT_SECONDS - 0.5)
    assert reports(early) == [], 'reported before the wait was over'
    late = call.run(40)
    found = reports(late)
    assert len(found) == 1, f'expected exactly one report: {found}'
    elapsed, action = found[0]
    assert 0.3 <= elapsed <= 1.0, f'reported {elapsed} s after the end of the wait'
    assert action == {'type': 'unanswered', 'epoch': epoch, 'reason': 'no_assistant_turn'}


def test_the_wait_counts_from_the_final_of_the_question_not_from_its_first_word(tmp_path):
    call = Call(tmp_path)
    call.ask(said_for=4.0)                                         # the listener took 4 s to say it
    found = reports(call.run(ANSWER_WAIT_SECONDS - 0.5))
    assert found == [], 'the seconds the question took to say are not the cloud\'s silence'
    assert len(reports(call.run(2))) == 1


def test_a_cue_ends_the_wait_for_good(tmp_path):
    call = Call(tmp_path)
    call.ask()
    call.run(ANSWER_WAIT_SECONDS - 1.5)
    out = call.cloud(F.DIRECT_ANSWER)
    assert any(a['type'] == 'speak' for a in out), 'precondition: the answer produced a cue'
    assert reports(call.run(120)) == [], 'a question that was answered is never reported'


@pytest.mark.parametrize('text,reason', [('Сейчас уточню.', 'no_usable_text'), ('', 'no_usable_text'),
                                         ('Инерция — это инерция.', 'no_usable_text')],
                         ids=['service_phrase', 'empty_turn', 'question_read_back'])
def test_text_that_gives_no_cue_is_reported_with_its_own_reason(tmp_path, text, reason):
    call = Call(tmp_path)
    call.ask()
    out = call.cloud(text)
    assert not [a for a in out if a['type'] == 'speak'], 'precondition: this text is no cue'
    found = reports(call.run(ANSWER_WAIT_SECONDS + 1))
    assert [a['reason'] for _, a in found] == [reason]


def test_the_listener_speaking_holds_the_report_back_until_they_stop(tmp_path):
    call = Call(tmp_path)
    call.ask()
    call.run(ANSWER_WAIT_SECONDS - 1)
    c = call.controller
    c.speech_started()
    c.provider(F.created('h1', 'user', 'Я'))
    held = []
    for n in range(1, 7):                                          # their transcript keeps growing for 6 s: past the deadline
        c.provider(F.delta('h1', ' ещё', n))
        held += call.run(1.0)
    assert reports(held) == [], 'the prompter announced a missing answer over the listener'
    found = reports(call.run(4))
    assert len(found) == 1 and found[0][0] <= 3.5, 'and it has to come as soon as they are quiet (hearing runs out after 2.5 s)'


def test_a_new_question_restarts_the_wait(tmp_path):
    call = Call(tmp_path)
    call.ask(F.DIRECT_QUESTION, 'u1')
    call.run(5)
    call.ask(F.OTHER_DIRECT_QUESTION, 'u2')
    second_epoch = call.controller.epoch
    assert reports(call.run(ANSWER_WAIT_SECONDS - 0.5)) == [], 'the first question\'s deadline passed, but it is not the question any more'
    found = reports(call.run(2))
    assert [a['epoch'] for _, a in found] == [second_epoch]


def test_stop_ends_the_wait(tmp_path):
    call = Call(tmp_path)
    call.ask()
    call.run(2)
    call.controller.provider(F.done('s1', 'user', 'Стоп'))
    assert reports(call.run(60)) == []


def test_after_the_report_a_late_answer_for_that_question_is_never_spoken(tmp_path):
    call = Call(tmp_path)
    call.ask()
    assert len(reports(call.run(ANSWER_WAIT_SECONDS + 1))) == 1
    out = call.cloud(F.DIRECT_ANSWER)
    assert [a for a in out if a['type'] == 'speak'] == [], 'the abandoned question\'s late answer was spoken'
    assert [a for _, a in call.run(60) if a['type'] == 'speak'] == []
    assert call.controller.state() is None, 'nothing of it reached the stored session'


def test_after_the_report_the_next_question_is_answered_normally(tmp_path):
    call = Call(tmp_path)
    call.ask()
    call.run(ANSWER_WAIT_SECONDS + 1)
    call.ask(F.OTHER_DIRECT_QUESTION, 'u2')
    out = call.cloud(F.OTHER_DIRECT_ANSWER, 'a2')
    cues = [a for a in out if a['type'] == 'speak']
    assert len(cues) == 1 and cues[0]['text'].lower() in F.OTHER_DIRECT_ANSWER.lower()
    assert reports(call.run(60)) == []


def test_a_question_that_needs_the_lookup_is_counted_from_the_delivery_of_its_sources(tmp_path):
    call = Call(tmp_path)
    call.ask(F.LOOKUP_QUESTION)
    assert call.controller.direct_content is False, 'precondition: this question needs the lookup'
    call.run(2)
    epoch = call.controller.epoch
    call.controller.grounding(epoch, F.sources_for(F.LOOKUP_QUESTION))
    assert call.controller.delivery_sent(epoch, None), 'precondition: the context reached the model'
    assert reports(call.run(LOOKUP_ANSWER_WAIT_SECONDS - 0.5)) == [], 'counted from the final instead of from the delivery'
    assert len(reports(call.run(1.5))) == 1


def test_a_lookup_question_whose_sources_never_arrive_is_still_reported_after_the_lookup_budget_and_the_wait(tmp_path):
    call = Call(tmp_path)
    call.ask(F.LOOKUP_QUESTION)
    assert reports(call.run(LOOKUP_WAIT_SECONDS + ANSWER_WAIT_SECONDS - 0.5)) == []
    assert len(reports(call.run(1.5))) == 1, 'a question stuck before its context was delivered stays silent for ever'


def test_a_question_the_listener_was_already_told_about_is_not_reported_again(tmp_path):
    call = Call(tmp_path)
    call.ask(F.LOOKUP_QUESTION)
    call.controller.answer_diagnosed(call.controller.epoch)       # the wire spoke «Не нашёл. Повторите вопрос.»
    assert reports(call.run(LOOKUP_WAIT_SECONDS + ANSWER_WAIT_SECONDS + 5)) == []


def test_a_diagnosed_epoch_does_not_silence_the_next_question(tmp_path):
    call = Call(tmp_path)
    call.ask(F.LOOKUP_QUESTION)
    call.controller.answer_diagnosed(call.controller.epoch)
    call.ask(F.DIRECT_QUESTION, 'u2')
    assert len(reports(call.run(ANSWER_WAIT_SECONDS + 1))) == 1


def test_a_diagnosis_of_a_superseded_question_does_not_disarm_the_current_one(tmp_path):
    call = Call(tmp_path)
    call.ask(F.LOOKUP_QUESTION, 'u1')
    stale = call.controller.epoch
    call.ask(F.DIRECT_QUESTION, 'u2')
    call.controller.answer_diagnosed(stale)                       # a late lookup failure of the first question
    assert len(reports(call.run(ANSWER_WAIT_SECONDS + 1))) == 1


def test_an_answer_held_for_a_possible_continuation_is_not_taken_for_silence(tmp_path):
    """The controller itself waits (the coalescing window, up to 9.2 s while a tail that could still be merged is unfinished) before
    it speaks an answer to a question that ends in a function word: that wait is the controller's, not the cloud's silence."""
    call = Call(tmp_path)
    c = call.controller
    call.ask('Что такое инерция в', 'u1')
    call.cloud(F.DIRECT_ANSWER)
    F.precondition(c.held_source is not None, 'the answer is held back')
    call.run(1.0)
    c.speech_started()
    c.provider(F.created('t1', 'user', 'газообразное?'))            # a tail that could still be merged; the provider never finishes it
    out = call.run(ANSWER_WAIT_SECONDS - 0.5)                      # 8.5 s after the question: past the deadline, inside the 9.2 s hold
    F.precondition(c.held_source is not None, 'the hold lasts past the deadline')
    assert reports(out) == [], 'the controller\'s own hold was taken for the cloud\'s silence'
    out = call.run(4)
    assert [a for _, a in out if a['type'] == 'speak'], 'the held answer is released when the hold is over'
    assert reports(out) == []


def test_a_lone_word_held_for_the_grace_window_is_not_taken_for_silence(tmp_path):
    """An answer without terminal punctuation may be cut: the controller holds it for ANSWER_GRACE_SECONDS (1.2 s) before it speaks
    the lone word. An answer that arrives just before the deadline is spoken after it: its own window, not the cloud's silence."""
    from test_task1_review_round2 import Session
    s = Session(tmp_path)
    s.ask('Как называется наука о насекомых')
    s.whole('Энтомология', ANSWER_WAIT_SECONDS - 0.5)
    s.until(ANSWER_WAIT_SECONDS + 6)
    assert s.texts == ['Энтомология'], f'the held word was lost to the watchdog: {s.texts}'


def test_a_listener_speaking_does_not_turn_the_grace_window_into_silence(tmp_path):
    """The window counts from the end of the listener's turn (bounded): the lone word is spoken at 8.2 s, after the deadline."""
    from test_task1_review_round2 import Session
    from test_first_cue_never_silent import created
    s = Session(tmp_path)
    s.ask('Как называется наука о насекомых')
    s.whole('Энтомология', 1.0)
    s.at(1.5, created('u2', 'user', 'Уг'))                         # never finished
    s.until(14)
    assert s.texts == ['Энтомология'] and s.cues[0][0] > ANSWER_WAIT_SECONDS


def test_a_continuation_segment_that_is_still_open_is_left_to_the_idle_flush(tmp_path):
    """The producer cut its answer mid-word and went quiet without closing the turn: the existing rule speaks what arrived once it has
    been idle for SEGMENT_IDLE_SECONDS. Giving the question up at 8 s would throw that text away."""
    call = Call(tmp_path)
    call.ask('Как называется переход вещества из твёрдого состояния в газообразное')
    call.run(1.0)
    call.controller.provider(F.created('a1', 'assistant', 'Это назы'))
    call.controller.provider(F.done('a1', 'assistant', 'Это назы'))
    call.run(0.5)
    call.controller.provider(F.created('a2', 'assistant', 'вается суб'))
    call.run(0.2)
    call.controller.provider(F.delta('a2', 'лима', 1))
    out = call.run(40)
    assert reports(out) == [], "the text of the open segment was given up before the idle flush could speak it"
    spoken = [(t, a['text']) for t, a in out if a['type'] == 'speak']
    assert len(spoken) == 1 and spoken[0][1] == 'сублима' and spoken[0][0] > ANSWER_WAIT_SECONDS, spoken


def test_a_question_accepted_early_by_a_delegation_is_counted_from_its_own_final(tmp_path):
    """The cloud's delegation can announce a question while the listener is still saying it (the controller accepts it then): the seconds
    they go on speaking are not the cloud's silence, and nothing may be reported before the question is final. The delegation is the
    model asking for sources; for a settled fact (F3, item 4) it is answered at once ("no search - answer from what you know"), no lookup
    runs, and the wait is the cloud's own budget counted from the final."""
    call = Call(tmp_path)
    c = call.controller
    c.provider(F.created('u1', 'user', 'Что такое инерция'))
    c.provider(F.delegation('d1', 'u1'))
    F.precondition(c.question_id == 'u1', 'the delegation accepted the question while it was being said')
    assert reports(call.run(ANSWER_WAIT_SECONDS + 2)) == [], 'reported while the question was still being spoken'
    c.provider(F.done('u1', 'user', 'Что такое инерция?'))
    assert reports(call.run(ANSWER_WAIT_SECONDS - 0.5)) == [], 'counted from the early acceptance instead of from the final'
    assert len(reports(call.run(1.5))) == 1


def test_the_wait_can_be_switched_off(tmp_path):
    call = Call(tmp_path, answer_wait_seconds=0)
    call.ask()
    assert reports(call.run(120)) == []


def test_a_reopened_call_with_a_stored_session_has_no_question_to_report(tmp_path):
    first = Call(tmp_path)
    first.ask()
    first.cloud(F.DIRECT_ANSWER)
    second = Call(tmp_path)                                       # the same database: a reconnect
    assert reports(second.run(120)) == []


def test_the_controller_does_not_log_the_listeners_words_when_it_reports(tmp_path, caplog):
    call = Call(tmp_path)
    call.ask('Что такое секретная инерция?')
    with caplog.at_level(logging.DEBUG):
        call.run(ANSWER_WAIT_SECONDS + 1)
    assert 'секретная' not in caplog.text and 'инерция' not in caplog.text.lower()
    assert 'answer_timeout' in caplog.text


# ======================================================================================================
# 2. through the wire (virtual time): what the phone receives
# ======================================================================================================

def silent_cloud(rig, kind):
    async def go():
        await rig.ask(F.DIRECT_QUESTION)
        if kind == 'only_a_service_phrase':
            await rig.answer('Сейчас уточню.')
        elif kind == 'empty_final':
            await rig.feed(F.done('a1', 'assistant', ''))
        elif kind == 'only_the_question_echoed':
            await rig.answer('Инерция — это инерция.')
    return go()


SILENT_KINDS = ['nothing_at_all', 'only_a_service_phrase', 'empty_final', 'only_the_question_echoed']


@pytest.mark.parametrize('kind', SILENT_KINDS)
def test_a_cloud_that_gives_no_usable_answer_is_followed_by_the_spoken_phrase_after_the_wait(tmp_path, monkeypatch, kind):
    async def body(rig):
        t0 = rig.now()
        await silent_cloud(rig, kind)
        await rig.advance(ANSWER_WAIT_SECONDS - 0.5)
        assert not responses(rig.frames) and not rig.errors(), 'something was reported before the wait was over'
        await rig.advance(6)
        heard = responses(rig.frames)
        assert [r['text'] for r in heard] == [ANSWER], rig.timeline()
        phrase = heard[0]
        assert phrase['status'] == 'completed' and phrase['pcm'] == wav_pcm('answer'), 'the packaged audio (nothing was pre-rendered here)'
        assert ANSWER_WAIT_SECONDS <= phrase['start'] - t0 <= ANSWER_WAIT_SECONDS + 1.0, phrase['start'] - t0
        assert rig.errors() == ['controlled_answer_timeout'], 'the error frame stays (probes and logs read it)'
        assert not rig.source.frames, 'nothing is sent to the model on behalf of the abandoned question'
    run_wire(tmp_path, monkeypatch, body)


def test_the_phrase_is_a_diagnostic_and_never_an_answer(tmp_path, monkeypatch):
    async def body(rig):
        await rig.ask(F.DIRECT_QUESTION)
        await rig.advance(ANSWER_WAIT_SECONDS + 6)
        F.precondition(phrases_heard(rig.frames) == [ANSWER], 'the phrase was spoken')
        controller = rig.controller
        assert controller.state() is None and controller.published == '', 'a diagnostic must not become the stored answer'
        assert controller.repeat_at is None, 'nothing is armed to repeat it'
        quiet_from = rig.now()
        await rig.advance(120)
        assert not [f for f in rig.frames if f.type == 'response.created' and f.t >= quiet_from], 'the phrase repeats itself'
        assert rig.errors() == ['controlled_answer_timeout'], 'one report for one question'
    run_wire(tmp_path, monkeypatch, body)


def test_a_late_answer_for_the_abandoned_question_is_not_spoken(tmp_path, monkeypatch):
    async def body(rig):
        await rig.ask(F.DIRECT_QUESTION)
        await rig.advance(ANSWER_WAIT_SECONDS + 6)
        F.precondition(phrases_heard(rig.frames) == [ANSWER], 'the phrase was spoken')
        t_late = rig.now()
        await rig.answer(F.DIRECT_ANSWER)                          # the cloud finally answers
        await rig.advance(60)
        assert [r['text'] for r in responses(rig.frames) if r['start'] >= t_late] == [], rig.timeline()
        assert rig.controller.state() is None
    run_wire(tmp_path, monkeypatch, body)


def test_the_next_question_after_the_phrase_is_answered_as_fast_as_ever(tmp_path, monkeypatch):
    async def body(rig):
        await rig.ask(F.DIRECT_QUESTION)
        await rig.advance(ANSWER_WAIT_SECONDS + 6)
        F.precondition(phrases_heard(rig.frames) == [ANSWER], 'the phrase was spoken')
        t1 = rig.now()
        await rig.ask_direct(F.OTHER_DIRECT_QUESTION, F.OTHER_DIRECT_ANSWER)
        await rig.advance(FIRST_CUE_BOUND)
        cues = [r for r in responses(rig.frames) if r['start'] >= t1 and r['text'] not in EVERY_PHRASE]
        assert cues and cues[0]['status'] == 'completed' and cues[0]['start'] - t1 <= FIRST_CUE_BOUND
        await rig.advance(60)
        assert phrases_heard(rig.frames) == [ANSWER], 'an answered question must not be reported afterwards'
    run_wire(tmp_path, monkeypatch, body)


def test_a_slow_but_healthy_answer_is_not_announced(tmp_path, monkeypatch):
    """The slowest healthy first cue in the latency data is 3.8 s; an answer whose cue comes at 6 s is late, not lost."""
    async def body(rig):
        t0 = rig.now()
        await rig.ask(F.DIRECT_QUESTION)
        await rig.advance(6.0)
        await rig.answer(F.DIRECT_ANSWER)
        await rig.advance(FIRST_CUE_BOUND)
        await rig.advance(60)
        assert phrases_heard(rig.frames) == [] and not rig.errors(), rig.timeline()
        assert rig.spoken(t0)[0] == rig.controller.state()['chunks'][0]
    run_wire(tmp_path, monkeypatch, body)


def test_the_phrase_does_not_wait_for_the_end_of_the_cloud_turn(tmp_path, monkeypatch):
    """A cloud that has begun an answer it never finishes and whose text gives no cue is still reported on time."""
    async def body(rig):
        await rig.feed(F.created('u1', 'user', 'Что'))
        await rig.feed(F.done('u1', 'user', F.DIRECT_QUESTION))
        t0 = rig.now()
        await rig.feed(F.created('a1', 'assistant', 'Сейчас'))      # never finished
        await rig.advance(ANSWER_WAIT_SECONDS + 6)
        heard = responses(rig.frames)
        assert [r['text'] for r in heard] == [ANSWER] and heard[0]['start'] - t0 <= ANSWER_WAIT_SECONDS + 1.0
    run_wire(tmp_path, monkeypatch, body)


@pytest.mark.parametrize('mode', ['raise', 'hang', 'empty'])
def test_a_failed_lookup_is_announced_once_and_the_missing_answer_is_not_announced_on_top(tmp_path, monkeypatch, mode):
    async def body(rig):
        await rig.ask(F.LOOKUP_QUESTION)
        await rig.advance(LOOKUP_WAIT_SECONDS + ANSWER_WAIT_SECONDS + 30)
        assert phrases_heard(rig.frames) == [LOOKUP_EMPTY], rig.timeline()
        assert rig.errors() == ['controlled_sources_unavailable']
    run_wire(tmp_path, monkeypatch, body, lookup=[mode])


# 4.09a personal_volatile is always on: a calendar question gets the honest local phrase; this test guards the model road, so it asks a personal question outside the volatile list
def test_a_refused_personal_question_is_not_announced_as_an_error_and_a_missing_answer_is_announced_once(tmp_path, monkeypatch):
    """F3 (item 2) replaces what this pinned («Ошибка. Повторите вопрос.» straight after the question): the refusal of the public lookup
    is the listener's business no more - the model is told there is no search - and a cloud that then never answers is reported by the
    watchdog, once, in the words of a missing answer."""
    async def body(rig):
        await rig.ask('Что у меня записано в заметках на завтра?')
        await rig.advance(ANSWER_WAIT_SECONDS + 30)
        assert phrases_heard(rig.frames) == [ANSWER], rig.timeline()
        assert rig.errors() == ['controlled_answer_timeout']
    run_wire(tmp_path, monkeypatch, body)


def test_a_question_given_up_is_not_reported_again_by_the_lookup_that_was_still_running(tmp_path, monkeypatch):
    """With a wait shorter than the lookup budget (a setting, not the product value) the question is given up while its lookup still runs;
    the failure of that lookup, 6 s later, belongs to an epoch that is over and is not reported."""
    async def body(rig):
        await rig.ask(F.LOOKUP_QUESTION)
        await rig.advance(20)
        assert rig.errors() == ['controlled_answer_timeout'], rig.timeline()
        assert phrases_heard(rig.frames) == [ANSWER]
    run_wire(tmp_path, monkeypatch, body, lookup=['hang'], controller_kwargs={'answer_wait_seconds': 2.0, 'lookup_wait_seconds': 0.0})


def test_a_lookup_question_the_cloud_never_answers_is_announced_after_the_delivery_plus_the_lookup_budget(tmp_path, monkeypatch):
    async def body(rig):
        t0 = rig.now()
        await rig.ask(F.LOOKUP_QUESTION)                           # the lookup works; the cloud takes the sources and says nothing
        await rig.advance(LOOKUP_ANSWER_WAIT_SECONDS - 0.5)
        F.precondition([k for k, _ in rig.source.frames] and {k for k, _ in rig.source.frames} == {'E'}, 'the context reached the model')
        assert not responses(rig.frames), 'reported before the wait after the delivery was over'
        await rig.advance(6)
        heard = responses(rig.frames)
        assert [r['text'] for r in heard] == [ANSWER], rig.timeline()
        assert heard[0]['start'] - t0 <= LOOKUP_ANSWER_WAIT_SECONDS + 1.0, 'counted from the delivery, which was immediate here'
    run_wire(tmp_path, monkeypatch, body)


def test_the_listener_speaking_over_the_deadline_is_not_interrupted_by_the_phrase(tmp_path, monkeypatch):
    async def body(rig):
        await rig.ask(F.DIRECT_QUESTION)
        await rig.advance(ANSWER_WAIT_SECONDS - 1)
        await rig.feed(F.created('h1', 'user', 'Подождите'))       # they start to say something at once
        for n in range(1, 7):
            await rig.advance(1.0)
            await rig.feed(F.delta('h1', ' пожалуйста', n))
        assert not responses(rig.frames), 'the phrase was spoken over the listener'
        await rig.advance(8)
        assert phrases_heard(rig.frames) == [ANSWER], 'and it still comes once they are quiet'
    run_wire(tmp_path, monkeypatch, body)


def test_a_persistent_silent_cloud_is_reported_once_per_question_and_never_in_a_loop(tmp_path, monkeypatch):
    async def body(rig):
        for _ in range(4):
            await rig.ask(F.DIRECT_QUESTION)
            await rig.advance(ANSWER_WAIT_SECONDS + 6)             # the phrase is over before they ask again
        starts = [r['start'] for r in responses(rig.frames)]
        assert len(starts) == 4 and all(b - a >= 10 for a, b in zip(starts, starts[1:])), starts
        quiet_from = rig.now()
        await rig.advance(120)
        assert not [f for f in rig.frames if f.type == 'response.created' and f.t >= quiet_from]
    run_wire(tmp_path, monkeypatch, body)


def test_the_report_is_logged_with_class_and_reason_and_without_the_listeners_words(tmp_path, monkeypatch):
    async def body(rig):
        await rig.ask('Что такое секретная инерция?')
        await rig.answer('Сейчас уточню.')
        await rig.advance(ANSWER_WAIT_SECONDS + 6)
        F.precondition(rig.errors(), 'the report must have happened')
    with F.capture_logs() as logs:
        run_wire(tmp_path, monkeypatch, body)
    text = logs.text(logging.WARNING)
    assert 'class=answer' in text and 'code=controlled_answer_timeout' in text and 'reason=no_usable_text' in text, text
    assert 'diagnostic=spoken' in text
    assert 'секретная' not in logs.text(logging.DEBUG)


# ======================================================================================================
# 3. through controlled_host.serve
# ======================================================================================================

def test_the_host_speaks_the_prerendered_phrase_when_the_cloud_stays_silent(tmp_path, monkeypatch):
    async def body(host):
        host.synth_plan.calls.clear()
        t0 = host.now()
        await host.ask(F.DIRECT_QUESTION)
        await host.advance(ANSWER_WAIT_SECONDS + 6)
        heard = responses(host.ws.frames)
        assert [r['text'] for r in heard] == [ANSWER] and heard[0]['status'] == 'completed'
        assert heard[0]['pcm'] == b'\x01\x02' * 2400 != wav_pcm('answer'), 'the pre-rendered PCM, not the packaged one'
        assert not [t for _, t in host.synth_plan.calls if t in EVERY_PHRASE], 'the phrase must not be synthesized at report time'
        assert host.errors(t0) == ['controlled_answer_timeout']
        assert ANSWER_WAIT_SECONDS <= heard[0]['start'] - t0 <= ANSWER_WAIT_SECONDS + 1.5
        assert not host.finished, 'the call goes on'
        text = host.logger.text(logging.WARNING)
        assert 'controlled_answer_timeout' in text and 'call=' in text, text
    run_host(tmp_path, monkeypatch, body)


def test_the_production_controller_arms_the_watchdog_without_any_new_argument():
    """controlled_host.serve passes no ``answer_wait_seconds``: the product default is on (the S6 rigs pin the call by ``ast``)."""
    import inspect
    parameter = inspect.signature(controlled_media.ControlledMedia.__init__).parameters['answer_wait_seconds']
    assert parameter.default == ANSWER_WAIT_SECONDS
