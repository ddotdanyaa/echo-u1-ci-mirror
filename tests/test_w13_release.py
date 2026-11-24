"""W13 item 5: the sound does not wait for the final. With the candidate's flags on together (``two_witnesses``, ``ear_release``, ``gate_text``,
``ear_command_early``, ``instant``, the controller set from the profile as ``controlled_host`` sets it), a question with no number and no «не»,
the ear and the cloud's stable piece agreeing, sounds as soon as the job prepared on the ear has its first sentence."""
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import helpers_s6_state as S
from test_h3_tempo import TICK, call       # noqa: F401 - call is the fixture
from test_h4_ear_first import ANSWER, decisions

PROFILE = {'fast_text': 'on', 'ear_release': 'on', 'gate_text': 'on', 'instant': 'on'}
WORDS = ['Так, в каком ', 'году было ', 'крещение ', 'Руси']


def candidate(call, **over):
    rig = call(**{**PROFILE, **over})
    s = rig.settings
    assert s['ear_release'] == 'on', s      # the profile resolves: no flag turns another off
    return rig


def _speaks_with_the_cloud(rig, text='так в каком году было крещение руси', words=WORDS):
    uid = rig.onset()
    rig.pump(0.5)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    for n, word in enumerate(words):
        rig.w.feed(S.turn_delta('u1', word, n))
        rig.pump(0.2)
    ended = rig.offset()
    rig.pump(0.15)
    rig.worker.heard(uid, text)
    rig.pump(TICK)
    assert rig.fake.runs, 'precondition: the job was prepared on the ear'
    return ended


@pytest.mark.parametrize('silence', [0.0, 0.3, 0.9])
def test_the_question_sounds_with_the_first_sentence_of_the_job(call, silence):
    rig = candidate(call)
    _speaks_with_the_cloud(rig)
    rig.pump(silence)
    began = rig.w.clock.t
    rig.job_says(0, ANSWER)
    cue = rig.next_cue(1.5)
    assert cue is not None and '988' in cue.text, rig.said()
    assert cue.t - max(began, rig.w.clock.t - 1.5) <= 0.9 + 3 * TICK, 'not held for the final'


def test_a_number_the_cloud_has_not_witnessed_still_waits(call, caplog):
    rig = candidate(call)
    with caplog.at_level(logging.INFO, logger='echo-sync'):
        _speaks_with_the_cloud(rig, 'сколько часов ехать от москвы до казани сто километров', ['Сколько часов ', 'ехать от ', 'Москвы до ', 'Казани ', '200 ', 'километров'])
        rig.pump(0.9)
        rig.job_says(0, 'Около двух часов.')
        rig.pump(TICK * 4)
    assert rig.said() == []


def _cloud_late(rig, chunks, lag, text='так в каком году было крещение руси'):
    """The phone's order: the ear's text 0.15 s after the end, the cloud's piece ``lag`` s after the end, in ``chunks``."""
    uid = rig.onset()
    rig.pump(0.5)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.pump(1.0)
    rig.offset()
    rig.pump(0.15)
    rig.worker.heard(uid, text)
    rig.pump(max(0.0, lag - 0.15))
    for n, chunk in enumerate(chunks):
        rig.w.feed(S.turn_delta('u1', chunk, n))
        rig.pump(TICK)


@pytest.mark.parametrize('chunks', [['Так, в каком году было крещение Руси'], ['Так, в каком году ', 'было крещение Руси']], ids=['one', 'two'])
def test_a_late_cloud_piece_in_few_deltas_still_releases_before_the_final(call, chunks):
    rig = candidate(call)
    _cloud_late(rig, chunks, 1.06)
    rig.job_says(0, ANSWER)
    cue = rig.next_cue(2.0)
    assert cue is not None and '988' in cue.text, rig.said()


def test_the_host_sets_on_the_controller_every_flag_the_controller_reads_from_its_settings():
    """The flags the controller reads from ``self.settings`` were set by the replay stand only: on the laptop the
    controller had CALL_SETTINGS, the profile's flag was inert. The host sets them as it sets ``two_witnesses``."""
    import re
    import echo_sync
    root = Path(echo_sync.__file__).parent
    from cm_patch import controller_source
    media = controller_source()          # controlled_media.py and every cm_*.py
    host = (root / 'controlled_host.py').read_text(encoding='utf-8')
    read = set(re.findall(r"\(self\.settings or \{\}\)\.get\('([a-z_]+)'\)", media))
    assert not read, read      # the owner's rules are code now: the controller reads no profile key raw from its settings
    from echo_sync.settings import DEFAULTS, controller_settings      # ROOT-1: one builder, controller_settings(), at construction
    assert 'settings=controller_settings(profile_settings)' in host, 'the host does not hand the profile flags to controller.settings'
    assert all(controller_settings({key: 'changed'}).get(key) == 'changed' for key in read if key in DEFAULTS), read      # every key the controller reads raw reaches it when the profile changed it
