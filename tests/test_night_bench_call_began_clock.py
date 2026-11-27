"""night-bench, the finding «часы начала звонка» (671d2fe): the card of v6_memory and the topic recap are given the start of the call on the ENGINE's clock
(``ControlledMedia.begin_call``: ``self.call_began=self.engine.clock()``, time.time), while the ledger stamps its records with the CONTROLLER's clock
(``_ledger_turn``: ``at=self.clock()``, time.monotonic). ``Projection._rebuild`` / ``_append`` keep a record only when ``r.at >= since``, ``ConversationLedger.recap``
when ``q.at >= since``: on a call that begins later than RECONNECT_WINDOW_S after the last portion of the call before (every new call of the phone's one session)
no record passes, the card is empty for the whole call and v6_memory=on changes nothing. The real controller with its default clocks; no stand, no network.
Red on 671d2fe. The owner of the files decides the fix (one clock for both, or ``since`` given on the ledger's clock)."""
import time

from echo_sync import v6_memory as V
from echo_sync.controlled_media import RECONNECT_WINDOW_S, ControlledMedia

SET = {'conversation_ledger': 'memory', 'topic_recap': 'on'}
COND = 'условие такое скидка пять процентов только если заказ больше трёхсот единиц'
ASK = 'напомни какая скидка по условию про заказ'
TALK = (('Сколько будет шесть умножить на семь?', 'Сорок два.'), ('В каком году было крещение Руси?', 'Крещение Руси в 988 году.'), ('Когда основали Петербург?', 'В 1703 году.'))


def turn(tid, role, text):
    return {'type': 'turn.done', 'turn': {'id': tid, 'role': role, 'transcript': text}}


def answered(c, n, question, answer):
    c.provider(turn(f'u{n}', 'user', question))
    c.grounding(c.epoch, [{'url': 'https://example.org', 'text': 'source'}])
    c.provider(turn(f'a{n}', 'assistant', getattr(c, 'answer_marker', '') + answer))


def a_call(tmp_path, later_s):
    """The session's second call, ``later_s`` seconds of the wall clock after an answer of its first call; the condition and some talk are said in it."""
    first = ControlledMedia(tmp_path / 's.db', session_id='s', settings=SET)
    first.begin_call()
    answered(first, 0, 'Почему меняются времена года?', 'Наклон земной оси меняет освещение.')
    c = ControlledMedia(tmp_path / 's.db', session_id='s', settings=SET)
    c.engine.clock = lambda: time.time() + later_s
    c.begin_call()
    c.provider(turn('k1', 'user', COND))
    for n, (question, answer) in enumerate(TALK, 1):
        answered(c, n, question, answer)
    return c


def found(card):
    return any('пять процентов' in line for part in card.lines.values() for line in part)


def test_the_control_a_reconnect_inside_the_window_has_the_condition_in_the_card(tmp_path):
    c = a_call(tmp_path, 5.0)
    assert c.call_began is None, 'the same conversation: the start of the call is not moved'
    assert found(V.build_card(c.convo, ASK, since=c.call_began))


def test_a_new_call_of_the_session_has_what_was_said_in_it_in_the_card(tmp_path):
    c = a_call(tmp_path, RECONNECT_WINDOW_S + 3480.0)          # the next call, an hour later
    assert c.call_began is not None, 'precondition: a new call (the answer of the call before is stale)'
    assert found(V.build_card(c.convo, ASK, since=None)), 'precondition: the ledger of this call has the condition'
    card = V.build_card(c.convo, ASK, since=c.call_began)
    assert found(card), ('the card of a new call is empty: call_began=%.1f is the engine\'s wall clock, the ledger\'s records are at %.1f..%.1f of the controller\'s clock; parts %s'
                         % (c.call_began, min(r.at for r in c.convo.records()), max(r.at for r in c.convo.records()), dict(card.parts)))
