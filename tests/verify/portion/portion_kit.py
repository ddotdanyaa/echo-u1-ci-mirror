"""V4 kit: what the verify tests of ``tests/verify/portion`` share (the family «portion and terms»: the cut of the answer, the repeat, the stumble, the waits of the tempo).

Nothing here decides anything. It drives the REAL ControlledMedia: through the rig ``call`` of ``test_h3_tempo`` (REAL NativeMediaSocket, ShadowEar and FastText channel; the speech detector, the recognizer's worker,
the cloud's events and the job's stream are scripted; the clock is the world's) and through ``helpers_s6_ack.Dictation`` (the controller built as the host builds it, the clock injected). No number here is a
measurement of a call, a laptop or a phone.
"""
import os
import sys
from pathlib import Path

_TESTS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _TESTS not in sys.path:
    sys.path.insert(0, _TESTS)

import helpers_s6_ack as H                                                # noqa: E402
import helpers_s6_state as S                                              # noqa: E402,F401
from echo_sync.controlled_media import TEMPO_FILLER_SECONDS, TEMPO_START_SECONDS, TEMPO_TWICE_SECONDS   # noqa: E402,F401
from echo_sync.settings import controller_settings, resolve               # noqa: E402
from echo_sync.textutil import syllables                                  # noqa: E402,F401
from echo_sync.timer_policy import TEMPO_REPEAT_SECONDS                   # noqa: E402,F401
from test_h3_tempo import GRID, HEAD, PORTION, REST, TICK, WAIT_OF_H3, call          # noqa: E402,F401 - call is the fixture of the directory
from test_h5_live import LIVE, plan                                       # noqa: E402,F401
from test_repeat_cases import ASK, CANDIDATE, HOST_SYNCS_ENGINE, NEXT, P1, P2, P3, rig_of, utter      # noqa: E402,F401
from test_c22_repeat_wiring import RULE, after, walk                      # noqa: E402,F401
from test_h5_live import EAR_BAPTISM, answer_over_speech, asked, spoken_failures      # noqa: E402,F401
from echo_sync.controlled_media import EAR_RELEASE_SILENCE_SECONDS, EAR_TAIL_SILENCE_SECONDS, TEMPO_STEP_SECONDS      # noqa: E402,F401
from echo_sync.repeat_rule import DICTATION_START_SECONDS, DictationPace   # noqa: E402,F401
from echo_sync.timer_policy import DICTATION_CYCLE_SECONDS                 # noqa: E402,F401

LIVE_RULES = dict(LIVE)                                                   # the profile of the working call as the other tests of the family build it


def state(rig):
    return rig.c.state() or {}


def index(rig):
    return state(rig).get('chunk_index', 0)


def moved(rig, before):
    """The cursor of the answer went on (or the answer was completed) since ``before``."""
    st = state(rig)
    return bool(st.get('completed')) or st.get('chunk_index', 0) > before


def cue_times(rig):
    return [(c.t, c.text) for c in rig.cues()]


def dictation_of(directory, answer, at=0, **profile):
    """The controller of the host over ``answer`` (``H.Dictation``) with the profile's keys through the one builder of a controller's settings; ``at`` portions repeated whole before the one that waits."""
    settings = controller_settings(resolve(profile)) if profile else None
    d = H.Dictation(Path(directory), answer, settings=settings)
    if settings is not None and HOST_SYNCS_ENGINE:
        d.controller.engine.settings = d.controller.settings
    for n in range(at):
        assert d.say(d.current, gap=4.0).after == n + 1, 'precondition: the cue before the portion is confirmed'
    d.clock.advance(4.0)
    return d
