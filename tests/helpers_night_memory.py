"""The stand of the conversation memory (night 12-13.11): ONE whole call through the real chain, wired as ``controlled_host.serve`` wires it.

REAL, the same code as production: ControlledMedia (built by ``helpers_s6_state.World`` with the keywords read from controlled_host.py, its settings made by
``controlled_host.controller_settings`` from the profile), NativeMediaSocket, FramelessTurns and its sink into the ConversationLedger, the X-CUE source, the engine and its SQLite file,
``fast_text.for_call`` (FastText and its job threads), ``v6_memory.attach`` hooked the way the host hooks it (``wire.fast.card = v6.apply``), CallTrace (the call journal, a real file),
``controller.begin_call()`` after the wiring, as the host calls it.
SCRIPTED, only at the boundary: the provider's turn events (what the cloud heard), the phone, the synthesis, and the text model: ``mind(request)`` answers from WHAT THE REQUEST HOLDS and nothing
else, so a prompt can be right only when the memory is in the request.
CLOCKS, as in production: the controller's clock is monotonic (here the world's fake clock, 1000.0 at its start), the engine's clock is the wall clock (here ``WALL`` + the fake clock, so the
windows the engine counts by its own clock pass with the call; World leaves it at the real ``time.time``, which stands still while a three-hour call is played in seconds).
Nothing here is a measurement of the laptop or the phone: the times it reports are of this machine."""
import json
import random
import re
import threading
import time
from pathlib import Path

import helpers_s6_state as S
from echo_sync import fast_text as FT
from echo_sync import v6_memory as V
from echo_sync.call_trace import CallTrace
from echo_sync.controlled_host import controller_settings
from echo_sync.settings import resolve
from echo_sync.textutil import normalize
from test_h1_fast_text import FakeEar

WALL = 1_794_000_000.0                 # the engine's clock is the wall clock: seconds of the epoch, far from the controller's monotonic seconds
POLICY = 'POLICY'
MEMORY = {'fast_text': 'on', 'conversation_ledger': 'memory', 'topic_recap': 'on'}      # the set of the task

VOCAB = ('погода кофе прогулка дорога фильм музыка вечер сосед собака велосипед завтрак озеро поезд гитара ветер мост лес сад окно книга чай река гора поле город дождь снег лето осень '
         'зима весна кино театр рынок площадь улица двор крыша лестница').split()

# what is said in the call (the minute of each is in ``Call.plant``)
OPENING = 'Добрый день, давайте обсудим поставку оборудования для склада в Казани.'
COND = 'Условие такое: скидка пять процентов, только если заказ больше трёхсот единиц.'
PRICE_OLD = 'Цена за штуку 500 рублей.'
PRICE_FIX = 'Нет, не 500, а 700 рублей за штуку.'
PAY_MISHEARD = 'Срок оплаты 90 дней после отгрузки.'      # the first final of the turn
PAY = 'Срок оплаты 30 дней после отгрузки.'               # the refined final of the same turn
SHIP_OLD = 'Доставка займёт пятнадцать дней.'
SHIP_FIX = 'Нет, не пятнадцать, а пятьдесят дней.'
Q_WARRANTY = 'Какой у вас гарантийный срок на оборудование?'
A_WARRANTY = 'Гарантия 24 месяца с даты поставки. Она покрывает замену любых узлов.'
Q_COND = 'Какая скидка по условию про заказ?'
Q_PRICE = 'Какая цена за штуку?'
Q_PAY = 'Какой срок оплаты после отгрузки?'
Q_SHIP = 'Сколько дней займёт доставка?'
Q_OURS = 'Какую гарантию на оборудование мы называли?'
UNKNOWN = 'В разговоре этого не было.'
Q_EARLIER = 'Что такое инерция?'      # the earlier call (``earlier_call``)
A_EARLIER = 'Инерция — это свойство тела сохранять своё состояние движения или покоя.'


def asked(request):
    """What the job was asked: the last user message, without the answer in play."""
    return request['input'][-1]['content'][0]['text'].rsplit('Сейчас прозвучало: ', 1)[-1]


def memory_of(request):
    """What stands in the instructions after the policy: the old blocks (off, shadow) or the card (on)."""
    return request['instructions'][len(POLICY):].lstrip('\n')


def whole(request):
    return request['instructions'] + '\n' + '\n'.join(part['text'] for message in request['input'] for part in message['content'])


def lines_with(request, needle):
    return [line for line in whole(request).split('\n') if needle in line]


ROOM = re.compile(r'^(?:- (?:\d+ ч )?\d+ мин, ' + re.escape(V.SPEAKER) + r': «(?P<line>.*)»|Прозвучало без ответа: (?P<un>.*)|Вопрос: (?P<q>.*))')


def room_lines(request):
    """The lines of the request that are told as said in the room (by somebody the microphone heard, not by the prompter): ``[text]``."""
    out = []
    for line in request['instructions'].split('\n'):
        m = ROOM.match(line)
        if m:
            out.append(next(g for g in m.groups() if g is not None))
    return out


def mind(request):
    """The text model of the stand: it answers a question about the call from the request alone."""
    q, seen = asked(request), memory_of(request)
    m = re.search(r'партии (\d+)\?$', q)
    if m:
        n = int(m.group(1))
        return 'Срок поставки партии %d — %d дней. Отгрузка партии %d идёт со склада номер %d.' % (n, 10 + n % 7, n, 1 + n % 5)
    if q.endswith(Q_EARLIER):
        return A_EARLIER
    if q.endswith(Q_WARRANTY):
        return A_WARRANTY
    if q.endswith(Q_COND):
        return 'Скидка пять процентов, если заказ больше трёхсот единиц.' if 'пять процентов' in seen and 'трёхсот' in seen else UNKNOWN
    if q.endswith(Q_PRICE):
        said = re.findall(r'(\d+) рублей', seen)
        return 'Цена %s рублей за штуку.' % said[-1] if said else UNKNOWN
    if q.endswith(Q_PAY):
        said = re.findall(r'оплаты (\d+) дней', seen)
        return 'Оплата через %s дней после отгрузки.' % said[-1] if said else UNKNOWN      # not the words of the room's own line: what the owner says back must be told apart from what the room said
    if q.endswith(Q_SHIP):
        return 'Доставка займёт пятьдесят дней.' if 'пятьдесят' in seen else UNKNOWN
    if q.endswith(Q_OURS):
        return 'Мы называли гарантию 24 месяца.' if '24 месяца' in seen else UNKNOWN
    return '—'


class Threads:
    """``fast_text.threading`` of the stand: real threads, each job thread kept so that the stand waits for it instead of sleeping (tools/replay/stand.py does the same)."""
    Event, Lock = threading.Event, threading.Lock

    def __init__(self):
        self.jobs = []

    def Thread(self, target, args=(), name=None, daemon=None):      # noqa: N802 - the name of threading's
        thread = threading.Thread(target=target, args=args, name=name, daemon=True)
        if args and hasattr(args[0], 'request'):
            self.jobs.append(thread)
        return thread


class Call:
    def __init__(self, tmp_path, mind=mind, seed=7, **profile):
        self.profile = resolve({**MEMORY, **profile})
        self.mind, self.rng, self.root = mind, random.Random(seed), Path(tmp_path)
        self._original = S.host_kwargs, FT.threading
        original, host = S.host_kwargs, {'settings': controller_settings(self.profile), 'fast_text': self.profile['fast_text'],
                                         'repeat_seconds': self.profile['repeat_seconds'], 'max_auto_repeats': self.profile['max_auto_repeats']}
        S.host_kwargs = lambda: {**original(), **host}
        self.threads = FT.threading = Threads()
        # (call, minute, request); (call, minute, question, what the hook left after the policy, the history it left); (call, minute, seconds in the hook); (call, minute, seconds from a final to its request)
        self.requests, self.cards, self.hook_s, self.first_s = [], [], [], []
        self.said_back, self.traces, self.n, self.calls, self._followed, self._fed = [], [], 0, 0, set(), None
        self.w = S.World(self.root / 'state')
        self.attach()

    # -- the wiring of controlled_host.serve ------------------------------------------------------------------------------------------
    def attach(self):
        w = self.w
        self.c = c = w.controller
        c.engine.clock = lambda: WALL + w.clock.now()
        self.calls += 1
        self.trace = CallTrace(self.root / 'echo_calls', 'night%d' % self.calls, clock=w.clock.now, facts=True,
                               mic_gap_ms=self.profile['mic_gap_ms'], mic_ring_s=self.profile['mic_ring_s'])
        self.traces.append(self.trace)
        c.facts_why = w.wire.facts_why = True
        self.fast = FT.for_call(self.profile, c, stream=self.stream, instructions=lambda *a: POLICY, wake=lambda: None, clock=w.clock.now, report=self.trace.note)
        w.wire.fast, w.wire.ear = self.fast, FakeEar()
        self.v6 = V.attach(self.profile, c, note=self.trace.note, pinned=lambda: ())
        if self.fast is not None and self.v6 is not None:
            apply = self.v6.apply

            def timed(fast, text, instructions, history):
                began = time.perf_counter()
                out = apply(fast, text, instructions, history)
                self.hook_s.append((self.calls, self.minute(), time.perf_counter() - began))
                self.cards.append((self.calls, self.minute(), text, out[0][len(POLICY):].lstrip('\n'), list(out[1])))
                return out
            self.fast.card = timed
        self.trace.open(source='stand')
        self.zero = w.clock.now()
        c.begin_call()

    def stream(self, request, cancelled):
        if self._fed is not None:
            self.first_s.append((self.calls, self.minute(), time.perf_counter() - self._fed))
            self._fed = None
        self.requests.append((self.calls, self.minute(), request))
        text = self.mind(request)

        def run():
            if text:
                yield text
        return run()

    # -- time -------------------------------------------------------------------------------------------------------------------------
    def minute(self):
        return (self.w.clock.now() - self.zero) / 60.0

    def jobs_done(self):
        while self.threads.jobs:
            self.threads.jobs.pop().join(5)

    def pump(self, seconds=0.3, step=0.1):
        self.jobs_done()
        self.w.advance(seconds, step=step)
        self.jobs_done()

    def go(self, minute):
        """Silence until ``minute`` of the call (the host ticks every 0.1 s; here every second)."""
        left = minute * 60.0 - (self.w.clock.now() - self.zero)
        if left > 0:
            self.pump(left, 1.0)

    # -- what is said -----------------------------------------------------------------------------------------------------------------
    def say(self, text, uid=None):
        """Somebody is heard: the cloud's turn of these words, its final at once."""
        self.n += 1
        uid = uid or 'u%d' % self.n
        self.w.feed(S.turn_created(uid, 'user', text.split()[0]))
        self._fed = time.perf_counter()
        self.w.feed(S.turn_done(uid, 'user', text))
        self._fed = None
        self.pump()
        return uid

    def refine(self, uid, text):
        """The provider's refined transcript of the same speech: a second, different final of the turn."""
        self.w.feed(S.turn_done(uid, 'user', text))
        self.pump()

    def owner_follows(self, limit=12, quiet_s=10.0):
        """The owner says every portion after hearing it, until the answer is over: no new portion for ``quiet_s`` (the answer is due within 8 s of the question, the portions follow each other within seconds), so the words of one answer never meet the next question."""
        silent = 0.0
        for _ in range(limit):
            while True:
                self.pump(0.6)
                cues = [cue for cue in self.w.cues if not cue.diagnostic]
                if cues and cues[-1].seq not in self._followed:
                    silent = 0.0
                    break
                silent += 0.6
                if silent >= quiet_s:
                    return
            self._followed.add(cues[-1].seq)
            words = S.relaxed(cues[-1].text)
            self.said_back.append(words)
            self.say(words)

    def ask(self, text):
        uid = self.say(text)
        self.owner_follows()
        return uid

    def chatter(self):
        return self.say(' '.join(self.rng.choice(VOCAB) for _ in range(self.rng.randint(5, 9))))

    def traffic(self, until):
        """The call goes on until ``until`` (a minute): something is said every 20-50 s, one time in four a question with an answer of two portions the owner says back."""
        while True:
            gap = self.rng.uniform(20.0, 50.0)
            if self.minute() + gap / 60.0 >= until:
                return self.go(until)
            self.pump(gap, 1.0)
            if self.rng.random() < 0.25:
                self.n_asked = getattr(self, 'n_asked', 0) + 1
                self.ask('Какой срок поставки у партии %d?' % self.n_asked)
            else:
                self.chatter()

    def redial(self, after_s):
        """The line dropped and the phone dialled again ``after_s`` later: a new controller over the same state file, wired again."""
        self.jobs_done()
        self.fast.close()
        self.trace.close()
        self.pump(after_s, 1.0)
        began = self.minute()
        self.w.reconnect()
        self.attach()
        return began

    # -- reading ----------------------------------------------------------------------------------------------------------------------
    def request_for(self, question, after=0.0, call=None):
        """The first request asked ``question`` at or after minute ``after`` of call ``call`` (the last one when None)."""
        call = self.calls if call is None else call
        return next(request for n, minute, request in self.requests if n == call and minute >= after - 1e-6 and asked(request).endswith(question))

    def all_requests(self, call=None):
        call = self.calls if call is None else call
        return [request for n, _, request in self.requests if n == call]

    def cues(self):
        return [cue.text for cue in self.w.cues if not cue.diagnostic]

    def journal(self, last=False):
        """The records of the call journals of this stand, in order (``last``: of the last call only)."""
        out = []
        for trace in (self.traces[-1:] if last else self.traces):
            if trace.path is not None and Path(trace.path).exists():
                out += [json.loads(line) for line in Path(trace.path).read_text(encoding='utf-8').splitlines() if line.strip()]
        return out

    def close(self):
        try:
            self.jobs_done()
            if self.fast is not None:
                self.fast.close()
            self.trace.close()
            self.w.close()
        finally:
            S.host_kwargs, FT.threading = self._original


def plant(call, until=178.0, marks=None):
    """THE call of the stand, up to ``until`` minutes: what is planted and when. ``marks``: {name: minute} of what was asked (filled)."""
    marks = {} if marks is None else marks
    steps = [(1.0, lambda: call.say(OPENING)),
             (5.0, lambda: call.say(COND)),
             (10.0, lambda: call.say(PRICE_OLD)),
             (12.0, lambda: call.say(PRICE_FIX)),
             (15.0, lambda: call.refine(call.say(PAY_MISHEARD), PAY)),
             (18.0, lambda: (call.say(SHIP_OLD), call.pump(8.0, 1.0), call.say(SHIP_FIX))),
             (22.0, lambda: call.ask(Q_WARRANTY)),
             (40.0, lambda: call.ask(Q_COND)), (45.0, lambda: call.ask(Q_PRICE)), (50.0, lambda: call.ask(Q_PAY)), (55.0, lambda: call.ask(Q_SHIP)), (60.0, lambda: call.ask(Q_OURS)),
             (170.0, lambda: call.ask(Q_COND)), (172.0, lambda: call.ask(Q_PRICE)), (174.0, lambda: call.ask(Q_OURS))]
    for minute, step in steps:
        if minute > until:
            break
        if minute >= 25.0:
            call.traffic(minute)
        else:
            call.go(minute)
        marks[minute] = call.minute()
        step()
    call.traffic(until) if until >= 25.0 else call.go(until)
    return marks


def earlier_call(call, gap_min=30.0):
    """What the laptop has before any call of the day: the state file of an EARLIER call (the phone's session id is one constant). One exchange, then the phone dials again ``gap_min`` later:
    ``begin_call`` takes it for a new call."""
    call.ask(Q_EARLIER)
    call.redial(gap_min * 60.0)


def said(text):
    return normalize(text)
