"""Deliberate breakages of the product for tests/test_t_classes.py::test_the_checks_can_fail_when_the_product_breaks.

A test that cannot fail proves nothing. Each function here breaks ONE behaviour of the production code (in memory, through
``monkeypatch``; no file is touched) in the way a real regression would; the scenarios of Task T-A that guard that behaviour must
then fail. This module deliberately imports the production code: it is the opposite of an oracle. (Task T-B owns the full
mutation harness of V3 section 10 on a scratch copy of the sources; these are the targeted negative controls of T-A's own oracles.)
"""
from cm_patch import patch_controller
from echo_sync import cm_probes, controlled_media, engine, native_media_socket, ru_alignment, user_intents
from echo_sync.classifier import ACK, QUIET, REPLAY, Decision, waiting_portion
from echo_sync.controlled_media import ControlledMedia
from echo_sync.native_media_socket import NativeMediaSocket
from echo_sync.utterance_judge import command_ruling


def attempts_are_confirmations(mp):
    """Any attempt or stray speech while a portion waits is taken for the confirmation."""
    real = cm_probes.analyze

    def mutated(text, state, qa, settings=None):
        decision = real(text, state, qa, settings)
        if decision.kind in (QUIET, REPLAY) and waiting_portion(state) is not None and decision.reason != 'empty':
            return Decision(ACK, 'mutant_attempt_is_ack', None, None)
        return decision
    patch_controller(mp, 'analyze', mutated)


def cancel_does_not_clear_the_phone(mp):
    """The `output_audio_buffer.clear` frame is never sent: the phone keeps what it has buffered."""
    real = NativeMediaSocket._send

    async def send(self, event):
        if isinstance(event, dict) and event.get('type') == 'output_audio_buffer.clear':
            return None
        return await real(self, event)
    mp.setattr(NativeMediaSocket, '_send', send)


def own_voice_is_not_recognised(mp):
    """The controller never finds evidence that a user turn is the cue heard back: the guard (in drop mode) has nothing to act on."""
    mp.setattr(ControlledMedia, '_own_voice_evidence', lambda self, tid: None)


def reopened_call_trusts_replays(mp):
    """A reopened call takes the saved position for playback authority (quiet_reopen switched off after construction)."""
    real = ControlledMedia.__init__

    def init(self, *args, **kwargs):
        real(self, *args, **kwargs)
        self.quiet_reopen = False
    mp.setattr(ControlledMedia, '__init__', init)


def _drop_atoms(mp, keep):
    real = ru_alignment._atoms.__wrapped__ if hasattr(ru_alignment._atoms, '__wrapped__') else ru_alignment._atoms

    def atoms(text):
        return tuple(a for a in real(text) if keep(a))
    mp.setattr(ru_alignment, '_atoms', atoms)


def matcher_ignores_negation(mp):
    """The matcher forgets the word «не»."""
    _drop_atoms(mp, lambda atom: atom.atom != 'не')


def matcher_ignores_numbers(mp):
    """The matcher forgets numbers (every number atom)."""
    _drop_atoms(mp, lambda atom: atom.kind != 'n' and not atom.atom.startswith('!spoken'))


def the_timer_advances_the_cursor(mp):
    """The silence timer, besides repeating the portion, confirms it."""
    real = ControlledMedia.tick

    def tick(self, *, now):
        actions = real(self, now=now)
        if any(action.get('type') == 'speak' for action in actions):
            portion = self.engine.current(self.state())
            if portion != engine.SILENT:
                self._reply(portion, f'{self.nonce}:mutant:{now}', decided=command_ruling(ACK))
        return actions
    mp.setattr(ControlledMedia, 'tick', tick)


def old_answers_are_owned_by_the_current_question(mp):
    """Every assistant turn, old or late, is taken for the answer to the current question."""
    real = ControlledMedia._source

    def source(self, turn, settled=False):
        self.owners[turn['id']] = self.question_id
        self.retired_assistants.discard(turn['id'])
        return real(self, turn, settled)
    mp.setattr(ControlledMedia, '_source', source)


def stop_is_not_understood(mp):
    """«стоп» is not a stop word any more."""
    mp.setattr(user_intents, 'STOP_WORDS', frozenset())
    from echo_sync import classifier
    mp.setattr(classifier, 'STOP_WORDS', frozenset())
    mp.setattr(classifier, 'is_stop', lambda words, fillers: False)


def duplicate_events_are_not_recognised(mp):
    """A turn event delivered a second time is taken for a new one (neither the ledger nor the controller remember the id)."""
    from echo_sync.voice_turns import FramelessTurns
    real_apply = FramelessTurns.apply
    real_accept = ControlledMedia._accept_user

    def apply(self, event):
        raw = event.get('turn') if isinstance(event, dict) else None
        if isinstance(raw, dict) and event.get('type') == 'turn.done':
            self._turns.pop(raw.get('id'), None)
        return real_apply(self, event)

    def accept(self, turn, **kw):    # u13: _accept_user gained keyword arguments (cause=...); the mutant passes all of them on
        self.seen.discard(turn['id'])
        return real_accept(self, turn, **kw)
    mp.setattr(FramelessTurns, 'apply', apply)
    mp.setattr(ControlledMedia, '_accept_user', accept)
