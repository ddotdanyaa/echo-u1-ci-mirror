"""P14 / stand scoring fixes (tools/rehearsal/score.py, sim.py, tools/replay/stand.py): errors of the stand's own scorer, never of the product.
Each case is a record built for it (the board counts what it is given) or a real rehearsal through the real controller (``sim.play``)."""
import logging

from tools.rehearsal import plan as P
from tools.rehearsal import score, sim
from tools.replay import stand as ST
from tools.replay.stand import Outcome, Said

Q1 = P.Fact('num', ('a',), 'Сколько дней в високосном году?', 'В високосном году 366 дней.')
Q2 = P.Fact('num', ('b',), 'Сколько часов в неделе?', 'В неделе 168 часов.')
Q3 = P.Fact('num', ('c',), 'Сколько секунд в минуте?', 'В минуте 60 секунд.')


def said(n, kind, text, onset, offset, meaning=None, who='friend', final=True):
    u = Said(n, kind, text, text.lower(), onset, offset, ear_at=offset + 0.2, final_at=offset + 2.0 if final else None, meaning=meaning)
    u.who = who
    return u


def cue(t, text, rev=1, index=0):
    return (t, text, rev, index, (text,), False, False, None)


def out_of(said_, cues, states=(), jobs=(), errors=()):
    out = Outcome(1, {'rehearsal': 'Р000'})
    out.said, out.cues, out.states, out.jobs, out.errors = said_, cues, list(states), list(jobs), list(errors)
    return out


def test_an_answer_cued_before_the_cancel_is_no_false_cue_but_one_after_it_is():
    asked = [said(1, 'question', Q1.text, 1.0, 3.0, ('q', Q1))]
    before = out_of(asked, [cue(5.0, Q1.reply)])
    before.cancelled = {1: 8.0}                              # «неважно» at 8.0
    assert score.board(before)[0]['false_cue'] == 0
    after = out_of(asked, [cue(9.0, Q1.reply)])
    after.cancelled = {1: 8.0}
    assert score.board(after)[0]['false_cue'] == 1


def test_a_real_rehearsal_records_when_each_cancel_began():
    out = sim.play(sim.Spec('Р054'), 0, keep_log=False)
    assert out.cancelled and all(isinstance(at, float) for at in out.cancelled.values()), out.cancelled
    assert all(n in {u.n for u in out.said} for n in out.cancelled)


def test_the_earliest_unused_utterance_pays_for_an_advance():
    """Two repeats in one window (6.0 and 8.0) and two advances: the first advance takes the earlier repeat, the second the later one. Taking the LAST left the second with none."""
    friend = said(1, 'question', Q1.text, 0.5, 1.0, ('q', Q1))
    first, second = said(2, 'repeat', 'повторяю', 6.0, 6.5, None, 'user'), said(3, 'repeat', 'ещё раз', 8.0, 8.5, None, 'user')
    cues = [cue(5.0, 'a', 1, 0), cue(7.0, 'b', 1, 1)]
    states = [(5.0, 1, 0, False, False, False, 1), (9.0, 1, 1, False, False, False, 1), (14.0, 1, 2, False, False, False, 1)]
    m, eps = score.board(out_of([friend, first, second], cues, states))
    assert m['false_step'] == 0, eps


def test_the_a3_check_of_the_stand_also_takes_the_earliest_utterance():
    friend = said(1, 'question', Q1.text, 0.5, 1.0, ('q', Q1))
    first, second = said(2, 'repeat', 'повторяю', 6.0, 6.5, None, 'user'), said(3, 'repeat', 'ещё раз', 8.0, 8.5, None, 'user')
    out = out_of([friend, first, second], [cue(5.0, 'a', 1, 0), cue(7.0, 'b', 1, 1)],
                 [(5.0, 1, 0, False, False, False, 1), (9.0, 1, 1, False, False, False, 1), (14.0, 1, 2, False, False, False, 1)])
    assert not [x for x in ST.check(out) if x[0] == 'A3'], ST.check(out)


def test_a_question_whose_cloud_final_was_lost_does_not_open_an_endless_a2e_window():
    """q2's cloud final is lost; a later question q4 repeats q1 and its answer is said at 100 s: that is the answer of the last question, not an older answer after the ear."""
    q1 = said(1, 'question', Q1.text, 1.0, 3.0, ('q', Q1))
    q2 = said(2, 'question', Q2.text, 40.0, 42.0, ('q', Q2), final=False)
    q3 = said(3, 'question', Q3.text, 60.0, 62.0, ('q', Q3))
    q4 = said(4, 'question', Q1.text, 90.0, 92.0, ('q', Q1))
    out = out_of([q1, q2, q3, q4], [cue(100.0, Q1.reply)])
    assert [x for x in ST.check(out) if x[0] == 'A2e'] == [], ST.check(out)
    inside = out_of([q1, q2, q3, q4], [cue(50.0, Q1.reply)])          # the same answer inside the window of the lost final is still an old answer after the ear
    assert [x for x in ST.check(inside) if x[0] == 'A2e'], ST.check(inside)


def test_a_question_whose_model_the_stand_killed_is_counted_apart_when_the_error_frame_was_said():
    friend = said(1, 'question', Q1.text, 1.0, 3.0, ('q', Q1))
    later = said(2, 'question', Q2.text, 40.0, 42.0, ('q', Q2))
    jobs = [{'at': 3.1, 'heard': Q1.text, 'answer': None, 'first': 20.0, 'fail': False, 'mixed': False}]
    told = out_of([friend, later], [cue(45.0, Q2.reply)], jobs=jobs, errors=[{'error': {'code': 'controlled_answer_failed'}}])
    m, _ = score.board(told)
    assert (m['missed'], m['model_down']) == (0, 1), m
    silent = out_of([friend, later], [cue(45.0, Q2.reply)], jobs=jobs, errors=[])
    m, _ = score.board(silent)
    assert (m['missed'], m['model_down']) == (1, 0), m                  # no error frame: the silence is a real miss


def test_a_missed_question_says_whether_anything_was_said():
    friend = said(1, 'question', Q1.text, 1.0, 3.0, ('q', Q1))
    later = said(2, 'question', Q2.text, 40.0, 42.0, ('q', Q2))
    spoken = (12.0, 'Не удалось ответить.', 1, 0, ('Не удалось ответить.',), False, True, None)       # a diagnostic cue (index 6): the timeout phrase
    m, _ = score.board(out_of([friend, later], [spoken, cue(45.0, Q2.reply)]))
    assert m['missed'] == 1 and m['missed_silent'] == 0
    m, _ = score.board(out_of([friend, later], [cue(45.0, Q2.reply)]))
    assert m['missed'] == 1 and m['missed_silent'] == 1


def test_a_real_rehearsal_with_a_killed_model_has_no_miss_for_it():
    logging.disable(logging.WARNING)
    try:
        out = sim.play(sim.Spec('Р054'), 0, keep_log=False)
    finally:
        logging.disable(logging.NOTSET)
    m, _ = score.board(out)
    assert any(str((f.get('error') or {}).get('code', '')).startswith('controlled_') for f in out.errors)
    assert m['model_down'] >= 1 and m['missed'] == 0, m


def test_the_worst_list_shows_every_kind_there_is():
    eps = [{'kind': kind, 'seed': seed, 'rehearsal': 'Р001', 't': 1.0, 'what': '', 'cause': ''} for kind in ('old_answer', 'missed', 'false_cue') for seed in range(30)]
    top = score.worst(eps, n=6)
    assert {e['kind'] for e in top} == {'old_answer', 'missed', 'false_cue'}
    assert len(score.kept(eps, per=3)) == 9


def test_a_comparison_on_few_seeds_says_it_is_noise_and_names_the_proof():
    from tools.rehearsal import run as R
    one = sim.play(sim.Spec('Р001'), 0, keep_log=False)
    board = {'Р001': score.total([score.board(one)[0]])}
    base = {'head': 'aaa', 'flags': '', 'seeds': 2, 'seed0': 0, 'cap': 1, 'jobs': 1, 'mutant': None, 'wall': 1, 'long_seeds': None, 'boards': board, 'worst': [], 'red': []}
    few = R.compare(base, {**base, 'head': 'bbb'})
    assert 'ШУМ: сидов 2 < 20' in few and 'tools.rehearsal.shrink' in few
    many = R.compare({**base, 'seeds': 100}, {**base, 'head': 'bbb', 'seeds': 100})
    assert 'ШУМ' not in many and 'tools.rehearsal.shrink' in many
