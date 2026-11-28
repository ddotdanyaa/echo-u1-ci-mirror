"""Control adapter over existing EchoEngine and Conduit provider turn events.

No microphone, model client, TTS engine or server. Side effects are actions for
the existing media transport. A source result is provenance, not a truth proof.
"""
# cm-split: assembled by tools/split_controlled_media.py (re-run it, do not edit the generated head by hand)
from .cm_base import (ABANDON_FINALS, Abbreviations, ABANDON_SHARE, ACK, ACK_JOIN_FRAGMENTS, ACK_JOIN_SECONDS, ACK_STABLE_SECONDS,
    ANSWER_CAP_SECONDS, ANSWER_GRACE_SECONDS, ANSWER_STEMS, ANSWER_WAIT_SECONDS, ANSWER_WORDS, ASKED_AGAIN_FEW_STEMS, ASKED_AGAIN_STEMS,
    ASK_ANSWER_STEMS, ASK_ANSWER_WORDS, AcceptCtx, BACK, CALL_SETTINGS, CLOSED, COMMAND_SAID, CONFIRM_SECONDS, CONVERSATION_GAP_S, CORRECTION,
    CUE_SYNTHESIS_SECONDS, CUE_TAIL_SECONDS, CallDictation, ConversationLedger, DICTATION_START_SECONDS, Decision,
    EAR_ANNOUNCE_MAX_SECONDS, EAR_ANNOUNCE_SLACK_SECONDS, EAR_ASK_HOLD_SECONDS, EAR_BIND_SECONDS, EAR_COMMAND_SETTLE_SECONDS,
    EAR_FINAL_SECONDS, EAR_FIRST_BIND_SECONDS, EAR_JOIN_GAP_SECONDS, EAR_JOIN_PIECES, EAR_PIECE_GRID_MS, EAR_PIECE_SECONDS, EAR_PILE_SECONDS,
    EAR_RELEASE_SILENCE_SECONDS, EAR_SAID_PIECES, EAR_SPEECH_SECONDS, EAR_START_SLACK_MS, EAR_STRONG_FORMS, EAR_TAIL_SILENCE_SECONDS, EAR_TAIL_WORDS,
    ECHO_MIN_LAG_SECONDS, EchoEngine, FAST_HEAD_WORDS, FAST_MARK_SECONDS, FAST_TAIL_SECONDS, FAST_TURN, FIGURE_HEAD_SECONDS, FIGURE_STILL_SECONDS,
    FIRST_HOLD_CAP_SECONDS, FIRST_HOLD_SECONDS, FIRST_TEXT_S, FUNCTION_WORDS, FlowAhead, FramelessTurns, GATE_TALK, GREETING,
    HANDED_BACK_WAIT_SECONDS, HEARING_SECONDS, HESITATION_WORDS, HISTORY_EXCHANGES, HOLD_BOUNDS, INPUT_CLOCK_SLACK_MS, InputMeter, JUDGE_RULES,
    LANDMARK_SECONDS, LEDGERS_KEPT, LIVE_MIN_WORDS, LONG_TALK_WORDS, LOOKUP_ANSWER_WAIT_SECONDS, LOOKUP_WAIT_SECONDS, MAX_AUTO_REPEATS,
    MAX_RESTARTS, MAX_TURN_CHARS, MERGE_PATIENCE_SECONDS, MONOLOGUE_OTHERS, MONOLOGUE_QUIET_SECONDS, MORE_DETAIL, NEXT, NO_AFTER_CUE_SECONDS,
    NO_ANOTHER, NUMBER_DOUBT, NUMBER_PREMISE, NUMBER_TRUSTS, NUMBER_WORDS, OPEN, OTHER_LANGUAGE, OWNER_SILENCE_S,
    PACE_HELP_SECONDS, PACE_QUIET_SECONDS, PARTIAL_STABLE_SECONDS, PLAYED_FRESH_S, PREPARE_MIN_WORDS, PREPARE_WORDS, Pace, Path,
    PauseLearner, QUESTION, QUESTION_WORDS, QUIET, READ_USER_WINDOW_S, CONTEXT_AGE_S, RECORD_PAUSE_SECONDS,
    REFUSAL, REFUSE_BEFORE_DROP_SECONDS, REMARK_REASONS, REPEAT, REPEAT_SAID, REPLAY, RESTART_ANCHOR_GAP, RESTART_DECIDE_WORDS,
    RESTART_MAX_WORDS, RESUME, Resolutions, SAID_ALREADY_SHARE, SAID_BACK_SHARE, SEGMENT_IDLE_SECONDS,
    SILENT, SOURCES_DIFFER, SPEECH_LEADS, SPEECH_STARTS, SPEECH_WORDS, SPLIT_JOIN_SECONDS, STAMPED_SLOTS, STOOD_MORE_STEMS, STOP, STOPWORDS,
    SequenceMatcher, Stamped, StreamingAnswer, TAIL_HEAD_WORDS, TEMPO_ANNOUNCE_SECONDS, TEMPO_BLANK, TEMPO_BLANK_WORDS, TEMPO_FILLER_SECONDS,
    TEMPO_FRAGMENT_WORDS, TEMPO_HOLD_SECONDS, TEMPO_PAUSE_SECONDS, TEMPO_SEEKING, TEMPO_START_SECONDS, TEMPO_STEP_SECONDS, TEMPO_TEXT_SECONDS,
    TEMPO_TWICE_SECONDS, TRY_FINAL_SECONDS, TURN_MAP_CAP, TURN_MAP_KEEP, TurnLang, UNANSWERED_KEPT, UNANSWERED_MIN_WORDS,
    UTTERANCE_FIX_WORDS, UTTERANCE_TAIL_WORDS, WITNESS_SLACK_SECONDS, WORDS, WRONG_REPEAT_SECONDS, _ABBREVIATIONS, _AFTER_ANCHOR, _AFTER_SCALE,
    _ASKS_A_CAUSE, _ASKS_A_NUMBER, _ASKS_A_PLACE, _ASKS_A_PURPOSE, _CHATTER_WORDS, _CYRILLIC, _ENDS_SENTENCE,
    _FIX_ONLY, _FIX_OPENER, _FIX_START, _FOR_THE_BRAIN, _GROWS,
    _HEAD_TERMINATOR, _HESITATES, _HYPHENS, _INVERTS, _JOINS, _LEADING_MARKS, _LEAD_PREPOSITION, _LEDGERS, _MAY_ANSWER, _MOVED_ON, _NOT_THIS_BUT,
    _NO_EVIDENCE, _NO_HEADS, _NO_REAL, _NO_SUBSTANCE, _NO_WORDS, _OPENING_MARKS, _OPTIONAL_LEADING, _OPTIONAL_STEMS, _ORDER_SHAPE,
    _PROPER_NAME, _QUOTE_START, _REQUEST_STEMS, _REQUEST_WORDS, _SAYS_A_PLACE, _SAYS_A_PURPOSE, _SCALE_STEMS, _SERVICE, _SIGNS,
    _SPOKEN_SENTENCE, _STALLS, ATTEMPT_REASONS, _UNITS, _WORD_PROBLEM_END, _YES_NO_HEADS, ATTEMPT_REASONS, _UNNAMED_SUBJECT, _atoms, _by_value, _chatter, _complete, _content, _ends_in_number, _holds_a_number, _last_sentence_words, _lemma,
    _like_a_try, _number_grows, _proper_name, _protected, _protected_word, _rest_end, _retelling, _retold_conflict, _said_within, _nouns,
    _segment_start, _stems, _valued, _values, about_itself, adds_nothing, _source_conflict,
    answer_conditions, answer_keeps, asked_of, asked_tail, asks_again, asks_for_more, asks_in, brain_answer, brain_command,
    caught_up, collections, command_ruling, compact_opening, complete_followup, conversation_map, definition_body, destutter,
    doubtful_what, doubts, drop_process_sentences, ear_disputes, ear_foreign, early_command, ends_like, first_cue, first_match,
    fold_asr, gate_decide, going_on, going_verdict, hearing_repair, honest_reply, instant, ipaddress, is_confirmation_tag, is_followup,
    is_repeat_request, landmark, landmark_command, lang_counts, lead, lead_row, lead_splice, logger, logging, match_current, most_said,
    CHANGES, route_need, norm_words, normalize, not_addressed, of_the_answer, pause_split, personal_volatile, privacy_gate, probe, progress_note, public_sources, question_key, quick_answer, quick_asked, quick_stated, re,
    reads_out, reads_text, reason_of, recall_parse, recall_resolve, reconnect_note, reference_lookup, reference_preload, remark_ruling,
    resolve, resume_window, revises, rule_verdict, said_share, said_within, same_question, same_start, says_a_number, shares, stable_prefix, stale_slots, stem, strip_process_prefix, stumble_place, sys,
    tail_progress, talks_about_itself, threading, time, two_witnesses, unhedged, unmarked, urlsplit, uuid,
    whole_portions, why_journal, wide_refusal, without_repeats, witness_rule, word_problem, written_to)
from .cm_kind import KindMixin
from .cm_question import QuestionMixin
from .cm_answer import AnswerMixin
from .cm_portion import PortionMixin
from .cm_timers import TimersMixin
from .cm_speech import SpeechMixin
from .cm_memory import MemoryMixin
from .cm_route import RouteMixin


class Mode:
    """One mode of the call, read from the call's resolved settings (``ControlledMedia.modes``, one ``settings.resolve`` of ``settings``) and from nowhere else: the host, ``fast_text.for_call`` and ``ear_shadow.for_call`` no longer copy a profile value onto the controller.
    ``needs``: the name of an attribute that must be set by then (the channel a job runs in); assigning writes the value into ``settings`` (a harness or a test switches a mode the way the profile does)."""
    def __init__(self,key,*,value='on',needs=None):self.key,self.value,self.needs=key,value,needs
    def __get__(self,obj,cls=None):
        if obj is None:return False
        return obj.modes[self.key]==self.value and (self.needs is None or getattr(obj,self.needs,None) is not None)
    def __set__(self,obj,on):
        obj.settings[self.key]=self.value if on else 'off';obj.modes=resolve(obj.settings)


class ControlledMedia(KindMixin, QuestionMixin, AnswerMixin, PortionMixin, TimersMixin, SpeechMixin, MemoryMixin, RouteMixin):
    # U20-S4: the deferred slots remember the epoch they were armed in (see ``_new_epoch``)
    repeat_at=Stamped('epoch',None)
    resume_repeat=Stamped('epoch',False)
    go_on=Stamped('epoch',None)
    @property
    def reopened(self):return self.quiet_reopen and not self.call_issued and not self.owners      # new-call-plan: the ONE rule of a call just reopened: the saved position is no playback authority until a cue of THIS call has been made, or the cloud has answered in THIS call (an assistant turn is in ``owners``): that answer made its own plan
    def reopen_lets(self,kind):return not self.reopened or kind in ((REPEAT,ACK) if self.reconnect_kept else (REPEAT,))      # ... and then only the listener's explicit repeat (and, after a drop of the line kept by ``_begin_call``, the ACK of it) may present it
    cloud_up=True         # U58: the wire says when the cloud fell (``enter_local``) and came back; without it no hold waits for the cloud's word
    cued_mark=None        # U58: (revision, index, question id, when) of the cue made last: what a held cue is checked against at its release (``held_cue``)
    go_ahead=Stamped('epoch',None)
    went_on=Stamped('epoch',None)
    tempo_hold=Stamped('epoch',None)
    tempo_start=Stamped('epoch',None)
    portion_tries=Stamped('epoch',None)

    @property
    def settings(self):return self._settings
    @settings.setter
    def settings(self,value):self._settings=value;self.modes=resolve(value)      # a call's settings are resolved ONCE per assignment; every mode of the call reads ``modes``

    def __init__(self,path,*,session_id,settings=None,repeat_seconds=None,source_delivery='marker',session_context_fallback=False,lookup_policy='always',first_useful_gate=False,coalesce_seconds=0,clock=None,quiet_reopen=False,max_auto_repeats=MAX_AUTO_REPEATS,answer_grace_seconds=ANSWER_GRACE_SECONDS,ack_join_seconds=ACK_JOIN_SECONDS,ack_join_fragments=ACK_JOIN_FRAGMENTS,cue_tail_seconds=CUE_TAIL_SECONDS,ack_stable_seconds=ACK_STABLE_SECONDS,segment_idle_seconds=SEGMENT_IDLE_SECONDS,answer_wait_seconds=ANSWER_WAIT_SECONDS,lookup_wait_seconds=LOOKUP_WAIT_SECONDS,lookup_answer_wait_seconds=LOOKUP_ANSWER_WAIT_SECONDS,answer_cap_seconds=ANSWER_CAP_SECONDS,confirm_seconds=CONFIRM_SECONDS,fast_text=None):
        self.settings=settings or dict(CALL_SETTINGS)      # ONE resolve of the call's settings (``modes``): the ``Mode`` flags below read it
        self.session_id=session_id
        self.engine=EchoEngine(path,self._generate,settings=self.settings)
        self.convo=None;self._convo_cue=None;self._convo_n=0;self._convo_ans=None;self.memory_began=None      # _convo_ans: (revision, answer id) of the last answer row; memory_began: M1-e2
        self.ledger=FramelessTurns(max_chars=MAX_TURN_CHARS,keep=self._active_turn_ids,sink=self._ledger_turn);import os.path as _osp;_dir=str(path) if _osp.isdir(str(path)) else _osp.dirname(_osp.abspath(str(path)));self.resolutions=Resolutions(path=None if str(path)==':memory:' else _osp.join(_dir,'resolutions.json'));self.owners={};self.seen=set()
        self.epoch=(self.state() or {}).get('revision',0);self.nonce=uuid.uuid4().hex
        # A stream still open in the database was left by a call that ended: its producer is gone and nothing in this controller will
        # ever extend it. Close it, or the listener's repeat of the last portion there is waits for more text for ever. (Nothing is
        # spoken by this: a reopened call stays quiet until an explicit repeat or a new question.)
        left=self.state()
        if left and left.get('streaming') and left.get('stream_turn_id') and type(left.get('revision')) is int:
            self.engine.extend_answer(session_id=session_id,revision=left['revision'],answer=left['answer'],final=True)
            logger.info('echo-sync decision kind=answer reason=left_stream_closed revision=%s',left['revision'])
        # ``question_tail``: the part of the question the classifier was given when the listener said it after a portion the stable partial had
        # already confirmed (``_early_tail``); ``question_text`` is then the whole utterance, and the engine is told which part is the verdict's.
        # Also what the listener said when the verdict asks something else: a corrected request («Нет, я спрашивал про X»: X is asked, and X
        # alone is no question for the engine - INTEG7, T-A C04).
        self.question_id=None;self.question_text='';self.question_tail='';self.sources=[];self.published=''
        self.said_log=collections.deque(maxlen=8)      # the ONE log of what was said lately: (time, text, is_a_cue): the last questions and cues (a final made of them opens nothing, ``_said_back``; U15-S9: the cues of it are the text a final may only read aloud)
        self.portion_tries=None       # (position, what the ear heard of it after the cue): a try counts (``_try_went``)
        self.go_on=None               # the position a try has done: the next portion goes at the next tick, no timer
        self.go_ahead=None            # c23: the next portion the same try said whole, word for word: confirmed with it, the one after it is cued
        self.went_on=None             # g17: (position, portion, the tries, when) a try went on from: the cloud's final of it is taken (``_try_final``)
        self.question_part=''     # H7 item 0: what the judgements by words read (``_part``)
        self.question_reason=''   # the classifier's reason for the current question ('topic_change': W1F-B C6, ``_old_tail``)
        # W1F-B (C2): bare self-correction openers said after the question (``_continuation``), as (turn id, text, when its final came),
        # and the question they belong to: the correction they announce is joined with them.
        self.pieces=[];self.pieces_of=None
        # W1F-B (C5): user turns that are not the question and nothing the listener said to the prompter about the portion (a bystander,
        # small talk, speech the classifier could not place), and the assistant turns that followed one of them while the answer was cut
        # mid-sentence (``_continues_cut_answer``): such a reply is «not this answer» unless it goes on with the cut sentence. Bounded.
        self.foreign_turns={};self.foreign_replies={}
        self.candidate=None;self.local_answer=False;self.refused_attempt=None     # wave G: _take_candidate, _publish_reference, the publication refusal in _source
        # G3 (the arbiter, see _hold_question): the plan an admission took over, {'entry': its history entry} (the entry keeps the portions and how far
        # the listener got), and the missing tail last cued for the waiting portion, (position, text, whether it really began to play).
        self.suspended=None;self._cue_tail(None);self.plan_told=None;self.said_wrong=False
        self.confirm_seconds=max(0.0,float(confirm_seconds))
        try:reference_preload()       # the first question costs no import: its cue comes in the tick of its final
        except Exception:logger.warning('echo-sync reference base could not be preloaded')
        # W1F-B (C2, sc01): the last QUIET finals said in a row, each begun within ``coalesce_seconds`` of the one before, as (turn id, text,
        # when it began, when its final came): the pieces of a question cut into short finals (``_joined_question``). Bounded.
        self.quiet_pieces=[]
        self.expiry_armed_for=None   # W1F-B (C4): the open turn whose stalled words let the hearing expiry arm the timer (``_expire_hearing``)
        self.answer_head=None   # (question id, id of the first assistant segment of its answer): see _interrupted_head
        self.lookup_query=''   # what the lookup of the current question asks (the question, with the topic of a follow-up): DEF-T-11
        self.lookup_served=False   # DEF-T-B15: a lookup runs for the model's own delegation on the model-knowledge route
        self.search_refused=False   # F3: the transport refused the lookup of this question (it is personal): no source can ever back its answer
        self.source_missing=False   # c8: the lookup gave no source (failed, timed out, unrelated rows): the model answers from memory, hedged
        self.refused_lookup=False   # F3 round 1: ... and it needs verification, and nothing public is left of it: it stays unanswered (no lookup to wait for)
        self.reconnect_kept=False   # F3 round 1: begin_call kept the waiting portion of a call that was cut a moment ago: its repeat and its ACK work
        self.answered_delegations=[]   # F3 round 1: the delegation items that have had their result (one result per item, whatever happens to the question)
        self.revision=None;self.grounded=False;self.blocked=set();self.source_id=None;self.parts_asked=set()      # E51: the asks of a compound question already taken up (``_open_part_due``): each once
        self.answer_marker=''
        if source_delivery not in {'marker','delegation'}:raise ValueError('Unknown source delivery')
        self.source_delivery=source_delivery;self.delegation_id=None;self.early_delegations={};self.reads_ahead={}
        self.session_context_fallback=session_context_fallback is True
        if lookup_policy not in {'always','required'}:raise ValueError('Unknown lookup policy')
        self.lookup_policy=lookup_policy;self.direct_content=False
        self.context_requested=False;self.delivery_ready=False
        self.user_boundaries={}
        self.delivery_anchors={}
        self.delivered_transport=None
        self.retired_assistants=set()
        self.source_segment_id=None;self.source_segment_prefix='';self.closed_source_segments=set()
        # Task E3c (see MAX_RESTARTS): the restart being weighed (an assistant segment that began a new sentence after a cut one), where in
        # a segment's text the answer goes on (a restart is used from the end of what it retold of the part the listener has heard), the
        # spoken text of the portions a restart continues, and how many restarts this question has had.
        self.pending_restart=None;self.segment_offsets={};self.restart_base=None;self.restarts=0
        self.pending_start=None;self.joined_segments=set()   # the signal of the segment being weighed; segments decided to be joined
        self.corrected=False   # DEF-T-B01: the answer of this question was corrected («Поправка: …») and is not followed any more
        self.frontier_since=None   # ((revision, index), since when) the listener waits at the frontier of an open stream: _stalled_stream
        self.repeat_seconds=max(1,float(resolve(self.settings)['repeat_seconds'] if repeat_seconds is None else repeat_seconds));self._arm(None)      # one value (settings.resolve) unless the host gives the profile's
        # See HEARING_SECONDS. ``hearing`` is a property: it expires by itself.
        self._hearing=False;self._heard_at=None
        # A cue was issued and the transport has not reported its end (or it was cancelled): nobody knows the portion is over.
        self.cue_outstanding=False
        # DEF-ACK-20: [first PCM frame, last voiced sample + margin] of the cue that is, or was last, in flight (an ESTIMATE from the
        # moment it was issued until the transport reports its first frame: ``_cue_playing``); whether that cue has REALLY begun to be
        # played (only then can it be heard back) and where the input audio was at its first frame (ms of the transport's count); and when
        # each user turn was ANNOUNCED (the time of its first non-final event: the provider announces a turn after the speech began).
        self.cue_tail_seconds=max(0.0,float(cue_tail_seconds));self.cue_window=None;self.announced_at={}
        self.cue_heard=False;self.cue_input_ms=None;self._input_clock=None
        self._cue_open=None;self._cue_subs=[]      # X-CUE: the one cue that has begun and not ended yet, and who listens to its life
        self._convo_open(path)      # U14-S4: with ``conversation_ledger`` off nothing is made
        self.input_probe=None;self.subscribe_cue(self._input_cue);self._input_logged=None      # U17-S4: the input meter (made at its first event; the repeat gate always obeys it)
        self.turn_lang=TurnLang();self._lang_seen={};self._lang_logged={};self.lang_gated=0;self.ear_lexicon=None      # U19-S3: the language of the turn (the cloud's finals) and the ear gate; ``ear_lexicon``: the words the Russian ear knows (a set or a predicate), None = every Cyrillic word
        self.audible_ms=None;self.audible_of=None     # T11 (E52): ``_audible`` of the last answer's first cue, and the revision it was taken for
        self.portion_heard=None      # A1-F6: ((revision, index), input ms) of the portion when it was first heard on this call
        # L1: (turn id, its partial text, since when it has been what it is) of a partial that already confirms the portion; 0 = off.
        self.ack_stable_seconds=max(0.0,float(ack_stable_seconds));self.partial_ack=None
        # Task E, ruling 3: the turns the stable partial has taken, as ``(state before the confirmation, epoch, when)``: their FINAL is
        # still classified for what was said after the portion (``_early_tail``). Bounded.
        self.early_taken={}
        self.resume_repeat=False
        # G5: auto-repeats of the current portion since the listener was last heard (see tick).
        self.max_auto_repeats=max(0,int(max_auto_repeats));self.auto_repeats=0;self.auto_repeat_of=None
        # x-cap: the counters of the one cap (see ``_silence``): the repeats of speech the meter could not place; the owner's turn (``auto_repeats=0``) zeroes all
        self.unconfirmed_repeats=0;self.unplaced=False
        self.record_seen=None      # u18-s3: ``(revision, {indices})`` the owner went on from in this answer (``_record_progress``)
        # c8b (see ABANDON_SECONDS in timer_policy): the waiting portion's {'at': position, 'since': first cued, 'engaged': the listener's last try, 'capped': the
        # auto-repeat that spent the cap, 'others': finals of other speech since the later of the two}, and how long other speech may go on.
        self.abandon=None
        self.first_useful_gate=first_useful_gate is True;self.abbrev=Abbreviations()      # c22 (N136): what the call spelled out of the profile's table (abbrev_state)
        self.coalesce_seconds=max(0,min(5,float(coalesce_seconds)))
        self.clock=clock or time.monotonic;self.user_done_at={};self.user_started_at={};self.speech_ended={}
        self.quiet_reopen=quiet_reopen is True;self.call_issued=False;self.input_signature=None;self.input_changed_at=None;self.quiet_checked=None
        self.question_clock=None;self.held_source=None
        # G3: (assistant turn id, when) of a provider-final turn whose text lacks terminal punctuation, waiting out the grace window.
        self.answer_grace_seconds=max(0,float(answer_grace_seconds));self.unsettled=None
        # When each assistant turn ended (the grace window counts from there), and the segment the flush has declared the end.
        self.turn_done_at={};self.settled_segment=None
        # When each assistant turn last did anything (created, delta): the idle watchdog (ruling 5) counts from there.
        self.segment_idle_seconds=max(0,float(segment_idle_seconds));self.activity_at={}
        # ACK-split: what the listener has said since the current portion started and nothing was done about: finals that
        # were only attempts, as (portion position, text, when it arrived). See ``_joined_repeat``.
        self.ack_join_seconds=max(0,float(ack_join_seconds));self.ack_join_fragments=max(1,int(ack_join_fragments))
        self.fragments=[]
        # DEF-FAULT-03 (see ANSWER_WAIT_SECONDS): the epoch of a question the transport has already told the listener about (a failed
        # lookup), when the sources of the current question were handed to the transport (queued), and when the helper last
        # acknowledged a frame of them (``*.context.appended``: the real delivery to the cloud).
        self.answer_wait_seconds=max(0.0,float(answer_wait_seconds));self.lookup_wait_seconds=max(0.0,float(lookup_wait_seconds))
        self.lookup_answer_wait_seconds=max(0.0,float(lookup_answer_wait_seconds));self.answer_cap_seconds=max(0.0,float(answer_cap_seconds))
        self.diagnosed_epoch=None;self.diagnostic_at=None;self.delivered_at=None;self.context_appended_at=None
        # R-EAR-ACT (see EAR_JOIN_GAP_SECONDS): for the local ear, when each of its utterances began and where the call stood then (uid ->
        # (when, ``_ear_mark``)), its last pieces, a verdict that waits for the cloud to announce its utterance, the utterance it took last,
        # and when it last heard speech begin.
        self.ear_started={};self.ear_pieces=[];self.ear_pending=None;self.ear_take=None;self.ear_onset_at=None
        # Fix round 1, item 4: ONE switch for all of the ear's acting (``_ear_safely``): set by its first failure, for the rest of the call.
        self.ear_off=False;self._ear_taking=None;self.ear_tail=None;self.ear_tail_taken=None      # u54: the ear's partial text whose tail matched the waiting portion; the one taken on it
        # w5-flow: the next portion released ahead of the end of the repeat (flow_ahead.py); only with an acting ear, whose peeks it reads
        self.flow=FlowAhead(duplex='half') if self.modes['local_ear']=='act' else None      # always with an acting ear (a rule of the controller, no key): the ear's text so far is what it reads
        self.flow_uid=None;self.flow_take=None
        # H4: what the ear may open and has not yet (``_ear_first``), what it heard lately, and the look at the job prepared on a text (``FastText.prepared``, set when the ear acts).
        self.ear_first=None;self.ear_said=[];self.prepared_job=None;self.unanswered=[]
        self.witness_born={};self.witness_seen=set();self.witness_cases=[]      # the answer witness: when each reply of the cloud began, those it has looked at, its verdicts of this call
        self.ear_ended=None        # H7 item 1: the last offset the ear reported, acting or not (the journal of the jobs)
        self.job_begun=lambda:False    # ``fast_text.for_call`` sets it
        self.prepare_wide=False    # H7: set by ``fast_text.for_call``, like ``prepared_job``
        self.lead_said=''          # W5-lead: the lead published for the open question (``_lead_cue``); BRAIN's text is spliced after it
        self.wide_breath=[];self.wide_no=0        # H7 item 4: what the ear heard of the breath it is in: ``(offset, text)``, and its number
        # H3 (TEMPO_*): the detector of the ear (``tempo_speaking``, when speech last began and ended), its utterances by uid (when each began and what waited then), the uid whose text has not come,
        # the pieces of what was said to the portion that waits, the start that stopped ``(position, what is missing, when)``, the hold ``(position, offset)`` and when the timer last spoke.
        self.tempo_speaking=False;self.tempo_began=None;self.tempo_ended=None;self.tempo_spans={};self.tempo_awaits=None
        self.pauses=PauseLearner()      # one-research EOT-RU: the speaker's own pause inside a turn; the wait of a closed question follows it (``_release_wait``)
        self.tempo_pieces=[];self.tempo_others=None;self.tempo_start=None;self.tempo_asked=None;self.tempo_hold=None;self.tempo_spoke=None;self.tempo_cut=None
        # H5 item 2: the pieces of speech with content, ``(end, text)``, no final has said yet (``_tempo_judged``): nobody has judged them. Item 6: when the run of speech the ear hears last began (``_ear_went_on``).
        self.tempo_unjudged=[];self.tempo_run=None;self.tempo_said_end={};self.tempo_contradicted=None      # c24-a1: final -> (where the speech it says ended, its marks): ``_said_after``
        self.rule_helped=None
        self.dictating=CallDictation(self.convo,self.clock)      # c22-repeat / c24-c: dictation said by voice, the owner's tempo of writing; a reconnect of the same session goes on at the tempo learned (the session's ledger holds them)
        self.pace=None;self.pace_key=None      # W5 (``prompt_pace``): this listener's pauses, and the portion they are told (``_pace_due``)
        # H6 item 6: when speech with content last ended, since when a first cue is held, and (its text, when) of the ear's text that stood in for a final.
        self.tempo_content=None;self.first_since=None;self.first_hold_from=None;self.ear_stood=None;self.ear_finals=0;self.cloud_heard=None
        # c9-numveto: the cloud's acknowledgements that advanced a portion (turn id -> (state before, epoch, when)), for a verdict of the ear that comes later.
        self.cloud_acks={}
        # H1, H2 (the text channel, fast_text.py; the profile's ``fast_text`` = "on"): the release asked of the channel for the current question as
        # (question id, id of the turn its text becomes), the turn that owns the answer (``fast_turn``: the cloud's turns of the question are ignored
        # by ``_source``), whether the channel is done with this question, and the text it has said so far. Off: none of this is ever touched.
        self.fast_on=(self.modes['fast_text'] if fast_text is None else fast_text)=='on';self.fast_n=0;self.fast_asked=None;self.fast_turn=None;self.fast_done=False;self.fast_said=''
        # H2: the answer in play when the question opened (rule 4), the topic before it, its verdict, the question the job declined, the one handed to the cloud, when this call began.
        self.fast_played=None;self.fast_topic='';self.question_kind=None;self.fast_declined=None;self.fast_handed=None;self.handed_asks=None;self.call_began=None
        # H2: the candidate the job declined, and (the final that replaced it, its text, when it was taken, the candidate) when a final came before the job had ruled on the one before it. H5: (text, when taken) of the last it ruled out.
        self.fast_passed=None;self.fast_left=None;self.fast_head=None
        # H5 item 7: the route of the question's job, and the question whose job has had its second chance.
        self.fast_route=('model',{});self.fast_retried=None
        # H6 item 3: what the job is asked of the open question when that is not the final as it stands, and the job that waits for the rest of a final on an open tail.
        self.fast_text='';self.fast_tail=None
        self.fast_mark=None     # H6 item 5: a command that waits for the end of speech: {'uid', 'word', 'job', 'at'}
        self.speech=None        # H6 item 10: the prepared speech of this call: {'text', 'entry': its history entry once it has opened}
        self.fast_call=self.fast_on       # stays when the channel is lost: the cloud's text is then dictated by the same filter (rule 7)

    TURN_MAPS=('owners','seen','blocked','user_boundaries','announced_at','user_done_at','user_started_at','turn_done_at','activity_at','early_taken','retired_assistants','witness_born')

    _answer=None      # B: bound by ``_bind_answer`` and by nothing else: (the answer, the turn that publishes it, the epoch, the engine revision)

    def state(self):
        """The engine's state, read; with the floor of the call (``call_began``) when a call began anew: the one place every reader of «what was asked before» gets it (``engine.asked_of``)."""
        state=self.engine.state(self.session_id)
        if isinstance(state,dict) and self.call_began is not None:state['call_began']=self.call_began
        return state

    # S0 fix round 1: the flag was set by the transport's own ear alone (``local_onset``), the cloud having said nothing of it (yet).
    _heard_locally=False
    tempo_live=False       # H3: the local ear runs and keeps the tempo (``ear_speech``)

    # ---- night-gate, step 1: the ONE place for what cannot be taken back -----------------------------------------------------------------------------------------------
    # Whatever cuts the sound, resets a portion, closes or supersedes a question, retires an answer or moves the reply token asks ``_act``. Nothing else calls ``_new_epoch``,
    # ``_cancelled`` or ``engine.retire``, clears ``question_id`` or builds the transport's «cancel»: tests/test_night_gate_lock.py counts the places by the AST, zero outside.
    # ``ACTS`` is closed data: reason -> (act, the steps in the order they run, may it be taken back, does it need a confirmed witness). Steps: ('epoch', the word ``_new_epoch`` is
    # told), ('timers',) the repeat timer, ('cut',) the cue is cut here, ('clear', fields) to ``QuestionSlot.CLOSED``, ('clear_own', fields) the same only for what is of the question being closed (its ``id``),
    # ('retire', the engine's word), ('note',) what that retire left unsaid is told to the model, ('wire',) the transport is told to cut. What a closing clears differs from site to site
    # ON PURPOSE (a stop keeps the answer, an abandon drops the suspended plan too): step 1 keeps every set and every order as it stood on 671d2fe, row by row; nothing is unified.
    ACT_WIRE='cancel'
    ACT_KINDS=('cut_sound','pause','reset_portion','close_question','supersede','speak')
    ACTS={
        # only the sound
        'speech_started':('cut_sound',(('owner',),('cut',),('wire',)),True,False),      # the listener began to speak: the transport cuts a playing cue off - over a cue, only the owner's near voice does (U52, the step 'owner')
        'revision_replaced':('cut_sound',(('cut',),),True,False),      # a restart or a rewrite replaced the portion heard last: its cue is stale, the new cue takes the audio over
        # the portion: its cue is void or the step is taken back (``engine.rewind``, the site's own); the question stays
        'early_ahead':('reset_portion',(('epoch','early_tail'),('cut',),('wire',)),False,False),      # the next portion was said whole ahead of its cue
        'early_doubt':('reset_portion',(('epoch','early_tail'),('cut',),('wire',)),False,False),      # words of doubt after what looked like a repeat: the step went back
        'flow_withdrawn':('reset_portion',(('cut',),('wire',)),True,False),      # a release ahead is withdrawn
        'ear_overruled':('reset_portion',(('cut',),('wire',)),True,False),      # the cloud's final overrules the confirmation the ear took
        'ear_number_veto':('reset_portion',(('cut',),('wire',)),True,False),      # the ear heard another number than the cloud confirmed
        'v5_stale':('reset_portion',(('epoch','v5_stale'),('timers',),('cut',),('retire','utterance_continued'),('wire',)),False,False),      # the answer gate: prepared for another form of the question, asked again
        # the listener's «стоп»: the answer is paused and kept (today the reply token moves too); with nothing kept the question closes (``stop_closes``)
        'stop':('pause',(('epoch','accept_user'),('timers',),('cut',),('clear',('held_source',)),('wire',)),False,False),
        'stop_closes':('close_question',(('clear',('question_id','grounded','unsettled','settled_segment','_answer')),),False,False),
        # the question closes
        'provider':('close_question',(('epoch','provider'),('clear',('question_id','grounded','held_source','unsettled','settled_segment','_answer')),('timers',),('cut',),('retire','revised_nonquestion'),('wire',)),False,False),
        'move_on':('close_question',(('epoch','accept_user'),('timers',),('cut',),('retire','move_on'),('clear',('question_id','grounded','held_source','unsettled','settled_segment','_answer')),('wire',)),False,False),
        'drop_question':('close_question',(('epoch','drop_question'),('clear',('question_id','grounded')),('timers',),('cut',),('clear',('held_source','unsettled','settled_segment','refused_attempt','_answer')),('clear_own',('candidate',)),('wire',)),False,False),
        'abandon':('close_question',(('epoch','abandon'),('timers',),('cut',),('retire','abandoned'),('clear',('question_id','grounded','held_source','unsettled','settled_segment','abandon','suspended','_answer')),('wire',)),False,False),
        'going_on':('close_question',(('epoch','going_on'),('clear',('question_id','grounded')),('timers',),('cut',),('clear',('held_source','unsettled','settled_segment','_answer')),('wire',)),False,False),
        'new_call':('close_question',(('retire','new_call'),('clear',('_answer',))),False,False),      # ``begin_call``: a stale answer an earlier call left waiting
        'ear_first_overruled':('close_question',(('retire','ear_first_overruled'),('clear',('_answer',))),False,False),      # what the ear opened was no question: its answer retires, then the question drops (``drop_question``)
        # a new question takes the place (step 3: only this row asks for a confirmed witness); what stood before it retires in the same decision
        'open_question':('supersede',(('epoch','open_question'),('clear',('_answer',)),('timers',),('cut',),('wire',)),False,True),
        'new_question':('supersede',(('retire','new_question'),('note',)),False,False),      # the answer before it retires as interrupted, what was left unsaid is noted for the model
        'utterance_continued':('supersede',(('retire','utterance_continued'),),False,False),      # it was the answer to an unfinished version of the same question: nothing of it is noted
        # the sound: the cue is made here and nowhere else; the wire and the callers ask whether a cue is still the one, whether the held one goes, whether a service phrase may sound. No journal line of the gate for these (the site of the decision writes its own)
        'cue':('speak',(('speak',),),True,False),
        'authorized':('speak',(('authorized',),),True,False),
        'held':('speak',(('held',),),True,False),
        'may_sound':('speak',(('may_sound',),),True,False),
    }

    # ---- M6: the steps of the gate. ``STEPS`` is closed data too: verb -> ``fn(self, ctx, step)``. ``ctx`` is what one entry knows: ``by`` (the site), ``basis``, ``closing`` (the question being closed), ``args`` (what the caller gave
    # ``_act`` besides the basis: the cue, the text), ``actions`` (what the transport is told) and ``stop`` (a head step that says 'stale' or 'park' ends the entry before anything is done). A row names the verbs in the order they run; a
    # verb nobody has defined is the verdict 'unknown' and nothing of the row is done. A new row or a new verb is a line of ``ACTS`` / ``STEPS``: the body of ``_act`` does not change (tests/test_m6_act_steps.py).
    def _step_owner(self,ctx,step):
        """U52, the head step of ``speech_started``: over a cue that plays only the owner's near voice cuts it (the gate's witnesses: near_voice level, the echo of the cue, own_voice print); in silence anybody's speech does. No gate: as ever."""
        gate=getattr(self,'speaker_gate',None);ask=getattr(gate,'cuts_cue',None)
        if ask is None or not self._cue_playing(self.clock()):return
        try:barges=bool(ask())
        except Exception:return
        if not barges:ctx['stop']='park'      # a witness that says it is not the owner stops this cut
    def _step_epoch(self,ctx,step):self._new_epoch(step[1],ctx['by'])
    def _step_timers(self,ctx,step):self._arm(None);self.resume_repeat=False
    def _step_cut(self,ctx,step):self._cancelled()
    def _step_clear(self,ctx,step):
        self.slot.close(*step[1])      # what a closing leaves is ``QuestionSlot.CLOSED``: the one table
    def _step_clear_own(self,ctx,step):      # fix5: only what is of the question being closed; a candidate of a NEWER turn (its speech ended after, its job flying) is not dropped with the older question (w3 n2_d06 step 2: the third part's job was killed by the second part's 8 s)
        for name in step[1]:
            held=getattr(self,name)
            if not isinstance(held,dict) or held.get('id') in (None,ctx['closing']):self.slot.close(name)
    def _step_retire(self,ctx,step):ctx['left']=self.engine.retire(self.session_id,step[1])      # what the engine's history says is left unsaid of the answer it retires: of this entry only, no state of the controller
    def _step_note(self,ctx,step):self._queue_note(ctx.get('left'))
    def _step_wire(self,ctx,step):
        action={'type':self.ACT_WIRE,'epoch':self.epoch};ctx['actions'].append(action);ctx['wired']=action
    def _step_authorized(self,ctx,step):
        """Is ``cue`` the one the plan waits for now? What the wire and the callers ask before a sound: a cue of another reply token, nonce or revision, or of a portion the cursor has left, is 'stale'."""
        cue=ctx['args']['cue'];state=self.state()
        if not (state and cue.get('nonce')==self.nonce and cue.get('epoch')==self.epoch and cue.get('revision')==state['revision']):ok=False
        elif state.get('completed'):
            # Only «повтори» after the last portion may speak a completed answer: its last portion, while that answer is current.
            ok=(cue.get('replay_last') is True and state.get('replay_last')==state['revision'] and cue.get('index')==len(state.get('chunks') or ())-1)
        else:ok=bool(cue.get('index')==state['chunk_index'] and (not state.get('stream_waiting_next') or cue.get('replay') is True))
        if not ok:ctx['stop']='stale'
    def _step_held(self,ctx,step):
        """U58: the wire releases the cue it held. 'do': it goes. 'stale': nothing is said. Made for another question than the one open now it is not said over it; what the listener said meanwhile
        (finals since it was made, ``fragments``) is the portion already (``most_said`` / ``ends_like``): dropped, the next portion comes from the cursor (``go_on``)."""
        cue=ctx['args']['cue']
        mark=self.cued_mark
        if not mark or mark[:2]!=(cue.get('revision'),cue.get('index')) or cue.get('replay_last'):return
        if mark[2]!=self.question_id:
            logger.info('echo-sync decision kind=silent reason=held_cue_of_an_old_question revision=%s',mark[0]);ctx['stop']='stale';return
        where=self._position(self.state())
        said=probe('strip_fillers',' '.join(text for place,text,when in self.fragments if place==where and when>=mark[3]),settings=self.settings).value
        if said and (most_said(said,cue.get('text') or '') or ends_like(said,cue.get('text') or '')):
            logger.info('echo-sync decision kind=next reason=held_cue_said_meanwhile revision=%s index=%s',mark[0],mark[1]);self.portion_tries=(where,[said]);self.go_on=where;ctx['stop']='stale';return
        return
    def _step_may_sound(self,ctx,step):
        """The transport asks, once, before the first frame of a sound that is no cue of the plan (``what``: 'say', a service phrase; a cue has ``authorized``). The rule: a service phrase never sounds over a cue of the open question that is still playing (the cue is the answer the listener waits for; the phrase would talk over it). Otherwise yes."""
        if self.question_id and self._cue_playing(self.clock()):ctx['stop']='park'      # a cue whose sound has begun; one still in synthesis or one that failed is no sound to talk over (``controlled_synthesis_failed`` is spoken)
    def _step_speak(self,ctx,step):
        """The one place a cue is made: ``text`` of the portion the cursor waits for, ``first``: the first cue of an answer (H5 item 2, ``first_cue_hold``). Only ``_act('speak', 'cue')`` gets here."""
        text,first=ctx['args']['text'],ctx['args'].get('first',False)
        if not text or text==SILENT:return
        self.said_log.append((self.clock(),text,True))
        self.call_issued=True;self.cue_outstanding=True
        state=self.state();self._arm(None);self.resume_repeat=False;self.tempo_hold=None;self.hold_cause=None      # U57: the cue ends the hold it was under
        now=self.clock();self.cued_mark=(state.get('revision'),state.get('chunk_index'),self.question_id,now);self.cue_window=[now,now+CUE_SYNTHESIS_SECONDS+self._spoken_estimate(state)+self.cue_tail_seconds]
        self.cue_heard=False;self.cue_input_ms=None   # nothing of it is audible until the transport reports the first frame
        # ``replay``: spoken again at the live frontier of a streaming answer (the listener has confirmed all the text there is and
        # asks to hear the last portion once more): the frontier waits, and that must not make this one cue unauthorized.
        if state.get('completed') and state.get('replay_last')==state['revision'] and state.get('chunks'):
            # «Повтори» after the last portion (engine: repeat_of_the_last_portion): the last portion once more.
            ctx['actions'].append({'type':'speak','text':text,'epoch':self.epoch,'nonce':self.nonce,
                     'revision':state['revision'],'index':len(state['chunks'])-1,'replay':False,'replay_last':True,**({'first':True} if first and self.tempo_live else {}),**self._end_of(True)});return
        if self.flow is not None:
            chunks=state.get('chunks') or [];index=state.get('chunk_index')
            nxt=chunks[index+1] if type(index) is int and index+1<len(chunks) else None
            self.flow.cue(text if text==probe('waiting_portion',state=state).value else '',nxt if text==probe('waiting_portion',state=state).value else None,now)
        ctx['actions'].append({'type':'speak','text':text,'epoch':self.epoch,'nonce':self.nonce,
                 'revision':state['revision'],'index':state['chunk_index'],'replay':bool(state.get('stream_waiting_next')),**({'first':True} if first and self.tempo_live else {}),
                 **self._end_of(not state.get('streaming') and state['chunk_index']==len(state.get('chunks') or ())-1)})
    STEPS={'owner':_step_owner,'epoch':_step_epoch,'timers':_step_timers,'cut':_step_cut,'clear':_step_clear,'clear_own':_step_clear_own,'retire':_step_retire,'note':_step_note,'wire':_step_wire,
           'authorized':_step_authorized,'held':_step_held,'may_sound':_step_may_sound,'speak':_step_speak}

    def _cue(self,text,first=False,unless_spoken_over=False):
        """The callers of the families ask the gate through this name. ``unless_spoken_over`` (c24 P07, seed 293: the cue of a local request («продолжай», «дальше») whose final comes while the owner already says the next utterance):
        the plan moves, the cue waits for the silence after it (the tempo, ``resume_repeat``; a question there retires it), never parked to sound as that utterance's answer."""
        if first and unless_spoken_over:self.first_since=None;self.first_hold_from=None      # a plan said again waits for the speech going on as a first cue does: its hold starts afresh (``first_cue_hold``)
        if unless_spoken_over and text and text!=SILENT and self.hearing:
            logger.info('echo-sync decision kind=silent reason=cue_waits_newer_speech');self._arm(None);self.resume_repeat=True;return []
        return self._act('speak','cue',text=text,first=first)[1]
    def authorized(self, cue):
        if 'qid' in cue and self.question_id is not None and cue['qid'] != self.question_id:
            return False
        return self._act('speak', 'authorized', cue=cue)[0] == 'do'
    def held_cue(self,cue):return None if self._act('speak','held',cue=cue)[0]=='do' else []      # U58: None: it goes; []: it is stale
    def may_sound(self,what,basis):return self._act('speak','may_sound',what=what,told=basis,basis=(None,None,None,basis[3]) if basis and len(basis)>3 else None)[0]=='do'      # U62: the ticket only: the token also moves for reasons that are no other question

    def _act(self,act,reason,*,basis=None,by_reflex=False,**args):
        """night-gate: the ONE entry of what cannot be taken back, and of every sound. ``act``, ``reason``: a row of ``ACTS`` (closed: an unknown pair raises). ``basis``: ``(reply token, plan revision, turn id, ticket)`` (the ticket, the fourth element, is the question slot's ticket)
        at the moment the evidence appeared; None: this very event; an element None: not stated. ``by_reflex``: done at once and judged by nothing (step 4). ``args``: what the steps of the row read (the cue, the text).
        Returns ``(verdict, actions)``: 'do' | 'park' | 'stale' | 'unknown' (a verb of the row nobody has defined: nothing is done), and what the transport is told. Only 'do' is carried out (one journal line, ``why_journal.act``,
        but none for the acts of sound: their sites write the decision line); the caller is told the verdict and does the rest."""
        kind,steps,_,_=self.ACTS[reason]
        if kind!=act:raise ValueError(f'night-gate: {reason} is a row of {kind}, not of {act}')
        if args and kind!='speak':raise TypeError(f'night-gate: {reason} is a row of {kind}, it takes no argument but basis and by_reflex (got {sorted(args)}: a misspelled basis would skip the stale check)')
        # the site, for the journal: ``_drop_question`` is a name of this gate, the site is its caller (as ``why_journal.epoch_drop`` read the frames before the gate stood here)
        by=sys._getframe(2 if reason=='drop_question' else 1).f_code.co_name
        verdict='do' if by_reflex else self._act_verdict(reason,basis)
        if verdict=='do' and any(step[0] not in self.STEPS for step in steps):verdict='unknown'
        ctx={'by':by,'basis':basis,'closing':self.question_id,'args':args,'actions':[],'stop':None,'wired':None,'left':None};done=verdict=='do'
        if done:
            for step in steps:
                self.STEPS[step[0]](self,ctx,step)
                if ctx['stop']:verdict,done=ctx['stop'],False;break
        if ctx['wired']:self.__dict__.setdefault('_act_wires',collections.deque(maxlen=8)).append((ctx['wired'],act,reason,by))
        if kind!='speak':why_journal.act(self,act,reason,by,basis,verdict,did=int(done),epoch=self.epoch,**({'reflex':1} if by_reflex else {}))
        return verdict,ctx['actions']

    def _new_epoch(self,reason,by=None):
        """The one place the reply token moves (U20-S3); night-gate: called by ``_act`` only (``by``: the site that asked the gate). ``reason`` is the word of the row.
        U20-S4: a deferred slot armed under the old token is stale now. A rule of the timer owner, always: one ``timer_stale`` line and the slot is cleared."""
        self.epoch+=1
        if getattr(self,'facts_why',False):why_journal.epoch_drop(self,reason,by)      # V5 step 0 (b): journal only
        stale=stale_slots(self)
        if stale:
            logger.info('echo-sync timer_stale slots=%s epoch=%s reason=%s',','.join(stale),self.epoch,reason)
            for name in stale:setattr(self,name,STAMPED_SLOTS[name])
        return self.epoch

    def _cancelled(self):
        """The transport cuts the audio off now: no cue is playing any more, and nothing of it can be heard after the margin."""
        if self._cue_open:self._cue_event('cut',self._cue_open[1],why='cancelled')
        self.cue_outstanding=False
        if self.cue_window:self.cue_window[1]=min(self.cue_window[1],self.clock()+self.cue_tail_seconds)

    job_asked=None      # c16: ``FastText.asked_of``

    _go_armed=None;ear_words_at=None      # U108 (2): (position, since) of a matched portion that waits for its next one; when the ear last wrote words

    prepared=None         # W2: ``prepared_answers.PreparedAnswers`` (controlled_host sets it): the owner's list and the long cache are a hit of the base too
    instant=None          # W5: the call's ``instant.Instant`` (controlled_host, ``instant`` = "on"): a bank question is a hit of the base too, and the ear's partial text may open it (``ear_partial``)

    number_asked=None      # Fable 10.11: (the two numbers, when) of the last clarification: it is asked once

    reference_wait=None      # g14: (question id, the base's answer): a hit on a final that ends on a number that can still grow
    reference_armed=None      # g14: when it was held (the slot of the DEADLINES row ``reference``)

    ear_asked=None      # c24 P16: when the ear last heard a question (``_ear_heard``)

    asked_over=None      # c25-a: (revision, start) of a question the ear heard begin after a cue of that plan

    ear_asked_input=None      # c25-a: (input ms of its start, text) of the last question the ear heard

    # ==== CL2: going on (ruling 4 + amendment A) and the spoken progress for the model (ruling 5) ====================================
    # Class defaults of the state below (an instance sets its own): the note waiting to be sent, the epoch and the text of the last
    # one sent, and whether a note has just gone up and nobody has spoken since (note_guard_event).
    note_due=None;noted_epoch=None;noted_text=None;note_guard=False
    # W1F-B (TR-FRAG): (turn id, text, when) of the last request served locally (``_going_on``): a fragment of the same utterance joins it.
    local_request=None

    instant_cut_uid=None      # W13 item 2: the utterance whose bank hit was cut (one cut each)
    @property
    def ear_command_early(self):return self.modes['fast_text']=='on' and self.modes['local_ear']=='act'      # w10 item 11 (w8-donors N74): the rule of an acting ear with the text channel: «стоп» acts on the ear's text so far (a stop costs nothing the final would not do; ``ear_command``)
    early_stop_uid=None

    tempo_began_at=None      # c24: the portion that waited when the ear heard the speech begin
    veto_back=None      # c24 P11: ((revision, index) taken back by the ear's number, whether the next portion's cue had sounded)

    ear_lookup=Mode('ear_lookup')      # c22-speed (the profile's ``ear_lookup``): a question of the search route opens on the ear and the cloud's open turn (``_ear_opens_job``), the lookup starts then
    turn_mark=Mode('turn_mark')      # c22-speed (the profile's ``turn_mark``): ``_turn_reads`` takes a number closed by «?»/«!» at the end of the cloud's open turn as the cloud's
    cloud_form=Mode('cloud_form')      # c22-speed (the profile's ``cloud_form``): an ear's breath with no form opens a job when the cloud's open turn asks (``_ear_formless``, ``_cloud_asks``)

    witness_note=None     # ``FastText.note`` (``fast_text.for_call`` sets it): the line of the call trace; the answer witness reads the cloud's reply when it is set

    live_first=Mode('live_first',needs='job_asked')      # the profile's ``live_first`` (``fast_text.for_call``): the first cue goes before the final, on the cloud's input text, see ``_live_stable``

    ear_stood_open=None      # c23 (c22-break P09, chaos mid_portion seed 27): {'tid', 'text', 'at', 'declined'}: the ear stood in for the open turn of the cloud (``_ear_final_due``)

    tempo_contradicted=None      # c24-a1: the end of the ear's text the cloud's open turn contradicted (``_ear_final_due``), until a final

    _carry=None

    ear_job=Mode('ear_job',needs='job_asked')      # c16 (the profile's ``ear_job``, ``fast_text.for_call``): the job of the ear's breath opens the question before the final, see ``_ear_opens_job``

    job_piece_seen=None      # W13 item 4: (turn, content words) of the cloud's stable piece a job was last looked at for

    fast_handed_at=None      # c24 P18: when the question was handed back to the cloud (``_fast_hand_back``)
    fast_provisional=None    # F20: (job turn, end of the roads' sentence in its text) while that sentence stands as the answer and the job's real text has not taken its place

