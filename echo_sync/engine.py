"""Deterministic text handshake; only accepted question turns can generate an answer.

The private full answer of a chat session is kept in SQLite and cut into spoken portions
(``portioner``). Every heard utterance is classified by the pure ``classifier``; this module
only applies the verdict to the stored state, inside one short transaction per turn.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
import threading
from contextlib import contextmanager
from pathlib import Path

from .classifier import (ACK, CLARIFY_REPAIR, CORRECTION, Decision, GREETING, IMPERATIVE, NEXT, QUESTION, QUIET, REPEAT, REPLAY, REPAIR_PROMPT, RESUME, ATTEMPT_REASONS, EXPLICIT_REPLAYS,
                         STOP, _content_stems)
from .portioner import level_settings, portions
from .followup import QuestionMap
from .prepared_answers import from_pairs
from .progress_notes import MAP_ROWS      # the notes of the cloud model (progress-notes) own the ONE cut of a text: the map hands them its texts whole
from .generator import SourcedAnswer, StreamingAnswer
from .settings import resolve
from .timer_policy import CONVERSATION_CARRY_S, CONVERSATION_GAP_S, DB_BUSY_S
from .textutil import WORDS, norm_words, normalize, syllables

SILENT = 'NO_REPLY'  # The explicitly opted-in host profile hides this successful marker.
READY_REPLY = 'Я готов. Задайте вопрос.'
logger = logging.getLogger('echo-sync')

__all__ = ['EchoEngine', 'SILENT', 'IMPERATIVE', 'WORDS', 'conversation_map', 'normalize']


# --- the conversation map (CL2, ruling 3) ----------------------------------------------------------------------------------------
# Every history entry (one per answered question) also says how the listener lived it: ``at`` (the engine clock when the answer was
# published), ``chunks`` (the portions as dictated), ``spoken`` (how many of them the listener confirmed) and ``status``. The state
# points at the entry of the answer it holds (``entry``: its index in the history).
TURN_ROWS_KEPT = 128         # R09-3: the idempotency rows of `turns` (a retransmit is of the last few turns)
HISTORY_CHAR_BUDGET = 24_000   # R09-2: characters of the history the model is given (questions, answers, sources)
HISTORY_LIMIT = 20          # entries kept in the state
CHUNKED_ENTRIES = 5         # the newest entries keep their portions; older ones keep question, answer, status, spoken and at
STATUSES = ('active', 'complete', 'interrupted', 'paused', 'revised')
_MAP_KEYS = frozenset({'at', 'chunks', 'spoken', 'status'})
_CORRECTION_OPENING = re.compile(r'^\W*поправка\b', re.I)     # answer policy v2: «Был неправ — начни с «Поправка:»»


UNASKED = 'unasked'     # the entry of an exchange that never happened (the ear opened a question the cloud's final took back): the engine's history says so, no controller keeps a list of its own


def call_history(state, floor=None):
    """THE one reading of the engine's history for a call (memory family, engine-history): the entries of the call, oldest first. Not the entries older than the floor of the call
    (``floor``, else ``state['call_began']`` the controller sets when a call began anew: «а почему?» is no follow-up to yesterday's question; no floor, a redial inside the window,
    sees all) and not an exchange that never happened (``UNASKED``). ``asked_of``, the controller's ``call_exchanges`` and the model's ``model_history`` all read this."""
    if not isinstance(state, dict):
        return []
    floor = state.get('call_began') if floor is None else floor
    old = lambda at: type(floor) in (int, float) and type(at) in (int, float) and at < floor      # noqa: E731
    return [entry for entry in state.get('history') or () if isinstance(entry, dict) and entry.get('status') != UNASKED and not old(entry.get('at'))]


def asked_of(state):
    """The questions of ``state``, oldest first: the ONE base of every follow-up: ``call_history`` plus the question in play (not of an earlier call, not one that never happened)."""
    if not isinstance(state, dict):
        return []
    asked = [str(entry.get('question') or '') for entry in call_history(state)]
    began = state.get('call_began')
    old = type(began) in (int, float) and type(state.get('issued_at')) in (int, float) and state['issued_at'] < began
    never = {entry.get('question') for entry in state.get('history') or () if isinstance(entry, dict) and entry.get('status') == UNASKED}
    if state.get('question') and state['question'] not in never and not old and (not asked or asked[-1] != state.get('question')):
        asked.append(str(state['question']))
    return asked


def model_history(history):
    """The history the model is given, questions and answers (and their provenance),
    never the map's bookkeeping, which changes while the answer is dictated, and never an exchange that never happened."""
    return [{key: value for key, value in entry.items() if key not in _MAP_KEYS}
            for entry in history or () if isinstance(entry, dict) and entry.get('status') != UNASKED]


def _entry_at(state):
    """The history entry of the answer ``state`` holds (or held last), whatever its status; else ``None``."""
    if not isinstance(state, dict):
        return None
    index, history = state.get('entry'), state.get('history')
    if type(index) is not int or not isinstance(history, list) or not 0 <= index < len(history):
        return None
    return history[index] if isinstance(history[index], dict) else None


def _current_entry(state):
    """The entry of the answer that is being dictated or is paused; ``None`` once it is over (or for a state from before the map)."""
    entry = _entry_at(state)
    return entry if entry is not None and entry.get('status') in ('active', 'paused') else None


def _sync_entry(state):
    """Write the listener's progress through the answer of ``state`` into its entry: confirmed portions and active / paused /
    complete. A restored answer (ruling 4c) holds only the unspoken part of its entry: ``spoken_base`` portions were said before."""
    entry = _current_entry(state)
    if entry is None or not state.get('chunks') or state.get('pending_turn'):
        return
    base = state['spoken_base'] if type(state.get('spoken_base')) is int else 0
    if state.get('completed'):
        chunks = entry.get('chunks')
        entry['spoken'] = len(chunks) if isinstance(chunks, list) else base + len(state['chunks'])
        entry['status'] = 'complete'
    else:
        entry['spoken'] = base + state['chunk_index'] + (1 if state.get('stream_waiting_next') else 0)
        entry['status'] = 'paused' if state.get('paused') else 'active'


def _close_entry(state, status=None):
    """The answer of ``state`` stops being current (a new question, a correction, a retire): its entry keeps how far the listener got,
    and is 'interrupted' while something is left unsaid, else 'complete' (``status`` overrides). Returns the entry, or ``None``."""
    entry = _current_entry(state)
    if entry is None:
        return None
    _sync_entry(state)
    chunks = entry.get('chunks') if isinstance(entry.get('chunks'), list) else []
    spoken = entry.get('spoken') if type(entry.get('spoken')) is int else 0
    entry['status'] = status or ('interrupted' if spoken < len(chunks) else 'complete')
    if entry['status'] == 'interrupted':
        state['active'] = False
        state['current_index'] = None
    return entry


def _bound(history):
    """At most HISTORY_LIMIT entries; only the newest CHUNKED_ENTRIES keep their portions."""
    del history[:-HISTORY_LIMIT]
    while len(history) > 2 and sum(len(json.dumps(model_history([entry])[0], ensure_ascii=False)) for entry in history if isinstance(entry, dict)) > HISTORY_CHAR_BUDGET:
        del history[0]       # R09-2: the model reads what the history holds: a budget of characters beside the count, the two newest entries always stay
    for entry in history[:-CHUNKED_ENTRIES]:
        if isinstance(entry, dict):
            entry.pop('chunks', None)


def _split(entry):
    """``(said, unsaid)``: the text of the portions the listener confirmed and of the rest. An entry that no longer keeps its
    portions is split only when it was said to the end."""
    chunks = entry.get('chunks')
    if isinstance(chunks, list) and all(isinstance(chunk, str) for chunk in chunks):
        spoken = entry.get('spoken') if type(entry.get('spoken')) is int else 0
        spoken = max(0, min(spoken, len(chunks)))
        return ' '.join(chunks[:spoken]), ' '.join(chunks[spoken:])
    answer = entry.get('answer') if isinstance(entry.get('answer'), str) else ''
    return (answer, '') if entry.get('status') == 'complete' else ('', '')


def unfinished(entry):
    """``{question, spoken_text, unspoken_text}`` of an entry that has something left unsaid, else ``None`` (texts uncapped)."""
    if not isinstance(entry, dict):
        return None
    said, unsaid = _split(entry)
    if not unsaid:
        return None
    question = entry.get('question') if isinstance(entry.get('question'), str) else ''
    return {'question': question, 'spoken_text': said, 'unspoken_text': unsaid}


def plan_entry(history, index):
    """Entry ``index`` while it is a plan a question took over that can still be taken up ('interrupted', something unsaid), else ``None`` (cm-suspended holds only the index)."""
    entry = history[index] if type(index) is int and isinstance(history, list) and 0 <= index < len(history) else None
    if entry is not None and isinstance(history, list):
        for subsequent in history[index + 1:]:
            if isinstance(subsequent, dict) and 'question' in subsequent:
                return None
    return resumable(entry, ('interrupted',))


def answered_after(history, index):
    """Was an answer given after entry ``index``: then the plan is not given back by itself."""
    return any(isinstance(entry, dict) and entry.get('answer') for entry in (history or ())[index + 1:])


def unfinished_at(index, history, statuses):
    """THE one lookup of an answer left unsaid (resume-memory; the notes of the cloud model read it): ``unfinished`` of the entry ``index`` of ``history`` when its status is one of ``statuses``
    ('active', 'paused': the answer the state holds; 'interrupted': the one a new question or a return retired), else ``None``."""
    if type(index) is not int or not isinstance(history, list) or not 0 <= index < len(history):
        return None
    entry = history[index]
    return unfinished(entry) if isinstance(entry, dict) and entry.get('status') in statuses else None


def resumable(entry, statuses=('interrupted', 'paused')):
    """THE one shape of a history entry a plan can go on from (the engine's ``resume_entry`` and the plan a question took over in ControlledMedia ask it alike): its status is one of ``statuses``,
    its portions are kept, something is left unsaid. ``entry`` itself, else ``None``."""
    if not isinstance(entry, dict) or entry.get('status') not in statuses:
        return None
    chunks, spoken = entry.get('chunks'), entry.get('spoken')
    if not isinstance(chunks, list) or not all(isinstance(chunk, str) for chunk in chunks):
        return None
    return entry if type(spoken) is int and 0 <= spoken < len(chunks) else None


def conversation_map(state, *, now, limit=MAP_ROWS, window_s=CONVERSATION_GAP_S):
    """The recent part of the conversation as the listener lived it, oldest first: for each answered question published at most
    ``window_s`` seconds before ``now`` (the newest ``limit`` of them) its question, status, what was said and what was not. Each
    text whole: the notes of the cloud model (progress_notes) cut them, there and nowhere else. THE one choice of the rows (``limit``, ``window_s``).
    A quiz in progress (the newest row carries a ``quiz_id``) is kept whole: every consecutive row of that quiz stays, even beyond ``limit``."""
    history = state.get('history') if isinstance(state, dict) else None
    rows = []
    for entry in history if isinstance(history, list) else ():
        if not isinstance(entry, dict) or entry.get('status') not in STATUSES:
            continue
        at = entry.get('at')
        if type(at) not in (int, float) or not 0 <= now - at <= window_s:
            continue
        said, unsaid = _split(entry)
        question = entry.get('question') if isinstance(entry.get('question'), str) else ''
        row = {'question': question, 'status': entry['status'], 'spoken_text': said, 'unspoken_text': unsaid}
        if entry.get('quiz_id'):
            row['quiz_id'] = entry['quiz_id']
        if entry.get('options'):
            row['options'] = entry['options']      # E881: the choices of a quiz question go with its row, as its quiz_id does: a row with none carries no key
        rows.append(row)
        qm = QuestionMap()      # T03 and N133: the one cut of a compound question («про X, про Y и про Z», «сколько стоит и когда привезут»); the parts the listener has not heard yet stay open
        eid = qm.ask(question, at)
        qm.feed(eid, said)
        if len(qm.parts(eid)) > 1:
            rows[-1]['open_parts'] = [part['text'] for part in qm.open_parts(eid)]
    if limit <= 0 or not rows:
        return []
    quiz_id = rows[-1].get('quiz_id')
    if quiz_id:
        start = len(rows) - 1
        while start > 0 and rows[start - 1].get('quiz_id') == quiz_id:
            start -= 1
        session = rows[start:]
        if len(session) >= limit:
            return session
        return rows[max(0, start - (limit - len(session))):start] + session
    return rows[-limit:]


# --- going on: NEXT and RESUME (CL2, ruling 4 + amendment A) ------------------------------------------------------------------------
# A try at the waiting portion (a part of it, a sloppy repeat): after one, «продолжай» moves on (QUESTION-T-06). The state remembers the
# position of the last try as ``attempt_at`` = [revision, chunk index]; a portion that is spoken anew forgets it (``_issue``).
_RETURN_FORMS = frozenset({'resume_return', 'resume_return_first'})
# Keys that belong to the answer being dictated, not to the entry a restored answer comes from.
_TRANSIENT = ('streaming', 'stream_waiting_next', 'stream_turn_id', 'paused', 'replay_last',
              'attempt_at', 'previous_entry', 'repair_clarification', 'sources', 'retrieval_status', 'retrieved_at', 'spoken_base',
              'abandoned')




def resume_window(decision):
    """The seconds an unfinished answer can still be resumed by ``decision``: the window of the conversation (``CONVERSATION_GAP_S``: one «same talk», with the ledger and the map), or, for an explicit RESUME command, ``CONVERSATION_CARRY_S`` (``resume_reach``)."""
    return resume_reach(decision is not None and decision.kind == RESUME)


def resume_reach(explicit):
    """The one place of the resume window: ``CONVERSATION_GAP_S``; for the listener's explicit «продолжай» (``explicit``) the long window of the next day."""
    return max(CONVERSATION_GAP_S, CONVERSATION_CARRY_S) if explicit else CONVERSATION_GAP_S


def state_age(state, now):
    """Seconds since the portion of ``state`` was last spoken (``issued_at``, else the ``at`` of its history entry), on the engine's clock ``now``; None when the state does not say."""
    at = state.get('issued_at')
    if type(at) not in (int, float):
        index, history = state.get('entry'), state.get('history')
        entry = history[index] if type(index) is int and isinstance(history, list) and 0 <= index < len(history) else None
        at = entry.get('at') if isinstance(entry, dict) else None
    return now - at if type(at) in (int, float) else None


def new_call_plan(state, *, now, waiting):
    """F3 (the owner's call of 3 Nov): what a NEW call does with the answer an earlier call left, as ``(new_conversation, plan)``. ``new_conversation``: the last portion was spoken more than ``CONVERSATION_GAP_S`` ago (or nothing says when): the call starts a conversation of its own.
    ``plan``: ``'keep'`` a portion that waits and was spoken at most that long ago stays (a phone that re-dials after a drop of the line is the same conversation); ``'close'`` a stale answer that waits, or a question never answered, is retired; None: nothing to settle. ``waiting``: a portion waits."""
    if not state:
        return False, None
    age = state_age(state, now)
    fresh = age is not None and 0 <= age <= CONVERSATION_GAP_S
    if not state.get('pending_turn'):
        if not waiting:
            return not fresh, None
        if fresh:
            return False, 'keep'
    return not fresh, 'close'


def _waits(state):
    """Is there an answer whose portion waits for the listener (being dictated or paused)?"""
    return isinstance(state, dict) and not state.get('completed') and not state.get('pending_turn') and bool(state.get('chunks'))


def _unfinished_entries(state, now, window_s):
    """Indices of the entries an answer can be resumed from, oldest first: interrupted or paused, their portions kept, something left
    unsaid, published (or last resumed) at most ``window_s`` seconds before ``now``. The phone's session id is one constant for every
    call, so the window is what keeps yesterday's answers out (QUESTION-T-B12)."""
    found = []
    history = state.get('history') if isinstance(state, dict) else None
    for index, entry in enumerate(history if isinstance(history, list) else ()):
        if resumable(entry) is None:
            continue
        at = entry.get('at')
        if type(at) not in (int, float) or not 0 <= now - at <= window_s:
            continue
        found.append(index)
    return found


def going_on(state, decision, *, now, window_s, heard=None):
    """What an utterance that asks to go on does with ``state`` (CL2, ruling 4 + amendment A), as ``(plan, entry index)``:

    * ``'next'``     one portion forward, the next one spoken (NEXT while a portion waits; «продолжай» after a try at that portion);
    * ``'reissue'``  the waiting portion again (ruling 4a: the interlocutor's «продолжайте» helps, never cancels; 4b: a paused portion
      was cut, so even «дальше» says it again);
    * ``'restore'``  nothing waits (or a return form names an earlier answer): the unspoken portions of that entry become the plan (4c);
    * ``'question'`` nothing to go on with: the words as said go to the model (4d); with no answer at all yet it is ``'quiet'``;
    * ``'quiet'``    nothing is done (an answer is being made);
    * ``'present'`` / ``'presented'``  a NEXT said before its portion was heard (``heard``: 'reopened' / 'unheard' / 'sounded'): the portion is said, or already was.
    A «вернёмся к <тема>» topic change (``decision.reason == 'topic_change'``) is a return when the topic shares a content stem with the
    question of a fresh unfinished entry (4e): ``'restore'`` (or ``'reissue'`` when it is the answer that waits). ``(None, None)``: the
    decision is not about going on and stays what it is. Pure: the engine and ControlledMedia decide alike."""
    if decision.kind not in (NEXT, RESUME):
        if decision.kind == REPEAT and isinstance(state, dict) and not _waits(state) and not state.get('pending_turn'):
            # c8b: the answer the listener left without a word (ControlledMedia abandoned its waiting portion): «повтори» says it again
            index = state.get('abandoned')
            if type(index) is int and index in _unfinished_entries(state, now, window_s):
                return 'restore', index
            return None, None
        if decision.reason != 'topic_change' or not isinstance(state, dict):
            return None, None
        mine = _content_stems(norm_words(decision.topic), ()) if decision.topic else set()      # the topic the classifier read once, handed on with the verdict
        if not mine:
            return None, None
        current = state.get('entry') if _current_entry(state) is not None else None
        for index in reversed(_unfinished_entries(state, now, window_s)):
            if index != current and mine & _content_stems(norm_words(state['history'][index].get('question') or ''), ()):
                return 'restore', index
        if current is not None and _waits(state) and mine & _content_stems(norm_words(state.get('question') or ''), ()):
            return 'reissue', None
        return None, None
    if not isinstance(state, dict) or state.get('pending_turn'):
        return 'quiet', None
    current = state.get('entry') if _current_entry(state) is not None else None
    candidates = [index for index in _unfinished_entries(state, now, window_s) if index != current]
    target = (candidates[0] if decision.reason == 'resume_return_first' else candidates[-1]) if candidates else None
    if _waits(state):
        if decision.reason in _RETURN_FORMS and target is not None:
            return 'restore', target
        if state.get('paused'):
            return 'reissue', None
        tried = state.get('attempt_at') == [state['revision'], state['chunk_index']]
        if decision.kind == NEXT or (decision.reason == 'resume_continue' and tried):
            if target is not None and not state.get('streaming') and state['chunk_index'] + 1 >= len(state['chunks']):
                return 'restore', target          # U140: the last portion of the answer to a question from the hall: «дальше» goes back to the story it interrupted
            # A1-F6 / c24 P06 (the listener's «дальше» before the portion was heard): ``heard`` is the controller's fact: 'reopened' (a call just reopened) or 'unheard' (said before the portion was heard on this call):
            # the portion is presented, not skipped; 'sounded' (it has sounded since that speech ended): presented already, nothing is done
            return {'reopened': 'present', 'unheard': 'present', 'sounded': 'presented'}.get(heard, 'next'), None
        return 'reissue', None
    if target is not None:
        return 'restore', target
    return ('question', None) if state.get('history') else ('quiet', None)


def _restore(state, index, revision, now):
    """Ruling 4c: the entry ``index`` (interrupted or paused, something unsaid) is the answer again, from its first unconfirmed portion:
    a new revision whose portions are the unspoken ones, cursor 0. The entry says so ('active', ``at`` = now: it was just resumed), and
    ``spoken_base`` keeps how many of its portions were said before (``_sync_entry``)."""
    entry = state['history'][index]
    spoken = entry['spoken']
    rest = list(entry['chunks'][spoken:])
    for key in _TRANSIENT:
        state.pop(key, None)
    for key in ('sources', 'retrieval_status', 'retrieved_at'):
        if key in entry:
            state[key] = entry[key]
    state.update(revision=revision, question=entry.get('question') or '', answer=entry.get('answer') or ' '.join(rest), chunks=rest,
                 chunk_index=0, completed=False, pending_turn=None, entry=index, spoken_base=spoken)
    entry.update(status='active', at=now)


def _damage(state):
    """Why a stored session state cannot be used (a short token), or ``None`` when it can.

    The phone's session id is one constant for every call, so a row that cannot be read must never be read again: it would fail
    every later call (DEF-T-07). Checked: the shape every turn relies on, not the optional extras (those are checked where used)."""
    if not isinstance(state, dict):
        return 'not_an_object'
    if type(state.get('revision')) is not int:
        return 'revision'
    chunks = state.get('chunks')
    if not isinstance(chunks, list) or not all(isinstance(chunk, str) for chunk in chunks):
        return 'chunks'
    index = state.get('chunk_index')
    if type(index) is not int or not 0 <= index <= len(chunks):
        return 'chunk_index'
    if type(state.get('completed')) is not bool:
        return 'completed'
    if not state['completed'] and not state.get('pending_turn') and index >= len(chunks):
        return 'chunk_index'
    pending = state.get('pending_turn')
    if pending is not None and not isinstance(pending, str):
        return 'pending_turn'
    if not isinstance(state.get('answer'), str) or not isinstance(state.get('question', ''), str):
        return 'text'
    history = state.get('history')
    if not isinstance(history, list) or not all(
            isinstance(entry, dict) and isinstance(entry.get('question', ''), str) and isinstance(entry.get('answer', ''), str)
            for entry in history):
        return 'history'
    return None


class PublicationRefused(ValueError):
    """Wave G: this material cannot be published (see ``EchoEngine._produce``). Not a failure of the turn."""


class EchoEngine:
    def __init__(self, path, generate, *, context='', qa=None, settings=None, clock=None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.generate = generate
        self.context = context
        self.bank = from_pairs(qa)      # the owner's question-answer pairs as ``PreparedAnswers`` (None: no list); the classifier asks it, the engine never matches a question itself
        self.settings = settings  # any subset of the keys of settings.DEFAULTS; may be replaced at any time
        self.clock = clock or time.time
        self._generation_lock = threading.Lock()
        self._active_generations = {}
        with self._db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS sessions (session_id TEXT PRIMARY KEY, state TEXT NOT NULL)')
            # A stored state that cannot be read is moved here (the latest one per session), never read again (DEF-T-07).
            db.execute('CREATE TABLE IF NOT EXISTS damaged_sessions (session_id TEXT PRIMARY KEY, state BLOB, reason TEXT, set_aside_at REAL)')
            db.execute('CREATE TABLE IF NOT EXISTS turns (session_id TEXT, turn_id TEXT, reply TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0, issued_index INTEGER, PRIMARY KEY(session_id,turn_id))')
            columns = {row[1] for row in db.execute('PRAGMA table_info(turns)')}
            if 'revision' not in columns:
                db.execute('ALTER TABLE turns ADD COLUMN revision INTEGER NOT NULL DEFAULT 0')
            if 'issued_index' not in columns:
                db.execute('ALTER TABLE turns ADD COLUMN issued_index INTEGER')
            if 'outcome' not in columns:
                db.execute('ALTER TABLE turns ADD COLUMN outcome TEXT')      # see EchoEngine.publication

    @contextmanager
    def _db(self):
        db = sqlite3.connect(str(self.path), timeout=DB_BUSY_S)
        db.execute(f'PRAGMA busy_timeout={int(DB_BUSY_S * 1000)}')
        try:
            with db:
                yield db
        finally:
            db.close()

    def _update_generation_tracking(self, session_id, revision, cancellation_event, invalidate_previous):
        """Apply generation-token changes only after the owning SQLite claim commits."""
        if cancellation_event is None and not invalidate_previous:
            return
        with self._generation_lock:
            active = self._active_generations.get(session_id)
            if invalidate_previous and active and active[0] <= revision:
                active[1].set()
                self._active_generations.pop(session_id, None)
                active = None
            if cancellation_event is not None:
                # A higher revision may have committed and registered while this
                # caller was leaving its transaction. Never replace its token.
                if active and active[0] >= revision:
                    cancellation_event.set()
                else:
                    if active:
                        active[1].set()
                    self._active_generations[session_id] = (revision, cancellation_event)

    def _read_state(self, db, session_id):
        """The stored state of ``session_id``, or ``None``. A row that cannot be used (``_damage``) is moved aside in the same
        transaction with ONE warning (a reason token, never a word of the conversation), and the session starts clean."""
        row = db.execute('SELECT state FROM sessions WHERE session_id=?', (session_id,)).fetchone()
        if not row:
            return None
        try:
            state = json.loads(row[0])
            reason = _damage(state)
        except (TypeError, ValueError, RecursionError):
            state, reason = None, 'unreadable'
        if reason is None:
            return state
        db.execute('INSERT OR REPLACE INTO damaged_sessions VALUES (?,?,?,?)', (session_id, row[0], reason, self.clock()))
        db.execute('DELETE FROM sessions WHERE session_id=?', (session_id,))
        logger.warning('echo-sync state damaged: the stored session was set aside and starts clean reason=%s', reason)
        return None

    def _generation_is_current(self, session_id, revision, turn_id):
        """Check the durable claim so a superseded stream cannot continue across instances."""
        with self._db() as db:
            latest = self._read_state(db, session_id)
        return bool(latest and latest.get('revision') == revision and latest.get('pending_turn') == turn_id)

    def state(self, session_id):
        with self._db() as db:
            return self._read_state(db, session_id)

    @staticmethod
    def heard_span(state):
        """``(chunks, confirmed, heard)``: the portions of the stream's plan, how many the listener has confirmed, and how many he has heard (the one he is on included). The one reading of the cursor for the rules that cut a stream's plan (the restart of a cut segment, the rewrite by the model, the provisional sentence replaced)."""
        chunks, index, waiting = state['chunks'], state['chunk_index'], bool(state.get('stream_waiting_next'))
        return chunks, min(len(chunks), index + 1 if waiting else index), min(len(chunks), index + 1)

    @staticmethod
    def current(state):
        """The portion a silence timer may speak again; SILENT when there is none (a paused answer has none: ruling 1)."""
        if not state:
            return SILENT
        if state.get('completed') or state.get('pending_turn') or state.get('stream_waiting_next') or state.get('paused'):
            return SILENT
        return state['chunks'][state['chunk_index']]

    @staticmethod
    def _issue(state, cfg, now, *, replay_waiting=False):
        """Speak the current portion. Remember when it was said. A portion that is spoken ends
        a pause: the dictation goes on."""
        if state:
            state.pop('repair_clarification', None)
        if not state or state.get('completed') or state.get('pending_turn'):
            return SILENT
        if state.get('stream_waiting_next') and not replay_waiting:
            return SILENT
        state.pop('paused', None)
        state.pop('attempt_at', None)          # the portion is said anew: a try at it is still to come
        portion = state['chunks'][state['chunk_index']]
        state['issued_at'] = now
        state['issued_syl'] = syllables(portion)
        return portion

    @staticmethod
    def _pause(state):
        """The listener's «стоп» (ruling 1): keep the plan - the portions and the cursor - and say nothing until they ask for it.

        Coordinator ruling (W1F-B, 3 Nov 2026): the pause keeps the CURRENT answer whole. A stream that is still open stays open: what the
        producer still says of this answer joins the plan (``extend_answer``, ``revise``) and is never spoken while paused - it is spoken
        from the paused portion on «продолжай / ещё раз / повтори» or a resume. The controller bounds such a stream (its post-publication
        cap, ControlledMedia._stalled_stream) and the cursor waits at the frontier meanwhile. Only a new question discards the old answer's
        tail (``retire``). A closed stream whose frontier had already been confirmed was said to the end: the answer is over, not paused.
        A listener who stops it and asks again gets a fresh answer: no answer is ever reused."""
        if state.get('streaming'):
            state['paused'] = True
            return
        for key in ('stream_waiting_next', 'stream_turn_id'):
            state.pop(key, None)
        if not state['completed']:
            state['paused'] = True

    @staticmethod
    def _next(state, cfg, now):
        """Amendment A: one portion forward without a repeat (the listener's explicit «дальше»). The ACK path, frontier rules included, but
        the word is not the portion, and our own voice never says it. Returns ``(reply, reason)``."""
        if state.get('stream_waiting_next'):
            return SILENT, 'stream_frontier_already_consumed'
        if state.get('streaming') and state['chunk_index'] + 1 >= len(state['chunks']):
            state['stream_waiting_next'] = True
            return SILENT, 'stream_frontier_waiting_for_text'
        state['chunk_index'] += 1
        state['completed'] = state['chunk_index'] >= len(state['chunks'])
        return EchoEngine._issue(state, cfg, now), 'one_portion_forward'

    @staticmethod
    def _log(session_id, turn_id, kind, reason, state, text):
        # Keep the call signature for existing callers, but never format the
        # transcript or conversational identifiers into ordinary diagnostics.
        logger.info('echo-sync decision kind=%s reason=%s revision=%s index=%s',
                    kind, reason, state.get('revision') if state else None,
                    state.get('chunk_index') if state else None)

    def publication(self, session_id, turn_id):
        """Wave G: what became of the answer of ``turn_id``. ``'pending'``: it is being made. ``'published'``: its portions are the plan.
        ``'refused'``: the material was not publishable (an unverified text, nothing to portion): nothing is planned and the turn stays open -
        the same turn id tries again with what it has then, on the same revision, while nothing newer has taken over (``_reclaim_refused``).
        ``'failed'``: a technical failure: the turn is over. ``None``: no answer was made for this turn (no row, not a question, a row older
        than this column)."""
        with self._db() as db:
            row = db.execute('SELECT outcome,revision FROM turns WHERE session_id=? AND turn_id=?', (session_id, turn_id)).fetchone()
            latest = self._read_state(db, session_id) if row else None
        if row and row[0] is None and latest and latest.get('pending_turn') == turn_id and latest.get('revision') == row[1]:
            return 'pending'
        return row[0] if row else None

    def _reclaim_refused(self, session_id, turn_id):
        """Wave G: a turn whose publication was refused (``publication``) tries again: the same claim - same turn id, same revision, nothing
        retired or cancelled by it - while nothing newer holds the session. The tuple of ``_claim_question`` to produce it, else None."""
        with self._db() as db:
            if not db.execute("SELECT 1 FROM turns WHERE session_id=? AND turn_id=? AND outcome='refused'", (session_id, turn_id)).fetchone():
                return None
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT revision FROM turns WHERE session_id=? AND turn_id=? AND outcome='refused'", (session_id, turn_id)).fetchone()
            state = self._read_state(db, session_id)
            if not row or not state or state.get('revision') != row[0] or state.get('pending_turn') or state.get('chunks'):
                return None
            state['pending_turn'] = turn_id
            db.execute('UPDATE sessions SET state=? WHERE session_id=?', (json.dumps(state, ensure_ascii=False), session_id))
            db.execute('UPDATE turns SET outcome=NULL WHERE session_id=? AND turn_id=?', (session_id, turn_id))
        self._log(session_id, turn_id, 'publication', 'refused_turn_tries_again', state, '')
        return row[0], state['question'], model_history(state['history']), None, None

    def reply(self, *, session_id, turn_id, text, request, model, decided, going=None, basis=None, settings=None):
        """Carries out the verdict ``decided`` on ``text``: the engine reads no text for the KIND of an utterance (B, КАРТА_РЕШЕНИЙ §8: one owner of the kind; the judge of the
        controller, or ``utterance_judge.plain_ruling`` for a host with none).

        ``decided``: the verdict (``Decision``: kind, reason; for a question or a correction also the question, which is ``text`` when it names none). ``going``: ``(plan, target)``
        of ``going_on`` for a NEXT or a RESUME (the owner worked it out; None: nothing to go on with). ``basis``: ``(revision, index or None)`` of the state the verdict was made on;
        a verdict made on another revision or another portion is not carried out (QUIET, ``stale_ruling``)."""
        text = str(text or '').strip()
        cfg = resolve(settings if settings is not None else self.settings)
        claim = self._reclaim_refused(session_id, turn_id)
        if claim is not None:
            return self._produce(session_id, turn_id, claim, cfg, request, model)
        pending = None
        cancellation_event = None
        invalidate_previous = False
        with self._db() as db:
            # Claim/invalidate in a short transaction. Never hold a SQLite writer
            # while the private provider request is running.
            db.execute('BEGIN IMMEDIATE')
            state = self._read_state(db, session_id)
            revision = state['revision'] if state else 0
            cached = db.execute('SELECT reply,revision,issued_index FROM turns WHERE session_id=? AND turn_id=?', (session_id, turn_id)).fetchone()
            if cached:
                if state is None and cached[1] == 0 and cached[0] == READY_REPLY:
                    return READY_REPLY
                current = (state and not state.get('completed') and not state.get('pending_turn')
                           and cached[1] == revision and cached[2] == state['chunk_index'])
                if cached[0] != SILENT and current:
                    # Re-delivery can speak again: stamp its actual cached text.
                    state['issued_at'] = self.clock()
                    state['issued_syl'] = syllables(cached[0])
                    state['repair_clarification'] = cached[0] == REPAIR_PROMPT
                    db.execute('UPDATE sessions SET state=? WHERE session_id=?',
                               (json.dumps(state, ensure_ascii=False), session_id))
                    reply = cached[0]
                else:
                    # Old positions (including legacy cache rows without a cursor)
                    # must not replay stale audio after progress or reconnect.
                    reply = SILENT
                self._log(session_id, turn_id, 'cached', 'same_turn_retry' if current else 'obsolete_turn_retry', state, text)
                return reply
            decision = decided
            now = self.clock()
            plan, target = going if going is not None else (None, None)
            stale = basis is not None and (state is None or basis[0] != state['revision'] or (basis[1] is not None and basis[1] != state['chunk_index']))
            if decision.kind in (QUESTION, CORRECTION) and decision.prepared is None:
                decision = decision._replace(question=decision.question or text)
            kind, reason = decision.kind, decision.reason
            if stale:
                kind, reason, plan = QUIET, 'stale_ruling', None       # the verdict is of another state than the one that stands now: nothing is carried out
            reply = SILENT
            if kind == GREETING:
                reply = READY_REPLY
            elif kind == ACK:
                if state.get('stream_waiting_next'):
                    # This portion was already accepted while its continuation
                    # was being produced. A second spoken ACK cannot advance.
                    reason = 'stream_frontier_ack_already_consumed'
                elif state.get('streaming') and state['chunk_index']+1 >= len(state['chunks']):
                    state['stream_waiting_next'] = True
                    reason = 'stream_frontier_waiting_for_text'
                else:
                    state['chunk_index'] += 1
                    state['completed'] = state['chunk_index'] >= len(state['chunks'])
                    reply = self._issue(state, cfg, now)
            elif kind == REPEAT and state and state.get('completed') and state.get('chunks') and not state.get('pending_turn'):
                # «Повтори» after the last portion (scenarios sc06/sc09 were silent): that portion once more; the cursor and the
                # completion stay, and the cue is authorized only while this answer is the current one (see ControlledMedia.authorized).
                reply = state['chunks'][-1]
                state['issued_at'] = now
                state['issued_syl'] = syllables(reply)
                state['replay_last'] = state['revision']
                reason = 'repeat_of_the_last_portion'
            elif kind in (REPEAT, REPLAY):
                if state and state.get('paused') and kind == REPLAY and reason not in EXPLICIT_REPLAYS:
                    # A pause ends on a request, not on a stray try at the paused portion or a word that shares its stem.
                    reason = 'paused_' + reason
                else:
                    reply = self._issue(state, cfg, now, replay_waiting=True)
            elif kind in (NEXT, RESUME):
                # CL2, ruling 4 + amendment A (see going_on). No model call in any of these branches.
                if plan == 'next':
                    reply, done = self._next(state, cfg, now)
                elif plan == 'reissue':
                    reply, done = self._issue(state, cfg, now, replay_waiting=True), 'the_portion_again'
                elif plan == 'restore':
                    revision += 1
                    invalidate_previous = True          # whatever was playing or queued of the answer it replaces is stale
                    _close_entry(state)
                    _restore(state, target, revision, now)
                    reply, done = self._issue(state, cfg, now), 'unfinished_answer_restored'
                else:
                    done = 'nothing_to_go_on_with'
                reason = f'{reason}:{done}'
            elif kind == CLARIFY_REPAIR:
                # No content generation, no cursor/revision change. If echo
                # guarding is enabled its baseline must be the actual prompt.
                reply = REPAIR_PROMPT
                # A rejected answer must never become eligible again when a
                # later ACK/REPEAT clears the transient clarification flag.
                state['repair_clarification'] = True
                state['issued_at'] = now
                state['issued_syl'] = syllables(reply)
            elif kind == STOP:
                if state:
                    # A new revision: every cached reply and queued cue of what was playing is stale (the sound is cut at once).
                    revision += 1
                    invalidate_previous = True
                    state['revision'] = revision
                    if state.get('pending_turn'):
                        # Nothing of the answer exists yet, so there is no plan to keep: the answer being made is cancelled.
                        state.update(answer='', chunks=[], chunk_index=0, completed=True, pending_turn=None)
                        for key in ('sources','retrieval_status','retrieved_at','streaming','stream_waiting_next','stream_turn_id'):
                            state.pop(key,None)
                    elif not state.get('completed') and state.get('chunks'):
                        self._pause(state)
                        reason = 'stop_pauses_the_answer' if state.get('paused') else 'stop_after_the_whole_answer'
            elif kind in (QUESTION, CORRECTION):
                # Every question is generated afresh: no answer is reused.
                pending, state, revision, cancellation_event = self._claim_question(
                    state, revision, decision, kind, turn_id)
                invalidate_previous = True
            if kind in (REPLAY, QUIET) and reason in ATTEMPT_REASONS and _waits(state):
                state['attempt_at'] = [state['revision'], state['chunk_index']]     # CL2: a try at this portion (see going_on)
            if state:
                _sync_entry(state)
                db.execute('INSERT OR REPLACE INTO sessions VALUES (?,?)', (session_id, json.dumps(state, ensure_ascii=False)))
            db.execute('INSERT INTO turns (session_id,turn_id,reply,revision,issued_index) VALUES (?,?,?,?,?)',
                       (session_id, turn_id, reply, revision, state['chunk_index'] if state else None))
            db.execute('DELETE FROM turns WHERE session_id=? AND rowid NOT IN (SELECT rowid FROM turns WHERE session_id=? ORDER BY rowid DESC LIMIT ?)', (session_id, session_id, TURN_ROWS_KEPT))     # R09-3
        self._update_generation_tracking(session_id, revision, cancellation_event, invalidate_previous)
        self._log(session_id, turn_id, kind, reason, state, text)
        if pending is None:
            return reply
        return self._produce(session_id, turn_id, pending, cfg, request, model)

    def _produce(self, session_id, turn_id, pending, cfg, request, model):
        """Make the answer of a claimed turn and publish it. Wave G, the publication contract: what is refused here is the MATERIAL
        (``PublicationRefused``), not the turn: the turn stays open for a text that may pass (``publication``); only a technical failure ends it."""
        claimed_revision, question, history, prepared, cancellation_event = pending
        answer, parts, provenance, context = '', [], {}, None
        stream_answer = False
        stream_final = True
        refused = False
        try:
            context = self.context() if callable(self.context) else self.context
            if prepared:
                generated = prepared['answer']
            elif hasattr(self.generate, 'generate_cancellable'):
                generated = self.generate.generate_cancellable(
                    question, history, context, request, model,
                    cancellation_event=cancellation_event,
                    is_current=lambda: self._generation_is_current(session_id, claimed_revision, turn_id),
                )
            else:
                # U94.2: the claim this answer is for (the turn and the revision claimed above) goes with the call: a generator that has bound an answer to a turn
                # (``ControlledMedia._generate``) compares it with the claim it is asked for, not with a state it reads by itself outside the transaction.
                generated = self.generate(question, history, context, {**(request or {}), 'claim': {'turn': turn_id, 'revision': claimed_revision}}, model)
            stream_answer = isinstance(generated,StreamingAnswer)
            stream_final = generated.final if stream_answer else True
            # What may be published is the route's rule (``RouteMixin._publishable``, read where the controller hands the answer over): the engine publishes what it is given.
            if isinstance(generated,SourcedAnswer):
                provenance = {'sources':list(generated.sources),'retrieval_status':generated.retrieval_status,
                              'retrieved_at':generated.retrieved_at}
            answer = str(generated).strip()
            parts = portions(answer, cfg, spoken=stream_answer)       # the text of a stream is the controller's spoken text (``_spell``): the engine never expands it a second time
            first_chunk=getattr(generated,'first_chunk',None) if stream_answer else None
            if first_chunk is not None:
                parts=None
                if not isinstance(first_chunk,str) or not first_chunk.strip() or not answer.startswith(first_chunk):
                    raise PublicationRefused('Invalid immutable first chunk')
                rest=answer[len(first_chunk):]
                if rest and first_chunk[-1].isalnum() and rest[0].isalnum():
                    raise PublicationRefused('First chunk cuts a word')
                parts=[first_chunk]+self._portions_after([first_chunk],answer[len(first_chunk):],cfg)
            if not parts:
                # A text the controller hands over may still grow; the answer of a model request is all there will be.
                raise PublicationRefused('Empty answer') if stream_answer else ValueError('Empty answer')
        except PublicationRefused as refusal:
            refused, parts = True, []
            logger.info('echo-sync decision kind=publication reason=refused detail=%s revision=%s', str(refusal).replace(' ', '_'), claimed_revision)
        except Exception as failure:
            # DEF-FAULT-09: the cause is named by its CLASS only - a message may carry the question or the answer (decision logs hold no conversation)
            logger.warning('Echo private answer could not be generated; outdated sequence remains stopped reason=%s', type(failure).__name__)
        finally:
            if cancellation_event is not None:
                with self._generation_lock:
                    active = self._active_generations.get(session_id)
                    if active and active[1] is cancellation_event:
                        self._active_generations.pop(session_id, None)
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            latest = self._read_state(db, session_id)
            if not latest or latest['revision'] != claimed_revision or latest.get('pending_turn') != turn_id:
                # A newer question/stop has already won: discard all late text.
                return SILENT
            latest['pending_turn'] = None
            previous = latest.get('previous_entry') if refused else latest.pop('previous_entry', None)
            if parts:
                now = self.clock()
                latest.update(answer=answer, chunks=parts, chunk_index=0, completed=False)
                if stream_answer:
                    latest.update(streaming=not stream_final, stream_waiting_next=False, stream_turn_id=turn_id)
                latest.update(provenance)
                stored = latest['history']
                if _CORRECTION_OPENING.match(answer) and type(previous) is int and 0 <= previous < len(stored):
                    stored[previous]['status'] = 'revised'       # «Поправка: …» replaces the answer before it
                stored.append({'question':question, 'answer':answer, **provenance,
                               'at':now, 'chunks':list(parts), 'spoken':0, 'status':'active'})
                if stream_answer and not stream_final:
                    stored[-1]['incomplete'] = True
                _bound(stored)
                latest['entry'] = len(stored) - 1
                reply = self._issue(latest, cfg, now)
            else:
                reply = SILENT
            db.execute('UPDATE sessions SET state=? WHERE session_id=?', (json.dumps(latest, ensure_ascii=False), session_id))
            db.execute('UPDATE turns SET reply=?,issued_index=?,outcome=? WHERE session_id=? AND turn_id=? AND revision=?',
                       (reply, latest['chunk_index'] if parts else None, 'published' if parts else 'refused' if refused else 'failed',
                        session_id, turn_id, claimed_revision))
            return reply

    def retire(self, session_id, reason='superseded'):
        """The caller has moved on (a new question was accepted, an early question was withdrawn): the answer of the session stops
        being current. This is NOT the listener's «стоп» (that pauses, ruling 1) and no text is classified here.

        The state is cleared exactly as a stop used to clear it - a new revision (every cached reply and cue of the old one is stale),
        no portions, no provenance, no stream, the running generation cancelled - and the history entry keeps how far the listener
        got ('interrupted' while something is left unsaid, else 'complete'). Returns ``{question, spoken_text, unspoken_text}`` of
        the answer when something was left unsaid, else ``None``. ``reason`` is a token for the log."""
        closed = None
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            state = self._read_state(db, session_id)
            if not state:
                return None
            entry = _close_entry(state)
            if entry is not None and entry.get('status') == 'interrupted':
                closed = unfinished(entry)
            revision = state['revision'] + 1
            state.update(revision=revision, answer='', chunks=[], chunk_index=0, completed=True, pending_turn=None)
            for key in ('sources', 'retrieval_status', 'retrieved_at', 'streaming', 'stream_waiting_next', 'stream_turn_id',
                        'paused', 'spoken_base', 'attempt_at', 'abandoned'):
                state.pop(key, None)
            if reason == 'abandoned' and entry is not None and entry.get('status') == 'interrupted' and type(state.get('entry')) is int:
                state['abandoned'] = state['entry']      # c8b: «повтори» may bring it back (going_on)
            db.execute('UPDATE sessions SET state=? WHERE session_id=?', (json.dumps(state, ensure_ascii=False), session_id))
        self._update_generation_tracking(session_id, revision, None, True)
        self._log(session_id, None, 'retire', str(reason), state, '')
        return closed

    def resume_entry(self, session_id, index, explicit=False):
        """G3: the answer of history entry ``index``, which a newer answer took over, is the answer again (the restore of «продолжай», ruling 4c, without the
        words): what is current now is closed as a new question closes it, a new revision, the entry's unspoken portions, cursor 0. Returns the portion that
        waits, or None when the entry cannot be resumed (``_unfinished_entries``). ``explicit``: the listener said «продолжай» (U14-S8: the long window of the next day)."""
        cfg = resolve(self.settings)
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            state = self._read_state(db, session_id)
            now = self.clock()
            if not state or index not in _unfinished_entries(state, now, resume_reach(explicit)):
                return None
            revision = state['revision'] + 1
            _close_entry(state)
            _restore(state, index, revision, now)
            reply = self._issue(state, cfg, now)
            _sync_entry(state)
            db.execute('UPDATE sessions SET state=? WHERE session_id=?', (json.dumps(state, ensure_ascii=False), session_id))
        self._update_generation_tracking(session_id, revision, None, True)
        self._log(session_id, None, 'resume', 'suspended_answer_resumed', state, '')
        return reply

    def revised(self, session_id, question, answer, status='revised'):
        """H2 rule 4: a repair of the text channel took the place of this answer (the text of a repair need not open with «Поправка»): its entry says 'revised', as after «Поправка: …»,
        and no «продолжай» or take-back finds it again. ``status=UNASKED``: the exchange never happened (the ear opened it, the cloud's final took it back): no reader of the call's history sees it. True when it was found."""
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            state = self._read_state(db, session_id)
            for entry in reversed((state or {}).get('history') or ()):
                if isinstance(entry, dict) and entry.get('question') == question and entry.get('answer') == answer:
                    entry['status'] = status if status in ('revised', UNASKED) else 'revised'
                    db.execute('UPDATE sessions SET state=? WHERE session_id=?', (json.dumps(state, ensure_ascii=False), session_id))
                    self._log(session_id, None, 'answer', 'answer_revised' if status != UNASKED else 'answer_unasked', state, '')
                    return True
        return False

    def cue_tail(self, session_id, position, text, sounded=False):
        """The tail of the waiting portion that was cued alone (the listener stalled part-way: «Только то, что осталось») is a parameter of the repeat, kept with the cursor:
        ``position`` is ``(revision, index)`` of the portion it belongs to, ``sounded`` whether the cue has begun to play. ``position`` None, or one that is not where the
        cursor is, drops it. True when it is kept."""
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            state = self._read_state(db, session_id)
            if not state:
                return False
            keep = bool(position) and text and state.get('revision') == position[0] and state.get('chunk_index') == position[1]
            if keep:
                state['tail_cue'] = [position[0], position[1], str(text), bool(sounded)]
            elif 'tail_cue' in state:
                state.pop('tail_cue')
            else:
                return False
            db.execute('UPDATE sessions SET state=? WHERE session_id=?', (json.dumps(state, ensure_ascii=False), session_id))
        return bool(keep)

    @staticmethod
    def tail_of(state):
        """``((revision, index), text, sounded)`` of the tail cued at the portion the cursor is on, else None (the cursor has gone on: the tail is no one's)."""
        tail = (state or {}).get('tail_cue')
        if not tail or state.get('revision') != tail[0] or state.get('chunk_index') != tail[1] or state.get('completed'):
            return None
        return (tail[0], tail[1]), tail[2], bool(tail[3])

    def rewind(self, *, session_id, revision, index, waiting=False):
        """Take back the one step an acknowledgement has just made (``ControlledMedia._early_tail``: the stable partial confirmed the portion at
        ``index``, and the rest of the same utterance turns out to ask for that portion again, so the listener has not moved on). ``waiting``:
        whether the frontier of a stream was already waiting for text before that acknowledgement.

        True when the state is again what it was before that step: the cursor on ``index``, the dictation not completed, the frontier flag as it
        was. That includes an acknowledgement that changed nothing (an echo, a portion already consumed at the frontier). False, and nothing
        changed, when the state is not where that acknowledgement left it: another revision, a question in flight, the cursor gone further than
        one step, a portion that is not there. Nothing is spoken: the caller asks for the repeat the usual way."""
        if type(index) is not int or type(revision) is not int:
            return False
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            state = self._read_state(db, session_id)
            if not state or state.get('revision') != revision or state.get('pending_turn'):
                return False
            here, parked = state.get('chunk_index'), bool(state.get('stream_waiting_next'))
            if here == index and parked == bool(waiting) and not state.get('completed'):
                return True
            # One portion on (past the last one: completed), unless the frontier waited before the acknowledgement (it consumed nothing then: the
            # stream moved the cursor by itself) or waits now (a second acknowledgement has been made since); or the frontier now waits for text
            # (``waiting`` is False here: had it been True, the state would be the one above and nothing would be left to take back).
            stepped = here == index + 1 and not parked and not waiting
            frontier = here == index and parked
            if not (stepped or frontier) or not 0 <= index < len(state.get('chunks') or ()):
                return False
            state['chunk_index'], state['completed'] = index, False
            if 'stream_waiting_next' in state:
                state['stream_waiting_next'] = False
            _sync_entry(state)
            db.execute('UPDATE sessions SET state=? WHERE session_id=?', (json.dumps(state, ensure_ascii=False), session_id))
            return True

    def extend_answer(self, *, session_id, revision, answer, final=False):
        """Append an immutable producer-confirmed prefix to the active stream.

        None rejects a stale/rewritten/closed stream. SILENT accepts an update
        with no new playback authority. A returned cue is authorized exactly
        once when an ACK had already reached the old frontier. This method
        neither calls a model nor changes an already planned portion.
        """
        if type(revision) is not int or not isinstance(answer,str) or type(final) is not bool:
            return None
        cfg = resolve(self.settings)
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            state = self._read_state(db, session_id)
            if not state or state.get('revision')!=revision or not state.get('stream_turn_id') or state.get('pending_turn'):
                return None
            previous = state['answer']
            if not state.get('streaming'):
                return SILENT if final and answer==previous else None
            if not answer.startswith(previous):
                return None
            tail = answer[len(previous):]
            if previous and tail and previous[-1].isalnum() and tail[0].isalnum():
                return None
            # A decimal continuation would change a protected already-issued
            # number even though it starts with punctuation rather than a letter.
            if previous[-1:].isdigit() and re.match(r'^[.,]\d',tail):
                return None
            added = self._portions_after(state['chunks'],tail,cfg)
            state['answer'] = answer
            state['chunks'].extend(added)
            reply = SILENT
            if state.get('stream_waiting_next') and added:
                state['chunk_index'] += 1
                state['stream_waiting_next'] = False
                if not state.get('paused'):                 # a paused answer is never spoken: its next portion waits for the resume
                    reply = self._issue(state,cfg,self.clock())
            if final:
                state['streaming'] = False
                if state.get('stream_waiting_next'):
                    state['stream_waiting_next'] = False
                    state['chunk_index'] += 1
                    state['completed'] = True
            history = state['history'][-1]
            history['answer'] = answer
            if final:
                history.pop('incomplete',None)
            entry = _current_entry(state)
            if entry is not None:
                entry['chunks'] = list(state['chunks'])     # the portions as dictated, the extensions included
            _sync_entry(state)
            db.execute('UPDATE sessions SET state=? WHERE session_id=?',(json.dumps(state,ensure_ascii=False),session_id))
            return reply

    @staticmethod
    def _portions_after(chunks, tail, cfg):
        """The portions of ``tail``, the text that follows the last stored chunk.

        A tail is portioned on its own, so one that is exactly a phrase the phone handles itself («Хватит.», «Пока.») has
        no portion at all, and its words would be lost without a trace. Such a tail leads with the last words of the
        previous chunk instead: the listener hears a word again, never a phrase it must not repeat.

        The text of a stream is already spoken text: the producer (ControlledMedia) expanded the abbreviations once, for the
        whole answer, so a fragment is not expanded again (DEF-SEG-14: «ВВП» would be spelled out in every fragment), yet a
        term that stands in it is still never cut."""
        added = portions(tail,cfg,spoken=True)
        if added or not WORDS.search(tail or ''):
            return added
        return EchoEngine._with_overlap(chunks,tail,cfg)

    @staticmethod
    def _with_overlap(chunks, tail, cfg):
        words = chunks[-1].split() if chunks else []
        tail = str(tail)
        joint = '' if tail[:1].isspace() or tail[:1] in '.,;:!?…' else ' '   # «остановиться» + «. Хватит.» stays «остановиться. Хватит.»
        for size in range(1, len(words)+1):
            added = portions(' '.join(words[-size:])+joint+tail,cfg,spoken=True)
            if added:
                return added
        # Nothing to lead the phrase with that is not itself chatter (the previous chunk is only fillers: «Да!» + «Хватит.» is a phone
        # phrase for every overlap size): the previous chunk and the tail are ONE unit, so that the words of the answer are never dropped
        # without a trace. With no previous chunk at all a lone phone phrase is chatter and adds nothing.
        if words and WORDS.search(tail):
            return [' '.join((' '.join(words)+joint+tail).split())]
        return []

    def revise(self, *, session_id, revision, keep, tail, final=False, settings=None):
        """Replace what the listener has not confirmed of the active stream (Task E3c, audit M04).

        The producer's text no longer continues what was published: the cloud started its answer again after the listener's repeat,
        or rewrote it. The first ``keep`` portions stay exactly as they are and the portions of ``tail`` follow them; ``keep`` may never
        be smaller than the number of portions the listener has confirmed (those are said and stay said). The stored answer becomes the
        kept portions joined by spaces, then ``tail``: later ``extend_answer`` calls continue THAT text.

        When the portion the listener is on (heard, not confirmed) is replaced, its cue is stale: the answer gets a new revision and the
        new portion in its place is the reply. At the stream frontier (the listener confirmed everything and waits) the first new portion
        is the reply. Otherwise nothing is spoken now. Returns ``(reply, revision, answer)``; None when the state is not the open stream
        this revision was made for, or when the listener would be left with no portion at all.

        Like ``extend_answer`` (INTEG7, CL2 x E3c): the state is read with ``_read_state`` (a damaged row is set aside), a stream that is
        closed takes no revision (a correction or the end of the answer was final; CL2's quiet notes go up only then), and the history entry
        of the answer follows - its portions as they will be dictated, ``spoken`` and the status (CL2's conversation map): a revised answer
        that is interrupted and resumed goes on with the revised text, never with what the cloud withdrew."""
        if type(revision) is not int or type(keep) is not int or not isinstance(tail, str) or type(final) is not bool:
            return None
        cfg = resolve(self.settings if settings is None else settings)     # ``settings``: the tail is cut by them (w2-portion)
        tail = tail.strip()
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            state = self._read_state(db, session_id)
            if (not state or state.get('revision') != revision or not state.get('stream_turn_id') or not state.get('streaming')
                    or state.get('pending_turn') or state.get('completed')):
                return None
            chunks, index, waiting = state['chunks'], state['chunk_index'], bool(state.get('stream_waiting_next'))
            confirmed = index + 1 if waiting else index
            if not confirmed <= keep <= len(chunks):
                return None
            kept = chunks[:keep]
            added = self._portions_after(kept, tail, cfg) if tail else []
            if not kept and not added:
                return None
            head = ' '.join(kept)
            answer = head + (' ' if head and tail else '') + tail
            now, reply = self.clock(), SILENT
            state.update(chunks=kept + added, answer=answer, streaming=not final)
            if not waiting and keep == index:
                # The portion the listener heard last is not the portion any more: its cue (and any cached reply) is stale.
                state['revision'] = revision + 1
                if added:
                    reply = SILENT if state.get('paused') else self._issue(state, cfg, now)     # never spoken while paused
                elif final:
                    state['completed'] = True
                else:
                    state['chunk_index'], state['stream_waiting_next'] = index - 1, True   # index >= 1: ``kept`` is not empty
            elif waiting:
                if added:
                    state['chunk_index'], state['stream_waiting_next'] = index + 1, False
                    reply = SILENT if state.get('paused') else self._issue(state, cfg, now)
                elif final:
                    state['chunk_index'], state['stream_waiting_next'], state['completed'] = index + 1, False, True
            history = state['history'][-1]
            history['answer'] = answer
            if final:
                history.pop('incomplete', None)
            else:
                history['incomplete'] = True
            entry = _current_entry(state)
            if entry is not None:
                entry['chunks'] = list(state['chunks'])     # the portions as dictated: the revised ones
            _sync_entry(state)
            db.execute('UPDATE sessions SET state=? WHERE session_id=?', (json.dumps(state, ensure_ascii=False), session_id))
            return reply, state['revision'], answer

    def adapt_rest(self, *, session_id, revision, level):
        """M4 cursor, w2-portion: cut the portions NOT YET SAID again at the length of ``level`` (portioner.ADAPT_LEVELS); None when nothing changed.

        Kept: every portion up to and including the one the listener is on (confirmed or heard); the words and numbers of the rest are unchanged, so
        the cursor and the revision stay. A streamed answer goes through ``revise`` (its frontier and its stream text follow); a WHOLE answer (nothing
        streams any more) is cut here, in its own transaction. Never while paused, never on a closed answer."""
        if type(revision) is not int or type(level) is not int:
            return None
        with self._db() as db:
            state = self._read_state(db, session_id)
        if (not state or state.get('revision') != revision or state.get('paused') or state.get('pending_turn') or state.get('completed')
                or not state.get('chunks')):
            return None
        keep = state['chunk_index'] + 1
        rest = ' '.join(state['chunks'][keep:])
        if not rest:
            return None
        if state.get('streaming') and state.get('stream_turn_id'):
            got = self.revise(session_id=session_id, revision=revision, keep=keep, tail=rest, settings=level_settings(self.settings, level))
            if got is None or got[0] != SILENT:
                return got
            return got if self.state(session_id)['chunks'] != state['chunks'] else None
        cfg = resolve(level_settings(self.settings, level))
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            state = self._read_state(db, session_id)
            if (not state or state.get('revision') != revision or state.get('paused') or state.get('pending_turn') or state.get('completed')
                    or state.get('streaming') or state['chunk_index'] + 1 != keep):
                return None
            kept, old = state['chunks'][:keep], state['chunks'][keep:]
            added = portions(' '.join(old), cfg, spoken=True)
            if not added or added == old or ' '.join(' '.join(added).split()).lower() != ' '.join(' '.join(old).split()).lower():
                return None       # nothing changed, or the cut would change the words: the rest stands as it was
            state['chunks'] = kept + added
            entry = _current_entry(state)
            if entry is not None:
                entry['chunks'] = list(state['chunks'])
            _sync_entry(state)
            db.execute('UPDATE sessions SET state=? WHERE session_id=?', (json.dumps(state, ensure_ascii=False), session_id))
            return SILENT, state['revision'], state['answer']

    @staticmethod
    def _claim_question(state, revision, decision, kind, turn_id):
        previous = None
        if state:
            # The answer being dictated stops being current; its entry is the «previous answer» a «Поправка» would revise.
            _close_entry(state)
            previous = state.get('entry') if type(state.get('entry')) is int else state.get('previous_entry')
        history = list(state['history']) if state else []
        if kind == CORRECTION and state.get('pending_turn') and state.get('question'):
            history.append({'question': state['question'], 'answer': '', 'incomplete': True})
        revision += 1
        state = {'schema':2, 'revision':revision, 'question':decision.question, 'answer':'',
                 'chunks':[], 'chunk_index':0, 'completed':True,
                 'pending_turn':turn_id, 'history':history}
        if type(previous) is int:
            state['previous_entry'] = previous
        cancellation_event = threading.Event() if decision.prepared is None else None
        pending = (revision, decision.question, model_history(history), decision.prepared, cancellation_event)
        return pending, state, revision, cancellation_event
