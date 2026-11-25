"""A complete model-knowledge answer must never leave the phone in silence.

Field defect 2026-11-01 (tests/fixtures/controlled_silent_inertia_20261101.json): the user asked
"Что такое инерция", the cloud model answered in full (252 characters), and ECHO published nothing
(published_chars 0) because the first-cue gate could not find a short "useful" opening and had no
way out, not even when the assistant turn was final.

These tests replay provider events through ControlledMedia built exactly as controlled_host.serve
builds it. No network, no server, no TTS: the only side effects are SQLite files in tmp_path.
"""
import ast
import asyncio
import json
import random
import re
from pathlib import Path

import pytest

import echo_sync
from echo_sync.controlled_media import ControlledMedia
from echo_sync.first_useful import first_cue
from echo_sync.native_media_socket import NativeMediaSocket
from echo_sync.settings import CALL_SETTINGS
from echo_sync.textutil import normalize

FIXTURE = Path(__file__).parent / 'fixtures' / 'controlled_silent_inertia_20261101.json'

# controlled_host.serve passes no settings, so ControlledMedia uses its own default profile: since F1 (wave F) the meaning profile.
DEFAULT_SETTINGS = dict(CALL_SETTINGS)
# The short-cue profile of WAVE 2 / L2 (the call's default before F1, still the 'slow_assistive' preset): the unit tests of the
# short first cue below run on it.
SHORT_CUE_SETTINGS = {'preset': 'slow_assistive', 'max_words': 4, 'min_words': 2}

# Same keywords as the ControlledMedia(...) call in echo_sync/controlled_host.py (checked below).
HOST_KWARGS = dict(source_delivery='delegation', session_context_fallback=True, lookup_policy='required',
                   first_useful_gate=True, coalesce_seconds=3.2, quiet_reopen=True)


pytestmark = pytest.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)


def host_controller(tmp_path, **overrides):
    return ControlledMedia(tmp_path / 'controlled-state.sqlite3', session_id='native-probe-' + '0' * 32,
                           **{**HOST_KWARGS, **overrides})


def fixture_case(name):
    return json.loads(FIXTURE.read_text(encoding='utf-8'))[name]


# --- provider wire events -------------------------------------------------------------------------

def created(tid, role, text):
    return {'type': 'turn.created', 'turn': {'id': tid, 'role': role, 'transcript': text}}


def delta(tid, text, n):
    return {'type': 'turn.delta', 'turn_id': tid, 'delta': text, 'start_ms': n * 40, 'end_ms': n * 40 + 39}


def done(tid, role, text):
    return {'type': 'turn.done', 'turn': {'id': tid, 'role': role, 'transcript': text}}


def slices(text, how, rng=None):
    """Deltas the provider could have sent: the wire only promises that they concatenate to the text."""
    if how == 'words':
        return re.findall(r'\s*\S+', text)
    if how == 'chars5':  # the fixture: 239 characters in 47 deltas
        return [text[i:i + 5] for i in range(0, len(text), 5)]
    pieces, i = [], 0
    while i < len(text):
        size = rng.randint(1, 9)
        pieces.append(text[i:i + size])
        i += size
    return pieces


class Replay:
    """One question and one assistant turn, fed event by event."""

    def __init__(self, tmp_path, question, answer, how='words', seed=0, coalesce_seconds=3.2):
        self.controller = c = host_controller(tmp_path, coalesce_seconds=coalesce_seconds)
        self.question, self.answer = question, answer
        rng = random.Random(seed)
        words = slices(question, 'words')
        c.provider(created('u1', 'user', words[0]))
        for n, piece in enumerate(words[1:], 1):
            c.provider(delta('u1', piece, n))
        self.user_actions = c.provider(done('u1', 'user', question))
        self.cues = []      # (index of the assistant event that produced it, text)
        self.arrived = []   # the answer text that had arrived when each cue was produced
        self.events = 0
        self._pieces = pieces = slices(answer, how, rng)
        self._feed(created('a1', 'assistant', pieces[0]))
        for n, piece in enumerate(pieces[1:], 1):
            self._feed(delta('a1', piece, n))
        self._feed(done('a1', 'assistant', answer))

    def _feed(self, event):
        for action in self.controller.provider(event):
            if action['type'] == 'speak':
                self.cues.append((self.events, action['text']))
                self.arrived.append(''.join(self._pieces[:self.events + 1]))
        self.events += 1

    @property
    def chunks(self):
        return (self.controller.state() or {}).get('chunks', [])

    def walk_acks(self):
        """The user repeats every cue aloud; collect what the phone speaks next, until nothing follows."""
        assert self.cues, 'total silence: nothing to repeat aloud'
        spoken = [self.cues[0][1]]
        for n in range(len(self.chunks) + 2):
            actions = self.controller.provider(done(f'ack{n}', 'user', spoken[-1]))
            speak = [a['text'] for a in actions if a['type'] == 'speak']
            if not speak:
                break
            spoken.append(speak[0])
        return spoken


def squeeze(text):
    return ' '.join(text.split())


def not_only_question_echo(cue, question):
    """Idea of scripts/voice_probe_checks.not_only_question_echo: the cue needs a word the question lacks."""
    words = lambda s: set(re.findall(r'\w+', str(s).casefold().replace('ё', 'е')))
    copulas = set('это является представляет собой такое так вот и а но из за для при без что как который '
                  'которая все весь вся всех'.split())
    return any(len(word) > 2 or word.isdigit() for word in words(cue) - words(question) - copulas)


def restates_for_longer_than_a_cue(answer, question):
    """WAVE 2 / L2: a first cue is 2-4 words (5 to keep a unit whole). When the answer opens with four or more words that are
    all the question's own («Великая Отечественная война началась 22 июня…») nothing that short says more, and the cue is
    the restatement itself - speaking it beats waiting for the first new word in silence."""
    return not not_only_question_echo(' '.join(answer.split()[:4]), question)


def check_replay(r):
    """What every replay of a final assistant answer must satisfy, whatever the answer says."""
    assert [a['type'] for a in r.user_actions] == ['cancel', 'route'] and r.controller.direct_content
    assert r.cues, 'total silence: a final assistant answer produced no cue'
    first = r.cues[0][1]
    assert first == r.chunks[0]
    assert not_only_question_echo(first, r.question) or restates_for_longer_than_a_cue(r.answer, r.question)
    assert all(normalize(text) != normalize(r.question) for text in [t for _, t in r.cues] + r.chunks)
    return first, squeeze(' '.join(r.chunks))


# --- the test harness itself must stay the host ------------------------------------------------------

def test_replay_harness_is_built_exactly_like_the_host(tmp_path):
    source = (Path(echo_sync.__file__).parent / 'controlled_host.py').read_text(encoding='utf-8')
    calls = [n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Call)
             and getattr(n.func, 'id', None) == 'ControlledMedia']
    assert len(calls) == 1
    host = {k.arg: ast.literal_eval(k.value) for k in calls[0].keywords if isinstance(k.value, ast.Constant)}
    assert {k: v for k, v in host.items() if k != 'session_id'} == HOST_KWARGS
    assert [ast.unparse(k.value) for k in calls[0].keywords if k.arg == 'settings'] == ['controller_settings(profile_settings)']      # ROOT-1: the host builds the controller's settings once, at construction
    assert host_controller(tmp_path).settings == DEFAULT_SETTINGS      # the harness: CALL_SETTINGS, the same profile in effect (test_root1_settings_once)


# --- the field defect --------------------------------------------------------------------------------

def inertia():
    case = fixture_case('silent_inertia')
    question = next(e['transcript'] for e in case['events']
                    if e.get('type') == 'conversation.item.input_audio_transcription.completed')
    answer = next(e['source_text_debug'] for e in case['events'] if 'source_text_debug' in e)
    return question, answer


# What the phone may say: the answer without its echoed head «Инерция — это» (written by hand).
INERTIA_SPOKEN = ('свойство тела сохранять своё состояние движения или покоя, пока внешняя сила не заставит его '
                  'это изменить. Чем больше масса у тела, тем сильнее проявляется его инерция. Это как когда '
                  'автобус резко тормозит, и тебя по инерции тянет вперёд.')


@pytest.mark.parametrize('how', ['words', 'chars5'])
def test_silent_inertia_fixture_gets_a_first_cue(tmp_path, how):
    question, answer = inertia()
    assert (question, len(answer)) == ('Что такое инерция', 252)  # the fixture is what the report says it is
    r = Replay(tmp_path, question, answer, how)
    first, heard = check_replay(r)
    # F1: the first meaning portion - the first clause (8 words), the same that WAVE 2 / L2 cut down to «свойство тела»
    assert first == 'свойство тела сохранять своё состояние движения или покоя,'
    assert heard == INERTIA_SPOKEN


def test_silent_inertia_cue_comes_while_the_first_sentence_is_still_streaming(tmp_path):
    question, answer = inertia()
    r = Replay(tmp_path, question, answer, 'chars5')
    assert r.cues, 'total silence'
    # The gate is provably stuck once the first clause boundary lies beyond the 6-word cue cap, long
    # before the end of the sentence, let alone turn.done (which arrived 17 s after the question).
    assert 'изменить' not in r.arrived[0]
    assert len(r.arrived[0]) < len(answer) // 2


def test_silent_inertia_every_portion_can_then_be_acknowledged(tmp_path):
    question, answer = inertia()
    r = Replay(tmp_path, question, answer)
    assert squeeze(' '.join(r.walk_acks())) == INERTIA_SPOKEN


def test_passing_sublimation_fixture_keeps_its_first_cue(tmp_path):
    """The case that already worked in the field: split question, early guess, coalescing, then the cue."""
    case = fixture_case('passing_sublimation')
    c = host_controller(tmp_path)
    head = 'Как называется переход вещества из твёрдого состояния сразу в'
    c.provider(created('u1', 'user', 'Как'))
    c.provider(delta('u1', head[3:], 1))
    c.provider(done('u1', 'user', head))
    # The cloud's early guess to the unfinished question: provider-final, no terminal punctuation.
    c.provider(created('a1', 'assistant', 'Субли'))
    c.provider(delta('a1', 'мация', 1))
    assert c.provider(done('a1', 'assistant', 'Сублимация')) == []
    c.provider(created('u2', 'user', ' газообразное'))
    c.provider(done('u2', 'user', ' газообразное'))
    cues = []
    for event in (created('a2', 'assistant', ', ещё'), delta('a2', ' говорят', 1), delta('a2', ' возгонка', 2),
                  delta('a2', '.', 3), done('a2', 'assistant', ', ещё говорят возгонка.')):
        cues += [a['text'] for a in c.provider(event) if a['type'] == 'speak']
    assert case['first_cue'] == 'Сублимация,'                 # what the field recorded (the short-cue profile of that day)
    assert case['final_cursor_state']['chunks'] == ['Сублимация,', 'ещё говорят возгонка.']
    assert cues[0] == 'Сублимация, ещё говорят возгонка.'       # F1: the sentence is one meaning portion
    assert c.state()['chunks'] == ['Сублимация, ещё говорят возгонка.']
    assert c.question_text == head + ' газообразное'


# --- varied model-knowledge answers (hand-derived expectations) -------------------------------------
# (id, question, answer, spoken, keep): ``spoken`` is the answer without a head the system may elide
# («X — это», «Потому что»); ``keep`` are the numbers/negations that must reach the listener verbatim.
COMPLETE = [
    ('term_copula_process', 'Что такое фотосинтез',
     'Фотосинтез — это процесс образования органических веществ из углекислого газа и воды на свету.',
     'процесс образования органических веществ из углекислого газа и воды на свету.', []),
    ('term_copula_phenomenon', 'Что такое испарение',
     'Испарение — это явление перехода вещества из жидкого состояния в газообразное на поверхности жидкости.',
     'явление перехода вещества из жидкого состояния в газообразное на поверхности жидкости.', []),
    ('term_copula_change', 'Что такое движение',
     'Движение — это изменение положения тела в пространстве относительно других тел с течением времени.',
     'изменение положения тела в пространстве относительно других тел с течением времени.', []),
    ('term_copula_form_no_comma', 'Что такое республика',
     'Республика — это форма правления при которой высшая власть принадлежит выборным органам.',
     'форма правления при которой высшая власть принадлежит выборным органам.', []),
    ('term_copula_negation_late', 'Что такое покой',
     'Покой — это состояние тела, при котором оно не изменяет своего положения относительно других тел.',
     'состояние тела, при котором оно не изменяет своего положения относительно других тел.', ['не изменяет']),
    ('term_first_no_copula', 'Что такое скорость',
     'Скорость показывает, какой путь проходит тело за единицу времени.',
     'Скорость показывает, какой путь проходит тело за единицу времени.', []),
    ('numbers_and_units', 'Сколько градусов в прямом угле',
     'В прямом угле 90 градусов, а в развёрнутом угле 180 градусов.',
     'В прямом угле 90 градусов, а в развёрнутом угле 180 градусов.', ['90 градусов', '180 градусов']),
    ('number_and_negation', 'Сколько планет в Солнечной системе',
     'В Солнечной системе 8 планет, не считая карликовых.',
     'В Солнечной системе 8 планет, не считая карликовых.', ['8 планет', 'не считая']),
    ('percent_signs', 'Сколько кислорода в воздухе',
     'Кислорода в воздухе около 21 %, а азота около 78 %.',
     'Кислорода в воздухе около 21 %, а азота около 78 %.', ['21 %', '78 %']),
    ('date', 'Когда началась Великая Отечественная война',
     'Великая Отечественная война началась 22 июня 1941 года.',
     'Великая Отечественная война началась 22 июня 1941 года.', ['22 июня', '1941 года']),
    ('negation_inside_answer', 'Правда ли что кит рыба',
     'Нет, кит не рыба, а млекопитающее, которое дышит лёгкими.',
     'Нет, кит не рыба, а млекопитающее, которое дышит лёгкими.', ['кит не рыба']),
    ('negation_first_word', 'Что такое вакуум',
     'Не воздух, а пространство, в котором практически нет вещества.',
     'Не воздух, а пространство, в котором практически нет вещества.', ['Не воздух']),
    ('long_single_term', 'Как называется наука о насекомых', 'Энтомология.', 'Энтомология.', []),
    ('adverbs_only_answer', 'Как движется тело без внешних сил',
     'Равномерно и прямолинейно.', 'Равномерно и прямолинейно.', []),
    ('verb_only_answer', 'Что делает вода при нуле градусов', 'Замерзает.', 'Замерзает.', []),
    ('enumeration', 'Какие бывают агрегатные состояния вещества',
     'Твёрдое, жидкое, газообразное и плазма.', 'Твёрдое, жидкое, газообразное и плазма.', []),
    ('two_sentences_because', 'Почему небо голубое',
     'Потому что воздух сильнее рассеивает синий свет. Поэтому днём мы видим небо голубым.',
     'воздух сильнее рассеивает синий свет. Поэтому днём мы видим небо голубым.', []),
    # praise is not part of the answer (review P2.4): it is dropped like the other preambles, then «Масса — это» is elided
    ('leading_service_phrase', 'Что такое масса',
     'Хороший вопрос. Масса — это мера инертности тела и количества вещества в нём.',
     'мера инертности тела и количества вещества в нём.', []),
]

# Provider-final but without terminal punctuation: the transport cannot know whether the last word is
# whole, so only complete portions before it may become immutable cues. (id, question, answer, spoken)
UNPUNCTUATED = [
    ('unpunctuated_scaffold_clause', 'Что такое инерция',
     'Инерция — это свойство тела сохранять своё состояние движения',
     'свойство тела сохранять своё состояние движения'),
    ('unpunctuated_gate_friendly', 'Что такое скорость',
     'Скорость показывает какой путь проходит тело за единицу времени',
     'Скорость показывает какой путь проходит тело за единицу времени'),
]


@pytest.mark.parametrize('how', ['words', 'chars5', 'random'])
@pytest.mark.parametrize('case', COMPLETE, ids=[c[0] for c in COMPLETE])
def test_a_final_model_knowledge_answer_is_always_cued_verbatim(tmp_path, case, how):
    _, question, answer, spoken, keep = case
    r = Replay(tmp_path, question, answer, how, seed=20261101)
    first, heard = check_replay(r)
    # Every portion the listener will be asked to repeat is a verbatim slice of the answer, in order,
    # so no number, unit or «не» was dropped, reworded or moved; the whole answer is there.
    assert heard == squeeze(spoken)
    for token in keep:
        assert token in heard
    assert heard.startswith(first)


@pytest.mark.parametrize('how', ['words', 'chars5', 'random'])
@pytest.mark.parametrize('case', UNPUNCTUATED, ids=[c[0] for c in UNPUNCTUATED])
def test_a_final_without_terminal_punctuation_still_gets_a_cue_of_whole_words(tmp_path, case, how):
    _, question, answer, spoken = case
    r = Replay(tmp_path, question, answer, how, seed=20261101)
    first, heard = check_replay(r)
    assert spoken.startswith(heard) and spoken[len(heard):len(heard) + 1] in ('', ' ')


# --- when the gate must still wait, and when it must stop waiting ------------------------------------

S = SHORT_CUE_SETTINGS
INERTIA_Q = 'Что такое инерция'


def test_the_first_cue_waits_for_the_word_after_it_not_for_punctuation():
    # WAVE 2 / L2 (was: the gate still waits while more words could give it a short useful cue): the cue is the first
    # short unit, released as soon as the word after it is whole; the first clause ends only after word 8 («покоя,»), and
    # nobody waits for that.
    waiting = 'свойство тела сохранять своё состояние'
    assert first_cue('свойство тела', INERTIA_Q, S, final=False, last=False) is None        # «тела» may still grow
    assert first_cue(waiting, INERTIA_Q, S, final=False, last=False) == 'свойство тела'
    assert first_cue(waiting + ' движения или покоя, пока', INERTIA_Q, S, final=False, last=False) == 'свойство тела'


def test_first_cue_after_a_generic_head_noun_waits_for_the_next_word():
    stuck = 'свойство тела сохранять своё состояние движения или покоя, пока внешняя '
    assert first_cue(stuck, INERTIA_Q, S, final=False, last=False) == 'свойство тела'


def test_a_finished_turn_never_waits_further():
    assert first_cue(INERTIA_SPOKEN, INERTIA_Q, S, final=True, last=True) == 'свойство тела'
    # a complete text has nothing left to wait for, even if the caller does not say the turn is over
    assert first_cue(INERTIA_SPOKEN, INERTIA_Q, S, final=True, last=False) == 'свойство тела'
    assert first_cue('Замерзает.', 'Что делает вода при нуле градусов', S, final=True, last=False) == 'Замерзает.'
    # A provider-final text is the END only once no newer segment followed it (final=True): a segment can stop in
    # the middle of a word, so until then its last word is never part of a cue.
    cue = first_cue('свойство тела сохранять своё состояние', INERTIA_Q, S, final=False, last=True)
    assert cue and 'свойство тела сохранять своё'.startswith(cue) and 'состояние' not in cue
    entomology = 'Как называется наука о насекомых'
    assert first_cue('Энтомолог', entomology, S, final=False, last=False) is None   # streaming: maybe half a word
    assert first_cue('Энтомология', entomology, S, final=False, last=True) is None  # a segment: maybe half a word
    assert first_cue('Энтомология', entomology, S, final=True, last=True) == 'Энтомология'  # the end: a whole word


def test_a_short_cue_that_says_more_than_the_question_is_never_overridden_by_the_fallback():
    # WAVE 2 / L2 (was: the cue waits for «проводит тепло», 5 words): «металл намного» already says more than the question.
    q = 'Почему металлическая ложка кажется холоднее деревянной?'
    answer = 'металл намного лучше проводит тепло и забирает его у руки.'
    cue = first_cue(answer, q, {'words_per_portion': 3}, final=True, last=True)  # profile of the pinned gate test
    assert cue == 'металл намного'


@pytest.mark.parametrize('question,answer,cue', [
    ('Сколько планет в Солнечной системе', 'В Солнечной системе 8 планет, не считая карликовых.',
     'В Солнечной системе 8 планет,'),
    ('Сколько градусов в прямом угле', 'В прямом угле 90 градусов, а в развёрнутом угле 180 градусов.',
     'В прямом угле 90 градусов,'),
    ('Сколько кислорода в воздухе', 'Кислорода в воздухе около 21 %, а азота около 78 %.',
     'Кислорода в воздухе около 21 %,'),
], ids=['planets', 'right_angle', 'oxygen'])
def test_an_answer_that_restates_the_question_is_cued_up_to_its_first_new_word(question, answer, cue):
    # «В Солнечной системе» alone is the question read back; the cue goes on to the number.
    assert first_cue(answer, question, S, final=True, last=True) == cue


@pytest.mark.parametrize('cleaned', ['инерция.', 'это.', 'хорошо.', 'ладно, итак.', 'инерция, инерция.'],
                         ids=['term_only', 'copula_only', 'filler_only', 'fillers_only', 'term_twice'])
def test_a_cue_that_only_echoes_the_question_or_says_nothing_is_never_chosen(cleaned):
    assert first_cue(cleaned, INERTIA_Q, S, final=True, last=True) is None


@pytest.mark.parametrize('answer', ['Инерция — это инерция.', 'Хорошо.', 'Ладно, итак.'],
                         ids=['definition_of_itself', 'filler', 'fillers'])
def test_an_answer_that_only_echoes_the_question_or_says_nothing_stays_silent(tmp_path, answer):
    assert Replay(tmp_path, INERTIA_Q, answer).cues == []


# --- a yes/no or a negation IS the answer, not an echo of the question ----------------------------------

YES_NO_Q = 'Правда ли что кит рыба'


@pytest.mark.parametrize('answer,cue', [('Нет.', 'Нет.'), ('Да.', 'Да.'), ('Не рыба.', 'Не рыба.'),
                                        ('Нет, не рыба.', 'Нет, не рыба.')],
                         ids=['no', 'yes', 'negated_echo', 'no_and_negated_echo'])
def test_a_short_yes_no_or_negated_answer_is_cued(tmp_path, answer, cue):
    r = Replay(tmp_path, YES_NO_Q, answer)
    assert [t for _, t in r.cues] == [cue]
    assert first_cue(answer, YES_NO_Q, S, final=True, last=True) == cue


# --- Fix rounds 1 and 2: what a question that ends in a function word is made to wait for ------------------------------
# controlled_media.py withholds the answer to a question whose last word is a function word, hoping the user continues
# («сразу в» + «газообразное»). A real continuation is merged within the coalescing window. The hold must END: with that
# window (and with a tail that began in it, as long as such a tail could still be merged), and it never applies to a question
# that is complete as asked: it carries «?» or is only an interrogative word («Почему?», «Как?», «А если?», «Почему так»).

class Clock:
    """Injectable time for ControlledMedia(clock=...): nothing here ever sleeps."""

    def __init__(self, now=100.0):
        self.now = now

    def __call__(self):
        return self.now


def clocked(tmp_path, clock, coalesce_seconds=3.2):
    return host_controller(tmp_path, clock=clock, coalesce_seconds=coalesce_seconds)


def ask(c, question, tid='u1'):
    """The user's turn ends now (the injected clock is its origin)."""
    words = slices(question, 'words')
    c.provider(created(tid, 'user', words[0]))
    for n, piece in enumerate(words[1:], 1):
        c.provider(delta(tid, piece, n))
    return c.provider(done(tid, 'user', question))


def assistant_events(text, start, end, tid='a1'):
    """[(seconds after the question ended, event)]: the answer streams word by word from start to end."""
    pieces = slices(text, 'words')
    step = (end - start) / len(pieces)
    events = [(start, created(tid, 'assistant', pieces[0]))]
    events += [(start + n * step, delta(tid, piece, n)) for n, piece in enumerate(pieces[1:], 1)]
    return events + [(end, done(tid, 'assistant', text))]


def drive(c, clock, schedule, until, ticks=True):
    """Feed the scheduled provider events and tick every 0.1 s the way NativeMediaSocket.tick does.
    Returns [(seconds after the question ended, cue text)]."""
    origin, pending, taken, cues = clock.now, sorted(schedule, key=lambda item: item[0]), 0, []
    for n in range(int(round(until * 10)) + 1):
        elapsed = n / 10
        clock.now = origin + elapsed
        actions = []
        while taken < len(pending) and pending[taken][0] <= elapsed + 1e-9:
            actions += c.provider(pending[taken][1])
            taken += 1
        if ticks:
            actions += c.tick(now=clock.now)
        cues += [(round(elapsed, 1), a['text']) for a in actions if a['type'] == 'speak']
    return cues


HEAD = 'Как называется переход вещества в'    # a question cut off after a preposition: the field's «…сразу в» + «газообразное»

FOLLOWUPS = [  # (id, question, answer, spoken): complete as asked (a «?» or only an interrogative word), yet it ends in a function word
    ('why', 'Почему?', 'Потому что наклон земной оси меняет освещение полушарий.',
     'наклон земной оси меняет освещение полушарий.'),
    ('why_without_a_mark', 'Почему', 'Потому что наклон земной оси меняет освещение полушарий.',
     'наклон земной оси меняет освещение полушарий.'),
    ('why_so', 'Почему так', 'Потому что вода расширяется при замерзании.', 'вода расширяется при замерзании.'),
    ('and_why', 'А почему', 'Потому что вода расширяется при замерзании.', 'вода расширяется при замерзании.'),
    ('what_for', 'Зачем?', 'Чтобы сохранять тепло в доме зимой.', 'Чтобы сохранять тепло в доме зимой.'),
    ('how', 'Как?', 'Нужно сначала нагреть воду, а потом добавить соль.',
     'Нужно сначала нагреть воду, а потом добавить соль.'),
    ('and_if', 'А если?', 'Тогда лёд растает быстрее, потому что температура выше.',
     'Тогда лёд растает быстрее, потому что температура выше.'),
    ('when', 'Когда?', 'Это произошло 22 июня 1941 года.', 'Это произошло 22 июня 1941 года.'),
    ('how_lone_word', 'Как?', 'Кипячением', 'Кипячением'),
]

HELD = [  # (id, question, answer, spoken): cut off in the middle: no «?», and more than an interrogative word
    ('preposition', HEAD, 'Это называется сублимация.', 'сублимация.'),
    ('conjunction', 'Расскажи про инерцию и', 'Инерция — это свойство тела сохранять скорость.',
     'Инерция — это свойство тела сохранять скорость.'),
    ('if', 'Что будет, если', 'Тогда лёд растает быстрее, потому что температура выше.',
     'Тогда лёд растает быстрее, потому что температура выше.'),
]


def answered(tmp_path, name, question, answer, ends_at, coalesce_seconds):
    clock = Clock()
    c = clocked(tmp_path / name, clock, coalesce_seconds)
    assert [a['type'] for a in ask(c, question)] == ['cancel', 'route']
    return c, drive(c, clock, assistant_events(answer, 0.3, ends_at), until=6.0)


@pytest.mark.parametrize('scenario,answer_ends_at', [('streams_past_the_window', 4.5), ('ends_inside_the_window', 1.2)])
@pytest.mark.parametrize('case', FOLLOWUPS, ids=[c[0] for c in FOLLOWUPS])
def test_a_complete_follow_up_is_not_made_to_wait_for_a_continuation(tmp_path, case, scenario, answer_ends_at):
    _, question, answer, spoken = case
    c, cues = answered(tmp_path, 'host', question, answer, answer_ends_at, 3.2)
    _, control = answered(tmp_path, 'control', question, answer, answer_ends_at, 0)   # the same stream, no coalescing at all
    assert cues, 'the answer to a complete follow-up was never spoken'
    assert cues[0][0] <= control[0][0] + 0.2                  # out exactly when its own text allows it
    if scenario == 'ends_inside_the_window':
        assert cues[0][0] < 3.2                                # not after the window of a continuation that cannot come
    assert cues[0][1] == c.state()['chunks'][0]
    assert squeeze(' '.join(c.state()['chunks'])) == spoken


@pytest.mark.parametrize('scenario,answer_ends_at', [('streams_past_the_window', 4.5), ('ends_inside_the_window', 1.2)])
@pytest.mark.parametrize('case', HELD, ids=[c[0] for c in HELD])
def test_an_unfinished_head_is_held_until_its_window_closes(tmp_path, case, scenario, answer_ends_at):
    _, question, answer, spoken = case
    c, cues = answered(tmp_path, 'held', question, answer, answer_ends_at, 3.2)
    _, control = answered(tmp_path, 'control', question, answer, answer_ends_at, 0)   # the same stream, no hold
    assert cues, 'the answer to an unfinished question was held for ever'
    assert cues[0][0] >= 3.2                                   # held while a continuation could still be merged
    assert cues[0][0] <= max(control[0][0], 3.2) + 0.2         # and out when that time is over and the text allows
    assert cues[0][1] == c.state()['chunks'][0]
    assert squeeze(' '.join(c.state()['chunks'])) == spoken


@pytest.mark.parametrize('case', FOLLOWUPS + HELD, ids=[c[0] for c in FOLLOWUPS + HELD])
def test_without_coalescing_the_same_questions_are_answered_at_once(tmp_path, case):
    _, question, answer, spoken = case
    clock = Clock()
    c = clocked(tmp_path, clock, coalesce_seconds=0)
    ask(c, question)
    cues = drive(c, clock, assistant_events(answer, 0.1, 1.5), until=6.0)
    lone = ' ' not in answer                                   # a lone word waits for the end-of-answer flush (1.2 s)
    assert cues and cues[0][0] <= 1.5 + (1.4 if lone else 0)   # long before any window could end
    assert squeeze(' '.join(c.state()['chunks'])) == spoken


def test_the_hold_also_ends_on_assistant_events_without_any_tick(tmp_path):
    clock = Clock()
    c = clocked(tmp_path, clock)
    ask(c, HEAD)
    # a first delta inside the window, the next ones after it: no tick is needed to let the answer out
    schedule = [(0.3, created('a1', 'assistant', 'Это называется')), (3.0, delta('a1', ' сублимация', 1)),
                (4.5, done('a1', 'assistant', 'Это называется сублимация.'))]
    cues = drive(c, clock, schedule, until=6.0, ticks=False)
    assert cues and 3.2 <= cues[0][0] <= 4.5
    assert squeeze(' '.join(c.state()['chunks'])) == 'сублимация.'


def test_a_real_continuation_inside_the_window_is_still_merged_and_the_early_guess_never_spoken(tmp_path):
    clock = Clock()
    c = clocked(tmp_path, clock)
    ask(c, HEAD)
    schedule = assistant_events('Это называется плавление.', 0.3, 0.6)                 # the cloud's early guess
    schedule += [(1.0, created('u2', 'user', 'газообразное')), (1.8, done('u2', 'user', 'газообразное'))]
    schedule += assistant_events('Это называется сублимация.', 2.0, 3.0, tid='a2')
    cues = drive(c, clock, schedule, until=6.0)
    assert c.question_text == HEAD + ' газообразное'
    assert [text for _, text in cues] == ['сублимация.']


def test_a_continuation_that_began_inside_the_window_keeps_the_hold_until_it_ends(tmp_path):
    clock = Clock()
    c = clocked(tmp_path, clock)
    ask(c, HEAD)
    schedule = assistant_events('Это называется плавление.', 0.3, 0.6)
    schedule += [(3.0, created('u2', 'user', 'газообразное')), (3.8, done('u2', 'user', 'газообразное'))]   # began at 3.0 < 3.2
    schedule += assistant_events('Это называется сублимация.', 4.0, 4.8, tid='a2')
    cues = drive(c, clock, schedule, until=6.0)
    assert c.question_text == HEAD + ' газообразное'
    assert [text for _, text in cues] == ['сублимация.']  # nothing spoken at 3.3 s from the early guess


def test_an_unfinished_continuation_cannot_hold_the_answer_for_ever(tmp_path):
    clock = Clock()
    c = clocked(tmp_path, clock)
    ask(c, HEAD)
    schedule = assistant_events('Это называется плавление.', 0.3, 0.6) + [(3.0, created('u2', 'user', 'газообразное'))]  # never ends
    cues = drive(c, clock, schedule, until=11.0)
    assert [text for _, text in cues] == ['плавление.'] and 9.2 <= cues[0][0] <= 9.4   # the window plus 6 s of patience


def test_a_new_question_during_the_hold_discards_the_held_answer(tmp_path):
    clock = Clock()
    c = clocked(tmp_path, clock)
    ask(c, HEAD)
    schedule = assistant_events('Это называется плавление.', 0.3, 0.6)
    schedule += [(1.0, done('u2', 'user', 'Что такое масса'))]
    schedule += assistant_events('Масса — это мера инертности тела.', 1.2, 1.8, tid='a2')
    cues = drive(c, clock, schedule, until=6.0)
    assert [text for _, text in cues] == ['мера инертности тела.']


def test_a_follow_up_after_an_answered_question_is_answered_too(tmp_path):
    clock = Clock()
    c = clocked(tmp_path, clock)
    ask(c, 'Что такое инерция')
    drive(c, clock, assistant_events('Инерция — это свойство тела сохранять скорость.', 0.3, 1.0), until=1.5)
    clock.now += 5
    assert [a['type'] for a in ask(c, 'Почему?', tid='u2')] == ['cancel', 'route']
    cues = drive(c, clock, assistant_events('Потому что на тело не действуют внешние силы.', 0.3, 2.0, tid='a2'),
                 until=6.0)
    assert cues and cues[0][0] < 3.2                           # a «?» closed it: nothing to wait for
    assert squeeze(' '.join(c.state()['chunks'])) == 'на тело не действуют внешние силы.'


def test_the_host_tick_speaks_a_held_head_when_its_window_closes(tmp_path):
    """Through NativeMediaSocket, the object the host ticks every 0.1 s: held at 1 s, synthesized at 3.3 s."""
    async def run():
        clock, sent, spoken = Clock(), [], []

        async def emit(frame):
            sent.append(frame)

        async def synthesize(text, end=None):
            spoken.append(text)
            return b'\0' * 960

        wire = NativeMediaSocket(clocked(tmp_path, clock), emit, lambda: None, lambda _: None, synthesize, clock=clock)
        wire.ready = True
        await wire.provider(done('u1', 'user', HEAD))
        clock.now += 0.5
        await wire.provider(created('a1', 'assistant', 'Это называется'))
        clock.now += 0.5
        await wire.provider(done('a1', 'assistant', 'Это называется сублимация, а не плавление.'))
        await wire.tick()
        await asyncio.gather(*wire.tasks)
        assert spoken == [] and not any(f['type'] == 'response.audio.delta' for f in sent)  # inside the window
        clock.now += 2.3  # 3.3 s after the question ended
        await wire.tick()
        await asyncio.gather(*wire.tasks)
        assert len(spoken) == 1 and 'сублимация, а не плавление.'.startswith(spoken[0])
        assert any(f['type'] == 'response.audio.delta' for f in sent)
        await wire.close()
    asyncio.run(run())
