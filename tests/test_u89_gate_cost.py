"""U89 (d): the answer gate's request (``parks`` + ``handed``) costs the same on a call of 360 minutes as on one of 180: it reads the newest turns after the question, not every turn of the call
(on the laptop one request with 2250 turns after an old open question took 0.257 s against the bound of 0.25 s). The work is counted (fingerprints made), not timed: a cloud box is no laptop."""
import pytest

from echo_sync import v5_gate
from test_v6_gate_meaning_attack import long_call, cue


def work(minutes, monkeypatch):
    c, gate, turns = long_call(minutes)
    c.question_id = 'q0'      # an old question still open: the whole call lies after it
    c.ledger.turns[:] = [dict(t, text=t['text'] + ' не') if i % 3 == 0 else t for i, t in enumerate(turns)]
    made, real = [], v5_gate.fingerprint
    monkeypatch.setattr(v5_gate, 'fingerprint', lambda text: made.append(1) or real(text))
    gate.parks(cue(nonce='z', revision=999), 9999.0)
    gate.handed(cue(nonce='z', revision=999), 9999.0)
    return len(made), len(turns)


def test_the_work_of_one_request_does_not_grow_with_the_length_of_the_call(monkeypatch):
    small, n_small = work(180, monkeypatch)
    big, n_big = work(360, monkeypatch)
    assert n_big == 2 * n_small and big <= small + 4, f'{small} fingerprints on {n_small} turns, {big} on {n_big}'


def ledger_with(gate, c, revision_at, fillers):
    row = lambda i, text: {'id': i, 'role': 'user', 'valid': True, 'final': True, 'text': text}      # noqa: E731
    turns = [row('qq', 'сколько стоит билет до Казани')] + [row('f%d' % k, 'это просто разговор про погоду') for k in range(fillers)]
    turns.insert(revision_at, row('rr', 'а пятьдесят?'))
    c.ledger.turns[:] = turns
    return gate._newer('qq', before=v5_gate.fingerprint('сколько стоит билет до Казани'))


def test_a_revision_among_the_newest_turns_after_the_question_is_found():
    c, gate, _ = long_call(2)
    assert ledger_with(gate, c, 4, 6) == ['а пятьдесят?']


def test_a_question_older_than_the_window_reads_its_newest_turns_only():
    c, gate, _ = long_call(2)
    n = v5_gate._KEPT
    assert ledger_with(gate, c, 1, n + 5) == []      # the revision stands further back than the window: that question is not the one being answered
    assert ledger_with(gate, c, n // 2, n // 2) == ['а пятьдесят?']
