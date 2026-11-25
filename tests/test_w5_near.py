"""w5-near: whose speech by LOUDNESS (microphone at the mouth). Synthetic voices (tests/helpers_w5_near.py): nothing here is a phone or a laptop measurement."""
import csv

import pytest

import helpers_w5_near as H
from echo_sync import near_voice as NV
from echo_sync.settings import resolve


def test_default_is_off_and_the_setting_is_checked():
    assert resolve({})['near_voice'] == 'off'
    assert [resolve({'near_voice': v})['near_voice'] for v in ('shadow', 'act', 'on', None)] == ['shadow', 'act', 'off', 'off']
    assert NV.mode({'near_voice': 'act'}) == 'act' and NV.mode({}) == 'off' and NV.mode(None) == 'off' and not NV.enabled({'near_voice': 'x'})


def test_no_sample_means_unknown_whatever_is_heard():
    near = NV.NearVoice()
    near.feed(H.pcm(H.mix(H.voice('other', 1.5, -40), H.room(1.5))))
    assert near.judge().kind == 'unknown' and near.judge_clip(H.scene('other', -15)).kind == 'unknown' and not near.ready


def test_only_aligned_pieces_teach_the_own_level():
    near = NV.NearVoice()
    for k in range(5):
        near.learn(H.pcm(H.voice('own', 1.4, -22, k)), aligned=False)
    near.learn(H.pcm(H.voice('own', 1.4, -22)), aligned=None)
    assert near.pieces == 0
    H.trained(near)
    assert near.ready and near.pieces == 4 and near.own_db == pytest.approx(-19, abs=2.5)


def test_profile_is_not_ready_on_little_speech():
    near = NV.NearVoice()
    for k in range(2):
        near.learn(H.pcm(H.voice('own', 1.4, -22, k)), aligned=True)
    assert not near.ready
    near.learn(H.pcm(H.voice('own', 0.3, -22)), aligned=True)        # 0.3 s carries no level
    assert near.pieces == 2


def test_a_quiet_aligned_piece_is_somebody_elses_word_of_the_prompt():
    near = H.trained(NV.NearVoice())
    n = near.pieces
    near.learn(H.pcm(H.mix(H.voice('other', 1.4, -22 - 16), H.room(1.4))), aligned=True)
    assert near.rejected == 1 and near.pieces == n and near.own_db == pytest.approx(-19, abs=2.5)


def test_judging_a_whole_clip_and_the_live_window_agree():
    near = H.trained(NV.NearVoice())
    near.feed(H.pcm(H.scene('other', -15, seconds=2.0) and H.mix(H.voice('other', 2.0, -22 - 15), H.room(2.0, 4))))
    assert near.judge().kind == 'other' == near.judge_clip(H.scene('other', -15)).kind
    near.feed(H.pcm(H.room(2.2, 3)))
    assert near.judge().kind == 'quiet'
    near.feed(H.pcm(H.mix(H.voice('own', 2.0, -22), H.room(2.0, 5))))
    assert near.judge().kind == 'own'


def test_chunking_does_not_matter():
    a, b = H.trained(NV.NearVoice()), H.trained(NV.NearVoice())
    audio = H.pcm(H.mix(H.voice('other', 2.0, -36), H.room(2.0, 4)))
    a.feed(audio)
    for at in range(0, len(audio), 777):
        b.feed(audio[at:at + 777])
    assert a.judge() == b.judge()


@pytest.fixture(scope='module')
def table():
    return H.rows()


def test_the_table_has_300_rows(table):
    assert len(table) == 300


def test_table_without_agc_never_calls_the_speaker_other(table):
    """Safety first: a wrong 'other' on the speaker's own speech (even soft by 6 dB, even with somebody loud over it) or on the room noise is the costly error."""
    assert [r for r in table if not r[0] and r[2] in ('own', 'own_soft', 'both', 'noise') and r[5] == 'other'] == []
    assert all(r[5] == 'quiet' for r in table if not r[0] and r[2] == 'noise')
    assert all(r[5] == 'own' for r in table if not r[0] and r[2] in ('own', 'both'))


def test_table_without_agc_other_speech_is_found_from_minus_ten_db(table):
    got = {}
    for r in table:
        if not r[0] and r[2] == 'other':got.setdefault(r[1], set()).add(r[5])
    assert all(v == {'other'} for k, v in got.items() if k <= -10)
    assert all('other' not in v for k, v in got.items() if k >= -5)       # loud neighbours are never judged: today's behaviour, no wrong answer


def test_table_with_agc_is_a_known_blind_spot(table):
    """The toy AGC (flattening each clip) hides the level of a lone voice: 'other' is found only at the very bottom, and the speaker is still never called 'other'. Pure room noise lifted by the AGC is called 'other':
    that is why ``act`` needs the AGC signs of the morning call (agc_signs) first."""
    assert [r for r in table if r[0] and r[2] in ('own', 'own_soft', 'both') and r[5] == 'other'] == []
    found = [r[1] for r in table if r[0] and r[2] == 'other' and r[5] == 'other']
    assert found and max(found) <= -18


def write_table(path):
    with open(path, 'w', newline='', encoding='utf-8') as out:
        w = csv.writer(out);w.writerow('agc other_db scene seed expected got conf rel_db'.split())
        w.writerows(H.rows())


# ---- the gate ----
class Clock:
    def __init__(self):self.t = 0.0
    def now(self):return self.t


class Verdicts:
    """Stands for NearVoice in the gate tests: ``judge`` says what the test wants."""
    def __init__(self, kind):self.kind = kind
    def feed(self, pcm):pass
    def judge(self):return NV.Verdict(self.kind, 0.9, -15.0, 0.0)


def gate(kind, clock, speaking=lambda: True, **kw):
    return NV.NearGate(Verdicts(kind), speaking=speaking, clock=clock.now, **kw)


def wait(g, clock, first, until=40.0, step=0.1):
    start = clock.t
    while clock.t - start < until:
        if g.releases({'first': first}):return round(clock.t - start, 1)
        clock.t += step
    return None


def test_other_speech_holds_a_first_cue_a_bounded_time_and_a_next_portion_briefly():
    c = Clock();assert wait(gate('other', c), c, True) == pytest.approx(12.0, abs=0.3)
    c = Clock();assert wait(gate('other', c), c, False) == pytest.approx(0.3, abs=0.3)


def test_own_speech_keeps_todays_hold_and_unknown_is_todays_bound():
    c = Clock();assert wait(gate('own', c), c, False, until=60) is None
    c = Clock();assert wait(gate('unknown', c), c, False) == pytest.approx(1.0, abs=0.3)
    c = Clock();assert wait(gate('unknown', c), c, True) == pytest.approx(30.0, abs=0.3)


def test_shadow_gate_changes_nothing():
    c = Clock();g = gate('other', c, act=False)
    assert wait(g, c, False, until=5) is None and g.other_speaking() is False and g.cuts_playing() is True
    assert not g.is_other_utterance({'kind': 'other', 'conf': 1.0})


def test_other_speech_cuts_a_playing_cue_only_after_the_run_cap():
    c = Clock();g = gate('other', c)
    assert g.cuts_playing() is False
    c.t = NV.OTHER_RUN_CAP_S + 0.5;assert g.cuts_playing() is True
    c = Clock();g = gate('own', c);assert g.cuts_playing() is True


def test_silence_resets_and_a_broken_judge_is_today():
    c = Clock();flag = {'s': True};g = gate('other', c, speaking=lambda: flag['s'])
    c.t = 5.0;g.releases({'first': True});flag['s'] = False;assert not g.releases({'first': True})
    flag['s'] = True;c.t = 6.0;assert not g.releases({'first': True})        # a new run

    class Broken:
        def judge(self):raise RuntimeError('x')
        def feed(self, p):raise RuntimeError('x')
    h = NV.NearGate(Broken(), speaking=lambda: True, clock=c.now)
    assert h.releases({'first': True}) is False and h.cuts_playing() is True and h.other_speaking() is False


def test_a_confirmation_by_another_voice_is_dropped_only_when_sure():
    c = Clock();g = gate('other', c)
    assert g.is_other_utterance({'kind': 'other', 'conf': 0.9}) and not g.is_other_utterance({'kind': 'other', 'conf': 0.4})
    assert not g.is_other_utterance({'kind': 'own', 'conf': 1.0}) and not g.is_other_utterance(None) and not g.is_other_utterance({'kind': 'unknown'})


def test_real_audio_through_the_gate_and_the_shadow_journal_has_no_text():
    c = Clock();lines = []
    g = NV.NearGate(speaking=lambda: True, clock=c.now, act=False, log=lines.append)
    g.on_audio(H.pcm(H.room(1.0, 98)))
    for k in range(4):
        rec = g.on_utterance(H.pcm(H.mix(H.voice('own', 1.4, -22, k), H.room(1.4, k))), 'семнадцатая статья налогового кодекса', 'семнадцатая статья налогового кодекса', uid=k)
    assert rec['aligned'] is True and g.near.ready
    rec = g.on_utterance(H.scene('other', -15), 'что вы сейчас говорили про налоги', 'семнадцатая статья налогового кодекса', uid=9)
    assert rec['kind'] == 'other' and rec['aligned'] is False and g.near.pieces == 4
    assert len(lines) == 5 and all(l.startswith('echo-sync near_voice uid=') and 'налог' not in l for l in lines)
    assert 'kind=other' in lines[-1] and 'rel_db=' in lines[-1]


def test_aligned_needs_the_portion_repeated():
    g = NV.NearGate(speaking=lambda: True, clock=Clock().now)
    pcm = H.pcm(H.mix(H.voice('own', 1.4, -22), H.room(1.4)))
    g.on_utterance(pcm, 'а вот про погоду совсем другое дело', 'семнадцатая статья налогового кодекса')
    assert g.near.pieces == 0
    g.on_utterance(pcm, 'статья налогового кодекса', 'семнадцатая статья налогового кодекса')
    assert g.near.pieces == 1


def test_agc_signs_from_journal_records():
    plain = [dict(aligned=True, level_db=-22 + (i % 3), crest_db=14.0, noise_db=-58 + (i % 2)) for i in range(8)] + [dict(aligned=False, level_db=-38, crest_db=14.0, noise_db=-58)]
    got = NV.agc_signs(plain)
    assert got['suspect'] is False and got['gap_db'] == pytest.approx(16, abs=2)
    squashed = [dict(aligned=True, level_db=-20 + 2 * i, crest_db=6.0, noise_db=-60 + 5 * (i % 4)) for i in range(8)] + [dict(aligned=False, level_db=-23, crest_db=6.0, noise_db=-45)]
    got = NV.agc_signs(squashed)
    assert got['suspect'] is True and got['signs'] >= 3
    assert NV.agc_signs([])['suspect'] is False


def test_never_raises_on_garbage():
    near = NV.NearVoice()
    near.feed(b'\x01');near.feed(None);near.learn(b'', aligned=True);near.learn(None, aligned=True)
    assert near.judge().kind == 'unknown' and near.judge_clip(b'').kind == 'unknown' and near.record(b'')['kind'] == 'unknown'


def test_cost_is_small():
    import time
    near = NV.NearVoice();audio = H.pcm(H.room(1.0, 3));start = time.perf_counter()
    for _ in range(5):near.feed(audio)
    assert (time.perf_counter() - start) / 5 < 0.25      # per second of audio, pure Python, a cloud Xeon; the laptop's N95 is measured there


# ---- the real gate (ControlledMedia.hold, controlled_media._tempo_stuck) with real audio; needs cloud_context/reports/w5-near.gate.diff ----
from test_h3_tempo import Rig, TICK      # noqa: E402,F401
from test_h3_tempo import call           # noqa: E402,F401  (fixture)


def _patched():
    import echo_sync.controlled_media as cm
    import echo_sync.native_media_socket as nm
    return all('speaker_gate' in open(m.__file__, encoding='utf-8', newline='').read() for m in (cm, nm))


needs_patch = pytest.mark.skipif(not _patched(), reason='the gate patch (cloud_context/reports/w5-near.gate.diff) is not applied')


def other_speaks_over_a_cue(rig, audio, seconds=25.0):
    rig.second_portion();began = rig.w.clock.t;n = len(rig.cues());rig.onset()
    while rig.w.clock.t - began < seconds:
        rig.w.controller.speaker_gate.on_audio(audio);rig.packet('speech');rig.pump(TICK)
        if len(rig.cues()) > n:return round(rig.w.clock.t - began, 1)
    return None


def with_near(rig, act=True):
    c, clock = rig.w.controller, rig.w.clock
    c.speaker_gate = NV.NearGate(H.trained(NV.NearVoice()), speaking=lambda: rig.ear.current is not None, clock=clock.now, act=act)


@needs_patch
def test_real_gate_a_loud_neighbour_at_minus_fifteen_db_does_not_hold_the_next_portion(call):
    rig = call();with_near(rig)
    got = other_speaks_over_a_cue(rig, H.pcm(H.mix(H.voice('other', 0.1, -22 - 15, 3), H.room(0.1, 3))))
    assert got is not None and got < 5.0, got


@needs_patch
def test_real_gate_the_speaker_keeps_todays_ten_seconds(call):
    rig = call();with_near(rig)
    assert other_speaks_over_a_cue(rig, H.pcm(H.mix(H.voice('own', 0.1, -22, 3), H.room(0.1, 3)))) == 10.0


@needs_patch
def test_real_gate_a_neighbour_at_minus_four_db_is_not_judged_and_shadow_is_today(call):
    rig = call();with_near(rig)
    assert other_speaks_over_a_cue(rig, H.pcm(H.mix(H.voice('other', 0.1, -22 - 4, 3), H.room(0.1, 3)))) == 10.0
    rig = call();with_near(rig, act=False)
    assert other_speaks_over_a_cue(rig, H.pcm(H.mix(H.voice('other', 0.1, -22 - 15, 3), H.room(0.1, 3)))) == 10.0
