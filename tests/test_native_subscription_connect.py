"""Reuse upstream negotiation: the default order of a real call is host candidates first with ONE STUN retry (as before CL1); STUN
is the retry (``controlled_host.ice_tries``: the one order, no switch).

(CL1 made STUN first the default; its review found that the live log of 2 Nov has 39 of 39 opens connected with host candidates
alone and that STUN adds its gathering to the offer phase of every open, so the order went back. The fallback rule is pinned in
test_stun_first.py.)"""
import asyncio
import json
from types import SimpleNamespace
from echo_sync.controlled_host import open_subscription

def test_one_stun_retry_after_unreachable_host_candidates_closes_first_helper():
    made=[];minted=[]
    class Bridge:
        def __init__(self,*args,**kwargs):self.stun=[];self.stage=0;self.closed=False;made.append(self)
        async def start(self):pass
        async def send(self,kind,payload):
            if kind=='C':self.stun=json.loads(payload)['stun']
        async def receive(self,timeout):
            self.stage+=1
            if self.stage==1:return ('O',b'v=0\n')
            if not self.stun:await asyncio.sleep(.002);raise asyncio.TimeoutError()
            if self.stage==2:return ('R',b'')
            return ('e',b'{"type":"session.started"}')
        async def close(self):self.closed=True
    async def scoped(profile,fn):minted.append(profile);return {'auth':'subscription','transport':{'sdp':'answer'}}
    api=SimpleNamespace(_run_scoped=scoped,WATCH_AUDIO_CONNECT_TIMEOUT_S=.01,WATCH_AUDIO_STUN=('stun:example.test:19302',))
    async def run():
        try:await open_subscription(api,'echo-sync','unused',('python',{},(),''),bridge_factory=Bridge)
        except TimeoutError:pass
        else:raise AssertionError('one try: host candidates alone do not connect')
        bridge=await open_subscription(api,'echo-sync','unused',('python',{},(),''),bridge_factory=Bridge,attempt=1)      # the retry of the wire's loop
        assert len(made)==2 and made[0].closed and not bridge.closed
        assert minted==['echo-sync','echo-sync']
        assert made[0].stun==[] and made[1].stun==['stun:example.test:19302']
        await bridge.close()
    asyncio.run(run())

def test_one_host_candidate_retry_after_a_timeout_with_stun_closes_first_helper():
    made=[];minted=[]
    class Bridge:
        def __init__(self,*args,**kwargs):self.stun=[];self.stage=0;self.closed=False;made.append(self)
        async def start(self):pass
        async def send(self,kind,payload):
            if kind=='C':self.stun=json.loads(payload)['stun']
        async def receive(self,timeout):
            self.stage+=1
            if self.stage==1:return ('O',b'v=0\n')
            if not self.stun:await asyncio.sleep(.002);raise asyncio.TimeoutError()
            if self.stage==2:return ('R',b'')
            return ('e',b'{"type":"session.started"}')
        async def close(self):self.closed=True
    async def scoped(profile,fn):minted.append(profile);return {'auth':'subscription','transport':{'sdp':'answer'}}
    api=SimpleNamespace(_run_scoped=scoped,WATCH_AUDIO_CONNECT_TIMEOUT_S=.01,WATCH_AUDIO_STUN=('stun:example.test:19302',))
    async def run():
        try:await open_subscription(api,'echo-sync','unused',('python',{},(),''),bridge_factory=Bridge,attempt=0)
        except TimeoutError:pass
        else:raise AssertionError('one try: host candidates alone do not connect')
        bridge=await open_subscription(api,'echo-sync','unused',('python',{},(),''),bridge_factory=Bridge,attempt=1)
        assert len(made)==2 and made[0].closed and not bridge.closed
        assert minted==['echo-sync','echo-sync']
        assert made[0].stun==[] and made[1].stun==['stun:example.test:19302']
        await bridge.close()
    asyncio.run(run())
