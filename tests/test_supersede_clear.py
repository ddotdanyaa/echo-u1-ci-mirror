"""WAVE 2 / Task B, DEF-STATE-08 (P2, in NativeMediaSocket): a cue that replaces a half-played one clears the phone first.

A command that arrives while a portion is being played (a final with no turn.created before it, e.g. «повтори») used to start the new
response on top of the old one: two responses were in flight on the phone, neither finished nor cleared. The cancel branch of the
transport always sent ``output_audio_buffer.clear``; the speak branch that supersedes a playing cue did not.
"""
import asyncio

import helpers_s6_ack as H

ANSWER = 'Свойство тела сопротивляться изменению своего движения. Это называется инерцией. Чем больше масса, тем сильнее инерция.'


def kinds(wire):
    return [f['type'] for f in wire.sent if f['type'] in ('response.created', 'response.done', 'output_audio_buffer.clear')]


def test_a_cue_that_replaces_a_playing_one_clears_the_phone_first(tmp_path):
    async def run():
        wire = H.Wire(tmp_path / 'supersede', pcm_ms=600)
        try:
            await wire.begin(ANSWER, settle=False)
            for _ in range(300):
                if wire.audio_frames >= 3:
                    break
                await asyncio.sleep(0.01)
            assert 3 <= wire.audio_frames < 30, 'precondition: the first portion is half played'
            before = kinds(wire)
            await wire.socket.provider(H.done('r1', 'user', 'повтори'))          # no turn.created before it
            await wire.settle(timeout=6.0)
            after = kinds(wire)[len(before):]
            assert after[:2] == ['output_audio_buffer.clear', 'response.created'], f'the new response began on top of the old one: {after}'
            assert after.count('response.created') == 1 and after[-1] == 'response.done', after
        finally:
            await wire.close()
    asyncio.run(run())


def test_a_cue_that_follows_a_finished_one_needs_no_clear(tmp_path):
    async def run():
        wire = H.Wire(tmp_path / 'plain')
        try:
            await wire.begin(ANSWER)
            cleared = wire.cleared()
            await wire.user('повтори', tid='r1', pair=False)
            assert wire.cleared() == cleared, 'nothing was playing: nothing to clear'
            assert wire.synthesized[-1] == wire.chunks[0]
        finally:
            await wire.close()
    asyncio.run(run())
