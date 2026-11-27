"""G2: the marathon (tools/replay/marathon.py): one call of many questions, each answered, none lost, in order; nothing grows or sticks with the number of answers."""
import pytest

from echo_sync.voice_turns import FramelessTurns


def user(tid, start):
    return {'type': 'turn.done', 'turn': {'id': tid, 'role': 'user', 'transcript': 'Вопрос.', 'start_ms': start, 'end_ms': start + 900}}


def test_a_new_answer_turn_is_not_evicted_from_a_full_ledger_because_it_has_no_clock():
    """Seed 2 at the 20th question (2552 s): 64 turns of the call, the fast channel's answer turn created without start_ms sorted as the oldest and was evicted at
    once; its turn.done came back None, ``_source(None)`` raised TypeError, and the fast channel was off for the rest of the call: 37 of 60 questions lost."""
    f = FramelessTurns(max_turns=64)
    for k in range(70):
        f.apply(user(f'u{k}', k * 5000))
        f.apply({'type': 'turn.created', 'turn': {'id': f'a{k}', 'role': 'assistant', 'transcript': ''}})
    assert f.apply({'type': 'turn.created', 'turn': {'id': 'fast-1', 'role': 'assistant', 'transcript': 'Осталось 20 рублей.'}}) is not None
    assert f.apply({'type': 'turn.done', 'turn': {'id': 'fast-1', 'role': 'assistant', 'transcript': 'Осталось 20 рублей.'}}) is not None
    assert len(f.history()) <= 64 and f.snapshot('u69') is not None


def test_the_oldest_by_arrival_goes_first_even_when_a_late_final_has_an_early_clock():
    f = FramelessTurns(max_turns=3)
    for k, start in enumerate((1000, 2000, 3000)):
        f.apply(user(f'u{k}', start))
    f.apply(user('late', 500))                        # a final that came late, of speech that began early: it is the newest thing the ledger has
    assert f.snapshot('late') is not None and f.snapshot('u0') is None


@pytest.fixture(scope='module')
def run():
    from tools.replay import marathon as M
    return M.one(2, questions=30, hours=0.5, keep=True)


def test_a_call_of_30_questions_answers_each_one_in_order(run):
    """Past the 64 turns of the ledger (seed 2, 30 questions in half an hour: the 28th, 29th and 30th were lost before the fix): every question answered in its episode, none by an older one, no crash."""
    assert run['crash'] is None
    assert run['asked'] == 30 and run['lost'] == [] and run['order'] == []


def test_nothing_is_left_up_after_an_answer(run):
    """After each answer (the episode closed, nobody speaking): no flag of speech, no stream waiting for more, no portion open, no live job, no task of the wire."""
    st = run['stand']
    assert run['stuck'] == []
    assert all(s[2]['fast.runs.alive'] == 0 and s[2]['wire.tasks.live'] == 0 for s in st.snaps)


def test_the_state_stays_bounded():
    """The controller's own maps are bounded (64/128 ids): after many answers they stop growing (seed 2: 60 answers in 2 h stay under 128)."""
    from tools.replay import marathon as M
    snaps = [(n, 0.0, {'cm.seen': min(4 * n, 128), 'cm.leak': 3 * n}, {}) for n in range(1, 61)]
    grown = M.growth(snaps)
    assert 'cm.leak' in grown and 'cm.seen' not in M.leaks(snaps)


def test_the_marathon_gives_the_logging_back(run):
    import logging
    assert logging.root.manager.disable == logging.NOTSET
