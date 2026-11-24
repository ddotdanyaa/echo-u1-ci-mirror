"""Task E3c: the cloud's restarts and replies glued into the dictation (root cause of the owner's call 35115fb1a8e5, 2 Nov 21:46).

Field evidence (the server state of that call, history of the phone session, read from a copy of controlled-state.sqlite3):

    «что такое сублимация» -> «Есть два основных значения. В психологии — когда сильные импульсы перенаправляются в социально
    приемлемые Первое — в психологии, когда сильные импульсы перенаправляют в творчество, работу и т.п.»
    «А почему» -> «так психика снижает внутренний конфликт и напряжение — вместо запрета или подавления энергия находит выход,
    который не вредит Может быть полезным или даже ценным для самого человека и окружающих. Десять.»

The cloud (GPT-Live) answers every user turn. The listener's repeat of a portion cuts the model's speech (the transport closes the
assistant segment at the listener's speech start), and after the listener's turn the model goes on with a NEW segment. That segment
is sometimes the rest of the same reply (« ног.», «ваются сильнее…»), but here it was the model starting its answer again
(«Первое — в психологии, …») or replying to the repeat («Может быть полезным…», «Десять.»), each a new sentence with a capital
letter (and, on the wire of this call, a leading space). ControlledMedia gave such a segment to the current question
(_continues_cut_answer: the segment before it was cut, the turn in between was no question) and _source joined the exact wire text:
the restart became a «continuation» of the cut sentence.

Amendment R2a (the owner's contract, binding): the capital letter is a signal, not the contract. A true continuation may begin with a
name, an abbreviation, a number or a quotation, a restart in lower case; «Может быть полезным…» is the development of the thought
(never lose the tail), «Десять.» is not. Both errors are tested - false glue and false drop - and the stems the alignment uses are
signals: the same stems with another number or negation never align (an explicit «Поправка:» instead).

Everything here drives the real ControlledMedia built with the production keywords of controlled_host.serve, on an injected clock,
with a tick every 0.1 s (the Session harness of tests/test_task1_review_round2.py). No network, no TTS, no server.
"""
import pytest

from test_first_cue_never_silent import created, delta, done, squeeze
from test_task1_review_round2 import Session
from engine_say import engine_reply


class Call(Session):
    """``Session`` plus a listener who repeats every NEW cue aloud: the speech starts ``start`` s after the cue (``turn.created`` with
    the first word), the final with the words of the cue comes ``length`` s later. ``mute``: the cues the listener leaves alone (by
    their order, 1-based). Scripted events can still be added with ``at``."""

    def __init__(self, tmp_path, *, start=0.6, length=1.2, mute=(), **overrides):
        super().__init__(tmp_path, **overrides)
        self.start, self.length, self.mute, self.said = start, length, set(mute), 0

    def until(self, seconds):
        last = int(round(seconds * 10))
        while self.step <= last:
            now = self.step / 10
            self.clock.now = 100.0 + now
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
                if len(self.cues) in self.mute or (len(self.cues) > 1 and self.cues[-2][1] == action['text']):
                    continue
                self.said += 1
                tid, text = f'r{self.said}', action['text']
                self.at(now + self.start, created(tid, 'user', text.split()[0]))
                self.at(now + self.start + self.length, done(tid, 'user', text))
            self.step += 1

    @property
    def distinct(self):
        """The cues in the order they were first spoken (a repeat of the same portion in a row is one)."""
        out = []
        for _, text in self.cues:
            if not out or out[-1] != text:
                out.append(text)
        return out

    @property
    def dictated(self):
        return squeeze(' '.join(self.distinct))


def stream(s, tid, text, start, step=0.25):
    """The cloud's speech transcript arriving word by word (``turn.created`` with the first word, a delta per word)."""
    words = [w for w in text.split(' ') if w]
    s.at(start, created(tid, 'assistant', words[0]))
    for n, word in enumerate(words[1:], 1):
        s.at(round(start + n * step, 3), delta(tid, ' ' + word, n))
    return round(start + len(words) * step, 3)


def glued(text):
    """A word of one sentence run into the capital of another: «приемлемыеПервое», «приемлемые Первое», «вредит Может»."""
    import re
    return re.findall(r'[а-яё]{2,}[ ]?(?:Первое|Может|Десять)\b', text)


# --- the owner's call, reproduced -------------------------------------------------------------------------------------

SUBLIMATION_CUT = ('Есть два основных значения. В психологии — когда сильные импульсы перенаправляются в социально '
                   'приемлемые')                                   # the cloud was cut here by the listener's repeat
SUBLIMATION_RESTART = ' Первое — в психологии, когда сильные импульсы перенаправляют в творчество, работу и т.п.'


def sublimation_call(tmp_path, restart=SUBLIMATION_RESTART, cut=SUBLIMATION_CUT, **kwargs):
    """The field shape of «что такое сублимация»: the answer streams, the first cue comes, the listener starts to repeat it while the
    cloud is still speaking (its segment is closed then), and after the listener's turn the cloud speaks again."""
    s = Call(tmp_path, mute=(1,), **kwargs)                       # the first cue is repeated by the script below, not the listener
    s.ask('что такое сублимация', tid='u1')
    ends = stream(s, 'a1', cut, 0.3)
    s.at(ends + 0.05, lambda s: s.c.provider(created('u2', 'user', 'Есть')))
    s.at(ends + 0.06, done('a1', 'assistant', cut))
    s.at(ends + 1.4, lambda s: s.c.provider(done('u2', 'user', s.texts[0])))
    s.at(ends + 1.45, created('a2', 'assistant', restart[:9]))
    s.at(ends + 1.9, delta('a2', restart[9:], 1))
    s.at(ends + 3.0, done('a2', 'assistant', restart))
    return s


def test_the_owners_sublimation_restart_is_never_glued_to_the_cut_sentence(tmp_path):
    s = sublimation_call(tmp_path)
    s.until(60)
    answer = str(s.state().get('answer') or '')
    assert not glued(answer), answer
    assert not any(glued(text) for text in s.texts + list(s.state().get('chunks') or [])), s.texts


WHY_CUT = ('Потому что так психика снижает внутренний конфликт и напряжение — вместо запрета или подавления энергия находит '
           'выход, который не вредит')
WHY_REPLY = ' Может быть полезным или даже ценным для самого человека и окружающих.'
WHY_OTHER = ' Десять.'


def why_call(tmp_path):
    """«А почему»: the cloud is cut, replies to the repeat with a new sentence, is cut again and replies to something else."""
    s = Call(tmp_path, mute=(1,))
    s.ask('А почему', tid='u1')
    ends = stream(s, 'a1', WHY_CUT, 0.3)
    s.at(ends + 0.05, lambda s: s.c.provider(created('u2', 'user', 'так')))
    s.at(ends + 0.06, done('a1', 'assistant', WHY_CUT))
    s.at(ends + 1.4, lambda s: s.c.provider(done('u2', 'user', s.texts[0])))
    s.at(ends + 1.45, created('a2', 'assistant', WHY_REPLY[:7]))
    s.at(ends + 2.2, delta('a2', WHY_REPLY[7:], 1))
    s.at(ends + 3.5, created('u3', 'user', 'Ну'))
    s.at(ends + 3.51, done('a2', 'assistant', WHY_REPLY))
    s.at(ends + 4.2, done('u3', 'user', 'Ну'))
    s.at(ends + 4.25, created('a3', 'assistant', WHY_OTHER))
    s.at(ends + 4.6, done('a3', 'assistant', WHY_OTHER))
    return s


# --- the revision contract for a restart (audit M04): the confirmed portions stay, the rest comes from the restart -----------

# F1 (wave F): with meaning-sized portions the owner's cut sentence («В психологии — когда …») is never published before the cut, so
# the listener is on a portion of the cut sentence only when that sentence is long enough to be planned while it streams: this cut
# keeps the owner's words and lengthens its second sentence so that its first clause is heard before the restart.
LONG_CUT = ('Есть два основных значения. В психологии, когда сильные импульсы человека, которые он не может выразить прямо, '
            'перенаправляются в социально приемлемые')
LONG_RESTART = ' Первое — в психологии, когда сильные импульсы человека перенаправляют в творчество, работу и т.п.'


def test_a_restart_aligned_on_the_portion_the_listener_heard_continues_after_it(tmp_path):
    """The restart restates the portion the listener is on («В психологии, когда сильные импульсы человека,») and goes on; the
    dictation goes on from there with the restart's words, nothing confirmed is said again and nothing is glued."""
    s = sublimation_call(tmp_path, cut=LONG_CUT, restart=LONG_RESTART)
    s.until(60)
    assert s.distinct[1] == 'В психологии, когда сильные импульсы человека,', s.distinct   # precondition: the listener is on it
    assert s.dictated == ('Есть два основных значения. В психологии, когда сильные импульсы человека, перенаправляют в творчество, '
                          'работу и т.п.'), s.distinct
    assert len(s.distinct) == len(set(s.distinct)), f'a portion was said twice: {s.distinct}'
    state = s.state()
    assert state['completed'] and not state.get('streaming'), state


def test_a_restart_of_the_unconfirmed_part_replaces_it_after_the_confirmed_portions(tmp_path):
    """The restart does not restate the portion the listener heard last («В психологии —») but retells the part nobody has confirmed:
    the confirmed portion stays, the restart takes the place of everything after it."""
    restart = ' Первое — когда сильные импульсы перенаправляют энергию в творчество, работу и т.п.'
    s = sublimation_call(tmp_path, restart=restart)
    s.until(60)
    state = s.state()
    assert squeeze(' '.join(state['chunks'])) == ('Есть два основных значения. Первое — когда сильные импульсы перенаправляют '
                                                   'энергию в творчество, работу и т.п.'), state['chunks']
    assert state['completed'] and not state.get('streaming'), state
    assert not any(glued(text) for text in s.texts), s.texts


def test_a_restart_that_retells_the_confirmed_part_in_other_words_is_dropped_and_the_plan_kept(tmp_path):
    """It says «два значения» (confirmed) without the rest of that portion and never reaches the part being dictated: no confident
    alignment. The original plan is dictated to its end; the restart is never glued and never makes the listener say a thing twice."""
    restart = ' Есть два значения, и оба связаны с энергией человека.'
    s = sublimation_call(tmp_path, restart=restart)
    s.until(60)
    assert s.dictated == squeeze(SUBLIMATION_CUT), s.distinct
    assert s.state()['completed'], s.state()


def test_nothing_said_yet_the_newer_segment_replaces_the_cut_one(tmp_path):
    """The cut segment was only a stall the gate never spoke; after a «угу» the model gives the answer as a new sentence. Nothing
    was published, so nothing is lost: the newer segment IS the answer (it is not appended to «Хорошо, сейчас»)."""
    s = Call(tmp_path)
    s.ask('Что такое инерция', tid='u1')
    s.at(0.4, created('a1', 'assistant', 'Хорошо,'), delta('a1', ' сейчас', 1))
    s.at(0.9, created('u2', 'user', 'Угу'))
    s.at(0.91, done('a1', 'assistant', 'Хорошо, сейчас'))
    s.at(1.5, done('u2', 'user', 'Угу'))
    s.at(1.55, created('a2', 'assistant', 'Инерция — это'))
    s.at(2.2, done('a2', 'assistant', 'Инерция — это свойство тела сохранять скорость.'))
    s.until(30)
    assert s.dictated == 'свойство тела сохранять скорость.', s.distinct


def test_a_proper_name_that_continues_the_cut_sentence_is_still_its_continuation(tmp_path):
    """Guard: Russian writes a proper name with a capital inside a sentence. «…в городе» | « Москве, …» is the rest of the same
    sentence, not a restart, and is joined exactly as before (the place is the answer)."""
    cut = 'Красная площадь находится в центре столицы, в городе'
    s = Call(tmp_path, mute=(1,))
    s.ask('Где находится Красная площадь', tid='u1')
    ends = stream(s, 'a1', cut, 0.3)
    # c23: since c22-merge (``_close_open_end``) the first cue «…центре столицы,» waits for the next clause while it may fit, so it is spoken
    # when the cut segment ends, not before: the listener repeats it after that (as ``cut_then`` below does since F1).
    s.at(ends + 0.06, done('a1', 'assistant', cut))
    s.at(ends + 0.3, lambda s: s.c.provider(created('u2', 'user', s.texts[0].split()[0])))
    s.at(ends + 1.6, lambda s: s.c.provider(done('u2', 'user', s.texts[0])))
    s.at(ends + 1.65, created('a2', 'assistant', ' Москве'))
    s.at(ends + 2.2, done('a2', 'assistant', ' Москве, рядом с Кремлём.'))
    s.until(60)
    assert s.dictated.endswith('в городе Москве, рядом с Кремлём.'), s.distinct
    assert s.state()['completed'], s.state()


# --- amendment R2a: a capital letter is a signal, not the verdict. Both errors are tested: false glue and false drop ----------------

def cut_then(tmp_path, question, cut, segment, *, done_at=0.55, **kwargs):
    """``cut`` streams and is closed by the listener's repeat of the first cue (an ACK); right after their final the cloud speaks
    ``segment`` (``turn.created`` with its first characters, ``turn.done`` ``done_at`` s later). The listener repeats every later cue.
    F1 (wave F): a meaning-sized first cue of a cut that has no clause end is spoken only when the cut segment ends, so the listener
    starts to repeat it once it has been spoken (at ``ends + 0.05`` when it was spoken before, as the old 2-word cue always was)."""
    s = Call(tmp_path, mute=(1,), **kwargs)
    s.ask(question, tid='u1')
    ends = stream(s, 'a1', cut, 0.3)

    def starts(s):
        if not s.texts:
            s.at(s.step / 10 + 0.1, starts)
            return []
        return s.c.provider(created('u2', 'user', s.texts[0].split()[0]))
    s.at(ends + 0.05, starts)
    s.at(ends + 0.06, done('a1', 'assistant', cut))
    s.at(ends + 1.4, lambda s: s.c.provider(done('u2', 'user', s.texts[0])))
    s.at(ends + 1.45, created('a2', 'assistant', segment if done_at is None else segment[:8]))
    if done_at is not None:
        s.at(ends + 1.45 + done_at, done('a2', 'assistant', segment))
    return s


# false glue

def test_a_lower_case_restart_is_aligned_not_glued(tmp_path):
    """The model starts again in lower case, retelling the portion the listener is on («в психологии, когда сильные импульсы
    человека»): it is a restart all the same."""
    s = sublimation_call(tmp_path, cut=LONG_CUT, restart=' ' + LONG_RESTART.split('— ', 1)[1])
    s.until(60)
    assert s.distinct[1] == 'В психологии, когда сильные импульсы человека,', s.distinct   # precondition: the listener is on it
    assert s.dictated == ('Есть два основных значения. В психологии, когда сильные импульсы человека, перенаправляют в творчество, '
                          'работу и т.п.'), s.distinct


@pytest.mark.parametrize('restart', [SUBLIMATION_RESTART, ' в психологии, когда сильные импульсы перенаправляют в творчество, работу и т.п.'],
                         ids=['capital', 'lower_case'])
def test_the_owners_restart_takes_the_place_of_the_cut_sentence_nobody_heard(tmp_path, restart):
    """F1 (wave F), the owner's own texts: the listener has heard «Есть два основных значения.» and nothing of the cut sentence, so
    the restart - capital or lower case - retells what nobody has heard and takes its place: never glued to «…приемлемые»."""
    s = sublimation_call(tmp_path, restart=restart)
    s.until(60)
    assert s.dictated == squeeze('Есть два основных значения.' + restart), s.distinct
    assert not any('приемлемые' in text or glued(text) for text in s.distinct), s.distinct
    assert len(s.distinct) == len(set(s.distinct)), f'a portion was said twice: {s.distinct}'
    state = s.state()
    assert state['completed'] and not state.get('streaming'), state


def test_a_reply_to_something_else_right_after_the_cut_is_never_dictated(tmp_path):
    """«Десять.» right after the cut sentence (not after a finished one, where the owner rule mutes it): a bare number to a question that
    asks for none is a reply to something else - dropped, and the answer being dictated is finished."""
    s = cut_then(tmp_path, 'А почему', WHY_CUT, WHY_OTHER, done_at=0.3)
    s.until(80)
    assert s.dictated == squeeze(WHY_CUT.replace('Потому что ', '')), s.distinct
    assert s.state()['completed'], s.state()


def test_a_restart_that_retells_the_confirmed_number_otherwise_is_an_explicit_correction(tmp_path):
    """The same stems with another number («Восемь планет» confirmed, «Девять планет» retold) are never aligned (R2a): what the listener
    has said stays said, and the rest is an explicit correction."""
    s = cut_then(tmp_path, 'Сколько планет в Солнечной системе', 'Восемь планет, не считая карликовых: Меркурий, Венера, Земля',
                 ' Девять планет, если считать Плутон.')
    s.until(60)
    assert s.distinct[0] == 'Восемь планет, не считая карликовых:' and any(t.startswith('Поправка:') for t in s.distinct), s.distinct
    assert 'Девять планет, если считать Плутон.' in s.dictated, s.distinct
    assert not any(glued(t) or 'Меркурий' in t for t in s.distinct), s.distinct


def test_a_restart_that_retells_the_heard_words_with_another_negation_is_an_explicit_correction(tmp_path):
    """The heard portion is found again in the restart, but the part before it retells «не всегда» as «всегда»: no alignment
    (it would splice «не всегда» onto a text that says the opposite) - an explicit correction."""
    s = cut_then(tmp_path, 'Всегда ли трение тормозит движение', 'Трение не всегда тормозит движение, иногда оно помогает',
                 ' Трение всегда тормозит движение, без исключений.')
    s.until(60)
    assert any(t.startswith('Поправка:') for t in s.distinct), s.distinct
    assert s.dictated.endswith('Поправка: Трение всегда тормозит движение, без исключений.'), s.distinct


# false drop: what goes on with the cut sentence is never thrown away for its capital

FALSE_DROPS = [  # (id, question, the cut segment, the segment that goes on with it, how the dictation ends)
    ('abbreviation', 'Какой стандарт задаёт правила для отчётов', 'Общие требования к текстовым документам задаёт',
     ' ГОСТ 2.105, который действует с 1995 года.', 'документам задаёт ГОСТ 2.105, который действует с 1995 года.'),
    ('number', 'Когда началась Великая Отечественная война', 'Нападение Германии на Советский Союз случилось',
     ' 22 июня 1941 года.', 'Советский Союз случилось 22 июня 1941 года.'),
    ('quotation', 'Какой роман Толстого самый известный', 'Чаще всего вспоминают эпопею', ' «Война и мир».',
     'вспоминают эпопею «Война и мир».'),
    ('name_of_common_words', 'Какое событие началось в 1914 году', 'Это событие вошло в историю как', ' Первая мировая война.',
     'в историю как Первая мировая война.'),
    ('development', 'А почему', WHY_CUT, WHY_REPLY, 'который не вредит Может быть полезным или даже ценным для самого человека и '
                                                    'окружающих.'),
]


@pytest.mark.parametrize('case', FALSE_DROPS, ids=[c[0] for c in FALSE_DROPS])
def test_what_goes_on_with_the_cut_sentence_is_never_dropped_for_its_capital(tmp_path, case):
    _, question, cut, segment, ending = case
    s = cut_then(tmp_path, question, cut, segment)
    s.until(80)
    assert s.dictated.endswith(ending), s.distinct
    assert s.state()['completed'], s.state()


def test_the_owners_why_answer_keeps_the_development_of_the_thought_and_never_the_reply_to_something_else(tmp_path):
    """The field shape of «А почему»: the model went on after the repeat with a new sentence that says no word of the answer so far
    («Может быть полезным…» - the development of the thought, R2a: never lose the tail), and later answered something else («Десять.»)."""
    s = why_call(tmp_path)
    s.until(80)
    answer = str(s.state().get('answer') or '')
    assert 'Десять' not in answer and not any('Десять' in t for t in s.texts), s.texts
    assert s.dictated == squeeze(WHY_CUT.replace('Потому что ', '') + WHY_REPLY), s.distinct


def test_a_segment_that_never_ends_is_weighed_on_what_arrived_and_never_holds_the_answer(tmp_path):
    """Bounded: the segment never grows and never closes its turn. SEGMENT_IDLE_SECONDS after its last event it is weighed on what did
    arrive (it retells nothing and is no reply: the answer going on) and the answer is finished."""
    s = cut_then(tmp_path, 'А почему', WHY_CUT, ' Может быть полезным', done_at=None)
    s.until(90)
    assert s.dictated == squeeze(WHY_CUT.replace('Потому что ', '') + ' Может быть полезным'), s.distinct
    assert s.state()['completed'], s.state()


# the alignment signal itself: inflection and order are a paraphrase, another number or negation is not

def test_the_anchor_is_found_in_another_inflection_and_never_with_another_number_or_negation():
    from echo_sync.controlled_media import _content, _retelling

    def verdict(heard, restart):
        found = _retelling(_content(heard), _content(restart), False)
        return None if found is None else ('conflict' if found[1] else 'match')

    assert verdict('когда сильные импульсы', 'Первое — когда сильных импульсов становится много') == 'match'
    assert verdict('восемь планет', 'Девять планет, если считать Плутон') == 'conflict'
    assert verdict('не тормозит движение', 'Трение тормозит движение') == 'conflict'
    assert verdict('в 1914 году', 'Война началась в 1915 году') == 'conflict'
    assert verdict('сильные импульсы', 'Мощные побуждения находят выход') is None


# --- EchoEngine.revise: the engine half of the contract ---------------------------------------------------------------------

from echo_sync.engine import SILENT, EchoEngine  # noqa: E402
from echo_sync.generator import StreamingAnswer  # noqa: E402


def streamed(tmp_path, text='Один два три. Четыре пять шесть. Семь восемь девять.'):
    """An engine holding a streamed answer of three portions; the cursor on the first one."""
    answer = {'value': StreamingAnswer(text, [], final=False, retrieval_status='unverified')}
    engine = EchoEngine(tmp_path / 'e.sqlite3', lambda *a: answer['value'], settings={'portion_mode': 'words', 'words_per_portion': 3})
    engine_reply(engine, session_id='s', turn_id='q', text='Что такое счёт?', request={}, model='m')
    return engine


def test_revise_never_touches_a_confirmed_portion(tmp_path):
    engine = streamed(tmp_path)
    engine_reply(engine, session_id='s', turn_id='ack1', text='Один два три', request={}, model='m')
    state = engine.state('s')
    assert state['chunk_index'] == 1 and state['chunks'][:2] == ['Один два три.', 'Четыре пять шесть.']
    assert engine.revise(session_id='s', revision=state['revision'], keep=0, tail='Другое начало.', final=True) is None
    assert engine.state('s')['chunks'] == state['chunks']


def test_revise_in_place_of_the_heard_portion_is_a_new_revision_with_its_cue(tmp_path):
    engine = streamed(tmp_path)
    engine_reply(engine, session_id='s', turn_id='ack1', text='Один два три', request={}, model='m')
    before = engine.state('s')
    reply, revision, answer = engine.revise(session_id='s', revision=before['revision'], keep=1, tail='Десять одиннадцать.', final=True)
    after = engine.state('s')
    assert reply == 'Десять одиннадцать.' and revision == before['revision'] + 1 == after['revision']
    assert after['chunks'] == ['Один два три.', 'Десять одиннадцать.'] and after['chunk_index'] == 1
    assert answer == after['answer'] == 'Один два три. Десять одиннадцать.' and not after['streaming']


def test_revise_after_the_heard_portion_keeps_its_revision_and_speaks_nothing(tmp_path):
    engine = streamed(tmp_path)
    before = engine.state('s')
    reply, revision, _ = engine.revise(session_id='s', revision=before['revision'], keep=1, tail='Десять одиннадцать.', final=False)
    after = engine.state('s')
    assert reply == SILENT and revision == before['revision'] == after['revision']
    assert after['chunks'] == ['Один два три.', 'Десять одиннадцать.'] and after['chunk_index'] == 0 and after['streaming']


def test_revise_at_the_frontier_speaks_the_next_portion(tmp_path):
    engine = streamed(tmp_path)
    state = engine.state('s')
    engine.revise(session_id='s', revision=state['revision'], keep=1, tail='', final=False)
    engine_reply(engine, session_id='s', turn_id='ack1', text='Один два три', request={}, model='m')
    assert engine.state('s')['stream_waiting_next']
    reply, revision, _ = engine.revise(session_id='s', revision=state['revision'], keep=1, tail='Десять одиннадцать.', final=True)
    after = engine.state('s')
    assert reply == 'Десять одиннадцать.' and revision == state['revision'] and after['chunk_index'] == 1
    assert not after['stream_waiting_next'] and not after['streaming']


def test_revise_that_would_leave_nothing_to_say_is_refused(tmp_path):
    engine = streamed(tmp_path)
    state = engine.state('s')
    assert engine.revise(session_id='s', revision=state['revision'], keep=0, tail='', final=False) is None
    assert engine.revise(session_id='s', revision=state['revision'] + 1, keep=1, tail='Десять.', final=True) is None
    assert engine.state('s')['chunks'] == state['chunks']


def test_the_rest_of_a_cut_answer_is_not_lost_when_its_window_runs_out_between_two_ticks_of_the_listeners_repeat(tmp_path):
    """The grace window of the cut segment counts from the end of the listener's turn when they speak through it. A tick that comes
    while they still speak after it ran out puts it off; but when it runs out between two ticks and their final comes first, nothing
    put it off, and the rest of the answer (the field: 14-47 ms after the final) found the end of the answer already declared."""
    cut = 'Инерция — это свойство тела сохранять своё'
    s = Call(tmp_path, mute=(1,), answer_grace_seconds=1.15)   # expires at 2.4 + 1.15: between the ticks 3.5 and 3.6
    s.ask('Что такое инерция', tid='u1')
    stream(s, 'a1', cut, 0.3)                                   # the text ends at 2.05 s
    s.at(2.36, done('a1', 'assistant', cut))                    # handled at the 2.4 tick: the first cue «свойство тела» then (F1)
    s.at(2.45, created('u2', 'user', 'свойство'))              # the listener repeats it (F1: it was at 1.8 s, the repeat at 2.35 s)
    s.at(3.6, done('u2', 'user', 'свойство тела'))              # handled at the 3.6 tick, before the tick itself
    s.at(3.65, created('a2', 'assistant', ' состояние'))
    s.at(4.2, done('a2', 'assistant', ' состояние движения.'))
    s.until(40)
    assert s.dictated == 'свойство тела сохранять своё состояние движения.', s.distinct
