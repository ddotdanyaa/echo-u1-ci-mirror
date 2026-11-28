"""always-answer, step 2: ``fast_text.FastText`` over the real ``reserve_text.Roads`` with scripted roads and a clock the test drives. A refusal or a hang of the first road (Codex) is not heard:
the next road is asked by itself, the honest sentence is said only when every road is dead, and a dead question never puts the channel out."""
import threading
import time

import pytest

from echo_sync import fast_text as FT
from echo_sync import codex_road as CR
from echo_sync import reserve_text
from echo_sync.reserve_text import ALL_DEAD_S, NEXT_ROAD_S, PRIMARY, ReserveError, ReserveStream, Roads

G120, G20, GEM, QWEN = ('GROQ_API_KEY', 'openai/gpt-oss-120b'), ('GROQ_API_KEY', 'openai/gpt-oss-20b'), ('GEMINI_API_KEY', 'gemini-3.5-flash-lite'), ('GROQ_API_KEY', 'qwen/qwen3.8-27b')
KEYS = {'GROQ_API_KEY': 'one', 'GEMINI_API_KEY': 'k'}
ANSWER = 'Инерция — это свойство тел.'
T0 = 1000.0


@pytest.fixture(autouse=True)
def _fresh():
    reserve_text._REST.clear()
    reserve_text._PRIMARY['until'] = 0.0
    yield
    reserve_text._REST.clear()
    reserve_text._PRIMARY['until'] = 0.0


def until(condition, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if condition():
            return True
        time.sleep(0.002)
    return False


class Clock:
    def __init__(self):
        self.t = T0

    def __call__(self):
        return self.t


# What a road does when it is asked: ``say`` gives the text, ``fail`` raises, ``empty`` ends with no word, ``hang`` says nothing until the scene is over (or, for the first road, the job is cancelled).
def say(text=ANSWER):
    return lambda scene, cancelled: iter([text])


def fail(error):
    def behave(scene, cancelled):
        raise error
        yield
    return behave


def empty(scene, cancelled):
    return iter(())


def hang(scene, cancelled):
    while not scene.over.is_set() and not (cancelled is not None and cancelled.is_set()):
        time.sleep(0.003)
    return iter(())


class Scene:
    """The roads of a test: ``plan(road, *behaviors)`` is what each next ask of the road does (a road with no plan left hangs); ``asked`` is the order the roads were asked in."""

    def __init__(self):
        self.asked, self.plans, self.over, self.cancelled = [], {}, threading.Event(), []

    def plan(self, road, *behaviors):
        self.plans.setdefault(road, []).extend(behaviors)

    def _behave(self, road, cancelled):
        self.asked.append(road)
        plans = self.plans.get(road)
        return (plans.pop(0) if plans else hang)(self, cancelled)

    def primary(self, request, cancelled):
        self.cancelled.append(cancelled)
        yield from self._behave(PRIMARY, cancelled)

    def count(self, road):
        return self.asked.count(road)


def sse_of(scene):
    """The reserve's ``post``: what a road says goes as the lines of a chat stream."""
    import json

    def post(url, headers, body, timeout):
        road = ('GEMINI_API_KEY' if headers['Authorization'].endswith('k') else 'GROQ_API_KEY', body['model'])
        for piece in scene._behave(road, None):
            yield f'data: {json.dumps({"choices": [{"delta": {"content": piece}}]})}'
        yield 'data: [DONE]'
    return post


def channel(scene, *, cloud=True, primary=True):      # cloud: the cloud has its own answer to the question (the roads give up at ALL_DEAD_S and say no sentence); False: it has none (GIVE_UP_S and the honest sentence)
    clock = Clock()
    roads = Roads(scene.primary if primary else None, ReserveStream(KEYS, post=sse_of(scene), clock=clock), clock=clock)
    fast = FT.FastText(roads, instructions=lambda: 'POLICY', history=lambda: [], clock=clock, wake=lambda: None)
    if cloud:
        fast.cloud_answer = lambda: True
    return fast, clock


@pytest.fixture
def scene():
    scene = Scene()
    yield scene
    scene.over.set()


def open_question(fast, qid='q1', text='Что такое инерция?'):
    return fast.release(qid=qid, turn='t' + qid, epoch=1, question=text)


def texts(events):
    return ''.join(e['text'] for e in events if e['kind'] == 'text')


def kinds(events):
    return [e['kind'] for e in events]


def flying(fast):
    return [j for j in (fast.job, fast.twin) if j is not None and j.outcome is None]


def over(fast):
    return until(lambda: fast.job is None or fast.job.outcome is not None)


def drain(fast, kind='done'):
    """Polls until an event of ``kind`` comes; all the events that came."""
    events = []
    until(lambda: events.extend(fast.poll()) or kind in kinds(events))
    return events


# --- a road that hangs or refuses is not heard ----------------------------------------------------------------------------------------

def test_a_first_road_that_hangs_gets_the_next_road_asked_at_two_seconds_and_its_text_comes_as_the_answer(scene):
    scene.plan(G120, say())
    fast, clock = channel(scene)
    assert open_question(fast) == 'started' and until(lambda: scene.asked == [PRIMARY])
    clock.t = T0 + NEXT_ROAD_S - 0.1
    assert fast.poll() == [] and scene.asked == [PRIMARY]      # not before
    clock.t = T0 + NEXT_ROAD_S
    assert fast.poll() == []
    assert until(lambda: fast.twin is not None and fast.twin.first_at is not None) and scene.asked == [PRIMARY, G120]
    events = fast.poll()
    assert texts(events) == ANSWER and scene.cancelled[0].is_set() and not fast.off      # the first road is let go
    assert 'done' in kinds(events + ([] if 'done' in kinds(events) else drain(fast)))


def test_a_first_road_that_refuses_at_once_is_answered_by_the_next_with_one_job_and_a_rest(scene):
    scene.plan(PRIMARY, fail(CR.FastTextError('http_503')))
    scene.plan(G120, say())
    fast, clock = channel(scene)
    open_question(fast)
    assert until(lambda: fast.job.first_at is not None)
    assert texts(fast.poll()) == ANSWER and fast.count == 1 and scene.asked == [PRIMARY, G120]
    assert reserve_text._PRIMARY['until'] == T0 + reserve_text.PRIMARY_FAIL_REST_S


def test_an_answer_with_no_word_is_the_turn_of_the_next_road(scene):
    scene.plan(PRIMARY, empty)
    scene.plan(G120, say())
    fast, clock = channel(scene)
    open_question(fast)
    assert until(lambda: fast.job.first_at is not None)
    assert texts(fast.poll()) == ANSWER and scene.asked == [PRIMARY, G120] and not fast.off


def test_a_first_road_that_breaks_after_its_word_is_the_failure_of_the_job_and_no_other_road_is_asked(scene):
    def broken(scene, cancelled):
        yield 'Инерция — это '
        raise CR.FastTextError('no_terminal_event')
    scene.plan(PRIMARY, broken)
    scene.plan(G120, say())
    fast, clock = channel(scene)
    open_question(fast)
    assert over(fast)
    events = fast.poll()
    assert kinds(events)[-1] == 'failed' and scene.asked == [PRIMARY]


# --- every road hangs ------------------------------------------------------------------------------------------------------------------

def test_every_road_hanging_the_silent_reserve_is_a_stall_at_four_seconds_of_its_own_two_flying_at_most_the_first_road_lives_and_the_question_is_let_go_at_eight(scene):
    fast, clock = channel(scene)
    open_question(fast)
    assert until(lambda: scene.asked == [PRIMARY])
    for tick in range(0, 80):
        clock.t = T0 + tick / 10
        assert not fast.poll() and len(flying(fast)) <= 2, tick
        time.sleep(0.004)
    assert until(lambda: len(scene.asked) == 3) and scene.asked == [PRIMARY, G120, GEM]      # at 0, 2, 6 s (the reserve road of 2 s is let go at 6 s, Groq is silent: its host is skipped, Gemini before the second Groq model)
    assert not scene.cancelled[0].is_set()      # the first road is not let go for a reserve road that is silent too: it lives to the time to give up
    clock.t = T0 + ALL_DEAD_S
    events = fast.poll()
    assert kinds(events) == ['failed'] and not flying(fast) and not fast.off
    assert open_question(fast) == 'off'      # the retry of the controller does not walk the roads again; the question goes to the cloud


def test_with_the_guard_the_honest_sentence_comes_at_eight_seconds_and_the_end_at_twelve_as_done(scene):
    fast, clock = channel(scene, cloud=False)
    open_question(fast)
    for second in (2, 4, 6):
        clock.t = T0 + second
        fast.poll()
        until(lambda: len(scene.asked) >= (2 if second < 6 else 3))
    clock.t = T0 + reserve_text.REFUSE_AFTER_S
    events = fast.poll()
    assert [(e['kind'], e['text']) for e in events] == [('text', reserve_text.REFUSAL)] and events[0]['provisional']
    clock.t = T0 + 10
    assert fast.poll() == []
    clock.t = T0 + reserve_text.GIVE_UP_S
    assert kinds(fast.poll()) == ['done'] and not fast.off and fast._spent == 'q1'
    assert open_question(fast) == 'off'


def test_the_text_of_a_late_road_replaces_the_provisional_refusal(scene):
    scene.plan(G120, hang, hang)
    fast, clock = channel(scene, cloud=False)
    open_question(fast)
    for second in (2, 4, 6):
        clock.t = T0 + second
        fast.poll()
        until(lambda: len(scene.asked) >= (2 if second < 6 else 3))
    scene.plan(G20, say())      # Groq and Gemini are silent: the next road is the first left of the order
    clock.t = T0 + 8.0
    assert kinds(fast.poll()) == ['text']      # the refusal
    clock.t = T0 + 10.0      # the Gemini walker of 6 s is let go, the place is the next road's
    fast.poll()
    assert until(lambda: fast.twin is not None and fast.twin.first_at is not None)
    events = fast.poll()
    assert texts(events) == ANSWER and events[0].get('replaces') is True


# --- every road refuses ---------------------------------------------------------------------------------------------------------------

def refusing_all(scene):
    scene.plan(PRIMARY, fail(CR.FastTextError('http_503')))
    for road in (G120, G20, GEM, QWEN):
        scene.plan(road, fail(ReserveError('http_503')))


def test_every_road_refusing_at_once_is_failed_at_once_and_the_retry_of_the_same_question_is_off_but_another_question_works(scene):
    refusing_all(scene)
    fast, clock = channel(scene)
    assert open_question(fast) == 'started'
    assert over(fast)
    assert kinds(fast.poll()) == ['failed'] and scene.asked == [PRIMARY, G120, G20, GEM, QWEN]
    assert open_question(fast) == 'off' and open_question(fast) == 'off'
    scene.plan(PRIMARY, say())
    assert open_question(fast, 'q2', 'Что такое масса?') == 'started'      # the roads rest, but a rest is an order: the first to rise is asked
    assert until(lambda: fast.job.first_at is not None) and texts(fast.poll()) == ANSWER


def test_three_dead_questions_in_a_row_do_not_put_the_channel_out_and_the_fourth_is_answered_when_a_road_lives_again(scene):
    fast, clock = channel(scene)
    for number in range(3):
        refusing_all(scene)
        assert open_question(fast, f'q{number}', f'Что такое инерция {number}?') == 'started'
        assert over(fast)
        assert kinds(fast.poll()) == ['failed']
        clock.t += 1.0
    assert not fast.off
    scene.plan(PRIMARY, say())      # the first to rise is asked first
    assert open_question(fast, 'q3', 'Что такое масса?') == 'started' and until(lambda: fast.job.first_at is not None)
    assert texts(fast.poll()) == ANSWER and not fast.off


def test_a_quota_refusal_of_the_first_road_pauses_nothing_of_the_channel(scene):
    scene.plan(PRIMARY, fail(CR.FastTextError('http_429')))
    scene.plan(G120, say(), say())
    fast, clock = channel(scene, cloud=False)
    open_question(fast)
    assert until(lambda: fast.job.first_at is not None) and texts(fast.poll()) == ANSWER
    over(fast)
    fast.poll()
    assert not fast.off and not fast.closed
    assert open_question(fast, 'q2', 'Что такое масса?') == 'started'      # no pause of the quota on the channel: the first road rests by itself
    assert reserve_text._PRIMARY['until'] == T0 + reserve_text.PRIMARY_QUOTA_REST_S and scene.asked[:2] == [PRIMARY, G120]


# --- the job prepared before the question ----------------------------------------------------------------------------------------------

def test_a_prepared_job_races_from_the_moment_of_the_release_and_a_road_silent_since_its_start_is_let_go_at_once(scene):
    scene.plan(G120, say())
    fast, clock = channel(scene)
    assert fast.prepare('Что такое инерция?')
    assert until(lambda: scene.asked == [PRIMARY])
    clock.t = T0 + 3.0
    assert open_question(fast) == 'adopted' and fast.job.asked == T0 + 3.0
    assert fast.poll() == []      # the first road has been silent 3 s: the next is asked now
    assert until(lambda: fast.twin is not None and fast.twin.first_at is not None) and texts(fast.poll()) == ANSWER


def test_the_time_to_give_up_of_an_adopted_job_counts_from_its_release(scene):
    fast, clock = channel(scene)
    assert fast.prepare('Что такое инерция?')
    assert until(lambda: scene.asked == [PRIMARY])
    clock.t = T0 + 5.0
    assert open_question(fast) == 'adopted'
    clock.t = T0 + 5.0 + ALL_DEAD_S - 0.1
    assert 'failed' not in kinds(fast.poll())
    clock.t = T0 + 5.0 + ALL_DEAD_S
    assert kinds(fast.poll()) == ['failed']


# --- two silent losses rest the first road, one does not ------------------------------------------------------------------------------

def silent_loss(fast, scene, clock, qid, start):
    """A question the first road leaves silent and the next road answers at two seconds."""
    clock.t = start
    asks = scene.count(PRIMARY)
    assert open_question(fast, qid, f'Что такое {qid}?') == 'started' and until(lambda: scene.count(PRIMARY) == asks + 1)
    clock.t = start + NEXT_ROAD_S
    fast.poll()
    assert until(lambda: fast.twin is not None and fast.twin.first_at is not None)
    events = fast.poll()
    assert texts(events) == ANSWER and 'done' in kinds(events + ([] if 'done' in kinds(events) else drain(fast)))


def test_two_silent_losses_in_a_row_rest_the_first_road_and_one_does_not(scene):
    scene.plan(G120, say(), say(), say())
    fast, clock = channel(scene)
    silent_loss(fast, scene, clock, 'q1', T0)
    assert reserve_text._PRIMARY['until'] == 0.0      # one is no verdict
    silent_loss(fast, scene, clock, 'q2', T0 + 10)
    assert reserve_text._PRIMARY['until'] == T0 + 10 + NEXT_ROAD_S + reserve_text.PRIMARY_FAIL_REST_S
    clock.t = T0 + 20
    open_question(fast, 'q3', 'Что такое масса?')
    assert until(lambda: fast.job.first_at is not None) and texts(fast.poll()) == ANSWER
    assert scene.count(PRIMARY) == 2      # resting: the first road is not asked first any more


def test_a_word_of_the_first_road_between_two_silent_losses_clears_the_count(scene):
    scene.plan(G120, say(), say())
    scene.plan(PRIMARY, hang, say(), hang)
    fast, clock = channel(scene)
    silent_loss(fast, scene, clock, 'q1', T0)
    clock.t = T0 + 10
    open_question(fast, 'q2', 'Что такое масса?')
    assert until(lambda: fast.job.first_at is not None) and texts(fast.poll()) == ANSWER and scene.asked.count(PRIMARY) == 2      # it spoke
    over(fast)
    fast.poll()
    scene.plan(G120, say())
    silent_loss(fast, scene, clock, 'q3', T0 + 20)
    assert reserve_text._PRIMARY['until'] == 0.0


# --- the cloud has its own answer to the open question: dead roads hand the question back, no sentence is said -------------------------------

def hanging_to(fast, clock, scene, until_s):
    """Every road hangs; the loop ticks each second to ``until_s`` (exclusive) so the walkers are asked at 0, 2, 4, 6 s."""
    for second in range(1, int(until_s)):
        clock.t = T0 + second
        fast.poll()
        until(lambda: len(scene.asked) >= (2 if second < 6 else 3))


def test_with_the_cloud_answer_the_guard_says_no_refusal_at_eight_seconds_the_roads_are_dead_as_failed_and_the_retry_is_off(scene):
    fast, clock = channel(scene, cloud=False)
    fast.cloud_answer = lambda: True
    open_question(fast)
    hanging_to(fast, clock, scene, 8)
    clock.t = T0 + reserve_text.REFUSE_AFTER_S
    events = fast.poll()
    assert kinds(events) == ['failed'] and texts(events) == '' and not fast._refuse and fast._spent == 'q1' and not fast.off
    assert open_question(fast) == 'off'      # the retry of the controller goes straight to the cloud


def test_without_the_cloud_answer_all_is_as_before_the_refusal_at_eight_and_done_at_twelve(scene):
    fast, clock = channel(scene, cloud=False)
    fast.cloud_answer = lambda: False
    open_question(fast)
    hanging_to(fast, clock, scene, 8)
    clock.t = T0 + 8.0
    assert [e['text'] for e in fast.poll()] == [reserve_text.REFUSAL]
    clock.t = T0 + reserve_text.GIVE_UP_S
    assert kinds(fast.poll()) == ['done'] and open_question(fast) == 'off'


def test_a_cloud_answer_that_raises_is_no_answer(scene):
    def broken():
        raise RuntimeError('the ledger is gone')
    fast, clock = channel(scene, cloud=False)
    fast.cloud_answer = broken
    open_question(fast)
    hanging_to(fast, clock, scene, 8)
    clock.t = T0 + 8.0
    assert [e['text'] for e in fast.poll()] == [reserve_text.REFUSAL]
    clock.t = T0 + reserve_text.GIVE_UP_S
    assert kinds(fast.poll()) == ['done']


def test_the_cloud_that_answers_a_tick_before_the_limit_wins_and_the_cloud_that_answers_after_the_sentence_wins_at_the_same_second(scene):      # replaces ..._and_the_cloud_that_answers_after_the_refusal_does_not
    early, clock = channel(scene, cloud=False)
    answered = {'at': 7.9}
    early.cloud_answer = lambda: clock.t - T0 >= answered['at']
    open_question(early)
    hanging_to(early, clock, scene, 8)
    clock.t = T0 + 7.9
    assert early.poll() == []
    clock.t = T0 + 8.0
    assert kinds(early.poll()) == ['failed']      # 7.9 s: no refusal was due, 8 s: dead
    scene2 = Scene()
    late, clock2 = channel(scene2, cloud=False)
    late.cloud_answer = lambda: clock2.t - T0 >= 8.1
    open_question(late)
    hanging_to(late, clock2, scene2, 8)
    clock2.t = T0 + 8.0
    assert [e['text'] for e in late.poll()] == [reserve_text.REFUSAL]
    clock2.t = T0 + 8.1
    said = late.poll()
    clock2.t = T0 + 8.2
    assert kinds(said + late.poll()) == ['done']      # U134/arrival order, replaces `late.poll() == []` at 8.1 (the answer of the cloud that came after the sentence did not end the job until 12 s): the question is dead at the same eight seconds as when the cloud's text came first (done: the sentence was said)
    clock2.t = T0 + reserve_text.GIVE_UP_S
    assert late.poll() == []
    scene2.over.set()


# --- a slow first road with the whole reserve refusing is still heard; a controller that lets a job go, an interruption and a close are no stall of a road ----------------------

def tick(fast, clock, upto, dt=0.1):
    """The loop ticks every ``dt`` virtual seconds to ``upto``; the events that came."""
    events = []
    while clock.t < upto - 1e-9:
        clock.t = round(clock.t + dt, 6)
        events += [dict(e, at=round(clock.t - T0, 1)) for e in fast.poll()]
        time.sleep(0.004)
    return events


def at_time(clock, when, text=ANSWER):
    """A road that is healthy but slow: its first word at the virtual moment ``when``."""
    def behave(scene, cancelled):
        while clock.t < when and not scene.over.is_set() and not (cancelled is not None and cancelled.is_set()):
            time.sleep(0.002)
        return iter([text]) if clock.t >= when and not (cancelled is not None and cancelled.is_set()) else iter(())
    return behave


@pytest.mark.parametrize('tail', [True, False])
def test_a_slow_first_road_with_every_reserve_road_refusing_is_heard_to_the_give_up_time_and_gets_no_stall(scene, tail):
    fast, clock = channel(scene, cloud=not tail)
    scene.plan(PRIMARY, at_time(clock, T0 + 6.0))
    for road in (G120, G20, GEM):
        scene.plan(road, fail(ReserveError('http_429')))
    assert open_question(fast) == 'started'
    events = tick(fast, clock, T0 + 7.9)
    texted = [e for e in events if e['kind'] == 'text' and not e.get('provisional')]
    assert texted and texted[0]['text'] == ANSWER and texted[0]['at'] >= 6.0 and 'failed' not in kinds(events), events
    events += [] if 'done' in kinds(events) else drain(fast)
    assert 'done' in kinds(events) and 'failed' not in kinds(events)
    assert scene.asked.count(PRIMARY) == 1 and fast._spent is None
    assert reserve_text._PRIMARY['until'] == 0.0      # the first road is not given a stall for this question
    assert not fast.roads._stalls.get(PRIMARY)


@pytest.mark.parametrize('tail', [False, True])
def test_a_job_the_controller_let_go_before_its_first_word_is_not_resurrected_on_a_new_road(scene, tail):
    scene.plan(G120, say())
    fast, clock = channel(scene, cloud=not tail)
    assert open_question(fast) == 'started' and until(lambda: scene.asked == [PRIMARY])
    tick(fast, clock, T0 + 0.5)
    fast.finish('tq1')      # the controller keeps nothing of it (a pump failure, a stale question)
    events = tick(fast, clock, T0 + 3.0)
    until(lambda: False, 0.1)
    assert scene.asked == [PRIMARY] and events == [] and fast.job is None and fast.twin is None


def test_two_questions_the_listener_interrupts_at_two_seconds_do_not_rest_the_first_road(scene):
    fast, clock = channel(scene)
    for n in (1, 2):
        assert open_question(fast, f'q{n}', f'Что такое {n}?') == 'started' and until(lambda: scene.count(PRIMARY) == n)
        tick(fast, clock, clock.t + 1.9)      # healthy and slow: no road asked yet
        clock.t += 0.2
        fast.retain(f'q{n + 1}')      # a new question: the old job is cancelled by the controller, the road did not fail
    assert reserve_text._PRIMARY['until'] == 0.0 and not fast.roads._stalls.get(PRIMARY)


def test_a_close_with_a_silent_flying_job_and_a_job_that_was_let_go_rest_no_road(scene):
    fast, clock = channel(scene)
    assert open_question(fast, 'q1') == 'started' and until(lambda: scene.count(PRIMARY) == 1)
    tick(fast, clock, T0 + 1.9)
    clock.t += 0.2
    fast.finish('tq1')      # the controller let it go at 2.1 s
    assert open_question(fast, 'q2', 'Что такое масса?') == 'started' and until(lambda: scene.count(PRIMARY) == 2)
    clock.t += 2.1
    fast.close()      # the end of the call: the road is no reason to rest in the next call (the rest is the process's)
    assert reserve_text._PRIMARY['until'] == 0.0 and not fast.roads._stalls.get(PRIMARY)


def test_a_stall_let_go_a_loser_of_the_race_and_the_flying_at_the_dead_time_are_losses_of_their_road(scene):
    scene.plan(G120, say(), say())
    fast, clock = channel(scene)
    silent_loss(fast, scene, clock, 'q1', T0)
    silent_loss(fast, scene, clock, 'q2', T0 + 10)      # the loser of the race, twice: the first road rests
    assert reserve_text._PRIMARY['until'] == T0 + 10 + NEXT_ROAD_S + reserve_text.PRIMARY_FAIL_REST_S
    reserve_text._PRIMARY['until'] = 0.0
    fast.roads._stalls.clear()
    for n, start in ((3, T0 + 20), (4, T0 + 40)):      # every road hangs: the first road is let go at 4 s (a stall), then the question is dead at 8 s
        scene.plan(G120, hang)
        clock.t = start
        assert open_question(fast, f'q{n}', f'Что такое {n}?') == 'started'
        for second in range(1, 9):
            clock.t = start + second
            fast.poll()
            until(lambda: False, 0.03)
    assert reserve_text._PRIMARY['until'] > clock.t - 8


def test_a_failed_question_is_told_only_after_the_owner_said_dead_so_the_retry_of_the_same_question_is_off(scene):
    gate = threading.Event()

    def gated(scene_, cancelled):
        gate.wait(2.0)
        raise ReserveError('http_503')
        yield
    scene.plan(PRIMARY, gated)
    for road in (G120, G20, GEM, QWEN):
        scene.plan(road, fail(ReserveError('http_503')))
    fast, clock = channel(scene)
    real_step = fast.roads.step

    def step(now, tried, walk, **kw):
        acts = real_step(now, tried, walk, **kw)
        gate.set()
        until(lambda: fast.job is not None and fast.job.outcome is not None, 1.0)      # the thread ends right after the step looked, before the poll reads the outcome
        return acts
    fast.roads.__dict__['step'] = step
    assert open_question(fast) == 'started'
    clock.t += 0.1
    assert fast.poll() == [] and fast._spent is None      # over with no word, and dead is not said yet: held
    clock.t += 0.1
    assert kinds(fast.poll()) == ['failed'] and fast._spent == 'q1'      # told once, after dead
    asked = len(scene.asked)
    assert open_question(fast) == 'off'
    clock.t += 0.1
    assert fast.poll() == [] and len(scene.asked) == asked


# --- silence is the host: every road of a hanging host is skipped for the live one ---------------------------------------------------

@pytest.mark.parametrize('first', ['hang', 'refuse'])
def test_every_groq_road_hanging_gemini_is_asked_when_the_silent_groq_road_is_let_go_and_its_text_comes_with_no_refusal(scene, first):
    scene.plan(PRIMARY, hang if first == 'hang' else fail(ReserveError('http_429')))
    scene.plan(GEM, say())
    fast, clock = channel(scene, cloud=False)
    open_question(fast)
    assert until(lambda: scene.asked[:1] == [PRIMARY])
    events, moment = [], None
    for tick in range(0, 70):
        clock.t = T0 + tick / 10
        events += fast.poll()
        time.sleep(0.01)
        if GEM in scene.asked and moment is None:
            moment = tick / 10
    assert until(lambda: GEM in scene.asked)
    events += drain(fast)
    assert scene.asked == [PRIMARY, G120, GEM]      # not another Groq model: they hang with the host
    assert moment is not None and moment <= (6.2 if first == 'hang' else 2.2) and texts(events) == ANSWER and reserve_text.REFUSAL not in texts(events)


# --- a word nobody heard is no word: a twin that spoke and broke while the released job ended with none does not hold the failure for ever ------------------------------------------------

def hang_then_fail(clock, when, error):
    """A road that says nothing and ends in ``error`` at the virtual moment ``when`` (a ReadTimeout of a reserve road)."""
    def behave(scene, cancelled):
        while clock.t < when and not scene.over.is_set():
            time.sleep(0.002)
        raise error
        yield
    return behave


def word_and_break(scene, cancelled):
    yield 'Инерция '
    raise ReserveError('RemoteProtocolError')


def held_twin_scene(scene, clock):
    """The first road refuses at once; the second walker hangs to a timeout at 6 s; the last road (asked from 2 s on, when the others refused at once) says a word and breaks."""
    scene.plan(PRIMARY, fail(CR.FastTextError('http_429')))
    scene.plan(G120, hang_then_fail(clock, T0 + 6.0, ReserveError('ReadTimeout')))
    scene.plan(QWEN, word_and_break)
    for road in (GEM, G20):
        scene.plan(road, fail(ReserveError('http_429')))


@pytest.mark.parametrize('tail', [False, True])
def test_a_twin_that_spoke_and_broke_while_the_released_job_ended_with_no_word_does_not_hold_the_failure_for_ever(scene, tail):
    fast, clock = channel(scene, cloud=not tail)
    held_twin_scene(scene, clock)
    assert open_question(fast) == 'started'
    events = tick(fast, clock, T0 + 40.0)
    ended = [e for e in events if e['kind'] in ('failed', 'done')]
    assert ended and ended[0]['at'] <= (12.3 if tail else 6.3) and not texts([e for e in events if not e.get('provisional')]), events      # nobody heard the word of the twin
    assert scene.asked[0] == PRIMARY and scene.asked[-1] == QWEN and scene.count(G120) == 1
    assert open_question(fast) == 'off'      # the roads were found dead: the retry goes to the cloud
    clock.t += 1.0
    assert fast.poll() == [] and fast.job is None and fast.twin is None


def test_a_channel_whose_owner_says_nothing_still_closes_a_question_nobody_flies_for(scene, monkeypatch):
    refusing_all(scene)
    fast, clock = channel(scene)
    monkeypatch.setattr(fast.roads, 'step', lambda *args, **kwargs: [])      # an owner that never decides
    assert open_question(fast) == 'started' and over(fast)
    events = []
    for _ in range(3):
        events += fast.poll()
    assert kinds(events) == ['failed'] and fast._spent == 'q1'      # no flyer, no word, no decision: the channel itself calls the question dead
    assert open_question(fast) == 'off'
    clock.t += 40.0
    assert fast.poll() == [] and fast.job is None


# --- one speaker to a question: the words of two roads are never one answer -----------------------------------------------------------

def gated(gate, piece, then=None):
    """A road that waits for ``gate`` (an Event), says ``piece`` and then ends, or raises ``then``."""
    def behave(scene, cancelled):
        while not gate.is_set() and not scene.over.is_set():
            time.sleep(0.002)
        yield piece
        if then is not None:
            raise then
    return behave


def road_b_breaking(scene, gate):
    """B says its word at once and breaks when ``gate`` opens."""
    yield 'Слово дороги Б. '
    while not gate.is_set() and not scene.over.is_set():
        time.sleep(0.002)
    raise ReserveError('http_503')


def test_a_whole_answer_that_ends_in_the_window_of_a_begun_one_is_the_answer_and_the_break_of_the_begun_one_mixes_nothing(scene):
    gate_a, gate_b = threading.Event(), threading.Event()
    scene.plan(PRIMARY, gated(gate_a, 'Слово дороги А. '))
    scene.plan(G120, lambda s, c: road_b_breaking(s, gate_b))
    fast, clock = channel(scene)
    open_question(fast)
    clock.t = T0 + NEXT_ROAD_S
    fast.poll()      # B is asked
    assert until(lambda: fast.twin is not None and fast.twin.first_at is not None)      # B spoke first ...
    clock.t = T0 + NEXT_ROAD_S + 0.1
    gate_a.set()
    assert until(lambda: fast.job.outcome == 'ok')      # ... and A ended whole before the loop looked
    events = drain(fast)
    assert texts(events) == 'Слово дороги А.' and kinds(events)[-1] == 'done'      # the text of a job is cut at its end (strip_process_prefix)
    gate_b.set()
    clock.t = T0 + 5
    events += fast.poll()
    assert 'Слово дороги Б.' not in texts(events) and 'failed' not in kinds(events)


def test_a_begun_answer_that_won_is_the_only_speaker_and_a_whole_one_that_ends_later_is_not_mixed_in_when_it_breaks(scene):
    gate_a, gate_b = threading.Event(), threading.Event()
    scene.plan(PRIMARY, gated(gate_a, 'Слово дороги А. '))

    scene.plan(G120, lambda s, c: road_b_breaking(s, gate_b))
    fast, clock = channel(scene)
    open_question(fast)
    clock.t = T0 + NEXT_ROAD_S
    fast.poll()
    assert until(lambda: fast.twin is not None and fast.twin.first_at is not None)
    events = fast.poll()      # B won: the owner heard it
    assert texts(events) == 'Слово дороги Б.'
    clock.t = T0 + 2.5
    gate_a.set()
    assert until(lambda: all(j.outcome is not None for j in (fast.job, fast.twin) if j is not None and j.first_at is not None and j is not fast.job))
    gate_b.set()
    clock.t = T0 + 3.0
    assert over(fast)
    events += drain(fast, 'failed')
    assert texts(events) == 'Слово дороги Б.' and kinds(events)[-1] == 'failed' and 'done' not in kinds(events)


def test_a_repeated_question_whose_first_asking_was_voiced_still_has_its_refusal_deadline_and_its_dead_time(scene):
    scene.plan(PRIMARY, say())
    fast, clock = channel(scene, cloud=False)
    open_question(fast)
    events = drain(fast)
    assert texts(events) == ANSWER and kinds(events)[-1] == 'done'      # the first asking of q1 was voiced: the controller got its word
    assert fast.job is None
    clock.t = T0 + 100
    open_question(fast)      # the same question asked again (a repeat): every road hangs now
    for second in (2, 4, 6):
        clock.t = T0 + 100 + second
        fast.poll()
        until(lambda: len(scene.asked) >= 1 + second // 2 + 1)
    clock.t = T0 + 100 + reserve_text.REFUSE_AFTER_S
    ev = fast.poll()      # the word of the first asking is no word of this one: the honest sentence is due at its time, as for any question
    assert [(e['kind'], e['text']) for e in ev] == [('text', reserve_text.REFUSAL)]
    clock.t = T0 + 100 + reserve_text.GIVE_UP_S
    assert kinds(fast.poll()) == ['done'] and fast._spent == 'q1'
