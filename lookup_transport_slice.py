"""Exact source methods of native_media_socket._lookup/_lookup_done (sanitized)."""
import asyncio
import logging
logger=logging.getLogger('mirror')
LOOKUP_TIMEOUT_S=2.0

class LookupTransport:
    async def _lookup(self,action):
        
        try:


            ticket=action.get('ticket')
            if ((ticket is not None and self.controller.ticket_stale(ticket))
                    or action.get('epoch')!=self.controller.epoch):
                return
            query=action.get('lookup_question',action['question'])
            await self._observe('lookup_start')
            if ((ticket is not None and self.controller.ticket_stale(ticket))
                    or action.get('epoch')!=self.controller.epoch):
                return
            rows=await asyncio.wait_for(self.early.resolve(action.get('input_turn_id'),query),LOOKUP_TIMEOUT_S)
            await self._observe('lookup_end',source_count=len(rows) if isinstance(rows,list) else 0)
            await self._lookup_done(action,*self.controller.lookup_result(action['epoch'],rows,ticket=action.get('ticket')))
        except asyncio.CancelledError:raise
        except Exception as error:

            await self._observe('lookup_failure',error_type=type(error).__name__)
            await self._lookup_done(action,*self.controller.lookup_result(action['epoch'],failure=error,ticket=action.get('ticket')))

    async def _lookup_done(self,action,actions,failure,reason):
        
        if failure=='moot':
            await self._observe('lookup_moot')
            logger.info('echo-sync lookup unused class=lookup reason=local_answer_stands')
            return
        if failure:
            await self._error(failure,reason,epoch=action['epoch']);return
        await self.actions(actions)

