"""Existing PCM-frame authorization/cancel playback source. Pure test adapter, no phone or real PCM."""
import asyncio
import base64
import contextlib
import logging
import time
import uuid
logger=logging.getLogger('synthetic-playback')

def boost_active(gain,presence):
    return False   # CI isolates unboosted PCM branch; not a production replacement

class PlaybackWire:
    async def _play(self,pcm,text,generation,authorized,played=None,started=None,abandoned=None):
        
        response_id=uuid.uuid4().hex;began=time.monotonic();opened=False;first=False;why='cancelled'
        boosted=iter(boost_frames(pcm,self.voice_gain,self.voice_presence)) if boost_active(self.voice_gain,self.voice_presence) else None
        try:
            for offset in range(0,len(pcm),960):
                await asyncio.sleep(max(0,began+offset/48000-time.monotonic()))
                async with self.send_lock:
                    if self.closed or generation!=self.audio_generation:why='closed' if self.closed else 'superseded';return False
                    if not authorized():why='unauthorized';return await self._abandoned(opened)
                    if offset==0:
                        self._cue_to_gate(pcm)
                        if self.cloud_witness:self.cloud_witness.event(self.clock())
                        opened=True
                        await self.emit({'type':'response.created','response':{'id':response_id}})
                        await self.emit({'type':'response.audio_transcript.delta','response_id':response_id,'delta':text})
                    await self.emit({'type':'response.audio.delta','response_id':response_id,
                                     'delta':base64.b64encode(next(boosted) if boosted else pcm[offset:offset+960]).decode('ascii')})
                    first=True
                    if offset==0 and started:started(began)
            async with self.send_lock:
                if self.closed or generation!=self.audio_generation:why='closed' if self.closed else 'superseded';return False
                if not authorized():why='unauthorized';return await self._abandoned(opened)
                await self.emit({'type':'response.done','response':{'id':response_id,'status':'completed'}})
                opened=False;why=None

                if played:played(began)
            return True
        except Exception:

            why='error'
            if opened and not self.closed and generation==self.audio_generation:
                with contextlib.suppress(Exception):await self._send({'type':'output_audio_buffer.clear'})
            raise
        finally:
            if why and first and abandoned:
                try:abandoned(began,opened,why,time.monotonic())
                except Exception:logger.debug('echo-sync cue_abandoned failed',exc_info=True)

    async def _abandoned(self,opened):
        
        if opened:await self.emit({'type':'output_audio_buffer.clear'})
        return False

