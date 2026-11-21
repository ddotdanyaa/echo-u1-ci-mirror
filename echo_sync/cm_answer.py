"""The answer methods of ``ControlledMedia`` (cut from controlled_media.py by tools/split_controlled_media.py). Imports from cm_base, never from controlled_media."""
from .gate_text import public_address_allowed

from .cm_base import (CORRECTION, probe, state_age, EAR_PILE_SECONDS, FAST_TAIL_SECONDS, FIGURE_HEAD_SECONDS, MAX_RESTARTS, MERGE_PATIENCE_SECONDS, PLAYED_FRESH_S,
    PREPARE_MIN_WORDS, REFUSE_BEFORE_DROP_SECONDS, RESTART_ANCHOR_GAP, RESTART_DECIDE_WORDS, RESTART_MAX_WORDS, STOPWORDS,
    StreamingAnswer, WITNESS_SLACK_SECONDS, WORDS, _AFTER_ANCHOR, _ASKS_A_CAUSE, _CYRILLIC, _ENDS_SENTENCE,
    _GIVES_A_CAUSE, _HEAD_TERMINATOR, _LEADING_MARKS, _MAY_ANSWER, _NO_SUBSTANCE, 
    _REQUEST_STEMS, _UNNAMED_SUBJECT, _chatter, _complete, _content, _ends_in_number, _last_sentence_words,
    _retelling, _source_conflict, _stems, _valued, answer_conditions, asks_for_more, brain_answer, first_cue, honest_reply, lead,
    lead_row, lead_splice, logger, CHANGES, route_need, norm_words, normalize, personal_volatile, privacy_gate, public_sources,
    quick_answer, quick_asked, re, revises, REFUSAL, search_identity, threading, uuid, witness_rule)

from .diagnostics import reason_of


class AnswerMixin:
    @staticmethod
    def _impersonal(question):
        """The question without its first-person frame, when what remains is a public question (``privacy_gate.impersonal``), ``''`` otherwise."""
        return privacy_gate.impersonal(question,_content)
    def _continues_cut_answer(self,user):
        """Is a new assistant turn the rest of the answer being dictated, rather than an answer to the user turn before it?

        Yes when that user turn is only something the listener said in between (a repeated portion, «угу»: processed, and not
        the question) and the last segment of this answer stopped mid-sentence with nothing declaring it the end. The field
        logs show the model going on 27-47 ms after such a turn, even in the middle of a word. A reply to a repeat after a
        FINISHED sentence stays muted, and so does anything after «стоп» or after the end of the answer was declared.
        Whether that segment is joined to the cut sentence is decided in ``_source`` on what it says, though: the model may also start
        its answer again or answer something else (the owner's call of 2 Nov; Task E3c, amendment R2a: ``_weigh_segment``).
        """
        sid=self.source_segment_id
        if not user or not sid or not self.question_id or user['id']==self.question_id or user['id'] not in self.seen:return False
        if sid==self.settled_segment:return False
        last=self.ledger.snapshot(sid)
        return bool(last and last['valid'] and last['final'] and last['role']=='assistant' and not _ENDS_SENTENCE.search(last['text']))
    def _adopt_reply(self,pieces,tid):
        """sc01: the cloud heard the question whole and began its answer after the first piece (« Объясни» -> « Конденсация — это когда газ
        охлаждается и его молекулы», cut by the rest of the question), and its next segment goes on with that sentence. So the last reply
        to a piece, when it was cut mid-sentence and asks nothing back, is where the answer to the joined question begins: the cloud's
        next segment is weighed against it as usual (joined, or taking its place: ``_restart_verdict``), and when none comes it is the
        answer as it stands (the grace window, ``_settle``)."""
        replies=[t for t in self.ledger.history() if t['role']=='assistant' and self.owners.get(t['id']) in pieces
                 and t['id'] not in self.retired_assistants]
        if not replies:return
        last=replies[-1]
        if not last['valid'] or not last['final'] or _ENDS_SENTENCE.search(last['text']) or '?' in last['text'] or not _content(last['text']):
            return
        self.owners[last['id']]=tid;self.source_segment_id=last['id'];self.answer_head=(tid,last['id'])
        self._end_open(last['id'],self.clock())
        logger.info('echo-sync decision kind=answer reason=reply_to_the_first_piece_kept revision=%s',(self.state() or {}).get('revision'))
    def _bind_answer(self,answer,tid):
        """B: the ONE writer of ``_answer``. The answer is bound to the turn that publishes it (``tid``), the epoch and the revision of the plan it replaces; None unbinds. It lives for one call of the engine
        (``_reply``), so an answer is never the answer of another question: what is left unbound or bound to another turn is refused by ``_generate`` (no number of seconds is kept)."""
        if answer is not None:answer_conditions.report(self.question_text,answer,self.witness_note)      # U80: the broken condition of the question is a line of the trace; the answer is released as it stands
        self._answer=None if answer is None else (answer,tid,self.epoch,(self.state() or {}).get('revision',0))
    @staticmethod
    def public_lookup_allowed(question,search=False):
        """The ONE privacy gate of the road (cm-route): ``privacy_gate.allowed``. ``search=True`` (E88): may it reach the PUBLIC search."""
        return privacy_gate.allowed(question,search) and (not search or public_address_allowed(question))
    def _reply(self,text,tid,*,decided,going=None,basis=None,answer=None):
        """The one entrance to the engine (B): it carries out ``decided`` (the verdict of the owner of the kind: the judge, ``command_ruling`` for a command the controller gives as text, ``_asked_ruling`` for a publication)
        with the plan ``going`` of going on and the ``basis`` (revision, index) the verdict was made on. ``answer``: what the engine is to publish for this turn (``_bind_answer``): it lives this one call."""
        if answer is not None:self._bind_answer(answer,tid)
        try:
            return self.engine.reply(session_id=self.session_id,turn_id=tid,text=text,request={},model='GPT-Live-subscription-controlled',decided=decided,going=going,basis=basis)
        finally:
            self._bind_answer(None,None)
    @staticmethod
    def _basis(state):
        """B: the state a verdict was made on, as the engine checks it: (revision, index)."""
        return (state['revision'],state.get('chunk_index')) if state else None
    def _release_held(self,now):
        """Speak an answer that was held for a possible continuation once none can come, even if nothing else
        arrives (a short answer can be over long before the window is). A segment the grace window has declared the end of the answer
        while it was held is released as that end."""
        tid=self.held_source
        if tid is None or self._holding(now):return []
        self.held_source=None
        turn=self.ledger.snapshot(tid)
        if not turn or not turn['valid'] or turn['role']!='assistant':return []
        return self._source(turn,settled=tid==self.settled_segment)
    def _settle(self,now):
        """The producer's turn is over but its text has no terminal punctuation, so it may have been cut and a continuation
        segment may follow. Give one the grace window; when none came, that text is the end of the answer: the rest of it is
        portioned and dictated (a user waiting at the end of the published part hears the next portion now), and a lone word
        is spoken at last. Silence from a turn that never finished proves nothing and is not settled. While the listener is
        speaking a segment can follow even that turn (the field logs), so the window counts from the end of their turn
        (bounded, so that a turn the provider never closes cannot hold the end of an answer for ever). And it is declared only once the
        listener has run out of the text published so far (``_listener_waits``), checked again with every tick."""
        waiting=self._end_window()
        if waiting is None or not self._end_over(waiting[1],now):return []
        tid=waiting[0]
        user=self.ledger.latest_user()
        if (user and user['valid'] and not user['final'] and user['id']!=self.question_id
                and now-self.turn_done_at.get(tid,waiting[1])<self.answer_grace_seconds+MERGE_PATIENCE_SECONDS):
            self._end_open(tid,now);return []
        if not self._listener_waits():return []
        self.unsettled=None
        turn=self.ledger.snapshot(tid)
        # A newer segment or a newer question has taken over since: not this turn's business any more.
        if tid!=self.source_segment_id or not turn or not turn['valid'] or turn['role']!='assistant' or not turn['final']:return []
        return self._end_declared(turn,'end_grace_elapsed')
    # cm-end-of-answer (the ONE place of the time that ends an answer): the grace window of a text without a mark (``unsettled``, written
    # only by ``_end_open``, read only by ``_end_window``), its expiry (``_end_over``) and the quiet of a segment that stopped arriving
    # (``_idle_over``) are decided here; ``_settle``, ``_flush_idle``, ``_flush_restart``, ``_candidate_settled`` and the starving of a
    # listener are its readers, ``tick`` its clock.
    def _end_open(self,tid,since):
        """Arm (or put off) the end of the answer of the turn ``tid``: its window counts from ``since``."""
        self.unsettled=(tid,since)
    def _end_declared(self,turn,reason=''):
        """The ONE declaration that the text of ``turn`` is the end of the answer (grace elapsed, idle segment, stalled stream, the job's close): the window is spent, the rest is portioned by ``_source``."""
        self.settled_segment=turn['id'];self.unsettled=None
        if reason:logger.info('echo-sync decision kind=answer reason=%s revision=%s',reason,(self.state() or {}).get('revision'))
        return self._source(turn,settled=True)
    def _end_over(self,since,now):
        """Has the grace window that counted from ``since`` run out at ``now``?"""
        return now-since>=self.answer_grace_seconds
    def _idle_over(self,last,now):
        """Has a segment whose last event was at ``last`` been quiet for ``segment_idle_seconds`` at ``now``?"""
        return now-last>=self.segment_idle_seconds
    def _end_window(self):
        """``(turn, since)`` of the open window, or None. The window put off for a listener restarts at the final of their speech that closed after
        it was armed (and so does a window that ran out while they were still speaking but between two ticks, so that nothing put it off: Task E3c,
        the next segment comes 14-47 ms after their final and found the end of the answer declared); a turn that ended inside the window leaves it
        as it is. It was done once by ``_accept_user`` at the final; as a reading of the ledger here it is the same at every tick and is kept once."""
        waiting=self.unsettled
        if waiting is None:return None
        user=self.ledger.latest_user();final_at=self.user_done_at.get(user['id']) if user and user['valid'] and user['final'] else None
        if final_at is None or final_at<=waiting[1]:return waiting
        cut,since=waiting;ended=self.turn_done_at.get(cut,since);expiry=since+self.answer_grace_seconds
        raced=(self.user_started_at.get(user['id'],final_at)<expiry<=final_at and final_at-ended<self.answer_grace_seconds+MERGE_PATIENCE_SECONDS)
        if since>ended or raced:self._end_open(cut,final_at)
        return self.unsettled
    def answer_diagnosed(self,epoch):
        """The transport has told the listener why this question has no answer (its lookup failed, or it is a personal question the
        public lookup refuses): the watchdog has nothing to add for it. The epoch of a question that has been replaced since is ignored."""
        if epoch==self.epoch:self.diagnosed_epoch=epoch
    def answer_deadline(self):
        """U20-S6: the moment ``_answer_watchdog`` will drop the question if the cloud stays silent (the count restarts with every sign of life; ``answer_cap_seconds`` bounds it); ``None`` when the watchdog has nothing to do."""
        qid=self.question_id
        if not self.answer_wait_seconds or not qid or self.fast_mark or self.published or self.diagnosed_epoch==self.epoch:return None
        question=self.ledger.snapshot(qid)
        if not question or not question['valid'] or not question['final']:return None
        deadline,cap_at=self._silence_due(qid)[2:]
        return deadline if cap_at is None else min(deadline,cap_at)
    def refuse_deadline(self,qid=None):
        """U20-S6, hold8 (the one anchor, no key): when the honest refusal is due, ``REFUSE_BEFORE_DROP_SECONDS`` before the question is dropped, so that it is said before the drop and not after; ``None`` without a deadline.
        fix5: of the question of the JOB (``qid``): a job asked on a question not yet opened (its final not admitted) has its own speech's bound, not the older open question's (w3 n2_d06 step 2: the third part's job got the second part's moment, passed at its start, and the sentence came 0.1 s after it)."""
        if qid is not None and qid!=self.question_id:
            if self.candidate and self.candidate['id']==qid:return None      # round 3: no sentence of the roads while a candidate is judged: its walk ends at its due and the controller says the phrase (``_answer_watchdog``)
            due=self.decision_due(qid);return None if due is None else due-REFUSE_BEFORE_DROP_SECONDS
        deadline=self.answer_deadline();due=None if self.fast_mark or self.published or self.diagnosed_epoch==self.epoch else self.decision_due()      # hold8: the refusal is due by the bound of the whole chain (a question the ear opened has no final of the cloud, the watchdog has nothing to do for it; one on the lookup's route has the lookup's wait on the watchdog, not on its job)
        if due is not None:deadline=due if deadline is None else min(deadline,due)
        return None if deadline is None else deadline-REFUSE_BEFORE_DROP_SECONDS
    def _stalled_stream(self,now):
        """DEF-T-B01: the answer watchdog once something is published - never off for good. The listener has run out of the published
        text and waits at the frontier of a stream that is still open: after ``answer_cap_seconds`` of that wait (the same absolute cap as
        for a question that produced no cue, whatever the cloud does meanwhile) the text that did arrive is the end of the answer (its
        segment is settled as at the end of the grace window), or the stream is closed as it stands. The first segment's silence alone
        still proves nothing for that long (Task 2: it may be a long thought); not while the listener speaks."""
        state=self.state()
        # W1F-B (the coordinator's ruling on «стоп»): a paused answer whose stream is still open has the same cap, counted from the pause.
        paused=bool(state and state.get('paused'))
        if not state or not state.get('streaming') or not (state.get('stream_waiting_next') or paused):
            self.frontier_since=None;return []
        spot=(state.get('revision'),'paused' if paused else state.get('chunk_index'))
        if not self.frontier_since or self.frontier_since[0]!=spot:self.frontier_since=(spot,now)
        cap=self.answer_cap_seconds or self.answer_wait_seconds
        if self.hearing or now-self.frontier_since[1]<cap:return []
        logger.info('echo-sync decision kind=answer reason=stream_stalled waited=%.1f revision=%s',now-self.frontier_since[1],spot[0])
        self.frontier_since=None
        sid=self.source_segment_id;turn=self.ledger.snapshot(sid) if sid else None
        if turn and turn['valid'] and turn['role']=='assistant' and self.owners.get(sid)==self.question_id and sid not in self.retired_assistants:
            actions=self._end_declared(turn)
            if not (self.state() or {}).get('streaming'):return actions
        reply=self.engine.extend_answer(session_id=self.session_id,revision=self.revision,answer=self.published,final=True)
        return self._cue(reply) if reply else []
    def grounding(self,epoch,rows):
        if epoch!=self.epoch or not self.question_id or (self.direct_content and not self.lookup_served):return []
        if self._declined(self.question_id):return []     # G3: the cloud took the turn for nothing to answer: it is not asked again with the sources
        sources=self._relevant(public_sources(rows))
        if not sources or self.grounded:return []
        self.sources=sources;self.grounded=True
        self.answer_marker='[ECHO:'+uuid.uuid4().hex+']'
        # Previous ungrounded assistant turns must never acquire a source label.
        self.blocked.update(t['id'] for t in self.ledger.history() if t['role']=='assistant')
        return self._context_action()
    def _relevant(self,sources):
        """DEF-T-11 (T-A F33/C12/C20) with amendment R2a. Shared stems are a signal that a source is about what was asked, never proof;
        the protected parts of the question decide what a source is NOT about. What is asked is the lookup's query (the question, and
        for a follow-up the topic it inherits) without the words of the request itself.

        - a row with fewer than two content words («см.») is a fragment, no source;
        - a row that shares stems with the question but says them of another number or year, of the affirmed word where the question
          negates it, of another subject (it shares none of the question's nouns), or under another condition (its own «если …» about
          the question's condition with another predicate) is about something else: never grounding, whatever it shares;
        - a row that shares a content stem and conflicts with none of that is grounding;
        - a row that shares no stem (a source in synonyms, or one about something else: they cannot be told apart by words) is kept as
          WEAK grounding (``relevance: weak``, the model reads it as data and the policy lets it say it does not know) rather than
          answering a possibly good source with «Не нашёл»; but only when no row shares the question's words - next to those it is noise,
          unless it gives the cause a question that asks for one wants («почему …?» - «…, потому что …»): it answers what was asked, a
          signal that it may be about the question's subject (INTEG7, T-A C11: the passage of the full lecture that answers «почему» in
          other words was dropped next to the summary that names the subject). It stays weak.
        A query with no content word, and a row with no Cyrillic letter (no Russian stem to compare), keep the form check alone."""
        query=self.lookup_query or self.question_text
        asked=[item for item in _content(query) if item[0] not in _REQUEST_STEMS]
        if not asked:return sources
        stems={item[0] for item in asked}
        cause=bool(_ASKS_A_CAUSE.search(query))
        kept,dropped=[],{}             # (kind, source) in the order of the rows: 'strong', 'cause' (weak: the cause asked for), 'weak'
        for source in sources:
            text=' '.join(str(source.get(key) or '') for key in ('title','text'))
            if not _CYRILLIC.search(text):
                kept.append(('strong',source));continue
            items=_content(text)
            reason='fragment' if len(items)<2 else _source_conflict(asked,items,query,text,by_value=self.fast_call)
            if reason is None:     # A3-1: the same article number of another code or law, or a repealed one, is no source of this question
                identity=search_identity.identity(query,source);reason=identity if identity in ('document','article','repealed') else None
            # The subject rule needs a subject of the row's own: a row whose leading clause has a pronoun for its subject names none (INTEG7).
            unnamed=reason=='subject' and bool(_UNNAMED_SUBJECT.match(source.get('text') or ''))
            if reason and not unnamed:
                dropped[reason]=dropped.get(reason,0)+1;continue
            if stems&{item[0] for item in items} and not unnamed:kept.append(('strong',source))
            else:kept.append(('cause' if cause and _GIVES_A_CAUSE.search(text) else 'weak',{**source,'relevance':'weak'}))
        if dropped:logger.info('echo-sync decision kind=lookup reason=sources_unrelated %s',
                               ' '.join(f'{key}={value}' for key,value in sorted(dropped.items())))
        named=any(kind=='strong' for kind,_ in kept)
        result=[source for kind,source in kept if kind!='weak' or not named]
        weak=sum(1 for source in result if source.get('relevance')=='weak')
        if weak:logger.info('echo-sync decision kind=lookup reason=sources_weak kept=%s',weak)
        return result
    def _question_final(self):
        """Has the listener finished the question (its user turn is final)? F3 round 1: a result for the model is sent only then - a delegation can
        arrive while the question is still being said, and what was decided on a partial («Что говорится в девятой статье») is not the verdict on
        the question («… Налогового кодекса»)."""
        user=self.ledger.snapshot(self.question_id) if self.question_id else None
        return bool(user and user['valid'] and user['final'])
    def _note_answered(self,delegation_id):
        self.answered_delegations.append(delegation_id)
        del self.answered_delegations[:-64]
    def _release_result(self):
        """The result of the question's delegation, if it was waiting for the final of the question (``_question_final``)."""
        if not self.delegation_id or self.delegation_id in self.answered_delegations or not self._question_final():return []
        return (self.without_source(self.epoch,'delegated') or []) if self.direct_content else self._context_action()
    def _context_action(self):
        if self.context_requested or not self.grounded:return []
        transport='delegation' if self.delegation_id else None
        if self.source_delivery=='delegation' and not self.delegation_id:
            user=self.ledger.snapshot(self.question_id)
            if not self.session_context_fallback or not user or not user['valid'] or not user['final']:
                return self._fast_release('sources',sources=self.sources) if self.ear_lookup and self.fast_call and user and user['valid'] else []      # c22-speed: the job with its source starts now, the cloud's context goes with the final (``_ear_first_final``)
            transport='session_context'
        elif self.delegation_id and (self.delegation_id in self.answered_delegations or not self._question_final()):return []   # one result per item
        self.context_requested=True
        if self.delegation_id:self._note_answered(self.delegation_id)
        return self._fast_release('sources',sources=self.sources)+[{'type':'context','epoch':self.epoch,'question':self.question_text,'sources':self.sources,
                 'marker':self.answer_marker,'delegation_id':self.delegation_id,'source_transport':transport}]
    def delivery_sent(self,epoch,delegation_id):
        if epoch!=self.epoch or not self.context_requested:return False
        if self.delegation_id:
            if delegation_id!=self.delegation_id:return False
        elif not self.session_context_fallback or delegation_id is not None:return False
        self.delivery_ready=True;self.delivered_at=self.clock();self.refused_attempt=None
        self.delivered_transport='delegation' if delegation_id else 'session_context'
        if self.lookup_served and self.direct_content and not self.source_missing:
            # DEF-T-B15: the sources the model asked for reached it. Nothing said yet: its answer is a sourced one from now on (and text it
            # made before is not). A model-knowledge answer already being dictated goes on as it is.
            if self.published:return True
            self.direct_content=False
        self.blocked.update(t['id'] for t in self.ledger.history() if t['role']=='assistant')
        self.delivery_anchors={t['id']:t['text'].lstrip() for t in self.ledger.history() if t['role']=='assistant' and t['id']!=self.fast_turn}
        return True
    def lookup_result(self,epoch,rows=None,failure=None,ticket=None):
        """The ONE verdict on the end of a lookup (cm-route, the stage «итог поиска»): ``(actions, failure, reason)``. ``rows``: what the search returned (``grounding``); ``failure``: the exception of a search that failed or timed out.
        ``failure`` of the answer is None when the actions go on (they may be empty: a question that has been replaced or grounded is no business of this result); ``'moot'`` when the local reference answer of this question already sounds
        (``_publish_reference``: nothing of the model or of the lookup is its answer from then on, Level1-c of 06.11, question 19), so a lookup that was not used is no failure to tell the listener of; otherwise it is the code of the one
        phrase the transport says, when the question cannot go on to the model's own knowledge (``without_source``, c8)."""
        if ticket is not None and self.ticket_stale(ticket):return [],None,None      # U62: the search was made for another question than the one standing
        if failure is None:
            actions=self.grounding(epoch,rows)
            if actions or epoch!=self.epoch or self.grounded:return actions,None,None
            reason='no_sources'
        else:
            if epoch!=self.epoch:return [],None,None
            reason=failure
        if self.question_id and self.local_answer and bool(self.published) and not self.grounded:return [],'moot',None
        follow=self.without_source(epoch,'failed')
        if follow is None:
            self.answer_diagnosed(epoch)      # the phrase of the failure is said to the listener (``diagnostic_line``): the answer watchdog adds none on top
            return [],'controlled_sources_unavailable',reason
        # Logged like every failure (class + reason, never the listener's words); the listener hears nothing of it now.
        logger.warning('echo-sync failure class=lookup code=controlled_sources_unavailable reason=%s diagnostic=deferred_answer_from_memory',reason_of(reason))
        return follow,None,None
    def _no_search_result(self,unsourced=False):
        """The ONE no-search result for the model (``context_frames``, ``no_search``), on the item of its delegation, so the model's wait ends; once per question, only when the
        question is FINAL (a partial decides nothing). ``unsourced`` (c8): the lookup gave no source - the answer is from memory, hedged; it goes on the session's speakable context too
        (the fallback a lookup's sources take without a delegation) and only while nothing of an answer is published (``_release_result`` sends it once the final is in). Otherwise
        (F3, items 2 and 4): nothing is looked up, the model-knowledge route stays as it is (its answer is dictated as unverified) and the model is told why - a settled fact
        ("stable knowledge") or a personal question (nothing to look it up in) - in words that are true of it; nothing without a delegation (a model that did not ask for a
        search is not waiting for a result)."""
        did=self.delegation_id
        if self.context_requested or not self._question_final() or (unsourced and self.published):return []
        if did:
            if did in self.answered_delegations:return []
            transport='delegation'
        elif unsourced and self.source_delivery=='delegation' and self.session_context_fallback:transport='session_context'
        else:return []
        self.context_requested=True
        return (self._fast_release('unsourced') if unsourced else [])+self._no_search_context(did,'unsourced' if unsourced else 'personal' if self.search_refused else 'settled',transport,self.answer_marker)
    def _no_search_context(self,did,why,transport='delegation',marker=''):
        """The ONE frame that tells the model there is nothing to search (``native_media_socket.context_frames``): the item of its delegation ``did`` is answered, once. ``why``: 'settled' (a stable fact), 'personal' (the public lookup refuses it) or 'unsourced' (the lookup gave nothing: from memory)."""
        if did:self._note_answered(did)
        if why!='unsourced':logger.info('echo-sync decision kind=lookup reason=model_delegated_no_search revision=%s',(self.state() or {}).get('revision'))
        return [{'type':'context','epoch':self.epoch,'sources':[],'marker':marker,'delegation_id':did,'source_transport':transport,'no_search':True,'why':why}]
    def _publish_reference(self,text):
        """The answer of the reference base goes through the engine as any answer (provenance 'local_reference'): its first cue, or None when
        nothing could be planned of it and the question goes the usual way. From here on nothing of the model is this question's answer (``_source``)
        and a delegation is answered with no search (``without_source``, 'delegated')."""
        # The first portion of a ready answer is the stream's: ONE rule (``first_cue``), the answer being over. Where the rule finds no cue (a restated
        # question, a phone phrase) the engine's plan stands, as it always did for a base answer: it is never silent.
        if self.first_useful_gate:text=self._spell(text)      # the engine takes a stream as spoken text: the base answer is spelled out here, once per call, as every other answer
        cue=first_cue(text,self._part(),self.settings,final=True,last=True)
        cue=cue if cue and text.startswith(cue) else None
        reply=self._reply(self._part(),f'{self.nonce}:{self.question_id}:{self.epoch}:content',decided=self._asked_ruling(self._part(),'local_reference'),
                          answer=StreamingAnswer(text,final=True,retrieval_status='local_reference',first_chunk=cue))
        state=self.state()
        if not state or not state.get('chunks'):return None
        self.local_answer=True;self.direct_content=True;self.published=text;self.revision=state['revision']
        return self._cue(reply,first=True)
    def _interrupted_head(self,first,joined,final=False):
        """How many characters of ``joined`` (the exact wire text of this answer's segments, ``first`` being the first one) still belong
        to the sentence that the assistant segment before ``first`` - owned by ANOTHER question - left unfinished: 0 when the answer
        starts on its own, ``None`` while the end of that sentence has not arrived yet.

        W1F-B (C6, sc12 step 4): the transport also cuts BETWEEN two words («…могут иметь» | « одинаковую массу, но разную
        плотность.Небо…»). A segment that opens with a space and a lower-case word is weighed up to its first sentence end
        (``_old_tail``): the old tail is skipped, a head that is the new answer is kept (``final``: no more text will come)."""
        turns=self._wire_turns();ids=[t['id'] for t in turns]
        if first not in ids or ids.index(first)==0:return 0
        prev=turns[ids.index(first)-1]
        if self.owners.get(prev['id'])==self.question_id or _ENDS_SENTENCE.search(prev['text']):return 0
        word_goes_on=bool(re.match(r'[а-яёa-z]',joined) and re.search(r'[^\W\d_]$',prev['text'])) \
            or bool(re.match(r'\d',joined) and re.search(r'\d$',prev['text']))
        end=_HEAD_TERMINATOR.search(joined)
        if not (word_goes_on or re.match(r'[,.;:!?…»”)]',joined)):
            if not re.match(r'\s+[а-яё]',joined):return 0
            if _ends_in_number(prev['text']):
                # C7 (W4 w4_05 step 6): «Шестьдесят» | « лет.» - the old sentence stopped at its number, and a lower-case word after it is
                # that number's unit or what it counts: never the start of a new answer (a bare «лет.» was cued and the number was lost)
                return (end.end() if end else len(joined)) if (end or final) else None
            verdict=self._old_tail(joined[:end.end()] if end else joined,prev,complete=bool(end) or final)
            if verdict is None:return None
            return (end.end() if end else len(joined)) if verdict else 0
        return end.end() if end else None
    def _old_tail(self,head,prev,complete):
        """W1F-B (C6): is ``head`` - the first sentence of a new answer's first segment, which opens with a lower-case word after ``prev``, a
        segment of another question cut between two words - the rest of that old sentence? Not when it shares a content word with the new
        question (it is about it), nor when it has the form the question asks for («␣в 1941 году.» to «Когда началась война?», ``_answers_the_form``); yes when
        the new question names something of its own: a word it does not share is no sign of the new answer (G3, rule 6: a continuation of an older answer is
        never the answer); an elliptical follow-up («А почему?») names nothing, and its answer goes on with the topic («␣потому что…»). ``None``: not known yet
        (the head's sentence end has not arrived)."""
        question=self.question_tail or self.question_text     # of a repeat + a question in one breath only the question: the rest of the utterance is the old answer
        asked={item[0] for item in _content(question) if item[0] not in _REQUEST_STEMS}
        mine=_stems(head)
        if mine&asked:return False
        topic=self.question_reason=='topic_change'
        if not topic and not asked:return False
        if not complete:return None
        return topic or not self._answers_the_form(head,question)
    def _old_answer_goes_on(self,text,turn):
        """G3, rule 6: the rest of an older sentence opened this segment. What follows it is the new answer only when it speaks of what the question names («…
        разную плотность.Небо голубое …»); else the older answer is simply going on, and no text of it becomes this question's answer. Held until its first
        sentence is over; then the cloud has said nothing to the question (``_declined``)."""
        asked={item[0] for item in _content(self.question_tail or self.question_text) if item[0] not in _REQUEST_STEMS}
        if not asked or not text or asked&_stems(text):return False
        if turn['final'] or _ENDS_SENTENCE.search(text):
            self.retired_assistants.add(turn['id']);self.plan_told=self.question_id
        return True
    def _answer_so_far(self):
        """The text of the current answer before a restart: the spoken text a previous restart continued, the closed segments after
        it and the segment the restart follows (raw wire text, each segment from where the answer goes on in it)."""
        sid=self.source_segment_id
        last=self.ledger.snapshot(sid) if sid else None
        text=self.source_segment_prefix+(last['text'][self.segment_offsets.get(sid,0):] if last else '')
        return (self.restart_base+' '+text) if self.restart_base else text
    def _restart_verdict(self,text,final,start):
        """Task E3c with amendment R2a: what a new segment of this answer is, after a segment that was cut. ``start``: the signal of its
        first characters (``_segment_start``), never the verdict. Returns ``'join'`` (the rest of the cut sentence or the answer going on:
        joined as before), ``'drop'`` (a reply to the listener, or a retelling that cannot be aligned: the plan stays, nothing glued, no
        foreign word spoken), ``(keep, offset, marker)`` (the first ``keep`` portions stay; the answer goes on with the segment's text from
        ``offset``, after ``marker`` when it is a correction), or None (not decided yet: more text will tell; bounded by the segment's end,
        RESTART_MAX_WORDS and ``segment_idle_seconds``).

        Stems are signals, the protected tokens decide what is NOT the same (R2a):
        - the segment retells what the listener heard - the content words of the portion heard last (or of the last confirmed one) in order,
          with the same numbers and the same negation, from its first word unless it begins a new sentence: it goes on after them;
        - the same stems with another number or another negation, in the heard words or in what the segment retold before them: it says
          something else about it - an explicit correction («Поправка:») of everything not confirmed, never an alignment;
        - a new sentence that shares no content word with the confirmed portions but two with the rest of the answer retells the part nobody
          has confirmed: it takes its place; one that shares two with the confirmed portions starts the answer again: dropped;
        - a new sentence that retells nothing is the answer going on (never lose its tail) unless it is a reply to the listener
          («Хорошо, продолжаем.», a bare number to a question that asks for none): dropped;
        - a lower-case word, a digit, a mark, a name, an abbreviation or a quotation that retells nothing goes on with the cut sentence.
        Nothing of the answer said yet: a new sentence takes the place of the cut segment, unless it is a reply to the listener."""
        usable=_complete(text,final);items=_content(usable)
        bounded=final or len(items)>=RESTART_MAX_WORDS
        items=items[:RESTART_MAX_WORDS]
        enough=bounded or len(items)>=(RESTART_DECIDE_WORDS if start=='sentence' else 2)
        head=_LEADING_MARKS.match(text).end()
        state=self.state()
        if not self.published or not state or not state.get('chunks') or state.get('completed'):
            if start!='sentence':return 'join'
            if not enough:return None
            return 'drop' if _chatter(usable,self.question_text) else (0,head,'')
        chunks,confirmed,heard=self.engine.heard_span(state)
        # F1 round 2: what a restart retells is weighed against the TEXT heard so far, however it was cut into portions (an anchor of the
        # last four words of the portion heard last depended on the portion size: with meaning-sized portions a restart that retold the
        # start of that portion, or the part of the cut sentence nobody had heard yet, was glued onto the cut sentence). Numbers are
        # compared by their value (ru_alignment), «не»/«ни» go with the word they negate.
        heard_text=' '.join(chunks[:heard])
        said=_valued(_content(heard_text),heard_text)
        words=_valued(items,usable)
        # The retelling goes on after what was heard only when it reaches its end: its last word and the one before it in the same
        # sentence (one word when the sentence has just one) - also for the portions confirmed when the listener is on another one.
        ends={heard:(len(said)-1,min(2,_last_sentence_words(said,heard_text)))}
        if 0<confirmed<heard:
            confirmed_text=' '.join(chunks[:confirmed])
            known=_valued(_content(confirmed_text),confirmed_text)
            ends[confirmed]=(len(known)-1,min(2,_last_sentence_words(known,confirmed_text)))
        first=start!='sentence'                         # a lower-case word, a digit, a mark or a name retells only from its first word
        told=_retelling(said,words,first) if said and words else None
        unheard=None
        if said:      # the content items of the answer after the text heard: what the cut segment said and nobody has heard yet (None: the heard words are not in it in order)
            whole=self._answer_so_far();every=_valued(_content(whole),whole);found,last=0,-1
            for at,item in enumerate(every):
                if found<len(said) and item[0]==said[found][0]:found,last=found+1,at
            unheard=every[last+1:] if found==len(said) else None
        fresh=_retelling(unheard,words,first,from_start=True,strict=True) if unheard and words else None
        if first:
            if not words:return 'join' if bounded else None
            # It can begin neither a retelling of what was heard nor one of what the cut segment said and nobody has heard: it goes on
            # with the cut sentence at once - never held.
            if not told and not fresh:return 'join'
        if told and told[1] and len(told[0])>=2:return (confirmed,head,'Поправка:')   # the same words saying something else (R2a)
        for keep,(end,needed) in sorted(ends.items(),reverse=True):
            run=_retelling(said[:end+1],words,first,to_end=True) if told and end>=0 else None
            if run and not run[1] and len(run[0])>=needed:
                offset=_AFTER_ANCHOR.match(text,words[run[0][-1][1]][2]).end()
                if _content(usable[offset:]):return (keep,offset,'')
                return 'drop' if final else None              # it retells what was heard and says nothing more (yet)
        if fresh and len(fresh[0])>=min(2,len(unheard)):
            return (heard,head,'')    # it tells again what the cut segment said and nobody has heard yet: it takes the place of that
        if not enough:return None
        if first:return 'join'
        # W1F-B (w1_11): a retelling of what was heard may still be completing at the end of this prefix (« Стоп. Окей, у знака » |
        # ««Стоп»…»): a verdict that drops or glues the segment waits for the next words, so that it never depends on how the transport cut
        # the deltas.
        if not bounded and told and told[0][-1][0]<len(said)-1 and told[0][-1][1]>=len(words)-1-RESTART_ANCHOR_GAP:return None
        mine={item[0] for item in items}
        said=_stems(' '.join(chunks[:confirmed]))
        rest=(_stems(' '.join(chunks[confirmed:]))|_stems(self._answer_so_far()))-said
        if not mine&said and len(mine&rest)>=2:return (confirmed,head,'')
        if len(mine&said)>=2 or _chatter(usable,self.question_text):return 'drop'
        return 'join'
    def _weigh_segment(self,turn,start):
        """Task E3c / R2a: ``turn`` is a new assistant segment of this answer after a segment that was cut. Weighed while it arrives
        (``_restart_verdict``): None when it is to be joined to the cut segment as before; otherwise the actions of its verdict (held
        while undecided, dropped, or continuing the plan after what the listener has heard)."""
        tid=turn['id']
        if tid in self.joined_segments:return None
        if self.pending_restart not in (None,tid):self._drop_restart(self.pending_restart,'restart_superseded')
        verdict=self._restart_verdict(turn['text'],turn['final'],start)
        if verdict=='join':
            if self.pending_restart==tid:self.pending_restart=None
            self.joined_segments.add(tid)
            return None
        self.pending_restart,self.pending_start=tid,start
        self.unsettled=None        # the end of the cut segment is not declared while this one is weighed
        if verdict is None:return []
        if verdict=='drop':return self._drop_restart(tid,'restart_unaligned')
        if self.restarts>=MAX_RESTARTS:return self._drop_restart(tid,'restart_cap')
        return self._commit_restart(turn,*verdict)
    def _drop_restart(self,tid,reason):
        """The segment is not this answer, or cannot be aligned with confidence: it is never spoken, and the plan stays as it is. The
        segment it followed is the end of the answer after all: declared the usual way (the grace window, ``_settle``)."""
        self.retired_assistants.add(tid)
        if self.pending_restart==tid:self.pending_restart=None
        logger.info('echo-sync decision kind=silent reason=%s revision=%s',reason,(self.state() or {}).get('revision'))
        sid=self.source_segment_id;last=self.ledger.snapshot(sid) if sid else None
        if last and last['valid'] and last['final'] and sid!=self.settled_segment and self.unsettled is None:
            self._end_open(sid,self.clock())
        return []
    def _same_words(self,text):
        """``text`` as the continuation of what was published when its first words ARE the published words (punctuation, case, spacing
        or ё changed: a refined transcript of the same speech); else None."""
        said=norm_words(self.published)
        words=list(WORDS.finditer(text))
        if len(words)<len(said) or [normalize(word.group()) for word in words[:len(said)]]!=said:return None
        if not said:return self.published+text
        rest=text[words[len(said)-1].end():]
        # F1 round 2: a published portion that ends at its punctuation («… почти всегда,») already holds the mark the new text has there
        mark=self.published[list(WORDS.finditer(self.published))[-1].end():].strip()
        if mark and rest.lstrip().startswith(mark):rest=rest.lstrip()[len(mark):]
        return self.published+rest
    def _lead_passed(self):
        """f3-reaction (``lead_cue``): the lead only fills the wait for the substance; once the substance is there and the listener has not begun the lead, it does not
        wait for a repeat of the lead (it used to be cued again after ``repeat_seconds``): the lead counts as said and the substance is cued after it at once."""
        state=self.state() or {}
        if self.tempo_speaking or state.get('chunk_index')!=0 or probe('waiting_portion',state=state).value!=self.lead_said:return []
        logger.info('echo-sync decision kind=ack reason=lead_passed revision=%s index=0',state.get('revision'))
        return self._accept_user({'id':f'lead-{self.question_id}','role':'user','valid':True,'final':True,'text':self.lead_said},boundary='lead_cue',cause='lead_cue')
    def _lead_cue(self,turn):
        """W5-lead (``lead_cue``): the answer from the model's knowledge opens with the question's own words at once (question_lead.py); the ear's text is the
        first witness and the cloud's final the second. Published as the first portion of the answer, so BRAIN's text goes on after it (``_lead_join``). Not the first
        useful help: its own journal line."""
        if not self.fast_call or self.published or not self.question_id or not self.direct_content:return []
        if not self.ear_said:      # E56: no word of the ear came before this final, so the lead has no head start; a job prepared on the cloud's stable text that is over gives the answer itself with this final, and the lead would only go before it
            said=self.prepared_job(self.fast_text or self.question_text) if self.prepared_job else None
            if said and said[1] and brain_answer(said[0]):return []
        ear=' '.join(piece['text'] for piece in self.ear_said[-1:] if piece.get('text')) or turn['text']
        got=lead(ear,cloud=turn['text'])
        if got is None:return []
        reply=self._reply(self._part(),f'{self.nonce}:{self.question_id}:{self.epoch}:content',decided=self._asked_ruling(self._part(),'admitted_answer'),
                          answer=StreamingAnswer(got.text,self.sources,final=False,retrieval_status='unverified',first_chunk=got.text,raw_text=got.text))
        state=self.state()
        if not state or not state.get('chunks'):return []
        self.revision=state['revision'];self.published=self.lead_said=got.text
        logger.info('echo-sync lead_cue %s',' '.join(f'{k}={v}' for k,v in lead_row(got,at=round(self.clock(),3)).items() if k not in ('event','text')))
        return self._cue(reply)
    def _lead_join(self,text,final):
        """W5-lead: BRAIN's text after the lead already said (``question_lead.splice``): the lead, then what the answer says beyond it. None: not decided yet."""
        joined=lead_splice(self.lead_said,text,final=final)
        if joined.mode=='pending':return None
        if self.published==self.lead_said:logger.info('echo-sync lead_cue splice=%s',joined.mode)
        return self.lead_said+(' '+joined.rest if joined.rest else '')
    def note_guard_event(self,event):
        """A note asks the cloud nothing (quiet commentary), and the moments it is sent at leave nothing the cloud says open to dictation
        (``_note_safe``). On top of that: an assistant turn that BEGINS after a note and before the listener speaks again can only be a
        reaction to the note (or to nothing), so it is retired at once, before the controller sees it - it is never dictated, whatever
        later becomes of the conversation. The transport calls this for every provider event, before ``provider``."""
        if not self.note_guard or not isinstance(event,dict):return
        typ=event.get('type');raw=event.get('turn')
        role=raw.get('role') if isinstance(raw,dict) else None
        if typ=='turn.delta':
            known=self.ledger.snapshot(event.get('turn_id')) if isinstance(event.get('turn_id'),str) else None
            role=known['role'] if known else None
        if typ=='input_audio_buffer.speech_started' or (role=='user' and typ in ('turn.created','turn.delta','turn.done')):
            self.note_guard=False;return
        tid=raw.get('id') if isinstance(raw,dict) else None
        if role=='assistant' and typ in ('turn.created','turn.done') and isinstance(tid,str) and self.ledger.snapshot(tid) is None:
            self.retired_assistants.add(tid)
            logger.info('echo-sync decision kind=silent reason=reply_after_a_note_retired')
    def _witness(self,text):
        """Q1 and W2: what the same code makes of ``text``: a figure, else a prepared answer (the ear may get a word of the question wrong as it gets numbers wrong: ``same_question`` guards numbers, not every word)."""
        figure=quick_answer(text)
        return figure if figure else self._prepared(text)
    def _witness_look(self,turn):
        """The answer witness (no key; nothing is said): while the job's answer is said, the cloud's own reply to the question is read for its first sentence with a number (``answer_witness.py``). What it says of the job's leading number is a line of the call trace at
        once; when they differ the third source is asked off the loop and says who is right, and what would be said. Nothing here changes the call, and it can never touch it. A reply begun before the final of the question is the tail of the one before."""
        try:
            tid=turn['id'];done=self.user_done_at.get(self.question_id)
            self.witness_born.setdefault(tid,self.clock())
            if tid==self.fast_turn or not self.fast_turn or self.local_answer or done is None or self.witness_born[tid]<done-WITNESS_SLACK_SECONDS or (self.question_id,tid) in self.witness_seen:return
            said=brain_answer(self.fast_said);asked=(self.ledger.snapshot(self.question_id) or {}).get('text') or self.question_text      # the cloud's words: the question text of an ear that opened may be its last piece only
            sentence=witness_rule.first_sentence(turn['text'],asked,closed=turn['final'])
            case=witness_rule.judge(asked,said,sentence,()) if said and sentence else None
            if not case:return
            self.witness_seen.add((self.question_id,tid));self.witness_cases=self.witness_cases[-31:]+[case]
            self._witness_write('witness',case,asked,said,sentence)
            if case['verdict']=='differ':threading.Thread(target=self._witness_third,args=(case,asked,said,sentence),name='echo-witness',daemon=True).start()
        except Exception as error:logger.warning('echo-sync answer witness failed type=%s',type(error).__name__)
    def _witness_write(self,line,case,asked,said,sentence):
        if self.witness_note:self.witness_note(line,asked=asked[-200:],said=said[:200],sentence=sentence[:200],**case)
    def _witness_third(self,case,asked,said,sentence):
        """Off the loop: the third source decides, or says it cannot. Its second line has the side, the source and the correction it would have said."""
        try:
            began=self.clock();passages=self._witness_passages(asked)
            case.update(witness_rule.judge(asked,said,sentence,passages),passages=len(passages),ms=round((self.clock()-began)*1000))
            self._witness_write('witness_third',case,asked,said,sentence)
        except Exception as error:logger.warning('echo-sync answer witness third failed type=%s',type(error).__name__)
    def _witness_passages(self,asked):
        """The third source, its order: the bank, the laws, the material. By its words, with no rule of a match: such a text is never an answer here, it only tells two numbers apart (``answer_witness.decide``). What a match can answer has been answered before any job."""
        from .law_base import passages      # noqa: PLC0415 - as the base's adapters: only when it is asked
        near=self.instant.near(asked) if self.instant is not None else []
        return [item for item in near if item[1]=='bank']+[(text,'law_base') for text in passages(asked)]+[item for item in near if item[1]=='material']
    # ==== H1 + H2: the text channel (fast_text.py) is the brain, GPT-Live the ear ====================================================
    # H2 rulings 1-3 (the owner's call of 4 Nov 20:34): there is no race. Every final the arbiter leaves goes to ONE job, a question the classifier saw (``_fast_release``) and a final
    # with no form (``_take_candidate``, ``_fast_ask``), and the job's text is the verdict and the source. «—» or nothing: nothing is said, no question opens, one the classifier
    # opened is dropped and the plan gives back. An answer: for a candidate that is the admission. While a job runs the cloud's turns are set aside (``_fast_holds``); its text is
    # weighed only when the job fails or times out with nothing published (the hand-back). Once a job fails with something published the cloud is not asked to go on.
    def _fast_running(self):
        """Is the job of the open question still at work?"""
        return self.fast_asked is not None and not self.fast_done and self.fast_asked[0]==self.question_id
    def _fast_holds(self,tid):
        """Is this assistant turn set aside (rule 1)? A job owns the answer, or runs for the open question, or has declined it and the plan waits for silence to come back."""
        if self.fast_turn:return tid!=self.fast_turn
        if (self.question_id is not None and self.fast_declined==self.question_id) or self._fast_running():return True
        return self.fast_on and self.fast_handed!=self.question_id     # H6 item 1: whatever the route: no text of the cloud until a job for that very final has failed
    def fast_in_play(self):
        """Rule 4: ``(its question, the whole answer)`` of the answer in play: the current plan or the last entry of the history, spoken or not; None.
        R05-F1: not once ``PLAYED_FRESH_S`` have passed since its portion was last spoken (``engine.state_age``): after that a bare «правда?» is the talk of others, not a doubt of it."""
        state=self.state() or {};rows=[row for row in self.fast_exchanges() if row.get('answer')]      # ROOT-2: an unanswered row is context, never the answer in play
        if self.lead_said and state.get('answer')==self.lead_said:       # W5-lead: the lead alone is the question's own words, no answer in play: the job prepared before it stands
            rows=[row for row in rows if row.get('answer')!=self.lead_said];state={}
        if not rows:return None
        age=state_age(state,self.engine.clock())
        if age is not None and age>PLAYED_FRESH_S:return None
        return (str(state.get('question') or ''),state['answer']) if state.get('answer') else (str(rows[-1].get('question') or ''),rows[-1]['answer'])
    def _fast_tail_waits(self,asked,route,extra):
        """H6 item 3: the open question stops on an open tail: its job waits for the rest (FAST_TAIL_SECONDS, ``tick``). What the ear knows ends the wait: nothing goes on."""
        waits=self.fast_tail
        if waits is None or waits['qid']!=self.question_id:
            if not self._tail_open(asked):return False
            self.fast_tail=waits={'qid':self.question_id,'until':self.clock()+FAST_TAIL_SECONDS,'route':route,'extra':extra}
        return self.clock()<waits['until']
    def _fast_tail_due(self,now):
        """H6 item 3, on the tick: the wait of a job for the rest of its final is over."""
        waits=self.fast_tail
        if waits is None or waits.get('over') or now<waits['until']:return []
        waits['over']=True
        return self._fast_release(waits['route'],**waits['extra']) if waits['qid']==self.question_id else []
    def _fast_drop(self):
        """The question went to the lookup (or the reference base answered it): a job the ear prepared is not wanted."""
        return [{'type':'fast','op':'drop'}] if self.fast_on else []
    def _fast_routed(self,asked):
        """Would the model-knowledge route take this question: no lookup, no data that changes?"""
        history=(self.state() or {}).get('history',())
        return (self.fast_call or self.public_lookup_allowed(asked)) and not route_need(asked,history)      # G38 cut 3: «у меня» keeps a question from the public search, not from the job its final goes to
    def _fast_preparable(self,asked):
        """Is this a question of at least three words that the model-knowledge route would take?"""
        return len(norm_words(asked))>=PREPARE_MIN_WORDS and self._fast_routed(asked) and not self._reference(asked)      # A8-2: the base or the code answers it
    def fast_feed(self,turn,qid,kind,text=''):
        """What the channel's job ``turn`` of the final ``qid`` has produced: ``kind`` 'text' (a piece), 'done' or 'failed'. Returns ``(keep, actions)``; ``keep`` False: the channel
        is done with it (the job may be cancelled). A job that is over lets the final that waited for it go to the next one."""
        keep,actions=self._fast_fed(turn,qid,kind,text)
        return keep,actions+self._fast_ask()
    def _fast_answers(self,turn,answer):
        """The job's text is the answer of the open question: an assistant turn owned by it, through the ordinary path, in the event shapes the provider sends."""
        self.fast_turn=turn;self.owners[turn]=self.question_id;self.fast_said=answer
        logger.info('echo-sync decision kind=answer reason=fast_text_owns revision=%s',(self.state() or {}).get('revision'))
        return self.provider({'type':'turn.created','turn':{'id':turn,'role':'assistant','transcript':answer}})
    def _fast_replaced(self,turn,text,final=False):
        """F20 (h31; fix5: the owner's 8 s are kept by the roads' provisional sentence «Ответа пока нет…» said at the question's due, and the job goes on): the sentence stands as the answer of the
        job ``turn`` and its real text comes after it. The text takes the sentence's place from the first portion the listener has not confirmed (``_commit_restart``: the first portion of the answer is
        cued anew); it is never a portion after the sentence that nobody cues. Until a stable piece of it is committed the text waits in the turn; ``final``: the job is over, all of it goes. None: not that case."""
        mark=self.fast_provisional
        if not mark or mark[0]!=turn or self.fast_turn!=turn:return None
        self.fast_said+=text
        snap=self.ledger.apply({'type':'turn.done','turn':{'id':turn,'role':'assistant','transcript':self.fast_said}} if final else {'type':'turn.delta','turn_id':turn,'delta':text})
        if not snap or not self.fast_said[mark[1]:].strip():return []
        state=self.state() or {}
        keep=self.engine.heard_span(state)[1] if state.get('chunks') else 0
        self.source_segment_id=None      # the same turn goes on: it is not closed as a segment that was cut
        actions=self._commit_restart(snap,keep,mark[1])
        self.source_segment_id=turn
        if self.segment_offsets.get(turn)==mark[1]:      # committed: the text is the answer from here on, its later pieces extend it the usual way
            self.fast_provisional=None
            logger.info('echo-sync decision kind=answer reason=fast_text_replaces_refusal keep=%s revision=%s',keep,(self.state() or {}).get('revision'))
        return actions
    def _remember_answer(self):
        """E62 (the ONE writer of the long cache, ``PreparedAnswers.remember``): the job's text ended whole (``done``, never ``failed``) and is the answer of the open question: it is kept for the next call, so that the same
        standalone question is a hit of ``_prepared`` without the model. Only a question the privacy gate lets to the public search (``privacy_gate.allowed(search=True)``: nothing of the listener's own affairs), no correction,
        no refusal sentence, no answer the lookup said it has no source for; what changes with time or refers back is refused inside ``remember`` (``_stable``). Never raises, says nothing."""
        try:
            if self.prepared is None or self.local_answer or self.question_kind==CORRECTION or self.source_missing or self.search_refused:return
            asked=self.question_text
            answer=brain_answer(self.fast_said)
            if not asked or not answer or REFUSAL in answer or not privacy_gate.allowed(asked,True) or privacy_gate.personal_reason(asked):return
            self.prepared.remember(asked,answer)
        except Exception:      # noqa: BLE001 - a cache never costs a call
            return
    def _fast_close(self,turn):
        """The job is over: its text is whole (a stream without ``response.completed`` is a failure, fast_text.codex_stream), so no grace window waits for a continuation that
        cannot come. What is left of it is said, or held with the question as any text, and a stream that took none of it still ends here, not at the 30 s cap."""
        closed=self.ledger.apply({'type':'turn.done','turn':{'id':turn,'role':'assistant','transcript':self.fast_said}}) or self.ledger.snapshot(turn)      # fix5 (F20): the text that took the sentence's place at the job's end has closed the turn already (``_fast_replaced``): it is closed as it stands (half_hour seed 4: a TypeError here lost the answer)
        self.turn_done_at.setdefault(turn,self.clock())
        actions=self._end_declared(closed)
        return actions+self._fast_closed() if self.published and (self.state() or {}).get('streaming') else actions
    def _fast_out(self,turn):
        """The job's turn is no answer and never will be."""
        self.fast_turn=None;self.retired_assistants.add(turn);self.owners.pop(turn,None)
        self.source_segment_id=None;self.source_segment_prefix='';self.answer_head=None;self.unsettled=None;self.settled_segment=None;self.held_source=None
    def _fast_failed(self,turn):
        """H5 item 7: a job failed with nothing published: one more on the same question, with a wait of its own. Only then the cloud."""
        if self.fast_retried==self.question_id:return self._fast_hand_back(turn)
        self.fast_retried=self.question_id;self._fast_out(turn)
        self.fast_asked=None;self.fast_done=False;self.fast_said=''
        logger.info('echo-sync decision kind=answer reason=fast_text_failed_asked_again revision=%s',(self.state() or {}).get('revision'))
        return self._fast_release(self.fast_route[0],**self.fast_route[1])
    def _fast_hand_back(self,turn):
        """Rule 1: the job failed or timed out with nothing published: the cloud's turns of the question are weighed as of now, and those still to come are the answer."""
        self._fast_out(turn);self.fast_handed=self.question_id;self.fast_handed_at=self.clock()
        logger.info('echo-sync decision kind=answer reason=fast_text_failed_handed_back revision=%s',(self.state() or {}).get('revision'))
        actions=[]
        for earlier in self.ledger.history():
            if earlier['role']=='assistant' and earlier['valid'] and self.owners.get(earlier['id'])==self.question_id and earlier['id'] not in self.retired_assistants and earlier['text'].strip():
                actions+=self._source(earlier)
        return actions
    def _fast_whole(self):
        """What a job that broke after the answer began leaves of its text: the whole sentences, and never less than what is published already (a portion may
        end at a comma, so the cut is the later of the last sentence end and the end of the published text in it). A torn word is never dictated."""
        said=self.fast_said;end=0
        for found in _HEAD_TERMINATOR.finditer(said):end=found.end()
        tail=self.published[-24:];at=said.rfind(tail) if tail else -1
        return said[:(max(end,at+len(tail)) if at>=0 else end)]
    def _fast_closed(self):
        """The text left of a job that is over does not begin with what was published (a term the portioner spelled out, the cut in ``_fast_whole``): no more of it goes in and
        nothing is rewritten, the answer ends with what was said."""
        reply=self.engine.extend_answer(session_id=self.session_id,revision=self.revision,answer=self.published,final=True)
        return self._cue(reply) if reply else []
    def _fast_took_back(self):
        """Rule 4: the answer is whole and it is a repair (``fast_text.revises``): the answer before it stays in the history as 'revised' and the plan it replaced never comes back.
        A doubt that confirms changes nothing: the answer was said once more, as an answer."""
        played,self.fast_played=self.fast_played,None
        if played and revises(played[1],self.fast_said,heard=self.question_tail or self.question_text,question=played[0],disputed=self.question_kind==CORRECTION):
            self.engine.revised(self.session_id,played[0],played[1]);self.suspended=None
    def _fast_no_search(self,uid):
        """The job declined this final and the model had asked for a search on it: it is told there is none, on its item, so that its wait ends (DEF-T-B15). It stays the fallback of
        the next job, and a turn of it is nobody's answer here."""
        did=self.early_delegations.pop(uid,None)
        if not did or did in self.answered_delegations:return []
        return self._no_search_context(did,'settled')
    def fast_lost(self):
        """The channel is out for the rest of the call (the breaker, a fault of the pump, none at all): what it was asked goes back to the cloud, which decides from now on as it did
        before. Nothing published hands the cloud's turns back; something published is closed where it broke; a question that has moved on is a no-op."""
        actions=self._candidate_back() if self.candidate and 'job' in self.candidate else []
        self.fast_retried=self.question_id     # nobody is left to ask again
        if self._fast_running():actions+=self.fast_feed(self.fast_asked[1],self.fast_asked[0],'failed')[1]
        self.fast_on=False
        return actions
