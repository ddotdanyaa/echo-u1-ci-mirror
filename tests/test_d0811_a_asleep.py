"""Lane A (13.11, map §7.4/§8.4/§8.2 item 2): the waiting portion yields to a new question by quantity, and never holds the call for ever.

The call of 13.11 08:11 (class K7 from the other side, c8b): a portion nobody repeated stayed «waiting» and every later question was judged
against it and dropped as unrelated speech. The lock is three numbers in ``ControlledMedia._abandons`` (the one owner of «the portion yields»):
ABANDON_SECONDS (the portion's clock runs from its last cue or the listener's last try), ABANDON_SHARE (what share of the words said is the
portion's own: more is a try that failed, less is talk) and ABANDON_FINALS (finals of other speech that show it). After the auto-repeats spent
their cap the clock runs from the last try only. Under the dictation cycle (h28, ruling 8.2.2) the clock alone never retires the portion.
All phrases are made up (the structure of the recorded ones, none of their words).
"""
import logging

import pytest

from echo_sync.classifier import QUESTION, QUIET, analyze, portion_share
from helpers_w1f import Wire

Q = ' Что такое амортизация?'
A = ' Амортизация это постепенный перенос стоимости имущества на расходы.'
# long talk (>= 12 words) with ONE word of the portion's own («стоимость»): not a try at it
SHARED = ' Стоимость билетов на электричку опять выросла с понедельника и теперь мы ездим на работу на автобусе'
# long talk with none
APART = ' Мы вчера ходили в кино там было шумно и душно и все разговаривали весь сеанс'
# a made-up definition question whose form is not a question word: with a portion waiting it is «unrelated», with nothing waiting a question
FIVE_Q, FIVE_A = ' Что такое срок хранения документов?', ' Пять лет с конца отчётного года.'
FORMLESS = ' так вот штраф за кассовую книгу'
TRY = ' постепенный перенос стоимости'
YEAR_TALK = ' В прошлом году мы ездили на дачу и копали картошку и потом ещё долго чинили забор у соседей'
LIVE = {}     # the head of the journal of 08:11 (the cap 3 is ``max_auto_repeats``)


def lake(tmp_path, question=Q, answer=A, flags=None, **overrides):
    w = Wire(tmp_path, **overrides)
    if flags:
        w.c.settings = {**(w.c.settings or {}), **flags}
        w.c.engine.settings = w.c.settings
    w.user('u1', question, 0.0, 1.5)
    w.assistant('a1', answer, 1.6, 2.4)
    return w


def writing(w):
    """U141: the owner is WRITING, told from their speech: they went on from two places of this answer (the record state is earned in LIVE). No key brings the cycle."""
    w.until(3.0)
    w.c.record_seen = (w.state()['revision'], {0, 1})


def waits(w):
    state = w.state()
    return bool(state.get('chunks')) and not state.get('completed') and state.get('chunk_index') == 0


def lines(caplog, what):
    return [r.getMessage() for r in caplog.records if what in r.getMessage()]


def verdict(w, text):
    decision = analyze(text, w.state(), [], w.c.settings)
    return decision.kind, decision.reason


def test_one_shared_word_in_long_talk_does_not_hold_the_portion(tmp_path, caplog):
    """A1: no cap, no cycle: the clock runs from the cue; a talk with one word of the portion in it is not a try that restarts it."""
    caplog.set_level(logging.INFO, logger='echo-sync')
    w = lake(tmp_path, max_auto_repeats=0)
    w.until(7.0)
    assert waits(w) and w.played, w.played
    assert w.played[0][0] < 4.0, w.played
    assert verdict(w, SHARED)[0] == QUIET, verdict(w, SHARED)
    assert (portion_share(SHARED, w.state(), w.c.settings) or 0.0) < 0.34
    w.user('t1', SHARED, 8.0, 10.0)
    w.user('t2', SHARED, 24.0, 26.0)
    w.until(27.0)
    assert not waits(w) and w.state().get('completed'), w.state()
    gone = lines(caplog, 'reason=portion_abandoned')
    assert len(gone) == 1 and 'tried=False' in gone[0], gone
    assert any('portion_asleep path=clock' in line for line in lines(caplog, 'portion_asleep')), lines(caplog, 'portion_asleep')


def test_after_the_cap_one_content_final_yields_the_portion(tmp_path, caplog):
    """A2: the head of 08:11 (cap 3, the plain pace: the cycle needs the owner's speech, U141). The repeats spent the cap, nobody tried: one final of other speech is enough."""
    caplog.set_level(logging.INFO, logger='echo-sync')
    w = lake(tmp_path, flags=LIVE, max_auto_repeats=3)
    w.until(40.0)      # U141: no cycle until the owner's speech shows they write, so the repeats keep the plain pace (cue 2.3 s, then 6 s apart) and spend the cap by 21 s
    mark = w.c.abandon
    assert mark is not None and mark['capped'] is not None, mark         # precondition: the repeats spent the cap (the cue, then three repeats)
    assert waits(w) and len(w.played) == 4, w.played
    assert verdict(w, SHARED)[0] == QUIET and (portion_share(SHARED, w.state(), w.c.settings) or 0.0) < 0.34
    at = w.now + 2.0                  # the wire sets its clock to an event no earlier than now; the speech starts after the cap
    w.user('t1', SHARED, at, at + 1.5)         # one word of the portion in a long talk is no try: before, it marked the portion «tried» for good
    w.until(at + 3.0)
    assert not waits(w) and w.state().get('completed'), w.state()
    gone = lines(caplog, 'reason=portion_abandoned')
    assert len(gone) == 1 and 'tried=False' in gone[0], gone
    assert any('portion_asleep path=cap' in line for line in lines(caplog, 'portion_asleep')), lines(caplog, 'portion_asleep')


def test_the_yielding_final_is_judged_again_as_when_nothing_waits(tmp_path, caplog):
    """A3: the redo. With the portion waiting the final is silence (mismatch_policy_silent); once the portion yields it is judged again as
    when nothing waits, and it is a question."""
    caplog.set_level(logging.INFO, logger='echo-sync')
    w = lake(tmp_path, question=FIVE_Q, answer=FIVE_A, flags={}, max_auto_repeats=0)
    w.until(7.0)
    assert waits(w) and w.played, w.state()
    waiting, empty = analyze(FORMLESS, w.state(), [], w.c.settings), analyze(FORMLESS, {}, [], w.c.settings)
    assert waiting.kind != QUESTION and empty.kind == QUESTION, (waiting, empty)      # precondition: the portion is what silences it
    assert verdict(w, YEAR_TALK)[0] == QUIET
    w.user('t1', YEAR_TALK, 8.0, 10.0)                  # one word of the portion in it: before, a try for good
    w.until(20.0)
    assert waits(w), w.state()
    w.user('q2', FORMLESS, 26.0, 28.0)
    w.until(30.0)
    assert w.c.question_id == 'q2', w.c.question_id
    assert len(lines(caplog, 'reason=portion_abandoned')) == 1
    assert len([line for line in lines(caplog, 'judge tid=q2')]) == 2, lines(caplog, 'judge tid=q2')      # silent first, a question once the portion yielded
    assert len(lines(caplog, 'resolution tid=q2')) >= 1 and 'cause=redo' in ' '.join(lines(caplog, 'resolution tid=q2')), lines(caplog, 'resolution')


def test_the_dictation_clock_alone_never_retires_the_portion(tmp_path, caplog):
    """A4 (h28, ruling 8.2.2): under the cycle of a writing owner (U141, from speech), with the cap out of reach, 50 s of talk around the owner keep the portion."""
    caplog.set_level(logging.INFO, logger='echo-sync')
    w = lake(tmp_path, flags={**LIVE, 'cycle_max_repeats': 30}, max_auto_repeats=3)
    writing(w)
    for k in range(8):
        w.user(f'b{k}', APART, 5.0 + 6.0 * k, 7.0 + 6.0 * k)
    w.until(58.0)
    assert waits(w), w.state()
    assert not lines(caplog, 'reason=portion_abandoned')


def test_mostly_the_portions_words_long_after_the_cue_keep_it(tmp_path):
    """A5: a final of mostly the portion's own words is a try that failed, however long after the cue."""
    w = lake(tmp_path, max_auto_repeats=0)
    mostly = ' Амортизация это постепенный перенос стоимости ну я понял про имущество вообще всё ясно мне теперь'
    w.until(24.0)
    assert (portion_share(mostly, w.state(), w.c.settings) or 0.0) >= 0.34
    assert verdict(w, mostly)[0] == QUIET, verdict(w, mostly)
    w.user('t1', mostly, 25.0, 27.0)
    w.until(28.0)
    assert waits(w), w.state()
    assert w.c.abandon['engaged'] is not None and w.c.abandon['engaged'] >= 25.0, w.c.abandon


@pytest.mark.parametrize('after,gone', [(19.0, False), (21.0, True)])
def test_the_clock_boundary_moves_with_abandon_seconds(tmp_path, after, gone):
    """A6: T: 19 s after the cue it waits, 21 s after it yields; the constant moves the border."""
    w = lake(tmp_path, max_auto_repeats=0)
    w.until(4.0)
    cue = w.c.cue_window[0]
    w.user('b1', APART, cue + after - 1.5, cue + after)
    w.until(cue + after + 1.0)
    assert (not waits(w)) is gone, (after, w.state())


def test_the_clock_border_is_the_constant(tmp_path, monkeypatch):
    import cm_patch
    cm_patch.patch_controller(monkeypatch, 'ABANDON_SECONDS', 25.0)
    w = lake(tmp_path, max_auto_repeats=0)
    w.until(4.0)
    cue = w.c.cue_window[0]
    w.user('b1', APART, cue + 19.5, cue + 21.0)
    w.until(cue + 22.0)
    assert waits(w), w.state()


def test_the_share_boundary_moves_with_abandon_share(tmp_path, monkeypatch):
    """A7: K: a final with a third of its content the portion's is a try at 0.30 (the portion is kept), talk at 0.34 (it yields)."""
    import cm_patch
    third = ' Так вот стоимость билетов и расходы на электричку выросли в городе и мы как бы ну уже'      # six content stems, two of them the portion's
    w = lake(tmp_path, max_auto_repeats=0)
    w.until(4.0)
    share = portion_share(third, w.state(), w.c.settings)
    assert share is not None and 0.30 <= share < 0.34, share      # between the two borders
    cue = w.c.cue_window[0]
    w.user('b1', third, cue + 21.0, cue + 22.5)
    w.until(cue + 23.5)
    assert waits(w), w.state()
    (tmp_path / 'again').mkdir()
    again = lake(tmp_path / 'again', max_auto_repeats=0)
    cm_patch.patch_controller(monkeypatch, 'ABANDON_SHARE', 0.34)
    again.until(4.0)
    cue = again.c.cue_window[0]
    again.user('b1', third, cue + 21.0, cue + 22.5)
    again.until(cue + 23.5)
    assert not waits(again), again.state()


def test_one_final_is_enough_after_the_clock(tmp_path, caplog):
    """A8: J = 1: one final of talk 22 s after the cue retires the portion (before, the second one did)."""
    caplog.set_level(logging.INFO, logger='echo-sync')
    w = lake(tmp_path, max_auto_repeats=0)
    w.until(4.0)
    cue = w.c.cue_window[0]
    w.user('b1', APART, cue + 20.5, cue + 22.0)
    w.until(cue + 23.0)
    assert not waits(w), w.state()
    assert len(lines(caplog, 'reason=portion_abandoned')) == 1


def test_a_try_just_before_the_talk_keeps_it_after_the_cap(tmp_path):
    """The cap spent, a try 10 s ago: the clock of the try (T) has not run, the talk of a bystander does not retire the portion."""
    w = lake(tmp_path, flags=LIVE, max_auto_repeats=3)
    w.until(40.0)
    mark = w.c.abandon
    assert mark is not None and mark['capped'] is not None, mark
    at = w.now + 2.0                  # the wire sets its clock to an event no earlier than now: a past instant would put the try and the talk at one moment
    attempt = analyze(TRY, w.state(), [], w.c.settings)
    assert attempt.kind == QUIET and w.c._tries(attempt, w.c._effective_reason(TRY, w.state(), attempt)), attempt      # precondition: a try at the portion
    w.user('t1', TRY, at, at + 1.0)
    w.user('b1', APART, at + 8.0, at + 10.0)
    w.until(at + 12.0)
    assert waits(w), w.state()


def test_a_try_long_ago_does_not_keep_it_after_the_cap(tmp_path, caplog):
    """Under the cycle after the cap the clock of the LAST TRY (T) is the only one: a try 25 s ago is old, one talk of a bystander yields the portion."""
    caplog.set_level(logging.INFO, logger='echo-sync')
    w = lake(tmp_path, flags=LIVE, max_auto_repeats=3)
    w.until(40.0)
    mark = w.c.abandon
    assert mark is not None and mark['capped'] is not None, mark
    at = w.now + 2.0
    attempt = analyze(TRY, w.state(), [], w.c.settings)
    assert attempt.kind == QUIET and w.c._tries(attempt, w.c._effective_reason(TRY, w.state(), attempt)), attempt
    w.user('t1', TRY, at, at + 1.0)
    w.user('b1', APART, at + 25.0, at + 27.0)
    w.until(at + 29.0)
    assert not waits(w), w.state()
    assert any('portion_asleep path=cap' in line for line in lines(caplog, 'portion_asleep')), lines(caplog, 'portion_asleep')


@pytest.mark.xfail(strict=True, reason='lane «Классификатор» (after the acceptance of B): a waiting portion that is 14 s old and not repeated '
                   'loses the right to silence a new question; lane A never retires it by the clock under the dictation cycle (h28, 8.2.2)')
def test_a_formless_question_while_an_old_portion_waits_under_the_cycle(tmp_path):
    """A7 of the review (the shape of Q7 of 08:11): the cycle on, no cap in reach, the portion 14 s old and unrepeated; a definition question
    without a question word is silenced as «unrelated» while a portion waits, and is a question with none. Still red until the classifier lane."""
    w = lake(tmp_path, question=FIVE_Q, answer=FIVE_A, flags={**LIVE, 'cycle_max_repeats': 30},
             max_auto_repeats=3)
    writing(w)
    w.until(14.0)
    assert waits(w), w.state()
    waiting, empty = analyze(FORMLESS, w.state(), [], w.c.settings), analyze(FORMLESS, {}, [], w.c.settings)
    assert waiting.kind != QUESTION and empty.kind == QUESTION, (waiting, empty)      # precondition
    w.user('q2', FORMLESS, 14.5, 16.0)
    w.until(18.0)
    assert w.c.question_id == 'q2', w.c.question_id


DISPUTE = ' Да нет, стоимость же никуда не девается, вы тут какие-то глупости выдумываете и сами это отлично знаете'


def test_a_dispute_of_the_answer_with_a_word_of_it_is_no_talk_around_it(tmp_path, caplog):
    """A9 (scene n2_d15, step 10): the listener argues with the waiting answer, opening on a negation and with one word of it in the speech. It is
    addressed to the answer, not moved on from it: after the cap it restarts the clock like a try that failed (before the share the one word did)."""
    caplog.set_level(logging.INFO, logger='echo-sync')
    w = lake(tmp_path, flags=LIVE, max_auto_repeats=3)
    w.until(40.0)      # U141: no cycle until the owner's speech shows they write, so the repeats keep the plain pace (cue 2.3 s, then 6 s apart) and spend the cap by 21 s
    mark = w.c.abandon
    assert mark is not None and mark['capped'] is not None and waits(w), (mark, w.played)
    assert verdict(w, DISPUTE)[0] == QUIET and 0.0 < (portion_share(DISPUTE, w.state(), w.c.settings) or 0.0) < 0.30
    at = w.now + 2.0                  # the wire sets its clock to an event no earlier than now; the speech starts after the cap
    w.user('t1', DISPUTE, at, at + 1.5)
    w.until(at + 3.0)
    assert waits(w), w.state()
    assert not lines(caplog, 'reason=portion_abandoned') and not lines(caplog, 'portion_asleep'), lines(caplog, 'portion_asleep')


ASKS = ' Угу, ага, понятно. А можно какой-нибудь простой пример с материалами или с товаром'


def test_speech_that_asks_the_prompter_for_something_does_not_put_the_portion_to_sleep(tmp_path, caplog):
    """A10 (scene n1_01, step 6): a backchannel and then «А можно … пример» long after the last try is a request, not talk around the portion."""
    caplog.set_level(logging.INFO, logger='echo-sync')
    w = lake(tmp_path, flags=LIVE, max_auto_repeats=3)
    w.until(40.0)      # U141: no cycle until the owner's speech shows they write, so the repeats keep the plain pace (cue 2.3 s, then 6 s apart) and spend the cap by 21 s
    mark = w.c.abandon
    assert mark is not None and mark['capped'] is not None and waits(w), (mark, w.played)
    at = w.now + 2.0                  # the wire sets its clock to an event no earlier than now; the speech starts after the cap
    w.user('t1', ASKS, at, at + 1.5)
    w.until(at + 3.0)
    assert waits(w), w.state()
    assert not lines(caplog, 'portion_asleep'), lines(caplog, 'portion_asleep')
