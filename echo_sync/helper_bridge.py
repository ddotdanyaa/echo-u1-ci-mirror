"""Test adapter over the installed Conduit Watch helper, not a voice engine.

No server or persistent setting. The child receives SDP/PCM, never OAuth.
Product routing remains unchanged until the media contract is accepted.
"""
import asyncio,collections,contextlib,logging,os,struct,sys
import threading
from .timer_policy import CLOSE_WAIT_S, PEER_WAIT_S

logger=logging.getLogger('echo-sync')

MAX_FRAME=1024*1024
KINDS=set('CAPEQORpexX')
# DEF-FAULT-11: how long ONE write to the helper may stay pending before the pipe counts as stalled (a helper that stopped reading its
# stdin never lets drain() return). Audio flows at 48 kB/s and the transport buffers 64 kB, so a pending write means the helper has not
# read for at least a second; 5 s later the conversation is dead anyway (nothing the listener says reaches the cloud).
HELPER_WRITE_TIMEOUT_S=5.0
# The most bytes that may wait un-written: 1 MiB is 21 s of 24 kHz 16-bit PCM, several times what can pile up while a stalled write is
# still inside its timeout, so only a stall can overflow it. Overflow is a stall too (bounded memory, and not a queue that grows for ever).
HELPER_QUEUE_MAX_BYTES=1<<20
# close(): how long the quit frame may take to be written (a helper that stopped reading never takes it), how long the helper then has
# to leave by itself, and how long it has to die after terminate() (then kill()).
CLOSE_QUIT_S=1.0
CLOSE_KILL_S=3.0

def helper_environment(source):
 # Same restricted subprocess boundary as Conduit's Watch runtime; plus
 # PYTHONPATH for the already isolated diagnostic wheel directory.
 names={'PATH','SYSTEMROOT','WINDIR','TEMP','TMP','TMPDIR','HOME','USERPROFILE',
        'HOMEDRIVE','HOMEPATH','LANG','TZ','PYTHONPATH','PYTHONHOME'}
 return {key:value for key,value in source.items() if key.upper() in names or key.startswith('LC_')}

class SettledInput:
 """Probe-only partial boundary; never a substitute for provider-final ASR.

 An assistant completion from a retired turn cannot finalize words that
 arrive later. A real input delta reopens the tentative boundary.
 """
 def __init__(self):self.parts=[];self.last=None;self.ended=False
 def input(self,text,at):self.parts.append(text);self.last=at;self.ended=False
 def assistant_done(self):self.ended=bool(self.parts)
 def settled(self,at,*,input_ended):
  if input_ended and self.ended and self.last is not None and at-self.last>=.4:return ''.join(self.parts).strip() or None
  return None

def pack_frame(kind,payload=b''):
 if kind not in KINDS or len(kind)!=1:raise ValueError('unknown helper kind')
 if len(payload)>MAX_FRAME:raise ValueError('helper frame size')
 return kind.encode('ascii')+struct.pack('>I',len(payload))+payload

async def read_frame(reader):
 try:header=await reader.readexactly(5)
 except asyncio.IncompleteReadError as error:
  if not error.partial:return None
  raise ValueError('truncated helper header') from None
 kind=header[:1].decode('ascii');size=struct.unpack('>I',header[1:])[0]
 if kind not in KINDS:raise ValueError('unknown helper kind')
 if size>MAX_FRAME:raise ValueError('helper frame size')
 try:payload=await reader.readexactly(size)
 except asyncio.IncompleteReadError:raise ValueError('truncated helper payload') from None
 return kind,payload

class BoundedWriter:
 """Writes to the helper pipe without ever making a caller wait for it (DEF-FAULT-11).

 ``put`` only queues (bounded: HELPER_QUEUE_MAX_BYTES) and returns at once; one task writes the frames in order, each write cut after
 HELPER_WRITE_TIMEOUT_S. A helper that stops reading its stdin never lets ``drain()`` return: before, that wait sat in the loop that reads
 the phone, so «стоп» was never read and nothing timed out. A write that times out, raises, or a queue that overflows is a FAILURE, reported
 once to ``on_failure(reason)`` with a fixed token (never free text): ``helper_write_stalled``, ``helper_write_failed``,
 ``helper_queue_full``. After it nothing is queued or written: the channel is dead, the caller closes the call. Cancelling a timed-out write
 cannot corrupt the framing: a frame is handed to the transport whole by ``write`` and only the wait for the buffer to drain is cut.
 """
 def __init__(self,send,*,on_failure=None,timeout=None,max_bytes=None,closer=None):
  self._send=send;self._on_failure=on_failure;self._closer=closer      # closer: what ``close`` also awaits (the pipe behind it)
  self.timeout=HELPER_WRITE_TIMEOUT_S if timeout is None else timeout
  self.max_bytes=HELPER_QUEUE_MAX_BYTES if max_bytes is None else max_bytes
  self._frames=collections.deque();self._queued=0;self._wake=asyncio.Event();self._task=None
  self.failed=None;self.closed=False
 @property
 def queued_bytes(self):return self._queued
 def start(self):
  if self._task is None and not self.closed:self._task=asyncio.get_running_loop().create_task(self._pump())
  return self
 def put(self,kind,payload=b''):
  """Queue one frame. False (and nothing queued) once the writer has failed or was closed, or when this frame overflows the queue."""
  if self.failed or self.closed:return False
  size=len(payload)+5
  if self._queued+size>self.max_bytes:self._fail('helper_queue_full');return False
  self._frames.append((kind,payload,size));self._queued+=size;self._wake.set();return True
 async def send(self,kind,payload=b''):self.put(kind,payload)      # what the wire calls: only queues
 def _fail(self,reason):
  if self.failed or self.closed:return
  self.failed=reason;queued=self._queued;self._frames.clear();self._queued=0
  logger.warning('echo-sync helper write failure reason=%s queued_bytes=%s',reason,queued)
  try:current=asyncio.current_task()
  except RuntimeError:current=None
  if self._task is not None and self._task is not current:self._task.cancel()
  if self._on_failure is not None:
   try:self._on_failure(reason)
   except Exception as error:logger.warning('echo-sync helper write failure callback failed type=%s',type(error).__name__)
 async def _pump(self):
  while True:
   while not self._frames:
    self._wake.clear();await self._wake.wait()
   kind,payload,size=self._frames[0]            # stays queued (and counted) until it is written
   try:await asyncio.wait_for(self._send(kind,payload),self.timeout)
   except asyncio.CancelledError:raise
   except asyncio.TimeoutError:self._fail('helper_write_stalled');return
   except Exception as error:
    logger.warning('echo-sync helper write raised type=%s',type(error).__name__);self._fail('helper_write_failed');return
   if self.failed or self.closed:return
   self._frames.popleft();self._queued-=size
 async def close(self):
  """Stop writing. Returns at once, even when a write is stuck: that write is cancelled, not waited for."""
  self.closed=True;self._frames.clear();self._queued=0
  task,self._task=self._task,None
  if task is not None:
   task.cancel();await asyncio.gather(task,return_exceptions=True)
  if self._closer is not None:return await self._closer()

class HelperBridge:
 def __init__(self,helper,*,python=None,environment=None,flags=()):
  self.helper=str(helper);self.process=None;self.stderr=b''
  self.python=str(python or sys.executable);self.environment=helper_environment(os.environ if environment is None else environment);self.flags=tuple(flags)
 async def start(self):
  self.process=await asyncio.create_subprocess_exec(self.python,'-X','utf8','-X','faulthandler',*self.flags,self.helper,
   stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,
   env=self.environment,
   creationflags=0x08000000 if os.name=='nt' else 0)
  return self
 async def send(self,kind,payload=b''):
  self.process.stdin.write(pack_frame(kind,payload));await self.process.stdin.drain()
 async def receive(self,timeout=PEER_WAIT_S):return await asyncio.wait_for(read_frame(self.process.stdout),timeout)
 async def close(self):
  if not self.process:return
  if self.process.returncode is None:
   # The quit frame queues behind whatever a helper that stopped reading never took: bounded, or close() hangs with it (DEF-FAULT-11/12).
   with contextlib.suppress(BrokenPipeError,ConnectionResetError,asyncio.TimeoutError):await asyncio.wait_for(self.send('Q'),CLOSE_QUIT_S)
   # Its daemon reader otherwise blocks in buffered stdin.read while the
   # interpreter finalizes, causing _enter_buffered_busy on Windows.
   self.process.stdin.close()
   try:_,self.stderr=await asyncio.wait_for(self.process.communicate(),CLOSE_WAIT_S)
   except RuntimeError:
    # c22-reviewfix: a reader still waits on stdout (local mode closes a stalled channel while the call's reader is in receive): communicate()
    # cannot read that pipe. The child is ended without reading it, and the reader then meets EOF.
    with contextlib.suppress(ProcessLookupError):self.process.terminate()
    try:await asyncio.wait_for(self.process.wait(),CLOSE_KILL_S)
    except asyncio.TimeoutError:
     with contextlib.suppress(ProcessLookupError):self.process.kill()
     await asyncio.wait_for(self.process.wait(),CLOSE_KILL_S)
   except asyncio.TimeoutError:
    with contextlib.suppress(ProcessLookupError):self.process.terminate()
    try:_,self.stderr=await asyncio.wait_for(self.process.communicate(),CLOSE_KILL_S)
    except asyncio.TimeoutError:
     with contextlib.suppress(ProcessLookupError):self.process.kill()
     _,self.stderr=await asyncio.wait_for(self.process.communicate(),CLOSE_KILL_S)
  else:
   _,self.stderr=await asyncio.wait_for(self.process.communicate(),CLOSE_KILL_S)
  return self.process.returncode

async def _cancel_others():
 """(On the private loop.) Cancel every other task of the loop and wait for them: their callers' futures resolve."""
 others=[t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
 for task in others:task.cancel()
 await asyncio.gather(*others,return_exceptions=True)

class ThreadedHelperBridge:
 """Host only the existing pipe adapter on a private subprocess-capable loop.

 Windows ASGI selects SelectorEventLoop, which cannot create subprocess
 pipes. Do not change that server/global policy: one call owns one thread
 and one Proactor loop for its already required Watch helper process.
 """
 def __init__(self,*args,**kwargs):
  self.delegate=HelperBridge(*args,**kwargs);self.loop=None;self.thread=None
  self._exit=None;self._ready=threading.Event();self._closed=False
 @property
 def process(self):return self.delegate.process
 async def _call(self,coro):
  return await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(coro,self.loop))
 async def start(self):
  if self.thread:raise RuntimeError('Helper already started')
  def run():
   self.loop=asyncio.ProactorEventLoop() if os.name=='nt' else asyncio.new_event_loop()
   asyncio.set_event_loop(self.loop);self._ready.set()
   try:self.loop.run_forever()
   finally:self.loop.close()
  self.thread=threading.Thread(target=run,name='echo-watch-helper-loop',daemon=True);self.thread.start()
  if not await asyncio.to_thread(self._ready.wait,5):raise TimeoutError('Private helper loop')
  try:await self._call(self.delegate.start())
  except BaseException:
   await self.close();raise
  return self
 async def send(self,*args):return await self._call(self.delegate.send(*args))
 async def receive(self,timeout=PEER_WAIT_S):return await self._call(self.delegate.receive(timeout))
 async def close(self):
  if self._closed:return self._exit
  self._closed=True
  if not self.loop or not self.loop.is_running():return self._exit
  try:self._exit=await self._call(self.delegate.close())
  finally:
   # c22-reviewfix: nothing that waits on this loop (a reader in receive) is left with a future that never resolves once it stops
   with contextlib.suppress(Exception):await asyncio.wait_for(self._call(_cancel_others()),CLOSE_KILL_S)
   self.loop.call_soon_threadsafe(self.loop.stop)
   await asyncio.to_thread(self.thread.join,CLOSE_KILL_S)
  return self._exit
