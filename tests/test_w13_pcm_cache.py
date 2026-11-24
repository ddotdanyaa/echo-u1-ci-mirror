"""W13 item 3: the cue's PCM goes back at once (0.45 s on the laptop instead of 0.05: ``cached`` wrote and trimmed 1677 files twice before it
returned). Writing and trimming are in the background, the trim at most once a minute, one walk of the directory."""
import threading
import time

from echo_sync import pcm_cache


def test_cached_returns_the_pcm_before_the_write(tmp_path, monkeypatch):
    cache = pcm_cache.PcmCache(tmp_path, max_bytes=10 ** 6)
    gate = threading.Event()
    real = cache.put
    monkeypatch.setattr(cache, 'put', lambda *a, **k: (gate.wait(5), real(*a, **k))[1])
    began = time.monotonic()
    assert pcm_cache.cached(cache, lambda text: b'\x02\x00' * 10, 'Один', 'v', 24000) == b'\x02\x00' * 10
    assert time.monotonic() - began < 0.5, 'the write did not hold the PCM'
    gate.set()
    assert cache.flush(5)
    assert cache.get('Один', 'v', 24000) == b'\x02\x00' * 10


def test_the_background_trim_runs_at_most_once_a_minute(tmp_path):
    now = [1000.0]
    cache = pcm_cache.PcmCache(tmp_path, max_bytes=10 ** 6, clock=lambda: now[0])
    walks = []
    real = cache._files
    cache._files = lambda: (walks.append(1), real())[1]
    for i in range(5):
        pcm_cache.cached(cache, lambda text: b'\x02\x00' * 10, f'Текст {i}', 'v', 24000)
        assert cache.flush(5)
    assert len(walks) == 1, walks
    now[0] += 61
    pcm_cache.cached(cache, lambda text: b'\x02\x00' * 10, 'Ещё', 'v', 24000)
    assert cache.flush(5) and len(walks) == 2


def test_one_walk_one_stat_per_file(tmp_path, monkeypatch):
    cache = pcm_cache.PcmCache(tmp_path, max_bytes=10 ** 6)
    for i in range(3):
        cache.put(f'Т {i}', 'v', 24000, b'\x00\x00' * 10)
    calls = []
    real = pcm_cache.Path.stat
    monkeypatch.setattr(pcm_cache.Path, 'stat', lambda self, *a, **k: (calls.append(self) if self.suffix == '.pcm' else None, real(self, *a, **k))[1])
    cache._trim()
    assert len(calls) <= 3, len(calls)
