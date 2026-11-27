"""Wave F / F3, item 3 (the owner's REAL call of 3 Nov 09:55, call abcc139fe874): a new call starts clean.

The call opened with the engine state at revision 13, index 1 - a portion an earlier call had left waiting (the phone's session id is one
constant for every call) - and the first question was judged against it ('unrelated_speech'). At call open an answer still waiting from
an earlier call is retired (history kept). Proved through the real call-open path: controlled_host.serve (helpers_s6_fault.HostRig: fake
phone, fake cloud helper pipe, fake SAPI, virtual time) over a database an earlier ControlledMedia left behind.

Items 2 and 4 (the delegation result) are in test_f3_delegation.py, item 1 (sentences about the cloud's own actions) in
test_f3_process_sentences.py.
"""
import json
import logging
import sqlite3
from pathlib import Path

import pytest

import helpers_s6_fault as F
from echo_sync.classifier import waiting_portion
from echo_sync.controlled_media import ControlledMedia
from echo_sync.engine import EchoEngine
from test_first_cue_never_silent import Clock, created, done

PHONE_SESSION = 'live-native-controlled-user-v1'        # controlled_host.controller_session_id: one constant for every phone call
ANSWER = 'Инерция — это свойство тела сохранять свою скорость. Оно не зависит от массы.'


def db_of(home):
    return Path(home) / 'echo-sync' / 'controlled-state.sqlite3'


def stored(path, session=PHONE_SESSION):
    """The stored session state, read the way the next call reads it."""
    return EchoEngine(path, lambda *a: None).state(session)


def age_state(path, seconds, session=PHONE_SESSION, *, keep_issued_at=True):
    """The stored answer of the session as it was ``seconds`` ago (the engine's wall clock: ``issued_at``, the entry's ``at``)."""
    db = sqlite3.connect(str(path))
    try:
        state = json.loads(db.execute('SELECT state FROM sessions WHERE session_id=?', (session,)).fetchone()[0])
        if keep_issued_at:
            state['issued_at'] -= seconds
        else:
            state.pop('issued_at', None)
        for entry in state.get('history', []):
            if 'at' in entry:
                entry['at'] -= seconds
        db.execute('UPDATE sessions SET state=? WHERE session_id=?', (json.dumps(state, ensure_ascii=False), session))
        db.commit()
    finally:
        db.close()


STALE = 300     # seconds: older than RECONNECT_WINDOW_S (a drop and a re-dial), younger than the resume window of "продолжай" (600 s)


def stale_portion(home, seconds=STALE):
    """The state of an earlier call that ended ``seconds`` ago with a portion waiting. Returns (the portion, the state)."""
    seen = leave_a_portion_waiting(db_of(home))
    age_state(db_of(home), seconds)
    return seen[0], stored(db_of(home))


# fix-c20: G15 holds the first sentence of DIRECT_ANSWER (9 words) as one first portion: one more sentence keeps a second portion to wait (as integ9 did below)
WAITING_ANSWER = F.DIRECT_ANSWER + ' Её мерой служит масса тела.'


def leave_a_portion_waiting(path, session=PHONE_SESSION, question=F.DIRECT_QUESTION, answer=WAITING_ANSWER):
    """An earlier call that ended with its answer half dictated: the first portion confirmed, the second one waiting for the listener
    (the owner's call opened at revision 13, index 1). Returns (the portion that waits, the stored state)."""
    c = ControlledMedia(path, session_id=session, clock=Clock(100.0), **F.HOST_KWARGS)
    c.provider(created('u0', 'user', question.split()[0]))
    c.provider(done('u0', 'user', question))
    first = next(a['text'] for a in c.provider(done('a0', 'assistant', answer)) if a['type'] == 'speak')
    c.provider(done('r0', 'user', first))
    state = c.state()
    portion = waiting_portion(state)
    assert portion and portion != first and state['chunk_index'] == 1, state   # precondition: the second portion waits
    return portion, state


def run_call(tmp_path, monkeypatch, body, *, before=None):
    """The real serve() on virtual time. ``before(home)`` runs BEFORE the call opens (it leaves the state of an earlier call)."""
    async def main():
        F.patch_clock(monkeypatch)
        rig = F.HostRig(tmp_path, monkeypatch)
        seen = before(rig.home) if before else None
        async with rig as host:
            await host.handshake()
            return await body(host, seen)
    return F.run(main)


@pytest.fixture(autouse=True)
def decisions_are_logged(caplog):
    caplog.set_level(logging.INFO, logger='echo-sync')


# ===================================================================================================================================
# 1. A new call starts clean (item 3)
# ===================================================================================================================================

def test_a_call_that_opens_retires_the_answer_an_earlier_call_left_waiting(tmp_path, monkeypatch):
    """The owner's call: «ear uid=1 ... revision=13 index=1» at the first word - a portion left by an earlier call, and the first
    question was judged against it. Through the real serve(): the answer that waited is retired, its history entry kept."""
    async def body(host, before):
        portion, old = before
        now = stored(db_of(host.home))
        assert waiting_portion(now) is None and now['completed'] and now['chunks'] == [], now
        assert now['revision'] == old['revision'] + 1                         # retired the way a new question retires an answer
        entry = now['history'][-1]
        assert entry['question'] == F.DIRECT_QUESTION and entry['answer'] == old['answer']      # what the earlier call dictated, as it was
        assert entry['status'] == 'interrupted' and entry['spoken'] == 1 and portion in entry['chunks'], entry
        assert host.spoken() == [], 'opening a call speaks nothing'
    run_call(tmp_path, monkeypatch, body, before=stale_portion)


def test_the_listener_of_a_new_call_is_not_given_the_portion_of_the_earlier_call(tmp_path, monkeypatch):
    """Before: a reopened call stayed quiet until «повтори», and then said the portion of the CALL BEFORE. The first words of a new
    call are about this call."""
    async def body(host, before):
        host.cloud(F.created('r1', 'user', 'Повтори'))
        host.cloud(F.done('r1', 'user', 'Повтори'))
        await host.advance(3)
        assert host.spoken() == [], host.spoken()
    run_call(tmp_path, monkeypatch, body, before=stale_portion)


def test_what_the_earlier_call_left_unsaid_can_still_be_asked_for_by_name(tmp_path, monkeypatch):
    """History kept: the retired answer is an interrupted entry the listener can go on with («продолжай», CL2) inside the resume window -
    a retire, not a deletion."""
    async def body(host, before):
        portion, _ = before
        host.cloud(F.created('c1', 'user', 'Продолжай'))
        host.cloud(F.done('c1', 'user', 'Продолжай'))
        await host.advance(3)
        assert host.spoken() == [portion], host.spoken()
    run_call(tmp_path, monkeypatch, body, before=stale_portion)


def test_a_call_that_opens_after_a_finished_answer_changes_nothing(tmp_path, monkeypatch):
    """Only an answer that WAITS for the listener is retired; one that was said to the end stays as the call before left it."""
    def finished(home):
        path = db_of(home)
        c = ControlledMedia(path, session_id=PHONE_SESSION, clock=Clock(100.0), **F.HOST_KWARGS)
        c.provider(created('u0', 'user', 'Что'))
        c.provider(done('u0', 'user', 'Что такое инерция?'))
        c.provider(done('a0', 'assistant', 'Свойство тела сохранять скорость.'))
        for n in range(6):
            state = c.state()
            if state['completed']:
                break
            c.provider(done(f'r{n}', 'user', waiting_portion(state)))
        assert c.state()['completed'], c.state()
        return c.state()

    async def body(host, before):
        assert stored(db_of(host.home))['revision'] == before['revision']
    run_call(tmp_path, monkeypatch, body, before=finished)


def test_a_call_that_opens_with_nothing_stored_is_untouched(tmp_path, monkeypatch):
    async def body(host, before):
        assert stored(db_of(host.home)) is None
    run_call(tmp_path, monkeypatch, body)


def test_the_first_remark_of_a_new_call_is_not_judged_against_the_portion_of_the_call_before(tmp_path, monkeypatch, caplog):
    """The decision log of the call (what the owner reads in the trace): «Ну и короче я готов» was 'unrelated_speech' (a verdict about
    the portion that waited, rev=13 idx=1); in a clean call it is only 'not a question', and no portion is mentioned."""
    async def body(host, before):
        host.cloud(F.created('u1', 'user', 'Ну'))
        host.cloud(F.done('u1', 'user', 'Ну и короче я готов'))
        await host.advance(1)
        lines = [r.getMessage() for r in caplog.records if 'echo-sync decision' in r.getMessage()]
        assert not [line for line in lines if 'unrelated_speech' in line or 'mismatch_silent' in line], lines
    run_call(tmp_path, monkeypatch, body, before=stale_portion)


def test_begin_call_is_what_the_host_calls_and_it_is_idempotent(tmp_path):
    path = tmp_path / 'controlled-state.sqlite3'
    leave_a_portion_waiting(path)
    age_state(path, STALE)                                                   # an earlier call, long over (a fresh one is kept: test_f3_round1)
    c = ControlledMedia(path, session_id=PHONE_SESSION, clock=Clock(200.0), **F.HOST_KWARGS)
    assert waiting_portion(c.state()) is not None                            # the constructor alone keeps the position (tests reopen it)
    revision = c.state()['revision']
    c.begin_call()
    assert waiting_portion(c.state()) is None and c.state()['revision'] == revision + 1
    c.begin_call()
    assert c.state()['revision'] == revision + 1                             # nothing waits any more: a second call changes nothing
