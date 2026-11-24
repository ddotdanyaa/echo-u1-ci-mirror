"""night-bench, the finding «карточка растёт квадратом от числа реплик с числами» (671d2fe): ``v6_memory._exact`` compares every utterance that carries a number
with every one already chosen (two sets built per pair, line 519), at every model request, on the thread of the call's loop (``FastText._start`` -> ``Memory.apply``),
in shadow as well as on. The growth tests of tests/test_v6_memory_attack.py speak pseudo-words with three numbers in 4000 utterances, so they never see it.
Here the same test (``test_growth_time_of_a_request_does_not_grow_faster_than_the_call``, the same bound) on a call whose utterances carry numbers, as a talk about
prices, dates and quantities does. Red on 671d2fe. Nothing here is a measure of the laptop."""
import random
import time

from echo_sync import v6_memory as V
from echo_sync.conversation_ledger import ConversationLedger

THINGS = ('цена за штуку', 'скидка на заказ', 'срок поставки', 'аванс по договору', 'остаток на складе', 'доставка до Казани', 'штраф за просрочку', 'объём партии')


def a_call_about_numbers(n, minutes, seed=11, share=0.4):
    """``n`` finals over ``minutes``: ``share`` of them name a thing and a number (and a quarter of those correct the number just said), the rest are the pseudo-words of ``realistic_call``."""
    rng = random.Random(seed)
    vocab = [''.join(rng.choice('абвгдежзиклмнопрстуфхцчшэюя') + rng.choice('аеиоуы') for _ in range(rng.randint(2, 4))) for _ in range(1500)]
    led, last = ConversationLedger(), None
    for i in range(n):
        if rng.random() < share:
            thing, value = rng.choice(THINGS), rng.randint(2, 900)
            text = 'нет, не %d, а %d' % (last, value) if last is not None and rng.random() < 0.25 else '%s %d' % (thing, value)
            last = value
        else:
            text = ' '.join(rng.choice(vocab) for _ in range(rng.randint(5, 14)))
        led.user_final('t%d' % i, text, final_rev=1, at=i * minutes * 60.0 / n)
    return led


def per_request(n):
    led = a_call_about_numbers(n, minutes=n * 180 // 4000)
    proj = V.Projection(led)
    V.build_card(led, 'цена', since=0.0, projection=proj)
    ts = []
    for k in range(8):
        led.user_final('n%d' % k, 'новая реплика про цену %d' % k, final_rev=1, at=1e5 + k)
        t = time.perf_counter()
        V.build_card(led, 'какая цена за штуку', since=0.0, projection=proj)
        ts.append(time.perf_counter() - t)
    return sum(ts) / len(ts)


def test_growth_time_of_a_request_does_not_grow_faster_than_the_call_when_the_talk_carries_numbers():
    small, big = per_request(500), per_request(3000)
    assert big < small * 6 * 2.0, 'six times the call, %.0f times the time of a request: %.1f ms at 500 finals, %.1f ms at 3000' % (big / small, small * 1000, big * 1000)


def test_growth_a_request_at_the_end_of_a_call_about_numbers_keeps_the_bound_of_the_growth_test():
    """tests/test_v6_memory_attack.py: «assert mean < 0.15, 'every new final rebuilds the whole projection ... (an N95 is several times slower)'»: the same bound, 4000 finals, the projection kept."""
    led = a_call_about_numbers(4000, minutes=180)
    proj = V.Projection(led)
    V.build_card(led, 'какая цена за штуку', since=0.0, projection=proj)
    ts = []
    for k in range(10):
        led.user_final('n%d' % k, 'новая реплика про цену за штуку %d' % k, final_rev=1, at=10800.0 + 3 * k)
        t = time.perf_counter()
        V.build_card(led, 'какая цена за штуку', since=0.0, projection=proj)
        ts.append(time.perf_counter() - t)
    mean = sum(ts) / len(ts)
    assert mean < 0.15, 'a request at the end of a call of 4000 utterances, 40%% of them with a number: %.3f s on the loop of the call (an N95 is several times slower)' % mean
