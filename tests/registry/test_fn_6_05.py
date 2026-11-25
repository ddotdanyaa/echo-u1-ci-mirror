"""Registry 6.05 «Длинная сессия 1-3 часа». Registry state: РАБОТАЕТ НА СЕРВЕРЕ (проверено тестом или пробой, на телефоне не проверено).
Proves, through the real controller (tests/helpers_night_memory.Call: real ControlledMedia + native media socket + engine + ledger + fast_text + CallTrace; cloud, model, synthesis, phone, clock scripted),
a DENSE call of 180 virtual minutes (>100 utterances, the 64-turn ledger of the cloud overflows, the journal filled to the live density of ~5 MB through call.trace.note: a faked density at the boundary):
the same question is put at minute 1, 3, 60, 125, 177, and
 1 the answer of the third hour is the answer of the first minute (same portions), the virtual delay to the first portion does not grow
 2 the request to the model at the third hour has the same question and a prompt of the same bounded kind (policy + last lines)
 3 the journal (5 MB, as live) still gets the real events at minute 177 and has no trace_full (cap 8 MB; at the old 1 MB cap it fills, see notes)
 4 the work per question does not grow: Python calls (sys/threading.setprofile) for the question at minute 177 <= 1.5 x minute 3 and <= 1.05 x minute 125 (deterministic; sleeps and wall time are NOT seen)
 5 no exception, no wire violation
Keys: fast_text=on (code default off, live on), conversation_ledger=memory (default off, live memory), facts_journal=on (default off, live on); v6_memory, topic_recap off as live.
Off-switch check (private copy, registry_proof/6.05.json): MAX_FILE_BYTES 1_000_000 for 3 (the cap of the old build); a loop over all written lines in the record writer of CallTrace for 4."""
import itertools
import sys
import threading

import pytest

import helpers_night_memory as M
from echo_sync.settings import DEFAULTS

PROFILE = {'fast_text': 'on', 'conversation_ledger': 'memory', 'facts_journal': 'on', 'topic_recap': 'off'}
ASK_AT = (1.0, 3.0, 60.0, 125.0, 177.0)       # minute 1 is cold, minute 3 is the warm start, the last two are in the second and the third hour
CHATTER_EVERY, PAD_LINES, PAD_BYTES = 1.7, 100, 470      # minutes between utterances (~105 in the call); ~100 x 0.5 KB of service lines per utterance = ~5 MB in 3 hours (the registry: 1 MB per 37-58 min)
GROWTH, PLATEAU = 1.5, 1.05                  # calls for the question: the third hour vs the start (the ledger fills up and saturates in the first hour) and vs the second hour


def ask_once(call, question):
    """Put the question and let the owner say the portions back: (portions, seconds to the first one, request, number of Python calls while it went)."""
    began, seen, before, ticks = call.w.clock.now(), len(call.w.cues), len(call.requests), itertools.count()
    counter = lambda frame, event, arg: next(ticks) if event == 'call' else None      # noqa: E731
    threading.setprofile(counter)
    sys.setprofile(counter)
    try:
        call.ask(question)             # the question, its job thread and request, and the owner saying the portions back
    finally:
        sys.setprofile(None)
        threading.setprofile(None)
    cues = [cue for cue in call.w.cues[seen:] if not cue.diagnostic]
    return [cue.text for cue in cues], cues[0].t - began, call.requests[before][2], next(ticks)


@pytest.fixture(scope='module')
def played(tmp_path_factory):
    call = M.Call(tmp_path_factory.mktemp('long_call'), **PROFILE)
    try:
        asks, minute = [], CHATTER_EVERY
        for at in ASK_AT:
            while minute < at - 1.0:
                call.go(minute)
                call.chatter()
                for n in range(PAD_LINES):
                    call.trace.note('pad', n=n, text='x' * PAD_BYTES)      # the live density of the journal: lines of the same writer the engine uses
                minute += CHATTER_EVERY
            call.go(at)
            asks.append((call.minute(), *ask_once(call, M.Q_WARRANTY)))
        call.go(179.0)
        return {'asks': asks, 'said': call.n, 'errors': list(call.w.errors) + list(call.w.loop_errors), 'violations': list(call.w.violations), 'minutes': call.minute(),
                'requests': call.all_requests(), 'journal': call.journal()}
    finally:
        call.close()


def test_the_answer_of_the_third_hour_is_the_answer_of_the_first_minute(played):
    first, *later = played['asks']
    assert [round(a[0]) for a in played['asks']] == [1, 3, 60, 125, 177] and played['said'] > 100      # the 64-turn ledger of the cloud has overflowed
    assert first[1] == [M.A_WARRANTY.split('. ')[0] + '.', M.A_WARRANTY.split('. ')[1]]                 # two portions, as the model said them
    for minute, portions, delay, *_ in later:
        assert portions == first[1], minute
        assert delay <= first[2] + 0.05 and delay < 2.0, (minute, delay, first[2])                    # the virtual delay does not grow with the call


def test_the_request_of_the_third_hour_is_as_small_as_the_first(played):
    first, *later = played['asks']
    for minute, _, _, request, _ in later:
        assert request['instructions'].startswith(M.POLICY) and len(request['instructions']) < len(M.POLICY) + DEFAULTS['v6_memory_chars'] + 600, minute      # the policy and the memory card (never longer than its budget), nothing piles up
        assert M.asked(request) == M.asked(first[3]), minute


def test_the_dense_journal_keeps_being_written_to_the_third_hour(played):
    rows = played['journal']
    kinds = [r['ev'] for r in rows]
    assert kinds.count('pad') >= 10_000 and sum(len(str(r)) for r in rows if r['ev'] == 'pad') > 4_500_000      # the density is real: ~5 MB, the old cap of 1 MB would be over at minute 40
    assert kinds.count('trace_full') == 0 and kinds[-1] != 'trace_full'                                    # the cap was never reached: the "journal is full" mark is absent
    jobs = [r for r in rows if r['ev'] == 'fast_job']
    assert [r['job'] for r in jobs] == list(range(1, len(played['requests']) + 1))                            # one line for every request, none lost
    assert jobs[-1]['t'] >= 177 * 60_000 and jobs[-1]['first'].startswith('Гарантия 24 месяца')              # the real events of minute 177 are written, with the answer
    assert [r['t'] for r in rows] == sorted(r['t'] for r in rows)


def test_the_work_per_question_does_not_grow_with_the_call(played):
    start, hour, second, late = (played['asks'][i][4] for i in (1, 2, 3, 4))
    assert start > 1000, start                                                  # the counter really sees the engine at work (a sleep or wall time is NOT seen by it)
    assert late <= GROWTH * start and late <= PLATEAU * second, (start, hour, second, late)      # same question: the third hour costs no more Python calls than minute 3 and than the second hour


def test_nothing_breaks_in_three_hours(played):
    assert played['minutes'] >= 178.0 and played['errors'] == [] and played['violations'] == []
