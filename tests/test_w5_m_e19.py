"""W5 package M, E19: what a speaker said under a condition or a negation survives the clipping of its line to the room of the card (MST T04: the conditions survive the compression): «только если акт приёмки
подписан», «а не просто по факту» stand together, not cut right behind the «если». Before: a line was cut around the stopwords of the question («мы», «за») and lost the clause."""
import helpers_night_memory as M
from echo_sync import v6_memory as V
from echo_sync.conversation_ledger import ConversationLedger
from echo_sync.textutil import norm_words, stems

COND_LONG = ('Значит так, по поставке оборудования для склада в Казани мы договорились о следующем: партию мы принимаем по частям, первая часть приходит в понедельник на основной склад, '
             'вторая часть приходит позже на запасной склад, и при этом оплату мы делаем только если акт приёмки подписан обеими сторонами, а не просто по факту отгрузки.')
CONDITION = 'только если акт приёмки подписан обеими сторонами'
NEGATION = 'а не просто по факту отгрузки'
Q_HOW = 'На каких условиях мы делаем оплату?'


import pytest
pytestmark = pytest.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)


def tag(n):
    return 'метка' + ''.join(chr(ord('а') + int(d)) for d in '%02d' % n)


def filler(n):
    return '%s %s' % (tag(n), ' '.join(M.VOCAB[(n * 7 + k * 3) % len(M.VOCAB)] for k in range(14)))


def test_e19_a_clipped_line_keeps_the_condition_and_the_negation_together():
    keys = frozenset(stems(norm_words(Q_HOW)))
    body = V.window(COND_LONG, 217, keys)
    assert body.startswith('…') and CONDITION in body and NEGATION in body, body


def test_e19_the_numerals_of_a_clipped_line_stay_with_what_they_count():
    text = ('мы долго обсуждали разные вещи про склад и про машины и про людей, и про то, как всё будет идти дальше, и в конце сошлись на том, что скидка составит пять процентов, '
            'а заказ должен быть больше трёхсот единиц, и ещё немного слов про погоду и дорогу домой')
    body = V.window(text, 120, frozenset())
    assert 'пять процентов' in body or 'трёхсот единиц' in body, body


def test_e19_a_whole_line_is_told_whole():
    assert V.window('нет, не пятьсот', 80, frozenset(['цен'])) == 'нет, не пятьсот'


def test_e19_the_card_tells_the_condition_of_a_long_utterance_in_one_piece():
    led = ConversationLedger()
    led.user_final('c', COND_LONG, final_rev=1, at=60.0)
    for n in range(120):
        led.user_final('t%d' % n, filler(n), final_rev=1, at=90.0 + 30.0 * n)
    card = V.build_card(led, Q_HOW)
    told = [line for part in ('retrieved', 'exact') for line in card.lines.get(part, ()) if 'оплату' in line]
    assert told and CONDITION in told[0] and NEGATION in told[0], told


def test_e19_through_the_controller_the_condition_said_at_minute_5_stands_whole_in_the_request_at_minute_40(tmp_path):
    call = M.Call(tmp_path, mind=M.mind)
    try:
        call.go(1.0)
        call.say(M.OPENING)
        call.go(5.0)
        call.say(COND_LONG)
        call.traffic(40.0)
        call.say(Q_HOW)
        call.pump(2.0)
        request = call.request_for(Q_HOW, after=39.0)
    finally:
        call.close()
    text = M.whole(request)
    assert CONDITION in text and NEGATION in text, M.memory_of(request)[:900]
    line = M.lines_with(request, CONDITION)[0]
    assert line.startswith('- 5 мин, '), line
