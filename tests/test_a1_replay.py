"""A1: the stand of a whole conversation (tools/replay/stand.py) and what it found.

The stand plays a seeded conversation through the real controller, the real wire, the real ShadowEar and the real FastText channel; the ear, the cloud and the text model are
scripted (their texts, their delays, their failures). ``check`` reads the record against the invariants A0-A8 of the stand's docstring.

First the stand's own tests: one seed is one conversation, every check fires on a record built to break it and stays quiet on one that keeps it. Then the findings: each one is the
smallest seed of its group in the run of cloud_context/reports/a1-fuzz.md, cut to the moment of the violation, a RED test (never xfail) with its number until the patch of the
report lands (the files are not this task's). Nothing here is a measurement of time on a laptop or a phone.
"""
import pytest

from tools.replay import stand
from tools.replay.stand import Outcome, Q, Said, check

MONEY = Q('money', (80, 20), 'Если у меня было 80 рублей и я потратил 20 рублей, сколько денег осталось?')
SWAPPED = Q('money', (20, 80), 'Если у меня было 20 рублей и я потратил 80 рублей, сколько денег осталось?')
COLD = Q('verb', ('охлаждать', 'нагревать'), 'Нужно не нагревать, а охлаждать эту жидкость при таком давлении?')
HOT = Q('verb', ('нагревать', 'охлаждать'), 'Нужно не охлаждать, а нагревать эту жидкость при таком давлении?')


pytestmark = pytest.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)


def said(n, kind, onset, offset, *, q=None, ear_at=None, final_at=None, text=None, created_at=None):
    meaning = ('q', q) if q is not None else ('cmd', kind) if kind in ('stop', 'again', 'resume') else None
    return Said(n, kind, text or (q.text if q else kind), '', onset, offset, ear_at=ear_at, final_at=final_at, meaning=meaning, created_at=created_at)


def cue(t, text, revision, index, chunks=None, qid='u1'):
    return (t, text, revision, index, tuple(chunks or (text,)), False, False, qid)


def record(utterances, cues, states=()):
    out = Outcome(0, {})
    out.said, out.cues, out.states = list(utterances), list(cues), list(states)
    return out


def kinds(out):
    return sorted({inv for inv, _, _ in check(out)})


# =====================================================================================================================================
# the stand
# =====================================================================================================================================

def test_a_seed_is_one_conversation():
    first, second = stand.run(7, length=45), stand.run(7, length=45)
    assert [(u.kind, u.text, u.onset, u.ear_at, u.final_at) for u in first.said] == [(u.kind, u.text, u.onset, u.ear_at, u.final_at) for u in second.said]
    assert first.cues == second.cues and first.violations == second.violations
    assert first.cues and len(first.said) > 5, 'precondition: something was said and answered'


def test_the_ideal_mind_answers_what_was_said_and_its_correction_last():
    mind = stand.Mind()
    mind.learn(MONEY.text, ('q', MONEY))
    fixed = Q('money', (90, 20), MONEY.text.replace('80', '90'))
    mind.learn('Нет, не 80, а 90.', ('fix', fixed))
    asked = {'input': [{'content': [{'text': MONEY.text + ' Нет, не 80, а 90.'}]}]}
    assert mind.answer(asked) == 'Осталось 70 рублей.'
    assert mind.answer({'input': [{'content': [{'text': 'Маша, закрой дверь.'}]}]}) == '—'


@pytest.mark.parametrize('q, plan, fits', [(MONEY, 'Осталось 60 рублей.', True), (SWAPPED, 'Осталось 60 рублей.', False), (SWAPPED, 'Не хватает 60 рублей.', True),
                                           (COLD, 'Да, при таком давлении жидкость нужно охлаждать,', True), (HOT, 'Да, при таком давлении жидкость нужно охлаждать,', False),
                                           (HOT, 'Да, нужно нагревать, а не охлаждать.', True)])
def test_what_an_answer_answers(q, plan, fits):
    assert q.fits(plan) is fits


def test_a_kept_record_has_no_violation():
    out = record([said(1, 'question', 1.0, 4.0, q=MONEY, ear_at=4.3, final_at=5.0, created_at=1.5)],
                 [cue(6.0, 'Осталось 60 рублей.', 1, 0)], [(5.0, 1, 0, False, False, False, 1)])
    assert check(out) == []


def test_each_check_fires():
    q1 = said(1, 'question', 1.0, 4.0, q=MONEY, ear_at=4.3, final_at=5.0, created_at=1.5)
    q2 = said(2, 'question', 8.0, 11.0, q=SWAPPED, ear_at=11.3, final_at=12.0, created_at=8.5)
    assert 'A2' in kinds(record([q1, q2], [cue(6.0, 'Осталось 60 рублей.', 1, 0), cue(13.0, 'Осталось 60 рублей.', 1, 0)]))
    assert kinds(record([q1], [cue(6.0, 'Осталось 70 рублей.', 1, 0)])) == ['A7']
    assert 'A6' in kinds(record([q1], [cue(2.9, 'Осталось 60 рублей.', 1, 0)]))
    assert 'A6o' in kinds(record([said(1, 'question', 1.0, 4.0, q=MONEY, ear_at=4.3, final_at=5.0)], [cue(2.9, 'Осталось 60 рублей.', 1, 0)]))
    assert 'A8' in kinds(record([q1], [cue(6.0, 'Мг.', 1, 0)]))
    assert 'A1' in kinds(record([q1], [cue(6.0, 'Осталось 60 рублей.', 1, 0), cue(7.0, 'Да, при таком давлении жидкость нужно охлаждать,', 2, 0)]))
    stop = said(2, 'stop', 7.0, 7.5, ear_at=7.8, final_at=8.0)
    assert 'A2' in kinds(record([q1, stop], [cue(6.0, 'Осталось 60 рублей.', 1, 0), cue(9.0, 'Осталось 60 рублей.', 1, 0)]))
    assert 'A3' in kinds(record([q1], [cue(6.0, 'a', 1, 0, ('a', 'b'))], [(5.0, 1, 0, False, False, False, 1), (6.5, 1, 1, False, False, False, 1)]))
    assert 'A3' in kinds(record([q1], [], [(5.0, 1, 1, False, False, False, 1), (6.5, 1, 0, False, False, False, 1)]))
    assert 'A5' in kinds(record([q1], [], [(5.0, 1, 0, False, False, False, 1), (30.0, 1, 0, False, False, False, 1)]))


def test_a_resume_may_bring_the_older_answer_back():
    q1 = said(1, 'question', 1.0, 4.0, q=MONEY, ear_at=4.3, final_at=5.0)
    q2 = said(2, 'question', 8.0, 11.0, q=COLD, ear_at=11.3, final_at=12.0)
    back = said(3, 'resume', 14.0, 14.5, ear_at=14.8, final_at=15.0)
    assert 'A2' not in kinds(record([q1, q2, back], [cue(6.0, 'Осталось 60 рублей.', 1, 0), cue(15.2, 'Осталось 60 рублей.', 3, 0)]))


@pytest.mark.parametrize('seed', range(20, 32))
def test_no_exception_no_error_frame_no_two_portions_in_flight(seed):
    """A0 over a few whole conversations with faults: what the wire itself must never do, whatever the defects below."""
    out = stand.run(seed, length=60)
    assert out.crash is None and [v for v in out.violations if v[0] == 'A0'] == [], stand.describe(out)


# =====================================================================================================================================
# the findings (cloud_context/reports/a1-fuzz.md): the smallest seed of each group, cut at the violation
# =====================================================================================================================================

def found(seed, invariant, at, length):
    out = stand.run(seed, length=length)
    return [v for v in out.violations if v[0] == invariant and abs(v[1] - at) < 0.05], out


# (number, seed, invariant, time of the violation, length of the conversation cut just after it, the first cause). PATCHED: run 0:2000 of cloud_context/reports/a1-fuzz/run-2000.txt on 227f594, their patches
# are in controlled_media.py / native_media_socket.py since w3-integ item 5: each stays as a regression row. On the integrated tree before the patches only F2, F3, F6b still showed at these seeds (the
# other conversations had moved), so F1, F4, F6, F7 guard less than they did. OPEN: no patch (cloud_context/reports/a1-fuzz.md), seeds of the run on the integrated tree (w3-integ.md).
PATCHED = [
    ('F1', 30, 'A6', 86.1, 87.0, 'a first cue parked for speech the cloud has announced is held by the ear alone, 1 s (native_media_socket._speech_began)'),
    ('F2', 11, 'A2', 90.02, 91.0, 'the job of a new question fails and the older answer admitted while it was asked is said (ControlledMedia.first_cue_hold)'),
    ('F3', 288, 'A8', 36.38, 37.0, 'the cloud reply «Мг.» is admitted as the answer after the job failed (_CHATTER_WORDS)'),
    ('F4', 600, 'A3', 57.9, 58.5, 'the late number veto takes the next utterance for the ack it vetoes and rewinds the portion (ControlledMedia._ear_run_of)'),
    ('F6', 4, 'A3', 16.58, 17.0, '«дальше» said before the portion was heard skips it (ControlledMedia._going_on)'),
    ('F6b', 595, 'A3', 66.04, 67.0, 'two «дальше», one said before the portion: the cursor jumps two (ControlledMedia._going_on)'),
    ('F7', 13, 'A9', 63.84, 64.5, 'the job gets the cloud\'s words of one utterance and the ear\'s of another (ControlledMedia._ear_words)'),
    ('F8', 1206, 'A5', 71.92, 72.5, 'a question whose job failed and that the cloud left unanswered is neither answered nor reported (g3-chaos: ControlledMedia._answer_watchdog, the candidate branch)'),
    # c24-a1: the seed's own conversation no longer has that «стоп»; the minimal scene of c22-break (ddmin seed 259 for 88) is gone too (on the base it stays): see c24-a1.md
    ('F5', 88, 'A2', 21.48, 22.0, 'a «стоп» the ear heard is dropped (changed_since_onset) because an answer was admitted during it, and that answer is said (c24-a1)'),
]
# OPEN (P14, run 0:2000 on claude/one 446237b, 7469 s, 2 jobs; seeds that still show on ci/one-merge-11d + the P14 stand): the smallest seed of every invariant that is not zero. A RED test the owner of the
# family must turn green (no xfail): A2 old answer (M3), A2e old answer after the ear (M2/M3, an observation of the stand), A3 step with no utterance (M4), A5 portion said again in silence (M5/M4),
# A6o cue inside speech by the ear (M6, the 1 s ear-only hold is by design: the owner decides), A9 one request two utterances (M1). A1 (3 seeds on claude/one) no longer shows on ci/one-merge-11d.
OPEN = [
    ('O-A2', 54, 'A2', 55.86, 56.9, 'cue ’Статья 19 Налогового кодекса о налогах и сборах.’ of plan ’Статья 19 Налогового кодекса о налогах и сборах.’ answers the older question 7 ’Что го'),
    ('O-A2e', 0, 'A2e', 38.44, 39.4, 'cue ’Гагарин полетел в 1961 году.’ of another question begun after the ear heard question 7 ’В каком году было крещение Руси?’ at 37.44 (its final at'),
    ('O-A3', 670, 'A3', 20.08, 21.1, 'revision 3: advance 0 -> 1 with no utterance of its own since the portion was said at 17.78'),
    ('O-A5', 1956, 'A5', 61.6, 62.6, 'portion ’18. Это 3 раз по 6.’ said 4 times in a row with nobody speaking'),
    ('O-A6o', 28, 'A6o', 44.74, 45.7, 'cue ’Петербург основали в 1703 году.’ began at 44.74 inside utterance 9 ’Хорошо. Да, я готовился на самом деле. Если у меня было 70 рублей и я потрати'),
    ('O-A9', 375, 'A9', 34.26, 35.3, 'one request, two utterances: ’на 7? Твой ответ: 28. Это 4 раз по 7. Сейчас прозвучало: Распознано: Продолжай. / продолжай нет не четыре а четырнадца'),
]
FINDINGS = PATCHED + OPEN


@pytest.mark.parametrize('number, seed, invariant, at, length, cause', [pytest.param(*row, id=row[0]) for row in FINDINGS])
def test_a_finding_is_gone(number, seed, invariant, at, length, cause):
    hits, out = found(seed, invariant, at, length)
    assert hits == [], stand.describe(out)
