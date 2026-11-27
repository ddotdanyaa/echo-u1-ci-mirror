"""The route methods of ``ControlledMedia`` (cut from controlled_media.py by tools/split_controlled_media.py). Imports from cm_base, never from controlled_media."""
from .cm_base import (CORRECTION, EAR_PILE_SECONDS, FAST_TURN, FIGURE_HEAD_SECONDS, MORE_DETAIL, QUESTION, SOURCES_DIFFER, StreamingAnswer,
    TAIL_HEAD_WORDS, _ENDS_SENTENCE, _atoms, _protected, _rest_end, _segment_start, _stems, compact_opening, honest_reply, instant, norm_words, personal_volatile,
    quick_answer, quick_asked, re, reference_lookup,
    definition_body, drop_process_sentences, first_cue, logger, says_a_number, stable_prefix, strip_process_prefix, unhedged,
    unmarked)


class RouteMixin:
    def _generate(self,*args):
        bound=self._answer
        if bound is None:raise RuntimeError('Controlled content not authorized')
        answer,tid,epoch,revision=bound;state=self.state() or {}
        if state.get('pending_turn')!=tid or epoch!=self.epoch or state.get('revision') not in (revision,revision+1):
            raise RuntimeError('Controlled content of another turn')      # a plain failure (outcome 'failed'), never ``PublicationRefused``: the turn is not tried again with another answer
        return answer
    def prefetch_candidate(self,text=None):
        """Q1 / B9: ``text``: what the local ear heard of the cloud's open turn (``ear_prefetch``), judged by the very same rules as the cloud's partial (privacy included)."""
        user=self.ledger.latest_user()
        if not user or not user['valid'] or user['final'] or user['id'] in self.seen:return None
        decision=self._classify(text or user['text'],self._heard_with(self.state()))      # a reading of the shadow prefetch, through the one funnel and not counted: it is no row of the judge's final
        question=decision.question or text or user['text']
        if decision.kind not in (QUESTION,CORRECTION) or len(question.split())<3:return None
        if self._follows_on(question) or not self._lookup_routed(question):return None      # the route's one question «would it go to the public search» (``_lookup_routed``), not a copy of its rule
        if self._reference(question):return None       # the base or the code answers it: there is nothing to search
        return user['id'],question
    def _wire_predecessor(self,tid):
        """The assistant turn right before ``tid`` on the wire (the ledger's order of arrival), or None."""
        turns=self._wire_turns();ids=[t['id'] for t in turns]
        return turns[ids.index(tid)-1] if tid in ids and ids.index(tid)>0 else None
    def _wire_turns(self):
        """The cloud's assistant turns: a job's turn is in the ledger, it was never on the wire."""
        return [t for t in self.ledger.history() if t['role']=='assistant' and not t['id'].startswith(FAST_TURN)]
    def _source(self,turn,settled=False,stalled=False):
        """``settled``: the grace window after this provider-final turn passed with no continuation (see ``_settle``). ``stalled``: the
        producer fell silent before this segment gave a first cue (``_rescue_first_cue``): the cue is chosen as when its turn is over."""
        tid=turn['id']
        if tid in self.retired_assistants or self.local_answer:return []
        if (not self.grounded and not self.direct_content) or self.owners.get(tid)!=self.question_id:return []
        if self._fast_holds(tid):return []     # H2, rule 1: a job runs for this question or owns its answer: the cloud's turns are set aside
        if self.source_id and self.source_id!=tid and self.source_delivery!='delegation':return []
        text=turn['text'].lstrip();raw=turn['text']
        spoken=False   # ``text`` begins with spoken text already (the portions a restart continues): no opening is stripped from it
        # Arrival order alone cannot prove a response used the new context:
        # a delayed pre-lookup creation can arrive after lookup completed.
        # Only the post-grounding request contains this unique output fence.
        # It is stripped and can never be spoken. This fences generation,
        # not factual entailment; supplied sources still require validation.
        if self.source_delivery=='delegation':
            if not self.direct_content and not self.delivery_ready and tid!=self.fast_turn:return []     # H1: a fast turn counts as delivered
            anchor=self.delivery_anchors.get(tid)
            # A plain session append is not a delegation handoff. Never
            # turn an already-generating answer into a sourced continuation.
            if self.delivered_transport=='session_context' and anchor is not None:return []
            if anchor is not None:
                if not text.startswith(anchor) or text==anchor:return []
                # A native delegated continuation can complete a sentence
                # already being formed. Do NOT slice off its subject or
                # grammar at an arbitrary tool-delivery character offset.
                # Require new post-result content, then clean the whole
                # coherent answer. This is not factual entailment proof.
            if tid in self.closed_source_segments:return []
            if self.refused_attempt and self.refused_attempt[0]==self.source_segment_id!=tid:
                # Wave G: a next segment is new material for a question refused at publication: the refused text is not its head.
                self.retired_assistants.add(self.source_segment_id)
                self.source_segment_id=None;self.source_segment_prefix='';self.answer_head=None
            if self.source_segment_id and self.source_segment_id!=tid:
                previous=self.ledger.snapshot(self.source_segment_id)
                # Native turns may be acoustic segments, including mid-word
                # cuts. Concatenate exact wire text only after the preceding
                # segment ended, with the SAME owning user question.
                if not previous or not previous['valid'] or not previous['final']:return []
                if len(self.closed_source_segments)>=self.ledger.max_turns:return []
                if len(self.source_segment_prefix)+len(previous['text'])+len(turn['text'])>self.ledger.max_chars:return []
                if not _ENDS_SENTENCE.search(previous['text']):
                    # Task E3c / R2a: the segment before was cut. What comes next may be its rest («ваются…», « ног.», « Москве»), the model
                    # starting its answer again (the owner's call: «…приемлемые Первое — в психологии…»), or a reply to the listener
                    # («Десять.»). Only the rest of a word is joined at once; anything else is weighed on what it says (_weigh_segment).
                    wire=self._wire_predecessor(tid)
                    if wire and wire['id']!=previous['id'] and wire['id'] in self.retired_assistants and not _ENDS_SENTENCE.search(wire['text']):
                        # W1F-B (w1_11): the segment right before this one on the wire was dropped and cut mid-sentence: what goes on with
                        # it is dropped with it, never glued to the older segment the answer stopped at.
                        going=_segment_start(turn['text'],final=turn['final'],after=wire['text'])
                        if going is None:return []
                        if going in ('midword','continuation'):return self._drop_restart(tid,'continues_a_dropped_segment')
                    start=_segment_start(turn['text'],final=turn['final'],after=previous['text'])
                    if start is None:return []
                    if tid in self.foreign_replies:
                        # W1F-B (C5): after a turn that is not the question the default is «not this answer»: only the rest of the cut word or
                        # sentence (a lower-case word, a digit, a mark) is the answer's, through the end of that sentence (below).
                        if start in ('sentence','name'):return self._drop_restart(tid,'reply_to_another_turn')
                        self.joined_segments.add(tid)
                    elif start!='midword':
                        weighed=self._weigh_segment(turn,start)
                        if weighed is not None:return weighed
                self.closed_source_segments.add(self.source_segment_id)
                self.source_segment_prefix+=previous['text'][self.segment_offsets.get(previous['id'],0):]
            self.source_segment_id=tid
            # Whatever waited for the end of an earlier segment is moot: this one continues it, or is the last word on it.
            self.unsettled=None
            body=turn['text'][self.segment_offsets.get(tid,0):]
            if tid in self.foreign_replies:
                # W1F-B (C5): the rest of the cut sentence is the answer's; what the cloud says after it is its reply to the other turn.
                end=_rest_end(body,turn['final'])
                if end is not None:body=body[:end]
            joined=self.source_segment_prefix+body
            if self.restart_base is not None:
                # After a restart (Task E3c): the portions it continues, as they were spoken, then the rest of the restart as it arrives.
                text=self.restart_base+(' ' if self.restart_base and joined else '')+joined;spoken=True
            else:
                # Root cause F1 (scenarios sc12/sc07): the transport cuts the model's speech into segments when the listener's turn opens,
                # even mid-word, and the next segment carries the rest («…волны рассеи» | «ваются сильнее, …»). When that next segment
                # is the FIRST of a new question's answer, the rest of the old sentence is skipped through its end; nothing is published
                # until that end has arrived (the start-of-segment counterpart of the first_cue final/last guard).
                if self.answer_head is None or self.answer_head[0]!=self.question_id:self.answer_head=(self.question_id,tid)
                skip=0 if tid==self.fast_turn else self._interrupted_head(self.answer_head[1],joined,final=turn['final'] or settled)   # H1: it starts on its own
                if skip is None:return []
                text=raw=joined[skip:].lstrip()
                if skip and self._old_answer_goes_on(text,turn):return []
        elif not self.answer_marker or text.count(self.answer_marker)!=1:return []
        if tid==self.fast_turn:text=unmarked(text)     # H5 skeptic: a mark inside an answer is not said
        # Frameless can append a context-triggered answer to the existing
        # assistant turn, rather than create a new id. The fresh commit fence
        # still identifies its start: discard ALL earlier ungrounded text.
        if self.source_delivery=='marker':text=text.split(self.answer_marker,1)[1].lstrip()
        withheld=False
        if not spoken:
            text=strip_process_prefix(text,self._part(),digits=self.fast_call)
            # c7-meta (w3_07): a sentence about the cloud's own work later in the answer is no portion either
            whole=text
            text=drop_process_sentences(text,self._part(),
                                        final=settled or (turn['final'] and self.source_delivery!='delegation'),talk=self.fast_call)
            # integ10: an open sentence the drop withholds («… синий свет. Поэт») means the text is cut, not that the answer ends at «свет.»
            withheld=text!=whole and not _ENDS_SENTENCE.search(whole)
            text=definition_body(text,self._part())
        if not self.published:
            # G3, rule 4: a backchannel, or the older answer told again, is no answer to this question
            if self._backchannel(text):return []
            if self.fast_call and not text:return self._fallback_refused(tid,'talk',final=(turn['final'] or settled) and not self._backchannel(turn['text'])) or []     # H2: nothing is left of it: no hold of the question waits for that. H6 item 1: of a fallback that is a refusal
            told=False if tid==self.fast_turn else self._retells_the_plan(turn)     # H2: the job declines with «—»; an answer said again is a doubt it confirmed
            if told is None:return []
            if told:
                self.retired_assistants.add(tid);self.plan_told=self.question_id
                return []
        if self._holding(self.clock()):
            # The question may be unfinished, or is still being spoken or corrected: wait for its continuation, but only while one could
            # still be merged. tick() lets the answer out when that time is over, even if no further event arrives for it.
            self.held_source=tid;return []
        if self.lead_said and text:
            text=self._lead_join(text,turn['final'] or settled)
            if text is None:return []
            spoken=True        # W5-lead: the text begins with the lead already said: no opening is stripped from it
        if self.first_useful_gate:
            if not spoken:text=compact_opening(text,self._part(),self.settings)
            text=self._abbreviations(text)
        # c8 (C8 ruling): the model's hedge of an answer from memory («По памяти: …») is never cued - the listener repeats every portion
        # aloud in front of the examiner; none is added. The engine checks the model's own text for it (StreamingAnswer.raw_text).
        if self.source_missing and not spoken:text=unhedged(text)
        if not text:return []
        refused=self._fallback_refused(tid,'number',text)
        if refused is not None:return refused
        if self.published and not text.startswith(self.published):
            # DEF-T-B01: the producer's text no longer begins with what was published. The same words with another surface go on as
            # published; anything else is a rewrite, never dropped in silence with the stream left open.
            same=self._same_words(text)
            if same is None:return self._fast_closed() if tid==self.fast_turn and self.fast_done else self._rewritten(turn,text,settled)
            text=same
        final=turn['final'] or settled
        if self.source_delivery=='delegation':
            # A transport segment ending in letters is not a producer promise
            # that its last word, let alone the whole answer, is complete: a
            # continuation segment may follow. It is the end of the answer only
            # once the grace window passed with none (_settle).
            final=final and (settled or (bool(_ENDS_SENTENCE.search(text)) and not withheld))
            # The turn is over but its text may be cut: wait for a continuation, then let tick() finish the answer. This is
            # armed even when nothing could be said yet (a lone word, half a sentence): that wait has to end as well.
            if turn['final'] and not final and tid!=self.settled_segment:self.unsettled=(tid,self.turn_done_at.get(tid,self.clock()))
        refused=None if self.published else self._fallback_refused(tid,'short',text,final)     # H6 item 1: «Да.» may still go on, while its turn does
        if refused is not None:return refused
        initial=None
        if self.first_useful_gate and not self.published:
            # The gate may wait for a better opening, never forever: once it is stuck or the producer's turn is over, the
            # ordinary first portion is spoken. Its unfinished last word is not, until the text is final (a segment can
            # stop in the middle of a word and the next one go on); a lone word waits for the grace flush (_settle).
            initial=first_cue(text,self._part(),self.settings,final=final,last=turn['final'] or stalled,patient=tid==self.fast_turn)
            prefix=initial or (text if final and tid==self.fast_turn else None)     # H2: the gate wants a better opening, but the job is over and this is the answer («Канберра.» to «… это Канберра»)
        else:
            # F1 round 2: a listener who has repeated everything published waits at the frontier - an open meaning sentence lets its
            # first planned portion go then, instead of holding them in silence until the sentence ends; once that wait is as long as
            # an idle segment takes to be flushed (the text trickles in), every complete word that arrived goes
            now_state=self.state() or {};waits=bool(now_state.get('stream_waiting_next'));since=self.frontier_since
            starving=bool(waits and since and since[0]==(now_state.get('revision'),now_state.get('chunk_index'))
                          and self.clock()-since[1]>=self.segment_idle_seconds)
            prefix=text if final else stable_prefix(text,self.settings,committed=self.published,eager=waits,starving=starving)
        if not prefix:return []
        if self.published and (not prefix.startswith(self.published) or len(prefix)<len(self.published)):
            self.blocked.add(tid);return []
        if not self.published and self._overtaken('answer'):
            logger.info('echo-sync decision kind=silent reason=admitted_answer_after_a_newer_question revision=%s',(self.state() or {}).get('revision'))
            if self.suspended:self.suspended['asked_before']=True      # Р059 seed 101: the answer held back is no decline: an older plan going on would be an old answer as well
            self.blocked.add(tid);return []
        if not self.published:
            # A finalized producer may have more text beyond the first cue.
            if final and initial:prefix=text
            status='unsourced' if self.source_missing else 'no_search' if self.search_refused else 'unverified' if self.direct_content else 'source_backed'
            # Wave G: a refused segment is tried again only when that can change the verdict: another status, or its text is over (no retry storm).
            attempt=(tid,status,bool(final))
            if attempt==self.refused_attempt:return []
            # A question said after an early-confirmed portion: the verdict is that of the part it was made of, the question recorded is the whole.
            content=f'{self.nonce}:{self.question_id}:{self.epoch}:content';put=self.question_tail or self._part()
            reply=self._reply(put,content,asked=self.question_text if self.question_tail else None,
                              decided=self._asked_ruling(put,'admitted_answer' if self.question_reason=='cloud_admitted' or tid==self.fast_turn or self._part()!=self.question_text else None),
                              answer=StreamingAnswer(prefix,self.sources,final=final,retrieval_status=status,first_chunk=initial,raw_text=raw))     # H2: the job's text is the verdict. H7 item 0: the history and the engine's own gate read what was asked; a part was judged a question with the words around it
            state=self.state()
            if not state or not state.get('chunks'):
                if self.engine.publication(self.session_id,content) in ('refused','failed'):self.refused_attempt=attempt      # wave G: the material was refused (``EchoEngine.publication``): the turn stays open for what comes next, and when nothing else comes the watchdog ends it, once; the engine reads no text again at publication, so there is no «not a question after all»
                return []
            self.revision=state['revision'];self.source_id=tid;self.refused_attempt=None
        else:
            reply=self.engine.extend_answer(session_id=self.session_id,revision=self.revision,answer=prefix,final=final)
            if reply is None:return []
        first=not self.published;led=self.lead_said and self.published==self.lead_said and prefix!=self.lead_said;self.published=prefix
        if tid==self.fast_turn and self.fast_done:self._fast_took_back()
        return self._cue(reply,first=first)+(self._lead_passed() if led else [])
    # ---- the local source (cm-local-base folded into the route): the ONE place that says whether a ready local answer exists: the base and the laws, the bank, the code (a figure), the owner's prepared answers, the listener's own volatile data
    def _reference(self,text):
        """Wave G: the answer of the local reference base (``reference_kb.lookup``: exact, instant, no network) to ``text``, or None. W5: and of the bank (``instant``); the two that differ are no answer."""
        history=self.call_questions()
        context=self._followup_of(text,history)      # g31: «а счёт 62» after «Счёт 51 активный или пассивный?» is that question; «а пример» is nothing the bank has: it would say the old answer
        if context is not None:
            if not context.bank:return None
            text=context.bank
        try:
            hit=reference_lookup(text,history,**({'prepositions':True,'tails':True} if self.fast_call else {})) or (self._figure(text) if self.quick_math else None) or None
            bank=self.instant.lookup(text,bank_only=True) if self.instant is not None else None
            if MORE_DETAIL.search(text):return None       # the owner's call of 06.11: «подробнее про 51 счёт» got the same one line four times: the model answers it, with the material
            if bank is not None and hit is not None and bank.answer!=hit and not instant.same_fact(bank.answer,hit):return SOURCES_DIFFER      # c22 (NC4): two sources, two answers: neither is taken; the listener is told so, once, at once
            return (bank.answer if bank is not None else hit) or self._prepared(text,history) or self._personal_reply(text) or None
        except Exception:
            logger.warning('echo-sync reference base failed: the question goes the usual way')
            return None
    def _reference_read(self,text):
        """The ONE reading of what the reference base answers to a final: the whole of it, else the last clause (``_reference_tail``). Every road that asks the base about a final reads it here (the open question, the model's delegation that came first, the hold of a remark)."""
        return self._reference(text) or self._reference_tail(text)
    def _reference_tail(self,text):
        """h30, the call of 21:16: the cloud cut the head off, «, предприятия, понятия, страховой риск»: the base knew the term, the model took 7 s; «Сколько будет семь плюс три? Сколько будет семь плюс три»: the sum,
        said twice, is no sum. What the base answers in the last clause of a final, of two words at least, is the answer: the clause the cloud itself set apart, whatever came before it."""
        parts=[part for part in re.split(r'[.,](?!\d)|(?<!\d)[.,]|[?!…;:]',str(text or '')) if part.strip()]      # h31: «1,5» is one number, not a clause
        if len(parts)<2 or len(norm_words(parts[-1]))<2:return None
        tail,head=parts[-1].strip(),' '.join(parts[:-1])
        again=_stems(head) and len(_stems(head)&_stems(tail))*2>=len(_stems(head))      # the same thing said twice
        cut=all(len(norm_words(part))<=TAIL_HEAD_WORDS for part in parts[:-1])      # scraps of a head the cloud lost: a head that says something of its own is the job's to judge
        if not again and (not cut or any(key.startswith('#') for key in _protected(_atoms(head)))):return None
        hit=self._reference(tail)
        return None if hit and self.quick_math and hit==quick_answer(tail) and not quick_asked(tail) else hit
    def _figure(self,text):
        """Q1, the skeptic: what code works out of ``text``. A figure reads all that was said, unlike a reference: with no word that asks for it, this soon after the final before it, it may be the rest of that breath, the cloud
        having cut it in two («Раздели» | «Сто на пять» is no 500): no hit, the model's 2 s."""
        answer=quick_answer(text)
        user=self.ledger.latest_user()
        floor=self._ear_floor(user['id']) if answer and user else None
        return None if floor is not None and self.clock()-floor<FIGURE_HEAD_SECONDS and not quick_asked(text) else answer
    def _prepared(self,text,history=None):
        """W2: the owner's prepared answer to ``text`` (``prepared_answers``), after the base and the code; None when none."""
        if self.prepared is None:return None
        return self.prepared.lookup(text,self.call_questions() if history is None else history)
    def _personal_reply(self,text):
        """c22 (N135): a question about the listener's OWN data that changes (an account, the weather where they are, a calendar, a parcel) has no answer in any base and no source anywhere: the short honest reply of
        personal_volatile.py is the answer, as a local one, at once (before: the E88 path, 8 s and «Не нашёл»). Any other text: None.
        w3 n2_h06 step 5: the listener's finals of the last ``EAR_PILE_SECONDS`` are the parts of the same question («я ложусь в одиннадцать» | «вставать в шесть» | «сколько часов сна у меня получится»):
        a number given in them makes it a task, the model's to work out."""
        now=self.clock()
        before=[(self.ledger.snapshot(tid) or {}).get('text') or '' for tid,when in self.user_done_at.items() if now-when<=EAR_PILE_SECONDS]
        kind=personal_volatile(text,before)
        return honest_reply(kind) if kind else None
