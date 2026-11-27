"""always-answer, step 1: ``reserve_text.Roads``, the ONE owner of the roads of text. The order (a rest is an order, never a ban), the walker (a road that fails or says nothing before its first word is
the turn of the next), the decision of the loop (``step``: the next road on NEXT_ROAD_S of silence, at once on a refusal, a stall on 2 * NEXT_ROAD_S, dead on ALL_DEAD_S or when no road is left), the silent losses (``lost``, STALLS)."""
import json
import threading

import pytest

from echo_sync import fast_text, reserve_text
from echo_sync import codex_road as CR
from echo_sync.reserve_text import PRIMARY, ReserveError, ReserveStream, Roads, Tried, Walk

G120, G20, GEM = ('GROQ_API_KEY', 'openai/gpt-oss-120b'), ('GROQ_API_KEY', 'openai/gpt-oss-20b'), ('GEMINI_API_KEY', 'gemini-3.5-flash-lite')
KEYS = {'GROQ_API_KEY': 'one', 'GEMINI_API_KEY': 'k'}


@pytest.fixture(autouse=True)
def _fresh():
    for table in (reserve_text._REST, reserve_text._BUDGET):
        table.clear()
    reserve_text._PRIMARY['until'] = 0.0
    yield
    for table in (reserve_text._REST, reserve_text._BUDGET):
        table.clear()
    reserve_text._PRIMARY['until'] = 0.0


def sse(*texts):
    return [f'data: {json.dumps({"choices": [{"delta": {"content": t}}]})}' for t in texts] + ['data: [DONE]']


def request():
    return fast_text.build_request('Когда была Полтавская битва?', instructions='Ты суфлёр.')


class Provider:
    """The reserve's ``post``: a road in ``refuse`` raises, a road in ``empty`` ends with no word, the others answer; ``asked`` is the order they were asked in."""

    def __init__(self, refuse=(), empty=()):
        self.asked, self.refuse, self.empty = [], set(refuse), set(empty)

    def __call__(self, url, headers, body, timeout):
        road = ('GROQ_API_KEY' if headers['Authorization'].endswith('one') else 'GEMINI_API_KEY', body['model'])
        self.asked.append(road)
        if road in self.refuse:
            raise ReserveError('http_503')
        yield from ([] if road in self.empty else sse('Ответ ', road[0][:4]))


def roads(primary=None, provider=None, now=None, keys=KEYS):
    now = now if now is not None else [100.0]
    reserve = ReserveStream(keys, post=provider or Provider(), clock=lambda: now[0])
    return Roads(primary, reserve, clock=lambda: now[0]), now


def text(stream, walk=None, cancelled=None):
    return ''.join(piece for piece in stream(request(), cancelled or threading.Event(), *([walk] if walk else [])) if isinstance(piece, str))


def refusing(error):
    def primary(request, cancelled):
        raise error
        yield
    return primary


def speaking(*pieces):
    def primary(request, cancelled):
        yield from pieces
    return primary


# --- the order: a rest is an order, never a ban ----------------------------------------------------------------------------------

def test_the_roads_stand_the_first_road_then_the_reserve_in_its_own_order_and_the_names_say_so():
    stream, _ = roads(speaking('x'))
    assert stream.names() == [PRIMARY, G120, G20, GEM, ('GROQ_API_KEY', 'qwen/qwen3.8-27b')]
    assert stream.order(request()) == stream.names()
    assert roads(None)[0].names() == [G120, G20, GEM, ('GROQ_API_KEY', 'qwen/qwen3.8-27b')]
    assert Roads.reserve is True and not hasattr(reserve_text, 'WithReserve')


def test_the_roads_that_rest_stand_last_and_the_one_whose_rest_ends_first_stands_first_of_them():
    stream, now = roads(speaking('x'))
    reserve_text._REST[G120], reserve_text._PRIMARY['until'], reserve_text._REST[GEM] = 150.0, 120.0, 130.0
    order = stream.order(request())
    assert order[:2] == [G20, ('GROQ_API_KEY', 'qwen/qwen3.8-27b')] and order[2:] == [PRIMARY, GEM, G120]
    now[0] = 125.0
    assert stream.order(request())[-2:] == [GEM, G120] and stream.order(request())[0] == PRIMARY      # a rest that is over is no rest


def test_when_every_road_rests_the_first_to_rise_is_asked_first_and_nothing_is_banned():
    stream, _ = roads(speaking('x'))
    for road, until in zip(stream.names(), (140.0, 110.0, 190.0, 120.0, 130.0)):
        reserve_text._PRIMARY['until'] = until if road == PRIMARY else reserve_text._PRIMARY['until']
        if road != PRIMARY:
            reserve_text._REST[road] = until
    assert not stream.alive() and stream.order(request())[0] == G120 and len(stream.order(request())) == 5


def test_alive_is_some_road_that_does_not_rest():
    stream, now = roads(speaking('x'))
    for road in stream.names()[1:]:
        reserve_text._REST[road] = 200.0
    assert stream.alive()                      # the first road is not resting
    reserve_text._PRIMARY['until'] = 160.0
    assert not stream.alive() and stream.alive(170.0) and not stream.alive(150.0)
    now[0] = 161.0
    assert stream.alive()
    assert not Roads(None, ReserveStream({}, post=Provider())).alive()


# --- the walker: before its first word a failure is the turn of the next road ------------------------------------------------------

def test_a_first_road_that_fails_before_its_word_hands_the_question_to_the_reserve_at_once_and_rests():
    provider = Provider()
    stream, _ = roads(refusing(CR.FastTextError('http_429')), provider)
    assert text(stream) == 'Ответ GROQ' and provider.asked == [G120]
    assert reserve_text._PRIMARY['until'] == 100.0 + reserve_text.PRIMARY_QUOTA_REST_S
    reserve_text._PRIMARY['until'] = 0.0
    stream, _ = roads(refusing(OSError('connection reset')), Provider())
    assert text(stream) == 'Ответ GROQ' and reserve_text._PRIMARY['until'] == 100.0 + reserve_text.PRIMARY_FAIL_REST_S


def test_a_road_that_ends_with_no_word_is_the_turn_of_the_next_for_the_first_road_and_the_reserve_alike():
    provider = Provider(empty={G120})
    stream, _ = roads(speaking(), provider)
    assert text(stream) == 'Ответ GROQ' and provider.asked == [G120, G20]
    assert reserve_text._PRIMARY['until'] == 100.0 + reserve_text.PRIMARY_FAIL_REST_S and reserve_text._REST[G120] == 100.0 + reserve_text.REST_S
    only = Roads(None, ReserveStream({'GEMINI_API_KEY': 'k'}, post=Provider(empty={GEM}), clock=lambda: 100.0), clock=lambda: 100.0)
    with pytest.raises(ReserveError, match='empty'):
        text(only)


def test_after_its_first_word_a_failure_is_the_jobs_and_nothing_else_is_asked():
    provider = Provider()

    def primary(request, cancelled):
        yield 'Начало '
        raise CR.FastTextError('no_terminal_event')
    stream, _ = roads(primary, provider)
    got = []
    with pytest.raises(CR.FastTextError):
        for piece in stream(request(), threading.Event()):
            got.append(piece)
    assert got == ['Начало '] and provider.asked == []
    assert reserve_text._PRIMARY['until'] == 100.0 + reserve_text.PRIMARY_FAIL_REST_S      # it broke after its word: it rests as one that broke before it (the next call starts with the next road)


def test_a_road_that_said_a_word_and_broke_rests_and_the_next_call_starts_with_the_next_road_while_the_text_of_the_job_is_not_mixed():
    provider = Provider()

    def primary(request, cancelled):
        yield 'Начало '
        raise OSError('connection reset')
    stream, _ = roads(primary, provider)
    got = []
    with pytest.raises(OSError):
        for piece in stream(request(), threading.Event()):
            got.append(piece)
    assert got == ['Начало '] and provider.asked == [] and reserve_text._PRIMARY['until'] == 100.0 + reserve_text.PRIMARY_FAIL_REST_S
    assert stream.order(request())[0] == G120 and stream.order(request())[-1] == PRIMARY
    assert text(stream) == 'Ответ GROQ' and provider.asked == [G120]      # the retry of the controller is answered by the reserve
    # a reserve road that broke after its word rests as well

    def broken(url, headers, body, timeout):
        yield from sse('Раз')[:1]
        raise ReserveError('http_500')
    only = Roads(None, ReserveStream({'GEMINI_API_KEY': 'k'}, post=broken, clock=lambda: 100.0), clock=lambda: 100.0)
    with pytest.raises(ReserveError):
        text(only)
    assert reserve_text._REST[GEM] == 100.0 + reserve_text.REST_S


def test_a_usage_before_any_word_is_nobodys_and_a_usage_after_the_word_goes_on():
    stream, _ = roads(speaking({'usage': {'input_tokens': 1}}, 'Слово.', {'usage': {'input_tokens': 2}}))
    assert list(stream(request(), threading.Event())) == ['Слово.', {'usage': {'input_tokens': 2}}]


def test_a_cancelled_walker_returns_and_records_nothing():
    cancelled = threading.Event()

    def primary(request, cancelled_):
        cancelled.set()
        raise OSError('closed under it')
        yield
    provider = Provider()
    stream, _ = roads(primary, provider)
    assert list(stream(request(), cancelled)) == [] and provider.asked == []
    assert reserve_text._PRIMARY['until'] == 0.0 and not reserve_text._REST


def test_no_road_left_is_the_last_failure_and_a_walk_that_took_every_road_is_no_road():
    stream, _ = roads(refusing(OSError('down')), Provider(refuse={G120, G20, GEM, ('GROQ_API_KEY', 'qwen/qwen3.8-27b')}))
    with pytest.raises(ReserveError, match='http_503'):
        text(stream)
    walk = Walk(request())
    for road in stream.names():
        walk.take(road, object(), 0.0)
    with pytest.raises(ReserveError, match='no_road'):
        text(stream, walk)


def test_two_walkers_of_one_walk_never_take_the_same_road():
    release, asked = threading.Event(), []

    def primary(request, cancelled):
        asked.append('first walker')
        release.wait(5)
        yield 'поздно'
    provider = Provider()
    stream, _ = roads(primary, provider)
    walk, out = Walk(request()), []
    first = threading.Thread(target=lambda: out.append(text(stream, walk)))
    first.start()
    while not asked:
        threading.Event().wait(0.01)
    assert text(stream, walk) == 'Ответ GROQ'      # the first road is taken: the second walker starts at the reserve
    assert provider.asked == [G120] and walk.where(next(iter(walk._at)))[0] == PRIMARY
    release.set()
    first.join(5)
    assert out == ['поздно'] and asked == ['first walker']


def test_a_resting_first_road_is_asked_when_the_reserve_has_failed_for_this_question():
    reserve_text._PRIMARY['until'] = 500.0
    provider = Provider(refuse={G120, G20, GEM, ('GROQ_API_KEY', 'qwen/qwen3.8-27b')})
    stream, _ = roads(speaking('Вернулся.'), provider)
    assert text(stream) == 'Вернулся.' and provider.asked == [G120, G20, GEM, ('GROQ_API_KEY', 'qwen/qwen3.8-27b')]


# --- step: the decision of the loop -----------------------------------------------------------------------------------------------

class Loop:
    """A question of the loop: the walk, its walkers by number, the moment it was asked."""

    def __init__(self, stream, asked=0.0):
        self.stream, self.walk, self.asked, self.tried = stream, Walk(request()), asked, {}

    def start(self, number, road, now, **fields):
        key = object()
        self.walk.take(road, key, now)
        self.tried[number] = dict(key=key, started=now, first_at=None, outcome=None, **fields)
        return key

    def step(self, now, give_up=reserve_text.ALL_DEAD_S):
        tried = [Tried(number, one['key'], one['started'], one['first_at'], one['outcome']) for number, one in self.tried.items()]
        return self.stream.step(now, tried, self.walk, asked=self.asked, give_up=give_up)


def test_a_road_silent_for_the_next_road_s_gets_the_next_asked_too_and_not_before():
    stream, _ = roads(speaking('x'))
    loop = Loop(stream)
    loop.start(1, PRIMARY, 0.0)
    assert loop.step(1.9) == [] and loop.step(2.0) == [('next', None)]


def test_a_walker_that_is_over_with_no_word_and_a_road_left_gets_the_next_at_once():
    stream, _ = roads(speaking('x'))
    loop = Loop(stream)
    loop.start(1, PRIMARY, 0.0)
    loop.tried[1]['outcome'] = 'error'
    assert loop.step(0.1) == [('next', None)]


def test_the_first_text_wins_and_every_other_flying_walker_is_cancelled():
    stream, _ = roads(speaking('x'))
    loop = Loop(stream)
    loop.start(1, PRIMARY, 0.0)
    loop.start(2, G120, 2.0)
    loop.start(3, G20, 2.5)
    loop.tried[2]['first_at'] = loop.tried[3]['first_at'] = 3.0
    assert loop.step(3.1) == [('win', 2), ('cancel', 1), ('cancel', 3)]
    loop.tried[1]['outcome'] = 'cancelled'
    assert loop.step(3.2) == [('win', 2), ('cancel', 3)]


def test_a_whole_answer_beats_a_begun_one_in_the_same_window_and_at_a_tie_the_earlier_first_word_wins():
    stream, _ = roads(speaking('x'))
    loop = Loop(stream)
    loop.start(1, PRIMARY, 0.0)
    loop.start(2, G120, 0.5)
    loop.tried[2]['first_at'] = 2.0      # B began first ...
    loop.tried[1]['first_at'], loop.tried[1]['outcome'] = 2.1, 'ok'      # ... A ended whole in the same window
    assert loop.step(2.2) == [('win', 1), ('cancel', 2)]
    loop.tried[2]['outcome'] = 'ok'      # both whole: the earlier first word
    assert loop.step(2.3) == [('win', 2), ('cancel', 1)]
    loop.tried[1]['first_at'] = 1.9
    assert loop.step(2.4) == [('win', 1), ('cancel', 2)]


def test_a_loser_that_ended_whole_is_let_go_too():
    stream, _ = roads(speaking('x'))
    loop = Loop(stream)
    loop.start(1, PRIMARY, 0.0)
    loop.start(2, G120, 0.5)
    loop.tried[1]['first_at'], loop.tried[1]['outcome'] = 2.1, 'ok'
    loop.tried[2]['first_at'] = 2.0
    assert ('cancel', 2) in loop.step(2.2)
    loop.tried[2]['first_at'], loop.tried[2]['outcome'] = 1.0, 'ok'
    assert loop.step(2.3) == [('win', 2), ('cancel', 1)]


def test_a_reserve_road_silent_for_twice_the_next_road_s_is_a_stall_the_first_road_never_and_the_cascade_goes_with_two_flying_at_most():
    stream, _ = roads(speaking('x'))
    loop = Loop(stream)
    loop.start(1, PRIMARY, 0.0)
    loop.start(2, G120, 2.0)
    assert loop.step(3.9) == [] and loop.step(4.0) == []      # two fly: no third; the first road is silent 4 s and is NOT let go for a reserve road that is silent too
    assert loop.step(5.9) == [] and loop.step(6.0) == [('stall', 2), ('next', None)]      # the silent reserve walker is let go, its place is the next road's
    loop.tried[2]['outcome'] = 'timeout'
    loop.start(3, G20, 6.0)
    assert loop.step(7.9) == []      # the first road and the third walker fly: no stall of the first, no fourth


def test_nothing_answers_for_the_give_up_time_and_the_question_is_dead_with_every_flying_walker_let_go():
    stream, _ = roads(speaking('x'))
    loop = Loop(stream, asked=1.0)
    loop.start(1, PRIMARY, 1.0)
    loop.start(2, G120, 5.0)
    assert loop.step(8.9) == []      # 7.9 s after the question: not yet dead (the first road, silent 7.9 s, is not let go for a reserve road that stands 3.9 s)
    assert loop.step(9.0) == [('stall', 1), ('stall', 2), ('dead', None)]
    assert loop.step(13.0, give_up=12.0) == [('stall', 1), ('stall', 2), ('dead', None)]
    assert ('dead', None) not in loop.step(12.9, give_up=12.0)


def test_nobody_flies_and_no_road_is_left_is_dead_at_once():
    stream, _ = roads(speaking('x'))
    loop = Loop(stream)
    for number, road in enumerate(stream.names(), 1):
        loop.start(number, road, 0.0)
        loop.tried[number]['outcome'] = 'error'
    assert loop.step(0.3) == [('dead', None)]
    loop.tried[5]['outcome'] = None      # one still flies: it is waited for (to the give-up time)
    assert loop.step(0.3) == []


def test_a_silent_last_walker_with_no_road_left_is_let_go_only_at_the_give_up_time_and_dead_in_one_step():
    stream, _ = roads(None)
    loop = Loop(stream)
    for number, road in enumerate(stream.names(), 1):
        loop.start(number, road, 0.0)
        loop.tried[number]['outcome'] = 'error'
    loop.start(9, 'last', 0.0)
    assert loop.step(4.0) == [] and loop.step(7.9) == []      # nobody is left to ask: the last walker lives to the give-up time (it may be a slow road, not a dead one)
    assert loop.step(8.0) == [('stall', 9), ('dead', None)]


def test_one_flying_walker_with_no_road_left_is_no_stall_before_the_give_up_time_and_a_stall_and_dead_at_it():
    stream, _ = roads(None)
    loop = Loop(stream)
    for number, road in enumerate(stream.names(), 1):
        loop.start(number, road, 0.0)
        loop.tried[number]['outcome'] = 'error'
    loop.start(9, 'last', 0.0)
    assert loop.step(4.0) == [] and loop.step(7.9) == []
    assert loop.step(12.0, give_up=12.0) == [('stall', 9), ('dead', None)] and loop.step(8.0) == [('stall', 9), ('dead', None)]


def test_two_flying_walkers_with_no_road_left_both_silent_for_five_seconds_are_left_alone():
    stream, _ = roads(None)
    loop = Loop(stream)
    for number, road in enumerate(stream.names(), 1):
        loop.start(number, road, 0.0)
        loop.tried[number]['outcome'] = 'error'
    loop.start(8, 'last', 0.0)
    loop.start(9, 'lastbutone', 0.0)
    assert loop.step(5.0) == [] and loop.step(7.9) == []
    assert loop.step(8.0) == [('stall', 8), ('stall', 9), ('dead', None)]


def test_a_road_left_keeps_the_rule_of_the_stall_the_silent_reserve_walker_is_let_go_and_the_next_asked_never_the_first_road():
    stream, _ = roads(speaking('x'))
    loop = Loop(stream)
    loop.start(1, PRIMARY, 0.0)
    loop.start(2, G120, 2.0)
    assert loop.step(4.0) == [] and loop.step(6.0) == [('stall', 2), ('next', None)]


def test_a_road_the_order_leaves_out_is_not_asked_for_and_the_question_is_dead_with_no_walker_spawned_in_a_loop():
    stream, _ = roads(speaking('x'))
    stream.order = lambda request: stream.names()[:1]      # the order holds fewer roads than the names (a road the budget leaves out)
    loop = Loop(stream)
    loop.start(1, PRIMARY, 0.0)
    loop.tried[1]['outcome'] = 'error'
    assert loop.step(0.3) == [('dead', None)]      # the walker of the question can not be given a road that the order does not hold


# --- lost: the silent losses of a road ---------------------------------------------------------------------------------------------

def test_one_silent_loss_gives_no_rest_and_two_in_a_row_do_and_the_third_rests_again():
    stream, _ = roads(speaking('x'))
    loop = Loop(stream)
    key = loop.start(1, PRIMARY, 0.0)
    stream.lost(loop.walk, key, 2.0)
    assert reserve_text._PRIMARY['until'] == 0.0 and stream.alive(2.0)
    second = Loop(stream)      # another question: the same first road
    key = second.start(2, PRIMARY, 3.0)
    stream.lost(second.walk, key, 5.0)
    assert reserve_text._PRIMARY['until'] == 5.0 + reserve_text.PRIMARY_FAIL_REST_S
    reserve_text._PRIMARY['until'] = 0.0
    third = Loop(stream)
    key = third.start(3, PRIMARY, 6.0)
    stream.lost(third.walk, key, 8.0)
    assert reserve_text._PRIMARY['until'] == 8.0 + reserve_text.PRIMARY_FAIL_REST_S      # one trial: another stall rests it again


def test_a_word_of_the_road_between_two_losses_resets_the_count():
    stream, _ = roads(speaking('x'))
    first = Loop(stream)
    stream.lost(first.walk, first.start(1, PRIMARY, 0.0), 2.0)
    stream.spoke(PRIMARY)
    second = Loop(stream)
    stream.lost(second.walk, second.start(2, PRIMARY, 3.0), 5.0)
    assert reserve_text._PRIMARY['until'] == 0.0


def test_a_loss_of_less_than_the_next_road_s_is_no_stall_and_a_reserve_road_rests_for_the_reserve_rest():
    stream, _ = roads(speaking('x'))
    short = Loop(stream)
    for number in (1, 2, 3):
        stream.lost(short.walk, short.start(number, PRIMARY, 0.0), 1.9)
    assert reserve_text._PRIMARY['until'] == 0.0
    for number in (4, 5):
        one = Loop(stream)
        stream.lost(one.walk, one.start(number, G120, 10.0), 12.0)
    assert reserve_text._REST[G120] == 12.0 + reserve_text.REST_S and G20 not in reserve_text._REST
    nowhere = Walk(request())
    stream.lost(nowhere, object(), 99.0)      # a walker that stood on no road: nothing to lose


def test_the_counts_are_the_calls_own_and_the_constants_are_the_stated_ones():
    one, _ = roads(speaking('x'))
    other, _ = roads(speaking('x'))
    loop = Loop(one)
    one.lost(loop.walk, loop.start(1, PRIMARY, 0.0), 2.0)
    again = Loop(other)
    other.lost(again.walk, again.start(1, PRIMARY, 0.0), 2.0)
    assert reserve_text._PRIMARY['until'] == 0.0      # one loss each: no call infects another
    assert (reserve_text.NEXT_ROAD_S, reserve_text.ALL_DEAD_S, reserve_text.STALLS) == (2.0, 8.0, 2)


def test_a_walker_that_spoke_and_broke_is_the_failure_of_the_job_and_no_other_road_is_asked():
    stream, _ = roads(speaking('x'))
    loop = Loop(stream)
    loop.start(1, PRIMARY, 0.0)
    loop.tried[1].update(first_at=0.5, outcome='error')
    assert loop.step(0.6) == []      # (the give-up time is checked before any branch that says nothing: see the tests of the dead question below)
    assert loop.step(9.0) == [('dead', None)]


def silent_job_and_broken_twin(left):
    """What the channel shows the owner when the released job ended with no word and its twin spoke and broke: a word nobody heard is no word (the twin is shown as a walker that was refused with none)."""
    stream, _ = roads(None)
    loop = Loop(stream)
    for number, road in enumerate(stream.names()[:-1] if left else stream.names(), 1):
        loop.start(number, road, 0.0)
        loop.tried[number]['outcome'] = 'error'
    return loop


def test_a_job_over_with_no_word_and_a_twin_that_broke_after_a_word_nobody_heard_is_dead_when_no_road_is_left():
    loop = silent_job_and_broken_twin(left=False)
    assert loop.step(6.0) == [('dead', None)]


def test_the_same_with_a_road_left_asks_the_next_road():
    loop = silent_job_and_broken_twin(left=True)
    assert loop.step(6.0) == [('next', None)]


def test_the_give_up_time_is_checked_before_any_branch_that_says_nothing_nobody_flies_after_it_is_dead():
    stream, _ = roads(speaking('x'))
    loop = Loop(stream)
    loop.start(1, PRIMARY, 0.0)
    loop.tried[1].update(first_at=0.5, outcome='error')      # spoke and broke: the failure is the job's, no road is asked; but not for ever
    assert loop.step(7.9) == [] and loop.step(8.0) == [('dead', None)]


# --- a word is a delta with a character that is not a space ------------------------------------------------------------------------

def test_a_road_whose_answer_is_only_white_space_is_empty_and_the_next_road_answers():
    def blanks(request, cancelled):
        yield ' '
        yield '\n'
    provider = Provider()
    stream, _ = roads(blanks, provider)
    assert text(stream) == 'Ответ GROQ' and provider.asked == [G120]      # nothing of the blanks was said
    assert reserve_text._PRIMARY['until'] == 100.0 + reserve_text.PRIMARY_FAIL_REST_S


def test_a_blank_before_the_first_real_word_goes_with_it_and_the_next_road_is_not_asked():
    def spaced(request, cancelled):
        yield ' '
        yield 'Ответ.'
    provider = Provider()
    stream, _ = roads(spaced, provider)
    assert text(stream) == ' Ответ.' and provider.asked == []


def test_only_white_space_from_the_only_road_is_the_error_empty():
    only = Roads(None, ReserveStream({'GEMINI_API_KEY': 'k'}, post=lambda *a: iter(sse(' ', '\n')), clock=lambda: 100.0), clock=lambda: 100.0)
    with pytest.raises(ReserveError, match='empty'):
        text(only)


# --- silence is the host, a refusal is the key --------------------------------------------------------------------------------------

K3 = {'GROQ_API_KEY': 'one', 'GROQ_API_KEY_2': 'two', 'GEMINI_API_KEY': 'k'}
GK1, GK2, GG20, GG20B = G120, ('GROQ_API_KEY_2', 'openai/gpt-oss-120b'), G20, ('GROQ_API_KEY_2', 'openai/gpt-oss-20b')


class Keyed(Provider):
    """``Provider`` with a second Groq key: the road is told by its key and model."""

    def __call__(self, url, headers, body, timeout):
        token = headers['Authorization'].split()[-1]
        road = ({'one': 'GROQ_API_KEY', 'two': 'GROQ_API_KEY_2'}.get(token, 'GEMINI_API_KEY'), body['model'])
        self.asked.append(road)
        if road in self.refuse:
            raise ReserveError('http_429')
        yield from sse('Ответ ', road[0][:4])


def spawn(loop, number, now, clock, provider):
    """The next walker of the question as the loop starts it: runs it to its end and notes which road it asked first (the first it took)."""
    clock[0], key, before = now, threading.Event(), len(provider.asked)
    text(loop.stream, loop.walk, key)
    loop.tried[number] = dict(key=key, started=now, first_at=None, outcome=None)
    return provider.asked[before]


def test_a_road_silent_for_the_next_road_s_marks_its_host_so_the_next_walker_takes_a_road_of_another_host_first():
    provider = Keyed()
    stream, clock = roads(speaking('x'), provider, keys=K3)
    loop = Loop(stream, asked=100.0)
    loop.start(1, PRIMARY, 100.0)
    assert loop.step(102.0) == [('next', None)]
    assert spawn(loop, 2, 102.0, clock, provider) == GK1      # the first road is silent: its host is codex, the next is the first of the reserve
    assert loop.step(104.0) == [] and loop.step(106.0) == [('stall', 2), ('next', None)]      # the silent reserve walker is let go (the first road is not)
    loop.tried[2]['outcome'] = 'timeout'
    assert spawn(loop, 3, 106.0, clock, provider) == GEM      # Groq is silent (not a key): Gemini before the second Groq key


def test_a_refusal_of_the_last_stranger_sends_the_walker_on_to_the_muted_host_when_no_other_host_is_left():
    provider = Keyed(refuse={GEM})
    stream, clock = roads(speaking('x'), provider, keys=K3)
    loop = Loop(stream, asked=100.0)
    loop.start(1, PRIMARY, 100.0)
    loop.step(102.0)
    spawn(loop, 2, 102.0, clock, provider)
    loop.step(106.0)
    clock[0] = 106.0
    assert text(stream, loop.walk) == 'Ответ GROQ' and provider.asked[-2:] == [GEM, GK2]      # Gemini refused at once: no stranger is left, the muted host's next key is asked


def test_a_quick_refusal_marks_no_host_the_neighbour_in_the_list_is_next():
    provider = Keyed(refuse={GK1})
    stream, clock = roads(refusing(CR.FastTextError('http_429')), provider, keys=K3)
    assert text(stream) == 'Ответ GROQ' and provider.asked == [GK1, GK2]      # codex 429, groq key 1 429: key 2, not Gemini


def test_the_mark_lives_in_the_question_only_a_new_question_asks_the_roads_in_their_order():
    provider = Keyed()
    stream, clock = roads(speaking('x'), provider, keys=K3)
    first = Loop(stream, asked=100.0)
    first.start(1, PRIMARY, 100.0)
    first.step(102.0)
    assert first.walk.muted == {'codex'}
    again = Loop(stream, asked=100.0)
    clock[0] = 110.0
    assert text(stream, again.walk) == 'x' and again.walk.taken == {PRIMARY} and again.walk.muted == set()      # the first road is the first again
