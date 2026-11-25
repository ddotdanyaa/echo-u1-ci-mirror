"""U20-S1: every time constant of the call in one table, the relations between them in another, and a lock on the clock. Pure: reads the modules, changes nothing.

Why (proved, h31): the refusal waited 11 s where the controller drops the question after 8 s, and the apology turned into silence. Such a link lived in a comment only. Now:
  TIMERS     every module-level time constant (``module.NAME`` -> unit); ``unregistered()`` must be empty: a new constant of time is written here the day it is born (the lock counts, it lists no phrase);
  RELATIONS  R1-R13: the links between them and the owner's settings; ``validate(settings)`` returns the violated ones (hard = a defect, soft = worth a look);
  CLOCK_LOCK the state machines read the injected clock only: ``clock_calls`` finds a direct ``time.monotonic()`` by the AST.
A setting that is not there (a mechanism that has not arrived yet) skips its relation; a module that is not there is not scanned."""
import ast
import importlib
import re
from collections import namedtuple
from pathlib import Path

_DIR = Path(__file__).resolve().parent

# module -> its time constants. ``ms`` when the name ends in _MS, else seconds. Written from the scan: ``unregistered()`` is the check.
_BY_MODULE = {
    'arch_liveness': ('MIN_RUN_S',),
    'call_trace': ('LIVE_QUIET_S', 'FRAME_S', 'DUPLEX_MIN_CUE_S', 'DUPLEX_MIN_IDLE_S', 'MIC_HOLE_S', 'MIC_CUE_GUARD_S', 'MIC_DROP_S',),
    'call_audio': ('DRIFT_MS', 'MAX_FILL_MS',),
    'controlled_host': ('UPSTREAM_OPEN_TIMEOUT_S',),
    'conversation_ledger': ('PLAY_LAG_S',),
    'controlled_media': ('RECORD_PAUSE_SECONDS', 'MONOLOGUE_QUIET_SECONDS', 'TRY_FINAL_SECONDS', 'EAR_JOIN_GAP_SECONDS', 'EAR_ANNOUNCE_SLACK_SECONDS', 'EAR_START_SLACK_MS', 'EAR_BIND_SECONDS', 'EAR_PIECE_SECONDS', 'EAR_PIECE_GRID_MS', 'EAR_ANNOUNCE_MAX_SECONDS', 'TEMPO_STEP_SECONDS', 'PACE_QUIET_SECONDS', 'TEMPO_START_SECONDS', 'LANDMARK_SECONDS', 'TEMPO_TWICE_SECONDS', 'TEMPO_FILLER_SECONDS', 'TEMPO_PAUSE_SECONDS', 'EAR_FINAL_SECONDS', 'TEMPO_HOLD_SECONDS', 'FIRST_HOLD_SECONDS', 'TEMPO_ANNOUNCE_SECONDS', 'TEMPO_TEXT_SECONDS', 'EAR_RELEASE_SILENCE_SECONDS', 'EAR_TAIL_SILENCE_SECONDS', 'EAR_FIRST_BIND_SECONDS', 'EAR_PILE_SECONDS', 'PACE_HELP_SECONDS', 'FAST_TAIL_SECONDS', 'FAST_MARK_SECONDS', 'EAR_COMMAND_SETTLE_SECONDS',),
    'diagnostics': ('DIAGNOSTIC_FLUSH_S', 'PRERENDER_TIMEOUT_S', 'TARGET_SECONDS', 'MAX_SECONDS',),
    'ear_prefetch': ('EAR_FEED_WAIT_SECONDS', 'EAR_FEED_JOIN_SECONDS', 'EAR_FEED_SETTLE_SECONDS',),
    'ear_shadow': ('MAX_PENDING_S', 'MAX_UTTERANCE_S', 'VOICE_BUFFER_S', 'MAX_STREAM_S', 'FLOW_PARTIAL_MS',),
    'ear_sherpa': ('TAIL_PAD_S',),
    'fast_text': ('FIRST_TEXT_S', 'WHOLE_S',),
    'codex_road': ('CREDENTIALS_TTL_S', 'KEEPALIVE_S', 'PING_S', 'PING_TIMEOUT_S', 'DRAIN_S',),
    'flow_ahead': ('SYNTH_S', 'DOWN_S', 'PLAY_S', 'MIC_PACKET_S', 'EAR_SEEN_S', 'FLOW_TARGET_S', 'FLOW_AIM_S', 'MIN_PAUSE_S', 'LATE_MIN_S',),
    'helper_bridge': ('HELPER_WRITE_TIMEOUT_S', 'CLOSE_QUIT_S', 'CLOSE_KILL_S',),
    'input_state': ('NO_PACKET_GAP_S', 'DEAD_INPUT_S', 'ASR_GRACE_S', 'HALF_LISTEN_S', 'MIN_SPEECH_MS',),
    'instant': ('PARTIAL_MS',),
    'local_ear': ('FRAME_MS', 'ONSET_MS', 'OFFSET_MS', 'FLOOR_WINDOW_MS', 'ONSET_BUILD_TIMEOUT_S', 'CLOSED_MIN_S', 'CLOSED_MAX_S', 'PAUSE_MARGIN_S', 'ZERO_HOLD_MS',),
    'native_media_socket': ('SYNTHESIS_BUDGET_S', 'WRITE_RETRY_S', 'MIC_QUEUE_TRIM_MS', 'LOCAL_RETRY_FIRST_S', 'LOCAL_OPEN_GRACE_S', 'LOCAL_RETRY_EVERY_S', 'LOCAL_LINE_WAIT_S', 'LOCAL_HANDOVER_S', 'LOCAL_REPLAY_S',),
    'near_voice': ('FRAME_S', 'WINDOW_S', 'MIN_PIECE_SPEECH_S', 'MIN_PROFILE_SECONDS', 'OTHER_FIRST_HOLD_S', 'UNKNOWN_HOLD_S', 'OTHER_NEXT_HOLD_S', 'UNKNOWN_NEXT_HOLD_S', 'OTHER_RUN_CAP_S', 'JUDGE_EVERY_S',),
    'own_voice': ('MIN_SEGMENT_SECONDS', 'MIN_JUDGE_SECONDS', 'MIN_PROFILE_SECONDS', 'OWN_HOLD_S', 'JUDGE_EVERY_S', 'WINDOW_S',),
    'pace': ('CAP_SECONDS', 'TEXT_SECONDS',),
    'prosody': ('BRIDGE_MS',),
    'pcm_trim': ('LEAD_IN_KEEP_MS', 'MAX_SCAN_MS', 'MAX_TAIL_SCAN_MS', 'TAIL_KEEP_MS',),
    'reserve_text': ('REST_S', 'PRIMARY_QUOTA_REST_S', 'PRIMARY_FAIL_REST_S', 'FIRST_TEXT_S', 'NEXT_ROAD_S', 'ALL_DEAD_S', 'GIVE_UP_S', 'REFUSE_AFTER_S', 'SPENT_RACE_HOLD_S',),
    'reserve_search': ('SEARCH_S',),
    'timer_policy': ('EAR_ASK_HOLD_SECONDS', 'REPEAT_SECONDS', 'TEMPO_REPEAT_SECONDS', 'PREPARED_TTL_S', 'TRIM_EVERY_SECONDS', 'SPARE_MAX_AGE_S', 'WARM_GUARD_PERIOD_S', 'WARM_VOICE_IDLE_S', 'WARM_EAR_IDLE_S', 'WARM_EAR_PING_S', 'WARM_STEP_BUDGET_S', 'CUE_TAIL_SECONDS', 'CUE_SYNTHESIS_SECONDS', 'ECHO_MIN_LAG_SECONDS', 'INPUT_CLOCK_SLACK_MS', 'ANSWER_WAIT_SECONDS', 'LOOKUP_WAIT_SECONDS', 'LOOKUP_ANSWER_WAIT_SECONDS', 'ANSWER_CAP_SECONDS', 'REFUSE_BEFORE_DROP_SECONDS', 'FIRST_HOLD_CAP_SECONDS', 'HANDED_BACK_WAIT_SECONDS', 'ANSWER_GRACE_SECONDS', 'CONFIRM_SECONDS', 'WRONG_REPEAT_SECONDS', 'ABANDON_SECONDS', 'MERGE_PATIENCE_SECONDS', 'SEGMENT_IDLE_SECONDS', 'NO_AFTER_CUE_SECONDS', 'FIGURE_STILL_SECONDS', 'FIGURE_HEAD_SECONDS', 'PLAYED_FRESH_S', 'CONTEXT_AGE_S', 'PLAN_BACK_SECONDS', 'WITNESS_SLACK_SECONDS', 'READ_USER_WINDOW_S', 'ACK_JOIN_SECONDS', 'HEARING_SECONDS', 'ACK_STABLE_SECONDS', 'PARTIAL_STABLE_SECONDS', 'EARLY_LOOKUP_STABLE_SECONDS', 'OWNER_SILENCE_S', 'CLOUD_DEAF_S', 'SECONDS_PER_SYLLABLE', 'WAKE_TICK_S', 'LAG_PERIOD_S', 'LATE_CUE_S', 'LOCAL_READ_TIMEOUT_S', 'FAST_SIGN_IN_TIMEOUT_S', 'RECEIVE_TIMEOUT_S', 'EAR_SPEECH_SECONDS', 'QUIET_INTERVAL_S', 'COALESCE_SECONDS', 'ONSET_HOLD_MAX_S', 'LOOKUP_TIMEOUT_S', 'CONVERSATION_GAP_S', 'GENERATOR_HTTP_TIMEOUT_S', 'CLOSE_WAIT_S', 'PEER_WAIT_S', 'POLL_SLICE_S', 'SESSION_OPEN_S', 'DB_BUSY_S', 'SAPI_STARTUP_S', 'SAPI_IDLE_S', 'SAPI_REAP_S', 'SAPI_JOIN_S', 'CONVERSATION_CARRY_S', 'DICTATION_START_SECONDS', 'DICTATION_WORD_SECONDS', 'DICTATION_EXTRA_SECONDS', 'DICTATION_MIN_SECONDS', 'DICTATION_MAX_SECONDS', 'DICTATION_CYCLE_SECONDS', 'DICTATION_CYCLE_MAX_SECONDS', 'EDITION_STALE_S', 'SPLIT_JOIN_SECONDS', 'DIAGNOSTIC_MIN_INTERVAL_S',),
    'ws_transport': ('DRAIN_S',),
}
# THE AGES (census: cm-age-thresholds): how old a thing may be to count - every such number of the call, defined here, once; the controller, the transport and the settings read it, none writes its own. Growing order of what they age:
WITNESS_SLACK_SECONDS = 0.1   # ``answer_witness``: a reply of the question begins with its final, 20 ms after it on 6 Nov; one begun earlier is the tail of the reply before
FIGURE_STILL_SECONDS = 0.2    # A8-1: the cloud's partial is a witness of a figure only with its last word closed: a mark or a space after it, or no delta for this long (a token may stop inside «пять|десят»)
NO_AFTER_CUE_SECONDS = 1.5    # c25-a (the owner's live call): a short «нет» begun at most this long after the cue's end (or during it) rejects the portion; later it is speech of the conversation
SPLIT_JOIN_SECONDS = 1.0      # g14-split (the owner's calls of 06.11: «так характеристика счёт» | «пятьдесят два»): a text that ends on a number that can still grow (``_number_grows``) waits this long for the rest of it (the ear's open, the base's held answer: the DEADLINES row ``reference``): a wrong number is worse than a late one
FIGURE_HEAD_SECONDS = 3.0     # Q1, the skeptic: ``_figure``. A final comes up to 3 s after the end of its speech on the phone, two finals of one breath are as far apart as the second piece is long
ABANDON_SECONDS = 20.0        # c8b / lane A: a waiting portion falls asleep (is retired) once other speech has gone on this long since it was cued or tried (R12: no later than PLAN_BACK_SECONDS)
PLAN_BACK_SECONDS = 30.0      # H6 item 2 (N4): a plan goes on after a decline only when it was cued less than this ago (and no newer answer, and the listener was at it)
PLAYED_FRESH_S = 45.0         # R05-F1: how long the last answer stays «in play» for the finals that follow it (the job is shown it, and a doubt word may confirm it); unmeasured (UNMEASURED)
READ_USER_WINDOW_S = 60       # U15-S9: how far back the listener's own earlier finals count as the text that may be read aloud
CONTEXT_AGE_S = 120.0         # ONE age of the conversation's recent past (two numbers of 120 before): a declined utterance stays the next job's context, the disagreements of the two witnesses of a number count as repeated, and the cues played count as the text that may be read aloud, this long

# U108 (2): the longest the next portion waits, after the owner's word was heard and the portion matched, when the owner says nothing (no words, though the detector may say «speech»). One number for the lock; the owner's own figure is a laptop check.
OWNER_SILENCE_S = 3.0
# The deadlines of ``ControlledMedia`` that many of its methods read (cm-ack-join, cm-hearing-expiry, cm-stable-partial of the census): defined here, once.
ACK_JOIN_SECONDS = 10.0       # ACK-split: the fragments of one repeat of a portion are joined when the finals arrive not further apart than this
HEARING_SECONDS = 2.5         # «the listener is speaking» expires this long after the last sign of speech (DEF-FAULT-14)
ACK_STABLE_SECONDS = 0.15     # a partial transcript that fully matches the waiting portion and has not changed this long is the confirmation (L1 latency)
CLOUD_DEAF_S = 15.0          # the cloud closes a turn 0.3-2.3 s after the speech; w5-tail stalls of the network last up to 12 s: past that, nobody answers (the transport tells the listener once: controlled_upstream_stalled)
SECONDS_PER_SYLLABLE = 0.2    # how long one syllable of our voice takes: the length of a cue is its syllables times this (settings sec_per_syllable starts from it; the ledger's fallback for a cue whose voiced length is unknown reads it too)
PARTIAL_STABLE_SECONDS = 0.25  # H7: the cloud's partial that has stood this still with the ear silent is looked at and prepared (the same «partial stood still» rule, the prepare step)
EARLY_LOOKUP_STABLE_SECONDS = 0.5  # the cloud's partial that has stood this still starts the early lookup of a question (the same rule, the lookup step; the ear's own text needs no wait)

# THE SILENCE REPEAT (census: cm-tick, repeat-seconds-value): the wait before a portion is said again on its own, the ONE place of the value; settings.resolve takes it through ``repeat_wait``, the controller and pace read the result.
REPEAT_SECONDS = 6.0          # UX (the owner's call of 2 Nov had 3 s and 3 repeats): the calm default, one repeat after 6 s of silence (settings repeat_seconds, 1..60)
TEMPO_REPEAT_SECONDS = 2.0    # H3 rule 2: the default of ``repeat_seconds`` when the local ear keeps the tempo (local ear). H7 item 0: 3.5 until the owner's call of 5 Nov 10:27: «там ну максимум секунда две наверное должна быть перерыва»

# The values of the helpers that had them as literals (loop_guard): defined here, read there. ``controlled_host.WAKE_TICK_S`` is the same number until it imports this one (test_m5_tick holds them equal).
WAKE_TICK_S = 0.1             # the host wakes the tick at least this often: the ceiling for the deadlines that have no event
LAG_PERIOD_S = 0.01           # the loop-lag meter sleeps this long and records how late it woke
LOCAL_READ_TIMEOUT_S = 2      # the host's read of the owner's own files (the profile's settings, the call context, the whole material): a locked file or a dead drive counts as no file after this
FAST_SIGN_IN_TIMEOUT_S = 3    # H1: how long a job of the fast text channel waits for the profile's Codex sign-in (read on the loop's scoped executor)
RECEIVE_TIMEOUT_S = 65        # the longest silence on the phone's socket: the host hangs up on a phone silent this long
LATE_CUE_S = 1.5             # U57: a cue that comes later than this after the decision of the question writes its own decision row (cause and seconds)
EAR_SPEECH_SECONDS = 8.0      # one stretch of speech with no offset: the ear's detector is stuck after this (ControlledMedia's ear_detector hold and pace's voice flag both read it)
QUIET_INTERVAL_S = 3          # U20-S1: the input unchanged this long is a quiet interval (ControlledMedia.input_quiet_due reads it; the transport only reports the changes of the input)
COALESCE_SECONDS = 3.2        # a turn that began within this of the previous final of the utterance goes on with it (the host passes it to ControlledMedia; the observation event carries it)

# The windows and holds several modules read, defined here, once (census: socket-hold, socket-lookup-budget, reconnect-window, resume-window).
EAR_ASK_HOLD_SECONDS = 4.0     # c24 P16 (moved from cm_base, E43): a question the ear heard holds an older plan back from giving itself back for this long (the cloud's final of it is due); the ear's final is up to 3.7 s behind
ONSET_HOLD_MAX_S = 1.0        # the longest the transport's own ear alone holds a cue that is no first cue (a next portion, a replay)
DIAGNOSTIC_MIN_INTERVAL_S = 10      # cm-speech: at most one spoken diagnostic per this many seconds per session (from the START of the previous one; ``cm_speech.RATE_LIMIT_EXEMPT`` codes excepted)
LOOKUP_TIMEOUT_S = 8          # the public lookup for one question: after this the wire speaks its own phrase
CONVERSATION_GAP_S = 600.0    # the ONE window of the same conversation: a call opened at most this long after the newest record (the last portion spoken, the ledger's newest row) goes on with it: the waiting portion is kept (a redial after a drop of the line), the memory goes on, the resume window is this long
GENERATOR_HTTP_TIMEOUT_S = 120  # the private generator's HTTP client gives up after this
EDITION_STALE_S = 365 * 86400   # how old a law edition may be before the answer of the law base says its date (law_base reads it; was its own STALE_DAYS)
CONVERSATION_CARRY_S = 36 * 3600  # the ONE long window of the conversation: how far back the recap of earlier calls reaches, the memory kinds that outlive a call live, and an explicit «продолжай» resumes (no other utterance gets it)

# The bounds of the transports and helpers, defined here, once (census: socket-io-timers, synth-io-timers, host-timers): the module that waits imports the number, none writes its own.
CLOSE_WAIT_S = 5.0            # a closing thing waits this long for its peer to finish by itself (the call audio's writer, the journal's thread, the helper process)
PEER_WAIT_S = 30              # a transport waits this long for the answer of its peer (a frame of the helper, a request of the speech worker)
POLL_SLICE_S = 0.05           # one slice of a poll: a read waits this long at a time so that a cancel is seen at once; nothing wakes more often
SESSION_OPEN_S = 40           # the host opens the cloud's session (the exchange of the offer) inside this
DB_BUSY_S = 150               # the engine's database waits this long for a lock (seconds; the pragma reads the same number in ms)
SAPI_STARTUP_S = 8            # the speech worker has this long to say it is ready
SAPI_IDLE_S = 45              # a speech worker that nobody asked for this long is let go
SAPI_REAP_S = 1               # a stopped speech process is waited for this long, one step at a time
SAPI_JOIN_S = 2               # the supervisor's thread is joined this long on close

# The ages and waits of ControlledMedia that its judges read (census: cm-age-thresholds, cm-end-of-answer, candidate-timers, cm-coalesce, cm-tick): defined here, once; cm_base and settings import them.
# THE CACHE LIVES (census: cache-ttl): how long a stored thing is kept and how a warm part is watched, defined here, once; the cache, the ledger, the spare helper and the warm-up read these, none writes its own number.
PREPARED_TTL_S = 30 * 86400       # a record of the cache of prepared answers (prepared_answers)
TRIM_EVERY_SECONDS = 60.0         # W13 item 3: the background trim of the PCM cache walks the directory at most this often
SPARE_MAX_AGE_S = 1800            # a spare helper older than this is not taken (it is renewed at half of it)
WARM_GUARD_PERIOD_S = 5.0         # the warm guard looks at its resources this often
WARM_VOICE_IDLE_S = 60.0          # an idle voice worker / VAD pool is pinged after this
WARM_EAR_IDLE_S = 120.0           # an idle ear is pinged after this
WARM_EAR_PING_S = 5               # the ear's ping waits this long for it to be ready
WARM_STEP_BUDGET_S = 10.0         # the budget of a warm step that has none of its own
WARM_BUDGET_S = {'reference_kb': 1, 'classifier': 1, 'material': 1, 'instant': 20, 'voice': 2, 'vad': 1, 'ear_model': 30, 'model_road': 2}      # the budgets of the warm-up steps, by name

# THE ANSWER WAITS (census: cm-answer-watchdog, cm-end-of-answer): how long a question waits for its answer and its refusal, defined here, once; the watchdog, the refusal, the holds and the settings read these, none writes its own.
# DEF-FAULT-03: the cloud took the question and nothing usable came. After this long WITHOUT A SIGN OF LIFE the listener is told («Нет
# ответа. Повторите вопрос.») and the question is abandoned, so a late answer is never dictated. A sign of life is any event of an
# assistant turn that belongs to the question (created, grown, finished): every one restarts the count, because a cloud that is
# streaming is not silent however long its text takes to become a cue (Task E, ruling 1: counted to the first CUE, the watchdog gave up
# answers while they were arriving). The count starts at the FINAL of the question. 05_WORK/scripts/LATENCY_BASELINE.md, model route,
# p95 per stage: final -> assistant turn 82 ms, -> first useful phrase 3425 ms, synthesis 228 ms, publication + first PCM 49 ms: the
# slowest healthy first cue is about 3.8 s after the final. 8 s is 2.1 times that, and the same scale as the wire's 8 s lookup budget.
# 0 switches the watchdog off (constructor keyword).
ANSWER_WAIT_SECONDS=8.0
# A question that needs the public lookup is counted from the moment its sources REALLY reached the model (the last acknowledgement of
# the appended context frames, not the instant they were queued); while they have not, from the final plus this long
# (native_media_socket.LOOKUP_TIMEOUT_S, the lookup's own budget after which the wire speaks its own phrase).
LOOKUP_WAIT_SECONDS=LOOKUP_TIMEOUT_S      # one lookup bound: timer_policy.LOOKUP_TIMEOUT_S (the wire, this wait and the reserve search read the same number)
# The lookup route has its own budget of no sign of life, counted from the real delivery. LATENCY_BASELINE.md, lookup route: end of the
# question -> first PCM p95 12.6 s (old builds, N=15), and the sources are delivered 2.5 s or more after the final (lookup p95 2.7 s):
# the slowest healthy wait after the delivery is about 10 s, and the stalling opener the model says first is no cue (Task C). 20 s is
# twice that. The recorded runs of the review show the first useful text 5.6-8.1 s after the QUEUEING of the context.
LOOKUP_ANSWER_WAIT_SECONDS=20.0
# Whatever the cloud does, a question that has produced no cue is given up this long after its start (the final; for a lookup question
# the real delivery). Without it activity that never becomes a cue (chatter every few seconds) would put the report off for ever.
# It is checked before the controller's own windows too (the hold for a continuation of the question, the grace window, the idle wait of a
# continuation segment): a keep-alive less than SEGMENT_IDLE_SECONDS apart in a continuation segment would keep that last one open for ever
# (Task E2, ruling 4). Three times the slowest healthy wait of the lookup route (about 10 s after the delivery).
ANSWER_CAP_SECONDS=30.0
REFUSE_BEFORE_DROP_SECONDS=0.5      # U20-S6: the refusal of the fast channel is due this long before the watchdog drops the question (8.0 - 0.5 = final + 7.5)
FIRST_HOLD_CAP_SECONDS=ANSWER_CAP_SECONDS     # w3-integ (w2-own-voice): whatever holds a first cue (a job, a candidate, speech with content), not longer than this from the moment it began to hold it
HANDED_BACK_WAIT_SECONDS=4.0      # c24 P18: the cloud's silence after both jobs of a question failed and it was handed back: then the honest phrase (a sign of life restarts it)

# THE CUE WINDOW (census: cue-window): how long our own cue counts as playing and as audible back, defined here, once; the judges of the controller read it, none writes its own.
# «The listener is speaking» (``ControlledMedia.hearing``) holds back every cue and the repeat timer. It is set by anything that
# looks like a start of speech and was cleared only by an accepted final, so a start with no transcript (a cough, a VAD false
# start, the phone's ``response.cancel`` / ``input_audio_buffer.clear``, a retransmitted ``turn.created``) silenced the call for
# good (DEF-FAULT-14, DEF-STATE-02, DEF-ACK-19). It now expires this long after the last sign of speech (a start, or the growth
# of the transcript), and then the parked cue is played and the repeat timer runs again.
# The system's own voice must not confirm itself (DEF-ACK-20). A cue is «in flight» from the first PCM frame the transport sent
# until the last VOICED sample of the PCM plus this margin (the phone's playout buffer, Bluetooth): user speech that BEGAN inside
# that window and matches the portion is the cue heard back, not a confirmation. The window ends at the last voiced sample, not at
# the PCM end: every SAPI cue carries ~0.78 s of trailing silence, and a genuine fast repeat starts inside it.
CUE_TAIL_SECONDS=0.3
# Before the transport has reported the first PCM frame (or when it never does) a cue is taken to be in flight this long, plus the
# time the portion takes to say, counted from the moment it was issued: a lost cue must never block the listener for good. (Only for
# «is a cue being played»: ``_cue_playing``. The own-voice window below needs a cue that has REALLY begun.)
CUE_SYNTHESIS_SECONDS=1.5
# DEF-ACK-20, second round (Task E, ruling 2). The window above was judged on the instant the provider ANNOUNCES the listener's turn, and
# that comes after the speech began (0.3 s in the recorded session tests/fixtures/provider_user_turn_20261025.json; the review measured
# 0.9-2.3 s from the start of its probe audio). A listener who began to repeat before the silence timer's auto-repeat was therefore
# announced inside that repeat's window, the barge-in cut it, and the correct repeat was dropped as «own voice»: the cursor stood still
# and the portion came back for ever. So there is no drop: the decision is taken and logged (``reason=own_voice_suspect``, ``_own_voice_evidence``), the repeat is accepted. The
# evidence: the listener's REAL speech start (``start_ms`` of their turn on the provider's input-audio clock,
# against the position of the input audio at the cue's first PCM frame); where the provider does not carry it, the cue must have
# actually begun to play and the turn must have been announced at least ECHO_MIN_LAG_SECONDS after its first audio.
# The cue's own echo cannot be transcribed, hence announced, sooner than this after the cue's first audio (the review: 0.9-2.3 s, never
# under 1.26 s from the start of its probe audio).
ECHO_MIN_LAG_SECONDS=1.0
# The provider's ``end_ms`` is on the input-audio clock the transport counts only if it is not AHEAD of the audio that was sent (the
# provider cannot have heard what was never sent); this much slack for the counting and the 200 ms grid of the provider's clock. The
# recorded session: a turn is announced 0.12-0.33 s after the end_ms of its fragment.
INPUT_CLOCK_SLACK_MS=500

# Tunables of the controlled route. Constants for now; each is also a keyword of ControlledMedia (the lower-case name)
# whose default it is, so a later task can read them from the settings file without touching the logic.
# G3: how long to wait for a continuation after the producer's turn is over but its text does not end in «.!?…» (the
# delegation transport may split an answer into segments, even in the middle of a word). When none comes, that text IS
# the end of the answer and the rest of it is portioned and dictated.
ANSWER_GRACE_SECONDS=1.2
# G3 round 2: a reply that shows a turn with no question form to be a question is only prepared. It is released when the listener has been silent this long
# after it was ready: a bystander's exchange goes on, a real question leaves silence for its answer. Speech meanwhile keeps it unreleased, and is judged.
CONFIRM_SECONDS=0.7
# G3 round 2 (rule 1): how long after a wrong repeat the portion is said again (the silence timer takes ``repeat_seconds``). Not 0: a wrong final speaks nothing
# in its own tick, pinned by test_s6_segmentation, test_stable_partial_ack, test_controlled_media and test_t_new_classes N03, N05, N07, MM2.
WRONG_REPEAT_SECONDS=1.0
# c8b (the owner's call of 3 Nov 20:10), lane A (13 Nov 08:11): a waiting portion nobody repeats must not hold the call. It is ABANDONED - retired
# ('abandoned'; its history entry kept, «повтори» / «продолжай» bring it back) - by a final of OTHER speech (``_MOVED_ON``: not a try, a command, a
# clarification, small talk or noise; less than ABANDON_SHARE of it the answer's own words, else it is a try that failed) when the portion's clock
# has run ABANDON_SECONDS: from its last cue (``_plan_mark``, the clock of G3 too) or the listener's last try before that speech. Once the
# auto-repeats spent their cap the clock runs from the last try only (none: at once). ABANDON_FINALS such finals do it. Under the dictation
# cycle (h28) the clock alone never does, the count of repeats does. That final, and every later one, is judged as when nothing waits.
# How long past its window a wait for the listener's continuation may be extended while that turn is still being spoken:
# the end-of-answer flush (G3) and the hold of an answer to an unfinished question (_coalescing_open) both stop waiting then.
MERGE_PATIENCE_SECONDS=6.0
# A continuation segment (the answer went on after a cut) whose producer fell silent without ever closing its turn is not waited for
# for ever: this long after its last event, the text that did arrive is the end of the answer.
SEGMENT_IDLE_SECONDS=15.0

# THE WAIT OF THE SILENT REPEAT (census: dictation-wait, folded into cm-tick): how long silence is the owner's writing, not silence. Defined here, once; ``repeat_rule.silence`` and ``DictationPace`` read these two functions, none writes its own wait.
DICTATION_START_SECONDS = 4.0      # a stop inside the portion while dictating: help after this (TEMPO_START_SECONDS otherwise): it may be the pen
DICTATION_WORD_SECONDS = 1.5       # the first guess of the seconds one word takes to write, before the owner's own
DICTATION_EXTRA_SECONDS = 2.0      # the wait is the owner's own writing time times DICTATION_SPARE, and this much more
DICTATION_MIN_SECONDS = 6.0        # the pen's wait is never shorter than this
DICTATION_MAX_SECONDS = 30.0       # nor longer than this: the portion comes again
DICTATION_CYCLE_SECONDS = 1.0      # h25/U141 the cycle of the writing owner: silence while dictating, the same portion (or the rest of it) again this long after it ended
DICTATION_CYCLE_MAX_SECONDS = 8.0  # h28: one second more for each repeat past the easy ones, up to this
DICTATION_SPARE = 1.5              # the wait is this many times the owner's own writing time
DICTATION_CYCLE_EASY = 5           # h28: this many repeats at the cycle's pace, then one second more each: about a minute in all


def pen_wait(per_word, words, base=0.0):
    """c22: how long silence after the cue of a portion of ``words`` words is writing: the owner's learned ``per_word`` seconds, bounded MIN..MAX, never shorter than ``base`` (the profile's silence timer)."""
    own = DICTATION_SPARE * per_word * words + DICTATION_EXTRA_SECONDS
    return max(base, min(DICTATION_MAX_SECONDS, max(DICTATION_MIN_SECONDS, own)))


def cycle_wait(n):
    """h25/h28: the wait before repeat ``n`` (counted from 0) of the owner's cycle: the cycle's pace, one second more for each repeat past DICTATION_CYCLE_EASY, up to DICTATION_CYCLE_MAX_SECONDS."""
    return min(DICTATION_CYCLE_MAX_SECONDS, DICTATION_CYCLE_SECONDS + max(0, n - DICTATION_CYCLE_EASY + 1))


def within(now, then, window):
    """THE ONE AGE TEST of the controller's judges (census: cm-ack-join, cm-coalesce, cm-age-thresholds): ``then`` is not later than ``now`` and not older than ``window`` seconds. Every «not further apart than», «began within» and «at most this long after» of the cm-age-thresholds module asks this, none writes the comparison itself."""
    return 0 <= now - then <= window


TIMERS = {m + '.' + n: ('ms' if n.endswith('_MS') else 's') for m, names in _BY_MODULE.items() for n in names}

# Modules scanned for time constants: those of the table above. No «future» list: ``unscanned_modules()`` reads EVERY module of echo_sync (recall, utterance_judge, lang_hint hold no time constant: their scan is empty), so a module that gains one is a red test the day it does.
FUTURE = ()
SCANNED = tuple(_BY_MODULE)

_NAME = re.compile(r'(_S|_MS|_TTL)$|SECONDS|TIMEOUT|_WAIT$')

# Looks like time and is not (key -> why): nothing today; bytes of a second are skipped by name.
NOT_TIMERS = {}

CYCLE_REPEATS_CEILING = 30

Violation = namedtuple('Violation', 'rule hard text')
Relation = namedtuple('Relation', 'rule hard text check')


def _numeric(node):
    for x in ast.walk(node):
        if isinstance(x, (ast.Call, ast.Attribute, ast.Subscript, ast.Dict, ast.Set, ast.List)):
            return False
        if isinstance(x, ast.Constant) and not isinstance(x.value, (int, float)):
            return False
    return True


def _files(module):
    """echo_sync/<module>.py; for the controller also its cut-out ``cm_*.py`` modules (the module level of controlled_media lives in cm_base)."""
    paths = [_DIR / (module + '.py')]
    if module == 'controlled_media':
        paths += sorted(_DIR.glob('cm_*.py'))
    return [p for p in paths if p.is_file()]


def scan(module):
    """The time constants (names) at the top of echo_sync/<module>.py; [] when the module is not there."""
    found = []
    for path in _files(module):
        for node in ast.parse(path.read_text(encoding='utf-8')).body:
            if isinstance(node, ast.Assign) and _numeric(node.value):
                for target in node.targets:
                    if isinstance(target, ast.Name) and (target.id.isupper() or target.id[1:].isupper()) and _NAME.search(target.id) and 'BYTES' not in target.id:
                        found.append(target.id)
    return found


def unregistered():
    """The constants the scan finds that TIMERS does not hold (and NOT_TIMERS does not excuse): must be []."""
    return sorted(m + '.' + n for m in SCANNED for n in scan(m) if m + '.' + n not in TIMERS and m + '.' + n not in NOT_TIMERS)


def stale():
    """Rows of TIMERS whose constant is no longer there (a rename that forgot the table): must be []."""
    return sorted(key for key in TIMERS if key.split('.', 1)[1] not in scan(key.split('.', 1)[0]))


def unscanned_modules():
    """Modules of echo_sync with time constants that SCANNED does not list: must be []."""
    return sorted(p.stem for p in _DIR.glob('*.py') if p.stem not in SCANNED and not p.stem.startswith('cm_') and scan(p.stem))


def repeat_wait(local_ear):
    """The default of ``repeat_seconds`` for this ``local_ear``: the one rule of its value (a profile that states its own value keeps it). With an ear the local ear keeps the tempo of the prompter (H3), without one the plain wait."""
    return REPEAT_SECONDS if local_ear == 'off' else TEMPO_REPEAT_SECONDS


def value(key):
    """The live value of ``module.NAME``: a patched module shows here."""
    module, name = key.split('.', 1)
    return getattr(importlib.import_module(__package__ + '.' + module), name)


def _hold_bounds_max():
    return max(seconds for seconds, _ in value('controlled_media.HOLD_BOUNDS').values())


def _r9(settings):
    cap = settings.get('cycle_max_repeats') or value('repeat_rule.DICTATION_CYCLE_REPEATS')
    auto = settings.get('max_auto_repeats')
    if cap > CYCLE_REPEATS_CEILING or (auto is not None and auto > cap):
        return False
    rule = importlib.import_module(__package__ + '.repeat_rule')
    if hasattr(rule, 'repeat_cap'):            # X-CAP-1: after an unplaced input the cap is max_auto_repeats, whatever the cycle says
        auto = 1 if auto is None else auto
        return rule.repeat_cap(cycling=True, recording=False, unplaced=True, cycle_max_repeats=cap, max_auto_repeats=auto)[0] == auto
    return True


def _le(a, b):
    return lambda settings: value(a) <= value(b)


def _setting_le(key, limit):
    def check(settings):
        got = settings.get(key)
        return got is None or got <= value(limit)
    return check


RELATIONS = (
    Relation('R1', True, 'the refusal comes before the controller drops the question: reserve_text.REFUSE_AFTER_S <= ANSWER_WAIT_SECONDS (h31: 11 > 8)',
             _le('reserve_text.REFUSE_AFTER_S', 'timer_policy.ANSWER_WAIT_SECONDS')),
    Relation('R2', True, 'the refusal comes before the roads give up: REFUSE_AFTER_S < GIVE_UP_S',
             lambda s: value('reserve_text.REFUSE_AFTER_S') < value('reserve_text.GIVE_UP_S')),
    Relation('R3', True, 'the first text of a job comes within the whole job: FIRST_TEXT_S <= WHOLE_S', _le('fast_text.FIRST_TEXT_S', 'fast_text.WHOLE_S')),
    Relation('R4', True, 'TEMPO_HOLD_SECONDS is the final and the first text of a job: EAR_FINAL_SECONDS + FIRST_TEXT_S',
             lambda s: value('controlled_media.TEMPO_HOLD_SECONDS') == value('controlled_media.EAR_FINAL_SECONDS') + value('fast_text.FIRST_TEXT_S')),
    Relation('R5', True, 'every hold on the listener\'s speech ends within the wait for an answer: max(HOLD_BOUNDS) <= ANSWER_WAIT_SECONDS',
             lambda s: _hold_bounds_max() <= value('timer_policy.ANSWER_WAIT_SECONDS')),
    Relation('R6', True, 'the waits for an answer are within its cap: ANSWER_WAIT_SECONDS, LOOKUP_ANSWER_WAIT_SECONDS <= ANSWER_CAP_SECONDS',
             lambda s: max(value('timer_policy.ANSWER_WAIT_SECONDS'), value('timer_policy.LOOKUP_ANSWER_WAIT_SECONDS')) <= value('timer_policy.ANSWER_CAP_SECONDS')),
    Relation('R7', True, 'the ping times out before the next ping and the keepalive outlasts it: PING_TIMEOUT_S < PING_S < KEEPALIVE_S',
             lambda s: value('codex_road.PING_TIMEOUT_S') < value('codex_road.PING_S') < value('codex_road.KEEPALIVE_S')),
    Relation('R8', False, 'the silence before an automatic repeat is not shorter than the answer grace: repeat_seconds >= ANSWER_GRACE_SECONDS',
             lambda s: s.get('repeat_seconds') is None or s['repeat_seconds'] >= value('timer_policy.ANSWER_GRACE_SECONDS')),
    Relation('R9', True, 'the repeat cap is bounded: max_auto_repeats <= cycle cap <= 30; after an unplaced input repeat_cap gives max_auto_repeats', _r9),
    Relation('R10', True, 'the wait for the ear\'s text ends with the language hold: asr_grace_seconds <= TEMPO_HOLD_SECONDS',
             _setting_le('asr_grace_seconds', 'controlled_media.TEMPO_HOLD_SECONDS')),
    Relation('R11', False, 'half-duplex listening is no longer than the longest cycle wait: half_listen_seconds <= DICTATION_CYCLE_MAX_SECONDS',
             _setting_le('half_listen_seconds', 'timer_policy.DICTATION_CYCLE_MAX_SECONDS')),
    Relation('R13', True, 'a reserve road held back from the race (U50) is asked in time for its first word before the refusal: SPENT_RACE_HOLD_S + NEXT_ROAD_S < REFUSE_AFTER_S',
             lambda s: value('reserve_text.SPENT_RACE_HOLD_S') + value('reserve_text.NEXT_ROAD_S') < value('reserve_text.REFUSE_AFTER_S')),
    Relation('R12', True, 'a portion falls asleep no later than G3 stops giving the plan back, both from the one cue clock (_plan_mark): ABANDON_SECONDS <= PLAN_BACK_SECONDS',
             _le('timer_policy.ABANDON_SECONDS', 'timer_policy.PLAN_BACK_SECONDS')),
)


def validate(settings=None):
    """The violated relations for these settings (a dict; None = none stated): a list of ``Violation``. Hard ones are defects; a relation that cannot be read is skipped."""
    settings = settings or {}
    out = []
    for relation in RELATIONS:
        try:
            ok = relation.check(settings)
        except (ImportError, AttributeError, KeyError, TypeError):
            continue
        if not ok:
            out.append(Violation(relation.rule, relation.hard, relation.text))
    return out


# M5: what is measured and what is not. A constant here has a number nobody has measured on a call; the plan says how it will be (R05-F1: the finals shown the last answer as «in play»).
UNMEASURED = {
    'timer_policy.PLAYED_FRESH_S': 'unmeasured (45 s was written, not measured). Plan, the G-LATE rows: take the in-play rows of the R05 corpus (brain_eval_n2, 60 rows) and the recorded calls; for the age of the last portion 15/30/45/90 s count the finals shown the old answer '
                                       'that were talk of others (late doubt word: the wrong repeat) against those that were a doubt of it (the right confirm); the number moves only on a table with a passport (set, profile, checker, n of N). The G-LATE source rows were not in the repository at P08.',
}

# M5: the table of waits, REASON against LIMIT. ``reason``: the number comes from something observed (a breath, a transport, a model); ``limit``: a bound on a signal that may never come (no hold without a bound, R5); ``unmeasured``: see UNMEASURED.
# The constants below hold the listener's speech or a cue for it; every ``limit`` must end within ANSWER_WAIT_SECONDS (R5 reads HOLD_BOUNDS, ``validate_waits`` reads this table).
WAITS = {
    'controlled_media.EAR_RELEASE_SILENCE_SECONDS': ('reason', 'the pause that ends a breath of speech on the phone (ear offsets); shorter is mid-sentence, longer is the listener waiting'),
    'controlled_media.EAR_TAIL_SILENCE_SECONDS': ('reason', 'silence after an open tail that is an end all the same: the tail is evidence, not a veto'),
    'controlled_media.TEMPO_TEXT_SECONDS': ('reason', 'the ear\'s text of an utterance is waited for this long after its end; no text, no hold'),
    'controlled_media.EAR_FINAL_SECONDS': ('reason', 'the cloud final came up to 3.7 s behind the ear on the phone'),
    'timer_policy.EAR_SPEECH_SECONDS': ('limit', 'a stretch of speech with no offset and no word of the cloud: the detector is stuck (the number 8.0 is the bound of the owner\'s 8 s rule, not a measure)'),
    'controlled_media.FIRST_HOLD_SECONDS': ('limit', 'U57: speech with content holds a first cue at most this long past the last such speech heard; a stuck detector or noisy room must not silence the call. 8.0 = ANSWER_WAIT_SECONDS by the owner\'s 8 s rule; every hold that lasts longer than LATE_CUE_S writes its cause and seconds (cue_late row)'),
    'timer_policy.EAR_ASK_HOLD_SECONDS': ('limit', 'c24 P16: a question the ear heard holds an older plan back from giving itself back until the cloud final of it is due (3.7 s behind the ear on the phone); at most this long, then the old plan may go on'),
    'fast_text.FIRST_TEXT_S': ('limit', 'E43: a job that has said nothing by then is a failure; the first text of a job is not waited for longer (HOLD_BOUNDS job_first_text)'),
    'controlled_media.FAST_TAIL_SECONDS': ('limit', 'E43: a final on an open tail gets this much rest, then the job goes on what there is (HOLD_BOUNDS tail_before_job)'),
    'timer_policy.ONSET_HOLD_MAX_S': ('limit', 'E43: the longest the own ear of the transport alone holds a cue that is no first cue (HOLD_BOUNDS cue_in_speech)'),
    'timer_policy.DICTATION_CYCLE_MAX_SECONDS': ('limit', 'h28: the longest wait between two repeats of the dictation cycle of the owner; the portion comes again after this at most'),
    'controlled_media.FAST_MARK_SECONDS': ('limit', 'a mark of the job waited for silence: it is carried out after this'),
    'controlled_media.RECORD_PAUSE_SECONDS': ('limit', 'the longest hold on a pause while the owner writes (the pen\'s wait cut to this)'),
    'controlled_media.TRY_FINAL_SECONDS': ('limit', 'g17: the cloud final of a try the ear went on with comes this late at most; later it is not that try'),
    'controlled_media.TEMPO_HOLD_SECONDS': ('reason', 'R4: the final (EAR_FINAL_SECONDS) plus the first text of a job (FIRST_TEXT_S): a hold on unjudged speech ends there'),
    'controlled_media.EAR_PILE_SECONDS': ('limit', 'h28: speech nobody judged that ended this close to the last words can be one question with them'),
    'timer_policy.LOOKUP_WAIT_SECONDS': ('limit', 'the wait for a lookup answer: the same bound as for any answer'),
    'timer_policy.ANSWER_WAIT_SECONDS': ('limit', 'the owner\'s rule: the listener gets a cue or an honest failure phrase within 8 s of the end of the question\'s speech'),
}
WAIT_KINDS = ('reason', 'limit', 'unmeasured')


def validate_waits():
    """Defects of the table of waits: a row of a constant that is not there, a kind that is not one of WAIT_KINDS, a ``limit`` longer than the wait for an answer, a constant of 8.0 s in the controller that no row explains. [] when it holds."""
    bad = []
    cap = value('timer_policy.ANSWER_WAIT_SECONDS')
    for key, (kind, why) in WAITS.items():
        if key not in TIMERS:
            bad.append((key, 'not a registered constant'))
        elif kind not in WAIT_KINDS or not why:
            bad.append((key, 'kind or reason missing'))
        elif kind == 'limit' and value(key) > cap:
            bad.append((key, 'a limit beyond ANSWER_WAIT_SECONDS'))
    for key in TIMERS:
        if key.startswith(('controlled_media.', 'timer_policy.')) and key not in WAITS and value(key) == cap and key.endswith('SECONDS'):
            bad.append((key, 'a wait of the same length with no row: reason or limit?'))
    return bad


# E43: every hold on the listener's speech (``controlled_media.HOLD_BOUNDS``, name -> (seconds, what happens at the bound)) is named here by the constant that bounds it, and that constant has a row of WAITS: no hold without a bound and without a reason.
# A new hold is a new row of HOLD_BOUNDS AND a row here the day it is born: ``holds_unexplained`` is the lock (it counts, it lists no phrase).
HOLD_NAMES = {'ear_text': 'controlled_media.TEMPO_TEXT_SECONDS', 'cloud_final': 'controlled_media.EAR_FINAL_SECONDS', 'job_first_text': 'fast_text.FIRST_TEXT_S',
              'speech_unjudged': 'controlled_media.TEMPO_HOLD_SECONDS', 'ear_detector': 'timer_policy.EAR_SPEECH_SECONDS', 'first_cue': 'controlled_media.FIRST_HOLD_SECONDS',
              'command': 'controlled_media.FAST_MARK_SECONDS', 'tail_before_job': 'controlled_media.FAST_TAIL_SECONDS', 'tail_before_cue': 'controlled_media.EAR_TAIL_SILENCE_SECONDS',
              'cue_in_speech': 'timer_policy.ONSET_HOLD_MAX_S', 'no_final': 'timer_policy.ANSWER_WAIT_SECONDS', 'record_pause': 'controlled_media.RECORD_PAUSE_SECONDS'}


def holds_unexplained():
    """E43: the defects of the table of holds. A hold of HOLD_BOUNDS with no constant here, a constant with no WAITS row, a bound that is not the constant's value, a bound beyond ANSWER_WAIT_SECONDS, a name here that HOLD_BOUNDS no longer has. [] when it holds."""
    bounds = value('controlled_media.HOLD_BOUNDS')
    cap = value('timer_policy.ANSWER_WAIT_SECONDS')
    bad = []
    for name, (seconds, _) in bounds.items():
        key = HOLD_NAMES.get(name)
        if key is None:
            bad.append((name, 'a hold with no constant named in HOLD_NAMES'))
        elif key not in WAITS:
            bad.append((name, 'its constant %s has no row in WAITS' % key))
        elif value(key) != seconds:
            bad.append((name, 'the bound %s is not the value of %s' % (seconds, key)))
        elif seconds > cap:
            bad.append((name, 'a bound beyond ANSWER_WAIT_SECONDS'))
    bad += [(name, 'named in HOLD_NAMES, not a hold of HOLD_BOUNDS any more') for name in HOLD_NAMES if name not in bounds]
    return bad


# U57: the rule of ``first_cue_hold`` (why_journal.held) -> the constant whose seconds bound that hold: what the cue_late row names. A rule with no number of its own is bounded by the cap of the question.
HOLD_CONSTS = {'speech_with_content': 'FIRST_HOLD_SECONDS', 'ear_text_awaited': 'TEMPO_TEXT_SECONDS', 'job_pending': 'FIRST_HOLD_CAP_SECONDS',
               'handed_back_to_cloud': 'ANSWER_WAIT_SECONDS', 'job_failed_question_to_cloud': 'ANSWER_CAP_SECONDS'}

# M5: the deadlines the tick keeps (cm_timers ``_deadlines_due``, called by ``ControlledMedia.tick``). A deadline is a name, the slot of the controller that holds the moment it was armed (None: not armed), how long it runs and the method that fires it.
# Adding a deadline is adding a row here (and its method): the tick reads the table, nobody edits the tick. The seconds are read live from the key (``value``), so a patched constant shows.
Deadline = namedtuple('Deadline', 'slot seconds fire')
DEADLINES = {'reference': Deadline('reference_armed', 'timer_policy.SPLIT_JOIN_SECONDS', '_reference_fire')}      # g14: the base's answer held for the rest of a number (``reference_wait``) goes when SPLIT_JOIN_SECONDS have passed with no continuation


def deadline_seconds(row):
    """The seconds of a row: a number, or a ``module.NAME`` key of TIMERS."""
    return float(value(row.seconds)) if isinstance(row.seconds, str) else float(row.seconds)


# M5: a literal second outside this file is a deadline the table does not know. ``literal_seconds`` finds them by the AST: a number given as ``timeout=``/``*_seconds=``/``*_s=`` or the wait argument of sleep/wait_for/call_later/join/wait, or the
# default of a parameter or ``self.`` attribute named like a time. ``LITERAL_DEBT`` is the ratchet (file -> count at P08): a new one is red, a paid one must be struck off here. The owners of the files pay them (requests in the P08 report).
_LITERAL_KW = ('timeout', 'seconds', 'delay', 'interval', 'after', 'wait', 'ttl', 'window', 'grace', 'budget')
_LITERAL_CALLS = {'sleep': 0, 'wait_for': 1, 'call_later': 0, 'call_at': 0, 'join': 0, 'wait': 0}
_LITERAL_NAME = re.compile(r'(seconds|_s$|timeout|_ttl$|delay$|interval$)', re.I)


def _is_time_number(node):
    return isinstance(node, ast.Constant) and type(node.value) in (int, float) and node.value > 0


def literal_seconds():
    """[(file, line, site, value)] of the literal seconds in echo_sync/*.py outside timer_policy (the registry itself)."""
    found = []
    for path in sorted(_DIR.glob('*.py')):
        if path.stem == 'timer_policy':
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            if isinstance(node, ast.Call):
                name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, 'id', None)
                for k in node.keywords:
                    if k.arg and any(w in k.arg.lower() for w in _LITERAL_KW) and _is_time_number(k.value):
                        found.append((path.name, node.lineno, '%s(%s=)' % (name, k.arg), k.value.value))
                if name in _LITERAL_CALLS and len(node.args) > _LITERAL_CALLS[name] and _is_time_number(node.args[_LITERAL_CALLS[name]]):
                    found.append((path.name, node.lineno, '%s(arg)' % name, node.args[_LITERAL_CALLS[name]].value))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                a = node.args
                pos = a.posonlyargs + a.args
                pairs = list(zip(pos[len(pos) - len(a.defaults):], a.defaults)) + [(x, y) for x, y in zip(a.kwonlyargs, a.kw_defaults) if y is not None]
                found += [(path.name, d.lineno, '%s(%s=)' % (node.name, arg.arg), d.value) for arg, d in pairs if _is_time_number(d) and _LITERAL_NAME.search(arg.arg)]
            elif isinstance(node, ast.Assign) and _is_time_number(node.value):
                found += [(path.name, node.lineno, 'self.' + t.attr, node.value.value) for t in node.targets if isinstance(t, ast.Attribute) and _LITERAL_NAME.search(t.attr)]
    return found


# P08 census of the literals (38 sites, from the scan above): the owner of the file takes the number into this file and imports it.
LITERAL_DEBT = {'build_info.py': 1, 'call_trace.py': 1}


def literal_debt():
    """file -> count of the literal seconds found now."""
    out = {}
    for f, *_ in literal_seconds():
        out[f] = out.get(f, 0) + 1
    return out


# The clock lock: the state machines read ``self.clock`` (injected, so a test can drive it). A direct call of the real clock is allowed only in the named functions.
CLOCK_LOCK = {'controlled_media': (), 'repeat_rule': (), 'reserve_text': (), 'native_media_socket': ('_play',)}
_CLOCKS = {'monotonic', 'time', 'perf_counter', 'monotonic_ns', 'time_ns'}


def clock_calls(module):
    """[(function, line)] of the direct calls of time.monotonic()/time.time()/perf_counter() in echo_sync/<module>.py."""
    found = []

    def walk(node, function):
        for child in ast.iter_child_nodes(node):
            name = child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else function
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute) and isinstance(child.func.value, ast.Name) and child.func.value.id == 'time' and child.func.attr in _CLOCKS:
                found.append((function, child.lineno))
            walk(child, name)
    for path in _files(module):
        walk(ast.parse(path.read_text(encoding='utf-8')), None)
    return found


def clock_violations():
    """Direct clock calls outside CLOCK_LOCK: must be []."""
    return [(m, f, line) for m, allowed in CLOCK_LOCK.items() for f, line in clock_calls(m) if f not in allowed]


class OrderLedger:
    """U20-S5a: forbidden orders of a call, keyed by the epoch of the action (the reply token; from the U15 turn record once wired). Pure: no clock, no I/O; ``violations`` only records, the caller decides (shadow/on).
      O1  refusal after the answer of the same epoch was played;
      O2  second refusal for one epoch (D6: a provisional one then a final one is two phrases);
      O3  refusal of an epoch older than one already played;
      O4  any action on a closed epoch.
    A provisional refusal followed by the answer is allowed."""

    def __init__(self):
        self._played = set()
        self._refused = set()
        self._closed = set()
        self.violations = []

    def closed(self, epoch):
        return epoch in self._closed

    def close(self, epoch):
        self._closed.add(epoch)

    def refusal_allowed(self, epoch):
        """(ok, rule): the rule that forbids a spoken refusal now; changes nothing."""
        if epoch in self._closed:
            return False, 'O4'
        if epoch in self._played:
            return False, 'O1'
        if any(p > epoch for p in self._played):
            return False, 'O3'
        if epoch in self._refused:
            return False, 'O2'
        return True, None

    def _note(self, rule, epoch):
        if rule:
            self.violations.append((rule, epoch))
        return rule

    def refuse(self, epoch, provisional=False):
        """Record a refusal (spoken or about to be); returns the violated rule or None."""
        rule = self.refusal_allowed(epoch)[1]
        self._refused.add(epoch)
        return self._note(rule, epoch)

    def play(self, epoch):
        """Record the start of an answer cue; returns 'O4' on a closed epoch, else None."""
        rule = 'O4' if epoch in self._closed else None
        self._played.add(epoch)
        return self._note(rule, epoch)


# U20-S4: deferred slots that carry the reply token they were armed in. Name -> value of "nothing armed".
STAMPED_SLOTS = {'repeat_at': None, 'resume_repeat': False, 'go_on': None, 'go_ahead': None, 'went_on': None,
                 'tempo_hold': None, 'tempo_start': None, 'portion_tries': None}


class Stamped:
    """A slot that remembers the token (``epoch``) of its owner at the moment it was armed. Reading gives the value, as a plain attribute; ``stale_slots(owner)`` names the armed slots whose token is not the owner's now. Pure: it never clears anything itself."""

    def __init__(self, token='epoch', empty=None):
        self.token = token
        self.empty = empty

    def __set_name__(self, owner, name):
        self.name = name
        self.key = '_st_' + name

    def __get__(self, obj, cls=None):
        if obj is None:
            return self
        return obj.__dict__.get(self.key, (self.empty, None))[0]

    def __set__(self, obj, value):
        obj.__dict__[self.key] = (value, getattr(obj, self.token, None))

    def armed(self, obj):
        return obj.__dict__.get(self.key, (self.empty, None))[0] not in (None, False)

    def stamp(self, obj):
        return obj.__dict__.get(self.key, (self.empty, None))[1]


def stale_slots(owner):
    """Names of the Stamped slots of ``owner`` that are armed under another token than the one it holds now."""
    now = getattr(owner, 'epoch', None)
    return [n for n, d in vars(type(owner)).items() if isinstance(d, Stamped) and d.armed(owner) and d.stamp(owner) != now]
