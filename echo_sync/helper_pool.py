"""W6 item 10: one spare audio helper kept started while the line is idle (always, no switch). The next open takes it without
``start()``; a spare that died or is older than ``max_age_s`` is not taken (it is closed off the path) and the open goes the usual way.
Cause: offer_ms 5-11 s after a pause against 1.2 s warm (controlled_host.open_subscription, the helper start is in offer_ms).
U31: a spare nobody takes is renewed by the idle line itself, at RENEW_AT of ``max_age_s``: ``take`` refused one older than that, so the first open after a long idle (U31: ready at 15 s
against 1.8 s for the second) found none and paid the helper start; the next call's ``ensure`` came only at the end of a call."""
import asyncio
import time

from .timer_policy import SPARE_MAX_AGE_S


def alive(bridge):
    """A started helper whose process has not exited and that nobody closed."""
    if bridge is None or getattr(bridge,'_closed',False) or getattr(bridge,'closed',False) is True:return False
    try:process=bridge.process
    except Exception:return False
    return process is not None and getattr(process,'returncode',None) is None


RENEW_AT=0.5      # of ``max_age_s``: an idle spare is replaced by a started one at this age


class SpareHelper:
    def __init__(self,factory,*,max_age_s=SPARE_MAX_AGE_S,clock=time.monotonic,sleep=asyncio.sleep):
        self.factory,self.max_age_s,self.clock,self._sleep=factory,max_age_s,clock,sleep
        self.bridge=None;self.born=None;self._starting=None;self._keeper=None;self._tasks=set()

    def _fresh(self):
        return self.bridge is not None and alive(self.bridge) and self.clock()-self.born<=self.max_age_s

    def _spawn(self,coro):
        """A background task of the pool, held until it is done: the loop keeps only a weak reference to a task, so one nobody holds can be collected while it still waits («Task was destroyed but it is pending»).
        ``close`` ends what is left."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            coro.close()
            raise
        task = loop.create_task(coro)
        self._tasks.add(task);task.add_done_callback(self._tasks.discard)
        return task

    def ensure_later(self):
        """``ensure`` in the background (the end of a call: the next call finds a started helper). The task is the pool's, not the call's: it outlives the call, and ``close`` cancels it. None with no loop."""
        try:return self._spawn(self.ensure())
        except RuntimeError:return None

    async def ensure(self):
        """A live spare is there after this (one start at a time); a stale one is closed first. Errors stay here: no spare is no harm."""
        if self._fresh():self._watch();return self.bridge
        if self._starting is not None:return await self._starting
        stale,self.bridge=self.bridge,None
        if stale is not None:await _close(stale)
        self._starting=asyncio.ensure_future(self._start())
        try:return await self._starting
        finally:
            self._starting=None
            if self.bridge is not None:self._watch()

    async def _start(self):
        bridge=self.factory()
        try:await bridge.start()
        except Exception:
            await _close(bridge);return None
        self.bridge,self.born=bridge,self.clock();return bridge

    def _watch(self):
        """U31: one keeper per pool while a spare waits (a task of the loop that runs the calls, like the ``ensure`` at the end of a call)."""
        if self._keeper is None or self._keeper.done():
            try:self._keeper=asyncio.get_running_loop().create_task(self._keep())
            except RuntimeError:pass

    async def _keep(self):
        """Sleeps until the waiting spare is RENEW_AT of its age limit old, then replaces it; ends when nothing waits (taken: the call's end makes the next one)."""
        while self.bridge is not None:
            wait=self.born+self.max_age_s*RENEW_AT-self.clock()
            if wait>0:
                await self._sleep(wait);continue
            if await self._renew() is None:return

    async def _renew(self):
        stale,self.bridge=self.bridge,None
        if stale is not None:await _close(stale)
        if self._starting is not None:return await self._starting
        self._starting=asyncio.ensure_future(self._start())
        try:return await self._starting
        finally:self._starting=None

    def take(self):
        """The live spare (it is no longer kept), or None: none, dead or too old (that one is closed in the background)."""
        bridge,self.bridge=self.bridge,None
        if bridge is None:return None
        if alive(bridge) and self.clock()-self.born<=self.max_age_s:return bridge
        try:self._spawn(_close(bridge))
        except RuntimeError:pass
        return None

    async def close(self):
        keeper,self._keeper=self._keeper,None
        if keeper is not None and keeper is not asyncio.current_task():keeper.cancel()
        later=[task for task in self._tasks if task is not asyncio.current_task()]
        for task in later:task.cancel()
        if later:await asyncio.gather(*later,return_exceptions=True)
        bridge,self.bridge=self.bridge,None
        if bridge is not None:await _close(bridge)


async def _close(bridge):
    try:await bridge.close()
    except Exception:pass
