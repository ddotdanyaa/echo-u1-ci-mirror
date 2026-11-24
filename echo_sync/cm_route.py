"""The route methods of ``ControlledMedia`` (cut from controlled_media.py by tools/split_controlled_media.py). Imports from cm_base, never from controlled_media."""
from .gate_text import public_address_allowed
from .cm_base import (CORRECTION, EAR_PILE_SECONDS, FAST_TURN, FIGURE_HEAD_SECONDS, MORE_DETAIL, QUESTION, SOURCES_DIFFER, StreamingAnswer,
    TAIL_HEAD_WORDS, _ENDS_SENTENCE, _atoms, _protected, _rest_end, _segment_start, _stems, compact_opening, honest_reply, instant, norm_words, personal_volatile,
    quick_answer, quick_asked, re, reference_lookup,
    definition_body, drop_process_sentences, first_cue, logger, says_a_number, stable_prefix, strip_process_prefix, unhedged,
    CHANGES, PublicationRefused, hedged, resolve, route_need, unmarked, probe)
from . import privacy_gate
from .reserve_text import NEXT_ROAD_S


class RouteMixin:
    def _generate(self,*args):
        bound=self._answer
        if bound is None:raise RuntimeError('Controlled content not authorized')
        answer,tid,epoch,revision=bound;state=self.state() or {}
        wanted=((args[3] if len(args)>3 else None) or {}).get('claim') or {}      # U94.2: args are (question, history, context, request, model) of ``EchoEngine._produce``; the claim is the turn and the revision it claimed
        if wanted.get('turn')!=tid or wanted.get('revision') not in (revision,revision+1) or state.get('pending_turn')!=tid or epoch!=self.epoch or state.get('revision')!=wanted.get('revision'):
            raise RuntimeError('Controlled content of another turn')      # a plain failure (outcome 'failed'), never ``PublicationRefused``: the turn is not tried again with another answer
        if isinstance(answer,StreamingAnswer) and not self._publishable(answer,*args[:2]):
            raise PublicationRefused('Unverified answer cannot publish a streaming prefix')      # the material is refused, not the turn (``EchoEngine.publication``): it is tried again with the text that may pass
        return answer
    @staticmethod
    def _publishable(answer,question,history):
        """cm-route, the ONE rule «may this text be published» (it was a second check of the engine at publication, on its own copy of ``route_need``): a question that needs a source (a lookup, ``route_need``) publishes only
        what the local reference base holds, a text with its sources (``source_backed``), or - when the lookup gave none (c8: ``unsourced``) - an answer from memory that says so (``hedged``) or has no number the question does not have
        (``says_a_number``: a rate, a sum or a date is never made up). A question that needs none publishes what the route handed over. The engine publishes what it is given: it reads no text for the route."""
        if not route_need(question,history) or answer.retrieval_status=='local_reference' or (answer.sources and answer.retrieval_status=='source_backed'):return True
        return answer.retrieval_status=='unsourced' and (hedged(answer.raw_text,question) or not says_a_number(str(answer),question))
    def prefetch_candidate(self,text=None):
        """Q1 / B9: ``text``: what the local ear heard of the cloud's open turn (``ear_prefetch``), judged by the very same rules as the cloud's partial (privacy included)."""
        user=self.ledger.latest_user()
        if not user or not user['valid'] or user['final'] or user['id'] in self.seen:return None
        if not public_address_allowed(user['text']) or (text is not None and not public_address_allowed(text)):return None
        decision=self._classify(text or user['text'],self._heard_with(self.state()))      # a reading of the shadow prefetch, through the one funnel and not counted: it is no row of the judge's final
        question=decision.question or text or user['text']
        if decision.kind not in (QUESTION,CORRECTION) or len(question.split())<3:return None
        if self._follows_on(question) or not self._lookup_routed(question):return None      # the route's one question «would it go to the public search» (``_lookup_routed``), not a copy of its rule
        if self._reference(question):return None       # the base or the code answers it: there is nothing to search
        return user['id'],question
    def without_source(self,epoch,why):
        """cm-route, the ONE rule «the question has no source and what is done then» (one place for the refusal before a lookup and the failure after it).
        ``why='delegated'``: the model's own request for sources (below). ``why='refused'``: the privacy gate refused the public lookup of this question (it is personal; F3 item 2), the listener is told nothing (it was «Ошибка. Повторите вопрос.»):
        - it does not need verification: the model-knowledge route, the model told by the result of its delegation that there is none (``_no_search_result``);
        - it needs verification (a rate, a code article, «сейчас»): the model's memory is no source. The first-person frame goes (``_impersonal``); if what remains is public the PUBLIC lookup
          runs on that (a ``lookup`` action; w10 item 1); if not, the job (H7, E88) is told there is no source and decides (talk is declined, data that changes is «Не нашёл»), and with no job the
          question stays unanswered (the watchdog's phrase) and the model is told NOTHING.
        ``why='failed'`` (c8): the lookup gave no source - it failed, timed out, or ``grounding`` kept no row. The listener is told nothing now: the question goes on to the model's own knowledge,
        HEDGED (the model is told so on the channel a finished lookup's result takes, ``_no_search_result``), recorded 'unsourced'. Data that changes (a rate, a sum, «сейчас», the current norm; candidate 8,
        ruling B) is never given from memory: ``None``, the transport says «Не нашёл» (``controlled_sources_unavailable``). So is a question of another epoch or one already grounded, and a transport that
        cannot tell the model (not the delegation, or no item and no session-context fallback).
        Returns the actions (maybe none) or ``None``: nothing to go on with (``failed``: the caller says «Не нашёл»; ``refused``: a question that has been replaced since)."""
        if epoch!=self.epoch or not self.question_id:return None
        # A quoted/extracted suffix may be public-looking even when the heard
        # utterance explicitly addressed a person. Do not reconstruct a public
        # lookup from that suffix in the no-source fallback.
        original=self.ledger.snapshot(self.question_id)
        if (not public_address_allowed(self.question_text)
                or (original and not public_address_allowed(original.get('text','')))):
            self.refused_lookup=True;self.search_refused=True
            return self._no_search_result()
        history=(self.state() or {}).get('history',());part=self._part();revision=(self.state() or {}).get('revision')
        if why=='delegated':
            # DEF-T-B15 (T-B N15; F3 item 4; Wave G): the model on the model-knowledge route itself asks for sources (its delegation) and waits for that tool result. Nothing to search - the base has answered, the job's answer is being said,
            # the question is personal (the public lookup never sees it) or a settled fact (``route_need`` empty) - its wait ends at once ("answer from your own knowledge", ``_no_search_result``) and no lookup runs. Otherwise the request is served
            # (the lookup, then the context on its delegation) while the model-knowledge route stays open; the sources delivered before anything was said make the answer a sourced one (``delivery_sent``).
            if self.local_answer:return self._no_search_result()
            if self.source_missing:return self._no_search_result(True)
            if self.fast_turn:return self._no_search_result()      # H2, H4: the job's answer is being said before the model's delegation or the final: the model still waits, nothing is searched
            if self.lookup_served or self.context_requested or not self.direct_content or self.published:return []
            if not (self.public_lookup_allowed(part,True) and self.public_lookup_allowed(self.lookup_query or part,True) and route_need(part,history)):return self._no_search_result()
            self.lookup_served=True
            logger.info('echo-sync decision kind=lookup reason=model_delegated revision=%s',revision)
            return [{'type':'lookup','epoch':self.epoch,'ticket':self.slot.ticket,'question':part,'lookup_question':self.lookup_query or part,'input_turn_id':self.question_id}]
        def from_memory(reason):
            self.source_missing=True;self.direct_content=True;self.lookup_served=True
            logger.info('echo-sync decision kind=lookup reason=%s revision=%s',reason,revision)
            return self._no_search_result(True)
        if why=='failed':
            if self.grounded or self.source_delivery!='delegation' or not (self.delegation_id or self.session_context_fallback):return None
            if CHANGES in (route_need(part,history),route_need(self.lookup_query or '',history)):
                logger.info('echo-sync decision kind=lookup reason=no_source_current_data revision=%s',revision)
                return None
            return from_memory('no_source_from_memory')
        if route_need(part,history) or route_need(self.lookup_query or '',history):
            rest=self._impersonal(part) or (self._impersonal(probe('question_part',part).value) if probe('question_part',part).value!=part else '')     # w10 item 1: the introduction («меня зовут Игорь…») stays home, the general question after it is looked up
            if rest:
                self.lookup_query=rest
                logger.info('echo-sync decision kind=lookup reason=personal_public_remainder revision=%s',revision)
                return [{'type':'lookup','epoch':self.epoch,'ticket':self.slot.ticket,'question':rest,'lookup_question':rest,'input_turn_id':self.question_id}]
            if self.fast_call and route_need(part,history)!=CHANGES:return from_memory('no_search_from_memory')     # H7 item 0: there is no search for it, the job is told so and decides: not 9.9 s of silence and «Нет ответа»
            if self.fast_call and privacy_gate.SEARCH_PERSONAL.search(part) and self.public_lookup_allowed(part):return from_memory('no_search_to_the_job')     # E88: what only the wider words keep from the search still reaches the job, told there is no source (BRAIN)
            self.refused_lookup=True
            logger.info('echo-sync decision kind=silent reason=personal_unanswerable revision=%s',revision)
            return []
        self.direct_content=True;self.search_refused=True
        return self._fast_release('model')+self._no_search_result()
    def _wire_predecessor(self,tid):
        """The assistant turn right before ``tid`` on the wire (the ledger's order of arrival), or None."""
        turns=self._wire_turns();ids=[t['id'] for t in turns]
        return turns[ids.index(tid)-1] if tid in ids and ids.index(tid)>0 else None
    def _wire_turns(self):
        """The cloud's assistant turns: a job's turn is in the ledger, it was never on the wire."""
        return [t for t in self.ledger.history() if t['role']=='assistant' and not t['id'].startswith(FAST_TURN)]
    def _source(self,turn,settled=False,stalled=False):
        """E22.3 (D-8, the owner: «двойные системы, тройные системы», one fast answer always): the job of the open question has said nothing for ``NEXT_ROAD_S`` (the very number at which the next road of the model is
        asked too: the cloud is one more road of the same race, not a second clock) and the cloud has text for it: the cloud's turn is weighed by the SAME judges as after a failure of the job (``_source_of``). A text they
        refuse is not said and the job is NOT touched (it may still answer; the watchdog's refusal stands behind it). Once a portion of the cloud's text has been published the job is let go the way a failed one is
        (``fast_feed`` 'failed', handed back), so that it never speaks over it and the rest of the cloud's answer is not held. A lead already said (``lead_said``) is not a portion of the cloud's text."""
        late=self._job_is_late(turn)
        before=self.published
        actions=self._source_of(turn,settled,stalled,release=late)
        if late and self.published!=before and self._fast_running():actions+=self._let_late_job_go()
        return actions
    def _job_is_late(self,turn):
        """E22.3: the job holds the cloud's turn (``_fast_holds``), has said nothing (no ``fast_turn``), and has been silent ``NEXT_ROAD_S`` since the question opened; the turn has text."""
        if self.fast_turn or not self._fast_running() or self.fast_declined==self.question_id or not (turn.get('text') or '').strip():return False
        if self.question_clock is None or self.clock()-self.question_clock<NEXT_ROAD_S:return False
        return self._fast_holds(turn['id'])
    def _let_late_job_go(self):
        self.fast_retried=self.question_id
        logger.info('echo-sync decision kind=answer reason=fast_text_late_cloud_stands_in revision=%s',(self.state() or {}).get('revision'))
        actions=self.fast_feed(self.fast_asked[1],self.fast_asked[0],'failed')[1]
        self.fast_handed=self.question_id;self.fast_handed_at=self.clock()
        return actions
    def _late_cloud_due(self,now):
        """E22.3, on the tick (the ONE place that weighs again, no timer of its own): a cloud turn that ended before the job was late waited (``_fast_holds``); once the job is ``NEXT_ROAD_S`` silent it is weighed here. A turn is weighed again
        only when its text has grown (``_late_weighed``): a refused text is not tried on every tick."""
        if self.fast_turn or not self._fast_running() or self.question_id is None:return []
        for turn in self.ledger.history():
            if turn['role']!='assistant' or not turn.get('valid') or turn['id'].startswith(FAST_TURN) or turn['id'] in self.retired_assistants or self.owners.get(turn['id'])!=self.question_id:continue
            mark=(self.question_id,turn['id'],len(turn.get('text') or ''))
            if mark in self.__dict__.setdefault('_late_weighed',set()) or not self._job_is_late(turn):continue
            self._late_weighed.add(mark)
            return self._source(turn,settled=bool(turn.get('final')))
        return []
    def _source_of(self,turn,settled=False,stalled=False,release=False):
        """``settled``: the grace window after this provider-final turn passed with no continuation (see ``_settle``). ``stalled``: the
        producer fell silent before this segment gave a first cue (``_rescue_first_cue``): the cue is chosen as when its turn is over."""
        tid=turn['id']
        if tid in self.retired_assistants or self.local_answer:return []
        if (not self.grounded and not self.direct_content) or self.owners.get(tid)!=self.question_id:return []
        if self._fast_holds(tid) and not release:return []     # H2, rule 1: a job runs for this question or owns its answer: the cloud's turns are set aside (``release``: E22.3, the job is late)
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
            if self.fast_call and not text:return self._fallback_refused(tid,'talk',final=(turn['final'] or settled) and not self._backchannel(turn['text']),late=release) or []     # H2: nothing is left of it: no hold of the question waits for that. H6 item 1: of a fallback that is a refusal
            told=tid!=self.fast_turn and self._said_already(turn['text'],self.question_tail or self.question_text)     # H2: the job declines with «—»; an answer said again is a doubt it confirmed: the one «already said» (``_said_already``)
            if told and not (turn['final'] or _ENDS_SENTENCE.search(turn['text'])):return []      # the first sentence is not over: it may yet be an answer
            if told:
                self.retired_assistants.add(tid);self.plan_told=self.question_id
                return []
        if self._holding(self.clock()):
            # The question may be unfinished, or is still being spoken or corrected: wait for its continuation, but only while one could
            # still be merged. tick() lets the answer out when that time is over, even if no further event arrives for it.
            self.held_source=tid;return []
        own=text
        if self.lead_said and text:
            text=self._lead_join(text,turn['final'] or settled)
            if text is None:return []
            spoken=True        # W5-lead: the text begins with the lead already said: no opening is stripped from it
        if self.first_useful_gate:
            if not spoken:text=compact_opening(text,self._part(),self.settings)
            text=self._spell(text)
        # c8 (C8 ruling): the model's hedge of an answer from memory («По памяти: …») is never cued - the listener repeats every portion
        # aloud in front of the examiner; none is added. The engine checks the model's own text for it (StreamingAnswer.raw_text).
        if self.source_missing and not spoken:text=unhedged(text)
        if not text:return []
        refused=self._fallback_refused(tid,'number',text,late=release)
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
            if turn['final'] and not final and tid!=self.settled_segment:self._end_open(tid,self.turn_done_at.get(tid,self.clock()))
        refused=None if self.published and self.published!=self.lead_said else self._fallback_refused(tid,'short',own,final,late=release)     # H6 item 1: «Да.» may still go on, while its turn does
        if refused is not None:return refused
        initial=None
        if self.first_useful_gate and not self.published:
            # The gate may wait for a better opening, never forever: once it is stuck or the producer's turn is over, the
            # ordinary first portion is spoken. Its unfinished last word is not, until the text is final (a segment can
            # stop in the middle of a word and the next one go on); a lone word waits for the grace flush (_settle).
            initial=first_cue(text,self._part(),self.settings,final=final,last=turn['final'] or stalled,patient=tid==self.fast_turn)
            prefix=initial or (text if final and tid==self.fast_turn else None)     # H2: the gate wants a better opening, but the job is over and this is the answer («Канберра.» to «… это Канберра»)
        else:
            prefix=self._stream_prefix(text,final,self.published,frontier=True)
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
            reply=self._reply(put,content,
                              decided=self._asked_ruling(put,'admitted_answer' if self.question_reason=='cloud_admitted' or tid==self.fast_turn or self._part()!=self.question_text else None,whole=self.question_text if self.question_tail else None),
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
    def _stream_prefix(self,text,final,committed,frontier=False):
        """The ONE reading of which part of the arriving text becomes portions now (``portioner.stable_prefix``; a final text goes whole), for the answer's stream and for a restart's segment. ``frontier``: F1 round 2 - a listener who has repeated everything published waits at the frontier, so an open meaning sentence lets its first planned portion go instead of holding them in silence until it ends; once that wait is as long as an idle segment takes to be flushed (the text trickles in), every complete word that arrived goes."""
        if final:return text
        state=(self.state() or {}) if frontier else {};waits=bool(state.get('stream_waiting_next'));since=self.frontier_since
        starving=bool(waits and since and since[0]==(state.get('revision'),state.get('chunk_index')) and self._idle_over(since[1],self.clock()))
        return stable_prefix(text,self.settings,committed=committed,eager=waits,starving=starving)
    # ---- the local source (cm-local-base folded into the route): the ONE place that says whether a ready local answer exists: the base and the laws, the bank, the code (a figure), the owner's prepared answers, the listener's own volatile data
    def _spell(self,text):
        """The ONE place where the profile's abbreviation table is spelled out in what the controller says (``abbrev_state``: once per call, again when asked); the text goes to the engine as spoken text, which never expands it again."""
        return self.abbrev.say(text,resolve(self.settings)['abbreviations'],self.question_id,self.question_text)
    def _reference(self,text):
        """Wave G: the answer of the local reference base (``reference_kb.lookup``: exact, instant, no network) to ``text``, or None. W5: and of the bank (``instant``); the two that differ are no answer."""
        history=self.call_questions()
        context=self._followup_of(text,history)      # g31: «а счёт 62» after «Счёт 51 активный или пассивный?» is that question; «а пример» is nothing the bank has: it would say the old answer
        if context is not None:
            if not context.bank:return None
            text=context.bank
        try:
            hit=reference_lookup(text,history,**({'prepositions':True,'tails':True} if self.fast_call else {})) or self._figure(text) or None
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
        return None if hit and hit==quick_answer(tail) and not quick_asked(tail) else hit
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
