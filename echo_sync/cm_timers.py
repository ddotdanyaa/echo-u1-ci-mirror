"""The timers methods of ``ControlledMedia`` (cut from controlled_media.py by tools/split_controlled_media.py). Imports from cm_base, never from controlled_media."""
from . import timer_policy
from .cm_base import (CALL_QUESTIONS, CONVERSATION_GAP_S, NO_ANOTHER, Stamped, CONTEXT_AGE_S, WRONG_REPEAT_SECONDS,
    UNASKED, call_history, conversation_map, logger, reconnect_note, resolve, state_age)


class TimersMixin:
    hold_cause=None      # U57: (rule, const) of the hold the first cue is under now, while the controller holds it (``first_cue_hold``); None: not held
    late_row=None        # U57: the ``cued_mark`` the late-cue row was written for (one row per cue)
    def _arm(self,at):
        """U94.5 (U40): the ONE writer of ``repeat_at``, the moment the silence timer runs to (None: no timer). The slot is ``Stamped``: the reply token it is armed under is the owner's of that moment, and ``_repeat_gate`` drops
        it when the question moved on. Every other method asks here; the AST count in tests/test_m5_tick.py holds the number of writes elsewhere to what is still to be moved."""
        self.repeat_at=at
    def _deadlines_due(self,now):
        """M5: the deadlines of ``timer_policy.DEADLINES`` that have run out, through the tick: a row is a slot (the moment it was armed), its seconds (a number or a key of the registry) and the method that fires it. The first that returns actions
        wins, as the tick's other owners do; a row that fired is disarmed first, so it fires once. A new deadline is a row in timer_policy, not a line here."""
        for name,row in tuple(timer_policy.DEADLINES.items()):
            armed=getattr(self,row.slot,None)
            if armed is None or now-armed<timer_policy.deadline_seconds(row):continue
            setattr(self,row.slot,None)
            fired=getattr(self,row.fire)(now)
            if fired:
                logger.info('echo-sync decision kind=deadline reason=%s seconds=%s',name,timer_policy.deadline_seconds(row))
                return fired
        return []
    def end_call(self):
        """U91: the line of this call is closed (the transport's ``close``): a final it opened a question for, seen again by a later call, is a reconnect's repeat."""
        self._final_closed()
    def begin_call(self):
        """``_begin_call``; then M1-e2: the start of the conversation the memory counts from (``memory_began``, the engine's clock). ``call_began`` is decided by the age of the last
        portion spoken; the memory goes on with the conversation when the line came back within CONVERSATION_GAP_S (the one window of the same conversation) of the last thing the ledger holds (said, answered, played)."""
        try:return self._begin_call()
        finally:
            if self.convo is not None:self.memory_began=self.convo.conversation(self.call_began,CONVERSATION_GAP_S)
    def timers_snapshot(self):
        """U20-S4: every Stamped slot as ``name -> (value, token it was armed under)``."""
        return {n:(getattr(self,n),d.stamp(self)) for n,d in vars(type(self)).items() if isinstance(d,Stamped)}
    def _cue_playing(self,now):
        """Is a cue still being played, as far as anybody knows? Not after the window it can last in has closed: a cue whose end
        was never reported (a diagnostic took the audio over) must not look like one in flight for ever."""
        return self.cue_outstanding and self.cue_window is not None and now<=self.cue_window[1]
    def _spoken_estimate(self,state=None):
        syllables=(state or self.state() or {}).get('issued_syl')
        return (syllables if isinstance(syllables,(int,float)) else 0)*resolve(self.settings)['sec_per_syllable']
    def _rule_no_to_the_cue(self,c):
        if not c.tail and not c.utterance and self._no_to_the_cue(c.text,self.tempo_began if self.tempo_began is not None else self.clock(),c.state):      # c25-a: the model is asked for another answer to the question in play
            self._no_taken(c.state);c.text=NO_ANOTHER;c.turn={**c.turn,'text':c.text};c.spoke('no_to_the_cue')
    def reconnect_notes(self):
        """Ruling 5b: the transport has just opened the cloud session of a call. When this session's map holds entries newer than
        ``CONVERSATION_GAP_S`` (the newest MAP_ROWS of them; a stale one is never sent: the phone's session id is the same constant every
        day), one quiet note tells the model what was said and what was not. ``[]`` or ``[{'type': 'note', 'kind': 'reconnect', ...}]``."""
        text=reconnect_note(conversation_map(self.state(),now=self.engine.clock()))
        if not text:return []
        self.note_guard=True
        return [{'type':'note','kind':'reconnect','epoch':self.epoch,'text':text}]
    def _tempo_off(self):
        """The ear is gone: nobody will tell the end of what it was hearing, so a portion that waits gets its timer here."""
        self.tempo_live=False;self.tempo_speaking=False;self.tempo_awaits=None;self.tempo_hold=None
        if self.repeat_at is None:self._tempo_arm(self.clock()+self.repeat_seconds)
    @property
    def auto_repeats(self):
        return self._auto_repeats
    @auto_repeats.setter
    def auto_repeats(self,value):
        """x-cap: the count of silent repeats of the portion. Zero is the owner being heard: it zeroes the unconfirmed count and the unplaced flag with it; a new portion zeroes only its own (``_auto_repeats``)."""
        self._auto_repeats=value
        if not value:self.unconfirmed_repeats=0;self.unplaced=False
    def _record_tools(self):
        """u18-s4: do the tools of writing (the pen's wait, the pause, ``written_to``, the learning of the owner's tempo) run: only in the record state (the owner is seen writing; the rule of every call)."""
        return self._recording()
    def _tempo_arm(self,at):
        """The silence timer runs to ``at``, unless a cue is being said (its end arms it) or nothing waits."""
        if not self._cue_playing(self.clock()) and self._position(self.state()) is not None:self._arm(at)
    def _tempo_resume(self,now):
        """The final of a try, on the tick (``resume_repeat``): it ends a hold and never puts a running timer off; a wrong repeat has its second as ever. The wait counts from the end of the speech the
        hold was for, not from a transcript that came seconds after it."""
        hold,self.tempo_hold=self.tempo_hold,None
        ended=hold[1] if hold else self.tempo_ended if self.ear_job and self.tempo_ended is not None else now      # c16: the speech ended where the ear heard it end, with a hold or without (c15-cand-f: «и родам» 3.9 s, the number repeated wrong 3.4 s)
        due=(max(now,ended+WRONG_REPEAT_SECONDS) if self.ear_job else now+WRONG_REPEAT_SECONDS) if self.said_wrong else max(now,ended+self._silence().wait)
        self._tempo_arm(due if self.repeat_at is None else min(self.repeat_at,due))
    def _hold_row(self,held):
        """U57: a first cue that came more than ``LATE_CUE_S`` after the decision (``cued_mark``) writes one decision row naming the hold that kept it and the seconds of that hold (``timer_policy.HOLD_CONSTS``): ``echo-sync decision kind=cue_late
        reason=<rule> const=<NAME> seconds=<its value> lag_s=<since the decision>``. While the controller holds it the rule is remembered; the row is written when the hold ends, once per cue."""
        if held:
            self.hold_cause=(self.__dict__.get('v5_held_rule') or 'first_cue_held',self.clock());return
        mark=self.cued_mark
        if not mark or self.late_row==mark:return
        lag=self.clock()-mark[3]
        if lag<=timer_policy.LATE_CUE_S:return
        self.late_row=mark;rule=(self.hold_cause or ('no_controller_hold',0.0))[0];self.hold_cause=None
        const=timer_policy.HOLD_CONSTS.get(rule)
        seconds=timer_policy.value('controlled_media.'+const) if const else None
        logger.info('echo-sync decision kind=cue_late reason=%s const=%s seconds=%s lag_s=%.1f revision=%s',rule,const or '-',seconds if seconds is not None else '-',lag,mark[0])
    def call_exchanges(self):
        """THE selector of the call's past (memory family): the answered exchanges of this call, as history entries: the engine's ``call_history`` (an earlier call's are no context - the phone's session is one constant, see ``begin_call`` -
        and an exchange the ear opened by mistake never happened) with an answer. The model's context (``fast_exchanges``), the local base and the prepared answers (``call_questions``) read it, each with no window of its own."""
        return [entry for entry in call_history(self.state()) if entry.get('answer')]
    def call_questions(self):
        """The questions of this call, oldest first, the last ``CALL_QUESTIONS`` of them: what a follow-up («а 27-я?») of the local reference base and of the prepared answers takes its code from."""
        return [str(entry.get('question') or '') for entry in self.call_exchanges() if entry.get('question')][-CALL_QUESTIONS:]
    def fast_exchanges(self):
        """The answers of this call so far (``call_exchanges``), then what was said and declined since."""
        answered=self.call_exchanges()
        # ROOT-2 (the call of 09.11 20:51): what was said and declined since the last answer follows them, marked ``unanswered``: a test question read with its options
        # and then «и что выбрать?» is one question in two breaths, and the job of the second one saw nothing of the first
        now=self.engine.clock()
        self.unanswered=[row for row in self.unanswered if row[1]>=len(answered) and now-row[2]<=CONTEXT_AGE_S]
        return answered+[{'question':text,'answer':'','unanswered':True} for text,_,_ in self.unanswered]
