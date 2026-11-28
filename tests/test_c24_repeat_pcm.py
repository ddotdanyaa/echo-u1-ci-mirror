"""c24-c item 1: a repeat of an unchanged portion is the sound already made: no new synthesis (nor a model call, nor a lookup). The host's synthesizer of a call keeps what it made
(``pcm_cache.PcmCache``, its memory of the call): another text, another voice key (voice, ending, speech text) is synthesized again; a render that failed keeps nothing. Nothing here is a measurement of a call."""
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
    """The host's ``synthesize`` (controlled_host.py) over the rig's voice: ``pcm_cache.cached`` over the call's cache (the memory alone, no disk)."""
    renders = []

    async def synthesize(text, end=None):
        def render(said):
            renders.append(said)
            return b'\x00\x40' * 12000
        return pcm_cache.cached(memo, render, text, f'{voice}|{end}', 24000)
    rig.w.wire.synthesize = synthesize
    return renders


def test_silence_repeats_the_portion_with_the_sound_already_made(monkeypatch):
    rig = H.Rig(monkeypatch, **H.WAIT_OF_H3)
    try:
        memo = pcm_cache.PcmCache()
        renders = host_like(rig, memo)
        rig.first_portion()
        runs, lookups = len(rig.fake.runs) if rig.fake else 0, len(rig.w.lookup_calls)
        rig.pump(rig.c._silence().wait + 1.5)
        assert rig.said() == [H.HEAD, H.HEAD], rig.said()
        assert renders == [H.HEAD] and memo.reused == 1, renders       # the repeat: no synthesis
        assert (len(rig.fake.runs) if rig.fake else 0, len(rig.w.lookup_calls)) == (runs, lookups)
    finally:
        rig.close()


def test_the_memo_is_bounded_and_keyed_by_the_whole_text_and_the_voice():
    memo = pcm_cache.PcmCache(keep=3)
    made = []

    def render(said):
        made.append(said)
        return b'\x00\x40' * 10
    for n in range(5):
        pcm_cache.cached(memo, render, f'порция {n}', 'v', 24000)
    assert len(memo.kept) == 3 and memo.reused == 0
    pcm_cache.cached(memo, render, 'порция 4', 'v', 24000)
    assert memo.reused == 1 and made.count('порция 4') == 1
    pcm_cache.cached(memo, render, 'порция 0', 'v', 24000)                 # gone from the memo: rendered again
    pcm_cache.cached(memo, render, 'Порция 4', 'v', 24000)                 # a letter changed: another text
    pcm_cache.cached(memo, render, 'порция 4', 'v|fall', 24000)            # E76: the lowered ending is another sound
    assert made.count('порция 0') == 2 and made.count('Порция 4') == 1 and made.count('порция 4') == 2


def test_a_failed_render_keeps_nothing():
    memo = pcm_cache.PcmCache()
    pcm_cache.cached(memo, lambda said: b'', 'порция', 'v', 24000)
    pcm_cache.cached(memo, lambda said: b'\x00', 'порция', 'v', 24000)      # odd length: no PCM16
    assert not memo.kept and memo.reused == 0


def test_the_host_synthesizes_through_the_one_cache_of_the_call():
    source = (Path(echo_sync.__file__).parent / 'controlled_host.py').read_text(encoding='utf-8')
    calls = [n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Call) and getattr(n.func, 'attr', None) == 'to_thread' and n.args
             and getattr(n.args[0], 'attr', None) == 'cached']
    assert len(calls) == 1 and any(getattr(a, 'id', None) == 'cue_cache' for a in calls[0].args), 'controlled_host.synthesize must pass the call cache'
    assert 'CallMemo' not in source and 'cue_memo' not in source, 'one cache of the call, not a cache and a memo'


def test_one_cache_serves_memory_then_disk_then_render(tmp_path):
    cache = pcm_cache.PcmCache(tmp_path)
    made = []

    def render(said):
        made.append(said)
        return b'\x00\x40' * 10
    a = pcm_cache.cached(cache, render, 'порция', 'v', 24000)
    assert pcm_cache.cached(cache, render, 'порция', 'v', 24000) == a and cache.reused == 1 and made == ['порция']      # memory
    assert cache.flush(5)
    fresh = pcm_cache.PcmCache(tmp_path)                                                                                 # the next call: the disk, no render
    assert pcm_cache.cached(fresh, render, 'порция', 'v', 24000) == a and made == ['порция'] and fresh.reused == 0
    assert pcm_cache.PcmCache().get('порция', 'v', 24000) is None and not pcm_cache.PcmCache().put('x', 'v', 24000, a)    # no folder: no disk
