"""V6 memory slice, the independent attack (echo_sync/v6_memory.py). Written by someone who did not write the patch; the code is not edited here.
Classes of variants: (a) the outcome must NOT change (tempo, timing, fillers, a recogniser slip in an unimportant word, other words, order and duplicates of delivery, restart),
(b) the outcome MUST change (another number, a negation, a correction, another topic); then growth, budget, off/shadow, poison, failure, files, text leaks, threads.
Known limits that the patch names itself (no speaker in the ledger, no synonyms) are strict xfail: they document the limit and do not count as defects."""
import builtins
import itertools
import json
import logging
import random
import re
import sqlite3
import threading
import time
import tracemalloc

import pytest

from echo_sync import fast_text as FT
from echo_sync import v6_memory as V
from echo_sync.conversation_ledger import ConversationLedger

VOCAB = ('погода кофе прогулка дорога фильм музыка вечер сосед собака велосипед завтрак озеро поезд гитара ветер мост лес сад окно книга чай река гора поле город дождь снег лето осень '
         'зима весна кино театр рынок площадь улица двор крыша лестница').split()
COND = 'условие такое скидка пять процентов только если заказ больше трёхсот единиц'
Q = 'напомни какая скидка по условию про заказ'


def chatter(rng, n=None):
    return ' '.join(rng.choice(VOCAB) for _ in range(n or rng.randint(5, 8)))


def rows_of(seed=3, minutes=47, extra=(), cond=COND, cond_at=300):
    """(second, text, answer): the condition at ``cond_at``, chatter every 12 s to ``minutes``; ``extra`` rows are added."""
    rng = random.Random(seed)
    out = [(60, 'давайте обсудим поставку оборудования для склада в Казани', 'Хорошо.'), (cond_at, cond, 'Понял.'), (1200, 'цену доставки отдельно договоримся позже', 'Хорошо.')]
    out += list(extra)
    t = 800
    while t < minutes * 60:
        out.append((t, chatter(rng), chatter(rng, 4)))
        t += 12
    return sorted(out)


def feed(led, rows, order=None, dup=False):
    rows = list(rows)
    idx = list(range(len(rows)))
    if order is not None:
        idx = order
    for i in idx:
        t, text, answer = rows[i]
        for _ in range(2 if dup else 1):
            led.user_final('t%d' % i, text, final_rev=1, at=float(t))
        if answer:
            led.answer('a%d' % i, answer, tid='t%d' % i, at=float(t) + 2)
    return led


def card(rows, question=Q, since=0.0, **kw):
    return V.build_card(feed(ConversationLedger(), rows), question, since=since, **kw)


def found(c, needle, parts=('retrieved', 'exact', 'exchanges')):
    return any(needle in l for p in parts for l in c.lines.get(p, ()))


def minutes_of(lines):
    out = []
    for l in lines:
        m = re.match(r'^- (?:(\d+) ч )?(\d+) мин', l)
        if m:
            out.append(int(m.group(1) or 0) * 60 + int(m.group(2)))
    return out


# ---------------------------------------------------------------- (a) a condition said at minute 5 is in the card at minute 47, under variants that change nothing

@pytest.mark.parametrize('scale', [0.1, 0.25, 0.5, 1.0, 2.0, 4.0])
@pytest.mark.parametrize('offset', [0.0, 1000.0, 86400.0])
def test_a_other_tempo_and_timing_keep_the_condition(scale, offset):
    rows = [(offset + t * scale, x, a) for t, x, a in rows_of()]
    c = V.build_card(feed(ConversationLedger(), rows), Q, since=offset)
    assert found(c, 'скидка пять процентов'), (scale, offset, c.text)


FILLERS = ['э-э', 'ну', 'значит', 'вот', 'короче', 'ммм', 'так', 'слушай', 'пожалуйста', 'а']


@pytest.mark.parametrize('seed', range(12))
def test_a_fillers_in_the_question_keep_the_condition(seed):
    rng = random.Random(seed)
    words = Q.split()
    for _ in range(rng.randint(1, 4)):
        words.insert(rng.randint(0, len(words)), rng.choice(FILLERS))
    c = card(rows_of(), ' '.join(words))
    assert found(c, 'скидка пять процентов'), (words, c.text)


@pytest.mark.parametrize('question', ['какая будет скидка по этому условию', 'сколько процентов скидки по условию про заказ', 'скидку по условию заказа напомни',
                                      'а скидки какие условия', 'СКИДКА по условию?', 'скидка!!! по условию... про заказ???', 'какой процент скидки при заказе'])
def test_a_the_same_thing_in_other_forms_of_words_in_the_question(question):
    assert found(card(rows_of(), question), 'скидка пять процентов'), question


@pytest.mark.parametrize('slip', [('такое', 'такой'), ('только', 'толко'), ('больше', 'болше'), ('единиц', 'единица'), ('если', 'есль'), ('условие', 'условия')])
def test_a_a_recogniser_slip_in_an_unimportant_word_of_the_stored_words(slip):
    cond = COND.replace(*slip)
    c = card(rows_of(cond=cond))
    assert found(c, 'скидка'), (slip, c.text)


@pytest.mark.parametrize('slip', [('напомни', 'напомней'), ('какая', 'какой'), ('про', 'при'), ('по', 'на'), ('условию', 'условии')])
def test_a_a_recogniser_slip_in_an_unimportant_word_of_the_question(slip):
    assert found(card(rows_of(), Q.replace(*slip)), 'скидка пять процентов'), slip


@pytest.mark.parametrize('minutes', [10, 20, 40, 90, 180])
def test_a_the_condition_survives_any_call_length(minutes):
    assert found(card(rows_of(minutes=minutes)), 'скидка пять процентов'), minutes


def test_a_the_condition_in_a_long_utterance_after_400_characters_is_not_lost():
    """index_chars=400 clips an utterance before the index and before the numbers are read: a long spoken paragraph loses its tail, and a condition in the tail is gone for good."""
    tail = 'условие такое скидка пять процентов только если заказ больше трёхсот единиц'
    long = ' '.join(['мы обсуждали поставку и график машин на складе'] * 12) + ' ' + tail
    assert len(long) > 500
    c = card(rows_of(cond=long))
    assert found(c, 'трёхсот') or found(c, 'пять процентов'), c.text


def test_a_a_number_at_the_end_of_a_long_utterance_is_an_exact_thing():
    long = ' '.join(['мы обсуждали поставку и график машин на складе'] * 12) + ' итого цена за штуку 777 рублей'
    c = card(rows_of(extra=[(500, long, 'Ок.')]), 'какая цена за штуку')
    assert found(c, '777'), c.text


# ---------------------------------------------------------------- (a) order and duplicates of delivery, (b) corrections

def corrections(values=(500, 450, 430, 410), start=600, same_words=True):
    ex = []
    for k, v in enumerate(values):
        pre = ['цена за штуку', 'нет не так цена за штуку теперь', 'ой ещё раз цена за штуку', 'окончательно цена за штуку'][k % 4]
        ex.append((start + 60 * k, ('%s %d рублей' % (pre, v)) if same_words else ('нет %d' % v if k else 'цена %d' % v), 'Записал.'))
    return ex


def exact_values(c):
    out = []
    for l in c.lines['exact'] + c.lines['retrieved']:
        for m in re.findall(r'\b(\d{3})\b', l):
            if m not in out:
                out.append(m)
    return out


@pytest.mark.parametrize('values', [(500, 450, 430, 410), (900, 800, 700), (120, 130, 140, 150, 160)])
def test_b_a_number_corrected_several_times_all_values_in_spoken_order(values):
    c = card(rows_of(extra=corrections(values)), 'какая цена за штуку')
    assert [int(v) for v in exact_values(c) if int(v) in values] == list(values), c.text


@pytest.mark.parametrize('seed', range(8))
def test_a_reordered_delivery_of_ledger_entries_keeps_the_spoken_order(seed):
    rows = rows_of(extra=corrections())
    order = list(range(len(rows)))
    random.Random(seed).shuffle(order)
    led = feed(ConversationLedger(), rows, order=order)
    c = V.build_card(led, 'какая цена за штуку', since=0.0)
    vals = [int(v) for v in exact_values(c) if int(v) in (500, 450, 430, 410)]
    assert vals == [500, 450, 430, 410], (seed, c.text)
    for part in ('retrieved', 'exact', 'outline'):
        m = minutes_of(c.lines[part])
        assert m == sorted(m), (seed, part, m)


def test_a_reordered_delivery_does_not_change_the_card_of_the_in_order_delivery():
    rows = rows_of(extra=corrections())
    base = V.build_card(feed(ConversationLedger(), rows), 'какая цена за штуку', since=0.0)
    for seed in range(5):
        order = list(range(len(rows)))
        random.Random(seed).shuffle(order)
        got = V.build_card(feed(ConversationLedger(), rows, order=order), 'какая цена за штуку', since=0.0)
        for part in ('retrieved', 'exact', 'outline'):
            assert got.lines[part] == base.lines[part], (seed, part)


def test_a_duplicate_delivery_same_tid_and_revision_changes_nothing():
    rows = rows_of(extra=corrections())
    a = V.build_card(feed(ConversationLedger(), rows), 'какая цена за штуку', since=0.0)
    b = V.build_card(feed(ConversationLedger(), rows, dup=True), 'какая цена за штуку', since=0.0)
    assert a.text == b.text


def test_a_duplicate_delivery_under_a_new_tid_does_not_eat_the_budget_twice():
    """The recogniser provider re-sends a final under a new id (a reconnect): the same words twice must not stand twice in the card."""
    rows = rows_of(extra=corrections())
    led = feed(ConversationLedger(), rows)
    for i, (t, x, a) in enumerate(rows):
        if 'цена за штуку' in x:
            led.user_final('dup%d' % i, x, final_rev=1, at=float(t) + 0.5)
    c = V.build_card(led, 'какая цена за штуку', since=0.0)
    lines = [l.split(': ', 1)[1] for p in ('retrieved', 'exact') for l in c.lines[p]]
    assert len(lines) == len(set(lines)), lines


@pytest.mark.parametrize('a,b', [('450', '460'), ('450', '45'), ('двадцать пять', 'двадцать шесть'), ('3 июля', '4 июля')])
def test_b_another_number_changes_the_card(a, b):
    ca = card(rows_of(extra=[(600, 'цена за штуку %s рублей' % a, 'Ок.')]), 'какая цена за штуку')
    cb = card(rows_of(extra=[(600, 'цена за штуку %s рублей' % b, 'Ок.')]), 'какая цена за штуку')
    assert ca.text != cb.text and found(ca, a) and found(cb, b)


@pytest.mark.parametrize('pos,neg', [('скидка будет', 'скидки не будет'), ('мы согласны на цену', 'мы не согласны на цену')])
def test_b_a_negation_changes_the_card(pos, neg):
    ca = card(rows_of(extra=[(600, pos + ' по заказу', 'Ок.')]), 'что с заказом')
    cb = card(rows_of(extra=[(600, neg + ' по заказу', 'Ок.')]), 'что с заказом')
    assert ca.text != cb.text and found(cb, ' не ')


def test_b_another_topic_leaves_the_condition_out_of_retrieval():
    for q in ['что с доставкой', 'как погода в Казани', 'когда приедет машина на склад']:
        c = card(rows_of(), q)
        assert not found(c, 'скидка пять процентов', ('retrieved', 'exact')), (q, c.lines['retrieved'], c.lines['exact'])


def test_b_the_question_about_another_topic_finds_that_topic():
    c = card(rows_of(), 'что с доставкой')
    assert found(c, 'цену доставки'), c.text


# ---------------------------------------------------------------- the outline: «что он говорил полчаса назад»

@pytest.mark.parametrize('minutes', [10, 15, 30, 45, 60, 90, 120, 150, 180])
def test_the_outline_covers_half_an_hour_ago(minutes):
    rows = rows_of(minutes=minutes)
    c = card(rows, 'что он говорил полчаса назад')
    now = rows[-1][0] / 60.0
    target = now - 30
    if target < 14:
        pytest.skip('before the chatter starts')
    got = minutes_of(c.lines['outline'] + c.lines['retrieved'] + c.lines['exact'] + c.lines['exchanges'])
    step = V.START['step_min']
    assert any(abs(m - target) <= step for m in got), (minutes, target, got)


@pytest.mark.parametrize('minutes', [20, 60, 120, 180])
def test_the_outline_spans_the_call_from_start_to_end(minutes):
    c = card(rows_of(minutes=minutes), 'что было')
    m = minutes_of(c.lines['outline'])
    assert m and max(m) >= 0.5 * minutes and min(m) <= 0.3 * minutes + 15, (minutes, m)


# ---------------------------------------------------------------- speakers, numerals, unicode

@pytest.mark.xfail(strict=True, reason='known limit named by the patch: the ledger has no speaker, every line says «в комнате»')
def test_limit_two_speakers_are_told_apart():
    led = ConversationLedger()
    led.user_final('a1', 'цена за штуку 500 рублей', final_rev=1, at=100.0)
    led.user_final('b1', 'цена за штуку 450 рублей', final_rev=1, at=130.0)
    c = V.build_card(led, 'какая цена за штуку', since=0.0)
    labels = {re.match(r'^- \d+ мин, ([^:]+):', l).group(1) for l in c.lines['retrieved'] + c.lines['exact']}
    assert len(labels) == 2


@pytest.mark.xfail(strict=True, reason='known limit: retrieval is by stems of words, a synonym shares no stem with the stored words')
def test_limit_a_synonym_in_the_question_finds_the_condition():
    assert found(card(rows_of(), 'сколько уступят за крупную партию'), 'скидка пять процентов')


def test_numerals_in_words_versus_digits_retrieval_limit_written_down():
    """Spoken «двадцать пять» is stored as words; the question has «25». Honest check of both directions; a failure is written in the note as a limit."""
    spoken = card(rows_of(extra=[(600, 'вес партии двадцать пять тонн', 'Ок.')]), 'сколько весит партия 25 тонн')
    digits = card(rows_of(extra=[(600, 'вес партии 25 тонн', 'Ок.')]), 'сколько весит партия двадцать пять тонн')
    assert found(spoken, 'двадцать пять') and found(digits, '25')      # found by the common words «вес партии тонн»
    only = card(rows_of(extra=[(600, 'двадцать пять', 'Ок.')]), 'а точно 25')
    only2 = card(rows_of(extra=[(600, '25', 'Ок.')]), 'а точно двадцать пять')
    assert found(only, 'двадцать пять') and found(only2, '25'), (only.lines['exact'], only2.lines['exact'])


@pytest.mark.parametrize('stored,asked', [('всё решили на четверг', 'что решили на четверг, все?'), ('ёлка стоит дорого', 'сколько стоит елка'), ('елка стоит дорого', 'сколько стоит ёлка'),
                                          ('Ёжик купил Ёлку', 'кто купил елку'), ('ВСЁ ПО ЗАКАЗУ ГОТОВО', 'что готово по заказу')])
def test_a_yo_and_ye_and_case(stored, asked):
    assert found(card(rows_of(extra=[(600, stored, 'Ок.')]), asked), stored), (stored, asked)


@pytest.mark.parametrize('variant', [' ', '​', ' ', '\t', '  '])
def test_a_odd_spaces_inside_the_stored_words(variant):
    text = 'договор подписан в среду'.replace(' ', variant) if variant != '​' else 'дого​вор подписан в среду'
    assert found(card(rows_of(extra=[(600, text, 'Ок.')]), 'когда подписан договор'), 'подписан'), repr(variant)


def test_a_nfd_form_of_a_letter_is_found():
    import unicodedata
    text = unicodedata.normalize('NFD', 'договор подписан в чётверг')
    assert found(card(rows_of(extra=[(600, text, 'Ок.')]), 'когда подписан договор'), 'подписан')


# ---------------------------------------------------------------- FTS5 and query syntax

class NoFts:
    """sqlite3 without FTS5: creating the virtual table fails like «no such module: fts5»."""
    Error = sqlite3.Error

    @staticmethod
    def connect(*a, **k):
        real = sqlite3.connect(*a, **k)

        class W:
            def execute(self, sql, *args):
                if 'fts5' in sql.lower():
                    raise sqlite3.OperationalError('no such module: fts5')
                return real.execute(sql, *args)

            def __getattr__(self, name):
                return getattr(real, name)
        return W()


def test_fts5_missing_gives_the_same_card(monkeypatch):
    rows = rows_of(extra=corrections())
    good = card(rows, 'какая цена за штуку')
    monkeypatch.setattr(V, 'sqlite3', NoFts)
    bad = card(rows, 'какая цена за штуку')
    assert bad.text == good.text


def test_fts5_missing_midway_degrades_and_stays_degraded(monkeypatch):
    led = feed(ConversationLedger(), rows_of(extra=corrections()))
    proj = V.Projection(led)
    base = V.build_card(led, 'какая цена за штуку', since=0.0, projection=proj)
    monkeypatch.setattr(V, 'sqlite3', NoFts)
    led.user_final('zz', 'ещё слово про цену за штуку 400', final_rev=1, at=3000.0)
    got = V.build_card(led, 'какая цена за штуку', since=0.0, projection=proj)
    assert got.chars > 0 and found(got, '400')


SYNTAX = ['" OR ""', 'NEAR(цена скидка, 2)', 'цена* OR скидка', '"цена', "цена' --", 'цена AND NOT скидка', '^цена : скидка', '{цена скидка}', 'цена-скидка', '(((цена', 'цена)))', 'col:цена', '*', '"', "'", '-', 'OR', 'AND', 'NOT', 'NEAR',
          'a b c d e', '%s', '\\', '\x00цена', 'цена\x00скидка', ';DROP TABLE d;--']


@pytest.mark.parametrize('syntax', SYNTAX)
def test_fts_query_syntax_in_the_question_cannot_crash_or_inject(syntax):
    rows = rows_of(extra=corrections())
    a = card(rows, 'какая %s цена за штуку' % syntax)
    b = card(rows, 'какая %s цена за штуку' % syntax, fts=False)
    assert a.text == b.text and a.chars <= V.START['chars']


@pytest.mark.parametrize('syntax', SYNTAX)
def test_fts_query_syntax_in_the_spoken_text_cannot_crash_or_change_other_lines(syntax):
    rows = rows_of(extra=corrections() + [(700, 'сказал %s и всё' % syntax, 'Ок.')])
    a = card(rows, 'какая цена за штуку')
    b = card(rows, 'какая цена за штуку', fts=False)
    assert a.text == b.text and found(a, '450')


def test_fts_and_plain_pass_agree_on_random_scenes():
    bad = 0
    for seed in range(25):
        rng = random.Random(seed)
        extra = [(rng.randint(100, 2000), ' '.join(rng.choice(['цена', 'скидка', 'заказ', 'штука', 'доставка', '300', '450']) for _ in range(rng.randint(2, 7))), 'Ок.') for _ in range(rng.randint(3, 25))]
        rows = rows_of(seed=seed, extra=extra)
        q = ' '.join(rng.choice(['цена', 'скидка', 'заказ', 'штука', 'доставка', 'погода']) for _ in range(rng.randint(1, 4)))
        bad += card(rows, q).text != card(rows, q, fts=False).text
    assert bad == 0, bad


# ---------------------------------------------------------------- budget

@pytest.mark.parametrize('budget', [1, 5, 20, 60, 100, 200, 400, 800, 1500, 4000])
def test_budget_is_never_exceeded_with_pinned_lines(budget):
    pins = ('Тема: поставки оборудования ' + 'очень длинная строка ' * 30, 'Слушатели: ' + 'х' * 400, 'Стиль: коротко')
    c = card(rows_of(extra=corrections()), 'какая цена за штуку', budget=budget, pinned=pins, carry='Прошлые разговоры (кратко):\n- 3 ч назад: «вопрос» - ответ')
    assert c.chars == len(c.text) <= budget, (budget, c.chars)


@pytest.mark.parametrize('budget', [1, 30, 100, 300, 1500, 4000])
@pytest.mark.parametrize('kind', ['spaced', 'nospace', 'digits'])
def test_budget_with_very_long_utterances(budget, kind):
    text = {'spaced': 'скидка цена заказ ' * 800, 'nospace': 'цена' * 3000, 'digits': ' '.join(str(10 ** 6 + i) for i in range(900))}[kind]
    rows = rows_of(extra=[(600 + 5 * i, text, text) for i in range(8)])
    c = card(rows, 'какая цена и скидка по заказу', budget=budget)
    assert len(c.text) <= budget, (kind, budget, len(c.text))


def test_budget_smaller_than_one_line_gives_an_empty_or_whole_lines_never_a_broken_line():
    c = card(rows_of(extra=corrections()), 'какая цена за штуку', budget=60)
    assert len(c.text) <= 60
    for l in c.text.split('\n'):
        assert l == '' or l.endswith(':') or l.startswith(('Вопрос', 'Ответ', '- ', 'Прозвучало')) or len(l) < 60


@pytest.mark.parametrize('budget', [-5, 0, None])
def test_budget_odd_values_from_the_settings(budget):
    c = card(rows_of(), Q, budget=budget)
    assert c.chars <= V.START['chars']


def test_budget_on_mode_total_growth_of_the_request_is_the_budget_at_most():
    led = feed(ConversationLedger(), rows_of(extra=corrections()))
    fast, _, memory = hooked('on', led, v6_memory_chars=1500)
    base = hooked('off', led)[0]
    request = fast._start('какая цена за штуку').request
    old = base._start('какая цена за штуку').request
    assert len(request['instructions']) - len(old['instructions']) <= 1500 + 2 + 1


# ---------------------------------------------------------------- the three modes at the hook

class Controller:
    def __init__(self, led, began=0.0):
        self.convo, self.call_began = led, began


def fast_text(history=(), carry=''):
    seen = []
    fast = FT.FastText(lambda request, cancelled: iter(()), instructions=lambda *a: 'POLICY', history=lambda: list(history), clock=lambda: 100.0, wake=lambda: None, report=lambda ev, **f: seen.append((ev, f)))
    if carry:
        fast.carry = lambda: carry
    return fast, seen


HISTORY = [{'question': 'какой срок', 'answer': 'десять дней'}, {'question': 'кто платит', 'answer': 'покупатель'}]
CARRY = 'Прошлые разговоры (кратко):\n- 3 ч назад: «вопрос» - ответ'


def hooked(mode, led, controller=None, **settings):
    fast, seen = fast_text(history=HISTORY, carry=CARRY)
    memory = V.attach({'v6_memory': mode, **settings}, controller or Controller(led), note=lambda ev, **f: seen.append((ev, f)), timer=iter([0.0, 0.004] * 1000).__next__)
    if memory:
        fast.card = memory.apply
    return fast, seen, memory


def test_shadow_does_not_touch_the_ledger_and_the_old_state():
    led = feed(ConversationLedger(), rows_of(extra=corrections()))
    before = led.records()
    for q in (Q, 'цена'):
        hooked('shadow', led)[0]._start(q)
        hooked('on', led)[0]._start(q)
    assert led.records() == before and len(led) == len(before)


def test_shadow_note_is_bounded_whatever_the_call():
    led = feed(ConversationLedger(), rows_of(minutes=180, extra=corrections()))
    fast, seen, _ = hooked('shadow', led)
    fast._start(Q)
    note = [f for ev, f in seen if ev == 'memory_card'][0]
    assert len(json.dumps(note, ensure_ascii=False)) < 2500


def test_no_utterance_text_goes_to_the_logger(caplog):
    led = feed(ConversationLedger(), rows_of(extra=corrections()))
    with caplog.at_level(logging.DEBUG):
        for mode in ('shadow', 'on'):
            hooked(mode, led)[0]._start('какая цена за штуку')
    assert 'цена за штуку' not in caplog.text and 'скидка' not in caplog.text


# ---------------------------------------------------------------- failure: the call is never broken, the trace is left

def _fail_cases():
    def records(m): m.setattr(ConversationLedger, 'records', lambda self: (_ for _ in ()).throw(RuntimeError('boom')))
    def assemble(m): m.setattr(V, '_assemble', lambda *a, **k: 1 / 0)
    def refresh(m): m.setattr(V.Projection, 'refresh', lambda *a, **k: (_ for _ in ()).throw(KeyError('x')))
    def fit(m): m.setattr(V, 'fit', lambda *a, **k: [][1])
    def outline(m): m.setattr(V, '_outline', lambda *a, **k: [][0])
    def exact(m): m.setattr(V, '_exact', lambda *a, **k: int('x'))
    def atoms(m): m.setattr(V, '_atoms', lambda *a, **k: (_ for _ in ()).throw(ImportError('pymorphy')))
    def fts(m): m.setattr(V.Projection, '_scores_fts', lambda *a, **k: (_ for _ in ()).throw(MemoryError()))
    return [records, assemble, refresh, fit, outline, exact, atoms, fts]


@pytest.mark.parametrize('case', _fail_cases(), ids=lambda f: f.__name__)
@pytest.mark.parametrize('mode', ['shadow', 'on'])
def test_an_exception_inside_degrades_to_the_old_request_and_leaves_a_trace(case, mode, monkeypatch):
    led = feed(ConversationLedger(), rows_of(extra=corrections()))
    plain = fast_text(history=HISTORY, carry=CARRY)[0]._start(Q).request
    fast, seen, _ = hooked(mode, led)
    case(monkeypatch)
    request = fast._start(Q).request
    assert request == plain
    assert [f for ev, f in seen if ev == 'memory_card_fail'], seen


@pytest.mark.parametrize('what', ['pinned', 'carry', 'note', 'timer'])
def test_a_failing_neighbour_never_breaks_the_call(what):
    led = feed(ConversationLedger(), rows_of(extra=corrections()))
    fast, seen = fast_text(history=HISTORY, carry=CARRY)
    boom = lambda *a, **k: 1 / 0     # noqa: E731
    kw = {'pinned': dict(pinned=boom), 'note': dict(note=boom), 'timer': dict(timer=boom)}.get(what, {})
    memory = V.attach({'v6_memory': 'on'}, Controller(led), **kw)
    if what == 'carry': fast.carry = boom
    fast.card = memory.apply
    assert fast._start(Q).request['input'][-1]['content'][0]['text'] == Q


def test_one_poison_record_does_not_switch_the_memory_off_for_the_rest_of_the_call():
    """A record with an impossible time (nan, inf, a huge number) is in the ledger: the card of every later request must still hold the real condition."""
    for bad in (float('nan'), float('inf'), -float('inf'), 1e300, -1e300):
        led = feed(ConversationLedger(), rows_of(extra=corrections()))
        led.user_final('poison', 'цена за штуку 999 рублей', final_rev=1, at=bad)
        try:
            c = V.build_card(led, 'какая цена за штуку', since=0.0)
        except Exception as e:      # noqa: BLE001
            pytest.fail('build_card raised %r for at=%r: from now on every request of this call falls back to the old history' % (e, bad))
        assert found(c, '450'), bad


def test_poison_texts_do_not_crash():
    poisons = ['', ' ', '\x00', '\ud800', '😀' * 500, '١٢٣', '１２３', '5' * 5000, '-' * 5000, ('слово ' * 100000), '\n\n\n', '<script>', '%s%d{}', 'NEAR(', '"' * 100]
    led = feed(ConversationLedger(), rows_of(extra=corrections()))
    for i, p in enumerate(poisons):
        led.user_final('p%d' % i, p, final_rev=1, at=2000.0 + i)
        led.answer('pa%d' % i, p, tid='p%d' % i, at=2001.0 + i)
    c = V.build_card(led, 'какая цена за штуку', since=0.0, pinned=poisons[:3], carry='\n'.join(poisons[:5]))
    assert c.chars <= V.START['chars'] and found(c, '450')


@pytest.mark.parametrize('question', ['', ' ', '\x00', '\ud800', '😀' * 10, 'цена ' * 50000, '"' * 100000], ids=['empty', 'space', 'nul', 'surrogate', 'emoji', 'long-words', 'quotes'])
def test_poison_questions(question):
    t = time.perf_counter()
    c = card(rows_of(extra=corrections()), question)
    assert c.chars <= V.START['chars'] and time.perf_counter() - t < 5


# ---------------------------------------------------------------- growth over 180 minutes

def realistic_call(n=4000, minutes=180, seed=11, words=1500, answered=4):
    rng = random.Random(seed)
    vocab = [''.join(rng.choice('абвгдежзиклмнопрстуфхцчшэюя') + rng.choice('аеиоуы') for _ in range(rng.randint(2, 4))) for _ in range(words)]
    rows, led = [], ConversationLedger()
    for i in range(n):
        t = i * minutes * 60.0 / n
        text = ' '.join(rng.choice(vocab) for _ in range(rng.randint(5, 14)))
        if i == 100:
            text = COND
        if i in (1500, 2500):
            text = 'цена за штуку %d рублей' % (500 - i // 100)
        led.user_final('t%d' % i, text, final_rev=1, at=t)
        if i % answered == 0:
            led.answer('a%d' % i, ' '.join(rng.choice(vocab) for _ in range(rng.randint(3, 9))), tid='t%d' % i, at=t + 1.5)
    return led


def test_growth_a_call_of_180_minutes_with_4000_utterances_time_and_memory():
    led = realistic_call()
    proj = V.Projection(led)
    t = time.perf_counter()
    c = V.build_card(led, 'какая скидка по условию про заказ', since=0.0, projection=proj)
    cold = time.perf_counter() - t
    assert found(c, 'пять процентов')
    times = []
    for k in range(30):
        led.user_final('n%d' % k, 'новая реплика про цену за штуку %d' % k, final_rev=1, at=10800.0 + 3 * k)
        led.answer('na%d' % k, 'ответ', tid='n%d' % k, at=10801.0 + 3 * k)
        t = time.perf_counter()
        V.build_card(led, 'какая цена за штуку', since=0.0, projection=proj)
        times.append(time.perf_counter() - t)
    tracemalloc.start()
    V.build_card(led, 'какая цена за штуку', since=0.0, projection=V.Projection(led))
    peak = tracemalloc.get_traced_memory()[1] / 1e6
    tracemalloc.stop()
    mean = sum(times) / len(times)
    print('cold %.3f mean-per-request %.3f max %.3f peak %.1f MB records %d' % (cold, mean, max(times), peak, len(led)))
    assert cold < V.BOUNDS['cold_s'] and max(times) < V.BOUNDS['warm_s'] and peak < V.BOUNDS['peak_mb']
    assert mean < 0.15, 'every new final rebuilds the whole projection: %.3f s per request at 3000 finals (an N95 is several times slower)' % mean


@pytest.mark.xfail(strict=True, reason='known limit of the ledger (LEDGER_HOT=6000): 4000 finals, each answered, are 8000 records; the first 2000 fall off and the minute-5 condition is gone from the memory')
def test_limit_growth_every_utterance_answered_loses_the_early_condition():
    c = V.build_card(realistic_call(answered=1), 'какая скидка по условию про заказ', since=0.0)
    assert found(c, 'пять процентов')


def test_growth_time_of_a_request_does_not_grow_faster_than_the_call():
    def per_request(n):
        led = realistic_call(n=n, minutes=n * 180 // 4000)
        proj = V.Projection(led)
        V.build_card(led, 'цена', since=0.0, projection=proj)
        ts = []
        for k in range(8):
            led.user_final('n%d' % k, 'новая реплика про цену %d' % k, final_rev=1, at=1e5 + k)
            t = time.perf_counter()
            V.build_card(led, 'какая цена за штуку', since=0.0, projection=proj)
            ts.append(time.perf_counter() - t)
        return sum(ts) / len(ts)
    small, big = per_request(500), per_request(3000)
    assert big < small * 6 * 2.0, (small, big)


def test_growth_the_card_size_does_not_depend_on_the_call_length():
    sizes = [card(rows_of(minutes=m), Q).chars for m in (10, 60, 180)]
    assert max(sizes) <= V.START['chars']


def test_growth_the_projection_cache_does_not_keep_dead_rows():
    led = ConversationLedger(hot=200)
    proj = V.Projection(led)
    for i in range(3000):
        led.user_final('t%d' % i, 'слово%d другое%d третье%d' % (i, i, i), final_rev=1, at=float(i))
        if i % 100 == 0:
            V.build_card(led, 'слово', since=0.0, projection=proj)
    V.build_card(led, 'слово', since=0.0, projection=proj)
    assert proj.size() <= 200 and len(proj._cache) <= 200 and len(proj._inv) <= 3 * 200 + 5


# ---------------------------------------------------------------- restart in the middle of a call

def disk(tmp_path, **kw):
    return ConversationLedger(directory=tmp_path / 'conversation', **kw)


@pytest.mark.parametrize('restarts', [1, 2, 3])
def test_a_restart_in_the_middle_of_a_call_disk_ledger_same_card(tmp_path, restarts):
    rows = rows_of(extra=corrections())
    half = len(rows) // 2
    led = feed(disk(tmp_path), rows[:half])
    for _ in range(restarts):
        led = disk(tmp_path)
    feed2 = ConversationLedger()
    feed(feed2, rows[:half])
    assert V.build_card(led, Q, since=0.0).text == V.build_card(feed2, Q, since=0.0).text


def test_a_restart_then_duplicate_delivery_of_the_same_finals(tmp_path):
    rows = rows_of(extra=corrections())
    feed(disk(tmp_path), rows)
    led = disk(tmp_path)
    before = V.build_card(led, 'какая цена за штуку', since=0.0).text
    feed(led, rows)       # the provider re-sends everything after the restart
    assert V.build_card(led, 'какая цена за штуку', since=0.0).text == before
    assert len(disk(tmp_path)) == len(led)


def test_a_restart_with_a_torn_last_line(tmp_path):
    rows = rows_of(extra=corrections())
    feed(disk(tmp_path), rows)
    f = next((tmp_path / 'conversation').glob('ledger-*.jsonl'))
    f.write_bytes(f.read_bytes() + b'{"k": "user", "tid": "zz", "te')
    c = V.build_card(disk(tmp_path), 'какая цена за штуку', since=0.0)
    assert found(c, '450')


def test_a_restart_of_the_memory_ledger_degrades_to_the_old_request():
    led = ConversationLedger()
    fast, seen, _ = hooked('on', led)
    plain = fast_text(history=HISTORY, carry=CARRY)[0]._start(Q).request
    assert fast._start(Q).request == plain       # a new empty ledger after the restart: the old request, whole


# ---------------------------------------------------------------- the ledger off while v6_memory is on

def test_ledger_missing_on_the_controller_while_mode_on_changes_nothing():
    class Bare:
        call_began = 0.0
    fast, seen = fast_text(history=HISTORY, carry=CARRY)
    memory = V.attach({'v6_memory': 'on'}, Bare())
    fast.card = memory.apply
    assert fast._start(Q).request == fast_text(history=HISTORY, carry=CARRY)[0]._start(Q).request
    assert not [1 for ev, f in seen if ev == 'memory_card_fail']


def test_a_ledger_that_appears_later_is_picked_up():
    c = Controller(None)
    fast, seen = fast_text(history=HISTORY, carry=CARRY)
    memory = V.attach({'v6_memory': 'on'}, c)
    fast.card = memory.apply
    fast._start(Q)
    c.convo = feed(ConversationLedger(), rows_of(extra=corrections()))
    assert 'скидка пять процентов' in fast._start(Q).request['instructions']


def test_the_ledger_object_replaced_gets_a_new_projection():
    c = Controller(feed(ConversationLedger(), rows_of(cond='старое условие про лодку')))
    fast, seen = fast_text()
    memory = V.attach({'v6_memory': 'on'}, c)
    fast.card = memory.apply
    fast._start('что про лодку')
    c.convo = feed(ConversationLedger(), rows_of(cond='новое условие про лодку'))
    ins = fast._start('что про лодку').request['instructions']
    assert 'новое условие' in ins and 'старое условие' not in ins


# ---------------------------------------------------------------- files and network: nothing outside the profile folder

def test_nothing_is_written_anywhere_and_no_network(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    opened, connects = [], []
    real_open, real_connect = builtins.open, sqlite3.connect

    def spy_open(file, mode='r', *a, **k):
        if any(c in mode for c in 'wax+'):
            opened.append(str(file))
        return real_open(file, mode, *a, **k)

    def spy_connect(target, *a, **k):
        connects.append(str(target))
        return real_connect(target, *a, **k)
    monkeypatch.setattr(builtins, 'open', spy_open)
    monkeypatch.setattr(sqlite3, 'connect', spy_connect)
    import socket
    monkeypatch.setattr(socket.socket, 'connect', lambda *a, **k: (_ for _ in ()).throw(AssertionError('network')))
    led = feed(ConversationLedger(), rows_of(extra=corrections()))
    for mode in ('shadow', 'on'):
        hooked(mode, led)[0]._start('какая цена за штуку')
    assert opened == [] and set(connects) <= {':memory:'} and list(tmp_path.iterdir()) == []


def test_the_module_has_no_file_or_network_calls_in_its_source():
    import inspect
    src = inspect.getsource(V)
    for bad in ('open(', 'write_text', 'write_bytes', 'urlopen', 'socket', 'requests', 'subprocess', 'os.system', 'pickle', 'shelve', '.dump('):
        assert bad not in src, bad


# ---------------------------------------------------------------- threads

def test_the_request_is_assembled_on_another_thread_while_the_ledger_is_written():
    led = feed(ConversationLedger(hot=400), rows_of(minutes=30, extra=corrections()))
    proj = V.Projection(led)
    stop, errors, cards = threading.Event(), [], []

    def writer():
        i = 0
        while not stop.is_set():
            led.user_final('w%d' % i, 'цена за штуку %d рублей' % (400 + i % 50), final_rev=1, at=3000.0 + i)
            led.user_final('w%d' % i, 'цена за штуку %d рублей исправлено' % (400 + i % 50), final_rev=2, at=3000.0 + i)
            led.answer('wa%d' % i, 'ок', tid='w%d' % i, at=3000.5 + i)
            i += 1
            time.sleep(0.002)

    def reader():
        for _ in range(40):
            try:
                cards.append(V.build_card(led, 'какая цена за штуку', since=0.0, projection=proj))
            except Exception as e:      # noqa: BLE001
                errors.append(repr(e))
    w = threading.Thread(target=writer)
    rs = [threading.Thread(target=reader) for _ in range(3)]
    w.start()
    [r.start() for r in rs]
    [r.join() for r in rs]
    stop.set()
    w.join()
    assert not errors, errors[:3]
    assert all(c.chars <= V.START['chars'] and c.chars == len(c.text) for c in cards)


def test_two_requests_at_once_through_the_memory_hook_do_not_cross():
    led = feed(ConversationLedger(), rows_of(extra=corrections()))
    memory = V.attach({'v6_memory': 'on'}, Controller(led))
    out, errors = {}, []

    def run(q):
        try:
            for _ in range(30):
                out[q] = memory.apply(fast_text()[0], q, 'POLICY', [])[0]
        except Exception as e:      # noqa: BLE001
            errors.append(repr(e))
    ts = [threading.Thread(target=run, args=(q,)) for q in ('какая цена за штуку', 'что с доставкой', Q)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errors and 'цену доставки' in out['что с доставкой'] and 'скидка пять процентов' in out[Q]
