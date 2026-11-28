"""W6 item 10: a spare audio helper, started while the line is idle, is taken by the next open without start(); a dead or too old one is
not taken and the open goes the usual way. Cause: offer_ms 5-11 s after a pause against 1.2 s (controlled_host.py, the helper start)."""
import asyncio
import json
from types import SimpleNamespace
from echo_sync import helper_pool, settings
from echo_sync.controlled_host import open_subscription

def bridge_class(made):
    class Bridge:
        def __init__(self,*args,**kwargs):self.started=0;self.closed=False;self.stage=0;self.process=SimpleNamespace(returncode=None);made.append(self)
        async def start(self):self.started+=1;return self
        async def send(self,kind,payload):pass
        async def receive(self,timeout):
            self.stage+=1
            if self.stage==1:return ('O',b'v=0\n')
            if self.stage==2:return ('R',b'')
            return ('e',b'{"type":"session.started"}')
        async def close(self):self.closed=True;self.process.returncode=0
    return Bridge

def api():
    async def scoped(profile,fn):return {'auth':'subscription','transport':{'sdp':'answer'}}
    return SimpleNamespace(_run_scoped=scoped,WATCH_AUDIO_CONNECT_TIMEOUT_S=.05,WATCH_AUDIO_STUN=())

def test_a_live_spare_is_taken_without_start_and_a_new_one_follows():
    made=[];Bridge=bridge_class(made);now=[0.0]
    spare=helper_pool.SpareHelper(Bridge,max_age_s=1800,clock=lambda:now[0])
    async def run():
        await spare.ensure();assert len(made)==1 and made[0].started==1
        bridge=await open_subscription(api(),'p','unused',('python',{},(),''),bridge_factory=Bridge,spare=spare)
        assert bridge is made[0] and bridge.started==1 and len(made)==1, 'the spare is used as it is: no second start, no new helper'
        assert spare.take() is None
        await spare.ensure();assert len(made)==2 and made[1].started==1
    asyncio.run(run())

def test_a_dead_or_old_spare_is_not_taken_and_the_open_goes_the_usual_way():
    for kill in (True,False):
        made=[];Bridge=bridge_class(made);now=[0.0]
        spare=helper_pool.SpareHelper(Bridge,max_age_s=1800,clock=lambda:now[0])
        async def run():
            await spare.ensure()
            if kill:made[0].process.returncode=1
            else:now[0]=1801.0
            bridge=await open_subscription(api(),'p','unused',('python',{},(),''),bridge_factory=Bridge,spare=spare)
            await asyncio.sleep(0)
            assert bridge is made[1] and made[1].started==1 and made[0].closed
        asyncio.run(run())

def test_without_a_spare_nothing_changes():
    made=[];Bridge=bridge_class(made)
    bridge=asyncio.run(open_subscription(api(),'p','unused',('python',{},(),''),bridge_factory=Bridge))
    assert bridge is made[0] and made[0].started==1

def test_there_is_no_flag_the_spare_is_always_kept():
    assert 'spare_helper' not in settings.DEFAULTS and 'spare_helper' not in settings.resolve({'spare_helper':'off'})


def test_the_end_of_a_call_asks_for_the_next_spare_in_a_task_the_pool_holds():
    """«Task was destroyed but it is pending»: the ``ensure`` that the end of a call starts for the next call was a task nobody held (the loop keeps a weak reference), so a collection while the helper
    started destroyed it, and a loop that ended with it pending reported it. The pool holds it until it is done; ``close`` cancels what is left."""
    import gc
    made=[];Bridge=bridge_class(made)
    class Slow(Bridge):
        async def start(self):
            await asyncio.sleep(3600);return await super().start()
    spare=helper_pool.SpareHelper(Slow)
    async def run():
        task=spare.ensure_later()
        await asyncio.sleep(0);gc.collect();await asyncio.sleep(0)
        assert task in spare._tasks and not task.done(), 'the pool holds its background task while the helper starts'
        await spare.close()
        assert task.done() and not spare._tasks, 'close ends what is left of it'
        assert spare.bridge is None
    asyncio.run(run())
