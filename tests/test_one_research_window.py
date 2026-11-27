"""one-research (CONTEXT, OWNER_REQUIREMENTS U-new-8 «окно последних 15 реплик плюс сводка следующего окна»): the card of v6_memory carries the last START['window']
utterances of BOTH sides in spoken order (what the newest exchanges did not already show), and one brief line of the window before it. Ideas: ericwang915/interview-copilot
app.js:487 (``history.slice(-15)`` with speaker labels), livekit/agents turn detector (last 6 turns), HF speech-to-speech LLM/chat.py:1373 (older turns summarised, the last kept)."""
import re

from echo_sync import v6_memory as V
from echo_sync.conversation_ledger import ConversationLedger

WORDS = 'альфа бета гамма дельта эпсилон дзета эта тета йота каппа лямбда мю ню кси омикрон пи ро сигма тау ипсилон фи хи пси омега'.split()


def chatter(n, answer_every=0):
    """n room utterances, each with its own first word (``u<i> …``); every ``answer_every``-th has our answer."""
    led = ConversationLedger()
    for i in range(n):
        led.user_final('t%d' % i, 'u%d %s %s реплика' % (i, WORDS[i % len(WORDS)], WORDS[(i * 7) % len(WORDS)]), final_rev=1, at=10.0 * i)
        if answer_every and i % answer_every == answer_every - 1:
            led.answer('a%d' % i, 'ответ%d на это' % i, tid='t%d' % i, at=10.0 * i + 2)
    return led


def window_lines(card):
    return card.lines.get('window', [])


def test_window_holds_the_last_15_utterances_in_order():
    """Every one of the last 15 is in the card exactly once (the exchanges, retrieval or exact things may hold some: then the window does not repeat them); the window keeps spoken order."""
    card = V.build_card(chatter(40), 'что дальше')
    assert V.HEAD['window'] in card.text
    for i in range(40 - V.START['window'], 40):
        assert len(re.findall(r'\bu%d\b' % i, card.text)) == 1, i
    order = [int(l.split('«', 1)[1].split()[0][1:]) for l in window_lines(card)]
    assert order == sorted(order) and order[-1] >= 40 - V.START['window'] and card.parts['window'] >= 8


def test_brief_of_the_window_before():
    card = V.build_card(chatter(40), 'что дальше')
    brief = card.lines.get('brief', [])
    assert len(brief) == 1 and V.HEAD['brief'] in card.text
    assert 'u10' in brief[0] and 'u24' in brief[0] and 'u9 ' not in brief[0] and 'u25' not in brief[0]
    assert len(brief[0]) <= V.START['brief_chars']


def test_both_sides_are_in_the_window():
    card = V.build_card(chatter(30, answer_every=3), 'что дальше')
    got = '\n'.join(window_lines(card) + card.lines.get('exchanges', []))
    assert 'ответ29' in got and 'u29' in got
    assert any(V.OURS in l for l in window_lines(card) + card.lines.get('brief', [])), 'our answers are replicas of the window or its brief, labelled as ours'


def test_no_line_twice():
    card = V.build_card(chatter(40, answer_every=4), 'u35 альфа')
    shown = [l for name in ('exchanges', 'window', 'retrieved', 'exact', 'outline') for l in card.lines.get(name, [])]
    bodies = [l.split('«', 1)[-1] for l in shown if '«' in l]
    assert len(bodies) == len(set(bodies))


def test_short_call_is_as_before():
    """Everything a short call said is in the exchanges already: no window, no brief, the card as before."""
    led = ConversationLedger()
    led.user_final('t0', 'какая скидка на заказ', final_rev=1, at=1.0)
    led.answer('a0', 'Пять процентов.', tid='t0', at=3.0)
    card = V.build_card(led, 'а доставка')
    assert V.HEAD['window'] not in card.text and V.HEAD['brief'] not in card.text
    assert card.parts['window'] == 0 and card.parts['brief'] == 0


def test_budget_holds():
    card = V.build_card(chatter(200, answer_every=2), 'что дальше', budget=1500)
    assert card.chars <= 1500
