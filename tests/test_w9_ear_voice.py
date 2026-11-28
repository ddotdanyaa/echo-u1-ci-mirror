"""w9-ear-voice (E78, N127-N129): the real ShadowEar hands the audio of each utterance to near_voice and puts ``voice`` into the record. Synthetic voices (helpers_w5_near): not a phone measurement.
Off unless the raw setting ``near_voice`` is shadow/act."""
import logging

import helpers_w5_near as V
import test_ear_shadow as T
from echo_sync import ear_shadow, near_voice

PKT = 2400                       # 100 ms at 24 kHz, what the phone sends


def to24(samples16):
    """Linear 16 kHz -> 24 kHz."""
    out = []
    for i in range(int(len(samples16) * 1.5)):
        x = i / 1.5;a = int(x);b = min(a + 1, len(samples16) - 1);out.append(samples16[a] + (samples16[b] - samples16[a]) * (x - a))
    return out


def packets(samples16):
    raw = V.pcm(to24(samples16))
    return [raw[i:i + PKT * 2] for i in range(0, len(raw) - PKT * 2 + 1, PKT * 2)]


def say(kind, db, seconds=1.4, seed=0):
    return packets(V.mix(V.voice(kind, seconds, db, seed), V.room(seconds, seed + 3)))


def hush(seconds=1.0, seed=0):
    return packets(V.room(seconds, seed))


def run_call(d, with_voice, scenes):
    """scenes: [(kind, db, text)]; a hush of 1 s before. Returns the records."""
    recognizer = T.FakeRecognizer([t for _, _, t in scenes])
    worker = ear_shadow.EarWorker(lambda: recognizer)
    assert worker.wait_ready(5)
    script, wav = [], []
    for p in hush(1.0, 99):script.append('quiet');wav.append(p)
    for kind, db, _ in scenes:
        pk = say(kind, db, seed=len(wav))
        for i, p in enumerate(pk):script.append('onset' if i == 0 else 'end' if i == len(pk) - 1 else 'speech');wav.append(p)
        for p in hush(0.4, len(wav)):script.append('quiet');wav.append(p)
    ear = ear_shadow.ShadowEar(worker, ear_shadow.controller_decider(d.controller), detector=T.ScriptedDetector(script), clock=d.clock,
                               voice=near_voice.NearGate(speaking=lambda: ear.current is not None, clock=d.clock, act=False) if with_voice else None,
                               portion=lambda: T.PORTION)
    records = []
    for i, p in enumerate(wav):
        ear.feed(p, input_ms=100 * (i + 1))
    records = T.drain(ear, len(scenes))
    return ear, records


def test_off_nothing_is_kept_and_no_voice_key(tmp_path):
    d = T.H.Dictation(tmp_path / 'a', T.ANSWER)
    ear, records = run_call(d, False, [('own', -22, T.FULL)])
    assert 'voice' not in records[0] and not getattr(ear, 'voice_buf', None)


def test_shadow_puts_voice_in_the_record_and_tells_a_friend_from_the_speaker(tmp_path):
    d = T.H.Dictation(tmp_path / 'b', T.ANSWER)
    scenes = [('own', -22, T.FULL)] * 4 + [('other', -36, 'а вы вчера видели матч')]
    ear, records = run_call(d, True, scenes)
    assert len(records) == 5 and all('voice' in r for r in records)
    assert records[0]['voice']['aligned'] is True and records[-1]['voice']['aligned'] is False
    assert records[-1]['voice']['kind'] == 'other', records[-1]['voice']
    assert records[-1]['voice']['kind'] != records[1]['voice']['kind']
    assert 'text' not in records[-1]['voice'], 'numbers only'


def test_voice_does_not_change_kind_or_reason_of_the_record(tmp_path):
    d = T.H.Dictation(tmp_path / 'c', T.ANSWER)
    _, on = run_call(d, True, [('own', -22, T.FULL)])
    d2 = T.H.Dictation(tmp_path / 'c2', T.ANSWER)
    _, off = run_call(d2, False, [('own', -22, T.FULL)])
    assert [(r['kind'], r['reason']) for r in on] == [(r['kind'], r['reason']) for r in off]


def test_the_audio_buffer_is_bounded_and_cut_by_utterance(tmp_path):
    d = T.H.Dictation(tmp_path / 'e', T.ANSWER)
    ear, records = run_call(d, True, [('own', -22, T.FULL)] * 3)
    assert ear.voice_bytes_max <= ear_shadow.VOICE_BUFFER_S * 32000 + 32000
    assert not ear.voice_open, 'the utterance pcm is released at its end'


def test_a_broken_voice_judge_costs_only_the_voice(tmp_path):
    d = T.H.Dictation(tmp_path / 'f', T.ANSWER)

    class Bad:
        def on_audio(self, pcm):raise RuntimeError('x')
        def on_utterance(self, *a, **k):raise RuntimeError('y')
    recognizer = T.FakeRecognizer([T.FULL])
    worker = ear_shadow.EarWorker(lambda: recognizer);worker.wait_ready(5)
    ear = ear_shadow.ShadowEar(worker, ear_shadow.controller_decider(d.controller), detector=T.ScriptedDetector(['onset', 'speech', 'end']), clock=d.clock, voice=Bad())
    for i in range(3):ear.feed(T.packet(i), input_ms=100 * (i + 1))
    [rec] = T.drain(ear, 1)
    assert not ear.off and rec['kind'] == 'ack' and 'voice' not in rec


def test_for_call_builds_it_only_with_the_raw_setting(tmp_path):
    d = T.H.Dictation(tmp_path / 'g', T.ANSWER)
    worker = ear_shadow.EarWorker(lambda: T.FakeRecognizer([]))
    mk = lambda s: ear_shadow.for_call({'local_ear': 'shadow', **s}, d.controller, detector_factory=lambda: T.ScriptedDetector([]), worker=worker)
    assert mk({}).voice is None and mk({'near_voice': 'off'}).voice is None
    sh, act = mk({'near_voice': 'shadow'}), mk({'near_voice': 'act'})
    assert sh.voice is not None and sh.voice.act is False and act.voice.act is True


def test_w10_act_wires_the_gate_into_the_controller_and_shadow_does_not(tmp_path):
    """w10 item 10: near_voice «act» is the controller's ``speaker_gate`` (read by ControlledMedia.hold and _tempo_stuck); the holds are bounded."""
    from echo_sync import near_voice
    worker = ear_shadow.EarWorker(lambda: T.FakeRecognizer([]))
    def mk(s):
        d = T.H.Dictation(tmp_path / ('g' + s.get('near_voice', 'x')), T.ANSWER)
        ear_shadow.for_call({'local_ear': 'shadow', **s}, d.controller, detector_factory=lambda: T.ScriptedDetector([]), worker=worker)
        return d.controller
    assert getattr(mk({'near_voice': 'shadow'}), 'speaker_gate', None) is None and getattr(mk({}), 'speaker_gate', None) is None
    gate = mk({'near_voice': 'act'}).speaker_gate
    assert gate is not None and gate.act and near_voice.OTHER_FIRST_HOLD_S <= 12 and near_voice.UNKNOWN_HOLD_S <= 30 and near_voice.OTHER_RUN_CAP_S <= 20
