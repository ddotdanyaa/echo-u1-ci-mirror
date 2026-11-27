"""one-input U90: the answer gate in the owner's hands: a new standalone question with a number is no correction of the previous one; the ceiling of a hold never lets a cue out
over speech whose speaker is not known; a release at the ceiling is its own reason in the journal (never «pass»)."""
from echo_sync import v5_gate
from echo_sync.native_media_socket import NativeMediaSocket
from test_v5_gate_same import job_gate
from test_v5_answer_gate import Controller, Voice, Wire, cue


def test_a_new_standalone_question_with_a_number_is_no_correction():
    c, gate, a, notes = job_gate('Сколько будет сорок на два', 'Сколько будет сорок на два', 'Восемьдесят.', mode='on')
    c.ledger.turns.append({'id': 'u2', 'role': 'user', 'valid': True, 'final': True, 'text': 'Кто победил в 1812 году'})
    assert gate.handed(a, 101.0) is None
    assert notes[-1][1]['would'] == 'pass' and notes[-1][1]['newer'] == 0, 'the old answer to the old question is said'


def test_a_short_correction_with_a_number_is_still_a_correction():
    for text in ('а пятьдесят?', 'нет, пятьдесят на два', 'Сколько будет пятьдесят на два'):
        assert v5_gate.revising(text), text
    assert not v5_gate.revising('Кто победил в 1812 году') and not v5_gate.revising('А когда родился Пушкин в 1799 году')


def ceiling_socket(kind, notes):
    """The real ``NativeMediaSocket._v5_held`` over a gate (on): a clock the test moves, a controller whose speaker gate says ``kind``."""
    c = Controller(hearing=True, **({'speaker_gate': Voice(kind)} if kind else {}))
    sock = NativeMediaSocket.__new__(NativeMediaSocket)
    sock.t, sock.release_timer, sock.release_at, sock.controller = 100.0, None, 0.0, c
    sock.clock = lambda: sock.t
    sock.v5_gate = v5_gate.attach({'v5_answer_gate': 'on'}, c, Wire(), note=lambda ev, **f: notes.append((ev, f)))
    return sock


def test_the_ceiling_never_releases_a_cue_over_speech_of_an_unknown_speaker():
    notes = []
    sock, a = ceiling_socket(None, notes), cue(first=True)
    for t in (100.0, 102.0, 103.0, 105.0, 109.0):
        sock.t = t
        assert sock._v5_held(a, 'speech_with_content') is True, t
    sock.v5_gate.handed(a, 110.0)
    assert notes[-1][1]['would'] == 'release_earlier' and notes[-1][1]['speaker'] == 'unknown'


def test_the_ceiling_exit_over_a_voice_known_to_be_somebody_elses_is_its_own_reason():
    notes = []
    sock, a = ceiling_socket('other', notes), cue(first=True)
    assert sock._v5_held(a, 'speech_with_content') is True
    sock.t = 101.0
    assert sock._v5_held(a, 'speech_with_content') is False, 'the cap of a voice known to be somebody else\'s'
    sock.v5_gate.handed(a, 101.0)
    assert notes[-1][1]['would'] == 'ceiling' and notes[-1][1]['code'] != 'pass' and notes[-1][1]['held_s'] == 1.0
