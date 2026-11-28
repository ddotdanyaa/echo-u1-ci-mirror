"""The kind methods of ``ControlledMedia`` (cut from controlled_media.py by tools/split_controlled_media.py). Imports from cm_base, never from controlled_media."""
from .timer_policy import QUIET_INTERVAL_S, HEARING_SECONDS, within
from . import utterance_judge as judge_table      # M1: the table of rows the judge walks
from .portioner import number_goes_on
from .cm_question import CLOSE
from .classifier import IMPERATIVE, _THAT_STANDS_ALONE
from .gate_text import TALK as GATE_TALK, decide as gate_decide, talk_without_flag      # M1: the text gate is a row of the judge
from .cm_base import (gate, ACK, ANSWER_STEMS, ANSWER_WAIT_SECONDS, ANSWER_WORDS, ASKED_AGAIN_FEW_STEMS, ASKED_AGAIN_STEMS, ASK_ANSWER_STEMS,
    ASK_ANSWER_WORDS, AcceptCtx, COMMAND_SAID, CORRECTION, DICTATION_START_SECONDS, Decision, EAR_ANNOUNCE_MAX_SECONDS, EAR_ANNOUNCE_SLACK_SECONDS,
    EAR_BIND_SECONDS, EAR_COMMAND_SETTLE_SECONDS, EAR_FINAL_SECONDS, EAR_FIRST_BIND_SECONDS, EAR_JOIN_GAP_SECONDS, EAR_JOIN_PIECES,
    EAR_PIECE_GRID_MS, EAR_PIECE_SECONDS, EAR_PILE_SECONDS, EAR_RELEASE_SILENCE_SECONDS, EAR_SAID_PIECES, EAR_SPEECH_SECONDS, EAR_START_SLACK_MS,
    EAR_STRONG_FORMS, EAR_TAIL_SILENCE_SECONDS, EAR_TAIL_WORDS, ECHO_MIN_LAG_SECONDS, FAST_HEAD_WORDS, FAST_MARK_SECONDS, FAST_TAIL_SECONDS,
    FIGURE_STILL_SECONDS, FIRST_HOLD_CAP_SECONDS, FIRST_HOLD_SECONDS, FIRST_TEXT_S, FUNCTION_WORDS, GREETING, HESITATION_WORDS, INPUT_CLOCK_SLACK_MS,
    InputMeter, JUDGE_RULES, LANDMARK_SECONDS, LIVE_MIN_WORDS, LONG_TALK_WORDS, MERGE_PATIENCE_SECONDS, MONOLOGUE_OTHERS, MORE_DETAIL, NEXT,
    NO_AFTER_CUE_SECONDS, NUMBER_WORDS, OTHER_LANGUAGE, PACE_HELP_SECONDS, PACE_QUIET_SECONDS, PREPARE_MIN_WORDS, PREPARE_WORDS,
    QUESTION, QUESTION_WORDS, QUIET, READ_USER_WINDOW_S, CONTEXT_AGE_S, RECORD_PAUSE_SECONDS, REFUSAL, REFUSE_BEFORE_DROP_SECONDS,
    REMARK_REASONS, REPEAT, REPEAT_SAID, REPLAY, RESUME, SAID_ALREADY_SHARE, SAID_BACK_SHARE, SILENT, SOURCES_DIFFER,
    SPEECH_LEADS, SPEECH_STARTS, SPEECH_WORDS, SPLIT_JOIN_SECONDS, STAMPED_SLOTS, STOOD_MORE_STEMS, STOP, STOPWORDS, TAIL_HEAD_WORDS,
    TEMPO_ANNOUNCE_SECONDS, TEMPO_BLANK, TEMPO_BLANK_WORDS, TEMPO_FILLER_SECONDS, TEMPO_FRAGMENT_WORDS, TEMPO_HOLD_SECONDS, TEMPO_PAUSE_SECONDS,
    TEMPO_SEEKING, TEMPO_START_SECONDS, TEMPO_TEXT_SECONDS, TEMPO_TWICE_SECONDS, TRY_FINAL_SECONDS, UTTERANCE_FIX_WORDS, UTTERANCE_TAIL_WORDS, WORDS,
    _ABBREVIATIONS, _AFTER_SCALE, _ENDS_SENTENCE, _FIX_ONLY, _FIX_START, _FOR_THE_BRAIN, _HESITATES, _HYPHENS, _INVERTS, _JOINS, _LEAD_PREPOSITION,
    _MAY_ANSWER, _NOT_THIS_BUT, _NO_EVIDENCE, _NO_HEADS, _NO_REAL, _NO_SUBSTANCE, _NO_WORDS, _OPTIONAL_STEMS, _ORDER_SHAPE, _REQUEST_STEMS, _SIGNS,
    _SPOKEN_SENTENCE, _STALLS, ATTEMPT_REASONS, _UNITS, _YES_NO_HEADS, _atoms, _by_value, _chatter, _content, _holds_a_number, _lemma, _like_a_try, ATTEMPT_REASONS,
    _number_grows, _protected, _protected_word, _said_within, _segment_start, _stems, about_itself, adds_nothing, answer_keeps,
    asked_tail, asks_again, asks_in, brain_answer, brain_command, caught_up, command_ruling, destutter, doubtful_what, doubts,
    drop_process_sentences, ear_disputes, ear_foreign, early_command, ends_like, first_match, fold_asr, going_on, hearing_repair, instant,
    is_confirmation_tag, is_followup, is_repeat_request, landmark, landmark_command, lang_counts, logger, match_current, most_said,
    CHANGES, route_need, norm_words, normalize, not_addressed, of_the_answer, pause_split, probe, quick_answer, quick_asked,
    re, reads_out, reads_text, reason_of, recall_parse, recall_resolve, reference_lookup, remark_ruling, resolve, resume_window,
    rule_verdict, said_share, said_within, same_question, same_start, shares, stale_slots, stem, strip_process_prefix,
    stumble_place, tail_progress, talks_about_itself, two_witnesses, whole_portions, why_journal, wide_refusal,
    UNASKED, call_history, unfinished_at, without_repeats, word_problem, written_to)


class KindMixin:
    def speech_started(self,parked_first=False,announced=False):
        """The ONE entrance of «speech began». announced: the cloud tells it after the ear heard it end - no cut (H3). parked_first: a first cue waits for this speech (H5 item 2): nothing to cut; the cloud hears it too, so the ear alone no longer bounds the hold (A1-F1)."""
        if announced and self.tempo_old_news():return []
        if parked_first:
            if self.tempo_live:self.hearing=True
            return []
        if not self.tempo_live:self._arm(None)
        elif self.cue_outstanding:
            self.tempo_cut=self.clock()     # H3: what is being said now cut it: it is no cue heard back (``_tempo_over``)
            if not self.tempo_speaking:self._arm(self.clock()+self._silence().wait)      # the ear hears nobody, and nobody will tell the end of what is cut
        if self.cue_outstanding and getattr(self,'facts_why',False):why_journal.why(self,'drop','cue','listener_speech_started','hearing_seconds',self.epoch,by='speech_started')      # V5 step 0 (b): journal only
        self.hearing=True      # the transport cuts a playing cue off
        return self._act('cut_sound','speech_started')[1]
    def new_user_turn(self,event):
        """Is this provider event the first sight of a user turn (``turn.created`` of an id the ledger has not got)? The same turn delivered again is a retransmission, not speech."""
        raw=event.get('turn',{})
        if event.get('type')!='turn.created' or not isinstance(raw,dict) or raw.get('role')!='user':return False
        tid=raw.get('id')
        return not (isinstance(tid,str) and self.ledger.snapshot(tid) is not None)
    def grew_into_speech(self,turn):
        """The growth of the cloud's transcript of a turn (``turn`` is its ledger snapshot) starts speech only for a turn not yet taken while no flag is up; with the ear holding the tempo (H3) it is no sign of speech."""
        return bool(not turn['final'] and turn['id'] not in self.seen and not self.hearing and not self.tempo_live)
    def _early_tail(self,turn):
        """The words of a turn the stable partial or the ear has already taken (the judge's row ``early_tail``, ``_rule_early_tail``): the one entry is the judge, ``_judge``, run on it as on a final; what it returns is the actions that row took."""
        c=AcceptCtx(turn,'provider_turn_done',False,'',False,False,False,turn['id'],turn['text'],self.state());c.early=True
        return self._judge(c).actions or []
    def _rule_early_tail(self,c):
        """Task E, ruling 3: the FINAL of a turn the stable partial has already taken. What the listener said after the portion in the
        same breath (the partial was only the beginning of the turn) is classified once, as the base would have classified a turn of its
        own, and acted on when it is a stop, a new question, a correction or a request to hear it again; extra plain words stay ignored.
        The turn never advances a second time (an ACK tail is not acted on). A one-word confirmation tag («да?», «правильно?») is such an
        extra word (Task E2, ruling 1); a question or a correction is recorded with the whole utterance (ruling 2); a request to hear it again
        takes the early advance back and replays the portion the listener has just said (ruling 3).

        R-EAR-ACT: the same for a turn the local ear took (``_ear_take``): after a confirmation exactly as above; after a command (a repeat
        request, a stop, «дальше») the tail is what follows the command, and a question, a correction or ANOTHER command in it is acted on
        - the same command never twice (fix round 1, item 5). A later piece of the utterance the ear took (``ear_piece``) is a tail as a
        whole; an earlier one (``'head'``) is the take's own words. Fix round 1, item 1: when the cloud cut the utterance, the tail is found in
        its pieces joined (``_ear_utterance_text``); item 2: a final that does not confirm the portion and says another number, unit or «не»
        takes the ear's confirmation back (``_ear_overruled``). H2 (rule 2, the turn of 69.1 of the call that ended at 105.8): what a final says past the window of a tail is a final of
        its own, on what waits by now (another turn: this one has had its verdict): a repeat of that portion, a question, and for the job what no rule took. H4: the final of a turn the ear opened
        a question on says whether the ear heard right (``_ear_first_final``)."""
        if not c.early:return      # a row of the judge, for a turn the stable partial or the ear has already taken: the actions it takes are its verdict (``_early_tail`` runs the judge on it)
        turn=c.turn
        taken=self.early_taken.pop(turn['id'],None) if turn['final'] else None
        if taken is None:c.actions=[];return
        before,epoch,when,kind,piece,ear=taken
        late=not within(self.clock(),when,self.ack_join_seconds)
        if epoch!=self.epoch or (late and not self.fast_on):c.actions=[];return   # something else has happened since
        if piece=='head':c.actions=[];return
        whole=turn['text']
        if ear is not None and not piece:
            whole=self._ear_safely(self._ear_utterance_text,ear,turn['text'],default=turn['text'])
            if ear.get('first'):c.actions=self._ear_safely(self._ear_first_final,turn,whole,ear['first'],default=[]);return
            if kind==ACK:
                overruled=self._ear_safely(self._ear_overruled,turn,whole,before,ear.get('text'))
                if overruled is not None:c.actions=overruled;return
        tail=whole.strip() if piece else self._tail_after(whole,before,kind)
        if kind==ACK and tail and self._classify(tail,before).kind==ACK:      # W13 item 8 (1_#17, 3_#10): the cloud's text of the repeat the ear took is that repeat, no question
            logger.info('echo-sync decision kind=silent reason=early_ack_same_repeat revision=%s',(self.state() or {}).get('revision'))
            c.actions=[];return
        if kind==ACK and tail and not late and probe('waiting_portion',state=self.state()).value is not None and self._classify(tail,self.state()).kind==ACK \
                and match_current(tail,probe('waiting_portion',state=self.state()).value,resolve(self.settings)['fillers'],lenient=False)=='ack':
            # g7: said ahead of the cue: the tail is the whole next portion, word for word: it is not cued again, the one after it is
            logger.info('echo-sync decision kind=ack reason=early_ack_ahead revision=%s',(self.state() or {}).get('revision'))
            c.actions=self._act('reset_portion','early_ahead',basis=(epoch,(before or {}).get('revision'),turn['id']))[1]+self._accept_user({**turn,'text':tail},boundary='early_tail',tail=True,whole=whole,cause='early_tail');return
        if late:c.actions=self.provider({'type':'turn.done','turn':{'id':f"{turn['id']}:rest",'role':'user','transcript':tail or whole.strip()}});return
        if not tail:c.actions=[];return
        if is_confirmation_tag(norm_words(tail),frozenset(resolve(self.settings)['fillers'])|HESITATION_WORDS):
            # «<portion>, да?» / «правильно?» / «дальше?»: the listener asks whether the repeat was right, or whether to go on. That is the
            # confirmation again, not a question for the cloud: like the plain words below, it is ignored and the plan goes on (Task E2, ruling 1).
            logger.info('echo-sync decision kind=silent reason=early_ack_confirmation_tag revision=%s',(self.state() or {}).get('revision'))
            c.actions=[];return
        waits=self.state()
        decision=self._classify(tail,waits)
        if probe('waiting_portion',state=waits).value is None:
            # The early ACK took the LAST portion: nothing waits any more, and «что?» would read as a new question. A request to hear it again
            # is heard against the portion that waited when the listener spoke.
            earlier=self._classify(tail,before)
            if earlier.kind==REPEAT or earlier.reason=='replay_hearing_repair':decision=earlier
        again=decision.kind==REPEAT or decision.reason=='replay_hearing_repair'
        if kind==ACK and self.fast_on and doubts(tail) and decision.kind==QUIET and self._step_back(before):
            # H6 item 4: the words of doubt came after what looked like a repeat: no confirmation: the step goes back, the next cue with it, and the whole goes to the job
            c.actions=self._act('reset_portion','early_doubt',basis=(epoch,before['revision'],turn['id']))[1]+self._take_candidate({**turn,'text':whole});return
        if kind!=ACK:
            # R-EAR-ACT: after a command the ear took, a question or a correction is never lost, and another command acts («Подожди. …
            # Повтори ещё раз.»: the portion is said again, as the cloud alone does); the same command is not acted on twice.
            family=self._ear_family(decision) or (RESUME if decision.kind==RESUME else None)
            if not (decision.kind in (QUESTION,CORRECTION) or (family is not None and family!=kind)):c.actions=[];return
            logger.info('echo-sync decision kind=%s reason=early_ack_tail revision=%s',decision.kind,(self.state() or {}).get('revision'))
            c.actions=self._accept_user({**turn,'text':tail},boundary='early_tail',tail=True,whole=whole,cause='early_tail');return
        if not again and decision.kind not in (STOP,QUESTION,CORRECTION):
            # G3, rule 2: the tail is judged alone: speech the classifier has nothing on waits for the cloud, as any such final; the plan goes on meanwhile.
            if decision.kind==QUIET and self._effective_reason(tail,waits,decision) in (_FOR_THE_BRAIN if self.fast_on else _NO_EVIDENCE) and (_content(tail) or (self.fast_on and doubts(tail))):
                c.actions=self._take_candidate({**turn,'text':tail});return
            c.actions=[];return
        # Task E2, ruling 3: «<portion> повтори» asks to hear the portion just said, which the base replayed without moving the cursor. The early
        # advance is taken back (and the cue it started is no longer the one the cursor waits for), then the portion is replayed the usual way.
        # When the position is no longer the one the early ACK left, the request belongs to a portion the listener has left: nothing is done.
        if again and not self._step_back(before):c.actions=[];return
        logger.info('echo-sync decision kind=%s reason=early_ack_tail revision=%s',decision.kind,(self.state() or {}).get('revision'))
        c.actions=self._accept_user({**turn,'text':tail},boundary='early_tail',tail=True,whole=whole,cause='early_tail');return
    def _step_back(self,before):
        """The one take-back of an early step (the stable partial's, the ear's, the flow's): the engine's cursor goes back to the place ``before`` (the state the step left) held; False when the call is no longer where that step left it."""
        return self.engine.rewind(session_id=self.session_id,revision=before['revision'],index=before['chunk_index'],waiting=bool(before.get('stream_waiting_next')))
    def _accept_user(self,turn,*,boundary='provider_turn_done',tail=False,whole='',utterance=False,admitted=False,gated=False,cause=None):
        """``cause``: why this final is judged (the name the turn record keeps, X-TURN). ``tail``: the words said after a portion the stable partial had already confirmed (``_early_tail``): the turn is known,
        it is the tail of it that is classified now. ``whole``: the final text of that turn, portion included. The tail decides the KIND
        (stop, question, correction, repeat); a question or a correction is what the listener said as a whole, its subject usually being the
        portion's words (Task E2, ruling 2). ``utterance``: ``turn['text']`` is the question's whole utterance (``_continuation``): the answer
        it replaces was the answer to an unfinished version of the same question, so nothing of it is noted for the model (ruling 5a)."""
        if '-' in str(turn.get('text') or ''):turn['text']=destutter(turn['text'])      # h27
        tid=turn['id']
        if self.prepare_wide and turn['final']:self._wide_break()
        if not turn['final'] and boundary!='provider_delegation':return []
        if tid not in self.seen and turn['final']:self._input_feed('reset')      # U17-S4: the owner's words were taken: a new listening window
        if tid in self.seen and not tail:return self._early_tail(turn)
        ctx=AcceptCtx(turn,boundary,tail,whole,utterance,admitted,gated,tid,turn['text'],None);ctx.cause=cause
        if self._judge(ctx,take=True).taken is not None:return ctx.taken      # the rows of the first stage (``try_final``, ``head_repeat``): the final they take whole is no more than their actions
        turn=ctx.turn
        self.seen.add(tid)
        if not tail:
            self.user_boundaries[tid]=boundary
            # G3: a prepared reply outlives a backchannel of the listener («угу»), which says nothing: its silence starts again
            if self.candidate and self.candidate.get('ready') and not _content(turn['text']):self.candidate['ready']['at']=self.clock()
            elif not (self.candidate and 'job' in self.candidate and not _content(turn['text'])):     # H2: so does a job that judges it
                if self.candidate and 'job' in self.candidate:self.fast_left=(tid,self.candidate['text'],self.candidate['taken'],self.candidate) if not self.candidate.get('alone') else None
                self.candidate=None
        self.hearing=False
        state=self.state();text=turn['text'];self.said_wrong=False
        ctx.turn,ctx.text,ctx.state=turn,text,state
        ctx.analyses=self.reads_ahead.pop(tid,0)      # the readings made ahead of the judge for this final (a delegation) are its readings
        self._judge(ctx)      # U15-S1: the rules that make the verdict of this final, in today's order (``JUDGE_RULES``)
        if ctx.taken is not None:return ctx.taken      # a row took the final whole (the prepared speech opened, the suspended plan taken back)
        turn,text,state,decision,pieces=ctx.turn,ctx.text,ctx.state,ctx.decision,ctx.pieces
        logger.info(ctx.line())
        self._resolve(ctx)
        evidence=ctx.evidence      # the witness of the row ``own_voice`` (a feature of the verdict, never a drop)
        if boundary in ('stable_partial','ear_tail','flow_ahead') and decision.kind==ACK and not tid.startswith(('ear-','flow-')):self._note_early(tid,state)      # the one place a turn taken early by a partial, the ear's tail or the pace is noted for its final (``_early_tail``); a number veto above makes it no ACK: then nothing was taken
        reason=self._effective_reason(text,state,decision)
        if reason!=decision.reason:
            # W1F-B (C4): the sub-reason the silent policy folds into 'mismatch_policy_silent' (the engine logs that one), so the sink is
            # measurable: a try at the portion, a weak question, or speech that is about something else.
            logger.info('echo-sync decision kind=silent reason=%s policy=mismatch_silent revision=%s index=%s',reason,
                        (state or {}).get('revision'),(state or {}).get('chunk_index'))
        if not tail and not utterance and (fate:=self._question_fate('asleep',state,tid=tid,text=turn['text'],decision=decision,reason=reason)).verdict==CLOSE:
            # c8b: the listener has moved on from the portion: it is retired, and this final is judged as when nothing waits
            actions=self._end_question(fate,state)
            self.seen.discard(tid)
            return actions+self._accept_user(turn,boundary=boundary,cause='redo')
        if decision.kind==ACK:self._record_progress(self._position(state))      # u18-s3: the position before the advance
        self._listener_acted(decision,reason,state)      # a repeat, «повтори», a failed try, a question: not silence
        if self.expiry_armed_for==tid:
            self.expiry_armed_for=None
            if decision.kind==GREETING or (decision.kind==QUIET and not self._rearms(decision,reason,turn['text'])):
                self._arm(None);self.resume_repeat=False
        if decision.kind==GREETING or (decision.kind==QUIET and not self._rearms(decision,reason,turn['text'])):
            # W1F-B (C5): not the question, and nothing said to the prompter about the portion: what the cloud says next is its reply to this.
            self.foreign_turns[tid]=True
            while len(self.foreign_turns)>64:self.foreign_turns.pop(next(iter(self.foreign_turns)))
        if not tail and not utterance:self._note_quiet(tid,turn['text'],decision,reason)
        tried=self.heard_since_portion()       # what the listener said of this portion before this final (G3, rule 3)
        self._remember_fragment(turn['text'],decision,state)
        if (decision.kind==QUIET and (evidence is None or self.fast_on) and turn['final'] and boundary in ('provider_turn_done','ear_first') and not tail and not utterance
                and (self._open_to_the_cloud(turn['text'],reason,state) or (reason in ATTEMPT_REASONS and self.fast_on and ((self.fast_left and self.fast_left[0]==tid and self._ear_went_on(self.fast_left[2])) or self._fast_breath(take=False))))):
            admitted=self._take_candidate(turn)
            if admitted:return admitted
        elif (decision.kind==ACK or (decision.kind==QUIET and reason in ATTEMPT_REASONS)) and self.fast_left and self.fast_left[0]==tid:      # H5 skeptic, H6 (R9): a try at the portion or its repeat says nothing of what the job judges (203.7-210.1 of n1_01: «рублей, ну»)
            self.candidate=self.fast_left[3]
            if decision.kind==ACK:self.candidate['alone']=True      # its verdict stands, and it is no head of what comes next
        # H3: the hold waited for this final, and it says what a final said before the ear kept the tempo (W1F-B C4): nothing is said to speech nobody could place. A job has its own say (rule 5).
        if self.tempo_hold and not (self.candidate and 'job' in self.candidate) and (decision.kind==GREETING or (decision.kind==QUIET and not self._rearms(decision,reason,turn['text']))):self.tempo_hold=None
        if decision.reason=='move_on_without_content' and not tail:
            # c7-meta round 2 (w4_04): the examiner moves on («Давайте следующий билет.»): the current answer ends quietly, nothing is cued, and
            # what the cloud says to this turn is its reply to a chat turn (foreign, above). The next topic phrase is the question.
            cut=self._act('close_question','move_on')[1]
            logger.info('echo-sync decision kind=silent reason=move_on_retired revision=%s',(state or {}).get('revision'))
            return cut
        if decision.kind==RESUME and self.suspended and not tail:
            back=self._take_back(turn,state,boundary,resume=True)     # rule 5: «продолжай» over an answer nobody has taken up
            if back or (back is not None and not self.fast_call):return back      # H6 item 5: a stopped plan comes back with nothing said: the listener is still told
        if decision.kind in (RESUME,NEXT) or decision.reason=='topic_change' or (decision.kind==REPEAT and (state or {}).get('abandoned') is not None):
            # CL2, ruling 4 + amendment A: going on is served locally (_going_on); with nothing to go on with, the words are a question.
            decision,actions=self._going_on(turn,decision,state,tail,ctx.going)
            if actions is not None:return actions
        if decision.kind in (QUESTION,CORRECTION):
            left=self.fast_left
            head=left[1] if left and left[0]==tid and (self._ear_went_on(left[2]) or self._follows_on(turn['text'],tail=True)) and not self._reference(turn['text']) else self._fast_breath() if boundary=='provider_turn_done' and not (tail or utterance or self._reference(turn['text'])) else None      # c25-b case 2: a hit of the base said alone takes no head (the chatter of a job that hung glued to it: no bank, no answer)
            if head:      # H5 item 6: the final before it, not ruled on or ruled out, is the head of this breath
                joined=f"{head} {turn['text']}";turn={**turn,'text':joined};decision=decision._replace(question=joined)
            return self._open_question(turn,decision,tail=tail,whole=whole,utterance=utterance,pieces=pieces,local=ctx.local)
        if decision.kind==GREETING:return []
        if ctx.hold=='stop_waits':      # H6 item 5: «подождите» of «подождите, а как считается…»: the cloud gave it a final, the ear hears the rest (the judge's ``held`` row)
            self._fast_mark_waits(tid,'стоп');return []
        if decision.kind==STOP:
            dictated=bool(self.question_id and self.published)
            cut=self._act('pause','stop')[1]
            self._reply(turn['text'],f'{self.nonce}:{tid}'+(':tail' if tail else ''),decided=decision)      # the stop is the judge's verdict; what it pauses is the engine's state of now (no basis)
            after=self.state() or {}
            if dictated and after.get('paused') and not after.get('completed') and type(after.get('revision')) is int:
                # Coordinator ruling (W1F-B, 3 Nov 2026): «стоп» pauses the CURRENT answer and keeps all of it - the text that has arrived,
                # published or not, and the text of the same answer that still arrives stay in the plan, never spoken while paused (the engine
                # issues nothing); the paused stream keeps its post-publication cap (``_stalled_stream``). The answer stays this question's,
                # under the stop's revision; what the cloud says to the stop itself is not the answer (C5). Only a new question discards it.
                self.revision=after['revision']
                self.foreign_turns[tid]=True
            else:self._act('close_question','stop_closes')      # nothing of an answer is kept paused: the question closes
            self._queue_note(unfinished_at((self.state() or {}).get('entry'),(self.state() or {}).get('history'),('active','paused')))     # CL2, ruling 5a: the listener paused an answer with something unsaid
            return cut
        if not self.reopen_lets(decision.kind):
            # Persisted position is not playback authority in a new call.
            # Only an explicit repeat/new question may present that position - and, when begin_call kept the portion of a call that was cut a
            # moment ago (F3 round 1), the listener's repeat of it.
            return []
        if not self.state():return []
        if ctx.hold=='repeat_waits':      # c25-a G1 repeat_command (Р084, Р073 seed 102): «ещё раз» after a newer question asks for its answer: the older plan said again is an old answer
            logger.info('echo-sync decision kind=silent reason=repeat_waits_for_the_newer_question revision=%s',(state or {}).get('revision'));return []
        actions=self._cue(self._reply(text,f'{self.nonce}:{tid}'+(':tail' if tail else ''),decided=decision,going=ctx.going,basis=self._basis(state)))
        if decision.kind==ACK:actions=actions+self._speech_resumes()
        if not actions and reason in ATTEMPT_REASONS and not tail:
            actions=self._stuck(turn['text'],state,tried)
            if not actions and self._said_wrong(turn,state):return []
        if not actions and self.engine.current(self.state())!=SILENT and self._rearms(decision,reason,text):
            # A barge-in can cancel synthesis before its first byte; then no
            # playback_done callback exists to restart the silence timer.
            # W1F-B (C4): only silence or a real try runs it again (``_rearms``), never speech the classifier could not place.
            self.resume_repeat=True
        # Partial/incorrect repeats hold the cue, then restart the timeout.
        # The transport arms it only after confirmed local send completion.
        return actions
    def _rule_answered_elsewhere(self,c):
        """U117: somebody else already answered the question (near_voice's tag 'other' on the ear's piece of this final): our prompt for it is not needed. The question is the job's candidate this final replaced, or the one
        open with nothing of its answer said yet; the remark must answer it (``answers_asked``). The verdict is QUIET and the question is closed, so nothing of its answer is cued. No tag, no ear, a plan waiting: nothing happens."""
        gate=getattr(self,'speaker_gate',None);left=self.fast_left
        if gate is None or c.tail or c.decision.kind not in (QUESTION,QUIET) or probe('waiting_portion',state=c.state).value is not None:return
        asked=left[1] if left and left[0]==c.tid else self.question_text if self.question_id and not self.published and not self.lead_said else ''
        if not asked:return
        said=set(norm_words(c.text))      # the final may be the question's continuation (``utterance``): it is the ear's piece in another voice that is looked at, if the final carries it
        if not any(piece.get('text') and gate.is_other_utterance(piece.get('voice')) and len(set(norm_words(piece['text']))&said)*5>=len(norm_words(piece['text']))*3 and shares(asked,piece['text'],stems=ANSWER_STEMS,words=ANSWER_WORDS) and not asks_in(norm_words(piece['text']),piece['text']) for piece in self.ear_said):return
        if left and left[0]==c.tid:self.fast_left=None
        elif self._cue_playing(self.clock()):return
        else:self._drop_question()
        self._ruled(c,QUIET,'answered_elsewhere',None,'answered_elsewhere')
        logger.info('echo-sync decision kind=silent reason=answered_elsewhere revision=%s',(c.state or {}).get('revision'))
    def _ear_partial(self,record):
        uid,text=record.get('uid'),record.get('text')
        if self.ear_command_early and isinstance(text,str) and text.strip() and uid!=self.early_stop_uid:
            stopped=self._ear_early_stop(uid,text)
            if stopped is not None:return stopped
        flowed=self._ear_progress(record) if self.flow is not None else []      # f3-reaction: the text so far times the next portion (``flow_ahead``); it had no producer. A stop goes first
        if flowed:return flowed
        cut=self._ear_tail_note(uid,text)
        if cut:return cut
        if self.instant is None or not isinstance(text,str) or not text.strip():return []
        if self._followup_of(text) is not None:return []      # g31: «а счёт шестьдесят два» after «Счёт 51 активный или пассивный?» is no «Что такое счёт 62?»: the final asks the completed question (``_reference``)
        gate=getattr(self,'speaker_gate',None)
        try:noise=gate is not None and gate.verdict().kind=='quiet'      # f4-noise (near_voice act): text decoded from no speech (noise, a biased ear) opens no answer; the final decides
        except Exception:noise=False
        if noise:return []
        had=self.instant.hit if self.instant._uid==uid else None
        hit=self.instant.feed(text,self.clock(),uid=uid)
        if had is not None and self.instant.cut:
            # W13 item 2 (s3#16): once per utterance; the question the hit opened is marked cut, so its final is judged as if the ear had not acted (``_ear_first_final``), never «confirmed» onto a parked cue
            if self.instant_cut_uid!=uid and (self.published==had.answer or (self.ear_first or {}).get('hit')==had.answer):
                self.instant_cut_uid=uid
                logger.info('echo-sync instant act=cut uid=%s',uid)
                first=((self.ear_take or {}).get('ear') or {}).get('first')
                if first and first.get('hit')==had.answer:first['cut']=True
                self.ear_first=None
                return self.speech_started()
            return []
        if hit is None:return []
        started=self.ear_started.get(uid)
        piece={'uid':uid,'text':text,'onset':started[0] if started else None,'mark':started[1] if started else None,'offset':self.clock(),
               'onset_input_ms':None,'offset_input_ms':None,'acted':False}
        logger.info('echo-sync instant act=hit kind=%s trust=%s ms=%s uid=%s',hit.kind,hit.trust,hit.ms,uid)
        return self._ear_first([piece],piece)
    def _ear_tail_note(self,uid,text):
        """U54: the ear's text so far of the utterance ``uid`` has said the whole waiting portion, nothing after it (``flow_ahead.progress``: clean, every word, no word more): note it; ``_stable_due`` counts the portion as said once it
        has stood ``ack_stable_seconds`` (the rule of the cloud's stable partial), without the end-of-speech pause of the ear. Any other text drops the note: a word after the tail, or the speaker going back, cancels."""
        taken=self.ear_tail_taken
        if taken and taken[0]==uid and isinstance(text,str) and len(text.split())>len(taken[1].split()):      # taken, and the speaker went on: that was not the end
            self.ear_tail_taken=None;self.tempo_speaking=self.tempo_live;logger.info('echo-sync decision kind=silent reason=ear_tail_cut uid=%s',uid)
            return self.speech_started()
        old,self.ear_tail=self.ear_tail,None
        state=self.state();portion=probe('waiting_portion',state=state).value;started=self.ear_started.get(uid)
        if not self.ack_stable_seconds or not isinstance(text,str) or portion is None or started is None or self._may_still_grow(portion):return []
        if started[1]!=self._ear_mark() or not self._cue_over_before(started[0]):return []      # said over the cue, or the call moved since the onset: the final decides
        pr=tail_progress(text,portion)
        if not (pr.clean and pr.total>1 and pr.said==pr.total) or self._joined_repeat(text,state,alone=True) is None:return []
        self.ear_tail=old if old and old[:2]==(uid,text) else (uid,text,self.clock(),self._position(state));return []
    def _ear_verdict(self,run):
        """``(decision, None)`` when the ear may act on ``run`` now; else ``(None, why)`` (``why`` None: a verdict the ear never acts on)."""
        if any(p['text'] is None or p['onset'] is None for p in run):return None,'unknown_speech'
        state=self.state()
        if self._disputes(' '.join(p['text'] for p in run),state):
            numbers=lambda words:{atom for atom in self._protected_atoms(words)[0] if atom.startswith('#')}
            if state.get('revision') is not None and numbers(' '.join(p['text'] for p in run))-numbers(probe('waiting_portion',state=state).value or ''):
                self.ear_asked_on=state['revision']      # F6 (Р104): a new figure against the plan («нет, не 6, а 16»): the old answer is not repeated on its own
            return None,'dispute'      # H6 item 4: the final goes to the job
        decision=self._classify(' '.join(p['text'] for p in run),state)
        if probe('waiting_portion',state=state).value is not None and self._tries(decision,self._effective_reason(' '.join(p['text'] for p in run),state,decision)):
            self._engaged(state,to_it=decision.kind not in (QUESTION,CORRECTION))       # c8b: the ear heard a try at the portion: it is not abandoned meanwhile
        if self._ear_family(decision) is None:return None,None      # a question (of any voice) goes on to the job
        if decision.kind==STOP and run[-1]['uid']==self.early_stop_uid:return None,'early_stopped'      # w10 item 11: its partial has stopped the plan already
        gate=getattr(self,'speaker_gate',None)
        if gate is not None and all(gate.is_other_utterance(p.get('voice')) for p in run):return None,'other_voice'      # w5-near: a confirmation, a request to repeat or a «дальше» in somebody else's voice is not the listener's
        in_flight=decision.kind==STOP and self.fast_call and self.question_id and not self.published and self.diagnosed_epoch!=self.epoch      # g38 (always, no switch): an answer on its way, no portion yet: the stop of the ear stops it (the cloud's final came 2-5 s later, the cue between)
        if probe('waiting_portion',state=state).value is None and not in_flight:return None,'nothing_waits'
        mark=self._ear_mark()
        if any(p['mark']!=mark for p in run) and not in_flight:return None,'changed_since_onset'      # g38: the change is the question it stops being accepted («Стоп.» begun before that question's final)
        if not self._cue_over_before(run[0]['onset']) and not self._ear_stop(decision,run,state) and not self._ear_no_echo(decision,run,state):return None,'during_cue'    # said over a cue, or to one not heard: the cloud's
        return decision,None
    def _ear_early_stop(self,uid,text):
        """w10 item 11: the ear's text so far is a stop by itself (``ear_command.early_command``: not a word of the cue being said) and the portion waits: the stop of the ear (``_ear_stops``) now, ~0.2 s
        before the end of the utterance and its final decode. The final of the same utterance acts no more (``_ear_verdict``: ``early_stopped``). None: nothing to do."""
        state=self.state();portion=probe('waiting_portion',state=state).value
        gate=getattr(self,'speaker_gate',None)
        try:heard=gate.verdict().kind if gate is not None else None      # f4-noise (near_voice act): a stop in somebody else's voice, or in what is no speech, is not the listener's; the final decides
        except Exception:heard=None
        if heard in ('other','quiet'):return None
        if portion is None or not self.fast_call or early_command(text,portion=portion,fillers=frozenset(resolve(self.settings)['fillers']))!='stop':return None
        decision=self._classify(text,state)
        if decision.kind!=STOP:return None
        started=self.ear_started.get(uid)
        piece={'uid':uid,'text':text,'onset':started[0] if started else self.clock(),'mark':started[1] if started else None,'offset':self.clock(),'onset_input_ms':None,'offset_input_ms':None,'acted':False}
        self.early_stop_uid=uid
        logger.info('echo-sync ear command=stop early=1 uid=%s',uid)
        return self._ear_stops([piece],decision)
    def _ear_overruled(self,turn,whole,before,heard=None):
        """Fix round 1, item 2: the cloud's final of a turn whose confirmation the ear took. When the cloud's words of the utterance (``whole``)
        do not confirm the portion that waited (``before``) and say a number, a unit or a «не»/«ни» it does not have, the cloud heard
        something else where it matters: the step is taken back (``engine.rewind``), the next cue is cancelled, and the final is judged as
        the cloud alone would have judged it - the outcome without the ear. ``None`` when the confirmation stands (also when the cursor has
        moved on since and the step cannot be taken back). H5 item 4: ``heard``, the ear's words: the cloud cut at the marker of a self-correction and has said what he took back: that overrules nothing."""
        portion=probe('waiting_portion',state=before).value;corrected=probe('self_corrected',heard).value
        if portion is None or self._classify(whole,before).kind==ACK or self._tail_after(whole,before,ACK):return None
        if not self._late_correction(portion,whole) or (corrected and not self._late_correction(corrected[0],whole)):return None
        if not self._step_back(before):return None
        logger.info('echo-sync decision kind=silent reason=local_ear_overruled revision=%s index=%s',before['revision'],before['chunk_index'])
        cut=self._act('reset_portion','ear_overruled',basis=(None,before['revision'],turn['id']))[1];self.ear_take=None
        return cut+self._accept_user({**turn,'text':whole},boundary='early_tail',tail=True,whole=whole,cause='early_tail')
    def _ear_late_veto(self):
        """c9-numveto: the ear's utterance (``ear_pieces``) has just grown. When the cloud has already confirmed the portion it belongs to
        (``cloud_acks``: not by the ear, nothing else has happened since) and it carries another number than the portion
        (``_ear_number_veto``), the step is taken back as for ``_ear_overruled`` (``engine.rewind``, the next cue cancelled) and the utterance is
        judged as the ear heard it. Actions, or ``None`` when there is nothing to take back."""
        now=self.clock()
        for tid,(before,epoch,when) in list(self.cloud_acks.items()):
            if epoch!=self.epoch or not within(now,when,self.ack_join_seconds):
                self.cloud_acks.pop(tid,None);continue
            heard=self._ear_number_veto(tid,before)
            if heard is None:continue
            self.cloud_acks.pop(tid,None)
            if not self._step_back(before):return None
            logger.info('echo-sync decision kind=silent reason=local_ear_number_veto boundary=taken_back revision=%s index=%s',
                        before['revision'],before['chunk_index'])
            self.veto_back=(self._position(before),self.cue_heard)      # c24 P11: the next portion may have sounded already: the owner's try at it says where he is
            self._veto_place(before)      # c25-a G6: the help after it is the owner's rule: from the number, not the whole portion
            cut=self._act('reset_portion','ear_number_veto',basis=(epoch,before['revision'],tid))[1];self.ear_take=None;self.early_taken.pop(tid,None)
            turn=self.ledger.snapshot(tid) or {'id':tid,'role':'user','valid':True}
            return cut+self._accept_user({**turn,'final':True,'text':heard},boundary='early_tail',tail=True,whole=heard,cause='early_tail')
        return None
    def _ear_first_due(self):
        """What the ear may open, once it may: on the ear's text, on the tick and when the cloud's turn appears or grows. Actions, or None. The bounds are the ones of a confirmation (EAR_BIND_SECONDS) and, for a job,
        of its first text; a final of these words (``_ear_first_passed``) and speech that begins (``_ear_onset``) end the wait."""
        first=self.ear_first
        if first is None:return None
        why='not_announced' if self.clock()>first['deadline'] else None
        if why=='not_announced' and self._bank_first(first):return self._ear_stands_in(first['text'],first['run'][-1]['offset'])      # h28: its time is up and no cloud came: the base's answer is said, never dropped
        if why is None and not first['hit']:
            ready=self._ear_first_ready(first)
            if ready is None:why='nothing_to_answer'
            elif not ready:return None
        if why is None and self._ear_sum(first) and self.clock()-first['run'][-1]['offset']<EAR_RELEASE_SILENCE_SECONDS:return None
        if why is None and _number_grows(first['text']) and self.clock()-first['run'][-1]['offset']<SPLIT_JOIN_SECONDS:return None      # g14: «что такое счёт пятьдесят» | «два» is 52: «Счёт 50 — касса» was said
        if why is None:
            tid,why=self._ear_first_turn(first)
            if tid is not None:
                self.ear_first=None
                return self._ear_take(tid,first['run'],first['decision'],first)
            if why in ('no_open_turn','cloud_behind'):
                if self._bank_first(first):return self._ear_stands_in(first['text'],first['run'][-1]['offset'])      # h28: the base's answer needs no cloud (the call of 14:45: 110 ear texts, no final, no cue); h29 (910 s, the article on the seventh second): a number too: the cue names it, the final corrects it
                return None
        self._ear_first_drop(why)
        return None
    def _ear_first_ready(self,first):
        """Rule 2: has the ear's silence lasted, and has the job prepared on it given its first sentence? None: that job is over and has none (a remark in the form of a question): a verdict only once a final adopts it."""
        if self.clock()-first['run'][-1]['offset']<EAR_RELEASE_SILENCE_SECONDS:return False
        if first.get('lookup'):return first['decision'].kind==QUESTION or first.get('form')=='cloud'      # c22-speed: no job without its source; the cloud's open turn is the witness (``_turn_reads``)
        said=self.prepared_job(first['asked'])
        if said is None:return False
        answer=brain_answer(said[0])
        if answer and first['decision'].kind!=QUESTION and self._said_already(answer,first['asked']):return None      # c16: words with no form, and the job said the answer in play: no reason to open
        if answer and self._of_substance(answer,first['asked'],said[1],brain=True)[1]:return True
        return None if said[1] else False
    def _ear_first_overruled(self,turn,whole):
        """The final says something else: the cue is cut, what was opened goes (a job with it: a cancel keeps no job of a question that is gone), it is no answer to anything said, no «продолжай» finds it, the plan it took
        over is back, and the final is judged on that as if the ear had not acted. For the job and the base this exchange never happened (the history entry says ``unasked``)."""
        state=self.state() or {};tid=turn['id'];held=self._plan_held(state)
        logger.info('echo-sync decision kind=silent reason=ear_first_overruled revision=%s',state.get('revision'))
        self._act('close_question','ear_first_overruled')
        if state.get('answer'):
            self.engine.revised(self.session_id,state.get('question'),state['answer'],status=UNASKED)      # the engine's history says it never happened: every reader of the call's history skips it
        if self.fast_turn:self._fast_out(self.fast_turn)
        cut=self._drop_question()
        self.fast_asked=None;self.local_answer=False;self.suspended=None;self.ear_take=None;self.seen.discard(tid);self.user_boundaries.pop(tid,None)
        self.lookup_topic=self.fast_topic;self.question_text='';self.published=''
        if self.delegation_id:self.early_delegations[tid]=self.delegation_id      # the model waits for a result on this turn
        if held is not None:
            got=self._plan_back(held)      # H6 item 2 (R4): a plan that was stopped is as it was: no timer, nothing is said until the listener resumes
            if got is not None and not got[1]:self.resume_repeat=True
        return cut+self._accept_user({**turn,'text':whole},cause='ear_overruled')
    def _tempo_speech(self,uid,what):
        now=self.clock()
        if what=='live':
            self.tempo_live=True;self._hearing_end()
        elif not self.tempo_live:return
        elif what=='lost':self._tempo_off()
        elif what=='onset':
            if self.tempo_ended is None or now-self.tempo_ended>=EAR_RELEASE_SILENCE_SECONDS:self.tempo_run=now
            elif not (self.cue_window is not None and self.cue_window[0]>=self.tempo_ended):self.pauses.went_on(now-self.tempo_ended)      # one-research EOT-RU: the speaker paused and went on in the same run (not a pause a cue began in: that was our turn, livekit re-anchors it)
            self.tempo_speaking=True;self.tempo_began=now;self.tempo_awaits=None;self._heard_locally=True;self.tempo_began_at=self._position(self.state())
            self.tempo_spans[uid]=(now,self._position(self.state()))
            while len(self.tempo_spans)>16:self.tempo_spans.pop(next(iter(self.tempo_spans)))
        else:self.tempo_speaking=False;self.tempo_ended=now;self.tempo_awaits=uid
    def _tempo_stuck(self,now):
        """H6 item 6: one stretch of speech with no offset for EAR_SPEECH_SECONDS, and the cloud has written no word of it for EAR_FINAL_SECONDS: the detector is stuck: it says nothing any more (the call of 4 Nov has stretches longer than that, and the cloud wrote them
        down). An offset that does come later does no harm."""
        gate=getattr(self,'speaker_gate',None)      # w2-own-voice: speech confirmed to be somebody else's is no speech of the listener: the detector is not waited for
        other=bool(self.tempo_speaking and gate is not None and gate.other_speaking())
        if self.tempo_speaking and self.tempo_began is not None and (other or (now-self.tempo_began>=EAR_SPEECH_SECONDS and (self.cloud_heard is None or now-self.cloud_heard>=EAR_FINAL_SECONDS))):
            logger.info('echo-sync ear tempo=stuck after_s=%.1f',now-self.tempo_began)
            self.tempo_speaking=False;self.tempo_ended=now;self.tempo_awaits=None
            if self.repeat_at is None and self._position(self.state()) is not None:self._tempo_arm(now+self._silence().wait)
    def _tempo_judged(self,final,tid=None):
        """H5 skeptic: a final judges only what it says: the cloud's come seconds behind the ear (n1_01 step 16: 203.7 «Теперь станок» with the ear at the fifth comma). Of the pieces nobody has judged it takes those up to the
        last it names; the rest is later speech. Naming none, it takes them all: one of the two misheard the other."""
        said=self._final_pieces(final,[text for _,text in self.tempo_unjudged])[0];self.tempo_contradicted=None
        if tid is not None:      # c24-a1: where the speech this final says ended, of all the ear heard since the speech the final before said («старый ответ», fuzz seeds 0, 16, 18): ``_said_after``
            ends=self.__dict__.setdefault('tempo_said_end',{});since=max((end for end,_ in ends.values()),default=None)
            pieces=[p for p in self.ear_said if p['text'] and type(p['offset']) in (int,float) and (since is None or (p['onset'] is not None and p['onset']>since))] if self.ear_said else []
            at,known=self._final_pieces(final,[p['text'] for p in pieces]) if pieces else ([],set())
            if not at and self.tempo_unjudged:pieces,(at,known)=[{'offset':end} for end,_ in self.tempo_unjudged],(said,{mark for _,text in self.tempo_unjudged[:said[-1]+1] for mark in self._marks(text)} if said else set())
            if at:ends[tid]=(pieces[at[-1]]['offset'],known)
            while len(ends)>8:ends.pop(next(iter(ends)))
            own={pieces[n]['offset'] for n in at} if at and not said and 'text' in pieces[0] else None
            if own:      # c24-a1 (fuzz seed 36): naming none of them, it names speech of its own the ear heard: what nobody judged is another utterance (a question whose final was lost), not misheard
                self.tempo_unjudged=[(end,text) for end,text in self.tempo_unjudged if end not in own and self._may_ask(text)];return
        if said:      # c24-a1 (fuzz seed 36): a piece before the last it names that it does not name, a breath of its own before the next it names (a silence of EAR_RELEASE_SILENCE_SECONDS): another utterance
            onset={p['offset']:p['onset'] for p in self.ear_said if type(p.get('offset')) in (int,float) and p.get('onset') is not None}
            apart=lambda n:any(onset.get(self.tempo_unjudged[m][0]) is not None and onset[self.tempo_unjudged[m][0]]-self.tempo_unjudged[n][0]>=EAR_RELEASE_SILENCE_SECONDS for m in said if m>n)
            self.tempo_unjudged=[self.tempo_unjudged[n] for n in range(said[-1]) if n not in said and apart(n) and self._may_ask(self.tempo_unjudged[n][1])]+self.tempo_unjudged[said[-1]+1:];return      # a try, a remark: judged with it, as ever (h3 ``…doubt_of_the_year_after_the_help``)
        self.tempo_unjudged=[]
    def _utterance_over(self,text):
        """H5 item 6: is the utterance of ``text`` over, for an answer to go? See EAR_RELEASE_SILENCE_SECONDS. With no ear the flag of speech says, as ever."""
        if not self.tempo_live:return not self.hearing
        now=self.clock();quiet=now-self.tempo_ended if self.tempo_ended is not None else EAR_TAIL_SILENCE_SECONDS
        return not self.speech_open(now) and quiet>=self._release_wait(text)
    @classmethod
    def _said_by_value(cls,said,portion):
        """``_walk_start`` on the comparison atoms: words by their lemma, numbers by value. A number the listener has not finished («в девятьсот» of «В 988 году») stops there: it is what is missing. The
        preposition in front of a number may be gone: the listener or the recognizer drops it («девятьсот» of «В 988 году»), as the job's answer drops it (``_said_as_written``)."""
        from .ru_alignment import _canonical, spoken_as_written, unit_start
        said=spoken_as_written(said,portion)      # U16: a range said as its two ends is the range written
        atoms=_canonical(portion,(),True)
        own=[re.sub(r'^#ord:','#',atom.atom) for atom in atoms]
        heard=[re.sub(r'^#ord:','#',atom.atom) for atom in _canonical(said,(),True)]
        twice=False
        at=1 if heard and own and heard[0].startswith('#') and not own[0].startswith('#') and _LEAD_PREPOSITION.match(str(portion)) else 0
        for spot,atom in enumerate(heard):
            if at<len(own) and atom==own[at]:at+=1
            elif atom in own[:at]:twice=True
            elif spot==len(heard)-1 and atom.startswith('#') and at<len(own) and cls._may_grow_into(atom,{own[at]} if own[at].startswith('#') else set()):break
            else:return None
        else:
            if not 0<at<len(own):return None
        if not any(atom.startswith('#') for atom in heard):return None    # with no number in it ``_walk_start`` has said what there is to say
        folded=str(portion).casefold().replace('ё','е');end=0
        for atom in atoms[:at]:
            for word in atom.surface.split():
                spot=re.compile(r'\s*'.join(map(re.escape,word))).search(folded,end)
                if spot is None:return None
                end=spot.end()
        rest=WORDS.search(str(portion),end)
        if rest is None:return None
        sign=_SIGNS.search(str(portion),end,rest.start())      # F6: «₽ в месяц»: the sign of a unit is no word, and it is what is missing
        return (str(portion)[unit_start(str(portion),sign.start() if sign else rest.start()):],twice)      # U16: never cut inside a range
    def _ear_words(self,final,floor=None,split=False):
        """H6 item 3 (n1_01 step 16: the cloud had holes where the ear had the words): what the ear heard of the utterance of ``final``: the pieces of the breath of the last piece it names, a pause of EAR_RELEASE_SILENCE_SECONDS ends a
        breath, and what the ear acted on is said already. '' when the ear heard none of it, or the same."""
        pieces=[piece for piece in self.ear_said if piece['text'] and piece['onset'] is not None and piece['offset'] is not None and not piece['acted']]
        named=[at for at,piece in enumerate(pieces) if self._final_says(final,piece['text'])]
        if not named:return ''
        numbers=lambda said:{atom for atom in self._protected_atoms(said)[0] if atom.startswith('#')}
        says=lambda text:len({stem for stem in _stems(text)&_stems(final) if not stem.isdigit()})+len(numbers(text)&numbers(final))
        first=last=max(named,key=lambda at:(says(pieces[at]['text']),at))     # A1-F7: the piece that says most of the final (words, numbers by value), not the last one sharing a word with it («в каком году было …» of the next question)
        while first and pieces[first]['onset']-pieces[first-1]['offset']<EAR_RELEASE_SILENCE_SECONDS:first-=1
        while not split and last+1<len(pieces) and pieces[last+1]['onset']-pieces[last]['offset']<EAR_RELEASE_SILENCE_SECONDS:last+=1      # c23 P04: not into the utterance the cloud has a turn of its own for («Распознано: A / B»)
        if floor is not None and pieces[last]['offset']<floor:return ''      # A8-4: a breath over before the listener's last final of another turn is no recording of this one
        heard=' '.join(piece['text'] for piece in pieces[first:last+1])
        strip=lambda text:probe('strip_fillers',text,settings=self.settings).value
        return '' if same_question(heard,final,strip=strip) and same_question(final,heard,strip=strip) else heard
    def _fast_wide_ear(self,record):
        """H7 item 4 (С2): every ear final goes the way of ``_fast_wide``, as the breath it is in."""
        text=record.get('text');onset=record.get('onset')
        if not isinstance(text,str) or not text.strip():return []
        if self.wide_breath and (onset is None or self.wide_breath[-1][0] is None or onset-self.wide_breath[-1][0]>=EAR_RELEASE_SILENCE_SECONDS):self._wide_break()
        self.wide_breath=self.wide_breath+[(record.get('offset'),text)]
        return self._fast_wide(('. ' if self.ear_job else ' ').join(piece[1] for piece in self.wide_breath),'ear')      # c16: the ear has no marks and a piece ended on a pause: it is what ``question_part`` cuts by
    def _speech_goes_on(self):
        """H6 item 5: with the channel on, does the ear hear speech go on past what has just been judged?"""
        return bool(self.fast_on and self.tempo_live and (self.tempo_speaking or (self.tempo_ended is not None and self.clock()-self.tempo_ended<EAR_RELEASE_SILENCE_SECONDS and self.tempo_awaits is not None)))
    def _rule_remark_form(self,c):
        form=None if c.tail or c.utterance or c.decision.reason not in REMARK_REASONS else remark_ruling(c.text)      # U118: an objection is a correction of the answer, a clarification asks about it
        if form:c.decision=form;c.spoke('remark_form')      # U108 (5): a complaint is no question, the plan begun stays
    def _continuation(self,turn):
        """W1F-B (class C2): does this user final go on with the question's utterance (see UTTERANCE_TAIL_WORDS)? ``None``; ``('piece',)``
        for a bare self-correction opener («Нет», «Ой, подождите»: the correction is still to come and there is nothing to act on yet); ``('heard',)``
        for a final that says only what the question's job heard already (c16: nothing is joined, nothing is cut); or
        ``('join', question id, the joined utterance, restorable)``.

        Only a turn that BEGAN within ``coalesce_seconds`` of the previous final of the utterance (the question's, or an opener's said after
        it), and only while the listener has confirmed nothing of the answer: before its first cue, or after it while the first portion still
        waits. Then it joins when it is at most UTTERANCE_TAIL_WORDS words that alone are nothing the controller acts on (no confirmation,
        command, greeting or question of its own), or when it corrects the question: alone a correction, or a self-correction opener, «не X,
        а Y» or two of the question's content words again, at most UTTERANCE_FIX_WORDS words. A tail that opens with a question word is a
        question of its own, and a try at the waiting portion is a try. ``restorable``: the old narrow seam - a question cut after a function
        word, nothing published yet - whose cloud scaffolding may go on («Это называется» | «сублимация.»); every other join retires what
        the cloud said to the unfinished question. On the lookup route (integ9: F3 looks up every amount / rate question, so «Сколько процентов
        составляет» | «ставка НДС» is on it from its head on) only while the sources have not been handed to the model yet: the join is then
        asked again as the whole question (a new lookup), never restored - an external-source handoff keeps no scaffolding."""
        def job_heard():
            """c16 (n1_02 step 14 of c16-a: the cloud cut «… нужно предупредить» | « работодателя», the job on the ear's breath had the answer 1.5 s after the speech, the join threw it away, a new job on the final: 5.3 s): is this final of
            another turn a rest of the open question that its job has heard already? All it says is in what the job was asked, and the question with it reads as that (``wide_refusal``). Then nothing is joined and nothing is cut. Anything the job
            has not heard, a number or a word, goes the old way."""
            if not (self.ear_job or self.live_first) or not self.job_asked or not self.question_id or turn['id']==self.question_id or not self.fast_on:return False
            heard=self.job_asked(self.question_id)
            if not heard or not self._said_words(turn['text']):return False
            if self.ear_onset_at is not None and self.question_clock is not None and self.ear_onset_at>self.question_clock:return False      # speech began after the question opened: it may be its own
            strip=lambda text:probe('strip_fillers',text,settings=self.settings).value
            return said_within(heard,turn['text'],strip=strip) and wide_refusal(heard,f"{self.question_text} {turn['text']}",strip=strip,whole=True) is None
        if self._ear_safely(job_heard,default=False):return 'heard',      # c16: the job has heard it: nothing is joined, nothing is cut (the caller says it was heard)
        old_id=self.question_id
        if not self.coalesce_seconds or not old_id or turn['id']==old_id:return None
        if self.suspended and self._said_to_the_plan(turn['text'],self.state()):return None    # G3: words at the plan a question took over do not go on with it
        lookup=not self.direct_content
        if lookup and (self.context_requested or self.delivery_ready):return None
        if turn['id'] in self.seen:return None        # a turn the stable partial already took: its final is its tail's (``_early_tail``)
        old=self.ledger.snapshot(old_id)
        if not old or not old['valid'] or not old['final']:return None
        last=self._utterance_final();began=self.user_started_at.get(turn['id'],self.clock())
        gap=began-(last if last is not None else -100);breath=self._ear_went_on(last,old_id)
        if not breath and not 0<=gap<=self.coalesce_seconds:return None
        published=bool(self.published)
        # After the first cue only what began before that cue was over (this turn, or the opener it goes on from): what begins after it
        # is a reaction to it, never the rest of the question («Слушай, ты меня слышишь?» 2 s after a fast first cue).
        began=min([began]+[self.user_started_at.get(piece,began) for piece,_,_ in self._pieces()])
        if published and (not self._nothing_confirmed() or self._cue_over_before(began)):return None
        state=self.state();decision=self._classify(turn['text'],self._heard_with(state))
        how=self._goes_on(turn['text'],decision,published,seam=not lookup and not published and not self._pieces())
        restorable=how=='seam'
        # Beyond the old seam only a turn that was announced before its final: one that arrives as a bare final (a retransmit after a
        # reconnect, S4) has no known start, so nothing says it went on with the question.
        how='join' if restorable else how if turn['id'] in self.announced_at else None
        if how=='piece':return 'piece',
        if not restorable and not self._has_content(turn['text']):return None      # c24 (half_hour seed 4 @1334): a laugh («Хи-хи.») adds nothing to the question: it does not retire the answer in play
        # H5 item 6: a question stopped on an open tail, or the same breath by the ear: what follows is its rest, however long, unless it is a command or a repeat. The cue is cut and the job asked again on the whole.
        if how!='join' and not (self.fast_on and (breath or probe('open_tail',self.question_text).value) and decision.kind in (QUIET,QUESTION,CORRECTION) and decision.reason not in ATTEMPT_REASONS):return None
        joined=self.question_text.rstrip()
        for piece in [text for _,text,_ in self._pieces()]+[turn['text']]:
            piece=piece.strip()
            joined+=('' if re.match(r'[,.;:!?…]',piece) else ' ')+piece
        return 'join',old_id,joined,restorable
    def _goes_on(self,text,decision,published,seam=False):
        """W1F-B: how a tail said within the window goes on with the question - the ONE rule of it (the join of ``_continuation`` and the
        wait of ``_holding`` read it): ``'seam'`` (only when ``seam``: nothing is published; the narrow seam as it was before W1F-B: a question
        cut after a function word («…сразу в») takes a short non-command continuation («газообразное»), and the cloud's scaffolding to the
        head may go on), ``'piece'`` (a bare self-correction opener: the correction is still to come), ``'join'``, or None (``decision``: the
        classifier's verdict on the tail alone; ``published``: the first cue is out). A complete question (with «?», or only an interrogative
        word) takes a correction only: what follows it is another utterance otherwise."""
        words=norm_words(self.question_text);tail=self._said_words(text)
        if seam:
            cut_tail=norm_words(text)
            # Wave F (F2): alone a bare named topic is a question now (classifier rule 1); after a head cut at a function word it is that head's
            # complement («Расскажи про» | «подзолистую почву.», T-A F39/C17), not a command.
            if words and words[-1] in FUNCTION_WORDS and cut_tail and len(cut_tail)<=UTTERANCE_TAIL_WORDS and cut_tail[0] not in QUESTION_WORDS:
                if decision.kind in (QUIET,REPLAY) or decision.reason=='topic_phrase':return 'seam'
                # ASR may punctuate the grammatical complement as its own question ('в' + 'газообразное?'): after «в»/«на» only.
                if decision.kind==QUESTION and words[-1] in {'в','на'}:
                    try:
                        from . import ru_alignment as ru
                        ru._lemma(cut_tail[0])
                        with ru._LOCK:parses=ru._MORPH.parse(cut_tail[0])
                        if any(p.tag.POS in {'ADJF','PRTF'} and p.tag.case in {'accs','loct'} for p in parses):return 'seam'
                    except ImportError:pass
        if not words or not tail or tail[0] in QUESTION_WORDS:return None
        said=' '.join(tail)
        if _FIX_ONLY.fullmatch(said):
            if decision.kind==ACK:return None
            if not published:return 'piece'
            # Integration (S6 invariant S4): after the first cue, a bare «Нет,» that is the START of the waiting portion itself («Нет, кит
            # не рыба,») is the listener beginning to repeat it - a try, never a self-correction opener of the question.
            reason=self._effective_reason(text,self.state(),decision)
            portion=norm_words(probe('waiting_portion',state=self.state()).value or '')
            if reason.startswith('attempt') or (portion and portion[:len(tail)]==tail):return None
            return 'piece' if decision.kind==QUIET else None
        opens=bool(_FIX_START.match(said) or _NOT_THIS_BUT.search(said))
        contrast=re.search(r'(?:^|\s)(не\s+\S+(?:\s+\S+)?\s+а\s+\S+)',said)
        if opens and published and contrast and _said_within(contrast.group(1),[probe('waiting_portion',state=self.state()).value or '']):opens=False      # c23 (S6 S4): «не рыба, а млекопитающее» of the waiting «Нет, кит не рыба, а млекопитающее, …» is a try at it
        if opens and published and not _NOT_THIS_BUT.search(said):
            # Integration (S6 invariant S4): a «нет …» that is the waiting portion's own first word is the listener's try at the portion
            # («Нет, кит рыба» for «Нет, кит не рыба,» - a wrong repeat), not the opener of a correction of the question.
            portion=norm_words(probe('waiting_portion',state=self.state()).value or '')
            if portion and tail[0]==portion[0]:opens=False
        # Wave F / F2 fix round 1 (ruling 1): a bare topic phrase is a question alone, but after a question head («Сколько стоит» |
        # «баррель нефти») it goes on with it like a QUIET tail - the guards below (a complete question, no content, the length) decide.
        if decision.kind in (QUIET,REPLAY) or decision.reason=='topic_phrase':
            reason=self._effective_reason(text,self.state(),decision)
            if reason in ('empty','only_fillers') or (published and decision.kind!=QUIET):return None
            # A try at the waiting first portion is a try («Пять на пять» for «Четыре на пять —»), unless it says that it corrects
            # («Подождите, четыре билета…» for the echo «Три билета по двести —»).
            if published and reason.startswith('attempt') and not opens:return None
        elif decision.kind!=CORRECTION:return None
        if not _content(text):return None       # «Угу», «Да», «Это» go on with nothing
        fixes=decision.kind==CORRECTION or opens or len(_stems(said)&_stems(self.question_text))>=2
        if probe('question_complete',self.question_text).value and not (fixes or self._pieces()):return None
        if len(tail)>UTTERANCE_TAIL_WORDS and (len(tail)>UTTERANCE_FIX_WORDS or not fixes):return None
        return 'join'
    def _pieces(self):
        """The bare openers said after the CURRENT question (``self.pieces``), oldest first."""
        return self.pieces if self.pieces_of==self.question_id and self.question_id else []
    def _utterance_final(self):
        """When the last final of the question's utterance came: the question's own, or that of an opener said after it."""
        times=[self.user_done_at.get(self.question_id)]+[when for _,_,when in self._pieces()]
        times=[when for when in times if when is not None]
        return max(times) if times else None
    def _cue_over_before(self,began):
        """Had the listener heard the last cue to its end (its voice and the margin after it, ``cue_window``) before ``began``? A cue that
        never began to play (parked while they spoke, cut before its first frame) was not heard at all."""
        window=self.cue_window
        return bool(self.cue_heard and window and began>window[1])
    def _take_piece(self,turn,boundary='provider_turn_done'):
        """A bare self-correction opener said after the question: it is kept to be joined with the correction it announces. Nothing is
        acted on, and it releases nothing: a cue that waits for the listener to finish goes on waiting (the flag of their speech expires by
        itself, HEARING_SECONDS), and the answer to the question is held while the rest may still come (``_holding``)."""
        tid=turn['id']
        self.seen.add(tid);self.user_boundaries[tid]=boundary
        if self.pieces_of!=self.question_id:self.pieces,self.pieces_of=[],self.question_id
        self.pieces=(self.pieces+[(tid,turn['text'],self.clock())])[-4:]
        self._hearing_alive()
        logger.info('echo-sync decision kind=silent reason=utterance_goes_on revision=%s',(self.state() or {}).get('revision'))
        return []
    def _effective_reason(self,text,state,decision):
        """The reason of a QUIET verdict with the sub-reason the call's silent verdict folds away: in the call's own verdict every utterance the
        classifier cannot place is 'mismatch_policy_silent', a real try at the portion as much as a bystander. The classifier itself tells
        them apart in its diagnostic reading (``analyze(diagnose=True)``, ``classifier._mismatch``): attempt_shared_stem / attempt_repeat_cover / attempt_clarification,
        or speech_too_long_for_an_attempt / weak_question_ignored / unrelated_speech. Any other verdict keeps its reason."""
        if decision.kind!=QUIET or decision.reason!='mismatch_policy_silent':return decision.reason
        try:
            probe=self._classify(text,state,diagnose=True)
        except Exception:return decision.reason
        return probe.reason if probe.kind in (QUIET,REPLAY) else decision.reason
    def _joined_repeat(self,text,state,alone=False):
        """ACK-split: the cloud may hear ONE repeat of a portion as several consecutive turns («свойство тела» | «сопротивляться
        изменению своего движения»), and each piece alone is only an attempt. The text that confirms the portion, when the
        pieces said since it started (``heard_since_portion``) joined in order with this final are exactly its words; else
        ``None``. The same matcher decides, so a wrong number, an added «не» or another word still fails. The shortest join
        that confirms wins, and at most ``ack_join_fragments`` pieces (this final included) are tried. ``alone``: the text on its own is tried first (no piece joined): the one answer to «does this text confirm the waiting portion»
        that the stable partial and the ear's tail ask; the judge's rule asks only after the classifier has said no."""
        if probe('waiting_portion',state=state).value is None:return None
        if alone and self._classify(text,state).kind==ACK:return text
        pieces=self.heard_since_portion()
        for count in range(1,min(len(pieces),self.ack_join_fragments-1)+1):
            candidate=' '.join(pieces[-count:]+[text])
            if self._classify(candidate,state).kind==ACK:return candidate
        return None
    def _joined_question(self,tid,text,state):
        """W1F-B (C2 while an older answer waits, sc01 / w1_14 step 3): the question twin of ``_joined_repeat``. The cloud may cut ONE
        question into short finals at a pause («Объясни» | «Кандса»; «А откуда взялось» | «Такое название у этой науки»), each of them
        nothing alone. This final (QUIET) is joined with the QUIET finals before it that it goes on from - each begun within
        ``coalesce_seconds`` of the final before it, at most three - and judged again: ``(joined text, decision, piece ids)`` when the
        joined text is a question or a correction (the shortest join that is), else None. A question the classifier finds too weak to
        replace a waiting portion («Объясни Кандса»: two words) counts when the cloud answered a piece of it with something of substance:
        the strength rule guards against one stray word, and this is neither one word nor stray."""
        if not self.coalesce_seconds or tid not in self.announced_at:return None
        run=[];began=self.user_started_at.get(tid,self.clock())
        for piece in reversed(self.quiet_pieces):
            if not within(began,piece[3],self.coalesce_seconds):break
            run.insert(0,piece);began=piece[2]
            if len(run)>=3:break
        for count in range(1,len(run)+1):
            candidate=' '.join([piece[1].strip() for piece in run[-count:]]+[text.strip()])
            ids=tuple(piece[0] for piece in run[-count:])
            decision=self._classify(candidate,self._heard_with(state))
            if decision.kind in (QUESTION,CORRECTION):return candidate,decision,ids
            if self._effective_reason(candidate,state,decision)=='weak_question_ignored' and any(self.owners.get(t['id']) in ids and self._of_substance(t['text'],self.question_text,True)[1] for t in self.ledger.history() if t['role']=='assistant'):      # the cloud answered a piece of it in substance: the one test of the candidate's admission (``_of_substance``)
                return candidate,decision._replace(kind=QUESTION,reason='joined_weak_question',question=probe('strip_fillers',candidate,settings=self.settings).value),ids
        return None
    def _request_goes_on(self,tid,text,state):
        """W1F-B (TR-FRAG, w1_08 step 4): the provider split «Вернёмся к цунами. На чём мы остановились?» into three finals; the first
        restored the tsunami answer, and the second, alone a question («на чём»), retired it at once. A final that began within
        ``coalesce_seconds`` of the last request served locally (``local_request``: going on, a return) and names nothing of its own (its
        content words are none, or that request's) goes on with that request when the two joined are still a request to go on: ``(joined
        text, its decision)``, served as one (the engine decides it again: the portion that waits is said once more). Else None - a real
        question after a request («А что такое оползень») stays a question."""
        request=self.local_request
        if not request or not self.coalesce_seconds or tid not in self.announced_at:return None
        if not within(self.user_started_at.get(tid,self.clock()),request[2],self.coalesce_seconds):return None
        own={item[0] for item in _content(text) if item[0] not in _REQUEST_STEMS}
        if own-_stems(request[1]):return None
        joined=request[1].rstrip()+(' ' if not re.match(r'\s*[,.;:!?…]',text) else '')+text.strip()
        decision=self._classify(joined,state)
        if decision.kind in (RESUME,NEXT) or decision.reason=='topic_change':return joined,decision
        return None
    def _note_quiet(self,tid,text,decision,reason):
        """Keep a QUIET final the classifier could not place as a possible piece of a question (``_joined_question``); anything the
        controller acts on, or a try at the portion, ends the run (a final of nothing but fillers or a backchannel leaves it as it is)."""
        if decision.kind==QUIET and (reason in ('empty','only_fillers') or not _content(text)):return
        if decision.kind==QUIET and not self._rearms(decision,reason,text) and tid in self.announced_at:
            self.quiet_pieces=(self.quiet_pieces+[(tid,text,self.user_started_at.get(tid,self.clock()),self.clock())])[-4:]
        else:self.quiet_pieces=[]
    @staticmethod
    def _may_still_grow(portion):
        """Is the end of this portion something a partial transcript can still add to? A number: «1945» is «19» for a moment, and
        «19» is a complete number too. Those portions are confirmed by the final only (unknown: the same, to be safe)."""
        try:
            from .ru_alignment import _canonical
            atoms=_canonical(portion,(),True)
        except Exception:return True
        return not atoms or atoms[-1].kind=='n'
    def _stable_taken(self,slot,now):
        """The one clock of the stable text of the waiting portion (``ack_stable_seconds``): the noted text of ``slot`` (the cloud's partial ``partial_ack``, the ear's text ``ear_tail``) once it has stood that long, taken out of its slot; else ``None``. Both feed the one judge (``_accept_user``) the same way."""
        pending=getattr(self,slot)
        if pending is None or now-pending[2]<self.ack_stable_seconds:return None
        setattr(self,slot,None);return pending
    def _stable_due(self,now):
        """The one acceptor of a stable text of the waiting portion: the noted text of each slot of ``_stable_taken`` that has stood ``ack_stable_seconds`` and still says the portion at the position it was noted at is the listener's confirmation, judged by the one judge (``_accept_user``): the cloud's partial (``_watch_partial``: its turn is taken, its final can never advance the portion a second time, what was said AFTER the portion is still heard, ``_early_tail``), then the ear's tail (``_ear_tail_note``: the cloud's open turn of the utterance, when there is one, is taken; the final of the ear then finds the call moved, ``changed_since_onset``). The actions of the first that acts, else ``[]``."""
        for slot in ('partial_ack','ear_tail'):
            pending=self._stable_taken(slot,now)
            if pending is None:continue
            who,text,_,position=pending;state=self.state()
            if self._position(state)!=position or (said:=self._joined_repeat(text,state,alone=True)) is None:continue
            if slot=='partial_ack':
                turn=self.ledger.snapshot(who)
                if not turn or not turn['valid'] or turn['final'] or who in self.seen or turn['text']!=text:continue
                logger.info('echo-sync decision kind=ack reason=stable_partial revision=%s',(state or {}).get('revision'))
                actions=self._accept_user({**turn,'final':True},boundary='stable_partial',cause='stable_partial')
            else:
                actions=self._ear_safely(self._ear_tail_take,who,text,said,now,default=[])
            if actions:return actions
        return []
    def _ear_tail_take(self,uid,text,said,now):
        """U54: the ear's noted tail is the confirmation (see ``_stable_due``, which has just read the position and the text: they are not read twice)."""
        state=self.state()
        tid=self._open_turn_id('ear',uid)
        logger.info('echo-sync decision kind=ack reason=ear_tail uid=%s revision=%s index=%s',uid,state.get('revision'),state.get('chunk_index'))
        turn=self.ledger.snapshot(tid) or {'id':tid,'role':'user','valid':True}
        if self.tempo_live and self.tempo_speaking:self.tempo_speaking=False;self.tempo_ended=now      # the speaker has said all there is to say: the cue is not held for the detector's pause (its offset, when it comes, finds the call moved)
        actions=self._take_early(turn,said,'ear_tail');self.ear_tail_taken=(uid,text)
        return actions
    def _take_early(self,turn,text,boundary):
        """The one way a portion is confirmed AHEAD of the final of its turn (the cloud's stable partial, the ear's stable tail, the pace of the speaker): the turn, taken whole with ``text`` as its words, goes to the one judge (``_accept_user``), whose one place notes it for its final (``_early_tail``). ``boundary`` is also the cause the turn record keeps."""
        return self._accept_user({**turn,'final':True,'text':text},boundary=boundary,cause=boundary)
    def _open_turn_id(self,prefix,uid):
        """The turn a confirmation made ahead belongs to: the cloud's open turn of the utterance when there is one (its final is then only a tail), else ``<prefix>-<uid>``, a turn of its own."""
        user=self.ledger.latest_user()
        return user['id'] if user and user['valid'] and not user['final'] and user['id'] not in self.seen else f'{prefix}-{uid}'
    def _remember_fragment(self,text,decision,state):
        """Keep this final for ``_joined_repeat`` when it was only an attempt (or anything the classifier keeps quiet about);
        anything the controller acted on (a confirmation, «повтори», a question, «стоп») starts the portion afresh."""
        position=self._position(state)
        keep=decision.kind==QUIET or (decision.kind==REPLAY and decision.reason.startswith('attempt'))
        if position is None or not keep:
            self.fragments=[];return
        if decision.reason in ('empty','only_fillers'):return   # nothing was said
        now=self.clock()
        self.fragments=[f for f in self.fragments if f[0]==position and within(now,f[2],self.ack_join_seconds)][-max(0,self.ack_join_fragments-2):]
        if self.ack_join_fragments>1:self.fragments.append((position,text,now))
    def _heard_with(self,state):
        """Wave F / F2 fix round 1 (ruling 4): the state a user turn is classified with. While an accepted question waits for its first cue
        (nothing published, the question not given up nor its failure told), the classifier is told so (``asked_in_flight``): a bare topic
        phrase then names no new question - a restated topic («Крещение Руси.» after «Когда было крещение Руси?»), the tail of a question the
        provider cut. The engine's own state is not changed (it classifies the question text with it when the answer is published)."""
        if not self.question_id or self.published or self.diagnosed_epoch==self.epoch:return state
        return {**(state or {}),'asked_in_flight':self.question_text or True}
    def _asked_ruling(self,text,admitted=None,whole=None):
        """B: the verdict a publication carries: the kind and the reason the question was opened with, or the admission that settled it. The engine does not judge the text again.
        ``whole``: the question as recorded when ``text`` is only the part of it that was judged (a question said after an early-confirmed portion: the kind is that of the part, the question is everything they said); the engine records ``Decision.question``."""
        kind=QUESTION if admitted or self.question_kind not in (QUESTION,CORRECTION) else self.question_kind
        return Decision(kind,admitted or self.question_reason or 'question',whole or text,None)
    @property
    def hearing(self):
        """Is the listener speaking right now? Set by a start of speech, kept alive by the growth of their transcript, cleared by
        an accepted final, and released by itself ``hearing_seconds`` after the last sign of speech (HEARING_SECONDS). H3: while the ear keeps the tempo, its detector alone says so."""
        if self.tempo_live:return self.tempo_speaking
        if self._hearing:self._expire_hearing(self.clock())
        return self._hearing
    @hearing.setter
    def hearing(self,value):
        if self.tempo_live:
            if value:self._heard_locally=False      # the cloud hears them too: a ready cue is no longer held by the ear alone
            return
        self._hearing_end()
        if value:self._hearing=True;self._heard_at=self.clock()
    def _hearing_end(self):
        """The one place the cloud's flag of speech is lowered (an accepted final, the expiry, the lock of the portion matched, the ear taking the tempo): nothing else writes ``_hearing`` / ``_heard_at`` / ``_heard_locally`` down."""
        self._hearing=False;self._heard_at=None;self._heard_locally=False
    def _hearing_alive(self):
        """The one place a sign of speech (a transcript that grows, the transport's ear) keeps a flag that is set alive; one that is not set is not set by it."""
        if self._hearing:self._heard_at=self.clock()
    def _expire_hearing(self,now):
        """A start of speech that never became a transcript must not silence the call for good (DEF-FAULT-14, DEF-STATE-02,
        DEF-ACK-19): release it, and let the repeat timer run again when the portion is not being played just now (a parked cue
        is played by the transport and re-arms the timer when it ends). The silence counts from the instant the flag ran out,
        not from the moment somebody noticed (a tick or a read), so the repeat is not late however rarely that happens."""
        if not self._hearing or self._heard_at is None or now-self._heard_at<HEARING_SECONDS:return
        ran_out=self._heard_at+HEARING_SECONDS
        self._hearing_end()
        if not self._cue_playing(now) and self.repeat_at is None and self.engine.current(self.state())!=SILENT:
            self._arm(ran_out+self._silence().wait)
            # W1F-B (C4): a turn whose words have arrived but whose final has not (the provider took 4 s over « Кандса», sc01): when its
            # final comes and is speech the classifier cannot place, that final takes this timer back (``_accept_user``); a turn that never
            # ends keeps it (the call is never left listening for good).
            user=self.ledger.latest_user()
            if user and user['valid'] and not user['final'] and user['id'] not in self.seen and self._said_words(user['text']):
                self.expiry_armed_for=user['id']
        meter=getattr(self,'input_meter',None)
        logger.info('echo-sync decision kind=silent reason=hearing_released_without_transcript%s',(' input_state=%s unplaced=%s'%(meter.state(now),self.unplaced)) if meter is not None else '')
    def local_onset(self):
        """Task S0, ruling 2: the transport's own ear (local_ear.SpeechOnset) has heard the listener START to speak, before the cloud
        has said anything (it announces a turn 0.3-2.3 s after the speech began). The listener is heard from now on, as after the
        cloud's start of speech: the silence timer stops and a new cue waits. But nothing is cut: a cue that is playing goes on (only
        ``speech_started`` cuts one), so nothing is returned. Released like any other start of speech (HEARING_SECONDS)."""
        if self.tempo_live:return            # H3: there is one flag, the detector of the local ear
        self._expire_hearing(self.clock())   # a flag that has run out unnoticed is released first, as a tick would have
        local=self._heard_locally or not self._hearing   # a flag the cloud set stays the cloud's
        self.hearing=True;self._arm(None);self._heard_locally=local
    def local_speech(self):
        """The transport's ear still hears the listener: a flag that is set stays set (like a growing transcript). One that has been
        released (an accepted final, the expiry) is not set again: only a new start of speech does that."""
        if self.hearing:self._hearing_alive()
    def _input(self,now=None):
        """U17-S4: the input meter of this call (made at the first event; the repeat gate always obeys it, U17-S5)."""
        if self.input_probe is None:
            self.input_probe=self.input_meter=InputMeter(self.clock() if now is None else now)
        return self.input_probe
    def _input_feed(self,method,*args,now=None,**kw):
        """One guarded hook: the meter never costs the call anything."""
        try:
            meter=self._input(now)
            if meter is not None:getattr(meter,method)(self.clock() if now is None else now,*args,**kw)
        except Exception:logger.debug('echo-sync input meter failed',exc_info=True)    # noqa: BLE001
    def _lang_observe(self,turn):
        """U19-S3: the cloud's final of the listener's words says the language of the turn, one vote for each turn."""
        try:
            if turn.get('id') in self._lang_seen or not isinstance(turn.get('text'),str):return
            self._lang_seen[turn['id']]=self.turn_lang.observe(turn['text'])
            while len(self._lang_seen)>64:self._lang_seen.pop(next(iter(self._lang_seen)))
        except Exception:logger.debug('echo-sync lang observe failed',exc_info=True)    # noqa: BLE001
    def _ear_lang_gate(self,record):
        """U19-S3: runs first in each ear entry (``ear_heard``, ``ear_partial``, ``tempo_heard``), before the input meter. ``(record, gated)``. The ear is Russian: its text is no evidence when the turn is not Russian
        (the English ear is no rule: an English turn waits for the cloud's final) or when half its words or more are words it cannot know (``ear_foreign``). ``on``: a gated record has ``text=None`` and ``reason=ear_other_language``, and waits for the cloud's final;
        ``shadow``: only the line (numbers and labels, once for each utterance). A fault is no gate."""
        try:
            text=record.get('text') if isinstance(record,dict) else None
            if not isinstance(text,str) or not text.strip():return record,False
            lang=self.turn_lang.lang
            lex=self.ear_lexicon;known=(lambda word:True) if lex is None else (lex if callable(lex) else (lambda word:word in lex))
            c=lang_counts(text);why='turn_en' if lang!='ru' and c['ru']+c['en'] else 'ear_foreign' if ear_foreign(text,known) else None
            if why is None:return record,False
            uid=record.get('uid')
            if uid not in self._lang_logged:
                self._lang_logged[uid]=why;self.lang_gated+=1
                while len(self._lang_logged)>64:self._lang_logged.pop(next(iter(self._lang_logged)))
                logger.info('echo-sync lang_gate mode=on uid=%s why=%s turn=%s ru=%s en=%s',uid,why,lang,c['ru'],c['en'])
            return dict(record,text=None,reason=OTHER_LANGUAGE),True
        except Exception:
            logger.debug('echo-sync lang gate failed',exc_info=True)    # noqa: BLE001
            return record,False
    def _input_log(self,now):
        """U17-S4: the tick's line, numbers and labels only, when the state or the act changes."""
        meter=self.input_probe
        if meter is None:return
        try:
            act=meter.repeat_action(now);key=(act.state,act.act)
            if key!=self._input_logged:
                self._input_logged=key
                logger.info('echo-sync input_state state=%s act=%s got_s=%.2f duplex=%s',act.state,act.act,act.got_s,meter.duplex(now))
        except Exception:logger.debug('echo-sync input meter failed',exc_info=True)    # noqa: BLE001
    def _speech_start_ms(self,turn):
        """The listener's real speech start, in ms of the provider's input-audio clock, when the provider carries it and that clock is the
        one the transport counts (the turn's end can not be ahead of the audio that was sent); else ``None``."""
        start,end,sent=turn.get('start_ms'),turn.get('end_ms'),self.input_ms()
        if sent is None or type(start) not in (int,float):return None
        if type(end) in (int,float) and end>sent+INPUT_CLOCK_SLACK_MS:return None
        return start
    def input_changed(self,signature,now):
        """The transport reports the user's input changed (its signature: turn id and text): the clock of the quiet interval starts again. The one place that holds the time of the input; the transport only reports."""
        self.input_signature=signature;self.input_changed_at=now;self.quiet_checked=None
    def input_reset(self):
        self.input_signature=None;self.input_changed_at=None;self.quiet_checked=None
    def input_quiet_due(self,now):
        """Is the input unchanged for QUIET_INTERVAL_S and not yet looked at (once per signature)? The cm-tick rule of "the listener went quiet": the transport asks, ``partial_quiet`` observes."""
        if self.input_changed_at is None or now-self.input_changed_at<QUIET_INTERVAL_S or self.quiet_checked==self.input_signature:return False
        self.quiet_checked=self.input_signature
        return True
    def partial_quiet(self,*,now):
        """Observe a paused failed/partial attempt without accepting any ACK.

        The wire uses Conduit TurnAssembler's3s user-quiet interval. Raw
        provider-final remains false; a resumed phrase can still complete.
        """
        if self.reopened:return None
        user=self.ledger.latest_user();state=self.state()
        if not user or not user['valid'] or user['final'] or self.engine.current(state)==SILENT:return None
        decision=self._classify(user['text'],state)
        if decision.kind not in (QUIET,REPLAY):return None
        reason=self._effective_reason(user['text'],state,decision)
        self.hearing=False
        # W1F-B (C4): a stalled try at the portion runs the silence timer again; other speech is observed and nothing more. H3: the stall of a lagging transcript says nothing, the ear has said it all.
        if not self.tempo_live:
            self.resume_repeat=False
            if self._rearms(decision,reason,user['text']):self._arm(now+self._silence().wait)
        self._listener_acted(decision,reason,state,to_it=True)
        return user
    def _listener_acted(self,decision,reason,state,to_it=None):
        """The ONE effect of speech heard on the portion that waits, for a final (``_accept_user``) and for the quiet stall of a partial (``partial_quiet``): a confirmation, a command, a request, a try, a clarification
        is the listener working on the portion (``_tries``: never abandoned while they are at it, ``_engaged``; ``to_it`` None: a question or a correction is not said to it, H6 item 2); and the listener's own speech
        (not QUIET/GREETING, or a real try ``ATTEMPT_REASONS``) starts the count of automatic repeats again. Noise, a TV, a bystander and anything else the classifier keeps quiet about never does: the phone on a table in a room is not a listener."""
        if self._tries(decision,reason):self._engaged(state,to_it=decision.kind not in (QUESTION,CORRECTION) if to_it is None else to_it)
        if (decision.kind not in (QUIET,GREETING) or reason in ATTEMPT_REASONS) and not self._tempo_said_before():self.auto_repeats=0
    def _speech_end(self,qid,done_at=None):
        """W13 item 6: when the ear heard the speech of the question ``qid`` end (``ear_ended``), or None: no ear, or its last end is of an older utterance, or of one after the final."""
        ended,begun=self.ear_ended,self.user_started_at.get(qid)
        if type(ended) not in (int,float) or begun is None or ended<begun or (done_at is not None and ended>done_at):return None
        return ended
    def _holding(self,now):
        """Is the first cue of the answer held for the question's utterance (nothing is published yet)? The ONE wait for the rest of a question, on the model-knowledge route only, from two
        causes. (1) A question cut after a function word waits for a continuation while the coalescing window is open: it counts from the end of the user's turn (the same instant
        ``_continuation`` measures from) and goes on while a tail that began inside it is still being spoken and could still be merged (the seam of ``_goes_on``); both extensions are
        bounded: a turn the provider never closes cannot hold an answer for ever. (2) W1F-B (C2): any question waits while its utterance is still being spoken or corrected: while an opener
        said after it («Нет») waits for the correction it announces (``coalesce_seconds`` after its final), and while a user turn that began within ``coalesce_seconds`` of the utterance's last
        final is still being spoken and could still go on with it. Bounded: MERGE_PATIENCE_SECONDS past that window at most, and the answer cap (``_answer_watchdog``). A final of the listener
        alone never ends it: the hearing flag is not what holds it."""
        if not self.coalesce_seconds or not self.direct_content or self.published:return False
        words=norm_words(self.question_text);started=self.question_clock;seam=False
        if words and words[-1] in FUNCTION_WORDS and not probe('question_complete',self.question_text).value and started is not None:
            done_at=self.user_done_at.get(self.question_id);ended=self._speech_end(self.question_id,done_at)
            if done_at is None and ended is None:
                seam=now-started<=self.coalesce_seconds+MERGE_PATIENCE_SECONDS      # early delegation accepted the question while the user was still speaking: their window has not begun
            else:
                started=ended if ended is not None else max(started,done_at)      # W13 item 6 (s4#6 waited 3.29 s): from the end of the speech, not from the admission
                waited=now-started
                if waited<=self.coalesce_seconds:seam=True
                elif waited<=self.coalesce_seconds+MERGE_PATIENCE_SECONDS:
                    user=self.ledger.latest_user();begun=self.user_started_at.get(user['id']) if user else None
                    seam=bool(user and user['valid'] and not user['final'] and user['id']!=self.question_id
                              and begun is not None and within(begun,started,self.coalesce_seconds)
                              and (not norm_words(user['text']) or self._goes_on(user['text'],self._classify(user['text'],self.state()),False,seam=True)=='seam'))      # the same seam rule as the join of ``_continuation``: the tail so far still fits the cut head
        if seam and not ((self.ear_job or self.live_first) and self.tempo_live and self._utterance_over(self.question_text)):return True      # c16: the ear knows it is over («это одно и то же»)
        last=self._utterance_final()
        if last is None:return False
        if self._pieces() and now-last<=self.coalesce_seconds:return True
        if now-last>self.coalesce_seconds+MERGE_PATIENCE_SECONDS:return False
        if (self.ear_job or self.live_first) and self.job_asked and self.tempo_live and self._utterance_over(self.question_text) and self.job_asked(self.question_id):return False      # c16: the ear heard the speech end and the job all of it: an open turn of the cloud is a cut of what was said (n1_02 step 14 of c16-a: the right answer waited 1 s for « работодателя», and went)
        user=self.ledger.latest_user()
        if not user or not user['valid'] or user['final'] or user['id']==self.question_id:return False
        begun=self.user_started_at.get(user['id'])
        if begun is None or not within(begun,last,self.coalesce_seconds):return False
        return not self._said_words(user['text']) or self._goes_on(user['text'],self._classify(user['text'],self.state()),False) is not None      # a turn that has just begun may still go on; else as far as it has got, the rule of the join (``_goes_on``)
    def _note_early(self,tid,state,kind=ACK,piece=False,ear=None):
        """The stable partial of turn ``tid`` has just confirmed the portion that ``state`` waited for. R-EAR-ACT: or the local ear has taken
        the turn with its verdict ``kind`` (ACK, REPEAT, STOP or NEXT: ``_ear_family``); ``piece``: the turn is a later piece of the utterance
        the ear took (``ear_piece``), all of whose words come after what was decided, or ``'head'``: an earlier one, whose words are the
        take's own (fix round 1); ``ear``: what the ear's take knows of the utterance (``{'earlier': ids}``: the cloud's turns of it before
        this one, ``_ear_earlier``), None for the stable partial."""
        self.early_taken[tid]=(state,self.epoch,self.clock(),kind,piece,ear)
        while len(self.early_taken)>8:self.early_taken.pop(next(iter(self.early_taken)))
    def _tail_after(self,text,state,kind):
        """R-EAR-ACT: what the final ``text`` of a turn taken early says after the part already decided: after the portion that ``state`` waited for, for a confirmation - the shortest prefix (by words) that the same matcher accepts as the portion IS the portion, the rest is the tail, ``''`` when the whole final is the repeat («Статья семнадцать …» for «Статья 17 …»: no tail, nothing opens, W13 item 8, 1_#17, 3_#10) or the recognizer revised the words (where the portion ends is not known, nothing is guessed);
        after the command for a command - the shortest prefix (by words) the classifier gives the same verdict (``_ear_family``) is the command, the rest the tail. ``''`` when there is none: nothing is guessed."""
        tokens=str(text).split()
        if kind==ACK:
            portion=probe('waiting_portion',state=state).value
            if portion is None or self._classify(str(text),state).kind==ACK:return ''
            return (self._ack_prefix(text,state,portion) or (None,'',None))[1]
        for count in range(1,len(tokens)):
            if self._ear_family(self._classify(' '.join(tokens[:count]),state))==kind:return ' '.join(tokens[count:])
        return ''
    def _analyze(self,c,text,state):
        """U15-S1: every ``analyze`` the judge makes goes through here, so the number of them per final is known (``AcceptCtx.analyses``)."""
        return self._classify(text,state,c)
    def _classify(self,text,state,c=None,tid=None,settings=None,diagnose=False):
        """The one reading of a text by the classifier, and the only place where ``analyze`` is called for the judge: by a row (``c``, the final being judged) or ahead of the
        judge (``tid``: the delegation and the delegated final are evidence for it, ``_delegation_opens`` / ``_delegated_final_closes``). Every reading is counted in ``AcceptCtx.analyses`` of its final (U15-S1)."""
        if c is not None:c.analyses+=1
        elif tid is not None:
            self.reads_ahead[tid]=self.reads_ahead.get(tid,0)+1
            while len(self.reads_ahead)>8:self.reads_ahead.pop(next(iter(self.reads_ahead)))
        return probe('analyze',text,state=state,settings=self.settings if settings is None else settings,diagnose=diagnose).value
    def _delegation_opens(self,user):
        """The model delegated on a turn of the listener that is not taken yet (``_delegation``): the delegation is EVIDENCE that it is a question, the judge is who reads it. True when the judge reads the partial as a question or a
        correction and there is enough of it (three words, or a conversation behind it): the one threshold of a partial that a delegation makes a question."""
        state=self.state();decision=self._classify(user['text'],self._heard_with(state),tid=user['id'])
        enough=len(user['text'].split())>=PREPARE_MIN_WORDS or bool((state or {}).get('history'))
        return enough and decision.kind in (QUESTION,CORRECTION)
    def _delegated_final_closes(self,turn):
        """The final of a question the delegation opened on a partial said something else (``provider``): the judge says whether the question stands. It is closed when the final is neither a question nor a correction, unless the model's delegation
        is evidence by itself: a final the classifier has none for is a candidate the judge admits (Wave G, ``_take_candidate``)."""
        state=self.state();decision=self._classify(turn['text'],state,tid=turn['id'])
        return decision.kind not in (QUESTION,CORRECTION) and not (self.delegation_id and self._effective_reason(turn['text'],state,decision) in _NO_EVIDENCE)
    def _ruled(self,c,kind,reason,question,spoke):
        """The one place where a rule of the judge writes its verdict (kind, reason, the question it carries) and tells what it did: a rule is a row, not a new way to set the kind."""
        c.decision=command_ruling(kind,reason,question);c.spoke(spoke)      # command_ruling: the one builder of a verdict
    def _judge(self,c,take=False):
        """U15-S1 / M1: the verdict of one final: the ROWS of ``JUDGE_RULES`` (``utterance_judge.Rule``) run in their order, each reads and rewrites ``c``; a row that returns a verdict has it written and named here.
        U15-S11: the rows stop at the first one that spoke with a verdict (first match by priority, the only order). The rows marked ``after`` (the feature ``going_on`` and the veto ``not_addressed``, U15-S9) run after the table.
        What a row does besides the verdict (the tempo's help, the flags of a suspended plan) stays in the row, in its place. A new row is a new ``Rule`` in the table: this walker is not edited for it."""
        c.cm=self;table=judge_table.JUDGE_RULES      # read at the walk: the table is the one in ``utterance_judge``
        if take:      # the first stage: the rows that take a final whole in front of its bookkeeping (``Rule.first``); no verdict is made here
            for rule in table:
                if rule.first:
                    self._run_row(rule,c)
                    if c.taken is not None:break
            return c
        for rule in table:
            if rule.after or rule.first:continue
            if first_match(c) is not None:break      # first match: a row has spoken with a verdict, the later ones do not run
            self._run_row(rule,c)
            if rule.name=='recall' and c.decision is not None:return c      # U14-S6: a recall is the verdict; no other row looks at it
            if c.actions is not None:return c      # a row has taken the actions of this final (``early_tail``): it is settled, no verdict is made of it
            if c.taken is not None:return c      # a row took the final whole: the verdict is its actions, no other row looks at it
        step=first_match(c)
        if step is not None and c.decision is not None and (c.decision.kind,c.decision.reason)!=(step[1].kind,step[1].reason):
            rule,c.decision,c.text,c.turn,c.state,c.pieces=step;c.chain=c.chain[:c.chain.index(rule)+1] if rule in c.chain else c.chain[:1]      # the first row that spoke stands (a later row that changed no kind keeps its text)
        for rule in table:
            if rule.after:self._run_row(rule,c)
        return c
    def _run_row(self,rule,c):
        """One row: ``fn(c)`` may return a verdict (``Decision``): it becomes the verdict of the final and the row is named for it, as a row that rewrites ``c`` and ``spoke``s itself."""
        verdict=rule.fn(c)
        if verdict is not None:c.decision=verdict;c.spoke(rule.name)
    def _rule_own_voice(self,c):
        """The one place that says a final may be our own cue heard back (the witness of the cue's window and the listener's speech start): a feature of the verdict, not a verdict: it is a witness and never a drop (a fast listener repeats INSIDE the cue).
        The witness (never a drop: the iPhone cancels our playback and a fast listener repeats INSIDE the cue): only a cue that has really begun to be played can be heard back, and a turn whose speech began before it started was not a reaction to it. ``speech_start``: the listener's real speech start fell inside the span of the cue's audio (first frame .. last voiced sample + margin), on the input-audio clock; ``announcement``: the start is unknown, the provider announced the turn inside the window but not sooner than ECHO_MIN_LAG_SECONDS after the cue's first audio.
        DEF-ACK-20: the words of the portion, spoken while the portion itself was being played: possibly our own voice heard back. The decision stands and is kept for calibration (the lag is what a real device will tell), the repeat counts; ``_accept_user`` reads ``c.evidence``."""
        c.evidence=None
        window=self.cue_window
        if not c.tail and window and self.cue_heard:      # the witness of the cue's window and the listener's speech start (it was ``_own_voice_evidence``: its one caller)
            turn=self.ledger.snapshot(c.tid)
            start=self._speech_start_ms(turn) if turn else None
            if start is not None and self.cue_input_ms is not None:
                c.evidence='speech_start' if self.cue_input_ms<=start<=self.cue_input_ms+(window[1]-window[0])*1000 else None
            else:
                announced=self.announced_at.get(c.tid)
                c.evidence='announcement' if announced is not None and window[0]+ECHO_MIN_LAG_SECONDS<=announced<=window[1] else None
        if c.decision is not None and c.decision.kind==ACK and c.evidence is not None:
            announced=self.announced_at.get(c.tid)
            lag='%.2f'%(announced-self.cue_window[0]) if announced is not None and self.cue_window else 'unknown'
            logger.info('echo-sync decision kind=ack reason=own_voice_suspect evidence=%s announced_after_first_audio=%s revision=%s index=%s',
                        c.evidence,lag,(c.state or {}).get('revision'),(c.state or {}).get('chunk_index'))
    def _rule_recall(self,c):
        """U14-S6 (the ledger is always there): «повтори мои последние 20 слов» of a final runs before every other rule: the verdict is a question whose
        local answer (``c.local``) is the verbatim words, opened by ``_open_question(local=...)``. Nothing to repeat, or no recall: the other rules judge it."""
        if self.convo is None or not c.turn.get('final') or c.tail or c.utterance or c.early:return
        words=self._recall_opens(c.text,c.tid)
        if not words:return
        c.local=' '.join(words);self._ruled(c,QUESTION,'recall',c.text,'recall')
        logger.info('echo-sync recall tid=%s words=%s',c.tid,len(words))
    def _recall_opens(self,text,tid=None):
        """U14-S6: the verbatim words of a recall command (``recall.parse``) from the ledger, the command's own final left out; [] when ``text`` is none."""
        try:
            found=recall_parse(text)
            return recall_resolve(self.convo,found,skip=tid) if found else []
        except Exception:      # noqa: BLE001 - a recall that cannot be read is no recall, the other rules judge the final
            logger.debug('echo-sync recall failed',exc_info=True);return []
    def _rule_try_final(self,c):
        """g17: the cloud's final of a try the ear went on from is that try, taken and nothing more (``_try_final``)."""
        if not c.tail and not c.utterance and self._try_final(c.turn):c.taken=[]
    def _rule_head_repeat(self,c):
        """Rule 2: a final that repeats the waiting portion and goes on with other words is the repeat confirmed once and its tail judged alone (``_repeat_and_tail``). The text is first said as the portion is written (``_said_as_written``); that text is the final's from here on."""
        if c.boundary!='provider_turn_done' or c.tail or c.utterance:return
        state=self.state();c.turn={**c.turn,'text':self._said_as_written(c.turn['text'],state)};c.text=c.turn['text']
        head=self._aligned_head(c.text,state)
        if head and not self._disputes(c.text,state) and not (self._own_number(c.text,state) and self._bank_asks(c.text,state)):c.taken=self._repeat_and_tail(c.turn,head)
    def _rule_speech_opens(self,c):
        """The final opens the prepared speech (a command to begin, or the first words of the text, with nothing in play): the speech is the plan, and it is the whole of what this final does."""
        if not (c.tail or c.utterance) and self._speech_begins(c.text,c.state):c.taken=self._speech_opens(c.turn)
    def _rule_plan_back(self,c):
        """Rule 5: the words said to the plan an admission took over (``suspended``) bring it back and drop the intruder (``_take_back``); the final is then judged on it by the redo of ``_accept_user``."""
        if self.suspended and not (c.tail or c.utterance):
            back=self._take_back(c.turn,c.state,c.boundary)
            if back or (back is not None and not self.fast_call):c.taken=back      # H6 item 5: a stopped plan comes back with nothing said: the listener is still told
    def _rule_ear_number_veto(self,c):
        """c9-numveto: the cloud confirms the portion, but the local ear heard ANOTHER number in the same utterance (``_ear_number_veto``): the utterance is judged as the ear heard it - a try at the portion, which stays -
        and the cloud's confirmation does not advance. The going on of the new verdict is worked out by the row after this one."""
        if c.decision.kind!=ACK or c.tail or c.utterance or c.boundary=='local_ear':return
        heard=self._ear_safely(self._ear_number_veto,c.tid,c.state)
        if heard is None:
            self.cloud_acks[c.tid]=(c.state,self.epoch,self.clock())
            while len(self.cloud_acks)>8:self.cloud_acks.pop(next(iter(self.cloud_acks)))
            return
        logger.info('echo-sync decision kind=silent reason=local_ear_number_veto boundary=%s revision=%s index=%s',c.boundary,(c.state or {}).get('revision'),(c.state or {}).get('chunk_index'))
        c.text=heard;c.turn={**c.turn,'text':heard};c.decision=self._analyze(c,heard,self._heard_with(c.state));c.spoke('ear_number_veto')
    def _rule_held(self,c):
        """What the verdict says of the step of this final (``c.hold``), not of its kind: a stop the cloud gave a final while the ear hears the rest of the speech waits for the ear's silence (H6 item 5); a repeat said after a newer question
        the ear heard is nobody's, the older plan said again is an old answer (c25-a G1). ``_accept_user`` carries it out where it stood."""
        decision=c.decision;c.hold=None
        if decision.kind==STOP and c.boundary=='provider_turn_done' and not c.tail and self._speech_goes_on():c.hold='stop_waits'
        elif decision.kind==REPEAT and not c.tail and self._overtaken('repeat',state=c.state):c.hold='repeat_waits'
    def _rule_base(self,c):
        c.decision=self._analyze(c,c.text,self._heard_with(c.state))
        self.dictating.heard(c.decision.reason)      # c22-repeat: «диктуй медленно» / «хватит диктовать»
    def _rule_long_talk(self,c):
        # H5 item 6: the whole of a question the classifier never saw a form in (the job admitted its head, or declined it while the breath went on) is still a question: it goes to the job, or the head's answer stands.
        # B: a long remark is talk, and no question stands in it - unless one stands in its LAST words (``asked_tail``: a count of words, ``ASK_TAIL_WORDS``): that question is asked, and it is the one that goes to the
        # bank, the sum and the job. The kind is decided here and nowhere after: the engine carries the verdict out.
        if c.decision.kind==QUESTION and self._long_talk(c.text,c.state):
            tail=asked_tail(c.text)
            if tail:
                c.decision=c.decision._replace(question=tail)
                logger.info('echo-sync judge_tail words=%s tail=%s',len(c.text.split()),len(tail.split()))      # no `spoke`: the later rules judge it as any question
            else:self._ruled(c,QUIET,'long_talk',c.text,'long_talk')
    def _rule_doubt(self,c):
        if c.decision.kind==QUESTION and c.decision.reason=='question_word' and not (c.tail or c.utterance) and doubtful_what(c.text,probe('waiting_portion',state=c.state).value is not None):      # U47/U59: doubt does not break, nothing opens, the portion stays
            self._ruled(c,QUIET,'doubt_what',None,'doubt')
        elif c.decision.kind==QUESTION and c.decision.reason=='question_word' and not (c.tail or c.utterance) and self._disputes(c.text,c.state) and self._doubts_the_answer(c.text):
            c.decision=command_ruling(QUIET,'doubt_of_the_answer',None)      # E44 «Ты уверена, что в 988 году»: the same doubt, its «что» no question; only where ``_rule_dispute`` takes it (``_disputes``: a portion waits); the row does not speak: ``_rule_dispute`` after it hands the doubt of the portion to the job; with no portion waiting it stays a QUESTION (``_doubt_held`` gives the confirmation)
        elif c.decision.kind==QUESTION and c.decision.reason=='question_word' and not (c.tail or c.utterance) and self._said_in_own_words(c.text,c.state):
            self._ruled(c,QUIET,'portion_said_in_own_words',None,'doubt')
    def _said_in_own_words(self,text,state):
        """«так что …» said while a portion waits: its «что» is a conjunction, the words are the portion's own."""
        portion=probe('waiting_portion',state=state).value
        if portion is None: return False
        words=list(norm_words(text))
        if words[:2]!=['так','что']: return False
        rest=words[2:]
        if not rest or frozenset(rest)&QUESTION_WORDS or rest[0] in _THAT_STANDS_ALONE: return False      # «так что такое / значит / за …»: its «что» asks what the thing is, whose words the portion happens to hold
        own={stem(word) for word in norm_words(portion)}
        return sum(stem(word) in own for word in rest)*2>=len(rest)

    def _doubts_the_answer(self, text):
        play=self.fast_in_play()      # the answer in play, as ``_doubt_held`` (item 7) reads it: a word of doubt and no subject of its own
        return bool(play) and of_the_answer(text,play[1],play[0])
    def _rule_going_on(self,c):
        """B: going on as a feature of the verdict (CL2 ruling 4 + amendment A): ``c.going`` is ``(plan, target)`` of ``engine.going_on`` for a NEXT, a RESUME, a topic change or a «повтори» of an abandoned portion, else None. The kind stays what the
        verdict says: the steps after the judge read it as it is (``_going_on`` rewrites it for the one that goes on)."""
        decision,state=c.decision,c.state
        c.going=None
        if decision is None:return
        if decision.kind in (RESUME,NEXT) or decision.reason=='topic_change' or (decision.kind==REPEAT and (state or {}).get('abandoned') is not None):
            plan,target=judge_table.going_plan(self.engine,state,decision,heard='reopened' if self.reopened else self._heard_after(c.turn,state,timed=True))      # the engine decides what the listener's «дальше» does with what he has heard (present / presented / skip); here only the facts
            if plan is not None:c.going=(plan,target)
    def _admitted_decision(self,text):
        """The one builder of the verdict of an admission by the cloud's evidence (the judge's row and ``_admit``): a question with the words stripped of fillers."""
        return Decision(QUESTION,'cloud_admitted',probe('strip_fillers',text,settings=self.settings).value or text,None)
    def _rule_cloud_admitted(self,c):
        if (c.utterance or c.admitted) and self.fast_on and c.decision.kind==QUIET and c.decision.reason!='long_talk' and not self._said_back(c.text,grown=c.utterance):
            c.decision=self._admitted_decision(c.text);c.spoke('cloud_admitted')      # c16 ``admitted``: the job prepared on these words has answered them (``_ear_first_ready``), as ``_fast_verdict`` is told after a final
    def _rule_tempo_help(self,c):
        decision,state,text,disputed=c.decision,c.state,c.text,c.disputed
        if self.tempo_live and decision.kind in (QUIET,REPLAY) and not disputed and probe('waiting_portion',state=state).value is not None and not state.get('paused'):      # the final says what the ear lost: the same rule
            said=probe('strip_fillers',text,settings=self.settings).value
            before=self.tempo_began is not None and self.cue_window and self.tempo_began<self.cue_window[0] and self.tempo_began_at!=self._position(state)      # c23 (P03): speech begun before this cue was said: its late final is no try at it (fuzz seed 286); c24: unless that cue is this very portion again (the ear's help or replay for this speech: half_hour seed 4 @1667)
            over=self.tempo_began is None or self._tempo_over(self.tempo_began)
            if before or landmark_command(said):pass      # c24-c: a landmark is the ear's to place (``_tempo_verdict``), its final is no try
            elif self.dictation and not over:pass      # c24-c: dictating, the owner speaks after the cue, never over it: words begun over a cue that played on may be that cue heard back (the ear's own rule, ``_tempo_heard``)
            elif (most_said(said,probe('waiting_portion',state=state).value) and not self._started(text,probe('waiting_portion',state=state).value)) or ends_like(said,probe('waiting_portion',state=state).value):self.go_on=self._position(state)      # a clean start that stopped has its own help
            elif rule_verdict(said,probe('waiting_portion',state=state).value)=='next':self.go_on=self._position(state)      # c22-repeat: the owner's rule, what the ear lost; c23: never a late final of speech begun before this cue was said (P03: «Осталось 20 рублей» of the cue before is not the last word of «Не хватает 20 рублей»)
    def _rule_dispute(self,c):
        """H6 item 4 (N6): a final that disputes the portion that waits (``_disputes``) is QUIET for the job, and ``c.disputed`` tells the rows after it (``tempo_help``, ``joined_repeat``) that it is no try. One row: the flag and the ruling."""
        c.disputed=not (c.tail or c.utterance) and c.decision.kind in (ACK,QUIET,QUESTION) and self._disputes(c.text,c.state)
        if c.disputed:self._ruled(c,QUIET,'dispute_of_the_portion',None,'dispute')
    def _rule_landmark_said(self,c):
        if not (c.tail or c.utterance) and c.decision.kind in (QUIET,QUESTION,REPLAY) and self._landmark_said(c.text,c.state):self._ruled(c,QUIET,'landmark_said',None,'landmark_said')      # c24-c: the ear places it (``_tempo_verdict``); nothing for a job
    def _rule_gate_talk(self,c):
        # w8-admission (N23, N32, E08): «Миша, ты зарядку не видел?» has a question mark and is said to a person: the text gate keeps it quiet, nothing opens.
        if c.decision.kind==QUESTION and not (c.tail or c.utterance) and self._gate_talk(c.text) and not c.gated:self._ruled(c,QUIET,'gate_talk',None,'gate_talk')      # E41: an early/cloud-admitted question still needs the recipient verdict
    def _gate_talk(self,text):
        """w8-admission, M1: the text gate (gate_text.py) says «talk»: silence without a job. Only a talk said to one person or the room (``talk_without_flag``) keeps a question quiet; a statement, noise and a question to «вы» are the job's to judge: «question» and «unknown» change nothing.
        What it weighs: the answer in play (its question, the answer), then the quiet finals since, oldest first; two finals after the answer put it out of play."""
        pieces=[{'text':piece[1],'kind':'speech'} for piece in self.quiet_pieces if piece[1]!=text][-2:]
        played=self.fast_in_play() if self.fast_on else None
        verdict=gate_decide(text,([{'text':played[0],'kind':'speech'},{'text':played[1],'kind':'answer'}] if played and played[1] else [])+pieces)
        talk=verdict.kind==GATE_TALK and talk_without_flag(text,verdict)
        if talk:logger.info('echo-sync gate_text kind=talk reason=%s',verdict.reason)
        return talk
    def _rule_read_again(self,c):
        """The question in play read again is no new question, one row for both forms of it: c24-c, the question alone: the portion in hand again, no new answer (the engine is given the command ``REPEAT_SAID``); g28, the question read again and the cue said back in one final: the cue's repeat, the rest is judged alone."""
        if c.decision.kind!=QUESTION or c.tail or c.utterance:return
        state=c.state
        if self._read_again(c.text,state):
            logger.info('echo-sync decision kind=repeat reason=question_read_again revision=%s index=%s',(state or {}).get('revision'),(state or {}).get('chunk_index'))
            said=REPEAT_SAID
        elif (said:=self._question_said_back(c.text)) is not None:
            logger.info('echo-sync decision kind=silent reason=question_said_back revision=%s',(state or {}).get('revision'))
        else:return
        c.text=said;c.turn={**c.turn,'text':said};c.decision=self._analyze(c,said,self._heard_with(state));c.spoke('read_again')
    def _rule_past_the_veto(self,c):
        if c.decision.kind!=ACK and not c.tail and not c.utterance:
            stepped=self._past_the_veto(c.tid,c.text,c.state)
            if stepped is not None:c.state,c.decision=stepped;c.spoke('past_the_veto')
    def _rule_not_addressed(self,c):
        """U15-S9 (``addressed_gate``): a question that is the cues read aloud, or long talk with no ask feature, is not addressed to us: QUIET, listened to, no job."""
        if c.decision.kind!=QUESTION or c.tail or c.utterance:return
        found=not_addressed(c.text,self._read_sources(c))
        if not found:return
        logger.info('echo-sync addressed_gate witness=%s share=%s',found[0],'%.2f'%found[1] if found[1] is not None else '-')
        self._ruled(c,QUIET,'not_addressed',None,'not_addressed')
    def _read_sources(self,c):
        """U15-S9: what may be read aloud: the cues played within ``CONTEXT_AGE_S``, the plan in play, the listener's earlier finals within ``READ_USER_WINDOW_S``."""
        now=self.clock();sources=[text for at,text,cue in self.said_log if cue and now-at<=CONTEXT_AGE_S]+self._plan_said()
        mine=self.ledger.snapshot(c.tid) or {};start=mine.get('start_ms')
        if type(start) in (int,float):
            sources+=[t['text'] for t in self.ledger.history() if t['role']=='user' and t['final'] and t['id']!=c.tid and type(t.get('end_ms')) in (int,float) and 0<=start-t['end_ms']<=READ_USER_WINDOW_S*1000]
        return sources
    def _bank_asks(self,text,state):
        """g1-ladder L1 (seed 103: «Проводка: перечислили зарплату с расчётного счёта.» while «Счета, собирающие затраты:» waited, one stem shared): a row of the bank, its whole form
        (not a ranked guess), is a question however it is said, unless it is the answer that is on or its words are mostly the portion's (a repeat stays a repeat)."""
        if self.instant is None:return False
        try:
            found=self.instant._match(' '.join(str(text or '').split()),self.clock(),True,adapters=False)
        except Exception:return False
        if not found or found[0].kind!='bank':return False       # h28: a ranked hit counts too: «Так, нет, перечисли название видов…» went silent over an open portion while the cloud timed out; «can I answer it» is the test of a question, not its form
        plan=' '.join((state or {}).get('chunks') or ())
        if plan and normalize(found[0].answer).startswith(normalize(plan)[:40]):return False
        portion=set(norm_words(probe('waiting_portion',state=state).value or ''));said=norm_words(text)
        whole=set(norm_words(' '.join((state or {}).get('chunks') or ())))      # h28: words of any part of the answer on, not only the portion: said ahead is an attempt, not a question
        return bool(said) and (self._own_number(text,state) or sum(word in portion or word in whole for word in said)*2<len(said))      # h29: words in common do not outweigh a number of its own
    # ---- G3: the arbiter over the ledger, the revision and the cursor -------------------------------------------------------------------------------
    # Local strong evidence decides at once: a repeat, a command, a try at the portion. A repeat that goes on with new words is split (``_aligned_head``).
    # A final the classifier has no evidence for leaves the plan alone until the cloud shows that it was a question (``_take_candidate``: the reference base,
    # its delegation, a reply of substance bound to this turn). A question the classifier sees opens at once (its lookup must not wait for the cloud's
    # filler), but neither it nor an admission retires the plan for good: the history entry keeps it (``suspended``). The listener's next words at its portion
    # take it back and drop the intruder (``_take_back``), and a question nobody answers gives it back (``_plan_after_decline``, the watchdog): a wrong
    # admission costs one whisper, not the position.

    def _open_to_the_cloud(self,text,reason,state):
        """Rule 4: may this QUIET final be a question the classifier could not see? It has no evidence either way (a paused answer takes none of those: its
        plan is held on purpose), or it says «не X, а Y» whatever it shares with the portion. Not when it names the prompter (a remark), nor when it is a late
        try at the portion just finished (rule 6: a repeat never generates). H2 (rule 2): with the text channel on the job judges every such final and the words of a remark."""
        corrects=probe('not_this_but',text).value
        if reason=='gate_talk' or self._gate_talk(text):return False      # w8-admission: no job is spent on talk
        if self.fast_on:wants=(reason in _FOR_THE_BRAIN or (corrects and reason in ATTEMPT_REASONS)) and (bool(_content(text)) or doubts(text))
        else:wants=((reason in _NO_EVIDENCE and not (state or {}).get('paused')) or (corrects and (reason in _NO_EVIDENCE or reason in ATTEMPT_REASONS))) and bool(_content(text)) and 'суфлер' not in norm_words(text)
        return wants and not self._late_try(text,state)
    def _late_try(self,text,state):
        """Is ``text`` said of the last portion of the answer that has just been finished? Nothing waits, so the classifier has no portion to weigh it on."""
        chunks=(state or {}).get('chunks') or []
        if not chunks or not state.get('completed') or state.get('pending_turn'):return False
        probe={**state,'completed':False,'chunk_index':len(chunks)-1}
        if self._disputes(text,probe):return False
        decision=self._classify(text,probe)
        return decision.kind==ACK or self._effective_reason(text,probe,decision) in ATTEMPT_REASONS
    def _no_to_the_cue(self,text,began,state):
        """c25-a (the owner's live call: «нет» right after a cue, the repeats went on to the cap while the model talked to the other person): is ``text`` a short
        rejection («нет», «нет, не то», «неправильно») begun during the cue or at most NO_AFTER_CUE_SECONDS after its end? Not when the portion itself opens with
        a negation: «Нет.» to «Нет, земля не амортизируется.» is a try at it, an answer of substance."""
        portion=probe('waiting_portion',state=state).value
        if portion is None or not self.fast_on or not self.cue_window or began is None or state.get('paused'):return False
        words=self._said_words(text)
        if not words or len(words)>4 or not set(words)<=_NO_WORDS or words[0] not in _NO_HEADS:return False
        if len(set(words))>1 and not set(words)&_NO_REAL:return False      # h31: «нет, это так» says the opposite
        if norm_words(portion)[:1] and norm_words(portion)[0] in _NO_HEADS:return False
        return self.auto_repeats<=1 and self.cue_window[0]<=began<=self.cue_window[1]+NO_AFTER_CUE_SECONDS      # h31: the cycle repeats every second: the window of the cue itself, not of all its repeats
    def _no_taken(self,state):
        """c25-a: the portion rejected: the model is asked for another. h31: the portion is held, not taken away: an answer replaces it, and with none it is said again: «нет» never leaves the owner with nothing."""
        self.tempo_hold=None;self._tempo_arm(self.clock()+ANSWER_WAIT_SECONDS)      # h31: the model's time to give another answer before the portion is said again is the wait for an answer
        logger.info('echo-sync decision kind=silent reason=no_after_the_cue revision=%s index=%s',state.get('revision'),state.get('chunk_index'))
    def _disputes(self,text,state):
        """H6 item 4 (N6: «Нет, год вы назвали неверный», «<порция>, ты уверена», «Нет, <порция>, это неверно»): is ``text`` no try at the portion that waits but a dispute of it, for the job? What it says beyond the portion's words holds
        a doubt, or it opens with a negation the portion does not have and says less than half of it. A self-correction that ends on the portion is a repeat, and so is a confirmation tag («…, да?»). With the channel off nobody judges a dispute."""
        portion=probe('waiting_portion',state=state).value
        if not self.fast_on or portion is None:return False
        said=self._said_words(text);corrected=probe('self_corrected',text).value;fillers=resolve(self.settings)['fillers']
        if not said or (corrected and match_current(corrected[1],portion,fillers,lenient=False)=='ack'):return False
        own={stem(word) for word in norm_words(portion)}
        extra=[word for word in said if stem(word) not in own]
        if len(extra)==1 and is_confirmation_tag(extra,frozenset(fillers)|HESITATION_WORDS):return False
        heard=norm_words(text);heard=heard[:len(heard)//2] if len(heard)>=2 and len(heard)%2==0 and heard[:len(heard)//2]==heard[len(heard)//2:] else heard      # «не слышу, не слышу»: one request said twice
        if len(extra)==len(said) and (is_repeat_request(heard,frozenset(fillers)|HESITATION_WORDS) or hearing_repair(heard,frozenset(fillers)|HESITATION_WORDS)):return False      # g25: «не слышу», «не расслышал»: a request to hear it again, no dispute
        if doubts(' '.join(extra)):return True
        if said[0] in own or said[0] not in ('нет','не'):return False
        numbers=lambda words:{atom for atom in self._protected_atoms(words)[0] if atom.startswith('#')}
        whole=len(_stems(portion))+len(numbers(portion))
        share=len(_stems(text)&_stems(portion))+len(numbers(text)&numbers(portion))
        return said[0]=='не' or share*2<whole
    def _aligned_head(self,text,state):
        """F9: ``_aligned_head_in`` for the waiting portion, and for the tail that was cued and began to play: the listener repeats it and goes on."""
        head=self._aligned_head_in(text,state)
        tail=self.engine.tail_of(state)
        if head or not tail:return head
        position=self._position(state)
        if position is None or tail[0]!=position or not tail[2]:return None
        chunks=list(state['chunks']);chunks[state['chunk_index']]=tail[1]
        return self._aligned_head_in(text,{**state,'chunks':chunks})
    def _aligned_head_in(self,text,state):
        """Rule 2: the words of ``text`` that repeat the waiting portion, when it goes on with others after them: the shortest prefix the matcher confirms
        as the portion, word for word (a word the lenient rule would forgive may be the one the rest replaces: «… все покупки» for «… покупки»); else None (a
        plain repeat, or no repeat at all). What goes on with protected words is no repeat (rule 1, R2a): words that negate or invert it («… но это не так»)
        unless they ask something, a bare number, or a number after a portion that ends in a number («двадцать» | «пять» is 25, not 20)."""
        portion=probe('waiting_portion',state=state).value
        if portion is None:return None
        found=self._ack_prefix(text,state,portion)
        if found is None:return None
        head,rest,verdict=found;words=norm_words(rest)
        if verdict.reason!='ack_after_lead_in' and match_current(head,portion,resolve(self.settings)['fillers'],lenient=False)!='ack':return None
        if not words:return None
        number=words[0].isdigit() or words[0] in NUMBER_WORDS
        if number and (len(words)<=2 or self._may_still_grow(portion)):return None
        if _INVERTS.intersection(words) and self._classify(rest,state).kind!=QUESTION:return None
        return head
    def _ack_prefix(self,text,state,portion):
        """The one search of the words a listener said ahead of the rest: the shortest prefix of ``text`` (by words; at most the portion's words and ``attempt_extra_words`` more) that the classifier takes as the portion ``state`` waits for, as ``(head, rest, its verdict)``; else None. ``_tail_after`` (the rest of a turn taken early) and ``_aligned_head_in`` (rule 2) are its two readers."""
        tokens=str(text).split()
        for count in range(1,min(len(tokens),len(portion.split())+resolve(self.settings)['attempt_extra_words']+1)):
            head=' '.join(tokens[:count]);verdict=self._classify(head,state)
            if verdict.kind==ACK:return head,' '.join(tokens[count:]),verdict
        return None
    def _said_as_written(self,text,state):
        """H2 rule 5: ``text`` as the waiting portion or without the preposition in front of it, when that is what stands between it and a repeat. The job writes numbers in digits and
        answers in the form of the question: «988 году.» is said «в девятьсот восемьдесят восьмом году», «С 1941 по 1945 год.» with two ordinals. Numbers still by value, every word as
        always, and a portion that has its preposition is held to it. Anything else stays what it is."""
        portion=probe('waiting_portion',state=state).value
        if not self.fast_on or portion is None:return text
        lead=_LEAD_PREPOSITION.match(text)
        bare=text[lead.end():] if lead and lead.group(1).casefold()!=next(iter(norm_words(portion)),'') else text
        if _by_value(bare)==_by_value(portion):return portion
        if bare!=text and (self._classify(bare,state).kind==ACK or self._aligned_head(bare,state)):return bare
        return text
    def _walk_start(self,portion,words):
        """Rule 3, the strict walk of ``_started``: how far the already told words (``words``: fillers and stalls taken out) got in ``portion``: ``(the rest of the portion, whether words were said twice)``, or None when it is no clean start of it. The finals of the cloud are read as the ear's text is (F1):
        ONE reader, ``_started`` (a hesitation or a filler anywhere, numbers by value, the portion's own opening filler ("и", "а", "ну"), the words people lean on (F5)); this is its inner step."""
        portion=str(portion);marks=list(WORDS.finditer(portion));parts=[(stem(part),index) for index,mark in enumerate(marks) for part in _HYPHENS.split(normalize(mark.group())) if part];own=[part for part,_ in parts]
        lemmas=[_lemma(part) for mark in marks for part in _HYPHENS.split(normalize(mark.group())) if part]       # F10: the same word in another case has another stem («подпись» | «подписи»), never another lemma
        at=0;twice=False;again=None       # G26: ``again``: where a restart has got to, while it is behind ``at`` («сортировка по … сортировка по»: the second «по» is the restart's, not the «по» further on)
        raws=[part for mark in marks for part in _HYPHENS.split(normalize(mark.group())) if part];heard=[part for word in words for part in _HYPHENS.split(word) if part]
        for position,raw in enumerate(heard):
            lemma=_lemma(raw);part=stem(raw)
            if again is not None and again<at and (part==own[again] or lemma==lemmas[again]):
                again+=1
                continue
            again=None
            if not at and own and part!=own[0] and own[0] in _OPTIONAL_STEMS:at=1       # F4: the opening «и», «а», «ну» of the portion may be left out
            if at<len(own) and (part==own[at] or lemma==lemmas[at]):
                if position==len(heard)-1 and lemma!=lemmas[at] and raws[at].replace('ё','е').startswith(raw.replace('ё','е')) and len(raws[at])-len(raw)>=2 and raw not in _ABBREVIATIONS and raw not in _UNITS:break       # F11: a word cut off is the word they are on, not a word said («это» of «этого», «пот» of «потом»): the stem is the same; another FORM of the word («миллион» of «миллионов») is a word said
                at+=1
            elif part in own[:at] or lemma in lemmas[:at]:
                if position==len(heard)-1 and raw in raws[at+1:] and raw not in raws[:at]:return None      # c23 (walk 43): «счетов» of «Счёт 68.90 в рабочем плане счетов» is the word ahead, a word skipped, no restart of «Счёт»
                twice=True;again=max(index for index in range(at) if own[index]==part or lemmas[index]==lemma)+1
            else:return None
        if not 0<at<len(own):return None
        spot=parts[at][1]       # the word of the first part not said: «из» of «из-за» is not «из-за» said
        while spot and number_goes_on(marks[spot-1].group(),portion[marks[spot-1].end():marks[spot].start()],marks[spot].group()):spot-=1       # F2: a number is cued whole: never «000 километров», «6 градуса»
        begin=marks[spot].start() if spot else 0
        while begin and portion[begin-1] in '«"„“(\'':begin-=1      # G26: the opening quote goes with its word («дебет» of «Слово «дебет» …»)
        return (portion[begin:],twice) if spot else None
    @staticmethod
    def _heard_words(text,portion):
        """F5: the words of ``text`` without what people lean on while they look for the next one («значит», «типа», «как бы», «в общем», «это самое»), unless the portion has those words itself. F6: «13%» is «13 процентов» when the portion says it with a word."""
        held=normalize(portion);text=str(text)
        if '%' in text and '%' not in str(portion) and 'процент' in held:text=re.sub(r'\s*%',' процентов',text)       # F6
        said=_STALLS.sub(lambda hit:hit.group() if re.search(r'(?<![\w-])'+re.escape(hit.group())+r'(?![\w-])',held) else ' ',normalize(text))
        return said.split()
    def _stuck(self,text,state,tried):
        """Rule 3: the listener is stuck on a start of the portion: the same words twice, or the same start again. Only what is missing is cued."""
        portion=probe('waiting_portion',state=state).value
        found=self._started(text,portion) if portion and not state.get('paused') and not self.tempo_live else None     # H3: the ear has said this, seconds ago (``_tempo_heard``)
        if not found:return []
        before=self._started(tried[-1],portion) if tried else None
        if not found[1] and not (before and before[0]==found[0]):return []
        logger.info('echo-sync decision kind=replay reason=missing_tail revision=%s index=%s',state.get('revision'),state.get('chunk_index'))
        self._cue_tail(self._position(state),found[0])
        return self._cue(found[0])
    def _said_wrong(self,turn,state):
        """Rule 1: a whole try at the portion that is not the portion (a number, a «не», a term): it stays, and it is said again WRONG_REPEAT_SECONDS after the
        final, not after the whole silence. Only a try as long as the portion: a shorter one is a listener who has stopped (``_stuck``, the silence timer).
        True when so. Not in the tick of the final: S6 and the T suite pin that a wrong final speaks nothing (see WRONG_REPEAT_SECONDS)."""
        portion=probe('waiting_portion',state=state).value
        if portion is None or state.get('paused') or self._started(turn['text'],portion):return False
        if len(self._said_words(turn['text']))<len(norm_words(portion)):return False
        if len(_stems(turn['text'])&_stems(portion))*2<len(_stems(portion)):return False       # the call of 06.11 09:03: «пятьдесят девятый счёт это» over «пассивный счёт учитывает» is no try of it
        logger.info('echo-sync decision kind=replay reason=wrong_repeat revision=%s index=%s',state.get('revision'),state.get('chunk_index'))
        self.resume_repeat=True;self.said_wrong=True
        return True
    def _tail_repeated(self,text,state):
        """Rule 3: the listener repeats the missing tail that was cued: the waiting portion is confirmed (its words, for the verdict); else None."""
        position=self._position(state);tail=self.engine.tail_of(state)
        if not tail or position is None or tail[0]!=position or not tail[2]:return None
        chunks=list(state['chunks']);whole=chunks[state['chunk_index']];rest=tail[1]
        before=whole[:len(whole)-len(rest)].split() if whole.endswith(rest) else []
        for size in range(min(2,len(before))+1):       # F8: the listener may resume a word or two early
            chunks[state['chunk_index']]=' '.join(before[len(before)-size:]+[rest]) if size else rest
            if self._classify(text,{**state,'chunks':chunks}).kind==ACK:return whole
        return None
    def _take_candidate(self,turn):
        """Wave G: this final keeps its verdict for now (nothing is cued, the portion waits), and the evidence that may admit it is looked at: the
    reference base at once, then a delegation or a reply that has come already (a reply that goes on arriving: ``_candidate_reply``). H2: after the reference base the
    evidence is the job's text alone (``job``: asked once this final is done with, ``_fast_ask``). A final said before the job had ruled on the one before it goes to the job with it:
    the job of that one is gone, and nothing else would ever judge it («Пять умножить на пять» | «Ну давай быстрее уже»)."""
        tid=turn['id'];left=self.fast_left
        hit=self._reference_read(turn['text'])        # a reference asks nothing of the remark before it
        before=left[1] if left and left[0]==tid and not (left[3:] and left[3].get('refusal')) else self._fast_breath()      # a remark the roads had no word for (their honest sentence, ``refusal``) is over: it is not carried to the next final
        if before and norm_words(before)==norm_words(turn['text']):return []      # a listener stuck on the start of the portion says the same words twice: a repeat (``_stuck``), no question to look up
        if before and hit==quick_answer(turn['text']):hit=None      # a figure does (``_figure``)
        text=f"{before} {turn['text']}" if before and not hit else turn['text']
        spoke=self.tempo_ended if self.tempo_ended is not None and not self.hearing and within(self.clock(),self.tempo_ended,ANSWER_WAIT_SECONDS) else None      # round 3 (the owner's 8 s): the bound of the question counts from the END OF ITS SPEECH, not from the cloud's final that came seconds after it
        self.candidate={'id':tid,'text':text,'taken':self.clock(),'ask':self._unglued(text,self.state()),'spoke':spoke}
        hit=hit or (self._reference(text) if text!=turn['text'] else None)
        if hit and self._said_back(turn['text'],grown=tid==self.question_id):hit=None      # g28: words of the answer in play the base knows («шестьдесят второй счёт» said ahead) are no new question: the job declines them (``_fast_ask``)
        if hit:return self._admit('reference',local=hit)
        if not self.fast_on:return self._candidate_evidence(tid)
        self.candidate.update(job=None,said='')
        if self.tempo_live and self.repeat_at is None:self._tempo_arm(self.clock()+FIRST_TEXT_S)      # the job lives to the give-up of the roads, the silence timer waits for it FIRST_TEXT_S at most (``_tempo_waits``)
        return []
    def _candidate_evidence(self,tid):
        """A delegation or a reply that has come already admits the candidate."""
        if tid in self.early_delegations:return self._admit('delegation')
        for reply in [t for t in self.ledger.history() if t['role']=='assistant' and self.owners.get(t['id'])==tid]:
            admitted=self._candidate_reply(reply)
            if admitted:return admitted
        return []
    def _candidate_reply(self,turn):
        """The actions of the admission when this assistant turn admits the candidate; ``None`` when it is not its reply or does not (yet). The reply that
        follows a cut older segment is the candidate's only when it does not go on with that segment: until its first word tells, and while it is the
        candidate's, it is held from the older answer (``[]``)."""
        candidate=self.candidate;tid=turn['id']
        if not candidate or tid in self.retired_assistants:return None
        if 'job' in candidate:return [] if self.owners.get(tid)==candidate['id'] else None     # H2, rule 1: set aside; an older answer's segment goes its own way
        after_cut=candidate.get('after_cut')==tid
        if self.owners.get(tid)!=candidate['id'] and not after_cut:return None
        if after_cut:
            wire=self._wire_predecessor(tid)
            start=_segment_start(turn['text'],final=turn['final'],after=wire['text'] if wire else '')
            if start is None and not turn['final']:return []
            if start not in ('sentence','name'):
                del candidate['after_cut'];return None
        if candidate.get('ready'):return []
        if self._reply_admits(turn,candidate):
            if after_cut:
                self.owners[tid]=candidate['id'];self.foreign_replies.pop(tid,None)
            if not self.confirm_seconds:return self._admit('reply',reply=turn)
            candidate['ready']={'id':tid,'at':self.clock()}
            logger.info('echo-sync decision kind=silent reason=reply_prepared_waits_for_silence revision=%s',(self.state() or {}).get('revision'))
            return []
        if turn['final']:candidate['ended']=(tid,self.clock())
        elif after_cut:return []
        if after_cut and turn['final'] and _ENDS_SENTENCE.search(turn['text']):
            del candidate['after_cut'];return None
        return [] if after_cut else None
    def _candidate_due(self,now):
        """The one deadline of the candidate (a turn with no form of a question, taken to the model): two stages, the first that has something to do wins.
        1. A reply that ended with no mark may have been cut: as for an answer (``_settle``) its text is whole only once the grace window has passed
        with no newer turn of the listener. 2. G3 round 2 (``confirm_seconds``): the prepared reply goes out once the listener has been silent for the
        window; while they speak the window starts again. A final of that speech is judged on its own (``_accept_user``), and unless it is a backchannel
        the prepared reply goes with the candidate; the job's answer that waited for the silence goes out the same way. The third stage of old (g3-chaos: the model hung or broke on a final the ear stood in for) is the candidate branch of ``_answer_watchdog``, the one timer of an unanswered question."""
        candidate=self.candidate;ended=candidate.get('ended') if candidate else None
        if ended and self._end_over(ended[1],now) and not self.hearing:
            del candidate['ended']
            user=self.ledger.latest_user();reply=self.ledger.snapshot(ended[0])
            if reply and user and user['id']==candidate['id'] and self._reply_admits(reply,candidate,whole=True):
                if candidate.get('after_cut')==reply['id']:
                    self.owners[reply['id']]=candidate['id'];self.foreign_replies.pop(reply['id'],None)
                done=self._admit('reply',reply=reply)
                if done:return done
        candidate=self.candidate;ready=candidate.get('ready') if candidate else None
        if not candidate:
            done=self._readback_job_retired(now)
            if done:return done
        elif candidate.get('verdict') and not self.hearing:
            done=self._fast_verdict(candidate['job'])[1]      # H2: the job's answer waited for the silence
            if done:return done
        elif ready:
            if self.hearing:ready['at']=now
            elif now-ready['at']>=self.confirm_seconds:
                reply=self.ledger.snapshot(ready['id'])
                done=self._admit('reply',reply=reply) if reply else []
                if done:return done
        return []
    def _readback_job_retired(self,now):
        """Nothing is left up after an answer: a job prepared on the ear's text, with no word yet, whose words are only our own played cue said back (``_said_back``: no question word, nothing new) is let go once the cue is over
        and the listener quiet: it can only decline them («—»), and a final that comes is judged as ever. A remark of no form or a question is no read-back: its job stays."""
        if not self.fast_on or not self.prepared_job or not self.ear_said or self.hearing or self.tempo_speaking or self._cue_playing(now):return []
        text=probe('strip_fillers',str(self.ear_said[-1].get('text') or ''),settings=self.settings).value.strip()
        job=self.prepared_job(text) if text else None
        if not job or job[0] or job[1] or not self._said_back(text):return []
        strip=lambda said:probe('strip_fillers',said,settings=self.settings).value
        if self.question_id and self.question_text and same_question(text,self.question_text,strip=strip) and same_question(self.question_text,text,strip=strip):return []      # the job of the question just opened on these words is its answer, no read-back of a cue
        logger.info('echo-sync decision kind=silent reason=readback_job_retired revision=%s',(self.state() or {}).get('revision'))
        return self._fast_drop()
    def _reply_admits(self,turn,candidate,whole=False):
        """Does the model's reply to the candidate show that it took the turn for a question? A reply is bound to its own turn: its assistant turn began after
        that turn (``_candidate_reply``), and what goes on with an older segment cut on the wire is that older answer (the 20:10 call: «физлиц, торговый сбор
        …» after a bystander), and so is one that tells the older answer again, unless it says something of the candidate's that the older answer does not
        («не 15, а 50» -> «… за 50 лет …»). A real new answer during an old stream admits. After the filter of the cloud's process talk it holds a complete
        sentence of substance: not chatter, no question back, nothing said to the listener or about the cloud itself (``talks_about_itself``); the cloud's
        first-person content stays (an interview). ``whole``: its last sentence is over, with or without a mark."""
        wire=self._wire_predecessor(turn['id'])
        if wire and not _ENDS_SENTENCE.search(wire['text']) and _segment_start(turn['text'],final=turn['final'],after=wire['text']) not in ('sentence','name'):
            return False
        if norm_words(turn['text'])[:1] in (['угу'],['ага']):return False     # policy v2.4: the cloud's word for a turn that is not for it, whatever follows
        asked=candidate['text']
        text,sentences=self._of_substance(turn['text'],asked,whole)
        return bool(sentences) and not self._said_already(text,asked)      # the one «already said» (``_said_already``)
    @staticmethod
    def _of_substance(text,asked,whole,brain=False):
        """``(text after the filter of process talk, its complete sentences of substance)``: not chatter, no question back, nothing said to the listener or about the producer.
        ``whole``: the last sentence is over, with or without a mark. ``brain``: the text channel's: first-person content is content, and «Да.» answers; it does not retell."""
        text=drop_process_sentences(strip_process_prefix(text,asked,digits=brain),asked,final=whole,talk=brain)
        if whole and text and not _ENDS_SENTENCE.search(text):text+='.'
        def counts(sentence):
            if sentence.rstrip().endswith('?') or (about_itself(sentence,asked) if brain else talks_about_itself(sentence)):return False
            return any(word not in STOPWORDS and word not in _NO_SUBSTANCE or (brain and word in _MAY_ANSWER) for word in norm_words(sentence))
        return text,[sentence for sentence in _SPOKEN_SENTENCE.findall(text) if counts(sentence)]
    @staticmethod
    def _backchannel(text):
        """Is ``text`` nothing but the cloud's backchannel: no word of it can answer anything?"""
        words=norm_words(text)
        return any(word in _NO_SUBSTANCE for word in words) and all(word not in _MAY_ANSWER and (word in _NO_SUBSTANCE or (word in STOPWORDS and len(word)<=3)) for word in words)
    def _at_it(self,state):
        """H6 item 2: was the listener at the portion of ``state``? He said a word to it since it was cued, or the timer has not had to say it again: a plan only the timer keeps alive is nobody's."""
        mark=self.abandon if (self.abandon or {}).get('at')==self._position(state) else None
        return not mark or mark.get('said') is not None or not mark.get('timed')
    def _speech_begins(self,text,state):
        """Does this final open the speech: it has not opened, nothing is in play, and it is a command to begin or the first words of the text?"""
        speech=self.speech
        if not speech or speech['entry'] is not None or probe('waiting_portion',state=state).value is not None or self.question_id or self.candidate:return False
        said=self._said_words(text)
        if frozenset(said)&SPEECH_STARTS and frozenset(said)<=SPEECH_STARTS|SPEECH_LEADS:return True
        own=norm_words(speech['text'])[:len(said)]
        return len(said)>=SPEECH_WORDS and [stem(word) for word in said]==[stem(word) for word in own]
    def _speech_opens(self,turn):
        """The material is the plan: as the base's answer, no job, no cloud: said once more it is a repeat. What he has said of the first portion is not said again."""
        speech=self.speech;text=turn['text']
        logger.info('echo-sync decision kind=question reason=speech_start revision=%s',(self.state() or {}).get('revision'))
        actions=self._open_question(turn,Decision(QUESTION,'speech_start',text,None),local=speech['text'])
        state=self.state() or {};portion=probe('waiting_portion',state=state).value
        if portion is None:return actions
        speech['entry']=state.get('entry');said=self._started(text,portion)
        said_back=self._classify(text,state)
        if said_back.kind==ACK:
            return [action for action in actions if action['type']!='speak']+self._cue(self._reply(text,f'{self.nonce}:{turn["id"]}:speech',decided=said_back,basis=self._basis(state)))
        if said:
            self._cue_tail(self._position(state),said[0])
            return [action for action in actions if action['type']!='speak']+self._cue(said[0])
        return actions
    def _admit(self,evidence,*,reply=None,local=None,job=None,said=None):
        """The candidate is the question: what a new question does (``_open_question``), and the reply already streaming is its answer, with no
        new request to the model: its text goes the usual way (``_source``; a question that needs a lookup waits for it there, as any other)."""
        candidate,self.candidate=self.candidate,None
        turn=self.ledger.snapshot(candidate['id']) if candidate else None
        if not turn or not turn['valid'] or self._overtaken('final',turn):return []      # G23: an older final after a newer question is dropped
        # the ONE veto of a candidate that asks nothing (rule of cm-open): the cloud's delegation or reply on the answer in play said back (g28, ``ahead``); the question in play said back, heard twice (the owner's call of 06.11 09:03, every way in, not only the job's); talk the reply proves no question (h29)
        if evidence in ('delegation','reply') and self._said_back(candidate['text'],ahead=self.state()):why,foreign='said_back',True
        elif self._said_back(candidate['text'],grown=candidate['id']==self.question_id):why,foreign='said_back',False
        elif local is None and self._talk_no_question(candidate['text'],reply['text'] if reply else said):why,foreign='talk_no_question',True
        else:why=foreign=None
        if why:
            if foreign:
                self.foreign_turns[turn['id']]=True
                if reply is not None:self.retired_assistants.add(reply['id'])
            else:self.fast_passed=candidate['id']
            logger.info('echo-sync decision kind=silent reason=%s evidence=%s revision=%s',why,evidence,(self.state() or {}).get('revision'))
            return self._fast_no_search(turn['id'])
        self.foreign_turns.pop(turn['id'],None);self.quiet_pieces=[]
        logger.info('echo-sync decision kind=question reason=cloud_admitted evidence=%s revision=%s',evidence,(self.state() or {}).get('revision'))
        decision=self._admitted_decision(candidate['text'])
        actions=self._open_question({**turn,'text':candidate['text']},decision,local=local,job=job)
        return actions+self._source(reply) if reply is not None else actions
    @staticmethod
    def _tries(decision,reason):
        """c8b: is this the listener working on the waiting portion - a confirmation, a command, a request, a try, a clarification - so that it is
        never abandoned while they are at it?"""
        return (decision.kind not in (QUIET,GREETING) or reason in ATTEMPT_REASONS
                or reason in ('attempt_clarification','attempt_answer_words','attempt_ru_alignment'))
    @staticmethod
    def _rearms(decision,reason,text=''):
        """W1F-B (C4): may the silence auto-repeat run again after a final that spoke nothing while a portion waits? After a verdict the
        controller acted on (a cut cue, a request whose cue was cancelled before its first byte) and after silence in words - a final of
        nothing but fillers or a backchannel («угу», «ага»: no content word in ``text``), our own voice heard back - or a real try at the
        portion (``ATTEMPT_REASONS``, the sub-reason of the silent policy included: ``reason``; an uncertain «а?» / «что?» counts as noise). Never
        after speech the classifier could not place: a connection check, thanks, a bystander, a command it does not know (W1 w1_10, w1_12,
        w1_09, w1_14, sc01: the stale portion spoken over the listener 6 s later)."""
        if decision.kind!=QUIET:return True
        return reason in ('empty','only_fillers','local_repair_prompt_echo','attempt_clarification') or reason in ATTEMPT_REASONS or not _content(text)
    def _asked_again_unheard(self,turn,text,state):
        """c24 P15 (fuzz seed 90, A3): the question in play asked again (the same question both ways) by speech that ended before the first portion of its answer was heard:
        the friend repeated it because no answer had come yet. It is the same request: the answer that is being said is its answer, not retired and said again from the start
        (the owner's repeat of that start would then confirm the new copy with nobody speaking to it)."""
        if not state or state.get('chunk_index') or probe('waiting_portion',state=state).value is None:return False
        asked=str(state.get('question') or '');strip=lambda value:probe('strip_fillers',value,settings=self.settings).value
        if not asked or not (same_question(text,asked,strip=strip) and same_question(asked,text,strip=strip)):return False
        return self._heard_after(turn,state)=='sounded'      # its first portion has sounded since that speech ended; not heard on this call at all (a call reopened) it is presented as asked
    # ---- R-EAR-ACT: the local ear acts (local_ear = "act"; see EAR_JOIN_GAP_SECONDS) --------------------------------------------------
    # The ear (ear_shadow.ShadowEar, mode "act") tells ``ear_onset`` every start of speech its detector hears and hands ``ear_heard`` the
    # text of every utterance it recognized. A confirmation, a repeat request, a stop or «дальше» for the portion that waits is applied at
    # once through ``_accept_user`` - the path a cloud final takes - on the cloud's own open turn of the same utterance, which is taken
    # (``seen``) the way the stable partial takes one, so the cloud's partials and final never act on it again, and what its final says
    # after the part the ear decided is classified then (``_early_tail``). Questions and everything else stay the cloud's: the ear does
    # nothing about them, but for H4 (``_ear_first``, behind the text channel). In any doubt the ear does nothing and the call goes on as without it.

    def _ear_mark(self):
        """Where the call stands, as far as a verdict of the ear is concerned: a new epoch, the cursor moved, a pause, the end - any of them
        since the ear heard an utterance begin means it was not said to what is there now. (A cue issued since is ``_cue_over_before``'s.)"""
        state=self.state() or {}
        return (self.epoch,state.get('revision'),state.get('chunk_index'),bool(state.get('paused')),
                bool(state.get('completed')),bool(state.get('stream_waiting_next')))
    @staticmethod
    def _ear_family(decision):
        """The verdicts the ear acts on, by what they do: ACK, REPEAT (with «не расслышал», a REPLAY of the hearing-repair kind), STOP and
        NEXT; ``None`` for everything else (a question, a correction, an attempt, «продолжай», noise)."""
        if decision.kind in (ACK,REPEAT,STOP,NEXT):return decision.kind
        return REPEAT if decision.reason=='replay_hearing_repair' else None
    def _ear_safely(self,work,*args,default=None):
        """Fix round 1, item 4: every way into the ear's acting runs here - ``ear_onset``, ``ear_heard``, ``ear_piece``, the waiting verdict on
        the provider's path and on the tick, the take of a later piece, the ear's part of ``_early_tail``. A failure switches the ear off for
        the rest of the call, once and logged by type (``_ear_fail``); from then on every entry returns ``default`` at once and the cloud
        decides alone, as without the ear."""
        if self.ear_off:return default
        try:return work(*args)
        except Exception as error:
            self._ear_fail(error)
            return default
    def ear_onset(self,uid):
        """The ear's detector has heard speech begin (utterance ``uid`` of this call): when, and where the call stood then. A verdict that
        still waits for the cloud (``ear_pending``) is given up: the cloud may make one turn of it and this new speech."""
        self._ear_safely(self._ear_onset,uid)
    def _ear_onset(self,uid):
        now=self.clock();self.ear_onset_at=now
        self.ear_started[uid]=(now,self._ear_mark())
        while len(self.ear_started)>16:self.ear_started.pop(next(iter(self.ear_started)))
        if self.ear_pending is not None:
            logger.info('echo-sync ear act=dropped reason=new_onset uid=%s',self.ear_pending['run'][-1]['uid'])
            self.ear_pending=None
        if self.ear_first is not None:self._ear_first_drop('new_onset')
    def ear_progress(self,record):
        """w5-flow: the ear's text of the utterance SO FAR (a ``ShadowEar`` peek while the listener speaks: ``uid``, ``text``). Only read by
        ``flow_ahead``; nothing is decided on it but the release ahead of the next portion (``_flow_due``)."""
        return self._ear_safely(self._ear_progress,record,default=[])
    def _ear_progress(self,record):
        if self.flow is None or not isinstance(record.get('text'),str):return []
        self.flow_uid=record.get('uid');now=self.clock()
        self.flow.heard(record['text'],now)
        return self._flow_due(now)
    def ear_heard(self,record):
        """What the ear recognized of one utterance (a ``ShadowEar.poll`` record: ``uid``, ``text``, ``offset`` - the end its detector
        heard, on this controller's clock - and ``onset_input_ms`` / ``offset_input_ms`` on the transport's input clock). Returns the
        actions of the verdict when the ear acts on it, else ``[]``. It acts when the verdict on the utterance (its pieces joined:
        ``_ear_run``) is a confirmation, a repeat request, a stop or «дальше» (``_ear_family``) for the portion that waits, the utterance
        began after the last cue had been heard to its end, nothing happened since it began (``_ear_mark``), and the cloud's turn of it
        can be taken (``_ear_turn``); when the cloud has not announced it yet, the verdict waits EAR_BIND_SECONDS for it."""
        return self._ear_safely(self._ear_heard,self._ear_lang_gate(record)[0],default=[])
    def ear_partial(self,record):
        """W5 instant: the ear's text so far of the utterance ``uid`` (``ShadowEar.partials``), while it is still being said. A unique hit of the bank (``Instant.feed``) opens the answer as the ear's final would (H4
        rule 1, ``_ear_first``), its end being now; new significant words after it cut the cue (``speech_started``) and the question goes the usual way. Returns the actions."""
        record,gated=self._ear_lang_gate(record)
        return [] if gated else self._ear_safely(self._ear_partial,record,default=[])
    def _instant_holds(self,uid,text):
        """W5: the ear's text of the utterance whose partial opened the bank's answer (``ear_partial``), with nothing new in it: that answer has judged it."""
        i=self.instant
        if i is None or i.hit is None or i._uid!=uid or i.cut or not isinstance(text,str):return False
        hit=i.lookup(text,bank_only=True)
        return hit is not None and hit.answer==i.hit.answer
    def _ear_heard(self,record):
        uid=record.get('uid');text=record.get('text')
        if record.get('kind')=='question' and isinstance(text,str) and text:self.ear_newest=(text,(self.ledger.latest_user() or {}).get('start_ms',-1))      # G23: read by ``_overtaken`` only
        if record.get('kind')=='question' and record.get('revision') is not None:self.ear_question_on=record['revision']      # W14: read by ``_ear_final_due`` only
        if record.get('kind')=='question' and not (isinstance(text,str) and self._same_as_asked(text)):self.ear_asked=self.clock()      # c24 P16: read by ``_overtaken`` only; fix4 (Р101 seed 2 @76.46): the ear's text of the question in play itself, come after its final, is no newer question (the plan it took over goes on when it is declined)
        if record.get('kind')=='question' and type(record.get('onset_input_ms')) in (int,float) and isinstance(text,str) and probe('question_by_form',text).value:self.ear_asked_input=(record['onset_input_ms'],text)      # Р015/Р034 seed 102: the ear calls «как раз пожалуйста», «давайте задавайте любой вопрос» questions: the form decides      # c25-a: read by ``_overtaken`` only
        started=self.ear_started.pop(uid,None)
        if record.get('kind')=='question' and record.get('reason')!='topic_phrase' and started and self.cue_window and started[0]>=self.cue_window[0] and record.get('revision') is not None and isinstance(text,str) and not most_said(text,probe('waiting_portion',state=self.state() or {}).value or '') and not self._same_as_asked(text):self.asked_over=(record['revision'],started[0],self.clock())      # c25-a G1: a new question begun after a cue of this plan
        # An utterance begun before this one whose text never came (dropped by the ear, or failed) was speech nobody knows: it may have
        # been the start of this one («не, …»).
        earlier=[key for key in self.ear_started if type(key) is int and type(uid) is int and key<uid]
        unknown=[self.ear_started.pop(key)[0] for key in earlier]
        offset=record.get('offset')
        piece={'uid':uid,'text':text if isinstance(text,str) and text.strip() else None,'onset':started[0] if started else None,
               'mark':started[1] if started else None,'offset':offset if type(offset) in (int,float) else None,
               'onset_input_ms':record.get('onset_input_ms'),'offset_input_ms':record.get('offset_input_ms'),'acted':False,'voice':record.get('voice')}
        if unknown and piece['onset'] is not None and piece['onset']-max(unknown)<=EAR_PIECE_SECONDS:piece['text']=None
        run=self._ear_run(piece)
        self.ear_pieces=(self.ear_pieces+[piece])[-EAR_JOIN_PIECES:]
        self.ear_said=(self.ear_said+[piece])[-EAR_SAID_PIECES:]
        late=self._ear_late_veto()
        if late is not None:return late
        decision,why=self._ear_verdict(run)
        if decision is not None and self._ear_goes_on(piece):decision,why=None,'goes_on'
        if decision is None:
            if why:logger.info('echo-sync ear act=no reason=%s uid=%s',why,uid)
            return self._ear_first(run,piece)
        now=self.clock();kind=self._ear_family(decision)
        # A command waits until the quiet after it has lasted EAR_COMMAND_SETTLE_SECONDS (the tick takes it then, ``_ear_bind_pending``), and
        # so does the confirmation of a portion that ends in a number (fix round 1, item 3: «ему было двадцать» | «пять» - a number can still
        # grow, the rule of the stable partial, ``_may_still_grow``); speech that begins meanwhile drops it and is judged with it.
        grows=kind==ACK and self._may_still_grow(probe('waiting_portion',state=self.state()).value or '')
        settle=piece['offset']+EAR_COMMAND_SETTLE_SECONDS if kind!=ACK or grows else now
        if now>=settle:
            tid,why=self._ear_turn(run,decision)
            if tid is not None:return self._ear_take(tid,run,decision)
            if self._ear_stop(decision,run,self.state()) or self._ear_alone(decision,run,why):return self._ear_stops(run,decision)
        if now<settle or why=='no_open_turn':
            self.ear_pending={'run':run,'kind':kind,'not_before':settle,'deadline':max(now,settle)+EAR_BIND_SECONDS}
            logger.info('echo-sync ear act=waits uid=%s kind=%s',uid,decision.kind)
        else:
            logger.info('echo-sync ear act=no reason=%s uid=%s kind=%s',why,uid,decision.kind)
        return []
    def _ear_run(self,piece):
        """The pieces of ONE utterance of the listener ending with ``piece``: the earlier pieces the ear heard, each begun at most
        EAR_JOIN_GAP_SECONDS after the end of the one before it and none acted on, at most EAR_JOIN_PIECES in all."""
        run=[piece]
        for before in reversed(self.ear_pieces):
            first=run[0]
            if len(run)>=EAR_JOIN_PIECES or before['acted'] or before['offset'] is None or first['onset'] is None:break
            if not within(first['onset'],before['offset'],EAR_JOIN_GAP_SECONDS):break
            run.insert(0,before)
        return run
    def _ear_goes_on(self,piece):
        """Has the ear already heard speech begin again, within EAR_JOIN_GAP_SECONDS of the end of ``piece``? Then the utterance goes on
        («Подожди, | лучше скажи …»): nothing is decided on ``piece`` alone, the next piece's verdict is taken on the two joined."""
        later=self.ear_onset_at
        return bool(later is not None and piece['onset'] is not None and piece['offset'] is not None and later>piece['onset']
                    and later-piece['offset']<=EAR_JOIN_GAP_SECONDS)
    def _ear_stop(self,decision,run,state):
        """H6 item 5 (n1_02 step 15, R1): a whole «стоп» of the ear, with the channel on: it acts on the ear, over a cue too: the cue cannot say it when no word of it is the portion's."""
        return bool(self.fast_call and decision.kind==STOP and not self._of_the_portion(' '.join(p['text'] for p in run),probe('waiting_portion',state=state).value or ''))
    def _ear_no_echo(self,decision,run,state):
        """g25: «ещё раз», «громче» said right after the cue: no word of it is the portion's, so it is no echo of the cue; it is the owner, who did not hear it."""
        if not self.fast_call or self._ear_family(decision)!=REPEAT or self.candidate or self._cue_playing(self.clock()):return False      # never «дальше» (it moves the plan: rehearsal Р001 seed 2, an old answer), never with a newer question at work
        return not self._of_the_portion(' '.join(p['text'] for p in run),probe('waiting_portion',state=state).value or '')
    def _ear_alone(self,decision,run,why,expired=False):
        """g25 (WAVE20: «быстро, без облака, по уху»): the cloud has no open turn of this utterance. «ещё раз», «громче», «дальше» are carried out on the ear alone, as a stop is (``_ear_stops``): the cloud's
        turn, when it comes, is a piece of that take. Not words of the portion (the cue heard back). A confirmation waits EAR_BIND_SECONDS for the cloud first (``expired``): it moves the plan on."""
        kind=self._ear_family(decision)
        if not self.fast_call or why!='no_open_turn' or kind not in ((REPEAT,NEXT,ACK) if expired else (REPEAT,NEXT)):return False
        user=self.ledger.latest_user()
        if any(done>=run[0]['onset'] for done in self.user_done_at.values()):return False      # a final of the cloud came since the speech began: it has judged these words
        if user and user['valid'] and not user['final']:return False      # a turn of the cloud is still open (taken, H4): its final holds these words and decides (test_h4: a command in the question's turn)
        return kind==ACK or not self._of_the_portion(' '.join(p['text'] for p in run),probe('waiting_portion',state=self.state()).value or '')
    def _ear_stops(self,run,decision):
        """H6 item 5: the stop of the ear is carried out with no turn of the cloud, which comes up to 3.7 s after the onset (EAR_FIRST_BIND_SECONDS): that turn is then a piece of this take (``_ear_piece``), and acts no more.
        g25: so are a repeat request, «дальше» and, once the cloud has had its time, a confirmation (``_ear_alone``)."""
        state=self.state() or {};tid=f"ear-{run[-1]['uid']}";text=' '.join(p['text'] for p in run);kind=self._ear_family(decision) or STOP
        logger.info('echo-sync decision kind=%s reason=%s uid=%s revision=%s index=%s',decision.kind,'local_ear_stop' if kind==STOP else 'local_ear_alone',run[-1]['uid'],state.get('revision'),state.get('chunk_index'))
        self.tempo_unjudged=[]
        actions=self._accept_user({'id':tid,'role':'user','valid':True,'final':True,'text':text},boundary='local_ear',cause='local_ear')
        self.ear_take={'tid':tid,'state':state,'kind':kind,'when':self.clock(),'offset':run[-1]['offset'],'offset_input_ms':run[-1]['offset_input_ms'],'ear':{'earlier':[],'first':None,'text':text},'stop':True}
        for piece in run:piece['acted']=True
        return actions
    def _ear_turn(self,run,decision):
        """The cloud's turn of this utterance, for the ear to take: the latest user turn, still open (no final yet) and taken by nobody,
        announced after the utterance began (one announced before holds earlier speech too), and - when the provider says where its
        speech began (``_speech_start_ms``) - begun within the utterance. When the cloud has already heard a number, a unit or a «не» the
        waiting portion does not have - in that turn or in a piece of the utterance it cut off before it (fix round 1, item 2: «Не при ста»
        | «градусах…») - it disagrees with a confirmation: the ear does not confirm over it. ``(tid, None)`` or ``(None, why)``."""
        user=self.ledger.latest_user()
        if not user or not user['valid'] or user['final'] or user['id'] in self.seen:return None,'no_open_turn'
        announced=self.announced_at.get(user['id'])
        if announced is None or announced<run[0]['onset']-EAR_ANNOUNCE_SLACK_SECONDS:return None,'turn_began_before'
        start=self._speech_start_ms(user)
        first,last=run[0]['onset_input_ms'],run[-1]['offset_input_ms']
        if start is not None and type(first) in (int,float) and type(last) in (int,float) and not first-EAR_START_SLACK_MS<=start<=last:
            return None,'turn_elsewhere'
        if decision.kind==ACK:
            heard=self._ear_utterance_text({'earlier':self._ear_earlier(run,user['id'])},user['text'])
            if self._cloud_disagrees(heard,probe('waiting_portion',state=self.state()).value or ''):return None,'cloud_disagrees'
        return user['id'],None
    def _ear_earlier(self,run,tid):
        """Fix round 1, item 1: the cloud's user turns before ``tid`` (in its order of turns) that belong to the utterance of ``run`` -
        announced at most EAR_ANNOUNCE_SLACK_SECONDS before the run began and, when the provider says where their speech began, begun within
        the run: the pieces of the utterance the cloud cut off before the turn the ear takes («При ста градусах» | «Цельсия, а почему?»)."""
        turns=[t for t in self.ledger.history() if t['role']=='user']
        ids=[t['id'] for t in turns]
        if tid not in ids:return []
        first,last=run[0]['onset_input_ms'],run[-1]['offset_input_ms']
        out=[]
        for turn in turns[:ids.index(tid)]:
            announced=self.announced_at.get(turn['id'],self.user_started_at.get(turn['id']))
            if not turn['valid'] or announced is None or announced<run[0]['onset']-EAR_ANNOUNCE_SLACK_SECONDS:continue
            start=self._speech_start_ms(turn)
            if start is not None and type(first) in (int,float) and type(last) in (int,float) and not first-EAR_START_SLACK_MS<=start<=last:
                continue
            out.append(turn['id'])
        return out
    def _ear_utterance_text(self,ear,text):
        """The cloud's words of the utterance the ear took: its earlier pieces (``ear['earlier']``, as far as the cloud has them) and ``text``."""
        words=[]
        for tid in ear.get('earlier') or ():
            turn=self.ledger.snapshot(tid)
            if turn and turn['text'].strip():words.append(turn['text'].strip())
        return ' '.join(words+[str(text).strip()])
    @staticmethod
    def _protected_atoms(text):
        """What a confirmation must never get wrong in ``text``, by value: numbers («сто», «100», «сотый» are one), units, «не», «ни». Returns
        ``(atoms, last)``: ``last`` is the number ``text`` ends with (None when it ends otherwise)."""
        from .ru_alignment import _canonical
        from .ru_numbers import digits_for_words      # U43: «четыре два два», «four two two», «two hundred» are numbers
        found,last=set(),None
        for atom in _canonical(digits_for_words(str(text or '')),(),True):
            last=None
            if atom.atom in ('не','ни') or atom.kind=='u':found.add(atom.atom)
            elif atom.kind=='n' or atom.atom.startswith('!spoken:'):
                last='#'+re.split(r'[:#]',atom.atom)[-1];found.add(last)
        return found,last
    def _cloud_disagrees(self,heard,portion,growing=True):
        """Has the cloud heard (``heard``: its words) a number, a unit or a «не»/«ни» that ``portion`` does not have? While its words still
        grow (``growing``), the number they end with may still be being said (the replay: «в тысяча девятьсот» on the way to «1914»): it
        disagrees only when it cannot grow into a number of the portion (``_may_grow_into``). Unknown: yes."""
        try:
            (said,last),(wanted,_)=self._protected_atoms(self._what_stands(heard)),self._protected_atoms(portion)
            extra=said-wanted
            if growing and last in extra and self._may_grow_into(last,{atom for atom in wanted if atom.startswith('#')}):extra.discard(last)
            return bool(extra)
        except Exception:return True
    @staticmethod
    def _what_stands(heard):
        """H5 item 4: what ``heard`` says of a number: what follows the speaker's self-correction, when a number stands there. A marker with no number after it took none back: the veto of a wrong number stays."""
        corrected=probe('self_corrected',heard).value
        return corrected[1] if corrected and _holds_a_number(corrected[1]) else heard
    def _late_correction(self,ear,cloud,inside=True):
        """U15-S6: ONE verdict on a late word of the cloud against what the ear (or the portion) said: ``meaning_guard`` drives it: DIFFERS cancels, SAME and UNKNOWN (a dropped «не», number or word: the ear's drop or the meaning, ``UNKNOWN_POLICY``) keep playing."""
        from .fast_text import _prepared,_protected,_words,meaning_guard
        from .utterance_judge import DIFFERS,UNKNOWN
        strip=lambda said:probe('strip_fillers',said,settings=self.settings).value
        try:
            verdict=meaning_guard(ear,cloud,strip=strip)
            # a content word the cloud has and the ear lacks, the ear having no word the cloud lacks, is a word the ear missed INSIDE the question (a filler head is stripped above): the job made on the ear's text is not the question asked
            if verdict==UNKNOWN and inside:      # ``inside`` False: the cloud's words are a head and its rest, a turn that may be of its own: only a DIFFERS is a correction
                one,other=_words(_prepared(strip(ear))),_words(_prepared(strip(cloud)))
                if other-one and not one-other:verdict=DIFFERS
                # the same for a number or «не» the cloud has and the ear lacks (the base's not-same-start answer): the ear missed it inside the question, the portion on the ear's text is not the question asked
                if verdict==UNKNOWN and not _protected(_prepared(strip(ear)))-_protected(_prepared(strip(cloud))) and _protected(_prepared(strip(cloud)))-_protected(_prepared(strip(ear))):verdict=DIFFERS
        except Exception:verdict='unknown'
        logger.info('echo-sync late_correction verdict=%s',verdict)
        return verdict==DIFFERS
    def _ear_run_of(self,tid,state):
        """c9-numveto: the pieces of the ear (``ear_pieces``, joined as ``_ear_run`` joins them) that are the utterance the cloud's turn ``tid``
        holds, for the portion that ``state`` waited for: heard while the call stood on that portion (``_ear_mark``), none acted on or already
        used for a veto, the first begun from EAR_ANNOUNCE_SLACK_SECONDS before to EAR_ANNOUNCE_MAX_SECONDS after the turn was announced and,
        when the provider says where its speech began (``_speech_start_ms``), within the utterance (EAR_START_SLACK_MS allowed) - the rule
        of ``_ear_turn`` the other way round. ``[]`` when there is none: the ear has not heard that utterance (yet)."""
        announced=self.announced_at.get(tid)
        if announced is None or not state:return []
        where=(state.get('revision'),state.get('chunk_index'))
        turn=self.ledger.snapshot(tid)
        start=self._speech_start_ms(turn) if turn else None
        end=turn.get('end_ms') if start is not None else None
        run=[]
        for piece in self.ear_pieces:
            if piece['acted'] or piece.get('vetoed') is not None or piece['text'] is None or piece['onset'] is None:continue
            if piece['mark'] is None or tuple(piece['mark'][1:3])!=where:continue
            if type(end) in (int,float) and type(piece['onset_input_ms']) in (int,float) and piece['onset_input_ms']>end:continue     # A1-F4: begun after the cloud's turn was over (with its pre-roll): the next utterance, not this one
            if run and run[-1]['offset'] is not None and within(piece['onset'],run[-1]['offset'],EAR_JOIN_GAP_SECONDS):run=run+[piece]
            elif -EAR_ANNOUNCE_SLACK_SECONDS<=announced-piece['onset']<=EAR_ANNOUNCE_MAX_SECONDS:run=[piece]
        if not run:return []
        first,last=run[0]['onset_input_ms'],run[-1]['offset_input_ms']
        if start is not None and type(first) in (int,float) and type(last) in (int,float) and not first-EAR_START_SLACK_MS<=start<=last:return []
        return run
    def _ear_other_number(self,heard,portion):
        """``_ear_once``; c24 (w3 n2_d10 15): «сто пятьдесят тысяч пятьсот тысяч» is two numbers the ear wrote with no mark between («150 000 / 500 000»): ``ru_numbers`` refuses the run
        and reads its pieces (100, 50, 1000, 500): when the run read as numbers that end at each scale word has no other number, the ear has none."""
        if not self._ear_once(heard,portion):return False
        regrouped=_AFTER_SCALE.sub(r'\1 / ',str(heard or ''))
        if regrouped!=str(heard or '') and not self._ear_once(regrouped,portion):return False
        places=self._number_places(heard)      # c25-c (half hour P1, seeds 5 11 15): «триста сорок шесть двенадцать» of «Статья 346.12», refused as one number, is 346 and 12
        return places==str(heard or '') or self._ear_once(places,portion)
    @staticmethod
    def _number_places(heard):
        """c25-c: ``heard`` with « / » where a run of number words starts a new number: the next word is not below the place the run has reached (300 40 6 | 12)."""
        from .ru_alignment import _canonical
        out,run=[],0
        for word in str(heard or '').split():
            atoms=list(_canonical(word,(),True));value=re.split(r'[:#]',atoms[0].atom)[-1] if len(atoms)==1 and (atoms[0].kind=='n' or atoms[0].atom.startswith('!spoken:number:')) else ''
            if not value.isdigit() or value in ('1000','1000000','1000000000'):out.append(word);run=0;continue      # a scale word: the reading of ``ru_numbers`` stands
            value=int(value)
            if run and not value<10**(len(str(run))-len(str(run).rstrip('0'))):out.append('/')
            out.append(word);run=run+value if run and value<10**(len(str(run))-len(str(run).rstrip('0'))) else value
        return ' '.join(out)
    def _ear_once(self,heard,portion):
        """c9-numveto: does ``heard`` (the ear's words) carry a number that ``portion`` does not have, while ``portion`` has one? By value
        (``_protected_atoms``: «девятьсот восемьдесят девять» and «989» are one); a number the ear may still be saying (its last, which can
        grow into a number of the portion, ``_may_grow_into``) is no other number. Units and «не» are not looked at: that is the cloud's
        business, and a weak ear must not block a confirmation for a spurious one."""
        tried=getattr(self,'portion_tries',None)
        if tried and reads_out(' '.join([*tried[1],heard]),portion):return False      # level 2 of 06.11: «двадцать» | «два процента» is 22 said in two breaths
        (said,last),(wanted,_)=self._protected_atoms(self._what_stands(heard)),self._protected_atoms(portion)     # H5 item 4: the number he took back says nothing
        said={atom for atom in said if atom.startswith('#')};wanted={atom for atom in wanted if atom.startswith('#')}
        if not wanted:return False
        extra=said-wanted
        if last in extra and self._may_grow_into(last,wanted):extra.discard(last)
        extra={atom for atom in extra if not any(self._tail_of(atom,number) for number in wanted)}      # w3-scenes: «двадцать тысяч» after «сто» (a number cut by a pause) is the end of «сто двадцать тысяч»
        extra-=self._parts_of(portion,wanted)      # g1-ladder L2: «статья одиннадцать три» of «Статья 11.3», «семнадцать девять две тысячи двадцать» of «17.09.2020»
        if not re.search(r'(?<![\w.,])(?:ноль|нуль|0)(?![\w.,])',str(heard),re.I):extra={atom for atom in extra if not (atom.startswith('#0.') and any(number.startswith('#') and '.' in number and number[1:].split('.')[1]==atom[3:] for number in wanted))}      # c23 (L2 seed 130): «до то целых четырёх десятых» of «2,4»: the whole part lost is a word lost, «ноль целых» is a number
        for whole in wanted:      # g1-ladder L2: «двадцати двух» read as 20 and 2 is the 22 of the portion
            value=whole[1:]
            if value.isdigit() and len(value)==2 and value[1]!='0' and {'#'+value[0]+'0','#'+value[1]}<=extra:extra-={'#'+value[0]+'0','#'+value[1]}
        return bool(extra)
    @staticmethod
    def _parts_of(portion,wanted):
        """The parts of a number of the portion written with dots («11.3», «333.16», «17.09.2020»): said aloud they are numbers of their own («одиннадцать три»); an account with its zero («05») is said «пять»."""
        found=[number[1:] for number in wanted]+re.findall(r'\d+(?:\.\d+)+',str(portion or ''))
        parts=[part for number in found if '.' in number for part in number.split('.') if part.isdigit()]+re.findall(r'(?<![\d.,])0\d+(?![\d.,]\d)',str(portion or ''))      # «кредит 05»: «пять»
        return {'#'+str(int(part)) for part in parts}|({'#0'} if any(len(part)>1 and part[0]=='0' for part in parts) else set())      # «60.01»: «шестьдесят ноль один»
    @staticmethod
    def _tail_of(part,number):
        """Is ``part`` (#20000) the end of ``number`` (#120000): its digits are the last digits of the longer whole number? Only for a round number of three or more places."""
        a,b=part[1:],number[1:]
        return a.isdigit() and b.isdigit() and len(a)>=3 and len(a)<len(b) and b.endswith(a) and a.rstrip('0')!=a
    def _ear_number_veto(self,tid,state):
        """c9-numveto (FIRST_DIVERGENCE w3_02 step 4: «… 989 годом» confirmed as «… 988 годом» by a cloud biased by the answer it generated):
        the cloud's turn ``tid`` is about to confirm the portion that ``state`` waits for. The text the local ear heard of the same utterance
        (``_ear_run_of``), when it carries another number than the portion - the portion having one - is returned, and the confirmation is
        refused (the caller judges the utterance as the ear heard it). ``None``: the cloud decides - the ear has not heard the utterance (yet:
        ``_ear_late_veto`` then takes the step back), heard no number (empty, garbled) or the same one. Only ``local_ear`` = "act" has an ear
        that reaches the controller (``ear_heard``): in any other mode there is nothing to compare with and nothing changes."""
        portion=probe('waiting_portion',state=state).value
        if portion is None:return None
        run=self._ear_run_of(tid,state)
        if not run:return None
        heard=' '.join(piece['text'] for piece in run)
        if not self._ear_other_number(self._before_the_next(without_repeats(heard,portion) or heard,state),portion):return None      # g7: «168… 168» is one number
        if self._restart_says_no_other(self._before_the_next(heard,state),portion):return None      # c25-c: «тридцать восемь эта | двадцать восемь это семь раз по четыре»
        for piece in run:piece['vetoed']=tid
        return heard
    def _restart_says_no_other(self,heard,portion):
        """c25-c (half hour seeds 1 2 6 14 15): the owner began the portion again within the utterance («28. Это... 28. Это 7 раз по 4.», the ear wrote the false start
        «тридцать восемь эта»): the last start of the portion stands. True when a later part of ``heard`` starts the portion and carries no other number."""
        from .ru_alignment import _canonical
        first=lambda text:next((atom.atom for atom in _canonical(str(text),(),True)),None)
        words=str(heard or '').split();fillers=resolve(self.settings)['fillers'];start=first(portion)
        for k in range(len(words)-1,0,-1):
            tail=words[k:]
            if start is None or first(' '.join(tail[:3]))!=start or not any(self._started(' '.join(tail[:m]),portion) is not None or match_current(' '.join(tail[:m]),portion,fillers,lenient=False)=='ack' for m in (2,3) if m<=len(tail)):continue
            return not self._ear_other_number(' '.join(tail),portion)
        return False
    def _before_the_next(self,heard,state):
        """g7 (Р031 seed 1): ``heard`` without its tail when the tail is the start of the portion after the one ``state`` waits for, or that whole portion: the
        owner said it ahead of its cue («… 0 процентов первое налог начисляют»), and its numbers («первое») are no other number of this portion."""
        chunks=list(state.get('chunks') or []);index=state.get('chunk_index',0)
        if type(index) is not int or index+1>=len(chunks):return heard
        words=str(heard).split();after=chunks[index+1]
        number=lambda word:bool(norm_words(word)) and (norm_words(word)[0].isdigit() or norm_words(word)[0] in NUMBER_WORDS)
        for k in range(1,len(words)):
            if number(words[k-1]) and number(words[k]):continue       # never inside a number («сто | пятьдесят тысяч»)
            tail=' '.join(words[k:])
            if self._started(tail,after) is not None or match_current(tail,after,resolve(self.settings)['fillers'],lenient=False)=='ack':return ' '.join(words[:k])
        return heard
    def _past_the_veto(self,tid,text,state):
        """c24 P11 (half_hour seed 6 @1711): the ear's other number took a step back (``_ear_late_veto``) after the next portion had sounded, and the owner says that next
        portion whole: he heard it, and he is there. The portion taken back is confirmed as the cloud confirmed it, and this try is judged on the next one.
        ``(state, decision)`` after that step, else None."""
        back=self.veto_back
        if not back or not back[1] or back[0]!=self._position(state):
            self.veto_back=None;return None
        chunks=state.get('chunks') or [];index=state['chunk_index']
        if index+1>=len(chunks) or self._classify(text,{**state,'chunk_index':index+1}).kind!=ACK:return None
        self.veto_back=None
        logger.info('echo-sync decision kind=ack reason=next_after_veto revision=%s index=%s',state['revision'],index)
        self._reply(probe('waiting_portion',state=state).value,f'{self.nonce}:veto:{tid}',decided=command_ruling(ACK),basis=self._basis(state))
        after=self.state()
        return after,self._classify(text,after)
    def _veto_place(self,state):
        """c25-a G6 (Р017 seed 101 and all 15 take-backs of the c24-e seeds: the owner had said the portion's number, the ear misheard it): the portion taken back is
        helped from its first number on (``tempo_start``, rule 3), as a stop before it is: «366 дней.», not «В високосном году 366 дней.» once more."""
        portion=probe('waiting_portion',state=state).value;words=str(portion or '').split()
        number=lambda word:bool(norm_words(word)) and (norm_words(word)[0].isdigit() or norm_words(word)[0] in NUMBER_WORDS)
        at=next((k for k,word in enumerate(words) if number(word)),None)
        if at:self.tempo_start=(self._position(state),' '.join(words[at:]),self.clock());self.rule_helped=None
    def _ear_take(self,tid,run,decision,first=None):
        """Take the cloud's turn ``tid`` with what the ear heard and act on it the way a cloud final is acted on (``_accept_user``). The
        cloud's earlier pieces of the same utterance (``_ear_earlier``) are the take's too: those still open are taken with it (fix round 1,
        item 1), and the tail of the final is found in all of them joined (``_early_tail``). H4: ``first``: the ear opens a question on this turn (``_ear_first``), which it may have
        taken for a confirmation before: the question is then a tail of it. Words that open nothing after all leave the turn to the cloud."""
        state=self.state() or {};job=bool(first and (self.ear_job or 'live' in first));text=first['text'] if job else ' '.join(p['text'] for p in run);kind=self._ear_family(decision) or QUESTION
        if job and first.get('tail'):text=first['asked']      # c25-b case 1: the question at the end of the breath, the one its job was prepared on
        if job and first.get('lookup'):text=(self.ledger.snapshot(tid) or {}).get('text') or text      # c22-speed: the search reads the cloud's open turn, which read as the ear's question (``_turn_reads``): its figures, its «?»
        boundary='ear_first' if first else 'local_ear';again=bool(first) and tid in self.seen;self.tempo_unjudged=[]
        logger.info('echo-sync decision kind=%s reason=%s uid=%s pieces=%s revision=%s index=%s',decision.kind,boundary,run[-1]['uid'],
                    len(run),state.get('revision'),state.get('chunk_index'))
        ear=self._ear_of_take(tid,run,first,text)
        self._ear_taking=(tid,self._ear_mark())
        actions=self._accept_user({**self.ledger.snapshot(tid),'final':True,'text':text},boundary=boundary,tail=again,admitted=bool(job and first['asked'] and not first.get('lookup')),gated=bool(job and first.get('form')=='cloud'),cause='ear_take')
        if first:
            if self.question_id!=tid:
                self._ear_taking=None
                if not again:
                    self.seen.discard(tid);self.user_boundaries.pop(tid,None)
                return actions
            self.user_boundaries[tid]=boundary
        self._ear_took(tid,run,state,kind,ear)
        self._ear_taking=None
        return actions
    def _ear_of_take(self,tid,run,first,text):
        """What a take knows of the utterance: the cloud's earlier turns of it, the question the ear opened (None: a confirmation or a command), the words taken."""
        ear={'earlier':self._ear_earlier(run,tid),'first':first,'text':text}
        if first:first['heads']=[head for head in ear['earlier'] if not (self.ledger.snapshot(head) or {'final':True})['final']]      # a turn final by now was judged by itself
        return ear
    def _ear_took(self,tid,run,state,kind,ear):
        """The turn ``tid`` is the ear's from now on: the final that comes (``_early_tail``) and the turns of the same utterance that follow it (``ear_piece``) are judged as tails of this take; its pieces have acted."""
        self._note_early(tid,state,kind,ear=ear)
        for head in ear['earlier']:
            turn=self.ledger.snapshot(head)
            if turn and not turn['final'] and head not in self.seen:
                self.seen.add(head);self.user_boundaries[head]='local_ear_piece'
                self._note_early(head,state,kind,piece='head',ear=ear)
        self.ear_take={'tid':tid,'state':state,'kind':kind,'when':self.clock(),'offset':run[-1]['offset'],
                       'offset_input_ms':run[-1]['offset_input_ms'],'ear':ear}
        for piece in run:piece['acted']=True
    def _ear_bind_pending(self):
        """A verdict that waits (``ear_heard``: for the cloud to announce its utterance, or a command for the quiet after it to last) takes
        the cloud's turn once it may, when the verdict still stands and the turn is its utterance's; actions, or None. Called when a user
        turn of the cloud appears or grows, and on every tick."""
        pending=self.ear_pending
        if pending is None or self.clock()<pending['not_before']:return None
        alone=pending['kind']==ACK and self.fast_call and self.clock()>pending['deadline']
        if not alone and self._ear_expire(self.clock()):return None
        decision,why=self._ear_verdict(pending['run'])
        if decision is None or self._ear_family(decision)!=pending['kind']:
            self.ear_pending=None
            logger.info('echo-sync ear act=dropped reason=%s uid=%s',why or 'verdict_changed',pending['run'][-1]['uid'])
            return None
        tid,why=self._ear_turn(pending['run'],decision)
        if tid is None and (self._ear_stop(decision,pending['run'],self.state()) or self._ear_alone(decision,pending['run'],why,alone)):
            self.ear_pending=None
            return self._ear_stops(pending['run'],decision)
        if tid is None:
            if why!='no_open_turn' or alone:
                self.ear_pending=None
                logger.info('echo-sync ear act=dropped reason=%s uid=%s',why if why!='no_open_turn' else 'not_announced',pending['run'][-1]['uid'])
            return None
        self.ear_pending=None
        return self._ear_take(tid,pending['run'],decision)
    def _ear_expire(self,now):
        """A verdict whose utterance the cloud has not announced within EAR_BIND_SECONDS is given up: the cloud decides alone. True if so."""
        pending=self.ear_pending
        if pending is None or now<=pending['deadline'] or (pending['kind']==ACK and self.fast_call):return False     # g25: a confirmation the cloud never announced is ``_ear_bind_pending``'s (``_ear_alone``)
        self.ear_pending=None
        logger.info('echo-sync ear act=dropped reason=not_announced uid=%s',pending['run'][-1]['uid'])
        return True
    def ear_piece(self,turn):
        """Is ``turn`` (a user turn the cloud has just announced: a provider ``turn`` dict or a ledger snapshot) a later piece of the
        utterance the ear took last - the cloud cut it where the ear did not («свойство тела» | «сопротивляться…»)? Only when the ear has
        heard no speech begin since that take and the turn comes within EAR_PIECE_SECONDS of the end the ear heard; and when the provider
        says where the turn's speech began, that was before that end (EAR_PIECE_GRID_MS of its grid allowed). The transport does not cut the
        cue that is playing for such a turn, and its words are only a tail of the take (``_early_tail``)."""
        return self._ear_safely(self._ear_piece,turn,default=False)
    def _ear_piece(self,turn):
        take=self.ear_take
        if not take or not isinstance(turn,dict) or turn.get('role')!='user' or take['offset'] is None:return False
        if self.ear_onset_at is not None and self.ear_onset_at>take['when']:return False
        limit=EAR_FIRST_BIND_SECONDS if take.get('stop') else TEMPO_ANNOUNCE_SECONDS if (take.get('ear') or {}).get('first') else EAR_PIECE_SECONDS
        if take.get('stop') and turn.get('final') and (turn.get('text') or '').strip() and self._ear_family(self._classify(turn['text'],take['state']))==take['kind']:limit=max(limit,TEMPO_HOLD_SECONDS)      # g25: the cloud's final of the very command the ear carried out alone, however late: one act
        if not within(self.clock(),take['offset'],limit):return False
        start=self._speech_start_ms(turn)
        end=take['offset_input_ms']
        return not (start is not None and type(end) in (int,float) and start>=end-EAR_PIECE_GRID_MS)
    def _ear_claim_piece(self,tid):
        """Take ``tid``, a later piece of the utterance the ear took (``ear_piece``): it acts no more, its words are a tail of that take."""
        take=self.ear_take
        self.seen.add(tid);self.user_boundaries[tid]='local_ear_piece'
        self._note_early(tid,take['state'],take['kind'],piece=True,ear=take.get('ear'))
        logger.info('echo-sync decision kind=silent reason=local_ear_piece revision=%s',(take['state'] or {}).get('revision'))
    # ---- H4: the ear first (``fast_text`` = "on", an acting ear; see EAR_RELEASE_SILENCE_SECONDS) ------------------------------------------------------------------
    def _ear_first(self,run,piece):
        """The ear's text that no verdict took (``_ear_heard``): may a question open on it, before the cloud's final? Then it does, at once or when its conditions hold (``_ear_first_due``). Not on an utterance
        that goes on, nor over a cue that may be heard back: in any doubt the ear does nothing, and the final comes as ever. Unlike a confirmation it does not ask where the call stood when the speech began (``_ear_mark``): a
        question stands on its own, and the cloud's final of the utterance before comes during this one (55.2 of the call, inside 53.07-56.22). Returns the actions."""
        if not self.fast_call or piece['offset'] is None or self._ear_goes_on(piece):return []
        first=self._ear_opens(run,self.state())
        if first is None:return []
        began=first['run'][0]['onset']
        if self.cue_heard and self.cue_window and self.cue_window[0]<=began and not self._tempo_over(began):       # begun before the cue it cannot be that cue heard back
            logger.info('echo-sync ear first=no reason=during_cue uid=%s',piece['uid'])
            return []
        first['deadline']=self.clock()+(EAR_FIRST_BIND_SECONDS if first['hit'] else EAR_BIND_SECONDS+FIRST_TEXT_S)
        self.ear_first=first
        logger.info('echo-sync ear first=waits kind=%s uid=%s pieces=%s','reference' if first['hit'] else 'question',piece['uid'],len(first['run']))
        # H1 prepares on one utterance of the ear: a question cut by a breath gets its job here
        prepare=[{'type':'fast','op':'prepare','text':first['asked']}] if first['asked'] and (len(first['run'])>1 or self.ear_job) and not first.get('lookup') else []
        return prepare+(self._ear_first_due() or [])
    def _ear_opens(self,run,state):
        """What of the pieces of ``run`` a question may open on: ``{'run', 'text', 'decision', 'hit', 'asked'}``, or None. Rule 1, ``hit``: the answer of the base; the longest reading first («двадцать» | «первая статья …»
        is article 21). The answer in play is no new question: the final decides that one as it always did. Rule 2, ``asked``: the text of the job, whose form is strong and which does not stop at a function word: the last
        piece when it is that by itself (what came before it may be a remark), else the longest reading."""
        known=[]
        for piece in reversed(run):
            if piece['text'] is None or piece['onset'] is None:break
            known.insert(0,piece)
        for at in range(len(known)):
            text=' '.join(p['text'] for p in known[at:]);decision=self._ear_may_open(text,state)
            if not decision and self._bank_asks(text,state):decision=Decision(QUESTION,'bank_question',probe('strip_fillers',text,settings=self.settings).value or text,None)      # h28: «can it be answered» is the test on the ear too: «контрольная функция финансов» has no form of a question
            hit=self._reference(text) if decision else None
            if hit and at and hit==quick_answer(text):continue      # a figure reads all of the run: «раздели» | «сто на пять» is no 500
            if hit and hit!=self.published and not self._ear_misheard(text,state) and not self._said_back(text,ahead=state):return {'run':known[at:],'text':text,'decision':decision,'hit':hit,'asked':None}
        if not known or not self.fast_on or not self.prepared_job or self.lookup_policy!='required':return None
        if self.ear_job:return self._ear_opens_job(state)
        for at in [len(known)-1]+list(range(len(known)-1)):
            text=' '.join(p['text'] for p in known[at:]);decision=self._ear_may_open(text,state)
            asked=probe('strip_fillers',text,settings=self.settings).value.strip()
            if (decision and decision.kind==QUESTION and decision.reason in EAR_STRONG_FORMS and self._fast_preparable(asked) and norm_words(asked)[-1] not in FUNCTION_WORDS and not probe('open_tail',asked).value):
                return {'run':known[at:],'text':text,'decision':decision,'hit':None,'asked':asked}
        return None
    def _ear_opens_job(self,state):
        """c16 (c15-cand-f: 14 of 20 first answers had no ``ear first`` at all): rule 2 asked for a strong form, on at most three pieces, and most questions of a call have none while a portion waits («Выручка и прибыль, это одно и то же»)
        or come after a preface. Here all the ear heard of the breath goes (a condition said in an earlier piece is the question's), in any form a final could be judged in (``_ear_may_open``): whether it asks is what a final with no form
        is judged by, the job's text (``_ear_first_ready``). The witness is the rule of an adoption on the cloud's open turn (``_ear_first_turn``). It does not stop on an open tail; a particle is no such tail («это одно и то же»)."""
        said=[piece for piece in self.ear_said if piece['offset'] in {ended for ended,_ in self.wide_breath} and piece['text'] and piece['onset'] is not None]
        spoken=[at for at,piece in enumerate(said) if piece['acted']]
        said=said[spoken[-1]+1:] if spoken else said
        if not said or self._at_the_answer(' '.join(piece['text'] for piece in said),state):return None
        text='. '.join(piece['text'] for piece in said);asked=probe('strip_fillers',text,settings=self.settings).value.strip();part=probe('question_part',asked).value;words=norm_words(part)
        decision=self._ear_may_open(text,state);form=None
        if not decision and self.cloud_form:decision,form=self._ear_formless(text,state),'cloud'      # c22-speed: the ear hears no «?»: the cloud's open turn must ask (``_turn_reads``)
        tail=self._ear_tail(asked,state) if self.cloud_form and not word_problem(part) and (not decision or decision.kind!=QUESTION or not self._fast_routed(part)) else None
        if tail:asked,part,words,decision,form=tail,probe('question_part',tail).value,norm_words(probe('question_part',tail).value),self._classify(tail,self._heard_with(state)),'cloud'      # c25-b case 1: the question at the end of a long breath; the cloud's open turn must ask
        if tail and decision.kind!=QUESTION:decision=Decision(QUESTION,'ear_tail',tail,None)
        sum_told=self.cloud_form and word_problem(part) and route_need(part,(state or {}).get('history',()))!=CHANGES      # c25-b: a word problem: the cloud's open turn must ask it too
        if not decision and sum_told:decision,form=Decision(QUESTION,'word_problem',part,None),'cloud'
        lookup=self.ear_lookup and not sum_told and not self._fast_routed(part) and self._lookup_routed(part)      # c22-speed: the search route opens on the two witnesses too, the job waits for its source
        if not decision or len(norm_words(asked))<PREPARE_MIN_WORDS or not words or probe('open_tail',part).value or not (lookup or sum_told or self._fast_routed(part)) or self._reference(asked):return None
        return {'run':said,'text':text,'decision':decision,'hit':None,'asked':asked,'form':form,'lookup':lookup,**({'tail':True} if tail else {})}
    def _ear_tail(self,asked,state):
        """c25-b case 1 (stand, phone times: a question after a 20-word preface in one breath, the cue 5.4-6.0 s instead of 2.3-2.9 s): the ear writes no comma nor «?», so the whole breath is ``not_a_question``
        (the question word is past the window) and a «у меня» of the preface keeps it from the job. The question at its end: from «если» of a word problem, else from the first question word (its preposition
        kept) of the last ``EAR_TAIL_WORDS`` words whose rest is a question the job's route takes. None: no such clause. The words before it are a preface; the cloud's open turn must ask (``form`` 'cloud')."""
        words=asked.split()
        if len(words)<=PREPARE_MIN_WORDS:return None
        low=[normalize(w) for w in words];start=max(1,len(words)-EAR_TAIL_WORDS);history=(state or {}).get('history',())
        for at in range(start,len(words)-PREPARE_MIN_WORDS+1):
            if low[at]=='если' and word_problem(' '.join(words[at:])):return ' '.join(words[at:])
        for at in range(start,len(words)-PREPARE_MIN_WORDS+1):
            if low[at] not in QUESTION_WORDS or low[at] in ('можно','нужно','правда','верно','можешь','что','как'):continue
            at-=low[at-1] in ('в','на','с','о','об','по','до','от','из','за','у','к','при','для')
            tail=' '.join(words[at:])
            if (self._classify(tail,self._heard_with(state)).kind==QUESTION and self._fast_routed(probe('question_part',tail).value) and route_need(tail,history)!=CHANGES
                    and not self._reference(tail)):return tail
            return None
        return None
    def _ear_formless(self,text,state):
        """c22-speed (``cloud_form``): the verdict of a final with no form that the cloud's final would give to the brain (``_open_to_the_cloud``) but for the text gate, which reads the ear's words
        without their «?» («нужно не увеличивать а уменьшать эту жидкость» is a ``statement`` to it). None for a repeat, a command, a try, words to the plan."""
        if self.suspended and self._said_to_the_plan(text,state):return None
        decision=self._classify(text,self._heard_with(state))
        if decision.kind!=QUIET or self._effective_reason(text,state,decision) not in _FOR_THE_BRAIN or not _content(text) or self._late_try(text,state):return None
        words=norm_words(probe('strip_fillers',text,settings=self.settings).value)
        if not words or not (probe('not_this_but',' '.join(words)).value or words[0] in _YES_NO_HEADS):return None      # only a form the ear loses with the «?»: «нужно не X, а Y», «можно …»; chatter and a cue said back open nothing
        portion=probe('waiting_portion',state=state).value
        if portion is not None and (self._said_back(text) or most_said(' '.join(words),portion) or self._tempo_verdict(text,text,state,portion)[0]=='try'):return None      # fuzz seed 272: the portion's words are a try to the ear
        return decision
    def _ear_misheard(self,text,state):
        """The words of the portion that waits with another number: the ear gets numbers wrong (c9-numveto), and the base has that article too. It may be the portion misheard: the final decides."""
        portion=probe('waiting_portion',state=state).value;said={item[0] for item in _content(text) if not item[4]}
        return bool(portion and said and said<={item[0] for item in _content(portion)} and self._ear_other_number(text,portion))
    def _ear_may_open(self,text,state):
        """The classifier's verdict on ``text`` when a question may open on it: it is one, or it is a final with no form that the cloud's final would make a candidate of (``_open_to_the_cloud``). None for a repeat, a
        command, a try, and for words said to the plan a question took over."""
        if self.suspended and self._said_to_the_plan(text,state):return None
        if self._read_again(text,state) or self._landmark_said(text,state):return None      # c24-c: the question of the answer being written, read again; a word of it named: no job
        decision=self._classify(text,self._heard_with(state))
        if decision.kind==QUESTION:return decision
        return decision if decision.kind==QUIET and self._open_to_the_cloud(text,self._effective_reason(text,state,decision),state) else None
    def _landmark_said(self,text,state):
        """c24-c: «повтори со слова …», «я записал …» while a portion waits: said to the plan, never a question (whether the word is there or not)."""
        return bool(isinstance(text,str) and probe('waiting_portion',state=state).value is not None and landmark_command(probe('strip_fillers',text,settings=self.settings).value or text))
    def _read_again(self,text,state):
        """c24-c: dictating, ``text`` is the question of the plan whose portion waits, read again: the same words, numbers, «не» and their roles both ways (``same_question``). Its answer is in hand: the
        portion is said again from its start, the place kept, nothing asked anew. Another number, a «не», another question: no."""
        asked=(state or {}).get('question')
        if not self.dictation or not asked or not isinstance(text,str) or probe('waiting_portion',state=state).value is None or (state or {}).get('paused'):return False
        strip=lambda said:probe('strip_fillers',said,settings=self.settings).value
        return len(norm_words(strip(text)))>=2 and same_question(text,asked,strip=strip) and same_question(asked,text,strip=strip)
    def _bank_first(self,first):
        """h28: is this the ear's hit of the base, to be said on the ear alone: no figure worked out of its words, no open turn of the cloud whose words go another way."""
        if not first['hit'] or self._ear_sum(first):return False
        user=self.ledger.latest_user();cloud=user['text'] if user and user['valid'] and not user['final'] and user['id'] not in self.seen and self._said_words(user['text']) else ''
        return not cloud or any(same_start(first['text'],tail,strip=lambda said:probe('strip_fillers',said,settings=self.settings).value,open_end=True) for tail in self._cloud_tails(first,user['id'],cloud))
    def _ear_sum(self,first):
        """Q1, the skeptic: is what would open a figure worked out from the ear's words (``quick_math``)? The ear gets numbers wrong (c9-numveto), and ``same_start`` leaves the last word of a partial open and a turn with no word
        yet open altogether: such a cue was said to its end (0.5 s) long before the final could cut it (2.2 s on the phone). So it waits until the ear's silence says the utterance is over, a number can still grow, and
        until the cloud's open turn, read by the same code, gives the same figure (about 1.06 s on the phone): two witnesses of every number and of every word around them, whoever cut the utterance where. A hit of the
        base stays rule 1. What they both got wrong the final cuts."""
        return bool(first['hit'] and ((quick_answer(first['text'])==first['hit']) or (self.prepared is not None and self._witness(first['text'])==first['hit'])))
    def _ear_first_passed(self,turn):
        """A final has come. Of the utterance the ear waited to open: that is the cloud's verdict on it now, a final of an older turn changes nothing here. So it must say these words, not only what came before them
        in the same turn (``_ear_said_of``: a head of that is the turn before, its rest still to come)."""
        strip=lambda text:probe('strip_fillers',text,settings=self.settings).value;text=self.ear_first['text']
        if same_question(text,turn['text'],strip=strip) or said_within(turn['text'],text,strip=strip) or ((self.ear_job or 'live' in self.ear_first) and self._ear_reads(self.ear_first,turn['text'])):self._ear_first_drop('final_came')
    def _ear_first_again(self,turn):
        """The final of another turn that says what the ear opened, with no speech begun since: the cloud cut its turns elsewhere than the ear, here or in a piece it claimed (``ear_piece``). Actions, nothing opens twice; the
        model may have asked for a search on this turn, it is told there is none. A rest that says something else after a final that was only a head of what the ear heard: the two together are what the cloud heard
        (``_ear_first_overruled``). False: it is a final of its own."""
        take=self.ear_take;first=(take.get('ear') or {}).get('first') if take else None;tid=turn['id']
        if not first or tid==take['tid'] or take['tid']!=self.question_id:return False
        claimed=(self.early_taken.get(tid) or (None,)*5)[4] is True
        if tid in self.seen and not claimed:return False
        if not claimed and self.ear_onset_at is not None and self.ear_onset_at>take['when']:return False
        strip=lambda text:probe('strip_fillers',text,settings=self.settings).value
        if not any(text and said_within(text,turn['text'],strip=strip) for text in self._ear_said_of(first,take['tid'])):
            if claimed:      # it says something else: no piece of what was opened
                self.early_taken.pop(tid,None);self.seen.discard(tid);self.user_boundaries.pop(tid,None)
            head=self.ledger.snapshot(take['tid'])
            whole=f"{head['text']} {turn['text']}" if head else ''      # the head and its rest are what the cloud heard: it is the two together that the ear's words are judged against (the head alone is only a part of them)
            if head and head['final'] and same_start(first['text'],head['text'],strip=strip,open_end=False) and self._late_correction(first['text'],whole,inside=False):
                return self._ear_first_overruled(turn,whole)
            return False
        self.early_taken.pop(tid,None);self.seen.add(tid);self.user_boundaries[tid]='local_ear_piece';self.fast_passed=tid
        logger.info('echo-sync decision kind=silent reason=ear_first_piece revision=%s',(self.state() or {}).get('revision'))
        return self._fast_no_search(tid)
    def _ear_first_drop(self,why):
        logger.info('echo-sync ear first=dropped reason=%s uid=%s',why,self.ear_first['run'][-1]['uid'])
        self.ear_first=None
    def _ear_first_turn(self,first):
        """The cloud's open turn of what the ear heard: ``(tid, None)`` or ``(None, why)``. Its words so far say so (E86 ``_two_witnesses``: the stable piece agrees, ``_ear_agrees``); with no word yet it is no second witness. Unlike a confirmation's
        (``_ear_turn``) the clock of the turn is not asked: the words are there to say it, and the cloud's start of speech came up to 3 s behind the ear's on the phone. A turn the ear took for a confirmation or a command may
        go on with the question (rule 2 needs no turn of its own): it opens there, a tail of that turn.
        A question that only the local ear has heard so far gets its answer at once; if the cloud heard otherwise, the answer is corrected (26.11-3): an open turn with no word of the cloud yet is no reason to wait."""
        user=self.ledger.latest_user()
        if not user or not user['valid'] or user['final'] or user['id'] not in self.announced_at:return None,'no_open_turn'
        tid=user['id'];taken=self.early_taken.get(tid)
        if tid in self.seen and (first['decision'].kind!=QUESTION or taken is None or taken[4] or (taken[5] or {}).get('first')):return None,'no_open_turn'
        if 'live' in first:return self._live_reads(first,tid,user['text'])
        if self._ear_sum(first):return (tid,None) if self._witness(user['text'])==first['hit'] and (user['text'][-1:] in ' .,!?…;:' or self.clock()-(self.cloud_heard or 0.0)>=FIGURE_STILL_SECONDS) else (None,'cloud_behind')
        if self._said_words(user['text']) and self.ear_job:return self._turn_reads(first,tid,user['text'])
        if self._said_words(user['text']):return self._two_witnesses(first,tid,user['text'])
        if first['decision'].kind==QUESTION and first.get('form')!='cloud':return tid,None      # 26.11-3: a question the ear alone has heard is answered at once; the final corrects it (``_ear_first_overruled``)
        return None,'cloud_behind'      # no form of a question yet: the cloud's words are the witness of it
    def _two_witnesses(self,first,tid,cloud):
        """E86: ``(tid, None)`` when the stable piece of the cloud's open turn (``two_witnesses.Pieces``) witnesses what the ear heard (``two_witnesses.verdict``) and goes its way (``_ear_agrees``); a piece
        that goes another way is ``cloud_disagrees`` (the final decides, nothing sounds), too little of it ``cloud_behind`` (the ear waits for more, up to its deadline)."""
        pieces=self.__dict__.setdefault('witness_pieces',two_witnesses.Pieces())
        piece=pieces.feed(tid,cloud,still=self.clock()-(self.cloud_heard or 0.0)>=FIGURE_STILL_SECONDS)
        strip=lambda text:probe('strip_fillers',text,settings=self.settings).value
        verdicts=[two_witnesses.verdict(first['text'],tail,strip=strip) for tail in self._cloud_tails(first,tid,piece)]      # DEF2: the cloud's turn glues the breaths the ear heard apart (``_cloud_tails``): what was said before the question is no disagreement, whichever tail goes the ear's way
        verdict=two_witnesses.SOUND if two_witnesses.SOUND in verdicts else two_witnesses.WAIT if two_witnesses.WAIT in verdicts else two_witnesses.CUT
        if verdict==two_witnesses.CUT:return None,'cloud_disagrees'
        if verdict==two_witnesses.WAIT:return None,'cloud_behind'
        return (tid,None) if self._ear_agrees(first,tid,cloud) else (None,'cloud_disagrees')
    def _turn_reads(self,first,tid,cloud):
        """c16: ``(tid, None)`` when the cloud's open turn, as far as it has got, reads as what the ear opened. A preface at its head is no disagreement (34 of 80 ``ear first`` of the night ended there, each time for good, the question's
        words still to come): anything else waits for more of the cloud, and the final decides. A number or «не» at its very end may still grow: it waits (``stable_text``)."""
        words=norm_words(cloud)
        closed=self.turn_mark and cloud.rstrip()[-1:] in two_witnesses.CLOSING and words and words[-1] not in ('не','ни')      # c22-speed: no number grows past a «?» (G32, ``two_witnesses.Pieces``)
        if not words or (_protected_word(words[-1]) and not closed):return None,'cloud_behind'
        if first.get('form')=='cloud' and not self._cloud_asks(cloud):return None,'cloud_behind'
        return (tid,None) if self._ear_reads(first,cloud) else (None,'cloud_behind')
    def _cloud_asks(self,cloud):
        """c22-speed (``cloud_form``): the cloud's open turn is a question by its form (the classifier) and no talk to the text gate: the witness of the form the ear cannot hear."""
        return self._form_verdict(cloud,self.state())
    def _form_verdict(self,text,state):
        """U15: the one verdict of a text's form - a question by the classifier and no talk to the text gate: the single place where the two layers are combined (``_cloud_asks`` asks it of the cloud's open turn)."""
        return self._classify(text,self._heard_with(state)).kind==QUESTION and not self._gate_talk(text)
    def _live_stable(self,user,heard):
        """``live_first``: the cloud's partial stands still and the ear is silent. GPT-Live's reply is never first (6 Nov, from the end of speech, phone and probe: its first fragment comes with its final, 3.17 s and 1.67 s, a whole clause of it at about
        6.9 s and 5.6 s, a job at the final at 4.3 s and 3.1 s), but what it heard is complete at 1.67 s and 0.73 s, and it reads what the ear cannot (КО-2). So a job goes on that text, or the one the ear began stays when it fits: only when the cloud has
        caught up with the ear (``caught_up``: a still partial alone was a head of the final in 14 of 18), and a question may open on it, with no final. Nothing is loosened: the ear must not dispute a number, a code or a «не» (``ear_disputes``), the words of
        the turn must still be those the job was asked, and its text must keep their numbers (``_live_reads``). What the final then says otherwise cuts the cue and is answered at once (``_ear_first_final``). Returns the actions."""
        strip=lambda text:probe('strip_fillers',text,settings=self.settings).value
        if not caught_up(heard,user['text'],strip=strip):return []
        prepared=self._fast_wide(user['text'],'partial')
        if not prepared or not self.fast_call:return prepared
        first=self.ear_first;asked=prepared[0]['text'];state=self.state();decision=self._ear_may_open(asked,state)
        run=[piece for piece in self.ear_said if piece['offset'] in {ended for ended,_ in self.wide_breath} and piece['text'] and piece['onset'] is not None and not piece['acted']]
        if not decision or not run or (first is not None and first['hit']) or self._ear_goes_on(run[-1]):return prepared
        began=run[0]['onset']
        if (self.cue_heard and self.cue_window and self.cue_window[0]<=began and not self._tempo_over(began)) or ear_disputes(heard,user['text'],strip=strip):      # the rule of ``_ear_first``: it may be that cue heard back
            logger.info('echo-sync ear first=no reason=live_disputed uid=%s',run[-1]['uid'])
            return prepared
        if first is not None:self._ear_first_drop('live_first')
        self.ear_first={'run':run,'text':asked,'decision':decision,'hit':None,'asked':asked,'live':user['text'],'deadline':self.clock()+EAR_BIND_SECONDS+FIRST_TEXT_S}
        logger.info('echo-sync ear first=waits kind=live uid=%s pieces=%s',run[-1]['uid'],len(run))
        return prepared+(self._ear_first_due() or [])
    def _live_reads(self,first,tid,cloud):
        """``live_first``: ``(tid, None)`` when all the cloud holds is what the job was asked and what the job has said keeps its numbers (``answer_keeps``). Words it has gained since or a job gone another way leave the question to the final."""
        if cloud!=first['live']:return None,'cloud_disagrees'
        said=self.prepared_job(first['asked'])
        if not said or not answer_keeps(first['asked'],brain_answer(said[0]),strip=lambda text:probe('strip_fillers',text,settings=self.settings).value):return None,'job_disagrees'
        return tid,None
    def _ear_said_of(self,first,tid):
        """What the ear heard of the cloud's turn ``tid``: the text the question opened on, or that with every piece before it since the listener's last final of another turn: one turn of the cloud may hold several
        utterances of the ear (143.7-150.4 of the call: the repeat, a remark, the question). What was said after it is no agreement: it is more than the question that opened."""
        floor=self._ear_floor(tid);last=first['run'][-1]['onset']
        return first['text'],' '.join(p['text'] for p in self.ear_said if p['text'] and p['onset'] is not None and (floor is None or p['onset']>=floor) and p['onset']<=last)
    def _ear_agrees(self,first,tid,cloud,final=False):
        """Do the cloud's words of the turn go the way the ear heard them? ``final``: the same question (``same_question``), or a head of it: the cloud cut the utterance, its rest is another turn."""
        strip=lambda text:probe('strip_fillers',text,settings=self.settings).value
        if final and 'live' in first:return same_question(first['text'],cloud,strip=strip)      # what was said went on these words: a final that says more is what the job was not asked
        heard=[text for text in self._ear_said_of(first,tid) if text]
        if final and self.ear_job and self._ear_reads(first,cloud):return True
        if final and any(same_question(text,cloud,strip=strip) for text in heard):return True
        return any(same_start(text,tail,strip=strip,open_end=not final) for text in heard for tail in ([cloud] if final else self._cloud_tails(first,tid,cloud)))
    def _cloud_tails(self,first,tid,cloud):
        """Fable 10.11 (20:54, 28.9 s: the ear heard the bank's question whole, the cloud's open turn was the breath before it and the head of this one in one piece, the ear's question was dropped as
        ``cloud_disagrees`` and the bank's answer waited 2.7 s for the final). The cloud's words of the open turn, and the same without the head the ear heard as EARLIER breaths (or as a hesitation):
        the cloud glues breaths the ear cuts, that is no disagreement. What is left must still go the ear's way (``same_start``)."""
        onset=first['run'][0].get('onset');floor=self._ear_floor(tid);before=set(_HESITATES)
        for piece in self.ear_said:
            if piece['text'] and piece['offset'] is not None and onset is not None and piece['offset']<=onset and (floor is None or piece['offset']>=floor):before|=set(norm_words(piece['text']))
        words=str(cloud).split();tails=[cloud]
        for at,word in enumerate(words[:-1]):
            if not set(norm_words(word))<=before or self._protected_atoms(word)[0]:break      # a number, a unit, a «не» said before the question is its condition, heard earlier or not: it is never dropped
            tails.append(' '.join(words[at+1:]))
        return tails
    def _ear_heard_since(self,first,rest):
        """Fable 10.11 (the call of 07.11 21:12 replayed: the place jumped back twice). One stretch of speech has one owner: what the ear heard after its question it has acted on itself, breath by breath (a
        repeat of the cue moved the place then); the same words in the cloud's final are not judged a second time. ``SAID_ALREADY_SHARE`` of the rest's words in the ear's later pieces."""
        end=first['run'][-1].get('offset');words=set(norm_words(rest));heard=set()
        for piece in self.ear_said:
            if piece['text'] and piece['onset'] is not None and end is not None and piece['onset']>=end and piece['acted']:heard|=set(norm_words(piece['text']))
        return bool(words) and len(words&heard)>=SAID_ALREADY_SHARE*len(words)
    def _ear_first_final(self,turn,whole,first):
        """The final of a turn the ear opened a question on, ``whole`` its words with the cloud's earlier turns of the utterance (those are told by their time, and the cloud's times lag: an older turn may be among
        them, so its own words count alone too). The same question, or for a reference the same answer of the base: nothing happens, nothing opens twice. Anything else is what the cloud heard and the ear did not
        (``_ear_first_overruled``). Unless it is no word on it at all (``_ear_first_other``), or the question and then the listener's repeat of the cue, in one turn (``_ear_first_rest``)."""
        rest=self._ear_first_rest(first,turn['id'],turn['text'])      # Fable 10.11: looked at first: a final that says the question AND more is confirmed for the question, and the rest is judged as a turn of its own (it was lost: the same answer of the base «confirmed» the whole)
        if rest and not first.get('cut') and not self._ear_heard_since(first,rest):
            logger.info('echo-sync ear first=confirmed rest=judged revision=%s',(self.state() or {}).get('revision'))
            return self.provider({'type':'turn.done','turn':{'id':f"{turn['id']}:rest",'role':'user','transcript':rest}})
        if first.get('cut'):return self._ear_first_overruled(turn,whole)      # W13 item 2: the instant hit was cut by new words: the cue never sounds, the question goes the usual way
        if any(self._ear_agrees(first,turn['id'],said,final=True) or (first['hit'] and self._reference(said)==first['hit']) or self._ear_goes_past(first,said) for said in (turn['text'],whole)):
            logger.info('echo-sync ear first=confirmed revision=%s',(self.state() or {}).get('revision'))
            return self._context_action() if self.ear_lookup and self.grounded and not self.context_requested else []      # c22-speed: the sources found before the final reach the cloud now
        if self._ear_first_other(turn['text'],first):
            logger.info('echo-sync ear first=another_turn revision=%s',(self.state() or {}).get('revision'))
            return []
        return self._ear_first_overruled(turn,self._ear_utterance_text({'earlier':first.get('heads')},turn['text']))
    @staticmethod
    def _ear_goes_past(first,said):
        """h29 (1074 s: the ear's head of a task opened the base's answer, the final of the whole task took it away): a final that holds the ear's words whole only goes on past them: the answer stands."""
        if not first['hit']:return False      # round 3: only the base's answer stands over a longer final; the answer of a JOB was made on the ear's words and the rest («в Киеве, и кто его провёл») is judged by a job on the whole (h5: the final that shows the utterance went on)
        if first['hit']==quick_answer(first['text']):return False      # «пять на пять метров, это сколько квадратных»: a figure reads all that was said (``_figure``)
        heard=norm_words(first['text'])
        whole=f" {' '.join(norm_words(said))} ";at=whole.find(f" {' '.join(heard)} ")
        return len(heard)>=3 and at>=0 and ' не ' not in whole[at+len(' '.join(heard))+1:]      # h31: «что такое инфляция не в экономике, а в космологии» is another question
    def _ear_first_other(self,text,first):
        """Is this final no word on what the ear opened? An empty turn of the cloud may be the one of the utterance before: on the phone it came during the next (53.07 the ear, 53.3 the turn, 55.2 its final). A backchannel
        («Ага», 62.9 of the call) or the words of an utterance the ear heard before this one are that turn's. What was opened stands, and the turn of its own words is a piece of it (``_ear_first_again``)."""
        if (not _content(text) or self._backchannel(text)) and not doubts(text) and self._ear_family(self._classify(text,self.state())) is None:return True
        strip=lambda said:probe('strip_fillers',said,settings=self.settings).value;began=first['run'][0]['onset']
        older=[p['text'] for p in self.ear_said if p['text'] and p['onset'] is not None and p['onset']<began]
        return any(same_question(' '.join(older[at:]),text,strip=strip) for at in range(len(older)))
    def _ear_first_rest(self,first,tid,text):
        """The cue now comes before the cloud has closed the turn of the question, which can hold seconds of silence (177.4-237.0 of the call: 2.2 s): the listener's repeat lands in it. What the final says after the question,
        when it is said to the portion that waits: a repeat, a command, or a try. Else ''."""
        tokens=text.split();state=self.state();strip=lambda said:probe('strip_fillers',said,settings=self.settings).value;rests=[];heard=[said for said in self._ear_said_of(first,tid) if said]
        for count in range(len(tokens)-1,0,-1):
            head,rest=' '.join(tokens[:count]),' '.join(tokens[count:])
            if any(same_question(said,head,strip=strip) and said_within(head,said,strip=strip) for said in heard) or (first['hit'] and self._reference(head)==first['hit'] and heard and len(norm_words(strip(head)))>=min(len(norm_words(strip(said))) for said in heard)):rests.append((rest,self._classify(rest,state),head[-1:] in '.?!,;:…' and _stems(strip(head))<=set().union(*(_stems(strip(said)) for said in heard))))      # Fable 10.11: the head is no shorter than what the ear heard: a cut inside the question leaves no rest. The third: the head is the ear's question and no word more, and the cloud ends it with a mark: only then what follows is another sentence («Пять на пять метров, это сколько квадратных?» goes on with the SAME question: the whole final is it)
        return next((rest for rest,decision,_ in rests if self._ear_family(decision)),'') or next((rest for rest,decision,_ in rests if self._effective_reason(rest,state,decision) in ATTEMPT_REASONS),'') or next((rest for rest,decision,apart in reversed(rests) if apart and decision.kind==QUESTION),'')      # Fable 10.11: a new question after the one opened is the longest such rest
    # ---- H3: the local ear keeps the tempo (see TEMPO_STEP_SECONDS) ---------------------------------------------
    # ``ear_speech`` is told what the detector hears as it hears it; ``tempo_heard`` gets the text of an utterance on the transport's tick, acting ear or not. A cue of these rules goes out where the silence timer's
    # always did (``tick``: counted, capped, ``_missing_part``): the rules only say when. Nothing here touches a confirmation: that is the ear's (``ear_heard``) and the cloud's, as ever.
    def ear_speech(self,uid,what):
        """The ear's detector (``ShadowEar.on_speech``): 'onset' and 'offset' of utterance ``uid``. 'live': the ear runs, from now on it keeps the tempo. 'lost': it has gone, the cloud keeps the flag again."""
        self._tempo_safely(self._tempo_speech,uid,what)
    def _cloud_stands_in(self,ear,cloud,figure):
        """g1-ladder L0 (the final lost, the ear «чем отличается относительная от абсолютной» of the cloud's «...относительная ссылка от абсолютной?»): the cloud's open words, still for
        FIGURE_STILL_SECONDS, are the question when they are no shorter than the ear's but a word, hold every word the ear heard but one in five (at least one), and agree with it on every number and «не»
        (``fast_text._protected``); no figure on either side (a figure is two witnesses or none). Anything else: the contradiction stands, nothing sounds."""
        from .fast_text import _atoms,_protected
        if not cloud or figure or quick_answer(cloud) or self.cloud_heard is None or self.clock()-self.cloud_heard<FIGURE_STILL_SECONDS or not self._has_content(cloud):return False
        heard,have=_atoms(probe('strip_fillers',ear,settings=self.settings).value),_atoms(probe('strip_fillers',cloud,settings=self.settings).value)
        words={atom.atom for atom in have}
        if not heard or len(have)<len(heard)-1 or sum(atom.atom not in words for atom in heard)>max(1,len(heard)//5):return False
        return _protected(heard)==_protected(have)
    def _ear_final_due(self,now):
        """H6 item 6 (n1_02 step 12: speech nobody judges): no final came by EAR_FINAL_SECONDS after speech with content: the job runs on the ear's text and its verdict stands: no grammar has a say on a text of the ear, whatever it shares with the portion
    (only the base's answer comes first, as ever). On the open turn of the cloud, if it has one (its final, should it come, finds it judged); else on a turn of the ear's, and a final of the same words that comes later is that turn's (``_ear_said_it``).
    A job past this bound gets no second chance: 8 s are up. Only an acting ear stands in: a shadow ear lets nothing go (W9-A1)."""
        if not self.fast_on or self.ear_off or self.modes['local_ear']!='act' or not self.tempo_unjudged or self.tempo_speaking or self.tempo_awaits is not None or now<self.tempo_unjudged[-1][0]+EAR_FINAL_SECONDS:return []
        if self._fast_running() or (self.candidate and 'job' in self.candidate):return []      # a job at work: it decides what comes next
        ended=self.tempo_unjudged[-1][0];near=[said for at,said in self.tempo_unjudged if ended-at<=EAR_PILE_SECONDS];self.tempo_unjudged=[]      # h28: what went before is no part of this question: the pile of talk nobody judged made every question after it unanswerable (the scene of tools/replay/quantity.py: 5 garbage turns, the base's question, silence)
        text=next((' '.join(near[at:]) for at in range(len(near)) if self._reference(' '.join(near[at:]))),' '.join(near))
        user=self.ledger.latest_user();open_turn=bool(user and user['valid'] and not user['final'] and user['id'] not in self.seen)
        # A8-3: the ear stands in for no word of the cloud: an open turn whose words go another way (a number, «не», a word: c9-numveto) waits for its final, and a figure is worked out of two witnesses or none (Q1, ``_ear_sum``)
        cloud=user['text'] if open_turn and self._said_words(user['text']) else '';figure=quick_answer(text)
        contradicted=(cloud and not same_start(text,cloud,strip=lambda said:probe('strip_fillers',said,settings=self.settings).value,open_end=True)) or (figure and quick_answer(cloud)!=figure)
        if contradicted and cloud and not figure:contradicted=self._late_correction(text,cloud)      # U15-S6: only a DIFFERS contradicts
        if contradicted and self._cloud_stands_in(text,cloud,figure):      # g1-ladder L0: the ear lost or changed a word the cloud's still words have: those words are the question
            logger.info('echo-sync decision kind=silent reason=no_final_the_cloud_words_stand_in revision=%s',(self.state() or {}).get('revision'))
            text,contradicted=cloud,False
        if contradicted:
            revision=(self.state() or {}).get('revision')
            logger.info('echo-sync decision kind=silent reason=no_final_the_ear_is_contradicted figure=%s revision=%s',bool(figure),revision)
            if revision is not None and getattr(self,'ear_question_on',None)==revision:self.ear_asked_on=revision      # W14: a new question nobody answers: the plan is not repeated
            if self._may_ask(text):self.tempo_contradicted=ended      # c24-a1 (fuzz seed 48): a question, a correction nobody has judged yet: the final does (``_tempo_unheard``); a remark holds nothing (ladder L4 seed 8: the weather of somebody else, the cloud 11 s late)
            return []
        if self._at_the_answer(text,self.state()):
            logger.info('echo-sync decision kind=silent reason=no_final_a_try_at_the_answer revision=%s',(self.state() or {}).get('revision'))
            if self._try_counted(text,self.state()):self.go_on=self._position(self.state())      # U94.11: the owner's repeat of the portion is a try: counted as ``_rule_tempo_help`` counts it, no new repeat is armed over it (call 13.11: two loops, 87 s)
            else:self._tempo_arm(now+self._silence().wait)
            return []
        return self._ear_stands_in(text,ended)
    def _try_counted(self,text,state):
        """U94.11: do these words say back the portion that waits (``most_said``: all its numbers and half of what it says: the one threshold of the owner's repeat)? Then they are a try at it, whatever the final is to come."""
        portion=probe('waiting_portion',state=state).value
        return bool(portion) and most_said(probe('strip_fillers',text,settings=self.settings).value,portion)
    def _at_the_answer(self,text,state):
        """h28 (the call of 16:15: «нет потому что государством» while «Шесть видов: между государством…» was on: a job, and its reply took the answer away from under the owner): words of the answer on, with no word
        that asks («потому что» asks nothing), are the owner at the answer, whatever the ear's classifier made of them. The base's own question is another matter (``_bank_asks``)."""
        if probe('waiting_portion',state=state).value is None or self._bank_asks(text,state):return False
        said=re.sub(r'(?<!\w)(?:потому|оттого|затем|так|то|в том|тем)\s*,?\s+что(?!\w)|(?<!\w)чтобы(?!\w)',' ',str(text).casefold().replace('ё','е'))
        if frozenset(norm_words(said))&QUESTION_WORDS:return False
        plan=_stems(' '.join(str(chunk) for chunk in (state or {}).get('chunks') or ()));words=norm_words(said)
        return bool(words) and sum(bool(_stems(word)&plan) for word in words)*2>=len(words)      # h31: mostly words of the answer, one word in common is no try
    def _ear_stands_in(self,text,ended):
        """The ear's text is the turn: the open turn of the cloud, if it has one (its final, should it come, finds it judged), else a turn of the ear's."""
        now=self.clock();self.tempo_unjudged=[];hit=self._reference(text);first=self.ear_first;before=self.state() or {}
        user=self.ledger.latest_user();open_turn=bool(user and user['valid'] and not user['final'] and user['id'] not in self.seen)
        self.ear_finals+=1;tid=user['id'] if open_turn else f'ear-final-{self.ear_finals}'
        ear=self._ear_of_take(tid,first['run'],first,text) if open_turn and first is not None else None      # DEF1: a stand-in of the ear's question is a take of it: its final is judged by the one judge of such a turn (``_ear_first_final``)
        logger.info('echo-sync decision kind=silent reason=no_final_the_ear_stands_in revision=%s',(self.state() or {}).get('revision'))
        turn=self.ledger.apply({'type':'turn.done','turn':{'id':tid,'role':'user','transcript':text}})
        self.seen.add(tid);self.user_done_at[tid]=now;self.user_boundaries[tid]='ear_final';self.speech_ended[tid]=ended
        if not open_turn:self.ear_stood=(text,now)
        else:self.ear_stood_open={'tid':tid,'text':text,'at':now,'hit':hit}      # c23 P09: its final may still come, and say more
        if self.ear_first is not None:self._ear_first_drop('no_final')
        actions=self._take_candidate(turn)
        if ear is not None and self.question_id==tid:self._ear_took(tid,first['run'],before,self._ear_family(first['decision']) or QUESTION,ear)
        if self.candidate and 'job' in self.candidate:self.candidate['retried']=True
        return actions+self._fast_ask()
    def _ear_stood_short(self,turn):
        """c23 P09: the final of a turn the ear stood in for, whose job declined the ear's text, says a word or a number the ear's text did not (the ear cut «…статья семнадцать налогового», the final has
        «…Налогового кодекса?»): what was declined is not what was said, the final is judged again. The same words: it has been judged."""
        stood=self.ear_stood_open
        if not stood or stood['tid']!=turn['id']:return False
        self.ear_stood_open=None
        if ((self.early_taken.get(turn['id']) or (None,)*6)[5] or {}).get('first'):return False      # DEF1: the ear's question stood in: its final is the judge's of a take (``_rule_early_tail``), what it says of other words is judged there
        strip=lambda said:probe('strip_fillers',said,settings=self.settings).value
        numbers=lambda said:{atom for atom in self._protected_atoms(said)[0] if atom.startswith('#')}
        more=_stems(strip(turn['text']))-_stems(strip(stood['text']));number=numbers(turn['text'])-numbers(stood['text'])
        # Fable 10.11 (20:54, 106 s: the stand-in was declined at 86 s, the final came at 108 s with a whole new question and nobody judged it: 20 s of silence):
        # nothing was opened on the stand-in and the final brings a number or STOOD_MORE_STEMS new words: a new utterance, judged whenever it comes
        if (stood.get('declined') or (not stood.get('hit') and self.question_id!=turn['id'])) and (number or len(more)>=STOOD_MORE_STEMS):return True
        if not (stood.get('declined') or stood.get('hit')) or self.clock()-stood['at']>TEMPO_HOLD_SECONDS:return False
        if stood.get('declined'):return bool(more or number)
        return bool(number or (more and self._reference(turn['text']) not in (None,stood['hit'])) or ' не ' in f" {' '.join(norm_words(turn['text']))} "[len(' '.join(norm_words(stood['text']))):] or not (said_within(turn['text'],stood['text'],strip=strip) or same_start(stood['text'],turn['text'],strip=strip,open_end=False)))      # h31: the base's answer said on the ear alone: the final may yet name another thing; DEF1: or say nothing of what the ear heard (a command, a doubt, another question): it is a final of its own
    def _ear_said_it(self,turn):
        """H6 item 6: a final of the cloud that says what the ear's text said in its place: it has been judged."""
        stood=self.ear_stood
        if not stood:return False
        self.ear_stood=None
        return self.clock()-stood[1]<=self.ack_join_seconds and self._final_says(turn['text'],stood[0])
    def tempo_old_news(self):
        """Is a start of speech the cloud announces now that of an utterance the ear has already heard end? Then nobody is speaking: no cue is cut for it (see TEMPO_ANNOUNCE_SECONDS). Speech the ear
        has not heard at all stays the cloud's to tell."""
        if not (self.tempo_live and not self.tempo_speaking and self.tempo_ended is not None and self.clock()-self.tempo_ended<=TEMPO_ANNOUNCE_SECONDS):return False
        return not (self.cue_outstanding and self.cue_window and self.tempo_began is not None and self.tempo_began>=self.cue_window[0])       # H6 item 5 (R1): begun over the cue that plays, it is news for that cue: «стоп» cuts it now, not at its final
    def _repeat_gate(self,state,now):
        """x-tick: the order in front of an automatic repeat, the first that holds speaks: (1) a stale slot (U20: it is cleared and the repeat waits), (2) the state of the input (U17 ``repeat_action``:
        hold and defer are not counted, unconfirmed speech sets ``unplaced``), (3) the language hold (U19 ``tempo_hold``), then (4) the cap, which ``tick`` applies below. Returns the reason, or None."""
        self._input_log(now)
        stale=stale_slots(self)
        if stale:
            logger.info('echo-sync timer_stale slots=%s epoch=%s reason=repeat_gate',','.join(stale),self.epoch)
            for name in stale:setattr(self,name,STAMPED_SLOTS[name])
        meter=getattr(self,'input_meter',None);act=meter.repeat_action(now) if meter is not None and not stale else None
        hold=self.tempo_hold
        why=gate(stale=bool(stale),input_act=act.act if act else None,held=bool(self.tempo_live and hold is not None and hold[0]==self._position(state) and now<hold[1]+self._hold_s(hold)))
        unconfirmed=bool(act and act.act=='unconfirmed')
        if why is not None:
            if getattr(self,'_gate_seen',None)!=why:
                self._gate_seen=why
                logger.info('echo-sync decision kind=silent reason=repeat_gate gate=%s revision=%s index=%s',why,(state or {}).get('revision'),(state or {}).get('chunk_index'))
            return why
        self._gate_seen=None
        if unconfirmed:self.unplaced=True      # the repeat that follows is counted where it is said (tick), so a cap that blocks it costs nothing
        return None
    def _duplex(self):
        """u17: what the input meter (always counting) has seen of the phone: 'half' | 'full' | 'unknown'."""
        meter=self.input_probe
        try:return meter.duplex(self.clock()) if meter is not None else 'unknown'
        except Exception:return 'unknown'    # noqa: BLE001
    def _tempo_said_before(self):
        """Rule 6: no speech has begun since the timer last spoke: a final that comes now is what was said before that cue, the cloud being late. It tells nothing of how the listener took it."""
        return self.tempo_live and self.tempo_spoke is not None and (self.tempo_began is None or self.tempo_began<=self.tempo_spoke)
    def _tempo_back_at_it(self):
        """Has the listener gone back to the portion since the final the job is judging? Rule 3 is for them, a remark waits for no one."""
        start=self.tempo_start;taken=self.candidate.get('taken');asked=getattr(self,'tempo_asked',None)
        if taken is not None and asked is not None and asked>taken and self._position(self.state()) is not None:return True      # g25: «как там», «забыл», «секунду» since: the owner asks for the word, the job judges older speech
        return bool(start and taken is not None and start[2]>taken and self._tempo_missing(self.state()))
    def tempo_heard(self,record):
        """What the ear recognized of one utterance (a ``ShadowEar.poll`` record), on the transport's tick. Only the timer's business: it says when the tick speaks."""
        if isinstance(record,dict):
            if str(record.get('text') or '').strip():self.ear_words_at=self.clock()      # U108 (2): words of the owner
            record,gated=self._ear_lang_gate(record)      # U19-S3: first
            self._input_feed('ear',str(record.get('text') or ''),str(record.get('reason') or ''),record.get('speech_ms') or 0,**({'hold_s':TEMPO_HOLD_SECONDS} if gated else {}))      # U17-S4: after the language gate, before the timer's own business; a gated record is pending for the hold
            if gated:return self._tempo_safely(self._tempo_foreign,record) if self.tempo_live else None
        if self.tempo_live:self._tempo_safely(self._tempo_heard,record)
    def _tempo_foreign(self,record):
        """U19-S3: speech the ear cannot read (another language, noise): no text to judge and no timer on it; the repeat holds (``tempo_hold``) for TEMPO_HOLD_SECONDS or until the cloud's final, as for any other speech."""
        uid=record.get('uid');offset=record.get('offset')
        span=self.tempo_spans.pop(uid,None)
        if self.tempo_awaits==uid:self.tempo_awaits=None
        if type(offset) not in (int,float):offset=self.tempo_ended if self.tempo_ended is not None else self.clock()
        state=self.state();where=self._position(state)
        if where is None or state.get('paused') or span is None or span[1]!=where:return
        self._arm(None);self.tempo_hold=(where,offset)
    def _tempo_heard(self,record):
        uid=record.get('uid');text=record.get('text');offset=record.get('offset')
        span=self.tempo_spans.pop(uid,None)
        if self.tempo_awaits==uid:self.tempo_awaits=None
        if type(offset) not in (int,float):offset=self.tempo_ended if self.tempo_ended is not None else self.clock()
        last=max(self.user_done_at,key=self.user_done_at.get,default=None)
        if isinstance(text,str) and self._has_content(text):self.tempo_content=offset
        if isinstance(text,str) and (last is None or (offset>self.user_done_at[last] and (not self._final_says((self.ledger.snapshot(last) or {}).get('text') or '',text) or self._said_past(text,span,offset,last))) or self._said_after(text,span,last)) and self._has_content(text) and (self.ear_take or {}).get('offset')!=offset and not self._instant_holds(uid,text):self.tempo_unjudged=(self.tempo_unjudged+[(offset,text)])[-EAR_SAID_PIECES:]      # what the ear has just acted on is judged, and what the last final says, however late the ear's text came
        state=self.state();where=self._position(state)
        if where is None or state.get('paused') or span is None or span[1]!=where:return     # not said to what waits now
        wait=offset+self._silence().wait
        if record.get('kind')=='error' or not isinstance(text,str):return self._tempo_arm(wait)
        portion=probe('waiting_portion',state=state).value;over=self._tempo_over(span[0])
        kind,found=self._tempo_verdict(text,self._tempo_join(where,text,span[0],offset),state,portion)
        if kind=='try' and self._own_number(text,state) and self._bank_asks(text,state):kind='other'      # h29: «статья 422» over «Статья 79…»: another row of the base; a slip with no row stays a wrong repeat (g28)
        elif kind=='try' and record.get('kind')=='question':kind='other'      # g17: «Что такое налоговые органы?» over «банки и налоговые органы.» says words of the portion and asks: no try, the next portion is not cued on it
        elif kind=='try' and probe('question_by_form',text).value and len(self._marks(text)-self._marks(portion or ''))>=2 and norm_words(probe('strip_fillers',text,settings=self.settings).value)[:1] not in (['да'],['нет'],['не']):kind='other'      # c24-a1 (not a reply to the portion that asks at its end: «Да там просто сто двадцать тысяч, … зачем эти сложности», w3 n2_d03 step 10) (F1, fuzz seed 107): so is a question the ear wrote with no «?» and words of its own beyond the portion («… сколько денег осталось» over «Осталось 10 рублей.»)
        due=self._pace_due(where,portion,text,span[0],offset) if self.pace is not None else None
        logger.info('echo-sync ear tempo=%s uid=%s over=%s revision=%s index=%s',kind,uid,over,state.get('revision'),state.get('chunk_index'))
        if kind=='landmark':
            self._engaged(state);self.auto_repeats=0;self.tempo_hold=None;self._arm(None);self.tempo_asked=self.clock()
            if found is None:return self._tempo_arm(offset+self._silence().wait)       # no such word here (the next portion's, another number): nothing moves, the wait as ever
            if found[0]=='next':self.portion_tries=(where,[text]);self.go_on=where;return      # the last word of the portion written: the rule's one NEXT
            self.tempo_start=(where,found[1],self.clock());self.rule_helped=None
            return self._tempo_arm(offset+LANDMARK_SECONDS)
        if kind=='dictation':
            self.dictating.heard(found);self._engaged(state);self.auto_repeats=0;self.tempo_hold=None;self._arm(None)
            return self._tempo_arm(offset+self._silence().wait)
        if kind=='done':
            # c22-repeat: the owner's rule: the last word of the portion or most of it said: the next portion at the next tick (``go_on``), the cloud's final of it taken (``_try_final``)
            if not over:return self._tempo_arm(max(self.repeat_at or wait,wait))     # said with the cue: it may be the cue heard back
            if (self._record_tools() or self.dictation) and self.cue_window and span[0]>self.cue_window[1]:self.dictating.pace.observe(portion,span[0]-self.cue_window[1]);self.dictating.keep()
            self._engaged(state);self.auto_repeats=0;self.tempo_hold=None;self._arm(None)
            self.portion_tries=(where,[text]);self.go_on=where
            return
        if kind=='pause':
            # g25: the owner asked for time: no cue into it (nor a hold for a job: there is none), TEMPO_PAUSE_SECONDS from its end, then the portion or what is missing of its start.
            self._engaged(state);self.auto_repeats=0;self.tempo_hold=None;self._arm(None);self.tempo_asked=self.clock()
            if found:self.tempo_start=(where,found[0],self.clock())
            return self._tempo_arm(offset+(min(RECORD_PAUSE_SECONDS,self.dictating.pace.wait(portion or '',TEMPO_PAUSE_SECONDS)) if self._recording() else TEMPO_PAUSE_SECONDS))      # u18-s4: in the record state the pause is the pen's wait
        if kind=='filler':
            # Rule 4: the wait is not reset, and it is at most TEMPO_FILLER_SECONDS more. Said over a cue, it may be that cue heard back: only a timer that nothing runs is run. The word will not come: they
            # say they are stuck, and that is no silence to be bounded: the count starts again, as for a try.
            said=norm_words(text)
            if over and (TEMPO_BLANK.search(' '.join(said)) or (frozenset(said)&TEMPO_SEEKING and frozenset(said)&QUESTION_WORDS)):self._engaged(state);self.auto_repeats=0;self.tempo_asked=self.clock()     # g25: «как там», «как его» ask for the word as «забыл» does: help however many repeats were said
            if not over:
                if self.repeat_at is None:self._tempo_arm(wait)
                elif due is not None and self._tempo_missing(state):self._tempo_arm(min(self.repeat_at,due))     # W5: a filler after a start that stopped: help at once
            else:self._tempo_arm(min(self.repeat_at,offset+TEMPO_FILLER_SECONDS) if self.repeat_at is not None else offset+TEMPO_FILLER_SECONDS)
            return
        if kind in ('start','try'):
            if not over and kind=='start' and found and self.cue_window and offset>self.cue_window[1]:self.tempo_start=(where,found[0],self.clock())      # h27: said along with the cue and ending after it: a cue heard back ends with the cue, this is their voice, and the place is theirs (the call of 16:08)
            if not over:return self._tempo_arm(max(self.repeat_at or wait,wait))    # the listener spoke with the cue: the wait counts from their end, what they said may be the cue heard back
            self._engaged(state);self.auto_repeats=0                                # only silence is bounded: what the cloud's final would do seconds from now
        if kind=='start':
            twice=found[1] or bool(self.tempo_start and self.tempo_start[0]==where and self.tempo_start[1]==found[0])
            self.tempo_start=(where,found[0],self.clock());self.tempo_hold=None
            if self._record_tools() or self.dictation:due=max(due or 0,offset+DICTATION_START_SECONDS)      # c22-repeat: a stop while dictating may be the pen: helped later, from the same word
            self._tempo_arm(due if due is not None else offset+(TEMPO_TWICE_SECONDS if twice else TEMPO_START_SECONDS))     # W5: the listener's own wait (``_pace_due``), rule 3 without it
        else:
            self.tempo_others=(where,(self.tempo_others[1] if self.tempo_others and self.tempo_others[0]==where else 0)+1) if kind=='other' else None      # u18: other speech in a row
            talks=kind=='other' and self.tempo_others[1]>=MONOLOGUE_OTHERS
            self._arm(None);self.tempo_hold=(where,offset,'question') if kind=='other' and record.get('kind')=='question' else (where,offset,'monologue') if talks else (where,offset)     # w10 R10.1: a question the ear heard over the plan is no try of it
        if kind=='try' and over and record.get('kind')=='question' and not (most_said(probe('strip_fillers',text,settings=self.settings).value,portion) or ends_like(probe('strip_fillers',text,settings=self.settings).value,portion)):return      # G23 (Р087): a question the ear heard is no try of the portion, whatever words it shares with it
        if kind=='try' and over and not self._disputes(text,state) and not self._of_the_try(text,state):      # a start that stopped has its own help, from the word it stopped at
            self.portion_tries=(where,self.portion_tries[1]+[text] if self.portion_tries and self.portion_tries[0]==where else [text])
            if self._try_went(where,portion):self.tempo_hold=None;self.go_on=where;self.go_ahead=self._next_said_whole(text,state,where)
    def _went_on(self,where,portion):
        tried=self.portion_tries[1] if self.portion_tries and self.portion_tries[0]==where else []
        self._record_progress(where)
        self.went_on=[where,portion,list(tried),self.clock(),len(tried)]      # the last: the utterances of the try whose finals are still to come
    def _try_final(self,turn):
        """g17 (the bank on the controller): the ear's try went on, and the cloud's final of the same words comes a second later, while the portion after it waits. Judged against that one it was a wrong
        repeat (the portion said again: two cues of it), or it ended like it too («календарный год» twice) and went on once more: two portions for one try. It is the try the ear heard: taken, nothing more.
        One final for each utterance of the try: a later one is a try of its own at the waiting portion (walk 21011: «внеоборотные активы» after «Внеоборотные и активы.»)."""
        went=self.went_on
        if not turn.get('final') or not went or went[4]<=0 or not self._of_the_try(turn['text'],self.state(),final=True):return False
        if self._own_number(turn['text'],self.state()) and self._bank_asks(turn['text'],self.state()):return False      # h29
        went[4]-=1;self.seen.add(turn['id']);self.user_boundaries[turn['id']]='a_try_heard'
        logger.info('echo-sync decision kind=silent reason=the_final_of_a_try revision=%s index=%s',self.state()['revision'],self.state()['chunk_index'])
        return True
    def _of_the_try(self,text,state,*,final=False):
        """Does ``text`` say the portion a try has just gone on from (``went_on``), rather than the one that waits now? The rest of a portion said in two breaths is no first try at the next one either
        (walk 2648: «или бухгалтер и кассир.» was a try at «При отсутствии главного бухгалтера», the owner's next words its second try, and those went on whatever they said): its final is the try's too.
        ``final``: the cloud's final of an utterance of the try, which says what the ear heard, or the portion before more than the one after."""
        went=self.went_on
        if not went or self.clock()-went[3]>TRY_FINAL_SECONDS:return False
        where=self._position(state);said=probe('strip_fillers',text,settings=self.settings).value;waits=probe('waiting_portion',state=state).value
        if where is None and state and type(state.get('chunk_index')) is int and state.get('chunk_index')==len(state.get('chunks') or ()):where=(state.get('revision'),state['chunk_index'])      # c24 (half_hour seed 8 @1516): the try went on from the LAST portion: its late final is that try, not a new question
        if where is None or where!=(went[0][0],went[0][1]+1) or not said:return False
        tried=probe('strip_fillers',' '.join(went[2]),settings=self.settings).value
        if final and tried and said_within(tried,said):return True      # the try's own words are it even when the next portion says the same («Расчёты с поставщиками.» twice in an answer)
        if waits is None:return bool(most_said(said,went[1]) or ends_like(said,went[1]))
        if ends_like(said,waits) and (not final or not ends_like(said,went[1])):return False      # «внеоборотные активы» ends «Первый раздел внеоборотные активы,», not «Внеоборотные и оборотные
        # активы.»; a new breath that ends like the waiting portion is a try at it, even when the one before ended alike (walk 30071: «Прочие доходы и расходы.» and «Прочие доходы и расходы,»)
        old,new=said_share(said,went[1]),said_share(said,waits)      # what says the portion before more than the one after («законодательство Российской Федерации о налогах» before «законодательство субъектов …»)
        if (most_said(said,went[1]) or ends_like(said,went[1])) and not (new or 0)>=(old or 0)>0 and not (new or 0)>=0.6>(old or 0):
            if not final:went[4]+=1      # its final is to come too
            return True
        return False
    def _next_said_whole(self,text,state,where):
        """c23: ``(where, the next portion)`` when ``text`` ends in the whole next portion, word for word (strict: a «не», a word or a number of its own is no such portion; a start of it is G26's,
        test_repeat_cases two_words_ahead), after words that go on from the waiting one; else None. As the early ACK's tail (g7, ``_early_tail``)."""
        chunks=list(state.get('chunks') or []);index=state.get('chunk_index');fillers=resolve(self.settings)['fillers']
        if type(index) is not int or index+1>=len(chunks) or (state.get('streaming') and index+2>=len(chunks)):return None
        words=str(text).split();portion=chunks[index]
        for k in range(1,len(words)):
            head=probe('strip_fillers',' '.join(words[:k]),settings=self.settings).value
            read=whole_portions(words[k:],chunks[index+1:],fillers) if head and (most_said(head,portion) or ends_like(head,portion)) else None      # U60: one portion or more, read through to the end
            if read:return where,read
        return None
    def _try_went(self,where,portion):
        """A try counts: most of the portion said, or a second try of any kind (the owner's words of 06.11: «я уже повторил за тобой, опять не говоришь дальше»). What it got wrong
        was said again once, the answer goes on."""
        tried=self.portion_tries[1] if self.portion_tries and self.portion_tries[0]==where else []
        said=probe('strip_fillers',' '.join(tried),settings=self.settings).value
        return len(tried)>=2 or (bool(tried) and (most_said(said,portion) or ends_like(said,portion)))
    def _pace_due(self,where,portion,text,began,offset):
        """When a start that stopped is helped: the pace of this listener, told the utterance (its words spread over it: the ear gives no time of a word) up to the speech's end, EAR_QUIET before the
        offset. None when it has no say (other speech, the portion said, no portion): rule 3 stands. A fault switches it off for the call, like the tempo's."""
        try:
            key=(where,portion)
            if self.pace_key!=key:
                self.pace_key=key;self.pace.cue(portion,self.cue_window[1] if self.cue_window else began)
            self.pace.utterance(text,began,max(began,offset-PACE_QUIET_SECONDS))
            now=self.clock();d=self.pace.decide(now)
            logger.info('echo-sync ear pace=%s reason=%s wait_ms=%s',d.kind,d.reason,d.wait_ms)
            due=now+d.wait_ms/1000 if d.kind=='wait' else now if d.kind=='prompt' else None
            if due is None:return None
            due=max(due,offset-PACE_QUIET_SECONDS+PACE_HELP_SECONDS[1 if d.reason=='number' else 0])      # w10 item 16, f3-reaction: 0.7 s at least after the last word (a breath), a filler and a repeat too
            # («at once» was 0.35 s, over the listener); a stop inside a number is a reading pause (n1_01 step 17: «сто сорок четыре | ноль ноль ноль»): the top of the window
            return min(due,offset-PACE_QUIET_SECONDS+PACE_HELP_SECONDS[1])      # and never later than the owner's 1.2 s
        except Exception as error:
            logger.warning('echo-sync ear pace=off reason=%s',reason_of(error));self.pace=None
            return None
    def _ear_jobs_declined(self):
        """c24-a1 (ladder L4 seed 29: «Курс доллара …», «Маша, подай ручку» of others held the answer of the owner's question 7 s, until the cloud's late finals): speech whose job, prepared on the
    ear's text (H7, ``_fast_wide``), is over and said no answer («—») has been judged as a final of it would be (``fast_text_declined``): it holds nothing any more. The pieces from the first of
    a breath so declined on."""
        if not self.tempo_unjudged or not self.fast_on or not self.prepared_job or self._fast_running():return
        breath=[text for _,text in self.wide_breath or ()]
        if breath:      # the job of the breath these pieces are in (``_fast_wide_ear``: its pieces joined)
            said=self.prepared_job(probe('strip_fillers',('. ' if self.ear_job else ' ').join(breath),settings=self.settings).value.strip())
            if said and said[1] and not brain_answer(said[0]) and any(text in breath for _,text in self.tempo_unjudged):
                logger.info('echo-sync decision kind=silent reason=ear_job_declined pieces=%s revision=%s',len(breath),(self.state() or {}).get('revision'))
                self.tempo_unjudged=[(end,text) for end,text in self.tempo_unjudged if text not in breath];return
        for at in range(len(self.tempo_unjudged)):
            said=self.prepared_job(probe('strip_fillers',' '.join(text for _,text in self.tempo_unjudged[at:]),settings=self.settings).value.strip())
            if said and said[1] and not brain_answer(said[0]):
                logger.info('echo-sync decision kind=silent reason=ear_job_declined pieces=%s revision=%s',len(self.tempo_unjudged)-at,(self.state() or {}).get('revision'))
                self.tempo_unjudged=self.tempo_unjudged[:at];return
    def _said_past(self,text,span,offset,last):
        """c23 (c22-break P01, fuzz seeds 7 and 59): what the ear heard is speech the final ``last`` cannot say, whatever words they share: it began after that final came («не охлаждать, а нагревать» after
        «не нагревать, а охлаждать»), or it went on EAR_BIND_SECONDS past it with words the final has not («Ну что, давайте … 40 рублей и … 50» over the final of «50 … 40»)."""
        came=self.user_done_at[last]
        if self.cue_heard and self.cue_window and self.cue_window[0]>=came:return False      # a cue was heard since that final: what is said now is said to it (a try, h3 ``…_word_lost_goes_on``), as before
        if span is not None and span[0]>came:return True
        final=(self.ledger.snapshot(last) or {}).get('text') or ''
        return offset-came>EAR_BIND_SECONDS and len({stem for stem in _stems(text)-_stems(final) if not stem.isdigit()})>=2
    def _said_after(self,text,span,last):
        """c24-a1 («старый ответ», fuzz seeds 0, 16, 18): speech begun after the speech the final ``last`` says had ended - that final came during it, or after it with the ear's text late - is not said by it, however many
        words they share («не нагревать, а охлаждать» | «не охлаждать, а нагревать»; «70 … 90» | «90 … 70»): one final says one utterance. Unless its own words (none of the speech the final says) are the final's: the ear's text of
        the final's own speech, come late. Not after a cue heard since that final: what is said then is said to it (``_said_past``)."""
        said=(getattr(self,'tempo_said_end',None) or {}).get(last)
        if span is None or not said or span[0]<=said[0]:return False
        if self.cue_heard and self.cue_window and self.cue_window[0]>=self.user_done_at[last]:return False
        if self._ear_family(self._classify(text,self.state())) is not None or doubts(text):return False      # a command («повтори», «дальше», «стоп»), a doubt: said of the answer, no new question (fuzz seed 532: «Повтори.» held the first cue 2 s)
        own=self._marks(text)-said[1];final=(self.ledger.snapshot(last) or {}).get('text') or ''
        return not (own and own&self._marks(final)) and not self._words_in(final,text)
    def _may_ask(self,text):
        """c24-a1: may the ear's ``text`` be a new question or a correction of one: by its form, «не X, а Y», or a dispute of the portion that waits (``_disputes``)?"""
        state=self.state() or {};decision=self._classify(text,self._heard_with(state))
        return decision.kind in (QUESTION,CORRECTION) or probe('question_by_form',text).value or self._disputes(text,state)
    def _older_final(self,turn):
        """c24-a1 (fuzz seed 411; g23 Р057 «late final of the older question retires the newer plan»): is this final of an utterance that ended before the speech of the question the ear
        opened began? The ear opened that question on its own words, its answer is in play; the listener has gone past the older one, which opens nothing now and retires nothing.
        Not when the final says the question's own words too (the cloud joined the two), nor when nothing tells where its speech ended."""
        take=self.ear_take or {};first=(take.get('ear') or {}).get('first')
        if not first or take.get('tid')!=self.question_id or turn['id']==self.question_id or not first.get('run'):return False
        began=first['run'][0].get('onset');said=(getattr(self,'tempo_said_end',None) or {}).get(turn['id'])
        if began is None or not said or said[0]>=began:return False
        return bool(self._marks(first['text'])-self._marks(turn['text']))
    def _final_pieces(self,final,texts):
        """c24-a1: which of ``texts`` (the ear's pieces, in order) the final says, and the stems of those up to the last: a later piece by its own words, not by those it shares with one the final says
        («В каком году было Куликовская битва?» says nothing of «в каком году было основание Петербурга» after it: fuzz seed 8). A piece with no word of its own is said as the one before."""
        said,known,upto,marks=[],set(),set(),self._marks(final)
        for at,text in enumerate(texts):
            own=self._marks(text)-known;known|=self._marks(text)
            if (self._final_says(final,text) or norm_words(final)==norm_words(text)) and (not said or not own or own&marks or self._words_in(final,text)):said.append(at);upto=set(known)      # the same words: a command has no stem of content («Повтори.»)
        return said,upto
    def _marks(self,text):
        """c24-a1: the words of ``text`` to tell one utterance from another: the stems of its words that are no number, and its numbers by value («семьдесят» of the ear and «70» of the cloud are one)."""
        numbers={atom for atom in self._protected_atoms(text)[0] if atom.startswith('#')}
        return {stem for word in WORDS.findall(text or '') if not any(atom.startswith('#') for atom in self._protected_atoms(word)[0]) for stem in _stems(word)}|numbers
    def _final_says(self,final,text):
        """Does the final say something of what the ear heard: a word, or a number by value (the words of a number share no stem with its digits)?"""
        numbers=lambda said:{atom for atom in self._protected_atoms(said)[0] if atom.startswith('#')}
        return bool(_stems(text)&_stems(final)) or bool(numbers(text)&numbers(final))
    def _ear_went_on(self,since,qid=None):
        """H5 item 6: did the speech the ear hears, or heard last, a run with no silence of EAR_RELEASE_SILENCE_SECONDS in it, begin before the final that came at ``since`` and go on past it? Then what the cloud says next is
        the rest of that breath: nothing the listener heard came between. c24-a1 (ladder L4 seed 21): not a run begun after the speech the final of ``qid`` says had ended: that is other speech."""
        said=(getattr(self,'tempo_said_end',None) or {}).get(qid) if qid is not None else None
        if said and self.tempo_run is not None and self.tempo_run>said[0]:return False
        return bool(self.tempo_live and self.tempo_run is not None and since is not None and self.tempo_run<since and (self.tempo_speaking or (self.tempo_ended is not None and self.tempo_ended>since)))
    def _tempo_over(self,began):
        """Is speech begun at ``began`` the listener's, for certain? The last cue was over by then, or this speech cut it: said over a cue that ran on, it may be that cue heard back."""
        return self._cue_over_before(began) or (self.tempo_cut is not None and self.tempo_cut>=began)
    def _tempo_join(self,where,text,began,offset):
        """``text`` with the pieces of the same utterance before it (the detector ends one at 300 ms of quiet): each begun at most EAR_JOIN_GAP_SECONDS after the end of the one before, EAR_JOIN_PIECES in all."""
        pieces=[piece for piece in self.tempo_pieces if piece[0]==where];joined=[text];at=began
        for _,said,onset,ended in reversed(pieces):
            if len(joined)>=EAR_JOIN_PIECES or not within(at,ended,EAR_JOIN_GAP_SECONDS):break
            joined.insert(0,said);at=onset
        self.tempo_pieces=(pieces+[(where,text,began,offset)])[-EAR_JOIN_PIECES:]
        return ' '.join(said for said in joined if said.strip())
    def _tempo_verdict(self,text,joined,state,portion):
        """What the ear heard, for the timer: ``(kind, what)``. 'own': a repeat, a command: their own path, the cloud's final is on its way. 'filler': a hesitation (rule 4). 'start': a start of the portion
        that stopped (rule 3; ``what``: the rest, and whether words were said twice). 'try': words of the portion, and no start. 'other': speech of its own (rule 5)."""
        said=self._classify(joined,state);alone=self._classify(text,state) if joined!=text else said
        if self._read_again(text,state) or self._read_again(joined,state):return 'own',None      # c24-c: the question read again: the final's (a REPEAT), no try
        if portion and landmark_command(text):      # c24-c: a word of the portion named: the help moves inside it, the cursor never jumps
            return 'landmark',landmark(text,portion,self._helped_at(state,portion))
        if self._ear_family(said) or self._ear_family(alone) or RESUME in (said.kind,alone.kind):return 'own',None
        if said.reason.startswith('dictation_') or alone.reason.startswith('dictation_'):return 'dictation',(alone if alone.reason.startswith('dictation_') else said).reason
        rest=written_to(probe('strip_fillers',text,settings=self.settings).value or '',portion) if portion and self._record_tools() and not frozenset(norm_words(text))&QUESTION_WORDS else None
        if portion and not rest and any(rule_verdict(probe('strip_fillers',piece,settings=self.settings).value or '',portion)=='next' for piece in dict.fromkeys((text,joined))):return 'done',None      # c22-repeat: the last word or most of it
        if alone.reason=='pause_request' or said.reason=='pause_request':      # g25: «секунду», «общие, сейчас»: the owner asks for time
            head=(pause_split(norm_words(joined),frozenset(resolve(self.settings)['fillers'])|HESITATION_WORDS) or ([],))[0]
            return 'pause',(self._started(' '.join(head),portion) if head else None)
        heard=[word for word in norm_words(text) if word not in frozenset(resolve(self.settings)['fillers'])|HESITATION_WORDS];own=norm_words(portion)
        if heard and len(heard)<len(own) and own[:len(heard)]==heard:      # g25: «Сейчас» of «Сейчас основная ставка …»: the portion's own first words, a function word too, are a start, no hesitation
            found=self._started(joined,portion) or self._started(text,portion)
            if found:return 'start',found
        if self._hesitates(text,portion,alone) and not self._has_content(text):return 'filler',None
        missing=self._tempo_missing(state)
        for whole in (portion,missing[0]) if missing else (portion,):     # what was just cued is what they may stammer on next
            found=self._started(joined,whole) or (self._started(text,whole) if joined!=text else None) or self._misheard_start(text,whole,alone)
            if found:return 'start',found
        if rest:return 'start',(rest,False)
        if self._of_the_portion(text,portion) and (_like_a_try(text,portion) or self._next_said_whole(text,state,self._position(state))):return 'try',None      # U60: the portion and whole next ones after it: read through      # c24 F1: a word or a number in common is no try when the speech is mostly words of its own
        return 'other',None
    def _helped_at(self,state,portion):
        """c24-c: the index of the word the last help of the waiting portion began from (where the writer is), or None."""
        start=self.tempo_start
        if not start or start[0]!=self._position(state) or not str(portion).endswith(str(start[1])) or start[1]==portion:return None
        from .ru_alignment import _canonical
        return len(list(_canonical(str(portion),(),True)))-len(list(_canonical(str(start[1]),(),True)))
    def _misheard_start(self,text,portion,decision):
        """H7 item 0 (480.4 of the owner's call of 5 Nov, «запнулся на втором слове»: «инфляция это устойчивый» came as «цвета устойчивый»; the whole portion 15.4 s later, from the start): the ear wrote the head of a start as something else: at most
        TEMPO_FRAGMENT_WORDS words that are not the portion's, no more of them than a start up to there would have, then a word of it, and there it stops. What comes after that word is missing. A question or a doubt is no start."""
        if not self.fast_on or decision.kind in (QUESTION,CORRECTION) or doubts(text) or frozenset(norm_words(text))&QUESTION_WORDS:return None
        heard=[word for word in norm_words(text) if word not in frozenset(resolve(self.settings)['fillers'])|HESITATION_WORDS];own=[stem(word) for word in norm_words(portion)]
        if not 2<=len(heard)<=TEMPO_FRAGMENT_WORDS+1 or stem(heard[-1]) not in own or any(stem(word) in own for word in heard[:-1]):return None
        at=own.index(stem(heard[-1]))
        return self._walk_start(portion,norm_words(portion)[:at+1]) if len(heard)-1<=at+1 else None
    @staticmethod
    def _of_the_portion(text,portion):
        """Does ``text`` say a word of ``portion``? A number counts whatever it is: the words of a wrong number share no stem with digits."""
        return bool(_stems(text)&_stems(portion)) or (_holds_a_number(text) and _holds_a_number(portion))
    def _hesitates(self,text,portion,decision=None):
        """Rule 4: nothing of the portion in it, and the word will not come (TEMPO_BLANK), or no content word at all («как там», «э-э», nothing recognized), or a fragment that is no question («оксим», «блин
        блин блин»). A doubt, a follow-up and a question word are short too, and they are the job's: they are not a hesitation. ``decision``: what the classifier made of it, when anybody asked."""
        said=norm_words(text);heard=' '.join(said)
        words=[word for word in said if word not in frozenset(resolve(self.settings)['fillers'])|HESITATION_WORDS]
        if self._of_the_portion(text,portion) or doubts(text) or self._follows_on(heard):return False
        if TEMPO_BLANK.search(heard) and len(words)<=TEMPO_BLANK_WORDS:return True
        if frozenset(said)&QUESTION_WORDS and not frozenset(said)&TEMPO_SEEKING:return False
        return not _content(' '.join(words)) or (len(set(words))<=TEMPO_FRAGMENT_WORDS and not (decision and decision.kind in (QUESTION,CORRECTION)))
    def _has_content(self,text):
        """H5 item 1: is this speech with content, however short («Дальше задачка.» at a comma, n1_01 step 8)? A word of the language that says something. Noise the recognizer spelled («оксим», «кхм»), an
        interjection («блин», «ой») and «the word will not come» (TEMPO_BLANK) say nothing to wait for."""
        said=norm_words(text);words=[word for word in said if word not in frozenset(resolve(self.settings)['fillers'])|HESITATION_WORDS]
        if TEMPO_BLANK.search(' '.join(said)) and len(words)<=TEMPO_BLANK_WORDS:return False
        paused=pause_split(said,frozenset(resolve(self.settings)['fillers'])|HESITATION_WORDS)
        if paused is not None:words=[word for word in words if word in fold_asr(paused[0])]      # g25: a request for time is nothing to wait for; what came before it is judged as ever
        return any((probe('known_word',word).value or word.isdigit()) and _content(word) and not any(reading[0]=='INTJ' for reading in probe('readings',word).value) for word in words)      # c24-a1 (fuzz seed 42): «нет не 70 а 60» of the ear says as much as «нет не семьдесят а шестьдесят»
    def _started(self,text,portion):
        """Rule 3: how far the ear's ``text`` got in ``portion``: ``_walk_start``, by value where a number stands (the ear writes «статья семнадцать», the portion «Статья 17»). Fillers do not count wherever they
        stand, but for the words the portion itself has («Так называемые…»). None when it is no clean start."""
        from .ru_alignment import resume_word
        found=resume_word(text,portion)      # the aligner reads first, always (U42, G6 rule 3, R07): no flag; the walk below only where it finds no clean start
        if found is not None:return found
        fillers=frozenset(resolve(self.settings)['fillers'])|HESITATION_WORDS;heard=self._heard_words(text,portion);own=fillers-frozenset(norm_words(portion))
        kept=[word for word in heard if word not in own];whole=len(set(kept))>=len(norm_words(portion))
        return self._start_in(kept,portion,whole) or (self._start_in([word for word in heard if word not in fillers],portion,whole) if own!=fillers else None)
    def _start_in(self,words,portion,whole):
        """``_started`` on the words: a start, and after it nothing but a hesitation («общие как там», «общие не могу вспомнить»). ``whole``: a try as long as the portion did not stop, so a word of content at
        its end stands in the place of the portion's: a wrong repeat, not a pause (``_said_wrong``)."""
        for cut in range(len(words)):
            if cut:
                tail=' '.join(words[len(words)-cut:])
                if self._of_the_portion(words[-cut],portion):return None
                if not self._hesitates(tail,portion) or (whole and _content(tail) and not TEMPO_BLANK.search(tail)):continue
            said=words[:len(words)-cut]
            if cut and self._has_content(tail) and len(_content(' '.join(said)))<2:continue       # H5 skeptic: «купили станок» to «Купили материалы…»: one word of the portion and one of its own open a sentence
            found=self._walk_start(portion,said) or self._said_by_value(' '.join(said),portion)
            if found:return found
            if whole:continue
            if (said_share(' '.join(said),portion) or 0)>0.5:return None      # the coordinator (fix-c20): most of the portion said (more than half) is a try that goes on (_try_went), no place in it is looked for
            found=stumble_place(said,portion)      # G26: a stammer, a jump, a start in the middle, a synonym (always read; no switch)
            if found:return found
        return None
    def _tail_open(self,asked):
        """Does ``asked`` stop on an open tail, with the ear not knowing better?"""
        return probe('open_tail',asked).value and not (self.tempo_live and not self.tempo_speaking and self.tempo_ended is not None and self.clock()-self.tempo_ended>=FAST_TAIL_SECONDS)
    def _unglued(self,text,state):
        """H6 item 3 (n1_01 step 11, n1_04 step 10): the question of a final that glues a repeat of the portion to it: without the portion's words at its head (``_aligned_head``) and at its end. They are the plan's, and the job has the plan."""
        portion=probe('waiting_portion',state=state).value
        if not self.fast_on or portion is None:return text
        head=self._aligned_head(text,state)
        rest=text[len(head):].lstrip(' ,.;:!?…—–-') if head and text.startswith(head) else text
        tokens=rest.split();fillers=resolve(self.settings)['fillers']
        for count in range(max(1,len(tokens)-len(portion.split())-resolve(self.settings)['attempt_extra_words']),len(tokens)):
            said=' '.join(tokens[count:])
            if len(norm_words(said))>=2 and match_current(said,portion,fillers,lenient=False)=='ack':return ' '.join(tokens[:count])
        return rest
    def _said_back(self,text,grown=False,ahead=None):
        """A final that only says back the last question and cues asks nothing: no job, no second answer. A question word or «а …» is the listener's and stays a question.
        g28 (the owner's call of 06.11 09:03): the cues include the plan of the answer in play not cued yet: «источники его образования» said while «…, пассивный —» waits is that answer, known ahead.
        c23-final(A): ``grown`` - the text is the question in play grown: its own final after its partial opened it (a delegation before the final), or the whole utterance of a breath
        whose head opened it (``utterance``). That question is no question said back («восемнадцатая статья налогового» -> «… кодекса это», test_g1_admit; «станок Стоимость …» ->
        «… Амортизация линейным способом за год», test_h5_live n1_01 step 16: since c18 211f329 both were dropped and nobody answered)."""
        if ahead is not None:      # g28: ahead of the answer in play (``ahead``: its state): the ear's reference is no question on the words of the plan while a portion of it waits (said ahead or said back); a cue of an answer overruled since is asked anew
            if probe('waiting_portion',state=ahead).value is None:return False
            said=[]
        else:
            said=self._said_texts()
            if grown and self.question_text in said:said.reverse();said.remove(self.question_text);said.reverse()
        said+=self._plan_said();strip=lambda said:probe('strip_fillers',said,settings=self.settings).value
        return bool(said) and not frozenset(norm_words(text))&QUESTION_WORDS and not self._follows_on(text,tail=True) and not doubts(text) and not self._asked_before(text) and ((adds_nothing(text,said,strip=strip) and not probe('not_this_but',text).value) or _said_within(strip(text),self._plan_said()))
    def _asked_before(self,text):
        """A question of an answer given earlier in the call (not the one in play), asked once more: it is a question, not the last question said back (the deque of ``said_log`` keeps the questions of the last answers too)."""
        state=self.state() or {};strip=lambda said:probe('strip_fillers',said,settings=self.settings).value
        playing=state.get('question') or self.question_text
        if playing and same_question(text,playing,strip=strip) and same_question(playing,text,strip=strip):return False
        mine=_stems(text)
        if len(mine)>=ASKED_AGAIN_FEW_STEMS and mine<=set().union(set(),*map(_stems,[playing or '']+self._plan_said())):return False      # the question in play, or the plan of its answer, said back in fewer words is said back
        return any(isinstance(entry,dict) and entry.get('question') and ((same_question(text,entry['question'],strip=strip) and same_question(entry['question'],text,strip=strip))
                                                                         or (len(mine)>=ASKED_AGAIN_FEW_STEMS and mine<=_stems(entry['question']))) for entry in call_history(state))      # in the same words, or in fewer of them (all of them its own); the call's past by the ONE selector (memory family)
    def _long_talk(self,text,state):
        """h29 (the call of 20:29, nine remarks of 35 to 190 words opened a question on a word in their middle). h31: a form counts where a question stands: at the head of a sentence or in the last clause of the breath,
        «?» anywhere. Inside a clause («мы поговорили сколько») it is talk. What goes to the job is judged by its reply (``_said_already``)."""
        words=str(text).split()
        if len(words)<LONG_TALK_WORDS or '?' in str(text) or self._bank_asks(' '.join(words[-EAR_TAIL_WORDS:]),state):return False
        if reads_text(text):return False      # Fable 10.11 (20:51): a sheet read aloud has no form and is no talk: what the job says to it is the verdict (``_said_already`` still keeps a retelling out)
        sentences=[part for part in re.split(r'[.!…;]+(?!\d)',str(text)) if norm_words(part)]
        last=[part for part in re.split(r'[,:]+(?!\d)',sentences[-1]) if norm_words(part)][-1:] if sentences else []
        return not any(self._opens_asking(part) for part in sentences+last) and not probe('topic_tail',text,settings=self.settings).known      # H7: a form is no more a question than a topic said bare at its end (rule 1): «…, значит 55 статья налогового кодекса»
    @staticmethod
    def _opens_asking(part):
        """Does this piece of speech open as a question or a task: a question word, an order or an infinitive of any verb, past a word that only joins it on? A count of shapes, not a list of verbs."""
        said=norm_words(part)
        while said and said[0] in _JOINS:said=said[1:]
        return bool(said) and (said[0] in QUESTION_WORDS or bool(_ORDER_SHAPE.fullmatch(said[0])) or bool(IMPERATIVE.match(said[0])))
    def _reads_answer(self,text):
        """Words mostly of the answer in play, no «?» and no question word: the owner reading it, whatever else he says («точно, рост цен»)."""
        plan=self._plan_said();said=norm_words(text)
        if not plan or not said or '?' in str(text) or frozenset(said)&QUESTION_WORDS or doubts(' '.join(said[-2:])):return False      # a doubt stands at the end («…, ты уверена»), an agreeing word at the head («точно, рост цен»)
        return sum(bool(_stems(word)&_stems(plan[0])) for word in said)*2>=len(said)
    def _talk_no_question(self,text,answer=None):
        """h29 (the call of 20:29: 131, 190, 698 s, the answer began again): the model answers whatever it hears, so its reply proves no question. With an answer given, a question shows itself: a form, the base, a follow-up, a doubt.
        Words mostly of that answer are the owner reading it, in any form, «Та-ак Веках» too. With no answer given the reply still admits (a topic said bare), a long breath apart. h30: a remark of no form may yet be the job's to answer («а двадцать пять», «да, 25»)."""
        state=self.state()
        if self._long_talk(text,state):return not shares(text,answer,stems=ASK_ANSWER_STEMS,words=ASK_ANSWER_WORDS)      # U35 (a): a long ask of no form that the model answers in substance, on its words, is no talk
        if self._follows_on(text,tail=True) or self._bank_asks(text,state) or probe('not_this_but',text).value:return False      # «не охлаждать, а нагревать» argues: rule 4 (``_open_to_the_cloud``)
        return self._reads_answer(text)
    @staticmethod
    def _quotes(answer,asked):
        """Do the words of ``answer`` stand in ``asked`` in the same order?"""
        rest=[_stems(word) for word in norm_words(asked)]
        for word in norm_words(answer):
            stems=_stems(word)
            if not stems:continue
            at=next((index for index,other in enumerate(rest) if stems&other),None)
            if at is None:return False
            rest=rest[at+1:]
        return True
    def _topic_stems(self,asked=''):
        """The words of meaning of the last questions and cues of the call (``said_log``): what the talk is about now. Round 3: not of ``asked`` itself, which is the latest of them (a remark under judgment
        is always about itself: «зачем ты это опять повторяешь» then restarted the answer it had just got)."""
        strip=lambda said:probe('strip_fillers',said,settings=self.settings).value
        return set().union(set(),*(_stems(str(said)) for said in self._said_texts() if not (asked and same_question(said,asked,strip=strip))))
    def _said_texts(self):return [text for _,text,_ in self.said_log]      # the questions and cues said lately (``said_log``), oldest first
    def _said_already(self,answer,asked):
        """h29, the map of the conversation (the owner: «он видит, что он до этого говорил»; 131, 846, 878 s of the call of 20:29): the model's text whose words are mostly an answer of this conversation is not said a second time.
        The same question asked again is a request for it. The state's history and the answer on: the conversation's own record, no list of phrases. h31: measured against old answers, not old questions; a number of its own is a new answer;
        a question is answered unless the reply is an old answer that has nothing to do with what was asked (half_hour 24 has, «ты вообще меня слышишь?» has not); a question's own words in the reply are no retelling («Толстой или Достоевский?»).
        Answer-fusion 2 (16.11): THE one «already said» of the controller. Four checks counted it four ways (the job's text; its head against the answer in play; the cloud's reply to a candidate by half of its words; the cloud's reply to a question by
        the order of 5 words): the job's text, the cloud's reply (``_reply_admits``, the route's first sentences) and the ear's first sentence are all judged here, against the call's answers, the answer in play and the plan."""
        mine=_stems(answer);asked=str(asked)
        if len(mine)<4:return False
        if (doubts(asked) or asks_again(asked) or self._classify(asked,self.state() or {}).kind in (RESUME,REPEAT,NEXT)) and not self._reads_answer(asked):return False      # a repeat or a resume asks for it too      # «ты уверена», «пересчитайте ещё раз»: the answer again is what was asked for
        question=asked.rstrip().endswith('?') or 'или' in norm_words(asked) or self._classify(asked,{}).kind==QUESTION      # «организации или физические лица»: a choice, its answer is its own words
        if not question and mine<=_stems(asked) and self._quotes(answer,asked) and (len(norm_words(answer))>=SAID_BACK_SHARE*len(norm_words(asked)) or self._opens_asking(answer)):return True      # Fable 10.11: a reply that itself orders or asks («Рассчитайте долю…») is the task said back however short      # h30, К16 (1077 s of the call of 20:29): the task said back to the one who read it is no answer; h31: said back is in its order, «да, при таком давлении нужно уменьшать» answers
        short=len(asked.split())<LONG_TALK_WORDS      # a short remark that speaks of the exchange (a dispute: «да это просто слова») is answered by that answer, as a short question is; only a long talk is judged by the share alone
        state=self.state() or {}
        given=[(entry.get('question'),entry.get('answer')) for entry in self.call_exchanges()]+[(state.get('question'),text) for text in self._plan_said()]+[tuple(played) for played in [self.fast_in_play()] if played]      # the call's answers (``call_exchanges``): an earlier call's are not «already said»
        strip=lambda said:probe('strip_fillers',said,settings=self.settings).value
        from .ru_numbers import digits_for_words
        from .classifier import IMPERATIVE
        numbers=lambda said:{key for key in _protected(_atoms(digits_for_words(str(said)))) if key.startswith('#')}      # U43: «four hundred fifty» is 450, whichever language the question is asked in
        bids=short and bool(IMPERATIVE.search(asked))      # fix4-scenes (w3 n2_d06 10, n2_d14 8, n2_c05 10, n2_c06 10, n2_d15 12): a short order to say («уточни», «объясните», «приведите пример») asks to be told: the answer it gets is said, as for a doubt. Round 3 took ``asked`` out of ``_topic_stems``, and the question of the answer in play had already left the eight of ``said_log`` under its own repeated cues
        for old_question,old in given:
            if old and old_question and self._asked_again(asked,old_question):return False      # its question once more, with words round it: the answer again is what was asked for, whoever else said it
            if not old or (old_question and same_question(asked,old_question,strip=strip)):continue
            if numbers(answer)-numbers(f'{old_question or ""} {old}') or len(mine&_stems(old))<SAID_ALREADY_SHARE*len(mine):continue
            if bids or (short and ((mine|_stems(old_question or '')|self._topic_stems(asked))&_stems(asked) or numbers(answer)&numbers(asked))):continue      # it speaks of what was asked, of the question this old answer answered («приведи пример» after «посчитайте налог»), or of its numbers («три» heard, «3» said); words alike are not one question («не охлаждать, а нагревать» and back)
            return True
        return False
    @staticmethod
    def _asked_again(asked,old_question):
        """The question of an old answer asked once more with words round it («Вот смотрите, постоянные расходы …, и точка безубыточности в штуках» for «и точка безубыточности в штуках»): all the words of meaning of the old
        question (``ASKED_AGAIN_STEMS`` of them at least) are in what was asked now. The same question asked again is a request for its answer, whatever stands before it."""
        old=_stems(old_question)
        return len(old)>=ASKED_AGAIN_STEMS and old<=_stems(asked)
    def _own_number(self,text,state):
        """h29 (925 s: «статья 422» while «Статья 79…» was on): a number that is not in the answer on: words in common do not make it a try at that answer."""
        plan=' '.join(str(chunk) for chunk in (state or {}).get('chunks') or ())
        return bool(plan) and bool({key for key in _protected(_atoms(text)) if key.startswith('#')}-set(_protected(_atoms(plan))))
    def _question_said_back(self,text):
        """g28: a final that is the question in play said again and then the cue's words said back (the cloud glues the listener's reading of the question and the
        repeat into one turn): the rest after the question, to be judged alone. ``None`` when it is no such thing: a question asked again alone stays a question."""
        asked=(self.state() or {}).get('question') or self.question_text
        if not asked or not isinstance(text,str):return None
        words=text.split();size=len(norm_words(asked));strip=lambda said:probe('strip_fillers',said,settings=self.settings).value
        cues=[said for said in self._said_texts() if not same_question(said,asked,strip=strip)]+self._plan_said()
        for cut in range(max(1,size-2),min(len(words),size+3)):
            head,rest=' '.join(words[:cut]),' '.join(words[cut:])
            if len(norm_words(rest))>=2 and not frozenset(norm_words(rest))&QUESTION_WORDS and same_question(head,asked,strip=strip) and same_question(asked,head,strip=strip) and adds_nothing(rest,cues,strip=strip):return rest
        return None
    def fast_prepare(self,record):
        """The local ear reported an utterance (a ``ShadowEar.poll`` record). A question of at least three words that the model-knowledge route would take
        (no lookup, no data that changes) is PREPARED: the channel starts a job for its text. Nothing is said and no state changes here; only a release
        adopts it, and only then is its text a verdict (rule 9)."""
        if not self.fast_on or self.lookup_policy!='required':return []
        try:
            if type(record.get('offset')) in (int,float):self.ear_ended=record['offset']
            text=record.get('text')
            if self.prepare_wide:return self._fast_wide_ear(record)
            if not isinstance(text,str) or record.get('kind')!=QUESTION:return []
            asked=probe('strip_fillers',text,settings=self.settings).value.strip()
            if self._read_again(asked,self.state()):return []      # c24-c: the question of the answer being written: no job prepared
            return [{'type':'fast','op':'prepare','text':asked}] if self._fast_preparable(asked) else []
        except Exception:return []
    def _wide_break(self):
        """A breath is over: a pause, or a final of it."""
        self.wide_breath=[];self.wide_no+=1
    def fast_stable(self):
        """H7 item 3 (С1), the wire says when: the cloud's partial has stood still with the ear silent. It goes the way of ``_fast_wide``."""
        if not self.prepare_wide or not self.fast_on or self.lookup_policy!='required':return []
        try:
            user=self.ledger.latest_user()
            if not user or not user['valid'] or user['final'] or user['id'] in self.seen:return []
            ear=' '.join(piece[1] for piece in self.wide_breath)
            if self.live_first:return self._live_stable(user,ear)
            return self._fast_wide(user['text'],'partial') if len(norm_words(probe('question_part',user['text']).value))>=len(norm_words(probe('question_part',ear).value)) else []      # behind the ear it is half of what was said: it may catch up
        except Exception:return []
    def fast_stable_piece(self):
        """W13 item 4: while the listener still speaks, the STABLE piece of the cloud's open turn (two deltas agree: ``two_witnesses.Pieces``) that has gained a content word since the last look goes the way
        of ``_fast_wide``: the job starts on it, not on the final. A job of the same meaning already running is kept (``FastText._prepare_wide``: ``_fits``)."""
        if not self.prepare_wide or not self.fast_on or self.lookup_policy!='required' or self.ear_job or self.live_first:return []      # c16: the ear's breath is ahead of this piece, and jobs on the preface took the place of the one on the question (n1_02 of c15-cand-g)
        try:
            user=self.ledger.latest_user()
            if not user or not user['valid'] or user['final'] or user['id'] in self.seen:return []
            piece=self.__dict__.setdefault('job_pieces',two_witnesses.Pieces()).feed(user['id'],user['text'])
            words=frozenset(w for w in norm_words(probe('question_part',piece).value) if w not in STOPWORDS and w not in HESITATION_WORDS)
            seen=self.job_piece_seen
            if len(words)<2 or (seen is not None and seen[0]==user['id'] and words<=seen[1]):return []
            self.job_piece_seen=(user['id'],words)
            return self._fast_wide(piece,'stable_piece')
        except Exception:return []
    def _fast_wide(self,text,on):
        """H7: what the arbiter would leave to a job, with the filter of a final (``_ear_may_open``: no repeat, command or try at the portion) and what the route would take (``_fast_preparable`` of its question part), is PREPARED. Only a release adopts it. See PREPARE_WORDS."""
        asked=probe('strip_fillers',text,settings=self.settings).value.strip()
        if not (LIVE_MIN_WORDS if self.live_first and on=='partial' else PREPARE_MIN_WORDS)<=len(norm_words(probe('question_part',asked).value if self.ear_job else asked))<=PREPARE_WORDS or self._reference(asked):return []      # c16: a long preface is no reason to leave the question without a job
        state=self.state()
        if not (self._ear_may_open(asked,state) or self._classify(asked,self._heard_with(state)).kind==CORRECTION) or not self._fast_routed(probe('question_part',asked).value):return []
        return [{'type':'fast','op':'prepare','text':asked,'on':on,'breath':self.wide_no}]
    def _fast_fed(self,turn,qid,kind,text):
        candidate=self.candidate
        if self.fast_on and candidate and candidate.get('job')==turn and candidate['id']==qid:return self._fast_judged(turn,kind,text)
        if not self.fast_on or self.fast_done or self.fast_asked!=(qid,turn) or qid!=self.question_id:return False,[]
        if self.local_answer:
            self.fast_done=True;return False,[]
        if kind=='text':
            replaced=self._fast_replaced(turn,text)
            if replaced is not None:return True,replaced
            self.fast_said+=text
            if self.fast_turn:return True,self.provider({'type':'turn.delta','turn_id':turn,'delta':text})
            answer=brain_answer(self.fast_said)
            if answer and self._said_already(answer,self.question_text):
                self.fast_done=True
                logger.info('echo-sync decision kind=silent reason=said_already revision=%s',(self.state() or {}).get('revision'))
                return False,self._fast_declined(turn)
            actions=self._fast_answers(turn,answer) if answer else []
            if answer and text.startswith(REFUSAL) and self.fast_turn==turn:self.fast_provisional=(turn,len((self.ledger.snapshot(turn) or {}).get('text') or ''))      # F20: the roads' sentence stands until the job's real text takes its place (``_fast_replaced``)
            return True,actions
        self.fast_done=True
        if kind=='failed' and not self._answered():return False,self._fast_failed(turn)
        command=brain_command(self.fast_said) if kind=='done' else None
        if command and self._asks_for_detail(command,(self.ledger.snapshot(qid) or {}).get('text','')):return False,self._fast_hand_back(turn)      # level2-c of 06.11: «Подробнее» read as [продолжай]: the cloud's turns are the answer, the plan that waits is not said again
        if command:return False,self._fast_command(qid,command,job=turn)
        if self.fast_turn is None and not self.published and kind=='done':
            held=self._doubt_held(self.question_tail or self.question_text,self.fast_played)
            if held:return False,self._fast_answers(turn,held)+self._fast_close(turn)
        if self.fast_turn is None:
            if (self.sources or self.source_missing or self.search_refused) and not self.published and not brain_answer(self.fast_said):
                q_candidate=self.ledger.snapshot(self.question_id)
                if q_candidate and self._candidate_asks(q_candidate):
                    return False,self._fast_hand_back(turn)
            return False,[] if self.published else self._fast_declined(turn)
        if kind=='failed':self.fast_said=self._fast_whole()
        else:self._remember_answer()
        actions=(self._fast_replaced(turn,'',final=True) or [])+self._fast_close(turn)      # F20: a real text after the roads' sentence that was not stable before the end takes its place now
        # nothing was published of what it said (a backchannel, talk about itself): that is no answer. A question held for its utterance goes on; a refused text is the watchdog's
        if not self.published and self.held_source is None and not self.refused_attempt:actions+=self._fast_declined(turn)
        return False,actions
    def _fast_declined(self,turn):
        """Rule 3: the job's verdict on the open question is that nothing is asked: it is dropped and the plan gives back, once the listener is quiet (``_plan_after_decline``)."""
        self._fast_out(turn);self.fast_declined=self.question_id;self.lookup_topic=self.fast_topic;self._fast_told(self.question_id);self._keep_unanswered(self.question_text)
        logger.info('echo-sync decision kind=silent reason=fast_text_declined revision=%s',(self.state() or {}).get('revision'))
        return self._fast_no_search(self.question_id)+self._plan_after_decline(self.clock())
    def _fast_judged(self,turn,kind,text):
        """The job of a candidate (``_take_candidate``): its text is the verdict, nothing stands open meanwhile. A failure hands the candidate to the cloud's evidence as of now."""
        candidate=self.candidate
        if kind=='failed':
            if candidate.get('retried'):return False,self._candidate_back()
            for key in ('over','verdict'):candidate.pop(key,None)
            candidate.update(job=None,said='',retried=True)      # H5 item 7: ``fast_feed`` asks again
            logger.info('echo-sync decision kind=silent reason=fast_text_failed_asked_again revision=%s',(self.state() or {}).get('revision'))
            return False,[]
        if kind=='text' and text.startswith(REFUSAL) and not self._candidate_asks(candidate):candidate['refusal']=True;return False,[]      # the honest sentence of the roads is about a question: of words that ask nothing it is no verdict and no admission (it would open a remark as a question over a stopped plan)
        if kind=='done' and candidate.get('refusal') and not candidate['said']:return False,self._candidate_back()      # the roads were out of words: nothing was said by the job, so the candidate goes to the cloud's evidence as after a failure
        if kind=='text':candidate['said']+=text
        else:candidate['over']=True
        return self._fast_verdict(turn)
    def _fast_said_again(self,candidate):
        """c16: the old answer is no answer to what the job was asked (``_said_already``): nothing is admitted and the plan stands. Words that open on a stop are that stop: the ear heard «стоп» alone and dropped it because the speech went on
        (``ear act=dropped reason=new_onset``), the classifier gives the long final no form. Anything else is a decline. Returns what ``_fast_judged`` returns."""
        self.candidate=None;self.fast_passed=candidate['id']
        logger.info('echo-sync decision kind=silent reason=fast_text_said_again revision=%s',(self.state() or {}).get('revision'))
        if self._classify(re.split(r'[,.;:!?…—–]',candidate['text'].strip(),maxsplit=1)[0],self.state() or {}).kind==STOP:return False,self._fast_command(candidate['id'],'стоп')
        self.fast_head=(candidate['text'],candidate['taken'])
        self.auto_repeats=0      # c24 F1 (w3 n2_d01 12, n2_h02 11, …): «Да нет, там 150» is the owner at the answer, and the job stands by it: the timer may say the portion again (only silence is bounded)
        self._tempo_declined()
        return False,self._fast_no_search(candidate['id'])
    def _doubt_held(self,heard,played):
        """H6 item 7 (1 of 8 measured): the job said «—» to a doubt of the answer in play (``played``): the first sentence of that answer is said again: a short confirmation, never silence. '' when it was no such doubt."""
        if not played or not played[1] or not of_the_answer(heard,played[1],played[0]):return ''
        said_at=max((at for at,_,cue in self.said_log if cue),default=None)      # the last thing the prompter said: the lines the room said after it are counted, the doubt among them; what is said TO the answer (a confirmation, «повтори», «дальше») is no line of the room
        lines=sum(done>said_at and (self.resolutions.get(tid) or {}).get('resolution') not in (ACK,REPEAT,STOP,NEXT,RESUME) for tid,done in self.user_done_at.items()) if said_at is not None else 0
        if lines>judge_table.DOUBT_WINDOW_LINES:return ''      # harvest11 #6: the doubt is the 3rd line after the answer or later (8 of the 13 measured): it is talk, the old answer is not said again
        found=_SPOKEN_SENTENCE.search(played[1])
        return found.group().strip() if found else played[1].strip()
    def _fast_breath(self,take=True):
        """H5 skeptic (n1_01 step 16: one breath, four finals, each declined alone, the last asked of nobody): what the job ruled out is the head of the next final while the ear heard no silence between them, and no remark of its
        own (129.6 of the call, 60 words about the prompter, then «Пять умножить на пять» in the same breath): at most FAST_HEAD_WORDS words, the breath going on. Taken once; ``take=False`` only looks (is the next final the same breath?)."""
        head=self.fast_head
        if take:self.fast_head=None
        return head[0] if head and len(norm_words(head[0]))<=FAST_HEAD_WORDS and self._ear_went_on(head[1]) else None
    def _fast_mark_waits(self,uid,word,job=None):
        """H6 item 5: the command waits for the ear's silence (``_fast_mark_due``). A new question takes it away (``_open_question``), and so does what moves the plan."""
        self.fast_mark={'uid':uid,'word':word,'job':job,'at':self.clock()}
        logger.info('echo-sync decision kind=silent reason=command_waits_for_silence word=%s revision=%s',word,(self.state() or {}).get('revision'))
    def _fast_mark_due(self,now):
        """H6 item 5, on the tick: the ear's silence has lasted, nothing is left to judge: the command is carried out. FAST_MARK_SECONDS bound the wait: speech that goes on for ever must not hold a stop for good."""
        mark=self.fast_mark
        if mark is None or (now<mark['at']+FAST_MARK_SECONDS and not (self._utterance_over('') and not (self.candidate and 'job' in self.candidate))):return []
        self.fast_mark=None
        return self._fast_command(mark['uid'],mark['word'],job=mark['job'],settled=True)
    @staticmethod
    def _asks_for_detail(command,text):
        """Level2-c of 06.11 (step 45): «Подробнее.» over a waiting portion; the job said the mark [продолжай] and the portion that waited was said again as the answer. A request for more of the answer
        (``MORE_DETAIL``) is never a command to go on: a mark of going on that the words do not say is none, and the cloud's answer to the request stands."""
        return command in ('продолжай','дальше') and bool(MORE_DETAIL.search(str(text or '')))
    def _fast_command(self,uid,word,job=None,settled=False):
        """H5 item 3: the job's text is a mark (fast_text.COMMANDS): the final ``uid`` is that command in words the grammars do not know, and it goes the way of the word itself (the path of a tail: the turn was judged, only the kind
        is decided here). ``job``: the job of a question the classifier opened: it asks nothing, it is gone, and what it took over is the plan the command is about. A plan abandoned by this very final comes back through
        the judge's going on (``engine.going_on``). With no plan in play: silence, as for a decline. H6 item 5: [дальше] and [стоп] only on whole speech (``settled``: it has been waited for)."""
        if word in ('дальше','стоп') and not settled and self.tempo_live and not self._utterance_over(''):
            self._fast_mark_waits(uid,word,job)
            return []
        state=self.state() or {};turn=self.ledger.snapshot(uid);held=self._plan_held(state)
        logger.info('echo-sync decision kind=silent reason=fast_text_command word=%s revision=%s',word,state.get('revision'))
        actions=[]
        if job:
            waiting=self.candidate
            self._fast_told(uid);self._fast_out(job);actions=self._drop_question();self.lookup_topic=self.fast_topic;self.suspended=None;self.candidate=waiting;self.fast_passed=uid
            if held is not None:self._plan_back(held)     # as it was: even «дальше» says a cut portion again (engine.going_on)
        elif held is not None and word=='продолжай':
            back=self._take_back(turn,state,'fast_command',resume=True)
            if back is not None:return back+self._fast_no_search(uid)
        state=self.state() or {}
        if not self._plan_in_play(word,state):
            self._tempo_declined()
            return actions+self._fast_no_search(uid)
        return actions+self._accept_user({**turn,'final':True,'text':COMMAND_SAID.get(word,word)},boundary='fast_command',tail=True,cause='fast_command')+self._fast_no_search(uid)
    def _plan_in_play(self,word,state):
        """Has the command ``word`` a plan to act on? A portion that waits or a paused one; the end of an answer can only be heard again; going on is the engine's to say (``going_on``: what can be restored too)."""
        if probe('waiting_portion',state=state).value is not None:return True
        decision=self._classify(word,state)
        if word=='повтори' and not (state.get('abandoned') is not None and judge_table.going_plan(self.engine,state,decision)[0]=='restore'):return bool(state.get('completed') and state.get('chunks'))      # c8b: «повтори» of an abandoned portion is the engine's going on too
        return judge_table.going_plan(self.engine,state,decision)[0] in ('next','reissue','restore')
    def _fast_admit(self,turn,answer):
        """The job's answer is the admission, and its text the answer (``fast_feed``). Rule 6: a question that needs a lookup waits for its sources and one more job."""
        candidate=self.candidate;qid=candidate['id'];over=candidate.get('over')
        actions=self._admit('text',job=turn,said=answer)
        if self.fast_asked!=(qid,turn):return False,actions
        actions+=self._fast_answers(turn,answer)
        return (False,actions+self._fast_fed(turn,qid,'done','')[1]) if over else (True,actions)
    def _candidate_back(self):
        """The candidate's job failed or the channel is gone: the evidence of the cloud is looked at as of now, as when the candidate was taken."""
        candidate=self.candidate
        for key in ('job','said','over','verdict'):candidate.pop(key,None)
        self.fast_handed=candidate['id']
        if self._candidate_asks(candidate):self.handed_asks=(self.clock(),(self.state() or {}).get('revision'))      # c24-a1 (fuzz seed 143): a question went back to the cloud: the older first cue waits for it (``first_cue_hold``), a remark said meanwhile replaces no question
        logger.info('echo-sync decision kind=silent reason=fast_text_candidate_handed_back revision=%s',(self.state() or {}).get('revision'))
        actions=self._candidate_evidence(candidate['id'])
        if not actions and str(candidate['id']).startswith('ear-final-') and self._classify(candidate['text'],self.state() or {}).kind==QUESTION:
            # g19 (never silent): the ear stood in for a final the cloud never sent, so no turn of the cloud will ever weigh it: a question whose job failed is given up aloud, not in silence
            self.candidate=None;self.fast_passed=candidate['id']
            logger.info('echo-sync decision kind=silent reason=ear_question_unanswered revision=%s',(self.state() or {}).get('revision'))
            return self._give_up_aloud('ear_question_unanswered')
        if not actions and self.candidate is candidate:
            candidate['back']=self.clock()      # g3-chaos: the cloud's evidence is awaited, bounded (``_answer_watchdog``)
            revision=(self.state() or {}).get('revision')
            if revision is not None and self._candidate_asks(candidate):self.ear_asked_on=revision      # ... and meanwhile the older plan is not said again on its own (W14: a new question nobody answers); a remark lets it come back
        return actions
    def _candidate_asks(self,candidate):
        """Is the candidate a question by its words: the ear's, its turn's final, or the cloud's final of the same speech that came as a turn of its own after the ear stood in
        (g3-chaos: nobody else will say). A newer utterance would have replaced the candidate."""
        texts=[candidate['text']]
        for turn in (self.ledger.snapshot(candidate['id']),self.ledger.latest_user()):
            if turn and turn.get('final') and turn['text'].strip():texts.append(turn['text'])
        try:return any(self._classify(text,self.state()).kind==QUESTION or probe('question_by_form',text).value for text in texts)      # c25-a (the owner's live call, G1 ear_tempo): «Нужно не X, а Y …», «а как … считают»: the ear writes no «?»; the old portion said again while it is thought on is an old answer
        except Exception:return False                 # noqa: BLE001 - not sure it asks: it does not
