"""Synthetic PCM only. Tests of the current pure U52 envelope-witness algorithm.

These prove neither speaker identity nor real iPhone acoustic behavior.
"""
import math
import random
from array import array

import pytest

from echo_sync.near_voice import NearGate, NearVoice, barge_cuts, ECHO_MIN_FRAMES

CUE_RATE=24000
MIC_RATE=16000
FRAMES=64


def profile(seed=2026, size=FRAMES):
    r=random.Random(seed)
    return [r.randint(400, 12000) for _ in range(size)]


def pcm(levels, rate):
    words=array('h')
    for amp in levels:
        sample=max(0,min(22000,int(amp)))
        words.extend((sample if i % 2 else -sample for i in range(rate//50)))
    return words.tobytes()


def rig():
    return NearGate(near=NearVoice(), speaking=lambda: True, clock=lambda: 0., act=True)


@pytest.mark.parametrize('delay', [0, 3, 9, 18])
def test_exact_synthetic_cue_echo_is_detected_and_will_not_barge(delay):
    g=rig()
    levels=profile()
    g.cue_began(pcm(levels,CUE_RATE),rate=CUE_RATE)
    g.on_audio(pcm([0]*delay+levels,MIC_RATE))
    assert g.hears_cue_back(), delay
    assert not g.cuts_cue(), 'microphone picked the existing cue, not a user barge'


def test_no_cue_and_no_microphone_does_not_claim_echo():
    g=rig()
    assert not g.hears_cue_back()
    g.cue_began(pcm(profile(),CUE_RATE),rate=CUE_RATE)
    assert not g.hears_cue_back()


def test_less_than_25_frames_does_not_claim_echo_even_if_identical():
    g=rig()
    levels=profile(size=ECHO_MIN_FRAMES-1)
    g.cue_began(pcm(levels,CUE_RATE),rate=CUE_RATE)
    g.on_audio(pcm(levels,MIC_RATE))
    assert not g.hears_cue_back()


def test_unrelated_synthetic_speaker_envelope_must_not_match():
    g=rig()
    cue=profile(2026)
    voice=profile(80411)
    g.cue_began(pcm(cue,CUE_RATE),rate=CUE_RATE)
    g.on_audio(pcm(voice,MIC_RATE))
    assert not g.hears_cue_back()
    assert g.cuts_cue(), 'unknown, distinct voice is allowed to interrupt in existing policy'


def test_echo_that_contains_independent_user_speech_is_not_reliably_the_cue():
    g=rig()
    cue=profile(2026)
    user=profile(80411)
    g.cue_began(pcm(cue,CUE_RATE),rate=CUE_RATE)
    # Human speaks over the output: synthetic RMS energy is dominated by user.
    g.on_audio(pcm([min(20000,2*u+e//4) for u,e in zip(user,cue)],MIC_RATE))
    assert not g.hears_cue_back()
    assert g.cuts_cue()


@pytest.mark.parametrize('kind,echo,expected', [
    ('other',False,False),('other',True,False),
    ('own',False,True),('own',True,False),
    ('quiet',False,False),('unknown',False,True),
    ('unknown',True,False),
])
def test_existing_barge_cuts_contract_is_unchanged(kind,echo,expected):
    assert barge_cuts(kind,echo) == expected
