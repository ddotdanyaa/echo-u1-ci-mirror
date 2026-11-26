"""V1a U90: «the answer gate stays in the shadow»: switched on it let a cue out over speech at the 3 s ceiling (132-180 times in a long call against 0-1), the journal wrote «pass» for that exit, and a new standalone question with
a number was taken for a correction of the previous one.

Fixed in the code by a732bb1b / dd701425 (the ceiling exit is its own reason, never a cue over unknown speech, a new standalone question is no correction); the guards of the gate itself are tests/test_one_u90_gate.py (the pure
gate over a stub controller). These are the same acceptance on the REAL ControlledMedia and the real wire: the rig ``call`` with ``v5_answer_gate=on`` and the gate attached as the host attaches it (``v5_gate.attach``), the
others' speech as the cloud streams it (turn.created, a delta per word, turn.done), the job's answer scripted. Not run on the laptop. The «replay of the calls of 11 Nov: questions without an answer in 5 s no more than 10» of the row
is a measurement on recorded audio (the stand of I1): not here. The rule: the gate stays in ``shadow`` on the server until the owner says (not for the tests to change).
"""
from echo_sync import v5_gate
import helpers_s6_state as S
from kind_a_kit import TICK, pending_jobs
from test_h3_tempo import call      # noqa: F401 - the fixture
from test_h5_live import asked

CEILING = v5_gate.COSTS['hold_unknown_s']


def gated(call):
    rig = call(fast_text='on', max_auto_repeats=3, v5_answer_gate='on')
    notes = []
    rig.w.wire.v5_gate = v5_gate.attach(rig.settings, rig.c, rig.w.wire, note=lambda ev, **f: notes.append((ev, f)))
    return rig, notes


def test_in_a_long_call_no_cue_begins_over_the_speech_of_others_and_no_ceiling_exit_is_called_pass(call):
    rig, notes = gated(call)
    windows = []
    for k in range(6):
        since = len(rig.fake.runs)
        asked(rig, f'А какая столица страны номер {k + 1}', uid=f'q{k}')
        t0 = rig.w.clock.t
        uid = rig.onset()                                    # the others begin to speak: the live profile's own ear hears them (the cloud's events alone are no speech to a call whose tempo the ear keeps)
        rig.w.feed(S.turn_created(f's{k}', 'user', 'Ну'))
        for n in pending_jobs(rig, since):
            rig.job_says(n, f'Город номер {k + 1}.')
            rig.job_ends(n)
        words = 'ну вот мы вчера говорили про отчётность и про то как нам быть дальше'.split()
        for n in range(10):                                  # 5 s of content: past the 3 s ceiling of the gate
            rig.w.feed(S.turn_delta(f's{k}', ' ' + words[n], n))
            rig.pump(0.5)
        windows.append((t0 + 0.2, rig.w.clock.t))
        rig.offset()
        rig.w.feed(S.turn_done(f's{k}', 'user', ' '.join(words)))
        rig.worker.heard(uid, ' '.join(words))
        rig.pump(9.0)
    over = [(c.text, round(c.t, 1)) for c in rig.cues() for a, b in windows if a < c.t < b]
    assert over == [], f'a cue began over the speech of others: {over}'
    verdicts = [f for ev, f in notes if ev == 'v5_gate']
    assert verdicts, 'the gate was told of the cues'
    wrongly_pass = [v for v in verdicts if v['would'] == 'pass' and v['held_s'] > CEILING and v['speaker'] != 'owner']
    assert wrongly_pass == [], wrongly_pass


def test_a_new_standalone_question_with_a_number_is_no_correction_of_the_one_before(call):
    """«Сколько будет сорок на два» is asked, then «Кто победил в 1812 году»: the second is a question of its own, it revises nothing (``newer`` is 0 in every verdict) and its answer is the one that sounds."""
    rig, notes = gated(call)
    asked(rig, 'Сколько будет сорок на два', uid='u1')
    for n in pending_jobs(rig, 0):
        rig.job_says(n, 'Восемьдесят.')
        rig.job_ends(n)
    rig.pump(6.0)
    since = len(rig.fake.runs)
    asked(rig, 'Кто победил в 1812 году', uid='u2')
    for n in pending_jobs(rig, since):
        rig.job_says(n, 'Победила Россия.')
        rig.job_ends(n)
    rig.pump(6.0)
    verdicts = [f for ev, f in notes if ev == 'v5_gate']
    assert all(v['newer'] == 0 for v in verdicts), verdicts
    assert any('Россия' in text for text in rig.said()), rig.said()
    assert 'Восемьдесят.' in rig.said(), 'the first answer was said as well: nothing took the second for its correction'
