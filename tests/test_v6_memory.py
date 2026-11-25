"""V6 slice «память» (echo_sync/v6_memory.py, setting ``v6_memory`` = off | shadow | on, default off).

The ledger of verbatim words (conversation_ledger.py) is the truth. The slice adds no store: it assembles, for ONE model request, a CARD under a budget of characters from
rebuildable projections of the ledger, in a fixed order of priority: pinned lines, the newest exchanges, retrieved earlier utterances (FTS5 or a plain pass: the same lines),
exact things (numbers and dates in spoken order, a correction stands after the value it corrects), an outline of the call. What does not fit goes from the bottom; a line is never
cut inside a number. Shadow writes sizes and ids to the call journal and changes nothing. On puts the card in at the one point of FastText._start. Off is byte for byte as before.
Nothing here is measured on the laptop: the bounds are tested on a synthetic call."""
import json
import random
import re
import sqlite3
import tracemalloc
from pathlib import Path

import pytest

from echo_sync import codex_road as CR
from echo_sync import fast_text as FT
from echo_sync import settings as cfg
from echo_sync import v6_memory as V
from echo_sync.conversation_ledger import ConversationLedger

ROOT = Path(__file__).resolve().parents[1]

CHATTER = ('погода кофе прогулка дорога фильм музыка вечер сосед собака велосипед завтрак озеро поезд гитара ветер мост лес сад окно книга чай река гора поле город дождь снег лето осень '
           'зима весна кино театр рынок площадь улица двор крыша лестница').split()


def sentence(rng, n=None):
    return ' '.join(rng.choice(CHATTER) for _ in range(n or rng.randint(5, 8)))


def feed(led, rows):
    """rows: (second, listener text, answer or None); tid ``t<i>``, answer ``a<i>`` two seconds later."""
    for i, (t, text, answer) in enumerate(rows):
        led.user_final('t%d' % i, text, final_rev=1, at=float(t))
        if answer:
            led.answer('a%d' % i, answer, tid='t%d' % i, at=float(t) + 2)
    return led


def scene(seed=7):
    """A call of 47 minutes: a condition at minute 5, a price and its correction at minutes 10 and 12, then chatter about other things."""
    rng = random.Random(seed)
    rows = [(60, 'давайте обсудим поставку оборудования для склада в Казани', 'Хорошо.'),
            (300, 'условие такое скидка пять процентов только если заказ больше трёхсот единиц', 'Понял.'),
            (600, 'цена за штуку 500 рублей', 'Записал.'),
            (720, 'нет не 500, а 450 рублей за штуку', 'Хорошо, 450.'),
            (1200, 'цену доставки отдельно договоримся позже', 'Хорошо.')]
    t = 800
    while t < 2780:
        rows.append((t, sentence(rng), sentence(rng, 4)))
        t += 12
    return sorted(rows)


QUESTION = 'напомни какая скидка по условию про заказ'
PRICE_Q = 'а какая цена за штуку'


# -- the setting ----------------------------------------------------------------------------------------------------------------------------------------------------

def test_setting_defaults_choices_and_numbers():
    assert 'v6_memory' not in cfg.DEFAULTS and 'v6_memory' not in cfg.resolve({'v6_memory': 'off'})      # memory is always on: no switch
    for key, start in (('v6_memory_chars', 'chars'), ('v6_memory_step_min', 'step_min'), ('v6_memory_lines', 'lines')):
        assert cfg.DEFAULTS[key] == V.START[start] == cfg.resolve({})[key]
    assert cfg.resolve({'v6_memory_chars': 100})['v6_memory_chars'] == cfg.DEFAULTS['v6_memory_chars']      # out of range: the default
    assert cfg.resolve({'v6_memory_chars': 6000})['v6_memory_chars'] == 6000
    assert cfg.resolve({'v6_memory_step_min': 0})['v6_memory_step_min'] == cfg.DEFAULTS['v6_memory_step_min']
    assert cfg.resolve({'v6_memory_lines': 3})['v6_memory_lines'] == 3 and cfg.resolve({'v6_memory_lines': 0})['v6_memory_lines'] == 0
    document = (ROOT / 'SETTINGS.md').read_text(encoding='utf-8')
    for key in ('v6_memory_chars', 'v6_memory_step_min', 'v6_memory_lines'):
        assert f'`{key}`' in document


# -- the ledger is read, never written -------------------------------------------------------------------------------------------------------------------------------

def test_ledger_gives_a_read_only_copy_of_its_records():
    led = feed(ConversationLedger(), [(1, 'раз', 'два')])
    rows = led.records()
    assert [r.kind for r in rows] == ['user', 'answer'] and isinstance(rows, tuple)
    led.user_final('x', 'три', final_rev=1, at=5.0)
    assert len(rows) == 2 and len(led.records()) == 3


def test_building_the_card_does_not_change_the_ledger():
    led = feed(ConversationLedger(), scene())
    before = led.records()
    V.build_card(led, QUESTION, since=0.0)
    assert led.records() == before


# -- the card: order, budget, lines ---------------------------------------------------------------------------------------------------------------------------------

def sections(card):
    """The positions of the part headers in the card, by name."""
    return {name: card.text.find(head) for name, head in V.HEAD.items() if head in card.text}


def test_parts_stand_in_the_fixed_order_and_lines_carry_time_and_speaker():
    led = feed(ConversationLedger(), scene())
    carry = 'Прошлые разговоры (кратко):\n- 20 ч назад: «вопрос» - ответ'
    card = V.build_card(led, PRICE_Q, since=0.0, pinned=('Тема: поставки', 'Стиль: коротко'), carry=carry)
    at = sections(card)
    assert set(at) == {'pinned', 'exchanges', 'retrieved', 'exact', 'window', 'brief', 'outline', 'carry'}, at      # one-research (U-new-8): the window of the last 15 and its brief after the exact things
    order = ['pinned', 'exchanges', 'retrieved', 'exact', 'window', 'brief', 'outline', 'carry']
    assert [at[k] for k in order] == sorted(at.values())
    assert 'Тема: поставки' in card.text and 'Стиль: коротко' in card.text and '- 20 ч назад' in card.text
    lines = [l for l in card.text.split('\n') if l.startswith('- ')]
    assert any(re.match(r'^- \d+ мин, ' + V.SPEAKER + r': «', l) for l in lines)      # time from the start of the call and who
    assert card.chars == len(card.text) and card.nonempty


def test_the_newest_exchanges_are_verbatim_as_today():
    led = feed(ConversationLedger(), [(10, 'первый вопрос про дождь', 'первый ответ'), (30, 'второй вопрос про снег', 'второй ответ')])
    card = V.build_card(led, 'третий', since=0.0)
    assert V.HEAD['exchanges'] in card.text
    assert 'Вопрос: первый вопрос про дождь\nОтвет: первый ответ\nВопрос: второй вопрос про снег\nОтвет: второй ответ' in card.text
    assert FT.build_request('x', instructions='I', history=[{'question': 'q', 'answer': 'a'}])['instructions'].split('\n\n')[1].startswith(V.HEAD['exchanges'])      # the same heading as the old block


def test_the_question_itself_is_not_an_unanswered_exchange_and_the_answer_in_play_is_not_doubled():
    led = feed(ConversationLedger(), [(10, 'первый вопрос про дождь', 'первый ответ'), (30, 'какая цена', 'не знаю')])
    led.user_final('now', 'а какая цена за штуку', final_rev=1, at=50.0)
    card = V.build_card(led, 'а какая цена за штуку', since=0.0, played=('какая цена', 'не знаю'))
    assert 'Вопрос: какая цена' not in card.text and 'Прозвучало без ответа: а какая цена за штуку' not in card.text
    assert 'Вопрос: первый вопрос про дождь' in card.text


def test_a_condition_said_at_minute_5_is_retrieved_at_minute_46():
    led = feed(ConversationLedger(), scene())
    card = V.build_card(led, QUESTION, since=0.0)
    part = card.part('retrieved')
    assert len(part) <= V.START['lines']
    hit = [l for l in part if 'скидка пять процентов' in l]
    assert hit and hit[0].startswith('- 5 мин, ' + V.SPEAKER + ': «условие такое скидка пять процентов только если заказ больше трёхсот единиц»')
    assert 'скидка пять процентов' not in '\n'.join(card.part('exchanges'))      # the old window could not have had it


def test_retrieval_by_fts5_and_by_the_plain_pass_give_the_same_card(monkeypatch):
    led = feed(ConversationLedger(), scene())
    a = V.build_card(led, QUESTION, since=0.0, fts=True)
    b = V.build_card(led, QUESTION, since=0.0, fts=False)
    assert a.text == b.text and a.ids == b.ids
    for question in (PRICE_Q, 'что там с поставкой оборудования в Казань', 'про погоду и кофе'):
        assert V.build_card(led, question, since=0.0, fts=True).text == V.build_card(led, question, since=0.0, fts=False).text
    monkeypatch.setattr(sqlite3, 'connect', lambda *a, **k: (_ for _ in ()).throw(sqlite3.OperationalError('no fts5')))      # a Python without FTS5
    assert V.build_card(led, QUESTION, since=0.0, fts=True).text == a.text


def test_a_correction_stands_after_the_value_it_corrects():
    """U88, the coordinator's decision of 15.11 (replaces test_a_correction_takes_the_place_of_the_value_it_corrects, whose card hid the old value): the old value and its correction are two lines of the exact things, the
    correction AFTER it, under the heading that says the correction stands; the old value is told nowhere else (retrieved, window, outline), so it never stands alone."""
    led = feed(ConversationLedger(), scene())
    card = V.build_card(led, PRICE_Q, since=0.0)
    lines = card.part('exact')
    old = [i for i, l in enumerate(lines) if 'цена за штуку 500 рублей' in l]
    new = [i for i, l in enumerate(lines) if 'не 500, а 450' in l]
    assert old and new and old[0] < new[0]
    assert lines[old[0]].startswith('- 10 мин, ') and lines[new[0]].startswith('- 12 мин, ')
    assert 'после прежнего' in V.HEAD['exact'] and card.text.index(V.HEAD['exact']) < card.text.index('цена за штуку 500 рублей')
    assert not any('500' in l and '450' not in l for p in ('retrieved', 'window', 'outline') for l in card.part(p))


def test_a_spoken_number_is_exact_too_and_the_patch_does_not_pick_the_right_one():
    rng = random.Random(5)
    led = feed(ConversationLedger(), [(60, 'скидка будет пятьсот рублей', None), (120, 'нет скидка четыреста пятьдесят рублей', None)] + [(300 + 10 * i, sentence(rng), sentence(rng, 3)) for i in range(10)])
    lines = V.build_card(led, 'какая скидка', since=0.0).part('exact')
    assert len(lines) == 2 and 'пятьсот' in lines[0] and 'четыреста пятьдесят' in lines[1]


def test_outline_has_a_line_or_two_per_step_by_rarity_with_times():
    rng = random.Random(3)
    rows, t = [], 30
    while t < 3000:
        rows.append((t, sentence(rng), None))
        t += 15
    rows.append((905, 'экскаватор перфоратор бетономешалка арматура', None))      # rare words in minute 15
    rows.sort()
    led = feed(ConversationLedger(), rows)
    card = V.build_card(led, 'вопрос', since=0.0, budget=6000, step_min=10)
    lines = card.part('outline')
    assert any('экскаватор перфоратор' in l and l.startswith('- 15 мин') for l in lines)
    steps = {}
    for l in lines:
        steps.setdefault(int(re.match(r'- (\d+) мин', l).group(1)) // 10, []).append(l)
    assert len(steps) >= 4 and all(1 <= len(v) <= 2 for v in steps.values())
    assert [int(re.match(r'- (\d+) мин', l).group(1)) for l in lines] == sorted(int(re.match(r'- (\d+) мин', l).group(1)) for l in lines)


def test_the_choice_uses_no_word_list():
    """Rarity inside the call is the only measure: the same words, rare in another call, change the outline."""
    def outline(everywhere):
        rows = [(30 + 15 * i, 'сосед ' + ('озеро мост лес' if everywhere else ('дорога' if i % 2 else 'фильм')) + ' вечер', None) for i in range(90)]      # one-research: 90, not 60, so the rare row stands before the window of the last 15 (in it, it is shown by recency, not by rarity)
        rows[20] = (rows[20][0], 'сосед озеро мост лес вечер' if not everywhere else 'сосед гитара вечер', None)
        return V.build_card(feed(ConversationLedger(), rows), 'вопрос', since=0.0, budget=6000, step_min=15).part('outline')
    assert any('озеро мост лес' in l for l in outline(False))      # rare in this call: chosen
    assert not any('озеро мост лес' in l and '- 5 мин' in l for l in outline(True)) and any('гитара' in l for l in outline(True)) and not any('гитара' in l for l in outline(False))      # the same words everywhere: the rare line is another one


def test_nothing_that_does_not_fit_stays_and_pinned_lines_never_go():
    led = feed(ConversationLedger(), scene())
    pinned = ('Тема: поставки оборудования', 'Стиль: коротко и по делу')
    for budget in (1500, 1800, 2500, 4000, 9000):
        card = V.build_card(led, QUESTION, since=0.0, budget=budget, pinned=pinned)
        assert card.chars == len(card.text) <= budget
        assert all(p in card.text for p in pinned)
    names = ('exchanges', 'retrieved', 'exact', 'outline')
    shown = [[k for k in names if V.build_card(led, PRICE_Q, since=0.0, budget=b, pinned=pinned).part(k)] for b in (1500, 1800, 2500, 4000, 9000)]
    assert all(set(a) <= set(b) for a, b in zip(shown, shown[1:])) and shown[0] and len(shown[-1]) == 4      # a bigger budget only adds, from the top down


def test_a_line_is_never_cut_inside_a_number():
    text = 'заказ на сумму 1 500 рублей и еще ' + 'слово ' * 8 + 'до числа 123456 и 7890 конец'
    for n in range(0, len(text) + 5):
        r = V.fit(text, n)
        assert len(r) <= n or n < 0
        if r and r != text:
            kept = r[:-1].rstrip()
            assert r.endswith('…') and text.startswith(kept) and text[len(kept)] == ' '
            assert not (kept.split()[-1].isdigit() and text[len(kept):].lstrip()[0].isdigit())
    assert V.fit(text, len(text)) == text and V.fit('', 10) == ''


def test_no_number_of_the_card_is_a_piece_of_a_number_of_the_ledger():
    rng = random.Random(1)
    rows = [(10 * i, sentence(rng, 20) + ' сумма %d%d%d%d рублей ' % (1 + i % 9, 5, 0, 0) + sentence(rng, 20), 'ответ %d' % (i * 37 + 1011)) for i in range(120)]
    led = feed(ConversationLedger(), rows)
    whole = set(re.findall(r'\d+', ' '.join(r.text for r in led.records())))

    def body_numbers(text):
        return set(re.findall(r'\d+', '\n'.join(re.sub(r'^- (\d+ ч \d+ мин|\d+ мин), [^:]+: ', '', l) for l in text.split('\n'))))
    for budget in (1500, 2200, 3333, 5000):
        for question in ('сумма рублей', 'сумма 1500', 'про погоду'):
            card = V.build_card(led, question, since=0.0, budget=budget, line_chars=70)
            assert body_numbers(card.text) <= whole, (budget, question)


# -- rebuildable ----------------------------------------------------------------------------------------------------------------------------------------------------

def test_erase_the_projection_rebuild_it_and_the_card_is_the_same():
    led = feed(ConversationLedger(), scene())
    projection = V.Projection(led)
    first = V.build_card(led, QUESTION, since=0.0, projection=projection)
    assert projection.size() > 0
    projection.clear()
    assert projection.size() == 0
    again = V.build_card(led, QUESTION, since=0.0, projection=projection)
    fresh = V.build_card(led, QUESTION, since=0.0)
    assert first.text == again.text == fresh.text and first.ids == again.ids == fresh.ids


def test_the_projection_follows_a_revised_final():
    led = ConversationLedger()
    led.user_final('t1', 'цена за штуку 500 рублей', final_rev=1, at=10.0)
    projection = V.Projection(led)
    assert '500' in V.build_card(led, 'сколько это стоит', since=0.0, projection=projection).text
    led.user_final('t1', 'цена за штуку 450 рублей', final_rev=2, at=10.0)      # the same turn, a newer text replaces the older
    text = V.build_card(led, 'сколько это стоит', since=0.0, projection=projection).text
    assert '450' in text and '500' not in text


def test_a_restart_in_the_middle_of_a_call_gives_the_same_card(tmp_path):
    directory, wall = tmp_path / 'conversation', (lambda: 1_700_000_000.0)
    rows = scene()
    first = ConversationLedger(directory=directory, wall=wall)
    first.open_call(0.0)
    feed(first, rows[:80])
    reference = ConversationLedger()
    feed(reference, rows[:80])
    before = V.build_card(first, QUESTION, since=0.0)
    restarted = ConversationLedger(directory=directory, wall=wall)      # the process restarts: the tail comes back from the day file
    assert len(restarted) == len(first)
    after = V.build_card(restarted, QUESTION, since=0.0)
    assert before.text == after.text == V.build_card(reference, QUESTION, since=0.0).text and before.ids == after.ids
    for led in (restarted, reference):      # and the call goes on on both
        for i, (t, text, answer) in enumerate(rows[80:90], 80):
            led.user_final('t%d' % i, text, final_rev=1, at=float(t))
            led.answer('a%d' % i, answer, tid='t%d' % i, at=float(t) + 2)
    assert V.build_card(restarted, PRICE_Q, since=0.0).text == V.build_card(reference, PRICE_Q, since=0.0).text


def test_records_of_earlier_calls_before_since_are_not_this_calls_memory():
    led = ConversationLedger()
    led.user_final('old', 'вчерашний договор на пятьсот штук', final_rev=1, at=5.0)
    led.user_final('new', 'сегодняшний разговор про погоду', final_rev=1, at=1005.0)
    card = V.build_card(led, 'договор', since=1000.0)
    assert 'вчерашний' not in card.text


# -- bounded: a call of 180 minutes -----------------------------------------------------------------------------------------------------------------------------------

def long_call():
    """180 minutes, one exchange every 3.6 s: 3000 listener finals and 3000 answers = the 6000 records the ledger keeps hot."""
    rng = random.Random(11)
    led = ConversationLedger()
    for i in range(3000):
        t = 3.6 * i
        led.user_final('t%d' % i, ('сумма %d рублей ' % rng.randint(100, 999) if i % 97 == 0 else '') + sentence(rng, 9), final_rev=1, at=t)
        led.answer('a%d' % i, sentence(rng, 5), tid='t%d' % i, at=t + 1.0)
    return led


def test_a_call_of_180_minutes_is_bounded_in_time_and_memory():
    led = long_call()
    assert len(led) == 6000
    import time
    started = time.perf_counter()
    projection = V.Projection(led)
    cold = V.build_card(led, 'сумма рублей погода', since=0.0, projection=projection)
    cold_s = time.perf_counter() - started
    tracemalloc.start()
    _, peak = tracemalloc.get_traced_memory()
    V.build_card(led, 'сумма рублей погода', since=0.0, projection=V.Projection(led))      # the whole build again, under the memory meter
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert cold.chars <= V.START['chars'] and cold.nonempty
    assert cold_s < V.BOUNDS['cold_s'] and peak < V.BOUNDS['peak_mb'] * 2 ** 20, (cold_s, peak)
    led.user_final('tx', 'ещё одна фраза про озеро', final_rev=1, at=3.6 * 3000)
    started = time.perf_counter()
    V.build_card(led, 'озеро', since=0.0, projection=projection)
    assert time.perf_counter() - started < V.BOUNDS['warm_s']
    assert projection.size() <= V.BOUNDS['rows']


def test_the_projection_holds_at_most_the_ledger_rows_and_clipped_text():
    led = ConversationLedger()
    led.user_final('big', 'слово ' * 5000, final_rev=1, at=1.0)
    projection = V.Projection(led)
    V.build_card(led, 'слово', since=0.0, projection=projection)
    assert max(len(u.text) for u in projection.rows()) <= V.START['index_chars']


# -- the three modes at the one point of FastText._start --------------------------------------------------------------------------------------------------------------

class Controller:
    def __init__(self, led, began=0.0):
        self.convo, self.call_began = led, began


def fast_text(history=(), carry='', **keywords):
    seen = []
    fast = FT.FastText(lambda request, cancelled: iter(()), instructions=lambda *a: 'POLICY', history=lambda: list(history), clock=lambda: 100.0, wake=lambda: None,
                       report=lambda ev, **f: seen.append((ev, f)), **keywords)
    if carry:
        fast.carry = lambda: carry
    return fast, seen


HISTORY = [{'question': 'какой срок', 'answer': 'десять дней'}, {'question': 'кто платит', 'answer': 'покупатель'}]


def off_request():
    """The request the OLD code builds for a fixed scene: the golden file is that, captured before the slice existed."""
    fast, _ = fast_text(history=HISTORY, carry='Прошлые разговоры (кратко):\n- 3 ч назад: «вопрос» - ответ')
    job = fast._start('какая скидка', material='')
    return job.request


def hooked(mode, led, history=HISTORY, carry='Прошлые разговоры (кратко):\n- 3 ч назад: «вопрос» - ответ', **settings):
    fast, seen = fast_text(history=history, carry=carry)
    memory = V.attach({**settings}, Controller(led), note=lambda ev, **f: seen.append((ev, f)), timer=iter([0.0, 0.004] * 100).__next__)
    fast.card = memory.apply
    return fast, seen, memory


def test_on_puts_the_card_in_place_of_the_old_blocks():
    led = feed(ConversationLedger(), scene())
    fast, seen, _ = hooked('on', led)
    request = fast._start('какая скидка по условию про заказ').request
    instructions = request['instructions']
    assert instructions.startswith('POLICY\n\n') and V.HEAD['exchanges'] in instructions and 'скидка пять процентов' in instructions
    assert 'Ранее в этом разговоре:' not in instructions          # the old recap is replaced
    assert 'Прошлые разговоры (кратко):\n- 3 ч назад: «вопрос» - ответ' in instructions      # the carry stands at the bottom of the card
    assert instructions.count(V.HEAD['exchanges']) == 1            # and the old history block is gone: the card holds the exchanges
    assert request['input'][-1]['content'][0]['text'] == 'какая скидка по условию про заказ'
    assert [f for ev, f in seen if ev == 'memory_card'][-1]['mode'] == 'on'


def test_on_with_an_empty_card_leaves_the_old_request():
    fast, seen, _ = hooked('on', ConversationLedger())
    assert fast._start('какая скидка').request == off_request()


def test_an_exception_falls_back_to_the_old_behaviour_with_one_journal_line():
    class Broken(ConversationLedger):
        def records(self):
            raise RuntimeError('boom')
    for mode in ('shadow', 'on'):
        fast, seen, _ = hooked(mode, Broken())
        assert fast._start('какая скидка').request == off_request()
        failed = [f for ev, f in seen if ev == 'memory_card_fail']
        assert len(failed) == 1 and failed[0]['error'] == 'RuntimeError' and 'boom' not in json.dumps(failed[0])


def test_a_controller_without_a_ledger_changes_nothing():
    fast, seen, _ = hooked('on', None)
    assert fast._start('какая скидка').request == off_request() and not [1 for ev, _ in seen if ev.startswith('memory_card')]


def test_the_numbers_come_from_the_settings():
    led = feed(ConversationLedger(), scene())
    fast, seen, memory = hooked('on', led, v6_memory_chars=1800, v6_memory_lines=2, v6_memory_step_min=20)
    request = fast._start('какая скидка по условию про заказ').request
    assert len(request['instructions']) - len('POLICY\n\n') <= 1800
    note = [f for ev, f in seen if ev == 'memory_card'][-1]
    assert note['budget'] == 1800 and note['parts']['retrieved'] <= 2


def test_the_one_hook_is_in_fast_text_and_the_host_attaches_it():
    text = (ROOT / 'echo_sync' / 'fast_text.py').read_text(encoding='utf-8')
    assert text.count('self.card(') == 1 and text.index('self.card(') < text.index('played = self._played()')
    host = (ROOT / 'echo_sync' / 'controlled_host.py').read_text(encoding='utf-8')
    assert 'v6_memory.attach(' in host


# -- incremental: an append is not a rebuild; erase and rebuild stays the same ------------------------------------------------------------------------------------

def _state(projection):
    return (projection.rows(), projection.pairs(), projection._inv, projection._total, projection._now, projection._start, projection.rarity())


def _count_rebuilds(monkeypatch, target):
    calls = []
    real = V.Projection._rebuild
    monkeypatch.setattr(V.Projection, '_rebuild', lambda self, *a, **k: (calls.append(1) if self is target else None, real(self, *a, **k))[1])
    return calls


def test_appending_finals_and_answers_does_not_rebuild_the_projection(monkeypatch):
    led = feed(ConversationLedger(), scene())
    projection = V.Projection(led)
    V.build_card(led, QUESTION, since=0.0, projection=projection)
    calls = _count_rebuilds(monkeypatch, projection)
    for k in range(12):
        led.user_final('x%d' % k, 'новая реплика про цену за штуку %d рублей' % k, final_rev=1, at=5000.0 + 3 * k)
        led.answer('xa%d' % k, 'ответ номер %d' % k, tid='x%d' % k, at=5001.0 + 3 * k)
        incremental = V.build_card(led, 'какая цена за штуку', since=0.0, projection=projection)
        assert incremental.text == V.build_card(led, 'какая цена за штуку', since=0.0).text
    assert calls == []
    fresh = V.Projection(led)
    fresh.refresh(0.0)
    assert _state(projection) == _state(fresh)


def test_the_incremental_projection_equals_a_fresh_one_with_fts_and_without():
    for fts in (True, False):
        led = feed(ConversationLedger(), scene())
        projection = V.Projection(led, fts=fts)
        V.build_card(led, QUESTION, since=0.0, projection=projection, fts=fts)
        rng = random.Random(5)
        for k in range(25):
            led.user_final('y%d' % k, sentence(rng) + (' цена %d рублей' % (100 + k) if k % 3 == 0 else ''), final_rev=1, at=6000.0 + 4 * k)
            if k % 2 == 0:
                led.answer('ya%d' % k, sentence(rng, 4), tid='y%d' % k, at=6001.0 + 4 * k)
            if k == 7:
                led.user_final('y8x', 'то же самое слово в слово ' + str(k), final_rev=1, at=6029.0)
                led.user_final('y8y', 'то же самое слово в слово ' + str(k), final_rev=1, at=6030.0)      # the same words under a new id: one utterance
            got = V.build_card(led, 'какая цена', since=0.0, projection=projection, fts=fts)
            want = V.build_card(led, 'какая цена', since=0.0, fts=fts)
            assert got.text == want.text and got.ids == want.ids, (fts, k)
        fresh = V.Projection(led, fts=fts)
        fresh.refresh(0.0)
        assert _state(projection) == _state(fresh)


def test_what_is_not_an_append_still_rebuilds_and_stays_right(monkeypatch):
    led = ConversationLedger()
    led.user_final('a', 'первая реплика про цену 500', final_rev=1, at=10.0)
    led.answer('aa', 'ответ один', tid='a', at=11.0)
    led.user_final('b', 'вторая реплика про сроки', final_rev=1, at=20.0)
    projection = V.Projection(led)
    V.build_card(led, 'цена', since=0.0, projection=projection)
    calls = _count_rebuilds(monkeypatch, projection)
    led.user_final('a', 'первая реплика про цену 450', final_rev=2, at=10.0)         # a revised final
    assert '450' in V.build_card(led, 'цена', since=0.0, projection=projection).text
    led.user_final('c', 'реплика сказанная раньше но доставленная позже', final_rev=1, at=15.0)         # delivered late: the spoken order changes
    got = V.build_card(led, 'цена', since=0.0, projection=projection)
    assert got.text == V.build_card(led, 'цена', since=0.0).text and [r.tid for r in projection.rows()] == ['a', 'c', 'b']
    led.answer('ab2', 'новый ответ', tid='a', supersedes='aa', at=30.0)      # a superseded answer
    got = V.build_card(led, 'цена', since=0.0, projection=projection)
    assert got.text == V.build_card(led, 'цена', since=0.0).text and len(projection.pairs()) == 1
    assert len(calls) == 3
    V.build_card(led, 'цена', since=1000.0, projection=projection)         # another start of the call
    assert len(calls) == 4


def test_a_full_ledger_that_drops_its_oldest_records_stays_right():
    led = ConversationLedger(hot=60)
    projection = V.Projection(led)
    for i in range(200):
        led.user_final('t%d' % i, 'слово%d другое%d цена %d' % (i, i, i), final_rev=1, at=float(i))
        if i % 3 == 0:
            led.answer('a%d' % i, 'ответ %d' % i, tid='t%d' % i, at=i + 0.5)
        got = V.build_card(led, 'слово цена', since=0.0, projection=projection)
        assert got.text == V.build_card(led, 'слово цена', since=0.0).text, i
    fresh = V.Projection(led)
    fresh.refresh(0.0)
    assert _state(projection) == _state(fresh) and projection.size() <= 60


def test_erase_after_incremental_updates_gives_the_same_card():
    led = feed(ConversationLedger(), scene())
    projection = V.Projection(led)
    V.build_card(led, QUESTION, since=0.0, projection=projection)
    for k in range(6):
        led.user_final('z%d' % k, 'ещё одна реплика про сумму %d рублей' % (1000 + k), final_rev=1, at=7000.0 + k)
        led.answer('za%d' % k, 'принято %d' % k, tid='z%d' % k, at=7000.5 + k)
        V.build_card(led, 'сумма рублей', since=0.0, projection=projection)
    before = V.build_card(led, 'сумма рублей', since=0.0, projection=projection)
    projection.clear()
    assert projection.size() == 0
    after = V.build_card(led, 'сумма рублей', since=0.0, projection=projection)
    assert before.text == after.text and before.ids == after.ids
