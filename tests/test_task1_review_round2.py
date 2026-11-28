"""Fix round 2 for WAVE 2 / Task 1: what the independent review of bb879e0 found.

Everything here runs the real ControlledMedia built with the production keywords of controlled_host.serve, driven the way the
host drives it: provider events at given seconds and a tick every 0.1 s, on an injected clock. Nothing sleeps, no network,
no TTS, no server. The listener (when there is one) repeats every cue aloud 0.3 s after it was produced.

P1.1  A provider turn.done ends an acoustic SEGMENT, and a segment can stop in the middle of a word («Это назы» | «вается»).
      A word cut in half is never spoken, and the rest of the answer is not lost. A lone complete word at the true end of
      the answer is still spoken: once the grace window passed with no newer segment (Task 2's flush).
P1.2  The next segment of a cut answer is the same answer, whatever the listener said in between (a repeated portion, «угу»):
      the field logs show it arriving 27-47 ms after that user turn. A genuinely new question still retires the old answer.
"""
import pytest

from helpers_live_line import LiveLine
from test_first_cue_never_silent import DEFAULT_SETTINGS, Clock, created, delta, done, host_controller, slices, squeeze

ORIGIN = 100.0


class Session:
    """The production-profile controller on an injected clock. ``at`` schedules provider events; ``until`` advances time in
    0.1 s ticks, feeding the events that are due and ticking after them. ``cues`` is [(seconds, text)]."""

    def __init__(self, tmp_path, *, ack_after=None, ack_skip=0, **overrides):
        self.clock = Clock(ORIGIN)
        self.c = host_controller(tmp_path, clock=self.clock, **overrides)
        self.line = LiveLine(self.c, ORIGIN)      # the phone streams its microphone all call long (helpers_live_line)
        self.ack_after, self.ack_skip = ack_after, ack_skip       # the listener leaves the first ``ack_skip`` cues alone
        self.agenda, self.step, self.order, self.acks, self.cues = [], 0, 0, 0, []

    def at(self, seconds, *events):
        for event in events:
            self.order += 1
            self.agenda.append((seconds, self.order, event))

    def ask(self, question, at=0.0, tid='u1'):
        self.at(at, created(tid, 'user', question.split()[0]), done(tid, 'user', question))

    def whole(self, text, at, tid='a1'):
        """One assistant segment that arrives in one piece."""
        self.at(at, created(tid, 'assistant', text[:3]), done(tid, 'assistant', text))

    def stream(self, text, start, end, tid='a1', how='words'):
        pieces = slices(text, how)
        step = (end - start) / len(pieces)
        self.at(start, created(tid, 'assistant', pieces[0]))
        for n, piece in enumerate(pieces[1:], 1):
            self.at(round(start + n * step, 3), delta(tid, piece, n))
        self.at(end, done(tid, 'assistant', text))

    def until(self, seconds):
        last = int(round(seconds * 10))
        while self.step <= last:
            now = self.step / 10
            self.clock.now = ORIGIN + now
            self.line.run_to(self.clock.now)
            due = sorted(item for item in self.agenda if item[0] <= now + 1e-9)
            self.agenda = [item for item in self.agenda if item[0] > now + 1e-9]
            actions = []
            for _, _, event in due:
                actions += (event(self) or []) if callable(event) else self.c.provider(event)
            actions += self.c.tick(now=self.clock.now)
            for action in actions:
                if action['type'] != 'speak':
                    continue
                self.cues.append((now, action['text']))
                if self.ack_after is not None and len(self.cues) > self.ack_skip:
                    self.acks += 1
                    self.order += 1
                    self.agenda.append((now + self.ack_after, self.order, done(f'ack{self.acks}', 'user', action['text'])))
            self.step += 1

    @property
    def heard(self):
        return squeeze(' '.join(text for _, text in self.cues))

    @property
    def texts(self):
        return [text for _, text in self.cues]

    def state(self):
        return self.c.state() or {}


# --- P1.1: a segment cut inside a word -------------------------------------------------------------------------------

CUT_PAIRS = [  # (id, question, segment 1 (cut), segment 2, what the listener must hear, hand-derived)
    ('it_is_called', 'Как называется переход вещества из твёрдого состояния в газообразное',
     'Это назы', 'вается сублимация.', 'сублимация.'),
    ('definition', 'Что такое инерция', 'Инерция — это свойство тела сохра', 'нять своё состояние движения.',
     'свойство тела сохранять своё состояние движения.'),
    ('single_term', 'Как называется наука о насекомых', 'Энтомо', 'логия.', 'Энтомология.'),
    ('number_in_two', 'С какой скоростью движется свет', 'Около 299', ' 792 километров в секунду.',
     'Около 299 792 километров в секунду.'),
    ('number_and_unit', 'При какой температуре кипит вода', 'При 100', ' градусах Цельсия при нормальном давлении.',
     'При 100 градусах Цельсия при нормальном давлении.'),
    ('date', 'Когда началась Великая Отечественная война', 'Великая Отечественная война началась 22',
     ' июня 1941 года.', 'Великая Отечественная война началась 22 июня 1941 года.'),
    ('lone_negation', 'Что такое вакуум', 'Не', ' воздух, а пространство, в котором практически нет вещества.',
     'Не воздух, а пространство, в котором практически нет вещества.'),
    ('negation_in_two', 'Правда ли что кит рыба', 'Кит не', ' рыба, а млекопитающее.', 'Кит не рыба, а млекопитающее.'),
    ('abbreviation', 'Что такое ДНК', 'ДНК — эт', 'о молекула, хранящая наследственную информацию.',
     'молекула, хранящая наследственную информацию.'),
]


@pytest.mark.parametrize('gap', [0.05, 0.9], ids=['next_segment_at_once', 'next_segment_inside_the_grace_window'])
@pytest.mark.parametrize('case', CUT_PAIRS, ids=[c[0] for c in CUT_PAIRS])
def test_a_segment_cut_inside_a_word_is_never_spoken_and_the_rest_is_not_lost(tmp_path, case, gap):
    _, question, first, second, spoken = case
    s = Session(tmp_path, ack_after=0.3)
    s.ask(question)
    s.at(1.0, created('a1', 'assistant', first[:2]), done('a1', 'assistant', first))
    s.at(1.0 + gap, created('a2', 'assistant', second[:2]), done('a2', 'assistant', second))
    s.until(40)
    assert s.heard == squeeze(spoken), f'the listener heard {s.texts}'
    state = s.state()
    assert state['completed'] and not state.get('streaming')


LONE_WORDS = [  # (id, question, the whole answer, which is one word without a period)
    ('entomology', 'Как называется наука о насекомых', 'Энтомология'),
    ('sublimation', 'Как называется переход вещества из твёрдого состояния в газообразное', 'Сублимация'),
    ('no', 'Правда ли что кит рыба', 'Нет'),
    ('capital', 'Какой город столица России', 'Москва'),
    ('boiling', 'Чем обеззараживают воду', 'Кипячением'),
]


@pytest.mark.parametrize('coalesce_seconds', [0, 3.2], ids=['no_coalescing', 'host_coalescing'])
@pytest.mark.parametrize('how', ['words', 'chars5'])
@pytest.mark.parametrize('case', LONE_WORDS, ids=[c[0] for c in LONE_WORDS])
def test_a_lone_word_at_the_true_end_is_spoken_once_no_newer_segment_came(tmp_path, case, how, coalesce_seconds):
    _, question, word = case
    s = Session(tmp_path, ack_after=0.3, coalesce_seconds=coalesce_seconds)
    s.ask(question)
    s.stream(word, 0.3, 1.0, how=how)             # turn.done at 1.0 s
    s.until(2.1)                                   # 1.1 s later: inside the 1.2 s window, a next segment may still come
    assert s.cues == [], 'a word that may be half of one was spoken at turn.done'
    s.until(2.6)
    assert s.texts == [word] and 2.2 <= s.cues[0][0] <= 2.4
    assert not s.state()['streaming']              # the word was the end of the answer: the stream is closed
    s.until(8)
    assert s.state()['completed']


def test_the_flush_waits_for_a_listener_who_is_still_speaking(tmp_path):
    s = Session(tmp_path)
    s.ask('Как называется наука о насекомых')
    s.at(1.0, created('a1', 'assistant', 'Энтомология'), done('a1', 'assistant', 'Энтомология'))
    s.at(1.5, created('u2', 'user', 'Уг'))                      # the listener starts to speak; the provider does not close it
    s.until(3.5)
    assert s.cues == []                                          # 2.5 s after turn.done, but a segment may follow the listener
    s.at(3.6, done('u2', 'user', 'Угу'))
    s.until(4.6)
    assert s.cues == []                                          # the window counts from the end of the listener's turn
    s.until(5.2)
    assert s.texts == ['Энтомология'] and 4.7 < s.cues[0][0] <= 5.0


def test_a_listener_who_never_finishes_cannot_hold_the_word_for_ever(tmp_path):
    s = Session(tmp_path)
    s.ask('Как называется наука о насекомых')
    s.at(1.0, created('a1', 'assistant', 'Энтомология'), done('a1', 'assistant', 'Энтомология'))
    s.at(1.5, created('u2', 'user', 'Уг'))                      # never closed
    s.until(12)
    assert s.texts == ['Энтомология'] and s.cues[0][0] > 7.0


# --- P1.2: the next segment of a cut answer is the same answer ---------------------------------------------------------

INERTIA = ('Инерция — это свойство тела сохранять своё состояние движения или покоя, пока внешняя сила не заставит его '
           'это изменить. Чем больше масса у тела, тем сильнее проявляется его инерция. Это как когда автобус резко '
           'тормозит, и тебя по инерции тянет вперёд.')
CUT_AT = 'пока внешняя сила'
INERTIA_SPOKEN = INERTIA.split('— это ', 1)[1]


def test_a_continuation_is_not_dropped_because_the_listener_repeated_the_early_cue_in_between(tmp_path):
    """The field shape: the early cue is out, the listener repeats it, and the model's text goes on in a new segment."""
    first, second = INERTIA.split(CUT_AT)[0] + CUT_AT, INERTIA.split(CUT_AT)[1]
    s = Session(tmp_path, ack_after=0.3)
    s.ask('Что такое инерция')
    s.stream(first, 0.3, 2.0)                       # the early cue comes at about 1.9 s, the listener repeats it at 2.2 s
    s.whole(second, 2.9, tid='a2')                  # and the model's text goes on 0.7 s later, in a new segment
    s.until(60)
    # the early cue came first (F1: the first clause, at its comma; WAVE 2 / L2 had cut it to «свойство тела»)
    assert s.cues and s.cues[0][1] == 'свойство тела сохранять своё состояние движения или покоя,' and s.cues[0][0] < 2.0
    assert s.heard == squeeze(INERTIA_SPOKEN)
    assert s.state()['completed']


@pytest.mark.parametrize('filler', ['Угу', 'Так', 'Ммм', 'Ага'])
def test_a_filler_between_two_segments_does_not_swallow_the_answer(tmp_path, filler):
    s = Session(tmp_path, ack_after=0.3)
    s.ask('Что такое фотосинтез')
    s.at(1.0, created('a1', 'assistant', 'Фотосинтез'), done('a1', 'assistant', 'Фотосинтез — это'))
    s.at(1.2, created('u2', 'user', filler[:2]), done('u2', 'user', filler))
    s.whole(' процесс образования глюкозы из углекислого газа и воды на свету.', 1.25, tid='a2')
    s.until(30)
    assert s.heard == 'процесс образования глюкозы из углекислого газа и воды на свету.'


def test_the_listeners_repeat_between_segments_is_still_an_acknowledgement(tmp_path):
    """The repeated portion advances the cursor as ever; the continuation then extends the answer behind it."""
    s = Session(tmp_path, ack_after=0.3)
    s.ask('Что такое инерция')
    s.stream('Инерция — это свойство тела сохранять своё состояние движения', 0.3, 1.0)
    s.whole(' или покоя, пока внешняя сила не заставит его изменить.', 1.6, tid='a2')
    s.until(40)
    assert s.heard == 'свойство тела сохранять своё состояние движения или покоя, пока внешняя сила не заставит его изменить.'
    assert s.state()['completed']


def test_a_genuinely_new_question_between_segments_still_retires_the_old_answer(tmp_path):
    s = Session(tmp_path, ack_after=0.3)
    s.ask('Что такое инерция')
    s.at(1.0, created('a1', 'assistant', 'Инерция'), done('a1', 'assistant', 'Инерция — это свойство тела сохранять'))
    s.ask('Что такое масса', at=1.2, tid='u2')
    s.whole('Масса — это мера инертности тела и количества вещества в нём.', 1.3, tid='a2')
    s.until(30)
    assert s.heard == 'мера инертности тела и количества вещества в нём.'      # nothing of the old answer after its question


def test_stop_between_segments_pauses_and_keeps_the_rest_of_the_answer(tmp_path):
    """Coordinator ruling (W1F-B, 3 Nov 2026), binding: «under CL2 ruling 1 «стоп» is a PAUSE that keeps the plan. Consistently, text of
    the CURRENT answer that has already arrived when the user pauses — published or not yet published — and text of the same answer that
    keeps arriving after the pause are kept in the plan (never spoken while paused; spoken from the paused portion on «продолжай / ещё
    раз / повтори» or by a resume). Only a NEW question (internal retire) discards the old answer's tail.»
    Until then this test pinned the opposite (the segment after «стоп» never joined the plan: the answer was over at «свойство тела»)."""
    s = Session(tmp_path, ack_after=0.3)
    s.ask('Что такое инерция')
    s.at(1.0, created('a1', 'assistant', 'Инерция'),
         done('a1', 'assistant', 'Инерция — это свойство тела сохранять своё состояние движения'))
    s.at(1.4, done('stop', 'user', 'стоп'))
    s.whole(' или покоя, пока внешняя сила не заставит его изменить.', 1.45, tid='a2')
    s.until(20)
    whole = 'свойство тела сохранять своё состояние движения или покоя, пока внешняя сила не заставит его изменить.'
    assert s.texts == ['свойство тела сохранять']             # F1: the first cue of the cut segment; nothing is spoken while paused
    assert s.state()['paused'] and not s.state()['completed']
    assert squeeze(' '.join(s.state()['chunks'])) == squeeze(whole)   # what had arrived and what came after the stop: the plan
    s.at(20.0, done('go', 'user', 'продолжай'))                # the resume speaks from the paused portion on
    s.until(60)
    assert s.heard == squeeze(whole) and s.state()['completed']


def test_a_reply_to_the_listener_after_a_finished_sentence_stays_muted(tmp_path):
    s = Session(tmp_path, ack_after=0.3)
    s.ask('Что такое инерция')
    s.whole('Инерция — это свойство тела сохранять скорость.', 1.0)
    s.whole('Хорошо, продолжаем.', 1.5, tid='chatter')           # the model talks to the listener's repeat
    s.until(30)
    assert s.heard == 'свойство тела сохранять скорость.'


def test_talk_after_the_grace_window_is_not_appended_to_a_finished_answer(tmp_path):
    s = Session(tmp_path, ack_after=0.3)
    s.ask('Что такое инерция')
    s.whole('Инерция — это свойство тела сохранять скорость', 1.0)   # no period: closed by the grace flush at 2.2 s
    s.whole('Хорошо, продолжаем.', 4.0, tid='chatter')
    s.until(30)
    assert s.heard == 'свойство тела сохранять скорость'


def test_a_late_continuation_is_still_the_rest_of_an_answer_that_nobody_has_spoken(tmp_path):
    """Nothing could be said of the cut segment, so nothing was closed: the rest of it is still the answer."""
    s = Session(tmp_path, ack_after=0.3)
    s.ask('Что такое фотосинтез')
    s.at(1.0, created('a1', 'assistant', 'Фотосинтез'), done('a1', 'assistant', 'Фотосинтез — это'))
    s.at(4.0, created('u2', 'user', 'Уг'), done('u2', 'user', 'Угу'))
    s.whole(' процесс образования глюкозы из углекислого газа и воды на свету.', 6.0, tid='a2')   # 5 s after the cut
    s.until(30)
    assert s.heard == 'процесс образования глюкозы из углекислого газа и воды на свету.'


# --- the reviewer's differential replay, as a property: any delivery shape dictates the whole answer --------------------

from test_first_cue_never_silent import COMPLETE  # noqa: E402  (the 18 answers of the first property table, hand-derived)

SHAPES = ['split_at_a_space', 'split_inside_a_word', 'three_pieces_inside_words', 'no_final_period']


def segments_of(answer, shape, seed):
    """The pieces the provider could deliver as separate assistant turns; they concatenate to the answer."""
    import random
    rng = random.Random(seed)
    if shape == 'no_final_period':
        return [answer.rstrip('.')]
    inside = [i for i in range(2, len(answer) - 2) if answer[i - 1].isalnum() and answer[i].isalnum()]
    if shape == 'split_at_a_space':
        spots = [i for i in range(2, len(answer) - 2) if answer[i] == ' ']
        cuts = [rng.choice(spots)]
    elif shape == 'split_inside_a_word':
        cuts = [rng.choice(inside)]
    else:
        cuts = sorted(rng.sample(inside, 2))
    bounds = [0] + cuts + [len(answer)]
    return [answer[a:b] for a, b in zip(bounds, bounds[1:])]


def feasible(answer, shape):
    return shape != 'split_at_a_space' or ' ' in answer[2:-2]    # a one-word answer has no space to cut at


SHAPE_CASES = [pytest.param(case, shape, id=f'{case[0]}-{shape}') for case in COMPLETE for shape in SHAPES
               if feasible(case[2], shape)]


@pytest.mark.parametrize('case,shape', SHAPE_CASES)
def test_whatever_the_delivery_shape_the_whole_answer_is_dictated_whole_words_only(tmp_path, case, shape):
    _, question, answer, spoken, keep = case
    pieces = segments_of(answer, shape, seed=20261102)
    s = Session(tmp_path, ack_after=0.3)
    s.ask(question)
    for n, piece in enumerate(pieces):
        s.at(1.0 + 0.4 * n, created(f'a{n}', 'assistant', piece[:2]), done(f'a{n}', 'assistant', piece))
    s.until(70)
    expected = squeeze(spoken.rstrip('.') if shape == 'no_final_period' else spoken)
    assert s.heard == expected, f'delivered as {pieces}; the listener heard {s.texts}'
    for token in keep:
        assert token in s.heard
    state = s.state()
    assert state['completed'] and not state.get('streaming')


# --- P1.3: choice («…или…?») and yes/no («…ли…?») questions are answered with the question's own words ------------------

from echo_sync.first_useful import first_cue  # noqa: E402

CHOICE = [  # (id, question, the whole answer): every word of the answer is a word of the question, and it IS the answer
    ('tea_or_coffee', 'Чай или кофе?', 'Кофе.'),
    ('earth_round', 'Правда ли, что Земля круглая?', 'Правда, Земля круглая.'),
    ('whale', 'Кит — рыба или млекопитающее?', 'Млекопитающее.'),
    ('sun_or_earth_sentence', 'Что больше, Солнце или Земля?', 'Солнце больше Земли.'),
    ('sun_or_earth_word', 'Что больше, Солнце или Земля?', 'Солнце.'),
    ('spider', 'Сколько ног у паука, шесть или восемь?', 'Восемь.'),
    ('seven_or_nine', 'Что больше, 7 или 9?', '9 больше 7.'),
    ('colour', 'Какого цвета небо днём, синего или зелёного?', 'Синего.'),
    ('whale_true', 'Правда ли, что кит млекопитающее?', 'Это правда.'),
    ('whale_restated', 'Правда ли, что кит млекопитающее?', 'Правда, кит млекопитающее.'),
    ('hands', 'Нужно ли мыть руки перед едой?', 'Нужно.'),
]


@pytest.mark.parametrize('case', CHOICE, ids=[c[0] for c in CHOICE])
def test_a_choice_or_yes_no_question_answered_in_its_own_words_is_not_silent(tmp_path, case):
    _, question, answer = case
    s = Session(tmp_path, ack_after=0.3)
    assert [a['type'] for a in s.c.provider(done('u1', 'user', question))][-1] == 'route' and s.c.direct_content
    s.whole(answer, 0.5)
    s.until(20)
    assert s.heard == squeeze(answer)
    assert s.state()['completed']


@pytest.mark.parametrize('question,answer', [
    ('Чай или кофе?', 'Чай или кофе.'),                                    # the question read back
    ('Правда ли, что Земля круглая?', 'Правда ли, что Земля круглая.'),    # the question read back
    ('Правда ли, что Земля круглая?', 'Хорошо.'),                          # a filler is no answer
    ('Что такое инерция', 'Инерция.'),                                     # an ordinary question: the term read back
], ids=['choice_read_back', 'yes_no_read_back', 'yes_no_filler', 'term_read_back'])
def test_the_question_read_back_is_still_no_answer(tmp_path, question, answer):
    s = Session(tmp_path)
    s.c.provider(done('u1', 'user', question))
    s.whole(answer, 0.5)
    s.until(8)
    assert s.cues == []


@pytest.mark.parametrize('question,answer', [
    ('Вы понимаете, что это важно?', 'Понимаю.'),
    ('Вы примете наше предложение?', 'Принимаю.'),
    ('Сообщите?', 'Сообщу.'),
    ('Ты знаешь, где находится вокзал?', 'Знаю.'),
], ids=['understand', 'accept', 'tell', 'know'])
def test_a_yes_no_question_answered_with_its_own_verb_is_dictated_not_reported_unanswered(tmp_path, question, answer):
    """Coordinator's addition to F1 round 2 (found at integration): the reply is complete and adds nothing against the question; it
    was given no cue and the listener heard «Нет ответа». A complete reply is cued; the gate only decides to extend a first portion."""
    s = Session(tmp_path, ack_after=0.3)
    s.c.provider(done('u1', 'user', question))
    s.whole(answer, 0.5)
    s.until(20)
    assert s.heard == squeeze(answer)
    assert s.state()['completed']


@pytest.mark.parametrize('opening,growth', [
    ('Инерция — это свойство тела сохранять своё', ' состояние'),
    ('Сублимация — это переход вещества из твёрдого', ' состояния'),
], ids=['inertia', 'sublimation'])
def test_a_first_segment_that_stalls_inside_its_first_sentence_is_cued_not_reported_unanswered(tmp_path, opening, growth):
    """F1 round 2: a meaning first cue of an open sentence waits for its clause end or a word past the first-cue window. A producer
    that falls silent before either, its turn still open, used to leave the text that did arrive unspoken: the answer watchdog gave the
    question up («Нет ответа», no_usable_text). Before giving up, the first cue is chosen from what arrived, as when the turn is over."""
    s = Session(tmp_path)
    s.ask(opening.split(' — ')[0].join(('Что такое ', '')))
    s.at(1.0, created('a1', 'assistant', opening))
    s.at(1.3, delta('a1', growth, 1))
    s.until(30)
    assert s.cues, 'the text that arrived was never cued'
    assert s.texts[0] and s.texts[0] in squeeze(opening + growth), s.texts
    assert s.state().get('streaming'), s.state()                   # the answer is not over: its producer may still go on


# --- P3.9: two behaviours the first round claimed but no test pinned ---------------------------------------------------

def test_an_answer_whose_only_new_word_is_ni_is_cued():
    cue = first_cue('Ни рыбы ни кита.', 'Что общего у рыбы и кита', DEFAULT_SETTINGS, final=True, last=True)
    assert cue and cue.startswith('Ни')


@pytest.mark.parametrize('echo', ['инерции.', 'Об инерции.', 'Инерцией.'])
def test_an_echo_in_another_inflection_is_still_an_echo(echo):
    assert first_cue(echo, 'Что такое инерция', DEFAULT_SETTINGS, final=True, last=True) is None


# --- P2.4: stalling and praise are never a cue ------------------------------------------------------------------------------
# «Сейчас гляну.» / «Секунду.» / «Хороший вопрос.» / «Давайте разберёмся.» are not the answer. Spoken as the only cue they also
# closed the stream (they end in a period), so the real answer of the next segment was lost.

from echo_sync.textutil import strip_process_prefix  # noqa: E402

STALLING = ['Сейчас гляну.', 'Секунду.', 'Хороший вопрос.', 'Давайте разберёмся.', 'Сейчас посмотрю.', 'Дайте подумать.',
            'Так, посмотрим.', 'Сейчас скажу.', 'Сейчас найду.', 'Одну секунду.', 'Очень интересный вопрос!']
INERTIA_ANSWER = 'Инерция — это свойство тела сохранять скорость, пока на него не действуют силы.'
INERTIA_ANSWER_SPOKEN = 'свойство тела сохранять скорость, пока на него не действуют силы.'


@pytest.mark.parametrize('phrase', STALLING)
def test_a_stalling_phrase_alone_is_never_spoken(tmp_path, phrase):
    s = Session(tmp_path)
    s.ask('Что такое инерция')
    s.whole(phrase, 1.0)
    s.until(8)
    assert s.cues == []


@pytest.mark.parametrize('phrase', STALLING)
def test_a_stalling_segment_does_not_close_the_answer_that_follows_it(tmp_path, phrase):
    s = Session(tmp_path, ack_after=0.3)
    s.ask('Что такое инерция')
    s.whole(' ' + phrase, 1.0)
    s.whole(' ' + INERTIA_ANSWER, 1.3, tid='a2')
    s.until(40)
    assert s.heard == INERTIA_ANSWER_SPOKEN
    assert s.state()['completed']


@pytest.mark.parametrize('phrase', STALLING)
def test_a_stalling_opening_is_dropped_from_the_answer_it_precedes(tmp_path, phrase):
    s = Session(tmp_path, ack_after=0.3)
    s.ask('Что такое инерция')
    s.whole(phrase + ' ' + INERTIA_ANSWER, 1.0)
    s.until(40)
    assert s.heard == INERTIA_ANSWER_SPOKEN


@pytest.mark.parametrize('text,rest', [
    ('Сейчас гляну. Масса — это мера.', 'Масса — это мера.'),
    ('Секунду. Масса.', 'Масса.'),
    ('Хороший вопрос! Масса.', 'Масса.'),
    ('Давайте разберёмся. Масса.', 'Масса.'),
    ('Дайте подумать. Масса.', 'Масса.'),
    ('Так, посмотрим. Масса.', 'Масса.'),
    ('Сейчас гляну. Секунду. Масса.', 'Масса.'),
])
def test_stalling_openings_are_stripped_like_the_other_procedural_preambles(text, rest):
    assert strip_process_prefix(text) == rest


@pytest.mark.parametrize('text', [
    'Давайте разберёмся, что такое масса.',       # the sentence goes on: it is content
    'Скажу честно: масса не зависит от места.',
    'Посмотрим на график скорости.',
    'Найду производную по определению.',
    'Хороший вопрос о массе: это мера.',
    'Момент силы — это произведение силы на плечо.',
    'Секунда — единица времени.',
])
def test_a_real_sentence_that_starts_like_a_stalling_phrase_is_kept(text):
    assert strip_process_prefix(text) == text


# --- the limits of the owner rule (found by mutating it: nothing pinned them) ------------------------------------------------

def test_chatter_after_a_finished_sentence_that_said_nothing_is_not_an_answer(tmp_path):
    s = Session(tmp_path, ack_after=0.3)
    s.ask('Что такое инерция')
    s.whole('Хороший вопрос.', 1.0)                                  # praise: finished, and nothing to dictate
    s.at(1.5, created('u2', 'user', 'Уг'), done('u2', 'user', 'Угу'))
    s.whole('Хорошо, продолжаем.', 1.6, tid='a2')                    # the model talking to the listener's «угу»
    s.until(10)
    assert s.cues == []


def test_talk_after_an_answer_was_declared_the_end_is_not_its_continuation(tmp_path):
    s = Session(tmp_path, ack_after=0.3)
    s.ask('Что такое инерция')
    s.whole('Это инерция', 1.0)                       # no period, and nothing in it to say: the flush declares it the end at 2.2 s
    s.at(3.0, created('u2', 'user', 'Уг'), done('u2', 'user', 'Угу'))
    s.whole('Хорошо, продолжаем.', 3.1, tid='a2')
    s.until(12)
    assert s.cues == []


def test_a_reply_that_starts_while_the_listener_is_still_asking_something_new_belongs_to_that_question(tmp_path):
    s = Session(tmp_path, ack_after=0.3)
    s.ask('Что такое инерция')
    s.at(1.0, created('a1', 'assistant', 'Инерция'), done('a1', 'assistant', 'Инерция — это свойство тела сохранять'))
    s.at(1.2, created('u2', 'user', 'Что'))                       # the listener asks something new; the turn is still open
    s.at(1.3, created('a2', 'assistant', 'Масса'))                # and the model already answers it
    s.at(1.5, done('u2', 'user', 'Что такое масса'))
    s.at(2.0, done('a2', 'assistant', 'Масса — это мера инертности тела.'))
    s.until(30)
    assert s.heard == 'мера инертности тела.'


def test_stop_before_anything_was_said_ends_the_answer_too(tmp_path):
    s = Session(tmp_path, ack_after=0.3)
    s.ask('Что такое фотосинтез')
    s.at(1.0, created('a1', 'assistant', 'Фотосинтез'), done('a1', 'assistant', 'Фотосинтез — это'))
    s.at(1.3, done('stop', 'user', 'стоп'))
    s.whole(' процесс образования глюкозы из углекислого газа и воды на свету.', 1.35, tid='a2')
    s.until(20)
    assert s.cues == []


def test_a_lone_word_held_for_the_window_is_spoken_when_the_window_closes(tmp_path):
    """The 1.2 s of grace are counted from the end of the turn (1.2 s), not from the moment the hold lets go (3.2 s)."""
    s = Session(tmp_path)
    s.ask(HEAD)
    s.stream('Сублимация', 0.3, 1.2)
    s.until(3.1)
    assert s.cues == []
    s.until(4.4)
    assert s.texts == ['Сублимация'] and 3.2 <= s.cues[0][0] <= 3.4


# --- P3.7, P3.8: how long the hold of an answer to an unfinished question lasts -------------------------------------------

HEAD = 'Как называется переход вещества в'


def test_a_tail_that_can_no_longer_merge_ends_the_hold_at_the_window(tmp_path):
    s = Session(tmp_path)
    s.ask(HEAD)
    s.whole('Это называется плавление.', 0.5)                        # the cloud's early guess to the unfinished question
    s.at(2.5, created('u2', 'user', 'газообразное'))
    s.at(3.0, delta('u2', ' состояние при нормальном', 1))            # four words
    s.at(3.1, delta('u2', ' атмосферном давлении', 2))                # six: more than the five that can be merged
    s.until(8)                                                         # (the listener's turn is still open)
    assert s.texts == ['плавление.'] and 3.2 <= s.cues[0][0] <= 3.5


@pytest.mark.parametrize('tail', ['что такое масса', 'повтори'], ids=['opens_with_a_question_word', 'is_a_command'])
def test_a_tail_that_is_a_new_question_or_a_command_cannot_merge(tmp_path, tail):
    s = Session(tmp_path)
    s.ask(HEAD)
    s.whole('Это называется плавление.', 0.5)
    s.at(2.5, created('u2', 'user', tail))                             # still open
    s.until(8)
    assert s.texts == ['плавление.'] and 3.2 <= s.cues[0][0] <= 3.5


def test_a_tail_that_could_still_merge_holds_longer_than_twice_the_window(tmp_path):
    """The reviewer's repro: the continuation started at 2.5 s and its turn ends at 6.6 s, after twice the window."""
    s = Session(tmp_path)
    s.ask(HEAD)
    s.whole('Это называется плавление.', 0.5)
    s.at(2.5, created('u2', 'user', 'газообразное'))
    s.at(4.0, delta('u2', ' минуя', 1))
    s.at(5.0, delta('u2', ' жидкое', 2))
    s.at(6.6, done('u2', 'user', 'газообразное минуя жидкое'))
    s.whole('Это называется сублимация.', 6.8, tid='a2')
    s.until(12)
    assert s.c.question_text == HEAD + ' газообразное минуя жидкое'
    assert s.texts == ['сублимация.']


def test_a_tail_that_never_ends_cannot_hold_the_answer_for_ever(tmp_path):
    s = Session(tmp_path)
    s.ask(HEAD)
    s.whole('Это называется плавление.', 0.5)
    s.at(2.5, created('u2', 'user', 'газообразное'))                   # one word, could merge: never closed
    s.until(12)
    assert s.texts == ['плавление.'] and 9.2 <= s.cues[0][0] <= 9.4


def test_the_window_counts_from_the_end_of_the_users_turn_when_the_question_came_by_delegation(tmp_path):
    """Early delegation accepts the question while the user is still speaking; the real window starts at their final."""
    head = 'Как называется переход вещества из твёрдого состояния сразу в'
    s = Session(tmp_path)
    delegation = {'type': 'delegation.created', 'item': {'id': 'd1', 'type': 'delegation', 'target': 'client',
                                                         'user_bidi_turn_id': 'u1', 'content': []}}
    s.at(0.0, created('u1', 'user', head), delegation)                 # the question is accepted at 0 s
    s.whole('Это называется плавление.', 1.0)                          # the early guess is held
    s.at(6.0, done('u1', 'user', head))                                # and the provider closes the turn 6 s later
    s.at(6.5, created('u2', 'user', 'газообразное'), done('u2', 'user', 'газообразное'))   # inside the real window
    s.whole('Это называется сублимация.', 7.0, tid='a2')
    s.until(12)
    assert s.texts == ['сублимация.'], 'the early guess was spoken 0.1 s after the final'
    assert s.c.question_text == head + ' газообразное'


# --- P2.6: an answer without a period is dictated to the number and the negation in its tail ----------------------------

TAILS = [  # (id, question, the whole answer without terminal punctuation)
    ('penguins', 'Правда ли что все птицы летают', 'Нет пингвины не летают'),
    ('not_all_birds', 'Правда ли что все птицы летают', 'Да но не все птицы умеют летать например пингвины'),
    ('right_angle', 'Сколько градусов в прямом угле',
     'В прямом угле ровно девяносто градусов а в развёрнутом углу сто восемьдесят градусов'),
]


@pytest.mark.parametrize('arrival', ['whole', 'streamed'])
@pytest.mark.parametrize('case', TAILS, ids=[c[0] for c in TAILS])
def test_an_answer_without_a_period_is_dictated_to_the_number_and_the_negation_in_its_tail(tmp_path, case, arrival):
    _, question, answer = case
    s = Session(tmp_path, ack_after=0.3)
    s.ask(question)
    if arrival == 'whole':
        s.whole(answer, 1.0)
    else:
        s.stream(answer, 0.3, 2.0)
    s.until(60)
    assert s.heard == squeeze(answer), f'the listener heard {s.texts}'
    state = s.state()
    assert state['completed'] and not state.get('streaming')


def test_a_continuation_that_has_only_just_begun_keeps_the_hold(tmp_path):
    s = Session(tmp_path)
    s.ask(HEAD)
    s.whole('Это называется плавление.', 0.5)
    s.at(2.5, created('u2', 'user', ''))                               # the listener's turn is open, no word in it yet
    s.at(3.5, delta('u2', 'газообразное', 1))
    s.at(4.0, done('u2', 'user', 'газообразное'))
    s.whole('Это называется сублимация.', 4.2, tid='a2')
    s.until(10)
    assert s.c.question_text == HEAD + ' газообразное' and s.texts == ['сублимация.']


# ======================================================================================================================
# The independent review of Task 2 (a544477): its two P1 findings are the root causes above (a cut first cue, the owner
# rule); these are ITS repros, plus the coordinator's rulings 1-5.
# ======================================================================================================================

LEVER = 'Как работает рычаг'
LEVER_CUT = 'Рычаг уравнивает моменты сил. Длинное плечо даёт выигрыш в силе. Короткое плечо даёт выиг'   # cut in «выигрыш»
LEVER_REST = 'рыш в пути, но не в работе.'
LEVER_WHOLE = ('Рычаг уравнивает моменты сил. Длинное плечо даёт выигрыш в силе. '
               'Короткое плечо даёт выигрыш в пути, но не в работе.')


# Cue 0 is produced at 1.1 s and takes about 2.2 s to say (this session reports no playback, so ControlledMedia assumes it is audible
# until 1.1 + 1.5 + 2.2 + 0.3 s); a listener begins to repeat it after it is over (speech that begins while a cue can be heard is the
# cue heard back, not a repeat: Wave 2 / Task B).
START = 6.0


@pytest.mark.parametrize('speech', [0.8, 1.8, 3.0], ids=['listener_0.8_s', 'listener_1.8_s', 'listener_3.0_s'])
def test_the_field_pattern_the_cloud_resumes_40_ms_after_the_listeners_turn_ends(tmp_path, speech):
    """The listener starts to repeat the first cue; the cloud cuts its answer mid-word and goes on right after their turn."""
    s = Session(tmp_path, ack_after=2.5, ack_skip=1)
    s.ask(LEVER)
    s.stream(LEVER_CUT, 0.5, 3.05)                                             # turn.done at 3.05 s, cut in «выигрыш»
    s.at(START, created('ack0', 'user', 'Рыч'))                                 # the listener repeats cue 0 ...
    # ... for ``speech`` seconds. W1F-A (brief task-w1fix-briefs.md (a), «close the cue at clause/sentence punctuation that has ALREADY
    # arrived»): cue 0 is the whole first sentence, its full stop came on the delta that released it (WAVE 2 / L2 had 2 words here)
    s.at(START + speech, done('ack0', 'user', 'Рычаг уравнивает моменты сил'))
    s.whole(LEVER_REST, START + speech + 0.04, tid='a2')                        # and the cloud resumes 40 ms later
    s.until(90)
    assert s.heard == squeeze(LEVER_WHOLE), f'the listener heard {s.texts}'
    assert s.state()['completed']


CUT_SHORT = [  # (id, question, a short first segment cut inside a word / number, the rest, what is heard)
    ('lever_short_head', LEVER, 'Длинное пле', 'чо даёт выигрыш в силе.', 'Длинное плечо даёт выигрыш в силе.'),
    ('thermos', 'Как устроен термос', 'Это правило не д', 'ействует для звука.', 'Это правило не действует для звука.'),
    ('price', 'Сколько стоит билет', 'Это стоит 2', ' 500 рублей.', 'Это стоит 2 500 рублей.'),
]


@pytest.mark.parametrize('gap', [0.4, 0.8], ids=['gap_0.4_s', 'gap_0.8_s'])
@pytest.mark.parametrize('case', CUT_SHORT, ids=[c[0] for c in CUT_SHORT])
def test_a_short_first_segment_cut_inside_a_word_or_number_is_continued_not_stuck(tmp_path, case, gap):
    _, question, first, rest, spoken = case
    s = Session(tmp_path, ack_after=2.5)
    s.ask(question)
    s.whole(first, 1.0)
    s.whole(rest, 1.0 + gap, tid='a2')
    s.until(60)
    assert s.heard == squeeze(spoken), f'the listener heard {s.texts}'
    state = s.state()
    assert state['completed'] and not state.get('streaming')       # and the listener is not parked at an open stream


LATE = [  # (id, question, the first segment (cut), the continuation, what is heard)
    ('but_not', 'Можно ли это делать', 'Да, это можно делать, но', ' не при высокой температуре.',
     'Да, это можно делать, но не при высокой температуре.'),
    ('number', 'С какой скоростью движется свет', 'Свет проходит в вакууме около 300', ' 000 километров в секунду.',
     'Свет проходит в вакууме около 300 000 километров в секунду.'),
    ('word', 'Как устроен термос', 'Двойные стенки с вакуумом между ни', 'ми почти не пропускают тепло.',
     'Двойные стенки с вакуумом между ними почти не пропускают тепло.'),
]


# Ruling 1 is done in ControlledMedia (the end of an answer is declared only for a listener who has run out of published text). The
# «but_not» repro also needs the FIRST cue of an unpunctuated segment to go out at once (the portion before its cut last word), so that
# the stream stays open while the listener is behind: that is first_useful.first_cue, which has done it since WAVE 2 / Task C-seg
# (merged in integ2). The strict xfail marker that waited for it (NEEDS_FIRST_CUE, the e4c04ee dependency) is removed.


@pytest.mark.parametrize('gap', [1.5, 2.4], ids=['gap_1.5_s', 'gap_2.4_s'])
@pytest.mark.parametrize('case', LATE, ids=[c[0] for c in LATE])
def test_a_continuation_that_comes_late_is_merged_while_the_listener_is_still_behind(tmp_path, case, gap):
    """The listener repeats each cue 2.5 s after it was produced, so at 1.0 + gap they have not run out of text yet."""
    _, question, first, rest, spoken = case
    s = Session(tmp_path, ack_after=2.5)
    s.ask(question)
    s.whole(first, 1.0)
    s.whole(rest, 1.0 + gap, tid='a2')
    s.until(80)
    assert s.heard == squeeze(spoken), f'the listener heard {s.texts}'
    assert s.state()['completed']


def test_the_tail_is_kept_for_a_listener_who_is_behind_and_released_when_he_catches_up(tmp_path):
    tail = ('Рычаг уравнивает моменты сил. Длинное плечо даёт выигрыш в силе. '
            'Короткое плечо даёт выигрыш в пути и скорости')                  # no period
    s = Session(tmp_path)                                                       # the listener answers by hand
    s.ask(LEVER)
    s.whole(tail, 1.0)
    s.until(20)
    assert len(s.cues) == 1 and s.state()['streaming']                         # not closed over a listener who is not there yet
    s.at(20.0, done('ack', 'user', s.cues[0][1]))                               # now he has repeated the last portion there is
    s.until(20.6)
    assert len(s.cues) == 2 and s.cues[1][0] <= 20.3                           # and the next one comes at once
    assert not s.state()['streaming']                                           # and from then on the answer is closed


# --- ruling 2: a persisted open stream must not park the listener after a reconnect ---------------------------------

@pytest.mark.parametrize('drop_at', [8.0, 20.0], ids=['phone_drops_at_8_s', 'phone_drops_at_20_s'])
def test_a_persisted_open_stream_is_closed_when_the_phone_reconnects(tmp_path, drop_at):
    answer = ' '.join(f'Рычаг даёт выигрыш номер {n} в силе или в пути.' for n in range(1, 40))
    first = Session(tmp_path, ack_after=0.3)
    first.ask(LEVER)
    first.stream(answer, 0.3, 30.0)                                              # the cloud is still answering ...
    first.until(drop_at)                                                         # ... when the phone drops
    assert first.state()['streaming']
    clock = Clock(ORIGIN + 500)
    second = host_controller(tmp_path, clock=clock)                              # the new call: a new controller, the same db
    assert second.state()['streaming'] is False                                  # nobody produces the rest of it any more
    actions = second.provider(done('again', 'user', 'повтори'))                  # the listener asks for the portion again
    for n in range(300):                                                         # and walks to the end of what there is
        speak = [a['text'] for a in actions if a['type'] == 'speak']
        if not speak:
            break
        actions = second.provider(done(f'k{n}', 'user', speak[0]))
    state = second.state()
    assert state['completed'] and not state.get('stream_waiting_next')


# --- ruling 3: only the listener's own speech starts the repeat count again, never noise, a TV or a bystander -------

def silent_answer_session(tmp_path):
    s = Session(tmp_path)
    s.ask('Как работает рычаг')
    s.whole('Рычаг уравнивает моменты сил. Длинное плечо даёт выигрыш в силе.', 0.3)
    return s


def test_the_ambient_helper_really_repeats_in_silence(tmp_path):
    """Control for the tests below: the production profile repeats an unconfirmed portion 3 times, then waits."""
    s = Ambient(tmp_path, None, '').run()
    assert len(s.cues) == 4 and len(set(t for _, t in s.cues)) == 1


class Ambient:
    """The same silent listener, but with someone else talking near the phone."""

    def __init__(self, tmp_path, every, say, until=300, partial=False):
        self.s = silent_answer_session(tmp_path)
        self.played = 0
        for n, moment in enumerate(range(5, until, every) if every else ()):
            if partial:
                self.s.at(moment, created(f'amb{n}', 'user', say))              # a stalled partial turn, never finished
                self.s.at(moment + 3.1, lambda session: session.c.partial_quiet(now=session.clock.now) and [])
            else:
                self.s.at(moment, created(f'amb{n}', 'user', say.split()[0]), done(f'amb{n}', 'user', say))

    def run(self, until=300):
        s = self.s
        # the transport reports the end of every playout 1.2 s after the cue, as NativeMediaSocket._speak does
        for second in range(0, until):
            s.until(second)
            while self.played < len(s.cues):
                text = s.cues[self.played][1]
                self.played += 1
                s.at(s.cues[self.played - 1][0] + 1.2, (lambda t: lambda session: session.c.playback_done(
                    {'text': t, 'epoch': session.c.epoch, 'nonce': session.c.nonce,
                     'revision': session.state()['revision'], 'index': session.state()['chunk_index']},
                    now=session.clock.now) or [])(text))
        return s


@pytest.mark.parametrize('say', ['а', 'Продолжение следует', 'Сегодня будет дождь и я не знаю брать ли мне зонт или нет'],
                         ids=['one_word_of_noise', 'tv', 'bystander_twelve_words'])
@pytest.mark.parametrize('every', [12, 20], ids=['every_12_s', 'every_20_s'])
def test_noise_a_tv_or_a_bystander_never_starts_the_repeat_count_again(tmp_path, say, every):
    s = Ambient(tmp_path, every, say).run()
    assert len(s.cues) <= 1 + 3, f'the same portion was spoken {len(s.cues)} times in 300 s'
    assert len(set(t for _, t in s.cues)) == 1


def test_a_stalled_partial_of_noise_never_starts_the_repeat_count_again(tmp_path):
    s = Ambient(tmp_path, 12, 'Продолжение следует', partial=True).run()
    assert len(s.cues) <= 1 + 3


def test_assistant_chatter_never_starts_the_repeat_count_again(tmp_path):
    s = silent_answer_session(tmp_path)
    for n in range(5, 300, 5):
        s.whole('Хорошо, продолжаем.', n, tid=f'chatter{n}')
    s.until(300)
    assert len(s.cues) <= 1 + 3


# --- ruling 4: an answer of any length is dictated (the ledger no longer drops a turn longer than 4000 characters) ----

SENTENCES = ['Вода кипит при ста градусах.', 'Лёд плавится при нуле.', 'Пар легче воды.', 'Солнце нагревает землю днём.',
             'Ночью земля остывает быстро.', 'Ветер переносит тепло.', 'Облака собирают влагу.', 'Дождь питает реки.',
             'Реки текут к морю.', 'Море хранит тепло.']


def answer_of(characters):
    text, n = '', 0
    while len(text) < characters:
        text += (' ' if text else '') + SENTENCES[n % len(SENTENCES)]
        n += 1
    return text


@pytest.mark.parametrize('arrival,characters', [('whole', 4600), ('streamed', 4600), ('whole', 9000)],
                         ids=['whole_4600', 'streamed_4600', 'whole_9000'])
def test_an_answer_longer_than_the_old_4000_character_limit_is_dictated_to_the_end(tmp_path, arrival, characters):
    answer = answer_of(characters)
    s = Session(tmp_path, ack_after=0.1)
    s.ask('Как устроена погода')
    if arrival == 'whole':
        s.whole(answer, 1.0)
    else:
        s.stream(answer, 0.3, 20.0)
    s.until(520)
    assert s.heard == squeeze(answer), f'{len(s.heard)} of {len(squeeze(answer))} characters were dictated'
    assert s.state()['completed']


# --- ruling 5: a continuation that never gets turn.done is flushed after an idle time, not waited for for ever ----------

FIRST_CUT = ('Рычаг уравнивает моменты сил. Длинное плечо даёт выигрыш в силе. '
             'Короткое плечо даёт выигрыш в пути, но')                           # the first segment: turn.done, no period


def test_a_continuation_without_turn_done_is_flushed_after_the_idle_time(tmp_path):
    s = Session(tmp_path, ack_after=0.3)
    s.ask(LEVER)
    s.whole(FIRST_CUT, 1.0)
    s.at(1.5, created('a2', 'assistant', ' не в раб'))
    s.at(1.7, delta('a2', 'оте', 1))                                             # ... and then nothing, ever
    s.until(16.0)
    assert s.state()['streaming']                                               # 14.3 s after its last delta: still waiting
    s.until(17.5)
    assert not s.state()['streaming']                                           # 15 s after its last delta: flushed
    s.until(60)
    assert s.heard == squeeze(FIRST_CUT + ' не в работе')                       # everything that did arrive was dictated
    assert s.state()['completed']


def test_the_idle_watchdog_counts_from_the_last_delta(tmp_path):
    s = Session(tmp_path, ack_after=0.3)
    s.ask(LEVER)
    s.whole(FIRST_CUT, 1.0)
    s.at(1.5, created('a2', 'assistant', ' не'))
    for n in range(1, 8):                                                       # a slow producer: a word every 10 s
        s.at(1.5 + 10 * n, delta('a2', f' слово{n}', n))
    s.until(75)
    assert s.state()['streaming']                                               # never idle for 15 s: never flushed
    s.at(80.0, done('a2', 'assistant', ' не слово1 слово2 слово3 слово4 слово5 слово6 слово7.'))
    s.until(90)
    assert not s.state()['streaming']                                           # and its own turn.done closes it as before


def test_a_continuation_without_turn_done_is_not_total_silence_even_when_nothing_was_spoken_yet(tmp_path):
    s = Session(tmp_path, ack_after=0.3)
    s.ask('Как называется переход вещества из твёрдого состояния в газообразное')
    s.whole('Это назы', 1.0)                                                    # nothing can be said of this yet
    s.at(1.5, created('a2', 'assistant', 'вается суб'))
    s.at(1.7, delta('a2', 'лима', 1))                                            # ... and the producer never finishes
    s.until(14.0)
    assert s.cues == []                                                         # it may still be going on
    s.until(40)
    assert s.heard == 'сублима' and s.state()['completed']                      # the idle time ends the wait; the word is spoken


def test_the_idle_watchdog_leaves_the_first_segment_alone(tmp_path):
    """Task 2's rule, kept: silence from the FIRST segment of an answer proves nothing (it may be a long thought) - but not for good
    (E3c, DEF-T-B01): once the listener has waited at the frontier for ANSWER_CAP_SECONDS, the text that arrived ends the answer."""
    s = Session(tmp_path, ack_after=0.3)
    s.ask(LEVER)
    s.at(1.0, created('a1', 'assistant', 'Рычаг уравнивает моменты сил. Длинное плечо даёт выигрыш в'))
    s.until(25)
    assert s.state()['streaming']
    s.until(60)
    assert not s.state()['streaming']
