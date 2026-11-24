"""one-research EOT-RU through the real controller (the rig of test_h3_tempo): a question asked whole is released after the speaker's own pause, an open tail
still waits EAR_TAIL_SILENCE_SECONDS, and a call that has learned nothing waits EAR_RELEASE_SILENCE_SECONDS as before."""
from echo_sync.controlled_media import EAR_RELEASE_SILENCE_SECONDS, EAR_TAIL_SILENCE_SECONDS
from echo_sync.local_ear import CLOSED_MIN_S
from test_h3_tempo import call  # noqa: F401 - the fixture


def speak(rig, uid, seconds):
    rig.c._tempo_speech(uid, 'onset')
    rig.w.clock.advance(seconds)
    rig.c._tempo_speech(uid, 'offset')


def habit(rig, pause, n=30):
    """The speaker talks in runs with short inner pauses: each onset comes ``pause`` after the last offset."""
    rig.c._tempo_speech('live', 'live')
    for i in range(n):
        speak(rig, 'h%d' % i, 1.0)
        rig.w.clock.advance(pause)
    speak(rig, 'last', 1.0)


def over_after(rig, text, quiet):
    rig.w.clock.advance(quiet)
    return rig.c._utterance_over(text)


def test_nothing_learned_waits_as_before(call):
    rig = call()
    rig.c._tempo_speech('live', 'live')
    speak(rig, 'u1', 1.0)
    assert not over_after(rig, 'что такое амортизация', EAR_RELEASE_SILENCE_SECONDS - 0.05)
    assert over_after(rig, 'что такое амортизация', 0.06)


def test_closed_question_released_on_the_speakers_short_pause(call):
    rig = call()
    habit(rig, 0.25)
    assert rig.c.pauses.count >= 30
    assert rig.c._release_wait('что такое амортизация') < 0.6
    assert over_after(rig, 'что такое амортизация', 0.6), 'a whole question of a quick speaker goes at 0.6 s, not 0.9 s'


def test_open_tail_and_unsure_keep_their_waits_whatever_was_learned(call):
    rig = call()
    habit(rig, 0.25)
    assert rig.c._release_wait('налог на') == EAR_TAIL_SILENCE_SECONDS
    assert rig.c._release_wait('налог на прибыль') == EAR_RELEASE_SILENCE_SECONDS
    assert not over_after(rig, 'налог на', 0.95)


def test_a_slow_speaker_never_waits_longer_than_today(call):
    rig = call()
    habit(rig, 0.85)
    assert CLOSED_MIN_S <= rig.c._release_wait('что такое амортизация') <= EAR_RELEASE_SILENCE_SECONDS


def test_first_cue_opens_reads_the_same_wait(call):
    rig = call()
    habit(rig, 0.25)
    rig.c.question_text = 'что такое амортизация'
    hold = rig.c.first_cue_hold()
    if rig.c.prepare_wide and hold:
        assert hold[1] == rig.c.tempo_ended + rig.c._release_wait('что такое амортизация')


def test_a_pause_a_cue_began_in_is_not_learned(call):
    """G1-16 (livekit endpointing.py:202-206 re-anchors when the agent spoke): the speaker stopped, our cue began, they spoke again: that was no pause of theirs."""
    rig = call()
    rig.c._tempo_speech('live', 'live')
    for i in range(20):
        speak(rig, 'c%d' % i, 1.0)
        rig.w.clock.advance(0.1)
        rig.c.cue_window = [rig.w.clock.now(), rig.w.clock.now() + 2.0]
        rig.w.clock.advance(0.15)
    assert rig.c.pauses.count == 0
