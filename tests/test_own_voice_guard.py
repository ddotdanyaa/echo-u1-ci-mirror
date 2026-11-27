"""WAVE 2 / Task E, ruling 2 (fix round on d4c15e9): the own-voice window must never reject a genuine repeat.

What the independent review found (both reviewers): DEF-ACK-20 judged «did the speech begin while the cue could be heard» on the
instant the provider ANNOUNCES the listener's turn (turn.created), and that announcement comes after the speech began (the review
measured 0.9-2.3 s after the start of the probe audio). The silence timer repeats a portion 3 s after the PCM end; a listener who
starts to repeat about then is not announced yet when the timer fires, so the auto-repeat is issued, the announcement lands inside
its window (also inside the ESTIMATED window of a cue that never played a single frame), the barge-in cuts the cue, and the CORRECT,
complete repeat is dropped as «own voice»: the cursor does not move, the portion comes back 3 s later, and a consistent listener
meets the same collision until the cap of automatic repeats makes the prompter go silent. The base accepts all of these. Every test
of the first version injected turn.created at the true start of the speech, so none could see it.

Rulings (coordinator): there is no drop (the key ``own_voice_guard`` is gone): the decision is computed and logged as
``reason=own_voice_suspect``, the cursor is not touched. The evidence (``_rule_own_voice``) is the listener's REAL speech start when the provider
carries it (``start_ms``, on the input-audio clock, against the position of the input audio at the first PCM frame of the cue); otherwise the cue must
have actually started playing and the turn must have been announced no sooner than ECHO_MIN_LAG_SECONDS after its first audio. A timer auto-repeat that collides with a turn in
progress is never turned into a rejection.

Time is injected (and virtual); only the one test through the real pacing of the transport waits.
"""
import asyncio
import base64
import json
import logging
import struct
import time
from pathlib import Path

import pytest

import helpers_s6_ack as H
from echo_sync import controlled_media, settings
from echo_sync.controlled_media import ControlledMedia, CUE_TAIL_SECONDS

# Production plan: «Вода кипит» | «при ста градусах Цельсия.» | «При ста градусах» | «вода кипит.»
ANSWER = 'Вода кипит при ста градусах Цельсия. При ста градусах вода кипит.'
VOICED = 1.2                           # a 4-word cue: how long its voice lasts
FIXTURES = Path(__file__).parent / 'fixtures'


def speaks(actions):
    return [a['text'] for a in actions if a['type'] == 'speak']


def auto_repeat(d):
    """The silence timer falls due and repeats the waiting portion: the cue it issues."""
    c = d.controller
    d.clock.now = max(d.clock.now, c.repeat_at)
    [cue] = [a for a in c.tick(now=d.clock()) if a['type'] == 'speak']
    return cue


def created_at(tid, text, start_ms=None, end_ms=None):
    turn = {'id': tid, 'role': 'user', 'transcript': text}
    if start_ms is not None:
        turn.update(start_ms=start_ms, end_ms=end_ms if end_ms is not None else start_ms + 200)
    return {'type': 'turn.created', 'turn': turn}


def done_at(tid, text, start_ms=None, end_ms=None):
    turn = {'id': tid, 'role': 'user', 'transcript': text}
    if start_ms is not None:
        turn.update(start_ms=start_ms, end_ms=end_ms if end_ms is not None else start_ms + 1000)
    return {'type': 'turn.done', 'turn': turn}


class Audio:
    """The input audio the phone streams in real time since ``origin`` (controller clock): the transport's count of it, in ms."""

    def __init__(self, d, origin=None):
        self.d = d
        self.origin = d.clock() if origin is None else origin
        d.controller.bind_input_clock(self.ms)

    def ms(self):
        return int(round((self.d.clock() - self.origin) * 1000))


# ====================================================================================================================
# 1. the reviewers' collision repros ADVANCE in the default mode
# ====================================================================================================================

def test_a_correct_repeat_that_collides_with_the_auto_repeat_advances(tmp_path):
    """probe_inline_repro.py: the listener was already speaking when the timer repeated the cue; the barge-in cut it; their complete
    and correct repeat used to be dropped as «own voice»."""
    d = H.Dictation(tmp_path / 'inline', ANSWER)
    c, portion = d.controller, d.current
    cue = auto_repeat(d)
    c.cue_started(cue, voiced_seconds=0.9)
    d.clock.advance(0.6)
    c.speech_started()
    c.provider(H.created('u', 'user', ''))
    d.clock.advance(1.0)
    out = c.provider(H.done('u', 'user', portion))
    assert d.index == 1 and speaks(out) == [d.chunks[1]], 'the correct repeat was rejected as our own voice'


@pytest.mark.parametrize('announced', [0.05, 0.2, 0.4, 0.55, 0.8, 1.4])
def test_a_repeat_announced_after_an_auto_repeat_that_never_played_a_frame_advances(tmp_path, announced):
    """probe_autorepeat_collision.py: the cue is issued, the transport has not sent a frame (nothing of it is audible), the provider
    announces the turn ``announced`` s later: the window of a cue that is not audible does not exist."""
    d = H.Dictation(tmp_path / 'never', ANSWER)
    c, portion = d.controller, d.current
    auto_repeat(d)
    d.clock.advance(announced)
    c.speech_started()
    c.provider(H.created('u-live', 'user', ''))
    d.clock.advance(1.6 - announced)
    out = c.provider(H.done('u-live', 'user', portion))
    assert d.index == 1 and speaks(out) == [d.chunks[1]], f'rejected {announced} s after a cue that never played'


def test_the_halves_of_a_split_repeat_are_joined_when_the_first_was_announced_inside_the_window(tmp_path):
    """probe_split_in_window.py: ACK-split x cue window. The first half is announced while the auto-repeat plays; it used to be
    forgotten as «our own voice», so the second half could not complete the repeat."""
    d = H.Dictation(tmp_path / 'split', ANSWER)
    assert d.say(d.current, gap=4.0).after == 1, 'precondition: the first cue is confirmed whole'
    d.clock.advance(1.0)
    c, portion = d.controller, d.current
    half1, half2 = ' '.join(portion.split()[:2]), ' '.join(portion.split()[2:])
    cue = auto_repeat(d)
    t0 = d.clock()
    c.cue_started(cue, voiced_seconds=0.9)
    d.clock.now = t0 + 0.5
    c.speech_started()
    c.provider(H.created('s1', 'user', ''))
    d.clock.now = t0 + 1.0
    c.provider(H.done('s1', 'user', half1))
    assert d.index == 1
    d.clock.now = t0 + 4.0
    c.speech_started()
    c.provider(H.created('s2', 'user', ''))
    d.clock.now = t0 + 5.0
    c.provider(H.done('s2', 'user', half2))
    assert d.index == 2, 'the second half did not complete the repeat'


def tone_pcm(voiced, tail):
    samples = [int(6000 * ((i // 12) % 2 * 2 - 1)) for i in range(int(24000 * voiced))] + [0] * int(24000 * tail)
    return struct.pack('<%dh' % len(samples), *samples)


@pytest.mark.parametrize('announce', [0.1, 0.6])
def test_through_the_transport_a_listener_already_speaking_when_the_timer_repeats_is_accepted(tmp_path, announce):
    """probe_wire_collision.py: NativeMediaSocket + ControlledMedia, real asyncio and real pacing. The auto-repeat is issued, the provider
    announces the listener's turn ``announce`` s later, the listener finishes a second after, with the correct repeat."""
    async def run():
        wire = H.Wire(tmp_path / f'wire-{announce}')
        pcm = tone_pcm(0.9, 0.3)

        async def synthesize(text, end=None):
            wire.synthesized.append(text)
            return pcm
        wire.socket.synthesize = synthesize
        try:
            await wire.begin(ANSWER, settle=False)
            for _ in range(100):                                        # the first cue plays to its end
                await asyncio.sleep(0.05)
                if not wire.socket.tasks:
                    break
            c = wire.controller
            portion = wire.chunks[wire.index]
            assert c.repeat_at is not None, 'precondition: the silence timer is armed after the cue'
            wire.skew = c.repeat_at - time.monotonic() + 0.01
            before, spoken = wire.index, len(wire.synthesized)
            await wire.socket.tick()                                     # the timer repeats the portion
            await asyncio.sleep(announce)
            await wire.socket.provider(H.created('u-live', 'user', ''))
            await asyncio.sleep(1.0)
            await wire.socket.provider(H.done('u-live', 'user', portion))
            await wire.settle(timeout=6.0)
            return before, wire.index, len(wire.synthesized) - spoken
        finally:
            await wire.close()
    before, after, synthesized = asyncio.run(run())
    assert after == before + 1 and synthesized >= 2, f'announced {announce} s after the repeat cue: cursor {before} -> {after}'


# ====================================================================================================================
# 2. shadow mode: the decision is still taken, logged, and does not change the cursor
# ====================================================================================================================

def echo_like(tmp_path, name, **kwargs):
    """The cue has really started (first frame at t0, voice lasts VOICED) and a turn that says the portion is announced 1.3 s later."""
    d = H.Dictation(tmp_path / name, ANSWER, **kwargs)
    c, portion = d.controller, d.current
    cue = auto_repeat(d)
    t0 = d.clock()
    c.cue_started(cue, voiced_seconds=VOICED)
    d.clock.now = t0 + 1.3
    c.speech_started()
    c.provider(H.created('echo', 'user', ''))
    d.clock.now = t0 + 2.0
    return d, portion


def test_in_shadow_mode_a_suspect_final_advances_and_is_logged_as_suspect(tmp_path, caplog):
    d, portion = echo_like(tmp_path, 'shadow')
    with caplog.at_level(logging.INFO, logger='echo-sync'):
        out = d.controller.provider(H.done('echo', 'user', portion))
    assert d.index == 1 and speaks(out) == [d.chunks[1]], 'the shadow mode changed the cursor'
    text = caplog.text
    assert 'reason=own_voice_suspect' in text and 'reason=own_voice ' not in text, text


def test_the_suspect_line_carries_numbers_only(tmp_path, caplog):
    d, portion = echo_like(tmp_path, 'private')
    with caplog.at_level(logging.INFO, logger='echo-sync'):
        d.controller.provider(H.done('echo', 'user', portion))
    line = [r.getMessage() for r in caplog.records if 'own_voice_suspect' in r.getMessage()][0]
    for word in portion.lower().replace('.', '').split():
        assert word not in line.lower(), f'the listener\'s words are in the log: {line}'
    assert 'evidence=announcement' in line


def test_in_shadow_mode_nothing_is_logged_for_a_repeat_outside_the_window(tmp_path, caplog):
    d = H.Dictation(tmp_path / 'outside', ANSWER)
    c, portion = d.controller, d.current
    cue = auto_repeat(d)
    t0 = d.clock()
    c.cue_started(cue, voiced_seconds=VOICED)
    d.clock.now = t0 + VOICED + CUE_TAIL_SECONDS + 0.5
    c.speech_started()
    c.provider(H.created('u', 'user', ''))
    d.clock.advance(1.0)
    with caplog.at_level(logging.INFO, logger='echo-sync'):
        c.provider(H.done('u', 'user', portion))
    assert d.index == 1 and 'own_voice' not in caplog.text


def test_in_shadow_mode_the_stable_partial_still_confirms_a_suspect_turn(tmp_path):
    """The early confirmation is not held back by a suspicion that is only logged."""
    d, portion = echo_like(tmp_path, 'shadow-partial')
    c = d.controller
    sent = ''
    for n, word in enumerate(portion.split(), 1):
        piece = ('' if not sent else ' ') + word
        sent += piece
        c.provider({'type': 'turn.delta', 'turn_id': 'echo', 'delta': piece, 'start_ms': n * 10, 'end_ms': n * 10 + 5})
    out = []
    for _ in range(10):
        d.clock.advance(0.1)
        out += c.tick(now=d.clock())
    assert d.index == 1 and speaks(out) == [d.chunks[1]]


# ====================================================================================================================
# 3. there is no drop: the echo is a witness, the key and the keyword are gone
# ====================================================================================================================

def test_the_minimum_lag_of_an_echo_is_a_named_second():
    assert controlled_media.ECHO_MIN_LAG_SECONDS == 1.0


def test_there_is_no_own_voice_key_and_no_keyword(tmp_path):
    assert 'own_voice_guard' not in settings.DEFAULTS
    with pytest.raises(TypeError):
        ControlledMedia(tmp_path / 'k.sqlite3', session_id='k', own_voice_guard='drop')


# ====================================================================================================================
# 6. the transport tells the controller where the input audio is
# ====================================================================================================================

def pcm_frame(seconds):      # U77: not digital silence: a quiet backlog (a burst of seconds at one instant) is given back by the queue trim on every call
    return base64.b64encode(b'\x40\x1f' * int(24000 * seconds)).decode('ascii')


def test_the_transport_counts_the_input_audio_it_forwards_and_the_controller_reads_it(tmp_path):
    async def run():
        wire = H.Wire(tmp_path / 'clock')
        try:
            assert wire.socket.input_ms() == 0
            await wire.socket.client({'type': 'input_audio_buffer.append', 'audio': pcm_frame(1.0)})
            await wire.socket.client({'type': 'input_audio_buffer.append', 'audio': pcm_frame(0.5)})
            return wire.socket.input_ms(), wire.controller.input_ms()
        finally:
            await wire.close()
    assert asyncio.run(run()) == (1500, 1500)


def test_a_cue_remembers_where_the_input_audio_was_at_its_first_frame(tmp_path):
    async def run():
        wire = H.Wire(tmp_path / 'first-frame', pcm_ms=200)
        try:
            await wire.socket.client({'type': 'input_audio_buffer.append', 'audio': pcm_frame(2.0)})
            await wire.begin(ANSWER, settle=False)
            for _ in range(200):
                if wire.audio_frames:
                    break
                await asyncio.sleep(0.01)
            assert wire.audio_frames, 'precondition: the first cue is playing'
            return wire.controller.cue_input_ms
        finally:
            await wire.close()
    assert asyncio.run(run()) == 2000


# ====================================================================================================================
# 7. the recorded event the design rests on
# ====================================================================================================================

def test_a_recorded_user_turn_carries_its_real_speech_start_on_the_input_audio_clock(tmp_path):
    """03_TESTS/gpt_live_webrtc/streaming_profit_turn_fenced.json (a real GPT-Live session): the turn.created of the listener carries
    start_ms/end_ms of its first fragment; the speech began at 1200 ms of the input audio, the announcement arrived 1519 ms after the
    audio began (0.3 s after the speech started: a lag the reviewers' 0.9-2.3 s include the 1.2 s of silence the probe audio opens with),
    and the finished turn's end_ms is not ahead of the audio that had been sent when it arrived."""
    recorded = json.loads((FIXTURES / 'provider_user_turn_20261025.json').read_text(encoding='utf-8'))
    c = ControlledMedia(tmp_path / 'rec.sqlite3', session_id='rec')
    first = recorded['events'][0]
    assert first['event']['type'] == 'turn.created'
    c.provider(first['event'])
    turn = c.ledger.snapshot(first['event']['turn']['id'])
    assert (turn['start_ms'], turn['end_ms']) == (1200, 1400)
    announced_on_the_input_clock = first['wall_ms'] - recorded['input_start_ms']
    assert announced_on_the_input_clock == 1519 and 0 <= announced_on_the_input_clock - turn['start_ms'] <= 400
    for item in recorded['events'][1:]:
        c.provider(item['event'])
    last = recorded['events'][-1]
    final = c.ledger.snapshot(last['event']['turn']['id'])
    assert final['final'] and final['start_ms'] == 1200 and final['end_ms'] == 6200
    assert final['end_ms'] <= (last['wall_ms'] - recorded['input_start_ms']) + controlled_media.INPUT_CLOCK_SLACK_MS
