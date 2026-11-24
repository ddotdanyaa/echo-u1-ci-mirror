"""U52: the owner's voice interrupts a cue. Rule: in silence anybody's speech start cuts what plays (today); DURING a cue only the owner's NEAR voice does - the echo of the cue and a far / other voice do not.
The one place of the decision is ``ControlledMedia._act('cut_sound', 'speech_started')`` (witness row ``owner``); the witnesses are the gate's (near_voice level + 'is it the cue heard back', own_voice print).
Synthetic PCM (helpers_w5_near). Needs no phone: the phone check is one line in the report (Conduit sends the microphone during a cue, so the server hears the start at all)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import helpers_s6_ack as D           # noqa: E402
import helpers_w5_near as H          # noqa: E402
from echo_sync import near_voice as NV      # noqa: E402
from echo_sync import own_voice as OV       # noqa: E402
from echo_sync.settings import CALL_SETTINGS      # noqa: E402

RATE = 16000


def make(tmp_path, cue=True, playing=True):
    d = D.Dictation(tmp_path / 'c', None, settings={**CALL_SETTINGS, 'act_gate': 'off'})
    c = d.controller
    c.speaker_gate = NV.NearGate(H.trained(NV.NearVoice()), speaking=lambda: True, clock=d.clock)
    if playing:
        now = d.clock();c.cue_outstanding = True;c.cue_window = [now, now + 6.0]
    return d, c


def speech(seed, seconds=2.1, db=-26):
    """A cue like real speech: its syllable rate changes from phrase to phrase (a single steady rate would correlate with any voice)."""
    return [x for k in range(3) for x in H.voice('other', seconds / 3, db, seed * 7 + k)]


def cue_pcm(seconds=2.1):
    return H.pcm(H.mix(speech(11, seconds), H.room(seconds, 11)))


def hear(c, mic):
    for at in range(0, len(mic), 3200):c.speaker_gate.on_audio(mic[at:at + 3200])


def cancelled(actions):
    return any(a.get('type') == 'cancel' for a in actions)


def test_in_silence_anybody_s_speech_cuts(tmp_path):
    d, c = make(tmp_path, playing=False)
    hear(c, H.scene('other', -15))
    assert cancelled(c.speech_started())


def test_during_a_cue_the_owner_s_near_voice_cuts(tmp_path):
    d, c = make(tmp_path)
    c.speaker_gate.cue_began(cue_pcm(), RATE)
    hear(c, H.scene('own', 0, seed=3))
    assert cancelled(c.speech_started())


def test_during_a_cue_a_far_voice_does_not_cut(tmp_path):
    d, c = make(tmp_path)
    c.speaker_gate.cue_began(cue_pcm(), RATE)
    hear(c, H.scene('other', -15, seed=4))
    assert not cancelled(c.speech_started())


def test_during_a_cue_its_echo_does_not_cut_even_when_loud_as_the_owner(tmp_path):
    """The worst echo: the cue comes back to the microphone as loud as the owner (verdict 'own' by level); its envelope is the cue's, 0.12 s later."""
    d, c = make(tmp_path)
    cue = H.voice('other', 2.0, -22, 11)
    c.speaker_gate.cue_began(H.pcm(H.mix(cue, H.room(2.0, 11))), RATE)
    hear(c, H.pcm(H.mix(H.room(0.12, 1), cue, H.room(2.12, 12))))
    assert c.speaker_gate.near.judge().kind == 'own'      # the level alone would have cut it
    assert not cancelled(c.speech_started())


def test_the_owner_talking_over_the_cue_cuts_through_its_echo(tmp_path):
    d, c = make(tmp_path)
    cue = H.voice('other', 2.0, -34, 11)
    c.speaker_gate.cue_began(H.pcm(H.mix(cue, H.room(2.0, 11))), RATE)
    hear(c, H.pcm(H.mix(H.room(0.12, 1), cue, H.voice('own', 2.12, -22, 5), H.room(2.12, 12))))
    assert cancelled(c.speech_started())


def test_the_veto_is_the_gate_s_verdict_of_the_one_owner(tmp_path):
    """No second cut path: the barge-in is refused inside ``_act`` ('park', nothing for the transport), the same entry that cuts in silence."""
    d, c = make(tmp_path)
    c.speaker_gate.cue_began(cue_pcm(), RATE)
    hear(c, H.scene('other', -15, seed=4))
    assert c._act('cut_sound', 'speech_started') == ('park', [])
    c.cue_outstanding = False
    assert c._act('cut_sound', 'speech_started')[0] == 'do'


def test_an_unknown_voice_keeps_todays_cut(tmp_path):
    """No own-level profile yet: nothing says it is not the owner, so it cuts as before."""
    d, c = make(tmp_path)
    c.speaker_gate = NV.NearGate(NV.NearVoice(), speaking=lambda: True, clock=d.clock)
    hear(c, H.scene('other', -15))
    assert cancelled(c.speech_started())


def test_the_own_voice_print_gate_follows_the_same_rule(tmp_path):
    d, c = make(tmp_path)
    gate = OV.SpeakerGate(OV.VoiceProfile(OV.ScriptedEmbedder(lambda pcm: [1.0, 0.0])), speaking=lambda: True, clock=d.clock)
    gate.verdict = lambda: OV.Verdict('other', 0.1)
    c.speaker_gate = gate
    assert not cancelled(c.speech_started())
    gate.verdict = lambda: OV.Verdict('own', 0.9)
    assert cancelled(c.speech_started())


@pytest.mark.parametrize('seed', range(8))
def test_the_witness_does_not_mistake_a_voice_for_an_echo_nor_an_echo_for_a_voice(tmp_path, seed):
    d, c = make(tmp_path)
    c.speaker_gate.cue_began(cue_pcm(), RATE)
    hear(c, H.scene('own', 0, seed=seed))
    assert c.speaker_gate.hears_cue_back() is False
    d, c = make(tmp_path / 'e')
    cue = speech(seed, db=-22)
    c.speaker_gate.cue_began(H.pcm(cue), RATE)
    hear(c, H.pcm(H.mix(H.room(0.1 + 0.02 * seed, 1), cue, H.room(2.2, 12))))
    assert c.speaker_gate.hears_cue_back() is True
