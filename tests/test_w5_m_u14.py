"""W5 package M, U14: the ledger is the one structure of the call (the room's words, our answers, the played cues, what the call holds): no second kind of record beside them (the ``cloud`` interim-text kind
and ``last_sentence`` had no reader)."""
from echo_sync import conversation_ledger as L
from echo_sync.conversation_ledger import ConversationLedger


def test_u14_the_ledger_has_one_kind_of_row_for_the_room_one_for_us_and_one_for_what_was_played():
    assert {L.USER, L.ANSWER, L.PLAY} == {'user', 'answer', 'play'}
    assert not hasattr(L, 'CLOUD') and not hasattr(ConversationLedger, 'cloud_text') and not hasattr(ConversationLedger, 'last_sentence')
    led = ConversationLedger()
    led.user_final('t1', 'раз два', final_rev=1, at=1.0)
    led.answer('a1', 'три', tid='t1', at=2.0)
    led.play_began('c1', 'три', 2.5, 0.5)
    assert {r.kind for r in led.records()} == {'user', 'answer', 'play'}
