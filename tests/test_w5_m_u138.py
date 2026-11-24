"""W5 package M, U138: the memory is always on and the last 15 replies are ALL in the request of a long call, the 15 before them in the one line of the brief (OWNER_REQUIREMENTS U-new-8). Through the real controller
(``tests/helpers_night_memory.Call``, the stand of test_night_memory_stand) and through ``v6_memory`` itself. Before: the window took 25 % of the budget, so replies of a spoken length (100 characters) filled it with
5 to 8 lines and the others of the last 15 stood nowhere."""
import re

import helpers_night_memory as M
from echo_sync import v6_memory as V
from echo_sync.conversation_ledger import ConversationLedger


def tag(n):
    """A word that is only this utterance's (letters only: no digit and no numeral makes it a clue of its own)."""
    return 'метка' + ''.join(chr(ord('а') + int(d)) for d in '%02d' % n)


def filler(n):
    return '%s %s' % (tag(n), ' '.join(M.VOCAB[(n * 7 + k * 3) % len(M.VOCAB)] for k in range(14)))


def test_u138_the_last_15_replies_are_all_in_the_card_when_they_are_of_a_spoken_length():
    led = ConversationLedger()
    for n in range(60):
        led.user_final('t%d' % n, filler(n), final_rev=1, at=20.0 * n)
    card = V.build_card(led, 'что дальше')
    for n in range(45, 60):                                    # the last 15 rows of the call
        assert re.search(r'\b%s\b' % tag(n), card.text), n
    for n in range(30, 45):                                    # the 15 before them: the brief
        assert re.search(r'\b%s\b' % tag(n), '\n'.join(card.lines['brief'])), n
    assert card.chars <= V.START['chars']


def test_u138_a_line_that_fits_is_not_clipped_and_the_window_is_in_spoken_order():
    led = ConversationLedger()
    for n in range(40):
        led.user_final('t%d' % n, 'коротко %s' % tag(n), final_rev=1, at=10.0 * n)
    card = V.build_card(led, 'что дальше')
    got = [re.search(r'метка\w+', line).group() for line in card.lines['window']]
    assert got == sorted(got) and all(line.endswith('»') for line in card.lines['window'])


def test_u138_through_the_controller_the_request_of_minute_40_holds_the_last_15_and_the_brief_of_the_15_before(tmp_path):
    call = M.Call(tmp_path, mind=M.mind)
    try:
        call.go(1.0)
        for n in range(1, 41):
            call.say(filler(n))
            call.pump(20.0, 1.0)
        call.say(M.Q_PRICE)
        call.pump(2.0)
        memory = M.memory_of(call.request_for(M.Q_PRICE))
    finally:
        call.close()
    missing = [n for n in range(27, 41) if tag(n) not in memory]
    assert not missing, ('the last 15 rows are the question and the fillers 27..40', missing, memory[:400])
    briefed = [n for n in range(12, 27) if tag(n) not in memory]
    assert not briefed, ('the brief of the 15 before them', briefed)


def test_u138_no_setting_switches_the_memory_off():
    from echo_sync import settings
    assert not [k for k, v in settings.DEFAULTS.items() if 'memory' in k and isinstance(v, bool)]
    assert all(isinstance(settings.DEFAULTS[k], int) for k in settings.DEFAULTS if k.startswith('v6_memory'))
