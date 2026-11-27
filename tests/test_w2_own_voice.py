"""w2-own-voice: the ear learns the prompted speaker's voice from what aligned with the prompt (no enrolment), and the gate's wait on somebody else's speech is bounded.
No model, no network: a scripted embedder stands for the speaker model (the real one is measured on the laptop, cloud_context/reports/w2-own-voice.md)."""
import math

import pytest

from echo_sync import own_voice as OV
from echo_sync.settings import resolve

A, B = [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]


def pcm(seconds, tag=0):
    """16 kHz mono s16: ``seconds`` of a constant whose value is the tag (the scripted embedder reads it)."""
    return int(tag).to_bytes(2, 'little', signed=True) * int(seconds * OV.SAMPLE_RATE)


def embedder(table=None):
    table = table or {1: A, 2: B}
    return OV.ScriptedEmbedder(lambda tag: table.get(tag))


def profile(**kw):
    return OV.VoiceProfile(embedder(), **kw)


def noisy(base, k):
    return [base[0] + 0.05 * k, base[1] + 0.02 * k, base[2] + 0.01 * k]


def test_the_dead_key_is_gone():
    assert 'speaker_voice' not in resolve({'speaker_voice': 'on'}) and not hasattr(OV, 'enabled')      # the key never wired anything: gone


def test_cosine_and_unit_mean():
    assert OV.cosine(A, A) == pytest.approx(1.0) and OV.cosine(A, B) == pytest.approx(0.0)
    assert OV.cosine(A, [0, 0, 0]) == 0.0 and OV.cosine(A, [1, 0]) == 0.0
    m = OV.unit_mean([A, B])
    assert math.hypot(*m) == pytest.approx(1.0)


def test_nothing_is_known_before_enough_aligned_speech():
    p = profile()
    assert p.judge(pcm(2, 1)).kind == 'unknown' and not p.ready
    p.learn(pcm(2, 1), aligned=True)
    assert not p.ready and p.judge(pcm(2, 1)).kind == 'unknown'      # 2 s is not enough: the speaker is not invented


def test_only_what_aligned_with_the_prompt_is_the_speakers_voice():
    p = profile()
    p.learn(pcm(5, 2), aligned=False)                                  # somebody else, not aligned: never a sample
    assert p.seconds == 0
    for _ in range(3):
        p.learn(pcm(2.5, 1), aligned=True)
    assert p.ready
    assert p.judge(pcm(2, 1)).kind == 'own' and p.judge(pcm(2, 2)).kind == 'other'


def test_short_or_unembeddable_pieces_are_not_taken():
    p = profile()
    p.learn(pcm(0.3, 1), aligned=True)                                 # under MIN_SEGMENT_SECONDS
    p.learn(pcm(3, 99), aligned=True)                                  # the model gave nothing
    p.learn(b'', aligned=True)
    assert p.seconds == 0 and p.pieces == 0
    assert p.judge(b'').kind == 'unknown' and p.judge(pcm(3, 99)).kind == 'unknown'


def test_a_misaligned_piece_does_not_poison_the_profile():
    p = profile()
    for _ in range(3):
        p.learn(pcm(3, 1), aligned=True)
    before = p.pieces
    p.learn(pcm(3, 2), aligned=True)                                   # aligned by a fluke (the other voice said a word of the prompt)
    assert p.pieces == before and p.rejected == 1
    assert p.judge(pcm(2, 2)).kind == 'other'


def test_the_middle_is_unknown_not_a_guess():
    t = {1: A, 2: B, 3: [0.5, 0.866, 0.0]}
    p = OV.VoiceProfile(embedder(t))
    for _ in range(3):
        p.learn(pcm(3, 1), aligned=True)
    v = p.judge(pcm(2, 3))                                             # cos = 0.5: between the thresholds
    assert OV.OTHER_BELOW < v.score < OV.OWN_ABOVE and v.kind == 'unknown'


def test_pieces_are_capped_and_the_profile_stays_unit():
    p = profile()
    for k in range(OV.MAX_PIECES + 10):
        p.learn(pcm(1, 1), aligned=True)
    assert p.pieces == OV.MAX_PIECES and math.hypot(*p.centroid) == pytest.approx(1.0)


def test_reset_forgets():
    p = profile()
    for _ in range(3):
        p.learn(pcm(3, 1), aligned=True)
    p.reset()
    assert not p.ready and p.pieces == 0 and p.judge(pcm(2, 1)).kind == 'unknown'


def test_a_broken_embedder_never_raises():
    def boom(tag):
        raise RuntimeError('model')
    p = OV.VoiceProfile(OV.ScriptedEmbedder(boom))
    p.learn(pcm(3, 1), aligned=True)
    assert p.judge(pcm(3, 1)).kind == 'unknown' and p.errors == 1


def test_sherpa_embedder_is_lazy_and_reports_a_missing_model():
    e = OV.SherpaEmbedder('/no/such/model.onnx')
    assert e.embed(pcm(1, 1)) is None and e.error                      # no sherpa_onnx / no model here: None, never an exception


# ---- the wait on somebody else's speech (the gate) ----

class Clock:
    t = 100.0


def run(policy, kind_at, first=True, until=40.0, step=0.1):
    """Feed the policy a speech with the verdicts ``kind_at(t)``; the seconds from the start of the speech to the first 'go'."""
    t = 0.0
    while t <= until:
        d = policy.step(100.0 + t, speaking=True, verdict=kind_at(t), first=first)
        if d == 'go':
            return round(t, 1)
        t += step
    return None


def test_other_voice_holds_a_first_cue_a_bounded_time():
    got = run(OV.OtherSpeech(), lambda t: 'other')
    assert got == OV.OTHER_FIRST_HOLD_S


def test_the_speakers_own_voice_keeps_todays_hold():
    assert run(OV.OtherSpeech(), lambda t: 'own', until=OV.OWN_HOLD_S + 1) is None    # not this policy's to cut short: the old holds stand


def test_unknown_voice_is_todays_behaviour_and_bounded_too():
    assert run(OV.OtherSpeech(), lambda t: 'unknown') == OV.UNKNOWN_HOLD_S


def test_own_voice_resets_the_other_run():
    p = OV.OtherSpeech()
    kinds = lambda t: 'other' if t < OV.OTHER_FIRST_HOLD_S - 1 else ('own' if t < OV.OTHER_FIRST_HOLD_S else 'other')
    got = run(p, kinds)
    assert got is not None and got > OV.OTHER_FIRST_HOLD_S                 # the speaker spoke in between: the count starts anew


def test_next_portion_is_held_only_briefly_by_other_speech():
    assert run(OV.OtherSpeech(), lambda t: 'other', first=False) == OV.OTHER_NEXT_HOLD_S


def test_silence_resets_everything():
    p = OV.OtherSpeech()
    assert p.step(100.0, speaking=True, verdict='other', first=True) == 'hold'
    assert p.step(101.0, speaking=False, verdict='other', first=True) == 'go'
    assert p.step(101.1, speaking=True, verdict='other', first=True) == 'hold' and p.run_seconds(101.1) == 0.0


def test_cut_a_playing_cue_only_on_a_confirmed_own_voice():
    p = OV.OtherSpeech()
    assert p.cut_playing(100.0, speaking=True, verdict='other') is False
    assert p.cut_playing(100.0, speaking=True, verdict='unknown') is True     # as today: nobody knows, the cue yields
    assert p.cut_playing(100.0, speaking=True, verdict='own') is True
    assert p.cut_playing(100.0, speaking=False, verdict='own') is False


def test_other_speech_never_cuts_for_longer_than_the_run_cap():
    p = OV.OtherSpeech()
    assert p.cut_playing(100.0, speaking=True, verdict='other') is False
    assert p.cut_playing(100.0 + OV.OTHER_RUN_CAP_S + 0.1, speaking=True, verdict='other') is True


def test_bad_arguments_are_safe():
    p = OV.OtherSpeech()
    assert p.step(float('nan'), speaking=True, verdict='other', first=True) == 'go'
    assert p.step(1.0, speaking=True, verdict=None, first=True) in ('hold', 'go')


# ---- the gate's adapter ----

class Tick:
    def __init__(self):
        self.t = 100.0
        self.on = True

    def now(self):
        return self.t


def gate(clock, voices=None):
    p = profile()
    for _ in range(3):
        p.learn(pcm(3, 1), aligned=True)
    return OV.SpeakerGate(p, speaking=lambda: clock.on, clock=clock.now)


def go_on(g, clock, tag, seconds, first, step=0.1):
    """Speech of a voice ``tag``; the seconds until the gate lets the cue go, or None."""
    began = clock.t
    while clock.t - began <= seconds:
        g.on_audio(pcm(step, tag))
        if g.releases({'first': first}):
            return round(clock.t - began, 1)
        clock.t += step
    return None


def test_gate_releases_a_next_cue_over_other_voice_but_not_over_the_speaker():
    c = Tick()
    g = gate(c)
    got = go_on(g, c, 2, 5, first=False)
    assert got is not None and OV.MIN_JUDGE_SECONDS <= got <= OV.UNKNOWN_NEXT_HOLD_S      # judged after half a second of it, then 0.3 s: never later than today's 1 s
    c2 = Tick()
    assert go_on(gate(c2), c2, 1, 30, first=False) is None                  # the speaker's own voice: nothing shortened


def test_gate_first_cue_over_other_voice_goes_at_the_cap_and_never_before_it_is_judged():
    c = Tick()
    got = go_on(gate(c), c, 2, 30, first=True)
    assert got is not None and OV.OTHER_FIRST_HOLD_S - 0.01 <= got <= OV.OTHER_FIRST_HOLD_S + OV.JUDGE_EVERY_S + 0.2


def test_gate_unknown_voice_is_today_for_a_first_cue():
    c = Tick()
    g = OV.SpeakerGate(profile(), speaking=lambda: True, clock=c.now)       # no profile at all
    assert go_on(g, c, 2, 25, first=True) is None


def test_gate_silence_releases_nothing_and_resets():
    c = Tick()
    g = gate(c)
    c.on = False
    assert g.releases({'first': True}) is False and g.cuts_playing() is False


def test_gate_does_not_cut_a_cue_for_other_voice_and_survives_a_broken_profile():
    c = Tick()
    g = gate(c)
    g.on_audio(pcm(2, 2))
    assert g.cuts_playing() is False
    c.t += OV.OTHER_RUN_CAP_S + 1
    g.on_audio(pcm(2, 2))
    assert g.cuts_playing() is True
    c.t += 1.0
    g.profile = None                                                       # a broken profile: no release, the cue yields as today
    assert g.releases({'first': False}) is False and g.cuts_playing() is True


def test_alignment_is_the_prompt_repeated_not_any_speech():
    portion = 'общие условия установления налогов и сборов'
    assert OV.aligned('общие условия установления налогов', portion)
    assert not OV.aligned('а у вас какая ставка по договору', portion) and not OV.aligned('условия', portion)
    assert not OV.aligned('', portion) and not OV.aligned(None, portion)


# ---- the real gate (native_media_socket._held_by_listener) with the adapter; needs the patch of cloud_context/reports/w2-own-voice.gate.diff ----

from test_h3_tempo import Rig, TICK      # noqa: E402
from test_h3_tempo import call           # noqa: E402,F401  (fixture)


def other_speaks_over_a_cue(rig, seconds=25.0):
    """The second portion has been said, nobody repeated it, somebody else talks without a stop: the seconds until the next cue plays over it, or None."""
    rig.second_portion()
    began = rig.w.clock.t
    n = len(rig.cues())
    rig.onset()
    while rig.w.clock.t - began < seconds:
        rig.packet('speech')
        rig.pump(TICK)
        if len(rig.cues()) > n:
            return round(rig.w.clock.t - began, 1)
    return None


def _patched():
    import echo_sync.controlled_media as cm
    import echo_sync.native_media_socket as nm
    return all('speaker_gate' in open(m.__file__, encoding='utf-8', newline='').read() for m in (cm, nm))


needs_patch = pytest.mark.skipif(not _patched(), reason='the gate patch (cloud_context/reports/w2-own-voice.gate.diff) is not applied')


def with_voice(rig, kind):
    c, clock = rig.w.controller, rig.w.clock

    class Voice:
        def judge(self, pcm):
            return OV.Verdict(kind, 0.1)
    c.speaker_gate = OV.SpeakerGate(Voice(), speaking=lambda: rig.ear.current is not None, clock=clock.now)
    real = rig.packet
    rig.packet = lambda step, settle=True: (c.speaker_gate.on_audio(pcm(0.1, 2)), real(step, settle))[1]


def test_today_the_next_portion_waits_ten_seconds_over_endless_speech(call):
    """The fact asked for in RELEASE_FOCUS 5.2 (measured on the real controller, the ear's detector scripted): the cue plays 10.0 s into somebody else's speech: EAR_SPEECH_SECONDS (8) of a detector with no offset + the silence wait."""
    assert other_speaks_over_a_cue(call()) == 10.0


@needs_patch
def test_real_gate_other_voice_does_not_hold_the_next_portion_ten_seconds(call):
    rig = call()
    with_voice(rig, 'other')
    got = other_speaks_over_a_cue(rig)
    assert got is not None and got < 5.0, got            # the judging second plus the ordinary silence wait of the timer


@needs_patch
def test_real_gate_the_speakers_own_voice_keeps_todays_wait(call):
    rig = call()
    with_voice(rig, 'own')
    assert other_speaks_over_a_cue(rig) == 10.0


@needs_patch
def test_real_gate_unknown_voice_keeps_todays_wait(call):
    rig = call()
    with_voice(rig, 'unknown')
    assert other_speaks_over_a_cue(rig) == 10.0


def test_a_first_cue_is_not_held_for_ever_whatever_holds_it(call):
    """w3-integ item 11: a hold of the first cue whose own bound is gone (no question clock: an answer of a candidate, a question opened by the ear) still ends: FIRST_HOLD_CAP_SECONDS from the moment it began
    holding. Somebody else talking all the while is the case: nothing of today's gate tells their speech from the listener's."""
    from echo_sync.controlled_media import FIRST_HOLD_CAP_SECONDS
    rig = call()
    c = rig.c
    assert c.tempo_live, 'precondition: the ear leads the tempo'
    c.question_clock = None
    c.candidate = {'id': 'u9', 'job': 'fast-1', 'text': 'Что такое инерция'}       # a job at work holds the first cue (H5 item 2)
    assert c.first_cue_held()
    rig.w.clock.t += FIRST_HOLD_CAP_SECONDS - 0.1
    assert c.first_cue_held(), 'the job may take its time'
    rig.w.clock.t += 0.2
    assert not c.first_cue_held(), 'but not for ever'
