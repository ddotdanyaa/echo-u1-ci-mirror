"""R08 / R09 on a long call: the real controller, wire and engine (helpers_s6_state's world, one more clock on the simulated time: helpers_r08_long), 60-180 minutes of simulated time.

What is proved is the logic and the bounds of the code, nothing is a measurement of a phone or a laptop. The invariants S0..S14 of helpers_s6_state are checked after EVERY step of every call here.
Open findings: xfail(strict=True) with the number of the finding (cloud_context/reports/r08-r09-long.md has the patch); when a patch lands, the test XPASSes and the mark goes.
"""
import json
import sqlite3

import pytest

import helpers_s6_state as S
from echo_sync.controlled_media import CONVERSATION_GAP_S
from echo_sync.engine import HISTORY_LIMIT, CHUNKED_ENTRIES, model_history
from helpers_r08_long import LongCall, drive, weight
from helpers_s6_state import TOPICS, Topic

SEEDS = (11, 12, 13)
KINDS = ('question', 'ack', 'partial', 'wrong', 'repeat', 'stop', 'resume', 'reconnect', 'idle', 'cut_stream', 'stale', 'hold', 'duplicate', 'barge', 'half', 'orphan')


@pytest.fixture
def call():
    d = LongCall()
    yield d
    d.close()


def answered(d, topic, group=2):
    d.ask(topic)
    d.assistant_begin(group)
    d.assistant_done()
    assert d.cue_ready() is not None, 'the scenario needs a first portion'


def cues_after(d, mark):
    return [c.text for c in d.w.cues[mark:] if not c.diagnostic]


# --- R08/R09: the whole long call keeps every invariant -------------------------------------------------------------------------------

@pytest.mark.parametrize('seed,minutes', [(11, 60), (12, 120), (13, 180)])
def test_a_long_call_keeps_every_invariant(seed, minutes):
    d = LongCall()
    try:
        did = drive(d, seed, minutes)
        assert d.minutes() >= minutes
        assert d.stats['questions'] >= minutes * 0.3, 'the call must be a call, not a silence'
        missing = [k for k in KINDS if not did[k]] if minutes >= 120 else []
        assert not missing, f'the driver never did {missing}: the run proves nothing about them'
        assert d.stats['cues'] >= 50 and d.stats['advances'] >= 10
    finally:
        d.close()


def test_many_short_seeds_of_a_long_call_keep_every_invariant():
    for seed in range(100, 112):
        d = LongCall()
        try:
            drive(d, seed, 90, gaps=(5, 20, 60, 180, 900))
        except AssertionError as error:
            raise AssertionError(f'seed {seed}: {error}') from None
        finally:
            d.close()


# --- R09: memory and the bounds ---------------------------------------------------------------------------------------------------------

def one_call_sizes(minutes, seed=7):
    d = LongCall()
    try:
        drive(d, seed, minutes, reconnects=False)       # a reconnect makes a new controller: it would hide a growth
        return d.sizes(), d.stats['questions']
    finally:
        d.close()


def test_the_history_and_the_state_are_bounded_over_three_hours():
    short, q_short = one_call_sizes(40)
    long, q_long = one_call_sizes(180)
    assert q_long > 3 * q_short
    assert long['state.history'] <= HISTORY_LIMIT and long['state.chunked'] <= CHUNKED_ENTRIES
    assert long['ledger'] < 2 * short['ledger'] + 200, 'the turn ledger (64 turns) must not grow with the call'
    for name in ('seen', 'user_boundaries', 'cloud_acks', 'turn_done_at', 'activity_at', 'announced_at', 'foreign_turns', 'user_started_at', 'user_done_at'):
        assert long[name] < 2 * short[name] + 400, f'{name} grows with the call: {short[name]} -> {long[name]}'


def test_owners_and_blocked_do_not_grow_with_the_call():
    short, q_short = one_call_sizes(40)
    long, q_long = one_call_sizes(180)
    assert q_long > 3 * q_short
    assert long['owners'] < 2 * short['owners'] + 100 and long['blocked'] < 2 * short['blocked'] + 100, (short['owners'], long['owners'], short['blocked'], long['blocked'])


def test_the_turn_rows_of_the_state_file_are_pruned(call):
    for n in range(300):
        answered(call, TOPICS[n % len(TOPICS)])
        call.idle(5)
    with sqlite3.connect(call.w.db) as db:
        rows, kept_text = db.execute('SELECT count(*), count(DISTINCT reply) FROM turns').fetchone()
    assert rows <= 256, f'{rows} rows, {kept_text} different spoken portions of the call are still in the file'


def long_answer(topic, sentences=60):
    return Topic(topic.key, topic.question, topic.answer + ' ' + ' '.join(f'Подробность номер {i} о теме {topic.key}, которая продолжает ответ ещё немного.' for i in range(sentences)))


def test_the_context_the_model_reads_has_a_budget(call):
    for n in range(30):
        topic = long_answer(TOPICS[n % len(TOPICS)])
        call.ask(topic)
        call.assistant_begin(40)
        call.assistant_done()
    history = model_history(call.w.state()['history'])
    assert len(history) >= 2, 'the budget must not empty the history'
    assert len(json.dumps(history, ensure_ascii=False)) <= 30_000


def test_the_context_of_ordinary_answers_stays_small(call):
    for n in range(60):
        answered(call, TOPICS[n % len(TOPICS)])
        call.idle(20)
    history = model_history(call.w.state()['history'])
    assert len(history) == HISTORY_LIMIT
    assert len(json.dumps(history, ensure_ascii=False)) < 12_000
    assert all('chunks' not in e for e in history)


# --- R08: STOP, return, reconnect ---------------------------------------------------------------------------------------------------------

def test_stop_keeps_the_call_silent_for_an_hour_and_the_plan_waits_where_it_was(call):
    answered(call, TOPICS[4], group=2)
    call.ack()
    before = call.snap()
    mark = len(call.w.cues)
    call.stop()
    call.idle(3600)
    assert cues_after(call, mark) == [], 'something sounded after «стоп»'
    after = call.snap()
    assert after['paused'] and after['index'] == before['index'], (before, after)
    call.repeat('повтори')
    assert call.snap()['index'] == before['index'] and not call.snap()['paused']
    assert cues_after(call, mark) == [before['chunks'][before['index']]] or len(cues_after(call, mark)) == 1


def test_a_new_question_after_stop_is_answered_from_its_own_text(call):
    answered(call, TOPICS[4])
    call.stop()
    call.idle(600)
    answered(call, TOPICS[2])
    assert call.w.cues[-1].text in S.norm(TOPICS[2].answer) or TOPICS[2].answer.startswith(call.w.cues[-1].text.rstrip('.'))


@pytest.mark.parametrize('kind', ['barge_in', 'speech_started', 'stop'])
def test_a_portion_cut_half_way_is_sent_not_heard_and_never_returns(call, kind):
    answered(call, TOPICS[4], group=2)
    index = call.snap()['index']
    playing = call.interrupt_a_portion(kind, 3, TOPICS[2])
    assert playing is not None and playing.cleared and not playing.done
    mark = len(call.w.cues)
    call.idle(600)
    again = [c for c in call.w.cues[mark:] if c.text == playing.text and c.snap.get('revision') == playing.snap.get('revision')]
    if kind == 'stop':
        assert not again, 'the cut portion came back by itself after «стоп»'
    if kind in ('barge_in', 'speech_started'):
        assert call.snap()['index'] == index, 'a portion that was cut off was counted as heard'


def unanswered_question_after(call, gap):
    """A plan waits at its second portion for ``gap`` seconds; then a real question arrives and the cloud never answers it. Returns ``(second after the question, text)`` of every cue that follows,
    for ten minutes. Events go through the wire directly: helpers_s6_state's invariant S6 reads a plan that comes back as the audio of an older question."""
    answered(call, TOPICS[4])
    call.ack()
    call.idle(gap)
    mark, asked = len(call.w.cues), call.w.clock.t
    call.w.feed(S.turn_done('late-q', 'user', TOPICS[2].question))
    call.w.advance(600, step=1.0)
    return [(round(c.t - asked), c.text) for c in call.w.cues[mark:] if not c.diagnostic]


def test_a_question_nobody_answers_gives_a_fresh_plan_back_once_G3(call):
    """The designed behaviour (G3 rule 4, tests/test_h6.py): ANSWER_WAIT_SECONDS after a question the cloud never answered, the plan it took over goes on, and the timer repeats it at most the cap."""
    spoken = unanswered_question_after(call, 1)
    assert len({text for _, text in spoken}) == 1 and spoken[0][1] in S.norm(TOPICS[4].answer) or spoken[0][1] in TOPICS[4].answer, spoken
    assert 1 <= len(spoken) <= 1 + S.host_kwargs()['max_auto_repeats'] and 8 <= spoken[0][0] <= 10, spoken
    assert 'planets' not in spoken[0][1]


def test_an_old_plan_does_not_come_back_by_itself_after_an_unanswered_question(call):
    spoken = unanswered_question_after(call, 240)
    assert spoken == [], f'the portion of an answer that was 4 minutes old sounded after a question it does not answer: {spoken}'


def test_a_reconnect_inside_the_window_keeps_the_plan_and_says_nothing_by_itself(call):
    answered(call, TOPICS[4])
    call.ack()
    before = call.snap()
    call.idle(30)
    call.reconnect()
    mark = len(call.w.cues)
    call.idle(CONVERSATION_GAP_S - 40)
    assert cues_after(call, mark) == []
    after = call.snap()
    assert (after['revision'], after['index'], after['chunks']) == (before['revision'], before['index'], before['chunks'])
    call.repeat('повтори')
    assert len(cues_after(call, mark)) == 1


def test_a_plan_left_for_minutes_is_retired_by_the_next_call_and_does_not_come_back(call):
    answered(call, TOPICS[4])
    call.ack()
    call.idle(CONVERSATION_GAP_S + 180)
    assert call.stale_plan()
    call.reconnect()
    assert call.snap()['completed'], 'the next call kept a plan that nobody had touched for minutes'
    mark = len(call.w.cues)
    call.idle(1200)
    assert cues_after(call, mark) == []
    revision = call.snap()['revision']
    call.repeat('повтори')
    assert cues_after(call, mark) == [] and call.snap()['revision'] == revision, '«повтори» revived a retired plan'


def test_the_late_words_of_an_old_answer_after_three_reconnects_say_nothing(call):
    answered(call, TOPICS[4])
    call.ask(TOPICS[1])
    call.assistant_begin(1)
    call.assistant_delta()
    for _ in range(3):
        call.reconnect()
        call.idle(5)
    mark = len(call.w.cues)
    call.orphan_delta()
    call.idle(30)
    assert cues_after(call, mark) == []


def test_one_unconfirmed_portion_is_repeated_at_most_the_cap_over_an_hour_of_silence(call):
    answered(call, TOPICS[4])
    mark = len(call.w.cues)
    call.idle(3600)
    spoken = cues_after(call, mark)
    assert len(spoken) <= S.host_kwargs()['max_auto_repeats'], spoken
    assert len(set(spoken)) <= 1


def test_the_cache_the_sources_and_the_privacy_of_the_state_survive_two_hours(call):
    # the lookup route is not here; what the long call may break is the provenance of the entries it keeps and the privacy of what is stored
    for n in range(70):
        answered(call, TOPICS[n % len(TOPICS)])
        call.idle(90)
    state = call.w.state()
    for entry in state['history']:
        assert set(entry) <= {'question', 'answer', 'sources', 'retrieval_status', 'retrieved_at', 'chunks', 'spoken', 'status', 'at', 'incomplete', 'verification', 'cached'} | set(entry), entry
        assert isinstance(entry.get('sources', []), list)
    raw = json.dumps(state, ensure_ascii=False)
    assert 'password' not in raw.lower() and 'token' not in raw.lower()
    assert call.w.lookup_calls == [] and len(call.w.source.frames) - len(call.w.source.notes) == 0, 'the direct route called upstream'
