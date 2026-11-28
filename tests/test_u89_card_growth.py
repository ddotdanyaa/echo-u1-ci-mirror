"""U89 (a): the memory card of a request costs LINEARLY in the length of the call, not with its square (v6_memory._exact in one pass, union-find, 13eceff): a call of 4500 replies costs a request about twice a call of 2250.
The growth ratio is compared, not milliseconds (a cloud box is no laptop, and a laptop number is not made here): the best of several requests per size, each after one more exchange, and a ratio a square would break (x4)."""
import random
import time

from echo_sync import v6_memory as V
from echo_sync.conversation_ledger import ConversationLedger
from test_v6_memory import PRICE_Q, sentence


def call(n, seed=3):
    """A call of ``n`` replies about prices and dates (the case that made the quadratic cost): a number in every seventh utterance."""
    rng, led = random.Random(seed), ConversationLedger(hot=10 * n)
    for i in range(n):
        led.user_final('t%d' % i, sentence(rng) + (' цена за штуку %d рублей до %d числа' % (rng.randint(100, 999), rng.randint(1, 28)) if i % 7 == 0 else ''), final_rev=1, at=i * 4.0)
        led.answer('a%d' % i, sentence(rng, 4), tid='t%d' % i, at=i * 4.0 + 2)
    return led


def request_s(n, repeats=5):
    led = call(n)
    proj = V.Projection(led)
    V.build_card(led, PRICE_Q, projection=proj)
    best = []
    for k in range(repeats):
        led.user_final('x%d' % k, 'новая реплика про скидку %d' % k, final_rev=1, at=n * 4.0 + k * 4)
        led.answer('y%d' % k, 'ответ', tid='x%d' % k, at=n * 4.0 + k * 4 + 2)
        start = time.perf_counter()
        card = V.build_card(led, PRICE_Q, projection=proj)
        best.append(time.perf_counter() - start)
    assert card.text
    return min(best)


def test_a_request_on_4500_replies_costs_about_twice_one_on_2250_not_four_times():
    small, big = request_s(2250), request_s(4500)
    assert big / small < 3.0, 'x%.1f (%.1f ms -> %.1f ms)' % (big / small, small * 1000, big * 1000)
