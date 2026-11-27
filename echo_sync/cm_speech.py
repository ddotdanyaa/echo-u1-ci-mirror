"""The speech methods of ``ControlledMedia`` (cut from controlled_media.py by tools/split_controlled_media.py). Imports from cm_base, never from controlled_media."""
from .cm_base import (INPUT_CLOCK_SLACK_MS, Pace, abbrev_found, asks_expansion, expand_abbreviations, logger, reason_of, resolve)


class SpeechMixin:
    def _end_of(self,last):
        """E76: ``{'end':'fall'}`` for the cue of the LAST portion of an answer (its stream is closed and this is its final portion), when the profile has
        ``end_intonation`` on; ``{}`` for every other cue, so a middle portion is spoken exactly as before."""
        return {'end':'fall'} if last and (self.settings or {}).get('end_intonation')=='fall' else {}
    def cue_started(self,cue,*,voiced_seconds=None):
        """The transport has just sent the first PCM frame of ``cue``: it is in flight from now until its voice ends (``voiced_seconds``,
        or what the portion takes to say) and the margin after it, and it can be heard back from now on. The window is kept on the
        controller's own clock, the one the listener's speech is stamped with, and the input audio is noted where it stands."""
        if not self.authorized(cue):return
        self._cue_event('began',cue,**({'voiced':voiced_seconds} if isinstance(voiced_seconds,(int,float)) and voiced_seconds>0 else {}))
        spoken=voiced_seconds if isinstance(voiced_seconds,(int,float)) and voiced_seconds>=0 else self._spoken_estimate()
        now=self.clock();self.cue_window=[now,now+spoken+self.cue_tail_seconds]
        self.cue_heard=True;self.cue_input_ms=self.input_ms()
        self.first_hold_from=None      # a hold of a first cue ends when a cue plays (``_first_held``)
        if cue.get('index')==0 and not cue.get('replay_last') and self.audible_of!=cue.get('revision'):self.audible_of=cue.get('revision');self.audible_ms=self._audible(now)    # T11 (E52)
        if self.portion_heard is None or self.portion_heard[0]!=(cue.get('revision'),cue.get('index')):self.portion_heard=((cue.get('revision'),cue.get('index')),self.input_ms())   # A1-F6
        tail=self.engine.tail_of(self.state())
        if tail and tail[1]==cue.get('text'):self._cue_tail(tail[0],tail[1],True)
        where=(cue.get('revision'),cue.get('index'))
        if not cue.get('replay_last') and (self.abandon is None or self.abandon['at']!=where):
            self.abandon={'at':where,'since':now,'engaged':None,'capped':None,'others':0}
    def act_told(self,action):
        """night-gate: ``(act, reason, site)`` of the gate's entry that built this very ``action`` for the transport (its cut), or None: the transport's journal line says why it cut
        (the gate keeps the last eight)."""
        return next((row[1:] for row in self.__dict__.get('_act_wires',()) if row[0] is action),None)
    @staticmethod
    def _cue_key(cue):return (cue.get('revision'),cue.get('index'),bool(cue.get('replay_last')))
    def subscribe_cue(self,listener):
        """X-CUE: ``listener(kind, cue, at, num)`` hears every cue event (kind: began|done|cut|abandoned) once; a failing listener costs nothing."""
        self._cue_subs.append(listener)
    def _cue_event(self,kind,cue,at=None,**num):
        """X-CUE, the one source of a cue's life: ``began`` opens it, the first of ``done``/``cut``/``abandoned`` closes it, the later ones
        for the same cue are dropped (first end wins). ``at`` is on ``time.monotonic``, the clock of the transport and (by default) of
        this controller. True when the event was passed on."""
        key=self._cue_key(cue);open_=self._cue_open
        if kind=='began':
            if open_ and open_[0]==key:return False        # the same cue sent again after a failed write: it has begun once
            if open_:self._cue_event('cut',open_[1],at,why='replaced')   # a cue that begins while another is open took the audio over
            self._cue_open=(key,cue)
        else:
            if not open_ or open_[0]!=key:return False
            self._cue_open=None
        at=self.clock() if at is None else at
        for listener in tuple(self._cue_subs):
            try:listener(kind,cue,at,num)
            except Exception:logger.debug('echo-sync cue listener failed',exc_info=True)    # noqa: BLE001 - a listener never costs the cue
        return True
    @property
    def input_mode(self):
        return resolve(self.settings).get('input_state','shadow')
    def mic_packet(self,nbytes,dbfs=None,now=None):
        """The transport saw one microphone packet of ``nbytes`` bytes at ``dbfs``."""
        self._input_feed('packet',nbytes,dbfs,now=now)
    def input_vad(self,voiced_ms,now=None):
        """The transport's own ear saw ``voiced_ms`` more of speech."""
        self._input_feed('vad',voiced_ms,now=now)
    def input_fault(self,kind='',now=None):
        """The ear or the cloud reported a fault."""
        self._input_feed('fault',kind,now=now)
    @property
    def lang_mode(self):
        return resolve(self.settings).get('lang_turn','off')
    def _input_cue(self,kind,cue,at,num):
        self._input_feed('cue_begin' if kind=='began' else 'cue_end',now=at)
    def input_counts(self):
        """Flat numbers and labels for the call_close line ({} when the meter never ran)."""
        meter=self.input_probe
        if meter is None:return {}
        try:
            summary=meter.summary(self.clock())
            counts={'input_'+k:v for k,v in summary.items() if k!='states'}
            counts.update({'input_n_'+k:v for k,v in summary['states'].items()})
            return counts
        except Exception:return {}    # noqa: BLE001
    def cue_abandoned(self,cue,*,at=None,opened=False,why=None):
        """X-CUE: the transport gave the cue up after its first frame (superseded, unauthorized, closed, cancelled, a failed write)."""
        return self._cue_event('abandoned',cue,at,opened=bool(opened),why=why)
    def bind_input_clock(self,reader):
        """The transport tells the controller how far the input audio has got: ``reader()`` is the milliseconds of microphone audio it has
        forwarded to the provider since the call began, the provider's own input-audio clock (the ``start_ms`` of the listener's turn)."""
        self._input_clock=reader
    def input_ms(self):
        """The input audio forwarded so far, in ms, or ``None`` when the transport does not count it."""
        try:value=self._input_clock() if self._input_clock else None
        except Exception:return None
        return value if type(value) in (int,float) else None
    def _audible(self,now):
        """T11 (E52): ms from the end of the question's speech to the first PCM frame of its answer, the latency the listener hears: on the provider's input-audio clock when the question's turn carries
        ``end_ms`` on the clock the transport counts, else on the controller's clock from the end of speech the ear heard; None when neither knows. Logged as numbers only."""
        try:snap=self.ledger.snapshot(self.question_id) if self.question_id else None
        except Exception:snap=None      # noqa: BLE001 - a measurement never costs the cue
        end,sent=(snap or {}).get('end_ms'),self.input_ms()
        if type(end) in (int,float) and sent is not None and end<=sent+INPUT_CLOCK_SLACK_MS:value,clock=round(sent-end),'input'
        elif self.tempo_ended is not None and now>=self.tempo_ended:value,clock=round((now-self.tempo_ended)*1000),'ear'
        else:return None
        logger.info('echo-sync audible first_cue_ms=%s clock=%s revision=%s',value,clock,(self.state() or {}).get('revision'))
        return value
    def _answer_watchdog(self,now):
        """DEF-FAULT-03: the cloud took the question and shows no sign of life: nothing it does for the question (an event of an
        assistant turn that is the question's) for ``answer_wait_seconds`` since the final of the question. A question that needs the
        lookup is counted from the REAL delivery of its sources (the last acknowledged frame) and has the budget
        ``lookup_answer_wait_seconds``; while they have not been delivered, from the final plus the lookup budget on top. Every sign of
        life restarts the count (Task E: a cloud that streams is not silent, however long its text takes to become a cue), but
        ``answer_cap_seconds`` after the start a question that has produced no cue is given up whatever the cloud does.
        Then the question is given up the way «стоп» ends one (a new epoch: whatever of it is still in flight is stale, and an answer of
        the cloud that comes late is not the answer to any question, so it is never dictated) and ONE action tells the transport to say
        so. Not while the listener is speaking (they will either ask again or be quiet in a moment) nor while the controller itself
        holds text that did arrive (see below; each of those windows is bounded by its own limit, and the count goes on from where it
        was when they end), but none of those windows outlasts ``answer_cap_seconds`` (Task E2, ruling 4: the idle wait of a continuation
        segment counts from its last event, so a keep-alive less than ``segment_idle_seconds`` apart put the end of the answer off for ever
        and the call stayed silent for good). Counted to the first CUE: text that gives none (a service phrase, the question read back, an
        empty turn) is the same silence as no text.

        g3-chaos (the candidate): a question the ear stood in for, whose job failed or broke and that went back to the cloud's evidence, is counted by THIS timer too, from the same anchor (``decision_due``: the end of its speech, the 8 s less the
        refusal's half second where it had spoken) and the listener's speech after it starts the count again. When none comes, a question by its words is not left in silence: the honest phrase, once; any other words are let go as the cloud
        would have them, with nothing said."""
        candidate=self.candidate
        if candidate and candidate.get('back') is not None and 'job' not in candidate and not candidate.get('ready'):
            if self.hearing:candidate['quiet']=now
            else:
                due=self.decision_due(candidate['id'])
                if due is not None and now>=due:
                    self.candidate=None;self.fast_passed=candidate['id']
                    asked=self._candidate_asks(candidate)
                    if asked:logger.info('echo-sync decision kind=silent reason=candidate_unanswered cause=fast_text_failed waited=%.1f revision=%s',now-self._question_start(candidate['id']),(self.state() or {}).get('revision'))
                    return self._give_up_aloud('candidate_unanswered',asked=asked,let_go='candidate_let_go cause=no_evidence')
        qid=self.question_id
        if not self.answer_wait_seconds or not qid or self.fast_mark:return []      # H6 item 5: the job has ruled: a command waits for silence, bounded (FAST_MARK_SECONDS)
        if self.published:return self._stalled_stream(now)
        if self.diagnosed_epoch==self.epoch:return []
        question=self.ledger.snapshot(qid)
        if not question or not question['valid'] or not question['final']:return []   # still being spoken: the cloud has not got it all yet
        start,since,due,cap_at=self._silence_due(qid)
        capped=cap_at is not None and now>=cap_at
        # The controller's own windows for text that DID arrive (each with its own bound) are not the cloud's silence: the hold for a
        # continuation of the question, the grace window of an answer that may be cut, and a continuation segment waiting to go idle.
        # The absolute cap is checked first: no window of the controller's own may keep a question that has produced no cue unanswered.
        if not capped and (self.held_source is not None or self.unsettled is not None or self._idle_candidate() is not None
                           or self.pending_restart is not None):return []
        if (now<due and not capped) or self.hearing:return []
        reason='no_usable_text' if any(owner==qid for owner in self.owners.values()) else 'no_assistant_turn'
        if reason=='no_usable_text':
            rescued=self._rescue_first_cue(qid)
            if rescued:return rescued
        logger.info('echo-sync decision kind=silent reason=answer_timeout cause=%s waited=%.1f since_start=%.1f',reason,now-since,now-start)
        epoch=self.epoch;declined=self._declined(qid);failed=self.fast_handed==qid
        if self.refusal_pending is not None and self.refusal_pending():logger.info('echo-sync drop_before_refusal reason=%s waited=%.1f since_start=%.1f',reason,now-since,now-start)      # U20-S6: monitor, every mode: the question is dropped while the fast channel's refusal has not been said
        cut=self._drop_question()
        if (declined or reason=='no_assistant_turn') and not failed:      # w10 R10.2 (rehearsal Р051): a question whose job FAILED is no talk: the honest phrase, the older plan stays in the history
            # G3, rules 4-5: the cloud took this for nothing to answer: a plan that waited goes on, and nothing is said aloud of a backchannel. A cloud that
            # promised an answer and gave none is told about as before, and the plan stays where the listener's words can take it back.
            back=self._resume_after_nothing(cut)
            if back or (back is not None and not self.fast_call):return back      # H6 item 5: a stopped plan comes back with nothing said: the listener is still told
            if declined:
                logger.info('echo-sync decision kind=silent reason=cloud_declined revision=%s',(self.state() or {}).get('revision'))
                return []
        # c8: the lookup gave no source and the model, told to answer from memory, gave nothing either: the lookup's «Не нашёл».
        return self._give_up_aloud(reason,epoch=epoch,missing=self.source_missing)
    def _give_up_aloud(self,reason,*,epoch=None,missing=False,asked=True,let_go=None):
        """The ONE place that decides whether a question given up is told aloud («Нет ответа. Повторите вопрос.» / «Не нашёл») or let go in silence (giveup-phrase): the watchdog, a fallback of the cloud's text that is refused, a candidate handed back and a candidate whose time ran out all end here. ``asked`` False (the words are no question) lets it go with ``let_go`` logged; ``missing`` (the lookup gave no source) adds the code of «Не нашёл». ``epoch`` is the epoch the question was given up in (the caller may have already moved it)."""
        if not asked:
            if let_go:logger.info('echo-sync decision kind=silent reason=%s revision=%s',let_go,(self.state() or {}).get('revision'))
            return []
        return [{'type':'unanswered','epoch':self.epoch if epoch is None else epoch,'reason':reason,**({'code':'controlled_sources_unavailable'} if missing else {})}]
    def _abbreviations(self,text):
        """``expand_abbreviations`` of the profile's table; a term is spelled out once PER CALL (N136, always, abbrev_state.py): in the answers of the questions after the one that introduced it the short form stays, until the listener asks what it
        means. Stateless inside one answer (a stream is expanded again at every tick and must not change under what is planned): what the earlier answers introduced is ``abbrev_known``, this answer's own is ``abbrev_now``."""
        table=resolve(self.settings)['abbreviations']
        if not table:return expand_abbreviations(text,table)
        if self.abbrev_qid!=self.question_id:self.abbrev_known|=self.abbrev_now;self.abbrev_now=set();self.abbrev_qid=self.question_id
        ask=self.question_text or ''
        out=expand_abbreviations(text,{key:value for key,value in table.items() if key not in self.abbrev_known or asks_expansion(ask,key)})
        self.abbrev_now|={key for key in table if abbrev_found(key,text)}
        return out
    def ear_failed(self,error):
        """The transport's own last line (``NativeMediaSocket._ear_acts``) turns the ear off through the same switch: once, logged by type."""
        if not self.ear_off:self._ear_fail(error)
    def _ear_fail(self,error):
        """The ear stops acting: nothing of it waits or stays taken. A take that broke before anything of it was applied (the call stands
        where it stood) gives the cloud its turn back, so that the cloud's final confirms as without the ear."""
        taking,self._ear_taking=self._ear_taking,None
        self.ear_off=True;self.ear_pending=None;self.ear_take=None;self.ear_first=None
        if taking is not None:
            try:untouched=self._ear_mark()==taking[1]
            except Exception:untouched=False
            if untouched:
                tid=taking[0];self.seen.discard(tid);self.early_taken.pop(tid,None);self.user_boundaries.pop(tid,None)
        logger.warning('echo-sync ear act=off reason=%s',reason_of(error))
    def _ear_floor(self,tid):
        """When the listener's last final of another turn than ``tid`` came: what the ear heard after that may be in ``tid``."""
        return max((when for key,when in self.user_done_at.items() if key!=tid),default=None)
    def _tempo_safely(self,work,*args,default=None):
        """A fault here switches the mode off for the rest of the call, logged by type: the cloud keeps the flag and the timer as without it."""
        try:return work(*args)
        except Exception as error:
            logger.warning('echo-sync ear tempo=off reason=%s',reason_of(error))
            self._tempo_off()
            return default
    def _recording(self):
        """u18-s3: has the owner gone on from ``record_engage_k`` places of this answer: they are writing, the pen is what the silence waits for."""
        seen=self.record_seen;state=self.state() or {}
        return bool(seen and seen[0]==state.get('revision') and len(seen[1])>=resolve(self.settings)['record_engage_k'])
    @property
    def dictation(self):
        """c22-repeat: is the owner dictating: said by voice («диктуй медленно» / «хватит диктовать»), else the profile's ``dictation`` (``CallDictation``)."""
        return self.dictating.on(getattr(self,'settings',None))
    def pace_on(self):
        """W5 (``prompt_pace`` = "on", ``ear_shadow.for_call``): the wait of a start that stopped is this listener's, from the end of their last word (``echo_sync.pace``). What is said stays rule 3's."""
        self.pace=Pace(cap=self.repeat_seconds)
    def fast_job_lost(self):
        """A fault over one job: what it was asked goes back to the cloud as in ``fast_lost``, the channel stays for the next question."""
        try:return self.fast_lost()
        finally:self.fast_on=True;self.fast_retried=None
