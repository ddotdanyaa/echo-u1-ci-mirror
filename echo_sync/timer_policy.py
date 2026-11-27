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
    'call_audio': ('DRIFT_MS', 'CLOSE_JOIN_S', 'MAX_FILL_MS',),
    'conversation_ledger': ('PLAY_LAG_S', 'LEDGER_CARRY_S',),
    'controlled_media': ('ANSWER_GRACE_SECONDS', 'RECORD_PAUSE_SECONDS', 'CONFIRM_SECONDS', 'WRONG_REPEAT_SECONDS', 'ABANDON_SECONDS', 'MONOLOGUE_QUIET_SECONDS', 'MERGE_PATIENCE_SECONDS', 'TRY_FINAL_SECONDS', 'SEGMENT_IDLE_SECONDS', 'CUE_TAIL_SECONDS', 'CUE_SYNTHESIS_SECONDS', 'ECHO_MIN_LAG_SECONDS', 'INPUT_CLOCK_SLACK_MS', 'EAR_JOIN_GAP_SECONDS', 'EAR_ANNOUNCE_SLACK_SECONDS', 'EAR_START_SLACK_MS', 'EAR_BIND_SECONDS', 'EAR_PIECE_SECONDS', 'EAR_PIECE_GRID_MS', 'EAR_ANNOUNCE_MAX_SECONDS', 'TEMPO_STEP_SECONDS', 'PACE_QUIET_SECONDS', 'TEMPO_START_SECONDS', 'LANDMARK_SECONDS', 'TEMPO_TWICE_SECONDS', 'TEMPO_FILLER_SECONDS', 'NO_AFTER_CUE_SECONDS', 'TEMPO_PAUSE_SECONDS', 'EAR_FINAL_SECONDS', 'TEMPO_HOLD_SECONDS', 'FIRST_HOLD_SECONDS', 'TEMPO_ANNOUNCE_SECONDS', 'TEMPO_TEXT_SECONDS', 'EAR_RELEASE_SILENCE_SECONDS', 'EAR_ASK_HOLD_SECONDS', 'HANDED_BACK_WAIT_SECONDS', 'EAR_TAIL_SILENCE_SECONDS', 'EAR_FIRST_BIND_SECONDS', 'EAR_PILE_SECONDS', 'SPLIT_JOIN_SECONDS', 'PACE_HELP_SECONDS', 'FIGURE_STILL_SECONDS', 'FIGURE_HEAD_SECONDS', 'PLAN_BACK_SECONDS', 'PLAYED_FRESH_S', 'FAST_TAIL_SECONDS', 'FAST_MARK_SECONDS', 'WITNESS_SLACK_SECONDS', 'EAR_COMMAND_SETTLE_SECONDS', 'ANSWER_WAIT_SECONDS', 'LOOKUP_WAIT_SECONDS', 'LOOKUP_ANSWER_WAIT_SECONDS', 'ANSWER_CAP_SECONDS', 'FIRST_HOLD_CAP_SECONDS', 'REFUSE_BEFORE_DROP_SECONDS', 'UNANSWERED_SECONDS',),
    'diagnostics': ('DIAGNOSTIC_MIN_INTERVAL_S', 'DIAGNOSTIC_FLUSH_S', 'PRERENDER_TIMEOUT_S', 'TARGET_SECONDS', 'MAX_SECONDS',),
    'ear_prefetch': ('EAR_FEED_WAIT_SECONDS', 'EAR_FEED_JOIN_SECONDS', 'EAR_FEED_SETTLE_SECONDS',),
    'ear_shadow': ('MAX_PENDING_S', 'MAX_UTTERANCE_S', 'VOICE_BUFFER_S', 'MAX_STREAM_S', 'FLOW_PARTIAL_MS',),
    'ear_sherpa': ('TAIL_PAD_S',),
    'fast_text': ('FIRST_TEXT_S', 'WHOLE_S',),
    'codex_road': ('CREDENTIALS_TTL_S', 'KEEPALIVE_S', 'PING_S', 'PING_TIMEOUT_S', 'DRAIN_S',),
    'flow_ahead': ('SYNTH_S', 'DOWN_S', 'PLAY_S', 'MIC_PACKET_S', 'EAR_SEEN_S', 'FLOW_TARGET_S', 'FLOW_AIM_S', 'MIN_PAUSE_S', 'LATE_MIN_S',),
    'helper_bridge': ('HELPER_WRITE_TIMEOUT_S', 'CLOSE_QUIT_S', 'CLOSE_EXIT_S', 'CLOSE_KILL_S',),
    'input_state': ('NO_PACKET_GAP_S', 'DEAD_INPUT_S', 'ASR_GRACE_S', 'HALF_LISTEN_S', 'MIN_SPEECH_MS',),
    'instant': ('PARTIAL_MS',),
    'local_ear': ('FRAME_MS', 'ONSET_MS', 'OFFSET_MS', 'FLOOR_WINDOW_MS', 'ONSET_BUILD_TIMEOUT_S', 'CLOSED_MIN_S', 'CLOSED_MAX_S', 'PAUSE_MARGIN_S', 'ZERO_HOLD_MS',),
    'native_media_socket': ('UPSTREAM_OPEN_TIMEOUT_S', 'SYNTHESIS_BUDGET_S', 'WRITE_RETRY_S', 'MIC_QUEUE_TRIM_MS', 'LOCAL_RETRY_FIRST_S', 'LOCAL_OPEN_GRACE_S', 'LOCAL_RETRY_EVERY_S', 'LOCAL_LINE_WAIT_S', 'LOCAL_HANDOVER_S', 'LOCAL_REPLAY_S',),
    'near_voice': ('FRAME_S', 'WINDOW_S', 'MIN_PIECE_SPEECH_S', 'MIN_PROFILE_SECONDS', 'OTHER_FIRST_HOLD_S', 'UNKNOWN_HOLD_S', 'OTHER_NEXT_HOLD_S', 'UNKNOWN_NEXT_HOLD_S', 'OTHER_RUN_CAP_S', 'JUDGE_EVERY_S',),
    'own_voice': ('MIN_SEGMENT_SECONDS', 'MIN_JUDGE_SECONDS', 'MIN_PROFILE_SECONDS', 'OTHER_FIRST_HOLD_S', 'UNKNOWN_HOLD_S', 'OTHER_NEXT_HOLD_S', 'UNKNOWN_NEXT_HOLD_S', 'OWN_HOLD_S', 'OTHER_RUN_CAP_S', 'JUDGE_EVERY_S', 'WINDOW_S',),
    'pace': ('CAP_SECONDS', 'TEXT_SECONDS',),
    'pcm_cache': ('TRIM_EVERY_SECONDS',),
    'prosody': ('BRIDGE_MS',),
    'pcm_trim': ('LEAD_IN_KEEP_MS', 'MAX_SCAN_MS', 'MAX_TAIL_SCAN_MS', 'TAIL_KEEP_MS',),
    'portioner': ('TAIL_HOLD_SECONDS',),
    'prepared_answers': ('TTL_S',),
    'repeat_rule': ('DICTATION_START_SECONDS', 'DICTATION_WORD_SECONDS', 'DICTATION_EXTRA_SECONDS', 'DICTATION_CYCLE_SECONDS', 'DICTATION_CYCLE_MAX_SECONDS',),
    'reserve_text': ('REST_S', 'PRIMARY_QUOTA_REST_S', 'PRIMARY_FAIL_REST_S', 'FIRST_TEXT_S', 'NEXT_ROAD_S', 'ALL_DEAD_S', 'GIVE_UP_S', 'REFUSE_AFTER_S', 'SPENT_RACE_HOLD_S',),
    'reserve_search': ('SEARCH_S',),
    'settings': ('TEMPO_REPEAT_SECONDS', 'READ_WINDOW_S', 'READ_USER_WINDOW_S',),
    'timer_policy': ('ACK_JOIN_SECONDS', 'HEARING_SECONDS', 'ACK_STABLE_SECONDS', 'PARTIAL_STABLE_SECONDS', 'EARLY_LOOKUP_STABLE_SECONDS', 'OWNER_SILENCE_S', 'CLOUD_DEAF_S', 'SECONDS_PER_SYLLABLE', 'WAKE_TICK_S', 'LAG_PERIOD_S', 'JOURNAL_JOIN_S', 'LATE_CUE_S', 'LOCAL_READ_TIMEOUT_S', 'FAST_SIGN_IN_TIMEOUT_S', 'RECEIVE_TIMEOUT_S', 'EAR_SPEECH_SECONDS', 'QUIET_INTERVAL_S', 'COALESCE_SECONDS', 'ONSET_HOLD_MAX_S', 'LOOKUP_TIMEOUT_S', 'RECONNECT_WINDOW_S', 'CONVERSATION_GAP_S', 'RESUME_NEXT_DAY_S', 'GENERATOR_HTTP_TIMEOUT_S', 'HOST_LOOKUP_TIMEOUT_S',),
    'ws_transport': ('DRAIN_S', 'SLICE_S',),
}
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

# The values of the helpers that had them as literals (loop_guard): defined here, read there. ``controlled_host.WAKE_TICK_S`` is the same number until it imports this one (test_m5_tick holds them equal).
WAKE_TICK_S = 0.1             # the host wakes the tick at least this often: the ceiling for the deadlines that have no event
LAG_PERIOD_S = 0.01           # the loop-lag meter sleeps this long and records how late it woke
JOURNAL_JOIN_S = 5.0          # closing the journal waits this long for its writer thread
LOCAL_READ_TIMEOUT_S = 2      # the host's read of the owner's own files (the profile's settings, the call context, the whole material): a locked file or a dead drive counts as no file after this
FAST_SIGN_IN_TIMEOUT_S = 3    # H1: how long a job of the fast text channel waits for the profile's Codex sign-in (read on the loop's scoped executor)
RECEIVE_TIMEOUT_S = 65        # the longest silence on the phone's socket: the host hangs up on a phone silent this long
LATE_CUE_S = 1.5             # U57: a cue that comes later than this after the decision of the question writes its own decision row (cause and seconds)
EAR_SPEECH_SECONDS = 8.0      # one stretch of speech with no offset: the ear's detector is stuck after this (ControlledMedia's ear_detector hold and pace's voice flag both read it)
QUIET_INTERVAL_S = 3          # U20-S1: the input unchanged this long is a quiet interval (ControlledMedia.input_quiet_due reads it; the transport only reports the changes of the input)
COALESCE_SECONDS = 3.2        # a turn that began within this of the previous final of the utterance goes on with it (the host passes it to ControlledMedia; the observation event carries it)

# The windows and holds several modules read, defined here, once (census: socket-hold, socket-lookup-budget, reconnect-window, resume-window).
ONSET_HOLD_MAX_S = 1.0        # the longest the transport's own ear alone holds a cue that is no first cue (a next portion, a replay)
LOOKUP_TIMEOUT_S = 8          # the public lookup for one question: after this the wire speaks its own phrase
RECONNECT_WINDOW_S = 120      # a call that opens this long after the last portion was spoken is the same conversation after a drop of the line
CONVERSATION_GAP_S = 600.0    # a call opened at most this long after the newest record goes on with the conversation
GENERATOR_HTTP_TIMEOUT_S = 120  # the private generator's HTTP client gives up after this
HOST_LOOKUP_TIMEOUT_S = LOOKUP_TIMEOUT_S - 2     # the host's public lookup of a question: one try, ends inside the one lookup bound
RESUME_NEXT_DAY_S = 36 * 3600  # how far back an explicit «продолжай» reaches; no other utterance gets it

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
        return rule.repeat_cap(cycling=True, recording=False, unplaced=True, record_mode='off', cycle_max_repeats=cap, max_auto_repeats=auto)[0] == auto
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
             _le('reserve_text.REFUSE_AFTER_S', 'controlled_media.ANSWER_WAIT_SECONDS')),
    Relation('R2', True, 'the refusal comes before the roads give up: REFUSE_AFTER_S < GIVE_UP_S',
             lambda s: value('reserve_text.REFUSE_AFTER_S') < value('reserve_text.GIVE_UP_S')),
    Relation('R3', True, 'the first text of a job comes within the whole job: FIRST_TEXT_S <= WHOLE_S', _le('fast_text.FIRST_TEXT_S', 'fast_text.WHOLE_S')),
    Relation('R4', True, 'TEMPO_HOLD_SECONDS is the final and the first text of a job: EAR_FINAL_SECONDS + FIRST_TEXT_S',
             lambda s: value('controlled_media.TEMPO_HOLD_SECONDS') == value('controlled_media.EAR_FINAL_SECONDS') + value('fast_text.FIRST_TEXT_S')),
    Relation('R5', True, 'every hold on the listener\'s speech ends within the wait for an answer: max(HOLD_BOUNDS) <= ANSWER_WAIT_SECONDS',
             lambda s: _hold_bounds_max() <= value('controlled_media.ANSWER_WAIT_SECONDS')),
    Relation('R6', True, 'the waits for an answer are within its cap: ANSWER_WAIT_SECONDS, LOOKUP_ANSWER_WAIT_SECONDS <= ANSWER_CAP_SECONDS',
             lambda s: max(value('controlled_media.ANSWER_WAIT_SECONDS'), value('controlled_media.LOOKUP_ANSWER_WAIT_SECONDS')) <= value('controlled_media.ANSWER_CAP_SECONDS')),
    Relation('R7', True, 'the ping times out before the next ping and the keepalive outlasts it: PING_TIMEOUT_S < PING_S < KEEPALIVE_S',
             lambda s: value('codex_road.PING_TIMEOUT_S') < value('codex_road.PING_S') < value('codex_road.KEEPALIVE_S')),
    Relation('R8', False, 'the silence before an automatic repeat is not shorter than the answer grace: repeat_seconds >= ANSWER_GRACE_SECONDS',
             lambda s: s.get('repeat_seconds') is None or s['repeat_seconds'] >= value('controlled_media.ANSWER_GRACE_SECONDS')),
    Relation('R9', True, 'the repeat cap is bounded: max_auto_repeats <= cycle cap <= 30; after an unplaced input repeat_cap gives max_auto_repeats', _r9),
    Relation('R10', True, 'the wait for the ear\'s text ends with the language hold: asr_grace_seconds <= TEMPO_HOLD_SECONDS',
             _setting_le('asr_grace_seconds', 'controlled_media.TEMPO_HOLD_SECONDS')),
    Relation('R11', False, 'half-duplex listening is no longer than the longest cycle wait: half_listen_seconds <= DICTATION_CYCLE_MAX_SECONDS',
             _setting_le('half_listen_seconds', 'repeat_rule.DICTATION_CYCLE_MAX_SECONDS')),
    Relation('R13', True, 'a reserve road held back from the race (U50) is asked in time for its first word before the refusal: SPENT_RACE_HOLD_S + NEXT_ROAD_S < REFUSE_AFTER_S',
             lambda s: value('reserve_text.SPENT_RACE_HOLD_S') + value('reserve_text.NEXT_ROAD_S') < value('reserve_text.REFUSE_AFTER_S')),
    Relation('R12', True, 'a portion falls asleep no later than G3 stops giving the plan back, both from the one cue clock (_plan_mark): ABANDON_SECONDS <= PLAN_BACK_SECONDS',
             _le('controlled_media.ABANDON_SECONDS', 'controlled_media.PLAN_BACK_SECONDS')),
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
    'controlled_media.PLAYED_FRESH_S': 'unmeasured (45 s was written, not measured). Plan, the G-LATE rows: take the in-play rows of the R05 corpus (brain_eval_n2, 60 rows) and the recorded calls; for the age of the last portion 15/30/45/90 s count the finals shown the old answer '
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
    'controlled_media.FAST_MARK_SECONDS': ('limit', 'a mark of the job waited for silence: it is carried out after this'),
    'controlled_media.RECORD_PAUSE_SECONDS': ('limit', 'the longest hold on a pause while the owner writes (the pen\'s wait cut to this)'),
    'controlled_media.TRY_FINAL_SECONDS': ('limit', 'g17: the cloud final of a try the ear went on with comes this late at most; later it is not that try'),
    'controlled_media.TEMPO_HOLD_SECONDS': ('reason', 'R4: the final (EAR_FINAL_SECONDS) plus the first text of a job (FIRST_TEXT_S): a hold on unjudged speech ends there'),
    'controlled_media.EAR_PILE_SECONDS': ('limit', 'h28: speech nobody judged that ended this close to the last words can be one question with them'),
    'controlled_media.LOOKUP_WAIT_SECONDS': ('limit', 'the wait for a lookup answer: the same bound as for any answer'),
    'controlled_media.ANSWER_WAIT_SECONDS': ('limit', 'the owner\'s rule: the listener gets a cue or an honest failure phrase within 8 s of the end of the question\'s speech'),
}
WAIT_KINDS = ('reason', 'limit', 'unmeasured')


def validate_waits():
    """Defects of the table of waits: a row of a constant that is not there, a kind that is not one of WAIT_KINDS, a ``limit`` longer than the wait for an answer, a constant of 8.0 s in the controller that no row explains. [] when it holds."""
    bad = []
    cap = value('controlled_media.ANSWER_WAIT_SECONDS')
    for key, (kind, why) in WAITS.items():
        if key not in TIMERS:
            bad.append((key, 'not a registered constant'))
        elif kind not in WAIT_KINDS or not why:
            bad.append((key, 'kind or reason missing'))
        elif kind == 'limit' and value(key) > cap:
            bad.append((key, 'a limit beyond ANSWER_WAIT_SECONDS'))
    for key in TIMERS:
        if key.startswith('controlled_media.') and key not in WAITS and value(key) == cap and key.endswith('SECONDS'):
            bad.append((key, 'a wait of the same length with no row: reason or limit?'))
    return bad


# U57: the rule of ``_first_held`` (why_journal.held) -> the constant whose seconds bound that hold: what the cue_late row names. A rule with no number of its own is bounded by the cap of the question.
HOLD_CONSTS = {'speech_with_content': 'FIRST_HOLD_SECONDS', 'ear_text_awaited': 'TEMPO_TEXT_SECONDS', 'job_pending': 'FIRST_HOLD_CAP_SECONDS',
               'handed_back_to_cloud': 'ANSWER_WAIT_SECONDS', 'job_failed_question_to_cloud': 'ANSWER_CAP_SECONDS'}

# M5: the deadlines the tick keeps (cm_timers ``_deadlines_due``, called by ``ControlledMedia.tick``). A deadline is a name, the slot of the controller that holds the moment it was armed (None: not armed), how long it runs and the method that fires it.
# Adding a deadline is adding a row here (and its method): the tick reads the table, nobody edits the tick. The seconds are read live from the key (``value``), so a patched constant shows.
Deadline = namedtuple('Deadline', 'slot seconds fire')
DEADLINES = {}


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
LITERAL_DEBT = {'build_info.py': 1, 'call_trace.py': 1, 'controlled_host.py': 2, 'controlled_media.py': 1, 'engine.py': 2, 'helper_bridge.py': 3,
                'helper_pool.py': 1, 'native_media_socket.py': 1, 'native_prefetch.py': 1, 'question_map.py': 1, 'sapi_worker.py': 9, 'search_race.py': 1, 'warm.py': 11}      # 11: the model_road step (U31, P10) came with its own literal budget_s=2; a debt, to be named like the rest


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
