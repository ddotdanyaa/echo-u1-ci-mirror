"""UX-trace, part 2 through controlled_host.serve: the silence auto-repeat follows the PROFILE settings of the call.

The real serve() with a fake phone, a fake cloud helper and a fake SAPI worker, on virtual time (helpers_s6_fault.HostRig): a
listener asks, hears the first portion and then says nothing at all. What the phone receives is the oracle: how many times the
portion is spoken again on its own and how long after the previous one ended.
"""
import asyncio
import inspect
import json
import threading
from pathlib import Path

import helpers_s6_fault as F
from echo_sync import controlled_host, controlled_media
from echo_sync.controlled_media import ControlledMedia
from helpers_spoken_diagnostics import run_host

SILENCE = 90.0                  # far past every repeat the settings below allow


import pytest
pytestmark = pytest.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)


def settings_file(home, text=None, **values):
    folder = Path(home) / 'materials'
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'echo_settings.json').write_text(json.dumps(values) if text is None else text, encoding='utf-8')


async def silent_listener(host):
    """The listener asks, the first portion is spoken, and nobody says a word. Returns the frames that started a spoken cue."""
    await host.ask(F.DIRECT_QUESTION)
    await host.answer(F.DIRECT_ANSWER)
    await host.advance(SILENCE)
    return host.frames('response.audio_transcript.delta')


def gaps(starts):
    return [round(b.t - a.t, 2) for a, b in zip(starts, starts[1:])]


def run_silent_call(tmp_path, monkeypatch, **profile):
    """One call whose profile holds ``profile`` (or nothing); returns (texts of the cues, gaps between their starts)."""
    async def main():
        F.patch_clock(monkeypatch)
        async with F.HostRig(tmp_path, monkeypatch) as host:
            if profile:
                settings_file(host.home, **profile)
            await host.handshake()
            starts = await silent_listener(host)
            return [f.data['delta'] for f in starts], gaps(starts)
    return F.run(main)


def test_the_default_profile_repeats_a_silent_portion_once_after_six_seconds(tmp_path, monkeypatch):
    """Break: the host never passes the profile's values, so the call keeps ControlledMedia's own 3 s / 3 repeats."""
    texts, spacing = run_silent_call(tmp_path, monkeypatch)
    assert len(texts) == 2 and texts[0] == texts[1], texts
    assert len(spacing) == 1 and 6.0 <= spacing[0] <= 7.0, spacing        # the portion itself (~0.1 s) + 6 s of silence


def test_the_profile_decides_how_often_and_how_soon(tmp_path, monkeypatch):
    texts, spacing = run_silent_call(tmp_path, monkeypatch, repeat_seconds=2, max_auto_repeats=3)
    assert len(texts) == 4 and len(set(texts)) == 1, texts
    assert len(spacing) == 3 and all(2.0 <= gap <= 3.0 for gap in spacing), spacing


def test_zero_repeats_means_the_portion_waits_for_the_listener(tmp_path, monkeypatch):
    texts, spacing = run_silent_call(tmp_path, monkeypatch, max_auto_repeats=0)
    assert len(texts) == 1 and not spacing


def test_a_broken_settings_file_means_the_calm_defaults_and_the_call_goes_on(tmp_path, monkeypatch):
    async def main():
        F.patch_clock(monkeypatch)
        async with F.HostRig(tmp_path, monkeypatch) as host:
            settings_file(host.home, text='{not json')
            await host.handshake()
            starts = await silent_listener(host)
            assert len(starts) == 2 and 6.0 <= gaps(starts)[0] <= 7.0
            assert not host.errors()
    F.run(main)


def test_bad_values_are_replaced_by_the_defaults(tmp_path, monkeypatch):
    texts, spacing = run_silent_call(tmp_path, monkeypatch, repeat_seconds=0, max_auto_repeats=99)
    assert len(texts) == 2 and 6.0 <= spacing[0] <= 7.0


def test_a_read_of_the_settings_that_never_returns_still_opens_the_call_with_the_defaults(tmp_path, monkeypatch):
    """Break: a HANG in the read (a locked file, a dead network drive) holds the phone's first message for ever.

    A REAL event loop, like the same test of the lesson files: the virtual clock stands still while a thread job is in flight."""
    release, entered = threading.Event(), threading.Event()

    def hangs(path):
        entered.set()
        release.wait(30)                              # stands for a read that never returns (freed by the test at the end)
        return {'repeat_seconds': 1, 'max_auto_repeats': 9}
    monkeypatch.setattr(controlled_host, 'load_settings', hangs)
    seen = []
    real = controlled_host.ControlledMedia

    def spy(*args, **kwargs):
        seen.append(kwargs)
        return real(*args, **kwargs)
    monkeypatch.setattr(controlled_host, 'ControlledMedia', spy)

    async def main():
        F.patch_clock(monkeypatch)
        async with F.HostRig(tmp_path, monkeypatch) as host:
            try:
                await host.handshake()
                assert entered.is_set(), 'the stub was never reached: the test does not test the read'
                assert (seen[0]['repeat_seconds'], seen[0]['max_auto_repeats']) == (6, 1)
                assert not host.errors()
            finally:
                release.set()
    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
        runner.run(main())


def test_the_settings_are_read_off_the_event_loop(tmp_path, monkeypatch):
    threads = []
    real = controlled_host.load_settings

    def spy(path):
        threads.append(threading.current_thread())
        return real(path)
    monkeypatch.setattr(controlled_host, 'load_settings', spy)

    async def body(host):
        assert threads and all(t is not threading.current_thread() for t in threads)
    run_host(tmp_path, monkeypatch, body)


def test_controlled_media_keeps_its_own_defaults_when_nobody_passes_anything():
    """The G5 contract of the class itself (3 s, 3 repeats, tests/test_task2_stuck_endless_complete.py) is not what the PHONE gets: the
    host passes the profile's calm values. Break: someone moves the class default instead of the profile."""
    parameters = inspect.signature(ControlledMedia.__init__).parameters
    assert parameters['repeat_seconds'].default == 3
    assert parameters['max_auto_repeats'].default == controlled_media.MAX_AUTO_REPEATS == 3
