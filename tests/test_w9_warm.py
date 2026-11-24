"""w9-warm: the warm plan, the model pool, the material cache and the idle guard (echo_sync/warm.py). The real knowledge-base and classifier steps run."""
import asyncio
import os
import threading
import time

import pytest

from echo_sync import warm


def test_a_failing_step_is_recorded_and_the_rest_still_run():
    seen = []
    plan = [warm.Step('a', lambda: seen.append('a')), warm.Step('b', lambda: 1 / 0), warm.Step('c', lambda: seen.append('c'))]
    done = warm.run_plan(plan)
    assert seen == ['a', 'c'] and [d['ok'] for d in done] == [True, False, True] and done[1]['reason'] == 'ZeroDivisionError'


def test_start_plan_does_not_block_the_caller():
    gate, finished = threading.Event(), threading.Event()
    began = time.perf_counter()
    warm.start_plan([warm.Step('slow', gate.wait)], on_done=lambda r: finished.set())
    assert time.perf_counter() - began < 0.05 and not finished.is_set()
    gate.set()
    assert finished.wait(2)


def test_the_real_cold_steps_make_the_first_sentence_cheap():
    from echo_sync import classifier
    done = warm.run_plan(warm.default_steps('.'))
    assert {d['name']: d['ok'] for d in done} == {'reference_kb': True, 'classifier': True, 'material': True, 'instant': True, 'voice': True, 'vad': True, 'ear_model': True}
    began = time.perf_counter()
    classifier.analyze('Какой срок исковой давности по статье 196?', [], [])
    assert (time.perf_counter() - began) * 1000 < 30


def test_model_pool_hands_out_a_ready_model_and_refills():
    built = []
    class Model:
        def __init__(self):
            built.append(self); self.resets = 0
        def reset(self):
            self.resets += 1
    pool = warm.ModelPool(Model)
    pool.fill()
    assert len(built) == 1
    began = time.perf_counter()
    first = pool.take()
    assert time.perf_counter() - began < 0.01 and first is built[0] and first.resets == 1
    for _ in range(200):
        if len(pool.items) == 1:
            break
        time.sleep(0.01)
    assert len(pool.items) == 1 and len(built) == 2
    assert pool.take() is built[1]


def test_model_pool_empty_builds_on_the_spot_and_remembers_a_failure():
    n = []
    def factory():
        n.append(1)
        if len(n) > 1:
            raise OSError('x')
        return object()
    pool = warm.ModelPool(factory)
    assert pool.take() is not None
    for _ in range(200):
        if pool.failed:
            break
        time.sleep(0.01)
    assert pool.failed == 'OSError'


def test_material_cache_reads_once_and_again_when_a_file_changes(tmp_path):
    folder = tmp_path / 'materials'
    folder.mkdir()
    (folder / 'context.md').write_text('one')
    reads = []
    cache = warm.MaterialCache(lambda home: reads.append(1) or ((folder / 'context.md').read_text() if (folder / 'context.md').exists() else None))
    assert cache.load(tmp_path) == 'one' and cache.load(tmp_path) == 'one' and len(reads) == 1 and cache.hits == 1
    (folder / 'context.md').write_text('two!')
    assert cache.load(tmp_path) == 'two!' and len(reads) == 2
    (folder / 'context.md').unlink()
    assert cache.load(tmp_path) is None and len(reads) == 3   # a missing file is a new key: read again, never stale


def test_idle_guard_pings_only_the_idle_and_revives_a_dead_one():
    t = [0.0]
    g = warm.IdleGuard(clock=lambda: t[0])
    revived = []
    def dead():
        raise RuntimeError('gone')
    g.add('voice', lambda: None, idle_s=30)
    g.add('ear', dead, idle_s=30, revive=lambda: revived.append(1))
    t[0] = 20; g.touch('voice'); g.check()
    assert g.log == []
    t[0] = 55; g.check()
    assert g.log == [('voice', 'ok'), ('ear', 'failed')] and revived == [1]
    t[0] = 60; g.check()
    assert len(g.log) == 2                                    # just pinged: not again for another idle_s


def test_idle_guard_run_loop_checks_off_the_loop():
    async def main():
        g = warm.IdleGuard(clock=time.monotonic)
        hit = threading.Event()
        g.add('x', hit.set, idle_s=0)
        task = asyncio.create_task(g.run(0.01))
        await asyncio.sleep(0.1)
        task.cancel()
        return hit.is_set()
    assert asyncio.run(main())
