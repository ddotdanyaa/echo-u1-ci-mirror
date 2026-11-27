"""c24-c item 1: a repeat of an unchanged portion is the sound already made: no new synthesis (nor a model call, nor a lookup). The host's synthesizer of a call keeps what it made
(``pcm_cache.CallMemo``): another text, another voice key (voice, ending, speech text) is synthesized again; a render that failed keeps nothing. Nothing here is a measurement of a call."""
import ast
import logging
from pathlib import Path

import pytest

import echo_sync
import test_h3_tempo as H
from echo_sync import pcm_cache


@pytest.fixture(autouse=True)
def quiet():
    logging.disable(logging.CRITICAL)
    yield
    logging.disable(logging.NOTSET)


def host_like(rig, memo, voice='v'):
    """The host's ``synthesize`` (controlled_host.py) over the rig's voice: ``pcm_cache.cached`` with the call's memo, no disk cache."""
    renders = []

    async def synthesize(text, end=None):
        def render(said):
            renders.append(said)
            return b'\x00\x40' * 12000
        return pcm_cache.cached(None, render, text, f'{voice}|{end}', 24000, memo)
    rig.w.wire.synthesize = synthesize
    return renders


def test_silence_repeats_the_portion_with_the_sound_already_made(monkeypatch):
    rig = H.Rig(monkeypatch, **H.WAIT_OF_H3)
    try:
        memo = pcm_cache.CallMemo()
        renders = host_like(rig, memo)
        rig.first_portion()
        runs, lookups = len(rig.fake.runs) if rig.fake else 0, len(rig.w.lookup_calls)
        rig.pump(rig.c._repeat_wait() + 1.5)
        assert rig.said() == [H.HEAD, H.HEAD], rig.said()
        assert renders == [H.HEAD] and memo.reused == 1, renders       # the repeat: no synthesis
        assert (len(rig.fake.runs) if rig.fake else 0, len(rig.w.lookup_calls)) == (runs, lookups)
    finally:
        rig.close()


def test_the_memo_is_bounded_and_keyed_by_the_whole_text_and_the_voice():
    memo = pcm_cache.CallMemo(keep=3)
    made = []

    def render(said):
        made.append(said)
        return b'\x00\x40' * 10
    for n in range(5):
        pcm_cache.cached(None, render, f'порция {n}', 'v', 24000, memo)
    assert len(memo.kept) == 3 and memo.reused == 0
    pcm_cache.cached(None, render, 'порция 4', 'v', 24000, memo)
    assert memo.reused == 1 and made.count('порция 4') == 1
    pcm_cache.cached(None, render, 'порция 0', 'v', 24000, memo)                 # gone from the memo: rendered again
    pcm_cache.cached(None, render, 'Порция 4', 'v', 24000, memo)                 # a letter changed: another text
    pcm_cache.cached(None, render, 'порция 4', 'v|fall', 24000, memo)            # E76: the lowered ending is another sound
    assert made.count('порция 0') == 2 and made.count('Порция 4') == 1 and made.count('порция 4') == 2


def test_a_failed_render_keeps_nothing():
    memo = pcm_cache.CallMemo()
    pcm_cache.cached(None, lambda said: b'', 'порция', 'v', 24000, memo)
    pcm_cache.cached(None, lambda said: b'\x00', 'порция', 'v', 24000, memo)      # odd length: no PCM16
    assert not memo.kept and memo.reused == 0


def test_the_host_synthesizes_through_the_memo_of_the_call():
    source = (Path(echo_sync.__file__).parent / 'controlled_host.py').read_text(encoding='utf-8')
    calls = [n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Call) and getattr(n.func, 'attr', None) == 'to_thread' and n.args
             and getattr(n.args[0], 'attr', None) == 'cached']
    assert len(calls) == 1 and getattr(calls[0].args[-1], 'id', None) == 'cue_memo', 'controlled_host.synthesize must pass the call memo'
    assert 'cue_memo=pcm_cache.CallMemo()' in source
