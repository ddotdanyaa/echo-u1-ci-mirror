"""V5 step 0 (b): WHICH rule or timer held a ready cue or dropped a cue, a plan or a question, as one journal line each. Journal only: nothing here
reads a decision back, nothing is called unless the owner has ``facts_why`` set (the host always sets it), and nothing raises.

The line is ``echo-sync why kind=hold|drop subject=… rule=<short code> const=<NAME[|NAME]> id=… by=… seconds=…`` and the trace turns it into a ``why``
record (call_trace._DecisionTap). A hold is written when it begins or its rule changes (per kind, subject and id), not on every tick of 0.1 s.
``const`` names the constant or setting behind the rule, ``seconds`` is its value where it is a module constant: six different constants are 8.0
(controlled_media EAR_SPEECH_SECONDS, FIRST_HOLD_SECONDS, FAST_MARK_SECONDS, ANSWER_WAIT_SECONDS, LOOKUP_WAIT_SECONDS, RECORD_PAUSE_SECONDS; also
reserve_text.REFUSE_AFTER_S, pace.VOICE_STUCK), so the number alone never says which one fired."""
import logging
import sys

logger = logging.getLogger('echo-sync')
PREFIX = 'echo-sync why '
MEMO_MAX = 200
# The caller of ``_drop_question`` -> the constants / settings behind that drop (empty: an event, not a timer).
SITES = {
    '_answer_watchdog': ('ANSWER_WAIT_SECONDS', 'answer_cap_seconds', 'LOOKUP_ANSWER_WAIT_SECONDS'),
    '_plan_after_decline': ('ANSWER_GRACE_SECONDS',),
    '_take_back': (), '_speech_resumes': (), '_ear_first_overruled': (), '_fallback_refused': (), '_fast_command': (),
}
# The reason of ``_new_epoch`` -> the constants behind it.
EPOCH = {'early_tail': ('ACK_JOIN_SECONDS',), 'abandon': ('ABANDON_SECONDS',), 'provider': (), 'accept_user': (), 'open_question': (), 'going_on': (), 'drop_question': (), 'v5_stale': ()}


def _clean(value):
    return str(value).replace(' ', '_')[:64] if value not in (None, '') else '-'


def why(owner, kind, subject, rule, const='', ident='', by='', **extra):
    """One line, once per change of rule for (kind, subject, ident). Never raises; nothing when ``owner.facts_why`` is not true."""
    try:
        if not getattr(owner, 'facts_why', False):
            return
        memo = owner.__dict__.setdefault('_why_memo', {})
        key = (kind, subject, str(ident))
        if memo.get(key) == rule:
            return
        if len(memo) > MEMO_MAX:
            memo.clear()
        memo[key] = rule
        names = const.split('|') if const else []
        seconds = getattr(sys.modules.get(type(owner).__module__), names[0], None) if names else None
        fields = {'kind': kind, 'subject': subject, 'rule': rule, 'const': const or '-', 'id': ident, 'by': by, **extra}
        if isinstance(seconds, (int, float)) and not isinstance(seconds, bool):
            fields['seconds'] = float(seconds)
        logger.info(PREFIX + ' '.join(f'{k}={_clean(v)}' for k, v in fields.items()))
    except Exception:
        return


def held(owner, subject, rule, const='', ident='', **extra):
    """``why(…, 'hold', …)`` that returns True, so that a hold site reads ``return held(…)`` and decides exactly what it decided. The rule is also kept on the owner
    (``v5_held_rule``) for the answer gate (v5_gate.py), which reads it; nothing else does."""
    try:
        owner.__dict__['v5_held_rule'] = rule
    except Exception:
        pass
    why(owner, 'hold', subject, rule, const, ident, **extra)
    return True


def epoch_drop(owner, reason, by=None):
    """The reply token moved (``_new_epoch``): whatever was in flight for the question - a cue, a plan, its answer - is stale. Called from ``_new_epoch`` only.
    ``by``: the site, when the caller knows it (night-gate: the gate ``_act`` stands between the site and ``_new_epoch``, so the frames no longer tell); None: read off the frames, as before."""
    try:
        if not getattr(owner, 'facts_why', False):
            return
        depth = 3 if reason == 'drop_question' else 2
        by = by or sys._getframe(depth).f_code.co_name
        const = EPOCH.get(reason, ())
        if reason == 'drop_question':
            const = SITES.get(by, ())
        why(owner, 'drop', 'question', reason, '|'.join(const), ident=getattr(owner, 'epoch', ''), by=by, cue_out=int(bool(getattr(owner, 'cue_outstanding', False))))
    except Exception:
        return


def act(owner, act, reason, by, basis, verdict, **extra):
    """night-gate: one line per entry of the gate of the irreversible (``ControlledMedia._act`` and what asks it), written by the gate:
    ``echo-sync why kind=act act=… reason=… by=… basis=<reply token>/<plan revision>/<turn> verdict=do|park|stale …``. ``basis``: the marks the evidence was about ('now': this very
    event; '-': not stated). Not memoized (every entry is a line); the trace keeps it with the other ``why`` records (always, on the host). Never raises."""
    try:
        marks = '/'.join('-' if mark is None else str(mark) for mark in basis) if basis else 'now'
        fields = {'kind': 'act', 'act': act, 'reason': reason, 'by': by, 'basis': marks, 'verdict': verdict, **extra}
        logger.info(PREFIX + ' '.join(f'{k}={_clean(v)}' for k, v in fields.items()))
    except Exception:
        return


def cut(owner, act, reason, by, **extra):
    """night-gate: the transport carries a cut of the gate out (NativeMediaSocket.actions, the ``cancel`` branch): ``echo-sync why kind=cut subject=cue rule=<reason> act=… by=… epoch=…
    parked=0|1 playing=0|1`` (what there was to cut). Written by the wire. Not memoized. Never raises."""
    try:
        fields = {'kind': 'cut', 'subject': 'cue', 'rule': reason, 'act': act, 'by': by, **extra}
        logger.info(PREFIX + ' '.join(f'{k}={_clean(v)}' for k, v in fields.items()))
    except Exception:
        return
