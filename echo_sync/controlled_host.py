"""Host binding for the existing authenticated Conduit LocalLive socket.

Feature-off until real PCM, retrieval and device acceptance. Subscription
exchange/auth remains the existing Conduit implementation. There is no paid
API, text model fallback, listener or background scheduler in this module.
"""
import asyncio
import base64
import contextlib
import contextvars
import inspect
import json
import sys
from pathlib import Path
import tempfile
import time
import wave
import re
import uuid

from .content_policy import ANSWER_POLICY, POLICY_VERSION, CallContext, build_instructions, load_call_context
from .settings import SETTINGS_FILE, controller_settings, load as load_settings, resolve as resolve_settings, timer_policy_check
from .timer_policy import COALESCE_SECONDS, FAST_SIGN_IN_TIMEOUT_S, HOST_LOOKUP_TIMEOUT_S, LOCAL_READ_TIMEOUT_S, RECEIVE_TIMEOUT_S, WAKE_TICK_S
from . import build_info, degradation
from .speech_text import speak
from .call_trace import CallTrace
from . import call_audio
from . import v5_tap
from . import v5_gate
from . import v6_memory
from . import material_pick
from .material_pick import load_whole
from .helper_pool import SpareHelper
from . import ear_shadow, fast_text, instant, pcm_cache
from .controlled_media import ControlledMedia
from .diagnostics import PHRASES
from .native_media_socket import NativeMediaSocket
from .helper_bridge import BoundedWriter, ThreadedHelperBridge
from .pcm_trim import trim_leading_silence
from .loop_guard import EarTap,SharedOnset,WakeTicker
from . import warm
from .sapi_worker import profile_sapi_worker, lang_ssml
from .settings import SETTINGS_FILE, controller_settings, load as load_settings, resolve as resolve_settings, timer_policy_check

def keep_worker_resident(worker):
    """Pin the shared SAPI worker for the life of the server; returns at once (safe on the event loop).

    The worker starts and primes itself in the background and is repaired there after a crash, so no
    cue pays the 0.7-1.6 s PowerShell start. A shared manager that predates the resident mode keeps
    its own lease-style behaviour, and a failure here only means the first cue starts the worker
    lazily, as before: an optimisation must never fail a live call.
    """
    pin=getattr(worker,'keep_resident',None)
    if callable(pin):
        try:pin()
        except Exception as error:degradation.note('host.sapi_worker',error,what='голос не закреплён: первая подсказка стартует его сама')      # U78

def voice_key(voice,end=None,lang=False,ranges=False):
    """The voice part of the PCM cache key of a cue: the worker's voice, the end intonation (E76) and the mark of the text before the voice (a sound cached before it was spoken in words is not this one)."""
    return (voice or 'sapi')+(f':{end}' if end else '')+':speech'+(':lang' if lang else '')+(':ranges' if ranges else '')      # U16-S8: a plural century is read apart under ``number_ranges``; U19-S5: (English runs by the English voice) is cached apart

def render_cue_pcm(worker,text,directory):
    """One cue as 24 kHz mono PCM16 with the engine's leading silence trimmed. Blocking: run off the loop.

    Only the front is cut here; the transport cuts the silence after the voice and times the cue from the voice (task S0).
    """
    with tempfile.TemporaryDirectory(prefix='cue-',dir=str(directory)) as folder:
        path=Path(folder)/'cue.wav';worker.synthesize(speak(text),str(path))      # E89: the text before the voice (speech_text)
        with wave.open(str(path),'rb') as audio:
            if (audio.getframerate(),audio.getnchannels(),audio.getsampwidth())!=(24000,1,2):
                raise ValueError('SAPI format')
            pcm=audio.readframes(audio.getnframes())
    return trim_leading_silence(pcm)

class EndVoice:
    """The shared worker with the end intonation of ONE cue bound to it (E76), so that ``render_cue_pcm`` keeps its signature."""
    def __init__(self,worker,end,lang=False):self._worker=worker;self._end=end;self._lang=lang
    def synthesize(self,text,output_path,**kwargs):return self._worker.synthesize(text,output_path,end=self._end,**({'lang':True} if self._lang else {}),**kwargs)

def controller_session_id(query):
    probe=query.get('echo_probe_id','')
    if query.get('echo_trace')=='1':
        if not isinstance(probe,str) or not re.fullmatch(r'[0-9a-f]{32}',probe):probe=uuid.uuid4().hex
        return 'native-probe-'+probe
    return 'live-native-controlled-user-v1'


def probe_flags(settings,query,trace):
    """``live_first`` on the call of one probe, the way ``echo_ice`` chooses the ICE tries: only a PROBE (``echo_trace=1``) may ask for it (``echo_live_first=1``), so a build is measured with the profile's file and every phone call as they are. ``prepare_wide``
    comes with it, it is a part of it; what else it needs stays the profile's, ``resolve`` reads that."""
    asked={**({'prepare_wide':'on','live_first':'on'} if query.get('echo_live_first')=='1' else {}),**({'answer_witness':'shadow'} if query.get('echo_answer_witness')=='1' else {})} if trace else None      # ``answer_witness``: its line in the trace, the same way
    return resolve_settings({**settings,**asked}) if asked else settings      # a layer over the profile, then the ONE resolve: what a probe asks for needs what the profile gives (ear_release, two_witnesses ...), as for any call

async def read_profile_settings(home):
    """The validated settings of the profile, read once when a call opens, off the event loop. A file that cannot be read - or a read
    that has not returned within LOCAL_READ_TIMEOUT_S (a locked file, a dead drive) - means the defaults: the owner's settings
    are an addition and must never hold a phone call. ``load_settings`` itself never raises; the rest is for a broken disk."""
    try:return await asyncio.wait_for(asyncio.to_thread(load_settings,Path(home)/'materials'/SETTINGS_FILE),LOCAL_READ_TIMEOUT_S)
    except Exception as error:
        degradation.note('host.profile_settings',error,what='файл настроек не прочитан: настройки по умолчанию')      # U78
        return resolve_settings(None)

# The text the cloud model is given lives in content_policy.py (answer policy v2 + the owner's subject and materials). The old name
# stays for whoever still imports it: it is the policy alone, as before.
CONTENT_POLICY=ANSWER_POLICY

# UP-02. Which ICE configuration the cloud channel tries first. A real call keeps HOST candidates first (False): in the ECHO profile
# log of 2026-11-02 (05:50-12:48) all 39 successful opens connected with host candidates alone (3.4-15.5 s) and none needed the
# STUN retry that STUN-first was meant to save, while STUN puts its address gathering (aioice waits up to 5 s for one interface
# that never answers) in front of the offer of every open. True = STUN first, host candidates as the fallback; a PROBE can try it
# per call (echo_ice=stun) to compare both orders on one build before this default is flipped - see the stun_first keyword.
STUN_FIRST=False

def ice_tries(api,stun_first=STUN_FIRST):
    """The ICE configurations ``open_subscription`` tries, in order: ``(stun servers, ())`` or the reverse. Without a configured
    STUN server there is exactly one try (two identical ones would only double the wait)."""
    stun=tuple(getattr(api,'WATCH_AUDIO_STUN',None) or ())
    if not stun:return ((),)
    return (stun,()) if stun_first else ((),stun)

class SubscriptionSource:
    """What the wire writes to: the helper pipe behind a BoundedWriter (DEF-FAULT-11). ``send`` only queues, so a helper that stops
    reading its stdin can never hold the loop that reads the phone; a stalled write is reported to ``on_failure`` after
    HELPER_WRITE_TIMEOUT_S. The pipe is addressed through ``self.bridge`` at every write, never through a method bound once."""
    def __init__(self,bridge,*,on_failure=None):
        self.bridge=bridge
        self.writer=BoundedWriter(self._write,on_failure=on_failure).start()
    async def _write(self,kind,payload):return await self.bridge.send(kind,payload)
    async def send(self,kind,payload=b''):self.writer.put(kind,payload)
    async def close(self):
        await self.writer.close()
        return await self.bridge.close()

_SPARES={}      # W6 item 10: (helper path, python) -> helper_pool.SpareHelper, alive between calls

def stages_of(marks):
    """U31: the stages of one open as ``name:ms,...`` for the log line (numbers and labels only)."""
    return ','.join(f'{name}:{ms}' for name,ms in marks.items()) or '-'

async def open_subscription(api,profile,helper_path,runtime,*,bridge_factory=ThreadedHelperBridge,instructions=None,stun_first=STUN_FIRST,spare=None,marks=None,clock=None,attempt=0):
    """Adapt upstream _GptLiveWatchSession.run/_connect: ONE try. Whether an open is tried again is decided in one place, the loop of
    ``NativeMediaSocket._open_upstream`` (any failure, bounded); this function has no loop and no retry rule of its own.

    The order of the ICE configurations is ``stun_first`` (UP-02; the default STUN_FIRST is host candidates first, STUN second); the
    ``attempt`` (0 the first open, 1 its retry, ...) picks the configuration, so the retry of a failed open uses the other one.
    ``instructions`` is the complete text for the cloud session (policy + the owner's lesson, see
    content_policy.build_instructions). Without it the session gets the policy alone.
    U31: ``marks`` (a dict, the caller's, so that a failed open keeps what it reached) gets, in order, the ms since the open began of each stage: ``spare`` (a started helper was taken)
    or ``helper`` (this open started one), ``offer`` (the helper's ICE offer), ``instructions`` (the call's text was ready), ``exchange`` (the cloud's answer), ``connected`` (the media
    channel), ``started`` (the session); this try's. Always on: they are in the log line of every open, ready or failed.
    """
    python,environment,flags,_=runtime
    clock=clock or (lambda:time.monotonic());begun=clock();marks=marks if marks is not None else {}    # (the lambda: a patched ``time.monotonic`` is the clock of the open too)
    mark=lambda name:marks.__setitem__(name,round((clock()-begun)*1000))
    instructions=ANSWER_POLICY if instructions is None else instructions
    # w8-net N17 (open_overlap): ``instructions`` may still be being read (an awaitable, e.g. a task): the helper starts and gathers its
    # addresses meanwhile and the text is awaited only where the exchange needs it.
    tries=ice_tries(api,stun_first);stun=tries[attempt%len(tries)]      # route: the ICE configuration is chosen by the attempt of the ONE retry loop (native_media_socket._open_upstream), not by a loop of its own
    bridge=spare.take() if spare is not None and attempt%len(tries)==0 else None      # W6 item 10: a live spare helper is already started
    warm=bridge is not None
    if bridge is None:bridge=bridge_factory(helper_path,python=python,environment=environment,flags=flags)
    marks.clear();phase='helper_offer';connected=False
    tried=clock()
    try:
        if not warm:await bridge.start()
        mark('spare' if warm else 'helper')
        await bridge.send('C',json.dumps({'input_rate':24000,'output_rate':24000,'stun':list(stun)}).encode())
        offer=await bridge.receive(20)
        if not offer or offer[0]!='O':raise RuntimeError('No media offer')
        phase='subscription_exchange';offered=clock();mark('offer')
        if inspect.isawaitable(instructions):instructions=await instructions
        mark('instructions')
        result=await asyncio.wait_for(api._run_scoped(profile,lambda:api.create_gpt_live_session(
            offer[1].decode(),billing='subscription',call_opening=False,
            limiter_key=api._limiter_key(profile),_content_instructions=instructions)),40)
        exchanged=clock();mark('exchange')
        if result.get('auth')!='subscription':raise RuntimeError('Subscription required')
        await bridge.send('A',result['transport']['sdp'].encode())
        phase='subscription_channel';deadline=time.monotonic()+api.WATCH_AUDIO_CONNECT_TIMEOUT_S
        while time.monotonic()<deadline:
            try:frame=await bridge.receive(min(2,max(.001,deadline-time.monotonic())))
            except asyncio.TimeoutError:continue
            if frame is None or frame[0]=='X':raise RuntimeError('Media closed before readiness')
            if frame[0]=='R' and not connected:
                connected=True;deadline=time.monotonic()+10;mark('connected')
            if frame[0]=='e':
                event=json.loads(frame[1])
                if event.get('type')=='session.started':
                    mark('started');logger=getattr(api,'logger',None)
                    # How long a good open takes decides the cap of NativeMediaSocket.UPSTREAM_OPEN_TIMEOUT_S. elapsed_ms counts every
                    # try; offer_ms (helper start + offer, i.e. ICE gathering) and exchange_ms (the cloud's answer) are of this try
                    # and show which phase made a slow open slow. Numbers only.
                    if logger and warm:logger.info('Controlled media spare helper taken')      # W6 item 10: offer_ms below is then ICE only
                    if logger:logger.info('Controlled media ready stun=%s elapsed_ms=%s offer_ms=%s exchange_ms=%s',bool(stun),
                        round((clock()-begun)*1000),round((offered-tried)*1000),round((exchanged-offered)*1000))
                    if logger:logger.info('Controlled media open stages stun=%s stages=%s',bool(stun),stages_of(marks))      # U31: every open, ready or not, trace or not
                    return bridge
                if event.get('type')=='error':raise RuntimeError('Subscription setup refused')
        raise TimeoutError('Subscription readiness deadline')
    except BaseException as error:
        await bridge.close()
        logger=getattr(api,'logger',None)
        if logger:logger.warning('Controlled media setup failed phase=%s type=%s elapsed_ms=%s stages=%s',phase,type(error).__name__,round((clock()-begun)*1000),stages_of(marks))
        raise

def degradation_lines():
    """U78: the «недоступно: …» lines of the check before a call (the journal of this process and the cheap default probes); never raises."""
    try:return [l for l in degradation.check_before_call(degradation.default_checks())[1] if l.startswith('недоступно: ')]
    except Exception:return []      # noqa: BLE001 - the check never costs a call

def who_closed(error,closing):
    """U07-S1 (U09): ``(closer, code)`` of the end of a call, numbers and labels only. 'cloud': the upstream channel was lost and the host closed the phone's socket (``closing``);
    'phone': the phone's socket ended the read (a disconnect, with the code it carries when it has one); 'host': the host's own limit or a fault (no code); none: the loop ended by itself."""
    if closing.get('by'):return closing['by'],closing.get('code')
    if error is None:return 'host',None
    code=getattr(error,'code',None)
    code=code if isinstance(code,int) and not isinstance(code,bool) else None
    name=type(error).__name__
    if code is not None or 'Disconnect' in name or 'Closed' in name:return 'phone',code
    return 'host',None

async def serve(ws,*,api,profile,home):
    home=Path(home);helper_path=Path(api.__file__).parent/'watch_audio_helper.py'
    selected=api._watch_audio_runtime.python()
    if not selected:raise RuntimeError('Prepared native audio runtime unavailable')
    bridge=None
    # UX-trace: the calm silence auto-repeat (and the call trace switch) of this call come from the profile; read before anything is held.
    profile_settings=await read_profile_settings(home)
    loaded={}
    if build_info.build_id()=='unknown':degradation.note('host.build','unknown',what='нет файла BUILD и git: откат не к чему привязать')      # U120: a build with no name cannot be rolled back to
    try:
        from .build_info import fingerprint
        loaded=fingerprint(profile_settings);__import__('logging').getLogger('echo-sync').info('echo-sync loaded build=%s code=%s prompt=%s flags=%s',loaded['build'],loaded['digest'],loaded['prompt'],loaded['flags'])      # W03: what this call runs, from the process
    except Exception as error:degradation.note('host.fingerprint',error,what='сборка не названа в журнале')      # U78: a fingerprint never costs a call
    worker=profile_sapi_worker(home)
    # Start and prime the shared worker now, long before the first cue; it then stays for the server's life.
    keep_worker_resident(worker)
    # Product state is separate from all historical/synthetic probe cursors.
    # Reopening is quiet until an explicit repeat or a new question.
    trace=ws.query_params.get('echo_trace')=='1'
    profile_settings=probe_flags(profile_settings,ws.query_params,trace)      # a PROBE's asked modes join the profile's BEFORE the call's settings are made: the controller reads them from there (ControlledMedia.modes)
    controller=ControlledMedia(home/'echo-sync/controlled-state.sqlite3',session_id=controller_session_id(ws.query_params),settings=controller_settings(profile_settings),source_delivery='delegation',session_context_fallback=True,lookup_policy='required',first_useful_gate=True,coalesce_seconds=COALESCE_SECONDS,quiet_reopen=True,
        repeat_seconds=profile_settings['repeat_seconds'],max_auto_repeats=profile_settings['max_auto_repeats'],fast_text=profile_settings['fast_text'])
    from .prepared_answers import PreparedAnswers,load as load_prepared      # W2: prepared answers without the model (prepared_answers.py): the owner's list, when a file is set, and the long cache
    cache=home/'echo-sync/prepared-answers-cache.json';listing=profile_settings['prepared_answers_file']
    controller.prepared=load_prepared(listing,cache_path=cache) if listing else PreparedAnswers(cache_path=cache)
    building=None
    if profile_settings['instant']=='on':     # W5: the bank, the laws, the chart and the material in one index, built off the loop; the call does not wait for it
        async def build_instant():
            controller.instant=await asyncio.to_thread(instant.for_home,profile_settings,home)
        building=asyncio.ensure_future(build_instant())      # held to the end of the call: a task nobody holds can be collected while it waits, and one that outlives the call is cancelled with it
    cue_cache=pcm_cache.from_settings(profile_settings)     # W5: the first portions of the bank already spoken (pcm_cache.py); None: as before
    wire=None;reader=None;ticker=None
    call_text={'value':None}    # H2: the prompt of this call's text channel (BRAIN and the owner's material)
    observations=0;lookup_requests=0
    prefetch=await api._run_scoped(profile,lambda:api._gpt_live_settings().get('controlled_prefetch_enabled') is True)
    if trace and ws.query_params.get('echo_prefetch') in {'0','1'}:
        prefetch=ws.query_params.get('echo_prefetch')=='1'
    fresh_lookup=trace and ws.query_params.get('echo_fresh_lookup')=='1'
    # Like the two switches above, only a PROBE (echo_trace=1) may choose the order of the ICE tries - echo_ice=host|stun - so that
    # both orders can be measured on one deployed build (V3 section 8). A real call always uses STUN_FIRST.
    stun_first=STUN_FIRST
    if trace and ws.query_params.get('echo_ice') in {'host','stun'}:
        stun_first=ws.query_params.get('echo_ice')=='stun'
    call_id=uuid.uuid4().hex[:12]
    lost=False;announcing=set()
    counters={'input_pcm_packets':0,'output_pcm_packets':0,'user_segments':0,'user_finals':0,'last_error':None}
    started=time.monotonic();logger=getattr(api,'logger',None)
    if logger:logger.info('Controlled call opened call=%s source=%s',call_id,'probe' if controller.session_id.startswith('native-probe-') else 'phone')
    unavailable=degradation_lines()      # U78: «недоступно: …» of the journal and the cheap probes, printed before the first question
    if logger:
        for line in unavailable:logger.warning('%s call=%s',line,call_id)
    # UX-trace: the LOCAL trace of this call, logs/echo_calls/<time>-<call id>.jsonl in the profile (call_trace in the profile's settings;
    # a probe has its own observations and writes none). Inert when off. It is opened below, before the tasks of the call are created,
    # and it never raises: nothing in the call depends on it.
    calltrace=CallTrace(home/'logs'/'echo_calls' if (trace and ws.query_params.get('echo_call_trace')=='1') or (not trace and profile_settings['call_trace']=='on') else None,call_id,clock=lambda:time.monotonic(),threaded=True,facts=profile_settings['facts_journal']=='on',mic_gap_ms=profile_settings['mic_gap_ms'],mic_ring_s=profile_settings['mic_ring_s'])
    v5tap=v5_tap.attach(controller,profile_settings,calltrace.directory,call_id,clock=time.monotonic)      # V5 step 1a (always, in the folder of the call journal: no journal, no folder, no record): one lock for the entries, the inputs and the returned actions in a record
    calltrace.live_watch=profile_settings.get('live_first')=='on'
    # U07-S3: the sound of the call, ONLY when asked: pcm_record=on in the profile (a phone call) or echo_pcm_record=1 (a probe, echo_trace=1). Laptop only, never decoded into a decision, never raises into the call.
    pcm_root=home/'logs'/'echo_pcm';rec=None
    try:
        if (trace and ws.query_params.get('echo_pcm_record')=='1') or (not trace and profile_settings['pcm_record']=='on'):rec=call_audio.CallAudio(pcm_root,call_id,cap_mb=profile_settings['pcm_record_call_mb'])
    except Exception as error:
        rec=None;degradation.note('host.pcm_record',error,what='запись звука звонка не открыта')      # U78
    def rec_pcm(channel,b64):
        if rec is None or not isinstance(b64,str) or not b64:return
        try:rec.write(channel,base64.b64decode(b64))
        except Exception:pass
    async def emit(frame):
        calltrace.frame(frame)
        if frame.get('type')=='response.audio.delta':counters['output_pcm_packets']+=1;rec_pcm('cue',frame.get('delta'))
        if frame.get('type')=='error':
            code=str(frame.get('error',{}).get('code',''))
            counters['last_error']=code if re.fullmatch(r'[a-zA-Z0-9_]{1,80}',code) else 'redacted_error'
            # Every failure is in the log of the call (class and reason: the 'echo-sync' log of the wire); this line ties it to the call.
            if logger:logger.warning('Controlled call error call=%s code=%s',call_id,counters['last_error'])
            if frame.get('echo_local'):return      # local mode: the journal and the log have it; the phone would hang the call up on it
        await ws.send_text(json.dumps(frame,ensure_ascii=False))
    async def helper_lost(ended,channel=None):
        """The helper is gone (the reader met its end) or stuck (a write timed out, or the queue to it overflowed): the listener hears
        «Связь прервалась» BEFORE the socket closes, and the close waits (bounded) for the phrase. ONE place for whoever notices
        first. The wire stops cueing first: a repeat falling due must not cut the phrase, and nothing more goes to a dead channel.

        ``local_fallback``: a channel that dies MID-CALL (a VPN flap is as likely as the handshake timeout of 06.11) does not close the
        call either. It falls into local mode IN PLACE - the phone's session, the waiting portion and the cursor are untouched, the
        listener hears the one short line, and the cloud is retried quietly until the same call can be upgraded back. ``lost`` is cleared
        again, so a second drop after an upgrade is noticed like the first."""
        nonlocal lost
        if lost or wire.closed:return
        # c22-reviewfix: a complaint of a channel that is no longer the call's (the old helper after an upgrade) closes nothing of the new one
        if channel is not None and channel is not bridge:
            if logger:logger.info('Controlled call stale channel call=%s reason=%s',call_id,ended)
            return
        # The call already runs from the local bases: a later complaint of the SAME dead channel (its reader ending, its writer timing
        # out, its queue overflowing) is nothing to report and must never close the call a second time.
        if wire.local_mode:
            if logger:logger.info('Controlled call channel lost call=%s local_mode=on already reason=%s',call_id,ended)
            return
        lost=True
        if wire.local_fallback:
            # The failure itself still belongs in the evidence of the call (the error frame and the log line); the listener hears the one
            # line of local mode instead of «Связь прервалась. Повторите вопрос.», which would ask them to repeat into a dead channel.
            with contextlib.suppress(Exception):await wire._error('controlled_upstream_closed',ended,announce=False)
            # c22-reviewfix: a writer that noticed (stalled, failed, overflowed) while the reader still waits on the same pipe: the reader is
            # stopped first, as the teardown below does («Stop the sole pipe reader before communicate()»): the close of the old channel is not
            # met by it, and the old helper delivers no final after the fall.
            if reader is not None and reader is not asyncio.current_task() and not reader.done():
                reader.cancel();await asyncio.gather(reader,return_exceptions=True)
            if await wire.enter_local(ended,source_lost=True):
                lost=False
                if logger:logger.warning('Controlled call channel lost call=%s local_mode=on reason=%s',call_id,ended)
                return
        wire.ready=False
        try:
            await wire._error('controlled_upstream_closed',ended)
            await wire.finish_diagnostic()
        except Exception as error:
            # The phone may be gone: the announcement fails, the close is still tried (or the call would stay open for ever).
            if logger:logger.warning('Controlled call channel announcement failed call=%s type=%s',call_id,type(error).__name__)
        closing['by']='cloud';closing['code']=1011
        with contextlib.suppress(Exception):await ws.close(code=1011)
    closing={'by':None,'code':None}      # U07-S1: set where the host itself closes the phone's socket
    def writer_failed(reason,channel=None):
        task=asyncio.create_task(helper_lost(reason,channel));announcing.add(task);task.add_done_callback(announcing.discard)
    async def instructions_for_call():
        """The complete text for the cloud session of this call: the policy and the owner's subject and materials AS THEY ARE NOW
        (the files are read at every open, so a new lecture is used by the next call and needs no restart). Off the event loop; a
        failure of any kind - or a read that has not returned within 2 s (it would eat the 18 s cap of the open) - means the bare
        policy: the lesson is an addition and must never fail a live call."""
        reading=time.monotonic()
        try:
            context=await asyncio.wait_for(asyncio.to_thread(warm.material_cache.load if profile_settings['warm_start']=='on' else load_call_context,home),LOCAL_READ_TIMEOUT_S)
            text=build_instructions(context)
            call_text['value']=build_instructions(context,fast_text.BRAIN_POLICY)
            call_text['pinned']=[f'{name}: {value}' for name,value in (('Тема',context.subject),('Слушатели',context.audience),('Стиль',context.style)) if value]      # V6 memory: the owner's standing lines of this call (pinned in the card)
            if profile_settings['material_pick']=='on':       # w5-material: parts by the question; W13 item 7: always when on, the job's own cap (material_pick.JOB_MATERIAL_CHARS)
                picker=material_pick.for_job(await asyncio.wait_for(asyncio.to_thread(load_whole,home),LOCAL_READ_TIMEOUT_S))
                def brain_for(question=None,history=()):
                    if not question:return call_text['value']
                    text,pick=picker.instructions_and_pick(question,history,context,fast_text.BRAIN_POLICY)
                    if logger:logger.info('Controlled call material call=%s %s',call_id,pick.summary())
                    return text
                call_text['fn']=brain_for
            if profile_settings['prepared_speech']=='on':controller.prepare_speech(context.excerpt)
        except Exception as error:
            context,text=CallContext(),ANSWER_POLICY
            if logger:logger.warning('Controlled call context unavailable call=%s type=%s',call_id,type(error).__name__)
        # The subject, the version (hash) and the sizes of what the call was given; never the material itself.
        # read_ms (w8-net N17): how long the read held the open (or ran beside it, open_overlap).
        if logger:logger.info('Controlled call context call=%s policy=%s read_ms=%d instructions_chars=%s %s',call_id,POLICY_VERSION,
                              round((time.monotonic()-reading)*1000),len(text),context.summary())
        return text
    spare=None
    if profile_settings.get('spare_helper')=='on':     # W6 item 10: one helper of this runtime kept started between calls (helper_pool.py)
        python,environment,flags,_=selected
        spare=_SPARES.get((str(helper_path),python))
        if spare is None:spare=_SPARES[(str(helper_path),python)]=SpareHelper(lambda:ThreadedHelperBridge(helper_path,python=python,environment=environment,flags=flags))
    opens=0      # route: how many opens this call has made; the ICE configuration of an open follows it (open_subscription ``attempt``)
    async def connect():
        nonlocal bridge,reader,opens
        attempt=opens;opens+=1
        marks={};spared={'spare':spare} if spare is not None else {}
        try:
            if profile_settings.get('open_overlap')!='on':
                bridge=await open_subscription(api,profile,helper_path,selected,instructions=await instructions_for_call(),stun_first=stun_first,marks=marks,attempt=attempt,**spared)
            else:
                # w8-net N17: the material (up to 2 s) is read while the helper starts and gathers its addresses (offer_ms 1.2 s warm, 5-11 s cold).
                text=asyncio.create_task(instructions_for_call())
                try:bridge=await open_subscription(api,profile,helper_path,selected,instructions=text,stun_first=stun_first,marks=marks,attempt=attempt,**spared)
                finally:
                    if not text.done():text.cancel()
        finally:      # U31: every open, whatever the profile: where the time of the first one went (a failed one: what it reached) - the call's trace, and to a probe's own client
            since=round((time.monotonic()-started)*1000);calltrace.note('open_stages',since_serve_ms=since,**marks)
            if trace:
                with contextlib.suppress(Exception):await wire._send({'type':'conduit.echo.observation','open_stages':dict(marks),'since_serve_ms':since})
        own=bridge      # c22-reviewfix: the reader and the writer of THIS channel name it; ``bridge`` is rebound by the next connect
        source=SubscriptionSource(own,on_failure=lambda reason:writer_failed(reason,own))
        reader=asyncio.create_task(read_source(own));return source
    async def read_source(channel=None):
        nonlocal observations
        ended='helper_closed';channel=channel or bridge
        try:
            while not wire.closed:
                try:frame=await channel.receive(30)
                except asyncio.TimeoutError:continue
                if frame is None or frame[0]=='X':break
                if trace and frame[0]!='p' and observations<160:
                    observations+=1
                    observation={'type':'conduit.echo.observation','kind':frame[0],'bytes':len(frame[1]),'ready':wire.ready}
                    if frame[0]=='e':
                        observed=json.loads(frame[1]);observation['provider_type']=observed.get('type')
                        if observed.get('type')=='error' and isinstance(observed.get('error'),dict):
                            observation['provider_error_code']=observed['error'].get('code')
                        turn=observed.get('turn')
                        if isinstance(turn,dict):observation.update(role=turn.get('role'),chars=len(str(turn.get('transcript',''))))
                    await wire._send(observation)
                if frame[0]=='e':
                    event=json.loads(frame[1])
                    calltrace.provider(event)   # before the controller sees it: the decisions it causes follow it in the trace
                    turn=event.get('turn',{})
                    if isinstance(turn,dict) and turn.get('role')=='user':
                        if event.get('type')=='turn.created':counters['user_segments']+=1
                        if event.get('type')=='turn.done':counters['user_finals']+=1
                    if event.get('type') in {'error','session.closed'}:ended='provider_'+event['type'].replace('.','_');break
                    if channel is not bridge or wire.local_mode:continue      # c22-reviewfix: an old or a fallen channel gives no final
                    await wire.provider(event)
                    waker.wake()      # w9-loop: what the event started (a settle, a release) is looked at now, not on the next .1 s
                    if trace and event.get('type')=='turn.done' and isinstance(event.get('turn'),dict) and event['turn'].get('role')=='assistant':
                        text=event['turn'].get('transcript','')
                        await wire._send({'type':'conduit.echo.observation','grounded':controller.grounded,
                            'commit_marker_seen':bool(controller.answer_marker and controller.answer_marker in text),
                            'published_chars':len(controller.published),
                            **({'source_text_debug':str(text)[:1000]} if ws.query_params.get('echo_debug_text')=='1' else {})})
                elif frame[0]=='p' and calltrace.live_watch:calltrace.live_audio(frame[1])      # only the moment its voice begins
                # 'p' is raw cloud PCM. It is ALWAYS discarded.
        except Exception as error:
            ended=type(error).__name__;raise
        finally:
            await helper_lost(ended,channel)
    async def lookup(question):
        nonlocal lookup_requests
        lookup_requests+=1
        await wire._observe('public_lookup_request',number=lookup_requests)
        def scoped():
            return api._echo_quick_lookup_module().search(question,3,str(home),timeout=HOST_LOOKUP_TIMEOUT_S,force_refresh=fresh_lookup)
        # The search has a second road as the text has (reserve_search.py; no keys: no rows). In local mode (the cloud is out) it is asked first.
        async def second():
            from . import reserve_search
            rows=await asyncio.to_thread(reserve_search.search,question)
            await wire._observe('reserve_lookup',rows=len(rows))
            return rows
        local=getattr(wire,'local_mode',False)
        if local:
            rows=await second()
            if rows:return rows
        try:
            result=await api._run_scoped(profile,scoped,api._search_executor)
            rows=result.get('data',{}).get('web',[]) if result.get('success') else []
        except asyncio.CancelledError:raise
        except Exception:
            if local:raise
            rows=[]
        return rows or (await second() if not local else rows)
    cue_memo=pcm_cache.CallMemo()      # c24-c: a repeat of an unchanged portion is the sound this call already made
    ranges_on=profile_settings.get('number_ranges')=='on'      # U16-S8: the plural century is read in its own paradigm; cached apart (``voice_key``)
    worker.prime_lang=True      # U19-S5: English runs of a cue are read by the English voice (the worker builds the markup); cached apart
    async def synthesize(text,end=None):      # E76: ``end`` ('fall') speaks the last word of the answer lower; its PCM is cached apart from the plain one
        lang=lang_ssml(text) is not None      # U19-S5: only a cue with an English run is rendered (and cached) apart; a Russian cue is the sound it always was
        voice=EndVoice(worker,end,lang) if end or lang else worker
        reused=cue_memo.reused
        pcm=await asyncio.to_thread(pcm_cache.cached,cue_cache,lambda said:render_cue_pcm(voice,said,home/'echo-sync'),text,voice_key(getattr(worker,'voice',None),end,lang,ranges_on),24000,cue_memo)
        if logger and cue_memo.reused>reused:logger.info('Controlled call synthesis reused call=%s reused=%s rendered=%s',call_id,cue_memo.reused,cue_memo.rendered)
        return pcm
    waker=WakeTicker(WAKE_TICK_S)
    async def tick():
        failures=0
        waker.bind()
        while not wire.closed:
            await waker.wait()      # w9-loop N105: woken by an event, .1 s stays the ceiling for the timers
            calltrace.mic_watch()      # V5 step 0: a stretch with no microphone packet is written while it lasts (inert unless facts_journal=on)
            try:await wire.tick()
            except asyncio.CancelledError:raise
            except Exception as error:
                # One failing tick (a database hiccup, a bug in a helper) must not stop every timer of the rest of the call: the
                # repeat timer, the release of a parked cue, the stable-partial confirmation, the release of «the user is speaking».
                failures+=1
                if logger and (failures==1 or failures%100==0):
                    logger.warning('Controlled call tick failed call=%s type=%s count=%s',call_id,type(error).__name__,failures)
    async def prerender():
        # The spoken diagnostics are rendered ONCE per call, here and not at failure time (when SAPI may be the thing that is
        # broken); a phrase that cannot be rendered is served by the WAV packaged next to the modules (echo_sync/diagnostics.py).
        await wire.diagnostic_audio.prerender(synthesize)
        if logger:logger.info('Controlled call diagnostics call=%s prerendered=%s/%s',call_id,len(wire.diagnostic_audio.prerendered),len(PHRASES))
    wire=NativeMediaSocket(controller,emit,connect,lookup,synthesize,diagnostics=trace,prefetch=prefetch)      # the head of a cue, the voice boost, local mode, the transport's ear and the same-meaning prefetch: the wire reads them from ``controller.modes``
    if profile_settings.get('local_fallback')=='on':
        # Local mode is worth nothing without the local ear: it is the ONLY source of the listener's words when the cloud is gone. The
        # bank needs ``instant`` on besides (settings.py keeps that off unless fast_text is on and local_ear is "act"); the law base, the
        # chart of accounts, the owner's prepared answers and the arithmetic answer with any ear. One clear line says what is missing.
        needs=[name for name,ready in (('local_ear',profile_settings['local_ear'] in ('shadow','act')),
                                       ('instant',profile_settings['instant']=='on')) if not ready]
        if logger:
            if 'local_ear' in needs:logger.warning('Controlled call local fallback call=%s DEAF: local_ear=%s - with no cloud nothing would hear the listener',call_id,profile_settings['local_ear'])
            elif needs:logger.warning('Controlled call local fallback call=%s on, without the bank: %s off (the law base, the chart and the material still answer)',call_id,','.join(needs))
            else:logger.info('Controlled call local fallback call=%s on ear=%s bank=on',call_id,profile_settings['local_ear'])
    controller.facts_why=wire.facts_why=profile_settings['facts_journal']=='on'      # V5 step 0 (b): the rule or timer behind a hold or a drop, journal only
    wire.trace_note=calltrace.note      # U07-S4: the stages of the wire (native_media_socket.TRACE_STAGES) into the call trace
    wire.v5_gate=v5_gate.attach(profile_settings,controller,wire,tap=v5tap,note=calltrace.note)      # V5 slice: v5_answer_gate=shadow|on: the verdict next to every answer cue (None when off: the wire is as before)
    # H1: the fast text channel (profile fast_text = "on"; None otherwise). Its job threads read the Codex sign-in through the same scoped executor every
    # other sign-in of this call uses, and wake the loop when they have text. Whatever goes wrong here, the call opens without it.
    loop=asyncio.get_running_loop()
    def fast_credentials():
        return asyncio.run_coroutine_threadsafe(api._run_scoped(profile,lambda:api._codex_credentials()),loop).result(FAST_SIGN_IN_TIMEOUT_S)
    wake_context={'value':None}    # the call's context once its trace is open: the pump a wake starts runs in it (a job thread's own context is empty)
    def fast_wake():
        with contextlib.suppress(RuntimeError):loop.call_soon_threadsafe(wire.fast_wake,context=wake_context['value'])
        waker.wake()
    def ear_wake():
        with contextlib.suppress(RuntimeError):loop.call_soon_threadsafe(wire.ear_wake,context=wake_context['value'])
        waker.wake()
    try:wire.fast=fast_text.for_call(profile_settings,controller,credentials=fast_credentials,instructions=lambda *a:(call_text['fn'](*a) if call_text.get('fn') else call_text['value']) or fast_text.BRAIN_POLICY,wake=fast_wake,report=calltrace.note)
    except Exception as error:
        if logger:logger.warning('Controlled call fast text unavailable call=%s type=%s',call_id,type(error).__name__)
    if getattr(wire,'fast',None) is not None:      # V6 slice: the card of the model request from the ledger (v6_memory.py), always
        wire.fast.card=v6_memory.attach(profile_settings,controller,note=calltrace.note,pinned=lambda:call_text.get('pinned',())).apply
    # Open the trace BEFORE the ticker task exists: a task inherits the context of its creator, and the context says whose decisions
    # (the controller's log lines) belong to this trace - the repeat timer's decisions are made in the ticker.
    calltrace.open(source='probe' if trace else 'phone',policy=POLICY_VERSION,build=loaded.get('build'),code=loaded.get('digest'),flags=loaded.get('flags'),repeat_seconds=controller.repeat_seconds,max_auto_repeats=controller.max_auto_repeats,repeat_cap=controller._repeat_cap(),dictation_cycle=profile_settings.get('dictation_cycle'),record_mode=profile_settings.get('record_mode'),number_ranges=profile_settings.get('number_ranges'),timer_violations=timer_policy_check(profile_settings),**({'live_first':'on'} if calltrace.live_watch else {}))
    if unavailable:calltrace.note('degradation',lines=unavailable)      # U78: the same lines as one record of the call trace
    wake_context['value']=contextvars.copy_context()
    stages={'seen':set()}      # U07-S1 (U09): the stages of the opening, so that a call that closes before ready can be read; labels and milliseconds only
    def stage(name):
        if name in stages['seen']:return
        stages['seen'].add(name);calltrace.note('stage',name=name,ms=round((time.monotonic()-started)*1000))
    stage('trace_open')
    # F3 (the owner's call of 3 Nov 09:55): a new call starts clean. The phone's session is one constant for every call, so an answer an
    # earlier call left waiting is retired here (history kept), after the trace is open so that the decision is in it, and before the first
    # word of the call is heard. An addition: whatever goes wrong, the call opens.
    try:controller.begin_call()
    except Exception as error:
        if logger:logger.warning('Controlled call could not retire an earlier answer call=%s type=%s',call_id,type(error).__name__)
    ticker=asyncio.create_task(tick());phrases=asyncio.create_task(prerender())
    # S0: the transport's own ear in the mode the profile asks for (settings.local_onset), set before the first microphone packet is read -
    # with S0's energy rule, which needs no model. R-VAD: the engine the profile asks for (settings.local_onset_engine, Silero VAD by default) is built in
    # a thread, bounded to local_ear.ONSET_BUILD_TIMEOUT_S, and replaces the energy rule when it is ready; too slow or broken, the energy rule stays
    # (logged). The call never waits for a model, nor does anything on the event loop load one.
    async def hear_better():
        try:
            await wire.load_onset(controller.modes['local_onset'],controller.modes['local_onset_engine'],model_factory=warm.vad_pool.take if profile_settings['warm_start']=='on' else None)
            # S1: the local ear, only in the profile's shadow mode (default off). It logs next to the cloud's verdicts and never acts.
            if wire.onset is not None:
                # w9-loop N112: the ear takes the transport's verdict of the same packet; Silero runs once per packet, not twice
                wire.onset=shared=SharedOnset(wire.onset)
                ear=ear_shadow.for_call(profile_settings,controller,detector_factory=lambda:EarTap(shared),report=calltrace.note)
            else:ear=await ear_shadow.for_call_async(profile_settings,controller,report=calltrace.note)
            if wire.closed:
                if ear is not None:ear.close()
            else:
                wire.ear=ear
                if ear is not None and profile_settings['prepare_wide']=='on':ear.wake=ear_wake      # H7 item 6
        except asyncio.CancelledError:raise
        except Exception as error:
            wire.ear=None
            if logger:logger.warning('Controlled call ear unavailable call=%s type=%s',call_id,type(error).__name__)
    ears=asyncio.create_task(hear_better())
    try:
        # T1: the channel's client, TLS and sign-in are prepared in a background thread from here and kept warm until the call closes (``wire.close`` in the ``finally`` below -> ``fast.close``); the call does not wait for any of it.
        # Not before this ``try``: a call that died on its way here would leave a thread pinging for the life of the server.
        if wire.fast is not None:wire.fast.warm()
        received_pcm=0
        while not wire.closed:
            message=await asyncio.wait_for(ws.receive_text(),RECEIVE_TIMEOUT_S)
            if len(message)>132000:raise ValueError('Oversized native frame')
            try:event=json.loads(message)
            except ValueError:await wire._error('controlled_invalid_json','invalid_json');continue
            if isinstance(event,dict) and event.get('type')=='input_audio_buffer.append':
                counters['input_pcm_packets']+=1
                calltrace.mic(event)   # arrival time and length only (the duplex evidence); never the audio
                rec_pcm('mic',event.get('audio'))
            if trace and isinstance(event,dict) and event.get('type')=='input_audio_buffer.append':
                received_pcm+=1
                if received_pcm==1:await wire._send({'type':'conduit.echo.observation','client_pcm_seen':True,'ready':wire.ready,'prefetch_enabled':prefetch,'fresh_lookup':fresh_lookup,'session_context_fallback':True,'lookup_policy':'required','first_useful_gate':True,'coalesce_seconds':COALESCE_SECONDS})
            await wire.client(event)
            if wire.source is not None:stage('upstream_open')
            if wire.ready:stage('ready')
    finally:
        # The numbers of the duplex summary (a verdict and seconds) join the metadata of this line, trace file or not.
        closer,close_code=who_closed(sys.exc_info()[1],closing)
        counters.update(controller.input_counts())      # U17-S4: numbers and labels of the input meter
        pcm_rec=None
        if rec is not None:      # U07-S3: drain and fix the files off the loop (it waits for the writer thread); then the oldest calls go
            try:
                pcm_rec=await asyncio.to_thread(rec.close)
                await asyncio.to_thread(call_audio.prune,pcm_root,profile_settings['pcm_record_calls'],profile_settings['pcm_record_mb'],call_id)
            except BaseException as error:
                pcm_rec=pcm_rec or {'state':'failed:'+type(error).__name__}
        spend=wire.fast.spend() if getattr(wire,'fast',None) is not None else None      # U107: what the call asked of the first road (Codex) and the reserve and what it cost, numbers only
        counters.update(calltrace.close(elapsed_ms=round((time.monotonic()-started)*1000),ready=wire.ready,counters=dict(counters),close_code=close_code,closer=closer,**({'pcm_rec':pcm_rec} if pcm_rec else {}),**({'spend':spend} if spend else {})))
        if v5tap is not None:v5tap.close()      # V5 step 1a: the record of the call is complete
        if logger:logger.info('Controlled call closed call=%s ready=%s elapsed_ms=%s metadata=%s',call_id,wire.ready,round((time.monotonic()-started)*1000),json.dumps(counters,sort_keys=True))
        # Stop the sole pipe reader before communicate() drains that pipe.
        wire.closed=True
        if spare is not None:spare.ensure_later()      # W6 item 10: the next call finds a started helper (the pool holds the task: it outlives this call)
        if reader:
            reader.cancel();await asyncio.gather(reader,return_exceptions=True)
        # Every step of the cleanup is its own try: a helper that cannot be closed must neither skip the rest (the worker lease, the tasks)
        # nor hide why the call ended (DEF-FAULT-12). The failure is logged with its type.
        async def step(name,work):
            try:await work
            except Exception as error:
                if logger:logger.warning('Controlled call cleanup step failed call=%s step=%s type=%s',call_id,name,type(error).__name__)
        await step('wire',wire.close())
        # Connect failure may occur before wire.source was assigned.
        if not wire.source and bridge and bridge.process and bridge.process.returncode is None:
            await step('bridge',bridge.close())
        tasks=[t for t in (reader,ticker,phrases,ears,building,*announcing) if t]
        for task in tasks:task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
        worker.release()
