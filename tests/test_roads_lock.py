"""always-answer, the lock on the QUANTITY and not on the cases: ``fast_text.FastText`` over the real ``reserve_text.Roads`` with 2000 random scenarios (and 200 more for each of the last two) (a seed makes one, ``random.Random(seed)``, no hypothesis; they come in batches of 100 seeds, the batch is in the name of the test)
and six invariants that must hold on every one of them, so that the next defect of this kind is caught without anybody having thought of its scenario.

A scenario: 3-6 roads (the first is ``codex``, the reserve on two hosts as in ``reserve_text.ROADS``: several keys of Groq, one or two of Gemini), each with a behavior drawn from: an answer at once, an answer after d seconds, a refusal at once (429, 401, 500,
a refused connection), an empty answer, white space only, a hang for ever, a hang that the road itself ends with a time-out at 6 s, a word and a cut right after it, a word, a pause, a cut, a usage with no text, an answer that drips for seconds.
Besides: the tail guard on or off, ``cloud_answer`` False / True / True from a random moment, a question prepared 0-3 s before its release or not, and (rarely) something from outside: ``finish(turn)``, ``retain(other)``, a release of a new question, ``close()``.

The invariants (checked on every tick of 0.1 s of the virtual time, to 45 s after the release):
  L1 a question always ends: not later than the TERM (8 s, 12 s with the guard, 8 s with the guard when the cloud has its answer by the 8th second, +0.3 s; a road that has said a word and whose text is handed on extends it to the end of its answer,
     never beyond WHOLE_S + 0.3 s from its request) the channel tells ONE ending event, done or failed; after it nothing of that question comes and ``fast.job is None``.
  L2 the answer of a living road is not lost: what a simple model of the rules of the roads (written here from SPEC.md, not from the code) says is the first word before the time to give up, is the text of the question, and it ends with done.
  L3 the roads are not mixed: all the text of a question (but the provisional refusal) is the beginning of the scripted answer of ONE road.
  L4 never more than two requests at once; no eternal thread (after the end of a scenario and the release of the roads that hang, no thread of a road lives).
  L5 a retry does not drive the roads: after a question that ended with no word the release of the same qid is 'off' and no road is asked; a new qid with one road alive is answered.
  L6 a rest is an order, not a ban: three questions in a row on one scenario, the third has a road that comes alive: it is not 'off', and it is answered.

The threads of the roads are synchronized with the test, not slept with: a road thread runs only when the test lets it (a baton, one thread at a time, in the order of the jobs) and parks at every wait of the virtual time (``Scene.park``); the test goes on
when every thread of a road is parked or over. So a scenario has one history, whatever the machine. A failure says its seed, the scenario in a line and the journal: ``LOCK_SEED=<seed> python -m pytest tests/test_roads_lock.py -k one_seed`` repeats it."""
import json
import logging
import os
import random
import threading
import time
from collections import namedtuple

import pytest

from echo_sync import fast_text as FT
from echo_sync import codex_road as CR
from echo_sync import reserve_text
from echo_sync.reserve_text import PRIMARY, ReserveError, ReserveStream, Roads

T0, SKEW = 100.0, 1e-8      # the virtual clock: T0 + k / 10 + k * SKEW (the skew keeps the boundaries of ``>=`` as the exact arithmetic has them: a difference of ideal 2.0 s is never 1.9999999999 s)
HORIZON = 450               # ticks of 0.1 s after the release
SEEDS = 2000
BATCH = 100
SIDE = 200                  # seeds of L5 and L6
KEYS = {'GROQ_API_KEY': 'kg1', 'GROQ_API_KEY_2': 'kg2', 'GEMINI_API_KEY': 'km1', 'GEMINI_API_KEY_2': 'km2'}
ALIAS = {'GROQ_API_KEY': 'groq1', 'GROQ_API_KEY_2': 'groq2', 'GEMINI_API_KEY': 'gem1', 'GEMINI_API_KEY_2': 'gem2'}
WORDS = ('альфа', 'бета', 'гамма', 'дельта', 'эпсилон', 'дзета')
QUESTION, QUESTION2, QUESTION3 = 'Что такое инерция?', 'Что такое масса?', 'Что такое сила?'
WHOLE = int(FT.WHOLE_S * 10)


@pytest.fixture(autouse=True)
def _fresh():
    log = logging.getLogger('echo-sync')
    level, log.level = log.level, logging.CRITICAL
    _clear()
    yield
    _clear()
    log.level = level


def _clear():
    reserve_text._REST.clear()
    reserve_text._BUDGET.clear()
    reserve_text._PRIMARY['until'] = 0.0


# --- the scenario ---------------------------------------------------------------------------------------------------------------------

Beh = namedtuple('Beh', 'kind a b', defaults=(0, ()))      # kind, a: a number (tenths of a second, or a code), b: more numbers
Road = namedtuple('Road', 'label id host beh pieces')
Scenario = namedtuple('Scenario', 'seed roads tail cloud lead disturb')      # cloud: None | the tenth the cloud answer comes at; lead: tenths the question is prepared before its release; disturb: None | (what, tenth)

def tied(r):
    """The delay of a slow road: now and then at the very tick the loop decides at (2 s: the next road, 4 s: the stall, and one tick about them), otherwise anywhere."""
    pick = 0.0 if getattr(r, 'tight', False) else r.random()
    return r.choice([19, 20, 21, 22, 39, 40, 41, 42]) if pick < 0.25 else r.randint(15, 45) if pick < 0.5 else r.randint(1, 70)


# a delay is often drawn about the moments the loop moves at (2 and 4 s): the answers that come at the very tick of a decision
FULL = [(10, lambda r: Beh('now')), (16, lambda r: Beh('delay', tied(r))), (16, lambda r: Beh('refuse', r.choice(['429', '401', '500', 'conn']))), (5, lambda r: Beh('empty')), (4, lambda r: Beh('blank')),
        (10, lambda r: Beh('hang')), (10, lambda r: Beh('timeout')), (12, lambda r: Beh('cut_now')), (8, lambda r: Beh('cut_pause', r.randint(1, 60))), (4, lambda r: Beh('usage')),
        (6, lambda r: Beh('drip', r.randint(0, 20), tuple(r.randint(5, 30) for _ in range(r.randint(2, 5)))))]
DEAD = [(28, lambda r: Beh('refuse', r.choice(['429', '401', '500', 'conn']))), (10, lambda r: Beh('empty')), (8, lambda r: Beh('blank')), (28, lambda r: Beh('hang')), (18, lambda r: Beh('timeout')), (8, lambda r: Beh('usage'))]


def draw(rnd, table):
    return rnd.choices([make for _, make in table], weights=[weight for weight, _ in table])[0](rnd)


def pieces_of(word, beh):
    first = f'Дорога {word} даёт ответ. '
    if beh.kind in ('now', 'delay'):
        return (first, 'Он целый и понятный. ')
    if beh.kind == 'drip':
        return (first,) + tuple(f'Часть {n} идёт дальше. ' for n in range(1, len(beh.b) + 1))
    return (first,)


def timeline(beh):
    """The events of a road from the moment it is asked, ``(tenths after it, what)``: the model's own reading of a behavior."""
    kind, a = beh.kind, beh.a
    if kind == 'now':
        return [(0, 'word'), (0, 'ok')]
    if kind == 'delay':
        return [(a, 'word'), (a, 'ok')]
    if kind in ('refuse', 'empty', 'blank', 'usage'):
        return [(0, 'fail')]
    if kind == 'timeout':
        return [(60, 'fail')]
    if kind == 'cut_now':
        return [(0, 'word'), (0, 'break')]
    if kind == 'cut_pause':
        return [(0, 'word'), (a, 'break')]
    if kind == 'drip':
        return [(a, 'word'), (a + sum(beh.b), 'ok')]
    return []      # hang


def spec_of(beh):
    return beh.kind + ('' if not beh.a and not beh.b else f'({beh.a}{"," + ",".join(map(str, beh.b)) if beh.b else ""})')


def make_scenario(seed, *, dead=False, quiet=False):
    """The scenario of a seed. ``dead``: every road fails or hangs (L5, L6); ``quiet``: nothing prepared and nothing from outside (L5, L6)."""
    rnd = random.Random(seed)
    entries = list(reserve_text.ROADS)
    while True:
        chosen = sorted(rnd.sample(range(len(entries)), rnd.randint(2, 5)))
        hosts = {entries[i][1] for i in chosen}
        if len(hosts) == 2:
            break
    rnd.tight = rnd.random() < 0.2      # a fifth of the scenarios: the slow roads answer at the moments of the decisions
    table = DEAD if dead or rnd.random() < 0.2 else FULL      # one scenario in five has no living road at all
    roads = [Road('codex', PRIMARY, PRIMARY, draw(rnd, table), ())]
    for number, i in enumerate(chosen):
        name, base, model = entries[i]
        roads.append(Road(f'{ALIAS[name]}:{model.split("/")[-1]}', (name, model), base, draw(rnd, table), ()))
    roads = [road._replace(pieces=pieces_of(WORDS[number], road.beh)) for number, road in enumerate(roads)]
    tail = rnd.random() < 0.5
    pick = rnd.random()
    cloud = None if pick < 0.55 else 0 if pick < 0.7 else rnd.randint(1, 110)
    if quiet:
        cloud = None if cloud is None else 0
    lead = 0 if quiet or rnd.random() < 0.45 else rnd.randint(1, 30)
    disturb = None if quiet or rnd.random() > 0.14 else (rnd.choice(['finish', 'retain', 'release', 'close']), rnd.randint(1, 200))
    return Scenario(seed, roads, tail, cloud, lead, disturb)


def describe(sc):
    roads = ', '.join(f'{road.label}={spec_of(road.beh)}' for road in sc.roads)
    return f'seed={sc.seed} tail={sc.tail} cloud={sc.cloud} lead={sc.lead / 10} disturb={sc.disturb} roads=[{roads}]'


# --- the threads of the roads, parked and let go one at a time ------------------------------------------------------------------------

class _Park:
    def __init__(self, pred):
        self.pred, self.go = pred, threading.Event()


class Scene:
    """The virtual time ``k`` (tenths of a second after the release) and the road threads. A road thread runs only while the test lets it (``settle``): at every wait it ``park``s with the condition that ends it; ``settle`` lets go, one at a time,
    in the order of the jobs, the parked thread whose condition is true, and returns when every thread of a road is parked on a false condition or over."""

    def __init__(self):
        self.k, self.over, self.lock, self.local = 0, threading.Event(), threading.Lock(), threading.local()
        self.parked, self.number, self.runners, self.asks = {}, {}, {}, []

    def park(self, pred):
        entry = _Park(pred)
        with self.lock:
            self.parked[threading.get_ident()] = entry
        entry.go.wait()

    def settle(self, limit=30.0):
        end = time.monotonic() + limit
        while True:
            threads = [thread for thread in threading.enumerate() if thread.name == 'echo-fast-text']
            busy = False
            with self.lock:
                if any(thread.ident not in self.parked for thread in threads):
                    busy = True      # a thread that starts, runs or ends
                else:
                    ready = sorted((self.number.get(self.runners.get(ident, (None, None))[1], 0), ident) for ident, entry in self.parked.items() if entry.pred())
                    if ready:
                        entry = self.parked.pop(ready[0][1])
                        entry.go.set()
                        busy = True
            if not busy:
                return
            if time.monotonic() > end:
                raise AssertionError('the harness: a road thread neither parked nor ended in %.0f s (a lock or a loop in the code)' % limit)
            time.sleep(0.0001)

    def alive(self):
        return [thread for thread in threading.enumerate() if thread.name == 'echo-fast-text']


class Ev(namedtuple('Ev', 'k qid kind text provisional replaces')):
    def __str__(self):
        return f'{self.k / 10:.1f}s {self.qid} {self.kind}{" (provisional)" if self.provisional else ""}{" (replaces)" if self.replaces else ""} {self.text[:24]!r}'


class Rig:
    """A channel of the scenario: ``FastText`` over the real ``Roads`` with the scripted roads, a clock the test drives, one question after another."""

    def __init__(self, sc):
        self.sc, self.scene = sc, Scene()
        self.events, self.releases, self.live_max, self.flying_max, self.terminal_at, self.job_after = [], [], 0, 0, {}, []
        self.override = {}
        self.by_id = {road.id: road for road in sc.roads}
        entries = tuple(entry for entry in reserve_text.ROADS if (entry[0], entry[2]) in self.by_id)
        scene = self.scene
        self.clock = lambda: T0 + scene.k / 10 + scene.k * SKEW
        self.roads = Roads(self._primary, ReserveStream(KEYS, post=self._post, clock=self.clock, roads=entries), clock=self.clock)
        self.fast = FT.FastText(self.roads, instructions=lambda: 'POLICY', history=lambda: [], clock=self.clock, wake=lambda: None)
        if not sc.tail:
            self.fast.cloud_answer = lambda: True      # ``tail`` False: the cloud has an answer of its own all along: the roads give up at ALL_DEAD_S and say no sentence
        elif sc.cloud is not None:
            self.fast.cloud_answer = lambda: scene.k >= sc.cloud
        walk = self.roads

        def stream(request, cancelled, walk_=None):
            scene.local.cancelled = cancelled
            scene.runners[threading.get_ident()] = (threading.current_thread(), cancelled)
            scene.park(lambda: True)      # the thread starts when the test lets it
            yield from walk(request, cancelled, walk_)
        self.fast.stream = stream
        start = self.fast._start

        def numbered(*args, **kwargs):
            job = start(*args, **kwargs)
            scene.number[job.cancelled] = job.number
            return job
        self.fast._start = numbered

    # -- what a road does --------------------------------------------------------------------------------------------------------------
    def _primary(self, request, cancelled):
        yield from self._behave(self.by_id[PRIMARY], cancelled)

    def _post(self, url, headers, body, timeout):
        name = next(key for key, value in KEYS.items() if headers['Authorization'].endswith(value))
        for piece in self._behave(self.by_id[(name, body['model'])], None):
            data = {'choices': [], **piece} if isinstance(piece, dict) else {'choices': [{'delta': {'content': piece}}]}
            yield 'data: ' + json.dumps(data)
        yield 'data: [DONE]'

    def _behave(self, road, cancelled):
        """The behavior of ``road`` (``cancelled``: the job's event for the first road, which sees a cancel at once; None for a reserve road, whose request is blocked in the net until it ends)."""
        scene, beh = self.scene, self.override.get(road.label, road.beh)
        start = scene.k
        scene.asks.append((road.label, start))
        pieces = road.pieces if beh == road.beh else pieces_of(WORDS[self.sc.roads.index(road)], beh)

        def sleep_to(k):
            scene.park(lambda: scene.k >= k or scene.over.is_set() or (cancelled is not None and cancelled.is_set()))
            return not (scene.over.is_set() or (cancelled is not None and cancelled.is_set()))
        kind, error = beh.kind, (CR.FastTextError if road.id == PRIMARY else ReserveError)
        if kind == 'now':
            yield from pieces
        elif kind == 'delay':
            if sleep_to(start + beh.a):
                yield from pieces
        elif kind == 'refuse':
            raise ConnectionRefusedError('refused') if beh.a == 'conn' else error(f'http_{beh.a}')
        elif kind == 'empty':
            return
        elif kind == 'blank':
            yield '   '
        elif kind == 'usage':
            yield {'usage': {'prompt_tokens': 10, 'completion_tokens': 0, 'total_tokens': 10}}
        elif kind == 'hang':
            sleep_to(10 ** 9)
        elif kind == 'timeout':
            if sleep_to(start + 60):
                raise TimeoutError('road_timeout')
        elif kind == 'cut_now':
            yield pieces[0]
            raise error('no_terminal_event')
        elif kind == 'cut_pause':
            yield pieces[0]
            if sleep_to(start + beh.a):
                raise error('no_terminal_event')
        elif kind == 'drip':
            if beh.a and not sleep_to(start + beh.a):
                return
            yield pieces[0]
            moment = start + beh.a
            for gap, piece in zip(beh.b, pieces[1:]):
                moment += gap
                if not sleep_to(moment):
                    return
                yield piece

    # -- the loop ------------------------------------------------------------------------------------------------------------------------
    def prepare(self, text=QUESTION):
        self.fast.prepare(text)
        self.scene.settle()

    def release(self, qid, text=QUESTION):
        result = self.fast.release(qid=qid, turn='t' + qid, epoch=1, question=text)
        self.releases.append((qid, self.scene.k, result))
        self.scene.settle()
        return result

    def tick(self):
        scene = self.scene
        scene.k += 1
        scene.settle()      # the roads whose time has come speak (before the loop looks)
        self._disturb()
        for event in self.fast.poll():
            self.events.append(Ev(scene.k, event['qid'], event['kind'], event.get('text', ''), bool(event.get('provisional')), bool(event.get('replaces'))))
            if event['kind'] in ('done', 'failed') and event['qid'] not in self.terminal_at:
                self.terminal_at[event['qid']] = scene.k
        scene.settle()      # the roads the loop has just started
        live = sum(1 for thread, cancelled in scene.runners.values() if thread.is_alive() and not cancelled.is_set())
        flying = [job for job in (self.fast.job, self.fast.twin) if job is not None and job.outcome is None]
        self.live_max, self.flying_max = max(self.live_max, live), max(self.flying_max, len(flying))
        for qid, at in self.terminal_at.items():
            job = self.fast.job
            if job is not None and job.released is not None and job.released['qid'] == qid and not self.job_after:
                self.job_after.append(f'fast.job of {qid} is still there at {scene.k / 10:.1f}s (its ending came at {at / 10:.1f}s)')

    def _disturb(self):
        disturb = self.sc.disturb
        if disturb is None or disturb[1] != self.scene.k:
            return
        what = disturb[0]
        if what == 'finish':
            self.fast.finish('tq1')
        elif what == 'retain':
            self.fast.retain('other')
        elif what == 'release':
            self.fast.release(qid='q2', turn='tq2', epoch=1, question=QUESTION2)
        else:
            self.fast.close()

    def run_to_end(self, qid, cap=200):
        """Ticks until the ending event of ``qid`` came (a few ticks past it), at most ``cap``."""
        for _ in range(cap):
            self.tick()
            if qid in self.terminal_at:
                break

    def finish(self):
        """The end of a scenario: the roads that hang are let go; what is left alive is an eternal thread."""
        self.scene.over.set()
        try:
            self.scene.settle()
        except AssertionError as error:
            self.stuck = str(error)
        end = time.monotonic() + 3.0
        while self.scene.alive() and time.monotonic() < end:
            time.sleep(0.001)
        self.leftover = len(self.scene.alive())

    stuck = None
    leftover = 0


# --- the model of the rules of the roads (from SPEC.md, not from the code) ------------------------------------------------------------

def predict(roads, order, lead, beh_of):
    """What the rules (SPEC section 2: the roads are walked in ``order``; a refusal or an empty answer before the first word is the next road at once; a road silent 2.0 s gets the next one asked too, never more than two fly; a road silent 4.0 s with a road left
    untaken is let go; a host of a silent road is last; the first word wins, but a whole answer that is over in the same look beats a begun one) say about a question: ``('win', label, full)`` the first word, with the time in tenths (``full``: the road ends its answer in time), ``('dead',)`` no word ever,
    ``None`` when the rules do not decide it alone (a road that says a word and breaks between two looks of the loop: the repair of such a case is the owner's, not a rule; a prepared walker that ended before the release)."""
    host = {road.label: road.host for road in roads}
    beh = {road.label: beh_of(road) for road in roads}
    taken, muted, walkers = set(), set(), []

    def pick():
        left = [label for label in order if label not in taken]
        left = [label for label in left if host[label] not in muted] + [label for label in left if host[label] in muted]
        return left[0] if left else None

    def start(walker, at):
        label = pick()
        if label is None:
            walker['ended'], walker['road'] = 'err', None
            return
        taken.add(label)
        walker.update(road=label, since=at, events=timeline(beh[label]), i=0)
        walker.setdefault('t0', at)

    def run(now):
        moved = True
        while moved:
            moved = False
            for walker in walkers:
                while not walker['cancelled'] and walker['ended'] is None and walker['i'] < len(walker['events']) and walker['since'] + walker['events'][walker['i']][0] <= now:
                    rel, what = walker['events'][walker['i']]
                    walker['i'] += 1
                    if what == 'word':
                        walker['word'], walker['spoke'] = walker['since'] + rel, walker['road']
                    elif what == 'ok':
                        walker['ended'], walker['end'] = 'ok', walker['since'] + rel
                    elif what == 'break':
                        walker['ended'], walker['end'] = 'err', walker['since'] + rel
                    else:
                        start(walker, walker['since'] + rel)
                        moved = True

    def new(at):
        walker = dict(number=len(walkers) + 1, cancelled=False, ended=None, word=None, spoke=None, road=None, since=at, events=[], i=0)
        walkers.append(walker)
        start(walker, at)
        return walker
    new(-lead)
    for now in range(-lead, 160):
        run(now)
        if now <= 0:
            if walkers[0]['ended'] == 'err' and walkers[0]['word'] is None and now == 0 and lead:
                return None      # the prepared walker is over with no word before the release: a new job on the roads as they rest after it
            continue
        live = [w for w in walkers if not w['cancelled']]
        texted = [w for w in live if w['word'] is not None and w['ended'] in (None, 'ok')]
        if texted:
            win = min(texted, key=lambda w: (w['ended'] != 'ok', w['word'], w['number']))      # a whole answer beats a begun one in the same look; then the earlier first word
            label, rel = win['spoke'], win['word'] - win['since']
            kind = beh[label].kind
            if kind in ('now', 'delay', 'drip'):
                end = win['end'] if win['ended'] == 'ok' else win['since'] + timeline(beh[label])[-1][0]
                margin = win['t0'] + WHOLE - end
                if -2 <= margin <= 2:
                    return None
                return ('win', label, margin > 0, win['word'])
            return ('win', label, False, win['word'])
        if any(w['word'] is not None for w in live):
            return None      # it spoke and broke before the loop looked
        flying = [w for w in live if w['ended'] is None]
        left = [label for label in order if label not in taken]
        stood = lambda w: now - w['since']
        stalled = [w for w in flying if stood(w) >= 40 and w['road'] != 'codex'] if left else []      # the first road is never let go for a reserve road that is silent too: it lives to the time to give up
        for w in stalled:
            w['cancelled'] = True
            muted.add(host[w['road']])
        rest = [w for w in flying if w not in stalled]
        if not rest and not left:
            return ('dead',)
        if left and (not rest or (len(rest) == 1 and stood(rest[0]) >= 20)):
            for w in rest:
                if stood(w) >= 20:
                    muted.add(host[w['road']])
            new(now)
            run(now)
    return ('dead',)


def bounds(sc):
    """(the base of the term of L1, the lower bound of the time to give up) in tenths."""
    if not sc.tail or (sc.cloud is not None and sc.cloud <= 79):
        return 80, 80
    if sc.cloud is not None and sc.cloud <= 81:
        return 120, 80
    return 120, 120


# --- the runs ------------------------------------------------------------------------------------------------------------------------

Run = namedtuple('Run', 'sc rig')
_RUNS = {}


def run_main(seed):
    if seed in _RUNS:
        return _RUNS[seed]
    _clear()
    sc = make_scenario(seed)
    rig = Rig(sc)
    try:
        if sc.lead:
            rig.scene.k = -sc.lead
            rig.prepare()
            for _ in range(sc.lead):
                rig.tick()
        rig.release('q1')
        for _ in range(HORIZON):
            rig.tick()
    except AssertionError as error:
        rig.stuck = str(error)
    finally:
        rig.finish()
        _clear()
    _RUNS[seed] = Run(sc, rig)
    return _RUNS[seed]


def journal(run):
    rig = run.rig
    return f'{describe(run.sc)}\n  releases={rig.releases}\n  asks={[(label, at / 10) for label, at in rig.scene.asks]}\n  events=[{"; ".join(map(str, rig.events))}]\n  repeat: LOCK_SEED={run.sc.seed} python -m pytest tests/test_roads_lock.py -k one_seed'


def delivered(rig, qid):
    return ''.join(e.text for e in rig.events if e.qid == qid and e.kind == 'text' and not e.provisional)


def speaker(run, qid):
    """The road whose scripted answer starts with the text handed on (None: no text; '?' none does)."""
    text = delivered(run.rig, qid)
    if not text:
        return None
    found = [road for road in run.sc.roads if ''.join(road.pieces).startswith(text)]
    return found[0] if found else '?'


def ending(rig, qid):
    return [e for e in rig.events if e.qid == qid and e.kind in ('done', 'failed')]


# --- L1 ---------------------------------------------------------------------------------------------------------------------------------

def l1(run):
    rig, sc = run.rig, run.sc
    out = []
    ends = ending(rig, 'q1')
    if rig.releases and rig.releases[0][2] == 'off':
        out.append('the release of the question is off: no job')
    if len(ends) > 1:
        out.append(f'{len(ends)} ending events')
    if ends:
        later = [e for e in rig.events if e.qid == 'q1' and rig.events.index(e) > rig.events.index(ends[0])]
        if later:
            out.append(f'events after the ending: {[str(e) for e in later]}')
    if rig.job_after and sc.disturb is None:
        out += rig.job_after
    if sc.disturb is not None:
        return out
    base, _ = bounds(sc)
    term = base + 3
    who = speaker(run, 'q1')
    if isinstance(who, Road):
        start = next(at for label, at in rig.scene.asks if label == who.label)
        term = max(term, min(start + timeline(who.beh)[-1][0] + 3, start + WHOLE + 3))
    if not ends:
        out.append(f'no ending event in {HORIZON / 10:.0f} s (the term was {term / 10:.1f} s)')
    elif ends[0].k > term:
        out.append(f'the ending came at {ends[0].k / 10:.1f} s, the term was {term / 10:.1f} s')
    if rig.fast.job is not None and rig.fast.job.released is not None and rig.fast.job.released['qid'] == 'q1' and ends:
        out.append('fast.job is not None at the end')
    return out


# --- L2 ---------------------------------------------------------------------------------------------------------------------------------

def l2(run):
    sc, rig = run.sc, run.rig
    if sc.disturb is not None:
        return []
    order = [road.label for road in sc.roads]
    guess = predict(sc.roads, order, sc.lead, lambda road: road.beh)
    if guess is None or guess[0] != 'win':
        return []
    _, label, full, at = guess
    _, ceiling = bounds(sc)
    if at > ceiling - 2:
        return []
    road = next(road for road in sc.roads if road.label == label)
    text, ends = delivered(rig, 'q1'), ending(rig, 'q1')
    whole = ''.join(road.pieces)
    out = []
    if not text:
        out.append(f'the model says the first word of {label} at {at / 10:.1f} s, and no text of the question came')
    elif not whole.startswith(text):
        out.append(f'the model says the first word of {label} at {at / 10:.1f} s, and the text is another: {text[:40]!r}')
    elif full and (text != whole or not ends or ends[-1].kind != 'done'):
        out.append(f'the model says the whole answer of {label} (first word at {at / 10:.1f} s): the text is {text!r}, the ending {[e.kind for e in ends]}')
    elif not full and ends and ends[-1].kind != 'failed' and road.beh.kind not in ('drip', 'cut_pause'):
        out.append(f'{label} breaks after its word: the ending must be failed, it is {[e.kind for e in ends]}')
    return out


# --- L3 ---------------------------------------------------------------------------------------------------------------------------------

def l3(run):
    out = []
    for qid in sorted({e.qid for e in run.rig.events}):
        if speaker(run, qid) == '?':
            out.append(f'the text of {qid} is the beginning of the answer of no road: {delivered(run.rig, qid)!r}')
    return out


# --- L4 ---------------------------------------------------------------------------------------------------------------------------------

def l4(run):
    rig, out = run.rig, []
    if rig.live_max > 2:
        out.append(f'{rig.live_max} requests live at once')
    if rig.flying_max > 2:
        out.append(f'{rig.flying_max} jobs fly at once')
    if rig.leftover:
        out.append(f'{rig.leftover} road threads live after the roads are let go')
    if rig.stuck:
        out.append(rig.stuck)
    return out


def check(batch_start, rule, name):
    failed = []
    for seed in range(batch_start, batch_start + BATCH):
        if os.environ.get('LOCK_SEED') and int(os.environ['LOCK_SEED']) != seed:
            continue
        run = run_main(seed)
        problems = rule(run)
        if problems:
            failed.append((seed, problems, journal(run)))
    if failed:
        shown = '\n'.join(f'- seed {seed}: {"; ".join(problems)}\n  {journal_}' for seed, problems, journal_ in failed[:3])
        pytest.fail(f'{name}: {len(failed)} of {BATCH} scenarios break it, seeds {[seed for seed, _, _ in failed]}:\n{shown}', pytrace=False)


BATCHES = [pytest.param(start, id=f'seeds_{start:03d}_{start + BATCH - 1:03d}') for start in range(0, SEEDS, BATCH)]


@pytest.mark.parametrize('first', BATCHES)
def test_L1_a_question_always_ends(first):
    check(first, l1, 'L1 a question always ends')


@pytest.mark.parametrize('first', BATCHES)
def test_L2_the_answer_of_a_living_road_is_not_lost(first):
    check(first, l2, 'L2 the answer of a living road is not lost')


@pytest.mark.parametrize('first', BATCHES)
def test_L3_the_roads_are_not_mixed(first):
    check(first, l3, 'L3 the roads are not mixed')


@pytest.mark.parametrize('first', BATCHES)
def test_L4_two_requests_at_most_and_no_eternal_thread(first):
    check(first, l4, 'L4 two requests at most, no eternal thread')


def test_the_scenarios_are_many_kinds_and_the_model_has_something_to_say():
    """The lock is no lock if the scenarios are all alike: every behavior, every flag is there, and L2's model decides a good part of them."""
    kinds, flags, said = set(), set(), 0
    for seed in range(SEEDS):
        sc = make_scenario(seed)
        kinds |= {road.beh.kind for road in sc.roads}
        flags |= {('tail', sc.tail), ('cloud', sc.cloud is None), ('lead', bool(sc.lead))} | ({('disturb', sc.disturb[0])} if sc.disturb else set())
        guess = predict(sc.roads, [road.label for road in sc.roads], sc.lead, lambda road: road.beh) if sc.disturb is None else None
        said += bool(guess and guess[0] == 'win' and guess[3] <= bounds(sc)[1] - 2)
    assert kinds == {'now', 'delay', 'refuse', 'empty', 'blank', 'hang', 'timeout', 'cut_now', 'cut_pause', 'usage', 'drip'}, kinds
    assert {('tail', True), ('tail', False), ('cloud', True), ('cloud', False), ('lead', True), ('lead', False), ('disturb', 'finish'), ('disturb', 'retain'), ('disturb', 'release'), ('disturb', 'close')} <= flags, flags
    assert said >= SEEDS * 0.4, said


# --- L5, L6 -----------------------------------------------------------------------------------------------------------------------------

def labels_in_order(rig):
    by_id = rig.by_id
    return [by_id[road].label for road in rig.roads.order({})]


def revive(run_rig, rnd):
    road = rnd.choice(run_rig.sc.roads)
    run_rig.override[road.label] = Beh('now')
    return road


def sequence(seed, kind):
    _clear()
    sc = make_scenario(seed + (100000 if kind == 'L5' else 200000), dead=kind == 'L5' or seed % 2 == 0, quiet=True)
    rnd = random.Random(f'{kind}-{seed}')
    rig = Rig(sc)
    problems = []
    try:
        rig.release('q1')
        rig.run_to_end('q1')
        if kind == 'L5':
            ends = ending(rig, 'q1')
            if not ends:
                problems.append('the first question did not end')
            asked = len(rig.scene.asks)
            again = rig.release('q1')
            for _ in range(30):
                rig.tick()
            if not delivered(rig, 'q1'):
                if again != 'off':
                    problems.append(f'the retry of a question that ended with no word is {again!r}, not off')
                if len(rig.scene.asks) != asked:
                    problems.append(f'the retry asked the roads: {rig.scene.asks[asked:]}')
                if rig.fast.job is not None:
                    problems.append('the retry left a job')
            for _ in range(rnd.randint(0, 50)):
                rig.tick()
            third, number = 'q2', 2
        else:
            for _ in range(rnd.randint(0, 30)):
                rig.tick()
            rig.release('q2', QUESTION2)
            rig.run_to_end('q2')
            for _ in range(rnd.randint(0, 30)):
                rig.tick()
            third, number = 'q3', 3
        ids = set(rig.by_id)
        if set(rig.roads.order({})) != ids or len(rig.roads.order({})) != len(ids):
            problems.append(f'the order of the roads is not all of them: {rig.roads.order({})}')
        road = revive(rig, rnd)
        order = labels_in_order(rig)
        result = rig.release(third, QUESTION3)
        if result == 'off' or any(r[2] == 'off' for r in rig.releases if r[0] != 'q1' or kind == 'L6'):
            problems.append(f'a release is off: {rig.releases}')
        guess = predict(sc.roads, order, 0, lambda r: rig.override.get(r.label, r.beh))
        rig.run_to_end(third)
        rig.said = guess
        text, ends = delivered(rig, third), ending(rig, third)
        if guess and guess[0] == 'win' and guess[3] <= bounds(sc)[1] - 2:
            label, full = guess[1], guess[2]
            owner = next(r for r in sc.roads if r.label == label)
            pieces = pieces_of(WORDS[sc.roads.index(owner)], rig.override.get(label, owner.beh))
            if not text or not ''.join(pieces).startswith(text):
                problems.append(f'{third} is not answered by {label} as the model says (first word at {guess[3] / 10:.1f} s): text {text[:40]!r}, order {order}, revived {road.label}')
            elif full and (text != ''.join(pieces) or not ends or ends[-1].kind != 'done'):
                problems.append(f'{third} is not answered whole by {label}: text {text[:40]!r}, endings {[e.kind for e in ends]}')
        rig.counted = bool(guess and guess[0] == 'win' and guess[3] <= bounds(sc)[1] - 2)
    except AssertionError as error:
        problems.append(str(error))
    finally:
        rig.finish()
        problems += l4(Run(sc, rig))
        _clear()
    return sc, rig, problems


def side_check(kind):
    failed, counted = [], 0
    for seed in range(SIDE):
        if os.environ.get('LOCK_SEED') and int(os.environ['LOCK_SEED']) != seed:
            continue
        sc, rig, problems = sequence(seed, kind)
        counted += getattr(rig, 'counted', False)
        if problems:
            failed.append((seed, problems, f'{describe(sc)}\n  releases={rig.releases}\n  asks={[(label, at / 10) for label, at in rig.scene.asks]}\n  events=[{"; ".join(map(str, rig.events))}]\n  repeat: LOCK_SEED={seed} python -m pytest tests/test_roads_lock.py -k {kind}_'))
    if failed:
        shown = '\n'.join(f'- seed {seed}: {"; ".join(problems)}\n  {journal_}' for seed, problems, journal_ in failed[:3])
        pytest.fail(f'{kind}: {len(failed)} of {SIDE} scenarios break it, seeds {[seed for seed, _, _ in failed]}:\n{shown}', pytrace=False)
    return counted


def test_L5_a_retry_does_not_drive_the_roads_and_a_new_question_is_answered():
    counted = side_check('L5')
    assert counted >= SIDE * 0.3 or os.environ.get('LOCK_SEED'), f'the model asserts the answer of the new question in only {counted} of {SIDE} scenarios'


def test_L6_a_rest_is_an_order_not_a_ban():
    counted = side_check('L6')
    assert counted >= SIDE * 0.3 or os.environ.get('LOCK_SEED'), f'the model asserts the answer of the third question in only {counted} of {SIDE} scenarios'


@pytest.mark.skipif(not os.environ.get('LOCK_SEED'), reason='LOCK_SEED=<seed> repeats one scenario of the lock')
def test_one_seed():
    seed = int(os.environ['LOCK_SEED'])
    run = run_main(seed)
    print(journal(run))
    problems = [f'{name}: {p}' for name, rule in (('L1', l1), ('L2', l2), ('L3', l3), ('L4', l4)) for p in rule(run)]
    assert not problems, '\n'.join(problems) + '\n' + journal(run)
