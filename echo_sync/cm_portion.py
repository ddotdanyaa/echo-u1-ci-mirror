"""The portion methods of ``ControlledMedia`` (cut from controlled_media.py by tools/split_controlled_media.py). Imports from cm_base, never from controlled_media."""
from .cm_base import (ABANDON_FINALS, ABANDON_SHARE, ACK, ANSWER_WAIT_SECONDS, CLOSED, EAR_RELEASE_SILENCE_SECONDS, EAR_TAIL_SILENCE_SECONDS,
    FIRST_TEXT_S, HESITATION_WORDS, MAX_RESTARTS, MONOLOGUE_QUIET_SECONDS, OPEN, OWNER_SILENCE_S, PLAN_BACK_SECONDS, QUESTION, QUIET, REFUSAL,
    REFUSE_BEFORE_DROP_SECONDS, REPEAT, SILENT, STOPWORDS, TEMPO_FILLER_SECONDS, TEMPO_HOLD_SECONDS, TEMPO_STEP_SECONDS, TEMPO_TEXT_SECONDS, WORDS,
    WRONG_REPEAT_SECONDS, _ENDS_SENTENCE, _MOVED_ON, _content, _valued, brain_answer, brain_command, command_ruling, cycle_wait,
    doubts, going_verdict, logger, norm_words, normalize, probe, re, record_on, repeat_cap, resolve, stable_prefix)
from .portioner import PortionAdapter

ADAPT_FAST_SLACK=1.5      # w2-portion: a portion confirmed within its cue plus this many seconds is «fast»


class PortionMixin:
    def _cue_tail(self,position,text='',sounded=False):
        """The tail of the waiting portion that is cued alone is kept with the cursor, in the engine's state (``engine.cue_tail``; read back by ``engine.tail_of(state)``). No ``position``: dropped."""
        if self.session_id:self.engine.cue_tail(self.session_id,position,text,sounded)
    def _go_lock(self,now):
        """U108 (2): the portion matched (``go_on``) is followed by the next one no later than OWNER_SILENCE_S after the last words of the owner, whatever the detector still says: a stuck onset, a cough, a breath keep ``hearing`` and
        the portion waits for nothing (the call of 13.11, 10-16 s). Words (the cloud's, the ear's) after the match are speech: the silence counts from the last of them."""
        if self.go_on is None:self._go_armed=None;return
        if self._go_armed is None or self._go_armed[0]!=self.go_on:self._go_armed=(self.go_on,now)
        if not self.hearing:return
        spoke=max(self.cloud_heard or 0,self.ear_words_at or 0)
        if spoke>self._go_armed[1]:self._go_armed=(self.go_on,spoke)
        if now-self._go_armed[1]<OWNER_SILENCE_S:return
        logger.info('echo-sync go_on_lock silent_s=%.1f revision=%s',now-self._go_armed[1],(self.state() or {}).get('revision'))
        if self.tempo_live:self.tempo_speaking=False;self.tempo_ended=now;self.tempo_awaits=None
        else:self._hearing_end()
    def _repeat_and_tail(self,turn,head):
        """Rule 2: the repeat is confirmed once, as a stable partial would have (the turn is taken), and its tail is judged alone by the path of a turn
        taken early (``_early_tail``). When the tail takes over, the next portion is not spoken first."""
        done=self._take_early({**turn,'text':head},head,'stable_partial')
        rest=self._early_tail(turn)
        if any(action['type']==self.ACT_WIRE for action in rest):done=[action for action in done if action['type']!='speak']
        return done+rest
    def _abandon(self,state):
        """c8b: the waiting portion is given up the way «следующий билет» ends an answer: nothing is cued, the engine retires it ('abandoned': its
        history entry says 'interrupted', and «повтори» / «продолжай» bring it back), the cloud's reply to the question is no longer the answer."""
        where=self._position(state);mark=self.abandon or {}
        cut=self._act('close_question','abandon')[1]      # c23 (F2): the suspended plan goes with it: the answer given up is the newest; «продолжай» brings IT back (the engine's 'abandoned' entry), never an older plan suspended under it
        logger.info('echo-sync decision kind=silent reason=portion_abandoned after_s=%.1f tried=%s revision=%s index=%s',
                    self.clock()-(mark.get('engaged') or mark.get('since') or self.clock()),mark.get('engaged') is not None,
                    *(where or (None,None)))
        return cut
    def _commit_restart(self,turn,keep,offset,marker=''):
        """The segment continues the answer: the first ``keep`` portions stay as they were spoken, then ``marker`` («Поправка:» for a
        correction) and the segment's text from ``offset`` (``EchoEngine.revise``); the segment is the answer's segment from now on (its later
        text, and segments that continue it, extend it the usual way). Nothing said yet: it simply takes the place of the cut segment."""
        tid=turn['id']
        if self.source_segment_id:self.closed_source_segments.add(self.source_segment_id)
        if not self.published:
            self.source_segment_prefix='';self.segment_offsets={tid:offset};self.source_segment_id=None
            self.pending_restart=None;self.restarts+=1;self.joined_segments.add(tid)
            logger.info('echo-sync decision kind=answer reason=restart_replaces_unspoken revision=%s',(self.state() or {}).get('revision'))
            return self._source(turn)
        state=self.state() or {}
        head=' '.join((state.get('chunks') or [])[:keep])
        base=(head+' '+marker).strip() if marker else head
        committed=base+(' ' if base else '')
        text=committed+turn['text'][offset:]
        if self.first_useful_gate:text=self._abbreviations(text)
        final=turn['final'] and bool(_ENDS_SENTENCE.search(text))
        prefix=text if final else stable_prefix(text,self.settings,committed=committed)
        if marker and not final and not (prefix or committed)[len(committed):].strip():
            self.closed_source_segments.discard(self.source_segment_id)
            return []                                       # never «Поправка:» alone: more of the segment first
        tail=(prefix or committed)[len(head):] if (prefix or committed).startswith(head) else ''
        reply=self._revise_to(keep,tail,final)
        if reply is None:
            self.closed_source_segments.discard(self.source_segment_id)
            return []                                       # nothing yet to say in place of the heard portion: weighed again later
        revision=self.revision
        self.source_segment_prefix='';self.segment_offsets={tid:offset};self.source_segment_id=tid
        self.restart_base=base;self.pending_restart=None;self.restarts+=1;self.unsettled=None;self.joined_segments.add(tid)
        if turn['final'] and not final:self.unsettled=(tid,self.turn_done_at.get(tid,self.clock()))
        logger.info('echo-sync decision kind=answer reason=%s keep=%s revision=%s','restart_corrected' if marker else 'restart_aligned',
                    keep,revision)
        return self._cue(reply)
    def _revise_to(self,keep,tail,final):
        """The one executor of «the answer goes on differently from the portion ``keep``» (restart of a cut segment and rewrite by the model: ``_restart_verdict`` and ``_rewritten`` are the two rules, this is the one act): ``EchoEngine.revise``, the cue of the portion replaced under the listener is cut, and the new revision and published text are the controller's. The reply to cue, or None when the stream cannot take a revision."""
        result=self.engine.revise(session_id=self.session_id,revision=self.revision,keep=keep,tail=tail,final=final)
        if result is None:return None
        reply,revision,answer=result
        if revision!=self.revision:self._act('cut_sound','revision_replaced')      # the portion the listener heard last was replaced: its cue is stale
        self.revision=revision;self.published=answer
        return reply
    def _rewritten(self,turn,text,settled):
        """DEF-T-B01 (T-B N01, audit M04): the cloud rewrote what it had said, and the controller had published some of it. Never dropped
        in silence with the stream left open, never spliced onto the old head:

        - the first word that changed is in a portion nobody has heard yet: that portion and the ones after it are replaced by the new
          text, without a word (what the listener heard stays);
        - the listener has heard it (a confirmed portion, or the one they are on): every portion not confirmed is replaced by an explicit
          correction, «Поправка: » and the new text from the sentence that changed (from the first portion not confirmed, when the change
          is there), and the answer ends with it.

        One correction per question, and the revisions of a question are bounded (MAX_RESTARTS, shared with the restarts): past that the
        producer's text is not followed any more, and a stream left open is ended by ``_stalled_stream``."""
        state=self.state()
        if (self.corrected or self.restarts>=MAX_RESTARTS or self.revision is None or not state or not state.get('chunks')
                or state.get('completed') or state.get('revision')!=self.revision):return []
        chunks,confirmed,heard=self._heard_span(state)
        said=norm_words(self.published);words=list(WORDS.finditer(text))
        new=[normalize(word.group()) for word in words]
        changed=next((i for i,(old,now) in enumerate(zip(said,new)) if old!=now),min(len(said),len(new)))
        sizes=[len(norm_words(chunk)) for chunk in chunks]
        holder=next((n for n in range(len(chunks)) if sum(sizes[:n+1])>changed),len(chunks))
        at=lambda count:words[count].start() if count<len(words) else len(text)
        final=(turn['final'] or settled) and (self.source_delivery!='delegation' or settled or bool(_ENDS_SENTENCE.search(text)))
        if holder>=heard:
            keep,tail,corrected=holder,text[at(sum(sizes[:holder])):],False
        else:
            before=sum(sizes[:confirmed])
            if changed<before:
                start=0
                for end in re.finditer(r'[.!?…]+(?=\s)',text[:at(changed)]):start=end.end()
            else:start=at(before)
            keep,tail,corrected,final=confirmed,'Поправка: '+text[start:].lstrip(),True,True
        reply=self._revise_to(keep,tail,final)
        if reply is None:
            # The stream cannot take a revision: it is ended as it stands, never left open in silence.
            self.engine.extend_answer(session_id=self.session_id,revision=self.revision,answer=self.published,final=True)
            logger.info('echo-sync decision kind=answer reason=rewrite_closed revision=%s',self.revision)
            return []
        revision=self.revision
        if corrected:self.corrected=True
        else:self.restarts+=1
        logger.info('echo-sync decision kind=answer reason=%s keep=%s revision=%s','rewrite_corrected' if corrected else 'rewrite_unheard',
                    keep,revision)
        return self._cue(reply)
    def _going_on(self,turn,decision,state,tail=False,going=None):
        """NEXT («дальше»), RESUME («продолжай», «вернёмся к прошлому вопросу») and a «вернёмся к <тема>» that returns to an unfinished
        answer (ruling 4e) are served from the local plan, as the engine decides (engine.going_on: the same pure rule, the engine's clock).
        Returns ``(decision, actions)``; ``actions`` is ``None`` when the utterance goes on as ``decision`` (a question: 4d, or a topic
        change that returns to nothing).

        In every local branch the cloud is asked nothing and its own reply to the utterance is never dictated: no question is opened (the
        reply belongs to a turn that is not the question), and a restored answer opens none either (``question_id`` stays None, as after
        «стоп»: the plan is local, nothing of the cloud joins it). A call that was just reopened presents the stored portion before
        anything moves (like «повтори»: the persisted position is no playback authority until it has been presented), so a NEXT there
        says that portion rather than skipping it."""
        plan,target=going or (None,None)      # the plan is a feature of the verdict (``_rule_going_on``)
        if plan is None:return decision,None
        if plan=='question':
            # 4d: nothing of ours to go on with (a complete answer: «продолжай» means «say more»): the words as said are the question.
            return decision._replace(kind=QUESTION,question=decision.question or turn['text']),None
        tid=f'{self.nonce}:{turn["id"]}'+(':tail' if tail else '')
        if plan=='quiet':
            logger.info('echo-sync decision kind=%s reason=%s:nothing_to_go_on_with',decision.kind,decision.reason)
            return decision,[]
        if plan=='restore':
            before=state or {}
            cut=self._act('close_question','going_on')[1]
            reply=self._reply(turn['text'],tid,decided=going_verdict(decision,plan),going=(plan,target),basis=self._basis(state))
            after=self.state() or {}
            self.lookup_topic=str(after.get('question') or '')[:300]      # a follow-up («а почему?») is about the restored answer
            # The answer it replaces (a return form while another answer waited) is left unfinished: noted like a new question's.
            self._queue_note(self._superseded(before,after))
            logger.info('echo-sync decision kind=resume reason=unfinished_answer_restored revision=%s',after.get('revision'))
            self.local_request=(turn['id'],turn['text'],self.clock())
            return decision,cut+self._cue(reply)
        if plan=='presented':      # the portion has sounded since that speech ended: presented already, «дальше» said before it neither skips nor says it once more
            logger.info('echo-sync decision kind=%s reason=%s:presented_since',decision.kind,decision.reason);return decision,[]
        self.local_request=(turn['id'],turn['text'],self.clock())
        text=turn['text']
        if plan=='present':text='повтори';said=command_ruling(REPEAT),None      # the portion is presented, not skipped (the judge's plan): the verdict is a repeat
        else:said=going_verdict(decision,plan),(plan,target)
        actions=self._cue_unless_spoken_over(self._reply(text,tid,decided=said[0],going=said[1],basis=self._basis(state)))
        if not actions and self.engine.current(self.state())!=SILENT:self.resume_repeat=True
        return decision,actions
    def _flow_due(self,now):
        """w5-flow: what ``flow_ahead`` says now. 'prepare': the transport may synthesize the next portion (an action it may ignore).
        'release' due: the waiting portion is confirmed the way the ear confirms it (the cloud's open turn of the utterance, when there is one,
        is taken: its final is only a tail, ``_early_tail``). 'withdraw' of a sent one: the step is taken back as ``_ear_overruled`` takes it
        and the portion is cued again."""
        if self.flow is None or self.flow.p is None:return []
        d=self.flow.decide(now)
        if d.action=='prepare' and self.flow.p.next_text:
            return [{'type':'prepare','text':self.flow.p.next_text,'epoch':self.epoch,'nonce':self.nonce}]
        if d.action=='release' and d.at is not None and d.at<=now:
            state=self.state();portion=probe('waiting_portion',state=state).value
            if portion is None or portion!=self.flow.p.text:
                self.flow.p.off='moved';return []
            tid=self._open_turn_id('flow',self.flow_uid)
            self.flow_take={'state':state,'tid':tid}
            logger.info('echo-sync decision kind=ack reason=flow_ahead uid=%s revision=%s index=%s',self.flow_uid,state.get('revision'),state.get('chunk_index'))
            turn=self.ledger.snapshot(tid) or {'id':tid,'role':'user','valid':True}
            return self._take_early(turn,portion,'flow_ahead')
        if d.action=='withdraw' and d.reason.endswith(':sent') and self.flow_take is not None:
            before=self.flow_take['state'];self.flow_take=None
            if not self.engine.rewind(session_id=self.session_id,revision=before['revision'],index=before['chunk_index'],
                                      waiting=bool(before.get('stream_waiting_next'))):return []
            logger.info('echo-sync decision kind=silent reason=flow_withdrawn why=%s revision=%s index=%s',d.reason,before['revision'],before['chunk_index'])
            return self._act('reset_portion','flow_withdrawn',basis=(None,before['revision'],None))[1]+self._cue(probe('waiting_portion',state=self.state()).value)
        return []
    def first_cue_opens(self):
        """H7 item 6 (Б4, ``prepare_wide``): the moment the silence of ``_utterance_over`` lets the first cue go, when nothing but that silence holds it; None otherwise: the tick looks."""
        now=self.clock()
        if not self.prepare_wide or not self.tempo_live or self.tempo_ended is None or self._speech_open(now) or (self.candidate and 'job' in self.candidate) or (self.tempo_awaits is not None and now<self.tempo_ended+TEMPO_TEXT_SECONDS):return None
        return self.tempo_ended+self._release_wait(self.question_text)
    def _release_wait(self,text):
        """one-research EOT-RU: the ear's silence that ends the utterance of ``text``: an open tail EAR_TAIL_SILENCE_SECONDS, a question asked whole the speaker's own pause (``local_ear.PauseLearner``: at most EAR_RELEASE_SILENCE_SECONDS, at least CLOSED_MIN_S), the rest EAR_RELEASE_SILENCE_SECONDS."""
        end=probe('turn_end',text).value
        return EAR_TAIL_SILENCE_SECONDS if end==OPEN else (min(EAR_RELEASE_SILENCE_SECONDS,self.pauses.wait()) if end==CLOSED else EAR_RELEASE_SILENCE_SECONDS)
    def _contests(self,text):
        """Lane A: is ``text`` an argument with the answer («Да нет, …», «Неправда, …», a word of doubt in it)? It is addressed to the answer, so it is no talk around it: the clock of ``_abandons`` restarts."""
        words=[w for w in norm_words(text) if w not in ('да','ну','а','так')]
        return bool(words) and (words[0] in ('нет','не','неправда','неверно') or doubts(text))
    def _requests(self,text):
        """Lane A: does a sentence of ``text`` ask the prompter for something («Угу, ага, понятно. А можно какой-нибудь пример»)? Speech that asks is no talk around the portion either."""
        for sentence in re.split(r'[.!?;]+',str(text or '')):
            words=[w for w in norm_words(sentence) if w not in HESITATION_WORDS]
            while words and words[0] in ('а','ну','и','так','да'):words=words[1:]
            if words and (words[0] in ('можно','можешь','можете') or words[:2]==['могли','бы']) and len(words)>2:return True      # a request of permission or ability, with an object
        return False
    def _abandons(self,tid,text,decision,reason,state):
        """Lane A (13 Nov, map §7.4 and §8.4), the one owner of «the waiting portion yields» (c8b, ABANDON_SECONDS): does this final of other
        speech (``_MOVED_ON``; two words of content or more, less than ABANDON_SHARE of them the answer's own, else it is a try that failed and
        restarts the clock) show that the portion has fallen asleep? It has when its clock has run ABANDON_SECONDS - from its last cue
        (``_plan_mark``) or the listener's last try before this speech began; once the auto-repeats spent their cap, from the last try only (none:
        at once) - and ABANDON_FINALS finals of other speech came. Under the dictation cycle (h28, ruling 8.2.2) the clock alone never does, the
        count of repeats does. Never for a paused answer («стоп» holds it on purpose) or one still being made. The final is then judged again as
        when nothing waits (the redo of ``_accept_user``)."""
        if decision.kind!=QUIET or reason not in _MOVED_ON or not state or state.get('paused') or state.get('pending_turn'):return False
        where=self._position(state);now=self.clock()
        if where is None:return False
        if len([w for w in norm_words(text) if w not in STOPWORDS and w not in HESITATION_WORDS and (len(w)>=3 or w.isdigit())])<2:
            return False                # noise («э-э мм кхм»), a lone word (a slow repeat goes word by word): neither a try nor other speech
        seen=probe('portion_share',text,state=state,settings=self.settings,loose_numbers=self.fast_call);share=(seen.value if seen.known else 0.0) or 0.0      # the registry row (M7/S1) is the one reader of the classifier's portion_share
        if share>=ABANDON_SHARE or (share>0 and self._contests(text)) or self._requests(text):        # mostly the answer's own words (a neighbour portion, a wrong repeat, a wrong number), or a word of it in an argument with it: a try that failed, never talk
            self._engaged(state)
            return False
        mark=self.abandon
        if mark is None or mark['at']!=where:self.abandon=mark={'at':where,'since':now,'engaged':None,'capped':None,'others':0}      # its cue was never seen: the clock starts now
        mark['others']+=1
        start=self.user_started_at.get(tid,now)
        tried=mark['engaged'] if mark['engaged'] is not None and mark['engaged']<start else None      # the partial words of this very speech are no try before it
        capped=mark['capped'] is not None and start>=mark['capped']
        origin=tried if capped else max(moment for moment in (self._plan_mark(state)['cued'],mark['since'],tried) if moment is not None)      # after the cap the cues of the timer prove nothing
        if origin is not None and now-origin<self.abandon_seconds:return False
        if mark['others']<ABANDON_FINALS or (not capped and self._cycling()):return False      # h28: under the cycle the clock alone does not end the portion, the count of repeats does
        logger.info('echo-sync portion_asleep path=%s share=%.2f age_s=%s others=%s revision=%s index=%s','cap' if capped else 'clock',share,
                    'none' if origin is None else '%.1f'%(now-origin),mark['others'],*where)
        return True
    def _said_words(self,text):
        """The words of an utterance from its first one that is not a filler or a hesitation."""
        words=norm_words(text);fillers=frozenset(resolve(self.settings)['fillers'])|HESITATION_WORDS
        while words and words[0] in fillers:words=words[1:]
        return words
    @staticmethod
    def _position(state):
        """Which portion waits for its confirmation: ``(revision, index)``, or ``None`` when none does."""
        return (state['revision'],state['chunk_index']) if probe('waiting_portion',state=state).value is not None else None
    def heard_since_portion(self):
        """The pieces of speech (finals) the listener has said since the waiting portion started that confirmed nothing, oldest
        first, still inside the joining window."""
        position=self._position(self.state());now=self.clock()
        return [text for where,text,when in self.fragments if where==position and 0<=now-when<=self.ack_join_seconds]
    def _watch_partial(self,turn):
        """L1: the partial transcript of the listener's turn may already be the whole confirmation. Note it; ``_stable_due``
        accepts it once it has been unchanged for ``ack_stable_seconds``. Every change of the text starts the wait again."""
        tid=turn['id'];self.partial_ack=None
        if not self.ack_stable_seconds or tid in self.seen or not turn['valid']:return
        if not self.reopen_lets(ACK):return   # persisted position is not playback authority in a new call
        state=self.state();portion=probe('waiting_portion',state=state).value
        if portion is None or self._may_still_grow(portion):return
        if self._confirming_text(turn['text'],state) is not None:
            self.partial_ack=(tid,turn['text'],self.clock(),self._position(state))
    def playback_done(self,cue,*,now,voiced_until=None):
        """The transport has paced the whole PCM of ``cue`` out (``now``); its voice stopped at ``voiced_until`` (earlier than the
        PCM end by the silence left after it). Both the window of the cue and the silence timer count from where the voice stopped
        (task S0): the transport trims that silence (pcm_trim.trim_trailing_silence), and how long the listener is given must not
        depend on how much of it the PCM still carries. Without ``voiced_until`` the PCM end stands for the end of the voice."""
        self._cue_event('done',cue,now)
        if self.authorized(cue):
            self.cue_outstanding=False;self.cue_heard=True
            # Durations, not the transport's timestamps: the voice stopped (now-voiced_until) before the PCM ended, which is about now.
            silence=max(0.0,now-voiced_until) if isinstance(voiced_until,(int,float)) else 0.0
            here=self.clock();ended=here-silence
            self.cue_window=[self.cue_window[0] if self.cue_window else here,ended+self.cue_tail_seconds]
            self.resume_repeat=False;self.repeat_at=now-silence+self._repeat_wait()
    def _listener_waits(self):
        """Has the listener run out of published text, or is there none yet? Only then is the end of an answer declared on time alone:
        the next portion is what they wait for. While they are still working through what was published a continuation can yet come,
        in time to be merged, and nobody waits for the flush: it is made the moment they catch up (the next tick)."""
        if not self.published:return True
        state=self.state()
        return not state or not state.get('streaming') or bool(state.get('stream_waiting_next'))
    def _idle_candidate(self):
        """``(turn, time of its last event)`` of the continuation segment that ``_flush_idle`` waits to go quiet, else ``None``. Only a
        continuation: the first segment of an answer may be a producer still thinking, and its silence proves nothing. Like ``_settle``,
        only for a listener who has run out of published text."""
        tid=self.source_segment_id
        if not tid or not (self.source_segment_prefix or tid in self.segment_offsets) or tid==self.settled_segment:return None
        last=self.activity_at.get(tid)
        if last is None:return None
        turn=self.ledger.snapshot(tid)
        if not turn or not turn['valid'] or turn['role']!='assistant' or turn['final']:return None
        if tid in self.retired_assistants or self.owners.get(tid)!=self.question_id or not self._listener_waits():return None
        return turn,last
    def _flush_idle(self,now):
        """A continuation segment whose producer fell silent without ever closing its turn: ``segment_idle_seconds`` after its last
        event, the text that did arrive is the end of the answer."""
        candidate=self._idle_candidate()
        if candidate is None or now-candidate[1]<self.segment_idle_seconds:return []
        turn=candidate[0];self.settled_segment=turn['id'];self.unsettled=None
        logger.info('echo-sync decision kind=answer reason=segment_idle revision=%s',(self.state() or {}).get('revision'))
        return self._source(turn,settled=True)
    @property
    def adapter(self):
        """M4: the one rule of the length of the portions not yet said (portioner.PortionAdapter), fed by ``_adapt_observe``; always on."""
        if getattr(self,'_adapter',None) is None:self._adapter=PortionAdapter()
        return self._adapter
    @adapter.setter
    def adapter(self,value):self._adapter=value
    def _adapt_observe(self,now):
        """M4, w2-portion: watches the cursor of the engine. A portion is CONFIRMED when the cursor of the same answer moves one forward; the record carries
        the signals of that portion (reissued at all = repeat asked or said again by silence, a tail cue = stumbled, the cue plus ADAPT_FAST_SLACK s = fast).
        A change of level cuts the rest of the answer again (``EchoEngine.adapt_rest``) when nothing is playing and nothing is paused; otherwise it waits."""
        state=self.state()
        if not state or state.get('pending_turn'):return
        where=(state.get('revision'),state.get('chunk_index'))
        seen=getattr(self,'_adapt_seen',None)
        stamp=(state.get('issued_at'),state.get('issued_syl'))
        if seen is None or seen['at'][0]!=where[0]:self._adapt_seen=seen={'at':where,'reissues':0,'stamp':stamp,'first':stamp,'tail':False}
        elif seen['at'][1]!=where[1]:
            if where[1]==seen['at'][1]+1:
                issued,syl=seen['first']
                cue_s=(syl if isinstance(syl,(int,float)) else 0)*resolve(self.settings)['sec_per_syllable']
                fast=type(issued) in (int,float) and now-issued<=cue_s+ADAPT_FAST_SLACK
                change=self.adapter.record(first_try=seen['reissues']==0 and not seen['tail'],fast=bool(fast),stumbled=seen['tail'],repeat_asked=seen['reissues']>0)
                if change:self._adapt_pending=(where[0],change)
            self._adapt_seen=seen={'at':where,'reissues':0,'stamp':stamp,'first':stamp,'tail':False}
        elif stamp!=seen['stamp']:seen['reissues']+=1;seen['stamp']=stamp
        tail=self.engine.tail_of(state)
        if tail and tail[0]==self._position(state):seen['tail']=True
        pending=getattr(self,'_adapt_pending',None)
        if pending and (pending[0]!=where[0] or state.get('completed')):self._adapt_pending=pending=None
        if pending and not state.get('paused') and not self._cue_playing(now) and not self.hearing:
            self._adapt_pending=None
            got=self.engine.adapt_rest(session_id=self.session_id,revision=state['revision'],level=pending[1]['level'])
            logger.info('echo-sync portion_adapt level=%s from=%s reason=%s n=%s changed=%s revision=%s index=%s',pending[1]['level'],pending[1]['from'],pending[1]['reason'],pending[1]['n'],int(got is not None),state['revision'],state['chunk_index'])
    def tick(self,*,now):
        self._adapt_observe(now)
        self._go_lock(now)
        self._expire_hearing(now)
        self._tempo_safely(self._tempo_stuck,now)
        self._ear_safely(self._ear_expire,now,default=False)
        flowed=self._ear_safely(self._flow_due,now,default=[])   # w5-flow: the next portion ahead, or its withdrawal
        if flowed:return flowed
        heard=self._ear_safely(self._ear_bind_pending)     # R-EAR-ACT: a verdict of the local ear that may be taken now
        if heard:return heard
        opened=self._ear_safely(self._ear_first_due)       # H4: a question the ear may open now
        if opened:return opened
        waited=self._reference_due(now)
        if waited:return waited
        stable=self._stable_due(now)
        if stable:return stable
        released=self._release_held(now)
        if released:return released
        settled=self._settle(now) or self._candidate_settled(now) or self._candidate_released(now) or self._plan_after_decline(now) or self._fast_tail_due(now) or self._fast_ask() or self._fast_mark_due(now) or self._tempo_safely(self._ear_final_due,now,default=[])
        if settled:return settled
        idle=self._flush_idle(now)
        if idle:return idle
        restarted=self._flush_restart(now)
        if restarted:return restarted
        unanswered=self._answer_watchdog(now)
        if unanswered:return unanswered
        if self.reopened:return []
        if self.go_on is not None and not self.hearing:
            where,self.go_on=self.go_on,None
            state=self.state();portion=self.engine.current(state)
            if self._position(state)==where and portion!=SILENT:
                logger.info('echo-sync decision kind=next reason=a_try_counts revision=%s index=%s',state['revision'],state['chunk_index'])
                self._went_on(where,probe('waiting_portion',state=state).value);ahead,self.go_ahead=self.go_ahead,None
                cue=self._reply(portion,f'{self.nonce}:try:{where[0]}:{where[1]}',decided=command_ruling(ACK),basis=where);after=self.state();there=self._position(after)
                for read in (ahead[1] if ahead and ahead[0]==where else ()):      # c23 (g7 of the ear): the next portion(s) said whole ahead of the cue: not cued, the one after is; the cloud's final is the try's. U60: any number of them
                    if not cue==read==probe('waiting_portion',state=after).value:break
                    logger.info('echo-sync decision kind=next reason=a_try_said_ahead revision=%s index=%s',after['revision'],after['chunk_index'])
                    self.portion_tries=(there,list(self.went_on[2]));self._went_on(there,cue);cue=self._reply(cue,f'{self.nonce}:ahead:{there[0]}:{there[1]}',decided=command_ruling(ACK),basis=there);after=self.state();there=self._position(after)
                return self._cue(cue)
        if not self.hearing and self.resume_repeat:
            self.resume_repeat=False
            if self.tempo_live:self._tempo_resume(now)
            else:self.repeat_at=now+(WRONG_REPEAT_SECONDS if self.said_wrong else self._repeat_wait())
            self.said_wrong=False
        if not self.hearing and self.repeat_at is not None and now>=self.repeat_at:
            gated=self._repeat_gate(self.state(),now)      # x-tick: the one ordered gate in front of the repeat; the cap (4th) stays below, where the portion is known
            if gated:
                if gated=='tempo_hold':self._tempo_safely(self._tempo_waits,now,default=False)      # its own clears and re-arms stand
                return []
        if (self.tempo_live and self._tempo_safely(self._tempo_waits,now,default=False)) or self.hearing or self.repeat_at is None or now<self.repeat_at:return []
        state=self.state();portion=self.engine.current(state)   # read first: a failure here must not lose the timer (DEF-FAULT-10)
        self.repeat_at=None
        if portion==SILENT or str(portion).startswith(REFUSAL.split('.')[0]):return []      # the honest sentence of the roads is said once: it is no portion of an answer the silence timer says again
        if isinstance(portion,str) and portion.strip() and REFUSAL.startswith(portion.strip()):return []      # nor any head of it (merge-10: a refusal cut into a portion is not repeated by silence)
        # This is the only place where the prompter repeats a portion on its own. Count per portion; the listener
        # being heard (_accept_user, partial_quiet) starts the count again, so only SILENCE is bounded.
        spot=(state['revision'],state['chunk_index'])
        if spot!=self.auto_repeat_of:
            if self.auto_repeat_of is None or self.auto_repeat_of[0]!=spot[0]:self.answer_repeats=0      # x-cap: a new revision is a new answer
            self.auto_repeat_of=spot;self._auto_repeats=0      # a new portion: its own count; the answer's and the owner's flags stand
        if self.tempo_live and self._try_went(self._position(state),portion):
            logger.info('echo-sync decision kind=next reason=a_try_counts revision=%s index=%s',state['revision'],state['chunk_index'])
            self._went_on(self._position(state),probe('waiting_portion',state=state).value)
            return self._cue(self._reply(portion,f'{self.nonce}:try:{state["revision"]}:{state["chunk_index"]}',decided=command_ruling(ACK),basis=self._basis(state)))
        if self.tempo_live and getattr(self,'ear_asked_on',None)==state['revision']:
            # W14 (Р052 seed 2): the ear heard a new question over this plan and nothing answered it (the cloud's turn went another way): the person has
            # moved on, the old plan is not said again on its own - that is an answer of an older question after a newer one (A2)
            logger.info('echo-sync decision kind=silent reason=ear_heard_a_new_question revision=%s index=%s',state['revision'],state['chunk_index'])
            return []
        count,cap,why,scope=self._cap_count()
        if count>=cap:
            # No content, no identifiers: the owner has to be able to tell why the phone went quiet.
            logger.info('echo-sync decision kind=silent reason=auto_repeat_cap repeats=%s revision=%s index=%s cap=%s why=%s count=%s scope=%s unplaced=%s',
                        self.auto_repeats,state['revision'],state['chunk_index'],cap,why,count,scope,self.unplaced)
            return []
        cue=self._missing_part(portion,state)
        if self._rule_on() and cue!=portion and self.tempo_start is not None and self.rule_helped!=self.tempo_start:self.rule_helped=self.tempo_start      # c22-repeat: the help of a stumble answers speech, once for it: no automatic repeat
        else:
            self.auto_repeats+=1;self.answer_repeats+=1
            if self.unplaced:self.unconfirmed_repeats+=1      # u17-s5: after speech nobody placed the repeats are counted on their own against max_auto_repeats
            helped=self.rule_helped if self._rule_on() else None
            if cue==portion and helped and helped[0]==self._position(state) and str(portion).endswith(helped[1]):cue=helped[1];self._cue_tail(helped[0],cue)      # c22-repeat: silence after a stumble: help from the same word, however long the silence
        if self.abandon is not None and self.abandon['at']==spot:self.abandon['timed']=True      # H6 item 2 (``_at_it``)
        if self._cap_count()[0]>=self._repeat_cap() and self.abandon is not None and self.abandon['at']==spot:self.abandon['capped']=self.clock()
        if self.tempo_live:
            self.tempo_spoke=self.clock();count,cap,why,scope=self._cap_count()
            logger.info('echo-sync decision kind=replay reason=ear_tempo repeats=%s revision=%s index=%s cap=%s why=%s count=%s scope=%s unplaced=%s',self.auto_repeats,state['revision'],state['chunk_index'],cap,why,count,scope,self.unplaced)
        return self._cue(cue)
    def _rule_joined_repeat(self,c):
        state=c.state
        if c.decision.kind!=ACK and not c.tail and not c.disputed:
            # ACK-split: a full repeat outranks anything else this piece looks like, so look for one first.
            joined=self._joined_repeat(c.text,state) or self._tail_repeated(c.text,state)
            if joined:
                c.text=joined;c.decision=self._analyze(c,c.text,state);c.spoke('joined_repeat')
                logger.info('echo-sync decision kind=ack reason=joined_fragments pieces=%s revision=%s',
                            len(self.heard_since_portion())+1,(state or {}).get('revision'))
    def _heard_missing(self,portion,state):
        """F7: how far the finals since the portion started got: the newest speech first, and it is read with the finals before it joined to it (the cloud cuts one breath into
        «свойство» | «тела»), then the older finals alone; against the portion and against the tail that was cued (a second stall inside the tail cues what is left of it)."""
        pieces=self.heard_since_portion();wholes=[portion]
        tail=self.engine.tail_of(state)
        if tail and tail[0]==self._position(state):wholes.append(tail[1])
        for text in [' '.join(pieces[-count:]) for count in range(1,len(pieces)+1)]+list(reversed(pieces[:-1])):
            found=[said for said in ((self._said_of(text,whole) or (self._started(text,whole) if self._rule_on() else None)) for whole in wholes) if said]      # h26: a start in the middle counts here too
            if found:return min(found,key=lambda said:len(said[0]))
        return None
    def _missing_part(self,portion,state):
        """What the silence timer says: the whole portion, or only what is missing when the listener stopped after a start of it (rule 3)."""
        found=self._tempo_missing(state) or self._heard_missing(portion,state)
        if not found:
            self._cue_tail(None)                  # the whole portion again: it is the whole portion that is repeated now
            return portion
        self._cue_tail(self._position(state),found[0])
        return found[0]
    def _plan_mark(self,state):
        """What ``_plan_stands`` needs of the plan in ``state``, told when a question takes it over: when it was last cued, and whether the listener was at it. ``cued`` is the ONE clock of «since the portion was cued»: G3 (``_plan_stands``, PLAN_BACK_SECONDS) and the portion that falls asleep (``_abandons``, ABANDON_SECONDS <= PLAN_BACK_SECONDS, R12) both read it here."""
        return {'cued':self.cue_window[0] if self.cue_window else None,'at_it':self._at_it(state),'age':self._age_of(state)}
    def _engaged(self,state,to_it=True):
        """c8b: the listener has just worked on the portion that waits: its clock of other speech starts again. ``to_it``: his words were said to it: a question is neither (H6 item 2, ``_at_it``)."""
        where=self._position(state);now=self.clock()
        if where is None:return
        self.tempo_others=None
        if self.abandon is None or self.abandon['at']!=where:self.abandon={'at':where,'since':now,'engaged':now,'capped':None,'others':0}
        else:self.abandon.update(engaged=now,others=0)
        if to_it:self.abandon['said']=now
    def _unheard(self,said):
        """F1 round 2: the content items (``_valued``) of the answer after the text the listener has heard (``said``, its items): what the
        cut segment said that nobody has heard yet. None when the heard words are not found in the answer in order."""
        text=self._answer_so_far()
        items=_valued(_content(text),text)
        found,last=0,-1
        for i,item in enumerate(items):
            if found<len(said) and item[0]==said[found][0]:found,last=found+1,i
        return items[last+1:] if found==len(said) else None
    def _cue_unless_spoken_over(self,reply,first=False):
        """c24 P07 (seed 293): the cue of a local request («продолжай», «дальше») whose final comes while the owner already says the next utterance: the plan
        moves, its cue waits for the silence after it (the tempo, ``resume_repeat``; a question there retires it), never parked to sound as that utterance's answer."""
        if reply and reply!=SILENT and self.hearing:
            logger.info('echo-sync decision kind=silent reason=cue_waits_newer_speech');self.repeat_at=None;self.resume_repeat=True;return []
        return self._cue(reply,first=first)
    def _unheard_before(self,turn,state):
        """A1-F6: had the listener not heard the portion ``state`` waits at when the speech of ``turn`` ended? Not heard on this call at all, or heard first after that speech
        ended on the provider's clock (``portion_heard``, ``_speech_start_ms``)."""
        snap=self.ledger.snapshot(turn['id']) or turn;end=snap.get('end_ms')
        if self._speech_start_ms(snap) is None or type(end) not in (int,float):return False     # the provider does not say when it was said: as before
        heard=self.portion_heard
        if heard is None or heard[0]!=((state or {}).get('revision'),(state or {}).get('chunk_index')):return True
        return type(heard[1]) in (int,float) and end<=heard[1]
    def _heard_since(self,turn,state):
        """c24 P06: has the portion ``state`` waits at sounded on this call after the speech of ``turn`` ended (``portion_heard``)?"""
        end=(self.ledger.snapshot(turn['id']) or turn).get('end_ms');heard=self.portion_heard
        return type(end) in (int,float) and heard is not None and heard[0]==((state or {}).get('revision'),(state or {}).get('chunk_index')) and type(heard[1]) in (int,float) and end<=heard[1]
    @staticmethod
    def _may_grow_into(start,numbers):
        """Can a number still being said, whose words so far read ``start`` («тысяча девятьсот» = #1900), become one of ``numbers`` (#1914:
        what is left is below the place its last word set, 14 < 100; #421 from #420, #25 from #20)? Digits typed so far grow too (#19 on the
        way to #1945). Never a smaller number, never #200 -> #100."""
        try:value=float(start[1:])
        except ValueError:return False
        zeros=len(start[1:])-len(start[1:].rstrip('0')) if value.is_integer() and '.' not in start else 0
        for number in numbers:
            try:other=float(number[1:])
            except ValueError:continue
            if other==value or 0<other-value<10**zeros or number[1:].startswith(start[1:]):return True
        return False
    def _cycling(self):
        """h25: the owner's cycle: silence repeats, the place is kept, a confirmed end moves on once. h28: no mode and no command: aloud or on paper it is the same silence (7 Nov: «надо было сказать, я начинаю писать, но это тупо»)."""
        return (getattr(self,'settings',None) or {}).get('dictation_cycle')=='on'
    def _record_progress(self,where):
        """u18-s3: the owner went on from the portion ``where`` (``(revision, index)``, the place before the advance). A set of places per revision: the same words said twice are one advance (S36, S37); a new revision starts over.
        With ``record_mode`` off the state is only logged (``record_shadow=``)."""
        if where is None:return
        revision,index=where
        if self.record_seen is None or self.record_seen[0]!=revision:self.record_seen=(revision,set())
        if index in self.record_seen[1]:return
        self.record_seen[1].add(index)
        if not record_on(resolve(self.settings)['record_mode']):logger.info('echo-sync decision kind=silent reason=record_progress record_shadow=%s revision=%s index=%s advances=%s',self._recording(),revision,index,len(self.record_seen[1]))
    def _cap_count(self):
        """x-cap: ``(count, cap, why, scope)``: the repeats counted (the portion's, or the answer's when ``repeat_scope`` is "answer") against the one cap of ``repeat_rule.repeat_cap``."""
        cfg=resolve(self.settings);scope=cfg['repeat_scope']
        cap,why=repeat_cap(cycling=self._cycling(),recording=self._recording(),unplaced=self.unplaced,record_mode=cfg['record_mode'],cycle_max_repeats=cfg['cycle_max_repeats'],max_auto_repeats=self.max_auto_repeats,duplex=self._duplex())
        count=self.unconfirmed_repeats if self.unplaced else (self.answer_repeats if scope=='answer' else self.auto_repeats)      # u17-s5: unplaced switches the count to (unconfirmed_repeats, max_auto_repeats)
        return count,cap,why,scope
    def _repeat_cap(self):
        return self._cap_count()[1]
    def _repeat_wait(self):
        """How long the silence timer waits after a cue: ``repeat_seconds``. H3 rule 2: TEMPO_STEP_SECONDS more for each automatic repeat this portion has had."""
        if self._cycling():
            state=self.state() or {}
            return cycle_wait(self.auto_repeats if self.auto_repeat_of==(state.get('revision'),state.get('chunk_index')) else 0)      # h31: the count of this portion, not of the one before; h25: the owner's cycle; h28: longer as silence goes on, it is the hand or nobody
        tools=self._record_tools();state=(self.state() or {}) if self.tempo_live or tools else {}
        wait=self.repeat_seconds if not self.tempo_live else self.repeat_seconds+(TEMPO_STEP_SECONDS*self.auto_repeats if self.auto_repeat_of==(state.get('revision'),state.get('chunk_index')) else 0)
        return self.dictating.pace.wait(probe('waiting_portion',state=state).value or '',wait) if tools else wait      # c22-repeat: while dictating silence is the hand writing: the owner's tempo
    def _tempo_declined(self):
        """Rule 5: the job took the final for nothing to answer: the timer runs again, unless later speech has its own final to come: the hold is that speech's."""
        if self.tempo_live and not self._tempo_unheard(self.clock()):
            state=self.state();self.tempo_hold=None;due=self.clock()+self._repeat_wait()
            if self.cue_window and (self.clock()-self.cue_window[0]>=PLAN_BACK_SECONDS or not self._at_it(state)):      # H6 item 2: the one rule: a decline runs no timer for a portion the listener has left: it waits for his words
                self.repeat_at=None;return
            self._tempo_arm(min(due,self.repeat_at) if self.repeat_at is not None and self._tempo_missing(state) else due)
    def _tempo_waits(self,now):
        """Must the silence timer wait, whatever it says? While a job judges a final (rule 5: whatever the ear made of that speech, or if it heard no text at all), but for a start said after that final. For
        the text of the utterance that has just ended, and through a hold. An utterance whose text never came: nobody knows what was said, it may be a repeat on its way to the cloud: rule 2 from its end.
        A hold ends by itself TEMPO_HOLD_SECONDS after its speech: a lost final must not silence the call."""
        if self.candidate and 'job' in self.candidate and not self._tempo_back_at_it() and (self.candidate.get('said') or self.job_begun() or now<self.candidate['taken']+FIRST_TEXT_S or self._candidate_asks(self.candidate)):return True      # a job with no word holds the timer FIRST_TEXT_S at most (the one road lets it live to the give-up: the listener's silence is not left waiting for it), but never over a question: the old portion is not said again over it (W14)
        if self._tempo_unheard(now) and not self._tempo_missing(self.state()):return True     # H6 (R10): speech nobody has judged, wherever the cursor stood when it began
        if self.tempo_awaits is not None:
            if now<self.tempo_ended+TEMPO_TEXT_SECONDS:return True
            self.tempo_awaits=None
            self._tempo_arm(self.tempo_ended+self._repeat_wait())
        hold=self.tempo_hold
        if hold is not None:
            if hold[0]==self._position(self.state()):
                if now<hold[1]+self._hold_s(hold):return True
                if hold[2:]==('question',):      # w10 R10.1 (rehearsal Р041): the hold of a NEW question whose final was lost: saying the old portion again is an old answer; the listener's next words decide
                    logger.info('echo-sync decision kind=silent reason=ear_question_hold_no_replay revision=%s',(self.state() or {}).get('revision'))
                    self.tempo_hold=None;self.repeat_at=None;return True
                self._tempo_arm(now)
            self.tempo_hold=None
        return self.tempo_ended is not None and now<self.tempo_ended+TEMPO_FILLER_SECONDS and not self._tempo_missing(self.state())     # H5 item 1: a comma, not an end. A start that stopped has its own time
    @staticmethod
    def _hold_s(hold):
        """u18: how long a ``tempo_hold`` lasts: the owner talking by themselves (``MONOLOGUE_OTHERS`` utterances of other speech in a row) is waited out, a single remark is not."""
        if hold[2:]==('question',):return min(TEMPO_HOLD_SECONDS,ANSWER_WAIT_SECONDS-REFUSE_BEFORE_DROP_SECONDS)      # round 3: the owner's 8 s: a question the ear heard is decided by then (cue or the phrase), its hold ends a tick before the bound
        return MONOLOGUE_QUIET_SECONDS if hold[2:]==('monologue',) else TEMPO_HOLD_SECONDS
    def _tempo_missing(self,state):
        """Rule 3: ``(what is missing, False)`` of the start the ear heard, while it is inside the joining window of a try, else None."""
        start=self.tempo_start
        if not self.tempo_live or not start or start[0]!=self._position(state):return None
        if not 0<=self.clock()-start[2]<=self.ack_join_seconds and not self._rule_on():return None      # h26, the owner's rule: the place where they stopped holds while they are on this portion, however long the silence (the call of 12:59: heard at 24,9 s, the repeat at 34 s went from the top)
        return start[1],False
    @staticmethod
    def _words_in(final,text):
        """c24-a1: are the words of ``text`` said in a row in ``final``: «два» of «двадцать плюс двадцать» | «два» is in «Двадцать плюс двадцать два», though not by value (q1 ``…goes_on_after_a_breath``)."""
        said=' '.join(norm_words(text));whole=' '.join(norm_words(final))
        return bool(said) and f' {said} ' in f' {whole} '
    def _fast_verdict(self,turn):
        """Rule 3. A sentence of substance is the admission: at once, or when the listener has stopped (speech meanwhile is a final of its own, and that replaces the candidate). A
        job that is over with none declined: the candidate is gone, nothing was touched."""
        candidate=self.candidate;over=candidate.get('over');answer=brain_answer(candidate['said'])
        if not candidate.get('held') and (self._said_back(candidate['text']) or self._talk_no_question(candidate['text'],answer)):answer=''       # h31: what the doubt holds is judged once, no second round; a job the ear prepared on it: the same as ``_fast_ask``
        command=brain_command(candidate['said']) if over else None
        if command and self._asks_for_detail(command,candidate['text']):command=None
        if command:
            self.candidate=None;self.fast_passed=candidate['id']
            return False,self._fast_command(candidate['id'],command)
        if answer and self._of_substance(answer,candidate['text'],over,brain=True)[1]:
            if self._says_again(answer,candidate['text']) or self._said_already(answer,candidate['text']):return self._fast_said_again(candidate)
            if self._utterance_over(candidate['text']):return self._fast_admit(turn,answer)
            candidate['verdict']=True
            return True,[]
        if not over:return True,[]
        held=self._doubt_held(candidate['text'],self.fast_in_play())
        if held:
            candidate['said']=held;candidate['held']=True
            return self._fast_verdict(turn)
        self.candidate=None;self.fast_passed=candidate['id'];self.fast_head=(candidate['text'],candidate['taken']);self._keep_unanswered(candidate['text'])
        logger.info('echo-sync decision kind=silent reason=fast_text_declined revision=%s',(self.state() or {}).get('revision'))
        self._tempo_declined()
        stood=self.ear_stood_open
        if stood and stood['tid']==candidate['id']:      # c23 P09: what was declined is the ear's text of a turn whose final is still to come: the portion is not said again before it
            stood['declined']=True
            if self.repeat_at is not None:self._tempo_arm(max(self.repeat_at,stood['at']+TEMPO_HOLD_SECONDS))
        return False,self._fast_no_search(candidate['id'])
