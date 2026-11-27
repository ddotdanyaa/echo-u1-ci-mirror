"""WAVE 2 / S6, axis STATE: random event sequences against the real controller and the real wire.

What is tested
  One ``RuleBasedStateMachine`` drives ``Dialogue`` (tests/helpers_s6_state.py). ``Dialogue`` delivers provider
  and phone events through the production ``NativeMediaSocket`` -> ``ControlledMedia`` -> ``EchoEngine``
  (SQLite), built exactly as ``controlled_host.serve`` builds them (keywords read from that file), with fakes only
  at the boundary (GPT-Live helper, SAPI synthesis, lookup, websocket send, clock). After EVERY step it checks
  the invariants S0..S14 listed in ``Dialogue``'s docstring: no two portions in flight, the portion index never
  decreases or skips, only a fresh full correct repeat advances, nothing of an old question after a new one,
  a final answer always yields a first portion, «стоп» silences until a new question, a reconnect never
  double-advances, no exception escapes, and a question the cloud never answers is reported once (a spoken
  diagnostic, not a portion) after the wait of Wave 2 / Task D and is over then like after «стоп» (S14).

How to read a failure
  The assertion starts with the invariant id, e.g. ``[S6]``; the 30 last events follow; hypothesis prints the
  rule sequence (shrunk) that reproduces it.

Known open defects
  Tests marked ``xfail(strict=True, reason="DEF-STATE-NN ...")`` are the minimal reproductions. The machine
  steps around exactly those triggers (``helpers_s6_state.TOLERATED``) so that one open defect does not hide the
  next one: it does not require a first portion when a user turn came
  between the question and its answer (05), does not require «повтори» to speak while the stream waits for text
  (06), never replays an old ack that starts with a question word (07), asks no question that ends on a
  function word (04), and says no «стоп» at the live frontier (09, recorded by W1F-A: pre-existing on 66b29f1).
  (DEF-STATE-01 is fixed, its test is an ordinary one now; of -04 only the «Как?» case is left.)
  When a defect is fixed its xfail test XPASSes, the strict mark fails the suite, and the
  tolerance has to be removed in the same change.

Not covered here: the lookup route (questions that need sources), real-time ordering of the asyncio tasks beyond
  what one event loop gives, ASR variants of a repeat (axis ack), failures of SAPI/lookup/socket (axis fault).

``test_the_invariant_checks_catch_*`` are the checks' own tests: each breaks the production code in one way and
requires the matching invariant to fire, so a green machine is not a machine that cannot fail.
"""
from collections import Counter

from cm_patch import patch_controller
import pytest
from hypothesis import HealthCheck, Phase, settings, strategies as st
from hypothesis.stateful import RuleBasedStateMachine, precondition, rule, run_state_machine_as_test

from helpers_s6_state import (NOISE_PHRASES, REPEAT_PHRASES, TOLERATED, TOPICS, Dialogue, World, host_kwargs, norm,
                              turn_created, turn_done)

STATS = Counter()
TOPIC = st.sampled_from(TOPICS)
INERTIA = TOPICS[0]
EXAMPLES, STEPS = 35, 35        # sized so that the whole module runs in about a minute


class EchoSessionMachine(RuleBasedStateMachine):
    """new question, assistant delta/done, correct/partial/wrong repeat, silence, «повтори», «стоп»,
    new question during dictation, duplicate event, stale/out-of-order event, reconnect, barge-in,
    a synthesis that is still running while the conversation moves on."""

    steps = 0
    since_question = 0
    disturbances = 0
    silences = 0
    interrupts = 0

    def __init__(self):
        super().__init__()
        self.d = Dialogue()
        STATS['runs'] += 1

    def teardown(self):
        try:
            for key, value in self.d.stats.items():
                STATS[key] += value
            STATS['steps'] += self.steps
        finally:
            self.d.close()

    def _step(self, name, disturbance=False):
        self.steps += 1
        if name.startswith(('ask', 'a_new_question', 'start_a_question')):
            self.since_question = 0
            self.disturbances = self.silences = self.interrupts = 0
        else:
            self.since_question += 1
        self.disturbances += bool(disturbance)
        STATS['rule:' + name] += 1

    def may_disturb(self):
        """At most two disturbances per answer, so the answer also makes progress between them."""
        return self.disturbances < 2 and self.since_question >= 1

    def busy(self):
        """An answer is on its way (portions waiting): the states worth disturbing."""
        return self.d.active_answer() or self.d.assistant_open()

    def may_start_a_question(self):
        """Questions start a new answer: only after the previous one got a few steps (or is over), so the machine
        reaches the deep states (second, third portion, the live frontier) instead of restarting all the time."""
        return not self.busy() or self.since_question >= 5

    # -- questions ---------------------------------------------------------------------------------------------

    @precondition(lambda self: not self.d.assistant_can_begin() and self.may_start_a_question())
    @rule(topic=TOPIC, partial_first=st.booleans(), finish_open=st.booleans())
    def ask(self, topic, partial_first, finish_open):
        self._step('ask')
        self.d.ask(topic, partial_first=partial_first, finish_open=finish_open)

    def _ask_and_hear(self, topic, group, deltas, finish, done_only=False):
        d = self.d
        d.ask(topic)
        if done_only:
            d.assistant_only_done()
            return
        d.assistant_begin(group)
        for _ in range(deltas):
            if not d.assistant_can_stream():
                break
            d.assistant_delta()
        if finish:
            d.assistant_done()

    @precondition(lambda self: self.d.dictating is None and self.may_start_a_question())
    @rule(topic=TOPIC, group=st.integers(1, 4), deltas=st.integers(0, 6), finish=st.booleans())
    def ask_and_hear_the_answer(self, topic, group, deltas, finish):
        """The common path in one step: question, then the provider streams the answer (maybe to its end)."""
        self._step('ask_and_hear_the_answer')
        self._ask_and_hear(topic, group, deltas, finish)

    @precondition(lambda self: self.d.dictating is None and self.may_start_a_question())
    @rule(topic=TOPIC, group=st.integers(1, 4), done_only=st.booleans())
    def ask_and_hear_the_whole_answer(self, topic, group, done_only):
        self._step('ask_and_hear_the_whole_answer')
        self._ask_and_hear(topic, group, 0, True, done_only=done_only)

    @precondition(lambda self: self.d.dictating is None and self.may_start_a_question())
    @rule(topic=TOPIC, group=st.integers(1, 4), extra=st.integers(0, 1))
    def ask_and_hear_until_the_first_portion(self, topic, group, extra):
        """The answer is still streaming when its first portion is spoken: the user may catch up with the stream."""
        self._step('ask_and_hear_until_the_first_portion')
        d = self.d
        d.ask(topic)
        d.assistant_begin(group)
        while d.cue_ready() is None and d.assistant_can_stream():
            d.assistant_delta()
        for _ in range(extra):
            if d.assistant_can_stream():
                d.assistant_delta()

    @precondition(lambda self: self.d.dictating is None and self.busy() and self.may_disturb())
    @rule(topic=TOPIC)
    def start_a_question_and_keep_dictating(self, topic):
        self._step('start_a_question_and_keep_dictating', disturbance=True)
        self.d.dictate(topic)

    @precondition(lambda self: self.d.assistant_can_stream() and self.d.dictating is None)
    @rule(topic=TOPIC, late=st.integers(1, 4), group=st.integers(1, 4))
    def a_new_question_while_the_old_answer_still_streams(self, topic, late, group):
        """Question replaced mid-answer: the rest of the old answer arrives late and must stay silent."""
        self._step('a_new_question_while_the_old_answer_still_streams')
        d = self.d
        d.ask(topic)
        for _ in range(late):
            if d.has_stale():
                d.stale_assistant()
        d.assistant_begin(group)

    @precondition(lambda self: self.d.dictating is not None)
    @rule(phrase=st.sampled_from(NOISE_PHRASES))
    def dictation_ends_without_a_question(self, phrase):
        self._step('dictation_ends_without_a_question')
        self.d.finish_dictation_without_a_question(phrase)

    # -- repeats -----------------------------------------------------------------------------------------------

    @precondition(lambda self: self.d.dictating is None and self.d.cue_ready() is not None)
    @rule(relaxed_text=st.booleans(), partial_first=st.booleans())
    def full_correct_repeat(self, relaxed_text, partial_first):
        self._step('full_correct_repeat')
        self.d.ack(relaxed_text=relaxed_text, partial_first=partial_first)

    @precondition(lambda self: self.d.dictating is None and self.d.cue_ready() is not None)
    @rule(relaxed_text=st.booleans())
    def full_correct_repeat_again(self, relaxed_text):
        self._step('full_correct_repeat_again')
        self.d.ack(relaxed_text=relaxed_text)

    @precondition(lambda self: self.d.dictating is None and self.d.cue_ready() is not None)
    @rule(count=st.integers(2, 6))
    def repeat_several_portions_in_a_row(self, count):
        self._step('repeat_several_portions_in_a_row')
        for _ in range(count):
            if self.d.cue_ready() is None:
                break
            self.d.ack()

    @precondition(lambda self: self.d.dictating is None and self.d.cue_ready() is not None
                  and len(self.d.cue_ready().text.split()) >= 2)
    @rule(take=st.integers(1, 3), partial_first=st.booleans())
    def partial_repeat(self, take, partial_first):
        self._step('partial_repeat')
        self.d.partial_repeat(take, partial_first=partial_first)

    @precondition(lambda self: self.d.dictating is None and self.d.cue_ready() is not None)
    @rule(how=st.sampled_from(['negate', 'drop_negation', 'digit', 'swap']), partial_first=st.booleans())
    def wrong_repeat(self, how, partial_first):
        self._step('wrong_repeat')
        self.d.wrong_repeat(how, partial_first=partial_first)

    @precondition(lambda self: self.d.dictating is None and self.busy())
    @rule(kind=st.sampled_from(['repeat', 'repeat', 'stop', 'noise']), phrase=st.integers(0, 4),
          partial_first=st.booleans())
    def the_user_says_a_command_or_nothing(self, kind, phrase, partial_first):
        # DEF-STATE-09 is fixed (W1F-B stop ruling, 3 Nov): a «стоп» at the live frontier is generated again.
        self._step('the_user_says_' + kind)
        if kind == 'repeat':
            self.d.repeat(REPEAT_PHRASES[phrase % len(REPEAT_PHRASES)], partial_first=partial_first)
        elif kind == 'stop':
            self.d.stop(partial_first=partial_first)
        else:
            self.d.noise(NOISE_PHRASES[phrase % len(NOISE_PHRASES)])

    @precondition(lambda self: self.silences < 3)
    @rule(seconds=st.sampled_from([0.2, 1.0, 2.9, 3.6, 7.0, 12.0]))
    def silence(self, seconds):
        self._step('silence')
        self.silences += 1
        self.d.silence(seconds)

    @precondition(lambda self: self.d.cue_ready() is not None and self.silences < 3)
    @rule(seconds=st.sampled_from([3.6, 7.0, 12.0]))
    def silence_after_a_portion(self, seconds):
        """The user does not repeat: the portion is spoken again (S1/S7), never a later one."""
        self._step('silence_after_a_portion')
        self.silences += 1
        self.d.silence(seconds)

    @precondition(lambda self: self.d.assistant_can_stream() and self.d.cue_ready() is not None
                  and self.d.dictating is None)
    @rule(then=st.sampled_from(['text_arrives', 'text_arrives', 'user_speaks_then_text', 'user_speaks_then_noise',
                                'repeat_command']), topic=TOPIC)
    def the_user_catches_up_with_the_stream(self, then, topic):
        """Repeat every portion that exists until the live frontier of the growing answer is reached; then the
        next text arrives, or the user speaks as it arrives (the continuation is parked), or asks to repeat."""
        self._step('the_user_catches_up_with_the_stream', disturbance=then != 'text_arrives')
        d = self.d
        for _ in range(8):
            if d.snap()['waiting'] or d.cue_ready() is None:
                break
            d.ack()
        if not d.snap()['waiting'] or not d.assistant_can_stream():
            return
        if then == 'text_arrives':
            d.assistant_delta()
        elif then == 'repeat_command':
            d.repeat('повтори')
        else:
            d.dictate(topic)
            d.assistant_delta()
            if then == 'user_speaks_then_noise':
                d.finish_dictation_without_a_question('ну')

    # -- disorder ----------------------------------------------------------------------------------------------

    @precondition(lambda self: self.busy() and self.may_disturb() and len(self.d.duplicable()) > 0)
    @rule(pick=st.integers(0, 5))
    def duplicate_event(self, pick):
        self._step('duplicate_event', disturbance=True)
        choices = self.d.duplicable()
        self.d.duplicate(choices[pick % len(choices)])

    @precondition(lambda self: self.d.has_stale())
    @rule()
    def late_event_of_an_old_answer(self):
        self._step('late_event_of_an_old_answer')
        self.d.stale_assistant()

    @precondition(lambda self: self.busy() and self.may_disturb() and self.d.stats['orphans'] < 3)
    @rule()
    def delta_of_an_unknown_turn(self):
        self._step('delta_of_an_unknown_turn', disturbance=True)
        self.d.orphan_delta()

    @precondition(lambda self: self.d.stats['reconnects'] < 3 and self.busy() and self.may_disturb())
    @rule()
    def reconnect(self):
        self._step('reconnect', disturbance=True)
        self.d.reconnect()

    @precondition(lambda self: self.d.can_replay_ack() and self.d.stats['replays'] < 2)
    @rule()
    def replay_the_last_ack_on_the_new_call(self):
        self._step('replay_the_last_ack_on_the_new_call')
        self.d.replay_last_ack()

    @precondition(lambda self: self.d.dictating is None and self.busy() and self.may_disturb())
    @rule(how=st.sampled_from(['client_cancel', 'client_clear', 'provider_speech_started']),
          follow=st.sampled_from(['noise', 'ack', 'repeat']))
    def barge_in_then_the_user_finishes(self, how, follow):
        self._step('barge_in_then_the_user_finishes', disturbance=True)
        d = self.d
        ready = d.cue_ready()
        d.barge_in(how)
        if follow == 'ack' and ready is not None:
            d.ack(cue=ready)
        elif follow == 'repeat':
            d.repeat('повтори')
        else:
            d.noise('ну')

    @precondition(lambda self: self.d.active_answer() and self.d.dictating is None and not self.d.w.hold
                  and self.interrupts < 3)
    @rule(kind=st.sampled_from(['barge_in', 'speech_started', 'new_question', 'question_partial', 'stop', 'silence']),
          frames=st.integers(1, 4), topic=TOPIC)
    def a_portion_is_interrupted_half_way(self, kind, frames, topic):
        self._step('a_portion_is_interrupted_half_way')
        self.interrupts += 1
        self.d.interrupt_a_portion(kind, frames, topic)

    def at_the_live_frontier(self):
        """The listener has confirmed every published portion and the answer still streams: a «стоп» here is DEF-STATE-09."""
        state = self.d.snap()
        return state['revision'] is not None and bool(state['waiting']) and bool(state['streaming'])

    @precondition(lambda self: not self.d.w.hold and self.d.active_answer() and self.d.stats['holds'] < 4
                  and self.may_disturb())
    @rule()
    def synthesis_gets_slow(self):
        self._step('synthesis_gets_slow', disturbance=True)
        self.d.hold_synthesis()

    @precondition(lambda self: self.d.w.hold)
    @rule()
    def synthesis_finishes(self):
        self._step('synthesis_finishes')
        self.d.release_synthesis()


def run_machine(examples, steps, shrink=True):
    run_state_machine_as_test(
        EchoSessionMachine,
        settings=settings(max_examples=examples, stateful_step_count=steps, deadline=None, derandomize=True,
                          database=None, suppress_health_check=list(HealthCheck), print_blob=False,
                          phases=[Phase.generate, Phase.shrink] if shrink else [Phase.generate]))


def test_random_event_sequences_keep_every_invariant():
    run_machine(EXAMPLES, STEPS)
    print('S6_STATE_SUMMARY', dict(STATS))


# =====================================================================================================
# The harness itself
# =====================================================================================================

def answered(d, topic=INERTIA, group=2):
    d.ask(topic)
    d.assistant_begin(group)
    d.assistant_done()
    cue = d.cue_ready()
    assert cue is not None, 'the scenario needs a first portion'
    return cue


def at_the_frontier(d, topic=INERTIA):
    """Stream the answer only as far as its first portion, then repeat it: the next text is awaited."""
    d.ask(topic)
    d.assistant_begin(1)
    while d.cue_ready() is None and d.assistant_can_stream():
        d.assistant_delta()
    assert d.cue_ready() is not None, 'the scenario needs a first portion while the answer streams'
    d.ack()
    assert d.snap()['waiting'], 'the scenario needs the repeat to reach the live frontier'


def test_the_world_is_built_exactly_like_the_host():
    # repeat_seconds / max_auto_repeats: the host passes the PROFILE's values (UX-trace); a profile with no settings file has the calm defaults
    assert {k: v for k, v in host_kwargs().items() if k != 'settings'} == {'source_delivery': 'delegation', 'session_context_fallback': True,
                             'lookup_policy': 'required', 'first_useful_gate': True, 'coalesce_seconds': 3.2,
                             'quiet_reopen': True, 'repeat_seconds': 6.0, 'max_auto_repeats': 1}      # fast_text: the controller reads it from its settings (the host passes none)


def test_a_plain_conversation_passes_every_invariant():
    d = Dialogue()
    try:
        # F1: an answer of three meaning portions, so that «стоп» and «повтори» below still come in the middle of it (the inertia
        # answer is two portions now: the relaxed confirmation would complete it, and «повтори» would come after its end)
        cue = answered(d, TOPICS[4])
        assert cue.text == 'процесс образования органических веществ'   # F1: the first phrase (L2 had «свойство тела» of inertia)
        d.silence(7)                                     # unconfirmed: spoken again, same portion
        d.partial_repeat(2)
        d.wrong_repeat('negate')
        d.ack()
        d.repeat('повтори')
        d.ack(relaxed_text=True)
        d.stop()
        d.silence(10)
        d.repeat('повтори')
        answered(d, TOPICS[2])
        d.reconnect()
        d.repeat('ещё раз')
        d.ack()
        assert d.stats['advances'] >= 3 and d.stats['cues'] >= 6
    finally:
        d.close()


# =====================================================================================================
# The checks' own tests: break production one way, the matching invariant must fire
# =====================================================================================================

def broken(monkeypatch, scenario, pattern, patch):
    """``scenario(d)`` must pass on the real code and fail with ``[S..]`` once ``patch`` has broken it."""
    d = Dialogue()
    try:
        scenario(d)
    finally:
        d.close()
    patch(monkeypatch)
    d = Dialogue()
    try:
        with pytest.raises(AssertionError, match=pattern):
            scenario(d)
    finally:
        d.close()


def test_the_invariant_checks_catch_a_partial_repeat_that_advances(monkeypatch):
    from echo_sync import controlled_media
    from echo_sync import cm_probes
    from echo_sync.classifier import ACK, QUIET, REPLAY, Decision

    def patch(mp):
        real = cm_probes.analyze

        def analyze(text, state, qa, settings=None):
            decision = real(text, state, qa, settings)
            if decision.kind in (QUIET, REPLAY) and state and state.get('chunks') and not state.get('completed'):
                portion = norm(state['chunks'][state['chunk_index']])
                if norm(text) and portion.startswith(norm(text)) and norm(text) != portion:
                    return Decision(ACK, 'mutant: a partial repeat is accepted', None, None)
            return decision
        patch_controller(mp, 'analyze', analyze)      # B: the judge of the controller reads the text; the engine carries out its verdict

    def scenario(d):
        answered(d)
        d.partial_repeat(2)
    broken(monkeypatch, scenario, r'\[S2\]', patch)


def test_the_invariant_checks_catch_a_correct_repeat_that_is_ignored(monkeypatch):
    from echo_sync import ru_alignment

    def scenario(d):
        answered(d)
        d.ack()
    broken(monkeypatch, scenario, r'\[S3\]', lambda mp: mp.setattr(ru_alignment, 'match_current', lambda *a, **k: None))


def test_the_invariant_checks_catch_a_skipped_portion(monkeypatch):
    from echo_sync.engine import EchoEngine

    def patch(mp):
        real = EchoEngine._issue

        def issue(state, cfg, now, *, replay_waiting=False):
            if state and state.get('chunk_index', 0) >= 1 and not state.get('completed') \
                    and state['chunk_index'] + 1 < len(state['chunks']):
                state['chunk_index'] += 1                       # the mutant: advance one more
            return real(state, cfg, now, replay_waiting=replay_waiting)
        mp.setattr(EchoEngine, '_issue', staticmethod(issue))

    def scenario(d):
        # F1: an answer of three meaning portions (the inertia answer is two now): there is a portion after the next one to skip
        answered(d, TOPICS[4])
        d.ack()
    broken(monkeypatch, scenario, r'\[S1\]', patch)


def test_the_invariant_checks_catch_the_answer_of_an_old_question(monkeypatch):
    from echo_sync.controlled_media import ControlledMedia

    def patch(mp):
        real = ControlledMedia._source

        def source(self, turn):
            self.owners[turn['id']] = self.question_id          # the mutant: any answer belongs to the question
            return real(self, turn)
        mp.setattr(ControlledMedia, '_source', source)

    def scenario(d):
        d.ask(INERTIA)
        d.assistant_begin(1)
        d.ask(TOPICS[1])                                       # the first answer is still streaming
        while d.has_stale():                                   # ...and the rest of it arrives late
            d.stale_assistant()
    broken(monkeypatch, scenario, r'\[S6\]', patch)


def test_the_invariant_checks_catch_a_stop_that_does_not_stop(monkeypatch):
    from echo_sync.controlled_media import ControlledMedia

    def patch(mp):
        real = ControlledMedia._accept_user

        def accept(self, turn, **kwargs):
            if norm(turn['text']) == 'стоп':
                return []                                      # the mutant: «стоп» is not obeyed
            return real(self, turn, **kwargs)
        mp.setattr(ControlledMedia, '_accept_user', accept)

    def scenario(d):
        answered(d)
        d.stop()
        d.silence(10)
    broken(monkeypatch, scenario, r'\[S9\]', patch)


def test_the_invariant_checks_catch_audio_of_a_cancelled_synthesis(monkeypatch):
    from echo_sync.controlled_media import ControlledMedia
    from echo_sync.native_media_socket import NativeMediaSocket

    def patch(mp):
        real = NativeMediaSocket.actions

        async def actions(self, items):
            return await real(self, [a for a in items if a['type'] != 'cancel'])   # the mutant: nothing is cancelled
        mp.setattr(NativeMediaSocket, 'actions', actions)
        mp.setattr(ControlledMedia, 'authorized', lambda self, cue: True)

    def scenario(d):
        d.ask(INERTIA)
        d.hold_synthesis()
        d.assistant_begin(2)
        d.assistant_done()                                      # the first portion is still being synthesized
        d.ask(TOPICS[1])                                        # the conversation moves on
        d.release_synthesis()                                   # ...and the old audio must NOT be played now
    broken(monkeypatch, scenario, r'\[S[567]\]', patch)


def test_the_invariant_checks_catch_a_half_played_portion_that_keeps_playing(monkeypatch):
    from echo_sync.controlled_media import ControlledMedia
    from echo_sync.native_media_socket import NativeMediaSocket

    def patch(mp):
        real = NativeMediaSocket.actions

        async def actions(self, items):
            return await real(self, [a for a in items if a['type'] != 'cancel'])   # the mutant: nothing is cancelled
        mp.setattr(NativeMediaSocket, 'actions', actions)
        mp.setattr(ControlledMedia, 'authorized', lambda self, cue: True)

    def scenario(d):
        answered(d)
        d.interrupt_a_portion('new_question', 2, TOPICS[1])
    broken(monkeypatch, scenario, r'\[S[567]\]', patch)


def test_the_invariant_checks_catch_a_question_that_is_not_accepted(monkeypatch):
    from echo_sync import controlled_media
    from echo_sync.classifier import QUIET, Decision

    def scenario(d):
        d.ask(INERTIA)

    def patch(mp):
        patch_controller(mp, 'analyze', lambda *a, **k: Decision(QUIET, 'mutant', None, None))
    broken(monkeypatch, scenario, r'\[S0\]', patch)


def test_the_invariant_checks_catch_a_state_that_contradicts_itself(monkeypatch):
    from echo_sync.engine import EchoEngine

    def patch(mp):
        real = EchoEngine._issue

        def issue(state, cfg, now, *, replay_waiting=False):
            out = real(state, cfg, now, replay_waiting=replay_waiting)
            if state and state.get('chunks') and state['chunk_index'] == len(state['chunks']) - 1:
                state['completed'] = True                     # the mutant: "completed" while the last portion waits
            return out
        mp.setattr(EchoEngine, '_issue', staticmethod(issue))

    def scenario(d):
        answered(d)
        while d.cue_ready() is not None:
            d.ack()
    broken(monkeypatch, scenario, r'\[S13\]', patch)


def test_the_invariant_checks_catch_a_repeat_that_calls_the_model(monkeypatch):
    from echo_sync.native_media_socket import NativeMediaSocket

    def patch(mp):
        real = NativeMediaSocket.actions

        async def actions(self, items):
            if any(a['type'] == 'speak' for a in items):
                await self.source.send('E', b'{}')              # the mutant: every spoken portion costs a model call
            return await real(self, items)
        mp.setattr(NativeMediaSocket, 'actions', actions)

    def scenario(d):
        answered(d)
        d.repeat('повтори')
    broken(monkeypatch, scenario, r'\[S9\]', patch)


def test_the_invariant_checks_catch_a_final_answer_without_a_first_portion(monkeypatch):
    from echo_sync import controlled_media

    def scenario(d):
        d.ask(INERTIA)
        d.assistant_begin(2)
        d.assistant_done()
    broken(monkeypatch, scenario, r'\[S8\]', lambda mp: patch_controller(mp, 'first_cue', lambda *a, **k: None))


def test_the_invariant_checks_catch_a_reconnect_that_moves_the_cursor(monkeypatch):
    import json
    import sqlite3
    from echo_sync.controlled_media import ControlledMedia

    def patch(mp):
        real = ControlledMedia.__init__

        def init(self, path, *args, **kwargs):
            real(self, path, *args, **kwargs)
            state = self.state()
            if state and state.get('chunks') and not state.get('completed'):
                state['chunk_index'] += 1                       # the mutant: opening a call moves the cursor
                with sqlite3.connect(str(path)) as db:
                    db.execute('UPDATE sessions SET state=? WHERE session_id=?',
                               (json.dumps(state, ensure_ascii=False), self.session_id))
        mp.setattr(ControlledMedia, '__init__', init)

    def scenario(d):
        answered(d)
        d.reconnect()
    broken(monkeypatch, scenario, r'\[S10\]', patch)


def test_the_invariant_checks_catch_an_exception_in_the_dispatch(monkeypatch):
    from echo_sync.voice_turns import FramelessTurns

    def patch(mp):
        real = FramelessTurns.apply

        def apply(self, event):
            if event.get('type') == 'turn.delta':
                raise RuntimeError('mutant')
            return real(self, event)
        mp.setattr(FramelessTurns, 'apply', apply)

    def scenario(d):
        d.ask(INERTIA)
        d.assistant_begin(1)
        d.assistant_delta()
    broken(monkeypatch, scenario, r'\[S11\]', patch)


def test_the_invariant_checks_catch_audio_while_the_user_is_speaking(monkeypatch):
    from echo_sync.native_media_socket import NativeMediaSocket

    def scenario(d):
        at_the_frontier(d)
        d.dictate(TOPICS[1])
        while d.assistant_can_stream():                         # text arrives while the user speaks (WAVE 2: the next portion
            d.assistant_delta()                                 # is committed once three portions follow it, not after one delta)
        d.silence(1)
    broken(monkeypatch, scenario, r'\[S12\]', lambda mp: mp.setattr(NativeMediaSocket, '_can_play', lambda self, cue=None: True))


def test_the_invariant_checks_catch_a_silent_cloud_that_is_never_reported(monkeypatch):
    from echo_sync.controlled_media import ControlledMedia

    def scenario(d):
        d.ask(INERTIA)                                          # the cloud sends nothing, nobody speaks
        d.silence(12)
        assert d.stats['answer_reports'] == 1 and d.stopped, 'the real code reports it once, and the question is over'
    broken(monkeypatch, scenario, r'\[S14\].*not reported', lambda mp: mp.setattr(ControlledMedia, '_answer_watchdog', lambda self, now: []))


def test_the_invariant_checks_catch_a_report_that_comes_before_the_wait_is_over(monkeypatch):
    from echo_sync.controlled_media import ControlledMedia

    def patch(mp):
        real = ControlledMedia.__init__

        def init(self, *args, **kwargs):
            real(self, *args, **kwargs)
            self.answer_wait_seconds = 2.0                      # the mutant: gives the question up after 2 s
        mp.setattr(ControlledMedia, '__init__', init)

    def scenario(d):
        d.ask(INERTIA)
        d.silence(3)
    broken(monkeypatch, scenario, r'\[S14\].*before the 8 s wait', patch)


def test_the_invariant_checks_catch_a_report_for_a_question_that_was_answered(monkeypatch):
    from echo_sync.controlled_media import ControlledMedia

    def mutant(self, now):
        if self.question_id and now - self.question_clock >= 8:   # ignores that a cue was made
            epoch = self.epoch
            self.epoch += 1
            self.question_id = None
            return [{'type': 'unanswered', 'epoch': epoch, 'reason': 'no_assistant_turn'}]
        return []

    def scenario(d):
        answered(d)
        d.silence(9)
    broken(monkeypatch, scenario, r'\[S14\].*waiting for its first cue', lambda mp: mp.setattr(ControlledMedia, '_answer_watchdog', mutant))


# =====================================================================================================
# Behaviour that must hold (these pass today and pin the neighbourhood of the open defects)
# =====================================================================================================

def test_an_unconfirmed_portion_is_spoken_again_after_the_silence_window():
    d = Dialogue()
    try:
        first = answered(d)
        again = d.silence(7)
        # UX-trace: the calm profile defaults - ONE repeat, 6 s after the portion ended (was 3 s and up to three times)
        assert [c.text for c in again] == [first.text]
        assert all(c.snap['index'] == 0 for c in again)
        assert d.silence(30) == []                                        # the cap: the prompter waits for the listener
    finally:
        d.close()


def test_the_next_text_after_a_repeat_at_the_frontier_is_spoken_once():
    d = Dialogue()
    try:
        at_the_frontier(d)
        index = d.snap()['index']
        spoken = []
        while d.snap()['waiting'] and d.assistant_can_stream():
            spoken += d.assistant_delta()
        spoken += d.assistant_done() if d.assistant_open() else []
        assert d.stats['frontier_releases'] == 1 and d.snap()['index'] == index + 1
        assert [c.snap['index'] for c in spoken] == [index + 1]            # exactly one cue, for the next portion
    finally:
        d.close()


def test_text_that_arrives_while_the_user_speaks_is_parked_and_played_when_he_stops():
    d = Dialogue()
    try:
        at_the_frontier(d)
        index = d.snap()['index']
        d.dictate(TOPICS[1])
        while d.assistant_can_stream() and not d.snap()['index'] > index:
            assert d.assistant_delta() == []                               # nothing is played over the user
        assert d.w.wire.pending_cue is not None and d.stats['parked_cues'] >= 1
        d.finish_dictation_without_a_question('ну')                        # a cough, not a question
        assert d.w.cues[-1].snap['index'] == index + 1 and d.w.wire.pending_cue is None
    finally:
        d.close()


def test_repeat_stop_and_a_new_question_in_sequence():
    d = Dialogue()
    try:
        answered(d)
        assert d.repeat('повтори')[0].text == 'свойство тела сохранять своё состояние движения или покоя.'   # F1: the sentence
        d.stop()
        assert d.silence(30) == []
        answered(d, TOPICS[3])
        assert d.w.cues[-1].text.startswith('Великая Отечественная')        # WAVE 2 / L2: a restating opening is cued in short units
    finally:
        d.close()


# =====================================================================================================
# OPEN DEFECTS: minimal reproductions. xfail(strict) so that a fix has to remove the mark.
# =====================================================================================================

def soak(world, seconds):
    """Everything spoken during ``seconds`` of silence."""
    start = len(world.cues)
    world.advance(seconds, step=1.0)
    return world.cues[start:]


def asked_and_answered(world, question=INERTIA.question, answer=INERTIA.answer):
    world.feed(turn_done('u1', 'user', question))
    world.feed(turn_done('a1', 'assistant', answer))


# DEF-STATE-01 (an unconfirmed portion was auto-repeated forever: ~170 repeats in 600 s) was fixed by Wave 2 / Task 2 (a544477):
# the xfail marker is gone, this is an ordinary test now.
def test_auto_repeats_of_an_unconfirmed_portion_are_bounded():
    w = World()
    try:
        asked_and_answered(w)
        first = w.cues[0]
        repeats = [c for c in soak(w, 600) if c.text == first.text]
        assert len(repeats) <= 10, f'{len(repeats)} automatic repeats of {first.text!r} in 10 minutes of silence'
    finally:
        w.close()


# DEF-STATE-02 (the «user is speaking» flag had no timeout: three triggers silenced the call for good) was fixed by Wave 2 /
# Task B (HEARING_SECONDS, and a retransmitted turn.created is no start of speech): the three markers are gone.
def test_a_repeated_turn_created_does_not_leave_the_call_listening_for_good():
    w = World()
    try:
        start = turn_created('u1', 'user', 'Что')
        w.feed(start)
        asked_and_answered(w)
        w.feed(start)                                       # the provider repeats an event it sent before
        assert soak(w, 30), 'nothing was spoken for 30 s: the call listens to a user who is not speaking'
    finally:
        w.close()


def test_a_barge_in_without_a_transcript_does_not_leave_the_call_listening_for_good():
    w = World()
    try:
        asked_and_answered(w)
        w.client({'type': 'response.cancel'})
        assert soak(w, 60), 'nothing was spoken for 60 s after a barge-in that produced no words'
    finally:
        w.close()


def test_a_question_that_is_never_finished_does_not_leave_the_call_listening_for_good():
    w = World()
    try:
        asked_and_answered(w)
        w.feed(turn_created('u2', 'user', 'Что такое фотосинтез'))
        assert soak(w, 60), 'nothing was spoken for 60 s after a partial question that never finished'
    finally:
        w.close()


# DEF-STATE-03 (a second, different final of the current question muted every later portion) was fixed by Wave 2 / Task B: the
# ledger takes a revised user final as a revision, not a conflict (tests/test_revised_final.py holds the rest of the contract).
def test_a_revised_final_of_the_current_question_does_not_mute_the_call():
    w = World()
    try:
        asked_and_answered(w)
        first = w.cues[0]
        w.feed(turn_done('u1', 'user', INERTIA.question.rstrip('?') + ' пожалуйста?'))   # same id, new text
        w.feed(turn_done('k1', 'user', first.text))
        assert len(w.cues) >= 2 and w.cues[1].text != first.text, \
            f"after the repeat the next portion was not spoken (cursor {w.state()['chunk_index']}, " \
            f"parked: {w.wire.pending_cue is not None})"
    finally:
        w.close()


CLARIFICATION = 'Потому что масса тела определяет, как сильно оно сопротивляется изменению скорости.'


# DEF-STATE-04 (a question whose last word is a function word - every bare «Почему?», «Как?» - was never answered: the
# continuation hold had no end) was fixed by Wave 2 / Task 1 fix round 1 (bb879e0): five of the six cases are ordinary tests now.
# The sixth, bare «Как?», passed too until Task A (t-ack) was merged, and keeps a strict marker: Task A deliberately reads
# «как?» as "what did you say?" while a portion of the previous answer waits (here: the first answer is being repeated), so the
# portion is replayed and the follow-up is not answered. Which one changes - this scenario or that rule - is a decision for
# the owner of the contract (integ-report.md); the marker is strict, so it has to go together with the decision.
@pytest.mark.parametrize('question,answer', [
    ('Почему?', CLARIFICATION),
    ('Почему так?', CLARIFICATION),
    ('Зачем?', CLARIFICATION),
    pytest.param('Как?', CLARIFICATION, marks=pytest.mark.xfail(
        strict=True, reason='DEF-STATE-04: a bare «Как?» while a portion of the previous answer waits is read as "what did '
                            'you say?" (Task A, test_ack_commands.py) and the portion is replayed: the follow-up is not '
                            'answered; this scenario and that rule disagree')),
    ('Когда?', CLARIFICATION),
    ('Объясни разницу между', 'Масса постоянна везде, а вес зависит от притяжения планеты.'),
], ids=['why', 'why_so', 'what_for', 'how', 'when', 'between'])
def test_a_question_that_ends_on_a_function_word_is_still_answered(question, answer):
    w = World()
    try:
        asked_and_answered(w)                                # a first question, answered and being repeated
        before = len(w.cues)
        w.feed(turn_done('u2', 'user', question))
        w.feed(turn_created('a2', 'assistant', answer.split()[0]))
        w.feed(turn_done('a2', 'assistant', answer))
        soak(w, 10)                                          # far beyond the 3.2 s continuation window
        assert any(norm(c.text) in norm(answer) for c in w.cues[before:]),             f'the complete answer to {question!r} was never spoken (cues: {[c.text for c in w.cues[before:]]})'
    finally:
        w.close()


@pytest.mark.xfail(strict=True, reason='DEF-STATE-07: a late repeat of an EARLIER portion that starts with a question '
                                       'word («Чем больше масса,») is taken as a new question and wipes the answer')
def test_a_late_repeat_of_an_earlier_portion_is_not_a_new_question():
    w = World()
    try:
        asked_and_answered(w)
        chunks = w.state()['chunks']
        for n in range(len(chunks) - 1):                     # the user confirms every portion up to the last one
            w.feed(turn_done(f'k{n}', 'user', w.cues[-1].text))
        assert w.state()['chunk_index'] == len(chunks) - 1 and chunks[-2].startswith('Чем')
        revision = w.state()['revision']
        w.feed(turn_done('late', 'user', chunks[-2]))        # the previous portion once more (echo, stumble, retransmit)
        state = w.state()
        assert (state['revision'], state['completed']) == (revision, False),             'the answer was thrown away as if a new question had been asked'
    finally:
        w.close()


# DEF-STATE-05 (a user turn between the question and the first event of its answer stole the answer) was fixed by Wave 2 / Task B
# (ControlledMedia._aside; tests/test_answer_owner.py holds the rest of the contract).
def test_a_word_from_the_user_before_the_answer_arrives_does_not_swallow_the_answer():
    w = World()
    try:
        w.feed(turn_done('u1', 'user', INERTIA.question))
        w.feed(turn_done('u2', 'user', 'повтори'))          # or «ну», a cough, the interviewer's voice
        w.feed(turn_created('a1', 'assistant', 'Инерция'))
        w.feed(turn_done('a1', 'assistant', INERTIA.answer))
        assert w.cues, 'the final answer for the question never produced a first portion'
    finally:
        w.close()


# DEF-STATE-09 fixed by W1F-B's stop ruling (3 Nov): «стоп» at the live frontier pauses and keeps the whole answer (strict xfail removed).
def test_a_stop_at_the_live_frontier_is_a_pause_and_a_repeat_then_speaks_the_current_portion():
    """Pre-existing on 66b29f1 for every topic of the machine (W1F-A reproduced it there); the machine found it once W1F-A moved
    where the planner cuts. The stop/pause logic lives in controlled_media/engine, not in W1F-A's files."""
    d = Dialogue()
    try:
        at_the_frontier(d)
        d.stop()
        d.repeat('повтори')
    finally:
        d.close()


# DEF-STATE-06 («повтори» was silent while the stream waits for the next text) was fixed by Wave 2 / Task B (a replay cue at the
# live frontier is authorized).
def test_repeat_works_while_the_stream_waits_for_the_next_text():
    d = Dialogue()
    try:
        at_the_frontier(d)
        last = d.w.cues[-1]
        spoken = d.repeat('повтори')
        assert spoken and d.w.cues[-1].text == last.text, '«повтори» at the live frontier was not answered'
    finally:
        d.close()


# DEF-STATE-08 (a new portion replaced a half-played one without output_audio_buffer.clear) was fixed by Wave 2 / Task B
# (tests/test_supersede_clear.py).
def test_a_command_that_arrives_mid_playout_does_not_leave_two_portions_in_flight():
    w = World()
    try:
        w.feed(turn_done('u1', 'user', INERTIA.question))
        w.feed(turn_done('a1', 'assistant', INERTIA.answer), settle=False)
        w.pump_until(3)
        assert w.open is not None and w.open.audio_frames >= 3          # the first portion is half played
        w.feed(turn_done('u2', 'user', 'повтори'))                       # a final with no turn.created before it
        assert not w.violations, w.violations[0]
    finally:
        w.close()


def test_every_tolerated_defect_has_its_xfail_test():
    """The tolerance list and the xfail marks must not drift apart."""
    import inspect
    import sys
    source = inspect.getsource(sys.modules[__name__])
    for defect in TOLERATED:
        assert f"reason='{defect}:" in source, f'{defect} has no xfail test'
