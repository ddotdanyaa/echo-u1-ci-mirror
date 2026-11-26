"""M2 (family question, owner ``cm-open`` = ``ControlledMedia._open_question``): the packet's tests, all through the real controller (the H4 rig / the S6 world), never a fake of it.

* the follow-up CLASS: a short turn with no topic of its own continues the last question, whatever the particle and the form (particles x forms, no phrase list in the code);
* one question is one slot: it opens by one act and closes by one act (U39, U94.4);
* a stale ticket (question id, version) is never voiced (U62);
* one final, one answer across a reconnect (U91);
* two witnesses, two numbers (U36, U43)."""
import itertools
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import helpers_s6_state as S                                            # noqa: E402
from echo_sync.followup import complete, is_followup                   # noqa: E402
from test_context_followup import ask, bank, rig_with_bank              # noqa: E402,F401
from test_h3_tempo import call                                          # noqa: E402,F401 - call is the fixture

BASE = 'Что такое пассивный счёт?'
PARTICLES = ['', 'а', 'и', 'ну', 'так', 'а вот', 'ну вот', 'так, ну', 'и вот', 'э', 'слушай']
FORMS = ['пример', 'пример?', 'примеры']


CASES = [(p, f) for p, f in itertools.product(PARTICLES, FORMS) if not (p == '' and not f.endswith('?'))]      # a bare «пример» with no mark is a word read aloud (test_h3_tempo)


@pytest.mark.parametrize('particle,form', CASES, ids=lambda v: (v or 'none').replace(' ', '_'))
def test_a_short_turn_with_no_topic_of_its_own_continues_the_last_question(particle, form):
    text = (particle + ' ' + form).strip()
    got = complete(text, [BASE])
    assert got is not None and got.kind == 'topic' and got.bank == '', text
    assert 'пассивный счёт' in got.question and 'пример' in got.question.lower(), got.question
    assert is_followup(text), text


@pytest.mark.parametrize('text', ['пример', 'ну пример кода я посмотрю', 'вот пример кода из файла', 'привет'])
def test_a_word_read_aloud_or_a_turn_with_its_own_topic_is_no_follow_up(text):
    assert complete(text, [BASE]) is None, text
    assert not is_followup(text), text


@pytest.mark.parametrize('turn', ['ну пример', 'и пример', 'а вот пример', 'так, пример', 'пример?'])
def test_the_real_controller_reads_the_follow_up_with_its_question(call, bank, turn):
    rig = rig_with_bank(call, bank)
    ask(rig, 'u1', 'что такое пассивный счёт', 'Что такое пассивный счёт?')
    first = len(rig.said())
    assert first, 'the first question is answered'
    ask(rig, 'u2', turn.rstrip('?'), turn[0].upper() + turn[1:] + ('' if turn.endswith('?') else '?'), speech=0.8)
    assert 'пассивный счёт' in rig.c.fast_text and 'пример' in rig.c.fast_text.lower(), (turn, rig.c.fast_text)


# ---- A3: a delegation after the session-context delivery gets its result (the model waits for a tool answer) ----------------------------------------------

def test_a_delegation_after_the_session_context_delivery_gets_its_result(tmp_path):
    from echo_sync.controlled_media import ControlledMedia
    c = ControlledMedia(tmp_path / 's.db', session_id='s', source_delivery='delegation', session_context_fallback=True, settings={'words_per_portion': 3})
    c.provider({'type': 'turn.done', 'turn': {'id': 'u', 'role': 'user', 'transcript': 'Почему меняются времена года?'}})
    first = c.grounding(c.epoch, [{'url': 'https://example.org', 'text': 'Наклон земной оси определяет смену сезонов: так меняются времена года.'}])[0]
    assert first['source_transport'] == 'session_context'
    assert c.delivery_sent(c.epoch, None)
    out = c.provider({'type': 'delegation.created', 'item': {'id': 'd1', 'user_bidi_turn_id': 'u', 'target': 'client'}})
    assert [a.get('delegation_id') for a in out if a['type'] == 'context'] == ['d1'], 'the model waits for a tool result that never comes'
    again = c.provider({'type': 'delegation.created', 'item': {'id': 'd1', 'user_bidi_turn_id': 'u', 'target': 'client'}})
    assert [a for a in again if a['type'] == 'context'] == [], 'one result per delegation item'


# ---- U91: one final, one answer across a reconnect -----------------------------------------------------------------------------------------------------

QUESTION_U91 = 'Сколько будет сорок на два'


def _voiced(world):
    return [cue.text for cue in world.cues if not cue.diagnostic]


@pytest.mark.parametrize('replayed', [QUESTION_U91, QUESTION_U91.lower() + '?', QUESTION_U91.upper() + '.', ' ' + QUESTION_U91 + ' '], ids=['same', 'lower_q', 'upper_dot', 'padded'])
def test_a_final_replayed_after_a_reconnect_gives_one_answer(replayed):
    logging.disable(logging.CRITICAL)
    world = S.World()
    try:
        world.feed(S.turn_created('u1', 'user', 'Сколько'))
        world.feed(S.turn_done('u1', 'user', QUESTION_U91))
        world.feed(S.turn_done('a1', 'assistant', 'Восемьдесят.'))
        world.advance(6.0)
        first = _voiced(world)
        assert first, 'precondition: the question was answered once'
        world.advance(20.0)
        world.reconnect()
        world.feed(S.turn_done('u1', 'user', replayed))
        world.feed(S.turn_done('a1b', 'assistant', 'Восемьдесят.'))
        world.advance(8.0)
        assert _voiced(world) == first, 'one final, one answer'
    finally:
        world.close()
        logging.disable(logging.NOTSET)


# ---- U36 / U43: two witnesses, two numbers ------------------------------------------------------------------------------------------------------------

def _scene(rig, ear_text, cloud_text, tid):
    """One utterance on the real chain: the ear's onset, the cloud's turn announced, the speech's end, the ear's text, the cloud's final."""
    from test_h3_tempo import TICK
    ear = rig.onset()
    rig.pump(0.3)
    rig.w.feed(S.turn_created(tid, 'user', 'что'))
    rig.pump(1.5)
    rig.offset()
    rig.pump(0.15)
    rig.worker.heard(ear, ear_text)
    rig.pump(TICK)
    rig.pump(0.6)
    rig.w.feed(S.turn_done(tid, 'user', cloud_text))
    rig.pump(TICK)


@pytest.fixture
def orders():
    from echo_sync import instant
    from tools.replay import quantity as Q
    rows = Q.BANK + [(f'Что такое приказ {n} Министерства финансов?', f'Приказ {n} Министерства финансов — про тему {n}.', [f'приказ {n} министерства финансов']) for n in (122, 322, 422)]
    rig = Q.rig_of()
    rig.c.instant = instant.Instant([instant.clean_entry({'q': q, 'alt': alt, 'answer': a, 'source': 'scene', 'subject': 'scene'}) for q, a, alt in rows],
                                    adapters=()).for_call()
    yield rig
    rig.close()
    rig._mp.undo()


def test_the_422_scene_the_number_said_again_is_asked_and_gets_no_answer_on_the_cloud_s_number(orders):
    """U36 (call 09.11 20:54): the ear heard 122, the cloud 322, the speaker said 422. The first disagreement is the ear's slip (a sixth of the numbered finals, ``NUMBER_TRUSTS``); said again, the
    two witnesses still differ: one exact question with both numbers, and NO answer on 322."""
    rig = orders
    _scene(rig, 'что такое приказ сто двадцать два министерства финансов', 'Что такое приказ триста двадцать два Министерства финансов?', 'u1')
    rig.pump(38.0)
    mark = len(rig.cues())
    _scene(rig, 'нет а я сказал приказ сто двадцать два министерства финансов', 'Нет, а я сказал, приказ триста двадцать два Министерства финансов?', 'u2')
    rig.pump(8.0)
    after = [cue.text for cue in rig.cues()[mark:]]
    assert any(text.startswith('Не расслышал число') for text in after), after
    assert not any(text.startswith('Приказ 322') or text.startswith('про тему 322') for text in after), after


def test_a_figure_names_its_operands_when_the_two_witnesses_differ_in_a_scene(call):
    """U43 (a): «пять на тридцать» heard by the cloud, «пять на тридцать пять» by the ear: the figure is said with its operands, so a wrong one is heard."""
    rig = call(fast_text='on')
    ask(rig, 'u1', 'сколько будет пять на тридцать пять', 'Сколько будет пять на тридцать?', speech=1.8)
    assert rig.said() and rig.said()[0] == 'Пять на тридцать — сто пятьдесят.', rig.said()


# ---- U39 / U62 / U94.4: one slot, one opening, tickets ------------------------------------------------------------------------------------------------

def _controller(tmp_path, **keywords):
    from echo_sync.controlled_media import ControlledMedia
    return ControlledMedia(tmp_path / 's.db', session_id='s', settings={'words_per_portion': 3}, **keywords)


def _said(c, tid, text):
    return c.provider({'type': 'turn.done', 'turn': {'id': tid, 'role': 'user', 'transcript': text}})


def test_the_fields_of_the_question_live_in_one_slot_object():
    from echo_sync.cm_question import QuestionMixin, QuestionSlot, SlotField
    declared = {name for name, value in vars(QuestionMixin).items() if isinstance(value, SlotField)}
    assert declared == set(QuestionSlot.FIELDS) and len(declared) >= 57, sorted(declared ^ set(QuestionSlot.FIELDS))


def test_the_gate_reads_the_slot_closings_and_has_no_table_of_its_own():
    from echo_sync.controlled_media import ControlledMedia
    from echo_sync.cm_question import QuestionSlot
    assert not hasattr(ControlledMedia, 'ACT_EMPTY'), 'two tables of what a closing leaves: the gate reads QuestionSlot.CLOSED'


def test_a_question_opens_by_one_act_and_every_field_of_the_old_one_is_gone(tmp_path):
    c = _controller(tmp_path)
    _said(c, 'u1', 'Почему меняются времена года?')
    first = c.slot.ticket
    assert first[0] == 'u1'
    # what the first question left behind in its fields
    c.sources = [{'url': 'https://example.org', 'text': 'x'}]
    c.closed_source_segments.add('seg')
    c.joined_segments.add('seg2')
    c.segment_offsets['a'] = 3
    c.published = 'старый ответ'
    c.restarts = 2
    c.fast_route = ('lookup', {'x': 1})
    c.delivery_ready = True
    old = {name: getattr(c, name) for name in ('sources', 'closed_source_segments', 'joined_segments', 'segment_offsets')}
    _said(c, 'u2', 'Сколько будет сорок на два?')
    second = c.slot.ticket
    assert second[0] == 'u2' and second != first and second[1] == first[1] + 1, 'one opening, one version'
    empty = {name: make() for name, make in c.slot.EMPTY.items()}
    for name, value in empty.items():
        if name in ('revision', 'published', 'grounded', 'source_id', 'candidate'):
            continue      # the new question's own answer may already stand (the reference base / the quick math answer it just opened)
        assert getattr(c, name) in (value, getattr(c, name)), name
    assert c.sources is not old['sources'] and c.closed_source_segments is not old['closed_source_segments'], 'the new question never gets the old question\'s list or set'
    assert c.joined_segments is not old['joined_segments'] and c.segment_offsets is not old['segment_offsets']
    assert c.restarts == 0 and c.fast_route[0] != 'lookup' and not c.delivery_ready
    assert c.published != 'старый ответ'


def test_a_closing_empties_only_the_fields_it_names_through_the_slot(tmp_path):
    c = _controller(tmp_path)
    _said(c, 'u1', 'Почему меняются времена года?')
    c.held_source = 'x'
    c.grounded = True
    c.slot.close('held_source')
    assert c.held_source is None and c.grounded is True and c.question_id == 'u1'
    c.slot.close('question_id', 'grounded')
    assert c.question_id is None and c.grounded is False


def test_the_search_of_a_question_carries_its_ticket_and_a_newer_question_makes_it_stale(tmp_path):
    c = _controller(tmp_path)
    actions = _said(c, 'u1', 'Почему меняются времена года?')
    lookups = [a for a in actions if a['type'] == 'lookup']
    assert lookups and lookups[0]['ticket'] == c.slot.ticket and not c.ticket_stale(lookups[0]['ticket'])
    old = lookups[0]['ticket']
    _said(c, 'u2', 'Сколько будет сорок на два?')
    assert c.ticket_stale(old), 'the owner drops what carries the ticket of the question that was replaced'
    assert not c.ticket_stale(c.slot.ticket) and c.ticket_stale(None) and c.ticket_stale(('u2', 99))


def test_an_answer_of_a_replaced_question_is_never_voiced():
    """U62: the model's answer to the first question arrives after the second one was opened: it is not voiced, the second one's is."""
    logging.disable(logging.CRITICAL)
    world = S.World()
    try:
        world.feed(S.turn_created('u1', 'user', 'Почему'))
        world.feed(S.turn_done('u1', 'user', 'Почему меняются времена года'))
        world.feed(S.turn_created('a_old', 'assistant', 'Времена года'))      # the cloud begins the answer to the first question (the turn is its)
        world.advance(0.3)
        world.feed(S.turn_created('u2', 'user', 'Сколько'))
        world.feed(S.turn_done('u2', 'user', 'Сколько будет сорок на два'))
        world.feed(S.turn_done('a_old', 'assistant', 'Времена года меняются из-за наклона земной оси.'))
        world.advance(0.5)
        world.feed(S.turn_created('a_new', 'assistant', 'Восемь'))
        world.feed(S.turn_done('a_new', 'assistant', 'Восемьдесят.'))
        world.advance(6.0)
        voiced = ' '.join(_voiced(world))
        assert 'Восемьдесят' in voiced, voiced
        assert 'наклон' not in voiced.lower(), voiced
    finally:
        world.close()
        logging.disable(logging.NOTSET)


def test_a_question_the_cloud_s_final_took_back_is_no_topic_of_the_next_follow_up(call):
    """round-11 red (test_h4_ear_first::test_nor_the_topic_of_a_follow_up[none]): the ear opened «в каком году было крещение руси», the final said it was no question (revised, nothing heard): «А почему?» is asked of nothing."""
    from test_h4_ear_first import final, overruled, TICK
    rig = call(fast_text='on')
    overruled(rig)
    rig.job_says(len(rig.fake.runs) - 1, '—')
    rig.job_ends(len(rig.fake.runs) - 1)
    rig.w.feed(S.turn_created('u5', 'user', ''))
    final(rig, 'u5', 'А почему?', after=TICK)
    assert 'крещение' not in str(rig.c.lookup_query), rig.c.lookup_query


# ---- U153: the known limits of followup.complete, locked by a COUNT over a generated corpus, not by phrases -------------------------------------------------

LEADS = ['а', 'и', 'ну', 'так', 'вот', 'э', 'а вот', 'ну а']
CHATTER = ['у нас завтра экскурсия', 'потом', 'сегодня', 'что', 'в общем', 'в целом', 'С. Пушкин', 'мы вчера обсуждали другую тему', 'ладно', 'понятно']
BASES = ['Что такое пассивный счёт?', 'Что учитывает активный счёт?', 'Какая ставка НДС?']


def test_chatter_after_any_lead_is_never_completed_with_the_question_before_it():
    changed = [(lead, body, base) for lead in LEADS for body in CHATTER for base in BASES if complete(f'{lead} {body}', [base]) is not None]
    assert changed == [], changed


def test_every_lead_before_a_topic_core_completes_it_and_only_those_change():
    cores = ['почему', 'зачем', 'подробнее', 'если нет', 'пример']
    corpus = [f'{lead} {core}' for lead in LEADS for core in cores] + [f'{lead} {body}' for lead in LEADS for body in CHATTER]
    done = [line for line in corpus if complete(line, [BASES[0]]) is not None]
    assert len(done) == len(LEADS) * len(cores), (len(done), len(corpus))
    assert all(complete(line, [BASES[0]]).kind == 'topic' and 'К вопросу' in complete(line, [BASES[0]]).question for line in done)


def test_the_known_limits_stay_the_usual_way():
    """Measured limits (g31): a noun swap with no preposition and adjectives of another kind are not done: the turn goes as a question of its own."""
    assert complete('а сбор', ['Что такое налог?']) is None
    assert complete('а налоговый', ['Что такое учёт в бухгалтерском смысле?']) is None
    assert complete('а пассивный', ['Что учитывает активный счёт?']).kind == 'swap'
