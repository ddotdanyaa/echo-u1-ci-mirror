"""M9 (slot S4): what the call HOLDS is a kind of the conversation ledger: one row of ``KINDS`` (a TTL of timer_policy, what it binds to, why it ends), written by ``hold``, read by ``held``, ended by the tick.
Everything here goes through the real ControlledMedia: the controller learns no name of a kind."""
import ast
import re
from pathlib import Path

import pytest

from echo_sync import conversation_ledger as CL
from echo_sync import timer_policy
from echo_sync.controlled_media import ControlledMedia


class Box:
    """The engine's clock of a test: one number that the test moves."""

    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def controller(tmp_path, box=None):
    box = box or Box()
    c = ControlledMedia(tmp_path / 's.db', session_id='s', clock=box)
    c.engine.clock = box
    return c, box


@pytest.fixture
def toy(monkeypatch):
    """A new thing to hold, added the way the architecture says: a TTL in the clock table, one row in KINDS. cm_memory is not edited."""
    monkeypatch.setattr(CL, 'TOY_HOLD_S', 5.0, raising=False)
    monkeypatch.setitem(timer_policy.TIMERS, 'conversation_ledger.TOY_HOLD_S', 's')
    monkeypatch.setitem(CL.KINDS, 'toy', CL.Kind('conversation_ledger.TOY_HOLD_S', 'epoch', ('expired', 'epoch')))
    return 'toy'


def test_a_toy_kind_is_held_and_expires_by_its_ttl_through_the_real_controller(tmp_path, toy):
    c, box = controller(tmp_path)
    c.begin_call()
    c.convo.hold(toy, 'k', None, 'пообещали вернуться к смете', box())
    assert c.convo.held(toy, 'k', box()) == 'пообещали вернуться к смете'
    box.t += 4.0
    c.note_actions()                                   # the transport's tick
    assert c.convo.held(toy, 'k') == 'пообещали вернуться к смете'
    box.t += 2.0                                       # 6 s > TOY_HOLD_S
    c.note_actions()
    assert c.convo.held(toy, 'k') is None


def test_a_toy_kind_bound_to_the_epoch_ends_when_the_epoch_moves(tmp_path, toy):
    c, box = controller(tmp_path)
    c.begin_call()
    c.note_actions()                                   # the controller's epoch is seen
    c.convo.hold(toy, 'k', None, 'x', box())
    c.epoch += 1
    c.note_actions()
    assert c.convo.held(toy, 'k') is None


def test_a_held_item_without_a_registry_row_fails(tmp_path):
    c, box = controller(tmp_path)
    with pytest.raises(KeyError):
        c.convo.hold('no-such-kind', 'k', None, 'x', box())
    with pytest.raises(KeyError):
        c.convo.held('no-such-kind', 'k')


def test_a_kind_ends_only_for_the_reasons_of_its_row(toy):
    led = CL.ConversationLedger()
    led.hold(toy, 'k', None, 'x', 0.0)
    with pytest.raises(ValueError):
        led.end(toy, 'k', 'call')                      # not among the toy's reasons
    assert led.end(toy, 'k', 'epoch') is True


def test_a_kind_without_a_clock_row_cannot_be_held(monkeypatch):
    monkeypatch.setitem(CL.KINDS, 'orphan', CL.Kind('conversation_ledger.NOT_A_TIMER', 'tid', ('expired',)))
    assert any('orphan' in p for p in CL.kind_problems())
    with pytest.raises(KeyError):
        CL.ConversationLedger().hold('orphan', 'k', None, 'x', 0.0)


def test_every_row_of_kinds_is_valid_and_every_hold_in_the_engine_names_a_row():
    assert CL.kind_problems() == []
    used = set()
    for path in Path(CL.__file__).parent.glob('*.py'):
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in ('hold', 'held') and node.args \
                    and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                used.add(node.args[0].value)
    assert used and used <= set(CL.KINDS), used - set(CL.KINDS)


# -- A4: lookup-topic is a kind: a new call starts without the topic of the call before; a redial inside the window keeps it ---------------------------------------

def test_a4_the_lookup_topic_is_held_by_the_ledger_and_a_new_call_does_not_inherit_it(tmp_path):
    c, box = controller(tmp_path)
    c.lookup_topic = 'Почему меняются времена года?'
    assert c.convo.held('topic', 'lookup') == 'Почему меняются времена года?'
    assert c.lookup_topic == 'Почему меняются времена года?'
    c.call_began = box()                               # a new call began (``_begin_call``)
    assert c.lookup_topic == '' and c.convo.held('topic', 'lookup') is None


# -- U88 / U89: the card reaches the model's request; the projection follows the ledger when the words are written, not in the hook of the request --------------------

import time as _time

from echo_sync import v6_memory as V


class Fast:
    carry = recap = None

    def _played(self):
        return None


def turn(tid, role, text):
    return {'type': 'turn.done', 'turn': {'id': tid, 'role': role, 'transcript': text}}


def answered(c, tid, question, answer):
    c.provider(turn(tid, 'user', question))
    c.grounding(c.epoch, [{'url': 'https://example.org', 'text': 'source'}])
    acts = c.provider(turn('a' + tid, 'assistant', getattr(c, 'answer_marker', '') + answer))
    cue = next((x for x in acts if isinstance(x, dict) and x.get('text')), None)      # a correction of the answer before it gets no cue of its own
    if cue:
        c._cue_event('began', cue, c.clock())
        c._cue_event('done', cue, c.clock() + 1.0)


def test_u89_the_projection_follows_the_ledger_when_the_words_are_written_not_in_the_hook(tmp_path):
    """Red before: ``Memory.prepare`` read a mode that no longer exists, raised on every write and the controller swallowed it: nothing was ready, the hook rebuilt it all on the request."""
    c, box = controller(tmp_path)
    memory = V.attach({}, c)
    c.begin_call()
    c.provider(turn('u1', 'user', 'Цена за штуку 500 рублей.'))
    assert memory._proj is not None and memory._proj.size() >= 1, 'the card of the first request must not be the first time the ledger is read'


def test_u88_the_correction_scene_the_request_carries_700_and_500_only_before_its_correction(tmp_path):
    c, box = controller(tmp_path)
    memory = V.attach({}, c)
    c.begin_call()
    answered(c, 'u1', 'Цена за штуку 500 рублей.', 'Записал: пятьсот.')
    answered(c, 'u2', 'Нет, не 500, а 700 рублей за штуку.', 'Исправил: семьсот.')
    for n in range(3, 9):
        answered(c, 'u%d' % n, 'Расскажи про погоду номер %d в Казани' % n, 'Погода номер %d тёплая.' % n)
    instructions, history = memory.apply(Fast(), 'какая цена за штуку?', 'POLICY', [])
    card = instructions[len('POLICY'):]
    assert '700' in card, card
    exact = card.split(V.HEAD['exact'])[1].split('\n\n')[0] if V.HEAD['exact'] in card else card
    assert exact.index('500') < exact.index('700') if '500' in exact else True, exact


# -- U89 / U81: a session of 42 journals with 120 s between them; the card build grows with the call by its rows, not by their square ----------------------------------------

def _journal(rng, k, n):
    """One journal of a call: ``n`` exchanges about its own subject (a real journal is a call; these are shaped like them, the real ones are not in the repository)."""
    subject = ('поставка', 'смета', 'договор', 'склад', 'доставка', 'оплата', 'гарантия')[k % 7]
    words = ('погода кофе прогулка дорога фильм музыка вечер сосед собака велосипед завтрак озеро поезд гитара ветер зима весна кино театр рынок площадь улица двор крыша лестница').split()
    return [('%s %d: %s' % (subject, k, ' '.join(rng.choice(words) for _ in range(7))), ' '.join(rng.choice(words) for _ in range(5))) for _ in range(n)]


def test_u89_u81_a_session_of_42_journals_the_card_time_grows_linearly_with_the_rows(tmp_path, capsys):
    import random
    rng = random.Random(81)
    led = CL.ConversationLedger()
    class Owner:
        convo, call_began, memory_began = led, 0.0, 0.0
    memory = V.Memory({}, Owner())
    at, took, rows_at = 0.0, {}, {}
    for k in range(42):
        for q, a in _journal(rng, k, 14):               # 14 exchanges ~ 2.3 min of talk at 10 s an exchange
            n = len(led)
            led.user_final('t%d' % n, q, final_rev=1, at=at)
            led.answer('a%d' % n, a, tid='t%d' % n, at=at + 2)
            memory.prepare()
            at += 10.0
        at += 120.0                                     # the gap between two journals
        if k + 1 in (21, 42):
            runs = []
            for _ in range(7):
                began = _time.perf_counter()
                memory.apply(Fast(), 'поставка 3: какая цена', 'POLICY', [])
                runs.append(_time.perf_counter() - began)
            took[k + 1], rows_at[k + 1] = min(runs), len(led)
    ratio = took[42] / took[21]
    print('PASSPORT U89/U81: set=42 synthetic journals x 14 exchanges, gap 120 s (%.0f min of call); profile=this laptop, memory ledger, fts on; checker=min of 7 builds per point;'
          ' rows %d -> %d; build %.1f ms -> %.1f ms; x%.2f for x%.2f rows; n=1 of N=1 run' % (at / 60, rows_at[21], rows_at[42], took[21] * 1000, took[42] * 1000, ratio, rows_at[42] / rows_at[21]))
    assert rows_at[42] > 1.8 * rows_at[21]
    assert ratio < 3.0, 'x%.2f for x%.2f rows: more than linear' % (ratio, rows_at[42] / rows_at[21])


# -- U138: the memory is always on: the last 15 turns word for word and the 15 before them in one line ---------------------------------------------------------------

def test_u138_the_last_15_turns_and_a_summary_of_the_window_before_them_are_in_every_request(tmp_path):
    c, box = controller(tmp_path)
    memory = V.attach({}, c)                          # no setting anywhere: the card is the request's memory
    c.begin_call()
    for n in range(1, 41):
        answered(c, 'u%d' % n, 'Вопрос номер %d про тему %d кофе' % (n, n), 'Ответ номер %d про тему %d' % (n, n))
        box.t += 10.0
    instructions, history = memory.apply(Fast(), 'что там про тему 3?', 'POLICY', [])
    assert history == []
    # rows from the end: a40 q40 a39 q39 ... : the 15th is the answer 33; the 15 before it are q26 ... q33 (the summary, one line)
    newest = instructions.split(V.HEAD['brief'])[0]
    for n in range(34, 41):
        assert 'номер %d ' % n in newest, n
    assert 'Ответ номер 33 ' in newest
    brief = instructions.split(V.HEAD['brief'])[1].split('\n\n')[0]
    for n in range(26, 33):
        assert 'номер %d ' % n in brief + ' ', (n, brief)
    assert 'Ответ номер 33' not in brief and 'номер 25 ' not in brief + ' '


# -- U139: the memory of the day before is searched by the words of the question (stems, 0 rub, no service) ----------------------------------------------------------

def test_u139_a_question_of_the_next_day_finds_the_session_of_the_day_before_by_the_stems_of_its_words(tmp_path):
    c, box = controller(tmp_path)
    memory = V.attach({}, c)
    c.begin_call()
    answered(c, 'u1', 'Что такое договор поставки оборудования для склада?', 'Хорошо, договор поставки обсуждаем.')
    for n in range(2, 7):
        answered(c, 'u%d' % n, 'Расскажи про погоду номер %d в Казани' % n, 'Погода номер %d тёплая.' % n)
    box.t += 30 * 3600                                  # the next day
    c.begin_call()
    instructions, _ = memory.apply(Fast(), 'а что мы решили по договорам?', 'POLICY', [])
    carry = instructions.split(V.HEAD['carry'])[1] if V.HEAD['carry'] in instructions else ''
    first = carry.strip().split('\n')[0] if carry else ''
    assert 'договор поставки' in first, instructions[-900:]      # found by the question, not because it was the newest: the weather exchanges are newer


def test_u139_beyond_the_day_the_search_reaches_and_an_unrelated_question_finds_nothing_old(tmp_path):
    c, box = controller(tmp_path)
    c.begin_call()
    answered(c, 'u1', 'Что такое договор поставки оборудования?', 'Договор поставки обсуждаем.')
    box.t += 5 * 86400                                  # five days later: out of the recent window
    c.begin_call()
    assert 'договор поставки' in c.convo.recap_calls(question='что с договорами?')
    assert c.convo.recap_calls(question='какая завтра погода?') == ''
    assert c.convo.recap_calls() == ''                  # without a question only the recent hours are told, as before
