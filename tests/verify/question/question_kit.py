"""V2 kit: what the verify tests of ``tests/verify/question`` share (the family «question»: opening, parts, follow-ups, late and stale answers, the question beside an answer in play).

Nothing here decides anything. It drives the REAL ControlledMedia through the REAL NativeMediaSocket, ShadowEar and FastText channel of the rig ``call`` of ``test_h3_tempo`` (the speech detector, the recognizer's
worker, the cloud's events and the job's stream are scripted; the clock is the world's). No number here is a measurement of a call, a laptop or a phone.
"""
import os
import sys

_TESTS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _TESTS not in sys.path:
    sys.path.insert(0, _TESTS)

import helpers_s6_state as S                                              # noqa: E402
from echo_sync import ear_shadow                                          # noqa: E402
from echo_sync import fast_text as FT                                     # noqa: E402
from echo_sync.engine import UNASKED                                      # noqa: E402
from echo_sync.textutil import normalize                                  # noqa: E402
from helpers_fast_fake import two_asks                                    # noqa: E402
from test_h3_tempo import GRID, TICK, Recognizer, call                    # noqa: E402,F401 - call is the fixture of the directory
from test_h5_live import LIVE, asked, cloud, decisions, fails, piece, plan, said_to_the_room, spoken_failures      # noqa: E402,F401
from test_h6 import BAPTISM, INERTIA, NOTICE, RIGHT, TWO_NOTICE, job_declines, remark      # noqa: E402,F401
from test_h7 import CALL_1027, HEAD_89, NO_89, SAID_15, SAID_89, job_answers, partial, said_with_a_delegation      # noqa: E402,F401

LIVE_RULES = dict(LIVE)                                                   # the profile of the working call as the other tests of the family build it
WIDE = {'fast_text': 'on', 'prepare_wide': 'on', 'tempo': None}           # as test_h7: a job on a stable partial of the cloud

ACCOUNT = 'Как отразить покупку материалов'
MATERIALS = 'Купили материалы за 10 000 рублей: дебет счёта материалов, кредит счёта денег.'
AMORT = 'Что такое амортизация'
AMORT_ANSWER = 'Амортизация — постепенный перенос стоимости на расходы.'
LONG_ANSWER = 'Срок уплаты налога через десять дней. Ставка налога двадцать процентов. Платёж вносится в бюджет.'
LONG_ASKED = 'Когда платить налог'


def user_turn(rig, uid, text, wait=0.5):
    """The cloud's user turn: its start, ``wait`` seconds, its final."""
    rig.w.feed(S.turn_created(uid, 'user', ''))
    rig.pump(wait)
    rig.w.feed(S.turn_done(uid, 'user', text))
    rig.pump(TICK * 2)


def job_text(rig, n):
    """What the speaker said, of the job's input (with an answer in play the job also gets the exchange above it)."""
    return rig.fake.run(n).question.rsplit('Сейчас прозвучало: ', 1)[-1]


def job_input(rig, n):
    """The whole input of the job, the exchange before it included."""
    return rig.fake.run(n).question


def answered(rig, n, text):
    rig.job_says(n, text)
    rig.job_ends(n)
    rig.pump(TICK * 2)


def heard(rig, key):
    return any(key in text for text in rig.said())


def history(rig):
    return list((rig.c.state() or {}).get('history') or [])


def entry_of(rig, key):
    """The newest history entry whose question holds ``key``, else None."""
    for entry in reversed(history(rig)):
        if isinstance(entry, dict) and key in str(entry.get('question', '')):
            return entry
    return None


def old_portions(snapshot_chunks):
    return {normalize(x) for x in snapshot_chunks}


def rebuilt(rig):
    """The host's reconnect (as ``test_w3_replays.rebuilt``): the old call closed, a new controller, wire, ear and channel over the same file."""
    rig.fast.close()
    rig.w.reconnect()
    rig.c = rig.w.controller
    rig.c.begin_call()
    rig.detector = type(rig.detector)([])
    rig.worker = Recognizer()
    rig.ear = ear_shadow.for_call(rig.settings, rig.c, detector_factory=lambda: rig.detector, worker=rig.worker, clock=rig.w.clock.now)
    rig.w.wire.ear = rig.ear
    rig.fake = type(rig.fake)()
    rig.fast = FT.for_call(rig.settings, rig.c, stream=two_asks(rig.fake, rig.w.clock.now), instructions=lambda: 'POLICY', wake=lambda: None, clock=rig.w.clock.now)
    rig.w.wire.fast = rig.fast
