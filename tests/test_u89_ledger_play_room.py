"""U89 (c): the playback rows (X-CUE) of a long call take no room from the conversation rows of the ledger (LEDGER_HOT = 6000): a cue is one row each, a call speaks
thousands of them, and they used to push the listener's finals and our answers out of memory long before the conversation itself was that long."""
from echo_sync.conversation_ledger import ConversationLedger, LEDGER_HOT, PLAY, USER, ANSWER


def talk(led, n, cues_per_turn):
    for i in range(n):
        led.user_final('t%d' % i, 'слово%d' % i, final_rev=1, at=float(i * 10))
        led.answer('a%d' % i, 'ответ%d' % i, tid='t%d' % i, at=float(i * 10 + 2))
        for c in range(cues_per_turn):
            led.play_began('c%d_%d' % (i, c), 'порция %d' % c, float(i * 10 + 3 + c))
            led.play_done('c%d_%d' % (i, c), float(i * 10 + 3.5 + c))


def kinds(led):
    out = {}
    for r in led.records():
        out[r.kind] = out.get(r.kind, 0) + 1
    return out


def test_playback_rows_do_not_evict_conversation_rows_small_ledger():
    led = ConversationLedger(hot=60)
    talk(led, 25, 8)                       # 50 conversation rows, 200 cues
    got = kinds(led)
    assert got[USER] == 25 and got[ANSWER] == 25, got
    assert led.user_words(3) == ['слово22', 'слово23', 'слово24']      # the readers go on


def test_playback_rows_do_not_evict_conversation_rows_at_the_real_cap():
    led = ConversationLedger()
    talk(led, LEDGER_HOT // 2 - 100, 3)    # 5800 conversation rows and 8700 cues together are more than the cap
    got = kinds(led)
    assert got[USER] == got[ANSWER] == LEDGER_HOT // 2 - 100, got


def test_the_conversation_rows_are_still_capped_and_the_oldest_go_first():
    led = ConversationLedger(hot=40)
    talk(led, 40, 2)                       # 80 conversation rows against a cap of 40
    users = [r.tid for r in led.records() if r.kind == USER]
    assert len(users) + len([r for r in led.records() if r.kind == ANSWER]) == 40 and users[-1] == 't39'


def test_the_newest_cues_stay_readable_and_the_older_ones_are_bounded():
    led = ConversationLedger(hot=60)
    talk(led, 25, 8)
    plays = [r for r in led.records() if r.kind == PLAY]
    assert 0 < len(plays) <= 60 // 4 and plays[-1].ref == 'c24_7'
    assert led.played_words(2) == ['порция', '7']
    assert led.last_sentence('played') == 'порция 7'


def test_a_revision_still_finds_its_predecessor_after_the_cues_were_dropped():
    led = ConversationLedger(hot=60)
    talk(led, 25, 8)
    led.user_final('t24', 'новое', final_rev=2, at=300.0)
    mine = [r for r in led.records() if r.kind == USER and r.tid == 't24']
    assert [(r.final_rev, r.superseded) for r in mine] == [(1, True), (2, False)]
