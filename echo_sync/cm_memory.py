"""The memory methods of ``ControlledMedia`` (cut from controlled_media.py by tools/split_controlled_media.py). Imports from cm_base, never from controlled_media."""
import json
import re
from .cm_base import (ACK, BACK, ConversationLedger, HISTORY_EXCHANGES, LEDGERS_KEPT, NEXT, Path, REPEAT, RESUME, STOP,
    TURN_MAP_CAP, TURN_MAP_KEEP, UTTERANCE_TAIL_WORDS, QUESTION_WORDS, _LEDGERS, asked_of, complete_followup, is_followup, logger, norm_words, progress_note, resolve, unfinished_at)


class MemoryMixin:
    def forget_turns(self,*extra):
        """The ONE place that forgets turns (turn-memory): every map or set keyed by turn (``TURN_MAPS``, plus the ``extra`` sets a caller keeps, e.g. the socket's ``transcribed``) is cut when one of them is longer than TURN_MAP_CAP.
        It keeps the turns the ledger still holds, the ones in play (``_active_turn_ids``) and the newest TURN_MAP_KEEP of the others (c24 P17: these grew for the whole call); what was evicted from the ledger can no longer be asked about."""
        maps=[(name,getattr(self,name,None)) for name in self.TURN_MAPS]+[(None,value) for value in extra]
        if not any(isinstance(value,(dict,set)) and len(value)>TURN_MAP_CAP for _,value in maps):return
        live={t['id'] for t in self.ledger.history()}|self._active_turn_ids()
        for name,value in maps:
            if not isinstance(value,(dict,set)) or len(value)<=TURN_MAP_KEEP:continue
            gone=[key for key in value if key not in live]
            drop=set(gone[:max(0,len(gone)-TURN_MAP_KEEP)]) if isinstance(value,dict) else set(gone)-set(gone[-TURN_MAP_KEEP:])
            if not drop:continue
            if isinstance(value,dict):
                if name:setattr(self,name,{key:item for key,item in value.items() if key not in drop})
                else:
                    for key in drop:del value[key]
            else:value.difference_update(drop)
    def _active_turn_ids(self):
        """The turns of the question being answered and of the answer being streamed: the ledger must never evict them.

        Every ACK is a turn, so a long dictation pushes the question out of any bounded ledger by arrival order (the
        64-turn ledger lost it after 21-62 ACKs and the prompter went mute: NativeMediaSocket._can_play needs it). Only
        finished history is evicted, which keeps the ledger bounded.
        """
        return {tid for tid in (self.question_id,self.source_segment_id,self.source_id,self.held_source,getattr(self,'fast_turn',None)) if tid}      # c16: and the job's turn, before its first segment says so
    def _convo_open(self,path):
        """U14-S4 / M9: the call's ledger and its ear on the X-CUE source. Always: memory is not a switch. It is kept on disk beside the state file (the ledger turns the disk off by itself when it cannot write and goes on in memory)."""
        wall=lambda:self.engine.clock()      # noqa: E731 - M1-a: one clock: ``call_began`` and the ledger's wall stamps are the engine's
        key=(str(path),self.session_id)
        kept=_LEDGERS.get(key)      # M1-e: a ledger lives as long as the process, not the connection: a redial of the session goes on with it
        if kept is not None:kept.use_wall(wall);self.convo=kept;_LEDGERS.move_to_end(key)
        else:self.convo=ConversationLedger(directory=Path(path).parent/'conversation'/re.sub(r'[^\w.-]','_','%s-%s'%(Path(path).name,self.session_id)),wall=wall,since_on_wall=True)
        _LEDGERS[key]=self.convo
        while len(_LEDGERS)>LEDGERS_KEPT:_LEDGERS.popitem(last=False)
        self.lookup_topic=(self.state() or {}).get('question','')      # the topic of a redial is the question the engine's history holds (the one owner of what was asked); a call that begins anew ends it (``call_began``)
        self.subscribe_cue(self._ledger_cue)
    @property
    def lookup_topic(self):
        """M9 kind ``topic``: what a follow-up («а почему?») is about, held by the ledger (it ends with a new call, ``call_began``, A4)."""
        if self.convo is None:return ''
        return self.convo.held('topic','lookup') or ''
    @lookup_topic.setter
    def lookup_topic(self,value):
        if getattr(self,'convo',None) is None:return
        self.convo.hold('topic','lookup',getattr(self,'question_id',None),value,self.engine.clock())
    @property
    def call_began(self):return self.__dict__.get('_call_began')
    @call_began.setter
    def call_began(self,value):
        """A call that begins ends what the ledger holds for the call (kinds that end for 'call': the topic). ``None`` is the controller being built, not a call."""
        self.__dict__['_call_began']=value
        if value is not None and getattr(self,'convo',None) is not None:self.convo.end_all('call')
    def _ledger_turn(self,tid,text=None,revisions=0):
        """U14-S4: a final of the listener's words goes to the ledger with the ``final_rev`` the turn record (``Resolutions``) holds; before the judge has
        looked at it the provider's own count of refinements stands in. The ledger drops an exact (tid, final_rev) repeat."""
        if self.convo is None:return
        try:
            turn=self.ledger.snapshot(tid) if text is None else {'text':text,'revisions':revisions,'final':True,'role':'user'}
            if not turn or not turn.get('final') or turn.get('role')!='user':return
            rec=self.resolutions.records.get(tid)
            rev=max(rec['final_rev'] if rec else 1,1+turn.get('revisions',0))
            self.convo.user_final(tid,turn['text'],final_rev=rev,at=self.clock(),who=BACK if rec and rec.get('resolution')==ACK else None);self._memory_ready()      # M1-g: the judge heard the prompt said back: our words, not the room's
        except Exception:logger.debug('echo-sync ledger turn failed',exc_info=True)    # noqa: BLE001 - the ledger never costs the call
    def _memory_ready(self):
        """V6 memory: the ledger was written; the card's projection follows it now (``v6_memory.Memory.prepare``), not in the hook of the request. """
        ready=getattr(self,'memory_ready',None)
        if ready is not None:ready()
    def _ledger_answer(self,cue,at):
        """U14-S7: the first cue that begins for a revision writes its answer row; a revision after another supersedes the earlier row. A revision
        none of whose cues began has no row (it was never played, so ``played_words`` never holds it either)."""
        rev=cue.get('revision')
        if rev is None or (self._convo_ans and self._convo_ans[0]==rev):return
        try:
            state=self.state() or {};aid='r%s'%rev
            text=state.get('answer') if state.get('revision')==rev and isinstance(state.get('answer'),str) else None
            self.convo.answer(aid,text or cue.get('text') or '',tid=self.question_id,supersedes=self._convo_ans[1] if self._convo_ans else None,at=at)
            self._convo_ans=(rev,aid);self._memory_ready()
        except Exception:logger.debug('echo-sync ledger answer failed',exc_info=True)    # noqa: BLE001 - the ledger never costs the call
    def _ledger_cue(self,kind,cue,at,num):
        """U14-S4: the X-CUE source writes what was played (one cue is open at a time, so its ledger id is the current one)."""
        if kind=='began':
            self._ledger_answer(cue,at)      # U14-S7: the answer row stands before the first play of its revision
            self._convo_n+=1;self._convo_cue='c%d'%self._convo_n
            self.convo.play_began(self._convo_cue,cue.get('text') or '',at,num.get('voiced'));return
        name,self._convo_cue=self._convo_cue,None
        if name is None:return
        (self.convo.play_done if kind=='done' else self.convo.play_cut)(name,at)
    def _rule_went_to_the_answer(self,c):
        kind=c.decision.kind
        if kind in (ACK,STOP,REPEAT,NEXT):self.suspended=None      # said to the answer that is current: that is the answer
        if kind in (ACK,REPEAT,NEXT,RESUME):self.fast_mark=None
    def _queue_note(self,item):
        """Ruling 5a: an answer was left with something unsaid (a new question, a correction or a return replaced it, or the listener paused
        it). ONE quiet note tells the cloud model what was said of it and what was not (progress_notes.progress_note); it goes up once that
        is safe (``note_actions``). A newer note replaces one that has not gone yet."""
        if not item:return
        text=progress_note(item)
        if text:self.note_due=text
    def _note_safe(self):
        """May a note go up now? Only when nothing the cloud could say in reply can be dictated, and never while a speakable commit is
        pending (ruling 5c). That is: nobody is speaking and the latest user turn has been taken (a reply would belong to it); no context
        of the current question is waiting for its answer; and either no question is open (after «стоп», a restored answer, a question
        given up), or the open question's answer has been published and its stream is closed (nothing can be added to it any more)."""
        if self.hearing:return False
        user=self.ledger.latest_user()
        if user and (not user['final'] or user['id'] not in self.seen):return False
        if self.context_requested and not self.published:return False
        if self.question_id is None and (user is None or user['id'] in self.seen):return True
        if not self.published:return False
        state=self.state()
        return bool(state) and not state.get('streaming')
    def note_actions(self):
        """The note action to send now, if one is due and it is safe (the transport asks on every tick): ``[]`` or ``[{'type': 'note',
        'kind': 'progress', 'epoch', 'text'}]``. Ruling 5c: never more than one note per epoch, and never the same text twice in a row."""
        if self.convo is not None:self.convo.expire(self.engine.clock(),epoch=self.epoch)      # M9: what the call holds ends by its kind's rules, the tick is the clock
        text=self.note_due
        if text is None or not self._note_safe():return []
        self.note_due=None
        if text==self.noted_text or self.noted_epoch==self.epoch:
            logger.info('echo-sync note skipped kind=progress reason=%s',
                        'same_text' if text==self.noted_text else 'one_per_epoch')
            return []
        self.noted_text=text;self.noted_epoch=self.epoch;self.note_guard=True
        return [{'type':'note','kind':'progress','epoch':self.epoch,'text':text}]
    def _final_held(self,tid,words):
        """U91: is this final of a question one that an EARLIER call of this session (closed, within CONVERSATION_GAP_S: the ledger's kind 'final') opened already - same turn id and same words? Remembers this one otherwise."""
        if self.convo is None:return False
        now=self.engine.clock();raw=self.convo.held('final','session',now);then=json.loads(raw) if raw else None
        if then and then[0]!=self.nonce and then[3] and then[1:3]==[tid,words]:return True
        self.convo.hold('final','session',None,json.dumps([self.nonce,tid,words,False,now]),now)
        return False
    def _final_closed(self):
        """U91: the line of this call is closed: the final it opened a question for stays held, marked as closed, for the window it was held under."""
        raw=self.convo.held('final','session') if self.convo is not None else None;then=json.loads(raw) if raw else None
        if then and then[0]==self.nonce:then[3]=True;self.convo.hold('final','session',None,json.dumps(then),then[4])
    def fast_carry(self):
        """U14-S8: the recap of earlier calls for the model's prompt: built once per call, so the prompt stays the same and its cache holds. '' when no earlier call is in the ledger."""
        if self.convo is None:return ''
        if self._carry is None:
            try:self._carry=self.convo.recap_calls()
            except Exception:logger.debug('echo-sync ledger recap failed',exc_info=True);self._carry=''    # noqa: BLE001 - the ledger never costs the call
        return self._carry
    def _plan_said(self):
        """g28: the whole plan of the answer in play, cued or not (its words are the listener's to say back, never a question)."""
        state=self.state() or {}
        chunks=[chunk for chunk in state.get('chunks') or () if isinstance(chunk,str)]
        return [' '.join(chunks)] if chunks and state.get('question') else []
    def _asked_here(self,state=None):
        """The questions a follow-up may attach to: ``engine.asked_of`` of the state with the floor of THIS call (A4: a call that began after an answer was given does not inherit it: «а почему?» is no follow-up to yesterday's question).
        A call that was not begun anew (``call_began`` None, a redial inside the window) sees the whole history."""
        return asked_of(self.state() if state is None else state)
    def _follows_on(self,text,*,tail=False):
        """The one follow-up of the controller (``followup.is_followup``): does ``text`` hang on the question before it? By default over the questions of this call («а почему?» after one asked here).
        ``tail``: the final that ended a pause («А Новой Зеландии?», H6 R9): a short phrase with no question word of its own, by the shape of a follow-up; a whole question after a pause stands alone (H5)."""
        if not tail:return is_followup(text,self._asked_here())
        words=norm_words(text)
        return len(words)<=UTTERANCE_TAIL_WORDS and not frozenset(words)&QUESTION_WORDS and is_followup(text,loose=True)
    def _followup_of(self,text,history=None):
        """g31: ``text`` completed with the questions asked before it (``followup.complete``; ``history``: those questions, this call's by default), or None.
        «а пассивный» after «Что учитывает активный счёт?» is «Что учитывает пассивный счёт?» for the bank, the search and the model; «а пример» is that example of the question before."""
        return complete_followup(text,self._asked_here() if history is None else history)
