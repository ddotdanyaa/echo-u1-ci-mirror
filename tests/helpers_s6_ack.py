"""Helpers of tests/test_s6_ack_properties.py (WAVE 2 / S6, axis "ack").

Test code only. Nothing here re-implements the engine: the controller is built with the keyword arguments that
``controlled_host.serve`` passes (read from its source by ``ast``), the profile is ControlledMedia's own default,
and every decision is made by the production ``analyze`` / ``EchoEngine`` / ``ControlledMedia`` /
``NativeMediaSocket``. Fakes exist only at the external boundary: the clock, the GPT-Live helper (provider events are
plain dicts), the lookup, and SAPI synthesis (a function returning silent PCM).
"""
from __future__ import annotations

import ast
import asyncio
import collections
import itertools
import tempfile
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from hypothesis import HealthCheck, Phase, settings
from hypothesis import strategies as st

import echo_sync
from echo_sync.classifier import analyze
from echo_sync.controlled_media import ControlledMedia
from echo_sync.native_media_socket import NativeMediaSocket
from echo_sync.portioner import portions
from echo_sync.settings import resolve
from echo_sync.textutil import norm_words
from helpers_live_line import LiveLine

# --------------------------------------------------------------------------------------------------------------------
# Production wiring
# --------------------------------------------------------------------------------------------------------------------

SESSION = 'native-probe-' + '0' * 32


def _host_call():
    source = (Path(echo_sync.__file__).parent / 'controlled_host.py').read_text(encoding='utf-8')
    calls = [n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Call)
             and getattr(n.func, 'id', None) == 'ControlledMedia']
    assert len(calls) == 1, 'controlled_host.serve must build exactly one ControlledMedia'
    return calls[0]


# What controlled_host.serve passes to ControlledMedia (everything but the session id).
def _host_keywords():
    """A keyword that is a constant, or the name of one constant of the one table of time (timer_policy: COALESCE_SECONDS ...) the host imports by name; the rest the host reads off the profile."""
    from echo_sync import timer_policy
    out = {}
    for k in _host_call().keywords:
        if isinstance(k.value, ast.Constant):
            out[k.arg] = k.value.value
        elif isinstance(k.value, ast.Name) and hasattr(timer_policy, k.value.id):
            out[k.arg] = getattr(timer_policy, k.value.id)
    return out


HOST_KWARGS = _host_keywords()
HOST_PASSES_SETTINGS = any(k.arg == 'settings' for k in _host_call().keywords)


def _default_profile():
    from echo_sync.controlled_host import controller_settings
    from echo_sync.settings import resolve
    return controller_settings(resolve(None))


# The profile production runs with on a profile left at its defaults: serve() builds it with controlled_host.controller_settings (ROOT-1).
PROD_SETTINGS = _default_profile()
MODES = {'ru_aligned': PROD_SETTINGS}
CFG = resolve(PROD_SETTINGS)
FILLERS = frozenset(CFG['fillers'])

CASES = collections.Counter()   # generated cases per property, asserted by the last test of the module


def properties(max_examples, *, defect=False, shared_state=False):
    """Hypothesis profile: deterministic, no example database, no deadline.

    ``defect``: the test is an expected failure. Run the explicit minimal reproduction first, then generate; do not
    spend time shrinking (the minimal case is the explicit example).
    ``shared_state``: the examples run against one live dictation (Walker), so a failing example cannot be replayed on
    the same state: report the first failure as it is, without shrinking.
    """
    phases = (Phase.explicit, Phase.generate) if (defect or shared_state) \
        else (Phase.explicit, Phase.generate, Phase.shrink)
    checks = [HealthCheck.too_slow, HealthCheck.data_too_large, HealthCheck.filter_too_much]
    return settings(max_examples=max_examples, derandomize=True, database=None, deadline=None, phases=phases,
                    suppress_health_check=checks, print_blob=False)


# --------------------------------------------------------------------------------------------------------------------
# Provider events and decision-level helpers
# --------------------------------------------------------------------------------------------------------------------

def created(tid, role, text=''):
    return {'type': 'turn.created', 'turn': {'id': tid, 'role': role, 'transcript': text}}


def done(tid, role, text):
    return {'type': 'turn.done', 'turn': {'id': tid, 'role': role, 'transcript': text}}


def waiting(portion, *following):
    """The engine's stored state while ``portion`` waits for the user's repeat (same shape EchoEngine persists)."""
    chunks = [portion, *(following or ('Следующая порция ответа.',))]
    return {'schema': 2, 'revision': 1, 'question': 'q', 'answer': ' '.join(chunks), 'chunks': chunks,
            'chunk_index': 0, 'completed': False, 'pending_turn': None, 'history': []}


def verdict(heard, portion, settings=None):
    return analyze(heard, waiting(portion), [], PROD_SETTINGS if settings is None else settings)


def describe(heard, portion, decision):
    return f'heard={heard!r} portion={portion!r} -> {decision.kind}/{decision.reason}'


# --------------------------------------------------------------------------------------------------------------------
# A realistic corpus. Portions come from the production portioner with the production profile.
# --------------------------------------------------------------------------------------------------------------------

ANSWERS = (
    'Инерция — это свойство тела сохранять своё состояние движения или покоя. Чем больше масса у тела, тем сильнее проявляется его инерция.',
    'Великая Отечественная война началась 22 июня 1941 года.',
    'В Солнечной системе 8 планет, не считая карликовых.',
    'Вода кипит при 100 градусах Цельсия при нормальном атмосферном давлении.',
    'Кит не рыба, а млекопитающее, которое дышит лёгкими.',
    'Ставка налога на доходы физических лиц составляет 13 процентов.',
    'Свет не нуждается в среде для распространения и движется со скоростью около 300 000 километров в секунду.',
    'Эверест имеет высоту 8849 метров над уровнем моря.',
    'Нельзя делить на ноль, потому что результат не определён.',
    'Ни одно тело с массой не может двигаться быстрее света.',
    'Как правило, вода замерзает при нуле градусов.',
    'Когда температура падает, водяной пар конденсируется в капли.',
    'Известно, что Земля вращается вокруг Солнца за 365 суток.',
    'Что-то вроде электронной почты используют многие компании.',
    'Интернет-магазин принимает заказы круглосуточно, по-новому оформляя доставку.',
    'Электроэнцефалограмма регистрирует электрическую активность мозга.',
    'Хорошо проводит тепло медь, а дерево проводит его плохо.',
    'Так называемый парниковый эффект удерживает тепло у поверхности планеты.',
    'Вот почему зимой на улице холоднее, чем летом.',
    'Александр Сергеевич Пушкин родился в 1799 году в Москве.',
    'Масса Юпитера больше массы Земли примерно в 318 раз.',
    'Число пи примерно равно 3,14.',
    'В часе 60 минут, а в минуте 60 секунд.',
    'Площадь России составляет более 17 миллионов квадратных километров.',
    'Население Москвы превышает 13 миллионов человек.',
    'Закон сохранения энергии гласит, что энергия не возникает из ничего и не исчезает бесследно.',
    'ВВП измеряет стоимость всех товаров и услуг, произведённых в стране за год.',
    'Фотосинтез — это процесс образования органических веществ из углекислого газа и воды на свету.',
    'Сила тяжести на Луне примерно в шесть раз меньше, чем на Земле.',
    'Статья 228 Уголовного кодекса устанавливает ответственность за незаконный оборот наркотиков.',
    'Скорость звука в воздухе составляет около 340 метров в секунду.',
    'Давление измеряется в паскалях, а температура — в градусах.',
    'Никто не знает точно, сколько звёзд во Вселенной.',
    'Атом состоит из ядра и электронов, которые движутся вокруг него.',
    'Первый закон Ньютона утверждает, что тело сохраняет скорость, пока на него не действует сила.',
    'Второй закон Ньютона связывает силу, массу и ускорение.',
    'Температура человеческого тела в норме около 36,6 градуса.',
    'На Земле примерно 71 процент поверхности покрыт водой.',
    'Москва находится в центральной части России на реке Москве.',
    'Вторая мировая война продолжалась с 1939 по 1945 год.',
    'Кислорода в воздухе около 21 процента, а азота около 78 процентов.',
    'Лёд легче воды, поэтому он не тонет.',
    'Все планеты вращаются вокруг Солнца в одном направлении.',
    'Для этого нужно не менее трёх свидетелей.',
    'Гражданин вправе обжаловать решение в течение 30 дней.',
    'Он не только учёный, но и преподаватель.',
    'Полупроводник проводит ток лучше изолятора, но хуже металла.',
    'Да, это правильно, но есть исключение.',
    'Нет, это неверно.',
    'Температура плавления железа составляет 1538 градусов Цельсия.',
    'Первая космическая скорость равна примерно 7,9 километра в секунду.',
)


# Longer answers (two sentences each) so that one live dictation survives many property examples.
LONG_ANSWERS = tuple(' '.join(ANSWERS[i:i + 2]) for i in range(0, 20, 2))
# Consecutive portions with the same text: a duplicate delivery is observable only here, because with ordinary
# answers the next portion differs and "the text of the old portion" cannot advance anything anyway.
SAME_PORTIONS_ANSWER = 'Раз, два, три. Раз, два, три. Раз, два, три. Раз, два, три.'


def _words(text):
    return norm_words(text)


def corpus_portions():
    seen, out = set(), []
    for answer in ANSWERS:
        for portion in portions(answer, CFG):
            if portion not in seen:
                seen.add(portion)
                out.append(portion)
    return tuple(out)


PORTIONS = corpus_portions()


def only_fillers(portion):
    return all(word in FILLERS for word in _words(portion))


CONTENT_PORTIONS = tuple(p for p in PORTIONS if not only_fillers(p))
NUMERIC_PORTIONS = tuple(p for p in CONTENT_PORTIONS if any(ch.isdigit() for ch in p))
NEGATED_PORTIONS = tuple(p for p in CONTENT_PORTIONS if {'не', 'ни'} & set(_words(p)))
HYPHEN_PORTIONS = tuple(p for p in CONTENT_PORTIONS if any('-' in w for w in p.split()))


def content_words(portion):
    """Words that carry meaning: not a filler, not shorter than 3 letters (the classifier's own notion, restated)."""
    return [w for w in _words(portion) if len(w) >= 3 and w not in FILLERS]


# --------------------------------------------------------------------------------------------------------------------
# Spoken Russian numbers (oracle for "digits vs number words"; independent of the production tables)
# --------------------------------------------------------------------------------------------------------------------

_ONES = ('ноль один два три четыре пять шесть семь восемь девять десять одиннадцать двенадцать тринадцать '
         'четырнадцать пятнадцать шестнадцать семнадцать восемнадцать девятнадцать').split()
_TENS = {2: 'двадцать', 3: 'тридцать', 4: 'сорок', 5: 'пятьдесят', 6: 'шестьдесят', 7: 'семьдесят', 8: 'восемьдесят',
         9: 'девяносто'}
_HUNDREDS = {1: 'сто', 2: 'двести', 3: 'триста', 4: 'четыреста', 5: 'пятьсот', 6: 'шестьсот', 7: 'семьсот',
             8: 'восемьсот', 9: 'девятьсот'}


def cardinal(n):
    """0..999 in the nominative."""
    assert 0 <= n < 1000
    if n < 20:
        return _ONES[n]
    if n < 100:
        return _TENS[n // 10] + ('' if n % 10 == 0 else ' ' + _ONES[n % 10])
    return _HUNDREDS[n // 100] + ('' if n % 100 == 0 else ' ' + cardinal(n % 100))


def _feminine(words):
    head, _, last = words.rpartition(' ')
    last = {'один': 'одна', 'два': 'две'}.get(last, last)
    return (head + ' ' + last).strip()


def cardinal_big(n):
    """1000..999999 in the nominative, the way it is said: «две тысячи пятьсот», «тысяча девятьсот»."""
    assert 1000 <= n < 10 ** 6
    k, rest = divmod(n, 1000)
    if k % 100 in range(11, 15):
        unit = 'тысяч'
    elif k % 10 == 1:
        unit = 'тысяча'
    elif k % 10 in (2, 3, 4):
        unit = 'тысячи'
    else:
        unit = 'тысяч'
    head = 'тысяча' if k == 1 else _feminine(cardinal(k)) + ' ' + unit
    return head + ('' if rest == 0 else ' ' + cardinal(rest))


_ORD_PREP = {1: 'первом', 2: 'втором', 3: 'третьем', 4: 'четвёртом', 5: 'пятом', 6: 'шестом', 7: 'седьмом', 8: 'восьмом',
             9: 'девятом', 10: 'десятом', 11: 'одиннадцатом', 12: 'двенадцатом', 13: 'тринадцатом', 14: 'четырнадцатом',
             15: 'пятнадцатом', 16: 'шестнадцатом', 17: 'семнадцатом', 18: 'восемнадцатом', 19: 'девятнадцатом',
             20: 'двадцатом', 30: 'тридцатом', 40: 'сороковом', 50: 'пятидесятом', 60: 'шестидесятом',
             70: 'семидесятом', 80: 'восьмидесятом', 90: 'девяностом'}


def year_in_year(year):
    """«в 1945 году» as it is spoken: «в тысяча девятьсот сорок пятом году» (1001..2099, last two digits not 00)."""
    assert 1001 <= year <= 2099 and year % 100
    thousands, rest = divmod(year, 1000)
    hundreds, last = divmod(rest, 100)
    head = 'тысяча' if thousands == 1 else 'две тысячи'
    if hundreds:
        head += ' ' + _HUNDREDS[hundreds]
    if last in _ORD_PREP:
        tail = _ORD_PREP[last]
    else:
        tail = _TENS[last // 10] + ' ' + _ORD_PREP[last % 10]
    return f'в {head} {tail} году'


# --------------------------------------------------------------------------------------------------------------------
# ASR-like surface noise: the same words, rendered differently. Deterministic given a Style (so @example works).
# --------------------------------------------------------------------------------------------------------------------

CASE_FUNCTIONS = {'keep': lambda s: s, 'lower': str.lower, 'upper': str.upper, 'capitalize': str.capitalize,
                  'title': str.title}
UNICODE_FORMS = ('NFC', 'NFD')           # composition forms an ASR/OS may emit (compatibility forms would turn «…» into «...»)
# Separators between two words; the tolerated punctuation of the matcher plus every kind of space an ASR emits.
SEPARATORS = (' ', ', ', '. ', '! ', '? ', '; ', ': ', ' … ', '  ', '\u00a0', '\u202f', '\u2009', '\t', '\n', ' — ', ' – ')
LEADS = ('', '«', '"', "'", ', ', '. ')
TRAILS = ('', '.', '!', '?', ',', '…', ';', ':', '»', '"', '.»')


@dataclass(frozen=True)
class Style:
    case: str = 'keep'
    yo: bool = False                    # ё -> е, the usual ASR output
    form: str = 'NFC'
    seps: tuple = (' ',)
    lead: str = ''
    trail: str = ''


PLAIN = Style()
styles = st.builds(
    Style,
    case=st.sampled_from(tuple(CASE_FUNCTIONS)), yo=st.booleans(), form=st.sampled_from(UNICODE_FORMS),
    seps=st.lists(st.sampled_from(SEPARATORS), min_size=1, max_size=4).map(tuple),
    lead=st.sampled_from(LEADS), trail=st.sampled_from(TRAILS))


def _plain_word(word):
    return len(word) >= 2 and word.isalpha()


_EDGE_MARKS = '.,!?;:…«»"\'—–-'


def plain_words(text):
    """The words of ``text`` without edge punctuation and without bare punctuation tokens."""
    return [w for w in (w.strip(_EDGE_MARKS) for w in text.split()) if w]


def apply_style(style, text):
    """Render ``text`` as ``style`` says: the portion's own edge punctuation is replaced by the style's.

    Dashes only between two real words; only plain spaces next to a digit token; no adjacent punctuation marks
    (a run such as «..» or «?!» is a different tokenisation and is exercised by its own defect test).
    """
    words = plain_words(text)
    pieces = []
    for i, word in enumerate(words):
        pieces.append(word)
        if i + 1 == len(words):
            break
        sep = style.seps[i % len(style.seps)]
        nxt = words[i + 1]
        if sep.strip() in ('—', '–') and not (_plain_word(word) and _plain_word(nxt)):
            sep = ' '
        if (any(ch.isdigit() for ch in word) or any(ch.isdigit() for ch in nxt)) and sep.strip():
            sep = ' '
        pieces.append(sep)
    out = style.lead + ''.join(pieces) + style.trail
    out = CASE_FUNCTIONS[style.case](out)
    if style.yo:
        out = out.replace('ё', 'е').replace('Ё', 'Е')
    return unicodedata.normalize(style.form, out)


# --------------------------------------------------------------------------------------------------------------------
# Dispatch-level harness: ControlledMedia as the host builds it, driven with provider events
# --------------------------------------------------------------------------------------------------------------------

class FakeClock:
    def __init__(self, start=1000.0):
        self.now = float(start)

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds
        return self.now


MODEL_ACTIONS = frozenset({'lookup', 'context', 'route'})
DICTATION_KILLERS = frozenset({'cancel', 'lookup', 'context', 'route'})


@dataclass
class Outcome:
    actions: list
    before: int
    after: int
    completed: bool
    generate_calls: int

    @property
    def types(self):
        return [a['type'] for a in self.actions]

    @property
    def speaks(self):
        return [a['text'] for a in self.actions if a['type'] == 'speak']

    @property
    def model_calls(self):
        return self.generate_calls + sum(a['type'] in MODEL_ACTIONS for a in self.actions)

    @property
    def destroyed(self):
        """The answer was dropped or a new question started: cancel / lookup / context / route."""
        return any(t in DICTATION_KILLERS for t in self.types)


class Dictation:
    """One question and one final assistant answer, replayed through ControlledMedia built as the host builds it."""

    QUESTION = 'Расскажи подробнее'

    def __init__(self, directory, answer, *, question=None, settings=None, clock=None, play_first=True, **controller_kwargs):
        """``play_first=False`` leaves the first cue "in flight": issued, not yet reported finished by the transport.
        ``controller_kwargs``: more keywords of ControlledMedia."""
        Path(directory).mkdir(parents=True, exist_ok=True)
        self.directory = Path(directory)
        self.clock = clock or FakeClock()
        kwargs = dict(HOST_KWARGS)
        kwargs.update(controller_kwargs)
        self.controller_kwargs = controller_kwargs
        if settings is not None:
            kwargs['settings'] = settings
        self.controller = c = ControlledMedia(Path(directory) / 'controlled-state.sqlite3', session_id=SESSION,
                                              clock=self.clock, **kwargs)
        c.engine.clock = self.clock       # the engine's own time source (echo guard) follows the injected clock
        LiveLine(c, self.clock()).attach()      # the phone streams its microphone all call long: every tick reads a live line (helpers_live_line)
        self._ids = itertools.count(1)
        self.generate_calls = 0
        generate = c.engine.generate

        def counted(*args):
            self.generate_calls += 1
            return generate(*args)

        c.engine.generate = counted
        self.cues = []
        self.answer = answer
        if answer is None:        # a new connection to a session that already exists (reconnect): no question, no answer
            return
        c.speech_started()
        c.provider(created('q1', 'user', ''))
        question_actions = c.provider(done('q1', 'user', question or self.QUESTION))
        assert [a['type'] for a in question_actions] == ['cancel', 'route'], question_actions
        answer_actions = c.provider(done('a1', 'assistant', answer))
        assert any(a['type'] == 'speak' for a in answer_actions), f'no first cue for {answer!r}: {answer_actions}'
        if play_first:
            self.play(answer_actions)
        else:
            self.cues.extend(a for a in answer_actions if a['type'] == 'speak')

    def reconnect(self):
        """A new ControlledMedia over the same session database, built as the host builds it (new nonce, empty ledger)."""
        return Dictation(self.directory, None, clock=self.clock, **self.controller_kwargs)

    # -- the state --------------------------------------------------------------------------------------------------
    @property
    def state(self):
        return self.controller.state() or {}

    @property
    def index(self):
        return self.state.get('chunk_index', 0)

    @property
    def chunks(self):
        return list(self.state.get('chunks') or [])

    @property
    def completed(self):
        return bool(self.state.get('completed'))

    @property
    def current(self):
        return self.chunks[self.index] if self.chunks and self.index < len(self.chunks) else None

    @property
    def remaining(self):
        return 0 if self.completed else len(self.chunks) - self.index

    # -- the transport ----------------------------------------------------------------------------------------------
    def play(self, actions, seconds=0.6):
        """What NativeMediaSocket does after it has streamed a cue: report the (estimated) end of playback."""
        for action in actions:
            if action['type'] == 'speak':
                self.cues.append(action)
                self.clock.advance(seconds)
                self.controller.playback_done(action, now=self.clock())

    def say(self, text, *, gap=4.0, hold=0.0, tid=None, play=True):
        """One user utterance as NativeMediaSocket.provider feeds it: speech start, turn.created, turn.done."""
        c = self.controller
        tid = tid or f'u{next(self._ids)}'
        self.clock.advance(gap)
        before, calls = self.index, self.generate_calls
        c.speech_started()
        c.provider(created(tid, 'user', ''))
        if hold:
            self.clock.advance(hold)
        actions = c.provider(done(tid, 'user', text))
        if play:
            self.play(actions)
        return Outcome(actions, before, self.index, self.completed, self.generate_calls - calls)

    def deliver(self, event):
        """Hand one raw provider event to the controller (duplicates, retransmits)."""
        before, calls = self.index, self.generate_calls
        actions = self.controller.provider(event)
        return Outcome(actions, before, self.index, self.completed, self.generate_calls - calls)


class Walker:
    """Keeps one live Dictation across many property examples; starts the next answer when it runs out.

    Only for invariants whose effect is a known cursor move (accept: +1) or none (reject): a violation of either shows
    up at the example that causes it, so sharing one dictation between examples cannot hide a defect.
    """

    def __init__(self, base, answers, **kwargs):
        self.base, self.kwargs = Path(base), kwargs
        self.answers = tuple(answers)
        self.count = 0
        self.live = None

    def dictation(self, remaining=2):
        while self.live is None or self.live.remaining < remaining:
            answer = self.answers[self.count % len(self.answers)]
            self.live = Dictation(self.base / f'walk{self.count}', answer, **self.kwargs)
            self.count += 1
        return self.live


# --------------------------------------------------------------------------------------------------------------------
# Wire-level harness: NativeMediaSocket over ControlledMedia, fakes at the boundary only
# --------------------------------------------------------------------------------------------------------------------

class FakeSource:
    def __init__(self):
        self.frames = []

    async def send(self, kind, payload=b''):
        self.frames.append((kind, payload))

    async def close(self):
        pass


class Wire:
    """Run inside one running event loop. ``skew`` moves the transport clock forward (time that passes without waiting)."""

    def __init__(self, directory, *, pcm_ms=60, synth_delay=0.0, **controller_kwargs):
        Path(directory).mkdir(parents=True, exist_ok=True)
        self.sent, self.synthesized, self.skew, self.frozen = [], [], 0.0, None
        self.clock = lambda: (time.monotonic() if self.frozen is None else self.frozen) + self.skew
        self.controller = ControlledMedia(Path(directory) / 'controlled-state.sqlite3', session_id=SESSION,
                                          clock=self.clock, **{**HOST_KWARGS, **controller_kwargs})
        self.controller.engine.clock = self.clock
        LiveLine(self.controller, self.clock()).attach()      # the phone streams its microphone all call long: every tick reads a live line (helpers_live_line)
        self._ids = itertools.count(1)
        pcm = bytes(48 * pcm_ms)           # 24 kHz mono 16-bit silence, 48 bytes per millisecond

        async def emit(frame):
            self.sent.append(frame)

        async def connect():
            return FakeSource()

        async def lookup(question):
            return []

        async def synthesize(text, end=None):
            self.synthesized.append(text)
            if synth_delay:
                await asyncio.sleep(synth_delay)
            return pcm

        self.socket = NativeMediaSocket(self.controller, emit, connect, lookup, synthesize, clock=self.clock)
        self.socket.ready, self.socket.source = True, FakeSource()

    # -- feeding ----------------------------------------------------------------------------------------------------
    async def begin(self, answer, question=Dictation.QUESTION, *, settle=True):
        await self.socket.provider(created('q1', 'user', ''))
        await self.socket.provider(done('q1', 'user', question))
        await self.socket.provider(done('a1', 'assistant', answer))
        if settle:
            await self.settle()

    async def user(self, text, tid=None, *, pair=True, reaction=4.0):
        """One user utterance; ``reaction`` seconds of (transport) time pass first, as a person needs time to answer."""
        tid = tid or f'u{next(self._ids)}'
        self.skew += reaction
        if pair:
            await self.socket.provider(created(tid, 'user', ''))
        await self.socket.provider(done(tid, 'user', text))
        await self.settle()
        return tid

    async def settle(self, timeout=3.0):
        deadline = time.monotonic() + timeout
        while self.socket.tasks and time.monotonic() < deadline:
            await asyncio.sleep(0.01)

    async def elapse(self, seconds):
        """Let ``seconds`` of transport time pass without waiting, then run the transport's periodic tick."""
        self.skew += seconds
        await self.socket.tick()
        await self.settle()

    def freeze(self, at=None):
        """The transport's clock stands at ``at`` (default: now) and moves only by ``skew`` from here on. What a test says about the time between two
        events then holds however long the machine took between them. The PCM is still paced in real time."""
        self.frozen = (self.clock() if at is None else at) - self.skew

    # -- observing --------------------------------------------------------------------------------------------------
    @property
    def index(self):
        return (self.controller.state() or {}).get('chunk_index', 0)

    @property
    def chunks(self):
        return list((self.controller.state() or {}).get('chunks') or [])

    @property
    def audio_frames(self):
        return sum(1 for f in self.sent if f.get('type') == 'response.audio.delta')

    def cleared(self):
        return sum(1 for f in self.sent if f.get('type') == 'output_audio_buffer.clear')

    async def close(self):
        await self.socket.close()
