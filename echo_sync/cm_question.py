"""The question methods of ``ControlledMedia`` (cut from controlled_media.py by tools/split_controlled_media.py). Imports from cm_base, never from controlled_media."""
from .cm_base import (CORRECTION, Decision, EAR_ASK_HOLD_SECONDS, FAST_TAIL_SECONDS, FAST_TURN, GATE_TALK,
    HANDED_BACK_WAIT_SECONDS, INPUT_CLOCK_SLACK_MS, MERGE_PATIENCE_SECONDS, NEXT, NUMBER_DOUBT, NUMBER_PREMISE, NUMBER_TRUSTS, PLAN_BACK_SECONDS,
    QUESTION, QUIET, RECONNECT_WINDOW_S, REFUSE_BEFORE_DROP_SECONDS, RESUME, RETOLD_WORDS, SOURCES_DIFFER, SPLIT_JOIN_SECONDS, STOP, SequenceMatcher,
    TEMPO_FILLER_SECONDS, TURN_MAP_CAP, UNANSWERED_KEPT, UNANSWERED_MIN_WORDS, UNANSWERED_SECONDS, _ASKS_A_CAUSE, _ASKS_A_NUMBER, _ASKS_A_PLACE,
    _ASKS_A_PURPOSE, _ENDS_SENTENCE, _GIVES_A_CAUSE, _SAYS_A_PLACE, _SAYS_A_PURPOSE, _SEARCH_PERSONAL, _content,
    _number_grows, _stems, TOPIC_MARK, command_ruling, complete_followup, compact_opening, gate_decide, logger, needs_current_data, needs_verification, norm_words, probe,
    question_key, quick_answer, quick_stated, same_question, same_start, wide_refusal, word_problem, asks_for_more, says_a_number, STOPWORDS, _MAY_ANSWER, _NO_SUBSTANCE)


class QuestionSlot:
    """U39 / U94.4 / U62: the ONE object a question lives in. Its fields (``FIELDS``) were 59 attributes of the controller, set by an opening in one place and cleared by closings in six others,
    each clearing another set; now they are slots of this object (``SlotField`` on the controller reads and writes them, so a reader outside does not change). ``open`` is the only way a question is
    born: every field of ``EMPTY`` takes its empty value and the ones the opening knows are set, the ``version`` of the slot moves; ``close`` is the only way fields are emptied (the closings of ``ACTS`` name
    which). A TICKET is ``(question id, version)``: what an answer, a search or a sound was made for; ``stale`` is true for every ticket but the one standing now. The values of ``EMPTY`` are factories: a
    new question never gets the old question's list or set."""
    EMPTY={'held_source':lambda:None,'unsettled':lambda:None,'settled_segment':lambda:None,'grounded':lambda:False,'sources':list,'published':lambda:'','revision':lambda:None,'source_id':lambda:None,
           'answer_marker':lambda:'','lead_said':lambda:'','context_requested':lambda:False,'delivery_ready':lambda:False,'delivered_at':lambda:None,'context_appended_at':lambda:None,
           'delivery_anchors':dict,'delivered_transport':lambda:None,'source_segment_id':lambda:None,'source_segment_prefix':lambda:'','closed_source_segments':set,'pending_restart':lambda:None,
           'segment_offsets':dict,'restart_base':lambda:None,'restarts':lambda:0,'corrected':lambda:False,'joined_segments':set,'candidate':lambda:None,'local_answer':lambda:False,
           'refused_attempt':lambda:None,'fast_turn':lambda:None,'fast_done':lambda:False,'fast_said':lambda:'','fast_route':lambda:('model',{}),'fast_tail':lambda:None,'fast_mark':lambda:None,
           'first_since':lambda:None,'first_hold_from':lambda:None,'lookup_served':lambda:False,'search_refused':lambda:False,'refused_lookup':lambda:False,'source_missing':lambda:False}
    # the fields only a closing / an opening that knows them sets; their value before any question
    # ``lookup_topic`` is NOT a field of the question: the conversation ledger holds it (M9 kind ``topic``, cm_memory.MemoryMixin.lookup_topic: it ends with a call, not with a question)
    HELD={'question_id':None,'question_text':'','question_part':'','question_reason':'','question_kind':None,'question_tail':'','question_clock':None,'fast_topic':None,'direct_content':False,
          'fast_asked':None,'fast_played':None,'fast_text':'','delegation_id':None,'lookup_query':'','suspended':None,'abandon':None,'_answer':None}
    # what a closing of ``ACTS`` leaves in the fields it names (the one table: ``ControlledMedia._step_clear`` reads it)
    CLOSED={'question_id':None,'grounded':False,'held_source':None,'unsettled':None,'settled_segment':None,'refused_attempt':None,'candidate':None,'abandon':None,'suspended':None,'_answer':None}
    FIELDS=frozenset(EMPTY)|frozenset(HELD)

    def __init__(self):
        self.version=0
        self.values={name:make() for name,make in self.EMPTY.items()}
        self.values.update(self.HELD)

    def open(self,**given):
        """A question is born: the version moves, every field of ``EMPTY`` is empty, ``given`` (the fields the opening knows) is set. The one opening."""
        unknown=set(given)-self.FIELDS
        if unknown:raise KeyError(f'not a field of the question: {sorted(unknown)}')
        self.version+=1
        for name,make in self.EMPTY.items():self.values[name]=make()
        self.values.update(given)
        return self.ticket

    def close(self,*names):
        """The listed fields are emptied as the closing of the question says (``CLOSED``); nothing else is touched."""
        for name in names:self.values[name]=self.CLOSED[name]

    @property
    def ticket(self):
        return (self.values['question_id'],self.version)

    def stale(self,ticket):
        """Is ``ticket`` of another question, or another version of the slot, than stands now? A ticket that is not a pair is stale."""
        return not (isinstance(ticket,tuple) and len(ticket)==2 and tuple(ticket)==self.ticket)


class SlotField:
    """A field of the controller that lives in its ``QuestionSlot``: reading and writing it as an attribute (``self.question_id``) reaches the slot, so no reader changes."""
    def __set_name__(self,owner,name):self.name=name
    def __get__(self,obj,owner=None):
        return self if obj is None else obj.slot.values[self.name]
    def __set__(self,obj,value):
        obj.slot.values[self.name]=value


def _slot_of(self):
    slot=self.__dict__.get('_slot')
    if slot is None:slot=self.__dict__['_slot']=QuestionSlot()
    return slot


class QuestionMixin:
    slot=property(_slot_of)      # U39: the question's own object (``QuestionSlot``); the fields below are its slots
    _answer=SlotField()
    abandon=SlotField()
    answer_marker=SlotField()
    candidate=SlotField()
    closed_source_segments=SlotField()
    context_appended_at=SlotField()
    context_requested=SlotField()
    corrected=SlotField()
    delegation_id=SlotField()
    delivered_at=SlotField()
    delivered_transport=SlotField()
    delivery_anchors=SlotField()
    delivery_ready=SlotField()
    direct_content=SlotField()
    fast_asked=SlotField()
    fast_done=SlotField()
    fast_mark=SlotField()
    fast_played=SlotField()
    fast_route=SlotField()
    fast_said=SlotField()
    fast_tail=SlotField()
    fast_text=SlotField()
    fast_topic=SlotField()
    fast_turn=SlotField()
    first_hold_from=SlotField()
    first_since=SlotField()
    grounded=SlotField()
    held_source=SlotField()
    joined_segments=SlotField()
    lead_said=SlotField()
    local_answer=SlotField()
    lookup_query=SlotField()
    lookup_served=SlotField()
    pending_restart=SlotField()
    published=SlotField()
    question_clock=SlotField()
    question_id=SlotField()
    question_kind=SlotField()
    question_part=SlotField()
    question_reason=SlotField()
    question_tail=SlotField()
    question_text=SlotField()
    refused_attempt=SlotField()
    refused_lookup=SlotField()
    restart_base=SlotField()
    restarts=SlotField()
    revision=SlotField()
    search_refused=SlotField()
    segment_offsets=SlotField()
    settled_segment=SlotField()
    source_id=SlotField()
    source_missing=SlotField()
    source_segment_id=SlotField()
    source_segment_prefix=SlotField()
    sources=SlotField()
    suspended=SlotField()
    unsettled=SlotField()
    def no_search(self,epoch):
        """F3 (item 2): the transport refused the public lookup of this question - it is personal. The listener is told nothing (it was
        «Ошибка. Повторите вопрос.», and the cloud's answer was then never dictated). What happens depends on the question (round 1):

        - it does not need verification: it goes on the model-knowledge route, and the model, if it asked for a search, is told through the result of
          its delegation that there is none (``_no_search_result``); one that delegates later is told then (``_delegated_lookup``);
        - it needs verification (a rate, a code article, «сейчас»): the model's memory is no source. The first-person frame goes (``impersonal``); if
          what remains is public the PUBLIC lookup runs on that - a ``lookup`` action for the wire - and the sourced answer is the answer; if not, the
          question stays unanswered (the watchdog's phrase, in its plain budget: there is no lookup to wait for) and the model is told NOTHING - above
          all not that no search is needed.

        The epoch of a question that has been replaced since is ignored."""
        if epoch!=self.epoch or not self.question_id:return []
        history=(self.state() or {}).get('history',())
        part=self._part()
        if needs_verification(part,history) or needs_verification(self.lookup_query or '',history) or (self.fast_call and needs_current_data(part,history)):
            rest=self._impersonal(part) or (self._impersonal(probe('question_part',part).value) if probe('question_part',part).value!=part else '')     # w10 item 1: the introduction («меня зовут Игорь…») stays home, the general question after it is looked up
            if rest:
                self.lookup_query=rest
                logger.info('echo-sync decision kind=lookup reason=personal_public_remainder revision=%s',(self.state() or {}).get('revision'))
                return [{'type':'lookup','epoch':self.epoch,'question':rest,'lookup_question':rest,'input_turn_id':self.question_id}]
            if self.fast_call and not needs_current_data(part,history):return self._from_memory('no_search_from_memory')     # H7 item 0: there is no search for it, the job is told so and decides: not 9.9 s of silence and «Нет ответа»
            if self.fast_call and _SEARCH_PERSONAL.search(part) and self.public_lookup_allowed(part):return self._from_memory('no_search_to_the_job')     # E88: what only the wider words keep from the search still reaches the job, told there is no source: talk is declined, data that changes is «Не нашёл» (BRAIN)
            self.refused_lookup=True
            logger.info('echo-sync decision kind=silent reason=personal_unanswerable revision=%s',(self.state() or {}).get('revision'))
            return []
        self.direct_content=True;self.search_refused=True
        return self._fast_release('model')+self._no_search_result()
    def _begin_call(self):
        """F3 (the owner's call of 3 Nov 09:55): a NEW call starts clean. The phone's session id is one constant for every call, so the call opened
        at «revision=13 index=1» - a portion an earlier call had left waiting - and its first words were judged against that portion (the verdict was
        'unrelated_speech', not 'a topic of its own'), and an early «повтори» would have said the earlier call's portion. A STALE answer that still
        WAITS for the listener (or whose question was never answered: always) is retired the way a new question retires it: new revision, nothing
        left to repeat, the history entry kept ('interrupted': the conversation map still tells the model, and «продолжай» / «вернёмся к …» still go
        on with it inside the resume window). An answer that was said to the end is left alone.

        Fix round 1: only a STALE one. A phone that re-dials after a drop of the line is the same conversation: when the last portion was spoken at
        most RECONNECT_WINDOW_S ago (the engine's wall clock, ``issued_at``; else the time of the history entry) the portion is kept - the listener's
        «повтори» replays it and their repeat confirms it (``reconnect_kept``: an ACK passes the quiet reopen). Not in ``__init__``: a controller built
        again over the same file (a test's reconnect) keeps the stored position. Returns what was left unsaid of a retired answer or ``None``."""
        state=self.state();self.suspended=None;self._carry=None
        if self.convo is not None:self.convo.open_call(self.clock())
        if not state:return None
        age=self._age_of(state)
        if age is None or not 0<=age<=RECONNECT_WINDOW_S:self.call_began=self.engine.clock()
        if not state.get('pending_turn'):
            if probe('waiting_portion',state=state).value is None:return None
            if age is not None and 0<=age<=RECONNECT_WINDOW_S:
                self.reconnect_kept=True
                logger.info('echo-sync decision kind=resume reason=reconnect_kept revision=%s index=%s',state.get('revision'),state.get('chunk_index'))
                return None
        self._act('close_question','new_call')
        return self.act_left
    def act_basis(self,turn=None):
        """night-gate: the marks a later decision is checked against (the ``basis`` of ``_act``): the reply token, the plan revision and the turn in play (or ``turn``), as they stand
        now."""
        return (self.epoch,(self.state() or {}).get('revision'),self.question_id if turn is None else turn)
    def provider(self,event):
        self.note_guard_event(event)      # the one entry of the cloud's turns is also where a reply that begins after a quiet note is retired
        if isinstance(event,dict) and event.get('type')=='delegation.created':return self._delegation(event)
        if isinstance(event,dict) and str(event.get('type')).endswith('.context.appended'):
            # The helper acknowledges every frame of the context it appends (about 100 ms apart: 2.5-3.1 s for the 26 frames of a lookup
            # answer, measured): the cloud cannot answer from it before the last one, and that is the delivery the watchdog counts from.
            if self.delivery_ready:self.context_appended_at=self.clock()
            return []
        turn=self.ledger.apply(event)
        if not turn or not turn['valid']:return []
        tid=turn['id']
        if len(self.seen)>TURN_MAP_CAP or len(self.announced_at)>TURN_MAP_CAP or len(self.activity_at)>TURN_MAP_CAP:self._prune_turn_maps()
        if self.answer_witness and turn['role']=='assistant':self._witness_look(turn)
        if turn['role']=='assistant':
            if tid not in self.owners:
                user=self.ledger.latest_user()
                cut=self._continues_cut_answer(user)
                self.owners[tid]=self.question_id if cut or self._aside(user) else (user['id'] if user else None)
                if len(self.owners)>128:        # R09-1: only what the ledger still holds can be asked about
                    live={t['id'] for t in self.ledger.history()}
                    self.owners={key:value for key,value in self.owners.items() if key in live};self.blocked.intersection_update(live)
                if cut and user['id'] in self.foreign_turns:
                    # W1F-B (C5): the cloud's reply to a turn that is not the question: weighed as «not this answer» (``_source``).
                    self.foreign_replies[tid]=True
                    while len(self.foreign_replies)>64:self.foreign_replies.pop(next(iter(self.foreign_replies)))
                # G3: a plan stands and a candidate waits: whose this reply is, its words will tell (with nothing published yet it is the open question's)
                if cut and self.published and self.candidate and self.candidate['id']==user['id']:self.candidate['after_cut']=tid
            if turn['final']:
                self.turn_done_at.setdefault(tid,self.clock())
                while len(self.turn_done_at)>64:self.turn_done_at.pop(next(iter(self.turn_done_at)))
            else:
                self.activity_at[tid]=self.clock()
                while len(self.activity_at)>64:self.activity_at.pop(next(iter(self.activity_at)))
            admitted=self._candidate_reply(turn)
            return self._source(turn) if admitted is None else admitted
        if turn['role']=='user' and turn['final']:self._lang_observe(turn)      # U19-S3
        if tid not in self.user_started_at and tid not in self.seen and self.ear_piece(turn):self._ear_safely(self._ear_claim_piece,tid)
        self.user_started_at.setdefault(tid,self.clock())
        while len(self.user_started_at)>64:self.user_started_at.pop(next(iter(self.user_started_at)))
        if not turn['final']:
            if turn['text'].strip():self.cloud_heard=self.clock()     # H6 item 6: words of the cloud: what the ear hears is speech
            self._hearing_alive()   # the transcript grows: still speaking
            self.announced_at.setdefault(tid,self.clock())
            while len(self.announced_at)>64:self.announced_at.pop(next(iter(self.announced_at)))
            self._watch_partial(turn)
            taken=self._ear_safely(self._ear_bind_pending)     # R-EAR-ACT: a verdict of the local ear waited for the cloud to announce this utterance
            if taken is not None:return taken
            opened=self._ear_safely(self._ear_first_due)       # H4: so did a question it may open, and the partial may let it
            if opened is not None:return opened
        if turn['final']:
            self._tempo_safely(self._tempo_judged,turn['text'],tid)
            if tid not in self.seen and self._ear_safely(self._older_final,turn,default=False):      # c24-a1 (fuzz seed 411, g23 Р057)
                self.seen.add(tid);self.user_boundaries[tid]='older_final'
                logger.info('echo-sync decision kind=silent reason=older_final revision=%s',(self.state() or {}).get('revision'))
                return []
            if tid in self.seen and self._ear_stood_short(turn):self.seen.discard(tid)      # c23 P09: judged again, as the final it is
            if tid not in self.seen and self._ear_said_it(turn):
                self.seen.add(tid);self.user_done_at[tid]=self.clock();self.fast_passed=tid
                return self._fast_no_search(tid)
            if self.ear_first is not None:self._ear_safely(self._ear_first_passed,turn)
            again=self._ear_safely(self._ear_first_again,turn,default=False)
            continuation=None if again is not False else self._continuation(turn)
            now=self.clock();self.user_done_at[tid]=now
            if tid not in self.speech_ended:      # fix5: the final is no clock of the question (``_question_start``): the end of its speech is the ear's (the stand-in's stays), else the final's own end_ms on the input clock
                end,sent=turn.get('end_ms'),self.input_ms();ended=self._speech_end(tid,now)
                if ended is None and type(end) in (int,float) and sent is not None and end<=sent+INPUT_CLOCK_SLACK_MS:ended=now-max(0.0,sent-end)/1000.0
                if ended is not None:self.speech_ended[tid]=min(ended,now)
            while len(self.user_done_at)>64:self.user_done_at.pop(next(iter(self.user_done_at)))
            while len(self.speech_ended)>64:self.speech_ended.pop(next(iter(self.speech_ended)))
            if again is not False:return again
            if continuation and continuation[0]=='heard':
                self.seen.add(tid);self.user_boundaries[tid]='local_ear_piece';self.fast_passed=tid
                logger.info('echo-sync decision kind=silent reason=job_heard_it revision=%s',(self.state() or {}).get('revision'))
                return self._fast_no_search(tid)
            if self.unsettled:
                # The window put off for this listener restarts now; and so does a window that ran out while they were still speaking
                # but between two ticks, so that nothing put it off (Task E3c: the next segment comes 14-47 ms after their final and
                # found the end of the answer declared). A turn that ended inside the window leaves it as it is.
                cut,since=self.unsettled[0],self.unsettled[1];ended=self.turn_done_at.get(cut,since)
                final_at,expiry=self.user_done_at[tid],since+self.answer_grace_seconds
                raced=(self.user_started_at.get(tid,final_at)<expiry<=final_at
                       and final_at-ended<self.answer_grace_seconds+MERGE_PATIENCE_SECONDS)
                if since>ended or raced:
                    self.unsettled=(cut,final_at)
            if continuation and continuation[0]=='piece':return self._take_piece(turn)
            if continuation:
                _,old_id,text,restorable=continuation
                prior_segment=self.source_segment_id
                prior_prefix=self.source_segment_prefix
                prior_closed=set(self.closed_source_segments)
                prior_offsets=dict(self.segment_offsets)
                previous=self.ledger.snapshot(prior_segment) if prior_segment else None
                prior_text=(prior_prefix+previous['text'][prior_offsets.get(prior_segment,0):]).lstrip() if previous else ''
                scaffolding=bool(previous and not compact_opening(prior_text,self.question_text))
                unfinished=bool(previous and not _ENDS_SENTENCE.search(prior_text))
                from .ru_alignment import _canonical
                tail_atoms=_canonical(turn['text'],())
                protected_change=any(a in {'не','ни','+','−','%','‰','×','÷','=','<','>','≤','≥'} or a.startswith(('#','!')) for a in tail_atoms)
                old_assistants={key for key,owner in self.owners.items() if owner==old_id}
                segments=[old_id]+[piece for piece,_,_ in self._pieces()]+[tid]
                prior_fast=self.fast_turn      # H1: its job is cancelled by the join, no more text comes: it is no segment to restore
                actions=self._accept_user({**turn,'text':text},utterance=True,cause='utterance')
                if self.question_id==tid:
                    if restorable:
                        for key,owner in list(self.owners.items()):
                            if owner==old_id:self.owners[key]=tid
                    if prior_fast:self.retired_assistants.add(prior_fast)
                    if restorable and prior_fast:pass     # what the cloud said before the join stays the joined question's; the fast turn does not
                    elif restorable and (scaffolding or unfinished) and not protected_change:
                        self.source_segment_id=prior_segment
                        self.source_segment_prefix=prior_prefix
                        self.closed_source_segments=prior_closed
                        self.segment_offsets=prior_offsets
                    else:
                        # A lexical answer guessed before the continuation
                        # is not evidence of an answer to the complete question.
                        # W1F-B: nor is anything the cloud said to the unfinished question once it was answered as complete, or once it
                        # was corrected. Those segments stay the old question's: the rest of a sentence of them that opens the cloud's next
                        # segment is skipped as another question's (F1, ``_interrupted_head``).
                        self.retired_assistants.update(old_assistants)
                    actions.insert(0,{'type':'coalesced','segments':segments})
                return actions
        if not turn['final'] and tid in self.early_delegations:
            return self._delegation({'item':{'id':self.early_delegations[tid],'user_bidi_turn_id':tid,'target':'client'}})
        if turn['final'] and tid==self.question_id and self.user_boundaries.get(tid)=='provider_delegation' and question_key(turn['text'])!=question_key(self.question_text):
            # A delegation permits preparation, not treating a changing ASR
            # hypothesis as immutable. Rebind the real final to a new revision.
            self.seen.discard(tid)
            self.retired_assistants.update(t['id'] for t in self.ledger.history() if t['role']=='assistant')
            self.retired_assistants.intersection_update(t['id'] for t in self.ledger.history())
            if self.delegation_id:self.early_delegations[tid]=self.delegation_id
            if self._delegated_final_closes(turn):      # the judge says whether the question stands (Wave G: the delegation is evidence)
                self.seen.add(tid)
                return self._act('close_question','provider')[1]
        actions=self._accept_user(turn,cause='cloud_final')
        # F3 round 1: a delegation that came while the question was being said was not answered on a partial; its result goes out now that the
        # question is final (a final that changed the question was re-accepted just above, and answered there).
        if turn['final'] and tid==self.question_id:actions=actions+self._reference_at_final(tid)+(self._fast_release('model') if self.direct_content else [])+self._release_result()
        return actions+self._fast_ask()
    def _final_again(self,turn):
        """U91: the final of a question already opened by an EARLIER call of this session (a reconnect, within RECONNECT_WINDOW_S) came again, same turn id and same words: no second question, so no second answer. Remembers this one otherwise."""
        if not turn.get('final'):return False
        return self._final_held(turn['id'],' '.join(norm_words(turn['text'])))
    def _open_question(self,turn,decision,*,tail=False,whole='',utterance=False,pieces=(),local=None,job=None):
        """``turn`` is the question from now on: whatever is being answered or dictated retires, and the route of the new question is decided. The
        arguments of ``_accept_user``; ``local``: the answer of the reference base when it is known already (``_take_candidate``); ``job``: the turn of the job whose answer
        admitted it (H2): that is its job, unless the route wants another one (rule 6: the lookup; data that changes gets none)."""
        tid=turn['id']
        if self._final_again(turn):return []      # U91: one final, one answer
        self.fast_topic=self.lookup_topic
        asked=decision.question or turn['text']        # what the classifier made of the text it was given (the tail, for an early tail)
        everything=probe('strip_fillers',whole,settings=self.settings).value if tail and whole else ''
        next_question=everything or asked
        part=probe('question_part',next_question).value if self.fast_call else next_question      # H7 item 0: the route and the search read what is asked, the job all that was said
        previous_topic=self.lookup_topic or self.question_text
        lookup_question=part
        context=self._followup_of(asked) if turn.get('final',True) and not everything else None      # g31: «а пассивный» after «Что учитывает активный счёт?» is «Что учитывает пассивный счёт?» for the search and the model
        if context is None and previous_topic and self._follows_on(asked):context=complete_followup(asked,[previous_topic])      # the topic of the search has ONE owner and ONE form (``followup.TOPIC_MARK``): a bare follow-up that the history of this call cannot complete is completed on the topic in play
        if context is not None:
            if self.public_lookup_allowed(context.question,True):lookup_question=next_question+TOPIC_MARK+context.base if everything and context.kind=='topic' else context.question      # all that was said, then the topic: the same form as ``complete``
            self.lookup_topic=(context.question if context.kind=='swap' else context.base)[:300]
        else:self.lookup_topic=part[:300]
        was=self.epoch;cut=self._act('supersede','open_question',basis=(was,None,tid))[1]
        before=self.state() or {}
        # G3: the plan is kept, and ``gives_back`` when nothing answers: an objection or a correction called it wrong, it is not said again on its own.
        if probe('waiting_portion',state=before).value is not None and type(before.get('entry')) is int and not utterance:
            # H6 item 2 (N4): with the text channel an older plan has no claim over the answer in play, whoever took it up: no newer answer may have been given since (``_plan_stands``).
            older=self._suspended_entry(before)
            if older is None or before.get('chunk_index') or self.fast_call:self.suspended={'entry':before['entry'],'gives_back':decision.kind==QUESTION,'paused':bool(before.get('paused')),**self._plan_mark(before),'epoch':was,'asked_before':bool(self.asked_over and self.asked_over[0]==before.get('revision') and self.tempo_began is not None and self.asked_over[2]<self.tempo_began)}
            else:self.suspended['gives_back']=decision.kind==QUESTION     # nobody took the answer before this one up: the plan stays the older one
        # Retire an issued prefix immediately, before a new model result. Not the listener's «стоп» (that pauses): the engine's own
        # retire path records the old answer as interrupted (CL2, ruling 1), and what was left unsaid of it is noted (ruling 5a).
        if utterance:self._act('supersede','utterance_continued')
        else:self._act('supersede','new_question')
        self.said_log.append((self.clock(),next_question,False))
        # U39: the question is born by ONE act on its slot: every field of the question that is emptied on opening is emptied there (``QuestionSlot.EMPTY``), the ones this opening knows are set; its ticket is (id, version).
        self.slot.open(question_id=tid,question_text=next_question,question_part=part,question_reason=decision.reason,question_kind=decision.kind,question_clock=self.clock(),
                       question_tail=turn['text'] if everything or (decision.reason=='corrected_request' and asked!=turn['text']) else '')
        history=(self.state() or {}).get('history',())
        # The route is decided on what was asked. A tail that is only an elliptical follow-up («а почему?») still inherits the lookup of
        # the exchange before (needs_verification looks at the history for it), which the whole utterance no longer is.
        self.direct_content=(self.lookup_policy=='required' and (self.public_lookup_allowed(part) or (self.cloud_form and word_problem(part)))      # c25-b: a word problem's «у меня» is nobody's affair
                             and (bool(quick_answer(part)) or not (needs_verification(part,history) or (bool(everything) and needs_verification(asked,history)) or (self.fast_call and needs_current_data(part,history)))))     # W13 item 6: what the code works out (quick_math) is no search; H6 item 1: data that changes has no memory route (n1_04 step 10)
        self.fast_asked=(tid,job) if job and self.direct_content else None
        self.fast_played=self.fast_in_play() if self.fast_on else None
        self.fast_text=context.question if context is not None else asked if everything else self._unglued(next_question,before)
        self.delegation_id=self.early_delegations.pop(tid,None)
        self.lookup_query=lookup_question
        self.blocked.update(t['id'] for t in self.ledger.history() if t['role']=='assistant')
        if pieces:self._adopt_reply(pieces,tid)
        # The base reads the words as they were said: «а двадцать седьмая?» is a follow-up by its «а».
        read=whole if tail and whole else next_question if pieces else turn['text'];self.reference_wait=None
        local=local or ((self._reference_read(read) or (self._reference(self.fast_text) if self.fast_on and self.fast_text else None)) if turn['final'] else None)      # w3-skeptic S3: and on what H6 unglued
        if turn['final']:local=self._number_witness(local,read,tid)
        if local and turn['final'] and _number_grows(read) and not (self.tempo_live and self._utterance_over(read)):      # the ear heard the speech end: no rest is coming
            # g14: «Так, что такое счёт пятьдесят» | « два.» said «Счёт 50 — касса.»: the number can still grow, the rest may come within SPLIT_JOIN_SECONDS (``_reference_due``)
            self.reference_wait=(tid,local,self.clock()+SPLIT_JOIN_SECONDS)
            return cut+self._fast_drop()
        if local:
            # Wave G: the answer of the reference base is the answer, in this very tick; what the model does for this question is not.
            cue=self._publish_reference(local)
            if cue is not None:return cut+[{'type':'route','route':'local_reference'}]+self._fast_drop()+cue+self._release_result()
        if self.direct_content:
            # DEF-T-B15: the model asked for sources before the question was accepted: its request is served (see _delegated_lookup).
            served=self._delegated_lookup() if self.delegation_id else []
            return cut+[{'type':'route','route':'model_knowledge'}]+self._fast_release('model')+served+self._lead_cue(turn)
        private=self.fast_private and not self._split_after(tid) and not self.public_lookup_allowed(part) and not needs_verification(part,history) and not (self.fast_call and needs_current_data(part,history))      # G38 cut 3 (after G32): the gate refuses its lookup at once and ``no_search`` releases the job: the one prepared stays; c24-b: not when the cloud opened a turn after it (seed 1029: «Нет, не 40, а 50.» got the job of the question before, A7)
        dropped=[] if private else self._fast_drop()
        if not (self.public_lookup_allowed(part,True) and self.public_lookup_allowed(lookup_question,True)):return cut+dropped+self.no_search(self.epoch)      # the ONE privacy decision of a lookup (cm-route): a personal question never becomes a lookup action for the transport to refuse again
        return cut+[{'type':'lookup','epoch':self.epoch,'ticket':self.slot.ticket,'question':part,'lookup_question':lookup_question,'input_turn_id':tid}]+dropped
    def _drop_question(self,basis=None):
        """Whatever is in flight for the current question stops being anybody's answer: a later text of it is never cued (rule 6). night-gate: the row ``drop_question`` of the gate;
        returns what the transport is told (the cut), for the callers that hand it on."""
        return self._act('close_question','drop_question',basis=basis)[1]
    @classmethod
    def _answers_the_form(cls,head,question):
        """G3: has ``head`` the form ``question`` asks for: a number or a date for «когда / сколько», a cause for «почему», a purpose for «зачем», a place for «где»?"""
        return bool((_ASKS_A_NUMBER.search(question) and any(atom.startswith('#') for atom in cls._protected_atoms(head)[0]))
                    or (_ASKS_A_CAUSE.search(question) and _GIVES_A_CAUSE.search(head))
                    or (_ASKS_A_PURPOSE.search(question) and _SAYS_A_PURPOSE.match(head))
                    or (_ASKS_A_PLACE.search(question) and _SAYS_A_PLACE.match(head)))
    def v5_stale(self,cue,asked):
        """V5 slice (``v5_answer_gate=on``, v5_gate.py): the answer of ``cue`` was prepared for another question than the one open now: it is not said. The question stays
        open: what was published of it retires, and its job is asked again on the question as it stands (``asked``), on the route it had, as ``_fast_failed`` asks again.
        Nothing without the text channel (the gate passes the cue then) or when ``cue`` is no longer authorized."""
        if not self.fast_on or not self.question_id or not self.authorized(cue):return []
        logger.info('echo-sync decision kind=silent reason=v5_stale_answer revision=%s',cue.get('revision'))
        turn=self.fast_turn or self.source_id
        cut=self._act('reset_portion','v5_stale',basis=(cue.get('epoch'),cue.get('revision'),self.question_id))[1]
        if turn:self.retired_assistants.add(turn)
        if self.fast_turn:self._fast_out(self.fast_turn)
        self.published='';self.revision=None;self.source_id=None;self.refused_attempt=None;self.lead_said='';self.first_since=None;self.first_hold_from=None
        self.fast_asked=None;self.fast_done=False;self.fast_said='';self.fast_text=asked;self.question_clock=self.clock()
        return cut+self._fast_release(self.fast_route[0],**self.fast_route[1])
    def ticket_stale(self,ticket):
        """U62: is ``ticket`` (what an answer, a search or a sound carries: the question id and the slot's version it was made for) of a question that is no longer the one standing? The owner drops what it carries."""
        return self.slot.stale(ticket)
    def _nothing_confirmed(self):
        """Has the listener confirmed nothing of the answer of the current question: its first portion still waits?"""
        state=self.state()
        return bool(state and self.revision is not None and state.get('revision')==self.revision and not state.get('completed')
                    and state.get('chunk_index')==0 and not state.get('stream_waiting_next'))
    def _aside(self,user):
        """Was the latest user turn only an aside - something the listener said between the question and the first event of its
        answer («повтори», «ну», a cough, another voice), taken by the controller and NOT taken for a question? Then the question is
        where it was and the answer that begins now is the answer to it (DEF-STATE-05: it used to be dropped, for good). Not while that
        turn is still being spoken (whose it is cannot be told), not after «стоп» (no question), and not once the answer has begun
        (something of it is published: a filler that published nothing has not begun it, w3_07 on candidate 12): then a turn after the listener's
        repeat is the model's chatter (``_continues_cut_answer`` decides)."""
        return bool(user and self.question_id and user['id']!=self.question_id and user['final'] and user['id'] in self.seen
                    and not self.published)
    def _act_verdict(self,reason,basis):
        """What the gate says of this entry; read-only. 'stale': the evidence was about another reply token or another plan revision than stands now (an element of ``basis`` that is not
        stated is not compared; no basis: the evidence is this very event). 'park': the row needs a confirmed witness and has none (step 3: nothing is parked yet). Else 'do'."""
        if basis is not None:
            token,revision=basis[0],basis[1]
            if token is not None and token!=self.epoch:return 'stale'
            if revision is not None and revision!=(self.state() or {}).get('revision'):return 'stale'
        return 'do'
    def _order_cue(self,kind,cue,at,num):
        """U20-S5: an answer cue that began is played; the OrderLedger keys it by the epoch the cue was made in."""
        if kind=='began' and self.order_guard!='off' and isinstance(cue.get('epoch'),int):self.order.play(cue['epoch'])
    def _rescue_first_cue(self,qid):
        """F1 round 2: a meaning first cue of an open sentence waits for its clause end or a word past the first-cue window. A producer
        that falls silent before either, its turn still open, would leave the text that did arrive unspoken and the question given up.
        Before the watchdog gives up, the first cue is chosen from what arrived, as when the producer's turn is over (``stalled``); the
        answer itself goes on (a first segment's silence proves nothing about its end, Task 2)."""
        if self.published:return []
        mine=[tid for tid,owner in self.owners.items() if owner==qid and tid not in self.retired_assistants]
        for tid in sorted(mine,key=lambda tid:self.activity_at.get(tid,0.0),reverse=True):
            turn=self.ledger.snapshot(tid)
            if turn and turn['valid'] and turn['role']=='assistant' and not turn['final'] and str(turn['text'] or '').strip():
                logger.info('echo-sync decision kind=answer reason=first_cue_on_stall turn=%s',tid)
                return self._source(turn,stalled=True)
        return []
    def _last_sign_of_life(self,qid):
        """When the cloud last did anything for this question: an event (created, grown, finished) of an assistant turn it owns; else
        ``None``. Only the last 64 turns are remembered, which is all a question can have."""
        times=[self.activity_at.get(tid) for tid,owner in self.owners.items() if owner==qid and tid in self.activity_at]
        times+=[self.turn_done_at.get(tid) for tid,owner in self.owners.items() if owner==qid and tid in self.turn_done_at]
        return max(times,default=None)
    def _question_start(self,qid):
        """fix5 (the owner's rule: the listener's decision within 8 s of the END OF THE QUESTION'S SPEECH): the ONE anchor of every bound of the question ``qid`` (``decision_due``, ``refuse_deadline``,
        ``_watchdog_window``, the candidate's phrase): when its speech ended (``speech_ended``: the ear's end of it, else the final's own ``end_ms``; a candidate: the end of the speech it was taken on),
        never when the final came (Р001 seed 3 q15: the final 1.7 s late put the phrase 9.3 s after the speech). Only a question whose end nobody knows (no ear, no ``end_ms``) counts from when it was had."""
        ended=self.speech_ended.get(qid);candidate=self.candidate
        if ended is None and candidate and candidate['id']==qid:ended=candidate.get('spoke')
        if ended is not None:return ended
        return max(self.question_clock if self.question_clock is not None and qid==self.question_id else 0.0,self.user_done_at.get(qid) or 0.0)
    def decision_due(self,qid=None):
        """hold8: when the listener's decision on the open question (a cue, or the failure phrase) is due: the whole chain from the end of the question - the holds, the walk of the roads of its job - lives inside this one moment
        (ANSWER_WAIT_SECONDS, 8 s from its start). A job on the lookup's route (its sources, or the instruction for none) is asked after the lookup has been waited for: its 8 s count from the delivery of the sources (``_watchdog_window``), not from the question. The walk of the roads gets only what is left of it (``FastText``); None without a question."""
        qid=qid or self.question_id      # the question of the JOB: a job on a candidate (the ear's text, not yet opened) is another question than the open one
        if not self.answer_wait_seconds or not qid:return None
        start=self._watchdog_window(qid)[0] if qid==self.question_id and self.fast_route[0]!='model' else self._question_start(qid)
        candidate=self.candidate
        if candidate and candidate['id']==qid:start=max(start,candidate.get('quiet',0.0))      # the listener's speech after the candidate was handed back starts its count again (the one watchdog, ``_answer_watchdog``)
        if candidate and candidate['id']==qid and candidate.get('spoke') is not None:return start+self.answer_wait_seconds-REFUSE_BEFORE_DROP_SECONDS      # round 3: no refusal is said while a candidate is judged, so the walk of its job ends where the refusal would be due, and the phrase follows in the same tick
        return start+self.answer_wait_seconds
    def _watchdog_window(self,qid):
        """U20-S6 (pure extraction from ``_answer_watchdog``): where the silence of the cloud is counted from and how long it may last for this question: ``(start, wait)``."""
        start=self._question_start(qid)
        wait=self.answer_wait_seconds
        if (not self.direct_content or self.lookup_served) and not self.refused_lookup:
            if self.delivery_ready and self.delivered_at is not None:
                # c8: after a no-source result the model has nothing to read: the plain wait (the sourced budget is for reading sources)
                start=max(start,self.delivered_at,self.context_appended_at or 0.0);wait=wait if self.source_missing else (self.lookup_answer_wait_seconds or wait)
            else:start+=self.lookup_wait_seconds
        if self.fast_handed==qid and self.fast_handed_at is not None:      # hold8: the cloud's OWN window, a rule row (not a restart of the question's clock): the jobs of the question are over (their walk ends within its bound, ``decision_due``) and its silence is counted from the hand back on. c24 P18 (half_hour seed 11): a question asked as one («?») on the model route has a wait of HANDED_BACK_WAIT_SECONDS; talk keeps the long wait and says nothing (w8 E85)
            start=max(start,self.fast_handed_at)
            if self.direct_content and HANDED_BACK_WAIT_SECONDS<wait and str(self.question_text or '').rstrip().endswith('?'):wait=HANDED_BACK_WAIT_SECONDS
            life=self._last_sign_of_life(qid)
            if self.direct_content and (life is None or life<self.fast_handed_at):wait=max(0.0,min(wait,self._question_start(qid)+self.answer_wait_seconds-start))      # nothing from the cloud since the hand back: it has had the question's whole 8 s, the failure is not put off past them (a sign of life gives it its wait in full)
        return start,wait
    def _silence_due(self,qid):
        """The ONE count of the cloud's silence for the question ``qid`` (the watchdog and ``answer_deadline`` both read it): ``(start, since, due, cap_at)``. ``since`` is the later of the start and the last sign of life; ``due`` is when the question is given up if the cloud stays silent: its wait counted from the start or from the
        last sign of life (every one restarts the count), but never later than ``answer_cap_seconds`` after the start (``capped``, the absolute bound, is ``now>=cap_at``): ``cap_at`` is ``None`` without a cap."""
        start,wait=self._watchdog_window(qid)
        life=self._last_sign_of_life(qid);since=max(start,life) if life is not None else start
        cap_at=start+self.answer_cap_seconds if self.answer_cap_seconds else None
        due=since+wait
        return start,since,due,cap_at
    def _delegation(self,event):
        item=event.get('item')
        if self.source_delivery!='delegation' or not isinstance(item,dict) or item.get('target')!='client':return []
        did,uid=item.get('id'),item.get('user_bidi_turn_id')
        if not all(isinstance(x,str) and 0<len(x)<=200 for x in (did,uid)):return []
        if uid!=self.question_id:
            self.early_delegations[uid]=did
            while len(self.early_delegations)>4:self.early_delegations.pop(next(iter(self.early_delegations)))
            if self.candidate and self.candidate['id']==uid:return [] if 'job' in self.candidate else self._admit('delegation')     # H2: kept for the verdict
            if uid in (self.fast_passed,self.fast_declined):return self._fast_no_search(uid)
            user=self.ledger.snapshot(uid)
            if user and user['valid'] and user['role']=='user' and uid not in self.seen:
                if self._delegation_opens(user):return self._accept_user(user,boundary='provider_delegation',cause='delegation')      # the judge reads the delegation as evidence
            return []
        if self.delegation_id:return []
        self.delegation_id=did
        if self.context_requested and self.delivered_transport=='session_context' and not self.published and did not in self.answered_delegations:self.context_requested=False      # A3: the sources went out on the session's context; the model that asks for them by delegation waits for ITS tool result
        if self.direct_content:return self._delegated_lookup()
        return self._context_action()
    def _part(self):
        """H7 item 0: what every judgement of the open question by words reads: with the text channel on the part of it that asks (``classifier.question_part``), not the remark around it; with it off the question as it was."""
        return self.question_part or self.question_text
    def _resolve(self,c):
        """X-TURN: the one record of this utterance (``Resolutions``): what the judge made of it and why. It records and logs; the first decision stands."""
        if c.decision is None:return
        kind=getattr(c.decision,'kind',None)
        onset=self.user_started_at.get(c.tid,self.user_done_at.get(c.tid))      # when the user began to speak, else when they finished
        rec,outcome=self.resolutions.resolve(c.tid,resolution=kind,cause=c.cause,epoch=self.epoch,onset=onset,rule=c.rule,reason=getattr(c.decision,'reason',None),
                                             revision=(c.state or {}).get('revision'),going=c.going)
        logger.info(self.resolutions.line(rec,outcome));self._ledger_turn(c.tid)
    def _rule_bank_question(self,c):
        if (c.decision.kind==QUIET or c.decision.reason=='attempt_ru_alignment') and not (c.tail or c.utterance) and not self._said_back(c.text) and self._bank_asks(c.text,c.state):
            c.decision=Decision(QUESTION,'bank_question',probe('strip_fillers',c.text,settings=self.settings).value or c.text,None);c.spoke('bank_question')      # g1-ladder
    def _rule_asked_again_unheard(self,c):
        if c.decision.kind==QUESTION and not (c.tail or c.utterance) and self._asked_again_unheard(c.turn,c.text,c.state):
            logger.info('echo-sync decision kind=silent reason=asked_again_before_its_answer revision=%s',(c.state or {}).get('revision'))
            self._ruled(c,QUIET,'asked_again_before_its_answer',None,'asked_again_unheard')
    def _rule_joined_question(self,c):
        if (c.decision.kind==QUIET or c.decision.reason=='topic_while_waiting') and not c.tail and not c.utterance:
            # W1F-B (C2, sc01): the pieces of a question cut into short finals, each nothing alone, are judged joined. c7-meta round 2: a
            # topic phrase that would name a new question while a portion waits is first tried as the tail of such a cut question.
            found=self._joined_question(c.tid,c.text,c.state)
            if found:
                c.text,c.decision,c.pieces=found;c.spoke('joined_question')
                logger.info('echo-sync decision kind=%s reason=joined_question pieces=%s revision=%s',c.decision.kind,len(c.pieces)+1,
                            (c.state or {}).get('revision'))
    def _rule_request_goes_on(self,c):
        if c.decision.kind in (QUESTION,RESUME,NEXT) and not c.tail and not c.utterance:
            # W1F-B (TR-FRAG, w1_08 step 4): a fragment of a request just served locally goes on with that request.
            request=self._request_goes_on(c.tid,c.text,c.state)
            if request:
                c.text,c.decision=request;c.turn={**c.turn,'text':c.text};c.spoke('request_goes_on')
                logger.info('echo-sync decision kind=%s reason=request_goes_on revision=%s',c.decision.kind,(c.state or {}).get('revision'))
    def _number_witness(self,local,text,tid):
        """Fable 10.11 (20:54, U36: the ear heard 122, the cloud 322, the base said the article 322 as if sure; the owner had said 422). The base's answer hangs on the number, and the two witnesses of this
        utterance name different ones. Once (``NUMBER_TRUSTS``) that is the ear mishearing, a sixth of the numbered finals of the calls: the cloud's answer goes, as ever. They differ AGAIN within
        ``UNANSWERED_SECONDS``, on these numbers or others (the speaker said the number again: the first answer was not his): the doubt is not settled by one witness: one exact question (the two numbers
        and «say it again»: neither may be right), and past it the answer says which number it stands on (``NUMBER_PREMISE``). The same number from both ends the doubt. One witness: ``local``."""
        if not local or local==SOURCES_DIFFER:return local
        heard=self._ear_safely(self._ear_words,text,self._ear_floor(tid),self._split_after(tid),default='')
        numbers=lambda said:frozenset(atom[1:] for atom in self._protected_atoms(said)[0] if atom.startswith('#'))
        cloud,ear=numbers(text),numbers(heard or '')
        if not (cloud-ear and ear-cloud):
            if cloud and ear:self.number_asked=None      # both witnesses, one number: the doubt is over
            return local
        now=self.clock();asked=self.number_asked[0] if self.number_asked and now-self.number_asked[1]<=UNANSWERED_SECONDS else 0
        self.number_asked=(asked+1,now)
        if local==quick_answer(text):local=quick_stated(text) or local      # U43 (a): a figure over two witnesses names its operands: a wrong one is heard
        lang='en' if sum(char.isascii() and char.isalpha() for char in text)*2>sum(char.isalpha() for char in text) else 'ru'
        logger.info('echo-sync decision kind=%s reason=two_witnesses_two_numbers differed=%s revision=%s','trust' if asked<NUMBER_TRUSTS else 'clarify' if asked==NUMBER_TRUSTS else 'premise',asked,(self.state() or {}).get('revision'))
        if asked<NUMBER_TRUSTS:return local
        if asked>NUMBER_TRUSTS:return NUMBER_PREMISE[lang].format(*sorted(cloud-ear)[:1],local)
        return NUMBER_DOUBT[lang].format(*sorted(ear-cloud)[:1],*sorted(cloud-ear)[:1])
    def _reference_due(self,now):
        """g14: the base's answer held for the rest of a number (``reference_wait``) goes once SPLIT_JOIN_SECONDS have passed with no continuation; a new question has taken its place otherwise."""
        wait=self.reference_wait
        if wait is None or now<wait[2]:return []
        self.reference_wait=None
        if wait[0]!=self.question_id or self.published or self.local_answer:return []
        cue=self._publish_reference(wait[1])
        return [{'type':'route','route':'local_reference'}]+cue+self._release_result() if cue is not None else []
    def _reference_at_final(self,tid):
        """A question taken on a partial (the model's delegation came first): the base had to wait for the final of the question."""
        if self.user_boundaries.get(tid)!='provider_delegation' or self.local_answer or self.published:return []
        said=self.ledger.snapshot(tid)['text']
        hit=self._reference_read(said)
        return (self._publish_reference(hit) or []) if hit else []
    def _take_back(self,turn,state,boundary,resume=False):
        """Rule 5: the plan an admission took over comes back at once when the listener's next words are said to it, and the intruder is dropped. Its history
        entry (``suspended``) still holds it: the engine restores it from the first unconfirmed portion, and the final is judged on it. ``resume``: «продолжай»
        while nobody has taken the new answer up. The final that confirms the answer that is current keeps it. None: the plan does not come back."""
        if self._suspended_entry(state) is None:
            self.suspended=None;return None
        if resume:
            if state.get('chunk_index'):return None
        elif (self.fast_call and self.suspended.get('paused')) or not self._said_to_the_plan(turn['text'],state):return None     # H6 item 2 (R4): a stopped plan stays stopped: a try is no resume, the engine says so too
        index=self.suspended['entry'];self.suspended=None
        reply=self.engine.resume_entry(self.session_id,index,explicit=resume)
        if reply is None:return None
        cut=self._drop_question()
        if not resume:self.note_due=None        # the note that the plan was left: it was not (a return said in words hands on what it always handed on)
        logger.info('echo-sync decision kind=resume reason=suspended_plan_taken_back revision=%s',(self.state() or {}).get('revision'))
        if resume:self.first_since=None;self.first_hold_from=None;return cut+self._cue_unless_spoken_over(reply,first=True)      # c24-a1 (P13, fuzz seed 1): said again from its first unconfirmed portion, it waits for the speech going on as a first cue does; c24-a2 (P07): with the owner already speaking it waits for the silence
        self.seen.discard(turn['id'])
        return cut+self._accept_user(turn,boundary=boundary,cause='resume')
    def _suspended_entry(self,state):
        """The history entry of the suspended plan while it can still be taken up (something unsaid, its portions kept), else None."""
        index=self.suspended['entry'] if self.suspended else None
        history=(state or {}).get('history') or []
        entry=history[index] if type(index) is int and 0<=index<len(history) else None
        if not isinstance(entry,dict) or entry.get('status')!='interrupted' or not isinstance(entry.get('chunks'),list):return None
        spoken=entry.get('spoken')
        return entry if type(spoken) is int and 0<=spoken<len(entry['chunks']) else None
    def _declined(self,qid):
        """Did the cloud answer this question with no more than a backchannel («Угу», «Хорошо, рад помочь!») or the older answer told again? Then it took the
        turn for nothing to answer. H2: the verdict is the job's; the cloud's word counts only for a question handed back to it (or with no channel)."""
        if qid and self.fast_declined==qid:return True
        if self.fast_on and self.fast_handed!=qid:return False
        return self.plan_told==qid or any(self.owners.get(t['id'])==qid and t['role']=='assistant' and t['final'] and self._backchannel(t['text'])
                                          for t in self.ledger.history())
    def _retells_the_plan(self,turn):
        """Rule 4: the reply to a question is the plan that question took over, or the answer before it, told again: its words are that answer's, in that order,
        and it says nothing of the question's that the answer does not (an answer that explains the same thing in other words is an answer). ``None`` while its
        first sentence is not over and it may still be."""
        if self.published:return False
        state=self.state() or {}
        entry=self._suspended_entry(state) or next((e for e in reversed(state.get('history') or ()) if isinstance(e,dict) and e.get('answer')),None)
        if entry is None:return False
        text=turn['text'];said=[item[0] for item in _content(text)];own=[item[0] for item in _content(str(entry.get('answer') or ''))]
        asked=_stems(self.question_tail or self.question_text)
        if len(said)<2 or len(own)<2 or (asked&set(said))-set(own) or asked&_stems(str(entry.get('question') or '')):return False   # the same subject may be told again
        told=sum(block.size for block in SequenceMatcher(None,own,said,autojunk=False).get_matching_blocks() if block.size>=2)
        if not (turn['final'] or _ENDS_SENTENCE.search(text)):return None if told==len(said) else False
        return told>=min(RETOLD_WORDS,len(own)) and told*10>=len(said)*7
    def _plan_after_decline(self,now):
        """The cloud answered the question that took a plan over with a backchannel and nothing followed in the grace window: the plan goes on. A question on
        the lookup route stays: its sources may still bring the answer (the watchdog then). H2: the job's verdict is whole at once, on any route: the question is dropped, the
        plan that gave way to it goes on, and a final that waited for the job stays."""
        qid=self.question_id
        if qid and self._overtaken('plan',now=now):return []      # c24 P16 (ladder L4 seed 1 @105.24): the ear has heard a newer question whose final is still to come: the old plan does not cut in as its answer
        if qid and qid==self.fast_declined:
            if self.hearing or self.ear_first is not None or (self.tempo_live and (self.tempo_awaits is not None or self._tempo_unheard(now) or (self.candidate and 'job' in self.candidate) or (self.tempo_ended is not None and now<self.tempo_ended+TEMPO_FILLER_SECONDS))):return []      # the speech that has just ended may be what comes next (241.45-241.7 of the call); H5 item 1: it is a replay too
            waiting=self.candidate
            cut=self._drop_question();self.candidate=waiting
            return self._resume_after_nothing(cut) or []
        if not qid or self.published or not (self.suspended or {}).get('gives_back') or not self.direct_content or self.hearing or not self._declined(qid):return []
        if self.fast_handed==qid:return []      # w10 R10.2 (rehearsal Р051): the job FAILED and the cloud has only a backchannel: no verdict of talk; the watchdog says so, the older plan stays in the history
        last=self._last_sign_of_life(qid)
        if last is None or now-last<self.answer_grace_seconds:return []
        return self._resume_after_nothing(self._drop_question()) or []
    def _overtaken(self,where,turn=None,*,now=None,state=None):
        """G23 / c24 P16 / c25-a G1 (cm-overtaken, the ONE place): is what is about to be taken or said the OLDER question's, after a NEWER question? ``where`` says which door asks:
        'final' (``_admit``: a job's answer on an older turn admitted late; ``turn`` is it): the ear heard a question begin after it, or two whole questions, the second begun after the first ended, or a newer question of the cloud was taken (Р063; not at the final itself, ``_accept_user``: dropping a final lost answers);
        'plan' (``_plan_after_decline``, ``now``): the ear heard a question after the question in play, within EAR_ASK_HOLD_SECONDS, whose final is still to come: the old plan does not cut in as its answer;
        'answer' (``_source``): the answer of the question in play is about to sound first and the ear heard another question begin after that question's speech ended;
        'repeat' (``_accept_user``, ``state``): the ear heard a new question begin after a cue of the plan that waits, so «ещё раз» asks for ITS answer. Every fact it reads is told by ``_ear_heard`` (ear_newest, ear_asked, ear_asked_input, asked_over)."""
        if where=='plan':
            return self.ear_asked is not None and self.question_clock is not None and self.ear_asked>self.question_clock and now-self.ear_asked<EAR_ASK_HOLD_SECONDS
        if where=='repeat':
            return bool(self.tempo_live and self.asked_over and (state or {}).get('revision') is not None and self.asked_over[0]==(state or {}).get('revision'))
        if where=='answer':
            heard=self.ear_asked_input;turn=self.ledger.snapshot(self.question_id) if self.question_id else None
            if not heard or not turn or type(turn.get('end_ms')) not in (int,float):return False
            if heard[0]<=turn['end_ms']:return False
            latest=self.ledger.latest_user()      # h4: the ear's piece of the question's own breath may start after a turn the cloud cut: a newer turn of the cloud must be there too
            if not latest or latest.get('id')==self.question_id or type(latest.get('start_ms')) not in (int,float) or latest['start_ms']<turn['end_ms']:return False
            try:return not same_question(heard[1],turn.get('text') or '')
            except Exception:return False      # noqa: BLE001 - not sure: as before
        heard=getattr(self,'ear_newest',None)
        if not turn.get('final'):return False
        began=turn.get('start_ms',-1);state=self.state()
        if type(began) not in (int,float) or began<0:return False      # c24-a1 (fuzz seed 117): a turn the ear made (it stood in for a lost final) has no start of speech: every turn would be «newer»
        by_ear=bool(heard) and heard[1]>began and not same_start(heard[0],turn['text'],open_end=True)
        for other in self.ledger.history():
            if other['role']!='user' or other['id']==turn['id'] or not other['valid']:continue
            if other.get('start_ms',-1)<=began or len(self._said_words(other['text']))<2:continue
            taken=other['id'] in self.seen
            if not (by_ear and not taken):
                if not (len(self._said_words(other['text']))>=3 and turn.get('end_ms',1e18)<=other.get('start_ms',-1)
                        and self._classify(other['text'],state).kind==QUESTION and self._classify(turn['text'],state).kind==QUESTION):continue
            logger.info('echo-sync decision kind=silent reason=older_final_after_newer_question revision=%s',(state or {}).get('revision'))
            self.seen.add(turn['id']);return True
        return False
    def _same_as_asked(self,text):
        """c25-a: the question in play read again (c24-c ``_read_again``: the portion again) is no newer question."""
        try:return bool(self.question_text) and same_question(text,self.question_text)
        except Exception:return True      # noqa: BLE001 - not sure: no newer question
    def _resume_after_nothing(self,cut):
        """Nobody answered the question that took the plan over: the plan goes on. Actions, or None when there is no plan to go back to. ``cut``: what the drop of that question told the transport (``_drop_question``)."""
        state=self.state() or {}
        entry=self._suspended_entry(state)
        if entry is None or not self.suspended.get('gives_back') or not self._plan_stands(state):return None
        if self.suspended.get('asked_before'):      # c25-a G1 plan_goes_on_after_no_answer (Р086 seed 101 @112.9): a question heard after this plan's cue, before the one that took it over, is still unanswered: the plan going on would be an old answer to it
            logger.info('echo-sync decision kind=silent reason=plan_stays_after_a_newer_question revision=%s',state.get('revision'));return None
        index=self.suspended['entry'];stopped=self.suspended.get('paused');self.suspended=None
        reply=self.engine.resume_entry(self.session_id,index)
        if reply is None:return None
        self.note_due=None
        if stopped:                 # H5 item 3: it comes back as it was: nothing is said until the listener resumes
            self._reply('стоп',f'{self.nonce}:stopped:{self.epoch}',decided=command_ruling(STOP))
            return []
        logger.info('echo-sync decision kind=resume reason=plan_goes_on_after_no_answer revision=%s',(self.state() or {}).get('revision'))
        return cut+self._cue(reply)
    def _plan_stands(self,state):
        """H6 item 2, the one rule (N4, R3): may the plan a question took over go on by itself? No newer answer was given since, it was cued less than PLAN_BACK_SECONDS ago, the listener was at it. With the channel off G3 stands as it was."""
        plan=self.suspended
        if not self.fast_call:return plan.get('age') is None or plan['age']<PLAN_BACK_SECONDS       # R08-1: the age limit of H6 item 2 holds with the channel off too
        newer=any(isinstance(entry,dict) and entry.get('answer') for entry in (state.get('history') or [])[plan['entry']+1:])
        fresh=plan.get('cued') is None or self.clock()-plan['cued']<PLAN_BACK_SECONDS
        if not newer and fresh and plan.get('at_it'):return True
        logger.info('echo-sync decision kind=silent reason=plan_stays_in_the_history newer=%s fresh=%s at_it=%s revision=%s',newer,fresh,plan.get('at_it'),state.get('revision'))
        return False
    # ---- H6 item 10: the prepared speech (``prepared_speech`` = "on"; see SPEECH_STARTS) -----------------------------------------------------------------------------
    def prepare_speech(self,text):
        """The host: the material of this call is the speech it prompts."""
        text=' '.join(str(text or '').split())
        self.speech={'text':text,'entry':None} if text else None
    def _speech_resumes(self):
        """The answer to a question asked in the middle of the speech is over: the speech goes on where it stopped. It is the plan of this call: no rule of a plan given back holds it (``_plan_stands``)."""
        speech=self.speech;state=self.state() or {}
        if not speech or speech['entry'] is None or not state.get('completed') or state.get('entry')==speech['entry']:return []
        reply=self.engine.resume_entry(self.session_id,speech['entry'])
        if reply is None:return []
        cut=self._drop_question();self.suspended=None;self.note_due=None
        speech['entry']=(self.state() or {}).get('entry')
        logger.info('echo-sync decision kind=resume reason=prepared_speech_goes_on revision=%s',(self.state() or {}).get('revision'))
        return cut+self._cue(reply)
    @staticmethod
    def _cloud_tail(asked,said):
        """c25-b case 1: ``said`` of the cloud from where the ear's tail question begins (its first two words, the last place they stand), else ``said`` as it is."""
        head=norm_words(asked)[:2];words=str(said).split()
        for at in range(len(words)-len(head),-1,-1):
            if norm_words(' '.join(words[at:at+len(head)]))==head:return ' '.join(words[at:])
        return said
    def _lookup_routed(self,asked):
        """c22-speed (``ear_lookup``) and Q1 / B9 (``prefetch_candidate``): would the route take this question to the public search: the search is always taken or required and the question may reach it (``public_lookup_allowed(search=True)``: no word of the listener's own affairs),
        and it needs a source."""
        history=(self.state() or {}).get('history',())
        return self.public_lookup_allowed(asked,True) and not quick_answer(asked) and (self.lookup_policy!='required' or needs_verification(asked,history) or (self.fast_call and needs_current_data(asked,history)))
    def _ear_reads(self,first,said):
        """c16: does ``said`` of the cloud read as what the ear opened: the rule that adopts a job (``wide_refusal``: the parts that ask, every number, «не» and role, a preface around them no conflict)?"""
        if first.get('tail'):said=self._cloud_tail(first['asked'],said)      # c25-b case 1: the preface of the breath is not the question's («одну книжку» is no number of it)
        rule=wide_refusal(first['asked'] or first['text'],said,strip=lambda text:probe('strip_fillers',text,settings=self.settings).value,whole=True)
        if rule and first.get('rule')!=rule:
            first['rule']=rule
            logger.info('echo-sync ear first=unread rule=%s uid=%s',rule,first['run'][-1]['uid'])
        return rule is None
    def fast_questions(self):
        """The finals a job may run for: what a cancel leaves alone."""
        return [self.question_id]+([self.candidate['id']] if self.candidate else [])
    def _keep_unanswered(self,text):
        """ROOT-2: a declined utterance of substance stays the next job's context until an answer is given or ``UNANSWERED_SECONDS`` pass (``fast_exchanges``)."""
        text=' '.join(str(text or '').split())
        if len(norm_words(text))<UNANSWERED_MIN_WORDS or any(row[0]==text for row in self.unanswered):return
        answered=len([row for row in self.fast_exchanges() if not row.get('unanswered')])       # the same count ``fast_exchanges`` drops the row by
        self.unanswered=(self.unanswered+[(text,answered,self.engine.clock())])[-UNANSWERED_KEPT:]
    def _fast_release(self,route,**extra):
        """The open question (``route``: 'model' - the model-knowledge route; 'sources' - the lookup gave them, ``extra['sources']``; 'unsourced' - the lookup gave none and the
        question is a stable reference) asks the channel for its text: ONE ``fast`` action per question. The channel adopts the job the ear prepared when it is this question's,
        else starts one. The route 'model' gets none for a question the cloud answers because its job failed. A question taken on a partial
        (the model's delegation) waits for its final (rule 2): half a question is not judged. The channel has one job: a candidate's goes, and it is asked again after this one."""
        if not self.fast_on or self.fast_asked is not None or not self.question_id or self.local_answer:return []
        if self.user_boundaries.get(self.question_id)=='provider_delegation' and not self._question_final():return []
        if route=='model' and self.fast_handed==self.question_id:return []
        if self.candidate and self.candidate.get('job'):
            for key in ('over','verdict'):self.candidate.pop(key,None)
            self.candidate.update(job=None,said='')
        asked=self.fast_text or self.question_text
        if self._fast_tail_waits(asked,route,extra):return []
        self.fast_n+=1;turn=f'{FAST_TURN}{self.fast_n}';self.fast_asked=(self.question_id,turn);self.fast_route=(route,extra)
        return [{'type':'fast','op':'release','epoch':self.epoch,'qid':self.question_id,'turn':turn,'question':asked,'route':route,**self._fast_also(asked,self.question_id),**extra}]
    def _fast_also(self,asked,tid=None):
        """H6 item 3: the ear's words of ``asked`` for the job, when they differ from the cloud's."""
        heard=self._ear_safely(self._ear_words,asked,self._ear_floor(tid) if tid else None,self._split_after(tid),default='')
        return {'also':heard} if heard else {}
    def _split_after(self,tid):
        """c23 (c22-break P04, fuzz seed 6): has the cloud opened a user turn after ``tid``? Then it heard the speech after it as another utterance: the ear's next breath is that one's, not a hole of this final."""
        if not tid:return False
        users=[turn['id'] for turn in self.ledger.history() if turn['role']=='user']
        return tid in users and users.index(tid)<len(users)-1
    def _fast_ask(self):
        """Rule 2: the final with no form goes to the job once what that final does is done. A job at a time: an answer is not cut for it, it waits for the job of the question."""
        candidate=self.candidate
        if not self.fast_on or not candidate or 'job' not in candidate or candidate['job'] or self._fast_running():return []
        asked=candidate.get('ask') or candidate['text']
        if self._said_back(asked):
            self.candidate=None;self.fast_passed=candidate['id']
            logger.info('echo-sync decision kind=silent reason=said_back revision=%s',(self.state() or {}).get('revision'))
            self._tempo_declined()
            return self._fast_no_search(candidate['id'])
        if self._tail_open(asked) and self.clock()<candidate.setdefault('until',self.clock()+FAST_TAIL_SECONDS):return []     # H6 item 3, ``tick``
        self.fast_n+=1;candidate['job']=f'{FAST_TURN}{self.fast_n}'
        return [{'type':'fast','op':'release','epoch':self.epoch,'qid':candidate['id'],'turn':candidate['job'],'question':asked,'route':'candidate',**self._fast_also(asked,candidate['id'])}]
    def _fallback_refused(self,tid,why,text='',final=True):
        """H5 item 7, H6 item 1: the ONE rule of the cloud standing in for the brain (a question whose jobs failed, or a call that has lost the channel): its text is refused, ``why`` 'number': it has a number the question does not have
        (``says_a_number``: the wrong year of the fuzz, one failure away) and no source backs it, 'short': no whole answer (nothing in it but a word of yes or no to a question that asks for something else: n1_04 step 10: «Да.» to «в каком году»),
        'talk': nothing but talk about itself. An honest failure beats a wrong word. What was said stands and the answer ends there; with nothing said the question is given up and the failure is said, as the watchdog says it: «Не нашёл» where
        the lookup found nothing. The plan stays where the listener's words can take it back. ``None``: the cloud does not stand in, or the text stands; ``[]``: refused only once its turn is over (``final``), not yet."""
        if not (self.fast_call and tid!=self.fast_turn and (self.fast_handed==self.question_id or not self.fast_on)):return None
        if why=='number' and not (self.direct_content and not self.sources and says_a_number(text,self._part())):return None
        if why=='short' and not (asks_for_more(self.question_tail or self._part()) and not any(word not in STOPWORDS and word not in _NO_SUBSTANCE and word not in _MAY_ANSWER for word in norm_words(text))):return None
        if why!='number' and not final:return []
        self.retired_assistants.add(tid)
        logger.info('echo-sync decision kind=silent reason=fallback_%s_refused revision=%s',why,(self.state() or {}).get('revision'))
        if self.published:return self._fast_closed()
        epoch=self.epoch;missing=self.source_missing
        self._drop_question()
        return self._give_up_aloud(f'fallback_{why}_refused',epoch=epoch,missing=missing)
    def _fast_told(self,uid):
        """The open question ``uid`` turned out to be none: the model's delegation on it goes the way of a final's (``_fast_no_search``), or it waits for a result that never comes (DEF-T-B15)."""
        if self.delegation_id:self.early_delegations[uid]=self.delegation_id
