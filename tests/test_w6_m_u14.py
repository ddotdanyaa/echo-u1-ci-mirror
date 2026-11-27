"""W6 package M, U14: the topic of a long call reaches the model by ONE path, the card of v6_memory. The old second path («Ранее в этом разговоре»: ``ConversationLedger.recap`` / ``fast_recap`` /
``channel.recap``) was a shadow (the card cut it from the request whenever it was not empty, and it is never empty when the recap is) and is gone. Through the real controller (the stand of
test_night_memory_stand)."""
import re
from pathlib import Path

import helpers_night_memory as M
from echo_sync import fast_text as FT
from echo_sync.conversation_ledger import ConversationLedger
from echo_sync.controlled_media import ControlledMedia

ROOT = Path(__file__).resolve().parent.parent / 'echo_sync'


def tag(n):
    return 'метка' + ''.join(chr(ord('а') + int(d)) for d in '%02d' % n)


def filler(n):
    return '%s %s' % (tag(n), ' '.join(M.VOCAB[(n * 7 + k * 3) % len(M.VOCAB)] for k in range(14)))


def test_u14_the_request_of_minute_40_has_the_card_and_never_the_old_recap_block(tmp_path):
    call = M.Call(tmp_path, mind=M.mind)
    try:
        call.go(1.0)
        for n in range(1, 21):                       # 20 exchanges: far more than the 6 of the old window
            call.say(filler(n))
            call.pump(20.0, 1.0)
        call.say(M.Q_PRICE)
        call.pump(2.0)
        request = call.request_for(M.Q_PRICE)
        memory = M.memory_of(request)
        whole = M.whole(request)
    finally:
        call.close()
    assert memory and tag(1) in memory, ('the first utterance of the call stands in the card', memory[:300])
    assert 'Ранее в этом разговоре' not in whole, 'the old recap block is a second path of the topic'


def test_u14_no_second_path_of_the_topic_stands_in_the_code():
    assert not hasattr(ConversationLedger, 'recap') and not hasattr(ControlledMedia, 'fast_recap')
    assert not hasattr(FT.FastText(lambda request, cancelled: iter(()), instructions=lambda *a: '', history=lambda: []), 'recap')
    for path in ROOT.glob('*.py'):
        text = path.read_text(encoding='utf-8')
        assert not re.search(r'\bfast_recap\b|\bchannel\.recap\b|\.recap\(|_recap_key|Ранее в этом разговоре', text), path.name
