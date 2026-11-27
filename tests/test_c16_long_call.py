"""c16: a long call. level1-a, question 17 of 30 (6 Nov 08:36): `fast_text pump failed reason=TypeError`, the channel out for the rest of the call. The ledger holds 64 turns and evicts the one that sorts first, a job's turn
has no ``start_ms`` and sorts first of all: with the ledger full the new job's own turn went, its text was lost, and `_fast_close` read None. The logic only: nothing here is a measurement of a call."""
import helpers_s6_state as S
from echo_sync.voice_turns import FramelessTurns
from test_h3_tempo import TICK, call       # noqa: F401 - call is the fixture

ANSWER = 'Бухгалтерский баланс — отчёт об имуществе организации и источниках его формирования.'


def said_turns(rig, count):
    """What a long call leaves in the ledger: turns of the cloud with their place on its clock."""
    for n in range(count):
        ms = 1000 + 500 * n
        rig.w.feed({'type': 'turn.created', 'turn': {'id': f'a{n}', 'role': 'assistant', 'transcript': '', 'start_ms': ms}})
        rig.w.feed({'type': 'turn.done', 'turn': {'id': f'a{n}', 'role': 'assistant', 'transcript': 'Ага.', 'start_ms': ms, 'end_ms': ms + 100}})


def asked(rig, tid='q1', text='Что такое бухгалтерский баланс'):
    rig.w.feed({'type': 'turn.created', 'turn': {'id': tid, 'role': 'user', 'transcript': 'Что', 'start_ms': 100000}})
    rig.w.feed({'type': 'turn.done', 'turn': {'id': tid, 'role': 'user', 'transcript': text, 'start_ms': 100000, 'end_ms': 101000}})
    rig.pump(TICK * 2)


def test_the_job_of_a_full_ledger_is_said_and_the_channel_stays(call):
    rig = call(fast_text='on')
    said_turns(rig, 70)
    asked(rig)
    rig.job_says(0, ANSWER)
    rig.job_ends(0)
    rig.pump(1.0)
    assert any('отчёт об имуществе' in text for text in rig.said()), rig.said()
    assert rig.c.fast_on and rig.fast.off is False, 'the channel lives on'


def test_the_ledger_evicts_the_oldest_by_arrival_and_not_a_turn_with_no_clock():
    ledger = FramelessTurns(max_turns=3)
    for n in range(3):
        ledger.apply({'type': 'turn.done', 'turn': {'id': f't{n}', 'role': 'user', 'transcript': 'да', 'start_ms': 1000 + n}})
    ledger.apply({'type': 'turn.created', 'turn': {'id': 'job', 'role': 'assistant', 'transcript': 'текст'}})
    assert ledger.snapshot('job') is not None and ledger.snapshot('t0') is None
