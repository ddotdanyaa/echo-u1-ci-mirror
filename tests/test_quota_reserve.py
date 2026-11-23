"""U50, the free quota of the reserve (8 000 tokens a minute and 1 000 requests a day for a key and a model), guarded without cutting the quality of an answer.
Through ``FastText`` over the real ``Roads`` and ``ReserveStream`` with a fake provider (its own headers, its own words) and a clock the test drives.
1. a remark with no form of a question is asked in the short form (no material) and the full request goes only when the answer says it is a question;
3. a road is never sent what its known minute cannot hold while another road can; a day's limit that is spent rests the road until the provider's reset; a reserve road is not started
   in the race against a first road that is healthy and only slow when the minute of the reserve is nearly spent (never when the first road rests or fails, and never for ever)."""
import json
import threading
import time

import pytest

from echo_sync import fast_text as FT
from echo_sync import reserve_text
from echo_sync.reserve_text import NEXT_ROAD_S, PRIMARY, ReserveError, ReserveStream, Roads

import test_reserve_brief as BRIEF
from test_roads_channel import Clock, T0, until

MODEL, SMALL = 'openai/gpt-oss-120b', 'openai/gpt-oss-20b'
KEYS = {'GROQ_API_KEY': 'one', 'GROQ_API_KEY_2': 'two'}
MATERIAL = '⟦МАТЕРИАЛЫ'


@pytest.fixture(autouse=True)
def _fresh():
    for table in (reserve_text._REST, reserve_text._BUDGET):
        table.clear()
    reserve_text._PRIMARY['until'] = 0.0
    yield
    for table in (reserve_text._REST, reserve_text._BUDGET):
        table.clear()
    reserve_text._PRIMARY['until'] = 0.0


def told(left, back='30s', limit=8000, day_left=990, day_limit=1000, day_back='9m'):
    return {'x-ratelimit-limit-tokens': str(limit), 'x-ratelimit-remaining-tokens': str(left), 'x-ratelimit-reset-tokens': back,
            'x-ratelimit-limit-requests': str(day_limit), 'x-ratelimit-remaining-requests': str(day_left), 'x-ratelimit-reset-requests': day_back}


class Provider:
    """A reserve host: ``say(body)`` is what a road writes to the request it gets; ``asked`` keeps ``(road, whether the request holds the material, its size in characters)``."""

    def __init__(self, say=None, left=None, refuse=None, day_left=None):
        self.say, self.asked, self.left, self.refuse, self.day_left = say or (lambda body: 'Ответ.'), [], dict(left or {}), dict(refuse or {}), dict(day_left or {})

    def __call__(self, url, headers, body, timeout):
        road = (headers['Authorization'].split()[-1], body['model'])
        system = body['messages'][0]['content']
        self.asked.append((road, MATERIAL in system, sum(len(m['content']) for m in body['messages'])))
        if road in self.refuse:
            raise self.refuse[road]
        yield told(self.left.get(road, 8000), day_left=self.day_left.get(road, 990))
        yield f'data: {json.dumps({"choices": [{"delta": {"content": self.say(body)}}]})}'
        yield 'data: [DONE]'

    @property
    def sizes(self):
        return [size for _, _, size in self.asked]


def channel(provider, *, instructions=None, primary=None):
    clock = Clock()
    stream = ReserveStream(KEYS, post=provider, clock=clock)
    roads = Roads(primary, stream, clock=clock)
    text = instructions if instructions is not None else BRIEF.instructions()
    return FT.FastText(roads, instructions=lambda *a: text, history=lambda: [], clock=clock, wake=lambda: None), clock


def ask(fast, text):
    assert fast.release(qid='q1', turn='tq1', epoch=1, question=text) == 'started'
    events = []
    until(lambda: events.extend(fast.poll()) or any(e['kind'] in ('done', 'failed') for e in events))
    return events


def heard(events):
    return ''.join(e['text'] for e in events if e['kind'] == 'text')


# --- 1. a remark is not a full request -------------------------------------------------------------------------------------------------

def test_a_remark_with_no_form_of_a_question_is_asked_in_the_short_form_and_the_dash_ends_it():
    provider = Provider(say=lambda body: '—' if MATERIAL not in body['messages'][0]['content'] else 'Ответ по материалу.')
    fast, _ = channel(provider)
    events = ask(fast, 'Ну давай быстрее уже')
    assert [e['kind'] for e in events][-1] == 'done' and FT.brain_answer(heard(events)) == ''      # «—»: no question, nothing is said
    assert [material for _, material, _ in provider.asked] == [False] and len(provider.asked) == 1      # one request, with no material
    request = FT.build_request('Ну давай быстрее уже', instructions=BRIEF.instructions())
    screen, full = reserve_text._weight(reserve_text.chat_body(request, MODEL, screen=True)), reserve_text._weight(reserve_text.chat_body(request, MODEL))
    assert screen < 0.55 * full, (screen, full)      # what the minute of the road is charged: the prompt and the whole allowance of the answer


def test_a_question_with_no_form_gets_the_full_request_after_the_short_one_says_it_is_one():
    def say(body):
        return 'Ответ по материалу.' if MATERIAL in body['messages'][0]['content'] else '25'
    provider = Provider(say=say)
    fast, _ = channel(provider)
    events = ask(fast, 'пять на пять')
    assert heard(events) == 'Ответ по материалу.' and [e['kind'] for e in events][-1] == 'done'      # what the short request said (no material) is never heard
    assert [material for _, material, _ in provider.asked] == [False, True] and provider.asked[0][0] == provider.asked[1][0]


def test_a_question_with_its_form_goes_at_once_in_the_full_request_and_a_mark_of_the_listener_is_taken_as_it_came():
    provider = Provider()
    fast, _ = channel(provider)
    assert heard(ask(fast, 'Когда была Полтавская битва?')) == 'Ответ.' and [material for _, material, _ in provider.asked] == [True]
    marks = Provider(say=lambda body: '[стоп]')
    fast, _ = channel(marks)
    assert 'стоп' in heard(ask(fast, 'остановись пожалуйста')) and len(marks.asked) == 1      # a command needs no material: the short request's answer is the answer


def test_with_no_material_in_the_instructions_nothing_is_asked_twice():
    provider = Provider(say=lambda body: '25')
    fast, _ = channel(provider, instructions=FT.BRAIN_POLICY)
    assert heard(ask(fast, 'пять на пять')) == '25' and len(provider.asked) == 1


def test_a_doubt_of_the_answer_in_play_and_a_job_with_a_material_are_never_screened():
    provider = Provider()
    fast, _ = channel(provider)
    assert fast.release(qid='q1', turn='t1', epoch=1, question='ты уверена', material='⟦ИСТОЧНИКИ⟧ текст') == 'started'
    until(lambda: provider.asked)
    assert provider.asked[0][1] is True and len(provider.asked) == 1


# --- 3. the minute and the day of a road -----------------------------------------------------------------------------------------------

def big():
    return FT.build_request('Когда была Полтавская битва?', instructions=BRIEF.instructions())


def test_through_the_roads_a_request_the_known_minute_cannot_hold_goes_to_a_road_that_can():
    provider, now = Provider(left={('one', MODEL): 900}), [100.0]
    roads = Roads(None, ReserveStream(KEYS, post=provider, clock=lambda: now[0]), clock=lambda: now[0])
    assert ''.join(roads(big(), threading.Event())) == 'Ответ.'      # nothing known: the first road, it tells 900 are left
    now[0] += 1.0
    assert ''.join(roads(big(), threading.Event())) == 'Ответ.'
    assert [road for road, _, _ in provider.asked] == [('one', MODEL), ('two', MODEL)]      # the second question: not the road that cannot hold it
    assert reserve_text.Roads.order(roads, big())[0] == ('GROQ_API_KEY_2', MODEL)


def test_a_day_that_is_spent_rests_the_road_until_the_reset_of_the_provider_not_for_ten_minutes():
    provider, now = Provider(day_left={('one', MODEL): 0}), [100.0]
    roads = Roads(None, ReserveStream(KEYS, post=provider, clock=lambda: now[0]), clock=lambda: now[0])
    assert ''.join(roads(big(), threading.Event())) == 'Ответ.'
    road = ('GROQ_API_KEY', MODEL)
    assert reserve_text._REST[road] == 100.0 + 540.0      # 'x-ratelimit-reset-requests: 9m'
    provider.say = lambda body: 'Ответ.'
    now[0] += 200.0
    roads(big(), threading.Event()).__next__()
    assert provider.asked[-1][0] != ('one', MODEL) and roads.resting(road, now[0])
    now[0] += 400.0
    assert not roads.resting(road, now[0])


def test_a_refusal_of_the_day_rests_the_road_as_long_as_it_says_even_hours():
    refused = ReserveError('http_429')
    refused.headers = {'retry-after': '5400'}
    refused.said = {'kind': 'RPD', 'limit': 1000, 'used': 1000, 'asked': 1, 'again': 5400.0}
    provider = Provider(refuse={('one', MODEL): refused})
    roads = Roads(None, ReserveStream(KEYS, post=provider, clock=lambda: 100.0), clock=lambda: 100.0)
    assert ''.join(roads(big(), threading.Event())) == 'Ответ.'
    assert reserve_text._REST[('GROQ_API_KEY', MODEL)] == 100.0 + 5400.0      # a minute's limit is capped (``test_reserve_roads``); a day's is not
    assert reserve_text._REST[('GROQ_API_KEY', MODEL)] > 100.0 + reserve_text.PRIMARY_QUOTA_REST_S


def test_a_day_that_is_spent_is_still_asked_when_no_other_road_is_left():
    provider = Provider(day_left={('one', MODEL): 0, ('two', MODEL): 0})
    stream = ReserveStream({'GROQ_API_KEY': 'one'}, post=provider, clock=lambda: 100.0)
    roads = Roads(None, stream, clock=lambda: 100.0)
    for _ in range(2):
        assert ''.join(roads(big(), threading.Event())) == 'Ответ.'      # a rest is an order, never a ban: the question is never left without a road
    assert len(provider.asked) >= 2


# --- the race against a first road that is healthy and only slow ----------------------------------------------------------------------

class Scene:
    """A first road that says its words at ``slow`` seconds of the clock (it hangs till then) and the reserve that is asked on the way."""

    def __init__(self, clock, slow):
        self.clock, self.slow, self.cancelled, self.asked = clock, slow, [], 0

    def primary(self, request, cancelled):
        self.asked += 1
        self.cancelled.append(cancelled)
        while self.clock.t < self.slow and not cancelled.is_set():
            time.sleep(0.003)
        if not cancelled.is_set():
            yield 'Ответ Codex.'


def race(slow, *, spent):
    provider = Provider()
    clock = Clock()
    stream = ReserveStream(KEYS, post=provider, clock=clock)
    scene = Scene(clock, T0 + slow)
    roads = Roads(scene.primary, stream, clock=clock)
    fast = FT.FastText(roads, instructions=lambda *a: BRIEF.instructions(), history=lambda: [], clock=clock, wake=lambda: None)
    if spent:
        for name, _, model in stream.roads:
            reserve_text._note((name, model), T0, told(300))
    assert fast.release(qid='q1', turn='tq1', epoch=1, question='Когда была Полтавская битва?') == 'started'
    return fast, clock, provider, scene


def run(fast, clock, until_t, step=0.25):
    events = []
    while clock.t < until_t:
        clock.t = round(clock.t + step, 6)
        events += fast.poll()
        time.sleep(0.01)
    return events


def test_a_slow_first_road_is_not_raced_by_a_reserve_whose_minute_is_nearly_spent():
    fast, clock, provider, scene = race(3.0, spent=True)
    events = run(fast, clock, T0 + 3.5)
    assert heard(events) == 'Ответ Codex.' and provider.asked == [] and scene.asked == 1      # the first road answered at 3 s, not a token of the reserve was spent


def test_the_same_slow_first_road_is_raced_as_ever_when_the_reserve_has_the_room():
    fast, clock, provider, scene = race(3.0, spent=False)
    run(fast, clock, T0 + NEXT_ROAD_S + 0.6)
    assert until(lambda: provider.asked)      # the second road is asked at NEXT_ROAD_S


def test_a_first_road_that_is_silent_is_never_waited_for_for_ever_the_reserve_is_asked_at_the_hold():
    fast, clock, provider, scene = race(60.0, spent=True)
    run(fast, clock, T0 + NEXT_ROAD_S + 1.5)
    assert provider.asked == []      # held
    events = run(fast, clock, T0 + reserve_text.SPENT_RACE_HOLD_S + 1.0)
    assert until(lambda: provider.asked) and reserve_text.SPENT_RACE_HOLD_S < reserve_text.REFUSE_AFTER_S


def test_when_the_first_road_rests_the_reserve_is_asked_at_once_whatever_its_minute():
    reserve_text._PRIMARY['until'] = T0 + 30.0
    fast, clock, provider, scene = race(60.0, spent=True)
    assert until(lambda: provider.asked)      # the first road is last in the order: the question walks the reserve at its start, no race
    assert heard(run(fast, clock, T0 + 1.0)) == 'Ответ.'
