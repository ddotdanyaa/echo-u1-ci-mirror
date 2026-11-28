"""The speech methods of ``ControlledMedia`` (cut from controlled_media.py by tools/split_controlled_media.py). Imports from cm_base, never from controlled_media."""
from .timer_policy import DIAGNOSTIC_MIN_INTERVAL_S
from .cm_base import (ANSWER_WAIT_SECONDS, FIRST_HOLD_CAP_SECONDS, FIRST_HOLD_SECONDS, HOLD_BOUNDS, INPUT_CLOCK_SLACK_MS, ONSET_HOLD_MAX_S, Pace, TEMPO_HOLD_SECONDS, TEMPO_TEXT_SECONDS, logger, reason_of, resolve, why_journal)


# cm-speech: the failure class of an error code (what the phone's ``error`` frame carries); every code not listed is class 'other'. A class is the key of ``diagnostics.PHRASES`` the listener hears, except 'lookup': see ``diagnostic_line``.
CLASS_OF_CODE = {
    'controlled_sources_unavailable': 'lookup',
    'controlled_synthesis_failed': 'synthesis',
    'controlled_upstream_unavailable': 'channel',
    'controlled_upstream_closed': 'channel',
    'controlled_upstream_stalled': 'channel',      # the helper is open, the cloud has gone deaf (timer_policy.CLOUD_DEAF_S)
    'controlled_answer_timeout': 'answer',
}
# The missing-answer phrase is limited to ONCE PER QUESTION already (the controller gives the question up with a new epoch): a second limit would leave the listener who was just told to ask again with nothing (Task E, ruling 4).
RATE_LIMIT_EXEMPT = frozenset({'controlled_answer_timeout'})


def failure_class(code):
    return CLASS_OF_CODE.get(code, 'other')


def v5_hold(gate,cue,rule,now,ask):
    """V5 slice (``v5_answer_gate``): the gate is told every hold of a ready cue (by which rule). True: it stays held, as today. Only on, a hold by speech not known to be the owner's ends at its cap (v5_gate.COSTS): False from then on, and the parked cue is looked at again at that moment (the moment goes to ``ask``)."""
    if gate is None:return True
    until=gate.held(cue,rule,now)
    if until is None:return True
    if now>=until:return not gate.ceiling(cue,now)      # the ceiling lets a cue go over a voice known to be somebody else's only, never over speech nobody knows
    ask.append(until);return True


class SpeechMixin:
    ear_hold_cue=None;ear_held_for=0.0;ear_held_since=None;ear_held_spent=False      # wire-hold: how long the ear ALONE has held the ready cue ``ear_hold_cue`` (ONSET_HOLD_MAX_S), counted across its stretches
    def first_cue_hold(self):
        """THE hold of the first cue of an answer (H5 item 2, n1_01 step 16: the job's answer to the question before was cued 6 s before the end of the next one; U57; the rule of cm-speech, one place with its release): None when the
    cue may start; else ``(rule, opens)``: the rule that holds it (a row of ``timer_policy.HOLD_CONSTS``) and the moment the silence lets it go (None: not known, the tick looks; H7 item 6, Б4, ``prepare_wide``: the transport arms its
    release at it). While the ear hears speech, whatever ONSET_HOLD_MAX_S gives another cue, and until that speech has been judged: its text, its final, the job on it. A new question takes the cue with it. A lost text or final have their
    bounds, and speech that goes on for ever the cap of a question with no cue (R2.5: no hold without a bound). W5 instant: the answer of a bank hit that stands (not cut by new words, ``Instant.cut``) is released before the end of speech, so the speech going on holds nothing."""
        hold=None
        try:
            now=self.clock()
            if self.tempo_live and not (self.answer_cap_seconds and self.question_clock is not None and now-self.question_clock>=self.answer_cap_seconds):
                if self.first_hold_from is None:self.first_hold_from=now
                if now-self.first_hold_from>=FIRST_HOLD_CAP_SECONDS:     # w3-integ (w2-own-voice): no hold without a bound, also where the question's own cap is not set
                    if self.first_hold_from>-1:logger.info('echo-sync decision kind=silent reason=first_hold_capped after_s=%.1f',now-self.first_hold_from);self.first_hold_from=-1e9
                else:
                    handed=self.handed_asks;job=bool(self.candidate and 'job' in self.candidate);awaits=self.tempo_awaits is not None and now<self.tempo_ended+TEMPO_TEXT_SECONDS
                    if awaits and self.cloud_up:hold=('ear_text_awaited','TEMPO_TEXT_SECONDS')
                    elif job:hold=('job_pending','')
                    elif handed is not None and self.cloud_up and now-handed[0]<ANSWER_WAIT_SECONDS and (self.state() or {}).get('revision')==handed[1]:hold=('handed_back_to_cloud','ANSWER_WAIT_SECONDS')      # c24-a1 (fuzz seed 143): a question handed back to the cloud, whatever candidate came after it, until an answer of its own or ANSWER_WAIT_SECONDS
                    elif self.cloud_up and self.candidate and self.fast_handed==self.candidate.get('id') and self._candidate_asks(self.candidate):hold=('job_failed_question_to_cloud','answer_cap_seconds')      # A1-F2: a question whose job failed goes to the cloud; the older answer does not slip through meanwhile (bounded: answer_cap_seconds above)
                    elif (self.speech_open(now) and not (self.instant is not None and self.instant.hit is not None and not self.instant.cut and self.instant.hit.answer==self.published)) if self.local_answer else not self._utterance_over(self.question_text):
                        if self.first_since is None:self.first_since=now
                        if now<max(self.first_since,self.tempo_content or 0.0,self.cloud_heard or 0.0)+FIRST_HOLD_SECONDS:hold=('speech_with_content','FIRST_HOLD_SECONDS')      # H6 item 6: speech with content holds it, a stuck detector and a noisy room do not
            if hold:
                why_journal.held(self,'first_cue',hold[0],hold[1],self.question_id)      # V5 step 0 (b): the line says which rule held; the decision is the same
                opens=self.tempo_ended+self._release_wait(self.question_text) if self.prepare_wide and self.tempo_ended is not None and not job and not awaits and not self.speech_open(now) else None      # H7 item 6: nothing but the silence of ``_utterance_over`` holds it
                hold=(hold[0],opens)
        except Exception as error:
            logger.warning('echo-sync ear tempo=off reason=%s',reason_of(error));self._tempo_off();hold=None
        self._hold_row(bool(hold))
        return hold
    def speech_open(self,now):
        """Is speech going on, or has speech with content ended that nobody has judged yet?"""
        return self.tempo_speaking or self._tempo_unheard(now)
    def _tempo_unheard(self,now):
        """Has speech with content ended that no final has said yet? Bounded: a lost final must not silence the call."""
        if self.tempo_contradicted is not None and now<self.tempo_contradicted+TEMPO_HOLD_SECONDS:return True      # c24-a1: the ear's text the cloud's open turn contradicted waits for that final, within the same bound
        self._ear_jobs_declined()
        return bool(self.tempo_unjudged) and now<self.tempo_unjudged[-1][0]+TEMPO_HOLD_SECONDS
    def hold(self,cue,v5=None):
        """wire-hold, the ONE place that says whether a ready ``cue`` waits (the transport only waits for the verdict and looks again at the moment it names): ``(held, look_again_at)``.
        Held while, in this order: the speaker gate does not release it; a first cue the controller holds (``first_cue_hold``); the cloud hears the listener (HEARING_SECONDS); the transport's own ear alone hears them, ONSET_HOLD_MAX_S in all for this cue (S0 fix round 1; counted across every stretch in which the ear alone held it); the V5 gate parks a first portion; the question the cue answers has no final yet (H4: an ear-opened one needs none). ``v5``: the answer gate or None."""
        now=self.clock();ask=[];held=self._held_by_speech(cue,v5,now,ask)
        if not held:
            until=v5.parks(cue,now) if v5 is not None else None
            if until is not None:ask.append(until);held=True
        if not held:
            tid=self.question_id;user=self.ledger.snapshot(tid) if tid else None
            held=bool(tid) and not bool(user and user['valid'] and (user['final'] or self.user_boundaries.get(tid)=='ear_first'))      # H4: the ear opened this question: its answer does not wait for the cloud's final, which only says whether the ear heard right
            if held:      # E43: no hold without a bound: a final that never comes (a turn the cloud keeps open, one it never announced) holds the cue to the bound of the whole chain, counted from the end of the question's speech, then it plays
                end=self._question_start(tid)+HOLD_BOUNDS['no_final'][0]
                if self.clock()<end:ask.append(end)
                else:held=False
        return held,(min(ask) if ask else None)
    def _held_by_speech(self,cue,v5,now,ask):
        """The speech of the listener against a ready cue (see ``hold``): True while it holds the cue back; a moment at which the hold may end goes to ``ask``. A first cue has no share of the ear: the controller says. W5 instant: the first cue of a bank hit that stands is not held by the speech going on."""
        gate=getattr(self,'speaker_gate',None)      # w2-own-voice: somebody else's speech holds a cue for a bounded time only (own_voice.SpeakerGate)
        if gate is not None and gate.releases(cue):return False
        why=lambda rule,const:why_journal.why(self,'hold','cue',rule,const,id(cue) if cue is not None else '',by='hold',first=int(bool(cue and cue.get('first'))))      # journal only (``facts_why``): one line per change of rule
        first=self.first_cue_hold() if cue and cue.get('first') else None
        if first:
            if first[1] is not None:ask.append(first[1])      # H7 item 6: at its time, not on the tick after it
            why('first_cue_held_by_controller','FIRST_HOLD_SECONDS')
            return v5_hold(v5,cue,self.__dict__.get('v5_held_rule') or 'first_cue_held_by_controller',now,ask)
        if cue and cue.get('first') and self.tempo_live and self.local_answer and self.instant is not None and self.instant.hit is not None and not self.instant.cut and self.instant.hit.answer==self.published:return False
        hearing=self.hearing;local=bool(hearing and self._heard_locally)
        if cue is not self.ear_hold_cue:self.ear_hold_cue,self.ear_held_for,self.ear_held_since,self.ear_held_spent=cue,0.0,None,False
        if not local:
            if self.ear_held_since is not None:self.ear_held_for+=now-self.ear_held_since;self.ear_held_since=None
            if hearing:why('cloud_hears_listener','HEARING_SECONDS')
            return hearing and v5_hold(v5,cue,'cloud_hears_listener',now,ask)
        if self.ear_held_since is None:self.ear_held_since=now
        left=ONSET_HOLD_MAX_S-self.ear_held_for-(now-self.ear_held_since)
        if left>1e-6:
            ask.append(now+left);why('local_ear_onset','ONSET_HOLD_MAX_S')
            return v5_hold(v5,cue,'local_ear_onset',now,ask)
        if not self.ear_held_spent:
            self.ear_held_spent=True
            logger.info('echo-sync local speech onset hold spent held_ms=%d',round((ONSET_HOLD_MAX_S-left)*1000))
        return False
    def _end_of(self,last):
        """E76: ``{'end':'fall'}`` for the cue of the LAST portion of an answer (its stream is closed and this is its final portion): the voice falls where the answer
        ends, always (a rule of speech, no key); ``{}`` for every other cue, so a middle portion is spoken exactly as before."""
        return {'end':'fall'} if last else {}
    def diagnostic_line(self,code,epoch=None,model_answer=None,now=None):
        """The ONE decision of a spoken diagnostic (cm-speech: the service phrase is a line of the controller, the wire only renders and plays it): ``(key, why)``.
        ``key`` is the key of ``diagnostics.PHRASES`` to say, or None with ``why`` ``rate_limited`` (at most one phrase per
        DIAGNOSTIC_MIN_INTERVAL_S, measured from the start of the last one, ``diagnostic_began``; the missing-answer phrase is exempt: RATE_LIMIT_EXEMPT). ``model_answer``: whether a model-knowledge
        answer goes on (None: this question's route says, ``direct_content``). ``now``: the clock of the transport that plays it (default: this controller's)."""
        now=self.clock() if now is None else now
        if code not in RATE_LIMIT_EXEMPT and self.diagnostic_at is not None and now-self.diagnostic_at<DIAGNOSTIC_MIN_INTERVAL_S:return None,'rate_limited'
        kind=failure_class(code)
        if kind!='lookup':return kind,None
        return ('lookup_degraded' if (bool(self.direct_content) if model_answer is None else model_answer) else 'lookup_empty'),None      # a lookup failure says «search did not answer» only when a model-knowledge answer goes on; else the listener is asked to repeat
    def diagnostic_began(self,now=None):
        """The transport has begun to say a diagnostic: the rate limit counts from here."""
        self.diagnostic_at=self.clock() if now is None else now
    def cue_started(self,cue,*,voiced_seconds=None):
        """The transport has just sent the first PCM frame of ``cue``: it is in flight from now until its voice ends (``voiced_seconds``,
        or what the portion takes to say) and the margin after it, and it can be heard back from now on. The window is kept on the
        controller's own clock, the one the listener's speech is stamped with, and the input audio is noted where it stands."""
        if not self.authorized(cue):return
        self._cue_event('began',cue,**({'voiced':voiced_seconds} if isinstance(voiced_seconds,(int,float)) and voiced_seconds>0 else {}))
        spoken=voiced_seconds if isinstance(voiced_seconds,(int,float)) and voiced_seconds>=0 else self._spoken_estimate()
        now=self.clock();self.cue_window=[now,now+spoken+self.cue_tail_seconds]
        self.cue_heard=True;self.cue_input_ms=self.input_ms()
        self.first_hold_from=None      # a hold of a first cue ends when a cue plays (``first_cue_hold``)
        if cue.get('index')==0 and not cue.get('replay_last') and self.audible_of!=cue.get('revision'):self.audible_of=cue.get('revision');self.audible_ms=self._audible(now)    # T11 (E52)
        if self.portion_heard is None or self.portion_heard[0]!=(cue.get('revision'),cue.get('index')):self.portion_heard=((cue.get('revision'),cue.get('index')),self.input_ms())   # A1-F6
        tail=self.engine.tail_of(self.state())
        if tail and tail[1]==cue.get('text'):self._cue_tail(tail[0],tail[1],True)
        where=(cue.get('revision'),cue.get('index'))
        if not cue.get('replay_last'):self._abandon_mark(where,now)
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
    def mic_packet(self,nbytes,dbfs=None,now=None):
        """The transport saw one microphone packet of ``nbytes`` bytes at ``dbfs``."""
        self._input_feed('packet',nbytes,dbfs,now=now)
    def input_vad(self,voiced_ms,now=None):
        """The transport's own ear saw ``voiced_ms`` more of speech."""
        self._input_feed('vad',voiced_ms,now=now)
    def input_fault(self,kind='',now=None):
        """The ear or the cloud reported a fault."""
        self._input_feed('fault',kind,now=now)
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
        if self._answered():return self._stalled_stream(now)
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
        """c22-repeat: is the owner dictating: said by voice («диктуй медленно» / «хватит диктовать»; ``CallDictation``)."""
        return self.dictating.on()
    def pace_on(self):
        """W5 (``prompt_pace`` = "on", ``ear_shadow.for_call``): the wait of a start that stopped is this listener's, from the end of their last word (``echo_sync.pace``). What is said stays rule 3's."""
        self.pace=Pace(cap=self.repeat_seconds)
    def fast_job_lost(self):
        """A fault over one job: what it was asked goes back to the cloud as in ``fast_lost``, the channel stays for the next question."""
        try:return self.fast_lost()
        finally:self.fast_on=True;self.fast_retried=None
