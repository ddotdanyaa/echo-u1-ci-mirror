# factory-backlog-id: U209
import asyncio
from echo_sync.native_prefetch import EarlyLookup

def test_early_lookup_recheck():
    fetch_list = []

    def fetch(question):
        fetch_list.append(question)
        return ['x']

    async def trace(*a, **k):
        pass

    async def run_test():
        el = EarlyLookup(fetch, trace, enabled=True)
        el.observe_ear('t1', 'сколько стоит доставка', now=0.0)
        await el.tick(now=0.0)
        await asyncio.sleep(0)

        el.observe('t1', 'сколько стоит доставка в Москву', now=1.0)
        await el.tick(now=1.0 + el.stable_seconds + 0.1)
        await asyncio.sleep(0)

        assert fetch_list == ['сколько стоит доставка', 'сколько стоит доставка в Москву']
        assert el.task_signature == el.signature

        res = await el.resolve('t1', 'сколько стоит доставка в Москву')
        assert res == ['x']
        assert len(fetch_list) == 2

    asyncio.run(run_test())
